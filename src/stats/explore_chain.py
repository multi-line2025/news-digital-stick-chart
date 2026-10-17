#!/usr/bin/env python3
"""T-127：島の連鎖の探索（手法を作る期間）。

島の定義は変えない（C7、V = A、一度跳ねたタグの扱いあり、判定期間 28 日、倍率 2・4・8）。全部並べ、選ばない・勧めない。
試す形（下の定数）は、本番の前にこのファイルに書き、コミットしてから流す。結果に、このファイルの sha256 を入れる。

1. 記述（理解のため。区画全体の判定の結果を使う。予測の入力にはしない）
   きっかけ：予言日 w に島（倍率 m）になったタグ A。種類は all（すべて）・stay（上がったまま）・back（戻った）。
     上がったまま／戻ったは T-125 と同じ（explore_sea.after_level・back_or_stay。t+57〜t+180 の比率の平均が max(2B, V) 以下なら戻った）。
   その後 k = 1〜12 週の予言日 w+k に、ほかのタグ B（その予言日の対象）が島（同じ倍率 m）になったかを、A との関係ごとに数える。
     関係（流す前に書いた決め方）
       hop1：A が B の網の1歩の隣（B の lift の上位10。T-119 の hop_signals の1歩と同じ）。
       hop2：A が B の2歩先の隣（1歩の隣の、そのまた隣。B 自身と1歩の隣を除く。T-119 の hop_signals の2歩と同じ）。
         網は w を含む月の前の12か月（M-12〜M-1）の lift10（T-117 の月ごとの P1 の組の文書の数、es.neighbors_from_matrix）。
       family：同じ系統の海域（T-125。「その他」どうしは関係に数えない）。
       community：同じ群れの海域（T-125。「小さな群れ」どうしは関係に数えない）。
       none：上の4つのどれでもない。
     比べ方：週 w+k ごとに、関係の無い組（none）の島の割合を「ふだんの割合」とし、期待の数 = 組の数 × その週の none の割合。
       比（ratio_none）= 島の数の和 ÷ 期待の数の和。参考に、その週の対象すべての島の割合で作った比（ratio_all）も並べる。
   海域どうしの順序（系統の海域。13）：海域 X の島（きっかけ）のあと k = 1〜K 週の、海域 Y の島の割合を、Y のふだんの島の割合
     （全週）で割った値 lift(X→Y)。向きの差 log(lift(X→Y) / lift(Y→X))。K は ORDER_KS。
   事例：CASE_FIRST〜CASE_LAST の予言日の、週ごと・海域ごとの島の数と、先に（1〜12週前に）同じ倍率の島になった hop1・hop2 の隣・
     同じ系統の海域のタグがあった島の数。テーマの名前の入った並びは chain-private.tsv（公開しない印付き）にだけ書く。
   偶然の比べ：タグごとに、予言日の並び（対象かどうか・島・上がったまま／戻った）を、乱数で決めた週数だけ輪のようにずらした系列
     （乱数の種 NULL_SEED、NULL_R 本）で、同じ数を作る。網と海域はずらさない。偶然の水準は NULL_Q の点（最近順位）。
     向きの差は、ずらした系列の ORDER_Q の範囲の外なら「向きあり」、中なら「見分けられない」。
2. 予測の形（予言日 t の時点で観測できるものだけ）
   状態：予言日 t のタグ j が「高い」とは、c_j(t) > max(STATE_MULT × B_j(t), V)（c は t-1 で終わる7日の平均、B は封印済みの
     関数で t-1 以前。判定の参照実装と同じ厳密な不等号）。続いた週数 d_j(t)：t から前へ、高い予言日が続いた数（t-7, t-14, … の
     予言日の値だけを使う。最初の予言日 2016-04-11 より前は数えない）。
   励起の重み：d_j(t) ≥ D のとき exp(−(d_j(t) − 1) / λ)、それ以外は 0。D は STATE_MIN_WEEKS、λ は LAMBDAS。
   励起の量（対象の行の B について）：hop1・hop2 の隣の重みの重み付き平均（隣の重みは T-119 と同じ n_ij/n_i と、その積）、
     同じ系統（名前から決まる。「その他」は 0）の自分以外の平均、同じ群れ（予言日 t を含む月の網の lift10 のラベル伝播。
     T-119 と同じ）の自分以外の平均。隣が無ければ 0。
   モデル：素朴な予測（naive.py の7つの特徴量、ロジスティック回帰、リッジ 1）に、(D, λ) ごとに4つの関係をまとめて足したものと、
     1つずつ足したもの。主は分け方 B（学習 〜2017-12-04、確かめ 2018-01-08〜2018-12-03）、A（学習 〜2018-12-03、検証 2019-01-07〜）は参考。

予言の時点のデータだけ：日の比率は ReadGuard（入力は t-399〜t-1、判定は t+1〜t+28）。網の月は予言日を含む月より前で、
予言日ごとに網の最後の日 < t を確かめる（es.check_network_before）。状態の続いた週数は t 以前の予言日の値だけから作る。
区画の外（2020-12-15 以降）は読まない。

出力：要約（テーマの名前を載せない）と集計の表。テーマの名前の入った表は名前を -private とし、先頭の行に公開しない印を付ける。

流し方（プロジェクトのルートで。TMPDIR は scratchpad の中に）
  .venv/bin/python -B src/stats/explore_chain.py --t117-cache <explore-t117-cache/run2> --out-dir <書き出す先>

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
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import explore_sea as sea  # noqa: E402

x2 = sea.x2
ex = sea.ex
ed = sea.ed
eg = sea.eg
em = sea.em
es = sea.es
ei = sea.ei
naive = sea.naive

LABEL = "explore-chain-t127-v1"
MULTIPLIERS = em.MULTIPLIERS
HORIZON = em.HORIZON
DAY = datetime.timedelta(days=1)

# ---------------------------------------------------------------------------
# 試す形（本番の前に書いた）
# ---------------------------------------------------------------------------
LAGS = tuple(range(1, 13))                          # k = 1〜12 週
LAG_BANDS = ((1, 4), (5, 8), (9, 12), (1, 12))
RELATIONS = ("hop1", "hop2", "family", "community", "none")
TRIGGER_KINDS = ("all", "stay", "back")
GRAPH_WINDOW = 12                                   # 網：予言日を含む月の前の12か月（T-119 と同じ）
ORDER_KS = (4, 12)
ORDER_KINDS = ("all", "stay")
NULL_SEED = 127
NULL_R = 200
NULL_Q = 0.90
ORDER_Q = (0.05, 0.95)
CASE_FIRST = datetime.date(2020, 1, 6)
CASE_LAST = datetime.date(2020, 4, 27)
STATE_MULT = 2
STATE_MIN_WEEKS = (1, 2)
LAMBDAS = (1.0, 2.0, 4.0)
EXC_RELATIONS = ("hop1", "hop2", "family", "community")
SPLIT_MAIN = "B"
SPLITS = ("B", "A")
MAIN_M = 4
MAIN_KINDS = ("stay", "back")

AFTER_CODE = {"unknown": 0, "back": 1, "stay": 2}
KIND_CODE = {"stay": 2, "back": 1}


class ChainError(Exception):
    pass


def variants():
    """(D, λ) の組。"""
    return [(d, lam) for d in STATE_MIN_WEEKS for lam in LAMBDAS]


def exc_column(rel, d, lam):
    return "exc_%s_D%d_L%g" % (rel, d, lam)


EXC_COLUMNS = tuple(exc_column(r, d, lam) for d, lam in variants() for r in EXC_RELATIONS)


def models():
    """(名前, 足す列) の一覧。"""
    out = []
    for d, lam in variants():
        out.append(("chain_D%d_L%g" % (d, lam), tuple(exc_column(r, d, lam) for r in EXC_RELATIONS)))
    for d, lam in variants():
        for r in EXC_RELATIONS:
            out.append(("chain_%s_D%d_L%g" % (r, d, lam), (exc_column(r, d, lam),)))
    return out


def nearest_rank(sorted_xs, q):
    return sea.nearest_rank(sorted_xs, q)


# ---------------------------------------------------------------------------
# 状態（予言日 t の時点で観測できるもの）
# ---------------------------------------------------------------------------

def is_high(b, c, v):
    """c > max(STATE_MULT × b, V)。b か c が決まらなければ False。"""
    if b is None or c is None:
        return False
    return c > max(STATE_MULT * b, v)


def durations(flags):
    """予言日ごとの、そこまで高い予言日が続いた数（その予言日を含む）。flags[t] は予言日 t の値だけから決まる。
    durations の t の値は、flags の t 以前だけで決まる。"""
    out = array.array("H")
    d = 0
    for f in flags:
        d = d + 1 if f else 0
        out.append(min(d, 65535))
    return out


def exc_weight(d, dmin, lam):
    return math.exp(-(d - 1) / lam) if d >= dmin else 0.0


# ---------------------------------------------------------------------------
# 網（T-119 の1歩・2歩）
# ---------------------------------------------------------------------------

def hop_lists(nbrs, n):
    """各タグの1歩の隣 [(j, w)] と2歩先 [(k, w1·w2)]（T-119 の hop_signals と同じ集め方。番号の順）。"""
    h1, h2 = [], []
    for i in range(n):
        first = [(j, w) for j, w, _s in nbrs.get(i)]
        near = {j for j, _w in first}
        near.add(i)
        acc = {}
        for j, w in first:
            for k, w2, _s2 in nbrs.get(j):
                if k in near:
                    continue
                acc[k] = acc.get(k, 0.0) + w * w2
        h1.append(first)
        h2.append(sorted(acc.items()))
    return h1, h2


def csr(lists):
    """[[(j, w)]] → (off, j, w) の配列。"""
    off, js, ws = array.array("I", [0]), array.array("I"), array.array("d")
    for lst in lists:
        for j, w in lst:
            js.append(j)
            ws.append(w)
        off.append(len(js))
    return off, js, ws


def reverse_csr(lists, n):
    """A → [B | A が lists[B] に入っている]（B の番号の順）。戻り値：(off, j)。"""
    rev = [[] for _ in range(n)]
    for b, lst in enumerate(lists):
        for a, _w in lst:
            rev[a].append(b)
    off, js = array.array("I", [0]), array.array("I")
    for lst in rev:
        js.extend(lst)
        off.append(len(js))
    return off, js


# ---------------------------------------------------------------------------
# 励起の量（予言日 t の対象の行）
# ---------------------------------------------------------------------------

def week_weights(dur_col, n):
    """予言日 t の、(D, λ) ごとのタグの重み。dur_col[j] は d_j(t)。"""
    return [[exc_weight(dur_col[j], d, lam) for j in range(n)] for d, lam in variants()]


def group_sums(values, groups):
    """groups[j]（負なら数えない）ごとの (和, 数)。"""
    s, c = {}, {}
    for x, g in zip(values, groups):
        if g < 0:
            continue
        s[g] = s.get(g, 0.0) + x
        c[g] = c.get(g, 0) + 1
    return s, c


def exc_features(i, h1, h2, ew, fsum, fam, csum, comm):
    """対象 i の励起の量（EXC_COLUMNS の順）。ew は week_weights、fsum・csum は (和, 数) の (D, λ) ごとの並び。"""
    out = []
    for vi in range(len(ew)):
        e = ew[vi]
        x1 = es.weighted_mean([(w, e[j]) for j, w in h1])
        x2_ = es.weighted_mean([(w, e[k]) for k, w in h2])
        f = fam[i]
        if f >= 0 and fsum[vi][1].get(f, 0) > 1:
            xf = (fsum[vi][0][f] - e[i]) / (fsum[vi][1][f] - 1)
        else:
            xf = 0.0
        g = comm[i]
        if g >= 0 and csum[vi][1].get(g, 0) > 1:
            xc = (csum[vi][0][g] - e[i]) / (csum[vi][1][g] - 1)
        else:
            xc = 0.0
        out.extend([0.0 if x1 is None else x1, 0.0 if x2_ is None else x2_, xf, xc])
    return out


# ---------------------------------------------------------------------------
# 月ごとの網と励起の量（子プロセス）
# ---------------------------------------------------------------------------

_W = {}


def _init_graph(t117_cache, small, dur, targets_by_week, fam_pred, mondays, case_months):
    _W.update(cache_dir=t117_cache, meta=small, dur=dur, targets=targets_by_week, fam=fam_pred, mondays=mondays,
              case_months=case_months)


def graph_of_month(cache_dir, meta, mk):
    """月 mk の網（前の12か月）。戻り値：(月の一覧, lift10 の Nbrs, ラベル伝播のラベル)。"""
    n = len(meta["tags"])
    months = es.network_months(es.month_first(mk), GRAPH_WINDOW, "M")
    acc = None
    for m in months:
        a = es.load_pairs(cache_dir, meta, m)
        if len(a) != n * n:
            raise ChainError("網の大きさが違う")
        acc = a if acc is None else array.array("I", map(operator.add, acc, a))
    marg = [0] * n
    total = 0
    for m in months:
        for i in range(n):
            marg[i] += meta["month_v1"][m][i]
        total += meta["month_docs"][m]
    nb = es.neighbors_from_matrix(acc, n, marg, total)["lift10"]
    lab, _sw = eg.label_propagation(eg.union_graph(nb, acc, n))
    return months, nb, lab


def month_features(mk, h1, h2, lab, dur, targets, fam, mondays, n):
    """月 mk の予言日の対象の行の励起の量。{(週の番号, タグの番号): array('d')}。"""
    out = {}
    for ti, t in enumerate(mondays):
        if es.month_key(t) != mk:
            continue
        ew = week_weights([dur[j][ti] for j in range(n)], n)
        fsum = [group_sums(e, fam) for e in ew]
        csum = [group_sums(e, lab) for e in ew]
        for i in targets.get(ti, ()):
            out[(ti, i)] = array.array("d", exc_features(i, h1[i], h2[i], ew, fsum, fam, csum, lab))
    return out


def _graph_task(mk):
    meta = _W["meta"]
    n = len(meta["tags"])
    months, nb, lab = graph_of_month(_W["cache_dir"], meta, mk)
    h1, h2 = hop_lists(nb, n)
    feats = month_features(mk, h1, h2, lab, _W["dur"], _W["targets"], _W["fam"], _W["mondays"], n)
    r1 = reverse_csr(h1, n)
    r2 = reverse_csr(h2, n)
    fwd = (csr(h1), csr(h2)) if mk in _W["case_months"] else None
    return {"mk": mk, "months": months, "rev1": r1, "rev2": r2, "lab": lab, "feats": feats, "fwd": fwd,
            "edges1": sum(len(x) for x in h1), "edges2": sum(len(x) for x in h2)}


# ---------------------------------------------------------------------------
# 記述の数（本物とずらした系列で同じ関数）
# ---------------------------------------------------------------------------

def shift_rows(rows_by_tag, offsets):
    """タグごとの bytes を、offsets[i] だけ輪のようにずらす（ずらした値[w] = 元[(w + o) mod W]）。"""
    return [r[o:] + r[:o] if o else r for r, o in zip(rows_by_tag, offsets)]


def describe_counts(tgt, isl, aft, rev_of_week, fam, comm, famsea, nseas):
    """関係ごと・ずれ k ごとの数と、海域どうしの順序の数。

    tgt[i][w]：対象なら 1。isl[i][w]：島の印（倍率の番号のビット）。aft[i][w]：AFTER_CODE。
    rev_of_week(w)：週 w の網の (rev1, rev2)（それぞれ (off, j)。A → A を隣に持つ B）。
    fam・comm：関係に使う海域の番号（負なら関係に数えない）。famsea：順序に使う系統の海域の番号（0〜nseas-1）。
    戻り値：{"rel": {(倍率, 種類, 関係, k): [島, 組, 期待(none), 島(none の期待のある週), 期待(all)]},
             "trig": {(倍率, 種類): きっかけの数}, "order": {(倍率, 種類, K): (obs[x][y], pairs[x][y])}, "base": {倍率: [Y の割合]}}
    """
    n = len(tgt)
    W = len(tgt[0]) if n else 0
    N = [bytes(tgt[i][w] for i in range(n)) for w in range(W)]
    ISL = [bytes(isl[i][w] for i in range(n)) for w in range(W)]
    AFT = [bytes(aft[i][w] for i in range(n)) for w in range(W)]
    TL = [[i for i in range(n) if N[w][i]] for w in range(W)]
    IL = [[[i for i in range(n) if ISL[w][i] >> mi & 1] for w in range(W)] for mi in range(len(MULTIPLIERS))]
    NSY = [[0] * nseas for _ in range(W)]
    ISY = [[[0] * nseas for _ in range(W)] for _mi in MULTIPLIERS]
    for w in range(W):
        for i in TL[w]:
            NSY[w][famsea[i]] += 1
        for mi in range(len(MULTIPLIERS)):
            for i in IL[mi][w]:
                ISY[mi][w][famsea[i]] += 1
    base = {}
    for mi, m in enumerate(MULTIPLIERS):
        tot = [sum(NSY[w][y] for w in range(W)) for y in range(nseas)]
        isy = [sum(ISY[mi][w][y] for w in range(W)) for y in range(nseas)]
        base[m] = [isy[y] / tot[y] if tot[y] else None for y in range(nseas)]
    rel = collections.defaultdict(lambda: [0, 0, 0.0, 0, 0.0])
    trig = collections.Counter()
    order = {}
    for mi, m in enumerate(MULTIPLIERS):
        for kind in ORDER_KINDS:
            for K in ORDER_KS:
                order[(m, kind, K)] = ([[0] * nseas for _ in range(nseas)], [[0] * nseas for _ in range(nseas)])
    for w in range(W - 1):
        ks = [k for k in LAGS if w + k < W]
        (o1, j1), (o2, j2) = rev_of_week(w)
        for mi, m in enumerate(MULTIPLIERS):
            t_all = IL[mi][w]
            for kind in TRIGGER_KINDS:
                T = t_all if kind == "all" else [a for a in t_all if AFT[w][a] == KIND_CODE[kind]]
                if not T:
                    continue
                trig[(m, kind)] += len(T)
                c1, c2, ch = [0] * n, [0] * n, [0] * n
                selfT = bytearray(n)
                for a in T:
                    selfT[a] = 1
                    fa, ca = fam[a], comm[a]
                    for off, js, cc in ((o1, j1, c1), (o2, j2, c2)):
                        for p in range(off[a], off[a + 1]):
                            b = js[p]
                            cc[b] += 1
                            if not ((fa >= 0 and fam[b] == fa) or (ca >= 0 and comm[b] == ca)):
                                ch[b] += 1
                tf = collections.Counter(fam[a] for a in T if fam[a] >= 0)
                tc = collections.Counter(comm[a] for a in T if comm[a] >= 0)
                tfc = collections.Counter((fam[a], comm[a]) for a in T if fam[a] >= 0 and comm[a] >= 0)
                nT = len(T)
                cf = [(tf.get(fam[b], 0) - selfT[b]) if fam[b] >= 0 else 0 for b in range(n)]
                cc_ = [(tc.get(comm[b], 0) - selfT[b]) if comm[b] >= 0 else 0 for b in range(n)]
                cfc = [(tfc.get((fam[b], comm[b]), 0) - selfT[b]) if (fam[b] >= 0 and comm[b] >= 0) else 0
                       for b in range(n)]
                cn = [nT - selfT[b] - cf[b] - cc_[b] + cfc[b] - ch[b] for b in range(n)]
                cols = (("hop1", c1), ("hop2", c2), ("family", cf), ("community", cc_), ("none", cn))
                for k in ks:
                    w2 = w + k
                    tl, il = TL[w2], IL[mi][w2]
                    ra = (len(il) / len(tl)) if tl else None
                    vals = [(r, sum(map(c.__getitem__, il)), sum(map(c.__getitem__, tl))) for r, c in cols]
                    on, pn = vals[-1][1], vals[-1][2]
                    rn = on / pn if pn else None
                    for r, o, p in vals:
                        acc = rel[(m, kind, r, k)]
                        acc[0] += o
                        acc[1] += p
                        if rn is not None:
                            acc[2] += p * rn
                            acc[3] += o
                        if ra is not None:
                            acc[4] += p * ra
                if kind in ORDER_KINDS:
                    tx = [0] * nseas
                    for a in T:
                        tx[famsea[a]] += 1
                    for K in ORDER_KS:
                        kk = [k for k in ks if k <= K]
                        sy = [sum(ISY[mi][w + k][y] for k in kk) for y in range(nseas)]
                        ny = [sum(NSY[w + k][y] for k in kk) for y in range(nseas)]
                        ob, pa = order[(m, kind, K)]
                        for x in range(nseas):
                            if not tx[x]:
                                continue
                            for y in range(nseas):
                                ob[x][y] += tx[x] * sy[y]
                                pa[x][y] += tx[x] * ny[y]
    return {"rel": {k: list(v) for k, v in rel.items()}, "trig": dict(trig), "order": order, "base": base}


def null_offsets(n, W, r_count=NULL_R, seed=NULL_SEED):
    """ずらす週数（1〜W-1）。[本数][タグ]。0 本目（本物）は含めない。"""
    rng = random.Random(seed)
    return [[rng.randrange(1, W) for _ in range(n)] for _ in range(r_count)]


def _init_desc(tgt, isl, aft, revs, week_mk, fam, comm, famsea, nseas, offsets):
    _W.update(tgt=tgt, isl=isl, aft=aft, revs=revs, week_mk=week_mk, fam=fam, comm=comm, famsea=famsea,
              nseas=nseas, offsets=offsets)


def _desc_task(r):
    n = len(_W["tgt"])
    offs = [0] * n if r == 0 else _W["offsets"][r - 1]
    revs, week_mk = _W["revs"], _W["week_mk"]
    res = describe_counts(shift_rows(_W["tgt"], offs), shift_rows(_W["isl"], offs), shift_rows(_W["aft"], offs),
                          lambda w: revs[week_mk[w]], _W["fam"], _W["comm"], _W["famsea"], _W["nseas"])
    return r, res


# ---------------------------------------------------------------------------
# 比の作り方
# ---------------------------------------------------------------------------

def band_values(rel, m, kind, r, lo, hi):
    """k = lo〜hi を足した [島, 組, 期待(none), 島(none の期待のある週), 期待(all)]。"""
    acc = [0, 0, 0.0, 0, 0.0]
    for k in range(lo, hi + 1):
        v = rel.get((m, kind, r, k))
        if v is None:
            continue
        for j in range(5):
            acc[j] += v[j]
    return acc


def ratios(acc):
    """(ratio_none, ratio_all)。期待が 0 なら None。"""
    rn = acc[3] / acc[2] if acc[2] > 0 else None
    ra = acc[0] / acc[4] if acc[4] > 0 else None
    return rn, ra


def lift_table(order_res, base, m, kind, K, nseas):
    """lift[x][y] = (obs/pairs) / base_y。"""
    ob, pa = order_res[(m, kind, K)]
    out = [[None] * nseas for _ in range(nseas)]
    for x in range(nseas):
        for y in range(nseas):
            b = base[m][y]
            if pa[x][y] > 0 and b:
                out[x][y] = (ob[x][y] / pa[x][y]) / b
    return out


def asym(lift, x, y):
    a, b = lift[x][y], lift[y][x]
    if a is None or b is None or a <= 0 or b <= 0:
        return None
    return math.log(a / b)


# ---------------------------------------------------------------------------
# 事例
# ---------------------------------------------------------------------------

def case_weeks(mondays):
    return [ti for ti, t in enumerate(mondays) if CASE_FIRST <= t <= CASE_LAST]


def islands_of_week(tgt, isl, w, mi):
    return [a for a in range(len(tgt)) if tgt[a][w] and isl[a][w] >> mi & 1]


def case_links(ti, b, islands_at, fwd_of_week, fam):
    """週 ti の島 b に、1〜12週前に同じ倍率の島になった hop1・hop2 の隣・同じ系統の海域のタグがあったか。
    islands_at(w)：週 w の同じ倍率の島のタグ。網は先の島の週の月のもの（B の隣に A が入っているか）。
    戻り値：(hop1 の [(k, a)], hop2 の [(k, a)], 同じ系統の数)。"""
    l1, l2, nf = [], [], 0
    for k in LAGS:
        w = ti - k
        if w < 0:
            break
        (o1, j1, _w1), (o2, j2, _w2) = fwd_of_week(w)
        s1 = set(j1[o1[b]:o1[b + 1]])
        s2 = set(j2[o2[b]:o2[b + 1]])
        for a in islands_at(w):
            if a == b:
                continue
            if a in s1:
                l1.append((k, a))
            elif a in s2:
                l2.append((k, a))
            if fam[a] >= 0 and fam[a] == fam[b]:
                nf += 1
    return l1, l2, nf


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
    pos = {d: k for k, d in enumerate(days)}
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
    rows = {}
    for i, res in enumerate(results):
        for ti, (st, _b, _c, _m1, _m2, js, lv) in enumerate(res):
            if st == "target" and not any(x is None for x in js):
                rows[(ti, i)] = (js, lv)
    keys = sorted(rows)
    log("対象の行 %d" % len(rows))
    # 状態（t 以前だけ）
    dur = [durations([is_high(b, c, v) for (_st, b, c, _m1, _m2, _js, _lv) in results[j]]) for j in range(n)]
    high_counts = [sum(1 for j in range(n) if dur[j][ti] > 0) for ti in range(W)]
    del results
    # 島の後と跳ねの大きさ
    after = {}
    jump = {}
    for k in keys:
        js, lv = rows[k]
        if not any(js):
            continue
        t = mondays[k[0]]
        after[k] = sea.back_or_stay(sea.after_level(series[k[1]], pos, t), lv["B"], v)
        jump[k] = sea.jump_size(series[k[1]], pos, t, lv["B"])
    # 月ごとの網・励起の量
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
    fam_pred = [-1 if f == "その他" else k for f, k in zip(fam_names, index_of(fam_names))]
    targets_by_week = collections.defaultdict(list)
    for (ti, i) in keys:
        targets_by_week[ti].append(i)
    pred_months = sorted({es.month_key(t) for t in mondays})
    net_off = None
    for t in mondays:
        off = es.check_network_before(t, es.network_months(t, GRAPH_WINDOW, "M"))
        net_off = off if net_off is None else max(net_off, off)
    cw = case_weeks(mondays)
    case_months = sorted({es.month_key(mondays[w]) for ti in cw for w in range(max(0, ti - max(LAGS)), ti + 1)})
    graphs = {}
    feats = {}
    with es._pool(workers, _init_graph, (t117_cache, small, dur, dict(targets_by_week), fam_pred, mondays,
                                         set(case_months))) as pool:
        for k, g in enumerate(pool.imap(_graph_task, pred_months), 1):
            if g["months"] != es.network_months(es.month_first(g["mk"]), GRAPH_WINDOW, "M"):
                raise ChainError("網の月が違う")
            feats.update(g.pop("feats"))
            graphs[g["mk"]] = g
            log("網 %d / %d（%d）" % (k, len(pred_months), g["mk"]))
    for ti, t in enumerate(mondays):
        if graphs[es.month_key(t)]["months"] != es.network_months(t, GRAPH_WINDOW, "M"):
            raise ChainError("予言日の網の月が違う")
        es.check_network_before(t, graphs[es.month_key(t)]["months"])
    if sorted(feats) != keys:
        raise ChainError("励起の量の行が対象の行と合わない")
    # 海域（T-125 と同じ決め方）
    comm_names = sea.community_seas([graphs[m]["lab"] for m in sea.COMM_MONTHS], n)
    seas = {"family": fam_names, "community": comm_names}
    fam_rel = fam_pred
    comm_idx = index_of(comm_names)
    comm_rel = [-1 if c == "小さな群れ" else k for c, k in zip(comm_names, comm_idx)]
    fam_order = sorted(set(fam_names), key=lambda s: (-fam_names.count(s), s))
    famsea = [fam_order.index(f) for f in fam_names]
    # 記述の並び
    tgt = [bytearray(W) for _ in range(n)]
    isl = [bytearray(W) for _ in range(n)]
    aft = [bytearray(W) for _ in range(n)]
    for (ti, i) in keys:
        js = rows[(ti, i)][0]
        tgt[i][ti] = 1
        isl[i][ti] = sum(1 << mi for mi, x in enumerate(js) if x)
        if any(js):
            aft[i][ti] = AFTER_CODE[after[(ti, i)]]
    tgt, isl, aft = [bytes(x) for x in tgt], [bytes(x) for x in isl], [bytes(x) for x in aft]
    revs = {mk: (g["rev1"], g["rev2"]) for mk, g in graphs.items()}
    week_mk = [es.month_key(t) for t in mondays]
    offsets = null_offsets(n, W)
    desc = [None] * (NULL_R + 1)
    with es._pool(workers, _init_desc, (tgt, isl, aft, revs, week_mk, fam_rel, comm_rel, famsea, len(fam_order),
                                        offsets)) as pool:
        for k, (r, res) in enumerate(pool.imap(_desc_task, range(NULL_R + 1)), 1):
            desc[r] = res
            if k % 10 == 0:
                log("記述 %d / %d 本" % (k, NULL_R + 1))
    # 事例
    fwd = {mk: graphs[mk]["fwd"] for mk in case_months}
    case = []
    for mi, m in enumerate(MULTIPLIERS):
        il = {w: islands_of_week(tgt, isl, w, mi) for w in range(max(0, cw[0] - max(LAGS)), cw[-1] + 1)}
        for ti in cw:
            for b in il[ti]:
                l1, l2, nf = case_links(ti, b, il.__getitem__, lambda w: fwd[week_mk[w]], fam_rel)
                case.append((ti, b, m, l1, l2, nf))
    log("事例を数えた")
    info = {"daily_min_read": lo.isoformat(), "daily_max_read": hi.isoformat(), "network_last_day_minus_t_max_days": net_off,
            "graph_months": pred_months, "case_months": case_months, "high_counts": high_counts,
            "edges": {str(mk): [g["edges1"], g["edges2"]] for mk, g in sorted(graphs.items())}}
    del graphs, revs
    files = evaluate_and_build(tags, mondays, rows, keys, feats, desc, case, seas, fam_order, after, jump, v, ctx,
                               info, workers, log)
    return write_outputs(out_dir, files)


def index_of(names):
    """名前を、出てきた順の番号にする。"""
    idx = {}
    return [idx.setdefault(s, len(idx)) for s in names]


# ---------------------------------------------------------------------------
# 予測の評価（子プロセス）
# ---------------------------------------------------------------------------

def _init_fit(base_tb, extra, split_idx, p0):
    _W.update(base_tb=base_tb, extra=extra, split_idx=split_idx, p0=p0)


def _fit_task(args):
    sp, m, name, cols = args
    tb = dict(_W["base_tb"][m])
    for c in cols:
        tb[c] = _W["extra"][c]
    tri, tei = _W["split_idx"][sp]
    fit, _p, x = ed.fit_eval(tb, m, ed.naive_cols(m) + list(cols), tri, tei, _W["p0"][(sp, m)])
    return sp, m, name, x, list(fit["coef"])


def evaluate_models(rows, keys, mondays, tags, v, feats, workers, log):
    idx = {k: r for r, k in enumerate(keys)}
    base_tb = {m: ed.make_table(rows, keys, mondays, tags, m, v) for m in MULTIPLIERS}
    extra = {c: array.array("d", [feats[k][j] for k in keys]) for j, c in enumerate(EXC_COLUMNS)}
    split_idx = {}
    for sp in SPLITS:
        tr, te = ed.split_rows(keys, mondays, sp)
        split_idx[sp] = ([idx[k] for k in tr], [idx[k] for k in te])
    p0, out, coefs = {}, [], []
    for sp in SPLITS:
        for m in MULTIPLIERS:
            fit, p0[(sp, m)], x0 = ed.fit_eval(base_tb[m], m, ed.naive_cols(m), *split_idx[sp])
            out.append((sp, m, "naive", x0))
            coefs.append((sp, m, "naive", ["intercept"] + list(naive.FEATURES), list(fit["coef"])))
    log("素朴な予測を当てはめた")
    tasks = [(sp, m, name, cols) for sp in SPLITS for m in MULTIPLIERS for name, cols in models()]
    colnames = {name: cols for name, cols in models()}
    with es._pool(workers, _init_fit, (base_tb, extra, split_idx, p0)) as pool:
        for k, (sp, m, name, x, coef) in enumerate(pool.imap(_fit_task, tasks), 1):
            out.append((sp, m, name, x))
            coefs.append((sp, m, name, ["intercept"] + list(naive.FEATURES) + list(colnames[name]), coef))
            if k % 20 == 0:
                log("モデル %d / %d" % (k, len(tasks)))
    order = {(sp, m, name): r for r, (sp, m, name) in enumerate(
        [(sp, m, "naive") for sp in SPLITS for m in MULTIPLIERS] + [(t[0], t[1], t[2]) for t in tasks])}
    out.sort(key=lambda r: order[(r[0], r[1], r[2])])
    coefs.sort(key=lambda r: order[(r[0], r[1], r[2])])
    return out, coefs, extra


# ---------------------------------------------------------------------------
# 出力
# ---------------------------------------------------------------------------

OUT_NAMES = ("relations.tsv", "sea_order.tsv", "case.tsv", "chain-private.tsv", "models.tsv", "coefs.tsv",
             "excitation.tsv", "run.json", "summary.md")
PRIVATE_HEADER = sea.PRIVATE_HEADER
f6 = es.f6


def fx(x, fmt="%.4f"):
    return "-" if x is None else fmt % x


def relation_rows(desc):
    """relations.tsv の行（dict）。"""
    real = desc[0]
    reps = desc[1:]
    out = []
    for m in MULTIPLIERS:
        for kind in TRIGGER_KINDS:
            for r in RELATIONS:
                for lo, hi in [(k, k) for k in LAGS] + list(LAG_BANDS):
                    acc = band_values(real["rel"], m, kind, r, lo, hi)
                    rn, ra = ratios(acc)
                    nn = sorted(x for x in (ratios(band_values(d["rel"], m, kind, r, lo, hi))[0] for d in reps)
                                if x is not None)
                    na = sorted(x for x in (ratios(band_values(d["rel"], m, kind, r, lo, hi))[1] for d in reps)
                                if x is not None)
                    out.append({"m": m, "kind": kind, "rel": r, "lag": "%d" % lo if lo == hi else "%d-%d" % (lo, hi),
                                "band": lo != hi, "triggers": real["trig"].get((m, kind), 0), "islands": acc[0],
                                "pairs": acc[1], "rate": acc[0] / acc[1] if acc[1] else None,
                                "exp_none": acc[2], "ratio_none": None if r == "none" else rn,
                                "null_none_med": None if r == "none" else sea.median(nn),
                                "null_none_q": None if r == "none" else nearest_rank(nn, NULL_Q),
                                "null_none_n": len(nn), "exp_all": acc[4], "ratio_all": ra,
                                "null_all_med": sea.median(na), "null_all_q": nearest_rank(na, NULL_Q)})
    return out


def order_rows(desc, fam_order):
    real, reps = desc[0], desc[1:]
    ns = len(fam_order)
    out = []
    for m in MULTIPLIERS:
        for kind in ORDER_KINDS:
            for K in ORDER_KS:
                lift = lift_table(real["order"], real["base"], m, kind, K, ns)
                rl = [lift_table(d["order"], d["base"], m, kind, K, ns) for d in reps]
                for x in range(ns):
                    for y in range(x + 1, ns):
                        a = asym(lift, x, y)
                        nl = sorted(z for z in (asym(t, x, y) for t in rl) if z is not None)
                        qlo, qhi = nearest_rank(nl, ORDER_Q[0]), nearest_rank(nl, ORDER_Q[1])
                        if a is None or qlo is None:
                            d = "分からない"
                        elif a > qhi:
                            d = "x_first"
                        elif a < qlo:
                            d = "y_first"
                        else:
                            d = "none"
                        out.append({"m": m, "kind": kind, "K": K, "x": fam_order[x], "y": fam_order[y],
                                    "lift_xy": lift[x][y], "lift_yx": lift[y][x], "asym": a, "null_lo": qlo,
                                    "null_hi": qhi, "direction": d})
    return out


def case_rows(case, mondays, seas, fam_order, after):
    """case.tsv：週・倍率・海域ごとの島の数と、先に隣・同じ系統の島があった島の数。"""
    cnt = collections.OrderedDict()
    for ti in case_weeks(mondays):
        for m in MULTIPLIERS:
            for s in fam_order:
                cnt[(ti, m, s)] = [0, 0, 0, 0, 0, 0, 0, 0]
    for ti, b, m, l1, l2, nf in case:
        c = cnt[(ti, m, seas["family"][b])]
        c[0] += 1
        a = after[(ti, b)]
        c[{"stay": 1, "back": 2, "unknown": 3}[a]] += 1
        c[4] += 1 if l1 else 0
        c[5] += 1 if l2 else 0
        c[6] += 1 if (l1 or l2) else 0
        c[7] += 1 if nf else 0
    return [(mondays[ti].isoformat(), m, s, *c) for (ti, m, s), c in cnt.items()]


def case_private_rows(case, mondays, tags, seas, after, jump):
    out = []
    for ti, b, m, l1, l2, nf in sorted(case, key=lambda r: (r[0], r[2], tags[r[1]])):
        out.append((mondays[ti].isoformat(), m, tags[b], seas["family"][b], seas["community"][b], after[(ti, b)],
                    fx(jump[(ti, b)], "%.2f"), nf, len(l1), len(l2),
                    ";".join("%d:%s" % (k, tags[a]) for k, a in sorted(l1, key=lambda z: (z[0], tags[z[1]]))) or "-",
                    ";".join("%d:%s" % (k, tags[a]) for k, a in sorted(l2, key=lambda z: (z[0], tags[z[1]]))) or "-"))
    return out


def excitation_rows(extra, keys, mondays, rows):
    """励起の量の要約（分け方ごとの学習の行）：列ごとの 0 でない割合・平均と、島（倍率 4）の行と島でない行の平均。"""
    out = []
    mi = MULTIPLIERS.index(MAIN_M)
    for sp in SPLITS:
        tr, _te = ed.split_rows(keys, mondays, sp)
        trs = set(tr)
        sel = [r for r, k in enumerate(keys) if k in trs]
        ys = [rows[keys[r]][0][mi] for r in sel]
        for c in EXC_COLUMNS:
            xs = [extra[c][r] for r in sel]
            pos_ = [x for x, y in zip(xs, ys) if y]
            neg = [x for x, y in zip(xs, ys) if not y]
            out.append((sp, c, len(xs), "%.4f" % (sum(1 for x in xs if x > 0) / len(xs)), "%.6f" % (sum(xs) / len(xs)),
                        fx(sum(pos_) / len(pos_) if pos_ else None, "%.6f"),
                        fx(sum(neg) / len(neg) if neg else None, "%.6f")))
    return out


REL_COLS = ("m", "kind", "rel", "lag", "triggers", "islands", "pairs", "rate", "exp_none", "ratio_none", "null_none_med",
            "null_none_q", "exp_all", "ratio_all", "null_all_med", "null_all_q")
ORDER_COLS = ("m", "kind", "K", "x", "y", "lift_xy", "lift_yx", "asym", "null_lo", "null_hi", "direction")


def cell(x):
    if isinstance(x, float):
        return "%.6f" % x
    if x is None:
        return "-"
    return x


def evaluate_and_build(tags, mondays, rows, keys, feats, desc, case, seas, fam_order, after, jump, v, ctx, info,
                       workers, log):
    mres, coefs, extra = evaluate_models(rows, keys, mondays, tags, v, feats, workers, log)
    return build_outputs(tags, mondays, rows, keys, extra, desc, case, seas, fam_order, after, jump, ctx, info, mres,
                         coefs)


def own_code_shas():
    code = dict(ei._LOADED_SHA, **x2.own_code_shas())
    for rel, mod in (("src/stats/explore_sea.py", sea), ("src/stats/explore_chain.py", sys.modules[__name__])):
        with open(os.path.abspath(mod.__file__), "rb") as f:
            code[rel] = hashlib.sha256(f.read()).hexdigest()
    return code


def build_outputs(tags, mondays, rows, keys, extra, desc, case, seas, fam_order, after, jump, ctx, info, mres, coefs):
    rrows = relation_rows(desc)
    orows = order_rows(desc, fam_order)
    crows = case_rows(case, mondays, seas, fam_order, after)
    relations = ei.tsv(REL_COLS, [tuple(cell(d[c]) for c in REL_COLS) for d in rrows])
    sea_order = ei.tsv(ORDER_COLS, [tuple(cell(d[c]) for c in ORDER_COLS) for d in orows])
    case_tsv = ei.tsv(("monday", "multiplier", "family_sea", "islands", "stay", "back", "unknown", "linked_hop1",
                       "linked_hop2", "linked_hop12", "linked_family"), crows)
    chain_private = PRIVATE_HEADER.encode("utf-8") + ei.tsv(
        ("monday", "multiplier", "theme", "family_sea", "community_sea", "after", "jump_size", "earlier_family",
         "earlier_hop1", "earlier_hop2", "earlier_hop1_list", "earlier_hop2_list"),
        case_private_rows(case, mondays, tags, seas, after, jump))

    def ci(x):
        c = x.get("d_ll_ci")
        return ("-", "-") if c is None else (f6(c[0]), f6(c[1]))
    models_tsv = ei.tsv(("split", "multiplier", "horizon_days", "model", "n_test", "islands_test", "logloss", "auc",
                         "top10_hits", "d_logloss_vs_naive", "d_ll_ci4w_lo", "d_ll_ci4w_hi", "d_top10_vs_naive"),
                        [(sp, m, HORIZON, name, x["n"], x["pos"], f6(x["logloss"]), f6(x["auc"]), x["topk"],
                          f6(x.get("d_logloss")), *ci(x), x.get("d_topk", "-")) for sp, m, name, x in mres])
    coefs_tsv = ei.tsv(("split", "multiplier", "model", "column", "coef"),
                       [(sp, m, name, c, f6(b)) for sp, m, name, cols, cf in coefs for c, b in zip(cols, cf)])
    exc_tsv = ei.tsv(("split", "column", "train_rows", "nonzero_share", "mean", "mean_island_m4", "mean_not_island_m4"),
                     excitation_rows(extra, keys, mondays, rows))
    run = {"label": LABEL, "code": own_code_shas(), "python": sys.version.split()[0], "refs": ctx["refs"],
           "v": "%d/%d" % (ctx["v"].numerator, ctx["v"].denominator), "rows": len(keys), "tags": len(tags),
           "options": {"lags": LAGS, "lag_bands": LAG_BANDS, "relations": RELATIONS, "trigger_kinds": TRIGGER_KINDS,
                       "graph_window": GRAPH_WINDOW, "order_ks": ORDER_KS, "order_kinds": ORDER_KINDS,
                       "null_seed": NULL_SEED, "null_r": NULL_R, "null_q": NULL_Q, "order_q": ORDER_Q,
                       "case": [CASE_FIRST.isoformat(), CASE_LAST.isoformat()], "state_mult": STATE_MULT,
                       "state_min_weeks": STATE_MIN_WEEKS, "lambdas": LAMBDAS, "exc_relations": EXC_RELATIONS,
                       "splits": SPLITS, "split_main": SPLIT_MAIN, "main_multiplier": MAIN_M},
           "info": info, "family_seas": fam_order, "models_per_multiplier_split": len(models()),
           "citation": [ei.CITATION_EN, ei.CITATION_JA]}
    files = {"relations.tsv": relations, "sea_order.tsv": sea_order, "case.tsv": case_tsv,
             "chain-private.tsv": chain_private, "models.tsv": models_tsv, "coefs.tsv": coefs_tsv,
             "excitation.tsv": exc_tsv,
             "run.json": (json.dumps(run, ensure_ascii=False, sort_keys=True, indent=1) + "\n").encode("utf-8")}
    files["summary.md"] = summary_md(run, rrows, orows, crows, mres, fam_order, tags, mondays)
    for name, data in files.items():
        ei.check_public(name, data)
    return files


def write_outputs(out_dir, files):
    if sorted(files) != sorted(OUT_NAMES):
        raise ChainError("出力の名前が決めた一覧と違う")
    os.makedirs(out_dir, exist_ok=True)
    for name in OUT_NAMES:
        if os.path.lexists(os.path.join(out_dir, name)):
            raise ChainError("書き出す先に同じ名前のファイル（%s）がある。上書きしない" % name)
    return {name: es.write_new(os.path.join(out_dir, name), files[name]) for name in OUT_NAMES}


# ---------------------------------------------------------------------------
# 要約
# ---------------------------------------------------------------------------

REL_JA = {"hop1": "網の1歩の隣", "hop2": "網の2歩先の隣", "family": "同じ系統の海域", "community": "同じ群れの海域",
          "none": "関係なし"}
KIND_JA = {"all": "すべての島", "stay": "上がったままの島", "back": "戻った島"}


def find_rel(rrows, m, kind, rel, lag):
    for d in rrows:
        if d["m"] == m and d["kind"] == kind and d["rel"] == rel and d["lag"] == lag:
            return d
    return None


def ratio_text(d):
    if d is None or d["ratio_none"] is None:
        return "分からない"
    q = d["null_none_q"]
    if q is None:
        return "%.2f 倍（偶然の水準は分からない）" % d["ratio_none"]
    return "%.2f 倍（偶然の90%%点 %.2f 倍を%s）" % (d["ratio_none"], q, "超える" if d["ratio_none"] > q else "超えない")


def summary_md(run, rrows, orows, crows, mres, fam_order, tags, mondays):
    L = []
    a = L.append
    md = ei.md_table
    a("# 島の連鎖の探索（T-127、手法を作る期間）")
    a("")
    same = sum(1 for s in fam_order if s in set(tags))
    a("この文書は `src/stats/explore_chain.py` が出力したもので、手で書き足していない。島の定義は変えていない。テーマの名前は載せていない"
      "（海域として載せた系統の名前を除く。系統の名前 %d 個のうち %d 個は、一覧に同じ名前のテーマがある）。全部並べ、選ばない・勧めない。"
      % (len(fam_order), same))
    a("")
    a("## 1. やさしい説明")
    a("")
    a("ここで「連鎖」と呼ぶのは、ある予言日に島になったタグ（きっかけ）のあと、1〜12週あとの予言日に、そのタグと関係のあるタグが"
      "島になりやすいかどうか。比は、同じ週の関係の無いタグの島の割合を1としたときの倍数。偶然の比べは、タグごとに予言日の並びを"
      "乱数で輪のようにずらした %d 本（乱数の種 %d）で同じ比を作ったときの90%%点。" % (NULL_R, NULL_SEED))
    a("")
    for kind in MAIN_KINDS:
        d0 = find_rel(rrows, MAIN_M, kind, "hop1", "1-12")
        a("- 倍率 %d の%s（きっかけ %d 件）のあと：" % (MAIN_M, KIND_JA[kind], d0["triggers"] if d0 else 0))
        for r in EXC_RELATIONS:
            parts = []
            for lo, hi in LAG_BANDS[:3]:
                parts.append("%d〜%d週後 %s" % (lo, hi, ratio_text(find_rel(rrows, MAIN_M, kind, r, "%d-%d" % (lo, hi)))))
            a("  - %s：%s。" % (REL_JA[r], "、".join(parts)))
    a("")
    for kind in MAIN_KINDS:
        ks = [(k, find_rel(rrows, MAIN_M, kind, "hop1", "%d" % k)) for k in LAGS]
        ks = [(k, d["ratio_none"]) for k, d in ks if d is not None and d["ratio_none"] is not None]
        if ks:
            kmax = max(ks, key=lambda z: (z[1], -z[0]))
            a("- 遅れ（倍率 %d、%s、網の1歩の隣）：週ごとの比は %s。比が最も大きかったのは %d 週後（%.2f 倍）。" % (
                MAIN_M, KIND_JA[kind], "、".join("%d週 %.2f" % (k, x) for k, x in ks), kmax[0], kmax[1]))
    a("")
    main_o = [d for d in orows if d["m"] == MAIN_M and d["kind"] == "all" and d["K"] == max(ORDER_KS)]
    xf = [d for d in main_o if d["direction"] in ("x_first", "y_first")]
    a("- 海域どうしの順序（倍率 %d、すべての島、%d 週以内）：系統の海域の組 %d のうち、ずらした系列の %d〜%d%% の範囲の外に出た組は %d"
      "（偶然でも約 %.1f 組は外に出る）。" % (MAIN_M, max(ORDER_KS), len(main_o), round(100 * ORDER_Q[0]),
                                    round(100 * ORDER_Q[1]), len(xf), len(main_o) * (ORDER_Q[0] + 1 - ORDER_Q[1])))
    for d in xf:
        first, second = (d["x"], d["y"]) if d["direction"] == "x_first" else (d["y"], d["x"])
        a("  - %s が先、%s があと（lift %s→%s %.2f、逆向き %.2f）。" % (
            first, second, first, second, d["lift_xy"] if d["direction"] == "x_first" else d["lift_yx"],
            d["lift_yx"] if d["direction"] == "x_first" else d["lift_xy"]))
    a("")
    weeks = sorted({r[0] for r in crows})
    a("- 事例（%s〜%s の予言日、倍率 %d）：週ごとの島の数、多い海域、上がったまま、先に（1〜12週前に）網の隣（1歩か2歩）の島が"
      "あった島の数。" % (CASE_FIRST, CASE_LAST, MAIN_M))
    for w in weeks:
        rs = [r for r in crows if r[0] == w and r[1] == MAIN_M]
        tot = sum(r[3] for r in rs)
        top = sorted([r for r in rs if r[3] > 0], key=lambda r: (-r[3], fam_order.index(r[2])))
        a("  - %s：島 %d（%s）。上がったまま %d、先に網の隣の島 %d。" % (
            w, tot, "、".join("%s %d" % (r[2], r[3]) for r in top) if top else "無し", sum(r[4] for r in rs),
            sum(r[9] for r in rs)))
    a("")
    for sp in SPLITS:
        a("- 予測（分け方 %s%s）：" % (sp, "、主" if sp == SPLIT_MAIN else "、参考"))
        for m in MULTIPLIERS:
            rs = [(name, x) for s2, m2, name, x in mres if s2 == sp and m2 == m and name != "naive"]
            nv = [x for s2, m2, name, x in mres if s2 == sp and m2 == m and name == "naive"][0]
            below = sum(1 for _n, x in rs if x["d_ll_ci"][1] < 0)
            rel_ = [100 * x["d_logloss"] / nv["logloss"] for _n, x in rs]
            a("  - 倍率 %d：素朴な予測に励起の量を足した %d のモデルの対数損失の差は %+.2f%%〜%+.2f%%。差の範囲（4週束ね）が0より下に"
              "収まったのは %d。" % (m, len(rs), min(rel_), max(rel_), below))
    a("- 2020年の連鎖は、分け方 A の検証の期間（2019-01-07〜）の中にしかない。主の分け方 B（確かめ 2018年）には入っていない。")
    a("")
    a("## 2. 作り方")
    a("- 予言日・対象・判定は T-115 と同じ（C7、V = %s、一度跳ねたタグの扱いあり、判定期間 %d 日、倍率 %s）。対象の行 %d。" % (
        run["v"], HORIZON, "・".join(str(m) for m in MULTIPLIERS), run["rows"]))
    a("- きっかけ：予言日 w に島（倍率 m）になったタグ A。上がったまま／戻ったは T-125 と同じ（t+57〜t+180 の比率の平均が max(2B, V) "
      "以下なら戻った、上なら上がったまま、t+180 が区画の外か使える日が60未満なら分からない。分からないものは「すべて」にだけ入る）。")
    a("- 関係：網の1歩の隣は、A が B の lift の上位10に入っていること。2歩先は、B の1歩の隣の、そのまた上位10（B と1歩の隣を除く）。"
      "網は w を含む月の前の12か月（T-119 と同じ）。同じ系統・同じ群れの海域は T-125 の海域（「その他」「小さな群れ」どうしは関係に"
      "数えない）。関係なしは、この4つのどれでもない組。")
    a("- 比：週 w+k の対象 B が島（同じ倍率）になった数を、組の数 × その週の関係なしの組の島の割合（期待の数）で割った。足し合わせは"
      "週ごとの期待の数の和で割る。参考に、その週の対象すべての島の割合で作った比（ratio_all）も relations.tsv に並べた。")
    a("- 偶然の比べ：タグごとに、予言日の並び（対象かどうか・島・上がったまま／戻った）を 1〜%d 週の乱数でずらした（輪のように回す）。"
      "網と海域はずらさない。%d 本、乱数の種 %d。90%%点は最近順位。" % (len(mondays) - 1, NULL_R, NULL_SEED))
    a("- 海域どうしの順序：lift(X→Y) = X の島のあと1〜K 週の Y の島の割合 ÷ Y の全週の島の割合。向きの差 log(lift(X→Y)/lift(Y→X)) が、"
      "ずらした系列の %d%%〜%d%% の範囲（最近順位）の外なら向きありとした。K = %s。" % (
          round(100 * ORDER_Q[0]), round(100 * ORDER_Q[1]), "・".join(str(k) for k in ORDER_KS)))
    a("- 予測の形：予言日 t のタグ j が高いとは、c_j(t) > max(%d × B_j(t), V)（t-1 以前のデータだけ）。続いた週数 d は、t から前へ"
      "高い予言日が続いた数。重み exp(−(d−1)/λ)（d ≥ D のとき）。D = %s、λ = %s。励起の量は、B の網の1歩・2歩の隣の重みの重み付き平均"
      "（隣の重みは T-119 と同じ）、同じ系統（名前で決まる。「その他」は 0）と同じ群れ（t を含む月の網のラベル伝播）の自分以外の平均。"
      % (STATE_MULT, "・".join(str(d) for d in STATE_MIN_WEEKS), "・".join("%g" % x for x in LAMBDAS)))
    a("- 評価：素朴な予測（naive.py の特徴量、ロジスティック回帰、リッジ 1）に足した分。主は分け方 B（学習 〜%s、確かめ %s〜%s）。"
      "分け方 A（学習 〜%s、検証 %s〜）は参考。モデルは (D, λ) ごとに4つの関係をまとめて足したもの %d と、1つずつ足したもの %d。" % (
          em.INNER_TRAIN_LAST, em.INNER_VAL_FIRST, es.TRAIN_LAST, es.TRAIN_LAST, es.TEST_FIRST, len(variants()),
          len(variants()) * len(EXC_RELATIONS)))
    a("")
    a("## 3. 連鎖の表（倍率 %d）" % MAIN_M)
    a("")
    for kind in TRIGGER_KINDS:
        a("### %s" % KIND_JA[kind])
        a("")
        a(md(["関係", "遅れ（週）", "島", "組", "割合", "比（関係なし）", "偶然の中央値", "偶然の90%点", "比（対象すべて）"],
             [(REL_JA[d["rel"]], d["lag"], d["islands"], d["pairs"], fx(d["rate"]), fx(d["ratio_none"], "%.3f"),
               fx(d["null_none_med"], "%.3f"), fx(d["null_none_q"], "%.3f"), fx(d["ratio_all"], "%.3f"))
              for d in rrows if d["m"] == MAIN_M and d["kind"] == kind and d["band"]]))
        a("")
    a("倍率 2・8 と、週ごとの値は relations.tsv。")
    a("")
    a("## 4. 海域どうしの順序（倍率 %d、すべての島、%d 週以内）" % (MAIN_M, max(ORDER_KS)))
    a("")
    a(md(["海域 x", "海域 y", "lift x→y", "lift y→x", "向きの差", "偶然の範囲", "向き"],
         [(d["x"], d["y"], fx(d["lift_xy"], "%.3f"), fx(d["lift_yx"], "%.3f"), fx(d["asym"], "%.3f"),
           "%s〜%s" % (fx(d["null_lo"], "%.3f"), fx(d["null_hi"], "%.3f")),
           {"x_first": "x が先", "y_first": "y が先", "none": "見分けられない"}.get(d["direction"], d["direction"]))
          for d in main_o]))
    a("")
    a("ほかの倍率・上がったままの島・%d 週以内は sea_order.tsv。" % min(ORDER_KS))
    a("")
    a("## 5. 予測の結果")
    a("")
    for sp in SPLITS:
        for m in MULTIPLIERS:
            rs = [(name, x) for s2, m2, name, x in mres if s2 == sp and m2 == m]
            nv = rs[0][1]
            a("### 分け方 %s%s、倍率 %d（確かめの行 %d、島 %d）" % (sp, "（主）" if sp == SPLIT_MAIN else "（参考）", m, nv["n"],
                                                       nv["pos"]))
            a("")
            a(md(["モデル", "対数損失", "AUC", "上位10の島", "素朴な予測との差（割合）", "差の範囲（4週束ね）", "上位10の差"],
                 [(name, f6(x["logloss"]), f6(x["auc"]), x["topk"],
                   "-" if name == "naive" else "%s（%+.2f%%）" % (f6(x["d_logloss"]), 100 * x["d_logloss"] / nv["logloss"]),
                   "-" if name == "naive" else "%s〜%s" % (f6(x["d_ll_ci"][0]), f6(x["d_ll_ci"][1])),
                   "-" if name == "naive" else x["d_topk"]) for name, x in rs]))
            a("")
    a("- この一覧の読み方：比べたモデルは、分け方と倍率ごとに %d（素朴な予測を除く）。多重比較の補正をしていない。4週の束どうしは"
      "独立でない（判定期間 %d 日が隣の束に重なる）。範囲が0を含まないことは、効くことの確かめにはならない。" % (
          run["models_per_multiplier_split"], HORIZON))
    a("")
    a("## 6. 予言の時点のデータだけを使ったことの確かめ")
    a("- 日の比率：ReadGuard で、入力は t-399〜t-1、判定は t+1〜t+28 の外を読むと止まる。読んだ日の範囲は %s〜%s。" % (
        run["info"]["daily_min_read"], run["info"]["daily_max_read"]))
    a("- 網：予言日ごとに、網の月が予言日を含む月の前の12か月であることと、網の最後の日 < 予言日を確かめた（最後の日 − 予言日の最大 %d 日）。"
      % run["info"]["network_last_day_minus_t_max_days"])
    a("- 状態：高いかどうかは、予言日 t の B と c（t-1 以前）だけで決め、続いた週数は t 以前の予言日の値だけから作った。"
      "島の判定の結果（判定期間が終わるまで分からない）は予測の入力に使っていない。")
    a("- 記述（1〜4章の連鎖と順序）は、区画全体の判定の結果と、T-125 の海域（群れは 2016-04〜2018-12 の網で決めたもの）を使った理解のための"
      "数で、予測の入力にはしていない。")
    a("")
    a("## 7. 限界")
    a("- 遅れは予言日の週で数えた。島は判定期間 28 日のどこかで跳ねればよいので、1〜3週の遅れは、きっかけと同じ出来事を数えうる。")
    a("- 一度跳ねたタグの扱いにより、すでに高いタグは対象にならない。連鎖の数は、あとで静かなところから跳ねたタグだけを数えている。")
    a("- 組の数は独立な件数ではない。同じ出来事で多くのタグが一緒に跳ね、毎週の判定期間が重なる。偶然の比べ（ずらした系列）は、"
      "タグごとの並びの形を残すが、週ごとの共通の動き（嵐）は壊す。比は同じ週の関係なしの割合で割っているので週ごとの動きは"
      "差し引かれるが、海域どうしの lift は全週の割合で割っているので、嵐が数週続くことも含む。")
    a("- 比べた数は多い（倍率 3 × きっかけ 3 × 関係 4 × 遅れの帯 3、海域の組 %d × 設定 %d）。偶然の90%%点を超える数は、偶然でも1割ほど出る。"
      % (len(main_o), len(MULTIPLIERS) * len(ORDER_KINDS) * len(ORDER_KS)))
    a("- 続いた週数は、最初の予言日（2016-04-11）より前を数えないので、2016年の初めは短く出る。")
    a("- 網の隣が無いとき、励起の量は 0 とした（欠けの印は足していない）。")
    a("- 一覧と V の先読み：タグの一覧と V は、手法を作る期間の区画全体のデータで決まった（seq 17）。")
    a("- 除外の規則の漏れ：民族・人物の姓・宗教・犯罪・紛争・政治に当たる名前のテーマが一覧に残っている（オーナーの決定 2026-10-16、(a)）。"
      "事例のテーマの並び（chain-private.tsv）には名前が入るので、公開しない。")
    a("- 分け方 B の確かめ（2018年）と分け方 A の検証（2019〜2020年）は、T-117〜T-125 で既に何度も見た期間の再利用で、"
      "未見のデータでの確かめにはならない。")
    a("")
    a("## 8. 再計算")
    a("```")
    a(".venv/bin/python -B src/stats/explore_chain.py --t117-cache <explore-t117-cache/run2> --out-dir <書き出す先>")
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
        raise ChainError("要約に太字の印がある")
    if "%%" in out:
        raise ChainError("要約に書式の誤り（%%）がある")
    if sea.names_in_text(out, tags, fam_order):
        raise ChainError("要約にテーマの名前がある")
    return out.encode("utf-8")


def main(argv=None):
    p = argparse.ArgumentParser(description="T-127 島の連鎖の探索")
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
    except (ChainError, sea.SeaError, x2.Diffusion2Error, ex.DiffusionError, ed.DenomError, em.ModelError,
            es.SignalError, ei.ExploreError) as e:
        sys.stderr.write("止まった：%s\n" % e)
        return 1
    for name in OUT_NAMES:
        print("%s  %s" % (shas[name], name))
    log("終わり")
    return 0


if __name__ == "__main__":
    sys.exit(main())
