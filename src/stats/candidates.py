#!/usr/bin/env python3
"""閾値と判定期間の候補、判定の定義、選ぶ規則（T-011）。

データを見ずに決めた候補の値を、機械可読な形で出す。文書は docs/stats/candidates.md。
- データは読まない。ネットワークは使わない。現在の日時を読まない。標準ライブラリと
  同じフォルダの periods.py だけを使う。
- この版は「提案」で、オーナーの承認のあと封印係が封印する。統計係は封印しない。

用語（docs/stats/periods.md と同じ）
  t     予言日。予言の入力は日付 t-1 以前のデータだけ。
  r(d)  タグの日次の比率（そのタグの報道量 / 同じ日の全体の報道量）。
        全体の報道量が 0 か取得できなかった日は「欠けた日」で、値を持たない。
        全体があってタグが 0 の日は r(d) = 0（欠けた日ではない）。
  B(t)  普段の水準。予言日 t の時点で計算した値（直近365日の中央値。CLAUDE.md）。
        判定でも、予言日 t の時点の B(t) を使い、判定期間のデータで計算し直さない。
  H     判定期間の日数（候補）。判定期間は日付 t+1 から t+H まで（両端を含む）。
  m     閾値の倍率（候補）。
  J     判定が読む最後の日のずれ。判定は t+H までしか読まないので J = H。

判定（固定。候補にしない）
  判定期間の中に完全に収まる、連続した7日の平均（7日の終わりの日 d は t+7 から t+H）
  のうち、一つでも m × B(t) を超えたら（厳密に大きい）島とする。
  - 7日のまとまりに欠けた日が1日でもあれば、そのまとまりは使わない。
  - 使えるまとまりが一つも無ければ「判定不能」（None）。
  - B(t) が 0 のタグは予言の対象にしない（倍率が意味を持たないため）。judge() は止まる。

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
SMOOTHING_DAYS = 7

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


def judge(ratio_of_day, t, horizon_days, multiplier, baseline):
    """判定の参照実装。True（島）・False（島でない）・None（判定不能）を返す。

    ratio_of_day(d) は日付 d の比率を返す関数。欠けた日は None を返す。
    この関数が呼ぶのは、判定期間（t+1 から t+H）の日だけである。
    baseline は予言日 t の時点の B(t)。
    """
    if horizon_days not in HORIZON_DAYS:
        raise ValueError("判定期間が候補に無い")
    if multiplier not in THRESHOLD_MULTIPLIERS:
        raise ValueError("倍率が候補に無い")
    if not baseline > 0:
        raise ValueError("B(t) が 0 以下のタグは予言の対象にしない")
    first, last = judgment_window(t, horizon_days)
    values = {}
    d = first
    while d <= last:
        values[d] = ratio_of_day(d)
        d += ONE_DAY
    limit = multiplier * baseline
    usable = 0
    for end in smoothing_window_ends(t, horizon_days):
        days = [end - datetime.timedelta(days=k) for k in range(SMOOTHING_DAYS)]
        xs = [values[x] for x in days]
        if any(x is None for x in xs):
            continue
        usable += 1
        if sum(xs) / SMOOTHING_DAYS > limit:
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
            "comparison": "mean > m * B(t) (strict)",
            "baseline_from": "B(t) at prediction time; not recomputed",
            "missing_day": "a 7-day block with any missing day is not used",
            "no_usable_block": "undeterminable (null)",
            "zero_baseline": "tag with B(t) = 0 is not a prediction target",
        },
        "tiers": [
            {"name": n, "center": _frac(c), "low": _frac(lo), "high": _frac(hi)}
            for n, c, lo, hi in TIERS
        ],
        "selection_rule": [
            "horizons in ascending order",
            "low tier: multiplier with rate in [low, high], closest to center on log scale; tie -> larger multiplier",
            "high tier: multiplier smaller than the low-tier one, rate in range, closest to center; tie -> larger multiplier",
            "first horizon where both tiers are found",
            "none found -> stop and report to owner",
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
