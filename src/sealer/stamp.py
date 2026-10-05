#!/usr/bin/env python3
"""記録への OpenTimestamps の時刻証明。T-005、T-007、T-009。

OpenTimestamps のクライアント（ots）をそのまま使う。中身は送らない。
- stamp: 記録の先頭 N 行のバイト列を ots の標準入力に渡す。ots はそれを手元で sha256 にし、
  16 バイトのランダムな値（nonce）を付けてもう一度 sha256 にしたものだけを公開カレンダーに
  送る。カレンダーには記録のハッシュそのものも届かない。
- upgrade: 確定前の .ots を一時的な場所に写し、そこで ots upgrade を実行する。
  Bitcoin の確定が入っていれば（この判定は ots info の表示ではなく、otsfile で .ots を読んで
  行う）、元の .ots を書き換えずに sealed/ledger.jsonl.seqNNNNNN.bitcoin.ots として新しく書く。
  ブロックのヘッダの書き込みは seal_bitcoin.py（T-009）。

使い方（プロジェクトのルートで）
    .venv/bin/python -B src/sealer/stamp.py stamp   [--seq N]   最後の記録（または seq N）に付ける
    .venv/bin/python -B src/sealer/stamp.py upgrade [--seq N]   Bitcoin の確定を取りにいく

ネットワークを使うのは、ots の stamp と upgrade だけ（OpenTimestamps の公開カレンダー）。
"""

import argparse
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import ledger  # noqa: E402
import otsfile  # noqa: E402

PROJECT = os.path.dirname(os.path.dirname(HERE))
DEFAULT_LEDGER = os.path.join(PROJECT, "sealed", "ledger.jsonl")
DEFAULT_OTS = os.path.join(PROJECT, ".venv", "bin", "ots")

# ots の stamp が使う公開カレンダー（ots の既定と同じ 4 つ）。2 つ以上が応答すれば完了。
# 一覧は ledger.STAMP_CALENDARS に置く。検証は、.ots の Pending の宛先を、これらの集約先が
# 返す実体のカレンダー（ledger.ALLOWED_PENDING_URIS）に限る。
CALENDARS = tuple(submit for submit, _uri in ledger.STAMP_CALENDARS)
MIN_CALENDARS = 2
TIMEOUT_SECONDS = 20


def check_ots(ots_cmd, runner=subprocess.run):
    """ots が実行できることを、何かを書く前に確かめる。版の文字列を返す。"""
    try:
        r = runner([ots_cmd, "--version"], capture_output=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise ledger.LedgerError("ots を実行できない: %s" % type(e).__name__) from None
    if r.returncode != 0:
        raise ledger.LedgerError("ots --version が失敗した")
    return (r.stdout + r.stderr).decode("utf-8", "replace").strip()


def stamp_seq(ledger_path, seq, ots_cmd=DEFAULT_OTS, runner=subprocess.run):
    """記録の先頭 seq 行に時刻証明を付け、sealed/ledger.jsonl.seqNNNNNN.ots を書く。

    返り値: (.ots のパス, 応答したカレンダーの一覧, 送ったカレンダーの一覧)
    """
    data = ledger.read_ledger(ledger_path)
    ledger.verify_chain(data)
    prefix = ledger.prefix_bytes(data, seq)
    sealed_dir = os.path.dirname(ledger_path)
    out_path = os.path.join(sealed_dir, ledger.ots_name(seq))
    if os.path.exists(out_path):
        raise ledger.LedgerError("%s は既にある。上書きしない" % out_path)
    cmd = [ots_cmd, "-v", "--no-cache", "stamp", "-m", str(MIN_CALENDARS),
           "--timeout", str(TIMEOUT_SECONDS)]
    for c in CALENDARS:
        cmd += ["-c", c]
    r = runner(cmd, input=prefix, capture_output=True, timeout=TIMEOUT_SECONDS + 60)
    err = r.stderr.decode("utf-8", "replace")
    if r.returncode != 0:
        raise ledger.LedgerError("ots stamp が失敗した（終了コード %d）:\n%s" % (r.returncode, err))
    ots_bytes = r.stdout
    digest = ledger.ots_file_digest(ots_bytes)
    if digest != ledger.sha256_hex(prefix):
        raise ledger.LedgerError("ots が返した .ots の対象が、記録の先頭 %d 行と一致しない" % seq)
    ledger.write_once(out_path, ots_bytes)
    submitted = [c for c in CALENDARS if c in err]
    return out_path, err, submitted


def upgrade_seq(ledger_path, seq, ots_cmd=DEFAULT_OTS, runner=subprocess.run):
    """確定前の .ots の写しを upgrade し、Bitcoin の確定があれば .bitcoin.ots として書く。T-005、T-009。

    手順
      1. 元の .ots（ledger.jsonl.seqNNNNNN.ots）の対象が、記録の先頭 seq 行と一致することを確かめる。
      2. 元の .ots を一時的な場所に写し、写しに ots upgrade を実行する（ネットワークを使う）。
         ots は写しを書き換え、写しの .bak を作る。元の .ots には触れない。
      3. upgrade した写しを、このコード（otsfile）で読む。Bitcoin の証明が無ければ、何も書かずに
         None を返す（まだ確定していない）。
      4. 対象のハッシュが記録の先頭 seq 行と一致し、Pending の宛先が許可した 4 つ
         （ledger.ALLOWED_PENDING_URIS）の中にあることを確かめる。
      5. ledger.jsonl.seqNNNNNN.bitcoin.ots として新しく書く（既にあれば止める。上書きしない）。
    元の .ots は書き換えない。返り値: 書いたパス（まだ確定していなければ None）。
    runner: subprocess.run の代わり（テストで ots の通信を差し替える）。
    """
    sealed_dir = os.path.dirname(ledger_path)
    src = os.path.join(sealed_dir, ledger.ots_name(seq))
    dst = os.path.join(sealed_dir, ledger.ots_name(seq, bitcoin=True))
    if os.path.exists(dst):
        raise ledger.LedgerError("%s は既にある。上書きしない" % dst)
    data = ledger.read_ledger(ledger_path)
    ledger.verify_chain(data)
    expect = ledger.prefix_digest(data, seq)
    with open(src, "rb") as f:
        original = f.read()
    if ledger.ots_file_digest(original) != expect:
        raise ledger.LedgerError("%s の対象が、記録の先頭 %d 行と一致しない" % (src, seq))
    with tempfile.TemporaryDirectory() as tmp:
        work = os.path.join(tmp, ledger.ots_name(seq))
        shutil.copyfile(src, work)
        r = runner([ots_cmd, "upgrade", work], capture_output=True, timeout=300)
        with open(work, "rb") as f:
            upgraded = f.read()
    try:
        digest, atts = otsfile.parse(upgraded)
    except otsfile.OtsError as e:
        raise ledger.LedgerError("upgrade の後の .ots を読めない: %s" % e) from None
    if digest != expect:
        raise ledger.LedgerError("upgrade の後の .ots の対象が、記録の先頭 %d 行と一致しない" % seq)
    if not any(a["type"] == "bitcoin" for a in atts):
        sys.stderr.write(r.stderr.decode("utf-8", "replace"))
        return None
    bad = sorted({a["uri"] for a in atts
                  if a["type"] == "pending" and a["uri"] not in ledger.ALLOWED_PENDING_URIS})
    if bad:
        raise ledger.LedgerError("upgrade の後の .ots に、許可していないカレンダーの Pending がある: %s"
                                 % ", ".join(bad))
    with open(src, "rb") as f:
        if f.read() != original:
            raise ledger.LedgerError("upgrade の間に元の .ots が変わった")
    ledger.write_once(dst, upgraded)
    return dst


def bitcoin_heights(ots_path):
    """.ots の中の Bitcoin の証明の高さの一覧。"""
    with open(ots_path, "rb") as f:
        try:
            _digest, atts = otsfile.parse(f.read())
        except otsfile.OtsError as e:
            raise ledger.LedgerError("%s: %s" % (ots_path, e)) from None
    return sorted({a["height"] for a in atts if a["type"] == "bitcoin"})


def main(argv=None):
    p = argparse.ArgumentParser(allow_abbrev=False, description=__doc__.splitlines()[0])
    p.add_argument("action", choices=("stamp", "upgrade"))
    p.add_argument("--seq", type=int, default=None, help="対象の記録（既定は最後の記録）")
    p.add_argument("--ledger", default=DEFAULT_LEDGER)
    p.add_argument("--ots", default=DEFAULT_OTS)
    a = p.parse_args(argv)
    try:
        records = ledger.verify_chain(ledger.read_ledger(a.ledger))
        if not records:
            raise ledger.LedgerError("記録が空")
        seq = a.seq if a.seq is not None else len(records)
        check_ots(a.ots)
        if a.action == "stamp":
            path, err, submitted = stamp_seq(a.ledger, seq, a.ots)
            print("書いた: %s" % os.path.relpath(path, PROJECT))
            print("送った先: %s" % ", ".join(submitted))
            sys.stderr.write(err)
        else:
            path = upgrade_seq(a.ledger, seq, a.ots)
            if path is None:
                print("まだ Bitcoin で確定していない。時間をおいて再実行する。")
                return 1
            print("書いた: %s" % os.path.relpath(path, PROJECT))
    except ledger.LedgerError as e:
        print("失敗: %s" % e, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
