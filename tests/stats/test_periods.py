"""過去データの三期間の区切り（src/stats/periods.py）のテスト。T-004。

実行（プロジェクトのルートで。__pycache__ を作らないよう、必ず次の形で）:
    PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest discover -s tests/stats -v

データもネットワークも使わない。
"""

import ast
import datetime
import json
import os
import re
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(os.path.dirname(HERE))
SRC = os.path.join(PROJECT, "src", "stats")
SCRIPT = os.path.join(SRC, "periods.py")
DOC = os.path.join(PROJECT, "docs", "stats", "periods.md")
sys.path.insert(0, SRC)

import periods  # noqa: E402

D = datetime.date
DAY = datetime.timedelta(days=1)

# 割り振り（T-004）で与えられた固定の事実。
FACT_EARLIEST_METHOD_START = D(2015, 3, 2)
FACT_TODAY = D(2026, 10, 6)
PROPOSED_HORIZON_DAYS = 30  # 未決事項3の案

# この提案で固定する区画の境目（テストの側にも直接書き、コードの FROZEN_BLOCKS と照合する）。
V1_BLOCKS = (
    ("method", D(2015, 3, 2), D(2020, 12, 14)),
    ("threshold", D(2020, 12, 15), D(2023, 11, 6)),
    ("baseline", D(2023, 11, 7), D(2026, 9, 30)),
)
V1_FROZEN_CONSTANTS = {
    "DATA_START": D(2015, 3, 2),
    "TODAY": D(2026, 10, 6),
    "DATA_SETTLE_DAYS": 5,
    "BLOCK_WEIGHTS": (2, 1, 1),
    "MEDIAN_WINDOW_DAYS": 365,
    "SEASONAL_MARGIN_DAYS": 35,
}


def blocks_of(ps):
    return tuple((p["name"], p["block_start"], p["block_end"]) for p in ps)


class TestLayout(unittest.TestCase):
    def setUp(self):
        self.ps = periods.compute_periods()

    def test_three_periods_in_order(self):
        self.assertEqual([p["name"] for p in self.ps], ["method", "threshold", "baseline"])

    def test_blocks_contiguous_and_disjoint(self):
        for a, b in zip(self.ps, self.ps[1:]):
            self.assertLess(a["block_end"], b["block_start"])
            self.assertEqual(a["block_end"] + DAY, b["block_start"])
        for p in self.ps:
            self.assertLessEqual(p["block_start"], p["block_end"])

    def test_prediction_ranges_inside_blocks(self):
        for p in self.ps:
            self.assertLessEqual(p["block_start"], p["prediction_first"])
            self.assertLessEqual(p["prediction_first"], p["prediction_last"])
            self.assertLessEqual(p["prediction_last"], p["block_end"])

    def test_prediction_ranges_disjoint_with_embargo(self):
        for a, b in zip(self.ps, self.ps[1:]):
            gap = (b["prediction_first"] - a["prediction_last"]).days - 1
            self.assertGreaterEqual(gap, periods.EMBARGO_DAYS)

    def test_judgment_stays_inside_own_block(self):
        for p in self.ps:
            last_read = p["prediction_last"] + datetime.timedelta(days=periods.EMBARGO_DAYS)
            self.assertLessEqual(last_read, p["block_end"])

    def test_embargo_covers_proposed_horizon(self):
        self.assertTrue(periods.horizon_is_valid(PROPOSED_HORIZON_DAYS))
        self.assertTrue(periods.horizon_is_valid(periods.EMBARGO_DAYS))
        self.assertFalse(periods.horizon_is_valid(periods.EMBARGO_DAYS + 1))
        self.assertFalse(periods.horizon_is_valid(0))

    def test_method_starts_on_or_after_clean_data(self):
        m = self.ps[0]
        self.assertGreaterEqual(m["block_start"], FACT_EARLIEST_METHOD_START)
        self.assertEqual(periods.DATA_START, FACT_EARLIEST_METHOD_START)

    def test_method_lookback_inside_method_block(self):
        m = self.ps[0]
        first_input_day = m["prediction_first"] - datetime.timedelta(days=periods.LOOKBACK_DAYS)
        self.assertGreaterEqual(first_input_day, m["block_start"])
        self.assertGreaterEqual(periods.LOOKBACK_DAYS, periods.MEDIAN_WINDOW_DAYS)

    def test_later_lookback_never_before_data_start(self):
        for p in self.ps[1:]:
            first_input_day = p["prediction_first"] - datetime.timedelta(days=periods.LOOKBACK_DAYS)
            self.assertGreaterEqual(first_input_day, periods.DATA_START)

    def test_latest_end_results_complete_before_today(self):
        b = self.ps[-1]
        self.assertEqual(periods.TODAY, FACT_TODAY)
        last_read = b["prediction_last"] + datetime.timedelta(days=periods.EMBARGO_DAYS)
        self.assertLessEqual(last_read, b["block_end"])
        self.assertLess(b["block_end"], FACT_TODAY)
        self.assertLessEqual(
            b["block_end"], FACT_TODAY - datetime.timedelta(days=periods.DATA_SETTLE_DAYS)
        )

    def test_each_period_has_weekly_predictions(self):
        for p in self.ps:
            ds = periods.prediction_dates(p)
            self.assertGreaterEqual(len(ds), 104, p["name"])
            for d in ds:
                self.assertEqual(d.weekday(), periods.PREDICTION_WEEKDAY)
                self.assertLessEqual(p["prediction_first"], d)
                self.assertLessEqual(d, p["prediction_last"])
            # 範囲の中で、最初の月曜より前・最後の月曜より後に月曜は無い。
            self.assertLess((ds[0] - p["prediction_first"]).days, 7)
            self.assertLess((p["prediction_last"] - ds[-1]).days, 7)


# ---------------------------------------------------------------------------
# 文書の表とコードの照合
# ---------------------------------------------------------------------------

def read_doc():
    with open(DOC, encoding="utf-8") as f:
        return f.read()


def read_table(marker, text=None):
    """文書の <!-- table:marker --> の直後にある表を (見出し, 本体の行) で返す。"""
    lines = (read_doc() if text is None else text).splitlines()
    tag = "<!-- table:%s -->" % marker
    idx = [i for i, ln in enumerate(lines) if ln.strip() == tag]
    if len(idx) != 1:
        raise AssertionError("表の印が1つではない: " + marker)
    rows = []
    i = idx[0] + 1
    while i < len(lines) and lines[i].startswith("|"):
        rows.append([c.strip() for c in lines[i].strip().strip("|").split("|")])
        i += 1
    if len(rows) < 3 or not all(set(c) <= set("-: ") for c in rows[1]):
        raise AssertionError("表の形が想定と違う: " + marker)
    header, body = rows[0], rows[2:]
    for r in body:
        if len(r) != len(header):
            raise AssertionError("列の数が見出しと違う: " + marker)
    return header, body


def iso(d):
    return d.isoformat()


PERIODS_HEADER = ["期間", "区画の始まり", "区画の終わり", "区画の日数", "予言日の範囲の始まり",
                  "予言日の範囲の終わり", "予言日の範囲の日数", "最初の月曜", "最後の月曜", "月曜の回数"]


def expected_periods_rows():
    rows = []
    for p in periods.compute_periods():
        ds = periods.prediction_dates(p)
        rows.append([
            p["label_ja"], iso(p["block_start"]), iso(p["block_end"]),
            str((p["block_end"] - p["block_start"]).days + 1),
            iso(p["prediction_first"]), iso(p["prediction_last"]),
            str((p["prediction_last"] - p["prediction_first"]).days + 1),
            iso(ds[0]), iso(ds[-1]), str(len(ds)),
        ])
    return rows


def expected_same_week_row(n):
    f = periods.same_week_feasibility(n)
    return [
        str(n), str(periods.same_week_lookback_days(n)),
        iso(f["method"]["prediction_first"]), str(f["method"]["monday_count"]),
        iso(f["threshold"]["prediction_first"]), str(f["threshold"]["monday_count"]),
        iso(f["baseline"]["prediction_first"]), str(f["baseline"]["monday_count"]),
    ]


def periods_table_matches(text):
    header, body = read_table("periods", text)
    return header == PERIODS_HEADER and body == expected_periods_rows()


def same_week_table_matches(text):
    header, body = read_table("same_week", text)
    if len(header) != 8 or header[0] != "N 年":
        return False
    if [r[0] for r in body] != ["1", "2", "3", "4", "5"]:
        return False
    return all(r == expected_same_week_row(int(r[0])) for r in body)


class TestDocTables(unittest.TestCase):
    def test_periods_table(self):
        header, body = read_table("periods")
        self.assertEqual(header, PERIODS_HEADER)
        self.assertEqual(body, expected_periods_rows())

    def test_constants_table(self):
        header, body = read_table("constants")
        self.assertEqual(header[:2], ["定数", "値"])
        values = {r[0]: r[1] for r in body}
        self.assertEqual(
            values,
            {
                "DATA_START": iso(periods.DATA_START),
                "TODAY": iso(periods.TODAY),
                "DATA_SETTLE_DAYS": str(periods.DATA_SETTLE_DAYS),
                "BLOCK_WEIGHTS": ":".join(str(w) for w in periods.BLOCK_WEIGHTS),
                "MEDIAN_WINDOW_DAYS": str(periods.MEDIAN_WINDOW_DAYS),
                "SEASONAL_MARGIN_DAYS": str(periods.SEASONAL_MARGIN_DAYS),
                "LOOKBACK_DAYS": str(periods.LOOKBACK_DAYS),
                "EMBARGO_DAYS": str(periods.EMBARGO_DAYS),
                "PREDICTION_WEEKDAY": str(periods.PREDICTION_WEEKDAY),
            },
        )
        frozen = {r[0] for r in body if r[3] == "固定"}
        self.assertEqual(frozen, set(V1_FROZEN_CONSTANTS))

    def test_same_week_table(self):
        header, body = read_table("same_week")
        self.assertEqual(header[0], "N 年")
        self.assertEqual(len(header), 8)
        self.assertEqual([r[0] for r in body], ["1", "2", "3", "4", "5"])
        for r in body:
            self.assertEqual(r, expected_same_week_row(int(r[0])), "N=" + r[0])

    def test_tampered_tables_are_detected(self):
        # 照合の関数が、本物の文書では一致し、書き換えた文書では一致しないこと。
        text = read_doc()
        self.assertTrue(periods_table_matches(text))
        self.assertTrue(same_week_table_matches(text))
        lines = text.splitlines()
        i = lines.index("<!-- table:periods -->")
        # 行の入れ替え
        swapped = list(lines)
        swapped[i + 3], swapped[i + 4] = swapped[i + 4], swapped[i + 3]
        self.assertFalse(periods_table_matches("\n".join(swapped)))
        # 回数のセルを1つ書き換える
        edited = list(lines)
        edited[i + 3] = edited[i + 3].replace("| 232 |", "| 233 |")
        self.assertNotEqual(edited[i + 3], lines[i + 3])
        self.assertFalse(periods_table_matches("\n".join(edited)))
        # 3章(5) の表のセルを書き換える
        j = lines.index("<!-- table:same_week -->")
        edited = list(lines)
        edited[j + 4] = edited[j + 4].replace("| 180 |", "| 181 |")
        self.assertNotEqual(edited[j + 4], lines[j + 4])
        self.assertFalse(same_week_table_matches("\n".join(edited)))


# 本文（表の外）の日付と日数の照合。
DATE_RE = r"(\d{4}-\d{2}-\d{2})"
FACT_GDELT2_START = D(2015, 2, 19)
FACT_COUNTRY_CODE_ERROR = (D(2015, 2, 19), D(2015, 3, 1))
FACT_OWNER_DECISION = D(2026, 10, 6)  # S1・M4 を解消したオーナーの決定の日（reviews/T-004.md）


def _same_end_range():
    """E が TODAY のときと同じになる TODAY の範囲（両端）。"""
    e = periods.data_end()
    lo = periods.TODAY
    while periods.data_end(today=lo - DAY) == e:
        lo -= DAY
    hi = periods.TODAY
    while periods.data_end(today=hi + DAY) == e:
        hi += DAY
    return lo, hi


def body_checks():
    """(言い回しの正規表現, 取り出す値の期待値の tuple) の list。"""
    ps = periods.compute_periods()
    e = periods.data_end()
    lo, hi = _same_end_range()
    total = (e - periods.DATA_START).days + 1
    return [
        (r"手法を作る期間の区画（" + DATE_RE + r" 〜 " + DATE_RE + r"）",
         (iso(ps[0]["block_start"]), iso(ps[0]["block_end"]))),
        (r"TODAY − 5日（" + DATE_RE + r"）",
         (iso(periods.TODAY - datetime.timedelta(days=periods.DATA_SETTLE_DAYS)),)),
        (r"E = " + DATE_RE, (iso(e),)),
        (r"E の翌日（" + DATE_RE + r"）", (iso(e + DAY),)),
        (r"までの日数（(\d+)日）", (str(total),)),
        (r"GDELT 2\.0 の開始日 " + DATE_RE, (iso(FACT_GDELT2_START),)),
        (r"誤りがあった期間（" + DATE_RE + r" から " + DATE_RE + r" の昼まで）",
         tuple(iso(d) for d in FACT_COUNTRY_CODE_ERROR)),
        (r"DATA_START（" + DATE_RE + r"）", (iso(periods.DATA_START),)),
        (r"TODAY（" + DATE_RE + r"）", (iso(periods.TODAY),)),
        (r"TODAY が " + DATE_RE + r" から " + DATE_RE + r" までのどの日でも E は変わらない",
         (iso(lo), iso(hi))),
        (r"TODAY が " + DATE_RE + r" 以前なら E は " + DATE_RE + r"、" + DATE_RE
         + r" 以降なら E は " + DATE_RE,
         (iso(lo - DAY), iso(periods.data_end(today=lo - DAY)),
          iso(hi + DAY), iso(periods.data_end(today=hi + DAY)))),
        (r"閾値を決める期間の区画（" + DATE_RE + r" 以降）", (iso(ps[1]["block_start"]),)),
        (DATE_RE + r" 以降の行", (iso(ps[1]["block_start"]),)),
        (DATE_RE + r" のオーナーの決定", (iso(FACT_OWNER_DECISION),)),
        (r"過去分400日・エンバーゴ120日なら `([^`]+)`", (periods.effective_label(400, 120),)),
    ]


TABLE_MARKERS = ("periods", "constants", "same_week")


def doc_body(text):
    """三つの照合済みの表を除いた本文を返す（8章のきっかけの表などは本文に含める）。"""
    lines = text.splitlines()
    out = []
    i = 0
    while i < len(lines):
        if lines[i].strip() in {"<!-- table:%s -->" % m for m in TABLE_MARKERS}:
            i += 1
            while i < len(lines) and lines[i].startswith("|"):
                i += 1
            continue
        out.append(lines[i])
        i += 1
    return "\n".join(out)


# 本文の「数字＋日」と「数字＋年」の並び（出てくる順）。値は定数から作る。
WEEK_DAYS = 7               # 予言の間隔（1章）
READ_ONE_DAY = 1            # 「30日後の1日だけを読む」（3章 (2)）
SAME_WEEK_WARN_YEARS = 4    # 「4年以上では残りが少なく」（3章 (5)）
EXAMPLE_EMBARGO = 120       # 8章 (3) の仮の名前の例


def expected_day_counts():
    e = periods.EMBARGO_DAYS
    lb = periods.LOOKBACK_DAYS
    st = periods.DATA_SETTLE_DAYS
    med = periods.MEDIAN_WINDOW_DAYS
    h = PROPOSED_HORIZON_DAYS
    total = (periods.data_end() - periods.DATA_START).days + 1
    return [
        WEEK_DAYS, e,                       # 1章
        st, total, e, lb, lb,               # 2章 計算の手順
        st, st, lb, e, e,                   # 2章 理由
        h, h, READ_ONE_DAY, e, e,           # 3章 (2)
        h, e - h, e,
        med, med, e, lb, lb,                # 3章 (3)
        e,                                  # 3章 (4)
        periods.SEASONAL_MARGIN_DAYS,       # 3章 (5)「N × 366 + 35 日」
        e, e, e, e,                         # 4章
        med, h,                             # 5章
        med, e, lb,                         # 6章
        lb, EXAMPLE_EMBARGO,                # 8章 (3)
    ]


def expected_year_counts():
    return [SAME_WEEK_WARN_YEARS]


def check_body(text):
    """本文を照合し、問題の一覧を返す（空なら一致）。"""
    body = doc_body(text)
    problems = []
    covered = set()
    for pattern, want in body_checks():
        ms = list(re.finditer(pattern, body))
        if not ms:
            problems.append("言い回しが見つからない: " + pattern)
        for m in ms:
            if m.groups() != want:
                problems.append("値が違う: %s %r != %r" % (pattern, m.groups(), want))
            for g in range(1, len(m.groups()) + 1):
                covered.add(m.start(g))
    for m in re.finditer(r"\d{4}-\d{2}-\d{2}", body):
        if m.start() not in covered:
            problems.append("照合されない日付: " + m.group(0))
    days = [int(x) for x in re.findall(r"(\d+)\s*日", body)]
    if days != expected_day_counts():
        problems.append("日数の並びが違う: %r" % days)
    years = [int(x) for x in re.findall(r"(\d+)\s*年", body)]
    if years != expected_year_counts():
        problems.append("年数の並びが違う: %r" % years)
    for pat in (r"\d{4}\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*日", r"\d{4}/\d{1,2}/\d{1,2}",
                r"\d{1,2}\s*月\s*\d{1,2}\s*日"):
        for m in re.finditer(pat, body):
            problems.append("置いてはいけない形の日付: " + m.group(0))
    return problems


class TestDocBodyDates(unittest.TestCase):
    def test_body_dates_match_code(self):
        self.assertEqual(check_body(read_doc()), [])

    def assert_detected(self, text, old, new):
        bad = text.replace(old, new, 1)
        self.assertNotEqual(bad, text, old)
        self.assertNotEqual(check_body(bad), [], old)

    def test_tampered_body_is_detected(self):
        text = read_doc()
        self.assertEqual(check_body(text), [])
        # ISO 形式の日付
        self.assert_detected(text, "E = 2026-09-30", "E = 2026-08-31")
        self.assert_detected(text, "## 4. 判定期間", "最後の月曜は 2026-06-22。\n\n## 4. 判定期間")
        self.assert_detected(text, "2026-10-05 から 2026-11-04", "2026-10-06 から 2026-11-05")
        # 日数と年数
        self.assert_detected(text, "最初の400日を過去分", "最初の365日を過去分")
        self.assert_detected(text, "**J ≤ 90日** のとき", "**J ≤ 91日** のとき")
        self.assert_detected(text, "4年以上", "5年以上")
        self.assert_detected(text, "## 4. 判定期間", "余計な 10日。\n\n## 4. 判定期間")
        # 置いてはいけない形の日付
        self.assert_detected(text, "## 4. 判定期間", "2026年6月22日。\n\n## 4. 判定期間")
        self.assert_detected(text, "## 4. 判定期間", "2026/06/22。\n\n## 4. 判定期間")


# ---------------------------------------------------------------------------
# 作り直しの規則
# ---------------------------------------------------------------------------

class TestRebuildFrozen(unittest.TestCase):
    def test_frozen_constants_are_v1(self):
        for name, value in V1_FROZEN_CONSTANTS.items():
            self.assertEqual(getattr(periods, name), value, name)
        self.assertEqual(periods.FROZEN_BLOCKS, V1_BLOCKS)
        self.assertEqual(blocks_of(periods.compute_periods()), V1_BLOCKS)

    def test_rebuild_without_trigger_equals_v1(self):
        self.assertEqual(periods.rebuild_periods(), periods.compute_periods())
        # 下限以下のきっかけでは何も変わらない（エンバーゴも過去分も縮めない）。
        self.assertEqual(
            periods.rebuild_periods(
                last_read_offset_days=30, network_window_days=180, naive_history_days=400
            ),
            periods.compute_periods(),
        )

    def test_triggers_do_not_move_blocks(self):
        cases = []
        for j in (1, 30, 90, 91, 120, 180, 300):
            cases.append({"last_read_offset_days": j})
        for w in (30, 365, 400, 401, 600, 1000, 1500):
            cases.append({"network_window_days": w})
        for n in (1, 2, 3, 4, 5):
            cases.append({"same_week_years": n})
        for h in (400, 500, 800):
            cases.append({"naive_history_days": h})
        cases.append({"last_read_offset_days": 150, "same_week_years": 3, "network_window_days": 700})
        for kw in cases:
            ps = periods.rebuild_periods(**kw)
            self.assertEqual(blocks_of(ps), V1_BLOCKS, kw)

    def test_trigger_effects(self):
        ps = periods.rebuild_periods(last_read_offset_days=120)
        for p in ps:
            self.assertEqual(p["prediction_last"], p["block_end"] - datetime.timedelta(days=120))
        ps = periods.rebuild_periods(network_window_days=600)
        self.assertEqual(ps[0]["prediction_first"], D(2015, 3, 2) + datetime.timedelta(days=600))
        v1 = periods.compute_periods()
        self.assertEqual(ps[1]["prediction_first"], v1[1]["prediction_first"])
        self.assertEqual(ps[2]["prediction_first"], v1[2]["prediction_first"])

    def test_rebuild_does_not_accept_frozen_constants(self):
        for kw in ("today", "data_start", "settle_days", "weights", "lookback_days", "embargo_days"):
            with self.assertRaises(TypeError):
                periods.rebuild_periods(**{kw: 1})

    def test_moving_today_would_move_blocks_but_rebuild_cannot(self):
        # TODAY を動かすと境目が動くことの確認（だから固定する）。
        moved = periods.compute_periods(today=D(2026, 11, 10))
        self.assertEqual(moved[0]["block_end"], D(2020, 12, 30))
        self.assertNotEqual(blocks_of(moved), V1_BLOCKS)
        self.assertEqual(blocks_of(periods.rebuild_periods()), V1_BLOCKS)

    def test_rebuild_guard_against_changed_constants(self):
        original = periods.TODAY
        try:
            periods.TODAY = D(2026, 11, 10)
            with self.assertRaises(RuntimeError):
                periods.rebuild_periods()
        finally:
            periods.TODAY = original
        self.assertEqual(blocks_of(periods.rebuild_periods()), V1_BLOCKS)

    def test_required_values(self):
        self.assertEqual(periods.required_embargo(), 90)
        self.assertEqual(periods.required_embargo(30), 90)
        self.assertEqual(periods.required_embargo(91), 91)
        with self.assertRaises(ValueError):
            periods.required_embargo(0)
        self.assertEqual(periods.required_lookback(), 400)
        self.assertEqual(periods.required_lookback(network_window_days=300), 400)
        self.assertEqual(periods.required_lookback(same_week_years=3), 1133)
        self.assertEqual(
            periods.required_lookback(network_window_days=1200, same_week_years=3), 1200
        )


class TestRebuildOutput(unittest.TestCase):
    """作り直した区切りを、定数を書き換えずに出力できること。既定の出力も同じ経路を通ること。"""

    def run_cli(self, *args):
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
        return subprocess.run(
            [sys.executable, "-B", SCRIPT] + list(args), capture_output=True, env=env
        )

    def test_default_output_goes_through_rebuild(self):
        calls = []
        original = periods.rebuild_periods

        def spy(**kw):
            calls.append(kw)
            return original(**kw)

        periods.rebuild_periods = spy
        try:
            rec = periods.as_record()
        finally:
            periods.rebuild_periods = original
        self.assertEqual(len(calls), 1)
        self.assertEqual(rec["rebuild_triggers"], {k: None for k in periods.TRIGGER_NAMES})
        self.assertIsNone(rec["deadline_status"])
        self.assertEqual(rec["rules"]["proposed_label"], periods.PROPOSED_LABEL)
        got = tuple((p["name"], D.fromisoformat(p["block_start"]), D.fromisoformat(p["block_end"]))
                    for p in rec["periods"])
        self.assertEqual(got, V1_BLOCKS)

    def test_cli_rebuild_records_triggers(self):
        r = self.run_cli("--last-read-offset-days", "120", "--same-week-years", "3",
                         "--deadline-status", "before_deadline")
        self.assertEqual(r.returncode, 0, r.stderr)
        rec = json.loads(r.stdout.decode("utf-8"))
        self.assertEqual(
            rec["rebuild_triggers"],
            {"last_read_offset_days": 120, "network_window_days": None,
             "same_week_years": 3, "naive_history_days": None},
        )
        self.assertEqual(rec["deadline_status"], "before_deadline")
        self.assertEqual(rec["rules"]["embargo_days"], 120)
        self.assertEqual(rec["rules"]["lookback_days"], 1133)
        self.assertEqual(rec["max_last_read_offset_days"], 120)
        self.assertEqual(rec["rules"]["proposed_label"], "periods-v1-rebuilt-L1133-E120")
        got = tuple((p["name"], D.fromisoformat(p["block_start"]), D.fromisoformat(p["block_end"]))
                    for p in rec["periods"])
        self.assertEqual(got, V1_BLOCKS)
        self.assertEqual(rec["periods"][0]["prediction_first"], "2018-04-08")
        for p in rec["periods"]:
            self.assertEqual(
                D.fromisoformat(p["prediction_last"]),
                D.fromisoformat(p["block_end"]) - datetime.timedelta(days=120),
            )

    def test_cli_after_deadline_is_recorded(self):
        r = self.run_cli("--network-window-days", "500", "--deadline-status", "after_deadline")
        self.assertEqual(r.returncode, 0, r.stderr)
        rec = json.loads(r.stdout.decode("utf-8"))
        self.assertEqual(rec["deadline_status"], "after_deadline")
        self.assertEqual(rec["rebuild_triggers"]["network_window_days"], 500)

    def test_cli_requires_deadline_status_with_triggers(self):
        r = self.run_cli("--last-read-offset-days", "120")
        self.assertEqual(r.returncode, 2)
        self.assertEqual(r.stdout, b"")

    def test_cli_rejects_deadline_status_without_triggers(self):
        r = self.run_cli("--deadline-status", "before_deadline")
        self.assertEqual(r.returncode, 2)
        self.assertEqual(r.stdout, b"")

    def test_cli_rejects_frozen_constants(self):
        for opt in ("--today", "--data-start", "--weights", "--embargo-days", "--lookback-days"):
            r = self.run_cli(opt, "1")
            self.assertEqual(r.returncode, 2, opt)
            self.assertEqual(r.stdout, b"", opt)

    def test_cli_rejects_abbreviations(self):
        r = self.run_cli("--last-read", "120", "--deadline-status", "before_deadline")
        self.assertEqual(r.returncode, 2)
        self.assertEqual(r.stdout, b"")

    def test_cli_rejects_repeated_options(self):
        for args in (
            ("--last-read-offset-days", "120", "--last-read-offset-days", "30",
             "--deadline-status", "before_deadline"),
            ("--same-week-years", "2", "--deadline-status", "before_deadline",
             "--deadline-status", "after_deadline"),
        ):
            r = self.run_cli(*args)
            self.assertEqual(r.returncode, 2, args)
            self.assertEqual(r.stdout, b"", args)

    def test_label_does_not_distinguish_versions(self):
        # 文書 8章 (3) のとおり、仮の名前では版を区別しない。区別は JSON の別の欄で行う。
        a = periods.as_record(last_read_offset_days=120, deadline_status="before_deadline")
        b = periods.as_record(last_read_offset_days=120, deadline_status="after_deadline")
        c = periods.as_record(last_read_offset_days=120, naive_history_days=380,
                              deadline_status="before_deadline")
        self.assertEqual(a["rules"]["proposed_label"], b["rules"]["proposed_label"])
        self.assertEqual(a["rules"]["proposed_label"], c["rules"]["proposed_label"])
        self.assertNotEqual(a["deadline_status"], b["deadline_status"])
        self.assertNotEqual(a["rebuild_triggers"], c["rebuild_triggers"])

    def test_cli_default_equals_function(self):
        r = self.run_cli()
        self.assertEqual(r.returncode, 0)
        self.assertEqual(r.stdout.decode("utf-8"), periods.canonical_json())


class TestLabel(unittest.TestCase):
    def test_label_is_proposed_not_version(self):
        rec = periods.as_record()
        self.assertEqual(rec["rules"]["proposed_label"], periods.PROPOSED_LABEL)
        text = periods.canonical_json()
        self.assertNotIn('"rules_version"', text)
        self.assertNotIn('"version"', text)
        self.assertFalse(hasattr(periods, "RULES_VERSION"))


# ---------------------------------------------------------------------------
# 決定性と、全体の終わりの規則
# ---------------------------------------------------------------------------

class TestDeterminism(unittest.TestCase):
    def test_same_constants_same_dates(self):
        self.assertEqual(periods.compute_periods(), periods.compute_periods())
        self.assertEqual(periods.canonical_json(), periods.canonical_json())

    def test_explicit_args_equal_defaults(self):
        self.assertEqual(
            periods.compute_periods(),
            periods.compute_periods(
                data_start=D(2015, 3, 2),
                today=D(2026, 10, 6),
                settle_days=5,
                weights=(2, 1, 1),
                lookback_days=400,
                embargo_days=90,
            ),
        )

    def test_script_output_identical_across_runs(self):
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
        outs = [
            subprocess.run(
                [sys.executable, "-B", SCRIPT], capture_output=True, check=True, env=env
            ).stdout
            for _ in range(2)
        ]
        self.assertEqual(outs[0], outs[1])
        rec = json.loads(outs[0].decode("utf-8"))
        self.assertEqual(rec["rules"]["proposed_label"], periods.PROPOSED_LABEL)
        self.assertEqual(len(rec["periods"]), 3)
        self.assertEqual(rec["periods"][0]["first_prediction_date"], "2016-04-11")
        self.assertEqual(rec["periods"][0]["last_prediction_date"], "2020-09-14")

    def test_end_by_today_including_first_days_of_month(self):
        # E は「TODAY - 5日」が入る月だけで決まる。月の初めの5日（1日〜4日と5日）を含めて確かめる。
        d = D(2026, 9, 25)
        while d <= D(2026, 11, 15):
            if D(2026, 10, 5) <= d <= D(2026, 11, 4):
                want = D(2026, 9, 30)
            elif d < D(2026, 10, 5):
                want = D(2026, 8, 31)
            else:
                want = D(2026, 10, 31)
            self.assertEqual(periods.data_end(today=d), want, d)
            d += DAY
        # 月の初めの具体的な日。
        self.assertEqual(periods.data_end(today=D(2026, 10, 1)), D(2026, 8, 31))
        self.assertEqual(periods.data_end(today=D(2026, 10, 4)), D(2026, 8, 31))
        self.assertEqual(periods.data_end(today=D(2026, 10, 5)), D(2026, 9, 30))
        self.assertEqual(periods.data_end(today=D(2026, 11, 4)), D(2026, 9, 30))
        self.assertEqual(periods.data_end(today=D(2026, 11, 5)), D(2026, 10, 31))

    def test_split_days_sums(self):
        for total in range(4, 200):
            self.assertEqual(sum(periods.split_days(total, (2, 1, 1))), total)


class TestNoDataNoNetwork(unittest.TestCase):
    """periods.py が標準ライブラリの限られたモジュールだけを使い、現在時刻を読まないこと。"""

    ALLOWED_IMPORTS = {"argparse", "datetime", "json", "sys"}

    def setUp(self):
        with open(SCRIPT, encoding="utf-8") as f:
            self.src = f.read()
        self.tree = ast.parse(self.src)

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
