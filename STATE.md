# State

Where dico stands, what blocks, what is next. Updated 2026-09-23.

## Where things live

- `dico.py`: the CLI, REPL, `--json` one-shot and `--serve` loop, one file, standard library only.
- `macos/`: the native popup (SwiftUI, Atelier design). Installed through the Homebrew cask in `mechanicpanic/homebrew-dico`, which points at this repo's releases. `tools/release.sh` writes the cask.
- `desktop/`: the Tauri app for Windows and Linux, built by `.github/workflows/desktop.yml` on every `v*` tag and attached to the release.
- `data/`: offline databases, git-ignored, rebuilt by `./setup.sh`.
- `tests/`: golden outputs of the CLI (`check_goldens.py`), the `--serve` loop (`check_serve.py`), tutor history (`check_history.py`). `desktop/test/smoke.mjs` drives the Tauri UI headless against the real CLI.
- The card store is a separate private git repo, pointed at by `store_path` in `~/.dico_config.json`. Tests never write to it: they run under a temporary `HOME`, `DICO_STORE` and `DICO_VOCAB`.

## Now

- Last release: **1.0.6** (macOS DMG and zip, Windows exe and msi, Linux deb and AppImage).
- Branch **`session-refactor`**, pushed, not merged. It holds the whole refactor planned in `docs/session-refactor.md`: one `Session` driver for the REPL, CLI and `--json`; results as data with one printer; one card-direction rule (`decide_direction`); `dico --serve`; tutor history. Also a 2 s budget on the card's Tatoeba example (slow lookups of new English words).
- The macOS app runs the checkout's `dico.py` before its bundled copy, so whichever branch is checked out is what the installed app runs.

## Before merging `session-refactor`

- Rebuild the macOS app from the branch and run its `--selftest`. Only with the owner's go-ahead: the app is in daily use.
- Use the REPL by hand for a while; the goldens cover fixed queries, not habits.
- Give the "Unreleased" section of `CHANGELOG.md` a version number when it ships.

## Next

- Switch the Swift and Tauri clients to one `dico --serve` process instead of a spawn per call.
- Let the card render before its Tatoeba example arrives (a second request, natural once on `--serve`).
- Windows: selection lookup; code signing is not planned (SmartScreen shows "unknown publisher").
- The stray public repo `mechanicpanic/dico-releases` is unused and should be deleted by the owner.

## Conventions

Until an `AGENTS.md` exists:

- English for docs, commits, help and UI. French only where it is the content: definitions (Wiktionnaire), tense and POS labels, tutor answers.
- French input is accent-tolerant everywhere: `etre` finds `être`.
- This repo is public. No side repos for distribution; releases live here.
- The `--json` schema is a contract with both apps: change it only with the goldens updated in the same commit.
- Never restart or rebuild the owner's running app without asking. Subagents never send keystrokes or clicks to the owner's screen; GUIs are verified offscreen (`--shots`, `--selftest`, jsdom).
