from enum import Enum


class CommandTarget(Enum):
    CHAIR = "chair"
    CAR = "car"
    ALL = "all"


devices = {

    "chair": {

        "id": "chair",

        "topic_cmd": "mesh/chair/control",

        "topic_telemetry": "mesh/chair/telemetry",

        "topic_ack": "mesh/chair/ack",

        "online": False

    },

    "car": {

        "id": "car",

        "topic_cmd": "robotcar/98:A3:16:BF:2C:C0/control",

        "topic_telemetry": "robotcar/98:A3:16:BF:2C:C0/status",

        "topic_ack": "robotcar/98:A3:16:BF:2C:C0/ack",
        
        "online": False

    }

}
