#!/usr/bin/env python3
"""順番4：手法を作る期間の区画の、欠けた日の一覧（T-087、T-089 で作り直し）。
文書は docs/stats/missing-days-method.md。

規則は docs/stats/candidates.md 3章 (5)（seq 2 で封印済み）。判定は candidates.day_is_missing() を使う。
  - 取得できたファイル（present_slots）= マニフェストの day の行の files_ok
  - 取得できたファイルから数えた全体の報道量（total_volume）= その日の正式な数え方 C7 の分母
    （reviews/T-087.md 3章のリードの判断の訂正。T-085 の「docs と読む」は取り消し）
C7 の分母は、順番1b で封印した src/stats/counting.py の関数で数える（新しく書かない）：
    counting.candidate_counts(counting.parse_day(日の集計), counting.OFFICIAL_CANDIDATE) の2つ目の値。
counting.py は、順番1b（seq 6）で封印した sha256（COUNTING_SHA256）と同じであることを確かめてから使う。

入力
- 正式な run の day の行は src/collector/gkg.py の official_day_records() だけから取る（gkg-run-result の
  関門を通る入口）。
- 日の集計は、その day の行の file_name のファイルだけを、引数で渡した置き場所から開く。開いたバイト列の
  sha256 を day の行の sha256 と照らし、合わなければ一覧を作らずに止まる。
- 日の集計から数えるのは C7 の分母だけ。テーマごとの数・比率・判定などは出力しない（counting の関数が
  中で作るテーマごとの数は、その場で捨てる）。
- ネットワークは使わない。現在の日時は出力に入れない（所要時間だけ標準エラーに出す）。何も書かない。
- 封印はしない（封印係が行う）。

使い方（プロジェクトのルートで）
  python3 -B src/stats/missing_days.py --store <日の集計の置き場所>            一覧を JSON で出す
  python3 -B src/stats/missing_days.py --store <日の集計の置き場所> --sha256   その JSON の sha256 だけを出す
  本物の置き場所："/Volumes/LACIE SHARE/news-stick-data/gkg-method"
"""

import datetime
import hashlib
import importlib.util
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(os.path.dirname(HERE))
GKG_PATH = os.path.join(PROJECT, "src", "collector", "gkg.py")
COUNTING_PATH = os.path.join(HERE, "counting.py")

if HERE not in sys.path:
    sys.path.insert(0, HERE)

import candidates  # noqa: E402
import counting  # noqa: E402
import periods  # noqa: E402

# 出力の label。文書（docs/stats/missing-days-method.md）の版と1対1にする。引数では変えない。
# 文書の規則・読み方・出力の形を変えたときだけ、文書の版と一緒に番号を上げる（テストで文書と照合する）。
# v1 は T-087（全体の報道量 = docs）。v2 は T-089（全体の報道量 = C7 の分母）。
LABEL = "missing-days-method-v2"

# 順番1b（seq 6）の記録の files にある src/stats/counting.py の sha256
COUNTING_SHA256 = "6f25985b21cd8ac93680b81308f3d1860b4ae6496577e10141d1e17ecf8c9fd3"

BLOCK_NAME = "method"
ENTRY = "src/collector/gkg.py official_day_records()"
RULE_SOURCE = "docs/stats/candidates.md 3章 (5)（seq 2）"
VOLUME_READING = ("total_volume = official C7 denominator of the day "
                  "(counting.candidate_counts(counting.parse_day(day file), "
                  "counting.OFFICIAL_CANDIDATE)[1]; reviews/T-087.md section 3)")


class MissingDaysError(Exception):
    """入力が規則の前提に合わない。一覧を作らずに止まる。"""


_GKG = None


def _gkg():
    """src/collector/gkg.py を読み込む（1回だけ）。読むだけで、収集係のコードは変えない。"""
    global _GKG
    if _GKG is None:
        spec = importlib.util.spec_from_file_location("gkg_for_stats_order4", GKG_PATH)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _GKG = mod
    return _GKG


def check_counting():
    """使っている counting が src/stats/counting.py で、順番1b で封印した sha256 と同じか。"""
    if os.path.realpath(counting.__file__) != os.path.realpath(COUNTING_PATH):
        raise MissingDaysError("読み込んだ counting が src/stats/counting.py でない")
    with open(COUNTING_PATH, "rb") as f:
        sha = hashlib.sha256(f.read()).hexdigest()
    if sha != COUNTING_SHA256:
        raise MissingDaysError("src/stats/counting.py の sha256 が、順番1b で封印した値と違う")
    return sha


def method_block():
    """手法を作る期間の区画 (start, end)（両端を含む date）。periods と gkg の両方と照合する。"""
    blocks = [b for b in periods.FROZEN_BLOCKS if b[0] == BLOCK_NAME]
    if len(blocks) != 1:
        raise MissingDaysError("periods.FROZEN_BLOCKS に手法を作る期間の区画が1つでない")
    _name, start, end = blocks[0][:3]
    g = _gkg()
    if (g.DATA_START, g.METHOD_BLOCK_END) != (start, end):
        raise MissingDaysError("gkg の区画（%s〜%s）が periods の区画（%s〜%s）と違う"
                               % (g.DATA_START, g.METHOD_BLOCK_END, start, end))
    return start, end


def _days(start, end):
    out, d = [], start
    while d <= end:
        out.append(d.isoformat())
        d += datetime.timedelta(days=1)
    return out


def _int(row, key):
    v = row.get(key)
    if isinstance(v, bool) or not isinstance(v, int) or v < 0:
        raise MissingDaysError("day の行（%s）の %s が0以上の整数でない" % (row.get("day"), key))
    return v


def check_rows(day_records, block):
    """day の行を検査し、(区画の日の一覧, {日: 行}, run_id) を返す。日の集計はまだ開かない。"""
    want = _days(*block)
    rows = {}
    run_ids = set()
    for r in day_records:
        if not isinstance(r, dict) or r.get("kind") != "day":
            raise MissingDaysError("day の行でないものがある")
        if r.get("mode") != "official":
            raise MissingDaysError("正式な run（official）でない day の行がある")
        d = r.get("day")
        if d in rows:
            raise MissingDaysError("同じ日（%s）の day の行が二つある" % d)
        rows[d] = r
        run_ids.add(r.get("run_id"))
    if len(run_ids) != 1:
        raise MissingDaysError("day の行の run_id が1つでない")
    run_id = run_ids.pop()
    outside = sorted(set(rows) - set(want), key=str)
    if outside:
        raise MissingDaysError("区画の外の日の day の行がある：%s" % outside[:5])
    absent = [d for d in want if d not in rows]
    if absent:
        raise MissingDaysError("day の行が無い日がある（%d 日。最初は %s）" % (len(absent), absent[0]))
    for d in want:
        r = rows[d]
        ok, listed = _int(r, "files_ok"), _int(r, "files_listed")
        if ok > listed:
            raise MissingDaysError("%s：files_ok が files_listed より多い" % d)
        if ok > candidates.SLOTS_PER_DAY:
            raise MissingDaysError("%s：files_ok が1日のファイルの数（%d）より多い"
                                   % (d, candidates.SLOTS_PER_DAY))
        if r.get("file_name") != counting.day_file_name(counting.OFFICIAL_MODE, run_id, d):
            raise MissingDaysError("%s：day の行の file_name が、決まった名前と違う" % d)
        sha = r.get("sha256")
        if not (isinstance(sha, str) and len(sha) == 64 and all(c in "0123456789abcdef" for c in sha)):
            raise MissingDaysError("%s：day の行の sha256 の形が違う" % d)
    return want, rows, run_id


def c7_denominator(data, day):
    """日の集計のバイト列から、その日の C7 の分母だけを返す（counting の封印済みの関数で数える）。"""
    summary = counting.parse_day(data, expect_day=day, expect_mode=counting.OFFICIAL_MODE)
    _counts, total = counting.candidate_counts(summary, counting.OFFICIAL_CANDIDATE)
    del _counts, summary
    if isinstance(total, bool) or not isinstance(total, int) or total < 0:
        raise MissingDaysError("%s：C7 の分母が0以上の整数でない" % day)
    return total


def build(day_records, block, read_day_file):
    """一覧の記録（dict）を作る。

    read_day_file(file_name) は、その名前の日の集計のバイト列を返す。すべての day の行を検査してから
    開き、開くたびに sha256 を day の行と照らす。欠けた日は candidates.day_is_missing(files_ok, C7 の分母)
    だけで決める。
    """
    want, rows, run_id = check_rows(day_records, block)
    denom = {}
    for d in want:
        r = rows[d]
        data = read_day_file(r["file_name"])
        if hashlib.sha256(data).hexdigest() != r["sha256"]:
            raise MissingDaysError("%s：日の集計 %s の sha256 が、day の行と一致しない"
                                   % (d, r["file_name"]))
        denom[d] = c7_denominator(data, d)
        del data
    missing = []
    partial = 0
    for d in want:
        r = rows[d]
        ok = r["files_ok"]
        if candidates.day_is_missing(ok, denom[d]):
            missing.append({
                "day": d,
                "files_ok": ok,
                "files_listed": r["files_listed"],
                "c7_denominator": denom[d],
                "below_min_files": ok < candidates.MIN_PRESENT_SLOTS,
                "zero_c7_denominator": denom[d] == 0,
            })
        elif ok < candidates.SLOTS_PER_DAY:
            partial += 1
    return {
        "label": LABEL,
        "block": {"name": BLOCK_NAME, "start": want[0], "end": want[-1]},
        "rule": {
            "source": RULE_SOURCE,
            "function": "src/stats/candidates.py day_is_missing(present_slots, total_volume)",
            "slots_per_day": candidates.SLOTS_PER_DAY,
            "min_present_slots": candidates.MIN_PRESENT_SLOTS,
            "present_slots": "files_ok of the manifest day row",
            "total_volume": VOLUME_READING,
            "official_candidate": counting.OFFICIAL_CANDIDATE,
            "counting_py_sha256": COUNTING_SHA256,
        },
        "input": {
            "entry": ENTRY,
            "run_id": run_id,
            "day_rows": len(rows),
            "day_files_read": len(want),
            "day_files_sha256_checked": True,
        },
        "days_in_block": len(want),
        "missing_count": len(missing),
        "missing_days": missing,
        "zero_c7_denominator_days": [d for d in want if denom[d] == 0],
        "c7_denominator_by_day": denom,
        "partial_days_count": partial,
    }


def store_reader(store):
    """置き場所 store の、名前を指定した日の集計だけを読む関数と、開いた数の記録を返す。"""
    if not os.path.isdir(store):
        raise MissingDaysError("日の集計の置き場所がディレクトリでない：%s" % store)
    opened = []

    def read(name):
        if os.path.basename(name) != name or name in ("", ".", ".."):
            raise MissingDaysError("日の集計の名前の形が違う")
        opened.append(name)
        return _gkg().read_bytes_nofollow(os.path.join(store, name))
    return read, opened


def official_record(store, _test_block=None, _opened=None):
    """正式な run の記録から一覧を作る。day の行の入口は official_day_records() だけ（関門を通る）。

    _test_block はテストの合成の run（数日だけ）のためのもの。コマンド（main）は渡さない。
    区画を差し替えても、入口（関門）と counting の照合は同じものを通る。
    """
    check_counting()
    block = method_block() if _test_block is None else _test_block
    day_records = _gkg().official_day_records()
    read, opened = store_reader(store)
    rec = build(day_records, block, read)
    if _opened is not None:
        _opened.extend(opened)
    return rec


def canonical_bytes(record):
    return (json.dumps(record, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")


def sha256_of(record):
    return hashlib.sha256(canonical_bytes(record)).hexdigest()


def _parse_args(argv):
    if len(argv) not in (2, 3) or argv[0] != "--store" or (len(argv) == 3 and argv[2] != "--sha256"):
        return None
    return argv[1], len(argv) == 3


def main(argv=None):
    if argv is None:
        argv = sys.argv[1:]
    parsed = _parse_args(list(argv))
    if parsed is None:
        sys.stderr.write("missing_days: 使い方は --store <置き場所> [--sha256]\n")
        return 2
    store, only_sha = parsed
    opened = []
    t0 = time.monotonic()
    try:
        rec = official_record(store, _opened=opened)
    except Exception as e:  # 関門（GkgError）・counting の照合・sha256 の照合・入力の誤りで止まる
        sys.stderr.write("missing_days: 止まった：%s: %s\n" % (type(e).__name__, e))
        return 1
    sys.stderr.write("missing_days: 日の集計を %d 個開いた（%.1f 秒）\n"
                     % (len(opened), time.monotonic() - t0))
    if only_sha:
        sys.stdout.write(sha256_of(rec) + "\n")
    else:
        sys.stdout.buffer.write(canonical_bytes(rec))
        sys.stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
