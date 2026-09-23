from __future__ import annotations

import asyncio
import logging
import threading
import time
import uuid
from typing import Any, Dict, List, Optional, Union
from core.managers.lifecycle_tracker import lifecycle_tracker, CommandLifecycleStage

logger = logging.getLogger("state_manager")


class StateManager:
    """
    Centralized System State Manager for SynaptiMesh.
    Provides a thread-safe single authoritative location for system runtime state,
    domain status tracking, active command lifecycle management, and session state.
    """

    def __init__(self):
        self._lock = threading.RLock()
        self.states: Dict[str, Dict[str, Any]] = {}
        self.active_commands: Dict[str, Dict[str, Any]] = {}
        self.domain_states: Dict[str, Dict[str, Any]] = {}
        self.device_registry: Dict[str, Dict[str, Any]] = {}
        self.system_state: Dict[str, Any] = {}
        self.active_session_id: str = self._generate_session_id()
        print(f"[SESSION] New session started\n[SESSION] Session ID: {self.active_session_id}")
        logger.info(f"[SESSION] New session started, Session ID: {self.active_session_id}")
        self._init_system_state()
        self._init_domain_states()

    @staticmethod
    def _generate_session_id() -> str:
        return f"SESSION-{uuid.uuid4().hex[:8].upper()}"

    def get_active_session_id(self) -> str:
        with self._lock:
            return self.active_session_id

    def _init_system_state(self) -> None:
        self.system_state = {
            "system_status": "IDLE",
            "execution_state": "IDLE",
            "active_tasks_count": 0,
            "last_activity_timestamp": time.time(),
            "metrics": {
                "total_commands": 0,
                "successful": 0,
                "failed": 0,
                "cancelled": 0,
                "timed_out": 0,
            },
            "performance": {
                "avg_execution_latency_ms": 0.0,
                "recent_execution_latency_ms": 0.0,
                "avg_processing_latency_ms": 0.0,
                "recent_processing_latency_ms": 0.0,
                "total_measured_commands": 0,
                "bottleneck_status": "OPTIMAL",
                "bottleneck_indicators": [],
                "stage_breakdown_ms": {
                    "normalization": 0.0,
                    "validation": 0.0,
                    "routing": 0.0,
                    "conflict_check": 0.0,
                    "execution": 0.0
                }
            },
            "failure_tracking": {
                "last_failure": None,
                "active_failures_count": 0,
                "total_failures_recorded": 0,
                "recovery_summary": {
                    "RECOVERED": 0,
                    "RETRYING": 0,
                    "RECOVERING": 0,
                    "RECOVERY_FAILED": 0,
                    "ISOLATED": 0,
                    "PENDING": 0
                },
                "failure_history": []
            }
        }

    def _init_domain_states(self) -> None:
        standard_domains = ["BCI", "IOT", "ROBOTICS", "EMBEDDED", "DESKTOP", "MEDIA", "AIML"]
        for domain in standard_domains:
            self.domain_states[domain.upper()] = {
                "domain": domain.upper(),
                "status": "READY",
                "session_active": False,
                "current_level": 1,
                "active_app": None,
                "last_action": None,
                "last_action_timestamp": None,
                "failure_reason": None,
                "failure_type": None,
                "affected_component": None,
                "recovery_status": "NONE",
                "recovery_attempt": 0,
                "last_failure_timestamp": None,
                "device_count": 0,
                "online_device_count": 0,
                "devices": {},
                "state_version": 1,
                "metadata": {}
            }

    # -------------------------------------------------------------
    # Session State Management (Backward Compatible & Dynamic)
    # -------------------------------------------------------------
    def get_state(self, session: Optional[str] = None) -> Dict[str, Any]:
        with self._lock:
            if not session or session == "default":
                session = self.active_session_id
            if session not in self.states:
                self.states[session] = {
                    "session_id": session,
                    "active_domain": None,
                    "active_app": None,
                    "active_mode": None,
                    "last_command": None,
                    "previous_command": None,
                    "current_level": 1,
                    "command_history": [],
                    "commands": {},
                    "retry_status": "READY",
                    "retry_attempt": 1,
                    "retry_reason": None,
                    "action_status": None,
                    "action_logs": [],
                    "last_command_id": None,
                    "lifecycle_stage": CommandLifecycleStage.CREATED.value,
                    "sequence_validation": {
                        "previous_command": None,
                        "current_command": None,
                        "status": "READY",
                        "is_valid": None,
                        "allowed_next_commands": ["PUSH", "PULL", "LEFT", "RIGHT", "PUSH_LEFT", "PUSH_RIGHT"],
                        "rejection_reason": None,
                        "current_state": {"current_level": 1, "active_domain": None, "active_app": None}
                    }
                }
            state = self.states[session]
            state["session_id"] = session
            try:
                from core.managers.command_lock_manager import command_lock_manager
                state["command_lock"] = command_lock_manager.get_lock_state(session)
            except Exception:
                pass
            return state

    def reset_state(self, session: Optional[str] = None) -> Dict[str, Any]:
        with self._lock:
            try:
                from core.managers.command_lock_manager import command_lock_manager
                if session and session != self.active_session_id:
                    command_lock_manager.reset_lock(session)
                else:
                    for s in list(self.states.keys()):
                        command_lock_manager.reset_lock(s)
                    command_lock_manager.reset_lock(self.active_session_id)
            except Exception:
                pass

            if session and session in self.states and session != self.active_session_id:
                del self.states[session]
                to_remove = [cid for cid, c in self.active_commands.items() if c.get("session") == session]
                for cid in to_remove:
                    self.active_commands.pop(cid, None)
                self.system_state["active_tasks_count"] = len(self.active_commands)
                return self.get_state(session)
            else:
                self.states.clear()
                self.active_commands.clear()
                self.active_session_id = self._generate_session_id()
                print(f"[SESSION] New session started\n[SESSION] Session ID: {self.active_session_id}")
                logger.info(f"[SESSION] New session started, Session ID: {self.active_session_id}")
                self._init_system_state()
                self._init_domain_states()
                self.system_state["execution_state"] = "RESET"
                self.system_state["system_status"] = "IDLE"
                self.system_state["active_tasks_count"] = 0
                return self.get_state(self.active_session_id)

    def update_state(self, session: str, state_updates: Dict[str, Any]) -> None:
        with self._lock:
            state = self.get_state(session)
            state.update(state_updates)
            self.system_state["last_activity_timestamp"] = time.time()

            # Synchronize active domain / level with domain states
            active_dom = state.get("active_domain")
            if active_dom:
                dom_key = "DESKTOP" if active_dom.upper() == "PYTHON" else active_dom.upper()
                if dom_key in self.domain_states:
                    self.domain_states[dom_key]["session_active"] = True
                    self.domain_states[dom_key]["current_level"] = state.get("current_level", 1)
                    if state.get("active_app"):
                        self.domain_states[dom_key]["active_app"] = state.get("active_app")

    def add_command(self, session: str, command: str, command_id: Optional[str] = None) -> None:
        with self._lock:
            state = self.get_state(session)
            state["last_command"] = command
            if "commands" not in state:
                state["commands"] = {}
            if command_id:
                state["last_command_id"] = command_id
                state["commands"][command_id] = {
                    "command": command,
                    "session_id": session,
                    "timestamp": time.time(),
                    "status": "RECEIVED"
                }
            state["command_history"].append(command)
            if len(state["command_history"]) > 20:
                state["command_history"].pop(0)

            self.system_state["metrics"]["total_commands"] += 1
            self.system_state["last_activity_timestamp"] = time.time()

    def record_performance_metrics(
        self,
        processing_ms: float,
        execution_ms: float,
        stage_breakdown: Optional[Dict[str, float]] = None
    ) -> Dict[str, Any]:
        with self._lock:
            perf = self.system_state.setdefault("performance", {
                "avg_execution_latency_ms": 0.0,
                "recent_execution_latency_ms": 0.0,
                "avg_processing_latency_ms": 0.0,
                "recent_processing_latency_ms": 0.0,
                "total_measured_commands": 0,
                "bottleneck_status": "OPTIMAL",
                "bottleneck_indicators": [],
                "stage_breakdown_ms": {}
            })
            count = perf.get("total_measured_commands", 0) + 1
            perf["total_measured_commands"] = count
            perf["recent_processing_latency_ms"] = round(processing_ms, 2)
            perf["recent_execution_latency_ms"] = round(execution_ms, 2)

            prev_avg_proc = perf.get("avg_processing_latency_ms", 0.0)
            perf["avg_processing_latency_ms"] = round(prev_avg_proc + (processing_ms - prev_avg_proc) / count, 2)

            prev_avg_exec = perf.get("avg_execution_latency_ms", 0.0)
            perf["avg_execution_latency_ms"] = round(prev_avg_exec + (execution_ms - prev_avg_exec) / count, 2)

            if stage_breakdown:
                perf["stage_breakdown_ms"] = {k: round(v, 3) for k, v in stage_breakdown.items()}

            indicators = []
            if perf["avg_processing_latency_ms"] > 25.0:
                indicators.append("HIGH_PROCESSING_LATENCY")
            if perf["avg_execution_latency_ms"] > 250.0:
                indicators.append("HIGH_EXECUTION_LATENCY")
            if self.system_state.get("active_tasks_count", 0) > 10:
                indicators.append("HIGH_CONCURRENCY_LOAD")

            perf["bottleneck_indicators"] = indicators
            perf["bottleneck_status"] = "WARNING" if indicators else "OPTIMAL"
            return dict(perf)

    def get_performance_metrics(self) -> Dict[str, Any]:
        with self._lock:
            return dict(self.system_state.get("performance", {}))

    # -------------------------------------------------------------
    # Failure Reason, Affected Component & Recovery Tracking (Day 7 Member 8)
    # -------------------------------------------------------------
    def record_failure(
        self,
        command_id: Optional[str] = None,
        domain: Optional[str] = None,
        affected_component: str = "Execution Engine",
        failure_type: str = "EXECUTION_ERROR",
        failure_reason: str = "Unknown error occurred",
        error_message: Optional[str] = None,
        error_source: str = "System",
        recovery_status: str = "PENDING",
        session: str = "default",
        metadata: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Records a structured failure event across centralized state, domain states, and active command tracking.
        Preserves fault isolation by isolating domain impact strictly to the affected domain.
        """
        with self._lock:
            now = time.time()
            now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now))
            dom_key = None
            if domain:
                dom_key = "DESKTOP" if domain.upper() == "PYTHON" else domain.upper()

            failure_record = {
                "command_id": command_id,
                "session_id": session,
                "domain": dom_key,
                "affected_domain": dom_key,
                "affected_component": affected_component,
                "failure_type": failure_type,
                "failure_reason": failure_reason,
                "error_message": error_message or failure_reason,
                "error_source": error_source,
                "recovery_status": recovery_status.upper(),
                "recovery_attempts": 1 if recovery_status.upper() in ("RETRYING", "RECOVERING") else 0,
                "max_recovery_attempts": 3,
                "timestamp": now,
                "timestamp_iso": now_iso,
                "metadata": metadata or {}
            }

            # Update system_state failure tracking
            ft = self.system_state.setdefault("failure_tracking", {
                "last_failure": None,
                "active_failures_count": 0,
                "total_failures_recorded": 0,
                "recovery_summary": {
                    "RECOVERED": 0, "RETRYING": 0, "RECOVERING": 0,
                    "RECOVERY_FAILED": 0, "ISOLATED": 0, "PENDING": 0
                },
                "failure_history": []
            })
            ft["last_failure"] = dict(failure_record)
            ft["total_failures_recorded"] = ft.get("total_failures_recorded", 0) + 1

            status_key = recovery_status.upper()
            if status_key in ft.get("recovery_summary", {}):
                ft["recovery_summary"][status_key] += 1

            history = ft.setdefault("failure_history", [])
            history.append(dict(failure_record))
            if len(history) > 50:
                history.pop(0)

            # Update active failures count
            active_statuses = {"PENDING", "RETRYING", "RECOVERING"}
            ft["active_failures_count"] = sum(
                1 for f in history if f.get("recovery_status") in active_statuses
            )

            # Fault Isolation: update only the affected domain
            if dom_key and dom_key in self.domain_states:
                self.domain_states[dom_key]["failure_reason"] = failure_reason
                self.domain_states[dom_key]["failure_type"] = failure_type
                self.domain_states[dom_key]["affected_component"] = affected_component
                self.domain_states[dom_key]["recovery_status"] = recovery_status.upper()
                self.domain_states[dom_key]["recovery_attempt"] = 1 if recovery_status.upper() in ("RETRYING", "RECOVERING") else 0
                self.domain_states[dom_key]["last_failure_timestamp"] = now
                if recovery_status.upper() in ("RECOVERING", "RETRYING"):
                    self.domain_states[dom_key]["status"] = "RECOVERING"
                elif recovery_status.upper() == "RECOVERY_FAILED":
                    self.domain_states[dom_key]["status"] = "DEGRADED"
                elif recovery_status.upper() == "ISOLATED":
                    self.domain_states[dom_key]["status"] = "ISOLATED"

            # Update session state failure_info
            if session in self.states:
                self.states[session]["failure_info"] = dict(failure_record)
                self.states[session]["retry_status"] = recovery_status.upper()
                self.states[session]["retry_reason"] = failure_reason

            # Update active_commands if command_id matches
            if command_id and command_id in self.active_commands:
                self.active_commands[command_id]["failure_info"] = dict(failure_record)
                self.active_commands[command_id]["error"] = failure_reason

            self.system_state["last_activity_timestamp"] = now
            return failure_record

    def update_recovery_status(
        self,
        command_id: Optional[str] = None,
        domain: Optional[str] = None,
        affected_component: Optional[str] = None,
        recovery_status: str = "RECOVERED",
        attempt: int = 1,
        reason: Optional[str] = None,
        session: str = "default"
    ) -> Optional[Dict[str, Any]]:
        """
        Updates the recovery lifecycle stage for an existing failure event.
        Transitions: PENDING -> RETRYING / RECOVERING -> RECOVERED / RECOVERY_FAILED / ISOLATED.
        """
        with self._lock:
            now = time.time()
            dom_key = None
            if domain:
                dom_key = "DESKTOP" if domain.upper() == "PYTHON" else domain.upper()

            status_upper = recovery_status.upper()
            ft = self.system_state.setdefault("failure_tracking", {
                "last_failure": None,
                "active_failures_count": 0,
                "total_failures_recorded": 0,
                "recovery_summary": {
                    "RECOVERED": 0, "RETRYING": 0, "RECOVERING": 0,
                    "RECOVERY_FAILED": 0, "ISOLATED": 0, "PENDING": 0
                },
                "failure_history": []
            })

            # Update last failure if matches or present
            last_f = ft.get("last_failure")
            if last_f:
                if (not command_id or last_f.get("command_id") == command_id) or (not dom_key or last_f.get("domain") == dom_key):
                    last_f["recovery_status"] = status_upper
                    last_f["recovery_attempts"] = attempt
                    if reason:
                        last_f["recovery_reason"] = reason

            if status_upper in ft.get("recovery_summary", {}):
                ft["recovery_summary"][status_upper] += 1

            # Update matching entries in failure_history
            for entry in reversed(ft.get("failure_history", [])):
                if (command_id and entry.get("command_id") == command_id) or (dom_key and entry.get("domain") == dom_key):
                    entry["recovery_status"] = status_upper
                    entry["recovery_attempts"] = attempt
                    if reason:
                        entry["recovery_reason"] = reason
                    break

            active_statuses = {"PENDING", "RETRYING", "RECOVERING"}
            ft["active_failures_count"] = sum(
                1 for f in ft.get("failure_history", []) if f.get("recovery_status") in active_statuses
            )

            # Update domain state
            if dom_key and dom_key in self.domain_states:
                prev_rec = self.domain_states[dom_key].get("recovery_status", "NONE")
                prev_fail = self.domain_states[dom_key].get("failure_reason")
                if prev_rec != "NONE" or prev_fail is not None or status_upper != "RECOVERED":
                    self.domain_states[dom_key]["recovery_status"] = status_upper
                    self.domain_states[dom_key]["recovery_attempt"] = attempt
                    if status_upper == "RECOVERED":
                        self.domain_states[dom_key]["status"] = "READY"
                        self.domain_states[dom_key]["failure_reason"] = None
                    elif status_upper == "RECOVERY_FAILED":
                        self.domain_states[dom_key]["status"] = "DEGRADED"
                    elif status_upper == "ISOLATED":
                        self.domain_states[dom_key]["status"] = "ISOLATED"
                    elif status_upper in ("RETRYING", "RECOVERING"):
                        self.domain_states[dom_key]["status"] = "RECOVERING"

            # Update session state
            if session in self.states:
                self.states[session]["retry_status"] = status_upper
                self.states[session]["retry_attempt"] = attempt
                if reason:
                    self.states[session]["retry_reason"] = reason
                if self.states[session].get("failure_info"):
                    self.states[session]["failure_info"]["recovery_status"] = status_upper
                    self.states[session]["failure_info"]["recovery_attempts"] = attempt

            return ft.get("last_failure")

    def get_failure_tracking(self) -> Dict[str, Any]:
        """Return a snapshot of failure and recovery telemetry."""
        with self._lock:
            return dict(self.system_state.get("failure_tracking", {}))

    def get_domain_health(self, domain: str) -> Dict[str, Any]:
        """Return health and recovery metrics for a specific domain."""
        with self._lock:
            dom_key = "DESKTOP" if domain.upper() == "PYTHON" else domain.upper()
            dom_state = self.get_domain_state(dom_key)
            return {
                "domain": dom_key,
                "status": dom_state.get("status", "READY"),
                "failure_reason": dom_state.get("failure_reason"),
                "failure_type": dom_state.get("failure_type"),
                "affected_component": dom_state.get("affected_component"),
                "recovery_status": dom_state.get("recovery_status", "NONE"),
                "recovery_attempt": dom_state.get("recovery_attempt", 0),
                "last_failure_timestamp": dom_state.get("last_failure_timestamp")
            }

    def clear_failure_history(self, domain: Optional[str] = None) -> None:
        """Clear failure records for a domain or globally."""
        with self._lock:
            ft = self.system_state.setdefault("failure_tracking", {
                "last_failure": None,
                "active_failures_count": 0,
                "total_failures_recorded": 0,
                "recovery_summary": {
                    "RECOVERED": 0, "RETRYING": 0, "RECOVERING": 0,
                    "RECOVERY_FAILED": 0, "ISOLATED": 0, "PENDING": 0
                },
                "failure_history": []
            })
            if domain:
                dom_key = "DESKTOP" if domain.upper() == "PYTHON" else domain.upper()
                ft["failure_history"] = [f for f in ft.get("failure_history", []) if f.get("domain") != dom_key]
                if ft.get("last_failure") and ft["last_failure"].get("domain") == dom_key:
                    ft["last_failure"] = None
                if dom_key in self.domain_states:
                    self.domain_states[dom_key]["failure_reason"] = None
                    self.domain_states[dom_key]["failure_type"] = None
                    self.domain_states[dom_key]["affected_component"] = None
                    self.domain_states[dom_key]["recovery_status"] = "NONE"
                    self.domain_states[dom_key]["recovery_attempt"] = 0
                    self.domain_states[dom_key]["status"] = "READY"
            else:
                ft["failure_history"].clear()
                ft["last_failure"] = None
                ft["active_failures_count"] = 0
                ft["recovery_summary"] = {
                    "RECOVERED": 0, "RETRYING": 0, "RECOVERING": 0,
                    "RECOVERY_FAILED": 0, "ISOLATED": 0, "PENDING": 0
                }
                for dom in self.domain_states.values():
                    dom["failure_reason"] = None
                    dom["failure_type"] = None
                    dom["affected_component"] = None
                    dom["recovery_status"] = "NONE"
                    dom["recovery_attempt"] = 0
                    dom["status"] = "READY"

    def get_session_lifecycle(self, session: str = "default") -> List[Dict[str, Any]]:
        """Retrieve full lifecycle audit trail for session."""
        return lifecycle_tracker.export_audit_trail(session)

    # -------------------------------------------------------------
    # Global System State Management
    # -------------------------------------------------------------
    def get_system_state(self) -> Dict[str, Any]:
        with self._lock:
            # Sync active_tasks_count
            self.system_state["active_tasks_count"] = len(self.active_commands)
            return dict(self.system_state)

    def update_system_state(self, updates: Dict[str, Any]) -> Dict[str, Any]:
        with self._lock:
            if "status" in updates:
                self.system_state["system_status"] = updates["status"]
            if "system_status" in updates:
                self.system_state["system_status"] = updates["system_status"]
            if "execution_state" in updates:
                self.system_state["execution_state"] = updates["execution_state"]
            if "metrics" in updates and isinstance(updates["metrics"], dict):
                self.system_state["metrics"].update(updates["metrics"])
            for k, v in updates.items():
                if k not in ("status", "system_status", "execution_state", "metrics"):
                    self.system_state[k] = v
            self.system_state["last_activity_timestamp"] = time.time()
            snapshot = dict(self.system_state)

        # Schedule WebSocket STATE_UPDATE broadcast outside the lock.
        # Matches the pattern used in api/telemetry_routes.py (record_telemetry_packet).
        try:
            loop = asyncio.get_running_loop()
            if loop.is_running():
                from core.communication.websocket_server import websocket_server
                loop.create_task(
                    websocket_server.broadcast_state_update(
                        state_payload=snapshot,
                        session_id=self.active_session_id,
                        domain="CORE",
                    )
                )
        except RuntimeError:
            pass  # No running event loop (sync context / tests) — safe no-op.

        return snapshot

    # -------------------------------------------------------------
    # Domain State Management
    # -------------------------------------------------------------
    def get_domain_state(self, domain: str, session: Optional[str] = None) -> Dict[str, Any]:
        with self._lock:
            dom_key = "DESKTOP" if domain.upper() == "PYTHON" else domain.upper()
            if dom_key not in self.domain_states:
                self.domain_states[dom_key] = {
                    "domain": dom_key,
                    "status": "READY",
                    "session_active": False,
                    "current_level": 1,
                    "active_app": None,
                    "last_action": None,
                    "last_action_timestamp": None,
                    "failure_reason": None,
                    "failure_type": None,
                    "affected_component": None,
                    "recovery_status": "NONE",
                    "recovery_attempt": 0,
                    "last_failure_timestamp": None,
                    "metadata": {}
                }
            return dict(self.domain_states[dom_key])

    def update_domain_state(self, domain: str, updates: Dict[str, Any], session: Optional[str] = None) -> Dict[str, Any]:
        with self._lock:
            dom_key = "DESKTOP" if domain.upper() == "PYTHON" else domain.upper()
            dom_state = self.get_domain_state(dom_key)
            dom_state.update(updates)
            dom_state["last_action_timestamp"] = time.time()
            self.domain_states[dom_key] = dom_state
            return dict(dom_state)

    # -------------------------------------------------------------
    # Authoritative IoT & Device State Synchronization (Task 6)
    # -------------------------------------------------------------
    def sync_device_state(self, device_data: Union[Any, Dict[str, Any]], force: bool = False) -> Dict[str, Any]:
        """
        Synchronize standardized device state with central state manager.
        Enforces monotonic timestamps & state versions to prevent stale updates.
        Updates authoritative domain aggregates and emits WebSocket envelopes.
        """
        if hasattr(device_data, "model_dump"):
            state_dict = device_data.model_dump(exclude_none=True)
        elif hasattr(device_data, "to_dict"):
            state_dict = device_data.to_dict()
        elif isinstance(device_data, dict):
            state_dict = dict(device_data)
        else:
            state_dict = {"raw": str(device_data)}

        device_id = state_dict.get("device_id") or state_dict.get("deviceId")
        if not device_id:
            return state_dict

        domain = str(state_dict.get("domain", "IOT")).upper()

        with self._lock:
            # Stale update prevention: monotonic timestamp & version check
            if device_id in self.device_registry and not force:
                existing = self.device_registry[device_id]
                existing_ts = float(existing.get("last_seen_timestamp", 0.0) or 0.0)
                existing_ver = int(existing.get("state_version", existing.get("metadata", {}).get("state_version", 1)) or 1)
                
                new_ts = float(state_dict.get("last_seen_timestamp", 0.0) or 0.0)
                new_ver = int(state_dict.get("state_version", state_dict.get("metadata", {}).get("state_version", 1)) or 1)

                if new_ts > 0 and existing_ts > 0 and new_ts < existing_ts and new_ver <= existing_ver:
                    logger.warning(
                        f"[STATE_MANAGER] Stale update rejected for device '{device_id}' "
                        f"(incoming ts {new_ts} < current ts {existing_ts})"
                    )
                    return dict(existing)

            # Store in central device registry
            self.device_registry[device_id] = state_dict

            # Update authoritative domain state
            dom_key = "DESKTOP" if domain == "PYTHON" else domain
            if dom_key not in self.domain_states:
                self._init_domain_states()
            
            dom_state = self.domain_states.setdefault(dom_key, {
                "domain": dom_key,
                "status": "READY",
                "device_count": 0,
                "online_device_count": 0,
                "devices": {},
                "state_version": 1
            })

            domain_devices = [d for d in self.device_registry.values() if str(d.get("domain", "IOT")).upper() in (dom_key, "PYTHON" if dom_key == "DESKTOP" else dom_key)]
            dom_state["device_count"] = len(domain_devices)
            dom_state["online_device_count"] = sum(
                1 for d in domain_devices
                if str(d.get("connection_status", "")).upper() in ("ONLINE", "CONNECTED")
                or d.get("online") is True
            )
            dom_state["devices"] = {
                d.get("device_id", "unknown"): d.get("connection_status", "ONLINE")
                for d in domain_devices if "device_id" in d
            }
            dom_state["last_action_timestamp"] = state_dict.get("last_seen_timestamp", time.time())
            dom_state["state_version"] = dom_state.get("state_version", 1) + 1
            dom_state["last_device_updated"] = device_id
            dom_state["last_action"] = f"DEVICE_STATE_SYNC:{device_id}"

            self.system_state["last_activity_timestamp"] = time.time()
            snapshot = dict(state_dict)

        # Broadcast update over WebSocket
        try:
            loop = asyncio.get_running_loop()
            if loop.is_running():
                from core.communication.websocket_server import websocket_server
                envelope = websocket_server.create_envelope(
                    msg_type="DEVICE_STATE",
                    source_domain=domain,
                    source_id=device_id,
                    payload=snapshot
                )
                loop.create_task(websocket_server.broadcast_envelope(envelope))
        except RuntimeError:
            try:
                from core.communication.websocket_server import websocket_server
                envelope = websocket_server.create_envelope(
                    msg_type="DEVICE_STATE",
                    source_domain=domain,
                    source_id=device_id,
                    payload=snapshot
                )
                websocket_server.broadcast_envelope_sync(envelope)
            except Exception:
                pass
        except Exception:
            pass

        return snapshot

    def get_device_state(self, device_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve authoritative device state by device ID."""
        with self._lock:
            dev = self.device_registry.get(device_id)
            return dict(dev) if dev else None

    def get_all_devices(self, domain: Optional[str] = None) -> List[Dict[str, Any]]:
        """Retrieve all registered device states with optional domain filter."""
        with self._lock:
            if domain:
                dom_norm = domain.upper()
                return [
                    dict(d) for d in self.device_registry.values()
                    if str(d.get("domain", "")).upper() == dom_norm
                ]
            return [dict(d) for d in self.device_registry.values()]

    def remove_device(self, device_id: str) -> bool:
        """Remove a device from the central registry."""
        with self._lock:
            if device_id in self.device_registry:
                del self.device_registry[device_id]
                return True
            return False

    # -------------------------------------------------------------
    # Active In-Flight Command Lifecycle Management
    # -------------------------------------------------------------
    def register_active_command(
        self,
        command_id: str,
        command: str,
        domain: Optional[str] = None,
        app: Optional[str] = None,
        session: str = "default",
        metadata: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        with self._lock:
            now = time.time()
            now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now))
            cmd_info = {
                "command_id": command_id,
                "command": command,
                "domain": domain,
                "app": app,
                "session": session,
                "status": "RUNNING",
                "registered_at": now,
                "started_at": now,
                "started_at_iso": now_iso,
                "completed_at": None,
                "completed_at_iso": None,
                "duration_ms": None,
                "duration_s": None,
                "updated_at": now,
                "result": None,
                "error": None,
                "metadata": metadata or {}
            }
            self.active_commands[command_id] = cmd_info
            self.system_state["active_tasks_count"] = len(self.active_commands)
            self.system_state["execution_state"] = "EXECUTING"
            self.system_state["system_status"] = "RUNNING"
            self.system_state["last_activity_timestamp"] = now

            if domain:
                dom_key = "DESKTOP" if domain.upper() == "PYTHON" else domain.upper()
                if dom_key in self.domain_states:
                    self.domain_states[dom_key]["status"] = "BUSY"
                    if app:
                        self.domain_states[dom_key]["active_app"] = app

            return dict(cmd_info)

    def update_command_state(
        self,
        command_id: str,
        status: Optional[str] = None,
        result: Optional[Any] = None,
        error: Optional[str] = None,
        session: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        with self._lock:
            if command_id not in self.active_commands:
                # If command already finalized or untracked, update metrics safely
                if status:
                    st_upper = status.upper()
                    if st_upper in ("SUCCESS", "COMPLETED"):
                        self.system_state["metrics"]["successful"] += 1
                        self.system_state["execution_state"] = "COMPLETED"
                    elif st_upper in ("FAILED", "ERROR"):
                        self.system_state["metrics"]["failed"] += 1
                        self.system_state["execution_state"] = "FAILED"
                    elif st_upper == "CANCELLED":
                        self.system_state["metrics"]["cancelled"] += 1
                        self.system_state["execution_state"] = "CANCELLED"
                    elif st_upper in ("TIMED_OUT", "TIMEOUT"):
                        self.system_state["metrics"]["timed_out"] += 1
                        self.system_state["execution_state"] = "TIMED_OUT"
                return None

            cmd_info = self.active_commands[command_id]
            if status:
                st_upper = status.upper()
                cmd_info["status"] = status
                if st_upper in ("SUCCESS", "COMPLETED"):
                    self.system_state["metrics"]["successful"] += 1
                    self.system_state["execution_state"] = "COMPLETED"
                elif st_upper in ("FAILED", "ERROR"):
                    self.system_state["metrics"]["failed"] += 1
                    self.system_state["execution_state"] = "FAILED"
                elif st_upper == "CANCELLED":
                    self.system_state["metrics"]["cancelled"] += 1
                    self.system_state["execution_state"] = "CANCELLED"
                elif st_upper in ("TIMED_OUT", "TIMEOUT"):
                    self.system_state["metrics"]["timed_out"] += 1
                    self.system_state["execution_state"] = "TIMED_OUT"
                elif st_upper == "EXECUTING":
                    self.system_state["execution_state"] = "EXECUTING"

                # Record terminal completion timestamp and execution duration
                if st_upper in ("SUCCESS", "COMPLETED", "FAILED", "ERROR", "CANCELLED", "TIMED_OUT", "TIMEOUT"):
                    now = time.time()
                    if cmd_info.get("completed_at") is None:
                        cmd_info["completed_at"] = now
                        cmd_info["completed_at_iso"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now))
                        st_time = cmd_info.get("started_at", cmd_info.get("registered_at", now))
                        cmd_info["duration_ms"] = round((now - st_time) * 1000.0, 2)
                        cmd_info["duration_s"] = round(cmd_info["duration_ms"] / 1000.0, 4)

            if result is not None:
                cmd_info["result"] = result
            if error is not None:
                cmd_info["error"] = error

            cmd_info["updated_at"] = time.time()
            self.system_state["last_activity_timestamp"] = time.time()
            return dict(cmd_info)

    def remove_active_command(self, command_id: str, session: Optional[str] = None) -> bool:
        with self._lock:
            if command_id in self.active_commands:
                cmd_info = self.active_commands.pop(command_id)
                self.system_state["active_tasks_count"] = len(self.active_commands)
                if len(self.active_commands) == 0:
                    if self.system_state["execution_state"] == "EXECUTING":
                        self.system_state["execution_state"] = "IDLE"
                    self.system_state["system_status"] = "IDLE"
                
                domain = cmd_info.get("domain")
                if domain:
                    dom_key = "DESKTOP" if domain.upper() == "PYTHON" else domain.upper()
                    # Check if any remaining active command uses this domain
                    domain_still_busy = any(
                        c.get("domain", "").upper() in (dom_key, "PYTHON" if dom_key == "DESKTOP" else dom_key)
                        for c in self.active_commands.values()
                    )
                    if not domain_still_busy and dom_key in self.domain_states:
                        self.domain_states[dom_key]["status"] = "READY"

                return True
            return False

    def get_active_commands(self, session: Optional[str] = None) -> List[Dict[str, Any]]:
        with self._lock:
            if session:
                return [dict(c) for c in self.active_commands.values() if c.get("session") == session]
            return [dict(c) for c in self.active_commands.values()]

    def get_command_timing(self, command_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve execution timing and duration information for a command."""
        with self._lock:
            timing = lifecycle_tracker.get_execution_timing(command_id)
            if timing:
                return timing
            if command_id in self.active_commands:
                cmd = self.active_commands[command_id]
                return {
                    "command_id": command_id,
                    "session_id": cmd.get("session"),
                    "command": cmd.get("command"),
                    "domain": cmd.get("domain"),
                    "status": cmd.get("status"),
                    "created_at": cmd.get("registered_at"),
                    "started_at": cmd.get("started_at"),
                    "started_at_iso": cmd.get("started_at_iso"),
                    "completed_at": cmd.get("completed_at"),
                    "completed_at_iso": cmd.get("completed_at_iso"),
                    "duration_ms": cmd.get("duration_ms"),
                    "duration_s": cmd.get("duration_s"),
                }
            return None

    # -------------------------------------------------------------
    # State Reset and Recovery
    # -------------------------------------------------------------
    def clear_stale_state(self, max_age_seconds: float = 300.0) -> int:
        with self._lock:
            now = time.time()
            stale_ids = [
                cid for cid, c in self.active_commands.items()
                if (now - c.get("updated_at", c.get("registered_at", now))) > max_age_seconds
            ]
            for cid in stale_ids:
                self.active_commands.pop(cid, None)
            self.system_state["active_tasks_count"] = len(self.active_commands)
            return len(stale_ids)

    # -------------------------------------------------------------
    # IoT Central Device State Synchronization (Tasks 5, 6)
    # -------------------------------------------------------------
    def sync_device_state(self, device_state: Any, force: bool = False) -> Optional[Dict[str, Any]]:
        """
        Synchronize IoT device state into the centralized state registry with monotonic version and timestamp validation.
        Prevents stale/out-of-order updates from overwriting newer device states.
        """
        with self._lock:
            if hasattr(device_state, "to_dict"):
                state_dict = device_state.to_dict()
            elif hasattr(device_state, "model_dump"):
                state_dict = device_state.model_dump()
            elif isinstance(device_state, dict):
                state_dict = dict(device_state)
            else:
                try:
                    from dataclasses import asdict
                    state_dict = asdict(device_state)
                except Exception:
                    state_dict = getattr(device_state, "__dict__", {})

            device_id = state_dict.get("device_id")
            if not device_id:
                logger.warning("[STATE MANAGER] sync_device_state rejected: missing device_id")
                return None

            incoming_ts = state_dict.get("last_seen_timestamp") or state_dict.get("timestamp")
            if isinstance(incoming_ts, (int, float)):
                incoming_time = float(incoming_ts)
            else:
                incoming_time = time.time()

            incoming_version = int(state_dict.get("state_version", 1))

            existing = self.device_registry.get(device_id)
            if existing and not force:
                existing_ts = existing.get("last_seen_timestamp") or existing.get("timestamp", 0.0)
                if isinstance(existing_ts, (int, float)):
                    existing_time = float(existing_ts)
                else:
                    existing_time = 0.0
                existing_version = int(existing.get("state_version", 1))

                # Rejection check: incoming update is older than existing state
                if incoming_time < existing_time or incoming_version < existing_version:
                    logger.warning(
                        f"[STATE MANAGER] Dropped stale update for device {device_id} "
                        f"(incoming ts={incoming_time}, ver={incoming_version} vs existing ts={existing_time}, ver={existing_version})"
                    )
                    return None

            # Update device registry
            self.device_registry[device_id] = state_dict

            # Update IOT domain state aggregate
            if "IOT" in self.domain_states:
                iot_dom = self.domain_states["IOT"]
                iot_dom["device_count"] = len(self.device_registry)
                iot_dom["online_device_count"] = sum(
                    1 for d in self.device_registry.values()
                    if d.get("online") is True
                    or str(d.get("status", "")).upper() == "ONLINE"
                    or str(d.get("connection_status", "")).upper() == "ONLINE"
                )
                iot_dom["devices"][device_id] = {
                    "online": state_dict.get("online", True if str(state_dict.get("connection_status", "")).upper() == "ONLINE" else False),
                    "status": state_dict.get("status") or str(state_dict.get("connection_status", "UNKNOWN")),
                    "last_seen": state_dict.get("last_seen", incoming_time),
                    "relays": state_dict.get("relays") or state_dict.get("state", {}),
                    "state_version": incoming_version
                }
                iot_dom["state_version"] = iot_dom.get("state_version", 1) + 1
                iot_dom["last_action_timestamp"] = incoming_time

            self.system_state["last_activity_timestamp"] = time.time()
            return dict(state_dict)

    def get_device_state(self, device_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve authoritative synchronized state for a specific IoT device."""
        with self._lock:
            dev = self.device_registry.get(device_id)
            return dict(dev) if dev else None

    def get_all_devices(self) -> List[Dict[str, Any]]:
        """Retrieve list of all registered IoT device states."""
        with self._lock:
            return [dict(d) for d in self.device_registry.values()]

    def remove_device(self, device_id: str) -> bool:
        """Remove a device from central registry."""
        with self._lock:
            if device_id in self.device_registry:
                self.device_registry.pop(device_id)
                if "IOT" in self.domain_states:
                    self.domain_states["IOT"]["devices"].pop(device_id, None)
                    self.domain_states["IOT"]["device_count"] = len(self.device_registry)
                    self.domain_states["IOT"]["online_device_count"] = sum(
                        1 for d in self.device_registry.values()
                        if d.get("online") is True
                        or str(d.get("status", "")).upper() == "ONLINE"
                        or str(d.get("connection_status", "")).upper() == "ONLINE"
                    )
                return True
            return False


state_manager = StateManager()

