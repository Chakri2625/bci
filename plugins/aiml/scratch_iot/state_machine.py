"""
state_machine.py
Hierarchical Brain-Computer Interface (BCI) State Machine for IoT Control.

Features:
 - Temporal Window Framing Control: Holds commands in a timed confirmation window (default 4.0s); executes only after the time frame completes.
 - Cancellation Support: Cancel pending framed command via PUSH + PULL.
 - Single-fire latching within customizable time window (continuous mental streams trigger only 1 time).
 - Combination command detection: PUSH + PULL -> BACK / Cancel (Return to Main Menu / Cancel Framing).
 - Root Selection Mode:
     'push'  -> Selects LIGHT
     'pull'  -> Selects FAN
     'left'  -> Selects PUMP
 - Device Control Mode:
     'right' -> Turn ON (framed)
     'left'  -> Turn OFF (framed)
     'push'  -> Opens Combo Window for PUSH + PULL (BACK / Cancel)
     'pull'  -> Ignored in locked domain unless preceded by 'push' (triggers PUSH+PULL -> BACK)
"""

import sys
import time
import asyncio
from typing import Dict, Any, Optional, Callable, List

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


class BCIStateMachine:
    def __init__(
        self,
        power_threshold: float = 0.35,
        debounce_ms: int = 900,
        single_fire_window_ms: int = 1500,
        combo_window_ms: int = 2000,
        framing_window_ms: int = 4000,
        framing_enabled: bool = True,
        auto_return_timeout_ms: int = 0,  # 0 = disabled
    ):
        self.power_threshold = float(power_threshold)
        self.debounce_ms = int(debounce_ms)
        self.single_fire_window_ms = int(single_fire_window_ms)
        self.combo_window_ms = int(combo_window_ms)
        self.framing_window_ms = int(framing_window_ms)
        self.framing_enabled = bool(framing_enabled)
        self.auto_return_timeout_ms = int(auto_return_timeout_ms)

        # State Variables
        self.current_state: str = "SELECT_APPLIANCE"  # "SELECT_APPLIANCE" | "CONTROL_DEVICE"
        self.selected_device: Optional[str] = None    # "light" | "fan" | "pump" | None
        self.device_states: Dict[str, str] = {
            "light": "OFF",
            "fan": "OFF",
            "pump": "OFF",
        }

        self.last_trigger_time: float = 0.0
        self._auto_return_task: Optional[asyncio.Task] = None

        # Single-fire latching state
        self._last_latched_action: Optional[str] = None
        self._latch_timestamp: float = 0.0

        # Combination command state
        self._combo_first_action: Optional[str] = None
        self._combo_start_time: float = 0.0
        self._combo_task: Optional[asyncio.Task] = None

        # Temporal Window Framing state
        self._pending_framed_command: Optional[Dict[str, Any]] = None
        self._framing_task: Optional[asyncio.Task] = None
        self._framing_start_time: float = 0.0

        self._listeners: Dict[str, List[Callable]] = {}

        self.stats: Dict[str, Any] = {
            "totalCommandsReceived": 0,
            "totalActionsDispatched": 0,
            "lastCommand": None,
            "lastPower": 0.0,
            "lastActionDispatched": None,
            "combosTriggered": 0,
            "framingWindowsCompleted": 0,
            "framingWindowsCancelled": 0,
        }

    # -------------------------------------------------------------------------
    # Event Emitter Mechanism
    # -------------------------------------------------------------------------
    def on(self, event_name: str, callback: Callable):
        if event_name not in self._listeners:
            self._listeners[event_name] = []
        self._listeners[event_name].append(callback)

    def emit(self, event_name: str, data: Any = None):
        if event_name in self._listeners:
            for callback in self._listeners[event_name]:
                try:
                    if asyncio.iscoroutinefunction(callback):
                        try:
                            loop = asyncio.get_running_loop()
                            loop.create_task(callback(data))
                        except RuntimeError:
                            asyncio.run(callback(data))
                    else:
                        callback(data)
                except Exception as e:
                    print(f"[ERROR in SM listener '{event_name}']: {e}")

    # -------------------------------------------------------------------------
    # Config & State Snapshots
    # -------------------------------------------------------------------------
    def update_config(self, config: Dict[str, Any]):
        if "powerThreshold" in config:
            self.power_threshold = max(0.05, min(1.0, float(config["powerThreshold"])))
        elif "power_threshold" in config:
            self.power_threshold = max(0.05, min(1.0, float(config["power_threshold"])))

        if "debounceMs" in config:
            self.debounce_ms = max(10, int(config["debounceMs"]))
        elif "debounce_ms" in config:
            self.debounce_ms = max(10, int(config["debounce_ms"]))

        if "singleFireWindowMs" in config:
            self.single_fire_window_ms = max(50, int(config["singleFireWindowMs"]))
        elif "single_fire_window_ms" in config:
            self.single_fire_window_ms = max(50, int(config["single_fire_window_ms"]))

        if "comboWindowMs" in config:
            self.combo_window_ms = max(100, int(config["comboWindowMs"]))
        elif "combo_window_ms" in config:
            self.combo_window_ms = max(100, int(config["combo_window_ms"]))

        if "framingWindowMs" in config:
            self.framing_window_ms = max(200, int(config["framingWindowMs"]))
        elif "framing_window_ms" in config:
            self.framing_window_ms = max(200, int(config["framing_window_ms"]))

        if "framingEnabled" in config:
            self.framing_enabled = bool(config["framingEnabled"])
        elif "framing_enabled" in config:
            self.framing_enabled = bool(config["framing_enabled"])

        if "autoReturnTimeoutMs" in config:
            self.auto_return_timeout_ms = int(config["autoReturnTimeoutMs"])
        elif "auto_return_timeout_ms" in config:
            self.auto_return_timeout_ms = int(config["auto_return_timeout_ms"])

        self.emit("config_updated", self.get_config())

    def get_config(self) -> Dict[str, Any]:
        return {
            "powerThreshold": self.power_threshold,
            "debounceMs": self.debounce_ms,
            "singleFireWindowMs": self.single_fire_window_ms,
            "comboWindowMs": self.combo_window_ms,
            "framingWindowMs": self.framing_window_ms,
            "framingEnabled": self.framing_enabled,
            "autoReturnTimeoutMs": self.auto_return_timeout_ms,
        }

    def get_full_state(self) -> Dict[str, Any]:
        return {
            "currentState": self.current_state,
            "selectedDevice": self.selected_device,
            "deviceStates": dict(self.device_states),
            "config": self.get_config(),
            "stats": dict(self.stats),
            "comboActive": bool(self._combo_first_action),
            "comboFirstAction": self._combo_first_action,
            "framingActive": bool(self._pending_framed_command),
            "pendingFramedCommand": self._pending_framed_command,
        }

    # -------------------------------------------------------------------------
    # Mental Command Processing Pipeline
    # -------------------------------------------------------------------------
    def process_mental_command(
        self, action: str, power: float = 1.0, is_simulation: bool = False
    ) -> Optional[Dict[str, Any]]:
        action = (action or "").lower().strip()
        power = float(power) if power is not None else 0.0

        self.stats["totalCommandsReceived"] += 1
        self.stats["lastCommand"] = action
        self.stats["lastPower"] = power

        # Live telemetry event
        self.emit("telemetry", {
            "action": action,
            "power": power,
            "isSimulation": is_simulation,
            "timestamp": int(time.time() * 1000),
        })

        now_ms = time.time() * 1000

        # Neutral or relaxation releases single-fire latch
        if action == "neutral" or not action:
            self._last_latched_action = None
            return None

        # Power threshold filter
        if power < self.power_threshold and not is_simulation:
            self._last_latched_action = None
            self.emit("command_filtered", {
                "action": action,
                "power": power,
                "threshold": self.power_threshold,
                "reason": "Below power threshold",
            })
            return None

        # ---------------------------------------------------------------------
        # 1. Single-Fire Latch Window Check
        # ---------------------------------------------------------------------
        if not is_simulation and self._last_latched_action == action:
            if (now_ms - self._latch_timestamp) < self.single_fire_window_ms:
                self.emit("single_fire_suppressed", {
                    "action": action,
                    "power": power,
                    "reason": f"Sustained gesture '{action}' suppressed within {self.single_fire_window_ms}ms window (taken only 1 time)",
                })
                return None

        # ---------------------------------------------------------------------
        # 2. Debounce Filter Check
        # ---------------------------------------------------------------------
        if (now_ms - self.last_trigger_time) < self.debounce_ms and not is_simulation:
            self.emit("command_filtered", {
                "action": action,
                "power": power,
                "reason": "Debounce cooldown active",
            })
            return None

        # Register successful trigger & lock single-fire latch
        self.last_trigger_time = now_ms
        self._last_latched_action = action
        self._latch_timestamp = now_ms

        # ---------------------------------------------------------------------
        # 3. Combination Command Check (PUSH + PULL -> BACK / EXIT DOMAIN / CANCEL FRAMING)
        # ---------------------------------------------------------------------
        if self._combo_first_action == "push" and (now_ms - self._combo_start_time) <= self.combo_window_ms:
            if action == "pull":
                # Matched Combo: PUSH + PULL -> BACK (Exit domain to Selection Mode / Cancel framing)
                self._cancel_combo_timer()
                self.cancel_framing_window("combo_push_pull")
                self._combo_first_action = None
                self.stats["combosTriggered"] += 1

                combo_event = {
                    "type": "COMBO_COMMAND",
                    "combo": "PUSH+PULL",
                    "action": "BACK",
                    "power": power,
                    "message": "Combination Detected: [PUSH + PULL] ➔ BACK (Exited domain / Cancelled framing to Selection Mode)",
                    "timestamp": int(now_ms),
                }
                self.emit("combo_triggered", combo_event)
                self.return_to_selection_mode("combo_push_pull")
                return combo_event

        # ---------------------------------------------------------------------
        # 4. Standard / Framed State Machine Evaluation
        # ---------------------------------------------------------------------
        return self._evaluate_state_transition(action, power)

    def _evaluate_state_transition(self, action: str, power: float) -> Optional[Dict[str, Any]]:
        if self.current_state == "SELECT_APPLIANCE":
            target_map = {"push": "light", "pull": "fan", "left": "pump"}
            if action in target_map:
                target_dev = target_map[action]
                if self.framing_enabled:
                    # If this action is 'push', also start the combo window so PUSH+PULL can cancel the pending selection
                    if action == "push":
                        self._start_combo_window("push")
                    return self._start_framing_window({
                        "kind": "SELECT",
                        "device": target_dev,
                        "action": action,
                        "power": power,
                        "description": f"When {target_dev.upper()} is selected, the system holds a {self.framing_window_ms/1000:.1f}-second confirmation window before locking into the {target_dev.upper()} domain. (Think PUSH+PULL to cancel)."
                    })
                else:
                    self._select_device(target_dev, action, power)
                    res = {"type": "SELECT", "device": target_dev, "action": action, "power": power}
                    self._emit_transition_event(res)
                    return res
            elif action == "right":
                self.emit("info", {
                    "message": "Gesture 'right' received in Selection Mode. Select Light (push), Fan (pull), or Pump (left) first.",
                    "action": action,
                })

        elif self.current_state == "CONTROL_DEVICE":
            # Domain is LOCKED to self.selected_device
            if action in ("right", "left"):
                state = "ON" if action == "right" else "OFF"
                if self.framing_enabled:
                    return self._start_framing_window({
                        "kind": "ACTUATOR",
                        "device": self.selected_device,
                        "state": state,
                        "action": action,
                        "power": power,
                        "description": f"Setting {self.selected_device.upper()} ➔ {state}. Executes once the {self.framing_window_ms/1000:.1f}s window finishes. (Think PUSH+PULL to cancel)."
                    })
                else:
                    return self._set_device_state(self.selected_device, state, action, power)

            elif action == "push":
                # In Control Mode: domain is locked on current device!
                # 'push' opens the Combo Window waiting for 'pull' to exit domain / cancel framing
                self._start_combo_window("push")
                combo_open_res = {
                    "type": "COMBO_WINDOW_OPEN",
                    "action": "push",
                    "device": self.selected_device,
                    "message": f"Domain locked on {self.selected_device.upper()}. PUSH detected: combo window active (think PULL to exit domain / cancel framing).",
                }
                self.emit("info", combo_open_res)
                return combo_open_res

            elif action == "pull":
                # In Control Mode: domain is locked! 'pull' without preceding 'push' does NOT switch to fan.
                self.emit("info", {
                    "message": f"Domain locked on {self.selected_device.upper()}. Think RIGHT (ON), LEFT (OFF), or PUSH+PULL to exit back to Main Menu.",
                    "action": action,
                })
                return None

        return None

        return None

    def _emit_transition_event(self, result: Dict[str, Any]):
        self.emit("transition", {
            **result,
            "currentState": self.current_state,
            "selectedDevice": self.selected_device,
            "deviceStates": dict(self.device_states),
        })

    # -------------------------------------------------------------------------
    # Temporal Window Framing Control (Deferred Execution Engine)
    # -------------------------------------------------------------------------
    def _start_framing_window(self, command_data: Dict[str, Any]) -> Dict[str, Any]:
        self.cancel_framing_window("new_command_override")
        self._pending_framed_command = command_data
        self._framing_start_time = time.time() * 1000

        framing_event = {
            "type": "FRAMING_STARTED",
            "pendingCommand": command_data,
            "windowMs": self.framing_window_ms,
            "expiresAt": int(self._framing_start_time + self.framing_window_ms),
            "description": command_data.get("description", ""),
        }

        self.emit("framing_window_started", framing_event)

        try:
            loop = asyncio.get_running_loop()
            self._framing_task = loop.create_task(self._framing_timer_coro())
        except RuntimeError:
            pass

        return framing_event

    async def _framing_timer_coro(self):
        try:
            await asyncio.sleep(self.framing_window_ms / 1000.0)
            if self._pending_framed_command:
                self._execute_framed_command(self._pending_framed_command)
        except asyncio.CancelledError:
            pass

    def _execute_framed_command(self, cmd: Dict[str, Any]):
        self._pending_framed_command = None
        self._framing_task = None
        self.stats["framingWindowsCompleted"] += 1

        kind = cmd.get("kind")
        action = cmd.get("action")
        power = cmd.get("power", 1.0)

        if kind == "SELECT":
            device = cmd.get("device")
            self._select_device(device, action, power)
            res = {"type": "SELECT", "device": device, "action": action, "power": power}
            self._emit_transition_event(res)
            self.emit("framing_executed", {"kind": "SELECT", "device": device, "result": res})

        elif kind == "ACTUATOR":
            device = cmd.get("device")
            state = cmd.get("state")
            res = self._set_device_state(device, state, action, power)
            self.emit("framing_executed", {"kind": "ACTUATOR", "device": device, "state": state, "result": res})

    def cancel_framing_window(self, reason: str = "user_cancelled"):
        if self._framing_task and not self._framing_task.done():
            self._framing_task.cancel()
        self._framing_task = None

        if self._pending_framed_command:
            cancelled_cmd = self._pending_framed_command
            self._pending_framed_command = None
            self.stats["framingWindowsCancelled"] += 1
            self.emit("framing_cancelled", {
                "reason": reason,
                "cancelledCommand": cancelled_cmd,
                "message": f"Temporal Framing Window aborted ({reason}). Command was not executed.",
            })

    def _select_device(self, device: str, action: str, power: float):
        self.selected_device = device
        self.current_state = "CONTROL_DEVICE"
        if self.auto_return_timeout_ms > 0:
            self._start_auto_return_timer()

        self.emit("device_selected", {
            "device": device,
            "action": action,
            "power": power,
            "message": f"Selected {device.upper()}. Think 'RIGHT' to turn ON, 'LEFT' to turn OFF. (Think 'PUSH+PULL' to return to Main Menu).",
        })

    def _set_device_state(
        self, device: Optional[str], state: str, trigger_action: str = "manual", power: float = 1.0
    ) -> Optional[Dict[str, Any]]:
        if not device or device not in self.device_states:
            return None

        previous_state = self.device_states[device]
        self.device_states[device] = state
        self.stats["totalActionsDispatched"] += 1
        now_ts = int(time.time() * 1000)
        self.stats["lastActionDispatched"] = {"device": device, "state": state, "time": now_ts}

        dispatch_event = {
            "device": device,
            "state": state,
            "previousState": previous_state,
            "triggerAction": trigger_action,
            "power": power,
            "timestamp": now_ts,
        }

        self.emit("actuator_command", dispatch_event)
        return dispatch_event

    def manual_override(self, device: str, state: str) -> Optional[Dict[str, Any]]:
        self.cancel_framing_window("manual_override")
        return self._set_device_state(device.lower(), state.upper(), "manual_override", 1.0)

    def return_to_selection_mode(self, reason: str = "combo_push_pull"):
        self._cancel_auto_return_timer()
        self._cancel_combo_timer()
        self.cancel_framing_window(reason)
        prev_device = self.selected_device
        self.current_state = "SELECT_APPLIANCE"
        self.selected_device = None

        self.emit("state_reset", {
            "reason": reason,
            "previousDevice": prev_device,
            "currentState": self.current_state,
            "message": "Returned to Main Menu Selection Mode (Push: Light, Pull: Fan, Left: Pump | PUSH+PULL: Back/Cancel)",
        })

    # -------------------------------------------------------------------------
    # Combination Window Timer
    # -------------------------------------------------------------------------
    def _start_combo_window(self, first_action: str):
        self._cancel_combo_timer()
        self._combo_first_action = first_action
        self._combo_start_time = time.time() * 1000

        self.emit("combo_window_started", {
            "firstAction": first_action,
            "comboExpected": "PUSH + PULL ➔ BACK (Exit Domain / Cancel)",
            "windowMs": self.combo_window_ms,
            "expiresAt": int(self._combo_start_time + self.combo_window_ms),
        })

        try:
            loop = asyncio.get_running_loop()
            self._combo_task = loop.create_task(self._combo_expiry_coro())
        except RuntimeError:
            pass

    async def _combo_expiry_coro(self):
        try:
            await asyncio.sleep(self.combo_window_ms / 1000.0)
            if self._combo_first_action:
                self._combo_first_action = None
                self.emit("combo_window_expired", {
                    "reason": "Combo window timed out without second command",
                })
        except asyncio.CancelledError:
            pass

    def _cancel_combo_timer(self):
        if self._combo_task and not self._combo_task.done():
            self._combo_task.cancel()
        self._combo_task = None
        self._combo_first_action = None

    # -------------------------------------------------------------------------
    # Auto-Return Inactivity Timer
    # -------------------------------------------------------------------------
    def _start_auto_return_timer(self):
        self._cancel_auto_return_timer()
        if self.auto_return_timeout_ms <= 0:
            return
        try:
            loop = asyncio.get_running_loop()
            self._auto_return_task = loop.create_task(self._auto_return_coro())
        except RuntimeError:
            pass

    async def _auto_return_coro(self):
        try:
            await asyncio.sleep(self.auto_return_timeout_ms / 1000.0)
            self.return_to_selection_mode("inactivity_timeout")
        except asyncio.CancelledError:
            pass

    def _reset_auto_return_timer(self):
        self._start_auto_return_timer()

    def _cancel_auto_return_timer(self):
        if self._auto_return_task and not self._auto_return_task.done():
            self._auto_return_task.cancel()
        self._auto_return_task = None
