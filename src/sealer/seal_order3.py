#!/usr/bin/env python3
"""順番3（数え方とのつながり。docs/stats/counting.md 4章 (3)、docs/stats/seal-order1.md 101・172〜185行、
docs/stats/tags-naive.md 368行）の試みを、1回ごとに ledger に記録し、関門を通ったときだけ順番3の記録を書く入口
（kind: stats-order3-attempt と stats-order3）。T-090。手順は docs/verify/periods-seal.md 17章。

使い方（プロジェクトのルートで。ots の通信を使うので .venv の python で実行する。root はこのファイルの場所から決まり、
引数では変えられない。seal_order2.py と同じ）
    PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -B src/sealer/seal_order3.py \\
        --bundle-out <プロジェクトと Git の外の、まだ無いファイルのパス>
    PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -B src/sealer/seal_order3.py --commit-written

「試み」は、この入口を一回動かすことを指す（seal-order1.md 185行）。関門の結果を画面に出す前に、試みの記録を ledger に
追記してコミットする。記録を書かずに関門の結果だけを確かめる使い方（乾式の実行など）は作らない。

1回の実行は、次の順で進む。0〜1 で止まったときは、何も書かない（試みは始まっていない）。
  0. 記録の鎖とすべての .ots を検証する（seal_records.load_checked）。作業ツリーがきれいで、HEAD が決まる。
  1. 書く前の確かめ（どれも関門の結果に依らない）：
     - 参照する順番1b の記録（この記録より前の stats-order1b の seq の最大。counting.md 4章 (3) の 1）に対する順番3の
       記録が、まだ無い（一つの順番1b に1件だけ）。
     - 統計係の文書 ledger.ORDER3_READING_DOC（その数え方で K を何と読むか。tags-naive.md 1章 (2)・368行）が、HEAD に
       コミットしてあり、作業ツリーと同じで、空でない。
  2. 参照を読む（verify.read_refs_now：for-each-ref の全行、worktree の HEAD、graft・浅い clone）。
  3. git bundle create --all を --bundle-out に作り、list-heads が読んだ refs と worktree の HEAD と合うかを見る
     （seal-order1.md 177・178行。ledger.bundle_heads_match）。合わなければ、時機の条件（F と ok）を計算せず、関門も
     流さずに halt（cause "bundle"）の試みを記録する（timing_check は null。list-heads は bundle_heads に入れる）。
     合ったときだけ、読んだ参照から時機の条件を順番3の時点で確かめ直す（verify.timing_from_refs。順番2と同じ計算。
     counting.md 4章 (3) の 3）。順番1b の記録が無ければ、F を数えず ok は false。T-091 でこの順にした。
  4. 封印した版の counting.py（参照する順番1b の記録が sha256 で縛る版）を git の履歴から探す（verify.find_order2_code。
     作業ツリーの版は使わない）。無ければ、関門を流さずに halt（cause "code"）の試みを記録する。
  5. 見つかった版の order3_gate() を、その counting.py だけを置いた空のフォルダで、-I・-B の Python で流す
     （verify.run_order3_gate）。入力は記録だけから決まる（ledger.order3_gate_inputs：順番1b の seq、順番2の記録、
     3 の timing_check、前の試みの gate を attempt_from_record にしたもの）。返った record を gate に入れる。
     order3_gate() が ValueError で入力を受け付けなかったときは、halt（cause "input"）の試みを記録する（T-091）。
  6. HEAD と作業ツリーがはじめと同じことを確かめ直し、試みの記録を書き（書く前の照合：seal_records.check_new）、.ots を
     作り、パスを指定してコミットする（seal_order2.commit_record と同じ固定のしかた）。
  7. gate が通った（may_seal が true）ときだけ、続けて順番3の記録（stats-order3）を書いて、.ots を作り、コミットする。
  8. 結果は、コミットのあとで画面に出す。書いたあとで止まったときは Order3Written で知らせ、「書いていない」とは
     表示しない。

ネットワークは ots の stamp だけ。drand は使わない。日の集計は開かない（順番3はデータを使わない）。
"""

import argparse
import datetime
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import ledger  # noqa: E402
import seal_order2  # noqa: E402
import seal_records  # noqa: E402
import stamp  # noqa: E402
import verify  # noqa: E402

ATTEMPT_MESSAGE = "順番3の試みの記録（stats-order3-attempt。src/sealer/seal_order3.py が書いてコミットした）"
ORDER3_MESSAGE = "順番3の記録（stats-order3。src/sealer/seal_order3.py が書いてコミットした）"
MESSAGES = {ledger.ORDER3_ATTEMPT_KIND: ATTEMPT_MESSAGE, ledger.ORDER3_KIND: ORDER3_MESSAGE}

BUNDLE_HALT_REASON = ("bundle の list-heads が、読んだ refs・worktree の HEAD と合わない（参照を読んでから bundle を作るまでに"
                      "参照が変わった）。時機の条件（F と ok）を計算せず、関門の結果を出さずに止まる（seal-order1.md 177・178行）")


class Order3Written(ledger.LedgerError):
    """記録（試み、または試みと順番3の記録）は書いたが、そのあとの段で止まった。「何も書いていない」とは表示しない。"""


def current_ref(records):
    """これから書く試みが参照する順番1b の記録（今の記録の stats-order1b の seq の最大。無ければ None）。"""
    return ledger.order2_ref_1b(records, len(records) + 1)


def check_not_sealed(root, records, ref):
    """ref（順番1b の記録）に対する順番3の記録が、まだ無いこと。あれば LedgerError（試みを書かない）。"""
    if ref is None:
        return
    for r in records:
        if r["kind"] == ledger.ORDER3_KIND \
                and ledger.read_target_json(root, r, ledger.ORDER3_KIND)["ref_1b"]["seq"] == ref["seq"]:
            raise ledger.LedgerError("順番1b（seq %d）に対する順番3の記録は、もう seq %d にある（一つの順番1b に1件だけ）。"
                                     "試みを書かない" % (ref["seq"], r["seq"]))


def reading_doc_sha(repo, root):
    """ledger.ORDER3_READING_DOC が HEAD にコミットしてあり、作業ツリーのファイル（リンクでない普通のファイル）が HEAD の版と
    同じで、空でないこと。返り値: HEAD の版のバイト列の sha256。満たさなければ LedgerError。"""
    rel = ledger.ORDER3_READING_DOC
    if not verify._git_ok(repo, "cat-file", "-e", "HEAD:" + rel):
        raise ledger.LedgerError("%s（その数え方で K を何と読むか。統計係の文書）が HEAD に無い。順番3の記録に縛る文書が"
                                 "無いので、試みを書かない" % rel)
    body = verify._rgit(repo, "show", "HEAD:" + rel)
    path = os.path.join(root, rel)
    if os.path.islink(path) or not os.path.isfile(path):
        raise ledger.LedgerError("%s が普通のファイルでない。試みを書かない" % rel)
    with open(path, "rb") as f:
        if f.read() != body:
            raise ledger.LedgerError("%s の作業ツリーのファイルが HEAD の版と違う。試みを書かない" % rel)
    if not body.strip():
        raise ledger.LedgerError("%s が空。試みを書かない" % rel)
    return ledger.sha256_hex(body)


def timing_without_1b(snap):
    """順番1b の記録が無いときの timing_check と timing_guards（F を数えず、ok は false。counting.md 4章 (3) の 1・249行）。
    参照の一覧・worktree の HEAD・HEAD・計算の前の確かめは、verify.read_refs_now で読んだもの（snap）をそのまま記録する。"""
    tc = {"ok": False, "ref_1b_seq": None, "head": snap["head"], "f_set": [], "refs": snap["refs"],
          "worktree_heads": snap["worktree_heads"], "reason": "順番1b の記録が無い"}
    ledger.check_order3_timing_shape(tc, "時機の条件の確かめ")
    return tc, {"graft_file": snap["graft"], "shallow": snap["shallow"]}


def build_attempt(root, data, records, bundle_out):
    """手順 1〜6 の書く前まで。返り値: 書く試みの中身。
    T-091：seal-order1.md 177行の順に、参照を読む → bundle を作って list-heads と照らす → 合ったときだけ、読んだ参照から F と
    ok を計算する。合わなければ F と ok は計算せず、halt（bundle）の試みにする（timing_check は null、list-heads は
    bundle_heads に入れる）。"""
    repo = verify.Repo(root)
    head = seal_order2.clean_head(repo)
    seq = len(records) + 1
    ref = current_ref(records)
    check_not_sealed(root, records, ref)                                    # 1. 書く前の確かめ
    reading_doc_sha(repo, root)
    snap = verify.read_refs_now(repo, label="順番3")                        # 2. 参照を読む
    if snap["head"] != head:
        raise ledger.LedgerError("確かめているあいだに HEAD が変わった。書かない")
    bundle, heads = seal_order2.create_bundle(repo, root, bundle_out)      # 3. bundle を作り、list-heads と照らす
    matched = ledger.bundle_heads_match(snap["refs"], snap["worktree_heads"], heads)
    tc = None
    guards = {"graft_file": snap["graft"], "shallow": snap["shallow"]}
    if matched:                                                             # 合ったときだけ時機の条件（確かめ直し）
        if ref is not None:
            tc, guards = verify.timing_from_refs(repo, records, ref, snap)
        else:
            tc, guards = timing_without_1b(snap)
    d1b = None if ref is None else ledger.read_target_json(root, ref, ledger.ORDER1B_KIND)
    code_sha = None if d1b is None else {f["path"]: f["sha256"] for f in d1b["files"]}.get(ledger.COUNTING_SCRIPT)
    commit, code = (None, None) if d1b is None else verify.find_order2_code(repo, head, d1b)   # 4. 封印した版
    gate, halt = None, None
    if not matched:
        halt = {"cause": "bundle", "reason": BUNDLE_HALT_REASON}
    elif commit is None:
        halt = {"cause": "code", "reason": "順番1b の記録が無く、封印した版の counting.py が決まらない" if ref is None else
                "順番1b の記録（seq %d）が縛る %s（sha256 %s）の版が、git の履歴に無い" % (ref["seq"], ledger.COUNTING_SCRIPT,
                                                                              code_sha)}
    else:                                                                   # 5. 封印した版の order3_gate()
        inputs = ledger.order3_gate_inputs(records, seq, tc, lambda r, role: ledger.read_target_json(root, r, role))
        with tempfile.TemporaryDirectory() as tmp:
            try:
                gate = verify.run_order3_gate(code, code_sha, inputs, tmp, "順番3の関門")
            except verify.Order3InputRejected as e:
                # T-091（T-090 の監査 軽-2）：関門のコードを一回動かしたので、入力を受け付けなかったことも試みとして記録する
                halt = {"cause": "input", "reason": verify.order3_input_halt_reason(str(e))}
            except verify.Unchecked as e:
                raise ledger.LedgerError("順番3の関門を流せない（%s）。書かない" % e) from None
    doc = {
        "kind": ledger.ORDER3_ATTEMPT_KIND,
        "ledger_head": ledger.expected_ledger_head(data, seq),
        "head": head,
        "ref_1b": ledger.record_ref(ref),
        "refs_read": {"head": snap["head"], "refs": snap["refs"], "worktree_heads": snap["worktree_heads"]},
        "bundle_heads": heads,
        "timing_check": tc,
        "timing_guards": guards,
        "bundle": bundle,
        "code": {"path": ledger.COUNTING_SCRIPT, "sha256": code_sha, "found": commit is not None, "commit": commit},
        "gate": gate,
        "halt": halt,
        "python": sys.version.split()[0],
    }
    if seal_order2.clean_head(repo) != head:                                # 6. 書く直前の確かめ直し
        raise ledger.LedgerError("確かめているあいだに HEAD が変わった。書かない")
    return doc


def build_order3(root, data, records, att_rec, att_doc):
    """通った試み（att_rec・att_doc。直前に書いてコミットしたもの）のあとに書く順番3の記録の中身。"""
    repo = verify.Repo(root)
    head = seal_order2.clean_head(repo)
    by = {r["seq"]: r for r in records}
    ref = by[att_doc["ref_1b"]["seq"]]
    c = ledger.read_target_json(root, ref, ledger.ORDER1B_KIND)["counting"]
    return {
        "kind": ledger.ORDER3_KIND,
        "ledger_head": ledger.expected_ledger_head(data, len(records) + 1),
        "head": head,
        "attempt": ledger.record_ref(att_rec),
        "ref_1b": att_doc["ref_1b"],
        "ref_order1": ledger.record_ref(ledger.first_order1(records)),
        "ref_order2": ledger.record_ref(by[att_doc["gate"]["chosen_order2_seq"]]),
        "counting": {"official_candidate": c["official_candidate"], "official_status": c["official_status"]},
        "reading": {"path": ledger.ORDER3_READING_DOC, "sha256": reading_doc_sha(repo, root)},
    }


def _write(root, kind, doc, data, records, note, now, ots_cmd, runner):
    """記録を1件書き、.ots を作り、コミットする（seal_order2.seal と同じ扱い）。追記の前で止まれば LedgerError（その記録は
    書いていない）。追記のあとで止まれば Order3Written。返り値: (記録, 中身のパス, .ots のパスか None, コミット)。"""
    repo = verify.Repo(root)
    try:
        rec, rel, ots_path = seal_records.write_doc_record(root, kind, doc, data, note, now, ots_cmd, runner=runner)
    except ledger.LedgerError as e:
        after = ledger.verify_chain(ledger.read_ledger(os.path.join(root, "sealed", "ledger.jsonl")))
        if len(after) <= len(records):
            raise
        last = after[-1]
        try:
            c = seal_order2.commit_record(repo, root, last, None, MESSAGES[kind])
        except ledger.LedgerError as e2:
            raise Order3Written("記録 seq %d（%s）と中身を作業ツリーに書いたが、.ots を作れず（%s）、コミットもしていない（%s）。"
                                "消さずに、原因を直してから seal_order3.py --commit-written でコミットし、stamp.py stamp --seq %d"
                                " で .ots を作る" % (last["seq"], kind, e, e2, last["seq"])) from None
        raise Order3Written("記録 seq %d（%s）と中身を書いてコミット %s に入れたが、.ots を作れなかった（%s）。stamp.py stamp "
                            "--seq %d で .ots を作ってコミットする" % (last["seq"], kind, c[:12], e, last["seq"])) from None
    try:
        commit = seal_order2.commit_record(repo, root, rec, ots_path, MESSAGES[kind])
    except ledger.LedgerError as e:
        raise Order3Written("記録 seq %d（%s）・中身・.ots を作業ツリーに書いたが、コミットしていない（%s）。消さずに、原因を"
                            "直してから seal_order3.py --commit-written でコミットする（手順書17章）" % (rec["seq"], kind, e)) from None
    return rec, rel, ots_path, commit


def seal(bundle_out, now, ots_cmd, runner=subprocess.run):
    """順番3の試みを1件追記してコミットし、関門を通ったときだけ、続けて順番3の記録を1件追記してコミットする。
    返り値: {"attempt": (記録, 中身のパス, .ots, 中身, コミット), "order3": 同じ形か None}。"""
    root = ledger.check_sealed_inside(ledger.PROJECT_ROOT)
    data, records = seal_records.load_checked(root, ots_cmd, runner=runner)
    doc = build_attempt(root, data, records, bundle_out)
    n = sum(1 for r in records if r["kind"] == ledger.ORDER3_ATTEMPT_KIND) + 1
    g, h = doc["gate"], doc["halt"]
    res = ("halt %s" % h["cause"]) if g is None else ("may_seal %s" % ("true" if g["may_seal"] else "false"))
    note = ("統計係の順番3の試み（docs/stats/counting.md 4章 (3)、docs/stats/seal-order1.md 172〜185行）。stats-order3-attempt の"
            " %d 件目。%s。参照する順番1b は %s。採用の区切りには使わない。"
            % (n, res, "無し" if doc["ref_1b"] is None else "seq %d" % doc["ref_1b"]["seq"]))
    rec, rel, ots_path, commit = _write(root, ledger.ORDER3_ATTEMPT_KIND, doc, data, records, note, now, ots_cmd, runner)
    out = {"attempt": (rec, rel, ots_path, doc, commit), "order3": None}
    if g is None or not g["may_seal"]:
        return out
    try:
        data, records = seal_records.load_checked(root, ots_cmd, runner=runner)
        odoc = build_order3(root, data, records, rec, doc)
        note3 = ("統計係の順番3（数え方とのつながり。docs/stats/tags-naive.md 368行）。試み seq %d、順番1b seq %d、順番2 seq %d。"
                 "採用の区切りには使わない。" % (rec["seq"], odoc["ref_1b"]["seq"], odoc["ref_order2"]["seq"]))
        o = _write(root, ledger.ORDER3_KIND, odoc, data, records, note3, now, ots_cmd, runner)
    except Order3Written:
        raise
    except ledger.LedgerError as e:
        raise Order3Written("順番3の試みの記録 seq %d（関門を通った）は書いてコミット %s に入れたが、順番3の記録は書いていない（%s）。"
                            "原因を直してから、もう一度この入口を流す（新しい試みとして記録される）"
                            % (rec["seq"], commit[:12], e)) from None
    out["order3"] = (o[0], o[1], o[2], odoc, o[3])
    return out


def main(argv=None):
    p = argparse.ArgumentParser(allow_abbrev=False, description=__doc__.splitlines()[0])
    p.add_argument("--bundle-out", help="git bundle を書くパス（プロジェクトと Git の外。まだ無いもの）")
    p.add_argument("--ots", default=stamp.DEFAULT_OTS)
    p.add_argument("--commit-written", action="store_true",
                   help="書いたがコミットしていない最後の stats-order3-attempt・stats-order3 の記録を、入口と同じ固定のしかたで"
                        "コミットする")
    a = p.parse_args(argv)
    if a.commit_written:
        try:
            c = seal_order2.commit_written(ledger.check_sealed_inside(ledger.PROJECT_ROOT), ledger.ORDER3_KINDS, MESSAGES)
        except ledger.LedgerError as e:
            print("失敗（コミットしていない）: %s" % e, file=sys.stderr)
            return 1
        print("コミット: %s" % c)
        return 0
    if not a.bundle_out:
        p.error("--bundle-out が要る")
    now = datetime.datetime.now(datetime.timezone.utc)
    try:
        out = seal(a.bundle_out, now, a.ots)
    except Order3Written as e:
        print("止まった（順番3の試みの記録は書いた）: %s" % e, file=sys.stderr)
        return 1
    except ledger.LedgerError as e:
        print("失敗（順番3の試みの記録は書いていない）: %s" % e, file=sys.stderr)
        return 1
    rec, rel, ots_path, doc, commit = out["attempt"]
    print(ledger.canonical_line(rec).decode("utf-8"))
    print("中身: %s" % rel)
    g, h = doc["gate"], doc["halt"]
    if g is None:
        print("順番3の試み：関門の結果を出さずに止まった（%s：%s）" % (h["cause"], h["reason"]))
    elif g["may_seal"]:
        print("順番3の試み：通った。参照する順番1b は seq %d、順番2の記録は seq %d" % (g["ref_1b_seq"], g["chosen_order2_seq"]))
    else:
        print("順番3の試み：止まった（%s）" % g["reason"])
    print("bundle: sha256 %s（公開していない）" % doc["bundle"]["sha256"])
    print("コミット: %s（試みの記録・中身・.ots。結果は、このコミットのあとで表示している）" % commit)
    if ots_path is not None:
        print("時刻証明: %s" % os.path.relpath(ots_path, ledger.PROJECT_ROOT))
    if out["order3"] is not None:
        rec3, rel3, ots3, _d3, c3 = out["order3"]
        print(ledger.canonical_line(rec3).decode("utf-8"))
        print("順番3の記録: %s、コミット %s" % (rel3, c3))
        if ots3 is not None:
            print("時刻証明: %s" % os.path.relpath(ots3, ledger.PROJECT_ROOT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
