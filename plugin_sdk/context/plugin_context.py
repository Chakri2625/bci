from core.logging.logger import logger
from core.events.event_bus import event_bus
from core.state.state_manager import state_manager
from core.queue.task_queue import task_queue

class PluginContext:
    def __init__(self):
        self.logger = logger
        self.event_bus = event_bus
        self.state_manager = state_manager
        self.task_queue = task_queue
        self.services = {}
