#!/usr/bin/env python3
"""T-143：順番7・順番8 と、採点計画の段4・N3・N4 の係数（封印の前の出力。封印はしない）。

出すもの
1. 順番7：periods.py の出力（--naive-history-days 399 --deadline-status before_deadline）。399 は naive.naive_lookback_days()。
2. 順番8：naive.py と scoring.py の出力（引数なしの canonical JSON）と、素朴な予測の21組（倍率7 × 判定期間3）の係数。
3. 採点計画（docs/stats/claims-scoring-plan.md）2章 (6)・8章 (3) の4：21組の表（docs/stats/tiers-select-t142/tiers_select.tsv）の
   選んだ形で、段4・N3・N4 の係数を21組ぶん。段1 の null_fix の定数（全21組。選ばれた組で使う）。

当てはめ（流す前に書いた。naive-scoring.md 3章 (2)・採点計画 2章 (6) のとおり）
- 行：手法を作る期間のすべての予言日（periods.py の予言の曜日。今は月曜、232回）の、状態が target で、判定期間 H の7つの倍率の
  判定がどれも判定不能でない行。判定不能の行だけを除き、ほかには何も除かない。
- 行の並べ方：予言日・タグ名の昇順（naive.sort_rows と同じ。同じ組があれば止まる）。
- 推定：em.fit_logistic_cols（naive.fit_logistic とビット単位で同じ結果になる。tests/stats/test_explore_models.py で確かめている）。
  リッジ 1（切片にも掛ける）、係数0から始めるニュートン法、一歩を半分に最大30回、TOL 1e-10、100回まで。収まらなければ止まる。
- 段2 の確率（N3・N4 の入力）：その行の予言日 t の時点で判定が確定した行（週の番号で t の ceil((H + 1) / 7) 週以上前）だけで作る。
  全期間は 2016-04-11 から（採点計画 8章 (4)）。
- 段4 の列：explore_tiers と同じ（nbwave は T-119 の hop_signals、chain は T-127 の D = 1・λ = 2）。

予言の時点のデータだけ：日の比率は ReadGuard（入力は t-399〜t-1、判定は t+1〜t+H）。網の最後の日 < t を確かめる。
区画の外（2020-12-15 以降）は読まない。閾値を決める期間・基準値を測る期間のデータは読まない。

流し方（プロジェクトのルートで。TMPDIR は scratchpad の中に）
  .venv/bin/python -B src/stats/order8_fit.py --t117-cache <explore-t117-cache/run2> --out-dir <書き出す先>

Data: The GDELT Project (https://www.gdeltproject.org/). This project is not affiliated with or endorsed by the GDELT Project.
"""

import argparse
import array
import collections
import datetime
import hashlib
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import tiers_select as ts  # noqa: E402

tr = ts.tr
ch = ts.ch
sea = ts.sea
ed = ts.ed
em = ts.em
es = ts.es
ei = ts.ei
naive = ts.naive
candidates = ts.candidates
scoring = ts.scoring

LABEL = "order8-fit-t145-v2"   # v2：T-145 で N3・N4 の学習の行を絞った（オーナーの決定 B、2026-10-20）。ほかは v1 と同じ
# N3・N4 の学習の行（オーナーの決定 B、reviews/T-143.md 末尾。T-143 の係数を見たあとの規則の変更）：
#   予言日 t の時点で判定が確定した予言日（週）の数が MIN_KNOWN_WEEKS 以上の行だけで当てはめる。
#   判定が確定した予言日の数 = 手法を作る期間の最初の予言日（2016-04-11、週の番号 0）から、週の番号 ti − ceil((H + 1) / 7) までの
#   予言日（月曜）の数 = ti − ceil((H + 1) / 7) + 1（タグによらない週の数。2016-04-11 からの経過週ではない）。
#   段1・段2・段3・段4 の当てはめは変えない。
MIN_KNOWN_WEEKS = 52
NAIVE_HISTORY_DAYS = 399
SELECT_TABLE = os.path.join(ei.PROJECT, "docs", "stats", "tiers-select-t142", "tiers_select.tsv")
SELECT_TABLE_SHA256 = "13a2784652964f0e1da23d28cba0970744ab8aadcbc715a35edfcf982ffc30b6"
HIST_FORMS = {f: (w, a) for f, w, a in ts.TIER2_FORMS}


class Order8Error(Exception):
    pass


def read_selection(path=SELECT_TABLE, want=SELECT_TABLE_SHA256):
    """21組の表（tiers-select-t142）を sha256 を照らしてから読む。{(H, m): {"tier1", "tier2", "tier4"}}。"""
    raw = ei.read_nofollow(path)
    if hashlib.sha256(raw).hexdigest() != want:
        raise Order8Error("21組の表の sha256 が違う")
    lines = raw.decode("utf-8").splitlines()
    head = lines[0].split("\t")
    out = {}
    for ln in lines[1:]:
        r = dict(zip(head, ln.split("\t")))
        out[(int(r["horizon_days"]), int(r["multiplier"]))] = {"tier1": r["tier1_form"], "tier2": r["tier2_form"],
                                                               "tier4": r["tier4_form"]}
    if sorted(out) != sorted((h, m) for h in ts.HORIZONS for m in ts.MULTS):
        raise Order8Error("21組がそろっていない")
    return out


def model_specs(sel):
    """(H, m, 名前, 足す列) の一覧。naive は素朴な予測、t4 は段4、n3・n4 は入れ子の並び。"""
    out = []
    for h in ts.HORIZONS:
        for m in ts.MULTS:
            s = sel[(h, m)]
            t4 = tuple(tr.tier4_columns(s["tier4"]))
            lh = ("lh_" + s["tier2"],)
            out += [(h, m, "naive", ()), (h, m, "t4", t4), (h, m, "n3", lh), (h, m, "n4", lh + t4)]
    return out


def sorted_rows(tb, rows):
    """行を予言日・タグ名の昇順に（naive.sort_rows と同じ並べ方）。同じ組が二つあれば止まる。"""
    out = sorted(rows, key=lambda r: (tb["t"][r], tb["tag"][r]))
    for a, b in zip(out, out[1:]):
        if (tb["t"][a], tb["tag"][a]) == (tb["t"][b], tb["tag"][b]):
            raise Order8Error("同じ予言日とタグの行が二つある")
    return out


def known_weeks(ti, h):
    """予言日（週の番号 ti）の時点で判定が確定した予言日の数（2016-04-11 から。タグによらない）。"""
    return max(0, ti - ts.known_lag_weeks(h) + 1)


def n3n4_rows(tb, rows, h):
    """N3・N4 の学習の行：判定が確定した予言日の数が MIN_KNOWN_WEEKS 以上の行（並びは rows のまま）。"""
    return [r for r in rows if known_weeks(tb["week"][r], h) >= MIN_KNOWN_WEEKS]


def _fit_task(args):
    h, m, name, colnames, cols, y = args
    fit = em.fit_logistic_cols(cols, y, em.FIXED_LAMBDA)
    return h, m, name, colnames, list(fit["coef"]), fit["converged"], fit["iterations"]


def _init_none():
    pass


def command_output(args):
    """プロジェクトのコードを引数つきで流した標準出力（バイト列）。"""
    r = subprocess.run([sys.executable, "-B"] + args, cwd=ei.PROJECT, capture_output=True, check=True,
                       env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
    return r.stdout


def run(root, t117_cache, out_dir, workers, log):
    es.check_free(os.path.dirname(os.path.abspath(out_dir)))
    if naive.naive_lookback_days() != NAIVE_HISTORY_DAYS:
        raise Order8Error("naive_lookback_days() が 399 でない")
    sel = read_selection()
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
    with es._pool(workers, ts._init_eval, (days, mondays, v)) as pool:
        for k, (j, res, a, b) in enumerate(pool.imap(ts._eval_task, list(enumerate(series)), chunksize=8), 1):
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
        raise Order8Error("区画の外を読んだ")
    targets = sorted(lvs_rows)
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
                raise Order8Error("網の月が違う")
            exc.update(e1)
            nbw.update(e2)
    if sorted(exc) != targets or sorted(nbw) != targets:
        raise Order8Error("網の手がかりの行が対象の行と合わない")
    log("網を作った")
    tables, _direct, keys_by_h = ts.build_tables(tags, mondays, lvs_rows, js_rows, exc, nbw, v)
    for h in ts.HORIZONS:
        for m in ts.MULTS:
            for f in HIST_FORMS:
                tables[(h, m)]["lh_" + f] = array.array("d", [tr.logit(p) for p in _direct[(h, m)][f]])
    info = {"daily_min_read": lo.isoformat(), "daily_max_read": hi.isoformat(),
            "network_last_day_minus_t_max_days": net_off, "target_rows": len(targets),
            "rows_by_h": {str(h): len(keys_by_h[h]) for h in ts.HORIZONS}}
    coefs, null_fix = [], []
    info["rows_n3n4_by_h"] = {}
    for h in ts.HORIZONS:
        rows = sorted_rows(tables[(h, ts.MULTS[0])], range(len(keys_by_h[h])))
        info["rows_n3n4_by_h"][str(h)] = len(n3n4_rows(tables[(h, ts.MULTS[0])], rows, h))
        tasks = []
        for (h2, m, name, extra) in [s for s in model_specs(sel) if s[0] == h]:
            tb = tables[(h, m)]
            colnames = ["intercept"] + list(naive.FEATURES[1:]) + list(extra)
            cols = [em.column_values(tb, em.naive_col(m, f), rows) for f in naive.FEATURES] + \
                [em.column_values(tb, c, rows) for c in extra]
            use = rows if name in ("naive", "t4") else n3n4_rows(tb, rows, h)
            if use is not rows:
                cols = [em.column_values(tb, em.naive_col(m, f), use) for f in naive.FEATURES] + \
                    [em.column_values(tb, c, use) for c in extra]
            y = [tb["y%d" % m][r] for r in use]
            tasks.append((h, m, name, colnames, cols, y))
        for m in ts.MULTS:
            y = tables[(h, m)]["y%d" % m]
            null_fix.append((h, m, len(y), sum(y), sum(y) / len(y)))
        with es._pool(workers, _init_none, ()) as pool:
            for res in pool.imap(_fit_task, tasks):
                if not res[5]:
                    raise Order8Error("当てはめが収まらなかった：%d/%d/%s" % res[:3])
                coefs.append(res)
        log("当てはめ 判定期間 %d" % h)
    files = build_outputs(sel, coefs, null_fix, info, ctx)
    return write_outputs(out_dir, files)


# ---------------------------------------------------------------------------
# 出力
# ---------------------------------------------------------------------------

OUT_NAMES = ("periods-order7.json", "naive.json", "scoring.json", "naive_coefs.tsv", "tier4_coefs.tsv",
             "n3_coefs.tsv", "n4_coefs.tsv", "tier1_null_fix.tsv", "forms.tsv", "run.json", "summary.md")
MODEL_FILE = {"naive": "naive_coefs.tsv", "t4": "tier4_coefs.tsv", "n3": "n3_coefs.tsv", "n4": "n4_coefs.tsv"}


def fr(x):
    return repr(float(x))


def own_code_shas():
    code = dict(ts.own_code_shas())
    with open(os.path.abspath(__file__), "rb") as f:
        code["src/stats/order8_fit.py"] = hashlib.sha256(f.read()).hexdigest()
    return code


def build_outputs(sel, coefs, null_fix, info, ctx):
    files = {}
    files["periods-order7.json"] = command_output(["src/stats/periods.py", "--naive-history-days",
                                                   str(NAIVE_HISTORY_DAYS), "--deadline-status", "before_deadline"])
    files["naive.json"] = command_output(["src/stats/naive.py"])
    files["scoring.json"] = command_output(["src/stats/scoring.py"])
    for name, fn in MODEL_FILE.items():
        rows = [(h, m, k, c, fr(b), it) for h, m, nm, cols, cf, _cv, it in coefs if nm == name
                for k, (c, b) in enumerate(zip(cols, cf))]
        files[fn] = ei.tsv(("horizon_days", "multiplier", "index", "column", "coef", "iterations"), rows)
    files["tier1_null_fix.tsv"] = ei.tsv(("horizon_days", "multiplier", "rows", "islands", "rate"),
                                         [(h, m, nr, k, fr(r)) for h, m, nr, k, r in null_fix])
    files["forms.tsv"] = ei.tsv(("horizon_days", "multiplier", "tier1_form", "tier2_form", "tier2_window",
                                 "tier2_a", "tier4_form", "tier4_columns"),
                                [(h, m, sel[(h, m)]["tier1"], sel[(h, m)]["tier2"], HIST_FORMS[sel[(h, m)]["tier2"]][0],
                                  HIST_FORMS[sel[(h, m)]["tier2"]][1], sel[(h, m)]["tier4"],
                                  ",".join(tr.tier4_columns(sel[(h, m)]["tier4"])))
                                 for h in ts.HORIZONS for m in ts.MULTS])
    run = {"label": LABEL, "code": own_code_shas(), "python": sys.version.split()[0], "refs": ctx["refs"],
           "v": "%d/%d" % (ctx["v"].numerator, ctx["v"].denominator), "info": info,
           "naive_history_days": NAIVE_HISTORY_DAYS, "select_table": "docs/stats/tiers-select-t142/tiers_select.tsv",
           "select_table_sha256": SELECT_TABLE_SHA256, "prediction_dates": "method period, %d dates" % 232,
           "models": len(coefs), "min_known_weeks_n3n4": MIN_KNOWN_WEEKS,
           "rows_n3n4_by_h": {str(h): n for h, n in info.get("rows_n3n4_by_h", {}).items()},
           "citation": [ei.CITATION_EN, ei.CITATION_JA]}
    files["run.json"] = (json.dumps(run, ensure_ascii=False, sort_keys=True, indent=1) + "\n").encode("utf-8")
    files["summary.md"] = summary_md(run, files)
    for name, data in files.items():
        ei.check_public(name, data)
    return files


def summary_md(run, files):
    L = []
    a = L.append
    a("# 順番7・順番8 と段4・N3・N4 の係数（T-145、封印の前の出力）")
    a("")
    a("この文書は `src/stats/order8_fit.py` が出力したもので、手で書き足していない。封印していない（封印は封印係が行う）。"
      "テーマの名前は載せていない。")
    a("")
    a("## 1. ファイル")
    a("")
    a(ei.md_table(["ファイル", "中身", "sha256"],
                  [(name, desc, hashlib.sha256(files[name]).hexdigest()) for name, desc in (
                      ("periods-order7.json", "順番7：periods.py --naive-history-days 399 --deadline-status before_deadline の出力"),
                      ("naive.json", "順番8：naive.py の出力（引数なし）"),
                      ("scoring.json", "順番8：scoring.py の出力（引数なし）"),
                      ("naive_coefs.tsv", "順番8：素朴な予測の21組の係数"),
                      ("tier4_coefs.tsv", "段4 の21組の係数（21組の表の選んだ形）"),
                      ("n3_coefs.tsv", "N3 の21組の係数"),
                      ("n4_coefs.tsv", "N4 の21組の係数"),
                      ("tier1_null_fix.tsv", "段1 の null_fix の定数（全21組）"),
                      ("forms.tsv", "21組の選んだ形（tiers-select-t142 の表から）"))]))
    a("")
    a("## 2. 当てはめ")
    a("- 行：手法を作る期間のすべての予言日（%s）の、状態が target で、判定期間 H の7つの倍率の判定がどれも判定不能でない行。"
      "行の数：%s。" % (run["prediction_dates"], "、".join("H = %s で %d" % (h, c) for h, c in sorted(
          run["info"]["rows_by_h"].items(), key=lambda x: int(x[0])))))
    a("- 行は予言日・タグ名の昇順。推定は em.fit_logistic_cols（naive.fit_logistic とビット単位で同じ）、リッジ 1（切片にも掛ける）。"
      "当てはめは %d 個で、すべて収まった。" % run["models"])
    a("- N3・N4 の学習の行（v2。オーナーの決定 B、2026-10-20。T-143 の係数を見たあとの規則の変更）：予言日の時点で判定が確定した"
      "予言日（2016-04-11 から数えた月曜。タグによらない週の数）が %d 以上の行だけ。行の数：%s。段3・段4 の行は上と同じ（変えていない）。"
      "変更前（T-143、order8-t143）の係数も残して公開する。" % (run["min_known_weeks_n3n4"], "、".join(
          "H = %s で %d" % (h, c) for h, c in sorted(run["rows_n3n4_by_h"].items(), key=lambda x: int(x[0])))))
    a("- 段2 の確率（N3・N4 の入力）は、行の予言日の時点で判定が確定した行だけで作った（全期間は 2016-04-11 から）。")
    a("- 21組の表：%s（sha256 %s を照らしてから読んだ）。" % (run["select_table"], run["select_table_sha256"]))
    a("- 日の比率は ReadGuard（入力は t-399〜t-1、判定は t+1〜t+H）。読んだ日の範囲は %s〜%s（区画の終わり 2020-12-14 より前）。"
      "網は予言日ごとに網の最後の日 < 予言日を確かめた（最後の日 − 予言日の最大 %d 日）。" % (
          run["info"]["daily_min_read"], run["info"]["daily_max_read"], run["info"]["network_last_day_minus_t_max_days"]))
    a("")
    a("## 3. 再計算")
    a("```")
    a(".venv/bin/python -B src/stats/order8_fit.py --t117-cache <explore-t117-cache/run2> --out-dir <書き出す先>")
    a("```")
    a("- Python %s。" % run["python"])
    for k in sorted(run["code"]):
        a("- %s：sha256 %s" % (k, run["code"][k]))
    a("")
    a("## 引用")
    a(ei.CITATION_EN)
    a("")
    a(ei.CITATION_JA)
    out = "\n".join(L) + "\n"
    if "**" in out or "%%" in out:
        raise Order8Error("要約の書式に誤りがある")
    return out.encode("utf-8")


def write_outputs(out_dir, files):
    if sorted(files) != sorted(OUT_NAMES):
        raise Order8Error("出力の名前が決めた一覧と違う")
    os.makedirs(out_dir, exist_ok=True)
    for name in OUT_NAMES:
        if os.path.lexists(os.path.join(out_dir, name)):
            raise Order8Error("書き出す先に同じ名前のファイル（%s）がある。上書きしない" % name)
    return {name: es.write_new(os.path.join(out_dir, name), files[name]) for name in OUT_NAMES}


def main(argv=None):
    p = argparse.ArgumentParser(description="T-143 順番7・順番8 と段4・N3・N4 の係数")
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
    except (Order8Error, ts.SelectError, tr.TierError, ch.ChainError, sea.SeaError, ed.DenomError, em.ModelError,
            es.SignalError, ei.ExploreError) as e:
        sys.stderr.write("止まった：%s\n" % e)
        return 1
    for name in OUT_NAMES:
        print("%s  %s" % (shas[name], name))
    log("終わり")
    return 0


if __name__ == "__main__":
    sys.exit(main())
