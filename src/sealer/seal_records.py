#!/usr/bin/env python3
"""threshold-access・acquisition-start・acquisition-result・method-access・gkg-run-start・gkg-run-result を書く共通の手順。
T-009、T-014。

使うのは seal_access.py、seal_acquisition.py、seal_method.py、seal_gkg_run.py（T-031）。中身の形と照合は
docs/verify/periods-seal.md 7章、ledger.py の check_drand_record・acquisition_result_fields・
check_acquisition_pairs と同じ。

手順（この順で行い、途中で失敗したら、それより後のことはしない）
  1. sealed/ と記録のファイルの実体がプロジェクトの下にあること（T-017。ledger.check_sealed_inside）、
     今の記録の鎖と、すべての seq の .ots を検証する。ots が実行できることを確かめる。
  2. 中身（JSON）を作る。drand を使う種類では、ここで drand の最新の回を取る（1 の後なので、
     回はできるだけ追記の直前のものになる）。ledger_head は 1 で読んだ記録から作る。
  3. 追記する行を作り、「今の記録 + その行」に対して、検証（verify.py）と同じ照合をする。
       - 鎖（kind が許可リストにあること、正規の形、seq、prev_hash）
       - 中身の kind が記録の kind と同じこと
       - threshold-access：ledger_head、drand、block_start（periods の 1 件目の閾値の期間の始まり）、
         その前に candidates の記録があり、候補の順序の照合に通ること（T-014）、
         J とエンバーゴの照合（T-017、T-023。ledger.check_horizon_embargo）
         periods の deadline_status の照合（T-027。ledger.check_deadline_statuses。verify periods と同じ規則）
       - acquisition-start：ledger_head、drand、step = 3、fetch（取得のコードのパスと sha256）、
         その前に candidates の記録があること（T-014。check_candidates_order）
       - method-access：ledger_head、drand、step = 4、区画（periods の 1 件目の method の区画）、
         仮の採用での deadline_status（T-031。ledger.check_deadline_statuses(provisional=True)）、
         その前に candidates と acquisition-result の記録があること（T-014）、
         J とエンバーゴの照合（T-017、T-023。ledger.check_horizon_embargo）
       - gkg-run-start（T-031）：ledger_head、drand、step = 4、中身の 13 個のキーと値
         （ledger.check_gkg_run_doc）、順序（method-access より後、official は 1 件だけ、
         trial は official より前だけ。ledger.check_gkg_runs）
       - stats-order1・stats-order1b（T-037）：ledger_head。どの種類でも、順番1・1b の照合
         （ledger.check_stats_order：順番1 は 1 件だけ、中身が check_order1_doc・check_order1b_doc に
         通る、順番1・1b は最初の method-access より前、gkg-run-start の前に順番1b）。
         method-access の前に順番1 は求めない（収集係のテストを直すタスクのあと）。区分表の取得は
         ledger に書かれないので、その前後は verify.py stats-order が git の履歴で照らす
       - stats-order2（T-073・T-078）：ledger_head、形（ledger.check_order2_run・check_order2_doc。check_stats_order の
         中）、HEAD のマニフェストからの行き先と runs・inputs（ledger.check_order2_plan）、head が今の HEAD、コードの版と
         時機の条件の計算し直し（verify.check_order2_git）。書く入口は seal_order2.py
       - gkg-run-result（T-066）：ledger_head、中身の 11 個のキー、指す gkg-run-start、マニフェストの先頭の
         manifest_lines 行の sha256 と run-complete の行（ledger.check_gkg_result_doc・check_gkg_results）、
         マニフェストの行の照合（ledger.check_gkg_manifests）
       - acquisition-result：start_seq・kept_rows_sha256 の形、start が実在し、result が後にあり、
         一つの start に result が一つだけであること
     どれかが通らなければ、何も書かずに止める。
  4. 中身を sealed/<kind>-<sha256>.json として新しく書く（既にあれば上書きしない）。
  5. 記録に 1 件追記する。1 で読んだ時点から記録が変わっていれば追記しない。
  6. その seq 自身の .ots を作る（ots stamp。ネットワークを使う）。
     6 が失敗したときは、記録はあるが .ots が無い状態になる。この状態では、次の追記と検証が
     止まる。`stamp.py stamp --seq N` で .ots を作ってから進める（記録は書き換えない）。
     6 が失敗しても、5 で追記した記録は鎖に残り、取り消せない。threshold-access なら、
     その時点で採用の区切りが決まる（docs/verify/periods-seal.md 7章。T-009 の監査 軽3）。

通信を差し替えられるところ
  drand_fetch：netfetch.http_get の代わり（URL → 応答のバイト列）
  runner：subprocess.run の代わり（ots stamp）
"""

import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import ledger  # noqa: E402
import netfetch  # noqa: E402
import stamp  # noqa: E402
import verify  # noqa: E402  T-078：順番2の記録の git を使う照合（verify と同じ関数）
COLLECTOR = os.path.join(os.path.dirname(HERE), "collector")


def load_privacy_scan():
    """収集係の検査器 src/collector/privacy_scan.py を読み込む（読むだけ。書き換えない）。順番2を書くときだけ要るので、
    使うときに読む（src/sealer だけを写した仮のプロジェクトでも、ほかの種類の書く仕組みが動くように）。"""
    if COLLECTOR not in sys.path:
        sys.path.append(COLLECTOR)
    try:
        import privacy_scan
    except ImportError:
        raise ledger.LedgerError("src/collector/privacy_scan.py を読み込めない。書かない") from None
    return privacy_scan


def check_privacy(rec, doc):
    """記録の行と中身の全体に、privacy_scan と同じ検査（許可していないメールアドレスの形）をかける（T-078 差し戻し1回目
    中-3。順番2の記録には参照の名前などが入るため）。当たれば LedgerError（何も書かない）。見つけた文字列は出さない。"""
    privacy_scan = load_privacy_scan()
    for what, data in (("記録の行", ledger.canonical_line(rec)), ("中身", ledger.canonical_line(doc))):
        hits = privacy_scan.find_in_bytes(data)
        if hits:
            raise ledger.LedgerError("%s の%sに、許可していないメールアドレスの形がある（%d か所。privacy_scan と同じ検査。"
                                     "参照の名前などを確かめる）。書かない" % (rec["kind"], what, sum(hits.values())))


WRITTEN_KINDS = (ledger.THRESHOLD_ACCESS_KIND, ledger.ACQ_START_KIND, ledger.ACQ_RESULT_KIND,
                 ledger.METHOD_ACCESS_KIND, ledger.GKG_RUN_KIND, ledger.ORDER1_KIND,
                 ledger.ORDER1B_KIND, ledger.GKG_RESULT_KIND, ledger.ORDER2_KIND)


def _paths(project):
    sealed = os.path.join(project, "sealed")
    return sealed, os.path.join(sealed, "ledger.jsonl")


def load_checked(project, ots_cmd, runner=subprocess.run):
    """手順 1。(記録のバイト列, 記録の一覧) を返す。"""
    ledger.check_sealed_inside(project)    # T-017：sealed/ が別の場所を指していないこと
    sealed, ledger_path = _paths(project)
    data = ledger.read_ledger(ledger_path)
    records = ledger.verify_chain(data)
    if records:
        ledger.check_anchors(data, sealed)
    if not ledger.records_of_kind(records, ledger.PERIODS_KIND):
        raise ledger.LedgerError("periods の記録が無い（期間の区切りの封印が先）。追記しない")
    if ots_cmd is not None:
        stamp.check_ots(ots_cmd, runner=runner)
    return data, records


def drand_part(now, drand_fetch):
    return netfetch.latest_drand(now, fetch=drand_fetch or netfetch.http_get)


def result_refs(project, records, extra=None):
    """{acquisition-result の seq: start_seq}。既存の result の中身はファイルから読んで照合する。"""
    refs = {}
    for r in records:
        if r["kind"] != ledger.ACQ_RESULT_KIND:
            continue
        if extra is not None and r["seq"] == extra[0]["seq"]:
            doc = extra[1]
        else:
            doc = ledger.read_target_json(project, r, ledger.ACQ_RESULT_KIND)
        refs[r["seq"]] = ledger.acquisition_result_fields(r, doc)[0]
    return refs


def _check_j(project, records_after):
    """J とエンバーゴの照合（T-017、T-023、T-027）。追記した後の記録に対して ledger.check_horizon_embargo。

    最初の method-access より後の periods-triggers の J が null か J の最大と等しいこと、採用される periods の
    embargo_days が max(1 件目の embargo_days, J の最大) と等しいこと、採用される periods-triggers
    の J が null でなければ J の最大と等しいこと。
    """
    ledger.check_horizon_embargo(records_after,
                                 lambda r, role: ledger.read_target_json(project, r, role))


def _reader(project, rec, doc):
    """新しい記録はまだファイルに無いので、その中身は doc を返す read_json。"""
    def read(r, role):
        if r["seq"] == rec["seq"]:
            return doc
        return ledger.read_target_json(project, r, role)
    return read


def head_manifest(project, rel):
    """HEAD の版のマニフェストのバイト列（HEAD に無ければ b""）。git は GIT_ の環境変数を固定して動かす。T-073。"""
    env = ledger.fixed_git_env()
    base = ["git", "-C", project]
    if subprocess.run(base + ["cat-file", "-e", "HEAD:" + rel], capture_output=True, env=env).returncode != 0:
        return b""
    r = subprocess.run(base + ["show", "HEAD:" + rel], capture_output=True, env=env)
    if r.returncode != 0:
        raise ledger.LedgerError("HEAD の版の %s を読めない" % rel)
    return r.stdout


def check_new(project, data_after, records_after, rec, doc):
    """手順 3。追記した後の記録に対して、新しい記録の照合をする。"""
    kind = rec["kind"]
    if kind not in WRITTEN_KINDS:
        raise ledger.LedgerError("この仕組みが書く種類ではない: %s" % kind)
    if not isinstance(doc, dict) or doc.get("kind") != kind:
        raise ledger.LedgerError("中身の kind が記録の kind と一致しない")
    read = _reader(project, rec, doc)
    # T-037：順番1・1b の数・中身・位置（method-access より前、gkg-run-start の前に順番1b）
    ledger.check_stats_order(records_after, read)
    if kind == ledger.ORDER2_KIND:
        check_privacy(rec, doc)
        # T-073 差し戻し2回目 2：HEAD のマニフェストから R と decide() の行き先を計算し直して照らす（verify は、記録を
        # 最初に含んだコミットの版で同じ計算をする）。T-078：ledger_head、counting_output の runs・inputs（check_order2_plan
        # の中）、記録の head が今の HEAD であること、コードの版と時機の条件の計算し直し（verify.check_order2_git。照らさな
        # かったことが一つでもあれば書かない）
        ledger.check_ledger_head(data_after, rec, doc)
        ledger.check_order2_plan(records_after, rec, doc, read,
                                 head_manifest(project, ledger.GKG_MANIFESTS["trial"]),
                                 head_manifest(project, ledger.GKG_MANIFESTS["official"]))
        repo = verify.Repo(project)
        head = verify._rgit(repo, "rev-parse", "--verify", "HEAD^{commit}").decode().strip()
        if doc["head"] != head:
            raise ledger.LedgerError("順番2の記録の head %s が、今の HEAD %s と違う。書かない" % (doc["head"][:12], head[:12]))
        notes = verify.check_order2_git(repo, data_after, records_after, rec, doc, head, read)
        if notes:
            raise ledger.LedgerError("順番2の記録の照合で、照らせないものがある（%s）。書かない" % "、".join(notes))
        return
    if kind == ledger.GKG_RESULT_KIND:
        # T-066：中身の形・ledger_head・指す gkg-run-start、マニフェストの先頭と run-complete の行
        ledger.check_gkg_result_doc(records_after, rec, doc, read, data_after)
        manifests = {}
        for mode, rel in ledger.GKG_MANIFESTS.items():
            path = os.path.join(project, rel)
            manifests[mode] = None
            if os.path.isfile(path) and not os.path.islink(path):
                with open(path, "rb") as f:
                    manifests[mode] = f.read()
        ledger.check_gkg_manifests(records_after, read, manifests)
        ledger.check_gkg_results(records_after, read, manifests)
        return
    if kind in (ledger.ORDER1_KIND, ledger.ORDER1B_KIND):
        ledger.check_ledger_head(data_after, rec, doc)
        (ledger.check_order1_doc if kind == ledger.ORDER1_KIND else ledger.check_order1b_doc)(rec, doc)
        return
    if kind in ledger.DRAND_RECORD_KINDS:
        ledger.check_drand_record(data_after, rec, doc, None)
    if kind == ledger.THRESHOLD_ACCESS_KIND:
        want = ledger.first_threshold_block_start(project, records_after)
        if ledger.threshold_access_block_start(doc) != want:
            raise ledger.LedgerError("block_start が periods の 1 件目の閾値の期間の始まりと一致しない")
        ledger.check_candidates_ready(project, records_after, rec["seq"])
        _check_j(project, records_after)
        # T-027 の差し戻し1回目の中1 (ii)：verify periods と同じ deadline_status の照合
        ledger.check_deadline_statuses(records_after,
                                       lambda r, role: ledger.read_target_json(project, r, role))
    elif kind == ledger.ACQ_START_KIND:
        ledger.acquisition_start_fields(doc)
        ledger.check_candidates_order(records_after)
    elif kind == ledger.GKG_RUN_KIND:
        # T-031：中身のキー・run_id・一覧・method-access・試しの日・除外の規則の記録と、順序
        # （method-access より後、official は 1 件だけ、trial は official より前だけ）
        ledger.check_gkg_runs(records_after, read)
    elif kind == ledger.METHOD_ACCESS_KIND:
        ledger.check_method_access_doc(project, records_after, rec, doc)
        ledger.check_method_access_order(records_after)
        ledger.check_acquisition_pairs(records_after, result_refs(project, records_after))
        _check_j(project, records_after)
        # T-031 の差し戻し1回目の軽2：method-access の関門と同じ、仮の採用（periods-triggers の
        # 最後の記録）での deadline_status の照合。関門が止まる状態の記録を書かないため
        ledger.check_deadline_statuses(records_after,
                                       lambda r, role: ledger.read_target_json(project, r, role),
                                       provisional=True)
    else:
        ledger.check_acquisition_pairs(records_after,
                                       result_refs(project, records_after, extra=(rec, doc)))


def write_doc_record(project, kind, doc, data, note, now, ots_cmd, runner=subprocess.run):
    """手順 3〜6。返り値: (記録, 中身のパス, .ots のパス か None)。"""
    ledger.check_sealed_inside(project)    # T-017：入口を飛ばして直接呼んでも、リンクなら止まる
    _sealed, ledger_path = _paths(project)
    content = ledger.canonical_line(doc) + b"\n"
    sha = ledger.sha256_hex(content)
    rel = "sealed/%s-%s.json" % (kind, sha)
    targets = [{"path": rel, "role": kind, "sha256": sha}]
    _records, rec, line = ledger.build_next_record(data, kind, targets, note, now)
    data_after = data + line
    records_after = ledger.verify_chain(data_after)
    check_new(project, data_after, records_after, rec, doc)
    ledger.write_once(os.path.join(project, rel), content)
    after = ledger.append_record(ledger_path, kind, targets, note, now, expected_data=data)
    if after[-1] != rec:
        raise ledger.LedgerError("追記した記録が、照合した記録と一致しない")
    if ots_cmd is None:
        return rec, rel, None
    ots_path, _err, _submitted = stamp.stamp_seq(ledger_path, rec["seq"], ots_cmd, runner=runner)
    return rec, rel, ots_path
