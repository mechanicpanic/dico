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
| **Conjugate** | 🔁 | A je/tu/il/nous/vous/ils × 7 tenses **grid**: full French tense names in the header, a muted pronoun gutter, alternating row bands, the présent column on its own tinted panel, compound forms with the auxiliary dimmed (`ai `**`dit`**) and a faint « — » where the impératif has no form. Sized from a width budget, so it never scrolls sideways; hover a column for what the tense is for. |
| **Grammar** | ✅ | The sentence with its mistakes highlighted (red = grammar, orange = spelling), the numbered messages, the suggestions as green chips, the corrected sentence + **Copy**. |
| **X-ray** | 🔬 | A compact table: word · lemma · pos · tense · role · meaning. |
| **Ask** | 💬 | The tutor answers in light markdown, model name dimmed. The word you came from is shown as an “about « … »” chip and passed as `--context`. |

## The word card

The card is the whole dictionary, not just the translation:

- **header** — the query with **its own** flag (🇬🇧/🇷🇺 — from `src_lang`, or
  Cyrillic → 🇷🇺) and the French result with 🇫🇷: « 🇷🇺 сказать → 🇫🇷 dire ».
  A French card is 🇫🇷 throughout. Then the head with its article, the gender pill
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
| **Russian** | the offline Multitran entry **in full** — one section per part of speech, one row per sense (number + domain tag: общ., юр., тех., gener.…), the translations flowing separated by « · », each note in small italic grey right after its translation. Nothing is capped or truncated: long notes are whole example sentences and they wrap; the card scrolls. | `-m` |
| **Examples** | Tatoeba sentences: up to 4 with an English translation, then up to 2 with a Russian one (🇷🇺); the card's own example stays first unless Tatoeba already has it. “No examples found” when both lists are empty | `--examples` |
| **Conjugate** | the conjugation grid, inline (verbs only) | `-c` |
| **Ask ?** | switches to Ask with this word as the tutor's context | `-a --context` |

The French term the sections query is sense 1 for a translation card
(`cook` → `cuire`) and the word itself for a French card.

## Recent

With an empty field the panel shows the **last 8 queries** (kept in
`UserDefaults`); click one to run it again, or **Clear** to forget them.

## Shortcuts

Press **⌘/** for this list inside the panel; it is also a tab in Settings, and
every button carries the same thing as a tooltip.

| | |
|---|---|
| `⌥D` | open / close the panel (global, from any app — configurable) |
| `Esc` | clears the field and the results; again to close |
| `⌘K` | clear the field |
| `⌘,` | Settings |
| `⌘/` | show the shortcuts sheet |
| `⌘W` | close the panel |
| `⌘⇧1`…`⌘⇧5` | Word · Conjugate · Grammar · X-ray · Ask |
| `⌘1`…`⌘9` | save the n-th sense of the card |
| `⌘D` | Definitions | 
| `⌘R` | Russian |
| `⌘E` | Examples |
| `⌘J` | Conjugate (on a verb card) |
| `⌘L` | ask the tutor about this word |
| `⌘⇧C` | copy the corrected sentence (Grammar) |
| click outside | close |

The footer is one line: `⌘/ shortcuts · Esc clear/close · ⌥D anywhere` — and
the hotkey shown is the one actually configured.

Erasing the field wipes the results too — nothing stale is ever left on screen.

The global hotkey goes through Carbon `RegisterEventHotKey`: **no Accessibility
permission is requested**.

## ⚙︎ Settings

**⌘,**, the ⚙︎ in the footer, or *Settings…* in the 📖 menu. It is a normal
window (not the floating panel), and it reads and writes **the same
`~/.dico_config.json` the CLI uses** — written atomically, `chmod 600` (it may
hold an API key), and keys it does not know about are preserved.

| Tab | What is in it | Config keys |
|---|---|---|
| **Tutor** | local / bring-your-own-key / Anthropic / none. *local* shows what actually answered `GET /v1/models` on LM Studio `:1234` and Ollama `:11434`. *byok* has presets — OpenAI, Mistral, Groq, Gemini, Custom — plus base URL, model and a secure key field. A **Test** button runs `dico --json -a "Reply with the single word ok"` and shows the model that answered, or the error. | `llm`, `llm_url`, `llm_model`, `llm_key`, `anthropic_key` |
| **Vocabulary** | auto-save every lookup; where the markdown view and the JSON store live (file pickers, empty = `~/.dico/…`). A caption warns when `DICO_VOCAB` / `DICO_STORE` are set in the environment — those still win over the config. | `autosave`, `vocab_path`, `store_path` |
| **General** | the example sentence on the card; X-ray roles via spaCy (*off = instant, on = ~3 s, needs `uv`*); the **global hotkey** (⌥D, ⌥Space, ⌃⌥D, ⌘⇧D — re-registered with Carbon on the spot); **launch at login** via `SMAppService`. | `examples`, `xray_spacy`, `popup_hotkey` |
| **Offline data** | **Build / refresh** runs `dico --setup --no-llm` in the background and streams its output into a log view with a spinner; **Take the tour** opens Terminal on `dico --tour`. | — |
| **Shortcuts** | the same list as ⌘/. | — |

Switching tutor backend clears the other backend's keys, exactly as
`dico --llm` does, so the CLI never sees two half-configured tutors.

## When something is missing

- `dico` itself not found → the panel shows the install recipe
  (`uv tool install …`, then `dico --setup`) with a **Copy** button;
- the offline databases not built → “Offline data not built — run:
  `dico --setup`”, also copyable;
- Multitran is optional — when it is not there the Russian section says
  “Multitran not installed — it needs the Apple dictionaries (optional, see
  README)”;
- the tutor has to be configured — in **Settings ▸ Tutor**, or with
  `dico --llm`.

## Building

```bash
./build.sh                                   # → build/Dico.app
./build/Dico.app/Contents/MacOS/Dico --selftest   # exercises the CLI→Swift chain
open build/Dico.app                          # then ⌥D
./install.sh                                 # → /Applications/Dico.app
```

`--selftest` runs every CLI call the panel makes (word, conjugation, grammar,
x-ray, Wiktionary, Multitran, `--examples` — both a full and an empty pack,
tutor), lays the views out off screen — including a word card **with a section
expanded** — and checks the recent list and the clear-on-erase behaviour. On
top of that it:

- lays out the conjugation grid for `-c dire` in both sizes and **asserts it
  fits** the panel's width budget, that the seven tenses are there in order,
  that `j'ai dit` splits into a dimmed `ai` + `dit`, and that the impératif's
  blanks land on je / il / ils;
- lays out the Multitran section for `-m dire` and `-m кошка` and asserts that
  **every** group, sense, domain, translation and note is represented, the long
  note on « называть » **verbatim**, and that the flat `lines` only render when
  `groups` is empty;
- checks the card's flag follows the *query's* language;
- round-trips the Settings model through a **temp** config file: every key back,
  unknown keys kept, `chmod 600`, and a backend switch clearing the other
  backend's keys (`DICO_CONFIG_PATH` overrides the path **for this app only** —
  the CLI always uses `~/.dico_config.json`);
- lays out all five Settings tabs;
- checks each hotkey preset's Carbon key code and modifier mask, and the
  fallback to ⌥D;
- checks the shortcut catalogue covers every documented key and lays the ⌘/
  sheet out;
- runs the Settings ▸ Test call (`--json -a`) once.

It prints one ✓ per line and exits non-zero on the first ✗.

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
Sources/DicoClient.swift   runs the CLI (blocking + streaming), decodes JSON
Sources/DicoConfig.swift   ~/.dico_config.json, atomic + chmod 600; hotkey presets
Sources/DicoModel.swift    modes, state, sections, recents, saving, toasts
Sources/PanelView.swift    palette, material, field, mode chips, recents, errors
Sources/ResultViews.swift  the five result views + the card sections
Sources/Shortcuts.swift    the shortcut catalogue, the ⌘/ sheet, the list
Sources/SettingsView.swift the ⚙︎ window: tutor, vocabulary, general, data, keys
Sources/DicoApp.swift      @main, menu bar, panel, the hotkey, --selftest
```
