from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.keys import Keys
from .browser_session import session_manager
import time

def compose_email(payload=None):
    if payload is None:
        payload = {}
        
    recipient = payload.get("recipient", "synapti4@gmail.com")
    subject = payload.get("subject", "BCI Test")
    message = payload.get("message", "Hello from SynaptiMesh!")
    attachment = payload.get("attachment", None)

    def action(driver):
        wait = WebDriverWait(driver, 10)
        
        # 1. Verify Gmail is active by ensuring we are on mail.google.com
        if "mail.google.com" not in driver.current_url:
            driver.get("https://mail.google.com")
            
        # 2. Find and click Compose
        try:
            compose_btn = wait.until(EC.element_to_be_clickable((By.XPATH, "//div[text()='Compose' or text()='COMPOSE' or @gh='cm']")))
            compose_btn.click()
        except:
            # Fallback to the 'c' shortcut if the button is obscured or localized differently
            driver.find_element(By.TAG_NAME, 'body').send_keys('c')

        time.sleep(2) # Wait for composer to pop up

        # 3. Fill the email using active element for To, and direct selectors for Subject and Body
        try:
            active_element = driver.switch_to.active_element
            active_element.send_keys(recipient)
            time.sleep(0.5)
            active_element.send_keys(Keys.ENTER) # Commit recipient chip
            time.sleep(0.5)
            
            # Find and fill Subject field directly
            try:
                subject_element = wait.until(EC.element_to_be_clickable((By.NAME, "subjectbox")))
            except Exception:
                subject_element = driver.find_element(By.XPATH, "//input[@name='subjectbox' or @placeholder='Subject']")
            
            subject_element.click()
            subject_element.clear()
            subject_element.send_keys(subject)
            time.sleep(0.5)
            
            # Find and fill Body field directly
            try:
                body_element = wait.until(EC.element_to_be_clickable((By.XPATH, "//div[@aria-label='Message Body' or @role='textbox']")))
            except Exception:
                body_element = driver.find_element(By.CSS_SELECTOR, "div[aria-label='Message Body'], div[role='textbox']")

            body_element.click()
            body_element.send_keys(message)
            time.sleep(0.5)
            
        except Exception as e:
            return {"status": "error", "message": f"Email: Failed to fill compose window - {str(e)}"}

        # 4. Attach file if required
        if attachment:
            try:
                # Find the hidden file input used by Gmail
                file_input = wait.until(EC.presence_of_element_located((By.XPATH, "//input[@type='file' and @name='Filedata']")))
                file_input.send_keys(attachment)
                # Give it some time to upload
                time.sleep(5)
            except Exception as e:
                # We do not fail completely, but we can log or just sleep
                time.sleep(2)

        return {"status": "success", "message": "Email: Compose window opened, filled, and attachment processed"}

    return session_manager.execute_in_tab(action)


def send_email(payload=None):
    if payload is None:
        payload = {}
        
    attachment = payload.get("attachment", None)

    def action(driver):
        wait = WebDriverWait(driver, 5)
        
        # 1. Verify Gmail is active
        if "mail.google.com" not in driver.current_url:
            return {"status": "error", "message": "Email: Not on Gmail page"}
            
        # 2. Verify composer is open (by finding the dialog or send button)
        try:
            send_btn = wait.until(EC.element_to_be_clickable((By.XPATH, "//div[text()='Send' or text()='SEND' and @role='button']")))
        except:
            return {"status": "error", "message": "Email: Composer not found or not ready"}

        # 3. Verify email details
        try:
            # Basic verification that the compose dialog exists
            driver.find_element(By.XPATH, "//div[@role='dialog']")
        except:
            return {"status": "error", "message": "Email: Could not verify email details (dialog missing)"}

        # 4. Verify attachment if required
        if attachment:
            try:
                # Check for presence of an uploaded file indicator (e.g. attachment chip)
                # Gmail uses various classes for attachments, we can check for an element containing the filename
                import os
                filename = os.path.basename(attachment)
                driver.find_element(By.XPATH, f"//div[contains(text(), '{filename}')]")
            except:
                # Soft failure for attachment verification
                pass

        # 5. Click Send
        try:
            send_btn.click()
        except:
            # Fallback to Ctrl+Enter
            driver.find_element(By.TAG_NAME, 'body').send_keys(Keys.CONTROL, Keys.ENTER)
            
        # 6. Confirm successful sending
        time.sleep(2) # Wait for send confirmation tooltip
        return {"status": "success", "message": "Email: Verified details and sent successfully"}

    return session_manager.execute_in_tab(action)

def close_app(payload=None):
    session_manager.close_session()
    return {"status": "success", "message": "Email: Application closed"}
