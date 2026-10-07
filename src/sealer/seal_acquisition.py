#!/usr/bin/env python3
"""試運転の手順3の取得の記録（acquisition-start、acquisition-result）を書く仕組み。T-009、T-014。

取得のコード（収集係）は、次の順で呼ぶ（docs/verify/periods-seal.md 7章）。
  1. start：取得を始める前。drand の最新の回、ledger_head、取得のコードのパスと sha256 を
     中身に入れて追記し、その seq 自身の .ots を作る。返り値の記録の seq を控える。
  2. 取得する。2020-12-15 以降の行は、メモリの上で捨ててからディスクに書く。
  3. result：取得の後。1 の seq（start_seq）と、捨てたあとの一覧の sha256（kept_rows_sha256）を
     中身に入れて追記し、その seq 自身の .ots を作る。

使い方（プロジェクトのルートで。ots と drand の通信を使うので .venv の python で実行する）
    PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -B src/sealer/seal_acquisition.py \\
        start --code <取得のコードの、ルートからの相対パス>
    PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -B src/sealer/seal_acquisition.py \\
        result --start-seq N --kept-rows-sha256 <64 桁の16進>

拒むもの（何も書かずに止める）
  - periods の記録が無い。記録の鎖か .ots の検証に通らない。
  - start：candidates の記録が 1 件も無い（T-014。T-013 の監査 B-1。候補は、手法を作る期間の
    データに触れる前に封印する決まり。drand を取りにいく前に止める）。
  - start：取得のコードが、このリポジトリの HEAD のコミットの中身と同じでない（コミットして
    いない、または作業ツリーで変えている）。第三者が、記録の sha256 をコミットの中の
    コードと照らせるようにするため。
  - result：start_seq が acquisition-start の記録でない。その start に result が既にある
    （一つの start に result は一つだけ）。kept_rows_sha256 の形が違う。

示せないこと（手順書 7章）：result の無い start は許している。kept_rows_sha256 だけでは、
2020-12-15 以降の行を捨てたことは示せない。
"""

import argparse
import datetime
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import ledger  # noqa: E402
import seal_records  # noqa: E402
import stamp  # noqa: E402

PROJECT = os.path.dirname(os.path.dirname(HERE))
STEP = 3


def committed_code_sha256(project, code_rel):
    """取得のコードの sha256。作業ツリーの中身が HEAD のコミットの中身と同じときだけ返す。"""
    path, _ = ledger.acquisition_start_fields(
        {"fetch": {"code_path": code_rel, "code_sha256": "0" * 64}})
    full = os.path.join(project, path)
    if not os.path.isfile(full) or os.path.islink(full):
        raise ledger.LedgerError("取得のコードが無い（または通常のファイルでない）: %s" % path)
    with open(full, "rb") as f:
        work = f.read()
    r = subprocess.run(["git", "-C", project, "show", "HEAD:%s" % path], capture_output=True)
    if r.returncode != 0:
        raise ledger.LedgerError("取得のコードが HEAD のコミットに無い: %s" % path)
    if r.stdout != work:
        raise ledger.LedgerError("取得のコードが HEAD のコミットの中身と違う（作業ツリーで変えている）"
                                 ": %s" % path)
    return path, ledger.sha256_hex(work)


def start(project, code_rel, now, ots_cmd, drand_fetch=None, runner=subprocess.run):
    """acquisition-start を 1 件追記する。返り値: (記録, 中身のパス, .ots のパス)。"""
    data, records = seal_records.load_checked(project, ots_cmd, runner=runner)
    if not ledger.records_of_kind(records, ledger.CANDIDATES_KIND):
        raise ledger.LedgerError("candidates の記録が無い。候補は、手法を作る期間のデータに触れる"
                                 "前に封印する決まり。追記しない")
    code_path, code_sha = committed_code_sha256(project, code_rel)
    doc = {
        "kind": ledger.ACQ_START_KIND,
        "step": STEP,
        "drand": seal_records.drand_part(now, drand_fetch),
        "ledger_head": ledger.expected_ledger_head(data, len(records) + 1),
        "fetch": {"code_path": code_path, "code_sha256": code_sha},
    }
    n = len(ledger.records_of_kind(records, ledger.ACQ_START_KIND)) + 1
    note = "試運転の手順3の取得を始める前の記録。acquisition-start の %d 件目。" % n
    return seal_records.write_doc_record(project, ledger.ACQ_START_KIND, doc, data, note, now,
                                         ots_cmd, runner=runner)


def result(project, start_seq, kept_rows_sha256, now, ots_cmd, runner=subprocess.run):
    """acquisition-result を 1 件追記する。返り値: (記録, 中身のパス, .ots のパス)。"""
    data, records = seal_records.load_checked(project, ots_cmd, runner=runner)
    doc = {
        "kind": ledger.ACQ_RESULT_KIND,
        "start_seq": start_seq,
        "kept_rows_sha256": kept_rows_sha256,
    }
    note = "試運転の手順3の取得の後の記録。acquisition-start（seq %r）に対応する。" % (start_seq,)
    return seal_records.write_doc_record(project, ledger.ACQ_RESULT_KIND, doc, data, note, now,
                                         ots_cmd, runner=runner)


def main(argv=None):
    p = argparse.ArgumentParser(allow_abbrev=False, description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest="action", required=True)
    s = sub.add_parser("start", allow_abbrev=False)
    s.add_argument("--code", required=True, help="取得のコードの、ルートからの相対パス")
    r = sub.add_parser("result", allow_abbrev=False)
    r.add_argument("--start-seq", type=int, required=True)
    r.add_argument("--kept-rows-sha256", required=True)
    for q in (s, r):
        q.add_argument("--ots", default=stamp.DEFAULT_OTS)
        q.add_argument("--root", default=PROJECT)
    a = p.parse_args(argv)
    root = os.path.abspath(a.root)
    now = datetime.datetime.now(datetime.timezone.utc)
    try:
        if a.action == "start":
            rec, rel, ots_path = start(root, a.code, now, a.ots)
        else:
            rec, rel, ots_path = result(root, a.start_seq, a.kept_rows_sha256, now, a.ots)
    except ledger.LedgerError as e:
        print("失敗: %s" % e, file=sys.stderr)
        return 1
    except seal_records.netfetch.FetchError as e:
        print("失敗（通信）: %s" % e, file=sys.stderr)
        return 1
    print(ledger.canonical_line(rec).decode("utf-8"))
    print("中身: %s" % rel)
    print("時刻証明: %s" % os.path.relpath(ots_path, root))
    return 0


if __name__ == "__main__":
    sys.exit(main())
