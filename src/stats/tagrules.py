#!/usr/bin/env python3
"""タグの一覧を作る規則（T-019。未決事項3の「入れる規則の数値の決め方」と未決事項5）。

データを見ずに決めた「決め方」を、機械可読な形で出す。文書は docs/stats/tags-naive.md。
- データは読まない。ネットワークは使わない。現在の日時を読まない。
  区分表（GDELT のテーマの区分表）も読まない。この版を作った時点で、統計係は区分表を見ていない。
- 一覧を作る関数 build_tag_list() は、手法を作る期間の区画のデータを「メモリの上の引数」として
  受け取る。ファイルは開かない。区画の外の日付が一つでも入っていれば止まる。
- この版は「提案」で、オーナーの承認のあと封印係が封印する。統計係は封印しない。
- 封印の時機（T-022 差し戻し1回目で変更）：入れる規則の定数と式（K、MIN_COUNT_PER_QUARTER、四半期の
  規則、A の式、存在の条件）は、除外の規則と同じ順番1で、区分表の取得と method-access より前に封印する。
  報道量の数え方（r(d) の分子と分母の単位）は未決のままでよい。この規則は、数え方がどれに決まっても
  同じ式で計算できる（K の単位は「r(d) の分子の単位で1日あたり」）。数え方が決まったあとの順番3では、
  この記録への参照と数え方とのつながりだけを足し、ここの定数と式は変えない（文書 5章）。

入れる規則（CLAUDE.md「タグの一覧」1）
  (1) 全体にわたって存在する：手法を作る期間の区画を暦の四半期に分け、欠けた日でない日の
      報道量の合計が、どの四半期でも MIN_COUNT_PER_QUARTER（1件）以上。
      欠けた日でない日が一日も無い四半期は数えない（その四半期は条件から外す）。
  (2) 平均報道量：欠けた日でない日の比率 r(d) の単純平均が A 以上。
      A = K_ARTICLES_PER_DAY / N_med。N_med は、欠けた日でない日の全体の報道量（r の分母）の
      中央値。A は「全体の報道量が普段どおりの日に、1日あたり平均 K 件」に当たる比率。
      最低の報道量 V は A と同じ値（docs/stats/candidates.md 3章 (4)）。
除外する規則（CLAUDE.md「タグの一覧」2）
  テーマの名前と説明を tokens() で語の並びにし、有効な区分の EXCLUSION_TERMS の語に当たる
  ものが一つでもあれば外す。当たり方は、完全一致・形の変化（inflections()）と、名前の欄だけに
  使うくっつき一致（先頭：PREFIX_MIN_LEN 文字以上の語、末尾：どの長さの語も。どちらも残りが
  GLUE_MIN_REST 文字以上）だけ（_word_matches()）。
  一件ずつの例外（特定のテーマ名を足す・外す）は持たない。

使い方
  python3 -B src/stats/tagrules.py
      規則の定数と語の一覧を JSON（キー順・UTF-8）で出力する
"""

import datetime
import fractions
import json
import math
import sys

PROPOSED_LABEL = "tagrules-v1"

# ---------------------------------------------------------------------------
# 入れる規則の数値の決め方
# ---------------------------------------------------------------------------

# A = K / N_med。K は「1日あたりの件数」。値は比率（分母が全体の報道量）で持つ。
K_ARTICLES_PER_DAY = 10

# 存在の確かめ方：暦の四半期ごとに、欠けた日でない日の報道量の合計がこれ以上。
MIN_COUNT_PER_QUARTER = 1

# ---------------------------------------------------------------------------
# 除外の規則は exclusion.py に分けた（T-022）。ここでは名前を引き継いで使う。
# ---------------------------------------------------------------------------

from exclusion import (  # noqa: E402,F401
    CLAUDE_CATEGORIES, CLAUDE_CATEGORY_OF, ENABLED_OPTIONAL_CATEGORIES, EXCLUSION_TERMS,
    GLUE_FIELDS, GLUE_MIN_REST, MATCH_FIELDS, OPTIONAL_CATEGORIES, OWNER_CHOICE_SOURCE,
    PREFIX_MIN_LEN, SUFFIX_BLOCK_ENDINGS, SUFFIX_BLOCK_MAX_LEN, _suffix_allowed, _term_match,
    _word_matches, enabled_categories, exclusion_matches, inflections, is_excluded,
    optional_choice_status, tokens,
)
import exclusion  # noqa: E402

ONE_DAY = datetime.timedelta(days=1)


# ---------------------------------------------------------------------------
# 入れる規則
# ---------------------------------------------------------------------------

def quarters(block_start, block_end):
    """区画を暦の四半期で区切った [(始まり, 終わり)]。最初と最後は区画で切る。"""
    out = []
    d = block_start
    while d <= block_end:
        q_month = 3 * ((d.month - 1) // 3) + 1
        if q_month + 3 > 12:
            nxt = datetime.date(d.year + 1, 1, 1)
        else:
            nxt = datetime.date(d.year, q_month + 3, 1)
        end = min(nxt - ONE_DAY, block_end)
        out.append((d, end))
        d = end + ONE_DAY
    return out


def _median(xs):
    xs = sorted(xs)
    n = len(xs)
    if n == 0:
        raise ValueError("中央値を取る値が無い")
    if n % 2 == 1:
        return fractions.Fraction(xs[n // 2])
    return fractions.Fraction(xs[n // 2 - 1] + xs[n // 2], 2)


def threshold_a(totals, missing_days):
    """A = K / N_med（分数）。N_med は欠けた日でない日の全体の報道量の中央値。"""
    usable = [v for d, v in totals.items() if d not in missing_days]
    n_med = _median(usable)
    if n_med <= 0:
        raise ValueError("全体の報道量の中央値が 0")
    return fractions.Fraction(K_ARTICLES_PER_DAY) / n_med, n_med


def _check_dates(dates, block_start, block_end, what):
    for d in dates:
        if not isinstance(d, datetime.date) or isinstance(d, datetime.datetime):
            raise ValueError("%s の日付の形が違う" % what)
        if d < block_start or d > block_end:
            raise ValueError("%s に区画の外の日付がある（%s）" % (what, d.isoformat()))


def _int_count(v):
    if isinstance(v, bool) or not isinstance(v, int) or v < 0:
        raise ValueError("件数は 0 以上の整数")
    return v


def build_tag_list(themes, counts, totals, missing_days, block_start, block_end, optional=None):
    """タグの一覧を作る（手法を作る期間の区画のデータだけで）。

    themes:  {テーマ名: 説明}。区分表の名前と説明（説明が無ければ None か ""）。
    counts:  {テーマ名: {日付: 件数}}。件数 0 の日は省いてよい。
    totals:  {日付: 全体の報道量}。区画のすべての日が要る（欠けた日は値があってもなくてもよい）。
    missing_days: 欠けた日の集合（封印した一覧）。
    どの引数にも区画の外の日付があれば止まる。区画の外のデータを渡す余地を無くすため。
    optional: 有効にする選べる区分（既定は ENABLED_OPTIONAL_CATEGORIES）。二つの設定で一覧を作って
              比べるときに渡す（文書 2章 (8)）。使った値は戻り値の enabled_optional_categories に入る。

    対象のテーマは、区分表のテーマと、データに現れたテーマの和集合（名前の順）。
    戻り値は、規則の値（A・N_med・四半期）とテーマごとの判定を含む dict。
    """
    if block_end < block_start:
        raise ValueError("区画が逆")
    opt = ENABLED_OPTIONAL_CATEGORIES if optional is None else tuple(optional)
    enabled_categories(opt)  # 選べる区分でない値なら止まる
    _check_dates(totals.keys(), block_start, block_end, "totals")
    _check_dates(missing_days, block_start, block_end, "missing_days")
    for name, per_day in counts.items():
        _check_dates(per_day.keys(), block_start, block_end, "counts[%s]" % name)
    usable_days = []
    d = block_start
    while d <= block_end:
        if d not in missing_days:
            if d not in totals:
                raise ValueError("欠けた日でない日の全体の報道量が無い（%s）" % d.isoformat())
            if _int_count(totals[d]) <= 0:
                raise ValueError("欠けた日でない日の全体の報道量が 0（%s）。欠けた日の規則と食い違う" % d.isoformat())
            usable_days.append(d)
        d += ONE_DAY
    if not usable_days:
        raise ValueError("欠けた日でない日が無い")
    a, n_med = threshold_a({d: totals[d] for d in usable_days}, set())
    qs = quarters(block_start, block_end)
    q_of_day = {}
    for i, (qa, qb) in enumerate(qs):
        x = qa
        while x <= qb:
            q_of_day[x] = i
            x += ONE_DAY
    q_has_data = [False] * len(qs)
    for x in usable_days:
        q_has_data[q_of_day[x]] = True
    names = sorted(set(themes) | set(counts))
    rows = []
    for name in names:
        per_day = counts.get(name, {})
        for v in per_day.values():
            _int_count(v)
        q_counts = [0 if has else None for has in q_has_data]
        for x, v in per_day.items():
            if x not in missing_days:
                q_counts[q_of_day[x]] += v
        present = all(c is None or c >= MIN_COUNT_PER_QUARTER for c in q_counts)
        mean = math.fsum(per_day.get(x, 0) / totals[x] for x in usable_days) / len(usable_days)
        volume_ok = fractions.Fraction(mean) >= a
        desc = themes.get(name)
        matches = exclusion_matches(name, desc, opt)
        rows.append({
            "name": name,
            "in_category_table": name in themes,
            "quarter_counts": q_counts,
            "present_throughout": present,
            "mean_ratio": mean,
            "mean_ratio_at_least_a": volume_ok,
            "exclusion_matches": [list(m) for m in matches],
            "in_list": bool(present and volume_ok and not matches),
        })
    return {
        "proposed_label": PROPOSED_LABEL,
        "block_start": block_start.isoformat(),
        "block_end": block_end.isoformat(),
        "usable_day_count": len(usable_days),
        "quarters": [[qa.isoformat(), qb.isoformat()] for qa, qb in qs],
        "quarters_without_usable_days": [i for i, h in enumerate(q_has_data) if not h],
        "n_med": "%d/%d" % (n_med.numerator, n_med.denominator),
        "a": "%d/%d" % (a.numerator, a.denominator),
        "a_float": float(a),
        "v_equals_a": True,
        "enabled_optional_categories": [c for c in OPTIONAL_CATEGORIES if c in opt],
        "themes": rows,
        "tag_list": [r["name"] for r in rows if r["in_list"]],
    }


def _input_signature(result):
    """入力だけで決まり、版（除外の規則）と設定に依らない値の組。

    区画・欠けた日でない日の数・四半期・使える日の無い四半期・a・n_med と、テーマごとの
    （名前、区分表にあるか、四半期ごとの件数、平均の比率）。1cb463a の版の結果も同じ欄を持つ。
    """
    themes = tuple(sorted(
        (r["name"], r["in_category_table"], tuple(r["quarter_counts"]), r["mean_ratio"])
        for r in result["themes"]))
    return (result["block_start"], result["block_end"], result["usable_day_count"],
            tuple(tuple(q) for q in result["quarters"]),
            tuple(result["quarters_without_usable_days"]),
            result["a"], result["n_med"], themes)


def compare_lists(old_result, new_result):
    """二つの build_tag_list() の結果を比べ、出入りしたテーマを返す（名前の順）。

    二つが同じ入力から作られたことを、_input_signature() の値（区画、欠けた日でない日の数
    usable_day_count、四半期、a、n_med、テーマごとの四半期の件数 quarter_counts と平均など）で
    確かめ、一つでも違えば止まる。戻り値には、両方の enabled_optional_categories を入れる
    （1cb463a の版の結果のように、その値を持たない結果は None）。
    """
    if _input_signature(old_result) != _input_signature(new_result):
        raise ValueError("二つの結果の入力が違う（区画・欠けた日でない日の数・四半期・a・n_med・"
                         "テーマの集合・テーマごとの件数と平均のどれか）")
    old, new = set(old_result["tag_list"]), set(new_result["tag_list"])
    return {"only_in_old": sorted(old - new), "only_in_new": sorted(new - old),
            "in_both": len(old & new),
            "enabled_optional_categories": {
                "old": old_result.get("enabled_optional_categories"),
                "new": new_result.get("enabled_optional_categories")}}


def as_record():
    return {
        "proposed_label": PROPOSED_LABEL,
        "inclusion": {
            "presence": "every calendar quarter of the method block (clipped at block ends) with at "
                        "least one usable day has total count >= %d on usable days; quarters "
                        "without usable days are skipped" % MIN_COUNT_PER_QUARTER,
            "min_count_per_quarter": MIN_COUNT_PER_QUARTER,
            "mean": "simple mean of daily ratio r(d) over usable (non-missing) days of the method block",
            "a_rule": "A = K / N_med, N_med = median daily total count over usable days of the method block "
                      "(even count -> mean of two middle values); compare mean >= A exactly",
            "k_articles_per_day": K_ARTICLES_PER_DAY,
            "v_rule": "V = A (docs/stats/candidates.md 3 (4))",
            "universe": "union of themes in the category table and themes appearing in method-block data",
            "data_scope": "method block only; any date outside the block in the inputs stops the build",
        },
        "exclusion": exclusion.as_record(),
        "counting": "numerator and denominator of r(d) follow the counting method decided after the trial "
                    "run and sealed later (order 3) with a reference to this record; K is read in the "
                    "numerator unit of r(d) per day at the median total; counts must be non-negative "
                    "integers; deciding the counting method does not change K, the presence rule or the "
                    "A formula",
        "seal_order": "order 1, together with the exclusion rule, before the category table acquisition "
                      "and before method-access (docs/stats/tags-naive.md 5)",
        "changes_after_seeing_table": "only fixes of defects reproducible by a test (exception, crash on "
                                      "empty input, etc.); no words, no numbers, no new kinds of match. "
                                      "New version, owner approval, before method-access; lists computed "
                                      "with both versions and themes that moved published. Theme names "
                                      "are never named",
        "sealed_versions": "the final version and the version of commit 1cb463a are both sealed; after the "
                           "category table is acquired both lists are computed and the themes that differ "
                           "are published (compare_lists)",
    }


def canonical_json():
    return json.dumps(as_record(), ensure_ascii=False, sort_keys=True, indent=2) + "\n"


def main(argv=None):
    if argv is None:
        argv = sys.argv[1:]
    if argv:
        sys.stderr.write("tagrules: 引数は取らない\n")
        return 2
    sys.stdout.write(canonical_json())
    return 0


if __name__ == "__main__":
    sys.exit(main())
