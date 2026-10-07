"""タグを入れる規則（src/stats/tagrules.py）のテスト（T-019〜T-022）。

実行（プロジェクトのルートで）:
    PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest discover -s tests/stats -v

データもネットワークも使わない。データはすべてテストの中で作る合成の値。照合に使う名前は、すべて
テストのために作ったもの。
このファイルは、入れる規則と除外の規則と一緒に、区分表の取得より前に順番1で封印する対象である
（docs/stats/tags-naive.md 5章）。T-022 の差し戻し1回目で test_t019.py から分けた。読むのは
src/stats/ の tagrules.py と exclusion.py と、同じく順番1で封印する docs/stats/tags-naive.md だけ。
"""

import ast
import datetime
import fractions
import json
import os
import random
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(os.path.dirname(HERE))
SRC = os.path.join(PROJECT, "src", "stats")
DOC = os.path.join(PROJECT, "docs", "stats", "tags-naive.md")
SCRIPT = os.path.join(SRC, "tagrules.py")
sys.path.insert(0, SRC)

import exclusion  # noqa: E402
import tagrules  # noqa: E402

D = datetime.date
DAY = datetime.timedelta(days=1)
F = fractions.Fraction

# 手法を作る期間の区画（docs/stats/periods.md。periods.py と一致することは test_t019.py で確かめる）。
METHOD_START, METHOD_END = D(2015, 3, 2), D(2020, 12, 14)


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
            "QQ_A": {d: 10 for d in ds},                 # 平均 = A ちょうど → 入る
            "QQ_B": {d: 9 for d in ds},                  # A 未満
            "QQ_C": {d: 50 for d in ds if d.month >= 4},  # 最初の四半期に無い
            "MILITARY_X": {d: 100 for d in ds},            # 除外の語
            "QQ_D": {d: 100 for d in ds},                # 説明で除外
        }
        themes = {"QQ_A": None, "QQ_B": "", "QQ_C": "x", "MILITARY_X": "", "QQ_D": "flood relief",
                  "QQ_E": "never appears"}
        r = tagrules.build_tag_list(themes, counts, totals, set(), self.S, self.E)
        self.assertEqual(r["tag_list"], ["QQ_A"])
        rows = {x["name"]: x for x in r["themes"]}
        self.assertTrue(rows["QQ_A"]["mean_ratio_at_least_a"])
        self.assertFalse(rows["QQ_B"]["mean_ratio_at_least_a"])
        self.assertFalse(rows["QQ_C"]["present_throughout"])
        self.assertEqual(rows["QQ_C"]["quarter_counts"][0], 0)
        self.assertEqual(rows["MILITARY_X"]["exclusion_matches"], [["conflict_violence", "MILITARY", "name", "exact"]])
        self.assertEqual(rows["QQ_D"]["exclusion_matches"], [["disaster", "FLOOD", "description", "exact"]])
        self.assertFalse(rows["QQ_E"]["present_throughout"])
        self.assertTrue(rows["QQ_A"]["in_category_table"])
        self.assertEqual([x["name"] for x in r["themes"]], sorted(rows))
        self.assertTrue(r["v_equals_a"])

    def test_theme_only_in_data_is_considered(self):
        ds = self.days()
        r = tagrules.build_tag_list({}, {"QQ_Z": {d: 20 for d in ds}}, self.base(), set(), self.S, self.E)
        self.assertEqual(r["tag_list"], ["QQ_Z"])
        self.assertFalse(r["themes"][0]["in_category_table"])

    def test_missing_days_not_counted(self):
        ds = self.days()
        march = [d for d in ds if d.month == 3]
        missing = set(march)  # 最初の四半期の使える日が無い → その四半期は条件から外す
        totals = self.base()
        counts = {"QQ_C": {d: 50 for d in ds if d.month >= 4}}
        r = tagrules.build_tag_list({}, counts, totals, missing, self.S, self.E)
        self.assertEqual(r["quarters_without_usable_days"], [0])
        self.assertEqual(r["tag_list"], ["QQ_C"])
        self.assertIsNone(r["themes"][0]["quarter_counts"][0])
        # 欠けた日の件数は存在の条件にも平均にも入らない
        missing2 = {march[0]}
        counts2 = {"QQ_Q": {march[0]: 10 ** 6}}
        r2 = tagrules.build_tag_list({}, counts2, totals, missing2, self.S, self.E)
        self.assertEqual(r2["themes"][0]["mean_ratio"], 0.0)
        self.assertEqual(r2["themes"][0]["quarter_counts"], [0, 0])

    def test_rejects_dates_outside_block(self):
        totals = self.base()
        later = {self.E + DAY: 5}
        with self.assertRaises(ValueError):
            tagrules.build_tag_list({}, {"QQ_A": later}, totals, set(), self.S, self.E)
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

    def test_two_settings_distinguishable(self):
        ds = self.days()
        counts = {"QQ_A": {d: 20 for d in ds}, "QQ_EBOLA": {d: 20 for d in ds}}
        allset = tagrules.build_tag_list({}, counts, self.base(), set(), self.S, self.E,
                                         optional=tagrules.OPTIONAL_CATEGORIES)
        planb = tagrules.build_tag_list({}, counts, self.base(), set(), self.S, self.E,
                                        optional=("ethnic_religious_group",))
        default = tagrules.build_tag_list({}, counts, self.base(), set(), self.S, self.E)
        self.assertEqual(allset["enabled_optional_categories"], ["disease_named", "ethnic_religious_group"])
        self.assertEqual(planb["enabled_optional_categories"], ["ethnic_religious_group"])
        self.assertEqual(default["enabled_optional_categories"], list(tagrules.ENABLED_OPTIONAL_CATEGORIES))
        self.assertNotEqual(allset["enabled_optional_categories"], planb["enabled_optional_categories"])
        self.assertEqual(allset["tag_list"], ["QQ_A"])
        self.assertEqual(planb["tag_list"], ["QQ_A", "QQ_EBOLA"])
        self.assertEqual(tagrules.compare_lists(allset, planb),
                         {"only_in_old": [], "only_in_new": ["QQ_EBOLA"], "in_both": 1,
                          "enabled_optional_categories": {
                              "old": ["disease_named", "ethnic_religious_group"],
                              "new": ["ethnic_religious_group"]}})
        with self.assertRaises(ValueError):
            tagrules.build_tag_list({}, counts, self.base(), set(), self.S, self.E, optional=("crime",))

    def result(self, names, tag_list, block=("2019-03-01", "2019-06-30"), a="1/100", n_med="1000/1",
               enabled=None, usable=122, qcounts=None, means=None):
        qcounts = qcounts or {}
        means = means or {}
        r = {"block_start": block[0], "block_end": block[1], "a": a, "n_med": n_med,
             "usable_day_count": usable,
             "quarters": [["2019-03-01", "2019-03-31"], ["2019-04-01", "2019-06-30"]],
             "quarters_without_usable_days": [],
             "themes": [{"name": n, "in_category_table": False, "quarter_counts": qcounts.get(n, [1, 1]),
                         "mean_ratio": means.get(n, 0.5)} for n in names],
             "tag_list": tag_list}
        if enabled is not None:
            r["enabled_optional_categories"] = enabled
        return r

    def test_compare_lists(self):
        names = ["A", "B", "C", "D", "E"]
        old = self.result(names, ["A", "B", "C"])  # 1cb463a の版のように設定を持たない結果
        new = self.result(names, ["B", "C", "D", "E"], enabled=["ethnic_religious_group"])
        self.assertEqual(tagrules.compare_lists(old, new),
                         {"only_in_old": ["A"], "only_in_new": ["D", "E"], "in_both": 2,
                          "enabled_optional_categories": {"old": None, "new": ["ethnic_religious_group"]}})

    def test_compare_lists_requires_same_input(self):
        names = ["A", "B"]
        base = self.result(names, ["A"])
        for other in (self.result(names, ["A"], block=("2019-03-02", "2019-06-30")),
                      self.result(names, ["A"], block=("2019-03-01", "2019-06-29")),
                      self.result(names, ["A"], a="1/99"),
                      self.result(names, ["A"], n_med="999/1"),
                      self.result(["A", "B", "C"], ["A"]),
                      self.result(names, ["A"], usable=121),
                      self.result(names, ["A"], qcounts={"B": [1, 2]}),
                      self.result(names, ["A"], means={"A": 0.25})):
            with self.assertRaises(ValueError):
                tagrules.compare_lists(base, other)
        # 同じ入力から作った二つの実の結果は比べられる
        ds = self.days()
        counts = {"QQ_A": {d: 20 for d in ds}}
        r1 = tagrules.build_tag_list({}, counts, self.base(), set(), self.S, self.E)
        r2 = tagrules.build_tag_list({}, counts, self.base(), set(), self.S, self.E,
                                     optional=tagrules.OPTIONAL_CATEGORIES)
        tagrules.compare_lists(r1, r2)
        r3 = tagrules.build_tag_list({}, counts, self.base(2000), set(), self.S, self.E)
        with self.assertRaises(ValueError):
            tagrules.compare_lists(r1, r3)

    def test_deterministic(self):
        ds = self.days()
        rng = random.Random(7)
        counts = {"T%02d" % i: {d: rng.randrange(0, 30) for d in ds} for i in range(20)}
        a = tagrules.build_tag_list({}, counts, self.base(), set(), self.S, self.E)
        b = tagrules.build_tag_list({}, dict(reversed(list(counts.items()))), self.base(), set(), self.S, self.E)
        self.assertEqual(json.dumps(a, sort_keys=True), json.dumps(b, sort_keys=True))

    def test_compare_lists_checks_usable_days_and_quarter_counts(self):
        # L-1：a と n_med とテーマの集合が同じでも、欠けた日の一覧や件数が違えば止まる。
        ds = self.days()
        counts = {"QQ_A": {d: 20 for d in ds}, "QQ_B": {d: 1 for d in ds}}
        r1 = tagrules.build_tag_list({}, counts, self.base(), set(), self.S, self.E)
        # 欠けた日を1日足す（全体の報道量は一定なので a と n_med は変わらない）。
        r2 = tagrules.build_tag_list({}, counts, self.base(), {ds[-1]}, self.S, self.E)
        self.assertEqual((r1["a"], r1["n_med"]), (r2["a"], r2["n_med"]))
        self.assertNotEqual(r1["usable_day_count"], r2["usable_day_count"])
        with self.assertRaises(ValueError):
            tagrules.compare_lists(r1, r2)
        # 一つのテーマの件数だけを変える（a・n_med・テーマの集合・欠けた日は同じ）。
        counts3 = {"QQ_A": {d: 20 for d in ds}, "QQ_B": {d: 1 for d in ds[1:]}}
        r3 = tagrules.build_tag_list({}, counts3, self.base(), set(), self.S, self.E)
        self.assertEqual((r1["a"], r1["n_med"], r1["usable_day_count"]),
                         (r3["a"], r3["n_med"], r3["usable_day_count"]))
        with self.assertRaises(ValueError):
            tagrules.compare_lists(r1, r3)
        # 同じ入力なら、設定を変えても比べられる。
        r4 = tagrules.build_tag_list({}, counts, self.base(), set(), self.S, self.E,
                                     optional=tagrules.OPTIONAL_CATEGORIES)
        self.assertEqual(tagrules.compare_lists(r1, r4)["in_both"], 1)



class TestTagrulesOutput(unittest.TestCase):
    def run_cli(self, *args):
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
        return subprocess.run([sys.executable, "-B", SCRIPT, *args],
                              capture_output=True, text=True, env=env, cwd=PROJECT)

    def test_cli_deterministic(self):
        a, b = self.run_cli(), self.run_cli()
        self.assertEqual(a.returncode, 0, a.stderr)
        self.assertEqual(a.stdout, b.stdout)
        self.assertEqual(a.stdout, tagrules.canonical_json())

    def test_cli_rejects_args(self):
        self.assertEqual(self.run_cli("--x").returncode, 2)

    def test_tagrules_output(self):
        rec = json.loads(tagrules.canonical_json())
        self.assertEqual(rec["inclusion"]["k_articles_per_day"], 10)
        self.assertEqual(rec["inclusion"]["min_count_per_quarter"], 1)
        self.assertEqual(rec["exclusion"]["per_theme_exceptions"], "none")
        self.assertEqual(rec["exclusion"], json.loads(exclusion.canonical_json()))
        self.assertEqual(rec["exclusion"]["terms"], {k: list(v) for k, v in tagrules.EXCLUSION_TERMS.items()})

    def test_seal_order_does_not_wait_for_counting(self):
        # M-1：入れる規則は順番1で封印する。数え方を待つ・数え方のあとに封印する、という文を持たない。
        rec = json.loads(tagrules.canonical_json())
        self.assertIn("order 1", rec["seal_order"])
        self.assertIn("before the category table acquisition", rec["seal_order"])
        self.assertIn("before method-access", rec["seal_order"])
        self.assertIn("does not change K, the presence rule or the A formula", rec["counting"])
        self.assertNotIn("sealed only after", rec["counting"])


class TestTagrulesNoDataNoNetwork(unittest.TestCase):
    def test_imports_clock_files(self):
        with open(SCRIPT, encoding="utf-8") as f:
            tree = ast.parse(f.read())
        names = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names.update(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom):
                names.add((node.module or "").split(".")[0])
            if isinstance(node, ast.Attribute):
                self.assertNotIn(node.attr, {"today", "now", "utcnow", "time"})
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                self.assertNotEqual(node.func.id, "open")
        self.assertEqual(names - {"datetime", "fractions", "json", "math", "sys", "exclusion"}, set())


if __name__ == "__main__":
    unittest.main()
