#!/bin/bash
set -e

USER_ID=$(id -u)
SERVICE="gui/${USER_ID}/com.local.autocorrect"
PLIST_FILE="$HOME/Library/LaunchAgents/com.local.autocorrect.plist"
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "Restarting Autocorrect..."

# Check if the service is registered in launchd
if launchctl print "$SERVICE" >/dev/null 2>&1; then
    # Kickstart with -k (kills running instance and restarts it cleanly)
    launchctl kickstart -k "$SERVICE"
else
    echo "LaunchAgent service was not active. Bootstrapping..."
    if [ ! -f "$PLIST_FILE" ] && [ -f "$REPO_DIR/com.local.autocorrect.plist" ]; then
        mkdir -p "$HOME/Library/LaunchAgents"
        cp "$REPO_DIR/com.local.autocorrect.plist" "$PLIST_FILE"
    fi
    pkill -f autocorrect.py 2>/dev/null || true
    launchctl bootstrap "gui/${USER_ID}" "$PLIST_FILE" 2>/dev/null || launchctl load "$PLIST_FILE" 2>/dev/null
fi

# Wait briefly for process to initialize
sleep 1

# Check if running
PID=$(pgrep -f "autocorrect.py" | head -n 1 || true)

if [ -n "$PID" ]; then
    echo "✓ Autocorrect restarted successfully (PID: $PID)"
    if [ -f "$HOME/autocorrect.log" ]; then
        echo "Latest log output:"
        tail -n 3 "$HOME/autocorrect.log"
    fi
else
    echo "⚠ Warning: Autocorrect process did not appear immediately. Check ~/autocorrect.log for details."
    exit 1
fi
