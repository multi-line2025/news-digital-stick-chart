#!/usr/bin/env python3
"""順番2の前の関門（T-073）。封印係が順番2で src/stats/counting.py を動かす前に、必ず最初に流す。

使い方（プロジェクトのルートで。引数は受け付けない。root はこのファイルの場所から決まる）
    PYTHONDONTWRITEBYTECODE=1 python3 -B src/sealer/order2_gate.py

すること
  1. 二つのマニフェスト（data/manifest/gdelt-gkg-trial.jsonl・gdelt-gkg-method.jsonl）について、counting.md 4章 (1)
     の git の確かめを先に行う：作業ツリーのファイルが HEAD の版と同じ（どちらにも無いのは同じとみなす）、
     `git log --all --full-history --format=%H -- <パス>` の各 commit の版（無い版は空）が HEAD の版の先頭と同じ。
     どちらかが通らなければ関門は閉じる（git は GIT_ の環境変数を固定して動かす：ledger.fixed_git_env）。
  2. HEAD の版のバイト列から、ledger.order2_plan で decide() の行き先を決める（decide() と同じ決め方。データは
     読まない）。待つなら閉じる。日の集計を読む前に止まる形なら、run に結び付けずに開く（input_run・
     gkg_run_result は null）。
  3. 日の集計を読む run があれば、ledger.require_gkg_run_result(mode, run_id) を呼ぶ（鎖・すべての .ots・
     マニフェストの照合と、その run の gkg-run-result の記録）。
  通れば、順番2の記録に入れる input_run と gkg_run_result（と、決めた行き先 plan）を JSON で標準出力に書き、
  終了コード 0。通らなければ理由を標準エラーに書き、終了コード 1。このときは counting.py を動かさず、順番2の
  記録も作らない（止まった (b) としても記録しない。docs/verify/periods-seal.md 14章）。

ネットワークは使わない。何も書かない。
"""

import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import ledger  # noqa: E402


def _git(root, *args):
    try:
        return subprocess.run(["git", "-C", root] + list(args), capture_output=True, env=ledger.fixed_git_env())
    except OSError as e:
        raise ledger.Order2GateClosed("git を動かせない（%s）" % e.__class__.__name__) from None


def version_at(root, commit, rel):
    """commit の版のバイト列（そのパスが無ければ None）。"""
    if _git(root, "cat-file", "-e", "%s:%s" % (commit, rel)).returncode != 0:
        return None
    r = _git(root, "show", "%s:%s" % (commit, rel))
    if r.returncode != 0:
        raise ledger.Order2GateClosed("%s の %s を読めない" % (commit[:12], rel))
    return r.stdout


def head_version(root, rel):
    """HEAD の版のバイト列（HEAD にそのパスが無ければ b""）。"""
    if _git(root, "rev-parse", "--verify", "-q", "HEAD^{commit}").returncode != 0:
        raise ledger.Order2GateClosed("HEAD の commit が無い")
    v = version_at(root, "HEAD", rel)
    return b"" if v is None else v


def checked_manifest(root, rel):
    """counting.md 4章 (1) の git の確かめ（T-073 差し戻し1回目 中-1）。通れば HEAD の版のバイト列（無ければ b""）。
      - 作業ツリーのファイルが HEAD の版と同じ（どちらにも無いのは同じ。通常のファイルでなければ違う）。
      - git log --all --full-history の各 commit の版（無い版は空）が、HEAD の版の先頭と同じ（追記だけ）。
    通らなければ Order2GateClosed（記録は作らない）。"""
    head = head_version(root, rel)
    in_head = version_at(root, "HEAD", rel) is not None
    path = os.path.join(root, rel)
    if os.path.lexists(path):
        if os.path.islink(path) or not os.path.isfile(path):
            raise ledger.Order2GateClosed("%s が通常のファイルでない" % rel)
        with open(path, "rb") as f:
            work = f.read()
        if not in_head or work != head:
            raise ledger.Order2GateClosed("%s の作業ツリーのファイルが HEAD の版と違う（コミットしていない行がある。"
                                          "取得の途中なら、終わってコミットしてから流す）" % rel)
    elif in_head:
        raise ledger.Order2GateClosed("%s が HEAD にあるのに、作業ツリーに無い" % rel)
    r = _git(root, "log", "--all", "--full-history", "--format=%H", "--", rel)
    if r.returncode != 0:
        raise ledger.Order2GateClosed("%s の git log を読めない" % rel)
    for c in r.stdout.decode("ascii", "replace").split():
        v = version_at(root, c, rel) or b""
        if not head.startswith(v):
            raise ledger.Order2GateClosed("%s の %s の版が、HEAD の版の先頭と合わない（コミットした行が書き換えられたか"
                                          "消された）" % (rel, c[:12]))
    return head


def gate():
    """関門。通れば {"input_run", "gkg_run_result", "plan"}。通らなければ Order2GateClosed。"""
    root = ledger.check_sealed_inside(ledger.PROJECT_ROOT)
    trial = checked_manifest(root, ledger.GKG_MANIFESTS["trial"])
    official = checked_manifest(root, ledger.GKG_MANIFESTS["official"])
    return ledger.require_order2_gate(trial, official)


def main(argv=None):
    if argv is None:
        argv = sys.argv[1:]
    if argv:
        sys.stderr.write("order2_gate: 引数は受け付けない\n")
        return 2
    try:
        got = gate()
    except ledger.LedgerError as e:
        sys.stderr.write("関門が通らない（counting.py を動かさず、順番2の記録も作らない）：%s\n" % e)
        return 1
    sys.stdout.write(json.dumps(got, ensure_ascii=False, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
