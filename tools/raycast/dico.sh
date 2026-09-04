#!/bin/bash

# Required parameters:
# @raycast.schemaVersion 1
# @raycast.title dico
# @raycast.mode fullOutput
# @raycast.packageName dico

# Optional parameters:
# @raycast.icon 📖
# @raycast.argument1 { "type": "text", "placeholder": "word, \"-c verb\", \"-g sentence\", \"-x sentence\"" }
# @raycast.description Russian/English → French dictionary (dico) in a popup

# Documentation:
# @raycast.author Anna Smirnova

# dico on the PATH (uv tool install) or a local clone
DICO="$(command -v dico || echo "$HOME/Projects/vibes/dico/dico.py")"
export PATH="$HOME/.local/bin:/opt/homebrew/bin:$PATH"
case "$DICO" in *.py) RUN=(python3 "$DICO");; *) RUN=("$DICO");; esac

# "-c manger", "-g elle est parti" → split into words; otherwise a word/sentence
read -r -a ARGS <<< "$1"
"${RUN[@]}" "${ARGS[@]}" 2>&1 | sed 's/\x1b\[[0-9;]*m//g'
