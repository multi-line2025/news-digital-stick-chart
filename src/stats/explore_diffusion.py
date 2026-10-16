#!/usr/bin/env python3
"""T-123：拡散の残差と波面の勾配の探索（T-122 の続き）。

網（T-117 の月ごとの P1 の組の文書の数。予言日 t を含む月 M の前の12か月 M-12〜M-1）の上で、予言日 t の直前の上がりを
出どころとして流し、「網から見込まれる活動」と実際の活動の差（拡散の残差）と、1〜3歩先の上がりの並び（波面の勾配）を作り、
素朴な予測に足したときに島に先行するかを見る。全部並べ、選ばない・勧めない。

網（2つ）と時期（2つ）
  (a) list：一覧のタグだけ。T-117 と同じ（explore-t117-cache/run2 の網を読むだけ）。
  (b) list+excl：(a) に、除外したテーマ（seq 17 の detail で除外の語に当たったテーマ。それ以外の一覧の外のテーマは入れない）を
      点として加えたもの。除外したテーマは出どころ・通り道としてだけ使い、予言の対象にしない（オーナー決定、reviews/T-122.md）。
      線は「一覧どうし」と「一覧 × 除外」だけで、「除外どうし」の線は入れない（計算の重さのため。1日に約24万組あり、12か月分を
      持てない。限界に書く）。そのための P1 の組と、除外したテーマの日次の数は、phase1 で日の集計から読み直してキャッシュに置く。
  時期：now（M-12〜M-1）と shift（3か月前にずらした M-15〜M-4。網と信号が同じ記事から作られることの影響を見る）。
  グラフ：lift の上位10（組の文書の数 20 以上。T-117・T-119 と同じ）の隣を双方向にまとめた無向グラフ。重みは組の文書の数。
      (b) では、一覧のタグの隣の候補に除外したテーマも入り、除外したテーマの隣の候補は一覧のタグだけ。

出どころ s：予言日 t の各点の上がり log((c+V)/(B+V))（B・c は封印済みの関数。t-1 以前だけ）。決まらなければ 0。
移り変わり P：行を正規化した重み（P = D^{-1} W）。v_k = P^k s（k = 1〜K_MAX）。
  熱の拡散（heat_τ）：見込み = e^{-τ} Σ_{k=1..K} τ^k / k! v_k（e^{-τ(I−P)} s の級数から自分の k=0 の項を除いたもの）。
  再出発つきのランダムウォーク（rwr_α）：見込み = α Σ_{k=1..K} (1−α)^k v_k（同じく k=0 の項を除く）。
  拡散の残差：見込み − ハブの割り引き − 自分の上がり。ハブの割り引きは、見込みを [1, log1p(次数), 12か月の自分の報道量の log] に
  学習の行だけで回帰した当てはめ値。
波面：E1・E2・E3 = v_1・v_2・v_3（ランダムウォークの1〜3歩の重み付き平均。最短距離の隣ではない）と、
  E3 > E2 > E1 > 自分の上がり なら 1 の印。

予言の時点のデータだけ：日の比率は ReadGuard（入力は t-399〜t-1、判定は t+1〜t+28）。網の月は予言日を含む月より前で、
予言日ごとに網の最後の日 < t を確かめる（es.check_network_before）。区画の外の日の集計は開かない。

流し方（プロジェクトのルートで。TMPDIR は scratchpad の中に）
  .venv/bin/python -B src/stats/explore_diffusion.py phase1 --store <日の集計> --detail <order5-detail.json> --cache-dir <新しいフォルダ>
  .venv/bin/python -B src/stats/explore_diffusion.py phase2 --cache-dir <同じフォルダ> --t117-cache <explore-t117-cache/run2> \
      --detail <order5-detail.json> --out-dir <書き出す先>

Data: The GDELT Project (https://www.gdeltproject.org/). This project is not affiliated with or endorsed by the GDELT Project.
"""

import argparse
import array
import datetime
import gzip
import hashlib
import io
import json
import math
import operator
import os
import sys
import time
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import explore_denominator as ed  # noqa: E402

eg = ed.eg
em = ed.em
es = ed.es
ei = ed.ei
naive = ed.naive
candidates = ei.candidates
counting = ei.counting

LABEL = "explore-diffusion-t123-v1"
PHASE1_LABEL = "explore-diffusion-phase1-v1"
MULTIPLIERS = em.MULTIPLIERS
HORIZON = em.HORIZON
ITEM = array.array("I").itemsize

# ---------------------------------------------------------------------------
# 試す形（本番の前に書いた）
# ---------------------------------------------------------------------------
WINDOW_MONTHS = 12
SHIFT_MONTHS = 3
TIMINGS = ("now", "shift")
GRAPHS = ("list", "listexcl")
KNN_K = 10
MIN_PAIR_DOCS = es.MIN_PAIR_DOCS          # 20
K_MAX = 30
HEAT_TAUS = (0.5, 1.0, 2.0)
RWR_ALPHAS = (0.15, 0.3, 0.5)
KERNELS = tuple(["heat_%g" % t for t in HEAT_TAUS] + ["rwr_%g" % a for a in RWR_ALPHAS])
SPLIT_MAIN = "B"
SPLITS = ("B", "A")
DETAIL_SHA256 = "e1dbd35e85451bf1718956a90369bdb5c4ebadca48be75fdc04af97be787b5cd"   # seq 17 の outside.detail


class DiffusionError(Exception):
    pass


def kernel_coefs(kernel):
    """k = 1〜K_MAX の係数。"""
    kind, x = kernel.split("_")
    x = float(x)
    if kind == "heat":
        out, c = [], math.exp(-x)
        for k in range(1, K_MAX + 1):
            c = c * x / k
            out.append(c)
        return out
    if kind == "rwr":
        return [x * (1 - x) ** k for k in range(1, K_MAX + 1)]
    raise DiffusionError("知らない拡散 %s" % kernel)


def window_months(t, timing):
    """予言日 t の網の月。now は M-12〜M-1、shift は M-15〜M-4（区画の前の月は入れない）。"""
    if timing == "now":
        return es.network_months(t, WINDOW_MONTHS, "M")
    if timing == "shift":
        first = es.month_key(ei.BLOCK_START)
        end = es.add_months(es.month_key(t), -SHIFT_MONTHS)
        ms = [es.add_months(end, -k) for k in range(WINDOW_MONTHS, 0, -1)]
        return [m for m in ms if m >= first]
    raise DiffusionError("知らない時期")


def window_end(t, timing):
    return window_months(t, timing)[-1]


# ---------------------------------------------------------------------------
# 除外したテーマ（seq 17 の detail）
# ---------------------------------------------------------------------------

def load_excluded(detail_path, ctx):
    """detail の sha256 を seq 17 の outside と照らし、除外の語に当たったテーマの名前（名前の順）を返す。"""
    data = ei.read_nofollow(detail_path)
    if hashlib.sha256(data).hexdigest() != DETAIL_SHA256:
        raise DiffusionError("detail の sha256 が seq 17 の outside と違う")
    d = json.loads(data.decode("utf-8"))
    res = d["official_result"]
    if res["tag_list"] != ctx["tags"]:
        raise DiffusionError("detail の一覧が seq 17 の一覧と違う")
    names = sorted(t["name"] for t in res["themes"] if t["exclusion_matches"])
    if set(names) & set(ctx["tags"]):
        raise DiffusionError("除外したテーマが一覧に入っている")
    return names


# ---------------------------------------------------------------------------
# phase1：除外したテーマの日次の数と、一覧 × 除外の P1 の組（月ごと）
# ---------------------------------------------------------------------------

_W = {}


def _init_p1(store, tags, excl, cache_dir):
    _W.update(store=store, tags=tuple(tags), excl=tuple(excl), cache_dir=cache_dir,
              li={t: i for i, t in enumerate(tags)}, ei_={t: j for j, t in enumerate(excl)})


def parse_el_pairs(data, li, ei_, el, ne):
    """日の集計の P1 の組のうち、一覧のタグと除外したテーマの組を el（一覧 × 除外の配列）に足す。翻訳の組は数えない。"""
    vocab = {}
    for raw in gzip.GzipFile(fileobj=io.BytesIO(data)):
        tag, _s, rest = raw.partition(b"\t")
        if tag == b"V":
            i, name = rest.rstrip(b"\n").split(b"\t")
            n = name.decode("ascii")
            if n in li:
                vocab[int(i)] = (0, li[n])
            elif n in ei_:
                vocab[int(i)] = (1, ei_[n])
        elif tag == b"P1":
            g, a, b, k = rest.split(b"\t")
            if g.endswith(b"T"):
                continue
            x = vocab.get(int(a))
            y = vocab.get(int(b))
            if x is None or y is None or x[0] == y[0]:
                continue
            if x[0] == 0:
                el[x[1] * ne + y[1]] += int(k)
            else:
                el[y[1] * ne + x[1]] += int(k)


def _month_task(args):
    mk, items = args
    tags, excl = _W["tags"], _W["excl"]
    nl, ne = len(tags), len(excl)
    el = array.array("I", bytes(ITEM * nl * ne))
    days = []
    for day, file_name, sha, missing in items:
        if datetime.date.fromisoformat(day) >= ei.NEXT_BLOCK_START:
            raise DiffusionError("区画の外の日を読もうとした")
        data = ei.read_nofollow(os.path.join(_W["store"], file_name))
        if hashlib.sha256(data).hexdigest() != sha:
            raise DiffusionError("%s：日の集計の sha256 が違う" % day)
        summary = counting.parse_day(data, expect_day=day, expect_mode=counting.OFFICIAL_MODE)
        n7, d7 = counting.candidate_counts(summary, "C7")
        n1, _d1 = counting.candidate_counts(summary, "C1")
        del summary
        if not missing:
            parse_el_pairs(data, _W["li"], _W["ei_"], el, ne)
        days.append((day, d7, array.array("I", [n7.get(t, 0) for t in excl]).tobytes(),
                     array.array("I", [n1.get(t, 0) for t in excl]).tobytes()))
    blob = zlib.compress(el.tobytes(), 6)
    es.check_free(_W["cache_dir"])
    sha = es.write_new(os.path.join(_W["cache_dir"], "el-%06d.bin.z" % mk), blob)
    return mk, days, sha, len(blob)


def phase1(root, store, detail, cache_dir, workers, log):
    ctx = ei.load_context(root)
    excl = load_excluded(detail, ctx)
    if os.path.lexists(cache_dir):
        raise DiffusionError("キャッシュのフォルダが既にある。上書きしない")
    es.check_free(os.path.dirname(os.path.abspath(cache_dir)))
    os.mkdir(cache_dir)
    days, rows, missing = ctx["days"], ctx["rows"], ctx["missing"]
    months = sorted({es.month_key(d) for d in days})
    tasks = [(mk, [(d.isoformat(), rows[d.isoformat()]["file_name"], rows[d.isoformat()]["sha256"], d in missing)
                   for d in days if es.month_key(d) == mk]) for mk in months]
    by_day, el_files = {}, {}
    with es._pool(workers, _init_p1, (store, ctx["tags"], excl, cache_dir)) as pool:
        for k, (mk, dout, sha, size) in enumerate(pool.imap(_month_task, tasks), 1):
            el_files[str(mk)] = {"file": "el-%06d.bin.z" % mk, "sha256": sha, "bytes": size}
            for r in dout:
                by_day[r[0]] = r
            log("月 %d / %d（%d）" % (k, len(tasks), mk))
    order = [d.isoformat() for d in days]
    bad = [d for d in order if by_day[d][1] != ctx["denom"][d]]
    if bad:
        raise DiffusionError("C7 の分母が順番4の一覧と違う日がある（最初は %s）" % bad[0])
    files = {}
    es.check_free(cache_dir)
    for name, k in (("excl_c7.bin.z", 2), ("excl_v1.bin.z", 3)):
        blob = zlib.compress(b"".join(by_day[d][k] for d in order), 6)
        files[name] = {"sha256": es.write_new(os.path.join(cache_dir, name), blob), "bytes": len(blob)}
    meta = {"label": PHASE1_LABEL, "tags": ctx["tags"], "excluded": excl, "days": order,
            "missing": sorted(d.isoformat() for d in missing), "refs": ctx["refs"], "el_files": el_files,
            "files": files, "itemsize": ITEM, "byteorder": sys.byteorder, "detail_sha256": DETAIL_SHA256,
            "code": dict(ei._LOADED_SHA, **own_code_shas())}
    data = (json.dumps(meta, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")
    return es.write_new(os.path.join(cache_dir, "phase1.json"), data)


def own_code_shas():
    out = dict(ed.own_code_shas())
    with open(os.path.abspath(__file__), "rb") as f:
        out["src/stats/explore_diffusion.py"] = hashlib.sha256(f.read()).hexdigest()
    return out


def load_cache(cache_dir, ctx, excl):
    raw = ei.read_nofollow(os.path.join(cache_dir, "phase1.json"))
    meta = json.loads(raw.decode("utf-8"))
    if meta.get("label") != PHASE1_LABEL or meta["tags"] != ctx["tags"] or meta["excluded"] != excl or \
            meta["refs"] != ctx["refs"] or meta["days"] != [d.isoformat() for d in ctx["days"]] or \
            meta["missing"] != sorted(d.isoformat() for d in ctx["missing"]) or meta["itemsize"] != ITEM or \
            meta["byteorder"] != sys.byteorder:
        raise DiffusionError("キャッシュが封印の記録・detail・この計算機と合わない")
    for name in ("excl_c7.bin.z", "excl_v1.bin.z"):
        data = ei.read_nofollow(os.path.join(cache_dir, name))
        if hashlib.sha256(data).hexdigest() != meta["files"][name]["sha256"]:
            raise DiffusionError("キャッシュの %s の sha256 が違う" % name)
        a = array.array("I")
        a.frombytes(zlib.decompress(data))
        meta[name[:-6]] = a
    meta["phase1_sha256"] = hashlib.sha256(raw).hexdigest()
    return meta


def load_el(cache_dir, meta, mk):
    f = meta["el_files"][str(mk)]
    data = ei.read_nofollow(os.path.join(cache_dir, f["file"]))
    if hashlib.sha256(data).hexdigest() != f["sha256"]:
        raise DiffusionError("キャッシュの %s の sha256 が違う" % f["file"])
    a = array.array("I")
    a.frombytes(zlib.decompress(data))
    return a


# ---------------------------------------------------------------------------
# グラフ
# ---------------------------------------------------------------------------

def knn_lift(cands, ni, marg, total, k=KNN_K):
    """cands：[(j, n_ij)]。組の文書の数 MIN_PAIR_DOCS 以上の相手の、lift の上位 k（同じなら番号の小さい方）。"""
    if ni <= 0:
        return []
    sc = [((x * total) / (ni * marg[j]), j, x) for j, x in cands if x >= MIN_PAIR_DOCS and marg[j] > 0]
    sc.sort(key=lambda z: (-z[0], z[1]))
    return [(j, x) for _s, j, x in sc[:k]]


def build_graph(ll, el, nl, ne, marg_l, marg_e, total, with_excl):
    """無向の隣接（{j: 重み}）。点の番号は一覧 0..nl-1、除外 nl..nl+ne-1。"""
    n = nl + (ne if with_excl else 0)
    adj = [dict() for _ in range(n)]
    marg = (marg_l + marg_e) if with_excl else marg_l
    for i in range(nl):
        row = ll[i * nl:(i + 1) * nl]
        cands = [(j, x) for j, x in enumerate(row) if x and j != i]
        if with_excl:
            erow = el[i * ne:(i + 1) * ne]
            cands += [(nl + j, x) for j, x in enumerate(erow) if x]
        for j, x in knn_lift(cands, marg_l[i], marg, total):
            adj[i][j] = x
            adj[j][i] = x
    if with_excl:
        for e in range(ne):
            col = el[e::ne]
            cands = [(i, x) for i, x in enumerate(col) if x]
            for i, x in knn_lift(cands, marg_e[e], marg_l, total):
                adj[nl + e][i] = x
                adj[i][nl + e] = x
    return adj


def transition(adj):
    """行を正規化した移り変わり（各点の [(j, 重み/和)]）。線の無い点は空。"""
    out = []
    for a in adj:
        s = sum(a.values())
        out.append([(j, w / s) for j, w in sorted(a.items())] if s > 0 else [])
    return out


def powers(P, s, kmax=K_MAX):
    """v_k = P^k s（k = 1..kmax）。"""
    out = []
    v = s
    for _ in range(kmax):
        v = [sum(w * v[j] for j, w in row) for row in P]
        out.append(v)
    return out


def diffusion_features(vks, own, idx):
    """点 idx の、拡散ごとの見込みと、E1〜E3・並びの印。"""
    out = {}
    for kern in KERNELS:
        cs = kernel_coefs(kern)
        out[kern] = sum(c * vk[idx] for c, vk in zip(cs, vks))
    e1, e2, e3 = vks[0][idx], vks[1][idx], vks[2][idx]
    out["E1"], out["E2"], out["E3"] = e1, e2, e3
    out["mono"] = 1.0 if (e3 > e2 > e1 > own) else 0.0
    return out


# ---------------------------------------------------------------------------
# 子プロセス：窓（網の最後の月）ごとにグラフを作り、その窓を使う予言日の対象の値を出す
# ---------------------------------------------------------------------------

def _init_graph(t117_cache, m117_small, cache_dir, meta_small, plan, rises):
    _W.update(t117=t117_cache, m117=m117_small, cache_dir=cache_dir, meta=meta_small, plan=plan, rises=rises)


def _graph_chunk(ends):
    """ends：窓の最後の月の並び（続き）。12か月の和を1か月ずつ足し引きして作る。"""
    m117, meta, plan = _W["m117"], _W["meta"], _W["plan"]
    nl, ne = len(m117["tags"]), len(meta["excluded"])
    first_block = es.month_key(ei.BLOCK_START)
    ll = el = None
    cur = []
    out = []
    for end in ends:
        want = [m for m in (es.add_months(end, -k) for k in range(WINDOW_MONTHS - 1, -1, -1)) if m >= first_block]
        for m in [m for m in cur if m not in want]:
            ll = array.array("I", map(operator.sub, ll, es.load_pairs(_W["t117"], m117, m)))
            el = array.array("I", map(operator.sub, el, load_el(_W["cache_dir"], meta, m)))
        for m in [m for m in want if m not in cur]:
            a = es.load_pairs(_W["t117"], m117, m)
            b = load_el(_W["cache_dir"], meta, m)
            ll = a if ll is None else array.array("I", map(operator.add, ll, a))
            el = b if el is None else array.array("I", map(operator.add, el, b))
        cur = want
        marg_l = [sum(m117["month_v1"][m][i] for m in want) for i in range(nl)]
        marg_e = [sum(meta["month_excl_v1"][m][e] for m in want) for e in range(ne)]
        total = sum(m117["month_docs"][m] for m in want)
        for g in GRAPHS:
            with_excl = g == "listexcl"
            adj = build_graph(ll, el, nl, ne, marg_l, marg_e, total, with_excl)
            P = transition(adj)
            deg = [len(a) for a in adj[:nl]]
            for (ti, timing, t_iso, targets) in plan.get(end, []):
                t = datetime.date.fromisoformat(t_iso)
                if window_months(t, timing) != want:
                    raise DiffusionError("窓の月が予言日の月と合わない")
                es.check_network_before(t, want)
                r = _W["rises"][ti]
                s = list(r[:nl]) + (list(r[nl:]) if with_excl else [])
                vks = powers(P, s, K_MAX)
                for i in targets:
                    f = diffusion_features(vks, s[i], i)
                    f["deg"] = deg[i]
                    f["vol"] = math.log(marg_l[i] + 1.0)
                    out.append(((ti, i), g, timing, f))
    return out


def chunks_of(ends, n):
    """続いた月の並びを n 個のかたまりに分ける。"""
    size = -(-len(ends) // n)
    return [ends[k:k + size] for k in range(0, len(ends), size)]


# ---------------------------------------------------------------------------
# 除外したテーマの上がり（子プロセス）
# ---------------------------------------------------------------------------

def rises_of(days, values, mondays, v):
    """予言日ごとの上がり log((c+V)/(B+V))（B・c は封印済みの関数。t-371〜t-1 だけを読む）。決まらなければ None。"""
    get = ei.ReadGuard(days, values)
    out = []
    for t in mondays:
        get.allow(t - datetime.timedelta(days=candidates.BASELINE_WINDOW_DAYS + candidates.SMOOTHING_DAYS - 1),
                  t - datetime.timedelta(days=1))
        b = candidates.baseline_level(get, t)
        c = candidates.current_level(get, t) if b is not None else None
        out.append(None if (b is None or c is None) else es.rise(c, b, v))
    return out


def _init_rises(days, mondays, v, counts, totals, missing_flags, ne):
    _W.update(days=days, mondays=mondays, v=v, counts=counts, totals=totals, miss=missing_flags, ne=ne)


def excl_series(counts, totals, missing_flags, ne, e):
    """除外したテーマ e の日の比率（C7 の数え方。欠けた日は None）。"""
    return [None if missing_flags[di] else counts[di * ne + e] / tot for di, tot in enumerate(totals)]


def _rises_task(rng):
    out = []
    for e in rng:
        values = excl_series(_W["counts"], _W["totals"], _W["miss"], _W["ne"], e)
        out.append((e, rises_of(_W["days"], values, _W["mondays"], _W["v"])))
    return out


# ---------------------------------------------------------------------------
# phase2
# ---------------------------------------------------------------------------

def phase2(root, cache_dir, t117_cache, detail, out_dir, workers, graph_workers, log):
    ctx = ei.load_context(root)
    excl = load_excluded(detail, ctx)
    meta = load_cache(cache_dir, ctx, excl)
    m117 = es.load_cache(t117_cache, ctx)
    tags, v = ctx["tags"], ctx["v"]
    nl, ne = len(tags), len(excl)
    days = ctx["days"]
    mondays = ei.prediction_mondays()
    missing = set(meta["missing"])
    # 一覧のタグ：T-115 と同じ（C7・V）
    series = es.daily_series(m117)
    del m117["weekc"]
    results = ed.evaluate_variant(series, days, mondays, v, workers, log, "一覧")
    rows = ed.variant_rows(results, mondays, tags, v)
    rises = [[None] * (nl + ne) for _ in mondays]
    lo = hi = None
    for i, res in enumerate(results):
        for ti, (st, b, c, _m1, _m2, _js, _lv) in enumerate(res):
            if b is not None and c is not None:
                rises[ti][i] = es.rise(c, b, v)
    del results, series
    log("一覧の対象の行 %d" % len(rows))
    # 除外したテーマの上がり（C7 の数え方）
    totals = [ctx["denom"][d] for d in meta["days"]]
    mflags = [d in missing for d in meta["days"]]
    ranges = [range(a, min(a + 64, ne)) for a in range(0, ne, 64)]
    with es._pool(workers, _init_rises, (days, mondays, v, meta["excl_c7"], totals, mflags, ne)) as pool:
        for k, out in enumerate(pool.imap(_rises_task, ranges), 1):
            for e, rr in out:
                for ti, x in enumerate(rr):
                    rises[ti][nl + e] = x
            if k % 50 == 0:
                log("除外したテーマの上がり %d / %d かたまり" % (k, len(ranges)))
    rises = [array.array("d", [0.0 if x is None else x for x in r]) for r in rises]
    # 月ごとの V1 の文書の数
    month_v1, month_docs, month_excl_v1 = {}, {}, {}
    exv1 = meta["excl_v1"]
    for di, d in enumerate(m117["days"]):
        if d in missing:
            continue
        mk = es.month_key(datetime.date.fromisoformat(d))
        mv = month_v1.setdefault(mk, [0] * nl)
        for i in range(nl):
            mv[i] += m117["v1"][di * nl + i]
        me = month_excl_v1.setdefault(mk, [0] * ne)
        for e in range(ne):
            me[e] += exv1[di * ne + e]
        month_docs[mk] = month_docs.get(mk, 0) + m117["docs"][di]
    # 計画：窓の最後の月 → [(週, 時期, 予言日, 対象の番号)]
    targets_by_t = {}
    for (ti, i) in rows:
        targets_by_t.setdefault(ti, []).append(i)
    plan = {}
    for ti, t in enumerate(mondays):
        for timing in TIMINGS:
            ms = window_months(t, timing)
            es.check_network_before(t, ms)
            plan.setdefault(ms[-1], []).append((ti, timing, t.isoformat(), sorted(targets_by_t.get(ti, []))))
    ends = sorted(plan)
    m117_small = {"tags": tags, "pair_files": m117["pair_files"], "month_v1": month_v1, "month_docs": month_docs}
    meta_small = {"excluded": excl, "el_files": meta["el_files"], "month_excl_v1": month_excl_v1}
    feats = {}
    with es._pool(graph_workers, _init_graph, (t117_cache, m117_small, cache_dir, meta_small, plan, rises)) as pool:
        for k, out in enumerate(pool.imap(_graph_chunk, chunks_of(ends, graph_workers)), 1):
            for key, g, timing, f in out:
                feats[(key, g, timing)] = f
            log("グラフのかたまり %d / %d" % (k, graph_workers))
    files = evaluate_and_write(rows, feats, mondays, tags, v, meta, ctx)
    return write_outputs(out_dir, files)


# ---------------------------------------------------------------------------
# 評価
# ---------------------------------------------------------------------------

def variants():
    """(名前, 種類, 網, 時期, 拡散) の一覧。"""
    out = []
    for g in GRAPHS:
        for timing in TIMINGS:
            for kern in KERNELS:
                out.append(("diff_%s_%s_%s" % (g, timing, kern), "diffusion", g, timing, kern))
            out.append(("wave_%s_%s" % (g, timing), "wave", g, timing, None))
    return out


def split_keys(keys, mondays, sp):
    return ed.split_rows(keys, mondays, sp)


def hub_fit(rows_x, rows_y):
    coef = ed.ols(rows_x, rows_y)
    return coef


def variant_columns(name, kind, g, timing, kern, feats, keys, tr, own, hub_info, sp):
    """1つの作り方の列（{列の名前: {行: 値}}）。拡散なら見込みと残差（ハブの割り引きは学習の行 tr だけで回帰）、波面なら E1〜E3 と印。"""
    if kind == "diffusion":
        exp_ = {k: feats[(k, g, timing)][kern] for k in keys}
        X = [[1.0, math.log1p(feats[(k, g, timing)]["deg"]), feats[(k, g, timing)]["vol"]] for k in tr]
        coef = hub_fit(X, [exp_[k] for k in tr])
        hub_info.append((sp, name, *coef))
        resid = {k: exp_[k] - (coef[0] + coef[1] * math.log1p(feats[(k, g, timing)]["deg"])
                               + coef[2] * feats[(k, g, timing)]["vol"]) - own[k] for k in keys}
        return {name + "_exp": exp_, name + "_res": resid}
    return {"%s_%s" % (name, f): {k: feats[(k, g, timing)][f] for k in keys} for f in ("E1", "E2", "E3", "mono")}


def evaluate_and_write(rows, feats, mondays, tags, v, meta, ctx):
    keys = sorted(rows)
    idx = {k: r for r, k in enumerate(keys)}
    own = {k: es.rise(rows[k][1]["c"], rows[k][1]["B"], v) for k in keys}
    results = []
    hub_info = []
    for sp in SPLITS:
        tr, te = split_keys(keys, mondays, sp)
        tri = [idx[k] for k in tr]
        tei = [idx[k] for k in te]
        base_tb, p0 = {}, {}
        for m in MULTIPLIERS:
            base_tb[m] = ed.make_table(rows, keys, mondays, tags, m, v)
            _f0, p0[m], x0 = ed.fit_eval(base_tb[m], m, ed.naive_cols(m), tri, tei)
            results.append((sp, m, "naive", x0))
        for name, kind, g, timing, kern in variants():
            extra = variant_columns(name, kind, g, timing, kern, feats, keys, tr, own, hub_info, sp)
            for m in MULTIPLIERS:
                tb = dict(base_tb[m])
                for c, vals in extra.items():
                    tb[c] = array.array("d", [vals[k] for k in keys])
                _f, _p, x = ed.fit_eval(tb, m, ed.naive_cols(m) + list(extra), tri, tei, p0[m])
                results.append((sp, m, name, x))
    return build_outputs(results, hub_info, meta, ctx, len(keys))


OUT_NAMES = ("models.tsv", "hub.tsv", "run.json", "summary.md")


def write_outputs(out_dir, files):
    if sorted(files) != sorted(OUT_NAMES):
        raise DiffusionError("出力の名前が決めた一覧と違う")
    os.makedirs(out_dir, exist_ok=True)
    for name in OUT_NAMES:
        if os.path.lexists(os.path.join(out_dir, name)):
            raise DiffusionError("書き出す先に同じ名前のファイル（%s）がある。上書きしない" % name)
    return {name: es.write_new(os.path.join(out_dir, name), files[name]) for name in OUT_NAMES}


f6 = es.f6


def build_outputs(results, hub_info, meta, ctx, n_rows):
    def ci(x):
        v = x.get("d_ll_ci")
        return ("-", "-") if v is None else (f6(v[0]), f6(v[1]))
    models = ei.tsv(("split", "multiplier", "horizon_days", "model", "n_test", "islands_test", "logloss", "auc",
                     "top10_hits", "d_logloss_vs_naive", "d_ll_ci4w_lo", "d_ll_ci4w_hi", "d_top10_vs_naive"),
                    [(sp, m, HORIZON, name, x["n"], x["pos"], f6(x["logloss"]), f6(x["auc"]), x["topk"],
                      f6(x.get("d_logloss")), *ci(x), x.get("d_topk", "-")) for sp, m, name, x in results])
    hub = ei.tsv(("split", "model", "intercept", "log1p_degree", "volume_level"),
                 [(sp, name, *[f6(c) for c in coef]) for sp, name, *coef in hub_info])
    n_models = len(variants())
    run = {"label": LABEL, "code": dict(ei._LOADED_SHA, **own_code_shas()), "python": sys.version.split()[0],
           "phase1_sha256": meta["phase1_sha256"], "refs": ctx["refs"],
           "v": "%d/%d" % (ctx["v"].numerator, ctx["v"].denominator), "rows": n_rows,
           "excluded_themes": len(meta["excluded"]), "detail_sha256": DETAIL_SHA256,
           "options": {"window_months": WINDOW_MONTHS, "shift_months": SHIFT_MONTHS, "graphs": GRAPHS,
                       "timings": TIMINGS, "knn_k": KNN_K, "min_pair_docs": MIN_PAIR_DOCS, "k_max": K_MAX,
                       "heat_taus": HEAT_TAUS, "rwr_alphas": RWR_ALPHAS, "splits": SPLITS, "split_main": SPLIT_MAIN},
           "models_per_multiplier_split": n_models, "models_total": n_models * len(MULTIPLIERS) * len(SPLITS),
           "citation": [ei.CITATION_EN, ei.CITATION_JA]}
    files = {"models.tsv": models, "hub.tsv": hub,
             "run.json": (json.dumps(run, ensure_ascii=False, sort_keys=True, indent=1) + "\n").encode("utf-8")}
    files["summary.md"] = summary_md(run, results)
    for name, data in files.items():
        ei.check_public(name, data)
    return files


def summary_md(run, results):
    L = []
    a = L.append
    md = ei.md_table
    a("# 拡散の残差と波面の勾配の探索（T-123、手法を作る期間）")
    a("")
    a("この文書は `src/stats/explore_diffusion.py` が出力したもので、手で書き足していない。網・拡散・モデルは、ここでは決めない"
      "（決定はオーナー）。全部並べ、選ばない・勧めない。テーマの名前は載せていない。")
    a("")
    a("## 0. 何をどう比べたか")
    a("- 予言日・対象・判定は T-115 と同じ（C7、V = %s、一度跳ねたタグの扱いあり、判定期間 %d 日、倍率 %s）。対象の行 %d。" % (
        run["v"], HORIZON, "・".join(str(m) for m in MULTIPLIERS), run["rows"]))
    a("- 網：T-117 の月ごとの P1 の組の文書の数。lift の上位 %d（組の文書の数 %d 以上）の隣を双方向にまとめた無向グラフ。" % (
        KNN_K, MIN_PAIR_DOCS))
    a("  - list：一覧のタグだけ。")
    a("  - listexcl：一覧のタグに、除外したテーマ %d 個（seq 17 の detail で除外の語に当たったテーマ）を点として加えたもの。"
      "除外したテーマは出どころ・通り道としてだけ使い、予言の対象にしない。線は一覧どうしと一覧 × 除外だけで、除外どうしの線は"
      "入れていない（6章）。" % run["excluded_themes"])
    a("  - now は予言日を含む月の前の12か月、shift はそれを3か月前にずらした12か月（網と信号が同じ記事から作られることの影響を見る）。"
      "どちらも予言日ごとに網の最後の日 < 予言日を確かめた。")
    a("- 出どころ：各点の予言日の直前の上がり log((c+V)/(B+V))（封印済みの関数、t-1 以前だけ）。決まらない点は 0。")
    a("- 拡散：行を正規化した移り変わり P で v_k = P^k s（k = 1〜%d）を作り、熱の拡散（heat_τ、τ = %s。e^{-τ(I−P)} の級数を "
      "%d 項で打ち切ったもの）と再出発つきのランダムウォーク（rwr_α、α = %s）で重みを付けて足した。どちらも自分の k = 0 の項は除いた。"
      % (K_MAX, "・".join("%g" % x for x in HEAT_TAUS), K_MAX, "・".join("%g" % x for x in RWR_ALPHAS)))
    a("- 拡散の残差：見込み − ハブの割り引き − 自分の上がり。ハブの割り引きは、見込みを [1, log1p(次数), 12か月の自分の報道量の log] に、"
      "分け方ごとの学習の行だけで回帰した当てはめ値（係数は hub.tsv）。モデルには見込みと残差の2つの列を足した。")
    a("- 波面：E1・E2・E3 = v_1・v_2・v_3（ランダムウォークの1〜3歩の重み付き平均。最短距離の隣ではない）と、E3 > E2 > E1 > 自分 の印。")
    a("- 評価：素朴な予測（naive.py の特徴量、ロジスティック回帰、リッジ 1）に足した分。主は分け方 B（学習 〜%s、確かめ %s〜%s）。"
      "分け方 A（学習 〜%s、検証 %s〜）は参考。" % (em.INNER_TRAIN_LAST, em.INNER_VAL_FIRST, es.TRAIN_LAST, es.TRAIN_LAST,
                                                 es.TEST_FIRST))
    a("")
    for i, sp in enumerate(SPLITS):
        a("## %d. 結果（分け方 %s%s）" % (i + 1, sp, "、主" if sp == SPLIT_MAIN else "、参考。既に何度も見た検証の期間の再利用"))
        a("")
        for m in MULTIPLIERS:
            rs = [(name, x) for s2, m2, name, x in results if s2 == sp and m2 == m]
            nv = rs[0][1]
            a("### 倍率 %d（確かめの行 %d、島 %d）" % (m, nv["n"], nv["pos"]))
            a("")
            a(md(["モデル", "対数損失", "AUC", "上位10の島", "素朴な予測との差（割合）", "差の範囲（4週束ね）", "上位10の差"],
                 [(name, f6(x["logloss"]), f6(x["auc"]), x["topk"],
                   "-" if name == "naive" else "%s（%+.2f%%）" % (f6(x["d_logloss"]), 100 * x["d_logloss"] / nv["logloss"]),
                   "-" if name == "naive" else "%s〜%s" % (f6(x["d_ll_ci"][0]), f6(x["d_ll_ci"][1])),
                   "-" if name == "naive" else x["d_topk"]) for name, x in rs]))
            a("")
            below = [name for name, x in rs if name != "naive" and x["d_ll_ci"][1] < 0]
            above = [name for name, x in rs if name != "naive" and x["d_ll_ci"][0] > 0]
            a("- 差の範囲が0より下に収まったモデル：%s。0より上に収まったモデル：%s。" % (
                "、".join(below) if below else "無い", "、".join(above) if above else "無い"))
            a("")
        a("- この一覧の読み方：比べたモデルは、分け方と倍率ごとに %d（素朴な予測を除く）、計 %d。出した差の範囲も同じ数で、多重比較の補正をして"
          "いない。基準はどれも同じ素朴な予測（ロジスティック、リッジ 1）。4週の束どうしは独立でない（判定期間 %d 日が隣の束に重なる）。"
          "範囲が0を含まないことは、効くことの確かめにはならない。" % (run["models_per_multiplier_split"], run["models_total"], HORIZON))
        a("")
    a("## 3. 予言の時点のデータだけを使ったことの確かめ")
    a("- 日の比率と上がり：ReadGuard で、入力は t-399〜t-1（除外したテーマの上がりは t-371〜t-1）の外を読むと止まる。")
    a("- 網：予言日ごとに、使う窓の月が予言日の月から決まるものと同じことと、窓の最後の日 < 予言日を確かめた（now と shift）。")
    a("- ハブの割り引きの回帰は、分け方ごとの学習の行だけで当てはめた。")
    a("")
    a("## 4. 限界")
    a("- 分け方 B の確かめ（2018年）は、T-118 で強さを選ぶのに使い、T-122 でも確かめに使った期間。分け方 A の検証（2019〜2020年）は、"
      "T-117〜T-122 で既に何度も見た期間の再利用。どちらも未見のデータでの確かめにはならない。")
    a("- 一覧と V の先読み：タグの一覧と V は、手法を作る期間の区画全体のデータで決まった（seq 17）。")
    a("- 除外の規則の漏れ：民族・人物の姓・宗教・犯罪・紛争・政治に当たる名前のテーマが一覧に残っている（オーナーの決定 2026-10-16、(a)）。"
      "listexcl では、除外の語に当たったテーマも網の点になる。要約にはテーマの名前を載せていない。")
    a("- WB のテーマの段のような上昇（T-116 の要約 6章）は、学習の期間の網と上がりに入る。")
    a("")
    a("## 5. 作り方の限界")
    a("- listexcl では、除外どうしの線を入れていない。1日に約24万組あり、12か月分を標準の Python で持てないため。除外したテーマを"
      "経由する流れは、一覧のタグ → 除外 → 一覧のタグの形だけになる。")
    a("- E1〜E3 は、ランダムウォークの歩数の重み付き平均で、行き戻りを含む。最短距離での隣ではない。")
    a("- 拡散の級数は %d 項で打ち切った。網は月の単位で、予言日の前の数週は入らない。網の作り方（隣の数、組の文書の数の下限）・τ・α・"
      "打ち切りの項数も選びうるもので、比べた数に入っていない。" % K_MAX)
    a("")
    a("## 6. 再計算")
    a("```")
    a(".venv/bin/python -B src/stats/explore_diffusion.py phase1 --store <日の集計> --detail <order5-detail.json> --cache-dir <新しいフォルダ>")
    a(".venv/bin/python -B src/stats/explore_diffusion.py phase2 --cache-dir <同じフォルダ> --t117-cache <explore-t117-cache/run2> "
      "--detail <order5-detail.json> --out-dir <書き出す先>")
    a("```")
    for k in sorted(run["code"]):
        a("- %s：sha256 %s" % (k, run["code"][k]))
    a("- キャッシュ phase1.json：sha256 %s。detail：sha256 %s（seq 17 の outside と照らした）" % (run["phase1_sha256"],
                                                                                         run["detail_sha256"]))
    a("")
    a("## 引用")
    a(ei.CITATION_EN)
    a("")
    a(ei.CITATION_JA)
    out = "\n".join(L) + "\n"
    if "**" in out:
        raise DiffusionError("要約に太字の印がある")
    return out.encode("utf-8")


def main(argv=None):
    p = argparse.ArgumentParser(description="T-123 拡散の残差と波面の勾配")
    sub = p.add_subparsers(dest="cmd", required=True)
    p1 = sub.add_parser("phase1")
    p1.add_argument("--store", required=True)
    p1.add_argument("--detail", required=True)
    p1.add_argument("--cache-dir", required=True)
    p1.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 1))
    p2 = sub.add_parser("phase2")
    p2.add_argument("--cache-dir", required=True)
    p2.add_argument("--t117-cache", required=True)
    p2.add_argument("--detail", required=True)
    p2.add_argument("--out-dir", required=True)
    p2.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 1))
    p2.add_argument("--graph-workers", type=int, default=5)
    a = p.parse_args(argv)
    t0 = time.time()

    def log(msg):
        sys.stderr.write("[%8.1f s] %s\n" % (time.time() - t0, msg))
        sys.stderr.flush()
    try:
        if a.cmd == "phase1":
            print("%s  phase1.json" % phase1(ei.PROJECT, a.store, a.detail, a.cache_dir, a.workers, log))
        else:
            shas = phase2(ei.PROJECT, a.cache_dir, a.t117_cache, a.detail, a.out_dir, a.workers, a.graph_workers, log)
            for name in OUT_NAMES:
                print("%s  %s" % (shas[name], name))
    except (DiffusionError, ed.DenomError, eg.GraphError, em.ModelError, es.SignalError, ei.ExploreError) as e:
        sys.stderr.write("止まった：%s\n" % e)
        return 1
    log("終わり")
    return 0


if __name__ == "__main__":
    sys.exit(main())
