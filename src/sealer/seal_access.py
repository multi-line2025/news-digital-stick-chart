#!/usr/bin/env python3
"""threshold-access の記録を書く仕組みと、関門の確認。T-009、T-014。

threshold-access は、閾値を決める期間の区画（2020-12-15 以降）の情報を初めて「扱う」直前に、
鎖へ追記する記録である（docs/verify/periods-seal.md 1章・7章）。最初の threshold-access が
採用の区切りになる。

使い方（プロジェクトのルートで。ots と drand の通信を使うので .venv の python で実行する）
    PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -B src/sealer/seal_access.py seal
        1. 記録の鎖と .ots を検証する。periods の記録が無ければ止める。candidates の記録が無いか、
           候補の順序の照合に通らなければ止める（T-014。drand を取りにいく前に止める）。
        2. drand（quicknet）の最新の回を取る。
        3. 中身 {"kind", "block_start", "drand", "ledger_head"} を作る。block_start は
           periods の 1 件目の出力の閾値の期間（threshold）の始まりで、引数では渡せない。
        4. 検証と同じ照合をしてから、sealed/threshold-access-<sha256>.json を書き、記録に追記し、
           その seq 自身の .ots を作る（手順の詳細は seal_records.py）。
    PYTHONDONTWRITEBYTECODE=1 python3 -B src/sealer/seal_access.py gate
        関門（ledger.require_threshold_access）を実行し、通れば終了コード 0、
        止まれば理由を出して終了コード 1。ネットワークは使わない。関門の root はプロジェクトの
        ルートに固定で、gate は --root を受け付けない（T-014。T-009 の監査 軽2）。

関門を飛ばしたかどうかは、記録からは検出できない（ledger.require_threshold_access の注記）。
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


def seal(project, now, ots_cmd, drand_fetch=None, runner=subprocess.run):
    """threshold-access を 1 件追記する。返り値: (記録, 中身のパス, .ots のパス)。"""
    data, records = seal_records.load_checked(project, ots_cmd, runner=runner)
    ledger.check_candidates_ready(project, records, len(records) + 1)
    block_start = ledger.first_threshold_block_start(project, records)
    doc = {
        "kind": ledger.THRESHOLD_ACCESS_KIND,
        "block_start": block_start,
        "drand": seal_records.drand_part(now, drand_fetch),
        "ledger_head": ledger.expected_ledger_head(data, len(records) + 1),
    }
    n = len(ledger.records_of_kind(records, ledger.THRESHOLD_ACCESS_KIND)) + 1
    note = ("閾値を決める期間の区画（%s 以降）の情報を扱う直前の記録。threshold-access の %d 件目。"
            "%s" % (block_start, n, "採用の区切り。" if n == 1 else "区切りは 1 件目。"))
    return seal_records.write_doc_record(project, ledger.THRESHOLD_ACCESS_KIND, doc, data, note,
                                         now, ots_cmd, runner=runner)


def main(argv=None):
    p = argparse.ArgumentParser(allow_abbrev=False, description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest="action", required=True)
    s = sub.add_parser("seal", allow_abbrev=False)
    s.add_argument("--ots", default=stamp.DEFAULT_OTS)
    s.add_argument("--root", default=PROJECT)
    sub.add_parser("gate", allow_abbrev=False)   # root はプロジェクトのルートに固定
    a = p.parse_args(argv)
    try:
        if a.action == "gate":
            rec = ledger.require_threshold_access()
            print("関門を通った：threshold-access の記録 seq %d がある。" % rec["seq"])
            print("注意：関門を飛ばしてデータに触れたかどうかは、記録からは検出できない。")
            return 0
        now = datetime.datetime.now(datetime.timezone.utc)
        rec, rel, ots_path = seal(os.path.abspath(a.root), now, a.ots)
    except ledger.LedgerError as e:
        print("失敗: %s" % e, file=sys.stderr)
        return 1
    except seal_records.netfetch.FetchError as e:
        print("失敗（通信）: %s" % e, file=sys.stderr)
        return 1
    print(ledger.canonical_line(rec).decode("utf-8"))
    print("中身: %s" % rel)
    print("時刻証明: %s" % os.path.relpath(ots_path, os.path.abspath(a.root)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
