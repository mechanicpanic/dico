#!/usr/bin/env python3
"""Construit data/lexique.db depuis Lexique 3.83 (lexique.org, licence CC-BY).

Donne, HORS-LIGNE et sans dépendance, pour n'importe quelle forme tapée (même
sans accents : « etre » → « être ») : le lemme, la nature (cgram), le genre
(→ un/une), le nombre, et la fréquence (occurrences par million — sous-titres
de films + livres). Sert à :
  - enrichir l'auto-save (lemme/genre hors-ligne → plus de requête réseau) ;
  - afficher un badge de fréquence (« très courant » … « rare ») ;
  - extraire le noyau de mots-outils (`dico --mots-outils`).

Télécharge Lexique383.tsv s'il est absent (≈ 26 Mo). Le TSV est conservé
(source mise en cache, non versionnée) pour des reconstructions rapides.

    python3 build_lexique.py
"""
import os
import sqlite3
import unicodedata
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
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
    print(f"… téléchargement de Lexique383.tsv depuis {URL}")
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
        f.readline()                          # en-tête
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
    print(f"✓ {n} formes → {os.path.relpath(DB, HERE)}")


if __name__ == "__main__":
    main()
