#!/usr/bin/env python3
"""封印の記録の検証（第三者向け）。T-005。

標準ライブラリと git だけを使う。ネットワークは使わない。手順は docs/verify/periods-seal.md。

使い方（プロジェクトのルートで）
    python3 -B src/sealer/verify.py chain              記録の鎖と、種類ごとの版の番号
    python3 -B src/sealer/verify.py anchors            各 seq 自身の .ots の有無、対象のハッシュ、
                                                       証明の状態（Pending か Bitcoin か）
    python3 -B src/sealer/verify.py targets [--rev R]  対象のファイルの sha256 の照合
    python3 -B src/sealer/verify.py periods            区画の境目と deadline_status の照合
    python3 -B src/sealer/verify.py adopted            期限と、採用される版
    python3 -B src/sealer/verify.py all [--rev R]      上のすべて

    どのコマンドにも --btc-header 高さ=ヘッダの16進（80 バイト）を何度でも付けられる。
    sealed/bitcoin-header-<高さ>.hex のファイルも同じように読む。ヘッダは、.ots の中の
    Bitcoin の証明（その高さ）に結び付いていなければ失敗になる。.ots の中に無い高さを
    渡しても失敗になる。ヘッダの値を自由に入れて、確定時刻を作ることはできない。

この検査で確かめないこと
    ヘッダが Bitcoin の本当の鎖の、その高さのブロックであること。出力するブロックの
    ハッシュを、ots verify・自分の Bitcoin のノード・複数のブロックエクスプローラーで
    確かめること。Pending の .ots については、カレンダーが受け付けたことしか示せない。

--rev
    working（既定）  作業ツリーのファイルと照合する。
    auto             各記録について、その記録を最初に含んだコミットを Git の履歴から探し、
                     そのコミットの中のファイルと照合する。
    <コミット>       そのコミットの中のファイルと照合する。

終了コード 0: すべての検査に通った（保留の判定があれば、そのことを出力する）
           1: どこかで失敗した  2: 引数の誤り
"""

import argparse
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import ledger  # noqa: E402

LEDGER_REL = "sealed/ledger.jsonl"
HEADER_FILE_RE = re.compile(r"\Abitcoin-header-(\d+)\.hex\Z")
NOT_CHECKED = ("時刻証明が Bitcoin の本当の鎖に入っているかは、ots verify で確かめる。"
               "この検査では確かめていない。")


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


class State:
    """記録・時刻証明・期限をまとめて読む。"""

    def __init__(self, root, header_args):
        self.root = root
        self.sealed = os.path.join(root, "sealed")
        self.data = ledger.read_ledger(os.path.join(root, LEDGER_REL))
        self.records = ledger.verify_chain(self.data)
        if not self.records:
            raise ledger.LedgerError("記録が空")
        self.anchors = ledger.check_anchors(self.data, self.sealed)
        headers = {}
        if os.path.isdir(self.sealed):
            for name in sorted(os.listdir(self.sealed)):
                m = HEADER_FILE_RE.match(name)
                if m:
                    with open(os.path.join(self.sealed, name), encoding="ascii") as f:
                        headers[int(m.group(1))] = _hex80(f.read().strip())
        for h, hx in header_args or []:
            headers[h] = hx
        self.times, self.detail, unused = ledger.confirmed_times(self.anchors, headers)
        if unused:
            raise ledger.LedgerError("高さ %s のヘッダが渡されたが、その高さの Bitcoin の証明は"
                                     ".ots の中に無い" % ", ".join(map(str, unused)))
        self.deadline, self.deadline_src = self._deadline()

    def file_json(self, record, role):
        t = ledger.output_target(record, role)
        with open(os.path.join(self.root, t["path"]), "rb") as f:
            raw = f.read()
        if ledger.sha256_hex(raw) != t["sha256"]:
            raise ledger.LedgerError("seq %d の %s のファイルが記録と一致しない"
                                     % (record["seq"], role))
        return json.loads(raw.decode("utf-8"))

    def _deadline(self):
        acq = [r for r in self.records if r["kind"] == ledger.ACQUISITION_KIND]
        if not acq:
            return None, None
        first = acq[0]
        return ledger.deadline_from_acquisition(self.file_json(first, "acquisition")), first


def _hex80(text):
    try:
        b = bytes.fromhex(text)
    except ValueError:
        raise ledger.LedgerError("ヘッダが16進でない") from None
    if len(b) != 80:
        raise ledger.LedgerError("ヘッダが 80 バイトでない")
    return b


def _parse_header_arg(text):
    h, sep, hx = text.partition("=")
    if not sep or not h.isdigit():
        raise argparse.ArgumentTypeError("高さ=ヘッダの16進 の形で渡すこと")
    try:
        return int(h), _hex80(hx)
    except ledger.LedgerError as e:
        raise argparse.ArgumentTypeError(str(e)) from None


def print_deadline(st):
    if st.deadline is None:
        print("期限：未確定（手順3の取得の記録 kind=acquisition が、まだ記録に無い）。"
              "期限前かどうかの判定は保留する。")
    else:
        print("期限：%s（seq %d の取得の記録の drand の回の公開時刻）"
              % (st.deadline.isoformat(), st.deadline_src["seq"]))


def cmd_chain(st, _a):
    print("記録: %d 件。鎖は正しい。" % len(st.records))
    counts = {}
    for r in st.records:
        counts[r["kind"]] = counts.get(r["kind"], 0) + 1
        print("  seq %d  %s の %d 件目  recorded_at(申告) %s  先頭 %d 行の sha256 %s"
              % (r["seq"], r["kind"], counts[r["kind"]], r["recorded_at"], r["seq"],
                 ledger.prefix_digest(st.data, r["seq"])))


def cmd_anchors(st, _a):
    for seq, path, digest, atts in st.anchors:
        print("  %s  対象 = 記録の先頭 %d 行の sha256 %s  一致"
              % (os.path.relpath(path, st.root), seq, digest))
        for at in atts:
            if at["type"] == "pending":
                print("      Pending（Bitcoin で未確定）: %s" % at["uri"])
            elif at["type"] == "bitcoin":
                print("      Bitcoin の証明: 高さ %d" % at["height"])
            else:
                print("      知らない種類の証明: %s" % at["tag"])
    for seq, height, when, block in st.detail:
        print("  seq %d: 高さ %d のヘッダと照合した。ヘッダの時刻 %s、ブロックのハッシュ %s"
              "（本当の鎖のその高さのブロックかは、別に確かめる）"
              % (seq, height, when.isoformat(), block))
    for r in st.records:
        if r["seq"] in st.times:
            print("  seq %d: Bitcoin で確定（%s）" % (r["seq"], st.times[r["seq"]].isoformat()))
        else:
            print("  seq %d: Pending。この seq 自身の .ots は Bitcoin で確定していない"
                  "（または照合したヘッダが無い）" % r["seq"])
    print("すべての seq に、その seq 自身の時刻証明があり、対象は記録と一致する。")
    print(NOT_CHECKED)


def cmd_targets(st, a):
    repo = Repo(st.root)
    revs = repo.commit_for_seq(st.data) if a.rev == "auto" else None
    bad = 0
    for r in st.records:
        rev = revs[r["seq"]] if revs else a.rev
        for t in r["targets"]:
            try:
                got = ledger.sha256_hex(repo.read(t["path"], rev))
            except (OSError, ledger.LedgerError):
                got = None
            ok = got == t["sha256"]
            bad += not ok
            print("  seq %d  %-8s %s  %s%s" % (r["seq"], t["role"], t["path"],
                                              "一致" if ok else "不一致",
                                              "" if rev == "working" else "  (コミット %s)" % rev[:12]))
    if bad:
        raise ledger.LedgerError("対象のファイルの sha256 が %d 件一致しない" % bad)
    print("対象のファイルの sha256 はすべて記録と一致する。")


def adopted_triggers(st):
    rec, statuses = ledger.adopted_record(st.records, ledger.TRIGGERS_KIND, st.deadline, st.times)
    values = None
    if rec is not None:
        values = ledger.triggers_values(st.file_json(rec, "triggers"))
    return rec, statuses, values


def cmd_periods(st, _a):
    versions = ledger.records_of_kind(st.records, "periods")
    if not versions:
        raise ledger.LedgerError("periods の記録が無い")
    for _v, r in ledger.records_of_kind(st.records, ledger.TRIGGERS_KIND):
        ledger.triggers_values(st.file_json(r, "triggers"))
    trig_rec, _s, trig_values = adopted_triggers(st)
    first = st.file_json(versions[0][1], "output")
    problems, held = [], []
    if first.get("deadline_status") is not None:
        problems.append("最初の版の deadline_status が null でない")
    for v, r in versions:
        out = st.file_json(r, "output")
        for p in ledger.check_blocks(first, out):
            problems.append("%d 件目: %s" % (v, p))
        expected, probs = ledger.judge_deadline_status(out, st.deadline is not None, trig_values)
        problems += ["%d 件目: %s" % (v, p) for p in probs]
        blocks = ledger.blocks_of(out)
        print("  periods の %d 件目（seq %d）: %s" % (v, r["seq"], ", ".join(
            "%s %s〜%s" % (n, s, e) for n, (s, e) in sorted(blocks.items(), key=lambda x: x[1]))))
        if expected is None:
            print("      きっかけの値なし。deadline_status は null（正しい）")
        elif expected == "held":
            held.append(v)
            print("      deadline_status の申告 %s：期限が未確定のため照合を保留"
                  % out.get("deadline_status"))
        else:
            print("      deadline_status の申告 %s、記録から決まる値 %s（照合に使った "
                  "periods-triggers: %s）" % (out.get("deadline_status"), expected,
                                              "seq %d" % trig_rec["seq"] if trig_rec else "なし"))
    if problems:
        raise ledger.LedgerError("; ".join(problems))
    print("periods のすべての版の区画の境目は、最初の版と一致する。")
    if held:
        print("保留: periods の %s 件目の deadline_status の照合" % ", ".join(map(str, held)))


def cmd_adopted(st, _a):
    print_deadline(st)
    for kind in ("periods", ledger.TRIGGERS_KIND):
        rec, statuses = ledger.adopted_record(st.records, kind, st.deadline, st.times)
        if not statuses:
            print("  %s: 記録なし" % kind)
            continue
        for seq, s in sorted(statuses.items()):
            extra = ""
            if s == ledger.HELD:
                extra = ("。この seq 自身の .ots は Bitcoin で確定（%s）" % st.times[seq].isoformat()
                         if seq in st.times else "。この seq 自身の .ots は Pending")
            print("  %s seq %d（%d 件目）: %s%s" % (kind, seq, ledger.version_of(st.records, seq),
                                                  ledger.STATUS_TEXT[s], extra))
        if st.deadline is None:
            print("  %s: 採用される版は保留（期限が未確定）" % kind)
        elif rec is None:
            print("  %s: 期限前と示せる記録が無い。採用される版は無い" % kind)
        else:
            print("  %s: 採用 = seq %d（%d 件目、期限前の最後の追記）"
                  % (kind, rec["seq"], ledger.version_of(st.records, rec["seq"])))


def cmd_all(st, a):
    cmd_chain(st, a)
    cmd_anchors(st, a)
    cmd_targets(st, a)
    cmd_periods(st, a)
    cmd_adopted(st, a)
    print("すべての検査に通った。" + ("期限が未確定のため、採用の判定は保留。"
                                      if st.deadline is None else ""))
    print(NOT_CHECKED)


def main(argv=None):
    p = argparse.ArgumentParser(allow_abbrev=False, description=__doc__.splitlines()[0])
    p.add_argument("--root", default=os.getcwd())
    sub = p.add_subparsers(dest="cmd", required=True)
    parsers = {}
    for name in ("chain", "anchors", "targets", "periods", "adopted", "all"):
        s = sub.add_parser(name, allow_abbrev=False)
        s.add_argument("--btc-header", type=_parse_header_arg, action="append",
                       help="高さ=80 バイトのヘッダの16進。.ots の中の Bitcoin の証明と照合する")
        parsers[name] = s
    for name in ("targets", "all"):
        parsers[name].add_argument("--rev", default="working")
    a = p.parse_args(argv)
    fn = {"chain": cmd_chain, "anchors": cmd_anchors, "targets": cmd_targets,
          "periods": cmd_periods, "adopted": cmd_adopted, "all": cmd_all}[a.cmd]
    try:
        st = State(os.path.abspath(a.root), a.btc_header)
        fn(st, a)
    except ledger.LedgerError as e:
        print("失敗: %s" % e, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
