#!/usr/bin/env bash
# Reconstruit les bases de données locales de dico (non versionnées : ~600 Mo).
# Nécessite `uv`. Multitran nécessite en plus les dictionnaires Apple installés.
set -e
cd "$(dirname "$0")"
DATA="${DICO_DATA:-data}"; mkdir -p "$DATA"
if [ "${1:-}" != "--multitran-only" ]; then

echo "==> Conjugaisons (verbecc)…"
uv run build_conjugations.py

echo "==> Index inverse des formes (doit → devoir)…"
python3 build_conj_forms.py

echo "==> Lexique 3.83 (fréquence, lemmes, genres, mots-outils)…"
python3 build_lexique.py

echo "==> Grammalecte (correcteur grammatical hors-ligne, pour dico -g)…"
python3 build_grammalecte.py

fi
BUNDLES="$HOME/Library/Dictionaries"
if [ -d "$BUNDLES/multitran_rufr.dictionary" ] && [ -d "$BUNDLES/multitran_frru.dictionary" ]; then
  for dir in rufr frru; do
    echo "==> Multitran $dir → Tabfile…"
    uv run --with pyglossary --with lxml --with biplist -- pyglossary \
      "$BUNDLES/multitran_${dir}.dictionary" "$DATA/multitran_${dir}.txt" \
      --read-format=AppleDictBin --write-format=Tabfile --no-progress-bar
  done
  echo "==> Construction de data/multitran.db…"
  python3 build_multitran.py
  rm -f "$DATA"/multitran_rufr.txt "$DATA"/multitran_frru.txt
  rm -rf "$DATA"/multitran_*.txt_res
else
  echo "!! Dictionnaires Multitran absents dans ~/Library/Dictionaries/."
  echo "   dico marchera sans l'option -m. Installe les .dictionary pour l'activer."
fi

echo "✓ Terminé."
