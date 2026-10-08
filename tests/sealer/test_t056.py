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
        self.assertEqual(self.run_with(0, lambda d: None), 2)

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

    def test_cannot_run_python_is_unchecked(self):
        """計算し直せないとき（Python で流せない）は止めずに「照らさなかった」（終了コード 0）。"""
        with mock.patch.object(verify, "_run_script",
                               side_effect=verify.Unchecked("見本：Python で流せない")):
            code, out, err = tl.run_verify_inproc(self.root, "all", "--rev", "auto")
        self.assertEqual(code, 0, err)
        self.assertIn("照らさなかった：順番1・1b の値の計算し直し（見本：Python で流せない）", out)
        self.assertIn("ただし、次は照らさなかった", out)

    def test_cli_rev_auto_recomputes_and_working_does_not(self):
        code, out, err = tl.run_verify_inproc(self.root, "stats-order", "--rev", "auto")
        self.assertEqual(code, 0, err)
        self.assertIn("順番1・1b の値：記録 2 件の head・ancestors・中身の値を、head の版から計算し直して照らした", out)
        code, out, err = tl.run_verify_inproc(self.root, "all")
        self.assertEqual(code, 0, err)
        self.assertIn("照らさなかった：順番1・1b の値の計算し直しは、--rev auto か --rev <コミット> のときだけ行う", out)

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
        for phrase in ("head の版から計算し直して照らす（T-056", "`--rev auto` か `--rev <コミット>` のとき、順番1・1b の値を",
                       "verify を使わずに手で確かめる手順", "GIT_ で始まる環境変数",
                       "書き込みの遅れの上限の目安"):
            self.assertIn(phrase, text)


if __name__ == "__main__":
    unittest.main()
