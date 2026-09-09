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
    var cefr: String?

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
    /// A1…C2 — the level a learner meets the word at (FLELex), which is a
    /// different question from how frequent it is for a native (`band`).
    var cefr: String?
    /// Pronunciation, offline, from Lexique's own alphabet turned into IPA.
    var ipa: String?
    var syll: String?
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
    /// The sentence that was analysed — the translation, when the input was not French.
    var sentence: String?
    var source: String?
    var translated: String?
}
private struct GrammarEnvelope: Decodable {
    var grammar: Grammar?; var sentence: String?; var source: String?; var translated: String?
}

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
/// The x-ray of a sentence: its words, and the translation it went through.
struct Xray {
    var tokens: [XrayToken]
    var source: String? = nil
    var translated: String? = nil
}
private struct XrayEnvelope: Decodable { var xray: [XrayToken]?; var source: String?; var translated: String? }

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

/// A word with the register tag Wiktionary attaches to it (familier, vieilli…).
struct WordNote: Decodable, Hashable {
    var word: String?
    var note: String?
}

/// A Russian translation: the word, its transliteration and its gender.
struct RuTerm: Decodable, Hashable {
    var word: String?
    var tr: String?
    var gender: String?
}

struct Definition: Decodable {
    var word: String?
    var ipa: String?
    var gender: String?
    var pos: String?
    var defs: [String]?
    var etym: String?
    var cefr: String?
    var syn: [WordNote]?
    var homo: [WordNote]?
    var ru: [RuTerm]?
    var has_audio: Bool?
}

struct AudioResult: Decodable {
    var path: String?
    var error: String?
}
private struct AudioEnvelope: Decodable { var audio: AudioResult? }
private struct DefinitionEnvelope: Decodable { var definition: Definition? }

/// One translation inside a sense, with the optional note Multitran attaches
/// to it (a gloss, a domain hint — or a whole example sentence).
struct MultitranItem: Decodable, Hashable {
    var tr: String?
    var note: String?
}

/// A numbered sense inside a part-of-speech group, tagged with its domain
/// (общ., юр., тех., gener., mech.eng. …).
struct MultitranSense: Decodable, Hashable {
    var n: String?
    var domain: String?
    var items: [MultitranItem]?
}

/// A part-of-speech group. `pos` may be empty, or a short code ("n", "гл.").
struct MultitranGroup: Decodable, Hashable {
    var pos: String?
    var senses: [MultitranSense]?
}

struct Multitran: Decodable {
    var direction: String?      // "frru" | "rufr"
    var lines: [String]?
    var groups: [MultitranGroup]?
    var error: String?
    /// Russian from the Wiktionnaire, when Multitran is not installed.
    var wiktionary_ru: [RuTerm]?

    /// Every group that actually carries something.
    var usableGroups: [MultitranGroup] {
        (groups ?? []).filter { !(($0.senses ?? []).isEmpty) }
    }
    var isEmpty: Bool {
        usableGroups.isEmpty && (lines ?? []).isEmpty && (wiktionary_ru ?? []).isEmpty
    }
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

    /// The friendly wording for "Multitran is not there" — it is optional, and
    /// it needs the Apple dictionaries.
    static let multitranMissing =
        "Multitran not installed — it needs the Apple dictionaries (optional, see README)"

    /// Multitran's own `error` field, dressed up.
    static func multitranProblem(_ raw: String) -> DicoError {
        raw.lowercased().contains("not installed") ? .cli(multitranMissing) : .cli(raw)
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
    /// A checkout comes FIRST: on a machine that has one, its data directory is
    /// the real one (it may hold Multitran, which the bundle never can). The
    /// bundled copy is the fallback that makes the app work on its own.
    private static var scriptCandidates: [String] {
        var out = [NSHomeDirectory() + "/Projects/vibes/dico/dico.py",
                   NSHomeDirectory() + "/dico/dico.py"]
        if let bundled = bundledScript { out.append(bundled) }
        return out
    }

    static var bundledScript: String? { Bundle.main.path(forResource: "dico", ofType: "py") }

    /// Where the app keeps the offline databases: ~/.dico/data, the same place
    /// the CLI uses. The bundle carries a copy, which is seeded on first run.
    static var dataDir: String { NSHomeDirectory() + "/.dico/data" }

    /// Set by resolve(): true when we fell back to the copy inside the app.
    /// Only then do we impose ~/.dico — a script that lives in a checkout
    /// resolves its own data directory, and that one may have Multitran in it.
    private(set) static var usingBundledScript = false

    /// Guards the seeding so it is attempted once per run, whichever entry
    /// point gets there first (the panel, a Service, or --selftest).
    private static let seedOnce: Bool = seedData()

    /// Copies the databases out of the app bundle on first run — 20 MB, a
    /// second or two, no network, no `uv`, no Terminal. This is what makes the
    /// app work by being dragged to /Applications.
    /// Returns true if it actually seeded something.
    @discardableResult
    static func seedDataIfNeeded() -> Bool { seedOnce }

    private static func seedData() -> Bool {
        let fm = FileManager.default
        guard let packed = Bundle.main.resourcePath.map({ $0 + "/data" }),
              fm.fileExists(atPath: packed) else { return false }
        // Already there? A single file is enough to tell: the CLI checks each.
        if fm.fileExists(atPath: dataDir + "/lexique.db") { return false }
        try? fm.createDirectory(atPath: dataDir, withIntermediateDirectories: true)
        var seeded = false
        for item in (try? fm.contentsOfDirectory(atPath: packed)) ?? [] {
            let dest = dataDir + "/" + item
            guard !fm.fileExists(atPath: dest) else { continue }
            do {
                try fm.copyItem(atPath: packed + "/" + item, toPath: dest)
                seeded = true
            } catch {
                continue
            }
        }
        return seeded
    }

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
            usingBundledScript = (s == bundledScript)
            // dico is pure standard library and runs on the python macOS ships
            // (3.9), so no interpreter has to be installed either.
            for py in ["/opt/homebrew/bin/python3", "/usr/bin/python3", "/usr/local/bin/python3"]
            where FileManager.default.isExecutableFile(atPath: py) {
                return (py, [s])
            }
        }
        return nil
    }

    /// The built-in deck: dico's store, scheduled by the CLI (SM-2).
    struct Deck: Decodable {
        struct Card: Decodable {
            var key: String; var front: String?; var back: [String]?
            var state: String?; var ivl: Int?; var reps: Int?
            var gender: String?; var pos: String?; var cefr: String?; var ipa: String?
            var card: ReviewCard {
                ReviewCard(key: key, ankiId: nil, front: front ?? "", backLines: back ?? [],
                           state: state ?? "new", interval: ivl ?? 0, reps: reps ?? 0,
                           gender: gender ?? "", pos: pos ?? "", cefr: cefr ?? "", ipa: ipa ?? "")
            }
        }
        struct Counts: Decodable { var learning: Int?; var due: Int?; var new: Int? }
        struct Saved: Decodable, Hashable { var front: String?; var gloss: String? }
        var cards: [Card]?; var counts: Counts?
        var total: Int?; var recent: [Saved]?
        var ankiCounts: AnkiCounts { AnkiCounts(new: counts?.new ?? 0, learning: counts?.learning ?? 0, due: counts?.due ?? 0) }
    }
    static func due() throws -> Deck { try call(Deck.self, ["--json", "--due"]) }
    private struct Graded: Decodable { var card: Deck.Card?; var error: String? }
    /// One card, filled in by the CLI if it was bare (gloss, example, IPA…).
    static func card(_ key: String) throws -> ReviewCard {
        let g = try call(Graded.self, ["--json", "--card", key])
        if let e = g.error, !e.isEmpty { throw DicoError.cli(e) }
        guard let c = g.card else { throw DicoError.cli("no card") }
        return c.card
    }
    static func grade(_ key: String, ease: Int) throws {
        let g = try call(Graded.self, ["--json", "--grade", key, "--ease", String(ease)])
        if let e = g.error, !e.isEmpty { throw DicoError.cli(e) }
    }

    /// Where the CLI keeps things — the store is what the Anki push reads.
    struct Paths: Decodable {
        var config: String; var vocab: String; var store: String; var data: String
        var cards_repo: String?; var cards_autosync: Bool?
    }
    /// `dico --backup`: pull, render, commit, push the cards. Slow-ish (git + network).
    struct Backup: Decodable { var repo: String?; var remote: String?; var steps: [String]?; var error: String? }
    /// `dico --backup-init [URL]`: the cards get a repository of their own.
    struct BackupInit: Decodable { var repo: String?; var remote: String?; var moved: Bool?; var pushed: Bool?; var error: String? }
    static func backupInit(remote: String) throws -> BackupInit {
        var args = ["--json", "--backup-init"]
        if !remote.isEmpty { args.append(remote) }
        return try call(BackupInit.self, args, timeout: 90)
    }
    static func backup(pullOnly: Bool = false) throws -> Backup {
        try call(Backup.self, ["--json", pullOnly ? "--pull" : "--backup"], timeout: 90)
    }
    static func paths() throws -> Paths { try call(Paths.self, ["--json", "--paths"]) }

    /// Runs the CLI and returns raw stdout. Blocking — call it off the main thread.
    static func raw(_ args: [String], timeout: TimeInterval = 30) throws -> String {
        _ = seedOnce                    // the databases must exist before the first call
        guard let (exe, prefix) = resolve() else { throw DicoError.notFound }

        let task = Process()
        task.executableURL = URL(fileURLWithPath: exe)
        task.arguments = prefix + args
        var env = ProcessInfo.processInfo.environment
        env["PATH"] = searchPath.joined(separator: ":")
        env["PYTHONIOENCODING"] = "utf-8"
        // The bundled script has no repo next to it: point it at ~/.dico.
        if usingBundledScript {
            if env["DICO_DATA"] == nil { env["DICO_DATA"] = dataDir }
            if env["DICO_HOME"] == nil { env["DICO_HOME"] = NSHomeDirectory() + "/.dico" }
        }
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

    private static func call<T: Decodable>(_ type: T.Type, _ args: [String], timeout: TimeInterval = 30) throws -> T {
        try decode(type, from: raw(args, timeout: timeout))
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
        guard var g = env.grammar else { throw DicoError.cli("No grammar analysis") }
        g.sentence = env.sentence; g.source = env.source; g.translated = env.translated
        return g
    }

    static func xray(_ sentence: String) throws -> Xray {
        let env = try call(XrayEnvelope.self, ["--json", "-x", sentence])
        guard let x = env.xray, !x.isEmpty else { throw DicoError.cli("Nothing to dissect") }
        return Xray(tokens: x, source: env.source, translated: env.translated)
    }

    static func ask(_ question: String, context: String?) throws -> Answer {
        var args = ["--json", "-a", question]
        if let c = context, !c.isEmpty { args += ["--context", c] }
        let a = try call(Answer.self, args)
        if let e = a.error, !e.isEmpty { throw DicoError.from(message: e) }
        return a
    }

    static func save(term: String, sens: String, example: [String] = [], tier: String = "") throws -> SaveResult {
        var args = ["--json", "--save-term", term, "--sens", sens]
        if !tier.isEmpty { args += ["--tier", tier] }
        if example.count >= 1, !example[0].isEmpty { args += ["--example", example[0]] }
        if example.count >= 2, !example[1].isEmpty { args += ["--example-en", example[1]] }
        return try call(SaveResult.self, args)
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
        if let e = m.error, !e.isEmpty { throw DicoError.multitranProblem(e) }
        if m.isEmpty {
            throw DicoError.cli("Nothing in Multitran for \u{ab} \(word) \u{bb}.")
        }
        return m
    }

    /// The Tatoeba example sentences of a French word (`--examples`).
    /// An empty pack is a valid answer — the view says "No examples found".
    /// Downloads (once) the native recording and returns the local mp3 path.
    static func audio(_ word: String) throws -> AudioResult {
        let env = try call(AudioEnvelope.self, ["--json", "--say", word])
        guard let a = env.audio else { throw DicoError.notFound }
        return a
    }

    static func examples(_ word: String) throws -> ExamplePack {
        let env = try call(ExamplesEnvelope.self, ["--json", "--examples", word])
        guard let p = env.examples else { throw DicoError.cli("No examples for \u{ab} \(word) \u{bb}.") }
        return p
    }

    // MARK: Long-running calls, streamed (Settings ▸ Offline data)

    /// Runs the CLI and hands every stdout/stderr line to `onLine` as it comes,
    /// then the exit status to `onExit`. Both on the main queue. Non-blocking.
    static func stream(_ args: [String],
                       onLine: @escaping (String) -> Void,
                       onExit: @escaping (Int32) -> Void) {
        guard let (exe, prefix) = resolve() else {
            onLine(DicoError.notFound.errorDescription ?? "dico not found")
            onExit(127)
            return
        }
        let task = Process()
        task.executableURL = URL(fileURLWithPath: exe)
        task.arguments = prefix + args
        var env = ProcessInfo.processInfo.environment
        env["PATH"] = searchPath.joined(separator: ":")
        env["PYTHONIOENCODING"] = "utf-8"
        // The bundled script has no repo next to it: point it at ~/.dico.
        if usingBundledScript {
            if env["DICO_DATA"] == nil { env["DICO_DATA"] = dataDir }
            if env["DICO_HOME"] == nil { env["DICO_HOME"] = NSHomeDirectory() + "/.dico" }
        }
        task.environment = env

        let pipe = Pipe()
        task.standardOutput = pipe
        task.standardError = pipe
        do { try task.run() } catch {
            onLine(DicoError.notFound.errorDescription ?? "dico could not be started")
            onExit(127)
            return
        }
        DispatchQueue.global(qos: .utility).async {
            var buffer = Data()
            let handle = pipe.fileHandleForReading
            while true {
                let chunk = handle.availableData
                if chunk.isEmpty { break }
                buffer.append(chunk)
                while let nl = buffer.firstIndex(of: 0x0A) {
                    let line = String(decoding: buffer[buffer.startIndex..<nl], as: UTF8.self)
                    buffer.removeSubrange(buffer.startIndex...nl)
                    let clean = stripANSI(line).trimmingCharacters(in: .whitespacesAndNewlines)
                    if !clean.isEmpty { DispatchQueue.main.async { onLine(clean) } }
                }
            }
            if !buffer.isEmpty {
                let clean = stripANSI(String(decoding: buffer, as: UTF8.self))
                    .trimmingCharacters(in: .whitespacesAndNewlines)
                if !clean.isEmpty { DispatchQueue.main.async { onLine(clean) } }
            }
            task.waitUntilExit()
            let status = task.terminationStatus
            DispatchQueue.main.async { onExit(status) }
        }
    }

    /// The CLI paints its output; the log view wants plain text.
    static func stripANSI(_ s: String) -> String {
        var out = ""
        var skipping = false
        for ch in s {
            if skipping {
                if ch.isLetter { skipping = false }
                continue
            }
            if ch == "\u{1B}" { skipping = true; continue }
            out.append(ch)
        }
        return out
    }

    // MARK: Probing a local model server (Settings ▸ Tutor)

    /// `GET <base>/models` — the model ids an OpenAI-compatible server offers.
    /// Returns nil when nothing answers within `timeout`.
    static func models(at base: String, key: String = "", timeout: TimeInterval = 2.5) -> [String]? {
        guard let url = URL(string: base.hasSuffix("/") ? base + "models" : base + "/models")
        else { return nil }
        var req = URLRequest(url: url, timeoutInterval: timeout)
        if !key.isEmpty { req.setValue("Bearer \(key)", forHTTPHeaderField: "Authorization") }
        var ids: [String]?
        let sem = DispatchSemaphore(value: 0)
        URLSession.shared.dataTask(with: req) { data, _, _ in
            defer { sem.signal() }
            guard let data,
                  let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                  let list = obj["data"] as? [[String: Any]] else { return }
            let found = list.compactMap { $0["id"] as? String }
            if !found.isEmpty { ids = found }
        }.resume()
        _ = sem.wait(timeout: .now() + timeout + 1)
        return ids
    }

    /// The two local servers the CLI auto-detects.
    static let localServers = [("LM Studio", "http://localhost:1234/v1"),
                               ("Ollama", "http://localhost:11434/v1")]
}
