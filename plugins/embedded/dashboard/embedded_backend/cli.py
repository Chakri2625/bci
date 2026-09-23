from .dispatcher import CommandSource
from .device_registry import CommandTarget


class CLI:

    def __init__(self, dispatcher):

        self.dispatcher = dispatcher

        self.current_target = CommandTarget.CHAIR
def start(self):

        print()
        print("================================")
        print(" SynaptiMesh CLI")
        print("================================")
        print()

        while True:

            cmd = input("> ").strip().upper()

            if cmd == "EXIT":
                break

        self.handle_command(cmd)

# -------------------------------------------------------
# COMMAND HANDLER
# -------------------------------------------------------

def handle_command(self, command):

    # ----------------------------
    # Change Target
    # ----------------------------

    if command == "CAR":

        self.current_target = CommandTarget.CAR

        print("[CLI] Target -> CAR")

        return

    if command == "CHAIR":

        self.current_target = CommandTarget.CHAIR

        print("[CLI] Target -> CHAIR")

        return

    if command == "ALL":

        self.current_target = CommandTarget.ALL

        print("[CLI] Target -> ALL")

        return


    # ----------------------------
    # Valid Commands
    # ----------------------------

    valid = {

        "FORWARD",

        "BACKWARD",

        "LEFT",

        "RIGHT",

        "LEFT360",

        "RIGHT360",

        "STOP",

        "DROP"

    }

    if command not in valid:

        print(f"[CLI] Unknown Command : {command}")

        return


    # ----------------------------
    # Dispatch
    # ----------------------------

    self.dispatcher.dispatch(

        source=CommandSource.CLI,

        target=self.current_target,

        domain="LIFT",

        command=command

    )