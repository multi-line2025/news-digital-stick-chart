#!/usr/bin/env python3
"""順番4（手法を作る期間の区画の、欠けた日の一覧。docs/stats/missing-days-method.md）を、1回だけ ledger に記録する入口
（kind: stats-order4）。T-095。手順は docs/verify/periods-seal.md 18章。

使い方（プロジェクトのルートで。ots の通信を使うので .venv の python で実行する。root はこのファイルの場所から決まり、
引数では変えられない。seal_order2.py・seal_order3.py と同じ）
    PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -B src/sealer/seal_order4.py --store <正式な run の日の集計の置き場所>
    PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -B src/sealer/seal_order4.py --commit-written
    PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -B src/sealer/seal_order4.py --write-content --store <置き場所>
      （追記のあとで中身を書けなかったときだけ。T-100）

一覧のコード（統計係の src/stats/missing_days.py）は、作業ツリーのものを使わない。HEAD の版のファイル（src/・sealed/・
data/manifest/ の下のすべて。ledger.ORDER4_TREE_PREFIXES）を git から空のフォルダに取り出し、その中の missing_days.py を
-I・-B の Python で流す（verify.run_order4）。出力（JSON）は、そのまま記録の list に入れる。統計係が別に流した JSON は入力に
しない（理由は18章）。

1回の実行は、次の順で進む。0〜3 で止まったときは、何も書かない。
  0. 記録の鎖とすべての .ots を検証する（seal_records.load_checked）。作業ツリーがきれいで、HEAD が決まる。
  1. 書く前の確かめ（どれも一覧の値に依らない）：
     - 位置（ledger.check_order4_position）：順番4の記録がまだ無い（1件だけ）、順番3（stats-order3）の記録がある、
       threshold-access（と、これから作る順番5・モデルの kind）の記録が無い。
     - 参照する記録（ledger.order4_refs）が決まる：正式な run の gkg-run-result がちょうど1件、順番3の記録、それが参照する
       順番1b、periods・candidates の1件目。
     - HEAD の版のファイルから記録の code を作り（verify.order4_tree・order4_code）、一覧のコードが照らす3つのファイルの
       sha256 が封印の記録の値と同じ（ledger.check_order4_imports）。文書とテスト（ledger.ORDER4_DOC_FILES）が HEAD にある。
     - 置き場所がフォルダである（中のファイルは開かない）。
  2. 固定した版の一覧のコードを流す（60〜100分。verify.run_order4）。0 以外で終われば止まる（何も書かない）。
  3. 出力が決まった形の JSON であること（verify.parse_order4_output）。HEAD と作業ツリーがはじめと同じこと。
  4. 記録を書き（書く前の照合：seal_records.check_new。ledger.check_order4_records・verify.check_order4_git・
     verify.check_order4_rules（72本の条件を、封印済みの candidates.py とマニフェストで照らす）・verify.recount_order4（C7 の
     分母を、--store の日の集計で封印済みの counting.py で数え直す。T-100）・privacy_scan と同じ検査）。
     中身のファイルは、記録に追記したあとで書く（追記の前で止まっても、一覧の入ったファイルを作業ツリーに残さない）。
     .ots を作り、記録・中身・.ots だけをパス指定で index に入れてコミットする（seal_order2.commit_record と同じ
     固定のしかた。本文は ORDER4_MESSAGE）。
  5. 結果は、コミットのあとで画面に出す。書いたあとで止まったときは Order4Written で知らせ、「書いていない」とは表示しない。

ネットワークは ots の stamp だけ。drand は使わない。日の集計を開くのは、2 で流す一覧のコードだけ。
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

ORDER4_MESSAGE = "順番4の記録（stats-order4。src/sealer/seal_order4.py が書いてコミットした）"
MESSAGES = {ledger.ORDER4_KIND: ORDER4_MESSAGE}


class Order4Written(ledger.LedgerError):
    """記録は書いた（鎖に追記した）が、そのあとの段（.ots・コミット・コミットの確かめ）で止まった。「何も書いていない」とは
    表示しない。"""


def check_store(store):
    """置き場所の引数：あるフォルダで、その実体の絶対パスを返す（記録には入れない）。中のファイルは開かない。"""
    if not store or not os.path.isdir(store):
        raise ledger.LedgerError("日の集計の置き場所 %s がフォルダでない。書かない" % store)
    return os.path.realpath(store)


def _head(repo, clean):
    """clean が真なら、作業ツリーがきれいで HEAD の40桁（seal_order2.clean_head）。偽なら HEAD の40桁だけ（--write-content。
    作業ツリーの変更は呼ぶ側が確かめる）。"""
    if clean:
        return seal_order2.clean_head(repo)
    return verify._rgit(repo, "rev-parse", "--verify", "HEAD^{commit}").decode().strip()


def prepare(root, records, clean=True):
    """手順 1。返り値: (HEAD, 参照する記録, HEAD の版のファイル, 記録の code)。"""
    repo = verify.Repo(root)
    head = _head(repo, clean)
    seq = len(records) + 1
    ledger.check_order4_position(records, seq)
    read = lambda r, role: ledger.read_target_json(root, r, role)  # noqa: E731
    refs = ledger.order4_refs(records, seq, read)
    missing = [k for k in ledger.ORDER4_REF_KEYS if refs[k] is None]
    if missing:
        raise ledger.LedgerError("参照する記録（%s）が決まらない（正式な run の gkg-run-result がちょうど1件、順番3の記録と、"
                                 "それが参照する順番1b、periods・candidates の記録が要る）。書かない" % "・".join(missing))
    tree = verify.order4_tree(repo, head)
    code = verify.order4_code(repo, head, tree)
    ledger.check_order4_imports(refs, read, {x["path"]: x["sha256"] for x in code["imports"]},
                                "HEAD %s の版" % head[:12])
    return head, refs, tree, code


def build_doc(root, data, records, store, tmp, clean=True):
    """手順 1〜3。返り値: 書く中身。data・records は、この記録を足す前の記録。clean が偽なのは --write-content だけ。"""
    repo = verify.Repo(root)
    head, refs, tree, code = prepare(root, records, clean)                   # 1. 書く前の確かめ
    store = check_store(store)
    what = "順番4の一覧（HEAD %s の版の %s）" % (head[:12], ledger.ORDER4_SCRIPT)
    try:
        raw = verify.run_order4(tree, store, tmp, what)                       # 2. 固定した版を流す
    except verify.Unchecked as e:
        raise ledger.LedgerError("一覧のコードを流せない（%s）。書かない" % e) from None
    lst, sha = verify.parse_order4_output(raw, what)                          # 3. 出力の形
    if _head(repo, clean) != head:
        raise ledger.LedgerError("流しているあいだに HEAD が変わった。書かない")
    return {
        "kind": ledger.ORDER4_KIND,
        "ledger_head": ledger.expected_ledger_head(data, len(records) + 1),
        "head": head,
        "list": lst,
        "list_sha256": sha,
        "refs": {k: ledger.record_ref(refs[k]) for k in ledger.ORDER4_REF_KEYS},
        "code": code,
        "python": sys.version.split()[0],
    }


def seal(store, now, ots_cmd, runner=subprocess.run):
    """順番4の記録を1件追記し、続けてコミットする。返り値: (記録, 中身のパス, .ots のパスか None, 中身, コミット)。
    .ots を作れなかったとき（記録は鎖に残る）も、記録と中身をコミットしてから止まる。"""
    root = ledger.check_sealed_inside(ledger.PROJECT_ROOT)
    repo = verify.Repo(root)
    data, records = seal_records.load_checked(root, ots_cmd, runner=runner)
    store = check_store(store)
    with tempfile.TemporaryDirectory() as tmp:
        doc = build_doc(root, data, records, store, tmp)
    lst = doc["list"]
    note = ("統計係の順番4（手法を作る期間の区画の、欠けた日の一覧。docs/stats/missing-days-method.md、label %s）。一覧の sha256 %s。"
            "gkg-run-result seq %d、順番3 seq %d。採用の区切りには使わない。"
            % (lst["label"], doc["list_sha256"], doc["refs"]["gkg_run_result"]["seq"], doc["refs"]["order3"]["seq"]))
    try:
        rec, rel, ots_path = seal_records.write_doc_record(root, ledger.ORDER4_KIND, doc, data, note, now, ots_cmd,
                                                           runner=runner, content_after_append=True, order4_store=store)
    except ledger.LedgerError as e:
        after = ledger.verify_chain(ledger.read_ledger(os.path.join(root, "sealed", "ledger.jsonl")))
        if len(after) <= len(records):
            raise                              # 追記の前で止まった：何も書いていない
        last = after[-1]
        if not os.path.isfile(os.path.join(root, last["targets"][0]["path"])):
            raise Order4Written("記録 seq %d を追記したが、中身を書けなかった（%s）。コミットしていない。消さずに、原因を直して"
                                "から seal_order4.py --write-content --store <置き場所> で中身を書いてコミットする（同じ HEAD で流し直し、"
                                "記録の targets の sha256 と同じバイト列のときだけ書く。手順書18章）" % (last["seq"], e)) from None
        try:
            c = seal_order2.commit_record(repo, root, last, None, ORDER4_MESSAGE)
        except ledger.LedgerError as e2:
            raise Order4Written("記録 seq %d と中身を作業ツリーに書いたが、.ots を作れず（%s）、コミットもしていない（%s）。"
                                "消さずに、原因を直してから seal_order4.py --commit-written でコミットし、stamp.py stamp --seq %d"
                                " で .ots を作る" % (last["seq"], e, e2, last["seq"])) from None
        raise Order4Written("記録 seq %d と中身を書いてコミット %s に入れたが、.ots を作れなかった（%s）。stamp.py stamp --seq %d で"
                            ".ots を作ってコミットする" % (last["seq"], c[:12], e, last["seq"])) from None
    try:
        commit = seal_order2.commit_record(repo, root, rec, ots_path, ORDER4_MESSAGE)
    except ledger.LedgerError as e:
        raise Order4Written("記録 seq %d・中身・.ots を作業ツリーに書いたが、コミットしていない（%s）。消さずに、原因を直してから "
                            "seal_order4.py --commit-written でコミットする（手順書18章）" % (rec["seq"], e)) from None
    return rec, rel, ots_path, doc, commit


def write_content(store):
    """追記のあとで中身のファイルを書けなかった記録（T-100。T-095 の監査 P2）の中身を、同じ HEAD で build_doc を流し直して
    作り、記録の targets の sha256 と同じバイト列のときだけ書いて、入口と同じ固定のしかたでコミットする（--write-content）。
    条件（どれかに当たれば何も書かない）：
      - 最後の記録が stats-order4 で、その中身のファイルが無い（リンクも無い）。
      - HEAD の版の sealed/ledger.jsonl が、今の記録から最後の1行を除いたものと同じ（その記録はまだコミットしていない）。
      - 作業ツリーの変更が、sealed/ledger.jsonl と、その seq の .ots だけ。
      - 最後の1行を除いた記録と、すべての .ots の照合（その seq の .ots があれば、それも）に通る。
    中身は決まった値だけから作られる（HEAD・記録・置き場所の日の集計・Python の版）。どれかが書いた時と違えば、バイト列が
    sha256 と合わずに止まる。中身の照合（check_new）は、同じバイト列なので、書いた時に通ったものと同じである。
    返り値: コミットの40桁。"""
    root = ledger.check_sealed_inside(ledger.PROJECT_ROOT)
    repo = verify.Repo(root)
    data = ledger.read_ledger(os.path.join(root, "sealed", "ledger.jsonl"))
    records = ledger.verify_chain(data)
    last = records[-1]
    if last["kind"] != ledger.ORDER4_KIND:
        raise ledger.LedgerError("最後の記録が %s でない。書かない" % ledger.ORDER4_KIND)
    ledger.check_single_target(last, "最後の記録")
    t = last["targets"][0]
    if os.path.lexists(os.path.join(root, t["path"])):
        raise ledger.LedgerError("%s は既にある。--write-content は、中身を書けなかったときだけ使う" % t["path"])
    prefix = ledger.prefix_bytes(data, last["seq"] - 1)
    r = subprocess.run(["git", "-C", root, "cat-file", "blob", "HEAD:sealed/ledger.jsonl"], capture_output=True,
                       env=ledger.fixed_git_env())
    if r.returncode != 0 or r.stdout != prefix:
        raise ledger.LedgerError("HEAD の版の sealed/ledger.jsonl が、今の記録から最後の seq %d を除いたものと同じでない。書かない"
                                 % last["seq"])
    ots = os.path.join(root, "sealed", ledger.ots_name(last["seq"]))
    allowed = {"sealed/ledger.jsonl", "sealed/" + ledger.ots_name(last["seq"])}
    changed = {line[3:] for line in verify._rgit(repo, "status", "--porcelain", "--untracked-files=all")
               .decode("utf-8").splitlines()}
    if not changed or not changed <= allowed:
        raise ledger.LedgerError("作業ツリーの変更（%s）が、記録 seq %d の行と .ots だけでない。書かない"
                                 % ("、".join(sorted(changed)), last["seq"]))
    ledger.check_anchors(data if os.path.isfile(ots) else prefix, os.path.join(root, "sealed"))
    before = ledger.verify_chain(prefix)
    store = check_store(store)
    with tempfile.TemporaryDirectory() as tmp:
        doc = build_doc(root, prefix, before, store, tmp, clean=False)
    content = ledger.canonical_line(doc) + b"\n"
    if ledger.sha256_hex(content) != t["sha256"]:
        raise ledger.LedgerError("流し直した中身の sha256 %s が、記録 seq %d の targets の sha256 %s と違う（HEAD・置き場所・"
                                 "Python の版のどれかが、書いた時と違う）。書かない。リードに報告する"
                                 % (ledger.sha256_hex(content), last["seq"], t["sha256"]))
    ledger.write_once(os.path.join(root, t["path"]), content)
    return seal_order2.commit_record(repo, root, last, ots if os.path.isfile(ots) else None, ORDER4_MESSAGE)


def main(argv=None):
    p = argparse.ArgumentParser(allow_abbrev=False, description=__doc__.splitlines()[0])
    p.add_argument("--store", help="正式な run の日の集計の置き場所（フォルダ。記録には入れない）")
    p.add_argument("--ots", default=stamp.DEFAULT_OTS)
    p.add_argument("--commit-written", action="store_true",
                   help="書いたがコミットしていない最後の stats-order4 の記録を、入口と同じ固定のしかたでコミットする")
    p.add_argument("--write-content", action="store_true",
                   help="記録に追記したあとで中身を書けなかった最後の stats-order4 の中身を、同じ HEAD で流し直して書き、"
                        "コミットする（--store が要る）")
    a = p.parse_args(argv)
    if a.write_content:
        if not a.store:
            p.error("--write-content には --store が要る")
        try:
            c = write_content(a.store)
        except ledger.LedgerError as e:
            print("失敗（中身は書いていない）: %s" % e, file=sys.stderr)
            return 1
        print("コミット: %s（中身を書いた。.ots が無ければ stamp.py stamp --seq N で作る）" % c)
        return 0
    if a.commit_written:
        try:
            c = seal_order2.commit_written(ledger.check_sealed_inside(ledger.PROJECT_ROOT), (ledger.ORDER4_KIND,), MESSAGES)
        except ledger.LedgerError as e:
            print("失敗（コミットしていない）: %s" % e, file=sys.stderr)
            return 1
        print("コミット: %s" % c)
        return 0
    if not a.store:
        p.error("--store が要る")
    now = datetime.datetime.now(datetime.timezone.utc)
    try:
        rec, rel, ots_path, doc, commit = seal(a.store, now, a.ots)
    except Order4Written as e:
        print("止まった（順番4の記録は書いた）: %s" % e, file=sys.stderr)
        return 1
    except ledger.LedgerError as e:
        print("失敗（順番4の記録は書いていない）: %s" % e, file=sys.stderr)
        return 1
    print(ledger.canonical_line(rec).decode("utf-8"))
    print("中身: %s" % rel)
    print("順番4：一覧の sha256 %s（%s、欠けた日 %d 日）、%s の sha256 %s、head %s"
          % (doc["list_sha256"], doc["list"]["label"], doc["list"]["missing_count"], ledger.ORDER4_SCRIPT,
             doc["code"]["script"]["sha256"], doc["head"]))
    print("コミット: %s（記録・中身・.ots。結果は、このコミットのあとで表示している）" % commit)
    if ots_path is not None:
        print("時刻証明: %s" % os.path.relpath(ots_path, ledger.PROJECT_ROOT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
