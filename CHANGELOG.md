# Changelog

## 1.0.5 — unreleased

- **Windows (and Linux).** `desktop/` is the same panel as a Tauri app: a
  plain HTML front end in the Atelier design driving the CLI, with Alt+D, a
  tray icon, every mode, the Cards review and the settings sheet. The Windows
  installer carries the CLI frozen with PyInstaller and the offline data, so
  the person installing it needs nothing else. Built on GitHub Actions for
  every tag; `npm test` renders every mode off screen against the real CLI.
- The CLI plays audio on Windows through the default player.

## 1.0.4 — 2026-09-11

- A Russian word whose Google entry carries no back-translations
  (« государство ») crashed the parser and the panel showed an empty card.
  The parser copes, and a lookup that fails now shows its error in the panel
  instead of a blank card.

## 1.0.3 — 2026-09-11

- **Homebrew, fixed.** The `dico` command Homebrew links followed its own
  symlink to the wrong folder, and the app preferred that link over its own
  bundled script — so a brew-installed Dico could not look anything up. The
  launcher now resolves the link; the app uses its bundle before anything on
  PATH. The cask clears the quarantine flag after installing (Homebrew 6
  dropped `--no-quarantine`), so the first launch is not blocked.
- The panel opens on the screen the mouse is on.

## 1.0.2 — 2026-09-10

- **Homebrew.** `brew install --cask mechanicpanic/dico/dico` installs the app
  and the `dico` command; `brew upgrade` keeps them current. The tap is
  `mechanicpanic/homebrew-dico`, updated by the release script; the cask
  points at the release zip on this repository.
- The CLI ships inside the app (`Dico.app/Contents/Resources/bin/dico`) and
  uses the data the app unpacks.

## 1.0.1 — 2026-09-10

- **Size.** Settings ▸ General ▸ Size (Small · Default · Large · Larger), or
  ⌘+ / ⌘− / ⌘0 in the panel: the panel and its type scale together, so a big
  display gets a bigger panel with bigger type — crisp, not a stretched bitmap.
  Stored as `popup_zoom`.

## 1.0.0 — 2026-09-10

The first release: a French dictionary for a Russian/English speaker, as a CLI
and a macOS popup — with the popup designed, the cards reviewed inside it, and
the deck kept in git.

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
  (ACCORD, ORTHO.…), the correction sits in a green card with ⌘⇧C. X-ray lays
  the sentence out interlinear — a tile per word with its part of speech,
  gender and gloss underneath; click one for lemma, tense and role, « Look
  up » and « save ». English or Russian typed into Grammar or X-ray is
  translated first and the French is analysed, with both shown. The ⌘/ sheet and the five Settings tabs got the same
  language.
- `Dico --shots DIR` renders every screen, dark and light, to PNG — off
  screen, for design review.

### 🎴 Cards — every saved word is a card
- A sixth mode reviews the words dico saved: the front in serif, Space or ⏎
  for the answer, 1–4 or the buttons to grade. dico schedules them itself
  (an Anki-style SM-2: two learning steps, then intervals stretched by an
  ease that Again/Hard/Easy nudge), and keeps the state in its own store —
  no other app needed. `dico --review` does the same in the terminal;
  `--json --due` and `--json --grade KEY --ease N` are what the panel uses.
- **What a card holds.** Front: the word with its article, gender, IPA,
  CEFR level and part of speech. Back: an English gloss (fetched when what
  you typed was French, kept beside the Russian when that is how you got
  there), then a real example sentence and its translation — the card's own
  when the lookup had one, Tatoeba otherwise. `dico --enrich` backfills all
  of this on the words saved before.
- **The empty screen is yours.** Once there is a history it shows today's
  cards (« 20 cards to review — 0 due · 3 learning · 331 new », Review),
  the words saved lately with their gloss, and the recent searches. The
  four « try one » examples only greet a first run.
- **The cards live in git.** Settings ▸ Vocabulary ▸ Backup ▸ « Turn on »
  (or `dico --backup-init [URL]`) moves the store into a folder of its own,
  makes it a repository and, given the address of an empty remote, pushes
  it. Then `dico --backup` pulls what other sources wrote, renders
  `vocabulaire.md`, commits and pushes; `dico --pull` only pulls. The app
  pulls at launch and backs up 20 s after a save (a minute after a grade),
  coalesced — Settings ▸ Vocabulary ▸ Backup switches that off.
- **Anything can become a card.** ⌘S saves what is on screen: the phrase
  in the field, the corrected sentence in Grammar, the tutor's answer in
  Ask (front: the word it was about, back: the answer), sense 1 of a Word
  card. « save » appears on hover on every Examples sentence and every
  X-ray word. `--save-term` takes `--tier phrase|sentence|tutor` so the
  enrichment knows what not to fetch.
- Learning steps come first, then reviews due today, then up to twenty of
  the newest words. « Look it up » opens the Word card for the card on screen.
- **Anki, optionally.** Settings ▸ Vocabulary ▸ Cards can review an Anki
  deck instead, through the AnkiConnect add-on; « push to Anki » exports
  every saved word the deck lacks (front = word, back = meaning + example).
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

