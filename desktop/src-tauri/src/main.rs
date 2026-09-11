// Dico — the panel, for Windows (and Linux, and macOS if you like).
//
// A thin shell around the CLI: the front end is plain HTML in ui/, every
// lookup is `dico --json …` run as a child process — the same contract the
// native macOS app uses. On Windows the CLI is a PyInstaller build shipped
// in resources/dico-cli; elsewhere dico.py runs on the system python3.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::path::{Path, PathBuf};
use std::process::Command;
use tauri::menu::{Menu, MenuItem};
use tauri::tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent};
use tauri::{AppHandle, Emitter, Manager, PhysicalPosition, WebviewWindow};
use tauri_plugin_global_shortcut::{Code, GlobalShortcutExt, Modifiers, Shortcut, ShortcutState};

/// ~/.dico — where the data is unpacked to and the cache, audio and config live.
fn dico_home() -> PathBuf {
    dirs::home_dir().unwrap_or_else(|| PathBuf::from(".")).join(".dico")
}

/// The bundled data (Lexique, conjugations, Grammalecte), copied once into
/// ~/.dico/data: the install folder is read-only and the CLI writes next to it.
fn seed_data(resources: &Path) -> PathBuf {
    let dest = dico_home().join("data");
    let src = resources.join("data");
    if !dest.join("lexique.db").exists() && src.join("lexique.db").exists() {
        let _ = copy_dir(&src, &dest);
    }
    dest
}

fn copy_dir(src: &Path, dest: &Path) -> std::io::Result<()> {
    std::fs::create_dir_all(dest)?;
    for entry in std::fs::read_dir(src)? {
        let entry = entry?;
        let target = dest.join(entry.file_name());
        if entry.file_type()?.is_dir() {
            copy_dir(&entry.path(), &target)?;
        } else if !target.exists() {
            std::fs::copy(entry.path(), &target)?;
        }
    }
    Ok(())
}

/// The CLI: (program, leading args). Frozen build first, then dico.py on a
/// python3 — the checkout's copy in development.
fn resolve_cli(resources: &Path) -> Option<(PathBuf, Vec<String>)> {
    let exe = resources.join("dico-cli").join(if cfg!(windows) { "dico.exe" } else { "dico" });
    if exe.exists() {
        return Some((exe, vec![]));
    }
    let mut scripts = vec![resources.join("dico.py")];
    scripts.push(PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../dico.py"));
    let pythons: &[&str] = if cfg!(windows) { &["python", "python3", "py"] } else { &["python3", "/usr/bin/python3", "/opt/homebrew/bin/python3"] };
    for s in scripts {
        if s.exists() {
            for py in pythons {
                if which(py).is_some() || Path::new(py).exists() {
                    return Some((PathBuf::from(py), vec![s.to_string_lossy().into_owned()]));
                }
            }
        }
    }
    None
}

fn which(name: &str) -> Option<PathBuf> {
    if name.contains('/') || name.contains('\\') {
        return Path::new(name).exists().then(|| PathBuf::from(name));
    }
    let path = std::env::var_os("PATH")?;
    for dir in std::env::split_paths(&path) {
        for cand in [dir.join(name), dir.join(format!("{name}.exe"))] {
            if cand.is_file() {
                return Some(cand);
            }
        }
    }
    None
}

/// `dico --json …` → its stdout. Every lookup the panel makes goes through here.
#[tauri::command]
fn dico(app: AppHandle, args: Vec<String>) -> Result<String, String> {
    let resources = app.path().resource_dir().unwrap_or_else(|_| PathBuf::from("."));
    let data = seed_data(&resources);
    let (program, prefix) = resolve_cli(&resources)
        .ok_or_else(|| "dico is not installed: neither dico-cli nor dico.py + python3 were found".to_string())?;
    let mut cmd = Command::new(program);
    cmd.args(prefix).args(&args);
    cmd.env("DICO_HOME", dico_home());
    if data.join("lexique.db").exists() {
        cmd.env("DICO_DATA", &data);
    }
    cmd.env("PYTHONIOENCODING", "utf-8");
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        cmd.creation_flags(0x0800_0000); // CREATE_NO_WINDOW: no console flashing
    }
    let out = cmd.output().map_err(|e| format!("cannot run dico: {e}"))?;
    let stdout = String::from_utf8_lossy(&out.stdout).into_owned();
    if !out.status.success() && stdout.trim().is_empty() {
        let err = String::from_utf8_lossy(&out.stderr);
        return Err(err.lines().last().unwrap_or("dico failed").to_string());
    }
    Ok(stdout)
}

/// Show the panel on the monitor the mouse is on, centred there.
fn show_panel(window: &WebviewWindow) {
    if let (Ok(cursor), Ok(monitors)) = (window.app_handle().cursor_position(), window.available_monitors()) {
        let monitor = monitors
            .into_iter()
            .find(|m| {
                let p = m.position();
                let s = m.size();
                cursor.x >= p.x as f64 && cursor.x < (p.x + s.width as i32) as f64
                    && cursor.y >= p.y as f64 && cursor.y < (p.y + s.height as i32) as f64
            })
            .or_else(|| window.primary_monitor().ok().flatten());
        if let (Some(m), Ok(size)) = (monitor, window.outer_size()) {
            let p = m.position();
            let s = m.size();
            let x = p.x + (s.width as i32 - size.width as i32) / 2;
            let y = p.y + (s.height as i32 - size.height as i32) / 2 - (s.height as i32) / 10;
            let _ = window.set_position(PhysicalPosition::new(x, y));
        }
    }
    let _ = window.show();
    let _ = window.set_focus();
    let _ = window.emit("dico:shown", ());
}

fn toggle_panel(app: &AppHandle) {
    if let Some(w) = app.get_webview_window("main") {
        if w.is_visible().unwrap_or(false) {
            let _ = w.hide();
        } else {
            show_panel(&w);
        }
    }
}

#[tauri::command]
fn hide(window: WebviewWindow) {
    let _ = window.hide();
}

#[tauri::command]
fn resize(window: WebviewWindow, width: f64, height: f64) {
    let _ = window.set_size(tauri::LogicalSize::new(width, height));
}

fn main() {
    tauri::Builder::default()
        .plugin(tauri_plugin_global_shortcut::Builder::new().build())
        .invoke_handler(tauri::generate_handler![dico, hide, resize])
        .setup(|app| {
            // Alt+D anywhere — the same key as the macOS app.
            let hotkey = Shortcut::new(Some(Modifiers::ALT), Code::KeyD);
            let handle = app.handle().clone();
            // Another app may hold Alt+D (the native Dico, say): the tray still works.
            if let Err(e) = app.global_shortcut().on_shortcut(hotkey, move |_app, _sc, event| {
                if event.state == ShortcutState::Pressed {
                    toggle_panel(&handle);
                }
            }) {
                eprintln!("Alt+D not registered: {e}");
            }

            // The tray: Open · Quit; a left click toggles.
            let open = MenuItem::with_id(app, "open", "Open  (Alt+D)", true, None::<&str>)?;
            let quit = MenuItem::with_id(app, "quit", "Quit", true, None::<&str>)?;
            let menu = Menu::with_items(app, &[&open, &quit])?;
            TrayIconBuilder::new()
                .icon(app.default_window_icon().cloned().expect("icon"))
                .menu(&menu)
                .show_menu_on_left_click(false)
                .on_menu_event(|app, e| match e.id.as_ref() {
                    "open" => toggle_panel(app),
                    "quit" => app.exit(0),
                    _ => {}
                })
                .on_tray_icon_event(|tray, event| {
                    if let TrayIconEvent::Click { button: MouseButton::Left, button_state: MouseButtonState::Up, .. } = event {
                        toggle_panel(tray.app_handle());
                    }
                })
                .build(app)?;

            // Click away: the panel hides when it loses focus.
            if let Some(w) = app.get_webview_window("main") {
                let w2 = w.clone();
                w.on_window_event(move |e| {
                    if let tauri::WindowEvent::Focused(false) = e {
                        let _ = w2.hide();
                    }
                });
                // `--show`: open the panel straight away (first run, demos).
                if std::env::args().any(|a| a == "--show") {
                    show_panel(&w);
                }
            }
            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while running Dico");
}
