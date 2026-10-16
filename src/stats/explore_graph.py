#!/usr/bin/env python3
"""T-119：グラフ理論によるネットワーク分析の探索（T-117・T-118 の続き）。

T-117 の月ごとの共起の網（P1、一覧のタグどうし。explore-t117-cache/run2 を読むだけで作り直さない）を、グラフとして
見る。予言日 t には、t を含む月より前の月だけで作ったグラフを使う。T-117 と同じ予言日・対象・判定・学習と検証の分け方・
倍率 2・4・8 × 判定期間 28 日で、グラフの見方から作った値を素朴な予測に足したときに、島に先行するかを探る。
結果を並べるだけで、選ばない・勧めない。

見方と作り方（検証の期間の結果を見る前にこのファイルに書き、コミットしてから本番を流す）
  網：月 M（予言日 t を含む月）の前の12か月（M-12〜M-1）の組の文書の数の和（T-117 の w12m と同じ）。
      グラフは、lift の上位10（lift10）または n_ij/n_i の上位30（share30）の隣を、双方向にまとめた無向グラフ
      （組の文書の数が MIN_PAIR_DOCS 以上の相手だけ。T-117 と同じ es.neighbors_from_matrix）。
  1 新しい結びつき：直前の月（M-1）に NEW_TIE_RECENT_MIN 件以上の組のある相手のうち、その前の12か月（M-13〜M-2）の
      組が NEW_TIE_BASE_MAX 件未満の相手。その割合（nt_frac）、数の log1p（nt_lognew）、直前の月の組の文書の数のうちの割合（nt_weight）。
  2 群れ：重み付きのラベル伝播（順番は番号の順、同じ重みなら小さいラベル、最大 LPA_MAX_SWEEPS 回）。lift10 と share30 の
      グラフの2通り。同じ群れの他のタグの上がり（comm_rise）、群れの大きさの log（comm_logsize）、前の月の群れとの入れ替わり
      （1 − Jaccard、comm_change）。群れの数・大きさ・月をまたいだ安定さ（NMI）も並べる（採点計画の材料。決めない）。
  3 橋渡しの位置：媒介中心性（重みなし、lift10 のグラフ）。始点を BTW_SOURCES 個だけ乱数の種 BTW_SEED で選ぶ近似
      （Brandes の方法）。12か月のグラフ（btw_base）と、直近3か月（M-3〜M-1）のグラフとの比（btw_change）。
  4 2歩先の隣：1歩の隣（lift10、重み n_ij/n_i）の上がりの重み付き平均（hop1）と、2歩先（1歩の隣とその人自身を除く、
      重みは2つの重みの積）の上がりの重み付き平均（hop2）。
  5 中心性の変化：直近3か月の lift10 グラフと12か月の lift10 グラフでの、次数の比（deg_change）と PageRank の比（pr_change）。

予言の時点のデータだけを使うこと
- 日の比率と素朴な予測は T-117 の関数（ReadGuard。入力は t-399〜t-1、判定は t+1〜t+28）。
- グラフは月 M より前の月だけ。予言日 t ごとに、使う月の最後の日 < t を確かめ（es.check_network_before）、外れれば止まる。
- 区画の外は読まない（キャッシュは区画の日だけ）。

流し方（プロジェクトのルートで。TMPDIR は scratchpad の中に）
  .venv/bin/python -B src/stats/explore_graph.py --cache-dir <explore-t117-cache/run2> --out-dir <書き出す先>

Data: The GDELT Project (https://www.gdeltproject.org/). This project is not affiliated with or endorsed by the GDELT Project.
"""

import argparse
import array
import collections
import datetime
import hashlib
import json
import math
import operator
import os
import random
import statistics
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import explore_models as em  # noqa: E402

es = em.es
ei = em.ei
naive = em.naive
candidates = em.candidates

LABEL = "explore-graph-t119-v1"
MULTIPLIERS = em.MULTIPLIERS
HORIZON = em.HORIZON

# ---------------------------------------------------------------------------
# 試す形（検証の期間の結果を見る前に書いた）
# ---------------------------------------------------------------------------
GRAPH_WINDOW = 12
RECENT_MONTHS = 3
NEW_TIE_RECENT_MIN = 5
NEW_TIE_BASE_MAX = es.MIN_PAIR_DOCS          # 20
LPA_MAX_SWEEPS = 30
BTW_SOURCES = 256
BTW_SEED = 119
BTW_EPS = 1e-6
PR_DAMPING = 0.85
PR_ITERS = 50
COMM_VARIANTS = ("lift10", "share30")

GROUPS = {
    "A_newtie": ("nt_frac", "nt_lognew", "nt_weight", "nt_miss"),
    "B_comm_lift10": ("comm_rise_lift10", "comm_logsize_lift10", "comm_change_lift10", "comm_miss_lift10"),
    "B_comm_share30": ("comm_rise_share30", "comm_logsize_share30", "comm_change_share30", "comm_miss_share30"),
    "C_btw": ("btw_base", "btw_change"),
    "D_hop1": ("hop1_rise", "hop1_miss"),
    "D_hop2": ("hop2_rise", "hop2_miss"),
    "D_hop12": ("hop1_rise", "hop1_miss", "hop2_rise", "hop2_miss"),
    "E_deg": ("deg_change",),
    "E_pr": ("pr_change",),
}
ALL_GROUP = ("A_newtie", "B_comm_lift10", "C_btw", "D_hop12", "E_deg", "E_pr")
GRAPH_COLUMNS = tuple(sorted({c for cs in GROUPS.values() for c in cs}))
ALL_COLUMNS = tuple(sorted({c for g in ALL_GROUP for c in GROUPS[g]}))
# (名前, 種類, 列, 比べる相手)
MODELS = tuple([("naive", "logit", (), None)]
               + [(g, "logit", GROUPS[g], "naive") for g in GROUPS]
               + [("all", "logit", ALL_COLUMNS, "naive"),
                  ("gbdt_naive", "gbdt", (), "naive"),
                  ("gbdt_graph", "gbdt", ALL_COLUMNS, "gbdt_naive")])


class GraphError(Exception):
    pass


# ---------------------------------------------------------------------------
# グラフの計算（標準の Python だけ）
# ---------------------------------------------------------------------------

def union_graph(nbrs, mat, n):
    """隣の一覧（Nbrs）を双方向にまとめた無向グラフ。重みは行列の n_ij。戻り値：[{j: n_ij}]。"""
    adj = [dict() for _ in range(n)]
    for i in range(n):
        for j, _w, _s in nbrs.get(i):
            x = mat[i * n + j]
            adj[i][j] = x
            adj[j][i] = x
    return adj


def label_propagation(adj, max_sweeps=LPA_MAX_SWEEPS):
    """重み付きのラベル伝播。番号の順に1つずつ更新し、隣のラベルの重みの和が最大のもの（同じなら小さいラベル）にする。
    変わるものが無くなるか max_sweeps 回で止める。ラベルは群れの中の最小の番号に付け直す。戻り値：(ラベル, 回数)。"""
    n = len(adj)
    lab = list(range(n))
    sweeps = 0
    for sweeps in range(1, max_sweeps + 1):
        changed = 0
        for i in range(n):
            if not adj[i]:
                continue
            tally = {}
            for j, w in adj[i].items():
                tally[lab[j]] = tally.get(lab[j], 0) + w
            best = min(tally.items(), key=lambda x: (-x[1], x[0]))[0]
            if best != lab[i]:
                lab[i] = best
                changed += 1
        if changed == 0:
            break
    first = {}
    for i, l in enumerate(lab):
        first.setdefault(l, i)
    return [first[l] for l in lab], sweeps


def pagerank(adj, damping=PR_DAMPING, iters=PR_ITERS):
    """重み付き PageRank（行き先を出ていく重みで割る。行き先の無い点の分は全体に均等に配る）。固定の回数だけ回す。"""
    n = len(adj)
    pr = [1.0 / n] * n
    out = [sum(a.values()) for a in adj]
    for _ in range(iters):
        nxt = [0.0] * n
        dangling = 0.0
        for i in range(n):
            if out[i] <= 0:
                dangling += pr[i]
                continue
            share = pr[i] / out[i]
            for j, w in adj[i].items():
                nxt[j] += share * w
        base = (1.0 - damping) / n + damping * dangling / n
        pr = [base + damping * x for x in nxt]
    return pr


def betweenness_approx(adj, sources):
    """重みなしの媒介中心性（Brandes の方法）を、始点 sources だけで足し、n / len(sources) を掛けた近似。無向なので2で割る。"""
    n = len(adj)
    bc = [0.0] * n
    nbr = [sorted(a) for a in adj]
    for s in sources:
        stack = []
        pred = [[] for _ in range(n)]
        sigma = [0] * n
        sigma[s] = 1
        dist = [-1] * n
        dist[s] = 0
        q = collections.deque([s])
        while q:
            v = q.popleft()
            stack.append(v)
            for w in nbr[v]:
                if dist[w] < 0:
                    dist[w] = dist[v] + 1
                    q.append(w)
                if dist[w] == dist[v] + 1:
                    sigma[w] += sigma[v]
                    pred[w].append(v)
        delta = [0.0] * n
        while stack:
            w = stack.pop()
            for v in pred[w]:
                delta[v] += sigma[v] / sigma[w] * (1.0 + delta[w])
            if w != s:
                bc[w] += delta[w]
    scale = n / len(sources) / 2.0
    norm = (n - 1) * (n - 2) / 2.0 if n > 2 else 1.0
    return [x * scale / norm for x in bc]


def new_ties(recent1, prev, n):
    """新しい結びつき：(nt_frac, nt_lognew, nt_weight) の一覧。直前の月に組が無いタグは (None, 0.0, None)。"""
    out = []
    for i in range(n):
        r1 = recent1[i * n:(i + 1) * n]
        rp = prev[i * n:(i + 1) * n]
        part = [(j, x) for j, x in enumerate(r1) if x >= NEW_TIE_RECENT_MIN and j != i]
        if not part:
            out.append((None, 0.0, None))
            continue
        new = [(j, x) for j, x in part if rp[j] < NEW_TIE_BASE_MAX]
        tot = sum(x for _j, x in part)
        out.append((len(new) / len(part), math.log1p(len(new)), sum(x for _j, x in new) / tot))
    return out


def nmi(a, b):
    """2つのラベルの並びの正規化相互情報量（算術平均で正規化）。どちらも1つの群れだけなら 1.0。"""
    n = len(a)
    ca = collections.Counter(a)
    cb = collections.Counter(b)
    cab = collections.Counter(zip(a, b))
    ha = -sum(c / n * math.log(c / n) for c in ca.values())
    hb = -sum(c / n * math.log(c / n) for c in cb.values())
    if ha == 0 and hb == 0:
        return 1.0
    mi = sum(c / n * math.log((c / n) / ((ca[x] / n) * (cb[y] / n))) for (x, y), c in cab.items())
    return 2 * mi / (ha + hb)


def community_stats(labels):
    sizes = sorted(collections.Counter(labels).values(), reverse=True)
    return {"n_comm": len(sizes), "singletons": sum(1 for s in sizes if s == 1), "max_size": sizes[0],
            "median_size": statistics.median(sizes), "n_size_ge5": sum(1 for s in sizes if s >= 5)}


def comm_changes(lab_now, lab_prev):
    """タグごとの、今の月の群れと前の月の群れの入れ替わり（1 − Jaccard）。数え表から計算する（集合を作らない）。"""
    ca = collections.Counter(lab_now)
    cb = collections.Counter(lab_prev)
    cab = collections.Counter(zip(lab_now, lab_prev))
    out = []
    for x, y in zip(lab_now, lab_prev):
        inter = cab[(x, y)]
        union = ca[x] + cb[y] - inter
        out.append(1.0 - inter / union)
    return out


# ---------------------------------------------------------------------------
# 月ごとのグラフ（子プロセス）
# ---------------------------------------------------------------------------

_W = {}


def graph_months(mk):
    """月 M のグラフに使う月：(12か月 M-12〜M-1, その前の12か月 M-13〜M-2, 直近3か月, 直前の月)。区画の前の月は入れない。"""
    first_block = es.month_key(ei.BLOCK_START)
    base = es.network_months(es.month_first(mk), GRAPH_WINDOW, "M")
    prev = [es.add_months(m, -1) for m in base if es.add_months(m, -1) >= first_block]
    return base, prev, base[-RECENT_MONTHS:], base[-1]


def _init_graph(cache_dir, small):
    _W["cache_dir"], _W["meta"] = cache_dir, small


def _graph_task(mk):
    meta = _W["meta"]
    n = len(meta["tags"])
    base_m, prev_m, rec3_m, rec1_m = graph_months(mk)
    size = n * n
    base = prev = rec3 = rec1 = None

    def add(acc, a):
        return a if acc is None else array.array("I", map(operator.add, acc, a))
    for m in sorted(set(base_m) | set(prev_m)):
        a = es.load_pairs(_W["cache_dir"], meta, m)
        if len(a) != size:
            raise GraphError("網の大きさが違う")
        if m in base_m:
            base = add(base, a)
        if m in prev_m:
            prev = add(prev, a)
        if m in rec3_m:
            rec3 = add(rec3, a)
        if m == rec1_m:
            rec1 = a
    if prev is None:
        prev = array.array("I", bytes(4 * size))

    def marg_total(months):
        mg = [0] * n
        tot = 0
        for m in months:
            for i in range(n):
                mg[i] += meta["month_v1"][m][i]
            tot += meta["month_docs"][m]
        return mg, tot
    mb, tb_ = marg_total(base_m)
    mr, tr_ = marg_total(rec3_m)
    nb_base = es.neighbors_from_matrix(base, n, mb, tb_)
    nb_rec = es.neighbors_from_matrix(rec3, n, mr, tr_)
    g_lift = union_graph(nb_base["lift10"], base, n)
    g_share = union_graph(nb_base["share30"], base, n)
    g_rec = union_graph(nb_rec["lift10"], rec3, n)
    nt = new_ties(rec1, prev, n)
    lab_lift, sw1 = label_propagation(g_lift)
    lab_share, sw2 = label_propagation(g_share)
    sources = sorted(random.Random(BTW_SEED).sample(range(n), min(BTW_SOURCES, n)))
    btw_b = betweenness_approx(g_lift, sources)
    btw_r = betweenness_approx(g_rec, sources)
    pr_b = pagerank(g_lift)
    pr_r = pagerank(g_rec)
    return {"mk": mk, "months": base_m, "prev_months": prev_m, "nbrs": nb_base["lift10"], "nt": nt,
            "lab": {"lift10": lab_lift, "share30": lab_share}, "sweeps": {"lift10": sw1, "share30": sw2},
            "btw_b": btw_b, "btw_r": btw_r, "pr_b": pr_b, "pr_r": pr_r,
            "deg_b": [len(a) for a in g_lift], "deg_r": [len(a) for a in g_rec]}


# ---------------------------------------------------------------------------
# 信号
# ---------------------------------------------------------------------------

def hop_signals(i, nbrs, rises):
    """(hop1, hop2)。hop1：1歩の隣の上がりの重み付き平均。hop2：2歩先（1歩の隣と自分を除く）の、重みの積での重み付き平均。"""
    first = nbrs.get(i)
    h1 = es.weighted_mean([(w, rises[j]) for j, w, _s in first])
    near = {j for j, _w, _s in first}
    near.add(i)
    acc = {}
    for j, w, _s in first:
        for k, w2, _s2 in nbrs.get(j):
            if k in near:
                continue
            acc[k] = acc.get(k, 0.0) + w * w2
    h2 = es.weighted_mean([(w, rises[k]) for k, w in sorted(acc.items())])
    return h1, h2


def comm_sums(lab, rises):
    """群れごとの (上がりの和, 上がりが決まったタグの数)。"""
    out = {}
    for l, r in zip(lab, rises):
        if r is None:
            continue
        a = out.setdefault(l, [0.0, 0])
        a[0] += r
        a[1] += 1
    return out


def comm_rise(i, lab, sums, rises):
    """同じ群れの、自分以外のタグの上がりの平均。決まらなければ None。"""
    s, c = sums.get(lab[i], (0.0, 0))
    if rises[i] is not None:
        s, c = s - rises[i], c - 1
    return s / c if c > 0 else None


def graph_row(i, g, sizes, sums, changes, rises):
    """1つの対象の行の、グラフの値の列（GRAPH_COLUMNS の名前の dict）。"""
    v = {}
    f, ln, wt = g["nt"][i]
    v["nt_frac"] = 0.0 if f is None else f
    v["nt_lognew"] = ln
    v["nt_weight"] = 0.0 if wt is None else wt
    v["nt_miss"] = 1.0 if f is None else 0.0
    for cv in COMM_VARIANTS:
        lab = g["lab"][cv]
        cr = comm_rise(i, lab, sums[cv], rises)
        ch = changes[cv][i] if changes[cv] is not None else None
        v["comm_rise_" + cv] = 0.0 if cr is None else cr
        v["comm_logsize_" + cv] = math.log(sizes[cv][lab[i]])
        v["comm_change_" + cv] = 0.0 if ch is None else ch
        v["comm_miss_" + cv] = 1.0 if (cr is None or ch is None) else 0.0
    v["btw_base"] = math.log(g["btw_b"][i] + BTW_EPS)
    v["btw_change"] = math.log((g["btw_r"][i] + BTW_EPS) / (g["btw_b"][i] + BTW_EPS))
    h1, h2 = hop_signals(i, g["nbrs"], rises)
    v["hop1_rise"] = 0.0 if h1 is None else h1
    v["hop1_miss"] = 1.0 if h1 is None else 0.0
    v["hop2_rise"] = 0.0 if h2 is None else h2
    v["hop2_miss"] = 1.0 if h2 is None else 0.0
    v["deg_change"] = math.log((g["deg_r"][i] + 1) / (g["deg_b"][i] + 1))
    v["pr_change"] = math.log(g["pr_r"][i] / g["pr_b"][i])
    return v


# ---------------------------------------------------------------------------
# 表を作る
# ---------------------------------------------------------------------------

def build_table(root, cache_dir, workers, log):
    ctx = ei.load_context(root)
    meta = es.load_cache(cache_dir, ctx)
    tags, v = meta["tags"], ctx["v"]
    n = len(tags)
    days = ctx["days"]
    mondays = ei.prediction_mondays()
    series = es.daily_series(meta)
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
    month_v1, month_docs = {}, {}
    v1 = meta["v1"]
    for di, d in enumerate(meta["days"]):
        if d in missing:
            continue
        mk = es.month_key(datetime.date.fromisoformat(d))
        mv = month_v1.setdefault(mk, [0] * n)
        for i in range(n):
            mv[i] += v1[di * n + i]
        month_docs[mk] = month_docs.get(mk, 0) + meta["docs"][di]
    pred_months = sorted({es.month_key(t) for t in mondays})
    gmonths = [es.add_months(pred_months[0], -1)] + pred_months
    small = {"tags": tags, "pair_files": meta["pair_files"], "month_v1": month_v1, "month_docs": month_docs}
    graphs = {}
    with es._pool(workers, _init_graph, (cache_dir, small)) as pool:
        for k, g in enumerate(pool.imap(_graph_task, gmonths), 1):
            graphs[g["mk"]] = g
            log("グラフ %d / %d（%d）" % (k, len(gmonths), g["mk"]))
    sizes = {mk: {cv: collections.Counter(g["lab"][cv]) for cv in COMM_VARIANTS} for mk, g in graphs.items()}
    changes = {}
    for mk, g in graphs.items():
        gp = graphs.get(es.add_months(mk, -1))
        changes[mk] = {cv: (comm_changes(g["lab"][cv], gp["lab"][cv]) if gp is not None else None)
                       for cv in COMM_VARIANTS}
    cstats = []
    for mk in gmonths:
        for cv in COMM_VARIANTS:
            st = community_stats(graphs[mk]["lab"][cv])
            prev = es.add_months(mk, -1)
            st["nmi_prev"] = nmi(graphs[mk]["lab"][cv], graphs[prev]["lab"][cv]) if prev in graphs else None
            st["sweeps"] = graphs[mk]["sweeps"][cv]
            cstats.append((mk, cv, st))
    tb = {"t": [], "tag": [], "week": [], "family": []}
    for m in MULTIPLIERS:
        tb["y%d" % m] = []
        for k in range(len(naive.FEATURES)):
            tb["naive%d_%d" % (m, k)] = []
    for c in GRAPH_COLUMNS:
        tb[c] = []
    net_off = None
    for ti, t in enumerate(mondays):
        mk = es.month_key(t)
        g = graphs[mk]
        months = es.network_months(t, GRAPH_WINDOW, "M")
        if g["months"] != months:
            raise GraphError("グラフの月が予言日の月と合わない")
        off = es.check_network_before(t, months)
        if g["prev_months"]:
            es.check_network_before(t, g["prev_months"])
        gp = graphs.get(es.add_months(mk, -1))
        if gp is not None:
            es.check_network_before(t, gp["months"])
        net_off = off if net_off is None else max(net_off, off)
        rises = [None] * n
        for j in range(n):
            st, b, c, _m1, _m2, _js, _lv = results[j][ti]
            if b is not None and c is not None:
                rises[j] = es.rise(c, b, v)
        sums = {cv: comm_sums(g["lab"][cv], rises) for cv in COMM_VARIANTS}
        for i in range(n):
            st, b, c, _m1, _m2, js, lv = results[i][ti]
            if st != "target" or any(x is None for x in js):
                continue
            tb["t"].append(t)
            tb["tag"].append(tags[i])
            tb["week"].append(ti)
            tb["family"].append(em.family_of(tags[i]))
            for m, y in zip(MULTIPLIERS, js):
                tb["y%d" % m].append(1 if y else 0)
                for k, x in enumerate(naive.features_from_levels(lv, m, v)):
                    tb["naive%d_%d" % (m, k)].append(x)
            vals = graph_row(i, g, sizes[mk], sums, changes[mk], rises)
            for c in GRAPH_COLUMNS:
                tb[c].append(vals[c])
        if (ti + 1) % 40 == 0:
            log("信号 %d / %d 週" % (ti + 1, len(mondays)))
    for c in list(GRAPH_COLUMNS) + ["naive%d_%d" % (m, k) for m in MULTIPLIERS for k in range(len(naive.FEATURES))]:
        if len(tb[c]) != len(tb["t"]):
            raise GraphError("列 %s の長さが違う" % c)
        tb[c] = array.array("d", tb[c])
    for m in MULTIPLIERS:
        tb["y%d" % m] = array.array("b", tb["y%d" % m])
    tb["train"] = [r for r, t in enumerate(tb["t"]) if es.split_of(t) == "train"]
    tb["test"] = [r for r, t in enumerate(tb["t"]) if es.split_of(t) == "test"]
    info = {"daily_min_read": lo.isoformat(), "daily_max_read": hi.isoformat(),
            "network_last_day_minus_t_max_days": net_off, "phase1_sha256": meta["phase1_sha256"],
            "phase1_label": meta["label"], "refs": ctx["refs"], "v": meta["v"], "graph_months": gmonths}
    return tb, info, cstats


# ---------------------------------------------------------------------------
# モデル（子プロセス）
# ---------------------------------------------------------------------------

def model_columns(m, cols):
    return [em.naive_col(m, f) for f in naive.FEATURES] + list(cols)


def _init_fit(tb):
    _W["tb"] = tb


def _fit_task(args):
    m, name = args
    tb = _W["tb"]
    _n, kind, cols, _ref = [x for x in MODELS if x[0] == name][0]
    feats = model_columns(m, cols)
    tr = em.ordered(tb, tb["train"])
    y = [tb["y%d" % m][r] for r in tr]
    if kind == "logit":
        tcols = [em.column_values(tb, c, tr) for c in feats]
        fit = em.fit_logistic_cols(tcols, y, em.FIXED_LAMBDA)
        ecols = [em.column_values(tb, c, tb["test"]) for c in feats]
        return args, {"labels": [em.column_label(c) for c in feats], "coef": fit["coef"],
                      "converged": fit["converged"], "iterations": fit["iterations"],
                      "probs": em.predict_cols(ecols, fit["coef"])}
    tbins, ebins, nb = [], [], []
    for c in feats[1:]:
        tv = em.column_values(tb, c, tr)
        edges = em.bin_edges(tv, em.GBDT["bins"])
        tbins.append(em.to_bins(tv, edges))
        ebins.append(em.to_bins(em.column_values(tb, c, tb["test"]), edges))
        nb.append(len(edges) + 1)
    model = em.fit_gbdt(tbins, y, em.GBDT, nb)
    return args, {"labels": [em.column_label(c) for c in feats[1:]], "converged": True,
                  "iterations": em.GBDT["trees"], "probs": em.predict_gbdt(model, ebins, len(tb["test"]))}


def run(root, cache_dir, out_dir, workers, log):
    tb, info, cstats = build_table(root, cache_dir, workers, log)
    log("表：%d 行（学習 %d、検証 %d）" % (len(tb["t"]), len(tb["train"]), len(tb["test"])))
    tasks = [(m, name) for m in MULTIPLIERS for name, kind, _c, _r in MODELS]
    tasks.sort(key=lambda a: ([x for x in MODELS if x[0] == a[1]][0][1] != "gbdt", a))
    res = {}
    with es._pool(workers, _init_fit, (tb,)) as pool:
        for k, (args, out) in enumerate(pool.imap_unordered(_fit_task, tasks), 1):
            res[args] = out
            log("モデル %d / %d %r" % (k, len(tasks), args))
    files = build_outputs(tb, info, cstats, res)
    return write_outputs(out_dir, files)


# ---------------------------------------------------------------------------
# 出力
# ---------------------------------------------------------------------------

OUT_NAMES = ("models.tsv", "coefs.tsv", "signals.tsv", "communities.tsv", "run.json", "summary.md")


def write_outputs(out_dir, files):
    if sorted(files) != sorted(OUT_NAMES):
        raise GraphError("出力の名前が決めた一覧と違う")
    os.makedirs(out_dir, exist_ok=True)
    for n in OUT_NAMES:
        if os.path.lexists(os.path.join(out_dir, n)):
            raise GraphError("書き出す先に同じ名前のファイル（%s）がある。上書きしない" % n)
    return {n: es.write_new(os.path.join(out_dir, n), files[n]) for n in OUT_NAMES}


def f6(x):
    return es.f6(x)


def signal_summary(tb):
    out = []
    tr = tb["train"]
    for c in GRAPH_COLUMNS:
        if c.endswith("_miss") or "_miss_" in c:
            continue
        for m in MULTIPLIERS:
            y = tb["y%d" % m]
            pos = [tb[c][r] for r in tr if y[r]]
            neg = [tb[c][r] for r in tr if not y[r]]
            out.append((c, m, len(tr), len(pos), f6(sum(pos) / len(pos) if pos else None),
                        f6(sum(neg) / len(neg) if neg else None)))
    return out


def build_outputs(tb, info, cstats, res):
    test = tb["test"]
    weeks_all = sorted({tb["week"][r] for r in test})
    rows, crows = [], []
    for m in MULTIPLIERS:
        naive_p = res[(m, "naive")]["probs"]
        for name, kind, cols, ref in MODELS:
            out = res[(m, name)]
            mn = em.metrics(tb, m, test, out["probs"], None if name == "naive" else naive_p, weeks_all)
            mr = em.metrics(tb, m, test, out["probs"], res[(m, ref)]["probs"], weeks_all) \
                if ref not in (None, "naive") else mn
            rows.append({"m": m, "name": name, "kind": kind, "ref": ref, "nfeat": len(out["labels"]), "mn": mn,
                         "mr": mr, "conv": out["converged"], "iter": out["iterations"]})
            if "coef" in out:
                for lab, b in zip(out["labels"], out["coef"]):
                    crows.append((m, name, lab, f6(b)))

    def ci(x, key):
        v = x.get(key)
        return ("-", "-") if v is None else (f6(v[0]), f6(v[1]))
    models_tsv = ei.tsv(
        ("multiplier", "horizon_days", "model", "kind", "n_features", "n_test", "islands_test", "logloss", "auc",
         "top10_hits", "d_logloss_vs_naive", "d_ll_vs_naive_ci4w_lo", "d_ll_vs_naive_ci4w_hi", "d_top10_vs_naive",
         "ref", "d_logloss_vs_ref", "d_ll_vs_ref_ci4w_lo", "d_ll_vs_ref_ci4w_hi", "d_top10_vs_ref", "converged",
         "iterations"),
        [(r["m"], HORIZON, r["name"], r["kind"], r["nfeat"], r["mn"]["n"], r["mn"]["pos"], f6(r["mn"]["logloss"]),
          f6(r["mn"]["auc"]), r["mn"]["topk"], f6(r["mn"].get("d_logloss")), *ci(r["mn"], "d_ll_ci"),
          r["mn"].get("d_topk", "-"), r["ref"] or "-", f6(r["mr"].get("d_logloss")), *ci(r["mr"], "d_ll_ci"),
          r["mr"].get("d_topk", "-"), r["conv"], r["iter"]) for r in rows])
    coefs_tsv = ei.tsv(("multiplier", "model", "feature", "coef"), crows)
    sig = signal_summary(tb)
    signals_tsv = ei.tsv(("signal", "multiplier", "train_rows", "train_islands", "mean_islands", "mean_non_islands"),
                         sig)
    comm_tsv = ei.tsv(("graph_month", "graph", "n_comm", "singletons", "max_size", "median_size", "n_size_ge5",
                       "nmi_vs_prev_month", "lpa_sweeps"),
                      [(mk, cv, s["n_comm"], s["singletons"], s["max_size"], s["median_size"], s["n_size_ge5"],
                        f6(s["nmi_prev"]), s["sweeps"]) for mk, cv, s in cstats])
    code = dict(ei._LOADED_SHA, **es.own_code_shas())
    for rel, mod in (("src/stats/explore_models.py", em), ("src/stats/explore_graph.py", sys.modules[__name__])):
        with open(os.path.abspath(mod.__file__), "rb") as f:
            code[rel] = hashlib.sha256(f.read()).hexdigest()
    n_models = len(MODELS) - 1
    n_ranges = sum(1 + (1 if ref not in (None, "naive") else 0) for _n, _k, _c, ref in MODELS if ref is not None)
    run_json = dict(info, **{
        "label": LABEL, "code": code, "python": sys.version.split()[0],
        "rows": {"all": len(tb["t"]), "train": len(tb["train"]), "test": len(tb["test"])},
        "train_last_monday": es.TRAIN_LAST.isoformat(), "test_first_monday": es.TEST_FIRST.isoformat(),
        "options": {"graph_window": GRAPH_WINDOW, "recent_months": RECENT_MONTHS,
                    "new_tie_recent_min": NEW_TIE_RECENT_MIN, "new_tie_base_max": NEW_TIE_BASE_MAX,
                    "lpa_max_sweeps": LPA_MAX_SWEEPS, "btw_sources": BTW_SOURCES, "btw_seed": BTW_SEED,
                    "btw_eps": BTW_EPS, "pr_damping": PR_DAMPING, "pr_iters": PR_ITERS, "groups": GROUPS,
                    "all_group": ALL_GROUP, "models": MODELS, "gbdt": em.GBDT, "fixed_lambda": em.FIXED_LAMBDA,
                    "min_pair_docs": es.MIN_PAIR_DOCS, "neighbors": es.NEIGHBORS},
        "models_per_multiplier": n_models, "models_total": n_models * len(MULTIPLIERS),
        "ranges_per_multiplier": n_ranges, "ranges_total": n_ranges * len(MULTIPLIERS),
        "test_weeks": len(weeks_all), "test_blocks_4w": len(es.blocks_of(weeks_all, es.BLOCK_WEEKS)),
        "citation": [ei.CITATION_EN, ei.CITATION_JA]})
    files = {"models.tsv": models_tsv, "coefs.tsv": coefs_tsv, "signals.tsv": signals_tsv,
             "communities.tsv": comm_tsv,
             "run.json": (json.dumps(run_json, ensure_ascii=False, sort_keys=True, indent=1) + "\n").encode("utf-8")}
    files["summary.md"] = summary_md(run_json, rows, sig, cstats)
    for name, data in files.items():
        ei.check_public(name, data)
    return files


def summary_md(run, rows, sig, cstats):
    L = []
    a = L.append
    md = ei.md_table
    a("# グラフ理論によるネットワーク分析の探索（T-119、手法を作る期間）")
    a("")
    a("この文書は `src/stats/explore_graph.py` が出力したもので、手で書き足していない。見方・作り方・モデルは、ここでは決めない"
      "（決定はオーナー）。全部の結果を並べ、選ばない・勧めない。テーマの名前は載せていない（系統の名前と数だけ）。")
    a("")
    a("## 0. 何をどう比べたか")
    a("- 入力・予言日・対象・判定・学習と検証の分け方は T-117・T-118 と同じ（キャッシュ phase1.json の sha256 %s）。"
      "学習：予言日 %s 以前（%d 行）。検証：%s 以降（%d 行）。倍率 %s、判定期間 %d 日。" % (
          run["phase1_sha256"], run["train_last_monday"], run["rows"]["train"], run["test_first_monday"],
          run["rows"]["test"], "・".join(str(m) for m in MULTIPLIERS), HORIZON))
    a("- 網：予言日を含む月 M の前の12か月（M-12〜M-1）の P1 の組の文書の数の和（T-117 の w12m と同じ）。グラフは lift10 または share30 "
      "の隣（組の文書の数 %d 以上）を双方向にまとめた無向グラフ。" % es.MIN_PAIR_DOCS)
    a("- 1 新しい結びつき（A_newtie）：直前の月に %d 件以上の組のある相手のうち、その前の12か月（M-13〜M-2）の組が %d 件未満の相手の、"
      "割合・数の log1p・直前の月の組の文書の数のうちの割合。" % (NEW_TIE_RECENT_MIN, NEW_TIE_BASE_MAX))
    a("- 2 群れ（B_comm_*）：重み付きのラベル伝播（番号の順に更新、同じ重みなら小さいラベル、最大 %d 回）。同じ群れの他のタグの上がりの平均、"
      "群れの大きさの log、前の月の群れとの入れ替わり（1 − Jaccard）。" % LPA_MAX_SWEEPS)
    a("- 3 橋渡しの位置（C_btw）：媒介中心性（重みなし、lift10 のグラフ）。**近似**：始点を %d 個だけ乱数の種 %d で選び（どの月も同じ始点）、"
      "Brandes の方法で足して n / %d 倍した。12か月のグラフでの値の log と、直近3か月（M-3〜M-1）のグラフとの比の log。"
      % (BTW_SOURCES, BTW_SEED, BTW_SOURCES))
    a("- 4 2歩先の隣（D_hop*）：1歩の隣（lift10、重み n_ij/n_i）の上がりの重み付き平均と、2歩先（1歩の隣と自分を除く。重みは2つの積）の上がり"
      "の重み付き平均。上がりは log((c+V)/(B+V))。")
    a("- 5 中心性の変化（E_*）：直近3か月の lift10 グラフと12か月の lift10 グラフでの、次数の比の log（E_deg）と PageRank（減衰 %g、%d 回）"
      "の比の log（E_pr）。" % (PR_DAMPING, PR_ITERS))
    a("- all：A・B_comm_lift10・C・D_hop12・E_deg・E_pr の列すべて。gbdt_graph：all の列を T-118 と同じ設定の GBDT で足したもの。")
    a("- モデル：素朴な予測の特徴量（7つ）に、見方の列を足したロジスティック回帰（リッジ %g、T-117 と同じ）。値が決まらない行は 0 にし、"
      "決まらないことを示す列（_miss）を足した。" % em.FIXED_LAMBDA)
    a("- 指標と束ね方は T-117・T-118 と同じ（対数損失・AUC・週ごとの上位10の島。検証の週を4週ずつ束ねた %d 個の単位の復元抽出 %d 回、"
      "乱数の種 %d）。" % (run["test_blocks_4w"], es.BOOT_N, es.BOOT_SEED))
    a("- 試す形は、このファイルに書いてコミットした版で流した（7章のコードの sha256）。本番の前に本物のデータで流したのは、"
      "検証の結果を出さない時間の見積もりだけ（係の申告。6章）。")
    a("")
    a("## 1. 結果（検証）")
    a("")
    for m in MULTIPLIERS:
        rs = [r for r in rows if r["m"] == m]
        nv = rs[0]["mn"]
        a("### 倍率 %d（検証の行 %d、島 %d）" % (m, nv["n"], nv["pos"]))
        a("")
        a(md(["モデル", "列の数", "対数損失", "AUC", "上位10の島", "naive との差（割合）", "差の範囲（4週束ね）", "上位10の差",
              "比べる相手", "相手との差（割合）", "相手との差の範囲"],
             [(r["name"], r["nfeat"], f6(r["mn"]["logloss"]), f6(r["mn"]["auc"]), r["mn"]["topk"],
               "-" if r["name"] == "naive" else "%s（%+.2f%%）" % (f6(r["mn"]["d_logloss"]),
                                                                   100 * r["mn"]["d_logloss"] / nv["logloss"]),
               "-" if r["name"] == "naive" else "%s〜%s" % (f6(r["mn"]["d_ll_ci"][0]), f6(r["mn"]["d_ll_ci"][1])),
               "-" if r["name"] == "naive" else r["mn"]["d_topk"],
               r["ref"] or "-",
               "-" if r["ref"] in (None, "naive") else "%s（%+.2f%%）" % (
                   f6(r["mr"]["d_logloss"]), 100 * r["mr"]["d_logloss"] / r["mr"]["ref_logloss"]),
               "-" if r["ref"] in (None, "naive") else "%s〜%s" % (f6(r["mr"]["d_ll_ci"][0]),
                                                                    f6(r["mr"]["d_ll_ci"][1])))
              for r in rs]))
        a("")
        below = [r["name"] for r in rs if r["ref"] and r["mn"]["d_ll_ci"][1] < 0]
        above = [r["name"] for r in rs if r["ref"] and r["mn"]["d_ll_ci"][0] > 0]
        a("- naive との対数損失の差の範囲が0より下に収まったモデル：%s。0より上に収まったモデル：%s。" % (
            "、".join(below) if below else "無い", "、".join(above) if above else "無い"))
        by = {r["name"]: r for r in rs}
        if by["gbdt_naive"]["mn"]["d_logloss"] > 0:
            a("- 注記：基準の gbdt_naive は naive より %+.2f%% 悪い。gbdt_graph の「相手との差」は、基準が下がった分を差し引いて読む"
              "（naive との差は %+.2f%%、範囲 %s〜%s）。この倍率では、GBDT を上限の目安と読めない。" % (
                  100 * by["gbdt_naive"]["mn"]["d_logloss"] / nv["logloss"],
                  100 * by["gbdt_graph"]["mn"]["d_logloss"] / nv["logloss"],
                  f6(by["gbdt_graph"]["mn"]["d_ll_ci"][0]), f6(by["gbdt_graph"]["mn"]["d_ll_ci"][1])))
        nc = [r["name"] for r in rs if not r["conv"]]
        if nc:
            a("- 収まらなかった推定：%s（結果は参考）。" % "、".join(nc))
        a("- この一覧の読み方：比べたモデルはこの倍率で %d（naive を除く）、3つの倍率で計 %d。出した差の範囲はこの倍率で %d、計 %d で、"
          "多重比較の補正をしていない。4週の束どうしは独立でない（判定期間 %d 日が隣の束に重なる。最後の束は %d 週）。"
          "範囲が0を含まないことは、見方が効くことの確かめにはならない。" % (
              run["models_per_multiplier"], run["models_total"], run["ranges_per_multiplier"], run["ranges_total"],
              HORIZON, run["test_weeks"] - es.BLOCK_WEEKS * (run["test_blocks_4w"] - 1)))
        a("")
    a("## 2. 見方の値（学習の行）")
    a("")
    a(md(["列", "倍率", "学習の行", "島", "島の平均", "島でないものの平均"], sig))
    a("")
    a("## 3. 群れ（採点計画の「出来事のまとまりで束ねる」単位の材料。決めない）")
    a("")
    for cv in COMM_VARIANTS:
        ss = [s for _mk, c, s in cstats if c == cv]
        nm = [s["nmi_prev"] for s in ss if s["nmi_prev"] is not None]
        a("- %s のグラフ（%d か月）：群れの数の中央値 %s（最小 %d、最大 %d）、1つだけの群れの数の中央値 %s、5つ以上の群れの数の中央値 %s、"
          "最大の群れの大きさの中央値 %s、前の月との NMI の中央値 %s（最小 %s、最大 %s）、ラベル伝播の回数の最大 %d。" % (
              cv, len(ss), statistics.median([s["n_comm"] for s in ss]), min(s["n_comm"] for s in ss),
              max(s["n_comm"] for s in ss), statistics.median([s["singletons"] for s in ss]),
              statistics.median([s["n_size_ge5"] for s in ss]), statistics.median([s["max_size"] for s in ss]),
              f6(statistics.median(nm)) if nm else "-", f6(min(nm)) if nm else "-", f6(max(nm)) if nm else "-",
              max(s["sweeps"] for s in ss)))
    a("- 月ごとの値は communities.tsv。群れの中のテーマの名前は載せていない。")
    a("")
    a("## 4. 予言の時点のデータだけを使ったことの確かめ")
    a("- 日の比率：実際に読んだ日は %s〜%s（入力は t-399〜t-1、判定は t+1〜t+28 の外を読むと止まる）。" % (
        run["daily_min_read"], run["daily_max_read"]))
    a("- グラフ：予言日 t ごとに、使う月（12か月、その前の12か月、前の月のグラフの月）の最後の日 < t を確かめた。最後の日 − t の最大は %d 日。"
      % run["network_last_day_minus_t_max_days"])
    a("")
    a("## 5. 限界")
    a("- **検証の期間の再利用**：検証の期間（2019〜2020年）は、T-117・T-118 で結果を見たあとの再利用で、T-119 の見方はその後に書いた。"
      "未見のデータでの確かめにはならない。未見のデータでの確かめは、閾値を決める期間になる。")
    a("- **一覧と V の先読み**：タグの一覧と V（= A）は、手法を作る期間の区画全体のデータで決まった（seq 17）（T-116 の要約 6章）。")
    a("- **除外の規則の漏れ**：民族・人物の姓・宗教・犯罪・紛争・政治に当たる名前のテーマが一覧に残っている（オーナーの決定 2026-10-16、"
      "(a) このまま進める）。グラフの点・群れ・隣にも入る。要約にはテーマの名前を載せていない。")
    a("- **WB のテーマの段のような上昇**：2016年4月から WB のテーマの一部が段のように上がり、2017年に戻る（T-116 の要約 6章）。"
      "学習の期間のグラフ（組の文書の数、群れ、中心性）にも入る。")
    a("- **近似**：媒介中心性は始点 %d 個の近似で、乱数の種を変えれば値は変わる。ラベル伝播は更新の順番に依る（番号の順に固定）。" % BTW_SOURCES)
    a("- グラフは月ごとにまとめた網なので、予言日の前の数週は入らない。グラフの作り方（隣の数、組の文書の数の下限、無向にまとめること）"
      "も選びうるもので、比べた数に入っていない。")
    a("")
    a("## 6. 本番の前に流したもの")
    a("- 本物のデータでは、検証の結果を出さない時間の見積もり（1か月分のグラフの計算）だけを流した（係の申告）。")
    a("")
    a("## 7. 再計算")
    a("```")
    a(".venv/bin/python -B src/stats/explore_graph.py --cache-dir <explore-t117-cache/run2> --out-dir <書き出す先>")
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
    p = argparse.ArgumentParser(description="T-119 グラフ理論によるネットワーク分析の探索")
    p.add_argument("--cache-dir", required=True)
    p.add_argument("--out-dir", required=True)
    p.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 1))
    a = p.parse_args(argv)
    t0 = time.time()

    def log(msg):
        sys.stderr.write("[%8.1f s] %s\n" % (time.time() - t0, msg))
        sys.stderr.flush()
    try:
        tb_info = run(ei.PROJECT, a.cache_dir, a.out_dir, a.workers, log)
    except (GraphError, em.ModelError, es.SignalError, ei.ExploreError) as e:
        sys.stderr.write("止まった：%s\n" % e)
        return 1
    for n in OUT_NAMES:
        print("%s  %s" % (tb_info[n], n))
    log("終わり")
    return 0


if __name__ == "__main__":
    sys.exit(main())
