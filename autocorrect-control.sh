#!/bin/bash

# Determine directory paths relative to this script for Safe Mode / Recovery Mode compatibility
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VOLUME_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

PLIST_PATH="$SCRIPT_DIR/Library/LaunchAgents/com.local.autocorrect.plist"
PLIST_DISABLED="$PLIST_PATH.disabled"
APP_PATH="$VOLUME_ROOT/Applications/Autocorrect.app"
APP_DISABLED="$APP_PATH.disabled"

ACTION="$1"

if [ "$ACTION" = "off" ]; then
    echo "Disabling Autocorrect daemon..."
    
    # 1. Try unloading LaunchAgent from launchd
    if command -v launchctl >/dev/null 2>&1; then
        USER_ID=$(id -u)
        launchctl bootout gui/"$USER_ID" "$PLIST_PATH" 2>/dev/null
        launchctl unload "$PLIST_PATH" 2>/dev/null
        launchctl bootout gui/"$USER_ID" "$PLIST_DISABLED" 2>/dev/null
        launchctl unload "$PLIST_DISABLED" 2>/dev/null
    fi
    
    # 2. Kill all active autocorrect python processes
    pkill -f autocorrect.py 2>/dev/null
    pkill -f v26_exclusive_mac.py 2>/dev/null
    
    # 3. Disable LaunchAgent file
    if [ -f "$PLIST_PATH" ]; then
        mv "$PLIST_PATH" "$PLIST_DISABLED"
        echo "✓ Disabled LaunchAgent file."
    fi
    
    # 4. Disable App wrapper bundle (prevents any login-item launch)
    if [ -d "$APP_PATH" ]; then
        mv "$APP_PATH" "$APP_DISABLED"
        echo "✓ Disabled Autocorrect.app bundle."
    fi
    
    echo "Autocorrect has been completely deactivated and will not launch at login."

elif [ "$ACTION" = "on" ]; then
    echo "Enabling Autocorrect daemon..."
    
    # 1. Restore App wrapper bundle
    if [ -d "$APP_DISABLED" ]; then
        mv "$APP_DISABLED" "$APP_PATH"
        echo "✓ Restored Autocorrect.app bundle."
    fi
    
    # 2. Restore LaunchAgent file
    if [ -f "$PLIST_DISABLED" ]; then
        mv "$PLIST_DISABLED" "$PLIST_PATH"
        echo "✓ Restored LaunchAgent file."
    fi
    
    # 3. Load LaunchAgent into launchd
    if command -v launchctl >/dev/null 2>&1; then
        USER_ID=$(id -u)
        launchctl bootstrap gui/"$USER_ID" "$PLIST_PATH" 2>/dev/null
        launchctl load "$PLIST_PATH" 2>/dev/null
    fi
    
    echo "Autocorrect has been activated and is running."

else
    echo "Usage: $0 {on|off}"
    exit 1
fi
