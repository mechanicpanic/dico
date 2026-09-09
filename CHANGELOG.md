# Changelog

## 1.0.0 — 2026-09-09

The first release: a French dictionary for a Russian/English speaker, as a CLI
and a macOS popup.

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
