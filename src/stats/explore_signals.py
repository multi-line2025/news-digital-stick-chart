#!/usr/bin/env python3
"""T-117：三つの信号（method.md 2.1 隣の波・2.2 先に届く波・2.3 空白の形）の探索。

手法を作る期間の区画（2015-03-02〜2020-12-14）の日の集計だけを使い、T-115 と同じ予言日（232回）・対象
（一度跳ねたタグの扱いあり）・判定で、信号が島に先行するかを、素朴な予測の特徴量だけのロジスティック回帰と、
信号を足したものとで比べる（method.md 3章）。作り方の選択肢（method.md 8章の未決事項1〜3）は、下の定数に
データを集計する前に書いたもので、結果を並べるだけで決めない（決定はオーナー）。モデルの形・係数は確定しない。

二段で流す
  phase1：日の集計を読み、キャッシュ（Git の外）に、日ごとのテーマの数（C7 の分子・V1 の文書の数）、
          月ごとの共起の網（P1。一覧のタグどうし）、週ごとの国別の数（C・NC）を書く。
  phase2：キャッシュを照らして読み、予言日ごとの状態・判定・素朴な予測の特徴量・信号を作り、モデルを比べる。

予言日 t の時点で入手できたデータだけを使うこと（t-1 以前）
- 日の比率：explore_islands.ReadGuard で、入力の計算中は t-399〜t-1、判定中は t+1〜t+28 の外を読むと止まる。
- 共起の網：月ごとの網を、t を含む月（四半期の更新なら、t を含む四半期の最初の月）より前の月だけで足す。
  使うたびに「網の最後の日 < t」を確かめ、外れれば止まる。
- 国別の週の数：t の前の週（t-7〜t-1）と、その前の52週だけを読む。使うたびに「週の最後の日 < t」を確かめる。
- 国の単位（上位30か国）は、最初の予言日より前（2015-03-02〜2016-04-10）の NC だけで決める。
- 区画の外（2020-12-15 以降）の日の集計は開かない（explore_islands.day_rows_from_manifest と read_day の確かめ）。

使う関数（変えない。ファイルを1回だけ読み、sha256 を照らしてから compile する。explore_islands と同じ形）
- explore_islands.py（T-115/T-116）：load_context・ReadGuard・read_nofollow など。candidates・scoring・counting・
  periods もそこで照らしたものを使う。
- naive.py：raw_levels・features_from_levels・fit_rows・predict。naive.py は封印の記録にまだ無い（順番6〜8の予定）。
  Git の履歴の版（82e0424 から変わっていない）の sha256 を NAIVE_SHA256 に固定して照らす。

流し方（プロジェクトのルートで。TMPDIR は scratchpad の中に）
  .venv/bin/python -B src/stats/explore_signals.py phase1 --store <日の集計> --cache-dir <新しいフォルダ>
  .venv/bin/python -B src/stats/explore_signals.py phase2 --cache-dir <同じフォルダ> --out-dir <書き出す先>

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
import multiprocessing
import operator
import os
import random
import sys
import time
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import explore_islands as ei  # noqa: E402

candidates = ei.candidates
scoring = ei.scoring
counting = ei.counting
periods = ei.periods

NAIVE_SHA256 = "859947f442b6843a332922d5ee1159403e36e38394bfa99f64594b229c35373a"
naive = ei._load_verified("naive", "src/stats/naive.py", NAIVE_SHA256,
                          deps=(("candidates", candidates), ("periods", periods), ("scoring", scoring)))

LABEL = "explore-signals-t117-v2"
PHASE1_LABEL = "explore-signals-phase1-v1"

ONE_DAY = datetime.timedelta(days=1)
DAYS = datetime.timedelta
OFFICIAL_CID = "C7"

# ---------------------------------------------------------------------------
# 作り方の選択肢（データを集計する前に書いた。決めない）
# ---------------------------------------------------------------------------

HORIZON = 28
MULTIPLIERS = (2, 4, 8)                  # 比べる組み合わせ：倍率 2・4・8 × 判定期間 28
NAIVE_LOOKBACK = 399                     # naive.naive_lookback_days()

# 未決事項1：網を作る期間の長さ（月）と更新の頻度
NETWORKS = (
    ("w12q", 12, "Q"),                   # 直前の12か月、四半期ごとに更新
    ("w12m", 12, "M"),                   # 直前の12か月、月ごとに更新
    ("w3m", 3, "M"),                     # 直前の3か月、月ごとに更新
)
# 未決事項2：「隣」の範囲と重み（1歩だけ。2歩先は v0 の探索に入れない）
MIN_PAIR_DOCS = 20                        # 組の文書の数がこれ未満の隣は使わない
NEIGHBORS = (
    ("lift10", "lift", 10),               # lift（n_ij N / (n_i n_j)）の上位10。重みは n_ij / n_i
    ("share30", "share", 30),             # n_ij / n_i の上位30。重みは n_ij / n_i
)
# 未決事項3：先に届く波の単位
LEAD_UNITS = ("country", "language")      # 言語は、日の集計の L・NL の行に言語が入っているときだけ計算する
TOP_COUNTRIES = 30                        # 国の単位：最初の予言日より前の NC の合計の上位30か国
COUNTRY_RULE_END = datetime.date(2016, 4, 10)
LEAD_BASE_WEEKS = 52
LEAD_AGGS = ("max", "frac2")              # max：国ごとの上がりの最大 − 全体の上がり。frac2：2倍を超えた国の割合
# 2.3 空白の形
GAP_KINDS = ("gap", "expect")             # gap：自分の上がり − 隣の上がり。expect：網から見た期待値との比

# 評価
TRAIN_LAST = datetime.date(2018, 12, 3)   # 学習：予言日がこれ以前（判定期間が 2018 年の中で終わる）
TEST_FIRST = datetime.date(2019, 1, 7)    # 検証：予言日がこれ以降


def split_of(t):
    """予言日 t が学習（"train"）・検証（"test"）・どちらでもない（None）のどれか。"""
    if t <= TRAIN_LAST:
        return "train"
    if t >= TEST_FIRST:
        return "test"
    return None
TOP_K = 10
BLOCK_WEEKS = 4                           # 束ねる単位（判定期間 28 日の重なりに合わせた4週）
BOOT_N = 2000
BOOT_SEED = 117

MIN_FREE_GIB_HOME = 20
MIN_FREE_GIB_LACIE = 30
LACIE_PREFIX = "/Volumes/LACIE SHARE"

ITEMSIZE = array.array("I").itemsize
if ITEMSIZE != 4:
    raise RuntimeError("array('I') が4バイトでない")


class SignalError(Exception):
    pass


def own_code_shas():
    """このファイルと explore_islands.py の sha256（流した時点のファイルの中身）。"""
    out = {}
    for rel, path in (("src/stats/explore_signals.py", os.path.abspath(__file__)),
                      ("src/stats/explore_islands.py", os.path.abspath(ei.__file__))):
        with open(path, "rb") as f:
            out[rel] = hashlib.sha256(f.read()).hexdigest()
    return out


# T-117 で作ったキャッシュ（run1・run2）を作ったコードの版について、確かめられたことと、記録が無いこと。
# phase1.json の sha256 がこの値のときだけ、run.json と要約に写す。
KNOWN_CACHE_PHASE1_SHA256 = "3c71b39e14ed657365ed538ac912e971ac66c47c6a0ed79aceb336af0a36caa5"
KNOWN_CACHE_PROVENANCE = (
    "phase1.json には、作ったコード（explore_signals.py・explore_islands.py）の sha256 の記録が無い（この版の phase1 の前に作った）。",
    "run1（phase1.json の時刻 2026-10-16 17:46）：作った版の記録は無い。直後の試しの phase2（try1、17:56）の run.json には "
    "explore_signals.py の sha256 fb841994b1c20bf1d8cdc99d40ad28641a7c723d4d32d669d981ebb662302fc8 が記録されているが、"
    "run1 の phase1 がこれと同じ版で流れたことを示す記録は無い。",
    "run2（phase1.json の時刻 18:22）：コミット d23f0e2（17:57）のあと、phase1 と phase2 を一続きのコマンドで流した。"
    "そのときの phase2 の run.json（explore-t117）の explore_signals.py の sha256 は e69ecd9e59dfdea25ca487243f716d7b28b57825d3c97bd72842b6505abfa737"
    "で、d23f0e2 の版と一致する。phase1 の版そのものの記録は無い。",
    "run1 と run2 の74ファイルの sha256 はすべて同じ。",
)


# ---------------------------------------------------------------------------
# 日付の小道具
# ---------------------------------------------------------------------------

def month_key(d):
    return d.year * 100 + d.month


def month_first(mk):
    return datetime.date(mk // 100, mk % 100, 1)


def month_last(mk):
    y, m = mk // 100, mk % 100
    nxt = datetime.date(y + (m == 12), 1 if m == 12 else m + 1, 1)
    return nxt - ONE_DAY


def add_months(mk, n):
    y, m = mk // 100, mk % 100
    k = y * 12 + (m - 1) + n
    return (k // 12) * 100 + k % 12 + 1


def week_index(d):
    """区画の始まり（2015-03-02、月曜）からの週の番号。週は月曜〜日曜。"""
    return (d - ei.BLOCK_START).days // 7


def week_last_day(k):
    return ei.BLOCK_START + DAYS(days=7 * k + 6)


def network_months(t, window_months, refresh):
    """予言日 t に使う網の月の一覧。月ごとの更新なら t を含む月の前の window 個、四半期なら t を含む四半期の
    最初の月の前の window 個。区画の始まりより前の月は入れない。"""
    mk = month_key(t)
    if refresh == "Q":
        m = (mk % 100 - 1) // 3 * 3 + 1
        mk = (mk // 100) * 100 + m
    elif refresh != "M":
        raise ValueError("更新の頻度は M か Q")
    first_block = month_key(ei.BLOCK_START)
    out = [add_months(mk, -k) for k in range(window_months, 0, -1)]
    return [m for m in out if m >= first_block]


def check_network_before(t, months):
    """網の最後の日が t より前であること。外れれば止まる。戻り値：(最後の日 − t) の日数。"""
    last = month_last(months[-1])
    if not last < t:
        raise SignalError("網の最後の日 %s が予言日 %s より前でない" % (last, t))
    return (last - t).days


def lead_weeks(t):
    """t の前の週の番号と、その前の LEAD_BASE_WEEKS 週の番号。週の最後の日 < t を確かめる。"""
    if t.weekday() != 0:
        raise SignalError("予言日が月曜でない")
    k = week_index(t)
    rec = k - 1
    base = list(range(k - 1 - LEAD_BASE_WEEKS, k - 1))
    if base[0] < 0:
        raise SignalError("国別の過去分が区画の前に出る")
    if not week_last_day(rec) < t:
        raise SignalError("国別の週の最後の日が予言日より前でない")
    return rec, base


# ---------------------------------------------------------------------------
# 空きの確かめ・書き出し
# ---------------------------------------------------------------------------

def free_gib(path):
    st = os.statvfs(path)
    return st.f_bavail * st.f_frsize / (1024 ** 3)


def check_free(path):
    """書く前の空き。内蔵ディスクは 20 GiB、LACIE SHARE は 30 GiB を下回れば止まる。"""
    limit = MIN_FREE_GIB_LACIE if os.path.abspath(path).startswith(LACIE_PREFIX) else MIN_FREE_GIB_HOME
    g = free_gib(path)
    if g < limit:
        raise SignalError("空きが %.1f GiB で、下限 %d GiB を下回る。書かずに止まる" % (g, limit))
    return g


def write_new(path, data):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o644)
    with os.fdopen(fd, "wb") as f:
        f.write(data)
    return hashlib.sha256(data).hexdigest()


# ---------------------------------------------------------------------------
# phase1：日の集計を読む
# ---------------------------------------------------------------------------

def parse_extra(data, tag_index, country_index, pairs=None, ncols=None):
    """日の集計（gzip）から、一覧のタグの V1 の文書の数、数える組の文書の数、国別の数、NC、P1 の組を読む。

    tag_index：{テーマ名: 一覧の番号}。country_index：{国: 番号}（None なら国を読まない）。
    pairs：array('I')（N×N）。None でなければ、P1 の一覧のタグどうしの組の文書の数を両向きに足す。
    戻り値：{"v1": list, "docs": int, "c": {番号*U+k: 数}, "nc": {国: 数}, "lang_rows": 言語が「-」でない L・NL の行の数}
    翻訳の印 T の付いた組 g は数えない（counting.counted_group）。
    """
    n = len(tag_index)
    U = len(country_index) if country_index is not None else 0
    vocab = {}
    v1 = [0] * n
    docs = 0
    cdict = {}
    nc = {}
    lang_rows = 0
    counted = counting.counted_group
    for raw in gzip.GzipFile(fileobj=io.BytesIO(data)):
        tag, _s, rest = raw.partition(b"\t")
        if tag == b"P1":
            if pairs is None:
                continue
            g, a, b, k = rest.split(b"\t")
            if g.endswith(b"T"):
                continue
            ia = vocab.get(int(a), -1)
            if ia < 0:
                continue
            ib = vocab.get(int(b), -1)
            if ib < 0:
                continue
            x = int(k)
            pairs[ia * ncols + ib] += x
            pairs[ib * ncols + ia] += x
        elif tag == b"C":
            if country_index is None:
                continue
            f = rest.split(b"\t")
            if f[0].endswith(b"T"):
                continue
            i = vocab.get(int(f[1]), -1)
            if i < 0:
                continue
            k = country_index.get(f[2].decode("ascii"))
            if k is None:
                continue
            key = i * U + k
            cdict[key] = cdict.get(key, 0) + max(int(f[3]), int(f[4]))
        elif tag == b"V":
            i, name = rest.rstrip(b"\n").split(b"\t")
            j = tag_index.get(name.decode("ascii"))
            if j is not None:
                vocab[int(i)] = j
        elif tag == b"T":
            f = rest.split(b"\t")
            if not counted(f[0].decode("ascii")):
                continue
            j = vocab.get(int(f[1]), -1)
            if j >= 0:
                v1[j] += int(f[2])
        elif tag == b"D":
            g, k = rest.rstrip(b"\n").split(b"\t")
            if counted(g.decode("ascii")):
                docs += int(k)
        elif tag == b"NC":
            g, c, k = rest.rstrip(b"\n").split(b"\t")
            if counted(g.decode("ascii")):
                c = c.decode("ascii")
                nc[c] = nc.get(c, 0) + int(k)
        elif tag == b"L":
            if rest.split(b"\t")[2] != b"-":
                lang_rows += 1
        elif tag == b"NL":
            if rest.split(b"\t")[1] != b"-":
                lang_rows += 1
    return {"v1": v1, "docs": docs, "c": cdict, "nc": nc, "lang_rows": lang_rows}


_W = {}


def _init_p1(store, tags, countries, cache_dir):
    _W["store"], _W["tags"], _W["cache_dir"] = store, tuple(tags), cache_dir
    _W["tag_index"] = {t: i for i, t in enumerate(tags)}
    _W["country_index"] = None if countries is None else {c: k for k, c in enumerate(countries)}


def _read_verified(day, file_name, sha):
    if datetime.date.fromisoformat(day) >= ei.NEXT_BLOCK_START:
        raise SignalError("区画の外の日を読もうとした")
    if os.path.basename(file_name) != file_name:
        raise SignalError("ファイルの名前の形が違う")
    data = ei.read_nofollow(os.path.join(_W["store"], file_name))
    if hashlib.sha256(data).hexdigest() != sha:
        raise SignalError("%s：日の集計の sha256 が day の行と違う" % day)
    return data


def _countries_task(args):
    """国の単位を決めるための NC の合計（1日分）。"""
    day, file_name, sha = args
    data = _read_verified(day, file_name, sha)
    return parse_extra(data, {}, None)["nc"]


def _month_task(args):
    """1か月分の日の集計を読む。網（P1）はキャッシュに書き、日ごと・週ごとの数を返す。"""
    mk, items = args
    tags = _W["tags"]
    n = len(tags)
    U = len(_W["country_index"])
    pairs = array.array("I", bytes(ITEMSIZE * n * n))
    days_out = []
    weekc, weeknc = {}, {}
    lang_rows = 0
    for day, file_name, sha, missing in items:
        data = _read_verified(day, file_name, sha)
        summary = counting.parse_day(data, expect_day=day, expect_mode=counting.OFFICIAL_MODE)
        counts, total = counting.candidate_counts(summary, OFFICIAL_CID)
        del summary
        c7 = array.array("I", [counts.get(t, 0) for t in tags])
        ex = parse_extra(data, _W["tag_index"], _W["country_index"], None if missing else pairs, n)
        del data
        lang_rows += ex["lang_rows"]
        days_out.append((day, total, c7.tobytes(), array.array("I", ex["v1"]).tobytes(), ex["docs"]))
        if not missing:
            k = week_index(datetime.date.fromisoformat(day))
            wc = weekc.setdefault(k, array.array("I", bytes(ITEMSIZE * n * U)))
            for key, x in ex["c"].items():
                wc[key] += x
            wn = weeknc.setdefault(k, [0] * U)
            for c, x in ex["nc"].items():
                j = _W["country_index"].get(c)
                if j is not None:
                    wn[j] += x
    blob = zlib.compress(pairs.tobytes(), 6)
    del pairs
    path = os.path.join(_W["cache_dir"], "pairs-%06d.bin.z" % mk)
    check_free(_W["cache_dir"])
    sha = write_new(path, blob)
    return mk, days_out, {k: v.tobytes() for k, v in weekc.items()}, weeknc, sha, len(blob), lang_rows


def choose_countries(nc_totals):
    """NC の合計の多い順に上位 TOP_COUNTRIES（同じなら国の符号の順）。"""
    return [c for c, _n in sorted(nc_totals.items(), key=lambda x: (-x[1], x[0]))[:TOP_COUNTRIES]]


def _pool(workers, init, initargs):
    return multiprocessing.get_context("spawn").Pool(workers, initializer=init, initargs=initargs)


def phase1(root, store, cache_dir, workers, log):
    ctx = ei.load_context(root)
    if os.path.lexists(cache_dir):
        raise SignalError("キャッシュのフォルダが既にある。上書きしない")
    parent = os.path.dirname(os.path.abspath(cache_dir))
    check_free(parent)
    os.mkdir(cache_dir)
    tags, days, rows, missing = ctx["tags"], ctx["days"], ctx["rows"], ctx["missing"]
    n = len(tags)
    # 国の単位：最初の予言日より前の、欠けた日でない日の NC
    early = [d for d in days if d <= COUNTRY_RULE_END and d not in missing]
    tasks = [(d.isoformat(), rows[d.isoformat()]["file_name"], rows[d.isoformat()]["sha256"]) for d in early]
    nc_tot = {}
    with _pool(workers, _init_p1, (store, tags, None, cache_dir)) as pool:
        for i, nc in enumerate(pool.imap(_countries_task, tasks, chunksize=2), 1):
            for c, x in nc.items():
                nc_tot[c] = nc_tot.get(c, 0) + x
            if i % 100 == 0:
                log("国の単位 %d / %d" % (i, len(tasks)))
    countries = choose_countries(nc_tot)
    log("国の単位：%d か国" % len(countries))
    # 月ごと
    months = sorted({month_key(d) for d in days})
    mtasks = []
    for mk in months:
        items = [(d.isoformat(), rows[d.isoformat()]["file_name"], rows[d.isoformat()]["sha256"], d in missing)
                 for d in days if month_key(d) == mk]
        mtasks.append((mk, items))
    U = len(countries)
    nweeks = week_index(ei.BLOCK_END) + 1
    by_day = {}
    weekc = [array.array("I", bytes(ITEMSIZE * n * U)) for _ in range(nweeks)]
    weeknc = [[0] * U for _ in range(nweeks)]
    pair_files = {}
    lang_rows = 0
    with _pool(workers, _init_p1, (store, tags, countries, cache_dir)) as pool:
        for i, (mk, dout, wc, wn, sha, size, lr) in enumerate(pool.imap(_month_task, mtasks), 1):
            pair_files[mk] = {"file": "pairs-%06d.bin.z" % mk, "sha256": sha, "bytes": size}
            lang_rows += lr
            for rec in dout:
                by_day[rec[0]] = rec
            for k, b in wc.items():
                a = array.array("I")
                a.frombytes(b)
                weekc[k] = array.array("I", map(operator.add, weekc[k], a))
            for k, v in wn.items():
                weeknc[k] = [x + y for x, y in zip(weeknc[k], v)]
            log("月 %d / %d（%d）" % (i, len(mtasks), mk))
    bad = [d for d in by_day if by_day[d][1] != ctx["denom"][d]]
    if bad:
        raise SignalError("C7 の分母が順番4の一覧と違う日がある（最初は %s）" % sorted(bad)[0])
    order = [d.isoformat() for d in days]
    c7 = b"".join(by_day[d][2] for d in order)
    v1 = b"".join(by_day[d][3] for d in order)
    files = {}
    check_free(cache_dir)
    for name, blob in (("c7.bin.z", zlib.compress(c7, 6)), ("v1.bin.z", zlib.compress(v1, 6)),
                       ("weekc.bin.z", zlib.compress(b"".join(w.tobytes() for w in weekc), 6))):
        files[name] = {"sha256": write_new(os.path.join(cache_dir, name), blob), "bytes": len(blob)}
    meta = {
        "label": PHASE1_LABEL, "tags": tags, "countries": countries, "days": order,
        "totals": [by_day[d][1] for d in order], "docs": [by_day[d][4] for d in order],
        "missing": sorted(d.isoformat() for d in missing), "weeks": nweeks, "weeknc": weeknc,
        "months": months, "pair_files": {str(k): v for k, v in sorted(pair_files.items())}, "files": files,
        "lang_rows_not_dash": lang_rows, "refs": ctx["refs"], "v": "%d/%d" % (ctx["v"].numerator, ctx["v"].denominator),
        "code": dict(ei._LOADED_SHA, **own_code_shas()), "itemsize": ITEMSIZE, "byteorder": sys.byteorder,
        "country_rule": "top %d by NC docs (non-T groups) over non-missing days %s..%s" % (
            TOP_COUNTRIES, ei.BLOCK_START, COUNTRY_RULE_END),
    }
    data = (json.dumps(meta, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")
    sha = write_new(os.path.join(cache_dir, "phase1.json"), data)
    return sha


# ---------------------------------------------------------------------------
# phase2：キャッシュを照らして読む
# ---------------------------------------------------------------------------

def read_cache_file(cache_dir, name, want_sha):
    data = ei.read_nofollow(os.path.join(cache_dir, name))
    if hashlib.sha256(data).hexdigest() != want_sha:
        raise SignalError("キャッシュの %s の sha256 が phase1.json と違う" % name)
    return data


def load_cache(cache_dir, ctx):
    raw = ei.read_nofollow(os.path.join(cache_dir, "phase1.json"))
    meta = json.loads(raw.decode("utf-8"))
    if meta.get("label") != PHASE1_LABEL:
        raise SignalError("キャッシュの版が違う")
    if meta["tags"] != ctx["tags"] or meta["refs"] != ctx["refs"] or \
            meta["days"] != [d.isoformat() for d in ctx["days"]] or \
            meta["missing"] != sorted(d.isoformat() for d in ctx["missing"]):
        raise SignalError("キャッシュが、封印の記録から読んだ一覧・参照・日・欠けた日と合わない")
    if meta["itemsize"] != ITEMSIZE or meta["byteorder"] != sys.byteorder:
        raise SignalError("キャッシュの数の形がこの計算機と違う")
    if meta["totals"] != [ctx["denom"][d] for d in meta["days"]]:
        raise SignalError("キャッシュの C7 の分母が順番4の一覧と違う")

    def arr(name):
        a = array.array("I")
        a.frombytes(zlib.decompress(read_cache_file(cache_dir, name, meta["files"][name]["sha256"])))
        return a
    meta["c7"] = arr("c7.bin.z")
    meta["v1"] = arr("v1.bin.z")
    meta["weekc"] = arr("weekc.bin.z")
    meta["phase1_sha256"] = hashlib.sha256(raw).hexdigest()
    return meta


def daily_series(meta):
    """タグごとの日の比率の列（欠けた日は None）。"""
    n = len(meta["tags"])
    missing = set(meta["missing"])
    c7 = meta["c7"]
    series = [[] for _ in range(n)]
    for di, (d, tot) in enumerate(zip(meta["days"], meta["totals"])):
        if d in missing:
            for s in series:
                s.append(None)
            continue
        if tot <= 0:
            raise SignalError("欠けた日でないのに分母が 0")
        base = di * n
        for i in range(n):
            series[i].append(c7[base + i] / tot)
    return series


# ---------------------------------------------------------------------------
# タグごとの計算（子プロセス）：状態・B・c・判定・素朴な予測の値
# ---------------------------------------------------------------------------

def evaluate_tag(days, values, mondays, v):
    """予言日ごとに (状態, B, c, m1, m2, 判定3つ, 素朴な予測の値)。読み方は ReadGuard で守る。

    m1：終わりが t-1 の7日の平均、m2：終わりが t-8 の7日の平均（欠けた日を含めば None）。
    判定と素朴な予測の値は、対象（状態 target）のときだけ。
    """
    get = ei.ReadGuard(days, values)
    out = []
    for t in mondays:
        get.allow(t - DAYS(days=NAIVE_LOOKBACK), t - ONE_DAY)
        st = scoring.target_status(get, t, v)
        b = c = m1 = m2 = None
        if st != "no_baseline":
            b = candidates.baseline_level(get, t)
            c = candidates.current_level(get, t)
            m1 = candidates._block_mean(get, t - ONE_DAY)
            m2 = candidates._block_mean(get, t - DAYS(days=8))
        js = lv = None
        if st == "target":
            lv = naive.raw_levels(get, t, HORIZON)
            get.allow(t + ONE_DAY, t + DAYS(days=HORIZON))
            js = tuple(candidates.judge(get, t, HORIZON, m, b, v) for m in MULTIPLIERS)
        out.append((st, b, c, m1, m2, js, lv))
    return out, get.min_read, get.max_read


def _init_eval(days, mondays, v):
    _W["days"], _W["mondays"], _W["v"] = days, mondays, v


def _eval_task(args):
    j, values = args
    return (j,) + evaluate_tag(_W["days"], values, _W["mondays"], _W["v"])


# ---------------------------------------------------------------------------
# 共起の網（子プロセス）
# ---------------------------------------------------------------------------

def load_pairs(cache_dir, meta, mk):
    pf = meta["pair_files"][str(mk)]
    a = array.array("I")
    a.frombytes(zlib.decompress(read_cache_file(cache_dir, pf["file"], pf["sha256"])))
    return a


def neighbors_from_matrix(mat, n, marg, total):
    """網の行列（n×n、両向き）と、テーマごとの文書の数 marg、全体の文書の数 total から、隣の一覧を作る。

    戻り値：{近さの名前: Nbrs}。Nbrs.get(i) は [(j, 重み n_ij/n_i, s_ji = n_ij/n_j), ...]。
    """
    out = {name: [] for name, _k, _K in NEIGHBORS}
    for i in range(n):
        row = mat[i * n:(i + 1) * n]
        ni = marg[i]
        cand = [(j, x) for j, x in enumerate(row) if x >= MIN_PAIR_DOCS and j != i] if ni > 0 else []
        for name, kind, K in NEIGHBORS:
            if kind == "lift":
                sc = [((x * total) / (ni * marg[j]) if marg[j] > 0 else 0.0, j, x) for j, x in cand]
            else:
                sc = [(x / ni, j, x) for j, x in cand]
            sc.sort(key=lambda z: (-z[0], z[1]))
            out[name].append([(j, x / ni, (x / marg[j]) if marg[j] > 0 else 0.0) for _s, j, x in sc[:K]])
    return {name: Nbrs(lists) for name, lists in out.items()}


class Nbrs:
    """タグごとの隣の一覧を、配列に詰めて持つ（メモリを抑えるため）。"""

    def __init__(self, lists):
        self.off = array.array("I", [0])
        self.j = array.array("I")
        self.w = array.array("d")
        self.s = array.array("d")
        for lst in lists:
            for j, w, x in lst:
                self.j.append(j)
                self.w.append(w)
                self.s.append(x)
            self.off.append(len(self.j))

    def get(self, i):
        a, b = self.off[i], self.off[i + 1]
        return list(zip(self.j[a:b], self.w[a:b], self.s[a:b]))

    def __getstate__(self):
        return (self.off.tobytes(), self.j.tobytes(), self.w.tobytes(), self.s.tobytes())

    def __setstate__(self, st):
        self.off, self.j, self.w, self.s = (array.array("I"), array.array("I"), array.array("d"), array.array("d"))
        for a, b in zip((self.off, self.j, self.w, self.s), st):
            a.frombytes(b)


def _init_net(cache_dir, meta_small):
    _W["cache_dir"], _W["meta"] = cache_dir, meta_small


def _net_task(args):
    window, mk = args
    meta = _W["meta"]
    n = len(meta["tags"])
    months = network_months(month_first(mk), window, "M")
    acc = None
    for m in months:
        a = load_pairs(_W["cache_dir"], meta, m)
        acc = a if acc is None else array.array("I", map(operator.add, acc, a))
    marg = [0] * n
    total = 0
    for m in months:
        for i in range(n):
            marg[i] += meta["month_v1"][m][i]
        total += meta["month_docs"][m]
    return window, mk, months, neighbors_from_matrix(acc, n, marg, total)


# ---------------------------------------------------------------------------
# 信号
# ---------------------------------------------------------------------------

def rise(c, b, v):
    return math.log((c + v) / (b + v))


def weighted_mean(pairs):
    """[(重み, 値)] の値が None でないものの重み付き平均。無ければ None。"""
    sw = sx = 0.0
    for w, x in pairs:
        if x is not None and w > 0:
            sw += w
            sx += w * x
    return sx / sw if sw > 0 else None


def neighbor_signal(nbrs, rises, trends):
    """隣の上がり（重み付き平均）と隣の勢い。どちらも隣に値が無ければ None。"""
    return (weighted_mean([(w, rises[j]) for j, w, _s in nbrs]),
            weighted_mean([(w, trends[j]) for j, w, _s in nbrs]))


def expect_signal(i, nbrs, cur, win, v):
    """網から見た期待値との比：期待値 = win_i × Σ s_ji c_j / Σ s_ji win_j（c と win は隣の比率）。
    log((c_i + V) / (期待値 + V))。決まらなければ None。"""
    num = den = 0.0
    for j, _w, s in nbrs:
        if cur[j] is None or win[j] is None or s <= 0:
            continue
        num += s * cur[j]
        den += s * win[j]
    if den <= 0 or cur[i] is None or win[i] is None:
        return None
    return math.log((cur[i] + v) / (win[i] * num / den + v))


def cumulative_weeks(weekc, weeknc, n, U):
    """週ごとの国別の数の累積和（cum[k] は週 0〜k-1 の和）。"""
    W = len(weeknc)
    size = n * U
    cumc = array.array("Q", bytes(8 * size * (W + 1)))
    for k in range(W):
        a, b = k * size, (k + 1) * size
        cumc[b:b + size] = array.array("Q", map(operator.add, cumc[a:a + size], weekc[a:a + size]))
    cumn = [[0] * U]
    for k in range(W):
        cumn.append([x + y for x, y in zip(cumn[-1], weeknc[k])])
    return cumc, cumn


def lead_signal(i, rec_w, base_w, cumc, cumn, n, U, v):
    """国別の先に届く波。(max：国ごとの上がりの最大 − 上位の国の合計の上がり, frac2：2倍を超えた国の割合)。
    rec_w の週と base_w（連続した週）の和を、累積和から取る。国別の数がこのタグに一つも無ければ (None, None)。"""
    if list(base_w) != list(range(base_w[0], base_w[-1] + 1)) or base_w[-1] + 1 != rec_w:
        raise SignalError("国別の週の並びが違う")
    size = n * U
    b0, b1, r1 = base_w[0], base_w[-1] + 1, rec_w + 1
    units = []
    tr = tb = nr = nb = 0
    for k in range(U):
        x = i * U + k
        r = cumc[r1 * size + x] - cumc[rec_w * size + x]
        b = cumc[b1 * size + x] - cumc[b0 * size + x]
        dr = cumn[r1][k] - cumn[rec_w][k]
        db = cumn[b1][k] - cumn[b0][k]
        units.append((r, b, dr, db))
        tr += r
        tb += b
        nr += dr
        nb += db
    if (tr == 0 and tb == 0) or nr == 0 or nb == 0:
        return None, None
    rises = [math.log((r / dr + v) / (b / db + v)) for r, b, dr, db in units if dr > 0 and db > 0]
    if not rises:
        return None, None
    tot = math.log((tr / nr + v) / (tb / nb + v))
    return max(rises) - tot, sum(1 for x in rises if x > math.log(2)) / len(rises)


# ---------------------------------------------------------------------------
# 評価
# ---------------------------------------------------------------------------

def log_loss_terms(ps, ys):
    out = []
    for p, y in zip(ps, ys):
        p = min(max(p, 1e-15), 1 - 1e-15)
        out.append(-math.log(p) if y else -math.log(1 - p))
    return out


def auc(ps, ys):
    """順位による AUC（同じ値は平均の順位）。正か負が無ければ None。"""
    order = sorted(range(len(ps)), key=lambda i: ps[i])
    ranks = [0.0] * len(ps)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and ps[order[j + 1]] == ps[order[i]]:
            j += 1
        r = (i + j) / 2 + 1
        for k in range(i, j + 1):
            ranks[order[k]] = r
        i = j + 1
    n1 = sum(ys)
    n0 = len(ys) - n1
    if n1 == 0 or n0 == 0:
        return None
    return (sum(r for r, y in zip(ranks, ys) if y) - n1 * (n1 + 1) / 2) / (n1 * n0)


def topk_by_week(ps, ys, weeks, tags, k=TOP_K):
    """週ごとに確率の上位 k（同じなら名前の順）の島の数。戻り値 {週: 数}。"""
    by = {}
    for p, y, w, t in zip(ps, ys, weeks, tags):
        by.setdefault(w, []).append((-p, t, y))
    return {w: sum(y for _p, _t, y in sorted(v)[:k]) for w, v in by.items()}


def blocks_of(weeks_sorted, size):
    return [weeks_sorted[i:i + size] for i in range(0, len(weeks_sorted), size)]


def bootstrap_diff(block_vals, n_boot=BOOT_N, seed=BOOT_SEED):
    """block_vals：[(差の和, 件数)]。束ねた単位を復元抽出し、差の平均（和 ÷ 件数）の 2.5% と 97.5% 点を返す。"""
    rng = random.Random(seed)
    nb = len(block_vals)
    stats = []
    for _ in range(n_boot):
        s = c = 0.0
        for _k in range(nb):
            a, b = block_vals[rng.randrange(nb)]
            s += a
            c += b
        stats.append(s / c if c else 0.0)
    stats.sort()
    lo = stats[max(0, int(math.ceil(0.025 * n_boot)) - 1)]
    hi = stats[max(0, int(math.ceil(0.975 * n_boot)) - 1)]
    return lo, hi


def _init_fit(table):
    _W["table"] = table


def _fit_task(args):
    """1つのモデル：(組み合わせ, モデルの名前, 使う列)。学習して検証の確率を返す。"""
    m, name, cols = args
    tb = _W["table"]
    ycol = "y%d" % m
    base = ["naive%d_%d" % (m, k) for k in range(len(naive.FEATURES))]
    use = base + list(cols)
    rows = []
    for r in tb["train"]:
        rows.append((r, tb["tag"][r], [tb[c][r] for c in use], tb[ycol][r]))
    fit = naive.fit_rows([(tb["t"][r], tb["tag"][r], x, y) for r, _tg, x, y in rows])
    probs = [naive.predict(fit["coef"], [tb[c][r] for c in use]) for r in tb["test"]]
    return m, name, use, fit["coef"], fit["iterations"], fit["converged"], probs


# ---------------------------------------------------------------------------
# phase2 の本体
# ---------------------------------------------------------------------------

def model_specs(lang_ok):
    """モデルの一覧（素朴な予測だけ、信号を1つずつ、三つすべて）。列の名前は signal_columns と同じ。"""
    specs = [("naive", ())]
    for net, _w, _r in NETWORKS:
        for nb, _k, _K in NEIGHBORS:
            v = "%s_%s" % (net, nb)
            specs.append(("s21_" + v, ("nb_rise_" + v, "nb_trend_" + v, "nb_miss_" + v)))
    for unit in LEAD_UNITS:
        if unit == "language" and not lang_ok:
            continue
        for agg in LEAD_AGGS:
            specs.append(("s22_%s_%s" % (unit, agg), ("lead_%s_%s" % (unit, agg), "lead_miss_" + unit)))
    for net, _w, _r in NETWORKS:
        for nb, _k, _K in NEIGHBORS:
            v = "%s_%s" % (net, nb)
            for g in GAP_KINDS:
                specs.append(("s23_%s_%s" % (g, v), ("%s_%s" % (g, v), "%s_miss_%s" % (g, v))))
    for net, _w, _r in NETWORKS:
        for nb, _k, _K in NEIGHBORS:
            v = "%s_%s" % (net, nb)
            specs.append(("all_" + v, ("nb_rise_" + v, "nb_trend_" + v, "nb_miss_" + v,
                                       "lead_country_max", "lead_miss_country", "gap_" + v, "gap_miss_" + v)))
    return specs


def phase2(root, cache_dir, out_dir, workers, log):
    ctx = ei.load_context(root)
    meta = load_cache(cache_dir, ctx)
    tags, v = meta["tags"], ctx["v"]
    n = len(tags)
    U = len(meta["countries"])
    days = ctx["days"]
    mondays = ei.prediction_mondays()
    lang_ok = meta["lang_rows_not_dash"] > 0
    if lang_ok:
        raise SignalError("日の集計に言語の別がある。言語の単位の計算はこの版に無いので止まる（報告する）")
    series = daily_series(meta)
    meta["v1_equals_c7"] = meta["v1"] == meta["c7"]
    cumc, cumn = cumulative_weeks(meta["weekc"], meta["weeknc"], n, U)
    del meta["weekc"]
    log("キャッシュを読んだ")
    # A：タグごと
    results = [None] * n
    lo = hi = None
    with _pool(workers, _init_eval, (days, mondays, v)) as pool:
        for k, (j, res, a, b) in enumerate(pool.imap(_eval_task, list(enumerate(series)), chunksize=8), 1):
            results[j] = res
            if a is not None:
                lo = a if lo is None or a < lo else lo
                hi = b if hi is None or b > hi else hi
            if k % 500 == 0:
                log("タグ %d / %d" % (k, n))
    # 月ごとの V1 の文書の数・全体の文書の数・比率の平均（網と期待値に使う）
    missing = set(meta["missing"])
    month_v1, month_docs, month_rsum, month_cnt = {}, {}, {}, {}
    v1 = meta["v1"]
    for di, d in enumerate(meta["days"]):
        if d in missing:
            continue
        mk = month_key(datetime.date.fromisoformat(d))
        mv = month_v1.setdefault(mk, [0] * n)
        rs = month_rsum.setdefault(mk, [0.0] * n)
        for i in range(n):
            mv[i] += v1[di * n + i]
            rs[i] += series[i][di]
        month_docs[mk] = month_docs.get(mk, 0) + meta["docs"][di]
        month_cnt[mk] = month_cnt.get(mk, 0) + 1
    # B：網（月ごとの更新の月すべて、窓の長さごと）
    pred_months = sorted({month_key(t) for t in mondays})
    windows = sorted({w for _n, w, _r in NETWORKS})
    small = {"tags": tags, "pair_files": meta["pair_files"], "month_v1": month_v1, "month_docs": month_docs}
    nets = {}
    with _pool(workers, _init_net, (cache_dir, small)) as pool:
        for k, (w, mk, months, nb) in enumerate(pool.imap(_net_task, [(w, mk) for w in windows for mk in pred_months]), 1):
            nets[(w, mk)] = (months, nb)
            if k % 20 == 0:
                log("網 %d / %d" % (k, len(windows) * len(pred_months)))
    # C：対象の行と信号
    table = {"t": [], "tag": [], "week": [], "train": [], "test": []}
    for m in MULTIPLIERS:
        table["y%d" % m] = []
        for k in range(len(naive.FEATURES)):
            table["naive%d_%d" % (m, k)] = []
    specs = model_specs(lang_ok)
    cols = sorted({c for _n, cs in specs for c in cs})
    for c in cols:
        table[c] = []
    net_offset_max = None
    lead_offset_max = None
    win_cache = {}
    netstat = {}
    for ti, t in enumerate(mondays):
        rises = [None] * n
        trends = [None] * n
        cur = [None] * n
        for j in range(n):
            st, b, c, m1, m2, _js, _lv = results[j][ti]
            if b is not None and c is not None:
                rises[j] = rise(c, b, v)
                cur[j] = c
            if m1 is not None and m2 is not None:
                trends[j] = rise(m1, m2, v)
        rec_w, base_w = lead_weeks(t)
        off = (week_last_day(rec_w) - t).days
        lead_offset_max = off if lead_offset_max is None else max(lead_offset_max, off)
        per_net = {}
        for net, w, refresh in NETWORKS:
            months = network_months(t, w, refresh)
            off = check_network_before(t, months)
            net_offset_max = off if net_offset_max is None else max(net_offset_max, off)
            key_mk = add_months(months[-1], 1)
            got_months, nb = nets[(w, key_mk)]
            if got_months != months:
                raise SignalError("網の月の一覧が合わない")
            wk = tuple(months)
            if wk not in win_cache:
                cnt = sum(month_cnt[m] for m in months)
                win_cache[wk] = [(sum(month_rsum[m][i] for m in months) / cnt) if cnt else None for i in range(n)]
            per_net[net] = (nb, win_cache[wk])
        for i in range(n):
            st, b, c, m1, m2, js, lv = results[i][ti]
            if st != "target" or any(x is None for x in js):
                continue
            table["t"].append(t)
            table["tag"].append(tags[i])
            table["week"].append(ti)
            r = len(table["t"]) - 1
            sp = split_of(t)
            if sp is not None:
                table[sp].append(r)
            for m, y in zip(MULTIPLIERS, js):
                table["y%d" % m].append(1 if y else 0)
                for k, x in enumerate(naive.features_from_levels(lv, m, v)):
                    table["naive%d_%d" % (m, k)].append(x)
            vals = {}
            for net, _w, _r in NETWORKS:
                nb, win = per_net[net]
                for nbn, _k, _K in NEIGHBORS:
                    vv = "%s_%s" % (net, nbn)
                    nbrs = nb[nbn].get(i)
                    nr, nt = neighbor_signal(nbrs, rises, trends)
                    ns = netstat.setdefault(vv, [0, 0, 0])
                    ns[0] += 1
                    ns[1] += len(nbrs)
                    ns[2] += 1 if not nbrs else 0
                    vals["nb_rise_" + vv] = nr
                    vals["nb_trend_" + vv] = nt
                    vals["nb_miss_" + vv] = None
                    vals["gap_" + vv] = (rises[i] - nr) if (nr is not None and rises[i] is not None) else None
                    vals["expect_" + vv] = expect_signal(i, nbrs, cur, win, v)
            lm, lf = lead_signal(i, rec_w, base_w, cumc, cumn, n, U, v)
            vals["lead_country_max"], vals["lead_country_frac2"] = lm, lf
            for c in cols:
                if "_miss_" in c or c.startswith("lead_miss"):
                    continue
                x = vals.get(c)
                table[c].append(0.0 if x is None else x)
            for c in cols:
                if c.startswith("nb_miss_"):
                    vv = c[len("nb_miss_"):]
                    table[c].append(1.0 if vals["nb_rise_" + vv] is None else 0.0)
                elif c.startswith("gap_miss_"):
                    vv = c[len("gap_miss_"):]
                    table[c].append(1.0 if vals["gap_" + vv] is None else 0.0)
                elif c.startswith("expect_miss_"):
                    vv = c[len("expect_miss_"):]
                    table[c].append(1.0 if vals["expect_" + vv] is None else 0.0)
                elif c == "lead_miss_country":
                    table[c].append(1.0 if lm is None else 0.0)
        if (ti + 1) % 40 == 0:
            log("信号 %d / %d 週" % (ti + 1, len(mondays)))
    for c in cols:
        if len(table[c]) != len(table["t"]):
            raise SignalError("列 %s の長さが違う" % c)
        table[c] = array.array("d", table[c])
    for m in MULTIPLIERS:
        table["y%d" % m] = array.array("b", table["y%d" % m])
        for k in range(len(naive.FEATURES)):
            table["naive%d_%d" % (m, k)] = array.array("d", table["naive%d_%d" % (m, k)])
    log("対象の行 %d（学習 %d、検証 %d）" % (len(table["t"]), len(table["train"]), len(table["test"])))
    # D：モデル
    tasks = [(m, name, cs) for m in MULTIPLIERS for name, cs in specs]
    fits = {}
    with _pool(workers, _init_fit, (table,)) as pool:
        for k, (m, name, use, coef, it, conv, probs) in enumerate(pool.imap(_fit_task, tasks), 1):
            fits[(m, name)] = (use, coef, it, conv, probs)
            log("モデル %d / %d（倍率 %d、%s）" % (k, len(tasks), m, name))
    files = build_outputs(meta, ctx, table, specs, fits, mondays, netstat, lo, hi, net_offset_max,
                          lead_offset_max, lang_ok)
    return write_outputs(out_dir, files)


# ---------------------------------------------------------------------------
# 出力
# ---------------------------------------------------------------------------

def f6(x):
    return "-" if x is None else "%.6f" % x


def evaluate_models(table, specs, fits):
    """モデルごとの検証の指標と、素朴な予測との差の束ねたばらつき。"""
    test = table["test"]
    weeks = sorted({table["week"][r] for r in test})
    week_pos = {w: i for i, w in enumerate(weeks)}
    blk4 = blocks_of(weeks, BLOCK_WEEKS)
    blk1 = blocks_of(weeks, 1)
    rows = []
    per = {}
    for m in MULTIPLIERS:
        ys = [table["y%d" % m][r] for r in test]
        wk = [table["week"][r] for r in test]
        tg = [table["tag"][r] for r in test]
        for name, _cs in specs:
            use, coef, it, conv, probs = fits[(m, name)]
            ll = log_loss_terms(probs, ys)
            tk = topk_by_week(probs, ys, wk, tg)
            per[(m, name)] = (ll, tk, probs)
        nll, ntk, _np = per[(m, "naive")]
        for name, _cs in specs:
            use, coef, it, conv, probs = fits[(m, name)]
            ll, tk, _p = per[(m, name)]
            by_w = {}
            for x, xn, w in zip(ll, nll, wk):
                a = by_w.setdefault(w, [0.0, 0])
                a[0] += x - xn
                a[1] += 1
            res = {}
            for label, blks in (("b4", blk4), ("b1", blk1)):
                vals = [(sum(by_w[w][0] for w in b), sum(by_w[w][1] for w in b)) for b in blks]
                res["ll_" + label] = bootstrap_diff(vals)
                tvals = [(sum(tk.get(w, 0) - ntk.get(w, 0) for w in b), len(b)) for b in blks]
                lo, hi = bootstrap_diff(tvals)
                res["tk_" + label] = (lo * len(weeks), hi * len(weeks))
            rows.append({
                "m": m, "name": name, "n_test": len(ys), "pos_test": sum(ys),
                "logloss": sum(ll) / len(ll), "auc": auc(probs, ys), "topk": sum(tk.values()),
                "d_logloss": (sum(ll) - sum(nll)) / len(ll), "d_topk": sum(tk.values()) - sum(ntk.values()),
                "conv": conv, "iter": it, **res})
    return rows, len(weeks), len(blk4)


def miss_column(c):
    """値の列 c に対応する、値が決まらないことを示す列。c が値の列でなければ None。"""
    if "_miss" in c:
        return None
    for pre in ("nb_rise_", "nb_trend_"):
        if c.startswith(pre):
            return "nb_miss_" + c[len(pre):]
    for pre in ("gap_", "expect_"):
        if c.startswith(pre):
            return pre[:-1] + "_miss_" + c[len(pre):]
    if c.startswith("lead_country_"):
        return "lead_miss_country"
    raise SignalError("知らない列 %s" % c)


def signal_summary(table, cols):
    """学習の行で、信号の列ごとの値の有る数と、島（倍率 4）と島でないものの平均。"""
    out = []
    tr = table["train"]
    for c in cols:
        miss = miss_column(c)
        if miss is None:
            continue
        have = [r for r in tr if miss is None or table[miss][r] == 0.0]
        for m in MULTIPLIERS:
            y = table["y%d" % m]
            pos = [table[c][r] for r in have if y[r]]
            neg = [table[c][r] for r in have if not y[r]]
            out.append((c, m, len(tr), len(have), len(pos), f6(sum(pos) / len(pos) if pos else None),
                        f6(sum(neg) / len(neg) if neg else None)))
    return out


def build_outputs(meta, ctx, table, specs, fits, mondays, netstat, lo, hi, net_off, lead_off, lang_ok):
    evrows, nweeks, nblocks = evaluate_models(table, specs, fits)
    cols = sorted({c for _n, cs in specs for c in cs})
    models_tsv = ei.tsv(
        ("multiplier", "horizon_days", "model", "n_test", "islands_test", "logloss", "auc", "top10_hits",
         "d_logloss_vs_naive", "d_logloss_ci4w_lo", "d_logloss_ci4w_hi", "d_logloss_ci1w_lo", "d_logloss_ci1w_hi",
         "d_top10_vs_naive", "d_top10_ci4w_lo", "d_top10_ci4w_hi", "converged", "iterations"),
        [(r["m"], HORIZON, r["name"], r["n_test"], r["pos_test"], f6(r["logloss"]), f6(r["auc"]), r["topk"],
          f6(r["d_logloss"]), f6(r["ll_b4"][0]), f6(r["ll_b4"][1]), f6(r["ll_b1"][0]), f6(r["ll_b1"][1]),
          r["d_topk"], "%.1f" % r["tk_b4"][0], "%.1f" % r["tk_b4"][1], r["conv"], r["iter"]) for r in evrows])
    coef_rows = []
    for (m, name), (use, coef, it, conv, _p) in sorted(fits.items()):
        for c, b in zip(use, coef):
            fname = naive.FEATURES[int(c.split("_")[1])] if c.startswith("naive") else c
            coef_rows.append((m, name, fname, f6(b)))
    coefs_tsv = ei.tsv(("multiplier", "model", "feature", "coef"), coef_rows)
    sig = signal_summary(table, cols)
    sig_tsv = ei.tsv(("signal", "multiplier", "train_rows", "rows_with_value", "islands_with_value",
                      "mean_islands", "mean_non_islands"), sig)
    net_tsv = ei.tsv(("network_neighbors", "target_rows", "mean_neighbors", "rows_without_neighbors"),
                     [(k, a, "%.2f" % (b / a), c) for k, (a, b, c) in sorted(netstat.items())])
    split = {"train_rows": len(table["train"]), "test_rows": len(table["test"]), "all_rows": len(table["t"])}
    for m in MULTIPLIERS:
        y = table["y%d" % m]
        split["train_islands_m%d" % m] = sum(y[r] for r in table["train"])
        split["test_islands_m%d" % m] = sum(y[r] for r in table["test"])
    run = {
        "label": LABEL, "phase1_sha256": meta["phase1_sha256"], "phase1_label": meta["label"],
        "refs": ctx["refs"], "v": meta["v"], "tag_count": len(meta["tags"]), "countries": len(meta["countries"]),
        "lang_rows_not_dash": meta["lang_rows_not_dash"], "language_unit_computed": lang_ok,
        "v1_docs_equal_c7_numerator_all_days": meta.get("v1_equals_c7"),
        "mondays": [len(mondays), mondays[0].isoformat(), mondays[-1].isoformat()],
        "daily_min_read": lo.isoformat() if lo else None, "daily_max_read": hi.isoformat() if hi else None,
        "network_last_day_minus_t_max_days": net_off, "country_week_last_day_minus_t_max_days": lead_off,
        "train_last_monday": TRAIN_LAST.isoformat(), "test_first_monday": TEST_FIRST.isoformat(),
        "test_weeks": nweeks, "test_blocks_4w": nblocks, "split": split,
        "options": {"networks": NETWORKS, "neighbors": NEIGHBORS, "min_pair_docs": MIN_PAIR_DOCS,
                    "lead_units": LEAD_UNITS, "top_countries": TOP_COUNTRIES, "lead_aggs": LEAD_AGGS,
                    "lead_base_weeks": LEAD_BASE_WEEKS, "gap_kinds": GAP_KINDS, "multipliers": MULTIPLIERS,
                    "horizon": HORIZON, "top_k": TOP_K, "boot_n": BOOT_N, "boot_seed": BOOT_SEED,
                    "block_weeks": BLOCK_WEEKS},
        "code": dict(ei._LOADED_SHA, **own_code_shas()),
        "cache_code_provenance": (list(KNOWN_CACHE_PROVENANCE) if meta["phase1_sha256"] == KNOWN_CACHE_PHASE1_SHA256
                                  else meta.get("code") or "記録が無い"),
        "comparisons_per_multiplier": len(specs) - 1, "comparisons_total": (len(specs) - 1) * len(MULTIPLIERS),
        "python": sys.version.split()[0], "citation": [ei.CITATION_EN, ei.CITATION_JA],
    }
    files = {
        "models.tsv": models_tsv, "coefs.tsv": coefs_tsv, "signals.tsv": sig_tsv, "networks.tsv": net_tsv,
        "run.json": (json.dumps(run, ensure_ascii=False, sort_keys=True, indent=1) + "\n").encode("utf-8"),
    }
    files["summary.md"] = summary_md(run, evrows, specs, sig, netstat)
    for name, data in files.items():
        ei.check_public(name, data)
    return files


OUT_NAMES = ("models.tsv", "coefs.tsv", "signals.tsv", "networks.tsv", "run.json", "summary.md")
TABLE_NAMES = ("models.tsv", "coefs.tsv", "signals.tsv", "networks.tsv")


def write_outputs(out_dir, files):
    if sorted(files) != sorted(OUT_NAMES):
        raise SignalError("出力の名前が決めた一覧と違う")
    os.makedirs(out_dir, exist_ok=True)
    for n in OUT_NAMES:
        if os.path.lexists(os.path.join(out_dir, n)):
            raise SignalError("書き出す先に同じ名前のファイル（%s）がある。上書きしない" % n)
    return {n: write_new(os.path.join(out_dir, n), files[n]) for n in OUT_NAMES}


GROUP_JA = {"naive": "素朴な予測だけ", "s21": "2.1 隣の波", "s22": "2.2 先に届く波", "s23": "2.3 空白の形",
            "all": "三つすべて"}


def summary_md(run, evrows, specs, sig, netstat):
    L = []
    a = L.append
    md = ei.md_table
    a("# 三つの信号の探索（T-117、手法を作る期間）")
    a("")
    a("この文書は `src/stats/explore_signals.py` が出力したもので、手で書き足していない。数字はすべて、手法を作る期間の"
      "区画（%s〜%s）のデータだけから計算した。モデルの形・係数・作り方の選択肢・閾値・判定期間・V は、"
      "ここでは決めない（決定はオーナー）。" % (ei.BLOCK_START, ei.BLOCK_END))
    a("")
    a("## 0. 何をどう比べたか")
    a("- 予言日・対象・判定は T-115 と同じ（%d 回の月曜、一度跳ねたタグの扱いあり、判定期間 %d 日）。組み合わせは倍率 %s。"
      % (run["mondays"][0], HORIZON, "・".join(str(m) for m in MULTIPLIERS)))
    a("- 学習：予言日が %s 以前（判定期間が 2018 年の中で終わる）。検証：予言日が %s 以降。あいだの予言日は使わない。"
      % (TRAIN_LAST, TEST_FIRST))
    a("- 学習の行 %d、検証の行 %d（対象で、3つの倍率のどれも判定不能でないもの）。" % (
        run["split"]["train_rows"], run["split"]["test_rows"]))
    a("- モデル：naive.py の特徴量（7つ）だけのロジスティック回帰（naive.fit_rows。リッジ 1.0）と、それに信号の列を足したもの。"
      "信号の値が決まらない行は 0 とし、決まらないことを示す列（_miss）を足した。")
    a("- 指標（検証）：対数損失（小さいほど良い）、AUC、週ごとに確率の上位 %d 件に入った島の数の合計。"
      "素朴な予測との差のばらつきは、検証の週を %d 週ずつ束ねた単位（%d 個）と、1週ずつ（参考）の復元抽出（%d 回、乱数の種 %d）で、"
      "2.5%% と 97.5%% の点を出した。AUC の差のばらつきは計算の重さのため出していない。"
      % (TOP_K, BLOCK_WEEKS, run["test_blocks_4w"], BOOT_N, BOOT_SEED))
    a("- 同じ出来事で多くのタグが一緒に跳ね、毎週の判定期間が重なるので、行の数は独立な試行の数ではない。束ねた単位のばらつきを見る。")
    a("")
    a("## 1. 作り方の選択肢（集計の前にコードに書いたもの。決めない）")
    a("- 網（method.md 8章の未決事項1）：P1（V1 のテーマの組の文書の数）で、一覧のタグどうしの組。"
      "w12q＝直前の12か月・四半期ごとに更新、w12m＝直前の12か月・月ごとに更新、w3m＝直前の3か月・月ごとに更新。"
      "どれも、予言日を含む月（四半期）より前の月だけを足す。P2 は計算を縮めるため使わなかった。")
    a("- 隣（未決事項2）：組の文書の数が %d 以上の相手のうち、lift10＝lift の上位10、share30＝n_ij / n_i の上位30。"
      "重みはどちらも n_ij / n_i。1歩先だけ。" % MIN_PAIR_DOCS)
    a("- 先に届く波の単位（未決事項3）：国（最初の予言日より前の NC の上位 %d か国。C の行の max(v1_docs, v2_docs)）。"
      "**ここでの「国」は、記事が言及した場所（V1LOCATIONS の国の符号）で、報道した媒体の国ではない。**"
      "まとめ方は max（国ごとの上がりの最大 − 上位の国の合計の上がり）と frac2（直近の週の割合が過去52週の2倍を超えた国の割合）。"
      % TOP_COUNTRIES)
    if run["language_unit_computed"]:
        a("- 言語の単位も計算した。")
    else:
        a("- **言語の単位は計算できなかった**：日の集計の L・NL の行の言語の欄が、すべて「-」だった（言語が「-」でない行の数 %d）。"
          "翻訳の記事を使わない決定（案a）で、翻訳ストリームを読まないので、言語の別が日の集計に入っていないため。"
          "今のデータでは言語を単位にして測れない。" % run["lang_rows_not_dash"])
    a("- **そのため、2.2（s22）の結果は、方針書 2.2 の仮説（一部の国・言語の報道が先に扱い、全体が後から追う）を試したことにならない。**"
      "試したのは「記事が言及した場所ごとの報道量の上がり方の違い」である。")
    a("- 2.1 隣の波：隣の上がり（log((c+V)/(B+V)) の重み付き平均）と、隣の勢い（直近7日の平均とその前の7日の平均の比の対数の重み付き平均）。")
    a("- 2.3 空白の形：gap＝自分の上がり − 隣の上がり。expect＝log((c_i+V)/(期待値+V))、期待値 = 網の期間の自分の平均 × "
      "Σ s_ji c_j / Σ s_ji（網の期間の隣の平均）、s_ji = n_ij / n_j。")
    a("- 三つすべて（all）：網と隣ごとに、2.1 と、2.2 の国・max と、2.3 の gap を足したもの。")
    a("- 選択肢と結果を見た順（記録で確かめられることだけ）：コードの sha256 fb841994… の版で試しの phase2（try1）を流し、"
      "その結果を見たあとで、選択肢は変えずに、要約の文（「選択肢は phase1 の前にコードに書き、結果を見たあとで足したものは無い」という文と、"
      "網の周辺の数の一致の文）だけを足してコミットした"
      "（d23f0e2、sha256 e69ecd9e…）。本番の数字は try1 と同じだった。phase1 の前に、日の集計2日分の行の種類の数（L の言語がすべて「-」"
      "であることを含む）と、1か月のうち3日分の phase1 の時間を見た。それより前に試しがあったかどうかは、記録に無い。")
    if run.get("v1_docs_equal_c7_numerator_all_days") is True:
        a("- 網の周辺の数（テーマごとの V1 の文書の数）は、一覧のタグでは、すべての日で C7 の分子（v1_or_v2_docs）と一致した"
          "（V2 にだけ付く文書が、一覧のタグには無かった）。")
    elif run.get("v1_docs_equal_c7_numerator_all_days") is False:
        a("- 網の周辺の数（テーマごとの V1 の文書の数）は、C7 の分子（v1_or_v2_docs）と一致しない日がある。")
    a("")
    a("## 2. 結果（検証）")
    a("")
    for m in MULTIPLIERS:
        rows = [r for r in evrows if r["m"] == m]
        a("### 倍率 %d・判定期間 %d 日（検証の行 %d、島 %d）" % (m, HORIZON, rows[0]["n_test"], rows[0]["pos_test"]))
        a("")
        a(md([
            "モデル", "対数損失", "AUC", "上位%d の島" % TOP_K, "対数損失の差", "差の範囲（4週束ね）", "差の範囲（1週、参考）",
            "上位%d の差" % TOP_K, "上位の差の範囲（4週束ね）"],
            [(r["name"], f6(r["logloss"]), f6(r["auc"]), r["topk"], f6(r["d_logloss"]),
              "%s〜%s" % (f6(r["ll_b4"][0]), f6(r["ll_b4"][1])), "%s〜%s" % (f6(r["ll_b1"][0]), f6(r["ll_b1"][1])),
              r["d_topk"], "%.1f〜%.1f" % r["tk_b4"]) for r in rows]))
        a("")
        base = [r for r in rows if r["name"] == "naive"][0]["logloss"]

        def rel(r):
            return "%s（%+.2f%%）" % (r["name"], 100.0 * r["d_logloss"] / base)
        better = [rel(r) for r in rows if r["name"] != "naive" and r["ll_b4"][1] < 0]
        worse = [rel(r) for r in rows if r["name"] != "naive" and r["ll_b4"][0] > 0]
        best = min((r for r in rows if r["name"] != "naive"), key=lambda r: (r["d_logloss"], r["name"]))
        a("- 対数損失の差の範囲（4週束ね）が0より下に収まったモデル（カッコは素朴な予測の対数損失に対する差の割合）：%s。"
          % ("、".join(better) if better else "無い"))
        a("- 0より上に収まったモデル（素朴な予測より悪い）：%s。" % ("、".join(worse) if worse else "無い"))
        a("- 差の大きさ：最も下がったモデル（%s）でも、素朴な予測の対数損失の %.2f%%。" % (
            best["name"], 100.0 * -best["d_logloss"] / base))
        a("- この一覧の読み方：比べた数はこの倍率で %d（素朴な予測を除く）、3つの倍率で計 %d で、多重比較の補正をしていない。"
          "4週の束どうしは独立でない（判定期間 %d 日が隣の束に重なる。最後の束は %d 週）。範囲が0を含まないことは、"
          "信号が効くことの確かめにはならない。" % (len(rows) - 1, (len(rows) - 1) * len(MULTIPLIERS), HORIZON,
                                                   run["test_weeks"] - BLOCK_WEEKS * (run["test_blocks_4w"] - 1)))
        nc = [r["name"] for r in rows if not r["conv"]]
        if nc:
            a("- 収まらなかった推定：%s（naive.fit_logistic の100回で収まらなかった。結果は参考）。" % "、".join(nc))
        a("")
    a("差は「信号を足したモデル − 素朴な予測だけ」。対数損失の差が負なら信号を足した方が良く、上位の差が正なら信号を足した方が島を多く拾った。")
    a("")
    a("## 3. 信号の値（学習の行。値が決まった行だけ）")
    a("")
    a(md(["信号", "倍率", "学習の行", "値の有る行", "島（値の有る行）", "島の平均", "島でないものの平均"], sig))
    a("")
    a("網ごとの隣の数（対象の行あたり）：")
    a("")
    a(md(["網_隣", "対象の行", "隣の数の平均", "隣が無い行"],
         [(k, x, "%.2f" % (y / x), z) for k, (x, y, z) in sorted(netstat.items())]))
    a("")
    a("## 4. 予言の時点のデータだけを使ったことの確かめ")
    a("- 日の比率：予言日 t の入力は t-399〜t-1、判定は t+1〜t+28 の外を読むと止まる形で計算した。実際に読んだ日は %s〜%s。"
      % (run["daily_min_read"], run["daily_max_read"]))
    a("- 網：使うたびに網の最後の日 < t を確かめた。網の最後の日 − t の最大は %d 日。" % run["network_last_day_minus_t_max_days"])
    a("- 国別の週：使うたびに週の最後の日 < t を確かめた。週の最後の日 − t の最大は %d 日。"
      % run["country_week_last_day_minus_t_max_days"])
    a("- 国の単位は、最初の予言日より前（%s〜%s）の NC だけで決めた。" % (ei.BLOCK_START, COUNTRY_RULE_END))
    a("")
    a("## 5. 限界")
    a("- **一覧と V の先読み**：タグの一覧と V（= A）は、手法を作る期間の区画全体のデータで決まった（seq 17）。"
      "この期間では、予言の対象の範囲と V が t より後のデータに依る（T-116 の要約 6章）。信号の比べ方にもこの依存が入る。")
    a("- **除外の規則の漏れ**：TAX_WORLDLANGUAGES_*・TAX_FNCACT_* などの名前で、民族・人物の姓・宗教・犯罪・紛争・政治に当たる"
      "テーマが一覧に残っている（オーナーの決定 2026-10-16、(a) このまま進める）。網の隣にもこれらが入る。この要約にはテーマの名前を載せていない。")
    a("- **WB のテーマの段のような上昇**：2016年4月から WB のテーマの一部が段のように上がり、2017年に戻る（T-116 の要約 6章）。"
      "学習の期間（2016〜2018年）に入り、網と信号にも入る。報道かテーマの付け方の変化かは区別できない。")
    a("- 検証は1回の前後の分け方だけで、選択肢が多い（素朴な予測を除く %d 個のモデル × %d つの倍率 = %d の比べ方）。"
      "このほかに、組の文書の数の下限（%d）・国の数（%d）・国別の過去の週の数（%d）・学習と検証の区切りの日・指標の種類"
      "（対数損失・AUC・上位 %d）も選びうるもので、この数に入っていない。一番良く見えるものを選ぶと、偶然の良さを拾う。ここでは選ばない。"
      % (len(specs) - 1, len(MULTIPLIERS), (len(specs) - 1) * len(MULTIPLIERS), MIN_PAIR_DOCS, TOP_COUNTRIES,
         LEAD_BASE_WEEKS, TOP_K))
    a("- 網は月の単位でまとめたので、更新は月の初め（四半期の初め）だけで、予言日の前の数週は網に入らない。")
    a("- 国別の数は、テーマ×国の行の max(v1_docs, v2_docs) で、V1 と V2 の両方に付いた文書を1回と数える C7 とは数え方が違う。")
    a("")
    a("## 6. 再計算")
    a("```")
    a(".venv/bin/python -B src/stats/explore_signals.py phase1 --store <日の集計> --cache-dir <新しいフォルダ>")
    a(".venv/bin/python -B src/stats/explore_signals.py phase2 --cache-dir <同じフォルダ> --out-dir <書き出す先>")
    a("```")
    for k in sorted(run["code"]):
        a("- %s：sha256 %s" % (k, run["code"][k]))
    a("- キャッシュ phase1.json：sha256 %s" % run["phase1_sha256"])
    prov = run["cache_code_provenance"]
    if isinstance(prov, list):
        a("- キャッシュを作ったコードの版：")
        for x in prov:
            a("  - " + x)
    else:
        a("- キャッシュを作ったコードの版：%s" % (json.dumps(prov, ensure_ascii=False, sort_keys=True)
                                         if isinstance(prov, dict) else prov))
    a("")
    a("## 引用")
    a(ei.CITATION_EN)
    a("")
    a(ei.CITATION_JA)
    return ("\n".join(L) + "\n").encode("utf-8")


def main(argv=None):
    p = argparse.ArgumentParser(description="T-117 三つの信号の探索")
    sub = p.add_subparsers(dest="cmd", required=True)
    p1 = sub.add_parser("phase1")
    p1.add_argument("--store", required=True)
    p1.add_argument("--cache-dir", required=True)
    p1.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 1))
    p2 = sub.add_parser("phase2")
    p2.add_argument("--cache-dir", required=True)
    p2.add_argument("--out-dir", required=True)
    p2.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 1))
    a = p.parse_args(argv)
    t0 = time.time()

    def log(msg):
        sys.stderr.write("[%8.1f s] %s\n" % (time.time() - t0, msg))
        sys.stderr.flush()
    try:
        if a.cmd == "phase1":
            sha = phase1(ei.PROJECT, a.store, a.cache_dir, a.workers, log)
            print("%s  phase1.json" % sha)
        else:
            shas = phase2(ei.PROJECT, a.cache_dir, a.out_dir, a.workers, log)
            for n in OUT_NAMES:
                print("%s  %s" % (shas[n], n))
    except (SignalError, ei.ExploreError) as e:
        sys.stderr.write("止まった：%s\n" % e)
        return 1
    log("終わり")
    return 0


if __name__ == "__main__":
    sys.exit(main())
