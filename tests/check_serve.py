#!/usr/bin/env python3
"""`dico --serve` == the one-shot CLI: drive the golden queries through ONE
--serve process (as "args" requests) and compare each `result` with the
recorded tests/golden/<name>.json — same scratch HOME / store, same volatile
fields (see check_goldens.py). Then the protocol: a follow-up over the
persistent session, a garbage line, an unknown request, ping, EOF → exit 0.

    python3 tests/check_serve.py
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from check_goldens import DICO, GOLDEN, QUERIES, REPO, _diff, _normalise, scratch_env  # noqa: E402


class Serve:
    def __init__(self, tmp):
        self.p = subprocess.Popen([sys.executable, DICO, "--serve"], stdin=subprocess.PIPE,
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                  encoding="utf-8", env=scratch_env(tmp), cwd=REPO)

    def raw(self, line):
        self.p.stdin.write(line + "\n")
        self.p.stdin.flush()
        out = self.p.stdout.readline()
        assert out.endswith("\n"), f"no response line for {line!r}"
        return json.loads(out)

    def ask(self, **req):
        return self.raw(json.dumps(req, ensure_ascii=False))

    def close(self):
        self.p.stdin.close()
        try:
            code = self.p.wait(timeout=30)
        except subprocess.TimeoutExpired:
            self.p.kill()
            code = "killed"
        return code, self.p.stderr.read()


def main():
    tmp = tempfile.mkdtemp(prefix="dico-serve-")
    failed = []
    ok = lambda name, cond, detail="": (print(f"{'ok' if cond else 'FAIL'} {name}" + (f"\n{detail}" if not cond and detail else "")),
                                        None if cond else failed.append(name))
    s = Serve(tmp)
    try:
        r = s.ask(id=0, op="ping")
        ok("ping", r.get("ok") is True and r.get("id") == 0 and r.get("version"), r)
        for i, (name, argv) in enumerate(QUERIES, 1):
            r = s.ask(id=i, args=["--json", *argv])
            path = os.path.join(GOLDEN, name + ".json")
            with open(path, encoding="utf-8") as f:
                want = json.load(f)
            if "error" in r and "result" not in r:
                ok(f"serve {name}", False, r["error"])
                continue
            now = _normalise(json.dumps(r["result"], ensure_ascii=False), name, tmp)
            ok(f"serve {name} (kind={r.get('kind')})", r.get("id") == i and "kind" in r and now == want,
               _diff(want, now, name) if now != want else r)
        # the session persists: a follow-up on the previous lookup
        r1 = s.ask(id="a", line="cook")
        r2 = s.ask(id="b", line="save 1")
        ok("follow-up: save 1 after cook", r1.get("kind") == "card_to_fr"
           and r2.get("kind") == "saved" and r2["result"]["saved"]["front"] == "cuisiner"
           and r2["result"]["saved"]["status"] == "added", (r1.get("kind"), r2))
        r3 = s.ask(id="c", line="conj")
        ok("follow-up: conj on the last card", r3.get("kind") == "card_fr" and
           r3["result"].get("conjugation", {}).get("infinitive") == "cuisiner", r3.get("result", r3).get("conjugation"))
        r = s.ask(id="h", op="history")
        turns = r.get("result", {}).get("history", [])
        ok("op history: the session's turns persist across requests", r.get("kind") == "history"
           and any(t.get("query") == "cook" and t.get("saved") == "cuisiner" for t in turns)
           and turns[-1].get("query") == "cuisiner", turns[-3:])
        # garbage in → an error out, no id, and the loop goes on
        r = s.raw("this is not json")
        ok("invalid JSON → error without id", "error" in r and "id" not in r, r)
        r = s.raw("[1, 2, 3]")
        ok("non-object → error", "error" in r, r)
        r = s.ask(id=9, nonsense=True)
        ok("unknown request → error with id", r.get("id") == 9 and "error" in r, r)
        r = s.ask(id=10, args=["--no-such-flag"])
        ok("bad args → error with id", r.get("id") == 10 and "error" in r, r)
        r = s.ask(id=11, op="ping")
        ok("still serving after errors", r.get("ok") is True and r.get("id") == 11, r)
        r = s.ask(id=12, args=["--json", "--context", "cook", "--paths"])
        ok("args: a store command over serve", r.get("kind") == "paths" and "store" in r.get("result", {}), r)
    finally:
        code, err = s.close()
        ok("EOF → exit 0", code == 0, f"exit {code}\n{err[-1500:]}")
        shutil.rmtree(tmp, ignore_errors=True)
    if failed:
        print(f"\n{len(failed)} failed: {', '.join(failed)}")
        return 1
    print("\nserve == one-shot")
    return 0


if __name__ == "__main__":
    sys.exit(main())
