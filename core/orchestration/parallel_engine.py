import asyncio
import logging
from typing import List, Dict, Any
from core.managers.async_task_manager import async_task_manager

logger = logging.getLogger("parallel_engine")

class ParallelExecutionEngine:
    async def execute_concurrently(self, executables: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Executes a list of already-validated commands concurrently.
        
        executables is a list of dicts, each containing:
        - cmd: original command string
        - resolution: the resolved command dictionary
        - payload: payload for plugin
        - execute_func: async callable to perform the action
        - is_direct_await: bool (if True, await. if False, we can still gather them)
        - base_result: the baseline result dict to append action_result to
        """
        
        safe_to_execute = []
        conflicts = []
        
        # Keep track of specific actions targeted at resources
        targeted_actions = {}
        targeted_resources = set()
        
        
        # Define mutually exclusive command sets for specific apps
        mutually_exclusive_sets = {
            ("EMBEDDED", "RC_CAR"): {"FORWARD", "BACKWARD", "LEFT", "RIGHT", "STOP"},
            ("IOT", "LIGHT"): {"Left_light_on", "Left_light_off"},
            ("IOT", "FAN"): {"Left_fan_on", "Left_fan_off"},
            ("IOT", "PUMP"): {"Left_pump_on", "Left_pump_off"},
            ("DESKTOP_MEDIA", "YOUTUBE"): {"previous_video", "next_video", "toggle_play_pause", "search", "PREVIOUS", "NEXT", "PUSH", "PULL", "LEFT", "RIGHT"},
            ("DESKTOP_MEDIA", "JIOSAAVN"): {"previous_track", "next_track", "toggle_play_pause", "search", "PREVIOUS", "NEXT", "PUSH", "PULL", "LEFT", "RIGHT"},
        }
        
        for item in executables:
            res = item["resolution"]
            if res.get("type") == "action":
                domain = res.get("domain")
                app = res.get("app")
                device_id = item.get("payload", {}).get("device_id")
                action = res.get("action")
                
                norm_domain = "DESKTOP_MEDIA" if domain in ("PYTHON", "DESKTOP", "MEDIA") and app in ("YOUTUBE", "JIOSAAVN", "CHROME", "NOTEPAD", "GMAIL") else domain
                resource_key = (norm_domain, app, device_id)
                
                # Determine if this action conflicts with already targeted actions for this resource
                conflict = False
                if resource_key in targeted_actions:
                    existing_actions = targeted_actions[resource_key]
                    mutex_set = mutually_exclusive_sets.get((norm_domain, app)) or mutually_exclusive_sets.get((domain, app))
                    
                    if mutex_set and action in mutex_set:
                        # Check if any existing action is in the same mutually exclusive set, but different from this action
                        if any(ea in mutex_set and ea != action for ea in existing_actions):
                            conflict = True
                            item["conflict"] = f"Conflict: Mutually exclusive action already targeted for {resource_key}"
                            conflicts.append(item)
                
                if not conflict:
                    if resource_key not in targeted_actions:
                        targeted_actions[resource_key] = set()
                    targeted_actions[resource_key].add(action)
                    safe_to_execute.append(item)
                    
            elif res.get("type") in ["navigate_back", "navigate_home", "transition"]:
                resource_key = ("navigation",)
                if resource_key in targeted_resources:
                    item["conflict"] = "Conflict: Multiple navigation commands"
                    conflicts.append(item)
                else:
                    targeted_resources.add(resource_key)
                    safe_to_execute.append(item)
            else:
                safe_to_execute.append(item)
                
        results = []
        task_id_to_item = {}
        
        for item in safe_to_execute:
            if item.get("execute_func"):
                task_id = async_task_manager.submit(item["execute_func"]())
                task_id_to_item[task_id] = item
            else:
                if item.get("status") != "FAILED":
                    item["status"] = "SUCCESS"
                item["action_res"] = None
                results.append(item)
                
        if task_id_to_item:
            task_ids = list(task_id_to_item.keys())
            statuses = await async_task_manager.wait_for_tasks(task_ids)
            
            for task_id, status_info in zip(task_ids, statuses):
                item = task_id_to_item[task_id]
                if status_info:
                    item["status"] = status_info["status"]
                    if status_info["status"] == "SUCCESS":
                        item["action_res"] = status_info["result"]
                    else:
                        item["error"] = status_info["error"]
                else:
                    item["status"] = "FAILED"
                    item["error"] = "Task tracking lost"
                results.append(item)
                    
        for item in conflicts:
            item["status"] = "FAILED"
            item["error"] = item["conflict"]
            results.append(item)
            
        return results

parallel_engine = ParallelExecutionEngine()
