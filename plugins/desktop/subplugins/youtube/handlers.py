from .browser_session import session_manager
from .state import state
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import time

def handle_ads(driver):
    try:
        # Give a moment for the player to initialize and ad to potentially start
        time.sleep(1)
        ad_elements = driver.find_elements(By.CSS_SELECTOR, ".ad-showing")
        if not ad_elements:
            # Make sure player is focused
            driver.execute_script("document.querySelector('.html5-video-player').focus();")
            return
            
        # Ad is playing, wait for skip or finish
        for _ in range(60): # Max wait 60 seconds
            skip_buttons = driver.find_elements(By.CSS_SELECTOR, ".ytp-ad-skip-button, .ytp-skip-ad-button, .ytp-skip-ad-button-v2")
            if skip_buttons and skip_buttons[0].is_displayed():
                try:
                    skip_buttons[0].click()
                    time.sleep(1)
                    break # Skipped successfully
                except:
                    pass
            
            ad_elements = driver.find_elements(By.CSS_SELECTOR, ".ad-showing")
            if not ad_elements:
                break # Ad finished naturally
                
            time.sleep(1)
            
        # Regain focus after ad
        time.sleep(1)
        driver.execute_script("document.querySelector('.html5-video-player').focus();")
    except Exception:
        pass

def toggle_play_pause():
    def _action(driver):
        if not state["player_ready"]:
            # If player_ready is False, automatically open the first search result before executing Play.
            videos = driver.find_elements(By.CSS_SELECTOR, "ytd-video-renderer a#video-title, ytd-grid-video-renderer a#video-title, ytd-rich-grid-media a#video-title-link")
            if videos:
                videos[0].click()
                
                # Wait until the video player is fully loaded
                WebDriverWait(driver, 10).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, ".html5-video-player"))
                )
                
                handle_ads(driver)
                
                state["active_video_url"] = driver.current_url
                state["player_ready"] = True
                state["active_youtube_tab"] = driver.current_window_handle
            else:
                return {"status": "error", "message": "No video found to play"}
        else:
            # Handle mid-video ads before toggling
            handle_ads(driver)
                
        try:
            # Control the active video only
            player = driver.find_element(By.CSS_SELECTOR, ".html5-video-player")
            driver.execute_script("arguments[0].focus();", player)
            
            # Check current state to return exact message requested
            is_playing = driver.execute_script("return document.querySelector('.html5-video-player').getPlayerState() === 1;")
            
            player.send_keys("k")
            time.sleep(1) # Wait for state change
            
            new_state = driver.execute_script("return document.querySelector('.html5-video-player').getPlayerState() === 1;")
            
            if is_playing == new_state:
                return {"status": "error", "message": "Player state did not change"}
            
            if is_playing:
                return {"status": "success", "message": "Video paused"}
            else:
                return {"status": "success", "message": "Playing active video"}
        except Exception as e:
            return {"status": "error", "message": f"Failed to play/pause: {e}"}

    return session_manager.execute_in_tab(_action)

def search(payload=None):
    query = "python tutor for beginners"
    if payload and 'query' in payload:
        query = payload['query']

    def _action(driver):
        if "youtube.com" not in driver.current_url:
            driver.get("https://www.youtube.com")
            
        try:
            search_box = WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.NAME, "search_query"))
            )
            search_box.clear()
            search_box.send_keys(query)
            search_box.send_keys(Keys.RETURN)
            
            state["last_search_query"] = query
            state["player_ready"] = False
            
            # Wait for search results
            WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "ytd-video-renderer"))
            )
            time.sleep(1) # Extra buffer for elements to become clickable
            
            # Automatically click the FIRST video result
            videos = driver.find_elements(By.CSS_SELECTOR, "ytd-video-renderer a#video-title")
            if videos:
                videos[0].click()
                
                # Wait until the video player is fully loaded
                WebDriverWait(driver, 10).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, ".html5-video-player"))
                )
                
                handle_ads(driver)
                
                state["active_video_url"] = driver.current_url
                state["player_ready"] = True
                state["active_youtube_tab"] = driver.current_window_handle
            
            return {"status": "success", "message": "Song is playing"}
        except Exception as e:
            return {"status": "error", "message": f"Search failed: {e}"}

    return session_manager.execute_in_tab(_action)

def previous_video():
    def _action(driver):
        if not state["player_ready"]:
            # Fallback: open first searched video
            videos = driver.find_elements(By.CSS_SELECTOR, "ytd-video-renderer a#video-title, ytd-grid-video-renderer a#video-title, ytd-rich-grid-media a#video-title-link")
            if videos:
                videos[0].click()
                
                WebDriverWait(driver, 10).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, ".html5-video-player"))
                )
                
                handle_ads(driver)
                
                state["active_video_url"] = driver.current_url
                state["player_ready"] = True
                state["active_youtube_tab"] = driver.current_window_handle
            else:
                return {"status": "error", "message": "No video found to play"}
        else:
            handle_ads(driver)
                
        try:
            old_url = driver.current_url
            
            # Focus the YouTube video player explicitly via JS and Python
            player = driver.find_element(By.CSS_SELECTOR, ".html5-video-player")
            driver.execute_script("arguments[0].focus();", player)
            
            # Execute the native YouTube shortcut: SHIFT + P (uppercase P)
            player.send_keys("P")
            
            # Wait for the previous video to load completely by detecting URL change
            try:
                WebDriverWait(driver, 5).until(
                    lambda d: d.current_url != old_url and "watch" in d.current_url
                )
            except:
                # If no previous video exists in the player natively, fallback to browser back
                driver.back()
                try:
                    WebDriverWait(driver, 5).until(
                        lambda d: d.current_url != old_url and "watch" in d.current_url
                    )
                except:
                    return {"status": "error", "message": "No previous video found"}
                
            WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, ".html5-video-player"))
            )
            
            handle_ads(driver)
            
            # Update active_video_url after navigation
            state["active_video_url"] = driver.current_url
            
            return {"status": "success", "message": "Previous video playing"}
        except Exception as e:
            return {"status": "error", "message": str(e)}
            
    return session_manager.execute_in_tab(_action)

def next_video():
    def _action(driver):
        if not state["player_ready"]:
            return {"status": "error", "message": "Not watching a video"}
        
        handle_ads(driver)
            
        try:
            old_url = driver.current_url
            
            player = driver.find_element(By.CSS_SELECTOR, ".html5-video-player")
            driver.execute_script("arguments[0].focus();", player)
            player.send_keys("N") # Shift+N
            
            try:
                WebDriverWait(driver, 10).until(
                    lambda d: d.current_url != old_url and "watch" in d.current_url
                )
            except:
                pass
                
            WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, ".html5-video-player"))
            )
            
            handle_ads(driver)
            state["active_video_url"] = driver.current_url
            
            return {"status": "success", "message": "Next video playing"}
        except Exception as e:
            return {"status": "error", "message": str(e)}
    return session_manager.execute_in_tab(_action)

def volume_up():
    def _action(driver):
        if not state["player_ready"]:
            return {"status": "error", "message": "Not watching a video"}
            
        handle_ads(driver)
            
        try:
            player = driver.find_element(By.CSS_SELECTOR, ".html5-video-player")
            driver.execute_script("arguments[0].focus();", player)
            player.send_keys(Keys.ARROW_UP)
            return {"status": "success", "message": "YouTube: Volume Up"}
        except Exception as e:
            return {"status": "error", "message": str(e)}
    return session_manager.execute_in_tab(_action)

def volume_down():
    def _action(driver):
        if not state["player_ready"]:
            return {"status": "error", "message": "Not watching a video"}
            
        handle_ads(driver)
            
        try:
            player = driver.find_element(By.CSS_SELECTOR, ".html5-video-player")
            driver.execute_script("arguments[0].focus();", player)
            player.send_keys(Keys.ARROW_DOWN)
            return {"status": "success", "message": "YouTube: Volume Down"}
        except Exception as e:
            return {"status": "error", "message": str(e)}
    return session_manager.execute_in_tab(_action)

def close_app():
    session_manager.close_session()
    state["active_youtube_tab"] = None
    state["active_video_url"] = None
    state["last_search_query"] = None
    state["player_ready"] = False
    return {"status": "success", "message": "YouTube: Application closed"}
