import urllib.request
import json

# 1. Fetch dashboard HTML
req = urllib.request.urlopen('http://127.0.0.1:8000/')
html = req.read().decode('utf-8')
assert 'exec-timing-card' in html, 'exec-timing-card not found in HTML'
assert 'Execution Timing' in html, 'Execution Timing not found in HTML'
assert 'Start Time' in html, 'Start Time not found in HTML'
assert 'Completion Time' in html, 'Completion Time not found in HTML'
print('[PASS] HTML Dashboard contains Execution Timing HUD Card and Activity table headers')

# 2. Dispatch a BCI command
data = json.dumps({'command': 'PUSH', 'session_id': 'http_test'}).encode('utf-8')
req = urllib.request.Request('http://127.0.0.1:8000/api/v1/bci/command', data=data, headers={'Content-Type': 'application/json'})
resp = urllib.request.urlopen(req)
cmd_res = json.loads(resp.read().decode('utf-8'))
cid = cmd_res.get('command_id')
status = cmd_res.get('status')
print(f'[PASS] Dispatched command: {cid}, status: {status}')

# 3. Fetch summary
req = urllib.request.urlopen('http://127.0.0.1:8000/api/v1/lifecycle/summary?session=http_test')
summary_res = json.loads(req.read().decode('utf-8'))
print(f'[PASS] Lifecycle Summary: {summary_res}')

# 4. Fetch command list
req = urllib.request.urlopen('http://127.0.0.1:8000/api/v1/lifecycle/commands?session=http_test')
cmds_res = json.loads(req.read().decode('utf-8'))
print(f'[PASS] Tracked Commands Count: {cmds_res.get("count")}')
cmd_rec = cmds_res['commands'][0]
print(f'       Command: {cmd_rec.get("command")} [{cmd_rec.get("current_stage")}]')
print(f'       Started: {cmd_rec.get("started_at_iso")}')
print(f'       Completed: {cmd_rec.get("completed_at_iso")}')
print(f'       Duration: {cmd_rec.get("duration_ms")} ms')

# 5. Fetch specific timing
req = urllib.request.urlopen(f'http://127.0.0.1:8000/api/v1/lifecycle/{cid}/timing')
timing_res = json.loads(req.read().decode('utf-8'))
print(f'[PASS] Command Timing Endpoint: {timing_res}')

assert cmd_rec.get('started_at_iso') is not None
assert cmd_rec.get('completed_at_iso') is not None
assert cmd_rec.get('duration_ms') is not None
print('\n*** ALL LIVE HTTP & TELEMETRY CHECKS PASSED SUCCESSFULLY ***')
