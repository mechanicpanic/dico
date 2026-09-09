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
            .init(keys: globalHotkey, what: "Open / close the panel, from any app", group: "Panel"),
            .init(keys: globalHotkey + " + selection", what: "Look up the text selected in the front app", group: "Panel"),
            .init(keys: "⌘V · ⌘C · ⌘A", what: "Paste, copy, select all in the field", group: "Panel"),
            .init(keys: "Esc", what: "Clear the field and the results — again to close", group: "Panel"),
            .init(keys: "⌘K", what: "Clear the field", group: "Panel"),
            .init(keys: "⌘,", what: "Settings", group: "Panel"),
            .init(keys: "⌘/", what: "Show this list", group: "Panel"),
            .init(keys: "⌘W", what: "Close the panel", group: "Panel"),

            .init(keys: "⌘⇧1", what: "Word mode 📖", group: "Modes"),
            .init(keys: "⌘⇧2", what: "Conjugate mode 🔁", group: "Modes"),
            .init(keys: "⌘⇧3", what: "Grammar mode ✅", group: "Modes"),
            .init(keys: "⌘⇧4", what: "X-ray mode 🔬", group: "Modes"),
            .init(keys: "⌘⇧5", what: "Ask mode 💬", group: "Modes"),

            .init(keys: "⌘1…⌘9", what: "Save sense N of the card", group: "Word card"),
            .init(keys: "⌘D", what: "Definitions (Wiktionary)", group: "Word card"),
            .init(keys: "⌘R", what: "Russian (Multitran)", group: "Word card"),
            .init(keys: "⌘E", what: "Examples (Tatoeba)", group: "Word card"),
            .init(keys: "⌘J", what: "Conjugate — on a verb card", group: "Word card"),
            .init(keys: "⌘L", what: "Ask the tutor about this word", group: "Word card"),
            .init(keys: "⌘P", what: "Hear the word said by a native speaker", group: "Word card"),

            .init(keys: "⌘⇧C", what: "Copy the corrected sentence", group: "Grammar"),
        ]
    }

    /// In the order the sheet shows them.
    static let groups = ["Panel", "Modes", "Word card", "Grammar"]

    @MainActor static func grouped() -> [(String, [Shortcut])] {
        let list = all()
        return groups.compactMap { g in
            let items = list.filter { $0.group == g }
            return items.isEmpty ? nil : (g, items)
        }
    }
}

// MARK: - The ⌘/ sheet

/// A compact two-column list of every shortcut, over the panel.
struct ShortcutsSheet: View {
    let close: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack {
                Text("⌨︎ Shortcuts").font(rounded(14, .bold))
                Spacer()
                Button(action: close) {
                    Image(systemName: "xmark.circle.fill").foregroundStyle(.tertiary)
                }
                .buttonStyle(.plain)
                .help("Close (Esc)")
            }
            .padding(.horizontal, 14).padding(.top, 12).padding(.bottom, 8)
            Divider().opacity(0.3)
            ScrollView {
                ShortcutsList(columns: 2)
                    .padding(.horizontal, 14).padding(.vertical, 11)
            }
        }
        .frame(width: PanelSize.width - 60, height: PanelSize.height - 70)
        .background(.ultraThickMaterial, in: RoundedRectangle(cornerRadius: 14, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: 14, style: .continuous)
                .strokeBorder(Color.primary.opacity(0.12), lineWidth: 1)
        )
        .shadow(radius: 18, y: 6)
    }
}

/// The catalogue, rendered — shared by the ⌘/ sheet and the Settings tab.
struct ShortcutsList: View {
    var columns: Int = 1

    var body: some View {
        let grouped = Shortcuts.grouped()
        if columns > 1 {
            let half = (grouped.count + 1) / 2
            HStack(alignment: .top, spacing: 18) {
                column(Array(grouped.prefix(half)))
                column(Array(grouped.dropFirst(half)))
            }
        } else {
            column(grouped)
        }
    }

    private func column(_ groups: [(String, [Shortcut])]) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            ForEach(groups, id: \.0) { name, items in
                VStack(alignment: .leading, spacing: 4) {
                    Text(name.uppercased())
                        .font(rounded(9, .bold)).foregroundStyle(.tertiary).tracking(0.7)
                    ForEach(items) { s in
                        HStack(alignment: .firstTextBaseline, spacing: 8) {
                            Text(s.keys)
                                .font(.system(size: 10.5, weight: .semibold, design: .rounded))
                                .frame(width: 58, alignment: .leading)
                                .padding(.horizontal, 5).padding(.vertical, 2)
                                .background(Color.primary.opacity(0.08),
                                            in: RoundedRectangle(cornerRadius: 5))
                            Text(s.what).font(rounded(11, .regular)).foregroundStyle(.secondary)
                                .fixedSize(horizontal: false, vertical: true)
                            Spacer(minLength: 0)
                        }
                    }
                }
            }
            Spacer(minLength: 0)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}
