"""T-056 のテスト：verify が順番1・1b の値を、記録の head の版から計算し直して照らすこと
（T-055 の監査 中-1、T-048 の軽-1）と、git を固定した環境で動かすこと（T-054 の軽-1）。

実行（プロジェクトのルートで）:
    PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest discover -s tests/sealer -v

本物のリポジトリを一時フォルダに clone し、その記録（seq 5 の順番1、seq 6 の順番1b）を使う。
中身を書き換えた場合は、記録の連なりを作り直さずに、verify の照合の関数（verify.recompute_orders）に、
書き換えた中身を返す読み方を渡して確かめる（監査の再現と同じ値の書き換え）。本物の sealed/ には書かない。
ネットワークは使わない。
"""

import copy
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import test_ledger as tl  # noqa: E402

ledger = tl.ledger
verify = tl.verify
DOC = os.path.join(tl.PROJECT, "docs", "verify", "periods-seal.md")


def real_orders(records):
    return ([r for r in records if r["kind"] == ledger.ORDER1_KIND],
            [r for r in records if r["kind"] == ledger.ORDER1B_KIND])


class CloneCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.td = tempfile.TemporaryDirectory()        # TMPDIR の下。クラスが終わると片づく
        cls.root = os.path.join(cls.td.name, "clone")
        subprocess.run(["git", "clone", "-q", tl.PROJECT, cls.root], check=True, capture_output=True)
        cls.st = verify.State(cls.root, None)
        cls.repo = verify.Repo(cls.root)
        o1, o1b = real_orders(cls.st.records)
        if not o1 or not o1b:
            raise unittest.SkipTest("本物の記録に順番1・1b が無い")
        cls.o1, cls.o1b = o1[0], o1b[0]

    @classmethod
    def tearDownClass(cls):
        cls.td.cleanup()

    def run_with(self, seq, mutate):
        """seq の記録の中身を mutate で書き換えた読み方で、recompute_orders を動かす。"""
        orig = self.st.file_json

        def file_json(r, role):
            doc = orig(r, role)
            if r["seq"] == seq:
                doc = copy.deepcopy(doc)
                mutate(doc)
            return doc
        with mock.patch.object(self.st, "file_json", file_json):
            got = {"order1": [self.o1], "order1b": [self.o1b]}
            return verify.recompute_orders(self.st, self.repo, got)


class TestRecomputeReal(CloneCase):
    def test_real_records_pass(self):
        n, missed = self.run_with(0, lambda d: None)
        self.assertEqual(missed, [])
        self.assertEqual(n, 25)     # 順番1：head 1・ancestors 4・対象 10、順番1b：head 1・ancestors 3・files 4・order1_ref 1・counting 1

    def test_tampered_values_fail(self):
        """監査の再現：中身の値を一つずつ書き換えると、verify の照合が止まる。"""
        s1, s1b = self.o1["seq"], self.o1b["seq"]
        other = subprocess.run(["git", "-C", self.root, "rev-parse", "HEAD"], check=True,
                               capture_output=True).stdout.decode().strip()

        def set_(path, value):
            def m(d):
                x = d
                for k in path[:-1]:
                    x = x[k]
                x[path[-1]] = value
            return m
        cases = [
            (s1b, set_(["files", 0, "sha256"], "0" * 64), "files の docs/stats/counting.md の sha256"),
            (s1b, set_(["order1_ref", "seq"], s1b), "order1_ref"),
            (s1b, set_(["order1_ref", "record_sha256"], "0" * 64), "order1_ref"),
            (s1b, set_(["counting", "output_sha256"], "0" * 64), "counting.output_sha256"),
            (s1b, set_(["counting", "candidate_ids"], ["C1", "C7"]), "counting.candidate_ids"),
            (s1b, set_(["counting", "criteria_ids"], ["B1"]), "counting.criteria_ids"),
            (s1b, set_(["head"], other), "の版の sealed/ledger.jsonl が、この記録を足す直前の記録"),
            (s1b, set_(["head"], "1" * 40), "の commit が、このリポジトリに無い"),
            (s1b, set_(["ancestors"], [other]), "の祖先でない"),
            (s1, set_(["targets", 1, "sha256"], "0" * 64), "の対象 src/stats/exclusion.py の出力 の sha256"),
            (s1, set_(["targets", 7, "sha256"], "0" * 64), "の対象 1cb463a:src/stats/tagrules.py の sha256"),
            (s1, set_(["targets", 8, "sha256"], "0" * 64), "の対象 1cb463a:src/stats/tagrules.py の出力"),
            (s1, set_(["head"], other), "の版の sealed/ledger.jsonl が、この記録を足す直前の記録"),
            (s1, set_(["ancestors"], [other]), "の祖先でない"),
        ]
        for seq, mutate, msg in cases:
            with self.subTest(seq=seq, msg=msg):
                with self.assertRaises(ledger.LedgerError) as cm:
                    self.run_with(seq, mutate)
                self.assertIn(msg, str(cm.exception))

    PYTHON_ITEMS = ("seq 5 の順番1 の対象「src/stats/exclusion.py の出力」（見本）",
                    "seq 5 の順番1 の対象「src/stats/tagrules.py の出力」（見本）",
                    "seq 5 の順番1 の対象「1cb463a:src/stats/tagrules.py の出力」（見本）",
                    "seq 6 の stats-order1b の counting（counting.py の出力）（見本）")

    def test_cannot_run_python_is_unchecked(self):
        """利用者の環境の都合（Python を起動できない）は止めずに「照らさなかった」（終了コード 0）。
        照らさなかった項目は、項目ごとに列挙する（T-056 差し戻し1回目 中-2）。"""
        with mock.patch.object(verify, "_run_script", side_effect=verify.Unchecked("見本")):
            n, missed = self.run_with(0, lambda d: None)
            code, out, err = tl.run_verify_inproc(self.root, "all", "--rev", "auto")
        self.assertEqual(missed, list(self.PYTHON_ITEMS))
        self.assertEqual(n, 21)     # Python の要らない照合は、すべて行った
        self.assertEqual(code, 0, err)
        for item in self.PYTHON_ITEMS:
            self.assertIn("照らさなかった：順番1・1b の値：%s" % item, out)
        self.assertIn("ただし、次は照らさなかった", out)

    def test_python_free_checks_continue_when_unchecked(self):
        """Python で流せなくても、Python の要らない照合（files・head・ancestors・order1_ref・順番1 のファイル）は
        行い、合わなければ止まる（中-2）。"""
        s1, s1b = self.o1["seq"], self.o1b["seq"]
        cases = [
            (s1b, lambda d: d["files"][0].__setitem__("sha256", "0" * 64), "files の docs/stats/counting.md"),
            (s1b, lambda d: d["order1_ref"].__setitem__("seq", s1b), "order1_ref"),
            (s1b, lambda d: d.__setitem__("ancestors", ["1" * 40]), "の祖先でない"),
            (s1, lambda d: d["targets"][0].__setitem__("sha256", "0" * 64), "の対象 src/stats/exclusion.py の sha256"),
            (s1, lambda d: d["targets"][9].__setitem__("sha256", "0" * 64), "の対象 2d23cdf:reviews/T-020.md の sha256"),
        ]
        with mock.patch.object(verify, "_run_script", side_effect=verify.Unchecked("見本")):
            for seq, mutate, msg in cases:
                with self.subTest(msg=msg):
                    with self.assertRaises(ledger.LedgerError) as cm:
                        self.run_with(seq, mutate)
                    self.assertIn(msg, str(cm.exception))

    def test_audit_a56dg_failing_script_is_mismatch(self):
        """監査の再現（scratchpad/a56dg）：head の版の counting.py が SystemExit(3) で終わる commit を作り、
        counting の値を偽った記録は、「照らさなかった」ではなく「記録と合わない」で止まる。"""
        s1b = self.o1b["seq"]
        real_head = self.st.file_json(self.o1b, ledger.ORDER1B_KIND)["head"]
        with tempfile.TemporaryDirectory() as d:
            wt = os.path.join(d, "wt")
            subprocess.run(["git", "-C", self.root, "worktree", "add", "-q", "--detach", wt, real_head],
                           check=True, capture_output=True)
            bad = b"raise SystemExit(3)\n"
            with open(os.path.join(wt, "src", "stats", "counting.py"), "wb") as f:
                f.write(bad)
            subprocess.run(["git", "-C", wt] + list(tl.AUTHOR) + ["commit", "-q", "-am", "偽の版"],
                           check=True, capture_output=True)
            fake = subprocess.run(["git", "-C", wt, "rev-parse", "HEAD"], check=True,
                                  capture_output=True).stdout.decode().strip()

            def mutate(doc):
                doc["head"] = fake
                for f in doc["files"]:
                    if f["path"] == "src/stats/counting.py":
                        f["sha256"] = ledger.sha256_hex(bad)
                doc["counting"]["output_sha256"] = "f" * 64
                doc["counting"]["candidate_ids"] = ["C7"]
            with self.assertRaises(ledger.LedgerError) as cm:
                self.run_with(s1b, mutate)
            self.assertIn("head の版の src/stats/counting.py が終了コード 3 で終わった", str(cm.exception))

    def test_cli_rev_auto_recomputes_and_working_does_not(self):
        code, out, err = tl.run_verify_inproc(self.root, "stats-order", "--rev", "auto")
        self.assertEqual(code, 0, err)
        self.assertIn("順番1・1b の値：記録 2 件について、25 項目を head の版から計算し直して照らした", out)
        code, out, err = tl.run_verify_inproc(self.root, "all")
        self.assertEqual(code, 0, err)
        self.assertIn("照らさなかった：順番1・1b の値の計算し直しは、--rev working では行わない（--rev auto で照らす）", out)

    def test_no_git_is_unchecked(self):
        with tempfile.TemporaryDirectory() as d:
            import shutil
            nogit = os.path.join(d, "p")
            shutil.copytree(self.root, nogit, ignore=shutil.ignore_patterns(".git"))
            code, out, err = tl.run_verify_inproc(nogit, "all", "--rev", "working")
        self.assertEqual(code, 0, err)
        self.assertIn("照らさなかった：git の履歴が無いので、順番1・1b の値を head の版から計算し直していない", out)


# 監査の再現（scratchpad/a56r1mk.sh、a56r1_shortto.py）を、.venv と /usr/bin/python3 の両方で確かめる。
# 子のプロセスで verify.recompute_orders を動かし、記録の中身を書き換えた読み方を渡す（記録の連なりは作り直さない）。
CHECKER = r"""
import sys, copy
root, src, seq, head, files_sha, out_sha, timeout = sys.argv[1:8]
sys.path.insert(0, src)
import verify, ledger
verify.RUN_TIMEOUT_SECONDS = float(timeout)
st = verify.State(root, None)
repo = verify.Repo(root)
orig = st.file_json
def fj(r, role):
    d = orig(r, role)
    if r["seq"] == int(seq):
        d = copy.deepcopy(d)
        d["head"] = head
        for f in d["files"]:
            if f["path"] == "src/stats/counting.py":
                f["sha256"] = files_sha
        d["counting"]["output_sha256"] = out_sha
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


_PYTHONS = None


def pythons():
    """照合を流す Python の一覧。プロジェクトの .venv（3.14）と /usr/bin/python3（3.9）を、版の重ならない形で
    返す（T-068。T-065 の監査 軽微6：/usr/bin/python3 でテストを流しても、3.14 も確かめる）。"""
    global _PYTHONS
    if _PYTHONS is None:
        cands = [sys.executable, os.path.join(tl.PROJECT, ".venv", "bin", "python"), "/usr/bin/python3"]
        out, seen = [], set()
        for py in cands:
            if not os.path.exists(py):
                continue
            r = subprocess.run([py, "-B", "-c", "import sys; print(sys.version)"], capture_output=True)
            v = r.stdout.strip()
            if r.returncode == 0 and v not in seen:
                seen.add(v)
                out.append(py)
        _PYTHONS = out
    return _PYTHONS


class TestForgedHeadsBothPythons(CloneCase):
    """T-056 再提出1回目 中-A：記録を作る側の commit の中身で起こせることは、「照らさなかった」ではなく
    「記録と合わない」で止まる（書き出せない名前は飛ばして続け、時間切れは合わない）。"""

    def forge(self, name, counting=None, extra=None):
        """seq 6 の head（本物）から、counting.py と余分な項目を変えた commit を作る。返り値: (commit, counting.py の sha256)。"""
        real_head = self.st.file_json(self.o1b, ledger.ORDER1B_KIND)["head"]
        wt = os.path.join(self.td.name, "wt-" + name)
        subprocess.run(["git", "-C", self.root, "worktree", "add", "-q", "--detach", wt, real_head],
                       check=True, capture_output=True)
        if counting is not None:
            with open(os.path.join(wt, "src", "stats", "counting.py"), "wb") as f:
                f.write(counting)
            subprocess.run(["git", "-C", wt, "add", "src/stats/counting.py"], check=True, capture_output=True)
        if extra is not None:
            blob = subprocess.run(["git", "-C", wt, "hash-object", "-w", "--stdin"], input=b"x\n",
                                  check=True, capture_output=True).stdout.decode().strip()
            subprocess.run(["git", "-C", wt, "update-index", "--add", "--cacheinfo",
                            "100644,%s,%s" % (blob, extra)], check=True, capture_output=True)
        subprocess.run(["git", "-C", wt] + list(tl.AUTHOR) + ["commit", "-q", "-m", "偽の版 " + name],
                       check=True, capture_output=True)
        head = subprocess.run(["git", "-C", wt, "rev-parse", "HEAD"], check=True,
                              capture_output=True).stdout.decode().strip()
        data = subprocess.run(["git", "-C", self.root, "show", head + ":src/stats/counting.py"],
                              check=True, capture_output=True).stdout
        return head, ledger.sha256_hex(data)

    def check(self, head, files_sha, timeout="1800"):
        out = {}
        for py in pythons():
            r = subprocess.run([py, "-B", "-c", CHECKER, self.root, os.path.join(tl.PROJECT, "src", "sealer"),
                                str(self.o1b["seq"]), head, files_sha, "9" * 64, timeout],
                               capture_output=True, env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
            self.assertEqual(r.returncode, 0, (py, r.stderr.decode()[-2000:]))
            out[py] = r.stdout.decode().strip()
        return out

    def assert_mismatch(self, out, text=None):
        for py, line in out.items():
            self.assertTrue(line.startswith("MISMATCH "), (py, line))
            if text is not None:
                self.assertIn(text, line, py)

    def test_long_name(self):
        """「zz/」＋300 文字の名前（書き出せない）を含む版：飛ばして続け、偽の output_sha256 で止まる。"""
        head, sha = self.forge("long", extra="zz/" + "a" * 300)
        self.assert_mismatch(self.check(head, sha), "counting.output_sha256")

    def test_name_colliding_with_src(self):
        """src/ とぶつかる「Src」（大文字小文字を区別しないファイルシステムで）を含む版も止まる。"""
        head, sha = self.forge("case", extra="Src")
        self.assert_mismatch(self.check(head, sha))

    def test_non_utf8_name(self):
        """UTF-8 でない名前を含む版も止まる。"""
        head, sha = self.forge("bad", extra=os.fsdecode(b"zz/\xff\xfe"))
        self.assert_mismatch(self.check(head, sha), "counting.output_sha256")

    def test_timeout_is_mismatch(self):
        """終わらない counting.py（時間切れ）は「記録と合わない」で止まる（上限は短く差し替えて確かめる）。"""
        head, sha = self.forge("loop", counting=b"while True:\n    pass\n")
        self.assert_mismatch(self.check(head, sha, timeout="3"), "上限の中に終わらなかった")

    def test_unforged_head_passes_in_checker(self):
        real_head = self.st.file_json(self.o1b, ledger.ORDER1B_KIND)["head"]
        files = {f["path"]: f["sha256"] for f in self.st.file_json(self.o1b, ledger.ORDER1B_KIND)["files"]}
        out = self.check(real_head, files["src/stats/counting.py"])
        self.assert_mismatch(out, "counting.output_sha256")     # 偽の output_sha256 だけで止まる


class ShowRepo:
    """git show <commit>:<path> だけに答えるリポジトリの代わり（_BoundDir の直接の確かめ）。T-059。"""

    def __init__(self, blobs):
        self.blobs = blobs              # {(commit, path): バイト列}
        self.calls = []

    def git(self, *args, env=None):
        self.calls.append(args)
        if args[0] == "show" and len(args) == 2:
            commit, path = args[1].split(":", 1)
            if (commit, path) in self.blobs:
                return self.blobs[(commit, path)]
        raise ledger.LedgerError("git %s が失敗した" % " ".join(args[:2]))


class TestBoundDir(unittest.TestCase):
    """T-056 再提出1回目 軽-B の確かめを、T-059 の形（記録が縛っているファイルだけを git show から書き出す）に
    置き換えた。git archive は使わない。"""

    C = "a" * 40

    def test_bound_path_ok(self):
        for p in ("a.py", "src/stats/x.py"):
            self.assertTrue(verify._bound_path_ok(p), p)
        for p in ("/etc/passwd", "../x", "a/../../x", "a\\b", "", "a//b", "./a", "a/", "a\x00b"):
            self.assertFalse(verify._bound_path_ok(p), p)

    def test_writes_only_bound_files(self):
        blobs = {(self.C, "src/stats/a.py"): b"print(1)\n", (self.C, "src/stats/b.py"): b"x = 2\n",
                 (self.C, "src/stats/__pycache__/a.cpython-39.pyc"): b"pyc"}
        files = [(p, ledger.sha256_hex(blobs[(self.C, p)])) for p in ("src/stats/a.py", "src/stats/b.py")]
        repo = ShowRepo(blobs)
        with tempfile.TemporaryDirectory() as d:
            b = verify._BoundDir(repo, self.C, files, d, "見本")
            found = []
            for root, dirs, names in os.walk(b.dir):
                found += [os.path.relpath(os.path.join(root, n), b.dir) for n in names]
            self.assertEqual(sorted(found), [os.path.join("src", "stats", "a.py"), os.path.join("src", "stats", "b.py")])
            self.assertEqual(os.listdir(d), [os.path.basename(b.dir)])     # 書いたのは、その中だけ
            self.assertTrue(all(c[0] == "show" for c in repo.calls))      # git archive は使わない
            self.assertEqual(b.run("src/stats/a.py", "見本"), b"1\n")
            with self.assertRaisesRegex(ledger.LedgerError, "縛っていない"):
                b.run("src/stats/__pycache__/a.cpython-39.pyc", "見本")

    def test_stops(self):
        blobs = {(self.C, "src/a.py"): b"x", (self.C, "Src/a.py"): b"y"}
        good = ledger.sha256_hex(b"x")
        cases = [
            ([("src/a.py", "0" * 64)], "の sha256"),                                      # 記録の sha256 と違う
            ([("src/missing.py", good)], "無い"),                                           # git の版に無い
            ([("src/a.py", good), ("Src/a.py", ledger.sha256_hex(b"y"))], "大文字小文字"),     # 名前のぶつかり
            ([("src/a.py", good), ("src/a.py", good)], "同じ名前"),
            ([("../a.py", good)], "相対パスでない"),
        ]
        for files, text in cases:
            with self.subTest(text=text):
                with tempfile.TemporaryDirectory() as d:
                    with self.assertRaisesRegex(ledger.LedgerError, text):
                        verify._BoundDir(ShowRepo(blobs), self.C, files, d, "見本")

    def test_timeout_and_launch_failure(self):
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "loop.py"), "w") as f:
                f.write("while True:\n    pass\n")
            with mock.patch.object(verify, "RUN_TIMEOUT_SECONDS", 1):
                with self.assertRaisesRegex(ledger.LedgerError, "上限の中に終わらなかった"):
                    verify._run_script(d, "loop.py", "見本")
            with mock.patch.object(verify.sys, "executable", os.path.join(d, "no-python")):
                with self.assertRaises(verify.Unchecked):
                    verify._run_script(d, "loop.py", "見本")


class TestFixedGitEnv(unittest.TestCase):
    def test_fixed_env(self):
        """T-054 の軽-1：GIT_ で始まる環境変数を除き、決めた2つだけを入れる。"""
        with mock.patch.dict(os.environ, {"GIT_DIR": "/x", "GIT_WORK_TREE": "/y", "GIT_SHALLOW_FILE": "/z"}):
            env = ledger.fixed_git_env()
        self.assertEqual(sorted(k for k in env if k.startswith("GIT_")),
                         ["GIT_GRAFT_FILE", "GIT_NO_REPLACE_OBJECTS"])
        self.assertEqual(env["GIT_NO_REPLACE_OBJECTS"], "1")
        self.assertFalse(os.path.exists(env["GIT_GRAFT_FILE"]))


class TestDocT056(unittest.TestCase):
    def test_statements(self):
        with open(DOC, encoding="utf-8") as f:
            text = f.read()
        for phrase in ("head の版から計算し直して照らす（T-056", "コミットを渡しても同じで、その値は使わない",
                       "verify を使わずに手で確かめる手順", "GIT_ で始まる環境変数",
                       "書き込みの遅れの上限の目安", "Python 3.14.2（`.venv/bin/python`）と 3.9.6",
                       "隔離した環境", "ネットワークを切って流す", "「記録と合わない」として終了コード 1 で止める",
                       "Python の要らない照合（必ず行う）", "cmp - before.jsonl", 'D=$(mktemp -d "${TMPDIR:-/tmp}/verify.XXXXXX")',
                       "記録を作る側の commit の中身で起こせることは、どれも「照らさなかった」にしない",
                       "Python を起動できない、git の履歴が無い、の2つに限る",
                       "export GIT_NO_REPLACE_OBJECTS=1 GIT_GRAFT_FILE=/dev/null/no-graft-file"):
            self.assertIn(phrase, text)


if __name__ == "__main__":
    unittest.main()
