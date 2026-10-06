#!/usr/bin/env python3
"""試運転の手順4（手法を作る期間のデータそのものの取得）の開始の記録と、関門の確認。T-014。

method-access は、手法を作る期間の区画（periods の 1 件目の出力の method の区画）のデータ
そのものに初めて触れる直前に、鎖へ追記する記録である（docs/verify/periods-seal.md 10章）。
採用の区切りには使わない（区切りは threshold-access のまま）。

使い方（プロジェクトのルートで。ots と drand の通信を使うので .venv の python で実行する）
    PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -B src/sealer/seal_method.py seal
        1. 記録の鎖と .ots を検証する。periods の記録が無ければ止める。
        2. candidates の記録と acquisition-result の記録が、それぞれ 1 件以上なければ止める
           （drand を取りにいく前に止める）。
        3. drand（quicknet）の最新の回を取る。
        4. 中身 {"kind", "step": 4, "block_start", "block_end", "drand", "ledger_head"} を作る。
           block_start・block_end は periods の 1 件目の出力の method の区画で、引数では渡せない。
        5. 検証と同じ照合をしてから、sealed/method-access-<sha256>.json を書き、記録に追記し、
           その seq 自身の .ots を作る（手順の詳細は seal_records.py）。
    PYTHONDONTWRITEBYTECODE=1 python3 -B src/sealer/seal_method.py gate
        関門（ledger.require_method_access）を実行し、通れば終了コード 0、止まれば理由を出して
        終了コード 1。ネットワークは使わない。関門の root はプロジェクトのルートに固定で、
        --root は受け付けない。

関門を飛ばしたかどうかは、記録からは検出できない（ledger.require_method_access の注記）。
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
STEP = 4


def seal(project, now, ots_cmd, drand_fetch=None, runner=subprocess.run):
    """method-access を 1 件追記する。返り値: (記録, 中身のパス, .ots のパス)。"""
    data, records = seal_records.load_checked(project, ots_cmd, runner=runner)
    kinds = {r["kind"] for r in records}
    for need in (ledger.CANDIDATES_KIND, ledger.ACQ_RESULT_KIND):
        if need not in kinds:
            raise ledger.LedgerError("%s の記録が無い。手順4は、候補の封印と手順3の取得の記録の"
                                     "後に行う決まり。追記しない" % need)
    ledger.check_candidates_ready(project, records, len(records) + 1)
    block_start, block_end = ledger.method_block_of(project, records)
    doc = {
        "kind": ledger.METHOD_ACCESS_KIND,
        "step": STEP,
        "block_start": block_start,
        "block_end": block_end,
        "drand": seal_records.drand_part(now, drand_fetch),
        "ledger_head": ledger.expected_ledger_head(data, len(records) + 1),
    }
    n = len(ledger.records_of_kind(records, ledger.METHOD_ACCESS_KIND)) + 1
    note = ("手法を作る期間の区画（%s〜%s）のデータそのもの（試運転の手順4）に触れる直前の記録。"
            "method-access の %d 件目。採用の区切りには使わない。" % (block_start, block_end, n))
    return seal_records.write_doc_record(project, ledger.METHOD_ACCESS_KIND, doc, data, note,
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
            rec = ledger.require_method_access()
            print("関門を通った：method-access の記録 seq %d がある。" % rec["seq"])
            print("注意：関門を飛ばしてデータに触れたかどうかは、記録からは検出できない。")
            return 0
        root = os.path.abspath(a.root)
        now = datetime.datetime.now(datetime.timezone.utc)
        rec, rel, ots_path = seal(root, now, a.ots)
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
