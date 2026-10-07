"""タグを入れる規則・素朴な予測・採点計画の一部のテスト（T-019〜T-022）。

除外の規則のテストは test_exclusion.py に分けた（T-022。除外の規則を K と別に封印するため）。

実行（プロジェクトのルートで）:
    PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest discover -s tests/stats -v

データもネットワークも使わない。データはすべてテストの中で作る合成の値。
"""

import ast
import datetime
import fractions
import json
import math
import os
import random
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(os.path.dirname(HERE))
SRC = os.path.join(PROJECT, "src", "stats")
DOC = os.path.join(PROJECT, "docs", "stats", "tags-naive.md")
sys.path.insert(0, SRC)

import candidates  # noqa: E402
import naive  # noqa: E402
import periods  # noqa: E402
import scoring  # noqa: E402
import exclusion  # noqa: E402

D = datetime.date
DAY = datetime.timedelta(days=1)
F = fractions.Fraction

METHOD_START, METHOD_END = D(2015, 3, 2), D(2020, 12, 14)
V1_BLOCKS = (
    ("method", D(2015, 3, 2), D(2020, 12, 14)),
    ("threshold", D(2020, 12, 15), D(2023, 11, 6)),
    ("baseline", D(2023, 11, 7), D(2026, 9, 30)),
)


def read_table(name):
    with open(DOC, encoding="utf-8") as f:
        lines = f.read().splitlines()
    i = lines.index("<!-- table:%s -->" % name)
    rows = []
    for line in lines[i + 1:]:
        if not line.startswith("|"):
            break
        rows.append([c.strip() for c in line.strip().strip("|").split("|")])
    return rows[0], rows[2:]


class Guarded:
    """first から last の外の日を読んだら失敗する比率の表。"""

    def __init__(self, tc, first, last, values=None, default=0.0):
        self.tc, self.first, self.last = tc, first, last
        self.values = values or {}
        self.default = default
        self.read = set()

    def __call__(self, d):
        self.tc.assertGreaterEqual(d, self.first, "読んではいけない古い日を読んだ")
        self.tc.assertLessEqual(d, self.last, "予言日 t 以降の日を読んだ")
        self.read.add(d)
        return self.values.get(d, self.default)


# ---------------------------------------------------------------------------
# 入れる規則のテストは test_tagrules.py に分けた（T-022 差し戻し1回目。順番1で封印するため）。
# ここでは、区画の日付が periods.py と一致することだけを確かめる。
# ---------------------------------------------------------------------------

class TestMethodBlockMatchesPeriods(unittest.TestCase):
    def test_matches_periods_block(self):
        ps = periods.rebuild_periods()
        self.assertEqual((ps[0]["block_start"], ps[0]["block_end"]), (METHOD_START, METHOD_END))



# ---------------------------------------------------------------------------
# 一度跳ねたタグと、対象なしの週
# ---------------------------------------------------------------------------

V = 0.5


class TestCooldown(unittest.TestCase):
    T = D(2018, 6, 4)

    def test_constants_from_candidates(self):
        self.assertEqual(scoring.JUMP_MULTIPLIER, min(candidates.THRESHOLD_MULTIPLIERS))
        self.assertEqual(scoring.COOLDOWN_DAYS, max(candidates.HORIZON_DAYS))
        self.assertEqual(scoring.cooldown_lookback_days(), 62)
        head, rows = read_table("scoring-constants")
        got = {r[0]: r[1] for r in rows}
        self.assertEqual(got, {"JUMP_MULTIPLIER": "2", "COOLDOWN_DAYS": "56"})

    def spike(self, end, level):
        return {end - k * DAY: level for k in range(7)}

    def test_reads_only_t62_to_t1(self):
        g = Guarded(self, self.T - 62 * DAY, self.T - DAY)
        self.assertFalse(scoring.recently_jumped(g, self.T, 1.0, V))
        self.assertEqual(min(g.read), self.T - 62 * DAY)
        self.assertEqual(max(g.read), self.T - DAY)

    def test_window_edges(self):
        # 終わりの日が t-56 の山は数え、t-57 の山は数えない。
        inside = Guarded(self, self.T - 62 * DAY, self.T - DAY, self.spike(self.T - 56 * DAY, 3.0))
        self.assertTrue(scoring.recently_jumped(inside, self.T, 1.0, V))
        # 最も古い日 t-62 は、終わりが t-56 のまとまりにだけ入る。その1日だけの値で境目を確かめる。
        g = Guarded(self, self.T - 62 * DAY, self.T - DAY, {self.T - 62 * DAY: 14.0})
        self.assertFalse(scoring.recently_jumped(g, self.T, 1.0, V))   # 14/7 = 2 は 2×1 を超えない
        g = Guarded(self, self.T - 62 * DAY, self.T - DAY, {self.T - 62 * DAY: 14.07})
        self.assertTrue(scoring.recently_jumped(g, self.T, 1.0, V))

    def test_limit_is_max_of_2b_and_v(self):
        g = lambda vals: Guarded(self, self.T - 62 * DAY, self.T - DAY, vals)  # noqa: E731
        s = self.spike(self.T - 10 * DAY, 2.0)
        self.assertFalse(scoring.recently_jumped(g(s), self.T, 1.0, V))   # 2.0 は 2×1.0 を超えない
        s = self.spike(self.T - 10 * DAY, 2.0001)
        self.assertTrue(scoring.recently_jumped(g(s), self.T, 1.0, V))
        s = self.spike(self.T - 10 * DAY, 0.4)
        self.assertFalse(scoring.recently_jumped(g(s), self.T, 0.0, V))   # B=0 でも V を超えなければ跳ねていない
        s = self.spike(self.T - 10 * DAY, 0.6)
        self.assertTrue(scoring.recently_jumped(g(s), self.T, 0.0, V))

    def test_missing_blocks_skipped(self):
        vals = self.spike(self.T - 10 * DAY, 5.0)
        vals[self.T - 12 * DAY] = None
        vals_all = dict(vals)
        g = Guarded(self, self.T - 62 * DAY, self.T - DAY, vals_all)
        # 欠けた日を含まない7日のまとまりで、山の一部を含むものはある（終わりが t-10 等）
        self.assertTrue(scoring.recently_jumped(g, self.T, 1.0, V))

    def test_target_status(self):
        lo = self.T - 371 * DAY
        base = {}
        d = lo
        while d < self.T:
            base[d] = 1.0
            d += DAY
        st = scoring.target_status(Guarded(self, lo, self.T - DAY, base), self.T, V)
        self.assertEqual(st, "target")
        jumped = dict(base)
        jumped.update(self.spike(self.T - 30 * DAY, 5.0))
        st = scoring.target_status(Guarded(self, lo, self.T - DAY, jumped), self.T, V)
        self.assertEqual(st, "cooldown")
        above = dict(base)
        above.update(self.spike(self.T - DAY, 1.5))
        self.assertEqual(scoring.target_status(Guarded(self, lo, self.T - DAY, above), self.T, V),
                         "above_baseline")
        nob = {d: None for d in base}
        self.assertEqual(scoring.target_status(Guarded(self, lo, self.T - DAY, nob), self.T, V), "no_baseline")
        noc = dict(base)
        for k in range(1, 14):
            noc[self.T - k * DAY] = None if k % 2 else 1.0
        self.assertEqual(scoring.target_status(Guarded(self, lo, self.T - DAY, noc), self.T, V), "no_current")

    def test_target_status_has_no_combination_argument(self):
        import inspect
        self.assertEqual(list(inspect.signature(scoring.target_status).parameters),
                         ["ratio_of_day", "t", "min_level"])

    def test_week_summary(self):
        s = scoring.week_summary({"a": "target", "b": "cooldown"})
        self.assertEqual(s["week_kind"], "has_targets")
        self.assertEqual(s["targets"], ["a"])
        self.assertEqual(scoring.week_summary({"a": "no_baseline", "b": "no_current"})["week_kind"],
                         "no_target_missing")
        self.assertEqual(scoring.week_summary({"a": "no_baseline", "b": "cooldown"})["week_kind"],
                         "no_target_quiet")
        with self.assertRaises(ValueError):
            scoring.week_summary({"a": "jumped"})
        with self.assertRaises(ValueError):
            scoring.week_summary({})


# ---------------------------------------------------------------------------
# 素朴な予測
# ---------------------------------------------------------------------------

class TestNaiveLookback(unittest.TestCase):
    def test_lookback_value(self):
        self.assertEqual(naive.naive_lookback_days(), 399)
        for h, last in ((14, 316), (28, 302), (56, 274)):
            self.assertEqual(naive.naive_lookback_days(h), 399)
            self.assertEqual(naive.latest_season_day_offset(h), last)

    def test_lookback_within_periods(self):
        tr = naive.periods_trigger()
        self.assertLessEqual(tr["naive_history_days"], periods.LOOKBACK_DAYS)
        self.assertFalse(tr["rebuild_needed"])
        self.assertEqual(tr["lookback_after"], periods.LOOKBACK_DAYS)

    def test_rebuild_with_trigger_is_v1(self):
        ps = periods.rebuild_periods(naive_history_days=naive.naive_lookback_days(),
                                     last_read_offset_days=candidates.max_last_read_offset_days())
        v1 = periods.rebuild_periods()
        self.assertEqual(tuple((p["name"], p["block_start"], p["block_end"]) for p in ps), V1_BLOCKS)
        for a, b in zip(ps, v1):
            self.assertEqual(a["prediction_first"], b["prediction_first"])
            self.assertEqual(a["prediction_last"], b["prediction_last"])

    def test_first_method_prediction_reads_inside_block(self):
        v1 = periods.rebuild_periods()
        t = v1[0]["prediction_first"]
        self.assertGreaterEqual(t - naive.naive_lookback_days() * DAY, METHOD_START)

    def test_doc_lookback_table(self):
        head, rows = read_table("lookback")
        got = {r[0]: (r[1], r[2]) for r in rows}
        self.assertEqual(got["素朴な予測の全体"], ("t-399 から t-1", str(naive.naive_lookback_days())))
        for h in candidates.HORIZON_DAYS:
            row = got["去年の同じ時期（H = %d）" % h]
            self.assertEqual(row, ("t-399 から t-%d" % naive.latest_season_day_offset(h), "399"))
        self.assertEqual(got["冷却（4章 (1)）"], ("t-62 から t-1", "62"))
        self.assertEqual(got["普段の水準 B(t)"], ("t-371 から t-1", "371"))

    def test_doc_constants(self):
        head, rows = read_table("naive-constants")
        got = {r[0]: r[1] for r in rows}
        self.assertEqual(got, {
            "SEASON_SHIFT_DAYS": str(naive.SEASON_SHIFT_DAYS),
            "SEASON_MARGIN_DAYS": str(naive.SEASON_MARGIN_DAYS),
            "RECENT_PEAK_DAYS": str(naive.RECENT_PEAK_DAYS),
            "RIDGE_LAMBDA": repr(naive.RIDGE_LAMBDA),
            "MAX_ITER": str(naive.MAX_ITER),
            "TOL": repr(naive.TOL),
        })
        head, rows = read_table("naive-features")
        self.assertEqual([r[0] for r in rows], list(naive.FEATURES))


class TestNaiveReadsOnlyPast(unittest.TestCase):
    T = D(2019, 9, 2)

    def series(self, seed):
        rng = random.Random(seed)
        vals = {}
        d = self.T - 500 * DAY
        while d <= self.T + 100 * DAY:
            vals[d] = rng.random()
            d += DAY
        return vals

    def test_reads_only_t399_to_t1(self):
        vals = self.series(1)
        for h in candidates.HORIZON_DAYS:
            g = Guarded(self, self.T - 399 * DAY, self.T - DAY, vals)
            naive.raw_levels(g, self.T, h)
            self.assertEqual(max(g.read), self.T - DAY)
            self.assertEqual(min(g.read), self.T - 399 * DAY)

    def test_future_values_do_not_change_features(self):
        vals = self.series(2)
        changed = dict(vals)
        d = self.T
        while d <= self.T + 100 * DAY:
            changed[d] = 1000.0
            d += DAY
        for h in candidates.HORIZON_DAYS:
            for m in candidates.THRESHOLD_MULTIPLIERS:
                a = naive.features(lambda x: vals[x], self.T, h, m, V)
                b = naive.features(lambda x: changed[x], self.T, h, m, V)
                self.assertEqual(a, b)

    def test_reading_future_raises(self):
        # 見張りがあることの確認：見張りの範囲を t-1 までにすると読んだ日はすべてその中。
        g = Guarded(self, self.T - 399 * DAY, self.T - DAY, self.series(3))
        naive.features(g, self.T, 56, 2, V)
        self.assertTrue(all(x < self.T for x in g.read))

    def test_season_windows(self):
        (a0, b0), (a1, b1) = naive.season_windows(self.T, 28)
        self.assertEqual(a0, self.T + DAY - 365 * DAY)
        self.assertEqual(b0, self.T + 28 * DAY - 365 * DAY)
        self.assertEqual((a1, b1), (a0 - 35 * DAY, b0 + 35 * DAY))


class TestNaiveFeatures(unittest.TestCase):
    def test_zero_baseline_and_level(self):
        x = naive.features_from_levels({"B": 0.0, "c": 0.0, "P": None, "S0": None, "S35": 0.0}, 2, V)
        self.assertEqual(x[0], 1.0)
        self.assertAlmostEqual(x[1], math.log(0.5))  # g(0) = log(V / (V + V))
        self.assertEqual(x[2], x[1])                 # P が無ければ c
        self.assertEqual(x[3], x[4])                 # S0 が無ければ S35
        self.assertEqual(x[5], 0.0)
        self.assertEqual(x[6], 0.0)

    def test_no_season(self):
        x = naive.features_from_levels({"B": 1.0, "c": 0.5, "P": 0.9, "S0": None, "S35": None}, 4, V)
        self.assertEqual(x[3:6], [0.0, 0.0, 1.0])

    def test_season_above_limit_is_positive(self):
        x = naive.features_from_levels({"B": 1.0, "c": 0.5, "P": 0.9, "S0": 5.0, "S35": 6.0}, 3, V)
        self.assertGreater(x[3], 0)
        self.assertGreater(x[4], x[3])

    def test_requires_b_and_c(self):
        with self.assertRaises(ValueError):
            naive.features_from_levels({"B": None, "c": 0.1, "P": None, "S0": None, "S35": None}, 2, V)
        with self.assertRaises(ValueError):
            naive.features_from_levels({"B": 1.0, "c": 0.1, "P": None, "S0": None, "S35": None}, 2, 0.0)


class TestLogistic(unittest.TestCase):
    def data(self, seed, n=3000):
        rng = random.Random(seed)
        true = [-1.0, 1.5, -0.7]
        X, y = [], []
        for _ in range(n):
            x = [1.0, rng.gauss(0, 1), rng.gauss(0, 1)]
            p = 1 / (1 + math.exp(-sum(a * b for a, b in zip(true, x))))
            X.append(x)
            y.append(1 if rng.random() < p else 0)
        return X, y, true

    def test_recovers_coefficients(self):
        X, y, true = self.data(11)
        r = naive.fit_logistic(X, y)
        self.assertTrue(r["converged"])
        for a, b in zip(r["coef"], true):
            self.assertAlmostEqual(a, b, delta=0.2)

    def test_deterministic(self):
        X, y, _ = self.data(12, 500)
        self.assertEqual(naive.fit_logistic(X, y), naive.fit_logistic(X, y))

    def test_row_order_fixed(self):
        X, y, _ = self.data(13, 400)
        rows = [(D(2017, 1, 2) + 7 * DAY * (i % 20), "TAG%03d" % (i // 20), X[i], y[i]) for i in range(400)]
        shuffled = list(rows)
        random.Random(5).shuffle(shuffled)
        a = naive.fit_rows(rows)
        b = naive.fit_rows(shuffled)
        self.assertEqual(a, b)  # 浮動小数点まで同じ
        ordered = naive.sort_rows(shuffled)
        self.assertEqual([(r[0], r[1]) for r in ordered], sorted((r[0], r[1]) for r in rows))
        self.assertEqual(a, naive.fit_logistic([r[2] for r in ordered], [r[3] for r in ordered]))
        with self.assertRaises(ValueError):
            naive.sort_rows(rows + [rows[0]])

    def test_fixed_constants(self):
        self.assertEqual((naive.RIDGE_LAMBDA, naive.MAX_ITER, naive.TOL), (1.0, 100, 1e-10))
        rec = json.loads(naive.canonical_json())
        self.assertIn("ridge_lambda, max_iter, tol", rec["revision_rule"])
        self.assertIn("(prediction date, tag name)", rec["row_order"])

    def test_separation_converges_with_ridge(self):
        X = [[1.0, float(i)] for i in range(-10, 11)]
        y = [1 if i > 0 else 0 for i in range(-10, 11)]
        r = naive.fit_logistic(X, y)
        self.assertTrue(r["converged"])
        self.assertTrue(all(math.isfinite(c) for c in r["coef"]))

    def test_no_positive(self):
        # 島が一つも無い組み合わせでも、切片にもリッジを掛けるので収まる。
        X = [[1.0, float(i % 5)] for i in range(2000)]
        r = naive.fit_logistic(X, [0] * 2000)
        self.assertTrue(r["converged"])
        self.assertLess(naive.predict(r["coef"], X[0]), 0.01)

    def test_bad_inputs(self):
        with self.assertRaises(ValueError):
            naive.fit_logistic([], [])
        with self.assertRaises(ValueError):
            naive.fit_logistic([[1.0, 2.0]], [2])
        with self.assertRaises(ValueError):
            naive.predict([1.0], [1.0, 2.0])


# ---------------------------------------------------------------------------
# 出力・データとネットワークを使わないこと
# ---------------------------------------------------------------------------

MODULES = ("naive", "scoring")  # tagrules は test_tagrules.py で確かめる


class TestOutput(unittest.TestCase):
    def run_cli(self, mod, *args):
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
        return subprocess.run([sys.executable, "-B", os.path.join(SRC, mod + ".py"), *args],
                              capture_output=True, text=True, env=env, cwd=PROJECT)

    def test_cli_deterministic(self):
        for mod in MODULES:
            a, b = self.run_cli(mod), self.run_cli(mod)
            self.assertEqual(a.returncode, 0, a.stderr)
            self.assertEqual(a.stdout, b.stdout)
            self.assertEqual(a.stdout, sys.modules[mod].canonical_json())
            json.loads(a.stdout)

    def test_cli_rejects_args(self):
        for mod in MODULES:
            self.assertEqual(self.run_cli(mod, "--x").returncode, 2)

    def test_naive_output_has_trigger(self):
        rec = json.loads(naive.canonical_json())
        self.assertEqual(rec["periods_trigger"]["naive_history_days"], 399)
        self.assertFalse(rec["periods_trigger"]["rebuild_needed"])

    def test_scoring_output_has_revision_rule(self):
        rec = json.loads(scoring.canonical_json())
        self.assertIn("before the first threshold-access", rec["revision"])


def _sha256(data):
    import hashlib
    return hashlib.sha256(data).hexdigest()


def _git_show(spec):
    r = subprocess.run(["git", "show", spec], capture_output=True, cwd=PROJECT)
    if r.returncode != 0:
        raise unittest.SkipTest("git の履歴が使えない")
    return r.stdout


def _run_script_bytes(code_bytes):
    import tempfile
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "tagrules.py")
        with open(path, "wb") as f:
            f.write(code_bytes)
        r = subprocess.run([sys.executable, "-B", path], capture_output=True, env=env, cwd=d)
    if r.returncode != 0:
        raise AssertionError(r.stderr.decode())
    return r.stdout


HANDOFF = os.path.join(PROJECT, "docs", "stats", "seal-order1.md")


def read_handoff_table(name):
    with open(HANDOFF, encoding="utf-8") as f:
        lines = f.read().splitlines()
    i = lines.index("<!-- table:%s -->" % name)
    rows = []
    for line in lines[i + 1:]:
        if not line.startswith("|"):
            break
        rows.append([c.strip() for c in line.strip().strip("|").split("|")])
    return rows[0], rows[2:]


def _run_cli_bytes(rel):
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    r = subprocess.run([sys.executable, "-B", os.path.join(PROJECT, rel)], capture_output=True, env=env,
                       cwd=PROJECT)
    if r.returncode != 0:
        raise AssertionError(r.stderr.decode())
    return r.stdout


def seal_target_bytes():
    """順番1の封印の対象（docs/stats/seal-order1.md の表 seal-targets）のバイト列。"""
    def read(rel):
        with open(os.path.join(PROJECT, rel), "rb") as f:
            return f.read()
    old = _git_show("1cb463a:src/stats/tagrules.py")
    return {
        "src/stats/exclusion.py": read("src/stats/exclusion.py"),
        "src/stats/exclusion.py の出力": _run_cli_bytes("src/stats/exclusion.py"),
        "tests/stats/test_exclusion.py": read("tests/stats/test_exclusion.py"),
        "src/stats/tagrules.py": read("src/stats/tagrules.py"),
        "src/stats/tagrules.py の出力": _run_cli_bytes("src/stats/tagrules.py"),
        "tests/stats/test_tagrules.py": read("tests/stats/test_tagrules.py"),
        "docs/stats/tags-naive.md": read("docs/stats/tags-naive.md"),
        "1cb463a:src/stats/tagrules.py": old,
        "1cb463a:src/stats/tagrules.py の出力": _run_script_bytes(old),
        "2d23cdf:reviews/T-020.md": _git_show("2d23cdf:reviews/T-020.md"),
    }


class TestSealTargets(unittest.TestCase):
    def test_seal_targets(self):
        head, rows = read_handoff_table("seal-targets")
        self.assertEqual(head, ["対象", "sha256"])
        got = {r[0].strip("`"): r[1].strip("`") for r in rows}
        want = {k: _sha256(v) for k, v in seal_target_bytes().items()}
        self.assertEqual(got, want)

    def test_seal_targets_read_only_seal_targets(self):
        # M-2：順番1で封印するテストは、封印しないファイル（作業中の reviews/、申し送りの文書、
        # naive.py・scoring.py・periods.py・candidates.py）を読まない。
        b = seal_target_bytes()
        for k in ("tests/stats/test_exclusion.py", "tests/stats/test_tagrules.py"):
            for word in (b'"reviews"', b"seal-order1", b"import naive", b"import scoring",
                         b"import periods", b"import candidates"):
                self.assertNotIn(word, b[k], (k, word))
            self.assertNotIn(b'os.path.join(PROJECT, path)', b[k], k)
        self.assertIn(b'_git_show(spec)', b["tests/stats/test_exclusion.py"])

    def test_inclusion_rule_in_order1(self):
        # M-1：K と入れる規則の定数と式は、順番1の対象（tagrules.py とその出力）に入っている。
        b = seal_target_bytes()
        self.assertIn(b"K_ARTICLES_PER_DAY = 10", b["src/stats/tagrules.py"])
        self.assertIn(b"MIN_COUNT_PER_QUARTER = 1", b["src/stats/tagrules.py"])
        rec = json.loads(b["src/stats/tagrules.py の出力"])
        self.assertEqual(rec["inclusion"]["k_articles_per_day"], 10)
        self.assertEqual(rec["inclusion"]["min_count_per_quarter"], 1)
        self.assertIn("A = K / N_med", rec["inclusion"]["a_rule"])
        # 除外の規則の出力には K が入らない（分けたファイルのまま）。
        self.assertNotIn(b"k_articles_per_day", b["src/stats/exclusion.py の出力"])

    def test_old_version_output_is_the_first_submission(self):
        # 1cb463a の出力は、初回の提出で報告した sha256（98926edb…）と同じ。
        b = seal_target_bytes()
        self.assertTrue(_sha256(b["1cb463a:src/stats/tagrules.py の出力"]).startswith("98926edb"))

    def test_exclusion_output_decided(self):
        rec = json.loads(seal_target_bytes()["src/stats/exclusion.py の出力"])
        self.assertEqual(rec["optional_choice_status"], "decided")
        self.assertEqual(rec["enabled_optional_categories"], ["ethnic_religious_group"])
        self.assertTrue(rec["owner_choice_source"].startswith("2d23cdf:reviews/T-020.md "))


class TestNoDataNoNetwork(unittest.TestCase):
    ALLOWED = {
        "naive": {"datetime", "json", "math", "sys", "candidates", "periods", "scoring"},
        "scoring": {"datetime", "json", "sys", "candidates"},
    }

    def test_imports_clock_files(self):
        for mod in MODULES:
            with open(os.path.join(SRC, mod + ".py"), encoding="utf-8") as f:
                tree = ast.parse(f.read())
            names = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    names.update(a.name.split(".")[0] for a in node.names)
                elif isinstance(node, ast.ImportFrom):
                    names.add((node.module or "").split(".")[0])
                if isinstance(node, ast.Attribute):
                    self.assertNotIn(node.attr, {"today", "now", "utcnow", "time"}, mod)
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                    self.assertNotEqual(node.func.id, "open", mod)
            self.assertEqual(names - self.ALLOWED[mod], set(), mod)


if __name__ == "__main__":
    unittest.main()
