#!/usr/bin/env python3
"""Construit la table `forms` (forme conjuguée → infinitif) dans conjugations.db.

Lit la table `verbs` DÉJÀ présente (aucune dépendance, pas besoin de verbecc) et
indexe chaque forme simple : « doit » → « devoir », « devais » → « devoir », …
Permet à `dico -c doit` de remonter automatiquement à l'infinitif.

    python3 build_conj_forms.py        (rapide : relit juste la base existante)
"""
import json
import os
import re
import sqlite3
import unicodedata

DB = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                  "data", "conjugations.db")
SKIP_TENSES = {"passé composé"}          # temps composés : 2 mots (aux + participe)


def deaccent(s):
    return "".join(c for c in unicodedata.normalize("NFD", s)
                   if unicodedata.category(c) != "Mn").lower()


def bare_form(s):
    """« que je doive » / « il doit » / « mangeons » → le dernier mot conjugué."""
    toks = re.findall(r"[a-zà-ÿ'’]+", s.lower())
    return toks[-1] if toks else ""


def main():
    if not os.path.exists(DB):
        raise SystemExit("conjugations.db absent — lance d'abord "
                         "build_conjugations.py")
    con = sqlite3.connect(DB)
    con.execute("DROP TABLE IF EXISTS forms")
    con.execute("CREATE TABLE forms (nform TEXT, verb TEXT)")
    seen, batch = set(), []
    rows = con.execute("SELECT verb, data FROM verbs").fetchall()
    for verb, data in rows:
        try:
            tenses = json.loads(data)
        except (ValueError, TypeError):
            continue
        for tense, forms in tenses.items():
            if tense in SKIP_TENSES or not isinstance(forms, list):
                continue
            for f in forms:
                nf = deaccent(bare_form(f))
                if not nf or (nf, verb) in seen:
                    continue
                seen.add((nf, verb))
                batch.append((nf, verb))
    con.executemany("INSERT INTO forms (nform, verb) VALUES (?, ?)", batch)
    con.execute("CREATE INDEX idx_forms_nform ON forms(nform)")
    con.commit()
    n = con.execute("SELECT count(*) FROM forms").fetchone()[0]
    con.close()
    print(f"✓ {n} formes indexées (sur {len(rows)} verbes) → table `forms`")


if __name__ == "__main__":
    main()
