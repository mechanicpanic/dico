#!/usr/bin/env bash
# Build Dico.dmg — the thing you hand to a person, not to a developer.
#
# Drag-to-Applications, and a visible note about the first launch: the build is
# signed ad-hoc (notarising needs a paid Apple account), so macOS refuses a
# double-click the first time and the way through is right-click ▸ Open.
set -euo pipefail
cd "$(dirname "$0")"

VERSION="$(sed -n 's/^__version__ = "\(.*\)"/\1/p' ../dico.py)"
[ -n "$VERSION" ] || VERSION="0.0.0"
DMG="build/Dico-$VERSION.dmg"
STAGE="build/dmg"

[ -d build/Dico.app ] || ./build.sh

rm -rf "$STAGE" "$DMG"
mkdir -p "$STAGE"
cp -R build/Dico.app "$STAGE/Dico.app"
ln -s /Applications "$STAGE/Applications"

cat > "$STAGE/READ ME FIRST.txt" <<'TXT'
Dico — a French dictionary that opens anywhere with ⌥D
======================================================

STEP 1.  Drag Dico onto the Applications folder, here in this window.

STEP 2.  Open it ONCE the long way. macOS blocks apps that are not signed by
         a paying Apple developer, and this one is free, so the first launch
         takes three extra clicks:

           a. Open your Applications folder and double-click Dico.
              macOS says it "cannot be opened". Click Done.
           b. Open System Settings ▸ Privacy & Security, scroll down to
              the Security section. It now says Dico "was blocked".
              Click "Open Anyway", and confirm.
           c. Dico starts. You never have to do this again.

         (On macOS 14 and older there is a shortcut: right-click Dico and
         choose Open. Apple removed it in macOS 15.)

STEP 3.  There is no step 3. Nothing to install, nothing to configure: the
         dictionary, the conjugations and the grammar checker are inside the
         app and work with no internet.

Using it
--------
   Press ⌥D (option-D) anywhere — the panel opens on top of whatever you are
   doing. Type an English or Russian word to get its French card, a French
   word to get its own, or a whole French sentence to have it corrected.
   Press ⌘/ for every shortcut, Esc to close.

   You can also select a word in any app and press ⌥D to look it up straight
   away (macOS asks for Accessibility permission the first time), or
   right-click a word and choose Services ▸ Look up in Dico.

Dico lives in the menu bar at the top of the screen — the « é » — not in the
Dock. Click it for Settings, or to quit.
TXT


hdiutil create -volname "Dico $VERSION" -srcfolder "$STAGE" \
  -ov -format UDZO -quiet "$DMG"
rm -rf "$STAGE"
echo "✓ $DMG  ($(du -h "$DMG" | cut -f1))"
