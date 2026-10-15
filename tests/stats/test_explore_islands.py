"""T-115 の記述の探索（src/stats/explore_islands.py）のテスト。

実行（プロジェクトのルートで）:
    PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -B -m unittest discover -s tests/stats -v

合成のデータだけを使う。本物の日の集計は読まない。ファイルを書かない（ファイルの読み書きは mock で置き換える）。
"""

import datetime
import fractions
import gzip
import hashlib
import json
import os
import re
import sys
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(os.path.dirname(HERE))
SRC = os.path.join(PROJECT, "src", "stats")
SCRIPT = os.path.join(SRC, "explore_islands.py")
sys.path.insert(0, SRC)

import explore_islands as ex  # noqa: E402

D = datetime.date
DAY = datetime.timedelta(days=1)
F = fractions.Fraction
V = F(1, 543539)


def sha(b):
    return hashlib.sha256(b).hexdigest()


class TestSealedCode(unittest.TestCase):
    def test_loaded_code_matches_pins(self):
        for rel, want in (("src/stats/periods.py", ex.PERIODS_SHA256),
                          ("src/stats/candidates.py", ex.CANDIDATES_SHA256),
                          ("src/stats/counting.py", ex.COUNTING_SHA256),
                          ("src/stats/scoring.py", ex.SCORING_SHA256)):
            with open(os.path.join(PROJECT, rel), "rb") as f:
                self.assertEqual(sha(f.read()), want, rel)
            self.assertEqual(ex._LOADED_SHA[rel], want)

    def test_scoring_uses_verified_candidates(self):
        self.assertIs(ex.scoring.candidates, ex.candidates)
        self.assertIs(ex.candidates.periods, ex.periods)

    def test_load_refuses_wrong_sha(self):
        with self.assertRaises(ex.ExploreError):
            ex._load_verified("x", "src/stats/periods.py", "0" * 64)

    def test_combos_and_constants(self):
        self.assertEqual(len(ex.COMBOS), 21)
        self.assertEqual(ex.MAX_H, 56)
        self.assertEqual(ex.INPUT_LOOKBACK, 371)
        self.assertEqual((ex.BLOCK_START, ex.BLOCK_END), (D(2015, 3, 2), D(2020, 12, 14)))
        self.assertEqual(ex.NEXT_BLOCK_START, D(2020, 12, 15))

    def test_source_has_no_email_like_string(self):
        with open(SCRIPT, "rb") as f:
            self.assertIsNone(ex.EMAIL_RE.search(f.read()))
        with open(os.path.abspath(__file__), "rb") as f:
            self.assertIsNone(ex.EMAIL_RE.search(f.read()))


class TestMondays(unittest.TestCase):
    def test_range(self):
        ms = ex.prediction_mondays()
        self.assertEqual((len(ms), ms[0], ms[-1]), (232, D(2016, 4, 11), D(2020, 9, 14)))
        self.assertTrue(all(m.weekday() == 0 for m in ms))
        self.assertGreaterEqual(ms[0] - datetime.timedelta(days=371), ex.BLOCK_START)
        self.assertLess(ms[-1] + datetime.timedelta(days=56), ex.NEXT_BLOCK_START)


class TestReadGuard(unittest.TestCase):
    def setUp(self):
        self.days = ex.block_days(D(2016, 1, 1), D(2016, 1, 31))
        self.g = ex.ReadGuard(self.days, [0.1] * len(self.days))

    def test_outside_allowed_range_stops(self):
        self.g.allow(D(2016, 1, 5), D(2016, 1, 10))
        self.assertEqual(self.g(D(2016, 1, 5)), 0.1)
        with self.assertRaises(ex.ExploreError):
            self.g(D(2016, 1, 11))
        with self.assertRaises(ex.ExploreError):
            self.g(D(2016, 1, 4))

    def test_outside_block_stops(self):
        self.g.allow(D(2015, 1, 1), D(2017, 1, 1))
        with self.assertRaises(ex.ExploreError):
            self.g(D(2016, 2, 1))

    def test_min_max_tracked(self):
        self.g.allow(D(2016, 1, 1), D(2016, 1, 31))
        self.g(D(2016, 1, 20))
        self.g(D(2016, 1, 3))
        self.assertEqual((self.g.min_read, self.g.max_read), (D(2016, 1, 3), D(2016, 1, 20)))


def synthetic_series(spike_start, spike_days=10, base=1e-5, spike=1e-4, missing=()):
    days = ex.block_days()
    vals = []
    for d in days:
        if d in missing:
            vals.append(None)
        elif spike_start <= d < spike_start + datetime.timedelta(days=spike_days):
            vals.append(spike)
        else:
            vals.append(base)
    return days, vals


class TestEvaluateTag(unittest.TestCase):
    """封印済みの関数を直接呼んだ結果と同じになること。予言日以降の値が入力に入らないこと。"""

    @classmethod
    def setUpClass(cls):
        cls.t = D(2017, 6, 5)                       # 月曜
        cls.ms = [cls.t - 7 * DAY, cls.t, cls.t + 7 * DAY, cls.t + 70 * DAY]
        cls.days, cls.vals = synthetic_series(cls.t + 10 * DAY)
        cls.out, cls.lo, cls.hi = ex.evaluate_tag(cls.days, cls.vals, cls.ms, V)

    def plain(self):
        m = dict(zip(self.days, self.vals))
        return m.__getitem__

    def test_matches_sealed_functions(self):
        f = self.plain()
        for t, (st, b, js, mx) in zip(self.ms, self.out):
            self.assertEqual(st, ex.scoring.target_status(f, t, V))
            if js is None:
                continue
            self.assertEqual(b, ex.candidates.baseline_level(f, t))
            self.assertEqual(js, tuple(ex.candidates.judge(f, t, h, m, b, V) for m, h in ex.COMBOS))

    def test_island_then_cooldown(self):
        st0, b0, js0, mx0 = self.out[1]
        self.assertEqual(st0, "target")
        # 10倍の跳ねが t+10 から10日。判定期間 28 日の最大の7日の平均は 10 × B で、8倍は超え、16倍は超えない
        c = ex.COMBOS.index((8, 28))
        self.assertTrue(js0[c])
        self.assertFalse(js0[ex.COMBOS.index((16, 28))])
        self.assertAlmostEqual(mx0, 1e-4)
        # 跳ねたあとの週は、跳ねが入力に入ると一度跳ねたタグの扱い（cooldown）か上（above_baseline）になる
        self.assertIn(self.out[2][0], ("target",))      # t+7 の入力（t+6 まで）には跳ねがまだ無い
        self.assertEqual(self.out[3][0], "cooldown")     # t+70 の入力には、56日以内の跳ねがある

    def test_reads_stay_in_range(self):
        self.assertEqual(self.lo, self.ms[0] - datetime.timedelta(days=371))
        self.assertLessEqual(self.hi, self.ms[-1] + datetime.timedelta(days=56))

    def test_inputs_do_not_use_future(self):
        """予言日 t 以降の値をすべて変えても、t の状態と B(t) は同じ。"""
        t = self.t
        vals2 = [v if d < t else 9e-3 for d, v in zip(self.days, self.vals)]
        out2, _lo, _hi = ex.evaluate_tag(self.days, vals2, [t], V)
        self.assertEqual(out2[0][0], self.out[1][0])
        self.assertEqual(out2[0][1], self.out[1][1])

    def test_judgment_does_not_read_past_horizon(self):
        """t+57 以降の値を変えても、t の判定は同じ。"""
        t = self.t
        vals2 = [v if d <= t + 56 * DAY else 9e-3 for d, v in zip(self.days, self.vals)]
        out2, _lo, _hi = ex.evaluate_tag(self.days, vals2, [t], V)
        self.assertEqual(out2[0], self.out[1])

    def test_missing_days_make_undecidable(self):
        t = self.t
        miss = set(ex.block_days(t + DAY, t + 56 * DAY))
        days, vals = synthetic_series(D(2019, 1, 1), missing=miss)
        out, _lo, _hi = ex.evaluate_tag(days, vals, [t], V)
        self.assertEqual(out[0][0], "target")
        self.assertTrue(all(j is None for j in out[0][2]))


def handmade_results():
    """2つのタグ、3つの予言日。js は21組の判定。"""
    ms = [D(2016, 4, 11), D(2016, 4, 18), D(2017, 1, 2)]
    nc = len(ex.COMBOS)

    def js(island_m, h_ok=(14, 28, 56), none=False):
        if none:
            return tuple([None] * nc)
        return tuple((m <= island_m and h in h_ok) for m, h in ex.COMBOS)
    a = [("target", 1e-5, js(4), 5e-5), ("cooldown", 1e-5, js(8), 9e-5), ("target", 0.0, js(16), 3e-5)]
    b = [("above_baseline", None, None, None), ("target", 2e-5, js(0), 2e-5), ("target", 1e-5, js(0, none=True), None)]
    return ["AAA", "BBB"], [a, b], ms


class TestAggregate(unittest.TestCase):
    def setUp(self):
        self.tags, self.res, self.ms = handmade_results()
        self.agg = ex.aggregate(self.tags, self.res, self.ms)

    def cell(self, v, m, h, i):
        return self.agg["weekly"][v][ex.COMBOS.index((m, h))][i]

    def test_cooldown_variant_excludes_cooldown_status(self):
        self.assertEqual(self.cell("cooldown", 2, 28, 1), [1, 0, 0])      # AAA は cooldown で外れ、BBB は島でない
        self.assertEqual(self.cell("no_cooldown", 2, 28, 1), [2, 1, 0])   # 参考では AAA も入る

    def test_undecidable_counted_separately(self):
        self.assertEqual(self.cell("cooldown", 2, 14, 2), [1, 1, 1])

    def test_combo_rows_and_years(self):
        rows = ex.combo_rows(self.agg, self.ms)
        r = [x for x in rows if x[:4] == ("cooldown", 4, 28, "all")][0]
        # 対象 3（i0 の AAA、i1 の BBB、i2 の AAA）、島 2（i0 の AAA、i2 の AAA）、判定不能 1
        self.assertEqual(r[4:], (3, 3, 2, 1, "66.67", 1))
        r16 = [x for x in rows if x[:4] == ("cooldown", 16, 28, "2016")][0]
        self.assertEqual(r16[4:], (2, 2, 0, 0, "0.00", 0))

    def test_monotone_check(self):
        tags, res, ms = handmade_results()
        bad = list(res[0])
        js = list(bad[0][2])
        js[ex.COMBOS.index((16, 14))] = True
        js[ex.COMBOS.index((12, 14))] = False
        bad[0] = (bad[0][0], bad[0][1], tuple(js), bad[0][3])
        with self.assertRaises(ex.ExploreError):
            ex.aggregate(tags, [bad, res[1]], ms)

    def test_examples_split_zero_baseline(self):
        exr, zero = ex.example_rows(self.agg, self.ms)
        r2016 = [r for r in exr if r[0] == 2 and r[2] == 2016]
        self.assertEqual([(r[4], r[5], r[8]) for r in r2016], [("AAA", "2016-04-11", "5.00")])
        z2017 = [r for r in zero if r[0] == 2 and r[2] == 2017]
        self.assertEqual(z2017[0][3:5], ("count", 1))
        self.assertEqual(z2017[1][5:7], ("AAA", "2017-01-02"))

    def test_top_weeks_and_clusters(self):
        tw = ex.top_week_rows(self.agg, self.ms)
        self.assertEqual(len([r for r in tw if r[0] == 2]), 3)
        cl = ex.cluster_rows(self.agg, self.ms)
        self.assertEqual(len(cl), 21)

    def test_week_status(self):
        rows = ex.week_status_rows(self.agg, self.ms)
        self.assertEqual(rows[0][1], "has_targets")
        self.assertEqual(rows[0][2:], (1, 0, 0, 1, 0))


class TestFamiliesAndWindows(unittest.TestCase):
    def test_family(self):
        self.assertEqual(ex.family("TAX_FNCACT_ARTISAN"), "TAX_FNCACT")
        self.assertEqual(ex.family("WB_2121_ICT_LICENSING"), "WB")
        self.assertEqual(ex.family("AFFECT"), "AFFECT")
        self.assertEqual(ex.family("TAX"), "TAX")

    def test_family_counts(self):
        tags, res, ms = handmade_results()
        agg = ex.aggregate(tags, res, ms)
        rows = [r for r in ex.family_rows(agg) if r[2] == 4 and r[3] == 28]
        self.assertEqual([r[:2] for r in rows], [("AAA", 1), ("BBB", 1)])
        self.assertEqual(rows[0][4:], (2, 2, "100.00", 1))   # AAA：対象 2（i0・i2）、島 2
        self.assertEqual(rows[1][4:], (1, 0, "0.00", 0))     # BBB：対象 1（i1）。i2 は判定不能

    def test_window_missing_rows(self):
        t = D(2020, 9, 14)
        miss = {D(2020, 9, 28)} | set(ex.block_days(D(2020, 10, 3), D(2020, 11, 9)))
        rows = ex.window_missing_rows([D(2016, 4, 11), t], miss)
        # 判定期間 14 日（9-15〜9-28）：終わりが 9-21〜9-28 の8つのまとまりのうち、9-28 を含む 9-28 で終わる1つが使えない
        self.assertIn((14, "2020-09-14", 7, 8), rows)
        self.assertFalse(any(r[1] == "2016-04-11" for r in rows))
        r56 = [r for r in rows if r[0] == 56][0]
        self.assertEqual(r56[3], 50)
        self.assertLess(r56[2], 50)


class TestOutputs(unittest.TestCase):
    def ctx(self):
        tags, res, ms = handmade_results()
        c = {"tags": tags, "v": V, "missing": {D(2015, 5, 29)}, "partial_days_count": 3,
             "refs": {"ledger_records": 17}}
        return c, res, ms

    def test_deterministic_and_clean(self):
        c, res, ms = self.ctx()
        a = ex.build_outputs(c, res, ms, D(2015, 4, 6), D(2017, 2, 27), 2115)
        b = ex.build_outputs(c, res, ms, D(2015, 4, 6), D(2017, 2, 27), 2115)
        self.assertEqual(a, b)
        self.assertEqual(sorted(a), sorted(ex.OUT_NAMES))
        self.assertIn(ex.CITATION_EN.encode("utf-8"), a["summary.md"])
        self.assertIn(ex.CITATION_JA.encode("utf-8"), a["summary.md"])
        for n, d in a.items():
            self.assertIsNone(ex.EMAIL_RE.search(d), n)
        self.assertNotIn(b"/Volumes", a["run.json"])

    def test_check_public(self):
        with self.assertRaises(ex.ExploreError):
            ex.check_public("x", b"name" + b"\x40" + b"example.org")
        with self.assertRaises(ex.ExploreError):
            ex.check_public("x", b"see https://example.org/a")
        ex.check_public("x", ex.CITATION_EN.encode("utf-8"))

    def test_write_refuses_existing(self):
        with mock.patch.object(ex.os, "makedirs"), mock.patch.object(ex.os.path, "lexists", return_value=True), \
                mock.patch.object(ex.os, "open") as op:
            with self.assertRaises(ex.ExploreError):
                ex.write_outputs("/nonexistent-dir", {n: b"" for n in ex.OUT_NAMES})
            op.assert_not_called()


class TestLedgerAndManifest(unittest.TestCase):
    def chain(self, recs):
        prev = "0" * 64
        lines = []
        for i, r in enumerate(recs, 1):
            r = dict(r, seq=i, prev_hash=prev)
            line = ex.canonical_line(r)
            prev = sha(line)
            lines.append(line)
        return b"\n".join(lines) + b"\n"

    def test_verify_ledger(self):
        data = self.chain([{"kind": "a"}, {"kind": "b"}, {"kind": "c"}])
        recs, hashes = ex.verify_ledger(data)
        self.assertEqual([r["kind"] for r in recs], ["a", "b", "c"])
        self.assertEqual(hashes[0], sha(data.split(b"\n")[0]))
        with self.assertRaises(ex.ExploreError):
            ex.verify_ledger(data.replace(b'"kind":"a"', b'"kind":"x"'))
        with self.assertRaises(ex.ExploreError):
            lines = data.split(b"\n")
            ex.verify_ledger(b"\n".join([lines[0], lines[2]]) + b"\n")

    def manifest(self, days, extra=()):
        rid = "0123456789abcdef"
        rows = [{"kind": "run-start", "run_id": rid}]
        for d in list(days) + list(extra):
            k = d.isoformat()
            rows.append({"kind": "day", "mode": "official", "run_id": rid, "day": k,
                         "file_name": ex.counting.day_file_name("official", rid, k), "sha256": "a" * 64})
        return rid, b"".join(json.dumps(r).encode() + b"\n" for r in rows)

    def test_day_rows(self):
        days = ex.block_days()
        rid, body = self.manifest(days)
        rows = ex.day_rows_from_manifest(ex.manifest_prefix(body, body.count(b"\n")), rid, days)
        self.assertEqual(len(rows), 2115)

    def test_day_rows_after_block_stop(self):
        days = ex.block_days()
        rid, body = self.manifest(days, extra=[D(2020, 12, 15)])
        with self.assertRaises(ex.ExploreError):
            ex.day_rows_from_manifest(body, rid, days)

    def test_day_rows_missing_day_stop(self):
        days = ex.block_days()
        rid, body = self.manifest(days[1:])
        with self.assertRaises(ex.ExploreError):
            ex.day_rows_from_manifest(body, rid, days)

    def test_manifest_prefix(self):
        self.assertEqual(ex.manifest_prefix(b"a\nb\nc\n", 2), b"a\nb\n")
        with self.assertRaises(ex.ExploreError):
            ex.manifest_prefix(b"a\nb\n", 3)

    def test_order4_sha_checked(self):
        lst = {"block": {"name": "method", "start": "2015-03-02", "end": "2020-12-14"}}
        doc = {"list": lst, "list_sha256": "0" * 64}
        with self.assertRaises(ex.ExploreError):
            ex.check_order4(doc, "r", {"manifest_sha256": "m"}, ex.block_days())

    def test_order5_sha_checked(self):
        with self.assertRaises(ex.ExploreError):
            ex.check_order5({"main": {"a": 1}, "main_sha256": "0" * 64}, ["0" * 64] * 17, "x")


def day_gz(day, themes):
    """counting.parse_day が読む形（gkg-day 版3）の合成の日の集計。themes：{名前: (組, v1, v2, v2m, v12)}。"""
    names = sorted(themes)
    lines = ["#\tgkg-day\t3\t%s\tofficial" % day]
    for i, n in enumerate(names):
        lines.append("V\t%d\t%s" % (i, n))
    lines.append("D\t1\t100")
    lines.append("D\t1T\t100")
    for i, n in enumerate(names):
        g, a, b, c, d = themes[n]
        lines.append("T\t%s\t%d\t%d\t%d\t%d\t%d" % (g, i, a, b, c, d))
    return gzip.compress(("\n".join(lines) + "\n").encode("ascii"), mtime=0)


class TestReadDay(unittest.TestCase):
    def test_c7_counts(self):
        data = day_gz("2016-01-01", {"AAA": ("1", 3, 4, 5, 6), "BBB": ("1", 1, 0, 0, 1), "CCC": ("1T", 9, 9, 9, 9)})
        with mock.patch.object(ex, "read_nofollow", return_value=data) as rd:
            total, vec = ex.read_day("2016-01-01", "f.tsv.gz", sha(data), "/store", ("AAA", "CCC", "ZZZ"))
        rd.assert_called_once_with(os.path.join("/store", "f.tsv.gz"))
        self.assertEqual(total, 7)                    # 翻訳の組 1T は数えない
        self.assertEqual(vec, [6, 0, 0])

    def test_sha_mismatch_stops(self):
        data = day_gz("2016-01-01", {"AAA": ("1", 1, 1, 1, 1)})
        with mock.patch.object(ex, "read_nofollow", return_value=data):
            with self.assertRaises(ex.ExploreError):
                ex.read_day("2016-01-01", "f.tsv.gz", "0" * 64, "/store", ("AAA",))

    def test_after_block_not_opened(self):
        with mock.patch.object(ex, "read_nofollow") as rd:
            with self.assertRaises(ex.ExploreError):
                ex.read_day("2020-12-15", "f.tsv.gz", "0" * 64, "/store", ("AAA",))
            rd.assert_not_called()

    def test_bad_file_name(self):
        with self.assertRaises(ex.ExploreError):
            ex.read_day("2016-01-01", "../f.tsv.gz", "0" * 64, "/store", ("AAA",))


class TestLoadRatios(unittest.TestCase):
    def test_missing_and_denominator(self):
        days = ex.block_days()
        miss = {days[3]}
        rows = {d.isoformat(): {"file_name": "f%d" % i, "sha256": "s"} for i, d in enumerate(days)}
        ctx = {"days": days, "rows": rows, "tags": ["AAA", "BBB"], "missing": miss,
               "denom": {d.isoformat(): 10 for d in days}}
        with mock.patch.object(ex, "read_day", return_value=(10, [2, 0])):
            series, n = ex.load_ratios(ctx, "/store", 1)
        self.assertEqual(n, 2115)
        self.assertEqual(series[0][0], 0.2)
        self.assertIsNone(series[0][3])
        self.assertEqual(series[1][5], 0.0)
        ctx["denom"][days[7].isoformat()] = 11
        with mock.patch.object(ex, "read_day", return_value=(10, [2, 0])):
            with self.assertRaises(ex.ExploreError):
                ex.load_ratios(ctx, "/store", 1)


if __name__ == "__main__":
    unittest.main()
