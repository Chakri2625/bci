"""
Async Task Queue & Lifecycle Engine.
------------------------------------
Provides TaskStatus, AsyncTask, and TaskQueue with background execution,
status tracking, timing, error handling, and cancellation.
"""

from __future__ import annotations

import asyncio
import inspect
from enum import Enum
import logging
import time
from typing import Any, Callable, Dict, Optional, Tuple
import uuid

logger = logging.getLogger("task_queue")


class TaskStatus(str, Enum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class AsyncTask:
    def __init__(
        self,
        target: Any,
        args: tuple = (),
        kwargs: dict = None,
        name: Optional[str] = None,
    ):
        self.id = str(uuid.uuid4())
        self.name = name or f"task_{self.id[:8]}"
        self.target = target
        self.args = args or ()
        self.kwargs = kwargs or {}
        self.status = TaskStatus.QUEUED
        self.result: Any = None
        self.error: Optional[str] = None
        self.created_at: float = time.time()
        self.started_at: Optional[float] = None
        self.completed_at: Optional[float] = None
        self._asyncio_task: Optional[asyncio.Task] = None
        self._cancel_requested: bool = False

    def cancel(self) -> bool:
        self._cancel_requested = True
        if self._asyncio_task and not self._asyncio_task.done():
            self._asyncio_task.cancel()
            self.status = TaskStatus.CANCELLED
            self.completed_at = time.time()
            return True
        elif self.status == TaskStatus.QUEUED:
            self.status = TaskStatus.CANCELLED
            self.completed_at = time.time()
            return True
        return False

    async def execute(self) -> Any:
        if self._cancel_requested:
            self.status = TaskStatus.CANCELLED
            self.completed_at = time.time()
            return {"status": "error", "message": "Task was cancelled"}

        self.status = TaskStatus.RUNNING
        self.started_at = time.time()

        try:
            if inspect.iscoroutinefunction(self.target):
                res = await self.target(*self.args, **self.kwargs)
            elif callable(self.target):
                res = await asyncio.to_thread(self.target, *self.args, **self.kwargs)
            elif inspect.isawaitable(self.target):
                res = await self.target
            else:
                res = self.target

            self.result = res
            self.status = TaskStatus.COMPLETED
            self.completed_at = time.time()
            return res
        except asyncio.CancelledError:
            self.status = TaskStatus.CANCELLED
            self.completed_at = time.time()
            raise
        except Exception as e:
            self.status = TaskStatus.FAILED
            self.error = str(e)
            self.completed_at = time.time()
            logger.error(f"[AsyncTask] Task {self.name} ({self.id}) failed: {e}", exc_info=True)
            return {"status": "error", "message": str(e)}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "status": self.status.value,
            "result": self.result,
            "error": self.error,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "duration_ms": (
                round((self.completed_at - self.started_at) * 1000, 2)
                if self.started_at and self.completed_at
                else None
            ),
        }


class TaskQueue:
    def __init__(self):
        self._queue: asyncio.Queue = asyncio.Queue()
        self._tasks: Dict[str, AsyncTask] = {}
        self._worker_task: Optional[asyncio.Task] = None

    async def enqueue(self, task: Any) -> None:
        if isinstance(task, AsyncTask):
            self._tasks[task.id] = task
            await self._queue.put(task)
        elif isinstance(task, dict):
            task_id = task.get("task_id") or task.get("id") or str(uuid.uuid4())
            self._tasks[task_id] = task
            await self._queue.put(task)
        else:
            await self._queue.put(task)

    async def dequeue(self) -> Any:
        return await self._queue.get()

    def submit_background(
        self,
        target: Any,
        *args,
        name: Optional[str] = None,
        **kwargs,
    ) -> AsyncTask:
        task = AsyncTask(target=target, args=args, kwargs=kwargs, name=name)
        self._tasks[task.id] = task

        async def _run():
            await task.execute()

        try:
            loop = asyncio.get_running_loop()
            task._asyncio_task = loop.create_task(_run(), name=task.name)
        except RuntimeError:
            pass

        return task

    def get_task(self, task_id: str) -> Optional[Dict[str, Any]]:
        task = self._tasks.get(task_id)
        if not task:
            return None
        if hasattr(task, "to_dict"):
            return task.to_dict()
        if isinstance(task, dict):
            return dict(task)
        return {"task": str(task)}

    def clear(self) -> None:
        while not self._queue.empty():
            try:
                self._queue.get_nowait()
                self._queue.task_done()
            except Exception:
                break
        self._tasks.clear()

    def qsize(self) -> int:
        return self._queue.qsize()

    def list_tasks(self, limit: int = 100) -> list[Dict[str, Any]]:
        result = []
        for t in list(self._tasks.values())[:limit]:
            if hasattr(t, "to_dict"):
                result.append(t.to_dict())
            elif isinstance(t, dict):
                result.append(dict(t))
            else:
                result.append({"task": str(t)})
        return result

    def cancel_task(self, task_id: str) -> bool:
        task = self._tasks.get(task_id)
        if task:
            return task.cancel()
        return False

    async def worker(self) -> None:
        while True:
            task = await self.dequeue()
            if isinstance(task, AsyncTask):
                await task.execute()
            self._queue.task_done()


task_queue = TaskQueue()
