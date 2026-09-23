import subprocess
import pyautogui
import pygetwindow as gw
import time

def open_url(url):
    subprocess.Popen(["cmd", "/c", "start", url])

def ensure_window(title_substring):
    windows = gw.getWindowsWithTitle(title_substring)
    return len(windows) > 0

def focus_window(title_substring):
    windows = gw.getWindowsWithTitle(title_substring)
    if windows:
        win = windows[0]
        try:
            if win.isMinimized:
                win.restore()
            win.activate()
            time.sleep(0.5)
            return True
        except Exception:
            pass
    return False
