#!/bin/zsh
# Builds "Personal Agent.app" in ~/Applications: a real Mac app with its own
# window, menu and Dock icon, showing the Personal Agent TUI. The app ships
# its own fonts, so the icons always render.
#
#   zsh macos/make-app.sh            # run once from the repo folder
#   zsh macos/make-app.sh buddy      # pick a logo: buddy, sprout, star, hearth, owl
#
# Needs uv and Apple's command line tools (swiftc). Re-run it after moving
# this folder or after pulling changes to macos/app/.
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
LOGO="${1:-}"
ICON="$REPO/macos/PersonalAgent.icns"
if [[ -n "$LOGO" ]]; then
  ICON="$REPO/macos/logos/logo-$LOGO.icns"
  [[ -f "$ICON" ]] || { echo "No logo called '$LOGO'. Pick one of: buddy sprout star hearth owl" >&2; exit 1; }
fi
UV="$(command -v uv || true)"
[[ -n "$UV" ]] || { echo "uv not found: https://docs.astral.sh/uv/" >&2; exit 1; }
if ! command -v swiftc >/dev/null; then
  echo "Apple's command line tools are missing. Run: xcode-select --install" >&2
  exit 1
fi

echo "• Preparing the Python environment"
(cd "$REPO" && "$UV" sync --quiet)

APP="$HOME/Applications/Personal Agent.app"
echo "• Building $APP"
osascript -e 'tell application "Personal Agent" to quit' >/dev/null 2>&1 || true
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
cp "$ICON" "$APP/Contents/Resources/PersonalAgent.icns"

# What the app runs: the local server for the TUI page
cat > "$APP/Contents/Resources/server.sh" <<SH
#!/bin/zsh
cd "$REPO" || exit 1
exec "$REPO/.venv/bin/python" -m personal_agent_tui.serve
SH
chmod +x "$APP/Contents/Resources/server.sh"

cat > "$APP/Contents/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>Personal Agent</string>
  <key>CFBundleDisplayName</key><string>Personal Agent</string>
  <key>CFBundleIdentifier</key><string>com.personal-agent.app</string>
  <key>CFBundleVersion</key><string>2</string>
  <key>CFBundleShortVersionString</key><string>0.2</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleExecutable</key><string>PersonalAgent</string>
  <key>CFBundleIconFile</key><string>PersonalAgent</string>
  <key>LSMinimumSystemVersion</key><string>12.0</string>
  <key>NSHighResolutionCapable</key><true/>
  <key>NSAppTransportSecurity</key>
  <dict><key>NSAllowsLocalNetworking</key><true/></dict>
</dict>
</plist>
PLIST

echo "• Compiling the window (swiftc)"
swiftc -O "$REPO/macos/app/main.swift" -o "$APP/Contents/MacOS/PersonalAgent"
codesign --force --deep --sign - "$APP" >/dev/null 2>&1 || true
touch "$APP"

echo "Done. Drag Personal Agent from the Finder window into your Dock to pin it."
open -R "$APP"
