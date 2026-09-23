import asyncio
import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List, Tuple

logger = logging.getLogger("async_task_manager")

class AsyncTaskManager:
    def __init__(self):
        self._tasks: Dict[str, Dict[str, Any]] = {}
        # Format: { task_id: {"status": "...", "result": ..., "error": ..., "task": asyncio.Task, ...} }

    def submit(self, coro, task_id: Optional[str] = None) -> str:
        """Submits a coroutine for execution and returns a task_id."""
        if not task_id:
            task_id = str(uuid.uuid4())

        start_ts = time.time()
        start_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
            
        self._tasks[task_id] = {
            "status": "PENDING",
            "result": None,
            "error": None,
            "task": None,
            "start_time": start_iso,
            "completion_time": None,
            "duration_seconds": None,
            "_start_ts": start_ts
        }
        
        # Wrap the coroutine to handle status updates and errors
        wrapped_coro = self._wrapper(task_id, coro)
        task = asyncio.create_task(wrapped_coro, name=task_id)
        
        self._tasks[task_id]["task"] = task
        logger.debug(f"[AsyncTaskManager] Task {task_id} submitted.")
        return task_id

    async def _wrapper(self, task_id: str, coro):
        """Internal wrapper to execute the coroutine and track its state."""
        self._tasks[task_id]["status"] = "RUNNING"
        try:
            result = await coro
            comp_ts = time.time()
            comp_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
            self._tasks[task_id]["status"] = "SUCCESS"
            self._tasks[task_id]["result"] = result
            self._tasks[task_id]["completion_time"] = comp_iso
            self._tasks[task_id]["duration_seconds"] = max(0.0, round(comp_ts - self._tasks[task_id]["_start_ts"], 3))
            return result
        except asyncio.CancelledError:
            comp_ts = time.time()
            comp_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
            self._tasks[task_id]["status"] = "CANCELLED"
            self._tasks[task_id]["error"] = "Task was cancelled"
            self._tasks[task_id]["completion_time"] = comp_iso
            self._tasks[task_id]["duration_seconds"] = max(0.0, round(comp_ts - self._tasks[task_id]["_start_ts"], 3))
            raise
        except Exception as e:
            comp_ts = time.time()
            comp_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
            self._tasks[task_id]["status"] = "FAILED"
            self._tasks[task_id]["error"] = str(e)
            self._tasks[task_id]["completion_time"] = comp_iso
            self._tasks[task_id]["duration_seconds"] = max(0.0, round(comp_ts - self._tasks[task_id]["_start_ts"], 3))
            logger.error(f"[AsyncTaskManager] Task {task_id} failed: {e}", exc_info=True)
            return e # Returning exception instead of re-raising, so gather doesn't crash unless intended

    def get_status(self, task_id: str) -> Optional[Dict[str, Any]]:
        """Returns the current state and result of a task."""
        if task_id not in self._tasks:
            return None
            
        t = self._tasks[task_id]
        return {
            "status": t["status"],
            "result": t["result"],
            "error": t["error"],
            "start_time": t.get("start_time"),
            "completion_time": t.get("completion_time"),
            "duration_seconds": t.get("duration_seconds")
        }

    def cancel(self, task_id: str) -> bool:
        """Cancels a task if it exists and is not already done."""
        if task_id in self._tasks:
            task = self._tasks[task_id]["task"]
            comp_ts = time.time()
            comp_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
            if task and not task.done():
                task.cancel()
            self._tasks[task_id]["status"] = "CANCELLED"
            self._tasks[task_id]["error"] = "Task was cancelled"
            self._tasks[task_id]["completion_time"] = comp_iso
            self._tasks[task_id]["duration_seconds"] = max(0.0, round(comp_ts - self._tasks[task_id]["_start_ts"], 3))
            logger.debug(f"[AsyncTaskManager] Task {task_id} cancelled.")
            return True
        return False

    def cleanup(self, task_id: str) -> bool:
        """Removes a completed task from tracking."""
        if task_id in self._tasks:
            status = self._tasks[task_id]["status"]
            if status in ["SUCCESS", "FAILED", "CANCELLED"]:
                del self._tasks[task_id]
                return True
        return False
        
    def cleanup_completed(self):
        """Removes all completed tasks from tracking."""
        completed_ids = [
            tid for tid, info in self._tasks.items() 
            if info["status"] in ["SUCCESS", "FAILED", "CANCELLED"]
        ]
        for tid in completed_ids:
            del self._tasks[tid]

    async def wait_for_tasks(self, task_ids: List[str]) -> List[Dict[str, Any]]:
        """Awaits specific tasks and returns their final statuses."""
        tasks_to_await = []
        for tid in task_ids:
            if tid in self._tasks and self._tasks[tid]["task"]:
                tasks_to_await.append(self._tasks[tid]["task"])
                
        if tasks_to_await:
            # We use return_exceptions=True so that one failure doesn't stop gathering the rest
            await asyncio.gather(*tasks_to_await, return_exceptions=True)
            
        return [self.get_status(tid) for tid in task_ids if tid in self._tasks]

async_task_manager = AsyncTaskManager()
