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
import io
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
                       "Python の要らない照合（必ず行う）", "cmp - before.jsonl", "D=$(mktemp -d)"):
            self.assertIn(phrase, text)


if __name__ == "__main__":
    unittest.main()
