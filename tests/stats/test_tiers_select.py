"""T-141 の21組の段の形の表（src/stats/tiers_select.py）のテスト。

実行（プロジェクトのルートで）:
    PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -B -m unittest discover -s tests/stats -v

合成のデータだけを使う。本物の日の集計とキャッシュは読まない。ファイルを書かない。
"""

import array
import collections
import datetime
import fractions
import os
import random
import sys
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(PROJECT, "src", "stats"))

import tiers_select as ts  # noqa: E402

tr = ts.tr
es = ts.es
ei = ts.ei
V = fractions.Fraction(1, 543539)


class TestRules(unittest.TestCase):
    def test_constants(self):
        self.assertEqual(ts.MULTS, (2, 3, 4, 6, 8, 12, 16))
        self.assertEqual(ts.HORIZONS, (14, 28, 56))
        self.assertEqual(len(ts.TIER2_FORMS), 6)
        self.assertEqual([f for f, _w, _a in ts.TIER2_FORMS], [f for f, _w, _a in tr.hist_forms()])
        self.assertEqual(ts.TIER4_FORMS, tr.TIER4_FORMS)

    def test_known_lag(self):
        for h in ts.HORIZONS:
            k = ts.known_lag_weeks(h)
            self.assertTrue(7 * k - h >= 1)            # s + H ≤ t − 1
            self.assertFalse(7 * (k - 1) - h >= 1)     # 1週近いと t-1 までに終わらない
        self.assertEqual([ts.known_lag_weeks(h) for h in ts.HORIZONS], [3, 5, 9])
        self.assertEqual(ts.known_lag_weeks(28), tr.KNOWN_LAG_WEEKS)

    def test_probs_match_explore_tiers_for_28(self):
        rng = random.Random(1)
        n, W = 6, 30
        bw = collections.defaultdict(list)
        for w in range(W):
            for i in range(n):
                if rng.random() < 0.7:
                    u = rng.random()
                    bw[w].append((i, (u < 0.3, u < 0.1, u < 0.03)))
        counts = tr.hist_counts(bw, n, W, 1)
        lag = ts.known_lag_weeks(28)
        for ti in range(W):
            self.assertEqual(ts.null_exp(ti, lag, counts[2], counts[3]), tr.null_exp(ti, counts[2], counts[3]))
            for i in range(n):
                for _f, w, a in ts.TIER2_FORMS:
                    self.assertEqual(ts.hist_prob(ti, i, w, a, lag, counts), tr.hist_prob(ti, i, w, a, counts))

    def test_only_finished_judgements(self):
        rng = random.Random(2)
        n, W = 5, 40
        bw = collections.defaultdict(list)
        for w in range(W):
            for i in range(n):
                if rng.random() < 0.8:
                    bw[w].append((i, (rng.random() < 0.3,)))
        for h in ts.HORIZONS:
            lag = ts.known_lag_weeks(h)
            c1 = tr.hist_counts(bw, n, W, 0)
            for ti in range(W):
                bw2 = {w: [(i, js if w <= ti - lag else (not js[0],)) for i, js in lst] for w, lst in bw.items()}
                c2 = tr.hist_counts(collections.defaultdict(list, bw2), n, W, 0)
                self.assertEqual(ts.null_exp(ti, lag, c1[2], c1[3]), ts.null_exp(ti, lag, c2[2], c2[3]))
                for i in range(n):
                    self.assertEqual(ts.hist_prob(ti, i, 52, 50, lag, c1), ts.hist_prob(ti, i, 52, 50, lag, c2))

    def test_choose(self):
        self.assertEqual(ts.choose(1, {"null_exp": 0.2, "null_fix": 0.2}), "null_exp")
        self.assertEqual(ts.choose(1, {"null_exp": 0.3, "null_fix": 0.2}), "null_fix")
        v = {f: 0.5 for f, _w, _a in ts.TIER2_FORMS}
        self.assertEqual(ts.choose(2, v), "hist_all_a10")
        v["hist_52_a200"] = 0.1
        self.assertEqual(ts.choose(2, v), "hist_52_a200")
        self.assertEqual(ts.choose(4, {"nbwave": 0.1, "chain": 0.1, "nbwave_chain": 0.1}), "nbwave")
        self.assertEqual(ts.choose(4, {"nbwave": 0.2, "chain": 0.1, "nbwave_chain": 0.1}), "chain")


class TestEvaluate(unittest.TestCase):
    def test_matches_explore_signals_for_28(self):
        """判定期間 28 日・倍率 2・4・8 では、T-117〜T-134 の evaluate_tag と同じ値。"""
        rng = random.Random(3)
        start = datetime.date(2015, 3, 2)
        days = [start + datetime.timedelta(days=k) for k in range(1000)]
        values = []
        base = 1e-4
        for k in range(1000):
            if rng.random() < 0.02:
                values.append(None)
            else:
                x = base * (1 + 0.5 * rng.random())
                if rng.random() < 0.03:
                    x *= 8
                values.append(x)
        mondays = [datetime.date(2016, 4, 11) + datetime.timedelta(days=7 * k) for k in range(70)]
        mine, lo, hi = ts.evaluate_tag_all(days, values, mondays, V)
        ref, lo2, hi2 = es.evaluate_tag(days, values, mondays, V)
        self.assertEqual(lo, lo2)
        self.assertLessEqual(hi2, hi)
        idx = [ts.MULTS.index(m) for m in tr.MULTIPLIERS]
        n_target = 0
        for (st, b, c, lvs, js), (st2, b2, c2, _m1, _m2, js2, lv2) in zip(mine, ref):
            self.assertEqual((st, b, c), (st2, b2, c2))
            if st == "target":
                n_target += 1
                self.assertEqual(lvs[28], lv2)
                self.assertEqual(tuple(js[28][k] for k in idx), js2)
        self.assertGreater(n_target, 10)

    def test_subset_table(self):
        tb = {"t": ["a", "b", "c"], "tag": ["x", "y", "z"], "y4": array.array("b", [0, 1, 0]),
              "c1": array.array("d", [1.0, 2.0, 3.0]), "c2": array.array("d", [4.0, 5.0, 6.0])}
        sub = ts.subset_table(tb, 4, ["c1"], [2, 0])
        self.assertEqual(sub["t"], ["c", "a"])
        self.assertEqual(list(sub["y4"]), [0, 0])
        self.assertEqual(list(sub["c1"]), [3.0, 1.0])
        self.assertNotIn("c2", sub)


class TestOutputs(unittest.TestCase):
    def rows(self):
        rng = random.Random(4)
        out = []
        for h in ts.HORIZONS:
            for m in ts.MULTS:
                ll = {f: round(rng.random(), 6) for f in ts.FORM_ORDER}
                out.append({"h": h, "m": m, "n_train": 100, "n_test": 50, "islands_test": 5, "ll": ll,
                            "sel": {1: ts.choose(1, ll), 2: ts.choose(2, ll), 4: ts.choose(4, ll)},
                            "conv": {f: True for f in ts.TIER4_FORMS}})
        return out

    def test_build(self):
        ctx = {"refs": {}, "v": V}
        info = {"daily_min_read": "2015-03-09", "daily_max_read": "2020-11-09", "network_last_day_minus_t_max_days": -1,
                "target_rows": 1}
        f1 = ts.build_outputs(self.rows(), ctx, info)
        f2 = ts.build_outputs(self.rows(), ctx, info)
        self.assertEqual(f1, f2)
        self.assertEqual(sorted(f1), sorted(ts.OUT_NAMES))
        sel = f1["tiers_select.tsv"].decode("utf-8").splitlines()
        self.assertEqual(len(sel), 1 + 21)
        allr = f1["tiers_select_all.tsv"].decode("utf-8").splitlines()
        self.assertEqual(len(allr), 1 + 21 * 12)
        chosen = collections.Counter((l.split("\t")[0], l.split("\t")[1], l.split("\t")[2]) for l in allr[1:]
                                     if l.split("\t")[7] == "yes")
        self.assertEqual(len(chosen), 21 * 3)
        self.assertTrue(all(c == 1 for c in chosen.values()))
        s = f1["summary.md"].decode("utf-8")
        self.assertIn(ei.CITATION_JA, s)
        self.assertNotIn("**", s)
        for n, d in f1.items():
            self.assertIsNone(ei.EMAIL_RE.search(d), n)

    def test_write_refuses_existing(self):
        with mock.patch.object(ts.os, "makedirs"), mock.patch.object(ts.os.path, "lexists", return_value=True), \
                mock.patch.object(ts.os, "open") as op:
            with self.assertRaises(ts.SelectError):
                ts.write_outputs("/nonexistent", {n: b"" for n in ts.OUT_NAMES})
            op.assert_not_called()


if __name__ == "__main__":
    unittest.main()
