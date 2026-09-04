#!/usr/bin/env bash
# Compile Dico.app — pas de projet Xcode, juste swiftc.
set -euo pipefail
cd "$(dirname "$0")"

APP="build/Dico.app"
MACOS="$APP/Contents/MacOS"
RES="$APP/Contents/Resources"

rm -rf "$APP"
mkdir -p "$MACOS" "$RES"

echo "→ compilation…"
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

# Signature ad-hoc : le raccourci global et l'accès trousseau aiment une identité stable.
codesign --force --sign - "$APP" 2>/dev/null || true

echo "✓ $APP"
echo
echo "  autotest :  ./build/Dico.app/Contents/MacOS/Dico --selftest"
echo "  lancer   :  open build/Dico.app     (puis ⌥D n'importe où)"
echo "  installer:  ./install.sh"
