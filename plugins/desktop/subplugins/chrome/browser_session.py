from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.common.exceptions import WebDriverException
import time
import logging

logger = logging.getLogger(__name__)

class ChromeSessionManager:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(ChromeSessionManager, cls).__new__(cls)
            cls._instance.driver = None
            cls._instance.chrome_tab = None
        return cls._instance

    def _init_driver(self):
        options = webdriver.ChromeOptions()
        options.add_experimental_option("detach", True)
        
        options.add_argument("--disable-notifications")
        options.add_argument("--start-maximized")

        self.driver = webdriver.Chrome(options=options)
        self.chrome_tab = None

    def get_chrome_tab(self):
        if self.driver is None:
            self._init_driver()
            
        try:
            handles = self.driver.window_handles
        except WebDriverException:
            logger.info("WebDriver died. Restarting...")
            self._init_driver()
            handles = self.driver.window_handles

        if self.chrome_tab in handles:
            self.driver.switch_to.window(self.chrome_tab)
        else:
            if len(handles) == 1 and self.driver.current_url == "data:,":
                self.chrome_tab = handles[0]
                self.driver.switch_to.window(self.chrome_tab)
                self.driver.get("https://google.com")
            else:
                self.driver.execute_script("window.open('https://google.com', '_blank');")
                self.chrome_tab = self.driver.window_handles[-1]
                self.driver.switch_to.window(self.chrome_tab)
            time.sleep(2)

        return self.driver

    def execute_in_tab(self, action_func):
        driver = self.get_chrome_tab()
        try:
            return action_func(driver)
        except WebDriverException as e:
            logger.error(f"Error executing in tab: {e}")
            driver = self.get_chrome_tab()
            return action_func(driver)

    def close_session(self):
        if self.driver:
            try:
                self.driver.quit()
            except Exception as e:
                logger.error(f"Error closing driver: {e}")
            finally:
                self.driver = None
                self.chrome_tab = None

session_manager = ChromeSessionManager()
