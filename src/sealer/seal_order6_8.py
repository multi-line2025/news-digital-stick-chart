#!/usr/bin/env python3
"""順番6〜8 と採点計画（docs/stats/seal-order6-8.md の封印の対象のすべて）の記録を書く入口（kind: stats-order6-8）。T-144。
手順は docs/verify/periods-seal.md 20章。

使い方（プロジェクトのルートで。ots の通信を使うので .venv の python で実行する。root はこのファイルの場所から決まる）
    PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -B src/sealer/seal_order6_8.py --t117-cache <explore-t117-cache/run2>
    PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -B src/sealer/seal_order6_8.py --commit-written

封印する中身は統計係がコミットしたファイルで、この入口は値を選ばない。HEAD の版のファイルの sha256 と、最後に変えたコミットと、
オーナーの決定の行を記録し、出力が封印したコードから同じに作れることを流し直して確かめてから書く。

1回の実行は、次の順で進む。途中で止まったら、それより後のことはしない。
  0. 記録の鎖とすべての .ots を検証する。作業ツリーがきれいで、HEAD（A）が決まる。
  1. 書く前の確かめ（何も書かない。止まれば何も書いていない）：位置（順番5（ok）のあと、threshold-access の前。
     ledger.check_order68_position）、一覧の文書の4章の表と HEAD の版のファイルの sha256・最後に変えたコミット、オーナーの決定の
     行、順番7の出力が periods の1件目と区切りで同じこと、データを使わない出力（periods.py・naive.py・scoring.py）の流し直し
     （verify.check_order68_git）。キャッシュが要る出力（order8_fit.py・tiers_select.py・chain_cap_check.py。約30分）の
     流し直し（verify.rerun_order68）。
  2. 順番7のきっかけの値（ledger.ORDER7_TRIGGERS）が、最後の periods-triggers の記録の値でなければ、periods-triggers の記録を
     書いてコミットする（seal_triggers.seal。.ots も作る。HEAD は B になる）。同じ値なら書かない。
  3. 順番6〜8 の記録を書く。書く前の照合（seal_records.check_new）で、1 と同じ確かめを B の版でもう一度行う（キャッシュが要る
     流し直しは、1 で同じコミットの版を流した結果を使う）。recorded_at は追記の直前に取る（T-112）。.ots を作り、パス指定で
     コミットする。
  4. 結果は、コミットのあとで画面に出す。書いたあとで止まったときは Order68Written で知らせる。

ネットワークは ots の stamp だけ。
"""

import argparse
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import ledger  # noqa: E402
import seal_order2  # noqa: E402
import seal_order5  # noqa: E402
import seal_records  # noqa: E402
import seal_triggers  # noqa: E402
import stamp  # noqa: E402
import verify  # noqa: E402

TRIGGERS_MESSAGE = "順番7のきっかけの値の記録（periods-triggers。src/sealer/seal_order6_8.py が書いてコミットした）"
ORDER68_MESSAGE = "順番6〜8 と採点計画の記録（stats-order6-8。src/sealer/seal_order6_8.py が書いてコミットした）"
MESSAGES = {ledger.TRIGGERS_KIND: TRIGGERS_MESSAGE, ledger.ORDER68_KIND: ORDER68_MESSAGE}


class Order68Written(ledger.LedgerError):
    """記録（periods-triggers、または順番6〜8）は書いたが、そのあとの段で止まった。「何も書いていない」とは表示しない。"""


def _read(root):
    return lambda r, role: ledger.read_target_json(root, r, role)


def build_doc(root, data, records, triggers_rec):
    """順番6〜8 の記録の中身を、HEAD の版と記録から作る。triggers_rec は、指す periods-triggers の記録（None なら仮の参照）。"""
    repo = verify.Repo(root)
    head = seal_order2.clean_head(repo)
    read = _read(root)
    seq = len(records) + 1
    ledger.check_order68_position(records, {"seq": seq, "kind": ledger.ORDER68_KIND}, read)
    ld, _text = verify.order68_list_doc_at(repo, head)
    targets = verify.order68_targets_at(repo, head)
    sha = {t["path"]: t["sha256"] for t in targets}
    py = sys.version.split()[0]
    p1 = ledger._first_of_kind(records, ledger.PERIODS_KIND)
    out1 = read(p1, "output")
    tref = ({"seq": 0, "record_sha256": "0" * 64} if triggers_rec is None else ledger.record_ref(triggers_rec))
    return {
        "kind": ledger.ORDER68_KIND, "ledger_head": ledger.expected_ledger_head(data, seq), "head": head, "python": py,
        "list_doc": ld, "targets": targets, "sealed_code": ledger.order68_sealed_code(records, read),
        "decisions": ledger.expected_order68_decisions(), "order6": dict(ledger.ORDER6),
        "order7": {"naive_history_days": ledger.ORDER7_NAIVE_HISTORY_DAYS, "output": ledger.ORDER7_OUTPUT,
                   "triggers": dict(tref, values=dict(ledger.ORDER7_TRIGGERS))},
        "periods": {"base": ledger.record_ref(p1), "lookback_days": out1["rules"]["lookback_days"],
                    "embargo_days": ledger.periods_embargo_days(out1),
                    "naive_history_days": ledger.ORDER7_NAIVE_HISTORY_DAYS,
                    "network_window_days_max": ledger.ORDER68_NETWORK_WINDOW_DAYS_MAX, "rebuild": False,
                    "cross_block_inputs": list(ledger.ORDER68_CROSS_BLOCK_INPUTS), "rule": ledger.ORDER68_PERIODS_RULE},
        "data_free": [{"script": s, "args": list(a), "output": o, "sha256": sha[o]} for s, a, o in ledger.ORDER68_DATA_FREE],
        "reruns": [{"script": s, "out_dir": d, "python": py,
                    "commit": verify.order68_last_change(repo, head, ["%s/%s" % (d, n) for n in names]),
                    "files": [{"name": n, "sha256": sha["%s/%s" % (d, n)]} for n in names]}
                   for s, d, names, _extra in ledger.ORDER68_RERUNS],
    }


def precheck(root, data, records, cache, memo, tmp):
    """手順 1（何も書かない）。仮の中身で、git の照合・データを使わない出力の流し直し・キャッシュが要る出力の流し直しを行う。
    返り値：HEAD（A）。"""
    repo = verify.Repo(root)
    doc = build_doc(root, data, records, None)
    rec = {"seq": len(records) + 1, "kind": ledger.ORDER68_KIND}
    what = "順番6〜8（書く前の確かめ）"
    verify.check_order68_git(repo, data, records, rec, doc, doc["head"], _read(root), tmp)
    try:
        verify.rerun_order68(repo, doc, cache, tmp, what, memo=memo)
    except verify.Unchecked as e:
        raise ledger.LedgerError("流し直せない（%s）" % e) from None
    return doc["head"]


def _write(root, doc, data, records, note, now, ots_cmd, runner, inputs):
    """順番6〜8 の記録を1件書き、.ots を作り、コミットする（seal_order5._write と同じ扱い）。追記の前で止まれば LedgerError。
    追記のあとで止まれば Order68Written。返り値：(記録, 中身のパス, .ots のパスか None, コミット)。"""
    kind = ledger.ORDER68_KIND
    repo = verify.Repo(root)
    try:
        rec, rel, ots_path = seal_records.write_doc_record(root, kind, doc, data, note, now, ots_cmd, runner=runner,
                                                           order68_inputs=inputs)
    except ledger.LedgerError as e:
        after = ledger.verify_chain(ledger.read_ledger(os.path.join(root, "sealed", "ledger.jsonl")))
        if len(after) <= len(records):
            raise
        last = after[-1]
        try:
            c = seal_order2.commit_record(repo, root, last, None, MESSAGES[kind])
        except ledger.LedgerError as e2:
            raise Order68Written("記録 seq %d（%s）と中身を作業ツリーに書いたが、.ots を作れず（%s）、コミットもしていない（%s）。"
                                 "消さずに、原因を直してから seal_order6_8.py --commit-written でコミットし、stamp.py stamp --seq %d"
                                 " で .ots を作る" % (last["seq"], kind, e, e2, last["seq"])) from None
        raise Order68Written("記録 seq %d（%s）と中身を書いてコミット %s に入れたが、.ots を作れなかった（%s）。stamp.py stamp "
                             "--seq %d で .ots を作ってコミットする" % (last["seq"], kind, c[:12], e, last["seq"])) from None
    return rec, rel, ots_path, _commit(root, rec, ots_path, kind)


def _commit(root, rec, ots_path, kind):
    repo = verify.Repo(root)
    try:
        return seal_order2.commit_record(repo, root, rec, ots_path, MESSAGES[kind])
    except ledger.LedgerError as e:
        raise Order68Written("記録 seq %d（%s）・中身・.ots を作業ツリーに書いたが、コミットしていない（%s）。消さずに、原因を直して"
                             "から seal_order6_8.py --commit-written でコミットする（手順書20章）" % (rec["seq"], kind, e)) from None


def write_triggers(root, ots_cmd, runner):
    """手順 2。返り値：(記録, .ots のパス, コミット)。"""
    rec, ots_path, _sub = seal_triggers.seal(root, dict(ledger.ORDER7_TRIGGERS), seal_records.utc_now(), ots_cmd, runner=runner)
    return rec, ots_path, _commit(root, rec, ots_path, ledger.TRIGGERS_KIND)


def seal(cache, now, ots_cmd, runner=subprocess.run):
    """書く前に確かめ、必要なら periods-triggers を、続けて順番6〜8 の記録を書いてコミットする。
    返り値：{"triggers": (記録, .ots, コミット) か None（書かなかった）, "order68": (記録, 中身のパス, .ots, 中身, コミット)}。"""
    root = ledger.check_sealed_inside(ledger.PROJECT_ROOT)
    cache = seal_order5.check_outside(root, cache)
    data, records = seal_records.load_checked(root, ots_cmd, runner=runner)
    memo = {}
    with tempfile.TemporaryDirectory() as tmp:
        precheck(root, data, records, cache, memo, tmp)
    out = {"triggers": None, "order68": None}
    last = ledger._last_before(records, ledger.TRIGGERS_KIND, len(records) + 1)
    if last is None or ledger.triggers_values(_read(root)(last, "triggers")) != ledger.ORDER7_TRIGGERS:
        out["triggers"] = write_triggers(root, ots_cmd, runner)
    try:
        data, records = seal_records.load_checked(root, ots_cmd, runner=runner)
        trec = ledger._last_before(records, ledger.TRIGGERS_KIND, len(records) + 1)
        doc = build_doc(root, data, records, trec)
        n = sum(1 for r in records if r["kind"] == ledger.ORDER68_KIND) + 1
        note = ("統計係の順番6〜8 と採点計画（docs/stats/seal-order6-8.md の対象 %d 件）。stats-order6-8 の %d 件目。順番7の"
                "きっかけの値は periods-triggers seq %d。採用の区切りには使わない。" % (len(doc["targets"]), n, trec["seq"]))
        rec, rel, ots_path, commit = _write(root, doc, data, records, note, now, ots_cmd, runner,
                                            {"cache": cache, "memo": memo})
    except Order68Written:
        raise
    except (ledger.LedgerError, OSError) as e:
        if out["triggers"] is None:
            raise
        t = out["triggers"][0]
        raise Order68Written("periods-triggers の記録 seq %d は書いてコミット %s に入れたが、順番6〜8 の記録は書いていない（%s）。"
                             "原因を直してから、もう一度この入口を流す（periods-triggers は同じ値なので書き足さない）"
                             % (t["seq"], out["triggers"][2][:12], e)) from None
    out["order68"] = (rec, rel, ots_path, doc, commit)
    return out


def commit_written(root):
    """書いたがコミットしていない最後の記録（stats-order6-8 か periods-triggers）を、入口と同じ固定のしかたでコミットする。"""
    data = ledger.read_ledger(os.path.join(root, "sealed", "ledger.jsonl"))
    rec = ledger.verify_chain(data)[-1]
    if rec["kind"] == ledger.ORDER68_KIND:
        return seal_order2.commit_written(root, (ledger.ORDER68_KIND,), MESSAGES)
    if rec["kind"] != ledger.TRIGGERS_KIND:
        raise ledger.LedgerError("最後の記録が %s・%s でない。コミットしない" % (ledger.ORDER68_KIND, ledger.TRIGGERS_KIND))
    # periods-triggers：中身に head が無いので seal_order2.check_written を使わず、同じ照合をここで行う
    repo = verify.Repo(root)
    ledger.check_sealed_inside(root)
    lines = ledger.split_lines(data)
    prefix = b"".join(x + b"\n" for x in lines[:-1])
    sealed = os.path.join(root, "sealed")
    ots = os.path.join(sealed, ledger.ots_name(rec["seq"]))
    if os.path.isfile(ots):
        seal_records.load_checked(root, None)
    else:
        ledger.check_anchors(prefix, sealed)
        ots = None
    r = subprocess.run(["git", "-C", root, "cat-file", "blob", "HEAD:sealed/ledger.jsonl"], capture_output=True,
                       env=ledger.fixed_git_env())
    if r.returncode != 0 or r.stdout != prefix:
        raise ledger.LedgerError("HEAD の版の sealed/ledger.jsonl が、今の記録から最後の seq %d を除いたものと同じでない。"
                                 "コミットしない" % rec["seq"])
    if ledger.triggers_values(ledger.read_target_json(root, rec, "triggers")) != ledger.ORDER7_TRIGGERS:
        raise ledger.LedgerError("最後の periods-triggers の値が、順番7の値でない。コミットしない")
    paths = {"sealed/ledger.jsonl"} | {t["path"] for t in rec["targets"]}
    if ots is not None:
        paths.add(os.path.relpath(ots, root).replace(os.sep, "/"))
    changed = {line[3:] for line in verify._rgit(repo, "status", "--porcelain", "--untracked-files=all").decode("utf-8")
               .splitlines()}
    if not changed or not changed <= paths:
        raise ledger.LedgerError("作業ツリーの変更（%s）が、最後の periods-triggers の記録・中身・.ots だけでない。コミットしない"
                                 % "、".join(sorted(changed)))
    return seal_order2.commit_record(repo, root, rec, ots, TRIGGERS_MESSAGE)


def main(argv=None):
    p = argparse.ArgumentParser(allow_abbrev=False, description=__doc__.splitlines()[0])
    p.add_argument("--t117-cache", help="手法を作る期間のキャッシュ（explore-t117-cache/run2。プロジェクトと Git の外）")
    p.add_argument("--ots", default=stamp.DEFAULT_OTS)
    p.add_argument("--commit-written", action="store_true",
                   help="書いたがコミットしていない最後の stats-order6-8・periods-triggers の記録をコミットする")
    a = p.parse_args(argv)
    if a.commit_written:
        try:
            c = commit_written(ledger.check_sealed_inside(ledger.PROJECT_ROOT))
        except ledger.LedgerError as e:
            print("失敗（コミットしていない）: %s" % e, file=sys.stderr)
            return 1
        print("コミット: %s" % c)
        return 0
    if not a.t117_cache:
        p.error("--t117-cache が要る")
    try:
        # T-112：recorded_at は、追記の直前に取る（now に None を渡す）
        out = seal(a.t117_cache, None, a.ots)
    except Order68Written as e:
        print("止まった（記録は書いた）: %s" % e, file=sys.stderr)
        return 1
    except ledger.LedgerError as e:
        print("失敗（記録は書いていない）: %s" % e, file=sys.stderr)
        return 1
    if out["triggers"] is not None:
        t, _o, c = out["triggers"]
        print(ledger.canonical_line(t).decode("utf-8"))
        print("periods-triggers：コミット %s" % c)
    rec, _rel, _ots, doc, commit = out["order68"]
    print(ledger.canonical_line(rec).decode("utf-8"))
    print("順番6〜8：一覧 %s の sha256 %s、対象 %d 件、オーナーの決定 %d 件、periods-triggers seq %d、区切りの作り直し 要らない"
          % (doc["list_doc"]["path"], doc["list_doc"]["sha256"], len(doc["targets"]), len(doc["decisions"]),
             doc["order7"]["triggers"]["seq"]))
    print("コミット: %s（記録・中身・.ots）" % commit)
    return 0


if __name__ == "__main__":
    sys.exit(main())
