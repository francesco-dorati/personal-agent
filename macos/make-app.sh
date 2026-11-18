#!/bin/zsh
# Builds "Personal Agent.app" in ~/Applications so you can open the TUI like
# any other program: from the Dock, Spotlight, Raycast or Launchpad.
#
#   zsh macos/make-app.sh            # run once from the repo folder
#
# Re-run it after moving the repo or reinstalling uv. Clicking the app opens
# a window of your terminal (Ghostty, then iTerm2, then Terminal) running the
# TUI; quitting the TUI closes that window.
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
UV="$(command -v uv || true)"
if [[ -z "$UV" ]]; then
  echo "uv not found. Install it first: https://docs.astral.sh/uv/" >&2
  exit 1
fi

APP="$HOME/Applications/Personal Agent.app"
mkdir -p "$HOME/Applications"
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
cp "$REPO/macos/PersonalAgent.icns" "$APP/Contents/Resources/PersonalAgent.icns"

# What runs inside the terminal window
cat > "$APP/Contents/Resources/run.sh" <<EOF
#!/bin/zsh
printf '\e]0;Personal Agent\a'
cd "$REPO" || exit 1
"$UV" run --quiet agent-tui
EOF

# What the Dock icon launches: open the TUI in the best terminal available
cat > "$APP/Contents/MacOS/PersonalAgent" <<'EOF'
#!/bin/zsh
RUN="$(cd "$(dirname "$0")/../Resources" && pwd)/run.sh"
if [[ -d /Applications/Ghostty.app ]]; then
  open -na Ghostty --args --title="Personal Agent" --window-width=150 --window-height=46 \
    --quit-after-last-window-closed=true -e "$RUN"
elif [[ -d /Applications/iTerm.app ]]; then
  osascript -e "tell application \"iTerm\" to create window with default profile command \"$RUN\""
else
  osascript -e "tell application \"Terminal\" to do script \"exec '$RUN'\"" \
            -e 'tell application "Terminal" to activate'
fi
EOF

cat > "$APP/Contents/Info.plist" <<'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>Personal Agent</string>
  <key>CFBundleDisplayName</key><string>Personal Agent</string>
  <key>CFBundleIdentifier</key><string>com.personal-agent.tui</string>
  <key>CFBundleVersion</key><string>1</string>
  <key>CFBundleShortVersionString</key><string>0.1</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleExecutable</key><string>PersonalAgent</string>
  <key>CFBundleIconFile</key><string>PersonalAgent</string>
  <key>LSMinimumSystemVersion</key><string>11.0</string>
</dict>
</plist>
EOF

chmod +x "$APP/Contents/MacOS/PersonalAgent" "$APP/Contents/Resources/run.sh"
touch "$APP"   # make Finder pick up the icon

# Prepare the Python environment now, so the first click opens instantly
(cd "$REPO" && "$UV" sync --quiet)

echo "Built: $APP"
echo "Drag it from the Finder window that just opened into your Dock to pin it."
open -R "$APP"
