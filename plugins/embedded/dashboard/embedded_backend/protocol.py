class ProtocolPacket:

    def __init__(
            self,
            domain: str,
            device: str,
            command: str):

        self.domain = domain.upper().strip()
        self.device = device.upper().strip()
        self.command = command.upper().strip()

    def encode(self):

        return (
            self.domain +
            self.device +
            self.command
        )

    def __str__(self):

        return self.encode()