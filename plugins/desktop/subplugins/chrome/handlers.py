from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from .browser_session import session_manager

def open_predefined_article():
    def action(driver):
        driver.get("https://en.wikipedia.org/wiki/Brain%E2%80%93computer_interface")
        return {"status": "success", "message": "Chrome: Opened article"}
    return session_manager.execute_in_tab(action)

def scroll_up():
    def action(driver):
        driver.execute_script("window.scrollBy(0, -500);")
        return {"status": "success", "message": "Chrome: Scrolled up"}
    return session_manager.execute_in_tab(action)

def scroll_down():
    def action(driver):
        driver.execute_script("window.scrollBy(0, 500);")
        return {"status": "success", "message": "Chrome: Scrolled down"}
    return session_manager.execute_in_tab(action)

def open_search_bar():
    def action(driver):
        driver.get("https://google.com")
        try:
            search_box = WebDriverWait(driver, 5).until(
                EC.presence_of_element_located((By.NAME, "q"))
            )
            search_box.click()
            return {"status": "success", "message": "Chrome: Search bar focused"}
        except Exception:
            return {"status": "error", "message": "Chrome: Could not focus search"}
    return session_manager.execute_in_tab(action)

def close_app():
    session_manager.close_session()
    return {"status": "success", "message": "Chrome: Application closed"}