#!/usr/bin/env bash
# Install Dico.app into /Applications (builds it first if needed).
set -euo pipefail
cd "$(dirname "$0")"

[ -d build/Dico.app ] || ./build.sh

pkill -f "Dico.app/Contents/MacOS/Dico" 2>/dev/null || true
rm -rf /Applications/Dico.app
cp -R build/Dico.app /Applications/Dico.app
echo "✓ /Applications/Dico.app"
echo "  open /Applications/Dico.app  — then ⌥D"
echo "  (⚙︎ Settings ▸ General ▸ Launch at login, once it is in /Applications.)"
