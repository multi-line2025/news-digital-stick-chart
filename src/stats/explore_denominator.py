#!/usr/bin/env python3
"""T-122：分母の感度分析と、中心性の低下の確かめ（他の AI の指摘を受けた確かめ）。

1. 分母の感度分析
   正式な数え方 C7（v1_or_v2_docs ÷ 同じ欄の全テーマの和）の分母は記事の数ではなく、テーマの付与の総数である。
   比率の数え方を次の4つにして、T-115 と同じ予言日・対象の決め方・判定（一度跳ねたタグの扱いあり）で比べる。
     C7：正式（seq 6・seq 14 の封印）
     C1：v1_docs ÷ D の行の docs（封印済みの参考の候補）
     C3：v2_docs ÷ D の行の docs（封印済みの参考の候補）
     X ：v1_or_v2_docs ÷ D の行の docs（この探索のための数え方。封印された候補ではない）
   数える組・欠けた日の扱いは counting.py と candidates.md のまま（封印済みのコードを変えずに使う。欠けた日は seq 15 の一覧）。
   タグの一覧と V（= A、C7 の比率の値）は seq 17 のまま変えない。V は C7 の比率の値なので、ほかの数え方では
   「V を使った場合」（V）と「倍率の条件だけの場合」（m。V の代わりに V_TINY を使う）の両方を出す。C7 も両方出す。
   素朴な予測（naive.py の特徴量、ロジスティック回帰、リッジ 1）の成績を、2つの分け方で数え方ごとに出す。
2. 中心性の低下の確かめ
   T-119 の btw_change・deg_change・pr_change（同じ関数で計算し直す）を、タグ自身の報道量（直近3か月と12か月の比、
   12か月の水準）と12か月の網の次数で、学習の行だけで回帰して差し引き、残りが島と島でないもので違うか、
   素朴な予測に残りを足すと変わるかを見る。

試す形（下の定数）は本番の前にコミットし、その版で流す。全部並べ、選ばない・勧めない。

予言の時点のデータだけを使うこと：日の比率は T-117 の evaluate_tag（ReadGuard。入力は t-399〜t-1、判定は
t+1〜t+28）。グラフと報道量の月は、予言日を含む月より前の月だけ（es.check_network_before で毎回確かめる）。
区画の外の日の集計は開かない。

流し方（プロジェクトのルートで。TMPDIR は scratchpad の中に）
  .venv/bin/python -B src/stats/explore_denominator.py phase1 --store <日の集計> --cache-dir <新しいフォルダ>
  .venv/bin/python -B src/stats/explore_denominator.py phase2 --cache-dir <同じフォルダ> \
      --t117-cache <explore-t117-cache/run2> --out-dir <書き出す先>

Data: The GDELT Project (https://www.gdeltproject.org/). This project is not affiliated with or endorsed by the GDELT Project.
"""

import argparse
import array
import datetime
import fractions
import hashlib
import json
import math
import os
import sys
import time
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import explore_graph as eg  # noqa: E402

em = eg.em
es = eg.es
ei = eg.ei
naive = em.naive
counting = ei.counting

LABEL = "explore-denominator-t122-v1"
PHASE1_LABEL = "explore-denominator-phase1-v1"
MULTIPLIERS = em.MULTIPLIERS
HORIZON = em.HORIZON
F = fractions.Fraction

# ---------------------------------------------------------------------------
# 試す形（本番の前に書いた）
# ---------------------------------------------------------------------------
COUNTINGS = ("C7", "C1", "C3", "X")
COUNTING_JA = {"C7": "C7（正式）", "C1": "C1（v1_docs ÷ docs、封印済みの参考）",
               "C3": "C3（v2_docs ÷ docs、封印済みの参考）",
               "X": "X（v1_or_v2_docs ÷ docs、探索のための数え方。封印された候補ではない）"}
V_MODES = ("V", "m")
V_TINY = F(1, 10 ** 15)                  # 「倍率の条件だけ」のときに V の代わりに使う値（比率よりずっと小さい）
VARIANTS = tuple("%s_%s" % (c, vm) for c in COUNTINGS for vm in V_MODES)
BASE_VARIANT = "C7_V"                    # T-115 と同じ
SPLITS = {
    "A": (None, es.TRAIN_LAST, es.TEST_FIRST, None),            # 学習 〜2018-12-03、検証 2019-01-07〜
    "B": (None, em.INNER_TRAIN_LAST, em.INNER_VAL_FIRST, es.TRAIN_LAST),   # 学習 〜2017-12-04、確かめ 2018-01-08〜2018-12-03
}
TOP_WEEKS = 5
CENTRALITY = ("btw_change", "deg_change", "pr_change")
VOLUME_FEATURES = ("vol_ratio", "vol_level", "deg_level")


class DenomError(Exception):
    pass


# ---------------------------------------------------------------------------
# phase1：日の集計から、一覧のタグの v1・v2・v1_or_v2 の文書の数と、2つの分母を数える
# ---------------------------------------------------------------------------

_W = {}


def _init_p1(store, tags):
    _W["store"], _W["tags"] = store, tuple(tags)


def count_day(data, day, tags):
    """封印済みの counting.py の数え方で、その日の (v1, v2, v12 の一覧のタグごとの数, docs, C7 の分母)。"""
    summary = counting.parse_day(data, expect_day=day, expect_mode=counting.OFFICIAL_MODE)
    n1, d1 = counting.candidate_counts(summary, "C1")
    n3, d3 = counting.candidate_counts(summary, "C3")
    n7, d7 = counting.candidate_counts(summary, "C7")
    if d1 != d3:
        raise DenomError("C1 と C3 の分母（docs）が違う")
    return ([n1.get(t, 0) for t in tags], [n3.get(t, 0) for t in tags], [n7.get(t, 0) for t in tags], d1, d7)


def _day_task(args):
    day, file_name, sha = args
    if datetime.date.fromisoformat(day) >= ei.NEXT_BLOCK_START:
        raise DenomError("区画の外の日を読もうとした")
    if os.path.basename(file_name) != file_name:
        raise DenomError("ファイルの名前の形が違う")
    data = ei.read_nofollow(os.path.join(_W["store"], file_name))
    if hashlib.sha256(data).hexdigest() != sha:
        raise DenomError("%s：日の集計の sha256 が day の行と違う" % day)
    v1, v2, v12, docs, d7 = count_day(data, day, _W["tags"])
    return day, array.array("I", v1).tobytes(), array.array("I", v2).tobytes(), array.array("I", v12).tobytes(), \
        docs, d7


def phase1(root, store, cache_dir, workers, log):
    ctx = ei.load_context(root)
    if os.path.lexists(cache_dir):
        raise DenomError("キャッシュのフォルダが既にある。上書きしない")
    parent = os.path.dirname(os.path.abspath(cache_dir))
    es.check_free(parent)
    os.mkdir(cache_dir)
    tags, days, rows = ctx["tags"], ctx["days"], ctx["rows"]
    tasks = [(d.isoformat(), rows[d.isoformat()]["file_name"], rows[d.isoformat()]["sha256"]) for d in days]
    got = {}
    with es._pool(workers, _init_p1, (store, tags)) as pool:
        for k, r in enumerate(pool.imap(_day_task, tasks, chunksize=4), 1):
            got[r[0]] = r
            if k % 200 == 0:
                log("日の集計 %d / %d" % (k, len(tasks)))
    order = [d.isoformat() for d in days]
    bad = [d for d in order if got[d][5] != ctx["denom"][d]]
    if bad:
        raise DenomError("C7 の分母が順番4の一覧と違う日がある（最初は %s）" % bad[0])
    files = {}
    es.check_free(cache_dir)
    for name, k in (("v1.bin.z", 1), ("v2.bin.z", 2), ("v12.bin.z", 3)):
        blob = zlib.compress(b"".join(got[d][k] for d in order), 6)
        files[name] = {"sha256": es.write_new(os.path.join(cache_dir, name), blob), "bytes": len(blob)}
    meta = {"label": PHASE1_LABEL, "tags": tags, "days": order, "docs": [got[d][4] for d in order],
            "c7_totals": [got[d][5] for d in order], "missing": sorted(d.isoformat() for d in ctx["missing"]),
            "refs": ctx["refs"], "files": files, "itemsize": array.array("I").itemsize, "byteorder": sys.byteorder,
            "code": dict(ei._LOADED_SHA, **own_code_shas())}
    data = (json.dumps(meta, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")
    return es.write_new(os.path.join(cache_dir, "phase1.json"), data)


def own_code_shas():
    out = dict(es.own_code_shas())
    for rel, mod in (("src/stats/explore_models.py", em), ("src/stats/explore_graph.py", eg),
                     ("src/stats/explore_denominator.py", sys.modules[__name__])):
        with open(os.path.abspath(mod.__file__), "rb") as f:
            out[rel] = hashlib.sha256(f.read()).hexdigest()
    return out


def load_cache(cache_dir, ctx):
    raw = ei.read_nofollow(os.path.join(cache_dir, "phase1.json"))
    meta = json.loads(raw.decode("utf-8"))
    if meta.get("label") != PHASE1_LABEL:
        raise DenomError("キャッシュの版が違う")
    if meta["tags"] != ctx["tags"] or meta["refs"] != ctx["refs"] or \
            meta["days"] != [d.isoformat() for d in ctx["days"]] or \
            meta["missing"] != sorted(d.isoformat() for d in ctx["missing"]) or \
            meta["c7_totals"] != [ctx["denom"][d] for d in meta["days"]]:
        raise DenomError("キャッシュが封印の記録から読んだものと合わない")
    if meta["itemsize"] != array.array("I").itemsize or meta["byteorder"] != sys.byteorder:
        raise DenomError("キャッシュの数の形が違う")
    for name in ("v1.bin.z", "v2.bin.z", "v12.bin.z"):
        data = ei.read_nofollow(os.path.join(cache_dir, name))
        if hashlib.sha256(data).hexdigest() != meta["files"][name]["sha256"]:
            raise DenomError("キャッシュの %s の sha256 が違う" % name)
        a = array.array("I")
        a.frombytes(zlib.decompress(data))
        meta[name[:-6]] = a
    meta["phase1_sha256"] = hashlib.sha256(raw).hexdigest()
    return meta


# ---------------------------------------------------------------------------
# 数え方ごとの比率
# ---------------------------------------------------------------------------

def ratio_series(meta, counting_id):
    """数え方ごとのタグの日の比率（欠けた日は None）。"""
    n = len(meta["tags"])
    missing = set(meta["missing"])
    num = {"C7": meta["v12"], "C1": meta["v1"], "C3": meta["v2"], "X": meta["v12"]}[counting_id]
    den = meta["c7_totals"] if counting_id == "C7" else meta["docs"]
    series = [[] for _ in range(n)]
    for di, (d, tot) in enumerate(zip(meta["days"], den)):
        if d in missing:
            for s in series:
                s.append(None)
            continue
        if tot <= 0:
            raise DenomError("欠けた日でないのに分母が 0 の日がある（%s、%s）" % (d, counting_id))
        base = di * n
        for i in range(n):
            series[i].append(num[base + i] / tot)
    return series


def v_of(variant, v):
    return v if variant.endswith("_V") else V_TINY


def variant_rows(results, mondays, tags, v):
    """タグごとの evaluate_tag の結果から、対象の行（3つの倍率のどれも判定不能でないもの）を取り出す。
    戻り値：{(週の番号, タグの番号): (判定3つ, 素朴な予測の値)}"""
    out = {}
    for i, res in enumerate(results):
        for ti, (st, _b, _c, _m1, _m2, js, lv) in enumerate(res):
            if st != "target" or any(x is None for x in js):
                continue
            out[(ti, i)] = (js, lv)
    return out


def evaluate_variant(series, days, mondays, v, workers, log, label):
    results = [None] * len(series)
    with es._pool(workers, es._init_eval, (days, mondays, v)) as pool:
        for k, (j, res, _a, _b) in enumerate(pool.imap(es._eval_task, list(enumerate(series)), chunksize=8), 1):
            results[j] = [(st, b, c, None, None, js, lv) for st, b, c, _m1, _m2, js, lv in res]
            if k % 1000 == 0:
                log("%s タグ %d / %d" % (label, k, len(series)))
    return results


# ---------------------------------------------------------------------------
# 比べ方
# ---------------------------------------------------------------------------

def rates(rows, mondays):
    """{倍率: {"all": (対象, 島), 年: (対象, 島)}}"""
    out = {}
    for mi, m in enumerate(MULTIPLIERS):
        d = {}
        for (ti, _i), (js, _lv) in rows.items():
            for key in ("all", mondays[ti].year):
                a = d.setdefault(key, [0, 0])
                a[0] += 1
                a[1] += 1 if js[mi] else 0
        out[m] = d
    return out


def overlap(base, other, mondays):
    """BASE と other の、倍率ごとの重なり。両方で対象の行について一致率と片方だけの島の数、週ごとの食い違いの数。"""
    out = {}
    both = sorted(set(base) & set(other))
    for mi, m in enumerate(MULTIPLIERS):
        agree = only_b = only_o = both_isl = 0
        weeks = {}
        for key in both:
            a = base[key][0][mi]
            b = other[key][0][mi]
            if a == b:
                agree += 1
                both_isl += 1 if a else 0
            else:
                if a:
                    only_b += 1
                else:
                    only_o += 1
                weeks[key[0]] = weeks.get(key[0], 0) + 1
        top = sorted(weeks.items(), key=lambda x: (-x[1], x[0]))[:TOP_WEEKS]
        out[m] = {"targets_base": len(base), "targets_other": len(other), "targets_both": len(both),
                  "agree": agree, "both_islands": both_isl, "only_base": only_b, "only_other": only_o,
                  "top_weeks": [(mondays[w].isoformat(), c) for w, c in top]}
    return out


def split_rows(keys, mondays, split):
    _a, train_last, test_first, test_last = SPLITS[split]
    tr = [k for k in keys if mondays[k[0]] <= train_last]
    te = [k for k in keys if mondays[k[0]] >= test_first and (test_last is None or mondays[k[0]] <= test_last)]
    return tr, te


def make_table(rows, keys, mondays, tags, m, v, extra=None):
    """em.metrics と em.fit_logistic_cols のための表（keys の順）。"""
    mi = MULTIPLIERS.index(m)
    tb = {"t": [mondays[k[0]] for k in keys], "tag": [tags[k[1]] for k in keys], "week": [k[0] for k in keys],
          "y%d" % m: array.array("b", [1 if rows[k][0][mi] else 0 for k in keys])}
    feats = [naive.features_from_levels(rows[k][1], m, v) for k in keys]
    for j in range(len(naive.FEATURES)):
        tb["naive%d_%d" % (m, j)] = array.array("d", [f[j] for f in feats])
    for name, vals in (extra or {}).items():
        tb[name] = array.array("d", [vals[k] for k in keys])
    return tb


def fit_eval(tb, m, cols, train_idx, test_idx, ref_probs=None):
    tr = sorted(train_idx, key=lambda r: (tb["t"][r], tb["tag"][r]))
    y = [tb["y%d" % m][r] for r in tr]
    fit = em.fit_logistic_cols([em.column_values(tb, c, tr) for c in cols], y, em.FIXED_LAMBDA)
    probs = em.predict_cols([em.column_values(tb, c, test_idx) for c in cols], fit["coef"])
    weeks = sorted({tb["week"][r] for r in test_idx})
    return fit, probs, em.metrics(tb, m, test_idx, probs, ref_probs, weeks)


def naive_cols(m):
    return [em.naive_col(m, f) for f in naive.FEATURES]


# ---------------------------------------------------------------------------
# 中心性の確かめ
# ---------------------------------------------------------------------------

def ols(X, y):
    """最小二乗（正規方程式、naive._solve）。X は行の並び（先頭の列は 1）。"""
    k = len(X[0])
    A = [[0.0] * k for _ in range(k)]
    b = [0.0] * k
    for xi, yi in zip(X, y):
        for a in range(k):
            b[a] += xi[a] * yi
            for c in range(k):
                A[a][c] += xi[a] * xi[c]
    return naive._solve(A, b)


def r_squared(X, y, coef):
    mean = sum(y) / len(y)
    ss_tot = sum((v - mean) ** 2 for v in y)
    ss_res = sum((v - sum(a * c for a, c in zip(x, coef))) ** 2 for x, v in zip(X, y))
    return 1.0 - ss_res / ss_tot if ss_tot > 0 else None


def volume_features(i, months_base, months_rec3, month_v1, deg_b):
    """自分の報道量（V1 の文書の数）：直近3か月と12か月（4分の1にして3か月に揃える）の比の log、12か月の水準の log、
    12か月の網の次数の log1p。"""
    b = sum(month_v1[m][i] for m in months_base)
    r = sum(month_v1[m][i] for m in months_rec3)
    return {"vol_ratio": math.log((r + 1.0) / (b / 4.0 + 1.0)), "vol_level": math.log(b + 1.0),
            "deg_level": math.log1p(deg_b)}


def centrality_rows(keys, graphs, mondays, month_v1, n):
    """対象の行ごとの、T-119 と同じ中心性の変化（btw_change・deg_change・pr_change）と、報道量と次数の値。"""
    out = {c: {} for c in CENTRALITY + VOLUME_FEATURES}
    for (ti, i) in keys:
        t = mondays[ti]
        mk = es.month_key(t)
        g = graphs[mk]
        months = es.network_months(t, eg.GRAPH_WINDOW, "M")
        if g["months"] != months:
            raise DenomError("グラフの月が予言日の月と合わない")
        es.check_network_before(t, months)
        out["btw_change"][(ti, i)] = math.log((g["btw_r"][i] + eg.BTW_EPS) / (g["btw_b"][i] + eg.BTW_EPS))
        out["deg_change"][(ti, i)] = math.log((g["deg_r"][i] + 1) / (g["deg_b"][i] + 1))
        out["pr_change"][(ti, i)] = math.log(g["pr_r"][i] / g["pr_b"][i])
        vf = volume_features(i, months, months[-eg.RECENT_MONTHS:], month_v1, g["deg_b"][i])
        for k, x in vf.items():
            out[k][(ti, i)] = x
    return out


def residualize(vals, train_keys, all_keys):
    """中心性の列ごとに、学習の行だけで [1, 報道量の比, 水準, 次数] に回帰し、全部の行の残りを返す。"""
    out, info = {}, {}
    for c in CENTRALITY:
        X = [[1.0] + [vals[f][k] for f in VOLUME_FEATURES] for k in train_keys]
        y = [vals[c][k] for k in train_keys]
        coef = ols(X, y)
        info[c] = {"coef": coef, "r2": r_squared(X, y, coef)}
        out[c + "_resid"] = {k: vals[c][k] - (coef[0] + sum(b * vals[f][k] for b, f in zip(coef[1:], VOLUME_FEATURES)))
                             for k in all_keys}
    return out, info


def naive_scores(var, rows, mondays, tags, v):
    """数え方ごとの素朴な予測の成績：{(数え方, 倍率, 分け方): 指標}。"""
    out = {}
    keys = sorted(rows)
    idx = {k: r for r, k in enumerate(keys)}
    for m in MULTIPLIERS:
        tb = make_table(rows, keys, mondays, tags, m, v)
        for sp in SPLITS:
            tr, te = split_rows(keys, mondays, sp)
            _fit, _p, x = fit_eval(tb, m, naive_cols(m), [idx[k] for k in tr], [idx[k] for k in te])
            out[(var, m, sp)] = dict(x, n_train=len(tr), pos_train=sum(tb["y%d" % m][idx[k]] for k in tr))
    return out


def centrality_eval(base, vals, mondays, tags, v):
    """分け方ごとに、学習の行だけで回帰して残りを作り、素朴な予測に足したときと、平均の違いを出す。"""
    keys = sorted(base)
    idx = {k: r for r, k in enumerate(keys)}
    cent = {}
    for sp in SPLITS:
        tr, te = split_rows(keys, mondays, sp)
        resid, info = residualize(vals, tr, keys)
        extra = {c: vals[c] for c in CENTRALITY}
        extra.update(resid)
        for m in MULTIPLIERS:
            tb = make_table(base, keys, mondays, tags, m, v, extra)
            tri = [idx[k] for k in tr]
            tei = [idx[k] for k in te]
            _f0, p0, x0 = fit_eval(tb, m, naive_cols(m), tri, tei)
            _f1, _p1, x1 = fit_eval(tb, m, naive_cols(m) + list(CENTRALITY), tri, tei, p0)
            _f2, _p2, x2 = fit_eval(tb, m, naive_cols(m) + [c + "_resid" for c in CENTRALITY], tri, tei, p0)
            means = {}
            for c in CENTRALITY:
                for kind, col in (("raw", c), ("resid", c + "_resid")):
                    for part, ii in (("train", tri), ("test", tei)):
                        pos = [tb[col][r] for r in ii if tb["y%d" % m][r]]
                        neg = [tb[col][r] for r in ii if not tb["y%d" % m][r]]
                        means[(c, kind, part)] = (sum(pos) / len(pos) if pos else None,
                                                  sum(neg) / len(neg) if neg else None, len(pos), len(neg))
            cent[(sp, m)] = {"naive": x0, "raw": x1, "resid": x2, "means": means, "ols": info}
    return cent


# ---------------------------------------------------------------------------
# phase2
# ---------------------------------------------------------------------------

def phase2(root, cache_dir, t117_cache, out_dir, workers, log):
    ctx = ei.load_context(root)
    meta = load_cache(cache_dir, ctx)
    m117 = es.load_cache(t117_cache, ctx)
    checks = {"v12_equals_t117_c7": meta["v12"] == m117["c7"], "v1_equals_t117_v1": meta["v1"] == m117["v1"],
              "docs_equals_t117_docs": meta["docs"] == m117["docs"]}
    if not all(checks.values()):
        raise DenomError("T-117 のキャッシュと数が合わない：%r" % checks)
    tags, v = meta["tags"], ctx["v"]
    n = len(tags)
    days = ctx["days"]
    mondays = ei.prediction_mondays()
    log("キャッシュを読んだ")
    rows = {}
    lo_hi = {}
    for c in COUNTINGS:
        series = ratio_series(meta, c)
        for vm in V_MODES:
            var = "%s_%s" % (c, vm)
            res = evaluate_variant(series, days, mondays, v_of(var, v), workers, log, var)
            rows[var] = variant_rows(res, mondays, tags, v_of(var, v))
            log("%s：対象の行 %d" % (var, len(rows[var])))
        del series
    naive_res = {}
    for var in VARIANTS:
        naive_res.update(naive_scores(var, rows[var], mondays, tags, v_of(var, v)))
        log("素朴な予測 %s" % var)
    # 中心性の確かめ（BASE_VARIANT の行）
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
    pred_months = sorted({es.month_key(t) for t in mondays})
    small = {"tags": tags, "pair_files": m117["pair_files"], "month_v1": month_v1, "month_docs": month_docs}
    graphs = {}
    with es._pool(workers, eg._init_graph, (t117_cache, small)) as pool:
        for g in pool.imap(eg._graph_task, pred_months):
            graphs[g["mk"]] = g
    log("グラフを作った")
    base = rows[BASE_VARIANT]
    vals = centrality_rows(sorted(base), graphs, mondays, month_v1, n)
    cent = centrality_eval(base, vals, mondays, tags, v)
    log("中心性の確かめ")
    files = build_outputs(meta, ctx, rows, mondays, naive_res, cent, checks)
    return write_outputs(out_dir, files)


# ---------------------------------------------------------------------------
# 出力
# ---------------------------------------------------------------------------

OUT_NAMES = ("rates.tsv", "overlap.tsv", "naive.tsv", "centrality.tsv", "centrality_ols.tsv", "run.json",
             "summary.md")


def write_outputs(out_dir, files):
    if sorted(files) != sorted(OUT_NAMES):
        raise DenomError("出力の名前が決めた一覧と違う")
    os.makedirs(out_dir, exist_ok=True)
    for name in OUT_NAMES:
        if os.path.lexists(os.path.join(out_dir, name)):
            raise DenomError("書き出す先に同じ名前のファイル（%s）がある。上書きしない" % name)
    return {name: es.write_new(os.path.join(out_dir, name), files[name]) for name in OUT_NAMES}


f6 = es.f6


def pct(a, b):
    return "-" if not b else "%.2f" % (100.0 * a / b)


def build_outputs(meta, ctx, rows, mondays, naive_res, cent, checks):
    years = sorted({t.year for t in mondays})
    rate_rows = []
    rt = {var: rates(rows[var], mondays) for var in VARIANTS}
    for var in VARIANTS:
        for m in MULTIPLIERS:
            for key in ["all"] + years:
                tg, isl = rt[var][m].get(key, [0, 0])
                rate_rows.append((var, m, HORIZON, key, tg, isl, pct(isl, tg)))
    ov = {var: overlap(rows[BASE_VARIANT], rows[var], mondays) for var in VARIANTS if var != BASE_VARIANT}
    ov_rows = []
    for var in VARIANTS:
        if var == BASE_VARIANT:
            continue
        for m in MULTIPLIERS:
            o = ov[var][m]
            ov_rows.append((BASE_VARIANT, var, m, o["targets_base"], o["targets_other"], o["targets_both"], o["agree"],
                            pct(o["agree"], o["targets_both"]), o["both_islands"], o["only_base"], o["only_other"],
                            ";".join("%s:%d" % w for w in o["top_weeks"])))
    nv_rows = []
    for var in VARIANTS:
        for m in MULTIPLIERS:
            for sp in SPLITS:
                x = naive_res[(var, m, sp)]
                nv_rows.append((var, m, sp, x["n_train"], x["pos_train"], x["n"], x["pos"], f6(x["logloss"]),
                                f6(x["auc"]), x["topk"]))
    c_rows, o_rows = [], []
    for (sp, m), x in sorted(cent.items()):
        for kind in ("naive", "raw", "resid"):
            y = x[kind]
            c_rows.append((sp, m, "model", kind, y["n"], y["pos"], f6(y["logloss"]), f6(y["auc"]), y["topk"],
                           f6(y.get("d_logloss")), f6(y["d_ll_ci"][0]) if "d_ll_ci" in y else "-",
                           f6(y["d_ll_ci"][1]) if "d_ll_ci" in y else "-", y.get("d_topk", "-")))
        for (c, kind, part), (mp, mn, npos, nneg) in sorted(x["means"].items()):
            c_rows.append((sp, m, "mean", "%s_%s_%s" % (c, kind, part), npos, nneg, f6(mp), f6(mn), "-", "-", "-", "-",
                           "-"))
        if m == MULTIPLIERS[0]:
            for c, info in x["ols"].items():
                o_rows.append((sp, c, f6(info["r2"]), *[f6(b) for b in info["coef"]]))
    files = {
        "rates.tsv": ei.tsv(("variant", "multiplier", "horizon_days", "year", "targets", "islands", "rate_percent"),
                            rate_rows),
        "overlap.tsv": ei.tsv(("base", "variant", "multiplier", "targets_base", "targets_variant", "targets_both",
                               "agree", "agree_percent", "islands_both", "islands_only_base", "islands_only_variant",
                               "top_weeks_disagree"), ov_rows),
        "naive.tsv": ei.tsv(("variant", "multiplier", "split", "n_train", "islands_train", "n_test", "islands_test",
                             "logloss", "auc", "top10_hits"), nv_rows),
        "centrality.tsv": ei.tsv(("split", "multiplier", "row", "name", "n_or_islands", "islands_or_non",
                                  "logloss_or_mean_islands", "auc_or_mean_non", "top10_hits", "d_logloss_vs_naive",
                                  "d_ll_ci4w_lo", "d_ll_ci4w_hi", "d_top10_vs_naive"), c_rows),
        "centrality_ols.tsv": ei.tsv(("split", "centrality", "r2_train", "intercept") + VOLUME_FEATURES, o_rows),
    }
    code = dict(ei._LOADED_SHA, **own_code_shas())
    run = {"label": LABEL, "code": code, "python": sys.version.split()[0], "phase1_sha256": meta["phase1_sha256"],
           "refs": ctx["refs"], "v": "%d/%d" % (ctx["v"].numerator, ctx["v"].denominator),
           "v_tiny": "%d/%d" % (V_TINY.numerator, V_TINY.denominator), "checks_vs_t117_cache": checks,
           "variants": VARIANTS, "splits": {k: [str(x) for x in s] for k, s in SPLITS.items()},
           "centrality": CENTRALITY, "volume_features": VOLUME_FEATURES,
           "citation": [ei.CITATION_EN, ei.CITATION_JA]}
    files["run.json"] = (json.dumps(run, ensure_ascii=False, sort_keys=True, indent=1) + "\n").encode("utf-8")
    files["summary.md"] = summary_md(run, rt, ov, naive_res, cent, years)
    for name, data in files.items():
        ei.check_public(name, data)
    return files


def summary_md(run, rt, ov, naive_res, cent, years):
    L = []
    a = L.append
    md = ei.md_table
    a("# 分母の感度分析と、中心性の低下の確かめ（T-122、手法を作る期間）")
    a("")
    a("この文書は `src/stats/explore_denominator.py` が出力したもので、手で書き足していない。数え方・モデル・閾値は、ここでは"
      "決めない（決定はオーナー）。全部並べ、選ばない・勧めない。テーマの名前は載せていない。")
    a("")
    a("## 0. 何をどう比べたか")
    a("- 予言日・対象の決め方・判定は T-115 と同じ（232 回の月曜、一度跳ねたタグの扱いあり、判定期間 %d 日、倍率 %s）。"
      "タグの一覧と V（= A = %s）は seq 17 のまま。" % (HORIZON, "・".join(str(m) for m in MULTIPLIERS), run["v"]))
    a("- 数え方（数える組と欠けた日の扱いは counting.py と candidates.md のまま。欠けた日は seq 15 の 48 日）：")
    for c in COUNTINGS:
        a("  - %s" % COUNTING_JA[c])
    a("- V は C7 の比率の値なので、ほかの数え方では大きさの意味が違う。そのため、どの数え方でも「V を使った場合」（_V）と"
      "「倍率の条件だけの場合」（_m。V の代わりに %s を使う）を並べる。C7_V が T-115 と同じ。" % run["v_tiny"])
    a("- 日の集計から数え直した C7 の分子・V1 の文書の数・記事の数は、T-117 のキャッシュとすべての日で一致した（%s）。" % (
        "、".join("%s=%s" % kv for kv in sorted(run["checks_vs_t117_cache"].items()))))
    a("- 素朴な予測：naive.py の特徴量のロジスティック回帰（リッジ 1）。分け方 A は T-117 と同じ（学習 〜%s、検証 %s〜）、"
      "分け方 B は参考（学習 〜%s、確かめ %s〜%s）。数え方ごとに対象と島が違うので、成績は同じ行どうしの比べ方ではない。" % (
          es.TRAIN_LAST, es.TEST_FIRST, em.INNER_TRAIN_LAST, em.INNER_VAL_FIRST, es.TRAIN_LAST))
    a("")
    a("## 1. 数え方ごとの対象と島")
    a("")
    for m in MULTIPLIERS:
        a("### 倍率 %d" % m)
        a("")
        hdr = ["数え方", "対象", "島", "割合（%）"] + ["%d年（%%）" % y for y in years]
        body = []
        for var in VARIANTS:
            d = rt[var][m]
            body.append([var, d["all"][0], d["all"][1], pct(d["all"][1], d["all"][0])]
                        + [pct(d.get(y, [0, 0])[1], d.get(y, [0, 0])[0]) for y in years])
        a(md(hdr, body))
        a("")
    a("## 2. C7_V との重なり（両方で対象の行）")
    a("")
    for m in MULTIPLIERS:
        a("### 倍率 %d" % m)
        a("")
        a(md(["数え方", "対象（C7_V）", "対象（この数え方）", "両方で対象", "島の判定の一致率（%）", "両方で島",
              "C7_V だけで島", "この数え方だけで島", "食い違いの多い週（予言日:行の数）"],
             [(var, ov[var][m]["targets_base"], ov[var][m]["targets_other"], ov[var][m]["targets_both"],
               pct(ov[var][m]["agree"], ov[var][m]["targets_both"]), ov[var][m]["both_islands"],
               ov[var][m]["only_base"], ov[var][m]["only_other"],
               "、".join("%s:%d" % w for w in ov[var][m]["top_weeks"])) for var in VARIANTS if var != BASE_VARIANT]))
        a("")
    a("## 3. 数え方ごとの素朴な予測の成績")
    a("")
    for sp in SPLITS:
        a("### 分け方 %s" % sp)
        a("")
        a(md(["数え方", "倍率", "学習の行", "学習の島", "検証の行", "検証の島", "対数損失", "AUC", "上位10の島"],
             [(var, m, naive_res[(var, m, sp)]["n_train"], naive_res[(var, m, sp)]["pos_train"],
               naive_res[(var, m, sp)]["n"], naive_res[(var, m, sp)]["pos"], f6(naive_res[(var, m, sp)]["logloss"]),
               f6(naive_res[(var, m, sp)]["auc"]), naive_res[(var, m, sp)]["topk"])
              for var in VARIANTS for m in MULTIPLIERS]))
        a("")
    a("## 4. 中心性の低下の確かめ（C7_V の対象の行）")
    a("")
    a("T-119 の btw_change・deg_change・pr_change を、同じ関数で計算し直した。それぞれを、自分の報道量（V1 の文書の数）の"
      "直近3か月と12か月の比の log（vol_ratio）、12か月の水準の log（vol_level）、12か月の網の次数の log1p（deg_level）に、"
      "学習の行だけで最小二乗で回帰し、差し引いた残り（_resid）を作った。")
    a("")
    for sp in SPLITS:
        a("### 分け方 %s：回帰の当てはまり（学習の行）" % sp)
        a("")
        x = cent[(sp, MULTIPLIERS[0])]["ols"]
        a(md(["中心性", "R²", "切片"] + list(VOLUME_FEATURES),
             [(c, f6(x[c]["r2"]), *[f6(b) for b in x[c]["coef"]]) for c in CENTRALITY]))
        a("")
        a("### 分け方 %s：島と島でないものの平均（検証の行）" % sp)
        a("")
        body = []
        for m in MULTIPLIERS:
            for c in CENTRALITY:
                r = cent[(sp, m)]["means"][(c, "raw", "test")]
                s = cent[(sp, m)]["means"][(c, "resid", "test")]
                body.append((m, c, f6(r[0]), f6(r[1]), f6(s[0]), f6(s[1]), r[2], r[3]))
        a(md(["倍率", "中心性", "そのままの平均（島）", "そのままの平均（島でない）", "残りの平均（島）", "残りの平均（島でない）",
              "島の行", "島でない行"], body))
        a("")
        a("### 分け方 %s：素朴な予測に足したとき（検証）" % sp)
        a("")
        body = []
        for m in MULTIPLIERS:
            x = cent[(sp, m)]
            nv = x["naive"]["logloss"]
            for kind, lab in (("naive", "素朴な予測だけ"), ("raw", "＋中心性（そのまま）"), ("resid", "＋中心性（残り）")):
                y = x[kind]
                body.append((m, lab, f6(y["logloss"]), f6(y["auc"]), y["topk"],
                             "-" if kind == "naive" else "%s（%+.2f%%）" % (f6(y["d_logloss"]), 100 * y["d_logloss"] / nv),
                             "-" if kind == "naive" else "%s〜%s" % (f6(y["d_ll_ci"][0]), f6(y["d_ll_ci"][1])),
                             "-" if kind == "naive" else y["d_topk"]))
        a(md(["倍率", "モデル", "対数損失", "AUC", "上位10の島", "素朴な予測との差（割合）", "差の範囲（4週束ね）", "上位10の差"],
             body))
        a("")
    a("- 比べたモデルは、分け方ごとに倍率3 × 2（そのまま・残り）で6、計12。出した差の範囲も12で、多重比較の補正をしていない。"
      "4週の束どうしは独立でない（判定期間 %d 日が隣の束に重なる）。範囲が0を含まないことは、効くことの確かめにはならない。" % HORIZON)
    a("")
    a("## 5. 限界")
    a("- 検証の期間の再利用：分け方 A の検証（2019〜2020年）は、T-117・T-118・T-119 で既に何度も見た期間の再利用で、"
      "未見のデータでの確かめにはならない。分け方 B の確かめ（2018年）も、T-118 で強さを選ぶのに使った期間である。")
    a("- 一覧と V の先読み：タグの一覧と V は、手法を作る期間の区画全体のデータで決まった（seq 17）。一覧は C7 で決めたので、"
      "ほかの数え方では一覧の入り方も違いうるが、ここでは一覧を変えていない。")
    a("- V の大きさ：V は C7 の比率の値で、ほかの数え方の比率とは大きさの意味が違う。_m は V の条件を外した場合で、"
      "普段の水準が 0 のタグは1件の報道でも島になりうる。")
    a("- X は探索のための数え方で、封印された候補ではない。")
    a("- 除外の規則の漏れ（民族・人物の姓・宗教・犯罪・紛争・政治に当たる名前のテーマが一覧に残っている。オーナーの決定 2026-10-16、"
      "(a) このまま進める）。要約にはテーマの名前を載せていない。")
    a("- WB のテーマの段のような上昇（T-116 の要約 6章）は、どの数え方にも入る。")
    a("- 中心性の確かめは、報道量と次数の一次の回帰で差し引いたもので、ほかの形（非線形・交互作用）で説明できる分は残りに入る。"
      "媒介中心性は始点256個の近似（T-119 と同じ）。")
    a("")
    a("## 6. 再計算")
    a("```")
    a(".venv/bin/python -B src/stats/explore_denominator.py phase1 --store <日の集計> --cache-dir <新しいフォルダ>")
    a(".venv/bin/python -B src/stats/explore_denominator.py phase2 --cache-dir <同じフォルダ> --t117-cache <explore-t117-cache/run2> "
      "--out-dir <書き出す先>")
    a("```")
    for k in sorted(run["code"]):
        a("- %s：sha256 %s" % (k, run["code"][k]))
    a("- キャッシュ phase1.json：sha256 %s" % run["phase1_sha256"])
    a("")
    a("## 引用")
    a(ei.CITATION_EN)
    a("")
    a(ei.CITATION_JA)
    out = "\n".join(L) + "\n"
    if "**" in out:
        raise DenomError("要約に太字の印がある（使わない）")
    return out.encode("utf-8")


def main(argv=None):
    p = argparse.ArgumentParser(description="T-122 分母の感度分析と中心性の低下の確かめ")
    sub = p.add_subparsers(dest="cmd", required=True)
    p1 = sub.add_parser("phase1")
    p1.add_argument("--store", required=True)
    p1.add_argument("--cache-dir", required=True)
    p1.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 1))
    p2 = sub.add_parser("phase2")
    p2.add_argument("--cache-dir", required=True)
    p2.add_argument("--t117-cache", required=True)
    p2.add_argument("--out-dir", required=True)
    p2.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 1))
    a = p.parse_args(argv)
    t0 = time.time()

    def log(msg):
        sys.stderr.write("[%8.1f s] %s\n" % (time.time() - t0, msg))
        sys.stderr.flush()
    try:
        if a.cmd == "phase1":
            print("%s  phase1.json" % phase1(ei.PROJECT, a.store, a.cache_dir, a.workers, log))
        else:
            shas = phase2(ei.PROJECT, a.cache_dir, a.t117_cache, a.out_dir, a.workers, log)
            for name in OUT_NAMES:
                print("%s  %s" % (shas[name], name))
    except (DenomError, eg.GraphError, em.ModelError, es.SignalError, ei.ExploreError) as e:
        sys.stderr.write("止まった：%s\n" % e)
        return 1
    log("終わり")
    return 0


if __name__ == "__main__":
    sys.exit(main())
