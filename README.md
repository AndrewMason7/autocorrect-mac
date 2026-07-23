# macOS Autocorrect Daemon

A fast, lightweight, and completely local autocorrect daemon for macOS. It monitors your keystrokes globally, detects misspelled words in real-time, and replaces them instantly with their correct spelling.

## Features

- **Context-aware replacements:** Reads the focused field and caret through the macOS Accessibility API, then verifies the exact source text before changing it.
- **No trigger/deletion race:** AX replacements leave the original trigger untouched; the fallback suppresses and replays it exactly once.
- **Newline-aware capitalization:** Distinguishes hard `LF`/`CRLF` line breaks from visual line wrapping.
- **Safe fallback:** Uses synchronous keystrokes when a field does not expose Accessibility text. If context is stale or unsafe, the correction is skipped instead of guessing.
- **Selection and password safety:** Never edits secure text fields or an active text selection.
- **Modifier and shortcut protection:** Queries macOS modifier flags on each physical keypress and clears pending context whenever `Command`, `Option`, or `Control` is active.
- **Production-Grade Log Rotation:** Uses a built-in `RotatingFileHandler` capped at 5MB with a 3-file history rotation, ensuring your system disk space is never filled by logs.
- **Bypass App Nap & Throttling:** Asserts a latency-critical activity reservation via Cocoa `NSProcessInfo` options (`NSActivityUserInitiated | NSActivityLatencyCritical`) to prevent the macOS kernel from pausing or throttling the daemon's event loop.
- **Singleton Process Lock:** Uses Unix file locking (`fcntl` flock on `~/.autocorrect.lock`) to guarantee that only one instance of the daemon executes at any time. This prevents event-loop conflict cascades and key-spamming if the app is launched multiple times (e.g., by both launchd and macOS Login Items).
- **macOS TCC Compatibility:** Can be packaged as a background `.app` bundle helper to satisfy macOS Privacy & Security (Accessibility) requirements permanently.

---

## Installation

### 1. Clone the repository
```bash
git clone https://github.com/AndrewMason7/autocorrect-mac.git
cd autocorrect-mac
```

### 2. Install dependencies
Install the keyboard, Cocoa, and Accessibility bindings:
```bash
pip3 install -r requirements.txt
```

### 3. Create the Autocorrect App Bundle
macOS requires Accessibility permissions to be granted to an Application Bundle (`.app`) rather than a loose Python script so it can be trusted by the OS.

Run the following commands to create the bundle structure in your Applications folder:
```bash
# Create the directory structure
mkdir -p /Applications/Autocorrect.app/Contents/MacOS

# Create the wrapper script
cat << 'EOF' > /Applications/Autocorrect.app/Contents/MacOS/Autocorrect
#!/bin/bash
exec /usr/bin/env python3 "$HOME/autocorrect-mac/autocorrect.py"
EOF

# Make it executable
chmod +x /Applications/Autocorrect.app/Contents/MacOS/Autocorrect

# Create the Info.plist configuration
cat << 'EOF' > /Applications/Autocorrect.app/Contents/Info.plist
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleExecutable</key>
    <string>Autocorrect</string>
    <key>CFBundleIdentifier</key>
    <string>com.local.autocorrect.app</string>
    <key>CFBundleName</key>
    <string>Autocorrect</string>
    <key>CFBundlePackageType</key>
    <string>APPL</string>
    <key>LSUIElement</key>
    <true/>
</dict>
</plist>
EOF
```

---

## Grant Permissions

1. Open **System Settings** → **Privacy & Security** → **Accessibility**.
2. Click the **`+` (plus)** button.
3. Select `/Applications/Autocorrect.app` to add it to the list.
4. Toggle the switch to **ON**.

---

## Customizing Rules

You can easily customize, add, or remove autocorrect mappings directly at the top of the `autocorrect.py` script:

1. **Contractions & Grammar (`grammar` dictionary):** Handles words like contractions (e.g. `dont` -> `don't`). The engine preserves your typing case dynamically (e.g., typing `Dont` corrects to `Don't`, and `DONT` corrects to `DON'T`).
2. **Proper Nouns & Shortcuts (`shortcuts` dictionary):** Handles word expansions and capitalizations (e.g., `apple watch` -> `Apple Watch`, `gcal` -> `Google Calendar`).
3. **Multi-Word Phrases:** You can define multi-word autocorrect expansions (e.g., `'united states': 'United States'`). The engine automatically scans up to the last 3 typed words to perform multi-word replacements.

> [!IMPORTANT]
> - Ensure all lookup keys in both dictionaries are typed in **lowercase**.
> - After modifying rules in `autocorrect.py`, restart the daemon to apply changes:
>   ```bash
>   autocorrect-off && autocorrect-on
>   ```

---

## Usage

### Context behavior

For each possible correction, the daemon first asks the focused text field for
its text and insertion-point range. It applies the change only when the exact
typed source is immediately before a collapsed caret. Secure fields, active
selections, and changed/moved carets are left untouched.

Some apps and custom editors do not expose editable text through Accessibility.
In those fields, the daemon falls back to its local keystroke history. The
fallback deletes only the source text; the original trigger is suppressed only
after the replacement has been posted. Navigation, app switching shortcuts,
and stale context clear phrase history.

### Auto-Start at Login (Launchd Daemon)
The daemon is configured to start automatically at login and keep itself alive via a launch agent plist.

To register the launch agent:
```bash
# Copy the plist file into your LaunchAgents directory
cp com.local.autocorrect.plist ~/Library/LaunchAgents/
# Load and start the daemon
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.local.autocorrect.plist
```

---

## Control Commands & Aliases

We provide a control script `autocorrect-control.sh` to safely toggle the engine.

### 1. Copy the control script
```bash
# Copy the script to your home directory and make it executable
cp autocorrect-control.sh ~/
chmod +x ~/autocorrect-control.sh
```

### 2. Configure Shell Aliases
Add the aliases to your `~/.zshrc` (or preferred shell profile) and reload it:
```bash
echo 'alias autocorrect-off="~/autocorrect-control.sh off"' >> ~/.zshrc
echo 'alias autocorrect-on="~/autocorrect-control.sh on"' >> ~/.zshrc
source ~/.zshrc
```

### Usage

#### Stop and Disable (Safe Mode/Recovery Safe)
To completely stop the daemon, unload it from launchd, and disable auto-start:
```bash
autocorrect-off
```
*(Under the hood, this runs `~/autocorrect-control.sh off`, which renames the plist and `.app` bundle, guaranteeing it cannot start at boot even in Safe Mode).*

### Start and Enable
To enable, restore the files, and start the daemon:
```bash
autocorrect-on
```
*(Runs `~/autocorrect-control.sh on`).*

---

## Logging & Monitoring

### Monitor Logs
Monitor corrections and activity in real-time:
```bash
tail -f ~/autocorrect.log
```

---

## Tests

Run the context, newline, range, and replacement regressions with:

```bash
python3 -m unittest discover -s tests -v
```

