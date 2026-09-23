import time
import hashlib
import json
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Any, Set, Tuple

try:
    from core.logging.logger import logger
except ImportError:
    logger = logging.getLogger("conflict_manager")

from core.validation.invalid_combination_rules import OPPOSING_PAIRS, MOVEMENT_COMMANDS


class DecisionStatus(str, Enum):
    ALLOWED = "ALLOWED"
    DUPLICATE = "DUPLICATE"
    CONFLICT = "CONFLICT"
    REJECTED = "REJECTED"
    DEFERRED = "DEFERRED"


@dataclass
class DecisionResult:
    status: DecisionStatus
    is_allowed: bool
    reason: Optional[str] = None
    conflicts: List[str] = field(default_factory=list)
    priority: int = 1

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status.value.lower(),
            "is_allowed": self.is_allowed,
            "reason": self.reason,
            "conflicts": self.conflicts,
            "priority": self.priority
        }


class ConflictManager:
    """
    Manages duplicate and conflict command prevention across execution cycles.
    Acts as an intelligent control point between command routing and plugin execution.
    """

    DEFAULT_DEBOUNCE_SECONDS = 0.5

    def __init__(self, debounce_interval: float = DEFAULT_DEBOUNCE_SECONDS):
        self.debounce_interval = debounce_interval
        # session -> key -> metadata
        self._active_commands: Dict[str, Dict[str, Dict[str, Any]]] = {}
        # session -> key -> last_seen_timestamp
        self._recent_commands: Dict[str, Dict[str, float]] = {}

    @staticmethod
    def compute_fingerprint(
        command: str,
        domain: Optional[str] = None,
        app: Optional[str] = None,
        device_id: Optional[str] = None,
        payload: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Generate a unique deterministic fingerprint for a command and its target scope.
        """
        norm_cmd = str(command).strip().upper()
        norm_domain = str(domain or "").strip().upper()
        norm_app = str(app or "").strip().upper()
        norm_device = str(device_id or "").strip()

        # Canonical domain mapping (Desktop / Python / Media cross-domain scope)
        if norm_domain in ("PYTHON", "DESKTOP", "MEDIA") and norm_app in ("YOUTUBE", "JIOSAAVN", "CHROME", "NOTEPAD", "GMAIL"):
            norm_domain = "DESKTOP_MEDIA"
        elif norm_domain == "PYTHON":
            norm_domain = "DESKTOP"

        # Canonical action mapping for common media/desktop actions
        if norm_app == "YOUTUBE":
            media_action_map = {
                "PUSH": "PREVIOUS_VIDEO",
                "PREVIOUS": "PREVIOUS_VIDEO",
                "PREVIOUS_VIDEO": "PREVIOUS_VIDEO",
                "PULL": "NEXT_VIDEO",
                "NEXT": "NEXT_VIDEO",
                "NEXT_VIDEO": "NEXT_VIDEO",
                "LEFT": "TOGGLE_PLAY_PAUSE",
                "TOGGLE_PLAY_PAUSE": "TOGGLE_PLAY_PAUSE",
                "RIGHT": "SEARCH",
                "SEARCH": "SEARCH"
            }
            norm_cmd = media_action_map.get(norm_cmd, norm_cmd)
        elif norm_app == "JIOSAAVN":
            media_action_map = {
                "PUSH": "PREVIOUS_TRACK",
                "PREVIOUS": "PREVIOUS_TRACK",
                "PULL": "NEXT_TRACK",
                "NEXT": "NEXT_TRACK",
                "LEFT": "TOGGLE_PLAY_PAUSE",
                "TOGGLE_PLAY_PAUSE": "TOGGLE_PLAY_PAUSE",
                "RIGHT": "SEARCH",
                "SEARCH": "SEARCH"
            }
            norm_cmd = media_action_map.get(norm_cmd, norm_cmd)

        # Clean payload to only include discriminating parameters (exclude non-discriminating/metadata keys)
        clean_payload = {}
        if payload and isinstance(payload, dict):
            metadata_keys = {"timestamp", "created_at", "started_at", "command_id", "confidence", "domain", "app", "source", "device_id"}
            for k, v in payload.items():
                if k not in metadata_keys:
                    clean_payload[k] = v

        payload_str = json.dumps(clean_payload, sort_keys=True)
        raw_key = f"{norm_domain}:{norm_app}:{norm_device}:{norm_cmd}:{payload_str}"
        return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()[:16]

    @staticmethod
    def get_effective_priority(command: str, explicit_priority: Optional[int] = None) -> int:
        """
        Determine effective priority for a command.
        Emergency/safety commands (e.g. STOP) receive top priority.
        """
        cmd_upper = str(command).strip().upper()
        if cmd_upper == "STOP":
            return max(10, explicit_priority or 10)
        if explicit_priority is not None:
            return explicit_priority
        return 1

    @staticmethod
    def _normalize_scope(domain: Optional[str], app: Optional[str], device_id: Optional[str]) -> str:
        d = str(domain or "").strip().upper()
        a = str(app or "").strip().upper()
        dev = str(device_id or "").strip()
        if d in ("PYTHON", "DESKTOP", "MEDIA") and a in ("YOUTUBE", "JIOSAAVN", "CHROME", "NOTEPAD", "GMAIL"):
            d = "DESKTOP_MEDIA"
        elif d == "PYTHON":
            d = "DESKTOP"
        return f"{d}:{a}:{dev}"

    def evaluate(
        self,
        command: str,
        domain: Optional[str] = None,
        app: Optional[str] = None,
        device_id: Optional[str] = None,
        payload: Optional[Dict[str, Any]] = None,
        session: str = "default",
        priority: Optional[int] = None
    ) -> DecisionResult:
        """
        Evaluate an incoming command for duplicate and conflict prevention.
        """
        cmd_upper = str(command).strip().upper()
        now = time.time()
        effective_priority = self.get_effective_priority(cmd_upper, priority)
        fingerprint = self.compute_fingerprint(cmd_upper, domain, app, device_id, payload)

        active_map = self._active_commands.setdefault(session, {})
        recent_map = self._recent_commands.setdefault(session, {})

        # Clean stale recent commands
        stale_keys = [k for k, t in recent_map.items() if now - t > self.debounce_interval * 4]
        for k in stale_keys:
            recent_map.pop(k, None)

        # 1. DUPLICATE CHECK
        # A command is a duplicate if it is currently executing or was submitted within the debounce window on the same target
        if fingerprint in active_map:
            active_info = active_map[fingerprint]
            reason = f"Duplicate command '{cmd_upper}' is currently executing on target {domain or 'DEFAULT'}/{app or device_id or 'DEFAULT'}."
            logger.info(f"[ConflictManager] Duplicate prevented (active): {reason}")
            return DecisionResult(
                status=DecisionStatus.DUPLICATE,
                is_allowed=False,
                reason=reason,
                conflicts=[cmd_upper],
                priority=effective_priority
            )

        last_seen = recent_map.get(fingerprint)
        if last_seen and (now - last_seen < self.debounce_interval):
            time_diff = now - last_seen
            reason = f"Duplicate command '{cmd_upper}' received within debounce window ({time_diff:.3f}s < {self.debounce_interval}s)."
            logger.info(f"[ConflictManager] Duplicate prevented (debounce): {reason}")
            return DecisionResult(
                status=DecisionStatus.DUPLICATE,
                is_allowed=False,
                reason=reason,
                conflicts=[cmd_upper],
                priority=effective_priority
            )

        # 2. CONFLICT CHECK
        # Inspect active commands on the same target scope (domain / app / device)
        target_scope = self._normalize_scope(domain, app, device_id)

        all_opposing = list(OPPOSING_PAIRS) + [
            ({"PREVIOUS", "NEXT"}, "Conflicting media track navigation"),
            ({"PREVIOUS_VIDEO", "NEXT_VIDEO"}, "Conflicting video navigation"),
            ({"PREVIOUS_TRACK", "NEXT_TRACK"}, "Conflicting audio navigation"),
            ({"PLAY", "STOP"}, "Conflicting playback commands"),
            ({"PLAY", "PAUSE"}, "Conflicting playback commands"),
            ({"FORWARD", "BACKWARD"}, "Conflicting directional movement"),
            ({"LEFT", "RIGHT"}, "Conflicting directional movement"),
            ({"PUSH", "PULL"}, "Conflicting directional movement"),
        ]

        media_action_aliases = {
            "PUSH": "PREVIOUS",
            "PREVIOUS_VIDEO": "PREVIOUS",
            "PREVIOUS_TRACK": "PREVIOUS",
            "PULL": "NEXT",
            "NEXT_VIDEO": "NEXT",
            "NEXT_TRACK": "NEXT",
        }

        for act_fp, act_data in list(active_map.items()):
            act_scope = self._normalize_scope(act_data.get('domain'), act_data.get('app'), act_data.get('device_id'))
            if act_scope != target_scope:
                continue

            act_cmd = act_data.get("command", "")
            act_priority = act_data.get("priority", 1)

            # Rule A: STOP vs Movement / Playback
            if cmd_upper == "STOP" and (act_cmd in MOVEMENT_COMMANDS or act_cmd in ("PLAY", "PAUSE", "PREVIOUS", "NEXT")):
                # STOP has higher priority; allows STOP and overrides active movement
                logger.info(f"[ConflictManager] STOP command overrides active command '{act_cmd}' on {target_scope}")
                continue
            elif act_cmd == "STOP" and (cmd_upper in MOVEMENT_COMMANDS or cmd_upper in ("PLAY", "PAUSE", "PREVIOUS", "NEXT")):
                if effective_priority <= act_priority:
                    reason = f"Conflicting command: active STOP on {target_scope} takes priority over '{cmd_upper}'"
                    logger.warning(f"[ConflictManager] Conflict rejected: {reason}")
                    return DecisionResult(
                        status=DecisionStatus.CONFLICT,
                        is_allowed=False,
                        reason=reason,
                        conflicts=[cmd_upper, act_cmd],
                        priority=effective_priority
                    )

            # Rule B: Opposing Directional / Media Pairs
            cmd_alias = media_action_aliases.get(cmd_upper, cmd_upper)
            act_alias = media_action_aliases.get(act_cmd, act_cmd)
            raw_pair = {cmd_upper, act_cmd}
            alias_pair = {cmd_alias, act_alias}

            for pair_set, pair_reason in all_opposing:
                if pair_set == raw_pair or pair_set == alias_pair:
                    if effective_priority > act_priority:
                        logger.info(f"[ConflictManager] Higher priority command '{cmd_upper}' ({effective_priority}) overrides '{act_cmd}' ({act_priority})")
                        continue
                    else:
                        reason = f"Conflicting directional command: '{cmd_upper}' opposes active '{act_cmd}' ({pair_reason})"
                        logger.warning(f"[ConflictManager] Conflict rejected: {reason}")
                        return DecisionResult(
                            status=DecisionStatus.CONFLICT,
                            is_allowed=False,
                            reason=reason,
                            conflicts=sorted(list(raw_pair)),
                            priority=effective_priority
                        )

        # 3. ALLOWED
        return DecisionResult(
            status=DecisionStatus.ALLOWED,
            is_allowed=True,
            reason=None,
            conflicts=[],
            priority=effective_priority
        )

    def register_active(
        self,
        command: str,
        domain: Optional[str] = None,
        app: Optional[str] = None,
        device_id: Optional[str] = None,
        payload: Optional[Dict[str, Any]] = None,
        session: str = "default",
        priority: Optional[int] = None
    ) -> str:
        """
        Register a command as currently active in the execution cycle.
        """
        cmd_upper = str(command).strip().upper()
        fingerprint = self.compute_fingerprint(cmd_upper, domain, app, device_id, payload)
        effective_priority = self.get_effective_priority(cmd_upper, priority)
        now = time.time()

        active_map = self._active_commands.setdefault(session, {})
        recent_map = self._recent_commands.setdefault(session, {})

        active_map[fingerprint] = {
            "command": cmd_upper,
            "domain": str(domain or "").strip().upper(),
            "app": str(app or "").strip().upper(),
            "device_id": str(device_id or "").strip(),
            "priority": effective_priority,
            "started_at": now
        }
        recent_map[fingerprint] = now
        return fingerprint

    def release_active(self, fingerprint: str, session: str = "default"):
        """
        Release a command from active execution cycle once completed or failed.
        """
        active_map = self._active_commands.get(session)
        if active_map and fingerprint in active_map:
            active_map.pop(fingerprint, None)

    def clear_cycle(self, session: Optional[str] = None):
        """
        Clear active command states for a session or globally.
        """
        if session:
            self._active_commands.pop(session, None)
            self._recent_commands.pop(session, None)
        else:
            self._active_commands.clear()
            self._recent_commands.clear()


conflict_manager = ConflictManager()
