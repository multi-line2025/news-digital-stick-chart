#!/usr/bin/env python3
"""T-125：海域ごとの波の性状と、素朴な予測が見落とした島（手法を作る期間の記述）。

島の定義は変えない（C7、V = A、一度跳ねたタグの扱いあり、判定期間 28 日、倍率 2・4・8）。全部並べ、選ばない・勧めない。

1. 海域ごとの波の性状（記述。区画全体のデータを使う。予測に使う形にしたものは無い）
   海域の単位（流す前に書いた決め方）
   - 系統：テーマの名前の頭の部分（explore_islands.family）。一覧のタグが FAMILY_MIN 以上の頭はそのまま、ほかは「その他」。
   - 群れ：T-119 の lift10 の群れ（12か月の網、ラベル伝播）を、学習の期間の月（COMM_MONTHS）ごとに作り、タグごとに最も多く
     属した群れ（同数なら小さいラベル）に割り当てる。タグが COMM_MIN 未満の群れは「小さな群れ」にまとめる。
   性状（タグごとに作り、海域ごとに中央値などでまとめる）
   a 荒さ：月曜ごとの上がり log((c+V)/(B+V))（B・c は封印済みの関数で t-1 以前）の、中央値からの絶対偏差の中央値（MAD）。
     島の起きやすさ：倍率ごとの島の割合。
   b 季節風：2016〜2019年の週ごとの log(7日の平均 + V) から年ごとの平均を引き、年の中の週の形（4年の平均）で説明できる割合。
     年ごとの形の似かた：年どうしの相関の平均。
   c 偏西風：週ごとの水準の傾き（1年あたりの log の変化）。海域に共通の流れ：週ごとの変化と、同じ海域の自分以外の平均の変化の相関。
   d 嵐：月曜ごとの島の割合（倍率 2）が上位 STORM_TOP の週。海域どうしの、週ごとの島の割合の相関。
   e 海底の隆起：週ごとの水準の、前後 STEP_WEEKS 週の中央値の差の最大が log(2) 以上なら段あり。島は、判定期間のあと
     t+57〜t+180 の比率の平均が max(2B, V) 以下なら「戻った」、それより上なら「上がったまま」、t+180 が区画の外か使える日が
     BACK_MIN_DAYS 未満なら「分からない」。
   f 素朴な予測の係数の年ごとの変化：2 の年ごとの当てはめの係数。
2. 素朴な予測が見落とした島
   予言日の年 y（2017〜2020）ごとに、判定期間が y の始まりより前に終わる予言日の対象の行だけで素朴な予測（naive.py の特徴量、
   ロジスティック回帰、リッジ 1）を作り、年 y の予言日の行に確率を付ける。見落とした島（流す前に書いた基準）：
     M1：確率が、学習の行の島の割合より低いのに島になった。
     M2：確率が、その年の行の確率の下位25%（最近順位）以下なのに島になった。
     M3：確率が、学習の行の島の割合の半分より低いのに島になった。

出力：要約（テーマの名前を載せない）と集計の表。テーマの名前の入った表は名前を -private とし、先頭の行に公開しない印を付ける。

流し方（プロジェクトのルートで。TMPDIR は scratchpad の中に）
  .venv/bin/python -B src/stats/explore_sea.py --t117-cache <explore-t117-cache/run2> --out-dir <書き出す先>

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
import statistics
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import explore_diffusion2 as x2  # noqa: E402

ex = x2.ex
ed = x2.ed
eg = ed.eg
em = x2.em
es = x2.es
ei = x2.ei
naive = x2.naive
candidates = ei.candidates

LABEL = "explore-sea-t125-v2"   # v2：T-126 で要約の文と言い方の規則を手直し（表は同じ）
MULTIPLIERS = em.MULTIPLIERS
HORIZON = em.HORIZON
DAY = datetime.timedelta(days=1)

# ---------------------------------------------------------------------------
# 試す形（本番の前に書いた）
# ---------------------------------------------------------------------------
FAMILY_MIN = 20
COMM_MIN = 10
COMM_MONTHS = tuple(m for m in range(201604, 201813) if 1 <= m % 100 <= 12)      # 2016-04〜2018-12
SEASON_YEARS = (2016, 2017, 2018, 2019)
STORM_TOP = 0.10
STEP_WEEKS = 26
STEP_MIN_VALUES = 20
STEP_LOG = math.log(2.0)
BACK_FROM, BACK_TO = 57, 180
BACK_MIN_DAYS = 60
MISS_YEARS = (2017, 2018, 2019, 2020)
MISS_RULES = ("M1", "M2", "M3")
MISS_MAIN = "M1"
MAIN_M = 4
# 平易な説明の言い方の目安（海域どうしの三分位と、決まった値）
SIMILAR_HIGH, SIMILAR_LOW = 0.5, 0.3      # v1 の目安（v2 の1章では使わない。記録のため残す）
# T-126：季節の割合と年どうしの相関の偶然の水準（本番の前に書いた）。季節の無い系列を種類ごとに NULL_N 本、同じ season_stats に流す。
NULL_SEED = 126
NULL_N = 300
NULL_AR = 0.9
NULL_KINDS = ("iid", "ar0.9", "randomwalk")
NULL_Q = 0.90                             # 偶然の水準：種類ごとの90%点（最近順位）のうち最も大きいもの
TREND_UP, TREND_DOWN = 0.1, -0.1
FLOW_HIGH, FLOW_LOW = 0.3, 0.1
STEP_SHARE_HIGH = 0.3


class SeaError(Exception):
    pass


# ---------------------------------------------------------------------------
# 小道具
# ---------------------------------------------------------------------------

def median(xs):
    xs = [x for x in xs if x is not None]
    return statistics.median(xs) if xs else None


def mad(xs):
    xs = [x for x in xs if x is not None]
    if len(xs) < 2:
        return None
    m = statistics.median(xs)
    return statistics.median([abs(x - m) for x in xs])


def corr(a, b):
    pairs = [(x, y) for x, y in zip(a, b) if x is not None and y is not None]
    if len(pairs) < 3:
        return None
    mx = sum(x for x, _y in pairs) / len(pairs)
    my = sum(y for _x, y in pairs) / len(pairs)
    sxx = sum((x - mx) ** 2 for x, _y in pairs)
    syy = sum((y - my) ** 2 for _x, y in pairs)
    if sxx <= 0 or syy <= 0:
        return None
    return sum((x - mx) * (y - my) for x, y in pairs) / math.sqrt(sxx * syy)


def slope(xs, ys):
    pairs = [(x, y) for x, y in zip(xs, ys) if y is not None]
    if len(pairs) < 3:
        return None
    mx = sum(x for x, _y in pairs) / len(pairs)
    my = sum(y for _x, y in pairs) / len(pairs)
    sxx = sum((x - mx) ** 2 for x, _y in pairs)
    return sum((x - mx) * (y - my) for x, y in pairs) / sxx if sxx > 0 else None


def nearest_rank(sorted_xs, q):
    if not sorted_xs:
        return None
    k = max(1, math.ceil(len(sorted_xs) * q))
    return sorted_xs[k - 1]


def tercile_label(value, values, labels):
    """values の中で value がどの三分位か（labels は低い順の3つ）。"""
    vs = sorted(x for x in values if x is not None)
    if value is None or not vs:
        return None
    lo, hi = nearest_rank(vs, 1 / 3), nearest_rank(vs, 2 / 3)
    return labels[0] if value <= lo else (labels[2] if value > hi else labels[1])


# ---------------------------------------------------------------------------
# 海域
# ---------------------------------------------------------------------------

def family_seas(tags):
    counts = collections.Counter(ei.family(t) for t in tags)
    return [ei.family(t) if counts[ei.family(t)] >= FAMILY_MIN else "その他" for t in tags]


def community_seas(labels_by_month, n):
    """月ごとのラベル（各月の [タグ番号 → 群れのラベル]）から、タグごとに最も多く属した群れ（同数なら小さいラベル）を決め、
    COMM_MIN 未満の群れは「小さな群れ」にする。群れの名前は大きさの順（同じなら小さいラベル）に「群れ01」…。"""
    best = []
    for i in range(n):
        c = collections.Counter(lab[i] for lab in labels_by_month)
        best.append(min(c.items(), key=lambda x: (-x[1], x[0]))[0])
    size = collections.Counter(best)
    big = sorted((l for l, s in size.items() if s >= COMM_MIN), key=lambda l: (-size[l], l))
    name = {l: "群れ%02d" % (k + 1) for k, l in enumerate(big)}
    return [name.get(l, "小さな群れ") for l in best]


# ---------------------------------------------------------------------------
# 週ごとの水準
# ---------------------------------------------------------------------------

def week_starts():
    """区画の始まり（月曜）からの、7日がすべて区画の中にある週の月曜。"""
    out, d = [], ei.BLOCK_START
    while d + 6 * DAY <= ei.BLOCK_END:
        out.append(d)
        d += 7 * DAY
    return out


def weekly_levels(values, days, v, weeks):
    """週ごとの log(その週の欠けた日でない日の比率の平均 + V)。使える日が無い週は None。"""
    pos = {d: k for k, d in enumerate(days)}
    out = []
    for w in weeks:
        xs = [values[pos[w + k * DAY]] for k in range(7)]
        xs = [x for x in xs if x is not None]
        out.append(math.log(sum(xs) / len(xs) + v) if xs else None)
    return out


def week_of_year(d):
    return min((d.timetuple().tm_yday - 1) // 7, 51)


def season_stats(levels, weeks):
    """(季節で説明できる割合, 年どうしの相関の平均)。SEASON_YEARS の週だけを使う。"""
    by_year = {}
    for y, w in zip(levels, weeks):
        if w.year in SEASON_YEARS and y is not None:
            by_year.setdefault(w.year, {})[week_of_year(w)] = y
    if len(by_year) < 2:
        return None, None
    det = {}
    for yr, d in by_year.items():
        mu = sum(d.values()) / len(d)
        det[yr] = {k: x - mu for k, x in d.items()}
    prof = {}
    for d in det.values():
        for k, x in d.items():
            prof.setdefault(k, []).append(x)
    prof = {k: sum(xs) / len(xs) for k, xs in prof.items()}
    ss_tot = sum(x * x for d in det.values() for x in d.values())
    ss_res = sum((x - prof[k]) ** 2 for d in det.values() for k, x in d.items())
    strength = 1 - ss_res / ss_tot if ss_tot > 0 else None
    years = sorted(det)
    cs = []
    for a in range(len(years)):
        for b in range(a + 1, len(years)):
            ks = sorted(set(det[years[a]]) & set(det[years[b]]))
            c = corr([det[years[a]][k] for k in ks], [det[years[b]][k] for k in ks])
            if c is not None:
                cs.append(c)
    return strength, (sum(cs) / len(cs) if cs else None)


def trend_per_year(levels, weeks):
    return slope([(w - ei.BLOCK_START).days / 365.25 for w in weeks], levels)


def step_size(levels):
    """前後 STEP_WEEKS 週の中央値の差のうち絶対値の最大（符号つき）。決まらなければ None。"""
    best = None
    for k in range(STEP_WEEKS, len(levels) - STEP_WEEKS + 1):
        a = [x for x in levels[k - STEP_WEEKS:k] if x is not None]
        b = [x for x in levels[k:k + STEP_WEEKS] if x is not None]
        if len(a) < STEP_MIN_VALUES or len(b) < STEP_MIN_VALUES:
            continue
        d = statistics.median(b) - statistics.median(a)
        if best is None or abs(d) > abs(best):
            best = d
    return best


def common_flow(levels_by_tag, members):
    """海域のタグごとの、週ごとの変化と、同じ海域の自分以外の平均の変化の相関。{タグ番号: 相関}。"""
    diffs = {}
    for i in members:
        lv = levels_by_tag[i]
        diffs[i] = [None if (a is None or b is None) else b - a for a, b in zip(lv, lv[1:])]
    nw = len(next(iter(diffs.values()))) if diffs else 0
    sums = [0.0] * nw
    cnts = [0] * nw
    for d in diffs.values():
        for k, x in enumerate(d):
            if x is not None:
                sums[k] += x
                cnts[k] += 1
    out = {}
    for i, d in diffs.items():
        loo = []
        for k, x in enumerate(d):
            c = cnts[k] - (1 if x is not None else 0)
            s = sums[k] - (x if x is not None else 0.0)
            loo.append(s / c if c > 0 else None)
        out[i] = corr(d, loo)
    return out


# ---------------------------------------------------------------------------
# 島の後（跳ねて戻ったか）と跳ねの大きさ
# ---------------------------------------------------------------------------

def after_level(values, pos, t):
    """t+57〜t+180 の比率の平均。t+180 が区画の外か、使える日が BACK_MIN_DAYS 未満なら None。"""
    last = t + BACK_TO * DAY
    if last > ei.BLOCK_END:
        return None
    xs = [values[pos[t + k * DAY]] for k in range(BACK_FROM, BACK_TO + 1)]
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if len(xs) >= BACK_MIN_DAYS else None


def back_or_stay(after, b, v):
    if after is None:
        return "unknown"
    return "back" if after <= max(2 * b, float(v)) else "stay"


def jump_size(values, pos, t, b):
    """判定期間の最大の7日の平均 ÷ B（B = 0 なら None）。"""
    best = None
    for end in candidates.smoothing_window_ends(t, HORIZON):
        xs = [values[pos[end - k * DAY]] for k in range(7)]
        if any(x is None for x in xs):
            continue
        m = sum(xs) / 7
        best = m if best is None or m > best else best
    return (best / b) if (best is not None and b > 0) else None


# ---------------------------------------------------------------------------
# 年ごとの素朴な予測と見落とし
# ---------------------------------------------------------------------------

def yearly_naive(rows, keys, mondays, tags, v):
    """{(年, 倍率): {"coef", "base", "probs": {行: 確率}}}。学習：判定期間が年の始まりより前に終わる予言日、確かめ：年の予言日。"""
    out = {}
    for y in MISS_YEARS:
        start = datetime.date(y, 1, 1)
        tr = [k for k in keys if mondays[k[0]] + HORIZON * DAY < start]
        te = [k for k in keys if mondays[k[0]].year == y]
        for m in MULTIPLIERS:
            mi = MULTIPLIERS.index(m)
            trs = sorted(tr, key=lambda k: (mondays[k[0]], tags[k[1]]))
            X = [[x for x in naive.features_from_levels(rows[k][1], m, v)] for k in trs]
            cols = [array.array("d", (r[j] for r in X)) for j in range(len(naive.FEATURES))]
            yv = [1 if rows[k][0][mi] else 0 for k in trs]
            fit = em.fit_logistic_cols(cols, yv, em.FIXED_LAMBDA)
            tcols = [array.array("d", (naive.features_from_levels(rows[k][1], m, v)[j] for k in te))
                     for j in range(len(naive.FEATURES))]
            probs = em.predict_cols(tcols, fit["coef"])
            out[(y, m)] = {"coef": fit["coef"], "converged": fit["converged"], "base": sum(yv) / len(yv),
                           "n_train": len(trs), "probs": dict(zip(te, probs)), "train_last": max(
                               mondays[k[0]] for k in tr).isoformat()}
    return out


def missed_flags(model, rows, m):
    """年と倍率ごとの {行: (M1, M2, M3)}（島の行だけ）。"""
    mi = MULTIPLIERS.index(m)
    probs = model["probs"]
    srt = sorted(probs.values())
    q25 = nearest_rank(srt, 0.25)
    base = model["base"]
    out = {}
    for k, p in probs.items():
        if rows[k][0][mi]:
            out[k] = (p < base, p <= q25, p < base / 2)
    return out


# ---------------------------------------------------------------------------
# 本体
# ---------------------------------------------------------------------------

def run(root, t117_cache, out_dir, workers, log):
    ctx = ei.load_context(root)
    m117 = es.load_cache(t117_cache, ctx)
    tags, v = ctx["tags"], ctx["v"]
    n = len(tags)
    days = ctx["days"]
    mondays = ei.prediction_mondays()
    series = es.daily_series(m117)
    del m117["weekc"]
    results = ed.evaluate_variant(series, days, mondays, v, workers, log, "一覧")
    rows = ed.variant_rows(results, mondays, tags, v)
    rises = [[es.rise(c, b, v) if (b is not None and c is not None) else None
              for (_st, b, c, _m1, _m2, _js, _lv) in res] for res in results]
    del results
    log("対象の行 %d" % len(rows))
    # 群れ
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
    labels = {}
    with es._pool(workers, eg._init_graph, (t117_cache, small)) as pool:
        for g in pool.imap(eg._graph_task, list(COMM_MONTHS)):
            labels[g["mk"]] = g["lab"]["lift10"]
    log("群れを作った")
    seas = {"family": family_seas(tags), "community": community_seas([labels[m] for m in COMM_MONTHS], n)}
    files = describe_and_build(tags, series, days, mondays, rows, rises, seas, v, ctx, log)
    return write_outputs(out_dir, files)


def describe_and_build(tags, series, days, mondays, rows, rises, seas, v, ctx, log):
    n = len(tags)
    pos = {d: k for k, d in enumerate(days)}
    weeks = week_starts()
    levels = [weekly_levels(series[i], days, float(v), weeks) for i in range(n)]
    keys = sorted(rows)
    by_tag = collections.defaultdict(list)
    for k in keys:
        by_tag[k[1]].append(k)
    tag_info = []
    for i in range(n):
        st, sim = season_stats(levels[i], weeks)
        stp = step_size(levels[i])
        rates = {}
        for mi, m in enumerate(MULTIPLIERS):
            ks = by_tag.get(i, [])
            rates[m] = (sum(1 for k in ks if rows[k][0][mi]) / len(ks)) if ks else None
        tag_info.append({"rough": mad(rises[i]), "season": st, "similar": sim, "trend": trend_per_year(levels[i], weeks),
                         "step": stp, "has_step": (stp is not None and abs(stp) >= STEP_LOG), "rates": rates,
                         "targets": len(by_tag.get(i, []))})
    for kind in ("family", "community"):
        groups = collections.defaultdict(list)
        for i, s in enumerate(seas[kind]):
            groups[s].append(i)
        for s, members in groups.items():
            flow = common_flow(levels, members) if len(members) > 1 else {i: None for i in members}
            for i in members:
                tag_info[i]["flow_" + kind] = flow[i]
    log("タグごとの性状を作った")
    # 嵐
    storm = storms(rows, keys, mondays, seas)
    # 島の後と跳ねの大きさ
    island_extra = {}
    for k in keys:
        js, lv = rows[k]
        if not any(js):
            continue
        t = mondays[k[0]]
        aft = after_level(series[k[1]], pos, t)
        island_extra[k] = {"after": back_or_stay(aft, lv["B"], v), "jump": jump_size(series[k[1]], pos, t, lv["B"])}
    # 年ごとの素朴な予測
    models = yearly_naive(rows, keys, mondays, tags, v)
    missed = {(y, m): missed_flags(models[(y, m)], rows, m) for y in MISS_YEARS for m in MULTIPLIERS}
    log("見落としを数えた")
    return build_outputs(tags, mondays, rows, keys, seas, tag_info, storm, island_extra, models, missed, ctx)


def storms(rows, keys, mondays, seas):
    """月曜ごとの島の割合（倍率 2）と嵐の週、海域ごとの週ごとの割合、海域どうしの相関（系統）。"""
    tot = collections.Counter()
    isl = collections.Counter()
    sea_tot = {kind: collections.defaultdict(collections.Counter) for kind in seas}
    sea_isl = {kind: collections.defaultdict(collections.Counter) for kind in seas}
    for k in keys:
        js = rows[k][0]
        tot[k[0]] += 1
        isl[k[0]] += 1 if js[0] else 0
        for kind in seas:
            s = seas[kind][k[1]]
            sea_tot[kind][s][k[0]] += 1
            sea_isl[kind][s][k[0]] += 1 if js[0] else 0
    rate = {w: isl[w] / tot[w] for w in tot}
    cut = nearest_rank(sorted(rate.values()), 1 - STORM_TOP)
    storm_weeks = sorted(w for w, r in rate.items() if r >= cut)
    weeks = sorted(rate)
    fam_series = {s: [sea_isl["family"][s][w] / sea_tot["family"][s][w] if sea_tot["family"][s][w] else None
                      for w in weeks] for s in sea_tot["family"]}
    fs = sorted(fam_series)
    cs = [corr(fam_series[a], fam_series[b]) for i, a in enumerate(fs) for b in fs[i + 1:]]
    cs = [c for c in cs if c is not None]
    return {"rate": rate, "cut": cut, "weeks": storm_weeks, "family_corr_median": median(cs),
            "sea_tot": sea_tot, "sea_isl": sea_isl}


# ---------------------------------------------------------------------------
# 出力
# ---------------------------------------------------------------------------

OUT_NAMES = ("seas.tsv", "storms.tsv", "naive_coefs.tsv", "missed.tsv", "tags-private.tsv", "missed-private.tsv",
             "run.json", "summary.md")
PRIVATE_HEADER = "# 公開しない（private）：テーマの名前を含む。要約と公開物には載せない。\n"


def f4(x):
    return "-" if x is None else "%.4f" % x


def sea_rows(kind, seas, tag_info, rows, keys, island_extra, missed):
    groups = collections.defaultdict(list)
    for i, s in enumerate(seas[kind]):
        groups[s].append(i)
    out = []
    for s in sorted(groups, key=lambda s: (-len(groups[s]), s)):
        members = groups[s]
        mem = set(members)
        ks = [k for k in keys if k[1] in mem]
        d = {"sea": s, "tags": len(members), "targets": len(ks),
             "rough": median(tag_info[i]["rough"] for i in members),
             "season": median(tag_info[i]["season"] for i in members),
             "similar": median(tag_info[i]["similar"] for i in members),
             "trend": median(tag_info[i]["trend"] for i in members),
             "flow": median(tag_info[i]["flow_" + kind] for i in members),
             "step_share": sum(1 for i in members if tag_info[i]["has_step"]) / len(members)}
        for mi, m in enumerate(MULTIPLIERS):
            isl = [k for k in ks if rows[k][0][mi]]
            d["islands_%d" % m] = len(isl)
            d["rate_%d" % m] = len(isl) / len(ks) if ks else None
            c = collections.Counter(island_extra[k]["after"] for k in isl)
            d["back_%d" % m], d["stay_%d" % m], d["unknown_%d" % m] = c["back"], c["stay"], c["unknown"]
            mk = [k for (y, mm), fl in missed.items() if mm == m for k, f in fl.items()
                  if f[MISS_RULES.index(MISS_MAIN)] and k[1] in mem]
            d["missed_%d" % m] = len(mk)
            d["missed_years_islands_%d" % m] = sum(1 for (y, mm), fl in missed.items() if mm == m
                                                   for k in fl if k[1] in mem)
        out.append(d)
    return out


SEA_COLS = ("sea", "tags", "targets", "rough", "season", "similar", "trend", "flow", "step_share") + tuple(
    "%s_%d" % (c, m) for m in MULTIPLIERS for c in ("islands", "rate", "back", "stay", "unknown", "missed",
                                                    "missed_years_islands"))


def null_levels(weeks):
    """季節の無い系列（独立な乱数・自己相関 NULL_AR・ランダムウォーク）を種類ごとに NULL_N 本作り、season_stats の
    (季節の割合, 年どうしの相関) を返す。戻り値：{"kinds": {種類: {"season": [...], "similar": [...]}}, "season": 水準, "similar": 水準}。"""
    import random
    rng = random.Random(NULL_SEED)
    kinds = {}
    for kind in NULL_KINDS:
        se, si = [], []
        for _ in range(NULL_N):
            x, ys = 0.0, []
            for _w in weeks:
                e = rng.gauss(0.0, 1.0)
                if kind == "iid":
                    x = e
                elif kind == "ar0.9":
                    x = NULL_AR * x + e
                else:
                    x = x + e
                ys.append(x)
            a, b = season_stats(ys, weeks)
            se.append(a)
            si.append(b)
        kinds[kind] = {"season": sorted(v for v in se if v is not None), "similar": sorted(v for v in si if v is not None)}
    lev = {stat: max(nearest_rank(kinds[k][stat], NULL_Q) for k in NULL_KINDS) for stat in ("season", "similar")}
    return dict(lev, kinds=kinds)


def plain_sentence(d, all_rows, null):
    """海域の平易な説明。荒さ・島の起きやすさは海域どうしの三分位、季節風と年ごとの形は偶然の水準との比べ。"""
    rough = tercile_label(d["rough"], [r["rough"] for r in all_rows], ("穏やか", "ふつう", "荒い"))
    rate = tercile_label(d["rate_%d" % MAIN_M], [r["rate_%d" % MAIN_M] for r in all_rows],
                         ("起きにくい", "ふつう", "起きやすい"))
    parts = ["ふだんの波の上下は%s" % {"穏やか": "小さく穏やか", "ふつう": "ほかの海と同じくらい", "荒い": "大きく荒い"}.get(rough, "分からない")]
    if d["season"] is None:
        season = "分からない"
    elif d["season"] > null["season"]:
        season = "偶然の水準（%.3f）を超えていて、ありそう" % null["season"]
    else:
        season = "見分けられない（季節の無い系列でも出る大きさ）"
    if d["similar"] is None:
        shape = "年ごとの形の似かたは分からない"
    elif d["similar"] > null["similar"]:
        shape = "年ごとの形は偶然の水準（%.3f）より似ている" % null["similar"]
    else:
        shape = "年ごとの形の似かたは見分けられない"
    parts.append("季節風（毎年同じ時期に来る波）は%s。%s" % (season, shape))
    if d["trend"] is not None:
        tr = "上がり気味" if d["trend"] >= TREND_UP else ("下がり気味" if d["trend"] <= TREND_DOWN else "ほぼ横ばい")
    else:
        tr = "分からない"
    parts.append("長い期間の流れ（偏西風）は%s" % tr)
    if d["flow"] is not None:
        fl = "海の中のテーマが一緒に動きやすい" if d["flow"] >= FLOW_HIGH else (
            "海の中のテーマはばらばらに動く" if d["flow"] < FLOW_LOW else "海の中のテーマはある程度一緒に動く")
        parts.append(fl)
    if d["step_share"] >= STEP_SHARE_HIGH:
        parts.append("水準が段のように変わったテーマが多い（%.0f%%）" % (100 * d["step_share"]))
    isl = d["islands_%d" % MAIN_M]
    st = d["stay_%d" % MAIN_M]
    bk = d["back_%d" % MAIN_M]
    parts.append("島（倍率 %d）は%s（%d 件）" % (MAIN_M, rate or "分からない", isl))
    if bk + st:
        parts.append("島のうち、跳ねたあと元に戻ったのは %d 件、上がったままだったのは %d 件" % (bk, st))
    return "。".join(parts) + "。"


def build_outputs(tags, mondays, rows, keys, seas, tag_info, storm, island_extra, models, missed, ctx):
    fam = sea_rows("family", seas, tag_info, rows, keys, island_extra, missed)
    com = sea_rows("community", seas, tag_info, rows, keys, island_extra, missed)
    seas_tsv = ei.tsv(("kind",) + SEA_COLS, [(kind,) + tuple(
        f4(d[c]) if isinstance(d[c], float) else d[c] for c in SEA_COLS) for kind, ds in (("family", fam),
                                                                                          ("community", com))
        for d in ds])
    storms_tsv = ei.tsv(("monday", "targets", "islands_m2", "rate_m2", "storm"),
                        [(mondays[w].isoformat(), sum(storm["sea_tot"]["family"][s][w] for s in storm["sea_tot"]["family"]),
                          sum(storm["sea_isl"]["family"][s][w] for s in storm["sea_isl"]["family"]), f4(storm["rate"][w]),
                          "yes" if w in set(storm["weeks"]) else "") for w in sorted(storm["rate"])])
    coef_rows = []
    for (y, m), md_ in sorted(models.items()):
        for f, b in zip(naive.FEATURES, md_["coef"]):
            coef_rows.append((y, m, md_["train_last"], md_["n_train"], f4(md_["base"]), f, f4(b), md_["converged"]))
    coefs_tsv = ei.tsv(("year", "multiplier", "train_last_monday", "train_rows", "train_island_rate", "feature",
                        "coef", "converged"), coef_rows)
    # 見落としの分布
    storm_set = set(storm["weeks"])
    rough_vals = [t["rough"] for t in tag_info]
    season_vals = [t["season"] for t in tag_info]
    mrows = []
    summary_missed = {}
    for m in MULTIPLIERS:
        for ri, rule in enumerate(MISS_RULES):
            for y in MISS_YEARS:
                fl = missed[(y, m)]
                isl = list(fl)
                mk = [k for k in isl if fl[k][ri]]
                mrows.append((m, rule, y, "all", "all", len(isl), len(mk)))
                groups = {
                    "family": lambda k: seas["family"][k[1]],
                    "community": lambda k: seas["community"][k[1]],
                    "rough": lambda k: tercile_label(tag_info[k[1]]["rough"], rough_vals, ("穏やか", "ふつう", "荒い")) or "-",
                    "season": lambda k: tercile_label(tag_info[k[1]]["season"], season_vals, ("弱い", "ふつう", "強い")) or "-",
                    "after": lambda k: island_extra[k]["after"],
                    "storm": lambda k: "storm" if k[0] in storm_set else "calm",
                    "step": lambda k: "step" if tag_info[k[1]]["has_step"] else "no_step",
                }
                for gname, gf in groups.items():
                    ci = collections.Counter(gf(k) for k in isl)
                    cm = collections.Counter(gf(k) for k in mk)
                    for val in sorted(ci, key=str):
                        mrows.append((m, rule, y, gname, val, ci[val], cm[val]))
            summary_missed[(m, rule)] = (sum(len(missed[(y, m)]) for y in MISS_YEARS),
                                         sum(1 for y in MISS_YEARS for f in missed[(y, m)].values() if f[ri]))
    missed_tsv = ei.tsv(("multiplier", "rule", "year", "group", "value", "islands", "missed"), mrows)
    # 名前の入った表（公開しない）
    tp = [(tags[i], seas["family"][i], seas["community"][i], tag_info[i]["targets"], f4(tag_info[i]["rough"]),
           f4(tag_info[i]["season"]), f4(tag_info[i]["similar"]), f4(tag_info[i]["trend"]),
           f4(tag_info[i]["flow_family"]), f4(tag_info[i]["step"]), tag_info[i]["has_step"],
           *[f4(tag_info[i]["rates"][m]) for m in MULTIPLIERS]) for i in range(len(tags))]
    tags_private = PRIVATE_HEADER.encode("utf-8") + ei.tsv(
        ("theme", "family_sea", "community_sea", "targets", "rough", "season", "similar", "trend", "flow_family", "step",
         "has_step") + tuple("island_rate_m%d" % m for m in MULTIPLIERS), tp)
    mp = []
    for (y, m), fl in sorted(missed.items()):
        probs = models[(y, m)]["probs"]
        for k in sorted(fl, key=lambda k: (k[0], tags[k[1]])):
            if not any(fl[k]):
                continue
            mp.append((m, y, tags[k[1]], mondays[k[0]].isoformat(), "%.6f" % probs[k], f4(island_extra[k]["jump"]),
                       island_extra[k]["after"], seas["family"][k[1]], seas["community"][k[1]],
                       *["yes" if x else "" for x in fl[k]]))
    missed_private = PRIVATE_HEADER.encode("utf-8") + ei.tsv(
        ("multiplier", "year", "theme", "monday", "prob", "jump_size", "after", "family_sea", "community_sea")
        + MISS_RULES, mp)
    code = dict(ei._LOADED_SHA, **x2.own_code_shas())
    with open(os.path.abspath(__file__), "rb") as f:
        code["src/stats/explore_sea.py"] = hashlib.sha256(f.read()).hexdigest()
    run = {"label": LABEL, "code": code, "python": sys.version.split()[0], "refs": ctx["refs"],
           "v": "%d/%d" % (ctx["v"].numerator, ctx["v"].denominator), "rows": len(keys),
           "storm_cut_rate_m2": storm["cut"], "storm_weeks": len(storm["weeks"]),
           "family_seas": len(fam), "community_seas": len(com),
           "options": {"family_min": FAMILY_MIN, "comm_min": COMM_MIN, "comm_months": COMM_MONTHS,
                       "season_years": SEASON_YEARS, "storm_top": STORM_TOP, "step_weeks": STEP_WEEKS,
                       "step_min_values": STEP_MIN_VALUES, "step_log": STEP_LOG, "back_from": BACK_FROM,
                       "back_to": BACK_TO, "back_min_days": BACK_MIN_DAYS, "miss_years": MISS_YEARS,
                       "miss_rules": MISS_RULES, "main_multiplier": MAIN_M},
           "citation": [ei.CITATION_EN, ei.CITATION_JA]}
    files = {"seas.tsv": seas_tsv, "storms.tsv": storms_tsv, "naive_coefs.tsv": coefs_tsv, "missed.tsv": missed_tsv,
             "tags-private.tsv": tags_private, "missed-private.tsv": missed_private,
             "run.json": (json.dumps(run, ensure_ascii=False, sort_keys=True, indent=1) + "\n").encode("utf-8")}
    null = null_levels(week_starts())
    run["null_levels"] = {"season": null["season"], "similar": null["similar"], "seed": NULL_SEED, "n": NULL_N,
                          "kinds": {k: {stat: [median(v[stat]), nearest_rank(v[stat], NULL_Q)] for stat in ("season", "similar")}
                                    for k, v in null["kinds"].items()}}
    files["run.json"] = (json.dumps(run, ensure_ascii=False, sort_keys=True, indent=1) + "\n").encode("utf-8")
    files["summary.md"] = summary_md(run, fam, com, storm, mondays, models, missed, summary_missed, mrows, tags, null)
    for name, data in files.items():
        ei.check_public(name, data)
    return files


def write_outputs(out_dir, files):
    if sorted(files) != sorted(OUT_NAMES):
        raise SeaError("出力の名前が決めた一覧と違う")
    os.makedirs(out_dir, exist_ok=True)
    for name in OUT_NAMES:
        if os.path.lexists(os.path.join(out_dir, name)):
            raise SeaError("書き出す先に同じ名前のファイル（%s）がある。上書きしない" % name)
    return {name: es.write_new(os.path.join(out_dir, name), files[name]) for name in OUT_NAMES}


def null_text(null, stat):
    names = {"iid": "独立な乱数", "ar0.9": "引き継ぐ系列", "randomwalk": "ランダムウォーク"}
    return "、".join("%sで中央値 %.3f・90%%点 %.3f" % (names[k], median(null["kinds"][k][stat]),
                                                    nearest_rank(null["kinds"][k][stat], NULL_Q)) for k in NULL_KINDS)


def summary_md(run, fam, com, storm, mondays, models, missed, summary_missed, mrows, tags, null=None):
    null = null if null is not None else null_levels(week_starts())
    L = []
    a = L.append
    md = ei.md_table
    a("# 海域ごとの波の性状と、素朴な予測が見落とした島（T-125、手法を作る期間）")
    a("")
    same = sum(1 for d in fam if d["sea"] in set(tags))
    a("この文書は `src/stats/explore_sea.py` が出力したもので、手で書き足していない。島の定義は変えていない。テーマの名前は載せていない"
      "（海域として載せた系統の名前を除く。系統の名前 %d 個のうち %d 個は、一覧に同じ名前のテーマがある）。" % (len(fam), same))
    a("この版（v2）の注記：v1 の季節風の言い方は海域どうしの三分位で、偶然の水準を考えていなかったため、偶然の水準と比べる形に替えた"
      "（表の sha256 は v1 と同じ）。"
      "全部並べ、選ばない・勧めない。")
    a("")
    a("## 1. 海域ごとのやさしい説明")
    a("")
    a("ここでの「海域」は、テーマの名前の頭の部分（系統）でまとめたもの。言葉の意味：「荒さ」はふだんの報道量の上下のふれ幅、"
      "「季節風」は毎年同じ時期に来る波、「偏西風」は何年もかけた上り下り、「嵐」は多くの海域が同じ週に一緒に荒れること、"
      "「海底の隆起」は報道量の水準が段のように変わること。荒さと島の起きやすさの目安は海域どうしの比べ（三分位）で、絶対の基準ではない。")
    a("")
    a("季節風について：季節の無い系列（独立な乱数、前の週の値の %.1f 倍を引き継ぐ系列、ランダムウォーク。各 %d 本、乱数の種 %d）を同じ計算に通すと、"
      "季節で説明できる割合は %s、年どうしの相関は %s になった。季節の割合が %.3f（種類ごとの90%%点のうち最も大きいもの）を超えない海域では、"
      "季節風は「見分けられない」と書く。年どうしの相関も同じく %.3f と比べる。" % (
          NULL_AR, NULL_N, NULL_SEED, null_text(null, "season"), null_text(null, "similar"), null["season"],
          null["similar"]))
    a("")
    for d in fam:
        a("- %s（テーマ %d）：%s" % (d["sea"], d["tags"], plain_sentence(d, fam, null)))
    a("")
    a("## 2. 素朴な予測が見落とした島（やさしい説明）")
    a("")
    for m in MULTIPLIERS:
        tot, mk = summary_missed[(m, MISS_MAIN)]
        bases = [models[(y, m)]["base"] for y in MISS_YEARS]
        a("- 倍率 %d：%d〜%d年の島 %d 件のうち、素朴な予測が平均より低い確率を付けた（約 %.1f〜%.1f%% 未満。年ごとの学習の行の島の割合）"
          "のに島になったのは %d 件（%.1f%%）。" % (m, MISS_YEARS[0], MISS_YEARS[-1], tot, 100 * min(bases), 100 * max(bases), mk,
                                               100 * mk / tot if tot else 0))
    def top(group, m, k=3):
        c = collections.Counter()
        ci = collections.Counter()
        for (mm, rule, y, g, val, isl, ms) in mrows:
            if mm == m and rule == MISS_MAIN and g == group:
                c[val] += ms
                ci[val] += isl
        return [(val, c[val], ci[val]) for val in sorted(c, key=lambda v_: (-c[v_], str(v_)))[:k]], c, ci
    tf, _c, _ci = top("family", MAIN_M)
    a("- 倍率 %d で見落とした島が多い海域：%s。" % (MAIN_M, "、".join("%s %d 件（その海域の島の %.0f%%）" % (
        val, ms, 100 * ms / isl if isl else 0) for val, ms, isl in tf)))
    by_year = {}
    for (mm, rule, y, g, val, isl, ms) in mrows:
        if mm == MAIN_M and rule == MISS_MAIN and g == "all":
            by_year[y] = (isl, ms)
    a("- 年ごと（倍率 %d）：%s。" % (MAIN_M, "、".join("%d年 %d / %d 件" % (y, by_year[y][1], by_year[y][0]) for y in MISS_YEARS)))
    _t, cs, cis = top("storm", MAIN_M)
    _t, ca, cia = top("after", MAIN_M)
    a("- 嵐の週（島の割合が上位 %d%% の週）の見落とし：%d 件（その週の島の %.0f%%）、静かな週：%d 件（%.0f%%）。" % (
        int(100 * STORM_TOP), cs["storm"], 100 * cs["storm"] / cis["storm"] if cis["storm"] else 0, cs["calm"],
        100 * cs["calm"] / cis["calm"] if cis["calm"] else 0))
    a("- 見落とした島のうち、跳ねたあと元に戻ったもの %d 件、上がったままのもの %d 件、区画の外にかかって分からないもの %d 件。" % (
        ca["back"], ca["stay"], ca["unknown"]))
    a("- 見落としの基準はほかに2つ（M2：その年の確率の下位25%、M3：学習の行の島の割合の半分より低い）を並べた（4章）。")
    a("")
    a("## 3. 海域の表（系統）")
    a("")
    hdr = ["海域", "テーマ", "対象の行", "荒さ（MAD）", "季節で説明できる割合", "年どうしの相関", "傾き（log/年）", "共通の流れ", "段の割合",
           "島（倍率 %d）" % MAIN_M, "島の割合", "戻った", "上がったまま", "分からない", "見落とし（%s）" % MISS_MAIN]
    a(md(hdr, [(d["sea"], d["tags"], d["targets"], f4(d["rough"]), f4(d["season"]), f4(d["similar"]), f4(d["trend"]),
                f4(d["flow"]), "%.2f" % d["step_share"], d["islands_%d" % MAIN_M], f4(d["rate_%d" % MAIN_M]),
                d["back_%d" % MAIN_M], d["stay_%d" % MAIN_M], d["unknown_%d" % MAIN_M], d["missed_%d" % MAIN_M])
               for d in fam]))
    a("")
    a("群れ（T-119 の lift10 の群れ。タグを、学習の期間の月で最も多く属した群れに割り当てた）：群れの海域 %d 個（タグ %d 以上）と「小さな群れ」。"
      "大きい順の上位 15：" % (len([d for d in com if d["sea"] != "小さな群れ"]), COMM_MIN))
    a("")
    a(md(hdr, [(d["sea"], d["tags"], d["targets"], f4(d["rough"]), f4(d["season"]), f4(d["similar"]), f4(d["trend"]),
                f4(d["flow"]), "%.2f" % d["step_share"], d["islands_%d" % MAIN_M], f4(d["rate_%d" % MAIN_M]),
                d["back_%d" % MAIN_M], d["stay_%d" % MAIN_M], d["unknown_%d" % MAIN_M], d["missed_%d" % MAIN_M])
               for d in com[:15]]))
    a("")
    a("## 4. 見落とした島の数（全体）")
    a("")
    body = []
    for m in MULTIPLIERS:
        for rule in MISS_RULES:
            tot, mk = summary_missed[(m, rule)]
            body.append((m, rule, tot, mk, "%.1f" % (100 * mk / tot if tot else 0)))
    a(md(["倍率", "基準", "島（%d〜%d年）" % (MISS_YEARS[0], MISS_YEARS[-1]), "見落とし", "割合（%）"], body))
    a("")
    a("海域・荒さ・季節風・跳ねたあと・嵐の週かどうか・段の有無・年ごとの分布は missed.tsv。")
    a("")
    a("## 5. 嵐の週")
    a("- 島の割合（倍率 2）が上位 %d%% の週を嵐の週とした（%d 週、割合 %.4f 以上）。系統の海域どうしの、週ごとの島の割合の相関の中央値は %s。"
      % (int(100 * STORM_TOP), run["storm_weeks"], run["storm_cut_rate_m2"], f4(storm["family_corr_median"])))
    a("- 嵐の週：%s。" % "、".join(mondays[w].isoformat() for w in storm["weeks"]))
    a("")
    a("## 6. 素朴な予測の係数の年ごとの変化（倍率 %d）" % MAIN_M)
    a("")
    a(md(["年", "学習の最後の予言日", "学習の行", "学習の島の割合"] + list(naive.FEATURES),
         [(y, models[(y, MAIN_M)]["train_last"], models[(y, MAIN_M)]["n_train"], f4(models[(y, MAIN_M)]["base"]),
           *[f4(b) for b in models[(y, MAIN_M)]["coef"]]) for y in MISS_YEARS]))
    a("")
    a("## 7. 作り方")
    a("- 海域：系統は名前の頭の部分（テーマ %d 以上の頭、ほかは「その他」）。群れは %d-%02d〜%d-%02d の月ごとの lift10 の群れのうち、"
      "最も多く属した群れ（同数なら小さいラベル）。" % (FAMILY_MIN, COMM_MONTHS[0] // 100, COMM_MONTHS[0] % 100,
                                                    COMM_MONTHS[-1] // 100, COMM_MONTHS[-1] % 100))
    a("- 荒さ：月曜ごとの上がり log((c+V)/(B+V)) の、中央値からの絶対偏差の中央値。季節風：%s年の週ごとの log(週の平均 + V) から年の平均を引き、"
      "年の中の週の形（年の平均）で説明できる割合と、年どうしの相関の平均（年は4つしかないので、形は当てはまりすぎる向きに出る）。"
      % "・".join(str(y) for y in SEASON_YEARS))
    a("- 偏西風：週ごとの水準の傾き（1年あたり）。共通の流れ：週ごとの変化と、同じ海域の自分以外の平均の変化の相関。")
    a("- 段：前後 %d 週の中央値の差の最大が log(2) 以上（%d 週以上の値があるところだけ）。跳ねたあと：t+%d〜t+%d の比率の平均が max(2B, V) 以下なら"
      "戻った、上なら上がったまま、t+%d が区画の外か使える日が %d 未満なら分からない。" % (
          STEP_WEEKS, STEP_MIN_VALUES, BACK_FROM, BACK_TO, BACK_TO, BACK_MIN_DAYS))
    a("- 素朴な予測：予言日の年 y ごとに、判定期間が y の始まりより前に終わる予言日の対象の行で作り直し、年 y の行に確率を付けた（予言日より前の"
      "データだけで作った確率）。見落とし：M1 確率 < 学習の行の島の割合、M2 確率 ≤ その年の確率の下位25%、M3 確率 < 学習の行の島の割合の半分。")
    a("- 1章の言い方の目安：荒さ・島の起きやすさは海域どうしの三分位。季節風と年ごとの形は、海域の中央値を偶然の水準（季節の無い系列の"
      "種類ごとの90%%点のうち最も大きいもの。季節の割合 %.3f、年どうしの相関 %.3f）と比べ、超えなければ「見分けられない」。季節の無い系列："
      "季節の割合は %s、年どうしの相関は %s（各 %d 本、乱数の種 %d）。傾き %+.1f 以上で上がり気味、%+.1f 以下で下がり気味。共通の流れ %.1f 以上で"
      "一緒に動きやすい、%.1f 未満でばらばら。段のあるテーマが %.0f%% 以上で段の文を足す。" % (
          null["season"], null["similar"], null_text(null, "season"), null_text(null, "similar"), NULL_N, NULL_SEED,
          TREND_UP, TREND_DOWN, FLOW_HIGH, FLOW_LOW, 100 * STEP_SHARE_HIGH))
    a("")
    a("## 8. 限界")
    a("- 性状の記述は、区画全体のデータ（判定期間より後の日も含む）を使った理解のための記述で、予言の入力にはしていない。予言の時点で"
      "作れる形にしたのは、2 の素朴な予測の確率だけ。")
    a("- 一覧と V の先読み：タグの一覧と V は、手法を作る期間の区画全体のデータで決まった（seq 17）。")
    a("- 除外の規則の漏れ：民族・人物の姓・宗教・犯罪・紛争・政治に当たる名前のテーマが一覧に残っている（オーナーの決定 2026-10-16、(a)）。"
      "見落とした島の一覧（missed-private.tsv）とタグの表（tags-private.tsv）には名前が入るので、公開しない。")
    a("- WB のテーマの段のような上昇（T-116 の要約 6章）は、段の割合と見落としに入りうる。")
    a("- 見落としの数は、同じ出来事で多くのタグが一緒に跳ね、毎週の判定期間が重なるので、独立な件数ではない。")
    a("- 群れの海域：群れが同じかどうかを、月ごとのラベル（群れの中の最小の番号）で決めている。月をまたいで群れの中身が変わっても、"
      "最小の番号が同じなら同じ群れと数えるので、「最も多く属した群れ」は近似的な対応である。")
    a("- 季節風の偶然の水準は、1本の系列の分布（90%点）と、海域の中のタグの値の中央値を比べたもの。中央値は1本の値よりばらつきが小さいので、"
      "この比べ方は「見分けられない」と書きやすい向きにある。")
    a("")
    a("## 9. 再計算")
    a("```")
    a(".venv/bin/python -B src/stats/explore_sea.py --t117-cache <explore-t117-cache/run2> --out-dir <書き出す先>")
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
        raise SeaError("要約に太字の印がある")
    sea_names = {d["sea"] for d in fam} | {d["sea"] for d in com}
    if names_in_text(out, tags, sea_names):
        raise SeaError("要約にテーマの名前がある")
    return out.encode("utf-8")


def names_in_text(text, tags, allowed):
    """text の中の識別子の形の語のうち、タグの名前に当たるもの（海域の名前として載せたものを除く）。"""
    import re
    toks = set(re.findall(r"[A-Z][A-Z0-9_]+", text))
    return sorted((toks & set(tags)) - set(allowed))


def main(argv=None):
    p = argparse.ArgumentParser(description="T-125 海域ごとの波の性状と見落とした島")
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
    except (SeaError, x2.Diffusion2Error, ex.DiffusionError, ed.DenomError, em.ModelError, es.SignalError,
            ei.ExploreError) as e:
        sys.stderr.write("止まった：%s\n" % e)
        return 1
    for name in OUT_NAMES:
        print("%s  %s" % (shas[name], name))
    log("終わり")
    return 0


if __name__ == "__main__":
    sys.exit(main())
