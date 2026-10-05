#!/usr/bin/env python3
"""閾値と判定期間の候補、判定の定義、選ぶ規則（T-011）。

データを見ずに決めた候補の値を、機械可読な形で出す。文書は docs/stats/candidates.md。
- データは読まない。ネットワークは使わない。現在の日時を読まない。標準ライブラリと
  同じフォルダの periods.py だけを使う。
- この版は「提案」で、オーナーの承認のあと封印係が封印する。統計係は封印しない。

用語（docs/stats/periods.md と同じ）
  t     予言日。予言の入力は日付 t-1 以前のデータだけ。
  r(d)  タグの日次の比率（そのタグの報道量 / 同じ日の全体の報道量。どちらもその日に
        取得できた15分ファイルだけから数える）。欠けた日（day_is_missing）は値を持たない。
        欠けた日でなく、タグが 0 の日は r(d) = 0。
  B(t)  普段の水準。7日の平均（終わりの日が t-365 から t-1）の中央値（CLAUDE.md、
        2026-10-06 オーナー決定）。判定でも予言日 t の時点の B(t) を使う。
  H     判定期間の日数（候補）。判定期間は日付 t+1 から t+H まで（両端を含む）。
  m     閾値の倍率（候補）。
  V     最低の報道量。手法を作る期間のデータで決め、threshold-access より前に封印する。
  J     判定が読む最後の日のずれ。判定は t+H までしか読まないので J = H。

判定（固定。候補にしない）
  判定期間の中に完全に収まる連続7日の平均（7日の終わりの日 d は t+7 から t+H）の
  うち、一つでも「m × B(t) より大きく、かつ V より大きい」ものがあれば島とする。
  - 7日のまとまりに欠けた日が1日でもあれば、そのまとまりは使わない。
  - 使えるまとまりが一つも無ければ「判定不能」（None）。
  - B(t) = 0 のタグも予言の対象に入る。V の条件で、B がごく小さいときに倍率が
    意味を失う問題を防ぐ。

使い方
  python3 -B src/stats/candidates.py
      候補・判定の定義・選ぶ規則の定数を JSON（キー順・UTF-8）で出力する
"""

import datetime
import fractions
import json
import sys

import periods

PROPOSED_LABEL = "candidates-v1"

# ---------------------------------------------------------------------------
# 候補（データを見ずに決めたもの。理由は docs/stats/candidates.md）
# ---------------------------------------------------------------------------

# 閾値の倍率の候補。2 から 16 まで、隣どうしの比が 1.5 以下になる 2^a 3^b の数。
THRESHOLD_MULTIPLIERS = (2, 3, 4, 6, 8, 12, 16)

# 判定期間の日数の候補。7 の倍数で、隣どうしの比が 2。
HORIZON_DAYS = (14, 28, 56)

# 判定の数字の平滑化（固定）。判定期間の中に完全に収まる、連続した7日の平均。
# 普段の水準と予言の時点の報道量も、同じ7日の平均で測る。
SMOOTHING_DAYS = 7

# 普段の水準：7日の平均を直近何日分とるか（CLAUDE.md）。読む過去分は 365 + 6 = 371 日。
BASELINE_WINDOW_DAYS = 365
# B(t) を計算するのに要る、使える7日のまとまりの最低数。365個の半分以上（183個）。
# これより少なければ B(t) は None（その週の対象にならない）。
MIN_BASELINE_BLOCKS = (BASELINE_WINDOW_DAYS + 1) // 2

# 予言の時点の報道量：終わりの日が t-1 から t-CURRENT_SEARCH_DAYS の7日のまとまりのうち、
# 欠けた日を含まない最も新しいもの。読む日は t-13 から t-1。
CURRENT_SEARCH_DAYS = 7

# 欠けた日の規則（固定）。GDELT 2.0 の15分ファイルは1日に96本。
SLOTS_PER_DAY = 96
# 72本（4分の3）以上あれば、その日は欠けた日としない。
MIN_PRESENT_SLOTS = 72

# 最低の報道量 V の決め方（値は決めない。決め方の規則だけを固定する）。
MIN_LEVEL_RULE = (
    "V = the tag inclusion threshold A (mean daily ratio over the method block), "
    "determined only from method-block data and sealed together with the tag list, "
    "before the models (owner decision 2026-10-06, CLAUDE.md)"
)

# ---------------------------------------------------------------------------
# 選ぶ規則の定数（二段の基準値。CLAUDE.md「基準値：二段」）
# 割合は分数で持ち、比べるときに丸めが入らないようにする。
# ---------------------------------------------------------------------------
F = fractions.Fraction
TIERS = (
    # name, 目標の中心, 許す範囲の下限, 上限（両端を含む）
    ("low", F(1, 50), F(1, 100), F(1, 25)),   # およそ2%（2% の半分から2倍まで）
    ("high", F(1, 8), F(1, 10), F(3, 20)),    # 10〜15%（中心は 12.5%）
)

ONE_DAY = datetime.timedelta(days=1)


def combinations():
    """候補の組み合わせ（倍率, 日数）をすべて返す。モデルはこの組み合わせごとに作る。"""
    return tuple((m, h) for h in HORIZON_DAYS for m in THRESHOLD_MULTIPLIERS)


def last_read_offset_days(horizon_days):
    """判定期間 H のときの J。判定は t+H までしか読まず、平滑化は期間の中で閉じる。"""
    if horizon_days < SMOOTHING_DAYS:
        raise ValueError("判定期間は平滑化の幅以上")
    return horizon_days


def max_last_read_offset_days():
    """候補の中で最大の J（案B では、エンバーゴはこれで決まる）。"""
    return max(last_read_offset_days(h) for h in HORIZON_DAYS)


def judgment_window(t, horizon_days):
    """判定期間の始まりと終わり（両端を含む）。"""
    return t + ONE_DAY, t + datetime.timedelta(days=horizon_days)


def smoothing_window_ends(t, horizon_days):
    """7日のまとまりの終わりの日の一覧。どのまとまりも判定期間の中に収まる。"""
    first, last = judgment_window(t, horizon_days)
    d = first + datetime.timedelta(days=SMOOTHING_DAYS - 1)
    out = []
    while d <= last:
        out.append(d)
        d += ONE_DAY
    return out


def _block_mean(values_of_day, end):
    """end で終わる連続7日の平均。欠けた日が1日でもあれば None。"""
    xs = [values_of_day(end - datetime.timedelta(days=k)) for k in range(SMOOTHING_DAYS)]
    if any(x is None for x in xs):
        return None
    return sum(xs) / SMOOTHING_DAYS


def _cached(ratio_of_day, first, last):
    """first から last までの日だけを読み、ほかの日を求められたら止める関数を返す。"""
    values = {}
    d = first
    while d <= last:
        values[d] = ratio_of_day(d)
        d += ONE_DAY

    def get(day):
        if day not in values:
            raise RuntimeError("読んではいけない日を読もうとした")
        return values[day]

    return get


def baseline_level(ratio_of_day, t):
    """普段の水準 B(t)。7日の平均（終わりの日が t-365 から t-1）の中央値。

    欠けた日を含む7日のまとまりは使わない。使えるまとまりが MIN_BASELINE_BLOCKS
    （183）個より少なければ None。
    読むのは t-371 から t-1 までの日だけ（予言日 t 以降の日は読まない）。
    個数が偶数のときは、真ん中の二つの平均。
    """
    first = t - datetime.timedelta(days=BASELINE_WINDOW_DAYS + SMOOTHING_DAYS - 1)
    get = _cached(ratio_of_day, first, t - ONE_DAY)
    means = []
    for k in range(1, BASELINE_WINDOW_DAYS + 1):
        m = _block_mean(get, t - datetime.timedelta(days=k))
        if m is not None:
            means.append(m)
    if len(means) < MIN_BASELINE_BLOCKS:
        return None
    means.sort()
    n = len(means)
    if n % 2 == 1:
        return means[n // 2]
    return (means[n // 2 - 1] + means[n // 2]) / 2


def current_level(ratio_of_day, t):
    """予言の時点の報道量。

    終わりの日が t-1, t-2, ..., t-7 の順に7日のまとまりを見て、欠けた日を含まない
    最初のまとまりの平均を返す。どれも使えなければ None。読む日は t-13 から t-1。
    """
    first = t - datetime.timedelta(days=CURRENT_SEARCH_DAYS + SMOOTHING_DAYS - 1)
    get = _cached(ratio_of_day, first, t - ONE_DAY)
    for k in range(1, CURRENT_SEARCH_DAYS + 1):
        m = _block_mean(get, t - datetime.timedelta(days=k))
        if m is not None:
            return m
    return None


def is_target(ratio_of_day, t):
    """予言の対象かどうか（一度跳ねたタグの扱いを除く。それは採点計画で決める）。

    B(t) と予言の時点の報道量がどちらも決まり、報道量 <= B(t) のとき True。
    どちらかが None なら False（その週は対象にならない）。B(t) = 0 でも対象になりうる。
    読む日は t-371 から t-1 だけ。
    """
    b = baseline_level(ratio_of_day, t)
    c = current_level(ratio_of_day, t)
    if b is None or c is None:
        return False
    return c <= b


def day_is_missing(present_slots, total_volume):
    """欠けた日の規則。

    present_slots: その日（収集係の規則で決まる UTC の日）の15分ファイルのうち、
        ファイル一覧に載り、かつ取得の記録で取得とハッシュの照合に成功したものの数。
    total_volume: その present_slots から数えた全体の報道量。
    present_slots が MIN_PRESENT_SLOTS 未満、または total_volume が 0 なら欠けた日。
    """
    if not (isinstance(present_slots, int) and 0 <= present_slots <= SLOTS_PER_DAY):
        raise ValueError("ファイルの数が不正")
    if total_volume < 0:
        raise ValueError("全体の報道量が負")
    return present_slots < MIN_PRESENT_SLOTS or total_volume == 0


def judge(ratio_of_day, t, horizon_days, multiplier, baseline, min_level):
    """判定の参照実装。True（島）・False（島でない）・None（判定不能）を返す。

    ratio_of_day(d) は日付 d の比率を返す関数。欠けた日は None を返す。
    この関数が読むのは、判定期間（t+1 から t+H）の日だけである。
    baseline は予言日 t の時点の B(t)（0 でもよい）。
    min_level は最低の報道量（手法を作る期間のデータで決めて封印する値。0 より大きい）。
    島：7日の平均 > multiplier × baseline、かつ 7日の平均 > min_level（どちらも厳密）。
    """
    if horizon_days not in HORIZON_DAYS:
        raise ValueError("判定期間が候補に無い")
    if multiplier not in THRESHOLD_MULTIPLIERS:
        raise ValueError("倍率が候補に無い")
    if baseline is None or baseline < 0:
        raise ValueError("B(t) が無い、または負")
    if min_level is None or not min_level > 0:
        raise ValueError("最低の報道量は 0 より大きい値が要る")
    first, last = judgment_window(t, horizon_days)
    get = _cached(ratio_of_day, first, last)
    limit = max(multiplier * baseline, min_level)
    usable = 0
    for end in smoothing_window_ends(t, horizon_days):
        mean = _block_mean(get, end)
        if mean is None:
            continue
        usable += 1
        if mean > limit:
            return True
    if usable == 0:
        return None
    return False


def _distance(rate, center):
    """対数の尺度での中心からの離れ（rate/center と center/rate の大きい方）。"""
    return max(rate / center, center / rate)


def _best(rates, ms, center):
    """ms のうち中心に最も近い倍率。同じ近さなら大きい倍率。"""
    return min(ms, key=lambda m: (_distance(rates[m], center), -m))


def select(rate_table):
    """選ぶ規則。閾値を決める期間の、組み合わせごとの島の数と対象の数だけを受け取る。

    rate_table: {(倍率, 日数): (島になった件数, 対象の件数)}。すべての組み合わせが
    ちょうど一つずつ必要。モデルの成績は受け取らない（受け取る引数が無い）。

    整合性の検査（どれかに反したら止まる。表を作る計算に誤りがあるとみなす）
      - 同じ判定期間では、対象の件数がどの倍率でも同じ。
        （対象は予言の時点の報道量と B(t) だけで決まり、倍率に依らない。判定不能も
        欠けた日と判定期間だけで決まり、倍率に依らない。）
      - 同じ判定期間では、倍率が大きいほど島の件数が増えない（割合が上がらない）。
        （倍率が大きい島は、小さい倍率でも島になる。）

    規則
      1. 判定期間を短い順に見る。
      2. その期間で、割合が「low」の範囲に入る倍率と、「high」の範囲に入る倍率を集める。
      3. low の段は、範囲に入る倍率のうち中心（2%）に最も近いもの。同じ近さなら大きい倍率。
      4. high の段は、範囲に入り、low の段の倍率より小さい倍率のうち、中心（12.5%）に
         最も近いもの。同じ近さなら大きい倍率。
      5. 両方が決まった最初の期間を選ぶ。
      6. どの期間でも決まらなければ None（作業を止めてオーナーに報告する）。
    戻り値: {"horizon_days": H, "low": m1, "high": m2} か None。
    """
    expected = set(combinations())
    keys = set(rate_table)
    if keys != expected:
        raise ValueError("組み合わせが候補と一致しない（足りない、または余計にある）")
    rates = {}
    for key in combinations():
        hits, n = rate_table[key]
        if not (isinstance(hits, int) and isinstance(n, int)) or isinstance(hits, bool) or isinstance(n, bool):
            raise ValueError("件数は整数")
        if n < 0 or hits < 0 or hits > n:
            raise ValueError("件数が不正")
        rates[key] = F(hits, n) if n > 0 else None
    for h in HORIZON_DAYS:
        ns = {rate_table[(m, h)][1] for m in THRESHOLD_MULTIPLIERS}
        if len(ns) != 1:
            raise ValueError("同じ判定期間で、対象の件数が倍率によって違う: H=%d" % h)
        hs = [rate_table[(m, h)][0] for m in THRESHOLD_MULTIPLIERS]
        if any(b > a for a, b in zip(hs, hs[1:])):
            raise ValueError("同じ判定期間で、倍率が大きいのに島の件数が増えている: H=%d" % h)
    (_, c_low, lo_low, hi_low), (_, c_high, lo_high, hi_high) = TIERS
    for h in sorted(HORIZON_DAYS):
        r = {m: rates[(m, h)] for m in THRESHOLD_MULTIPLIERS}
        low_ok = [m for m in THRESHOLD_MULTIPLIERS if r[m] is not None and lo_low <= r[m] <= hi_low]
        if not low_ok:
            continue
        m_low = _best(r, low_ok, c_low)
        high_ok = [
            m for m in THRESHOLD_MULTIPLIERS
            if m < m_low and r[m] is not None and lo_high <= r[m] <= hi_high
        ]
        if not high_ok:
            continue
        m_high = _best(r, high_ok, c_high)
        return {"horizon_days": h, "low": m_low, "high": m_high}
    return None


def check_against_periods():
    """候補が periods.py の区切りと矛盾しないことを確かめ、使った値を返す。"""
    j_max = max_last_read_offset_days()
    need = BASELINE_WINDOW_DAYS + SMOOTHING_DAYS - 1
    if need > periods.LOOKBACK_DAYS:
        raise RuntimeError("普段の水準に要る過去分が periods の過去分を超える")
    for h in HORIZON_DAYS:
        if not periods.horizon_is_valid(last_read_offset_days(h)):
            raise RuntimeError("J がエンバーゴを超える候補がある")
    ps = periods.rebuild_periods(last_read_offset_days=j_max)
    got = tuple((p["name"], p["block_start"], p["block_end"]) for p in ps)
    if got != periods.FROZEN_BLOCKS:
        raise RuntimeError("区画の境目が固定の値と一致しない")
    if periods.required_embargo(j_max) != periods.EMBARGO_DAYS:
        raise RuntimeError("エンバーゴの作り直しが要る")
    return {
        "max_last_read_offset_days": j_max,
        "embargo_days": periods.required_embargo(j_max),
        "periods_rebuild_needed": False,
        "baseline_lookback_days": need,
        "periods_lookback_days": periods.LOOKBACK_DAYS,
    }


def _frac(x):
    return "%d/%d" % (x.numerator, x.denominator)


def as_record():
    return {
        "proposed_label": PROPOSED_LABEL,
        "threshold_multipliers": list(THRESHOLD_MULTIPLIERS),
        "horizon_days": list(HORIZON_DAYS),
        "combinations": [list(c) for c in combinations()],
        "combination_count": len(combinations()),
        "last_read_offset_days": {str(h): last_read_offset_days(h) for h in HORIZON_DAYS},
        "judgment": {
            "window": "t+1 .. t+H (inclusive)",
            "statistic": "max over 7-day means fully inside the window",
            "smoothing_days": SMOOTHING_DAYS,
            "comparison": "mean > m * B(t) and mean > V (both strict)",
            "baseline": "B(t) = median of 7-day means ending t-365 .. t-1 (complete blocks only); not recomputed",
            "baseline_window_days": BASELINE_WINDOW_DAYS,
            "current_level": "latest complete 7-day mean ending t-1 .. t-7 (reads t-13 .. t-1); none -> null",
            "min_baseline_blocks": MIN_BASELINE_BLOCKS,
            "target": "B(t) and current level both defined and current level <= B(t); otherwise not a target that week",
            "missing_day": "fewer than %d of %d 15-minute files acquired, or total volume 0" % (MIN_PRESENT_SLOTS, SLOTS_PER_DAY),
            "missing_block": "a 7-day block with any missing day is not used",
            "no_usable_block": "undeterminable (null)",
            "zero_baseline": "tag with B(t) = 0 stays a prediction target",
            "min_level_rule": MIN_LEVEL_RULE,
        },
        "slots_per_day": SLOTS_PER_DAY,
        "min_present_slots": MIN_PRESENT_SLOTS,
        "tiers": [
            {"name": n, "center": _frac(c), "low": _frac(lo), "high": _frac(hi)}
            for n, c, lo, hi in TIERS
        ],
        "selection_rule": [
            "horizons in ascending order",
            "low tier: multiplier with rate in [low, high], closest to center on log scale; tie -> larger multiplier",
            "high tier: multiplier smaller than the low-tier one, rate in range, closest to center; tie -> larger multiplier",
            "first horizon where both tiers are found",
            "none found -> stop and report to owner; owner sees only the rate table",
        ],
        "rate_table_checks": [
            "same target count for every multiplier within a horizon",
            "hit count non-increasing in multiplier within a horizon",
        ],
        "sealed_before_models": [
            "tag list and V",
            "missing-day list of the method block",
        ],
        "sealed_before_threshold_access": [
            "these candidates and J = 56",
            "tag list, V, missing-day list of the method block",
            "the 42 models",
            "target rule (this file: is_target, current_level, baseline_level)",
            "rule for tags that already jumped (scoring plan); without it, do not proceed",
            "naive-model lookback (counted including 7-day blocks) as a periods trigger",
        ],
        "threshold_period_order": [
            "seal missing-day list for the threshold block (before any label)",
            "compute labels and the rate table for all 21 combinations",
            "seal the rate table and the select() result",
            "model / stick-chart / naive outputs are not computed on the threshold period",
        ],
        "periods_check": check_against_periods(),
    }


def canonical_json():
    return json.dumps(as_record(), ensure_ascii=False, sort_keys=True, indent=2) + "\n"


def main(argv=None):
    if argv is None:
        argv = sys.argv[1:]
    if argv:
        sys.stderr.write("candidates: 引数は取らない\n")
        return 2
    sys.stdout.write(canonical_json())
    return 0


if __name__ == "__main__":
    sys.exit(main())
