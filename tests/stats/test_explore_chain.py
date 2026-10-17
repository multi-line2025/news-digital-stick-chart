"""T-127 の島の連鎖の探索（src/stats/explore_chain.py）のテスト。

実行（プロジェクトのルートで）:
    PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -B -m unittest discover -s tests/stats -v

合成のデータだけを使う。本物の日の集計とキャッシュは読まない。ファイルを書かない。
"""

import array
import collections
import fractions
import math
import os
import random
import sys
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(os.path.dirname(HERE))
SRC = os.path.join(PROJECT, "src", "stats")
sys.path.insert(0, SRC)

import explore_chain as ch  # noqa: E402

ei = ch.ei
es = ch.es
eg = ch.eg
V = fractions.Fraction(1, 543539)


def synthetic(n, W, seed):
    rng = random.Random(seed)
    tgt, isl, aft = [], [], []
    for _i in range(n):
        t, s, a = bytearray(W), bytearray(W), bytearray(W)
        for w in range(W):
            if rng.random() < 0.6:
                t[w] = 1
                u = rng.random()
                if u < 0.3:
                    s[w] = 1 | (2 if u < 0.12 else 0) | (4 if u < 0.05 else 0)
                    a[w] = rng.choice([0, 1, 2])
        tgt.append(bytes(t))
        isl.append(bytes(s))
        aft.append(bytes(a))
    h1 = [[(j, 1.0) for j in sorted(set(rng.randrange(n) for _ in range(3)) - {i})] for i in range(n)]
    h2 = []
    for i in range(n):
        near = {j for j, _w in h1[i]} | {i}
        h2.append([(k, 1.0) for k in sorted(set(rng.randrange(n) for _ in range(6)) - near)])
    fam = [rng.randrange(4) - 1 for _ in range(n)]
    comm = [rng.randrange(5) - 1 for _ in range(n)]
    famsea = [rng.randrange(3) for _ in range(n)]
    return tgt, isl, aft, h1, h2, fam, comm, famsea


def brute(tgt, isl, aft, h1, h2, fam, comm, famsea, nseas):
    """describe_counts を組ごとに数え直す。"""
    n, W = len(tgt), len(tgt[0])
    rel = collections.defaultdict(lambda: [0, 0, 0.0, 0, 0.0])

    def relation(a, b):
        if any(j == a for j, _w in h1[b]):
            return "hop1"
        if any(k == a for k, _w in h2[b]):
            return "hop2"
        return None
    for w in range(W - 1):
        for mi, m in enumerate(ch.MULTIPLIERS):
            for kind in ch.TRIGGER_KINDS:
                T = [a for a in range(n) if tgt[a][w] and isl[a][w] >> mi & 1 and
                     (kind == "all" or aft[a][w] == ch.KIND_CODE[kind])]
                if not T:
                    continue
                for k in ch.LAGS:
                    w2 = w + k
                    if w2 >= W:
                        continue
                    cnt = {r: [0, 0] for r in ch.RELATIONS}
                    for a in T:
                        for b in range(n):
                            if b == a or not tgt[b][w2]:
                                continue
                            y = isl[b][w2] >> mi & 1
                            hr = relation(a, b)
                            sf = fam[a] >= 0 and fam[a] == fam[b]
                            sc = comm[a] >= 0 and comm[a] == comm[b]
                            rs = []
                            if hr:
                                rs.append(hr)
                            if sf:
                                rs.append("family")
                            if sc:
                                rs.append("community")
                            if not rs:
                                rs.append("none")
                            for r in rs:
                                cnt[r][0] += y
                                cnt[r][1] += 1
                    nt = sum(1 for b in range(n) if tgt[b][w2])
                    ni = sum(1 for b in range(n) if tgt[b][w2] and isl[b][w2] >> mi & 1)
                    on, pn = cnt["none"]
                    for r in ch.RELATIONS:
                        acc = rel[(m, kind, r, k)]
                        o, p = cnt[r]
                        acc[0] += o
                        acc[1] += p
                        if pn:
                            acc[2] += p * on / pn
                            acc[3] += o
                        if nt:
                            acc[4] += p * ni / nt
    return rel


class TestStates(unittest.TestCase):
    def test_is_high_strict(self):
        self.assertFalse(ch.is_high(None, 1.0, V))
        self.assertFalse(ch.is_high(1.0, None, V))
        self.assertFalse(ch.is_high(1.0, 2.0, V))
        self.assertTrue(ch.is_high(1.0, 2.0001, V))
        self.assertFalse(ch.is_high(0.0, V, V))
        self.assertTrue(ch.is_high(0.0, 2 * float(V), V))

    def test_durations_use_only_past(self):
        rng = random.Random(3)
        flags = [rng.random() < 0.4 for _ in range(100)]
        d = ch.durations(flags)
        for t in range(100):
            k = 0
            while t - k >= 0 and flags[t - k]:
                k += 1
            self.assertEqual(d[t], k)
            changed = flags[:t + 1] + [not f for f in flags[t + 1:]]
            self.assertEqual(ch.durations(changed)[:t + 1], d[:t + 1])

    def test_exc_weight(self):
        self.assertEqual(ch.exc_weight(0, 1, 2.0), 0.0)
        self.assertEqual(ch.exc_weight(1, 1, 2.0), 1.0)
        self.assertEqual(ch.exc_weight(1, 2, 2.0), 0.0)
        self.assertAlmostEqual(ch.exc_weight(3, 2, 2.0), math.exp(-1.0))

    def test_models(self):
        self.assertEqual(len(ch.models()), 30)
        self.assertEqual(len(ch.EXC_COLUMNS), 24)
        self.assertEqual(len(set(n for n, _c in ch.models())), 30)


class TestGraph(unittest.TestCase):
    def setUp(self):
        rng = random.Random(7)
        self.n = 25
        lists = []
        for i in range(self.n):
            js = sorted(set(rng.randrange(self.n) for _ in range(4)) - {i})
            lists.append([(j, rng.random() + 0.1, rng.random()) for j in js])
        self.nbrs = es.Nbrs(lists)
        self.rng = rng

    def test_hops_match_t119(self):
        h1, h2 = ch.hop_lists(self.nbrs, self.n)
        rises = [self.rng.gauss(0, 1) if self.rng.random() < 0.8 else None for _ in range(self.n)]
        for i in range(self.n):
            a, b = eg.hop_signals(i, self.nbrs, rises)
            x = es.weighted_mean([(w, rises[j]) for j, w in h1[i]])
            y = es.weighted_mean([(w, rises[k]) for k, w in h2[i]])
            self.assertEqual(a, x)
            if b is None:
                self.assertIsNone(y)
            else:
                self.assertAlmostEqual(b, y, places=12)
            self.assertNotIn(i, [k for k, _w in h2[i]])
            self.assertFalse(set(k for k, _w in h2[i]) & set(j for j, _w in h1[i]))

    def test_reverse_csr(self):
        h1, _h2 = ch.hop_lists(self.nbrs, self.n)
        off, js = ch.reverse_csr(h1, self.n)
        for a in range(self.n):
            want = [b for b in range(self.n) if any(j == a for j, _w in h1[b])]
            self.assertEqual(list(js[off[a]:off[a + 1]]), want)


class TestDescribe(unittest.TestCase):
    def test_counts_match_bruteforce(self):
        tgt, isl, aft, h1, h2, fam, comm, famsea = synthetic(14, 18, 11)
        r1, r2 = ch.reverse_csr(h1, 14), ch.reverse_csr(h2, 14)
        res = ch.describe_counts(tgt, isl, aft, lambda w: (r1, r2), fam, comm, famsea, 3)
        want = brute(tgt, isl, aft, h1, h2, fam, comm, famsea, 3)
        self.assertEqual(sorted(res["rel"]), sorted(want))
        for key, v in want.items():
            got = res["rel"][key]
            self.assertEqual(got[0], v[0], key)
            self.assertEqual(got[1], v[1], key)
            self.assertEqual(got[3], v[3], key)
            self.assertAlmostEqual(got[2], v[2], places=9)
            self.assertAlmostEqual(got[4], v[4], places=9)

    def test_order_counts(self):
        tgt, isl, aft, h1, h2, fam, comm, famsea = synthetic(12, 16, 5)
        r1, r2 = ch.reverse_csr(h1, 12), ch.reverse_csr(h2, 12)
        res = ch.describe_counts(tgt, isl, aft, lambda w: (r1, r2), fam, comm, famsea, 3)
        n, W = 12, 16
        for mi, m in enumerate(ch.MULTIPLIERS):
            for kind in ch.ORDER_KINDS:
                for K in ch.ORDER_KS:
                    ob = [[0] * 3 for _ in range(3)]
                    pa = [[0] * 3 for _ in range(3)]
                    for w in range(W - 1):
                        for a in range(n):
                            if not (tgt[a][w] and isl[a][w] >> mi & 1 and
                                    (kind == "all" or aft[a][w] == ch.KIND_CODE[kind])):
                                continue
                            for k in range(1, K + 1):
                                if w + k >= W:
                                    continue
                                for b in range(n):
                                    if tgt[b][w + k]:
                                        pa[famsea[a]][famsea[b]] += 1
                                        ob[famsea[a]][famsea[b]] += isl[b][w + k] >> mi & 1
                    self.assertEqual(res["order"][(m, kind, K)], (ob, pa))

    def test_shift_and_offsets(self):
        rows = [bytes([1, 2, 3, 4, 5]), bytes([6, 7, 8, 9, 10])]
        self.assertEqual(ch.shift_rows(rows, [2, 0]), [bytes([3, 4, 5, 1, 2]), rows[1]])
        a = ch.null_offsets(10, 232, 3)
        self.assertEqual(a, ch.null_offsets(10, 232, 3))
        self.assertTrue(all(1 <= o < 232 for r in a for o in r))
        tgt, isl, aft, h1, h2, fam, comm, famsea = synthetic(10, 12, 2)
        offs = [3] * 10
        sh = ch.shift_rows(tgt, offs)
        for i in range(10):
            for w in range(12):
                self.assertEqual(sh[i][w], tgt[i][(w + 3) % 12])

    def test_ratios_and_lift(self):
        self.assertEqual(ch.ratios([3, 10, 2.0, 3, 1.5]), (1.5, 2.0))
        self.assertEqual(ch.ratios([0, 0, 0.0, 0, 0.0]), (None, None))
        order = {(2, "all", 4): ([[1, 2], [3, 4]], [[10, 10], [10, 10]])}
        lift = ch.lift_table(order, {2: [0.1, 0.2]}, 2, "all", 4, 2)
        self.assertAlmostEqual(lift[0][1], 1.0)
        self.assertAlmostEqual(lift[1][0], 3.0)
        self.assertAlmostEqual(ch.asym(lift, 0, 1), math.log(1 / 3))


class TestFeatures(unittest.TestCase):
    def test_exc_features_and_future(self):
        rng = random.Random(9)
        n, W = 15, 10
        dur = [array.array("H", [rng.randrange(4) for _ in range(W)]) for _ in range(n)]
        h1 = [[(j, rng.random() + 0.1) for j in sorted(set(rng.randrange(n) for _ in range(3)) - {i})] for i in range(n)]
        h2 = [[(k, rng.random()) for k in sorted(set(rng.randrange(n) for _ in range(5)) - {i})] for i in range(n)]
        fam = [rng.randrange(3) - 1 for _ in range(n)]
        lab = [rng.randrange(3) for _ in range(n)]
        import datetime
        mondays = [datetime.date(2017, 1, 2) + datetime.timedelta(days=7 * k) for k in range(W)]
        targets = {ti: sorted(rng.sample(range(n), 6)) for ti in range(W)}
        mk = 201701
        f1 = ch.month_features(mk, h1, h2, lab, dur, targets, fam, mondays, n)
        self.assertEqual(sorted(f1), sorted((ti, i) for ti in range(W) if mondays[ti].month == 1 for i in targets[ti]))
        for (ti, i), x in f1.items():
            vals = []
            for d, lam in ch.variants():
                e = [ch.exc_weight(dur[j][ti], d, lam) for j in range(n)]
                sw = sum(w for _j, w in h1[i])
                vals.append(sum(w * e[j] for j, w in h1[i]) / sw if sw > 0 else 0.0)
                sw = sum(w for _k, w in h2[i] if w > 0)
                vals.append(sum(w * e[k] for k, w in h2[i] if w > 0) / sw if sw > 0 else 0.0)
                mf = [j for j in range(n) if j != i and fam[i] >= 0 and fam[j] == fam[i]]
                vals.append(sum(e[j] for j in mf) / len(mf) if mf else 0.0)
                mc = [j for j in range(n) if j != i and lab[j] == lab[i]]
                vals.append(sum(e[j] for j in mc) / len(mc) if mc else 0.0)
            for a, b in zip(x, vals):
                self.assertAlmostEqual(a, b, places=12)
            # 予言日より後の続いた週数を変えても、その予言日の量は変わらない
            dur2 = [array.array("H", list(dj[:ti + 1]) + [7] * (W - ti - 1)) for dj in dur]
            f2 = ch.month_features(mk, h1, h2, lab, dur2, targets, fam, mondays, n)
            self.assertEqual(list(f2[(ti, i)]), list(x))

    def test_network_before(self):
        import datetime
        for t in ei.prediction_mondays():
            months = es.network_months(t, ch.GRAPH_WINDOW, "M")
            self.assertLess(es.check_network_before(t, months), 0)
            self.assertEqual(len(months), ch.GRAPH_WINDOW)
        with self.assertRaises(es.SignalError):
            es.check_network_before(datetime.date(2017, 1, 30), [201701])


class TestCase_(unittest.TestCase):
    def test_case_links(self):
        tgt, isl, aft, h1, h2, fam, comm, famsea = synthetic(12, 20, 4)
        f1, f2 = ch.csr(h1), ch.csr(h2)
        mi = 0
        il = {w: ch.islands_of_week(tgt, isl, w, mi) for w in range(20)}
        for ti in range(13, 20):
            for b in il[ti]:
                l1, l2, nf = ch.case_links(ti, b, il.__getitem__, lambda w: (f1, f2), fam)
                w1 = [(k, a) for k in ch.LAGS for a in il[ti - k] if a != b and any(j == a for j, _w in h1[b])]
                w2 = [(k, a) for k in ch.LAGS for a in il[ti - k] if a != b and any(j == a for j, _w in h2[b])
                      and not any(j == a for j, _w in h1[b])]
                wf = sum(1 for k in ch.LAGS for a in il[ti - k] if a != b and fam[a] >= 0 and fam[a] == fam[b])
                self.assertEqual((l1, l2, nf), (w1, w2, wf))


class TestOutputs(unittest.TestCase):
    def build(self):
        tgt, isl, aft, h1, h2, fam, comm, famsea = synthetic(12, 232, 6)
        r1, r2 = ch.reverse_csr(h1, 12), ch.reverse_csr(h2, 12)
        desc = []
        offs = ch.null_offsets(12, 232, 4)
        for r in range(5):
            o = [0] * 12 if r == 0 else offs[r - 1]
            desc.append(ch.describe_counts(ch.shift_rows(tgt, o), ch.shift_rows(isl, o), ch.shift_rows(aft, o),
                                           lambda w: (r1, r2), fam, comm, famsea, 3))
        tags = ["AA_%02d" % i for i in range(12)]
        mondays = ei.prediction_mondays()
        fam_order = ["AA", "BB", "その他"]
        seas = {"family": [fam_order[s] for s in famsea], "community": ["群れ01"] * 12}
        rows, after, jump = {}, {}, {}
        for i in range(12):
            for ti in range(232):
                if tgt[i][ti]:
                    js = tuple(bool(isl[i][ti] >> mi & 1) for mi in range(3))
                    rows[(ti, i)] = (js, {"B": 0.001})
                    if any(js):
                        after[(ti, i)] = ["unknown", "back", "stay"][aft[i][ti]]
                        jump[(ti, i)] = 3.0
        keys = sorted(rows)
        f1, f2 = ch.csr(h1), ch.csr(h2)
        case = []
        cw = ch.case_weeks(mondays)
        for mi, m in enumerate(ch.MULTIPLIERS):
            il = {w: ch.islands_of_week(tgt, isl, w, mi) for w in range(232)}
            for ti in cw:
                for b in il[ti]:
                    l1, l2, nf = ch.case_links(ti, b, il.__getitem__, lambda w: (f1, f2), fam)
                    case.append((ti, b, m, l1, l2, nf))
        rng = random.Random(1)
        extra = {c: array.array("d", [rng.random() * (rng.random() < 0.3) for _ in keys]) for c in ch.EXC_COLUMNS}
        mres, coefs = [], []
        for sp in ch.SPLITS:
            for m in ch.MULTIPLIERS:
                mres.append((sp, m, "naive", {"n": 100, "pos": 10, "logloss": 0.3, "auc": 0.7, "topk": 5}))
                for name, cols in ch.models():
                    mres.append((sp, m, name, {"n": 100, "pos": 10, "logloss": 0.29, "auc": 0.71, "topk": 6,
                                               "d_logloss": -0.01, "d_ll_ci": (-0.02, 0.001), "d_topk": 1}))
                    coefs.append((sp, m, name, ["intercept"] + list(cols), [0.1] * (1 + len(cols))))
        ctx = {"refs": {}, "v": V}
        info = {"daily_min_read": "2015-03-02", "daily_max_read": "2020-10-12", "network_last_day_minus_t_max_days": -1,
                "graph_months": [], "case_months": [], "high_counts": [], "edges": {}}
        return ch.build_outputs(tags, mondays, rows, keys, extra, desc, case, seas, fam_order, after, jump, ctx, info,
                                mres, coefs), tags

    def test_build(self):
        f1, tags = self.build()
        f2, _t = self.build()
        self.assertEqual(f1, f2)
        self.assertEqual(sorted(f1), sorted(ch.OUT_NAMES))
        s = f1["summary.md"].decode("utf-8")
        self.assertNotIn("**", s)
        self.assertNotIn("%%", s)
        self.assertIn(ei.CITATION_JA, s)
        self.assertIn(ei.CITATION_EN, s)
        self.assertLess(s.index("やさしい説明"), s.index("作り方"))
        self.assertIn("2020年の連鎖は、分け方 A の検証の期間", s)
        # T-128
        self.assertEqual(ch.LABEL, "explore-chain-t127-v2")
        self.assertIn("この版（v2）の変更点", s)
        self.assertIn("表の sha256 は v1 と同じ", s)
        self.assertIn("1〜3週後（判定期間が重なる）比 ", s)
        self.assertIn("4〜12週後（判定期間が重ならない）比 ", s)
        self.assertIn("偶然の中央値", s)
        self.assertIn("21・14・7 日重なる", s)
        self.assertIn("範囲の外に出た組", s)
        self.assertIn("向きの差は小さい", s)
        self.assertIn("設定ごとの範囲の外の組の数：倍率 2・すべての島・4週", s)
        self.assertIn("嵐が何週か続くことと区別できない", s)
        self.assertIn("作り方の上でほぼ必ず付く", s)
        self.assertIn("T-127 の本番の前にコードの定数で決めたもの", s)
        self.assertNotIn("が先、", s)
        self.assertTrue(f1["chain-private.tsv"].startswith(ch.PRIVATE_HEADER.encode("utf-8")))
        for n, d in f1.items():
            self.assertIsNone(ei.EMAIL_RE.search(d), n)
            if n != "chain-private.tsv":
                self.assertNotIn(b"AA_0", d, n)

    def test_band_rows_and_topk_note(self):
        f, _t = self.build()
        s = f["summary.md"].decode("utf-8")
        self.assertNotIn("対数損失は下がったのに上位10の島が減ったモデルが", s)   # 合成の結果では上位10の島が増えている
        d = {"ratio_none": 1.5, "null_none_med": 1.2, "null_none_q": 1.3}
        self.assertEqual(ch.ratio_text2(d), "比 1.50・偶然の中央値 1.20・90%点 1.30（90%点を超える。中央値で割ると 1.25）")
        self.assertEqual(ch.ratio_text2(None), "分からない")

    def test_write_refuses_existing(self):
        with mock.patch.object(ch.os, "makedirs"), mock.patch.object(ch.os.path, "lexists", return_value=True), \
                mock.patch.object(ch.os, "open") as op:
            with self.assertRaises(ch.ChainError):
                ch.write_outputs("/nonexistent", {n: b"" for n in ch.OUT_NAMES})
            op.assert_not_called()


if __name__ == "__main__":
    unittest.main()
