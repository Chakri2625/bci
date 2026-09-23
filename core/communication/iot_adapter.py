import time
import logging
from typing import Dict, Any, Optional
from core.plugin_manager.manager import execute

logger = logging.getLogger("iot_adapter")

class IoTSyncAdapter:
    """
    Adapter to synchronize outbound navigation commands with the IoT plugin.
    Accepts already-validated navigation commands from the queue flow
    and sends them to the IoT layer using the existing public interface.
    """
    
    @staticmethod
    async def dispatch_command(
        command_id: str,
        action: str,
        device_id: str,
        direction: Optional[str] = None,
        priority: int = 1,
        timestamp: Optional[float] = None,
        **metadata
    ) -> Dict[str, Any]:
        """
        Sends a validated navigation command to the IoT plugin.
        Returns a normalized result suitable for queue/processor to use.
        """
        if not action or not device_id:
            return {
                "success": False,
                "status": "failed",
                "error": "malformed outbound data: missing action or device_id",
                "command_id": command_id
            }
            
        payload = {
            "command_id": command_id,
            "action": action,
            "device_id": device_id,
            "direction": direction,
            "priority": priority,
            "timestamp": timestamp or time.time(),
            **metadata
        }
        
        try:
            # Send to the existing IoT layer through its current public interface
            result = await execute("iot", action, payload)
            
            if not result:
                return {
                    "success": False,
                    "status": "failed",
                    "error": "no response from IoT plugin",
                    "command_id": command_id
                }
                
            return {
                "success": result.get("status") == "success",
                "status": result.get("status", "unknown"),
                "error": result.get("error") or result.get("message"),
                "command_id": command_id,
                "raw_response": result
            }
            
        except Exception as e:
            logger.error(f"Failed to dispatch command {command_id} to IoT: {e}")
            return {
                "success": False,
                "status": "failed",
                "error": f"IoT transport failure: {str(e)}",
                "command_id": command_id
            }

iot_adapter = IoTSyncAdapter()
