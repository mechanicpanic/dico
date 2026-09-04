import SwiftUI

/// The five modes of the panel.
enum Mode: String, CaseIterable, Identifiable {
    case mot, conjuguer, grammaire, rayonsX, demander
    var id: String { rawValue }

    var label: String {
        switch self {
        case .mot: return "Word"
        case .conjuguer: return "Conjugate"
        case .grammaire: return "Grammar"
        case .rayonsX: return "X-ray"
        case .demander: return "Ask"
        }
    }
    var icon: String {
        switch self {
        case .mot: return "📖"
        case .conjuguer: return "🔁"
        case .grammaire: return "✅"
        case .rayonsX: return "🔬"
        case .demander: return "💬"
        }
    }
    var placeholder: String {
        switch self {
        case .mot: return "a word… (cook, кошка, maison)"
        case .conjuguer: return "a verb… (aller)"
        case .grammaire: return "a sentence to correct…"
        case .rayonsX: return "a sentence to dissect…"
        case .demander: return "a question for the tutor…"
        }
    }
}

/// What the panel is showing right now.
enum Outcome {
    case vide
    case chargement
    case mot(Lookup)
    case conjugaison(Conjugation)
    case grammaire(Grammar, String)     // + the queried sentence (for the offsets)
    case rayonsX([XrayToken])
    case reponse(Answer)
    case erreur(String)
}

@MainActor
final class DicoModel: ObservableObject {
    @Published var query: String = ""
    @Published var mode: Mode = .mot
    @Published var outcome: Outcome = .vide
    @Published var busy: Bool = false
    @Published var toast: String? = nil
    @Published var shown: Bool = false          // drives the appearance animation

    /// Last word / sentence looked up — used as `--context` for the tutor.
    private(set) var lastContext: String = ""
    /// Source word of the current card (for `--sens` when saving).
    private(set) var currentSource: String = ""

    private var generation = 0
    private var toastTask: Task<Void, Never>?

    // MARK: Input

    /// A leading `-c`, `-g`, `-x` or `?` switches mode and is removed from the field.
    func normalizeInput() {
        let t = query
        let prefixes: [(String, Mode)] = [("-c ", .conjuguer), ("-g ", .grammaire),
                                          ("-x ", .rayonsX), ("? ", .demander), ("?", .demander)]
        for (p, m) in prefixes where t.hasPrefix(p) {
            mode = m
            query = String(t.dropFirst(p.count))
            return
        }
    }

    func clear() {
        query = ""
        outcome = .vide
    }

    // MARK: Query

    func submit() {
        let q = query.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !q.isEmpty else { return }
        generation += 1
        let gen = generation
        let mode = self.mode
        let ctx = lastContext
        busy = true
        outcome = .chargement

        Task.detached(priority: .userInitiated) {
            let result: Result<Outcome, Error>
            do {
                switch mode {
                case .mot:       result = .success(.mot(try DicoClient.lookup(q)))
                case .conjuguer: result = .success(.conjugaison(try DicoClient.conjugate(q)))
                case .grammaire: result = .success(.grammaire(try DicoClient.grammar(q), q))
                case .rayonsX:   result = .success(.rayonsX(try DicoClient.xray(q)))
                case .demander:  result = .success(.reponse(try DicoClient.ask(q, context: ctx)))
                }
            } catch {
                result = .failure(error)
            }
            await MainActor.run { [weak self] in
                guard let self, gen == self.generation else { return }
                self.busy = false
                switch result {
                case .success(let o):
                    self.outcome = o
                    if mode != .demander { self.lastContext = q }
                    if mode == .mot { self.currentSource = q }
                case .failure(let e):
                    self.outcome = .erreur((e as? LocalizedError)?.errorDescription ?? e.localizedDescription)
                }
            }
        }
    }

    // MARK: Saving a sense

    /// Save the n-th sense of the current card (1-indexed), for ⌘1…⌘9.
    func saveSense(number n: Int) {
        guard case .mot(let lookup) = outcome else { return }
        if let senses = lookup.senses, n >= 1, n <= senses.count {
            save(sense: senses[n - 1], lookup: lookup)
        }
    }

    func save(sense: Sense, lookup: Lookup) {
        // For a French card, the entry to save is the head ("une maison").
        let term = sense.saveTerm ?? lookup.head ?? lookup.query ?? ""
        guard !term.isEmpty else { return }
        let sens = currentSource.isEmpty ? (lookup.query ?? term) : currentSource
        let shown = sense.front ?? term
        Task.detached(priority: .userInitiated) {
            let msg: String
            do {
                let r = try DicoClient.save(term: term, sens: sens)
                let status = r.status ?? "added"
                msg = "✓ \u{201c}\(r.saved ?? shown)\u{201d} \(status)"
            } catch {
                msg = "⚠︎ not saved — \((error as? LocalizedError)?.errorDescription ?? "error")"
            }
            await MainActor.run { [weak self] in self?.flash(msg) }
        }
    }

    func flash(_ message: String) {
        toast = message
        toastTask?.cancel()
        toastTask = Task { [weak self] in
            try? await Task.sleep(nanoseconds: 2_000_000_000)
            guard !Task.isCancelled else { return }
            await MainActor.run { self?.toast = nil }
        }
    }
}
