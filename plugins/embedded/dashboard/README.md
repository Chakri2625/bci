# SynaptiMesh Master Hub

## Overview

SynaptiMesh Master Hub is a Flask-based control and monitoring
application for managing robot devices through MQTT and a web-based
interface.

The project is organized into four main areas:

-   **Backend** --- Handles commands, MQTT communication, device
    management, protocol handling, and telemetry.
-   **Static files** --- Contains CSS, JavaScript, images, 3D model
    assets, and vendor resources used by the web interface.
-   **Templates** --- Contains the HTML pages served by Flask.
-   **Root configuration files** --- Defines application settings,
    dependencies, and the main Flask entry point.

------------------------------------------------------------------------

## Project Structure

``` text
D:.
│   app.py
│   config.py
│   README.md
│   requirements.txt
│
├── backend
│   ├── cli.py
│   ├── device_registry.py
│   ├── dispatcher.py
│   ├── hub.py
│   ├── mqtt_client.py
│   ├── protocol.py
│   ├── socket_manager.py
│   └── telemetry.py
│
├── static
│   ├── css
│   │   ├── car_control.css
│   │   └── style.css
│   ├── images
│   │   └── background.jpg
│   ├── js
│   │   ├── car_control.js
│   │   ├── dashboard.js
│   │   └── 3d
│   │       ├── car3d.js
│   │       ├── controls.js
│   │       ├── scene.js
│   │       └── sensors.js
│   ├── models
│   │   ├── README.txt
│   │   └── robot-car.glb
│   └── vendor
│       └── README.txt
│
└── templates
    ├── car_control.html
    └── index.html
```

------------------------------------------------------------------------

# 1. Root Files

### `app.py`

The main Flask application entry point.

It connects the web interface with the backend system and provides the
HTTP routes used by the dashboard and robot-control page.

**Main responsibility:** - Starts the Flask application. - Serves the
web pages. - Receives commands from the frontend. - Passes commands to
the backend hub.

### `config.py`

Contains the application's main configuration values.

This is where settings such as the Flask server address/port and MQTT
broker configuration are maintained.

**Main responsibility:** - Application configuration. - Server
configuration. - MQTT broker configuration.

### `requirements.txt`

Lists the Python packages required to run the project.

It allows the project environment to be installed consistently using
Python's package manager.

### `README.md`

Project documentation.

It explains the structure, purpose, setup, and important components of
the Master Hub.

------------------------------------------------------------------------

# 2. Backend

The `backend` folder contains the core communication and control logic.

The general flow is:

``` text
Web Interface
      │
      ▼
    app.py
      │
      ▼
     hub.py
      │
      ▼
 dispatcher.py
      │
      ▼
 mqtt_client.py
      │
      ▼
 MQTT Broker
      │
      ▼
 Robot / ESP32
```

Telemetry and acknowledgements travel back through the MQTT system and
are processed by the backend before being sent to the web interface.

------------------------------------------------------------------------

### `cli.py`

Provides command-line related functionality.

**Main responsibility:** - Defines/handles command-related CLI
functionality. - Provides a way to work with supported robot commands
outside the web interface.

### `device_registry.py`

Maintains information about the devices controlled by the Master Hub.

**Main responsibility:** - Identifies registered devices. - Associates
devices with their communication topics. - Provides device/topic
information to the rest of the backend.

### `dispatcher.py`

Acts as the command dispatcher.

It takes a command prepared by the application and sends it toward the
appropriate device through MQTT.

**Main responsibility:** - Receives commands from the hub. -
Builds/prepares the outgoing protocol packet. - Publishes the command
through the MQTT client.

### `hub.py`

Acts as the central backend coordinator.

It brings the major backend components together and connects the
command, MQTT, device, socket, and telemetry systems.

**Main responsibility:** - Initializes backend managers. - Coordinates
communication between components. - Connects MQTT messages with
telemetry processing. - Provides the central control path for the
application.

### `mqtt_client.py`

Handles communication with the MQTT broker.

**Main responsibility:** - Connects to the MQTT broker. - Publishes
commands. - Subscribes to relevant MQTT topics. - Receives MQTT
messages. - Maintains MQTT connection handling.

This is the main communication layer between the Master Hub and
MQTT-connected devices.

### `protocol.py`

Defines the command packet/protocol structure used by the Master Hub.

It converts the logical command information into the format expected by
the robot communication system.

**Main responsibility:** - Defines protocol-related values. - Creates
command packets. - Keeps command formatting consistent.

### `socket_manager.py`

Handles communication between the backend and the web frontend using
Socket.IO.

**Main responsibility:** - Sends real-time backend information to the
dashboard. - Emits device, telemetry, ACK, and activity information to
connected clients. - Provides the real-time communication layer for the
browser interface.

### `telemetry.py`

Processes information received from the robot through MQTT.

It is responsible for interpreting incoming ACK/status-related
information and forwarding the appropriate information to the frontend.

**Main responsibility:** - Processes incoming telemetry. - Handles ACK
information. - Handles device status information. - Sends processed
information through the Socket.IO layer.

------------------------------------------------------------------------

# 3. Static Files

The `static` directory contains resources used by the browser.

``` text
static
├── css
├── images
├── js
├── models
└── vendor
```

------------------------------------------------------------------------

## `static/css`

Contains the stylesheets for the web application.

### `car_control.css`

Contains styling specifically for the robot car control interface.

### `style.css`

Contains the main/common styling for the Master Hub web interface.

------------------------------------------------------------------------

## `static/images`

### `background.jpg`

Background image used by the web interface.

------------------------------------------------------------------------

## `static/js`

Contains the browser-side JavaScript.

### `car_control.js`

Controls the robot car page in the browser.

**Main responsibility:** - Loads and displays the 3D robot. - Handles
movement controls. - Handles keyboard controls. - Sends commands to the
Flask backend. - Handles real-time ACK/status information. - Updates the
car-control interface. - Controls the visual simulation.

### `dashboard.js`

Controls the main dashboard interface.

**Main responsibility:** - Handles dashboard interactions. - Receives
real-time Socket.IO information. - Updates dashboard device/status
information. - Manages dashboard-side activity and command information.

------------------------------------------------------------------------

## `static/js/3d`

Contains JavaScript modules dedicated to the 3D robot environment.

### `car3d.js`

Handles the 3D robot/car functionality.

**Main responsibility:** - Robot model-related 3D functionality. -
Vehicle representation and animation logic.

### `controls.js`

Contains 3D control-related functionality.

**Main responsibility:** - Handles control behavior associated with the
3D environment. - Connects user interaction with the 3D vehicle.

### `scene.js`

Handles the Three.js scene.

**Main responsibility:** - Scene setup. - Camera/environment-related
functionality. - 3D rendering environment.

### `sensors.js`

Handles the visual/functional representation of robot sensors in the 3D
environment.

**Main responsibility:** - Sensor-related visualization. - Sensor state
handling in the 3D interface.

------------------------------------------------------------------------

# 4. 3D Models

## `static/models`

Contains the 3D assets used by the robot-control interface.

### `robot-car.glb`

The main 3D robot-car model.

The GLB contains the model geometry and can also contain its visual
materials, allowing the browser to load the robot's appearance as part
of the model rather than constructing the appearance entirely through
JavaScript.

### `README.txt`

Provides information associated with the 3D model directory.

------------------------------------------------------------------------

# 5. Vendor Files

## `static/vendor`

Reserved for third-party/vendor browser resources used by the frontend.

### `README.txt`

Provides information about the vendor directory and its intended
contents.

------------------------------------------------------------------------

# 6. Templates

The `templates` directory contains the HTML pages rendered by Flask.

### `index.html`

The main Master Hub/dashboard page.

It provides the primary web interface for viewing and interacting with
the system.

### `car_control.html`

The dedicated robot-car control page.

It provides the interface used for:

-   Selecting/controlling the robot.
-   Sending movement commands.
-   Viewing the 3D robot.
-   Viewing robot status.
-   Viewing sensor-related information.
-   Receiving real-time communication feedback.

------------------------------------------------------------------------

# 7. Overall System Flow

The major communication path can be summarized as:

``` text
                    MASTER HUB
                         │
             ┌───────────┴───────────┐
             │                       │
        Web Interface            Backend
             │                       │
     ┌───────┴────────┐        ┌─────┴─────┐
     │                │        │           │
 Dashboard       Car Control  Hub       Telemetry
     │                │        │           │
     └───────┬────────┘        │           │
             │                 │           │
          Socket.IO       Dispatcher ◄─────┘
             │                 │
             │            MQTT Client
             │                 │
             └──────────── MQTT Broker
                               │
                               ▼
                            ESP32 /
                            Robot
```

### Command direction

``` text
User
  │
  ▼
HTML / JavaScript
  │
  ▼
Flask (`app.py`)
  │
  ▼
Hub
  │
  ▼
Dispatcher
  │
  ▼
Protocol
  │
  ▼
MQTT Client
  │
  ▼
MQTT Broker
  │
  ▼
Robot
```

### Feedback direction

``` text
Robot
  │
  ▼
MQTT Broker
  │
  ▼
MQTT Client
  │
  ▼
Telemetry
  │
  ▼
Socket Manager
  │
  ▼
Socket.IO
  │
  ▼
Dashboard / Car Control
```

------------------------------------------------------------------------

# 8. Main Components at a Glance

  Component              Purpose
  ---------------------- -------------------------------------------
  `app.py`               Flask application and web/API entry point
  `config.py`            Application and MQTT configuration
  `hub.py`               Central backend coordinator
  `dispatcher.py`        Sends commands to devices
  `mqtt_client.py`       MQTT communication
  `protocol.py`          Command packet/protocol handling
  `device_registry.py`   Device and MQTT topic information
  `telemetry.py`         Processes ACK/status/telemetry
  `socket_manager.py`    Real-time browser communication
  `car_control.js`       Robot control page behavior
  `dashboard.js`         Main dashboard behavior
  `3d/*.js`              3D environment functionality
  `robot-car.glb`        Robot's 3D model
  `templates/*.html`     Web pages
  `static/css/*.css`     Web interface styling

------------------------------------------------------------------------

## Summary

The project separates the system into clear layers:

**Frontend → Flask → Backend Hub → MQTT → Robot**

and the robot's responses return through:

**Robot → MQTT → Telemetry → Socket.IO → Frontend**

This separation keeps web presentation, command processing, MQTT
communication, device management, telemetry processing, and 3D
visualization organized independently.
