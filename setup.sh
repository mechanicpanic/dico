#!/usr/bin/env bash
# Rebuild dico's local databases (not versioned: ~600 MB).
# Requires `uv`. Multitran also requires the Apple dictionaries to be installed.
set -e
cd "$(dirname "$0")"
DATA="${DICO_DATA:-data}"; mkdir -p "$DATA"
if [ "${1:-}" != "--multitran-only" ]; then

echo "==> Conjugations (verbecc)…"
uv run build_conjugations.py

echo "==> Reverse form index (doit → devoir)…"
python3 build_conj_forms.py

echo "==> Lexique 3.83 (frequency, lemmas, genders, function words)…"
python3 build_lexique.py

echo "==> Grammalecte (offline grammar checker, for dico -g)…"
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
  echo "==> Building data/multitran.db…"
  python3 build_multitran.py
  rm -f "$DATA"/multitran_rufr.txt "$DATA"/multitran_frru.txt
  rm -rf "$DATA"/multitran_*.txt_res
else
  echo "!! Multitran dictionaries missing from ~/Library/Dictionaries/."
  echo "   dico works without the -m option. Install the .dictionary bundles to enable it."
fi

echo "✓ Done."
