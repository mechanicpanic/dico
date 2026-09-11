# Dico — the panel for Windows (and Linux)

The macOS app is native SwiftUI (`../macos`). This is the same panel for the
other desktops: a [Tauri](https://tauri.app) shell around a plain HTML front
end (`ui/`), in the Atelier design, driving the CLI exactly the way the Mac
app does — `dico --json …` as a child process.

**Windows users need nothing else.** The installer carries the CLI frozen with
PyInstaller and the offline data; the data is unpacked to `~/.dico/data` on
first run. Alt+D opens the panel from any app; the tray icon has Open and Quit.

## Build it yourself

```sh
cd desktop && npm ci
npx tauri dev            # runs ../dico.py on the system python3
npx tauri build          # installers under src-tauri/target/release/bundle
```

For a Windows build without Python installed on the target, freeze the CLI
first (`pyinstaller --onedir --name dico dico.py`, output into
`desktop/src-tauri/cli/`); `.github/workflows/desktop.yml` does exactly that on
every `v*` tag and attaches the installers to the GitHub release.
