# Dico — macOS popup 📖

A small native floating panel sitting on top of the [`dico`](../README.md)
dictionary. It lives in the menu bar (no Dock icon) and opens **anywhere** with
**⌥D**.

![modes](https://img.shields.io/badge/modes-5-4c6ef5)

Everything is clickable: **no command-line flags are ever needed in the panel**.
One field, five mode chips, and a row of buttons on the word card.

## The five modes

| Mode | Chip | What you see |
|---|---|---|
| **Word** | 📖 | The card — translation, senses, and buttons that open the rest of the dictionary (see below). |
| **Conjugate** | 🔁 | A je/tu/il/nous/vous/ils × 7 tenses grid, pronouns stripped, the présent column highlighted. All seven tenses fit without scrolling; hover a column for what the tense is for. |
| **Grammar** | ✅ | The sentence with its mistakes highlighted (red = grammar, orange = spelling), the numbered messages, the suggestions as green chips, the corrected sentence + **Copy**. |
| **X-ray** | 🔬 | A compact table: word · lemma · pos · tense · role · meaning. |
| **Ask** | 💬 | The tutor answers in light markdown, model name dimmed. The word you came from is shown as an “about « … »” chip and passed as `--context`. |

## The word card

The card is the whole dictionary, not just the translation:

- **header** — the query with its flag (🇬🇧/🇷🇺 for a translation into French,
  🇫🇷 for a French word), the head with its article, the gender pill
  (m blue, f rose) and the frequency in ★;
- **senses** as numbered chips grouped by part of speech — **clicking one saves
  it** to the vocabulary (or **⌘1…⌘9**), and a toast confirms
  « un cuisinier » added;
- the **example sentence**, French in italic, English dimmed;
- a row of buttons that open **expandable sections**, each fetched the first
  time you open it, with its own spinner and a *Try again*:

| Button | What it opens | CLI behind it |
|---|---|---|
| **Definitions** | the Wiktionary entry: IPA, part of speech, numbered definitions, etymology | `-f` |
| **Russian** | the offline Multitran entry | `-m` |
| **Examples** | the example sentences of the French term | plain lookup |
| **Conjugate** | the conjugation grid, inline (verbs only) | `-c` |
| **Ask ?** | switches to Ask with this word as the tutor's context | `-a --context` |

The French term the sections query is sense 1 for a translation card
(`cook` → `cuire`) and the word itself for a French card.

## Recent

With an empty field the panel shows the **last 8 queries** (kept in
`UserDefaults`); click one to run it again, or **Clear** to forget them.

## Shortcuts

| | |
|---|---|
| `⌥D` | open / close the panel (global, from any app) |
| `Esc` | first press clears the field and the results, second press closes |
| `⌘K` | clear the field |
| `⌘1`…`⌘9` | save the n-th sense |
| click outside | close |

Erasing the field wipes the results too — nothing stale is ever left on screen.

The global hotkey goes through Carbon `RegisterEventHotKey`: **no Accessibility
permission is requested**.

## When something is missing

- `dico` itself not found → the panel shows the install recipe
  (`uv tool install …`, then `dico --setup`) with a **Copy** button;
- the offline databases not built → “Offline data not built — run:
  `dico --setup`”, also copyable;
- Multitran is optional (it needs the Apple dictionaries), and the tutor has to
  be configured with `dico --llm` — both say so in plain English.

## Building

```bash
./build.sh                                   # → build/Dico.app
./build/Dico.app/Contents/MacOS/Dico --selftest   # exercises the CLI→Swift chain
open build/Dico.app                          # then ⌥D
./install.sh                                 # → /Applications/Dico.app
```

`--selftest` runs every CLI call the panel makes (word, conjugation, grammar,
x-ray, Wiktionary, Multitran, examples, tutor), lays the views out off screen —
including a word card **with a section expanded** — and checks the recent list
and the clear-on-erase behaviour. It prints one ✓ per line and exits non-zero on
the first ✗.

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
mode additionally needs a tutor (`dico --llm`).

## Files

```
Sources/DicoClient.swift   runs the CLI, decodes the last JSON object
Sources/DicoModel.swift    modes, state, sections, recents, saving, toasts
Sources/PanelView.swift    palette, material, field, mode chips, recents, errors
Sources/ResultViews.swift  the five result views + the card sections
Sources/DicoApp.swift      @main, menu bar, panel, ⌥D, --selftest
```
