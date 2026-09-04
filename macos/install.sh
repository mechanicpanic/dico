#!/usr/bin/env bash
# Installe Dico.app dans /Applications (construit d'abord si besoin).
set -euo pipefail
cd "$(dirname "$0")"

[ -d build/Dico.app ] || ./build.sh

pkill -f "Dico.app/Contents/MacOS/Dico" 2>/dev/null || true
rm -rf /Applications/Dico.app
cp -R build/Dico.app /Applications/Dico.app
echo "✓ /Applications/Dico.app"
echo "  open /Applications/Dico.app  — puis ⌥D"
echo "  (Réglages → Général → Ouverture pour le lancer à la connexion.)"
