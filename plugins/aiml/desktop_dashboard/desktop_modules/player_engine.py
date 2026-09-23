import time
from logger import logger
from os_operations import send_os_media_key, get_system_master_volume, set_system_master_volume

class PlayerEngine:
    MODULE_NAME = "PlayerEngine"

    def __init__(self, browser_manager):
        self.browser_manager = browser_manager

    def _send_os_media_key(self, action_name):
        return send_os_media_key(action_name)

    def play_pause(self):
        logger.info(self.MODULE_NAME, "Executing Action: Play / Pause")
        
        # Try DOM Click first (works with Chrome remote debugging)
        dom_selectors = [
            "#player_play_pause",
            ".c-player__play",
            "[title='Play']",
            "[title='Pause']",
            ".play-pause-btn",
            "#play",
            "#pause",
            ".js-play",
            ".o-icon--play",
            ".o-icon--pause"
        ]
        dom_success = self.browser_manager.execute_js_click(dom_selectors, description="Play / Pause Button")
        
        if dom_success:
            return True
        
        # Fallback to OS media keys (limited on macOS due to security)
        os_success = self._send_os_media_key("Play / Pause")
        return os_success

    def next_track(self):
        logger.info(self.MODULE_NAME, "Executing Action: Next Track")
        
        # Try DOM Click first (works with Chrome remote debugging)
        dom_selectors = ["#player_next", "[title='Next']", ".c-player__next", ".js-next", "#next"]
        dom_success = self.browser_manager.execute_js_click(dom_selectors, description="Next Track Button")
        
        if dom_success:
            return True
        
        # Fallback to OS media keys (limited on macOS due to security)
        os_success = self._send_os_media_key("Next Track")
        return os_success

    def previous_track(self):
        logger.info(self.MODULE_NAME, "Executing Action: Previous Track")
        
        # Try DOM Click first (works with Chrome remote debugging)
        dom_selectors = ["#player_prev", "[title='Previous']", ".c-player__prev", ".js-prev", "#prev"]
        dom_success = self.browser_manager.execute_js_click(dom_selectors, description="Previous Track Button")
        
        if dom_success:
            return True
        
        # Fallback to OS media keys (limited on macOS due to security)
        os_success = self._send_os_media_key("Previous Track")
        return os_success

    def adjust_volume(self, action_name):
        logger.info(self.MODULE_NAME, f"Executing volume action: {action_name}")
        try:
            curr = get_system_master_volume()
            next_vol = min(100, curr + 10) if action_name == 'Volume Up' else max(0, curr - 10)
            set_system_master_volume(next_vol)
            logger.success(self.MODULE_NAME, f"✅ System volume set to {next_vol}% for '{action_name}'")
            return True
        except Exception as err:
            logger.warn(self.MODULE_NAME, f"System volume set warning: {err}")
            return False

    def search_and_play(self, song_name):
        logger.info(self.MODULE_NAME, f"Executing In-Tab Search & Play for: '{song_name}'")
        return self.browser_manager.in_tab_search_and_play(song_name)
