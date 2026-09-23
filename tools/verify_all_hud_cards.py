import urllib.request
import json
import time

BASE_URL = "http://127.0.0.1:8000"

def get_json(path):
    req = urllib.request.urlopen(f"{BASE_URL}{path}")
    return json.loads(req.read().decode("utf-8"))

def post_json(path, data):
    body = json.dumps(data).encode("utf-8")
    req = urllib.request.Request(f"{BASE_URL}{path}", data=body, headers={"Content-Type": "application/json"})
    try:
        resp = urllib.request.urlopen(req)
        return json.loads(resp.read().decode("utf-8")), resp.getcode()
    except urllib.error.HTTPError as e:
        return json.loads(e.read().decode("utf-8")), e.code

print("=== STARTING LIVE HUD CARDS VERIFICATION ===")

# 1. Reset state
post_json("/api/v1/state/reset", {})
post_json("/api/v1/state/failures/clear", {})

# 2. Check initial system state
sys_state = get_json("/api/v1/state/system")
print(f"[HUD 2 - PERFORMANCE] Initial state: Exec={sys_state.get('execution_state')}, ActiveTasks={sys_state.get('active_tasks_count')}")
assert sys_state.get("active_tasks_count") == 0
assert sys_state.get("performance", {}).get("bottleneck_status") == "OPTIMAL"

# 3. Dispatch valid command sequence
res_push, code1 = post_json("/api/v1/bci/command", {"command": "PUSH", "session_id": "hud_live_test"})
print(f"[HUD 1 - TIMING] Dispatched PUSH -> code: {code1}, result: {res_push.get('status')}")
assert code1 == 200
cid = res_push.get("command_id")
assert cid is not None
timing = res_push.get("timing")
assert timing is not None
print(f"[HUD 1 - TIMING] Command Timing: Started={timing.get('started_at_iso')}, Completed={timing.get('completed_at_iso')}, Duration={timing.get('duration_ms')}ms")

# 4. Check Performance metrics after execution
perf = get_json("/api/v1/state/performance")
print(f"[HUD 2 - PERFORMANCE] Recent Proc Latency={perf.get('recent_processing_latency_ms')}ms, Recent Exec Latency={perf.get('recent_execution_latency_ms')}ms")
assert perf.get("total_measured_commands") >= 1
assert perf.get("recent_processing_latency_ms") >= 0.0

# 5. Dispatch invalid command to test Fault & Recovery card
res_bad, code2 = post_json("/api/v1/bci/command", {"command": "INVALID_CMD_TEST", "session_id": "hud_live_test"})
print(f"[HUD 3 - FAULT] Dispatched invalid command -> code: {code2}")

failures = get_json("/api/v1/state/failures")
print(f"[HUD 3 - FAULT] Total recorded failures: {failures.get('total_failures_recorded')}, Active: {failures.get('active_failures_count')}")
assert failures.get("total_failures_recorded") >= 1
last_f = failures.get("last_failure")
assert last_f is not None
print(f"[HUD 3 - FAULT] Last failure: Component={last_f.get('affected_component')}, Reason={last_f.get('failure_reason')}")

# 6. Clear failures
clear_res, _ = post_json("/api/v1/state/failures/clear", {})
failures_after = get_json("/api/v1/state/failures")
assert failures_after.get("active_failures_count") == 0
print(f"[HUD 3 - FAULT] Failures cleared successfully. Active failures: {failures_after.get('active_failures_count')}")

print("\n*** ALL 3 HUD CARDS VERIFIED AND WORKING 100% OPERATIONAL ***")
