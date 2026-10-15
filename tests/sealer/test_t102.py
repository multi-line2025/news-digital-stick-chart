"""T-102 のテスト：区分表の取り直し（収集係の T-101。オーナーの承認は reviews/T-098.md）のマニフェストを、照合
（ledger.check_themes_manifest_refs と verify.check_themes_attempt_code）で受け付ける。

実行（プロジェクトのルートで）:
    PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -B -m unittest discover -s tests/sealer -v

本物の記録とマニフェストは、固定したコミット（fixed_records.THEMES_FAILED_COMMIT）を git から取り出して使う。書くのは一時の
フォルダ（clone）の中だけ。収集係の src/collector/themes.py は、定数を照らすために読み込むだけ（変えない）。
"""

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import fixed_records  # noqa: E402
import test_ledger as tl  # noqa: E402
import test_t099 as t99  # noqa: E402

ledger = tl.ledger
verify = tl.verify
C = fixed_records.THEMES_FAILED_COMMIT
REL = ledger.THEMES_MANIFEST
THEMES_PY = os.path.join(tl.PROJECT, "src", "collector", "themes.py")


def load_themes():
    spec = importlib.util.spec_from_file_location("themes_for_t102", THEMES_PY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestConstants(unittest.TestCase):
    """収集係の themes.py は、作業ツリーのファイルを読む（HEAD の版を git から読むのではない。T-104 軽-3）。
    理由：tests/sealer の規則（15章。tests/sealer/test_t077.py の TestRuleScan）は、プロジェクトの HEAD を git で読むことを、
    許可した数か所だけに限っている。コード（src/ の下）は作業ツリーのファイルとして読んでよい。そのため、収集係がコミットの前に
    themes.py を変えている間は、まだコミットしていない版と照らすことになる。合否は、コミットしたあと（作業ツリーが HEAD と
    同じとき）に流した結果で判断する。"""

    def test_same_as_themes(self):
        """上限と並びが、収集係の themes.py の値（MAX_TOTAL_ATTEMPTS・MANIFEST_NEXT）とちょうど同じ。"""
        th = load_themes()
        self.assertEqual(ledger.THEMES_MAX_ATTEMPTS, th.MAX_TOTAL_ATTEMPTS)
        self.assertEqual(ledger.THEMES_MAX_ATTEMPTS, 3)
        self.assertEqual(ledger.THEMES_NEXT, th.MANIFEST_NEXT)
        self.assertEqual(ledger.THEMES_FAILED_STAGES, th.FAILED_STAGES)


class Retry(unittest.TestCase):
    """本物の3行（attempt・fetch・failed）のあとに、取り直しの行を足した形。2回目・3回目の attempt は、コードの版が違ってよい。
    行の元は test_t099.Unit と同じ（そのテストは継がない）。"""

    check = t99.Unit.check

    @classmethod
    def setUpClass(cls):
        t99.Unit.setUpClass.__func__(cls)
        a, f, fl = cls.attempt, cls.fetch, cls.failed
        cls.a2 = dict(a, attempted_at="2026-10-16T01:00:00Z", code_sha256="b" * 64)
        cls.f2 = dict(f, at="2026-10-16T02:00:00Z", code_sha256="b" * 64)
        cls.fl2 = dict(fl, at="2026-10-16T02:00:01Z", stage="shape")
        cls.a3 = dict(a, attempted_at="2026-10-17T01:00:00Z", code_sha256="c" * 64)
        cls.f3 = dict(f, at="2026-10-17T02:00:00Z", code_sha256="c" * 64)
        cls.r3 = dict(cls.result, fetched_at="2026-10-17T02:00:01Z", attempted_at=cls.a3["attempted_at"],
                      code_sha256="c" * 64)
        cls.fl3 = dict(fl, at="2026-10-17T02:00:01Z", stage="fetch")

    def test_honest_retries(self):
        a, f, fl = self.attempt, self.fetch, self.failed
        self.assertEqual(self.check([a, f, fl, self.a2]), 2)
        self.assertEqual(self.check([a, f, fl, self.a2, self.f2, self.fl2]), 2)
        self.assertEqual(self.check([a, f, fl, self.a2, self.f2, self.fl2, self.a3, self.f3, self.r3]), 4)
        self.assertEqual(self.check([a, f, fl, self.a2, self.f2, self.fl2, self.a3, self.f3, self.fl3]), 3)

    def test_failed_with_stage(self):
        """T-101 差し戻し1回目からの failed の行（stage を持つ）も、stage の無い1回目の行も受け付ける。決まった語でない stage は止まる。"""
        a, f, fl = self.attempt, self.fetch, self.failed
        for st in ledger.THEMES_FAILED_STAGES:
            with self.subTest(stage=st):
                self.assertEqual(self.check([a, f, fl, self.a2, self.f2, dict(self.fl2, stage=st)]), 2)
        with self.assertRaisesRegex(ledger.LedgerError, "6 行目（failed）の stage が"):
            self.check([a, f, fl, self.a2, self.f2, dict(self.fl2, stage="人の名前")])

    def test_failed_form_follows_attempt_code(self):
        """T-103（T-101 の監査 軽-3）：stage の無い古い形の failed は、73877f10… の版の attempt のあとだけ。ほかの版の attempt の
        あとは stage のある形を求め、73877f10… の版のあとに stage のある形も止める。"""
        a, f, fl = self.attempt, self.fetch, self.failed
        self.assertEqual(a["code_sha256"], ledger.THEMES_LEGACY_FAILED_CODE_SHA256)
        legacy_after_new = {k: v for k, v in self.fl2.items() if k != "stage"}
        with self.assertRaisesRegex(ledger.LedgerError, "6 行目（failed）の形が、直前の attempt のコードの版に合わない"):
            self.check([a, f, fl, self.a2, self.f2, legacy_after_new])
        with self.assertRaisesRegex(ledger.LedgerError, "3 行目（failed）の形が、直前の attempt のコードの版に合わない"):
            self.check([a, f, dict(fl, stage="shape")])
        # 取り直しで同じ古い版を使った attempt のあとなら、古い形を許す
        a2_old = dict(self.a2, code_sha256=a["code_sha256"])
        self.assertEqual(self.check([a, f, fl, a2_old, dict(self.f2, code_sha256=a["code_sha256"]),
                                     dict(fl, at="2026-10-16T02:00:01Z")]), 2)

    def test_over_limit(self):
        a, f, fl = self.attempt, self.fetch, self.failed
        a4 = dict(a, attempted_at="2026-10-18T00:00:00Z")
        with self.assertRaisesRegex(ledger.LedgerError, "10 行目：attempt の行が上限の 3 行を超える"):
            self.check([a, f, fl, self.a2, self.f2, self.fl2, self.a3, self.f3, self.fl3, a4])

    def test_order_broken(self):
        a, f, fl = self.attempt, self.fetch, self.failed
        cases = {
            "failed のあとに fetch": [a, f, fl, self.f2],
            "failed のあとに result": [a, f, fl, self.r3],
            "attempt のあとに attempt": [a, f, fl, self.a2, self.a3],
            "result のあとに attempt": [a, f, fl, self.a2, self.f2, dict(self.r3, attempted_at=self.a2["attempted_at"],
                                                                       code_sha256="b" * 64), self.a3],
            "fetch のあとに attempt": [a, f, self.a2],
        }
        for name, rows in cases.items():
            with self.subTest(name=name), self.assertRaisesRegex(ledger.LedgerError, "の並びが違う"):
                self.check(rows)

    def test_fetch_result_follow_last_attempt(self):
        """fetch・result は、直前の attempt と照らす（最初の attempt ではない）。"""
        a, f, fl = self.attempt, self.fetch, self.failed
        cases = {
            "fetch の code_sha256 が最初の attempt の値": ([a, f, fl, self.a2, f], "5 行目（fetch）の code_sha256 が、直前の attempt"),
            "result の code_sha256 が前の attempt の値": ([a, f, fl, self.a2, self.f2, self.fl2, self.a3, self.f3,
                                                         dict(self.r3, code_sha256="b" * 64)], "9 行目（result）の code_sha256"),
            "result の attempted_at が最初の attempt の値": ([a, f, fl, self.a2, self.f2, self.fl2, self.a3, self.f3,
                                                           dict(self.r3, attempted_at=a["attempted_at"])],
                                                          "9 行目（result）の code_path・source_url・attempted_at"),
            "時刻が戻る取り直し": ([a, f, fl, dict(self.a2, attempted_at="2026-10-14T00:00:00Z")], "前の行の時刻より前"),
        }
        for name, (rows, text) in cases.items():
            with self.subTest(name=name), self.assertRaisesRegex(ledger.LedgerError, text):
                self.check(rows)

    def test_each_attempt_refs(self):
        """取り直しの attempt の除外の規則の参照も、記録と照らす。"""
        a, f, fl = self.attempt, self.fetch, self.failed
        for k, v in (("exclusion_rule_seq", 1), ("exclusion_rule_record_sha256", "0" * 64)):
            with self.subTest(key=k), self.assertRaisesRegex(ledger.LedgerError, "4 行目の exclusion_rule_seq"):
                self.check([a, f, fl, dict(self.a2, **{k: v})])


class RetryClone(unittest.TestCase):
    """固定したコミットの clone に取り直しの行を足してコミットし、verify all --rev auto で照らす（attempt の code_sha256 は git の
    履歴の themes.py の版）。"""

    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.addCleanup(self.td.cleanup)
        self.c = os.path.join(self.td.name, "c")
        code = "worktree" if os.environ.get("SEALER_DOC_TEST_WORKTREE") == "1" else "head"
        fixed_records.checkout(self.c, C, code=code)

    def git(self, *args):
        return subprocess.run(["git", "-C", self.c] + list(tl.AUTHOR) + list(args), check=True,
                              capture_output=True).stdout

    def rows(self):
        with open(os.path.join(self.c, REL), "rb") as f:
            return t99.rows_of(f.read())

    def append(self, *rows, commit=True):
        with open(os.path.join(self.c, REL), "ab") as f:
            f.write(t99.body_of(list(rows)))
        if commit:
            self.git("add", "--", REL)
            self.git("commit", "-q", "-m", "取り直しの行（テスト）")

    def themes_sha(self):
        return ledger.sha256_hex(self.git("cat-file", "blob", "HEAD:src/collector/themes.py"))

    def verify(self, *args):
        return tl.run_verify_inproc(self.c, *(args or ("all", "--rev", "auto")))

    def test_honest_retry_verified(self):
        a = self.rows()[0]
        a2 = dict(a, attempted_at="2026-10-16T01:00:00Z", code_sha256=self.themes_sha())
        self.append(a2)
        rc, out, err = self.verify()
        self.assertEqual(rc, 0, err)
        self.assertIn("attempt の行 2 行の code_sha256 は、その行を初めて含んだコミットの版の themes.py と同じ", out)
        self.append({"kind": "fetch", "at": "2026-10-16T02:00:00Z", "code_sha256": a2["code_sha256"]},
                    {"kind": "failed", "at": "2026-10-16T02:00:01Z", "reason": "ThemesError"})
        rc, out, err = self.verify()
        self.assertEqual(rc, 0, err)

    def test_attempt_code_not_in_history(self):
        """attempt の code_sha256 が、その行をコミットした時点の themes.py の版でなければ止まる。"""
        a = self.rows()[0]
        self.append(dict(a, attempted_at="2026-10-16T01:00:00Z", code_sha256="d" * 64))
        rc, _out, err = self.verify("stats-order")
        self.assertEqual(rc, 1)
        self.assertIn("その行を初めて含んだコミット", err)

    def test_uncommitted_attempt_unchecked(self):
        """まだコミットしていない attempt の行の code_sha256 は「照らさなかった」（終了コード 0）。"""
        a = self.rows()[0]
        self.append(dict(a, attempted_at="2026-10-16T01:00:00Z", code_sha256="d" * 64), commit=False)
        rc, out, err = self.verify("stats-order")
        self.assertEqual(rc, 0, err)
        self.assertIn("照らさなかった：区分表のマニフェストの attempt の行（attempted_at 2026-10-16T01:00:00Z）の code_sha256", out)

    def test_over_limit_verified(self):
        a, f, fl = self.rows()
        sha = self.themes_sha()
        more = []
        for d in ("16", "17", "18"):
            more += [dict(a, attempted_at="2026-10-%sT01:00:00Z" % d, code_sha256=sha),
                     {"kind": "fetch", "at": "2026-10-%sT02:00:00Z" % d, "code_sha256": sha},
                     {"kind": "failed", "at": "2026-10-%sT02:00:01Z" % d, "reason": "ThemesError"}]
        # T-104：試行の行と、fetch・failed の組を、themes.py と同じく別々のコミットにする
        for rows in (more[0:1], more[1:3], more[3:4], more[4:6]):
            self.append(*rows)
        rc, _out, err = self.verify("stats-order")
        self.assertEqual(rc, 0, err)
        self.append(more[6])
        rc, _out, err = self.verify("stats-order")
        self.assertEqual(rc, 1)
        self.assertIn("attempt の行が上限の 3 行を超える", err)


if __name__ == "__main__":
    unittest.main()
