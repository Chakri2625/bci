import uuid
import logging
from typing import Dict, List, Any, Optional

from core.managers.async_task_manager import async_task_manager

logger = logging.getLogger("command_group_manager")

class CommandGroupManager:
    def __init__(self):
        # Format: { group_id: {"task_ids": [...], "status": "PENDING"|"RUNNING"|"COMPLETED"} }
        self._groups: Dict[str, Dict[str, Any]] = {}

    def create_group(self, group_id: Optional[str] = None) -> str:
        """Initializes a new command group and returns its ID."""
        if not group_id:
            group_id = str(uuid.uuid4())
            
        self._groups[group_id] = {
            "task_ids": [],
            "status": "PENDING"
        }
        logger.debug(f"[CommandGroupManager] Group {group_id} created.")
        return group_id

    def add_to_group(self, group_id: str, coro) -> Optional[str]:
        """Submits an async task to the group via AsyncTaskManager."""
        if group_id not in self._groups:
            logger.error(f"[CommandGroupManager] Group {group_id} not found.")
            return None
            
        task_id = async_task_manager.submit(coro)
        self._groups[group_id]["task_ids"].append(task_id)
        self._groups[group_id]["status"] = "RUNNING"
        return task_id

    def add_tasks_to_group(self, group_id: str, coros: List[Any]) -> List[str]:
        """Submits multiple async tasks to the group."""
        task_ids = []
        for coro in coros:
            tid = self.add_to_group(group_id, coro)
            if tid:
                task_ids.append(tid)
        return task_ids

    def get_group_status(self, group_id: str) -> Optional[Dict[str, Any]]:
        """Returns the overall status of the group."""
        if group_id not in self._groups:
            return None
            
        task_ids = self._groups[group_id]["task_ids"]
        if not task_ids:
            return {
                "group_id": group_id,
                "status": self._groups[group_id]["status"],
                "total": 0,
                "completed": 0,
                "successful": 0,
                "failed": 0,
                "is_finished": True,
                "results": []
            }
            
        completed = 0
        successful = 0
        failed = 0
        results = []
        
        for tid in task_ids:
            status_info = async_task_manager.get_status(tid)
            if not status_info:
                # If a task was cleaned up or lost, we might consider it failed/lost
                failed += 1
                completed += 1
                continue
                
            task_status = status_info["status"]
            if task_status in ["SUCCESS", "FAILED", "CANCELLED"]:
                completed += 1
                if task_status == "SUCCESS":
                    successful += 1
                else:
                    failed += 1
            
            results.append({
                "task_id": tid,
                "status": task_status,
                "result": status_info["result"],
                "error": status_info["error"]
            })
            
        is_finished = (completed == len(task_ids))
        if is_finished:
            self._groups[group_id]["status"] = "COMPLETED"
            
        return {
            "group_id": group_id,
            "status": self._groups[group_id]["status"],
            "total": len(task_ids),
            "completed": completed,
            "successful": successful,
            "failed": failed,
            "is_finished": is_finished,
            "results": results
        }

    async def wait_for_group(self, group_id: str) -> Optional[Dict[str, Any]]:
        """Awaits the completion of all commands within the group."""
        if group_id not in self._groups:
            return None
            
        task_ids = self._groups[group_id]["task_ids"]
        await async_task_manager.wait_for_tasks(task_ids)
        return self.get_group_status(group_id)

    def cancel_group(self, group_id: str) -> bool:
        """Cancels all commands in the group."""
        if group_id not in self._groups:
            return False
            
        task_ids = self._groups[group_id]["task_ids"]
        for tid in task_ids:
            async_task_manager.cancel(tid)
            
        self._groups[group_id]["status"] = "COMPLETED"
        return True
        
    def cleanup_group(self, group_id: str) -> bool:
        """Removes the group tracking. Does not clean up AsyncTaskManager tasks automatically."""
        if group_id in self._groups:
            del self._groups[group_id]
            return True
        return False

command_group_manager = CommandGroupManager()
