import logging

logger = logging.getLogger("uart_protocol")

class CommandProtocol:
    @staticmethod
    def format_command(command: str) -> str:
        """Format a command to send over UART."""
        return f"CMD|{command}\n"

    @staticmethod
    def format_ack(command: str, status: str) -> str:
        """Format an ACK to send over UART."""
        return f"ACK|{command}|{status}\n"

    @staticmethod
    def parse_message(message: str) -> dict:
        """Parse an incoming UART message."""
        message = message.strip()
        parts = message.split("|")
        
        if not parts:
            return {"type": "UNKNOWN"}
            
        msg_type = parts[0]
        
        if msg_type == "CMD" and len(parts) >= 2:
            return {
                "type": "CMD",
                "command": parts[1]
            }
        elif msg_type == "ACK" and len(parts) >= 3:
            return {
                "type": "ACK",
                "command": parts[1],
                "status": parts[2]
            }
            
        return {"type": "INVALID", "raw": message}
