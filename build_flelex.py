#!/usr/bin/env python3
"""Add the `cefr` table to data/lexique.db from FLELex (CEFRLex, UCLouvain).

FLELex gives, for every lemma, its frequency at each CEFR level in a corpus of
textbooks for learners of French. A word's level is the FIRST level where it
actually appears (>= 1 occurrence per million); that is the level at which a
learner is expected to meet it. So the card can say « A1 » or « C1 » instead of
only « courant / rare », which measures how common a word is for *natives*.

    python3 build_flelex.py         (needs data/lexique.db — run build_lexique.py first)
"""
import os
import sqlite3
import unicodedata
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.environ.get("DICO_DATA") or os.path.join(HERE, "data")
CSV = os.path.join(DATA, "FleLex_TT.csv")
DB = os.path.join(DATA, "lexique.db")
URL = "https://cental.uclouvain.be/cefrlex/static/resources/fr/FleLex_TT.csv"
LEVELS = ["A1", "A2", "B1", "B2", "C1", "C2"]
THRESHOLD = 1.0          # occurrences per million: below that it is noise/smoothing

# FLELex uses TreeTagger tags; Lexique uses its own. Map to Lexique's cgram.
TAG_TO_CGRAM = {"NOM": "NOM", "VER": "VER", "ADJ": "ADJ", "ADV": "ADV",
                "PRP": "PRE", "PRO": "PRO", "KON": "CON", "DET": "ART",
                "NAM": "NOM", "INT": "ONO", "NUM": "ADJ"}


def deaccent(s):
    return "".join(c for c in unicodedata.normalize("NFD", s)
                   if unicodedata.category(c) != "Mn").lower()


def ensure_csv():
    if os.path.exists(CSV):
        return
    os.makedirs(DATA, exist_ok=True)
    print(f"… downloading FLELex from {URL}")
    req = urllib.request.Request(URL, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=60) as r, open(CSV, "wb") as f:
        f.write(r.read())


def level_of(freqs):
    """The first CEFR level where the word really occurs."""
    for name, value in zip(LEVELS, freqs):
        if value >= THRESHOLD:
            return name
    return LEVELS[-1]


def main():
    if not os.path.exists(DB):
        raise SystemExit("data/lexique.db missing — run build_lexique.py first")
    ensure_csv()
    rows = []
    with open(CSV, encoding="utf-8") as f:
        f.readline()                                   # header
        for line in f:
            c = line.rstrip("\n").split("\t")
            if len(c) < 9 or not c[0]:
                continue
            try:
                freqs = [float(x) for x in c[2:8]]
            except ValueError:
                continue
            word, tag = c[0], c[1]
            rows.append((word, deaccent(word), TAG_TO_CGRAM.get(tag, tag),
                         level_of(freqs), float(c[8])))
    con = sqlite3.connect(DB)
    con.execute("DROP TABLE IF EXISTS cefr")
    con.execute("""CREATE TABLE cefr (
        lemma TEXT, nlemma TEXT, cgram TEXT, level TEXT, freq REAL)""")
    con.executemany("INSERT INTO cefr VALUES (?,?,?,?,?)", rows)
    con.execute("CREATE INDEX idx_cefr_nlemma ON cefr(nlemma)")
    con.commit()
    spread = dict(con.execute(
        "SELECT level, count(*) FROM cefr GROUP BY level ORDER BY level"))
    con.close()
    print(f"✓ {len(rows)} lemmas graded → `cefr` table  "
          + " · ".join(f"{k} {v}" for k, v in spread.items()))


if __name__ == "__main__":
    main()
