# /// script
# requires-python = ">=3.10"
# dependencies = ["verbecc"]
# ///
"""Construit data/conjugations.db : conjugaisons françaises HORS-LIGNE.

Utilise verbecc UNE FOIS pour conjuguer tous les verbes français connus
(~7000), puis range les temps utiles dans une base SQLite. Ensuite, `dico -c`
lit cette base avec la seule bibliothèque standard (aucune dépendance).

Lancement :
    uv run build_conjugations.py
"""
import json
import os
import sqlite3

from verbecc import CompleteConjugator, LangCodeISO639_1

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(os.environ.get("DICO_DATA") or os.path.join(HERE, "data"))
DB = os.path.join(DATA, "conjugations.db")

# étiquette affichée  ->  (mood verbecc, tense verbecc)
TENSES = [
    ("présent",       ("indicatif", "présent")),
    ("passé composé", ("indicatif", "passé-composé")),
    ("imparfait",     ("indicatif", "imparfait")),
    ("futur simple",  ("indicatif", "futur-simple")),
    ("conditionnel",  ("conditionnel", "présent")),
    ("subjonctif",    ("subjonctif", "présent")),
    ("impératif",     ("imperatif", "imperatif-présent")),
]
PRONOUNS = ["je", "tu", "il", "nous", "vous", "ils"]
IMP_PRONOUNS = ["tu", "nous", "vous"]


def forms_for(entries, pronouns):
    by_pr = {}
    for e in entries:
        c = e.get("c") or []
        if c:
            by_pr[e.get("pr")] = c[0]
    return [by_pr[p] for p in pronouns if p in by_pr]


def main():
    os.makedirs(DATA, exist_ok=True)
    cc = CompleteConjugator(LangCodeISO639_1.fr)
    infinitives = cc.get_infinitives()
    print(f"verbes à conjuguer : {len(infinitives)}")
    con = sqlite3.connect(DB)
    con.execute("PRAGMA journal_mode=OFF")
    con.execute("DROP TABLE IF EXISTS verbs")
    con.execute("CREATE TABLE verbs (verb TEXT PRIMARY KEY, data TEXT)")
    n, batch = 0, []
    for inf in infinitives:
        try:
            moods = json.loads(cc.conjugate(inf).to_json())["moods"]
        except Exception:
            continue
        out = {}
        for label, (mood, tense) in TENSES:
            entries = moods.get(mood, {}).get(tense)
            if not entries:
                continue
            prons = IMP_PRONOUNS if mood == "imperatif" else PRONOUNS
            forms = forms_for(entries, prons)
            if forms:
                out[label] = forms
        if out:
            batch.append((inf, json.dumps(out, ensure_ascii=False)))
        if len(batch) >= 2000:
            con.executemany("INSERT OR REPLACE INTO verbs VALUES (?,?)", batch)
            n += len(batch)
            batch = []
            print(f"  ... {n}")
    if batch:
        con.executemany("INSERT OR REPLACE INTO verbs VALUES (?,?)", batch)
        n += len(batch)
    con.commit()
    con.close()
    size = os.path.getsize(DB) / 1e6
    print(f"✓ {n} verbes → {DB}  ({size:.1f} Mo)")


if __name__ == "__main__":
    main()
