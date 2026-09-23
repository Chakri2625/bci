class BasePlugin:
    plugin_id = "base"
    
    def initialize(self, context):
        pass
        
    async def execute(self, command, payload=None):
        raise NotImplementedError
        
    def shutdown(self):
        pass
