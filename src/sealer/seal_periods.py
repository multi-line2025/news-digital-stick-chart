#!/usr/bin/env python3
"""期間の区切りの封印（試運転の手順2）。T-005。

使い方（プロジェクトのルートで。ots を使うので .venv の python で実行する）
    PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -B src/sealer/seal_periods.py \\
        --expect-output-sha256 <出力の sha256> [-- <periods.py に渡す引数>]

手順（この順で行い、途中で失敗したら、それより後のことはしない）
  1. 既存の記録の鎖と時刻証明を検証する。ots が実行できることを確かめる。
  2. src/stats/periods.py を実行し、出力（標準出力の JSON）のバイト列を得る。
  3. 出力の sha256 が --expect-output-sha256 と一致することを確かめる。
  4. 封印の時機の検査
     - periods の最初の版：data/ の下（.gitignore の対象の data/raw も含む、すべての
       サブフォルダ）に .gitkeep 以外のファイルが無いこと。試運転の手順3より前に封印するため。
       調べるのはこのリポジトリの data/ の下だけで、Git の外の置き場は調べられない。
     - 後の版：区画の境目（block_start・block_end）が、最初の版の出力と一致すること。
  5. 出力を sealed/periods-output-<sha256>.json として書く（新しいファイル。上書きしない）。
  6. 4 つの対象の sha256 を記録に 1 件追記する。
  7. 記録の先頭からその行までに、OpenTimestamps の時刻証明を付ける。

版の番号は記録に書かない。periods の記録の何件目かで決まる（ledger.version_of）。
記録した日時は、この機械の時計の申告である。証明は OpenTimestamps で行う。
"""

import argparse
import datetime
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import ledger  # noqa: E402
import stamp  # noqa: E402

PROJECT = os.path.dirname(os.path.dirname(HERE))
KIND = "periods"
PERIODS_SCRIPT = "src/stats/periods.py"
SOURCES = (
    ("docs/stats/periods.md", "doc"),
    ("src/stats/periods.py", "code"),
    ("tests/stats/test_periods.py", "test"),
)
# データの取得が始まると、この下にファイルが入る（収集係の置き場と、Git の外の data/raw）。
DATA_ROOT = "data"


def run_periods(project, extra_args):
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    cmd = [sys.executable, "-B", os.path.join(project, PERIODS_SCRIPT)] + list(extra_args)
    r = subprocess.run(cmd, capture_output=True, env=env, cwd=project, timeout=120)
    if r.returncode != 0:
        raise ledger.LedgerError("periods.py が失敗した（終了コード %d）" % r.returncode)
    return r.stdout


def data_started(project):
    """data/ の下に .gitkeep 以外のファイル（またはそれ以外の項目）があれば、その一覧を返す。"""
    found = []
    full = os.path.join(project, DATA_ROOT)
    if not os.path.isdir(full):
        return found
    for root, dirs, files in os.walk(full, followlinks=False):
        for name in files:
            if name != ".gitkeep":
                found.append(os.path.relpath(os.path.join(root, name), project))
        for name in dirs:
            if os.path.islink(os.path.join(root, name)):
                found.append(os.path.relpath(os.path.join(root, name), project))
    return found


def seal(project, expect_sha, extra_args, now, ots_cmd, runner=subprocess.run):
    sealed_dir = os.path.join(project, "sealed")
    ledger_path = os.path.join(sealed_dir, "ledger.jsonl")

    # 1
    data = ledger.read_ledger(ledger_path)
    records = ledger.verify_chain(data)
    if records:
        ledger.check_anchors(data, sealed_dir)
    if ots_cmd is not None:
        stamp.check_ots(ots_cmd)

    # 2, 3
    out = run_periods(project, extra_args)
    out_sha = ledger.sha256_hex(out)
    if out_sha != expect_sha:
        raise ledger.LedgerError("出力の sha256 が期待と違う: %s" % out_sha)
    output = json.loads(out.decode("utf-8"))

    # 4
    previous = ledger.records_of_kind(records, KIND)
    if not previous:
        started = data_started(project)
        if started:
            raise ledger.LedgerError("データの取得が始まっている（%s）。最初の版は封印しない"
                                     % ", ".join(sorted(started)))
        if output.get("deadline_status") is not None:
            raise ledger.LedgerError("最初の版の deadline_status は null でなければならない")
    else:
        first = previous[0][1]
        first_out_path = os.path.join(project, ledger.output_target(first)["path"])
        with open(first_out_path, "rb") as f:
            first_bytes = f.read()
        if ledger.sha256_hex(first_bytes) != ledger.output_target(first)["sha256"]:
            raise ledger.LedgerError("最初の版の出力のファイルが、記録の sha256 と一致しない")
        problems = ledger.check_blocks(json.loads(first_bytes.decode("utf-8")), output)
        if problems:
            raise ledger.LedgerError("区画の境目が最初の版と違う: " + "; ".join(problems))

    # 5
    out_rel = "sealed/periods-output-%s.json" % out_sha
    ledger.write_once(os.path.join(project, out_rel), out)

    # 6
    targets = []
    for rel, role in SOURCES:
        targets.append({"path": rel, "role": role,
                        "sha256": ledger.sha256_file(os.path.join(project, rel))})
    targets.append({"path": out_rel, "role": "output", "sha256": out_sha})
    version = len(previous) + 1
    note = ("期間の区切り（試運転の手順2、T-005）。periods の %d 件目。"
            "出力は PYTHONDONTWRITEBYTECODE=1 python3 -B %s%s の標準出力。"
            "封印したことは公開しない（オーナーの決定）。"
            % (version, PERIODS_SCRIPT, "".join(" " + a for a in extra_args)))
    records = ledger.append_record(ledger_path, KIND, targets, note, now)
    seq = records[-1]["seq"]

    # 7
    if ots_cmd is None:
        return records[-1], None, []
    ots_path, err, submitted = stamp.stamp_seq(ledger_path, seq, ots_cmd, runner=runner)
    return records[-1], ots_path, submitted


def main(argv=None):
    p = argparse.ArgumentParser(allow_abbrev=False, description=__doc__.splitlines()[0])
    p.add_argument("--expect-output-sha256", required=True)
    p.add_argument("--ots", default=stamp.DEFAULT_OTS)
    p.add_argument("periods_args", nargs="*")
    a = p.parse_args(argv)
    now = datetime.datetime.now(datetime.timezone.utc)
    try:
        rec, ots_path, submitted = seal(PROJECT, a.expect_output_sha256.lower(),
                                        a.periods_args, now, a.ots)
    except ledger.LedgerError as e:
        print("失敗: %s" % e, file=sys.stderr)
        return 1
    print(ledger.canonical_line(rec).decode("utf-8"))
    print("時刻証明: %s" % os.path.relpath(ots_path, PROJECT))
    print("送った先: %s" % ", ".join(submitted))
    return 0


if __name__ == "__main__":
    sys.exit(main())
