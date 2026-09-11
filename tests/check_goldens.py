#!/usr/bin/env python3
"""Golden `--json` outputs for the session refactor (docs/session-refactor.md).

    python3 tests/check_goldens.py            # re-run every query, diff against tests/golden/
    python3 tests/check_goldens.py --record   # (re)write the goldens; runs each query twice
                                              # and reports any field that drifted between runs
    python3 tests/check_goldens.py -k card    # only the queries whose name contains "card"

Every query runs against a TEMPORARY store (DICO_STORE / DICO_VOCAB point into a
scratch directory), so the real card store is never touched. Network answers are
served from data/translate_cache.json; keep the cache warm. Fields listed in
VOLATILE (timestamps, machine paths) are scrubbed before comparison.
"""
import difflib
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
DICO = os.path.join(REPO, "dico.py")
GOLDEN = os.path.join(HERE, "golden")

# (name, argv) — every one gets --json. Order matters: save-term first, so that
# --card / --grade / --due find the card.
QUERIES = [
    ("cook",         ["cook"]),                          # EN noun/verb → FR card
    ("maison",       ["maison"]),                        # FR word typed directly
    ("koshka",       ["кошка"]),                         # RU word
    ("dire",         ["dire"]),                          # FR verb
    ("phrase",       ["i have to go"]),                  # EN phrase
    ("conj_dire",    ["-c", "dire"]),                    # conjugation grid
    ("fr_chat",      ["-f", "chat"]),                    # Wiktionary definition
    ("multi_chat",   ["-m", "chat"]),                    # Multitran fr→ru
    ("examples",     ["--examples", "chat"]),            # Tatoeba examples
    ("grammar",      ["-g", "elle est parti"]),          # Grammalecte
    ("xray",         ["-x", "le chat dort"]),            # x-ray (spaCy sidecar if present)
    ("paths",        ["--paths"]),
    ("save_term",    ["--save-term", "chat", "--sens", "cat"]),
    ("card",         ["--card", "chat"]),
    ("grade",        ["--grade", "chat", "--ease", "3"]),
    ("due",          ["--due"]),
    ("card_missing", ["--card", "nope"]),                # error case
]

# name → JSON paths scrubbed before comparison ("*" matches any key / index).
# Timestamps depend on the clock; the SRS schedule is relative to "now".
VOLATILE = {
    "card":  ["card.due"],
    "grade": ["card.due"],
    "due":   ["cards.*.due"],
}


# Queries that change the store: running them twice gives a different (correct)
# answer, so the --record drift probe skips them.
STATEFUL = {"save_term", "grade"}


def _scrub(obj, path):
    """Drop the field at `path` (list of keys, "*" = wildcard) in place."""
    if not path:
        return
    head, rest = path[0], path[1:]
    if isinstance(obj, dict):
        keys = list(obj) if head == "*" else ([head] if head in obj else [])
        for k in keys:
            if rest:
                _scrub(obj[k], rest)
            else:
                obj[k] = "<volatile>"
    elif isinstance(obj, list):
        idx = range(len(obj)) if head == "*" else ([int(head)] if head.isdigit() and int(head) < len(obj) else [])
        for i in idx:
            if rest:
                _scrub(obj[i], rest)
            else:
                obj[i] = "<volatile>"


def _normalise(text, name, tmp):
    text = text.replace(tmp, "<TMP>").replace(os.path.expanduser("~"), "<HOME>")
    try:
        data = json.loads(text)
    except ValueError:
        return {"_raw": text}
    for p in VOLATILE.get(name, []):
        _scrub(data, p.split("."))
    return data


def run(argv, tmp):
    env = dict(os.environ,
               DICO_STORE=os.path.join(tmp, "dico_vocab.json"),
               DICO_VOCAB=os.path.join(tmp, "vocabulaire.md"),
               NO_COLOR="1", PYTHONIOENCODING="utf-8")
    r = subprocess.run([sys.executable, DICO, "--json", *argv],
                       capture_output=True, text=True, env=env, timeout=300, cwd=REPO)
    if r.returncode:
        return {"_exit": r.returncode, "_stdout": r.stdout, "_stderr": r.stderr[-2000:]}
    return r.stdout


def _dump(data):
    return json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def _diff(a, b, name):
    return "".join(difflib.unified_diff(_dump(a).splitlines(True), _dump(b).splitlines(True),
                                        f"golden/{name}.json", f"{name} (now)"))


def main():
    record = "--record" in sys.argv
    only = None
    if "-k" in sys.argv:
        only = sys.argv[sys.argv.index("-k") + 1]
    os.makedirs(GOLDEN, exist_ok=True)
    tmp = tempfile.mkdtemp(prefix="dico-golden-")
    failed = []
    try:
        for name, argv in QUERIES:
            if only and only not in name:
                continue
            out = run(argv, tmp)
            now = _normalise(out, name, tmp) if isinstance(out, str) else out
            path = os.path.join(GOLDEN, name + ".json")
            if record:
                if name in STATEFUL:           # a second run would change the store → no drift probe
                    again = now
                else:
                    out2 = run(argv, tmp)
                    again = _normalise(out2, name, tmp) if isinstance(out2, str) else out2
                if again != now:
                    print(f"~ {name}: differs between two runs — mark the field volatile:\n"
                          + _diff(now, again, name))
                    failed.append(name)
                with open(path, "w", encoding="utf-8") as f:
                    f.write(_dump(now))
                print(f"= {name}: recorded ({len(_dump(now))} bytes)")
                continue
            if not os.path.exists(path):
                print(f"? {name}: no golden (run with --record)")
                failed.append(name)
                continue
            with open(path, encoding="utf-8") as f:
                want = json.load(f)
            if want == now:
                print(f"ok {name}")
            else:
                print(f"FAIL {name}\n" + _diff(want, now, name))
                failed.append(name)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    if failed:
        print(f"\n{len(failed)} failed: {', '.join(failed)}")
        return 1
    print("\nall goldens match" if not record else "\ngoldens recorded")
    return 0


if __name__ == "__main__":
    sys.exit(main())
