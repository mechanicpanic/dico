import Foundation
import Carbon.HIToolbox

// MARK: - ~/.dico_config.json — the SAME file the CLI reads and writes
//
// The store keeps the raw dictionary around so unknown keys written by the CLI
// (or by a future version of it) survive a round trip. It is written
// atomically and chmod-600, because it may hold an API key.

/// Where the config lives. Injectable, so `--selftest` can round-trip a temp file.
enum ConfigPath {
    static let userDefault = NSHomeDirectory() + "/.dico_config.json"

    /// `DICO_CONFIG_PATH` is honoured by THIS app only (the CLI always uses
    /// `~/.dico_config.json`); it exists so the self-test never touches the
    /// user's real settings.
    static var current: String {
        ProcessInfo.processInfo.environment["DICO_CONFIG_PATH"] ?? userDefault
    }
}

/// How the tutor is wired up — the CLI's `llm` key.
enum TutorKind: String, CaseIterable, Identifiable {
    case local, byok, anthropic, none
    var id: String { rawValue }

    var label: String {
        switch self {
        case .local: return "Local model"
        case .byok: return "Bring your own key"
        case .anthropic: return "Anthropic (Claude)"
        case .none: return "No tutor"
        }
    }
    var blurb: String {
        switch self {
        case .local: return "LM Studio (:1234) or Ollama (:11434), auto-detected. Free and private."
        case .byok: return "Any OpenAI-compatible endpoint — OpenAI, Mistral, Groq, Gemini, custom."
        case .anthropic: return "Claude through the Anthropic API. The CLI picks the model."
        case .none: return "Ask mode stays off until you configure a tutor."
        }
    }
}

/// The presets offered for “bring your own key”.
struct ProviderPreset: Identifiable, Hashable {
    let id: String
    let name: String
    let url: String
    let model: String

    static let all: [ProviderPreset] = [
        .init(id: "openai", name: "OpenAI", url: "https://api.openai.com/v1", model: "gpt-4o-mini"),
        .init(id: "mistral", name: "Mistral", url: "https://api.mistral.ai/v1", model: "mistral-small-latest"),
        .init(id: "groq", name: "Groq", url: "https://api.groq.com/openai/v1", model: "llama-3.3-70b-versatile"),
        .init(id: "gemini", name: "Gemini",
              url: "https://generativelanguage.googleapis.com/v1beta/openai", model: "gemini-2.0-flash"),
        .init(id: "custom", name: "Custom", url: "", model: ""),
    ]

    /// Which preset a stored URL corresponds to (Custom when nothing matches).
    static func matching(url: String) -> ProviderPreset {
        all.first { !$0.url.isEmpty && $0.url == url } ?? all[all.count - 1]
    }
}

// MARK: - The global hotkey

/// A global hotkey the user can pick, and its Carbon translation.
struct HotkeyChoice: Identifiable, Hashable {
    let id: String              // stored in the config as `popup_hotkey`
    let display: String         // "⌥D"
    let keyCode: UInt32
    let carbonModifiers: UInt32

    static let optD = HotkeyChoice(id: "opt+d", display: "⌥D",
                                   keyCode: UInt32(kVK_ANSI_D), carbonModifiers: UInt32(optionKey))
    static let optSpace = HotkeyChoice(id: "opt+space", display: "⌥Space",
                                       keyCode: UInt32(kVK_Space), carbonModifiers: UInt32(optionKey))
    static let ctrlOptD = HotkeyChoice(id: "ctrl+opt+d", display: "⌃⌥D",
                                       keyCode: UInt32(kVK_ANSI_D),
                                       carbonModifiers: UInt32(controlKey | optionKey))
    static let cmdShiftD = HotkeyChoice(id: "cmd+shift+d", display: "⌘⇧D",
                                        keyCode: UInt32(kVK_ANSI_D),
                                        carbonModifiers: UInt32(cmdKey | shiftKey))

    static let all: [HotkeyChoice] = [optD, optSpace, ctrlOptD, cmdShiftD]
    static let fallback = optD

    /// Parses a stored id; unknown strings fall back to ⌥D.
    static func from(_ id: String?) -> HotkeyChoice {
        guard let id, !id.isEmpty else { return fallback }
        let key = id.lowercased().replacingOccurrences(of: " ", with: "")
        return all.first { $0.id == key } ?? fallback
    }
}

// MARK: - The store

/// Reads and writes `~/.dico_config.json`, preserving keys it does not know.
@MainActor
final class ConfigStore: ObservableObject {
    /// Everything that was in the file, verbatim.
    private var raw: [String: Any] = [:]
    let path: String

    // The typed view the Settings pane binds to.
    @Published var tutor: TutorKind = .local
    @Published var llmURL: String = ""
    @Published var llmModel: String = ""
    @Published var llmKey: String = ""
    @Published var anthropicKey: String = ""
    @Published var autosave: Bool = false
    @Published var vocabPath: String = ""
    @Published var storePath: String = ""
    @Published var examples: Bool = true
    @Published var xraySpacy: Bool = true
    @Published var hotkey: HotkeyChoice = .fallback
    @Published var selection: Bool = true
    /// « system », « dark » or « light » — the panel and Settings follow it.
    @Published var appearance: String = "system"

    init(path: String = ConfigPath.current) {
        self.path = path
        reload()
    }

    // MARK: Read

    func reload() {
        raw = ConfigStore.readRaw(at: path)
        tutor = TutorKind(rawValue: string("llm") ?? "") ?? .local
        llmURL = string("llm_url") ?? ""
        llmModel = string("llm_model") ?? ""
        llmKey = string("llm_key") ?? ""
        anthropicKey = string("anthropic_key") ?? ""
        autosave = bool("autosave") ?? false
        vocabPath = string("vocab_path") ?? ""
        storePath = string("store_path") ?? ""
        examples = bool("examples") ?? true
        xraySpacy = bool("xray_spacy") ?? true
        hotkey = HotkeyChoice.from(string("popup_hotkey"))
        selection = bool(Selection.configKey) ?? true
        appearance = string(Appearance.configKey) ?? "system"
    }

    private func string(_ k: String) -> String? { raw[k] as? String }
    private func bool(_ k: String) -> Bool? {
        if let b = raw[k] as? Bool { return b }
        if let n = raw[k] as? NSNumber { return n.boolValue }
        return nil
    }

    static func readRaw(at path: String) -> [String: Any] {
        guard let data = FileManager.default.contents(atPath: path),
              let obj = try? JSONSerialization.jsonObject(with: data),
              let dict = obj as? [String: Any] else { return [:] }
        return dict
    }

    // MARK: Write

    private var saveTask: Task<Void, Never>?

    /// Debounced save — for text fields, so a key stroke is not a file write.
    func scheduleSave() {
        saveTask?.cancel()
        saveTask = Task { [weak self] in
            try? await Task.sleep(nanoseconds: 400_000_000)
            guard !Task.isCancelled else { return }
            _ = self?.save()
        }
    }

    /// Writes the typed view back, keeping every unknown key. Atomic, chmod 600.
    @discardableResult
    func save() -> Bool {
        var out = raw
        func put(_ k: String, _ v: Any?) {
            if let v { out[k] = v } else { out.removeValue(forKey: k) }
        }
        put("llm", tutor.rawValue)
        put("autosave", autosave)
        put("examples", examples)
        put("xray_spacy", xraySpacy)
        put("popup_hotkey", hotkey.id)
        put(Selection.configKey, selection)
        put(Appearance.configKey, appearance == "system" ? nil : appearance)
        put("vocab_path", vocabPath.isEmpty ? nil : vocabPath)
        put("store_path", storePath.isEmpty ? nil : storePath)

        // The CLI decides which backend to use by what is present in the file,
        // so a mode change has to clear the other backend's keys.
        switch tutor {
        case .local:
            // A local tutor still has an address: LM Studio, Ollama, a Spark on
            // the network, and the model that was pinned there. Wiping those
            // sent the CLI back to its slowest fallback (bug: the pinned
            // gemma-4-12b disappeared the first time Settings saved anything).
            put("llm_url", llmURL.isEmpty ? nil : llmURL)
            put("llm_model", llmModel.isEmpty ? nil : llmModel)
            put("llm_key", llmKey.isEmpty ? nil : llmKey)
            put("anthropic_key", nil)
        case .none:
            for k in ["llm_url", "llm_model", "llm_key", "anthropic_key"] { put(k, nil) }
        case .byok:
            put("llm_url", llmURL.isEmpty ? nil : llmURL)
            put("llm_model", llmModel.isEmpty ? nil : llmModel)
            put("llm_key", llmKey.isEmpty ? nil : llmKey)
            put("anthropic_key", nil)
        case .anthropic:
            put("anthropic_key", anthropicKey.isEmpty ? nil : anthropicKey)
            for k in ["llm_url", "llm_model", "llm_key"] { put(k, nil) }
        }

        guard ConfigStore.writeRaw(out, to: path) else { return false }
        raw = out
        return true
    }

    /// Atomic + chmod 600: the file may hold an API key.
    static func writeRaw(_ dict: [String: Any], to path: String) -> Bool {
        guard let data = try? JSONSerialization.data(
            withJSONObject: dict, options: [.prettyPrinted, .sortedKeys, .withoutEscapingSlashes])
        else { return false }
        let tmp = path + ".dico-tmp"
        let fm = FileManager.default
        try? fm.removeItem(atPath: tmp)
        guard fm.createFile(atPath: tmp, contents: data,
                            attributes: [.posixPermissions: NSNumber(value: Int16(0o600))])
        else { return false }
        do {
            // rename(2) through FileManager: replaces in one step, same volume.
            if fm.fileExists(atPath: path) { try fm.removeItem(atPath: path) }
            try fm.moveItem(atPath: tmp, toPath: path)
            try fm.setAttributes([.posixPermissions: NSNumber(value: Int16(0o600))],
                                 ofItemAtPath: path)
            return true
        } catch {
            try? fm.removeItem(atPath: tmp)
            return false
        }
    }

    /// The file's permission bits, for the self-test.
    static func permissions(of path: String) -> Int? {
        guard let attrs = try? FileManager.default.attributesOfItem(atPath: path),
              let n = attrs[.posixPermissions] as? NSNumber else { return nil }
        return n.intValue
    }

    // MARK: Defaults + environment

    /// What the CLI uses when `vocab_path` is empty.
    static var defaultVocabPath: String { NSHomeDirectory() + "/.dico/vocabulaire.md" }
    static var defaultStorePath: String { NSHomeDirectory() + "/.dico/dico_vocab.json" }

    /// `DICO_VOCAB` / `DICO_STORE` win over the config — say so when they are set.
    static var envOverrides: [String] {
        var out: [String] = []
        let env = ProcessInfo.processInfo.environment
        for k in ["DICO_VOCAB", "DICO_STORE"] where !(env[k] ?? "").isEmpty {
            out.append("\(k)=\(env[k]!)")
        }
        return out
    }
}
