# Dico — macOS popup 📖

A small native floating panel sitting on top of the [`dico`](../README.md)
dictionary. It lives in the menu bar (no Dock icon) and opens **anywhere** with
**⌥D**.

![modes](https://img.shields.io/badge/modes-5-4c6ef5)

## What it does

One field, five modes. Enter runs the query.

| Mode | Chip | What you see |
|---|---|---|
| **Word** | 📖 | Translation, senses grouped by part of speech, as numbered chips. Gender is colored (m blue, f pink), frequency in ★. **Clicking a chip saves the term** to the vocabulary (or **⌘1…⌘9**). Example + back-translations. |
| **Conjugate** | 🔁 | A je/tu/il/nous/vous/ils × 7 tenses grid, pronouns stripped, the présent column highlighted. |
| **Grammar** | ✅ | The sentence with its mistakes highlighted (red = grammar, orange = spelling), the numbered messages, the suggestions as green chips, the corrected sentence + **Copy**. |
| **X-ray** | 🔬 | A compact table: word · lemma · pos · tense · role · meaning. |
| **Ask** | 💬 | The tutor (local LLM) answers in light markdown. The last word you looked up is passed to it as `--context`. |

**Prefixes**: typing `-c `, `-g `, `-x ` or `?` at the start of the field
switches the mode and removes the prefix.

## Shortcuts

| | |
|---|---|
| `⌥D` | open / close the panel (global, from any app) |
| `Esc` | close |
| `⌘K` | clear the field |
| `⌘1`…`⌘9` | save the n-th sense |
| click outside | close |

The global hotkey goes through Carbon `RegisterEventHotKey`: **no Accessibility
permission is requested**.

## Building

```bash
./build.sh                                   # → build/Dico.app
./build/Dico.app/Contents/MacOS/Dico --selftest   # exercises the CLI→Swift chain
open build/Dico.app                          # then ⌥D
./install.sh                                 # → /Applications/Dico.app
```

No Xcode project: `xcrun swiftc` is enough (Xcode Command Line Tools,
Swift 5.9+, macOS 14+, Apple Silicon).

## Requirements

The app only drives the `dico` CLI, so you need `dico` and Python 3:

```bash
uv tool install git+https://github.com/mechanicpanic/dico
dico --setup
```

The app looks, in order, for: `$DICO_BIN`, then `dico` in `/opt/homebrew/bin`,
`~/.local/bin`, `/usr/local/bin`, `/usr/bin`, `/bin`; failing that it runs
`python3 $DICO_SCRIPT` or `python3 ~/Projects/vibes/dico/dico.py`. The **Ask**
mode additionally needs the local LLM (LM Studio on `http://localhost:1234`).

## Files

```
Sources/DicoClient.swift   runs the CLI, decodes the last JSON object
Sources/DicoModel.swift    modes, state, queries, saving, toasts
Sources/PanelView.swift    palette, material, field, mode chips, footer
Sources/ResultViews.swift  the five result views
Sources/DicoApp.swift      @main, menu bar, panel, ⌥D, --selftest
```
