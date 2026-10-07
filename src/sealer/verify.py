#!/usr/bin/env python3
"""封印の記録の検証（第三者向け）。T-005、T-007、T-008、T-013、T-014、T-017。

標準ライブラリと git だけを使う。ネットワークは使わない。手順は docs/verify/periods-seal.md。

使い方（プロジェクトのルートで）
    python3 -B src/sealer/verify.py chain              記録の鎖と、種類ごとの版の番号
    python3 -B src/sealer/verify.py anchors            各 seq 自身の .ots の有無、対象のハッシュ、
                                                       証明の状態（Pending か Bitcoin か）、
                                                       Pending の宛先が許可した 4 つか
    python3 -B src/sealer/verify.py targets [--rev R]  対象のファイルの sha256 の照合
    python3 -B src/sealer/verify.py access             threshold-access の記録の ledger_head・drand の回・
                                                       block_start、最初の threshold-access より前に
                                                       candidates があること（T-017）
    python3 -B src/sealer/verify.py acquisition        acquisition-start の ledger_head と drand の回、
                                                       acquisition-result との対応、
                                                       start の前に candidates があること（T-014）
    python3 -B src/sealer/verify.py method             method-access（手順4の開始）の ledger_head・
                                                       drand の回・区画、その前に candidates と
                                                       acquisition-result があること（T-014）
    python3 -B src/sealer/verify.py stats-order        統計係の順番1・順番1b（stats-order1・stats-order1b。T-037）の
                                                       中身・ledger_head・数（順番1 は 1 件）・位置（method-access より
                                                       前、gkg-run-start の前に順番1b）と、区分表の取得との前後
                                                       （git の履歴：マニフェストに行が入った commit の親に順番1）
    python3 -B src/sealer/verify.py gkg-runs           GKG の取得の run の開始（gkg-run-start。T-031）の
                                                       ledger_head・drand・中身・順序。試しの run の回数と、
                                                       各 run の run_id・code_sha256・日を並べる
    python3 -B src/sealer/verify.py periods            区画の境目と deadline_status の照合
    python3 -B src/sealer/verify.py candidates         閾値と判定期間の候補の記録の形・出力の形、
                                                       最初の acquisition-start より前にあること（T-013）、
                                                       J とエンバーゴ（T-017、T-023）：J を持つ
                                                       periods-triggers が最初の method-access より前に
                                                       だけあること、採用される periods の embargo_days
                                                       = max(1 件目の embargo_days, J の最大)、採用される
                                                       periods-triggers の J（null でなければ）= J の最大
    python3 -B src/sealer/verify.py adopted            採用される版（鎖の順番で決める）
    python3 -B src/sealer/verify.py all [--rev R]      上のすべて

採用の規則（T-007、T-008）
    最初の kind=threshold-access の記録より seq が小さい記録のうち、その種類（periods、
    periods-triggers、candidates）の最後のものを採用する。threshold-access の記録が無いうちは保留。
    acquisition-start・acquisition-result・method-access・gkg-run-start・stats-order1・stats-order1b は
    区切りに使わない。
    時刻（Bitcoin の確定時刻、drand の回の公開時刻）と、Pending かどうかは使わない。

drand の照合の幅（T-008）
    drand の回の公開時刻 T と、その記録自身の .ots の確定時刻（ヘッダの時刻）Tq を比べ、
    T < Tq + 2 時間（ledger.DRAND_HEADER_SLACK）なら通す。根拠は ledger.py の注記。

どのコマンドにも付けられるもの（何度でも）
    --btc-header 高さ=ヘッダの16進（80 バイト）
        .ots の中の Bitcoin の証明（その高さ）と照合する。sealed/bitcoin-header-<高さ>.hex と
        --ots-dir の中の同じ名前のファイルも読む。.ots の中に無い高さを渡すと失敗になる。
    --ots-dir ディレクトリ
        第三者が自分で upgrade した .ots（名前は ledger.jsonl.seqNNNNNN.ots か
        ledger.jsonl.seqNNNNNN.bitcoin.ots）を置いたディレクトリ。sealed/ の .ots と同じ検査
        （対象のハッシュ、Pending の宛先）をして読み足す。採用の判定は変わらない。

この検査で確かめないこと
    - ヘッダが Bitcoin の本当の鎖の、その高さのブロックであること。出力するブロックの
      ハッシュを、ots verify・自分の Bitcoin のノード・複数のブロックエクスプローラーで確かめる。
    - drand の署名（BLS）。drand の公開の API か drand の道具で確かめる。

--rev
    working（既定）  作業ツリーのファイルと照合する。
    auto             各記録について、その記録を最初に含んだコミットを Git の履歴から探し、
                     そのコミットの中のファイルと照合する。
    <コミット>       そのコミットの中のファイルと照合する。
    auto か <コミット> のときは、そのコミットの sealed/ の時刻証明（.ots・.bitcoin.ots）と
    ヘッダが、作業ツリーにも同じ中身であることも確かめる（auto なら HEAD の履歴で sealed/ に
    足されたことのあるもの全部。マージコミットで足したものも含む）。外していれば失敗する（T-023）。
    HEAD の履歴に、時刻証明かヘッダを消したコミット（マージを含む）があれば失敗する（T-027）。

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
# --rev で選んだコミットの sealed/ にあれば、作業ツリーにも同じ中身で無ければならないファイル
# （T-023。T-017 の再提出1回目の監査 軽1）。時刻証明（.ots と .bitcoin.ots）とヘッダ。
REV_ANCHOR_RE = re.compile(r"\Asealed/(ledger\.jsonl\.seq\d{6}(\.bitcoin)?\.ots"
                           r"|bitcoin-header-\d+\.hex)\Z")
NOT_CHECKED = ("この検査で確かめていないこと：(1) .ots の Bitcoin の証明に照合したヘッダが、"
               "Bitcoin の本当の鎖にあること（ots verify や自分のノードで確かめる）。"
               "(2) " + ledger.DRAND_NOT_VERIFIED)
ADOPT_CONDITION = ("条件：この記録の系列が公開されたものと同じであること。また、各 seq が確定時刻に"
                   "存在したという時刻の主張は、照合したヘッダが Bitcoin の本当の鎖にある場合に"
                   "限る。ヘッダが本当の鎖にあることは、この検査では確かめていない")


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

    def _anchor_log(self, diff_filter):
        """[(パス, コミット)]。HEAD の履歴で、sealed/ の時刻証明・ヘッダに diff_filter（A か D）の
        変更をしたコミット。T-027（T-023 の監査 軽A）：-m でマージコミットの差分も、親ごとに出す
        （git log は既定ではマージの差分を出さないので、マージで足したものや消したものが漏れていた）。
        --no-renames で、名前の変更も「消した」と「足した」に分けて出す。"""
        text = self.git("log", "-m", "--no-renames", "--diff-filter=" + diff_filter,
                        "--format=@%H", "--name-only", "HEAD", "--", "sealed/").decode("utf-8")
        out, commit = [], None
        for line in text.splitlines():
            if line.startswith("@"):
                commit = line[1:]
            elif line and REV_ANCHOR_RE.match(line):
                out.append((line, commit))
        return sorted(set(out))

    def anchor_files(self, rev):
        """[(パス, コミット)]。rev のコミットの sealed/ にある時刻証明とヘッダ。T-023、T-027。

        rev が auto なら、HEAD の履歴の中で sealed/ に足されたことのある、すべての時刻証明と
        ヘッダ（足したコミットの中身と比べる）。マージコミットで足したものも含む（T-027）。
        それ以外なら、そのコミットの sealed/ にあるもの。
        """
        if rev == "auto":
            return self._anchor_log("A")
        text = self.git("ls-tree", "-r", "--name-only", rev, "--", "sealed/").decode("utf-8")
        return sorted({(p, rev) for p in text.splitlines() if REV_ANCHOR_RE.match(p)})

    def removed_anchor_files(self):
        """[(パス, コミット)]。HEAD の履歴で、sealed/ の時刻証明かヘッダを消したコミット（マージを
        含む。名前の変更も含む）。T-027。時刻証明とヘッダは追記のみなので、一つでもあれば失敗にする。"""
        return self._anchor_log("D")


def check_rev_anchor_files(repo, rev):
    """--rev で選んだコミットの sealed/ の時刻証明（.ots・.bitcoin.ots）とヘッダが、作業ツリーにも
    同じ中身であることを確かめる。T-023（T-017 の再提出1回目の監査 軽1）。

    検証の残りは作業ツリーの sealed/ を読むので、コミットにある .bitcoin.ots とヘッダを
    作業ツリーからまとめて外すと、確定した seq が「Pending」のまま検証が通ってしまう。それを止める。
    作業ツリーのファイルがシンボリックリンクなら、それも失敗にする。
    T-027：HEAD の履歴に、時刻証明かヘッダを消したコミット（マージを含む）が一つでもあれば失敗。
    返り値: 照合した件数。
    """
    if rev == "working":
        return 0
    removed = repo.removed_anchor_files()
    if removed:
        raise ledger.LedgerError("sealed/ の時刻証明・ヘッダを消したコミットが履歴にある（追記のみの"
                                 "決まりに反する）: %s" % "; ".join(
                                     "%s（コミット %s）" % (rel, c[:12]) for rel, c in removed))
    files = repo.anchor_files(rev)
    bad = []
    for rel, commit in files:
        path = os.path.join(repo.root, rel)
        if os.path.islink(path) or not os.path.isfile(path):
            bad.append("%s（コミット %s にあるが、作業ツリーに無い）" % (rel, commit[:12]))
            continue
        with open(path, "rb") as f:
            got = f.read()
        if got != repo.git("show", "%s:%s" % (commit, rel)):
            bad.append("%s（作業ツリーの中身が、コミット %s の中身と違う）" % (rel, commit[:12]))
    if bad:
        raise ledger.LedgerError("--rev %s で選んだコミットの sealed/ の時刻証明・ヘッダが、作業ツリーと"
                                 "一致しない: %s" % (rev, "; ".join(bad)))
    return len(files)


class State:
    """記録と時刻証明をまとめて読む。"""

    def __init__(self, root, header_args, ots_dirs=()):
        self.root = root
        ledger.check_sealed_inside(root)     # T-017：sealed/ が別の場所を指していないこと
        self.sealed = os.path.join(root, "sealed")
        self.ots_dirs = [os.path.abspath(d) for d in ots_dirs or ()]
        self.data = ledger.read_ledger(os.path.join(root, LEDGER_REL))
        self.records = ledger.verify_chain(self.data)
        if not self.records:
            raise ledger.LedgerError("記録が空")
        self.anchors = ledger.check_anchors(self.data, self.sealed, self.ots_dirs)
        headers = {}
        for d in [self.sealed] + self.ots_dirs:
            if not os.path.isdir(d):
                continue
            for name in sorted(os.listdir(d)):
                m = HEADER_FILE_RE.match(name)
                if m:
                    with open(os.path.join(d, name), encoding="ascii") as f:
                        headers[int(m.group(1))] = _hex80(f.read().strip())
        for h, hx in header_args or []:
            headers[h] = hx
        # T-017（差し戻し1回目の軽2）：.ots に Bitcoin の証明がある高さは、すべてヘッダと照合する。
        # ヘッダが無い高さがあれば失敗にする。置いたヘッダを外して、確定時刻を黙って変えたり、
        # 「保留」のまま通したりできないようにするため。
        need = sorted({a["height"] for _s, _p, _d, atts in self.anchors for a in atts
                       if a["type"] == "bitcoin"})
        missing = [h for h in need if h not in headers]
        if missing:
            raise ledger.LedgerError("高さ %s の Bitcoin の証明が .ots の中にあるが、そのヘッダが無い"
                                     "（sealed/bitcoin-header-<高さ>.hex、--ots-dir の中の同じ名前の"
                                     "ファイル、または --btc-header で渡す）" % ", ".join(map(str, missing)))
        self.times, self.detail, unused = ledger.confirmed_times(self.anchors, headers)
        if unused:
            raise ledger.LedgerError("高さ %s のヘッダが渡されたが、その高さの Bitcoin の証明は"
                                     ".ots の中に無い" % ", ".join(map(str, unused)))
        self.cut = ledger.first_threshold_access(self.records)

    def file_json(self, record, role):
        return ledger.read_target_json(self.root, record, role)

    def rel(self, path):
        return os.path.relpath(path, self.root) if path.startswith(self.root + os.sep) else path


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


def cmd_chain(st, _a):
    print("記録: %d 件。鎖は正しい。" % len(st.records))
    counts = {}
    for r in st.records:
        counts[r["kind"]] = counts.get(r["kind"], 0) + 1
        print("  seq %d  %s の %d 件目  recorded_at(申告) %s  先頭 %d 行の sha256 %s"
              % (r["seq"], r["kind"], counts[r["kind"]], r["recorded_at"], r["seq"],
                 ledger.prefix_digest(st.data, r["seq"])))


def cmd_anchors(st, _a):
    print("時刻証明（.ots）が示すのは「記録の先頭からその seq までが、確定した時刻に存在した」"
          "ことだけ。採用の判定には使わない。")
    for seq, path, digest, atts in st.anchors:
        print("  %s  対象 = 記録の先頭 %d 行の sha256 %s  一致" % (st.rel(path), seq, digest))
        for at in atts:
            if at["type"] == "pending":
                print("      Pending（Bitcoin で未確定）: %s（許可した宛先）" % at["uri"])
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
            print("  seq %d: Bitcoin で確定（ヘッダの時刻 %s。ヘッダが本当の鎖にあることは"
                  "確かめていない）" % (r["seq"], st.times[r["seq"]].isoformat()))
        else:
            print("  seq %d: Pending。この seq の .ots は Bitcoin で確定していない"
                  "（または照合したヘッダが無い）" % r["seq"])
    print("すべての seq に、その seq 自身の時刻証明があり、対象は記録と一致する。"
          "Pending の宛先は、すべて許可した 4 つのカレンダーのどれか。")


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
    n = check_rev_anchor_files(repo, a.rev)
    if a.rev != "working":
        print("--rev %s で選んだコミットの sealed/ にある時刻証明（.ots・.bitcoin.ots）とヘッダ %d 件は、"
              "作業ツリーにも同じ中身である（T-023）。" % (a.rev, n))


def adopted_triggers(st):
    rec, _cand, cut = ledger.adoption(st.records, ledger.TRIGGERS_KIND)
    values = None
    if rec is not None:
        values = ledger.triggers_values(st.file_json(rec, "triggers"))
    return rec, values, cut is not None


def _print_drand(r, t, state, own):
    if state == "ok":
        print("      drand の回の公開時刻 %s は、この記録自身の .ots の確定時刻（ヘッダの時刻）%s に"
              "幅 %s を足した時刻より前（この記録は、ヘッダの時刻 + 幅 より前に存在した。確定時刻の"
              "側は、ヘッダが本当の鎖にあることを確かめた場合に限る。この記録が drand の回の公開"
              "時刻より後に作られたことは、drand の署名（BLS）を確かめた場合に限る。この検査では"
              "署名を確かめていない）" % (t.isoformat(), own.isoformat(), ledger.DRAND_HEADER_SLACK))
    else:
        print("      drand の回の公開時刻 %s。この記録自身の .ots が Pending のため、"
              "確定時刻との照合は保留" % t.isoformat())


def first_threshold_block_start(st):
    return ledger.first_threshold_block_start(st.root, st.records)


def cmd_access(st, _a):
    recs = [r for r in st.records if r["kind"] == ledger.THRESHOLD_ACCESS_KIND]
    if not recs:
        print("threshold-access の記録：なし（照合するものが無い）")
    else:
        want_start = first_threshold_block_start(st)
    for r in recs:
        doc = st.file_json(r, ledger.THRESHOLD_ACCESS_KIND)
        own = st.times.get(r["seq"])
        t, state = ledger.check_drand_record(st.data, r, doc, own)
        got = ledger.threshold_access_block_start(doc)
        if got != want_start:
            raise ledger.LedgerError("seq %d の threshold-access の block_start %s が、periods の"
                                     " 1 件目の閾値の期間の始まり %s と一致しない"
                                     % (r["seq"], got, want_start))
        print("  threshold-access seq %d: ledger_head は直前の記録（先頭 %d 行）のハッシュと一致。"
              "block_start %s は periods の 1 件目の閾値の期間の始まりと一致"
              % (r["seq"], r["seq"] - 1, got))
        _print_drand(r, t, state, own)
    if recs:
        # T-017（T-014 の監査 軽2）：関門（require_threshold_access）と同じ候補の順序の照合。
        # 最初の threshold-access より前に candidates が 1 件以上あり、すべての candidates が
        # 最初の acquisition-start より前にあり、形の照合に通ること。
        ledger.check_candidates_ready(st.root, st.records, recs[0]["seq"])
        print("  最初の threshold-access（seq %d）より前に candidates の記録がある"
              % recs[0]["seq"])
        print(ledger.DRAND_NOT_VERIFIED)


def cmd_acquisition(st, _a):
    starts = [r for r in st.records if r["kind"] == ledger.ACQ_START_KIND]
    results = [r for r in st.records if r["kind"] == ledger.ACQ_RESULT_KIND]
    if not starts and not results:
        print("acquisition-start・acquisition-result の記録：なし（照合するものが無い）")
    for r in starts:
        doc = st.file_json(r, ledger.ACQ_START_KIND)
        own = st.times.get(r["seq"])
        t, state = ledger.check_drand_record(st.data, r, doc, own)
        code_path, code_sha = ledger.acquisition_start_fields(doc)
        print("  acquisition-start seq %d: ledger_head は直前の記録（先頭 %d 行）のハッシュと一致。"
              "取得のコード %s の sha256 %s" % (r["seq"], r["seq"] - 1, code_path, code_sha))
        _print_drand(r, t, state, own)
    refs = {}
    for r in results:
        start_seq, kept = ledger.acquisition_result_fields(
            r, st.file_json(r, ledger.ACQ_RESULT_KIND))
        refs[r["seq"]] = start_seq
    pairs = ledger.check_acquisition_pairs(st.records, refs)
    for sseq, rseq in sorted(pairs.items()):
        if rseq is None:
            print("  acquisition-start seq %d: 対応する acquisition-result は無い"
                  "（取得の途中か、失敗した）" % sseq)
        else:
            print("  acquisition-start seq %d ← acquisition-result seq %d（start が実在し、"
                  "result が後にあり、result は一つだけ）" % (sseq, rseq))
    cut = ledger.check_candidates_order(st.records)
    if cut is not None:
        print("  最初の acquisition-start（seq %d）より前に candidates の記録がある" % cut["seq"])
    if starts:
        print(ledger.DRAND_NOT_VERIFIED)


def cmd_stats_order(st, _a):
    """統計係の順番1・順番1b の記録の照合と一覧。T-037（差し戻し1回目で改めた）。"""
    got = ledger.check_stats_order(st.records, st.file_json)
    if not got["order1"] and not got["order1b"]:
        print("stats-order1・stats-order1b の記録：なし")
    for r in got["order1"]:
        doc = st.file_json(r, ledger.ORDER1_KIND)
        ledger.check_ledger_head(st.data, r, doc)
        targets = ledger.check_order1_doc(r, doc)
        print("  stats-order1 seq %d（順番1）: HEAD %s、%s、対象 %d 件（名前は決まった 10 件）、承認 %s、"
              "tests/stats %s、対象だけの写し %s"
              % (r["seq"], doc["head"], doc["python"]["version"], len(targets),
                 "・".join(a["item"] for a in doc["approvals"]), doc["checks"]["stats_tests"],
                 doc["checks"]["targets_only_copy"]["tests"]))
        for name in ledger.ORDER1_TARGET_NAMES:
            print("      %s  %s" % (targets[name], name))
    for r in got["order1b"]:
        doc = st.file_json(r, ledger.ORDER1B_KIND)
        ledger.check_ledger_head(st.data, r, doc)
        files = ledger.check_order1b_doc(r, doc)
        c = doc["counting"]
        print("  stats-order1b seq %d（順番1b）: HEAD %s、候補 %s、基準の案 %s、正式な数え方 %s（%s）、"
              "counting.py の出力 %s、順番1 の参照 %s"
              % (r["seq"], doc["head"], ",".join(c["candidate_ids"]), ",".join(c["criteria_ids"]),
                 c["official_candidate"], c["official_status"], c["output_sha256"],
                 "無し" if doc["order1_ref"] is None else "seq %d" % doc["order1_ref"]["seq"]))
        for path in sorted(files):
            print("      %s  %s" % (files[path], path))
    o1 = ledger.first_order1(st.records)
    print("除外の規則の kind（%s）の記録：%s（1 件だけ）。順番1・1b は最初の method-access より前、"
          "最初の gkg-run-start の前に順番1b。" % (ledger.ORDER1_KIND, "無し" if o1 is None else "seq %d" % o1["seq"]))
    # 区分表の取得は ledger に書かれないので、git の履歴とマニフェストで照らす（差し戻し1回目 中1）
    repo = Repo(st.root)
    try:
        repo.git("rev-parse", "--git-dir")
    except ledger.LedgerError:
        print("git の履歴が無いので、区分表の取得との前後は照合していない（--rev auto には git の履歴が要る）")
        return
    n = ledger.check_order1_before_themes(st.records, repo.git)
    mpath = os.path.join(st.root, ledger.THEMES_MANIFEST)
    body = None
    if os.path.isfile(mpath) and not os.path.islink(mpath):
        with open(mpath, "rb") as f:
            body = f.read()
    rows = ledger.check_themes_manifest_refs(st.records, body)
    print("区分表の取得（%s）：行のある commit %d 件。どれも、親の sealed/ledger.jsonl に stats-order1 の行がある。"
          "作業ツリーのマニフェストの %d 行の exclusion_rule_seq と sha256 は stats-order1 の記録と一致する。"
          % (ledger.THEMES_MANIFEST, n, rows))


def cmd_method(st, _a):
    """手順4の開始（kind が method-access）の照合。T-014。"""
    recs = ledger.check_method_access_order(st.records)
    if not recs:
        print("method-access の記録：なし（照合するものが無い）")
        return
    for r in recs:
        doc = st.file_json(r, ledger.METHOD_ACCESS_KIND)
        own = st.times.get(r["seq"])
        t, state = ledger.check_drand_record(st.data, r, doc, own)
        start, end = ledger.check_method_access_doc(st.root, st.records, r, doc)
        print("  method-access seq %d: ledger_head は直前の記録（先頭 %d 行）のハッシュと一致。"
              "区画 %s〜%s は periods の 1 件目の method の区画と一致。前に candidates と "
              "acquisition-result の記録がある" % (r["seq"], r["seq"] - 1, start, end))
        _print_drand(r, t, state, own)
    print(ledger.DRAND_NOT_VERIFIED)


def cmd_gkg_runs(st, _a):
    """GKG の取得の run の開始（kind が gkg-run-start）の照合と一覧。T-031。"""
    runs = ledger.check_gkg_runs(st.records, st.file_json)
    if not runs:
        print("gkg-run-start の記録：なし（照合するものが無い）")
        return
    trials = [(r, d) for r, d in runs if d["mode"] == "trial"]
    officials = [(r, d) for r, d in runs if d["mode"] == "official"]
    print("GKG の取得の run の開始（gkg-run-start）：試しの run %d 回、正式な run %d 回"
          "（記録の件数から数える）" % (len(trials), len(officials)))
    for r, d in runs:
        own = st.times.get(r["seq"])
        t, state = ledger.check_drand_record(st.data, r, d, own)
        print("  seq %d  %s  run_id %s  code_sha256 %s（%s）  日 %s  一覧 %s  method-access seq %d  "
              "除外の規則の記録 seq %d"
              % (r["seq"], "試しの run（trial）" if d["mode"] == "trial" else "正式な run（official）",
                 d["run_id"], d["code_sha256"], d["code_path"],
                 "、".join(d["trial_days"]) if d["trial_days"] else "（区画の全体）",
                 d["filelist_sha256"], d["method_access_seq"], d["exclusion_rule_seq"]))
        _print_drand(r, t, state, own)
    print("順序：どの gkg-run-start も最初の method-access より後。official は %s。trial は official "
          "より前だけ。除外の規則の記録の kind は、まだ照合しない（kind が決まっていない）。"
          % ("1 件" if officials else "まだ無い"))
    print(ledger.DRAND_NOT_VERIFIED)


def cmd_periods(st, _a):
    versions = ledger.records_of_kind(st.records, ledger.PERIODS_KIND)
    if not versions:
        raise ledger.LedgerError("periods の記録が無い")
    for _v, r in ledger.records_of_kind(st.records, ledger.TRIGGERS_KIND):
        ledger.triggers_values(st.file_json(r, "triggers"))
    trig_rec, trig_values, decided = adopted_triggers(st)
    first = st.file_json(versions[0][1], "output")
    problems, held = [], []
    if first.get("deadline_status") is not None:
        problems.append("最初の版の deadline_status が null でない")
    for v, r in versions:
        out = st.file_json(r, "output")
        for p in ledger.check_blocks(first, out):
            problems.append("%d 件目: %s" % (v, p))
        expected, probs = ledger.judge_deadline_status(out, decided, trig_values)
        problems += ["%d 件目: %s" % (v, p) for p in probs]
        blocks = ledger.blocks_of(out)
        print("  periods の %d 件目（seq %d）: %s" % (v, r["seq"], ", ".join(
            "%s %s〜%s" % (n, s, e) for n, (s, e) in sorted(blocks.items(), key=lambda x: x[1]))))
        if expected is None:
            print("      きっかけの値なし。deadline_status は null（正しい）")
        elif expected == "held":
            held.append(v)
            print("      deadline_status の申告 %s：threshold-access の記録が無く、採用が保留のため"
                  "照合を保留" % out.get("deadline_status"))
        else:
            print("      deadline_status の申告 %s、記録から決まる値 %s（照合に使った、採用された "
                  "periods-triggers: %s）" % (out.get("deadline_status"), expected,
                                              "seq %d" % trig_rec["seq"] if trig_rec else "なし"))
    if problems:
        raise ledger.LedgerError("; ".join(problems))
    print("periods のすべての版の区画の境目は、最初の版と一致する。")
    if held:
        print("保留: periods の %s 件目の deadline_status の照合" % ", ".join(map(str, held)))


def cmd_candidates(st, _a):
    """閾値と判定期間の候補（kind が candidates）の照合。T-013。"""
    recs = ledger.records_of_kind(st.records, ledger.CANDIDATES_KIND)
    cut = ledger.check_candidates_order(st.records)
    if not recs:
        print("candidates の記録：なし（照合するものが無い）")
        return
    for v, r in recs:
        out = ledger.check_candidates_record(r)
        ms, hs = ledger.check_candidates_output(st.file_json(r, "output"))
        print("  candidates の %d 件目（seq %d）: 対象の role とパスは決まった 5 つと一致。"
              "出力 %s の sha256 %s" % (v, r["seq"], out["path"], out["sha256"]))
        for t in sorted(r["targets"], key=lambda t: t["path"]):
            if t["role"] != "output":
                print("      %-6s %s  %s" % (t["role"], t["path"], t["sha256"]))
        print("      閾値の倍率 %s、判定期間（日）%s、組み合わせ %d"
              % (", ".join(map(str, ms)), ", ".join(map(str, hs)), len(ms) * len(hs)))
        if cut is None:
            print("      acquisition-start の記録は無い（この記録は、どの acquisition-start "
                  "よりも前）")
        else:
            print("      最初の acquisition-start（seq %d）より前" % cut["seq"])
    print("candidates の記録は、すべて最初の acquisition-start の記録より前にある。")
    hz = ledger.check_horizon_embargo(st.records, st.file_json)
    if hz["status"] == "no-candidates":
        return
    print("J（判定が読む最後の日のずれ）の最大 %d。periods の 1 件目の embargo_days %d %s。"
          % (hz["j_max"], hz["embargo_first"],
             "以下（区切りの作り直しは要らない）" if hz["j_max"] <= hz["embargo_first"]
             else "を超える（作り直しと、periods-triggers が要る）"))
    for p, per, emb, trg, j in hz["points"]:
        print("  %s（seq %d）の時点で採用される periods（seq %d）の embargo_days %d = "
              "max(1 件目の embargo_days, J の最大)。periods-triggers：%s"
              % (p["kind"], p["seq"], per["seq"], emb,
                 "無し" if trg is None else "seq %d、last_read_offset_days %r%s"
                 % (trg["seq"], j, "（null）" if j is None else "（= J の最大）")))
    print("最初の method-access より後の periods-triggers の J は、null か J の最大と等しい"
          "（method-access の記録が無ければ、照合するものは無い）。")
    if hz["status"] == "pending":
        print("保留：method-access・threshold-access の記録がまだ無いので、periods-triggers の照合を保留")
    elif not hz["points"]:
        print("  method-access・threshold-access の記録がまだ無い。その記録ができたときに、"
              "その時点で採用される版と照合する")


def cmd_adopted(st, _a):
    print("採用の規則：最初の threshold-access の記録より seq が小さい記録のうち、その種類の最後の"
          "もの。acquisition-start・acquisition-result・method-access・gkg-run-start・stats-order1・"
          "stats-order1b は区切りに使わない。時刻（Bitcoin の確定"
          "時刻、drand の回の公開時刻）と Pending かどうかは使わない。")
    print("candidates は、これに加えて、すべての記録が最初の acquisition-start より前に"
          "なければならない（candidates の検査。後ろにあれば検証は失敗する）。")
    if st.cut is None:
        print("採用は保留（threshold-access の記録が無いため）。")
    else:
        print("区切り：最初の threshold-access の記録 = seq %d" % st.cut["seq"])
    for kind in ledger.ADOPTED_KINDS:
        rec, cand, cut = ledger.adoption(st.records, kind)
        if cut is None:
            if cand is None:
                print("  %s: 記録なし。採用は保留" % kind)
            else:
                print("  %s: 採用は保留。仮の候補 = seq %d（%d 件目。今ある最後の記録）"
                      % (kind, cand["seq"], ledger.version_of(st.records, cand["seq"])))
            continue
        if rec is None:
            print("  %s: seq %d より前に記録が無い。採用される版は無い" % (kind, cut["seq"]))
        else:
            print("  %s: 採用 = seq %d（%d 件目。seq %d の threshold-access より前の最後の記録）。%s"
                  % (kind, rec["seq"], ledger.version_of(st.records, rec["seq"]), cut["seq"],
                     ADOPT_CONDITION))
        later = [r["seq"] for r in st.records if r["kind"] == kind and r["seq"] > cut["seq"]]
        if later:
            print("      seq %s は threshold-access の記録より後なので、採用しない"
                  % ", ".join(map(str, later)))


def cmd_all(st, a):
    cmd_chain(st, a)
    cmd_anchors(st, a)
    cmd_targets(st, a)
    cmd_access(st, a)
    cmd_acquisition(st, a)
    cmd_stats_order(st, a)
    cmd_method(st, a)
    cmd_gkg_runs(st, a)
    cmd_periods(st, a)
    cmd_candidates(st, a)
    cmd_adopted(st, a)
    print("すべての検査に通った。" + ("採用は保留（threshold-access の記録が無いため）。"
                                      if st.cut is None else ""))
    print(NOT_CHECKED)


def main(argv=None):
    p = argparse.ArgumentParser(allow_abbrev=False, description=__doc__.splitlines()[0])
    p.add_argument("--root", default=os.getcwd())
    sub = p.add_subparsers(dest="cmd", required=True)
    parsers = {}
    for name in ("chain", "anchors", "targets", "access", "acquisition", "stats-order", "method",
                 "gkg-runs",
                 "periods", "candidates", "adopted", "all"):
        s = sub.add_parser(name, allow_abbrev=False)
        s.add_argument("--btc-header", type=_parse_header_arg, action="append",
                       help="高さ=80 バイトのヘッダの16進。.ots の中の Bitcoin の証明と照合する")
        s.add_argument("--ots-dir", action="append", default=[],
                       help="自分で upgrade した .ots を置いたディレクトリ（採用は変わらない）")
        parsers[name] = s
    for name in ("targets", "all"):
        parsers[name].add_argument("--rev", default="working")
    a = p.parse_args(argv)
    fn = {"chain": cmd_chain, "anchors": cmd_anchors, "targets": cmd_targets,
          "access": cmd_access, "acquisition": cmd_acquisition, "method": cmd_method,
          "gkg-runs": cmd_gkg_runs, "stats-order": cmd_stats_order,
          "periods": cmd_periods,
          "candidates": cmd_candidates, "adopted": cmd_adopted,
          "all": cmd_all}[a.cmd]
    try:
        st = State(os.path.abspath(a.root), a.btc_header, a.ots_dir)
        fn(st, a)
    except ledger.LedgerError as e:
        print("失敗: %s" % e, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
