#!/bin/bash

# LEGACY wrapper — prefer: python start_chrome.py (cross-platform: Windows/macOS/Linux)
# This script is kept for backward compatibility on macOS/Linux.
# New code (browser_manager.py) now calls start_chrome.py first.
# You can also run: python3 "$(dirname "$0")/start_chrome.py" "$@"

# Helper script to start Chrome with remote debugging enabled
# This enables DOM-based automation which bypasses OS accessibility restrictions

echo "Starting Chrome with remote debugging on port 9222..."
echo "NOTE: This is legacy — prefer: python3 \"\$(dirname \"\$0\")/start_chrome.py\" (Windows/macOS/Linux)"

check_port() {
    python3 -c "import socket,sys; s=socket.socket(); s.settimeout(0.5); sys.exit(0 if s.connect_ex(('127.0.0.1',9222))==0 else 1)" 2>/dev/null
    if [ $? -eq 0 ]; then return 0; fi
    if command -v lsof >/dev/null 2>&1; then
        lsof -Pi :9222 -sTCP:LISTEN -t >/dev/null 2>&1 && return 0
    fi
    if command -v ss >/dev/null 2>&1; then
        ss -ltn 2>/dev/null | grep -q ":9222" && return 0
    fi
    if command -v netstat >/dev/null 2>&1; then
        netstat -an 2>/dev/null | grep -q "9222.*LISTEN" && return 0
    fi
    return 1
}

if check_port; then
    echo "Chrome is already running with remote debugging on port 9222"
    echo "You can connect to it now."
    exit 0
fi

# Use a dedicated debug profile. Copy the real profile only ONCE (first run)
# so repeated launches are fast and NEVER disturb the user's own Chrome.
CHROME_PROFILE_DIR="$HOME/Library/Application Support/Google/Chrome"
CHROME_DEBUG_DIR="$HOME/chrome-debug-profile"
PROFILE_READY_FLAG="$CHROME_DEBUG_DIR/.debug-profile-ready"

if [ -f "$PROFILE_READY_FLAG" ]; then
    echo "Using existing debug profile: $CHROME_DEBUG_DIR"
else
    echo "Preparing Chrome debug profile (first-time setup)..."
    mkdir -p "$CHROME_DEBUG_DIR"
    if [ -d "$CHROME_PROFILE_DIR" ]; then
        # Copy the profile once, skipping bulky caches and stale lock files.
        if command -v rsync >/dev/null 2>&1; then
            rsync -a --delete \
                --exclude 'Cache*' \
                --exclude 'Code Cache' \
                --exclude 'GPUCache' \
                --exclude 'SingletonLock' \
                --exclude 'SingletonSocket' \
                --exclude 'SingletonCookie' \
                "$CHROME_PROFILE_DIR/" "$CHROME_DEBUG_DIR/" 2>/dev/null
            echo "✅ Chrome profile copied to debug profile (via rsync)"
        else
            echo "rsync not found — copying profile via cp (slower, no delete)..."
            mkdir -p "$CHROME_DEBUG_DIR"
            # cp -a fallback: copy and then remove cache dirs
            cp -a "$CHROME_PROFILE_DIR/." "$CHROME_DEBUG_DIR/" 2>/dev/null || cp -R "$CHROME_PROFILE_DIR/." "$CHROME_DEBUG_DIR/" 2>/dev/null
            rm -rf "$CHROME_DEBUG_DIR/Cache"* "$CHROME_DEBUG_DIR/Code Cache" "$CHROME_DEBUG_DIR/GPUCache" "$CHROME_DEBUG_DIR/SingletonLock" "$CHROME_DEBUG_DIR/SingletonSocket" "$CHROME_DEBUG_DIR/SingletonCookie" 2>/dev/null
            echo "✅ Chrome profile copied to debug profile (via cp)"
        fi
    else
        echo "Using empty debug profile"
    fi
    touch "$PROFILE_READY_FLAG"
fi

# Start Chrome with remote debugging using your copied profile
if [[ "$OSTYPE" == "darwin"* ]]; then
    # macOS - using your copied Chrome profile for remote debugging
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
        --remote-debugging-port=9222 \
        --user-data-dir="$CHROME_DEBUG_DIR" \
        > /dev/null 2>&1 &
elif [[ "$OSTYPE" == "linux-gnu"* ]]; then
    # Linux - using your copied Chrome profile for remote debugging
    google-chrome \
        --remote-debugging-port=9222 \
        --user-data-dir="$CHROME_DEBUG_DIR" \
        > /dev/null 2>&1 &
else
    echo "Unsupported OS. Please start Chrome manually with:"
    echo "chrome --remote-debugging-port=9222 --user-data-dir=/tmp/chrome-debug"
    exit 1
fi

# Wait for Chrome to start and check if port is listening
echo "Waiting for Chrome to start with remote debugging..."
for i in {1..20}; do
    if check_port; then
        echo "✅ Chrome is ready with remote debugging on port 9222"
        echo "Navigate to JioSaavn in this Chrome instance for full automation support."
        echo ""
        echo "IMPORTANT: This system is designed specifically for JioSaavn web player control."
        echo "Chrome remote debugging is required on macOS due to security restrictions."
        echo ""
        echo "✅ Your Chrome profile with existing account has been copied."
        echo "You should be already logged in to JioSaavn!"
        exit 0
    fi
    sleep 1
done

echo "❌ Chrome failed to start with remote debugging"
echo ""
echo "Troubleshooting steps:"
echo "1. Make sure all Chrome windows are closed"
echo "2. Try running the script again"
echo "3. Or start Chrome manually with:"
echo "/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome --remote-debugging-port=9222 --user-data-dir=$HOME/chrome-debug-profile"
