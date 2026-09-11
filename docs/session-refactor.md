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

0. **Goldens.** Before touching anything, capture `--json` output for a fixed
   list of queries into `tests/golden/*.json` (cook, maison, кошка, dire, -c
   dire, -f chat, -m chat, --examples chat, -g "elle est parti", -x "le chat
   dort", --due on a temp store, --grade, --card, --save-term on a temp store)
   and a script `tests/check_goldens.py` that diffs them. Network answers are
   cached on disk (`data/translate_cache.json`), so the goldens are stable
   while the cache is warm; run them with the cache present.
1. **Session.** Move `_LAST`, `_NO_AUTOSAVE`, `_FALLBACK_NOTE` into a class;
   `show()` and `_as_json()` read/write `self.` instead of globals. No
   behaviour change. `_follow_up`, `_repl_command`, `ai_ask` take the session.
2. **Results, not prints — one renderer at a time.** For each `_show_*`/
   `_render_*`: split into `x_result(...) -> dict` (the data, reusing what
   `_as_json` already computes) and `render_x(dict) -> [str]` (the exact lines
   printed today). `show()` calls both; `_as_json()` calls only the former.
   Order: grammar, xray, multitran, wikt, conj, card_to_fr, card_fr, ai.
   After this step `_as_json` is a thin wrapper and can be deleted: `--json`
   = `Session.handle_args(args)`.
3. **handle(line).** Lift `interactive()`'s dispatch (`:`, follow-ups, `?`,
   `!`/`-` hint, plain lookup) into `Session.handle(line)`; `interactive()`
   becomes the readline loop calling it and printing `render(result)`.
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

- `translate_rich` mutates `_FALLBACK_NOTE`; reset it per request.
- `_render_card_to_fr` sets `_LAST["senses"]` (what `save N` uses) — the
  result must carry `senses` so the session can keep it.
- `show()`'s autosave block builds the store record from the *rendered*
  card's data (entry/lex); keep it as `save_from_card(result)`.
- `_show_ai` prints a "thinking…" line with `\r`; in `--serve` that is noise.
