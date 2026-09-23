"""Command Window for Cortex mental command processing.

This component implements a time-based windowing mechanism that collects
Cortex mental commands and determines whether they represent single-line
or double-line commands based on the number of commands received within
the window duration.

The window determines HOW MANY commands were received.
The FSM determines WHAT those commands mean based on hierarchy level.
"""

import time
import logging
import threading
from typing import Callable, List, Tuple, Optional, Dict, Any

from .states import PRIMITIVE_COMMANDS


class CommandWindow:
    """Time-based window for collecting Cortex mental commands.
    
    The window collects commands for a specified duration and then
    determines if they represent a single-line or double-line command.
    Reuses 0.35 confidence threshold and 4-second grouping per updated spec.
    Centralized via COMMAND_WINDOW_SECONDS = 4.0
    """
    
    def __init__(
        self,
        window_duration: float = 4.0,
        confidence_threshold: float = 0.35,
        command_callback: Callable[[List[str]], None] = None,
        logger: Optional[logging.Logger] = None,
    ):
        """Initialize command window.
        
        Args:
            window_duration: Duration in seconds to collect commands (default 4.0 per spec)
            confidence_threshold: Minimum confidence for valid commands (default 0.35)
            command_callback: Function to call with command list when window closes
            logger: Logger instance (uses default if None)
        """
        self.window_duration = window_duration
        self.confidence_threshold = confidence_threshold
        self.command_callback = command_callback
        self.logger = logger or logging.getLogger(__name__)
        
        # Window state
        self.window_active = False
        self.window_start_time = None
        self.collected_commands: List[Tuple[str, float]] = []  # (command, confidence)
        self.window_timer = None
        self.max_commands_per_window = 2
        
        # Threading for window timer
        self.window_lock = threading.Lock()
    
    def add_command(self, command: str, confidence: float) -> bool:
        """Add a Cortex command to the current window.
        
        Args:
            command: The mental command (push/pull/left/right)
            confidence: The command confidence/power (0.0 to 1.0)
            
        Returns:
            True if command was added to window, False if rejected
        """
        # === NEUTRAL FILTERING (explicit, before window) ===
        norm = command.strip().lower() if isinstance(command, str) else ""
        if norm == "neutral":
            self.logger.info(f"[FILTER] NEUTRAL ignored (confidence={confidence:.3f}) - not entering window")
            return False
        # Validate command
        if command not in PRIMITIVE_COMMANDS:
            self.logger.warning(f"[WINDOW] Unknown command: {command}")
            return False
        
        # Apply confidence threshold
        if confidence < self.confidence_threshold:
            self.logger.info(
                f"[WINDOW] Command rejected: {command} (confidence={confidence:.3f} < threshold={self.confidence_threshold})"
            )
            return False
        
        with self.window_lock:
            # If no window is active, start a new one
            if not self.window_active:
                self._start_window()
            
            # Dedup: suppress repeated same-command within same window (live BCI produces PUSH,PUSH,PUSH for one intention)
            # Preserve ordered different doubles: PUSH+RIGHT must not be collapsed
            if len(self.collected_commands) == 1 and self.collected_commands[0][0] == command:
                self.logger.info(f"[COMMAND] Duplicate {command} suppressed (same as previous within window)")
                return False
            
            # Check if we've reached max commands for this window
            if len(self.collected_commands) >= self.max_commands_per_window:
                self.logger.warning(
                    f"[WINDOW] Window full ({self.max_commands_per_window} commands), ignoring: {command}"
                )
                return False
            
            # Add command to window
            self.collected_commands.append((command, confidence))
            self.logger.info(
                f"[WINDOW] Command added: {command} (confidence={confidence:.3f}, total={len(self.collected_commands)})"
            )
            self.logger.info(f"[LATENCY] Command accepted: {time.strftime('%H:%M:%S', time.localtime(time.time()))}.{int(time.time()*1000)%1000:03d}")
            
            # Spec: 4-second grouping - max time to recognize double, not mandatory delay
            # For intentional double with DIFFERENT commands, flush immediately to reduce latency
            if len(self.collected_commands) >= self.max_commands_per_window:
                if self.collected_commands[0][0] != self.collected_commands[1][0]:
                    self.logger.info(f"[WINDOW] Double detected: {self.collected_commands[0][0]} + {self.collected_commands[1][0]} - flushing immediately")
                    # Close immediately on separate thread to avoid deadlock
                    threading.Thread(target=self._close_window, daemon=True).start()
                    self.window_active = False
                else:
                    # Should not happen due to dedup above, but handle same-command double (should be suppressed)
                    self.logger.info(f"[WINDOW] Window full ({len(self.collected_commands)}/{self.max_commands_per_window}) - waiting for {self.window_duration}s expiry to process ordered double")
            
            return True
    
    def _start_window(self):
        """Start a new command window."""
        self.window_active = True
        self.window_start_time = time.time()
        self.collected_commands = []
        self.logger.info(f"[WINDOW] Window started (duration={self.window_duration}s) Timeout: 4.0s")
        self.logger.info(f"[LATENCY] Window started: {time.strftime('%H:%M:%S', time.localtime(self.window_start_time))}.{int(self.window_start_time*1000)%1000:03d}")
        
        # Start timer to close window
        def window_timer():
            time.sleep(self.window_duration)
            with self.window_lock:
                if self.window_active:
                    self._close_window()
        
        self.window_timer = threading.Thread(target=window_timer, daemon=True)
        self.window_timer.start()
    
    def _close_window(self):
        """Close the current window and process collected commands."""
        if not self.window_active and len(self.collected_commands)==0:
            return
        
        self.window_active = False
        commands = [cmd for cmd, conf in self.collected_commands]
        confidences = [conf for cmd, conf in self.collected_commands]
        
        self.logger.info(
            f"[WINDOW] Window closed: {len(commands)} command(s) collected: {commands}"
        )
        self.logger.info(f"[LATENCY] Window closed: {time.strftime('%H:%M:%S', time.localtime(time.time()))}.{int(time.time()*1000)%1000:03d}")
        
        # Determine command type
        if len(commands) == 0:
            self.logger.warning("[WINDOW] No commands collected in window")
            return
        
        # Process commands through callback
        if self.command_callback:
            try:
                self.command_callback(commands, confidences)
            except Exception as e:
                self.logger.error(f"[WINDOW] Command callback error: {e}")
    
    def reset(self):
        """Reset the window state (clear any active window)."""
        with self.window_lock:
            self.window_active = False
            self.window_start_time = None
            self.collected_commands = []
            self.logger.info("[WINDOW] Window reset")
    
    def is_active(self) -> bool:
        """Check if a window is currently active."""
        return self.window_active
    
    def get_collected_count(self) -> int:
        """Get the number of commands currently collected in the window."""
        with self.window_lock:
            return len(self.collected_commands)


def create_command_window(
    window_duration: float = 4.0,
    confidence_threshold: float = 0.35,
    command_callback: Callable[[List[str]], None] = None,
    logger: Optional[logging.Logger] = None,
) -> CommandWindow:
    """Factory function to create a command window instance.
    
    Args:
        window_duration: Duration in seconds to collect commands (4.0 per updated spec)
        confidence_threshold: Minimum confidence for valid commands (0.35)
        command_callback: Function to call with command list when window closes
        logger: Logger instance
        
    Returns:
        Configured CommandWindow instance
    """
    return CommandWindow(
        window_duration=window_duration,
        confidence_threshold=confidence_threshold,
        command_callback=command_callback,
        logger=logger,
    )