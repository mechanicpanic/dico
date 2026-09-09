#!/usr/bin/env bash
# Cut a release: check, build, package, tag, publish.
#
#   tools/release.sh            # dry run: everything except the tag and upload
#   tools/release.sh --publish  # …and push the tag + create the GitHub release
#
# The version comes from dico.py (__version__) and from nowhere else.
set -euo pipefail
cd "$(dirname "$0")/.."

PUBLISH=""
[ "${1:-}" = "--publish" ] && PUBLISH=1

VERSION="$(sed -n 's/^__version__ = "\(.*\)"/\1/p' dico.py)"
[ -n "$VERSION" ] || { echo "✗ no __version__ in dico.py"; exit 1; }
TAG="v$VERSION"
echo "==> dico $TAG"

# 1. The tree must be clean, and the tag must be new.
[ -z "$(git status --porcelain)" ] || { echo "✗ working tree is dirty"; exit 1; }
if git rev-parse "$TAG" >/dev/null 2>&1; then
  echo "✗ $TAG already exists — bump __version__ in dico.py"; exit 1
fi
grep -q "^## $VERSION " CHANGELOG.md || {
  echo "✗ CHANGELOG.md has no section for $VERSION"; exit 1; }

# 2. The CLI has to work from a clean checkout of what we are shipping.
echo "==> CLI"
python3 dico.py --version
python3 -c "import ast,sys; ast.parse(open('dico.py').read())"

# 3. The app: build and run its self-test (it exercises the whole CLI→UI chain).
echo "==> app + self-test"
( cd macos && ./build.sh >/dev/null && ./build/Dico.app/Contents/MacOS/Dico --selftest )

# 4. Package. The DMG is what a person gets: drag-to-Applications and a
#    READ ME that explains the one-off Gatekeeper dance. The zip is for
#    anyone who would rather not mount a disk image.
mkdir -p dist
ZIP="dist/Dico-$VERSION.zip"
rm -f "$ZIP"
ditto -c -k --keepParent macos/build/Dico.app "$ZIP"
echo "✓ $ZIP  ($(du -h "$ZIP" | cut -f1))"

( cd macos && ./package.sh )
DMG="dist/Dico-$VERSION.dmg"
mv "macos/build/Dico-$VERSION.dmg" "$DMG"
echo "✓ $DMG  ($(du -h "$DMG" | cut -f1))"

if [ -z "$PUBLISH" ]; then
  echo
  echo "Dry run finished. Publish with:  tools/release.sh --publish"
  exit 0
fi

# 5. Tag and publish.
echo "==> tagging $TAG"
git tag -a "$TAG" -m "dico $TAG"
git push origin "$TAG"

NOTES="$(awk -v v="## $VERSION " 'index($0,v)==1{f=1;next} f&&/^## /{exit} f' CHANGELOG.md)"
gh release create "$TAG" "$DMG" "$ZIP" \
  --title "dico $VERSION" \
  --notes "$NOTES

## Install

**CLI**
\`\`\`sh
uv tool install git+https://github.com/mechanicpanic/dico@$TAG
dico --setup
\`\`\`

**macOS app — nothing to install.** Download \`Dico-$VERSION.dmg\`, drag Dico to
Applications, press ⌥D. The dictionary, conjugations and grammar checker are
inside the app; no Python, no uv, no setup, works offline.

The first launch takes three extra clicks: the app is signed ad-hoc, so macOS
blocks the first double-click. Open **System Settings ▸ Privacy & Security**,
scroll to *Security*, and click **Open Anyway**. Once. (macOS 14 and older:
right-click ▸ Open.)"
echo "✓ published: $(gh release view "$TAG" --json url -q .url)"
