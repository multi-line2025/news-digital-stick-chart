"""T-058 のテスト：記録の head の版を取り出して流すとき、名前のぶつかりと、流すスクリプトのフォルダの中身の
食い違いを「記録と合わない」で止めること（T-056 の監査 重大-1）。

実行（プロジェクトのルートで）:
    PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest discover -s tests/sealer -v

本物のリポジトリを一時フォルダに clone し、その記録（seq 5 の順番1、seq 6 の順番1b）の head から、偽る側が
作れる commit（Src/stats/counting.py などを足したもの）を作る。記録の値は、その偽の commit を流した出力の
sha256 に合わせて差し替える（監査の再現 scratchpad/a56r3pre3.sh と同じ形。T-056 の版の verify では「一致」の 0
になったもの）。照合は、.venv の Python と /usr/bin/python3 の両方で、別のプロセスとして流す。
本物の sealed/ には書かない。ネットワークは使わない。
"""

import io
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
from test_t056 import CloneCase, FakeRepo, make_tar, pythons  # noqa: E402

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


def git(*args, **kw):
    return subprocess.run(["git"] + list(args), check=True, capture_output=True, **kw).stdout


class TestForgedSrcBothPythons(CloneCase):
    """監査の再現（重大-1）：偽る側が head の commit に Src/... を足し、記録の値をその出力に合わせる。"""

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
        self.assert_mismatch(self.check(self.forge_counting("definition")), COLLISION)

    def test_src_counting_one_more_byte(self):
        self.assert_mismatch(self.check(self.forge_counting("tail")), COLLISION)

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
        self.assert_mismatch(self.check(self.forge_exclusion()), COLLISION)

    def test_export_subst_changes_archive_bytes(self):
        """.gitattributes の export-subst で、git archive の counting.py だけを変える版（名前のぶつかりは無い）。
        files の sha256 は git show のバイト列に合わせ、output_sha256 は archive の版の出力に合わせる。
        取り出したものと git show のバイト列の照合（完了条件2）で止まる。"""
        wt = self.worktree(self.d1b["head"])
        real = self.real_output(wt, ledger.COUNTING_SCRIPT)
        src = git("-C", wt, "show", "HEAD:" + ledger.COUNTING_SCRIPT)
        pre = (b"import sys as _s\nif __name__ == '__main__' and not '$Format:%H$'.startswith('$'):\n"
               b"    _s.stdout.write(' ')\n    _s.stdout.flush()\n")
        head = self.commit(wt, {ledger.COUNTING_SCRIPT: pre + src,
                                ".gitattributes": b"src/stats/counting.py export-subst\n"}, "偽の版 export-subst")
        spec = {str(self.o1b["seq"]): {"head": head, "output_sha256": ledger.sha256_hex(b" " + real),
                                        "files": {ledger.COUNTING_SCRIPT: ledger.sha256_hex(pre + src)}}}
        self.assert_mismatch(self.check(spec), "git show")

    def test_real_heads_pass_in_checker(self):
        out = self.check({})
        for py, line in out.items():
            self.assertEqual(line, "OK", py)


class TestCheckFolder(CloneCase):
    """check_folder：取り出したあとのフォルダの中身を git show のバイト列と照らす（本物の seq 6 の head）。"""

    def tree(self):
        tmp = tempfile.mkdtemp(dir=self.td.name)
        return verify.HeadTree(self.repo, self.st.file_json(self.o1b, ledger.ORDER1B_KIND)["head"], tmp)

    def test_real_tree_passes(self):
        t = self.tree()
        t.check_folder(ledger.COUNTING_SCRIPT)
        t.check_folder("src/stats/tagrules.py")         # 同じフォルダは一度だけ照らす

    def test_changed_module_is_mismatch(self):
        t = self.tree()
        with open(os.path.join(t.dir, "src", "stats", "exclusion.py"), "ab") as f:
            f.write(b"\n")
        with self.assertRaisesRegex(ledger.LedgerError, "git show .*のバイト列と違う"):
            t.check_folder(ledger.COUNTING_SCRIPT)

    def test_extra_file_is_mismatch(self):
        t = self.tree()
        with open(os.path.join(t.dir, "src", "stats", "json.py"), "xb") as f:
            f.write(b"raise SystemExit(0)\n")
        with self.assertRaisesRegex(ledger.LedgerError, "git の版に無いファイル"):
            t.check_folder(ledger.COUNTING_SCRIPT)

    def test_script_not_regular_file_is_mismatch(self):
        t = self.tree()
        with self.assertRaisesRegex(ledger.LedgerError, "通常のファイルとして無い"):
            t.check_folder("src/stats/no_such_script.py")


class TestNameCollisions(unittest.TestCase):
    """取り出す前の名前のぶつかり（大文字小文字・NFC と NFD）。何も書き出さずに止まる。"""

    def info(self, name, kind="file"):
        import tarfile
        i = tarfile.TarInfo(name)
        i.type = tarfile.DIRTYPE if kind == "dir" else tarfile.REGTYPE
        return i

    def stops(self, entries, text=COLLISION):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaisesRegex(ledger.LedgerError, text):
                verify.HeadTree(FakeRepo(make_tar(entries)), "e" * 40, d)
            self.assertEqual(os.listdir(d), [])

    def test_case_only(self):
        self.stops([(self.info("Src/stats/counting.py"), b"x"), (self.info("src/stats/counting.py"), b"y")])

    def test_case_in_folder_only(self):
        # 途中のフォルダの名前だけがぶつかる（ディレクトリの項目が無くても止まる）
        self.stops([(self.info("Src/stats/a.py"), b"x"), (self.info("src/other.py"), b"y")])

    def test_dir_member_vs_file(self):
        self.stops([(self.info("SRC", "dir"), None), (self.info("src/a.py"), b"y")])

    def test_nfc_nfd(self):
        nfc = unicodedata.normalize("NFC", "src/café.py")
        nfd = unicodedata.normalize("NFD", nfc)
        self.assertNotEqual(nfc, nfd)
        self.stops([(self.info(nfc), b"x"), (self.info(nfd), b"y")])

    def test_case_and_normalization_together(self):
        self.stops([(self.info("src/CAFÉ.py"), b"x"),
                    (self.info(unicodedata.normalize("NFD", "src/café.py")), b"y")])

    def test_casefold_beyond_lower(self):
        # casefold でそろう名前（ß と ss）
        self.stops([(self.info("src/straße.py"), b"x"), (self.info("src/STRASSE.py"), b"y")])

    def test_same_name_twice(self):
        self.stops([(self.info("src/a.py"), b"x"), (self.info("src/a.py"), b"y")], "同じ名前の項目")

    def test_distinct_names_pass(self):
        with tempfile.TemporaryDirectory() as d:
            t = verify.HeadTree(FakeRepo(make_tar([(self.info("src", "dir"), None),
                                                   (self.info("src/a.py"), b"x"),
                                                   (self.info("src/b.py"), b"y")])), "f" * 40, d)
            self.assertEqual(sorted(os.listdir(os.path.join(t.dir, "src"))), ["a.py", "b.py"])

    def test_key(self):
        self.assertEqual(verify._name_key("Src/É"), verify._name_key("src/é"))
        self.assertNotEqual(verify._name_key("src/a"), verify._name_key("src/b"))


class TestDocT058(unittest.TestCase):
    def test_statements(self):
        with open(DOC, encoding="utf-8") as f:
            text = f.read()
        for phrase in ('git ls-tree -r --name-only "${H}"', "大文字小文字だけが違う名前",
                       "env -i", "unset", "git show のバイト列と照らす",
                       "大文字小文字と Unicode の正規化"):
            self.assertIn(phrase, text)


if __name__ == "__main__":
    unittest.main()
