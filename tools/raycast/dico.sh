#!/bin/bash

# Required parameters:
# @raycast.schemaVersion 1
# @raycast.title dico
# @raycast.mode fullOutput
# @raycast.packageName dico

# Optional parameters:
# @raycast.icon 📖
# @raycast.argument1 { "type": "text", "placeholder": "mot, « -c verbe », « -g phrase », « -x phrase »" }
# @raycast.description Dictionnaire russe/anglais → français (dico) dans un popup

# Documentation:
# @raycast.author Anna Smirnova

# dico dans le PATH (uv tool install) ou clone local
DICO="$(command -v dico || echo "$HOME/Projects/vibes/dico/dico.py")"
export PATH="$HOME/.local/bin:/opt/homebrew/bin:$PATH"
case "$DICO" in *.py) RUN=(python3 "$DICO");; *) RUN=("$DICO");; esac

# « -c manger », « -g elle est parti » → on éclate les mots ; sinon un mot/une phrase
read -r -a ARGS <<< "$1"
"${RUN[@]}" "${ARGS[@]}" 2>&1 | sed 's/\x1b\[[0-9;]*m//g'
