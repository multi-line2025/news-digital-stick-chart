"""T-058 のテスト：記録の head の版を取り出して流すとき、名前のぶつかりと、流すスクリプトのフォルダの中身の
食い違いを「記録と合わない」で止めること（T-056 の監査 重大-1）。
T-059 で、流すフォルダを記録が縛っているファイルだけにした（git archive をやめた）ので、偽の commit は
名前のぶつかりではなく、本物が流れて偽の値と合わないことで止まる。名前のぶつかりの照合は、記録が縛っている
ファイルの名前に当てる形で残した。

実行（プロジェクトのルートで）:
    PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest discover -s tests/sealer -v

本物のリポジトリを一時フォルダに clone し、その記録（seq 5 の順番1、seq 6 の順番1b）の head から、偽る側が
作れる commit（Src/stats/counting.py などを足したもの）を作る。記録の値は、その偽の commit を流した出力の
sha256 に合わせて差し替える（監査の再現 scratchpad/a56r3pre3.sh と同じ形。T-056 の版の verify では「一致」の 0
になったもの）。照合は、.venv の Python と /usr/bin/python3 の両方で、別のプロセスとして流す。
本物の sealed/ には書かない。ネットワークは使わない。
"""

import json
import os
import subprocess
import sys
import tempfile
import unicodedata
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import test_ledger as tl  # noqa: E402
from test_t056 import CloneCase, pythons  # noqa: E402

ledger = tl.ledger
verify = tl.verify
DOC = os.path.join(tl.PROJECT, "docs", "verify", "periods-seal.md")

# 別のプロセスで、記録の中身（seq ごとの head、order1 の対象の sha256、order1b の files・output の sha256）を
# 差し替えた読み方で recompute_orders を流し、OK / UNCHECKED / MISMATCH を出す。
# 引数: root（clone）、src（src/sealer）、差し替えの JSON。
CHECKER = r"""
import sys, copy, json
root, src, spec = sys.argv[1], sys.argv[2], json.loads(sys.argv[3])
sys.path.insert(0, src)
import verify, ledger
st = verify.State(root, None)
repo = verify.Repo(root)
orig = st.file_json
def fj(r, role):
    d = orig(r, role)
    s = spec.get(str(r["seq"]))
    if s:
        d = copy.deepcopy(d)
        d["head"] = s["head"]
        for t in d.get("targets", []):
            if t["name"] in s.get("targets", {}):
                t["sha256"] = s["targets"][t["name"]]
        for f in d.get("files", []):
            if f["path"] in s.get("files", {}):
                f["sha256"] = s["files"][f["path"]]
        if "output_sha256" in s:
            d["counting"]["output_sha256"] = s["output_sha256"]
    return d
st.file_json = fj
got = {"order1": [r for r in st.records if r["kind"] == ledger.ORDER1_KIND],
       "order1b": [r for r in st.records if r["kind"] == ledger.ORDER1B_KIND]}
try:
    n, missed = verify.recompute_orders(st, repo, got)
    print("OK" if not missed else "UNCHECKED " + " / ".join(missed))
except verify.Unchecked as e:
    print("UNCHECKED " + str(e))
except ledger.LedgerError as e:
    print("MISMATCH " + str(e))
"""

COLLISION = "大文字小文字か Unicode の正規化だけが違う名前"
# T-059 から、流すフォルダには記録が縛っているファイルしか置かないので、Src/... などは書き出されず、本物が流れて
# 偽の値と合わずに止まる
COUNTING_MISMATCH = "counting.output_sha256"
EXCLUSION_MISMATCH = "の対象 src/stats/exclusion.py の出力 の sha256"


def git(*args, **kw):
    return subprocess.run(["git"] + list(args), check=True, capture_output=True, **kw).stdout


class ForgeBase(CloneCase):
    """偽の commit を作り、記録の値を差し替えて、両方の Python で照らす道具（テストは持たない。T-059 でも使う）。"""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.d1 = cls.st.file_json(cls.o1, ledger.ORDER1_KIND)
        cls.d1b = cls.st.file_json(cls.o1b, ledger.ORDER1B_KIND)
        cls.n = 0

    def worktree(self, head):
        type(self).n += 1
        wt = os.path.join(self.td.name, "wt58-%d" % self.n)
        git("-C", self.root, "worktree", "add", "-q", "--detach", wt, head)
        return wt

    def real_output(self, wt, rel):
        r = subprocess.run([sys.executable, "-B", rel], cwd=wt, capture_output=True,
                           env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
        self.assertEqual(r.returncode, 0, r.stderr.decode()[-1000:])
        return r.stdout

    def commit(self, wt, files, msg):
        """files: {名前: バイト列}。update-index で足す（大文字小文字を区別しない手元でも別の項目になる）。"""
        for name, data in files.items():
            blob = git("-C", wt, "hash-object", "-w", "--stdin", input=data).decode().strip()
            git("-C", wt, "update-index", "--add", "--cacheinfo", "100644,%s,%s" % (blob, name))
        git("-C", wt, *(list(tl.AUTHOR) + ["commit", "-q", "-m", msg]))
        return git("-C", wt, "rev-parse", "HEAD").decode().strip()

    def check(self, spec, src=None):
        out = {}
        for py in pythons():
            r = subprocess.run([py, "-B", "-c", CHECKER, self.root, src or os.path.join(tl.PROJECT, "src", "sealer"),
                                json.dumps(spec)],
                               capture_output=True, env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
            self.assertEqual(r.returncode, 0, (py, r.stderr.decode()[-2000:]))
            out[py] = r.stdout.decode().strip()
        return out

    def assert_mismatch(self, out, text):
        self.assertEqual(len(out), len(pythons()))
        for py, line in out.items():
            self.assertTrue(line.startswith("MISMATCH "), (py, line))
            self.assertIn(text, line, py)


class TestForgedSrcBothPythons(ForgeBase):
    """監査の再現（重大-1）：偽る側が head の commit に Src/... を足し、記録の値をその出力に合わせる。"""

    def forge_counting(self, mode):
        """seq 6 の head に、偽の出力を書く Src/stats/counting.py を足す（src/stats/counting.py はそのまま）。"""
        wt = self.worktree(self.d1b["head"])
        real = self.real_output(wt, ledger.COUNTING_SCRIPT)
        self.assertEqual(ledger.sha256_hex(real), self.d1b["counting"]["output_sha256"])
        if mode == "definition":            # 正式な数え方 C7 の定義を変えた出力（記録の ids などはそのまま）
            d = json.loads(real.decode("utf-8"))
            for c in d["candidates"]:
                if c["id"] == "C7":
                    c["denominator_kind"], c["numerator_column"] = "docs", "v2_mentions"
            fake = json.dumps(d, sort_keys=True, ensure_ascii=False).encode("utf-8") + b"\n"
            self.assertNotEqual(fake, real)
        else:                               # 出力に1バイト足す
            fake = real + b" "
        printer = b"import sys\nsys.stdout.buffer.write(%s)\n" % repr(fake).encode("ascii")
        head = self.commit(wt, {"Src/stats/counting.py": printer}, "偽の版 Src " + mode)
        return {str(self.o1b["seq"]): {"head": head, "output_sha256": ledger.sha256_hex(fake)}}

    def test_src_counting_changed_definition(self):
        self.assert_mismatch(self.check(self.forge_counting("definition")), COUNTING_MISMATCH)

    def test_src_counting_one_more_byte(self):
        self.assert_mismatch(self.check(self.forge_counting("tail")), COUNTING_MISMATCH)

    def forge_exclusion(self):
        """seq 5 の head に Src/stats/exclusion.py（本物の先頭に、流したときだけ1バイト書く行を足したもの）を足す。
        tagrules.py が import したときは本物と同じに働くので、ほかの対象の値は変わらない。"""
        wt = self.worktree(self.d1["head"])
        real_src = git("-C", wt, "show", "HEAD:src/stats/exclusion.py")
        real = self.real_output(wt, "src/stats/exclusion.py")
        targets = {t["name"]: t["sha256"] for t in self.d1["targets"]}
        self.assertEqual(ledger.sha256_hex(real), targets["src/stats/exclusion.py の出力"])
        pre = b"import sys as _s\nif __name__ == '__main__':\n    _s.stdout.write(' ')\n    _s.stdout.flush()\n"
        head = self.commit(wt, {"Src/stats/exclusion.py": pre + real_src}, "偽の版 Src exclusion")
        return {str(self.o1["seq"]): {"head": head,
                                       "targets": {"src/stats/exclusion.py の出力": ledger.sha256_hex(b" " + real)}}}

    def test_src_exclusion_order1(self):
        self.assert_mismatch(self.check(self.forge_exclusion()), EXCLUSION_MISMATCH)

    def test_export_subst_changes_archive_bytes(self):
        """.gitattributes の export-subst で、git archive の counting.py だけを変える版（名前のぶつかりは無い）。
        files の sha256 は git show のバイト列に合わせ、output_sha256 は archive の版の出力に合わせる。
        T-059 から git archive を使わず、git show のバイト列を流すので、偽の出力と合わずに止まる。"""
        wt = self.worktree(self.d1b["head"])
        real = self.real_output(wt, ledger.COUNTING_SCRIPT)
        src = git("-C", wt, "show", "HEAD:" + ledger.COUNTING_SCRIPT)
        pre = (b"import sys as _s\nif __name__ == '__main__' and not '$Format:%H$'.startswith('$'):\n"
               b"    _s.stdout.write(' ')\n    _s.stdout.flush()\n")
        head = self.commit(wt, {ledger.COUNTING_SCRIPT: pre + src,
                                ".gitattributes": b"src/stats/counting.py export-subst\n"}, "偽の版 export-subst")
        spec = {str(self.o1b["seq"]): {"head": head, "output_sha256": ledger.sha256_hex(b" " + real),
                                        "files": {ledger.COUNTING_SCRIPT: ledger.sha256_hex(pre + src)}}}
        self.assert_mismatch(self.check(spec), COUNTING_MISMATCH)

    def test_real_heads_pass_in_checker(self):
        out = self.check({})
        for py, line in out.items():
            self.assertEqual(line, "OK", py)


class TestNameCollisions(unittest.TestCase):
    """書き出す名前のぶつかり（大文字小文字・NFC と NFD）。T-059 から、記録が縛っているファイルの名前に当てる。"""

    def stops(self, names, text=COLLISION):
        with self.assertRaisesRegex(ledger.LedgerError, text):
            verify._check_name_collisions("見本", names)

    def test_case_only(self):
        self.stops(["Src/stats/counting.py", "src/stats/counting.py"])

    def test_case_in_folder_only(self):
        self.stops(["Src/stats/a.py", "src/other.py"])

    def test_nfc_nfd(self):
        nfc = unicodedata.normalize("NFC", "src/caf\u00e9.py")
        nfd = unicodedata.normalize("NFD", nfc)
        self.assertNotEqual(nfc, nfd)
        self.stops([nfc, nfd])

    def test_case_and_normalization_together(self):
        self.stops(["src/CAF\u00c9.py", unicodedata.normalize("NFD", "src/caf\u00e9.py")])

    def test_casefold_beyond_lower(self):
        self.stops(["src/stra\u00dfe.py", "src/STRASSE.py"])

    def test_same_name_twice(self):
        self.stops(["src/a.py", "src/a.py"], "同じ名前の項目")

    def test_distinct_names_pass(self):
        verify._check_name_collisions("見本", ["src/a.py", "src/b.py", "docs/a.md"])

    def test_key(self):
        self.assertEqual(verify._name_key("Src/\u00c9"), verify._name_key("src/e\u0301"))
        self.assertNotEqual(verify._name_key("src/a"), verify._name_key("src/b"))


class TestDocT058(unittest.TestCase):
    def test_statements(self):
        with open(DOC, encoding="utf-8") as f:
            text = f.read()
        # T-059 で手の手順を、縛られたファイルだけを書く形に改めた（ls-tree での重なりの確かめと env -i の勧めは外した）
        for phrase in ("大文字小文字か Unicode の正規化（NFD にそろえて casefold。NFC と NFD は同じに扱う）",
                       'for v in $(env | sed -n', 'unset "$v"', "T-058 の名前のぶつかりの照合は、この名前に当てる形で残した"):
            self.assertIn(phrase, text)


if __name__ == "__main__":
    unittest.main()
