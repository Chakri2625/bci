"""
Cross-platform BrowserManager for JioSaavn Master Hub.

Works on Windows, macOS, and Linux. All Chrome interactions go through
the remote-debugging port (127.0.0.1:9222) so no OS-specific accessibility
hacks are needed. OS differences are isolated to:
  - detecting / launching the debug Chrome (via start_chrome.py)
  - building ChromeOptions for Selenium attach
  - fallback media-key handling (delegated to os_operations.py)
"""
import time
import socket
import platform
import shutil
import subprocess
import os
import sys
from pathlib import Path

from selenium import webdriver
from logger import logger


class BrowserManager:
    MODULE_NAME = "BrowserManager"
    DEBUG_PORT = 9222
    LAUNCH_COOLDOWN = 15.0

    def __init__(self, headless=False):
        self.headless = headless
        self.driver = None
        self._last_launch_attempt = 0.0
        self._system = platform.system()  # Darwin / Windows / Linux

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _is_port_open(self) -> bool:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(0.5)
                return s.connect_ex(("127.0.0.1", self.DEBUG_PORT)) == 0
        except Exception:
            return False

    def _is_debug_chrome_process_running(self) -> bool:
        """
        Cross-platform check: is a chrome process with --remote-debugging-port running?
        Returns False on error (so caller falls through to launch).
        """
        system = self._system
        try:
            if system == "Windows":
                # Prefer WMIC which can filter on CommandLine
                try:
                    r = subprocess.run(
                        ['wmic', 'process', 'where', 'name="chrome.exe"', 'get', 'CommandLine'],
                        capture_output=True, text=True, timeout=3
                    )
                    if "remote-debugging-port" in r.stdout:
                        return True
                except Exception:
                    pass
                # Fallback: tasklist + best-effort cmdline via powershell
                try:
                    r = subprocess.run(
                        ['powershell', '-Command',
                         "Get-CimInstance Win32_Process -Filter \"Name='chrome.exe'\" | Select-Object -ExpandProperty CommandLine"],
                        capture_output=True, text=True, timeout=3
                    )
                    if "remote-debugging-port" in r.stdout:
                        return True
                except Exception:
                    pass
                # Last fallback: if chrome.exe exists but port not open -> NOT debugging
                return False

            # macOS / Linux: pgrep -f on the flag, with fallbacks if pgrep missing
            pgrep = shutil.which("pgrep")
            if pgrep:
                r = subprocess.run([pgrep, "-f", f"remote-debugging-port={self.DEBUG_PORT}"],
                                   capture_output=True, text=True, timeout=2)
                if r.returncode == 0 and r.stdout.strip():
                    return True
                # Also try generic chrome process check for log clarity
                return False
            # No pgrep: try ps
            ps = shutil.which("ps")
            if ps:
                r = subprocess.run([ps, "aux"], capture_output=True, text=True, timeout=2)
                if f"remote-debugging-port={self.DEBUG_PORT}" in r.stdout:
                    return True
            return False
        except Exception:
            return False

    def _build_chrome_options(self) -> webdriver.ChromeOptions:
        opts = webdriver.ChromeOptions()
        opts.add_experimental_option("debuggerAddress", f"127.0.0.1:{self.DEBUG_PORT}")
        # Headless is NOT used when attaching to existing Chrome; flag kept for
        # future use and for explicit driver creation outside debug mode.
        # On Linux, remote debugging still benefits from a few stability flags
        # when the user runs start_chrome.py with those flags.
        if self._system == "Linux":
            # These are harmless when attaching (they are ignored) but document intent
            pass
        return opts

    # ------------------------------------------------------------------
    # Chrome status + auto-start
    # ------------------------------------------------------------------
    def _check_chrome_status(self):
        """
        Smart Chrome Status Detection with guarded auto-start:
        - Checks if port 9222 is open -> already debugging.
        - If not, checks cooldown to avoid spamming launches.
        - Optionally checks if a debug chrome process is already starting.
        - Otherwise launches start_chrome.py (cross-platform) or legacy .sh.
        Never kills or restarts the user's own Chrome.
        """
        if self._is_port_open():
            logger.debug(self.MODULE_NAME, "✅ Chrome is running with remote debugging enabled")
            return "chrome_debugging"

        now = time.monotonic()
        if now - self._last_launch_attempt < self.LAUNCH_COOLDOWN:
            logger.debug(self.MODULE_NAME, "Chrome launch cooldown active — waiting")
            return "chrome_start_pending"

        # If a debug process seems to be starting, just wait
        if self._is_debug_chrome_process_running():
            self._last_launch_attempt = now
            logger.debug(self.MODULE_NAME, "Chrome is starting with remote debugging...")
            return "chrome_starting"

        # Need to launch a dedicated debug Chrome
        self._last_launch_attempt = now
        py_path = Path(__file__).with_name("start_chrome.py")
        sh_path = Path(__file__).with_name("start_chrome.sh")

        try:
            if py_path.is_file():
                # Cross-platform launcher
                cmd = [sys.executable, str(py_path)]
                if self._system == "Windows":
                    # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
                    creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(subprocess, "DETACHED_PROCESS", 0)
                    subprocess.Popen(cmd, creationflags=creationflags,
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                else:
                    subprocess.Popen(cmd, start_new_session=True,
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                logger.success(self.MODULE_NAME, "✅ Chrome launch requested via start_chrome.py")
                logger.info(self.MODULE_NAME, "⏳ Waiting for Chrome to start...")
                return "chrome_started"

            if sh_path.is_file():
                # Legacy fallback (macOS/Linux)
                if self._system == "Windows":
                    logger.error(self.MODULE_NAME, "❌ start_chrome.sh cannot run on Windows")
                    logger.info(self.MODULE_NAME, "💡 Please run: python start_chrome.py")
                    return "chrome_not_running"
                subprocess.Popen(["bash", str(sh_path)], start_new_session=True,
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                logger.success(self.MODULE_NAME, "✅ Chrome started with remote debugging (legacy sh)")
                logger.info(self.MODULE_NAME, "⏳ Waiting for Chrome to start...")
                return "chrome_started"

            logger.error(self.MODULE_NAME, "❌ Could not find start_chrome.py (or legacy start_chrome.sh)")
            logger.info(self.MODULE_NAME, "💡 Please run: python start_chrome.py")
            if self._system == "Windows":
                logger.info(self.MODULE_NAME, "   Windows: py -m desktop_dashboard.desktop_modules.start_chrome")
            elif self._system == "Linux":
                logger.info(self.MODULE_NAME, "   Linux: python3 desktop_dashboard/desktop_modules/start_chrome.py")
            else:
                logger.info(self.MODULE_NAME, "   macOS: python3 desktop_dashboard/desktop_modules/start_chrome.py")
            return "chrome_not_running"

        except Exception as e:
            logger.error(self.MODULE_NAME, f"❌ Failed to launch Chrome: {e}")
            logger.info(self.MODULE_NAME, "💡 Please run: python start_chrome.py")
            return "chrome_not_running"

    # ------------------------------------------------------------------
    # Selenium driver
    # ------------------------------------------------------------------
    def get_or_create_driver(self):
        """
        Persistent Driver Singleton:
        Attaches strictly to 127.0.0.1:9222. Reuses self.driver if active.
        NEVER spawns any new Chrome process or window.
        Works identically on Windows / macOS / Linux.
        """
        if self.driver is not None:
            try:
                _ = self.driver.title
                _ = len(self.driver.window_handles)
                return self.driver
            except Exception:
                logger.warn(self.MODULE_NAME, "Existing Chrome session lost. Attempting re-attachment...")
                self.driver = None

        if not self._is_port_open():
            self._check_chrome_status()
            logger.debug(self.MODULE_NAME, f"Chrome port {self.DEBUG_PORT} is inactive. DOM automation disabled, using OS media keys instead.")
            return None

        try:
            debug_opts = self._build_chrome_options()
            self.driver = webdriver.Chrome(options=debug_opts)
            logger.success(self.MODULE_NAME, f"✅ Attached to Chrome instance on port {self.DEBUG_PORT} ({self._system})!")
            return self.driver
        except Exception as attach_err:
            # Provide OS-specific hint
            hint = ""
            if self._system == "Windows":
                hint = " (Windows: ensure Chrome was started with --remote-debugging-port=9222 and no other Chrome is blocking the port)"
            elif self._system == "Linux":
                hint = " (Linux: ensure chrome --remote-debugging-port=9222 is running; check that /tmp or ~/chrome-debug-profile is writable)"
            logger.error(self.MODULE_NAME, f"Failed to attach to Chrome on port {self.DEBUG_PORT}{hint}: {attach_err}")
            self.driver = None
            return None

    def focus_or_get_jiosaavn_tab(self):
        """
        Strict Tab Detection:
        Iterates through driver.window_handles.
        Switches to each handle and checks if 'jiosaavn.com' in driver.current_url.lower().
        If found, switches to it and returns True.
        NEVER opens new windows or tabs if not found.
        Cross-platform: same DOM, same Selenium API on all OSes.
        """
        driver = self.get_or_create_driver()
        if not driver:
            logger.debug(self.MODULE_NAME, "No active Chrome driver connected on port 9222. Using OS media keys instead.")
            return False

        try:
            handles = driver.window_handles
            for handle in handles:
                try:
                    driver.switch_to.window(handle)
                    curr_url = (driver.current_url or "").lower()
                    if "jiosaavn.com" in curr_url:
                        logger.info(self.MODULE_NAME, f"Focused existing JioSaavn tab: {driver.current_url}")
                        return True
                except Exception:
                    continue

            logger.warn(self.MODULE_NAME, "No active JioSaavn tab found among open Chrome windows. Please navigate to JioSaavn in your browser.")
            return False
        except Exception as e:
            logger.error(self.MODULE_NAME, f"Error detecting JioSaavn tab: {e}")
            return False

    def execute_js_click(self, selectors, description="element"):
        """Reuses self.driver to execute DOM clicks on existing tab without spawning windows. Cross-platform."""
        if not self.focus_or_get_jiosaavn_tab():
            return False

        try:
            js_script = """
            const selectors = arguments[0];
            for (let sel of selectors) {
                let elems = document.querySelectorAll(sel);
                for (let el of elems) {
                    let text = (el.innerText || el.textContent || '').trim().toLowerCase();
                    if (text.includes('new playlist') || text.includes('create')) continue;
                    if (el && (el.offsetParent !== null || el.offsetWidth > 0)) {
                        try {
                            el.click();
                            return { success: true, selector: sel };
                        } catch (e) {
                            try {
                                el.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true, view: window }));
                                return { success: true, selector: sel };
                            } catch (e2) {}
                        }
                    }
                }
            }
            return { success: false };
            """
            result = self.driver.execute_script(js_script, selectors)
            if result and result.get("success"):
                logger.success(self.MODULE_NAME, f"✅ Clicked '{result.get('selector')}' for {description}")
                return True
            else:
                logger.warn(self.MODULE_NAME, f"DOM click found no matching elements for {description}")
                return False
        except Exception as e:
            logger.warn(self.MODULE_NAME, f"JS click execution error for {description}: {e}")
            return False

    def open_new_tab(self, url="https://www.jiosaavn.com"):
        """
        Explicitly opens a new browser tab with the specified URL and switches focus to it.
        Cross-platform: uses Selenium new window API, fallback to window.open JS.
        """
        driver = self.get_or_create_driver()
        if not driver:
            return False

        try:
            initial_handles = set(driver.window_handles)
            try:
                driver.switch_to.new_window('tab')
                driver.get(url)
            except Exception:
                driver.execute_script(f"window.open('{url}', '_blank');")
                time.sleep(0.5)
                new_handles = set(driver.window_handles) - initial_handles
                if new_handles:
                    driver.switch_to.window(list(new_handles)[0])
                elif driver.window_handles:
                    driver.switch_to.window(driver.window_handles[-1])
            
            logger.success(self.MODULE_NAME, f"🚀 Opened new browser tab: {url}")
            return True
        except Exception as e:
            logger.error(self.MODULE_NAME, f"Failed to open new tab for {url}: {e}")
            return False

    def focus_or_open_tab(self, url="https://www.jiosaavn.com"):
        """
        Focuses an existing JioSaavn tab, or navigates current tab / opens url.
        Cross-platform.
        """
        driver = self.get_or_create_driver()
        if not driver:
            return False

        try:
            for handle in driver.window_handles:
                try:
                    driver.switch_to.window(handle)
                    if "jiosaavn.com" in (driver.current_url or "").lower():
                        if url and (driver.current_url or "").rstrip('/') != url.rstrip('/'):
                            driver.get(url)
                        logger.info(self.MODULE_NAME, f"Focused JioSaavn tab: {driver.current_url}")
                        return True
                except Exception:
                    continue

            # If no JioSaavn tab exists, use first handle
            if driver.window_handles:
                driver.switch_to.window(driver.window_handles[0])
                driver.get(url)
                logger.info(self.MODULE_NAME, f"Opened {url} in active tab")
                return True

            return False
        except Exception as e:
            logger.error(self.MODULE_NAME, f"Error in focus_or_open_tab: {e}")
            return False

    def _resolve_jiosaavn_autocomplete(self, query):
        """
        Queries JioSaavn's official autocomplete API to resolve exact target URL.
        Returns tuple: (target_url, title, type_name) or (None, None, None)
        Network operation — OS independent.
        """
        import urllib.request
        import urllib.parse
        import json

        try:
            encoded_query = urllib.parse.quote(query.strip())
            api_url = f"https://www.jiosaavn.com/api.php?__call=autocomplete.get&query={encoded_query}&_format=json&_marker=0&ctx=web6dot0"
            req = urllib.request.Request(
                api_url,
                headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}
            )
            with urllib.request.urlopen(req, timeout=4) as resp:
                data = json.loads(resp.read().decode('utf-8'))

            # Priority 1: Top query match
            if 'topquery' in data and isinstance(data['topquery'].get('data'), list) and len(data['topquery']['data']) > 0:
                item = data['topquery']['data'][0]
                url = item.get('url', '').replace('http://', 'https://')
                if url:
                    return (url, item.get('title', query), item.get('type', 'Top Match'))

            # Priority 2: Songs match
            if 'songs' in data and isinstance(data['songs'].get('data'), list) and len(data['songs']['data']) > 0:
                item = data['songs']['data'][0]
                url = item.get('url', '').replace('http://', 'https://')
                if url:
                    return (url, item.get('title', query), 'Song')

            # Priority 3: Albums match
            if 'albums' in data and isinstance(data['albums'].get('data'), list) and len(data['albums']['data']) > 0:
                item = data['albums']['data'][0]
                url = item.get('url', '').replace('http://', 'https://')
                if url:
                    return (url, item.get('title', query), 'Album')

            # Priority 4: Playlists match
            if 'playlists' in data and isinstance(data['playlists'].get('data'), list) and len(data['playlists']['data']) > 0:
                item = data['playlists']['data'][0]
                url = item.get('url', '').replace('http://', 'https://')
                if url:
                    return (url, item.get('title', query), 'Playlist')

        except Exception as err:
            logger.debug(self.MODULE_NAME, f"Autocomplete API query error: {err}")

        return (None, None, None)

    def in_tab_search_and_play(self, query):
        """
        404-Proof In-Tab Autocomplete Search & Direct Play:
        1. Resolves exact target URL using JioSaavn Autocomplete API.
        2. Navigates directly to the song/album/playlist in the active JioSaavn tab.
        3. Auto-clicks the dedicated Play button (.js-play-button / [aria-label='Play']).
        4. Gracefully falls back to search page navigation if needed.
        Cross-platform: pure Selenium + network.
        """
        if not query or not str(query).strip():
            logger.warn(self.MODULE_NAME, "Empty search query received.")
            return False

        query = str(query).strip()

        # Ensure JioSaavn tab is active
        if not self.focus_or_get_jiosaavn_tab():
            if not self.focus_or_open_tab("https://www.jiosaavn.com"):
                logger.warn(self.MODULE_NAME, "Cannot perform search: No active JioSaavn tab found on port 9222.")
                return False

        driver = self.driver
        logger.info(self.MODULE_NAME, f"🔍 Resolving search query: '{query}'...")

        try:
            # Phase 1: Try Autocomplete API
            target_url, title, item_type = self._resolve_jiosaavn_autocomplete(query)

            if target_url:
                logger.success(self.MODULE_NAME, f"🎯 Resolved {item_type}: '{title}' -> {target_url}")
                driver.get(target_url)
            else:
                # Fallback: Direct Search Results Page
                import urllib.parse
                search_url = f"https://www.jiosaavn.com/search/{urllib.parse.quote(query)}"
                logger.info(self.MODULE_NAME, f"No direct autocomplete match. Navigating to search page: {search_url}")
                driver.get(search_url)

            # Phase 2: Wait for DOM and trigger Play
            time.sleep(2.0)

            js_click_play = """
            const playSelectors = [
                'a.c-btn--primary.js-play-button',
                'button.c-btn--primary.js-play-button',
                'a.js-play-button',
                'button.js-play-button',
                '.js-play-button',
                '.o-snippet__action-final',
                '.o-icon-play-circle',
                '.c-song__play',
                'a[aria-label*="Play"]',
                'button[aria-label*="Play"]',
                'span[aria-label="Play"]',
                '#player_play_pause'
            ];

            for (let sel of playSelectors) {
                let elems = document.querySelectorAll(sel);
                for (let el of elems) {
                    let text = (el.innerText || el.textContent || '').trim().toLowerCase();
                    if (text.includes('new playlist') || text.includes('create') || text.includes('log in') || text.includes('sign up')) {
                        continue;
                    }
                    if (el && (el.offsetParent !== null || el.offsetWidth > 0)) {
                        try {
                            el.click();
                            return { success: true, selector: sel, text: text };
                        } catch(e) {
                            try {
                                el.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true, view: window }));
                                return { success: true, selector: sel, text: text };
                            } catch(e2) {}
                        }
                    }
                }
            }
            return { success: false };
            """

            # Retry clicking play button up to 3 times
            for attempt in range(3):
                result = driver.execute_script(js_click_play)
                if result and result.get("success"):
                    logger.success(self.MODULE_NAME, f"✅ Started playback for '{title or query}' using '{result.get('selector')}'")
                    return True
                time.sleep(1.0)

            logger.warn(self.MODULE_NAME, f"Navigated to '{title or query}', but play button click did not register.")
            return True

        except Exception as e:
            logger.error(self.MODULE_NAME, f"Search & play execution error for '{query}': {e}")
            return False

    def quit_driver(self):
        if self.driver is not None:
            self.driver = None
            logger.info(self.MODULE_NAME, "Detached driver reference.")

    # ------------------------------------------------------------------
    # Diagnostics (useful for UI / health checks)
    # ------------------------------------------------------------------
    def get_diagnostics(self) -> dict:
        return {
            "os": self._system,
            "port": self.DEBUG_PORT,
            "port_open": self._is_port_open(),
            "debug_process": self._is_debug_chrome_process_running(),
            "driver_attached": self.driver is not None,
        }
