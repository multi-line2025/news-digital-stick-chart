"""T-065 のテスト：netfetch の 308 の扱い（Python 3.9 でも1回で止まる）と、手の手順の確認の行。

実行（プロジェクトのルートで）:
    PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest discover -s tests/sealer -v

ネットワークは使わない（通信の部分は test_t014.FakeHTTPS に差し替える）。本物の sealed/ には書かない。
"""

import glob
import json
import os
import re
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import test_ledger as tl  # noqa: E402
from test_t056 import pythons  # noqa: E402

ledger = tl.ledger
DOC = os.path.join(tl.PROJECT, "docs", "verify", "periods-seal.md")

# 別のプロセス（両方の Python）で、各リダイレクトの応答に対する http_get の振る舞いを出す
CHILD = r"""
import json, sys
sys.path.insert(0, sys.argv[1]); sys.path.insert(0, sys.argv[2])
import netfetch, test_t014
out = {}
for code in (301, 302, 303, 307, 308):
    h = test_t014.FakeHTTPS({netfetch.DRAND_URLS[0]: (code, "https://example.com/elsewhere", b"")})
    op = netfetch.build_no_redirect_opener(h)
    sleeps = []
    try:
        netfetch.http_get(netfetch.DRAND_URLS[0], sleep=sleeps.append, opener=lambda r, timeout: op.open(r, timeout=timeout))
        err = None
    except Exception as e:
        err = type(e).__name__
    out[code] = [err, len(h.seen), len(sleeps), any("example.com" in u for u in h.seen)]
print(json.dumps(out))
"""


class TestRedirect308BothPythons(unittest.TestCase):
    def test_every_redirect_stops_after_one_request(self):
        for py in pythons():
            r = subprocess.run([py, "-B", "-c", CHILD, os.path.join(tl.PROJECT, "src", "sealer"), HERE],
                               capture_output=True, env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
            self.assertEqual(r.returncode, 0, (py, r.stderr.decode()[-2000:]))
            out = json.loads(r.stdout)
            for code in ("301", "302", "303", "307", "308"):
                # RedirectRefused で止まり、要求は1回だけ、再試行の待ちも無く、転送先には送らない
                self.assertEqual(out[code], ["RedirectRefused", 1, 0, False], (py, code))


def doc_block():
    with open(DOC, encoding="utf-8") as f:
        text = f.read()
    m = re.search(r"verify を使わずに手で確かめる手順（T-056、T-059[^\n]*\n  ```sh\n(.*?)\n  ```", text, re.S)
    return [l[2:] for l in m.group(1).split("\n")]


def check_line(prefix):
    """手の手順のうち、"$PY" -B -c '…' で始まる確認の行（prefix を含むもの）。"""
    lines = [l for l in doc_block() if l.startswith('"$PY" -B -c ') and prefix in l]
    return lines


class TestManualCheckLines(unittest.TestCase):
    """手の手順の確認の行（files がちょうど4件、targets がちょうど10件）を、本物の記録の中身に流して ok を出し、
    1件足した中身では ok を出さないことを確かめる（T-060 の軽-2）。"""

    def run_line(self, line, path, py):
        cmd = line.split(" sealed/")[0]                   # 末尾の sealed/…json を除いた部分
        code = re.match(r"\"\$PY\" -B -c '(.*)'$", cmd).group(1)
        r = subprocess.run([py, "-B", "-c", code, path], capture_output=True,
                           env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
        self.assertEqual(r.returncode, 0, r.stderr.decode())
        return r.stdout.decode().strip()

    def check(self, kind, key, needle, mutate):
        lines = check_line(needle)
        self.assertEqual(len(lines), 1, needle)
        real = [p for p in glob.glob(os.path.join(tl.PROJECT, "sealed", kind + "-*.json"))]
        self.assertEqual(len(real), 1)
        import tempfile
        with open(real[0], encoding="utf-8") as f:
            doc = json.load(f)
        mutate(doc[key])
        with tempfile.TemporaryDirectory() as d:
            bad = os.path.join(d, "bad.json")
            with open(bad, "w", encoding="utf-8") as f:
                json.dump(doc, f)
            for py in pythons():
                self.assertEqual(self.run_line(lines[0], real[0], py), "ok", py)
                self.assertNotEqual(self.run_line(lines[0], bad, py), "ok", py)

    def test_order1b_files(self):
        self.check("stats-order1b", "files", 'd["files"]',
                   lambda fs: fs.append({"path": "src/stats/fractions.py", "sha256": "a" * 64}))

    def test_order1_targets(self):
        self.check("stats-order1", "targets", 'd["targets"]',
                   lambda ts: ts.append({"name": "src/stats/fractions.py", "sha256": "a" * 64}))


if __name__ == "__main__":
    unittest.main()
