"""T-119 のグラフ理論によるネットワーク分析の探索（src/stats/explore_graph.py）のテスト。

実行（プロジェクトのルートで）:
    PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -B -m unittest discover -s tests/stats -v

合成のデータだけを使う。本物の日の集計とキャッシュは読まない。ファイルを書かない。
"""

import array
import datetime
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
SCRIPT = os.path.join(SRC, "explore_graph.py")
sys.path.insert(0, SRC)

import explore_graph as eg  # noqa: E402

em = eg.em
es = eg.es
ei = eg.ei
D = datetime.date


def adj_from_edges(n, edges):
    adj = [dict() for _ in range(n)]
    for a, b, w in edges:
        adj[a][b] = w
        adj[b][a] = w
    return adj


class TestGraphFunctions(unittest.TestCase):
    def test_lpa_two_groups(self):
        edges = [(0, 1, 10), (1, 2, 10), (0, 2, 10), (3, 4, 10), (4, 5, 10), (3, 5, 10), (2, 3, 1)]
        lab, sweeps = eg.label_propagation(adj_from_edges(6, edges))
        self.assertEqual(lab, [0, 0, 0, 3, 3, 3])
        self.assertEqual(eg.label_propagation(adj_from_edges(6, edges)), (lab, sweeps))

    def test_lpa_isolated(self):
        lab, _s = eg.label_propagation([dict(), dict()])
        self.assertEqual(lab, [0, 1])

    def test_pagerank(self):
        adj = adj_from_edges(4, [(0, 1, 1), (0, 2, 1), (0, 3, 1)])
        pr = eg.pagerank(adj)
        self.assertAlmostEqual(sum(pr), 1.0)
        self.assertGreater(pr[0], pr[1])
        self.assertAlmostEqual(pr[1], pr[2])

    def test_betweenness_exact_when_all_sources(self):
        adj = adj_from_edges(3, [(0, 1, 1), (1, 2, 1)])
        bc = eg.betweenness_approx(adj, [0, 1, 2])
        self.assertAlmostEqual(bc[1], 1.0)
        self.assertAlmostEqual(bc[0], 0.0)
        adj = adj_from_edges(5, [(0, 1, 1), (1, 2, 1), (2, 3, 1), (3, 4, 1)])
        bc = eg.betweenness_approx(adj, list(range(5)))
        self.assertAlmostEqual(bc[2], 4 / 6)                  # 中央は 4 組の最短経路の上（6 組のうち）

    def test_new_ties(self):
        n = 3
        rec = array.array("I", [0, 6, 9, 6, 0, 0, 9, 0, 0])
        prev = array.array("I", [0, 30, 1, 30, 0, 0, 1, 0, 0])
        nt = eg.new_ties(rec, prev, n)
        self.assertEqual(nt[0][0], 0.5)
        self.assertAlmostEqual(nt[0][1], math.log1p(1))
        self.assertAlmostEqual(nt[0][2], 9 / 15)
        self.assertEqual(nt[1][0], 0.0)
        rec2 = array.array("I", [0] * 9)
        self.assertEqual(eg.new_ties(rec2, prev, n)[0], (None, 0.0, None))

    def test_nmi(self):
        self.assertAlmostEqual(eg.nmi([0, 0, 1, 1], [5, 5, 7, 7]), 1.0)
        self.assertAlmostEqual(eg.nmi([0, 0, 1, 1], [0, 1, 0, 1]), 0.0)

    def test_comm_changes_and_rise(self):
        now = [0, 0, 0, 3]
        prev = [0, 0, 2, 2]
        ch = eg.comm_changes(now, prev)
        self.assertAlmostEqual(ch[0], 1 - 2 / 3)       # {0,1,2} と {0,1}
        self.assertAlmostEqual(ch[2], 1 - 1 / 4)       # {0,1,2} と {2,3}
        rises = [1.0, 2.0, None, 5.0]
        sums = eg.comm_sums(now, rises)
        self.assertAlmostEqual(eg.comm_rise(0, now, sums, rises), 2.0)
        self.assertAlmostEqual(eg.comm_rise(2, now, sums, rises), 1.5)
        self.assertIsNone(eg.comm_rise(3, now, sums, rises))

    def test_hops(self):
        nb = es.Nbrs([[(1, 0.5, 0.1), (2, 0.5, 0.1)], [(3, 1.0, 0.1), (0, 1.0, 0.1)], [(3, 1.0, 0.1)], []])
        rises = [0.0, 1.0, 3.0, 10.0]
        h1, h2 = eg.hop_signals(0, nb, rises)
        self.assertAlmostEqual(h1, 2.0)
        self.assertAlmostEqual(h2, 10.0)                # 2歩先は 3 だけ（0 と 1・2 は除く）

    def test_union_graph(self):
        nb = es.Nbrs([[(1, 0.5, 0.1)], [], []])
        mat = array.array("I", [0, 7, 0, 7, 0, 0, 0, 0, 0])
        adj = eg.union_graph(nb, mat, 3)
        self.assertEqual(adj, [{1: 7}, {0: 7}, {}])


class TestMonths(unittest.TestCase):
    def test_graph_months(self):
        base, prev, rec3, rec1 = eg.graph_months(201604)
        self.assertEqual(base[0], 201504)
        self.assertEqual(base[-1], 201603)
        self.assertEqual(prev[0], 201503)
        self.assertEqual(prev[-1], 201602)
        self.assertEqual(rec3, [201601, 201602, 201603])
        self.assertEqual(rec1, 201603)
        base, prev, _r3, _r1 = eg.graph_months(201603)
        self.assertEqual(len(prev), 11)               # 区画の前の月は入れない

    def test_all_prediction_days_before(self):
        for t in ei.prediction_mondays():
            mk = es.month_key(t)
            base, prev, rec3, rec1 = eg.graph_months(mk)
            self.assertEqual(base, es.network_months(t, 12, "M"))
            for ms in (base, prev, rec3, [rec1], eg.graph_months(es.add_months(mk, -1))[0]):
                self.assertLess(es.check_network_before(t, ms), 0)


class TestOptions(unittest.TestCase):
    def test_counts(self):
        names = [n for n, _k, _c, _r in eg.MODELS]
        self.assertEqual(len(names), len(set(names)))
        self.assertEqual(len(eg.MODELS) - 1, 12)
        for c in eg.ALL_COLUMNS:
            self.assertIn(c, eg.GRAPH_COLUMNS)

    def test_no_email(self):
        for p in (SCRIPT, os.path.abspath(__file__)):
            with open(p, "rb") as f:
                self.assertIsNone(ei.EMAIL_RE.search(f.read()))


def tiny_table(seed=7):
    rng = random.Random(seed)
    ms = ei.prediction_mondays()
    tb = {"t": [], "tag": [], "week": [], "family": []}
    for m in em.MULTIPLIERS:
        tb["y%d" % m] = []
        for k in range(len(em.naive.FEATURES)):
            tb["naive%d_%d" % (m, k)] = []
    for c in eg.GRAPH_COLUMNS:
        tb[c] = []
    for wi, t in enumerate(ms):
        if wi % 3:
            continue
        for j in range(10):
            sig = rng.gauss(0, 1)
            tb["t"].append(t)
            tb["tag"].append("T%02d" % j)
            tb["week"].append(wi)
            tb["family"].append("other")
            for m in em.MULTIPLIERS:
                tb["y%d" % m].append(1 if rng.random() < 1 / (1 + math.exp(-(sig - 1 - m / 4))) else 0)
                for k in range(len(em.naive.FEATURES)):
                    tb["naive%d_%d" % (m, k)].append(1.0 if k == 0 else rng.gauss(0, 1))
            for c in eg.GRAPH_COLUMNS:
                tb[c].append(0.0 if c.endswith("_miss") or "_miss_" in c else sig + rng.gauss(0, 1))
    for c in list(eg.GRAPH_COLUMNS) + ["naive%d_%d" % (m, k) for m in em.MULTIPLIERS
                                      for k in range(len(em.naive.FEATURES))]:
        tb[c] = array.array("d", tb[c])
    for m in em.MULTIPLIERS:
        tb["y%d" % m] = array.array("b", tb["y%d" % m])
    tb["train"] = [r for r, t in enumerate(tb["t"]) if es.split_of(t) == "train"]
    tb["test"] = [r for r, t in enumerate(tb["t"]) if es.split_of(t) == "test"]
    return tb


class TestOutputs(unittest.TestCase):
    def test_build(self):
        tb = tiny_table()
        eg._init_fit(tb)
        res = {}
        with mock.patch.dict(em.GBDT, {"trees": 3, "min_leaf": 20}):
            for m in em.MULTIPLIERS:
                for name, _k, _c, _r in eg.MODELS:
                    args, out = eg._fit_task((m, name))
                    res[args] = out
            info = {"daily_min_read": "2015-03-09", "daily_max_read": "2020-10-12",
                    "network_last_day_minus_t_max_days": -1, "phase1_sha256": "0" * 64, "phase1_label": "x",
                    "refs": {}, "v": "1/543539", "graph_months": [201603, 201604]}
            cstats = [(201603, cv, {"n_comm": 5, "singletons": 1, "max_size": 9, "median_size": 2, "n_size_ge5": 1,
                                    "nmi_prev": None, "sweeps": 3}) for cv in eg.COMM_VARIANTS]
            cstats += [(201604, cv, {"n_comm": 6, "singletons": 2, "max_size": 8, "median_size": 2,
                                     "n_size_ge5": 1, "nmi_prev": 0.8, "sweeps": 4}) for cv in eg.COMM_VARIANTS]
            f1 = eg.build_outputs(tb, info, cstats, res)
            f2 = eg.build_outputs(tb, info, cstats, res)
        self.assertEqual(f1, f2)
        self.assertEqual(sorted(f1), sorted(eg.OUT_NAMES))
        s = f1["summary.md"].decode("utf-8")
        for phrase in ("検証の期間の再利用", "多重比較の補正をしていない", "独立でない", "近似", "除外の規則の漏れ",
                       "WB のテーマの段", ei.CITATION_JA, "出した差の範囲"):
            self.assertIn(phrase, s)
        self.assertNotIn("T00", s)                    # 要約にテーマの名前を載せない
        run = json.loads(f1["run.json"])
        self.assertEqual(run["models_total"], 36)
        self.assertEqual(run["ranges_total"], 39)
        self.assertIn("src/stats/explore_graph.py", run["code"])
        for n, d in f1.items():
            self.assertIsNone(ei.EMAIL_RE.search(d), n)

    def test_write_refuses_existing(self):
        with mock.patch.object(eg.os, "makedirs"), mock.patch.object(eg.os.path, "lexists", return_value=True), \
                mock.patch.object(eg.os, "open") as op:
            with self.assertRaises(eg.GraphError):
                eg.write_outputs("/nonexistent", {n: b"" for n in eg.OUT_NAMES})
            op.assert_not_called()


if __name__ == "__main__":
    unittest.main()
