from core.logging.structured_logger import structured_logger
import logging
import os

# Ensure the logs directory exists
log_dir = os.path.join("data", "logs")
os.makedirs(log_dir, exist_ok=True)
log_file = os.path.join(log_dir, "navigation.log")

# Configure logging to write to both file and console
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(log_file),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger("synaptimesh")


def log_navigation(command: str, current_domain: str, target_domain: str, status: str, error: str = None):
    log_msg = f"[Navigation] command={command.lower()}\n"
    log_msg += f"[current_domain={current_domain if current_domain else 'domain_selection'}]\n"
    log_msg += f"[target_domain={target_domain if target_domain else 'domain_selection'}]\n"
    log_msg += f"[status={status}]"
    if error:
        log_msg += f"\n[error={error}]"
    
    for line in log_msg.split('\n'):
        logger.info(line)
