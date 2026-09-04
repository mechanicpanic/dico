#!/usr/bin/env python3
"""Install Grammalecte (French grammar checker, GPL, pure Python) into
data/grammalecte/ for `dico -g`. Downloads the latest official archive from
grammalecte.net (~6 MB) if it is missing. Zero dependencies.

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
        raise SystemExit("no archive found on grammalecte.net")
    v = max(found, key=lambda s: [int(x) for x in s.split(".")])
    return f"{SITE}zip/Grammalecte-fr-v{v}.zip", v


def main():
    if os.path.isdir(os.path.join(DEST, "grammalecte")):
        print(f"✓ Grammalecte already installed → {DEST}")
        return
    os.makedirs(DATA, exist_ok=True)
    url, v = latest_zip()
    zpath = os.path.join(DATA, "grammalecte.zip")
    print(f"… downloading Grammalecte v{v}")
    urllib.request.urlretrieve(url, zpath)
    with zipfile.ZipFile(zpath) as z:
        z.extractall(DEST)
    os.remove(zpath)
    print(f"✓ Grammalecte v{v} → {DEST}  (dico -g \"sentence\")")


if __name__ == "__main__":
    main()
