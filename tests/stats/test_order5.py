"""順番5：タグの一覧の結果（src/stats/order5.py）のテスト。T-109。

実行（プロジェクトのルートで。TMPDIR は一時フォルダの場所）:
    TMPDIR=<一時フォルダ> PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -B -m unittest tests/stats/test_order5.py -v

確かめること（データは合成だけ。本物の日の集計と本物の区分表のファイルは開かない）
  - 決まりの各段：A = 10 / N_med（欠けた日でない日の C7 の分母の中央値）、四半期ごとの存在、平均 ≥ A、除外の規則、
    欠けた日は順番4の一覧だけで決まること、翻訳の組を数えないこと（手で数えた値。TestRules）
  - 集めた入力（DayStore）で作った結果が、counting.candidate_counts の値を素直に dict にして
    tagrules.build_tag_list に渡した結果と同じこと（7つの候補・二つの設定・三つの版。TestFaithful）
  - 照合：コードの sha256、比べる版の sha256、封印の記録の値（本物の記録で）、順番4の一覧の sha256、区分表の
    sha256・頭の行・行数・名前の形、日の集計の sha256、C7 の分母と順番4の一覧の一致（TestChecks）
  - C7 が計算できない日があれば止まった記録になり、参考の候補が計算できなければその候補だけ「計算できない」
    （TestStatuses）
  - 出力：決まったキーだけ、メールアドレスの形が無い、並びが決まっている（TestOutput）
  - 関門：gkg-run-result が無ければ、マニフェストも日の集計も区分表も読まずに止まる。封印すれば通る（写しの中。
    TestGateEndToEnd。tests/collector の合成の run の仕組みを使う。ネットワークは使わない）
"""

import builtins
import copy
import datetime
import fractions
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(os.path.dirname(HERE))
SRC = os.path.join(PROJECT, "src", "stats")
SCRIPT = os.path.join(SRC, "order5.py")
DOC = os.path.join(PROJECT, "docs", "stats", "order5-tag-list.md")
COLLECTOR_TESTS = os.path.join(PROJECT, "tests", "collector")
sys.path.insert(0, SRC)

import order5 as o5  # noqa: E402

counting = o5.counting
tagrules = o5.tagrules
gkg = o5._gkg()
D = datetime.date
RID = "0123456789abcdef"
GKG_REFS = {"gkg_run_result_seq": 12, "gkg_run_result_record_sha256": "a" * 64,
            "manifest_path": "data/manifest/gdelt-gkg-method.jsonl", "manifest_lines": 5,
            "manifest_sha256": "b" * 64}
# 4日・二つの四半期（2015-03-30〜03-31 と 2015-04-01〜04-02）
BLOCK = (D(2015, 3, 30), D(2015, 4, 2))
DAYS = ("2015-03-30", "2015-03-31", "2015-04-01", "2015-04-02")
MISSING = ("2015-04-01",)
TABLE_FILE = "gdelt-themes-20261015T000000Z.tsv"


def _line(ft, n, coll, v1, v2, tr):
    cols = [b""] * gkg.N_COLUMNS
    cols[gkg.I_ID] = ("%s-%s%d" % (ft, "T" if tr else "", n)).encode()
    cols[gkg.I_D21] = ft.encode()
    cols[gkg.I_COLL] = coll.encode()
    cols[gkg.I_V1T] = v1.encode()
    cols[gkg.I_V2T] = v2.encode()
    return b"\t".join(cols) + b"\n"


def make_day(day, docs_rows):
    """gkg.serialize_day の形の日の集計（gzip のバイト列）。docs_rows：[(組, V1, V2, 翻訳か)]。"""
    ft = day.replace("-", "") + "120000"
    agg = gkg.Agg()
    vocab = {}
    for i, row in enumerate(docs_rows):
        gkg.add_line(agg, _line(ft, i, *row), ft.encode(), vocab)
    files = [{"file_time": ft, "result": "ok", "reason": None, "md5": "0" * 32, "size": 1,
              "sha256": "0" * 64, "attempts": 1, "docs": {g.decode(): n for g, n in agg.docs.items()}}]
    data = gkg.serialize_day(day, agg, files, "official")
    gkg.check_output_bytes(data, "テストの日の集計")
    return gkg.gzip_bytes(data)


def both(names):
    """V1 と V2 の両方に同じテーマを付けた文書の欄。"""
    return (";".join(names), ";".join("%s,%d" % (n, 10 * (i + 1)) for i, n in enumerate(names)))


def docs(n, names, coll="1", tr=False):
    v1, v2 = both(names)
    return [(coll, v1, v2, tr)] * n


def standard_spec(v1_empty_day=None):
    """日ごとの文書。数は TestRules の手計算に使う。

    どの日も：ZZ_ALPHA・ZZ_WAR・ZZ_EBOLA の3つが付いた文書12本、ZZ_RARE が付いた文書1本、
    翻訳の文書（ZZ_TR）1本、テーマの無い文書2本。
    3月の2日：ZZ_Q1ONLY が付いた文書12本を足す。欠けた日（04-01）：ZZ_GHOST が付いた文書20本を足す。
    C7 の分母：3月の日は 36 + 1 + 12 = 49、04-02 は 37、04-01 は 57。"""
    spec = {}
    for d in DAYS:
        rows = (docs(12, ["ZZ_ALPHA", "ZZ_WAR", "ZZ_EBOLA"]) + docs(1, ["ZZ_RARE"])
                + docs(1, ["ZZ_TR"], tr=True) + [("2", "", "", False)] * 2)
        if d.startswith("2015-03"):
            rows += docs(12, ["ZZ_Q1ONLY"])
        if d == "2015-04-01":
            rows += docs(20, ["ZZ_GHOST"])
        if d == v1_empty_day:
            rows = [(c, "", v2, tr) for c, _v1, v2, tr in rows]
        spec[d] = rows
    return spec


class Fixture:
    """day の行・日の集計・順番4の一覧・区分表の組。read は開いた名前を記録する。"""

    TABLE_NAMES = ("ZZ_ALPHA", "ZZ_ALPHA", "ZZ_WAR", "ZZ_TABLEONLY", "ZZ-SYM")

    def __init__(self, spec, missing=MISSING, run_id=RID, table_names=TABLE_NAMES):
        self.files, self.rows, self.opened = {}, [], []
        self.denom = {}
        for day, rows in spec.items():
            name = counting.day_file_name("official", run_id, day)
            data = make_day(day, rows)
            self.files[name] = data
            self.rows.append({"kind": "day", "mode": "official", "official": True, "run_id": run_id,
                              "day": day, "files_listed": 96, "files_ok": 96, "files_failed": 0,
                              "docs": len(rows), "file_name": name,
                              "sha256": hashlib.sha256(data).hexdigest()})
            s = counting.parse_day(data, expect_day=day, expect_mode="official")
            self.denom[day] = counting.candidate_counts(s, "C7")[1]
        self.order4 = {
            "block": {"name": "method", "start": BLOCK[0].isoformat(), "end": BLOCK[1].isoformat()},
            "input": dict(GKG_REFS, run_id=run_id),
            "missing_count": len(missing),
            "missing_days": [{"day": d} for d in missing],
            "c7_denominator_by_day": dict(self.denom),
        }
        self.table_bytes = ("THEME\n" + "".join(n + "\n" for n in sorted(table_names))).encode()
        self.result_row = {"file_name": TABLE_FILE, "sha256": hashlib.sha256(self.table_bytes).hexdigest(),
                           "rows": len(table_names), "kept_columns": ["THEME"], "headerless": True}

    def read(self, name):
        self.opened.append(name)
        return self.files.get(name, b"")

    def ctx(self):
        refs = {k: {"seq": i, "record_sha256": "c" * 64}
                for i, k in ((5, "order1"), (6, "order1b"), (10, "order2"), (14, "order3"))}
        refs["order4"] = {"seq": 15, "record_sha256": "c" * 64, "list_sha256": "d" * 64}
        refs["gkg_run_result"] = {"seq": 12, "record_sha256": "a" * 64}
        crit = {"input_mode": "trial", "input_run_id": "e" * 16, "input_days": list(counting.TRIAL_DAYS),
                "results": {b: {"candidate": "C1", "decided": "C1", "decided_by": "criterion", "official": False,
                                "reason": "fixed", "values": {}} for b in counting.CRITERIA_IDS}}
        return {"refs": refs, "order4_list": copy.deepcopy(self.order4), "criteria": crit,
                "order2_status": "decided", "gkg": dict(GKG_REFS)}

    def table(self):
        return o5.parse_themes_table(self.table_bytes, self.result_row)

    def build(self, versions=None, ctx=None):
        return o5.build(self.rows, BLOCK, self.read, ctx or self.ctx(), self.table(), self.result_row,
                        versions or VERSIONS)


VERSIONS = o5.load_old_versions()


def plain_inputs(fx, cid):
    """counting.candidate_counts の値を、そのまま dict にした build_tag_list の入力（比べるため）。"""
    counts, totals = {}, {}
    for r in fx.rows:
        d = D.fromisoformat(r["day"])
        s = counting.parse_day(fx.files[r["file_name"]], expect_day=r["day"], expect_mode="official")
        c, t = counting.candidate_counts(s, cid)
        totals[d] = t
        for name, n in c.items():
            counts.setdefault(name, {})[d] = n
    return counts, totals


def missing_dates(fx):
    return {D.fromisoformat(m["day"]) for m in fx.order4["missing_days"]}


class TestRules(unittest.TestCase):
    """決まりの各段を、手で数えた値と照らす（tags-naive.md 1章 (1)(2)(3)、2章 (8)、counting.md 2章）。"""

    @classmethod
    def setUpClass(cls):
        cls.fx = Fixture(standard_spec())
        cls.main, cls.extra = cls.fx.build()
        cls.off = cls.main["official"]["result"]
        cls.rows = {r["name"]: r for r in cls.off["themes"]}

    def test_a_is_k_over_median_of_usable_c7_denominators(self):
        # 欠けた日（04-01、57）を除いた 49・49・37 の中央値は 49。A = 10/49 = V
        self.assertEqual(self.fx.denom, {"2015-03-30": 49, "2015-03-31": 49, "2015-04-01": 57, "2015-04-02": 37})
        self.assertEqual(self.off["n_med"], "49/1")
        self.assertEqual(self.off["a"], "10/49")
        self.assertTrue(self.off["v_equals_a"])
        self.assertTrue(self.main["a_equals_v"])
        self.assertEqual(self.off["usable_day_count"], 3)
        self.assertEqual(tagrules.K_ARTICLES_PER_DAY, 10)

    def test_quarters_and_presence(self):
        self.assertEqual(self.off["quarters"], [["2015-03-30", "2015-03-31"], ["2015-04-01", "2015-04-02"]])
        self.assertEqual(self.rows["ZZ_ALPHA"]["quarter_counts"], [24, 12])     # 欠けた日の12は入れない
        self.assertTrue(self.rows["ZZ_ALPHA"]["present_throughout"])
        self.assertEqual(self.rows["ZZ_Q1ONLY"]["quarter_counts"], [24, 0])
        self.assertFalse(self.rows["ZZ_Q1ONLY"]["present_throughout"])
        # 欠けた日だけに出たテーマは、どの四半期でも0
        self.assertEqual(self.rows["ZZ_GHOST"]["quarter_counts"], [0, 0])
        self.assertEqual(self.rows["ZZ_GHOST"]["mean_ratio"], 0.0)

    def test_mean_ratio_and_threshold(self):
        want = (fractions.Fraction(12, 49) * 2 + fractions.Fraction(12, 37)) / 3
        self.assertAlmostEqual(self.rows["ZZ_ALPHA"]["mean_ratio"], float(want), places=15)
        self.assertTrue(self.rows["ZZ_ALPHA"]["mean_ratio_at_least_a"])
        self.assertFalse(self.rows["ZZ_RARE"]["mean_ratio_at_least_a"])
        self.assertTrue(self.rows["ZZ_RARE"]["present_throughout"])

    def test_exclusion_and_list(self):
        self.assertEqual(self.rows["ZZ_WAR"]["exclusion_matches"][0][1], "WAR")
        self.assertFalse(self.rows["ZZ_WAR"]["in_list"])
        # オーナーの選択（病名の区分は使わない）では ZZ_EBOLA は残り、すべて有効の設定では外れる
        self.assertEqual(self.off["tag_list"], ["ZZ_ALPHA", "ZZ_EBOLA"])
        self.assertEqual(self.main["settings"]["allset_result"]["tag_list"], ["ZZ_ALPHA"])
        self.assertEqual(self.main["settings"]["compare"]["only_in_new"], ["ZZ_EBOLA"])
        self.assertEqual(self.main["settings"]["compare"]["only_in_old"], [])
        self.assertEqual(self.off["enabled_optional_categories"], ["ethnic_religious_group"])

    def test_translated_not_counted_and_universe(self):
        # 翻訳の組だけに出たテーマはデータに現れない。区分表だけのテーマと記号の名前は件数0で入る
        self.assertNotIn("ZZ_TR", self.rows)
        for n in ("ZZ_TABLEONLY", "ZZ-SYM"):
            self.assertTrue(self.rows[n]["in_category_table"])
            self.assertEqual(self.rows[n]["quarter_counts"], [0, 0])
            self.assertFalse(self.rows[n]["in_list"])
        self.assertTrue(self.rows["ZZ_ALPHA"]["in_category_table"])
        self.assertFalse(self.rows["ZZ_EBOLA"]["in_category_table"])

    def test_missing_days_only_from_order4_list(self):
        """欠けた日は順番4の一覧だけで決まる。files_ok は使わない。一覧を変えれば結果が変わる。"""
        self.assertEqual(self.main["missing_days"], {"source": "order4", "count": 1, "days": ["2015-04-01"]})
        fx = Fixture(standard_spec(), missing=())
        for r in fx.rows:
            r["files_ok"] = 10                    # 72本未満でも、一覧に無ければ欠けた日にしない
        main, _x = fx.build()
        off = main["official"]["result"]
        self.assertEqual(off["usable_day_count"], 4)
        self.assertEqual(off["n_med"], "49/1")       # 37・49・49・57 の中央値
        rows = {r["name"]: r for r in off["themes"]}
        self.assertEqual(rows["ZZ_ALPHA"]["quarter_counts"], [24, 24])

    def test_themes_table_summary(self):
        t = self.main["themes_table"]
        self.assertEqual((t["rows"], t["unique_names"], t["duplicate_rows"]), (5, 4, 1))
        self.assertEqual(t["names_not_in_day_aggregate_form"], {"count": 1, "names": ["ZZ-SYM"]})
        self.assertFalse(t["description_column"])
        # データ（C7）に現れて区分表に無いもの：ZZ_EBOLA・ZZ_GHOST・ZZ_Q1ONLY・ZZ_RARE
        self.assertEqual(t["official_data_themes_not_in_table"], 4)

    def test_coverage_by_quarter(self):
        cov = self.main["coverage"]
        q0, q1 = cov["quarters"]
        # 3月の日：12 + 1 + 1 + 2 + 12 = 28 本（翻訳とテーマの無い文書も数える）、テーマの無い文書は2本
        self.assertEqual((q0["usable_days"], q0["docs_all_groups"], q0["docs_without_any_theme"]), (2, 56, 4))
        self.assertEqual((q1["usable_days"], q1["docs_all_groups"], q1["docs_without_v1_theme"]), (1, 16, 2))
        self.assertEqual(q1["ratios"]["docs_without_v2_theme"], "1/8")
        self.assertEqual(cov["total"]["docs_all_groups"], 72)
        self.assertEqual(cov["total"]["usable_days"], 3)

    def test_official_marked_once_and_references_noted(self):
        cands = self.main["candidates"]
        self.assertEqual([c["id"] for c in cands], list(counting.CANDIDATE_IDS))
        self.assertEqual([c["id"] for c in cands if c["official"]], ["C7"])
        self.assertTrue(self.main["official"]["official"])
        for c in cands:
            self.assertEqual(c["note"], None if c["official"] else o5.REF_NOTE)
        for part in (self.main["settings"], self.main["reference_criteria"], self.main["versions"]["1cb463a"]):
            self.assertIs(part["official"], False)
            self.assertEqual(part["note"], o5.REF_NOTE)
        self.assertEqual(sorted(self.main["reference_criteria"]["computed"]["results"]), list(counting.CRITERIA_IDS))
        c7 = cands[-1]
        self.assertEqual((c7["n_med"], c7["a"], c7["tag_list"]), ("49/1", "10/49", ["ZZ_ALPHA", "ZZ_EBOLA"]))

    def test_versions_split_between_main_and_extra(self):
        self.assertEqual(sorted(self.main["versions"]), ["1cb463a"])
        self.assertEqual(sorted(self.extra["versions"]), ["0e14f3b", "247fc1d"])
        self.assertIs(self.extra["sealed"], False)
        self.assertEqual(self.extra["main_sha256"], o5.sha256_of(self.main))
        v = self.main["versions"]["1cb463a"]
        self.assertIsNone(v["compare_with_official"]["enabled_optional_categories"]["old"])
        self.assertNotIn("ZZ_WAR", v["result"]["tag_list"])


class TestFaithful(unittest.TestCase):
    """DayStore と DaySeries で作った結果が、素直な dict の入力で build_tag_list を呼んだ結果と同じ。"""

    def check(self, fx):
        main, extra = fx.build()
        miss = missing_dates(fx)
        themes = {n: None for n in sorted(fx.table()["unique"])}
        counts7, totals7 = plain_inputs(fx, "C7")
        self.assertEqual(main["official"]["result"],
                         tagrules.build_tag_list(themes, counts7, totals7, miss, *BLOCK))
        self.assertEqual(main["settings"]["allset_result"],
                         tagrules.build_tag_list(themes, counts7, totals7, miss, *BLOCK,
                                                 optional=tagrules.OPTIONAL_CATEGORIES))
        for name in ("1cb463a", "0e14f3b", "247fc1d"):
            part = main["versions"] if name == "1cb463a" else extra["versions"]
            self.assertEqual(part[name]["result"],
                             VERSIONS[name].build_tag_list(themes, counts7, totals7, miss, *BLOCK))
        for c in main["candidates"]:
            if c["status"] != "ok":
                continue
            counts, totals = plain_inputs(fx, c["id"])
            r = tagrules.build_tag_list(themes, counts, totals, miss, *BLOCK)
            self.assertEqual((c["n_med"], c["a"], c["tag_list"], c["usable_day_count"]),
                             (r["n_med"], r["a"], r["tag_list"], r["usable_day_count"]), c["id"])
        return main

    def test_standard(self):
        self.check(Fixture(standard_spec()))

    def test_v1_and_v2_differ(self):
        spec = standard_spec()
        spec["2015-03-31"] = spec["2015-03-31"] + [("1", "ZZ_V1ONLY", "ZZ_V2ONLY,5;ZZ_V2ONLY,9", False)] * 15
        main = self.check(Fixture(spec))
        lists = {c["id"]: c["tag_list"] for c in main["candidates"]}
        self.assertTrue(all(lists[c] is not None for c in lists))

    def test_dayseries_is_a_mapping(self):
        fx = Fixture(standard_spec())
        want, rows, _rid = o5.check_rows(fx.rows, BLOCK)
        store, _dg = o5.read_days(want, rows, fx.read)
        counts7, _t = plain_inputs(fx, "C7")
        got = store.counts_for("C7")
        self.assertEqual(sorted(got), sorted(counts7))
        for name, series in got.items():
            self.assertEqual(dict(series.items()), counts7[name])
            self.assertEqual(len(series), len(counts7[name]))
            self.assertEqual(series.get(D(2000, 1, 1), 0), 0)
        # C1 と C2（分子の欄が同じ）は同じ分子、分母は違う
        self.assertEqual({n: dict(s) for n, s in store.counts_for("C1").items()},
                         {n: dict(s) for n, s in store.counts_for("C2").items()})
        self.assertNotEqual(store.totals["C1"], store.totals["C2"])


class TestStatuses(unittest.TestCase):

    def test_reference_candidate_not_computable_does_not_stop(self):
        fx = Fixture(standard_spec(v1_empty_day="2015-04-02"))
        main, extra = fx.build()
        st = {c["id"]: c for c in main["candidates"]}
        self.assertEqual(main["status"], "ok")
        self.assertEqual(st["C2"]["status"], "not_computable")
        self.assertEqual(st["C2"]["zero_days"], ["2015-04-02"])
        self.assertIsNone(st["C2"]["tag_list"])
        self.assertEqual(st["C1"]["status"], "ok")             # 分母は記事の数なので0にならない
        self.assertEqual(st["C7"]["status"], "ok")
        self.assertIsNotNone(extra)

    def test_c7_zero_on_usable_day_stops(self):
        spec = standard_spec()
        spec["2015-04-02"] = [("2", "", "", False)] * 3       # テーマの付いた文書が無い
        fx = Fixture(spec)
        main, extra = fx.build()
        self.assertEqual(main["status"], "stopped")
        self.assertIsNone(extra)
        st = {c["id"]: c for c in main["candidates"]}
        self.assertEqual((st["C7"]["status"], st["C7"]["zero_days"]), ("stop", ["2015-04-02"]))
        self.assertNotIn("official", main)
        self.assertTrue(all(c["tag_list"] is None for c in main["candidates"]))


class TestChecks(unittest.TestCase):

    def test_code_sha_checked_before_reading_anything(self):
        self.assertEqual(sorted(o5.check_stats_code()), sorted(o5._MODULES))
        never = mock.Mock(side_effect=AssertionError("照合より前に記録を読んではいけない"))
        for i, (rel, _sha, src) in enumerate(o5.SEALED_CODE):
            if rel not in o5._MODULES:
                continue
            bad = list(o5.SEALED_CODE)
            bad[i] = (rel, "0" * 64, src)
            with mock.patch.object(o5, "SEALED_CODE", tuple(bad)), \
                    mock.patch.object(gkg, "official_day_records", never):
                with self.assertRaisesRegex(o5.Order5Error, re.escape(rel)):
                    o5.official_record("/nonexistent", "/nonexistent")
        never.assert_not_called()

    def test_module_path_checked(self):
        other = mock.Mock(__file__=os.path.join(PROJECT, "elsewhere", "tagrules.py"))
        with mock.patch.dict(o5._MODULES, {"src/stats/tagrules.py": other}):
            with self.assertRaisesRegex(o5.Order5Error, "src/stats/tagrules.py でない"):
                o5.check_stats_code()

    def test_old_versions_checked_before_gate(self):
        never = mock.Mock(side_effect=AssertionError("照合より前に記録を読んではいけない"))
        for name, commit, _sha, _s in o5.OLD_VERSIONS:
            def show(c, p, _name=commit):
                data = o5._git_show(c, p)
                return data + b"\n# changed\n" if c == _name else data
            with mock.patch.object(gkg, "official_day_records", never):
                with self.assertRaisesRegex(o5.Order5Error, "%s の版の tagrules.py の sha256" % name):
                    o5.official_record("/nonexistent", "/nonexistent", _show=show)
        never.assert_not_called()
        # 取り出した 1cb463a の版の sha256 は、順番1の表の値と同じ
        self.assertEqual(hashlib.sha256(o5._git_show(o5.OLD_VERSIONS[0][1], "src/stats/tagrules.py")).hexdigest(),
                         "f7c325cb21bcf39c42e6d785deacbe47eacec7fb2834d2927634e446b62ce57a")

    def real_records(self):
        L = o5._ledger()
        recs = L.verify_chain(L.read_ledger(os.path.join(PROJECT, "sealed", "ledger.jsonl")))
        return L, recs, (lambda r, role: L.read_target_json(PROJECT, r, role))

    def test_pins_match_real_ledger(self):
        """本物の封印の記録（読むだけ）で、コードの値・参照・順番4の一覧が照らせる。値を一つ変えると止まる。"""
        L, recs, read = self.real_records()
        o5.check_sealed_code_in_ledger(recs, read)
        for i, (rel, _sha, src) in enumerate(o5.SEALED_CODE):
            bad = list(o5.SEALED_CODE)
            bad[i] = (rel, "1" * 64, src)
            with mock.patch.object(o5, "SEALED_CODE", tuple(bad)):
                with self.assertRaisesRegex(o5.Order5Error, re.escape(rel)):
                    o5.check_sealed_code_in_ledger(recs, read)
        ctx = o5.context_from_records(L, recs, read)
        self.assertEqual({k: v["seq"] for k, v in ctx["refs"].items()},
                         {"order1": 5, "order1b": 6, "order2": 10, "order3": 14, "order4": 15})
        self.assertEqual(ctx["refs"]["order4"]["list_sha256"], o5.PINS["order4_list_sha256"])
        self.assertEqual(ctx["order2_status"], "decided")
        self.assertEqual(sorted(ctx["criteria"]["results"]), list(counting.CRITERIA_IDS))
        for key, val in (("order4_list_sha256", "0" * 64), ("order4_seq", 16)):
            with mock.patch.dict(o5.PINS, {key: val}):
                with self.assertRaisesRegex(o5.Order5Error, "順番4"):
                    o5.context_from_records(L, recs, read)

    def test_real_themes_manifest_result_row(self):
        """本物のマニフェストの result の行（区分表のファイルは開かない）。値を変えると止まる。"""
        L, recs, _read = self.real_records()
        with open(os.path.join(PROJECT, "data", "manifest", "gdelt-themes.jsonl"), "rb") as f:
            mb = f.read()
        row = o5.themes_result_row(L, recs, mb)
        self.assertEqual(row["sha256"], o5.PINS["themes_table_sha256"])
        with mock.patch.dict(o5.PINS, {"themes_table_sha256": "0" * 64}):
            with self.assertRaisesRegex(o5.Order5Error, "決めた値と違う"):
                o5.themes_result_row(L, recs, mb)
        with self.assertRaisesRegex(o5.Order5Error, "照合に通らない"):
            o5.themes_result_row(L, recs, mb.replace(b'"kind": "result"', b'"kind": "fetch"'))
        with self.assertRaisesRegex(o5.Order5Error, "マニフェストが無い"):
            o5.themes_result_row(L, recs, None)

    def test_themes_table_checked(self):
        fx = Fixture(standard_spec())
        row = fx.result_row
        self.assertEqual(sorted(fx.table()["unique"]), ["ZZ-SYM", "ZZ_ALPHA", "ZZ_TABLEONLY", "ZZ_WAR"])
        cases = [
            (fx.table_bytes + b"ZZ_MORE\n", "sha256"),
            (fx.table_bytes.replace(b"THEME\n", b"NAME\n"), "頭の行"),
            (fx.table_bytes + b"ZZ_MORE\n", "行数"),
            (fx.table_bytes.replace(b"ZZ_WAR", b"zz_war"), "名前の形"),
            (fx.table_bytes.replace(b"ZZ_WAR", b"ZZ WAR"), "名前の形"),
            (fx.table_bytes[:-1], "改行"),
        ]
        for data, msg in cases:
            r = dict(row) if msg == "sha256" else dict(row, sha256=hashlib.sha256(data).hexdigest())
            with self.assertRaisesRegex(o5.Order5Error, msg):
                o5.parse_themes_table(data, r)

    def test_table_name_re_is_themes_py(self):
        themes = gkg._load_sibling("themes")
        self.assertEqual(o5.TABLE_NAME_RE.pattern, themes.THEME_NAME_RE.pattern)
        self.assertEqual(gkg.THEME_RE.pattern.decode(), counting.THEME_NAME_RE.pattern[2:-2])

    def test_day_file_sha_and_rows(self):
        fx = Fixture(standard_spec())
        name = fx.rows[1]["file_name"]
        fx.files[name] = make_day(fx.rows[1]["day"], [("1", "ZZ_A", "ZZ_A,1", False)])
        with self.assertRaisesRegex(o5.Order5Error, "sha256 が、day の行と一致しない"):
            fx.build()
        for mutate, msg in (
                (lambda f: f.rows.pop(), "区画の日"),
                (lambda f: f.rows[0].update(mode="trial"), "正式な run"),
                (lambda f: f.rows[0].update(run_id="f" * 16), "run_id"),
                (lambda f: f.rows[0].update(file_name="x"), "file_name"),
                (lambda f: f.rows[0].update(sha256="X" * 64), "sha256 の形"),
                (lambda f: f.rows.append(dict(f.rows[0])), "二つ")):
            fx = Fixture(standard_spec())
            mutate(fx)
            with self.assertRaisesRegex(o5.Order5Error, msg):
                fx.build()
            self.assertEqual(fx.opened, [], msg)

    def test_order4_list_checked_before_opening(self):
        for mutate, msg in (
                (lambda l: l.update(block={"name": "method", "start": "2015-03-02", "end": "2015-04-02"}), "区画"),
                (lambda l: l["input"].update(run_id="f" * 16), "run_id"),
                (lambda l: l["input"].update(manifest_sha256="0" * 64), "manifest_sha256"),
                (lambda l: l.update(missing_count=2), "missing_count"),
                (lambda l: l["missing_days"].append({"day": "2015-05-01"}) or l.update(missing_count=2), "区画の外"),
                (lambda l: l["c7_denominator_by_day"].pop("2015-03-30"), "c7_denominator_by_day")):
            fx = Fixture(standard_spec())
            ctx = fx.ctx()
            mutate(ctx["order4_list"])
            with self.assertRaisesRegex(o5.Order5Error, msg):
                fx.build(ctx=ctx)
            self.assertEqual(fx.opened, [], msg)

    def test_c7_denominator_must_match_order4(self):
        fx = Fixture(standard_spec())
        ctx = fx.ctx()
        ctx["order4_list"]["c7_denominator_by_day"]["2015-04-02"] = 38
        with self.assertRaisesRegex(o5.Order5Error, "c7_denominator_by_day と違う"):
            fx.build(ctx=ctx)

    def test_reader_rejects_paths(self):
        tmp = os.environ.get("TMPDIR") or tempfile.gettempdir()
        read = o5._reader(tmp, [])
        for bad in ("../a", "a/b", "", "..", "."):
            with self.assertRaises(o5.Order5Error):
                read(bad)
        with self.assertRaisesRegex(o5.Order5Error, "ディレクトリでない"):
            o5._reader(os.path.join(PROJECT, "no-such-dir"), [])


class TestOutput(unittest.TestCase):

    def test_canonical_bytes_and_keys(self):
        fx = Fixture(standard_spec())
        main, extra = fx.build()
        data = o5.canonical_bytes(main)
        self.assertTrue(data.endswith(b"}\n") and data.count(b"\n") == 1)
        self.assertEqual(json.loads(data.decode("utf-8")), main)
        self.assertEqual(o5.sha256_of(main), hashlib.sha256(data).hexdigest())
        # 同じ入力から同じバイト列
        main2, _x = Fixture(standard_spec()).build()
        self.assertEqual(o5.canonical_bytes(main2), data)
        self.assertTrue(o5._keys(main, set()) <= o5.ALLOWED_KEYS)
        self.assertTrue(o5._keys(extra, set()) <= o5.ALLOWED_KEYS)
        self.assertIn(o5.CITATION[0], main["citation"])
        self.assertEqual(main["label"], o5.LABEL)

    def test_check_public_stops(self):
        with self.assertRaisesRegex(o5.Order5Error, "決めていないキー"):
            o5.check_public({"label": "x", "V1PERSONS": ["ZZ"]})
        with self.assertRaisesRegex(o5.Order5Error, "絶対パス"):
            o5.check_public({"label": "/Volumes/X"})
        # メールアドレスの形のテーマ名（区分表の名前の形には合う）があれば、出力を作らずに止まる
        odd = "ZZ" + chr(64) + "EXAMPLE.COM"
        fx = Fixture(standard_spec(), table_names=Fixture.TABLE_NAMES + (odd,))
        with self.assertRaisesRegex(o5.Order5Error, "メールアドレスの形"):
            fx.build()

    def test_label_matches_doc(self):
        with open(DOC, encoding="utf-8") as f:
            text = f.read()
        found = re.findall(r"order5-tag-list-v[0-9]+", text)
        self.assertTrue(found)
        self.assertEqual(set(found), {o5.LABEL})
        self.assertIn("文書の版：`%s`" % o5.LABEL, text)

    def test_doc_cites_pins(self):
        with open(DOC, encoding="utf-8") as f:
            text = f.read()
        for _rel, sha, _src in o5.SEALED_CODE:
            self.assertIn(sha, text)
        for _n, commit, sha, _s in o5.OLD_VERSIONS:
            self.assertIn(commit, text)
            self.assertIn(sha, text)
        for v in o5.PINS.values():
            self.assertIn(str(v) if not isinstance(v, int) or v > 1000 else "seq %d" % v, text)

    def test_main_rejects_bad_args(self):
        for argv in ([], ["--store", "x"], ["--store", "a", "--themes-store", "b", "--x", "c"],
                     ["--store", "a", "--store", "b", "--out-dir", "c"]):
            self.assertEqual(o5.main(argv), 2, argv)

    def test_source_shape(self):
        with open(SCRIPT, encoding="utf-8") as f:
            src = f.read()
        body = src.split('"""', 2)[2]
        for bad in ("_day_records_of", "read_jsonl", "urllib", "socket", "LACIE", "news-stick-data"):
            self.assertNotIn(bad, body, bad)
        import inspect
        rec = inspect.getsource(o5.official_record).split('"""', 2)[2]
        order = ["check_stats_code()", "load_old_versions(", "official_day_records()", "sealed_context(",
                 "themes_result_row(", "parse_themes_table(", "build("]
        pos = [rec.index(x) for x in order]
        self.assertEqual(pos, sorted(pos))


class TestStalePycIgnored(unittest.TestCase):
    """T-096 と同じ形：__pycache__ に中身の違う古い .pyc があっても、照合したバイト列のコードが動く（写しの中）。"""

    NAMES = ("periods", "exclusion", "tagrules", "counting")

    def setUp(self):
        import py_compile
        self.tmp = tempfile.mkdtemp(prefix="o5-pyc-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.stats = os.path.join(self.tmp, "src", "stats")
        os.makedirs(os.path.join(self.stats, "__pycache__"))
        for n in ("order5",) + self.NAMES:
            shutil.copyfile(os.path.join(SRC, n + ".py"), os.path.join(self.stats, n + ".py"))
        for n in self.NAMES:
            with open(os.path.join(SRC, n + ".py"), "rb") as f:
                src = f.read() + b"\nSTALE_PYC = True\n"
            alt = os.path.join(self.tmp, n + "_stale.py")
            with open(alt, "wb") as f:
                f.write(src)
            cfile = os.path.join(self.stats, "__pycache__", "%s.%s.pyc" % (n, sys.implementation.cache_tag))
            py_compile.compile(alt, cfile=cfile, doraise=True,
                               invalidation_mode=py_compile.PycInvalidationMode.UNCHECKED_HASH)

    def test_order5_runs_verified_bytes(self):
        code = ("import sys, json; sys.path.insert(0, %r)\n"
                "import order5 as o\n"
                "o.check_stats_code()\n"
                "print(json.dumps([hasattr(m, 'STALE_PYC') for m in (o.periods, o.exclusion, o.tagrules, o.counting)]"
                " + [o.tagrules.exclusion is o.exclusion, 'tagrules' in sys.modules, 'exclusion' in sys.modules]))"
                % self.stats)
        r = subprocess.run([sys.executable, "-B", "-c", code], capture_output=True, cwd=self.tmp,
                           env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
        self.assertEqual(r.returncode, 0, r.stderr.decode(errors="replace"))
        self.assertEqual(json.loads(r.stdout.decode()), [False, False, False, False, True, False, False])


def _load_e2e():
    if COLLECTOR_TESTS not in sys.path:
        sys.path.insert(0, COLLECTOR_TESTS)
    import test_acquire_gkg  # noqa: E402
    return test_acquire_gkg


tag = _load_e2e()
taf, tg, ledger = tag.taf, tag.tg, tag.ledger
BLOCK3 = (D(2015, 3, 2), D(2015, 3, 4))
DAYS3 = ("2015-03-02", "2015-03-03", "2015-03-04")


class OpenRecorder:
    """builtins.open と os.open の呼び出しを記録する（中身はそのまま開く）。"""

    def __init__(self):
        self.paths = []
        self._open, self._os_open = builtins.open, os.open

    def _b(self, file, *a, **k):
        if isinstance(file, (str, bytes, os.PathLike)):
            self.paths.append(os.fsdecode(file))
        return self._open(file, *a, **k)

    def _o(self, path, *a, **k):
        self.paths.append(os.fsdecode(path))
        return self._os_open(path, *a, **k)

    def __enter__(self):
        self._p = [mock.patch.object(builtins, "open", self._b), mock.patch.object(os, "open", self._o)]
        for p in self._p:
            p.start()
        return self

    def __exit__(self, *exc):
        for p in reversed(self._p):
            p.stop()
        return False


class TestGateEndToEnd(tag.E2ECase):
    """合成の正式な run（3日）を写しの中で作り、関門を通して、収集係のコードが書いた日の集計から作る。
    写しの封印の記録に、順番1b（2件目）・2・3・4 の仮の記録と、区分表のマニフェストを足す。"""

    def setUp(self):
        super().setUp()
        self.themes_store = os.path.join(self.tmp, "themes-store")
        os.makedirs(self.themes_store)

    def full_official(self):
        self.add_method_access()
        out = self.acquire_official(self.gseams())
        self.commit_manifest("正式な run の結果")
        return out

    def ledger_path(self):
        return os.path.join(self.project, "sealed", "ledger.jsonl")

    def records(self):
        return ledger.verify_chain(ledger.read_ledger(self.ledger_path()))

    def add_doc(self, kind, doc):
        content = ledger.canonical_line(doc) + b"\n"
        sha = ledger.sha256_hex(content)
        rel = "sealed/%s-%s.json" % (kind, sha)
        ledger.write_once(os.path.join(self.project, rel), content)
        ledger.append_record(self.ledger_path(), kind, [{"path": rel, "role": kind, "sha256": sha}], "", tg.NOW)
        seq = len(self.records())
        tag.stamp.stamp_seq(self.ledger_path(), seq, "ots", runner=taf.FakeOts())
        return [r for r in self.records() if r["seq"] == seq][0]

    def seal_result(self, run_id):
        tag.seal_gkg_result.seal(self.project, "official", run_id, tg.NOW, "ots", runner=taf.FakeOts())

    def add_stats_records(self, run_id):
        recs = self.records()
        (res,) = [r for r in recs if r["kind"] == ledger.GKG_RESULT_KIND]
        gdoc = ledger.read_target_json(self.project, res, ledger.GKG_RESULT_KIND)
        gkg_refs = {"gkg_run_result_seq": res["seq"],
                    "gkg_run_result_record_sha256": ledger.sha256_hex(ledger.canonical_line(res)),
                    "manifest_path": gdoc["manifest_path"], "manifest_lines": gdoc["manifest_lines"],
                    "manifest_sha256": gdoc["manifest_sha256"]}
        data = ledger.read_ledger(self.ledger_path())
        d1b = tag._sealer_test_ledger.order_doc_for(
            data, len(recs) + 1, ledger.ORDER1B_KIND,
            counting={"candidate_ids": list(counting.CANDIDATE_IDS), "criteria_ids": list(counting.CRITERIA_IDS),
                      "official_candidate": "C7"})
        o1b = self.add_doc(ledger.ORDER1B_KIND, d1b)
        res_b = {b: {"candidate": "C1", "decided": "C1", "decided_by": "criterion", "official": False,
                     "reason": "fixed", "values": {}} for b in counting.CRITERIA_IDS}
        o2 = self.add_doc(ledger.ORDER2_KIND, {"kind": ledger.ORDER2_KIND, "ref_1b_seq": o1b["seq"],
                                               "counting_output": {"status": "decided", "input_mode": "trial",
                                                                   "input_run_id": "e" * 16,
                                                                   "inputs": [{"day": d} for d in DAYS3],
                                                                   "results": res_b}})
        (o1,) = [r for r in self.records() if r["kind"] == ledger.ORDER1_KIND]
        ref = lambda r: {"seq": r["seq"], "record_sha256": ledger.sha256_hex(ledger.canonical_line(r))}  # noqa
        o3 = self.add_doc(ledger.ORDER3_KIND, {"kind": ledger.ORDER3_KIND, "ref_order1": ref(o1),
                                               "ref_1b": ref(o1b), "ref_order2": ref(o2)})
        denom = {}
        for d in DAYS3:
            with open(os.path.join(self.gkg_store, counting.day_file_name("official", run_id, d)), "rb") as f:
                s = counting.parse_day(f.read(), expect_day=d, expect_mode="official")
            denom[d] = counting.candidate_counts(s, "C7")[1]
        lst = {"block": {"name": "method", "start": DAYS3[0], "end": DAYS3[-1]},
               "input": dict(gkg_refs, run_id=run_id), "missing_count": 1,
               "missing_days": [{"day": "2015-03-03"}], "c7_denominator_by_day": denom}
        list_sha = hashlib.sha256(o5.order4_list_bytes(lst)).hexdigest()
        o4 = self.add_doc(ledger.ORDER4_KIND, {"kind": ledger.ORDER4_KIND, "list": lst, "list_sha256": list_sha})
        # 区分表のマニフェスト（本物の行の形で、写しの順番1を指す）とファイル
        table = b"THEME\nQQ_ALPHA\nQQ_EXTRA\n"
        with open(os.path.join(PROJECT, "data", "manifest", "gdelt-themes.jsonl"), "rb") as f:
            real = [json.loads(x) for x in f.read().splitlines() if x.strip()]
        att, fet, resr = [dict(x) for x in real[-3:]]
        for row in (att, resr):
            row.update(exclusion_rule_seq=o1["seq"], exclusion_rule_record_sha256=ref(o1)["record_sha256"])
        resr.update(file_name=TABLE_FILE, sha256=hashlib.sha256(table).hexdigest(), rows=2)
        with open(os.path.join(self.project, "data", "manifest", "gdelt-themes.jsonl"), "wb") as f:
            f.write(b"".join(json.dumps(x, sort_keys=True).encode() + b"\n" for x in (att, fet, resr)))
        with open(os.path.join(self.themes_store, TABLE_FILE), "wb") as f:
            f.write(table)
        self.pins = {"order4_seq": o4["seq"], "order4_list_sha256": list_sha,
                     "themes_table_sha256": resr["sha256"], "themes_table_rows": 2}
        return o4

    def entry(self, opened=None):
        return self.run_with_root(o5.official_record, self.gkg_store, self.themes_store, BLOCK3, opened)

    def test_stops_without_gate_then_passes(self):
        out = self.full_official()
        run_id = out["run_id"]
        never = mock.Mock(side_effect=AssertionError("関門より前にマニフェストや日の集計を読んではいけない"))
        with mock.patch.object(gkg, "read_bytes_nofollow", never):
            with self.assertRaises(gkg.GkgError) as cm:
                self.entry()
        never.assert_not_called()
        self.assertIsInstance(cm.exception.__cause__, ledger.GkgRunResultRequired)

        self.seal_result(run_id)
        o4 = self.add_stats_records(run_id)
        # 写しの順番1（seq 5）は仮の中身なので、exclusion.py の値と照らすと止まる（日の集計は開かない）
        opened = []
        with mock.patch.dict(o5.PINS, self.pins):
            with self.assertRaisesRegex(o5.Order5Error, r"src/stats/exclusion.py の sha256 が、seq 5"):
                self.entry(opened)
        self.assertEqual(opened, [])
        # 写しでは、本物と同じ seq 1（periods）の照合だけを残して流す
        opened = []
        only_periods = tuple(x for x in o5.SEALED_CODE if x[0] == "src/stats/periods.py")
        with mock.patch.object(o5, "SEALED_CODE", only_periods), mock.patch.dict(o5.PINS, self.pins), \
                OpenRecorder() as rec:
            main, extra = self.entry(opened)
        names = [counting.day_file_name("official", run_id, d) for d in DAYS3]
        self.assertEqual(opened, [TABLE_FILE] + names)
        in_vol = [p for p in rec.paths if os.path.abspath(p).startswith(self.volume)]
        self.assertEqual(sorted(os.path.basename(p) for p in in_vol), sorted(names))
        self.assertFalse(any(os.path.abspath(p).startswith(self.home) for p in rec.paths))
        self.assertEqual(main["status"], "ok")
        self.assertEqual(main["input"]["run_id"], run_id)
        self.assertEqual(main["refs"]["order4"]["seq"], o4["seq"])
        self.assertEqual(main["missing_days"]["days"], ["2015-03-03"])
        self.assertEqual(main["official"]["result"]["usable_day_count"], 2)
        rows = {r["name"]: r for r in main["official"]["result"]["themes"]}
        self.assertTrue(rows["QQ_EXTRA"]["in_category_table"])
        self.assertEqual(main["themes_table"]["unique_names"], 2)
        self.assertIsNotNone(extra)

        # 区分表のファイルを書き換えると止まる。日の集計を書き換えると止まる
        tpath = os.path.join(self.themes_store, TABLE_FILE)
        with open(tpath, "ab") as f:
            f.write(b"QQ_MORE\n")
        with mock.patch.object(o5, "SEALED_CODE", only_periods), mock.patch.dict(o5.PINS, self.pins):
            with self.assertRaisesRegex(o5.Order5Error, "区分表のファイルの sha256"):
                self.entry()
        with open(tpath, "wb") as f:
            f.write(b"THEME\nQQ_ALPHA\nQQ_EXTRA\n")
        path = os.path.join(self.gkg_store, names[0])
        with open(path, "rb") as f:
            body = f.read()
        with open(path, "wb") as f:
            f.write(make_day(DAYS3[0], [("1", "ZZ_A", "ZZ_A,1", False)]))
        with mock.patch.object(o5, "SEALED_CODE", only_periods), mock.patch.dict(o5.PINS, self.pins):
            with self.assertRaisesRegex(o5.Order5Error, "sha256 が、day の行と一致しない"):
                self.entry()
        with open(path, "wb") as f:
            f.write(body)
        with mock.patch.object(o5, "SEALED_CODE", only_periods), mock.patch.dict(o5.PINS, self.pins):
            again, _x = self.entry()
        self.assertEqual(o5.sha256_of(again), o5.sha256_of(main))


if __name__ == "__main__":
    unittest.main()
