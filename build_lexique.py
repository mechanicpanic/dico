#!/usr/bin/env python3
"""Build data/lexique.db from Lexique 3.83 (lexique.org, CC-BY licence).

For any typed form (even unaccented: "etre" → "être") it gives, OFFLINE and
without dependencies: the lemma, the part of speech (cgram), the gender
(→ un/une), the number, and the frequency (occurrences per million — film
subtitles + books). It is used to:
  - enrich autosave (lemma/gender offline → no more network request);
  - show a frequency badge ("très courant" … "rare");
  - extract the core function words (`dico --mots-outils`).

Downloads Lexique383.tsv if it is missing (~26 MB). The TSV is kept (a cached,
un-versioned source) for fast rebuilds.

    python3 build_lexique.py
"""
import os
import sqlite3
import unicodedata
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(os.environ.get("DICO_DATA") or os.path.join(HERE, "data"))
TSV = os.path.join(DATA, "Lexique383.tsv")
DB = os.path.join(DATA, "lexique.db")
URL = "http://www.lexique.org/databases/Lexique383/Lexique383.tsv"


def deaccent(s):
    return "".join(c for c in unicodedata.normalize("NFD", s)
                   if unicodedata.category(c) != "Mn").lower()


def fnum(s):
    try:
        return float(s.replace(",", "."))
    except (ValueError, AttributeError):
        return 0.0


def ensure_tsv():
    if os.path.exists(TSV):
        return
    os.makedirs(DATA, exist_ok=True)
    print(f"… downloading Lexique383.tsv from {URL}")
    urllib.request.urlretrieve(URL, TSV)


def main():
    ensure_tsv()
    con = sqlite3.connect(DB)
    con.execute("DROP TABLE IF EXISTS lexique")
    con.execute("""CREATE TABLE lexique (
        ortho TEXT, northo TEXT, lemme TEXT, cgram TEXT,
        genre TEXT, nombre TEXT, freqfilms REAL, freqlivres REAL)""")
    rows = []
    with open(TSV, encoding="utf-8") as f:
        f.readline()                          # header row
        for line in f:
            c = line.rstrip("\n").split("\t")
            if len(c) < 10 or not c[0]:
                continue
            ortho, lemme, cgram, genre, nombre = c[0], c[2], c[3], c[4], c[5]
            rows.append((ortho, deaccent(ortho), lemme, cgram, genre, nombre,
                         fnum(c[8]), fnum(c[9])))      # freqfilms2, freqlivres
    con.executemany(
        "INSERT INTO lexique VALUES (?,?,?,?,?,?,?,?)", rows)
    con.execute("CREATE INDEX idx_lex_northo ON lexique(northo)")
    con.execute("CREATE INDEX idx_lex_ortho ON lexique(ortho)")
    con.execute("CREATE INDEX idx_lex_cgram ON lexique(cgram, freqfilms)")
    con.commit()
    n = con.execute("SELECT count(*) FROM lexique").fetchone()[0]
    con.close()
    print(f"✓ {n} forms → {DB}")


if __name__ == "__main__":
    main()
