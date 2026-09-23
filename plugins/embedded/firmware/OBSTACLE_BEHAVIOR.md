# Robot Car Obstacle Command Behavior

The obstacle sensors are directional command guards only.

- `FRONT BLOCKED` prevents `LIFTCARFORWARD` only.
- `REAR BLOCKED` prevents `LIFTCARBACKWARD` only.
- `LIFTCARLEFT` and `LIFTCARLEFT360` remain available when the front or rear is blocked.
- `LIFTCARRIGHT` and `LIFTCARRIGHT360` remain available when the front or rear is blocked.
- A front obstacle does not disable backward, left, or right movement.
- A rear obstacle does not disable forward, left, or right movement.
- The ESP32 continues reporting the sensor state through its normal status/ACK/serial paths.

This is intentional: the operator can see the robot's environment and use left/right movement to steer around an obstacle.
