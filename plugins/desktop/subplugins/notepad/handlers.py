import subprocess
import pyautogui
import time
from plugins.desktop.shared.services import ensure_window, focus_window

def open_notepad():
    if not ensure_window("Notepad"):
        subprocess.Popen("notepad.exe")
        time.sleep(1)
    else:
        focus_window("Notepad")
    return {"status": "success", "message": "Notepad: Opened"}

def save_file():
    if focus_window("Notepad"):
        pyautogui.hotkey('ctrl', 's')
        return {"status": "success", "message": "Notepad: Save prompt triggered"}
    return {"status": "error", "message": "Notepad is not open"}

def close_app():
    subprocess.run(["taskkill", "/IM", "notepad.exe", "/F"], capture_output=True)
    return {"status": "success", "message": "Notepad: Application closed"}
