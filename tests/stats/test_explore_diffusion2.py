"""T-124 の除外したテーマの網の試し直し（src/stats/explore_diffusion2.py）のテスト。

実行（プロジェクトのルートで）:
    PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -B -m unittest discover -s tests/stats -v

合成のデータだけを使う。本物の日の集計とキャッシュは読まない。ファイルを書かない。
"""

import array
import datetime
import fractions
import gzip
import hashlib
import json
import os
import random
import sys
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(os.path.dirname(HERE))
SRC = os.path.join(PROJECT, "src", "stats")
SCRIPT = os.path.join(SRC, "explore_diffusion2.py")
sys.path.insert(0, SRC)

import explore_diffusion2 as x2  # noqa: E402

ex = x2.ex
es = x2.es
ei = x2.ei
D = datetime.date
V = fractions.Fraction(1, 543539)


class TestRule(unittest.TestCase):
    def test_excl2_rule(self):
        t = {"exclusion_matches": [["a", "B", "name", "exact"]], "present_throughout": True,
             "mean_ratio_at_least_a": True}
        self.assertTrue(x2.excl2_rule(t))
        self.assertFalse(x2.excl2_rule(dict(t, present_throughout=False)))
        self.assertFalse(x2.excl2_rule(dict(t, mean_ratio_at_least_a=False)))
        self.assertFalse(x2.excl2_rule(dict(t, exclusion_matches=[])))

    def test_load_detail_checks_sha(self):
        with mock.patch.object(ei, "read_nofollow", return_value=b"{}"):
            with self.assertRaises(x2.Diffusion2Error):
                x2.load_detail("/x/order5-detail.json", {"tags": []})

    def test_load_detail(self):
        themes = [{"name": "L0", "exclusion_matches": [], "present_throughout": True, "mean_ratio_at_least_a": True},
                  {"name": "E1", "exclusion_matches": [["x"]], "present_throughout": True, "mean_ratio_at_least_a": True},
                  {"name": "E0", "exclusion_matches": [["x"]], "present_throughout": False,
                   "mean_ratio_at_least_a": True}]
        data = json.dumps({"official_result": {"tag_list": ["L0"], "themes": themes}}).encode()
        with mock.patch.object(ei, "read_nofollow", return_value=data), \
                mock.patch.object(ex, "DETAIL_SHA256", hashlib.sha256(data).hexdigest()):
            excl, excl2, flags = x2.load_detail("/x", {"tags": ["L0"]})
        self.assertEqual(excl, ["E0", "E1"])
        self.assertEqual(excl2, ["E1"])
        self.assertEqual(flags["E0"], (False, True))

    def test_no_email(self):
        for p in (SCRIPT, os.path.abspath(__file__)):
            with open(p, "rb") as f:
                self.assertIsNone(ei.EMAIL_RE.search(f.read()))


def day_gz(vocab, p_rows):
    lines = ["#\tgkg-day\t3\t2016-01-01\tofficial"]
    for i, n in enumerate(vocab):
        lines.append("V\t%d\t%s" % (i, n))
    for r in p_rows:
        lines.append("P1\t" + "\t".join(str(x) for x in r))
    return gzip.compress(("\n".join(lines) + "\n").encode("ascii"), mtime=0)


class TestPhase1Parts(unittest.TestCase):
    def test_parse_ee_pairs(self):
        data = day_gz(["E0", "E1", "L0", "E2"], [("1", 0, 1, 4), ("1T", 0, 1, 9), ("1", 0, 2, 5), ("1", 1, 3, 7)])
        ee = array.array("I", bytes(4 * 4))
        x2.parse_ee_pairs(data, {"E0": 0, "E1": 1}, ee, 2)
        self.assertEqual(list(ee), [0, 4, 4, 0])              # E2 は点でない、一覧との組と翻訳の組は数えない

    def test_extract_columns(self):
        el = array.array("I", [1, 2, 3, 4, 5, 6])          # nl=2, ne=3
        self.assertEqual(list(x2.extract_columns(el, 2, 3, [2, 0])), [3, 1, 6, 4])

    def test_after_block_not_opened(self):
        x2._W.update(store="/s", tags=("L0",), excl2=("E0",), cols=[0], t123="/t", small={"el_files": {}}, ne=1,
                     cache_dir="/c", e2i={"E0": 0})
        with mock.patch.object(ex, "load_el", return_value=array.array("I", [0])), \
                mock.patch.object(ei, "read_nofollow") as rd:
            with self.assertRaises(x2.Diffusion2Error):
                x2._month_task((202012, [("2020-12-15", "f", "0" * 64, False)]))
            rd.assert_not_called()


class TestGraph(unittest.TestCase):
    def random_case(self, seed, nl=6, ne=4):
        rng = random.Random(seed)
        ll = array.array("I", [0] * (nl * nl))
        for i in range(nl):
            for j in range(i + 1, nl):
                x = rng.choice([0, 0, 25, 60])
                ll[i * nl + j] = ll[j * nl + i] = x
        el = array.array("I", [rng.choice([0, 0, 30, 90]) for _ in range(nl * ne)])
        ee = array.array("I", [0] * (ne * ne))
        for a in range(ne):
            for b in range(a + 1, ne):
                x = rng.choice([0, 40])
                ee[a * ne + b] = ee[b * ne + a] = x
        ml = [rng.randint(50, 500) for _ in range(nl)]
        me = [rng.randint(50, 500) for _ in range(ne)]
        return ll, el, ee, nl, ne, ml, me

    def test_same_as_t123_without_ee(self):
        for seed in range(5):
            ll, el, ee, nl, ne, ml, me = self.random_case(seed)
            a, _k = x2.build_graph_x(ll, el, None, nl, ne, ml, me, 10000)
            self.assertEqual(a, ex.build_graph(ll, el, nl, ne, ml, me, 10000, True))
            b, _k = x2.build_graph_x(ll, None, None, nl, 0, ml, [], 10000)
            self.assertEqual(b, ex.build_graph(ll, el, nl, ne, ml, me, 10000, False))

    def test_ee_edges_and_stats(self):
        ll, el, ee, nl, ne, ml, me = self.random_case(3)
        adj, knn = x2.build_graph_x(ll, el, ee, nl, ne, ml, me, 10000)
        st = x2.graph_stats(adj, knn, nl, [(True, False), (True, True), (False, False), (True, True)])
        self.assertGreater(st["edges_ee"], 0)
        self.assertEqual(st["nodes"], nl + ne)
        self.assertEqual(st["knn_entries"], sum(len(k) for k in knn))
        self.assertLessEqual(st["knn_excl_both"], st["knn_excl_present"])
        total = sum(len(a) for a in adj) // 2
        self.assertEqual(total, st["edges_ll"] + st["edges_le"] + st["edges_ee"])

    def test_rolling(self):
        data = {m: array.array("I", [m % 7, m % 3]) for m in range(201503, 201513)}
        arrays = {"a": None}
        cur = []
        for want in ([201503, 201504, 201505], [201504, 201505, 201506], [201506, 201507]):
            cur = x2._rolling(cur, want, arrays, {"a": lambda m: data[m]})
            self.assertEqual(list(arrays["a"]), [sum(data[m][0] for m in want), sum(data[m][1] for m in want)])

    def test_window_of_end(self):
        self.assertEqual(x2.window_of_end(201603), es.network_months(D(2016, 4, 11), 12, "M"))
        self.assertEqual(x2.window_of_end(201512)[0], 201503)
        for t in ei.prediction_mondays():
            for timing in ex.TIMINGS:
                ms = ex.window_months(t, timing)
                self.assertEqual(x2.window_of_end(ms[-1]), ms)
                self.assertLess(es.check_network_before(t, ms), 0)


class TestGraphChunk(unittest.TestCase):
    def test_chunk_matches_direct(self):
        nl, n2 = 3, 2
        rng = random.Random(8)
        months = list(range(201503, 201513)) + list(range(201601, 201606))
        ll_m, el_m, ee_m = {}, {}, {}
        for m in months:
            a = array.array("I", [0] * 9)
            for i in range(nl):
                for j in range(i + 1, nl):
                    a[i * nl + j] = a[j * nl + i] = rng.choice([0, 5, 25])
            ll_m[m] = a
            el_m[m] = array.array("I", [rng.choice([0, 3, 30]) for _ in range(nl * n2)])
            e = array.array("I", [0] * 4)
            e[1] = e[2] = rng.choice([0, 30])
            ee_m[m] = e
        m117 = {"tags": ["A", "B", "C"], "month_v1": {m: [50, 60, 70] for m in months},
                "month_docs": {m: 1000 for m in months}}
        meta = {"excl2": ["E0", "E1"], "month_excl2_v1": {m: [40, 30] for m in months}}
        t = D(2016, 4, 11)
        plan = {ex.window_months(t, "now")[-1]: [(0, "now", t.isoformat(), [0, 2])]}
        rises = [array.array("d", [0.1, -0.2, 0.3, 0.5, -0.5])]
        x2._init_graph2("/t117", m117, "/c", meta, plan, rises, [(True, True), (True, True)])
        with mock.patch.object(es, "load_pairs", side_effect=lambda c, mm, m: array.array("I", ll_m[m])), \
                mock.patch.object(x2, "load_part", side_effect=lambda c, mm, m, kind: array.array(
                    "I", (el_m if kind == "el2" else ee_m)[m])):
            feats, stats = x2._graph2_chunk(sorted(plan))
        want = ex.window_months(t, "now")
        ll = [sum(ll_m[m][x] for m in want) for x in range(9)]
        el = [sum(el_m[m][x] for m in want) for x in range(6)]
        ee = [sum(ee_m[m][x] for m in want) for x in range(4)]
        ml = [sum(m117["month_v1"][m][i] for m in want) for i in range(nl)]
        me = [sum(meta["month_excl2_v1"][m][e] for m in want) for e in range(n2)]
        tot = sum(m117["month_docs"][m] for m in want)
        adj, _k = x2.build_graph_x(ll, el, ee, nl, n2, ml, me, tot)
        vks = ex.powers(ex.transition(adj), list(rises[0]))
        got = {k: f for k, g, tm, f in feats}
        for i in (0, 2):
            self.assertEqual(got[(0, i)]["rwr_0.3"], ex.diffusion_features(vks, rises[0][i], i)["rwr_0.3"])
        self.assertEqual({g for _e, g, _s in stats}, {"list", "listexcl2"})


def t123_rows():
    out = []
    for sp in ex.SPLITS:
        for m in ex.MULTIPLIERS:
            out.append({"split": sp, "multiplier": str(m), "horizon_days": "28", "model": "naive", "n_test": "10",
                        "islands_test": "2", "logloss": "0.300000", "auc": "0.700000", "top10_hits": "3",
                        "d_logloss_vs_naive": "-", "d_ll_ci4w_lo": "-", "d_ll_ci4w_hi": "-", "d_top10_vs_naive": "-"})
            for name, *_r in ex.variants():
                out.append({"split": sp, "multiplier": str(m), "horizon_days": "28", "model": name, "n_test": "10",
                            "islands_test": "2", "logloss": "0.290000", "auc": "0.710000", "top10_hits": "4",
                            "d_logloss_vs_naive": "-0.010000" if "shift" in name else "-0.005000",
                            "d_ll_ci4w_lo": "-0.020000", "d_ll_ci4w_hi": "0.001000", "d_top10_vs_naive": "1"})
    return out


class TestOutputs(unittest.TestCase):
    def test_check_naive_same(self):
        rows = t123_rows()
        own = [dict(r, source="T-124") for r in rows if r["model"] == "naive"]
        x2.check_naive_same(rows, own)
        own[0]["logloss"] = "0.300001"
        with self.assertRaises(x2.Diffusion2Error):
            x2.check_naive_same(rows, own)

    def test_count_not_in_table(self):
        data = json.dumps({"official_result": {"themes": [
            {"name": "A", "in_category_table": False}, {"name": "B", "in_category_table": True},
            {"name": "C", "in_category_table": False}]}}).encode()
        with mock.patch.object(ei, "read_nofollow", return_value=data), \
                mock.patch.object(ex, "DETAIL_SHA256", hashlib.sha256(data).hexdigest()):
            self.assertEqual(x2.count_not_in_table("/x", ["A", "B"]), 1)

    def test_read_t123_checks_sha(self):
        with mock.patch.object(ei, "read_nofollow", return_value=b"a\tb\n1\t2\n"):
            with self.assertRaises(x2.Diffusion2Error):
                x2.read_t123_models("/x/models.tsv")

    def test_network_of_and_shift(self):
        self.assertEqual(x2.network_of("diff_listexcl2_now_rwr_0.3"), "listexcl2")
        self.assertEqual(x2.network_of("diff_listexcl_shift_heat_1"), "listexcl")
        self.assertEqual(x2.network_of("wave_list_now"), "list")
        self.assertIsNone(x2.network_of("naive"))
        self.assertEqual(x2.shift_vs_now(t123_rows(), "B", 2, "list"), (7, 7))

    def test_build(self):
        rows = [dict(r, source="T-123") for r in t123_rows()]
        for sp in ex.SPLITS:
            for m in ex.MULTIPLIERS:
                for name, *_r in x2.new_variants():
                    rows.append({"split": sp, "multiplier": str(m), "horizon_days": "28", "model": name,
                                 "n_test": "10", "islands_test": "2", "logloss": "0.290000", "auc": "0.710000",
                                 "top10_hits": "4", "d_logloss_vs_naive": "-0.007000", "d_ll_ci4w_lo": "-0.020000",
                                 "d_ll_ci4w_hi": "-0.001000", "d_top10_vs_naive": "1", "source": "T-124"})
        st = {"nodes": 5, "edges_ll": 3, "edges_le": 2, "edges_ee": 1, "isolated": 0, "knn_entries": 10,
              "knn_excl": 4, "knn_excl_present": 3, "knn_excl_at_least_a": 2, "knn_excl_both": 2}
        stats = [(201603, g, dict(st)) for g in x2.NETWORKS_ALL]
        plan = {201603: [(0, "now", "2016-04-11", [0])]}
        meta = {"phase1_sha256": "0" * 64, "excl2_not_in_table": 1}
        ctx = {"refs": {}, "v": V}
        flags = {"EX_A": (True, True), "EX_B": (False, False)}
        f1 = x2.build_outputs(rows, [("B", "m", 0.1, 0.2, 0.3)], stats, [201603], plan, meta, ctx,
                              ["EX_A", "EX_B"], ["EX_A"], flags, 100)
        f2 = x2.build_outputs(rows, [("B", "m", 0.1, 0.2, 0.3)], stats, [201603], plan, meta, ctx,
                              ["EX_A", "EX_B"], ["EX_A"], flags, 100)
        self.assertEqual(f1, f2)
        s = f1["summary.md"].decode("utf-8")
        self.assertNotIn("**", s)
        self.assertNotIn("EX_A", s)
        for n in ("models.tsv", "network.tsv", "hub.tsv"):
            self.assertNotIn(b"EX_A", f1[n])
        for phrase in ("行って戻る道", "除外したテーマへの線が入る", "shift の差が now の差以下", "1825", ei.CITATION_JA,
                       "倍率 2 では 21 / 21", "区別できない", "v1 の4章の shift の文", "区分表に無いテーマ", "2つを同時に変えている"):
            self.assertIn(phrase, s)
        run = json.loads(f1["run.json"])
        self.assertEqual(run["models_per_split_multiplier_all_networks"], 42)
        self.assertIn("src/stats/explore_diffusion2.py", run["code"])
        for n, d in f1.items():
            self.assertIsNone(ei.EMAIL_RE.search(d), n)

    def test_write_refuses_existing(self):
        with mock.patch.object(x2.os, "makedirs"), mock.patch.object(x2.os.path, "lexists", return_value=True), \
                mock.patch.object(x2.os, "open") as op:
            with self.assertRaises(x2.Diffusion2Error):
                x2.write_outputs("/nonexistent", {n: b"" for n in x2.OUT_NAMES})
            op.assert_not_called()


if __name__ == "__main__":
    unittest.main()
