"""T-146 の chain の d の上限の確かめ（src/stats/chain_cap_check.py）のテスト。合成のデータだけを使う。"""

import array
import datetime
import math
import os
import random
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(PROJECT, "src", "stats"))

import chain_cap_check as cc  # noqa: E402

ch = cc.ch
ei = cc.ei


class TestCap(unittest.TestCase):
    def test_capped(self):
        self.assertEqual(list(cc.capped(array.array("H", [0, 51, 52, 53, 200]))), [0, 51, 52, 52, 52])

    def test_weight_bounds(self):
        a, b = cc.weight_bounds()
        self.assertAlmostEqual(a, math.exp(-26))
        self.assertAlmostEqual(b, math.exp(-25.5))
        self.assertLess(a, 6e-12)
        self.assertLess(b, 9e-12)
        # 上限を付けた重みと付けない重みの差は、d > 52 で b 以下
        for d in range(53, 300):
            self.assertLessEqual(abs(ch.exc_weight(d, 1, 2.0) - ch.exc_weight(52, 1, 2.0)), b)

    def test_features_diff_small(self):
        rng = random.Random(1)
        n, W = 12, 80
        dur = []
        for _ in range(n):
            flags = [rng.random() < 0.97 for _ in range(W)]
            dur.append(ch.durations(flags))
        h1 = [[(j, rng.random() + 0.1) for j in sorted(set(rng.randrange(n) for _ in range(3)) - {i})] for i in range(n)]
        h2 = [[(k, rng.random() + 0.1) for k in sorted(set(rng.randrange(n) for _ in range(5)) - {i})] for i in range(n)]
        fam = [rng.randrange(3) - 1 for _ in range(n)]
        lab = [rng.randrange(3) for _ in range(n)]
        mondays = [datetime.date(2017, 1, 2) + datetime.timedelta(days=7 * k) for k in range(W)]
        targets = {ti: list(range(n)) for ti in range(W)}
        diffs = 0.0
        vi = ch.variants().index(cc.tr.CHAIN_VARIANT)      # 前向きで使う D = 1・λ = 2 の4つの列だけ
        for mk in sorted({ch.es.month_key(t) for t in mondays}):
            a = ch.month_features(mk, h1, h2, lab, dur, targets, fam, mondays, n)
            b = ch.month_features(mk, h1, h2, lab, [cc.capped(d) for d in dur], targets, fam, mondays, n)
            a = {k: list(x[4 * vi:4 * vi + 4]) for k, x in a.items()}
            b = {k: list(x[4 * vi:4 * vi + 4]) for k, x in b.items()}
            diffs = max(diffs, cc.max_abs_diff(a, b))
        self.assertTrue(any(max(d) > 52 for d in dur))
        self.assertLessEqual(diffs, cc.weight_bounds()[1])

    def test_max_abs_diff(self):
        self.assertEqual(cc.max_abs_diff({1: [0.0, 1.0]}, {1: [0.5, 1.0]}), 0.5)
        with self.assertRaises(cc.CapError):
            cc.max_abs_diff({1: [0.0]}, {2: [0.0]})


if __name__ == "__main__":
    unittest.main()
