"""T-123 の拡散の残差と波面の勾配（src/stats/explore_diffusion.py）のテスト。

実行（プロジェクトのルートで）:
    PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -B -m unittest discover -s tests/stats -v

合成のデータだけを使う。本物の日の集計とキャッシュは読まない。ファイルを書かない。
"""

import array
import datetime
import fractions
import gzip
import json
import math
import os
import random
import sys
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(os.path.dirname(HERE))
SRC = os.path.join(PROJECT, "src", "stats")
SCRIPT = os.path.join(SRC, "explore_diffusion.py")
sys.path.insert(0, SRC)

import explore_diffusion as ex  # noqa: E402

es = ex.es
ei = ex.ei
D = datetime.date
DAY = datetime.timedelta(days=1)
V = fractions.Fraction(1, 543539)


class TestOptions(unittest.TestCase):
    def test_kernels(self):
        for tau in ex.HEAT_TAUS:
            cs = ex.kernel_coefs("heat_%g" % tau)
            self.assertEqual(len(cs), ex.K_MAX)
            self.assertAlmostEqual(sum(cs), 1 - math.exp(-tau), places=9)
        for a in ex.RWR_ALPHAS:
            cs = ex.kernel_coefs("rwr_%g" % a)
            self.assertAlmostEqual(sum(cs), (1 - a) * (1 - (1 - a) ** ex.K_MAX), places=12)
        with self.assertRaises(ex.DiffusionError):
            ex.kernel_coefs("other_1")

    def test_variants(self):
        vs = ex.variants()
        self.assertEqual(len(vs), 2 * 2 * (6 + 1))
        self.assertEqual(len({v[0] for v in vs}), len(vs))

    def test_no_email(self):
        for p in (SCRIPT, os.path.abspath(__file__)):
            with open(p, "rb") as f:
                self.assertIsNone(ei.EMAIL_RE.search(f.read()))


class TestWindows(unittest.TestCase):
    def test_now_and_shift(self):
        t = D(2016, 4, 11)
        self.assertEqual(ex.window_months(t, "now"), es.network_months(t, 12, "M"))
        sh = ex.window_months(t, "shift")
        self.assertEqual(sh[0], 201503)            # 区画の前の月（201501・201502）は入れない
        self.assertEqual(sh[-1], 201512)
        t = D(2018, 7, 2)
        sh = ex.window_months(t, "shift")
        self.assertEqual((sh[0], sh[-1], len(sh)), (201704, 201803, 12))

    def test_all_before_t(self):
        for t in ei.prediction_mondays():
            for timing in ex.TIMINGS:
                self.assertLess(es.check_network_before(t, ex.window_months(t, timing)), 0)
            self.assertLessEqual(es.check_network_before(t, ex.window_months(t, "shift")), -90)


class TestGraph(unittest.TestCase):
    def test_knn_lift(self):
        cands = [(1, 100), (2, 30), (3, 10)]
        marg = [200, 10000, 40, 50]
        self.assertEqual(ex.knn_lift(cands, 200, marg, 100000), [(2, 30), (1, 100)])
        self.assertEqual(ex.knn_lift(cands, 0, marg, 100000), [])

    def test_build_graph_no_excl_excl_edges(self):
        nl, ne = 3, 2
        ll = array.array("I", [0, 30, 0, 30, 0, 25, 0, 25, 0])
        el = array.array("I", [40, 0, 0, 0, 0, 50])      # 一覧0−除外0、一覧2−除外1
        ml = [100, 100, 100]
        me = [100, 100]
        a = ex.build_graph(ll, el, nl, ne, ml, me, 10000, False)
        self.assertEqual(len(a), 3)
        self.assertEqual(a[0], {1: 30})
        b = ex.build_graph(ll, el, nl, ne, ml, me, 10000, True)
        self.assertEqual(len(b), 5)
        self.assertEqual(b[3], {0: 40})
        self.assertEqual(b[4], {2: 50})
        self.assertNotIn(4, b[3])

    def test_transition_and_powers(self):
        adj = [{1: 1}, {0: 1, 2: 3}, {1: 3}, {}]
        P = ex.transition(adj)
        self.assertEqual(P[1], [(0, 0.25), (2, 0.75)])
        self.assertEqual(P[3], [])
        vks = ex.powers(P, [1.0, 0.0, 2.0, 5.0], 3)
        self.assertEqual(vks[0], [0.0, 1.75, 0.0, 0])
        self.assertEqual(vks[1][0], 1.75)

    def test_features(self):
        vks = [[0.1], [0.2], [0.3]] + [[0.0]] * (ex.K_MAX - 3)
        f = ex.diffusion_features(vks, -1.0, 0)
        self.assertEqual((f["E1"], f["E2"], f["E3"], f["mono"]), (0.1, 0.2, 0.3, 1.0))
        self.assertAlmostEqual(f["heat_1"], math.exp(-1) * (0.1 + 0.2 / 2 + 0.3 / 6))
        self.assertEqual(ex.diffusion_features(vks, 0.5, 0)["mono"], 0.0)

    def test_chunks(self):
        self.assertEqual(ex.chunks_of(list(range(7)), 3), [[0, 1, 2], [3, 4, 5], [6]])


def day_gz(day, vocab, p_rows):
    lines = ["#\tgkg-day\t3\t%s\tofficial" % day]
    for i, n in enumerate(vocab):
        lines.append("V\t%d\t%s" % (i, n))
    for r in p_rows:
        lines.append("P1\t" + "\t".join(str(x) for x in r))
    return gzip.compress(("\n".join(lines) + "\n").encode("ascii"), mtime=0)


class TestPhase1Parts(unittest.TestCase):
    def test_parse_el_pairs(self):
        vocab = ["L0", "L1", "E0", "E1", "O0"]
        data = day_gz("2016-01-01", vocab, [("1", 0, 2, 5), ("1T", 0, 2, 9), ("1", 1, 3, 2), ("1", 0, 1, 7),
                                            ("1", 2, 3, 4), ("1", 3, 4, 1), ("1", 3, 1, 1)])
        el = array.array("I", bytes(4 * 4))
        ex.parse_el_pairs(data, {"L0": 0, "L1": 1}, {"E0": 0, "E1": 1}, el, 2)
        self.assertEqual(list(el), [5, 0, 0, 3])          # 一覧どうし・除外どうし・ほかのテーマ・翻訳の組は数えない

    def test_load_excluded_checks_sha(self):
        with mock.patch.object(ei, "read_nofollow", return_value=b"{}"):
            with self.assertRaises(ex.DiffusionError):
                ex.load_excluded("/x/order5-detail.json", {"tags": []})

    def test_after_block_not_opened(self):
        ex._W.update(store="/s", tags=("L0",), excl=("E0",), li={"L0": 0}, ei_={"E0": 0}, cache_dir="/c")
        with mock.patch.object(ei, "read_nofollow") as rd:
            with self.assertRaises(ex.DiffusionError):
                ex._month_task((202012, [("2020-12-15", "f", "0" * 64, False)]))
            rd.assert_not_called()


class TestRises(unittest.TestCase):
    def test_rises_read_only_past(self):
        days = ei.block_days()
        vals = [1e-5] * len(days)
        t = D(2017, 6, 5)
        a = ex.rises_of(days, vals, [t], V)
        vals2 = [x if d < t else 9e-3 for d, x in zip(days, vals)]
        b = ex.rises_of(days, vals2, [t], V)
        self.assertEqual(a, b)
        self.assertAlmostEqual(a[0], 0.0)

    def test_excl_series(self):
        counts = array.array("I", [1, 2, 3, 4])
        self.assertEqual(ex.excl_series(counts, [10, 20], [False, True], 2, 1), [0.2, None])


class TestGraphChunk(unittest.TestCase):
    def test_rolling_window_equals_direct_sum(self):
        nl, ne = 3, 2
        rng = random.Random(4)
        months = [m for m in range(201503, 201513)] + [m for m in range(201601, 201606)]
        ll_m = {m: array.array("I", [0] * 9) for m in months}
        el_m = {m: array.array("I", [rng.choice([0, 3, 30]) for _ in range(nl * ne)]) for m in months}
        for m in months:
            for i in range(nl):
                for j in range(i + 1, nl):
                    x = rng.choice([0, 5, 25])
                    ll_m[m][i * nl + j] = x
                    ll_m[m][j * nl + i] = x
        m117 = {"tags": ["A", "B", "C"], "month_v1": {m: [50, 60, 70] for m in months},
                "month_docs": {m: 1000 for m in months}}
        meta = {"excluded": ["E0", "E1"], "month_excl_v1": {m: [40, 30] for m in months}}
        t1, t2 = D(2016, 4, 11), D(2016, 5, 2)
        plan = {}
        for ti, t in ((0, t1), (1, t2)):
            plan.setdefault(ex.window_months(t, "now")[-1], []).append((ti, "now", t.isoformat(), [0, 2]))
        rises = [array.array("d", [0.1, -0.2, 0.3, 0.5, -0.5]), array.array("d", [0.0, 0.4, -0.1, 0.2, 0.1])]
        ex._init_graph("/t117", m117, "/c", meta, plan, rises)
        with mock.patch.object(es, "load_pairs", side_effect=lambda c, mm, m: array.array("I", ll_m[m])), \
                mock.patch.object(ex, "load_el", side_effect=lambda c, mm, m: array.array("I", el_m[m])):
            out = ex._graph_chunk(sorted(plan))
        got = {(k, g, tm): f for k, g, tm, f in out}
        for ti, t in ((0, t1), (1, t2)):
            want = ex.window_months(t, "now")
            ll = [sum(ll_m[m][x] for m in want) for x in range(9)]
            el = [sum(el_m[m][x] for m in want) for x in range(nl * ne)]
            ml = [sum(m117["month_v1"][m][i] for m in want) for i in range(nl)]
            me = [sum(meta["month_excl_v1"][m][e] for m in want) for e in range(ne)]
            tot = sum(m117["month_docs"][m] for m in want)
            for g in ex.GRAPHS:
                adj = ex.build_graph(ll, el, nl, ne, ml, me, tot, g == "listexcl")
                s = list(rises[ti][:nl]) + (list(rises[ti][nl:]) if g == "listexcl" else [])
                vks = ex.powers(ex.transition(adj), s)
                for i in (0, 2):
                    f = ex.diffusion_features(vks, s[i], i)
                    self.assertEqual(got[((ti, i), g, "now")]["heat_1"], f["heat_1"])
                    self.assertEqual(got[((ti, i), g, "now")]["E2"], f["E2"])


class TestEvaluate(unittest.TestCase):
    def test_hub_regression_uses_train_only(self):
        rng = random.Random(1)
        keys = [(t, 0) for t in range(30)]
        feats = {(k, "list", "now"): {"heat_1": rng.random(), "deg": rng.randint(1, 20), "vol": rng.random()}
                 for k in keys}
        own = {k: rng.random() for k in keys}
        info1, info2 = [], []
        a = ex.variant_columns("d", "diffusion", "list", "now", "heat_1", feats, keys, keys[:20], own, info1, "B")
        for k in keys[20:]:
            feats[(k, "list", "now")]["heat_1"] = 99.0
        ex.variant_columns("d", "diffusion", "list", "now", "heat_1", feats, keys, keys[:20], own, info2, "B")
        self.assertEqual(info1, info2)
        self.assertEqual(sorted(a), ["d_exp", "d_res"])

    def test_summary(self):
        results = []
        for sp in ex.SPLITS:
            for m in ex.MULTIPLIERS:
                results.append((sp, m, "naive", {"n": 10, "pos": 2, "logloss": 0.3, "auc": 0.7, "topk": 3}))
                for name, *_r in ex.variants():
                    results.append((sp, m, name, {"n": 10, "pos": 2, "logloss": 0.29, "auc": 0.71, "topk": 4,
                                                  "d_logloss": -0.01, "d_ll_ci": (-0.02, 0.001), "d_topk": 1}))
        meta = {"phase1_sha256": "0" * 64, "excluded": ["E%d" % i for i in range(5)]}
        ctx = {"refs": {}, "v": V}
        f1 = ex.build_outputs(results, [("B", "x", 0.1, 0.2, 0.3)], meta, ctx, 100)
        f2 = ex.build_outputs(results, [("B", "x", 0.1, 0.2, 0.3)], meta, ctx, 100)
        self.assertEqual(f1, f2)
        s = f1["summary.md"].decode("utf-8")
        self.assertNotIn("**", s)
        self.assertNotIn("E0", s)
        for phrase in ("除外どうしの線を入れていない", "既に何度も見た", "多重比較の補正をしていない", ei.CITATION_JA):
            self.assertIn(phrase, s)
        run = json.loads(f1["run.json"])
        self.assertEqual(run["models_total"], 28 * 3 * 2)
        self.assertIn("src/stats/explore_diffusion.py", run["code"])
        for n, d in f1.items():
            self.assertIsNone(ei.EMAIL_RE.search(d), n)

    def test_write_refuses_existing(self):
        with mock.patch.object(ex.os, "makedirs"), mock.patch.object(ex.os.path, "lexists", return_value=True), \
                mock.patch.object(ex.os, "open") as op:
            with self.assertRaises(ex.DiffusionError):
                ex.write_outputs("/nonexistent", {n: b"" for n in ex.OUT_NAMES})
            op.assert_not_called()


if __name__ == "__main__":
    unittest.main()
