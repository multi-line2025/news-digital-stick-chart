#!/usr/bin/env python3
"""順番4：手法を作る期間の区画の、欠けた日の一覧（T-087、T-089 で作り直し）。
文書は docs/stats/missing-days-method.md。

規則は docs/stats/candidates.md 3章 (5)（seq 2 で封印済み）。判定は candidates.day_is_missing() を使う。
  - 取得できたファイル（present_slots）= マニフェストの day の行の files_ok
  - 取得できたファイルから数えた全体の報道量（total_volume）= その日の正式な数え方 C7 の分母
    （reviews/T-087.md 3章のリードの判断の訂正。T-085 の「docs と読む」は取り消し）
C7 の分母は、順番1b で封印した src/stats/counting.py の関数で数える（新しく書かない）：
    counting.candidate_counts(counting.parse_day(日の集計), counting.OFFICIAL_CANDIDATE) の2つ目の値。
中で使う periods.py・candidates.py・counting.py は、封印の記録が縛る sha256（SEALED_CODE）と同じであることを
確かめてから使う（T-093）。値は seq 1（periods）・seq 2（candidates）・seq 6（stats-order1b）の記録から写したもので、
実行のときにも、関門で検証した封印の記録の該当する欄と照らす（check_sealed_code_in_ledger）。

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

_LOADED_SHA = {}


def _load_verified(name, rel, deps=()):
    """src/stats のファイルを1回だけ読み、そのバイト列の sha256 を記録し、同じバイト列を compile/exec して
    モジュールにする（T-096）。import の仕組みを通さないので、__pycache__ の .pyc は読まない。

    deps：このファイルが import する src/stats のモジュール（名前, モジュール）。exec のあいだだけ
    sys.modules に置き、照合したバイト列から作ったものを import させる（終わったら元に戻す）。
    """
    import types
    path = os.path.join(PROJECT, *rel.split("/"))
    with open(path, "rb") as f:
        data = f.read()
    _LOADED_SHA[rel] = hashlib.sha256(data).hexdigest()
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


periods = _load_verified("periods", "src/stats/periods.py")
candidates = _load_verified("candidates", "src/stats/candidates.py", deps=(("periods", periods),))
counting = _load_verified("counting", "src/stats/counting.py")

# 出力の label。文書（docs/stats/missing-days-method.md）の版と1対1にする。引数では変えない。
# 文書の規則・読み方・出力の形を変えたときだけ、文書の版と一緒に番号を上げる（テストで文書と照合する）。
# v1 は T-087（全体の報道量 = docs）。v2 は T-089（全体の報道量 = C7 の分母）。
# v3 は T-093（規則と読み方は v2 と同じ。コードの照合を足し、出力の rule・input に欄を足した）。
LABEL = "missing-days-method-v3"

# 順番1b（seq 6）の記録の files にある src/stats/counting.py の sha256
COUNTING_SHA256 = "6f25985b21cd8ac93680b81308f3d1860b4ae6496577e10141d1e17ecf8c9fd3"
# seq 1（periods）の targets の role "code"（と seq 2 の role "import"）にある src/stats/periods.py の sha256
PERIODS_SHA256 = "81de229d065196a26e15d90c5a80eb1043ca534a6eaf66cdebd36285ae087605"
# seq 2（candidates）の targets の role "code" にある src/stats/candidates.py の sha256
CANDIDATES_SHA256 = "21b5838782991596057be2fdffdeac596bf4548517ef077e5c4547a719512e89"

# 照らす値の出どころ：(パス, sha256, [(seq, kind, 欄)])。欄は、記録の targets の role か、
# stats-order1b の中身の files
SEALED_CODE = (
    ("src/stats/periods.py", PERIODS_SHA256, ((1, "periods", "targets:code"),
                                              (2, "candidates", "targets:import"))),
    ("src/stats/candidates.py", CANDIDATES_SHA256, ((2, "candidates", "targets:code"),)),
    ("src/stats/counting.py", COUNTING_SHA256, ((6, "stats-order1b", "files"),)),
)
_MODULES = {"src/stats/periods.py": periods, "src/stats/candidates.py": candidates,
            "src/stats/counting.py": counting}

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


def check_stats_code():
    """使っている periods・candidates・counting が src/stats のそのファイルから作ったもので、動いているコードの
    バイト列（_load_verified が読んで compile したもの）の sha256 が SEALED_CODE と同じか。"""
    out = {}
    for rel, want, _src in SEALED_CODE:
        path = os.path.join(PROJECT, *rel.split("/"))
        if os.path.realpath(_MODULES[rel].__file__) != os.path.realpath(path):
            raise MissingDaysError("読み込んだモジュールが %s でない" % rel)
        sha = _LOADED_SHA.get(rel)
        if sha != want:
            raise MissingDaysError("%s の sha256 が、封印の記録の値と違う" % rel)
        out[rel] = sha
    return out


def check_counting():
    """互換のため残す（T-089）。check_stats_code() の counting の部分。"""
    return check_stats_code()["src/stats/counting.py"]


def check_sealed_code_in_ledger(records, read_order1b):
    """SEALED_CODE の値が、封印の記録の該当する欄と同じか。

    records：検証した封印の記録の一覧。read_order1b(record)：stats-order1b の記録の中身（JSON）を返す。
    """
    by_seq = {r.get("seq"): r for r in records}
    for rel, want, sources in SEALED_CODE:
        for seq, kind, field in sources:
            r = by_seq.get(seq)
            if r is None or r.get("kind") != kind:
                raise MissingDaysError("seq %d が %s の記録でない" % (seq, kind))
            if field.startswith("targets:"):
                role = field.split(":", 1)[1]
                got = [t.get("sha256") for t in r.get("targets", [])
                       if t.get("path") == rel and t.get("role") == role]
            else:
                got = [f.get("sha256") for f in read_order1b(r).get("files", []) if f.get("path") == rel]
            if got != [want]:
                raise MissingDaysError("%s の sha256 が、seq %d（%s）の %s の値と違う" % (rel, seq, kind, field))


def _ledger():
    return _gkg()._load_sibling("themes")._import_ledger()


def sealed_refs(run_id):
    """関門を通ったあとで、gkg-run-result の記録の参照と、使ったマニフェストの sha256 を返す。
    あわせて、SEALED_CODE の値を封印の記録と照らす。"""
    ledger = _ledger()
    rec = ledger.require_gkg_run_result("official", run_id)
    root = ledger._gate_root()
    records = ledger.verify_chain(ledger.read_ledger(os.path.join(root, "sealed", "ledger.jsonl")))
    same = [r for r in records if r["seq"] == rec["seq"]]
    if len(same) != 1 or ledger.canonical_line(same[0]) != ledger.canonical_line(rec):
        raise MissingDaysError("関門の返した gkg-run-result の記録が、封印の記録の中に無い")
    check_sealed_code_in_ledger(
        records, lambda r: ledger.read_target_json(root, r, ledger.ORDER1B_KIND))
    doc = ledger.read_target_json(root, rec, ledger.GKG_RESULT_KIND)
    if doc.get("mode") != "official" or doc.get("run_id") != run_id:
        raise MissingDaysError("gkg-run-result の記録が、この run のものでない")
    return {
        "gkg_run_result_seq": rec["seq"],
        "gkg_run_result_record_sha256": ledger.sha256_hex(ledger.canonical_line(rec)),
        "manifest_path": doc["manifest_path"],
        "manifest_lines": doc["manifest_lines"],
        "manifest_sha256": doc["manifest_sha256"],
    }


REF_KEYS = ("gkg_run_result_record_sha256", "gkg_run_result_seq", "manifest_lines", "manifest_path",
            "manifest_sha256")


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


def build(day_records, block, read_day_file, refs):
    """一覧の記録（dict）を作る。

    read_day_file(file_name) は、その名前の日の集計のバイト列を返す。すべての day の行を検査してから
    開き、開くたびに sha256 を day の行と照らす。欠けた日は candidates.day_is_missing(files_ok, C7 の分母)
    だけで決める。
    """
    if not isinstance(refs, dict) or tuple(sorted(refs)) != REF_KEYS:
        raise MissingDaysError("refs のキーが違う")
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
            "candidates_py_sha256": CANDIDATES_SHA256,
            "periods_py_sha256": PERIODS_SHA256,
        },
        "input": {
            "entry": ENTRY,
            "run_id": run_id,
            "day_rows": len(rows),
            "day_files_read": len(want),
            "day_files_sha256_checked": True,
            "gkg_run_result_seq": refs["gkg_run_result_seq"],
            "gkg_run_result_record_sha256": refs["gkg_run_result_record_sha256"],
            "manifest_path": refs["manifest_path"],
            "manifest_lines": refs["manifest_lines"],
            "manifest_sha256": refs["manifest_sha256"],
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
    区画を差し替えても、入口（関門）とコードの照合（check_stats_code・sealed_refs）は同じものを通る。
    """
    check_stats_code()
    block = method_block() if _test_block is None else _test_block
    day_records = _gkg().official_day_records()
    run_ids = {r.get("run_id") for r in day_records if isinstance(r, dict)}
    if len(run_ids) != 1:
        raise MissingDaysError("day の行の run_id が1つでない")
    refs = sealed_refs(run_ids.pop())
    read, opened = store_reader(store)
    rec = build(day_records, block, read, refs)
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
