#!/usr/bin/env python3
"""Bitcoin での確定を取り込む仕組み（upgrade と、ブロックのヘッダの書き込み）。T-009。

元の .ots（ledger.jsonl.seqNNNNNN.ots）は書き換えない。書くのは新しいファイルだけで、
既にあれば上書きしない。
  - sealed/ledger.jsonl.seqNNNNNN.bitcoin.ots   upgrade の結果（stamp.upgrade_seq）
  - sealed/bitcoin-header-<高さ>.hex            その高さのブロックのヘッダ（80 バイトの16進と改行）

使い方（プロジェクトのルートで。通信を使うので、実行は通信の許可を得てから）
    PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -B src/sealer/seal_bitcoin.py upgrade --seq N
        元の .ots の写しを ots upgrade し、Bitcoin の証明があれば .bitcoin.ots を書く。
        まだ確定していなければ何も書かず、終了コード 1。
    PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -B src/sealer/seal_bitcoin.py header --height H \\
        [--source explorers|bitcoin-cli]
        高さ H のヘッダを取り、sealed/ の .ots の中の、高さ H の Bitcoin の証明と照合してから書く。
    PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -B src/sealer/seal_bitcoin.py confirm --seq N \\
        [--source explorers|bitcoin-cli]
        upgrade（.bitcoin.ots が既にあれば飛ばす）と、その中のすべての高さの header をまとめて行う。

ヘッダを書く前に確かめること（どれかが通らなければ書かない）
  1. 記録の鎖と、すべての .ots の対象・Pending の宛先（ledger.check_anchors）
  2. sealed/ の .ots のどれかに、高さ H の Bitcoin の証明があること（無い高さのヘッダを置くと、
     verify.py が失敗にするため）
  3. ヘッダが、その証明の値と照合に通ること（マークルルート・作業量の証明・作業量の下限。
     otsfile.check_header）
  4. 取得先：explorers なら、2 つのブロックエクスプローラーが同じヘッダを返し、ヘッダのハッシュが
     返されたブロックのハッシュと一致すること（netfetch.header_from_explorers）
ヘッダが Bitcoin の本当の鎖にあることは、ここでも証明しない。第三者は、自分のノードや
ots verify で確かめる（docs/verify/periods-seal.md 5章）。

通信を差し替えられるところ
  runner：subprocess.run の代わり（ots upgrade、bitcoin-cli）
  header_fetch：高さ → 80 バイトのヘッダ を返す関数（netfetch.header_from_explorers などの代わり）
"""

import argparse
import functools
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import ledger  # noqa: E402
import netfetch  # noqa: E402
import otsfile  # noqa: E402
import stamp  # noqa: E402

PROJECT = os.path.dirname(os.path.dirname(HERE))


def header_name(height):
    return "bitcoin-header-%d.hex" % height


def _anchors(project):
    sealed = os.path.join(project, "sealed")
    data = ledger.read_ledger(os.path.join(sealed, "ledger.jsonl"))
    ledger.verify_chain(data)
    return sealed, ledger.check_anchors(data, sealed)


def write_header(project, height, header_fetch, min_work_bits=otsfile.MIN_WORK_BITS):
    """高さ height のヘッダを取り、照合してから sealed/bitcoin-header-<高さ>.hex に書く。

    返り値: (書いたパス, ヘッダの時刻, ブロックのハッシュ)。既に同じ中身があれば書かずに同じ値を返す。
    """
    sealed, anchors = _anchors(project)
    msgs = [(seq, a["msg"]) for seq, _p, _d, atts in anchors for a in atts
            if a["type"] == "bitcoin" and a["height"] == height]
    if not msgs:
        raise ledger.LedgerError("高さ %d の Bitcoin の証明は、sealed/ の .ots の中に無い。"
                                 "ヘッダを書かない" % height)
    try:
        header = header_fetch(height)
    except netfetch.FetchError as e:
        raise ledger.LedgerError("高さ %d のヘッダを取れなかった: %s" % (height, e)) from None
    if not isinstance(header, bytes) or len(header) != 80:
        raise ledger.LedgerError("ヘッダが 80 バイトでない")
    result = None
    for seq, msg in msgs:
        try:
            result = otsfile.check_header(header, msg, min_work_bits=min_work_bits)
        except otsfile.OtsError as e:
            raise ledger.LedgerError("seq %d の高さ %d の証明と、取ったヘッダが照合に通らない: %s"
                                     % (seq, height, e)) from None
    path = os.path.join(sealed, header_name(height))
    ledger.write_once(path, header.hex().encode("ascii") + b"\n")
    return path, result[0], result[1]


def confirm(project, seq, ots_cmd, header_fetch, runner=subprocess.run,
            min_work_bits=otsfile.MIN_WORK_BITS):
    """upgrade と header をまとめて行う。返り値: (.bitcoin.ots のパス か None, [書いたヘッダのパス])。"""
    sealed = os.path.join(project, "sealed")
    ledger_path = os.path.join(sealed, "ledger.jsonl")
    dst = os.path.join(sealed, ledger.ots_name(seq, bitcoin=True))
    if not os.path.exists(dst):
        if stamp.upgrade_seq(ledger_path, seq, ots_cmd, runner=runner) is None:
            return None, []
    written = []
    for h in stamp.bitcoin_heights(dst):
        if os.path.exists(os.path.join(sealed, header_name(h))):
            continue
        written.append(write_header(project, h, header_fetch, min_work_bits)[0])
    return dst, written


def header_fetcher(source, runner=subprocess.run):
    if source == "bitcoin-cli":
        return functools.partial(netfetch.header_from_bitcoin_cli, runner=runner)
    return netfetch.header_from_explorers


def main(argv=None):
    p = argparse.ArgumentParser(allow_abbrev=False, description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest="action", required=True)
    u = sub.add_parser("upgrade", allow_abbrev=False)
    u.add_argument("--seq", type=int, required=True)
    h = sub.add_parser("header", allow_abbrev=False)
    h.add_argument("--height", type=int, required=True)
    c = sub.add_parser("confirm", allow_abbrev=False)
    c.add_argument("--seq", type=int, required=True)
    for q in (u, h, c):
        q.add_argument("--root", default=PROJECT)
        q.add_argument("--ots", default=stamp.DEFAULT_OTS)
    for q in (h, c):
        q.add_argument("--source", choices=("explorers", "bitcoin-cli"), default="explorers")
    a = p.parse_args(argv)
    root = os.path.abspath(a.root)
    ledger_path = os.path.join(root, "sealed", "ledger.jsonl")
    try:
        if a.action == "upgrade":
            stamp.check_ots(a.ots)
            path = stamp.upgrade_seq(ledger_path, a.seq, a.ots)
            if path is None:
                print("まだ Bitcoin で確定していない。時間をおいて再実行する。")
                return 1
            print("書いた: %s（元の .ots は残した）" % os.path.relpath(path, root))
        elif a.action == "header":
            path, when, block = write_header(root, a.height, header_fetcher(a.source))
            print("書いた: %s（ヘッダの時刻 %s、ブロックのハッシュ %s）"
                  % (os.path.relpath(path, root), when.isoformat(), block))
        else:
            stamp.check_ots(a.ots)
            path, written = confirm(root, a.seq, a.ots, header_fetcher(a.source))
            if path is None:
                print("まだ Bitcoin で確定していない。時間をおいて再実行する。")
                return 1
            print("確定の証明: %s（元の .ots は残した）" % os.path.relpath(path, root))
            for w in written:
                print("書いた: %s" % os.path.relpath(w, root))
    except ledger.LedgerError as e:
        print("失敗: %s" % e, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
