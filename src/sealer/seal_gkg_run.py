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
    days・files_selected           （T-068。キーワード）取得する日の数とファイルの数（計画）。データを受け取る
                                   前に縛る。gkg.py の run-start の行の days・files_selected と同じ値
    plan_sha256                    （T-070。キーワード）計画の一覧の正規の形（ledger.gkg_plan_canonical）の sha256
    exclusion_rule_seq             除外の規則の封印の記録の seq
    exclusion_rule_record_sha256   その記録の行の正規の形の sha256
    now                            datetime（UTC）
    ots_cmd                        ots のコマンド（stamp.DEFAULT_OTS）。None なら .ots を作らない
                                   （テストだけ）
    drand_fetch・runner            通信の差し替え（テストだけ）

使い回し（T-043。T-041 の監査 中-1）
  同じ mode・run_id の gkg-run-start が既にあり、入力（上の 7 つ）がすべて同じで、マニフェスト（作業
  ツリーと HEAD の版）にまだその run-start の行が無ければ、新しく書かずに、その記録（と中身のパス・
  .ots のパス）を返す。ots の stamp が失敗したあと（記録は残り、.ots は
  `stamp.py stamp --seq N` で後から作る。作るまでは鎖の検証が止まる）や、記録を書いたあと run-start の
  行を書く前に止まったあとの、正直なやり直しで、記録が先へ進めなくならないようにするため。入力が
  一つでも違えば止まるので、結果を見てから入力を選び直す道にはならない。

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
  - official の記録が既にある（正式な run は 1 件だけ。trial は official より前だけ）。ただし下の
    「使い回し」に当たるときは、新しく書かずに既にある記録を返す。
  - 同じ mode・run_id の記録が既にあるのに、入力（code_sha256・filelist_sha256・method_access_seq・
    exclusion_rule_seq・その sha256・trial_days）が違うか、その記録に run-start の行が既にある。
    trial_days が 1〜3 日でない（T-031 の中3）。
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
import json
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
    return ledger.check_gkg_runs(records, lambda r, role: ledger.read_target_json(project, r, role))


def _manifest_run_start_rows(project, mode):
    """作業ツリーと HEAD の版のマニフェスト（その mode）の run-start の行。無ければ空。"""
    rel = ledger.GKG_MANIFESTS[mode]
    bodies = []
    full = os.path.join(project, rel)
    if os.path.isfile(full) and not os.path.islink(full):
        with open(full, "rb") as f:
            bodies.append(f.read())
    r = subprocess.run(["git", "-C", project, "show", "HEAD:%s" % rel], capture_output=True)
    if r.returncode == 0:
        bodies.append(r.stdout)
    rows = []
    for body in bodies:
        for raw in body.split(b"\n"):
            try:
                row = json.loads(raw.decode("utf-8")) if raw.strip() else None
            except (UnicodeDecodeError, ValueError):
                raise ledger.LedgerError("%s に JSON として読めない行がある。使い回さない" % rel) from None
            if isinstance(row, dict) and row.get("kind") == "run-start":
                rows.append(row)
    return rows


def _reuse(project, records, runs, mode, run_id, code_sha, filelist_sha256, method_access_seq,
           trial_days, exclusion_rule_seq, exclusion_rule_record_sha256, ots_cmd, runner, plan=None):
    """同じ mode・run_id の gkg-run-start が既にあれば、それを使い回す（T-043。T-041 の監査 中-1）。

    stamp が失敗したあと（記録は ledger に残り、.ots は stamp.py stamp --seq N で後から作る）や、
    記録を書いたあと run-start の行を書く前に止まったあとの、正直なやり直しのため。使い回すのは、
    次のすべてが同じで、まだ run-start の行が無い記録だけ（結果を見てから run を選び直す道は作らない）：
    mode・run_id・code_sha256・filelist_sha256・method_access_seq・exclusion_rule_seq・
    exclusion_rule_record_sha256・trial_days。run-start の行は、作業ツリーと HEAD の版のマニフェストで探す。
    trial は、official の記録が既にあれば使い回さない（試しの run は正式な run の前だけ）。
    返り値: (記録, 中身のパス, .ots のパス) か None（使い回す記録が無い）。
    """
    same = [(r, d) for r, d in runs if d["mode"] == mode and d["run_id"] == run_id]
    if not same:
        return None
    rec, d = same[0]
    want = {"code_sha256": code_sha, "filelist_sha256": filelist_sha256,
            "method_access_seq": method_access_seq, "exclusion_rule_seq": exclusion_rule_seq,
            "exclusion_rule_record_sha256": exclusion_rule_record_sha256,
            "trial_days": None if trial_days is None else list(trial_days)}
    # T-068：計画（days・files_selected）も同じでなければ使い回さない（計画を持たない古い形の記録は、計画を
    # 渡さないときだけ使い回せる）
    for k in ledger.GKG_RUN_PLAN_KEYS + (ledger.GKG_RUN_PLAN_SHA_KEY,):
        want[k] = None if plan is None else plan.get(k)
    diff = sorted(k for k, v in want.items() if d.get(k) != v)
    if diff:
        raise ledger.LedgerError("同じ mode・run_id %s の gkg-run-start（seq %d）が既にあるが、%s が違う。"
                                 "使い回さず、追記もしない" % (run_id, rec["seq"], "・".join(diff)))
    if mode == "trial" and any(x["mode"] == "official" for _r, x in runs):
        raise ledger.LedgerError("official の記録があるので、試しの run の記録（seq %d）は使い回さない。追記しない"
                                 % rec["seq"])
    for row in _manifest_run_start_rows(project, mode):
        if row.get("gkg_run_seq") == rec["seq"] or row.get("run_id") == run_id:
            raise ledger.LedgerError("gkg-run-start（seq %d）には run-start の行が既にある（run は始まっている）。"
                                     "再開では書かない。使い回さない" % rec["seq"])
    rel = ledger.output_target(rec, ledger.GKG_RUN_KIND)["path"]
    ots_path = os.path.join(project, "sealed", ledger.ots_name(rec["seq"]))
    return rec, rel, ots_path


def start(project, mode, code_rel, run_id, filelist_sha256, method_access_seq, trial_days,
          exclusion_rule_seq, exclusion_rule_record_sha256, now, ots_cmd, drand_fetch=None,
          runner=subprocess.run, days=None, files_selected=None, plan_sha256=None):
    """gkg-run-start を 1 件追記する（または、同じ run の記録を使い回す。_reuse）。
    days・files_selected（T-068）：取得する日の数とファイルの数（収集係の計画。gkg.py の run-start の行の
    days・files_selected と同じ値）。データを受け取る前に縛る。ledger.GKG_RUN_PLAN_REQUIRED_FOR_OFFICIAL が
    True なら official では必ず渡す（渡さなければ止まる。収集係が渡すようになる T-069 のあとに True にする）。
    渡さなければ、計画を持たない古い形で書く。
    plan_sha256（T-070）：取得する日とファイルの一覧（収集係の select_files の出力。試しの run は trial_plan）の
    正規の形（ledger.gkg_plan_canonical）の sha256。渡すときは days・files_selected も渡す。
    GKG_RUN_PLAN_REQUIRED_FOR_OFFICIAL が True なら、official では 3つとも必ず渡す。
    返り値: (記録, 中身のパス, .ots のパス か None)。"""
    project = os.path.abspath(project)
    if (days is None) != (files_selected is None):
        raise ledger.LedgerError("days と files_selected は、両方渡すか両方渡さない。追記しない")
    if plan_sha256 is not None and days is None:
        raise ledger.LedgerError("plan_sha256 を渡すときは、days・files_selected も渡す。追記しない")
    if mode == "official" and plan_sha256 is None and ledger.GKG_RUN_PLAN_REQUIRED_FOR_OFFICIAL:
        raise ledger.LedgerError("正式な run（official）は、取得の計画（days・files_selected・plan_sha256）を渡す"
                                 "（T-068、T-070）。追記しない")
    plan = None
    if days is not None:
        if type(days) is not int or days < 1 or type(files_selected) is not int or files_selected < 1:
            raise ledger.LedgerError("days・files_selected は 1 以上の整数。追記しない")
        plan = {"days": days, "files_selected": files_selected}
        if plan_sha256 is not None:
            if not isinstance(plan_sha256, str) or not ledger.HEX64.match(plan_sha256):
                raise ledger.LedgerError("plan_sha256 は 64 桁の16進。追記しない")
            plan[ledger.GKG_RUN_PLAN_SHA_KEY] = plan_sha256
    data, records = seal_records.load_checked(project, ots_cmd, runner=runner)
    runs = _precheck(project, records, mode)
    o1 = ledger.first_order1(records)
    if exclusion_rule_seq != o1["seq"]:
        raise ledger.LedgerError("exclusion_rule_seq %r が、除外の規則の kind（%s）の最初の記録の seq %d でない。"
                                 "追記しない" % (exclusion_rule_seq, ledger.ORDER1_KIND, o1["seq"]))
    if mode == "trial" and (not isinstance(trial_days, (list, tuple))
                            or not 0 < len(trial_days) <= ledger.TRIAL_DAYS_MAX):
        raise ledger.LedgerError("trial_days は 1〜%d 日の一覧。追記しない" % ledger.TRIAL_DAYS_MAX)
    code_path, code_sha = seal_acquisition.committed_code_sha256(project, code_rel)
    if run_id != code_sha[:16]:
        raise ledger.LedgerError("run_id %r が、取得のコードの sha256 の先頭 16 桁 %s と違う。追記しない"
                                 % (run_id, code_sha[:16]))
    reused = _reuse(project, records, runs, mode, run_id, code_sha, filelist_sha256, method_access_seq,
                    trial_days, exclusion_rule_seq, exclusion_rule_record_sha256, ots_cmd, runner, plan)
    if reused is not None:
        return reused
    ledger.check_gkg_run_modes([(r["seq"], d["mode"]) for r, d in runs] + [(len(records) + 1, mode)])
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
    if plan is not None:
        doc.update(plan)
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
    s.add_argument("--days", type=int, default=None)
    s.add_argument("--files-selected", type=int, default=None)
    s.add_argument("--plan-sha256", default=None)
    s.add_argument("--ots", default=stamp.DEFAULT_OTS)
    s.add_argument("--root", default=PROJECT)
    a = p.parse_args(argv)
    root = os.path.abspath(a.root)
    now = datetime.datetime.now(datetime.timezone.utc)
    try:
        rec, rel, ots_path = start(root, a.mode, a.code, a.run_id, a.filelist_sha256,
                                   a.method_access_seq, a.trial_day, a.exclusion_rule_seq,
                                   a.exclusion_rule_record_sha256, now, a.ots, days=a.days,
                                   files_selected=a.files_selected, plan_sha256=a.plan_sha256)
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
