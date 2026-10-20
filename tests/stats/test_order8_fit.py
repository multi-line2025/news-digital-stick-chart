"""T-143 の順番7・順番8 と段4・N3・N4 の係数（src/stats/order8_fit.py）のテスト。

実行（プロジェクトのルートで）:
    PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -B -m unittest discover -s tests/stats -v

合成のデータと、リポジトリの中のファイル（21組の表）だけを使う。日の集計とキャッシュは読まない。ファイルを書かない。
"""

import array
import fractions
import json
import os
import random
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(PROJECT, "src", "stats"))

import order8_fit as o8  # noqa: E402

ts = o8.ts
tr = o8.tr
em = o8.em
ei = o8.ei
naive = o8.naive
V = fractions.Fraction(1, 543539)


class TestInputs(unittest.TestCase):
    def test_history_days(self):
        self.assertEqual(o8.NAIVE_HISTORY_DAYS, naive.naive_lookback_days())

    def test_read_selection(self):
        sel = o8.read_selection()
        self.assertEqual(len(sel), 21)
        self.assertEqual(sel[(28, 16)]["tier1"], "null_fix")
        self.assertEqual(sel[(28, 4)], {"tier1": "null_exp", "tier2": "hist_all_a50", "tier4": "chain"})
        with self.assertRaises(o8.Order8Error):
            o8.read_selection(want="0" * 64)

    def test_model_specs(self):
        sel = o8.read_selection()
        specs = o8.model_specs(sel)
        self.assertEqual(len(specs), 84)
        d = {(h, m, n): e for h, m, n, e in specs}
        self.assertEqual(d[(28, 4, "naive")], ())
        self.assertEqual(d[(28, 4, "t4")], tr.CHAIN_COLUMNS)
        self.assertEqual(d[(28, 4, "n3")], ("lh_hist_all_a50",))
        self.assertEqual(d[(28, 4, "n4")], ("lh_hist_all_a50",) + tr.CHAIN_COLUMNS)
        self.assertEqual(d[(28, 2, "t4")], tr.NBWAVE_COLUMNS + tr.CHAIN_COLUMNS)


class TestFit(unittest.TestCase):
    def test_sorted_rows(self):
        tb = {"t": ["b", "a", "a"], "tag": ["x", "z", "y"]}
        self.assertEqual(o8.sorted_rows(tb, [0, 1, 2]), [2, 1, 0])
        with self.assertRaises(o8.Order8Error):
            o8.sorted_rows({"t": ["a", "a"], "tag": ["x", "x"]}, [0, 1])

    def test_same_as_naive_fit_rows(self):
        """当てはめは naive.fit_rows（封印する手順）と同じ係数になる。"""
        rng = random.Random(5)
        rows = []
        for k in range(400):
            x = [1.0] + [rng.gauss(0, 1) for _ in range(4)]
            y = 1 if rng.random() < 1 / (1 + 2.718281828 ** (-(0.5 * x[1] - x[2]))) else 0
            rows.append(("2017-01-%02d" % (k % 28 + 1), "T%04d" % k, x, y))
        ref = naive.fit_rows(rows)
        tb = {"t": [r[0] for r in rows], "tag": [r[1] for r in rows]}
        order = o8.sorted_rows(tb, list(range(len(rows))))
        cols = [array.array("d", [rows[r][2][j] for r in order]) for j in range(5)]
        y = [rows[r][3] for r in order]
        _h, _m, _n, _c, coef, conv, it = o8._fit_task((28, 4, "naive", ["c%d" % j for j in range(5)], cols, y))
        self.assertTrue(conv)
        self.assertEqual(coef, list(ref["coef"]))
        self.assertEqual(it, ref["iterations"])


class TestN3N4Rows(unittest.TestCase):
    def test_known_weeks(self):
        self.assertEqual(o8.MIN_KNOWN_WEEKS, 52)
        # 週の番号 ti の予言日で、判定が確定した予言日は 0〜ti − ceil((H + 1) / 7)
        self.assertEqual(o8.known_weeks(0, 28), 0)
        self.assertEqual(o8.known_weeks(5, 28), 1)
        self.assertEqual(o8.known_weeks(56, 28), 52)
        self.assertEqual(o8.known_weeks(55, 28), 51)
        self.assertEqual(o8.known_weeks(54, 14), 52)
        self.assertEqual(o8.known_weeks(60, 56), 52)

    def test_rows(self):
        tb = {"week": [0, 55, 56, 57, 100]}
        self.assertEqual(o8.n3n4_rows(tb, [4, 0, 1, 2, 3], 28), [4, 2, 3])


class TestOutputs(unittest.TestCase):
    def test_periods_output(self):
        out = json.loads(o8.command_output(["src/stats/periods.py", "--naive-history-days", "399",
                                            "--deadline-status", "before_deadline"]))
        self.assertEqual(out["deadline_status"], "before_deadline")
        self.assertEqual(out["rebuild_triggers"]["naive_history_days"], 399)

    def test_build(self):
        sel = o8.read_selection()
        coefs = []
        for h, m, name, extra in o8.model_specs(sel):
            cols = ["intercept"] + list(naive.FEATURES[1:]) + list(extra)
            coefs.append((h, m, name, cols, [0.1] * len(cols), True, 7))
        null_fix = [(h, m, 100, 3, 0.03) for h in ts.HORIZONS for m in ts.MULTS]
        info = {"daily_min_read": "2015-03-09", "daily_max_read": "2020-11-09", "network_last_day_minus_t_max_days": -1,
                "target_rows": 1, "rows_by_h": {"14": 1, "28": 1, "56": 1}}
        f1 = o8.build_outputs(sel, coefs, null_fix, info, {"refs": {}, "v": V})
        f2 = o8.build_outputs(sel, coefs, null_fix, info, {"refs": {}, "v": V})
        self.assertEqual(f1, f2)
        self.assertEqual(sorted(f1), sorted(o8.OUT_NAMES))
        self.assertEqual(len(f1["naive_coefs.tsv"].decode().splitlines()), 1 + 21 * 7)
        self.assertEqual(len(f1["forms.tsv"].decode().splitlines()), 1 + 21)
        s = f1["summary.md"].decode("utf-8")
        self.assertIn(ei.CITATION_JA, s)
        self.assertNotIn("**", s)
        for n, d in f1.items():
            self.assertIsNone(ei.EMAIL_RE.search(d), n)

    def test_write_refuses_existing(self):
        with mock.patch.object(o8.os, "makedirs"), mock.patch.object(o8.os.path, "lexists", return_value=True), \
                mock.patch.object(o8.os, "open") as op:
            with self.assertRaises(o8.Order8Error):
                o8.write_outputs("/nonexistent", {n: b"" for n in o8.OUT_NAMES})
            op.assert_not_called()


if __name__ == "__main__":
    unittest.main()
