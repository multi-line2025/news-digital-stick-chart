"""素朴な予測・採点計画の一部と、順番1の封印の対象のテスト（T-019〜T-022）。

除外の規則のテストは test_exclusion.py に、入れる規則のテストは test_tagrules.py に分けた（T-022）。
この二つは順番1で封印する。このファイルは封印しない（naive.py・scoring.py の改訂や、封印の対象の
sha256 の表 docs/stats/seal-order1.md と一緒に直すため）。

実行（プロジェクトのルートで。使う Python は .venv/bin/python に決める。T-024）:
    PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -B -m unittest discover -s tests/stats -v

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
# 素朴な予測と採点計画の表は、凍結する tags-naive.md から naive-scoring.md に移した（T-022 差し戻し3回目）。
DOC = os.path.join(PROJECT, "docs", "stats", "naive-scoring.md")
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
    def test_digest_script_agrees(self):
        # src/stats/order1_digests.py が、このテストの中の別の実装と同じ値を出すこと。CLI の出力も同じ。
        # order1_digests.py は封印の対象の外なので、封印係の照合（seal-order1.md 2章の項目6、3章 (1) の
        # 手順3）の根拠にはしない。封印係は自分のコードで計算し、このスクリプトの値は比べる参考に限る（T-025 L1）。
        import order1_digests
        want = {k: _sha256(v) for k, v in seal_target_bytes().items()}
        self.assertEqual(order1_digests.digests(PROJECT), want)
        r = subprocess.run([sys.executable, "-B", os.path.join(SRC, "order1_digests.py")], capture_output=True,
                           text=True, env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"), cwd=PROJECT)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout), want)
        r2 = subprocess.run([sys.executable, "-B", os.path.join(SRC, "order1_digests.py"), "--x"],
                            capture_output=True, cwd=PROJECT)
        self.assertEqual(r2.returncode, 2)

    def test_frozen_doc_hash_in_sealed_test(self):
        # M-3：封印するテスト test_tagrules.py の中の定数が、今の tags-naive.md の sha256 と同じ。
        # test_tagrules.py は import せず、封印の対象のバイト列から定数を読む（どの起動のしかたでも同じに動くため）。
        b = seal_target_bytes()
        tree = ast.parse(b["tests/stats/test_tagrules.py"].decode("utf-8"))
        values = [n.value.value for n in tree.body if isinstance(n, ast.Assign)
                  and [t.id for t in n.targets if isinstance(t, ast.Name)] == ["TAGS_NAIVE_SHA256"]]
        self.assertEqual(values, [_sha256(b["docs/stats/tags-naive.md"])])

    def test_seal_targets(self):
        head, rows = read_handoff_table("seal-targets")
        self.assertEqual(head, ["対象", "sha256"])
        got = {r[0].strip("`"): r[1].strip("`") for r in rows}
        want = {k: _sha256(v) for k, v in seal_target_bytes().items()}
        self.assertEqual(got, want)

    def test_inclusion_rule_in_order1(self):
        # M-1：K と入れる規則の定数と式は、順番1の対象（tagrules.py とその出力）に入っている。
        b = seal_target_bytes()
        self.assertIn(b"K_ARTICLES_PER_DAY = 10", b["src/stats/tagrules.py"])
        self.assertIn(b"MIN_COUNT_PER_QUARTER = 1", b["src/stats/tagrules.py"])
        rec = json.loads(b["src/stats/tagrules.py の出力"])
        self.assertEqual(rec["inclusion"]["k_articles_per_day"], 10)
        self.assertEqual(rec["inclusion"]["min_count_per_quarter"], 1)
        self.assertIn("A = K / N_med", rec["inclusion"]["a_rule"])
        # 除外の規則のコードと出力には、K の定数も K の値の欄も無い（分けたファイルのまま）。
        for k in ("src/stats/exclusion.py", "src/stats/exclusion.py の出力"):
            self.assertNotIn(b"K_ARTICLES_PER_DAY", b[k], k)
            self.assertNotIn(b"k_articles_per_day", b[k], k)
        # 除外の規則のテストは K の定数を使わず、tagrules を読み込まない（出力に K の欄が無いことを
        # 確かめるために、欄の名前だけを書いている）。
        self.assertNotIn(b"K_ARTICLES_PER_DAY", b["tests/stats/test_exclusion.py"])
        self.assertNotIn(b"import tagrules", b["tests/stats/test_exclusion.py"])

    def test_old_version_output_is_the_first_submission(self):
        # 1cb463a の出力は、初回の提出で報告した sha256（98926edb…）と同じ。
        b = seal_target_bytes()
        self.assertTrue(_sha256(b["1cb463a:src/stats/tagrules.py の出力"]).startswith("98926edb"))

    def test_exclusion_output_decided(self):
        rec = json.loads(seal_target_bytes()["src/stats/exclusion.py の出力"])
        self.assertEqual(rec["optional_choice_status"], "decided")
        self.assertEqual(rec["enabled_optional_categories"], ["ethnic_religious_group"])
        self.assertTrue(rec["owner_choice_source"].startswith("2d23cdf:reviews/T-020.md "))


# ---------------------------------------------------------------------------
# 順番1で封印するテストが、封印の対象の外を読まないこと（T-022 差し戻し2回目・3回目 M-1）
#
# 二つの確かめ方を組み合わせる。
#   (a) 実行の見張り：二つのテストを子プロセスで流し、Python の audit hook で、開いたファイル・
#       フォルダの一覧・プロセスの起動（subprocess.Popen と _posixsubprocess.fork_exec）・リンクの作成・
#       ctypes・通信などの事象を集め、許可リストと照らす（audit_sealed_tests）。
#   (b) ソースの検査：二つのテストのソースを ast で調べ、使ってよいモジュールと os・subprocess・sys の
#       使い方を許可リストに限る（sealed_test_source_problems）。audit hook で見えない読み方
#       （os.stat、os.path.exists など）と os.environ をそのまま読む書き方は、名前 os・sys から書いた
#       ものに限って、ここで止まる。許可したほかのモジュールの属性を通る os・sys の使い方
#       （unittest.loader.os.stat など）、許可した形で読んだ環境変数による分岐、日付による分岐は、
#       (a) でも (b) でも止まらない（T-025 L2）。
# 限界は docs/stats/tags-naive.md 5章 (1) の後の「限界」に書いた。今の二つの封印するテストに限界に
# 当たる書き方が無いことは、test_sealed_tests_have_no_limit_patterns で確かめる。補う手順は、対象だけを
# 置いた写しで見張りなしに流すこと（seal-order1.md 2章の項目10、test_sealed_tests_pass_in_targets_only_copy）。
# ---------------------------------------------------------------------------

# 子プロセス（と、その子の Python）に audit hook を入れる sitecustomize。
# フックの中では import をしない（import 自身が open の事象を起こすため）。
_SITECUSTOMIZE = """
import os, sys, json
_log = os.environ.get("STATS_AUDIT_LOG")
if _log:
    _fd = os.open(_log, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    _dumps = json.dumps
    _getcwd = os.getcwd
    _fspath = os.fspath
    _environ = os.environ
    _realpath = os.path.realpath
    _OTHER = ("os.system", "os.exec", "os.posix_spawn", "os.spawn", "os.fork", "os.forkpty", "pty.spawn",
              "os.link", "os.symlink", "os.rename", "os.remove", "os.rmdir", "os.truncate", "os.chdir",
              "os.mkdir", "os.chmod", "os.putenv", "os.unsetenv", "socket.connect", "socket.getaddrinfo",
              "socket.bind", "socket.__new__", "urllib.Request", "http.client.connect",
              "ctypes.dlopen", "ctypes.dlsym", "ctypes.call_function", "ctypes.cdata",
              "ctypes.addressof", "ctypes.string_at", "ctypes.wstring_at", "ctypes.create_string_buffer",
              "mmap.__new__", "shutil.copyfile", "shutil.copytree", "shutil.move", "shutil.rmtree",
              "tempfile.mkstemp", "tempfile.mkdtemp", "glob.glob", "os.walk", "pathlib.Path.glob")

    def _s(x):
        if isinstance(x, bytes):
            return x.decode("utf-8", "replace")
        if isinstance(x, (str, int)) or x is None:
            return x
        try:
            return _fspath(x)
        except TypeError:
            return repr(x)

    def _envdiff(env):
        if env is None:
            return []
        if not isinstance(env, dict):
            env = dict(_s(e).split("=", 1) for e in env)
        env = {_s(k): _s(v) for k, v in env.items()}
        keys = set(env) | set(_environ)
        return sorted([k, env.get(k)] for k in keys if env.get(k) != _environ.get(k))

    def _hook(event, args):
        try:
            if event == "open":
                path = args[0]
                rec = ["open", _s(path), _s(args[1]) if len(args) > 1 else None,
                       args[2] if len(args) > 2 and isinstance(args[2], int) else None,
                       None if isinstance(path, int) else _realpath(_fspath(path) if not isinstance(path, bytes)
                                                                   else path.decode("utf-8", "replace"))]
            elif event in ("os.listdir", "os.scandir"):
                path = args[0] if args and args[0] is not None else "."
                rec = ["dir", None if isinstance(path, int) else _realpath(_s(path))]
            elif event == "subprocess.Popen":
                argv = args[1]
                if isinstance(argv, (str, bytes)) or not hasattr(argv, "__iter__"):
                    argv = [argv]
                cwd = _realpath(_s(args[2])) if args[2] is not None else _getcwd()
                rec = ["proc", [_s(a) for a in argv], cwd, _envdiff(args[3])]
            elif event == "_posixsubprocess.fork_exec":
                argv = args[1]
                if isinstance(argv, (str, bytes)) or not hasattr(argv, "__iter__"):
                    argv = [argv]
                rec = ["fork", [_s(a) for a in argv], _envdiff(args[2])]
            elif event in _OTHER:
                rec = ["other", event, repr(args)[:500]]
            else:
                return
            os.write(_fd, (_dumps(rec) + "\\n").encode("utf-8"))
        except Exception as e:
            os.write(_fd, (_dumps(["hook-error", event, repr(e)]) + "\\n").encode("utf-8"))

    sys.addaudithook(_hook)
"""

SEALED_TEST_FILES = ("tests/stats/test_exclusion.py", "tests/stats/test_tagrules.py")

# 許可リスト。ファイルは順番1の封印の対象（作業ツリーにあるもの）だけ。読むだけで、書かない。
ALLOWED_OPENS = frozenset({
    "src/stats/exclusion.py", "src/stats/tagrules.py", "docs/stats/tags-naive.md",
    "tests/stats/test_exclusion.py", "tests/stats/test_tagrules.py",
})
# フォルダの一覧は、import の仕組みが sys.path のフォルダを読むものだけ。
ALLOWED_DIRS = frozenset({".", "tests", "tests/stats", "src/stats", "<WATCH>"})  # <WATCH> は sitecustomize を探すため
# プロセスは、封印の対象の二つのコードを動かすもの（拒むことを確かめる --x を含む）と、決まった
# git show だけ。どれもプロジェクトのルートで、環境変数を変えずに（テストが渡す
# PYTHONDONTWRITEBYTECODE=1 は、見張りの側で既に 1 なので差にならない）起動する。
ALLOWED_PROCS = frozenset({
    ("PYTHON", "-B", "src/stats/exclusion.py"), ("PYTHON", "-B", "src/stats/exclusion.py", "--x"),
    ("PYTHON", "-B", "src/stats/tagrules.py"), ("PYTHON", "-B", "src/stats/tagrules.py", "--x"),
    ("git", "show", "2d23cdf:reviews/T-020.md"),
})
_WRITE_FLAGS = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_APPEND | os.O_TRUNC


def _under(path, roots):
    return any(path == r or path.startswith(r + os.sep) for r in roots)


def audit_sealed_tests(project, test_files=SEALED_TEST_FILES):
    """test_files を子プロセスの unittest で流し、事象を集める。

    戻り値は dict：
      opens:  開いたファイルの (パス, 書き込みか) の集合。プロジェクトの中は相対パス、外は絶対パス。
              Python の本体と標準ライブラリ（sys.prefix などの下）と、見張りの sitecustomize.py と
              pyc の置き場だけを数えない。一時のフォルダのほかのファイル（ログを含む）は数える。
              パスは、事象が起きた時点で realpath にしたもの（リンクは指す先になる）。
      dirs:   一覧を読んだフォルダ。プロジェクトの中と見張りの一時のフォルダの中だけを数える（T-024 M-a）。
              プロジェクトの外のフォルダ（ユーザーや Homebrew の site-packages など。どの Python で
              流すかで変わる）は数えない。realpath で比べるので、外からプロジェクトの中を指すリンクは中に数える。
      procs:  subprocess.Popen の (引数, cwd, 環境変数の差) の組。Python の実行ファイルは "PYTHON"、
              プロジェクトの中のパスは相対パス。
      forks:  _posixsubprocess.fork_exec の引数の組の数（Popen を通らない起動を見つけるため）。
      others: ほかの事象（リンクの作成、ctypes、通信、プロセスを起こすほかの道など）。
      rc:     unittest の終了コード。
    """
    import collections
    import tempfile
    project = os.path.realpath(project)
    with tempfile.TemporaryDirectory() as tmp:
        tmp = os.path.realpath(tmp)
        with open(os.path.join(tmp, "sitecustomize.py"), "w", encoding="utf-8") as f:
            f.write(_SITECUSTOMIZE)
        log = os.path.join(tmp, "audit.log")
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTHONPATH=tmp, STATS_AUDIT_LOG=log,
                   PYTHONPYCACHEPREFIX=os.path.join(tmp, "pyc"))
        r = subprocess.run([sys.executable, "-B", "-m", "unittest", *test_files],
                           capture_output=True, env=env, cwd=project)
        with open(log, encoding="utf-8") as f:
            lines = [json.loads(x) for x in f]
        # 一時のフォルダを消す前に、パスの比べ方を決める（消したあとでは realpath が変わりうるため）。
        ignore_roots = [os.path.realpath(p) for p in (sys.prefix, sys.base_prefix, sys.exec_prefix,
                                                      sys.base_exec_prefix)]
        ignore_files = {os.path.join(tmp, "sitecustomize.py")}
        pyc_root = os.path.join(tmp, "pyc")
        exe = {sys.executable, os.path.realpath(sys.executable)}
        environ = dict(env)

        def rel(full):
            if _under(full, [tmp]):
                return "<WATCH>" + full[len(tmp):]   # 見張りの一時のフォルダ（ログを含む）
            return os.path.relpath(full, project) if _under(full, [project]) else full

        out = {"opens": set(), "dirs": set(), "procs": set(), "forks": collections.Counter(),
               "others": [], "rc": r.returncode}
        popen_argv = collections.Counter()
        for rec in lines:
            kind = rec[0]
            if kind == "open":
                path, mode, flags, full = rec[1:]
                if full is None:
                    continue  # 既に開いたファイル記述子（os.fdopen など）。新しいファイルではない。
                write = (isinstance(mode, str) and any(c in mode for c in "wax+")) or \
                        (isinstance(flags, int) and bool(flags & _WRITE_FLAGS))
                if not write and (_under(full, ignore_roots) or full in ignore_files
                                  or _under(full, [pyc_root])):
                    continue
                out["opens"].add((rel(full), write))
            elif kind == "dir":
                full = rec[1]
                if full is None or not _under(full, [project, tmp]) or _under(full, ignore_roots) \
                        or _under(full, [pyc_root]):
                    continue
                out["dirs"].add(rel(full))
            elif kind == "proc":
                argv, cwd, envdiff = rec[1], rec[2], rec[3]
                norm = []
                for k, a in enumerate(argv):
                    if k == 0 and (a in exe or os.path.realpath(a) in exe):
                        norm.append("PYTHON")
                    elif isinstance(a, str) and os.path.isabs(a) and _under(os.path.realpath(a), [project]):
                        norm.append(rel(os.path.realpath(a)))
                    else:
                        norm.append(a)
                out["procs"].add((tuple(norm), rel(os.path.realpath(cwd)),
                                  tuple(tuple(x) for x in envdiff)))
                popen_argv[tuple(argv)] += 1
            elif kind == "fork":
                out["forks"][tuple(rec[1])] += 1
            else:
                out["others"].append(rec)
        # fork_exec は、Popen を通った起動ごとにちょうど一つ。Popen を通らない起動があれば数が合わない。
        out["unpaired_forks"] = sorted((out["forks"] - popen_argv).elements())
        out["unpaired_popens"] = sorted((popen_argv - out["forks"]).elements())
        del environ
    return out


def allowed_procs_with_context():
    return {(p, ".", ()) for p in ALLOWED_PROCS}


def audit_problems(out):
    """audit_sealed_tests() の結果のうち、許可リストと違う点の一覧（空なら問題なし）。"""
    problems = []
    if out["rc"] != 0:
        problems.append("封印するテストが通らない（rc=%s）" % out["rc"])
    if out["others"]:
        problems.append("許可しない事象：%r" % out["others"][:5])
    writes = sorted(p for p, w in out["opens"] if w)
    if writes:
        problems.append("書き込み：%r" % writes)
    opens = {p for p, w in out["opens"]}
    if opens != set(ALLOWED_OPENS):
        problems.append("開いたファイルが違う：多い %r、少ない %r"
                        % (sorted(opens - ALLOWED_OPENS), sorted(ALLOWED_OPENS - opens)))
    if not out["dirs"] <= ALLOWED_DIRS:
        problems.append("一覧を読んだフォルダ：%r" % sorted(out["dirs"] - ALLOWED_DIRS))
    if out["procs"] != allowed_procs_with_context():
        problems.append("起動したプロセスが違う：多い %r、少ない %r"
                        % (sorted(out["procs"] - allowed_procs_with_context()),
                           sorted(allowed_procs_with_context() - out["procs"])))
    if out["unpaired_forks"] or out["unpaired_popens"]:
        problems.append("Popen を通らない起動：%r %r" % (out["unpaired_forks"], out["unpaired_popens"]))
    return problems


# ソースの検査の許可リスト。
SEALED_ALLOWED_IMPORTS = frozenset({"ast", "datetime", "fractions", "hashlib", "json", "os", "random", "subprocess",
                                    "sys", "unittest", "exclusion", "tagrules"})
SEALED_ALLOWED_ATTRS = {
    "os": frozenset({"path.join", "path.dirname", "path.abspath", "environ"}),
    "subprocess": frozenset({"run"}),
    "sys": frozenset({"executable", "path.insert"}),
}
SEALED_BANNED_NAMES = frozenset({"__import__", "eval", "exec", "compile", "getattr", "setattr", "globals",
                                 "locals", "vars", "__builtins__", "importlib", "breakpoint", "input"})


def _attr_chain(node):
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        return node.id, ".".join(reversed(parts))
    return None, None


def sealed_test_source_problems(source):
    """封印するテストのソースの、許可リストの外の書き方の一覧（空なら問題なし）。"""
    tree = ast.parse(source)
    problems = []
    parents = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parents[child] = node
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                if a.name.split(".")[0] not in SEALED_ALLOWED_IMPORTS or a.asname:
                    problems.append("import %s" % a.name)
        elif isinstance(node, ast.ImportFrom):
            problems.append("from %s import" % node.module)
        elif isinstance(node, ast.Name):
            if node.id in SEALED_BANNED_NAMES:
                problems.append("名前 %s" % node.id)
            if node.id in SEALED_ALLOWED_ATTRS:
                top = node
                while isinstance(parents.get(top), ast.Attribute):
                    top = parents[top]
                base, chain = _attr_chain(top)
                if not chain or chain not in SEALED_ALLOWED_ATTRS[node.id]:
                    problems.append("%s.%s" % (node.id, chain or ""))
                elif (node.id, chain) == ("os", "environ"):
                    # os.environ は、子プロセスに渡す dict(os.environ, ...) の最初の引数としてだけ使ってよい。
                    call = parents.get(top)
                    if not (isinstance(call, ast.Call) and isinstance(call.func, ast.Name)
                            and call.func.id == "dict" and call.args and call.args[0] is top):
                        problems.append("os.environ をそのまま読む")
                if isinstance(node.ctx, (ast.Store, ast.Del)):
                    problems.append("%s を置き換える" % node.id)
        elif isinstance(node, ast.Constant) and isinstance(node.value, (str, bytes)):
            v = node.value if isinstance(node.value, str) else node.value.decode("latin-1")
            if "STATS_" in v:
                problems.append("見張りの環境変数の名前 %r" % v)
        elif isinstance(node, ast.Attribute) and node.attr.startswith("__") and node.attr != "__file__" \
                and node.attr != "__name__":
            problems.append("属性 %s" % node.attr)
    return problems


class TestSealedTestsReadOnlyTargets(unittest.TestCase):
    def test_sealed_tests_read_only_targets(self):
        out = audit_sealed_tests(PROJECT)
        self.assertEqual(audit_problems(out), [])
        self.assertTrue(out["procs"])  # 見張りが働いていること（空の記録で通らないこと）

    def test_sealed_tests_source(self):
        for rel in SEALED_TEST_FILES:
            with open(os.path.join(PROJECT, rel), encoding="utf-8") as f:
                self.assertEqual(sealed_test_source_problems(f.read()), [], rel)

    def test_allowlist_is_seal_targets(self):
        # 許可リストのファイルは、すべて順番1の封印の対象（seal-order1.md の表）に入っている。
        head, rows = read_handoff_table("seal-targets")
        targets = {r[0].strip("`") for r in rows}
        self.assertLessEqual(set(ALLOWED_OPENS), targets)
        self.assertLessEqual(set(SEALED_TEST_FILES), targets)
        self.assertIn("2d23cdf:reviews/T-020.md", targets)

    # 回り道の例（T-022 の監査が試したもの）。どれも、ソースの検査か実行の見張りのどちらかで止まる。
    DETOURS = {
        "open_relative": 'data = open("reviews/T-020.md", "rb").read()',
        "open_joined": 'data = open(os.path.join(PROJECT, "rev" + "iews", "T-" + "020.md"), "rb").read()',
        "git_other": 'data = subprocess.run(["git", "show", "HEAD:" + "reviews/T-020.md"], capture_output=True).stdout',
        "fork_exec": 'import _posixsubprocess\ndata = b"x"',
        "spawnv_passfds": 'from multiprocessing.util import spawnv_passfds\ndata = b"x"',
        "ctypes": 'import ctypes\ndata = b"x"',
        "env_conditional": 'data = b"x" if "STATS_AUDIT_LOG" in os.environ else open("reviews/T-020.md", "rb").read()',
        "env_name_joined": 'data = b"x" if os.environ.get("STATS" + "_AUDIT_LOG") else b"y"',
        "stat": 'data = str(os.stat("reviews/T-020.md").st_size).encode()',
        "exists": 'data = str(os.path.exists("reviews/T-020.md")).encode()',
        "listdir": 'data = str(os.listdir("reviews")).encode()',
        "link": 'os.link("reviews/T-020.md", "x")\ndata = b"x"',
        "other_env": 'env = dict(os.environ, PYTHONPATH="")\n'
                     'data = subprocess.run([sys.executable, "-B", os.path.join(PROJECT, "src", "stats", "exclusion.py")], '
                     'capture_output=True, env=env, cwd=PROJECT).stdout',
        "other_cwd": 'data = subprocess.run([sys.executable, "-B", os.path.join(PROJECT, "src", "stats", "exclusion.py")], '
                     'capture_output=True, cwd=os.path.join(PROJECT, "src")).stdout or b"x"',
        "dunder": 'data = os.path.__dict__["exists"]("reviews/T-020.md") and b"x" or b"y"',
    }

    def _with_detour(self, src, body):
        import textwrap
        extra = ("\n\nclass TestDetour(unittest.TestCase):\n    def test_detour(self):\n"
                 + textwrap.indent(body, "        ") + "\n        self.assertTrue(len(data) > 0)\n")
        return src.replace('\n\nif __name__ == "__main__":', extra + '\n\nif __name__ == "__main__":')

    def test_detours_are_caught_by_source_check(self):
        with open(os.path.join(PROJECT, SEALED_TEST_FILES[0]), encoding="utf-8") as f:
            src = f.read()
        caught_by_source = {"fork_exec", "spawnv_passfds", "ctypes", "env_conditional", "env_name_joined",
                            "stat", "exists", "listdir", "link", "dunder"}
        for name, body in self.DETOURS.items():
            probs = sealed_test_source_problems(self._with_detour(src, body))
            if name in caught_by_source:
                self.assertTrue(probs, name)

    # 回り道ごとに、実行の見張りが出すはずの問題（audit_problems() の行の頭と、その行に含まれるはずの文字列）。
    # ソースの検査だけで止まるもの（ctypes、_posixsubprocess の import、os.stat・os.path.exists、環境変数の
    # 名前の文字列、__dict__）は、audit の事象を出さないか、写しの中で呼ぶと環境に依るので、ここには入れない。
    AUDIT_EXPECT = {
        "open_relative": ("開いたファイルが違う", "reviews/T-020.md"),
        "open_joined": ("開いたファイルが違う", "reviews/T-020.md"),
        "git_other": ("起動したプロセスが違う", "HEAD:reviews/T-020.md"),
        "listdir": ("一覧を読んだフォルダ", "reviews"),
        "link": ("許可しない事象", "os.link"),
        "other_env": ("起動したプロセスが違う", "PYTHONPATH"),
        "other_cwd": ("起動したプロセスが違う", "'src'"),
        "fork_exec_real": ("Popen を通らない起動", "/bin/cat"),
        "symlink_into_log_dir": ("開いたファイルが違う", "reviews/T-020.md"),
        "hardlink_into_log_dir": ("許可しない事象", "os.link"),
    }

    def _audit_bodies(self):
        bodies = {k: v for k, v in self.DETOURS.items() if k in self.AUDIT_EXPECT}
        bodies["fork_exec_real"] = (
            "from multiprocessing.util import spawnv_passfds\n"
            "r, w = os.pipe()\n"
            "pid = spawnv_passfds(b\"/bin/cat\", [b\"/bin/cat\", b\"reviews/T-020.md\"], (w,))\n"
            "os.close(w)\n"
            "data = b\"\"\n"
            "while True:\n"
            "    c = os.read(r, 65536)\n"
            "    if not c:\n"
            "        break\n"
            "    data += c\n"
            "os.waitpid(pid, 0)")
        bodies["symlink_into_log_dir"] = (
            "d = os.path.dirname(os.environ[\"STATS\" + \"_AUDIT_LOG\"])\n"
            "p = os.path.join(d, \"s\")\n"
            "os.symlink(os.path.join(PROJECT, \"reviews\", \"T-020.md\"), p)\n"
            "data = open(p, \"rb\").read()")
        bodies["hardlink_into_log_dir"] = (
            "d = os.path.dirname(os.environ[\"STATS\" + \"_AUDIT_LOG\"])\n"
            "p = os.path.join(d, \"h\")\n"
            "os.link(os.path.join(PROJECT, \"reviews\", \"T-020.md\"), p)\n"
            "data = open(p, \"rb\").read()")
        self.assertEqual(set(bodies), set(self.AUDIT_EXPECT))
        return bodies

    def test_detours_are_caught_by_audit(self):
        # T-024 M-c：回り道の無い対照で問題が一つも出ない写しを作り、回り道ごとに、期待する問題が出ることを
        # 確かめる。写しは、封印の対象のファイル5件と、回り道が読む reviews/T-020.md と、git の履歴の
        # 1cb463a と 2d23cdf（2d23cdf:reviews/T-020.md の git show に要る）だけを置いたもの
        # （make_targets_only_copy）。履歴があるので、写しでも封印するテストは通る（rc = 0）。
        # 回り道ごとに新しい写しを作る（回り道が写しに残すもの（リンクなど）が、ほかの回り道に効かないため）。
        import tempfile

        def run(body):
            with tempfile.TemporaryDirectory() as d:
                make_targets_only_copy(d, extra=("reviews/T-020.md",))
                path = os.path.join(d, SEALED_TEST_FILES[0])
                if body is not None:
                    with open(path, encoding="utf-8") as f:
                        src = f.read()
                    with open(path, "w", encoding="utf-8") as f:
                        f.write(self._with_detour(src, body))
                out = audit_sealed_tests(d)
            return out

        # 対照：回り道の無い写し。問題は一つも出ない（rc も 0）。見張りが働いていること（procs が空でない）。
        control = run(None)
        self.assertEqual(audit_problems(control), [])
        self.assertTrue(control["procs"])
        # 何もしない本体を足した写しでも、問題は出ない（足し方そのものでは問題が出ないこと）。
        self.assertEqual(audit_problems(run('data = b"x"')), [])
        for name, body in self._audit_bodies().items():
            with self.subTest(name=name):
                probs = audit_problems(run(body))
                head, word = self.AUDIT_EXPECT[name]
                hit = [p for p in probs if p.startswith(head) and word in p]
                self.assertTrue(hit, (name, probs))


def make_targets_only_copy(dst, extra=()):
    """封印の対象のファイル5件（と extra）と、1cb463a・2d23cdf の git の履歴だけを置いた写しを dst に作る。

    docs/stats/seal-order1.md 2章の項目10の手順と同じ作り方（あちらは HEAD の版を git show で置く。
    ここでは作業ツリーのファイルを置く）。git の履歴は、プロジェクトから2つの commit を深さ1で取る。
    ネットワークは使わない（取る元はプロジェクトのフォルダ）。
    """
    def git(*args):
        r = subprocess.run(["git", *args], capture_output=True, cwd=dst)
        if r.returncode != 0:
            raise AssertionError("git %s に失敗：%s" % (" ".join(args), r.stderr.decode("utf-8", "replace")))
    git("init", "-q")
    git("fetch", "-q", "--depth=1", PROJECT, *ORDER1_HISTORY_COMMITS)
    for rel in sorted(set(ALLOWED_OPENS) | set(extra)):
        os.makedirs(os.path.join(dst, os.path.dirname(rel)), exist_ok=True)
        with open(os.path.join(PROJECT, rel), "rb") as f:
            data = f.read()
        with open(os.path.join(dst, rel), "wb") as f:
            f.write(data)


# 封印の対象のうち git の履歴から読むもの（1cb463a:… と 2d23cdf:…）の commit の40桁の ID。
ORDER1_HISTORY_COMMITS = ("1cb463acfcf15ba315e6c454625ad681e86bbc2a", "2d23cdf6e01de5129fc7b0a5d85e89bf02e892c6")


# 限界に当たる書き方（docs/stats/tags-naive.md 5章 (1) の限界）を ast で探す（T-025 L3、差し戻し1回目 中3）。
_LIMIT_VIA_ATTRS = frozenset({"os", "_os", "sys", "_sys", "environ", "modules"})
# 日付・時刻を読む属性。固定の値から作る fromisoformat などは入れない。
_LIMIT_CLOCK_ATTRS = frozenset({"today", "now", "utcnow", "time", "time_ns", "monotonic", "monotonic_ns",
                                "perf_counter", "perf_counter_ns", "process_time", "localtime", "gmtime",
                                "ctime", "fromtimestamp", "utcfromtimestamp"})


def _is_dict_environ_call(node):
    """node が dict(os.environ, ...)（最初の引数が os.environ）の呼び出しか。"""
    return (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "dict"
            and len(node.args) >= 1 and isinstance(node.args[0], ast.Attribute)
            and node.args[0].attr == "environ" and isinstance(node.args[0].value, ast.Name)
            and node.args[0].value.id == "os")


def _is_subprocess_run(call):
    """call が subprocess.run(...)（名前 subprocess の属性 run の呼び出し）か。"""
    return (isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute) and call.func.attr == "run"
            and isinstance(call.func.value, ast.Name) and call.func.value.id == "subprocess")


def _is_env_kw_of_subprocess_run(node, parents):
    """node が subprocess.run(...) のキーワード引数 env= の値そのものか。"""
    user = parents.get(node)
    return (isinstance(user, ast.keyword) and user.arg == "env" and user.value is node
            and _is_subprocess_run(parents.get(user)))


def limit_pattern_problems(source):
    """限界に当たる書き方の一覧（空なら無い）。確かめるのは次の三つだけである。

    - os・sys 以外の名前から、os・_os・sys・_sys・environ・modules に至る属性の参照
      （unittest.loader.os.stat、random._os、exclusion.sys.modules など）
    - 日付・時刻を読む属性（today、now、time、monotonic、fromtimestamp など。_LIMIT_CLOCK_ATTRS）
    - os.environ の使い方。許すのは次の形だけで、ほかはすべて問題とする（T-028 で T-025 の監査の中1を直した）。
      * os.environ は dict(os.environ, ...) の最初の引数としてだけ現れる。
      * dict(os.environ, ...) の結果は、(a) subprocess.run(...) のキーワード引数 env= の値に直接書くか、
        (b) 一つの名前への単純な代入（env = dict(os.environ, ...)）の右辺に書く。(b) の代入は、
        クラスの本体に直接置かない（クラスの属性になり、self.env などの属性として読めるため）。
      * (b) の名前は、ファイルの中で、その代入のほかに代入されず、読み出しはすべて
        subprocess.run(...) のキーワード引数 env= の値そのもの（env=env）である。
      * (b) の名前と同じ名前の属性（self.env、C.env など）は、ファイルのどこにも現れない。
      これで、env.get(...)、env[...]、"X" in env、len(dict(os.environ))、for k in dict(os.environ)、
      str(dict(os.environ))、f(env=dict(os.environ))（subprocess.run 以外の呼び出し）、クラスの属性に
      入れて self.env で読む書き方は、問題になる。

    確かめないこと：subprocess という名前が本物の subprocess モジュールを指すか（import の別名や
    代入で置き換えたもの）、名前のつながりの外で値を読む書き方（globals()、locals()、vars() など、
    名前を文字列で引くもの）。これらは今の二つの封印するテストには無い（test_sealed_tests_have_no_limit_patterns
    は、この関数の結果が空であることだけを確かめる）。
    """
    tree = ast.parse(source)
    parents = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parents[child] = node
    problems = []
    env_names = {}   # dict(os.environ, ...) を入れた名前 → 代入の数
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            if node.attr in _LIMIT_CLOCK_ATTRS:
                problems.append("時刻の属性 %s（%d行）" % (node.attr, node.lineno))
            if node.attr in _LIMIT_VIA_ATTRS:
                base = node.value
                while isinstance(base, ast.Attribute):
                    base = base.value
                root = base.id if isinstance(base, ast.Name) else type(base).__name__
                if root not in ("os", "sys"):
                    problems.append("%s を通る %s（%d行）" % (root, node.attr, node.lineno))
                elif root == "os" and node.attr == "environ":
                    call = parents.get(node)
                    if not (_is_dict_environ_call(call) and call.args[0] is node):
                        problems.append("os.environ の読み方（%d行）" % node.lineno)
        if _is_dict_environ_call(node):
            if _is_env_kw_of_subprocess_run(node, parents):
                continue
            user = parents.get(node)
            if (isinstance(user, ast.Assign) and user.value is node and len(user.targets) == 1
                    and isinstance(user.targets[0], ast.Name)):
                if isinstance(parents.get(user), ast.ClassDef):
                    problems.append("dict(os.environ, ...) をクラスの本体で代入している（%d行）" % node.lineno)
                env_names[user.targets[0].id] = env_names.get(user.targets[0].id, 0) + 1
                continue
            problems.append("dict(os.environ, ...) の使い方（%d行）" % node.lineno)
    for name, count in sorted(env_names.items()):
        stores = [n for n in ast.walk(tree) if isinstance(n, ast.Name) and n.id == name
                  and isinstance(n.ctx, (ast.Store, ast.Del))]
        if len(stores) != count:
            problems.append("名前 %s に dict(os.environ, ...) のほかの代入がある" % name)
        for n in ast.walk(tree):
            if isinstance(n, ast.Name) and n.id == name and isinstance(n.ctx, ast.Load):
                if not _is_env_kw_of_subprocess_run(n, parents):
                    problems.append("名前 %s の読み方（%d行）" % (name, n.lineno))
            if isinstance(n, ast.Attribute) and n.attr == name:
                problems.append("名前 %s と同じ名前の属性（%d行）" % (name, n.lineno))
    return problems


class TestSealedTestsLimitPatterns(unittest.TestCase):
    """tags-naive.md 5章 (1)：今の二つの封印するテストに、限界に当たる書き方が無いこと（T-025 L3）。"""

    CONTROLS = {
        "unittest.loader.os.stat": 'unittest.loader.os.stat("x")',
        "random._os": 'random._os.stat("x")',
        "exclusion.sys.modules": 'y = "sitecustomize" in exclusion.sys.modules',
        "date.today": 'y = datetime.date.today()',
        "datetime.now": 'y = datetime.datetime.now()',
        "fromtimestamp": 'y = datetime.date.fromtimestamp(0)',
        "dict_environ_get": 'y = dict(os.environ).get("A")',
        "dict_environ_args_get": 'y = dict(os.environ, A="1").get("B")',
        "environ_direct": 'y = os.environ.get("A")',
        "environ_subscript": 'y = os.environ["A"]',
        "dict_environ_subscript": 'y = dict(os.environ)["A"]',
        # 差し戻し1回目で監査係が示した書き方（scratchpad の t025_probe.py）
        "var_get": 'env = dict(os.environ, A="1")\nif env.get("B"):\n    pass',
        "var_sub": 'env = dict(os.environ, A="1")\ny = env["B"]',
        "in_compare": 'y = "B" in dict(os.environ, A="1")',
        "len": 'y = len(dict(os.environ))',
        "iter": 'for k in dict(os.environ):\n    pass',
        "str_call": 'y = "B" in str(dict(os.environ))',
        # 名前に入れたものを、env= 以外で読むもの・別の値を代入し直すもの
        "var_in": 'env = dict(os.environ, A="1")\ny = "B" in env',
        "var_len": 'env = dict(os.environ, A="1")\ny = len(env)',
        "var_iter": 'env = dict(os.environ, A="1")\nfor k in env:\n    pass',
        "var_str": 'env = dict(os.environ, A="1")\ny = str(env)',
        "var_alias": 'env = dict(os.environ, A="1")\ne2 = env',
        "var_other_kw": 'env = dict(os.environ, A="1")\nf(x=env)',
        "var_positional": 'env = dict(os.environ, A="1")\nf(env)',
        "var_reassigned": 'env = dict(os.environ, A="1")\nenv = {"A": "1"}\nsubprocess.run(["x"], env=env)',
        "two_targets": 'env = e2 = dict(os.environ, A="1")',
        "unpack": 'env, e2 = dict(os.environ, A="1"), 1',
        "other_kw_direct": 'f(x=dict(os.environ, A="1"))',
        # T-025 再提出1回目の監査の中1で示された書き方（T-028 で足した）：env= を持つ呼び出しが
        # subprocess.run でないもの、クラスの本体の代入と、同じ名前の属性での読み出し
        "env_kw_other_func": 'def f(**kw):\n    return kw["env"].get("B")\ny = f(env=dict(os.environ, A="1"))',
        "var_env_kw_other_func": ('env = dict(os.environ, A="1")\ndef f(env=None):\n    return None\n'
                                  'y = f(env=env)'),
        "env_kw_other_run": 'y = runner.run(["x"], env=dict(os.environ, A="1"))',
        "class_body_self_attr": ('class C:\n    env = dict(os.environ, A="1")\n    def m(self):\n'
                                 '        subprocess.run(["x"], env=self.env)\n        return self.env.get("B")'),
        "same_name_attr": ('env = dict(os.environ, A="1")\nsubprocess.run(["x"], env=env)\n'
                           'class C:\n    pass\nC.env = {}\ny = C.env'),
        # T-025 再提出1回目の監査の軽5：time.time() の対照
        "time.time": 'y = time.time()',
    }

    def test_sealed_tests_have_no_limit_patterns(self):
        for rel in SEALED_TEST_FILES:
            with open(os.path.join(PROJECT, rel), encoding="utf-8") as f:
                self.assertEqual(limit_pattern_problems(f.read()), [], rel)

    def test_limit_pattern_check_catches_controls(self):
        allowed = ('env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")\n'
                   'r = subprocess.run(["x"], capture_output=True, env=env)\n'
                   'subprocess.run(["x"], env=dict(os.environ, A="1"))\n')
        self.assertEqual(limit_pattern_problems(allowed), [])
        for name, body in self.CONTROLS.items():
            with self.subTest(name=name):
                self.assertTrue(limit_pattern_problems(allowed + body + "\n"), name)


class TestTargetsOnlyCopy(unittest.TestCase):
    """seal-order1.md 2章の項目10（T-024 M-b）：見張りの環境変数を付けず、対象だけを置いた写しで、
    封印する二つのテストが通ること。見張りの有無で分岐して対象の外を読む書き方や、対象の外のファイルを
    読んで通る書き方は、この写しでは失敗する。"""

    def test_sealed_tests_pass_in_targets_only_copy(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            make_targets_only_copy(d)
            env = {k: v for k, v in os.environ.items()
                   if k not in ("STATS_AUDIT_LOG", "PYTHONPATH", "PYTHONPYCACHEPREFIX")}
            env["PYTHONDONTWRITEBYTECODE"] = "1"
            r = subprocess.run([sys.executable, "-B", "-m", "unittest", *SEALED_TEST_FILES],
                               capture_output=True, env=env, cwd=d)
            self.assertEqual(r.returncode, 0, r.stderr.decode("utf-8", "replace")[-3000:])
            # 写しの中に、置いた5件のほかのファイルができていない（テストは書かない）。
            found = set()
            for root, dirs, files in os.walk(d):
                dirs[:] = [x for x in dirs if not (root == d and x == ".git")]
                found.update(os.path.relpath(os.path.join(root, x), d) for x in files)
            self.assertEqual(found, set(ALLOWED_OPENS))

    def test_history_commits_are_seal_targets(self):
        head, rows = read_handoff_table("seal-targets")
        targets = {r[0].strip("`") for r in rows}
        for c in ORDER1_HISTORY_COMMITS:
            self.assertTrue(any(t.startswith(c[:7] + ":") for t in targets), c)
            r = subprocess.run(["git", "rev-parse", c[:7]], capture_output=True, text=True, cwd=PROJECT)
            self.assertEqual(r.stdout.strip(), c)


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
