# Session refactor — one driver, several skins

Branch: `session-refactor`. Goal: separate the REPL's *driver* (what a line
means, what state it touches) from its *printer* (colours, alignment), so the
same driver serves the terminal, the one-shot `--json` flag, and a long-lived
`--serve` mode for the panels. `dico.py` stays one file.

## Today

- `show(word, want_*…)` (≈200 lines) decides *and* prints: it calls
  `_render_card_fr / _render_card_to_fr / _show_wikt / _show_multitran /
  _show_xray / _show_grammar / _show_ai / _conj_lines`, each of which prints.
- `_as_json(text, args)` is a second implementation of the same decisions,
  building a dict. The two drift (e.g. the cognate flag, the "French
  sentence → grammar" auto-routing and the conj-form-of-verb note exist only
  in `show`; `translated`/`source` only in `_as_json`).
- REPL state lives in module globals: `_LAST` (word, fr, sentence, senses,
  hints, conj_shown), `_FALLBACK_NOTE`, `_NO_AUTOSAVE`.
- `interactive()` owns the loop: `:` commands (`_repl_command`), plain-word
  follow-ups (`_follow_up`: save N, conj, def, ru, ex, x, grammar, say, syn),
  `?`/`??` questions, and `show(line)` for the rest.

## Target

```
Session                      # state: last word/fr/sentence/senses, autosave-off flag,
  .handle(line) -> Result    #        tutor history; understands every REPL line
Result = dict                # kind + the same keys _as_json emits today (+ "saved", "note")
render(result) -> [str]      # the terminal printer: colours live ONLY here
loops:
  interactive():  readline → session.handle → print(render(r))
  serve():        stdin JSON line {"id","line"|"args"} → session.handle → stdout JSON line
  --json …:       Session().handle_args(args) → json.dumps (unchanged schema)
```

`Result.kind` ∈ {card_fr, card_to_fr, conjugation, grammar, xray, definition,
multitran, examples, answer, audio, synonyms, saved, setting, help, error}.
Composite lookups (`-c -d` together) return `kind: "card_*"` with the extra
sections under their existing keys (`conjugation`, `definition`, …), exactly
as `_as_json` nests them now.

## Steps (commit after each; `macos/build/Dico.app --selftest` + `desktop
npm test` + the goldens below must pass at every step)

0. ✅ **Goldens.** Before touching anything, capture `--json` output for a fixed
   list of queries into `tests/golden/*.json` (cook, maison, кошка, dire, -c
   dire, -f chat, -m chat, --examples chat, -g "elle est parti", -x "le chat
   dort", --due on a temp store, --grade, --card, --save-term on a temp store)
   and a script `tests/check_goldens.py` that diffs them. Network answers are
   cached on disk (`data/translate_cache.json`), so the goldens are stable
   while the cache is warm; run them with the cache present.
1. ✅ **Session.** Move `_LAST`, `_NO_AUTOSAVE`, `_FALLBACK_NOTE` into a class;
   `show()` and `_as_json()` read/write `self.` instead of globals. No
   behaviour change. `_follow_up`, `_repl_command`, `ai_ask` take the session.
2. ✅ **Results, not prints — one renderer at a time.** For each `_show_*`/
   `_render_*`: split into `x_result(...) -> dict` (the data, reusing what
   `_as_json` already computes) and `render_x(dict) -> [str]` (the exact lines
   printed today). `show()` calls both; `_as_json()` calls only the former.
   Order: grammar, xray, multitran, wikt, conj, card_to_fr, card_fr, ai.
   After this step `_as_json` is a thin wrapper and can be deleted: `--json`
   = `Session.handle_args(args)`.
   *Done as:* every builder returns the JSON section **plus `_`-prefixed keys
   for the terminal only** (`_card`, `_rows`, `_entry`, `_kind`…); `_public()`
   strips them for `--json`, so the schema did not move by a byte. `show()` =
   `lookup_result()` (the composite: card + sections + `saved`) → `render()`.
   `Session.handle_args()` keeps `--json`'s one-section priority. Goldens now
   cover the terminal too (`tests/golden/*.txt`), HOME-isolated.
3. ✅ **handle(line).** Lift `interactive()`'s dispatch (`:`, follow-ups, `?`,
   `!`/`-` hint, plain lookup) into `Session.handle(line)`; `interactive()`
   becomes the readline loop calling it and printing `render(result)`.
   *Done as:* `Session.parse(line)` and `Session.request_from_args(args)`
   each produce a **request** (`{"op": "lookup" | "definition" | "multitran"
   | "synonyms" | "audio" | "examples" | "conj" | "grammar" | "xray" | "ai" |
   "save_sense" | "setting" | "help" | "message", "text", …}`);
   `Session.run(request)` is the one dispatch, `handle(line)` / `handle_args(args)`
   the two entry points. `--json` keeps its one-section priority through
   `request_from_args`; the terminal one-shot gets the composite lookup.
   Audio playback moved out of the driver (`_play_audio`, after `render`).
   **Card direction is decided once**, in `decide_direction(word)` → `"fr"`
   when Lexique has the typed spelling as a *lemma* (accents as typed: « the »
   is not « thé »), a content word (`cgram` ∈ NOM, ADJ, VER, ADV — « car »,
   « pour », « son » stay English) with `freqfilms >= LEXIQUE_FRENCH_MIN`
   (**50** films/million: manger 208, table 111, dire 1565, chat 58 are
   French; chair 36, four 14, go 15 get translated, with the cognate flag);
   otherwise `"to_fr"` — translate first, then the terminal's old cognate
   logic. The accepted cost: frequent French homographs of English words
   (« sale », « pain », « coin », « main », « but ») give the French card.
   Goldens that moved: `dire.txt`, `manger.txt` (French verb cards) and
   `car.json` (« voiture »); the panel's plain lookup also inherits the
   terminal's path for unaccented French words (« ecole » → French card),
   nonsense words (empty French card) and French sentences (grammar).
4. **--serve.** JSON lines over stdin/stdout, one `Session` for the life of
   the process, `cache_flush()` after each request, one bad request must not
   kill it. Then the panels can send either `args` (today's contract) or a
   `line` (the REPL's language) and get the same `Result`.
5. **Tutor history.** With a live session, `ai_ask` keeps the last N
   exchanges in `Session` and sends them as context. Only now: this is the
   feature that justified the work.

## Non-goals

Changing the JSON schema (the Swift and Tauri clients decode it), changing
what the terminal prints (goldens for the printer too if cheap: capture
`dico cook` with `NO_COLOR`), touching the SRS/backup/enrich commands.

## Traps seen on the way

- A scratch store needs `DICO_VOCAB` as well as `DICO_STORE`: `store_upsert()`
  calls `store_render()`, which writes the markdown next to the vocab path —
  with only `DICO_STORE` set, `vocabulaire.md` inside the repo gets rewritten.
- A `conj` follow-up runs `show(session, fr, want_conj=True)`, which overwrites
  `session.last["word"]` with the French verb: after `cook` → `conj`, the
  tutor's context says « cuisiner », not « cook ». Kept as is (no behaviour
  change); decide in step 3 whether follow-ups should leave `last` alone.
- The two drivers used to decide the card's direction differently and each
  won some cases (`--json`: `manger` right, `car` wrong; the terminal: the
  reverse). Step 3 settled it in `decide_direction()` — see step 3 for the
  rule and the threshold; goldens `manger`, `car`, `table`, `chat`, `dire`,
  `cook` pin it in both modes.
- `tests/check_goldens.py -k` takes exact names (a comma list): a substring
  match once re-recorded `card` while asked for `car`.
- `Result.kind` is `_kind` for now: a public `kind` would be a schema change
  for the one-shot `--json`; `--serve` (step 4) can expose it in its envelope.
- `ai_result(progress=…)`: the « thinking… » line is a callback the terminal
  passes and `--serve` will not — so builders never print.
- Goldens must run with `HOME` pointed at the scratch dir: `~/.dico_config.json`
  has no env override, and with the user's `autosave: true` every terminal
  lookup writes (« seen before ×2 » on the second run).

- `translate_rich` mutates `_FALLBACK_NOTE`; reset it per request.
- `_render_card_to_fr` sets `_LAST["senses"]` (what `save N` uses) — the
  result must carry `senses` so the session can keep it.
- `show()`'s autosave block builds the store record from the *rendered*
  card's data (entry/lex); keep it as `save_from_card(result)`.
- `_show_ai` prints a "thinking…" line with `\r`; in `--serve` that is noise.
