import asyncio
import logging
import threading
import time
import uuid
from typing import Dict, Any, Tuple, Optional
from core.queue.task_queue import task_queue, TaskQueue

logger = logging.getLogger("RequestIntake")

class RequestIntake:
    """
    Thread-safe and concurrency-safe request intake layer for SynaptiMesh.
    Validates incoming API requests, assigns unique task identifiers,
    and safely forwards them to the underlying execution TaskQueue.
    
    Decouples request ingestion from task execution.
    """
    def __init__(self, queue: TaskQueue = task_queue):
        self.queue = queue
        self._lock = threading.Lock()
        self._async_lock = asyncio.Lock()
        self.total_received = 0
        self.total_accepted = 0
        self.total_rejected = 0

    def validate_request(self, request_type: str, payload: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
        """
        Validates request structure and payload before queue ingestion.
        """
        if not isinstance(payload, dict):
            return False, "Payload must be a valid JSON dictionary"

        if request_type == "automation":
            domain = payload.get("domain")
            plugin = payload.get("plugin")
            commands = payload.get("commands")

            if not domain or not isinstance(domain, str):
                return False, "Missing or invalid 'domain' in automation payload"
            if not plugin or not isinstance(plugin, str):
                return False, "Missing or invalid 'plugin' in automation payload"
            if commands is None or not isinstance(commands, list):
                return False, "Missing or invalid 'commands' list in automation payload"
            if len(commands) == 0:
                return False, "'commands' list cannot be empty"

        elif request_type == "bci_command":
            command = payload.get("command")
            if not command or not isinstance(command, str):
                return False, "Missing or invalid 'command' in BCI payload"

        return True, None

    async def accept_request(
        self,
        request_type: str,
        payload: Dict[str, Any],
        session: str = "default",
        custom_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Asynchronously accepts and validates concurrent requests in a thread-safe manner.
        Places valid tasks onto the task queue without directly executing them.
        """
        with self._lock:
            self.total_received += 1

        # 1. Validation phase
        is_valid, error_msg = self.validate_request(request_type, payload)
        if not is_valid:
            with self._lock:
                self.total_rejected += 1
            logger.warning(f"[Intake] Rejected {request_type} request: {error_msg}")
            return {
                "status": "rejected",
                "error": error_msg,
                "task_id": None,
                "timestamp": time.time()
            }

        # 2. Unique task ID generation
        task_id = custom_id or f"req_{int(time.time()*1000)}_{uuid.uuid4().hex[:8]}"

        task_record = {
            "task_id": task_id,
            "request_type": request_type,
            "payload": payload,
            "session": session,
            "timestamp": time.time(),
            "status": "QUEUED"
        }

        # 3. Thread-safe handoff to task queue
        async with self._async_lock:
            await self.queue.enqueue(task_record)
            with self._lock:
                self.total_accepted += 1

        logger.info(f"[Intake] Successfully queued request {task_id} ({request_type}) for session {session}")

        return {
            "status": "started",
            "task_id": task_id,
            "queue_size": self.queue.qsize(),
            "timestamp": task_record["timestamp"]
        }

    def get_metrics(self) -> Dict[str, Any]:
        """
        Returns thread-safe snapshot of request intake metrics.
        """
        with self._lock:
            return {
                "total_received": self.total_received,
                "total_accepted": self.total_accepted,
                "total_rejected": self.total_rejected,
                "current_queue_size": self.queue.qsize()
            }

request_intake = RequestIntake()
