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

終了コード 0: 照らした検査がすべて通った（保留の判定と、照らさなかったもの（例：git の履歴が無い
              写しでの区分表との前後）があれば、そのことを出力する。all では最後の行に出す）
           1: どこかで失敗した（浅い clone で区分表との前後を照らせないときも）  2: 引数の誤り
"""

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import unicodedata

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

    def git(self, *args, env=None):
        r = subprocess.run(["git", "-C", self.root] + list(args), capture_output=True, env=env)
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
        self.unchecked = []      # 照らさなかったもの（all の最後に出す。T-037 再提出1回目 軽2）

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


class Unchecked(Exception):
    """利用者の環境の都合で計算し直せない（Python を起動できない）。止めずに「照らさなかった」と出す。
    （git の履歴が無いときは、計算し直しそのものを行わず、cmd_stats_order がそう表示する。）head の版のスクリプトが 0 以外で終わる・出力が読めないのは、これに
    当たらず、記録と合わないとして止める（T-056 差し戻し1回目 中-2。リードの判断）。"""


def _child_env():
    env = {k: v for k, v in os.environ.items() if not k.startswith("PYTHON") and k != "STATS_AUDIT_LOG"}
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    # PYTHON で始まる環境変数は渡さない（-I でも無視されるが、渡さないことで、どの版の Python でも同じにする）。
    # .pyc の置き場は、環境変数（-I では読まれない）ではなく、python_command の -X pycache_prefix で決める（T-060 軽-1）
    return env


# head の版のスクリプトを流す時間の上限（秒）。超えたら「記録と合わない」（T-056 再提出1回目 中-A）
RUN_TIMEOUT_SECONDS = 1800

# 流すスクリプトを起こす小さなプログラム（T-059）。-I は、環境変数と利用者の site を無視するのに加えて、
# スクリプトのフォルダを sys.path に入れない。順番1 の tagrules.py は同じフォルダの exclusion.py（記録が
# sha256 で縛っているファイル）を読み込むので、スクリプトのフォルダだけを、ふつうにスクリプトを流したときと
# 同じ sys.path の先頭に戻す。そのフォルダには、記録が縛っているファイルしか置かない（_BoundDir）。
RUNNER = ("import os, runpy, sys; p = sys.argv[1]; sys.argv = sys.argv[1:]; "
          "sys.path.insert(0, os.path.dirname(os.path.abspath(p))); runpy.run_path(p, run_name='__main__')")


def python_command(rel, pycache):
    """流すときの引数（T-059）。-I（環境変数・利用者の site・カレントフォルダを使わない）、-B（.pyc を書かない）、
    -X pycache_prefix=<空の一時フォルダ>（.pyc をそこからしか読まない。-I では PYTHONPYCACHEPREFIX が読まれないため）。"""
    return [sys.executable, "-I", "-B", "-X", "pycache_prefix=" + pycache, "-c", RUNNER, rel]


def _run_script(cwd, rel, what):
    """python_command(rel) を cwd で流した標準出力（T-059 から -I・-B・空の pycache_prefix）。
    Python を起動できなければ Unchecked（利用者の環境の都合）。0 以外で終わる、または時間内に終わらなければ
    LedgerError（記録と合わない。記録を作る側の commit の中身で起こせることなので）。"""
    with tempfile.TemporaryDirectory() as pycache:
        try:
            r = subprocess.run(python_command(rel, pycache), cwd=cwd, capture_output=True,
                               env=_child_env(), timeout=RUN_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            raise ledger.LedgerError("%s：head の版の %s が %s 秒の上限の中に終わらなかった（記録と合わない）"
                                     % (what, rel, RUN_TIMEOUT_SECONDS)) from None
        except OSError as e:
            raise Unchecked("%s：Python を起動できない（%s）" % (what, e.__class__.__name__)) from None
    if r.returncode != 0:
        raise ledger.LedgerError("%s：head の版の %s が終了コード %d で終わった（記録は、その版で流した出力が"
                                 "あると主張している）" % (what, rel, r.returncode))
    return r.stdout


def _rgit(repo, *args):
    """計算し直しの git は、GIT_ の環境変数を固定した環境で行う（T-056 差し戻し1回目 軽-3）。"""
    return repo.git(*args, env=ledger.fixed_git_env())


def _name_key(name):
    """名前のぶつかりを調べる鍵。Unicode の正規化（NFC と NFD を同じに扱うため NFD にそろえる）と、大文字小文字
    （casefold）をそろえる（T-058）。"""
    return unicodedata.normalize("NFD", unicodedata.normalize("NFD", name).casefold())


def _check_name_collisions(where, names):
    """書き出す名前（とその途中のフォルダの名前）を _name_key でそろえて比べる。違う名前が同じ鍵になる、または
    同じ名前が2つある、なら LedgerError（記録と合わない）。T-058。"""
    seen, done = {}, set()
    for name in names:
        name = name.rstrip("/")
        if name in done:
            raise ledger.LedgerError("%s に、同じ名前の項目 %r が2つある（記録と合わない）" % (where, name))
        done.add(name)
        parts = name.split("/")
        for i in range(1, len(parts) + 1):
            p = "/".join(parts[:i])
            k = _name_key(p)
            if seen.setdefault(k, p) != p:
                raise ledger.LedgerError("%s に、大文字小文字か Unicode の正規化だけが違う名前 %r と %r がある"
                                         "（書き出すと同じ場所になりうる。記録と合わない）" % (where, seen[k], p))


def _bound_path_ok(path):
    """書き出してよい名前か（相対パスで、空・.・.. の部分が無く、バックスラッシュと NUL を含まない）。"""
    if not path or path.startswith("/") or "\\" in path or "\x00" in path:
        return False
    return all(part not in ("", ".", "..") for part in path.split("/"))


class _BoundDir:
    """記録が sha256 で縛っているファイルだけを、git show <commit>:<path> のバイト列から、空の新しいフォルダに
    書き出したもの（T-059。T-058 の監査 重大-A）。git archive は使わない。__pycache__・ほかの .py・.pth・
    .gitattributes など、縛られていないファイルは置かない。書いたあとに読み戻して、バイト列と sha256 を照らす。
    files: [(path, sha256)]。名前がぶつかる、git の版に無い、sha256 が違う、書き出せない、なら LedgerError。"""

    def __init__(self, repo, commit, files, tmp, what):
        self.commit, self.what = commit, what
        self.paths = [p for p, _ in files]
        where = "%s の、記録が縛っているファイルの名前" % what
        for p in self.paths:
            if not _bound_path_ok(p):
                raise ledger.LedgerError("%s %r は、書き出せる相対パスでない（記録と合わない）" % (where, p))
        _check_name_collisions(where, self.paths)
        self.dir = tempfile.mkdtemp(prefix="bound-", dir=tmp)
        for path, sha in files:
            data = _show(repo, commit, path)
            if ledger.sha256_hex(data) != sha:
                raise ledger.LedgerError("%s：%s:%s の sha256 %s が、記録の %s と違う" % (
                    what, commit[:12], path, ledger.sha256_hex(data), sha))
            dest = os.path.join(self.dir, *path.split("/"))
            try:
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                with open(dest, "xb") as f:
                    f.write(data)
                with open(dest, "rb") as f:
                    back = f.read()
            except (OSError, ValueError) as e:
                raise ledger.LedgerError("%s：%s を書き出せない（%s。記録と合わない）"
                                         % (what, path, e.__class__.__name__)) from None
            if back != data:
                raise ledger.LedgerError("%s：書き出した %s が git show のバイト列と違う（記録と合わない）" % (what, path))
        found = []
        for root, dirs, names in os.walk(self.dir):
            found += [os.path.relpath(os.path.join(root, n), self.dir).replace(os.sep, "/") for n in names]
        if sorted(found) != sorted(self.paths):
            raise ledger.LedgerError("%s：書き出したフォルダの中身が、記録が縛っているファイルと違う（記録と合わない）" % what)

    def run(self, rel, label):
        if rel not in self.paths:
            raise ledger.LedgerError("%s：流す %s を、記録が sha256 で縛っていない（記録と合わない）" % (label, rel))
        return _run_script(self.dir, rel, label)


def _show(repo, head, path):
    try:
        return _rgit(repo, "show", "%s:%s" % (head, path))
    except ledger.LedgerError:
        raise ledger.LedgerError("記録の head %s の版に %s が無い" % (head[:12], path)) from None


def _check_head(st, repo, r, doc):
    """記録の head が、その記録を足す直前の記録を持つ commit で、ancestors がその祖先であること。T-056。"""
    head = doc["head"]
    what = "seq %d の %s" % (r["seq"], r["kind"])
    try:
        _rgit(repo, "cat-file", "-e", head + "^{commit}")
    except ledger.LedgerError:
        raise ledger.LedgerError("%s の head %s の commit が、このリポジトリに無い" % (what, head)) from None
    try:
        led = _rgit(repo, "show", "%s:%s" % (head, LEDGER_REL))
    except ledger.LedgerError:
        led = None
    if led != ledger.prefix_bytes(st.data, r["seq"] - 1):
        raise ledger.LedgerError("%s の head %s の版の sealed/ledger.jsonl が、この記録を足す直前の記録（先頭 %d 行）と"
                                 "一致しない" % (what, head[:12], r["seq"] - 1))
    for a in doc["ancestors"]:
        try:
            _rgit(repo, "merge-base", "--is-ancestor", a, head)
        except ledger.LedgerError:
            raise ledger.LedgerError("%s の ancestors の %s が、head %s の祖先でない" % (what, a[:12], head[:12])) from None


def recompute_orders(st, repo, got):
    """順番1・1b の記録の値を、記録の head の版から計算し直して照らす（T-056。T-055 の監査 中-1、T-048 の軽-1。
    差し戻し1回目で、項目ごとに続け、照らさなかった項目を列挙する形に改めた）。
      - Python の要らない照合（必ず行う）：head が、その記録を足す直前の記録を持つ commit であること、
        ancestors が head の祖先であること、順番1 の対象のうちファイルのもの（head の版と、1cb463a: などの
        git show）、順番1b の files、order1_ref。
      - Python の要る照合：順番1 の「の出力」と、順番1b の counting（counting.py を流した出力の sha256 と値）。
        流すフォルダには、記録が sha256 で縛っているファイル（順番1 は targets のうち「の出力」でないもの、
        順番1b は files）だけを、git show のバイト列から空の新しいフォルダに書き出す（T-059。_BoundDir）。
        Python は -I・-B・空の pycache_prefix で流す（python_command）。
    値が違う、または流したスクリプトが 0 以外で終わる・出力が読めない、なら LedgerError（止める）。
    縛られたファイルの名前のぶつかり（大文字小文字・Unicode の正規化）、流すスクリプトが縛られていない、も
    LedgerError。利用者の環境の都合で計算し直せない項目（Python を起動できない）は、止めずに列挙する。
    流すのは、この verify を動かしている Python（sys.executable）。
    返り値: (照らした項目の数, 照らさなかった項目の一覧)。
    """
    checked, unchecked = 0, []
    with tempfile.TemporaryDirectory() as tmp:
        bound = {}

        def bound_dir(commit, files, what):
            """記録が縛っているファイルだけのフォルダ（commit と files ごとに一つ）。T-059。"""
            key = (commit, tuple(files))
            if key not in bound:
                bound[key] = _BoundDir(repo, commit, files, tmp, what)
            return bound[key]

        def python_item(label, fn):
            nonlocal checked
            try:
                fn()
                checked += 1
            except Unchecked as e:
                unchecked.append("%s（%s）" % (label, e))
        for r in got["order1"]:
            doc = st.file_json(r, ledger.ORDER1_KIND)
            _check_head(st, repo, r, doc)
            checked += 1 + len(doc["ancestors"])
            head = doc["head"]
            what1 = "seq %d の stats-order1" % r["seq"]
            # 記録が sha256 で縛っているファイル（targets のうち「の出力」でないもの）を、commit ごとに分ける
            groups = {}
            for t in doc["targets"]:
                if t["name"].endswith(" の出力"):
                    continue
                short, path = t["name"].split(":", 1) if ":" in t["name"] else (None, t["name"])
                groups.setdefault(short, []).append((path, t["sha256"]))
            for t in doc["targets"]:
                name = t["name"]
                output = name.endswith(" の出力")
                base = name[:-len(" の出力")] if output else name
                label = "seq %d の順番1 の対象「%s」" % (r["seq"], name)

                def compare(data, t=t, name=name):
                    v = ledger.sha256_hex(data)
                    if v != t["sha256"]:
                        raise ledger.LedgerError("seq %d の stats-order1 の対象 %s の sha256 %s が、head %s の版から計算し直した"
                                                 "値 %s と違う" % (r["seq"], name, t["sha256"], head[:12], v))
                if ":" in base:
                    short, path = base.split(":", 1)
                    commit = ledger.ORDER1_ANCESTORS.get(short)
                    if commit is None:
                        raise ledger.LedgerError("対象 %s の commit %s が、決まった祖先の一覧に無い" % (name, short))
                else:
                    short, path, commit = None, base, head
                if not output:
                    compare(_show(repo, commit, path))
                    checked += 1
                    continue
                _show(repo, commit, path)

                def run_output(commit=commit, short=short, path=path, label=label, compare=compare):
                    d = bound_dir(commit, groups.get(short, []), "%s（%s の版）" % (what1, commit[:12]))
                    compare(d.run(path, label))
                python_item(label, run_output)
        for r in got["order1b"]:
            doc = st.file_json(r, ledger.ORDER1B_KIND)
            what = "seq %d の stats-order1b" % r["seq"]
            ledger.check_order1b_doc(r, doc)       # files はちょうど ORDER1B_REQUIRED_FILES の 4 件（T-060）
            _check_head(st, repo, r, doc)
            checked += 1 + len(doc["ancestors"])
            head = doc["head"]
            for f in doc["files"]:
                v = ledger.sha256_hex(_show(repo, head, f["path"]))
                if v != f["sha256"]:
                    raise ledger.LedgerError("%s の files の %s の sha256 %s が、head %s の版の %s と違う"
                                             % (what, f["path"], f["sha256"], head[:12], v))
                checked += 1
            ref = doc["order1_ref"]
            if ref is not None:
                o1 = ledger.first_order1(st.records)
                if o1 is None or ref["seq"] != o1["seq"] or ref["seq"] >= r["seq"] \
                        or ref["record_sha256"] != ledger.sha256_hex(ledger.canonical_line(o1)):
                    raise ledger.LedgerError("%s の order1_ref %r が、stats-order1 の記録の seq と行の sha256 と一致しない"
                                             % (what, ref))
            elif ledger.first_order1([x for x in st.records if x["seq"] < r["seq"]]) is not None:
                raise ledger.LedgerError("%s の order1_ref が null なのに、それより前に stats-order1 の記録がある" % what)
            checked += 1

            def run_counting(doc=doc, what=what, head=head):
                label = "%s の counting" % what
                # 流すフォルダに置くのは ORDER1B_REQUIRED_FILES の 4 件だけ（T-060。T-059 の監査 重大-1）
                shas = {f["path"]: f["sha256"] for f in doc["files"]}
                if sorted(shas) != sorted(ledger.ORDER1B_REQUIRED_FILES) or len(shas) != len(doc["files"]):
                    raise ledger.LedgerError("%s の files が、決まった %d 件（ORDER1B_REQUIRED_FILES）とちょうど一致しない"
                                             % (what, len(ledger.ORDER1B_REQUIRED_FILES)))
                files = [(p, shas[p]) for p in ledger.ORDER1B_REQUIRED_FILES]
                out = bound_dir(head, files, "%s（%s の版）" % (what, head[:12])).run(ledger.COUNTING_SCRIPT, label)
                c = doc["counting"]
                if ledger.sha256_hex(out) != c["output_sha256"]:
                    raise ledger.LedgerError("%s の counting.output_sha256 %s が、head %s の版の counting.py の出力 %s と違う"
                                             % (what, c["output_sha256"], head[:12], ledger.sha256_hex(out)))
                try:
                    d = json.loads(out.decode("utf-8"))
                    got_c = {"candidate_ids": [x["id"] for x in d["candidates"]],
                             "criteria_ids": list(d["criteria_ids"]),
                             "official_candidate": d["official_candidate"],
                             "official_status": d["official_status"]}
                except (UnicodeDecodeError, ValueError, KeyError, TypeError):
                    raise ledger.LedgerError("%s：head の版の counting.py の出力を読めない（記録と合わない）" % what) from None
                for k, v in got_c.items():
                    if c[k] != v:
                        raise ledger.LedgerError("%s の counting.%s %r が、head %s の版の counting.py の出力の %r と違う"
                                                 % (what, k, c[k], head[:12], v))
            python_item("%s の counting（counting.py の出力）" % what, run_counting)
    return checked, unchecked


def cmd_stats_order(st, a):
    """統計係の順番1・順番1b の記録の照合と一覧。T-037（差し戻し1回目で改めた）、T-056。"""
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
        print("      オーナーの承認：%s の「%s」の下の「%s」（ちょうど 1 行）"
              % (doc["owner_approval"]["source"], doc["owner_approval"]["heading"], doc["owner_approval"]["line"]))
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
        # 軽2：止めないが、照らさなかったことを all の最後にも出す
        st.unchecked.append("区分表の取得と順番1 の前後（git の履歴が無いため）")
        print("照らさなかった：git の履歴が無いので、区分表の取得との前後は照合していない"
              "（--rev auto には git の履歴が要る）")
        if got["order1"] or got["order1b"]:
            st.unchecked.append("順番1・1b の値の計算し直し（git の履歴が無いため）")
            print("照らさなかった：git の履歴が無いので、順番1・1b の値を head の版から計算し直していない")
        return
    if repo.git("rev-parse", "--is-shallow-repository", env=ledger.fixed_git_env()).strip() != b"false":
        # 軽1：浅い clone では親が取れず、照合の理由が分かりにくいので、先に止めて理由を出す
        raise ledger.LedgerError("浅い clone である。区分表の取得との前後の照合には履歴が要るので、"
                                 "--depth を付けない clone（git fetch --unshallow でもよい）で確かめる")
    n = ledger.check_order1_before_themes(st.records, repo.git)
    mpath = os.path.join(st.root, ledger.THEMES_MANIFEST)
    body = None
    if os.path.isfile(mpath) and not os.path.islink(mpath):
        with open(mpath, "rb") as f:
            body = f.read()
    rows = ledger.check_themes_manifest_refs(st.records, body)
    # T-056：順番1・1b の値を、記録の head の版から計算し直す（--rev auto か <コミット> のとき）
    if got["order1"] or got["order1b"]:
        if getattr(a, "rev", "working") == "working":
            # --rev が working でなければ（auto でもコミットでも）計算し直す。計算し直しには、--rev の値ではなく、
            # 記録の head を使う（T-056 差し戻し1回目 軽-4）
            st.unchecked.append("順番1・1b の値の計算し直し（--rev working では行わない。--rev auto で照らす）")
            print("照らさなかった：順番1・1b の値の計算し直しは、--rev working では行わない（--rev auto で照らす）")
        else:
            k, missed = recompute_orders(st, repo, got)
            print("順番1・1b の値：記録 %d 件について、%d 項目を head の版から計算し直して照らした（流した Python：%s）。"
                  "照らした項目は、どれも記録と一致する。"
                  % (len(got["order1"]) + len(got["order1b"]), k, sys.version.split()[0]))
            for m in missed:
                st.unchecked.append("順番1・1b の値：%s" % m)
                print("照らさなかった：順番1・1b の値：%s" % m)
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


def gkg_manifests_check(st, day_dirs=()):
    """gkg-run-start の記録と、収集係のマニフェストの照合（T-041、T-066）。マニフェストが無い mode は照らさず、
    そう表示して all の最後にも出す。T-066：run-start の行の入力の値・day の行・run-complete の行の照合
    （ledger.check_gkg_manifest_rows）、gkg-run-result（マニフェストの時刻証明）の照合、日の集計の sha256 の照合
    （day_dirs を渡したときだけ）。"""
    manifests = {}
    for mode, rel in ledger.GKG_MANIFESTS.items():
        path = os.path.join(st.root, rel)
        manifests[mode] = None
        if os.path.lexists(path):
            # T-043（T-041 の監査 軽-1）：通常のファイルでない（symlink・ディレクトリなど）なら失敗
            if os.path.islink(path) or not os.path.isfile(path):
                raise ledger.LedgerError("%s が通常のファイルでない（symlink かディレクトリなど）" % rel)
            with open(path, "rb") as f:
                manifests[mode] = f.read()
    got = ledger.check_gkg_manifests(st.records, st.file_json, manifests)
    results = ledger.check_gkg_results(st.records, st.file_json, manifests)
    day_rows, states, runs_by_key = [], {}, {}
    for mode, res in got.items():
        rel = ledger.GKG_MANIFESTS[mode]
        if res is None:
            st.unchecked.append("%s の run-start の行と gkg-run-start の記録の照合（マニフェストが無い）" % rel)
            print("照らさなかった：%s が無いので、run-start の行と gkg-run-start の記録の照合をしていない" % rel)
            continue
        print("%s：run-start の行 %d 行、異なる run_id %d 個。どの行も、kind・mode・run_id の合う gkg-run-start の"
              "記録を指し、異なる run_id の数は %s の記録の件数と同じ" % (rel, res[1], res[0], mode))
        runs = ledger.check_gkg_manifest_rows(st.records, st.file_json, mode, manifests[mode])
        for rid, run in runs.items():
            c = run["complete"]
            print("  run_id %s：run-start の入力の値（code_sha256・trial_days・method_access_seq・filelist_sha256・"
                  "除外の規則の記録・mode・run_id）は gkg-run-start（seq %d）の中身と同じ。day の行 %d 行（日付は区画の"
                  "中で重ならない）。files_failed の合計 %d（day の行の合計。T-070）。%s"
                  % (rid, run["start"]["gkg_run_seq"], len(run["days"]), sum(d["files_failed"] for d in run["days"]),
                                          "run-complete（%d 行目）の数は day の行の合計と合う" % run["complete_lineno"]
                                          if c else "run-complete はまだ無い（取得の途中か、止まっている）"))
            day_rows += [(mode, d) for d in run["days"]]
            runs_by_key[(mode, rid)] = run
            states[(mode, rid)] = "run-complete まである" if c is not None else \
                "終わっていない run（run-complete の行が無い）"
            if c is not None:
                day_rows.append((mode, {"file_name": c.get("fetch_log_file"), "sha256": c.get("fetch_log_sha256"),
                                        "size": c.get("fetch_log_size"), "log": True}))
                r = results.get((mode, rid))
                if r is not None:
                    doc = st.file_json(r, ledger.GKG_RESULT_KIND)
                    print("  run_id %s：gkg-run-result（seq %d）の manifest_sha256 は %s の先頭 %d 行と同じで、"
                          "run-complete の行を含む" % (rid, r["seq"], rel, doc["manifest_lines"]))
                    _check_result_commit(st, r, doc)
    # T-068（T-066 の監査 中-2）：gkg-run-result の無い run は、マニフェストの状態（run-complete があるか、行が
    # あるか）によらず、gkg-run-start の記録ごとに「照らさなかった」に出す。行を消しても、この数は減らない
    for r in st.records:
        if r["kind"] != ledger.GKG_RUN_KIND:
            continue
        d = st.file_json(r, ledger.GKG_RUN_KIND)
        key = (d["mode"], d["run_id"])
        rel = ledger.GKG_MANIFESTS[d["mode"]]
        if key not in results:
            state = states.get(key, "マニフェストに行が無い")
            st.unchecked.append("%s の run_id %s のマニフェストの時刻証明（gkg-run-result の記録が無い。%s）"
                                % (rel, d["run_id"], state))
            print("照らさなかった：seq %d の run（%s・run_id %s）のマニフェストの時刻証明が無い（gkg-run-result の記録が"
                  "無い。%s）" % (r["seq"], d["mode"], d["run_id"], state))
        _check_plan_body(st, r, d, runs_by_key.get(key), day_dirs)
        if d["mode"] == "official" and "days" not in d:
            st.unchecked.append("seq %d の gkg-run-start（official）の取得の計画（days・files_selected が記録に無い）"
                                % r["seq"])
            print("照らさなかった：seq %d の gkg-run-start（official）に取得の計画（days・files_selected）が無いので、"
                  "日とファイルの数を、データを受け取る前の記録と照らしていない" % r["seq"])
    _check_day_files(st, day_rows, day_dirs)


def plan_file_name(mode, run_id):
    """計画の本体（ledger.gkg_plan_canonical のバイト列）のファイルの名前（T-070）。収集係が日の集計と同じ置き場所に
    書く（T-071）。"""
    return "gkg-%s-%s-plan.json" % (mode, run_id)


def _check_plan_body(st, r, d, run, day_dirs):
    """gkg-run-start の plan_sha256 と、計画の本体（--day-files の置き場所の gkg-<mode>-<run_id>-plan.json）を照らし、
    本体があれば、マニフェストの day の行の日付・files_listed・failed_files がその一覧と合うことを照らす（T-070）。
    本体が無ければ「照らさなかった」。plan_sha256 の無い official の記録も「照らさなかった」。"""
    if ledger.GKG_RUN_PLAN_SHA_KEY not in d:
        if d["mode"] == "official" and "days" in d:
            st.unchecked.append("seq %d の gkg-run-start（official）の計画の一覧（plan_sha256 が記録に無い）" % r["seq"])
            print("照らさなかった：seq %d の gkg-run-start（official）に plan_sha256 が無いので、どの日のどのファイルかを"
                  "データを受け取る前の記録と照らしていない（数だけを照らした）" % r["seq"])
        return
    name = plan_file_name(d["mode"], d["run_id"])
    found = None
    for dd in day_dirs:
        p = os.path.join(dd, name)
        if os.path.isfile(p) and not os.path.islink(p):
            found = p
            break
    if found is None:
        st.unchecked.append("seq %d の run の計画の本体（%s。--day-files の置き場所に無い）との照合" % (r["seq"], name))
        print("照らさなかった：seq %d の run の計画の本体 %s が、--day-files の置き場所に無い（plan_sha256 は記録にある）"
              % (r["seq"], name))
        return
    with open(found, "rb") as f:
        data = f.read()
    if ledger.sha256_hex(data) != d[ledger.GKG_RUN_PLAN_SHA_KEY]:
        raise ledger.LedgerError("%s の sha256 が、seq %d の gkg-run-start の plan_sha256 と違う" % (name, r["seq"]))
    plan = ledger.parse_gkg_plan(data)
    if (len(plan), sum(len(v) for v in plan.values())) != (d["days"], d["files_selected"]):
        raise ledger.LedgerError("%s の日の数・ファイルの数が、seq %d の gkg-run-start の days・files_selected と違う"
                                 % (name, r["seq"]))
    if d["mode"] == "trial" and sorted(plan) != list(d["trial_days"]):
        raise ledger.LedgerError("%s の日が、seq %d の trial_days と違う" % (name, r["seq"]))
    if run is not None:
        ledger.check_plan_rows(plan, run, "%s（seq %d の run）" % (ledger.GKG_MANIFESTS[d["mode"]], r["seq"]))
    print("seq %d の run：計画の本体 %s の sha256 は plan_sha256 と同じで、day の行の日付・files_listed・failed_files は"
          "その一覧と合う" % (r["seq"], name))


def _check_result_commit(st, r, doc):
    """gkg-run-result の manifest_commit の版のマニフェストの先頭が、記録と同じ（git の履歴があるとき）。"""
    repo = Repo(st.root)
    try:
        repo.git("rev-parse", "--git-dir")
    except (ledger.LedgerError, OSError):
        st.unchecked.append("seq %d の gkg-run-result の manifest_commit の照合（git の履歴が無い）" % r["seq"])
        print("  照らさなかった：git の履歴が無いので、seq %d の manifest_commit の版は照らしていない" % r["seq"])
        return
    try:
        body = _rgit(repo, "show", "%s:%s" % (doc["manifest_commit"], doc["manifest_path"]))
    except ledger.LedgerError:
        raise ledger.LedgerError("seq %d の gkg-run-result の manifest_commit %s の版に %s が無い"
                                 % (r["seq"], doc["manifest_commit"][:12], doc["manifest_path"])) from None
    if ledger.sha256_hex(ledger.manifest_prefix(body, doc["manifest_lines"], doc["manifest_path"])) \
            != doc["manifest_sha256"]:
        raise ledger.LedgerError("seq %d の gkg-run-result の manifest_sha256 が、manifest_commit %s の版の先頭 %d 行と違う"
                                 % (r["seq"], doc["manifest_commit"][:12], doc["manifest_lines"]))
    print("  manifest_commit %s の版のマニフェストの先頭 %d 行も同じ" % (doc["manifest_commit"][:12], doc["manifest_lines"]))


def _check_day_files(st, rows, day_dirs):
    """日の集計（と取得の記録）の sha256 を、渡された置き場所のファイルと照らす（T-066）。置き場所を渡さないとき、
    またはファイルが無いときは「照らさなかった」。違えば止める。"""
    if not rows:
        return
    if not day_dirs:
        st.unchecked.append("日の集計の sha256（--day-files で置き場所を渡したときだけ照らす）")
        print("照らさなかった：日の集計と取得の記録の sha256（%d 件）は、--day-files で置き場所を渡したときだけ照らす"
              % len(rows))
        return
    seen, missing = 0, []
    for mode, row in rows:
        name = row.get("file_name")
        found = None
        for d in day_dirs:
            p = os.path.join(d, name) if isinstance(name, str) and "/" not in name else None
            if p and os.path.isfile(p) and not os.path.islink(p):
                found = p
                break
        if found is None:
            missing.append(str(name))
            continue
        with open(found, "rb") as f:
            data = f.read()
        if ledger.sha256_hex(data) != row.get("sha256") or ("size" in row and len(data) != row["size"]):
            raise ledger.LedgerError("%s の sha256（または大きさ）が、%s のマニフェストの行と違う" % (name, mode))
        seen += 1
    print("日の集計と取得の記録：%d 件を、置き場所のファイルの sha256 と照らし、どれもマニフェストと同じ" % seen)
    if missing:
        st.unchecked.append("日の集計と取得の記録のうち、置き場所に無い %d 件（%s）" % (len(missing), "、".join(missing)))
        print("照らさなかった：置き場所に無い %d 件（%s）" % (len(missing), "、".join(missing)))


def cmd_gkg_runs(st, a):
    """GKG の取得の run の開始（kind が gkg-run-start）の照合と一覧。T-031、T-041。T-066：マニフェストの行と
    gkg-run-result の照合。"""
    runs = ledger.check_gkg_runs(st.records, st.file_json)
    for r in st.records:
        if r["kind"] == ledger.GKG_RESULT_KIND:
            ledger.check_gkg_result_doc(st.records, r, st.file_json(r, ledger.GKG_RESULT_KIND), st.file_json, st.data)
    gkg_manifests_check(st, [os.path.abspath(d) for d in getattr(a, "day_files", None) or []])
    if not runs:
        print("gkg-run-start の記録：なし")
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
          "より前だけ。除外の規則の記録（exclusion_rule_seq）は、kind が stats-order1 の最初の記録で、その行の "
          "sha256 と同じ（T-037。T-066 で文言を今の形に直した）。" % ("1 件" if officials else "まだ無い"))
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
          "stats-order1b は区切りに使わない（gkg-run-result も使わない。T-066）。時刻（Bitcoin の確定"
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
    if st.unchecked:
        print("ただし、次は照らさなかった（終了コード 0 は、照らした検査がすべて通ったことだけを示す）："
              + "、".join(st.unchecked))
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
    for name in ("targets", "all", "stats-order"):
        parsers[name].add_argument("--rev", default="working")
    for name in ("gkg-runs", "all"):
        # T-066：日の集計（と取得の記録）の置き場所。渡したときだけ sha256 を照らす（第三者はディスクを持たない）
        parsers[name].add_argument("--day-files", action="append", default=[])
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
