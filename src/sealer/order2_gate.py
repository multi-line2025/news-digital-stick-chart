#!/usr/bin/env python3
"""順番2の前の関門（T-073）。封印係が順番2で src/stats/counting.py を動かす前に、必ず最初に流す。

使い方（プロジェクトのルートで。引数は受け付けない。root はこのファイルの場所から決まる）
    PYTHONDONTWRITEBYTECODE=1 python3 -B src/sealer/order2_gate.py

すること
  1. 二つのマニフェスト（data/manifest/gdelt-gkg-trial.jsonl・gdelt-gkg-method.jsonl）の、HEAD の版のバイト列を
     読む（git show HEAD:<パス>。HEAD に無ければ空。counting.md 4章 (1) と同じ版。git は GIT_ の環境変数を
     固定して動かす：ledger.fixed_git_env）。
  2. ledger.order2_input_run で、順番2が使う run を決める（counting.decide() の段の決め方と同じ。データは読まない）。
  3. ledger.require_gkg_run_result(mode, run_id) を呼ぶ（鎖・すべての .ots・マニフェストの照合と、その run の
     gkg-run-result の記録）。
  通れば、順番2の記録に入れる input_run と gkg_run_result を JSON で標準出力に書き、終了コード 0。
  通らなければ理由を標準エラーに書き、終了コード 1。このときは counting.py を動かさず、順番2の記録も作らない
  （止まった (b) としても記録しない。docs/verify/periods-seal.md 14章）。

ネットワークは使わない。何も書かない。
"""

import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import ledger  # noqa: E402


def head_version(root, rel):
    """HEAD の版のバイト列（HEAD にそのパスが無ければ b""）。git が使えなければ Order2GateClosed。"""
    env = ledger.fixed_git_env()
    base = ["git", "-C", root]
    try:
        ok = subprocess.run(base + ["rev-parse", "--verify", "-q", "HEAD^{commit}"], capture_output=True, env=env)
        if ok.returncode != 0:
            raise ledger.Order2GateClosed("HEAD の commit が無い")
        has = subprocess.run(base + ["cat-file", "-e", "HEAD:" + rel], capture_output=True, env=env)
        if has.returncode != 0:
            return b""
        r = subprocess.run(base + ["show", "HEAD:" + rel], capture_output=True, env=env)
    except OSError as e:
        raise ledger.Order2GateClosed("git を動かせない（%s）" % e.__class__.__name__) from None
    if r.returncode != 0:
        raise ledger.Order2GateClosed("HEAD の版の %s を読めない" % rel)
    return r.stdout


def gate():
    """関門。通れば {"input_run", "gkg_run_result"}。通らなければ Order2GateClosed。"""
    root = ledger.check_sealed_inside(ledger.PROJECT_ROOT)
    trial = head_version(root, ledger.GKG_MANIFESTS["trial"])
    official = head_version(root, ledger.GKG_MANIFESTS["official"])
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
