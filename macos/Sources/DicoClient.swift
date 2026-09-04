import Foundation

// MARK: - Models decoded from `dico --json`

/// One sense: the "to_fr" shape carries term/front/back/gender/band, the "fr"
/// shape carries pos/terms. Everything stays optional.
struct Sense: Decodable, Hashable {
    var pos: String?
    var term: String?
    var front: String?
    var back: [String]?
    var terms: [String]?
    var gender: String?
    var band: String?

    /// What the chip shows.
    var display: String { front ?? term ?? terms?.first ?? "?" }
    /// What we pass to `--save-term`.
    var saveTerm: String? { term }
}

struct Lexique: Decodable {
    var ortho: String?
    var lemma: String?
    var pos: String?
    var genre: String?
    var nombre: String?
    var article: String?
    var band: String?
}

struct Lookup: Decodable {
    var query: String?
    var direction: String?      // "to_fr" | "fr"
    var src_lang: String?       // "ru" | "en"
    var translation: String?
    var head: String?
    var lexique: Lexique?
    var senses: [Sense]?
    var examples: [[String]]?
    var error: String?
}

struct Conjugation: Decodable {
    var infinitive: String?
    var tenses: [String: [String]]?
    var error: String?

    /// The tenses come in an (unordered) dictionary: we impose the order.
    static let order = ["présent", "passé composé", "imparfait", "futur simple",
                        "conditionnel", "subjonctif", "impératif"]
    /// Tooltips: what each tense is for, in English.
    static let hints: [String: String] = [
        "présent": "Présent — what is happening now, or generally true",
        "passé composé": "Passé composé — a finished action in the past",
        "imparfait": "Imparfait — an ongoing or habitual past",
        "futur simple": "Futur simple — what will happen",
        "conditionnel": "Conditionnel — what would happen",
        "subjonctif": "Subjonctif — after « que »: wish, doubt, emotion",
        "impératif": "Impératif — orders (tu / nous / vous only)",
    ]
    static let shortLabels: [String: String] = [
        "présent": "présent", "passé composé": "passé c.", "imparfait": "imparfait",
        "futur simple": "futur", "conditionnel": "cond.", "subjonctif": "subj.",
        "impératif": "impér.",
    ]
    var orderedTenses: [(String, [String])] {
        guard let t = tenses else { return [] }
        var out = Conjugation.order.compactMap { k in t[k].map { (k, $0) } }
        for (k, v) in t where !Conjugation.order.contains(k) { out.append((k, v)) }
        return out
    }
}
private struct ConjEnvelope: Decodable { var conjugation: Conjugation? }

struct GrammarError: Decodable, Hashable {
    var start: Int
    var end: Int
    var text: String?
    var message: String?
    var type: String?
    var suggestions: [String]?
}
struct SpellingError: Decodable, Hashable {
    var start: Int
    var end: Int
    var text: String?
    var suggestions: [String]?
}
struct Grammar: Decodable {
    var errors: [GrammarError]?
    var spelling: [SpellingError]?
    var corrected: String?
}
private struct GrammarEnvelope: Decodable { var grammar: Grammar? }

struct XrayToken: Decodable, Hashable {
    var text: String?
    var lemma: String?
    var pos: String?
    var tense: String?
    var gender: String?
    var band: String?
    var role: String?
    var gloss: String?
}
private struct XrayEnvelope: Decodable { var xray: [XrayToken]? }

/// One Tatoeba example: the French sentence plus one translation.
struct ExampleSentence: Decodable, Hashable {
    var fr: String?
    var en: String?
    var ru: String?
    /// Whichever translation this sentence carries.
    var gloss: String? { en ?? ru }
}

/// `--examples` returns two lists: English translations, then Russian ones.
struct ExamplePack: Decodable {
    var en: [ExampleSentence]?
    var ru: [ExampleSentence]?

    var isEmpty: Bool { (en ?? []).isEmpty && (ru ?? []).isEmpty }
    static let empty = ExamplePack(en: [], ru: [])
}
private struct ExamplesEnvelope: Decodable { var examples: ExamplePack? }

struct Definition: Decodable {
    var word: String?
    var ipa: String?
    var gender: String?
    var pos: String?
    var defs: [String]?
    var etym: String?
}
private struct DefinitionEnvelope: Decodable { var definition: Definition? }

struct Multitran: Decodable {
    var direction: String?      // "frru" | "rufr"
    var lines: [String]?
    var error: String?
}
private struct MultitranEnvelope: Decodable { var multitran: Multitran? }

struct Answer: Decodable {
    var answer: String?
    var error: String?
    var model: String?
}

struct SaveResult: Decodable {
    var saved: String?
    var status: String?
    var count: Int?
    var sens: String?
    var error: String?
}

// MARK: - Errors

enum DicoError: LocalizedError {
    case notFound
    case setupNeeded
    case timeout
    case badOutput(String)
    case cli(String)

    var errorDescription: String? {
        switch self {
        case .notFound:
            return "dico not found — install it: uv tool install git+https://github.com/mechanicpanic/dico"
        case .setupNeeded:
            return "Offline data not built — run: dico --setup"
        case .timeout:
            return "Too slow… (30 s) — is the local model answering?"
        case .badOutput(let s):
            return "Unreadable answer from dico\n\(s.prefix(200))"
        case .cli(let s):
            return s
        }
    }

    /// Does this CLI message mean "the offline databases were never built"?
    static func meansMissingData(_ message: String) -> Bool {
        let l = message.lowercased()
        return l.contains("--setup") || l.contains("not built") || l.contains("not installed — run")
    }

    /// Maps a raw CLI message onto the right case.
    static func from(message: String) -> DicoError {
        meansMissingData(message) ? .setupNeeded : .cli(message)
    }
}

// MARK: - Client

/// Runs the `dico` CLI and decodes the last JSON object of its output.
enum DicoClient {

    /// A minimal PATH, but enough to find python3/uv/dico.
    private static let searchPath = [
        "/opt/homebrew/bin",
        NSHomeDirectory() + "/.local/bin",
        "/usr/local/bin",
        "/usr/bin",
        "/bin",
    ]

    /// Possible locations of the script when the `dico` binary does not exist.
    private static let scriptCandidates = [
        NSHomeDirectory() + "/Projects/vibes/dico/dico.py",
        NSHomeDirectory() + "/dico/dico.py",
    ]

    /// Resolves (executable, argument prefix).
    private static func resolve() -> (String, [String])? {
        if let bin = ProcessInfo.processInfo.environment["DICO_BIN"],
           FileManager.default.isExecutableFile(atPath: bin) { return (bin, []) }
        for dir in searchPath {
            let p = dir + "/dico"
            if FileManager.default.isExecutableFile(atPath: p) { return (p, []) }
        }
        var scripts = scriptCandidates
        if let s = ProcessInfo.processInfo.environment["DICO_SCRIPT"] { scripts.insert(s, at: 0) }
        for s in scripts where FileManager.default.fileExists(atPath: s) {
            for py in ["/opt/homebrew/bin/python3", "/usr/bin/python3", "/usr/local/bin/python3"]
            where FileManager.default.isExecutableFile(atPath: py) {
                return (py, [s])
            }
        }
        return nil
    }

    /// Runs the CLI and returns raw stdout. Blocking — call it off the main thread.
    static func raw(_ args: [String], timeout: TimeInterval = 30) throws -> String {
        guard let (exe, prefix) = resolve() else { throw DicoError.notFound }

        let task = Process()
        task.executableURL = URL(fileURLWithPath: exe)
        task.arguments = prefix + args
        var env = ProcessInfo.processInfo.environment
        env["PATH"] = searchPath.joined(separator: ":")
        env["PYTHONIOENCODING"] = "utf-8"
        task.environment = env

        let out = Pipe(), err = Pipe()
        task.standardOutput = out
        task.standardError = err
        do { try task.run() } catch { throw DicoError.notFound }

        // Read in the background so the pipe does not fill up while we wait.
        var stdoutData = Data(), stderrData = Data()
        let lock = NSLock()
        let group = DispatchGroup()
        for (pipe, isOut) in [(out, true), (err, false)] {
            group.enter()
            DispatchQueue.global().async {
                let d = pipe.fileHandleForReading.readDataToEndOfFile()
                lock.lock()
                if isOut { stdoutData = d } else { stderrData = d }
                lock.unlock()
                group.leave()
            }
        }

        // Wait, with a deadline.
        let deadline = Date().addingTimeInterval(timeout)
        while task.isRunning && Date() < deadline { usleep(30_000) }
        if task.isRunning { task.terminate(); _ = group.wait(timeout: .now() + 1); throw DicoError.timeout }
        _ = group.wait(timeout: .now() + 2)

        let text = String(decoding: stdoutData, as: UTF8.self)
        if text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            let e = String(decoding: stderrData, as: UTF8.self).trimmingCharacters(in: .whitespacesAndNewlines)
            throw DicoError.cli(e.isEmpty ? "dico returned nothing" : String(e.suffix(300)))
        }
        return text
    }

    /// Extracts the LAST JSON object from the output (tolerating stray lines)
    /// and decodes it into the requested type.
    static func decode<T: Decodable>(_ type: T.Type, from text: String) throws -> T {
        guard let end = text.lastIndex(of: "}") else { throw DicoError.badOutput(text) }
        let head = String(text[text.startIndex...end])

        // Candidate starts: every "{" at the beginning of a line, last to first.
        var starts: [String.Index] = []
        var idx = head.startIndex
        var atLineStart = true
        while idx < head.endIndex {
            let c = head[idx]
            if atLineStart && c == "{" { starts.append(idx) }
            atLineStart = (c == "\n")
            idx = head.index(after: idx)
        }
        if starts.isEmpty, head.first == "{" { starts = [head.startIndex] }

        let dec = JSONDecoder()
        for s in starts.reversed() {
            let candidate = String(head[s...])
            if let d = candidate.data(using: .utf8), let v = try? dec.decode(T.self, from: d) { return v }
        }
        throw DicoError.badOutput(head)
    }

    private static func call<T: Decodable>(_ type: T.Type, _ args: [String]) throws -> T {
        try decode(type, from: raw(args))
    }

    // MARK: The five modes + saving

    static func lookup(_ word: String) throws -> Lookup { try call(Lookup.self, ["--json", word]) }

    static func conjugate(_ verb: String) throws -> Conjugation {
        let env = try call(ConjEnvelope.self, ["--json", "-c", verb])
        guard let c = env.conjugation else { throw DicoError.cli("No conjugation for \u{ab} \(verb) \u{bb}") }
        if let e = c.error, !e.isEmpty { throw DicoError.from(message: e) }
        guard c.infinitive != nil, let t = c.tenses, !t.isEmpty else {
            throw DicoError.cli("\u{ab} \(verb) \u{bb} is not a verb I know how to conjugate.")
        }
        return c
    }

    static func grammar(_ sentence: String) throws -> Grammar {
        let env = try call(GrammarEnvelope.self, ["--json", "-g", sentence])
        guard let g = env.grammar else { throw DicoError.cli("No grammar analysis") }
        return g
    }

    static func xray(_ sentence: String) throws -> [XrayToken] {
        let env = try call(XrayEnvelope.self, ["--json", "-x", sentence])
        guard let x = env.xray, !x.isEmpty else { throw DicoError.cli("Nothing to dissect") }
        return x
    }

    static func ask(_ question: String, context: String?) throws -> Answer {
        var args = ["--json", "-a", question]
        if let c = context, !c.isEmpty { args += ["--context", c] }
        let a = try call(Answer.self, args)
        if let e = a.error, !e.isEmpty { throw DicoError.from(message: e) }
        return a
    }

    static func save(term: String, sens: String) throws -> SaveResult {
        try call(SaveResult.self, ["--json", "--save-term", term, "--sens", sens])
    }

    // MARK: The word-card sections

    /// Wiktionary entry for a word that is already French (`-f`).
    static func definition(_ word: String) throws -> Definition {
        let env = try call(DefinitionEnvelope.self, ["--json", "-f", word])
        guard let d = env.definition, !(d.defs ?? []).isEmpty else {
            throw DicoError.cli("No Wiktionary entry for \u{ab} \(word) \u{bb} (needs the internet).")
        }
        return d
    }

    /// Offline Multitran entry (`-m`). The `error` field means "not installed".
    static func multitran(_ word: String) throws -> Multitran {
        let env = try call(MultitranEnvelope.self, ["--json", "-m", word])
        guard let m = env.multitran else { throw DicoError.cli("No Multitran answer") }
        if let e = m.error, !e.isEmpty { throw DicoError.cli(e) }
        if (m.lines ?? []).isEmpty {
            throw DicoError.cli("Nothing in Multitran for \u{ab} \(word) \u{bb}.")
        }
        return m
    }

    /// The Tatoeba example sentences of a French word (`--examples`).
    /// An empty pack is a valid answer — the view says "No examples found".
    static func examples(_ word: String) throws -> ExamplePack {
        let env = try call(ExamplesEnvelope.self, ["--json", "--examples", word])
        guard let p = env.examples else { throw DicoError.cli("No examples for \u{ab} \(word) \u{bb}.") }
        return p
    }
}
