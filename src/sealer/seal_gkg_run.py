#!/usr/bin/env python3
"""GKG の取得の run（試しの run・正式な run）の開始の記録（kind: gkg-run-start）を書く仕組み。T-031。

目的：試しの run を何回行ったか、どの run を入力に使ったか（正式な run）を、追記のみで時刻証明の
付く記録から、第三者が数えられるようにする（reviews/T-030.md）。手順書は
docs/verify/periods-seal.md 12章。

収集係の取得のコード（src/collector/acquire_gkg.py）は、関門（ledger.require_method_access）を
通ったあと、GKG への要求を送る前に start(...) を呼ぶ。返り値の記録の seq を控える。

    import seal_gkg_run
    rec, rel, ots_path = seal_gkg_run.start(
        project, mode, code_rel, run_id, filelist_sha256, method_access_seq, trial_days,
        exclusion_rule_seq, exclusion_rule_record_sha256, now, ots_cmd)

    mode                           "trial" か "official"
    code_rel                       取得の入口のコードの、ルートからの相対パス
                                   （src/collector/acquire_gkg.py）。HEAD のコミットの中身と同じで
                                   なければ止まる。その sha256 が code_sha256 になる
    run_id                         code_sha256 の先頭 16 桁（違えば止まる）
    filelist_sha256                使うファイル一覧の sha256。acquisition-result の kept_rows_sha256
    method_access_seq              最初の method-access の記録の seq
    trial_days                     試しの run の日（YYYY-MM-DD の list）。official なら None
    exclusion_rule_seq             除外の規則の封印の記録の seq
    exclusion_rule_record_sha256   その記録の行の正規の形の sha256
    now                            datetime（UTC）
    ots_cmd                        ots のコマンド（stamp.DEFAULT_OTS）。None なら .ots を作らない
                                   （テストだけ）
    drand_fetch・runner            通信の差し替え（テストだけ）

拒むもの（何も書かずに止める。drand を取りにいく前に止まるものを先に確かめる）
  - periods の記録が無い。記録の鎖か .ots の検証に通らない。
  - method-access の記録が無い（gkg-run-start は手順4の記録の後）。
  - official の記録が既にある（正式な run は 1 件だけ。trial は official より前だけ）。
  - 取得のコードが、HEAD のコミットの中身と同じでない。
  - 中身の照合（ledger.check_gkg_run_doc）に通らない。

中身に入れるのは公開してよい値だけである。保存先（ディスクやフォルダ）、ユーザー名、VolumeUUID は
入れない。採用の規則（threshold-access による区切り）には使わない。

CLI（プロジェクトのルートで。ots と drand の通信を使うので .venv の python で実行する）
    PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -B src/sealer/seal_gkg_run.py start \\
        --mode trial --code src/collector/acquire_gkg.py --run-id <16 桁> \\
        --filelist-sha256 <64 桁> --method-access-seq N \\
        --trial-day 2015-03-02 --trial-day 2015-03-03 --trial-day 2015-03-04 \\
        --exclusion-rule-seq M --exclusion-rule-record-sha256 <64 桁>
"""

import argparse
import datetime
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import ledger  # noqa: E402
import seal_acquisition  # noqa: E402
import seal_records  # noqa: E402
import stamp  # noqa: E402

PROJECT = os.path.dirname(os.path.dirname(HERE))
STEP = 4


def _precheck(project, records, mode):
    """drand を取りにいく前に止められるもの。"""
    if mode not in ledger.GKG_RUN_MODES:
        raise ledger.LedgerError("mode は trial か official だけ。追記しない")
    if ledger.check_method_access_order(records) == []:
        raise ledger.LedgerError("method-access の記録が無い。gkg-run-start は手順4の記録の後に書く。"
                                 "追記しない")
    runs = ledger.check_gkg_runs(records, lambda r, role: ledger.read_target_json(project, r, role))
    modes = [(r["seq"], d["mode"]) for r, d in runs] + [(len(records) + 1, mode)]
    ledger.check_gkg_run_modes(modes)


def start(project, mode, code_rel, run_id, filelist_sha256, method_access_seq, trial_days,
          exclusion_rule_seq, exclusion_rule_record_sha256, now, ots_cmd, drand_fetch=None,
          runner=subprocess.run):
    """gkg-run-start を 1 件追記する。返り値: (記録, 中身のパス, .ots のパス か None)。"""
    data, records = seal_records.load_checked(project, ots_cmd, runner=runner)
    _precheck(project, records, mode)
    code_path, code_sha = seal_acquisition.committed_code_sha256(project, code_rel)
    if run_id != code_sha[:16]:
        raise ledger.LedgerError("run_id %r が、取得のコードの sha256 の先頭 16 桁 %s と違う。追記しない"
                                 % (run_id, code_sha[:16]))
    doc = {
        "kind": ledger.GKG_RUN_KIND,
        "step": STEP,
        "mode": mode,
        "run_id": run_id,
        "code_path": code_path,
        "code_sha256": code_sha,
        "filelist_sha256": filelist_sha256,
        "method_access_seq": method_access_seq,
        "trial_days": None if trial_days is None else list(trial_days),
        "exclusion_rule_seq": exclusion_rule_seq,
        "exclusion_rule_record_sha256": exclusion_rule_record_sha256,
        "drand": seal_records.drand_part(now, drand_fetch),
        "ledger_head": ledger.expected_ledger_head(data, len(records) + 1),
    }
    n = sum(1 for r in records if r["kind"] == ledger.GKG_RUN_KIND) + 1
    note = ("GKG の取得の run の開始（%s。run_id %s）。gkg-run-start の %d 件目。採用の区切りには使わない。"
            % ("試しの run" if mode == "trial" else "正式な run", run_id, n))
    return seal_records.write_doc_record(project, ledger.GKG_RUN_KIND, doc, data, note, now,
                                         ots_cmd, runner=runner)


def main(argv=None):
    p = argparse.ArgumentParser(allow_abbrev=False, description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest="action", required=True)
    s = sub.add_parser("start", allow_abbrev=False)
    s.add_argument("--mode", required=True, choices=ledger.GKG_RUN_MODES)
    s.add_argument("--code", required=True)
    s.add_argument("--run-id", required=True)
    s.add_argument("--filelist-sha256", required=True)
    s.add_argument("--method-access-seq", type=int, required=True)
    s.add_argument("--trial-day", action="append", default=None)
    s.add_argument("--exclusion-rule-seq", type=int, required=True)
    s.add_argument("--exclusion-rule-record-sha256", required=True)
    s.add_argument("--ots", default=stamp.DEFAULT_OTS)
    s.add_argument("--root", default=PROJECT)
    a = p.parse_args(argv)
    root = os.path.abspath(a.root)
    now = datetime.datetime.now(datetime.timezone.utc)
    try:
        rec, rel, ots_path = start(root, a.mode, a.code, a.run_id, a.filelist_sha256,
                                   a.method_access_seq, a.trial_day, a.exclusion_rule_seq,
                                   a.exclusion_rule_record_sha256, now, a.ots)
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
