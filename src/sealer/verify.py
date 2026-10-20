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
                                                       （git の履歴：マニフェストに行が入った commit の親に順番1）。
                                                       順番2（stats-order2。T-073・T-078）の記録の形・行き先・inputs・
                                                       時機の条件・コードの版。--day-files で決まった記録の decide() を
                                                       流し直す（手順書16章）。順番3の試みと順番3の記録
                                                       （stats-order3-attempt・stats-order3。T-090）の形・時機の条件・
                                                       コードの版と、封印した版の order3_gate() の計算し直し（手順書17章）。
                                                       順番4（stats-order4。T-095）の形・位置・参照・一覧のつじつま・
                                                       コードの版と、封印済みの candidates.py での72本の条件。--store <日の
                                                       集計の置き場所> で、封印済みの counting.py で C7 の分母を数え直して
                                                       照らす（手順書18章。all にも付けられる）
    python3 -B src/sealer/verify.py gkg-runs           GKG の取得の run の開始（gkg-run-start。T-031）の
                                                       ledger_head・drand・中身・順序。試しの run の回数と、
                                                       各 run の run_id・code_sha256・日を並べる
    python3 -B src/sealer/verify.py filelist-rebuild --masterfilelist F [--out O]
                                                       GDELT の公開の一覧 F を、acquisition-start が固定する
                                                       版の filelist.py の規則で絞り、sha256 を kept_rows_sha256
                                                       と照らす（T-073）。一致すれば --out に本体を書く
                                                       （gkg-runs --filelist に渡す）。all には入らない
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

    def commit_for_seq(self, data, partial=False):
        """{seq: その記録を最初に含んだコミット}。履歴の記録が今の記録の先頭と食い違えば失敗。
        partial が False なら、どのコミットにも無い seq（まだコミットされていない記録）があれば失敗。True なら、
        その seq を返り値に入れずに返す（T-074。順番2の行き先の照合が「照らさなかった」にするため）。"""
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
        if missing and not partial:
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


def _run_script(cwd, rel, what, code=None, args=()):
    """python_command(rel) を cwd で流した標準出力（T-059 から -I・-B・空の pycache_prefix）。
    code を渡すと、RUNNER の代わりにその小さなプログラムを、同じ -I・-B・空の pycache_prefix で流し、args を渡す
    （T-070：計画の作り直し）。
    Python を起動できなければ Unchecked（利用者の環境の都合）。0 以外で終わる、または時間内に終わらなければ
    LedgerError（記録と合わない。記録を作る側の commit の中身で起こせることなので）。"""
    with tempfile.TemporaryDirectory() as pycache:
        cmd = python_command(rel, pycache) if code is None else \
            [sys.executable, "-I", "-B", "-X", "pycache_prefix=" + pycache, "-c", code] + list(args)
        try:
            r = subprocess.run(cmd, cwd=cwd, capture_output=True,
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

    def __init__(self, repo, commit, files, tmp, what, blobs=None):
        """blobs（T-070）：{path: バイト列}。渡したときは git show の代わりにそれを書く（版ごとに sha256 で探した
        バイト列。sha256 は files と照らす）。"""
        self.commit, self.what = commit, what
        self.paths = [p for p, _ in files]
        where = "%s の、記録が縛っているファイルの名前" % what
        for p in self.paths:
            if not _bound_path_ok(p):
                raise ledger.LedgerError("%s %r は、書き出せる相対パスでない（記録と合わない）" % (where, p))
        _check_name_collisions(where, self.paths)
        self.dir = tempfile.mkdtemp(prefix="bound-", dir=tmp)
        for path, sha in files:
            data = _show(repo, commit, path) if blobs is None else blobs[path]
            if ledger.sha256_hex(data) != sha:
                raise ledger.LedgerError("%s：%s:%s の sha256 %s が、記録の %s と違う" % (
                    what, (commit or "版")[:12], path, ledger.sha256_hex(data), sha))
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


def _version_or_empty(repo, commit, rel):
    try:
        _rgit(repo, "cat-file", "-e", "%s:%s" % (commit, rel))
    except ledger.LedgerError:
        return b""
    return _rgit(repo, "show", "%s:%s" % (commit, rel))


# ---- T-078：順番2の記録の、git を使う照合（書く仕組みと verify が同じ関数を使う）と、封印した decide() の流し方

ORDER2_MANIFEST_PATHS = (ledger.GKG_MANIFESTS["trial"], ledger.GKG_MANIFESTS["official"])
ORDER2_EXIT_STATUS = {0: "decided", 1: "stopped", 3: "pending"}      # counting.EXIT_CODES と同じ（テストが照らす）


def _git_ok(repo, *args):
    """git が 0 で終わるか（GIT_ の環境変数を固定して動かす）。"""
    try:
        r = subprocess.run(["git", "-C", repo.root] + list(args), capture_output=True, env=ledger.fixed_git_env())
    except OSError:
        return False
    return r.returncode == 0


def _has_rows(repo, commit, rel):
    """commit の版の rel に、空でない行が一つ以上あるか（無い版は False）。"""
    if not _git_ok(repo, "cat-file", "-e", "%s:%s" % (commit, rel)):
        return False
    return any(line.strip() for line in _rgit(repo, "show", "%s:%s" % (commit, rel)).split(b"\n"))


def order2_f_set(repo, starts):
    """時機の条件の F の集合（seal-order1.md 3章 (2)）を、starts（記録した refs の commit と worktree の HEAD）から辿る範囲で
    計算する：`git log --full-history --format=%H <starts> -- <二つのマニフェスト>` が出す commit のうち、その版の二つの
    マニフェストのどちらかに行が一つ以上あるもの。各要素は {commit, parents}（parents は `git rev-parse C^@` の順）。
    commit の順に並べる（集合として扱う）。git は GIT_ の環境変数を固定して動かす（GIT_NO_REPLACE_OBJECTS・GIT_GRAFT_FILE）。"""
    if not starts:
        return []
    log = _rgit(repo, "log", "--full-history", "--format=%H", *starts, "--", *ORDER2_MANIFEST_PATHS).decode().split()
    out = []
    for c in sorted(set(log)):
        if any(_has_rows(repo, c, p) for p in ORDER2_MANIFEST_PATHS):
            out.append({"commit": c, "parents": _rgit(repo, "rev-parse", c + "^@").decode().split()})
    return out


def order2_git_ok(repo, f_set, line):
    """F の集合のどの commit も、親のうち少なくとも一つの版の sealed/ledger.jsonl に、行の全体が line（参照する順番1b の
    記録の行。改行を除く）と一致する行があること。親が無い commit があれば満たさない。返り値: (満たすか, 理由か None)。"""
    for c in f_set:
        if not c["parents"]:
            return False, "F の commit %s に親が無い（最初の commit にマニフェストの行がある）" % c["commit"][:12]
        if not any(line in _version_or_empty(repo, p, LEDGER_REL).split(b"\n") for p in c["parents"]):
            return False, ("F の commit %s（マニフェストに行がある）のどの親の sealed/ledger.jsonl にも、参照する順番1b の"
                           "記録の行が無い（順番1b が試運転のデータより前に封印されたことを、git の親子で示せない）"
                           % c["commit"][:12])
    return True, None


def _main_worktree(repo):
    """repo が本体の worktree（clone した最初の作業ツリー）か（--git-dir と --git-common-dir が同じ）。"""
    gd = _rgit(repo, "rev-parse", "--path-format=absolute", "--git-dir").decode().strip()
    cd = _rgit(repo, "rev-parse", "--path-format=absolute", "--git-common-dir").decode().strip()
    return os.path.realpath(gd) == os.path.realpath(cd)


def read_refs_now(repo, label="順番2"):
    """時機の条件を確かめる前に、今のリポジトリの参照を読む（T-091。seal-order1.md 177行の順の 1）。F と ok は、まだ計算しない。
      - 本体の worktree であること（counting.md 4章 (3) の F を数える範囲）。違えば LedgerError（何も書かない）。
      - HEAD、`git for-each-ref --format='%(refname) %(objectname)'` の全行（名前の順）、`git worktree list --porcelain` の
        各 HEAD（重なりを除いて並べる）、--git-common-dir の下の info/grafts の有無、浅い clone か。
    git は GIT_ の環境変数を固定して動かす。返り値: {"head", "refs", "worktree_heads", "graft", "shallow"}。
    書く仕組みは、これを読んだあとで bundle を作って list-heads と照らし（ledger.bundle_heads_match）、合ったときだけ
    timing_from_refs で F と ok を計算する。"""
    if not _main_worktree(repo):
        raise ledger.LedgerError("本体の worktree（clone した最初の作業ツリー）でない。%sは本体の worktree で行う"
                                 "（counting.md 4章 (3)。F を数える範囲を git log --all とそろえるため）。書かない" % label)
    common = _rgit(repo, "rev-parse", "--path-format=absolute", "--git-common-dir").decode().strip()
    graft = os.path.lexists(os.path.join(common, "info", "grafts"))
    shallow = _rgit(repo, "rev-parse", "--is-shallow-repository").strip() != b"false"
    head = _rgit(repo, "rev-parse", "--verify", "HEAD^{commit}").decode().strip()
    refs = []
    for line in _rgit(repo, "for-each-ref", "--format=%(refname) %(objectname)").decode("utf-8").splitlines():
        name, _sp, obj = line.partition(" ")
        refs.append({"ref": name, "commit": obj})
    refs.sort(key=lambda x: x["ref"])
    heads = []
    for line in _rgit(repo, "worktree", "list", "--porcelain").decode("utf-8").splitlines():
        if line.startswith("HEAD ") and line[5:].strip() not in heads:
            heads.append(line[5:].strip())
    heads.sort()
    return {"head": head, "refs": refs, "worktree_heads": heads, "graft": graft, "shallow": shallow}


def timing_from_refs(repo, records, ref, snap):
    """read_refs_now で読んだ参照（snap）から、参照する順番1b の記録 ref の時機の条件（(a)）を計算する（seal-order1.md 3章 (2)。
    119・120行の graft・浅い clone・GIT_ の環境変数の固定、counting.md 4章 (3) の F を数える範囲）。T-091 で
    order2_timing_now から分けた（計算は変えていない）。
      1. 計算の前の確かめ：refs/replace/ の参照（snap の refs の名前から）、info/grafts、浅い clone。どれかに当たれば F を
         計算せず、ok は False。
      2. F の集合を、snap の refs と worktree の HEAD の commit から辿る範囲で計算し（order2_f_set）、今の git log --all と
         同じ集合であることを確かめる（違えば LedgerError。何も書かない）。
      3. ledger の条件（順番1b が最初の method-access より前）と、git の条件（order2_git_ok）。
    返り値: (timing_check, timing_guards)。"""
    refs, heads, graft, shallow = snap["refs"], snap["worktree_heads"], snap["graft"], snap["shallow"]
    replace = [r["ref"] for r in refs if r["ref"].startswith(ledger.REPLACE_REF_PREFIX)]
    reasons = []
    if replace:
        reasons.append("refs/replace/ に参照がある（%s）。置き換えで親を変えうるので計算しない" % "、".join(replace))
    if graft:
        reasons.append("graft のファイル（%s）がある。親を変えうるので計算しない" % "info/grafts")
    if shallow:
        reasons.append("浅い clone である。親が取れないので計算しない")
    if not ledger.order2_ledger_timing_ok(records, ref["seq"]):
        reasons.append("参照する順番1b の記録（seq %d）が、最初の method-access より後にある" % ref["seq"])
    f_set = []
    if not (replace or graft or shallow):
        starts = sorted({x["commit"] for x in refs} | set(heads))
        f_set = order2_f_set(repo, starts)
        every = _rgit(repo, "log", "--all", "--full-history", "--format=%H", "--", *ORDER2_MANIFEST_PATHS).decode().split()
        every = {c for c in set(every) if any(_has_rows(repo, c, p) for p in ORDER2_MANIFEST_PATHS)}
        if every != {c["commit"] for c in f_set}:
            raise ledger.LedgerError("F の集合が、git log --all と、記録する参照・worktree の HEAD から辿った範囲とで違う。書かない")
        ok_git, why = order2_git_ok(repo, f_set, ledger.canonical_line(ref))
        if not ok_git:
            reasons.append(why)
    tc = {"ok": not reasons, "ref_1b_seq": ref["seq"], "head": snap["head"], "f_set": f_set, "refs": refs,
          "worktree_heads": heads, "reason": "。".join(reasons) if reasons else None}
    ledger.check_order2_timing_shape(tc, "時機の条件の確かめ")
    return tc, {"graft_file": graft, "shallow": shallow}


def order2_timing_now(repo, records, ref, label="順番2"):
    """参照を読み、すぐに時機の条件を計算する（read_refs_now と timing_from_refs を続けて行う）。書く仕組みは使わない
    （T-091 から、参照を読む → bundle を照らす → 計算する、の順にした）。テストと、手元で確かめるために残す。"""
    return timing_from_refs(repo, records, ref, read_refs_now(repo, label))


def find_order2_code(repo, head, d1b):
    """参照する順番1b の記録（中身 d1b）が縛る src/stats/counting.py の版を、git の履歴から sha256 で探す（作業ツリーの
    ファイルは使わない）。探す場所：順番1b の記録の head の版、head から辿れる、そのパスを変えた commit の版（新しい順）。
    返り値: (見つかった commit, バイト列) か (None, None)。"""
    rel = ledger.COUNTING_SCRIPT
    sha = {f["path"]: f["sha256"] for f in d1b["files"]}.get(rel)
    cands = []
    if _git_ok(repo, "cat-file", "-e", d1b["head"] + "^{commit}"):
        cands.append(d1b["head"])
    if _git_ok(repo, "cat-file", "-e", head + "^{commit}"):
        cands += _rgit(repo, "rev-list", head, "--", rel).decode().split()
    for c in cands:
        if not _git_ok(repo, "cat-file", "-e", "%s:%s" % (c, rel)):
            continue
        data = _rgit(repo, "show", "%s:%s" % (c, rel))
        if ledger.sha256_hex(data) == sha:
            return c, data
    return None, None


def check_order2_git(repo, data, records, rec, doc, base, read_json):
    """順番2の記録の、git を使う照合（T-078）。書く仕組み（seal_records.check_new。base は HEAD）と verify（base は記録を
    最初に含んだコミット）が呼ぶ。
      - head の commit があり、その版の sealed/ledger.jsonl がこの記録を足す直前の記録（先頭 seq−1 行）と同じ。
        head が base の祖先（か同じ）。manifest_sha256 が head の版の二つのマニフェストの sha256（無いか空なら null）。
      - コードの版：find_order2_code を head で計算し直し、code.found・code.commit と同じ（(c) を書いたのに版が履歴に
        ある記録、版が無いのに decide() を流したと書く記録を止める）。
      - 時機の条件：計算の前の確かめ（timing_guards・refs/replace/）に当たっていなければ、記録した refs と worktree_heads
        から F の集合と親を計算し直して f_set と照らし（order2_f_set）、git の条件と ledger の条件から ok を計算し直して
        timing_check.ok と照らす。記録した参照や f_set の commit の一部がこのリポジトリに無い（push していない参照など）
        ときも飛ばさない（差し戻し1回目 中-1）：手元にある参照から計算した F が記録の f_set に含まれること、手元にある
        f_set の commit の親とマニフェストの行、手元の commit だけで時機の条件が破れていれば ok が False であることを照らし、
        残りを照らさなかったことを返す（bundle で照らす。手順書16章）。
    違えば LedgerError。返り値: 照らさなかったことの説明の一覧。"""
    what = "seq %d の %s（順番2）" % (rec["seq"], ledger.ORDER2_KIND)
    head = doc["head"]
    if not _git_ok(repo, "cat-file", "-e", head + "^{commit}"):
        raise ledger.LedgerError("%s の head %s の commit が、このリポジトリに無い" % (what, head[:12]))
    if _version_or_empty(repo, head, LEDGER_REL) != ledger.prefix_bytes(data, rec["seq"] - 1):
        raise ledger.LedgerError("%s の head %s の版の sealed/ledger.jsonl が、この記録を足す直前の記録（先頭 %d 行）と"
                                 "一致しない" % (what, head[:12], rec["seq"] - 1))
    if base != head and not _git_ok(repo, "merge-base", "--is-ancestor", head, base):
        raise ledger.LedgerError("%s の head %s が、%s の祖先でない" % (what, head[:12], base[:12]))
    want = {}
    for mode, rel in ledger.GKG_MANIFESTS.items():
        body = _version_or_empty(repo, head, rel)
        want[mode] = ledger.sha256_hex(body) if body else None
    if doc["manifest_sha256"] != want:
        raise ledger.LedgerError("%s の manifest_sha256 が、head %s の版の二つのマニフェストの sha256 と違う" % (what, head[:12]))
    ref = ledger.order2_ref_1b(records, rec["seq"])
    d1b = read_json(ref, ledger.ORDER1B_KIND)
    commit, _code = find_order2_code(repo, head, d1b)
    code = doc["code"]
    if (commit is not None) != code["found"] or commit != code["commit"]:
        if commit is not None and doc["stop_kind"] == "c":
            raise ledger.LedgerError("%s は (c)（コードの sha256 が合わない）で止まった記録なのに、順番1b の記録が縛る %s の版が"
                                     "git の履歴（commit %s）にある。版が履歴にあれば (c) は成り立たない"
                                     % (what, ledger.COUNTING_SCRIPT, commit[:12]))
        raise ledger.LedgerError("%s の code（found %r・commit %r）が、git の履歴から探し直した結果（%r）と違う"
                                 % (what, code["found"], code["commit"], commit))
    return check_timing_git(repo, records, ref, doc["timing_check"], doc["timing_guards"], what, rec["seq"], "順番2")


def check_timing_git(repo, records, ref, tc, g, what, seq, label):
    """時機の条件の記録（timing_check・timing_guards）を git から計算し直して照らす（T-078 の check_order2_git から、T-090 で
    順番3と共通にするために分けた。中身は変えていない）。ref は参照する順番1b の記録、label は「順番2」か「順番3」。
    計算の前の確かめに当たっていなければ、記録した refs と worktree_heads から F の集合と親を計算し直して f_set と照らし、
    git の条件と ledger の条件から ok を計算し直して timing_check.ok と照らす。手元に無い参照・commit があるときは部分照合
    （check_order2_git の注記）。違えば LedgerError。返り値: 照らさなかったことの説明の一覧。"""
    notes = []
    if g["graft_file"] or g["shallow"] or any(x["ref"].startswith(ledger.REPLACE_REF_PREFIX) for x in tc["refs"]):
        return notes                       # 計算の前の確かめで止まった記録（ok が False であることは ledger が照らす）
    starts = sorted({x["commit"] for x in tc["refs"]} | set(tc["worktree_heads"]))
    present = [c for c in starts if _git_ok(repo, "cat-file", "-e", c)]
    missing = [c for c in starts if c not in present]
    recorded = sorted(tc["f_set"], key=lambda x: x["commit"])
    by_commit = {c["commit"]: c for c in recorded}
    # T-078 差し戻し1回目 中-1：手元に無い参照があっても、計算し直しを飛ばさない。手元にある参照の commit から辿った F は、
    # 記録の f_set に（同じ親で）含まれなければならない。参照が全部手元にあれば、ちょうど同じでなければならない
    f = order2_f_set(repo, present)
    if missing:
        for c in f:
            if by_commit.get(c["commit"]) != c:
                raise ledger.LedgerError("%s：手元にある参照から計算した F の commit %s が、記録の timing_check.f_set に（同じ親で）"
                                         "無い" % (what, c["commit"][:12]))
    elif f != recorded:
        raise ledger.LedgerError("%s の timing_check.f_set が、記録した refs・worktree_heads から計算し直した F の集合と親と違う"
                                 % what)
    # 記録の f_set のうち手元にある commit（と、その親がすべて手元にあるもの）は、親が git と同じで、マニフェストに行がある
    local, partial = [], bool(missing)
    for c in recorded:
        if not _git_ok(repo, "cat-file", "-e", c["commit"] + "^{commit}"):
            partial = True
            continue
        actual = _rgit(repo, "rev-parse", c["commit"] + "^@").decode().split()
        if actual != c["parents"] or not any(_has_rows(repo, c["commit"], p) for p in ORDER2_MANIFEST_PATHS):
            raise ledger.LedgerError("%s の timing_check.f_set の commit %s の親が git と違うか、その版のマニフェストに行が無い"
                                     % (what, c["commit"][:12]))
        if not all(_git_ok(repo, "cat-file", "-e", p + "^{commit}") for p in c["parents"]):
            partial = True
            continue
        local.append(c)
    ok_git, _why = order2_git_ok(repo, local, ledger.canonical_line(ref))
    want = ok_git and ledger.order2_ledger_timing_ok(records, ref["seq"])
    if not partial:
        if want != tc["ok"]:
            raise ledger.LedgerError("%s の timing_check.ok %r が、記録した f_set と sealed/ledger.jsonl から計算し直した時機の"
                                     "条件 %r と違う" % (what, tc["ok"], want))
        return notes
    if tc["ok"] and not want:
        raise ledger.LedgerError("%s の timing_check.ok が True なのに、手元にある f_set の commit で時機の条件が破れている"
                                 "（%s）" % (what, _why or "順番1b が最初の method-access より後"))
    notes.append("seq %d の%sの時機の条件の計算し直しの一部（記録した参照・worktree の HEAD・f_set の commit のうち、この"
                 "リポジトリに無いものがある。手元にあるものだけで照らし、記録と食い違わなかった。残りは記録の bundle で照らす）"
                 % (seq, label))
    return notes


def run_order2_decide(code, code_sha, trial_manifest, official_manifest, stores, tmp, what):
    """封印した版の counting.py（code。sha256 が code_sha）の decide() を、そのファイルだけを置いた空のフォルダ（_BoundDir）
    で、-I・-B・空の pycache_prefix の Python で流す（`counting.py apply <試し> <正式> <試しの置き場所> <正式の置き場所>`）。
    マニフェストはバイト列を一時のファイルに書いて渡す（空なら EMPTY）。stores は {mode: 置き場所の絶対パス}。
    置き場所は、一時のフォルダの決まった名前のリンク（store-trial・store-official）を通し、流すフォルダからの相対パス
    （../store-trial など）で渡す。decide() の止まった理由の文に置き場所のパスが入るので、記録に手元の絶対パス（利用者の名前や
    ボリュームの名前）を入れず、どこに置いても同じ文になるようにするため。
    日の集計を開くのは、この中で流す decide() だけである。返り値: decide() の出力（dict）。
    終了コードが 0・1・3 でない、出力が JSON でない、status と終了コードが合わない、なら LedgerError。"""
    tmp = tempfile.mkdtemp(prefix="decide-", dir=tmp)
    bound = _BoundDir(None, None, [(ledger.COUNTING_SCRIPT, code_sha)], tmp, what, blobs={ledger.COUNTING_SCRIPT: code})
    for mode in ("trial", "official"):
        os.symlink(stores[mode], os.path.join(tmp, "store-" + mode))
    args = ["apply"]
    for name, body in (("trial", trial_manifest), ("official", official_manifest)):
        if not body:
            args.append("EMPTY")
            continue
        fd, path = tempfile.mkstemp(prefix="manifest-%s-" % name, dir=tmp)
        with os.fdopen(fd, "wb") as f:
            f.write(body)
        args.append(path)
    args += ["../store-trial", "../store-official"]
    with tempfile.TemporaryDirectory(dir=tmp) as pycache:
        try:
            r = subprocess.run(python_command(ledger.COUNTING_SCRIPT, pycache) + args, cwd=bound.dir,
                               capture_output=True, env=_child_env(), timeout=RUN_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            raise ledger.LedgerError("%s：decide() が %s 秒の上限の中に終わらなかった" % (what, RUN_TIMEOUT_SECONDS)) from None
        except OSError as e:
            raise ledger.LedgerError("%s：Python を起動できない（%s）" % (what, e.__class__.__name__)) from None
    try:
        out = json.loads(r.stdout.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise ledger.LedgerError("%s：封印した版の counting.py の出力が JSON でない（終了コード %d）" % (what, r.returncode)) from None
    if not isinstance(out, dict) or ORDER2_EXIT_STATUS.get(r.returncode) != out.get("status"):
        raise ledger.LedgerError("%s：封印した版の counting.py の終了コード %d と出力の status %r が合わない"
                                 % (what, r.returncode, out.get("status") if isinstance(out, dict) else None))
    return out


def _rerun_order2(st, repo, r, doc, trial, official, day_dirs):
    """--day-files の置き場所に、決まった記録の3日のファイルがあれば、封印した版の decide() を流し直して counting_output と
    照らす。返り値: 照らしたか（照らさなかった理由の文字列か True）。"""
    out = doc.get("counting_output")
    if out is None or out["status"] != "decided":
        return "決まった記録だけを流し直す（止まった記録は、そのときの置き場所の状態を再現できない）"
    names = [x["file_name"] for x in out["inputs"]]
    store = next((d for d in day_dirs if all(os.path.isfile(os.path.join(d, n)) for n in names)), None)
    if store is None:
        return "--day-files の置き場所に、3日のファイルがそろっていない"
    d1b = st.file_json(ledger.order2_ref_1b(st.records, r["seq"]), ledger.ORDER1B_KIND)
    _c, code = find_order2_code(repo, doc["head"], d1b)
    with tempfile.TemporaryDirectory() as tmp:
        empty = tempfile.mkdtemp(prefix="empty-store-", dir=tmp)
        stores = {"trial": empty, "official": empty}
        stores[doc["input_run"]["mode"]] = os.path.abspath(store)
        got = run_order2_decide(code, doc["code"]["sha256"], trial, official, stores, tmp,
                                "seq %d の順番2の流し直し" % r["seq"])
    if got != out:
        raise ledger.LedgerError("seq %d の順番2：--day-files の3日のファイルで、封印した版の decide() を流し直した出力が、記録の "
                                 "counting_output と違う" % r["seq"])
    return True


def check_order2_plans(st, records, day_dirs=()):
    """順番2の記録ごとに、記録を最初に含んだコミットのマニフェストから R と decide() の行き先（ledger.order2_plan）を
    計算し直し、記録の trial_result・stop_kind・input_run と照らす（T-073 差し戻し2回目 2。ledger.check_order2_plan）。
    T-078：ledger_head、counting_output.runs・inputs（check_order2_plan の中）、時機の条件とコードの版（check_order2_git）も
    照らし、--day-files で3日のファイルを渡せば、決まった記録の decide() を流し直す。
    git の履歴が無いとき・浅い clone のときは「照らさなかった」。食い違えば LedgerError。"""
    repo = Repo(st.root)
    why = None
    try:
        repo.git("rev-parse", "--git-dir")
    except (ledger.LedgerError, OSError):
        why = "git の履歴が無い"
    if why is None and not _not_shallow(repo):
        why = "浅い clone"
    commits = None
    for r in records:
        doc = st.file_json(r, ledger.ORDER2_KIND)
        ledger.check_ledger_head(st.data, r, doc)          # T-078
        run = doc["input_run"]
        desc = "input_run なし（段に進む前に止まる）" if run is None else "input_run %s・%s" % (run["mode"], run["run_id"])
        print("  %s seq %d（順番2）: stop_kind %s、%s、trial_result は seq %d（R の gkg-run-result。この記録より前）"
              % (ledger.ORDER2_KIND, r["seq"], doc["stop_kind"] or "null", desc, doc["trial_result"]["seq"]))
        print("    status %s、参照する順番1b は seq %d、時機の条件 %s、コードの版 %s（%s）"
              % (doc["status"], doc["ref_1b_seq"], "満たす" if doc["timing_check"]["ok"] else
                 "満たさない（%s）" % doc["timing_check"]["reason"],
                 "履歴にある" if doc["code"]["found"] else "履歴に無い", doc["code"]["sha256"]))
        if why is not None:
            st.unchecked.append("seq %d の順番2の行き先の計算し直し（%s）" % (r["seq"], why))
            print("照らさなかった：%s なので、seq %d の順番2の行き先をマニフェストから計算し直していない" % (why, r["seq"]))
            st.unchecked.append("seq %d の順番2の時機の条件とコードの版の計算し直し（%s）" % (r["seq"], why))
            continue
        if commits is None:
            commits = repo.commit_for_seq(st.data, partial=True)
        c = commits.get(r["seq"])
        if c is None:
            # T-074（T-073 の監査 軽-3）：記録を最初に含んだコミットが無いので、照らす版が決まらない。失敗にせず
            # 「照らさなかった」にする（コミットしたあとで流せば照らす）
            st.unchecked.append("seq %d の順番2の行き先の計算し直し（記録がまだコミットされていない）" % r["seq"])
            print("照らさなかった：記録がまだコミットされていないので、seq %d の順番2の行き先をマニフェストから計算し直して"
                  "いない（コミットしたあとで照らす）" % r["seq"])
            continue
        trial = _version_or_empty(repo, c, ledger.GKG_MANIFESTS["trial"])
        official = _version_or_empty(repo, c, ledger.GKG_MANIFESTS["official"])
        plan = ledger.check_order2_plan(st.records, r, doc, st.file_json, trial, official)
        print("    記録を最初に含んだコミット %s のマニフェストから計算し直した行き先（%s）と R は、記録と同じ。試しの run の"
              "マニフェストの全体は R の gkg-run-result が縛るバイト列と同じ"
              % (c[:12], plan["action"] if plan["action"] != "stage" else "%s の段" % plan["mode"]))
        notes = check_order2_git(repo, st.data, st.records, r, doc, c, st.file_json)
        print("    head %s の版の記録、コードの版、時機の条件（F の集合 %d 件と親、ok %s）を git から計算し直した。記録と同じ"
              % (doc["head"][:12], len(doc["timing_check"]["f_set"]), doc["timing_check"]["ok"]))
        for n in notes:
            st.unchecked.append(n)
            print("照らさなかった：%s" % n)
        if doc.get("counting_output") is not None:
            done = _rerun_order2(st, repo, r, doc, trial, official, day_dirs) if day_dirs else \
                "--day-files で3日のファイルの置き場所を渡したときだけ流し直す"
            if done is True:
                print("    --day-files の3日のファイルで、封印した版の decide() を流し直した出力は、記録の counting_output と同じ")
            else:
                st.unchecked.append("seq %d の順番2の decide() の流し直し（%s）" % (r["seq"], done))
                print("照らさなかった：seq %d の順番2の decide() の流し直し（%s）" % (r["seq"], done))


# ---- T-090：順番3（数え方とのつながり）の試みの記録と順番3の記録の、git を使う照合と、封印した版の order3_gate() の流し方

# 封印した版の counting.py を読み込み、attempt_from_record と order3_gate を流す小さなプログラム（-I・-B・空の pycache_prefix。
# 流すフォルダには counting.py だけを置く。_BoundDir）。入力は JSON のファイル（ledger.order3_gate_inputs の形）。
# order3_gate() が ValueError で止めたとき（つじつまの合わない入力）は {"ok": false, "error": …} を出す
ORDER3_GATE_RUNNER = r"""
import importlib.util, json, os, sys
root, src = sys.argv[1], sys.argv[2]
spec = importlib.util.spec_from_file_location("counting_sealed", os.path.join(root, "src", "stats", "counting.py"))
c = importlib.util.module_from_spec(spec)
spec.loader.exec_module(c)
with open(src, "rb") as f:
    d = json.loads(f.read().decode("utf-8"))
try:
    atts = [c.attempt_from_record(a["seq"], a["gate"]) for a in d["attempts"]]
    g = c.order3_gate(d["order1b_seqs"], d["order2_records"], d["timing_check"], atts)
    out = {"ok": True, "record": g["record"]}
except ValueError as e:
    out = {"ok": False, "error": str(e)}
sys.stdout.buffer.write(json.dumps(out, ensure_ascii=True, sort_keys=True).encode("ascii"))
"""


def run_order3_gate(code, code_sha, inputs, tmp, what):
    """封印した版の counting.py（code。sha256 が code_sha）の order3_gate() を、そのファイルだけを置いた空のフォルダで、
    -I・-B・空の pycache_prefix の Python で流す（ORDER3_GATE_RUNNER）。inputs は ledger.order3_gate_inputs の形。
    返り値: order3_gate() の record（ledger に書く gate の部分。キーは5個）。
    order3_gate() が ValueError で止めた（つじつまの合わない入力）、出力が読めない、0 以外で終わる、なら LedgerError。
    Python を起動できなければ Unchecked。"""
    tmp = tempfile.mkdtemp(prefix="order3-gate-", dir=tmp)
    bound = _BoundDir(None, None, [(ledger.COUNTING_SCRIPT, code_sha)], tmp, what, blobs={ledger.COUNTING_SCRIPT: code})
    fd, path = tempfile.mkstemp(prefix="order3-inputs-", dir=tmp)
    with os.fdopen(fd, "wb") as f:
        f.write(json.dumps(inputs, ensure_ascii=True, sort_keys=True).encode("ascii"))
    out = _run_script(bound.dir, ledger.COUNTING_SCRIPT, what, code=ORDER3_GATE_RUNNER, args=(bound.dir, path))
    try:
        d = json.loads(out.decode("ascii"))
        ok = d["ok"]
        if ok is True:
            return d["record"]
        err = d["error"] if ok is False else None
    except (UnicodeDecodeError, ValueError, KeyError, TypeError):
        err = None
    if isinstance(err, str):
        raise Order3InputRejected(err)
    raise ledger.LedgerError("%s：封印した版の order3_gate() の出力を読めない" % what)


class Order3InputRejected(ledger.LedgerError):
    """封印した版の order3_gate() が、ValueError（つじつまの合わない入力）で止めた。中身は ValueError の文。T-091：書く仕組みは
    これを halt（cause "input"）の試みとして記録する（seal-order1.md 185行「試み＝関門のコードを一回動かすこと」）。"""


def order3_input_halt_reason(error):
    """halt（input）の reason の文（書く仕組みと、計算し直しの照合が同じ文を使う）。"""
    return "封印した版の order3_gate() が、つじつまの合わない入力として止めた（ValueError: %s）" % error


def _check_record_head(repo, data, rec, head, base, what):
    """head の commit があり、その版の sealed/ledger.jsonl がこの記録を足す直前の記録（先頭 seq−1 行）と同じで、head が
    base の祖先（か同じ）であること。"""
    if not _git_ok(repo, "cat-file", "-e", head + "^{commit}"):
        raise ledger.LedgerError("%s の head %s の commit が、このリポジトリに無い" % (what, head[:12]))
    if _version_or_empty(repo, head, LEDGER_REL) != ledger.prefix_bytes(data, rec["seq"] - 1):
        raise ledger.LedgerError("%s の head %s の版の sealed/ledger.jsonl が、この記録を足す直前の記録（先頭 %d 行）と"
                                 "一致しない" % (what, head[:12], rec["seq"] - 1))
    if base != head and not _git_ok(repo, "merge-base", "--is-ancestor", head, base):
        raise ledger.LedgerError("%s の head %s が、%s の祖先でない" % (what, head[:12], base[:12]))


def check_order3_git(repo, data, records, rec, doc, base, read_json):
    """順番3の試みの記録・順番3の記録の、git を使う照合（T-090）。書く仕組み（seal_records.check_new。base は HEAD）と
    verify（base は記録を最初に含んだコミット）が呼ぶ。
      - どちらも：head の commit があり、その版の記録がこの記録を足す直前の記録と同じで、head が base の祖先。
      - 試み：コードの版（find_order2_code を head で計算し直し、code.found・code.commit と同じ）。時機の条件の計算し直し
        （check_timing_git。順番2と同じ関数。部分照合を含む）。順番1b の記録が無い試みは、F を数えない（ledger が
        ok は false・f_set は空を照らす）。
      - 順番3の記録：reading の sha256 が、head の版の ORDER3_READING_DOC のバイト列の sha256 と同じ。
    違えば LedgerError。返り値: 照らさなかったことの説明の一覧。"""
    if rec["kind"] == ledger.ORDER3_KIND:
        what = "seq %d の %s（順番3）" % (rec["seq"], ledger.ORDER3_KIND)
        _check_record_head(repo, data, rec, doc["head"], base, what)
        rel = ledger.ORDER3_READING_DOC
        if not _git_ok(repo, "cat-file", "-e", "%s:%s" % (doc["head"], rel)):
            raise ledger.LedgerError("%s の head %s の版に %s が無い" % (what, doc["head"][:12], rel))
        if ledger.sha256_hex(_rgit(repo, "show", "%s:%s" % (doc["head"], rel))) != doc["reading"]["sha256"]:
            raise ledger.LedgerError("%s の reading.sha256 が、head %s の版の %s の sha256 と違う" % (what, doc["head"][:12], rel))
        return []
    what = "seq %d の %s（順番3の試み）" % (rec["seq"], ledger.ORDER3_ATTEMPT_KIND)
    head = doc["head"]
    _check_record_head(repo, data, rec, head, base, what)
    ref = ledger.order2_ref_1b(records, rec["seq"])
    commit = None
    if ref is not None:
        commit, _code = find_order2_code(repo, head, read_json(ref, ledger.ORDER1B_KIND))
    code = doc["code"]
    if (commit is not None) != code["found"] or commit != code["commit"]:
        raise ledger.LedgerError("%s の code（found %r・commit %r）が、git の履歴から探し直した結果（%r）と違う"
                                 % (what, code["found"], code["commit"], commit))
    if ref is None or doc["timing_check"] is None:
        return []                          # 1b が無い試み（F を数えない）と halt（bundle。F と ok を計算していない）
    return check_timing_git(repo, records, ref, doc["timing_check"], doc["timing_guards"], what, rec["seq"], "順番3")


def recompute_order3_gate(repo, records, rec, doc, read_json, tmp):
    """試みの記録の gate を、封印した版の order3_gate() で計算し直して照らす（T-090）。入力は記録だけから決まる
    （ledger.order3_gate_inputs。前の試みは gate の部分だけを counting.attempt_from_record に渡す）。版は、参照する順番1b の
    記録が縛る sha256 の counting.py を、記録の head から辿れる git の履歴から探したもの（find_order2_code。作業ツリーの版は
    使わない）。halt（bundle・code）の記録は流さない（None を返す）。halt（input）の記録は流し直し、同じ入力で order3_gate() が
    ValueError を出し、その文から作った reason が記録と同じことを確かめる（T-091）。違えば LedgerError。
    返り値: 計算した record か None。"""
    halt = doc["halt"]
    if halt is not None and halt["cause"] != "input":
        return None
    what = "seq %d の順番3の試みの関門の計算し直し" % rec["seq"]
    ref = ledger.order2_ref_1b(records, rec["seq"])
    d1b = read_json(ref, ledger.ORDER1B_KIND)
    commit, code = find_order2_code(repo, doc["head"], d1b)
    if commit is None:
        raise ledger.LedgerError("%s：参照する順番1b の記録が縛る %s の版が、git の履歴に無い" % (what, ledger.COUNTING_SCRIPT))
    inputs = ledger.order3_gate_inputs(records, rec["seq"], doc["timing_check"], read_json)
    try:
        got = run_order3_gate(code, doc["code"]["sha256"], inputs, tmp, what)
    except Order3InputRejected as e:
        if halt is not None and order3_input_halt_reason(str(e)) == halt["reason"]:
            return None
        raise ledger.LedgerError("seq %d の順番3の試み：封印した版の order3_gate() を記録から計算し直すと、入力を受け付けない"
                                 "（ValueError: %s）。記録の %s と合わない" % (rec["seq"], e, "halt の reason" if halt else "gate"))
    if halt is not None:
        raise ledger.LedgerError("seq %d の順番3の試みは halt（input）なのに、封印した版の order3_gate() を記録から計算し直すと"
                                 "入力を受け付ける" % rec["seq"])
    if got != doc["gate"]:
        raise ledger.LedgerError("seq %d の順番3の試みの gate が、封印した版の order3_gate() を記録から計算し直した結果と違う"
                                 "（計算し直した may_seal %r、reason %r、chosen_order2_seq %r）"
                                 % (rec["seq"], got.get("may_seal"), got.get("reason"), got.get("chosen_order2_seq")))
    return got


def check_order3_entries(st, attempts, order3):
    """順番3の試みの記録と順番3の記録ごとに、ledger_head を照らし、行を出す。git の履歴があれば、記録を最初に含んだ
    コミットを base にして check_order3_git と recompute_order3_gate で計算し直す。git の履歴が無いとき・浅い clone の
    とき・まだコミットされていないときは「照らさなかった」（T-090）。食い違えば LedgerError。"""
    repo = Repo(st.root)
    why = None
    try:
        repo.git("rev-parse", "--git-dir")
    except (ledger.LedgerError, OSError):
        why = "git の履歴が無い"
    if why is None and not _not_shallow(repo):
        why = "浅い clone"
    commits = None
    for r in sorted(attempts + order3, key=lambda x: x["seq"]):
        doc = st.file_json(r, r["kind"])
        ledger.check_ledger_head(st.data, r, doc)
        if r["kind"] == ledger.ORDER3_ATTEMPT_KIND:
            g, h = doc["gate"], doc["halt"]
            if g is not None:
                res = "通った（順番2の記録 seq %d を参照）" % g["chosen_order2_seq"] if g["may_seal"] else \
                    "止まった（%s）" % g["reason"]
            else:
                res = "関門の結果を出さずに止まった（%s：%s）" % (h["cause"], h["reason"])
            tc = doc["timing_check"]
            print("  %s seq %d（順番3の試み）: %s、参照する順番1b は %s、時機の条件 %s、コードの版 %s"
                  % (r["kind"], r["seq"], res, "無し" if doc["ref_1b"] is None else "seq %d" % doc["ref_1b"]["seq"],
                     "計算していない（bundle の list-heads が読んだ参照と合わない）" if tc is None else
                     "満たす" if tc["ok"] else "満たさない（%s）" % tc["reason"],
                     "履歴にある" if doc["code"]["found"] else "履歴に無い"))
        else:
            print("  %s seq %d（順番3）: 試み seq %d、順番1b seq %d、順番2 seq %d、順番1 %s、正式な数え方 %s（%s）、%s の sha256 %s"
                  % (r["kind"], r["seq"], doc["attempt"]["seq"], doc["ref_1b"]["seq"], doc["ref_order2"]["seq"],
                     "無し" if doc["ref_order1"] is None else "seq %d" % doc["ref_order1"]["seq"],
                     doc["counting"]["official_candidate"], doc["counting"]["official_status"], doc["reading"]["path"],
                     doc["reading"]["sha256"]))
        if why is not None:
            st.unchecked.append("seq %d の順番3の記録の git からの計算し直し（%s）" % (r["seq"], why))
            print("照らさなかった：%s なので、seq %d の時機の条件・コードの版・関門を git から計算し直していない" % (why, r["seq"]))
            continue
        if commits is None:
            commits = repo.commit_for_seq(st.data, partial=True)
        c = commits.get(r["seq"])
        if c is None:
            st.unchecked.append("seq %d の順番3の記録の git からの計算し直し（記録がまだコミットされていない）" % r["seq"])
            print("照らさなかった：記録がまだコミットされていないので、seq %d を git から計算し直していない" % r["seq"])
            continue
        notes = check_order3_git(repo, st.data, st.records, r, doc, c, st.file_json)
        for n in notes:
            st.unchecked.append(n)
            print("照らさなかった：%s" % n)
        if r["kind"] == ledger.ORDER3_KIND:
            print("    head %s の版の記録と %s を git から照らした。記録と同じ" % (doc["head"][:12], doc["reading"]["path"]))
            continue
        if doc["timing_check"] is None:
            print("    head %s の版の記録とコードの版を git から照らした。記録と同じ（時機の条件は計算していない記録）"
                  % doc["head"][:12])
        else:
            print("    head %s の版の記録、コードの版、時機の条件（F の集合 %d 件と親、ok %s）を git から計算し直した。記録と同じ"
                  % (doc["head"][:12], len(doc["timing_check"]["f_set"]), doc["timing_check"]["ok"]))
        if doc["gate"] is None and doc["halt"]["cause"] != "input":
            continue
        try:
            with tempfile.TemporaryDirectory() as tmp:
                recompute_order3_gate(repo, st.records, r, doc, st.file_json, tmp)
        except Unchecked as e:
            st.unchecked.append("seq %d の順番3の関門の計算し直し（%s）" % (r["seq"], e))
            print("照らさなかった：seq %d の順番3の関門の計算し直し（%s）" % (r["seq"], e))
            continue
        print("    封印した版の order3_gate()（%s の sha256 %s…）を記録から計算し直した結果は、記録の %s と同じ（流した Python：%s）"
              % (ledger.COUNTING_SCRIPT, doc["code"]["sha256"][:12], "gate" if doc["gate"] is not None else "halt（input）",
                 sys.version.split()[0]))


# ---- T-095：順番4（欠けた日の一覧）の記録の、git を使う照合と、固定した版の一覧のコードの流し方（書く入口と verify が同じ関数を使う）

# 一覧のコードを流す時間の上限（秒）。所要時間の目安は 60〜100分（missing-days-method.md 4章）。超えたら止める（書く入口は何も
# 書かない。verify は記録と合わないとする）
ORDER4_TIMEOUT_SECONDS = 4 * 3600


def order4_tree(repo, commit):
    """commit の版の ledger.ORDER4_TREE_PREFIXES の下のファイルすべて：[(パス, sha256, バイト列)]（パスの順）。
    バイト列は git cat-file blob（filter・textconv を通らない）。普通のファイル（mode 100644・100755）でないもの（リンク・
    submodule）があれば LedgerError。"""
    out = []
    listing = _rgit(repo, "ls-tree", "-r", "-z", "--full-tree", commit, "--", *ledger.ORDER4_TREE_PREFIXES)
    for item in listing.split(b"\0"):
        if not item:
            continue
        meta, _tab, name = item.partition(b"\t")
        mode, typ, obj = meta.decode("ascii").split()
        path = name.decode("utf-8")
        if typ != "blob" or mode not in ("100644", "100755"):
            raise ledger.LedgerError("commit %s の版の %s が普通のファイルでない（mode %s）。順番4の一覧のコードを流すフォルダに"
                                     "置けない" % (commit[:12], path, mode))
        data = _rgit(repo, "cat-file", "blob", obj)
        out.append((path, ledger.sha256_hex(data), data))
    out.sort(key=lambda x: x[0])
    if not out:
        raise ledger.LedgerError("commit %s の版に %s のファイルが無い" % (commit[:12], "・".join(ledger.ORDER4_TREE_PREFIXES)))
    return out


def order4_tree_sha256(tree):
    """tree（order4_tree の返り値）の sha256：各ファイルの「<sha256><空白2つ><パス>\\n」（shasum -a 256 の出力の形）を
    パスの順につないだバイト列の sha256。"""
    return ledger.sha256_hex("".join("%s  %s\n" % (sha, path) for path, sha, _d in tree).encode("utf-8"))


def order4_code(repo, commit, tree):
    """記録の code の欄を、commit の版から作る：script（missing_days.py）・imports（3つ）・docs（文書とテスト）・tree。
    どれかが commit の版に無ければ LedgerError。"""
    by = {p: s for p, s, _d in tree}
    for rel in (ledger.ORDER4_SCRIPT,) + ledger.ORDER4_IMPORTS:
        if rel not in by:
            raise ledger.LedgerError("commit %s の版に %s が無い" % (commit[:12], rel))
    docs = []
    for rel in ledger.ORDER4_DOC_FILES:
        if not _git_ok(repo, "cat-file", "-e", "%s:%s" % (commit, rel)):
            raise ledger.LedgerError("commit %s の版に %s が無い" % (commit[:12], rel))
        docs.append({"path": rel, "sha256": ledger.sha256_hex(_rgit(repo, "cat-file", "blob", "%s:%s" % (commit, rel)))})
    return {"script": {"path": ledger.ORDER4_SCRIPT, "sha256": by[ledger.ORDER4_SCRIPT]},
            "imports": [{"path": rel, "sha256": by[rel]} for rel in ledger.ORDER4_IMPORTS],
            "docs": docs,
            "tree": {"prefixes": list(ledger.ORDER4_TREE_PREFIXES), "files": len(tree), "sha256": order4_tree_sha256(tree)}}


def run_order4(tree, store, tmp, what):
    """tree（order4_tree の返り値。固定した版のファイル）だけを空のフォルダに書き出し（_BoundDir。書いたあとに読み戻して
    sha256 を照らす）、その中の missing_days.py を -I・-B・空の pycache_prefix の Python で `--store <store>` を付けて流す。
    作業ツリーのファイルは使わない。関門（official_day_records・gkg-run-result）は、書き出したフォルダの sealed/ と
    data/manifest/ を読む。store は日の集計の置き場所（絶対パス。記録には入れない）。
    返り値: 標準出力のバイト列（一覧の JSON）。Python を起動できなければ Unchecked。0 以外で終わる・時間の上限を超えたら
    LedgerError（標準エラーの最後の行を添える）。"""
    bound = _BoundDir(None, None, [(p, s) for p, s, _d in tree], tmp, what, blobs={p: d for p, _s, d in tree})
    with tempfile.TemporaryDirectory(dir=tmp) as pycache:
        cmd = [sys.executable, "-I", "-B", "-X", "pycache_prefix=" + pycache, ledger.ORDER4_SCRIPT, "--store", store]
        try:
            r = subprocess.run(cmd, cwd=bound.dir, capture_output=True, env=_child_env(), timeout=ORDER4_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            raise ledger.LedgerError("%s：%s が %d 秒の上限の中に終わらなかった" % (what, ledger.ORDER4_SCRIPT,
                                                                     ORDER4_TIMEOUT_SECONDS)) from None
        except OSError as e:
            raise Unchecked("%s：Python を起動できない（%s）" % (what, e.__class__.__name__)) from None
    if r.returncode != 0:
        last = (r.stderr.decode("utf-8", "replace").strip().splitlines() or [""])[-1][:300]
        raise ledger.LedgerError("%s：固定した版の %s が終了コード %d で終わった（%s）" % (what, ledger.ORDER4_SCRIPT, r.returncode,
                                                                          last))
    return r.stdout


def parse_order4_output(raw, what):
    """一覧のコードの標準出力を JSON として読み、ledger.order4_list_bytes で書き直したバイト列が raw とちょうど同じことを
    確かめる（記録の list から list_sha256 を作り直せるようにするため）。返り値: (一覧, sha256)。"""
    try:
        lst = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise ledger.LedgerError("%s：%s の出力が JSON でない" % (what, ledger.ORDER4_SCRIPT)) from None
    if ledger.order4_list_bytes(lst) != raw:
        raise ledger.LedgerError("%s：%s の出力が、決まった形（UTF-8、sort_keys、indent=2、末尾に改行1つ）でない" % (what, ledger.ORDER4_SCRIPT))
    return lst, ledger.sha256_hex(raw)


def check_order4_git(repo, data, rec, doc, base):
    """順番4の記録の、git を使う照合（書く仕組み（base は HEAD）と verify（base は記録を最初に含んだコミット）が呼ぶ）。
      - head の commit があり、その版の sealed/ledger.jsonl がこの記録を足す直前の記録（先頭 seq−1 行）と同じ。head が base の
        祖先（か同じ）。
      - code（script・imports・docs・tree）を head の版から作り直したものが、記録の code とちょうど同じ（版の固定）。
    違えば LedgerError。返り値: 照らさなかったことの一覧（今は空）。"""
    what = "seq %d の %s（順番4）" % (rec["seq"], ledger.ORDER4_KIND)
    head = doc["head"]
    if not _git_ok(repo, "cat-file", "-e", head + "^{commit}"):
        raise ledger.LedgerError("%s の head %s の commit が、このリポジトリに無い" % (what, head[:12]))
    if _version_or_empty(repo, head, LEDGER_REL) != ledger.prefix_bytes(data, rec["seq"] - 1):
        raise ledger.LedgerError("%s の head %s の版の sealed/ledger.jsonl が、この記録を足す直前の記録（先頭 %d 行）と"
                                 "一致しない" % (what, head[:12], rec["seq"] - 1))
    if base != head and not _git_ok(repo, "merge-base", "--is-ancestor", head, base):
        raise ledger.LedgerError("%s の head %s が、%s の祖先でない" % (what, head[:12], base[:12]))
    got = order4_code(repo, head, order4_tree(repo, head))
    if got != doc["code"]:
        bad = [k for k in ledger.ORDER4_CODE_KEYS if got[k] != doc["code"].get(k)]
        raise ledger.LedgerError("%s の code の %s が、head %s の版のファイルから作り直したものと違う（一覧を作ったコードの版を"
                                 "偽っている）" % (what, "・".join(bad), head[:12]))
    return []


# T-095 差し戻し1回目 中-1：封印済みの candidates.py の day_is_missing を、渡した (日, files_ok, 報道量) に当てる
ORDER4_RULE_RUNNER = r"""
import json, os, sys
sys.path.insert(0, os.path.abspath(os.path.join("src", "stats")))
import candidates
with open(sys.argv[1], encoding="utf-8") as f:
    pairs = json.load(f)
print(json.dumps({"min_present_slots": candidates.MIN_PRESENT_SLOTS, "slots_per_day": candidates.SLOTS_PER_DAY,
                  "missing": {d: candidates.day_is_missing(ok, vol) for d, ok, vol in pairs}}))
"""

# 封印済みの counting.py で、各日の日の集計の C7 の分母を数える。開いたバイト列の sha256 を day の行と照らしてから
# parse_day に渡す（照らす前には何も数えない）。リンクは開かない
ORDER4_COUNT_RUNNER = r"""
import hashlib, json, os, sys
sys.path.insert(0, os.path.abspath(os.path.join("src", "stats")))
import counting
with open(sys.argv[1], encoding="utf-8") as f:
    rows = json.load(f)
store, out = sys.argv[2], {}
for r in rows:
    try:
        fd = os.open(os.path.join(store, r["file_name"]), os.O_RDONLY | os.O_NOFOLLOW)
    except OSError as e:
        print(json.dumps({"error": "open", "day": r["day"], "why": e.__class__.__name__}))
        sys.exit(0)
    with os.fdopen(fd, "rb") as f:
        data = f.read()
    if hashlib.sha256(data).hexdigest() != r["sha256"]:
        print(json.dumps({"error": "sha256", "day": r["day"]}))
        sys.exit(0)
    summary = counting.parse_day(data, expect_day=r["day"], expect_mode=counting.OFFICIAL_MODE)
    out[r["day"]] = counting.candidate_counts(summary, counting.OFFICIAL_CANDIDATE)[1]
    del data, summary
print(json.dumps({"official_candidate": counting.OFFICIAL_CANDIDATE, "denominators": out}))
"""


def order4_sealed_bytes(root, shas):
    """封印済みの版のバイト列 {パス: バイト列}。sha256 で決まるので、出どころは問わない：作業ツリーのファイル（リンクでない
    もの）の sha256 が同じならそれを、違えば git の履歴（HEAD から辿れる、そのパスの版）から探す。無ければ Unchecked。"""
    out, cache = {}, {}
    repo = Repo(root)
    for rel, sha in shas.items():
        path = os.path.join(root, *rel.split("/"))
        data = None
        if os.path.isfile(path) and not os.path.islink(path):
            with open(path, "rb") as f:
                data = f.read()
        if data is None or ledger.sha256_hex(data) != sha:
            data = _find_version(repo, rel, sha, cache) if _git_ok(repo, "rev-parse", "--git-dir") else None
        if data is None:
            raise Unchecked("封印済みの版の %s（sha256 %s…）が、作業ツリーにも git の履歴にも無い" % (rel, sha[:12]))
        out[rel] = data
    return out


def _run_sealed(code_bytes, runner, args, tmp, what, timeout=RUN_TIMEOUT_SECONDS):
    """封印済みの版のファイル（code_bytes：{パス: バイト列}）だけを置いた空のフォルダで、runner を -I・-B・空の
    pycache_prefix の Python で流し、標準出力の JSON を返す。Python を起動できなければ Unchecked。0 以外で終わる・
    時間の上限を超える・出力が JSON でない、なら LedgerError。"""
    bound = _BoundDir(None, None, [(p, ledger.sha256_hex(b)) for p, b in code_bytes.items()], tmp, what, blobs=code_bytes)
    with tempfile.TemporaryDirectory(dir=tmp) as pycache:
        cmd = [sys.executable, "-I", "-B", "-X", "pycache_prefix=" + pycache, "-c", runner] + list(args)
        try:
            r = subprocess.run(cmd, cwd=bound.dir, capture_output=True, env=_child_env(), timeout=timeout)
        except subprocess.TimeoutExpired:
            raise ledger.LedgerError("%s：%d 秒の上限の中に終わらなかった" % (what, timeout)) from None
        except OSError as e:
            raise Unchecked("%s：Python を起動できない（%s）" % (what, e.__class__.__name__)) from None
    if r.returncode != 0:
        last = (r.stderr.decode("utf-8", "replace").strip().splitlines() or [""])[-1][:300]
        raise ledger.LedgerError("%s：封印済みの版が終了コード %d で終わった（%s）" % (what, r.returncode, last))
    try:
        return json.loads(r.stdout.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise ledger.LedgerError("%s：封印済みの版の出力が JSON でない" % what) from None


def _json_arg(tmp, obj):
    fd, path = tempfile.mkstemp(prefix="order4-in-", suffix=".json", dir=tmp)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(obj, f)
    return path


def order4_inputs(root, records, rec, doc, read_json):
    """照らすための入力：(封印済みの版の {パス: sha256}, {日: day の行})。day の行は、正式な run の gkg-run-result が縛る
    マニフェスト（作業ツリーの data/manifest/、リンクでない普通のファイル）の先頭から取る（ledger.order4_day_rows）。"""
    refs = ledger.order4_refs(records, rec["seq"], read_json)
    shas = ledger.order4_sealed_code(refs, read_json)
    gdoc = read_json(refs["gkg_run_result"], ledger.GKG_RESULT_KIND)
    path = os.path.join(root, *gdoc["manifest_path"].split("/"))
    if os.path.islink(path) or not os.path.isfile(path):
        raise ledger.LedgerError("%s が普通のファイルでない" % gdoc["manifest_path"])
    with open(path, "rb") as f:
        body = f.read()
    b = doc["list"]["block"]
    return shas, ledger.order4_day_rows(body, gdoc, ledger._block_days(b["start"], b["end"]))


def check_order4_rules(root, records, rec, doc, read_json, tmp):
    """(1) 72本の条件（日の集計を使わない）：マニフェストの day の行の files_ok に、封印済みの candidates.py の
    day_is_missing(files_ok, 1) を当て、一覧の below_min_files・欠けた日の files_ok・files_listed・partial_days_count と
    照らす（ledger.check_order4_rule_results）。96・72 も封印済みの版の値と照らす。書く仕組み（seal_records.check_new）と
    verify が呼ぶ。違えば LedgerError。封印済みの版が手元に無い・Python を起動できなければ Unchecked。"""
    what = "seq %d の %s（順番4）" % (rec["seq"], ledger.ORDER4_KIND)
    shas, rows = order4_inputs(root, records, rec, doc, read_json)
    code = order4_sealed_bytes(root, {k: shas[k] for k in ("src/stats/candidates.py", "src/stats/periods.py")})
    pairs = [[d, rows[d]["files_ok"], ledger.ORDER4_RULE_VOLUME] for d in sorted(rows)]
    out = _run_sealed(code, ORDER4_RULE_RUNNER, [_json_arg(tmp, pairs)], tmp, what + " の72本の条件の照合")
    lst = doc["list"]
    if (out["slots_per_day"], out["min_present_slots"]) != (lst["rule"]["slots_per_day"], lst["rule"]["min_present_slots"]):
        raise ledger.LedgerError("%s の list.rule の96・72が、封印済みの candidates.py の値と違う" % what)
    ledger.check_order4_rule_results(lst, rows, out["missing"], out["slots_per_day"], what)
    return len(rows)


def recount_order4(root, records, rec, doc, read_json, store, tmp):
    """(2) C7 の分母（verify の --store）：一覧のコード（missing_days.py）は流さない。封印済みの counting.py で、置き場所の
    日の集計を day の行の sha256 と照らしてから C7 の分母を数え直し、封印済みの day_is_missing(files_ok, 分母) で欠けた日を
    決め直して、一覧と照らす（ledger.check_order4_recount）。違えば LedgerError。"""
    what = "seq %d の %s（順番4）" % (rec["seq"], ledger.ORDER4_KIND)
    shas, rows = order4_inputs(root, records, rec, doc, read_json)
    code = order4_sealed_bytes(root, {ledger.COUNTING_SCRIPT: shas[ledger.COUNTING_SCRIPT]})
    want_rows = [{"day": d, "file_name": rows[d]["file_name"], "sha256": rows[d]["sha256"]} for d in sorted(rows)]
    out = _run_sealed(code, ORDER4_COUNT_RUNNER, [_json_arg(tmp, want_rows), store], tmp,
                      what + " の C7 の分母の数え直し", timeout=ORDER4_TIMEOUT_SECONDS)
    if "error" in out:
        raise ledger.LedgerError("%s：置き場所の %s の日の集計が%s" % (what, out.get("day"), "、day の行の sha256 と違う"
                                 if out["error"] == "sha256" else "開けない（%s）" % out.get("why")))
    if out["official_candidate"] != doc["list"]["rule"]["official_candidate"]:
        raise ledger.LedgerError("%s：封印済みの counting.py の正式な候補が、一覧の rule と違う" % what)
    denoms = out["denominators"]
    code2 = order4_sealed_bytes(root, {k: shas[k] for k in ("src/stats/candidates.py", "src/stats/periods.py")})
    pairs = [[d, rows[d]["files_ok"], denoms[d]] for d in sorted(rows)]
    miss = _run_sealed(code2, ORDER4_RULE_RUNNER, [_json_arg(tmp, pairs)], tmp, what + " の欠けた日の決め直し")["missing"]
    ledger.check_order4_recount(doc["list"], denoms, miss, what)
    return len(denoms)


def check_order4_entries(st, recs, store):
    """順番4の記録ごとに、ledger_head を照らし、行を出す（T-095）。
      - git の履歴があれば、記録を最初に含んだコミットを base にして check_order4_git で照らす（コードの版）。git の履歴が
        無いとき・浅い clone のとき・まだコミットされていないときは「照らさなかった」。
      - 72本の条件（check_order4_rules。日の集計を使わない）は、いつも照らす。封印済みの版が手元に無い・Python を起動
        できないときは「照らさなかった」。
      - store（--store）を渡したときだけ、封印済みの counting.py で C7 の分母を数え直して照らす（recount_order4。
        missing_days.py は流さない）。渡さないときは「照らさなかった」。"""
    repo = Repo(st.root)
    why = None
    try:
        repo.git("rev-parse", "--git-dir")
    except (ledger.LedgerError, OSError):
        why = "git の履歴が無い"
    if why is None and not _not_shallow(repo):
        why = "浅い clone"
    commits = None
    for r in recs:
        doc = st.file_json(r, ledger.ORDER4_KIND)
        ledger.check_ledger_head(st.data, r, doc)
        lst = doc["list"]
        print("  %s seq %d（順番4）: 一覧の sha256 %s、%s（%s〜%s）の %d 日のうち欠けた日 %d 日、run_id %s（gkg-run-result seq %d）、"
              "順番3 seq %d、%s の sha256 %s、head %s"
              % (r["kind"], r["seq"], doc["list_sha256"], lst["block"]["name"], lst["block"]["start"], lst["block"]["end"],
                 lst["days_in_block"], lst["missing_count"], lst["input"]["run_id"], doc["refs"]["gkg_run_result"]["seq"],
                 doc["refs"]["order3"]["seq"], ledger.ORDER4_SCRIPT, doc["code"]["script"]["sha256"], doc["head"]))
        c = None
        if why is None:
            if commits is None:
                commits = repo.commit_for_seq(st.data, partial=True)
            c = commits.get(r["seq"])
        if c is None:
            reason = why or "記録がまだコミットされていない"
            st.unchecked.append("seq %d の順番4の記録の git からの照合（%s）" % (r["seq"], reason))
            print("照らさなかった：%s なので、seq %d のコードの版を git から照らしていない" % (reason, r["seq"]))
        else:
            check_order4_git(repo, st.data, r, doc, c)
            print("    head %s の版の記録、%s と照らす3つのファイル・文書とテスト・流すフォルダのファイル %d 件（sha256 %s…）を git から"
                  "照らした。記録と同じ" % (doc["head"][:12], ledger.ORDER4_SCRIPT, doc["code"]["tree"]["files"],
                                      doc["code"]["tree"]["sha256"][:12]))
        try:
            with tempfile.TemporaryDirectory() as tmp:
                n = check_order4_rules(st.root, st.records, r, doc, st.file_json, tmp)
            print("    72本の条件：マニフェストの day の行 %d 日の files_ok に、封印済みの candidates.py の day_is_missing を当てた結果が、"
                  "一覧の below_min_files・欠けた日の files_ok・一部が欠けた日の数と同じ（日の集計は使っていない。流した Python：%s）"
                  % (n, sys.version.split()[0]))
        except Unchecked as e:
            st.unchecked.append("seq %d の順番4の72本の条件の照合（%s）" % (r["seq"], e))
            print("照らさなかった：seq %d の順番4の72本の条件の照合（%s）" % (r["seq"], e))
        if not store:
            st.unchecked.append("seq %d の順番4の C7 の分母の数え直し（日の集計の置き場所 --store を渡していない）" % r["seq"])
            print("照らさなかった：日の集計の置き場所（--store）を渡していないので、seq %d の C7 の分母を数え直していない" % r["seq"])
            continue
        if not os.path.isdir(store):
            raise ledger.LedgerError("--store %s がフォルダでない" % store)
        try:
            with tempfile.TemporaryDirectory() as tmp:
                n = recount_order4(st.root, st.records, r, doc, st.file_json, os.path.realpath(store), tmp)
        except Unchecked as e:
            st.unchecked.append("seq %d の順番4の C7 の分母の数え直し（%s）" % (r["seq"], e))
            print("照らさなかった：seq %d の順番4の C7 の分母の数え直し（%s）" % (r["seq"], e))
            continue
        print("    C7 の分母：封印済みの counting.py で、日の集計 %d 個（day の行の sha256 と照らしてから開いた）の C7 の分母を数え直した。"
              "一覧の分母と欠けた日と同じ（%s は流していない。流した Python：%s）" % (n, ledger.ORDER4_SCRIPT, sys.version.split()[0]))


# ---- T-111：順番5（タグの一覧の結果）の試みと記録の、git を使う照合と、order5.py に頼らない計算し直し

# order5.py を流す時間の上限と、計算し直しの時間の上限（秒）。見込みはどちらも2〜4時間（order5-tag-list.md 7章）
ORDER5_TIMEOUT_SECONDS = 8 * 3600
ORDER5_RECOMPUTE = os.path.join(HERE, "order5_recompute.py")


def order5_code(repo, commit, tree, sealed):
    """順番5の試み・記録の code の欄を、commit の版から作る：script（order5.py）・docs（文書とテスト）・tree（order4_tree と同じ
    取り出し方の sha256）・sealed（封印済みのコードの名前と sha256。記録から決まる値）。"""
    by = {p: s for p, s, _d in tree}
    if ledger.ORDER5_SCRIPT not in by:
        raise ledger.LedgerError("commit %s の版に %s が無い" % (commit[:12], ledger.ORDER5_SCRIPT))
    docs = []
    for rel in ledger.ORDER5_DOC_FILES:
        if not _git_ok(repo, "cat-file", "-e", "%s:%s" % (commit, rel)):
            raise ledger.LedgerError("commit %s の版に %s が無い" % (commit[:12], rel))
        docs.append({"path": rel, "sha256": ledger.sha256_hex(_rgit(repo, "cat-file", "blob", "%s:%s" % (commit, rel)))})
    return {"script": {"path": ledger.ORDER5_SCRIPT, "sha256": by[ledger.ORDER5_SCRIPT]}, "docs": docs,
            "tree": {"prefixes": list(ledger.ORDER4_TREE_PREFIXES), "files": len(tree), "sha256": order4_tree_sha256(tree)},
            "sealed": [{"name": n, "sha256": sealed[n]} for n, _k, _f in ledger.ORDER5_SEALED]}


def check_order5_git(repo, data, records, rec, doc, base, read_json):
    """順番5の試み・記録の、git を使う照合（書く仕組み（base は HEAD）と verify（base は記録を最初に含んだコミット））：
    head の commit があり、その版の sealed/ledger.jsonl がこの記録を足す直前の記録と同じ、head が base の祖先、code を head の
    版から作り直したものが記録と同じ。違えば LedgerError。"""
    what = "seq %d の %s" % (rec["seq"], rec["kind"])
    head = doc["head"]
    if not _git_ok(repo, "cat-file", "-e", head + "^{commit}"):
        raise ledger.LedgerError("%s の head %s の commit が、このリポジトリに無い" % (what, head[:12]))
    if _version_or_empty(repo, head, LEDGER_REL) != ledger.prefix_bytes(data, rec["seq"] - 1):
        raise ledger.LedgerError("%s の head %s の版の sealed/ledger.jsonl が、この記録を足す直前の記録（先頭 %d 行）と"
                                 "一致しない" % (what, head[:12], rec["seq"] - 1))
    if base != head and not _git_ok(repo, "merge-base", "--is-ancestor", head, base):
        raise ledger.LedgerError("%s の head %s が、%s の祖先でない" % (what, head[:12], base[:12]))
    got = order5_code(repo, head, order4_tree(repo, head), ledger.order5_sealed_code(records, read_json))
    if got != doc["code"]:
        raise ledger.LedgerError("%s の code が、head %s の版のファイルから作り直したものと違う（順番5を流したコードの版を"
                                 "偽っている）" % (what, head[:12]))
    return []


def run_order5(tree, store, themes_store, out_dir, repo_root, tmp, what):
    """tree（固定した版のファイル）だけを空のフォルダに書き出し、その中の order5.py を -I・-B・空の pycache_prefix の Python で
    流す（--store・--themes-store・--out-dir・--repo）。返り値：終了コード（0 できた、3 C7 で止まった）。それ以外は
    LedgerError（標準エラーの最後の行を添える）。Python を起動できなければ Unchecked。"""
    bound = _BoundDir(None, None, [(p, s) for p, s, _d in tree], tmp, what, blobs={p: d for p, _s, d in tree})
    with tempfile.TemporaryDirectory(dir=tmp) as pycache:
        cmd = [sys.executable, "-I", "-B", "-X", "pycache_prefix=" + pycache, ledger.ORDER5_SCRIPT, "--store", store,
               "--themes-store", themes_store, "--out-dir", out_dir, "--repo", repo_root]
        try:
            r = subprocess.run(cmd, cwd=bound.dir, capture_output=True, env=_child_env(), timeout=ORDER5_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            raise ledger.LedgerError("%s：%s が %d 秒の上限の中に終わらなかった" % (what, ledger.ORDER5_SCRIPT,
                                                                     ORDER5_TIMEOUT_SECONDS)) from None
        except OSError as e:
            raise Unchecked("%s：Python を起動できない（%s）" % (what, e.__class__.__name__)) from None
    if r.returncode not in (0, 3):
        last = (r.stderr.decode("utf-8", "replace").strip().splitlines() or [""])[-1][:300]
        raise ledger.LedgerError("%s：固定した版の %s が終了コード %d で終わった（%s）" % (what, ledger.ORDER5_SCRIPT, r.returncode,
                                                                          last))
    return r.returncode


def order5_themes_row(root):
    """計算し直しに渡す区分表の result の行（themes_result_row と同じ）。テストが差し替える。"""
    return themes_result_row(root)


def themes_result_row(root):
    """区分表のマニフェストの最後の result の行（区分表のファイルの名前・sha256・行数）。無ければ LedgerError。
    行の形と並びと履歴は、stats-order の照合（check_themes_manifest_refs と追記だけの照合）が照らす。"""
    path = os.path.join(root, ledger.THEMES_MANIFEST)
    if os.path.islink(path) or not os.path.isfile(path):
        raise ledger.LedgerError("%s が無い" % ledger.THEMES_MANIFEST)
    with open(path, "rb") as f:
        rows = [json.loads(x) for x in f.read().split(b"\n") if x.strip()]
    if not rows or rows[-1].get("kind") != "result":
        raise ledger.LedgerError("%s の最後の行が result でない（区分表を取得していない）" % ledger.THEMES_MANIFEST)
    return rows[-1]


def check_order5_inputs(root, records, rec, doc, read_json):
    """main の input.day_files_digest と themes_table の file_name・sha256・rows・kept_columns・headerless を、日の集計を使わずに
    照らす（T-111 差し戻し1回目 中-1。order5-tag-list.md 5章 (4)）：digest は seq 12 が縛るマニフェストの day の行から、
    themes_table は区分表のマニフェストの最後の result の行から。書く仕組みと verify が呼ぶ。違えば LedgerError。"""
    what = "seq %d の %s（順番5）" % (rec["seq"], ledger.ORDER5_KIND)
    refs = ledger.order5_refs(records, rec["seq"], read_json)
    gdoc = read_json([r for r in records if r["seq"] == refs["gkg_run_result"]["seq"]][0], ledger.GKG_RESULT_KIND)
    with open(os.path.join(root, *gdoc["manifest_path"].split("/")), "rb") as f:
        body = f.read()
    b = doc["main"]["block"]
    rows = ledger.order4_day_rows(body, gdoc, ledger._block_days(b["start"], b["end"]))
    digest = ledger.sha256_hex("".join("%s\t%s\t%s\n" % (d, rows[d]["file_name"], rows[d]["sha256"])
                                       for d in sorted(rows)).encode("ascii"))
    if (doc["main"].get("input") or {}).get("day_files_digest") != digest:
        raise ledger.LedgerError("%s の main.input.day_files_digest が、マニフェストの day の行から決まる値と違う" % what)
    r = themes_result_row(root)
    tt = doc["main"].get("themes_table") or {}
    bad = [k for k in ("file_name", "sha256", "rows", "kept_columns", "headerless") if tt.get(k) != r.get(k)]
    if bad or tt.get("description_column") is not False:
        raise ledger.LedgerError("%s の main.themes_table の %s が、区分表のマニフェストの result の行と違う"
                                 % (what, "・".join(bad) or "description_column"))
    return digest


def order5_day_rows(root, gdoc, block):
    """計算し直しに渡す day の行（seq 12 が縛るマニフェストの先頭から。ledger.order4_day_rows）。テストが差し替える。"""
    with open(os.path.join(root, *gdoc["manifest_path"].split("/")), "rb") as f:
        body = f.read()
    return ledger.order4_day_rows(body, gdoc, ledger._block_days(block["start"], block["end"]))


def recompute_order5(root, records, rec, doc, read_json, store, themes_store, tmp, detail_bytes=None):
    """順番5の記録の main を、order5.py に頼らずに計算し直して照らす（order5-tag-list.md 5章。tags-naive.md 428行）。
      - 封印済みのコード（ledger.order5_sealed_code の sha256。periods・exclusion・tagrules・counting は作業ツリーか git の
        履歴から、1cb463a の版は git から）と、この verify の order5_recompute.py だけを空のフォルダに置いて流す。
      - 入力：seq 12 が縛るマニフェストの day の行（ledger.order4_day_rows）、seq 15 の欠けた日、区分表のマニフェストの
        result の行のファイル（themes_store の下。sha256 を照らす）、日の集計（store の下。sha256 を照らしてから開く）。
      - 照らすもの：status、区分表の数、C1〜C7 の要約、正式な一覧（themes を除いた値と tag_count・reason_counts）、二つの比較、
        欄の手厚さ（order5_recompute.compare_with_main）。
    違えば LedgerError。封印済みの版が手元に無い・Python を起動できなければ Unchecked。返り値：開いた日の集計の数。"""
    what = "seq %d の %s（順番5）の計算し直し" % (rec["seq"], ledger.ORDER5_KIND)
    refs = ledger.order5_refs(records, rec["seq"], read_json)
    sealed = ledger.order5_sealed_code(records, read_json)
    gdoc = read_json([r for r in records if r["seq"] == refs["gkg_run_result"]["seq"]][0], ledger.GKG_RESULT_KIND)
    b = doc["main"]["block"]
    rows = order5_day_rows(root, gdoc, b)
    o4 = [r for r in records if r["seq"] == refs["order4"]["seq"]][0]
    missing = sorted(m["day"] for m in read_json(o4, ledger.ORDER4_KIND)["list"]["missing_days"])
    trow = order5_themes_row(root)
    tpath = os.path.join(themes_store, trow["file_name"])
    if os.path.islink(tpath) or not os.path.isfile(tpath):
        raise ledger.LedgerError("%s：区分表のファイル %s が置き場所に無い" % (what, trow["file_name"]))
    code = order4_sealed_bytes(root, {k: sealed[k] for k in ("src/stats/periods.py", "src/stats/exclusion.py",
                                                             "src/stats/tagrules.py", "src/stats/counting.py")})
    repo = Repo(root)
    if not _git_ok(repo, "cat-file", "-e", "%s:src/stats/tagrules.py" % ledger.ORDER5_1CB463A_COMMIT):
        raise Unchecked("1cb463a の版の tagrules.py が git に無い")
    v1 = _rgit(repo, "cat-file", "blob", "%s:src/stats/tagrules.py" % ledger.ORDER5_1CB463A_COMMIT)
    if ledger.sha256_hex(v1) != sealed["1cb463a:src/stats/tagrules.py"]:
        raise ledger.LedgerError("%s：1cb463a の版の tagrules.py の sha256 が、stats-order1 の値と違う" % what)
    with open(ORDER5_RECOMPUTE, "rb") as f:
        runner = f.read()
    code.update({"v1cb463a/tagrules.py": v1, "order5_recompute.py": runner})
    inp = {"block": [b["start"], b["end"]], "missing_days": missing,
           "rows": [{"day": d, "file_name": rows[d]["file_name"], "sha256": rows[d]["sha256"]} for d in sorted(rows)],
           "themes_sha256": trow["sha256"], "themes_rows": trow["rows"]}
    bound = _BoundDir(None, None, [(p, ledger.sha256_hex(x)) for p, x in code.items()], tmp, what, blobs=code)
    with tempfile.TemporaryDirectory(dir=tmp) as pycache:
        cmd = [sys.executable, "-I", "-B", "-X", "pycache_prefix=" + pycache, "order5_recompute.py", bound.dir,
               _json_arg(tmp, inp), store, tpath]
        try:
            r = subprocess.run(cmd, cwd=bound.dir, capture_output=True, env=_child_env(), timeout=ORDER5_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            raise ledger.LedgerError("%s：%d 秒の上限の中に終わらなかった" % (what, ORDER5_TIMEOUT_SECONDS)) from None
        except OSError as e:
            raise Unchecked("%s：Python を起動できない（%s）" % (what, e.__class__.__name__)) from None
    if r.returncode != 0:
        last = (r.stderr.decode("utf-8", "replace").strip().splitlines() or [""])[-1][:300]
        raise ledger.LedgerError("%s：計算し直しが終了コード %d で終わった（%s）" % (what, r.returncode, last))
    got = json.loads(r.stdout.decode("utf-8"))
    import importlib.util
    spec = importlib.util.spec_from_file_location("order5_recompute_for_verify", ORDER5_RECOMPUTE)
    rc = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rc)
    bad = rc.compare_with_main(doc["main"], got)
    if bad:
        raise ledger.LedgerError("%s：main の値が、封印済みのコードで計算し直した値と違う（%s）" % (what, "、".join(bad[:10])))
    detail_checked = False
    if detail_bytes is not None and doc["status"] == "ok":
        # T-111 差し戻し1回目 中-2：Git の外の detail の中身も、計算し直した値と照らす。T-111 差し戻し2回目 軽-2：sha256 を
        # 照らしたのと同じバイト列（check_order5_outside が一度だけ読んだもの）を使う
        detail = json.loads(detail_bytes.decode("utf-8"))
        bad = rc.compare_with_detail(detail, got, ledger.ORDER5_LABEL, ledger.ORDER5_DETAIL_NOTE, ledger.ORDER5_CITATION)
        if bad:
            raise ledger.LedgerError("%s：detail の値が、封印済みのコードで計算し直した値と違う（%s）" % (what, "、".join(bad[:10])))
        detail_checked = True
    return len(rows), detail_checked


def check_order5_outside(doc, outside_dir, what):
    """Git の外の detail・extra のファイルが outside_dir にあれば、一度だけ読んで sha256 を記録の outside と照らす（リンクは
    開かない）。返り値：(照らしたファイルの名前の一覧, 無かったものの一覧, {part: 読んだバイト列})。照らしたバイト列は、
    detail の中身の照合（recompute_order5 の detail_bytes）にそのまま渡す（T-111 差し戻し2回目 軽-2）。違えば LedgerError。"""
    done, absent, blobs = [], [], {}
    for part in ("detail", "extra"):
        v = doc["outside"][part]
        path = os.path.join(outside_dir, v["file_name"])
        try:
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        except OSError:
            absent.append(v["file_name"])
            continue
        with os.fdopen(fd, "rb") as f:
            data = f.read()
        if ledger.sha256_hex(data) != v["sha256"]:
            raise ledger.LedgerError("%s：%s の sha256 が、記録の outside.%s と違う" % (what, v["file_name"], part))
        done.append(v["file_name"])
        blobs[part] = data
    return done, absent, blobs


def check_order5_entries(st, attempts, recs, store, themes_store, outside_dir):
    """順番5の試みと記録ごとに、ledger_head を照らし、行を出す（T-111）。git の照合（check_order5_git）。順番5の記録は、
    --store と --themes-store を渡したときだけ計算し直す（recompute_order5）。--order5-outside を渡したときだけ detail・extra の
    sha256 を照らす。渡さないとき・git の履歴が無いときは「照らさなかった」。"""
    repo = Repo(st.root)
    why = None
    try:
        repo.git("rev-parse", "--git-dir")
    except (ledger.LedgerError, OSError):
        why = "git の履歴が無い"
    if why is None and not _not_shallow(repo):
        why = "浅い clone"
    commits = None
    for r in sorted(attempts + recs, key=lambda x: x["seq"]):
        doc = st.file_json(r, r["kind"])
        ledger.check_ledger_head(st.data, r, doc)
        if r["kind"] == ledger.ORDER5_ATTEMPT_KIND:
            print("  %s seq %d（順番5の試み）: head %s、%s の sha256 %s" % (r["kind"], r["seq"], doc["head"], ledger.ORDER5_SCRIPT,
                                                                   doc["code"]["script"]["sha256"]))
        else:
            print("  %s seq %d（順番5）: status %s、main の sha256 %s、試み seq %d、順番4 seq %d、正式な一覧 %s 件"
                  % (r["kind"], r["seq"], doc["status"], doc["main_sha256"], doc["attempt"]["seq"], doc["refs"]["order4"]["seq"],
                     ((doc["main"].get("official") or {}).get("result") or {}).get("tag_count", "—")))
        c = None
        if why is None:
            if commits is None:
                commits = repo.commit_for_seq(st.data, partial=True)
            c = commits.get(r["seq"])
        if c is None:
            reason = why or "記録がまだコミットされていない"
            st.unchecked.append("seq %d の順番5の記録の git からの照合（%s）" % (r["seq"], reason))
            print("照らさなかった：%s なので、seq %d のコードの版を git から照らしていない" % (reason, r["seq"]))
        else:
            check_order5_git(repo, st.data, st.records, r, doc, c, st.file_json)
            print("    head %s の版の記録と、%s・文書とテスト・流すフォルダのファイル %d 件を git から照らした。記録と同じ"
                  % (doc["head"][:12], ledger.ORDER5_SCRIPT, doc["code"]["tree"]["files"]))
        if r["kind"] != ledger.ORDER5_KIND:
            continue
        check_order5_inputs(st.root, st.records, r, doc, st.file_json)        # T-111 差し戻し1回目 中-1
        print("    main の input.day_files_digest と themes_table の file_name・sha256・rows は、マニフェストから決まる値と同じ")
        detail_checked = False
        blobs, done, absent = {}, [], []
        if doc["status"] == "ok" and outside_dir:
            done, absent, blobs = check_order5_outside(doc, outside_dir, "seq %d の順番5" % r["seq"])
        if not (store and themes_store):
            st.unchecked.append("seq %d の順番5の一覧と要約の計算し直し（--store と --themes-store を渡していない）" % r["seq"])
            print("照らさなかった：日の集計と区分表の置き場所（--store・--themes-store）を渡していないので、seq %d の一覧と要約を"
                  "計算し直していない" % r["seq"])
        else:
            for p in (store, themes_store):
                if not os.path.isdir(p):
                    raise ledger.LedgerError("置き場所 %s がフォルダでない" % p)
            try:
                with tempfile.TemporaryDirectory() as tmp:
                    n, detail_checked = recompute_order5(st.root, st.records, r, doc, st.file_json, os.path.realpath(store),
                                                         os.path.realpath(themes_store), tmp,
                                                         detail_bytes=blobs.get("detail"))
                print("    封印済みの tagrules.py・counting.py で、日の集計 %d 個と区分表から、正式な一覧と要約を計算し直した。main と"
                      "同じ（order5.py は流していない。流した Python：%s）" % (n, sys.version.split()[0]))
                if detail_checked:
                    print("    Git の外の detail の中身（official_result・allset_result・versions.1cb463a・candidate_lists）も、"
                          "計算し直した値と同じ")
            except Unchecked as e:
                st.unchecked.append("seq %d の順番5の計算し直し（%s）" % (r["seq"], e))
                print("照らさなかった：seq %d の順番5の計算し直し（%s）" % (r["seq"], e))
        if doc["status"] != "ok":
            continue
        if not outside_dir:
            st.unchecked.append("seq %d の順番5の Git の外のファイル（detail・extra）の sha256（--order5-outside を渡していない）"
                                % r["seq"])
            print("照らさなかった：Git の外のファイルの置き場所（--order5-outside）を渡していないので、detail・extra の sha256 を"
                  "照らしていない")
            continue
        if done:
            print("    Git の外のファイル %s の sha256 は、記録の outside と同じ" % "・".join(done))
        if "order5-detail.json" in done and not detail_checked:
            st.unchecked.append("seq %d の順番5の detail の中身の計算し直し（--store と --themes-store を渡していない）" % r["seq"])
            print("照らさなかった：detail の中身は、--store と --themes-store も渡したときだけ計算し直して照らす")
        for a_ in absent:
            st.unchecked.append("seq %d の順番5の %s の sha256（置き場所に無い）" % (r["seq"], a_))
            print("照らさなかった：%s が置き場所に無い" % a_)


# ---- T-144：順番6〜8 と採点計画（stats-order6-8）の git を使う照合と流し直し

ORDER68_TIMEOUT_SECONDS = 2 * 3600
ORDER68_TREE_PREFIXES = ("data/manifest/", "sealed/")
ORDER68_ROW_RE = re.compile(r"\A\| *([^|（]+?) *(?:（[^|]*）)? *\|")
ORDER68_SUB_RE = re.compile(r"\A### \((\w+)\)")
STATS_PATH_RE = re.compile(r"\Asrc/stats/[A-Za-z0-9_]+\.py\Z")


def _blob(repo, commit, rel):
    """commit の版の rel のバイト列（無ければ None）。filter・textconv を通らない。"""
    if not _git_ok(repo, "cat-file", "-e", "%s:%s" % (commit, rel)):
        return None
    return _rgit(repo, "cat-file", "blob", "%s:%s" % (commit, rel))


def order68_last_change(repo, head, paths):
    """head の履歴で、paths のどれかを最後に変えたコミットの40桁。"""
    c = _rgit(repo, "log", "-1", "--format=%H", head, "--", *paths).decode("ascii").strip()
    if not ledger.HEX40.match(c):
        raise ledger.LedgerError("head %s の履歴に %s を変えたコミットが無い" % (head[:12], "・".join(paths)))
    return c


def order68_list_rows(text):
    """一覧の文書（seal-order6-8.md）の4章の表の行：[(節, パス, sha256, コミットか None)]。節は "4(1)" などの形。コミットの欄が
    40桁でない行（T-147 より前の「この文書と同じコミット」）は None（check_order68_git が止める）。sha256 の欄が無い行（見出しの
    行など）は数えない。"""
    rows, sec, in4 = [], None, False
    for line in text.split("\n"):
        if line.startswith("## "):
            in4 = line.startswith("## 4.")
            sec = None
            continue
        m = ORDER68_SUB_RE.match(line)
        if in4 and m:
            sec = "4(%s)" % m.group(1)
            continue
        if not (in4 and sec and line.startswith("|")):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        shas = [c for c in cells if ledger.HEX64.match(c)]
        if not shas:
            continue
        if len(shas) != 1:
            raise ledger.LedgerError("一覧の文書の4章の行に、sha256 が %d 個ある: %s" % (len(shas), line[:80]))
        path = cells[0].split("（", 1)[0].strip().strip("`")
        last = cells[-1]
        rows.append((sec, path, shas[0], last if ledger.HEX40.match(last) else None))
    return rows


def order68_targets_at(repo, head):
    """head の版の封印の対象：[{section, path, sha256, commit}]（ORDER68_TARGETS の並び。commit は head の履歴でそのファイルを
    最後に変えたコミット）。無いファイルがあれば LedgerError。"""
    out = []
    for sec, path in ledger.ORDER68_TARGETS:
        data = _blob(repo, head, path)
        if data is None:
            raise ledger.LedgerError("head %s の版に %s が無い" % (head[:12], path))
        out.append({"section": sec, "path": path, "sha256": ledger.sha256_hex(data),
                    "commit": order68_last_change(repo, head, [path])})
    return out


def order68_list_doc_at(repo, head):
    data = _blob(repo, head, ledger.ORDER68_LIST_DOC)
    if data is None:
        raise ledger.LedgerError("head %s の版に %s が無い" % (head[:12], ledger.ORDER68_LIST_DOC))
    return {"path": ledger.ORDER68_LIST_DOC, "sha256": ledger.sha256_hex(data),
            "commit": order68_last_change(repo, head, [ledger.ORDER68_LIST_DOC])}, data


def _decision_ok(text, heading, lines):
    """text（行の一覧）で、heading がちょうど1行、lines の各行がちょうど1行あり、その前で最も近い「## 」の見出しが heading。"""
    if text is None or sum(1 for x in text if x == heading) != 1:
        return False
    for line in lines:
        idx = [i for i, x in enumerate(text) if x == line]
        if len(idx) != 1:
            return False
        heads = [x for x in text[:idx[0]] if x.startswith("## ")]
        if not heads or heads[-1] != heading:
            return False
    return True


def check_order68_decisions(repo, head, what):
    """オーナーの決定の出どころ（ledger.ORDER68_DECISIONS）を git で照らす：そのコミットが head の祖先で、その版で行と見出しが
    決まった形にあり（_decision_ok）、第一の親の版ではそうなっていない（その行を入れたコミット）。head の版にも同じ形で残って
    いる（reviews は書き換えない）。違えば LedgerError。"""
    def lines_of(c, path):
        b = _blob(repo, c, path)
        return None if b is None else b.decode("utf-8").split("\n")
    for item, commit, path, heading, lines in ledger.ORDER68_DECISIONS:
        where = "%s の オーナーの決定「%s」（%s:%s）" % (what, item, commit[:12], path)
        if not _git_ok(repo, "merge-base", "--is-ancestor", commit, head):
            raise ledger.LedgerError("%s：コミットが head %s の祖先でない" % (where, head[:12]))
        if not _decision_ok(lines_of(commit, path), heading, lines):
            raise ledger.LedgerError("%s：その版に、見出しの下の決まった行が無い" % where)
        parent = _rgit(repo, "rev-parse", "--verify", commit + "^1").decode("ascii").strip()
        if _decision_ok(lines_of(parent, path), heading, lines):
            raise ledger.LedgerError("%s：第一の親の版にも同じ行がある（その行を入れたコミットでない）" % where)
        if not _decision_ok(lines_of(head, path), heading, lines):
            raise ledger.LedgerError("%s：head %s の版で、見出しの下の決まった行が変わった" % (where, head[:12]))


def stats_import_closure(blobs, script):
    """script（src/stats/ の .py）が使う src/stats/ のコードを、ast でたどった閉包（パスの昇順。script を含む）。
    blobs は {パス: バイト列}（src/stats/ の .py）。たどるもの：import の名前が src/stats/<名前>.py にあるもの（標準ライブラリは
    たどらない）と、文字列の定数がちょうど "src/stats/<名前>.py" の形のもの（explore_islands の _load_verified がパスで読み込む
    periods.py・candidates.py・counting.py・scoring.py・naive.py と、order8_fit の command_output が流す periods.py など）。
    __import__・importlib を使うものがあれば LedgerError（静的にたどれないため）。"""
    import ast
    seen, todo = set(), [script]
    while todo:
        p = todo.pop()
        if p in seen:
            continue
        if p not in blobs:
            raise ledger.LedgerError("%s が無い（import をたどれない）" % p)
        seen.add(p)
        tree = ast.parse(blobs[p].decode("utf-8"), filename=p)
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name.split(".")[0] for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
                names = [node.module.split(".")[0]]
            elif isinstance(node, ast.Constant) and isinstance(node.value, str) and STATS_PATH_RE.match(node.value):
                if node.value in blobs:
                    todo.append(node.value)
            elif isinstance(node, ast.Name) and node.id == "__import__" or \
                    isinstance(node, ast.Attribute) and node.attr == "import_module":
                raise ledger.LedgerError("%s が __import__ か import_module を使う（import を静的にたどれない）" % p)
            for n in names:
                q = "src/stats/%s.py" % n
                if q in blobs:
                    todo.append(q)
    return sorted(seen)


def order68_bound_shas(doc):
    """流すコードとして使ってよいファイルの {パス: sha256}：記録の targets（.py）と sealed_code。同じパスで値が違えば
    LedgerError（ledger.check_order68_doc も照らす）。"""
    out = {}
    for x in [t for t in doc["targets"] if t["path"].endswith(".py")] + list(doc["sealed_code"]):
        if out.setdefault(x["path"], x["sha256"]) != x["sha256"]:
            raise ledger.LedgerError("%s の sha256 が、targets と sealed_code で違う" % x["path"])
    return out


def order68_code_files(repo, commit, script, bound, what):
    """commit の版の src/stats/ の .py から、script の import の閉包を作り、どれもが bound（封印した sha256）と同じことを確かめる。
    返り値：[(パス, sha256, バイト列)]。封印していないファイルを使う・sha256 が違うなら LedgerError。"""
    listing = _rgit(repo, "ls-tree", "-r", "-z", "--full-tree", "--name-only", commit, "--", "src/stats/").split(b"\0")
    blobs = {}
    for name in listing:
        p = name.decode("utf-8")
        if p.endswith(".py") and p.count("/") == 2:
            blobs[p] = _rgit(repo, "cat-file", "blob", "%s:%s" % (commit, p))
    out = []
    for p in stats_import_closure(blobs, script):
        s = ledger.sha256_hex(blobs[p])
        if bound.get(p) != s:
            raise ledger.LedgerError("%s：%s が import する %s（commit %s の版。sha256 %s）は、この記録で封印したコード（targets・"
                                     "sealed_code）でない" % (what, script, p, commit[:12], s[:12]))
        out.append((p, s, blobs[p]))
    return out


def _run_bound(bound_dir, script, args, what, timeout, runner=True):
    """bound_dir の中の script を -I・-B・空の pycache_prefix の Python で、args を付けて流す。返り値：標準出力。0 以外で終われば
    LedgerError、Python を起動できなければ Unchecked。runner が真なら RUNNER（スクリプトのフォルダを sys.path の先頭に戻す。
    naive.py・scoring.py は同じフォルダのモジュールを読み込むが、自分では sys.path に足さない）を通す。偽なら、スクリプトの
    パスをそのまま渡す（キャッシュが要るスクリプトは自分でフォルダを足し、multiprocessing の子が __main__ をパスから読み直す）。"""
    with tempfile.TemporaryDirectory() as pycache:
        head = [sys.executable, "-I", "-B", "-X", "pycache_prefix=" + pycache]
        cmd = head + (["-c", RUNNER, script] if runner else [script]) + list(args)
        try:
            r = subprocess.run(cmd, cwd=bound_dir, capture_output=True, env=_child_env(), timeout=timeout)
        except subprocess.TimeoutExpired:
            raise ledger.LedgerError("%s：%s が %d 秒の上限の中に終わらなかった" % (what, script, timeout)) from None
        except OSError as e:
            raise Unchecked("%s：Python を起動できない（%s）" % (what, e.__class__.__name__)) from None
    if r.returncode != 0:
        last = (r.stderr.decode("utf-8", "replace").strip().splitlines() or [""])[-1][:300]
        raise ledger.LedgerError("%s：封印したコードの %s が終了コード %d で終わった（%s）" % (what, script, r.returncode, last))
    return r.stdout


def run_order68_data_free(repo, head, doc, tmp, what):
    """データを使わない出力（ledger.ORDER68_DATA_FREE。順番7の periods.py の出力、naive.py・scoring.py の出力）を、封印した
    コードだけを置いた空のフォルダで流し直し、標準出力の sha256 が記録（targets の出力の値）と同じことを確かめる。違えば
    LedgerError。返り値：流した数。"""
    bound = order68_bound_shas(doc)
    for x in doc["data_free"]:
        files = order68_code_files(repo, head, x["script"], bound, what)
        b = _BoundDir(None, None, [(p, s) for p, s, _d in files], tmp, what, blobs={p: d for p, _s, d in files})
        out = _run_bound(b.dir, x["script"], x["args"], what, RUN_TIMEOUT_SECONDS)
        if ledger.sha256_hex(out) != x["sha256"]:
            raise ledger.LedgerError("%s：%s %s を流し直した出力の sha256 %s が、記録の %s（%s）と違う"
                                     % (what, x["script"], " ".join(x["args"]), ledger.sha256_hex(out)[:12], x["output"],
                                        x["sha256"][:12]))
    return len(doc["data_free"])


def check_order7_output(repo, head, records, doc, read_json, what):
    """順番7の出力（periods-order7.json）の rebuild_triggers が順番7の値で、deadline_status が before_deadline で、ほかのキーが
    periods の1件目の出力と同じ（区画・予言日の範囲・過去分・エンバーゴが変わらない＝区切りの作り直しが要らない）。"""
    raw = _blob(repo, head, ledger.ORDER7_OUTPUT)
    try:
        out = json.loads(raw.decode("utf-8"))
    except (AttributeError, UnicodeDecodeError, ValueError):
        raise ledger.LedgerError("%s：%s が JSON でない" % (what, ledger.ORDER7_OUTPUT)) from None
    first = read_json(ledger._first_of_kind(records, ledger.PERIODS_KIND), "output")
    if out.get("rebuild_triggers") != ledger.ORDER7_TRIGGERS or out.get("deadline_status") != "before_deadline":
        raise ledger.LedgerError("%s：%s の rebuild_triggers・deadline_status が、順番7の値 %s と before_deadline でない"
                                 % (what, ledger.ORDER7_OUTPUT, json.dumps(ledger.ORDER7_TRIGGERS, sort_keys=True)))
    rest = sorted(set(out) | set(first))
    diff = [k for k in rest if k not in ("rebuild_triggers", "deadline_status") and out.get(k) != first.get(k)]
    if diff or ledger.check_blocks(first, out):
        raise ledger.LedgerError("%s：%s の %s が periods の1件目の出力と違う（区切りが変わる）"
                                 % (what, ledger.ORDER7_OUTPUT, "・".join(diff) or "区画"))


def check_order68_git(repo, data, records, rec, doc, base, read_json, tmp):
    """順番6〜8 の記録の、git を使う照合（書く仕組み（base は HEAD）と verify（base は記録を最初に含んだコミット））：
      - head の commit があり、その版の sealed/ledger.jsonl がこの記録を足す直前の記録と同じ、head が base の祖先。
      - list_doc・targets が head の版から作り直したもの（order68_list_doc_at・order68_targets_at）と同じ。一覧の文書の4章の表の
        行（節・パス・sha256、40桁のコミットの欄）が targets と同じ。
      - オーナーの決定の出どころ（check_order68_decisions）。順番7の出力（check_order7_output）。
      - reruns の commit が、head の履歴でその出力のファイルを最後に変えたコミット。
      - データを使わない出力の流し直し（run_order68_data_free）。
    違えば LedgerError。"""
    what = "seq %d の %s" % (rec["seq"], rec["kind"])
    head = doc["head"]
    if not _git_ok(repo, "cat-file", "-e", head + "^{commit}"):
        raise ledger.LedgerError("%s の head %s の commit が、このリポジトリに無い" % (what, head[:12]))
    if _version_or_empty(repo, head, LEDGER_REL) != ledger.prefix_bytes(data, rec["seq"] - 1):
        raise ledger.LedgerError("%s の head %s の版の sealed/ledger.jsonl が、この記録を足す直前の記録（先頭 %d 行）と"
                                 "一致しない" % (what, head[:12], rec["seq"] - 1))
    if base != head and not _git_ok(repo, "merge-base", "--is-ancestor", head, base):
        raise ledger.LedgerError("%s の head %s が、%s の祖先でない" % (what, head[:12], base[:12]))
    ld, text = order68_list_doc_at(repo, head)
    if ld != doc["list_doc"]:
        raise ledger.LedgerError("%s の list_doc が、head %s の版の %s（sha256 と最後に変えたコミット）と違う"
                                 % (what, head[:12], ledger.ORDER68_LIST_DOC))
    tg = order68_targets_at(repo, head)
    if tg != doc["targets"]:
        bad = [t["path"] for t, u in zip(tg, doc["targets"]) if t != u]
        raise ledger.LedgerError("%s の targets が、head %s の版のファイル（sha256 と最後に変えたコミット）と違う（%s）"
                                 % (what, head[:12], "・".join(bad[:3])))
    rows = order68_list_rows(text.decode("utf-8"))
    if [(s, p, h) for s, p, h, _c in rows] != [(t["section"], t["path"], t["sha256"]) for t in tg]:
        raise ledger.LedgerError("%s：一覧の文書 %s の4章の表（節・パス・sha256）が、封印する対象と同じでない（行が足りない・多い・"
                                 "値が違う）" % (what, ledger.ORDER68_LIST_DOC))
    for (_s, p, _h, c), t in zip(rows, tg):
        # T-148：統計係が T-147（67f6b32）で、すべての行の「最後に変えたコミット」を40桁にした。40桁でない行（以前の
        # 「この文書と同じコミット」）は、照らせないので止める
        if c is None:
            raise ledger.LedgerError("%s：一覧の文書の %s の行の「最後に変えたコミット」の欄が40桁でない（照らせない）" % (what, p))
        if c != t["commit"]:
            raise ledger.LedgerError("%s：一覧の文書の %s のコミット %s が、最後に変えたコミット %s と違う" % (what, p, c[:12], t["commit"][:12]))
    check_order68_decisions(repo, head, what)
    check_order7_output(repo, head, records, doc, read_json, what)
    for x, (script, out_dir, names, _extra) in zip(doc["reruns"], ledger.ORDER68_RERUNS):
        c = order68_last_change(repo, head, ["%s/%s" % (out_dir, n) for n in names])
        if x["commit"] != c:
            raise ledger.LedgerError("%s の reruns の %s の commit が、head の履歴で %s のファイルを最後に変えたコミット %s と違う"
                                     % (what, script, out_dir, c[:12]))
    check_order68_code_lists(repo, head, doc, what)
    run_order68_data_free(repo, head, doc, tmp, what)
    return []


# 出力の中に、計算に使ったコードの sha256 の一覧を持つもの：(スクリプト, 出力のパス)。一覧が、そのスクリプトの閉包
# （stats_import_closure）と封印した sha256 にちょうど同じこと
ORDER68_CODE_LISTS = (("src/stats/order8_fit.py", "docs/stats/order8-t145/run.json"),
                      ("src/stats/chain_cap_check.py", "docs/stats/chain-cap-t146/chain_cap.json"))


def check_order68_code_lists(repo, head, doc, what):
    """出力の code の欄（計算に使ったコードの {パス: sha256}）が、head の版でそのスクリプトがたどるコードの閉包と、この記録で
    封印した sha256 にちょうど同じこと（データを使わずに、出力が封印したコードで作られたと名乗っていることを照らす）。"""
    bound = order68_bound_shas(doc)
    for script, rel in ORDER68_CODE_LISTS:
        files = order68_code_files(repo, head, script, bound, what)
        try:
            got = json.loads(_blob(repo, head, rel).decode("utf-8")).get("code")
        except (AttributeError, UnicodeDecodeError, ValueError):
            raise ledger.LedgerError("%s：%s が JSON でない" % (what, rel)) from None
        if got != {p: s_ for p, s_, _d in files}:
            raise ledger.LedgerError("%s：%s の code の欄が、%s がたどるコードと封印した sha256 と違う" % (what, rel, script))


def run_order68_script(bound_dir, script, cache, out_dir, what):
    """手法を作る期間のキャッシュが要るスクリプトを、bound_dir の中で `--t117-cache <cache> --out-dir <out_dir>` を付けて流す。
    テストが差し替える。"""
    _run_bound(bound_dir, script, ["--t117-cache", cache, "--out-dir", out_dir], what, ORDER68_TIMEOUT_SECONDS, runner=False)


def order68_rerun_tree(repo, commit, script, extra, doc, what):
    """流し直すフォルダに置くファイル：commit の版の、script の import の閉包（封印したコードと同じであること）、sealed/ と
    data/manifest/ のすべて、extra（封印した targets と同じであること）。返り値：[(パス, sha256, バイト列)]。"""
    bound = order68_bound_shas(doc)
    files = order68_code_files(repo, commit, script, bound, what)
    tsha = {t["path"]: t["sha256"] for t in doc["targets"]}
    for rel in extra:
        b = _blob(repo, commit, rel)
        if b is None or ledger.sha256_hex(b) != tsha.get(rel):
            raise ledger.LedgerError("%s：commit %s の版の %s が、封印した値と違う" % (what, commit[:12], rel))
        files.append((rel, tsha[rel], b))
    listing = _rgit(repo, "ls-tree", "-r", "-z", "--full-tree", commit, "--", *ORDER68_TREE_PREFIXES)
    for item in listing.split(b"\0"):
        if not item:
            continue
        meta, _tab, name = item.partition(b"\t")
        mode, typ, obj = meta.decode("ascii").split()
        path = name.decode("utf-8")
        if typ != "blob" or mode not in ("100644", "100755"):
            raise ledger.LedgerError("%s：commit %s の版の %s が普通のファイルでない" % (what, commit[:12], path))
        b = _rgit(repo, "cat-file", "blob", obj)
        files.append((path, ledger.sha256_hex(b), b))
    files.sort(key=lambda x: x[0])
    return files


def rerun_order68(repo, doc, cache, tmp, what, memo=None):
    """手法を作る期間のキャッシュが要る出力（ledger.ORDER68_RERUNS）を、記録の reruns の commit の版のファイル（order68_rerun_tree。
    封印したコードと、その時点の sealed/・data/manifest/）だけを置いた空のフォルダで流し直し、出力のファイルのバイト列の sha256 が
    記録と同じことを確かめる。流した Python の版が記録の python と違えば Unchecked（出力に版が入るため）。
    memo（書く入口が使う）：{(スクリプト, commit, キャッシュ): {名前: sha256}}。同じ鍵で流したことがあれば、流さずにその値と
    照らす（同じ実行の中で、試みの前に流した結果を、書く前の照合で使う）。返り値：照らしたスクリプトの数。"""
    if sys.version.split()[0] != doc["python"]:
        raise Unchecked("流し直しの Python %s が、記録の python %s と違う（出力に版が入る）"
                        % (sys.version.split()[0], doc["python"]))
    cache = os.path.realpath(cache)
    if not os.path.isdir(cache):
        raise ledger.LedgerError("キャッシュの置き場所 %s がフォルダでない" % cache)
    for x, (script, _out_dir, names, extra) in zip(doc["reruns"], ledger.ORDER68_RERUNS):
        key = (script, x["commit"], cache)
        got = None if memo is None else memo.get(key)
        if got is None:
            tree = order68_rerun_tree(repo, x["commit"], script, extra, doc, what)
            b = _BoundDir(None, None, [(p, s) for p, s, _d in tree], tmp, what, blobs={p: d for p, _s, d in tree})
            out_dir = tempfile.mkdtemp(prefix="order68-out-", dir=tmp)
            out_dir = os.path.join(out_dir, "out")
            run_order68_script(b.dir, script, cache, out_dir, what)
            got = {}
            for n in names:
                p = os.path.join(out_dir, n)
                if os.path.islink(p) or not os.path.isfile(p):
                    raise ledger.LedgerError("%s：%s を流し直したが、%s が出ていない" % (what, script, n))
                got[n] = ledger.sha256_file(p)
            if memo is not None:
                memo[key] = got
        want = {f["name"]: f["sha256"] for f in x["files"]}
        bad = [n for n in names if got.get(n) != want[n]]
        if bad:
            raise ledger.LedgerError("%s：%s を流し直した出力の %s の sha256 が、記録と違う" % (what, script, "・".join(bad)))
    return len(doc["reruns"])


def check_order68_entries(st, recs, cache):
    """順番6〜8 の記録ごとに、ledger_head を照らし、行を出す（T-144）。git の照合（check_order68_git。データを使わない出力の
    流し直しを含む）。--t117-cache を渡したときだけ、キャッシュが要る出力を流し直す（rerun_order68）。"""
    repo = Repo(st.root)
    why = None
    try:
        repo.git("rev-parse", "--git-dir")
    except (ledger.LedgerError, OSError):
        why = "git の履歴が無い"
    if why is None and not _not_shallow(repo):
        why = "浅い clone"
    commits = None
    for r in recs:
        doc = st.file_json(r, r["kind"])
        ledger.check_ledger_head(st.data, r, doc)
        t = doc["order7"]["triggers"]
        print("  %s seq %d（順番6〜8 と採点計画）: head %s、一覧 %s の sha256 %s、対象 %d 件、オーナーの決定 %d 件、順番7 "
              "naive_history_days %d（periods-triggers seq %d）、区切りの作り直し %s"
              % (r["kind"], r["seq"], doc["head"], doc["list_doc"]["path"], doc["list_doc"]["sha256"], len(doc["targets"]),
                 len(doc["decisions"]), doc["order7"]["naive_history_days"], t["seq"], "要る" if doc["periods"]["rebuild"] else "要らない"))
        c = None
        if why is None:
            if commits is None:
                commits = repo.commit_for_seq(st.data, partial=True)
            c = commits.get(r["seq"])
        if c is None:
            reason = why or "記録がまだコミットされていない"
            st.unchecked.append("seq %d の順番6〜8 の記録の git からの照合（%s）" % (r["seq"], reason))
            print("照らさなかった：%s なので、seq %d の対象のファイルを git から照らしていない" % (reason, r["seq"]))
            continue
        with tempfile.TemporaryDirectory() as tmp:
            check_order68_git(repo, st.data, st.records, r, doc, c, st.file_json, tmp)
        print("    head %s の版の一覧の文書と対象 %d 件の sha256・最後に変えたコミット、オーナーの決定 %d 件の行、順番7の出力を git から"
              "照らした。データを使わない出力 %d 件を封印したコードで流し直した。記録と同じ"
              % (doc["head"][:12], len(doc["targets"]), len(doc["decisions"]), len(doc["data_free"])))
        if not cache:
            st.unchecked.append("seq %d の順番6〜8 の、キャッシュが要る出力（order8_fit.py・tiers_select.py・chain_cap_check.py）の"
                                "流し直し（--t117-cache を渡していない）" % r["seq"])
            print("照らさなかった：手法を作る期間のキャッシュの置き場所（--t117-cache）を渡していないので、seq %d の係数と表を"
                  "流し直していない" % r["seq"])
            continue
        try:
            with tempfile.TemporaryDirectory() as tmp:
                n = rerun_order68(repo, doc, cache, tmp, "seq %d の順番6〜8" % r["seq"])
            print("    手法を作る期間のキャッシュで、%d 個のスクリプト（%s）を封印したコードで流し直した。出力のファイルの sha256 は記録と"
                  "同じ（流した Python：%s）" % (n, "・".join(x["script"] for x in doc["reruns"]), sys.version.split()[0]))
        except Unchecked as e:
            st.unchecked.append("seq %d の順番6〜8 の流し直し（%s）" % (r["seq"], e))
            print("照らさなかった：seq %d の順番6〜8 の流し直し（%s）" % (r["seq"], e))


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
    if got["order2"]:
        check_order2_plans(st, got["order2"], getattr(a, "day_files", None) or ())
    if got["order3_attempt"] or got["order3"]:
        check_order3_entries(st, got["order3_attempt"], got["order3"])          # T-090
    if got["order4"]:
        check_order4_entries(st, got["order4"], getattr(a, "store", None))       # T-095
    if got["order5_attempt"] or got["order5"]:
        check_order5_entries(st, got["order5_attempt"], got["order5"], getattr(a, "store", None),
                             getattr(a, "themes_store", None), getattr(a, "order5_outside", None))   # T-111
    if got["order68"]:
        check_order68_entries(st, got["order68"], getattr(a, "t117_cache", None))                     # T-144
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
    if not _not_shallow(repo):
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
    # T-103（T-099 の監査 重大-1）：マニフェストが追記だけかを git の履歴で照らし、各版にも行の取り決めを当てる。回数は、
    # 履歴に現れた attempt の行の数の最大値。作業ツリーの版も、HEAD の版を先頭に持つこと

    def themes_rules(v):
        ledger.check_themes_manifest_refs(st.records, v)
        return sum(1 for x in v.split(b"\n") if x.strip() and json.loads(x).get("kind") == "attempt")
    n_versions, _counts, longest = check_manifest_append_only(repo, ledger.THEMES_MANIFEST, themes_rules, working=body)
    max_attempts = themes_rules(longest)          # 回数は、鎖の上で最も長い版の attempt の行の数（T-104 軽-4）
    last_kind = None
    for x in longest.split(b"\n"):
        if x.strip():
            last_kind = json.loads(x).get("kind")
    n_code, code_notes = check_themes_attempt_code(repo, body)          # T-102
    for m in code_notes:
        st.unchecked.append(m)
        print("照らさなかった：%s" % m)
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
          "行の形と並び（attempt → fetch → failed か result）は themes.py の取り決めどおり（T-099）。"
          "attempt の行 %d 行の code_sha256 は、その行を初めて含んだコミットの版の themes.py と同じ（T-102・T-104）。"
          "fetch の行 %d 行は、その行を初めて含んだコミットの第一の親の版で、マニフェストが直前の attempt で終わり、themes.py が"
          "同じ版。failed・result の行 %d 行は、直前の fetch と同じコミットで入った（T-104）。"
          % (ledger.THEMES_MANIFEST, n, rows, n_code["attempt"], n_code["fetch"], n_code["failed"] + n_code["result"]))
    print("  追記だけ（T-103・T-104）：%s の commit の版 %d 個（git log --all --reflog --full-history）と HEAD・作業ツリーの版は、"
          "1本の鎖（どの2つも、どちらかがどちらかの先頭部分）になり、どれも行の取り決めに通る。取得の試みの回数（鎖の上で最も長い版の"
          " attempt の行の数）は %d（上限 %d）。最も長い版の最後の行：%s%s"
          % (ledger.THEMES_MANIFEST, n_versions, max_attempts, ledger.THEMES_MAX_ATTEMPTS, last_kind or "無し",
             THEMES_LAST_NOTE.get(last_kind, "")))


THEMES_CODE_REL = "src/collector/themes.py"


# 区分表のマニフェストの最後の行の意味（T-103。T-099 の監査 軽-4）。fetch で終わる形は、通信の途中で止まった形と、結果を
# 書く前に止まった形の区別がつかない。結果の行を書いたあとコミットの前に消した形も、コミットしていなければ同じに見える
THEMES_LAST_NOTE = {
    "attempt": "（試行の行まで。通信はまだ）",
    "fetch": "（通信の直前の行で終わっている。通信の途中で止まったか、結果の行を書く前に止まった。どちらかは記録から分からない）",
    "failed": "（取得は失敗で終わった。上限までなら取り直せる）",
    "result": "（取得は終わった）",
}


def check_manifest_append_only(repo, rel, rules=None, working=None):
    """マニフェスト rel が追記だけであることを、git の履歴で照らす（T-103。T-099 の監査 重大-1。T-104 で鎖の形に改めた）。
      - 版：`git log --all --reflog --full-history --format=%H -- rel` のすべての commit の版（その commit に rel が無ければ空）と、
        HEAD の版と、working（作業ツリーの版。渡したときだけ）。--reflog は、手元で枝を消した commit も見るため（収集係の
        関門と同じ。外すと落ちるテストがある。第三者の clone には運営の reflog は無い）。
      - 集めた版が1本の鎖になること：長さの順に並べて、どの隣り合う2つも、短い方が長い方の先頭部分（どの2つを取っても、
        どちらかがどちらかの先頭部分）。HEAD がほかの参照より遅れているだけ（git fetch のあと、古い commit の checkout）なら
        通る。行を消す・書き換える・並べ替えた版がどこかの参照から辿れれば、鎖が分かれて止まる（あとで行を足し直しても、
        消す前の版と足し直した版のどちらも、もう一方の先頭部分にならない）。
      - どの commit の版も、その親の版を先頭に持つこと（行を消すコミットが無い）。最後の行を消しただけの版は鎖からは外れない
        ので、こちらで見つける。ファイルを消したコミットの版は空として扱うので、ここで止まる。
      - working（作業ツリーの版）を渡したときは、HEAD の版を先頭に持たなければ止まる（作業ツリーで行を消した形）。
      - rules を渡せば、各版に当てる（返り値を集める）。
    この照合の git は GIT_ の環境変数を固定して動かす（_rgit。GIT_NO_REPLACE_OBJECTS と、存在しないパスの GIT_GRAFT_FILE
    なので、refs/replace/ と info/grafts は、この照合の版の辿り方を変えない。verify のほかの照合の git がそうとは限らない。
    手順書13章）。浅い clone では、版を辿りきれないので LedgerError（呼ぶ側が止めるか「照らさなかった」にする）。
    返り値: (commit の版の数, [rules(版)...], 鎖の上で最も長い版)。"""
    if not _not_shallow(repo):
        raise ledger.LedgerError("浅い clone なので、%s が追記だけかを git の履歴で照らせない" % rel)
    head = _version_or_empty(repo, "HEAD", rel)
    if working is not None and not working.startswith(head):
        # 作業ツリーで行を消した形（鎖の上にはあっても、短い作業ツリーの版は止める。T-112：GKG にも同じく当てる）
        raise ledger.LedgerError("作業ツリーの %s が、HEAD の版を先頭に持たない（コミットした行を消すか書き換えた）" % rel)
    commits = _rgit(repo, "log", "--all", "--reflog", "--full-history", "--format=%H", "--", rel).decode().split()
    entries = [("commit %s" % c[:12], _version_or_empty(repo, c, rel)) for c in commits]
    entries.append(("HEAD", _version_or_empty(repo, "HEAD", rel)))
    if working is not None:
        entries.append(("作業ツリー", working))
    chain = sorted(entries, key=lambda e: len(e[1]))
    for (n1, v1), (n2, v2) in zip(chain, chain[1:]):
        if not v2.startswith(v1):
            raise ledger.LedgerError("%s の版が1本の鎖にならない：%s の版が、%s の版の先頭部分でない（行を消すか書き換えた版が"
                                     "どこかの参照から辿れる。マニフェストは追記だけ）" % (rel, n1, n2))
    # どの commit の版も、その親の版を先頭に持つ（行を消すコミットが無い）。HEAD が遅れているだけの形には、そういうコミットは
    # 無い。最後の行を消しただけの版は鎖からは外れない（短い方が先頭部分）ので、親との比べで見つける（T-104）。ファイルを
    # 消したコミットの版は空なので、行のある親の版を先頭に持たず、ここで止まる
    for c in commits:
        v = _version_or_empty(repo, c, rel)
        for p in _rgit(repo, "rev-parse", c + "^@").decode().split():
            if not v.startswith(_version_or_empty(repo, p, rel)):
                raise ledger.LedgerError("%s の commit %s の版が、親 %s の版を先頭に持たない（行を消すか書き換えたコミット。"
                                         "マニフェストは追記だけ）" % (rel, c[:12], p[:12]))
    got = []
    if rules is not None:
        seen = set()
        for _n, v in entries:
            if v not in seen:
                seen.add(v)
                got.append(rules(v))
    return len(commits), got, chain[-1][1]


def check_themes_attempt_code(repo, body):
    """区分表のマニフェストの行を、git の履歴と照らす（T-102、T-104 で改めた）。行は、何行目かで、その行を初めて含んだコミット C
    （`git log --reverse --full-history HEAD -- <マニフェスト>` の順で、その版の k 行目が、その行のバイト列と同じ最初のもの）と
    結びつける（同じバイト列の行が2つあっても、行の位置で別々に結びつく。T-104 軽-2）。
      - attempt：C の版の themes.py の sha256 が、行の code_sha256 と同じ（C の親の版は使わない。T-104 中-1。themes.py の
        code gate は HEAD にコミットした中身で動くので、正直な流れでは、試行の行だけを足したコミット C の themes.py は、
        その版のままである。親の版で初めて合うのは、試行の行と themes.py の変更を同じコミットに入れた形だけ）。
      - fetch：C の第一の親 P の版で、マニフェストがちょうど直前の attempt の行までで終わり、themes.py の sha256 が fetch の行の
        code_sha256 と同じ（themes.py は、作業ツリーのマニフェストが HEAD と同じで、最後が自分の試行の行のときだけ fetch を
        書く。T-104 中-3）。
      - failed・result：直前の fetch の行と同じコミットで初めて入った（themes.py は、fetch を書いた同じ実行の中で failed か
        result を書き、そのあとでコミットする）。result の code_sha256 は、ledger の照合で fetch・attempt と同じ。
    body は作業ツリーのマニフェスト（無ければ None）。まだコミットしていない行は「照らさなかった」。
    返り値: ({kind: 照らした行の数}, 照らさなかったことの一覧)。違えば LedgerError。"""
    counts = {"attempt": 0, "fetch": 0, "failed": 0, "result": 0}
    if not body:
        return counts, []
    lines = [x for x in body.split(b"\n") if x.strip()]
    rows = [json.loads(x.decode("utf-8")) for x in lines]
    rel = ledger.THEMES_MANIFEST
    commits = _rgit(repo, "log", "--reverse", "--full-history", "--format=%H", "HEAD", "--", rel).decode().split()
    versions = [(c, [x for x in _version_or_empty(repo, c, rel).split(b"\n") if x.strip()]) for c in commits]

    def first(k):
        return next((c for c, v in versions if len(v) > k and v[k] == lines[k]), None)

    def themes_sha(c):
        if not _git_ok(repo, "cat-file", "-e", "%s:%s" % (c, THEMES_CODE_REL)):
            return None
        return ledger.sha256_hex(_rgit(repo, "cat-file", "blob", "%s:%s" % (c, THEMES_CODE_REL)))

    notes = []
    for k, row in enumerate(rows):
        kind, where = row.get("kind"), "%s の %d 行目（%s）" % (rel, k + 1, row.get("kind"))
        c = first(k)
        if c is None:
            if kind == "attempt":
                notes.append("区分表のマニフェストの attempt の行（attempted_at %s）の code_sha256（その行がまだコミットされていない）"
                             % row.get("attempted_at"))
            else:
                notes.append("区分表のマニフェストの %d 行目（%s）の git の履歴との照合（その行がまだコミットされていない）"
                             % (k + 1, kind))
            continue
        if kind == "attempt":
            if themes_sha(c) != row.get("code_sha256"):
                raise ledger.LedgerError("%sの code_sha256 %s が、その行を初めて含んだコミット %s の版の %s の sha256 と違う"
                                         % (where, str(row.get("code_sha256"))[:12], c[:12], THEMES_CODE_REL))
        elif kind == "fetch":
            parents = _rgit(repo, "rev-parse", c + "^@").decode().split()
            if not parents:
                raise ledger.LedgerError("%sを初めて含んだコミット %s に親が無い" % (where, c[:12]))
            p = parents[0]
            pv = [x for x in _version_or_empty(repo, p, rel).split(b"\n") if x.strip()]
            if pv != lines[:k] or rows[k - 1].get("kind") != "attempt":
                raise ledger.LedgerError("%sを初めて含んだコミット %s の第一の親 %s の版で、マニフェストが直前の attempt の行で"
                                         "終わっていない（試行の行をコミットする前に通信した形）" % (where, c[:12], p[:12]))
            if themes_sha(p) != row.get("code_sha256"):
                raise ledger.LedgerError("%sの code_sha256 が、その行を初めて含んだコミット %s の第一の親 %s の版の %s の sha256 と違う"
                                         % (where, c[:12], p[:12], THEMES_CODE_REL))
        else:
            if first(k - 1) != c:
                raise ledger.LedgerError("%sが、直前の fetch の行と同じコミットで入っていない（fetch の行をコミットしたあとに書いた形）"
                                         % where)
        counts[kind] = counts.get(kind, 0) + 1
    return counts, notes

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


def gkg_manifests_check(st, day_dirs=(), filelists=None):
    """gkg-run-start の記録と、収集係のマニフェストの照合（T-041、T-066）。マニフェストが無い mode は照らさず、
    そう表示して all の最後にも出す。T-066：run-start の行の入力の値・day の行・run-complete の行の照合
    （ledger.check_gkg_manifest_rows）、gkg-run-result（マニフェストの時刻証明）の照合、日の集計の sha256 の照合
    （day_dirs を渡したときだけ）。"""
    filelists = filelists or {}
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
        _check_plan_body(st, r, d, runs_by_key.get(key), filelists)
    _check_official_trial_sha(st, manifests, results)
    _check_day_files(st, day_rows, day_dirs)


def _check_official_trial_sha(st, manifests, results):
    """正式な run の run-start の行の trial_manifest_sha256 を、R の gkg-run-result が縛る試しの run のマニフェストと
    照らす（T-074。ledger.check_official_trial_manifest_sha）。R の gkg-run-result が無ければ「照らさなかった」。"""
    got = ledger.check_official_trial_manifest_sha(st.file_json, manifests, results)
    if got is None:
        return
    rel = ledger.GKG_MANIFESTS["official"]
    if not got["checked"]:
        st.unchecked.append("%s の run-start の行の trial_manifest_sha256（%s）" % (rel, got["reason"]))
        print("照らさなかった：%sので、%s の run-start の行の trial_manifest_sha256 を、R の gkg-run-result が縛る試しの "
              "run のマニフェストと照らしていない" % (got["reason"], rel))
        return
    print("%s の run-start の行 %d 行の trial_manifest_sha256 は、R（run_id %s）の gkg-run-result（seq %d）が縛る試しの "
          "run のマニフェスト（先頭 %d 行）の sha256 と同じ%s"
          % (rel, got["rows"], got["run_id"], got["result_seq"], got["lines"],
             "" if not got["later"] else "か、R のあとの試しの run の行を含む今の試しのマニフェストの全体の sha256 と同じ"
                                         "（R のあとにも試しの run がある。この形では、順番2は関門で止まる）"))


# 計画を作り直す小さなプログラム（T-070 差し戻し2回目）。-I で流し、取り出した版の gkg.py を読み込んで、
# 封印済みのファイル一覧の本体から select_files（試しの run は trial_plan も）で計画を作り、JSON で書く
PLAN_REBUILDER = r"""
import importlib.util, json, os, sys
root, body_path, mode = sys.argv[1], sys.argv[2], sys.argv[3]
spec = importlib.util.spec_from_file_location("gkg", os.path.join(root, "src", "collector", "gkg.py"))
gkg = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gkg)
with open(body_path, "rb") as f:
    rows = gkg.parse_filelist(f.read())
plan = gkg.select_files(rows)
if mode == "trial":
    plan = gkg.trial_plan(plan)
sys.stdout.write(json.dumps({d: [[e["file_time"], e["size"], e["md5"]] for e in v] for d, v in plan.items()}))
"""


def _find_version(repo, rel, sha, cache):
    """rel の版のうち、内容の sha256 が sha のもの（rel を変えたコミットを新しい順に git show で探す）。無ければ None。"""
    key = (rel, sha)
    if key in cache:
        return cache[key]
    found = None
    try:
        commits = _rgit(repo, "rev-list", "HEAD", "--", rel).decode().split()
    except ledger.LedgerError:
        commits = []
    for c in commits:
        try:
            data = _rgit(repo, "show", "%s:%s" % (c, rel))
        except ledger.LedgerError:
            continue
        if ledger.sha256_hex(data) == sha:
            found = data
            break
    cache[key] = found
    return found


def pinned_of_acquire(source):
    """取得の入口のコード（acquire_gkg.py）のバイト列から、PINNED_SHA256 の {パス: sha256} を読む（実行せずに ast で）。"""
    import ast
    try:
        tree = ast.parse(source.decode("utf-8"))
    except (UnicodeDecodeError, SyntaxError, ValueError):
        raise ledger.LedgerError("取得の入口のコードを読めない") from None
    names, pinned = {}, None
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            n, v = node.targets[0].id, node.value
            if isinstance(v, ast.Constant) and isinstance(v.value, str):
                names[n] = v.value
            elif n == "PINNED_SHA256":
                pinned = v
    out = {}
    if not isinstance(pinned, ast.Tuple):
        raise ledger.LedgerError("取得の入口のコードに PINNED_SHA256 が無い")
    for el in pinned.elts:
        if not (isinstance(el, ast.Tuple) and len(el.elts) == 2 and isinstance(el.elts[1], ast.Constant)):
            raise ledger.LedgerError("取得の入口のコードの PINNED_SHA256 の形が違う")
        k = el.elts[0]
        path = names.get(k.id) if isinstance(k, ast.Name) else (k.value if isinstance(k, ast.Constant) else None)
        if not isinstance(path, str) or not isinstance(el.elts[1].value, str):
            raise ledger.LedgerError("取得の入口のコードの PINNED_SHA256 の形が違う")
        out[path] = el.elts[1].value
    return out


def rebuild_plan(repo, d, body, tmp, cache, what):
    """記録 d（gkg-run-start の中身）が固定する版の select_files（試しの run は trial_plan も）で、ファイル一覧の本体
    body から計画を作り直す（T-070 差し戻し2回目）。固定の連なり：d の code_sha256 → その版の acquire_gkg.py の
    PINNED_SHA256 → gkg.py（と同じフォルダで読み込む filelist.py・privacy_scan.py など、PINNED_SHA256 のすべて）。
    版は git の履歴から sha256 で探し、_BoundDir に書き出して -I で流す。返り値: {日付: [entry]}。"""
    code_rel = d["code_path"]
    acq = _find_version(repo, code_rel, d["code_sha256"], cache)
    if acq is None:
        raise ledger.LedgerError("%s：code_sha256 %s の %s の版が、git の履歴に無い" % (what, d["code_sha256"][:12], code_rel))
    pinned = pinned_of_acquire(acq)
    gkg_rel = "src/collector/gkg.py"
    if gkg_rel not in pinned:
        raise ledger.LedgerError("%s：%s の PINNED_SHA256 に %s が無い" % (what, code_rel, gkg_rel))
    blobs, files = {code_rel: acq}, [(code_rel, d["code_sha256"])]
    for rel, sha in sorted(pinned.items()):
        data = _find_version(repo, rel, sha, cache)
        if data is None:
            raise ledger.LedgerError("%s：PINNED_SHA256 の %s（%s）の版が、git の履歴に無い" % (what, rel, sha[:12]))
        blobs[rel] = data
        files.append((rel, sha))
    bound = _BoundDir(repo, None, files, tmp, what, blobs=blobs)
    fd, body_path = tempfile.mkstemp(prefix="filelist-", dir=tmp)
    with os.fdopen(fd, "wb") as f:
        f.write(body)
    out = _run_script(bound.dir, gkg_rel, what, code=PLAN_REBUILDER, args=(bound.dir, body_path, d["mode"]))
    try:
        raw = json.loads(out.decode("utf-8"))
        return {day: [{"file_time": ft, "size": size, "md5": md5} for ft, size, md5 in files_]
                for day, files_ in raw.items()}
    except (UnicodeDecodeError, ValueError, TypeError, AttributeError):
        raise ledger.LedgerError("%s：作り直した計画を読めない" % what) from None


# 封印済みのファイル一覧を、GDELT の公開の一覧から作り直す小さなプログラム（T-073。T-070 再提出2回目の監査 軽-1）。
# -I で流し、取り出した版の filelist.py（同じフォルダの privacy_scan.py を読み込む）の、取得のときと同じ関数
# （_read_kept_lines：2020-12-14 以前と判定できた行だけを残す、parse_kept_line：許可リストの4項目、
# serialize_rows：本体の書き方）で、本体と同じ形のバイト列を標準出力に書く
FILELIST_REBUILDER = r"""
import importlib.util, os, sys
root, src = sys.argv[1], sys.argv[2]
spec = importlib.util.spec_from_file_location("filelist", os.path.join(root, "src", "collector", "filelist.py"))
fl = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fl)
with open(src, "rb") as f:
    lines = fl._read_kept_lines(f, lambda: 0.0, 1.0)
rows = [r for r in (fl.parse_kept_line(x) for x in lines) if r is not None]
sys.stdout.buffer.write(fl.serialize_rows(rows))
"""
FILELIST_REL = "src/collector/filelist.py"


def filelist_source(records, read_json):
    """gkg-run-start が使う一覧（ledger.gkg_filelist_sha256 と同じ、最初の method-access より前のただ1件の
    acquisition-result）と、その acquisition-start の取得のコード。返り値: (code_path, code_sha256, kept_rows_sha256,
    acquisition-result の seq)。"""
    kept = ledger.gkg_filelist_sha256(records, read_json)
    m = ledger._first_of_kind(records, ledger.METHOD_ACCESS_KIND)
    res = [r for r in records if r["kind"] == ledger.ACQ_RESULT_KIND and (m is None or r["seq"] < m["seq"])][0]
    start_seq, _kept = ledger.acquisition_result_fields(res, read_json(res, ledger.ACQ_RESULT_KIND))
    start = {r["seq"]: r for r in records}.get(start_seq)
    if start is None or start["kind"] != ledger.ACQ_START_KIND:
        raise ledger.LedgerError("seq %d の acquisition-result の start_seq %d が acquisition-start でない"
                                 % (res["seq"], start_seq))
    code_path, code_sha = ledger.acquisition_start_fields(read_json(start, ledger.ACQ_START_KIND))
    return code_path, code_sha, kept, res["seq"]


def rebuild_filelist(repo, code_rel, code_sha, master_path, tmp, cache, what):
    """GDELT の公開の一覧（master_path）を、acquisition-start が固定する版の filelist.py の規則で絞り、封印済みの
    一覧の本体と同じ形のバイト列を作る（T-073）。固定の連なり：code_sha256 → その版の取得の入口のコード
    （acquire_filelist.py）→ その中の PINNED_SHA256 → filelist.py・privacy_scan.py（など、PINNED_SHA256 のすべて）。
    版は git の履歴から sha256 で探し（HEAD の版は使わない）、_BoundDir に書き出して -I で流す。"""
    acq = _find_version(repo, code_rel, code_sha, cache)
    if acq is None:
        raise ledger.LedgerError("%s：code_sha256 %s の %s の版が、git の履歴に無い" % (what, code_sha[:12], code_rel))
    pinned = pinned_of_acquire(acq)
    if FILELIST_REL not in pinned:
        raise ledger.LedgerError("%s：%s の PINNED_SHA256 に %s が無い" % (what, code_rel, FILELIST_REL))
    blobs, files = {code_rel: acq}, [(code_rel, code_sha)]
    for rel, sha in sorted(pinned.items()):
        data = _find_version(repo, rel, sha, cache)
        if data is None:
            raise ledger.LedgerError("%s：PINNED_SHA256 の %s（%s）の版が、git の履歴に無い" % (what, rel, sha[:12]))
        blobs[rel] = data
        files.append((rel, sha))
    bound = _BoundDir(repo, None, files, tmp, what, blobs=blobs)
    return _run_script(bound.dir, FILELIST_REL, what, code=FILELIST_REBUILDER,
                       args=(bound.dir, os.path.abspath(master_path)))


def cmd_filelist_rebuild(st, a):
    """第三者の手順（12章の「第三者が照らす手順」の 2・3）：GDELT の公開の一覧から、封印した規則で一覧の本体を
    作り直し、sha256 を acquisition-result の kept_rows_sha256 と照らす（T-073）。--out を渡すと、一致したときだけ
    作った本体をそこに新しく書く（gkg-runs --filelist に渡すため。既にあるファイルは上書きしない）。
    一致しなければ失敗（終了コード 1）。git の履歴が無い・浅い clone のときも、版を探せないので失敗。"""
    code_rel, code_sha, kept, res_seq = filelist_source(st.records, st.file_json)
    repo = Repo(st.root)
    try:
        repo.git("rev-parse", "--git-dir")
    except (ledger.LedgerError, OSError):
        raise ledger.LedgerError("git の履歴が無いので、固定された版の filelist.py を探せない") from None
    if not _not_shallow(repo):
        raise ledger.LedgerError("浅い clone なので、固定された版の filelist.py を探せない（--depth を付けない clone か "
                                 "git fetch --unshallow のあとで流す）")
    what = "一覧の作り直し（acquisition-start の %s・%s…）" % (code_rel, code_sha[:12])
    with tempfile.TemporaryDirectory() as tmp:
        body = rebuild_filelist(repo, code_rel, code_sha, a.masterfilelist, tmp, {}, what)
    got = ledger.sha256_hex(body)
    lines = body.count(b"\n") - 1
    if got != kept:
        raise ledger.LedgerError("作り直した一覧（%d 行）の sha256 %s が、seq %d の acquisition-result の kept_rows_sha256 %s と"
                                 "一致しない。渡した公開の一覧が、取得のときと違う（GDELT が一覧を変えたか、別の一覧を"
                                 "渡した）か、封印した一覧が規則どおりでない。どちらかは、この検査では区別できない"
                                 % (lines, got, res_seq, kept))
    print("作り直した一覧（%d 行）の sha256 %s は、seq %d の acquisition-result の kept_rows_sha256 と同じ（規則は "
          "acquisition-start が固定する版の %s。HEAD の版は使っていない）" % (lines, got, res_seq, FILELIST_REL))
    if a.out:
        try:
            with open(a.out, "xb") as f:
                f.write(body)
        except OSError as e:
            raise ledger.LedgerError("--out に書けない（%s。既にあるファイルは上書きしない）" % e.__class__.__name__) from None
        print("作った本体を %s に書いた。gkg-runs --filelist に渡す" % a.out)


def _check_plan_body(st, r, d, run, filelists):
    """gkg-run-start の plan_sha256 を、封印済みのファイル一覧の本体から作り直した計画と照らし、マニフェストの
    day の行の日付・files_listed・failed_files がその計画と合うことを照らす（T-070 差し戻し2回目）。
    一覧の本体は --filelist で渡したもののうち、sha256 が記録の filelist_sha256 と同じもの。無ければ「照らさなかった」。
    plan_sha256 の無い記録（T-070 より前の形。試しの run だけ。正式な run は check_gkg_run_doc が 16 個の形を求める。
    T-074）も、何も出さずに抜けず「照らさなかった」と出す。"""
    if ledger.GKG_RUN_PLAN_SHA_KEY not in d:
        st.unchecked.append("seq %d の gkg-run-start（%s）の計画の一覧（計画の sha256 が無い記録。T-070 より前）"
                            % (r["seq"], d["mode"]))
        print("照らさなかった：seq %d の gkg-run-start（%s）は、計画の sha256（plan_sha256）が無い記録（T-070 より前）なので、"
              "どの日のどのファイルかを、データを受け取る前の記録と照らしていない" % (r["seq"], d["mode"]))
        return
    what = "seq %d の run の計画の作り直し" % r["seq"]
    body = filelists.get(d["filelist_sha256"])
    if body is None:
        st.unchecked.append("seq %d の run の計画（plan_sha256）の作り直し（封印済みのファイル一覧の本体が無い。"
                            "--filelist で渡したときだけ照らす）" % r["seq"])
        print("照らさなかった：seq %d の run の plan_sha256 は、封印済みのファイル一覧（sha256 %s…）の本体を --filelist で"
              "渡したときだけ、作り直して照らす" % (r["seq"], d["filelist_sha256"][:12]))
        return
    repo = Repo(st.root)
    try:
        repo.git("rev-parse", "--git-dir")
    except (ledger.LedgerError, OSError):
        st.unchecked.append("%s（git の履歴が無い）" % what)
        print("照らさなかった：git の履歴が無いので、%s はしていない" % what)
        return
    if not _not_shallow(repo):
        # T-073（T-070 再提出2回目の監査 中-1）：浅い clone では、記録が固定する版が履歴に無いことがあり、正直な
        # 記録でも「版が git の履歴に無い」で止まってしまう。stats-order と同じやり方（--is-shallow-repository を
        # GIT_ の環境変数を固定して確かめる）で見分け、作り直しはせず「照らさなかった」にする
        st.unchecked.append("%s（浅い clone）" % what)
        print("照らさなかった：浅い clone なので、%s はしていない（--depth を付けない clone か "
              "git fetch --unshallow のあとで照らす）" % what)
        return
    if not hasattr(st, "_version_cache"):
        st._version_cache = {}
    with tempfile.TemporaryDirectory() as tmp:
        try:
            plan = rebuild_plan(repo, d, body, tmp, st._version_cache, what)
        except Unchecked as e:
            st.unchecked.append("%s（%s）" % (what, e))
            print("照らさなかった：%s（%s）" % (what, e))
            return
    got = ledger.gkg_plan_sha256(plan)
    if got != d[ledger.GKG_RUN_PLAN_SHA_KEY]:
        raise ledger.LedgerError("seq %d の gkg-run-start の plan_sha256 %s が、封印済みのファイル一覧から作り直した計画の "
                                 "sha256 %s と違う" % (r["seq"], d[ledger.GKG_RUN_PLAN_SHA_KEY], got))
    if (len(plan), sum(len(v) for v in plan.values())) != (d["days"], d["files_selected"]):
        raise ledger.LedgerError("seq %d の作り直した計画の日の数・ファイルの数が、gkg-run-start の days・files_selected と"
                                 "違う" % r["seq"])
    if d["mode"] == "trial" and sorted(plan) != list(d["trial_days"]):
        raise ledger.LedgerError("seq %d の作り直した計画の日が、trial_days と違う" % r["seq"])
    if run is None:
        st.unchecked.append("seq %d の run の day の行と計画の照合（マニフェストに行が無い）" % r["seq"])
        print("seq %d の run：封印済みのファイル一覧から作り直した計画の sha256 は plan_sha256 と同じ。照らさなかった："
              "マニフェストに行が無いので、day の行との照合はしていない" % r["seq"])
        return
    ledger.check_plan_rows(plan, run, "%s（seq %d の run）" % (ledger.GKG_MANIFESTS[d["mode"]], r["seq"]))
    print("seq %d の run：封印済みのファイル一覧から、記録が固定する版の select_files で作り直した計画の sha256 は "
          "plan_sha256 と同じで、day の行の日付・files_listed・failed_files はその計画と合う" % r["seq"])


def _not_shallow(repo):
    """浅い clone でないか（git rev-parse --is-shallow-repository が false）。cmd_stats_order と同じ確かめ方で、
    GIT_ の環境変数を固定して動かす。T-073。"""
    try:
        return repo.git("rev-parse", "--is-shallow-repository", env=ledger.fixed_git_env()).strip() == b"false"
    except (ledger.LedgerError, OSError):
        return False


def read_filelists(paths):
    """--filelist で渡したファイルの {sha256: バイト列}。"""
    out = {}
    for p in paths:
        with open(p, "rb") as f:
            data = f.read()
        out[ledger.sha256_hex(data)] = data
    return out


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


def gkg_manifests_append_only(st):
    """GKG の二つのマニフェストも、追記だけかを git の履歴で照らす（T-103）。gkg-run-result が縛る先頭は封印の記録と時刻証明で
    固定されるが、封印の前（run の途中）と、封印した先頭のあとの行は縛られないため。git の履歴が無いとき・浅い clone の
    ときは「照らさなかった」。"""
    repo = Repo(st.root)
    try:
        repo.git("rev-parse", "--git-dir")
    except (ledger.LedgerError, OSError):
        st.unchecked.append("GKG のマニフェストが追記だけか（git の履歴が無い）")
        print("照らさなかった：git の履歴が無いので、GKG のマニフェストが追記だけかを照らしていない")
        return
    if not _not_shallow(repo):
        st.unchecked.append("GKG のマニフェストが追記だけか（浅い clone）")
        print("照らさなかった：浅い clone なので、GKG のマニフェストが追記だけかを照らしていない")
        return
    for mode, rel in sorted(ledger.GKG_MANIFESTS.items()):
        path = os.path.join(st.root, rel)
        working = None
        if os.path.isfile(path) and not os.path.islink(path):
            with open(path, "rb") as f:
                working = f.read()
        n, _got, _longest = check_manifest_append_only(repo, rel, working=working)
        if n:
            print("  %s（%s）：commit の版 %d 個（git log --all --reflog --full-history）と HEAD・作業ツリーの版は、1本の鎖になる"
                  "（追記だけ。T-103・T-104）" % (rel, mode, n))


def cmd_gkg_runs(st, a):
    """GKG の取得の run の開始（kind が gkg-run-start）の照合と一覧。T-031、T-041。T-066：マニフェストの行と
    gkg-run-result の照合。"""
    runs = ledger.check_gkg_runs(st.records, st.file_json)
    for r in st.records:
        if r["kind"] == ledger.GKG_RESULT_KIND:
            ledger.check_gkg_result_doc(st.records, r, st.file_json(r, ledger.GKG_RESULT_KIND), st.file_json, st.data)
    gkg_manifests_check(st, [os.path.abspath(d) for d in getattr(a, "day_files", None) or []],
                        read_filelists(getattr(a, "filelist", None) or []))
    gkg_manifests_append_only(st)                                       # T-103
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
                 "gkg-runs", "filelist-rebuild",
                 "periods", "candidates", "adopted", "all"):
        s = sub.add_parser(name, allow_abbrev=False)
        s.add_argument("--btc-header", type=_parse_header_arg, action="append",
                       help="高さ=80 バイトのヘッダの16進。.ots の中の Bitcoin の証明と照合する")
        s.add_argument("--ots-dir", action="append", default=[],
                       help="自分で upgrade した .ots を置いたディレクトリ（採用は変わらない）")
        parsers[name] = s
    for name in ("targets", "all", "stats-order"):
        parsers[name].add_argument("--rev", default="working")
    # T-078：stats-order にも日の集計の置き場所（決まった順番2の記録の decide() を流し直す。渡したときだけ）
    parsers["stats-order"].add_argument("--day-files", action="append", default=[])
    # T-095：正式な run の日の集計の置き場所。渡したときだけ、封印済みの counting.py で順番4の C7 の分母を数え直す（60〜100分）
    for name in ("stats-order", "all"):
        parsers[name].add_argument("--store")
        # T-111：区分表のファイルの置き場所（順番5の計算し直し）と、Git の外の detail・extra の置き場所
        parsers[name].add_argument("--themes-store")
        parsers[name].add_argument("--order5-outside")
        # T-144：手法を作る期間のキャッシュ（explore-t117-cache/run2。Git の外）。渡したときだけ、順番6〜8 の係数と表を流し直す
        parsers[name].add_argument("--t117-cache")
    for name in ("gkg-runs", "all"):
        # T-066：日の集計（と取得の記録）の置き場所。渡したときだけ sha256 を照らす（第三者はディスクを持たない）。
        # all では、順番2の decide() の流し直しにも使う（T-078）
        parsers[name].add_argument("--day-files", action="append", default=[])
        # T-070 差し戻し2回目：封印済みのファイル一覧の本体。sha256 が記録の filelist_sha256 と同じものだけを使い、
        # 計画を作り直して plan_sha256 と照らす
        parsers[name].add_argument("--filelist", action="append", default=[])
    # T-073：GDELT の公開の一覧（masterfilelist.txt を取ったファイル）から、封印した規則で一覧の本体を作り直す
    parsers["filelist-rebuild"].add_argument("--masterfilelist", required=True)
    parsers["filelist-rebuild"].add_argument("--out")
    a = p.parse_args(argv)
    fn = {"chain": cmd_chain, "filelist-rebuild": cmd_filelist_rebuild, "anchors": cmd_anchors, "targets": cmd_targets,
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
