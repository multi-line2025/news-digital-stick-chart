#!/usr/bin/env python3
"""T-146：chain の続いた週数 d に上限 52 を付けたときの、当てはめ（上限なし）との差の確かめ（手法を作る期間）。

採点計画 2章 (7) の決定（2026-10-20 オーナー、reviews/T-145.md）：前向きの予言では、chain の d を予言日から前へ最大52個の月曜までだけ
数える（d ≤ 52）。手法を作る期間の当てはめ（T-143・T-145 の係数）は、d に上限を付けずに数えた。
ここでは、手法を作る期間の行で次を数える（係数は作り直さない）。
  1. 「高い」状態が続いた週数 d が D_CAP（52）を超えたタグと予言日の組の数（すべてのタグ・すべての予言日）。
  2. d を min(d, D_CAP) にしたときの、対象の行の chain の4つの列（D = 1・λ = 2）の差の絶対値の最大。
重みの上限：d > 52 のとき、上限なしの重みは exp(−(d−1)/2) ≤ exp(−26) ≈ 5.1e-12、上限を付けた重みは exp(−51/2) ≈ 8.4e-12。
1つのタグあたりの差は 8.4e-12 以下で、重み付き平均の差もそれ以下になる。

予言の時点のデータだけ：日の比率は ReadGuard（入力は t-399〜t-1）。区画の外（2020-12-15 以降）は読まない。

流し方（プロジェクトのルートで。TMPDIR は scratchpad の中に）
  .venv/bin/python -B src/stats/chain_cap_check.py --t117-cache <explore-t117-cache/run2> --out-dir <書き出す先>

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
es = tr.es
ei = tr.ei

LABEL = "chain-cap-t146-v1"
D_CAP = 52


class CapError(Exception):
    pass


def capped(dur, cap=D_CAP):
    return array.array("H", [min(d, cap) for d in dur])


def weight_bounds(cap=D_CAP, lam=tr.CHAIN_VARIANT[1]):
    """(上限なしで d > cap のときの重みの最大, 上限を付けたときの重み)。"""
    return math.exp(-cap / lam), math.exp(-(cap - 1) / lam)


def max_abs_diff(a, b):
    """{行: 並び} どうしの、同じ位置の差の絶対値の最大。"""
    if sorted(a) != sorted(b):
        raise CapError("行が違う")
    m = 0.0
    for k in a:
        for x, y in zip(a[k], b[k]):
            m = max(m, abs(x - y))
    return m


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
            results[j] = [(st, bb, cc) for st, bb, cc, _m1, _m2, _js, _lv in res]
            if a is not None:
                lo = a if lo is None or a < lo else lo
                hi = b if hi is None or b > hi else hi
    del series
    if hi > ei.BLOCK_END:
        raise CapError("区画の外を読んだ")
    targets = sorted((ti, i) for i in range(n) for ti in range(W) if results[i][ti][0] == "target")
    dur = [ch.durations([ch.is_high(b, c, v) for (_st, b, c) in results[j]]) for j in range(n)]
    rises = [[es.rise(results[j][ti][2], results[j][ti][1], v)
              if (results[j][ti][1] is not None and results[j][ti][2] is not None) else None for j in range(n)]
             for ti in range(W)]
    del results
    over = [(i, ti, dur[i][ti]) for i in range(n) for ti in range(W) if dur[i][ti] > D_CAP]
    log("d > %d の組 %d" % (D_CAP, len(over)))
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
    tbw = collections.defaultdict(list)
    for (ti, i) in targets:
        tbw[ti].append(i)
    pred_months = sorted({es.month_key(t) for t in mondays})
    feats = {}
    for name, dd in (("uncapped", dur), ("capped", [capped(d) for d in dur])):
        exc = {}
        with es._pool(workers, tr._init_graph, (t117_cache, small, dd, dict(tbw), fam_pred, mondays, rises)) as pool:
            for mk, months, e1, _e2 in pool.imap(tr._graph_task, pred_months):
                if months != es.network_months(es.month_first(mk), ch.GRAPH_WINDOW, "M"):
                    raise CapError("網の月が違う")
                exc.update(e1)
        feats[name] = exc
        log("励起の量（%s）" % name)
    diff = max_abs_diff(feats["uncapped"], feats["capped"])
    over_targets = sum(1 for (ti, i) in targets if dur[i][ti] > D_CAP)
    wmax, wcap = weight_bounds()
    out = {"label": LABEL, "d_cap": D_CAP, "lambda": tr.CHAIN_VARIANT[1], "min_weeks": tr.CHAIN_VARIANT[0],
           "pairs_over_cap": len(over), "pairs_over_cap_on_target_rows": over_targets,
           "max_d": max((d for _i, _t, d in over), default=max(max(x) for x in dur)),
           "tags_over_cap": len({i for i, _t, _d in over}),
           "max_abs_diff_chain_columns": diff, "target_rows": len(targets),
           "weight_uncapped_max_over_cap": wmax, "weight_capped_at_cap": wcap,
           "daily_min_read": lo.isoformat(), "daily_max_read": hi.isoformat(),
           "code": dict(tr.own_code_shas(), **{"src/stats/chain_cap_check.py": own_sha()}),
           "python": sys.version.split()[0], "citation": [ei.CITATION_EN, ei.CITATION_JA]}
    files = {"chain_cap.json": (json.dumps(out, ensure_ascii=False, sort_keys=True, indent=1) + "\n").encode("utf-8")}
    files["summary.md"] = summary_md(out)
    for k, d in files.items():
        ei.check_public(k, d)
    os.makedirs(out_dir, exist_ok=True)
    for k in files:
        if os.path.lexists(os.path.join(out_dir, k)):
            raise CapError("書き出す先に同じ名前のファイルがある。上書きしない")
    return {k: es.write_new(os.path.join(out_dir, k), d) for k, d in files.items()}


def own_sha():
    with open(os.path.abspath(__file__), "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def summary_md(out):
    L = ["# chain の続いた週数 d の上限 52 の確かめ（T-146、手法を作る期間）", "",
         "この文書は `src/stats/chain_cap_check.py` が出力したもので、手で書き足していない。係数は作り直していない。", "",
         "- 「高い」状態の続いた週数 d が %d を超えたタグと予言日の組：%d（タグ %d、すべてのタグ・すべての予言日。d の最大 %d）。"
         % (out["d_cap"], out["pairs_over_cap"], out["tags_over_cap"], out["max_d"]),
         "- そのうち対象の行（状態 target）の組：%d（対象の行 %d）。" % (out["pairs_over_cap_on_target_rows"], out["target_rows"]),
         "- d を min(d, %d) にしたときの、対象の行の chain の4つの列（D = %d、λ = %g）の差の絶対値の最大：%r。" % (
             out["d_cap"], out["min_weeks"], out["lambda"], out["max_abs_diff_chain_columns"]),
         "- 重み：d > %d のとき、上限なしの重みは %r 以下、上限を付けた重みは %r。1つのタグあたりの差はこれ以下で、"
         "重み付き平均の差もこれ以下になる。" % (out["d_cap"], out["weight_uncapped_max_over_cap"], out["weight_capped_at_cap"]),
         "- 読んだ日の範囲：%s〜%s（区画の中）。Python %s。" % (out["daily_min_read"], out["daily_max_read"], out["python"]), ""]
    for k in sorted(out["code"]):
        L.append("- %s：sha256 %s" % (k, out["code"][k]))
    L += ["", "## 引用", ei.CITATION_EN, "", ei.CITATION_JA]
    s = "\n".join(L) + "\n"
    if "**" in s or "%%" in s:
        raise CapError("要約の書式に誤りがある")
    return s.encode("utf-8")


def main(argv=None):
    p = argparse.ArgumentParser(description="T-146 chain の d の上限の確かめ")
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
    except (CapError, tr.TierError, ch.ChainError, es.SignalError, ei.ExploreError) as e:
        sys.stderr.write("止まった：%s\n" % e)
        return 1
    for k in sorted(shas):
        print("%s  %s" % (shas[k], k))
    return 0


if __name__ == "__main__":
    sys.exit(main())
