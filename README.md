# dico 🇫🇷

A pocket dictionary for a **Russian / English speaker learning French**: a
zero-dependency Python CLI (`dico`) and a native **macOS popup** (`macos/`,
**⌥D** from any app) that drives it. Several sources, most of them **offline**.

## Getting started

**With Homebrew** — the app and the `dico` command, and `brew upgrade` keeps
them current:

```sh
brew install --cask mechanicpanic/dico/dico          # add --no-quarantine to skip the Gatekeeper prompt
```

**Or the DMG — nothing to install.** Download `Dico-<version>.dmg` from the
[releases](https://github.com/mechanicpanic/dico/releases), drag Dico
to Applications, and press **⌥D** anywhere. The dictionary, the conjugations and
the grammar checker are *inside the app*: no Python, no `uv`, no Terminal, no
setup step, and it works offline.

> **The first launch takes three extra clicks.** The app is signed ad-hoc
> (notarising it needs a paid Apple account), so macOS refuses the first
> double-click. Open **System Settings ▸ Privacy & Security**, scroll to
> *Security* — it says Dico was blocked — and click **Open Anyway**. Once.
> (On macOS 14 and older, right-click ▸ Open does the same job; Apple removed
> that shortcut in macOS 15.) The DMG says all this too.

**The command line**, if you want `dico` in a terminal as well:

```sh
uv tool install git+https://github.com/mechanicpanic/dico
dico --setup     # builds the offline data (~2 min), then asks about the tutor
dico --tour      # a 2-minute guided walkthrough
dico             # the interactive mode — just type
```

Requirements for the **command line**: [`uv`](https://docs.astral.sh/uv/) (for
the install, the conjugation build and spaCy). The core is pure standard
library and runs on the Python macOS ships (3.9) — which is why the app needs
nothing at all.
Data and settings live in `~/.dico/` and `~/.dico_config.json`; `DICO_HOME`,
`DICO_DATA`, `DICO_VOCAB`, `DICO_STORE` move them elsewhere.

Working from a clone instead (development):

```sh
git clone https://github.com/mechanicpanic/dico && cd dico && ./setup.sh
alias dico="python3 $PWD/dico.py"
```

**Tutor without a local model?** Run `dico --llm` and bring your own key —
Anthropic, OpenAI, Mistral, Groq, Gemini or any OpenAI-compatible URL. It is
tested once and stored in `~/.dico_config.json` (chmod 600). With LM Studio or
Ollama running, dico finds the loaded model by itself.

## Interactive mode: no flags

**dico guesses what you mean**: an English/Russian word → a card with numbered
senses; a French word → its card (verbs show their présent); a French sentence →
grammar check with the rule; `? …` → the tutor. Then act on the card in plain
words:

```
» cook
     verbe      1 cuisiner ★★  2 cuire ★  3 faire la cuisine   ← bake
     nom        4 un cuisinier ★  5 une cuisine ★★             ← chef
     « Il aime cuisiner le week-end. » — He likes to cook on weekends.
» save 4              → saves « un cuisinier » (the noun, not the verb)
» conj                → full conjugation grid        (or: conj manger)
» def                 → dictionary definitions       (or: def maison)
» ru                  → Russian, Multitran, offline  (or: ru chat)
» ex                  → example sentences EN + RU    (or: ex partir)
» say · syn           → hear it said · synonyms and homophones
» grammar · x         → grammar check · x-ray, on the last sentence or one you give
» ? is it formal      → ask the tutor about what you're looking at (?? = detailed)
» help                → the cheat-sheet
```

Sense 1 is the one autosave keeps; `save N` saves sense N — no more fighting
with a translator that picked the wrong part of speech. `say` plays a **native
speaker recording** (Wiktionary/Commons), `syn` gives **synonyms with their
register** (*greffier (familier)*) and **homophones** — `vert` → *vair · ver ·
vers · verre*. **No need to type
accents**: `etre` finds *être*, `creche` finds *crèche*.

Settings from inside the REPL: `:save on|off` (autosave) · `:forget <word>` ·
`:render` · `:examples on|off` · `:spacy on|off` · `:llm <url> [model]`.

## One-shot switches (from the shell)

| Command | Source | Internet? |
|---|---|---|
| `dico кошка` | the card (Google senses + Lexique + Tatoeba) | yes |
| `dico -m кошка` | **Multitran** (rich, ru↔fr) | **no** 🔌 |
| `dico -c manger` | **Conjugation** (~7000 verbs, 7 tenses) | **no** 🔌 |
| `dico -c doit` | **Conjugated form** → infinitive (*doit → devoir*) | **no** 🔌 |
| `dico -f manger` | **Wiktionary** — the word is already French | yes |
| `dico -d house` | **Wiktionary** — after translation | yes |
| `dico -g "Elle est parti"` | **Grammar** — fixes a sentence, names the rule (Grammalecte) | **no** 🔌 |
| `dico -x "j'habitais à Lyon"` | **X-ray** — every word: lemma, tense, gender, role, meaning | no* 🔌 |
| `dico -a "tu ou vous ?"` | **Tutor** — a question (`-p` for a detailed answer) | no* |
| `dico -s house` | save this word now | yes |
| `dico --say chat` | **native recording** (Wiktionary/Commons, MP3, cached) | yes |
| `dico --syn heureux` | **synonyms + homophones** (Wiktionnaire) | yes |
| `dico --mots-outils` | **grammatical core** (Lexique): articles, prepositions, pronouns… | **no** 🔌 |

They combine: `dico -mc хотеть`, `dico -fc manger`. `*` local = no internet needed.
`dico --json …` returns the same things as JSON (what the popup and Raycast use).

## What is behind the card

### The dictionary card

A lookup is a **real entry**: senses **grouped by part of speech** and numbered,
the article/gender of every noun (Lexique), the frequency (★), the
back-translations of the main sense, and a real example sentence (Tatoeba). A
word that is **already French** (`maison`, `doit`) gets its own card: part of
speech · gender · article · frequency, then its English senses. Definitions
(`def`) come from the French Wiktionary and stay in French — with the etymology.

### Sentences: grammar and x-ray

- **Grammar** — the **Grammalecte** checker (GPL, pure Python, installed into
  `data/grammalecte/` by `build_grammalecte.py`): the sentence with its mistakes
  highlighted, each mistake *(what · why · → suggestion)*, then the corrected
  version. In the REPL any French sentence triggers it.
- **X-ray** — word by word: lemma, part of speech, **tense + person** (from the
  conjugation database — more reliable than spaCy for the imparfait), gender,
  frequency, **role** (sujet / COD / verbe principal…) and meaning. Roles come
  from **spaCy** (`tools/xray_spacy.py`, run through `uv run`; the model is
  downloaded on the first call, ~3 s afterwards). Without spaCy, or with
  `:spacy off`, everything else still works instantly and offline.

### The tutor

The tutor is a **question you ask**, not a tier you switch on. In the REPL,
`? your question` (`?? …` for a detailed answer) — it knows the last word you
looked up and the last sentence you analysed:

```
» cuisiner
» ? et cuire, c'est pareil ?
» x j'en veux deux
» ? explique « en » ici
```

Backends, in order: **1)** an **OpenAI-compatible** endpoint (LM Studio on
`http://localhost:1234/v1` or Ollama on `:11434`, auto-detected — or a DGX Spark /
Mistral / Groq through `DICO_LLM_URL`, `DICO_LLM_MODEL`, `DICO_LLM_KEY`, or
`dico --llm`); **2)** the Anthropic API (`ANTHROPIC_API_KEY`); **3)** the
`claude` command. Recommended local model (bake-off on 5 grammar questions,
M4 Pro): **Gemma 4 12B it — MLX 4-bit** (`lmstudio-community/gemma-4-12B-it-MLX-4bit`,
~2 s per answer, 5/5 correct). Ministral 3 8B is faster (~1.5 s) but got the
*de/des* rule wrong. Prefer **MLX** weights over GGUF on Apple Silicon (~2× faster).

### Levels, pronunciation and homophones — all offline

A French word carries its **CEFR level** (`A1`…`C2`, from **FLELex**) next to
the frequency band. They answer different questions: the band says how common a
word is *for a native*, the level says **when a learner is expected to meet it**
— `néanmoins` is *peu courant* but only **B1**. It also carries its
**pronunciation in IPA** (`maison  /mɛzɔ̃/`), derived from Lexique's own
phonetic column, so all 142 694 forms have one with no network.

Grouping Lexique on that same phonetic column gives **exact homophones,
offline and instantly** — `vert` → *vair · ver · verre · vers* (inflections of
the word itself are dropped). `syn` merges them with the Wiktionnaire's list.

### Lexique 3.83 — knowledge, offline

Every French word gets a badge `📊 frequency · part of speech · gender`
(*très courant → rare*, from [Lexique](http://www.lexique.org)), so you can tell
whether it is worth memorising. Lexique also enriches autosave (lemma + gender
**with no network**) and **detects cognates/false friends** — `table` (EN) stays
`table` (FR), but `pain` (EN → *douleur*) is flagged *"also a French word: un
pain"*. `dico --mots-outils` prints the grammatical scaffolding you cannot guess
(le, de, à, que, être, avoir…) with their English meanings; add `-s` to turn
them into cards.

## Vocabulary: autosave + JSON store

Everything you look up can be **saved automatically**. The **source of truth** is
`dico_vocab.json`; the markdown next to it is a **regenerated view** you never
edit by hand, and `push_anki.py` reads the store directly. Curation is
**subtractive**: everything is saved, you *remove* the junk.

| Command | Effect |
|---|---|
| `dico --autosave on` / `off` | turn automatic saving on/off (persistent) |
| `dico -s word` | save this word now (even when autosave is off) |
| `dico --forget word` | drop a word (subtractive curation) |
| `dico --render` | regenerate the markdown from the JSON store |
| `dico --review` | review the saved words — spaced repetition, in the terminal |
| `dico --enrich` | backfill gloss, example, IPA, CEFR and gender on every saved word |
| `dico --backup-init [URL]` | give the cards a git repository of their own (and a remote) |
| `dico --backup` / `--pull` | pull, render, commit and push the cards / only pull |

Every save enriches the word: **gender** (→ *un/une*), the accented lemma, the
part of speech, an **English gloss**, a real **example sentence** with its
translation (Tatoeba), **IPA** and **CEFR level** — everything a flashcard
needs. Each word is a card: `dico --review` (or the popup's 🎴 Cards mode)
schedules them with an Anki-style SM-2 whose state lives in the store.

**Backup.** Once the cards have a repository (`--backup-init`, or Settings ▸
Vocabulary ▸ Backup ▸ Turn on), every change is a commit; with a remote they
are pushed and other machines can write to them. The popup pulls at launch and
pushes after saves.
Where the files live: `vocab_path` / `store_path` in `~/.dico_config.json`
(the popup's Settings ▸ Vocabulary sets them), or `DICO_VOCAB` / `DICO_STORE`,
which win over the config.

## macOS popup

`macos/` is a native menu-bar app: **⌥D** anywhere opens a floating panel with
the same card, a conjugation grid, grammar, x-ray and the tutor — all by click,
no flags. **Select a word in any app and press ⌥D** to look it up directly (or
right-click ▸ Services ▸ *Look up in Dico*). Plus a ⚙︎ Settings window that edits the same `~/.dico_config.json`
the CLI uses (tutor / BYOK, autosave and store paths, hotkey, launch at login,
rebuild offline data). It only needs `dico` installed as above.

```sh
cd macos && ./build.sh      # → build/Dico.app   (Xcode Command Line Tools, macOS 14+)
./install.sh                # → /Applications/Dico.app, then ⌥D
```

Everything about it — modes, the card's sections, every shortcut, the settings
tabs, `--selftest` — is in [`macos/README.md`](macos/README.md).

**Raycast** instead: `tools/raycast/dico.sh` is a Raycast *Script Command*
(Raycast → Settings → Extensions → Script Commands → Add Directories → the
`tools/raycast` folder). `⌥ Space → dico кошка` shows the card in the Raycast
panel; `dico -c aller`, `dico -g elle est parti` work the same way.

## Releases

Tagged releases carry the CLI and a **built `Dico.app`**:

```sh
uv tool install git+https://github.com/mechanicpanic/dico@v1.0.0   # a pinned version
```

For the app, download `Dico-<version>.zip` from the release, unzip it and drag
it to `/Applications`. The build is **signed ad-hoc**, not notarised, so the
first launch needs **right-click ▸ Open** (or
`xattr -dr com.apple.quarantine /Applications/Dico.app`); after that it opens
normally. `CHANGELOG.md` says what is in each one.

Cutting one: `tools/release.sh` is a dry run — it refuses a dirty tree or a
version with no changelog section, builds the app, runs its self-test and zips
it — and `tools/release.sh --publish` tags and publishes. The version lives in
`dico.py` (`__version__`) and nowhere else: the wheel and the app's Info.plist
both read it from there, and `dico --version` prints it.

## Offline data (`data/`)

The SQLite databases are **not** versioned (~600 MB). `dico --setup` (or
`./setup.sh` in a clone) rebuilds them:

| Builder | Produces | Needs |
|---|---|---|
| `build_conjugations.py` | `conjugations.db` (verbecc, ~7000 verbs) | `uv` |
| `build_conj_forms.py` | the `forms` reverse index (*doit → devoir*) | — |
| `build_lexique.py` | `lexique.db` (Lexique 3.83, from lexique.org) — spelling, lemma, gender, frequency, **phonetics, syllables, homophones** | — |
| `build_flelex.py` | the `cefr` table (**FLELex**, CEFRLex/UCLouvain): an A1…C2 level for 14 236 lemmas | — |
| `build_grammalecte.py` | `data/grammalecte/` (the checker, from grammalecte.net) | — |
| `build_multitran.py` | `multitran.db` — **optional**, from the Apple dictionaries `~/Library/Dictionaries/multitran_{rufr,frru}.dictionary` (converted with `pyglossary` by `setup.sh`) | `uv` |

Without a database the matching feature is simply off (`-m` without Multitran,
`-c` without conjugations…); the rest of `dico` keeps working.

## Files

| Path | Role |
|---|---|
| `dico.py` | the tool (zero dependencies) |
| `build_*.py`, `setup.sh` | the offline data builders (above) |
| `tools/xray_spacy.py` | spaCy sidecar for x-ray roles (PEP 723, run through `uv`) |
| `tools/raycast/dico.sh` | Raycast script command |
| `macos/` | the popup app (SwiftUI, no Xcode project) |
| `data/` | SQLite databases **(not versioned)** |

## Sources & licences

- Code: **MIT**. Everything else is downloaded from its own author by
  `dico --setup`, never redistributed here.
- **Wiktionnaire / Wikimedia Commons** — definitions, etymology, synonyms,
  homophones, Russian translations *and* the spoken recordings (CC BY-SA).
  Multitran stays optional and bring-your-own; without it, `ru` answers from
  the Wiktionnaire (with transliteration and gender).
- **FLELex** (François, Gala, Watrin & Fairon — CEFRLex, UCLouvain) — the CEFR levels.
- **Lexique 3.83** (New, Pallier et al.) — CC BY-SA · **Tatoeba** — CC BY 2.0 fr ·
  **Grammalecte** (Olivier R.) — GPL 3 · **verbecc** — conjugations · **spaCy**
  `fr_core_news_md` — MIT/CC BY-SA · **Wiktionary** — CC BY-SA · **Multitran**:
  proprietary Apple dictionaries, *bring your own*.
- The quick translation goes through an unofficial Google endpoint, as
  `client=dict-chrome-ex` (what Chrome's own dictionary uses). The `client=gtx`
  value every scraping snippet uses is blocked outright — Google answers its
  *"Sorry… automated queries"* page with HTTP 429, and waiting does not clear
  it. dico tries `dict-chrome-ex` first, keeps `gtx` as a spare, and falls back
  to **MyMemory** (the card says so) only if both refuse.
- Every network source — translations, Tatoeba examples, Wiktionary — is cached
  on disk for 30 days (`data/translate_cache.json`), so a word you have already
  looked up comes back instantly and costs no request.
