#!/usr/bin/env python3
"""Installe Grammalecte (correcteur grammatical français, GPL, pur Python) dans
data/grammalecte/ pour `dico -g`. Télécharge la dernière archive officielle depuis
grammalecte.net (≈ 6 Mo) si elle est absente. Zéro dépendance.

    python3 build_grammalecte.py
"""
import os
import re
import urllib.request
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(os.environ.get("DICO_DATA") or os.path.join(HERE, "data"))
DEST = os.path.join(DATA, "grammalecte")
SITE = "https://grammalecte.net/"


def latest_zip():
    html = urllib.request.urlopen(SITE, timeout=30).read().decode("utf-8", "replace")
    found = re.findall(r"zip/Grammalecte-fr-v([0-9.]+)\.zip", html)
    if not found:
        raise SystemExit("aucune archive trouvée sur grammalecte.net")
    v = max(found, key=lambda s: [int(x) for x in s.split(".")])
    return f"{SITE}zip/Grammalecte-fr-v{v}.zip", v


def main():
    if os.path.isdir(os.path.join(DEST, "grammalecte")):
        print(f"✓ Grammalecte déjà présent → {os.path.relpath(DEST, HERE)}")
        return
    os.makedirs(DATA, exist_ok=True)
    url, v = latest_zip()
    zpath = os.path.join(DATA, "grammalecte.zip")
    print(f"… téléchargement de Grammalecte v{v}")
    urllib.request.urlretrieve(url, zpath)
    with zipfile.ZipFile(zpath) as z:
        z.extractall(DEST)
    os.remove(zpath)
    print(f"✓ Grammalecte v{v} → {os.path.relpath(DEST, HERE)}  (dico -g « phrase »)")


if __name__ == "__main__":
    main()
