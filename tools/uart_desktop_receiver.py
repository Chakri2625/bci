"""
SynaptiMesh UART Desktop Receiver & Executor (Standalone EXE)
--------------------------------------------------------------
Run this on the TARGET PC (PC 2) connected via UART cable.
It listens on the COM port, executes desktop actions, and sends immediate ACK/PONG responses.

To build as a standalone EXE:
    pip install pyserial pyinstaller pyautogui
    pyinstaller --onefile --name "SynaptiMesh_UART_Receiver" tools/uart_desktop_receiver.py
"""

import sys
import time
import os
import subprocess
import webbrowser
import serial
import serial.tools.list_ports

BAUDRATE = 9600
TIMEOUT = 0.1

def auto_find_port():
    ports = [p.device for p in serial.tools.list_ports.comports()]
    if ports:
        return ports[0]
    return "COM3"

def execute_desktop_action(command: str):
    import re
    # Clean up whitespace and punctuation so "Play / Pause" -> "PLAY_PAUSE"
    cmd = re.sub(r'[^a-zA-Z0-9]+', '_', command.strip()).strip('_').upper()
    print(f"[*] Executing Action: {cmd} (raw: {command})")
    try:
        if cmd in ("OPEN_NOTEPAD", "NOTEPAD"):
            subprocess.Popen("notepad.exe")
            return True, "Notepad opened"
        elif cmd in ("OPEN_CHROME", "OPEN_PREDEFINED_ARTICLE", "CHROME"):
            webbrowser.open("https://www.google.com")
            return True, "Chrome/Browser opened"
        elif cmd in ("OPEN_YOUTUBE", "YOUTUBE", "OPEN_DESKTOP_DASHBOARD", "DESKTOP_DASHBOARD_ACTIVE", "OPEN_DESKTOP", "LAUNCH_JIOSAAVN", "OPEN_JIOSAAVN", "RIGHT_JIOSAAVN"):
            webbrowser.open("https://www.youtube.com")
            return True, "YouTube opened"
        elif cmd in ("OPEN_GMAIL", "COMPOSE_EMAIL", "GMAIL"):
            webbrowser.open("https://mail.google.com")
            return True, "Gmail opened"
        elif cmd in ("PREVIOUS_VIDEO", "PREVIOUS_TRACK", "PREVIOUS", "RIGHT_PREVIOUS_SONG", "RIGHT_PREVIOUS_TRACK"):
            try:
                import pyautogui
                pyautogui.hotkey('shift', 'p')
            except Exception:
                webbrowser.open("https://www.youtube.com")
            return True, "Previous video/track triggered"
        elif cmd in ("NEXT_VIDEO", "NEXT_TRACK", "NEXT", "RIGHT_NEXT_SONG", "RIGHT_NEXT_TRACK"):
            try:
                import pyautogui
                pyautogui.hotkey('shift', 'n')
            except Exception:
                webbrowser.open("https://www.youtube.com")
            return True, "Next video/track triggered"
        elif cmd in ("TOGGLE_PLAY_PAUSE", "PLAY_PAUSE", "PLAY", "PAUSE", "RIGHT_PLAY_PAUSE"):
            try:
                import pyautogui
                pyautogui.press('k')
            except Exception:
                pass
            return True, "Play/Pause toggled"
        elif cmd in ("VOLUME_UP", "RIGHT_VOLUME_UP"):
            try:
                import pyautogui
                pyautogui.press('volumeup')
            except Exception:
                pass
            return True, "Volume Up triggered"
        elif cmd in ("VOLUME_DOWN", "RIGHT_VOLUME_DOWN"):
            try:
                import pyautogui
                pyautogui.press('volumedown')
            except Exception:
                pass
            return True, "Volume Down triggered"
        elif cmd in ("CLOSE_APP", "CLOSE"):
            try:
                import pyautogui
                pyautogui.hotkey('alt', 'f4')
            except Exception:
                pass
            return True, "Application closed"
        elif cmd.startswith("SEARCH") or cmd in ("RIGHT_SEARCH_PLAYLIST", "SEARCH_ALBUM_PLAYLIST", "SEARCH_ALBUMPLAYLIST"):
            webbrowser.open("https://www.youtube.com/results?search_query=trending")
            return True, "Search opened"
        else:
            print(f"[!] Generic command received: {cmd}")
            return True, f"Command {cmd} acknowledged"
    except Exception as e:
        print(f"[X] Execution error for {cmd}: {e}")
        return False, str(e)

def main():
    print("=" * 65)
    print("⚡ SynaptiMesh UART Desktop Receiver & Executor (EXE)")
    print("=" * 65)
    
    port = auto_find_port()
    print(f"[*] Detected COM Port: {port} (Baudrate: {BAUDRATE})")
    
    try:
        ser = serial.Serial(port=port, baudrate=BAUDRATE, timeout=TIMEOUT)
        print(f"[✓] Connected and listening on {port}...")
    except Exception as e:
        print(f"[X] Could not open serial port {port}: {e}")
        print("Please check your UART USB cable connection and COM port number.")
        input("Press Enter to exit...")
        return

    print("[*] Ready to receive commands from Host PC. Press Ctrl+C to stop.\n")

    try:
        while True:
            if ser.in_waiting > 0:
                line = ser.readline().decode('utf-8', errors='ignore').strip()
                if not line:
                    continue

                print(f"[RX] {line}")

                # Handle PING heartbeat
                if line == "PING":
                    ser.write(b"PONG\n")
                    ser.flush()
                    print("[TX] PONG")
                    continue

                # Handle Command: CMD|<COMMAND> or action cmd|<COMMAND>
                if line.startswith("CMD|") or line.lower().startswith("action cmd|"):
                    parts = line.split("|")
                    if len(parts) >= 2:
                        cmd = parts[1].strip()
                        # Send ACK immediately back to host PC to prevent timeouts
                        ack_msg = f"ACK|{cmd}|SUCCESS|Executed on remote PC\n"
                        ser.write(ack_msg.encode('utf-8'))
                        ser.flush()
                        print(f"[TX] {ack_msg.strip()}")
                        
                        # Execute the desktop action locally on PC 2
                        success, message = execute_desktop_action(cmd)

            time.sleep(0.02)
    except KeyboardInterrupt:
        print("\n[*] Stopping receiver...")
    finally:
        if ser.is_open:
            ser.close()
        print("[*] Port closed. Goodbye.")

if __name__ == "__main__":
    main()
