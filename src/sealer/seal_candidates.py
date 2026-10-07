#!/usr/bin/env python3
"""閾値と判定期間の候補の封印（kind: candidates）。T-013。

CLAUDE.md の「閾値の決め方」：閾値と判定期間の候補は、手法を作る期間のデータに触れる前に
決めて封印する。この仕組みは src/stats/candidates.py の出力をそのまま封印するだけで、値を
選ばない。

使い方（プロジェクトのルートで。ots を使うので .venv の python で実行する）
    PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -B src/sealer/seal_candidates.py \\
        --expect-output-sha256 <出力の sha256>

手順（この順で行い、途中で失敗したら、それより後のことはしない）
  1. 今の記録の鎖と、すべての seq の .ots を検証する。ots が実行できることを確かめる。
  2. 封印の時機の検査。どれかに当たれば止める。
     - periods の記録が無い（候補は期間の区切りに合わせて作るため、区切りの封印が先）
     - acquisition-start の記録がある（候補は手法を作る期間のデータに触れる前に封印する。
       検証の check_candidates_order が、後ろの candidates を失敗にする）
     - threshold-access の記録がある（その後の candidates は採用されないため）
     - data/ の下に .gitkeep 以外のファイルがある（seal_periods.data_started と同じ。
       このリポジトリの data/ の下だけを調べる手元の検査）
  3. 対象のファイル（ledger.CANDIDATES_SOURCES の 4 つ）が、HEAD のコミットの中身と同じで
     あることを確かめる。第三者がコミットの中のファイルで照合できるようにするため。
  4. src/stats/candidates.py を引数なしで実行し、標準出力のバイト列を得る。sha256 が
     --expect-output-sha256 と一致し、出力の形が照合（ledger.check_candidates_output）に
     通ることを確かめる。
  5. 追記する行を作り、「今の記録 + その行」に、検証と同じ照合をする
     （check_candidates_record・check_candidates_order）。
  6. 出力を sealed/candidates-output-<sha256>.json として新しく書く（上書きしない）。
  7. 記録に 1 件追記する。1 で読んだ時点から記録が変わっていれば追記しない。
  8. その seq 自身の .ots を作る（ots stamp。ネットワークを使う）。8 が失敗したときは、
     `stamp.py stamp --seq N` で .ots を作ってから進める（記録は書き換えない）。

版の番号は記録に書かない。candidates の記録の何件目かで決まる（ledger.version_of）。
採用は検証（verify.py adopted）が鎖の順番で決める。
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
import seal_periods  # noqa: E402
import stamp  # noqa: E402

PROJECT = os.path.dirname(os.path.dirname(HERE))
KIND = ledger.CANDIDATES_KIND


def run_candidates(project):
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    cmd = [sys.executable, "-B", os.path.join(project, ledger.CANDIDATES_SCRIPT)]
    r = subprocess.run(cmd, capture_output=True, env=env, cwd=project, timeout=120)
    if r.returncode != 0:
        raise ledger.LedgerError("candidates.py が失敗した（終了コード %d）" % r.returncode)
    return r.stdout


def check_committed(project, rel):
    """rel の作業ツリーの中身が HEAD のコミットの中身と同じなら、その sha256 を返す。"""
    full = os.path.join(project, rel)
    if not os.path.isfile(full) or os.path.islink(full):
        raise ledger.LedgerError("対象のファイルが無い（または通常のファイルでない）: %s" % rel)
    with open(full, "rb") as f:
        work = f.read()
    r = subprocess.run(["git", "-C", project, "show", "HEAD:%s" % rel], capture_output=True)
    if r.returncode != 0:
        raise ledger.LedgerError("対象のファイルが HEAD のコミットに無い: %s" % rel)
    if r.stdout != work:
        raise ledger.LedgerError("対象のファイルが HEAD のコミットの中身と違う"
                                 "（作業ツリーで変えている）: %s" % rel)
    return ledger.sha256_hex(work)


def check_timing(project, records):
    """手順 2。封印してよい時機でなければ LedgerError。"""
    if not ledger.records_of_kind(records, ledger.PERIODS_KIND):
        raise ledger.LedgerError("periods の記録が無い（期間の区切りの封印が先）。封印しない")
    start = ledger.first_acquisition_start(records)
    if start is not None:
        raise ledger.LedgerError("acquisition-start の記録（seq %d）がある。候補は手法を作る期間の"
                                 "データに触れる前に封印する決まりなので、封印しない"
                                 % start["seq"])
    cut = ledger.first_threshold_access(records)
    if cut is not None:
        raise ledger.LedgerError("threshold-access の記録（seq %d）がある。封印しない" % cut["seq"])
    started = seal_periods.data_started(project)
    if started:
        raise ledger.LedgerError("データの取得が始まっている（%s）。封印しない"
                                 % ", ".join(sorted(started)))


def seal(project, expect_sha, now, ots_cmd, runner=subprocess.run, require_committed=True):
    """返り値: (記録, .ots のパス か None, 送った先の一覧)。"""
    ledger.check_sealed_inside(project)    # T-017：sealed/ が別の場所を指していれば何もしない
    sealed_dir = os.path.join(project, "sealed")
    ledger_path = os.path.join(sealed_dir, "ledger.jsonl")

    # 1
    data = ledger.read_ledger(ledger_path)
    records = ledger.verify_chain(data)
    if records:
        ledger.check_anchors(data, sealed_dir)
    if ots_cmd is not None:
        stamp.check_ots(ots_cmd, runner=runner)

    # 2
    check_timing(project, records)

    # 3
    targets = []
    for rel, role in ledger.CANDIDATES_SOURCES:
        if require_committed:
            sha = check_committed(project, rel)
        else:
            sha = ledger.sha256_file(os.path.join(project, rel))
        targets.append({"path": rel, "role": role, "sha256": sha})

    # 4
    out = run_candidates(project)
    out_sha = ledger.sha256_hex(out)
    if out_sha != expect_sha:
        raise ledger.LedgerError("出力の sha256 が期待と違う: %s" % out_sha)
    try:
        output = json.loads(out.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise ledger.LedgerError("candidates.py の出力が JSON として読めない") from None
    ledger.check_candidates_output(output)

    # 5
    out_rel = ledger.candidates_output_rel(out_sha)
    targets.append({"path": out_rel, "role": "output", "sha256": out_sha})
    version = len(ledger.records_of_kind(records, KIND)) + 1
    note = ("閾値と判定期間の候補（T-011 の案、オーナー承認 2026-10-06、T-013）。candidates の"
            " %d 件目。出力は PYTHONDONTWRITEBYTECODE=1 python3 -B %s の標準出力。"
            "封印したことは公開しない（オーナーの決定）。" % (version, ledger.CANDIDATES_SCRIPT))
    _recs, rec, line = ledger.build_next_record(data, KIND, targets, note, now)
    records_after = ledger.verify_chain(data + line)
    ledger.check_candidates_record(rec)
    ledger.check_candidates_order(records_after)

    # 6
    ledger.write_once(os.path.join(project, out_rel), out)

    # 7
    after = ledger.append_record(ledger_path, KIND, targets, note, now, expected_data=data)
    if after[-1] != rec:
        raise ledger.LedgerError("追記した記録が、照合した記録と一致しない")

    # 8
    if ots_cmd is None:
        return rec, None, []
    ots_path, _err, submitted = stamp.stamp_seq(ledger_path, rec["seq"], ots_cmd, runner=runner)
    return rec, ots_path, submitted


def main(argv=None):
    p = argparse.ArgumentParser(allow_abbrev=False, description=__doc__.splitlines()[0])
    p.add_argument("--expect-output-sha256", required=True)
    p.add_argument("--ots", default=stamp.DEFAULT_OTS)
    a = p.parse_args(argv)
    now = datetime.datetime.now(datetime.timezone.utc)
    try:
        rec, ots_path, submitted = seal(PROJECT, a.expect_output_sha256.lower(), now, a.ots)
    except ledger.LedgerError as e:
        print("失敗: %s" % e, file=sys.stderr)
        return 1
    print(ledger.canonical_line(rec).decode("utf-8"))
    print("時刻証明: %s" % os.path.relpath(ots_path, PROJECT))
    print("送った先: %s" % ", ".join(submitted))
    return 0


if __name__ == "__main__":
    sys.exit(main())
