"""Mock BCI / Real-Time Data Simulator for SynaptiMesh.

Simulates the real Cortex/BCI live stream without requiring headset.
Enters the pipeline at the SAME point as real Cortex data:

    Mock BCI Data
        ↓
    Cortex command extraction (mock)
        ↓
    NEUTRAL filtering
        ↓
    Confidence filtering (0.35)
        ↓
    FSMController.receive_cortex_command()
        ↓
    4-second CommandWindow (ordered single/double)
        ↓
    process_command_sequence() -> mapping -> CommandRouter -> Mobile/Desktop

Generates timestamped packets:
    {"timestamp": "...", "command": "...", "confidence": 0.0, "level": 3}

NEUTRAL samples must have no effect on window (not counted, not resetting,
not affecting order, not participating in double detection).
"""

import time
import logging
import random
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)


def create_mock_packet(command: str, confidence: float = 0.85, timestamp: Optional[str] = None, level: int = 3) -> Dict[str, Any]:
    """Create a mock BCI packet with required fields."""
    if timestamp is None:
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()) + f".{int(time.time()*1000)%1000:03d}"
    return {
        "timestamp": timestamp,
        "command": command,
        "confidence": confidence,
        "level": level,
    }


def generate_realistic_stream(
    valid_sequence: List[str] = None,
    valid_confidences: List[float] = None,
    neutral_before: int = 20,
    neutral_between: int = 15,
    neutral_after: int = 20,
    level: int = 3,
) -> List[Dict[str, Any]]:
    """Generate a realistic mock stream with many NEUTRAL samples surrounding valid commands.

    Example: valid_sequence=["RIGHT","PUSH"] with neutrals around each produces
    20 NEUTRAL + RIGHT + 15 NEUTRAL + PUSH + 20 NEUTRAL.

    Args:
        valid_sequence: list of valid commands like ["RIGHT","PUSH"]
        valid_confidences: confidences for each valid command
        neutral_before/between/after: counts of NEUTRAL samples
        level: hierarchy level for all packets

    Returns:
        List of packets in temporal order
    """
    if valid_sequence is None:
        valid_sequence = ["RIGHT", "PUSH"]
    if valid_confidences is None:
        valid_confidences = [0.82, 0.76]
    
    packets = []
    base_time = time.time()
    idx = 0

    def add_neutral(count, start_idx):
        nonlocal idx
        for i in range(count):
            # NEUTRAL with high confidence (should still be ignored)
            conf = random.uniform(0.85, 0.95)
            ts = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(base_time + idx)) + ".000"
            packets.append(create_mock_packet("NEUTRAL", conf, ts, level))
            idx += 1

    def add_valid(cmd, conf):
        nonlocal idx
        ts = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(base_time + idx)) + ".000"
        packets.append(create_mock_packet(cmd, conf, ts, level))
        idx += 1

    add_neutral(neutral_before, 0)
    for j, cmd in enumerate(valid_sequence):
        conf = valid_confidences[j] if j < len(valid_confidences) else 0.85
        add_valid(cmd, conf)
        if j < len(valid_sequence) - 1:
            add_neutral(neutral_between, idx)
    add_neutral(neutral_after, idx)
    return packets


class MockBCIStream:
    """Feeds mock BCI packets into the REAL pipeline at the Cortex entry point.

    Usage:
        fsm = FSMController(mapper=..., dry_run=True)
        fsm.current_state = "MOBILE_DASHBOARD_ACTIVE"
        stream = MockBCIStream(fsm)
        packets = generate_realistic_stream(["RIGHT","PUSH"], [0.82,0.76])
        stream.feed(packets, verbose=True)  # logs [MOCK BCI], [FILTER], [WINDOW]
        time.sleep(8.5)  # wait for 4s window expiry
        # check fsm.history / last result
    """

    def __init__(self, fsm_controller, window_duration: float = 4.0):
        self.fsm = fsm_controller
        self.window_duration = window_duration
        self.logger = logging.getLogger(__name__)

    def feed(self, packets: List[Dict[str, Any]], verbose: bool = True, realtime: bool = False, inter_packet_delay: float = 0.05):
        """Feed mock packets into FSMController.receive_cortex_command (same as Cortex).

        Args:
            packets: list of {"command","confidence","timestamp","level"}
            verbose: if True, print [MOCK BCI], [FILTER], [WINDOW] stages
            realtime: if True, sleep between packets to simulate real-time
            inter_packet_delay: delay between packets when realtime=True
        """
        for pkt in packets:
            cmd = pkt.get("command", "")
            conf = float(pkt.get("confidence", 0.0))
            ts = pkt.get("timestamp", "")
            level = pkt.get("level", 3)

            if verbose:
                # This mimics Cortex extraction stage
                print(f"[MOCK BCI] {cmd} confidence={conf:.2f} level={level} ts={ts}")

            # This is the SAME entry point as real Cortex data:
            # Cortex -> cortex_bridge extract -> FSM.receive_cortex_command
            # receive_cortex_command handles NEUTRAL filtering, confidence 0.35, 4s window
            # We capture what happens via FSM logs; also print filter/window outcome
            before_count = len(self.fsm.window_commands) if hasattr(self.fsm, 'window_commands') else 0
            result = self.fsm.receive_cortex_command(cmd, conf, timestamp=None)
            
            if verbose:
                if cmd.strip().lower() == "neutral":
                    print(f"[FILTER] NEUTRAL ignored (not entering window)")
                elif not result:
                    # Could be low confidence or unknown
                    if conf < self.fsm.window_confidence_threshold:
                        print(f"[FILTER] Rejected low confidence {conf:.2f} < {self.fsm.window_confidence_threshold}")
                    else:
                        print(f"[FILTER] Rejected/ignored {cmd}")
                else:
                    # Accepted into window
                    with self.fsm.window_lock:
                        cnt = len(self.fsm.window_commands)
                    print(f"[WINDOW] Added {cmd} -> window now {cnt} cmd(s) (8s grouping)")

            if realtime and inter_packet_delay > 0:
                time.sleep(inter_packet_delay)

    def wait_for_window(self, extra: float = 0.5):
        """Wait for current 4s window to expire and process."""
        wait = self.window_duration + extra
        print(f"[WAIT] Waiting {wait:.1f}s for 4s window expiry...")
        time.sleep(wait)

    def get_window_commands(self):
        """Return current window contents (for testing reset)."""
        with self.fsm.window_lock:
            return list(self.fsm.window_commands)

    def assert_window_empty(self):
        """Check window is reset after processing."""
        return len(self.get_window_commands()) == 0
