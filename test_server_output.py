import subprocess
import sys
import time
from pathlib import Path

import httpx

server_dir = Path(__file__).parent
p = subprocess.Popen([sys.executable, "main.py"], cwd=str(server_dir), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
time.sleep(3)

try:
    print("Fetching UI...")
    res = httpx.get("http://127.0.0.1:8000/")
    print(res.text)
except Exception as e:
    print(e)

p.terminate()
out, _ = p.communicate()
print("SERVER STDOUT:")
print(out)
