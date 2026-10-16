#!/usr/bin/env python3
"""T-118：多変量の形の探索（T-117 の続き）。

T-117 で、素朴な予測に信号を足しても改善がわずかだった。それがモデルの形のせいか、信号に情報が無いせいかを
見分ける材料を作る。T-117 と同じキャッシュ（読むだけ）・予言日・対象・判定・学習と検証の分け方・倍率 2・4・8 ×
判定期間 28 日で、次の4つを比べる。結果を並べるだけで、選ばない・勧めない。

  1. 交互作用：ロジスティック回帰に、下の INTERACTIONS・NAIVE_PAIRS の掛け合わせを足す。
  2. リッジの強さ：学習の期間の中だけで、時期で分けた検証（INNER_*）により RIDGE_LAMBDAS から選び、
     学習の期間全体で作り直して、検証の期間で測る。検証の期間は選ぶのに使わない。
  3. 柔軟なモデル：決定木を重ねる手法（GBDT。設定は GBDT に固定）。上限の目安として測る。採用はしない。
  4. テーマの系統（FAMILIES）ごとの効き方。

試す形（INTERACTIONS・NAIVE_PAIRS・RIDGE_LAMBDAS・INNER_*・GBDT・FAMILIES・信号の組）は、検証の期間の結果を
見る前にこのファイルに書き、コミットしてから本番を流す。結果のファイルに、このファイルの sha256 を入れる。

予言の時点のデータだけを使うことは、T-117 の関数（explore_signals）で守る。この探索は新しいデータを読まない。

流し方（プロジェクトのルートで。TMPDIR は scratchpad の中に）
  .venv/bin/python -B src/stats/explore_models.py --cache-dir <explore-t117-cache/run2> --out-dir <書き出す先>

Data: The GDELT Project (https://www.gdeltproject.org/). This project is not affiliated with or endorsed by the GDELT Project.
"""

import argparse
import array
import bisect
import datetime
import functools
import hashlib
import json
import math
import operator
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import explore_signals as es  # noqa: E402

ei = es.ei
naive = es.naive
candidates = es.candidates
scoring = es.scoring

LABEL = "explore-models-t118-v1"

MULTIPLIERS = es.MULTIPLIERS
HORIZON = es.HORIZON

# ---------------------------------------------------------------------------
# 試す形（検証の期間の結果を見る前に書いた）
# ---------------------------------------------------------------------------

# 信号の組。FIRST は T-117 で最初に並べた選択肢（網 NETWORKS[0]、隣 NEIGHBORS[0]）で、T-117 の結果で選んだものではない。
FIRST_VARIANT = "%s_%s" % (es.NETWORKS[0][0], es.NEIGHBORS[0][0])          # w12q_lift10
S_FIRST = ("nb_rise_" + FIRST_VARIANT, "nb_trend_" + FIRST_VARIANT, "nb_miss_" + FIRST_VARIANT,
           "lead_country_max", "lead_country_frac2", "lead_miss_country",
           "gap_" + FIRST_VARIANT, "gap_miss_" + FIRST_VARIANT,
           "expect_" + FIRST_VARIANT, "expect_miss_" + FIRST_VARIANT)
S_FIRST_VALUES = ("nb_rise_" + FIRST_VARIANT, "nb_trend_" + FIRST_VARIANT, "lead_country_max",
                  "lead_country_frac2", "gap_" + FIRST_VARIANT, "expect_" + FIRST_VARIANT)
# 交互作用：信号 × 予言の時点の静かさ（naive の recent）、信号 × タグの大きさ（naive の size）、隣の上がり × 自分の上がり
INTERACTIONS = tuple([(s, "recent") for s in S_FIRST_VALUES] + [(s, "size") for s in S_FIRST_VALUES]
                     + [("nb_rise_" + FIRST_VARIANT, "own_rise")])
# 素朴な予測の特徴量どうしの掛け合わせ（切片を除く6つの組すべて）
NAIVE_PAIRS = tuple((naive.FEATURES[a], naive.FEATURES[b])
                    for a in range(1, len(naive.FEATURES)) for b in range(a + 1, len(naive.FEATURES)))

RIDGE_LAMBDAS = (0.1, 1.0, 10.0, 100.0, 1000.0, 10000.0)
FIXED_LAMBDA = naive.RIDGE_LAMBDA                         # 1.0（T-117 と同じ）
INNER_TRAIN_LAST = datetime.date(2017, 12, 4)              # 学習の期間の中の「作る」：予言日がこれ以前
INNER_VAL_FIRST = datetime.date(2018, 1, 8)                # 学習の期間の中の「測る」：これ以降、es.TRAIN_LAST まで

GBDT = {"trees": 200, "depth": 3, "learning_rate": 0.1, "min_leaf": 200, "l2": 1.0, "bins": 32}

FAMILIES = ("TAX_FNCACT", "WB", "TAX_WORLDLANGUAGES", "other")


def family_of(tag):
    """系統：TAX_FNCACT・WB・TAX_WORLDLANGUAGES と、そのほか（other）。"""
    f = ei.family(tag)
    return f if f in FAMILIES else "other"


def all_signal_columns():
    return tuple(sorted({c for _n, cs in es.model_specs(False) for c in cs}))


# モデルの一覧：(名前, 種類, 特徴の組, 比べる相手)
#   種類 "logit"：リッジ FIXED_LAMBDA のロジスティック回帰、"ridge"：強さを学習の期間の中で選ぶ、"gbdt"：GBDT
#   特徴の組："naive"・"first"・"all"・"naive_int"・"int_first"・"int_both"
MODELS = (
    ("naive", "logit", "naive", None),
    ("lin_first", "logit", "first", "naive"),
    ("naive_int", "logit", "naive_int", "naive"),
    ("int_first", "logit", "int_first", "lin_first"),
    ("int_both", "logit", "int_both", "naive_int"),
    ("ridge_naive", "ridge", "naive", "naive"),
    ("ridge_first", "ridge", "first", "ridge_naive"),
    ("ridge_all", "ridge", "all", "ridge_naive"),
    ("ridge_int_first", "ridge", "int_first", "ridge_naive"),
    ("gbdt_naive", "gbdt", "naive", "naive"),
    ("gbdt_first", "gbdt", "first", "gbdt_naive"),
    ("gbdt_all", "gbdt", "all", "gbdt_naive"),
)
# 系統ごとに作り直すモデル（系統の行だけで学習）
FAMILY_FITS = (("fam_naive", "naive"), ("fam_first", "first"))


class ModelError(Exception):
    pass


# ---------------------------------------------------------------------------
# 特徴の組
# ---------------------------------------------------------------------------

def naive_col(m, name):
    return "naive%d_%d" % (m, naive.FEATURES.index(name))


def feature_columns(m, kind):
    """特徴の組の列の名前の一覧。掛け合わせは ("*", a, b) の形で、build_columns が作る。"""
    base = [naive_col(m, f) for f in naive.FEATURES]

    def nv(x):
        return naive_col(m, x) if x in naive.FEATURES else x
    if kind == "naive":
        return base
    if kind == "first":
        return base + list(S_FIRST)
    if kind == "all":
        return base + list(all_signal_columns())
    if kind == "naive_int":
        return base + [("*", naive_col(m, a), naive_col(m, b)) for a, b in NAIVE_PAIRS]
    if kind == "int_first":
        return base + list(S_FIRST) + [("*", nv(a), nv(b)) for a, b in INTERACTIONS]
    if kind == "int_both":
        return (base + [("*", naive_col(m, a), naive_col(m, b)) for a, b in NAIVE_PAIRS]
                + list(S_FIRST) + [("*", nv(a), nv(b)) for a, b in INTERACTIONS])
    raise ModelError("知らない特徴の組 %s" % kind)


def column_values(tb, c, rows):
    """表 tb の列 c（掛け合わせなら積）の、行 rows の値。"""
    if isinstance(c, tuple):
        a, b = tb[c[1]], tb[c[2]]
        return array.array("d", (a[r] * b[r] for r in rows))
    col = tb[c]
    return array.array("d", (col[r] for r in rows))


def column_label(c):
    if isinstance(c, tuple):
        return "%s*%s" % (label_of(c[1]), label_of(c[2]))
    return label_of(c)


def label_of(c):
    if c.startswith("naive") and "_" in c and c[5:].split("_")[0].isdigit():
        return naive.FEATURES[int(c.split("_")[1])]
    return c


# ---------------------------------------------------------------------------
# ロジスティック回帰（列ごとの計算。naive.fit_logistic と同じ手順）
# ---------------------------------------------------------------------------

def _sigmoid(z):
    return naive._sigmoid(z)


def _log1pexp(z):
    return naive._log1pexp(z)


def _plain_sum(it):
    """左から順に + で足す（naive の += と同じ。組み込みの sum は 3.12 から補正付きの足し算で、結果が違う）。"""
    return functools.reduce(operator.add, it, 0.0)


def _linear(rows, beta):
    """行ごとの z（naive と同じく組み込みの sum で特徴の順に足す）。"""
    return [sum(map(operator.mul, r, beta)) for r in rows]


def _objective(rows, y, beta, lam):
    s = 0.0
    for zi, yi in zip(_linear(rows, beta), y):
        s += _log1pexp(zi) - yi * zi
    return s + 0.5 * lam * sum(b * b for b in beta)


def fit_logistic_cols(cols, y, lam):
    """naive.fit_logistic と同じ手順と同じ足し方（β=0 から、ニュートン法、目的関数が減らなければ一歩を半分に最大30回、
    max|Δβ| < TOL で止める、MAX_ITER 回まで）を、勾配とヘッセ行列だけ列ごとの計算で行う。結果は naive.fit_logistic と
    ビット単位で同じ（テストで確かめる）。cols の最初の列は切片（すべて 1.0）。戻り値 {"coef", "iterations", "converged"}。"""
    k = len(cols)
    n = len(y)
    if k == 0 or any(len(c) != n for c in cols) or any(v not in (0, 1) for v in y):
        raise ModelError("形が違う")
    rows = list(zip(*cols))
    beta = [0.0] * k
    obj = _objective(rows, y, beta, lam)
    for it in range(1, naive.MAX_ITER + 1):
        p = [_sigmoid(zi) for zi in _linear(rows, beta)]
        w = [pi * (1.0 - pi) for pi in p]
        r = [yi - pi for yi, pi in zip(y, p)]
        grad = [_plain_sum(map(operator.mul, r, c)) for c in cols]
        H = [[0.0] * k for _ in range(k)]
        for a in range(k):
            wa = list(map(operator.mul, w, cols[a]))
            for b in range(a, k):
                H[a][b] = _plain_sum(map(operator.mul, wa, cols[b]))
        for a in range(k):
            for b in range(a):
                H[a][b] = H[b][a]
        for a in range(k):
            grad[a] -= lam * beta[a]
            H[a][a] += lam
        step = naive._solve(H, grad)
        scale = 1.0
        for _ in range(30):
            cand = [b + scale * s for b, s in zip(beta, step)]
            new_obj = _objective(rows, y, cand, lam)
            if new_obj <= obj:
                break
            scale /= 2.0
        else:
            return {"coef": beta, "iterations": it, "converged": False}
        delta = max(abs(scale * s) for s in step)
        beta, obj = cand, new_obj
        if delta < naive.TOL:
            return {"coef": beta, "iterations": it, "converged": True}
    return {"coef": beta, "iterations": naive.MAX_ITER, "converged": False}


def predict_cols(cols, coef):
    return [_sigmoid(z) for z in _linear(list(zip(*cols)), coef)]


def ordered(tb, rows):
    """行を（予言日、タグ名）の順に並べる（naive.sort_rows と同じ決まり）。"""
    out = sorted(rows, key=lambda r: (tb["t"][r], tb["tag"][r]))
    for a, b in zip(out, out[1:]):
        if (tb["t"][a], tb["tag"][a]) == (tb["t"][b], tb["tag"][b]):
            raise ModelError("同じ予言日とタグの行が二つある")
    return out


# ---------------------------------------------------------------------------
# GBDT（決定木を重ねる手法。設定は GBDT に固定。ロジスティックの損失、ニュートン法の葉の値）
# ---------------------------------------------------------------------------

def bin_edges(values, nbins):
    """学習の行の値から、分位点で区切りを作る（同じ値の区切りはまとめる）。"""
    s = sorted(values)
    n = len(s)
    edges = []
    for q in range(1, nbins):
        x = s[min(n - 1, (q * n) // nbins)]
        if not edges or x > edges[-1]:
            edges.append(x)
    return edges


def to_bins(values, edges):
    return bytes(bisect.bisect_right(edges, x) for x in values)


def fit_gbdt(train_bins, y, cfg, nb):
    """train_bins：特徴ごとの bytes（行の順）。nb：特徴ごとの区切りの数 + 1。
    戻り値：(初期値, 木の一覧)。木は節の dict：{"f", "b", "l", "r"} か {"v"}。"""
    n = len(y)
    pbar = sum(y) / n
    pbar = min(max(pbar, 1e-6), 1 - 1e-6)
    f0 = math.log(pbar / (1 - pbar))
    F = [f0] * n
    trees = []
    lam = cfg["l2"]
    for _t in range(cfg["trees"]):
        p = [_sigmoid(x) for x in F]
        g = [pi - yi for pi, yi in zip(p, y)]
        h = [pi * (1 - pi) for pi in p]
        tree, leaf_of = _grow(train_bins, nb, g, h, list(range(n)), cfg, lam, 0)
        trees.append(tree)
        for i, v in leaf_of.items():
            F[i] += v
    return f0, trees


def _grow(bins, nb, g, h, idx, cfg, lam, depth):
    G = sum(g[i] for i in idx)
    Hs = sum(h[i] for i in idx)
    leaf = {"v": -cfg["learning_rate"] * G / (Hs + lam)}
    if depth >= cfg["depth"] or len(idx) < 2 * cfg["min_leaf"]:
        return leaf, {i: leaf["v"] for i in idx}
    best = None
    parent = G * G / (Hs + lam)
    for f, col in enumerate(bins):
        k = nb[f]
        if k < 2:
            continue
        hg = [0.0] * k
        hh = [0.0] * k
        hc = [0] * k
        for i in idx:
            b = col[i]
            hg[b] += g[i]
            hh[b] += h[i]
            hc[b] += 1
        gl = hl = 0.0
        cl = 0
        for b in range(k - 1):
            gl += hg[b]
            hl += hh[b]
            cl += hc[b]
            cr = len(idx) - cl
            if cl < cfg["min_leaf"] or cr < cfg["min_leaf"]:
                continue
            gr, hr = G - gl, Hs - hl
            gain = gl * gl / (hl + lam) + gr * gr / (hr + lam) - parent
            if best is None or gain > best[0]:
                best = (gain, f, b)
    if best is None or best[0] <= 0:
        return leaf, {i: leaf["v"] for i in idx}
    _gain, f, b = best
    col = bins[f]
    li = [i for i in idx if col[i] <= b]
    ri = [i for i in idx if col[i] > b]
    lt, lm = _grow(bins, nb, g, h, li, cfg, lam, depth + 1)
    rt, rm = _grow(bins, nb, g, h, ri, cfg, lam, depth + 1)
    lm.update(rm)
    return {"f": f, "b": b, "l": lt, "r": rt}, lm


def predict_gbdt(model, test_bins, n):
    f0, trees = model
    out = []
    for i in range(n):
        s = f0
        for t in trees:
            node = t
            while "v" not in node:
                node = node["l"] if test_bins[node["f"]][i] <= node["b"] else node["r"]
            s += node["v"]
        out.append(_sigmoid(s))
    return out


# ---------------------------------------------------------------------------
# 表を作る（T-117 の phase2 の A〜C と同じ手順。モデルは作らない）
# ---------------------------------------------------------------------------

def build_table(root, cache_dir, workers, log):
    ctx = ei.load_context(root)
    meta = es.load_cache(cache_dir, ctx)
    tags, v = meta["tags"], ctx["v"]
    n = len(tags)
    U = len(meta["countries"])
    days = ctx["days"]
    mondays = ei.prediction_mondays()
    if meta["lang_rows_not_dash"] > 0:
        raise ModelError("日の集計に言語の別がある（T-117 の版と違う）")
    series = es.daily_series(meta)
    cumc, cumn = es.cumulative_weeks(meta["weekc"], meta["weeknc"], n, U)
    del meta["weekc"]
    log("キャッシュを読んだ")
    results = [None] * n
    lo = hi = None
    with es._pool(workers, es._init_eval, (days, mondays, v)) as pool:
        for k, (j, res, a, b) in enumerate(pool.imap(es._eval_task, list(enumerate(series)), chunksize=8), 1):
            results[j] = res
            if a is not None:
                lo = a if lo is None or a < lo else lo
                hi = b if hi is None or b > hi else hi
            if k % 500 == 0:
                log("タグ %d / %d" % (k, n))
    missing = set(meta["missing"])
    month_v1, month_docs, month_rsum, month_cnt = {}, {}, {}, {}
    v1 = meta["v1"]
    for di, d in enumerate(meta["days"]):
        if d in missing:
            continue
        mk = es.month_key(datetime.date.fromisoformat(d))
        mv = month_v1.setdefault(mk, [0] * n)
        rs = month_rsum.setdefault(mk, [0.0] * n)
        for i in range(n):
            mv[i] += v1[di * n + i]
            rs[i] += series[i][di]
        month_docs[mk] = month_docs.get(mk, 0) + meta["docs"][di]
        month_cnt[mk] = month_cnt.get(mk, 0) + 1
    pred_months = sorted({es.month_key(t) for t in mondays})
    windows = sorted({w for _n, w, _r in es.NETWORKS})
    small = {"tags": tags, "pair_files": meta["pair_files"], "month_v1": month_v1, "month_docs": month_docs}
    nets = {}
    with es._pool(workers, es._init_net, (cache_dir, small)) as pool:
        for w, mk, months, nb in pool.imap(es._net_task, [(w, mk) for w in windows for mk in pred_months]):
            nets[(w, mk)] = (months, nb)
    log("網を作った")
    cols = all_signal_columns()
    tb = {"t": [], "tag": [], "week": [], "family": [], "own_rise": []}
    for m in MULTIPLIERS:
        tb["y%d" % m] = []
        for k in range(len(naive.FEATURES)):
            tb["naive%d_%d" % (m, k)] = []
    for c in cols:
        tb[c] = []
    net_off = lead_off = None
    win_cache = {}
    for ti, t in enumerate(mondays):
        rises = [None] * n
        trends = [None] * n
        cur = [None] * n
        for j in range(n):
            st, b, c, m1, m2, _js, _lv = results[j][ti]
            if b is not None and c is not None:
                rises[j] = es.rise(c, b, v)
                cur[j] = c
            if m1 is not None and m2 is not None:
                trends[j] = es.rise(m1, m2, v)
        rec_w, base_w = es.lead_weeks(t)
        off = (es.week_last_day(rec_w) - t).days
        lead_off = off if lead_off is None else max(lead_off, off)
        per_net = {}
        for net, w, refresh in es.NETWORKS:
            months = es.network_months(t, w, refresh)
            off = es.check_network_before(t, months)
            net_off = off if net_off is None else max(net_off, off)
            got_months, nb = nets[(w, es.add_months(months[-1], 1))]
            if got_months != months:
                raise ModelError("網の月の一覧が合わない")
            wk = tuple(months)
            if wk not in win_cache:
                cnt = sum(month_cnt[m] for m in months)
                win_cache[wk] = [(sum(month_rsum[m][i] for m in months) / cnt) if cnt else None for i in range(n)]
            per_net[net] = (nb, win_cache[wk])
        for i in range(n):
            st, b, c, m1, m2, js, lv = results[i][ti]
            if st != "target" or any(x is None for x in js):
                continue
            tb["t"].append(t)
            tb["tag"].append(tags[i])
            tb["week"].append(ti)
            tb["family"].append(family_of(tags[i]))
            tb["own_rise"].append(rises[i] if rises[i] is not None else 0.0)
            for m, y in zip(MULTIPLIERS, js):
                tb["y%d" % m].append(1 if y else 0)
                for k, x in enumerate(naive.features_from_levels(lv, m, v)):
                    tb["naive%d_%d" % (m, k)].append(x)
            vals = {}
            for net, _w, _r in es.NETWORKS:
                nb, win = per_net[net]
                for nbn, _k, _K in es.NEIGHBORS:
                    vv = "%s_%s" % (net, nbn)
                    nbrs = nb[nbn].get(i)
                    nr, nt = es.neighbor_signal(nbrs, rises, trends)
                    vals["nb_rise_" + vv] = nr
                    vals["nb_trend_" + vv] = nt
                    vals["gap_" + vv] = (rises[i] - nr) if (nr is not None and rises[i] is not None) else None
                    vals["expect_" + vv] = es.expect_signal(i, nbrs, cur, win, v)
            lm, lf = es.lead_signal(i, rec_w, base_w, cumc, cumn, n, U, v)
            vals["lead_country_max"], vals["lead_country_frac2"] = lm, lf
            for c in cols:
                if c.startswith("nb_miss_"):
                    x = 1.0 if vals["nb_rise_" + c[len("nb_miss_"):]] is None else 0.0
                elif c.startswith("gap_miss_"):
                    x = 1.0 if vals["gap_" + c[len("gap_miss_"):]] is None else 0.0
                elif c.startswith("expect_miss_"):
                    x = 1.0 if vals["expect_" + c[len("expect_miss_"):]] is None else 0.0
                elif c == "lead_miss_country":
                    x = 1.0 if lm is None else 0.0
                else:
                    x = vals.get(c)
                    x = 0.0 if x is None else x
                tb[c].append(x)
        if (ti + 1) % 40 == 0:
            log("信号 %d / %d 週" % (ti + 1, len(mondays)))
    for c in list(cols) + ["own_rise"] + ["naive%d_%d" % (m, k) for m in MULTIPLIERS for k in range(len(naive.FEATURES))]:
        if len(tb[c]) != len(tb["t"]):
            raise ModelError("列 %s の長さが違う" % c)
        tb[c] = array.array("d", tb[c])
    for m in MULTIPLIERS:
        tb["y%d" % m] = array.array("b", tb["y%d" % m])
    tb["train"] = [r for r, t in enumerate(tb["t"]) if es.split_of(t) == "train"]
    tb["test"] = [r for r, t in enumerate(tb["t"]) if es.split_of(t) == "test"]
    tb["inner_train"] = [r for r in tb["train"] if tb["t"][r] <= INNER_TRAIN_LAST]
    tb["inner_val"] = [r for r in tb["train"] if tb["t"][r] >= INNER_VAL_FIRST]
    info = {"daily_min_read": lo.isoformat(), "daily_max_read": hi.isoformat(),
            "network_last_day_minus_t_max_days": net_off, "country_week_last_day_minus_t_max_days": lead_off,
            "phase1_sha256": meta["phase1_sha256"], "phase1_label": meta["label"], "refs": ctx["refs"],
            "v": meta["v"]}
    return tb, info


def check_inner_split(tb):
    """学習の期間の中の分け方：作る行と測る行が重ならず、どちらも学習の期間の中にあり、検証の期間の行を含まない。"""
    last_inner = max(tb["t"][r] for r in tb["inner_train"])
    first_val = min(tb["t"][r] for r in tb["inner_val"])
    if not last_inner + datetime.timedelta(days=HORIZON) < first_val + datetime.timedelta(days=1):
        raise ModelError("学習の期間の中の作る行と測る行の判定期間が重なる")
    test = set(tb["test"])
    if any(r in test for r in tb["inner_train"] + tb["inner_val"]):
        raise ModelError("学習の期間の中の分け方に、検証の期間の行が入っている")
    if any(tb["t"][r] > es.TRAIN_LAST for r in tb["inner_train"] + tb["inner_val"]):
        raise ModelError("学習の期間の中の分け方に、学習の期間の外の行がある")
    return last_inner, first_val


# ---------------------------------------------------------------------------
# 子プロセスの仕事
# ---------------------------------------------------------------------------

_W = {}


def _init_fit(tb):
    _W["tb"] = tb


def logit_task(tb, m, kind, lam, train_rows, eval_rows):
    """リッジ lam のロジスティック回帰を train_rows で作り、eval_rows の確率を返す。"""
    feats = feature_columns(m, kind)
    tr = ordered(tb, train_rows)
    cols = [column_values(tb, c, tr) for c in feats]
    y = [tb["y%d" % m][r] for r in tr]
    fit = fit_logistic_cols(cols, y, lam)
    ecols = [column_values(tb, c, eval_rows) for c in feats]
    return [column_label(c) for c in feats], fit, predict_cols(ecols, fit["coef"])


def gbdt_task(tb, m, kind, train_rows, eval_rows):
    feats = feature_columns(m, kind)
    tr = ordered(tb, train_rows)
    tbins, ebins, nb = [], [], []
    for c in feats[1:]:                        # 切片は使わない
        tv = column_values(tb, c, tr)
        edges = bin_edges(tv, GBDT["bins"])
        tbins.append(to_bins(tv, edges))
        ebins.append(to_bins(column_values(tb, c, eval_rows), edges))
        nb.append(len(edges) + 1)
    y = [tb["y%d" % m][r] for r in tr]
    model = fit_gbdt(tbins, y, GBDT, nb)
    return [column_label(c) for c in feats[1:]], model, predict_gbdt(model, ebins, len(eval_rows))


def _task(args):
    kind = args[0]
    tb = _W["tb"]
    if kind == "inner":
        _k, m, fset, lam = args
        labels, fit, probs = logit_task(tb, m, fset, lam, tb["inner_train"], tb["inner_val"])
        ys = [tb["y%d" % m][r] for r in tb["inner_val"]]
        ll = sum(es.log_loss_terms(probs, ys)) / len(ys)
        return args, {"logloss": ll, "converged": fit["converged"], "iterations": fit["iterations"]}
    if kind == "logit":
        _k, m, fset, lam = args
        labels, fit, probs = logit_task(tb, m, fset, lam, tb["train"], tb["test"])
        return args, {"labels": labels, "coef": fit["coef"], "converged": fit["converged"],
                      "iterations": fit["iterations"], "probs": probs}
    if kind == "gbdt":
        _k, m, fset = args
        labels, _model, probs = gbdt_task(tb, m, fset, tb["train"], tb["test"])
        return args, {"labels": labels, "probs": probs, "converged": True, "iterations": GBDT["trees"]}
    if kind == "family":
        _k, m, fset, fam = args
        tr = [r for r in tb["train"] if tb["family"][r] == fam]
        te = [r for r in tb["test"] if tb["family"][r] == fam]
        labels, fit, probs = logit_task(tb, m, fset, FIXED_LAMBDA, tr, te)
        return args, {"labels": labels, "coef": fit["coef"], "converged": fit["converged"],
                      "iterations": fit["iterations"], "probs": probs, "rows": te}
    raise ModelError("知らない仕事")


def choose_lambda(inner):
    """{lam: 学習の期間の中の測る行の対数損失} から、最も小さいものを選ぶ（同じなら大きい lam）。収まらなかったものは除く。"""
    ok = [(ll, -lam, lam) for lam, (ll, conv) in inner.items() if conv]
    if not ok:
        raise ModelError("どの強さも収まらなかった")
    return min(ok)[2]


# ---------------------------------------------------------------------------
# 評価
# ---------------------------------------------------------------------------

def metrics(tb, m, rows, probs, ref_probs, weeks_all):
    """rows の行の指標と、ref_probs（同じ rows の比べる相手）との差の4週束ねの範囲。"""
    ys = [tb["y%d" % m][r] for r in rows]
    wk = [tb["week"][r] for r in rows]
    tg = [tb["tag"][r] for r in rows]
    ll = es.log_loss_terms(probs, ys)
    tk = es.topk_by_week(probs, ys, wk, tg)
    out = {"n": len(ys), "pos": sum(ys), "logloss": sum(ll) / len(ll), "auc": es.auc(probs, ys),
           "topk": sum(tk.values())}
    if ref_probs is None:
        return out
    rll = es.log_loss_terms(ref_probs, ys)
    rtk = es.topk_by_week(ref_probs, ys, wk, tg)
    by_w = {}
    for x, xr, w in zip(ll, rll, wk):
        a = by_w.setdefault(w, [0.0, 0])
        a[0] += x - xr
        a[1] += 1
    blks = es.blocks_of(weeks_all, es.BLOCK_WEEKS)
    vals = [(sum(by_w.get(w, [0.0, 0])[0] for w in b), sum(by_w.get(w, [0.0, 0])[1] for w in b)) for b in blks]
    tvals = [(sum(tk.get(w, 0) - rtk.get(w, 0) for w in b), len(b)) for b in blks]
    lo, hi = es.bootstrap_diff(tvals)
    out.update({"ref_logloss": sum(rll) / len(rll), "d_logloss": (sum(ll) - sum(rll)) / len(ll),
                "d_ll_ci": es.bootstrap_diff(vals), "d_topk": out["topk"] - sum(rtk.values()),
                "d_tk_ci": (lo * len(weeks_all), hi * len(weeks_all))})
    return out


def run(root, cache_dir, out_dir, workers, log):
    tb, info = build_table(root, cache_dir, workers, log)
    last_inner, first_val = check_inner_split(tb)
    log("表：%d 行（学習 %d、検証 %d、学習の中の作る %d・測る %d）" % (
        len(tb["t"]), len(tb["train"]), len(tb["test"]), len(tb["inner_train"]), len(tb["inner_val"])))
    ridge_sets = sorted({fs for _n, kind, fs, _r in MODELS if kind == "ridge"})
    stage1 = [("inner", m, fs, lam) for m in MULTIPLIERS for fs in ridge_sets for lam in RIDGE_LAMBDAS]
    stage1 += [("logit", m, fs, FIXED_LAMBDA) for m in MULTIPLIERS for _n, kind, fs, _r in MODELS if kind == "logit"]
    stage1 += [("gbdt", m, fs) for m in MULTIPLIERS for _n, kind, fs, _r in MODELS if kind == "gbdt"]
    stage1 += [("family", m, fs, fam) for m in MULTIPLIERS for _n, fs in FAMILY_FITS for fam in FAMILIES]
    # 重い仕事を先に流す（並べ方は結果に影響しない）
    weight = {"gbdt": 0, "inner": 1, "logit": 2, "family": 3}
    stage1.sort(key=lambda a: (weight[a[0]], -len(feature_columns(a[1], a[2])), repr(a)))
    res = {}
    with es._pool(workers, _init_fit, (tb,)) as pool:
        for k, (args, out) in enumerate(pool.imap_unordered(_task, stage1), 1):
            res[args] = out
            log("仕事 %d / %d %r" % (k, len(stage1), args))
        chosen = {}
        for m in MULTIPLIERS:
            for fs in ridge_sets:
                inner = {lam: (res[("inner", m, fs, lam)]["logloss"], res[("inner", m, fs, lam)]["converged"])
                         for lam in RIDGE_LAMBDAS}
                chosen[(m, fs)] = choose_lambda(inner)
        stage2 = sorted({("logit", m, fs, chosen[(m, fs)]) for m in MULTIPLIERS for fs in ridge_sets} - set(res),
                        key=repr)
        for k, (args, out) in enumerate(pool.imap_unordered(_task, stage2), 1):
            res[args] = out
            log("作り直し %d / %d %r" % (k, len(stage2), args))
    files = build_outputs(tb, info, res, chosen, last_inner, first_val)
    return write_outputs(out_dir, files)


def model_result(res, chosen, m, name):
    for n2, kind, fs, _r in MODELS:
        if n2 == name:
            if kind == "logit":
                return res[("logit", m, fs, FIXED_LAMBDA)]
            if kind == "ridge":
                return res[("logit", m, fs, chosen[(m, fs)])]
            return res[("gbdt", m, fs)]
    raise ModelError("知らないモデル %s" % name)


OUT_NAMES = ("models.tsv", "families.tsv", "ridge.tsv", "coefs.tsv", "run.json", "summary.md")


def f6(x):
    return es.f6(x)


def build_outputs(tb, info, res, chosen, last_inner, first_val):
    test = tb["test"]
    weeks_all = sorted({tb["week"][r] for r in test})
    mrows, frows, rrows, crows = [], [], [], []
    for m in MULTIPLIERS:
        naive_p = model_result(res, chosen, m, "naive")["probs"]
        for name, kind, fs, ref in MODELS:
            out = model_result(res, chosen, m, name)
            mn = metrics(tb, m, test, out["probs"], None if name == "naive" else naive_p, weeks_all)
            if ref is not None and ref != "naive":
                mr = metrics(tb, m, test, out["probs"], model_result(res, chosen, m, ref)["probs"], weeks_all)
            else:
                mr = mn
            lam = chosen.get((m, fs)) if kind == "ridge" else (FIXED_LAMBDA if kind == "logit" else None)
            mrows.append({"m": m, "name": name, "kind": kind, "fset": fs, "ref": ref, "lam": lam, "nfeat":
                          len(out["labels"]), "mn": mn, "mr": mr, "conv": out["converged"], "iter": out["iterations"]})
            if "coef" in out:
                for lab, b in zip(out["labels"], out["coef"]):
                    crows.append((m, name, lab, f6(b)))
        # 系統：全体のモデルを系統の行で測る、系統の行だけで作ったモデル
        pos = {r: k for k, r in enumerate(test)}
        for fam in FAMILIES:
            rows = [r for r in test if tb["family"][r] == fam]
            idx = [pos[r] for r in rows]
            fw = sorted({tb["week"][r] for r in rows})
            npf = [naive_p[k] for k in idx]
            for name in ("naive", "lin_first", "ridge_first", "gbdt_naive", "gbdt_first"):
                pp = [model_result(res, chosen, m, name)["probs"][k] for k in idx]
                ref = {"lin_first": "naive", "ridge_first": "ridge_naive", "gbdt_first": "gbdt_naive"}.get(name)
                refp = [model_result(res, chosen, m, ref)["probs"][k] for k in idx] if ref else None
                frows.append({"m": m, "fam": fam, "name": name, "fit": "all_rows", "ref": ref,
                              "x": metrics(tb, m, rows, pp, refp, fw)})
            fn = res[("family", m, "naive", fam)]
            ff = res[("family", m, "first", fam)]
            if fn["rows"] != rows or ff["rows"] != rows:
                raise ModelError("系統の行が合わない")
            frows.append({"m": m, "fam": fam, "name": "fam_naive", "fit": "family_rows", "ref": None,
                          "x": metrics(tb, m, rows, fn["probs"], None, fw)})
            frows.append({"m": m, "fam": fam, "name": "fam_first", "fit": "family_rows", "ref": "fam_naive",
                          "x": metrics(tb, m, rows, ff["probs"], fn["probs"], fw)})
            for lab, b in zip(ff["labels"], ff["coef"]):
                crows.append((m, "fam_first_" + fam, lab, f6(b)))
        for fs in sorted({fs for (mm, fs) in chosen if mm == m}):
            for lam in RIDGE_LAMBDAS:
                r = res[("inner", m, fs, lam)]
                rrows.append((m, fs, lam, f6(r["logloss"]), r["converged"], "yes" if chosen[(m, fs)] == lam else ""))

    def ci(x, key):
        v = x.get(key)
        return ("-", "-") if v is None else (f6(v[0]), f6(v[1]))
    models_tsv = ei.tsv(
        ("multiplier", "horizon_days", "model", "kind", "features", "n_features", "lambda", "n_test", "islands_test",
         "logloss", "auc", "top10_hits", "d_logloss_vs_naive", "d_ll_vs_naive_ci4w_lo", "d_ll_vs_naive_ci4w_hi",
         "d_top10_vs_naive", "ref", "d_logloss_vs_ref", "d_ll_vs_ref_ci4w_lo", "d_ll_vs_ref_ci4w_hi", "d_top10_vs_ref",
         "converged", "iterations"),
        [(r["m"], HORIZON, r["name"], r["kind"], r["fset"], r["nfeat"], "-" if r["lam"] is None else r["lam"],
          r["mn"]["n"], r["mn"]["pos"], f6(r["mn"]["logloss"]), f6(r["mn"]["auc"]), r["mn"]["topk"],
          f6(r["mn"].get("d_logloss")), *ci(r["mn"], "d_ll_ci"), r["mn"].get("d_topk", "-"), r["ref"] or "-",
          f6(r["mr"].get("d_logloss")), *ci(r["mr"], "d_ll_ci"), r["mr"].get("d_topk", "-"), r["conv"], r["iter"])
         for r in mrows])
    families_tsv = ei.tsv(
        ("multiplier", "family", "model", "fit_rows", "n_test", "islands_test", "logloss", "auc", "top10_hits",
         "ref", "d_logloss_vs_ref", "d_ll_ci4w_lo", "d_ll_ci4w_hi", "d_top10_vs_ref"),
        [(r["m"], r["fam"], r["name"], r["fit"], r["x"]["n"], r["x"]["pos"], f6(r["x"]["logloss"]), f6(r["x"]["auc"]),
          r["x"]["topk"], r["ref"] or "-", f6(r["x"].get("d_logloss")), *ci(r["x"], "d_ll_ci"),
          r["x"].get("d_topk", "-")) for r in frows])
    ridge_tsv = ei.tsv(("multiplier", "features", "lambda", "inner_val_logloss", "converged", "chosen"), rrows)
    coefs_tsv = ei.tsv(("multiplier", "model", "feature", "coef"), crows)
    code = dict(ei._LOADED_SHA, **es.own_code_shas())
    with open(os.path.abspath(__file__), "rb") as f:
        code["src/stats/explore_models.py"] = hashlib.sha256(f.read()).hexdigest()
    n_models = len(MODELS) - 1
    run_json = dict(info, **{
        "label": LABEL, "code": code, "python": sys.version.split()[0],
        "rows": {"all": len(tb["t"]), "train": len(tb["train"]), "test": len(tb["test"]),
                 "inner_train": len(tb["inner_train"]), "inner_val": len(tb["inner_val"])},
        "inner_train_last_monday": last_inner.isoformat(), "inner_val_first_monday": first_val.isoformat(),
        "train_last_monday": es.TRAIN_LAST.isoformat(), "test_first_monday": es.TEST_FIRST.isoformat(),
        "chosen_lambda": {"%d_%s" % k: v for k, v in sorted(chosen.items())},
        "options": {"first_variant": FIRST_VARIANT, "s_first": S_FIRST, "interactions": INTERACTIONS,
                    "naive_pairs": NAIVE_PAIRS, "ridge_lambdas": RIDGE_LAMBDAS, "fixed_lambda": FIXED_LAMBDA,
                    "gbdt": GBDT, "families": FAMILIES, "models": MODELS, "family_fits": FAMILY_FITS,
                    "boot_n": es.BOOT_N, "boot_seed": es.BOOT_SEED, "block_weeks": es.BLOCK_WEEKS},
        "comparisons_per_multiplier": n_models, "comparisons_total": n_models * len(MULTIPLIERS),
        "test_weeks": len(weeks_all), "test_blocks_4w": len(es.blocks_of(weeks_all, es.BLOCK_WEEKS)),
        "citation": [ei.CITATION_EN, ei.CITATION_JA]})
    files = {"models.tsv": models_tsv, "families.tsv": families_tsv, "ridge.tsv": ridge_tsv, "coefs.tsv": coefs_tsv,
             "run.json": (json.dumps(run_json, ensure_ascii=False, sort_keys=True, indent=1) + "\n").encode("utf-8")}
    files["summary.md"] = summary_md(run_json, mrows, frows, rrows)
    for name, data in files.items():
        ei.check_public(name, data)
    return files


def write_outputs(out_dir, files):
    if sorted(files) != sorted(OUT_NAMES):
        raise ModelError("出力の名前が決めた一覧と違う")
    os.makedirs(out_dir, exist_ok=True)
    for n in OUT_NAMES:
        if os.path.lexists(os.path.join(out_dir, n)):
            raise ModelError("書き出す先に同じ名前のファイル（%s）がある。上書きしない" % n)
    return {n: es.write_new(os.path.join(out_dir, n), files[n]) for n in OUT_NAMES}


NAME_JA = {
    "naive": "素朴な予測だけ（ロジスティック、リッジ 1）",
    "lin_first": "＋信号（first）",
    "naive_int": "素朴な予測＋素朴な特徴どうしの掛け合わせ",
    "int_first": "＋信号＋信号の掛け合わせ",
    "int_both": "＋両方の掛け合わせ",
    "ridge_naive": "素朴な予測だけ（強さを選ぶ）",
    "ridge_first": "＋信号 first（強さを選ぶ）",
    "ridge_all": "＋T-117 の全部の信号（強さを選ぶ）",
    "ridge_int_first": "＋信号＋掛け合わせ（強さを選ぶ）",
    "gbdt_naive": "GBDT：素朴な予測だけ",
    "gbdt_first": "GBDT：＋信号 first",
    "gbdt_all": "GBDT：＋T-117 の全部の信号",
}


def summary_md(run, mrows, frows, rrows):
    L = []
    a = L.append
    md = ei.md_table
    a("# 多変量の形の探索（T-118、手法を作る期間）")
    a("")
    a("この文書は `src/stats/explore_models.py` が出力したもので、手で書き足していない。モデルの形・係数・強さは、"
      "ここでは決めない（決定はオーナー）。全部の結果を並べ、選ばない・勧めない。")
    a("")
    a("## 0. 何をどう比べたか")
    a("- 入力・予言日・対象・判定・学習と検証の分け方は T-117 と同じ（キャッシュ phase1.json の sha256 %s、版 %s）。"
      "学習：予言日 %s 以前（%d 行）。検証：%s 以降（%d 行）。倍率 %s、判定期間 %d 日。" % (
          run["phase1_sha256"], run["phase1_label"], run["train_last_monday"], run["rows"]["train"],
          run["test_first_monday"], run["rows"]["test"], "・".join(str(m) for m in MULTIPLIERS), HORIZON))
    a("- 信号の組 first：T-117 で最初に並べた選択肢（網 %s）の 2.1・2.3 と、2.2 の国（max・frac2）。T-117 の結果で選んだものではない。"
      "all：T-117 の全部の信号の列（%d 列）。" % (FIRST_VARIANT, len(all_signal_columns())))
    a("- 交互作用：信号 first の値の6列 × 予言の時点の静かさ（素朴な予測の recent）、同じ6列 × タグの大きさ（size）、"
      "隣の上がり × 自分の上がり（log((c+V)/(B+V))）の13個。素朴な予測の特徴どうしの掛け合わせは、切片を除く6つの組すべて（15個）。")
    a("- リッジの強さ：候補 %s。学習の期間の中で、予言日 %s 以前で作り、%s〜%s で測った対数損失が最も小さいものを選んだ"
      "（同じなら大きい方。収まらなかった推定は除く）。選んだ強さで学習の期間全体で作り直し、検証の期間で測った。"
      "検証の期間の行は、選ぶ計算に入っていない（コードで確かめて止まる形）。" % (
          "・".join("%g" % x for x in RIDGE_LAMBDAS), run["inner_train_last_monday"], run["inner_val_first_monday"],
          run["train_last_monday"]))
    a("- GBDT（決定木を重ねる手法）：木 %d 本、深さ %d、学習率 %g、葉の最小の行 %d、葉の値の L2 %g、特徴は学習の行の分位点で %d 区分。"
      "ロジスティックの損失。設定は固定し、検証の期間で調整していない。採用の候補ではなく、上限の目安。" % (
          GBDT["trees"], GBDT["depth"], GBDT["learning_rate"], GBDT["min_leaf"], GBDT["l2"], GBDT["bins"]))
    a("- 系統：名前の頭の部分で %s（そのほかは other）。全体で作ったモデルを系統の行で測ったものと、系統の行だけで作ったもの"
      "（ロジスティック、リッジ 1）の両方。" % "・".join(FAMILIES[:-1]))
    a("- 指標：対数損失・AUC・週ごとの確率の上位10の島（T-117 と同じ）。差の範囲は、検証の週を4週ずつ束ねた単位（%d 個）の"
      "復元抽出（%d 回、乱数の種 %d）の 2.5%% と 97.5%% の点。" % (run["test_blocks_4w"], es.BOOT_N, es.BOOT_SEED))
    a("- ロジスティック回帰の推定は、naive.fit_logistic と同じ手順を列ごとの計算で行った（同じ答えになることをテストで確かめた）。")
    a("- 試す形はこのファイルに書いてコミットした版で流した（7章のコードの sha256）。本番より前に、この版の結果（検証の期間）を見る試しは流していない"
      "（係の申告）。")
    a("")
    a("## 1. 全体の結果（検証）")
    a("")
    for m in MULTIPLIERS:
        rows = [r for r in mrows if r["m"] == m]
        nv = rows[0]["mn"]
        a("### 倍率 %d（検証の行 %d、島 %d）" % (m, nv["n"], nv["pos"]))
        a("")
        a(md(["モデル", "特徴の数", "強さ", "対数損失", "AUC", "上位10の島", "素朴な予測との差（割合）",
              "差の範囲（4週束ね）", "比べる相手", "相手との差（割合）", "相手との差の範囲", "相手との上位10の差"],
             [(r["name"], r["nfeat"], "-" if r["lam"] is None else "%g" % r["lam"], f6(r["mn"]["logloss"]),
               f6(r["mn"]["auc"]), r["mn"]["topk"],
               "-" if r["name"] == "naive" else "%s（%+.2f%%）" % (f6(r["mn"]["d_logloss"]),
                                                                   100 * r["mn"]["d_logloss"] / nv["logloss"]),
               "-" if r["name"] == "naive" else "%s〜%s" % (f6(r["mn"]["d_ll_ci"][0]), f6(r["mn"]["d_ll_ci"][1])),
               r["ref"] or "-",
               "-" if not r["ref"] else "%s（%+.2f%%）" % (f6(r["mr"]["d_logloss"]),
                                                          100 * r["mr"]["d_logloss"] / r["mr"]["ref_logloss"]),
               "-" if not r["ref"] else "%s〜%s" % (f6(r["mr"]["d_ll_ci"][0]), f6(r["mr"]["d_ll_ci"][1])),
               "-" if not r["ref"] else r["mr"]["d_topk"]) for r in rows]))
        a("")
        below = [r["name"] for r in rows if r["ref"] and r["mr"]["d_ll_ci"][1] < 0]
        above = [r["name"] for r in rows if r["ref"] and r["mr"]["d_ll_ci"][0] > 0]
        a("- 比べる相手との対数損失の差の範囲が0より下に収まったモデル：%s。0より上に収まったモデル：%s。" % (
            "、".join(below) if below else "無い", "、".join(above) if above else "無い"))
        nc = [r["name"] for r in rows if not r["conv"]]
        if nc:
            a("- 収まらなかった推定：%s（結果は参考）。" % "、".join(nc))
        a("- この一覧の読み方：比べた数はこの倍率で %d（素朴な予測を除く）、3つの倍率で計 %d で、多重比較の補正をしていない。"
          "4週の束どうしは独立でない（判定期間 %d 日が隣の束に重なる。最後の束は %d 週）。範囲が0を含まないことは、"
          "形や信号が効くことの確かめにはならない。" % (run["comparisons_per_multiplier"], run["comparisons_total"], HORIZON,
                                                     run["test_weeks"] - es.BLOCK_WEEKS * (run["test_blocks_4w"] - 1)))
        a("")
    a("比べる相手：lin_first・naive_int は naive、int_first は lin_first、int_both は naive_int、ridge_* は ridge_naive、"
      "gbdt_first・gbdt_all は gbdt_naive、ridge_naive・gbdt_naive は naive。")
    a("")
    a("## 2. リッジの強さ（学習の期間の中で選んだ手順）")
    a("")
    a(md(["倍率", "特徴の組", "強さ", "学習の中の測る行の対数損失", "収まったか", "選んだ"], rrows))
    a("")
    a("## 3. テーマの系統ごと（検証）")
    a("")
    a("全体で作ったモデル（all_rows）を系統の行だけで測ったものと、系統の行だけで作ったモデル（family_rows）。上位10は、系統の行の中で週ごとに数えた。")
    a("")
    for m in MULTIPLIERS:
        a("### 倍率 %d" % m)
        a("")
        a(md(["系統", "モデル", "作った行", "検証の行", "島", "対数損失", "AUC", "上位10の島", "比べる相手", "差（割合）",
              "差の範囲（4週束ね）", "上位10の差"],
             [(r["fam"], r["name"], r["fit"], r["x"]["n"], r["x"]["pos"], f6(r["x"]["logloss"]), f6(r["x"]["auc"]),
               r["x"]["topk"], r["ref"] or "-",
               "-" if not r["ref"] else "%s（%+.2f%%）" % (f6(r["x"]["d_logloss"]),
                                                          100 * r["x"]["d_logloss"] / r["x"]["ref_logloss"]),
               "-" if not r["ref"] else "%s〜%s" % (f6(r["x"]["d_ll_ci"][0]), f6(r["x"]["d_ll_ci"][1])),
               "-" if not r["ref"] else r["x"]["d_topk"]) for r in frows if r["m"] == m]))
        a("")
    a("系統ごとの比べ方も、多重比較の補正をしていない（系統4 × 比べ方4 × 倍率3）。系統の検証の行は少ないものがあり、束ねた範囲は粗い。")
    a("")
    a("## 4. 読み方の手がかり（事実だけ）")
    for m in MULTIPLIERS:
        rows = {r["name"]: r for r in mrows if r["m"] == m}
        a("- 倍率 %d：素朴な予測だけの対数損失は、ロジスティック %s、強さを選んだもの %s、GBDT %s。信号 first を足した差（割合）は、"
          "ロジスティック %+.2f%%、強さを選んだもの %+.2f%%、GBDT %+.2f%%。" % (
              m, f6(rows["naive"]["mn"]["logloss"]), f6(rows["ridge_naive"]["mn"]["logloss"]),
              f6(rows["gbdt_naive"]["mn"]["logloss"]),
              100 * rows["lin_first"]["mr"]["d_logloss"] / rows["lin_first"]["mr"]["ref_logloss"],
              100 * rows["ridge_first"]["mr"]["d_logloss"] / rows["ridge_first"]["mr"]["ref_logloss"],
              100 * rows["gbdt_first"]["mr"]["d_logloss"] / rows["gbdt_first"]["mr"]["ref_logloss"]))
    a("")
    a("## 5. 予言の時点のデータだけを使ったことの確かめ（T-117 の関数で表を作った）")
    a("- 日の比率：実際に読んだ日は %s〜%s（予言日 t の入力は t-399〜t-1、判定は t+1〜t+28 の外を読むと止まる）。" % (
        run["daily_min_read"], run["daily_max_read"]))
    a("- 網の最後の日 − t の最大は %d 日、国別の週の最後の日 − t の最大は %d 日。" % (
        run["network_last_day_minus_t_max_days"], run["country_week_last_day_minus_t_max_days"]))
    a("- リッジの強さを選ぶ計算は、学習の期間の行だけ（作る行 %d、測る行 %d）。検証の期間の行が入っていれば止まる。" % (
        run["rows"]["inner_train"], run["rows"]["inner_val"]))
    a("")
    a("## 6. 限界")
    a("- **一覧と V の先読み**：タグの一覧と V（= A）は、手法を作る期間の区画全体のデータで決まった（seq 17）。"
      "この期間では、予言の対象の範囲と V が t より後のデータに依る（T-116 の要約 6章）。")
    a("- **除外の規則の漏れ**：TAX_WORLDLANGUAGES_*・TAX_FNCACT_* などの名前で、民族・人物の姓・宗教・犯罪・紛争・政治に当たる"
      "テーマが一覧に残っている（オーナーの決定 2026-10-16、(a) このまま進める）。系統の表の TAX_WORLDLANGUAGES・TAX_FNCACT にも入る。"
      "この要約にはテーマの名前を載せていない。")
    a("- **WB のテーマの段のような上昇**：2016年4月から WB のテーマの一部が段のように上がり、2017年に戻る（T-116 の要約 6章）。"
      "学習の期間と、リッジの強さを選ぶ学習の中の作る行（〜2017年）に入る。報道かテーマの付け方の変化かは区別できない。")
    a("- **2.2 の「国」**：記事が言及した場所で、報道した媒体の国ではない。言語は今のデータでは測れない。2.2 は方針書の仮説を試していない（T-117）。")
    a("- 検証は1回の前後の分け方だけ。比べた数（%d）のほかに、掛け合わせの選び方・強さの候補・GBDT の設定・系統の分け方・"
      "信号の組の選び方も選びうるもので、この数に入っていない。" % run["comparisons_total"])
    a("- GBDT は上限の目安で、設定を一つに固定した。設定を変えれば数字は変わる。")
    a("")
    a("## 7. 再計算")
    a("```")
    a(".venv/bin/python -B src/stats/explore_models.py --cache-dir <explore-t117-cache/run2> --out-dir <書き出す先>")
    a("```")
    for k in sorted(run["code"]):
        a("- %s：sha256 %s" % (k, run["code"][k]))
    a("")
    a("## 引用")
    a(ei.CITATION_EN)
    a("")
    a(ei.CITATION_JA)
    return ("\n".join(L) + "\n").encode("utf-8")


def main(argv=None):
    p = argparse.ArgumentParser(description="T-118 多変量の形の探索")
    p.add_argument("--cache-dir", required=True)
    p.add_argument("--out-dir", required=True)
    p.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 1))
    a = p.parse_args(argv)
    t0 = time.time()

    def log(msg):
        sys.stderr.write("[%8.1f s] %s\n" % (time.time() - t0, msg))
        sys.stderr.flush()
    try:
        shas = run(ei.PROJECT, a.cache_dir, a.out_dir, a.workers, log)
    except (ModelError, es.SignalError, ei.ExploreError) as e:
        sys.stderr.write("止まった：%s\n" % e)
        return 1
    for n in OUT_NAMES:
        print("%s  %s" % (shas[n], n))
    log("終わり")
    return 0


if __name__ == "__main__":
    sys.exit(main())
