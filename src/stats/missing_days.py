#!/usr/bin/env python3
"""順番4：手法を作る期間の区画の、欠けた日の一覧（T-087）。文書は docs/stats/missing-days-method.md。

規則は docs/stats/candidates.md 3章 (5)（seq 2 で封印済み）。判定は candidates.day_is_missing() を使う。
  - 取得できたファイル = マニフェストの day の行の files_ok
  - 取得できたファイルから数えた全体の報道量 = マニフェストの day の行の docs（取得できたファイルの
    記事（文書）の数。reviews/T-085.md のリードの判断 1）

入力は src/collector/gkg.py の official_day_records() だけ（gkg-run-result の関門を通る入口）。
- 日の集計のファイル（保存先の .tsv.gz）は開かない。マニフェストの day の行の数字だけを使う。
- ネットワークは使わない。現在の日時を読まない。何も書かない（標準出力だけ）。
- 封印はしない（封印係が行う）。

使い方（プロジェクトのルートで）
  python3 -B src/stats/missing_days.py            一覧を JSON（キー順・UTF-8・indent 2）で出す
  python3 -B src/stats/missing_days.py --sha256   上の JSON のバイト列の sha256 だけを出す
"""

import datetime
import hashlib
import importlib.util
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(os.path.dirname(HERE))
GKG_PATH = os.path.join(PROJECT, "src", "collector", "gkg.py")

if HERE not in sys.path:
    sys.path.insert(0, HERE)

import candidates  # noqa: E402
import periods  # noqa: E402

LABEL = "missing-days-method-v1"

# 手法を作る期間の区画（periods.FROZEN_BLOCKS の最初の区画。gkg.METHOD_BLOCK と一致することを確かめる）
BLOCK_NAME = "method"

ENTRY = "src/collector/gkg.py official_day_records()"
RULE_SOURCE = "docs/stats/candidates.md 3章 (5)（seq 2）"
VOLUME_READING = ("total_volume = docs of the manifest day row "
                  "(documents in the fetched files; reviews/T-085.md lead decision 1)")


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


def method_block():
    """手法を作る期間の区画 (start, end)（両端を含む date）。periods と gkg の両方と照合する。"""
    blocks = [b for b in periods.FROZEN_BLOCKS if b[0] == BLOCK_NAME]
    if len(blocks) != 1:
        raise MissingDaysError("periods.FROZEN_BLOCKS に手法を作る期間の区画が1つでない")
    _name, start, end = blocks[0][:3]
    start = _as_date(start)
    end = _as_date(end)
    g = _gkg()
    if (g.DATA_START, g.METHOD_BLOCK_END) != (start, end):
        raise MissingDaysError("gkg の区画（%s〜%s）が periods の区画（%s〜%s）と違う"
                               % (g.DATA_START, g.METHOD_BLOCK_END, start, end))
    return start, end


def _as_date(x):
    if isinstance(x, datetime.date):
        return x
    return datetime.date.fromisoformat(x)


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


def build(day_records, block):
    """day_records（official_day_records() の戻り値）から一覧の記録（dict）を作る。

    - 区画の各日に、day の行がちょうど1つあることを求める。無い日・区画の外の行・重なりは止める
      （正式な run は区画の全日の行を持つ。持たなければ入力の誤りとみなし、推測で埋めない）。
    - 欠けた日かどうかは candidates.day_is_missing(files_ok, docs) だけで決める。
    """
    start, end = block
    want = _days(start, end)
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
    outside = sorted(set(rows) - set(want), key=str)
    if outside:
        raise MissingDaysError("区画の外の日の day の行がある：%s" % outside[:5])
    absent = [d for d in want if d not in rows]
    if absent:
        raise MissingDaysError("day の行が無い日がある（%d 日。最初は %s）" % (len(absent), absent[0]))

    missing = []
    partial = 0
    for d in want:
        r = rows[d]
        ok = _int(r, "files_ok")
        listed = _int(r, "files_listed")
        docs = _int(r, "docs")
        if ok > listed:
            raise MissingDaysError("%s：files_ok が files_listed より多い" % d)
        if ok > candidates.SLOTS_PER_DAY:
            raise MissingDaysError("%s：files_ok が1日のファイルの数（%d）より多い"
                                   % (d, candidates.SLOTS_PER_DAY))
        if candidates.day_is_missing(ok, docs):
            missing.append({
                "day": d,
                "files_ok": ok,
                "files_listed": listed,
                "docs": docs,
                "below_min_files": ok < candidates.MIN_PRESENT_SLOTS,
                "zero_docs": docs == 0,
            })
        elif ok < candidates.SLOTS_PER_DAY:
            partial += 1
    return {
        "label": LABEL,
        "block": {"name": BLOCK_NAME, "start": start.isoformat(), "end": end.isoformat()},
        "rule": {
            "source": RULE_SOURCE,
            "function": "src/stats/candidates.py day_is_missing(present_slots, total_volume)",
            "slots_per_day": candidates.SLOTS_PER_DAY,
            "min_present_slots": candidates.MIN_PRESENT_SLOTS,
            "present_slots": "files_ok of the manifest day row",
            "total_volume": VOLUME_READING,
        },
        "input": {
            "entry": ENTRY,
            "run_id": run_ids.pop(),
            "day_rows": len(rows),
            "daily_aggregates_opened": False,
        },
        "days_in_block": len(want),
        "missing_count": len(missing),
        "missing_days": missing,
        "partial_days_count": partial,
    }


def official_record(_test_block=None):
    """正式な run の記録から一覧を作る。入口は official_day_records() だけ（関門を通る）。

    _test_block はテストの合成の run（数日だけ）のためのもの。コマンド（main）は渡さない。
    区画を差し替えても、入口（関門）は同じものを通る。
    """
    block = method_block() if _test_block is None else _test_block
    return build(_gkg().official_day_records(), block)


def canonical_bytes(record):
    return (json.dumps(record, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")


def sha256_of(record):
    return hashlib.sha256(canonical_bytes(record)).hexdigest()


def main(argv=None):
    if argv is None:
        argv = sys.argv[1:]
    if argv not in ([], ["--sha256"]):
        sys.stderr.write("missing_days: 引数は --sha256 だけ\n")
        return 2
    try:
        rec = official_record()
    except Exception as e:  # 関門（GkgError）や入力の誤りで止まる。一覧は出さない
        sys.stderr.write("missing_days: 止まった：%s: %s\n" % (type(e).__name__, e))
        return 1
    if argv == ["--sha256"]:
        sys.stdout.write(sha256_of(rec) + "\n")
    else:
        sys.stdout.buffer.write(canonical_bytes(rec))
        sys.stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
