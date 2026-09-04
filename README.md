# dico 🇫🇷

A command-line pocket dictionary: **Russian / English → French**, built for a
Russian/English-speaking learner. **Zero dependencies** at its core (the Python 3
standard library); several levels, two of which work **offline**.

## Levels (can be combined)

| Command | Source | Internet? |
|---|---|---|
| `dico кошка` | Google (fast) | yes |
| `dico -m кошка` | **Multitran** (rich, ru↔fr) | **no** 🔌 |
| `dico -c manger` | **Conjugation** (~7000 verbs, 7 tenses) | **no** 🔌 |
| `dico -c doit` | **Conjugated form** → infinitive (*doit → devoir*) | **no** 🔌 |
| `dico -f manger` | **Wiktionary** — the word is already French | yes |
| `dico -d house` | **Wiktionary** — after translation | yes |
| `dico -a house` | **AI tutor** — quick card (local model through LM Studio, or Claude) | no* |
| `dico -a "tu ou vous ?"` | **Free question** to the tutor (several words = a question) | no* |
| `dico -p …` | same, detailed answer | no* |
| `dico -s house` | save this word (vocabulary store) | yes |
| `dico --mots-outils` | **grammatical core** (Lexique): articles, prepositions, pronouns… | **no** 🔌 |
| `dico -g "Elle est parti"` | **Grammar** — fixes a sentence, names the rule (Grammalecte) | **no** 🔌 |
| `dico -x "j'habitais à Lyon"` | **X-ray** — every word: lemma, tense, gender, role, meaning | no* 🔌 |

They combine: `dico -mc хотеть`, `dico -fc manger`, `dico -mcdap word`…
Interactive mode: type `dico`, then `!m` `!c` `!f` `!d` `!a` `!p` `!s` in front of a word.

### The dictionary card (the default)

A lookup shows a **real entry**: senses **grouped by part of speech** and
**numbered**, the article/gender of every noun (Lexique), the frequency (★), the
back-translations of the main sense, and a real example sentence (Tatoeba):

```
» cook
     verbe      1 cuisiner ★★  2 cuire ★  3 faire la cuisine   ← bake
     nom        4 un cuisinier ★  5 une cuisine ★★             ← chef
     « Il aime cuisiner le week-end. » — He likes to cook on weekends.
» !s 4                      ← saves « un cuisinier » (the noun, not the verb)
```

Sense 1 is the one autosave keeps; **`!s N`** saves sense N — no more fighting
with flags when Google picked the wrong part of speech. A word that is **already
French** (`maison`, `doit`) gets its own card: part of speech · gender · article ·
frequency, then its English senses. `:examples off` turns the Tatoeba sentences off.

**No need to type accents**: `etre` finds *être*, `creche` finds *crèche*.
**With no prefix, dico guesses**: a RU/EN word → its card; a French word → its card
(a verb: + its présent); a **French sentence** → a grammar correction; `? …` → the
tutor. Prefixes only force a particular view (`!c` the full grid, `!x` the x-ray,
`!m` Multitran, `!f`/`!d` Wiktionary).

**Forgiving prefixes** (interactive mode): `!c manger`, `! c manger`, `manger !c`,
`-c manger`, `--conj manger`, `!cf word`, `!C MANGER` — all equivalent. An unknown
prefix gives a clear message.

### Sentences: `-g` (grammar) and `-x` (x-ray)

- **`dico -g "<sentence>"`** — the **Grammalecte** checker (GPL, pure Python,
  installed into `data/grammalecte/` by `build_grammalecte.py`): the sentence with
  its mistakes highlighted, then each mistake *(what · why · → suggestion)*, then
  the **corrected version**. Ideal for writing your own sentences and learning the
  rule you were missing.
- **`dico -x "<sentence>"`** — a word-by-word analysis: lemma, part of speech,
  **tense + person** (from the conjugation database — more reliable than spaCy for
  the imparfait), gender, frequency, **role** (sujet / COD / verbe principal…) and
  meaning. The roles come from **spaCy** (`tools/xray_spacy.py`, launched through
  `uv run` — the model is downloaded on the 1st call, ~3 s afterwards). Without
  spaCy, or with `:spacy off`, everything else still works instantly and offline.
  *The English translation line for the sentence needs internet.*

### AI tutor: `?` in the REPL, local model first

The tutor is no longer a "tier" you switch on: it is a **question you ask**. In
interactive mode, `? your question` (or `?? …` for a detailed answer) — the tutor
knows **the last word you looked up / the last sentence you analysed**:

```
» cuisiner
» ? et cuire, c'est pareil ?
» -x j'en veux deux
» ? explique « en » ici
```

Backends, in order: **1)** an **OpenAI-compatible** endpoint (LM Studio on
`http://localhost:1234/v1` by default — or a DGX Spark / Ollama / Mistral / Groq
through `DICO_LLM_URL`, `DICO_LLM_MODEL`, `DICO_LLM_KEY`, or `:llm <url> [model]`
in the REPL); **2)** the Anthropic API (`ANTHROPIC_API_KEY`); **3)** the `claude`
command. Recommended model (bake-off on 5 grammar questions, M4 Pro):
**Gemma 4 12B it — MLX 4-bit** (`lmstudio-community/gemma-4-12B-it-MLX-4bit`,
~2 s per answer, 5/5 correct). Ministral 3 8B is faster (~1.5 s) but got the
*de/des* rule wrong. Always prefer **MLX** weights over GGUF on Apple Silicon
(~2× faster). On the DGX Spark: Mistral Small 4.
`*` local = no internet needed.

### Lexique 3.83 — knowledge, offline (a badge on every lookup)

Every French word gets a **badge** `📊 frequency · part of speech · gender`
(*très courant → rare*, from [Lexique](http://www.lexique.org)), so you can tell
whether it is worth memorising. Lexique is also used to enrich autosave (lemma +
gender **with no network**), and to **detect cognates/false friends** — `table`
(EN) stays `table` (FR), but `pain` (EN→*douleur*) is flagged *"also a French
word: un pain"*. And `dico --mots-outils` prints the grammatical scaffolding you
cannot guess (le, de, à, que, être, avoir…) **with their English meanings**; add
`-s` to turn them into Anki cards (`dico --mots-outils -s`).

## Vocabulary: autosave + JSON store

Everything you look up can be **saved automatically**. The **source of truth** is
`dico_vocab.json` (next to the markdown); the `.md` is only a **regenerated
view** — you never edit the markdown by hand again, and `push_anki.py` reads the
store directly. Curation is **subtractive**: everything is saved, you *remove*
the junk.

| Command | Effect |
|---|---|
| `dico --autosave on` / `off` | turn automatic saving on/off (persistent) |
| `dico -s word` | save this word now (even when autosave is off) |
| `dico --forget word` | drop a word (subtractive curation) |
| `dico --render` | regenerate the markdown from the JSON store |

In interactive mode: `:save on|off` · `:forget <word>` · `:render` · `:spacy on|off` · `:llm` · `:examples on|off`.
Every save enriches the word with its **gender** (→ *un/une*), the accented lemma,
the part of speech and the source language; repeats bump an `×N` counter.

## Installation

```sh
# standalone tool (recommended) — a "dico" command on your PATH
uv tool install git+https://github.com/mechanicpanic/dico
dico --setup            # downloads / builds the offline databases (~2 min)

# or, from a clone (development):
git clone https://github.com/mechanicpanic/dico && cd dico && ./setup.sh
alias dico="python3 $PWD/dico.py"
```

Requirements: **Python 3.10+** and [`uv`](https://docs.astral.sh/uv/) (for the
conjugations, spaCy and the installation). The core has **no dependencies**.
Data and settings live in `~/.dico/` (or in the clone's directory); `DICO_HOME`,
`DICO_DATA`, `DICO_VOCAB`, `DICO_STORE` move them elsewhere.

```sh
# (optional) AI tutor: LM Studio on localhost:1234 works with no configuration;
# otherwise any OpenAI-compatible endpoint, or the Anthropic API:
export DICO_LLM_URL="http://spark.local:8000/v1"  DICO_LLM_MODEL="…"
export ANTHROPIC_API_KEY="sk-ant-..."
# (optional) where your cards live (an Obsidian vault, for instance)
export DICO_VOCAB="$HOME/notes/francais/mots-cherches.md"
```

### macOS popup: Raycast

For those allergic to the terminal (or just in a hurry): `tools/raycast/dico.sh`
is a Raycast *Script Command*. In Raycast → **Settings → Extensions → Script
Commands → Add Directories** → pick the `tools/raycast` folder of the clone (or of
`~/.local/share/uv/tools/dico/…` if installed as a tool). Then:

```
⌥ Space  →  dico кошка
            dico -c aller present
            dico -g elle est parti
```

The card appears in the Raycast panel. The script finds `dico` on the PATH
(`uv tool install`) or, failing that, `~/Projects/vibes/dico/dico.py`.

### Sources & licences

- Code: **MIT**. Everything else is downloaded from its own author by `dico --setup`, never redistributed here.
- **Lexique 3.83** (New, Pallier et al.) — CC BY-SA · **Tatoeba** — CC BY 2.0 fr ·
  **Grammalecte** (Olivier R.) — GPL 3 · **verbecc** — conjugations · **spaCy** `fr_core_news_md` — MIT/CC BY-SA ·
  **Wiktionary** — CC BY-SA · **Multitran**: proprietary Apple dictionaries, *bring your own* (the `-m` option).
- The quick translation goes through an unofficial Google endpoint (rate-limited), with a MyMemory fallback.

## Offline data (`data/`)

The SQLite databases are **not** versioned (~600 MB). Rebuild them with:

```sh
./setup.sh
```

- **Conjugations** → `build_conjugations.py` (through `verbecc` + `uv`). Standalone.
- **Multitran** → needs the Apple dictionaries
  `~/Library/Dictionaries/multitran_{rufr,frru}.dictionary` (from the Multitran
  `.zip` files). `setup.sh` converts them with `pyglossary`, then runs
  `build_multitran.py`.

Without those databases `dico` still works — only `-m` and `-c` are disabled.

## Files

| File | Role |
|---|---|
| `dico.py` | the tool (zero dependencies) |
| `build_conjugations.py` | builds `data/conjugations.db` |
| `build_multitran.py` | builds `data/multitran.db` (from the converted `.txt` files) |
| `setup.sh` | rebuilds every database |
| `data/` | SQLite databases **(not versioned)** |
