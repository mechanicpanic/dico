import SwiftUI

/// Les cinq modes du panneau.
enum Mode: String, CaseIterable, Identifiable {
    case mot, conjuguer, grammaire, rayonsX, demander
    var id: String { rawValue }

    var label: String {
        switch self {
        case .mot: return "Mot"
        case .conjuguer: return "Conjuguer"
        case .grammaire: return "Grammaire"
        case .rayonsX: return "Rayons X"
        case .demander: return "Demander ?"
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
        case .mot: return "un mot… (cook, кошка, maison)"
        case .conjuguer: return "un verbe… (aller)"
        case .grammaire: return "une phrase à corriger…"
        case .rayonsX: return "une phrase à disséquer…"
        case .demander: return "une question au tuteur…"
        }
    }
}

/// Ce que le panneau affiche à l'instant t.
enum Outcome {
    case vide
    case chargement
    case mot(Lookup)
    case conjugaison(Conjugation)
    case grammaire(Grammar, String)     // + la phrase interrogée (pour les offsets)
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
    @Published var shown: Bool = false          // pilote l'animation d'apparition

    /// Dernier mot / phrase consulté — sert de `--context` au tuteur.
    private(set) var lastContext: String = ""
    /// Mot source de la fiche courante (pour `--sens` à la sauvegarde).
    private(set) var currentSource: String = ""

    private var generation = 0
    private var toastTask: Task<Void, Never>?

    // MARK: Saisie

    /// `-c`, `-g`, `-x` ou `?` en tête bascule le mode et se retire du champ.
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

    // MARK: Requête

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

    // MARK: Sauvegarde d'une acception

    /// Sauve la n-ième acception de la fiche courante (1-indexé), pour ⌘1…⌘9.
    func saveSense(number n: Int) {
        guard case .mot(let lookup) = outcome else { return }
        if let senses = lookup.senses, n >= 1, n <= senses.count {
            save(sense: senses[n - 1], lookup: lookup)
        }
    }

    func save(sense: Sense, lookup: Lookup) {
        // Pour une fiche française, l'entrée à sauver est la tête ("une maison").
        let term = sense.saveTerm ?? lookup.head ?? lookup.query ?? ""
        guard !term.isEmpty else { return }
        let sens = currentSource.isEmpty ? (lookup.query ?? term) : currentSource
        let shown = sense.front ?? term
        Task.detached(priority: .userInitiated) {
            let msg: String
            do {
                let r = try DicoClient.save(term: term, sens: sens)
                let status = r.status ?? "ajouté"
                msg = "✓ « \(r.saved ?? shown) » \(status)"
            } catch {
                msg = "⚠︎ pas sauvé — \((error as? LocalizedError)?.errorDescription ?? "erreur")"
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
