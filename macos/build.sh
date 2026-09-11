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

# Self-contained: the CLI and the offline databases ride inside the app, so it
# works by being dragged to /Applications — no uv, no Python to install, no
# Terminal, no setup step. (~20 MB of data; Multitran stays bring-your-own.)
cp ../dico.py "$RES/dico.py"
# The command line, from the same bundle: Homebrew links it as `dico`.
mkdir -p "$RES/bin"
cat > "$RES/bin/dico" <<'SH'
#!/bin/sh
# dico — the CLI inside Dico.app. The data the app unpacks (~/.dico/data) is shared.
self="$0"
while [ -L "$self" ]; do                      # Homebrew links it from /opt/homebrew/bin
  target="$(readlink "$self")"
  case "$target" in /*) self="$target" ;; *) self="$(dirname "$self")/$target" ;; esac
done
here="$(cd "$(dirname "$self")/.." && pwd)"
export DICO_DATA="${DICO_DATA:-$HOME/.dico/data}"
export DICO_HOME="${DICO_HOME:-$HOME/.dico}"
if [ ! -f "$DICO_DATA/lexique.db" ] && [ -d "$here/data" ]; then
  mkdir -p "$DICO_DATA" && cp -R "$here/data/." "$DICO_DATA/"      # first run: seed, like the app does
fi
exec /usr/bin/python3 "$here/dico.py" "$@"
SH
chmod +x "$RES/bin/dico"
DATA_SRC="${DICO_DATA:-../data}"
if [ "${SKIP_DATA:-}" != "1" ] && [ -f "$DATA_SRC/lexique.db" ]; then
  mkdir -p "$RES/data"
  for f in lexique.db conjugations.db; do
    [ -f "$DATA_SRC/$f" ] && cp "$DATA_SRC/$f" "$RES/data/$f"
  done
  [ -d "$DATA_SRC/grammalecte" ] && cp -R "$DATA_SRC/grammalecte" "$RES/data/grammalecte"
  echo "  bundled data: $(du -sh "$RES/data" | cut -f1)"
else
  echo "  (no data bundled — build it with ./setup.sh in the repo root)"
fi

# Ad-hoc signature: the global hotkey and keychain access like a stable identity.
codesign --force --sign - "$APP" 2>/dev/null || true

echo "✓ $APP  (version $VERSION)"
echo
echo "  self-test:  ./build/Dico.app/Contents/MacOS/Dico --selftest"
echo "  run      :  open build/Dico.app     (then ⌥D anywhere)"
echo "  install  :  ./install.sh"
