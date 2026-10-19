#!/usr/bin/env python3
"""T-134：4段の比べ（手法を作る期間の区画だけの探索。封印しない）。

オーナーの決定（reviews/T-134.md）の4段：1 Null（全タグ同一確率）、2 Historical（タグごとの過去の島の割合）、
3 Naive（今の素朴な予測）、4 Digital Stick Chart（3 に網・波の手がかりを足したもの）。各段と上乗せ（2−1、3−2、4−3）を、
対数損失・ブライア・較正・上位10の島と、4週束ねの差の範囲で並べる。倍率 2・4・8、判定期間 28 日。主は分け方 B、A は参考。
島の定義は変えない（C7、V = A、一度跳ねたタグの扱いあり）。全部並べ、選ばない・勧めない。

試す形（下の定数）は、本番の前にこのファイルに書き、コミットしてから流す。結果に、このファイルの sha256 を入れる。

段1（Null）：その予言日のすべての対象に同じ確率。
  null_exp：予言日 t の時点で判定が確定した行（予言日 s の判定期間 s+1〜s+28 が t-1 までに終わったもの。s ≤ t − 35 日、
    週の番号で ti − 5 以下）すべての島の割合。(島 + 1) / (行 + 2)（確定した行が無い最初の5週は 0.5）。
  null_fix：分け方の学習の行の島の割合（学習の行だけで決めた定数。段3 の係数と同じ扱い）。
段2（Historical）：タグごとの過去の島の割合を、段1（null_exp）へ縮める。
  p = (k + a × p0) / (n + a)。k・n はそのタグの判定が確定した行の島・行の数（上と同じ確定の条件）、p0 は null_exp の値。
  使う過去の長さ HIST_WINDOWS（all：最初の予言日から、52：直近52週 = 予言日 t − 52 週〜t − 5 週）、縮めの強さ HIST_A。
段3（Naive）：naive.py の7つの特徴量、ロジスティック回帰、リッジ 1（T-117〜T-127 と同じ）。学習の行で当てはめる。
段4（Digital Stick Chart）：段3 に、T-117〜T-127 で試した手がかりを足したロジスティック回帰（TIER4_FORMS）。
  nbwave：網の1歩・2歩の隣の上がりの重み付き平均と欠けの印（T-119 の D_hop12 と同じ。網は t を含む月の前の12か月の lift10）。
  chain：連鎖の励起（T-127 の chain_D1_L2。4つの関係）。
  nbwave_chain：両方。
  この3つは、T-117〜T-127 の結果（同じ期間・同じ分け方）を見たあとで決めた。選んだことの偏りがありうる（要約に書く）。
入れ子の並び（参考。主張2 の分解の別の示し方）：
  N3_h：段3 の特徴量に logit(段2 の形 h の確率) を足したロジスティック回帰。N4_{h,f}：N3_h に段4 の形 f の列を足したもの。

予言の時点のデータだけ：日の比率は ReadGuard（入力は t-399〜t-1、判定は t+1〜t+28）。網の月は予言日を含む月より前で、
網の最後の日 < t を確かめる。段1・段2 は、判定期間が t より前に終わった行の判定だけを使う（hist_counts のテストで確かめる）。
区画の外（2020-12-15 以降）は読まない。閾値を決める期間・基準値を測る期間のデータは読まない。

流し方（プロジェクトのルートで。TMPDIR は scratchpad の中に）
  .venv/bin/python -B src/stats/explore_tiers.py --t117-cache <explore-t117-cache/run2> --out-dir <書き出す先>

Data: The GDELT Project (https://www.gdeltproject.org/). This project is not affiliated with or endorsed by the GDELT Project.
"""

import argparse
import array
import collections
import datetime
import hashlib
import json
import math
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import explore_chain as ch  # noqa: E402

sea = ch.sea
x2 = ch.x2
ex = ch.ex
ed = ch.ed
eg = ch.eg
em = ch.em
es = ch.es
ei = ch.ei
naive = ch.naive

LABEL = "explore-tiers-t134-v3"   # v3：T-136 で要約の文だけ手直し（表と作り方は v2 と同じ）。v2：T-134 の差し戻し1回目
MULTIPLIERS = em.MULTIPLIERS
HORIZON = em.HORIZON

# ---------------------------------------------------------------------------
# 試す形（本番の前に書いた）
# ---------------------------------------------------------------------------
KNOWN_LAG_WEEKS = 5                      # 判定が確定している予言日：週の番号で ti − 5 以下（s + 28 ≤ t − 7）
HIST_WINDOWS = ("all", 52)
HIST_A = (10, 50, 200)
NULL_FORMS = ("null_exp", "null_fix")
CHAIN_VARIANT = (1, 2.0)                 # T-127 の D = 1、λ = 2
TIER4_FORMS = ("nbwave", "chain", "nbwave_chain")
NBWAVE_COLUMNS = ("hop1_rise", "hop1_miss", "hop2_rise", "hop2_miss")
CHAIN_COLUMNS = tuple(ch.exc_column(r, CHAIN_VARIANT[0], CHAIN_VARIANT[1]) for r in ch.EXC_RELATIONS)
CAL_BINS = 10
SPLITS = ("B", "A")
SPLIT_MAIN = "B"
MAIN_M = 4
# v2（T-134 の差し戻し1回目。本番の前に書いた）
# 段2 を学習の行で較正した形：切片と logit(段2 の確率) だけのロジスティック回帰（リッジ 1）。名前は hcal_<段2 の形>。
# 識別と較正の分け方：確かめの行の上で、確率を [1, logit(p)] でロジスティック回帰し直した（リッジ 1）対数損失を「較正し直した対数損失」
#   （並べ方＝識別だけで決まる部分の目安）とし、もとの対数損失との差を「較正の損」とする。確かめの行で当てはめるので、前向きでは使えない目安。
# 窓をずらす見当：分け方ごとの確かめの週の中で、SIM_WINDOWS 週の窓を SIM_STRIDE 週ずつずらし、窓ごとに4週束ねの範囲（同じ
#   ブートストラップ）を作り、範囲の上端が0より下・下端が0より上の窓の割合を数える。比べる組は N4−N3 を除く上乗せの組。
# 束の数の下限：MIN_BLOCKS 未満の束での範囲は、狭く出がちなので判定に使わない目安とする（要約に書く）。
SIM_WINDOWS = (13, 26, 52)
SIM_STRIDE = 4
MIN_BLOCKS = 10


class TierError(Exception):
    pass


def hist_forms():
    return [("hist_%s_a%d" % (w, a), w, a) for w in HIST_WINDOWS for a in HIST_A]


def tier4_columns(form):
    return {"nbwave": NBWAVE_COLUMNS, "chain": CHAIN_COLUMNS, "nbwave_chain": NBWAVE_COLUMNS + CHAIN_COLUMNS}[form]


def model_list():
    """(名前, 段, 種類, 形)。種類：null・hist・logit。"""
    out = [(n, 1, "null", n) for n in NULL_FORMS]
    out += [(h, 2, "hist", h) for h, _w, _a in hist_forms()]
    out += [("hcal_" + h, 2, "logit_only", ("lh_" + h,)) for h, _w, _a in hist_forms()]
    out.append(("naive", 3, "logit", ()))
    out += [("t4_" + f, 4, "logit", tier4_columns(f)) for f in TIER4_FORMS]
    for h, _w, _a in hist_forms():
        out.append(("N3_" + h, 3, "logit", ("lh_" + h,)))
        for f in TIER4_FORMS:
            out.append(("N4_%s_%s" % (h, f), 4, "logit", ("lh_" + h,) + tier4_columns(f)))
    return out


def diff_pairs():
    """(上乗せの名前, 比べるモデル, 基準のモデル)。"""
    out = []
    for h, _w, _a in hist_forms():
        for n in NULL_FORMS:
            out.append(("2-1", h, n))
    for h, _w, _a in hist_forms():
        for n in NULL_FORMS:
            out.append(("2c-1", "hcal_" + h, n))
    for n in NULL_FORMS:
        out.append(("3-1", "naive", n))
    for h, _w, _a in hist_forms():
        out.append(("3-2", "naive", h))
    for h, _w, _a in hist_forms():
        out.append(("3-2c", "naive", "hcal_" + h))
    for f in TIER4_FORMS:
        out.append(("4-3", "t4_" + f, "naive"))
    for f in TIER4_FORMS:
        out.append(("4-1", "t4_" + f, "null_exp"))
    for h, _w, _a in hist_forms():
        out.append(("N3-2", "N3_" + h, h))
        out.append(("N3-2c", "N3_" + h, "hcal_" + h))
        for f in TIER4_FORMS:
            out.append(("N4-N3", "N4_%s_%s" % (h, f), "N3_" + h))
    return out


# ---------------------------------------------------------------------------
# 段1・段2（予言日 t の時点で判定が確定した行だけ）
# ---------------------------------------------------------------------------

def hist_counts(rows_by_week, n, W, mi):
    """週ごと・タグごとの (島, 行) の累積。rows_by_week[w] = [(タグ, 判定3つ)]。
    戻り値 (ck, cn, gk, gn)：ck[i][w]・cn[i][w] は週 0〜w-1 のタグ i の島・行の数、gk[w]・gn[w] は全タグの和。"""
    ck = [array.array("l", [0] * (W + 1)) for _ in range(n)]
    cn = [array.array("l", [0] * (W + 1)) for _ in range(n)]
    gk = array.array("l", [0] * (W + 1))
    gn = array.array("l", [0] * (W + 1))
    dk = [collections.Counter() for _ in range(W)]
    dn = [collections.Counter() for _ in range(W)]
    for w in range(W):
        for i, js in rows_by_week.get(w, ()):
            dn[w][i] += 1
            if js[mi]:
                dk[w][i] += 1
    for i in range(n):
        a = ck[i]
        b = cn[i]
        for w in range(W):
            a[w + 1] = a[w] + dk[w].get(i, 0)
            b[w + 1] = b[w] + dn[w].get(i, 0)
    for w in range(W):
        gk[w + 1] = gk[w] + sum(dk[w].values())
        gn[w + 1] = gn[w] + sum(dn[w].values())
    return ck, cn, gk, gn


def known_end(ti):
    """予言日 ti の時点で判定が確定した週の範囲の終わり（この番号の週は含まない）。"""
    return max(0, ti - KNOWN_LAG_WEEKS + 1)


def null_exp(ti, gk, gn):
    e = known_end(ti)
    return (gk[e] + 1) / (gn[e] + 2)


def hist_prob(ti, i, window, a, counts):
    ck, cn, gk, gn = counts
    e = known_end(ti)
    s = 0 if window == "all" else max(0, ti - window)
    s = min(s, e)
    k = ck[i][e] - ck[i][s]
    nn = cn[i][e] - cn[i][s]
    p0 = null_exp(ti, gk, gn)
    return (k + a * p0) / (nn + a)


def logit(p):
    p = min(max(p, 1e-9), 1 - 1e-9)
    return math.log(p / (1 - p))


# ---------------------------------------------------------------------------
# 指標
# ---------------------------------------------------------------------------

def calibration(ps, ys, bins=CAL_BINS):
    """(確率の平均, 島の割合, ECE)。ECE は確率の順に同じ件数の bins に分けた |平均の確率 − 島の割合| の件数の重み付き平均。"""
    n = len(ps)
    order = sorted(range(n), key=lambda r: (ps[r], r))
    ece = 0.0
    for b in range(bins):
        idx = order[b * n // bins:(b + 1) * n // bins]
        if not idx:
            continue
        mp = sum(ps[r] for r in idx) / len(idx)
        my = sum(ys[r] for r in idx) / len(idx)
        ece += len(idx) / n * abs(mp - my)
    return sum(ps) / n, sum(ys) / n, ece


def metrics(ps, ys, weeks, tags):
    ll = es.log_loss_terms(ps, ys)
    br = [(p - y) ** 2 for p, y in zip(ps, ys)]
    tk = es.topk_by_week(ps, ys, weeks, tags)
    mp, my, ece = calibration(ps, ys)
    return {"n": len(ys), "pos": sum(ys), "logloss": sum(ll) / len(ll), "brier": sum(br) / len(br),
            "auc": es.auc(ps, ys), "topk": sum(tk.values()), "mean_p": mp, "rate": my, "ece": ece,
            "_ll": ll, "_br": br, "_tk": tk}


def recal_logloss(ps, ys):
    """確かめの行の上で [1, logit(p)] にロジスティック回帰し直した（リッジ 1）対数損失の平均（識別だけで決まる部分の目安）。"""
    cols = [array.array("d", [1.0] * len(ps)), array.array("d", [logit(p) for p in ps])]
    fit = em.fit_logistic_cols(cols, list(ys), em.FIXED_LAMBDA)
    q = em.predict_cols(cols, fit["coef"])
    ll = es.log_loss_terms(q, ys)
    return sum(ll) / len(ll), fit["converged"]


def _recal_task(args):
    key, ps, ys = args
    v, conv = recal_logloss(ps, ys)
    return key, v, conv


def window_sim(a, b, weeks, wsize, stride=SIM_STRIDE):
    """確かめの週の中で wsize 週の窓を stride 週ずつずらし、窓ごとの対数損失の差（a − b）と4週束ねの範囲。
    戻り値：[(窓の最初の週, 差, 下端, 上端, 束の数)]。"""
    by_w = {}
    for x, xr, w in zip(a["_ll"], b["_ll"], weeks):
        s = by_w.setdefault(w, [0.0, 0])
        s[0] += x - xr
        s[1] += 1
    wk = sorted(by_w)
    out = []
    for st in range(0, len(wk) - wsize + 1, stride):
        win = wk[st:st + wsize]
        blks = es.blocks_of(win, es.BLOCK_WEEKS)
        vals = [(sum(by_w[w][0] for w in bl), sum(by_w[w][1] for w in bl)) for bl in blks]
        tot = sum(v[0] for v in vals) / sum(v[1] for v in vals)
        lo, hi = es.bootstrap_diff(vals)
        out.append((win[0], tot, lo, hi, len(blks)))
    return out


def diff_metrics(a, b, weeks):
    """モデル a と基準 b の差（a − b）と、4週束ねのブートストラップの範囲。"""
    wk_sorted = sorted(set(weeks))
    blks = es.blocks_of(wk_sorted, es.BLOCK_WEEKS)
    out = {}
    for key in ("_ll", "_br"):
        by_w = {}
        for x, xr, w in zip(a[key], b[key], weeks):
            s = by_w.setdefault(w, [0.0, 0])
            s[0] += x - xr
            s[1] += 1
        vals = [(sum(by_w.get(w, [0.0, 0])[0] for w in bl), sum(by_w.get(w, [0.0, 0])[1] for w in bl)) for bl in blks]
        out["d" + key] = (sum(a[key]) - sum(b[key])) / len(a[key])
        out["ci" + key] = es.bootstrap_diff(vals)
    tvals = [(sum(a["_tk"].get(w, 0) - b["_tk"].get(w, 0) for w in bl), len(bl)) for bl in blks]
    lo, hi = es.bootstrap_diff(tvals)
    out["d_tk"] = a["topk"] - b["topk"]
    out["ci_tk"] = (lo * len(wk_sorted), hi * len(wk_sorted))
    return out


# ---------------------------------------------------------------------------
# 網の手がかり（子プロセス）
# ---------------------------------------------------------------------------

_W = {}


def _init_graph(t117_cache, small, dur, targets_by_week, fam, mondays, rises):
    _W.update(cache_dir=t117_cache, meta=small, dur=dur, targets=targets_by_week, fam=fam, mondays=mondays, rises=rises)


def hop_rise(i, h1, h2, rises):
    """T-119 の hop_signals と同じ値（1歩・2歩の隣の上がりの重み付き平均。値が無ければ None）。"""
    return (es.weighted_mean([(w, rises[j]) for j, w in h1[i]]), es.weighted_mean([(w, rises[k]) for k, w in h2[i]]))


def month_nbwave(mk, h1, h2, targets, mondays, rises):
    out = {}
    for ti, t in enumerate(mondays):
        if es.month_key(t) != mk:
            continue
        r = rises[ti]
        for i in targets.get(ti, ()):
            a, b = hop_rise(i, h1, h2, r)
            out[(ti, i)] = (0.0 if a is None else a, 1.0 if a is None else 0.0, 0.0 if b is None else b,
                            1.0 if b is None else 0.0)
    return out


def _graph_task(mk):
    meta = _W["meta"]
    n = len(meta["tags"])
    months, nb, lab = ch.graph_of_month(_W["cache_dir"], meta, mk)
    h1, h2 = ch.hop_lists(nb, n)
    exc = ch.month_features(mk, h1, h2, lab, _W["dur"], _W["targets"], _W["fam"], _W["mondays"], n)
    vi = ch.variants().index(CHAIN_VARIANT)
    exc = {k: tuple(v[4 * vi:4 * vi + 4]) for k, v in exc.items()}
    nbw = month_nbwave(mk, h1, h2, _W["targets"], _W["mondays"], _W["rises"])
    return mk, months, exc, nbw


# ---------------------------------------------------------------------------
# 当てはめ（子プロセス）
# ---------------------------------------------------------------------------

def _init_fit(tables, split_idx):
    _W.update(tables=tables, split_idx=split_idx)


def fit_predict(tb, m, cols, tri, tei):
    tr = sorted(tri, key=lambda r: (tb["t"][r], tb["tag"][r]))
    y = [tb["y%d" % m][r] for r in tr]
    fit = em.fit_logistic_cols([em.column_values(tb, c, tr) for c in cols], y, em.FIXED_LAMBDA)
    return fit, em.predict_cols([em.column_values(tb, c, tei) for c in cols], fit["coef"])


def model_cols(m, kind, extra):
    if kind == "logit_only":
        return [em.naive_col(m, "intercept")] + list(extra)
    return ed.naive_cols(m) + list(extra)


def _fit_task(args):
    sp, m, name, cols = args
    tb = _W["tables"][m]
    tri, tei = _W["split_idx"][sp]
    fit, probs = fit_predict(tb, m, cols, tri, tei)
    return sp, m, name, list(fit["coef"]), fit["converged"], array.array("d", probs)


# ---------------------------------------------------------------------------
# 本体
# ---------------------------------------------------------------------------

def run(root, t117_cache, out_dir, workers, log):
    es.check_free(os.path.dirname(os.path.abspath(out_dir)))
    ctx = ei.load_context(root)
    m117 = es.load_cache(t117_cache, ctx)
    tags, v = ctx["tags"], ctx["v"]
    n = len(tags)
    days = ctx["days"]
    mondays = ei.prediction_mondays()
    W = len(mondays)
    series = es.daily_series(m117)
    del m117["weekc"]
    results = [None] * n
    lo = hi = None
    with es._pool(workers, es._init_eval, (days, mondays, v)) as pool:
        for k, (j, res, a, b) in enumerate(pool.imap(es._eval_task, list(enumerate(series)), chunksize=8), 1):
            results[j] = res
            if a is not None:
                lo = a if lo is None or a < lo else lo
                hi = b if hi is None or b > hi else hi
            if k % 1000 == 0:
                log("タグ %d / %d" % (k, n))
    del series
    rows = {}
    for i, res in enumerate(results):
        for ti, (st, _b, _c, _m1, _m2, js, lv) in enumerate(res):
            if st == "target" and not any(x is None for x in js):
                rows[(ti, i)] = (js, lv)
    keys = sorted(rows)
    log("対象の行 %d" % len(rows))
    dur = [ch.durations([ch.is_high(b, c, v) for (_st, b, c, _m1, _m2, _js, _lv) in results[j]]) for j in range(n)]
    rises = [[es.rise(results[j][ti][2], results[j][ti][1], v)
              if (results[j][ti][1] is not None and results[j][ti][2] is not None) else None for j in range(n)]
             for ti in range(W)]
    del results
    missing = set(m117["missing"])
    month_v1, month_docs = {}, {}
    for di, d in enumerate(m117["days"]):
        if d in missing:
            continue
        mk = es.month_key(datetime.date.fromisoformat(d))
        mv = month_v1.setdefault(mk, [0] * n)
        for i in range(n):
            mv[i] += m117["v1"][di * n + i]
        month_docs[mk] = month_docs.get(mk, 0) + m117["docs"][di]
    small = {"tags": tags, "pair_files": m117["pair_files"], "month_v1": month_v1, "month_docs": month_docs}
    del m117
    fam_names = sea.family_seas(tags)
    fam_pred = [-1 if f == "その他" else k for f, k in zip(fam_names, ch.index_of(fam_names))]
    targets_by_week = collections.defaultdict(list)
    for (ti, i) in keys:
        targets_by_week[ti].append(i)
    pred_months = sorted({es.month_key(t) for t in mondays})
    net_off = None
    for t in mondays:
        off = es.check_network_before(t, es.network_months(t, ch.GRAPH_WINDOW, "M"))
        net_off = off if net_off is None else max(net_off, off)
    exc, nbw = {}, {}
    with es._pool(workers, _init_graph, (t117_cache, small, dur, dict(targets_by_week), fam_pred, mondays,
                                         rises)) as pool:
        for k, (mk, months, e1, e2) in enumerate(pool.imap(_graph_task, pred_months), 1):
            if months != es.network_months(es.month_first(mk), ch.GRAPH_WINDOW, "M"):
                raise TierError("網の月が違う")
            for ti, t in enumerate(mondays):
                if es.month_key(t) == mk:
                    es.check_network_before(t, months)
            exc.update(e1)
            nbw.update(e2)
            log("網 %d / %d（%d）" % (k, len(pred_months), mk))
    if sorted(exc) != keys or sorted(nbw) != keys:
        raise TierError("網の手がかりの行が対象の行と合わない")
    info = {"daily_min_read": lo.isoformat(), "daily_max_read": hi.isoformat(),
            "network_last_day_minus_t_max_days": net_off}
    files = evaluate_and_build(tags, mondays, rows, keys, exc, nbw, ctx, info, workers, log)
    return write_outputs(out_dir, files)


def build_tables(tags, mondays, rows, keys, exc, nbw, v):
    """倍率ごとの表（段3・段4・入れ子の列）と、段1・段2 の確率。"""
    n = len(tags)
    W = len(mondays)
    by_week = collections.defaultdict(list)
    for (ti, i) in keys:
        by_week[ti].append((i, rows[(ti, i)][0]))
    tables, direct = {}, {}
    for mi, m in enumerate(MULTIPLIERS):
        counts = hist_counts(by_week, n, W, mi)
        tb = ed.make_table(rows, keys, mondays, tags, m, v)
        for j, c in enumerate(NBWAVE_COLUMNS):
            tb[c] = array.array("d", [nbw[k][j] for k in keys])
        for j, c in enumerate(CHAIN_COLUMNS):
            tb[c] = array.array("d", [exc[k][j] for k in keys])
        d = {"null_exp": array.array("d", [null_exp(k[0], counts[2], counts[3]) for k in keys])}
        for h, w, a in hist_forms():
            d[h] = array.array("d", [hist_prob(k[0], k[1], w, a, counts) for k in keys])
            tb["lh_" + h] = array.array("d", [logit(p) for p in d[h]])
        tables[m], direct[m] = tb, d
    return tables, direct


def evaluate_and_build(tags, mondays, rows, keys, exc, nbw, ctx, info, workers, log):
    tables, direct = build_tables(tags, mondays, rows, keys, exc, nbw, ctx["v"])
    log("表を作った")
    idx = {k: r for r, k in enumerate(keys)}
    split_idx = {}
    for sp in SPLITS:
        tr, te = ed.split_rows(keys, mondays, sp)
        split_idx[sp] = ([idx[k] for k in tr], [idx[k] for k in te])
    tasks = [(sp, m, name, model_cols(m, kind, extra)) for sp in SPLITS for m in MULTIPLIERS
             for name, _tier, kind, extra in model_list() if kind in ("logit", "logit_only")]
    probs, coefs = {}, []
    with es._pool(workers, _init_fit, (tables, split_idx)) as pool:
        for k, (sp, m, name, coef, conv, p) in enumerate(pool.imap(_fit_task, tasks), 1):
            probs[(sp, m, name)] = p
            coefs.append((sp, m, name, coef, conv))
            if k % 20 == 0:
                log("当てはめ %d / %d" % (k, len(tasks)))
    for sp in SPLITS:
        tri, tei = split_idx[sp]
        for m in MULTIPLIERS:
            y = tables[m]["y%d" % m]
            base = sum(y[r] for r in tri) / len(tri)
            probs[(sp, m, "null_fix")] = array.array("d", [base] * len(tei))
            for name in ["null_exp"] + [h for h, _w, _a in hist_forms()]:
                probs[(sp, m, name)] = array.array("d", [direct[m][name][r] for r in tei])
    rtasks = []
    for sp in SPLITS:
        _tri, tei = split_idx[sp]
        for m in MULTIPLIERS:
            ys = array.array("b", [tables[m]["y%d" % m][r] for r in tei])
            for name, _t, _k, _e in model_list():
                rtasks.append(((sp, m, name), probs[(sp, m, name)], ys))
    recal = {}
    with es._pool(workers, _init_fit, ({}, {})) as pool:
        for k, (key, v, conv) in enumerate(pool.imap(_recal_task, rtasks), 1):
            recal[key] = (v, conv)
            if k % 50 == 0:
                log("較正し直し %d / %d" % (k, len(rtasks)))
    res, sim = {}, []
    for sp in SPLITS:
        _tri, tei = split_idx[sp]
        for m in MULTIPLIERS:
            tb = tables[m]
            ys = [tb["y%d" % m][r] for r in tei]
            wk = [tb["week"][r] for r in tei]
            tg = [tb["tag"][r] for r in tei]
            mets = {}
            for name, _t, _k, _e in model_list():
                x = metrics(probs[(sp, m, name)], ys, wk, tg)
                x["ll_recal"], x["recal_converged"] = recal[(sp, m, name)]
                x["cal_loss"] = x["logloss"] - x["ll_recal"]
                mets[name] = x
            diffs = [(lab, a, b, diff_metrics(mets[a], mets[b], wk)) for lab, a, b in diff_pairs()]
            res[(sp, m)] = (mets, diffs)
            for lab, a, b in diff_pairs():
                if lab == "N4-N3":
                    continue
                for ws in SIM_WINDOWS:
                    sim.append((sp, m, lab, a, b, ws, window_sim(mets[a], mets[b], wk, ws)))
        log("指標 %s" % sp)
    return build_outputs(tags, mondays, keys, tables, res, coefs, ctx, info, sim)


# ---------------------------------------------------------------------------
# 出力
# ---------------------------------------------------------------------------

OUT_NAMES = ("tiers.tsv", "diffs.tsv", "coefs.tsv", "power.tsv", "run.json", "summary.md")
f6 = es.f6


def own_code_shas():
    code = dict(ch.own_code_shas())
    with open(os.path.abspath(__file__), "rb") as f:
        code["src/stats/explore_tiers.py"] = hashlib.sha256(f.read()).hexdigest()
    return code


def sim_rows(sim):
    out = []
    for sp, m, lab, a, b, ws, wins in sim:
        if not wins:
            out.append((sp, m, HORIZON, lab, a, b, ws, 0, "-", "-", "-", "-", "-", "-"))
            continue
        ds = sorted(w[1] for w in wins)
        out.append((sp, m, HORIZON, lab, a, b, ws, len(wins), wins[0][4],
                    "%.4f" % (sum(1 for w in wins if w[3] < 0) / len(wins)),
                    "%.4f" % (sum(1 for w in wins if w[2] > 0) / len(wins)),
                    f6(sea.median(ds)), f6(ds[0]), f6(ds[-1])))
    return out


def build_outputs(tags, mondays, keys, tables, res, coefs, ctx, info, sim):
    tier_of = {name: tier for name, tier, _k, _e in model_list()}
    trows, drows = [], []
    for sp in SPLITS:
        for m in MULTIPLIERS:
            mets, diffs = res[(sp, m)]
            for name, tier, _k, _e in model_list():
                x = mets[name]
                trows.append((sp, m, HORIZON, tier, name, x["n"], x["pos"], f6(x["logloss"]), f6(x["brier"]),
                              f6(x["auc"]), x["topk"], f6(x["mean_p"]), f6(x["rate"]), f6(x["ece"]),
                              f6(x["ll_recal"]), f6(x["cal_loss"]), x["recal_converged"]))
            for lab, a, b, d in diffs:
                drows.append((sp, m, HORIZON, lab, a, b, f6(d["d_ll"]), f6(d["ci_ll"][0]), f6(d["ci_ll"][1]),
                              f6(100 * d["d_ll"] / mets[b]["logloss"]), f6(d["d_br"]), f6(d["ci_br"][0]),
                              f6(d["ci_br"][1]), d["d_tk"], "%.1f" % d["ci_tk"][0], "%.1f" % d["ci_tk"][1],
                              f6(mets[a]["ll_recal"] - mets[b]["ll_recal"]), f6(mets[a]["cal_loss"] - mets[b]["cal_loss"])))
    tiers_tsv = ei.tsv(("split", "multiplier", "horizon_days", "tier", "model", "n_test", "islands_test", "logloss",
                        "brier", "auc", "top10_hits", "mean_prob", "island_rate", "ece10", "logloss_recal", "cal_loss",
                        "recal_converged"), trows)
    diffs_tsv = ei.tsv(("split", "multiplier", "horizon_days", "step", "model", "reference", "d_logloss",
                        "d_ll_ci4w_lo", "d_ll_ci4w_hi", "d_logloss_pct", "d_brier", "d_br_ci4w_lo", "d_br_ci4w_hi",
                        "d_top10", "d_top10_ci4w_lo", "d_top10_ci4w_hi", "d_logloss_recal", "d_cal_loss"), drows)
    power_tsv = ei.tsv(("split", "multiplier", "horizon_days", "step", "model", "reference", "window_weeks", "windows",
                        "blocks_per_window", "share_upper_below0", "share_lower_above0", "median_d_logloss",
                        "min_d_logloss", "max_d_logloss"), sim_rows(sim))
    colnames = {name: (["intercept"] if kind == "logit_only" else list(naive.FEATURES)) + list(extra)
                for name, _t, kind, extra in model_list() if kind in ("logit", "logit_only")}
    coefs_tsv = ei.tsv(("split", "multiplier", "model", "converged", "column", "coef"),
                       [(sp, m, name, conv, c, f6(b)) for sp, m, name, cf, conv in coefs
                        for c, b in zip(colnames[name], cf)])
    run = {"label": LABEL, "code": own_code_shas(), "python": sys.version.split()[0], "refs": ctx["refs"],
           "v": "%d/%d" % (ctx["v"].numerator, ctx["v"].denominator), "rows": len(keys), "tags": len(tags),
           "options": {"known_lag_weeks": KNOWN_LAG_WEEKS, "hist_windows": HIST_WINDOWS, "hist_a": HIST_A,
                       "null_forms": NULL_FORMS, "chain_variant": CHAIN_VARIANT, "tier4_forms": TIER4_FORMS,
                       "cal_bins": CAL_BINS, "splits": SPLITS, "split_main": SPLIT_MAIN, "main_multiplier": MAIN_M,
                       "block_weeks": es.BLOCK_WEEKS, "boot_n": es.BOOT_N, "boot_seed": es.BOOT_SEED,
                       "sim_windows": SIM_WINDOWS, "sim_stride": SIM_STRIDE, "min_blocks": MIN_BLOCKS},
           "info": info, "models": [name for name, _t, _k, _e in model_list()],
           "not_converged": sorted({"%s/%d/%s" % (sp, m, name) for sp, m, name, _cf, conv in coefs if not conv}),
           "citation": [ei.CITATION_EN, ei.CITATION_JA]}
    files = {"tiers.tsv": tiers_tsv, "diffs.tsv": diffs_tsv, "coefs.tsv": coefs_tsv, "power.tsv": power_tsv,
             "run.json": (json.dumps(run, ensure_ascii=False, sort_keys=True, indent=1) + "\n").encode("utf-8")}
    files["summary.md"] = summary_md(run, res, tier_of, tags, sim, coefs)
    for name, data in files.items():
        ei.check_public(name, data)
    return files


def write_outputs(out_dir, files):
    if sorted(files) != sorted(OUT_NAMES):
        raise TierError("出力の名前が決めた一覧と違う")
    os.makedirs(out_dir, exist_ok=True)
    for name in OUT_NAMES:
        if os.path.lexists(os.path.join(out_dir, name)):
            raise TierError("書き出す先に同じ名前のファイル（%s）がある。上書きしない" % name)
    return {name: es.write_new(os.path.join(out_dir, name), files[name]) for name in OUT_NAMES}


# ---------------------------------------------------------------------------
# 要約
# ---------------------------------------------------------------------------

STEP_JA = {"2-1": "段2 − 段1（タグごとの過去の割合の上乗せ）", "3-1": "段3 − 段1（素朴な予測の、全体の割合からの上乗せ）",
           "3-2": "段3 − 段2（素朴な予測の、タグごとの過去の割合からの上乗せ）",
           "4-3": "段4 − 段3（網・波の手がかりの上乗せ）", "4-1": "段4 − 段1",
           "N3-2": "入れ子：段3＋段2 − 段2", "N4-N3": "入れ子：段4＋段2 − 段3＋段2",
           "2c-1": "較正した段2 − 段1", "3-2c": "段3 − 較正した段2", "N3-2c": "入れ子：段3＋段2 − 較正した段2"}
NULL_TOPK_STEPS = ("2-1", "2c-1", "3-1", "4-1")


def sim_share(sim, sp, m, lab, ws):
    """組 lab の窓 ws 週の、範囲の上端が0より下の窓の割合の (最小, 最大, 窓の数, 束の数)。"""
    xs = [(sum(1 for w in wins if w[3] < 0) / len(wins), len(wins), wins[0][4])
          for s2, m2, l2, _a, _b, w2, wins in sim if s2 == sp and m2 == m and l2 == lab and w2 == ws and wins]
    if not xs:
        return None
    return min(x[0] for x in xs), max(x[0] for x in xs), xs[0][1], xs[0][2]


def step_text(diffs, mets, lab):
    ds = [(a, b, d) for l2, a, b, d in diffs if l2 == lab]
    pct = [100 * d["d_ll"] / mets[b]["logloss"] for a, b, d in ds]
    below = sum(1 for _a, _b, d in ds if d["ci_ll"][1] < 0)
    above = sum(1 for _a, _b, d in ds if d["ci_ll"][0] > 0)
    tk = [d["d_tk"] for _a, _b, d in ds]
    bb = sum(1 for _a, _b, d in ds if d["ci_br"][1] < 0)
    ba = sum(1 for _a, _b, d in ds if d["ci_br"][0] > 0)
    return ("%d 組。対数損失の差 %+.2f%%〜%+.2f%%。差の範囲（4週束ね）が0より下に収まった組 %d、0より上 %d。ブライアの差の範囲が"
            "0より下 %d、0より上 %d。上位10の島の差 %+d〜%+d"
            % (len(ds), min(pct), max(pct), below, above, bb, ba, min(tk), max(tk)))


def summary_md(run, res, tier_of, tags, sim, coefs=()):
    L = []
    a = L.append
    md = ei.md_table
    a("# 4段の比べ（T-134、手法を作る期間）")
    a("")
    a("この文書は `src/stats/explore_tiers.py` が出力したもので、手で書き足していない。島の定義は変えていない。テーマの名前は載せていない。"
      "探索で、封印していない。全部並べ、選ばない・勧めない。")
    a("この版（v2）の変更点：段2 を学習の行で較正した形（hcal）と、その上乗せ（2c−1・3−2c・N3−2c）を足した。対数損失を、確かめの行で"
      "較正し直した対数損失（識別の目安）と較正の損に分けた列を足した。窓をずらした検出力の見当（power.tsv）を足した。1章に、静的な違い・"
      "段1 基準の上位10・段4 の上位10の減り・較正の注意を書いた。v1 の coefs.tsv は、列の名前が1つずれていた（切片の名前が2回入り、"
      "最後の列の値が落ちていた）ので直した。v1 のほかの表の数（tiers.tsv・diffs.tsv の v1 にあった列）は同じ作り方。")
    a("この版（v3）の変更点：要約の文だけを直した（T-136）。較正し直した対数損失の歪み、束の下限を満たす窓の数、較正した段2 の傾きと、"
      "段2 より悪い理由の見立てを1章に書いた。表の sha256 は v2 と同じ。")
    a("")
    a("## 1. やさしい説明")
    a("")
    a("4つの段の予測を、同じ対象の行に付けて比べた。段1 はすべてのタグに同じ確率、段2 はタグごとの過去の島の割合、段3 は今の素朴な予測"
      "（直近の水準・季節・前年の同じ時期）、段4 は段3 に網や波の手がかりを足したもの。数字は、確かめの期間の対数損失（小さいほど良い）の、"
      "基準の段に対する差の割合。差の範囲は、4週ずつ束ねて選び直した 95%% の範囲。段1・段2 には形が %d・%d 通り、段4 には %d 通りあり、"
      "組ごとに並べた。" % (len(NULL_FORMS), len(hist_forms()), len(TIER4_FORMS)))
    a("")
    for sp in SPLITS:
        a("- 分け方 %s（%s）：" % (sp, "主。学習 〜2017-12-04、確かめ 2018-01-08〜2018-12-03" if sp == SPLIT_MAIN
                                  else "参考。学習 〜2018-12-03、検証 2019-01-07〜2020-09-14"))
        for m in MULTIPLIERS:
            mets, diffs = res[(sp, m)]
            a("  - 倍率 %d（確かめの行 %d、島 %d、島の割合 %.4f）：" % (m, mets["naive"]["n"], mets["naive"]["pos"],
                                                          mets["naive"]["rate"]))
            for lab in ("2-1", "2c-1", "3-1", "3-2", "3-2c", "4-3"):
                a("    - %s：%s。" % (STEP_JA[lab], step_text(diffs, mets, lab)))
    a("")
    mets_b, diffs_b = res[(SPLIT_MAIN, MAIN_M)]
    d31 = [d for lab, x, y, d in diffs_b if lab == "3-1" and y == "null_exp"][0]
    a("- 読み方の注意（静的な違い）：段3 − 段1（分け方 %s・倍率 %d で %+.1f%%）には、タグの普段の大きさ（段3 の size）という、"
      "予言日によらない静的な違いが入る。静的な違いを差し引いた比べは、段2 を基準にした 3−2・3−2c と、入れ子の N3−2・N3−2c。"
      % (SPLIT_MAIN, MAIN_M, 100 * d31["d_ll"] / mets_b["null_exp"]["logloss"]))
    a("- 読み方の注意（上位10）：段1 はすべてのタグに同じ確率なので、段1 の上位10の島は名前の順で決まる。段1 を基準にした上位10の島の差"
      "（%s）は意味を持たない。" % "・".join(NULL_TOPK_STEPS))
    lows = []
    for sp in SPLITS:
        for m in MULTIPLIERS:
            for lab, x, y, d in res[(sp, m)][1]:
                if lab == "4-3" and d["ci_tk"][1] < 0:
                    lows.append("分け方 %s・倍率 %d の %s（%+d、範囲 %.1f〜%.1f）" % (sp, m, x, d["d_tk"], d["ci_tk"][0], d["ci_tk"][1]))
    a("- 段4 で上位10の島が減り、差の範囲が0より下に収まった形：%s。対数損失が下がっても、上位10の島は減ることがある。" % (
        "、".join(lows) if lows else "無い"))
    eh = [mets_b[h]["ece"] for h, _w, _a in hist_forms()]
    ec = [mets_b["hcal_" + h]["ece"] for h, _w, _a in hist_forms()]
    clh = [mets_b[h]["cal_loss"] for h, _w, _a in hist_forms()]
    clc = [mets_b["hcal_" + h]["cal_loss"] for h, _w, _a in hist_forms()]
    a("- 較正：段2 は縮めた割合をそのまま確率にしたので、較正がずれうる。分け方 %s・倍率 %d で、段2 の ECE は %.4f〜%.4f、学習の行で"
      "較正した段2（hcal）は %.4f〜%.4f、段3 は %.4f。較正の損（対数損失 − 較正し直した対数損失）は、段2 で %.5f〜%.5f、hcal で "
      "%.5f〜%.5f、段3 で %.5f。2−1・3−2・N3−2 の差には、この較正の違いが混ざる。識別だけの目安は、diffs.tsv の d_logloss_recal。"
      % (SPLIT_MAIN, MAIN_M, min(eh), max(eh), min(ec), max(ec), mets_b["naive"]["ece"], min(clh), max(clh), min(clc),
         max(clc), mets_b["naive"]["cal_loss"]))
    gaps = sorted(((mets_b["hcal_" + h]["ll_recal"] - mets_b[h]["ll_recal"], h) for h, _w, _a in hist_forms()),
                  reverse=True)
    g, gh = gaps[0]
    a("- 較正し直した対数損失の歪み：較正し直しにもリッジ 1（切片を含む）を掛けたので、確率の幅が狭い形では大きく歪む。較正した段2 は"
      "段2 の単調な変換で、並べ方は同じ（AUC は分け方 %s・倍率 %d で %s）なのに、較正し直した対数損失は違った。差が最大の形（%s）で、"
      "段2 %.5f、較正した段2 %.5f、差 %.4f（段1 と段2 の、較正し直した対数損失の差 %.4f と同じくらいの大きさ）。識別は、当面 AUC を主に読む。"
      % (SPLIT_MAIN, MAIN_M, "・".join("%.3f" % mets_b[h]["auc"] for h, _w, _a in hist_forms()), gh, mets_b[gh]["ll_recal"],
         mets_b["hcal_" + gh]["ll_recal"], g, mets_b["null_exp"]["ll_recal"] - mets_b[gh]["ll_recal"]))
    slopes = {name: dict(zip(["intercept", "lh"], cf)) for sp, m, name, cf, _c in coefs
              if sp == SPLIT_MAIN and m == MAIN_M and name.startswith("hcal_")}
    if slopes:
        sl = sorted(v["lh"] for v in slopes.values())
        a("- 較正した段2 の傾き（logit(段2) の係数、分け方 %s・倍率 %d）は %.2f〜%.2f（全期間・a = 50 で %.3f）。1 より小さいので、確率の"
          "幅が段2 より狭い。較正した段2 の対数損失が段2 より大きい形が多いのは、学習の行の多くが、使える過去が短い時期（2016〜2017年）の"
          "行で、そこで当てはめた傾きが、過去が長くなった確かめの時期に合わないためと見られる（見立てで、確かめていない）。"
          % (SPLIT_MAIN, MAIN_M, sl[0], sl[-1], slopes.get("hcal_hist_all_a50", {}).get("lh", float("nan"))))
    for sp in SPLITS:
        ok = sorted({(w2, wins[0][4]) for s2, _m, _l, _a, _b, w2, wins in sim if s2 == sp and wins and wins[0][4] >= MIN_BLOCKS})
        a("- 束の下限 %d を満たす窓（分け方 %s）：%s。" % (MIN_BLOCKS, sp, "、".join("%d週の窓（束 %d）" % x for x in ok) if ok
                                                    else "1つも無い（確かめの週が足りない）"))
    for sp in SPLITS:
        parts = []
        for lab in ("3-1", "2-1", "2c-1", "3-2", "4-3"):
            for ws in SIM_WINDOWS:
                x = sim_share(sim, sp, MAIN_M, lab, ws)
                if x is not None:
                    parts.append("%s・%d週 %.0f〜%.0f%%（窓 %d、束 %d）" % (lab, ws, 100 * x[0], 100 * x[1], x[2], x[3]))
        a("- 窓をずらした見当（分け方 %s・倍率 %d）：窓の中の4週束ねの範囲が0より下に収まった窓の割合（形による幅）。%s。"
          "束が %d 未満の窓の範囲は狭く出がちで、判定には使えない目安。" % (sp, MAIN_M, "、".join(parts) if parts else "窓が無い",
                                                    MIN_BLOCKS))
    a("- 2020年の連鎖（T-127）は、分け方 A の検証の期間の中にしかない。主の分け方 B の確かめ（2018年）には入っていない。")
    a("- 段4 の3つの形は、T-117〜T-127 の結果（同じ期間・同じ分け方）を見たあとで選んだ。段4 の上乗せは、選んだことで大きめに出うる。")
    a("- 段1 の null_exp と段2 は、予言日ごとに、判定期間がその前に終わった行の判定だけで作った。段1 の null_fix と段3・段4 の係数は、"
      "学習の行だけで当てはめた。")
    a("")
    a("## 2. 作り方")
    a("- 予言日・対象・判定は T-115 と同じ（C7、V = %s、一度跳ねたタグの扱いあり、判定期間 %d 日、倍率 %s）。対象の行 %d、タグ %d。" % (
        run["v"], HORIZON, "・".join(str(m) for m in MULTIPLIERS), run["rows"], run["tags"]))
    a("- 判定が確定した行：予言日 s の判定期間 s+1〜s+%d が t-1 までに終わったもの（週の番号で t の %d 週以上前）。" % (
        HORIZON, KNOWN_LAG_WEEKS))
    a("- 段1：null_exp は確定した行すべての (島 + 1) / (行 + 2)。null_fix は分け方の学習の行の島の割合（定数）。")
    a("- 段2：(そのタグの確定した行の島 + a × null_exp) / (そのタグの確定した行 + a)。過去の長さは %s（52 は直近52週）、a = %s。" % (
        "・".join(str(w) for w in HIST_WINDOWS), "・".join(str(x) for x in HIST_A)))
    a("- 段3：naive.py の7つの特徴量、ロジスティック回帰、リッジ 1。段4：段3 に、nbwave（網の1歩・2歩の隣の上がり。T-119 と同じ）、"
      "chain（連鎖の励起。T-127 の D = %d、λ = %g）、その両方を足したもの。" % CHAIN_VARIANT)
    a("- 入れ子の並び（参考）：N3 は段3 の特徴量に logit(段2 の確率) を足したもの、N4 はそれに段4 の列を足したもの。段2 と段3 は"
      "入れ子でないので、3 − 2 と、N3 − 2（段2 の情報を持ったうえでの素朴な予測の上乗せ）を並べた。")
    a("- 較正した段2（hcal）：切片と logit(段2 の確率) だけのロジスティック回帰（リッジ 1）を、分け方の学習の行で当てはめた。")
    a("- 識別と較正の分け方：確かめの行の上で、確率を [1, logit(p)] にロジスティック回帰し直した（リッジ 1）対数損失を「較正し直した"
      "対数損失」（識別だけで決まる部分の目安）、もとの対数損失との差を「較正の損」とした。確かめの行で当てはめるので、前向きの予言には"
      "使えない目安。")
    a("- 窓をずらした見当：確かめの週の中で %s 週の窓を %d 週ずつずらし、窓ごとに4週束ねの範囲を作った（同じブートストラップ）。"
      "束の数の下限の目安は %d。" % ("・".join(str(w) for w in SIM_WINDOWS), SIM_STRIDE, MIN_BLOCKS))
    a("- 指標：対数損失、ブライア、AUC、上位10の島（週ごと、同じ確率なら名前の順）、較正（確率の平均・島の割合・%d 区分の ECE）。"
      "差の範囲は %d 週ずつ束ねて %d 回選び直した（乱数の種 %d）。" % (CAL_BINS, es.BLOCK_WEEKS, es.BOOT_N, es.BOOT_SEED))
    a("")
    for sp in SPLITS:
        for m in MULTIPLIERS:
            mets, diffs = res[(sp, m)]
            a("## 3. 各段の値（分け方 %s%s、倍率 %d）" % (sp, "、主" if sp == SPLIT_MAIN else "、参考", m))
            a("")
            a(md(["段", "モデル", "対数損失", "較正し直した対数損失", "較正の損", "ブライア", "AUC", "上位10の島", "確率の平均",
                  "島の割合", "ECE"],
                 [(tier_of[name], name, f6(x["logloss"]), f6(x["ll_recal"]), f6(x["cal_loss"]), f6(x["brier"]),
                   f6(x["auc"]), x["topk"], f6(x["mean_p"]), f6(x["rate"]), f6(x["ece"])) for name, x in mets.items()
                  if not name.startswith("N4_")]))
            a("")
            a("N4 の %d のモデルの値は tiers.tsv。" % sum(1 for name in mets if name.startswith("N4_")))
            a("")
            a(md(["上乗せ", "モデル", "基準", "対数損失の差（割合）", "差の範囲（4週束ね）", "較正し直した差", "較正の損の差",
                  "ブライアの差", "差の範囲（4週束ね）", "上位10の差", "差の範囲（4週束ね）"],
                 [(lab, ma, mb, "%s（%+.2f%%）" % (f6(d["d_ll"]), 100 * d["d_ll"] / mets[mb]["logloss"]),
                   "%s〜%s" % (f6(d["ci_ll"][0]), f6(d["ci_ll"][1])),
                   f6(mets[ma]["ll_recal"] - mets[mb]["ll_recal"]), f6(mets[ma]["cal_loss"] - mets[mb]["cal_loss"]),
                   f6(d["d_br"]), "%s〜%s" % (f6(d["ci_br"][0]), f6(d["ci_br"][1])),
                   d["d_tk"] if lab not in NULL_TOPK_STEPS else "%d（意味なし）" % d["d_tk"],
                   "%.1f〜%.1f" % d["ci_tk"]) for lab, ma, mb, d in diffs if lab != "N4-N3"]))
            a("")
            a("N4 − N3 の %d 組は diffs.tsv。" % sum(1 for lab, _a, _b, _d in diffs if lab == "N4-N3"))
            a("")
    a("## 3b. 窓をずらした見当（倍率 %d）" % MAIN_M)
    a("")
    a(md(["分け方", "上乗せ", "モデル", "基準", "窓（週）", "窓の数", "束の数", "範囲が0より下の窓", "範囲が0より上の窓",
          "差の中央値", "差の最小", "差の最大"],
         [(r[0], r[3], r[4], r[5], r[6], r[7], r[8], r[9], r[10], r[11], r[12], r[13]) for r in sim_rows(sim)
          if r[1] == MAIN_M]))
    a("")
    a("倍率 2・8 は power.tsv。束が %d 未満の窓の範囲は判定に使えない目安。" % MIN_BLOCKS)
    a("")
    a("## 4. 予言の時点のデータだけを使ったことの確かめ")
    a("- 日の比率：ReadGuard で、入力は t-399〜t-1、判定は t+1〜t+28 の外を読むと止まる。読んだ日の範囲は %s〜%s。" % (
        run["info"]["daily_min_read"], run["info"]["daily_max_read"]))
    a("- 網：予言日ごとに網の最後の日 < 予言日を確かめた（最後の日 − 予言日の最大 %d 日）。" % run["info"][
        "network_last_day_minus_t_max_days"])
    a("- 段1・段2：予言日 t には、判定期間が t より前に終わった行の判定だけを使った（週の番号で t の %d 週以上前）。" % KNOWN_LAG_WEEKS)
    a("")
    a("## 5. 限界")
    a("- 比べたモデルと組は多い（モデル %d、上乗せの組 %d、倍率 3、分け方 2）。多重比較の補正をしていない。4週の束どうしは独立でない"
      "（判定期間 %d 日が隣の束に重なる）。範囲が0を含まないことは、効くことの確かめにはならない。" % (
          len(run["models"]), len(diff_pairs()), HORIZON))
    a("- 分け方 B の確かめ（2018年）と分け方 A の検証（2019〜2020年）は、T-117〜T-127 で既に何度も見た期間の再利用。")
    a("- 段1 の null_exp は確定した行が無い最初の5週で 0.5 になる（学習の行にだけ入る）。段1 の上位10の島は、同じ確率なので名前の順で決まり、"
      "意味を持たない。")
    a("- 一覧と V の先読み：タグの一覧と V は、手法を作る期間の区画全体のデータで決まった（seq 17）。")
    a("- 除外の規則の漏れ：民族・人物の姓・宗教・犯罪・紛争・政治に当たる名前のテーマが一覧に残っている（オーナーの決定 2026-10-16、(a)）。")
    a("- 判定期間は未決（案 30 日）。ここでは T-115 からの 28 日で比べた。")
    a("")
    a("## 6. 再計算")
    a("```")
    a(".venv/bin/python -B src/stats/explore_tiers.py --t117-cache <explore-t117-cache/run2> --out-dir <書き出す先>")
    a("```")
    for k in sorted(run["code"]):
        a("- %s：sha256 %s" % (k, run["code"][k]))
    a("")
    a("## 引用")
    a(ei.CITATION_EN)
    a("")
    a(ei.CITATION_JA)
    out = "\n".join(L) + "\n"
    if "**" in out:
        raise TierError("要約に太字の印がある")
    if "%%" in out:
        raise TierError("要約に書式の誤り（%%）がある")
    if sea.names_in_text(out, tags, []):
        raise TierError("要約にテーマの名前がある")
    return out.encode("utf-8")


def main(argv=None):
    p = argparse.ArgumentParser(description="T-134 4段の比べ")
    p.add_argument("--t117-cache", required=True)
    p.add_argument("--out-dir", required=True)
    p.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 1))
    a = p.parse_args(argv)
    t0 = time.time()

    def log(msg):
        sys.stderr.write("[%8.1f s] %s\n" % (time.time() - t0, msg))
        sys.stderr.flush()
    try:
        shas = run(ei.PROJECT, a.t117_cache, a.out_dir, a.workers, log)
    except (TierError, ch.ChainError, sea.SeaError, x2.Diffusion2Error, ex.DiffusionError, ed.DenomError,
            em.ModelError, es.SignalError, ei.ExploreError) as e:
        sys.stderr.write("止まった：%s\n" % e)
        return 1
    for name in OUT_NAMES:
        print("%s  %s" % (shas[name], name))
    log("終わり")
    return 0


if __name__ == "__main__":
    sys.exit(main())
