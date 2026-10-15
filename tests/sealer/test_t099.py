"""T-099 のテスト：区分表のマニフェスト（data/manifest/gdelt-themes.jsonl）の行の照合（ledger.check_themes_manifest_refs）を、
収集係の themes.py の行の取り決めに合わせた。attempt と result の行には exclusion_rule_seq・exclusion_rule_record_sha256 を
求め、fetch・failed の行には求めない。そのかわり、行の形と並び（attempt → fetch → failed か result）を照らす。

実行（プロジェクトのルートで）:
    PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -B -m unittest discover -s tests/sealer -v

本物の記録は、固定したコミット（fixed_records.THEMES_FAILED_COMMIT。T-098 の attempt・fetch・failed の3行）を git から
取り出して使う。書くのは一時のフォルダ（clone）の中だけ。ネットワークは使わない。
"""

import json
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import fixed_records  # noqa: E402
import test_ledger as tl  # noqa: E402

ledger = tl.ledger
C = fixed_records.THEMES_FAILED_COMMIT
REL = ledger.THEMES_MANIFEST


def rows_of(body):
    return [json.loads(x) for x in body.split(b"\n") if x.strip()]


def body_of(rows):
    return b"".join((json.dumps(r, sort_keys=True) + "\n").encode("ascii") for r in rows)


class Unit(unittest.TestCase):
    """本物の記録（seq 1〜14）と、本物のマニフェストの3行から作った形で、照合だけを確かめる。"""

    @classmethod
    def setUpClass(cls):
        cls.records = ledger.verify_chain(fixed_records.show("sealed/ledger.jsonl", C))
        cls.real = rows_of(fixed_records.show(REL, C))
        cls.attempt, cls.fetch, cls.failed = cls.real
        o1 = ledger.first_order1(cls.records)
        cls.result = {"kind": "result", "file_name": "gdelt-themes-20261015T001727Z.tsv", "sha256": "a" * 64, "rows": 10,
                      "kept_columns": ["theme"], "dropped_columns": ["count"], "fetched_at": "2026-10-15T00:17:27Z",
                      "attempted_at": cls.attempt["attempted_at"], "sheet_names_replaced": 0, "headerless": False,
                      "source_url": cls.attempt["source_url"], "code_path": cls.attempt["code_path"],
                      "code_sha256": cls.attempt["code_sha256"], "exclusion_rule_seq": o1["seq"],
                      "exclusion_rule_record_sha256": ledger.sha256_hex(ledger.canonical_line(o1)),
                      "store_location": "home"}

    def check(self, rows):
        return ledger.check_themes_manifest_refs(self.records, body_of(rows))

    def test_real_manifest_passes(self):
        """今の本物の形（attempt・fetch・failed）が通る。2つのキーを照らすのは attempt の1行だけ。"""
        self.assertEqual([r["kind"] for r in self.real], ["attempt", "fetch", "failed"])
        self.assertNotIn("exclusion_rule_seq", self.fetch)
        self.assertNotIn("exclusion_rule_seq", self.failed)
        self.assertEqual(ledger.check_themes_manifest_refs(self.records, fixed_records.show(REL, C)), 1)

    def test_other_honest_shapes(self):
        """themes.py が書きうるほかの形：attempt だけ（1段目）、attempt・fetch（通信の途中で止まった）、attempt・fetch・result。"""
        self.assertEqual(self.check([self.attempt]), 1)
        self.assertEqual(self.check([self.attempt, self.fetch]), 1)
        self.assertEqual(self.check([self.attempt, self.fetch, self.result]), 2)
        self.assertEqual(ledger.check_themes_manifest_refs(self.records, None), 0)

    def test_missing_keys_in_attempt_and_result(self):
        """キーの欠けた attempt・result は止まる。"""
        for k in ("exclusion_rule_seq", "exclusion_rule_record_sha256"):
            with self.subTest(kind="attempt", key=k):
                bad = {x: v for x, v in self.attempt.items() if x != k}
                with self.assertRaisesRegex(ledger.LedgerError, "1 行目（attempt）のキーが"):
                    self.check([bad, self.fetch, self.failed])
            with self.subTest(kind="result", key=k):
                bad = {x: v for x, v in self.result.items() if x != k}
                with self.assertRaisesRegex(ledger.LedgerError, "3 行目（result）のキーが"):
                    self.check([self.attempt, self.fetch, bad])

    def test_refs_must_match(self):
        for row, pos, rows in ((dict(self.attempt, exclusion_rule_seq=1), 1, None),
                               (dict(self.result, exclusion_rule_record_sha256="0" * 64), 3, None)):
            with self.subTest(pos=pos):
                rows = [row, self.fetch, self.failed] if pos == 1 else [self.attempt, self.fetch, row]
                with self.assertRaisesRegex(ledger.LedgerError, "%d 行目の exclusion_rule_seq" % pos):
                    self.check(rows)

    def test_order_broken(self):
        """並びが崩れた形は止まる。"""
        cases = {
            "fetch が先頭": [self.fetch, self.attempt, self.failed],
            "failed が先頭": [self.failed],
            "fetch の無い failed": [self.attempt, self.failed],
            "fetch の無い result": [self.attempt, self.result],
            "attempt が2行": [self.attempt, self.attempt],
            "fetch が2行": [self.attempt, self.fetch, self.fetch],
            "failed のあとに行": [self.attempt, self.fetch, self.failed, self.fetch],
            "failed のあとに result": [self.attempt, self.fetch, self.failed, self.result],
            "result のあとに attempt": [self.attempt, self.fetch, self.result, self.attempt],
        }
        for name, rows in cases.items():
            with self.subTest(name=name), self.assertRaisesRegex(ledger.LedgerError, "の並びが違う"):
                self.check(rows)

    def test_shape(self):
        """fetch・failed の行の形（kind・時刻・code_sha256・reason）と、attempt とのつながり。"""
        cases = {
            "知らない kind": ([self.attempt, dict(self.fetch, kind="retry")], "kind 'retry'"),
            "fetch に余分なキー": ([self.attempt, dict(self.fetch, note="x")], "2 行目（fetch）のキーが"),
            "fetch の時刻の形": ([self.attempt, dict(self.fetch, at="2026-10-15 00:17:26")], "at が"),
            "fetch の code_sha256 の形": ([self.attempt, dict(self.fetch, code_sha256="x")], "code_sha256 の形"),
            "fetch の code_sha256 が attempt と違う": ([self.attempt, dict(self.fetch, code_sha256="b" * 64)],
                                                    "2 行目（fetch）の code_sha256 が、直前の attempt の行と違う"),
            "failed の reason の形": ([self.attempt, self.fetch, dict(self.failed, reason="人 の 名前")], "reason が"),
            "failed にキーが無い": ([self.attempt, self.fetch, {"kind": "failed", "at": self.failed["at"]}],
                                 "3 行目（failed）のキーが"),
            "時刻が戻る": ([self.attempt, self.fetch, dict(self.failed, at="2026-10-14T00:00:00Z")], "前の行の時刻より前"),
            "result の attempted_at": ([self.attempt, self.fetch, dict(self.result, attempted_at="2026-10-15T00:17:07Z")],
                                      "attempted_at・除外の規則の参照が、直前の attempt の行と違う"),
            "result の file_name": ([self.attempt, self.fetch, dict(self.result, file_name="../x.tsv")], "file_name が"),
            "attempt の code_path": ([dict(self.attempt, code_path="src/collector/other.py")], "code_path が"),
        }
        for name, (rows, text) in cases.items():
            with self.subTest(name=name), self.assertRaisesRegex(ledger.LedgerError, text):
                self.check(rows)


class RealClone(unittest.TestCase):
    """固定したコミット（T-098 の3行）の clone で、verify all --rev auto が 0。fetch・failed の行にキーが無いことで止まらない。"""

    def test_verify_all(self):
        with tempfile.TemporaryDirectory() as td:
            c = os.path.join(td, "c")
            code = "worktree" if os.environ.get("SEALER_DOC_TEST_WORKTREE") == "1" else "head"
            fixed_records.checkout(c, C, code=code)
            rc, out, err = tl.run_verify_inproc(c, "all", "--rev", "auto")
            self.assertEqual(rc, 0, err)
            self.assertIn("行の形と並び（attempt → fetch → failed か result）は themes.py の取り決めどおり", out)
            # attempt の行の exclusion_rule_seq を消すと止まる（書き換えたマニフェストをコミットして）
            with open(os.path.join(c, REL), "rb") as f:
                rows = rows_of(f.read())
            rows[0] = {k: v for k, v in rows[0].items() if k != "exclusion_rule_seq"}
            with open(os.path.join(c, REL), "wb") as f:
                f.write(body_of(rows))
            rc, _out, err = tl.run_verify_inproc(c, "stats-order")
            self.assertEqual(rc, 1)
            self.assertIn("1 行目（attempt）のキーが", err)


if __name__ == "__main__":
    unittest.main()
