# Changelog

## 0.9.1 — 2026-09-09

Installing it used to mean: get access to the repository, install `uv`, install
the CLI, run `dico --setup` (which needs `uv` again), then build the app. This
release is the one you can hand to a person.

- **Nothing to install.** `Dico.app` carries the dictionary code and the 71 MB
  of offline data (Lexique, conjugations, Grammalecte) inside it, and unpacks
  the databases into `~/.dico/data` the first time it is asked for anything.
  dico is pure standard library and runs on the Python macOS already ships, so
  there is no Python to install, no `uv`, no Terminal and no setup step.
- **A DMG**: drag Dico to Applications, press ⌥D. `READ ME FIRST.txt` explains
  the one-off Gatekeeper block (System Settings ▸ Privacy & Security ▸ Open
  Anyway — Apple removed right-click ▸ Open in macOS 15).
- **A first run that teaches itself**: four examples to click instead of an
  empty box, and a line naming the key that opens the panel from anywhere.
- A checkout still wins over the bundled copy, so a machine with its own data
  directory (with Multitran in it) keeps using that one.
- The self-test reports absent *optional* extras — Multitran, a tutor — as
  skips rather than failures, so a freshly installed machine reads as healthy.

## 1.0.0 — unreleased

The first release: a French dictionary for a Russian/English speaker, as a CLI
and a macOS popup.

### Atelier — the popup, designed
- The panel follows the **Atelier** design (Claude Design, « Dico — 1b
  Atelier » + spec): a rail of modes on the left, the query in a serif, and a
  Word card in **two panes** — headword, senses and example on the left; one
  pane on the right (Definitions, Russian, Examples, Conj.) switched by tabs
  or ⌘D ⌘R ⌘E ⌘J. Nothing pushes: the card's height never changes.
- Three faces: serif (New York) for the French being learned, sans (SF Pro)
  for the interface, mono (SF Mono) for IPA, keys, eyebrows and CLI output.
  Hairlines, not boxes; one accent per screen (bleu, vert for Grammar, rose
  for Russian and Ask); dark and light palettes.
- The conjugation grid is ruled, the **endings in blue**, the auxiliary
  dimmed; ⌘1 saves the infinitive. Grammar notes carry a mono rule label
  (ACCORD, ORTHO.…), the correction sits in a green card with ⌘⇧C. X-ray is a
  six-column table. The ⌘/ sheet and the five Settings tabs got the same
  language.
- `Dico --shots DIR` renders every screen, dark and light, to PNG — off
  screen, for design review.

### 🎴 Cards — Anki, in the panel
- A sixth mode reviews the Anki deck (« Français — Vocabulaire », set in
  Settings ▸ Vocabulary) through the AnkiConnect add-on: the front in serif,
  Space or ⏎ for the answer, 1–4 or the buttons to grade. Anki keeps the
  schedule; nothing touches the collection file. Learning cards come first,
  then due reviews, then up to twenty new ones.
- **Push saved words to Anki** sends every word dico saved that the deck
  does not have yet (front = the word, back = meaning + example), without
  duplicates. « Look it up » opens the Word card for the card on screen.
- When Anki is closed the panel says so and can open it. `dico --paths`
  reports where the config, vocabulary, store and data live.

### Looking things up
- A real **dictionary card**: senses grouped by part of speech and numbered,
  article and gender on every noun, frequency in ★, back-translations, and a
  real example sentence (Tatoeba).
- **No flags in interactive mode.** dico guesses: an EN/RU word gives its card,
  a French word its own (a verb also shows its présent), a French sentence a
  grammar check, `? …` the tutor. Then plain words act on the card: `save N`,
  `conj`, `def`, `ru`, `ex`, `say`, `syn`, `grammar`, `x`, `help`.
- **Accents are never required**: `etre` finds *être*, `creche` finds *crèche*.

### Knowing what you are looking at
- **CEFR level** A1…C2 for 14 236 lemmas (FLELex), next to the frequency band —
  how common a word is for a native and when a learner meets it are different
  questions.
- **IPA offline** for all 142 694 forms, from Lexique's phonetic column.
- **Exact homophones offline**, by grouping on that column: *vert* → *vair ·
  ver · verre · vers*.
- **Native recordings** (`say`): Wikimedia serves an MP3 transcode of every
  Commons `.ogg`, so it plays with no ffmpeg anywhere.
- **Synonyms** with their register (*greffier (familier)*), from the Wiktionnaire.
- **Russian** from Multitran when installed, otherwise from the Wiktionnaire
  with transliteration and gender — no proprietary dictionary needed.
- **Grammar** (Grammalecte, offline) and **x-ray** (lemma, tense, person,
  gender, role) for sentences.
- **Conjugations** for ~7000 verbs, offline, including *doit* → *devoir*.

### Vocabulary
- **Autosave** every lookup into a JSON store (the markdown next to it is a
  regenerated view); curation is subtractive (`dico --forget`). Cards carry the
  gender, lemma, part of speech, CEFR level and IPA into Anki/Obsidian.

### The tutor
- An **OpenAI-compatible endpoint first** (LM Studio / Ollama auto-detected),
  then the Anthropic API, then the `claude` CLI. `dico --llm` sets up a local
  model or your own key.

### macOS popup
- A menu-bar app: **⌥D** anywhere, five modes, every source by click.
- **Look up the selection**: ⌥D with text selected, or right-click ▸ Services ▸
  *Look up in Dico* (no permission needed).
- ⚙︎ **Settings** writing the same `~/.dico_config.json` the CLI uses.
- Its own icon, and a template menu-bar mark that follows dark mode.

### Robustness
- Google blocks `client=gtx` outright (its "Sorry… automated queries" page,
  served as HTTP 429). dico uses `client=dict-chrome-ex`, keeps `gtx` as a
  spare, and falls back to MyMemory if both refuse.
- Every network source is **cached on disk** for 30 days: a repeated lookup
  costs no request and returns in ~0.07 s.
