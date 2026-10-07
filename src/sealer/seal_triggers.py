#!/usr/bin/env python3
"""区切りを作り直すきっかけの値の封印（kind: periods-triggers）。T-005、T-008。

docs/stats/periods.md 8章 (2) の「きっかけの値は期限より前に決め、封印の記録に追記する」
を行う仕組み。値は統計係が決める。この仕組みは値を記録して時刻証明を付けるだけで、
値を選ばない。

使い方（プロジェクトのルートで。ots を使うので .venv の python で実行する）
    PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -B src/sealer/seal_triggers.py \\
        [--last-read-offset-days J] [--network-window-days W] \\
        [--same-week-years N] [--naive-history-days H]

  - 少なくとも一つの値を渡す。渡さなかった値は null として記録する。
  - 値は sealed/periods-triggers-<sha256>.json（4 つのキーの正規の形の JSON）に書き、
    記録に 1 件追記して、その seq 自身の .ots を作る。
  - periods の記録が 1 件も無ければ止まる（作り直しの元になる版が無いため）。

この記録が採用されるかは、この仕組みでは決めない。検証（verify.py periods / adopted）が、
鎖の順番で決める（最初の threshold-access の記録より前にある、periods-triggers の最後の記録）。
時刻証明の時刻は、採用の判定には使わない。
threshold-access の記録の後でも、追記は拒まない（関門は設けない。T-008）。その場合、
検証が「採用しない」と表示する。
"""

import argparse
import datetime
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import ledger  # noqa: E402
import stamp  # noqa: E402

PROJECT = os.path.dirname(os.path.dirname(HERE))


def seal(project, values, now, ots_cmd, runner=subprocess.run):
    doc = {k: values.get(k) for k in ledger.TRIGGER_KEYS}
    ledger.triggers_values(doc)
    ledger.check_sealed_inside(project)    # T-017：sealed/ が別の場所を指していれば何もしない
    sealed_dir = os.path.join(project, "sealed")
    ledger_path = os.path.join(sealed_dir, "ledger.jsonl")
    data = ledger.read_ledger(ledger_path)
    records = ledger.verify_chain(data)
    if records:
        ledger.check_anchors(data, sealed_dir)
    if not ledger.records_of_kind(records, "periods"):
        raise ledger.LedgerError("periods の記録が無い。きっかけの値は封印しない")
    if ots_cmd is not None:
        stamp.check_ots(ots_cmd)
    content = ledger.canonical_line(doc) + b"\n"
    sha = ledger.sha256_hex(content)
    rel = "sealed/periods-triggers-%s.json" % sha
    ledger.write_once(os.path.join(project, rel), content)
    n = len(ledger.records_of_kind(records, ledger.TRIGGERS_KIND)) + 1
    note = ("区切りを作り直すきっかけの値（docs/stats/periods.md 8章 (2)）。"
            "periods-triggers の %d 件目。" % n)
    records = ledger.append_record(ledger_path, ledger.TRIGGERS_KIND,
                                   [{"path": rel, "role": "triggers", "sha256": sha}], note, now)
    rec = records[-1]
    if ots_cmd is None:
        return rec, None, []
    ots_path, _err, submitted = stamp.stamp_seq(ledger_path, rec["seq"], ots_cmd, runner=runner)
    return rec, ots_path, submitted


def main(argv=None):
    p = argparse.ArgumentParser(allow_abbrev=False, description=__doc__.splitlines()[0])
    for k in ledger.TRIGGER_KEYS:
        p.add_argument("--" + k.replace("_", "-"), type=int, default=None, dest=k)
    p.add_argument("--ots", default=stamp.DEFAULT_OTS)
    a = p.parse_args(argv)
    values = {k: getattr(a, k) for k in ledger.TRIGGER_KEYS}
    now = datetime.datetime.now(datetime.timezone.utc)
    try:
        rec, ots_path, submitted = seal(PROJECT, values, now, a.ots)
    except ledger.LedgerError as e:
        print("失敗: %s" % e, file=sys.stderr)
        return 1
    print(ledger.canonical_line(rec).decode("utf-8"))
    print("時刻証明: %s" % os.path.relpath(ots_path, PROJECT))
    print("送った先: %s" % ", ".join(submitted))
    return 0


if __name__ == "__main__":
    sys.exit(main())
