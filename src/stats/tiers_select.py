#!/usr/bin/env python3
"""T-141：採点計画（docs/stats/claims-scoring-plan.md）8章の「(3) の規則」による、21組の段の形の表。

規則（オーナーの決定 2026-10-20、reviews/T-140.md。流す前にこのファイルに写した）
1. 候補の形：段1 は null_exp・null_fix の2つ、段2 は W（全期間・直近52週）× a（10・50・200）の6つ、段4 は nbwave・chain・
   nbwave_chain の3つ（explore_tiers.py と同じ作り方）。
2. 組（倍率 m、判定期間 H）ごとに、手法を作る期間の分け方 B（学習：予言日 〜2017-12-04、確かめ：2018-01-08〜2018-12-03）の
   確かめの行で、各形の対数損失の平均を求める。段4 の係数は分け方 B の学習の行で当てはめる。
3. 段ごとに、対数損失の平均が最も小さい形を選ぶ。同じ値なら、段1 は null_exp、段2 は全期間を先に a の小さい順、段4 は候補の
   一覧の順（nbwave・chain・nbwave_chain）で先の形を選ぶ。
4.（係数を全期間で当てはめ直して封印するのは、別のタスク）
5. 21組の表（組ごとの各形の対数損失と、選んだ形）を出力する（封印は別のタスク）。

組：倍率 candidates.THRESHOLD_MULTIPLIERS（2・3・4・6・8・12・16）× 判定期間 candidates.HORIZON_DAYS（14・28・56）。
採点する行：判定期間 H ごとに、状態が "target" で、7つの倍率の判定がどれも判定不能でない行（判定不能は倍率に依らない）。
判定が確定した行（段1・段2）：予言日 s の判定期間 s+1〜s+H が t-1 までに終わった行。週の番号で t の ceil((H + 1) / 7) 週以上前。
参考として、段3（素朴な予測）の対数損失も同じ表に並べる（選ぶ対象ではない）。

予言の時点のデータだけ：日の比率は ReadGuard（入力は t-399〜t-1、判定は t+1〜t+H）。網の月は予言日を含む月より前で、網の最後の日 < t
を確かめる（explore_tiers と同じ）。区画の外（2020-12-15 以降）は読まない。閾値を決める期間・基準値を測る期間のデータは読まない。

流し方（プロジェクトのルートで。TMPDIR は scratchpad の中に）
  .venv/bin/python -B src/stats/tiers_select.py --t117-cache <explore-t117-cache/run2> --out-dir <書き出す先>

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

import explore_tiers as tr  # noqa: E402

ch = tr.ch
sea = tr.sea
ed = tr.ed
em = tr.em
es = tr.es
ei = tr.ei
naive = tr.naive
candidates = es.candidates
scoring = es.scoring

LABEL = "tiers-select-t142-v2"   # v2：T-142 で対数損失を丸めずに出し、僅差の印と判定不能の行の数を足した（選び方は同じ）
NEAR_TIE = 1e-6                    # 僅差：選んだ形と、同じ段の次に小さい形の対数損失の差がこれ未満（本番の前に固定）
MULTS = tuple(candidates.THRESHOLD_MULTIPLIERS)
HORIZONS = tuple(candidates.HORIZON_DAYS)
TIER1_FORMS = ("null_exp", "null_fix")
TIER2_FORMS = tuple(("hist_%s_a%d" % (w, a), w, a) for w in ("all", 52) for a in (10, 50, 200))
TIER4_FORMS = ("nbwave", "chain", "nbwave_chain")
SPLIT = "B"
DAY = datetime.timedelta(days=1)


class SelectError(Exception):
    pass


def known_lag_weeks(h):
    """判定が確定している予言日：週の番号で t の ceil((H + 1) / 7) 週以上前（s + H ≤ t − 1）。"""
    return -(-(h + 1) // 7)


def known_end(ti, lag):
    return max(0, ti - lag + 1)


def null_exp(ti, lag, gk, gn):
    e = known_end(ti, lag)
    return (gk[e] + 1) / (gn[e] + 2)


def hist_prob(ti, i, window, a, lag, counts):
    ck, cn, gk, gn = counts
    e = known_end(ti, lag)
    s = 0 if window == "all" else max(0, ti - window)
    s = min(s, e)
    k = ck[i][e] - ck[i][s]
    nn = cn[i][e] - cn[i][s]
    return (k + a * null_exp(ti, lag, gk, gn)) / (nn + a)


def choose(tier, values):
    """values：{形: 対数損失}。最小の形（同じ値なら決まった順で先の形）。"""
    order = {1: [f for f in TIER1_FORMS], 2: [f for f, _w, _a in TIER2_FORMS], 4: list(TIER4_FORMS)}[tier]
    best = min(values[f] for f in order)
    return [f for f in order if values[f] == best][0]


# ---------------------------------------------------------------------------
# タグごとの計算（子プロセス）
# ---------------------------------------------------------------------------

def evaluate_tag_all(days, values, mondays, v):
    """予言日ごとに (状態, B, c, {H: 素朴な予測の値}, {H: 7つの倍率の判定})。対象のときだけ後ろの二つ。"""
    get = ei.ReadGuard(days, values)
    out = []
    for t in mondays:
        get.allow(t - datetime.timedelta(days=naive.naive_lookback_days()), t - DAY)
        st = scoring.target_status(get, t, v)
        b = c = None
        if st != "no_baseline":
            b = candidates.baseline_level(get, t)
            c = candidates.current_level(get, t)
        lvs = js = None
        if st == "target":
            lvs = {h: naive.raw_levels(get, t, h) for h in HORIZONS}
            get.allow(t + DAY, t + datetime.timedelta(days=max(HORIZONS)))
            js = {h: tuple(candidates.judge(get, t, h, m, b, v) for m in MULTS) for h in HORIZONS}
        out.append((st, b, c, lvs, js))
    return out, get.min_read, get.max_read


_W = {}


def _init_eval(days, mondays, v):
    _W.update(days=days, mondays=mondays, v=v)


def _eval_task(args):
    j, values = args
    return (j,) + evaluate_tag_all(_W["days"], values, _W["mondays"], _W["v"])


def subset_table(tb, m, cols, rows):
    """当てはめに要る列と、分け方 B の行（学習と確かめ）だけの表。"""
    out = {"t": [tb["t"][r] for r in rows], "tag": [tb["tag"][r] for r in rows],
           "y%d" % m: array.array("b", [tb["y%d" % m][r] for r in rows])}
    for c in cols:
        col = tb[c]
        out[c] = array.array("d", [col[r] for r in rows])
    return out


def _fit_task(args):
    h, m, name, cols, tb, tri, tei = args
    fit, probs = tr.fit_predict(tb, m, cols, tri, tei)
    return h, m, name, list(fit["coef"]), fit["converged"], array.array("d", probs)


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
    status = [None] * n
    lvs_rows, js_rows = {}, {}
    lo = hi = None
    with es._pool(workers, _init_eval, (days, mondays, v)) as pool:
        for k, (j, res, a, b) in enumerate(pool.imap(_eval_task, list(enumerate(series)), chunksize=8), 1):
            status[j] = [(st, bb, cc) for st, bb, cc, _l, _j in res]
            for ti, (st, _bb, _cc, lv, js) in enumerate(res):
                if st == "target":
                    lvs_rows[(ti, j)] = lv
                    js_rows[(ti, j)] = js
            if a is not None:
                lo = a if lo is None or a < lo else lo
                hi = b if hi is None or b > hi else hi
            if k % 1000 == 0:
                log("タグ %d / %d" % (k, n))
    del series
    if hi > ei.BLOCK_END:
        raise SelectError("区画の外を読んだ")
    targets = sorted(lvs_rows)
    log("対象の行（状態 target）%d" % len(targets))
    dur = [ch.durations([ch.is_high(b, c, v) for (_st, b, c) in status[j]]) for j in range(n)]
    rises = [[es.rise(status[j][ti][2], status[j][ti][1], v)
              if (status[j][ti][1] is not None and status[j][ti][2] is not None) else None for j in range(n)]
             for ti in range(W)]
    del status
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
    for (ti, i) in targets:
        targets_by_week[ti].append(i)
    pred_months = sorted({es.month_key(t) for t in mondays})
    net_off = None
    for t in mondays:
        off = es.check_network_before(t, es.network_months(t, ch.GRAPH_WINDOW, "M"))
        net_off = off if net_off is None else max(net_off, off)
    exc, nbw = {}, {}
    with es._pool(workers, tr._init_graph, (t117_cache, small, dur, dict(targets_by_week), fam_pred, mondays,
                                            rises)) as pool:
        for k, (mk, months, e1, e2) in enumerate(pool.imap(tr._graph_task, pred_months), 1):
            if months != es.network_months(es.month_first(mk), ch.GRAPH_WINDOW, "M"):
                raise SelectError("網の月が違う")
            exc.update(e1)
            nbw.update(e2)
            log("網 %d / %d" % (k, len(pred_months)))
    if sorted(exc) != targets or sorted(nbw) != targets:
        raise SelectError("網の手がかりの行が対象の行と合わない")
    info = {"daily_min_read": lo.isoformat(), "daily_max_read": hi.isoformat(),
            "network_last_day_minus_t_max_days": net_off, "target_rows": len(targets)}
    files = evaluate_and_build(tags, mondays, lvs_rows, js_rows, exc, nbw, v, ctx, info, workers, log)
    return write_outputs(out_dir, files)


def build_tables(tags, mondays, lvs_rows, js_rows, exc, nbw, v):
    """組ごとの表と、段1・段2 の確率。行は判定期間ごと（7つの倍率の判定がどれも判定不能でない対象の行）。"""
    n = len(tags)
    W = len(mondays)
    tables, direct, keys_by_h = {}, {}, {}
    for h in HORIZONS:
        keys = sorted(k for k in lvs_rows if all(x is not None for x in js_rows[k][h]))
        keys_by_h[h] = keys
        by_week = collections.defaultdict(list)
        for (ti, i) in keys:
            by_week[ti].append((i, js_rows[(ti, i)][h]))
        lag = known_lag_weeks(h)
        feats = None
        for mi, m in enumerate(MULTS):
            counts = tr.hist_counts(by_week, n, W, mi)
            tb = {"t": [mondays[k[0]] for k in keys], "tag": [tags[k[1]] for k in keys], "week": [k[0] for k in keys],
                  "y%d" % m: array.array("b", [1 if js_rows[k][h][mi] else 0 for k in keys])}
            feats = [naive.features_from_levels(lvs_rows[k][h], m, v) for k in keys]
            for j in range(len(naive.FEATURES)):
                tb[em.naive_col(m, naive.FEATURES[j])] = array.array("d", [f[j] for f in feats])
            for j, c in enumerate(tr.NBWAVE_COLUMNS):
                tb[c] = array.array("d", [nbw[k][j] for k in keys])
            for j, c in enumerate(tr.CHAIN_COLUMNS):
                tb[c] = array.array("d", [exc[k][j] for k in keys])
            d = {"null_exp": array.array("d", [null_exp(k[0], lag, counts[2], counts[3]) for k in keys])}
            for name, w, a in TIER2_FORMS:
                d[name] = array.array("d", [hist_prob(k[0], k[1], w, a, lag, counts) for k in keys])
            tables[(h, m)], direct[(h, m)] = tb, d
    return tables, direct, keys_by_h


def evaluate_and_build(tags, mondays, lvs_rows, js_rows, exc, nbw, v, ctx, info, workers, log):
    tables, direct, keys_by_h = build_tables(tags, mondays, lvs_rows, js_rows, exc, nbw, v)
    info = dict(info, scored_rows_by_h={str(h): len(keys_by_h[h]) for h in HORIZONS},
                unjudged_rows_by_h={str(h): len(lvs_rows) - len(keys_by_h[h]) for h in HORIZONS})
    log("表を作った")
    split_idx = {}
    for h in HORIZONS:
        keys = keys_by_h[h]
        idx = {k: r for r, k in enumerate(keys)}
        tr_, te_ = ed.split_rows(keys, mondays, SPLIT)
        split_idx[h] = ([idx[k] for k in tr_], [idx[k] for k in te_])
    probs, conv = {}, {}
    for h in HORIZONS:
        tri, tei = split_idx[h]
        rows_b = tri + tei
        sub_tri = list(range(len(tri)))
        sub_tei = list(range(len(tri), len(rows_b)))
        tasks = []
        for m in MULTS:
            base_cols = [em.naive_col(m, f) for f in naive.FEATURES]
            for name, extra in [("naive", ())] + [("t4_" + f, tr.tier4_columns(f)) for f in TIER4_FORMS]:
                cols = base_cols + list(extra)
                tasks.append((h, m, name, cols, subset_table(tables[(h, m)], m, cols, rows_b), sub_tri, sub_tei))
        with es._pool(workers, _init_eval, (None, None, None)) as pool:
            for h2, m, name, _coef, cv, p in pool.imap(_fit_task, tasks):
                probs[(h2, m, name)] = p
                conv[(h2, m, name)] = cv
        del tasks
        log("当てはめ 判定期間 %d" % h)
    rows = []
    for h in HORIZONS:
        tri, tei = split_idx[h]
        for m in MULTS:
            tb = tables[(h, m)]
            y = tb["y%d" % m]
            ys = [y[r] for r in tei]
            base = sum(y[r] for r in tri) / len(tri)
            ps = {"null_fix": [base] * len(tei), "null_exp": [direct[(h, m)]["null_exp"][r] for r in tei]}
            for name, _w, _a in TIER2_FORMS:
                ps[name] = [direct[(h, m)][name][r] for r in tei]
            for f in TIER4_FORMS:
                ps[f] = probs[(h, m, "t4_" + f)]
            ps["naive"] = probs[(h, m, "naive")]
            ll = {name: sum(es.log_loss_terms(p, ys)) / len(ys) for name, p in ps.items()}
            sel = {1: choose(1, ll), 2: choose(2, ll), 4: choose(4, ll)}
            rows.append({"h": h, "m": m, "n_train": len(tri), "n_test": len(tei), "islands_test": sum(ys),
                         "ll": ll, "sel": sel, "conv": {f: conv[(h, m, "t4_" + f)] for f in TIER4_FORMS}})
        log("判定期間 %d" % h)
    return build_outputs(rows, ctx, info)


# ---------------------------------------------------------------------------
# 出力
# ---------------------------------------------------------------------------

OUT_NAMES = ("tiers_select_all.tsv", "tiers_select.tsv", "run.json", "summary.md")
FORM_TIER = dict([(f, 1) for f in TIER1_FORMS] + [(f, 2) for f, _w, _a in TIER2_FORMS] + [(f, 4) for f in TIER4_FORMS]
                 + [("naive", 3)])
FORM_ORDER = list(TIER1_FORMS) + [f for f, _w, _a in TIER2_FORMS] + ["naive"] + list(TIER4_FORMS)


def own_code_shas():
    code = dict(tr.own_code_shas())
    with open(os.path.abspath(__file__), "rb") as f:
        code["src/stats/tiers_select.py"] = hashlib.sha256(f.read()).hexdigest()
    return code


TIER_FORMS = {1: list(TIER1_FORMS), 2: [f for f, _w, _a in TIER2_FORMS], 4: list(TIER4_FORMS)}


def runner_up(r, tier):
    """選んだ形の次の形（選んだ形を除いた中で、同じ規則で選ぶ形）と、その差（次 − 選んだ形。0 以上）。"""
    chosen = r["sel"][tier]
    rest = [f for f in TIER_FORMS[tier] if f != chosen]
    best = min(r["ll"][f] for f in rest)
    nxt = [f for f in rest if r["ll"][f] == best][0]
    return nxt, r["ll"][nxt] - r["ll"][chosen]


def fr(x):
    """丸めない表し方（repr。浮動小数を同じ値に読み戻せる最短の10進）。"""
    return repr(float(x))


def tables_bytes(rows):
    all_rows, sel_rows = [], []
    for r in rows:
        for f in FORM_ORDER:
            tier = FORM_TIER[f]
            chosen = "-" if tier == 3 else ("yes" if r["sel"][tier] == f else "no")
            if tier != 3 and r["sel"][tier] == f:
                nxt, gap = runner_up(r, tier)
                extra = (nxt, fr(gap), "yes" if gap < NEAR_TIE else "no")
            else:
                extra = ("-", "-", "-")
            all_rows.append((r["h"], r["m"], tier, f, r["n_test"], r["islands_test"], fr(r["ll"][f]), chosen) + extra)
        cells = []
        for tier in (1, 2, 4):
            nxt, gap = runner_up(r, tier)
            cells += [r["sel"][tier], fr(r["ll"][r["sel"][tier]]), nxt, fr(gap), "yes" if gap < NEAR_TIE else "no"]
        sel_rows.append((r["h"], r["m"], r["n_train"], r["n_test"], r["islands_test"]) + tuple(cells)
                        + (fr(r["ll"]["naive"]),))
    a = ei.tsv(("horizon_days", "multiplier", "tier", "form", "n_test", "islands_test", "logloss", "chosen",
                "next_form", "gap_to_next", "near_tie"), all_rows)
    head = ("horizon_days", "multiplier", "n_train", "n_test", "islands_test")
    for tier in (1, 2, 4):
        head += ("tier%d_form" % tier, "tier%d_logloss" % tier, "tier%d_next_form" % tier, "tier%d_gap_to_next" % tier,
                 "tier%d_near_tie" % tier)
    b = ei.tsv(head + ("naive_logloss_reference",), sel_rows)
    return a, b


def build_outputs(rows, ctx, info):
    a, b = tables_bytes(rows)
    nc = sorted("%d/%d/%s" % (r["h"], r["m"], f) for r in rows for f, c in r["conv"].items() if not c)
    run = {"label": LABEL, "code": own_code_shas(), "python": sys.version.split()[0], "refs": ctx["refs"],
           "v": "%d/%d" % (ctx["v"].numerator, ctx["v"].denominator), "info": info, "split": SPLIT,
           "multipliers": MULTS, "horizons": HORIZONS, "tier1_forms": TIER1_FORMS,
           "tier2_forms": [f for f, _w, _a in TIER2_FORMS], "tier4_forms": TIER4_FORMS,
           "known_lag_weeks": {str(h): known_lag_weeks(h) for h in HORIZONS}, "not_converged": nc,
           "near_tie": NEAR_TIE,
           "citation": [ei.CITATION_EN, ei.CITATION_JA]}
    files = {"tiers_select_all.tsv": a, "tiers_select.tsv": b,
             "run.json": (json.dumps(run, ensure_ascii=False, sort_keys=True, indent=1) + "\n").encode("utf-8")}
    files["summary.md"] = summary_md(run, rows)
    for name, data in files.items():
        ei.check_public(name, data)
    return files


def summary_md(run, rows):
    L = []
    a = L.append
    a("# 21組の段の形の表（T-142、手法を作る期間）")
    a("")
    a("この文書は `src/stats/tiers_select.py` が出力したもので、手で書き足していない。採点計画（docs/stats/claims-scoring-plan.md）"
      "8章の「(3) の規則」（オーナーの決定 2026-10-20）を、手法を作る期間の分け方 B の確かめの行で当てはめた。封印していない。"
      "テーマの名前は載せていない。")
    a("この版（v2、T-142）の変更点：表の対数損失を丸めずに出し、僅差の印（選んだ形と次の形の差が %s 未満）と、判定不能の行の数を足した。"
      "選び方とデータは T-141 と同じ。" % fr(NEAR_TIE))
    a("")
    a("## 1. 選んだ形")
    a("")
    a(ei.md_table(["判定期間（日）", "倍率", "確かめの行", "島", "段1", "段2", "段4", "段3（参考）の対数損失"],
                  [(r["h"], r["m"], r["n_test"], r["islands_test"], "%s（%.6f）" % (r["sel"][1], r["ll"][r["sel"][1]]),
                    "%s（%.6f）" % (r["sel"][2], r["ll"][r["sel"][2]]), "%s（%.6f）" % (r["sel"][4], r["ll"][r["sel"][4]]),
                    "%.6f" % r["ll"]["naive"]) for r in rows]))
    a("")
    a("## 2. 全形の対数損失")
    a("")
    a(ei.md_table(["判定期間（日）", "倍率"] + FORM_ORDER,
                  [(r["h"], r["m"]) + tuple("%.6f" % r["ll"][f] for f in FORM_ORDER) for r in rows]))
    a("")
    ties = [(r["h"], r["m"], tier, r["sel"][tier]) + runner_up(r, tier) for r in rows for tier in (1, 2, 4)
            if runner_up(r, tier)[1] < NEAR_TIE]
    a("## 2b. 僅差の組と段")
    a("")
    a("選んだ形と、同じ段の次の形の対数損失の差が %s 未満の組と段：%d。差は丸めない値で計算した（表の gap_to_next）。" % (
        fr(NEAR_TIE), len(ties)))
    a("")
    if ties:
        a(ei.md_table(["判定期間（日）", "倍率", "段", "選んだ形", "次の形", "差"],
                      [(h, m, t, f, nxt, fr(g)) for h, m, t, f, nxt, g in ties]))
        a("")
    a("## 3. 作り方")
    a("- 組：倍率 %s × 判定期間 %s 日。" % ("・".join(str(m) for m in MULTS), "・".join(str(h) for h in HORIZONS)))
    a("- 採点する行：判定期間ごとに、状態が target で、7つの倍率の判定がどれも判定不能でない行。分け方 B（学習：予言日 〜%s、"
      "確かめ：%s〜%s）。" % (em.INNER_TRAIN_LAST, em.INNER_VAL_FIRST, es.TRAIN_LAST))
    a("- 段1・段2 は、判定が確定した行（週の番号で t の ceil((H + 1) / 7) 週以上前：%s）の判定だけで作った。" % "、".join(
        "H = %s で %d 週" % (h, w) for h, w in sorted(run["known_lag_weeks"].items(), key=lambda x: int(x[0]))))
    a("- 段4 の係数は、分け方 B の学習の行で当てはめた（ロジスティック回帰、リッジ 1）。当てはめが収まらなかったもの：%s。" % (
        "、".join(run["not_converged"]) if run["not_converged"] else "無い"))
    a("- 選び方：段ごとに対数損失が最も小さい形。同じ値（浮動小数の完全一致）なら決まった順で先の形。表の対数損失は丸めずに出した"
      "（repr）。要約の表は小数6桁に丸めたもので、6桁で同じに見える形どうしの順は tiers_select_all.tsv の丸めない値で読む。")
    a("- 判定不能の行：この期間では、状態が target の行のうち判定不能の行は %s だった（仕組みとしては、判定不能は欠けた日だけで決まり、"
      "倍率に依らない）。採点する行は %s。" % (
          "、".join("H = %s で %d 件" % (h, c) for h, c in sorted(run["info"]["unjudged_rows_by_h"].items(),
                                                              key=lambda x: int(x[0]))),
          "、".join("H = %s で %d 件" % (h, c) for h, c in sorted(run["info"]["scored_rows_by_h"].items(),
                                                              key=lambda x: int(x[0])))))
    a("- 再計算の条件：Python %s。行は予言日・タグ名の昇順に並べ、対数損失は行ごとの値を組み込みの sum で足して行の数で割る"
      "（Python 3.12 以降の sum は補正付きの足し算）。当てはめは naive.py と同じ手順（ニュートン法、リッジ 1、学習の行は予言日・タグ名の昇順）。"
      % run["python"])
    a("- 日の比率は ReadGuard（入力は t-399〜t-1、判定は t+1〜t+H）。読んだ日の範囲は %s〜%s。網は予言日ごとに網の最後の日 < 予言日を"
      "確かめた。" % (run["info"]["daily_min_read"], run["info"]["daily_max_read"]))
    a("")
    a("## 4. 限界")
    a("- 分け方 B の確かめの期間（2018年）は、T-117〜T-134 で何度も見た期間で、段4 の候補はその結果を見て作った。")
    a("- 判定期間 56 日では、学習の最後の予言日（2017-12-04）の判定期間（〜2018-01-29）が、確かめの最初の予言日（2018-01-08）の判定期間"
      "（2018-01-09〜）と3週重なる。判定期間 14・28 日では重ならない。分け方 B は予言日で分けていて、判定期間に依らない（T-117〜T-134 と同じ）。")
    a("- 判定期間 28 日・倍率 2・4・8 は、T-134（explore-t134r1）と同じ行・同じ作り方。")
    a("")
    a("## 5. 再計算")
    a("```")
    a(".venv/bin/python -B src/stats/tiers_select.py --t117-cache <explore-t117-cache/run2> --out-dir <書き出す先>")
    a("```")
    for k in sorted(run["code"]):
        a("- %s：sha256 %s" % (k, run["code"][k]))
    a("")
    a("## 引用")
    a(ei.CITATION_EN)
    a("")
    a(ei.CITATION_JA)
    out = "\n".join(L) + "\n"
    if "**" in out or "%%" in out:
        raise SelectError("要約の書式に誤りがある")
    return out.encode("utf-8")


def write_outputs(out_dir, files):
    if sorted(files) != sorted(OUT_NAMES):
        raise SelectError("出力の名前が決めた一覧と違う")
    os.makedirs(out_dir, exist_ok=True)
    for name in OUT_NAMES:
        if os.path.lexists(os.path.join(out_dir, name)):
            raise SelectError("書き出す先に同じ名前のファイル（%s）がある。上書きしない" % name)
    return {name: es.write_new(os.path.join(out_dir, name), files[name]) for name in OUT_NAMES}


def main(argv=None):
    p = argparse.ArgumentParser(description="T-141 21組の段の形の表")
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
    except (SelectError, tr.TierError, ch.ChainError, sea.SeaError, ed.DenomError, em.ModelError, es.SignalError,
            ei.ExploreError) as e:
        sys.stderr.write("止まった：%s\n" % e)
        return 1
    for name in OUT_NAMES:
        print("%s  %s" % (shas[name], name))
    log("終わり")
    return 0


if __name__ == "__main__":
    sys.exit(main())
