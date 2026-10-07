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

いつ呼ぶか（T-031 の差し戻し1回目の中3）
  gkg-run-start は、収集係のマニフェストの run-start の行 1 件につき 1 件だけ書く。run の最初の実行
  （run-start の行を書く実行）で、要求を送る前に 1 回だけ呼び、同じ run の再開では呼ばない。
  そのため、試しの run の回数は gkg-run-start（trial）の件数と同じになる。同じ run_id の trial を
  2 件書こうとすると止まる。正式な run の 2 回目の実行（run-start を書いて止まったあとの実行）
  でも呼ばない。

拒むもの（何も書かずに止める）
  drand を取りにいく前に止まるもの：
  - periods の記録が無い。記録の鎖か .ots の検証に通らない。
  - method-access の記録が無い（gkg-run-start は手順4の記録の後）。
  - 除外の規則の kind（stats-order1）の記録が無い。exclusion_rule_seq がその最初の記録の seq でない。
    順番1b（stats-order1b）の記録が無い。順番1・1b の中身が照合（ledger.check_stats_order）に通らない
    （T-037。T-031 の監査 中2）。
  - threshold-access の記録がある（閾値を決める期間に触れたあとで、手法を作る期間の GKG の
    取得を始めない。T-031 の中2）。
  - official の記録が既にある（正式な run は 1 件だけ。trial は official より前だけ）。
  - trial で、同じ run_id の trial の記録が既にある。trial_days が 1〜3 日でない（T-031 の中3）。
  - 取得のコードが、HEAD のコミットの中身と同じでない。run_id がその sha256 の先頭 16 桁でない。
  drand を取ったあと、書く前に止まるもの（seal_records.check_new）：
  - 中身の照合（ledger.check_gkg_run_doc・check_gkg_runs）に通らない。例えば、一覧の sha256 が
    最初の method-access より前のただ 1 件の acquisition-result と違う、除外の規則の記録が最初の
    gkg-run-start より前に無い、ほかの gkg-run-start と入力（一覧・除外の規則・method-access）が違う。

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
    # T-037（T-031 の監査 中2）：除外の規則の kind（stats-order1）の記録と、順番1b の記録が要る
    if ledger.first_order1(records) is None:
        raise ledger.LedgerError("除外の規則の kind（%s）の記録が無い。gkg-run-start は順番1の封印の後に書く。"
                                 "追記しない" % ledger.ORDER1_KIND)
    if not any(r["kind"] == ledger.ORDER1B_KIND for r in records):
        raise ledger.LedgerError("順番1b（%s）の記録が無い。gkg-run-start は順番1b の封印の後に書く"
                                 "（docs/stats/seal-order1.md 3章 (3)）。追記しない" % ledger.ORDER1B_KIND)
    # 順番1・1b の中身（必須のファイル、正式な数え方など）と数も、drand の前に照らす（T-037 の差し戻し1回目 中2）
    ledger.check_stats_order(records, lambda r, role: ledger.read_target_json(project, r, role))
    cut = ledger.first_threshold_access(records)
    if cut is not None:
        raise ledger.LedgerError("threshold-access の記録（seq %d）がある。閾値を決める期間に触れたあとで、"
                                 "手法を作る期間の GKG の取得を始めない。追記しない" % cut["seq"])
    runs = ledger.check_gkg_runs(records, lambda r, role: ledger.read_target_json(project, r, role))
    modes = [(r["seq"], d["mode"]) for r, d in runs] + [(len(records) + 1, mode)]
    ledger.check_gkg_run_modes(modes)
    return runs


def start(project, mode, code_rel, run_id, filelist_sha256, method_access_seq, trial_days,
          exclusion_rule_seq, exclusion_rule_record_sha256, now, ots_cmd, drand_fetch=None,
          runner=subprocess.run):
    """gkg-run-start を 1 件追記する。返り値: (記録, 中身のパス, .ots のパス か None)。"""
    data, records = seal_records.load_checked(project, ots_cmd, runner=runner)
    runs = _precheck(project, records, mode)
    o1 = ledger.first_order1(records)
    if exclusion_rule_seq != o1["seq"]:
        raise ledger.LedgerError("exclusion_rule_seq %r が、除外の規則の kind（%s）の最初の記録の seq %d でない。"
                                 "追記しない" % (exclusion_rule_seq, ledger.ORDER1_KIND, o1["seq"]))
    if mode == "trial":
        same = [r["seq"] for r, d in runs if d["mode"] == "trial" and d["run_id"] == run_id]
        if same:
            raise ledger.LedgerError("同じ run_id %s の trial の記録（seq %d）が既にある。gkg-run-start は run の"
                                     "最初の実行で 1 件だけ書き、再開では書かない。追記しない"
                                     % (run_id, same[0]))
        if not isinstance(trial_days, (list, tuple)) or not 0 < len(trial_days) <= ledger.TRIAL_DAYS_MAX:
            raise ledger.LedgerError("trial_days は 1〜%d 日の一覧。追記しない" % ledger.TRIAL_DAYS_MAX)
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
