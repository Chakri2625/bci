from flask import Flask, render_template
from flask import request, jsonify
from plugins.embedded.dashboard.embedded_backend.hub import Hub
from plugins.embedded.dashboard.embedded_backend.dispatcher import CommandSource
from plugins.embedded.dashboard.embedded_backend.device_registry import CommandTarget
import plugins.embedded.dashboard.embedded_config as config


# ==========================================================
# APPLICATION
# ==========================================================

app = Flask(__name__)

# ==========================================================
# MasterHub Initialization
# ==========================================================

hub = Hub()


hub.socket.initialize(app)

# ==========================================================
# ROUTES
# ==========================================================

@app.route("/")
def index():

    return render_template("index.html")


@app.post("/command")
def command():

    text_command = (
        request.data
        .decode("utf-8")
        .strip()
        .upper()
    )

    print()
    print("================================")
    print("[WEB COMMAND]")
    print(f"RAW: {text_command}")
    print("================================")

    # ------------------------------------------
    # Validate command exists
    # ------------------------------------------

    if not text_command:
        return jsonify({
            "status": "error",
            "message": "Empty command"
        }), 400

    # ------------------------------------------
    # Command format:
    #
    # LIFTCARFORWARD
    # LIFTCARBACKWARD
    # LIFTCARLEFT
    # LIFTCARRIGHT
    # LIFTCARSTOP
    # LIFTCARLEFT360
    # LIFTCARRIGHT360
    #
    # LIFTCHAIRFORWARD
    # etc.
    # ------------------------------------------

    domains = (
        "LIFT",
        "DESKTOP",
        "IOT"
    )

    domain = None

    for d in domains:

        if text_command.startswith(d):

            domain = d
            break

    if domain is None:

        return jsonify({
            "status": "error",
            "message": f"Invalid domain: {text_command}"
        }), 400

    # ------------------------------------------
    # Extract target
    # ------------------------------------------

    remaining = text_command[len(domain):]

    if remaining.startswith("CAR"):

        target = CommandTarget.CAR
        command = remaining[3:]

    elif remaining.startswith("CHAIR"):

        target = CommandTarget.CHAIR
        command = remaining[5:]

    else:

        return jsonify({
            "status": "error",
            "message": f"Invalid target: {remaining}"
        }), 400

    # ------------------------------------------
    # Validate command
    # ------------------------------------------

    VALID_COMMANDS = {
        "FORWARD",
        "BACKWARD",
        "LEFT",
        "RIGHT",
        "LEFT360",
        "RIGHT360",
        "STOP",
        "DROP"
    }

    if command not in VALID_COMMANDS:

        return jsonify({
            "status": "error",
            "message": f"Invalid command: {command}"
        }), 400

    # ------------------------------------------
    # Dispatch
    # ------------------------------------------

    source = CommandSource.DASHBOARD

    print(f"[DOMAIN]  {domain}")
    print(f"[TARGET]  {target}")
    print(f"[COMMAND] {command}")

    hub.dispatcher.dispatch(
        source=source,
        target=target,
        domain=domain,
        command=command
    )

    print("[WEB COMMAND] ACCEPTED")

    return jsonify({
        "status": "ok",
        "command": text_command
    })


# ==========================================================
# MAIN
# ==========================================================


@app.route("/car-control")
def car_control():
    return render_template("car_control.html")


if __name__ == "__main__":

    print(config.APP_NAME)

    hub.initialize()

    hub.socket.socket.run(
        app,
        host=config.HOST,
        port=config.PORT,
        debug=config.DEBUG
    )