#!/usr/bin/env bash
# Build Dico.app — no Xcode project, just swiftc.
set -euo pipefail
cd "$(dirname "$0")"

APP="build/Dico.app"
MACOS="$APP/Contents/MacOS"
RES="$APP/Contents/Resources"

rm -rf "$APP"
mkdir -p "$MACOS" "$RES"

echo "→ compiling…"
xcrun swiftc -O -parse-as-library \
  -target arm64-apple-macos14 \
  -framework SwiftUI -framework AppKit -framework Carbon \
  Sources/*.swift \
  -o "$MACOS/Dico"

cat > "$APP/Contents/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key>              <string>Dico</string>
  <key>CFBundleDisplayName</key>       <string>Dico</string>
  <key>CFBundleExecutable</key>        <string>Dico</string>
  <key>CFBundleIdentifier</key>        <string>fr.dico.popup</string>
  <key>CFBundlePackageType</key>       <string>APPL</string>
  <key>CFBundleShortVersionString</key><string>1.0</string>
  <key>CFBundleVersion</key>           <string>1</string>
  <key>LSMinimumSystemVersion</key>    <string>14.0</string>
  <key>LSUIElement</key>               <true/>
  <key>NSHighResolutionCapable</key>   <true/>
</dict>
</plist>
PLIST

# Ad-hoc signature: the global hotkey and keychain access like a stable identity.
codesign --force --sign - "$APP" 2>/dev/null || true

echo "✓ $APP"
echo
echo "  self-test:  ./build/Dico.app/Contents/MacOS/Dico --selftest"
echo "  run      :  open build/Dico.app     (then ⌥D anywhere)"
echo "  install  :  ./install.sh"
