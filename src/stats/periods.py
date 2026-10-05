#!/usr/bin/env python3
"""過去データの三期間の区切り（T-004）。

規則の定数だけから、区切りの日付を決定的に計算する。
- データは読まない。ネットワークは使わない。標準ライブラリだけを使う。
- 現在の日時（date.today() など）は読まない。「今日」は定数 TODAY として固定する。
  実行した日によって結果が変わらないようにするため。
- 日付はすべて UTC の暦日。日付 d は [d 00:00 UTC, d+1 00:00 UTC) を表す。

用語
  区画（block）        各期間が「自分のデータ」として持つ日付の範囲。三つの区画は
                       重ならず、すき間なく並ぶ。試運転の手順4で取得・閲覧してよいのは
                       手法を作る期間の区画だけ。
  予言日の範囲         その期間の中で、過去の予言を置いてよい日付の範囲（両端を含む）。
                       prediction_first / prediction_last はこの範囲の始まりと終わりで、
                       予言の曜日とは限らない。実際の予言日は prediction_dates() が返す。
  過去分（lookback）   予言日 t の入力に使う過去のデータ。日付 t-1 以前だけを使う。
  判定が読む最後の日   予言日 t に対して、判定が読むデータの最後の日を t + J とする
                       （J は判定期間と平滑化の幅などから決まる。未決事項3）。
  エンバーゴ           各区画の最後の EMBARGO_DAYS 日。ここには予言を置かない。
                       J <= EMBARGO_DAYS なら、どの予言の判定も自分の区画の中で終わる。

作り直し
  区画の境目を決める定数（DATA_START・TODAY・DATA_SETTLE_DAYS・BLOCK_WEIGHTS）は
  この提案の値に固定する。作り直すときは rebuild_periods() だけを使う。
  rebuild_periods() が受け取るのは作り直しのきっかけの値（J・共起の網の期間・
  同じ週の年数・素朴な予測が要る過去分）だけで、区画の境目は変わらない。
  出力（as_record / CLI）は、v1 の既定の出力も含めて必ず rebuild_periods() を通る。
  定数を手で書き換えて作り直すことはしない。
  FROZEN_BLOCKS との照合は同じコードの中の照合にすぎず、コードを書き換えれば外せる。
  本当の防御は、後の版の block_* を最初に封印した版と照合することで、これは
  封印係の検証手順に申し送る（docs/stats/periods.md 8章 (1)）。

版の名前
  PROPOSED_LABEL（"periods-v1"）は仮の名前。正式な版の番号は、封印の記録
  （追記のみ）の長さで決まる。出力の JSON でも "proposed_label" として出す。
  仮の名前では版を区別しない。区別は JSON の rebuild_triggers と deadline_status
  （きっかけの値を封印の記録に追記した時点が期限より前か）で行う。

使い方
  python3 -B src/stats/periods.py
      v1 の区切りを JSON（キー順・UTF-8）で出力する
  python3 -B src/stats/periods.py --last-read-offset-days J --network-window-days W
          --same-week-years N --naive-history-days H --deadline-status before_deadline
      作り直した区切りを出力する（きっかけの値はどれか一つ以上。
      --deadline-status は、きっかけの値を渡すときは必須）
"""

import argparse
import datetime
import json
import sys

# 仮の名前。正式な版の番号ではない（docs/stats/periods.md 8章 (3)）。
PROPOSED_LABEL = "periods-v1"

# ---------------------------------------------------------------------------
# 規則の定数（データを見ずに決めたもの。理由は docs/stats/periods.md）
# ---------------------------------------------------------------------------

# --- 区画の境目を決める定数。作り直しでも変えない（固定） ---

# 使ってよい最初の日。GDELT 2.0 は 2015-02-19 に始まり、GKG の国コードに誤りがあった
# のが 2015-03-01 の昼まで。誤りを含まない最初の完全な暦日（UTC）。
DATA_START = datetime.date(2015, 3, 2)

# 今日。T-004 の割り振りで与えられた固定の日付。
TODAY = datetime.date(2026, 10, 6)

# データが出そろうのを待つ日数。最も新しい区画の終わりは、
# 「TODAY - DATA_SETTLE_DAYS 以前で最後の月末日」とする。
DATA_SETTLE_DAYS = 5

# 三つの区画の長さの比（手法を作る期間 : 閾値を決める期間 : 基準値を測る期間）。
BLOCK_WEIGHTS = (2, 1, 1)

# --- 作り直しのきっかけになりうる定数（下限として使う） ---

# 普段の水準（直近365日の中央値）に要る日数。
MEDIAN_WINDOW_DAYS = 365
# 素朴な予測が「去年の同じ時期」を前後に幅を持たせて見るための余裕。
SEASONAL_MARGIN_DAYS = 35
# 予言の入力に要る過去分。手法を作る期間ではこの過去分を区画の中に収める。
LOOKBACK_DAYS = MEDIAN_WINDOW_DAYS + SEASONAL_MARGIN_DAYS

# 各区画の最後に予言を置かない日数。判定が読む最後の日のずれ J の上限でもある。
EMBARGO_DAYS = 90

# 予言の曜日（0 = 月曜）。提案値。前向きの予言の曜日に合わせる。
# 区画と予言日の範囲は曜日に依存しない。
PREDICTION_WEEKDAY = 0

PERIOD_NAMES = ("method", "threshold", "baseline")
PERIOD_LABELS_JA = {
    "method": "手法を作る期間",
    "threshold": "閾値を決める期間",
    "baseline": "基準値を測る期間",
}

# この提案で固定する区画の境目（compute_periods() の出力の写し）。
# rebuild_periods() は、計算した区画がこれと一致しなければ止まる。
FROZEN_BLOCKS = (
    ("method", datetime.date(2015, 3, 2), datetime.date(2020, 12, 14)),
    ("threshold", datetime.date(2020, 12, 15), datetime.date(2023, 11, 6)),
    ("baseline", datetime.date(2023, 11, 7), datetime.date(2026, 9, 30)),
)

ONE_DAY = datetime.timedelta(days=1)


def _last_day_of_month(d):
    first_next = (d.replace(day=28) + datetime.timedelta(days=4)).replace(day=1)
    return first_next - ONE_DAY


def latest_month_end_on_or_before(d):
    """d 以前で最後の月末日。"""
    end = _last_day_of_month(d)
    if end <= d:
        return end
    return d.replace(day=1) - ONE_DAY


def data_end(today=TODAY, settle_days=DATA_SETTLE_DAYS):
    """最も新しい区画の終わり。"""
    return latest_month_end_on_or_before(today - datetime.timedelta(days=settle_days))


def split_days(total_days, weights):
    """total_days 日を weights の比で整数に分ける。端数は最後の区画に足す。"""
    s = sum(weights)
    sizes = [total_days * w // s for w in weights[:-1]]
    sizes.append(total_days - sum(sizes))
    return sizes


def compute_periods(
    data_start=DATA_START,
    today=TODAY,
    settle_days=DATA_SETTLE_DAYS,
    weights=BLOCK_WEIGHTS,
    lookback_days=LOOKBACK_DAYS,
    embargo_days=EMBARGO_DAYS,
):
    """区画と予言日の範囲を計算する。戻り値は期間ごとの dict の list。

    引数で定数を差し替えられるのは、テストと、規則が定数にどう依存するかを
    確かめるためだけ。作り直しには rebuild_periods() を使う。
    """
    end = data_end(today, settle_days)
    total = (end - data_start).days + 1
    if total <= 0:
        raise ValueError("データの範囲が空")
    sizes = split_days(total, weights)
    periods = []
    cursor = data_start
    for i, (name, size) in enumerate(zip(PERIOD_NAMES, sizes)):
        block_start = cursor
        block_end = cursor + datetime.timedelta(days=size - 1)
        if i == 0:
            # 最も古い区画は、過去分を区画の中に収める（data_start より前に行かないため）。
            pred_first = block_start + datetime.timedelta(days=lookback_days)
        else:
            # ほかの区画は、過去分が前の区画に入ることを許す。ただし data_start より前には
            # 行かない（docs/stats/periods.md 3章 (3)）。
            pred_first = max(block_start, data_start + datetime.timedelta(days=lookback_days))
        pred_last = block_end - datetime.timedelta(days=embargo_days)
        if pred_first > pred_last:
            raise ValueError("予言日の範囲が空: " + name)
        periods.append(
            {
                "name": name,
                "label_ja": PERIOD_LABELS_JA[name],
                "block_start": block_start,
                "block_end": block_end,
                "prediction_first": pred_first,
                "prediction_last": pred_last,
            }
        )
        cursor = block_end + ONE_DAY
    return periods


def prediction_dates(period, weekday=PREDICTION_WEEKDAY):
    """予言日の範囲のうち、指定の曜日の日付をすべて返す（実際の予言日）。"""
    d = period["prediction_first"]
    d += datetime.timedelta(days=(weekday - d.weekday()) % 7)
    out = []
    while d <= period["prediction_last"]:
        out.append(d)
        d += datetime.timedelta(days=7)
    return out


def horizon_is_valid(last_read_offset_days, embargo_days=EMBARGO_DAYS):
    """判定が読む最後の日のずれ J を受け取り、この区切りで有効かを返す。

    J は「t + J 日の暦日まで読む」の J。判定期間 30 日・終わりの日だけを読むなら J = 30。
    平滑化などで後ろに読む日があれば、その分を足した値を渡す。
    """
    return 1 <= last_read_offset_days <= embargo_days


def same_week_lookback_days(years, margin_days=SEASONAL_MARGIN_DAYS):
    """「過去数年の同じ週」案で、years 年さかのぼるのに要る過去分（多めに見積もる）。"""
    return years * 366 + margin_days


def required_embargo(last_read_offset_days=None):
    """作り直しで使うエンバーゴ。J が 90 日以下なら 90 日のまま（縮めない）。"""
    if last_read_offset_days is None:
        return EMBARGO_DAYS
    if last_read_offset_days < 1:
        raise ValueError("J は 1 以上")
    return max(EMBARGO_DAYS, last_read_offset_days)


def required_lookback(network_window_days=None, same_week_years=None, naive_history_days=None):
    """作り直しで使う過去分。400 日を下限とし、きっかけの値のうち最も長いものに合わせる。"""
    need = [LOOKBACK_DAYS]
    if network_window_days is not None:
        need.append(network_window_days)
    if same_week_years is not None:
        need.append(same_week_lookback_days(same_week_years))
    if naive_history_days is not None:
        need.append(naive_history_days)
    return max(need)


def rebuild_periods(
    last_read_offset_days=None,
    network_window_days=None,
    same_week_years=None,
    naive_history_days=None,
):
    """作り直しの唯一の入口。きっかけの値だけを受け取り、ほかの定数は固定の値を使う。

    DATA_START・TODAY・DATA_SETTLE_DAYS・BLOCK_WEIGHTS は引数に取らない。
    計算した区画の境目が FROZEN_BLOCKS と一致しなければ止まる。
    すべての値が None、またはどのきっかけも下限を超えないときは、この提案と同じ日付になる。
    """
    ps = compute_periods(
        data_start=DATA_START,
        today=TODAY,
        settle_days=DATA_SETTLE_DAYS,
        weights=BLOCK_WEIGHTS,
        lookback_days=required_lookback(
            network_window_days, same_week_years, naive_history_days
        ),
        embargo_days=required_embargo(last_read_offset_days),
    )
    got = tuple((p["name"], p["block_start"], p["block_end"]) for p in ps)
    if got != FROZEN_BLOCKS:
        raise RuntimeError("区画の境目が固定の値と一致しない")
    return ps


def same_week_feasibility(years):
    """「過去数年の同じ週」案を採ったときの、各期間の予言日の範囲の始まりと月曜の回数。"""
    out = {}
    for p in rebuild_periods(same_week_years=years):
        out[p["name"]] = {
            "prediction_first": p["prediction_first"],
            "monday_count": len(prediction_dates(p)),
        }
    return out


TRIGGER_NAMES = (
    "last_read_offset_days",
    "network_window_days",
    "same_week_years",
    "naive_history_days",
)
DEADLINE_STATUSES = ("before_deadline", "after_deadline")


def effective_label(lookback_days, embargo_days):
    """仮の名前。きっかけで定数が動かなければ PROPOSED_LABEL、動けば値から決まる名前。

    どちらも正式な版の番号ではない。仮の名前では版を区別しない（きっかけの値や
    deadline_status が違っても同じ名前になりうる）。版の区別は JSON の
    rebuild_triggers・deadline_status と封印の記録の件数で行う
    （docs/stats/periods.md 8章 (3)）。
    """
    if lookback_days == LOOKBACK_DAYS and embargo_days == EMBARGO_DAYS:
        return PROPOSED_LABEL
    return "%s-rebuilt-L%d-E%d" % (PROPOSED_LABEL, lookback_days, embargo_days)


def rules(lookback_days=LOOKBACK_DAYS, embargo_days=EMBARGO_DAYS):
    """封印のときに区切りと一緒に記録する、規則の定数（作り直しで使った値を含む）。"""
    return {
        "proposed_label": effective_label(lookback_days, embargo_days),
        "data_start": DATA_START.isoformat(),
        "today": TODAY.isoformat(),
        "data_settle_days": DATA_SETTLE_DAYS,
        "block_weights": list(BLOCK_WEIGHTS),
        "median_window_days": MEDIAN_WINDOW_DAYS,
        "seasonal_margin_days": SEASONAL_MARGIN_DAYS,
        "lookback_days_floor": LOOKBACK_DAYS,
        "embargo_days_floor": EMBARGO_DAYS,
        "lookback_days": lookback_days,
        "embargo_days": embargo_days,
        "prediction_weekday": PREDICTION_WEEKDAY,
        "timezone": "UTC",
        "frozen_on_rebuild": [
            "data_start",
            "today",
            "data_settle_days",
            "block_weights",
            "median_window_days",
            "seasonal_margin_days",
        ],
    }


def as_record(
    last_read_offset_days=None,
    network_window_days=None,
    same_week_years=None,
    naive_history_days=None,
    deadline_status=None,
):
    """規則と区切りを、JSON にできる形でまとめる。必ず rebuild_periods() を通す。

    きっかけの値を一つでも渡すときは、deadline_status（"before_deadline" か
    "after_deadline"）を必ず渡す。何も渡さないときは v1 の提案そのもので、
    deadline_status は null になる。
    """
    triggers = {
        "last_read_offset_days": last_read_offset_days,
        "network_window_days": network_window_days,
        "same_week_years": same_week_years,
        "naive_history_days": naive_history_days,
    }
    any_trigger = any(v is not None for v in triggers.values())
    if any_trigger and deadline_status not in DEADLINE_STATUSES:
        raise ValueError("きっかけの値を渡すときは deadline_status を明示する")
    if not any_trigger and deadline_status is not None:
        raise ValueError("きっかけの値が無いときは deadline_status を渡さない")
    lookback = required_lookback(network_window_days, same_week_years, naive_history_days)
    embargo = required_embargo(last_read_offset_days)
    ps = rebuild_periods(**triggers)
    out = []
    for p in ps:
        row = {k: (v.isoformat() if isinstance(v, datetime.date) else v) for k, v in p.items()}
        ds = prediction_dates(p)
        row["first_prediction_date"] = ds[0].isoformat()
        row["last_prediction_date"] = ds[-1].isoformat()
        row["prediction_count"] = len(ds)
        out.append(row)
    return {
        "rules": rules(lookback, embargo),
        "rebuild_triggers": triggers,
        "deadline_status": deadline_status,
        "periods": out,
        "max_last_read_offset_days": embargo,
    }


def canonical_json(**kwargs):
    return json.dumps(as_record(**kwargs), ensure_ascii=False, sort_keys=True, indent=2) + "\n"


def _positive_int(text):
    v = int(text)
    if v < 1:
        raise argparse.ArgumentTypeError("1 以上の整数")
    return v


class _Once(argparse.Action):
    """同じ引数が二度渡されたら止める（後の値で黙って上書きしないため）。"""

    def __call__(self, parser, namespace, values, option_string=None):
        if getattr(namespace, self.dest, None) is not None:
            parser.error("%s が二度渡された" % option_string)
        setattr(namespace, self.dest, values)


def build_parser():
    ap = argparse.ArgumentParser(
        allow_abbrev=False,
        description="三期間の区切りを JSON で出力する。引数が無ければ v1 の提案。"
        "きっかけの値を渡すと、rebuild_periods() で作り直した区切りを出す。"
    )
    ap.add_argument("--last-read-offset-days", action=_Once, type=_positive_int, help="J（判定が読む最後の日のずれ）")
    ap.add_argument("--network-window-days", action=_Once, type=_positive_int, help="共起の網を作る期間の日数")
    ap.add_argument("--same-week-years", action=_Once, type=_positive_int, help="「過去数年の同じ週」の年数 N")
    ap.add_argument("--naive-history-days", action=_Once, type=_positive_int, help="素朴な予測が要る過去分の日数")
    ap.add_argument(
        "--deadline-status",
        action=_Once,
        choices=DEADLINE_STATUSES,
        help="きっかけの値を渡すときは必須。期限（8章 (2)）の前か後か",
    )
    return ap


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        text = canonical_json(
            last_read_offset_days=args.last_read_offset_days,
            network_window_days=args.network_window_days,
            same_week_years=args.same_week_years,
            naive_history_days=args.naive_history_days,
            deadline_status=args.deadline_status,
        )
    except ValueError as e:
        sys.stderr.write("periods: %s\n" % e)
        return 2
    sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
