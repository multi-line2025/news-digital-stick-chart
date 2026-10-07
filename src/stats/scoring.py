#!/usr/bin/env python3
"""採点計画のうち、一度跳ねたタグの扱いと「対象なし」の週の数え方（T-019）。

文書は docs/stats/tags-naive.md 4章。
- データは読まない。ネットワークは使わない。現在の日時を読まない。
- 予言日 t の判断に使うのは、日付 t-1 以前のデータだけ（読む日は t-371 から t-1）。

一度跳ねたタグ（冷却）
  予言日 t の時点で、終わりの日が t-COOLDOWN_DAYS から t-1 の、欠けた日を含まない
  7日の平均のどれかが max(JUMP_MULTIPLIER × B(t), V) より大きいタグは、その週の対象にしない。
  JUMP_MULTIPLIER は倍率の候補の最小（2）、COOLDOWN_DAYS は判定期間の候補の最大（56日）。
  どちらも倍率と判定期間の組み合わせに依らないので、対象は21組で同じになる
  （candidates.select() の表の検査「同じ判定期間では対象の件数が同じ」を保つ）。

対象の状態（target_status）
  "no_baseline"     B(t) が決まらない
  "no_current"      予言の時点の報道量が決まらない
  "above_baseline"  予言の時点の報道量 > B(t)
  "cooldown"        上の冷却に当たる
  "target"          予言の対象

使い方
  python3 -B src/stats/scoring.py     規則の定数を JSON で出力する
"""

import datetime
import json
import sys

import candidates

PROPOSED_LABEL = "scoring-partial-v1"

JUMP_MULTIPLIER = min(candidates.THRESHOLD_MULTIPLIERS)
COOLDOWN_DAYS = max(candidates.HORIZON_DAYS)

STATUSES = ("target", "no_baseline", "no_current", "above_baseline", "cooldown")

ONE_DAY = datetime.timedelta(days=1)


def cooldown_lookback_days():
    """冷却の判断が読む過去分の日数（t-62 から t-1 なら 62）。"""
    return COOLDOWN_DAYS + candidates.SMOOTHING_DAYS - 1


def recently_jumped(ratio_of_day, t, baseline, min_level):
    """終わりの日が t-56..t-1 の使える7日の平均のどれかが max(2 × B(t), V) より大きいか。

    読む日は t-62 から t-1 だけ。baseline は予言日 t の時点の B(t)。
    """
    if baseline is None or baseline < 0:
        raise ValueError("B(t) が無い、または負")
    if min_level is None or not min_level > 0:
        raise ValueError("最低の報道量は 0 より大きい値が要る")
    first = t - datetime.timedelta(days=cooldown_lookback_days())
    get = candidates._cached(ratio_of_day, first, t - ONE_DAY)
    limit = max(JUMP_MULTIPLIER * baseline, min_level)
    for k in range(1, COOLDOWN_DAYS + 1):
        m = candidates._block_mean(get, t - datetime.timedelta(days=k))
        if m is not None and m > limit:
            return True
    return False


def target_status(ratio_of_day, t, min_level):
    """予言日 t のタグの状態（STATUSES のどれか）。読む日は t-371 から t-1。"""
    b = candidates.baseline_level(ratio_of_day, t)
    if b is None:
        return "no_baseline"
    c = candidates.current_level(ratio_of_day, t)
    if c is None:
        return "no_current"
    if c > b:
        return "above_baseline"
    if recently_jumped(ratio_of_day, t, b, min_level):
        return "cooldown"
    return "target"


def week_summary(statuses):
    """一つの予言日の、タグごとの状態の一覧から、週の記録を作る。

    statuses: {タグ: 状態}。タグの一覧のすべてのタグが要る。
    戻り値の "week_kind":
      "has_targets"        対象が1件以上
      "no_target_missing"  対象が0件で、すべてのタグが no_baseline か no_current
                           （欠けた日はタグに依らないので、データの欠けによる週）
      "no_target_quiet"    対象が0件で、それ以外（どのタグも上か冷却中など）
    """
    counts = {s: 0 for s in STATUSES}
    for tag, s in statuses.items():
        if s not in counts:
            raise ValueError("状態が不正: %r" % s)
        counts[s] += 1
    if not statuses:
        raise ValueError("タグが無い")
    if counts["target"] > 0:
        kind = "has_targets"
    elif counts["no_baseline"] + counts["no_current"] == len(statuses):
        kind = "no_target_missing"
    else:
        kind = "no_target_quiet"
    return {"week_kind": kind, "status_counts": counts,
            "targets": sorted(t for t, s in statuses.items() if s == "target")}


def as_record():
    return {
        "proposed_label": PROPOSED_LABEL,
        "jumped_tags": {
            "rule": "not a target at t if any complete 7-day mean ending t-%d .. t-1 exceeds "
                    "max(%d * B(t), V); B(t) is the value at t" % (COOLDOWN_DAYS, JUMP_MULTIPLIER),
            "jump_multiplier": JUMP_MULTIPLIER,
            "cooldown_days": COOLDOWN_DAYS,
            "reads": "t-%d .. t-1" % cooldown_lookback_days(),
            "same_for_all_combinations": True,
            "applies_to": "stick chart, naive, threshold-period rate table, baseline period, forward",
        },
        "revision": "the cooldown rule and the empty-week rule may be revised only while working on the "
                    "method period, as a new sealed version with owner approval, sealed before the first "
                    "threshold-access record; the same version applies to every series; no change after "
                    "threshold-access; earlier versions are published alongside",
        "statuses": list(STATUSES),
        "empty_weeks": {
            "kinds": ["has_targets", "no_target_missing", "no_target_quiet"],
            "rule": "a prediction date with no target is not a trial: no probability, not scored, "
                    "not in the rate table; it is still recorded (forward: sealed weekly record with "
                    "zero predictions) and its count and kind are published",
            "undeterminable": "targets whose judgment is null are not scored; a week whose targets are "
                              "all null is counted separately as an undeterminable week",
            "clusters": "time clusters with no scored prediction are dropped from interval estimates; "
                        "the number dropped is published",
            "same_treatment": "stick chart, naive and baseline use the same week records",
        },
    }


def canonical_json():
    return json.dumps(as_record(), ensure_ascii=False, sort_keys=True, indent=2) + "\n"


def main(argv=None):
    if argv is None:
        argv = sys.argv[1:]
    if argv:
        sys.stderr.write("scoring: 引数は取らない\n")
        return 2
    sys.stdout.write(canonical_json())
    return 0


if __name__ == "__main__":
    sys.exit(main())
