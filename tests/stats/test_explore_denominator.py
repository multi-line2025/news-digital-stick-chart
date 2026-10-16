"""T-122 の分母の感度分析と中心性の確かめ（src/stats/explore_denominator.py）のテスト。

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
SCRIPT = os.path.join(SRC, "explore_denominator.py")
sys.path.insert(0, SRC)

import explore_denominator as ed  # noqa: E402

es = ed.es
ei = ed.ei
em = ed.em
naive = ed.naive
D = datetime.date
V = fractions.Fraction(1, 543539)


def day_gz(day, themes, docs):
    names = sorted(themes)
    lines = ["#\tgkg-day\t3\t%s\tofficial" % day]
    for i, n in enumerate(names):
        lines.append("V\t%d\t%s" % (i, n))
    for g, k in docs:
        lines.append("D\t%s\t%d" % (g, k))
    for i, n in enumerate(names):
        for g, a, b, c, d in themes[n]:
            lines.append("T\t%s\t%d\t%d\t%d\t%d\t%d" % (g, i, a, b, c, d))
    return gzip.compress(("\n".join(lines) + "\n").encode("ascii"), mtime=0)


class TestCounting(unittest.TestCase):
    def test_count_day(self):
        data = day_gz("2016-01-01", {"AAA": [("1", 3, 4, 5, 6), ("1T", 9, 9, 9, 9)], "BBB": [("1", 2, 0, 0, 2)],
                                     "ZZZ": [("1", 1, 1, 1, 1)]}, [("1", 50), ("1T", 30)])
        v1, v2, v12, docs, d7 = ed.count_day(data, "2016-01-01", ("AAA", "BBB", "CCC"))
        self.assertEqual(v1, [3, 2, 0])
        self.assertEqual(v2, [4, 0, 0])
        self.assertEqual(v12, [6, 2, 0])
        self.assertEqual(docs, 50)             # 翻訳の組は数えない
        self.assertEqual(d7, 6 + 2 + 1)        # C7 の分母は一覧の外のテーマも含む全テーマの和

    def test_after_block_not_opened(self):
        ed._W["store"] = "/store"
        with mock.patch.object(ei, "read_nofollow") as rd:
            with self.assertRaises(ed.DenomError):
                ed._day_task(("2020-12-15", "f.tsv.gz", "0" * 64))
            rd.assert_not_called()

    def test_ratio_series(self):
        meta = {"tags": ["A", "B"], "missing": ["2016-01-02"], "days": ["2016-01-01", "2016-01-02", "2016-01-03"],
                "v12": array.array("I", [2, 1, 0, 0, 4, 4]), "v1": array.array("I", [1, 1, 0, 0, 2, 2]),
                "v2": array.array("I", [3, 0, 0, 0, 1, 0]), "docs": [10, 0, 20], "c7_totals": [4, 0, 8]}
        self.assertEqual(ed.ratio_series(meta, "C7"), [[0.5, None, 0.5], [0.25, None, 0.5]])
        self.assertEqual(ed.ratio_series(meta, "X"), [[0.2, None, 0.2], [0.1, None, 0.2]])
        self.assertEqual(ed.ratio_series(meta, "C1"), [[0.1, None, 0.1], [0.1, None, 0.1]])
        self.assertEqual(ed.ratio_series(meta, "C3"), [[0.3, None, 0.05], [0.0, None, 0.0]])

    def test_v_of(self):
        self.assertEqual(ed.v_of("C1_V", V), V)
        self.assertEqual(ed.v_of("C1_m", V), ed.V_TINY)
        self.assertLess(ed.V_TINY, V / 1000)

    def test_options(self):
        self.assertEqual(len(ed.VARIANTS), 8)
        self.assertIn(ed.BASE_VARIANT, ed.VARIANTS)


class TestFacts(unittest.TestCase):
    def test_data_facts(self):
        meta = {"missing": ["d2"], "days": ["d1", "d2", "d3"], "v1": array.array("I", [1, 2]),
                "v12": array.array("I", [1, 2]), "c7_totals": [5, 99, 7], "docs": [3, 99, 2]}
        f = ed.data_facts(meta)
        self.assertTrue(f["v1_equals_v12"])
        self.assertEqual(f["max_denominator"], {"C7": 7, "docs": 3})


class TestSplits(unittest.TestCase):
    def test_splits_do_not_overlap(self):
        ms = ei.prediction_mondays()
        keys = [(ti, 0) for ti in range(len(ms))]
        for sp in ed.SPLITS:
            tr, te = ed.split_rows(keys, ms, sp)
            last_tr = max(ms[k[0]] for k in tr)
            first_te = min(ms[k[0]] for k in te)
            self.assertLess(last_tr + datetime.timedelta(days=28), first_te + datetime.timedelta(days=1))
        _tr, te = ed.split_rows(keys, ms, "B")
        self.assertTrue(all(ms[k[0]] <= es.TRAIN_LAST for k in te))


def lv(rng):
    b = rng.random() * 1e-5
    return {"B": b, "c": b * rng.random(), "P": b, "S0": b * 2 * rng.random(), "S35": b * 3 * rng.random()}


def synthetic_rows(seed, p_island=0.2):
    rng = random.Random(seed)
    ms = ei.prediction_mondays()
    rows = {}
    for ti in range(0, len(ms), 2):
        for i in range(12):
            x = rng.random()
            rows[(ti, i)] = ((x < p_island, x < p_island / 2, x < p_island / 4), lv(rng))
    return rows


class TestCompare(unittest.TestCase):
    def test_rates_and_overlap(self):
        ms = ei.prediction_mondays()
        a = {(0, 0): ((True, True, False), {}), (0, 1): ((False, False, False), {}), (1, 0): ((True, False, False), {})}
        b = {(0, 0): ((True, False, False), {}), (0, 1): ((True, True, False), {}), (2, 5): ((True, True, True), {})}
        r = ed.rates(a, ms)
        self.assertEqual(r[2]["all"], [3, 2])
        self.assertEqual(r[4]["all"], [3, 1])
        o = ed.overlap(a, b, ms)
        self.assertEqual(o[2]["targets_both"], 2)
        self.assertEqual((o[2]["agree"], o[2]["both_islands"], o[2]["only_base"], o[2]["only_other"]), (1, 1, 0, 1))
        self.assertEqual((o[4]["only_base"], o[4]["only_other"]), (1, 1))
        self.assertEqual(o[4]["top_weeks"], [(ms[0].isoformat(), 2)])


class TestCentrality(unittest.TestCase):
    def test_ols_exact(self):
        rng = random.Random(1)
        X = [[1.0, rng.random(), rng.random()] for _ in range(50)]
        y = [2 + 3 * x[1] - x[2] for x in X]
        coef = ed.ols(X, y)
        for a, b in zip(coef, (2, 3, -1)):
            self.assertAlmostEqual(a, b, places=8)
        self.assertAlmostEqual(ed.r_squared(X, y, coef), 1.0)

    def test_residualize_uses_train_only(self):
        rng = random.Random(2)
        keys = [(t, 0) for t in range(40)]
        vals = {c: {} for c in ed.CENTRALITY + ed.VOLUME_FEATURES}
        for k in keys:
            f = [rng.random() for _ in ed.VOLUME_FEATURES]
            for c, x in zip(ed.VOLUME_FEATURES, f):
                vals[c][k] = x
            for c in ed.CENTRALITY:
                vals[c][k] = 1 + 2 * f[0] - f[1] + 0.5 * f[2]
        tr = keys[:30]
        resid, info = ed.residualize(vals, tr, keys)
        for c in ed.CENTRALITY:
            self.assertAlmostEqual(info[c]["r2"], 1.0)
            self.assertTrue(all(abs(resid[c + "_resid"][k]) < 1e-8 for k in keys))
        for k in keys[30:]:
            for c in ed.CENTRALITY:
                vals[c][k] = 99.0
        _resid2, info2 = ed.residualize(vals, tr, keys)
        self.assertEqual(info[ed.CENTRALITY[0]]["coef"], info2[ed.CENTRALITY[0]]["coef"])

    def test_volume_features(self):
        mv = {201601: [4, 0], 201602: [4, 0], 201603: [8, 0]}
        f = ed.volume_features(0, [201601, 201602, 201603], [201603], mv, 9)
        self.assertAlmostEqual(f["vol_ratio"], math.log(9 / (16 / 4 + 1)))
        self.assertAlmostEqual(f["vol_level"], math.log(17))
        self.assertAlmostEqual(f["deg_level"], math.log1p(9))


class TestOutputs(unittest.TestCase):
    def test_build(self):
        ms = ei.prediction_mondays()
        tags = ["T%02d" % i for i in range(12)]
        rows = {var: synthetic_rows(k + 1) for k, var in enumerate(ed.VARIANTS)}
        naive_res = {}
        for var in ed.VARIANTS:
            naive_res.update(ed.naive_scores(var, rows[var], ms, tags, ed.v_of(var, V)))
        base = rows[ed.BASE_VARIANT]
        rng = random.Random(9)
        vals = {c: {k: rng.gauss(0, 1) for k in base} for c in ed.CENTRALITY + ed.VOLUME_FEATURES}
        cent = ed.centrality_eval(base, vals, ms, tags, V)
        meta = {"phase1_sha256": "0" * 64, "v1_equals_v12": True, "max_denominator": {"C7": 7000000, "docs": 300000}}
        ctx = {"refs": {}, "v": V}
        f1 = ed.build_outputs(meta, ctx, rows, ms, naive_res, cent, {"v12_equals_t117_c7": True})
        f2 = ed.build_outputs(meta, ctx, rows, ms, naive_res, cent, {"v12_equals_t117_c7": True})
        self.assertEqual(f1, f2)
        self.assertEqual(sorted(f1), sorted(ed.OUT_NAMES))
        s = f1["summary.md"].decode("utf-8")
        self.assertNotIn("**", s)
        self.assertNotIn("T00", s)
        for phrase in ("検証の期間の再利用", "封印された候補ではない", "多重比較の補正をしていない", ei.CITATION_JA,
                       "X と C1 が同じになる理由", "条件として効かない大きさ", "V1 の文書の生の数"):
            self.assertIn(phrase, s)
        run = json.loads(f1["run.json"])
        self.assertIn("src/stats/explore_denominator.py", run["code"])
        for n, d in f1.items():
            self.assertIsNone(ei.EMAIL_RE.search(d), n)

    def test_no_email_in_source(self):
        for p in (SCRIPT, os.path.abspath(__file__)):
            with open(p, "rb") as f:
                self.assertIsNone(ei.EMAIL_RE.search(f.read()))

    def test_write_refuses_existing(self):
        with mock.patch.object(ed.os, "makedirs"), mock.patch.object(ed.os.path, "lexists", return_value=True), \
                mock.patch.object(ed.os, "open") as op:
            with self.assertRaises(ed.DenomError):
                ed.write_outputs("/nonexistent", {n: b"" for n in ed.OUT_NAMES})
            op.assert_not_called()


if __name__ == "__main__":
    unittest.main()
