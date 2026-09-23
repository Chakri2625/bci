import asyncio
import logging
import sys
import os

_ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
if _ROOT_DIR not in sys.path:
    sys.path.insert(0, _ROOT_DIR)

from plugins.desktop.plugin import DesktopPlugin

logging.basicConfig(level=logging.INFO)

async def run_tests():
    plugin = DesktopPlugin()
    
    print("\n--- TEST 3: PING / PONG ---")
    if not plugin.uart_transport.running:
        plugin.uart_transport.start()
    
    ping_result = plugin.uart_transport.ping()
    print(f"PING result: {ping_result}")
    
    print("\n--- TEST 4: OPEN_NOTEPAD ---")
    res = await plugin.execute("OPEN_NOTEPAD", {"app": "notepad"})
    print(f"Result: {res}")
    
    print("\n--- TEST 5: OPEN_CHROME ---")
    res = await plugin.execute("OPEN_CHROME", {"app": "chrome"})
    print(f"Result: {res}")
    
    print("\n--- TEST 6: OPEN_YOUTUBE ---")
    res = await plugin.execute("OPEN_YOUTUBE", {"app": "youtube"})
    print(f"Result: {res}")
    
    print("\n--- TEST 7: OPEN_GMAIL ---")
    res = await plugin.execute("OPEN_GMAIL", {"app": "email"})
    print(f"Result: {res}")

if __name__ == '__main__':
    asyncio.run(run_tests())
