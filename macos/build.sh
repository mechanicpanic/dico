#!/usr/bin/env bash
# Build Dico.app — no Xcode project, just swiftc.
set -euo pipefail
cd "$(dirname "$0")"

# One version for the whole project, declared in dico.py.
VERSION="$(sed -n 's/^__version__ = "\(.*\)"/\1/p' ../dico.py)"
[ -n "$VERSION" ] || VERSION="0.0.0"

APP="build/Dico.app"
MACOS="$APP/Contents/MacOS"
RES="$APP/Contents/Resources"

rm -rf "$APP"
mkdir -p "$MACOS" "$RES"

echo "→ icon…"
# Regenerated only when the recipe changes: iconutil takes a couple of seconds.
if [ ! -f build/Dico.icns ] || [ make_icon.swift -nt build/Dico.icns ]; then
  xcrun swift make_icon.swift >/dev/null
fi

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
  <key>CFBundleShortVersionString</key><string>__VERSION__</string>
  <key>CFBundleVersion</key>           <string>__VERSION__</string>
  <key>LSMinimumSystemVersion</key>    <string>14.0</string>
  <key>LSUIElement</key>               <true/>
  <key>NSHighResolutionCapable</key>   <true/>
  <key>CFBundleIconFile</key>          <string>Dico</string>
  <!-- Right-click ▸ Services ▸ "Look up in Dico" — no permission needed. -->
  <key>NSServices</key>
  <array>
    <dict>
      <key>NSMenuItem</key>   <dict><key>default</key><string>Look up in Dico</string></dict>
      <key>NSMessage</key>    <string>lookUp</string>
      <key>NSPortName</key>   <string>Dico</string>
      <key>NSSendTypes</key>  <array><string>NSStringPboardType</string></array>
    </dict>
  </array>
</dict>
</plist>
PLIST
sed -i '' "s/__VERSION__/$VERSION/g" "$APP/Contents/Info.plist"

cp build/Dico.icns "$RES/Dico.icns"

# Ad-hoc signature: the global hotkey and keychain access like a stable identity.
codesign --force --sign - "$APP" 2>/dev/null || true

echo "✓ $APP  (version $VERSION)"
echo
echo "  self-test:  ./build/Dico.app/Contents/MacOS/Dico --selftest"
echo "  run      :  open build/Dico.app     (then ⌥D anywhere)"
echo "  install  :  ./install.sh"
