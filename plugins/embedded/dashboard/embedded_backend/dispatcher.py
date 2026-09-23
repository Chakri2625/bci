from enum import Enum
from .protocol import ProtocolPacket
from .device_registry import (
    devices,
    CommandTarget
)


class CommandSource(Enum):

    CLI = 0
    DASHBOARD = 1
    PLAYBACK = 2
    BCI = 3


class Dispatcher:

    def __init__(self, mqtt_client):

        self.mqtt = mqtt_client

    # -------------------------------------------------------
    # PRIVATE
    # -------------------------------------------------------

    def _publish_to_device(
        self,
        target: CommandTarget,
        domain: str,
        command):

        topic = devices[target.value]["topic_cmd"]

        print(
            f"[Dispatcher] "
            f"{target.name} <- "
            f"{domain}:{command}"
        )

        packet = ProtocolPacket(
            domain=domain,
            device=target.name,
            command=command
        )

        payload = packet.encode()

        print("----------------------------------------")
        print("[Dispatcher]")
        print(f"Topic   : {topic}")
        print(f"Payload : {payload}")
        print("----------------------------------------")

        self.mqtt.publish(
            topic,
            payload
        )
    # -------------------------------------------------------
    # PUBLIC
    # -------------------------------------------------------

    def dispatch(
        self,
        source: CommandSource,
        target: CommandTarget,
        domain: str,
        command: str):

        print()

        print(
            f"[{source.name}] "
            f"{target.name} -> {command}"
        )

        print()

        if target == CommandTarget.CHAIR:

            self._publish_to_device(
                CommandTarget.CHAIR,
                domain,
                command
            )

        elif target == CommandTarget.CAR:

            self._publish_to_device(
                CommandTarget.CAR,
                domain,
                command
            )

        elif target == CommandTarget.ALL:

            self._publish_to_device(
                CommandTarget.CHAIR,
                domain,
                command
            )

            self._publish_to_device(
                CommandTarget.CAR,
                domain,
                command
            )

        else:

            print("[Dispatcher] Unknown Target")