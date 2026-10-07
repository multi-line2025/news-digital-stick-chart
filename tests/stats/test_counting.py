"""報道量の数え方の候補と、選ぶ基準の案のテスト（T-028。src/stats/counting.py、docs/stats/counting.md）。

実行（プロジェクトのルートで）:
    PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -B -m unittest discover -s tests/stats -v

データもネットワークも使わない。GKG の行は、このテストの中で作る合成の行で、テーマの名前は
実在の区分表から取ったものではない（ZZ で始まる作り物）。日の集計は、収集係の
src/collector/gkg.py の add_line と serialize_day で作る（読むだけ。収集係のコードは変えない）。
これで、候補が収集係の集計の形から計算できることを確かめる。
"""

import ast
import gzip
import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from fractions import Fraction as Fr

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(os.path.dirname(HERE))
SRC = os.path.join(PROJECT, "src", "stats")
DOC = os.path.join(PROJECT, "docs", "stats", "counting.md")
sys.path.insert(0, SRC)

import counting  # noqa: E402


def _load_gkg():
    path = os.path.join(PROJECT, "src", "collector", "gkg.py")
    spec = importlib.util.spec_from_file_location("gkg_for_counting_test", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


gkg = _load_gkg()

FT = {"2015-03-02": "20150302120000", "2015-03-03": "20150303120000", "2015-03-04": "20150304120000"}


def gkg_line(file_time, n, coll="1", v1="", v2="", translated=False):
    cols = [b""] * gkg.N_COLUMNS
    cols[gkg.I_ID] = ("%s-%s%d" % (file_time, "T" if translated else "", n)).encode()
    cols[gkg.I_D21] = file_time.encode()
    cols[gkg.I_COLL] = coll.encode()
    cols[gkg.I_V1T] = v1.encode()
    cols[gkg.I_V2T] = v2.encode()
    return b"\t".join(cols) + b"\n"


def make_day(day, rows, mode="trial"):
    """rows: [(coll, v1, v2, translated)] の文書。gkg.serialize_day の形の gzip のバイト列を返す。"""
    ft = FT[day]
    agg = gkg.Agg()
    vocab = {}
    for i, (coll, v1, v2, tr) in enumerate(rows):
        gkg.add_line(agg, gkg_line(ft, i, coll, v1, v2, tr), ft.encode(), vocab)
    files = [{"file_time": ft, "result": "ok", "reason": None, "md5": "0" * 32, "size": 1,
              "sha256": "0" * 64, "attempts": 1, "docs": {g.decode(): n for g, n in agg.docs.items()}}]
    data = gkg.serialize_day(day, agg, files, mode)
    gkg.check_output_bytes(data, "テストの日の集計")
    return gkg.gzip_bytes(data)


# 1日分の基本の文書。V1 と V2 の付き方を少し変えてある。
BASE_ROWS = [
    ("1", "ZZA;ZZB", "ZZA,10;ZZA,40;ZZB,5", False),     # V2 で ZZA は2回
    ("1", "ZZA", "ZZA,3", False),
    ("2", "ZZB;ZZC", "ZZC,8", False),                   # V2 に ZZB が無い
    ("1", "", "ZZD,1", False),                          # V1 にテーマが無い
    ("1", "", "", False),                               # どちらにも無い
    ("1", "ZZA", "ZZA,1;ZZA,2;ZZA,3", True),            # 翻訳の印（数えない）
    ("X1", "ZZC", "ZZC,4", False),                      # 組の形が違う（X。数える）
]


def base_summaries(rows_by_day=None):
    out = []
    for d in counting.TRIAL_DAYS:
        rows = BASE_ROWS if rows_by_day is None else rows_by_day[d]
        out.append(counting.parse_day(make_day(d, rows), expect_day=d, expect_mode="trial"))
    return out


class TestFormatAgreesWithCollector(unittest.TestCase):
    def test_trial_days(self):
        self.assertEqual(counting.TRIAL_DAYS, gkg.TRIAL_DAYS)

    def test_day_file_name(self):
        for d in counting.TRIAL_DAYS:
            self.assertEqual(counting.trial_day_file_name("0123456789abcdef", d),
                             gkg.day_file_name("0123456789abcdef", d, "trial"))
            for mode in ("trial", "official"):
                self.assertEqual(counting.day_file_name(mode, "0123456789abcdef", d),
                                 gkg.day_file_name("0123456789abcdef", d, mode))

    def test_official_run_id_rule(self):
        """2段目の run の決め方が、収集係の official_run_id（最初の run-start）と同じであること。"""
        rows = official_rows(OID, counting.TRIAL_DAYS, [RID]) + official_rows(RID2, counting.TRIAL_DAYS, [RID])
        self.assertEqual(gkg.official_run_id(rows), counting.select_official_input(manifest(rows))["run_id"])

    def test_day_format(self):
        self.assertEqual(gkg.DAY_FORMAT, ("%s\t%s" % (counting.DAY_FORMAT_NAME,
                                                      counting.DAY_FORMAT_VERSION)).encode())

    def test_manifest_path(self):
        self.assertEqual("/".join(gkg.MANIFEST_DIR_PARTS + (gkg.TRIAL_MANIFEST_NAME,)),
                         counting.TRIAL_MANIFEST_PATH)

    def test_s_names_exist_in_collector(self):
        with open(os.path.join(PROJECT, "src", "collector", "gkg.py"), encoding="utf-8") as f:
            src = f.read()
        for name in counting.S_UNCOVERED.values():
            self.assertIn('st["%s"]' % name, src)


class TestCandidates(unittest.TestCase):
    """各候補を、収集係の形の日の集計から計算できること（手で数えた値と一致）。"""

    def test_all_candidates_from_collector_format(self):
        s = base_summaries()[0]
        # 数える組：1・2・X（"X1" は形が違うので X になる）。翻訳の 1T は数えない。
        self.assertEqual(sorted(s["docs"]), ["1", "1T", "2", "X"])
        expect = {
            "C1": ({"ZZA": 2, "ZZB": 2, "ZZC": 2}, 6),
            "C2": ({"ZZA": 2, "ZZB": 2, "ZZC": 2}, 6),
            "C3": ({"ZZA": 2, "ZZB": 1, "ZZC": 2, "ZZD": 1}, 6),
            "C4": ({"ZZA": 2, "ZZB": 1, "ZZC": 2, "ZZD": 1}, 6),
            "C5": ({"ZZA": 3, "ZZB": 1, "ZZC": 2, "ZZD": 1}, 6),
            "C6": ({"ZZA": 3, "ZZB": 1, "ZZC": 2, "ZZD": 1}, 7),
            # C7：V1 か V2 の少なくとも一方。ZZB は1行目（両方）と3行目（V1 だけ）で2、ZZD は4行目（V2 だけ）で1
            "C7": ({"ZZA": 2, "ZZB": 2, "ZZC": 2, "ZZD": 1}, 7),
        }
        for cid in counting.CANDIDATE_IDS:
            with self.subTest(cid=cid):
                self.assertEqual(counting.candidate_counts(s, cid), expect[cid])

    def test_translated_groups_never_counted(self):
        rows = [("1", "ZZA", "ZZA,1", True)] * 3
        s = counting.parse_day(make_day("2015-03-02", rows))
        for cid in counting.CANDIDATE_IDS:
            self.assertEqual(counting.candidate_counts(s, cid), ({}, 0))
        self.assertFalse(counting.counted_group("1T"))
        self.assertFalse(counting.counted_group("XT"))
        self.assertTrue(counting.counted_group("X"))
        self.assertTrue(counting.counted_group("12"))

    def test_counts_are_nonnegative_ints(self):
        s = base_summaries()[0]
        for cid in counting.CANDIDATE_IDS:
            counts, total = counting.candidate_counts(s, cid)
            self.assertIsInstance(total, int)
            for v in counts.values():
                self.assertIsInstance(v, int)
                self.assertGreater(v, 0)

    def test_unknown_candidate(self):
        with self.assertRaises(ValueError):
            counting.candidate_counts(base_summaries()[0], "C8")

    def test_candidate_table(self):
        self.assertEqual(counting.CANDIDATE_IDS, ("C1", "C2", "C3", "C4", "C5", "C6", "C7"))
        self.assertEqual(counting.REFERENCE_CANDIDATE_IDS, counting.CANDIDATE_IDS[:6])
        cols = {c[1] for c in counting.CANDIDATES}
        self.assertEqual(cols, set(counting.COLUMNS))
        old = counting.COLUMNS[:3]
        self.assertEqual({(c[1], c[2]) for c in counting.CANDIDATES},
                         {(a, b) for a in old for b in counting.DENOMINATORS} | {("v1_or_v2_docs", "same")})

    def test_c7_counts_once_when_both(self):
        """C7 は、同じ文書で V1 と V2 の両方に付いても1回。V1 から V2 へ移っても数が変わらない。"""
        both = [("1", "ZZA", "ZZA,1", False)] * 4
        v1only = [("1", "ZZA", "", False)] * 4
        v2only = [("1", "", "ZZA,1", False)] * 4
        vals = []
        for rows in (both, v1only, v2only):
            s = counting.parse_day(make_day("2015-03-02", rows))
            vals.append(counting.candidate_counts(s, "C7")[0]["ZZA"])
        self.assertEqual(vals, [4, 4, 4])

    def test_names_differ_counted_separately(self):
        """限界（収集係の README 6.5.4）：V1 と V2 で名前が違えば、別々のテーマとして数える。"""
        s = counting.parse_day(make_day("2015-03-02", [("1", "ZZA", "ZZAB,1", False)] * 2))
        self.assertEqual(counting.candidate_counts(s, "C7"), ({"ZZA": 2, "ZZAB": 2}, 4))


class TestDenominatorChanges(unittest.TestCase):
    """counting.md 3章 (3) の (ア)(イ)(ウ)：二つの分母が除ける変化の違い（T-028 差し戻し1回目 中1）。
    ZZA の比率を、記事の数で割る C1 と、同じ数え方の合計で割る C2 で比べる。"""

    def ratio(self, rows, cid):
        s = counting.parse_day(make_day("2015-03-02", rows))
        counts, total = counting.candidate_counts(s, cid)
        return Fr(counts.get("ZZA", 0), total)

    BASE = [("1", "ZZA", "ZZA,1", False)] * 5 + [("1", "ZZB", "ZZB,1", False)] * 5 + [("1", "", "", False)] * 20

    def test_a_more_sources(self):
        # (ア) 収集元が増え、すべてが一律に倍：どちらの分母でも比率は変わらない
        for cid in ("C1", "C2"):
            self.assertEqual(self.ratio(self.BASE * 2, cid), self.ratio(self.BASE, cid), cid)

    def test_b_all_themes_attached_more(self):
        # (イ) 記事の数は同じで、どのテーマも一律に倍の記事に付く：C1 は倍になり、C2 は変わらない
        more = [("1", "ZZA", "ZZA,1", False)] * 10 + [("1", "ZZB", "ZZB,1", False)] * 10 + [("1", "", "", False)] * 10
        self.assertEqual(self.ratio(more, "C1"), 2 * self.ratio(self.BASE, "C1"))
        self.assertEqual(self.ratio(more, "C2"), self.ratio(self.BASE, "C2"))

    def test_c_theme_starts_or_stops(self):
        # (ウ) 新しいテーマ ZZN が付き始める：C1 の ZZA は変わらず、C2 の ZZA は下がる
        new = [(g, (v1 + ";ZZN").lstrip(";"), (v2 + ";ZZN,1").lstrip(";"), t) for g, v1, v2, t in self.BASE]
        self.assertEqual(self.ratio(new, "C1"), self.ratio(self.BASE, "C1"))
        self.assertLess(self.ratio(new, "C2"), self.ratio(self.BASE, "C2"))
        # ZZB が付かなくなる：C1 の ZZA は変わらず、C2 の ZZA は上がる
        gone = [(g, v1.replace("ZZB", ""), v2.replace("ZZB,1", ""), t) for g, v1, v2, t in self.BASE]
        self.assertEqual(self.ratio(gone, "C1"), self.ratio(self.BASE, "C1"))
        self.assertGreater(self.ratio(gone, "C2"), self.ratio(self.BASE, "C2"))


class TestParseDay(unittest.TestCase):
    def test_header_checks(self):
        gz = make_day("2015-03-02", BASE_ROWS)
        with self.assertRaises(counting.CountingError):
            counting.parse_day(gz, expect_day="2015-03-03")
        with self.assertRaises(counting.CountingError):
            counting.parse_day(gz, expect_mode="official")
        with self.assertRaises(counting.CountingError):
            counting.parse_day(b"not gzip")
        bad = gzip.compress(b"#\tgkg-day\t1\t2015-03-02\ttrial\n", mtime=0)
        with self.assertRaises(counting.CountingError):
            counting.parse_day(bad)

    def _raw(self, body):
        return gzip.compress(b"#\tgkg-day\t3\t2015-03-02\ttrial\n" + body, mtime=0)

    def test_malformed_rows(self):
        cases = [
            b"V\t0\tZZA\nV\t0\tZZB\n",                      # 番号の重なり
            b"D\t1\t3\nD\t1\t4\n",                          # 組の重なり
            b"V\t0\tZZA\nD\t1\t3\nT\t1\t1\t1\t1\n",         # 欄の数
            b"V\t0\tZZA\nD\t1\t3\nT\t1\t5\t1\t1\t1\n",      # V に無い番号
            b"V\t0\tZZA\nD\t1\t3\nT\t2\t0\t1\t1\t1\n",      # D に無い組
            b"V\t0\tZZA\nD\t1\t3\nT\t1\t0\t1\t1\t1\nT\t1\t0\t1\t1\t1\n",   # 重なり
            b"V\t0\tZZA\nD\t1\t-3\n",                       # 負の数
            b"S\ta\t1\nS\ta\t2\n",                          # S の重なり
        ]
        for body in cases:
            with self.subTest(body=body):
                with self.assertRaises(counting.CountingError):
                    counting.parse_day(self._raw(body))

    def test_version_3_only_and_row_relations(self):
        """版3（T-035）だけを読む。T の行の数どうしの関係が合わなければ止まる。"""
        old = gzip.compress(b"#\tgkg-day\t2\t2015-03-02\ttrial\n", mtime=0)
        with self.assertRaises(counting.CountingError):
            counting.parse_day(old)
        for nums in (b"2\t1\t1\t1", b"1\t2\t2\t1", b"1\t1\t1\t3", b"1\t2\t1\t2"):
            with self.subTest(nums=nums):
                with self.assertRaises(counting.CountingError):
                    counting.parse_day(self._raw(b"V\t0\tZZA\nD\t1\t3\nT\t1\t0\t" + nums + b"\n"))
        s = counting.parse_day(self._raw(b"V\t0\tZZA\nD\t1\t3\nT\t1\t0\t1\t1\t2\t1\n"))
        self.assertEqual(s["themes"]["ZZA"]["1"], (1, 1, 2, 1))

    def test_more_format_checks(self):
        """軽-1：テーマの名前の形、組の形、T の数が組の D を超える、S が D の和を超える、知らない行。"""
        bad = {
            "theme_name": b"V\t0\tzza\nD\t1\t3\n",
            "group": b"D\t1Z\t3\n",
            "t_over_d": b"V\t0\tZZA\nD\t1\t1\nT\t1\t0\t2\t0\t0\t2\n",
            "s_over_d": b"D\t1\t3\nS\tdocs_without_any_theme\t4\n",
            "unknown_tag": b"D\t1\t3\nQ\tx\n",
        }
        for name, body in bad.items():
            with self.subTest(name=name):
                with self.assertRaises(counting.CountingError):
                    counting.parse_day(self._raw(body))
        ok = counting.parse_day(self._raw(b"D\tXT\t3\nD\t12\t1\nS\tdocs_without_any_theme\t4\n"))
        self.assertEqual(ok["docs"], {"XT": 3, "12": 1})

    def test_honest_rich_aggregate_passes(self):
        """軽-1：収集係の gkg.py で作った、国・言語・翻訳の情報・組の網・いろいろな組を含む正直な集計を、
        新しい確かめが誤って止めない。"""
        ft = FT["2015-03-02"]
        agg, vocab = gkg.Agg(), {}
        lines = []
        for i in range(40):
            cols = [b""] * gkg.N_COLUMNS
            tr = (i % 7 == 0)
            cols[gkg.I_ID] = ("%s-%s%d" % (ft, "T" if tr else "", i)).encode()
            cols[gkg.I_D21] = ft.encode()
            cols[gkg.I_COLL] = [b"1", b"2", b"12", b"bad"][i % 4]
            cols[gkg.I_V1T] = [b"ZZA;ZZB", b"ZZB;ZZC;ZZD", b"", b"ZZA"][i % 4]
            cols[gkg.I_V2T] = [b"ZZA,1;ZZA,9;ZZE,3", b"ZZC,2", b"ZZD,5;ZZD,6", b""][i % 3]
            cols[gkg.I_V1LOC] = [b"1#Somewhere#US#US06#0#0#1", b"", b"4#Elsewhere#FR#FR11#0#0#2"][i % 3]
            cols[gkg.I_TINFO] = b"srclc:fra;eng:GT-FRA 1.0" if tr else b""
            lines.append(b"\t".join(cols) + b"\n")
        lines.append(b"too\tfew\n")
        for line in lines:
            gkg.add_line(agg, line, ft.encode(), vocab)
        files = [{"file_time": ft, "result": "ok", "reason": None, "md5": "0" * 32, "size": 1,
                  "sha256": "0" * 64, "attempts": 1, "docs": {g.decode(): n for g, n in agg.docs.items()}}]
        data = gkg.serialize_day("2015-03-02", agg, files, "trial")
        tags = {line.split(b"\t")[0] for line in data.split(b"\n") if line}
        self.assertTrue({b"C", b"L", b"P1", b"P2", b"NC", b"NL", b"E", b"F", b"FD"} <= tags, tags)
        s = counting.parse_day(gkg.gzip_bytes(data), expect_day="2015-03-02", expect_mode="trial")
        self.assertIn("XT", s["docs"])
        for cid in counting.CANDIDATE_IDS:
            counting.candidate_counts(s, cid)

    def test_regexes_match_collector(self):
        self.assertEqual(gkg.THEME_RE.pattern.decode(), counting.THEME_NAME_RE.pattern[2:-2])

    def test_coverage(self):
        """欄の手厚さ：S の3つの値と、すべての組の D の和。S の行が無ければ 0（T-036）。"""
        s = base_summaries()[0]
        # BASE_ROWS：V1 が空は4・5行目、V2 が空は5行目、どちらも空は5行目。7文書（翻訳の組も含む）
        self.assertEqual(counting.coverage([s]), {"docs_all_groups": 7, "docs_without_v1_theme": 2,
                                                  "docs_without_v2_theme": 1, "docs_without_any_theme": 1})
        bare = counting.parse_day(self._raw(b"D\t1\t3\n"))
        self.assertEqual(counting.coverage([bare]), {"docs_all_groups": 3, "docs_without_v1_theme": 0,
                                                     "docs_without_v2_theme": 0, "docs_without_any_theme": 0})

    def test_ignores_other_tables(self):
        s = base_summaries()[0]
        self.assertIn("docs_without_v1_theme", s["stats"])


def rows_with(v1_uncovered, v2_uncovered, both=4):
    """V1 だけが無い文書 v1_uncovered 本、V2 だけが無い文書 v2_uncovered 本、両方ある文書 both 本。"""
    rows = [("1", "ZZA", "ZZA,1", False)] * both
    rows += [("1", "", "ZZA,1", False)] * v1_uncovered
    rows += [("1", "ZZA", "", False)] * v2_uncovered
    return {d: rows for d in counting.TRIAL_DAYS}


class TestCriteria(unittest.TestCase):
    def test_b1_b2_field_choice(self):
        for u1, u2, b1, b2 in ((1, 2, "C2", "C1"), (2, 1, "C4", "C3"), (2, 2, "C2", "C1")):
            with self.subTest(u1=u1, u2=u2):
                s = base_summaries(rows_with(u1, u2))
                self.assertEqual(counting.criterion_b1(s)["candidate"], b1)
                self.assertEqual(counting.criterion_b2(s)["candidate"], b2)

    def test_b1_none_when_no_themed_docs(self):
        rows = {d: [("1", "", "", False)] * 3 for d in counting.TRIAL_DAYS}
        s = base_summaries(rows)
        self.assertIsNone(counting.criterion_b1(s)["candidate"])
        self.assertIsNone(counting.criterion_b2(s)["candidate"])
        self.assertIsNone(counting.criterion_b3(s)["candidate"])

    def test_b1_none_when_candidate_not_usable_on_a_day(self):
        rows = rows_with(0, 1)
        rows["2015-03-03"] = [("1", "", "ZZA,1", False)]     # この日だけ V1 が空
        s = base_summaries(rows)
        # 3日の和：V1 の付かない文書 0+1+0=1、V2 の付かない文書 1+0+1=2 → 欄は V1、候補は C2。
        # 2日目は C2 の分子が 0 なので、使えない → 該当なし（ほかの候補に代えない）
        r1 = counting.criterion_b1(s)
        self.assertEqual((r1["values"]["docs_without_v1_theme"], r1["values"]["docs_without_v2_theme"]), (1, 2))
        self.assertIsNone(r1["candidate"])
        self.assertEqual(r1["reason"], "not_usable")
        self.assertIsNone(counting.criterion_b3(s)["candidate"])

    def test_b1_counts_all_groups_for_coverage(self):
        """B1・B2 の n（S の行と比べる文書の数）は、翻訳の組を含むすべての組の D の和（3章 (1)）。"""
        rows = {d: [("1", "", "ZZA,1", False)] * 2 + [("1", "ZZA", "ZZA,1", True)] * 3 for d in counting.TRIAL_DAYS}
        s = base_summaries(rows)
        r = counting.criterion_b1(s)
        self.assertEqual(r["values"]["docs_all_groups"], 15)
        self.assertEqual(r["values"]["docs_without_v1_theme"], 6)
        # u1 = 6、u2 = 0 なので欄は V2。C4 は使える
        self.assertEqual(r["candidate"], "C4")
        rows = {d: [("1", "", "", False)] * 2 + [("1", "ZZA", "ZZA,1", True)] * 3 for d in counting.TRIAL_DAYS}
        r = counting.criterion_b1(base_summaries(rows))
        # 数える組にはテーマの付いた記事が無いが、n はすべての組なので u < n → 欄は V1、C2 は使えない
        self.assertEqual((r["candidate"], r["reason"]), (None, "not_usable"))

    def test_b3_fixed(self):
        self.assertEqual(counting.criterion_b3(base_summaries())["candidate"], "C1")

    def test_b4_spread(self):
        # 1文書あたりの V1 のテーマ数：1日目 1、2日目 q、3日目 1
        def rows(themes_day2_num, docs_day2_den):
            out = {}
            for d in counting.TRIAL_DAYS:
                out[d] = [("1", "ZZA", "ZZA,1", False)] * 10
            # 2日目：10文書のうち、ZZB も付く文書の数を変える
            out["2015-03-03"] = ([("1", "ZZA;ZZB", "ZZA,1", False)] * themes_day2_num
                                 + [("1", "ZZA", "ZZA,1", False)] * (docs_day2_den - themes_day2_num))
            return out
        # q = 11/10 ちょうど（上限と等しい）→ C1
        s = base_summaries(rows(1, 10))
        r = counting.criterion_b4(s)
        self.assertEqual(r["values"]["spread"], "11/10")
        self.assertEqual(r["candidate"], "C1")
        # q = 12/10 → C2
        s = base_summaries(rows(2, 10))
        self.assertEqual(counting.criterion_b4(s)["candidate"], "C2")

    def test_b4_none(self):
        rows = {d: [("1", "", "ZZA,1", False)] * 3 for d in counting.TRIAL_DAYS}
        self.assertIsNone(counting.criterion_b4(base_summaries(rows))["candidate"])
        rows = {d: [("1T", "ZZA", "ZZA,1", True)] * 3 for d in counting.TRIAL_DAYS}
        r = counting.criterion_b4(base_summaries(rows))
        self.assertIsNone(r["candidate"])
        self.assertEqual(r["reason"], "no_docs")

    def test_b5_ratio(self):
        def rows(extra_mentions):
            out = {}
            for d in counting.TRIAL_DAYS:
                out[d] = [("1", "ZZA", "ZZA,1", False)] * 20
            out["2015-03-02"] = ([("1", "ZZA", "ZZA,1;ZZA,2", False)] * extra_mentions
                                 + [("1", "ZZA", "ZZA,1", False)] * (20 - extra_mentions))
            return out
        # 文書 60、言及 60 + 3 → 63/60 = 21/20（等しい）→ C4
        r = counting.criterion_b5(base_summaries(rows(3)))
        self.assertEqual(r["values"]["ratio"], "21/20")
        self.assertEqual(r["candidate"], "C4")
        r = counting.criterion_b5(base_summaries(rows(4)))
        self.assertEqual(r["candidate"], "C6")
        rows0 = {d: [("1", "ZZA", "", False)] for d in counting.TRIAL_DAYS}
        self.assertIsNone(counting.criterion_b5(base_summaries(rows0))["candidate"])

    def test_every_criterion_outputs_one_candidate_or_none(self):
        variants = [None, rows_with(1, 2), rows_with(2, 1), rows_with(3, 3)]
        for v in variants:
            s = base_summaries(v)
            out = counting.apply_all(s)
            self.assertEqual(list(out), list(counting.CRITERIA_IDS))
            for bid, r in out.items():
                self.assertTrue(r["candidate"] is None or r["candidate"] in counting.CANDIDATE_IDS, bid)
                base = counting.CRITERIA[bid](s)
                self.assertEqual({k: r[k] for k in base}, base)
                self.assertIs(r["official"], False)
                self.assertEqual(r["decided"], base["candidate"] or counting.fallback_candidate(s, bid))

    def test_input_must_be_trial_days_in_order(self):
        s = base_summaries()
        for bid in counting.CRITERIA_IDS:
            with self.assertRaises(counting.CountingError):
                counting.CRITERIA[bid](list(reversed(s)))
            with self.assertRaises(counting.CountingError):
                counting.CRITERIA[bid](s[:2])

    def test_criteria_do_not_take_tag_list(self):
        """基準は、日の集計（summaries）だけを引数に取る。タグの一覧は受け取れない。"""
        import inspect
        for bid, fn in counting.CRITERIA.items():
            self.assertEqual(list(inspect.signature(fn).parameters), ["summaries"], bid)

    def test_official_undecided(self):
        """正式な数え方は OWNER_DECISION から機械的に決まる C7。B1〜B5 を正式に書き入れる場所は無い（T-028 軽-2）。"""
        self.assertEqual(counting.OFFICIAL_CANDIDATE, "C7")
        self.assertEqual(counting.official_candidate(), "C7")
        self.assertEqual(counting.official_status(), "decided")
        for name in ("OFFICIAL_CRITERION", "RECOMMENDED_CRITERION", "ANSWER_TO_CRITERION"):
            self.assertFalse(hasattr(counting, name), name)
        out = counting.apply_all(base_summaries())
        self.assertTrue(all(r["official"] is False for r in out.values()))
        # 決定の（分子、分母）を別の候補に変えると、別の候補になる（手で識別子を書く場所が無い）
        # 決定の中身を出どころの語句の対応と違うものに変えると、正式な候補は決まらない（中-4）
        saved = dict(counting.OWNER_DECISION)
        try:
            for key, value in (("numerator_column", "v1_docs"), ("denominator", "docs")):
                counting.OWNER_DECISION.clear()
                counting.OWNER_DECISION.update(saved)
                counting.OWNER_DECISION[key] = value
                with self.assertRaises(ValueError, msg=key):
                    counting.official_candidate()
        finally:
            counting.OWNER_DECISION.clear()
            counting.OWNER_DECISION.update(saved)

    def test_owner_decision_source_line(self):
        """OWNER_DECISION の出どころの行が、その commit の reviews/T-028.md にちょうど1つある。"""
        d = counting.OWNER_DECISION
        r = subprocess.run(["git", "show", "%s:%s" % (d["source_commit"], d["source_path"])],
                           capture_output=True, cwd=PROJECT)
        self.assertEqual(r.returncode, 0, r.stderr)
        lines = r.stdout.decode("utf-8").split("\n")
        self.assertEqual(lines.count(d["source_line"]), 1)
        # 2つ目の出どころ：リードの整理の「決定：」の行がちょうど1つあり、語句をすべて含む（中-4）
        dec = [x for x in lines if x.startswith(d["decision_line_prefix"])]
        self.assertEqual(len(dec), 1)
        for phrase, key, value in counting.DECISION_PHRASES:
            self.assertIn(phrase, dec[0], phrase)
            self.assertEqual(d[key], value, key)
        self.assertEqual({k for _p, k, _v in counting.DECISION_PHRASES}, {"numerator_column", "denominator"})


RID = "0123456789abcdef"
RID2 = "fedcba9876543210"
OID = "00112233aabbccdd"


def manifest(rows):
    return b"".join(json.dumps(r, sort_keys=True).encode() + b"\n" for r in rows)


def trial_rows(rid, days, complete=True, shas=None):
    out = [{"kind": "run-start", "run_id": rid, "mode": "trial", "trial": True, "official": False}]
    for d in days:
        sha = (shas or {}).get(d, hashlib.sha256(d.encode()).hexdigest())
        out.append({"kind": "day", "run_id": rid, "mode": "trial", "day": d,
                    "file_name": counting.trial_day_file_name(rid, d), "sha256": sha})
    if complete:
        out.append({"kind": "run-complete", "run_id": rid, "mode": "trial"})
    return out


def official_rows(oid, days, trial_ids, trial_manifest=b"", shas=None, extra_days=(), failed=None):
    """正式な run のマニフェストの行。run-start には、gkg._trial_info と同じ形で trial_run_ids と
    trial_manifest_sha256（空なら None）を書く。"""
    out = [{"kind": "run-start", "run_id": oid, "mode": "official", "trial": False, "official": True,
            "trial_run_ids": list(trial_ids),
            "trial_manifest_sha256": hashlib.sha256(trial_manifest).hexdigest() if trial_manifest else None}]
    for d in list(days) + list(extra_days):
        sha = (shas or {}).get(d, hashlib.sha256(d.encode()).hexdigest())
        out.append({"kind": "day", "run_id": oid, "mode": "official", "day": d,
                    "file_name": counting.day_file_name("official", oid, d), "sha256": sha,
                    "failed_files": (failed or {}).get(d, [])})
    return out


class TestTrialInputRule(unittest.TestCase):
    def test_normal(self):
        sel = counting.select_trial_input(manifest(trial_rows(RID, counting.TRIAL_DAYS)))
        self.assertEqual((sel["status"], sel["run_id"]), ("complete", RID))
        self.assertEqual([d["day"] for d in sel["days"]], list(counting.TRIAL_DAYS))

    def test_first_run_start_only(self):
        # 最初の run が終わっていなければ、あとの完了した run があっても代えない
        m = manifest(trial_rows(RID, counting.TRIAL_DAYS[:1], complete=False)
                     + trial_rows(RID2, counting.TRIAL_DAYS))
        self.assertEqual(counting.select_trial_input(m),
                         {"status": "not_complete", "run_id": RID, "start_runs": 2, "day_rows": 1})
        m = manifest(trial_rows(RID, counting.TRIAL_DAYS) + trial_rows(RID2, counting.TRIAL_DAYS))
        self.assertEqual(counting.select_trial_input(m)["run_id"], RID)

    def test_run_complete_required(self):
        """3日の day の行がそろっていても、R の run-complete が無ければ終わっていない（差し戻し1回目 軽1）。"""
        m = manifest(trial_rows(RID, counting.TRIAL_DAYS, complete=False))
        self.assertEqual(counting.select_trial_input(m)["status"], "not_complete")
        m = manifest(trial_rows(RID, counting.TRIAL_DAYS, complete=False)
                     + [{"kind": "run-complete", "run_id": RID2, "mode": "trial"}])
        self.assertEqual(counting.select_trial_input(m)["status"], "not_complete")

    def test_no_start(self):
        self.assertEqual(counting.select_trial_input(b""), {"status": "no_trial"})

    def test_rejections(self):
        good = trial_rows(RID, counting.TRIAL_DAYS)
        cases = {
            "missing_day": [r for r in good if r.get("day") != "2015-03-03"],
            "dup_day": good[:2] + [good[1]] + good[2:],
            "other_day": good + [dict(good[1], day="2015-03-05",
                                      file_name=counting.trial_day_file_name(RID, "2015-03-05"))],
            "bad_name": [dict(r, file_name="x.tsv.gz") if r["kind"] == "day" else r for r in good],
            "bad_mode": [dict(r, mode="official") if r["kind"] == "day" else r for r in good],
            "start_not_trial": [dict(r, trial=False) if r["kind"] == "run-start" else r for r in good],
            "bad_sha": [dict(r, sha256="0") if r["kind"] == "day" else r for r in good],
            "bad_run_id": [dict(r, run_id="xyz") for r in good],
            "bad_failed_files": [dict(r, failed_files="x") if r["kind"] == "day" else r for r in good],
        }
        for name, rows in cases.items():
            with self.subTest(name=name):
                with self.assertRaises(counting.CountingError) as cm:
                    counting.select_trial_input(manifest(rows))
                self.assertNotIsInstance(cm.exception, counting.InputNotReady)
        with self.assertRaises(counting.CountingError):
            counting.select_trial_input(b"{not json\n")

    def test_official_input(self):
        m = manifest(official_rows(OID, counting.TRIAL_DAYS, [RID], extra_days=("2015-03-05",)))
        sel = counting.select_official_input(m)
        self.assertEqual(sel["run_id"], OID)
        self.assertEqual([d["day"] for d in sel["days"]], list(counting.TRIAL_DAYS))
        with self.assertRaises(counting.InputNotReady):
            counting.select_official_input(manifest(official_rows(OID, counting.TRIAL_DAYS[:2], [RID])))
        with self.assertRaises(counting.InputNotReady):
            counting.select_official_input(b"")

    def test_prefix_versions(self):
        head = manifest(trial_rows(RID, counting.TRIAL_DAYS))
        counting.check_prefix_versions(head, [b"", head[:10], head])
        with self.assertRaises(counting.CountingError):
            counting.check_prefix_versions(head, [b"x" + head[1:20]])


def _files(mode, rid, rows=BASE_ROWS):
    files, shas = {}, {}
    for d in counting.TRIAL_DAYS:
        gz = make_day(d, rows, mode=mode)
        files[(mode, counting.day_file_name(mode, rid, d))] = gz
        shas[d] = hashlib.sha256(gz).hexdigest()
    return files, shas


def _reader(files):
    def read(mode, name):
        if (mode, name) not in files:
            raise counting.CountingError("無い")
        return files[(mode, name)]
    return read


class TestDecide(unittest.TestCase):
    """counting.md 4章 (2) の表（T-028 差し戻し1回目 中3、2回目 中-B1・中-B2）。"""

    def setUp(self):
        self.tf, self.tsha = _files("trial", RID)
        self.of, self.osha = _files("official", OID)
        self.tm = manifest(trial_rows(RID, counting.TRIAL_DAYS, shas=self.tsha))
        self.files = {**self.tf, **self.of}

    def om(self, trial_manifest, trial_ids, days=counting.TRIAL_DAYS, **kw):
        return manifest(official_rows(OID, days, trial_ids, trial_manifest, shas=self.osha, **kw))

    def decide(self, tm, om, files=None):
        return counting.decide(tm, om, _reader(self.files if files is None else files))

    def test_step1_before_official(self):
        out = self.decide(self.tm, b"")
        self.assertEqual((out["status"], out["input_mode"], out["input_run_id"]), ("decided", "trial", RID))
        self.assertEqual(set(out["results"]), set(counting.CRITERIA_IDS))
        self.assertEqual(out, self.decide(self.tm, b""))

    def test_step1_after_official(self):
        out = self.decide(self.tm, self.om(self.tm, [RID]))
        self.assertEqual((out["status"], out["input_mode"]), ("decided", "trial"))

    def test_trial_not_complete(self):
        """中-3：R が終わらないまま正式な run が始まったとき、2段目に進むのは R に day の行が一つも無く、
        試しの run の run-start が R の一つだけのときだけ。"""
        tm = manifest(trial_rows(RID, counting.TRIAL_DAYS, complete=False))
        self.assertEqual(self.decide(tm, b"")["status"], "pending")
        out = self.decide(tm, self.om(tm, [RID]))
        self.assertEqual(out["status"], "stopped")            # R に day の行がある
        tm0 = manifest(trial_rows(RID, (), complete=False))
        self.assertEqual(self.decide(tm0, b"")["status"], "pending")
        out = self.decide(tm0, self.om(tm0, [RID]))
        self.assertEqual((out["status"], out["input_mode"]), ("decided", "official"))

    def test_two_trial_runs_unfinished_stops(self):
        """中-3：試しの run を二つ行い（A を途中で止め、B で3日を全部作る）、A を終えないまま正式な run を
        始めても、2段目にはならず止まる。A に day の行が無くても同じ。"""
        for a_days in (counting.TRIAL_DAYS[:1], ()):
            tm = manifest(trial_rows(RID, a_days, complete=False) + trial_rows(RID2, counting.TRIAL_DAYS))
            self.assertEqual(self.decide(tm, b"")["status"], "pending")
            out = self.decide(tm, self.om(tm, [RID, RID2]))
            self.assertEqual(out["status"], "stopped", a_days)
            self.assertIn("二つ以上", out["steps"][-1]["reason"])

    def test_trial_run_ids_shapes(self):
        """軽-3：trial_run_ids の鍵が無い・一覧でない・2件以上の場合。"""
        rows = json_rows(self.om(self.tm, [RID]))
        del rows[0]["trial_run_ids"]
        self.assertEqual(self.decide(self.tm, manifest(rows))["status"], "stopped")
        rows[0]["trial_run_ids"] = RID
        self.assertEqual(self.decide(self.tm, manifest(rows))["status"], "stopped")
        out = self.decide(self.tm, self.om(self.tm, [RID, RID2]))
        self.assertEqual((out["status"], out["input_mode"]), ("decided", "trial"))
        self.assertEqual(self.decide(self.tm, self.om(self.tm, [RID2, RID]))["status"], "stopped")
        # 試しの run が無く、正式な run の run-start に trial_run_ids の鍵が無い・一覧でない：止まる
        for bad in (None, "x"):
            rows = json_rows(self.om(b"", []))
            if bad is None:
                del rows[0]["trial_run_ids"]
            else:
                rows[0]["trial_run_ids"] = bad
            self.assertEqual(self.decide(b"", manifest(rows))["status"], "stopped", bad)

    def test_no_trial_run(self):
        self.assertEqual(self.decide(b"", b"")["status"], "pending")
        out = self.decide(b"", self.om(b"", []))
        self.assertEqual((out["status"], out["input_mode"]), ("decided", "official"))

    def test_step2_waits_for_days(self):
        out = self.decide(b"", self.om(b"", [], days=counting.TRIAL_DAYS[:2]))
        self.assertEqual(out["status"], "pending")

    def test_run_complete_added_after_official_start_stops(self):
        """中-B1：正式な run の開始のあとに run-complete を書き足しても、1段目にはならず止まる。"""
        before = manifest(trial_rows(RID, counting.TRIAL_DAYS, complete=False, shas=self.tsha))
        om = self.om(before, [RID])
        after = before + manifest([{"kind": "run-complete", "run_id": RID, "mode": "trial"}])
        out = self.decide(after, om)
        self.assertEqual(out["status"], "stopped")
        self.assertIn("trial_manifest_sha256", out["steps"][-1]["reason"])

    def test_trial_run_ids_mismatch_stops(self):
        self.assertEqual(self.decide(self.tm, self.om(self.tm, [RID2]))["status"], "stopped")
        self.assertEqual(self.decide(self.tm, self.om(self.tm, []))["status"], "stopped")

    def test_file_problems_stop_not_step2(self):
        """中-B2：1段目のファイルの不一致・欠け・頭の行の違いは、2段目に進まず止まる。"""
        name = counting.trial_day_file_name(RID, "2015-03-03")
        changed = dict(self.files)
        changed[("trial", name)] = make_day("2015-03-03", BASE_ROWS[:3])
        missing = dict(self.files)
        del missing[("trial", name)]
        for files in (changed, missing):
            for om in (b"", self.om(self.tm, [RID])):
                self.assertEqual(self.decide(self.tm, om, files)["status"], "stopped")

    def test_wrong_day_in_file_stops(self):
        a = counting.trial_day_file_name(RID, "2015-03-02")
        b = counting.trial_day_file_name(RID, "2015-03-03")
        files = dict(self.files)
        files[("trial", b)] = files[("trial", a)]
        rows = [dict(r, sha256=hashlib.sha256(files[("trial", r["file_name"])]).hexdigest())
                if r["kind"] == "day" else r for r in json_rows(self.tm)]
        self.assertEqual(self.decide(manifest(rows), b"", files)["status"], "stopped")

    def test_wrong_mode_in_header_stops(self):
        """頭の行の mode が official の中身を、試しの run の名前で置き、sha256 も合わせたもの（軽4）。"""
        files = dict(self.files)
        for d in counting.TRIAL_DAYS:
            files[("trial", counting.trial_day_file_name(RID, d))] = make_day(d, BASE_ROWS, mode="official")
        rows = [dict(r, sha256=hashlib.sha256(files[("trial", r["file_name"])]).hexdigest())
                if r["kind"] == "day" else r for r in json_rows(self.tm)]
        out = self.decide(manifest(rows), b"", files)
        self.assertEqual(out["status"], "stopped")
        self.assertIn("mode", out["steps"][-1]["reason"])

    def test_git_check_failed_stops(self):
        self.assertEqual(self.decide(None, b"")["status"], "stopped")
        self.assertEqual(self.decide(self.tm, None)["status"], "stopped")
        tm = manifest(trial_rows(RID, counting.TRIAL_DAYS, complete=False))
        self.assertEqual(self.decide(tm, None)["status"], "stopped")

    def test_step2_file_problem_stops(self):
        files = dict(self.files)
        files[("official", counting.day_file_name("official", OID, "2015-03-02"))] = b"x"
        self.assertEqual(self.decide(b"", self.om(b"", []), files)["status"], "stopped")

    def test_no_usable_candidate_stops(self):
        tf, tsha = _files("trial", RID, [("1", "", "", False)])
        files = {**tf, **self.of}
        tm = manifest(trial_rows(RID, counting.TRIAL_DAYS, shas=tsha))
        self.assertEqual(self.decide(tm, self.om(tm, [RID]), files)["status"], "stopped")

    def test_coverage_in_output(self):
        out = self.decide(self.tm, b"")
        self.assertEqual([c["day"] for c in out["coverage"]], list(counting.TRIAL_DAYS))
        self.assertEqual(out["coverage"][0]["docs_without_any_theme"], 1)
        self.assertEqual((out["official_candidate"], out["official_status"]), ("C7", "decided"))

    def test_official_not_computable_stops(self):
        """C7 が入力のある日で計算できない（テーマの付いた文書が無い）なら止まる（4章 (3)）。"""
        rows = {d: BASE_ROWS for d in counting.TRIAL_DAYS}
        files, shas = {}, {}
        for d in counting.TRIAL_DAYS:
            gz = make_day(d, BASE_ROWS if d != "2015-03-03" else [("1", "", "", False)], mode="trial")
            files[("trial", counting.trial_day_file_name(RID, d))] = gz
            shas[d] = hashlib.sha256(gz).hexdigest()
        tm = manifest(trial_rows(RID, counting.TRIAL_DAYS, shas=shas))
        out = counting.decide(tm, b"", _reader(files))
        self.assertEqual(out["status"], "stopped")
        self.assertIn("C7", out["steps"][-1]["reason"])

    def test_runs_record(self):
        """中-B2：二つの run_id と、両方の run の3日の failed_files を出力に入れる。"""
        ff = {"2015-03-03": [{"file_time": "20150303000000", "reason": "http_404", "attempts": 1}]}
        tm = manifest([dict(r, failed_files=[]) if r["kind"] == "day" else r for r in json_rows(self.tm)])
        files = dict(self.files)
        out = counting.decide(tm, self.om(tm, [RID], failed=ff), _reader(files))
        self.assertEqual(out["runs"]["trial"]["run_id"], RID)
        self.assertEqual(out["runs"]["official"]["run_id"], OID)
        self.assertEqual(out["runs"]["official"]["failed_files"]["2015-03-03"], ff["2015-03-03"])
        self.assertEqual(out["runs"]["trial"]["failed_files"]["2015-03-02"], [])
        # day の行に failed_files の項目が無ければ None（[] と区別する。軽-6）
        out = counting.decide(self.tm, b"", _reader(files))
        self.assertIsNone(out["runs"]["trial"]["failed_files"]["2015-03-02"])
        out = counting.decide(b"", b"", _reader(files))
        self.assertEqual(out["runs"]["official"], {"run_id": None, "failed_files": None})

    def test_cli(self):
        base = os.environ.get("STATS_TEST_TMPDIR") or os.environ.get("TMPDIR")
        if not base:
            self.skipTest("一時フォルダの場所（STATS_TEST_TMPDIR か TMPDIR）を指定して流す")
        with tempfile.TemporaryDirectory(dir=base) as d:
            ts, os_ = os.path.join(d, "trial"), os.path.join(d, "official")
            os.makedirs(ts)
            os.makedirs(os_)
            for (mode, name), gz in self.files.items():
                with open(os.path.join(ts if mode == "trial" else os_, name), "wb") as f:
                    f.write(gz)
            tp, op = os.path.join(d, "trial.jsonl"), os.path.join(d, "method.jsonl")
            with open(tp, "wb") as f:
                f.write(self.tm)
            env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
            cmd = [sys.executable, "-B", os.path.join(SRC, "counting.py"), "apply"]
            # 正式な run のマニフェストのファイルが無いときは止まる（軽-4）。HEAD に無いことは EMPTY で示す
            r = subprocess.run(cmd + [tp, op, ts, os_], capture_output=True, env=env, cwd=PROJECT)
            self.assertEqual(r.returncode, 1, r.stderr)
            r = subprocess.run(cmd + [tp, "EMPTY", ts, os_], capture_output=True, env=env, cwd=PROJECT)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(json.loads(r.stdout), self.decide(self.tm, b""))
            r = subprocess.run(cmd + ["FAILED", "EMPTY", ts, os_], capture_output=True, env=env, cwd=PROJECT)
            self.assertEqual(r.returncode, 1)
            tm2 = manifest(trial_rows(RID, counting.TRIAL_DAYS, complete=False))
            with open(tp, "wb") as f:
                f.write(tm2)
            r = subprocess.run(cmd + [tp, "EMPTY", ts, os_], capture_output=True, env=env, cwd=PROJECT)
            self.assertEqual(r.returncode, 3)


class TestOrder5Status(unittest.TestCase):
    """中-3：順番5で候補が計算できないときの扱い。"""

    def test_reference_not_computable_does_not_stop(self):
        import datetime
        days = [datetime.date(2015, 3, 2) + datetime.timedelta(days=i) for i in range(4)]
        totals = {days[0]: 5, days[1]: 0, days[2]: 7}         # 2日目が0、4日目は値が無い
        missing = {days[3]}
        r = counting.order5_candidate_status("C2", totals, missing, days)
        self.assertEqual((r["status"], r["official"], r["zero_days"]), ("not_computable", False, ["2015-03-03"]))
        r = counting.order5_candidate_status("C7", totals, missing, days)
        self.assertEqual((r["status"], r["official"]), ("stop", True))
        r = counting.order5_candidate_status("C7", {d: 1 for d in days[:3]}, missing, days)
        self.assertEqual(r["status"], "ok")
        r = counting.order5_candidate_status("C4", {d: 1 for d in days[:3]}, set(), days)
        self.assertEqual((r["status"], r["zero_days"]), ("not_computable", ["2015-03-05"]))
        with self.assertRaises(ValueError):
            counting.order5_candidate_status("C9", totals, missing, days)


class TestFallback(unittest.TestCase):
    def test_fallback_when_criterion_none(self):
        # V1 がどの記事にも付かない → B3（C1 決め打ち）は該当なし → 代わりは記事の数で割る V2 の C3
        rows = [("1", "", "ZZA,1", False)] * 3
        s = base_summaries({d: rows for d in counting.TRIAL_DAYS})
        out = counting.apply_all(s)
        self.assertIsNone(out["B3"]["candidate"])
        self.assertEqual((out["B3"]["decided"], out["B3"]["decided_by"]), ("C3", "fallback"))

    def test_fallback_follows_criterion_denominator(self):
        # B1 が使えない（2日目は V1 が空）→ 代わりは「同じ数え方の合計」で割る V2 の C4
        rows = rows_with(0, 1)
        rows["2015-03-03"] = [("1", "", "ZZA,1", False)]
        out = counting.apply_all(base_summaries(rows))
        self.assertEqual((out["B1"]["candidate"], out["B1"]["decided"]), (None, "C4"))
        self.assertEqual((out["B2"]["candidate"], out["B2"]["decided"]), (None, "C3"))

    def test_orders(self):
        self.assertEqual(counting.FALLBACK_ORDER["B1"], ("C2", "C4", "C1", "C3", "C6", "C5"))
        self.assertEqual(counting.FALLBACK_ORDER["B2"], ("C1", "C3", "C2", "C4", "C5", "C6"))
        self.assertEqual(set(counting.FALLBACK_ORDER), set(counting.CRITERIA_IDS))
        for order in counting.FALLBACK_ORDER.values():
            self.assertEqual(sorted(order), sorted(counting.REFERENCE_CANDIDATE_IDS))


def json_rows(m):
    return [json.loads(x) for x in m.splitlines() if x.strip()]


class TestRecordAndDoc(unittest.TestCase):
    def test_cli_record_deterministic(self):
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
        outs = [subprocess.run([sys.executable, "-B", os.path.join(SRC, "counting.py")],
                               capture_output=True, env=env, cwd=PROJECT).stdout for _ in range(2)]
        self.assertEqual(outs[0], outs[1])
        self.assertEqual(outs[0].decode("utf-8"), counting.canonical_json())
        rec = json.loads(outs[0])
        self.assertEqual([c["id"] for c in rec["candidates"]], list(counting.CANDIDATE_IDS))
        self.assertEqual((rec["official_candidate"], rec["official_status"]), ("C7", "decided"))
        # 機械で読む定義が、コードの形式の版と一致する（中-1）
        self.assertIn("# %s %s <day>" % (counting.DAY_FORMAT_NAME, counting.DAY_FORMAT_VERSION), rec["input_format"])
        self.assertIn("official candidate not usable", rec["input_rule"]["step1"])
        self.assertIn("never leads to a new order 1b", rec["input_rule"]["stopped"])

    def test_cli_rejects_args(self):
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
        r = subprocess.run([sys.executable, "-B", os.path.join(SRC, "counting.py"), "x"],
                           capture_output=True, env=env, cwd=PROJECT)
        self.assertEqual(r.returncode, 2)

    def _table(self, name):
        with open(DOC, encoding="utf-8") as f:
            lines = f.read().split("\n")
        i = lines.index("<!-- table:%s -->" % name)
        rows = []
        for line in lines[i + 3:]:
            if not line.startswith("|"):
                break
            rows.append([c.strip() for c in line.strip("|").split("|")])
        return rows

    def test_doc_candidate_table(self):
        rows = self._table("candidates")
        self.assertEqual([r[0] for r in rows], ["`%s`" % c for c in counting.CANDIDATE_IDS])
        for r, (cid, col, den) in zip(rows, counting.CANDIDATES):
            self.assertEqual(r[1], "`%s`" % col, cid)
            self.assertEqual(r[2], "`%s`" % den, cid)
            # 集計のどの欄から計算するかが書いてある
            self.assertIn("T", r[3], cid)
            self.assertIn("D" if den == "docs" else "T", r[4], cid)

    def test_doc_criteria_table(self):
        rows = self._table("criteria")
        self.assertEqual([r[0] for r in rows], ["`%s`" % b for b in counting.CRITERIA_IDS])
        self.assertEqual(len(rows), len(counting.CRITERIA_IDS))

    def test_doc_official_and_no_recommendation(self):
        """正式な数え方の写しと、おすすめが無いこと（T-036）。"""
        rows = self._table("official")
        self.assertEqual(rows, [["`%s`" % counting.OFFICIAL_CANDIDATE,
                                 "`%s`" % counting.OWNER_DECISION["numerator_column"],
                                 "`%s`" % counting.OWNER_DECISION["denominator"],
                                 "`%s`" % counting.OWNER_DECISION["source_commit"],
                                 "`%s`" % counting.OWNER_DECISION["source_line"]]])
        with open(DOC, encoding="utf-8") as f:
            text = f.read()
        for word in ("おすすめ", "推奨", "読みA", "読みB"):
            self.assertNotIn(word, text, word)
        with open(os.path.join(SRC, "counting.py"), encoding="utf-8") as f:
            src = f.read()
        self.assertNotIn("おすすめ", src)
        self.assertNotIn("recommend", src.lower())

    def test_doc_fallback_table(self):
        """代わりの順の文書の写し（T-028 差し戻し2回目 軽3）。文書のほかの場所に順の写しを置かない。"""
        rows = self._table("fallback")
        self.assertEqual([r[0] for r in rows], ["`%s`" % b for b in counting.CRITERIA_IDS])
        for r in rows:
            bid = r[0].strip("`")
            self.assertEqual(r[1].split(), ["`%s`" % c for c in counting.FALLBACK_ORDER[bid]], bid)
        with open(DOC, encoding="utf-8") as f:
            text = f.read()
        # 6つの候補を並べた写し（「C1、C3、…」や「C1 → C3 …」の形）が表のほかに無い
        self.assertEqual(re.findall(r"C\d\s*[、→,]\s*C\d\s*[、→,]\s*C\d", text), [])

    def test_doc_constants(self):
        with open(DOC, encoding="utf-8") as f:
            text = f.read()
        self.assertIn("11/10", text)
        self.assertIn("21/20", text)
        self.assertEqual(str(counting.B4_SPREAD_LIMIT), "11/10")
        self.assertEqual(str(counting.B5_MENTION_LIMIT), "21/20")
        for d in counting.TRIAL_DAYS:
            self.assertIn(d, text)


class TestNoDataNoClock(unittest.TestCase):
    ALLOWED_IMPORTS = {"fractions", "gzip", "hashlib", "io", "json", "re", "sys"}

    def test_imports_and_clock(self):
        with open(os.path.join(SRC, "counting.py"), encoding="utf-8") as f:
            tree = ast.parse(f.read())
        names = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names.update(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom):
                names.add((node.module or "").split(".")[0])
            if isinstance(node, ast.Attribute):
                self.assertNotIn(node.attr, {"today", "now", "utcnow", "time", "environ"})
        self.assertEqual(names - self.ALLOWED_IMPORTS, set())

    def test_open_only_in_main(self):
        with open(os.path.join(SRC, "counting.py"), encoding="utf-8") as f:
            tree = ast.parse(f.read())
        for fn in tree.body:
            if isinstance(fn, ast.FunctionDef) and fn.name != "main":
                for node in ast.walk(fn):
                    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                        self.assertNotEqual(node.func.id, "open", fn.name)


if __name__ == "__main__":
    unittest.main()
