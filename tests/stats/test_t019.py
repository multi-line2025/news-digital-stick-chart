"""タグの一覧の規則・素朴な予測・採点計画の一部のテスト（T-019）。

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
import tagrules  # noqa: E402

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
# 除外の規則
# ---------------------------------------------------------------------------

class TestExclusion(unittest.TestCase):
    def test_tokens(self):
        self.assertEqual(tagrules.tokens("WB_123_Fragility-Conflict and violence"),
                         ("WB", "123", "FRAGILITY", "CONFLICT", "AND", "VIOLENCE"))
        self.assertEqual(tagrules.tokens(None), ())
        self.assertEqual(tagrules.tokens(""), ())

    def test_exact_token_match(self):
        self.assertTrue(tagrules.is_excluded("ECON_WAR_DAMAGE"))
        self.assertTrue(tagrules.is_excluded("x", "about the election results"))
        self.assertTrue(tagrules.is_excluded("tax_fncact_police"))

    def test_no_substring_match(self):
        for name in ("SOFTWARE", "AWARD", "FARMS", "GRAPE", "AIDGROUPS", "STOCKMARKET",
                     "KINGDOM_TRAVEL", "FIREWORKS", "FLUENT"):
            self.assertFalse(tagrules.is_excluded(name), name)

    def test_phrase_needs_contiguous_tokens(self):
        self.assertTrue(tagrules.is_excluded("TAX_FNCACT_PRIME_MINISTER"))
        m = tagrules.exclusion_matches("PRIME_RATE")
        self.assertEqual(m, [])
        self.assertIn(("politics_election", "HEAD OF STATE", "description"),
                      tagrules.exclusion_matches("X", "visit by a head of state"))
        self.assertFalse(tagrules.is_excluded("HEAD_STATE_OF"))

    def test_description_used_and_reported(self):
        m = tagrules.exclusion_matches("SOC_GENERAL", "Outbreak of cholera")
        self.assertIn(("disaster_disease", "OUTBREAK", "description"), m)
        self.assertIn(("disaster_disease", "CHOLERA", "description"), m)

    def test_neutral_examples_kept(self):
        for name, desc in (("ECON_STOCKMARKET", "Stock market"), ("EDUCATION", None),
                           ("ENV_SOLAR", "Solar power"), ("SOC_INNOVATION", "")):
            self.assertFalse(tagrules.is_excluded(name, desc), name)

    def test_terms_wellformed(self):
        allt = [t for ts in tagrules.EXCLUSION_TERMS.values() for t in ts]
        self.assertEqual(len(allt), len(set(allt)))
        for t in allt:
            self.assertRegex(t, r"\A[A-Z0-9]+( [A-Z0-9]+)*\Z")
        self.assertEqual(set(tagrules.EXCLUSION_TERMS),
                         set(tagrules.CLAUDE_CATEGORIES) | set(tagrules.EXTRA_CATEGORIES_NEEDING_APPROVAL))
        self.assertEqual(len(tagrules.CLAUDE_CATEGORIES), 5)

    def test_no_per_theme_exception_mechanism(self):
        # 一件ずつの例外を持たない：照合は名前と説明と語の一覧だけで決まる。
        with open(os.path.join(SRC, "tagrules.py"), encoding="utf-8") as f:
            src = f.read()
        for word in ("ALLOWLIST", "DENYLIST", "EXCEPTIONS =", "FORCE_INCLUDE", "FORCE_EXCLUDE"):
            self.assertNotIn(word, src)

    def test_doc_terms_table(self):
        head, rows = read_table("terms")
        self.assertEqual(head, ["区分", "語"])
        got = {r[0]: tuple(x.strip() for x in r[1].split(",")) for r in rows}
        self.assertEqual(got, tagrules.EXCLUSION_TERMS)
        self.assertEqual([r[0] for r in rows], list(tagrules.EXCLUSION_TERMS))


# ---------------------------------------------------------------------------
# 入れる規則
# ---------------------------------------------------------------------------

class TestQuarters(unittest.TestCase):
    def test_method_block(self):
        qs = tagrules.quarters(METHOD_START, METHOD_END)
        self.assertEqual(len(qs), 24)
        self.assertEqual(qs[0], (D(2015, 3, 2), D(2015, 3, 31)))
        self.assertEqual(qs[1], (D(2015, 4, 1), D(2015, 6, 30)))
        self.assertEqual(qs[-1], (D(2020, 10, 1), D(2020, 12, 14)))
        for (a, b), (c, d) in zip(qs, qs[1:]):
            self.assertEqual(b + DAY, c)
        self.assertEqual(sum((b - a).days + 1 for a, b in qs), (METHOD_END - METHOD_START).days + 1)

    def test_matches_periods_block(self):
        ps = periods.rebuild_periods()
        self.assertEqual((ps[0]["block_start"], ps[0]["block_end"]), (METHOD_START, METHOD_END))

    def test_doc_constants(self):
        head, rows = read_table("tag-constants")
        got = {r[0]: r[1] for r in rows}
        self.assertEqual(got["K_ARTICLES_PER_DAY"], str(tagrules.K_ARTICLES_PER_DAY))
        self.assertEqual(got["MIN_COUNT_PER_QUARTER"], str(tagrules.MIN_COUNT_PER_QUARTER))
        self.assertEqual(got["四半期の数"], str(len(tagrules.quarters(METHOD_START, METHOD_END))))


class TestBuildTagList(unittest.TestCase):
    # 小さな区画（2つの四半期にまたがる）で試す。
    S, E = D(2019, 3, 1), D(2019, 6, 30)

    def days(self):
        d, out = self.S, []
        while d <= self.E:
            out.append(d)
            d += DAY
        return out

    def base(self, total=1000):
        totals = {d: total for d in self.days()}
        return totals

    def test_a_is_k_over_median(self):
        totals = self.base()
        for i, d in enumerate(self.days()[:10]):
            totals[d] = 3000  # 中央値は 1000 のまま
        r = tagrules.build_tag_list({}, {}, totals, set(), self.S, self.E)
        self.assertEqual(r["a"], "1/100")
        self.assertEqual(r["n_med"], "1000/1")
        a, n = tagrules.threshold_a({1: 1, 2: 3, 3: 10, 4: 20}, set())
        self.assertEqual(n, F(13, 2))
        self.assertEqual(a, F(10) / F(13, 2))

    def test_rules(self):
        totals = self.base(1000)  # A = 10/1000
        ds = self.days()
        counts = {
            "ECON_A": {d: 10 for d in ds},                 # 平均 = A ちょうど → 入る
            "ECON_B": {d: 9 for d in ds},                  # A 未満
            "ECON_C": {d: 50 for d in ds if d.month >= 4},  # 最初の四半期に無い
            "MILITARY_X": {d: 100 for d in ds},            # 除外の語
            "ECON_D": {d: 100 for d in ds},                # 説明で除外
        }
        themes = {"ECON_A": None, "ECON_B": "", "ECON_C": "x", "MILITARY_X": "", "ECON_D": "flood relief",
                  "ECON_E": "never appears"}
        r = tagrules.build_tag_list(themes, counts, totals, set(), self.S, self.E)
        self.assertEqual(r["tag_list"], ["ECON_A"])
        rows = {x["name"]: x for x in r["themes"]}
        self.assertTrue(rows["ECON_A"]["mean_ratio_at_least_a"])
        self.assertFalse(rows["ECON_B"]["mean_ratio_at_least_a"])
        self.assertFalse(rows["ECON_C"]["present_throughout"])
        self.assertEqual(rows["ECON_C"]["quarter_counts"][0], 0)
        self.assertEqual(rows["MILITARY_X"]["exclusion_matches"], [["conflict_violence", "MILITARY", "name"]])
        self.assertEqual(rows["ECON_D"]["exclusion_matches"], [["disaster_disease", "FLOOD", "description"]])
        self.assertFalse(rows["ECON_E"]["present_throughout"])
        self.assertTrue(rows["ECON_A"]["in_category_table"])
        self.assertEqual([x["name"] for x in r["themes"]], sorted(rows))
        self.assertTrue(r["v_equals_a"])

    def test_theme_only_in_data_is_considered(self):
        ds = self.days()
        r = tagrules.build_tag_list({}, {"ECON_Z": {d: 20 for d in ds}}, self.base(), set(), self.S, self.E)
        self.assertEqual(r["tag_list"], ["ECON_Z"])
        self.assertFalse(r["themes"][0]["in_category_table"])

    def test_missing_days_not_counted(self):
        ds = self.days()
        march = [d for d in ds if d.month == 3]
        missing = set(march)  # 最初の四半期の使える日が無い → その四半期は条件から外す
        totals = self.base()
        counts = {"ECON_C": {d: 50 for d in ds if d.month >= 4}}
        r = tagrules.build_tag_list({}, counts, totals, missing, self.S, self.E)
        self.assertEqual(r["quarters_without_usable_days"], [0])
        self.assertEqual(r["tag_list"], ["ECON_C"])
        self.assertIsNone(r["themes"][0]["quarter_counts"][0])
        # 欠けた日の件数は存在の条件にも平均にも入らない
        missing2 = {march[0]}
        counts2 = {"ECON_Q": {march[0]: 10 ** 6}}
        r2 = tagrules.build_tag_list({}, counts2, totals, missing2, self.S, self.E)
        self.assertEqual(r2["themes"][0]["mean_ratio"], 0.0)
        self.assertEqual(r2["themes"][0]["quarter_counts"], [0, 0])

    def test_rejects_dates_outside_block(self):
        totals = self.base()
        later = {self.E + DAY: 5}
        with self.assertRaises(ValueError):
            tagrules.build_tag_list({}, {"ECON_A": later}, totals, set(), self.S, self.E)
        t2 = dict(totals)
        t2[self.E + DAY] = 1000
        with self.assertRaises(ValueError):
            tagrules.build_tag_list({}, {}, t2, set(), self.S, self.E)
        with self.assertRaises(ValueError):
            tagrules.build_tag_list({}, {}, totals, {self.S - DAY}, self.S, self.E)
        # 閾値を決める期間の始まりの日も拒む
        with self.assertRaises(ValueError):
            tagrules.build_tag_list({}, {"A": {D(2020, 12, 15): 1}}, {}, set(), METHOD_START, METHOD_END)

    def test_rejects_bad_totals_and_counts(self):
        totals = self.base()
        totals[self.S] = 0
        with self.assertRaises(ValueError):
            tagrules.build_tag_list({}, {}, totals, set(), self.S, self.E)
        totals = self.base()
        del totals[self.S]
        with self.assertRaises(ValueError):
            tagrules.build_tag_list({}, {}, totals, set(), self.S, self.E)
        with self.assertRaises(ValueError):
            tagrules.build_tag_list({}, {"A": {self.S: -1}}, self.base(), set(), self.S, self.E)
        with self.assertRaises(ValueError):
            tagrules.build_tag_list({}, {"A": {self.S: 1.5}}, self.base(), set(), self.S, self.E)

    def test_deterministic(self):
        ds = self.days()
        rng = random.Random(7)
        counts = {"T%02d" % i: {d: rng.randrange(0, 30) for d in ds} for i in range(20)}
        a = tagrules.build_tag_list({}, counts, self.base(), set(), self.S, self.E)
        b = tagrules.build_tag_list({}, dict(reversed(list(counts.items()))), self.base(), set(), self.S, self.E)
        self.assertEqual(json.dumps(a, sort_keys=True), json.dumps(b, sort_keys=True))


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

MODULES = ("tagrules", "naive", "scoring")


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

    def test_tagrules_output(self):
        rec = json.loads(tagrules.canonical_json())
        self.assertEqual(rec["inclusion"]["k_articles_per_day"], 10)
        self.assertEqual(rec["exclusion"]["per_theme_exceptions"], "none")
        self.assertEqual(rec["exclusion"]["terms"], {k: list(v) for k, v in tagrules.EXCLUSION_TERMS.items()})


class TestNoDataNoNetwork(unittest.TestCase):
    ALLOWED = {
        "tagrules": {"datetime", "fractions", "json", "math", "re", "sys"},
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
