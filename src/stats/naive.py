#!/usr/bin/env python3
"""素朴な予測（T-019）。直近の報道量・季節性・予定された行事（去年の同じ時期）。

文書は docs/stats/naive-scoring.md 3章（T-022 で tags-naive.md 3章から移した。章と節の番号は同じ）。
- データは読まない。ネットワークは使わない。現在の日時を読まない。
- 予言日 t の特徴量は、日付 t-399 から t-1 のデータだけから計算する（naive_lookback_days()）。
  t 以降の日を読もうとすると止まる（candidates._cached と同じ見張り）。
- 物差しは普段の水準・判定と同じ7日の平均（欠けた日を含むまとまりは使わない）。

特徴量（倍率 m と判定期間 H の組み合わせごと。V は最低の報道量）
  L      = max(m × B(t), V)                      島の判定の限界（t の時点で決まる）
  g(x)   = log((x + V) / (L + V))
  recent       = g(c(t))                         予言の時点の報道量（candidates.current_level）
  recent_peak  = g(P)                            P：終わりの日が t-28..t-1 の7日の平均の最大
  season_exact = g(S0)                           S0：去年の判定期間 [t+1-365, t+H-365] に
                                                 収まる7日の平均の最大
  season_wide  = g(S35)                          S35：同じ期間を前後35日ずつ広げた中の最大
  season_none  = 1（S35 が決まらない）/ 0         決まらないとき season_exact と season_wide は 0
  size         = log((B(t) + V) / V)
  S0 が決まらず S35 が決まるときは S0 = S35。P が決まらないときは P = c(t)。

モデル
  組み合わせごとのロジスティック回帰（切片 + 上の6つ）。係数は手法を作る期間の予言日と
  対象（scoring.target_status が "target"）と判定（candidates.judge、判定不能は除く）だけで決める。
  行は (予言日, タグ名) の順に並べてから推定する（fit_rows）。推定の定数・手順・学習データの選び方・
  行の並べ方は naive-v1 の値に固定し、改訂で変えてよいのは特徴量を足すことだけ。
  推定はリッジ（RIDGE_LAMBDA、切片にも掛ける）付きのニュートン法で、手順を固定する。

使い方
  .venv/bin/python -B src/stats/naive.py      規則の定数と過去分の日数を JSON で出力する
"""

import datetime
import json
import math
import sys

import candidates
import periods
import scoring

PROPOSED_LABEL = "naive-v1"

SEASON_SHIFT_DAYS = 365
SEASON_MARGIN_DAYS = periods.SEASONAL_MARGIN_DAYS  # 35
RECENT_PEAK_DAYS = 28

FEATURES = ("intercept", "recent", "recent_peak", "season_exact", "season_wide", "season_none", "size")

RIDGE_LAMBDA = 1.0
MAX_ITER = 100
TOL = 1e-10

ONE_DAY = datetime.timedelta(days=1)
DAYS = datetime.timedelta


def season_windows(t, horizon_days):
    """去年の同じ時期の範囲 [(始まり, 終わり)]（ちょうど、と前後35日広げたもの）。"""
    a = t + ONE_DAY - DAYS(days=SEASON_SHIFT_DAYS)
    b = t + DAYS(days=horizon_days) - DAYS(days=SEASON_SHIFT_DAYS)
    m = DAYS(days=SEASON_MARGIN_DAYS)
    return (a, b), (a - m, b + m)


def naive_lookback_days(horizon_days=None):
    """予言日 t の特徴量が読む最も古い日が t-何日か（判定期間の候補の全体での最大）。

    7日のまとまりの分（6日）を含めて数える。
    """
    hs = candidates.HORIZON_DAYS if horizon_days is None else (horizon_days,)
    t = datetime.date(2000, 1, 1)
    need = [
        candidates.BASELINE_WINDOW_DAYS + candidates.SMOOTHING_DAYS - 1,       # B(t)
        candidates.CURRENT_SEARCH_DAYS + candidates.SMOOTHING_DAYS - 1,        # c(t)
        RECENT_PEAK_DAYS + candidates.SMOOTHING_DAYS - 1,                      # P
        scoring.cooldown_lookback_days(),                                      # 冷却
    ]
    for h in hs:
        for (a, b) in season_windows(t, h):
            if b >= t:
                raise ValueError("去年の同じ時期が予言日に届く")
            need.append((t - a).days)
    return max(need)


def latest_season_day_offset(horizon_days):
    """去年の同じ時期（広い方）の最後の日が t-何日か（t 以降を読まないことの確認用）。"""
    t = datetime.date(2000, 1, 1)
    return (t - season_windows(t, horizon_days)[1][1]).days


def _max_block_mean_inside(get, first, last):
    """[first, last] に完全に収まる使える7日の平均の最大。無ければ None。"""
    best = None
    end = first + DAYS(days=candidates.SMOOTHING_DAYS - 1)
    while end <= last:
        m = candidates._block_mean(get, end)
        if m is not None and (best is None or m > best):
            best = m
        end += ONE_DAY
    return best


def raw_levels(ratio_of_day, t, horizon_days):
    """特徴量のもとになる値。読む日は t-399 から t-1 だけ。"""
    first = t - DAYS(days=naive_lookback_days())
    get = candidates._cached(ratio_of_day, first, t - ONE_DAY)
    b = candidates.baseline_level(get, t)
    c = candidates.current_level(get, t)
    p = _max_block_mean_inside(get, t - DAYS(days=RECENT_PEAK_DAYS + candidates.SMOOTHING_DAYS - 1),
                               t - ONE_DAY)
    (a0, b0), (a1, b1) = season_windows(t, horizon_days)
    s0 = _max_block_mean_inside(get, a0, b0)
    s35 = _max_block_mean_inside(get, a1, b1)
    return {"B": b, "c": c, "P": p, "S0": s0, "S35": s35}


def features_from_levels(levels, multiplier, min_level):
    """raw_levels の値から特徴量の並び（FEATURES の順）を作る。B と c は決まっている必要がある。"""
    b, c = levels["B"], levels["c"]
    if b is None or c is None:
        raise ValueError("B(t) と c(t) が要る（対象でないタグに特徴量は作らない）")
    if not min_level > 0:
        raise ValueError("V は 0 より大きい")
    v = min_level
    lim = max(multiplier * b, v)

    def g(x):
        return math.log((x + v) / (lim + v))

    p = levels["P"] if levels["P"] is not None else c
    s35 = levels["S35"]
    s0 = levels["S0"] if levels["S0"] is not None else s35
    if s35 is None:
        se, sw, sn = 0.0, 0.0, 1.0
    else:
        se, sw, sn = g(s0), g(s35), 0.0
    return [1.0, g(c), g(p), se, sw, sn, math.log((b + v) / v)]


def features(ratio_of_day, t, horizon_days, multiplier, min_level):
    return features_from_levels(raw_levels(ratio_of_day, t, horizon_days), multiplier, min_level)


# ---------------------------------------------------------------------------
# ロジスティック回帰（手順を固定した参照実装）
# ---------------------------------------------------------------------------

def _sigmoid(z):
    if z >= 0:
        return 1.0 / (1.0 + math.exp(-z))
    e = math.exp(z)
    return e / (1.0 + e)


def _log1pexp(z):
    return z + math.log1p(math.exp(-z)) if z > 0 else math.log1p(math.exp(z))


def _objective(X, y, beta, lam):
    s = 0.0
    for xi, yi in zip(X, y):
        z = sum(a * b for a, b in zip(xi, beta))
        s += _log1pexp(z) - yi * z
    return s + 0.5 * lam * sum(b * b for b in beta)


def _solve(A, b):
    """ガウスの消去法（部分ピボット）。"""
    n = len(b)
    M = [row[:] + [b[i]] for i, row in enumerate(A)]
    for col in range(n):
        piv = max(range(col, n), key=lambda r: (abs(M[r][col]), -r))
        if M[piv][col] == 0:
            raise ValueError("特異な行列")
        M[col], M[piv] = M[piv], M[col]
        for r in range(col + 1, n):
            f = M[r][col] / M[col][col]
            for k in range(col, n + 1):
                M[r][k] -= f * M[col][k]
    x = [0.0] * n
    for r in range(n - 1, -1, -1):
        x[r] = (M[r][n] - sum(M[r][k] * x[k] for k in range(r + 1, n))) / M[r][r]
    return x


def fit_logistic(X, y, lam=RIDGE_LAMBDA):
    """リッジ付きロジスティック回帰。行の順に足し合わせる（結果は入力の順に依る）。

    X: 各行が FEATURES の順の並び（先頭は切片の 1.0）。y: 0 か 1。
    戻り値 {"coef": [...], "iterations": n, "converged": bool}。
    手順：β=0 から始め、ニュートン法の一歩で目的関数が減らなければ、一歩を半分にする（最大30回）。
    max|Δβ| < TOL で止める。MAX_ITER 回で収まらなければ converged = False（使わない）。
    """
    if not X or len(X) != len(y):
        raise ValueError("データが無い、または長さが違う")
    k = len(X[0])
    if any(len(r) != k for r in X) or any(yi not in (0, 1) for yi in y):
        raise ValueError("形が違う")
    beta = [0.0] * k
    obj = _objective(X, y, beta, lam)
    for it in range(1, MAX_ITER + 1):
        grad = [0.0] * k
        H = [[0.0] * k for _ in range(k)]
        for xi, yi in zip(X, y):
            p = _sigmoid(sum(a * b for a, b in zip(xi, beta)))
            w = p * (1.0 - p)
            for a in range(k):
                grad[a] += (yi - p) * xi[a]
                for b in range(a, k):
                    H[a][b] += w * xi[a] * xi[b]
        for a in range(k):
            for b in range(a):
                H[a][b] = H[b][a]
        for a in range(k):
            grad[a] -= lam * beta[a]
            H[a][a] += lam
        step = _solve(H, grad)
        scale = 1.0
        for _ in range(30):
            cand = [b + scale * s for b, s in zip(beta, step)]
            new_obj = _objective(X, y, cand, lam)
            if new_obj <= obj:
                break
            scale /= 2.0
        else:
            return {"coef": beta, "iterations": it, "converged": False}
        delta = max(abs(scale * s) for s in step)
        beta, obj = cand, new_obj
        if delta < TOL:
            return {"coef": beta, "iterations": it, "converged": True}
    return {"coef": beta, "iterations": MAX_ITER, "converged": False}


def sort_rows(rows):
    """学習の行を、規則で決めた順（予言日、タグ名）に並べる。

    rows: (予言日 t, タグ名, 特徴量の並び, 0 か 1) の並び。同じ (t, タグ名) が二つあれば止まる。
    前提：タグ名はタグの一覧の中で一意（一覧は名前の集合として作るので重複しない）。
    この前提があるので、(予言日, タグ名) で行の順が一つに決まる。
    入力の順に依らず、同じ行の集まりからは同じ並びになる。
    """
    out = sorted(rows, key=lambda r: (r[0], r[1]))
    for a, b in zip(out, out[1:]):
        if (a[0], a[1]) == (b[0], b[1]):
            raise ValueError("同じ予言日とタグの行が二つある")
    return out


def fit_rows(rows):
    """sort_rows で並べ直してから fit_logistic で推定する。学習は必ずこの入口を通す。"""
    ordered = sort_rows(rows)
    return fit_logistic([r[2] for r in ordered], [r[3] for r in ordered])


def predict(coef, x):
    if len(coef) != len(x):
        raise ValueError("長さが違う")
    return _sigmoid(sum(a * b for a, b in zip(coef, x)))


def periods_trigger():
    """periods.md 8章のきっかけ「素朴な予測が要る過去分」の値と、作り直しが要るか。"""
    need = naive_lookback_days()
    return {
        "naive_history_days": need,
        "periods_lookback_days": periods.LOOKBACK_DAYS,
        "rebuild_needed": need > periods.LOOKBACK_DAYS,
        "lookback_after": periods.required_lookback(naive_history_days=need),
    }


def as_record():
    return {
        "proposed_label": PROPOSED_LABEL,
        "features": list(FEATURES),
        "definitions": {
            "L": "max(m * B(t), V)",
            "g": "log((x + V) / (L + V))",
            "recent": "g(c(t)), c = candidates.current_level",
            "recent_peak": "g(max complete 7-day mean ending t-%d .. t-1); none -> c(t)" % RECENT_PEAK_DAYS,
            "season_exact": "g(max complete 7-day mean inside [t+1-%d, t+H-%d]); none -> season_wide value"
                            % (SEASON_SHIFT_DAYS, SEASON_SHIFT_DAYS),
            "season_wide": "g(max complete 7-day mean inside [t+1-%d-%d, t+H-%d+%d])"
                           % (SEASON_SHIFT_DAYS, SEASON_MARGIN_DAYS, SEASON_SHIFT_DAYS, SEASON_MARGIN_DAYS),
            "season_none": "1 if the wide window has no complete block (then season_exact = season_wide = 0)",
            "size": "log((B(t) + V) / V)",
        },
        "season_shift_days": SEASON_SHIFT_DAYS,
        "season_margin_days": SEASON_MARGIN_DAYS,
        "recent_peak_days": RECENT_PEAK_DAYS,
        "model": "logistic regression per (m, H) combination, 21 models, fit on method-period "
                 "prediction dates, targets per scoring.target_status, labels per candidates.judge "
                 "(null labels dropped)",
        "fit": {"ridge_lambda": RIDGE_LAMBDA, "penalize_intercept": True, "start": "zeros",
                "method": "Newton with step halving (max 30)", "max_iter": MAX_ITER, "tol": TOL,
                "not_converged": "model not used; stop and report"},
        "training_data": "all prediction dates (prediction weekday) in the method period's prediction "
                         "range; all tags of the sealed tag list with status target; label = candidates.judge "
                         "with the sealed V; null labels dropped; nothing else dropped",
        "row_order": "rows sorted by (prediction date, tag name) ascending before fitting (fit_rows); "
                     "tag names are unique within the tag list; duplicate (date, tag) stops the fit",
        "revision_rule": "during the method period, the only allowed change is adding features (never "
                         "removing or changing one), as a new sealed version; ridge_lambda, max_iter, tol, "
                         "the fitting procedure, the training-data selection and the row order stay at the "
                         "naive-v1 values; added features also go into the stick-chart model; v1 results are "
                         "published alongside",
        "periods_trigger": periods_trigger(),
        "latest_season_day_offset": {str(h): latest_season_day_offset(h) for h in candidates.HORIZON_DAYS},
    }


def canonical_json():
    return json.dumps(as_record(), ensure_ascii=False, sort_keys=True, indent=2) + "\n"


def main(argv=None):
    if argv is None:
        argv = sys.argv[1:]
    if argv:
        sys.stderr.write("naive: 引数は取らない\n")
        return 2
    sys.stdout.write(canonical_json())
    return 0


if __name__ == "__main__":
    sys.exit(main())
