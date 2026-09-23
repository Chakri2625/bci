import asyncio
import time
import uuid
import logging
from enum import Enum
from typing import Optional, Any, List, Dict
from pydantic import BaseModel, Field

from core.logging.logger import logger, log_navigation
from core.state.state_manager import state_manager

class CommandLifecycleState(str, Enum):
    QUEUED = "QUEUED"
    EXECUTING = "EXECUTING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    TIMEOUT = "TIMEOUT"

class QueuedCommand(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    command: str
    session: str = "default"
    status: CommandLifecycleState = CommandLifecycleState.QUEUED
    payload: Optional[Dict[str, Any]] = None
    created_at: float = Field(default_factory=time.time)
    started_at: Optional[float] = None
    completed_at: Optional[float] = None
    start_time: Optional[str] = None
    completion_time: Optional[str] = None
    duration_seconds: Optional[float] = None
    result: Optional[Any] = None
    error: Optional[str] = None

class SequentialProcessor:
    def __init__(self):
        self.queue: asyncio.Queue[QueuedCommand] = asyncio.Queue()
        self.active_command: Optional[QueuedCommand] = None
        self.history: List[QueuedCommand] = []
        self.is_running: bool = False
        self._lock = asyncio.Lock()
        self._worker_task: Optional[asyncio.Task] = None

    def start(self):
        """Start the Sequential Processor loop."""
        if not self.is_running:
            self.is_running = True
            logger.info("[SequentialProcessor] Processor started")
            state_manager.update_state("default", {"processor_state": "RUNNING"})
            try:
                loop = asyncio.get_running_loop()
                if self._worker_task is None or self._worker_task.done():
                    self._worker_task = loop.create_task(self._process_loop())
            except RuntimeError:
                pass

    def stop(self):
        """Stop/pause the Sequential Processor."""
        self.is_running = False
        logger.info("[SequentialProcessor] Processor stopped")
        state_manager.update_state("default", {"processor_state": "STOPPED"})
        if self._worker_task and not self._worker_task.done():
            self._worker_task.cancel()
            self._worker_task = None

    async def enqueue(self, command: str, session: str = "default", payload: Optional[Dict[str, Any]] = None) -> QueuedCommand:
        """Enqueue a command into the sequential queue."""
        cmd_obj = QueuedCommand(
            command=command.upper(),
            session=session,
            payload=payload,
            status=CommandLifecycleState.QUEUED,
            created_at=time.time()
        )
        await self.queue.put(cmd_obj)
        logger.info(f"[SequentialProcessor] Command fetched/enqueued: id={cmd_obj.id}, command={cmd_obj.command}")
        
        state_manager.update_state(session, {
            "queue_length": self.queue.qsize(),
            "active_command": cmd_obj.command,
            "processor_state": CommandLifecycleState.QUEUED.value if not self.is_running else "RUNNING"
        })
        
        if self.is_running:
            try:
                loop = asyncio.get_running_loop()
                if self._worker_task is None or self._worker_task.done():
                    self._worker_task = loop.create_task(self._process_loop())
            except RuntimeError:
                pass

        return cmd_obj

    async def process_next(self) -> Optional[QueuedCommand]:
        """Fetch and execute the next command from the queue."""
        if self.queue.empty():
            return None

        cmd_obj = await self.queue.get()
        result = await self.execute_command(cmd_obj)
        self.queue.task_done()
        return result

    async def execute_command(self, cmd_obj: QueuedCommand) -> QueuedCommand:
        """
        Execute a single command safely inside an async lock so no second command
        can execute while this command is active.
        """
        async with self._lock:
            from core.navigation.controller import navigation_controller
            
            from core.logging.timestamp_tracker import get_timestamp_tracker
            tracker = get_timestamp_tracker()
            rec = tracker.record_start(cmd_obj.id, cmd_obj.session, cmd_obj.command)
            cmd_obj.start_time = rec.get("start_time") if isinstance(rec, dict) else time.strftime("%Y-%m-%dT%H:%M:%S")

            cmd_obj.started_at = time.time()
            cmd_obj.status = CommandLifecycleState.EXECUTING
            self.active_command = cmd_obj
            
            logger.info(f"[SequentialProcessor] Command started: id={cmd_obj.id}, command={cmd_obj.command}")
            
            state_manager.update_state(cmd_obj.session, {
                "processor_state": CommandLifecycleState.EXECUTING.value,
                "active_command": cmd_obj.command,
                "queue_length": self.queue.qsize()
            })
            
            try:
                from core.navigation.models import NavigationRequest
                response = await navigation_controller.handle_raw_command(
                    NavigationRequest(command=cmd_obj.command),
                    session=cmd_obj.session
                )
                
                cmd_obj.completed_at = time.time()
                cmd_obj.result = response
                
                if response.status == "failed":
                    cmd_obj.status = CommandLifecycleState.FAILED
                    cmd_obj.error = response.error or "Execution failed"
                    comp_rec = tracker.record_failure(
                        command_id=cmd_obj.id,
                        session_id=cmd_obj.session,
                        command=cmd_obj.command,
                        error=cmd_obj.error,
                    )
                    logger.info(f"[SequentialProcessor] Command failed: id={cmd_obj.id}, error={cmd_obj.error}")
                else:
                    cmd_obj.status = CommandLifecycleState.COMPLETED
                    comp_rec = tracker.record_completion(cmd_obj.id)
                    logger.info(f"[SequentialProcessor] Command completed: id={cmd_obj.id}, status=COMPLETED")
                
                if isinstance(comp_rec, dict):
                    cmd_obj.completion_time = comp_rec.get("completion_time")
                    cmd_obj.duration_seconds = comp_rec.get("duration_seconds")
                else:
                    cmd_obj.completion_time = time.strftime("%Y-%m-%dT%H:%M:%S")
                    cmd_obj.duration_seconds = round(cmd_obj.completed_at - cmd_obj.started_at, 4)
                    
            except Exception as e:
                cmd_obj.completed_at = time.time()
                cmd_obj.status = CommandLifecycleState.FAILED
                cmd_obj.error = str(e)
                comp_rec = tracker.record_failure(
                    command_id=cmd_obj.id,
                    session_id=cmd_obj.session,
                    command=cmd_obj.command,
                    error=str(e),
                )
                if isinstance(comp_rec, dict):
                    cmd_obj.completion_time = comp_rec.get("completion_time")
                    cmd_obj.duration_seconds = comp_rec.get("duration_seconds")
                else:
                    cmd_obj.completion_time = time.strftime("%Y-%m-%dT%H:%M:%S")
                    cmd_obj.duration_seconds = round(cmd_obj.completed_at - cmd_obj.started_at, 4)
                logger.error(f"[SequentialProcessor] Command failed with exception: id={cmd_obj.id}, error={e}")

            self.history.append(cmd_obj)
            if len(self.history) > 50:
                self.history.pop(0)

            self.active_command = None
            
            final_status = cmd_obj.status.value
            if self.is_running and not self.queue.empty():
                final_status = CommandLifecycleState.EXECUTING.value

            state_manager.update_state(cmd_obj.session, {
                "processor_state": final_status,
                "active_command": cmd_obj.command,
                "queue_length": self.queue.qsize()
            })
            
            return cmd_obj

    async def _process_loop(self):
        """Internal processing loop consuming items sequentially."""
        while self.is_running:
            try:
                if not self.queue.empty():
                    await self.process_next()
                else:
                    await asyncio.sleep(0.05)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[SequentialProcessor] Loop error: {e}")
                await asyncio.sleep(0.1)

    def get_status(self) -> Dict[str, Any]:
        return {
            "is_running": self.is_running,
            "active_command": self.active_command.command if self.active_command else (self.history[-1].command if self.history else None),
            "queue_length": self.queue.qsize(),
            "history_count": len(self.history)
        }

sequential_processor = SequentialProcessor()
