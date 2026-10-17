#!/usr/bin/env python3
"""T-124：除外したテーマの網の試し直し（T-123 の続き）。

T-123 の網 listexcl は、除外の語に当たったテーマ 16,902 個すべてを点にしたため、一覧のタグの隣の多くが量の少ないテーマに
置き換わった（T-123 の監査の中-1）。ここでは点を次の条件で絞った網 listexcl2 を作り、T-123 と同じ拡散・波面・ハブの割り引き・
時期・評価で、list・listexcl（T-123 の結果を照らして読み込む）と同じ表に並べる。全部並べ、選ばない・勧めない。

listexcl2 の点（流す前に書いた条件）
  seq 17 の detail（sha256 を seq 17 の outside と照らす）で、除外の語に当たり（exclusion_matches が空でない）、
  かつ present_throughout が真、かつ mean_ratio_at_least_a が真のテーマ（一覧の入れる規則を満たし、除外の規則だけで外れたもの）。
  線は、一覧どうし・一覧 × 除外・除外どうしの3種類。除外どうしの組は、日の集計から読み直してキャッシュに置く（phase1）。
  一覧 × 除外の組は、T-123 のキャッシュの月ごとの配列から、この点の列だけを抜き出す（phase1）。
  除外したテーマは出どころ・通り道としてだけ使い、予言の対象・評価の行に入れない。

網の中身の記述：網と窓（網の最後の月）ごとに、点の数、線の数（一覧どうし・一覧 × 除外・除外どうし）、一覧のタグの lift の上位10の
うち除外したテーマが占める割合と、その除外したテーマの内訳（全期間に存在するか、平均が A 以上か）。list・listexcl・listexcl2 の3つ。

予言の時点のデータだけ：日の比率と上がりは ReadGuard（t-1 以前）。網の月は予言日を含む月より前で、予言日ごとに網の最後の日 < t を
確かめる。区画の外の日の集計は開かない。

流し方（プロジェクトのルートで。TMPDIR は scratchpad の中に）
  .venv/bin/python -B src/stats/explore_diffusion2.py phase1 --store <日の集計> --detail <order5-detail.json> \
      --t123-cache <explore-t123-cache/run1> --cache-dir <新しいフォルダ>
  .venv/bin/python -B src/stats/explore_diffusion2.py phase2 --cache-dir <同じフォルダ> --t123-cache <explore-t123-cache/run1> \
      --t117-cache <explore-t117-cache/run2> --detail <order5-detail.json> --t123-models <explore-t123/models.tsv> --out-dir <書き出す先>

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
import statistics
import sys
import time
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import explore_diffusion as ex  # noqa: E402

ed = ex.ed
em = ex.em
es = ex.es
ei = ex.ei
naive = ex.naive
counting = ei.counting

LABEL = "explore-diffusion2-t124-v2"   # v2：T-124 の申し送り（4章の shift の文を数から作る形に。表は同じ）
PHASE1_LABEL = "explore-diffusion2-phase1-v1"
MULTIPLIERS = ex.MULTIPLIERS
HORIZON = ex.HORIZON
ITEM = ex.ITEM

# ---------------------------------------------------------------------------
# 試す形（本番の前に書いた）
# ---------------------------------------------------------------------------
NETWORK_NEW = "listexcl2"
NETWORKS_ALL = ("list", "listexcl", "listexcl2")
T123_PHASE1_SHA256 = "505da0fddde33dc761d250afa357e60f46a4dbc29b17e0b5e475c940158b92ea"
T123_MODELS_SHA256 = "1b7d93d9a80b4c60bdb9fe2ec624a11782fb7e305253270f0dae78887a18b279"


def excl2_rule(theme):
    """listexcl2 の点の条件：除外の語に当たり、全期間に存在し、平均が A 以上。"""
    return bool(theme["exclusion_matches"]) and theme["present_throughout"] is True and \
        theme["mean_ratio_at_least_a"] is True


class Diffusion2Error(Exception):
    pass


def count_not_in_table(detail_path, names):
    """names のうち、detail で区分表に無い（in_category_table が偽の）テーマの数。detail の sha256 を照らしてから読む。"""
    data = ei.read_nofollow(detail_path)
    if hashlib.sha256(data).hexdigest() != ex.DETAIL_SHA256:
        raise Diffusion2Error("detail の sha256 が seq 17 の outside と違う")
    want = set(names)
    return sum(1 for t in json.loads(data.decode("utf-8"))["official_result"]["themes"]
               if t["name"] in want and t.get("in_category_table") is False)


def load_detail(detail_path, ctx):
    """detail を照らして読み、(除外したテーマの名前の順の一覧, listexcl2 の点の名前の順の一覧, 除外したテーマの内訳の印)。"""
    data = ei.read_nofollow(detail_path)
    if hashlib.sha256(data).hexdigest() != ex.DETAIL_SHA256:
        raise Diffusion2Error("detail の sha256 が seq 17 の outside と違う")
    res = json.loads(data.decode("utf-8"))["official_result"]
    if res["tag_list"] != ctx["tags"]:
        raise Diffusion2Error("detail の一覧が seq 17 の一覧と違う")
    themes = [t for t in res["themes"] if t["exclusion_matches"]]
    excl = sorted(t["name"] for t in themes)
    excl2 = sorted(t["name"] for t in themes if excl2_rule(t))
    flags = {t["name"]: (t["present_throughout"] is True, t["mean_ratio_at_least_a"] is True) for t in themes}
    if set(excl) & set(ctx["tags"]):
        raise Diffusion2Error("除外したテーマが一覧に入っている")
    return excl, excl2, flags


# ---------------------------------------------------------------------------
# phase1：listexcl2 の除外どうしの組（日の集計から）と、一覧 × 除外の組（T-123 のキャッシュから抜き出す）
# ---------------------------------------------------------------------------

_W = {}


def _init_p1(store, tags, excl2, cols, t123_cache, el_files, ne, cache_dir):
    _W.update(store=store, tags=tuple(tags), excl2=tuple(excl2), cols=cols, t123=t123_cache,
              small={"el_files": el_files}, ne=ne, cache_dir=cache_dir, e2i={n: k for k, n in enumerate(excl2)})


def parse_ee_pairs(data, e2i, ee, n2):
    """日の集計の P1 の組のうち、listexcl2 の除外したテーマどうしの組を ee（n2 × n2、両向き）に足す。翻訳の組は数えない。"""
    vocab = {}
    for raw in gzip.GzipFile(fileobj=io.BytesIO(data)):
        tag, _s, rest = raw.partition(b"\t")
        if tag == b"V":
            i, name = rest.rstrip(b"\n").split(b"\t")
            k = e2i.get(name.decode("ascii"))
            if k is not None:
                vocab[int(i)] = k
        elif tag == b"P1":
            g, a, b, x = rest.split(b"\t")
            if g.endswith(b"T"):
                continue
            ka = vocab.get(int(a))
            if ka is None:
                continue
            kb = vocab.get(int(b))
            if kb is None:
                continue
            ee[ka * n2 + kb] += int(x)
            ee[kb * n2 + ka] += int(x)


def extract_columns(el, nl, ne, cols):
    """一覧 × 除外の配列（nl × ne）から、cols の列だけの配列（nl × len(cols)）を作る。"""
    out = array.array("I")
    for i in range(nl):
        row = el[i * ne:(i + 1) * ne]
        out.extend(row[j] for j in cols)
    return out


def _month_task(args):
    mk, items = args
    nl, n2 = len(_W["tags"]), len(_W["excl2"])
    el = ex.load_el(_W["t123"], _W["small"], mk)
    el2 = extract_columns(el, nl, _W["ne"], _W["cols"])
    del el
    ee = array.array("I", bytes(ITEM * n2 * n2))
    for day, file_name, sha, missing in items:
        if datetime.date.fromisoformat(day) >= ei.NEXT_BLOCK_START:
            raise Diffusion2Error("区画の外の日を読もうとした")
        if missing:
            continue
        data = ei.read_nofollow(os.path.join(_W["store"], file_name))
        if hashlib.sha256(data).hexdigest() != sha:
            raise Diffusion2Error("%s：日の集計の sha256 が違う" % day)
        parse_ee_pairs(data, _W["e2i"], ee, n2)
    es.check_free(_W["cache_dir"])
    s1 = es.write_new(os.path.join(_W["cache_dir"], "el2-%06d.bin.z" % mk), zlib.compress(el2.tobytes(), 6))
    s2 = es.write_new(os.path.join(_W["cache_dir"], "ee-%06d.bin.z" % mk), zlib.compress(ee.tobytes(), 6))
    return mk, s1, s2


def phase1(root, store, detail, t123_cache, cache_dir, workers, log):
    ctx = ei.load_context(root)
    excl, excl2, _flags = load_detail(detail, ctx)
    meta123 = ex.load_cache(t123_cache, ctx, excl)
    if meta123["phase1_sha256"] != T123_PHASE1_SHA256:
        raise Diffusion2Error("T-123 のキャッシュの版が違う")
    if os.path.lexists(cache_dir):
        raise Diffusion2Error("キャッシュのフォルダが既にある。上書きしない")
    es.check_free(os.path.dirname(os.path.abspath(cache_dir)))
    os.mkdir(cache_dir)
    cols = [excl.index(n) for n in excl2]
    days, rows, missing = ctx["days"], ctx["rows"], ctx["missing"]
    months = sorted({es.month_key(d) for d in days})
    tasks = [(mk, [(d.isoformat(), rows[d.isoformat()]["file_name"], rows[d.isoformat()]["sha256"], d in missing)
                   for d in days if es.month_key(d) == mk]) for mk in months]
    files = {}
    with es._pool(workers, _init_p1, (store, ctx["tags"], excl2, cols, t123_cache, meta123["el_files"], len(excl),
                                      cache_dir)) as pool:
        for k, (mk, s1, s2) in enumerate(pool.imap(_month_task, tasks), 1):
            files[str(mk)] = {"el2": {"file": "el2-%06d.bin.z" % mk, "sha256": s1},
                              "ee": {"file": "ee-%06d.bin.z" % mk, "sha256": s2}}
            log("月 %d / %d（%d）" % (k, len(tasks), mk))
    meta = {"label": PHASE1_LABEL, "tags": ctx["tags"], "excl2": excl2, "cols": cols, "refs": ctx["refs"],
            "days": [d.isoformat() for d in days], "missing": sorted(d.isoformat() for d in missing),
            "files": files, "itemsize": ITEM, "byteorder": sys.byteorder, "t123_phase1_sha256": T123_PHASE1_SHA256,
            "detail_sha256": ex.DETAIL_SHA256, "code": dict(ei._LOADED_SHA, **own_code_shas())}
    data = (json.dumps(meta, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")
    return es.write_new(os.path.join(cache_dir, "phase1.json"), data)


def own_code_shas():
    out = dict(ex.own_code_shas())
    with open(os.path.abspath(__file__), "rb") as f:
        out["src/stats/explore_diffusion2.py"] = hashlib.sha256(f.read()).hexdigest()
    return out


def load_cache(cache_dir, ctx, excl2):
    raw = ei.read_nofollow(os.path.join(cache_dir, "phase1.json"))
    meta = json.loads(raw.decode("utf-8"))
    if meta.get("label") != PHASE1_LABEL or meta["tags"] != ctx["tags"] or meta["excl2"] != excl2 or \
            meta["refs"] != ctx["refs"] or meta["days"] != [d.isoformat() for d in ctx["days"]] or \
            meta["itemsize"] != ITEM or meta["byteorder"] != sys.byteorder or \
            meta["t123_phase1_sha256"] != T123_PHASE1_SHA256:
        raise Diffusion2Error("キャッシュが封印の記録・detail・T-123 のキャッシュ・この計算機と合わない")
    meta["phase1_sha256"] = hashlib.sha256(raw).hexdigest()
    return meta


def load_part(cache_dir, meta, mk, kind):
    f = meta["files"][str(mk)][kind]
    data = ei.read_nofollow(os.path.join(cache_dir, f["file"]))
    if hashlib.sha256(data).hexdigest() != f["sha256"]:
        raise Diffusion2Error("キャッシュの %s の sha256 が違う" % f["file"])
    a = array.array("I")
    a.frombytes(zlib.decompress(data))
    return a


# ---------------------------------------------------------------------------
# グラフ（除外どうしの線を含む形）と網の中身の記述
# ---------------------------------------------------------------------------

def build_graph_x(ll, el, ee, nl, ne, marg_l, marg_e, total):
    """一覧（0..nl-1）と除外（nl..nl+ne-1）の無向の隣接と、一覧の点の lift の上位10（向きのある一覧）。
    el は nl × ne、ee は ne × ne（None なら除外どうしの線を入れない）。el が None なら一覧だけ。"""
    with_excl = el is not None
    n = nl + (ne if with_excl else 0)
    adj = [dict() for _ in range(n)]
    marg = (marg_l + marg_e) if with_excl else marg_l
    knn_list = []
    for i in range(nl):
        row = ll[i * nl:(i + 1) * nl]
        cands = [(j, x) for j, x in enumerate(row) if x and j != i]
        if with_excl:
            erow = el[i * ne:(i + 1) * ne]
            cands += [(nl + j, x) for j, x in enumerate(erow) if x]
        nb = ex.knn_lift(cands, marg_l[i], marg, total)
        knn_list.append([j for j, _x in nb])
        for j, x in nb:
            adj[i][j] = x
            adj[j][i] = x
    if with_excl:
        for e in range(ne):
            col = el[e::ne]
            cands = [(i, x) for i, x in enumerate(col) if x]
            if ee is not None:
                erow = ee[e * ne:(e + 1) * ne]
                cands += [(nl + j, x) for j, x in enumerate(erow) if x and j != e]
            for j, x in ex.knn_lift(cands, marg_e[e], marg, total):
                adj[nl + e][j] = x
                adj[j][nl + e] = x
    return adj, knn_list


def graph_stats(adj, knn_list, nl, excl_flags):
    """点の数、線の数（種類別）、線の無い点の数、一覧の点の lift の上位10に占める除外したテーマの割合と、その内訳。
    excl_flags：除外したテーマの番号ごとの (全期間に存在するか, 平均が A 以上か)。"""
    ll = le = ee = 0
    for i, a in enumerate(adj):
        for j in a:
            if j <= i:
                continue
            if i < nl and j < nl:
                ll += 1
            elif i < nl or j < nl:
                le += 1
            else:
                ee += 1
    entries = [j for nb in knn_list for j in nb]
    ex_entries = [j - nl for j in entries if j >= nl]
    pres = sum(1 for e in ex_entries if excl_flags[e][0])
    ata = sum(1 for e in ex_entries if excl_flags[e][1])
    both = sum(1 for e in ex_entries if excl_flags[e][0] and excl_flags[e][1])
    return {"nodes": len(adj), "edges_ll": ll, "edges_le": le, "edges_ee": ee,
            "isolated": sum(1 for a in adj if not a), "knn_entries": len(entries), "knn_excl": len(ex_entries),
            "knn_excl_present": pres, "knn_excl_at_least_a": ata, "knn_excl_both": both}


# ---------------------------------------------------------------------------
# 子プロセス：listexcl2 のグラフと値（窓ごと）、list・listexcl2 の記述
# ---------------------------------------------------------------------------

def _init_graph2(t117_cache, m117_small, cache_dir, meta_small, plan, rises, flags2):
    _W.update(t117=t117_cache, m117=m117_small, cache_dir=cache_dir, meta=meta_small, plan=plan, rises=rises,
              flags2=flags2)


def _rolling(cur, want, arrays, loaders):
    """月の和を、外れた月を引き、加わった月を足して作り直す。arrays：{名前: 配列 or None}、loaders：{名前: 月 → 配列}。"""
    for m in [m for m in cur if m not in want]:
        for k, f in loaders.items():
            arrays[k] = array.array("I", map(operator.sub, arrays[k], f(m)))
    for m in [m for m in want if m not in cur]:
        for k, f in loaders.items():
            a = f(m)
            arrays[k] = a if arrays[k] is None else array.array("I", map(operator.add, arrays[k], a))
    return list(want)


def window_of_end(end):
    first = es.month_key(ei.BLOCK_START)
    return [m for m in (es.add_months(end, -k) for k in range(ex.WINDOW_MONTHS - 1, -1, -1)) if m >= first]


def _graph2_chunk(ends):
    m117, meta, plan = _W["m117"], _W["meta"], _W["plan"]
    nl, n2 = len(m117["tags"]), len(meta["excl2"])
    arrays = {"ll": None, "el2": None, "ee": None}
    loaders = {"ll": lambda m: es.load_pairs(_W["t117"], m117, m),
               "el2": lambda m: load_part(_W["cache_dir"], meta, m, "el2"),
               "ee": lambda m: load_part(_W["cache_dir"], meta, m, "ee")}
    cur = []
    feats, stats = [], []
    for end in ends:
        want = window_of_end(end)
        cur = _rolling(cur, want, arrays, loaders)
        marg_l = [sum(m117["month_v1"][m][i] for m in want) for i in range(nl)]
        marg_e = [sum(meta["month_excl2_v1"][m][e] for m in want) for e in range(n2)]
        total = sum(m117["month_docs"][m] for m in want)
        adj0, knn0 = build_graph_x(arrays["ll"], None, None, nl, 0, marg_l, [], total)
        stats.append((end, "list", graph_stats(adj0, knn0, nl, [])))
        adj, knn = build_graph_x(arrays["ll"], arrays["el2"], arrays["ee"], nl, n2, marg_l, marg_e, total)
        stats.append((end, NETWORK_NEW, graph_stats(adj, knn, nl, _W["flags2"])))
        P = ex.transition(adj)
        deg = [len(a) for a in adj[:nl]]
        for (ti, timing, t_iso, targets) in plan.get(end, []):
            t = datetime.date.fromisoformat(t_iso)
            if ex.window_months(t, timing) != want:
                raise Diffusion2Error("窓の月が予言日の月と合わない")
            es.check_network_before(t, want)
            s = list(_W["rises"][ti])
            vks = ex.powers(P, s, ex.K_MAX)
            for i in targets:
                f = ex.diffusion_features(vks, s[i], i)
                f["deg"] = deg[i]
                f["vol"] = math.log(marg_l[i] + 1.0)
                feats.append(((ti, i), NETWORK_NEW, timing, f))
    return feats, stats


def _init_desc(t117_cache, m117_small, t123_cache, meta123_small, flags):
    _W.update(t117=t117_cache, m117=m117_small, t123=t123_cache, meta123=meta123_small, flags=flags)


def _desc_chunk(ends):
    """T-123 の listexcl の網の中身の記述（除外どうしの線は無い形。T-123 と同じ作り方）。"""
    m117, meta = _W["m117"], _W["meta123"]
    nl, ne = len(m117["tags"]), len(meta["excluded"])
    arrays = {"ll": None, "el": None}
    loaders = {"ll": lambda m: es.load_pairs(_W["t117"], m117, m),
               "el": lambda m: ex.load_el(_W["t123"], meta, m)}
    cur = []
    out = []
    for end in ends:
        want = window_of_end(end)
        cur = _rolling(cur, want, arrays, loaders)
        marg_l = [sum(m117["month_v1"][m][i] for m in want) for i in range(nl)]
        marg_e = [sum(meta["month_excl_v1"][m][e] for m in want) for e in range(ne)]
        total = sum(m117["month_docs"][m] for m in want)
        adj, knn = build_graph_x(arrays["ll"], arrays["el"], None, nl, ne, marg_l, marg_e, total)
        out.append((end, "listexcl", graph_stats(adj, knn, nl, _W["flags"])))
    return out


# ---------------------------------------------------------------------------
# T-123 の結果を照らして読む
# ---------------------------------------------------------------------------

def read_t123_models(path):
    data = ei.read_nofollow(path)
    if hashlib.sha256(data).hexdigest() != T123_MODELS_SHA256:
        raise Diffusion2Error("T-123 の models.tsv の sha256 が違う")
    lines = data.decode("utf-8").rstrip("\n").split("\n")
    head = lines[0].split("\t")
    out = []
    for line in lines[1:]:
        r = dict(zip(head, line.split("\t")))
        out.append(r)
    return out


def row_from_metrics(sp, m, name, x, source):
    return {"split": sp, "multiplier": str(m), "horizon_days": str(HORIZON), "model": name, "n_test": str(x["n"]),
            "islands_test": str(x["pos"]), "logloss": es.f6(x["logloss"]), "auc": es.f6(x["auc"]),
            "top10_hits": str(x["topk"]), "d_logloss_vs_naive": es.f6(x.get("d_logloss")),
            "d_ll_ci4w_lo": es.f6(x["d_ll_ci"][0]) if "d_ll_ci" in x else "-",
            "d_ll_ci4w_hi": es.f6(x["d_ll_ci"][1]) if "d_ll_ci" in x else "-",
            "d_top10_vs_naive": str(x.get("d_topk", "-")), "source": source}


def check_naive_same(t123_rows, own_rows):
    """T-124 で計算した素朴な予測の行が、T-123 の行と同じ値であること。"""
    a = {(r["split"], r["multiplier"]): r for r in t123_rows if r["model"] == "naive"}
    b = {(r["split"], r["multiplier"]): r for r in own_rows if r["model"] == "naive"}
    keys = ("n_test", "islands_test", "logloss", "auc", "top10_hits")
    if sorted(a) != sorted(b) or any(a[k][c] != b[k][c] for k in a for c in keys):
        raise Diffusion2Error("素朴な予測の行が T-123 と違う")


# ---------------------------------------------------------------------------
# phase2
# ---------------------------------------------------------------------------

def phase2(root, cache_dir, t123_cache, t117_cache, detail, t123_models, out_dir, workers, graph_workers, log):
    ctx = ei.load_context(root)
    excl, excl2, flags = load_detail(detail, ctx)
    meta = load_cache(cache_dir, ctx, excl2)
    meta["excl2_not_in_table"] = count_not_in_table(detail, excl2)
    meta123 = ex.load_cache(t123_cache, ctx, excl)
    if meta123["phase1_sha256"] != T123_PHASE1_SHA256:
        raise Diffusion2Error("T-123 のキャッシュの版が違う")
    t123_rows = read_t123_models(t123_models)
    m117 = es.load_cache(t117_cache, ctx)
    tags, v = ctx["tags"], ctx["v"]
    nl, ne, n2 = len(tags), len(excl), len(excl2)
    cols = meta["cols"]
    if cols != [excl.index(n) for n in excl2]:
        raise Diffusion2Error("キャッシュの列の番号が違う")
    days = ctx["days"]
    mondays = ei.prediction_mondays()
    missing = set(meta["missing"])
    series = es.daily_series(m117)
    del m117["weekc"]
    results = ed.evaluate_variant(series, days, mondays, v, workers, log, "一覧")
    rows = ed.variant_rows(results, mondays, tags, v)
    rises = [[None] * (nl + n2) for _ in mondays]
    for i, res in enumerate(results):
        for ti, (st, b, c, _m1, _m2, _js, _lv) in enumerate(res):
            if b is not None and c is not None:
                rises[ti][i] = es.rise(c, b, v)
    del results, series
    totals = [ctx["denom"][d] for d in meta["days"]]
    mflags = [d in missing for d in meta["days"]]
    pos2 = {e: k for k, e in enumerate(cols)}
    ranges = [cols[a:a + 32] for a in range(0, n2, 32)]
    with es._pool(workers, ex._init_rises, (days, mondays, v, meta123["excl_c7"], totals, mflags, ne)) as pool:
        for out in pool.imap(ex._rises_task, ranges):
            for e, rr in out:
                for ti, x in enumerate(rr):
                    rises[ti][nl + pos2[e]] = x
    rises = [array.array("d", [0.0 if x is None else x for x in r]) for r in rises]
    log("上がりを作った（一覧の対象の行 %d）" % len(rows))
    month_v1, month_docs, month_excl_v1, month_excl2_v1 = {}, {}, {}, {}
    exv1 = meta123["excl_v1"]
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
    for mk, me in month_excl_v1.items():
        month_excl2_v1[mk] = [me[e] for e in cols]
    targets_by_t = {}
    for (ti, i) in rows:
        targets_by_t.setdefault(ti, []).append(i)
    plan = {}
    for ti, t in enumerate(mondays):
        for timing in ex.TIMINGS:
            ms = ex.window_months(t, timing)
            es.check_network_before(t, ms)
            plan.setdefault(ms[-1], []).append((ti, timing, t.isoformat(), sorted(targets_by_t.get(ti, []))))
    ends = sorted(plan)
    m117_small = {"tags": tags, "pair_files": m117["pair_files"], "month_v1": month_v1, "month_docs": month_docs}
    meta_small = {"excl2": excl2, "files": meta["files"], "month_excl2_v1": month_excl2_v1}
    flags2 = [flags[n] for n in excl2]
    feats, stats = {}, []
    with es._pool(graph_workers, _init_graph2, (t117_cache, m117_small, cache_dir, meta_small, plan, rises,
                                                flags2)) as pool:
        for k, (fs, st) in enumerate(pool.imap(_graph2_chunk, ex.chunks_of(ends, graph_workers)), 1):
            for key, g, timing, f in fs:
                feats[(key, g, timing)] = f
            stats.extend(st)
            log("listexcl2 のかたまり %d / %d" % (k, graph_workers))
    meta123_small = {"excluded": excl, "el_files": meta123["el_files"], "month_excl_v1": month_excl_v1}
    flags_all = [flags[n] for n in excl]
    with es._pool(graph_workers, _init_desc, (t117_cache, m117_small, t123_cache, meta123_small, flags_all)) as pool:
        for k, st in enumerate(pool.imap(_desc_chunk, ex.chunks_of(ends, graph_workers)), 1):
            stats.extend(st)
            log("listexcl の記述 %d / %d" % (k, graph_workers))
    files = evaluate_and_build(rows, feats, mondays, tags, v, t123_rows, stats, ends, plan, meta, ctx, excl, excl2,
                               flags)
    return write_outputs(out_dir, files)


def evaluate_and_build(rows, feats, mondays, tags, v, t123_rows, stats, ends, plan, meta, ctx, excl, excl2, flags):
    keys = sorted(rows)
    idx = {k: r for r, k in enumerate(keys)}
    own = {k: es.rise(rows[k][1]["c"], rows[k][1]["B"], v) for k in keys}
    own_rows, hub_info = [], []
    for sp in ex.SPLITS:
        tr, te = ex.split_keys(keys, mondays, sp)
        tri = [idx[k] for k in tr]
        tei = [idx[k] for k in te]
        base_tb, p0 = {}, {}
        for m in MULTIPLIERS:
            base_tb[m] = ed.make_table(rows, keys, mondays, tags, m, v)
            _f0, p0[m], x0 = ed.fit_eval(base_tb[m], m, ed.naive_cols(m), tri, tei)
            own_rows.append(row_from_metrics(sp, m, "naive", x0, "T-124"))
        for name, kind, g, timing, kern in new_variants():
            extra = ex.variant_columns(name, kind, g, timing, kern, feats, keys, tr, own, hub_info, sp)
            for m in MULTIPLIERS:
                tb = dict(base_tb[m])
                for c, vals in extra.items():
                    tb[c] = array.array("d", [vals[k] for k in keys])
                _f, _p, x = ed.fit_eval(tb, m, ed.naive_cols(m) + list(extra), tri, tei, p0[m])
                own_rows.append(row_from_metrics(sp, m, name, x, "T-124"))
    check_naive_same(t123_rows, own_rows)
    all_rows = [dict(r, source="T-123") for r in t123_rows] + [r for r in own_rows if r["model"] != "naive"]
    return build_outputs(all_rows, hub_info, stats, ends, plan, meta, ctx, excl, excl2, flags, len(keys))


def new_variants():
    out = []
    for timing in ex.TIMINGS:
        for kern in ex.KERNELS:
            out.append(("diff_%s_%s_%s" % (NETWORK_NEW, timing, kern), "diffusion", NETWORK_NEW, timing, kern))
        out.append(("wave_%s_%s" % (NETWORK_NEW, timing), "wave", NETWORK_NEW, timing, None))
    return out


def network_of(model):
    for g in ("listexcl2", "listexcl", "list"):
        if model.startswith("diff_%s_" % g) or model == "wave_%s_now" % g or model == "wave_%s_shift" % g:
            return g
    return None


OUT_NAMES = ("models.tsv", "hub.tsv", "network.tsv", "run.json", "summary.md")


def write_outputs(out_dir, files):
    if sorted(files) != sorted(OUT_NAMES):
        raise Diffusion2Error("出力の名前が決めた一覧と違う")
    os.makedirs(out_dir, exist_ok=True)
    for name in OUT_NAMES:
        if os.path.lexists(os.path.join(out_dir, name)):
            raise Diffusion2Error("書き出す先に同じ名前のファイル（%s）がある。上書きしない" % name)
    return {name: es.write_new(os.path.join(out_dir, name), files[name]) for name in OUT_NAMES}


MODEL_COLS = ("split", "multiplier", "horizon_days", "model", "n_test", "islands_test", "logloss", "auc",
              "top10_hits", "d_logloss_vs_naive", "d_ll_ci4w_lo", "d_ll_ci4w_hi", "d_top10_vs_naive", "source")
STAT_COLS = ("nodes", "edges_ll", "edges_le", "edges_ee", "isolated", "knn_entries", "knn_excl", "knn_excl_present",
             "knn_excl_at_least_a", "knn_excl_both")


def order_key(r):
    g = network_of(r["model"])
    return (r["split"] != "B", int(r["multiplier"]), r["model"] != "naive",
            NETWORKS_ALL.index(g) if g else -1, r["model"])


def build_outputs(rows, hub_info, stats, ends, plan, meta, ctx, excl, excl2, flags, n_rows):
    rows = sorted(rows, key=order_key)
    models = ei.tsv(MODEL_COLS, [tuple(r[c] for c in MODEL_COLS) for r in rows])
    hub = ei.tsv(("split", "model", "intercept", "log1p_degree", "volume_level"),
                 [(sp, name, *[es.f6(c) for c in coef]) for sp, name, *coef in hub_info])
    now_ends = sorted({e for e, entries in plan.items() if any(x[1] == "now" for x in entries)})
    stats = sorted(stats, key=lambda x: (NETWORKS_ALL.index(x[1]), x[0]))
    network = ei.tsv(("network", "window_last_month", "used_by_now") + STAT_COLS,
                     [(g, e, e in now_ends, *[s[c] for c in STAT_COLS]) for e, g, s in stats])
    comp = {"excluded_all": len(excl), "present": sum(1 for n in excl if flags[n][0]),
            "at_least_a": sum(1 for n in excl if flags[n][1]),
            "both": sum(1 for n in excl if flags[n][0] and flags[n][1]), "listexcl2_nodes": len(excl2),
            "listexcl2_not_in_table": meta.get("excl2_not_in_table")}
    n_models = len(new_variants())
    run = {"label": LABEL, "code": dict(ei._LOADED_SHA, **own_code_shas()), "python": sys.version.split()[0],
           "phase1_sha256": meta["phase1_sha256"], "t123_phase1_sha256": T123_PHASE1_SHA256,
           "t123_models_sha256": T123_MODELS_SHA256, "detail_sha256": ex.DETAIL_SHA256, "refs": ctx["refs"],
           "v": "%d/%d" % (ctx["v"].numerator, ctx["v"].denominator), "rows": n_rows, "composition": comp,
           "excl2_rule": "exclusion_matches non-empty and present_throughout and mean_ratio_at_least_a",
           "new_models_per_split_multiplier": n_models,
           "models_per_split_multiplier_all_networks": n_models * len(NETWORKS_ALL),
           "citation": [ei.CITATION_EN, ei.CITATION_JA]}
    files = {"models.tsv": models, "hub.tsv": hub, "network.tsv": network,
             "run.json": (json.dumps(run, ensure_ascii=False, sort_keys=True, indent=1) + "\n").encode("utf-8")}
    files["summary.md"] = summary_md(run, rows, stats, now_ends)
    for name, data in files.items():
        ei.check_public(name, data)
    return files


def fnum(s):
    return None if s in ("-", "", None) else float(s)


def shift_vs_now(rows, sp, m, g):
    """同じ網・拡散で、shift の差が now の差以下だった数と、比べた数。"""
    d = {r["model"]: fnum(r["d_logloss_vs_naive"]) for r in rows if r["split"] == sp and r["multiplier"] == str(m)}
    n = k = 0
    for kern in list(ex.KERNELS) + [None]:
        a = ("diff_%s_now_%s" % (g, kern)) if kern else "wave_%s_now" % g
        b = ("diff_%s_shift_%s" % (g, kern)) if kern else "wave_%s_shift" % g
        if a in d and b in d:
            n += 1
            k += 1 if d[b] <= d[a] else 0
    return k, n


def summary_md(run, rows, stats, now_ends):
    L = []
    a = L.append
    md = ei.md_table
    comp = run["composition"]
    a("# 除外したテーマの網の試し直し（T-124、手法を作る期間）")
    a("")
    a("この文書は `src/stats/explore_diffusion2.py` が出力したもので、手で書き足していない。網・拡散・モデルは、ここでは決めない"
      "（決定はオーナー）。全部並べ、選ばない・勧めない。テーマの名前（除外したテーマを含む）は載せていない。")
    a("")
    a("## 0. 何をどう比べたか")
    a("- 予言日・対象・判定・拡散（熱 τ、再出発つきのランダムウォーク α）・波面・ハブの割り引き・時期（now・shift）・評価は T-123 と同じ。"
      "対象の行 %d。list と listexcl の数字は T-123 の models.tsv（sha256 を照らした）から読み、素朴な予測の行が T-124 で計算し直した"
      "ものと同じことを確かめた。" % run["rows"])
    a("- 除外の語に当たったテーマ %d 個の内訳：全期間に存在する %d、平均が A 以上 %d、その両方 %d。" % (
        comp["excluded_all"], comp["present"], comp["at_least_a"], comp["both"]))
    a("  - listexcl（T-123）：%d 個すべてを点にした。線は一覧どうしと一覧 × 除外だけ。" % comp["excluded_all"])
    a("  - listexcl2（T-124）：除外の語に当たり、全期間に存在し、平均が A 以上のテーマ %d 個（一覧の入れる規則を満たし、除外の規則だけで"
      "外れたもの）を点にした。線は一覧どうし・一覧 × 除外・除外どうしの3種類。" % comp["listexcl2_nodes"])
    a("  - 割り振りの文には「約1825個」とあったが、1825 は平均が A 以上だけの数で、全期間に存在することも満たすものは %d 個。"
      "コードには割り振りの文の条件（両方）を書いた。" % comp["both"])
    if comp.get("listexcl2_not_in_table") is not None:
        a("  - listexcl2 の点 %d 個のうち %d 個は、区分表に無いテーマ（データにだけ現れたテーマ。点の条件の上では正しく入る）。" % (
            comp["listexcl2_nodes"], comp["listexcl2_not_in_table"]))
    a("  - listexcl2 は、listexcl から点の条件（量の少ないテーマを除く）と線の種類（除外どうしの線を足す）の2つを同時に変えている。"
      "listexcl との違いが、どちらによるかは分けられない。")
    a("- 除外したテーマは出どころ・通り道としてだけ使い、予言の対象・評価の行には入れていない。")
    a("")
    a("## 1. 網の中身（now の窓 %d 個の中央値。窓ごとの値は network.tsv）" % len(now_ends))
    a("")
    body = []
    for g in NETWORKS_ALL:
        ss = [s for e, g2, s in stats if g2 == g and e in now_ends]
        if not ss:
            continue

        def med(c):
            return statistics.median([s[c] for s in ss])
        share = statistics.median([s["knn_excl"] / s["knn_entries"] for s in ss if s["knn_entries"]])
        inner = [s for s in ss if s["knn_excl"]]
        body.append((g, med("nodes"), med("edges_ll"), med("edges_le"), med("edges_ee"), med("isolated"),
                     "%.1f" % (100 * share),
                     "%.1f" % (100 * statistics.median([s["knn_excl_present"] / s["knn_excl"] for s in inner]))
                     if inner else "-",
                     "%.1f" % (100 * statistics.median([s["knn_excl_at_least_a"] / s["knn_excl"] for s in inner]))
                     if inner else "-",
                     "%.1f" % (100 * statistics.median([s["knn_excl_both"] / s["knn_excl"] for s in inner]))
                     if inner else "-"))
    a(md(["網", "点", "一覧どうしの線", "一覧 × 除外の線", "除外どうしの線", "線の無い点",
          "一覧の上位10に占める除外（%）", "そのうち全期間に存在（%）", "そのうち A 以上（%）", "そのうち両方（%）"], body))
    a("")
    a("- 一覧の上位10に占める除外：一覧のタグごとの lift の上位10（組の文書の数 %d 以上）のうち、除外したテーマの割合。listexcl では、"
      "一覧のタグの隣の多くが、量の少ない除外したテーマに置き換わっている（T-123 の監査の中-1）。" % ex.MIN_PAIR_DOCS)
    a("")
    for i, sp in enumerate(ex.SPLITS):
        a("## %d. 結果（分け方 %s%s）" % (i + 2, sp, "、主" if sp == ex.SPLIT_MAIN else "、参考。既に何度も見た検証の期間の再利用"))
        a("")
        for m in MULTIPLIERS:
            rs = [r for r in rows if r["split"] == sp and r["multiplier"] == str(m)]
            nv = [r for r in rs if r["model"] == "naive"][0]
            base = float(nv["logloss"])
            a("### 倍率 %d（確かめの行 %s、島 %s）" % (m, nv["n_test"], nv["islands_test"]))
            a("")
            a(md(["モデル", "網", "対数損失", "AUC", "上位10の島", "素朴な予測との差（割合）", "差の範囲（4週束ね）", "上位10の差",
                  "出どころ"],
                 [(r["model"], network_of(r["model"]) or "-", r["logloss"], r["auc"], r["top10_hits"],
                   "-" if r["model"] == "naive" else "%s（%+.2f%%）" % (r["d_logloss_vs_naive"],
                                                                     100 * float(r["d_logloss_vs_naive"]) / base),
                   "-" if r["model"] == "naive" else "%s〜%s" % (r["d_ll_ci4w_lo"], r["d_ll_ci4w_hi"]),
                   "-" if r["model"] == "naive" else r["d_top10_vs_naive"], r["source"]) for r in rs]))
            a("")
            for g in NETWORKS_ALL:
                gs = [r for r in rs if network_of(r["model"]) == g]
                below = sum(1 for r in gs if fnum(r["d_ll_ci4w_hi"]) is not None and fnum(r["d_ll_ci4w_hi"]) < 0)
                above = sum(1 for r in gs if fnum(r["d_ll_ci4w_lo"]) is not None and fnum(r["d_ll_ci4w_lo"]) > 0)
                k, n = shift_vs_now(rows, sp, m, g)
                a("- %s：%d モデルのうち、差の範囲が0より下 %d、0より上 %d。shift の差が now の差以下だったのは %d / %d。" % (
                    g, len(gs), below, above, k, n))
            a("")
        a("- この一覧の読み方：比べたモデルは、分け方と倍率ごとに %d（3つの網。素朴な予測を除く）。T-124 で新しく作ったのは listexcl2 の "
          "%d。出した差の範囲も同じ数で、多重比較の補正をしていない。基準はどれも同じ素朴な予測。4週の束どうしは独立でない（判定期間 %d 日が"
          "隣の束に重なる）。範囲が0を含まないことは、効くことの確かめにはならない。" % (
              run["models_per_split_multiplier_all_networks"], run["new_models_per_split_multiplier"], HORIZON))
        a("")
    a("## 4. T-123 の申し送り（読み方の補い）")
    a("- listexcl の点の内訳と置き換わり：0章と1章のとおり。listexcl の点の大半は、一覧の入れる規則でも外れる量の少ないテーマで、"
      "一覧のタグの lift の上位10の多くがそれに置き換わった。listexcl が list を上回らなかったことは、この置き換わりと合わせて読む。")
    a("- 拡散の見込みと自分の上がり：k ≥ 2 の P^k s には、隣へ行って戻る道を通して自分の上がりも入る。拡散の見込みは、他の点だけから"
      "来た値ではない（k = 0 の自分の項だけを除いた）。")
    a("- ハブの割り引きの次数：listexcl と listexcl2 では、ハブの割り引きの回帰に使う次数に除外したテーマへの線が入る。list とは意味が違う。")
    parts = []
    for m in MULTIPLIERS:
        ks = [shift_vs_now(rows, ex.SPLIT_MAIN, m, g) for g in NETWORKS_ALL]
        parts.append("倍率 %d では %d / %d（%s）" % (m, sum(k for k, _n in ks), sum(n for _k, n in ks),
                                                 "、".join("%s %d/%d" % (g, k, n) for g, (k, n) in zip(NETWORKS_ALL, ks))))
    a("- shift の網：分け方 %s で、3か月前にずらした網（shift）の差が now の差以下だった組み合わせの数は、%s。"
      "網と信号が同じ記事から作られることの影響が有るか無いかは、この比べ方では区別できない。" % (ex.SPLIT_MAIN, "、".join(parts)))
    a("- この版（v2）の注記：v1 の4章の shift の文は、本番の前に固定で書いたもので、結果（倍率 8 では逆）と合わなかったため、"
      "各章の数から作る形に替えた。表の sha256 は v1 と同じ。")
    a("")
    a("## 5. 予言の時点のデータだけを使ったことの確かめ")
    a("- 日の比率と上がり：ReadGuard で、一覧のタグは t-399〜t-1、除外したテーマは t-371〜t-1 の外を読むと止まる。")
    a("- 網：予言日ごとに、窓の月が予言日から決まるものと同じことと、窓の最後の日 < 予言日を確かめた（now と shift）。")
    a("- ハブの割り引きの回帰は、分け方ごとの学習の行だけで当てはめた。")
    a("")
    a("## 6. 限界")
    a("- 分け方 B の確かめ（2018年）も、分け方 A の検証（2019〜2020年）も、既に見た期間の再利用で、未見のデータでの確かめにはならない。")
    a("- 一覧と V の先読み：タグの一覧と V は、手法を作る期間の区画全体のデータで決まった（seq 17）。listexcl2 の点の条件（全期間に存在、"
      "平均が A 以上）も、区画全体のデータで決まる。")
    a("- 除外の規則の漏れ：民族・人物の姓・宗教・犯罪・紛争・政治に当たる名前のテーマが一覧に残っている（オーナーの決定 2026-10-16、(a)）。"
      "要約にはテーマの名前を載せていない。")
    a("- WB のテーマの段のような上昇（T-116 の要約 6章）は、学習の期間の網と上がりに入る。")
    a("- E1〜E3 は、ランダムウォークの歩数の重み付き平均で、最短距離の隣ではない。網の作り方・τ・α・打ち切りの項数も選びうるもので、"
      "比べた数に入っていない。")
    a("")
    a("## 7. 再計算")
    a("```")
    a(".venv/bin/python -B src/stats/explore_diffusion2.py phase1 --store <日の集計> --detail <order5-detail.json> "
      "--t123-cache <explore-t123-cache/run1> --cache-dir <新しいフォルダ>")
    a(".venv/bin/python -B src/stats/explore_diffusion2.py phase2 --cache-dir <同じフォルダ> --t123-cache <explore-t123-cache/run1> "
      "--t117-cache <explore-t117-cache/run2> --detail <order5-detail.json> --t123-models <explore-t123/models.tsv> --out-dir <書き出す先>")
    a("```")
    for k in sorted(run["code"]):
        a("- %s：sha256 %s" % (k, run["code"][k]))
    a("- キャッシュ phase1.json：sha256 %s。T-123 のキャッシュ：%s。T-123 の models.tsv：%s。detail：%s" % (
        run["phase1_sha256"], run["t123_phase1_sha256"], run["t123_models_sha256"], run["detail_sha256"]))
    a("")
    a("## 引用")
    a(ei.CITATION_EN)
    a("")
    a(ei.CITATION_JA)
    out = "\n".join(L) + "\n"
    if "**" in out:
        raise Diffusion2Error("要約に太字の印がある")
    return out.encode("utf-8")


def main(argv=None):
    p = argparse.ArgumentParser(description="T-124 除外したテーマの網の試し直し")
    sub = p.add_subparsers(dest="cmd", required=True)
    p1 = sub.add_parser("phase1")
    p1.add_argument("--store", required=True)
    p1.add_argument("--detail", required=True)
    p1.add_argument("--t123-cache", required=True)
    p1.add_argument("--cache-dir", required=True)
    p1.add_argument("--workers", type=int, default=6)
    p2 = sub.add_parser("phase2")
    p2.add_argument("--cache-dir", required=True)
    p2.add_argument("--t123-cache", required=True)
    p2.add_argument("--t117-cache", required=True)
    p2.add_argument("--detail", required=True)
    p2.add_argument("--t123-models", required=True)
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
            print("%s  phase1.json" % phase1(ei.PROJECT, a.store, a.detail, a.t123_cache, a.cache_dir, a.workers, log))
        else:
            shas = phase2(ei.PROJECT, a.cache_dir, a.t123_cache, a.t117_cache, a.detail, a.t123_models, a.out_dir,
                          a.workers, a.graph_workers, log)
            for name in OUT_NAMES:
                print("%s  %s" % (shas[name], name))
    except (Diffusion2Error, ex.DiffusionError, ed.DenomError, em.ModelError, es.SignalError, ei.ExploreError) as e:
        sys.stderr.write("止まった：%s\n" % e)
        return 1
    log("終わり")
    return 0


if __name__ == "__main__":
    sys.exit(main())
