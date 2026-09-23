import json
import urllib.request
import urllib.error
import sys
import time

MASTER_HUB_URL = "http://127.0.0.1:8000/api/v1/bci/command"

COMMAND_MAP = {
    "push": "FORWARD",
    "pull": "BACKWARD",
    "left": "LEFT",
    "right": "RIGHT",
    "stop": "STOP",
}

def check_health():
    try:
        with urllib.request.urlopen("http://127.0.0.1:8000/api/v1/state", timeout=2) as response:
            if response.status == 200:
                return True
    except Exception as e:
        return str(e)
    return False

def send_command(command, confidence):
    command = command.lower()
    
    print("HTTP METHOD:\nPOST\n")
    print(f"ACTUAL URL:\n{MASTER_HUB_URL}\n")
    
    payload = {
        "command": command,
        "confidence": confidence,
        "source": "emotiv_simulator"
    }
    data = json.dumps(payload).encode("utf-8")
    
    print(f"PAYLOAD:\n{json.dumps(payload)}\n")

    request = urllib.request.Request(
        MASTER_HUB_URL,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST"
    )

    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            result = response.read().decode("utf-8")
            print(f"HTTP RESPONSE:\n{response.status}\n")
            print(f"RESPONSE BODY:\n{result}\n")
            return True
    except urllib.error.HTTPError as e:
        print(f"HTTP RESPONSE:\n{e.code}\n")
        print(f"RESPONSE BODY:\n{e.reason}\n")
        return False
    except urllib.error.URLError as e:
        print(f"HTTP RESPONSE:\nERROR\n")
        print(f"RESPONSE BODY:\n{e.reason}\n")
        return False
    except Exception as e:
        print(f"HTTP RESPONSE:\nERROR\n")
        print(f"RESPONSE BODY:\n{e}\n")
        return False

def main():
    health_result = check_health()
    if health_result is not True:
        print("\nEMOTIV SIMULATOR ERROR\n")
        print("Master Hub:")
        print("DISCONNECTED\n")
        print("Reason:")
        print(health_result if isinstance(health_result, str) else "Connection Refused")
        sys.exit(1)
        
    print("\n========================================")
    print("      EMOTIV TEST SIMULATOR")
    print("========================================")
    print("\nConnection:")
    print("CONNECTED")
    print("\nMaster Hub:")
    print("127.0.0.1")
    print("\nPort:")
    print("8000")
    print("\nProtocol:")
    print("HTTP")
    print("\nEndpoint/topic:")
    print("/api/v1/bci/command\n")
    print("Commands:\n")
    for cmd in COMMAND_MAP.keys():
        print(cmd)
    print("\n")
    
    while True:
        try:
            user_input = input("EMOTIV> ").strip()
        except KeyboardInterrupt:
            print("\nSimulator stopped.")
            break

        if not user_input: continue
        if user_input.lower() == "exit":
            print("Simulator stopped.")
            break

        parts = user_input.lower().split()
        command = parts[0]
        confidence = 0.95

        if len(parts) > 1:
            try:
                confidence = float(parts[1])
            except ValueError:
                pass

        if command not in COMMAND_MAP:
            continue

        send_command(command, confidence)

if __name__ == "__main__":
    main()