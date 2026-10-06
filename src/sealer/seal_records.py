#!/usr/bin/env python3
"""threshold-access・acquisition-start・acquisition-result・method-access を書く共通の手順。
T-009、T-014。

使うのは seal_access.py、seal_acquisition.py、seal_method.py。中身の形と照合は
docs/verify/periods-seal.md 7章、ledger.py の check_drand_record・acquisition_result_fields・
check_acquisition_pairs と同じ。

手順（この順で行い、途中で失敗したら、それより後のことはしない）
  1. 今の記録の鎖と、すべての seq の .ots を検証する。ots が実行できることを確かめる。
  2. 中身（JSON）を作る。drand を使う種類では、ここで drand の最新の回を取る（1 の後なので、
     回はできるだけ追記の直前のものになる）。ledger_head は 1 で読んだ記録から作る。
  3. 追記する行を作り、「今の記録 + その行」に対して、検証（verify.py）と同じ照合をする。
       - 鎖（kind が許可リストにあること、正規の形、seq、prev_hash）
       - 中身の kind が記録の kind と同じこと
       - threshold-access：ledger_head、drand、block_start（periods の 1 件目の閾値の期間の始まり）、
         その前に candidates の記録があり、候補の順序の照合に通ること（T-014）
       - acquisition-start：ledger_head、drand、step = 3、fetch（取得のコードのパスと sha256）、
         その前に candidates の記録があること（T-014。check_candidates_order）
       - method-access：ledger_head、drand、step = 4、区画（periods の 1 件目の method の区画）、
         その前に candidates と acquisition-result の記録があること（T-014）
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


WRITTEN_KINDS = (ledger.THRESHOLD_ACCESS_KIND, ledger.ACQ_START_KIND, ledger.ACQ_RESULT_KIND,
                 ledger.METHOD_ACCESS_KIND)


def _paths(project):
    sealed = os.path.join(project, "sealed")
    return sealed, os.path.join(sealed, "ledger.jsonl")


def load_checked(project, ots_cmd, runner=subprocess.run):
    """手順 1。(記録のバイト列, 記録の一覧) を返す。"""
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


def check_new(project, data_after, records_after, rec, doc):
    """手順 3。追記した後の記録に対して、新しい記録の照合をする。"""
    kind = rec["kind"]
    if kind not in WRITTEN_KINDS:
        raise ledger.LedgerError("この仕組みが書く種類ではない: %s" % kind)
    if not isinstance(doc, dict) or doc.get("kind") != kind:
        raise ledger.LedgerError("中身の kind が記録の kind と一致しない")
    if kind in ledger.DRAND_RECORD_KINDS:
        ledger.check_drand_record(data_after, rec, doc, None)
    if kind == ledger.THRESHOLD_ACCESS_KIND:
        want = ledger.first_threshold_block_start(project, records_after)
        if ledger.threshold_access_block_start(doc) != want:
            raise ledger.LedgerError("block_start が periods の 1 件目の閾値の期間の始まりと一致しない")
        ledger.check_candidates_ready(project, records_after, rec["seq"])
    elif kind == ledger.ACQ_START_KIND:
        ledger.acquisition_start_fields(doc)
        ledger.check_candidates_order(records_after)
    elif kind == ledger.METHOD_ACCESS_KIND:
        ledger.check_method_access_doc(project, records_after, rec, doc)
        ledger.check_method_access_order(records_after)
        ledger.check_acquisition_pairs(records_after, result_refs(project, records_after))
    else:
        ledger.check_acquisition_pairs(records_after,
                                       result_refs(project, records_after, extra=(rec, doc)))


def write_doc_record(project, kind, doc, data, note, now, ots_cmd, runner=subprocess.run):
    """手順 3〜6。返り値: (記録, 中身のパス, .ots のパス か None)。"""
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
