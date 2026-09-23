from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.common.exceptions import WebDriverException, NoSuchWindowException
import time
import logging

logger = logging.getLogger(__name__)

class GmailSessionManager:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(GmailSessionManager, cls).__new__(cls)
            cls._instance.driver = None
            cls._instance.gmail_tab = None
        return cls._instance

    def _init_driver(self):
        import os
        options = webdriver.ChromeOptions()
        options.add_experimental_option("detach", True)
        options.add_argument("--disable-notifications")
        options.add_argument("--start-maximized")
        # Suppress first‑run and infobar prompts
        options.add_argument("--no-first-run")
        options.add_argument("--disable-infobars")
        # Use a persistent user‑data directory for Gmail profile
        base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
        profile_dir = os.path.join(base_dir, "data", "browser_profiles", "gmail")
        os.makedirs(profile_dir, exist_ok=True)
        options.add_argument(f"--user-data-dir={profile_dir}")
        # Use the default profile within the user‑data directory
        options.add_argument("--profile-directory=Default")
        # Disable automation detection flags
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option("useAutomationExtension", False)

        self.driver = webdriver.Chrome(options=options)
        self.gmail_tab = None

    def get_gmail_tab(self):
        if self.driver is None:
            self._init_driver()
            
        try:
            handles = self.driver.window_handles
        except WebDriverException:
            logger.info("WebDriver died. Restarting...")
            self._init_driver()
            handles = self.driver.window_handles

        # Reuse existing Gmail tab if possible
        if self.gmail_tab and self.gmail_tab in handles:
            self.driver.switch_to.window(self.gmail_tab)
            return self.driver
        # Look for any tab already on Gmail
        for handle in handles:
            self.driver.switch_to.window(handle)
            if "mail.google.com" in self.driver.current_url:
                self.gmail_tab = handle
                return self.driver
        # No existing Gmail tab – reuse the first tab and navigate it directly to Gmail
        first_handle = handles[0]
        self.driver.switch_to.window(first_handle)
        self.gmail_tab = first_handle
        self.driver.get("https://mail.google.com")
        time.sleep(3)  # Wait for Gmail to load
        return self.driver

    def execute_in_tab(self, action_func):
        driver = self.get_gmail_tab()
        try:
            return action_func(driver)
        except WebDriverException as e:
            logger.error(f"Error executing in tab: {e}")
            driver = self.get_gmail_tab()
            return action_func(driver)

    def close_session(self):
        if self.driver:
            try:
                self.driver.quit()
            except Exception as e:
                logger.error(f"Error closing driver: {e}")
            finally:
                self.driver = None
                self.gmail_tab = None

session_manager = GmailSessionManager()
