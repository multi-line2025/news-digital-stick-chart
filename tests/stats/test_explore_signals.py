"""T-117 の三つの信号の探索（src/stats/explore_signals.py）のテスト。

実行（プロジェクトのルートで）:
    PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -B -m unittest discover -s tests/stats -v

合成のデータだけを使う。本物の日の集計は読まない。ファイルを書かない（読み書きは mock で置き換える）。
"""

import array
import datetime
import fractions
import gzip
import hashlib
import json
import math
import os
import pickle
import random
import sys
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(os.path.dirname(HERE))
SRC = os.path.join(PROJECT, "src", "stats")
SCRIPT = os.path.join(SRC, "explore_signals.py")
sys.path.insert(0, SRC)

import explore_signals as es  # noqa: E402

ei = es.ei
D = datetime.date
DAY = datetime.timedelta(days=1)
F = fractions.Fraction
V = F(1, 543539)


class TestCode(unittest.TestCase):
    def test_naive_pinned(self):
        with open(os.path.join(PROJECT, "src", "stats", "naive.py"), "rb") as f:
            self.assertEqual(hashlib.sha256(f.read()).hexdigest(), es.NAIVE_SHA256)
        self.assertIs(es.naive.candidates, ei.candidates)

    def test_no_email_like(self):
        for p in (SCRIPT, os.path.abspath(__file__)):
            with open(p, "rb") as f:
                self.assertIsNone(ei.EMAIL_RE.search(f.read()))

    def test_model_specs(self):
        specs = es.model_specs(False)
        names = [n for n, _c in specs]
        self.assertEqual(len(specs), 1 + 6 + 2 + 12 + 6)
        self.assertEqual(len(set(names)), len(names))
        self.assertEqual(names[0], "naive")
        self.assertFalse(any("language" in n for n in names))


class TestDates(unittest.TestCase):
    def test_months(self):
        self.assertEqual(es.add_months(201601, -1), 201512)
        self.assertEqual(es.add_months(201512, 1), 201601)
        self.assertEqual(es.month_last(201602), D(2016, 2, 29))

    def test_network_months_monthly(self):
        t = D(2016, 4, 11)
        ms = es.network_months(t, 12, "M")
        self.assertEqual(ms, [201504, 201505, 201506, 201507, 201508, 201509, 201510, 201511, 201512,
                              201601, 201602, 201603])
        self.assertLess(es.check_network_before(t, ms), 0)

    def test_network_months_quarterly(self):
        t = D(2016, 5, 30)
        self.assertEqual(es.network_months(t, 3, "Q"), [201601, 201602, 201603])
        self.assertEqual(es.network_months(t, 3, "M"), [201602, 201603, 201604])

    def test_network_clipped_at_block_start(self):
        self.assertEqual(es.network_months(D(2015, 5, 4), 12, "M"), [201503, 201504])

    def test_network_after_t_stops(self):
        with self.assertRaises(es.SignalError):
            es.check_network_before(D(2016, 4, 11), [201604])

    def test_all_prediction_networks_before_t(self):
        for t in ei.prediction_mondays():
            for _n, w, r in es.NETWORKS:
                self.assertLess(es.check_network_before(t, es.network_months(t, w, r)), 0)

    def test_lead_weeks(self):
        for t in ei.prediction_mondays():
            rec, base = es.lead_weeks(t)
            self.assertEqual(es.week_last_day(rec), t - DAY)
            self.assertEqual(len(base), 52)
            self.assertEqual(base[-1] + 1, rec)
        with self.assertRaises(es.SignalError):
            es.lead_weeks(D(2016, 4, 12))


def day_gz(day, vocab, t_rows=(), c_rows=(), p_rows=(), nc_rows=(), l_rows=(), nl_rows=(), d_rows=(("1", 100),)):
    lines = ["#\tgkg-day\t3\t%s\tofficial" % day]
    for i, n in enumerate(vocab):
        lines.append("V\t%d\t%s" % (i, n))
    for g, k in d_rows:
        lines.append("D\t%s\t%d" % (g, k))
    for r in t_rows:
        lines.append("T\t" + "\t".join(str(x) for x in r))
    for r in c_rows:
        lines.append("C\t" + "\t".join(str(x) for x in r))
    for r in l_rows:
        lines.append("L\t" + "\t".join(str(x) for x in r))
    for r in p_rows:
        lines.append("P1\t" + "\t".join(str(x) for x in r))
    for r in nc_rows:
        lines.append("NC\t" + "\t".join(str(x) for x in r))
    for r in nl_rows:
        lines.append("NL\t" + "\t".join(str(x) for x in r))
    return gzip.compress(("\n".join(lines) + "\n").encode("ascii"), mtime=0)


class TestParseExtra(unittest.TestCase):
    def test_counts(self):
        vocab = ["AAA", "BBB", "ZZZ", "CCC"]
        tag_index = {"AAA": 0, "BBB": 1, "CCC": 2}
        data = day_gz("2016-01-01", vocab,
                      t_rows=[("1", 0, 5, 3, 4, 6), ("1T", 0, 9, 9, 9, 9), ("1", 2, 7, 7, 7, 7)],
                      c_rows=[("1", 0, "US", 2, 3, 4), ("1T", 0, "US", 9, 9, 9), ("1", 1, "FR", 4, 1, 1),
                              ("1", 0, "XX", 5, 5, 5)],
                      p_rows=[("1", 0, 1, 3), ("1T", 0, 1, 9), ("1", 0, 2, 4), ("1", 1, 3, 2)],
                      nc_rows=[("1", "US", 50), ("1T", "US", 70), ("1", "FR", 20)],
                      l_rows=[("1", 0, "-", 1, 1, 1)], nl_rows=[("1", "-", 3)],
                      d_rows=[("1", 100), ("1T", 40)])
        n = 3
        pairs = array.array("I", bytes(4 * n * n))
        ex = es.parse_extra(data, tag_index, {"US": 0, "FR": 1}, pairs, n)
        self.assertEqual(ex["v1"], [5, 0, 0])
        self.assertEqual(ex["docs"], 100)
        self.assertEqual(ex["c"], {0 * 2 + 0: 3, 1 * 2 + 1: 4})
        self.assertEqual(ex["nc"], {"US": 50, "FR": 20})
        self.assertEqual(ex["lang_rows"], 0)
        self.assertEqual(pairs[0 * 3 + 1], 3)
        self.assertEqual(pairs[1 * 3 + 0], 3)
        self.assertEqual(pairs[1 * 3 + 2], 2)          # BBB と CCC（日の番号 1 と 3）
        self.assertEqual(sum(pairs), 10)               # ZZZ（一覧に無い）の組と翻訳の組は数えない

    def test_lang_rows_counted(self):
        data = day_gz("2016-01-01", ["AAA"], l_rows=[("1", 0, "spa", 1, 1, 1)], nl_rows=[("1", "spa", 3)])
        self.assertEqual(es.parse_extra(data, {"AAA": 0}, None)["lang_rows"], 2)

    def test_after_block_not_opened(self):
        es._W["store"] = "/store"
        with mock.patch.object(ei, "read_nofollow") as rd:
            with self.assertRaises(es.SignalError):
                es._read_verified("2020-12-15", "f.tsv.gz", "0" * 64)
            rd.assert_not_called()

    def test_sha_mismatch(self):
        es._W["store"] = "/store"
        with mock.patch.object(ei, "read_nofollow", return_value=b"abc"):
            with self.assertRaises(es.SignalError):
                es._read_verified("2016-01-01", "f.tsv.gz", "0" * 64)

    def test_choose_countries(self):
        tot = {"US": 10, "UK": 10, "FR": 5}
        with mock.patch.object(es, "TOP_COUNTRIES", 2):
            self.assertEqual(es.choose_countries(tot), ["UK", "US"])


class TestNeighbors(unittest.TestCase):
    def test_lift_and_share(self):
        n = 4
        m = [0] * 16

        def put(i, j, x):
            m[i * n + j] = x
            m[j * n + i] = x
        put(0, 1, 100)   # 1 は大きいテーマ
        put(0, 2, 30)    # 2 は小さいテーマ
        put(0, 3, 10)    # MIN_PAIR_DOCS 未満
        marg = [200, 10000, 40, 50]
        out = es.neighbors_from_matrix(array.array("I", m), n, marg, 100000)
        lift = out["lift10"].get(0)
        share = out["share30"].get(0)
        self.assertEqual([j for j, _w, _s in lift], [2, 1])     # lift：30*1e5/(200*40) > 100*1e5/(200*1e4)
        self.assertEqual([j for j, _w, _s in share], [1, 2])    # share：100/200 > 30/200
        self.assertAlmostEqual(lift[0][1], 30 / 200)
        self.assertAlmostEqual(lift[0][2], 30 / 40)
        self.assertEqual(out["lift10"].get(3), [])

    def test_nbrs_pickle(self):
        nb = es.Nbrs([[(1, 0.5, 0.25)], [], [(0, 1.0, 2.0), (2, 0.1, 0.2)]])
        nb2 = pickle.loads(pickle.dumps(nb))
        self.assertEqual(nb2.get(2), [(0, 1.0, 2.0), (2, 0.1, 0.2)])
        self.assertEqual(nb2.get(1), [])


class TestSignals(unittest.TestCase):
    def test_neighbor_signal(self):
        nbrs = [(1, 1.0, 0.5), (2, 3.0, 0.5), (3, 2.0, 0.5)]
        rises = [0.0, 1.0, 2.0, None]
        trends = [0.0, None, None, None]
        nr, nt = es.neighbor_signal(nbrs, rises, trends)
        self.assertAlmostEqual(nr, (1.0 + 6.0) / 4.0)
        self.assertIsNone(nt)

    def test_expect_signal(self):
        v = 1e-9
        cur = [2e-5, 4e-5, None]
        win = [1e-5, 2e-5, 1e-5]
        x = es.expect_signal(0, [(1, 1.0, 0.5), (2, 1.0, 0.5)], cur, win, v)
        # 期待値 = 1e-5 × (0.5×4e-5) / (0.5×2e-5) = 2e-5 → log(1) = 0
        self.assertAlmostEqual(x, 0.0, places=6)
        self.assertIsNone(es.expect_signal(0, [], cur, win, v))

    def test_lead_signal(self):
        n, U, W = 1, 2, 60
        weekc = array.array("I", bytes(4 * n * U * W))
        weeknc = [[100, 100] for _ in range(W)]
        for w in range(W):
            weekc[w * U + 0] = 1
            weekc[w * U + 1] = 1
        weekc[55 * U + 0] = 8                          # 国0 が直近の週に8倍
        cumc, cumn = es.cumulative_weeks(weekc, weeknc, n, U)
        rec, base = 55, list(range(3, 55))
        lm, lf = es.lead_signal(0, rec, base, cumc, cumn, n, U, 0.0)
        tot = math.log((9 / 200) / (104 / 10400))
        self.assertAlmostEqual(lm, math.log(8) - tot)
        self.assertAlmostEqual(lf, 0.5)
        with self.assertRaises(es.SignalError):
            es.lead_signal(0, rec, base[:-1], cumc, cumn, n, U, 0.0)

    def test_lead_none_when_absent(self):
        n, U, W = 2, 1, 60
        weekc = array.array("I", bytes(4 * n * U * W))
        weeknc = [[100] for _ in range(W)]
        cumc, cumn = es.cumulative_weeks(weekc, weeknc, n, U)
        self.assertEqual(es.lead_signal(1, 55, list(range(3, 55)), cumc, cumn, n, U, 0.0), (None, None))


def synthetic_series(spike_start, base=1e-5, spike=1e-4, spike_days=10):
    days = ei.block_days()
    vals = [spike if spike_start <= d < spike_start + datetime.timedelta(days=spike_days) else base for d in days]
    return days, vals


class TestEvaluateTag(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.t = D(2017, 6, 5)
        cls.days, cls.vals = synthetic_series(cls.t + 10 * DAY)
        cls.out, cls.lo, cls.hi = es.evaluate_tag(cls.days, cls.vals, [cls.t], V)

    def test_matches_sealed_functions(self):
        f = dict(zip(self.days, self.vals)).__getitem__
        st, b, c, m1, m2, js, lv = self.out[0]
        self.assertEqual(st, ei.scoring.target_status(f, self.t, V))
        self.assertEqual(b, ei.candidates.baseline_level(f, self.t))
        self.assertEqual(c, ei.candidates.current_level(f, self.t))
        self.assertEqual(js, tuple(ei.candidates.judge(f, self.t, 28, m, b, V) for m in es.MULTIPLIERS))
        self.assertEqual(lv, es.naive.raw_levels(f, self.t, 28))
        self.assertEqual(js, (True, True, True))

    def test_reads_in_range(self):
        self.assertEqual(self.lo, self.t - datetime.timedelta(days=399))
        self.assertLessEqual(self.hi, self.t + datetime.timedelta(days=28))

    def test_inputs_do_not_use_future(self):
        vals2 = [x if d < self.t else 7e-3 for d, x in zip(self.days, self.vals)]
        out2, _a, _b = es.evaluate_tag(self.days, vals2, [self.t], V)
        self.assertEqual(out2[0][:5], self.out[0][:5])
        self.assertEqual(out2[0][6], self.out[0][6])


class TestMetrics(unittest.TestCase):
    def test_auc(self):
        self.assertAlmostEqual(es.auc([0.1, 0.4, 0.35, 0.8], [0, 0, 1, 1]), 0.75)
        self.assertAlmostEqual(es.auc([0.5, 0.5], [0, 1]), 0.5)
        self.assertIsNone(es.auc([0.1], [1]))

    def test_logloss(self):
        ll = es.log_loss_terms([0.5, 0.9], [1, 0])
        self.assertAlmostEqual(ll[0], math.log(2))
        self.assertAlmostEqual(ll[1], -math.log(0.1))

    def test_topk(self):
        tk = es.topk_by_week([0.9, 0.9, 0.1], [1, 0, 1], [0, 0, 0], ["B", "A", "C"], k=1)
        self.assertEqual(tk, {0: 0})                  # 同じ確率なら名前の順で A

    def test_bootstrap(self):
        vals = [(1.0, 10), (-1.0, 10), (0.5, 10)]
        a = es.bootstrap_diff(vals, n_boot=500)
        b = es.bootstrap_diff(vals, n_boot=500)
        self.assertEqual(a, b)
        self.assertLessEqual(a[0], a[1])
        self.assertGreaterEqual(a[0], -0.1)
        self.assertLessEqual(a[1], 0.1)


class TestFree(unittest.TestCase):
    def fake(self, gib):
        class S:
            f_bavail = int(gib * 1024 ** 3 / 4096)
            f_frsize = 4096
        return S()

    def test_home_limit(self):
        with mock.patch.object(es.os, "statvfs", return_value=self.fake(19.5)):
            with self.assertRaises(es.SignalError):
                es.check_free("/Users/x/Desktop/news-stick-data")
        with mock.patch.object(es.os, "statvfs", return_value=self.fake(25)):
            es.check_free("/Users/x/Desktop/news-stick-data")

    def test_lacie_limit(self):
        with mock.patch.object(es.os, "statvfs", return_value=self.fake(25)):
            with self.assertRaises(es.SignalError):
                es.check_free("/Volumes/LACIE SHARE/news-stick-data/explore-t117-cache")


class TestLoadCache(unittest.TestCase):
    def test_labels(self):
        self.assertEqual(es.LABEL, "explore-signals-t117-v3")
        self.assertEqual(es.PHASE1_LABEL, "explore-signals-phase1-v2")
        self.assertIn("explore-signals-phase1-v1", es.ACCEPTED_PHASE1_LABELS)

    def test_unknown_label_stops(self):
        with mock.patch.object(ei, "read_nofollow", return_value=json.dumps({"label": "x"}).encode()):
            with self.assertRaises(es.SignalError):
                es.load_cache("/c", {})

    def test_mismatch_stops(self):
        meta = {"label": es.PHASE1_LABEL, "tags": ["AAA"], "refs": {}, "days": [], "missing": [],
                "itemsize": 4, "byteorder": sys.byteorder, "totals": []}
        ctx = {"tags": ["BBB"], "refs": {}, "days": [], "missing": set(), "denom": {}}
        with mock.patch.object(ei, "read_nofollow", return_value=json.dumps(meta).encode()):
            with self.assertRaises(es.SignalError):
                es.load_cache("/c", ctx)

    def test_file_sha_checked(self):
        with mock.patch.object(ei, "read_nofollow", return_value=b"xyz"):
            with self.assertRaises(es.SignalError):
                es.read_cache_file("/c", "c7.bin.z", "0" * 64)


def tiny_table(seed=1):
    """モデルの比べ方のための小さな表（学習 400 行、検証 200 行）。"""
    rng = random.Random(seed)
    specs = es.model_specs(False)
    cols = sorted({c for _n, cs in specs for c in cs})
    tb = {"t": [], "tag": [], "week": [], "train": [], "test": []}
    for m in es.MULTIPLIERS:
        tb["y%d" % m] = []
        for k in range(len(es.naive.FEATURES)):
            tb["naive%d_%d" % (m, k)] = []
    for c in cols:
        tb[c] = []
    mondays = ei.prediction_mondays()
    for r in range(600):
        wk = r // 20 if r < 400 else 150 + (r - 400) // 20
        t = mondays[wk]
        tb["t"].append(t)
        tb["tag"].append("T%03d" % (r % 20))
        tb["week"].append(wk)
        (tb["train"] if r < 400 else tb["test"]).append(r)
        sig = rng.gauss(0, 1)
        for m in es.MULTIPLIERS:
            tb["y%d" % m].append(1 if rng.random() < 1 / (1 + math.exp(-(sig - m / 2))) else 0)
            for k in range(len(es.naive.FEATURES)):
                tb["naive%d_%d" % (m, k)].append(1.0 if k == 0 else rng.gauss(0, 1))
        for c in cols:
            tb[c].append(0.0 if "_miss" in c else sig + rng.gauss(0, 0.5))
    return tb, specs


class TestModels(unittest.TestCase):
    def test_fit_and_outputs(self):
        tb, specs = tiny_table()
        es._init_fit(tb)
        fits = {}
        for m in es.MULTIPLIERS:
            for name, cs in specs:
                mm, nn, use, coef, it, conv, probs = es._fit_task((m, name, cs))
                self.assertTrue(conv)
                fits[(m, name)] = (use, coef, it, conv, probs)
        rows, nweeks, nblocks = es.evaluate_models(tb, specs, fits)
        self.assertEqual(nweeks, 10)
        self.assertEqual(nblocks, 3)
        naive_rows = [r for r in rows if r["name"] == "naive"]
        self.assertTrue(all(r["d_logloss"] == 0 and r["d_topk"] == 0 for r in naive_rows))
        sig_rows = [r for r in rows if r["name"] == "s22_country_max" and r["m"] == 2]
        self.assertLess(sig_rows[0]["d_logloss"], 0)  # 信号に情報がある合成のデータでは、足すと良くなる
        meta = {"phase1_sha256": "0" * 64, "label": es.PHASE1_LABEL, "v": "1/543539", "tags": ["T"],
                "countries": ["US"], "lang_rows_not_dash": 0}
        ctx = {"refs": {}}
        netstat = {"w12q_lift10": [10, 50, 1]}
        files = es.build_outputs(meta, ctx, tb, specs, fits, ei.prediction_mondays(), netstat,
                                 D(2015, 3, 8), D(2020, 10, 12), -1, -1, False)
        files2 = es.build_outputs(meta, ctx, tb, specs, fits, ei.prediction_mondays(), netstat,
                                  D(2015, 3, 8), D(2020, 10, 12), -1, -1, False)
        self.assertEqual(files, files2)
        self.assertEqual(sorted(files), sorted(es.OUT_NAMES))
        s = files["summary.md"].decode("utf-8")
        for phrase in ("言語の単位は計算できなかった", "一覧と V の先読み", "除外の規則の漏れ", "WB のテーマの段",
                       ei.CITATION_JA, "報道した媒体の国ではない", "仮説", "多重比較の補正をしていない",
                       "独立でない", "それより前に試しがあったかどうかは、記録に無い", "記録が無い"):
            self.assertIn(phrase, s)
        self.assertNotIn("結果を見たあとで足した選択肢は無い。", s)
        run = json.loads(files["run.json"])
        self.assertIn("src/stats/explore_signals.py", run["code"])
        self.assertIn("src/stats/explore_islands.py", run["code"])
        self.assertEqual(run["comparisons_total"], 78)
        for n, d in files.items():
            self.assertIsNone(ei.EMAIL_RE.search(d), n)

    def test_write_refuses_existing(self):
        with mock.patch.object(es.os, "makedirs"), mock.patch.object(es.os.path, "lexists", return_value=True), \
                mock.patch.object(es.os, "open") as op:
            with self.assertRaises(es.SignalError):
                es.write_outputs("/nonexistent", {n: b"" for n in es.OUT_NAMES})
            op.assert_not_called()


class TestSplit(unittest.TestCase):
    def test_train_and_test_do_not_overlap(self):
        """学習の最後の予言日の判定期間の終わり < 検証の最初の予言日の判定期間の始まり。"""
        last_judged = es.TRAIN_LAST + datetime.timedelta(days=es.HORIZON)
        first_test_judged = es.TEST_FIRST + DAY
        self.assertLess(last_judged, first_test_judged)
        ms = ei.prediction_mondays()
        train = [t for t in ms if es.split_of(t) == "train"]
        test = [t for t in ms if es.split_of(t) == "test"]
        self.assertEqual(max(train), es.TRAIN_LAST)
        self.assertEqual(min(test), es.TEST_FIRST)
        self.assertLess(max(train) + datetime.timedelta(days=es.HORIZON), min(test) + DAY)
        self.assertTrue(all(es.split_of(t) is None for t in ms if es.TRAIN_LAST < t < es.TEST_FIRST))


class TestProvenance(unittest.TestCase):
    def test_own_code_shas(self):
        got = es.own_code_shas()
        for rel in ("src/stats/explore_signals.py", "src/stats/explore_islands.py"):
            with open(os.path.join(PROJECT, *rel.split("/")), "rb") as f:
                self.assertEqual(got[rel], hashlib.sha256(f.read()).hexdigest())


if __name__ == "__main__":
    unittest.main()
