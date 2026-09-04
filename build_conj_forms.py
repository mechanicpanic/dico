#!/usr/bin/env python3
"""Build the `forms` table (conjugated form → infinitive) in conjugations.db.

Reads the `verbs` table that is ALREADY there (no dependency, verbecc not
needed) and indexes every simple form: "doit" → "devoir", "devais" → "devoir", …
This lets `dico -c doit` walk back to the infinitive automatically.

    python3 build_conj_forms.py        (fast: it just re-reads the existing db)
"""
import json
import os
import re
import sqlite3
import unicodedata

DB = os.path.join(os.environ.get("DICO_DATA") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "data"), "conjugations.db")
SKIP_TENSES = {"passé composé"}          # compound tenses: 2 words (aux + participle)


def deaccent(s):
    return "".join(c for c in unicodedata.normalize("NFD", s)
                   if unicodedata.category(c) != "Mn").lower()


def bare_form(s):
    """"que je doive" / "il doit" / "mangeons" → the last conjugated word."""
    toks = re.findall(r"[a-zà-ÿ'’]+", s.lower())
    return toks[-1] if toks else ""


def main():
    if not os.path.exists(DB):
        raise SystemExit("conjugations.db missing — run build_conjugations.py "
                         "first")
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
    print(f"✓ {n} forms indexed (from {len(rows)} verbs) → `forms` table")


if __name__ == "__main__":
    main()
