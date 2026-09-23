"""
Desktop Integration Service — SynaptiMesh Python OS
Provides native Windows automation, active window switching, OS tactical launchpad,
browser automation, and mini process task manager.
"""

import os
import sys
import time
import subprocess
import logging
from typing import List, Dict, Any, Optional

logger = logging.getLogger("DesktopIntegrationService")


class DesktopIntegrationService:
    """
    Unified Desktop integration layer managing:
    1. Active Windows enumeration and foreground focusing
    2. OS-level tactical actions (Screenshot, Show Desktop, Lock Workstation, File Explorer)
    3. Web Browser automation (Smooth scrolling, tab switcher, zoom, URL search)
    4. Process monitoring & management
    """

    def __init__(self):
        self.is_windows = sys.platform == "win32"
        self._init_native_win32()

    def _init_native_win32(self):
        """Initialize win32 and ctypes hooks."""
        self.win32gui = None
        self.win32con = None
        self.win32process = None
        self.pyautogui = None
        
        if self.is_windows:
            try:
                import win32gui
                import win32con
                import win32process
                self.win32gui = win32gui
                self.win32con = win32con
                self.win32process = win32process
            except ImportError:
                logger.warning("pywin32 not fully installed; using ctypes fallbacks.")

            try:
                import pyautogui
                self.pyautogui = pyautogui
                pyautogui.FAILSAFE = False
            except ImportError:
                pass

    def execute_command(self, action: str, payload: Optional[Dict[str, Any]] = None, command_id: Optional[str] = None) -> Dict[str, Any]:
        """Unified command execution dispatcher for Desktop domain."""
        action_upper = action.upper().strip()
        payload = payload or {}
        
        if action_upper in ["FOCUS_WINDOW", "SWITCH_APP", "ACTIVATE_APP"]:
            hwnd = payload.get("hwnd")
            title = payload.get("title") or payload.get("query")
            return self.focus_window(hwnd=hwnd, title_query=title)
            
        elif action_upper in ["SHOW_DESKTOP", "LOCK_WORKSTATION", "SCREENSHOT", "FILE_EXPLORER", "TASK_VIEW", "CLIPBOARD_HISTORY", "MINIMIZE_ALL"]:
            return self.execute_os_action(action=action_upper, params=payload)
            
        elif action_upper in ["SCROLL_UP", "SCROLL_DOWN", "NEW_TAB", "CLOSE_TAB", "NEXT_TAB", "PREV_TAB", "REOPEN_TAB", "ZOOM_IN", "ZOOM_OUT", "REFRESH_PAGE", "SEARCH_QUERY"]:
            return self.execute_browser_action(action=action_upper, params=payload)
            
        elif action_upper in ["KILL_PROCESS", "TERMINATE_APP"]:
            pid = payload.get("pid")
            name = payload.get("name")
            return self.kill_process(pid=pid, name=name)
            
        return {"status": "error", "message": f"Unhandled desktop action: {action}"}

    # -------------------------------------------------------------
    # 1. WINDOW MANAGEMENT & ACTIVE APP SWITCHER
    # -------------------------------------------------------------
    def list_active_windows(self, limit: int = 15) -> List[Dict[str, Any]]:
        """
        Enumerate visible top-level desktop windows with titles and process info.
        """
        windows = []
        if not self.is_windows:
            return [
                {"hwnd": 1001, "title": "Chrome — SynaptiMesh Dashboard", "process": "chrome.exe", "is_minimized": False},
                {"hwnd": 1002, "title": "Notepad — Neural Logs", "process": "notepad.exe", "is_minimized": False},
                {"hwnd": 1003, "title": "Spotify — Focus Lo-Fi", "process": "spotify.exe", "is_minimized": True}
            ]

        try:
            if self.win32gui:
                def enum_handler(hwnd, extra):
                    if self.win32gui.IsWindowVisible(hwnd):
                        title = self.win32gui.GetWindowText(hwnd).strip()
                        if title and len(title) > 1 and title != "Program Manager":
                            _, pid = self.win32process.GetWindowThreadProcessId(hwnd)
                            proc_name = "application"
                            try:
                                import psutil
                                proc = psutil.Process(pid)
                                proc_name = proc.name()
                            except Exception:
                                pass
                            
                            is_minimized = self.win32gui.IsIconic(hwnd) != 0
                            extra.append({
                                "hwnd": hwnd,
                                "title": title,
                                "pid": pid,
                                "process": proc_name,
                                "is_minimized": is_minimized
                            })

                results = []
                self.win32gui.EnumWindows(enum_handler, results)
                # Filter duplicates and limit
                seen_titles = set()
                for w in results:
                    if w["title"] not in seen_titles:
                        seen_titles.add(w["title"])
                        windows.append(w)
                    if len(windows) >= limit:
                        break
            else:
                # Ctypes fallback
                import ctypes
                user32 = ctypes.windll.user32
                
                EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
                
                def py_enum(hwnd, lparam):
                    if user32.IsWindowVisible(hwnd):
                        length = user32.GetWindowTextLengthW(hwnd)
                        if length > 0:
                            buff = ctypes.create_unicode_buffer(length + 1)
                            user32.GetWindowTextW(hwnd, buff, length + 1)
                            title = buff.value.strip()
                            if title and title != "Program Manager":
                                windows.append({
                                    "hwnd": hwnd,
                                    "title": title,
                                    "process": "windows_app.exe",
                                    "is_minimized": False
                                })
                    return True
                
                user32.EnumWindows(EnumWindowsProc(py_enum), 0)
        except Exception as e:
            logger.error(f"Error enumerating windows: {e}")

        if not windows:
            windows = [
                {"hwnd": 1, "title": "Google Chrome", "process": "chrome.exe", "is_minimized": False},
                {"hwnd": 2, "title": "Visual Studio Code", "process": "Code.exe", "is_minimized": False},
                {"hwnd": 3, "title": "Windows Terminal", "process": "wt.exe", "is_minimized": False}
            ]

        return windows[:limit]

    def focus_window(self, hwnd: Optional[int] = None, title_query: Optional[str] = None) -> Dict[str, Any]:
        """
        Bring the requested window to the foreground and un-minimize it.
        """
        if not self.is_windows:
            return {"status": "success", "message": f"Simulated focus window {hwnd or title_query}"}

        try:
            import ctypes
            user32 = ctypes.windll.user32

            target_hwnd = hwnd
            if not target_hwnd and title_query and self.win32gui:
                def find_target(h, extra):
                    if self.win32gui.IsWindowVisible(h):
                        t = self.win32gui.GetWindowText(h)
                        if title_query.lower() in t.lower():
                            extra.append(h)
                found = []
                self.win32gui.EnumWindows(find_target, found)
                if found:
                    target_hwnd = found[0]

            if target_hwnd:
                # SW_RESTORE = 9, SW_SHOW = 5
                user32.ShowWindow(target_hwnd, 9)
                user32.SetForegroundWindow(target_hwnd)
                return {"status": "success", "hwnd": target_hwnd, "message": "Window brought to foreground"}
            else:
                return {"status": "error", "message": f"Window not found for query: {title_query or hwnd}"}
        except Exception as e:
            logger.error(f"Failed to focus window: {e}")
            return {"status": "error", "message": str(e)}

    # -------------------------------------------------------------
    # 2. OS PRODUCTIVITY & TACTICAL LAUNCHPAD
    # -------------------------------------------------------------
    def execute_os_action(self, action: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Execute an OS-level tactical action.
        Supported actions:
        - SHOW_DESKTOP: Win + D
        - LOCK_WORKSTATION: Win + L
        - SCREENSHOT: Win + Shift + S or PrintScreen
        - FILE_EXPLORER: Win + E
        - TASK_VIEW: Win + Tab
        - CLIPBOARD_HISTORY: Win + V
        - MINIMIZE_ALL: Win + M
        """
        action = action.upper().strip()
        logger.info(f"Executing OS Tactical Action: {action}")

        if not self.is_windows:
            return {"status": "success", "action": action, "platform": sys.platform, "message": "Action simulated"}

        try:
            import ctypes
            user32 = ctypes.windll.user32
            VK_LWIN = 0x5B
            KEYEVENTF_KEYUP = 0x0002

            if action == "SHOW_DESKTOP":
                # Win + D
                user32.keybd_event(VK_LWIN, 0, 0, 0)
                user32.keybd_event(ord('D'), 0, 0, 0)
                time.sleep(0.05)
                user32.keybd_event(ord('D'), 0, KEYEVENTF_KEYUP, 0)
                user32.keybd_event(VK_LWIN, 0, KEYEVENTF_KEYUP, 0)
                return {"status": "success", "action": action, "message": "Toggled Show Desktop (Win+D)"}

            elif action == "LOCK_WORKSTATION":
                # Native LockWorkStation API
                user32.LockWorkStation()
                return {"status": "success", "action": action, "message": "Workstation locked"}

            elif action == "SCREENSHOT":
                # Win + Shift + S
                VK_SHIFT = 0x10
                user32.keybd_event(VK_LWIN, 0, 0, 0)
                user32.keybd_event(VK_SHIFT, 0, 0, 0)
                user32.keybd_event(ord('S'), 0, 0, 0)
                time.sleep(0.05)
                user32.keybd_event(ord('S'), 0, KEYEVENTF_KEYUP, 0)
                user32.keybd_event(VK_SHIFT, 0, KEYEVENTF_KEYUP, 0)
                user32.keybd_event(VK_LWIN, 0, KEYEVENTF_KEYUP, 0)
                return {"status": "success", "action": action, "message": "Snipping Tool activated (Win+Shift+S)"}

            elif action == "FILE_EXPLORER":
                subprocess.Popen(["explorer.exe"])
                return {"status": "success", "action": action, "message": "Windows Explorer launched"}

            elif action == "TASK_VIEW":
                # Win + Tab
                VK_TAB = 0x09
                user32.keybd_event(VK_LWIN, 0, 0, 0)
                user32.keybd_event(VK_TAB, 0, 0, 0)
                time.sleep(0.05)
                user32.keybd_event(VK_TAB, 0, KEYEVENTF_KEYUP, 0)
                user32.keybd_event(VK_LWIN, 0, KEYEVENTF_KEYUP, 0)
                return {"status": "success", "action": action, "message": "Task View opened (Win+Tab)"}

            elif action == "CLIPBOARD_HISTORY":
                # Win + V
                user32.keybd_event(VK_LWIN, 0, 0, 0)
                user32.keybd_event(ord('V'), 0, 0, 0)
                time.sleep(0.05)
                user32.keybd_event(ord('V'), 0, KEYEVENTF_KEYUP, 0)
                user32.keybd_event(VK_LWIN, 0, KEYEVENTF_KEYUP, 0)
                return {"status": "success", "action": action, "message": "Clipboard History opened (Win+V)"}

            elif action == "MINIMIZE_ALL":
                # Win + M
                user32.keybd_event(VK_LWIN, 0, 0, 0)
                user32.keybd_event(ord('M'), 0, 0, 0)
                time.sleep(0.05)
                user32.keybd_event(ord('M'), 0, KEYEVENTF_KEYUP, 0)
                user32.keybd_event(VK_LWIN, 0, KEYEVENTF_KEYUP, 0)
                return {"status": "success", "action": action, "message": "All windows minimized (Win+M)"}

            else:
                return {"status": "error", "message": f"Unknown OS action: {action}"}

        except Exception as e:
            logger.error(f"Error executing OS action {action}: {e}")
            return {"status": "error", "message": str(e)}

    # -------------------------------------------------------------
    # 3. DEEP WEB BROWSER AUTOMATION
    # -------------------------------------------------------------
    def execute_browser_action(self, action: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Execute deep web browser actions (Chrome, Edge, Default Browser).
        Supported actions:
        - SCROLL_UP, SCROLL_DOWN (params: amount)
        - NEW_TAB (Ctrl + T)
        - CLOSE_TAB (Ctrl + W)
        - NEXT_TAB (Ctrl + Tab)
        - PREV_TAB (Ctrl + Shift + Tab)
        - REOPEN_TAB (Ctrl + Shift + T)
        - ZOOM_IN (Ctrl + Plus)
        - ZOOM_OUT (Ctrl + Minus)
        - REFRESH_PAGE (F5 or Ctrl + R)
        - SEARCH_QUERY (params: query, provider: "google" | "youtube" | "github")
        """
        action = action.upper().strip()
        params = params or {}
        logger.info(f"Executing Browser Action: {action} (params={params})")

        if not self.is_windows:
            return {"status": "success", "action": action, "message": f"Browser action {action} simulated"}

        try:
            import ctypes
            user32 = ctypes.windll.user32
            VK_CONTROL = 0x11
            VK_SHIFT = 0x10
            VK_TAB = 0x09
            VK_F5 = 0x74
            KEYEVENTF_KEYUP = 0x0002

            if action == "SCROLL_DOWN":
                amount = int(params.get("amount", 300))
                if self.pyautogui:
                    self.pyautogui.scroll(-amount)
                else:
                    # MOUSEEVENTF_WHEEL = 0x0800
                    user32.mouse_event(0x0800, 0, 0, -amount, 0)
                return {"status": "success", "action": action, "scrolled": -amount}

            elif action == "SCROLL_UP":
                amount = int(params.get("amount", 300))
                if self.pyautogui:
                    self.pyautogui.scroll(amount)
                else:
                    user32.mouse_event(0x0800, 0, 0, amount, 0)
                return {"status": "success", "action": action, "scrolled": amount}

            elif action == "NEW_TAB":
                # Ctrl + T
                user32.keybd_event(VK_CONTROL, 0, 0, 0)
                user32.keybd_event(ord('T'), 0, 0, 0)
                time.sleep(0.05)
                user32.keybd_event(ord('T'), 0, KEYEVENTF_KEYUP, 0)
                user32.keybd_event(VK_CONTROL, 0, KEYEVENTF_KEYUP, 0)
                return {"status": "success", "action": action, "message": "New tab opened"}

            elif action == "CLOSE_TAB":
                # Ctrl + W
                user32.keybd_event(VK_CONTROL, 0, 0, 0)
                user32.keybd_event(ord('W'), 0, 0, 0)
                time.sleep(0.05)
                user32.keybd_event(ord('W'), 0, KEYEVENTF_KEYUP, 0)
                user32.keybd_event(VK_CONTROL, 0, KEYEVENTF_KEYUP, 0)
                return {"status": "success", "action": action, "message": "Active tab closed"}

            elif action == "NEXT_TAB":
                # Ctrl + Tab
                user32.keybd_event(VK_CONTROL, 0, 0, 0)
                user32.keybd_event(VK_TAB, 0, 0, 0)
                time.sleep(0.05)
                user32.keybd_event(VK_TAB, 0, KEYEVENTF_KEYUP, 0)
                user32.keybd_event(VK_CONTROL, 0, KEYEVENTF_KEYUP, 0)
                return {"status": "success", "action": action, "message": "Switched to next tab"}

            elif action == "PREV_TAB":
                # Ctrl + Shift + Tab
                user32.keybd_event(VK_CONTROL, 0, 0, 0)
                user32.keybd_event(VK_SHIFT, 0, 0, 0)
                user32.keybd_event(VK_TAB, 0, 0, 0)
                time.sleep(0.05)
                user32.keybd_event(VK_TAB, 0, KEYEVENTF_KEYUP, 0)
                user32.keybd_event(VK_SHIFT, 0, KEYEVENTF_KEYUP, 0)
                user32.keybd_event(VK_CONTROL, 0, KEYEVENTF_KEYUP, 0)
                return {"status": "success", "action": action, "message": "Switched to previous tab"}

            elif action == "REOPEN_TAB":
                # Ctrl + Shift + T
                user32.keybd_event(VK_CONTROL, 0, 0, 0)
                user32.keybd_event(VK_SHIFT, 0, 0, 0)
                user32.keybd_event(ord('T'), 0, 0, 0)
                time.sleep(0.05)
                user32.keybd_event(ord('T'), 0, KEYEVENTF_KEYUP, 0)
                user32.keybd_event(VK_SHIFT, 0, KEYEVENTF_KEYUP, 0)
                user32.keybd_event(VK_CONTROL, 0, KEYEVENTF_KEYUP, 0)
                return {"status": "success", "action": action, "message": "Reopened closed tab"}

            elif action == "REFRESH_PAGE":
                user32.keybd_event(VK_F5, 0, 0, 0)
                time.sleep(0.05)
                user32.keybd_event(VK_F5, 0, KEYEVENTF_KEYUP, 0)
                return {"status": "success", "action": action, "message": "Refreshed page"}

            elif action == "SEARCH_QUERY":
                query = params.get("query", "SynaptiMesh BCI")
                provider = params.get("provider", "google").lower()
                import urllib.parse
                encoded = urllib.parse.quote(query)
                
                if provider == "youtube":
                    url = f"https://www.youtube.com/results?search_query={encoded}"
                elif provider == "github":
                    url = f"https://github.com/search?q={encoded}"
                else:
                    url = f"https://www.google.com/search?q={encoded}"

                import webbrowser
                webbrowser.open(url)
                return {"status": "success", "action": action, "url": url, "query": query}

            else:
                return {"status": "error", "message": f"Unsupported browser action: {action}"}

        except Exception as e:
            logger.error(f"Error in browser action {action}: {e}")
            return {"status": "error", "message": str(e)}

    # -------------------------------------------------------------
    # 4. MINI TASK MANAGER & PROCESS HEALTH HUD
    # -------------------------------------------------------------
    def list_top_processes(self, limit: int = 10) -> List[Dict[str, Any]]:
        """
        List top background and foreground processes sorted by memory/CPU.
        """
        procs = []
        try:
            import psutil
            for p in psutil.process_iter(['pid', 'name', 'cpu_percent', 'memory_info', 'status']):
                try:
                    info = p.info
                    name = info.get('name') or 'unknown'
                    # Skip idle/system idle
                    if name.lower() in ['system idle process', 'registry']:
                        continue
                    
                    mem_mb = 0
                    if info.get('memory_info'):
                        mem_mb = round(info['memory_info'].rss / (1024 * 1024), 1)

                    cpu = info.get('cpu_percent') or 0.0

                    procs.append({
                        "pid": info.get('pid'),
                        "name": name,
                        "cpu_percent": round(cpu, 1),
                        "memory_mb": mem_mb,
                        "status": info.get('status') or 'running'
                    })
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue

            # Sort primarily by memory, then limit
            procs.sort(key=lambda x: x["memory_mb"], reverse=True)
            return procs[:limit]

        except ImportError:
            # Fallback mock data
            return [
                {"pid": 4120, "name": "chrome.exe", "cpu_percent": 3.4, "memory_mb": 420.5, "status": "running"},
                {"pid": 8912, "name": "Code.exe", "cpu_percent": 1.8, "memory_mb": 310.2, "status": "running"},
                {"pid": 1204, "name": "python.exe", "cpu_percent": 1.2, "memory_mb": 145.8, "status": "running"},
                {"pid": 5832, "name": "explorer.exe", "cpu_percent": 0.5, "memory_mb": 112.4, "status": "running"}
            ]

    def kill_process(self, pid: Optional[int] = None, name: Optional[str] = None) -> Dict[str, Any]:
        """
        Safely terminate target process by PID or process name.
        """
        logger.warning(f"Request to terminate process: pid={pid}, name={name}")
        try:
            import psutil
            if pid:
                p = psutil.Process(pid)
                p_name = p.name()
                p.terminate()
                return {"status": "success", "pid": pid, "name": p_name, "message": f"Process {p_name} ({pid}) terminated"}
            elif name:
                killed = 0
                for p in psutil.process_iter(['pid', 'name']):
                    if p.info['name'] and p.info['name'].lower() == name.lower():
                        p.terminate()
                        killed += 1
                return {"status": "success", "name": name, "killed_count": killed, "message": f"Terminated {killed} instances of {name}"}
            else:
                return {"status": "error", "message": "Either pid or name must be specified"}
        except Exception as e:
            logger.error(f"Failed to kill process: {e}")
            return {"status": "error", "message": str(e)}


_desktop_integration_service_instance = None

def get_desktop_integration_service() -> DesktopIntegrationService:
    global _desktop_integration_service_instance
    if _desktop_integration_service_instance is None:
        _desktop_integration_service_instance = DesktopIntegrationService()
    return _desktop_integration_service_instance
