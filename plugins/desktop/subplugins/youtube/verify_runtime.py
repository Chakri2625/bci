import asyncio
import time
import sys
import os

# Add EMBEDED to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../..")))

from plugins.desktop.subplugins.youtube.plugin import YoutubePlugin
from plugins.desktop.subplugins.youtube.state import state

async def run_tests():
    plugin = YoutubePlugin()
    
    print("\n--- 1. Testing Search ---")
    res = await plugin.execute("search", {"query": "Believer Imagine Dragons"})
    print("Search Result:", res)
    print("State player_ready:", state["player_ready"])
    print("State URL:", state["active_video_url"])
    
    print("\n--- Letting it play for 5 seconds ---")
    time.sleep(5)
    
    print("\n--- 2. Testing Play/Pause (Pause) ---")
    res = await plugin.execute("toggle_play_pause")
    print("Pause Result:", res)
    
    print("\n--- Paused for 3 seconds ---")
    time.sleep(3)
    
    print("\n--- 3. Testing Play/Pause (Resume) ---")
    res = await plugin.execute("toggle_play_pause")
    print("Resume Result:", res)
    
    print("\n--- Letting it play for 3 seconds ---")
    time.sleep(3)
    
    print("\n--- 4. Testing Next Video ---")
    res = await plugin.execute("next_video")
    print("Next Result:", res)
    print("State URL after next:", state["active_video_url"])
    
    print("\n--- Letting it play for 5 seconds ---")
    time.sleep(5)
    
    print("\n--- 5. Testing Previous Video (Native) ---")
    res = await plugin.execute("previous_video")
    print("Previous Result:", res)
    print("State URL after prev:", state["active_video_url"])
    
    print("\n--- Letting it play for 5 seconds ---")
    time.sleep(5)
    
    print("\n--- 6. Testing Previous Video (Fallback to History) ---")
    res = await plugin.execute("previous_video")
    print("Previous (Fallback) Result:", res)
    print("State URL after fallback prev:", state["active_video_url"])

    print("\n--- 7. Testing Volume Up ---")
    res = await plugin.execute("volume_up")
    print("Volume Up Result:", res)

    print("\n--- 8. Testing Volume Down ---")
    res = await plugin.execute("volume_down")
    print("Volume Down Result:", res)
    
    print("\n--- Done ---")
    await plugin.execute("close_app")

if __name__ == "__main__":
    asyncio.run(run_tests())
