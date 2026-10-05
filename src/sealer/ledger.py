#!/usr/bin/env python3
"""封印の記録（追記のみ）の中核。T-005、T-007。

記録のファイル（既定は sealed/ledger.jsonl）は JSON Lines で、1 行が 1 件の記録。
標準ライブラリだけを使う。ネットワークは使わない。

1 行の形（キーはこの 6 つだけ。ほかのキーがあれば検証で失敗にする）
    seq          通し番号。1 から始まり、行の順に 1 ずつ増える。
    prev_hash    直前の行のバイト列（末尾の改行を含めない）の sha256。1 行目は 0 が 64 個。
    kind         種類（例: "periods"）。
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

採用の規則（adoption）。T-007 で、時刻ではなく鎖の順番で決める形に改めた。
    採用するのは、最初の acquisition の記録より seq が小さい記録のうち、その種類
    （periods、periods-triggers）の最後のもの。
    - acquisition の記録がまだ無いうちは「採用は保留」。仮の候補として、今ある最後の記録を示す。
    - 時刻（Bitcoin の確定時刻、drand の回の公開時刻）も、Pending かどうかも、recorded_at
      （申告）も使わない。adoption の引数は記録の一覧と種類だけである。
    - 鎖は行を消せず、順番も入れ替えられない（verify_chain）。そのため、.ots の upgrade を
      出すか出さないか、Pending のままにするか、drand のどの回を書くかで、採用は変わらない。

acquisition の記録（手順3の取得の記録）の照合（check_acquisition）
    - 中身の ledger_head が、直前の記録までの先頭の sha256（seq N−1 の .ots の対象と同じ値）と
      一致すること。
    - drand の回の公開時刻が、その acquisition の記録自身の .ots の Bitcoin の確定時刻より
      前であること。確定していなければ、この照合は保留する。
    - drand の署名（BLS）は、オフラインでは検証しない。randomness が signature の sha256
      であることだけを確かめる。

きっかけの値（kind が periods-triggers）
    区切りを作り直すきっかけの値は、periods-triggers の記録として追記する。periods の
    出力の rebuild_triggers が、採用された periods-triggers の記録と完全に一致すれば
    before_deadline、そうでなければ after_deadline が記録から決まる値で、
    出力の deadline_status（申告）と照合する（judge_deadline_status）。
    docs/stats/periods.md 8章 (2) の「期限前に追記した」は、この規則では「最初の
    acquisition の記録より前に鎖に入った」ことに当たる。

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
    欠番、正規でない書き方、形の違い、recorded_at の逆行。
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


ACQUISITION_KIND = "acquisition"
ADOPTED_KINDS = ("periods", "periods-triggers")


def first_acquisition(records):
    """最初の kind=acquisition の記録。無ければ None。"""
    for r in records:
        if r["kind"] == ACQUISITION_KIND:
            return r
    return None


def adoption(records, kind):
    """採用の規則（鎖の順番だけで決める）。

    返り値: (採用された記録, 仮の候補, 区切りに使った acquisition の記録)
      - acquisition の記録がある: 採用 = その seq より小さい、その種類の最後の記録
        （無ければ None）。仮の候補は None。
      - acquisition の記録が無い: 採用は保留（None）。仮の候補 = 今ある、その種類の
        最後の記録（無ければ None）。acquisition の記録は None。
    時刻・Pending かどうか・recorded_at は、引数にも無く、使わない。
    """
    of_kind = [r for r in records if r["kind"] == kind]
    acq = first_acquisition(records)
    if acq is None:
        return None, (of_kind[-1] if of_kind else None), None
    before = [r for r in of_kind if r["seq"] < acq["seq"]]
    return (before[-1] if before else None), None, acq


# ---------------------------------------------------------------- acquisition の記録の照合

# drand の鎖（公開されている値）。回 r の公開時刻は genesis_time + (r - 1) * period。
DRAND_CHAINS = {
    # quicknet
    "52db9ba70e0cc0f6eaf7803dd07447a1f5477735fd3f661792ba94600c84e971": (1692803367, 3),
    # default（mainnet）
    "8990e7a9aaed2ffed73dbd7092123d6f289930540d7651336225dc172e51b2ce": (1595431050, 30),
}
DRAND_NOT_VERIFIED = ("drand の署名（BLS）は、オフラインでは検証していない（randomness が "
                      "signature の sha256 であることだけを確かめた）。")


def drand_round_time(chain_hash, round_no):
    if chain_hash not in DRAND_CHAINS:
        raise LedgerError("知らない drand の鎖: %s" % chain_hash)
    if type(round_no) is not int or round_no < 1:
        raise LedgerError("drand の回の番号が正の整数でない")
    genesis, period = DRAND_CHAINS[chain_hash]
    return datetime.datetime.fromtimestamp(genesis + (round_no - 1) * period,
                                           datetime.timezone.utc)


def drand_time_of_acquisition(doc):
    """取得の記録の中身（JSON）から、drand の回の公開時刻を出す。

    randomness が signature の sha256 であることも確かめる（drand の決まり）。
    署名そのものの検証（BLS）はここではしない（DRAND_NOT_VERIFIED）。
    """
    try:
        d = doc["drand"]
        chain, rnd = d["chain_hash"], d["round"]
        randomness, signature = d["randomness"], d["signature"]
        if doc["step"] != 3:
            raise LedgerError("取得の記録の step が 3 でない")
    except (KeyError, TypeError):
        raise LedgerError("取得の記録に step か drand（chain_hash・round・randomness・"
                          "signature）が無い") from None
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


def check_acquisition(data, record, doc, own_time):
    """acquisition の記録を照合する。

    own_time: その記録自身の .ots で Bitcoin に確定した時刻（無ければ None）。
    返り値: (drand の回の公開時刻, "ok" か "pending")。食い違えば LedgerError。
    この照合は採用の判定に使わない。
    """
    seq = record["seq"]
    head = doc.get("ledger_head") if isinstance(doc, dict) else None
    want = expected_ledger_head(data, seq)
    if not isinstance(head, dict) or sorted(head) != ["seq", "sha256"]:
        raise LedgerError("seq %d の取得の記録に ledger_head（seq・sha256）が無い" % seq)
    if head != want:
        raise LedgerError("seq %d の取得の記録の ledger_head が、直前の記録のハッシュと一致しない"
                          "（入れた値 seq %r、記録から決まる値 seq %d の %s）"
                          % (seq, head.get("seq"), want["seq"], want["sha256"]))
    t3 = drand_time_of_acquisition(doc)
    if own_time is None:
        return t3, "pending"
    if not t3 < own_time:
        raise LedgerError("seq %d の取得の記録の drand の回の公開時刻 %s が、その記録自身の .ots の"
                          "確定時刻 %s より前でない" % (seq, t3.isoformat(), own_time.isoformat()))
    return t3, "ok"


# ---------------------------------------------------------------- periods の検査

TRIGGERS_KIND = "periods-triggers"
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

    decided: 採用が決まっているか（acquisition の記録があるか）。
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


def append_record(ledger_path, kind, targets, note, now):
    """記録を 1 件追記する。既存の行は書き換えない（追記のモードでだけ開く）。

    追記の前に、既存の記録の鎖を検証する。追記した後の記録の一覧を返す。
    """
    data = read_ledger(ledger_path)
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
    line = canonical_line(rec) + b"\n"
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
