"""T-134 の4段の比べ（src/stats/explore_tiers.py）のテスト。

実行（プロジェクトのルートで）:
    PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -B -m unittest discover -s tests/stats -v

合成のデータだけを使う。本物の日の集計とキャッシュは読まない。ファイルを書かない。
"""

import collections
import fractions
import os
import random
import sys
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(PROJECT, "src", "stats"))

import explore_tiers as tr  # noqa: E402

ei = tr.ei
es = tr.es
eg = tr.eg
V = fractions.Fraction(1, 543539)


def synthetic_rows(n, W, seed):
    rng = random.Random(seed)
    by_week = collections.defaultdict(list)
    for w in range(W):
        for i in range(n):
            if rng.random() < 0.7:
                u = rng.random()
                by_week[w].append((i, (u < 0.3, u < 0.1, u < 0.03)))
    return by_week


class TestHistory(unittest.TestCase):
    def test_counts_and_probs_match_bruteforce(self):
        n, W = 6, 40
        bw = synthetic_rows(n, W, 1)
        for mi in range(3):
            counts = tr.hist_counts(bw, n, W, mi)
            for ti in range(W):
                known = [(w, i, js) for w in range(W) if w <= ti - tr.KNOWN_LAG_WEEKS for i, js in bw[w]]
                gk = sum(1 for _w, _i, js in known if js[mi])
                self.assertAlmostEqual(tr.null_exp(ti, counts[2], counts[3]), (gk + 1) / (len(known) + 2))
                for i in range(n):
                    for window in tr.HIST_WINDOWS:
                        lo = 0 if window == "all" else ti - window
                        mine = [js for w, j, js in known if j == i and w >= lo]
                        k = sum(1 for js in mine if js[mi])
                        p0 = (gk + 1) / (len(known) + 2)
                        for a in tr.HIST_A:
                            self.assertAlmostEqual(tr.hist_prob(ti, i, window, a, counts), (k + a * p0) / (len(mine) + a))

    def test_only_finished_judgements(self):
        """予言日 t より4週以内の予言日（判定期間が t-1 までに終わらない）の判定を変えても、t の値は変わらない。"""
        n, W = 5, 30
        bw = synthetic_rows(n, W, 2)
        c1 = tr.hist_counts(bw, n, W, 0)
        for ti in range(W):
            bw2 = collections.defaultdict(list)
            for w, lst in bw.items():
                bw2[w] = [(i, js if w <= ti - tr.KNOWN_LAG_WEEKS else (not js[0], not js[1], not js[2])) for i, js in lst]
            c2 = tr.hist_counts(bw2, n, W, 0)
            self.assertEqual(tr.null_exp(ti, c1[2], c1[3]), tr.null_exp(ti, c2[2], c2[3]))
            for i in range(n):
                for window in tr.HIST_WINDOWS:
                    self.assertEqual(tr.hist_prob(ti, i, window, 10, c1), tr.hist_prob(ti, i, window, 10, c2))

    def test_known_lag(self):
        # 予言日 s の判定期間 s+1〜s+28 が t-1 までに終わる：s + 28 ≤ t − 1。週の差 5 なら 35 日で足りる、4 なら 28 日で足りない
        self.assertTrue(5 * 7 - 28 >= 1)
        self.assertFalse(4 * 7 - 28 >= 1)
        self.assertEqual(tr.known_end(10), 6)
        self.assertEqual(tr.known_end(2), 0)


class TestMetrics(unittest.TestCase):
    def test_calibration(self):
        ps = [0.1] * 10 + [0.9] * 10
        ys = [0] * 9 + [1] + [1] * 9 + [0]
        mp, my, ece = tr.calibration(ps, ys, bins=2)
        self.assertAlmostEqual(mp, 0.5)
        self.assertAlmostEqual(my, 0.5)
        self.assertAlmostEqual(ece, 0.0)

    def test_diff_sign(self):
        rng = random.Random(3)
        ys = [1 if rng.random() < 0.2 else 0 for _ in range(400)]
        wk = [k // 20 for k in range(400)]
        tg = ["T%02d" % (k % 20) for k in range(400)]
        good = tr.metrics([0.8 if y else 0.1 for y in ys], ys, wk, tg)
        flat = tr.metrics([0.2] * 400, ys, wk, tg)
        d = tr.diff_metrics(good, flat, wk)
        self.assertLess(d["d_ll"], 0)
        self.assertLess(d["ci_ll"][1], 0)
        self.assertLess(d["d_br"], 0)
        self.assertGreaterEqual(d["d_tk"], 0)

    def test_models_and_pairs(self):
        names = [n for n, _t, _k, _e in tr.model_list()]
        self.assertEqual(len(names), len(set(names)))
        self.assertEqual(len(names), 2 + 6 + 6 + 1 + 3 + 6 + 18)
        for _lab, a, b in tr.diff_pairs():
            self.assertIn(a, names)
            self.assertIn(b, names)
        self.assertEqual(len(tr.CHAIN_COLUMNS), 4)


class TestV2(unittest.TestCase):
    def test_recal_and_window(self):
        rng = random.Random(8)
        ps = [rng.random() * 0.4 for _ in range(2000)]
        ys = [1 if rng.random() < p else 0 for p in ps]
        good, conv = tr.recal_logloss(ps, ys)
        self.assertTrue(conv)
        bad, _c = tr.recal_logloss([min(0.99, 2 * p) for p in ps], ys)
        # 確率を2倍にしても並べ方は同じなので、較正し直した対数損失はほぼ同じ
        self.assertAlmostEqual(good, bad, places=2)
        raw = sum(es.log_loss_terms([min(0.99, 2 * p) for p in ps], ys)) / len(ys)
        self.assertGreater(raw, bad)
        wk = [k // 20 for k in range(2000)]
        tg = ["T%02d" % (k % 20) for k in range(2000)]
        a = tr.metrics(ps, ys, wk, tg)
        b = tr.metrics([0.2] * 2000, ys, wk, tg)
        wins = tr.window_sim(a, b, wk, 13)
        self.assertEqual(len(wins), len(range(0, 100 - 13 + 1, tr.SIM_STRIDE)))
        self.assertEqual(wins[0][4], 4)
        for st, d, lo, hi, nb in wins:
            self.assertLessEqual(lo, hi)

    def test_model_cols_and_names(self):
        self.assertEqual(tr.model_cols(4, "logit_only", ("lh_x",)), [tr.em.naive_col(4, "intercept"), "lh_x"])
        self.assertEqual(tr.model_cols(4, "logit", ("c",)), tr.ed.naive_cols(4) + ["c"])
        self.assertEqual(tr.naive.FEATURES[0], "intercept")


class TestNbwave(unittest.TestCase):
    def test_matches_t119(self):
        import datetime
        rng = random.Random(4)
        n = 20
        lists = []
        for i in range(n):
            js = sorted(set(rng.randrange(n) for _ in range(4)) - {i})
            lists.append([(j, rng.random() + 0.1, rng.random()) for j in js])
        nb = es.Nbrs(lists)
        h1, h2 = tr.ch.hop_lists(nb, n)
        mondays = [datetime.date(2017, 1, 2) + datetime.timedelta(days=7 * k) for k in range(6)]
        rises = [[rng.gauss(0, 1) if rng.random() < 0.8 else None for _ in range(n)] for _ in mondays]
        targets = {ti: list(range(0, n, 2)) for ti in range(6)}
        out = tr.month_nbwave(201701, h1, h2, targets, mondays, rises)
        for (ti, i), x in out.items():
            a, b = eg.hop_signals(i, nb, rises[ti])
            self.assertEqual(x[1], 1.0 if a is None else 0.0)
            self.assertEqual(x[3], 1.0 if b is None else 0.0)
            self.assertAlmostEqual(x[0], 0.0 if a is None else a, places=12)
            self.assertAlmostEqual(x[2], 0.0 if b is None else b, places=12)


class TestOutputs(unittest.TestCase):
    def build(self):
        rng = random.Random(5)
        res, sim = {}, []
        for sp in tr.SPLITS:
            for m in tr.MULTIPLIERS:
                ys = [1 if rng.random() < 0.1 else 0 for _ in range(300)]
                wk = [k // 30 for k in range(300)]
                tg = ["AA_%02d" % (k % 30) for k in range(300)]
                mets = {name: tr.metrics([min(0.99, max(0.01, 0.1 + rng.gauss(0, 0.03) + 0.2 * y)) for y in ys], ys, wk, tg)
                        for name, _t, _k, _e in tr.model_list()}
                for x in mets.values():
                    x["ll_recal"], x["recal_converged"] = x["logloss"] - 0.001, True
                    x["cal_loss"] = 0.001
                diffs = [(lab, a, b, tr.diff_metrics(mets[a], mets[b], wk)) for lab, a, b in tr.diff_pairs()]
                res[(sp, m)] = (mets, diffs)
                for lab, a, b in tr.diff_pairs():
                    if lab != "N4-N3":
                        for ws in tr.SIM_WINDOWS:
                            sim.append((sp, m, lab, a, b, ws, tr.window_sim(mets[a], mets[b], wk, ws, stride=4)))
        ctx = {"refs": {}, "v": V}
        info = {"daily_min_read": "2015-03-09", "daily_max_read": "2020-10-12", "network_last_day_minus_t_max_days": -1}
        coefs = [("B", 2, "naive", [0.1] * 8, True)] + [("B", 4, "hcal_" + h, [-3.0, 0.1 + 0.01 * k], True)
                                                         for k, (h, _w, _a) in enumerate(tr.hist_forms())]
        tags = ["AA_%02d" % i for i in range(30)]
        return tr.build_outputs(tags, [], list(range(300)), {}, res, coefs, ctx, info, sim)

    def test_build(self):
        f1, f2 = self.build(), self.build()
        self.assertEqual(f1, f2)
        self.assertEqual(sorted(f1), sorted(tr.OUT_NAMES))
        s = f1["summary.md"].decode("utf-8")
        for bad in ("**", "%%", "AA_0"):
            self.assertNotIn(bad, s)
        self.assertIn(ei.CITATION_JA, s)
        self.assertIn(ei.CITATION_EN, s)
        self.assertLess(s.index("## 1. やさしい説明"), s.index("## 2. 作り方"))
        self.assertIn("2020年の連鎖（T-127）は、分け方 A の検証の期間の中にしかない", s)
        for w in ("この版（v2）の変更点", "静的な違い", "名前の順で決まる", "段4 で上位10の島が減り", "較正の損", "窓をずらした見当",
                  "判定には使えない目安"):
            self.assertIn(w, s)
        self.assertEqual(tr.LABEL, "explore-tiers-t134-v3")
        for w in ("この版（v3）の変更点", "表の sha256 は v2 と同じ", "較正し直した対数損失の歪み", "識別は、当面 AUC を主に読む",
                  "較正した段2 の傾き", "0.10〜0.15（全期間・a = 50 で 0.110）", "束の下限 10 を満たす窓（分け方 B）：1つも無い"):
            self.assertIn(w, s)
        for n, d in f1.items():
            self.assertIsNone(ei.EMAIL_RE.search(d), n)
            self.assertNotIn(b"AA_0", d, n)

    def test_write_refuses_existing(self):
        with mock.patch.object(tr.os, "makedirs"), mock.patch.object(tr.os.path, "lexists", return_value=True), \
                mock.patch.object(tr.os, "open") as op:
            with self.assertRaises(tr.TierError):
                tr.write_outputs("/nonexistent", {n: b"" for n in tr.OUT_NAMES})
            op.assert_not_called()


if __name__ == "__main__":
    unittest.main()
