#!/usr/bin/env python3
"""封印の記録（追記のみ）の中核。T-005、T-007、T-008、T-009、T-013、T-014、T-017。

記録のファイル（既定は sealed/ledger.jsonl）は JSON Lines で、1 行が 1 件の記録。
標準ライブラリだけを使う。ネットワークは使わない。

1 行の形（キーはこの 6 つだけ。ほかのキーがあれば検証で失敗にする）
    seq          通し番号。1 から始まり、行の順に 1 ずつ増える。
    prev_hash    直前の行のバイト列（末尾の改行を含めない）の sha256。1 行目は 0 が 64 個。
    kind         種類。許可リスト（ALLOWED_KINDS）の 7 つだけ。それ以外は検証で失敗にする。
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
      開始）は区切りに使わない（T-014 のリードの指示。区切りは threshold-access のまま）。
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
ALLOWED_KINDS = (PERIODS_KIND, TRIGGERS_KIND, THRESHOLD_ACCESS_KIND, ACQ_START_KIND,
                 ACQ_RESULT_KIND, CANDIDATES_KIND, METHOD_ACCESS_KIND)

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
    acquisition-start・acquisition-result・method-access は区切りに使わない。
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

DRAND_RECORD_KINDS = (THRESHOLD_ACCESS_KIND, ACQ_START_KIND, METHOD_ACCESS_KIND)
# drand を持つ記録のうち、中身に step を持つものと、その値。
DRAND_RECORD_STEP = {ACQ_START_KIND: 3, METHOD_ACCESS_KIND: 4}


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


def check_horizon_embargo(records, read_json):
    """candidates の J の最大 ≤ periods の embargo_days かを確かめる。T-017（T-014 の監査 軽4）。

    read_json(記録, role) は、記録の対象のファイルを sha256 を照合して JSON で返す関数。
    - J の最大は、すべての candidates の記録の出力の J の最大（candidates_max_j）。
    - エンバーゴは、periods の 1 件目（最初に封印した版）の出力の rules.embargo_days。
    - J の最大 ≤ エンバーゴなら、区切りは作り直さなくてよく、periods-triggers は求めない。
    - 超えたときに限り、periods-triggers の記録を求める。期限は、最初の method-access と最初の
      threshold-access のうち早い方（docs/stats/periods.md 8章 (2)：J は手順4の前、かつ期限より
      前に追記する）。その期限より seq が小さい periods-triggers の記録のどれかの
      last_read_offset_days が、J の最大以上でなければ LedgerError。期限の記録がまだ無ければ保留。
    返り値: {"j_max", "embargo", "status", "deadline", "triggers"}。status は
      "no-candidates"（candidates が無い）、"within"（超えていない）、"ok"（超えていて、
      periods-triggers がある）、"pending"（超えているが、期限の記録がまだ無い）。
    """
    cands = [r for r in records if r["kind"] == CANDIDATES_KIND]
    out = {"j_max": None, "embargo": None, "status": "no-candidates", "deadline": None,
           "triggers": None}
    if not cands:
        return out
    out["j_max"] = max(candidates_max_j(read_json(r, "output")) for r in cands)
    versions = records_of_kind(records, PERIODS_KIND)
    if not versions:
        raise LedgerError("periods の記録が無い")
    out["embargo"] = periods_embargo_days(read_json(versions[0][1], "output"))
    if out["j_max"] <= out["embargo"]:
        out["status"] = "within"
        return out
    marks = [r for r in records if r["kind"] in (METHOD_ACCESS_KIND, THRESHOLD_ACCESS_KIND)]
    if not marks:
        out["status"] = "pending"
        return out
    deadline = marks[0]
    out["deadline"] = deadline
    for r in records:
        if r["kind"] != TRIGGERS_KIND or r["seq"] >= deadline["seq"]:
            continue
        j = triggers_values(read_json(r, "triggers"))["last_read_offset_days"]
        if j is not None and j >= out["j_max"]:
            out["status"], out["triggers"] = "ok", r
            return out
    raise LedgerError("candidates の J の最大 %d が、periods の 1 件目の embargo_days %d を超えている。"
                      "%s の記録（seq %d）より前に、last_read_offset_days が %d 以上の "
                      "periods-triggers の記録が要る" % (out["j_max"], out["embargo"],
                                                       deadline["kind"], deadline["seq"],
                                                       out["j_max"]))


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
    """新しいファイルを書く。既にあれば、中身が同じときだけ何もしない（上書きしない）。"""
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
    """project/sealed と project/sealed/ledger.jsonl の実体が、project の実体の下にあるか。

    T-017（T-015 の監査 軽1・軽5 の sealer の側）。sealed/ やその中の記録をシンボリックリンクに
    して、別の場所の記録を読ませたり、別の場所に追記させたりすることを止める。
    確かめること：realpath(project/sealed) が realpath(project) の下（それ自身ではない）にあり、
    realpath(project/sealed/ledger.jsonl) が realpath(project/sealed) の下にあること。
    記録のファイルがまだ無いときは、sealed/ の検査だけをする。返り値: realpath(project)。
    限界：検査のあとで置き換えられること（検査と使用のあいだの競合）は防げない。
    """
    root = os.path.realpath(project)
    sealed = os.path.realpath(os.path.join(project, "sealed"))
    if os.path.commonpath([root, sealed]) != root or sealed == root:
        raise LedgerError("sealed/ の実体（%s）が、プロジェクトの実体（%s）の下に無い。"
                          "シンボリックリンクで別の場所を指している" % (sealed, root))
    led = os.path.join(project, "sealed", "ledger.jsonl")
    if os.path.lexists(led):
        real = os.path.realpath(led)
        if os.path.commonpath([sealed, real]) != sealed or real == sealed:
            raise LedgerError("sealed/ledger.jsonl の実体（%s）が、sealed/ の実体（%s）の下に無い。"
                              "シンボリックリンクで別の場所を指している" % (real, sealed))
    return root


class ThresholdAccessRequired(LedgerError):
    """threshold-access の記録が鎖に無い（または検証に通らない）ので、先に進まない。"""


class MethodAccessRequired(LedgerError):
    """method-access の記録が鎖に無い（または検証に通らない）ので、先に進まない。T-014。"""


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
      - J とエンバーゴ（T-017）：check_horizon_embargo。candidates の J の最大が periods の
        embargo_days を超えるときだけ、期限より前に periods-triggers の記録があること
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
      - J とエンバーゴ（T-017）：check_horizon_embargo（require_threshold_access と同じ）
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
    except MethodAccessRequired:
        raise
    except LedgerError as e:
        raise MethodAccessRequired("関門：%s" % e) from None
    return rec
