"""閾値と判定期間の候補（src/stats/candidates.py）のテスト。T-011。

実行（プロジェクトのルートで）:
    PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest discover -s tests/stats -v

データもネットワークも使わない。
"""

import ast
import datetime
import fractions
import inspect
import json
import os
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(os.path.dirname(HERE))
SRC = os.path.join(PROJECT, "src", "stats")
SCRIPT = os.path.join(SRC, "candidates.py")
DOC = os.path.join(PROJECT, "docs", "stats", "candidates.md")
sys.path.insert(0, SRC)

import candidates  # noqa: E402
import periods  # noqa: E402

D = datetime.date
DAY = datetime.timedelta(days=1)
F = fractions.Fraction

# テストの側にも候補を直接書き、コードと照合する。
EXPECTED_MULTIPLIERS = (2, 3, 4, 6, 8, 12, 16)
EXPECTED_HORIZONS = (14, 28, 56)
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


def pct(fr):
    v = fr * 100
    return ("%d%%" % v) if v.denominator == 1 else ("%s%%" % format(float(v), "g"))


class TestCandidates(unittest.TestCase):
    def test_values(self):
        self.assertEqual(candidates.THRESHOLD_MULTIPLIERS, EXPECTED_MULTIPLIERS)
        self.assertEqual(candidates.HORIZON_DAYS, EXPECTED_HORIZONS)
        self.assertEqual(candidates.SMOOTHING_DAYS, 7)

    def test_multiplier_spacing(self):
        ms = candidates.THRESHOLD_MULTIPLIERS
        self.assertEqual(ms[0], 2)
        self.assertEqual(list(ms), sorted(set(ms)))
        for a, b in zip(ms, ms[1:]):
            self.assertLessEqual(F(b, a), F(3, 2))
        # 10〜15%の段の幅（1.5倍）と同じ上限
        hi = candidates.TIERS[1]
        self.assertEqual(hi[3] / hi[2], F(3, 2))

    def test_horizons_multiple_of_week(self):
        for h in candidates.HORIZON_DAYS:
            self.assertEqual(h % 7, 0)
            self.assertGreater(h, candidates.SMOOTHING_DAYS)

    def test_combinations(self):
        cs = candidates.combinations()
        self.assertEqual(len(cs), 21)
        self.assertEqual(len(set(cs)), 21)
        self.assertEqual(set(cs), {(m, h) for m in EXPECTED_MULTIPLIERS for h in EXPECTED_HORIZONS})

    def test_j(self):
        for h in candidates.HORIZON_DAYS:
            self.assertEqual(candidates.last_read_offset_days(h), h)
        self.assertEqual(candidates.max_last_read_offset_days(), 56)
        with self.assertRaises(ValueError):
            candidates.last_read_offset_days(6)


class TestAgainstPeriods(unittest.TestCase):
    def test_frozen_blocks_unchanged(self):
        self.assertEqual(periods.FROZEN_BLOCKS, V1_BLOCKS)
        ps = periods.rebuild_periods(last_read_offset_days=candidates.max_last_read_offset_days())
        self.assertEqual(tuple((p["name"], p["block_start"], p["block_end"]) for p in ps), V1_BLOCKS)

    def test_all_j_within_embargo(self):
        for h in candidates.HORIZON_DAYS:
            j = candidates.last_read_offset_days(h)
            self.assertTrue(periods.horizon_is_valid(j))
            self.assertLessEqual(j, periods.EMBARGO_DAYS)
        self.assertEqual(periods.required_embargo(candidates.max_last_read_offset_days()), 90)

    def test_prediction_ranges_same_as_v1(self):
        v1 = periods.as_record()
        rebuilt = periods.as_record(
            last_read_offset_days=candidates.max_last_read_offset_days(),
            deadline_status="before_deadline",
        )
        self.assertEqual(v1["periods"], rebuilt["periods"])
        self.assertEqual(rebuilt["rules"]["proposed_label"], periods.PROPOSED_LABEL)

    def test_judgment_inside_own_block(self):
        # 各期間の最後の予言でも、最も長い判定期間が自分の区画の中で終わる。
        h = max(candidates.HORIZON_DAYS)
        for p in periods.rebuild_periods(last_read_offset_days=h):
            last_t = periods.prediction_dates(p)[-1]
            first, last = candidates.judgment_window(last_t, h)
            self.assertGreater(first, last_t)
            self.assertLessEqual(last, p["block_end"])

    def test_check_function(self):
        r = candidates.check_against_periods()
        self.assertEqual(r["max_last_read_offset_days"], 56)
        self.assertEqual(r["embargo_days"], 90)
        self.assertFalse(r["periods_rebuild_needed"])

    def test_over_90_would_need_rebuild(self):
        # 90 を超える J を入れたら、エンバーゴの作り直しが要ることの確認。
        self.assertFalse(periods.horizon_is_valid(91))
        self.assertEqual(periods.required_embargo(120), 120)


class GuardedRatios:
    """first から last の外の日を読んだら失敗する比率の表。"""

    def __init__(self, first, last, values, testcase, default=0.0):
        self.first, self.last = first, last
        self.values = values
        self.tc = testcase
        self.default = default
        self.read = []

    def __call__(self, d):
        self.tc.assertGreaterEqual(d, self.first)
        self.tc.assertLessEqual(d, self.last)
        self.read.append(d)
        return self.values.get(d, self.default)


V = 0.5  # テストで使う最低の報道量（値に意味は無い）


class TestJudge(unittest.TestCase):
    T = D(2018, 1, 1)

    def ratios(self, h, values):
        first, last = candidates.judgment_window(self.T, h)
        return GuardedRatios(first, last, values, self)

    def judge(self, h, values, m=2, b=1.0, v=V):
        return candidates.judge(self.ratios(h, values), self.T, h, m, b, v)

    def test_window(self):
        first, last = candidates.judgment_window(self.T, 28)
        self.assertEqual(first, self.T + DAY)
        self.assertEqual(last, self.T + 28 * DAY)
        ends = candidates.smoothing_window_ends(self.T, 28)
        self.assertEqual(len(ends), 22)
        self.assertEqual(ends[0], self.T + 7 * DAY)
        self.assertEqual(ends[-1], last)

    def test_reads_only_window(self):
        for h in EXPECTED_HORIZONS:
            g = self.ratios(h, {})
            self.assertFalse(candidates.judge(g, self.T, h, 2, 1.0, V))
            self.assertEqual(sorted(set(g.read)), [self.T + k * DAY for k in range(1, h + 1)])

    def test_strictly_greater(self):
        days = {self.T + k * DAY: 2.0 for k in range(1, 8)}
        self.assertFalse(self.judge(14, days))
        days[self.T + 7 * DAY] = 2.07
        self.assertTrue(self.judge(14, days))

    def test_single_day_spike_is_smoothed(self):
        # 1日だけ 10 倍でも、7日の平均が 2 倍を超えなければ島ではない。
        self.assertFalse(self.judge(28, {self.T + 10 * DAY: 10.0}))
        self.assertTrue(self.judge(28, {self.T + 10 * DAY: 14.5}))

    def test_spike_after_window_not_counted(self):
        # t+15 は読まないので、判定に入らない（GuardedRatios が読めば失敗する）。
        self.assertFalse(self.judge(14, {self.T + 15 * DAY: 100.0}))

    def test_missing_days(self):
        h = 14
        missing = {self.T + k * DAY: None for k in range(1, h + 1)}
        self.assertIsNone(self.judge(h, missing))
        # t+7 が欠けると、終わりが t+7..t+13 のまとまりは使えない。
        # t+6 の跳ねはそれらのまとまりにしか入らないので数えない。
        self.assertFalse(self.judge(h, {self.T + 7 * DAY: None, self.T + 6 * DAY: 100.0}))
        self.assertTrue(self.judge(h, {self.T + 7 * DAY: None, self.T + 14 * DAY: 100.0}))

    def test_zero_baseline_is_judged_with_min_level(self):
        # B(t) = 0 のタグも判定できる。V を超えなければ島ではない。
        one_article = {self.T + 3 * DAY: 0.01}
        self.assertFalse(self.judge(14, one_article, b=0.0))
        self.assertTrue(self.judge(14, {self.T + 3 * DAY: 7 * V + 0.01}, b=0.0))
        self.assertFalse(self.judge(14, {self.T + 3 * DAY: 7 * V}, b=0.0))

    def test_tiny_baseline_needs_min_level(self):
        # 監査の例：B = 1e-12。V が無ければ、どの倍率でもごく小さい量で島になる。
        b = 1e-12
        small = {self.T + 3 * DAY: 1e-9}  # 7日の平均は 1e-9/7。16 × 1e-12 より大きい。
        for m in EXPECTED_MULTIPLIERS:
            self.assertGreater(1e-9 / 7, m * b)
            self.assertFalse(self.judge(14, small, m=m, b=b))
        # V を超えれば島（倍率の条件はもともと満たしている）。
        for m in EXPECTED_MULTIPLIERS:
            self.assertTrue(self.judge(14, {self.T + 3 * DAY: 7 * V * 1.01}, m=m, b=b))

    def test_multiplier_still_binds_when_baseline_large(self):
        # B が大きいタグでは、倍率の条件が判定を決める。
        days = {self.T + k * DAY: 2.5 for k in range(1, 8)}
        self.assertTrue(self.judge(14, days, m=2, b=1.0))
        self.assertFalse(self.judge(14, days, m=3, b=1.0))

    def test_bad_inputs_rejected(self):
        with self.assertRaises(ValueError):
            self.judge(14, {}, v=0.0)
        with self.assertRaises(ValueError):
            self.judge(14, {}, v=None)
        with self.assertRaises(ValueError):
            self.judge(14, {}, b=-1.0)
        with self.assertRaises(ValueError):
            self.judge(14, {}, b=None)
        with self.assertRaises(ValueError):
            candidates.judge(self.ratios(14, {}), self.T, 30, 2, 1.0, V)
        with self.assertRaises(ValueError):
            candidates.judge(self.ratios(14, {}), self.T, 14, 5, 1.0, V)


class TestLevels(unittest.TestCase):
    T = D(2018, 6, 4)

    def guarded(self, values, default=1.0):
        return GuardedRatios(self.T - 371 * DAY, self.T - DAY, values, self, default)

    def test_baseline_reads_only_past(self):
        g = self.guarded({})
        self.assertEqual(candidates.baseline_level(g, self.T), 1.0)
        self.assertEqual(min(g.read), self.T - 371 * DAY)
        self.assertEqual(max(g.read), self.T - DAY)

    def test_baseline_is_median_of_7day_means(self):
        # 最後の 7 日だけ 8.0。それを含むまとまりは 7 個しかなく、中央値は 1.0 のまま。
        vals = {self.T - k * DAY: 8.0 for k in range(1, 8)}
        self.assertEqual(candidates.baseline_level(self.guarded(vals), self.T), 1.0)
        # 半分を超える日が 0 なら中央値は 0。
        vals = {self.T - k * DAY: 0.0 for k in range(1, 372)}
        self.assertEqual(candidates.baseline_level(self.guarded(vals), self.T), 0.0)

    def test_baseline_even_count_and_missing(self):
        # 欠けた日のまとまりは使わない。全部欠ければ None。
        vals = {self.T - k * DAY: None for k in range(1, 372)}
        self.assertIsNone(candidates.baseline_level(self.guarded(vals), self.T))
        # 使えるまとまりが 2 個だけ（t-371..t-365 と t-370..t-364）→ 平均
        vals = {self.T - k * DAY: None for k in range(1, 364)}
        vals.update({self.T - k * DAY: 1.0 for k in range(365, 372)})
        vals[self.T - 364 * DAY] = 8.0
        # まとまり A = t-371..t-365 = 1.0、B = t-370..t-364 = (6 + 8)/7 = 2.0
        self.assertAlmostEqual(candidates.baseline_level(self.guarded(vals), self.T), 1.5)

    def test_current_level(self):
        g = GuardedRatios(self.T - 7 * DAY, self.T - DAY, {self.T - DAY: 8.0}, self, 1.0)
        self.assertAlmostEqual(candidates.current_level(g, self.T), 14.0 / 7)
        g = GuardedRatios(self.T - 7 * DAY, self.T - DAY, {self.T - 2 * DAY: None}, self, 1.0)
        self.assertIsNone(candidates.current_level(g, self.T))

    def test_baseline_fits_periods_lookback(self):
        self.assertEqual(candidates.BASELINE_WINDOW_DAYS + candidates.SMOOTHING_DAYS - 1, 371)
        self.assertLessEqual(371, periods.LOOKBACK_DAYS)


class TestMissingDay(unittest.TestCase):
    def test_rule(self):
        self.assertEqual(candidates.SLOTS_PER_DAY, 96)
        self.assertEqual(candidates.MIN_PRESENT_SLOTS, 72)
        self.assertFalse(candidates.day_is_missing(96, 100))
        self.assertFalse(candidates.day_is_missing(72, 100))
        self.assertTrue(candidates.day_is_missing(71, 100))
        self.assertTrue(candidates.day_is_missing(0, 0))
        self.assertTrue(candidates.day_is_missing(96, 0))

    def test_bad_inputs(self):
        for slots in (-1, 97, 1.5, None):
            with self.assertRaises(ValueError):
                candidates.day_is_missing(slots, 1)
        with self.assertRaises(ValueError):
            candidates.day_is_missing(96, -1)


def table(spec, n=1000):
    """spec: {H: {m: 島の件数}}。対象の件数は n でそろえる。

    指定の無い倍率には、次に大きい指定の倍率の値（無ければ 0）を入れる。
    指定の値が倍率について増えなければ、表は検査を通る。
    """
    out = {}
    for h in EXPECTED_HORIZONS:
        cur = 0
        for m in sorted(EXPECTED_MULTIPLIERS, reverse=True):
            cur = spec.get(h, {}).get(m, cur)
            out[(m, h)] = (cur, n)
    return out


class TestSelect(unittest.TestCase):
    def test_signature_has_no_model_scores(self):
        self.assertEqual(list(inspect.signature(candidates.select).parameters), ["rate_table"])

    def test_basic(self):
        t = table({28: {2: 125, 8: 20, 12: 0}})
        self.assertEqual(candidates.select(t), {"horizon_days": 28, "low": 8, "high": 2})

    def test_shortest_horizon_first(self):
        t = table({14: {3: 110, 12: 15}, 28: {2: 125, 8: 20}})
        self.assertEqual(candidates.select(t), {"horizon_days": 14, "low": 12, "high": 3})

    def test_closest_on_log_scale_and_tie_larger(self):
        # 1% と 4% は 2% から対数の尺度で同じ近さ -> 大きい倍率
        t = table({14: {16: 10, 12: 40, 2: 125}})
        self.assertEqual(candidates.select(t)["low"], 16)
        # 3% は 1.5 倍離れ、1.5% は 4/3 倍離れ -> 1.5% の方が近い
        t = table({14: {16: 0, 12: 15, 8: 30, 2: 125}})
        self.assertEqual(candidates.select(t)["low"], 12)

    def test_bounds_inclusive(self):
        self.assertEqual(candidates.select(table({14: {16: 10, 2: 150}})), {"horizon_days": 14, "low": 16, "high": 2})
        self.assertIsNone(candidates.select(table({14: {16: 9, 2: 150}})))
        self.assertIsNone(candidates.select(table({14: {16: 10, 2: 151}})))

    def test_none_when_unreachable(self):
        t = table({h: {m: 500 for m in EXPECTED_MULTIPLIERS} for h in EXPECTED_HORIZONS})
        self.assertIsNone(candidates.select(t))

    def test_zero_targets_not_in_band(self):
        t = table({28: {2: 125, 8: 20}})
        for m in EXPECTED_MULTIPLIERS:
            t[(m, 14)] = (0, 0)
        self.assertEqual(candidates.select(t)["horizon_days"], 28)

    def test_rejects_rate_increasing_with_multiplier(self):
        t = table({14: {2: 20, 3: 120}})  # 倍率3の方が島が多い
        with self.assertRaises(ValueError):
            candidates.select(t)
        t = table({})
        t[(16, 56)] = (1, 1000)  # 12倍は0件、16倍は1件
        with self.assertRaises(ValueError):
            candidates.select(t)

    def test_rejects_different_target_counts(self):
        t = table({28: {2: 125, 8: 20}})
        t[(4, 28)] = (20, 1001)
        with self.assertRaises(ValueError):
            candidates.select(t)

    def test_rejects_missing_or_extra_combinations(self):
        t = table({})
        del t[(2, 14)]
        with self.assertRaises(ValueError):
            candidates.select(t)
        t = table({})
        t[(5, 30)] = (1, 10)
        with self.assertRaises(ValueError):
            candidates.select(t)

    def test_rejects_bad_counts(self):
        for bad in [(1001, 1000), (-1, 1000), (1.0, 1000), (True, 1000)]:
            t = table({})
            t[(2, 14)] = bad
            with self.assertRaises(ValueError):
                candidates.select(t)

    def test_only_rates_matter(self):
        a = table({28: {2: 125, 8: 20}}, n=1000)
        b = table({28: {2: 250, 8: 40}}, n=2000)
        self.assertEqual(candidates.select(a), candidates.select(b))


class TestDoc(unittest.TestCase):
    def test_candidates_table(self):
        header, body = read_table("candidates")
        self.assertEqual(header, ["項目", "値"])
        v = dict((r[0], r[1]) for r in body)
        self.assertEqual(len(body), 6)
        self.assertEqual(v["閾値の倍率"], ", ".join(str(m) for m in candidates.THRESHOLD_MULTIPLIERS))
        self.assertEqual(v["判定期間（日）"], ", ".join(str(h) for h in candidates.HORIZON_DAYS))
        self.assertEqual(v["組み合わせの数"], str(len(candidates.combinations())))
        self.assertEqual(v["平滑化（日）"], str(candidates.SMOOTHING_DAYS))
        self.assertEqual(v["J の最大（日）"], str(candidates.max_last_read_offset_days()))
        self.assertEqual(v["エンバーゴ（日）"], str(periods.required_embargo(candidates.max_last_read_offset_days())))

    def test_horizons_table(self):
        header, body = read_table("horizons")
        self.assertEqual(len(header), 4)
        expected = []
        for h in candidates.HORIZON_DAYS:
            j = candidates.last_read_offset_days(h)
            expected.append([
                str(h), str(j), str(len(candidates.smoothing_window_ends(D(2018, 1, 1), h))),
                "はい" if periods.horizon_is_valid(j) else "いいえ",
            ])
        self.assertEqual(body, expected)

    def test_tiers_table(self):
        header, body = read_table("tiers")
        self.assertEqual(header, ["段", "中心", "下限", "上限"])
        expected = [[n, pct(c), pct(lo), pct(hi)] for n, c, lo, hi in candidates.TIERS]
        self.assertEqual(body, expected)


class TestOutput(unittest.TestCase):
    def run_cli(self, *args):
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
        return subprocess.run(
            [sys.executable, "-B", SCRIPT, *args], capture_output=True, text=True, env=env, cwd=PROJECT
        )

    def test_cli_equals_function_and_deterministic(self):
        a = self.run_cli()
        b = self.run_cli()
        self.assertEqual(a.returncode, 0, a.stderr)
        self.assertEqual(a.stdout, b.stdout)
        self.assertEqual(a.stdout, candidates.canonical_json())
        rec = json.loads(a.stdout)
        self.assertEqual(rec["threshold_multipliers"], list(EXPECTED_MULTIPLIERS))
        self.assertEqual(rec["horizon_days"], list(EXPECTED_HORIZONS))
        self.assertEqual(rec["combination_count"], 21)
        self.assertEqual(rec["periods_check"]["max_last_read_offset_days"], 56)
        self.assertEqual(rec["periods_check"]["baseline_lookback_days"], 371)
        self.assertEqual(rec["min_present_slots"], 72)
        self.assertIn("B(t) = 0 stays", rec["judgment"]["zero_baseline"])
        self.assertIn("mean > V", rec["judgment"]["comparison"])

    def test_cli_rejects_args(self):
        r = self.run_cli("--horizon", "30")
        self.assertEqual(r.returncode, 2)


class TestNoDataNoNetwork(unittest.TestCase):
    ALLOWED_IMPORTS = {"datetime", "fractions", "json", "sys", "periods"}

    def setUp(self):
        with open(SCRIPT, encoding="utf-8") as f:
            self.tree = ast.parse(f.read())

    def test_imports(self):
        names = set()
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Import):
                names.update(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom):
                names.add((node.module or "").split(".")[0])
        self.assertEqual(names - self.ALLOWED_IMPORTS, set())

    def test_no_clock_no_files(self):
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Attribute):
                self.assertNotIn(node.attr, {"today", "now", "utcnow", "time"})
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                self.assertNotEqual(node.func.id, "open")


if __name__ == "__main__":
    unittest.main()
