#!/usr/bin/env python3
"""T-115：手法を作る期間の島を見る、記述の探索（試運転の手順4の最初の探索）。

封印済みの判定の定義（docs/stats/candidates.md 3章）と、封印済みのタグの一覧（封印の記録の seq 17、
stats-order5 の main.official.result）を、そのまま手法を作る期間（2015-03-02〜2020-12-14）に当てはめ、
予言日（2016-04-11〜2020-09-14 の月曜、232回）ごとに、対象のタグと、21の組み合わせ（倍率 7 × 判定期間 3）
それぞれの島を数える。閾値・判定期間・V を選んだり勧めたりはしない。

使う封印済みの関数（変えない。ファイルを1回だけ読み、sha256 を照らしてから、そのバイト列を compile して使う）
- src/stats/candidates.py：baseline_level・judge・smoothing_window_ends・_block_mean・combinations
- src/stats/scoring.py：target_status（中で current_level と recently_jumped を使う）・week_summary
- src/stats/counting.py：parse_day・candidate_counts（正式な数え方 C7）・day_file_name
- src/stats/periods.py：FROZEN_BLOCKS・compute_periods・prediction_dates
scoring.py は、封印の記録にまだ sha256 が載っていない（封印は順番6〜8の予定。naive-scoring.md）。
ここでは T-115 の割り振りの時点の版の sha256 を SCORING_SHA256 として固定して照らす。

入力（どれも照らしてから使う）
- 封印の記録 sealed/ledger.jsonl：鎖（正規の形・seq・prev_hash）を自分のコードで確かめる。
- seq 12（gkg-run-result）の中身：マニフェストの先頭 manifest_lines 行の sha256 を照らし、
  正式な run の day の行（区画の 2115 日ちょうど）を取る。
- 日の集計：day の行の file_name のファイルだけを O_NOFOLLOW で開き、sha256 を day の行と照らす。
  日付が区画の終わり（2020-12-14）より後の行は、一つでもあれば止まる（読まない）。
- seq 15（stats-order4）の中身：一覧の sha256 を list_sha256 と照らし、欠けた日（48日）と、日ごとの C7 の分母を取る。
  日の集計から数えた C7 の分母が、すべての日でこの値と同じことを確かめる。
- seq 17（stats-order5）の中身：main の sha256 を main_sha256 と照らし、正式な一覧（3587件）と A（V = A）を取る。

比率 r(d)：C7 の分子（テーマの v1_or_v2_docs）÷ C7 の分母（同じ欄の全テーマの和）。欠けた日は None。
Python の int ÷ int（正しく丸めた float）で計算する。

読む日の確かめ（予言の時点で入手できたデータだけを使うこと）
- タグの比率は、区画の日だけを持つ辞書に入れる。区画の外の日を読もうとすると止まる。
- 予言日 t の入力の計算（target_status と baseline_level）のあいだは、t-371〜t-1 の外を読むと止まる。
- 判定（judge と最大の7日の平均）のあいだは、t+1〜t+56 の外を読むと止まる。
- 実際に読んだ日の最小と最大を、出力の run.json に残す。

出力（Git の外の --out-dir に、新しいファイルとして書く。同じ名前があれば止まる）
  combos.tsv  weekly.tsv  week-status.tsv  weekly-clusters.tsv  top-weeks.tsv
  examples.tsv  examples-zero-baseline.tsv  families.tsv  judgment-windows.tsv  run.json  summary.md
中身は入力とコードだけで決まる（時刻・所要時間・置き場所のパスは入れない）。標準出力には、書いたファイルの
名前と sha256 だけを出す。標準エラーには、進み具合と所要時間を出す。

流し方（プロジェクトのルートで。TMPDIR は scratchpad の中に）
  .venv/bin/python -B src/stats/explore_islands.py --store <日の集計の置き場所> --out-dir <書き出す先>

Data: The GDELT Project (https://www.gdeltproject.org/). This project is not affiliated with or endorsed by the GDELT Project.
"""

import argparse
import datetime
import fractions
import hashlib
import json
import multiprocessing
import os
import re
import statistics
import sys
import time
import types

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(os.path.dirname(HERE))

LABEL = "explore-islands-t115-v1"

# 封印の記録で照らす sha256（periods・candidates は seq 2 の targets、counting は seq 6 の中身の files）
PERIODS_SHA256 = "81de229d065196a26e15d90c5a80eb1043ca534a6eaf66cdebd36285ae087605"
CANDIDATES_SHA256 = "21b5838782991596057be2fdffdeac596bf4548517ef077e5c4547a719512e89"
COUNTING_SHA256 = "6f25985b21cd8ac93680b81308f3d1860b4ae6496577e10141d1e17ecf8c9fd3"
# 封印の記録にはまだ無い（順番6〜8で封印の予定）。T-115 の割り振りの時点（コミット 5252d32）の版。
SCORING_SHA256 = "ae30815f5690bf3d9faaabcdb25cce821c8c627282620e1e705220f79a9a4300"

_LOADED_SHA = {}


class ExploreError(Exception):
    pass


def _load_verified(name, rel, want_sha, deps=()):
    """ファイルを1回だけ読み、sha256 を照らし、同じバイト列を compile/exec してモジュールにする。"""
    path = os.path.join(PROJECT, *rel.split("/"))
    with open(path, "rb") as f:
        data = f.read()
    sha = hashlib.sha256(data).hexdigest()
    if sha != want_sha:
        raise ExploreError("%s の sha256 が、照らす値と違う" % rel)
    _LOADED_SHA[rel] = sha
    mod = types.ModuleType(name)
    mod.__file__ = path
    saved = {n: sys.modules.get(n) for n, _m in deps}
    try:
        for n, m in deps:
            sys.modules[n] = m
        exec(compile(data, path, "exec", dont_inherit=True), mod.__dict__)
    finally:
        for n, old in saved.items():
            if old is None:
                sys.modules.pop(n, None)
            else:
                sys.modules[n] = old
    return mod


periods = _load_verified("periods", "src/stats/periods.py", PERIODS_SHA256)
candidates = _load_verified("candidates", "src/stats/candidates.py", CANDIDATES_SHA256,
                            deps=(("periods", periods),))
counting = _load_verified("counting", "src/stats/counting.py", COUNTING_SHA256)
scoring = _load_verified("scoring", "src/stats/scoring.py", SCORING_SHA256,
                         deps=(("candidates", candidates),))

ONE_DAY = datetime.timedelta(days=1)
F = fractions.Fraction

SEQ_GKG_RESULT = 12
SEQ_ORDER4 = 15
SEQ_ORDER5 = 17
SEQ_CANDIDATES = 2
SEQ_ORDER1B = 6
OFFICIAL_CID = "C7"

BLOCK_NAME = "method"
_BLOCKS = [b for b in periods.FROZEN_BLOCKS if b[0] == BLOCK_NAME]
BLOCK_START, BLOCK_END = _BLOCKS[0][1], _BLOCKS[0][2]
# 閾値を決める期間の始まり。これ以降の日付は読まない。
NEXT_BLOCK_START = BLOCK_END + ONE_DAY

COMBOS = candidates.combinations()          # (倍率, 判定期間) の21組。判定期間の短い順、倍率の小さい順
MAX_H = max(candidates.HORIZON_DAYS)
INPUT_LOOKBACK = candidates.BASELINE_WINDOW_DAYS + candidates.SMOOTHING_DAYS - 1   # 371
EXAMPLE_H = 28
EXAMPLE_MS = (2, 4, 8)
TOP_N = 10
TOP_WEEK_THEMES = 5
VARIANTS = ("cooldown", "no_cooldown")
VARIANT_JA = {"cooldown": "一度跳ねたタグの扱いあり（scoring.py）",
              "no_cooldown": "一度跳ねたタグの扱いなし（参考）"}
INCLUDED = {"cooldown": ("target",), "no_cooldown": ("target", "cooldown")}

CITATION_EN = ("Data: The GDELT Project (https://www.gdeltproject.org/). "
               "This project is not affiliated with or endorsed by the GDELT Project.")
CITATION_JA = ("データ出典：GDELT Project（https://www.gdeltproject.org/）。"
               "本プロジェクトは GDELT Project と提携・承認の関係にありません。")

EMAIL_RE = re.compile(rb"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+")
URL_RE = re.compile(rb"https?://[A-Za-z0-9./_%#?=&:;~+-]+")
ALLOWED_URLS = (b"https://www.gdeltproject.org/",)

OUT_NAMES = ("combos.tsv", "weekly.tsv", "week-status.tsv", "weekly-clusters.tsv", "top-weeks.tsv",
             "examples.tsv", "examples-zero-baseline.tsv", "families.tsv", "judgment-windows.tsv",
             "run.json", "summary.md")
# 名前の頭の部分ごとの表で、個別に示す頭の最低のタグ数（それより少ない頭は「その他」にまとめる）
FAMILY_MIN_TAGS = 20


def prediction_mondays():
    """手法を作る期間の予言日（periods.py の月曜）。232回、2016-04-11〜2020-09-14 であることを照らす。"""
    ps = [p for p in periods.compute_periods() if p["name"] == BLOCK_NAME]
    if len(ps) != 1 or (ps[0]["block_start"], ps[0]["block_end"]) != (BLOCK_START, BLOCK_END):
        raise ExploreError("periods の区画が FROZEN_BLOCKS と違う")
    ms = periods.prediction_dates(ps[0])
    if (len(ms), ms[0], ms[-1]) != (232, datetime.date(2016, 4, 11), datetime.date(2020, 9, 14)):
        raise ExploreError("予言日の範囲が、割り振りの値（232回、2016-04-11〜2020-09-14）と違う")
    if ms[0] - datetime.timedelta(days=INPUT_LOOKBACK) < BLOCK_START or \
            ms[-1] + datetime.timedelta(days=MAX_H) > BLOCK_END:
        raise ExploreError("予言日の読む範囲が区画をはみ出す")
    return ms


def block_days(start=None, end=None):
    start = BLOCK_START if start is None else start
    end = BLOCK_END if end is None else end
    out, d = [], start
    while d <= end:
        out.append(d)
        d += ONE_DAY
    return out


# ---------------------------------------------------------------------------
# 封印の記録と、その中身の照らし方
# ---------------------------------------------------------------------------

def sha256_hex(b):
    return hashlib.sha256(b).hexdigest()


def canonical_line(rec):
    return json.dumps(rec, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def verify_ledger(data):
    """封印の記録の鎖を確かめ、(記録の一覧, 各行の sha256 の一覧) を返す。"""
    if not data.endswith(b"\n"):
        raise ExploreError("封印の記録が改行で終わっていない")
    lines = data[:-1].split(b"\n")
    prev = "0" * 64
    records, hashes = [], []
    for i, line in enumerate(lines, 1):
        try:
            rec = json.loads(line.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            raise ExploreError("封印の記録の %d 行目が JSON でない" % i) from None
        if not isinstance(rec, dict) or canonical_line(rec) != line:
            raise ExploreError("封印の記録の %d 行目が正規の形でない" % i)
        if rec.get("seq") != i or rec.get("prev_hash") != prev:
            raise ExploreError("封印の記録の %d 行目の seq か prev_hash が鎖と合わない" % i)
        prev = sha256_hex(line)
        records.append(rec)
        hashes.append(prev)
    return records, hashes


def read_nofollow(path):
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    except OSError:
        raise ExploreError("ファイルを開けない：%s" % os.path.basename(path)) from None
    with os.fdopen(fd, "rb") as f:
        return f.read()


def target_of(rec, role):
    ts = [t for t in rec.get("targets") or [] if t.get("role") == role]
    if len(ts) != 1:
        raise ExploreError("seq %s の記録に role %s の対象がちょうど1つない" % (rec.get("seq"), role))
    return ts[0]


def read_sealed_json(root, rec, role):
    t = target_of(rec, role)
    path = t["path"]
    if not path.startswith("sealed/") or "/" in path[len("sealed/"):]:
        raise ExploreError("封印の対象のパスの形が違う")
    data = read_nofollow(os.path.join(root, path))
    if sha256_hex(data) != t["sha256"]:
        raise ExploreError("%s の sha256 が、封印の記録と違う" % path)
    return json.loads(data.decode("utf-8"))


def manifest_prefix(body, n):
    if not body.endswith(b"\n"):
        raise ExploreError("マニフェストが改行で終わっていない")
    lines = body[:-1].split(b"\n")
    if type(n) is not int or not 1 <= n <= len(lines):
        raise ExploreError("マニフェストの先頭 %r 行を取れない" % (n,))
    return b"".join(x + b"\n" for x in lines[:n])


def day_rows_from_manifest(prefix, run_id, days):
    """マニフェストの先頭から、正式な run の day の行を {日の文字列: 行} で返す。日は days とちょうど同じ。"""
    rows = {}
    for raw in prefix.split(b"\n"):
        if not raw.strip():
            continue
        r = json.loads(raw)
        if not isinstance(r, dict) or r.get("kind") != "day" or r.get("run_id") != run_id:
            continue
        d = r.get("day")
        if r.get("mode") != counting.OFFICIAL_MODE or not isinstance(d, str) or d in rows:
            raise ExploreError("正式な run の day の行の mode が違うか、同じ日が二つある")
        try:
            dd = datetime.date.fromisoformat(d)
        except ValueError:
            raise ExploreError("day の行の日の形が違う") from None
        if dd >= NEXT_BLOCK_START or dd < BLOCK_START:
            raise ExploreError("day の行に区画の外の日（%s）がある。読まずに止まる" % d)
        if r.get("file_name") != counting.day_file_name(counting.OFFICIAL_MODE, run_id, d):
            raise ExploreError("%s の file_name が決まった名前と違う" % d)
        if not (isinstance(r.get("sha256"), str) and re.fullmatch(r"[0-9a-f]{64}", r["sha256"])):
            raise ExploreError("%s の sha256 の形が違う" % d)
        rows[d] = r
    if sorted(rows) != [x.isoformat() for x in days]:
        raise ExploreError("day の行の日が、区画の日とちょうど同じでない")
    return rows


def order4_list_bytes(lst):
    return (json.dumps(lst, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")


def order5_main_bytes(main):
    return (json.dumps(main, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
            + "\n").encode("utf-8")


def check_order4(doc, run_id, gkg_doc, days):
    lst = doc.get("list")
    if not isinstance(lst, dict) or sha256_hex(order4_list_bytes(lst)) != doc.get("list_sha256"):
        raise ExploreError("順番4の一覧の sha256 が list_sha256 と違う")
    if lst.get("block") != {"name": BLOCK_NAME, "start": BLOCK_START.isoformat(), "end": BLOCK_END.isoformat()}:
        raise ExploreError("順番4の一覧の区画が違う")
    inp = lst.get("input") or {}
    if inp.get("run_id") != run_id or inp.get("gkg_run_result_seq") != SEQ_GKG_RESULT \
            or inp.get("manifest_sha256") != gkg_doc["manifest_sha256"]:
        raise ExploreError("順番4の一覧の入力が、seq 12 の run と違う")
    miss = [m["day"] for m in lst.get("missing_days") or []]
    if len(miss) != lst.get("missing_count") or len(set(miss)) != len(miss):
        raise ExploreError("順番4の一覧の欠けた日の数が合わない")
    missing = {datetime.date.fromisoformat(d) for d in miss}
    if any(not (BLOCK_START <= d <= BLOCK_END) for d in missing):
        raise ExploreError("順番4の一覧に区画の外の欠けた日がある")
    denom = lst.get("c7_denominator_by_day")
    if not isinstance(denom, dict) or sorted(denom) != [d.isoformat() for d in days]:
        raise ExploreError("順番4の一覧の C7 の分母が区画の日とそろわない")
    return missing, denom, lst


def check_order5(doc, hashes, order4_list_sha):
    main = doc.get("main")
    if not isinstance(main, dict) or sha256_hex(order5_main_bytes(main)) != doc.get("main_sha256"):
        raise ExploreError("順番5の main の sha256 が main_sha256 と違う")
    refs = main.get("refs") or {}
    if refs.get("gkg_run_result") != {"seq": SEQ_GKG_RESULT, "record_sha256": hashes[SEQ_GKG_RESULT - 1]}:
        raise ExploreError("順番5の main の参照（seq 12）が封印の記録の行と違う")
    o4 = refs.get("order4") or {}
    if (o4.get("seq"), o4.get("record_sha256"), o4.get("list_sha256")) != \
            (SEQ_ORDER4, hashes[SEQ_ORDER4 - 1], order4_list_sha):
        raise ExploreError("順番5の main の参照（seq 15）が封印の記録の行と違う")
    off = main.get("official") or {}
    res = off.get("result") or {}
    if off.get("official") is not True or off.get("candidate") != OFFICIAL_CID:
        raise ExploreError("順番5の main.official が C7 の正式な結果でない")
    if res.get("v_equals_a") is not True or main.get("a_equals_v") is not True:
        raise ExploreError("順番5の結果で V = A になっていない")
    a = F(res["a"])
    tags = list(res.get("tag_list") or [])
    if len(tags) != res.get("tag_count") or len(set(tags)) != len(tags) or tags != sorted(tags):
        raise ExploreError("順番5の正式な一覧の件数か並びが合わない")
    for t in tags:
        if not counting.THEME_NAME_RE.fullmatch(t):
            raise ExploreError("正式な一覧に、テーマの名前の形に合わない名前がある")
    return tags, a, main


def load_context(root):
    """封印の記録と、その中身を照らして読み、計算に要るものを返す。日の集計はまだ開かない。"""
    data = read_nofollow(os.path.join(root, "sealed", "ledger.jsonl"))
    records, hashes = verify_ledger(data)
    if len(records) < SEQ_ORDER5:
        raise ExploreError("封印の記録が seq 17 まで無い")
    kinds = {SEQ_CANDIDATES: "candidates", SEQ_ORDER1B: "stats-order1b", SEQ_GKG_RESULT: "gkg-run-result",
             SEQ_ORDER4: "stats-order4", SEQ_ORDER5: "stats-order5"}
    for s, k in kinds.items():
        if records[s - 1]["kind"] != k:
            raise ExploreError("seq %d の記録の kind が %s でない" % (s, k))
    # コードの sha256 を封印の記録と照らす
    r2 = records[SEQ_CANDIDATES - 1]
    if target_of(r2, "code") != {"path": "src/stats/candidates.py", "role": "code", "sha256": CANDIDATES_SHA256} \
            or target_of(r2, "import") != {"path": "src/stats/periods.py", "role": "import",
                                           "sha256": PERIODS_SHA256}:
        raise ExploreError("candidates.py か periods.py の sha256 が seq 2 と違う")
    d1b = read_sealed_json(root, records[SEQ_ORDER1B - 1], "stats-order1b")
    if {"path": "src/stats/counting.py", "sha256": COUNTING_SHA256} not in (d1b.get("files") or []):
        raise ExploreError("counting.py の sha256 が seq 6 と違う")
    if counting.OFFICIAL_CANDIDATE != OFFICIAL_CID:
        raise ExploreError("counting.py の正式な候補が C7 でない")
    # seq 12：マニフェストの先頭と day の行
    g = read_sealed_json(root, records[SEQ_GKG_RESULT - 1], "gkg-run-result")
    if g.get("mode") != "official":
        raise ExploreError("seq 12 が正式な run でない")
    mpath = g["manifest_path"]
    if mpath != "data/manifest/gdelt-gkg-method.jsonl":
        raise ExploreError("seq 12 のマニフェストのパスが違う")
    prefix = manifest_prefix(read_nofollow(os.path.join(root, *mpath.split("/"))), g["manifest_lines"])
    if sha256_hex(prefix) != g["manifest_sha256"]:
        raise ExploreError("マニフェストの先頭の sha256 が seq 12 と違う")
    days = block_days()
    rows = day_rows_from_manifest(prefix, g["run_id"], days)
    # seq 15・17
    o4 = read_sealed_json(root, records[SEQ_ORDER4 - 1], "stats-order4")
    missing, denom, lst = check_order4(o4, g["run_id"], g, days)
    o5 = read_sealed_json(root, records[SEQ_ORDER5 - 1], "stats-order5")
    tags, a, main = check_order5(o5, hashes, o4["list_sha256"])
    if sorted(main.get("missing_days", {}).get("days") or []) != sorted(d.isoformat() for d in missing):
        raise ExploreError("順番5の欠けた日が順番4の一覧と違う")
    return {
        "days": days, "rows": rows, "missing": missing, "denom": denom, "tags": tags, "v": a,
        "partial_days_count": lst.get("partial_days_count"),
        "refs": {
            "ledger_records": len(records),
            "seq12": {"record_sha256": hashes[SEQ_GKG_RESULT - 1], "run_id": g["run_id"],
                      "manifest_path": mpath, "manifest_lines": g["manifest_lines"],
                      "manifest_sha256": g["manifest_sha256"]},
            "seq15": {"record_sha256": hashes[SEQ_ORDER4 - 1], "list_sha256": o4["list_sha256"]},
            "seq17": {"record_sha256": hashes[SEQ_ORDER5 - 1], "main_sha256": o5["main_sha256"]},
        },
    }


# ---------------------------------------------------------------------------
# 日の集計を読む（子プロセス）
# ---------------------------------------------------------------------------

_W = {}


def _init_days(store, tags):
    _W["store"] = store
    _W["tags"] = tuple(tags)


def read_day(day, file_name, sha, store, tags):
    """日の集計を1つ開き、sha256 を照らし、C7 の (分母, 一覧のタグごとの分子) を返す。"""
    if os.path.basename(file_name) != file_name or file_name in ("", ".", ".."):
        raise ExploreError("ファイルの名前の形が違う")
    if datetime.date.fromisoformat(day) >= NEXT_BLOCK_START:
        raise ExploreError("区画の外の日を読もうとした")
    data = read_nofollow(os.path.join(store, file_name))
    if sha256_hex(data) != sha:
        raise ExploreError("%s：日の集計の sha256 が day の行と違う" % day)
    summary = counting.parse_day(data, expect_day=day, expect_mode=counting.OFFICIAL_MODE)
    del data
    counts, total = counting.candidate_counts(summary, OFFICIAL_CID)
    return total, [counts.get(t, 0) for t in tags]


def _read_day_task(args):
    day, file_name, sha = args
    total, vec = read_day(day, file_name, sha, _W["store"], _W["tags"])
    return day, total, vec


def load_ratios(ctx, store, workers, log=None):
    """日の集計を読み、タグごとの比率の列（区画の日の順。欠けた日は None）を返す。"""
    days, rows, tags = ctx["days"], ctx["rows"], ctx["tags"]
    tasks = [(d.isoformat(), rows[d.isoformat()]["file_name"], rows[d.isoformat()]["sha256"]) for d in days]
    totals, vecs = {}, {}
    if workers <= 1:
        _init_days(store, tags)
        it = map(_read_day_task, tasks)
        pool = None
    else:
        pool = multiprocessing.get_context("spawn").Pool(workers, initializer=_init_days, initargs=(store, tags))
        it = pool.imap(_read_day_task, tasks, chunksize=4)
    try:
        for i, (day, total, vec) in enumerate(it, 1):
            totals[day], vecs[day] = total, vec
            if log and i % 200 == 0:
                log("日の集計 %d / %d" % (i, len(tasks)))
    finally:
        if pool is not None:
            pool.close()
            pool.join()
    bad = [d for d in totals if totals[d] != ctx["denom"][d]]
    if bad:
        raise ExploreError("C7 の分母が順番4の一覧と違う日がある（%d 日、最初は %s）" % (len(bad), sorted(bad)[0]))
    series = [[] for _ in tags]
    for d in days:
        k = d.isoformat()
        if d in ctx["missing"]:
            for s in series:
                s.append(None)
            continue
        tot = totals[k]
        if tot <= 0:
            raise ExploreError("欠けた日でないのに C7 の分母が 0 の日がある")
        for s, n in zip(series, vecs[k]):
            s.append(n / tot)
    return series, len(tasks)


# ---------------------------------------------------------------------------
# タグごとの計算（子プロセス）
# ---------------------------------------------------------------------------

class ReadGuard:
    """日付 → 比率。区画の日だけを持ち、許す範囲の外を読もうとすると止まる。読んだ日の最小と最大を残す。"""

    def __init__(self, days, values):
        if len(days) != len(values):
            raise ExploreError("日と値の数が違う")
        self.vals = dict(zip(days, values))
        self.lo = self.hi = None
        self.min_read = self.max_read = None

    def allow(self, lo, hi):
        self.lo, self.hi = lo, hi

    def __call__(self, d):
        if not (self.lo <= d <= self.hi):
            raise ExploreError("許す範囲の外の日 %s を読もうとした" % d.isoformat())
        try:
            v = self.vals[d]
        except KeyError:
            raise ExploreError("区画の外の日 %s を読もうとした" % d.isoformat()) from None
        if self.min_read is None or d < self.min_read:
            self.min_read = d
        if self.max_read is None or d > self.max_read:
            self.max_read = d
        return v


def max_block_mean(get, t, horizon):
    """判定期間（t+1〜t+H）の中に収まる、欠けた日を含まない7日の平均の最大。無ければ None。"""
    best = None
    for end in candidates.smoothing_window_ends(t, horizon):
        m = candidates._block_mean(get, end)
        if m is not None and (best is None or m > best):
            best = m
    return best


def evaluate_tag(days, values, mondays, v):
    """1つのタグの、予言日ごとの (状態, B(t), 21組の判定, 判定期間 28 日の最大の7日の平均)。

    状態は scoring.target_status。対象になりうる状態（target と cooldown）のときだけ、B(t) と判定を計算する。
    戻り値：(予言日ごとの結果の list, 読んだ日の最小, 最大)
    """
    get = ReadGuard(days, values)
    out = []
    for t in mondays:
        get.allow(t - datetime.timedelta(days=INPUT_LOOKBACK), t - ONE_DAY)
        st = scoring.target_status(get, t, v)
        if st not in ("target", "cooldown"):
            out.append((st, None, None, None))
            continue
        b = candidates.baseline_level(get, t)
        get.allow(t + ONE_DAY, t + datetime.timedelta(days=MAX_H))
        js = tuple(candidates.judge(get, t, h, m, b, v) for m, h in COMBOS)
        mx = max_block_mean(get, t, EXAMPLE_H)
        out.append((st, b, js, mx))
    return out, get.min_read, get.max_read


def _init_tags(days, mondays, v):
    _W["days"], _W["mondays"], _W["v"] = days, mondays, v


def _eval_task(args):
    j, values = args
    return (j,) + evaluate_tag(_W["days"], values, _W["mondays"], _W["v"])


def evaluate_all(series, days, mondays, v, workers, log=None):
    tasks = list(enumerate(series))
    if workers <= 1:
        _init_tags(days, mondays, v)
        it = map(_eval_task, tasks)
        pool = None
    else:
        pool = multiprocessing.get_context("spawn").Pool(workers, initializer=_init_tags,
                                                         initargs=(days, mondays, v))
        it = pool.imap(_eval_task, tasks, chunksize=8)
    results = [None] * len(tasks)
    lo = hi = None
    try:
        for i, (j, res, a, b) in enumerate(it, 1):
            results[j] = res
            if a is not None:
                lo = a if lo is None or a < lo else lo
                hi = b if hi is None or b > hi else hi
            if log and i % 500 == 0:
                log("タグ %d / %d" % (i, len(tasks)))
    finally:
        if pool is not None:
            pool.close()
            pool.join()
    return results, lo, hi


# ---------------------------------------------------------------------------
# 集計
# ---------------------------------------------------------------------------

def ratio_of(b, mx):
    """倍率（最大の7日の平均 ÷ B(t)）。B(t) = 0 なら None。"""
    if mx is None or b is None or b == 0:
        return None
    return mx / b


def family(name):
    """テーマの名前の頭の部分。TAX_ で始まる名前は2つ目の語まで（TAX_FNCACT など）、ほかは最初の語。"""
    parts = name.split("_")
    if parts[0] == "TAX" and len(parts) > 1:
        return "TAX_" + parts[1]
    return parts[0]


def window_missing_rows(mondays, missing):
    """判定期間に欠けた日がかかる予言日：(判定期間, 予言日, 使える7日のまとまりの数, まとまりの数)。
    欠けた日だけで決まり、タグに依らない。"""
    out = []
    for h in candidates.HORIZON_DAYS:
        for t in mondays:
            ends = candidates.smoothing_window_ends(t, h)
            usable = sum(1 for e in ends
                         if not any((e - datetime.timedelta(days=k)) in missing
                                    for k in range(candidates.SMOOTHING_DAYS)))
            if usable < len(ends):
                out.append((h, t.isoformat(), usable, len(ends)))
    return out


def aggregate(tags, results, mondays):
    """全体の数を作る。results[j][i] = (状態, B, 判定の tuple, 最大の7日の平均)。"""
    nc = len(COMBOS)
    years = sorted({t.year for t in mondays})
    # weekly[v][c][i] = [対象（判定できたもの）, 島, 判定不能]
    weekly = {v: [[[0, 0, 0] for _ in mondays] for _ in range(nc)] for v in VARIANTS}
    distinct = {v: [set() for _ in range(nc)] for v in VARIANTS}
    distinct_year = {v: [{y: set() for y in years} for _ in range(nc)] for v in VARIANTS}
    statuses = [{} for _ in mondays]
    islands_of = {}   # 冷却あり、例の組み合わせ：{c: [(タグ, i, B, 最大)]}
    week_islands = {v: {} for v in VARIANTS}   # 冷却あり：{c: {i: [(タグ, B, 最大)]}}
    fam_tags = {}
    for tag in tags:
        fam_tags[family(tag)] = fam_tags.get(family(tag), 0) + 1
    # 冷却あり：fam[c][頭] = [対象, 島, 島になったタグの集合]
    fam = [{f: [0, 0, set()] for f in fam_tags} for _ in range(nc)]
    ex_idx = [COMBOS.index((m, EXAMPLE_H)) for m in EXAMPLE_MS]
    for c in ex_idx:
        islands_of[c] = []
        week_islands["cooldown"][c] = {}
    for j, tag in enumerate(tags):
        for i, (st, b, js, mx) in enumerate(results[j]):
            statuses[i][tag] = st
            if js is None:
                continue
            for v in VARIANTS:
                if st not in INCLUDED[v]:
                    continue
                y = mondays[i].year
                for c in range(nc):
                    r = js[c]
                    w = weekly[v][c][i]
                    if r is None:
                        w[2] += 1
                        continue
                    w[0] += 1
                    if v == "cooldown":
                        fam[c][family(tag)][0] += 1
                        if r:
                            fam[c][family(tag)][1] += 1
                            fam[c][family(tag)][2].add(tag)
                    if r:
                        w[1] += 1
                        distinct[v][c].add(tag)
                        distinct_year[v][c][y].add(tag)
                        if v == "cooldown" and c in islands_of:
                            islands_of[c].append((tag, i, b, mx))
                            week_islands[v][c].setdefault(i, []).append((tag, b, mx))
    # 表の検査：同じ判定期間では対象の件数が倍率に依らず、島の件数は倍率について増えない
    for v in VARIANTS:
        for h in candidates.HORIZON_DAYS:
            cs = [COMBOS.index((m, h)) for m in candidates.THRESHOLD_MULTIPLIERS]
            for i in range(len(mondays)):
                tg = {(weekly[v][c][i][0] + weekly[v][c][i][2], weekly[v][c][i][2]) for c in cs}
                if len(tg) != 1:
                    raise ExploreError("同じ判定期間で対象の件数が倍率によって違う")
                isl = [weekly[v][c][i][1] for c in cs]
                if any(a < b for a, b in zip(isl, isl[1:])):
                    raise ExploreError("倍率が大きいほうが島の件数が多い")
    return {"weekly": weekly, "distinct": distinct, "distinct_year": distinct_year, "statuses": statuses,
            "islands_of": islands_of, "week_islands": week_islands, "years": years,
            "fam": fam, "fam_tags": fam_tags}


def pct(num, den):
    if den == 0:
        return "-"
    return "%.2f" % (100.0 * num / den)


def combo_rows(agg, mondays):
    """combos.tsv の行：(変種, 倍率, 判定期間, 年, 週の数, 対象, 島, 判定不能, 割合%, 島になったタグの種類)。"""
    out = []
    for v in VARIANTS:
        for c, (m, h) in enumerate(COMBOS):
            w = agg["weekly"][v][c]
            for y in ["all"] + agg["years"]:
                idx = [i for i, t in enumerate(mondays) if y == "all" or t.year == y]
                tg = sum(w[i][0] for i in idx)
                isl = sum(w[i][1] for i in idx)
                und = sum(w[i][2] for i in idx)
                kinds = len(agg["distinct"][v][c]) if y == "all" else len(agg["distinct_year"][v][c][y])
                out.append((v, m, h, str(y), len(idx), tg, isl, und, pct(isl, tg), kinds))
    return out


def nearest_rank(sorted_xs, q):
    """最近順位法の分位点（q は 0〜1）。"""
    if not sorted_xs:
        return None
    k = max(1, -(-len(sorted_xs) * q // 1))
    return sorted_xs[int(k) - 1]


def cluster_rows(agg, mondays):
    """weekly-clusters.tsv：冷却ありの、組み合わせごとの週の島の数の分布。"""
    out = []
    n_top = -(-len(mondays) // 10)   # 上位10%の週の数（切り上げ）
    for c, (m, h) in enumerate(COMBOS):
        w = agg["weekly"]["cooldown"][c]
        weeks = [i for i in range(len(mondays)) if w[i][0] > 0]
        isl = [w[i][1] for i in weeks]
        s = sorted(isl)
        total = sum(isl)
        top = sorted(isl, reverse=True)[:n_top]
        imax = max(weeks, key=lambda i: (w[i][1], -i)) if weeks else None
        out.append((m, h, len(weeks), total, "%.2f" % (total / len(weeks)) if weeks else "-",
                    statistics.median(s) if s else "-", nearest_rank(s, 0.9), s[-1] if s else "-",
                    mondays[imax].isoformat() if imax is not None else "-",
                    sum(1 for x in isl if x == 0), n_top, pct(sum(top), total)))
    return out


def theme_order_key(item):
    """週の中のテーマの並び：倍率の大きい順（B(t) = 0 は先頭で、最大の7日の平均の大きい順）、同じなら名前。"""
    tag, b, mx = item
    r = ratio_of(b, mx)
    return (0, -mx, tag) if r is None else (1, -r, tag)


def top_week_rows(agg, mondays):
    """top-weeks.tsv：例の3つの組み合わせで、島の数の多い週の上位10。"""
    out = []
    for m in EXAMPLE_MS:
        c = COMBOS.index((m, EXAMPLE_H))
        w = agg["weekly"]["cooldown"][c]
        order = sorted(range(len(mondays)), key=lambda i: (-w[i][1], i))[:TOP_N]
        for rank, i in enumerate(order, 1):
            items = sorted(agg["week_islands"]["cooldown"][c].get(i, []), key=theme_order_key)
            names = ",".join(x[0] for x in items[:TOP_WEEK_THEMES])
            out.append((m, EXAMPLE_H, rank, mondays[i].isoformat(), w[i][0], w[i][1], pct(w[i][1], w[i][0]), names))
    return out


def family_rows(agg):
    """families.tsv：冷却ありの、頭ごと・組み合わせごとの (頭, 一覧のタグ数, 倍率, 判定期間, 対象, 島, 割合, 島になったタグの種類)。"""
    out = []
    for f in sorted(agg["fam_tags"]):
        for c, (m, h) in enumerate(COMBOS):
            tg, isl, kinds = agg["fam"][c][f]
            out.append((f, agg["fam_tags"][f], m, h, tg, isl, pct(isl, tg), len(kinds)))
    return out


def fmt_float(x):
    return "%.6e" % x


def example_rows(agg, mondays):
    """examples.tsv：例の組み合わせ・年ごとに、倍率の大きい順の上位10（B(t) > 0 のもの）。
    examples-zero-baseline.tsv：B(t) = 0 の島の、組み合わせ・年ごとの件数と、最大の7日の平均の大きい順の上位10。"""
    ex, zero = [], []
    for m in EXAMPLE_MS:
        c = COMBOS.index((m, EXAMPLE_H))
        isl = agg["islands_of"][c]
        for y in agg["years"]:
            pos = [(ratio_of(b, mx), tag, i, b, mx) for tag, i, b, mx in isl
                   if mondays[i].year == y and b > 0]
            pos.sort(key=lambda r: (-r[0], r[1], r[2]))
            for rank, (r, tag, i, b, mx) in enumerate(pos[:TOP_N], 1):
                ex.append((m, EXAMPLE_H, y, rank, tag, mondays[i].isoformat(), fmt_float(b), fmt_float(mx),
                           "%.2f" % r))
            z = [(tag, i, mx) for tag, i, b, mx in isl if mondays[i].year == y and b == 0]
            z.sort(key=lambda r: (-r[2], r[0], r[1]))
            zero.append((m, EXAMPLE_H, y, "count", len(z), "", "", ""))
            for rank, (tag, i, mx) in enumerate(z[:TOP_N], 1):
                zero.append((m, EXAMPLE_H, y, "top", rank, tag, mondays[i].isoformat(), fmt_float(mx)))
    return ex, zero


def week_status_rows(agg, mondays):
    out = []
    for i, t in enumerate(mondays):
        s = scoring.week_summary(agg["statuses"][i])
        cnt = s["status_counts"]
        out.append((t.isoformat(), s["week_kind"]) + tuple(cnt[k] for k in scoring.STATUSES))
    return out


def weekly_rows(agg, mondays):
    out = []
    for v in VARIANTS:
        for c, (m, h) in enumerate(COMBOS):
            for i, t in enumerate(mondays):
                w = agg["weekly"][v][c][i]
                out.append((v, m, h, t.isoformat(), w[0], w[1], w[2]))
    return out


def tsv(header, rows):
    lines = ["\t".join(header)] + ["\t".join(str(x) for x in r) for r in rows]
    return ("\n".join(lines) + "\n").encode("utf-8")


# ---------------------------------------------------------------------------
# 要約（Markdown）
# ---------------------------------------------------------------------------

def md_table(header, rows):
    out = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    for r in rows:
        out.append("| " + " | ".join(str(x) for x in r) + " |")
    return "\n".join(out)


def summary_md(meta, crow, clus, topw, ex, zero, wstat, mondays, years, frows, wmiss):
    L = []
    a = L.append
    a("# 手法を作る期間の島（T-115、記述の探索）")
    a("")
    a("この文書は `src/stats/explore_islands.py` が出力したもので、手で書き足していない。数字はすべて、"
      "手法を作る期間の区画（%s〜%s）のデータだけから計算した。閾値・判定期間・V を選んだり勧めたりはしない"
      "（閾値と判定期間は、閾値を決める期間で封印済みの規則で選ぶ）。" % (BLOCK_START, BLOCK_END))
    a("")
    a("## 0. 何をどう数えたか")
    a("- タグの一覧：封印の記録の seq 17 の正式な一覧（%d 件）。V = A = %s（約 %.4e）。" % (
        meta["tag_count"], meta["v"], float(F(meta["v"]))))
    a("- 比率：正式な数え方 C7（分子はテーマの v1_or_v2_docs、分母は同じ欄の全テーマの和）。欠けた日（seq 15、%d 日）は値なし。"
      % meta["missing_days"])
    a("- 予言日：%s〜%s の月曜 %d 回。予言日 t の入力は t-1 以前だけ、判定は t+1〜t+H（candidates.md 2章・3章）。"
      % (mondays[0], mondays[-1], len(mondays)))
    a("- 計算は封印済みの関数をそのまま使った：candidates.py の baseline_level・judge、scoring.py の target_status"
      "（中で current_level と、一度跳ねたタグの扱い recently_jumped を使う）。")
    a("- 対象：target_status が target のタグ（一度跳ねたタグの扱いあり）。参考として、cooldown も含めた場合"
      "（扱いなし。対象の条件は is_target と同じ）も並べる。**正式な扱いは「あり」で、「なし」は参考。**")
    a("- 判定不能（判定期間の中の7日のまとまりがすべて欠けた日を含む）は、対象の数にも島の数にも入れず、別に数える。")
    a("- 割合 = 島の数 ÷ 対象の数。年は予言日の年（2016年は4月から、2020年は9月まで）。")
    a("- 1つのタグは毎週の予言で何度も数える。判定期間が重なり、一つの出来事で複数のタグが跳ねるので、"
      "件数は独立な試行の数ではない。")
    a("")
    a("## 1. 組み合わせごとの対象と島")
    a("")
    for v in VARIANTS:
        a("### %s" % VARIANT_JA[v])
        a("")
        rows = [r for r in crow if r[0] == v and r[3] == "all"]
        a(md_table(["倍率", "判定期間（日）", "対象", "島", "割合（%）", "判定不能", "島になったタグの種類"],
                   [(r[1], r[2], r[5], r[6], r[8], r[7], r[9]) for r in rows]))
        a("")
        a("年ごとの割合（%）と、カッコ内は島の数：")
        a("")
        hdr = ["倍率", "判定期間（日）"] + [str(y) for y in years]
        body = []
        for m, h in COMBOS:
            cells = []
            for y in years:
                r = [x for x in crow if x[0] == v and x[1] == m and x[2] == h and x[3] == str(y)][0]
                cells.append("%s (%d)" % (r[8], r[6]))
            body.append([m, h] + cells)
        a(md_table(hdr, body))
        a("")
        a("年ごとの対象の数（どの倍率でも同じ）：")
        a("")
        body = []
        for h in candidates.HORIZON_DAYS:
            cells = []
            for y in years:
                r = [x for x in crow if x[0] == v and x[1] == 2 and x[2] == h and x[3] == str(y)][0]
                cells.append(r[5])
            body.append([h] + cells)
        a(md_table(["判定期間（日）"] + [str(y) for y in years], body))
        a("")
    a("## 2. 同じ週に多くのタグが一緒に跳ねた様子（一度跳ねたタグの扱いあり）")
    a("")
    a("対象が1件以上ある週について、週ごとの島の数の分布。90%%点は最近順位法。"
      "「上位10%%の週の占める割合」は、島の数の多い順に上位 %d 週の島が、全体の島の何%%かを示す。" % clus[0][10])
    a("")
    a(md_table(["倍率", "判定期間（日）", "週の数", "島の合計", "週の平均", "中央値", "90%点", "最大",
                "最大の週", "島0の週", "上位10%の週の占める割合（%）"],
               [(r[0], r[1], r[2], r[3], r[4], r[5], r[6], r[7], r[8], r[9], r[11]) for r in clus]))
    a("")
    first = [r for r in clus if r[8] == mondays[0].isoformat()]
    a("- 島の数が最大の週が最初の予言日（%s）である組み合わせ：21組のうち %d 組。" % (mondays[0], len(first)))
    a("")
    a("島の数の多かった週の上位10（判定期間 %d 日）。テーマは、その週の島のうち倍率の大きい順の最大 %d 件"
      "（B(t) = 0 のものは先頭）。" % (EXAMPLE_H, TOP_WEEK_THEMES))
    a("")
    for m in EXAMPLE_MS:
        a("倍率 %d：" % m)
        a("")
        a(md_table(["順位", "予言日", "対象", "島", "割合（%）", "テーマ（上位）"],
                   [(r[2], r[3], r[4], r[5], r[6], r[7].replace(",", ", ")) for r in topw if r[0] == m]))
        a("")
    a("## 3. どんな島か：テーマの名前の頭の部分ごと（一度跳ねたタグの扱いあり、判定期間 %d 日）" % EXAMPLE_H)
    a("")
    a("頭の部分は、TAX_ で始まる名前は2つ目の語まで（TAX_FNCACT など）、ほかは最初の語（WB など）。"
      "一覧のタグが %d 件以上の頭を個別に示し、ほかは「その他」にまとめる。全部の頭と21組は families.tsv。"
      % FAMILY_MIN_TAGS)
    a("")
    hdr = ["頭", "一覧のタグ数", "対象"] + ["倍率 %d の島（割合%%）" % m for m in EXAMPLE_MS]
    body = []
    big = sorted((f for f, n in meta["fam_tags"].items() if n >= FAMILY_MIN_TAGS),
                 key=lambda f: (-meta["fam_tags"][f], f))
    small = sorted(f for f, n in meta["fam_tags"].items() if n < FAMILY_MIN_TAGS)

    def cells(fs):
        n = sum(meta["fam_tags"][f] for f in fs)
        tg = None
        out = []
        for m in EXAMPLE_MS:
            rows = [r for r in frows if r[0] in fs and r[2] == m and r[3] == EXAMPLE_H]
            t = sum(r[4] for r in rows)
            i = sum(r[5] for r in rows)
            tg = t
            out.append("%d (%s)" % (i, pct(i, t)))
        return [n, tg] + out
    for f in big:
        body.append([f] + cells({f}))
    if small:
        body.append(["その他（%d 種類の頭）" % len(small)] + cells(set(small)))
    body.append(["合計"] + cells(set(meta["fam_tags"])))
    a(md_table(hdr, body))
    a("")
    a("## 4. 代表的な島の例（一度跳ねたタグの扱いあり、判定期間 %d 日）" % EXAMPLE_H)
    a("")
    a("倍率 = 判定期間の中の最大の7日の平均 ÷ B(t)。B(t) > 0 の島だけを並べる（B(t) = 0 の島は倍率が決まらないので、"
      "件数を別に示す）。同じタグが続く週に何度も出るのは、判定期間が重なるため。")
    a("")
    for m in EXAMPLE_MS[1:]:
        same = all([r[3:] for r in ex if r[0] == m and r[2] == y] ==
                   [r[3:] for r in ex if r[0] == EXAMPLE_MS[0] and r[2] == y] for y in years)
        rs = [float(r[8]) for r in ex if r[0] == EXAMPLE_MS[0]]
        a("- 倍率 %d の表は、倍率 %d の表と%s。" % (
            m, EXAMPLE_MS[0], "すべての年で同じ（倍率 %d の表に並ぶ倍率の最小は %.2f）" % (EXAMPLE_MS[0], min(rs))
            if same and rs else "違う年がある"))
    a("")
    for m in EXAMPLE_MS:
        for y in years:
            rows = [r for r in ex if r[0] == m and r[2] == y]
            zc = [r for r in zero if r[0] == m and r[2] == y and r[3] == "count"][0][4]
            a("倍率 %d、%d年（B(t) = 0 の島 %d 件）：" % (m, y, zc))
            a("")
            if rows:
                a(md_table(["順位", "テーマ", "予言日", "B(t)", "最大の7日の平均", "倍率"],
                           [(r[3], r[4], r[5], r[6], r[7], r[8]) for r in rows]))
            else:
                a("（なし）")
            a("")
    a("## 5. データの状態")
    a("")
    kinds = {}
    for r in wstat:
        kinds[r[1]] = kinds.get(r[1], 0) + 1
    a("- 日の集計：%d 日分を読み、すべて day の行の sha256 と一致した。C7 の分母は、すべての日で seq 15 の値と一致した。"
      % meta["day_files_read"])
    a("- 欠けた日：%d 日（seq 15）。一部が欠けた日（72本以上96本未満）：%d 日。" % (
        meta["missing_days"], meta["partial_days_count"]))
    a("- 週の種類（scoring.week_summary）：" + "、".join("%s %d 週" % (k, kinds[k]) for k in sorted(kinds)) + "。")
    a("- 読んだ日の範囲（計算の中で実際に読んだ日）：%s〜%s。予言日 t の入力の計算では t-371〜t-1 の外、"
      "判定では t+1〜t+56 の外を読むと止まる形で計算した。" % (meta["min_read"], meta["max_read"]))
    by_h = {}
    for h, t, u, n in wmiss:
        by_h.setdefault(h, []).append((t, u, n))
    for h in candidates.HORIZON_DAYS:
        rs = by_h.get(h, [])
        if rs:
            a("- 判定期間 %d 日：判定期間に欠けた日がかかる予言日 %d 回（%s〜%s）。使える7日のまとまりの数の最小は %d / %d"
              "（判定不能は、使えるまとまりが0の予言だけ）。一覧は judgment-windows.tsv。"
              % (h, len(rs), rs[0][0], rs[-1][0], min(r[1] for r in rs), rs[0][2]))
        else:
            a("- 判定期間 %d 日：判定期間に欠けた日がかかる予言日は無い。" % h)
    a("")
    a("週ごとの状態の数（上位は対象の少ない週）：")
    a("")
    low = sorted(wstat, key=lambda r: (r[2], r[0]))[:10]
    a(md_table(["予言日", "週の種類"] + list(scoring.STATUSES), low))
    a("")
    a("## 6. 限界")
    a("- テーマの名前はデータ源の区分の名前で、出来事の名前ではない。同じ週に跳ねたタグが同じ出来事によるものかは、"
      "このデータからは確かめていない。")
    a("- V は比率で固定されている。全体の報道量が年によって違えば、同じ V が別の件数に当たる（tags-naive.md 1章 (2)）。")
    a("- 一覧は手法を作る期間の全体にわたって存在するテーマだけで、期間の途中で生まれたテーマは入っていない。")
    a("- これは記述の探索で、どの組み合わせを使うかの判断の材料にはしない。")
    a("")
    a("## 7. 再計算")
    a("```")
    a(".venv/bin/python -B src/stats/explore_islands.py --store <日の集計の置き場所> --out-dir <書き出す先>")
    a("```")
    a("- コード：src/stats/explore_islands.py（sha256 %s）" % meta["code"]["src/stats/explore_islands.py"])
    for k in sorted(meta["code"]):
        if k != "src/stats/explore_islands.py":
            a("- %s：sha256 %s" % (k, meta["code"][k]))
    a("")
    a("## 引用")
    a(CITATION_EN)
    a("")
    a(CITATION_JA)
    return ("\n".join(L) + "\n").encode("utf-8")


# ---------------------------------------------------------------------------
# 出力
# ---------------------------------------------------------------------------

def check_public(name, data):
    """メールアドレスの形の文字列と、引用以外の URL が無いこと。"""
    if EMAIL_RE.search(data):
        raise ExploreError("%s にメールアドレスの形の文字列がある" % name)
    for u in URL_RE.findall(data):
        if u not in ALLOWED_URLS:
            raise ExploreError("%s に引用以外の URL がある" % name)


def build_outputs(ctx, results, mondays, min_read, max_read, day_files_read):
    agg = aggregate(ctx["tags"], results, mondays)
    crow = combo_rows(agg, mondays)
    clus = cluster_rows(agg, mondays)
    topw = top_week_rows(agg, mondays)
    ex, zero = example_rows(agg, mondays)
    wstat = week_status_rows(agg, mondays)
    frows = family_rows(agg)
    wmiss = window_missing_rows(mondays, ctx["missing"])
    with open(os.path.abspath(__file__), "rb") as f:
        own = sha256_hex(f.read())
    code = dict(_LOADED_SHA)
    code["src/stats/explore_islands.py"] = own
    meta = {
        "label": LABEL, "tag_count": len(ctx["tags"]), "v": "%d/%d" % (ctx["v"].numerator, ctx["v"].denominator),
        "missing_days": len(ctx["missing"]), "partial_days_count": ctx["partial_days_count"],
        "day_files_read": day_files_read, "day_files_sha256_checked": True, "c7_denominators_match_seq15": True,
        "block": [BLOCK_START.isoformat(), BLOCK_END.isoformat()],
        "mondays": [len(mondays), mondays[0].isoformat(), mondays[-1].isoformat()],
        "min_read": min_read.isoformat() if min_read else None,
        "max_read": max_read.isoformat() if max_read else None,
        "refs": ctx["refs"], "code": code, "combos": [list(x) for x in COMBOS],
        "python": sys.version.split()[0], "fam_tags": agg["fam_tags"],
        "citation": [CITATION_EN, CITATION_JA],
    }
    files = {
        "combos.tsv": tsv(("variant", "multiplier", "horizon_days", "year", "weeks", "targets", "islands",
                           "undecidable", "island_rate_percent", "distinct_island_tags"), crow),
        "weekly.tsv": tsv(("variant", "multiplier", "horizon_days", "monday", "targets", "islands", "undecidable"),
                          weekly_rows(agg, mondays)),
        "week-status.tsv": tsv(("monday", "week_kind") + scoring.STATUSES, wstat),
        "weekly-clusters.tsv": tsv(("multiplier", "horizon_days", "weeks_with_targets", "islands_total",
                                    "mean_per_week", "median", "p90_nearest_rank", "max", "max_week",
                                    "weeks_with_zero", "top_weeks_n", "top10pct_weeks_share_percent"), clus),
        "top-weeks.tsv": tsv(("multiplier", "horizon_days", "rank", "monday", "targets", "islands",
                              "island_rate_percent", "top_themes"), topw),
        "examples.tsv": tsv(("multiplier", "horizon_days", "year", "rank", "theme", "monday", "baseline",
                             "max_7day_mean", "ratio"), ex),
        "examples-zero-baseline.tsv": tsv(("multiplier", "horizon_days", "year", "row", "count_or_rank", "theme",
                                           "monday", "max_7day_mean"), zero),
        "run.json": (json.dumps(meta, ensure_ascii=False, sort_keys=True, indent=1) + "\n").encode("utf-8"),
        "families.tsv": tsv(("family", "tags_in_list", "multiplier", "horizon_days", "targets", "islands",
                             "island_rate_percent", "distinct_island_tags"), frows),
        "judgment-windows.tsv": tsv(("horizon_days", "monday", "usable_blocks", "blocks"), wmiss),
        "summary.md": summary_md(meta, crow, clus, topw, ex, zero, wstat, mondays, agg["years"], frows, wmiss),
    }
    if sorted(files) != sorted(OUT_NAMES):
        raise ExploreError("出力の名前が決めた一覧と違う")
    for n, d in files.items():
        check_public(n, d)
    return files


def write_outputs(out_dir, files):
    os.makedirs(out_dir, exist_ok=True)
    for n in OUT_NAMES:
        if os.path.lexists(os.path.join(out_dir, n)):
            raise ExploreError("書き出す先に同じ名前のファイル（%s）がある。上書きしない" % n)
    shas = {}
    for n in OUT_NAMES:
        fd = os.open(os.path.join(out_dir, n), os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o644)
        with os.fdopen(fd, "wb") as f:
            f.write(files[n])
        shas[n] = sha256_hex(files[n])
    return shas


def run(root, store, out_dir, workers, log=None):
    mondays = prediction_mondays()
    ctx = load_context(root)
    series, nread = load_ratios(ctx, store, workers, log)
    results, lo, hi = evaluate_all(series, ctx["days"], mondays, ctx["v"], workers, log)
    files = build_outputs(ctx, results, mondays, lo, hi, nread)
    return write_outputs(out_dir, files)


def main(argv=None):
    p = argparse.ArgumentParser(description="T-115 手法を作る期間の島の記述の探索")
    p.add_argument("--store", required=True)
    p.add_argument("--out-dir", required=True)
    p.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 1))
    a = p.parse_args(argv)
    t0 = time.time()

    def log(msg):
        sys.stderr.write("[%7.1f s] %s\n" % (time.time() - t0, msg))
        sys.stderr.flush()
    try:
        shas = run(PROJECT, a.store, a.out_dir, a.workers, log)
    except ExploreError as e:
        sys.stderr.write("止まった：%s\n" % e)
        return 1
    for n in OUT_NAMES:
        print("%s  %s" % (shas[n], n))
    log("終わり")
    return 0


if __name__ == "__main__":
    sys.exit(main())
