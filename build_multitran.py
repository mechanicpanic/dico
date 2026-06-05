#!/usr/bin/env python3
"""Construit data/multitran.db à partir des Tabfiles convertis par pyglossary.

Étapes en amont (faites une fois, hors de ce script) :
    uv run --with pyglossary --with lxml --with biplist -- pyglossary \\
        ~/Library/Dictionaries/multitran_rufr.dictionary data/multitran_rufr.txt \\
        --read-format=AppleDictBin --write-format=Tabfile

Ce script lit ces .txt et fabrique une base SQLite interrogeable hors-ligne,
sans aucune dépendance externe (sqlite3 fait partie de la bibliothèque standard).
"""
import os
import sqlite3

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
DB = os.path.join(DATA, "multitran.db")
SOURCES = {"rufr": "multitran_rufr.txt", "frru": "multitran_frru.txt"}


def iter_entries(path):
    """Lit un Tabfile pyglossary : 'mot<TAB>corps'. Recolle les rares lignes
    de continuation (corps contenant un vrai retour à la ligne)."""
    hw, body = None, None
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\n")
            if "\t" in line:
                if hw:
                    yield hw, body
                hw, body = line.split("\t", 1)
            elif hw is not None:
                body += "\n" + line
        if hw:
            yield hw, body


def main():
    os.makedirs(DATA, exist_ok=True)
    con = sqlite3.connect(DB)
    con.execute("PRAGMA journal_mode=OFF")
    con.execute("DROP TABLE IF EXISTS entries")
    con.execute("CREATE TABLE entries (key TEXT, dir TEXT, headword TEXT, body TEXT)")
    total = 0
    for direction, fname in SOURCES.items():
        path = os.path.join(DATA, fname)
        if not os.path.exists(path):
            print(f"⚠ manquant : {fname} (conversion pyglossary non faite ?)")
            continue
        n, batch = 0, []
        for hw, body in iter_entries(path):
            key = hw.strip().lower()
            if not key:
                continue
            batch.append((key, direction, hw.strip(), body))
            if len(batch) >= 5000:
                con.executemany("INSERT INTO entries VALUES (?,?,?,?)", batch)
                n += len(batch)
                batch = []
        if batch:
            con.executemany("INSERT INTO entries VALUES (?,?,?,?)", batch)
            n += len(batch)
        print(f"  {direction} : {n:>7} entrées")
        total += n
    print("  index…")
    con.execute("CREATE INDEX idx_key_dir ON entries (key, dir)")
    con.commit()
    con.close()
    size = os.path.getsize(DB) / 1e6
    print(f"✓ {total} entrées → {DB}  ({size:.0f} Mo)")


if __name__ == "__main__":
    main()
