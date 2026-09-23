from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.common.exceptions import WebDriverException, NoSuchWindowException
import time
import logging

logger = logging.getLogger(__name__)

class YouTubeSessionManager:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(YouTubeSessionManager, cls).__new__(cls)
            cls._instance.driver = None
            cls._instance.youtube_tab = None
        return cls._instance

    def _init_driver(self):
        options = webdriver.ChromeOptions()
        options.add_experimental_option("detach", True)
        
        # Optional: Add arguments to avoid some detection or make it cleaner
        options.add_argument("--disable-notifications")
        options.add_argument("--start-maximized")
        # Ensure audio plays without interaction if needed
        options.add_argument("--autoplay-policy=no-user-gesture-required")

        self.driver = webdriver.Chrome(options=options)
        self.youtube_tab = None

    def get_youtube_tab(self):
        if self.driver is None:
            self._init_driver()
            
        try:
            handles = self.driver.window_handles
        except Exception:
            logger.info("WebDriver died. Restarting...")
            self._init_driver()
            handles = self.driver.window_handles

        if self.youtube_tab in handles:
            try:
                self.driver.switch_to.window(self.youtube_tab)
            except Exception:
                self.youtube_tab = None

        if self.youtube_tab is None:
            found = False
            for handle in handles:
                try:
                    self.driver.switch_to.window(handle)
                    if "youtube.com" in self.driver.current_url:
                        self.youtube_tab = handle
                        found = True
                        break
                except Exception:
                    continue
            
            if not found:
                try:
                    if len(handles) == 1 and self.driver.current_url == "data:,":
                        self.youtube_tab = handles[0]
                        self.driver.switch_to.window(self.youtube_tab)
                        self.driver.get("https://www.youtube.com")
                        found = True
                except Exception:
                    pass
                if not found:
                    try:
                        self.driver.execute_script("window.open('https://www.youtube.com', '_blank');")
                        self.youtube_tab = self.driver.window_handles[-1]
                        self.driver.switch_to.window(self.youtube_tab)
                    except Exception:
                        self._init_driver()
                        self.driver.get("https://www.youtube.com")
                        self.youtube_tab = self.driver.window_handles[0]
                time.sleep(2)

        return self.driver

    def execute_in_tab(self, action_func):
        """
        Ensures the tab is active and then executes the function, 
        passing the driver to the function.
        """
        try:
            driver = self.get_youtube_tab()
            return action_func(driver)
        except Exception as e:
            logger.error(f"Error executing in tab: {e}")
            try:
                self.youtube_tab = None
                self.driver = None
                driver = self.get_youtube_tab()
                return action_func(driver)
            except Exception as e2:
                logger.error(f"Recovery failed: {e2}")
                return {"status": "error", "message": str(e2)}

    def close_session(self):
        if self.driver:
            try:
                self.driver.quit()
            except Exception as e:
                logger.error(f"Error closing driver: {e}")
            finally:
                self.driver = None
                self.youtube_tab = None

session_manager = YouTubeSessionManager()
