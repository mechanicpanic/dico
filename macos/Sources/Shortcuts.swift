import SwiftUI

// MARK: - Every keyboard shortcut, in one place
//
// The catalogue is the single source of truth: the ⌘/ sheet, the Settings
// list and the `.help()` tooltips all read from it, so nothing can drift.

struct Shortcut: Identifiable, Hashable {
    let keys: String
    let what: String
    var group: String = ""
    var id: String { group + keys + what }
}

enum Shortcuts {
    /// The configured global hotkey, as text — the footer and the list show it.
    @MainActor static var globalHotkey: String {
        HotkeyChoice.from(ConfigStore.readRaw(at: ConfigPath.current)["popup_hotkey"] as? String).display
    }

    @MainActor static func all() -> [Shortcut] {
        [
            .init(keys: globalHotkey, what: "Open / close, from any app", group: "Panel"),
            .init(keys: globalHotkey + " + selection", what: "Look up the selection", group: "Panel"),
            .init(keys: "⌘V · ⌘C · ⌘A", what: "Paste, copy, select all", group: "Panel"),
            .init(keys: "Esc", what: "Clear — again to close", group: "Panel"),
            .init(keys: "⌘K", what: "Clear the field", group: "Panel"),
            .init(keys: "⌘,", what: "Settings", group: "Panel"),
            .init(keys: "⌘/", what: "This list", group: "Panel"),
            .init(keys: "⌘W", what: "Close the panel", group: "Panel"),

            .init(keys: "⌘⇧1", what: "📖 Word", group: "Modes"),
            .init(keys: "⌘⇧2", what: "🔁 Conjugate", group: "Modes"),
            .init(keys: "⌘⇧3", what: "✅ Grammar", group: "Modes"),
            .init(keys: "⌘⇧4", what: "🔬 X-ray", group: "Modes"),
            .init(keys: "⌘⇧5", what: "💬 Ask", group: "Modes"),
            .init(keys: "⌘⇧6", what: "🎴 Cards", group: "Modes"),

            .init(keys: "⌘1…⌘9", what: "Save sense N", group: "Word card"),
            .init(keys: "⌘D", what: "Definitions — Wiktionary", group: "Word card"),
            .init(keys: "⌘R", what: "Russian — Multitran", group: "Word card"),
            .init(keys: "⌘E", what: "Examples — Tatoeba", group: "Word card"),
            .init(keys: "⌘J", what: "Conjugate — verbs", group: "Word card"),
            .init(keys: "⌘L", what: "Ask the tutor about it", group: "Word card"),
            .init(keys: "⌘P", what: "Hear it said", group: "Word card"),

            .init(keys: "⌘⇧C", what: "Copy the corrected sentence", group: "Grammar"),

            .init(keys: "Space · ⏎", what: "Show the answer — then Good", group: "Cards"),
            .init(keys: "1 · 2 · 3 · 4", what: "Again · Hard · Good · Easy", group: "Cards"),
        ]
    }

    /// In the order the sheet shows them.
    static let groups = ["Panel", "Modes", "Word card", "Grammar", "Cards"]

    /// The eyebrow of each group takes the accent of what it drives.
    static func tint(_ group: String) -> Color {
        switch group {
        case "Word card": return Palette.roseInk
        case "Grammar": return Palette.vertInk
        case "Cards": return Palette.jauneInk
        default: return Palette.bleuInk
        }
    }

    @MainActor static func grouped() -> [(String, [Shortcut])] {
        let list = all()
        return groups.compactMap { g in
            let items = list.filter { $0.group == g }
            return items.isEmpty ? nil : (g, items)
        }
    }
}

// MARK: - The ⌘/ sheet

/// 548 × 400 over a scrim: every shortcut in two columns.
struct ShortcutsSheet: View {
    let close: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack(alignment: .firstTextBaseline, spacing: 10) {
                Text("Shortcuts").font(serif(20)).foregroundStyle(Palette.ink)
                Text("every key the panel listens to").font(sans(11)).foregroundStyle(Palette.ink(0.35))
                Spacer(minLength: 0)
                Button(action: close) {
                    Text("Esc to close").font(mono(10)).foregroundStyle(Palette.ink(0.30))
                }
                .buttonStyle(.plain)
                .help("Close (Esc)")
            }
            .padding(.bottom, 14)
            ScrollView(showsIndicators: false) {
                ShortcutsList(columns: 2, keyWidth: 76, keySize: 10, whatSize: 11.5, groupGap: 12)
            }
            Spacer(minLength: 0)
            Text("The hotkey shown is the one set in Settings ▸ General.")
                .font(sans(11)).foregroundStyle(Palette.ink(0.30))
        }
        .padding(.horizontal, 20).padding(.vertical, 18)
        .frame(width: 548, height: 400)
        .background(Palette.sheet, in: RoundedRectangle(cornerRadius: 14, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: 14, style: .continuous)
                .strokeBorder(Palette.ink(0.10), lineWidth: 1)
        )
        .shadow(color: .black.opacity(0.5), radius: 22, y: 10)
    }
}

/// The catalogue, rendered — shared by the ⌘/ sheet and the Settings tab.
struct ShortcutsList: View {
    var columns: Int = 1
    var keyWidth: CGFloat = 78
    var keySize: CGFloat = 10.5
    var whatSize: CGFloat = 12
    var groupGap: CGFloat = 16

    var body: some View {
        let grouped = Shortcuts.grouped()
        if columns > 1 {
            // Panel + Modes on the left; what the results listen to on the right.
            HStack(alignment: .top, spacing: 26) {
                column(Array(grouped.prefix(2)))
                column(Array(grouped.dropFirst(2)))
            }
        } else {
            column(grouped)
        }
    }

    private func column(_ groups: [(String, [Shortcut])]) -> some View {
        VStack(alignment: .leading, spacing: groupGap) {
            ForEach(groups, id: \.0) { name, items in
                VStack(alignment: .leading, spacing: 4) {
                    Eyebrow(name, tint: Shortcuts.tint(name))
                    ForEach(items) { s in
                        HStack(alignment: .firstTextBaseline, spacing: 10) {
                            Text(s.keys).font(mono(keySize)).foregroundStyle(Palette.ink(0.85))
                                .frame(width: keyWidth, alignment: .leading)
                                .lineLimit(1).minimumScaleFactor(0.7)
                            Text(s.what).font(sans(whatSize)).foregroundStyle(Palette.ink(0.55))
                                .fixedSize(horizontal: false, vertical: true)
                            Spacer(minLength: 0)
                        }
                    }
                }
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}
