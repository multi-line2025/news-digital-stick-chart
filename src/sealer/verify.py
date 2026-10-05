#!/usr/bin/env python3
"""封印の記録の検証（第三者向け）。T-005。

標準ライブラリと git だけを使う。ネットワークは使わない。手順は docs/verify/periods-seal.md。

使い方（プロジェクトのルートで）
    python3 -B src/sealer/verify.py chain              記録の鎖と、種類ごとの版の番号
    python3 -B src/sealer/verify.py anchors            .ots の対象と、記録の先頭 N 行の照合
    python3 -B src/sealer/verify.py targets [--rev R]  対象のファイルの sha256 の照合
    python3 -B src/sealer/verify.py periods            periods の後の版の区画の境目の照合
    python3 -B src/sealer/verify.py adopted --deadline T --anchor-time SEQ=T ...
                                                       期限前の最後の追記（採用される版）
    python3 -B src/sealer/verify.py all [--rev R]      chain・anchors・targets・periods

--rev
    working（既定）  作業ツリーのファイルと照合する。
    auto             各記録について、その記録を最初に含んだコミットを Git の履歴から探し、
                     そのコミットの中のファイルと照合する。対象のファイルが後で
                     書き換えられても、封印した時点の中身で確かめられる。
    <コミット>       そのコミットの中のファイルと照合する。

終了コード 0: すべて通った  1: どこかで失敗した  2: 引数の誤り
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

LEDGER_REL = "sealed/ledger.jsonl"


class Repo:
    def __init__(self, root):
        self.root = root

    def git(self, *args):
        r = subprocess.run(["git", "-C", self.root] + list(args), capture_output=True)
        if r.returncode != 0:
            raise ledger.LedgerError("git %s が失敗した" % " ".join(args[:2]))
        return r.stdout

    def read(self, rel, rev):
        if rev == "working":
            with open(os.path.join(self.root, rel), "rb") as f:
                return f.read()
        return self.git("show", "%s:%s" % (rev, rel))

    def commit_for_seq(self, data):
        """{seq: その記録を最初に含んだコミット}。履歴の記録が今の記録の先頭と食い違えば失敗。"""
        out = self.git("rev-list", "--reverse", "HEAD", "--", LEDGER_REL).decode().split()
        lines = ledger.split_lines(data)
        found = {}
        for c in out:
            try:
                old = self.git("show", "%s:%s" % (c, LEDGER_REL))
            except ledger.LedgerError:
                continue
            n = len(ledger.split_lines(old))
            if n > len(lines) or (n and ledger.prefix_bytes(data, n) != old):
                raise ledger.LedgerError("コミット %s の記録が、今の記録の先頭と一致しない"
                                         "（履歴の中で記録が書き換えられた）" % c[:12])
            for s in range(1, n + 1):
                found.setdefault(s, c)
        missing = [s for s in range(1, len(lines) + 1) if s not in found]
        if missing:
            raise ledger.LedgerError("seq %s の記録を含むコミットが無い" % missing)
        return found


def load(root):
    data = ledger.read_ledger(os.path.join(root, LEDGER_REL))
    return data, ledger.verify_chain(data)


def cmd_chain(root, _a):
    data, records = load(root)
    print("記録: %d 件。鎖は正しい。" % len(records))
    counts = {}
    for r in records:
        counts[r["kind"]] = counts.get(r["kind"], 0) + 1
        print("  seq %d  %s の %d 件目  recorded_at(申告) %s  先頭 %d 行の sha256 %s"
              % (r["seq"], r["kind"], counts[r["kind"]], r["recorded_at"], r["seq"],
                 ledger.prefix_digest(data, r["seq"])))


def cmd_anchors(root, _a):
    data, _records = load(root)
    for seq, path, digest in ledger.check_anchors(data, os.path.join(root, "sealed")):
        print("  %s  対象 = 記録の先頭 %d 行の sha256 %s  一致"
              % (os.path.relpath(path, root), seq, digest))
    print("時刻証明の対象は記録と一致する（証明そのものの確認は ots verify で行う）。")


def cmd_targets(root, a):
    data, records = load(root)
    repo = Repo(root)
    revs = repo.commit_for_seq(data) if a.rev == "auto" else None
    bad = 0
    for r in records:
        rev = revs[r["seq"]] if revs else a.rev
        for t in r["targets"]:
            try:
                got = ledger.sha256_hex(repo.read(t["path"], rev))
            except (OSError, ledger.LedgerError):
                got = None
            ok = got == t["sha256"]
            bad += not ok
            print("  seq %d  %-6s %s  %s%s" % (r["seq"], t["role"], t["path"],
                                              "一致" if ok else "不一致",
                                              "" if rev == "working" else "  (コミット %s)" % rev[:12]))
    if bad:
        raise ledger.LedgerError("対象のファイルの sha256 が %d 件一致しない" % bad)
    print("対象のファイルの sha256 はすべて記録と一致する。")


def cmd_periods(root, _a):
    _data, records = load(root)
    versions = ledger.records_of_kind(records, "periods")
    if not versions:
        raise ledger.LedgerError("periods の記録が無い")
    outputs = []
    for v, r in versions:
        t = ledger.output_target(r)
        with open(os.path.join(root, t["path"]), "rb") as f:
            raw = f.read()
        if ledger.sha256_hex(raw) != t["sha256"]:
            raise ledger.LedgerError("periods の %d 件目の出力が記録と一致しない" % v)
        outputs.append((v, r, json.loads(raw.decode("utf-8"))))
    _v1, _r1, first = outputs[0]
    problems = []
    if first.get("deadline_status") is not None:
        problems.append("最初の版の deadline_status が null でない")
    for v, r, out in outputs:
        for p in ledger.check_blocks(first, out):
            problems.append("%d 件目: %s" % (v, p))
        if v > 1:
            for p in ledger.check_deadline_status(out, None):
                problems.append("%d 件目: %s" % (v, p))
        blocks = ledger.blocks_of(out)
        print("  periods の %d 件目（seq %d）: %s" % (v, r["seq"], ", ".join(
            "%s %s〜%s" % (n, s, e) for n, (s, e) in sorted(blocks.items(), key=lambda x: x[1]))))
    if problems:
        raise ledger.LedgerError("; ".join(problems))
    print("periods のすべての版の区画の境目は、最初の版と一致する。")


def _parse_utc(text):
    dt = datetime.datetime.fromisoformat(text.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise argparse.ArgumentTypeError("UTC であることを Z か +00:00 で示すこと: %s" % text)
    return dt.astimezone(datetime.timezone.utc)


def _parse_anchor(text):
    seq, _, t = text.partition("=")
    return int(seq), _parse_utc(t)


def cmd_adopted(root, a):
    _data, records = load(root)
    times = dict(a.anchor_time or [])
    margin = datetime.timedelta(hours=a.margin_hours)
    rec = ledger.adopted_record(records, a.kind, a.deadline, times, margin)
    if rec is None:
        raise ledger.LedgerError("期限前と時刻証明で示せる %s の記録が無い" % a.kind)
    v = ledger.version_of(records, rec["seq"])
    print("採用: seq %d（%s の %d 件目）。時刻証明による存在の上限 %s、期限 %s"
          % (rec["seq"], a.kind, v, ledger.proven_time_of(rec["seq"], times).isoformat(),
             a.deadline.isoformat()))
    if a.kind == "periods":
        with open(os.path.join(root, ledger.output_target(rec)["path"]), "rb") as f:
            out = json.loads(f.read().decode("utf-8"))
        problems = ledger.check_deadline_status(out, True)
        if problems:
            raise ledger.LedgerError("; ".join(problems))


def cmd_all(root, a):
    cmd_chain(root, a)
    cmd_anchors(root, a)
    cmd_targets(root, a)
    cmd_periods(root, a)
    print("すべての検査に通った。")


def main(argv=None):
    p = argparse.ArgumentParser(allow_abbrev=False, description=__doc__.splitlines()[0])
    p.add_argument("--root", default=os.getcwd())
    sub = p.add_subparsers(dest="cmd", required=True)
    for name in ("chain", "anchors", "periods"):
        sub.add_parser(name, allow_abbrev=False)
    for name in ("targets", "all"):
        s = sub.add_parser(name, allow_abbrev=False)
        s.add_argument("--rev", default="working")
    s = sub.add_parser("adopted", allow_abbrev=False)
    s.add_argument("--kind", default="periods")
    s.add_argument("--deadline", type=_parse_utc, required=True)
    s.add_argument("--anchor-time", type=_parse_anchor, action="append",
                   help="SEQ=時刻。ots verify が示した Bitcoin の確定の時刻（UTC）")
    s.add_argument("--margin-hours", type=float, default=3.0)
    a = p.parse_args(argv)
    fn = {"chain": cmd_chain, "anchors": cmd_anchors, "targets": cmd_targets,
          "periods": cmd_periods, "adopted": cmd_adopted, "all": cmd_all}[a.cmd]
    try:
        fn(os.path.abspath(a.root), a)
    except ledger.LedgerError as e:
        print("失敗: %s" % e, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
