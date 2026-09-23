"""
Cross-platform OS operations abstraction module.
Provides unified interface for system volume control, media keys, and media status polling
across Windows, macOS, and Linux.

All classes are imported on any OS — actual system calls are guarded so the
module can be imported on any platform for testing / diagnostics.
"""

import platform
import subprocess
import time
import shutil
import asyncio
import logging
from logger import logger

# Silence noisy COM debug logs from comtypes
logging.getLogger("comtypes").setLevel(logging.WARNING)

# Log winrt ImportError only once so the 1s media-status poller doesn't spam.
_winrt_missing_logged = False


class OSOperations:
    """Base class for OS-specific operations"""
    
    def __init__(self):
        self.system = platform.system()
        logger.info("OSOperations", f"Initialized for {self.system}")
    
    def get_system_volume(self):
        """Get current system volume percentage (0-100)"""
        raise NotImplementedError("Subclasses must implement get_system_volume")
    
    def set_system_volume(self, volume_pct):
        """Set system volume percentage (0-100). Returns actual volume set."""
        raise NotImplementedError("Subclasses must implement set_system_volume")
    
    def send_media_key(self, key_name):
        """Send media key command. Key names: 'Play / Pause', 'Next Track', 'Previous Track', 'Volume Up', 'Volume Down'"""
        raise NotImplementedError("Subclasses must implement send_media_key")
    
    async def get_media_status(self):
        """Get current media status (title, artist, is_playing). Returns dict."""
        raise NotImplementedError("Subclasses must implement get_media_status")


class WindowsOperations(OSOperations):
    """Windows-specific operations using PyCaw/WinRT with ctypes fallbacks"""
    
    def get_system_volume(self):
        if self.system != "Windows":
            return 100
        # Try PyCaw first
        try:
            import comtypes
            comtypes.CoInitialize()
            from pycaw.pycaw import AudioUtilities
            spk = AudioUtilities.GetSpeakers()
            return round(spk.EndpointVolume.GetMasterVolumeLevelScalar() * 100)
        except ImportError:
            logger.debug("WindowsOperations", "pycaw/comtypes not installed — trying winmm fallback")
        except Exception as e:
            logger.warn("WindowsOperations", f"PyCaw get volume failed: {e} — trying fallback")

        # Fallback: winmm waveOutGetVolume via ctypes
        try:
            import ctypes
            winmm = ctypes.windll.winmm
            vol = ctypes.c_uint()
            # waveOutGetVolume(0, &vol) — low word is left, high is right
            if winmm.waveOutGetVolume(0, ctypes.byref(vol)) == 0:
                left = vol.value & 0xFFFF
                # 0xFFFF == max
                return round((left / 0xFFFF) * 100)
        except Exception as e:
            logger.warn("WindowsOperations", f"winmm fallback failed: {e}")
        return 50  # unknown, return mid-level
    
    def set_system_volume(self, volume_pct):
        if self.system != "Windows":
            return volume_pct
        try:
            import comtypes
            comtypes.CoInitialize()
            from pycaw.pycaw import AudioUtilities
            spk = AudioUtilities.GetSpeakers()
            scalar = max(0.0, min(1.0, float(volume_pct) / 100.0))
            spk.EndpointVolume.SetMasterVolumeLevelScalar(scalar, None)
            actual = round(spk.EndpointVolume.GetMasterVolumeLevelScalar() * 100)
            logger.success("WindowsOperations", f"System volume set to {actual}%")
            return actual
        except ImportError:
            logger.debug("WindowsOperations", "pycaw/comtypes not installed — trying winmm/nircmd fallback")
        except Exception as e:
            logger.warn("WindowsOperations", f"PyCaw set volume failed: {e} — trying fallback")

        # Fallback: try nircmd if present (common on Windows)
        try:
            nircmd = shutil.which("nircmd")
            if nircmd:
                vol = int(max(0, min(100, int(volume_pct))) * 65535 / 100)
                # nircmd setsysvolume expects 0-65535
                subprocess.run([nircmd, "setsysvolume", str(vol)], check=True, timeout=3)
                logger.success("WindowsOperations", f"System volume set via nircmd to {volume_pct}%")
                return int(volume_pct)
        except Exception as e:
            logger.debug("WindowsOperations", f"nircmd fallback failed: {e}")

        # Last resort: waveOutSetVolume
        try:
            import ctypes
            winmm = ctypes.windll.winmm
            v = int(max(0, min(100, int(volume_pct))) * 0xFFFF / 100)
            packed = (v & 0xFFFF) | ((v & 0xFFFF) << 16)
            winmm.waveOutSetVolume(0, packed)
            logger.success("WindowsOperations", f"System volume set via winmm to {volume_pct}%")
            return int(volume_pct)
        except Exception as e:
            logger.warn("WindowsOperations", f"All volume fallbacks failed: {e}")
            return volume_pct
    
    def send_media_key(self, key_name):
        if self.system != "Windows":
            return False
        try:
            import ctypes
            VK_CODES = {
                "Volume Up": 0xAF,
                "Volume Down": 0xAE,
                "Next Track": 0xB0,
                "Previous Track": 0xB1,
                "Play / Pause": 0xB3
            }
            vk_code = VK_CODES.get(key_name)
            if vk_code:
                ctypes.windll.user32.keybd_event(vk_code, 0, 0, 0)
                time.sleep(0.05)
                ctypes.windll.user32.keybd_event(vk_code, 0, 2, 0)
                logger.success("WindowsOperations", f"Sent media key: {key_name}")
                return True
        except Exception as e:
            logger.error("WindowsOperations", f"Failed to send media key {key_name}: {e}")
        # Fallback: try PowerShell SendKeys for media
        try:
            ps_map = {
                "Play / Pause": "{MEDIA_PLAY_PAUSE}",
                "Next Track": "{MEDIA_NEXT_TRACK}",
                "Previous Track": "{MEDIA_PREV_TRACK}",
            }
            if key_name in ps_map:
                subprocess.run(["powershell", "-Command",
                    f"$w=New-Object -ComObject WScript.Shell; $w.SendKeys('{ps_map[key_name]}')"],
                    timeout=3, capture_output=True)
                logger.success("WindowsOperations", f"Sent media key via PowerShell: {key_name}")
                return True
        except Exception:
            pass
        return False
    
    async def get_media_status(self):
        if self.system != "Windows":
            return {"title": "Not Supported", "artist": "Unknown", "is_playing": False}
        
        try:
            from winrt.windows.media.control import GlobalSystemMediaTransportControlsSessionManager
            manager = await GlobalSystemMediaTransportControlsSessionManager.request_async()
            current_session = manager.get_current_session()
            
            if current_session:
                playback_info = current_session.get_playback_info()
                is_playing = playback_info.playback_status == 4
                media_props = await current_session.try_get_media_properties_async()
                
                return {
                    "title": media_props.title or "Waiting for Track...",
                    "artist": media_props.artist or "Unknown Artist",
                    "is_playing": is_playing
                }
        except ImportError:
            global _winrt_missing_logged
            if not _winrt_missing_logged:
                _winrt_missing_logged = True
                logger.debug("WindowsOperations", "winrt not installed — media status unavailable (install winsdk)")
        except Exception as e:
            logger.warn("WindowsOperations", f"Failed to get media status: {e}")
        
        return {"title": "Waiting for Track...", "artist": "Unknown Artist", "is_playing": False}


class MacOSOperations(OSOperations):
    """macOS-specific operations using AppleScript and subprocess"""
    
    def get_system_volume(self):
        if self.system != "Darwin":
            return 100
        try:
            script = 'output volume of (get volume settings)'
            result = subprocess.run(['osascript', '-e', script], capture_output=True, text=True, timeout=3)
            if result.returncode == 0 and result.stdout.strip().isdigit():
                return int(result.stdout.strip())
            return 100
        except Exception as e:
            logger.warn("MacOSOperations", f"Failed to get system volume: {e}")
            return 100
    
    def set_system_volume(self, volume_pct):
        if self.system != "Darwin":
            return volume_pct
        try:
            volume = max(0, min(100, int(volume_pct)))
            script = f'set volume output volume {volume}'
            subprocess.run(['osascript', '-e', script], check=True, timeout=3)
            logger.success("MacOSOperations", f"System volume set to {volume}%")
            return volume
        except Exception as e:
            logger.warn("MacOSOperations", f"Failed to set system volume: {e}")
            return volume_pct
    
    def send_media_key(self, key_name):
        if self.system != "Darwin":
            return False
        try:
            if key_name in ["Volume Up", "Volume Down"]:
                logger.warn("MacOSOperations", f"Volume keys should be handled via set_system_volume")
                return False
            
            logger.warn("MacOSOperations", f"⚠️  Browser media control requires Chrome remote debugging")
            logger.info("MacOSOperations", "💡 To enable JioSaavn control:")
            logger.info("MacOSOperations", "   1. Run: python desktop_dashboard/desktop_modules/start_chrome.py  (cross-platform)")
            logger.info("MacOSOperations", "      (legacy: ./start_chrome.sh on macOS/Linux)")
            logger.info("MacOSOperations", "   2. Navigate to JioSaavn in that Chrome instance")
            logger.info("MacOSOperations", "   3. Chrome remote debugging bypasses OS security restrictions")
            
            return False
            
        except Exception as e:
            logger.error("MacOSOperations", f"Failed to send media key {key_name}: {e}")
            return False
    
    async def get_media_status(self):
        if self.system != "Darwin":
            return {"title": "Not Supported", "artist": "Unknown", "is_playing": False}
        
        try:
            script = '''
            tell application "System Events"
                set isPlaying to false
                set trackTitle to "Waiting for Track..."
                set trackArtist to "Unknown Artist"
                
                if (name of processes) contains "Music" then
                    tell application "Music"
                        if player state is playing then
                            set isPlaying to true
                            set trackTitle to name of current track
                            set trackArtist to artist of current track
                        end if
                    end tell
                else if (name of processes) contains "Spotify" then
                    tell application "Spotify"
                        if player state is playing then
                            set isPlaying to true
                            set trackTitle to name of current track
                            set trackArtist to artist of current track
                        end if
                    end tell
                end if
                
                return {trackTitle, trackArtist, isPlaying}
            end tell
            '''
            
            result = subprocess.run(['osascript', '-e', script], capture_output=True, text=True, timeout=5)
            if result.returncode == 0:
                parts = result.stdout.strip().split(', ')
                if len(parts) >= 3:
                    return {
                        "title": parts[0].strip(),
                        "artist": parts[1].strip(),
                        "is_playing": parts[2].strip().lower() == 'true'
                    }
        except Exception as e:
            logger.warn("MacOSOperations", f"Failed to get media status: {e}")
        
        return {"title": "Waiting for Track...", "artist": "Unknown Artist", "is_playing": False}


class LinuxOperations(OSOperations):
    """Linux-specific operations using pulseaudio/pipewire and dbus with graceful fallbacks"""
    
    def get_system_volume(self):
        if self.system != "Linux":
            return 100
        # Try pactl (PulseAudio / PipeWire)
        try:
            result = subprocess.run(
                ['pactl', 'get-sink-volume', '@DEFAULT_SINK@'],
                capture_output=True, text=True, timeout=3
            )
            if result.returncode == 0:
                import re
                match = re.search(r'(\d+)%', result.stdout)
                if match:
                    return int(match.group(1))
        except FileNotFoundError:
            logger.debug("LinuxOperations", "pactl not found — trying amixer")
        except Exception as e:
            logger.debug("LinuxOperations", f"pactl failed: {e} — trying amixer")

        # Fallback: amixer
        try:
            result = subprocess.run(['amixer', 'get', 'Master'], capture_output=True, text=True, timeout=3)
            if result.returncode == 0:
                import re
                m = re.search(r'\[(\d+)%\]', result.stdout)
                if m:
                    return int(m.group(1))
        except FileNotFoundError:
            logger.debug("LinuxOperations", "amixer not found")
        except Exception as e:
            logger.warn("LinuxOperations", f"amixer failed: {e}")

        # Fallback: wpctl (WirePlumber)
        try:
            result = subprocess.run(['wpctl', 'get-volume', '@DEFAULT_AUDIO_SINK@'], capture_output=True, text=True, timeout=3)
            if result.returncode == 0:
                import re
                m = re.search(r'([0-9.]+)', result.stdout)
                if m:
                    return int(float(m.group(1)) * 100)
        except Exception:
            pass

        logger.warn("LinuxOperations", "No volume backend found (pactl/amixer/wpctl missing), returning 50")
        return 50
    
    def set_system_volume(self, volume_pct):
        if self.system != "Linux":
            return volume_pct
        volume = max(0, min(100, int(volume_pct)))
        # Try pactl
        try:
            subprocess.run(
                ['pactl', 'set-sink-volume', '@DEFAULT_SINK@', f'{volume}%'],
                check=True, timeout=3
            )
            logger.success("LinuxOperations", f"System volume set to {volume}% via pactl")
            return volume
        except FileNotFoundError:
            logger.debug("LinuxOperations", "pactl not found — trying amixer")
        except Exception as e:
            logger.debug("LinuxOperations", f"pactl set failed: {e} — trying amixer")
        
        # Fallback: amixer
        try:
            subprocess.run(['amixer', 'set', 'Master', f'{volume}%'], check=True, timeout=3,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            logger.success("LinuxOperations", f"System volume set to {volume}% via amixer")
            return volume
        except FileNotFoundError:
            logger.debug("LinuxOperations", "amixer not found — trying wpctl")
        except Exception as e:
            logger.debug("LinuxOperations", f"amixer failed: {e} — trying wpctl")

        # Fallback: wpctl
        try:
            # wpctl expects 0.0-1.0
            subprocess.run(['wpctl', 'set-volume', '@DEFAULT_AUDIO_SINK@', f'{volume/100:.2f}'],
                           check=True, timeout=3)
            logger.success("LinuxOperations", f"System volume set to {volume}% via wpctl")
            return volume
        except Exception as e:
            logger.warn("LinuxOperations", f"All volume backends failed: {e}")
            return volume_pct
    
    def send_media_key(self, key_name):
        if self.system != "Linux":
            return False
        key_symbols = {
            "Play / Pause": "XF86AudioPlay",
            "Next Track": "XF86AudioNext",
            "Previous Track": "XF86AudioPrev",
            "Volume Up": "XF86AudioRaiseVolume",
            "Volume Down": "XF86AudioLowerVolume"
        }
        mpris_map = {
            "Play / Pause": "PlayPause",
            "Next Track": "Next",
            "Previous Track": "Previous",
        }
        # 1) Try playerctl (most reliable, works with Chrome/Chromium/Firefox/Spotify)
        playerctl = shutil.which("playerctl")
        if playerctl and key_name in mpris_map:
            try:
                subprocess.run([playerctl, mpris_map[key_name]], check=True, timeout=3,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                logger.success("LinuxOperations", f"Sent media key via playerctl: {key_name}")
                return True
            except Exception as e:
                logger.debug("LinuxOperations", f"playerctl failed for {key_name}: {e}")

        # 2) Try dbus-send MPRIS directly ( playerctl not installed )
        if key_name in mpris_map:
            try:
                # Find any MPRIS player — prefer chrome, then generic
                r = subprocess.run(
                    ['dbus-send', '--session', '--dest=org.freedesktop.DBus',
                     '--type=method_call', '/org/freedesktop/DBus',
                     'org.freedesktop.DBus.ListNames'],
                    capture_output=True, text=True, timeout=3
                )
                if r.returncode == 0:
                    # Prefer chrome-based players first
                    candidates = []
                    for line in r.stdout.splitlines():
                        if "org.mpris.MediaPlayer2." in line:
                            # extract name between quotes
                            import re
                            for m in re.finditer(r'"(org\.mpris\.MediaPlayer2\.[^"]+)"', line):
                                candidates.append(m.group(1))
                    # Prioritize chrome/chromium/firefox/spotify/vlc
                    priority = ["chrome", "chromium", "firefox", "spotify", "vlc"]
                    candidates.sort(key=lambda n: next((i for i, p in enumerate(priority) if p in n.lower()), 99))
                    for player in candidates:
                        try:
                            subprocess.run([
                                'dbus-send', '--session', '--dest', player,
                                '--type=method_call', '/org/mpris/MediaPlayer2',
                                f'org.mpris.MediaPlayer2.Player.{mpris_map[key_name]}'
                            ], check=True, timeout=2, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                            logger.success("LinuxOperations", f"Sent media key via dbus MPRIS ({player}): {key_name}")
                            return True
                        except Exception:
                            continue
            except FileNotFoundError:
                logger.debug("LinuxOperations", "dbus-send not found")
            except Exception as e:
                logger.debug("LinuxOperations", f"dbus MPRIS failed: {e}")

        # 3) Fallback: xdotool / wtype / ydotool for XF86 keys
        key_sym = key_symbols.get(key_name)
        if key_sym:
            for tool, argv in [
                ("xdotool", ["xdotool", "key", key_sym]),
                ("wtype", ["wtype", "-k", key_sym]),  # Wayland
                ("ydotool", ["ydotool", "key", key_sym]),
            ]:
                if shutil.which(tool):
                    try:
                        subprocess.run(argv, check=True, timeout=3)
                        logger.success("LinuxOperations", f"Sent media key via {tool}: {key_name}")
                        return True
                    except Exception as e:
                        logger.debug("LinuxOperations", f"{tool} failed for {key_name}: {e}")
                        continue

        logger.warn("LinuxOperations", f"No media-key backend found for '{key_name}'. Install playerctl (recommended) or xdotool/wtype.")
        return False
    
    async def get_media_status(self):
        if self.system != "Linux":
            return {"title": "Not Supported", "artist": "Unknown", "is_playing": False}
        
        # 1) Try playerctl — handles Chrome, Spotify, VLC, etc uniformly
        playerctl = shutil.which("playerctl")
        if playerctl:
            try:
                # playerctl metadata --format '{{title}}|{{artist}}|{{status}}'
                r = subprocess.run(
                    [playerctl, "metadata", "--format", "{{title}}|{{artist}}|{{status}}"],
                    capture_output=True, text=True, timeout=3
                )
                if r.returncode == 0 and r.stdout.strip():
                    parts = r.stdout.strip().split("|")
                    if len(parts) >= 3:
                        title, artist, status = parts[0].strip(), parts[1].strip(), parts[2].strip()
                        return {
                            "title": title or "Waiting for Track...",
                            "artist": artist or "Unknown Artist",
                            "is_playing": status.lower() == "playing"
                        }
                    elif len(parts) >= 1 and parts[0].strip():
                        return {"title": parts[0].strip(), "artist": "Unknown Artist", "is_playing": True}
            except Exception as e:
                logger.debug("LinuxOperations", f"playerctl metadata failed: {e}")

        # 2) Fallback: dbus MPRIS manual
        try:
            r = subprocess.run(
                ['dbus-send', '--session', '--dest=org.freedesktop.DBus',
                 '--type=method_call', '/org/freedesktop/DBus',
                 'org.freedesktop.DBus.ListNames'],
                capture_output=True, text=True, timeout=3
            )
            if r.returncode == 0:
                import re
                players = re.findall(r'"(org\.mpris\.MediaPlayer2\.[^"]+)"', r.stdout)
                # Prefer chrome/chromium/spotify/vlc
                priority = ["chrome", "chromium", "firefox", "spotify", "vlc", "mpv"]
                players.sort(key=lambda n: next((i for i, p in enumerate(priority) if p in n.lower()), 99))
                for player in players:
                    try:
                        # Get PlaybackStatus
                        status_r = subprocess.run([
                            'dbus-send', '--session', '--dest', player,
                            '--type=method_call', '/org/mpris/MediaPlayer2',
                            'org.freedesktop.DBus.Properties.Get',
                            'string:org.mpris.MediaPlayer2.Player', 'string:PlaybackStatus'
                        ], capture_output=True, text=True, timeout=2)
                        is_playing = "Playing" in status_r.stdout if status_r.returncode == 0 else False

                        meta_r = subprocess.run([
                            'dbus-send', '--session', '--dest', player,
                            '--type=method_call', '/org/mpris/MediaPlayer2',
                            'org.freedesktop.DBus.Properties.Get',
                            'string:org.mpris.MediaPlayer2.Player', 'string:Metadata'
                        ], capture_output=True, text=True, timeout=2)
                        if meta_r.returncode == 0 and "xesam:title" in meta_r.stdout:
                            # Very rough parse — extract title/artist strings
                            title_m = re.search(r'"xesam:title".*?string\s+"([^"]+)"', meta_r.stdout, re.DOTALL)
                            artist_m = re.search(r'"xesam:artist".*?string\s+"([^"]+)"', meta_r.stdout, re.DOTALL)
                            return {
                                "title": title_m.group(1) if title_m else "Linux Media",
                                "artist": artist_m.group(1) if artist_m else "Unknown Artist",
                                "is_playing": is_playing
                            }
                        elif meta_r.returncode == 0:
                            return {"title": "Linux Media", "artist": "Unknown Artist", "is_playing": is_playing}
                    except Exception:
                        continue
        except FileNotFoundError:
            logger.debug("LinuxOperations", "dbus-send not found for media status")
        except Exception as e:
            logger.warn("LinuxOperations", f"Failed to get media status: {e}")
        
        return {"title": "Waiting for Track...", "artist": "Unknown Artist", "is_playing": False}


def get_os_operations():
    """Factory function to get the appropriate OS operations instance"""
    system = platform.system()
    
    if system == "Windows":
        return WindowsOperations()
    elif system == "Darwin":
        return MacOSOperations()
    elif system == "Linux":
        return LinuxOperations()
    else:
        logger.warn("OSOperations", f"Unsupported platform: {system}, using basic fallback")
        return OSOperations()


# Global instance
os_ops = get_os_operations()


# Convenience functions that match the original API
def get_system_master_volume():
    return os_ops.get_system_volume()


def set_system_master_volume(volume_pct):
    return os_ops.set_system_volume(volume_pct)


def send_os_media_key(key_name):
    return os_ops.send_media_key(key_name)


async def get_media_status():
    return await os_ops.get_media_status()
