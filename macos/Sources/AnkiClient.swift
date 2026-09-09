import Foundation
import AppKit

// MARK: - Anki, through the AnkiConnect add-on (2055492159)
//
// Anki keeps the schedule; the panel only shows the card that is due and
// sends the grade back. Nothing is written to the collection file directly.

struct AnkiCard: Identifiable, Hashable {
    let id: Int
    let front: String
    let back: String            // HTML, as Anki stores it
    let queue: Int              // 0 new · 1/3 learning · 2 review
    let interval: Int
    let reps: Int
    let deck: String

    /// The back, without its HTML: the meaning first, then the example(s).
    var backLines: [String] { AnkiClient.lines(fromHTML: back) }
    var isNew: Bool { queue == 0 }
    var isLearning: Bool { queue == 1 || queue == 3 }
}

struct AnkiCounts: Hashable {
    var new = 0, learning = 0, due = 0
    var total: Int { new + learning + due }
}

enum AnkiError: LocalizedError {
    case unreachable
    case api(String)
    var errorDescription: String? {
        switch self {
        case .unreachable: return "Anki is not running (or the AnkiConnect add-on is missing)."
        case .api(let s): return "AnkiConnect: \(s)"
        }
    }
}

enum AnkiClient {
    static let url = URL(string: "http://127.0.0.1:8765")!
    static let defaultDeck = "Français — Vocabulaire"
    static let configKey = "anki_deck"

    /// The deck the Cards mode reviews — Settings ▸ Vocabulary.
    @MainActor static var deck: String {
        let d = (ConfigStore.readRaw(at: ConfigPath.current)[configKey] as? String ?? "")
            .trimmingCharacters(in: .whitespaces)
        return d.isEmpty ? defaultDeck : d
    }

    // MARK: The wire

    /// One AnkiConnect call. Blocking — call it off the main thread.
    @discardableResult
    static func invoke(_ action: String, _ params: [String: Any] = [:], timeout: TimeInterval = 8) throws -> Any {
        var req = URLRequest(url: url, timeoutInterval: timeout)
        req.httpMethod = "POST"
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        req.httpBody = try JSONSerialization.data(withJSONObject: [
            "action": action, "version": 6, "params": params])
        let sem = DispatchSemaphore(value: 0)
        var got: Data?, failed: Error?
        URLSession.shared.dataTask(with: req) { d, _, e in got = d; failed = e; sem.signal() }.resume()
        sem.wait()
        guard failed == nil, let data = got,
              let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else {
            throw AnkiError.unreachable
        }
        if let err = obj["error"] as? String, !err.isEmpty { throw AnkiError.api(err) }
        return obj["result"] ?? NSNull()
    }

    static func reachable() -> Bool {
        (try? invoke("version", timeout: 1.5)) != nil
    }

    static func launch() {
        guard let app = NSWorkspace.shared.urlForApplication(withBundleIdentifier: "net.ankiweb.dtop")
                ?? (FileManager.default.fileExists(atPath: "/Applications/Anki.app")
                    ? URL(fileURLWithPath: "/Applications/Anki.app") : nil) else { return }
        NSWorkspace.shared.openApplication(at: app, configuration: NSWorkspace.OpenConfiguration())
    }

    // MARK: Reading

    static func counts(deck: String) throws -> AnkiCounts {
        let q = "deck:\"\(deck)\""
        func n(_ extra: String) throws -> Int {
            ((try invoke("findCards", ["query": "\(q) \(extra)"])) as? [Any])?.count ?? 0
        }
        return AnkiCounts(new: try n("is:new"), learning: try n("is:learn"),
                          due: try n("is:due -is:learn"))
    }

    /// What is worth showing now: learning first, then the reviews that are
    /// due, then up to `newLimit` new cards — the order Anki itself uses.
    static func queue(deck: String, newLimit: Int = 20) throws -> [AnkiCard] {
        let ids = (try invoke("findCards", ["query": "deck:\"\(deck)\" (is:due OR is:new)"]) as? [Int]) ?? []
        guard !ids.isEmpty else { return [] }
        let infos = (try invoke("cardsInfo", ["cards": Array(ids.prefix(400))]) as? [[String: Any]]) ?? []
        var learning: [(Int, AnkiCard)] = [], review: [(Int, AnkiCard)] = [], fresh: [(Int, AnkiCard)] = []
        for i in infos {
            guard let card = card(from: i) else { continue }
            let due = i["due"] as? Int ?? 0
            if card.isLearning { learning.append((due, card)) }
            else if card.queue == 2 { review.append((due, card)) }
            else if card.queue == 0 { fresh.append((due, card)) }
        }
        let sorted = { (a: [(Int, AnkiCard)]) in a.sorted { $0.0 < $1.0 }.map { $0.1 } }
        return sorted(learning) + sorted(review) + Array(sorted(fresh).prefix(newLimit))
    }

    static func card(from i: [String: Any]) -> AnkiCard? {
        guard let id = i["cardId"] as? Int else { return nil }
        // Fields by order, whatever they are called (Front/Back, Recto/Verso…).
        let fields = (i["fields"] as? [String: [String: Any]] ?? [:])
            .sorted { ($0.value["order"] as? Int ?? 0) < ($1.value["order"] as? Int ?? 0) }
            .map { $0.value["value"] as? String ?? "" }
        let front = fields.first.map(plain) ?? plain(i["question"] as? String ?? "")
        let back = fields.count > 1 ? fields[1] : (i["answer"] as? String ?? "")
        return AnkiCard(id: id, front: front, back: back,
                        queue: i["queue"] as? Int ?? 0, interval: i["interval"] as? Int ?? 0,
                        reps: i["reps"] as? Int ?? 0, deck: i["deckName"] as? String ?? "")
    }

    // MARK: Writing

    /// 1 again · 2 hard · 3 good · 4 easy.
    static func answer(_ card: AnkiCard, ease: Int) throws {
        let r = try invoke("answerCards", ["answers": [["cardId": card.id, "ease": ease]]])
        guard let ok = (r as? [Bool])?.first, ok else { throw AnkiError.api("the card was not graded") }
    }

    /// Adds every saved word the deck does not have yet. Returns how many.
    static func push(_ rows: [(front: String, back: String)], deck: String) throws -> Int {
        try invoke("createDeck", ["deck": deck])
        let ids = (try invoke("findNotes", ["query": "deck:\"\(deck)\""]) as? [Int]) ?? []
        var have = Set<String>()
        if !ids.isEmpty, let notes = try invoke("notesInfo", ["notes": ids]) as? [[String: Any]] {
            for n in notes {
                let fields = (n["fields"] as? [String: [String: Any]] ?? [:])
                    .sorted { ($0.value["order"] as? Int ?? 0) < ($1.value["order"] as? Int ?? 0) }
                if let f = fields.first?.value["value"] as? String { have.insert(plain(f).lowercased()) }
            }
        }
        let fresh = rows.filter { !have.contains($0.front.lowercased()) }
        guard !fresh.isEmpty else { return 0 }
        let notes: [[String: Any]] = fresh.map { r in
            ["deckName": deck, "modelName": "Basic",
             "fields": ["Front": r.front, "Back": r.back],
             "options": ["allowDuplicate": false, "duplicateScope": "deck"]]
        }
        let added = (try invoke("addNotes", ["notes": notes], timeout: 30) as? [Any]) ?? []
        return added.filter { !($0 is NSNull) }.count
    }

    /// dico's store, as Anki rows — what `push` sends.
    static func storeRows() throws -> [(front: String, back: String)] {
        let store = try DicoClient.paths().store
        let data = try Data(contentsOf: URL(fileURLWithPath: store))
        let obj = try JSONSerialization.jsonObject(with: data) as? [String: Any]
        var seen = Set<String>(), out: [(front: String, back: String)] = []
        for e in (obj?["entries"] as? [[String: Any]]) ?? [] {
            let front = ((e["front"] as? String).flatMap { $0.isEmpty ? nil : $0 } ?? e["lemma"] as? String ?? "")
                .trimmingCharacters(in: .whitespaces)
            guard !front.isEmpty, seen.insert(front.lowercased()).inserted else { continue }
            let sens = (e["sens"] as? String ?? "").trimmingCharacters(in: .whitespaces)
            let ex = (e["example"] as? String ?? "").trimmingCharacters(in: .whitespaces)
            out.append((front, sens + (ex.isEmpty ? "" : "<br><i>\(ex)</i>")))
        }
        return out
    }

    // MARK: Text

    static func plain(_ html: String) -> String {
        lines(fromHTML: html).joined(separator: " ")
    }

    /// « sens<br><i>exemple</i> » → ["sens", "exemple"].
    static func lines(fromHTML html: String) -> [String] {
        var s = html.replacingOccurrences(of: "\r", with: "")
        for br in ["<br>", "<br/>", "<br />", "</div>", "</p>", "\n"] { s = s.replacingOccurrences(of: br, with: "\u{1}") }
        s = s.replacingOccurrences(of: "<[^>]+>", with: "", options: .regularExpression)
        for (e, c) in [("&nbsp;", " "), ("&amp;", "&"), ("&lt;", "<"), ("&gt;", ">"), ("&quot;", "\""), ("&#39;", "'")] {
            s = s.replacingOccurrences(of: e, with: c)
        }
        return s.split(separator: "\u{1}").map { $0.trimmingCharacters(in: .whitespaces) }.filter { !$0.isEmpty }
    }
}
