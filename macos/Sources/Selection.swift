import AppKit
import ApplicationServices

// MARK: - The selected text of whichever app is in front
//
// Two routes, both behind the Accessibility permission:
//   1. the Accessibility API — the focused element's kAXSelectedText. Works in
//      native apps, Safari, Chrome, Terminal, Preview… and leaves the
//      clipboard alone;
//   2. a simulated ⌘C, when 1. gives nothing (some Electron apps). The previous
//      clipboard contents are put back afterwards.
// Without the permission `grab()` returns nil at once and ⌥D just opens the
// panel — nothing is asked for until the user flips the switch in Settings.

enum Selection {
    static let configKey = "popup_selection"

    /// The permission, without prompting.
    static var trusted: Bool { AXIsProcessTrusted() }

    /// Asks macOS to show the permission prompt (once), and opens the pane.
    static func requestAccess() {
        let opts = [kAXTrustedCheckOptionPrompt.takeUnretainedValue() as String: true] as CFDictionary
        _ = AXIsProcessTrustedWithOptions(opts)
        if let url = URL(string: "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility") {
            NSWorkspace.shared.open(url)
        }
    }

    /// The feature is on unless the config says otherwise.
    static func enabled(in raw: [String: Any]) -> Bool {
        if let b = raw[configKey] as? Bool { return b }
        if let n = raw[configKey] as? NSNumber { return n.boolValue }
        return true
    }

    /// The selection in the frontmost app, normalised — or nil.
    /// Must be called BEFORE the panel takes focus.
    static func grab() -> String? {
        guard trusted else { return nil }
        if let s = normalize(viaAccessibility()) { return s }
        return normalize(viaCopy())
    }

    // MARK: Route 1 — Accessibility API

    private static func viaAccessibility() -> String? {
        let system = AXUIElementCreateSystemWide()
        var focused: CFTypeRef?
        guard AXUIElementCopyAttributeValue(system, kAXFocusedUIElementAttribute as CFString, &focused) == .success,
              let element = focused else { return nil }
        var value: CFTypeRef?
        let ax = element as! AXUIElement
        if AXUIElementCopyAttributeValue(ax, kAXSelectedTextAttribute as CFString, &value) == .success,
           let s = value as? String, !s.isEmpty {
            return s
        }
        return nil
    }

    // MARK: Route 2 — ⌘C, clipboard restored

    private static func viaCopy() -> String? {
        let pb = NSPasteboard.general
        let before = pb.changeCount
        let saved = pb.string(forType: .string)

        guard let src = CGEventSource(stateID: .combinedSessionState),
              let down = CGEvent(keyboardEventSource: src, virtualKey: 8, keyDown: true),   // kVK_ANSI_C
              let up = CGEvent(keyboardEventSource: src, virtualKey: 8, keyDown: false) else { return nil }
        down.flags = .maskCommand
        up.flags = .maskCommand
        down.post(tap: .cghidEventTap)
        up.post(tap: .cghidEventTap)

        // Give the other app a moment to serve the copy.
        let deadline = Date().addingTimeInterval(0.25)
        while pb.changeCount == before && Date() < deadline {
            RunLoop.current.run(mode: .default, before: Date().addingTimeInterval(0.02))
        }
        guard pb.changeCount != before else { return nil }
        let text = pb.string(forType: .string)

        pb.clearContents()
        if let saved { pb.setString(saved, forType: .string) }
        return text
    }

    // MARK: Shape

    /// One line, trimmed, punctuation around it dropped, capped — or nil when
    /// there is nothing worth looking up (empty, a URL, a wall of text).
    static func normalize(_ raw: String?) -> String? {
        guard var s = raw?.trimmingCharacters(in: .whitespacesAndNewlines), !s.isEmpty else { return nil }
        if let firstLine = s.split(whereSeparator: \.isNewline).first { s = String(firstLine) }
        s = s.replacingOccurrences(of: "\\s+", with: " ", options: .regularExpression)
        s = s.trimmingCharacters(in: CharacterSet(charactersIn: "\"'«»“”‘’(),;:.!?…-–—[]{}").union(.whitespaces))
        guard !s.isEmpty, s.count <= 200, !s.contains("://") else { return nil }
        return s
    }

    /// Which panel mode a selection should run in: up to 4 words → the card;
    /// a longer French-looking sentence → grammar; otherwise the card (which
    /// translates an EN/RU sentence).
    static func mode(for text: String) -> Mode {
        let words = text.split(separator: " ")
        guard words.count >= 5 else { return .mot }
        if text.range(of: "[\\u0400-\\u04FF]", options: .regularExpression) != nil { return .mot }
        return looksFrench(text) ? .grammaire : .mot
    }

    private static let frenchMarkers: Set<String> = [
        "le", "la", "les", "un", "une", "des", "du", "de", "et", "est", "sont", "à", "au", "aux",
        "je", "tu", "il", "elle", "on", "nous", "vous", "ils", "elles", "ne", "pas", "que", "qui",
        "ce", "cette", "ces", "mon", "ma", "mes", "son", "sa", "ses", "pour", "avec", "dans", "sur",
        "mais", "ou", "où", "très", "plus", "moi", "toi", "lui", "y", "en", "j'ai", "c'est", "n'est",
    ]

    static func looksFrench(_ text: String) -> Bool {
        if text.range(of: "[àâçéèêëîïôûùüÿœ]", options: .regularExpression) != nil { return true }
        let words = text.lowercased().split(separator: " ").map(String.init)
        let hits = words.filter { frenchMarkers.contains($0) }.count
        return Double(hits) / Double(max(words.count, 1)) >= 0.25
    }
}

// MARK: - The "Look up in Dico" service (right-click ▸ Services — no permission)

final class DicoServices: NSObject {
    var onText: ((String) -> Void)?

    @objc func lookUp(_ pboard: NSPasteboard, userData: String,
                      error: AutoreleasingUnsafeMutablePointer<NSString>) {
        guard let text = Selection.normalize(pboard.string(forType: .string)) else {
            error.pointee = "Nothing to look up"
            return
        }
        onText?(text)
    }
}
