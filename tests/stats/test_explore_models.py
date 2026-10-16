"""T-118 の多変量の形の探索（src/stats/explore_models.py）のテスト。

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
SCRIPT = os.path.join(SRC, "explore_models.py")
sys.path.insert(0, SRC)

import explore_models as em  # noqa: E402

es = em.es
ei = em.ei
D = datetime.date


class TestOptions(unittest.TestCase):
    def test_counts(self):
        self.assertEqual(em.FIRST_VARIANT, "w12q_lift10")
        self.assertEqual(len(em.INTERACTIONS), 13)
        self.assertEqual(len(em.NAIVE_PAIRS), 15)
        self.assertEqual(len(em.feature_columns(2, "naive")), 7)
        self.assertEqual(len(em.feature_columns(2, "first")), 17)
        self.assertEqual(len(em.feature_columns(2, "naive_int")), 22)
        self.assertEqual(len(em.feature_columns(2, "int_first")), 30)
        self.assertEqual(len(em.feature_columns(2, "int_both")), 45)
        self.assertEqual(len(em.feature_columns(4, "all")), 7 + len(em.all_signal_columns()))
        names = [n for n, _k, _f, _r in em.MODELS]
        self.assertEqual(len(set(names)), len(names))
        for _n, _k, _f, ref in em.MODELS:
            self.assertTrue(ref is None or ref in names)

    def test_inner_dates(self):
        ms = ei.prediction_mondays()
        self.assertIn(em.INNER_TRAIN_LAST, ms)
        self.assertIn(em.INNER_VAL_FIRST, ms)
        self.assertLess(em.INNER_TRAIN_LAST + datetime.timedelta(days=28), em.INNER_VAL_FIRST + datetime.timedelta(days=1))
        self.assertLess(em.INNER_VAL_FIRST, es.TRAIN_LAST)

    def test_family(self):
        self.assertEqual(em.family_of("TAX_FNCACT_X"), "TAX_FNCACT")
        self.assertEqual(em.family_of("WB_1_X"), "WB")
        self.assertEqual(em.family_of("TAX_WORLDLANGUAGES_X"), "TAX_WORLDLANGUAGES")
        self.assertEqual(em.family_of("TAX_WORLDFISH_X"), "other")
        self.assertEqual(em.family_of("ECON_X"), "other")

    def test_no_email(self):
        for p in (SCRIPT, os.path.abspath(__file__)):
            with open(p, "rb") as f:
                self.assertIsNone(ei.EMAIL_RE.search(f.read()))


def synth(n=3000, k=5, seed=3):
    rng = random.Random(seed)
    X = [[1.0] + [rng.gauss(0, 1) for _ in range(k - 1)] for _ in range(n)]
    y = [1 if rng.random() < 1 / (1 + math.exp(-(0.8 * x[1] - 0.5 * x[2] - 1.5))) else 0 for x in X]
    return X, y


class TestLogistic(unittest.TestCase):
    def test_same_as_naive(self):
        X, y = synth()
        for lam in (1.0, 0.1, 100.0):
            a = em.naive.fit_logistic(X, y, lam)
            cols = [array.array("d", (row[j] for row in X)) for j in range(len(X[0]))]
            b = em.fit_logistic_cols(cols, y, lam)
            self.assertEqual(a["coef"], b["coef"])
            self.assertEqual(a["iterations"], b["iterations"])
            self.assertEqual(a["converged"], b["converged"])
            p = em.predict_cols(cols, b["coef"])
            self.assertEqual(p[:20], [em.naive.predict(a["coef"], r) for r in X[:20]])

    def test_choose_lambda(self):
        self.assertEqual(em.choose_lambda({0.1: (0.5, True), 1.0: (0.4, True), 10.0: (0.4, True)}), 10.0)
        self.assertEqual(em.choose_lambda({0.1: (0.3, False), 1.0: (0.4, True)}), 1.0)
        with self.assertRaises(em.ModelError):
            em.choose_lambda({1.0: (0.4, False)})


class TestGBDT(unittest.TestCase):
    def test_bins(self):
        e = em.bin_edges([float(i) for i in range(100)], 4)
        self.assertEqual(e, [25.0, 50.0, 75.0])
        self.assertEqual(em.to_bins([0.0, 25.0, 26.0, 99.0], e), bytes([0, 1, 1, 3]))
        self.assertEqual(em.bin_edges([1.0] * 10, 4), [1.0])

    def test_learns_and_is_deterministic(self):
        X, y = synth(n=2000)
        cfg = dict(em.GBDT, trees=20, min_leaf=50)
        cols = [[r[j] for r in X] for j in range(1, len(X[0]))]
        edges = [em.bin_edges(c, cfg["bins"]) for c in cols]
        bins = [em.to_bins(c, e) for c, e in zip(cols, edges)]
        nb = [len(e) + 1 for e in edges]
        m1 = em.fit_gbdt(bins, y, cfg, nb)
        m2 = em.fit_gbdt(bins, y, cfg, nb)
        self.assertEqual(m1, m2)
        p = em.predict_gbdt(m1, bins, len(y))
        base = sum(y) / len(y)
        ll = sum(es.log_loss_terms(p, y)) / len(y)
        ll0 = sum(es.log_loss_terms([base] * len(y), y)) / len(y)
        self.assertLess(ll, ll0)

    def test_min_leaf_stops_splits(self):
        X, y = synth(n=300)
        cfg = dict(em.GBDT, trees=2, min_leaf=200)
        cols = [[r[j] for r in X] for j in range(1, len(X[0]))]
        bins = [em.to_bins(c, em.bin_edges(c, 32)) for c in cols]
        f0, trees = em.fit_gbdt(bins, y, cfg, [33] * len(bins))
        self.assertTrue(all("v" in t for t in trees))


def tiny_table(seed=5, n_per_week=12):
    rng = random.Random(seed)
    ms = ei.prediction_mondays()
    cols = em.all_signal_columns()
    tb = {"t": [], "tag": [], "week": [], "family": [], "own_rise": []}
    for m in em.MULTIPLIERS:
        tb["y%d" % m] = []
        for k in range(len(em.naive.FEATURES)):
            tb["naive%d_%d" % (m, k)] = []
    for c in cols:
        tb[c] = []
    fams = ["TAX_FNCACT_A", "WB_1_B", "TAX_WORLDLANGUAGES_C", "ECON_D"]
    for wi, t in enumerate(ms):
        if not (wi % 3 == 0):
            continue
        for j in range(n_per_week):
            tag = "%s%02d" % (fams[j % 4], j)
            sig = rng.gauss(0, 1)
            tb["t"].append(t)
            tb["tag"].append(tag)
            tb["week"].append(wi)
            tb["family"].append(em.family_of(tag))
            tb["own_rise"].append(rng.gauss(0, 1))
            for m in em.MULTIPLIERS:
                tb["y%d" % m].append(1 if rng.random() < 1 / (1 + math.exp(-(sig - 1 - m / 4))) else 0)
                for k in range(len(em.naive.FEATURES)):
                    tb["naive%d_%d" % (m, k)].append(1.0 if k == 0 else rng.gauss(0, 1))
            for c in cols:
                tb[c].append(0.0 if "_miss" in c else sig + rng.gauss(0, 1))
    for c in list(cols) + ["own_rise"] + ["naive%d_%d" % (m, k) for m in em.MULTIPLIERS
                                         for k in range(len(em.naive.FEATURES))]:
        tb[c] = array.array("d", tb[c])
    for m in em.MULTIPLIERS:
        tb["y%d" % m] = array.array("b", tb["y%d" % m])
    tb["train"] = [r for r, t in enumerate(tb["t"]) if es.split_of(t) == "train"]
    tb["test"] = [r for r, t in enumerate(tb["t"]) if es.split_of(t) == "test"]
    tb["inner_train"] = [r for r in tb["train"] if tb["t"][r] <= em.INNER_TRAIN_LAST]
    tb["inner_val"] = [r for r in tb["train"] if tb["t"][r] >= em.INNER_VAL_FIRST]
    return tb


class TestInnerSplit(unittest.TestCase):
    def test_ok(self):
        tb = tiny_table()
        last, first = em.check_inner_split(tb)
        self.assertLessEqual(last, em.INNER_TRAIN_LAST)
        self.assertGreaterEqual(first, em.INNER_VAL_FIRST)

    def test_test_rows_in_inner_stop(self):
        tb = tiny_table()
        tb["inner_val"] = tb["inner_val"] + tb["test"][:1]
        with self.assertRaises(em.ModelError):
            em.check_inner_split(tb)

    def test_overlap_stops(self):
        tb = tiny_table()
        extra = [r for r in tb["train"] if em.INNER_TRAIN_LAST < tb["t"][r] < em.INNER_VAL_FIRST]
        tb["inner_train"] = tb["inner_train"] + extra + [r for r in tb["inner_val"]][:1]
        with self.assertRaises(em.ModelError):
            em.check_inner_split(tb)

    def test_inner_ignores_test_labels(self):
        """検証の期間の正解を変えても、学習の期間の中の対数損失（強さを選ぶ数字）は変わらない。"""
        tb = tiny_table()
        em._init_fit(tb)
        a = em._task(("inner", 2, "first", 10.0))[1]
        for r in tb["test"]:
            tb["y2"][r] = 1 - tb["y2"][r]
            for c in em.all_signal_columns():
                tb[c][r] = 99.0
        b = em._task(("inner", 2, "first", 10.0))[1]
        self.assertEqual(a, b)


class TestOutputs(unittest.TestCase):
    def test_build(self):
        tb = tiny_table()
        em._init_fit(tb)
        res = {}
        ridge_sets = sorted({fs for _n, kind, fs, _r in em.MODELS if kind == "ridge"})
        small_gbdt = dict(em.GBDT, trees=3, min_leaf=20)
        with mock.patch.object(em, "GBDT", small_gbdt):
            tasks = [("inner", m, fs, lam) for m in em.MULTIPLIERS for fs in ridge_sets for lam in em.RIDGE_LAMBDAS]
            tasks += [("logit", m, fs, em.FIXED_LAMBDA) for m in em.MULTIPLIERS for _n, k, fs, _r in em.MODELS
                      if k == "logit"]
            tasks += [("gbdt", m, fs) for m in em.MULTIPLIERS for _n, k, fs, _r in em.MODELS if k == "gbdt"]
            tasks += [("family", m, fs, fam) for m in em.MULTIPLIERS for _n, fs in em.FAMILY_FITS
                      for fam in em.FAMILIES]
            for a in tasks:
                k, out = em._task(a)
                res[k] = out
            chosen = {}
            for m in em.MULTIPLIERS:
                for fs in ridge_sets:
                    chosen[(m, fs)] = em.choose_lambda({lam: (res[("inner", m, fs, lam)]["logloss"],
                                                              res[("inner", m, fs, lam)]["converged"])
                                                        for lam in em.RIDGE_LAMBDAS})
                    key = ("logit", m, fs, chosen[(m, fs)])
                    if key not in res:
                        res[key] = em._task(key)[1]
            last, first = em.check_inner_split(tb)
            info = {"daily_min_read": "2015-03-09", "daily_max_read": "2020-10-12",
                    "network_last_day_minus_t_max_days": -1, "country_week_last_day_minus_t_max_days": -1,
                    "phase1_sha256": "0" * 64, "phase1_label": "x", "refs": {}, "v": "1/543539"}
            f1 = em.build_outputs(tb, info, res, chosen, last, first)
            f2 = em.build_outputs(tb, info, res, chosen, last, first)
        self.assertEqual(f1, f2)
        self.assertEqual(sorted(f1), sorted(em.OUT_NAMES))
        s = f1["summary.md"].decode("utf-8")
        for phrase in ("多重比較の補正をしていない", "独立でない", "一覧と V の先読み", "除外の規則の漏れ", "WB のテーマの段",
                       "報道した媒体の国ではない", ei.CITATION_JA, "検証の期間の行は、選ぶ計算に入っていない"):
            self.assertIn(phrase, s)
        run = json.loads(f1["run.json"])
        self.assertIn("src/stats/explore_models.py", run["code"])
        self.assertIn("src/stats/explore_signals.py", run["code"])
        self.assertEqual(run["comparisons_total"], 33)
        self.assertEqual(run["ranges_total"], 54)
        self.assertIn("検証の期間の再利用", s)
        self.assertIn("出した差の範囲は", s)
        for n, d in f1.items():
            self.assertIsNone(ei.EMAIL_RE.search(d), n)

    def test_base_notes(self):
        def row(name, d, lam=None):
            return {"name": name, "lam": lam, "mn": {"d_logloss": d, "d_ll_ci": (d - 1e-4, d + 1e-4)}}
        nv = {"logloss": 0.03}
        rows = [row("ridge_naive", 0.0003, 100.0), row("ridge_first", 0.0001, 10.0), row("ridge_all", -0.0001, 10.0),
                row("ridge_int_first", 0.0, 10.0), row("gbdt_naive", 0.0005), row("gbdt_first", 0.0006),
                row("gbdt_all", 0.0004)]
        notes = em.base_notes(rows, nv)
        self.assertEqual(len(notes), 2)
        self.assertIn("強さが違う（基準 100、比べるもの 10）", notes[0])
        self.assertIn("上限の目安と読めない", notes[1])
        rows[0]["mn"]["d_logloss"] = -0.0001
        rows[4]["mn"]["d_logloss"] = -0.0001
        self.assertEqual(em.base_notes(rows, nv), [])

    def test_write_refuses_existing(self):
        with mock.patch.object(em.os, "makedirs"), mock.patch.object(em.os.path, "lexists", return_value=True), \
                mock.patch.object(em.os, "open") as op:
            with self.assertRaises(em.ModelError):
                em.write_outputs("/nonexistent", {n: b"" for n in em.OUT_NAMES})
            op.assert_not_called()


if __name__ == "__main__":
    unittest.main()
