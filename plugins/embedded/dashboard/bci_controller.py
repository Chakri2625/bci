"""Low-latency BCI command resolver for SynaptiMesh Robot Car.

BCI events are processed immediately. The configurable combination window is
used only to decide whether a single action should be held for a possible
combination. No intermediate action is transmitted to hardware.

Rules:
- Before a domain is selected, PUSH/PULL/LEFT/RIGHT select PYTHON/EMBEDDED/IOT/AIML.
- After EMBEDDED is selected but no device is selected, PUSH/PULL select ROBOT CAR/WHEELCHAIR.
- Navigation actions are consumed as selection events; the next BCI action is a fresh command.
- Robot Car command resolution is enabled only after ROBOT CAR is selected.
- Repeated actions inside one window are deduplicated.
- STOP is an immediate override.
- A valid two-action mapping resolves immediately; no artificial delay is used.
- A lone valid action is dispatched when the collection window expires.
- Invalid multi-action sets never dispatch partial commands.
"""
import asyncio
import time
from typing import Any, Callable, Dict, List, Optional


class BCIController:
    ACTIONS = frozenset(("pull", "push", "left", "right"))
    DOMAIN_BY_ACTION = {
        "push": "PYTHON",
        "pull": "EMBEDDED",
        "left": "IOT",
        "right": "AIML",
    }
    DEVICE_BY_ACTION = {
        "push": "car",
        "pull": "wheelchair",
    }

    # Exact, ORDER-SENSITIVE lookup tables. These are the source of truth.
    # The tuple order matters: LEFT+RIGHT is STOP, while RIGHT+LEFT is not.
    ROBOT_CAR_COMBINATIONS = {
        ("push",): "FORWARD",
        ("pull",): "BACKWARD",
        ("left",): "LEFT",
        ("right",): "RIGHT",
        ("left", "right"): "STOP",
        ("pull", "left"): "LEFT360",
        ("pull", "right"): "RIGHT360",
    }

    # Universal navigation combinations. These are checked before any
    # stage-specific meaning of PUSH/PULL/LEFT/RIGHT.
    DASHBOARD_COMBINATIONS = {
        ("push", "left"): "MAIN_MENU",
        ("push", "right"): "BACK",
    }

    # Compatibility aliases used by older code/tests.
    SINGLE_COMMANDS = {
        "push": "FORWARD",
        "pull": "BACKWARD",
        "left": "LEFT",
        "right": "RIGHT",
    }
    COMBINATION_COMMANDS = {
        key: {
            "name": "+".join(a.upper() for a in key),
            "type": "CAR_COMMAND",
            "command": command,
            "message": f"Combination detected: {' + '.join(a.upper() for a in key)} → {command}",
        }
        for key, command in ROBOT_CAR_COMBINATIONS.items()
        if len(key) > 1
    }

    def __init__(
        self,
        power_threshold=0.35,
        debounce_ms=300,
        single_fire_window_ms=500,
        neutral_stop=True,
        combo_window_ms=2500,
    ):
        self.power_threshold = float(power_threshold)
        self.debounce_ms = int(debounce_ms)
        self.single_fire_window_ms = int(single_fire_window_ms)
        self.neutral_stop = bool(neutral_stop)
        self.combo_window_ms = int(combo_window_ms)

        # Navigation/routing state.
        self.selected_domain: Optional[str] = None
        self.selected_device: Optional[str] = None

        self.last_trigger_time = 0.0
        self.last_latched_action: Optional[str] = None
        self.latch_timestamp = 0.0
        self.last_car_command = "STOP"

        # Current collection window.
        self._combo_start_time = 0.0
        self._combo_task: Optional[asyncio.Task] = None
        self._combo_actions: List[str] = []
        self._combo_powers: Dict[str, float] = {}
        self._combo_first_action: Optional[str] = None
        self._combo_first_power = 0.0

        self.stats = {
            "totalCommandsReceived": 0,
            "totalActionsDispatched": 0,
            "totalCombinationsDetected": 0,
            "totalDashboardActions": 0,
            "duplicatesIgnored": 0,
            "invalidCombinations": 0,
            "lastCommand": None,
            "lastPower": 0.0,
            "lastActionDispatched": "STOP",
            "lastCombination": None,
            "lastDashboardAction": None,
        }
        self._listeners: Dict[str, List[Callable]] = {}

    # ------------------------------------------------------------------
    # Event emitter
    # ------------------------------------------------------------------
    def on(self, event_name: str, callback: Callable):
        self._listeners.setdefault(event_name, []).append(callback)

    def emit(self, event_name: str, data: Any = None):
        for callback in list(self._listeners.get(event_name, [])):
            try:
                if asyncio.iscoroutinefunction(callback):
                    try:
                        asyncio.get_running_loop().create_task(callback(data))
                    except RuntimeError:
                        pass
                else:
                    callback(data)
            except Exception as exc:
                print(f"[BCI listener '{event_name}'] {exc}")

    # ------------------------------------------------------------------
    # State/config
    # ------------------------------------------------------------------
    def get_config(self):
        return {
            "powerThreshold": self.power_threshold,
            "debounceMs": self.debounce_ms,
            "singleFireWindowMs": self.single_fire_window_ms,
            "neutralStop": self.neutral_stop,
            "comboWindowMs": self.combo_window_ms,
        }

    def get_full_state(self):
        return {
            "currentState": (
                "CONTROL_DEVICE"
                if self.selected_device
                else ("SELECT_DEVICE" if self.selected_domain else "SELECT_DOMAIN")
            ),
            "selectedDomain": self.selected_domain,
            "selectedDevice": self.selected_device,
            "deviceStates": {"car": self.last_car_command} if self.selected_device == "car" else {},
            "config": self.get_config(),
            "stats": dict(self.stats),
            "comboActive": bool(self._combo_actions),
            "comboFirstAction": self._combo_first_action,
            "comboActions": list(self._combo_actions),
            "comboExpiresAt": (
                int(self._combo_start_time + self.combo_window_ms)
                if self._combo_actions
                else None
            ),
        }

    def update_config(self, config: Dict[str, Any]):
        if "powerThreshold" in config:
            self.power_threshold = max(0.05, min(1.0, float(config["powerThreshold"])))
        if "debounceMs" in config:
            self.debounce_ms = max(0, int(config["debounceMs"]))
        if "singleFireWindowMs" in config:
            self.single_fire_window_ms = max(0, int(config["singleFireWindowMs"]))
        if "neutralStop" in config:
            self.neutral_stop = bool(config["neutralStop"])
        if "comboWindowMs" in config:
            self.combo_window_ms = max(500, min(6000, int(config["comboWindowMs"])))
        self.emit("config_updated", self.get_config())

    # ------------------------------------------------------------------
    # Explicit routing selection
    # ------------------------------------------------------------------
    def select_domain(self, domain: str, trigger_action: Optional[str] = None):
        domain = str(domain or "").strip().upper()
        if domain not in ("PYTHON", "EMBEDDED", "IOT", "AIML"):
            raise ValueError("Unsupported domain. Use PYTHON, EMBEDDED, IOT, or AIML.")
        self._clear_window()
        self.selected_domain = domain
        self.selected_device = None
        event = {
            "type": "DOMAIN_SELECTED",
            "domain": domain,
            "selectedDomain": domain,
            "selectedDevice": None,
            "message": (
                "Embedded domain selected. Select Robot Car or Wheelchair."
                if domain == "EMBEDDED"
                else f"{domain} domain selected. Waiting for the next command."
            ),
        }
        if trigger_action:
            event["triggerAction"] = str(trigger_action).upper()
        self.emit("domain_selected", event)
        self.emit("transition", self.get_full_state())
        return event

    def select_device(self, device: str, trigger_action: Optional[str] = None):
        device = str(device or "").strip().lower()
        if self.selected_domain != "EMBEDDED":
            return {"success": False, "error": "Select the EMBEDDED domain first."}
        aliases = {"car": "car", "robotcar": "car", "wheelchair": "wheelchair", "chair": "wheelchair"}
        if device not in aliases:
            return {"success": False, "error": "Select Robot Car or Wheelchair."}
        self._clear_window()
        self.selected_device = aliases[device]
        message = (
            "Robot Car selected. Single and combination Robot Car BCI commands are now active."
            if self.selected_device == "car"
            else "Wheelchair selected. Robot Car commands are disabled until Robot Car is selected."
        )
        event = {
            "type": "DEVICE_SELECTED",
            "domain": self.selected_domain,
            "device": self.selected_device,
            "message": message,
        }
        if trigger_action:
            event["triggerAction"] = str(trigger_action).upper()
        self.emit("device_selected", event)
        self.emit("transition", self.get_full_state())
        return {"success": True, **event}

    def reset_navigation(self, reason="manual"):
        self._clear_window()
        previous = {"domain": self.selected_domain, "device": self.selected_device}
        self.selected_domain = None
        self.selected_device = None
        event = {
            "type": "NAVIGATION_RESET",
            "reason": reason,
            "previous": previous,
            "message": "Returned to Main Menu / domain selection.",
        }
        self.emit("state_reset", event)
        self.emit("transition", self.get_full_state())
        return event

    # ------------------------------------------------------------------
    # Main BCI resolver
    # ------------------------------------------------------------------
    def process_mental_command(
        self, action: str, power: float = 1.0, is_simulation: bool = False
    ):
        action = str(action or "").lower().strip()
        power = float(power or 0.0)
        now = time.time() * 1000

        self.stats["totalCommandsReceived"] += 1
        self.stats["lastCommand"] = action or "neutral"
        self.stats["lastPower"] = power

        self.emit(
            "telemetry",
            {
                "action": action or "neutral",
                "power": power,
                "isSimulation": is_simulation,
                "timestamp": int(time.time() * 1000),
            },
        )

        # Parsed-command display event. This is the UI-facing representation of
        # the current BCI input and is intentionally separate from raw telemetry.
        # The frontend can therefore show the command the parser is considering
        # without flooding the small Active Mental Command field with raw samples.
        if action in self.ACTIONS:
            self.emit(
                "parsed_command",
                {
                    "actions": [action],
                    "displayCommand": action.upper(),
                    "power": power,
                    "stage": self._current_navigation_stage(),
                    "selectedDomain": self.selected_domain,
                    "selectedDevice": self.selected_device,
                    "isSimulation": is_simulation,
                    "timestamp": int(time.time() * 1000),
                },
            )

        if action in ("neutral", ""):
            return None

        if power < self.power_threshold and not is_simulation:
            self.emit(
                "command_filtered",
                {
                    "action": action,
                    "power": power,
                    "threshold": self.power_threshold,
                    "reason": "Below power threshold",
                },
            )
            return None

        if action == "stop":
            return self._immediate_stop(power)

        if action not in self.ACTIONS:
            self.emit(
                "command_filtered",
                {"action": action, "reason": "Unsupported BCI action"},
            )
            return None

        # Every stage uses the same 2.5-second decision window so PUSH+LEFT
        # and PUSH+RIGHT can always be recognized as universal commands.
        # A single action is resolved only after the window expires, according
        # to the CURRENT navigation stage. Selection actions are therefore
        # consumed and never leak into the next stage.
        # --------------------------------------------------------------
        # Active collection window: process every event immediately.
        # Preserve arrival order. Do not use sets for command matching.
        # --------------------------------------------------------------
        if self._combo_actions:
            if action in self._combo_actions:
                self.stats["duplicatesIgnored"] += 1
                self.emit(
                    "combo_ignored",
                    {
                        "action": action,
                        "receivedAction": action,
                        "actions": list(self._combo_actions),
                        "stage": self._current_navigation_stage(),
                        "selectedDomain": self.selected_domain,
                        "selectedDevice": self.selected_device,
                        "reason": "Duplicate action ignored inside active command window.",
                    },
                )
                # Keep the UI synchronized with the complete sequence being
                # parsed, even when the newly received token is a duplicate.
                self.emit(
                    "combo_progress",
                    {
                        "receivedAction": action,
                        "actions": list(self._combo_actions),
                        "displayCommand": self._format_combo(self._combo_actions),
                        "displayCommand": self._format_combo(self._combo_actions),
                        "stage": self._current_navigation_stage(),
                        "selectedDomain": self.selected_domain,
                        "selectedDevice": self.selected_device,
                        "duplicate": True,
                        "message": "Duplicate action ignored; current command sequence retained.",
                    },
                )
                return None

            self._combo_actions.append(action)
            self._combo_powers[action] = power
            sequence = tuple(self._combo_actions)

            # Universal commands have priority at every navigation stage.
            dashboard = self.DASHBOARD_COMBINATIONS.get(sequence)
            if dashboard:
                return self._resolve_dashboard(
                    dashboard, sequence, max(self._combo_powers.values(), default=power)
                )

            # Robot Car combinations are only meaningful in Robot Car control mode.
            if self.selected_domain == "EMBEDDED" and self.selected_device == "car":
                robot = self.ROBOT_CAR_COMBINATIONS.get(sequence)
                if robot and len(sequence) > 1:
                    return self._resolve_robot(
                        robot,
                        self._format_combo(sequence),
                        max(self._combo_powers.values(), default=power),
                        sequence,
                    )

            # More input may still arrive, but nothing partial is transmitted.
            self.emit(
                "combo_progress",
                {
                    "receivedAction": action,
                    "actions": list(self._combo_actions),
                    "stage": self._current_navigation_stage(),
                    "selectedDomain": self.selected_domain,
                    "selectedDevice": self.selected_device,
                    "message": "No exact mapping yet; continuing collection without transmission.",
                },
            )
            return None

        # New window: debounce only applies to the first action of a window.
        if (
            not is_simulation
            and self.last_latched_action == action
            and (now - self.latch_timestamp) < self.single_fire_window_ms
        ):
            self.emit(
                "single_fire_suppressed",
                {
                    "action": action,
                    "power": power,
                    "reason": "Repeated sustained gesture suppressed",
                },
            )
            return None

        if (
            not is_simulation
            and (now - self.last_trigger_time) < self.debounce_ms
        ):
            self.emit(
                "command_filtered",
                {
                    "action": action,
                    "power": power,
                    "reason": "Debounce cooldown active",
                },
            )
            return None

        self.last_trigger_time = now
        self.last_latched_action = action
        self.latch_timestamp = now

        self._start_combo_window(action, power)
        return {
            "type": "COMBO_WINDOW_OPEN",
            "action": action,
            "actions": [action],
            "windowMs": self.combo_window_ms,
            "expiresAt": int(self._combo_start_time + self.combo_window_ms),
            "message": (
                f"{action.upper()} received. Collecting unique BCI actions for "
                f"up to {self.combo_window_ms / 1000:.1f}s; exact mappings are "
                "resolved before transmission."
            ),
        }

    def process_simulator_selection(self, actions, power=1.0):
        """Resolve one complete simulator selection without opening a live window.

        The simulator UI supplies the full ordered selection at once. Nothing is
        transmitted unless the complete sequence exactly matches a valid mapping
        for the current navigation stage.
        """
        power = float(power or 0.0)
        cleaned = [str(a or "").strip().lower() for a in (actions or [])]
        cleaned = [a for a in cleaned if a in self.ACTIONS]

        # Repeated switch presses are already handled by the UI, but keep the
        # backend deterministic if duplicate tokens are supplied.
        if len(cleaned) != len(set(cleaned)):
            return {
                "type": "SIMULATION_REJECTED",
                "command": None,
                "actions": cleaned,
                "message": "Duplicate simulator actions are not a valid exact mapping; nothing was transmitted.",
            }

        if not cleaned:
            return {
                "type": "SIMULATION_REJECTED",
                "command": None,
                "actions": [],
                "message": "No simulator command selected; nothing was transmitted.",
            }

        sequence = tuple(cleaned)

        # Universal dashboard commands have priority at every stage.
        dashboard = self.DASHBOARD_COMBINATIONS.get(sequence)
        if dashboard:
            return self._resolve_dashboard(dashboard, sequence, power)

        # Simulator navigation must use the same stage-dependent semantics as
        # the live BCI parser. A single selected switch is therefore NOT a
        # Robot Car movement command unless Robot Car is already selected.
        if len(sequence) == 1:
            action = sequence[0]

            # Root: PUSH/PULL/LEFT/RIGHT select the four domains.
            if self.selected_domain is None:
                domain = self.DOMAIN_BY_ACTION.get(action)
                if domain:
                    event = self.select_domain(domain, trigger_action=action.upper())
                    event["simulator"] = True
                    event["actions"] = list(sequence)
                    event["power"] = power
                    event["combo"] = self._format_combo(sequence)
                    return {
                        "type": "SIMULATION_NAVIGATION",
                        "command": f"SELECT_{domain}",
                        "actions": list(sequence),
                        "combo": self._format_combo(sequence),
                        "domain": domain,
                        "device": None,
                        "power": power,
                        "message": (
                            f"Single {action.upper()} → {domain} domain selected; "
                            "waiting for the next command."
                        ),
                    }

            # EMBEDDED device-selection stage: PUSH/PULL select Car/Wheelchair.
            if self.selected_domain == "EMBEDDED" and self.selected_device is None:
                device = self.DEVICE_BY_ACTION.get(action)
                if device:
                    result = self.select_device(device, trigger_action=action.upper())
                    return {
                        "type": "SIMULATION_NAVIGATION",
                        "command": f"SELECT_{device.upper()}",
                        "actions": list(sequence),
                        "combo": self._format_combo(sequence),
                        "domain": self.selected_domain,
                        "device": device,
                        "power": power,
                        "message": (
                            f"Single {action.upper()} → {device.upper()} selected; "
                            "waiting for the next command."
                        ),
                        "selection": result,
                    }

        # Robot Car single and exact combination mappings are valid only when
        # Robot Car is the currently selected device.
        if self.selected_domain == "EMBEDDED" and self.selected_device == "car":
            robot = self.ROBOT_CAR_COMBINATIONS.get(sequence)
            if robot:
                return self._resolve_robot(
                    robot, self._format_combo(sequence), power, sequence
                )

        return {
            "type": "SIMULATION_REJECTED",
            "command": None,
            "actions": list(sequence),
            "combo": self._format_combo(sequence),
            "message": (
                f"Invalid simulator sequence {self._format_combo(sequence)} for "
                f"the current stage/device; nothing was transmitted."
            ),
        }

    # ------------------------------------------------------------------
    # Resolution
    # ------------------------------------------------------------------
    def _immediate_stop(self, power):
        self._clear_window()
        if self.selected_device:
            return self._resolve_robot("STOP", "STOP", power, frozenset(("stop",)))
        return {
            "type": "STOP",
            "command": "STOP",
            "message": "STOP received; no device selected, so nothing was transmitted.",
        }

    def _resolve_robot(self, command, combo_name, power, actions):
        self._clear_window()
        self.stats["totalCombinationsDetected"] += 1 if len(actions) > 1 else 0
        self.stats["lastCombination"] = combo_name
        event = {
            "type": "COMBO_COMMAND" if len(actions) > 1 else "BCI_COMMAND",
            "combo": combo_name,
            "comboType": "ROBOT_CAR",
            "actions": list(actions),
            "domain": self.selected_domain,
            "device": self.selected_device,
            "command": command,
            "power": power,
            "timestamp": int(time.time() * 1000),
            "message": (
                f"{combo_name} → LIFTCAR{command} → "
                f"{str(self.selected_device).upper()}"
            ),
        }
        return self._dispatch(command, combo_name, power, extra=event)

    def _step_back(self):
        """Move the navigation pointer back exactly one level."""
        previous = {"domain": self.selected_domain, "device": self.selected_device}

        if self.selected_device is not None:
            # Device -> device-selection stage. Keep the domain selected.
            self.selected_device = None
            stage = "DEVICE_SELECTION"
            message = "Back: device deselected. Waiting for the next command to select a device."
        elif self.selected_domain is not None:
            # Domain -> domain-selection stage. Clear the domain.
            self.selected_domain = None
            stage = "DOMAIN_SELECTION"
            message = "Back: domain deselected. Waiting for the next command to select a domain."
        else:
            # Already at the root; nothing further to unselect.
            stage = "DOMAIN_SELECTION"
            message = "Back: already at domain selection. Waiting for the next command."

        return previous, stage, message

    def _resolve_dashboard(self, command, actions, power):
        combo_name = self._format_combo(actions)
        self._clear_window()
        self.stats["totalCombinationsDetected"] += 1
        self.stats["totalDashboardActions"] += 1
        self.stats["lastCombination"] = combo_name
        self.stats["lastDashboardAction"] = command

        # MAIN MENU always clears the complete navigation pointer.
        if command == "MAIN_MENU":
            previous = {"domain": self.selected_domain, "device": self.selected_device}
            self.selected_domain = None
            self.selected_device = None
            navigation_stage = "DOMAIN_SELECTION"
            navigation_message = "Main Menu: domain and device deselected. Waiting for the next command."
        # BACK moves exactly one stage backward.
        elif command == "BACK":
            previous, navigation_stage, navigation_message = self._step_back()
        else:
            previous = {"domain": self.selected_domain, "device": self.selected_device}
            navigation_stage = self.get_full_state().get("navigationStage")
            navigation_message = "Dashboard command executed."

        event = {
            "type": "DASHBOARD_COMMAND",
            "combo": combo_name,
            "comboType": "DASHBOARD",
            "actions": list(actions),
            "command": command,
            "domain": self.selected_domain,
            "device": self.selected_device,
            "selectedDomain": self.selected_domain,
            "selectedDevice": self.selected_device,
            "previous": previous,
            "navigationStage": navigation_stage,
            "power": power,
            "timestamp": int(time.time() * 1000),
            "message": f"{combo_name} → {command}. {navigation_message}",
        }
        self.emit("dashboard_command", event)
        self.emit("combo_triggered", event)
        self.emit("transition", self.get_full_state())
        return event

    def _dispatch(self, command, trigger_action, power, extra=None):
        if not self.selected_device:
            return None
        self.last_car_command = command
        self.stats["totalActionsDispatched"] += 1
        self.stats["lastActionDispatched"] = command
        event = {
            "device": self.selected_device,
            "domain": self.selected_domain,
            "state": command,
            "command": command,
            "triggerAction": trigger_action,
            "power": power,
            "timestamp": int(time.time() * 1000),
        }
        if extra:
            event["combo"] = extra.get("combo")
            event["comboType"] = extra.get("comboType")
            event["actions"] = extra.get("actions", [])
        self.emit("actuator_command", event)
        self.emit("transition", self.get_full_state())
        return event

    # ------------------------------------------------------------------
    # Window management
    # ------------------------------------------------------------------
    def _start_combo_window(self, first_action, power):
        self._clear_window()
        self._combo_first_action = first_action
        self._combo_first_power = power
        self._combo_actions = [first_action]
        self._combo_powers = {first_action: power}
        self._combo_start_time = time.time() * 1000

        self.emit(
            "combo_window_started",
            {
                "firstAction": first_action,
                "receivedAction": first_action,
                "actions": [first_action],
                "stage": self._current_navigation_stage(),
                "selectedDomain": self.selected_domain,
                "selectedDevice": self.selected_device,
                "windowMs": self.combo_window_ms,
                "expiresAt": int(self._combo_start_time + self.combo_window_ms),
                "message": (
                    f"2.5-second collection window active. "
                    f"{first_action.upper()} is being held for exact-match resolution."
                ),
            },
        )
        try:
            loop = asyncio.get_running_loop()
            self._combo_task = loop.create_task(self._combo_expiry_coro())
        except RuntimeError:
            self._combo_task = None

    async def _combo_expiry_coro(self):
        try:
            await asyncio.sleep(self.combo_window_ms / 1000.0)
            if not self._combo_actions:
                return

            sequence = tuple(self._combo_actions)
            power = max(self._combo_powers.values(), default=self._combo_first_power)

            # Universal two-action mappings must have arrived in exact order.
            dashboard = self.DASHBOARD_COMBINATIONS.get(sequence)
            if dashboard:
                self._resolve_dashboard(dashboard, sequence, power)
                return

            # At expiry, a single action is interpreted ONLY by the current stage.
            if len(sequence) == 1:
                action = sequence[0]

                if self.selected_domain is None:
                    domain = self.DOMAIN_BY_ACTION.get(action)
                    self._clear_window()
                    if domain:
                        event = self.select_domain(domain, trigger_action=action.upper())
                        self.emit(
                            "combo_window_expired",
                            {
                                "actions": [action],
                                "fallbackCommand": f"SELECT_{domain}",
                                "message": f"Single {action.upper()} → {domain} domain selected; waiting for the next command.",
                            },
                        )
                    return

                if self.selected_domain == "EMBEDDED" and self.selected_device is None:
                    device = self.DEVICE_BY_ACTION.get(action)
                    self._clear_window()
                    if device:
                        event = self.select_device(device, trigger_action=action.upper())
                        self.emit(
                            "combo_window_expired",
                            {
                                "actions": [action],
                                "fallbackCommand": f"SELECT_{device.upper()}",
                                "message": f"Single {action.upper()} → {device.upper()} selected; waiting for the next command.",
                            },
                        )
                    return

                if self.selected_domain == "EMBEDDED" and self.selected_device == "car":
                    command = self.ROBOT_CAR_COMBINATIONS.get(sequence)
                    self._clear_window()
                    if command:
                        self.emit(
                            "combo_window_expired",
                            {
                                "actions": [action],
                                "fallbackCommand": command,
                                "message": f"No combination arrived; executing single {action.upper()} → LIFTCAR{command}.",
                            },
                        )
                        self._dispatch(command, action, power)
                    return

                # Other selected domains/devices have no execution path here.
                self._clear_window()
                self.emit(
                    "combo_window_expired",
                    {
                        "actions": [action],
                        "fallbackCommand": None,
                        "reason": "No command execution is configured for the current stage.",
                        "message": f"Single {action.upper()} received; no command sent at the current stage.",
                    },
                )
                return

            # Any multi-action sequence without an exact mapping is invalid.
            invalid_actions = list(sequence)
            self.stats["invalidCombinations"] += 1
            self._clear_window()
            self.emit(
                "combo_window_expired",
                {
                    "actions": invalid_actions,
                    "fallbackCommand": None,
                    "reason": "Collected actions do not exactly match an allowed ordered combination; nothing sent.",
                    "message": (
                        f"Invalid BCI combination {self._format_combo(sequence)}; "
                        "nothing was transmitted."
                    ),
                },
            )
            self.emit(
                "combination_rejected",
                {
                    "actions": invalid_actions,
                    "reason": "No exact allowed ordered combination; nothing sent.",
                },
            )
        except asyncio.CancelledError:
            return

    def _clear_window(self):
        if self._combo_task and not self._combo_task.done():
            self._combo_task.cancel()
        self._combo_task = None
        self._combo_first_action = None
        self._combo_first_power = 0.0
        self._combo_start_time = 0.0
        self._combo_actions = []
        self._combo_powers = {}

    def _current_navigation_stage(self):
        if self.selected_domain is None:
            return "SELECT_DOMAIN"
        if self.selected_domain == "EMBEDDED" and self.selected_device is None:
            return "SELECT_DEVICE"
        if self.selected_domain == "EMBEDDED" and self.selected_device == "car":
            return "CONTROL_DEVICE"
        if self.selected_domain == "EMBEDDED" and self.selected_device == "wheelchair":
            return "CONTROL_DEVICE"
        return "DOMAIN_SELECTED"

    def _format_combo(self, actions):
        return "+".join(a.upper() for a in actions)

    # ------------------------------------------------------------------
    # Compatibility helpers
    # ------------------------------------------------------------------
    def manual_override(self, device: str, state: str):
        if str(device).lower() not in ("car", "robotcar"):
            raise ValueError("Only the robot car is controlled by this application.")
        if self.selected_domain is None:
            self.selected_domain = "EMBEDDED"
        if self.selected_device is None:
            self.selected_device = "car"
        return self._dispatch(str(state).upper(), "manual_override", 1.0)

    def cancel_framing_window(self, reason="manual"):
        self.emit(
            "framing_cancelled",
            {"reason": reason, "message": "No BCI framing window is active."},
        )

    def return_to_selection_mode(self, reason="manual"):
        return self.reset_navigation(reason)
