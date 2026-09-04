#!/usr/bin/env python3
"""Build data/multitran.db from the Tabfiles converted by pyglossary.

Upstream steps (done once, outside this script):
    uv run --with pyglossary --with lxml --with biplist -- pyglossary \\
        ~/Library/Dictionaries/multitran_rufr.dictionary data/multitran_rufr.txt \\
        --read-format=AppleDictBin --write-format=Tabfile

This script reads those .txt files and builds a SQLite database that can be
queried offline, with no external dependency (sqlite3 ships with Python).
"""
import os
import sqlite3
import unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(os.environ.get("DICO_DATA") or os.path.join(HERE, "data"))
DB = os.path.join(DATA, "multitran.db")
SOURCES = {"rufr": "multitran_rufr.txt", "frru": "multitran_frru.txt"}


def iter_entries(path):
    """Read a pyglossary Tabfile: 'word<TAB>body'. Re-joins the rare
    continuation lines (a body containing a real newline)."""
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


def _deaccent(s):
    """No accents, no uppercase — for the nkey column (lenient lookup)."""
    nfd = unicodedata.normalize("NFD", s)
    return "".join(c for c in nfd if unicodedata.category(c) != "Mn").lower()


def main():
    os.makedirs(DATA, exist_ok=True)
    con = sqlite3.connect(DB)
    con.execute("PRAGMA journal_mode=OFF")
    con.execute("DROP TABLE IF EXISTS entries")
    con.execute("CREATE TABLE entries "
                "(key TEXT, dir TEXT, headword TEXT, body TEXT, nkey TEXT)")
    total = 0
    for direction, fname in SOURCES.items():
        path = os.path.join(DATA, fname)
        if not os.path.exists(path):
            print(f"⚠ missing: {fname} (pyglossary conversion not done?)")
            continue
        n, batch = 0, []
        for hw, body in iter_entries(path):
            headword = hw.strip()
            # An entry often has several keys joined by "|", inside
            # quotes/spaces (" zéro "|" zero ") → split them all so they become
            # searchable (otherwise 55% of frru is unreachable).
            keys = {k for part in headword.split("|")
                    if (k := part.strip().strip('"').strip().lower())}
            for key in keys:
                batch.append((key, direction, headword, body, _deaccent(key)))
            if len(batch) >= 5000:
                con.executemany("INSERT INTO entries VALUES (?,?,?,?,?)", batch)
                n += len(batch)
                batch = []
        if batch:
            con.executemany("INSERT INTO entries VALUES (?,?,?,?,?)", batch)
            n += len(batch)
        print(f"  {direction}: {n:>7} entries")
        total += n
    print("  indexing…")
    con.execute("CREATE INDEX idx_key_dir ON entries (key, dir)")
    con.execute("CREATE INDEX idx_nkey_dir ON entries (nkey, dir)")
    con.commit()
    con.close()
    size = os.path.getsize(DB) / 1e6
    print(f"✓ {total} entries → {DB}  ({size:.0f} MB)")


if __name__ == "__main__":
    main()
