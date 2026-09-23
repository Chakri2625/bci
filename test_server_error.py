import subprocess
import sys
import time
from pathlib import Path

import httpx

base_dir = Path(__file__).resolve().parent
print("Starting server to catch error...")
from pathlib import Path
server_dir = Path(__file__).parent
p = subprocess.Popen([sys.executable, "main.py"], cwd=str(server_dir), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
time.sleep(3)

try:
    res = httpx.get("http://127.0.0.1:8000/")
    print("Response Status:", res.status_code)
except Exception as e:
    print("Error fetching:", e)

time.sleep(1)
p.terminate()

out, _ = p.communicate()
print("SERVER LOGS:")
print(out)
