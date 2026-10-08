#!/usr/bin/env python3
"""封印の記録（追記のみ）の中核。T-005、T-007、T-008、T-009、T-013、T-014、T-017。

記録のファイル（既定は sealed/ledger.jsonl）は JSON Lines で、1 行が 1 件の記録。
標準ライブラリだけを使う。ネットワークは使わない。

1 行の形（キーはこの 6 つだけ。ほかのキーがあれば検証で失敗にする）
    seq          通し番号。1 から始まり、行の順に 1 ずつ増える。
    prev_hash    直前の行のバイト列（末尾の改行を含めない）の sha256。1 行目は 0 が 64 個。
    kind         種類。許可リスト（ALLOWED_KINDS）の 11 だけ（T-066 で gkg-run-result を加えた）。それ以外は検証で失敗にする。
                 gkg-run-start（GKG の取得の run の開始。T-031）、stats-order1・stats-order1b
                 （統計係の順番1・順番1b の事前の封印。T-037）を加えた。
                 periods / periods-triggers / threshold-access / acquisition-start /
                 acquisition-result / candidates（T-013）/ method-access（T-014）
    targets      対象のファイルの一覧。各要素は {"path", "role", "sha256"}。
                 path はリポジトリのルートからの相対パス（区切りは /）。
    recorded_at  記録した日時（UTC、"YYYY-MM-DDTHH:MM:SSZ"）。記録した機械の時計による
                 申告であり、証明ではない。時刻の証明は OpenTimestamps で行う。
    note         注記。

行は正規の形で書く（キーを並べ替え、区切りに空白を入れず、UTF-8）。検証では、各行を
読み直して正規の形に戻し、元の行とバイト単位で一致することも確かめる。同じ中身を別の
書き方で書いた行を許さないため。

版の番号は記録に書かない（自己申告にしない）。同じ種類の記録の何件目かで決まる
（version_of）。

時刻証明（OpenTimestamps）の対象
    seq が N の記録を追記した直後の、記録のファイルの先頭から N 行目まで（各行の末尾の
    改行を含む）のバイト列の sha256（prefix_digest）。.ots のファイル名は
    ledger.jsonl.seqNNNNNN.ots。記録は追記のみなので、後で行が増えても、先頭 N 行の
    sha256 は変わらない。Bitcoin への確定を加えた .ots は、元の .ots を書き換えずに
    ledger.jsonl.seqNNNNNN.bitcoin.ots として別に置く（stamp.py の upgrade）。

時刻証明（OpenTimestamps）の役割と欠け
    すべての seq に、その seq 自身の .ots が要る（check_anchors）。欠けていれば検証は失敗する。
    .ots が示すのは「記録の先頭から seq 行目までが、Bitcoin で確定した時刻に存在した」
    ことだけである。採用の判定には使わない。
    Pending の証明の宛先は、stamp で使った 4 つのカレンダー（STAMP_CALENDARS の実体の側）に
    限る。それ以外の宛先があれば、検証は失敗する。

採用の規則（adoption）。T-007 で鎖の順番で決める形にし、T-008 で区切りを改めた。
    区切りは、最初の threshold-access の記録である。threshold-access は、閾値を決める期間の
    区画（2020-12-15 以降）の情報を初めて「扱う」直前に、鎖へ追記する記録である。「扱う」の
    定義は docs/stats/periods.md 8章 (2) に従う（ディスクに書く・画面に表示する・集計する・
    ログに出す。メモリの上で受け取り、ディスクに書く前に捨てることは含めない）。
    採用するのは、最初の threshold-access の記録より seq が小さい記録のうち、その種類
    （periods、periods-triggers、candidates）の最後のもの。
    - acquisition-start・acquisition-result（試運転の手順3の取得）と method-access（手順4の
      開始）と gkg-run-start（GKG の取得の run の開始。T-031）は区切りに使わない（T-014 の
      リードの指示。区切りは threshold-access のまま）。
      8章 (2) は、手順3で 2020-12-15 以降の行をメモリの上で捨てるなら、手順3は期限に
      当たらないとしている。そのため、手順3の後に追記したきっかけの値も、最初の
      threshold-access より前なら採用される。
    - threshold-access の記録がまだ無いうちは「採用は保留」。仮の候補として、今ある最後の
      記録を示す。
    - 区切りの後に追記した periods・periods-triggers を、追記の時点で拒む関門は設けない
      （設けない方がよい、という監査の所見による）。検証が「採用しない」と表示するだけである。
    - 時刻（Bitcoin の確定時刻、drand の回の公開時刻）も、Pending かどうかも、recorded_at
      （申告）も使わない。adoption の引数は記録の一覧と種類だけである。
    - 鎖は行を消せず、順番も入れ替えられない（verify_chain）。そのため、.ots の upgrade を
      出すか出さないか、Pending のままにするか、drand のどの回を書くかで、採用は変わらない。

drand を持つ記録（threshold-access、acquisition-start、method-access）の照合（check_drand_record）
    - 中身の kind が記録の kind と同じであること。
    - 中身の ledger_head が、直前の記録までの先頭の sha256（seq N−1 の .ots の対象と同じ値）と
      一致すること。
    - drand の回の公開時刻 T が、その記録自身の .ots の Bitcoin の確定時刻（ヘッダの時刻）Tq に
      対して、T < Tq + DRAND_HEADER_SLACK であること。幅を超えて T が後なら失敗にする。
      確定していなければ、この照合は保留する。幅の値と根拠は DRAND_HEADER_SLACK の注記。
    - drand の署名（BLS）は、オフラインでは検証しない。randomness が signature の sha256
      であることだけを確かめる。
    - threshold-access では、中身の block_start が、periods の 1 件目の出力の閾値の期間
      （threshold）の block_start と一致すること（verify.py で照合する）。

取得の記録（acquisition-start と acquisition-result）の対応の照合（check_acquisition_pairs）
    - result が参照する start（中身の start_seq）が、kind=acquisition-start の記録として実在すること。
    - result の seq が、その start の seq より後であること。
    - 一つの start に result が一つだけであること（二つ以上なら失敗）。
    result の無い start は、取得の途中か失敗として表示する（失敗にはしない）。

書く仕組みと関門（T-009）
    threshold-access は seal_access.py、acquisition-start・acquisition-result は
    seal_acquisition.py が書く（共通の手順は seal_records.py。追記の前に、この中の照合を
    「今の記録 + 追記する行」に対して行う。build_next_record）。
    閾値を決める期間の区画のデータに触れるコードは、最初に require_threshold_access を呼ぶ。
    関門を飛ばしたかどうかは、記録からは検出できない（require_threshold_access の注記）。

閾値と判定期間の候補（kind が candidates。T-013）
    対象は docs/stats/candidates.md（doc）、src/stats/candidates.py（code）、
    tests/stats/test_candidates.py（test）、src/stats/periods.py（import。candidates.py が
    読み込むので、出力を作り直すのに要る）、sealed/candidates-output-<sha256>.json（output）の
    5 つで、role とパスの組は固定（CANDIDATES_SOURCES。check_candidates_record）。
    output のファイル名の <sha256> は、記録の output の sha256 と同じでなければならない。
    採用の規則は periods と同じ（adoption）。
    これに加えて、candidates の記録は、すべて最初の acquisition-start の記録より前になければ
    ならない（check_candidates_order）。CLAUDE.md は候補を「手法を作る期間のデータに触れる
    前に」封印すると決めており、区切りの threshold-access より強い条件になるため。後ろに
    あれば検証は失敗する。acquisition-start があるなら、その前に candidates の記録が 1 件以上
    なければならない（T-014。T-013 の監査 B-1）。

手順4の開始（kind が method-access。T-014）
    手法を作る期間の区画のデータそのもの（試運転の手順4）に初めて触れる直前に追記する記録。
    中身は {"kind", "step": 4, "block_start", "block_end", "drand", "ledger_head"}。
    block_start・block_end は periods の 1 件目の出力の method の区画と一致しなければならない。
    前提（check_method_access_order）：その記録より前に candidates の記録と
    acquisition-result の記録が、それぞれ 1 件以上あること。
    手法を作る期間のデータに触れるコードは、最初に require_method_access() を呼ぶ。
    採用の区切りには使わない。

きっかけの値（kind が periods-triggers）
    区切りを作り直すきっかけの値は、periods-triggers の記録として追記する。periods の
    出力の rebuild_triggers が、採用された periods-triggers の記録と完全に一致すれば
    before_deadline、そうでなければ after_deadline が記録から決まる値で、
    出力の deadline_status（申告）と照合する（judge_deadline_status）。
    docs/stats/periods.md 8章 (2) の「期限前に追記した」は、この規則では「最初の
    threshold-access の記録より前に鎖に入った」ことである。

"""

import datetime
import hashlib
import json
import os
import re

import otsfile

GENESIS_PREV = "0" * 64
RECORD_KEYS = ("kind", "note", "prev_hash", "recorded_at", "seq", "targets")
TARGET_KEYS = ("path", "role", "sha256")
HEX64 = re.compile(r"\A[0-9a-f]{64}\Z")
TIME_RE = re.compile(r"\A\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z\Z")
KIND_RE = re.compile(r"\A[a-z][a-z0-9_-]{0,31}\Z")
OTS_NAME_RE = re.compile(r"\Aledger\.jsonl\.seq(\d{6})(\.bitcoin)?\.ots\Z")

# 記録の種類（kind）の許可リスト（T-008）。これ以外の kind は verify_chain で失敗にする。
# 決めていない名前の kind で正式な取得や閾値の期間への接触を記録して、区切りから外すことを
# 許さないため。T-007 の "acquisition" は、今の記録に無く、二つに分けたので外した。
PERIODS_KIND = "periods"
TRIGGERS_KIND = "periods-triggers"
THRESHOLD_ACCESS_KIND = "threshold-access"
ACQ_START_KIND = "acquisition-start"
ACQ_RESULT_KIND = "acquisition-result"
CANDIDATES_KIND = "candidates"
METHOD_ACCESS_KIND = "method-access"
GKG_RUN_KIND = "gkg-run-start"      # T-031：GKG の取得の run（試し・正式）の開始
ORDER1_KIND = "stats-order1"        # T-037：統計係の順番1（除外の規則と入れる規則）。除外の規則の kind
ORDER1B_KIND = "stats-order1b"      # T-037：統計係の順番1b（数え方の候補と基準の案）
GKG_RESULT_KIND = "gkg-run-result"  # T-066：GKG の取得の run が終わったあとの、マニフェストの封印
ALLOWED_KINDS = (PERIODS_KIND, TRIGGERS_KIND, THRESHOLD_ACCESS_KIND, ACQ_START_KIND,
                 ACQ_RESULT_KIND, CANDIDATES_KIND, METHOD_ACCESS_KIND, GKG_RUN_KIND,
                 ORDER1_KIND, ORDER1B_KIND, GKG_RESULT_KIND)

# stamp で使う公開カレンダー（ots の既定と同じ 4 つ）と、その集約先が返す Pending の宛先
# （実体のカレンダー）。stamp.py はこの左側に送る。.ots の Pending の宛先は右側に限る。
STAMP_CALENDARS = (
    ("https://a.pool.opentimestamps.org", "https://alice.btc.calendar.opentimestamps.org"),
    ("https://b.pool.opentimestamps.org", "https://bob.btc.calendar.opentimestamps.org"),
    ("https://a.pool.eternitywall.com", "https://finney.calendar.eternitywall.com"),
    ("https://ots.btc.catallaxy.com", "https://btc.calendar.catallaxy.com"),
)
ALLOWED_PENDING_URIS = frozenset(uri for _submit, uri in STAMP_CALENDARS)

class LedgerError(Exception):
    """記録の検証に失敗した。"""


# ---------------------------------------------------------------- 基本


def sha256_hex(data):
    return hashlib.sha256(data).hexdigest()


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def canonical_line(record):
    """記録を正規の形の 1 行（改行を含めないバイト列）にする。"""
    return json.dumps(record, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")


def format_time(dt):
    if dt.tzinfo is None:
        raise ValueError("タイムゾーンの無い日時は使わない")
    return dt.astimezone(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_time(text):
    if not TIME_RE.match(text):
        raise ValueError("日時の形が違う: %r" % text)
    return datetime.datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(
        tzinfo=datetime.timezone.utc)


# ---------------------------------------------------------------- 検証


def split_lines(data):
    """記録のファイルのバイト列を行に分ける。末尾は必ず改行で終わること。"""
    if data == b"":
        return []
    if not data.endswith(b"\n"):
        raise LedgerError("記録のファイルが改行で終わっていない（途中で切れている）")
    lines = data[:-1].split(b"\n")
    for i, line in enumerate(lines, 1):
        if line == b"":
            raise LedgerError("%d 行目が空行" % i)
        if b"\r" in line:
            raise LedgerError("%d 行目に CR がある" % i)
    return lines


def _check_record_shape(rec, lineno):
    if not isinstance(rec, dict) or tuple(sorted(rec)) != RECORD_KEYS:
        raise LedgerError("%d 行目: キーが決まった 6 つと一致しない" % lineno)
    if type(rec["seq"]) is not int:
        raise LedgerError("%d 行目: seq が整数でない" % lineno)
    if not isinstance(rec["prev_hash"], str) or not HEX64.match(rec["prev_hash"]):
        raise LedgerError("%d 行目: prev_hash の形が違う" % lineno)
    if not isinstance(rec["kind"], str) or not KIND_RE.match(rec["kind"]):
        raise LedgerError("%d 行目: kind の形が違う" % lineno)
    if rec["kind"] not in ALLOWED_KINDS:
        raise LedgerError("%d 行目: kind %r は許可リストに無い（許可するのは %s）"
                          % (lineno, rec["kind"], "、".join(ALLOWED_KINDS)))
    if not isinstance(rec["note"], str):
        raise LedgerError("%d 行目: note が文字列でない" % lineno)
    if not isinstance(rec["recorded_at"], str):
        raise LedgerError("%d 行目: recorded_at が文字列でない" % lineno)
    try:
        parse_time(rec["recorded_at"])
    except ValueError:
        raise LedgerError("%d 行目: recorded_at の形が違う" % lineno) from None
    targets = rec["targets"]
    if not isinstance(targets, list) or not targets:
        raise LedgerError("%d 行目: targets が空、または一覧でない" % lineno)
    paths = set()
    for t in targets:
        if not isinstance(t, dict) or tuple(sorted(t)) != TARGET_KEYS:
            raise LedgerError("%d 行目: targets の要素のキーが違う" % lineno)
        if not all(isinstance(t[k], str) for k in TARGET_KEYS):
            raise LedgerError("%d 行目: targets の値が文字列でない" % lineno)
        if not HEX64.match(t["sha256"]):
            raise LedgerError("%d 行目: targets の sha256 の形が違う" % lineno)
        p = t["path"]
        if (p.startswith("/") or "\\" in p or p == ""
                or any(part in ("", ".", "..") for part in p.split("/"))):
            raise LedgerError("%d 行目: targets の path が相対パスの正規の形でない" % lineno)
        if p in paths:
            raise LedgerError("%d 行目: targets の path が重複している" % lineno)
        paths.add(p)


def verify_chain(data):
    """記録のファイルのバイト列を検証し、記録の一覧を返す。

    検出するもの: 行の書き換え（最後の行を除く）、行の削除・挿入・入れ替え、
    欠番、正規でない書き方、形の違い、許可リストに無い kind、recorded_at の逆行。
    最後の行の書き換えと、末尾の行の削除は、鎖だけでは検出できない。
    これは check_anchors（時刻証明の対象のハッシュとの照合）と Git の履歴で検出する。
    """
    lines = split_lines(data)
    records = []
    prev_hash = GENESIS_PREV
    prev_time = None
    for i, line in enumerate(lines, 1):
        try:
            rec = json.loads(line.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            raise LedgerError("%d 行目: JSON として読めない" % i) from None
        _check_record_shape(rec, i)
        if canonical_line(rec) != line:
            raise LedgerError("%d 行目: 正規の形で書かれていない" % i)
        if rec["seq"] != i:
            raise LedgerError("%d 行目: seq が %d（欠番・重複・入れ替え）" % (i, rec["seq"]))
        if rec["prev_hash"] != prev_hash:
            raise LedgerError("%d 行目: prev_hash が直前の行のハッシュと一致しない"
                              "（直前までの行が書き換えられたか、削除・入れ替えがある）" % i)
        t = parse_time(rec["recorded_at"])
        if prev_time is not None and t < prev_time:
            raise LedgerError("%d 行目: recorded_at が直前の記録より前" % i)
        prev_time = t
        prev_hash = sha256_hex(line)
        records.append(rec)
    return records


def read_ledger(path):
    if not os.path.exists(path):
        return b""
    with open(path, "rb") as f:
        return f.read()


def prefix_bytes(data, n):
    """先頭から n 行（各行の改行を含む）のバイト列。"""
    lines = split_lines(data)
    if not 1 <= n <= len(lines):
        raise LedgerError("記録は %d 件で、先頭 %d 行は取れない" % (len(lines), n))
    return b"".join(line + b"\n" for line in lines[:n])


def prefix_digest(data, n):
    return sha256_hex(prefix_bytes(data, n))


# ---------------------------------------------------------------- 版と採用


def version_of(records, seq):
    """seq の記録が、その種類の何件目か（版の番号）。"""
    target = None
    for r in records:
        if r["seq"] == seq:
            target = r
    if target is None:
        raise LedgerError("seq %d の記録が無い" % seq)
    return sum(1 for r in records if r["kind"] == target["kind"] and r["seq"] <= seq)


def records_of_kind(records, kind):
    """(版の番号, 記録) の一覧。"""
    out = []
    for r in records:
        if r["kind"] == kind:
            out.append((len(out) + 1, r))
    return out


ADOPTED_KINDS = (PERIODS_KIND, TRIGGERS_KIND, CANDIDATES_KIND)


def first_threshold_access(records):
    """最初の kind=threshold-access の記録（採用の区切り）。無ければ None。"""
    for r in records:
        if r["kind"] == THRESHOLD_ACCESS_KIND:
            return r
    return None


def adoption(records, kind):
    """採用の規則（鎖の順番だけで決める）。T-008。

    返り値: (採用された記録, 仮の候補, 区切りに使った threshold-access の記録)
      - threshold-access の記録がある: 採用 = その seq より小さい、その種類の最後の記録
        （無ければ None）。仮の候補は None。
      - threshold-access の記録が無い: 採用は保留（None）。仮の候補 = 今ある、その種類の
        最後の記録（無ければ None）。区切りの記録は None。
    acquisition-start・acquisition-result・method-access・gkg-run-start は区切りに使わない。
    時刻・Pending かどうか・recorded_at は、引数にも無く、使わない。
    """
    of_kind = [r for r in records if r["kind"] == kind]
    cut = first_threshold_access(records)
    if cut is None:
        return None, (of_kind[-1] if of_kind else None), None
    before = [r for r in of_kind if r["seq"] < cut["seq"]]
    return (before[-1] if before else None), None, cut


# ---------------------------------------------------------------- drand を持つ記録の照合

# drand の鎖（公開されている値）。回 r の公開時刻は genesis_time + (r - 1) * period。
DRAND_CHAINS = {
    # quicknet
    "52db9ba70e0cc0f6eaf7803dd07447a1f5477735fd3f661792ba94600c84e971": (1692803367, 3),
    # default（mainnet）
    "8990e7a9aaed2ffed73dbd7092123d6f289930540d7651336225dc172e51b2ce": (1595431050, 30),
}
DRAND_NOT_VERIFIED = ("drand の署名（BLS）は、オフラインでは検証していない（randomness が "
                      "signature の sha256 であることだけを確かめた）。")

# drand の回の公開時刻と、Bitcoin のブロックのヘッダの時刻を比べるときの幅（T-008、T-009）。
# 値：2 時間（7200 秒）。
# 根拠（照合に効く向きだけ）：照合は「drand の回の公開時刻 T < ヘッダの時刻 Tq + 幅」である。
#   正しく作った記録（drand の回を取ってから追記し、そのあとで Bitcoin に確定した記録）が
#   この照合に落ちるのは、ヘッダの時刻が、実際に掘られた時刻より前に書かれた場合である。
#   ヘッダの時刻をどこまで前に書けるかは、Bitcoin の決まりのうち「直前の 11 ブロックの時刻の
#   中央値（median time past）より後であること」だけが決める。中央値は、平均 10 分ごとの
#   ブロックで、おおむね 6 ブロック前（約 1 時間前）に当たる。ブロックの間隔はばらつくので、
#   余裕を見て 2 時間とする。この幅の中の食い違いは失敗にしない。
# 代償：「記録は、ヘッダの時刻 + 2 時間 より前に存在した」までしか言えない。幅を超えて
#   drand の回の公開時刻が後なら、失敗にする。
DRAND_HEADER_SLACK = datetime.timedelta(hours=2)

DRAND_RECORD_KINDS = (THRESHOLD_ACCESS_KIND, ACQ_START_KIND, METHOD_ACCESS_KIND, GKG_RUN_KIND)
# drand を持つ記録のうち、中身に step を持つものと、その値。
DRAND_RECORD_STEP = {ACQ_START_KIND: 3, METHOD_ACCESS_KIND: 4, GKG_RUN_KIND: 4}


def drand_round_time(chain_hash, round_no):
    if chain_hash not in DRAND_CHAINS:
        raise LedgerError("知らない drand の鎖: %s" % chain_hash)
    if type(round_no) is not int or round_no < 1:
        raise LedgerError("drand の回の番号が正の整数でない")
    genesis, period = DRAND_CHAINS[chain_hash]
    return datetime.datetime.fromtimestamp(genesis + (round_no - 1) * period,
                                           datetime.timezone.utc)


def drand_time_of(doc):
    """記録の中身（JSON）の drand から、回の公開時刻を出す。

    randomness が signature の sha256 であることも確かめる（drand の決まり）。
    署名そのものの検証（BLS）はここではしない（DRAND_NOT_VERIFIED）。
    """
    try:
        d = doc["drand"]
        chain, rnd = d["chain_hash"], d["round"]
        randomness, signature = d["randomness"], d["signature"]
    except (KeyError, TypeError):
        raise LedgerError("記録の中身に drand（chain_hash・round・randomness・signature）が無い"
                          ) from None
    try:
        sig = bytes.fromhex(signature)
    except (TypeError, ValueError):
        raise LedgerError("drand の signature が16進でない") from None
    if sha256_hex(sig) != randomness:
        raise LedgerError("drand の randomness が signature の sha256 と一致しない")
    return drand_round_time(chain, rnd)


def expected_ledger_head(data, seq):
    """seq の記録に入れるべき ledger_head（直前の記録までの先頭の sha256）。"""
    n = seq - 1
    return {"seq": n, "sha256": prefix_digest(data, n) if n else sha256_hex(b"")}


def _check_doc_kind(record, doc):
    if not isinstance(doc, dict) or doc.get("kind") != record["kind"]:
        raise LedgerError("seq %d の記録の中身の kind が、記録の kind（%s）と一致しない"
                          % (record["seq"], record["kind"]))


def check_drand_record(data, record, doc, own_time):
    """drand を持つ記録（threshold-access、acquisition-start、method-access）を照合する。

    own_time: その記録自身の .ots で Bitcoin に確定した時刻（ヘッダの時刻。無ければ None）。
    返り値: (drand の回の公開時刻, "ok" か "pending")。食い違えば LedgerError。
    比べ方：drand の回の公開時刻 T が、own_time + DRAND_HEADER_SLACK より前なら通す。
    この照合は採用の判定に使わない。
    """
    seq = record["seq"]
    if record["kind"] not in DRAND_RECORD_KINDS:
        raise LedgerError("seq %d: kind %s は drand を持つ記録ではない" % (seq, record["kind"]))
    _check_doc_kind(record, doc)
    step = DRAND_RECORD_STEP.get(record["kind"])
    if step is not None and (type(doc.get("step")) is not int or doc.get("step") != step):
        raise LedgerError("seq %d の %s の step が %d でない" % (seq, record["kind"], step))
    head = doc.get("ledger_head")
    want = expected_ledger_head(data, seq)
    if not isinstance(head, dict) or sorted(head) != ["seq", "sha256"]:
        raise LedgerError("seq %d の記録の中身に ledger_head（seq・sha256）が無い" % seq)
    if head != want:
        raise LedgerError("seq %d の記録の中身の ledger_head が、直前の記録のハッシュと一致しない"
                          "（入れた値 seq %r、記録から決まる値 seq %d の %s）"
                          % (seq, head.get("seq"), want["seq"], want["sha256"]))
    t = drand_time_of(doc)
    if own_time is None:
        return t, "pending"
    if not t < own_time + DRAND_HEADER_SLACK:
        raise LedgerError("seq %d の drand の回の公開時刻 %s が、その記録自身の .ots の確定時刻"
                          "（ヘッダの時刻）%s に幅 %s を足した時刻より前でない"
                          % (seq, t.isoformat(), own_time.isoformat(), DRAND_HEADER_SLACK))
    return t, "ok"


def threshold_access_block_start(doc):
    """threshold-access の中身の block_start（閾値を決める期間の区画の始まり）。"""
    v = doc.get("block_start") if isinstance(doc, dict) else None
    if not isinstance(v, str):
        raise LedgerError("threshold-access の記録の中身に block_start が無い")
    return v


# ---------------------------------------------------------------- 取得の記録（start と result）


def acquisition_result_fields(record, doc):
    """acquisition-result の中身を検査し、(start_seq, kept_rows_sha256) を返す。"""
    _check_doc_kind(record, doc)
    start_seq = doc.get("start_seq")
    kept = doc.get("kept_rows_sha256")
    if type(start_seq) is not int or start_seq < 1:
        raise LedgerError("seq %d の acquisition-result の start_seq が正の整数でない"
                          % record["seq"])
    if not isinstance(kept, str) or not HEX64.match(kept):
        raise LedgerError("seq %d の acquisition-result の kept_rows_sha256 の形が違う"
                          % record["seq"])
    return start_seq, kept


def check_acquisition_pairs(records, result_start_seqs):
    """acquisition-start と acquisition-result の対応を照合する。

    result_start_seqs: {result の seq: その中身の start_seq}。
    照合すること：
      - result が参照する start が、kind=acquisition-start の記録として実在すること
      - result の seq が、その start の seq より後であること
      - 一つの start に result が一つだけであること
    返り値: {start の seq: result の seq か None}。食い違えば LedgerError。
    """
    by_seq = {r["seq"]: r for r in records}
    starts = [r["seq"] for r in records if r["kind"] == ACQ_START_KIND]
    results = [r["seq"] for r in records if r["kind"] == ACQ_RESULT_KIND]
    if sorted(result_start_seqs) != sorted(results):
        raise LedgerError("acquisition-result の記録と、照合に渡した中身の一覧が一致しない")
    pairs = {s: None for s in starts}
    for rseq in results:
        sseq = result_start_seqs[rseq]
        start = by_seq.get(sseq)
        if start is None or start["kind"] != ACQ_START_KIND:
            raise LedgerError("seq %d の acquisition-result が参照する seq %d は、"
                              "acquisition-start の記録ではない（実在しない）" % (rseq, sseq))
        if not rseq > sseq:
            raise LedgerError("seq %d の acquisition-result が、参照する acquisition-start "
                              "（seq %d）より前にある" % (rseq, sseq))
        if pairs[sseq] is not None:
            raise LedgerError("seq %d の acquisition-start に、acquisition-result が二つ以上ある"
                              "（seq %d と seq %d）" % (sseq, pairs[sseq], rseq))
        pairs[sseq] = rseq
    return pairs


def acquisition_start_fields(doc):
    """acquisition-start の中身の fetch（取得のコードのパスと sha256）を検査して返す。T-009。"""
    fetch = doc.get("fetch") if isinstance(doc, dict) else None
    if not isinstance(fetch, dict) or sorted(fetch) != ["code_path", "code_sha256"]:
        raise LedgerError("acquisition-start の中身の fetch のキーが code_path・code_sha256 でない")
    path, sha = fetch["code_path"], fetch["code_sha256"]
    if (not isinstance(path, str) or path == "" or path.startswith("/") or "\\" in path
            or any(part in ("", ".", "..") for part in path.split("/"))):
        raise LedgerError("acquisition-start の fetch.code_path が相対パスの正規の形でない")
    if not isinstance(sha, str) or not HEX64.match(sha):
        raise LedgerError("acquisition-start の fetch.code_sha256 の形が違う")
    return path, sha


# ---------------------------------------------------------------- candidates の検査（T-013）

# candidates の記録の対象。role とパスの組は固定で、これ以外の対象は認めない。
# output は sealed/candidates-output-<sha256>.json（下の CANDIDATES_OUTPUT_RE）。
CANDIDATES_SOURCES = (
    ("docs/stats/candidates.md", "doc"),
    ("src/stats/candidates.py", "code"),
    ("tests/stats/test_candidates.py", "test"),
    ("src/stats/periods.py", "import"),
)
CANDIDATES_SCRIPT = "src/stats/candidates.py"
CANDIDATES_OUTPUT_RE = re.compile(r"\Asealed/candidates-output-([0-9a-f]{64})\.json\Z")


def candidates_output_rel(sha):
    return "sealed/candidates-output-%s.json" % sha


def check_candidates_record(record):
    """candidates の記録の対象の形を照合する。output の対象を返す。

    - 対象は CANDIDATES_SOURCES の 4 つと output の 1 つ、合わせて 5 つだけ。
    - 各 role のパスが決まったものと同じ。
    - output のパスが sealed/candidates-output-<sha256>.json の形で、<sha256> が記録の
      output の sha256 と同じ。
    """
    seq = record["seq"]
    if record["kind"] != CANDIDATES_KIND:
        raise LedgerError("seq %d は candidates の記録ではない" % seq)
    want = dict((role, path) for path, role in CANDIDATES_SOURCES)
    got = {}
    for t in record["targets"]:
        if t["role"] in got:
            raise LedgerError("seq %d の candidates の記録に、role %s の対象が二つ以上ある"
                              % (seq, t["role"]))
        got[t["role"]] = t
    if sorted(got) != sorted(list(want) + ["output"]):
        raise LedgerError("seq %d の candidates の記録の対象の role が、決まった 5 つ（%s）と"
                          "一致しない（あるのは %s）"
                          % (seq, "、".join(sorted(list(want) + ["output"])),
                             "、".join(sorted(got))))
    for role, path in want.items():
        if got[role]["path"] != path:
            raise LedgerError("seq %d の candidates の記録の %s のパスが %s でない（%s）"
                              % (seq, role, path, got[role]["path"]))
    out = got["output"]
    m = CANDIDATES_OUTPUT_RE.match(out["path"])
    if not m:
        raise LedgerError("seq %d の candidates の記録の output のパスが "
                          "sealed/candidates-output-<sha256>.json の形でない" % seq)
    if m.group(1) != out["sha256"]:
        raise LedgerError("seq %d の candidates の記録の output のファイル名の sha256 が、"
                          "記録の sha256 と一致しない" % seq)
    return out


def _increasing_positive_ints(v):
    return (isinstance(v, list) and v and all(type(x) is int and x >= 1 for x in v)
            and all(a < b for a, b in zip(v, v[1:])))


def check_candidates_output(doc):
    """candidates の出力（JSON）の形を照合する。(倍率の一覧, 判定期間の一覧) を返す。

    - threshold_multipliers・horizon_days が、正の整数の、狭義に増える空でない一覧。
    - combinations が、倍率と判定期間のすべての組（[倍率, 判定期間]）とちょうど一致し、
      重複が無い。combination_count がその数。
    """
    if not isinstance(doc, dict):
        raise LedgerError("candidates の出力が JSON のオブジェクトでない")
    ms, hs = doc.get("threshold_multipliers"), doc.get("horizon_days")
    if not _increasing_positive_ints(ms):
        raise LedgerError("candidates の出力の threshold_multipliers が、正の整数の増える一覧でない")
    if not _increasing_positive_ints(hs):
        raise LedgerError("candidates の出力の horizon_days が、正の整数の増える一覧でない")
    combos = doc.get("combinations")
    if not isinstance(combos, list) or not all(
            isinstance(c, list) and len(c) == 2 for c in combos):
        raise LedgerError("candidates の出力の combinations が [倍率, 判定期間] の一覧でない")
    pairs = [tuple(c) for c in combos]
    want = {(m, h) for m in ms for h in hs}
    if len(pairs) != len(set(pairs)) or set(pairs) != want:
        raise LedgerError("candidates の出力の combinations が、倍率と判定期間のすべての組と"
                          "一致しない")
    if doc.get("combination_count") != len(want):
        raise LedgerError("candidates の出力の combination_count が組の数 %d と一致しない"
                          % len(want))
    return ms, hs


def first_acquisition_start(records):
    """最初の kind=acquisition-start の記録。無ければ None。"""
    for r in records:
        if r["kind"] == ACQ_START_KIND:
            return r
    return None


def check_candidates_order(records):
    """candidates の記録が、すべて最初の acquisition-start の記録より前にあるか。T-013、T-014。

    CLAUDE.md は、閾値と判定期間の候補を「手法を作る期間のデータに触れる前に」封印すると
    決めている。採用の区切り（threshold-access）より強い条件なので、別に照合する。
    次のどちらかなら LedgerError。
      - 後ろにある candidates の記録が一つでもある（T-013）
      - acquisition-start があるのに、その前に candidates の記録が 1 件も無い（T-014。
        T-013 の監査 B-1。候補を封印しないまま取得を始めた状態を通さないため）
    返り値: 最初の acquisition-start の記録（無ければ None）。
    """
    cut = first_acquisition_start(records)
    if cut is None:
        return None
    if not any(r["kind"] == CANDIDATES_KIND and r["seq"] < cut["seq"] for r in records):
        raise LedgerError("acquisition-start の記録（seq %d）より前に、candidates の記録が無い。"
                          "候補は、手法を作る期間のデータに触れる前に封印する決まり" % cut["seq"])
    late = [r["seq"] for r in records if r["kind"] == CANDIDATES_KIND and r["seq"] > cut["seq"]]
    if late:
        raise LedgerError("candidates の記録（seq %s）が、最初の acquisition-start の記録（seq %d）"
                          "より後にある。候補は、手法を作る期間のデータに触れる前に封印する決まり"
                          % (", ".join(map(str, late)), cut["seq"]))
    return cut


# ---------------------------------------------------------------- J とエンバーゴ（T-017）


def candidates_max_j(doc):
    """candidates の出力の J（判定が読む最後の日のずれ）の最大値。T-017（T-014 の監査 軽4）。

    出力の last_read_offset_days は {判定期間 H の文字列: その J}。キーが horizon_days と
    ちょうど一致し、各 J が整数で H 以上であること（判定は t+H まで読むので J < H はありえない）を
    確かめる。今の候補では J = H で、最大は 56。
    """
    check_candidates_output(doc)
    hs = doc["horizon_days"]
    js = doc.get("last_read_offset_days")
    if not isinstance(js, dict) or sorted(js) != sorted(str(h) for h in hs):
        raise LedgerError("candidates の出力の last_read_offset_days のキーが、horizon_days と一致しない")
    for h in hs:
        j = js[str(h)]
        if type(j) is not int or j < h:
            raise LedgerError("candidates の出力の last_read_offset_days[%d] が、%d 以上の整数でない"
                              % (h, h))
    return max(js.values())


def periods_embargo_days(doc):
    """periods の出力の rules.embargo_days（正の整数）。"""
    v = doc.get("rules", {}).get("embargo_days") if isinstance(doc, dict) else None
    if type(v) is not int or v < 1:
        raise LedgerError("periods の出力に rules.embargo_days（正の整数）が無い")
    return v


def _last_before(records, kind, seq):
    """seq より前にある kind の最後の記録（無ければ None）。"""
    found = None
    for r in records:
        if r["kind"] == kind and r["seq"] < seq:
            found = r
    return found


def triggers_j(record, read_json):
    """periods-triggers の記録の last_read_offset_days（null なら None）。"""
    return triggers_values(read_json(record, "triggers"))["last_read_offset_days"]


def candidates_j_max(records, read_json):
    """すべての candidates の記録の出力の J の最大。candidates の記録が無ければ None。"""
    cands = [r for r in records if r["kind"] == CANDIDATES_KIND]
    if not cands:
        return None
    return max(candidates_max_j(read_json(r, "output")) for r in cands)


def check_j_triggers_before_method(records, read_json, j_max):
    """最初の method-access より後の periods-triggers の J（last_read_offset_days）を確かめる。
    T-023（T-017 の再提出1回目の監査 中1）、T-027（T-023 の監査 軽B）。

    docs/stats/periods.md 8章 (2)：「J は試運転の手順4の前に決めて封印の記録に追記する。
    J は手法を作る期間のデータを見ずに決まる」。J は candidates の出力（method-access より前に
    封印する決まり）で決まっていて、その値は J の最大 j_max である（8章 (2) の案B）。
    - method-access の後の periods-triggers の J が null でなく、j_max と等しくなければ
      LedgerError（採用されるかどうかに関わらない）。j_max が None（candidates が無い）なら、
      method-access の後の J はすべて LedgerError。
    - T-027 で、j_max と等しい J は method-access の後でも許すことにした（T-023 では一律に拒んで
      いた）。手法を作る期間のデータを見て決めてよいほかの三つのきっかけ（periods.md 8章 (2)）を
      method-access の後に追記するとき、作り直しが要る場合は、その記録にも J が要るため
      （採用されるのは最後の periods-triggers で、その J が null なら照合 (2) に通らない）。
      等しい値に限るので、J とエンバーゴ（max(1 件目, j_max)）は、データを見たあとでも動かない。
    - J が null の periods-triggers は、ここでは拒まない（作り直しが要る場合に採用されれば、
      check_horizon_embargo の (2) で失敗する。書く仕組み seal_triggers は、その追記を拒む）。
    method-access が無ければ何もしない。返り値: 最初の method-access の記録か None。
    """
    m = next((r for r in records if r["kind"] == METHOD_ACCESS_KIND), None)
    if m is None:
        return None
    for r in records:
        if r["kind"] == TRIGGERS_KIND and r["seq"] > m["seq"]:
            j = triggers_j(r, read_json)
            if j is not None and j != j_max:
                raise LedgerError("periods-triggers（seq %d）が J（last_read_offset_days %d）を持ち、"
                                  "最初の method-access（seq %d）より後にあるが、candidates の J の最大 %s "
                                  "と等しくない。J は試運転の手順4の前に決まっている"
                                  "（docs/stats/periods.md 8章 (2)）。手順4の後に書けるのは、その値だけ"
                                  % (r["seq"], j, m["seq"], j_max))
    return m


def check_triggers_append(records, read_json, values):
    """periods-triggers を 1 件追記してよいかを、書く前に確かめる（seal_triggers が使う）。T-027。

    values はきっかけの値（4 つのキー）。次のどれかなら LedgerError。
    - 鎖に method-access があり、J が null でなく、candidates の J の最大と等しくない
      （check_j_triggers_before_method と同じ規則）。
    - J の最大が periods の 1 件目の embargo_days を超える（作り直しが要る）のに、J が null
      （T-023 の監査 軽B：この記録が採用されると threshold-access が二度と通らなくなるため。
      作り直しが要る場合は、ほかのきっかけと一緒に J の最大を渡す）。
    """
    j_max = candidates_j_max(records, read_json)
    j = values.get("last_read_offset_days")
    m = next((r for r in records if r["kind"] == METHOD_ACCESS_KIND), None)
    if m is not None and j is not None and j != j_max:
        raise LedgerError("method-access の記録（seq %d）がある。その後に書ける J（last_read_offset_days）は"
                          "、candidates の J の最大 %s だけ（docs/stats/periods.md 8章 (2)）。%d は追記しない"
                          % (m["seq"], j_max, j))
    versions = records_of_kind(records, PERIODS_KIND)
    if j_max is not None and versions and j is None:
        first = periods_embargo_days(read_json(versions[0][1], "output"))
        if j_max > first:
            raise LedgerError("candidates の J の最大 %d が periods の 1 件目の embargo_days %d を超える"
                              "（作り直しが要る）ので、J が null の periods-triggers は追記しない。"
                              "採用されると照合に通らなくなるため。--last-read-offset-days %d も渡す"
                              % (j_max, first, j_max))


def check_horizon_embargo(records, read_json):
    """candidates の J の最大と、採用される periods・periods-triggers を照合する。T-017、T-023。

    T-014 の監査 軽4 で加え、T-017 の差し戻し1回目の中2 で、照合の相手を「その時点で採用される
    版」に改めた。T-023（T-017 の再提出1回目の監査 中1）で、J の値とエンバーゴを「等しい」ことの
    照合に改め、J を持つ periods-triggers を最初の method-access より前に限った
    （以前は J が大きすぎても通り、method-access の後に J を足してエンバーゴを作り直せた）。

    read_json(記録, role) は、記録の対象のファイルを sha256 を照合して JSON で返す関数。
    - J の最大 = すべての candidates の記録の出力の J の最大（candidates_max_j）。
    - 期待するエンバーゴ E = max(periods の 1 件目の embargo_days, J の最大)
      （docs/stats/periods.md 8章 (1) の表の「EMBARGO_DAYS = max(90, J)」。1 件目は 90）。
    - 照合する時点 P = 最初の method-access と、最初の threshold-access（あるものすべて）。
      P ごとに、P より前の periods の最後の記録（P が threshold-access なら、採用される periods）と、
      P より前の periods-triggers の最後の記録（同じく、採用される periods-triggers）を使う。
    - 次のどれかなら LedgerError。
      (0) 最初の method-access より後の periods-triggers が、J の最大と等しくない J を持つ
          （check_j_triggers_before_method。採用されるかどうかに関わらない。T-027 で、等しい J は
          許すことにした）。
      (1) P で採用される periods の rules.embargo_days が E と等しくない
          （J を覆わない区切りも、きっかけの無い延長も拒む。periods.md 8章 (1)）。
      (2) J の最大が periods の 1 件目の embargo_days を超えている（作り直しが要る）のに、
          P で採用される periods-triggers が無いか、その last_read_offset_days が null。
      (3) P で採用される periods-triggers の last_read_offset_days が null でなく、J の最大と
          等しくない（小さすぎる値も、大きすぎる値も拒む）。
    - P が一つも無いうちは (0) 以外を失敗にしない。J の最大が 1 件目の embargo_days 以下なら
      "within"、超えていれば "pending"。
    返り値: {"j_max", "embargo_first", "embargo_expected", "status", "points"}。points は
      [(P の記録, periods の記録, その embargo_days, periods-triggers の記録か None, その J か None)]。
      status は "no-candidates"、"within"（作り直しは要らず、すべての P で照合に通る）、
      "ok"（作り直しが要り、すべての P で照合に通る）、"pending"。
    """
    j_max = candidates_j_max(records, read_json)
    check_j_triggers_before_method(records, read_json, j_max)
    out = {"j_max": None, "embargo_first": None, "embargo_expected": None,
           "status": "no-candidates", "points": []}
    if j_max is None:
        return out
    out["j_max"] = j_max
    versions = records_of_kind(records, PERIODS_KIND)
    if not versions:
        raise LedgerError("periods の記録が無い")
    first = periods_embargo_days(read_json(versions[0][1], "output"))
    out["embargo_first"] = first
    expected = max(first, j_max)
    out["embargo_expected"] = expected
    rebuild = j_max > first
    marks = []
    for kind in (METHOD_ACCESS_KIND, THRESHOLD_ACCESS_KIND):
        m = next((r for r in records if r["kind"] == kind), None)
        if m is not None:
            marks.append(m)
    if not marks:
        out["status"] = "pending" if rebuild else "within"
        return out
    for p in sorted(marks, key=lambda r: r["seq"]):
        per = _last_before(records, PERIODS_KIND, p["seq"])
        if per is None:
            raise LedgerError("%s の記録（seq %d）より前に periods の記録が無い" % (p["kind"], p["seq"]))
        emb = periods_embargo_days(read_json(per, "output"))
        trg = _last_before(records, TRIGGERS_KIND, p["seq"])
        j = None if trg is None else triggers_j(trg, read_json)
        where = "%s の記録（seq %d）の時点" % (p["kind"], p["seq"])
        if emb < j_max:
            raise LedgerError("%sで採用される periods（seq %d）の embargo_days %d が、candidates の J の"
                              "最大 %d より小さい。J を覆う区切りを、その前に封印する必要がある"
                              % (where, per["seq"], emb, j_max))
        if emb != expected:
            raise LedgerError("%sで採用される periods（seq %d）の embargo_days %d が、max(periods の "
                              "1 件目の embargo_days %d, candidates の J の最大 %d) = %d と等しくない。"
                              "きっかけの無い変更はしない決まり（docs/stats/periods.md 8章 (1)）"
                              % (where, per["seq"], emb, first, j_max, expected))
        if rebuild and (j is None or j < j_max):
            raise LedgerError("%sで採用される periods-triggers（%s）の last_read_offset_days が、"
                              "candidates の J の最大 %d 以上でない。J の最大が periods の 1 件目の "
                              "embargo_days %d を超えるので、その前に last_read_offset_days が %d の "
                              "periods-triggers の記録が要る"
                              % (where, "無し" if trg is None else "seq %d、%r" % (trg["seq"], j),
                                 j_max, first, j_max))
        if j is not None and j != j_max:
            raise LedgerError("%sで採用される periods-triggers（seq %d）の last_read_offset_days %d が、"
                              "candidates の J の最大 %d と等しくない" % (where, trg["seq"], j, j_max))
        out["points"].append((p, per, emb, trg, j))
    out["status"] = "ok" if rebuild else "within"
    return out


# ---------------------------------------------------------------- 手順4の開始（method-access。T-014）

METHOD_BLOCK = "method"
METHOD_DOC_KEYS = ("block_end", "block_start", "drand", "kind", "ledger_head", "step")


def check_method_access_order(records):
    """各 method-access の記録より前に、candidates と acquisition-result の記録があるか。T-014。

    手順4（手法を作る期間のデータそのものの取得）は、候補の封印（candidates）と手順3の
    取得の完了（acquisition-result）の後に行う決まり。どれかの method-access の前に、
    どちらかが 1 件も無ければ LedgerError。
    返り値: method-access の記録の一覧（無ければ空）。
    """
    out = []
    for m in records:
        if m["kind"] != METHOD_ACCESS_KIND:
            continue
        before = [r["kind"] for r in records if r["seq"] < m["seq"]]
        for need in (CANDIDATES_KIND, ACQ_RESULT_KIND):
            if need not in before:
                raise LedgerError("method-access の記録（seq %d）より前に、%s の記録が無い。"
                                  "手順4は、候補の封印と手順3の取得の記録の後に行う決まり"
                                  % (m["seq"], need))
        out.append(m)
    return out


def method_block_of(root, records):
    """periods の 1 件目（最初に封印した版）の出力の、手法を作る期間（method）の区画。"""
    versions = records_of_kind(records, PERIODS_KIND)
    if not versions:
        raise LedgerError("periods の記録が無い")
    blocks = blocks_of(read_target_json(root, versions[0][1], "output"))
    if METHOD_BLOCK not in blocks:
        raise LedgerError("periods の 1 件目の出力に method の期間が無い")
    return blocks[METHOD_BLOCK]


def check_method_access_doc(root, records, record, doc):
    """method-access の中身のキーと区画を照合する（drand と ledger_head は check_drand_record）。

    キーは METHOD_DOC_KEYS の 6 つだけ。block_start・block_end は、periods の 1 件目の出力の
    method の区画と一致しなければならない。返り値: (block_start, block_end)。
    """
    _check_doc_kind(record, doc)
    if tuple(sorted(doc)) != METHOD_DOC_KEYS:
        raise LedgerError("seq %d の method-access の中身のキーが、決まった 6 つ（%s）と一致しない"
                          % (record["seq"], "、".join(METHOD_DOC_KEYS)))
    want = method_block_of(root, records)
    got = (doc["block_start"], doc["block_end"])
    if got != tuple(want):
        raise LedgerError("seq %d の method-access の区画 %s〜%s が、periods の 1 件目の method の"
                          "区画 %s〜%s と一致しない" % (record["seq"], got[0], got[1], want[0],
                                                     want[1]))
    return got


# ---------------------------------------------------------------- GKG の取得の run の開始（T-031）

# 中身のキー（決まった 13 個だけ）。公開してよい値だけで、パスはリポジトリの中の相対パス
# （取得のコード）に限る。保存先のディスク、ユーザー名、VolumeUUID などは入れない。
GKG_RUN_DOC_KEYS = ("code_path", "code_sha256", "drand", "exclusion_rule_record_sha256",
                    "exclusion_rule_seq", "filelist_sha256", "kind", "ledger_head",
                    "method_access_seq", "mode", "run_id", "step", "trial_days")
GKG_RUN_MODES = ("trial", "official")
# 試しの run の日数の上限。収集係の src/collector/gkg.py の TRIAL_DAYS（3 日）と揃える（T-031 の中3）。
TRIAL_DAYS_MAX = 3
# 試しの run の日。収集係の src/collector/gkg.py の TRIAL_DAYS と同じ 3 日ちょうど（T-037。T-031 の
# 監査 軽1）。手法を作る期間の最初の 3 日。値はここに写し、テストで gkg.py と同じことを確かめる。
TRIAL_DAYS = ("2015-03-02", "2015-03-03", "2015-03-04")
RUN_ID_RE = re.compile(r"\A[0-9a-f]{16}\Z")
DAY_RE = re.compile(r"\A\d{4}-\d{2}-\d{2}\Z")


def _first_of_kind(records, kind):
    return next((r for r in records if r["kind"] == kind), None)


def check_gkg_run_doc(records, record, doc, read_json):
    """gkg-run-start の中身を照合する（drand と ledger_head は check_drand_record）。T-031。

    read_json(記録, role) は、記録の対象のファイルを sha256 を照合して JSON で返す関数。
    次のどれかなら LedgerError。
      - キーが GKG_RUN_DOC_KEYS の 13 個と一致しない。kind が記録と違う。step が 4 でない。
      - mode が trial・official のどちらでもない。
      - code_path が相対パスの正規の形でない。code_sha256 が 64 桁の16進でない。
      - run_id が 16 桁の16進でない、または code_sha256 の先頭 16 桁と違う（収集係の run_id の
        決め方。src/collector/gkg.py 5章）。
      - filelist_sha256 が、最初の method-access より前のただ 1 件の acquisition-result の
        kept_rows_sha256 と違う（gkg_filelist_sha256。手順3で封印した一覧だけを使う。T-031 の中1）。
      - method_access_seq が、最初の method-access の記録の seq でない。
      - trial_days：mode が trial なら、日付（YYYY-MM-DD）の、狭義に増える 1〜TRIAL_DAYS_MAX（3）日の
        一覧で、すべて periods の 1 件目の method の区画の中で、TRIAL_DAYS（収集係の 3 日）と
        ちょうど同じ（T-037）。mode が official なら null。
      - exclusion_rule_seq が、最初の gkg-run-start より前の記録の seq でない（gkg-run-start 自身や、
        試しの run のあとの記録は指せない。T-031 の中1）。exclusion_rule_record_sha256 が、
        その記録の行の正規の形（canonical_line）の sha256 と違う。
        除外の規則の kind（stats-order1）の最初の記録であることも照合する（T-037）。
        その記録が、除外の規則の kind（ORDER1_KIND = stats-order1）の最初の記録であること（T-037）。
    返り値: 中身の dict（そのまま）。
    """
    seq = record["seq"]
    _check_doc_kind(record, doc)
    if not isinstance(doc, dict) or tuple(sorted(doc)) != GKG_RUN_DOC_KEYS:
        raise LedgerError("seq %d の gkg-run-start の中身のキーが、決まった %d 個（%s）と一致しない"
                          % (seq, len(GKG_RUN_DOC_KEYS), "、".join(GKG_RUN_DOC_KEYS)))
    if type(doc["step"]) is not int or doc["step"] != 4:
        raise LedgerError("seq %d の gkg-run-start の step が 4 でない" % seq)
    mode = doc["mode"]
    if mode not in GKG_RUN_MODES:
        raise LedgerError("seq %d の gkg-run-start の mode が trial・official のどちらでもない" % seq)
    acquisition_start_fields({"fetch": {"code_path": doc["code_path"],
                                        "code_sha256": doc["code_sha256"]}})
    if not isinstance(doc["run_id"], str) or not RUN_ID_RE.match(doc["run_id"]) \
            or doc["run_id"] != doc["code_sha256"][:16]:
        raise LedgerError("seq %d の gkg-run-start の run_id が、code_sha256 の先頭 16 桁と一致しない"
                          % seq)
    fl = doc["filelist_sha256"]
    m = _first_of_kind(records, METHOD_ACCESS_KIND)
    want = gkg_filelist_sha256(records, read_json)
    if not isinstance(fl, str) or not HEX64.match(fl) or fl != want:
        raise LedgerError("seq %d の gkg-run-start の filelist_sha256 が、最初の method-access より前の"
                          "ただ 1 件の acquisition-result の kept_rows_sha256（%s）と一致しない" % (seq, want))
    if m is None or type(doc["method_access_seq"]) is not int or doc["method_access_seq"] != m["seq"]:
        raise LedgerError("seq %d の gkg-run-start の method_access_seq %r が、最初の method-access の"
                          "記録の seq（%s）と違う" % (seq, doc["method_access_seq"],
                                                    "無し" if m is None else m["seq"]))
    days = doc["trial_days"]
    if mode == "official":
        if days is not None:
            raise LedgerError("seq %d の gkg-run-start（official）の trial_days が null でない" % seq)
    else:
        versions = records_of_kind(records, PERIODS_KIND)
        if not versions:
            raise LedgerError("periods の記録が無い")
        start, end = blocks_of(read_json(versions[0][1], "output"))[METHOD_BLOCK]
        ok = (isinstance(days, list) and 0 < len(days) <= TRIAL_DAYS_MAX
              and all(isinstance(d, str) and DAY_RE.match(d) for d in days)
              and all(a < b for a, b in zip(days, days[1:])))
        if ok:
            for d in days:
                try:
                    datetime.date.fromisoformat(d)
                except ValueError:
                    ok = False
        if not ok:
            raise LedgerError("seq %d の gkg-run-start（trial）の trial_days が、日付（YYYY-MM-DD）の"
                              "増える一覧で 1〜%d 日のものでない" % (seq, TRIAL_DAYS_MAX))
        outside = [d for d in days if not start <= d <= end]
        if outside:
            raise LedgerError("seq %d の gkg-run-start（trial）の trial_days %s が、手法を作る期間の"
                              "区画 %s〜%s の外" % (seq, ", ".join(outside), start, end))
        if tuple(days) != TRIAL_DAYS:
            raise LedgerError("seq %d の gkg-run-start（trial）の trial_days %s が、収集係の TRIAL_DAYS（%s）と"
                              "同じでない（T-037）" % (seq, ", ".join(days), ", ".join(TRIAL_DAYS)))
    ex = doc["exclusion_rule_seq"]
    o1 = _first_of_kind(records, ORDER1_KIND)
    if o1 is None or ex != o1["seq"]:
        raise LedgerError("seq %d の gkg-run-start の exclusion_rule_seq %r が、除外の規則の kind（%s）の最初の"
                          "記録の seq（%s）でない（T-037。T-031 の監査 中2）"
                          % (seq, ex, ORDER1_KIND, "無し" if o1 is None else o1["seq"]))
    first_run = _first_of_kind(records, GKG_RUN_KIND)
    limit = seq if first_run is None else min(seq, first_run["seq"])
    target = next((r for r in records if r["seq"] == ex), None) if type(ex) is int else None
    if target is None or not ex < limit:
        raise LedgerError("seq %d の gkg-run-start の exclusion_rule_seq %r が、最初の gkg-run-start（seq %d）"
                          "より前の記録の seq でない" % (seq, ex, limit))
    if doc["exclusion_rule_record_sha256"] != sha256_hex(canonical_line(target)):
        raise LedgerError("seq %d の gkg-run-start の exclusion_rule_record_sha256 が、seq %d の記録の行の"
                          "sha256 と一致しない" % (seq, ex))
    return doc


def gkg_filelist_sha256(records, read_json):
    """gkg-run-start が使ってよいファイル一覧の sha256。T-031 の中1。

    最初の method-access より前の acquisition-result が、ちょうど 1 件でなければ LedgerError
    （どの一覧を使うかを、試しの run を見たあとで選べないようにするため。収集係の関門も 1 件を求める）。
    返り値: その記録の kept_rows_sha256。
    """
    m = _first_of_kind(records, METHOD_ACCESS_KIND)
    results = [r for r in records if r["kind"] == ACQ_RESULT_KIND and (m is None or r["seq"] < m["seq"])]
    if len(results) != 1:
        raise LedgerError("最初の method-access より前の acquisition-result が %d 件で、ちょうど 1 件でない。"
                          "gkg-run-start が使うファイル一覧を決められない" % len(results))
    return acquisition_result_fields(results[0], read_json(results[0], ACQ_RESULT_KIND))[1]


def check_gkg_run_order(records):
    """gkg-run-start の順序の照合。T-031。返り値: gkg-run-start の記録の一覧。
      - どの gkg-run-start も、最初の method-access の記録より後にあること。
      - どの gkg-run-start も、最初の threshold-access の記録より前にあること（T-031 の中2）。
      - mode が official の記録は 1 件だけ（0 件は可）。
      - mode が trial の記録は、official の記録より前にだけある。
    mode は記録の中身にあるので、modes（{seq: mode}）を渡す形にせず、check_gkg_run_modes で行う。
    ここでは位置（method-access の後）だけを確かめる。
    """
    runs = [r for r in records if r["kind"] == GKG_RUN_KIND]
    if not runs:
        return runs
    m = _first_of_kind(records, METHOD_ACCESS_KIND)
    cut = first_threshold_access(records)
    for r in runs:
        if m is None or r["seq"] < m["seq"]:
            raise LedgerError("gkg-run-start の記録（seq %d）が、最初の method-access の記録%sより前にある。"
                              "GKG の取得は手順4の記録の後に行う決まり"
                              % (r["seq"], "" if m is None else "（seq %d）" % m["seq"]))
        if cut is not None and r["seq"] > cut["seq"]:
            raise LedgerError("gkg-run-start の記録（seq %d）が、最初の threshold-access の記録（seq %d）より"
                              "後にある。閾値を決める期間に触れたあとで、手法を作る期間の GKG の取得を"
                              "始めない（T-031 の中2）" % (r["seq"], cut["seq"]))
    return runs


GKG_MANIFESTS = {"trial": "data/manifest/gdelt-gkg-trial.jsonl",
                 "official": "data/manifest/gdelt-gkg-method.jsonl"}


def check_gkg_manifests(records, read_json, manifests):
    """gkg-run-start の記録と、収集係のマニフェストの run-start の行を照らす（T-041。T-031 の監査 中1 の残り）。

    manifests：{"trial": バイト列か None, "official": バイト列か None}（None はマニフェストが無い）。
    マニフェストが無い mode：その mode の gkg-run-start の記録が 1 件以上あれば LedgerError（記録だけあって
    行が無い。T-043。T-041 の監査 軽-1）。0 件なら照らさない（返り値の値が None）。
    マニフェストのある mode について、次のどれかなら LedgerError：
      - run-start の行に gkg_run_seq（正の整数）と gkg_run_record_sha256（64 桁）が無い。
      - その seq の記録が無いか、kind が gkg-run-start でない、行の正規の形の sha256 が違う、
        中身の mode・run_id が行と違う（収集係の gkg.check_sealed_run と同じ照らし方）。
      - run-start の行の異なる run_id の数が、その mode の gkg-run-start の記録の件数と違う
        （試しの run の回数は「異なる run_id の数」。同じ run_id の行が 2 行以上あるのは正直な
        やり直しとして通す）。
      - official の run-start の行の trial_run_ids が、official の記録より前の trial の記録の run_id の一覧
        （seq の順）と違う（T-043。T-041 の監査 軽-2。src/collector/README.md 6.5.5 の第三者の照らし方3）。
    返り値: {mode: (異なる run_id の数, 行の数) か None（マニフェストが無い）}。
    """
    by_seq = {r["seq"]: r for r in records}
    out = {}
    for mode in ("trial", "official"):
        body = manifests.get(mode)
        if body is None:
            have = [r["seq"] for r in records if r["kind"] == GKG_RUN_KIND
                    and read_json(r, GKG_RUN_KIND).get("mode") == mode]
            if have:
                raise LedgerError("%s が無いのに、mode %s の gkg-run-start の記録がある（seq %s）。記録だけあって"
                                  "run-start の行が無い（マニフェストをコミットしたあとで照らす）"
                                  % (GKG_MANIFESTS[mode], mode, ", ".join(map(str, have))))
            out[mode] = None
            continue
        path = GKG_MANIFESTS[mode]
        ids, n = set(), 0
        for i, raw in enumerate(body.split(b"\n"), 1):
            if not raw.strip():
                continue
            try:
                row = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, ValueError):
                raise LedgerError("%s の %d 行目が JSON として読めない" % (path, i)) from None
            if not isinstance(row, dict) or row.get("kind") != "run-start":
                continue
            n += 1
            seq, sha = row.get("gkg_run_seq"), row.get("gkg_run_record_sha256")
            if type(seq) is not int or seq < 1 or not isinstance(sha, str) or not HEX64.match(sha):
                raise LedgerError("%s の %d 行目（run-start）に gkg_run_seq・gkg_run_record_sha256 が無いか、形が違う"
                                  % (path, i))
            rec = by_seq.get(seq)
            if rec is None or rec["kind"] != GKG_RUN_KIND:
                raise LedgerError("%s の %d 行目の gkg_run_seq %d の記録が、gkg-run-start でない（または無い）"
                                  % (path, i, seq))
            if sha256_hex(canonical_line(rec)) != sha:
                raise LedgerError("%s の %d 行目の gkg_run_record_sha256 が、seq %d の記録の行と一致しない"
                                  % (path, i, seq))
            doc = read_json(rec, GKG_RUN_KIND)
            if doc.get("mode") != mode or doc.get("mode") != row.get("mode") \
                    or doc.get("run_id") != row.get("run_id"):
                raise LedgerError("%s の %d 行目（mode %r・run_id %r）が、seq %d の gkg-run-start（mode %r・run_id %r）と"
                                  "合わない" % (path, i, row.get("mode"), row.get("run_id"), seq,
                                                doc.get("mode"), doc.get("run_id")))
            ids.add(row["run_id"])
            if mode == "official":
                want = [read_json(r, GKG_RUN_KIND).get("run_id") for r in records
                        if r["kind"] == GKG_RUN_KIND and r["seq"] < seq
                        and read_json(r, GKG_RUN_KIND).get("mode") == "trial"]
                if row.get("trial_run_ids") != want:
                    raise LedgerError("%s の %d 行目の trial_run_ids %r が、official の記録（seq %d）より前の trial の"
                                      "記録の run_id の一覧 %r と違う" % (path, i, row.get("trial_run_ids"), seq, want))
        # T-066：run-start の行の入力の値と gkg-run-start の中身、ほかの行（day・run-complete など）の照合
        check_gkg_manifest_rows(records, read_json, mode, body)
        recs = [r for r in records if r["kind"] == GKG_RUN_KIND
                and read_json(r, GKG_RUN_KIND).get("mode") == mode]
        if len(ids) != len(recs):
            raise LedgerError("%s の run-start の異なる run_id の数 %d が、mode %s の gkg-run-start の記録の件数 %d と"
                              "違う" % (path, len(ids), mode, len(recs)))
        out[mode] = (len(ids), n)
    return out


# ---- T-066：マニフェストの行の照合（run-start の入力の値、day、run-complete）と、gkg-run-result

# マニフェストの行の kind（収集係の src/collector/gkg.py が書くもの）
GKG_ROW_KINDS = ("run-start", "run-resume", "run-stop", "day", "run-complete")
# どの行にも入っていて、同じ run_id の最初の run-start と同じでなければならない欄（gkg.py の base）
GKG_ROW_BASE = ("code_path", "code_sha256", "filelist_sha256", "method_access_seq", "mode", "official")
# run-start の行と gkg-run-start の中身で、同じでなければならない入力の値
GKG_START_INPUTS = ("mode", "run_id", "code_path", "code_sha256", "filelist_sha256", "method_access_seq",
                    "exclusion_rule_seq", "exclusion_rule_record_sha256")
_DAY_RE = re.compile(r"\A\d{4}-\d{2}-\d{2}\Z")


def _nonneg_int(v):
    return type(v) is int and v >= 0


def manifest_rows(body, path):
    """マニフェストのバイト列を [(行番号, dict)] にする。空行は飛ばす。JSON でない・dict でない行は LedgerError。"""
    out = []
    for i, raw in enumerate(body.split(b"\n"), 1):
        if not raw.strip():
            continue
        try:
            row = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            raise LedgerError("%s の %d 行目が JSON として読めない" % (path, i)) from None
        if not isinstance(row, dict):
            raise LedgerError("%s の %d 行目が JSON のオブジェクトでない" % (path, i))
        out.append((i, row))
    return out


def check_gkg_manifest_rows(records, read_json, mode, body):
    """マニフェスト（mode の1つ）の行を、封印の記録と照らす（T-066。T-063 の採点 中-1）。

    run-start の行：指している gkg-run-start の中身と、入力の値（GKG_START_INPUTS と、trial なら trial_days）が
      同じ。official は False/True が mode と合う。区画（block_start・block_end）が method_access_seq の
      method-access の区画と同じ。days・files_selected が 0 以上の整数で、trial なら days は trial_days の数以下。
    どの行も：kind が GKG_ROW_KINDS のどれか。run_id の最初の行が run-start。GKG_ROW_BASE の欄が、その run_id の
      最初の run-start と同じ。
    day の行：day が日付で、その run の区画（trial は trial_days、official は method-access の区画）の中。同じ run の
      中で日付が重ならない。file_name が gkg-<mode>-<run_id>-day-<YYYYMMDD>.tsv.gz。sha256 が 64 桁。
      files_ok + files_failed = files_listed、failed_files の数 = files_failed。
    run-complete の行：run ごとに多くて1行で、その run の最後の行。days が day の行の数と、run-start の days と
      同じ。files_ok・files_failed が day の行の合計と同じ。day の行の files_listed の合計が run-start の
      files_selected と同じ。
    返り値: {run_id: {"start": 最初の run-start, "days": [day の行], "complete": run-complete の行か None,
                      "complete_lineno": その行の番号か None}}（run_id の出てきた順）。
    """
    path = GKG_MANIFESTS[mode]
    by_seq = {r["seq"]: r for r in records}
    runs = {}
    for i, row in manifest_rows(body, path):
        kind, rid = row.get("kind"), row.get("run_id")
        where = "%s の %d 行目（%s）" % (path, i, kind)
        if kind not in GKG_ROW_KINDS:
            raise LedgerError("%s の %d 行目の kind %r が、マニフェストの行の種類（%s）でない"
                              % (path, i, kind, "・".join(GKG_ROW_KINDS)))
        if row.get("mode") != mode:
            raise LedgerError("%s の mode %r が、マニフェストの mode %s と違う" % (where, row.get("mode"), mode))
        run = runs.get(rid)
        if run is None:
            if kind != "run-start":
                raise LedgerError("%s：run_id %r の最初の行が run-start でない" % (where, rid))
            seq = row.get("gkg_run_seq")
            rec = by_seq.get(seq) if type(seq) is int else None
            if rec is None or rec["kind"] != GKG_RUN_KIND:
                raise LedgerError("%s の gkg_run_seq %r の記録が、gkg-run-start でない（または無い）" % (where, seq))
            doc = read_json(rec, GKG_RUN_KIND)
            run = runs[rid] = {"start": row, "doc": doc, "days": [], "seen": set(), "complete": None,
                               "complete_lineno": None}
        if run["complete"] is not None:
            raise LedgerError("%s：run_id %s の run-complete（%d 行目）より後に、同じ run の行がある"
                              % (where, rid, run["complete_lineno"]))
        first = run["start"]
        for k in GKG_ROW_BASE:
            if row.get(k) != first.get(k):
                raise LedgerError("%s の %s %r が、同じ run の最初の run-start の %r と違う"
                                  % (where, k, row.get(k), first.get(k)))
        if row.get("official") is not (mode == "official"):
            raise LedgerError("%s の official が mode %s と合わない" % (where, mode))
        doc = run["doc"]
        if kind == "run-start":
            for k in GKG_START_INPUTS:
                if row.get(k) != doc.get(k):
                    raise LedgerError("%s の %s %r が、gkg-run-start（seq %s）の中身の %r と違う"
                                      % (where, k, row.get(k), row.get("gkg_run_seq"), doc.get(k)))
            if mode == "trial":
                if row.get("trial") is not True or row.get("trial_days") != doc.get("trial_days"):
                    raise LedgerError("%s の trial・trial_days が、gkg-run-start の中身の trial_days %r と合わない"
                                      % (where, doc.get("trial_days")))
            elif "trial_days" in row or row.get("trial") is True:
                raise LedgerError("%s：正式な run の run-start に trial・trial_days がある" % where)
            ma = by_seq.get(doc.get("method_access_seq"))
            if ma is None or ma["kind"] != METHOD_ACCESS_KIND:
                raise LedgerError("%s の method_access_seq の記録が method-access でない" % where)
            mdoc = read_json(ma, METHOD_ACCESS_KIND)
            if (row.get("block_start"), row.get("block_end")) != (mdoc.get("block_start"), mdoc.get("block_end")):
                raise LedgerError("%s の区画 %s〜%s が、method-access（seq %d）の区画 %s〜%s と違う"
                                  % (where, row.get("block_start"), row.get("block_end"), ma["seq"],
                                     mdoc.get("block_start"), mdoc.get("block_end")))
            if not _nonneg_int(row.get("days")) or not _nonneg_int(row.get("files_selected")):
                raise LedgerError("%s の days・files_selected が 0 以上の整数でない" % where)
            if mode == "trial" and row["days"] > len(doc.get("trial_days") or []):
                raise LedgerError("%s の days %d が、trial_days の数より多い" % (where, row["days"]))
            if row is not first:
                for k in ("days", "files_selected", "block_start", "block_end", "trial_days", "gkg_run_seq",
                          "gkg_run_record_sha256"):
                    if row.get(k) != first.get(k):
                        raise LedgerError("%s の %s が、同じ run の最初の run-start と違う" % (where, k))
            run["lo_hi"] = (mdoc.get("block_start"), mdoc.get("block_end"))
        elif kind == "day":
            day = row.get("day")
            if not isinstance(day, str) or not _DAY_RE.match(day):
                raise LedgerError("%s の day %r が日付の形でない" % (where, day))
            if mode == "trial":
                if day not in (doc.get("trial_days") or []):
                    raise LedgerError("%s の day %s が、試しの run の日（%s）の外" % (where, day,
                                      "、".join(doc.get("trial_days") or [])))
            else:
                lo, hi = run["lo_hi"]
                if not (isinstance(lo, str) and isinstance(hi, str) and lo <= day <= hi):
                    raise LedgerError("%s の day %s が、区画 %s〜%s の外" % (where, day, lo, hi))
            if day in run["seen"]:
                raise LedgerError("%s：run_id %s に、day %s の行が2つある" % (where, rid, day))
            run["seen"].add(day)
            want = "gkg-%s-%s-day-%s.tsv.gz" % (mode, rid, day.replace("-", ""))
            if row.get("file_name") != want:
                raise LedgerError("%s の file_name %r が、決まった名前 %s でない" % (where, row.get("file_name"), want))
            _check_hex(row.get("sha256"), HEX64, where + " の sha256")
            ok, bad, listed = row.get("files_ok"), row.get("files_failed"), row.get("files_listed")
            if not (_nonneg_int(ok) and _nonneg_int(bad) and _nonneg_int(listed)) or ok + bad != listed:
                raise LedgerError("%s の files_ok %r + files_failed %r が files_listed %r と合わない"
                                  % (where, ok, bad, listed))
            if not isinstance(row.get("failed_files"), list) or len(row["failed_files"]) != bad:
                raise LedgerError("%s の failed_files の数が files_failed と合わない" % where)
            run["days"].append(row)
        elif kind == "run-complete":
            days = run["days"]
            tot = {"days": len(days), "files_ok": sum(d["files_ok"] for d in days),
                   "files_failed": sum(d["files_failed"] for d in days)}
            for k, v in tot.items():
                if row.get(k) != v:
                    raise LedgerError("%s の %s %r が、day の行から数えた %d と違う" % (where, k, row.get(k), v))
            if first.get("days") != len(days):
                raise LedgerError("%s：day の行の数 %d が、run-start の days %r と違う" % (where, len(days),
                                                                                   first.get("days")))
            listed = sum(d["files_listed"] for d in days)
            if first.get("files_selected") != listed:
                raise LedgerError("%s：day の行の files_listed の合計 %d が、run-start の files_selected %r と違う"
                                  % (where, listed, first.get("files_selected")))
            _check_hex(row.get("fetch_log_sha256"), HEX64, where + " の fetch_log_sha256")
            run["complete"], run["complete_lineno"] = row, i
    for run in runs.values():
        del run["seen"], run["doc"]
        run.pop("lo_hi", None)
    return runs


GKG_RESULT_DOC_KEYS = ("gkg_run_record_sha256", "gkg_run_seq", "kind", "ledger_head", "manifest_commit",
                       "manifest_lines", "manifest_path", "manifest_sha256", "mode", "run_complete_line_sha256",
                       "run_id")


def manifest_prefix(body, n, path):
    """マニフェストの先頭 n 行（各行の改行を含む）のバイト列。取れなければ LedgerError。"""
    lines = body.split(b"\n")
    if not body.endswith(b"\n") or type(n) is not int or not 1 <= n <= len(lines) - 1:
        raise LedgerError("%s の先頭 %r 行を取れない（行の数 %d。最後は改行で終わること）"
                          % (path, n, body.count(b"\n")))
    return b"".join(line + b"\n" for line in lines[:n])


def check_gkg_result_doc(records, record, doc, read_json, data=None):
    """gkg-run-result の中身の形と、指している gkg-run-start との対応（T-066）。マニフェストとの照合は
    check_gkg_results。data（記録のバイト列）を渡せば ledger_head も照らす。"""
    what = "seq %d の gkg-run-result" % record["seq"]
    if not isinstance(doc, dict) or tuple(sorted(doc)) != GKG_RESULT_DOC_KEYS:
        raise LedgerError("%s の中身のキーが、決まった %d 個と一致しない" % (what, len(GKG_RESULT_DOC_KEYS)))
    if doc["kind"] != GKG_RESULT_KIND:
        raise LedgerError("%s の中身の kind が違う" % what)
    if data is not None:
        check_ledger_head(data, record, doc)
    seq = doc["gkg_run_seq"]
    by_seq = {r["seq"]: r for r in records}
    rec = by_seq.get(seq) if type(seq) is int else None
    if rec is None or rec["kind"] != GKG_RUN_KIND or seq >= record["seq"]:
        raise LedgerError("%s の gkg_run_seq %r が、それより前の gkg-run-start の記録でない" % (what, seq))
    if sha256_hex(canonical_line(rec)) != doc["gkg_run_record_sha256"]:
        raise LedgerError("%s の gkg_run_record_sha256 が、seq %d の行と一致しない" % (what, seq))
    run = read_json(rec, GKG_RUN_KIND)
    if (doc["mode"], doc["run_id"]) != (run.get("mode"), run.get("run_id")):
        raise LedgerError("%s の mode・run_id が、seq %d の gkg-run-start と違う" % (what, seq))
    if doc["manifest_path"] != GKG_MANIFESTS.get(doc["mode"]):
        raise LedgerError("%s の manifest_path が、mode %s のマニフェストでない" % (what, doc["mode"]))
    if type(doc["manifest_lines"]) is not int or doc["manifest_lines"] < 1:
        raise LedgerError("%s の manifest_lines が正の整数でない" % what)
    _check_hex(doc["manifest_sha256"], HEX64, what + " の manifest_sha256")
    _check_hex(doc["run_complete_line_sha256"], HEX64, what + " の run_complete_line_sha256")
    _check_hex(doc["manifest_commit"], HEX40, what + " の manifest_commit")
    return doc


def check_gkg_results(records, read_json, manifests):
    """gkg-run-result の記録を照らす（T-066）。manifests は check_gkg_manifests と同じ形。
      - 中身が check_gkg_result_doc に通る。同じ gkg_run_seq の gkg-run-result は1件だけ。
      - マニフェストの先頭 manifest_lines 行の sha256 が manifest_sha256 と同じ（マニフェストは追記のみなので、
        後の行が増えても先頭は変わらない）。
      - その先頭の行の中に、run_id の run-complete の行があり、その行（改行を除く）の sha256 が
        run_complete_line_sha256 と同じ。
    返り値: {(mode, run_id): 記録}。"""
    out = {}
    for r in records:
        if r["kind"] != GKG_RESULT_KIND:
            continue
        doc = check_gkg_result_doc(records, r, read_json(r, GKG_RESULT_KIND), read_json)
        key = (doc["mode"], doc["run_id"])
        if key in out:
            raise LedgerError("mode %s・run_id %s の gkg-run-result が2件ある（seq %d、%d）"
                              % (key[0], key[1], out[key]["seq"], r["seq"]))
        body = manifests.get(doc["mode"])
        if body is None:
            raise LedgerError("seq %d の gkg-run-result があるのに、%s が無い" % (r["seq"], doc["manifest_path"]))
        try:
            prefix = manifest_prefix(body, doc["manifest_lines"], doc["manifest_path"])
        except LedgerError as e:
            raise LedgerError("seq %d の gkg-run-result の manifest_lines：%s（マニフェストが封印のあとで短くなった）"
                              % (r["seq"], e)) from None
        if sha256_hex(prefix) != doc["manifest_sha256"]:
            raise LedgerError("seq %d の gkg-run-result の manifest_sha256 が、%s の先頭 %d 行の sha256 と違う"
                              "（マニフェストが封印のあとで書き換えられた）" % (r["seq"], doc["manifest_path"],
                                                                         doc["manifest_lines"]))
        found = None
        for line in prefix.split(b"\n")[:-1]:
            try:
                row = json.loads(line.decode("utf-8"))
            except (UnicodeDecodeError, ValueError):
                continue
            if isinstance(row, dict) and row.get("kind") == "run-complete" and row.get("run_id") == doc["run_id"]:
                found = line
        if found is None or sha256_hex(found) != doc["run_complete_line_sha256"]:
            raise LedgerError("seq %d の gkg-run-result が指す run-complete の行が、%s の先頭 %d 行の中に無いか、"
                              "sha256 が違う" % (r["seq"], doc["manifest_path"], doc["manifest_lines"]))
        out[key] = r
    return out


def check_gkg_run_modes(modes):
    """modes：[(seq, mode)]（seq の順）。official は 1 件だけ、trial は official より前だけ。T-031。"""
    official = [seq for seq, mode in modes if mode == "official"]
    if len(official) > 1:
        raise LedgerError("mode が official の gkg-run-start が %d 件ある（seq %s）。正式な run は 1 件だけ"
                          % (len(official), ", ".join(map(str, official))))
    if official:
        late = [seq for seq, mode in modes if mode == "trial" and seq > official[0]]
        if late:
            raise LedgerError("mode が trial の gkg-run-start（seq %s）が、official の記録（seq %d）より後に"
                              "ある。試しの run は正式な run の前にだけ行う決まり"
                              % (", ".join(map(str, late)), official[0]))


def check_gkg_runs(records, read_json):
    """すべての gkg-run-start の中身と順序を照合する（drand・ledger_head は別）。T-031。
    返り値: [(記録, 中身)]。"""
    runs = check_gkg_run_order(records)
    out = [(r, check_gkg_run_doc(records, r, read_json(r, GKG_RUN_KIND), read_json)) for r in runs]
    check_gkg_run_modes([(r["seq"], d["mode"]) for r, d in out])
    check_gkg_run_common(out)
    return out


GKG_RUN_COMMON_KEYS = ("filelist_sha256", "exclusion_rule_seq", "exclusion_rule_record_sha256",
                       "method_access_seq")


def check_gkg_run_common(runs):
    """runs：[(記録, 中身)]。T-031 の中1・中3。
      - すべての gkg-run-start で、GKG_RUN_COMMON_KEYS の値が同じ（試しの run を見たあとで、正式な
        run の入力（一覧・除外の規則の記録）を選び直せないようにする）。
      - mode が trial の記録どうしで run_id が重ならない（同じ run の再開では書かない決まり。
        gkg-run-start は収集係のマニフェストの run-start 1 件につき 1 件）。
    """
    if not runs:
        return
    r0, d0 = runs[0]
    for r, d in runs[1:]:
        for k in GKG_RUN_COMMON_KEYS:
            if d[k] != d0[k]:
                raise LedgerError("seq %d の gkg-run-start の %s %r が、最初の gkg-run-start（seq %d）の %r と違う。"
                                  "どの run も同じ入力を使う決まり" % (r["seq"], k, d[k], r0["seq"], d0[k]))
    seen = {}
    for r, d in runs:
        if d["mode"] != "trial":
            continue
        if d["run_id"] in seen:
            raise LedgerError("mode が trial の gkg-run-start（seq %d）の run_id %s が、seq %d と同じ。"
                              "gkg-run-start は run の最初の実行で 1 件だけ書き、再開では書かない"
                              % (r["seq"], d["run_id"], seen[d["run_id"]]))
        seen[d["run_id"]] = r["seq"]


# ---------------------------------------------------------------- 統計係の順番1・順番1b（T-037）

ORDER_KINDS = (ORDER1_KIND, ORDER1B_KIND)
HEX40 = re.compile(r"\A[0-9a-f]{40}\Z")
THEMES_MANIFEST = "data/manifest/gdelt-themes.jsonl"   # 区分表の取得のマニフェスト（収集係）
FILELIST_CODE_PATH = "src/collector/acquire_filelist.py"

# ---- 順番1（docs/stats/seal-order1.md 1章・2章）。値はこのコードに固定する。書く仕組み
# （seal_stats）と verify が同じ値で照らす（T-037 の差し戻し1回目 中3・軽5）。
# 祖先でなければならない commit（短い ID → 40 桁）。2章の項目4
ORDER1_ANCESTORS = {
    "1cb463a": "1cb463acfcf15ba315e6c454625ad681e86bbc2a",
    "2d23cdf": "2d23cdf6e01de5129fc7b0a5d85e89bf02e892c6",
    "8f0f4ec": "8f0f4ec233acdef6e3d6bd7144fa1523be389308",
    "0f98e62": "0f98e62b2810011c269efdd5836bd7cf3a5d5fce",
}
# 封印の対象の 10 件の名前（1章の表の「対象」の列と同じ文字列）。ちょうどこの 10 件でなければならない
ORDER1_TARGET_NAMES = (
    "src/stats/exclusion.py", "src/stats/exclusion.py の出力", "tests/stats/test_exclusion.py",
    "src/stats/tagrules.py", "src/stats/tagrules.py の出力", "tests/stats/test_tagrules.py",
    "docs/stats/tags-naive.md", "1cb463a:src/stats/tagrules.py", "1cb463a:src/stats/tagrules.py の出力",
    "2d23cdf:reviews/T-020.md",
)
# 2章の項目10：対象だけを置いた写しで流すテスト
ORDER1_SEALED_TESTS = ("tests/stats/test_exclusion.py", "tests/stats/test_tagrules.py")
# 2章の項目1：(名前, commit, パス, 行)
ORDER1_APPROVALS = (
    ("A", "8f0f4ec233acdef6e3d6bd7144fa1523be389308", "reviews/T-022.md",
     ("> Kはいま封印していいよ",)),
    ("B", "8f0f4ec233acdef6e3d6bd7144fa1523be389308", "reviews/T-022.md",
     ("> 2.数え方の候補を先に封印し、最後に全候補のタグの一覧を並べて公開する案でよいか",
      "> それでいいです。")),
    ("B (ii)", "0f98e62b2810011c269efdd5836bd7cf3a5d5fce", "reviews/T-024.md",
     ("> いいよ、正式に扱う基準は一つに絞ろう。",)),
)
# 2章の項目7
OWNER_CHOICE = ("2d23cdf6e01de5129fc7b0a5d85e89bf02e892c6", "reviews/T-020.md",
                "## 2026-10-08 オーナーの発言（原文のまま記録）",
                ("> 病名は案B", "> 民族、宗教の集団は除外の区分に加える。",
                 "> そのほかこのまま承認の項目は承認します"))

# ---- 順番1b（docs/stats/seal-order1.md 3章 (3)、docs/stats/counting.md 0章 (1)・7章。T-037 の差し戻し1回目 中2）
ORDER1B_REQUIRED_FILES = ("docs/stats/counting.md", "src/stats/counting.py", "tests/stats/test_counting.py",
                          "docs/stats/seal-order1.md")
COUNTING_SCRIPT = "src/stats/counting.py"
# 正式な数え方の出どころ（counting.md 0章 (1)）：commit、パス、オーナーの発言の行（行の全体が一致する行が
# ちょうど 1 つ）、「決定：」の行の先頭（先頭が一致する行がちょうど 1 つ）と、その行に含まれる語句
OWNER_DECISION = ("9c85f58f054a679b8e5f40fcd7adbb17536f6366", "reviews/T-028.md",
                  "> 作り方2を、新しい候補として加え、正式に使う数え方にしよう",
                  "- 決定：正式に使う数え方は、",
                  ("V1 か V2 の少なくとも一方", "同じ数え方の全テーマの合計"))

ORDER1_DOC_KEYS = ("ancestors", "approvals", "checks", "head", "kind", "ledger_head",
                   "owner_choice", "python", "targets")
ORDER1B_DOC_KEYS = ("ancestors", "approvals", "checks", "counting", "files", "head", "kind",
                    "ledger_head", "order1_ref", "owner_approval", "python")
# 正式な数え方（counting.OFFICIAL_CANDIDATE と同じ。2026-10-08 オーナー決定。seal-order1.md 3章 (3) の4）。
# 順番1b の counting.official_candidate は、この値と一致しなければならない（T-037 再提出1回目 中-A）
ORDER1B_OFFICIAL_CANDIDATE = "C7"
# 順番1b の承認事項へのオーナーの承認（counting.OWNER_APPROVAL_1B と同じ照らし方。T-037 再提出1回目 中-B）：
# (commit, パス, 見出しの行, 承認の行)。承認の行がちょうど 1 つ、その前で最も近い "## " の見出しが
# 見出しの行と行の全体で一致し、見出しの行もちょうど 1 つあること
OWNER_APPROVAL_1B = ("a970019c61808738b02629b14f68b3171c4ddd57", "reviews/T-036.md",
                     "## 2026-10-08 オーナーの発言（原文のまま記録。順番1b の承認事項）", "> 承認します")


def expected_owner_approval_1b():
    commit, path, heading, line = OWNER_APPROVAL_1B
    return {"source": "%s:%s" % (commit, path), "heading": heading, "line": line}
ORDER1_CHECK_KEYS = ("acquisition_starts", "gkg_manifests_absent", "method_access_absent",
                     "not_shallow", "optional_choice_status", "stats_tests", "targets_only_copy",
                     "themes_manifest_absent", "worktree_clean")
ORDER1B_CHECK_KEYS = ("gkg_manifests_absent", "method_access_absent", "not_shallow", "worktree_clean")
COUNTING_KEYS = ("candidate_ids", "criteria_ids", "official_candidate", "official_status",
                 "output_sha256", "owner_decision")


def order1_copy_files():
    """対象のうち、作業ツリーのファイルのもの（写しに置く 5 件。2章の項目10）。"""
    return tuple(n for n in ORDER1_TARGET_NAMES if ":" not in n and not n.endswith(" の出力"))


def order1_history_commits():
    """対象のうち git の履歴から読むものの commit の 40 桁（写しに取る。2章の項目10）。"""
    shorts = sorted({n.split(":", 1)[0] for n in ORDER1_TARGET_NAMES if ":" in n})
    return tuple(ORDER1_ANCESTORS[s] for s in shorts)


def expected_order1_approvals():
    return [{"item": a[0], "source": "%s:%s" % (a[1], a[2]), "lines": list(a[3])} for a in ORDER1_APPROVALS]


def expected_owner_choice():
    return {"source": "%s:%s" % (OWNER_CHOICE[0], OWNER_CHOICE[1]), "heading": OWNER_CHOICE[2],
            "lines": list(OWNER_CHOICE[3])}


def fixed_git_env():
    """git を、GIT_ で始まる環境変数を決めたものだけに固定して動かすための環境（T-056。T-054 の軽-1）。
    docs/stats/counting.md 4章 (3) と同じ固定の仕方：GIT_ で始まる環境変数を除き、
    GIT_NO_REPLACE_OBJECTS=1 と、存在しないパスの GIT_GRAFT_FILE だけを入れる。"""
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env["GIT_NO_REPLACE_OBJECTS"] = "1"
    env["GIT_GRAFT_FILE"] = "/dev/null/no-graft-file"
    return env


def check_ledger_head(data, record, doc):
    """中身の ledger_head が、記録の先頭 seq−1 行のハッシュと一致するか（drand を持たない種類）。"""
    head = doc.get("ledger_head") if isinstance(doc, dict) else None
    if head != expected_ledger_head(data, record["seq"]):
        raise LedgerError("seq %d の %s の中身の ledger_head が、直前の記録のハッシュと一致しない"
                          % (record["seq"], record["kind"]))


def _check_hex(value, pattern, what):
    if not isinstance(value, str) or not pattern.match(value):
        raise LedgerError("%s の形が違う" % what)


def _check_approvals(approvals, what):
    if not isinstance(approvals, list) or not approvals:
        raise LedgerError("%s の approvals が空でない一覧でない" % what)
    for a in approvals:
        if not isinstance(a, dict) or sorted(a) != ["item", "lines", "source"]:
            raise LedgerError("%s の approvals の要素のキーが item・lines・source でない" % what)
        src = a["source"]
        if not isinstance(src, str) or ":" not in src or not HEX40.match(src.split(":", 1)[0]):
            raise LedgerError("%s の approvals の source が「40 桁の commit:パス」でない" % what)
        if not isinstance(a["lines"], list) or not a["lines"] \
                or not all(isinstance(x, str) and x for x in a["lines"]):
            raise LedgerError("%s の approvals の lines が空でない文字列の一覧でない" % what)


def _check_python(py, what):
    if not isinstance(py, dict) or sorted(py) != ["path", "version"] or py.get("path") != ".venv/bin/python" \
            or not isinstance(py.get("version"), str) or not py["version"].startswith("Python "):
        raise LedgerError("%s の python が {path: .venv/bin/python, version: Python …} でない" % what)


def check_order1_doc(record, doc):
    """stats-order1 の中身を照合する（ledger_head は check_ledger_head）。T-037。
    形に加えて、中身が決まった値と一致することを確かめる（差し戻し1回目 中3・軽5）：
    対象の名前がちょうど ORDER1_TARGET_NAMES の 10 件、ancestors が ORDER1_ANCESTORS の 40 桁、
    approvals が ORDER1_APPROVALS、owner_choice が OWNER_CHOICE と同じ、checks の値、
    targets_only_copy のファイルが order1_copy_files() と同じ。
    返り値: {対象の名前: sha256}。"""
    what = "seq %d の stats-order1" % record["seq"]
    _check_doc_kind(record, doc)
    if not isinstance(doc, dict) or tuple(sorted(doc)) != ORDER1_DOC_KEYS:
        raise LedgerError("%s の中身のキーが、決まった %d 個（%s）と一致しない"
                          % (what, len(ORDER1_DOC_KEYS), "、".join(ORDER1_DOC_KEYS)))
    _check_hex(doc["head"], HEX40, what + " の head")
    if doc["ancestors"] != sorted(ORDER1_ANCESTORS.values()):
        raise LedgerError("%s の ancestors が、決まった 4 つの commit と一致しない" % what)
    _check_python(doc["python"], what)
    targets = doc["targets"]
    if not isinstance(targets, list):
        raise LedgerError("%s の targets が一覧でない" % what)
    out = {}
    for t in targets:
        if not isinstance(t, dict) or sorted(t) != ["name", "sha256"] or not isinstance(t["name"], str):
            raise LedgerError("%s の targets の要素のキーが name・sha256 でない" % what)
        _check_hex(t["sha256"], HEX64, what + " の targets の sha256")
        if t["name"] in out:
            raise LedgerError("%s の targets の名前 %s が重なる" % (what, t["name"]))
        out[t["name"]] = t["sha256"]
    if sorted(out) != sorted(ORDER1_TARGET_NAMES):
        raise LedgerError("%s の targets の名前が、決まった 10 件（ledger.ORDER1_TARGET_NAMES）とちょうど一致"
                          "しない（足りない %s、多い %s）"
                          % (what, sorted(set(ORDER1_TARGET_NAMES) - set(out)) or "なし",
                             sorted(set(out) - set(ORDER1_TARGET_NAMES)) or "なし"))
    _check_approvals(doc["approvals"], what)
    if doc["approvals"] != expected_order1_approvals():
        raise LedgerError("%s の approvals が、決まった照らし方（A・B・B (ii)）と一致しない" % what)
    if doc["owner_choice"] != expected_owner_choice():
        raise LedgerError("%s の owner_choice が、決まった出どころ（2d23cdf の reviews/T-020.md）と一致しない"
                          % what)
    checks = doc["checks"]
    if not isinstance(checks, dict) or tuple(sorted(checks)) != ORDER1_CHECK_KEYS:
        raise LedgerError("%s の checks のキーが、決まった %d 個と一致しない" % (what, len(ORDER1_CHECK_KEYS)))
    for k in ("gkg_manifests_absent", "method_access_absent", "not_shallow",
              "themes_manifest_absent", "worktree_clean"):
        if checks[k] is not True:
            raise LedgerError("%s の checks.%s が true でない" % (what, k))
    if checks["optional_choice_status"] != "decided":
        raise LedgerError("%s の checks.optional_choice_status が decided でない" % what)
    for k in ("stats_tests",):
        if not isinstance(checks[k], str) or not re.match(r"\AOK \(\d+ tests\)\Z", checks[k]):
            raise LedgerError("%s の checks.%s が「OK (N tests)」でない" % (what, k))
    copy = checks["targets_only_copy"]
    if not isinstance(copy, dict) or sorted(copy) != ["files", "tests"] \
            or not isinstance(copy["tests"], str) or not re.match(r"\AOK \(\d+ tests\)\Z", copy["tests"]) \
            or copy["files"] != sorted(order1_copy_files()):
        raise LedgerError("%s の checks.targets_only_copy が {tests: OK (N tests), files: 決まった 5 件} でない"
                          % what)
    return out


def check_order1b_doc(record, doc):
    """stats-order1b の中身を照合する（ledger_head は check_ledger_head）。T-037。
    差し戻し1回目 中2：files が ORDER1B_REQUIRED_FILES のちょうど4件であること（T-060 から、外のファイルも
    不可。重複も不可）、counting に候補と基準の案の識別子・
    正式な数え方（official_status が decided で、候補の中にある）・counting.py の出力の sha256・
    OWNER_DECISION の出どころの 2 行があること、approvals に B (ii) があること。
    再提出1回目：official_candidate が ORDER1B_OFFICIAL_CANDIDATE（C7）と一致すること（中-A）、
    owner_approval が OWNER_APPROVAL_1B の照らし方と一致すること（中-B）。
    返り値: {パス: sha256}。"""
    what = "seq %d の stats-order1b" % record["seq"]
    _check_doc_kind(record, doc)
    if not isinstance(doc, dict) or tuple(sorted(doc)) != ORDER1B_DOC_KEYS:
        raise LedgerError("%s の中身のキーが、決まった %d 個（%s）と一致しない"
                          % (what, len(ORDER1B_DOC_KEYS), "、".join(ORDER1B_DOC_KEYS)))
    _check_hex(doc["head"], HEX40, what + " の head")
    if not isinstance(doc["ancestors"], list) or not doc["ancestors"]:
        raise LedgerError("%s の ancestors が空でない一覧でない" % what)
    for c in doc["ancestors"]:
        _check_hex(c, HEX40, what + " の ancestors")
    _check_python(doc["python"], what)
    files = doc["files"]
    if not isinstance(files, list) or not files:
        raise LedgerError("%s の files が空でない一覧でない" % what)
    out = {}
    for f in files:
        if not isinstance(f, dict) or sorted(f) != ["path", "sha256"]:
            raise LedgerError("%s の files の要素のキーが path・sha256 でない" % what)
        acquisition_start_fields({"fetch": {"code_path": f["path"], "code_sha256": f["sha256"]}})
        if f["path"] in out:
            raise LedgerError("%s の files のパス %s が重なる" % (what, f["path"]))
        out[f["path"]] = f["sha256"]
    missing = [p for p in ORDER1B_REQUIRED_FILES if p not in out]
    if missing:
        raise LedgerError("%s の files に、必ず入れるファイル %s が無い" % (what, "、".join(missing)))
    extra = [p for p in out if p not in ORDER1B_REQUIRED_FILES]
    if extra:
        # T-060（T-059 の監査 重大-1）：files は ORDER1B_REQUIRED_FILES のちょうど4件に限る。verify は files の
        # ファイルだけを流すフォルダに置くので、5つ目以降（標準ライブラリを隠す src/stats/fractions.py など）を
        # 足せると、counting.py を変えずに出力を変えられる
        raise LedgerError("%s の files に、決まった %d 件（ORDER1B_REQUIRED_FILES）の外のファイル %s がある"
                          % (what, len(ORDER1B_REQUIRED_FILES), "、".join(extra)))
    _check_approvals(doc["approvals"], what)
    bii = expected_order1_approvals()[2]
    if bii not in doc["approvals"]:
        raise LedgerError("%s の approvals に B (ii) の照らし方が無い" % what)
    c = doc["counting"]
    if not isinstance(c, dict) or tuple(sorted(c)) != COUNTING_KEYS:
        raise LedgerError("%s の counting のキーが、決まった %d 個（%s）と一致しない"
                          % (what, len(COUNTING_KEYS), "、".join(COUNTING_KEYS)))
    for k in ("candidate_ids", "criteria_ids"):
        ids = c[k]
        if not isinstance(ids, list) or not ids or len(set(ids)) != len(ids) \
                or not all(isinstance(x, str) and x for x in ids):
            raise LedgerError("%s の counting.%s が、重ならない識別子の空でない一覧でない" % (what, k))
    if c["official_status"] != "decided" or c["official_candidate"] not in c["candidate_ids"]:
        raise LedgerError("%s の counting の正式な数え方が決まっていない（official_status が decided で、"
                          "official_candidate が候補の中にあること）" % what)
    if c["official_candidate"] != ORDER1B_OFFICIAL_CANDIDATE:
        raise LedgerError("%s の counting.official_candidate %r が、決まった正式な数え方 %s（ledger."
                          "ORDER1B_OFFICIAL_CANDIDATE）と違う" % (what, c["official_candidate"],
                                                               ORDER1B_OFFICIAL_CANDIDATE))
    if doc["owner_approval"] != expected_owner_approval_1b():
        raise LedgerError("%s の owner_approval が、決まった照らし方（ledger.OWNER_APPROVAL_1B。%s:%s）と"
                          "一致しない" % (what, OWNER_APPROVAL_1B[0], OWNER_APPROVAL_1B[1]))
    _check_hex(c["output_sha256"], HEX64, what + " の counting.output_sha256")
    od = c["owner_decision"]
    want_src = "%s:%s" % (OWNER_DECISION[0], OWNER_DECISION[1])
    if not isinstance(od, dict) or sorted(od) != ["decision_line", "source", "source_line"] \
            or od["source"] != want_src or od["source_line"] != OWNER_DECISION[2] \
            or not isinstance(od["decision_line"], str) or not od["decision_line"].startswith(OWNER_DECISION[3]) \
            or not all(p in od["decision_line"] for p in OWNER_DECISION[4]):
        raise LedgerError("%s の counting.owner_decision が、決まった出どころ（%s の発言の行と「決定：」の行）と"
                          "一致しない" % (what, want_src))
    ref = doc["order1_ref"]
    if ref is not None and (not isinstance(ref, dict) or sorted(ref) != ["record_sha256", "seq"]):
        raise LedgerError("%s の order1_ref が null か {seq, record_sha256} でない" % what)
    checks = doc["checks"]
    if not isinstance(checks, dict) or tuple(sorted(checks)) != ORDER1B_CHECK_KEYS \
            or not all(v is True for v in checks.values()):
        raise LedgerError("%s の checks のキーが決まった %d 個でないか、true でないものがある"
                          % (what, len(ORDER1B_CHECK_KEYS)))
    return out


def first_order1(records):
    """除外の規則の kind（stats-order1）の記録（無ければ None）。T-037 の差し戻し1回目 中5 で、
    stats-order1 は 1 件に限った（check_stats_order）ので、「最初」と「最後」は同じ記録である。
    収集係の関門と gkg-run-start の exclusion_rule_seq が指す記録。"""
    return _first_of_kind(records, ORDER1_KIND)


def check_stats_order(records, read_json):
    """順番1・順番1b の記録の数・中身・位置の照合。T-037（差し戻し1回目で改めた）。
    （docs/stats/seal-order1.md 2章の項目2、3章 (3)。docs/verify/periods-seal.md 13章）
      - stats-order1 の記録は 1 件だけ（差し戻し1回目 中5。2 件目は書く仕組みも止める。
        新しい版の扱いは別に決める）。
      - 各記録の中身が check_order1_doc・check_order1b_doc に通る。
      - stats-order1・stats-order1b の記録は、最初の method-access より前にある。
      - 最初の method-access の前に、stats-order1 の記録がある（T-041）と、stats-order1b の記録がある（T-043）。
        書く仕組み（seal_method は drand の前）、method-access の関門、verify のどれでも照らす（T-046）。
      - 最初の gkg-run-start の前に、stats-order1b の記録がある。
    区分表の取得は ledger に記録を書かない（収集係はマニフェスト data/manifest/gdelt-themes.jsonl に
    書く）ので、区分表の取得との前後は git の履歴で照らす（check_order1_before_themes。verify と
    seal_stats が行う）。
    返り値: {"order1": [記録], "order1b": [記録]}。
    """
    o1 = [r for r in records if r["kind"] == ORDER1_KIND]
    o1b = [r for r in records if r["kind"] == ORDER1B_KIND]
    if len(o1) > 1:
        raise LedgerError("stats-order1（順番1）の記録が %d 件ある（seq %s）。順番1 は 1 件だけ"
                          % (len(o1), ", ".join(str(r["seq"]) for r in o1)))
    for r in o1:
        check_order1_doc(r, read_json(r, ORDER1_KIND))
    for r in o1b:
        check_order1b_doc(r, read_json(r, ORDER1B_KIND))
    m = _first_of_kind(records, METHOD_ACCESS_KIND)
    g = _first_of_kind(records, GKG_RUN_KIND)
    for r in o1 + o1b:
        if m is not None and r["seq"] > m["seq"]:
            raise LedgerError("%s の記録（seq %d）が、最初の method-access の記録（seq %d）より後にある。順番1・1b は"
                              "データに触れる前に封印する決まり" % (r["kind"], r["seq"], m["seq"]))
    if m is not None and not any(r["seq"] < m["seq"] for r in o1):
        # T-041：収集係のテストが method-access の前に順番1・1b を置く形になったので、T-037 で保留した
        # 「順番1 が無ければ method-access も止まる」を入れた
        raise LedgerError("最初の method-access の記録（seq %d）より前に、stats-order1（順番1）の記録が無い"
                          % m["seq"])
    if m is not None and not any(r["seq"] < m["seq"] for r in o1b):
        # T-043（T-041 の監査 軽-4）：順番1b が無いまま method-access を書くと、そのあと順番1b も
        # gkg-run-start も書けず、記録が先へ進めなくなるので止める
        raise LedgerError("最初の method-access の記録（seq %d）より前に、stats-order1b（順番1b）の記録が無い"
                          % m["seq"])
    if g is not None and not any(r["seq"] < g["seq"] for r in o1b):
        raise LedgerError("最初の gkg-run-start の記録（seq %d）より前に、stats-order1b（順番1b）の記録が無い"
                          % g["seq"])
    return {"order1": o1, "order1b": o1b}


def themes_manifest_commits(git):
    """区分表のマニフェストに行がある commit の集合 F。git(*args) は bytes を返す関数。
    git log --all --full-history の commit のうち、その版のマニフェストに空でない行があるもの。"""
    out = set()
    log = git("log", "--all", "--full-history", "--format=%H", "--", THEMES_MANIFEST).decode().split()
    for c in log:
        try:
            body = git("show", "%s:%s" % (c, THEMES_MANIFEST))
        except LedgerError:
            continue
        if any(l.strip() for l in body.split(b"\n")):
            out.add(c)
    return out


def check_order1_before_themes(records, git):
    """区分表の取得より前に順番1、を git の履歴で照らす（T-037 の差し戻し1回目 中1）。
    F = 区分表のマニフェストに行がある commit の集合（themes_manifest_commits）。F のどの commit C についても、
    C の親（git rev-parse C^@）のうち少なくとも一つの版の sealed/ledger.jsonl に、今あるすべての
    stats-order1 の行（正規の形のバイト列）があること。F が空でなければ stats-order1 の記録が要る。
    親の無い commit が F にあれば失敗。並び順や時刻は使わない（seal-order1.md 3章 (2) と同じ考え方）。
    返り値: F の件数。"""
    f = themes_manifest_commits(git)
    lines = [canonical_line(r) for r in records if r["kind"] == ORDER1_KIND]
    if f and not lines:
        raise LedgerError("区分表のマニフェスト（%s）に行がある commit があるのに、stats-order1（順番1）の記録が"
                          "無い" % THEMES_MANIFEST)
    for c in sorted(f):
        parents = git("rev-parse", "%s^@" % c).decode().split()
        if not parents:
            raise LedgerError("区分表のマニフェストに行がある commit %s に親が無い（浅い clone では親が取れない。"
                              "この照合には履歴が要るので、--depth を付けない clone で確かめる）" % c[:12])
        ok = False
        for p in parents:
            try:
                led = git("show", "%s:sealed/ledger.jsonl" % p)
            except LedgerError:
                continue
            have = set(led.split(b"\n"))
            if all(line in have for line in lines):
                ok = True
                break
        if not ok:
            raise LedgerError("区分表のマニフェストに行がある commit %s の、どの親の sealed/ledger.jsonl にも "
                              "stats-order1 の記録の行が無い（区分表の取得が順番1 より前）" % c[:12])
    return len(f)


def check_themes_manifest_refs(records, manifest_bytes):
    """区分表のマニフェストの行の exclusion_rule_seq・exclusion_rule_record_sha256 が、stats-order1 の記録の
    seq と行の sha256 と一致すること（T-037 の差し戻し1回目 中1）。行に二つのキーが無ければ失敗。
    manifest_bytes は作業ツリーのマニフェストのバイト列（無ければ None）。返り値: 照らした行の数。"""
    if manifest_bytes is None:
        return 0
    o1 = first_order1(records)
    n = 0
    for i, raw in enumerate(manifest_bytes.split(b"\n"), 1):
        if not raw.strip():
            continue
        try:
            row = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            raise LedgerError("%s の %d 行目が JSON として読めない" % (THEMES_MANIFEST, i)) from None
        if not isinstance(row, dict) or "exclusion_rule_seq" not in row \
                or "exclusion_rule_record_sha256" not in row:
            raise LedgerError("%s の %d 行目に exclusion_rule_seq・exclusion_rule_record_sha256 が無い"
                              % (THEMES_MANIFEST, i))
        if o1 is None or row["exclusion_rule_seq"] != o1["seq"] \
                or row["exclusion_rule_record_sha256"] != sha256_hex(canonical_line(o1)):
            raise LedgerError("%s の %d 行目の exclusion_rule_seq %r（と sha256）が、stats-order1 の記録%sと一致しない"
                              % (THEMES_MANIFEST, i, row["exclusion_rule_seq"],
                                 "（無し）" if o1 is None else "（seq %d）" % o1["seq"]))
        n += 1
    return n


# ---------------------------------------------------------------- periods の検査

TRIGGER_KEYS = ("last_read_offset_days", "naive_history_days", "network_window_days",
                "same_week_years")


def output_target(record, role="output"):
    """記録の対象のうち role のもの。ちょうど 1 つでなければ失敗。"""
    outs = [t for t in record["targets"] if t["role"] == role]
    if len(outs) != 1:
        raise LedgerError("seq %d: role が %s の対象が 1 つでない" % (record["seq"], role))
    return outs[0]


def triggers_values(doc):
    """きっかけの値の記録の中身を検査し、そのまま返す。"""
    if not isinstance(doc, dict) or tuple(sorted(doc)) != TRIGGER_KEYS:
        raise LedgerError("きっかけの値の記録のキーが決まった 4 つと一致しない")
    for k, v in doc.items():
        if v is not None and (type(v) is not int or v < 1):
            raise LedgerError("きっかけの値 %s が正の整数でも null でもない" % k)
    if all(v is None for v in doc.values()):
        raise LedgerError("きっかけの値がすべて null")
    return doc


def blocks_of(output):
    try:
        return {p["name"]: (p["block_start"], p["block_end"]) for p in output["periods"]}
    except (KeyError, TypeError):
        raise LedgerError("出力に periods の block_start / block_end が無い") from None


def check_blocks(first_output, later_output):
    """後の版の区画の境目が、最初の版と一致するか。食い違いの一覧を返す（空なら一致）。"""
    a = blocks_of(first_output)
    b = blocks_of(later_output)
    problems = []
    for name in sorted(set(a) | set(b)):
        if name not in b:
            problems.append("%s: 後の版に無い" % name)
        elif name not in a:
            problems.append("%s: 最初の版に無い" % name)
        elif a[name] != b[name]:
            problems.append("%s: 最初の版 %s〜%s、後の版 %s〜%s"
                            % (name, a[name][0], a[name][1], b[name][0], b[name][1]))
    return problems


def judge_deadline_status(output, decided, adopted_triggers):
    """出力の deadline_status（統計係の申告）を、記録から決まる値と照合する。

    decided: 採用が決まっているか（threshold-access の記録があるか）。
    adopted_triggers: 採用された periods-triggers の記録の値（dict）、無ければ None。
      採用は adoption（鎖の順番）で決める。時刻は使わない。

    返り値: (記録から決まる値, 問題の一覧)。記録から決まる値は
      None（きっかけの値が無い。v1 の形）、"before_deadline"、"after_deadline"、"held"（保留）。
    規則（docs/stats/periods.md 8章 (2)）：出力の rebuild_triggers が、採用された
    periods-triggers の記録と完全に一致すれば before_deadline、そうでなければ after_deadline。
    """
    status = output.get("deadline_status")
    triggers = output.get("rebuild_triggers")
    if not isinstance(triggers, dict):
        return None, ["出力に rebuild_triggers が無い"]
    any_trigger = any(v is not None for v in triggers.values())
    if not any_trigger:
        if status is not None:
            return None, ["きっかけの値が無いのに deadline_status が %r" % (status,)]
        return None, []
    if status not in ("before_deadline", "after_deadline"):
        return None, ["きっかけの値があるのに deadline_status が %r" % (status,)]
    if not decided:
        return "held", []
    expected = ("before_deadline" if adopted_triggers is not None
                and dict(triggers) == dict(adopted_triggers) else "after_deadline")
    if status == expected:
        return expected, []
    if status == "before_deadline":
        return expected, ["before_deadline と申告しているが、きっかけの値が採用された "
                          "periods-triggers の記録と一致しない（または採用された記録が無い）"]
    return expected, ["after_deadline と申告しているが、きっかけの値は採用された "
                      "periods-triggers の記録と一致する"]


def check_deadline_statuses(records, read_json, provisional=False):
    """すべての periods の版の deadline_status を、verify.py periods と同じ規則
    （judge_deadline_status）で照合する。T-027 の差し戻し1回目の中1 (ii)、T-031。
    食い違いがあれば LedgerError。

    比べる相手の periods-triggers：
      - threshold-access の記録があれば、採用された periods-triggers（verify periods と同じ）。
      - 無ければ、provisional が偽なら何もしない（seal_access・threshold-access の関門の場合。
        追記した後の記録には threshold-access があるので、照合は行われる）。provisional が真なら、
        仮の採用として、今ある periods-triggers の最後の記録と比べる（method-access の関門。T-031。
        このあと periods-triggers を足さずに threshold-access を足したときと同じ結論になる）。
    確かめる範囲（T-031 の軽2 で明記）：
      - 各版の rebuild_triggers・deadline_status の形と、その申告が記録から決まる値と一致すること
      - periods の 1 件目の deadline_status が null であること
    確かめないこと：区画の境目（check_blocks。seal_periods と verify periods が行う）、対象の
    ファイルの sha256 の照合のほか（read_json が行う）。
    どの periods-triggers と比べるべきか（docs/stats/periods.md 8章 (2) の「記録に追記した値」）は、
    統計係の判断を待っている。決まるまでは verify periods と同じ規則を使う。
    """
    rec, _cand, cut = adoption(records, TRIGGERS_KIND)
    if cut is None:
        if not provisional:
            return
        rec = _last_of_kind(records, TRIGGERS_KIND)
    values = None if rec is None else triggers_values(read_json(rec, "triggers"))
    versions = records_of_kind(records, PERIODS_KIND)
    problems = []
    for v, r in versions:
        out = read_json(r, "output")
        if v == 1 and out.get("deadline_status") is not None:
            problems.append("1 件目: deadline_status が null でない")
        _expected, probs = judge_deadline_status(out, True, values)
        problems += ["%d 件目（seq %d）: %s" % (v, r["seq"], p) for p in probs]
    if problems:
        raise LedgerError("periods の deadline_status の照合に通らない（verify.py periods と同じ規則%s）: %s"
                          % ("。threshold-access がまだ無いので、periods-triggers の最後の記録を仮の採用として"
                             "比べた" if cut is None else "", "; ".join(problems)))


def _last_of_kind(records, kind):
    found = None
    for r in records:
        if r["kind"] == kind:
            found = r
    return found


def check_periods_version_append(records, read_json, output):
    """periods の 2 件目以降の版を書く前の照合（seal_periods が使う）。T-031（T-027 の監査 中1）。

    threshold-access の記録がまだ無いときだけ行う（その後の版は採用されず、verify periods が
    今までどおり照合する）。output は書こうとしている出力（dict）。次のどれかなら LedgerError。
      - rebuild_triggers がすべて null（または無い）のに、deadline_status が null でない。
      - deadline_status が before_deadline で、
          (a) periods-triggers の記録が無いか、その最後の記録の値と rebuild_triggers が違う
              （先にきっかけの値を追記してから作り直す決まり。docs/stats/periods.md 8章 (2)）。
          (b) 既にある before_deadline の版の rebuild_triggers と違う（違うと、どちらかの版が
              verify periods で「申告と一致しない」になり、記録から消せない）。
          (c) rebuild_triggers の J が null でなく、candidates の J の最大と違う。candidates の記録が
              まだ無ければ、J が null でない版は書かない（T-031 の軽4）。
      - deadline_status が after_deadline（T-031 の差し戻し1回目の中4。after_deadline は、期限
        （最初の threshold-access）の後の作り直し（オーナーの承認が要る。periods.md 8章 (2)）の
        ための申告なので、この関数が照合する期限の前には書かない）。
      - deadline_status がそれ以外。
    """
    if first_threshold_access(records) is not None:
        return
    status = output.get("deadline_status")
    trig = output.get("rebuild_triggers")
    if not isinstance(trig, dict) or not any(v is not None for v in trig.values()):
        if status is not None:
            raise LedgerError("きっかけの値が無いのに deadline_status が %r。書かない" % (status,))
        return
    last = _last_of_kind(records, TRIGGERS_KIND)
    last_values = None if last is None else triggers_values(read_json(last, "triggers"))
    shown = json.dumps(trig, sort_keys=True)
    if status == "before_deadline":
        if last_values is None or dict(trig) != dict(last_values):
            raise LedgerError("before_deadline の版の rebuild_triggers %s が、periods-triggers の最後の記録%s"
                              "と一致しない。先にきっかけの値を seal_triggers.py で追記してから作り直す。書かない"
                              % (shown, "（無し）" if last is None else "（seq %d、%s）"
                                 % (last["seq"], json.dumps(last_values, sort_keys=True))))
        for v, r in records_of_kind(records, PERIODS_KIND):
            out = read_json(r, "output")
            other = out.get("rebuild_triggers")
            if out.get("deadline_status") == "before_deadline" and isinstance(other, dict) \
                    and dict(other) != dict(trig):
                raise LedgerError("既にある before_deadline の版（%d 件目、seq %d）の rebuild_triggers %s と、"
                                  "書こうとしている版の %s が違う。どちらかが verify.py periods で失敗し続ける"
                                  "ので書かない" % (v, r["seq"], json.dumps(other, sort_keys=True), shown))
        j = trig.get("last_read_offset_days")
        j_max = candidates_j_max(records, read_json)
        if j is not None and j_max is None:
            # T-031 の軽4：candidates の前に J の版を書くと、あとで J の最大が違ったとき、値を変えられず
            # 行き詰まる（before_deadline の版と同じ値しか追記できないため）
            raise LedgerError("candidates の記録がまだ無いので、J（last_read_offset_days %r）を持つ版は書かない。"
                              "J は candidates で決まるので、先に candidates を封印する" % (j,))
        if j is not None and j != j_max:
            raise LedgerError("before_deadline の版の J（last_read_offset_days %r）が、candidates の J の最大 "
                              "%d と違う。書かない" % (j, j_max))
    elif status == "after_deadline":
        # T-031 の差し戻し1回目の中4：after_deadline は期限（最初の threshold-access）の後の作り直しの
        # 申告なので、期限の前には書かない（docs/stats/periods.md 8章 (2)）
        raise LedgerError("threshold-access の記録がまだ無い（期限の前）のに、deadline_status が "
                          "after_deadline の版。after_deadline は期限の後の作り直しの申告なので書かない")
    else:
        raise LedgerError("きっかけの値があるのに deadline_status が %r。書かない" % (status,))


def check_triggers_against_rebuilds(records, read_json, values):
    """periods-triggers を 1 件追記する前に、既にある before_deadline の periods の版の
    rebuild_triggers と食い違わないかを確かめる。T-027 の差し戻し1回目の中1 (ii)。

    verify periods は、すべての版の rebuild_triggers を「採用された」periods-triggers と比べる
    （judge_deadline_status）。before_deadline の版があるところに、それと違う値の
    periods-triggers を足すと、それが採用されたとき前の版が「申告と一致しない」になり、
    verify periods と all が失敗し続ける（追記のみの記録から消せない）。そのため書く前に拒む。
    - threshold-access の記録が既にあれば何もしない（その後の periods-triggers は採用されない）。
    - before_deadline の版が二つ以上あり、互いに rebuild_triggers が違えば、どの値でも拒む。
    - after_deadline の版の rebuild_triggers と同じ値も拒む（採用されると、その版が「after_deadline
      と申告しているが一致する」になる。T-031 の差し戻し1回目の中4）。
    どの periods-triggers と比べるべきかは統計係の判断を待っている。決まるまでの扱いである。
    """
    if first_threshold_access(records) is not None:
        return
    for v, r in records_of_kind(records, PERIODS_KIND):
        out = read_json(r, "output")
        trig = out.get("rebuild_triggers")
        if out.get("deadline_status") == "after_deadline" and isinstance(trig, dict) \
                and dict(trig) == dict(values):
            raise LedgerError("periods の %d 件目（seq %d）が after_deadline で、その rebuild_triggers と、"
                              "追記するきっかけの値 %s が同じ。この値が採用されると、その版は verify.py "
                              "periods で「after_deadline と申告しているが一致する」になるので追記しない"
                              % (v, r["seq"], json.dumps(values, sort_keys=True)))
        if out.get("deadline_status") != "before_deadline" or not isinstance(trig, dict):
            continue
        if dict(trig) != dict(values):
            raise LedgerError("periods の %d 件目（seq %d）が before_deadline で、その rebuild_triggers %s "
                              "と、追記するきっかけの値 %s が違う。この値が採用されると、その版は "
                              "verify.py periods で「申告と一致しない」になり、記録から消せないので追記しない"
                              "（docs/verify/periods-seal.md 9章。どの periods-triggers と比べるかは"
                              "統計係の判断待ち）"
                              % (v, r["seq"], json.dumps(trig, sort_keys=True),
                                 json.dumps(values, sort_keys=True)))


def read_target_json(root, record, role):
    """記録の対象（role のもの）のファイルを読み、sha256 を照合して JSON として返す。"""
    t = output_target(record, role)
    try:
        with open(os.path.join(root, t["path"]), "rb") as f:
            raw = f.read()
    except OSError:
        raise LedgerError("seq %d の %s のファイルが無い: %s" % (record["seq"], role, t["path"])
                          ) from None
    if sha256_hex(raw) != t["sha256"]:
        raise LedgerError("seq %d の %s のファイルが記録と一致しない" % (record["seq"], role))
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise LedgerError("seq %d の %s のファイルが JSON として読めない"
                          % (record["seq"], role)) from None


def first_threshold_block_start(root, records):
    """periods の 1 件目（最初に封印した版）の出力の、閾値を決める期間（threshold）の始まり。"""
    versions = records_of_kind(records, PERIODS_KIND)
    if not versions:
        raise LedgerError("periods の記録が無い")
    blocks = blocks_of(read_target_json(root, versions[0][1], "output"))
    if "threshold" not in blocks:
        raise LedgerError("periods の 1 件目の出力に threshold の期間が無い")
    return blocks["threshold"][0]


# ---------------------------------------------------------------- 時刻証明の照合


def ots_file_digest(ots_bytes):
    """.ots の対象の sha256 を取り出す（形式の全体も検査する）。"""
    try:
        return otsfile.parse(ots_bytes)[0]
    except otsfile.OtsError as e:
        raise LedgerError(str(e)) from None


def ots_name(seq, bitcoin=False):
    """seq の .ots の名前。bitcoin が真なら、upgrade で Bitcoin の確定を加えた方。"""
    return "ledger.jsonl.seq%06d%s.ots" % (seq, ".bitcoin" if bitcoin else "")


def list_anchors(sealed_dir):
    """[(seq, .ots のパス)]。名前が ledger.jsonl.seqNNNNNN[.bitcoin].ots のものだけ。"""
    out = []
    if not os.path.isdir(sealed_dir):
        return out
    for name in sorted(os.listdir(sealed_dir)):
        m = OTS_NAME_RE.match(name)
        if m:
            out.append((int(m.group(1)), os.path.join(sealed_dir, name)))
    return out


def _read_anchor(data, nlines, seq, path, label):
    if seq > nlines:
        raise LedgerError("%s は %d 行目までを対象にしているが、記録は %d 行しかない"
                          "（末尾の行が削除された）" % (label, seq, nlines))
    with open(path, "rb") as f:
        try:
            digest, atts = otsfile.parse(f.read())
        except otsfile.OtsError as e:
            raise LedgerError("%s: %s" % (label, e)) from None
    if digest != prefix_digest(data, seq):
        raise LedgerError("%s の対象のハッシュが、記録の先頭 %d 行と一致しない" % (label, seq))
    bad = sorted({a["uri"] for a in atts
                  if a["type"] == "pending" and a["uri"] not in ALLOWED_PENDING_URIS})
    if bad:
        raise LedgerError("%s に、許可していないカレンダーの Pending がある: %s"
                          "（許可しているのは stamp で使った 4 つの宛先だけ）"
                          % (label, ", ".join(bad)))
    return digest, atts


def check_anchors(data, sealed_dir, extra_dirs=()):
    """各 .ots の対象が記録の先頭 N 行の sha256 と一致し、すべての seq に自分の .ots
    （stamp で作った ledger.jsonl.seqNNNNNN.ots）があることを確かめる。

    - 最後の行の書き換え、末尾の行の削除、途中の .ots の欠けは、ここで検出する。
    - Pending の宛先が ALLOWED_PENDING_URIS の外なら失敗する。
    - extra_dirs: 第三者が自分で upgrade した .ots を置いたディレクトリ。名前が
      ledger.jsonl.seqNNNNNN[.bitcoin].ots のものを、同じ検査をして読み足す。
      必須の .ots（その seq 自身の stamp の .ots）は sealed_dir にあるものだけで数える。
    返り値: [(seq, .ots のパス, digest, 証明の一覧)]。
    """
    lines = split_lines(data)
    anchors = list_anchors(sealed_dir)
    result = []
    for seq, path in anchors:
        digest, atts = _read_anchor(data, len(lines), seq, path, os.path.basename(path))
        result.append((seq, path, digest, atts))
    have = {os.path.basename(p) for _s, p in anchors}
    missing = [s for s in range(1, len(lines) + 1) if ots_name(s) not in have]
    if missing:
        raise LedgerError("seq %s の記録に、その seq 自身の時刻証明（.ots）が無い"
                          % ", ".join(map(str, missing)))
    for d in extra_dirs:
        if not os.path.isdir(d):
            raise LedgerError("外から指定した .ots のディレクトリが無い: %s" % d)
        for seq, path in list_anchors(d):
            digest, atts = _read_anchor(data, len(lines), seq, path, path)
            result.append((seq, path, digest, atts))
    return result


def confirmed_times(anchor_results, headers, min_work_bits=None):
    """各 seq 自身の .ots の Bitcoin の証明を、渡されたヘッダで確かめ、確定した時刻を返す。

    headers: {高さ: 80 バイトのヘッダ}。
    返り値: ({seq: 最も早い確定時刻}, [(seq, 高さ, 時刻, ブロックのハッシュ)], [使われなかった高さ])
    ヘッダが照合に失敗すれば LedgerError。ヘッダの無い高さの証明は、確定として数えない。
    """
    kw = {} if min_work_bits is None else {"min_work_bits": min_work_bits}
    times, detail, used = {}, [], set()
    for seq, _path, _digest, atts in anchor_results:
        for a in atts:
            if a["type"] != "bitcoin" or a["height"] not in headers:
                continue
            try:
                when, block = otsfile.check_header(headers[a["height"]], a["msg"], **kw)
            except otsfile.OtsError as e:
                raise LedgerError("seq %d の高さ %d のヘッダ: %s" % (seq, a["height"], e)) from None
            used.add(a["height"])
            detail.append((seq, a["height"], when, block))
            if seq not in times or when < times[seq]:
                times[seq] = when
    unused = sorted(set(headers) - used)
    return times, detail, unused


# ---------------------------------------------------------------- 追記


def build_next_record(data, kind, targets, note, now):
    """data（今の記録のバイト列）の次に追記する記録と、その行（改行を含む）を作る。書かない。

    返り値: (今の記録の一覧, 次の記録, 行のバイト列)。append_record と同じ形で作るので、
    書く前に「追記した後の記録」を検査できる（T-009 の書き込みの仕組みが使う）。
    """
    records = verify_chain(data)
    prev = sha256_hex(split_lines(data)[-1]) if records else GENESIS_PREV
    rec = {
        "seq": len(records) + 1,
        "prev_hash": prev,
        "kind": kind,
        "targets": sorted(targets, key=lambda t: t["path"]),
        "recorded_at": format_time(now),
        "note": note,
    }
    _check_record_shape(rec, rec["seq"])
    if records and parse_time(rec["recorded_at"]) < parse_time(records[-1]["recorded_at"]):
        raise LedgerError("時計が直前の記録より前を指している。追記しない")
    return records, rec, canonical_line(rec) + b"\n"


def append_record(ledger_path, kind, targets, note, now, expected_data=None):
    """記録を 1 件追記する。既存の行は書き換えない（追記のモードでだけ開く）。

    追記の前に、既存の記録の鎖を検証する。追記した後の記録の一覧を返す。
    expected_data: 渡したときは、今の記録のバイト列がこれと同じでなければ追記しない。
      中身（ledger_head など）を作ったあとで、別の記録が先に追記された場合に止めるため。
    """
    check_sealed_path(ledger_path)          # T-017：外へのリンクなら追記しない
    data = read_ledger(ledger_path)
    if expected_data is not None and data != expected_data:
        raise LedgerError("記録が、中身を作った時点から変わっている。追記しない")
    _records, rec, line = build_next_record(data, kind, targets, note, now)
    with open(ledger_path, "ab") as f:
        f.write(line)
        f.flush()
        os.fsync(f.fileno())
    after = verify_chain(read_ledger(ledger_path))
    if after[-1] != rec:
        raise LedgerError("追記の後の検証で、最後の記録が書いたものと一致しない")
    return after


def write_once(path, content):
    """新しいファイルを書く。既にあれば、中身が同じときだけ何もしない（上書きしない）。

    書く場所は sealed/ の中だけ（T-017。check_sealed_path。外へのリンクなら書かない）。
    """
    check_sealed_path(path)
    try:
        with open(path, "xb") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        return True
    except FileExistsError:
        with open(path, "rb") as f:
            if f.read() != content:
                raise LedgerError("%s が既にあり、中身が違う。上書きしない" % path) from None
        return False


# ---------------------------------------------------------------- 関門（T-009、T-014）

# 関門が読むプロジェクトのルート。このファイルの場所から決まり、引数では変えられない
# （T-014。T-009 の監査 軽2：偽の記録を置いた別のフォルダを指せば関門が通ってしまうため）。
# T-017（T-014 の監査 軽1）：関門は引数を一つも取らない（以前のテスト用の root の引数は外した）。
# テストは、この変数をテストの中で差し替えて仮のプロジェクトを読ませる。src/ の下に、
# この変数を書き換えるコードと、テスト用の root の引数の名前が無いことは、テストで確かめる
# （tests/sealer/test_t017.py）。同じ Python の中でモジュールの変数を書き換えることは
# 防げない（posixpath の os を置き換えるのと同じく、言語の上の限界）。
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def check_sealed_inside(project):
    """project/sealed と project/sealed/ledger.jsonl が、別の場所を指すリンクでないか。

    T-017（T-015 の監査 軽1・軽5 の sealer の側。差し戻し1回目の軽1 で厳しくした）。
    sealed/ やその中の記録をシンボリックリンクにして、別の場所の記録を読ませたり、別の場所に
    追記させたりすることを止める。確かめること：
      - realpath(project/sealed) == join(realpath(project), "sealed")
        （プロジェクトの中の別のフォルダを指すリンクも拒む。project より上の階層のリンク、
        例えば /tmp → /private/tmp は、両辺が同じだけずれるので通る）
      - 記録のファイルがあれば、realpath(project/sealed/ledger.jsonl) ==
        join(realpath(project/sealed), "ledger.jsonl")
    返り値: realpath(project)。
    限界：検査のあとで置き換えられること（検査と使用のあいだの競合）は防げない。
    """
    root = os.path.realpath(project)
    sealed = os.path.realpath(os.path.join(project, "sealed"))
    if sealed != os.path.join(root, "sealed"):
        raise LedgerError("sealed/ の実体（%s）が、プロジェクトの実体の sealed/（%s）ではない。"
                          "シンボリックリンクで別の場所を指している"
                          % (sealed, os.path.join(root, "sealed")))
    led = os.path.join(project, "sealed", "ledger.jsonl")
    if os.path.lexists(led):
        real = os.path.realpath(led)
        if real != os.path.join(sealed, "ledger.jsonl"):
            raise LedgerError("sealed/ledger.jsonl の実体（%s）が、sealed/ の中の ledger.jsonl ではない。"
                              "シンボリックリンクで別の場所を指している" % real)
    return root


def check_sealed_path(path):
    """sealed/ に書く・追記するファイルのパスを、書く前に確かめる。T-017（差し戻し1回目の中1）。

    path は <渡したルート>/sealed/<名前> の形（親のフォルダの名前が sealed）でなければならない。
    その親（渡したルート）について check_sealed_inside を行い、path がもう存在するなら、その実体が
    sealed/ の中の同じ名前であること（別の場所へのリンクでないこと）と、リンク数が 1 である
    こと（ハードリンクでないこと。T-023）も確かめる。書く仕組みの共通の入口
    （append_record、write_once、stamp.stamp_seq、stamp.upgrade_seq）が呼ぶ。
    渡したルートが PROJECT_ROOT であることは確かめない（書く仕組みは --root で別のルートを
    受け付け、テストは仮のプロジェクトに書くため。T-023 の軽2 で、手順書の書き方をこれに合わせた）。
    """
    sealed_dir = os.path.dirname(os.path.abspath(path))
    if os.path.basename(sealed_dir) != "sealed":
        raise LedgerError("%s は sealed/ の中のファイルではない。書かない" % path)
    check_sealed_inside(os.path.dirname(sealed_dir))
    if os.path.lexists(path):
        real = os.path.realpath(path)
        if real != os.path.join(os.path.realpath(sealed_dir), os.path.basename(path)):
            raise LedgerError("%s の実体（%s）が sealed/ の中に無い。シンボリックリンクで別の場所を"
                              "指している。書かない" % (path, real))
        # T-023（T-017 の再提出1回目の監査 軽3）：ハードリンクは realpath では見分けられない。
        # 書く先（追記する ledger.jsonl）のリンク数が 2 以上なら、別の名前で同じ実体を持つ
        # ファイルがある。追記がそちらにも及ぶので書かない。もう一方の名前の場所は分からない。
        nlink = os.lstat(path).st_nlink
        if nlink != 1:
            raise LedgerError("%s のリンク数が %d（ハードリンクで、別の名前が同じ実体を持つ）。書かない"
                              % (path, nlink))


class ThresholdAccessRequired(LedgerError):
    """threshold-access の記録が鎖に無い（または検証に通らない）ので、先に進まない。"""


class MethodAccessRequired(LedgerError):
    """method-access の記録が鎖に無い（または検証に通らない）ので、先に進まない。T-014。"""



class GkgRunResultRequired(LedgerError):
    """GKG の取得の run の結果のマニフェストが、gkg-run-result の記録で縛られていない。T-066。"""


def require_gkg_run_result(mode, run_id):
    """GKG の取得の run の結果（日の集計）を使うコードが、最初に呼ぶ関門（T-066 で提案。どこから呼ぶかは
    リードが収集係・統計係に割り振る）。

    引数は mode と run_id だけ（root は PROJECT_ROOT に固定）。鎖とすべての .ots が検証に通り、マニフェストが
    照合（check_gkg_manifests）に通り、mode・run_id の gkg-run-result の記録があってマニフェストの先頭と
    run-complete の行が記録と同じ（check_gkg_results）ときだけ、その記録を返す。そうでなければ
    GkgRunResultRequired で止める。正式な run は、この関門を通るまで「完了」と扱わない。
    """
    try:
        root = _gate_root()
        data, records = _load_for_gate(root)
        read = lambda r, role: read_target_json(root, r, role)  # noqa: E731
        manifests = {}
        for m, rel in GKG_MANIFESTS.items():
            path = os.path.join(root, rel)
            manifests[m] = None
            if os.path.lexists(path):
                if os.path.islink(path) or not os.path.isfile(path):
                    raise LedgerError("%s が通常のファイルでない" % rel)
                with open(path, "rb") as f:
                    manifests[m] = f.read()
        check_gkg_runs(records, read)
        check_gkg_manifests(records, read, manifests)
        for r in records:
            if r["kind"] == GKG_RESULT_KIND:
                check_gkg_result_doc(records, r, read(r, GKG_RESULT_KIND), read, data)
        got = check_gkg_results(records, read, manifests)
        rec = got.get((mode, run_id))
        if rec is None:
            raise LedgerError("mode %s・run_id %s の gkg-run-result の記録が無い。src/sealer/seal_gkg_result.py で"
                              "マニフェストを封印してから使う" % (mode, run_id))
    except GkgRunResultRequired:
        raise
    except LedgerError as e:
        raise GkgRunResultRequired("関門：%s" % e) from None
    return rec

def _gate_root():
    """関門が読むルート。PROJECT_ROOT（このファイルの場所から決まる）だけで、引数は無い。

    sealed/ がプロジェクトの下にあること（check_sealed_inside）も確かめる。
    """
    return check_sealed_inside(PROJECT_ROOT)


def _load_for_gate(root):
    """関門の共通の手順：鎖とすべての seq の .ots を検証する。(記録のバイト列, 記録の一覧)。"""
    sealed = os.path.join(root, "sealed")
    data = read_ledger(os.path.join(sealed, "ledger.jsonl"))
    records = verify_chain(data)
    check_anchors(data, sealed)
    return data, records


def check_candidates_ready(root, records, before_seq):
    """候補の順序の検査（T-014）。candidates の記録が before_seq より前に 1 件以上あり、
    すべて最初の acquisition-start より前にあり、形の照合に通ること。"""
    check_candidates_order(records)
    cands = [r for r in records if r["kind"] == CANDIDATES_KIND]
    if not any(r["seq"] < before_seq for r in cands):
        raise LedgerError("seq %d より前に candidates の記録が無い。閾値と判定期間の候補は、"
                          "先に封印する決まり" % before_seq)
    for r in cands:
        check_candidates_record(r)
        check_candidates_output(read_target_json(root, r, "output"))


def require_threshold_access():
    """閾値を決める期間の区画（2020-12-15 以降）のデータに触れるコードが、最初に呼ぶ関門。

    引数は取らない（root はプロジェクトのルート PROJECT_ROOT に固定。T-017）。
    鎖に threshold-access の記録があり、検証に通るときだけ、その最初の記録を返す。
    そうでなければ ThresholdAccessRequired で止める。確かめること：
      - 記録の鎖が正しく、すべての seq に、その seq 自身の .ots があること
      - 最初の threshold-access の記録の中身のファイルが、記録の sha256 と一致すること
      - 中身の kind・ledger_head・drand（randomness が signature の sha256）が照合に通ること
      - 中身の block_start が、periods の 1 件目の出力の閾値の期間の始まりと一致すること
      - 候補の順序（T-014）：最初の threshold-access より前に candidates の記録が 1 件以上
        あり、すべての candidates が最初の acquisition-start より前にあり、形の照合に通ること
      - J とエンバーゴ（T-017、T-023、T-027）：check_horizon_embargo。最初の method-access より
        後の periods-triggers の J が null か J の最大と等しいこと。採用される periods の embargo_days が
        max(periods の 1 件目の embargo_days, candidates の J の最大) と等しいこと。採用される
        periods-triggers の J が null でなければ J の最大と等しいこと。J の最大が 1 件目の
        embargo_days を超えるときは、その periods-triggers が要ること
      - periods の deadline_status（T-027）：check_deadline_statuses。verify.py periods と同じ規則
      - sealed/ と記録のファイルの実体が、プロジェクトの下にあること（check_sealed_inside）
    記録が無ければ、先に src/sealer/seal_access.py で threshold-access を追記する。

    限界：この関門を呼ばずにデータに触れるコードを書くこと、関門を飛ばして触れることは、
    記録からは検出できない。記録に残るのは「threshold-access を追記した」ことだけで、
    「それより前に触れなかった」ことは示せない（docs/verify/periods-seal.md 7章の
    「示せないこと」の「記録に無い接触」）。関門は、正直な運用で手順を飛ばす誤りを防ぐ
    ためのもので、証明ではない。
    """
    try:
        root = _gate_root()
        data, records = _load_for_gate(root)
        rec = first_threshold_access(records)
        if rec is None:
            raise LedgerError("threshold-access の記録が鎖に無い。閾値を決める期間の区画"
                              "（2020-12-15 以降）のデータには触れない。先に "
                              "src/sealer/seal_access.py で追記する")
        doc = read_target_json(root, rec, THRESHOLD_ACCESS_KIND)
        check_drand_record(data, rec, doc, None)
        got = threshold_access_block_start(doc)
        want = first_threshold_block_start(root, records)
        if got != want:
            raise LedgerError("threshold-access（seq %d）の block_start %s が、periods の 1 件目の"
                              "閾値の期間の始まり %s と一致しない" % (rec["seq"], got, want))
        check_candidates_ready(root, records, rec["seq"])
        check_horizon_embargo(records, lambda r, role: read_target_json(root, r, role))
        check_deadline_statuses(records, lambda r, role: read_target_json(root, r, role))
    except ThresholdAccessRequired:
        raise
    except LedgerError as e:
        raise ThresholdAccessRequired("関門：%s" % e) from None
    return rec


def require_method_access():
    """手法を作る期間の区画のデータそのもの（試運転の手順4）に触れるコードが、最初に呼ぶ関門。T-014。

    引数は取らない（root はプロジェクトのルート PROJECT_ROOT に固定。T-017）。
    鎖に method-access の記録があり、検証に通るときだけ、その最初の記録を返す。
    そうでなければ MethodAccessRequired で止める。確かめること：
      - 記録の鎖が正しく、すべての seq に、その seq 自身の .ots があること
      - 最初の method-access の記録の中身のファイルが、記録の sha256 と一致すること
      - 中身の kind・step（4）・ledger_head・drand・区画（periods の 1 件目の method の区画）
      - 前提：その記録より前に candidates と acquisition-result の記録があること
        （check_method_access_order）。acquisition-start と result の対応が正しいこと
      - 候補の順序：candidates が最初の acquisition-start より前にあり、形の照合に通ること
      - J とエンバーゴ（T-017、T-023）：check_horizon_embargo（require_threshold_access と同じ）
      - 順番1・1b（T-037）：check_stats_order。順番1・1b の記録が method-access より後に無いこと
      - periods の deadline_status（T-031）：check_deadline_statuses(provisional=True)。
        threshold-access がまだ無ければ、periods-triggers の最後の記録を仮の採用として比べる
      - sealed/ と記録のファイルの実体が、プロジェクトの下にあること（check_sealed_inside）
    記録が無ければ、先に src/sealer/seal_method.py で method-access を追記する。

    限界：require_threshold_access と同じ。この関門を呼ばずにデータに触れること、関門の前に
    触れることは、記録からは検出できない。記録に残るのは「method-access を追記した」ことだけで、
    「それより前に触れなかった」ことは示せない。関門は、正直な運用で手順を飛ばす誤りを防ぐ
    ためのもので、証明ではない。
    """
    try:
        root = _gate_root()
        data, records = _load_for_gate(root)
        check_method_access_order(records)
        rec = None
        for r in records:
            if r["kind"] == METHOD_ACCESS_KIND:
                rec = r
                break
        if rec is None:
            raise LedgerError("method-access の記録が鎖に無い。手法を作る期間の区画のデータ"
                              "（試運転の手順4）には触れない。先に src/sealer/seal_method.py で"
                              "追記する")
        doc = read_target_json(root, rec, METHOD_ACCESS_KIND)
        check_drand_record(data, rec, doc, None)
        check_method_access_doc(root, records, rec, doc)
        refs = {}
        for r in records:
            if r["kind"] == ACQ_RESULT_KIND:
                refs[r["seq"]] = acquisition_result_fields(
                    r, read_target_json(root, r, ACQ_RESULT_KIND))[0]
        check_acquisition_pairs(records, refs)
        check_candidates_ready(root, records, rec["seq"])
        check_horizon_embargo(records, lambda r, role: read_target_json(root, r, role))
        # T-037：順番1・1b の位置（method-access より前にだけある、など）。T-046 で、method-access の前に
        # 順番1b があることも関門で照らす（収集係のテストが T-045 で関門の文言を受け付ける形になった）
        check_stats_order(records, lambda r, role: read_target_json(root, r, role))
        # T-031（T-027 の監査 中1）：仮の採用（periods-triggers の最後の記録）での deadline_status
        check_deadline_statuses(records, lambda r, role: read_target_json(root, r, role),
                                provisional=True)
    except MethodAccessRequired:
        raise
    except LedgerError as e:
        raise MethodAccessRequired("関門：%s" % e) from None
    return rec
