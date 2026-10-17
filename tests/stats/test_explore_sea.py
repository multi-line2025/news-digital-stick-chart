"""T-125 の海域ごとの波の性状と見落とした島（src/stats/explore_sea.py）のテスト。

実行（プロジェクトのルートで）:
    PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -B -m unittest discover -s tests/stats -v

合成のデータだけを使う。本物の日の集計とキャッシュは読まない。ファイルを書かない。
"""

import datetime
import fractions
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
SCRIPT = os.path.join(SRC, "explore_sea.py")
sys.path.insert(0, SRC)

import explore_sea as sea  # noqa: E402

ei = sea.ei
D = datetime.date
DAY = datetime.timedelta(days=1)
V = fractions.Fraction(1, 543539)


class TestSeas(unittest.TestCase):
    def test_family_seas(self):
        tags = ["AA_%d" % i for i in range(20)] + ["BB_1", "CC_1"]
        s = sea.family_seas(tags)
        self.assertEqual(s[0], "AA")
        self.assertEqual(s[-1], "その他")

    def test_community_seas(self):
        months = [[5, 5, 7] + [9] * 10, [5, 7, 7] + [9] * 10, [5, 7, 5] + [9] * 10]
        s = sea.community_seas(months, 13)
        self.assertEqual(s[3], "群れ01")                 # 10個の群れ（ラベル 9）が一番大きい
        self.assertEqual(s[0], "小さな群れ")
        self.assertEqual(s[2], "小さな群れ")

    def test_no_email(self):
        for p in (SCRIPT, os.path.abspath(__file__)):
            with open(p, "rb") as f:
                self.assertIsNone(ei.EMAIL_RE.search(f.read()))


class TestLevels(unittest.TestCase):
    def test_week_starts(self):
        w = sea.week_starts()
        self.assertEqual(w[0], ei.BLOCK_START)
        self.assertLessEqual(w[-1] + 6 * DAY, ei.BLOCK_END)
        self.assertEqual(len(w), 302)

    def test_weekly_levels(self):
        days = ei.block_days(D(2015, 3, 2), D(2015, 3, 15))
        vals = [1e-5] * 7 + [None] * 7
        self.assertEqual(sea.weekly_levels(vals, days, 0.0, [D(2015, 3, 2), D(2015, 3, 9)]),
                         [math.log(1e-5), None])

    def test_season_and_trend_and_step(self):
        weeks = sea.week_starts()
        seasonal = [math.sin(2 * math.pi * sea.week_of_year(w) / 52) for w in weeks]
        st, sim = sea.season_stats(seasonal, weeks)
        self.assertGreater(st, 0.95)
        self.assertGreater(sim, 0.95)
        noise = random.Random(1)
        rnd = [noise.gauss(0, 1) for _ in weeks]
        st2, sim2 = sea.season_stats(rnd, weeks)
        self.assertLess(sim2, 0.3)
        lin = [(w - ei.BLOCK_START).days / 365.25 * 0.5 for w in weeks]
        self.assertAlmostEqual(sea.trend_per_year(lin, weeks), 0.5)
        stepped = [0.0] * 150 + [1.0] * 152
        self.assertAlmostEqual(sea.step_size(stepped), 1.0)
        self.assertIsNone(sea.step_size([None] * 302))

    def test_common_flow(self):
        rng = random.Random(2)
        base = [rng.gauss(0, 1) for _ in range(50)]
        levels = {0: base, 1: [x + 1 for x in base], 2: [rng.gauss(0, 1) for _ in range(50)]}
        f = sea.common_flow(levels, [0, 1, 2])
        self.assertGreater(f[0], f[2])


class TestIslandsAfter(unittest.TestCase):
    def test_after_and_back(self):
        days = ei.block_days()
        pos = {d: k for k, d in enumerate(days)}
        vals = [1e-5] * len(days)
        t = D(2018, 1, 1)
        self.assertAlmostEqual(sea.after_level(vals, pos, t), 1e-5)
        self.assertIsNone(sea.after_level(vals, pos, D(2020, 9, 14)))       # t+180 が区画の外
        self.assertEqual(sea.back_or_stay(1e-5, 1e-5, V), "back")
        self.assertEqual(sea.back_or_stay(3e-5, 1e-5, V), "stay")
        self.assertEqual(sea.back_or_stay(None, 1e-5, V), "unknown")
        vals2 = list(vals)
        for k in range(10, 17):
            vals2[pos[t + k * DAY]] = 8e-5
        self.assertAlmostEqual(sea.jump_size(vals2, pos, t, 1e-5), 8.0)
        self.assertIsNone(sea.jump_size(vals2, pos, t, 0.0))


def synthetic_rows(seed=3, per_week=15):
    rng = random.Random(seed)
    ms = ei.prediction_mondays()
    rows = {}
    for ti in range(0, len(ms), 2):
        for i in range(per_week):
            b = rng.random() * 1e-5 + 1e-6
            lv = {"B": b, "c": b * rng.random(), "P": b, "S0": b * 2 * rng.random(), "S35": b * 3 * rng.random()}
            x = rng.random() + 0.3 * (lv["S0"] / b)
            rows[(ti, i)] = ((x > 0.9, x > 1.1, x > 1.25), lv)
    return rows, ms


class TestNaive(unittest.TestCase):
    def test_yearly_split_and_missed(self):
        rows, ms = synthetic_rows()
        tags = ["T%02d" % i for i in range(15)]
        keys = sorted(rows)
        models = sea.yearly_naive(rows, keys, ms, tags, V)
        for (y, m), md in models.items():
            self.assertLess(D.fromisoformat(md["train_last"]) + 28 * DAY, D(y, 1, 1))
            self.assertTrue(all(ms[k[0]].year == y for k in md["probs"]))
            fl = sea.missed_flags(md, rows, m)
            mi = sea.MULTIPLIERS.index(m)
            self.assertTrue(all(rows[k][0][mi] for k in fl))
            for k, f in fl.items():
                p = md["probs"][k]
                self.assertEqual(f[0], p < md["base"])
                self.assertEqual(f[2], p < md["base"] / 2)

    def test_names_in_text(self):
        self.assertEqual(sea.names_in_text("AA と ZZ_1 の話", ["ZZ_1", "AA"], {"AA"}), ["ZZ_1"])


class TestOutputs(unittest.TestCase):
    def test_build(self):
        rows, ms = synthetic_rows()
        tags = ["AA_%02d" % i for i in range(15)]
        keys = sorted(rows)
        seas = {"family": ["AA"] * 10 + ["その他"] * 5, "community": ["群れ01"] * 12 + ["小さな群れ"] * 3}
        rng = random.Random(5)
        tag_info = [{"rough": rng.random(), "season": rng.random(), "similar": rng.random(), "trend": rng.gauss(0, 0.1),
                     "step": 0.1, "has_step": i % 3 == 0, "rates": {2: 0.1, 4: 0.05, 8: 0.01}, "targets": 10,
                     "flow_family": 0.2, "flow_community": 0.1} for i in range(15)]
        storm = sea.storms(rows, keys, ms, seas)
        island_extra = {k: {"after": ["back", "stay", "unknown"][k[0] % 3], "jump": 3.0} for k in keys if any(rows[k][0])}
        models = sea.yearly_naive(rows, keys, ms, tags, V)
        missed = {(y, m): sea.missed_flags(models[(y, m)], rows, m) for y in sea.MISS_YEARS for m in sea.MULTIPLIERS}
        ctx = {"refs": {}, "v": V}
        f1 = sea.build_outputs(tags, ms, rows, keys, seas, tag_info, storm, island_extra, models, missed, ctx)
        f2 = sea.build_outputs(tags, ms, rows, keys, seas, tag_info, storm, island_extra, models, missed, ctx)
        self.assertEqual(f1, f2)
        self.assertEqual(sorted(f1), sorted(sea.OUT_NAMES))
        s = f1["summary.md"].decode("utf-8")
        self.assertNotIn("**", s)
        self.assertNotIn("AA_01", s)
        self.assertTrue(f1["tags-private.tsv"].startswith(sea.PRIVATE_HEADER.encode("utf-8")))
        self.assertTrue(f1["missed-private.tsv"].startswith(sea.PRIVATE_HEADER.encode("utf-8")))
        self.assertIn(b"AA_01", f1["tags-private.tsv"])
        for n in ("seas.tsv", "storms.tsv", "naive_coefs.tsv", "missed.tsv", "run.json"):
            self.assertNotIn(b"AA_0", f1[n], n)
        for phrase in ("海域ごとのやさしい説明", "見落とした島", "季節風（毎年同じ時期に来る波）", ei.CITATION_JA):
            self.assertIn(phrase, s)
        self.assertLess(s.index("海域ごとのやさしい説明"), s.index("海域の表"))
        for n, d in f1.items():
            self.assertIsNone(ei.EMAIL_RE.search(d), n)
        # T-126
        self.assertEqual(sea.LABEL, "explore-sea-t125-v2")
        self.assertNotIn("%%", s)
        self.assertIn("下位25%", s)
        self.assertIn("v1 の季節風の言い方は海域どうしの三分位で、偶然の水準を考えていなかったため、偶然の水準と比べる形に替えた"
                      "（表の sha256 は v1 と同じ）", s)
        self.assertIn("海域として載せた系統の名前を除く。系統の名前 2 個のうち 0 個は、一覧に同じ名前のテーマがある", s)
        self.assertIn("素朴な予測が平均より低い確率を付けた", s)
        self.assertIn("近似的な対応", s)
        null = sea.null_levels(sea.week_starts())
        self.assertIn("%.3f（種類ごとの90%%点のうち最も大きいもの）" % null["season"], s)
        for w in ("季節風は弱い", "季節風は強い", "季節風はふつう", "毎年ほぼ同じ形"):
            self.assertNotIn(w, s)
        self.assertIn("null_levels", f1["run.json"].decode("utf-8"))

    def test_null_levels_and_wording(self):
        weeks = sea.week_starts()
        a, b = sea.null_levels(weeks), sea.null_levels(weeks)
        self.assertEqual(a, b)
        self.assertEqual(sorted(a["kinds"]), sorted(sea.NULL_KINDS))
        for k in sea.NULL_KINDS:
            self.assertEqual(len(a["kinds"][k]["season"]), sea.NULL_N)
        self.assertEqual(a["season"], max(sea.nearest_rank(a["kinds"][k]["season"], sea.NULL_Q) for k in sea.NULL_KINDS))
        base = {"rough": 0.5, "trend": 0.0, "flow": 0.2, "step_share": 0.0, "rate_4": 0.05, "islands_4": 3, "back_4": 1, "stay_4": 1}
        rows = [dict(base, season=0.1 * i, similar=0.05 * i, rough=0.1 * i, rate_4=0.01 * i) for i in range(10)]
        lo = sea.plain_sentence(dict(base, season=a["season"], similar=a["similar"]), rows, a)
        self.assertIn("季節風（毎年同じ時期に来る波）は見分けられない", lo)
        self.assertIn("年ごとの形の似かたは見分けられない", lo)
        hi = sea.plain_sentence(dict(base, season=a["season"] + 0.01, similar=a["similar"] + 0.01), rows, a)
        self.assertIn("偶然の水準（%.3f）を超えていて" % a["season"], hi)
        self.assertIn("年ごとの形は偶然の水準（%.3f）より似ている" % a["similar"], hi)

    def test_write_refuses_existing(self):
        with mock.patch.object(sea.os, "makedirs"), mock.patch.object(sea.os.path, "lexists", return_value=True), \
                mock.patch.object(sea.os, "open") as op:
            with self.assertRaises(sea.SeaError):
                sea.write_outputs("/nonexistent", {n: b"" for n in sea.OUT_NAMES})
            op.assert_not_called()


if __name__ == "__main__":
    unittest.main()
