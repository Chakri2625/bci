from abc import ABC, abstractmethod

class CommandSource(ABC):
    @abstractmethod
    def get_command(self):
        pass

class ManualDashboardSource(CommandSource):
    def get_command(self):
        # In a real event loop this would wait for a command,
        # but in our API-driven design, the API acts as the receiver.
        pass

class MLServerSource(CommandSource):
    def get_command(self):
        pass
