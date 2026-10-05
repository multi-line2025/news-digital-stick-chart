#!/usr/bin/env python3
"""封印の記録（追記のみ）の中核。T-005。

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

採用の規則（adopted_record）
    同じ種類の記録が期限前に複数ある場合は、期限前の最後の追記（seq が最大のもの）だけを
    有効とする。「期限前」は recorded_at（申告）では決めず、時刻証明で決める。
    記録 k が存在した時刻の上限は、seq >= k の .ots のうち、Bitcoin で確定した時刻の
    最小値である。この時刻に安全の幅（既定 3 時間。Bitcoin のブロックの時刻の揺れの分）
    を足しても期限より前なら、記録 k は期限前とみなす。

区画の一致（check_blocks）
    periods の後の版の出力の block_start と block_end は、最初に封印した版（periods の
    1 件目）の出力と一致しなければならない。
"""

import datetime
import hashlib
import json
import os
import re

GENESIS_PREV = "0" * 64
RECORD_KEYS = ("kind", "note", "prev_hash", "recorded_at", "seq", "targets")
TARGET_KEYS = ("path", "role", "sha256")
HEX64 = re.compile(r"\A[0-9a-f]{64}\Z")
TIME_RE = re.compile(r"\A\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z\Z")
KIND_RE = re.compile(r"\A[a-z][a-z0-9_-]{0,31}\Z")
OTS_NAME_RE = re.compile(r"\Aledger\.jsonl\.seq(\d{6})(\.bitcoin)?\.ots\Z")

# Bitcoin のブロックの時刻は、実際の時刻から数時間ずれうる。期限との比較では、
# この幅を足しても期限より前であることを求める。
DEFAULT_BLOCK_TIME_MARGIN = datetime.timedelta(hours=3)

# OpenTimestamps の .ots の先頭（DetachedTimestampFile の形式）。
OTS_MAGIC = (b"\x00OpenTimestamps\x00\x00Proof\x00"
             b"\xbf\x89\xe2\xe8\x84\xe8\x92\x94")
OTS_VERSION = 1
OTS_OP_SHA256 = 0x08


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


def proven_time_of(seq, anchor_times):
    """記録 seq が存在した時刻の上限（時刻証明による）。

    anchor_times: {.ots の対象の seq: Bitcoin で確定した時刻（UTC の datetime）}。
    seq 以上の .ots のうちの最小の時刻。確定した .ots が無ければ None。
    """
    times = [t for s, t in anchor_times.items() if s >= seq]
    return min(times) if times else None


def adopted_record(records, kind, deadline, anchor_times,
                   margin=DEFAULT_BLOCK_TIME_MARGIN):
    """期限前の最後の追記を返す。期限前の記録が無ければ None。

    recorded_at（申告）は使わない。時刻証明で期限前と示せる記録だけが候補になる。
    """
    if deadline.tzinfo is None:
        raise ValueError("期限にはタイムゾーンを付けること")
    best = None
    for r in records:
        if r["kind"] != kind:
            continue
        t = proven_time_of(r["seq"], anchor_times)
        if t is not None and t + margin < deadline:
            if best is None or r["seq"] > best["seq"]:
                best = r
    return best


# ---------------------------------------------------------------- periods の検査


def output_target(record):
    """periods の記録の出力（role が output）の対象。ちょうど 1 つでなければ失敗。"""
    outs = [t for t in record["targets"] if t["role"] == "output"]
    if len(outs) != 1:
        raise LedgerError("seq %d: role が output の対象が 1 つでない" % record["seq"])
    return outs[0]


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


def check_deadline_status(output, proven_before_deadline):
    """出力の deadline_status（統計係の申告）を、記録から決まる事実と照合する。

    proven_before_deadline: 記録が時刻証明で期限前と示せるなら True、示せないなら False、
    まだ判断できない（期限か時刻証明が未確定）なら None。
    食い違いの一覧を返す（空なら問題なし）。
    """
    status = output.get("deadline_status")
    triggers = output.get("rebuild_triggers") or {}
    any_trigger = any(v is not None for v in triggers.values())
    problems = []
    if status is None:
        if any_trigger:
            problems.append("きっかけの値があるのに deadline_status が null")
        return problems
    if status not in ("before_deadline", "after_deadline"):
        return ["deadline_status の値が不正: %r" % (status,)]
    if not any_trigger:
        problems.append("きっかけの値が無いのに deadline_status がある")
    if status == "before_deadline" and proven_before_deadline is False:
        problems.append("before_deadline と申告しているが、記録は期限前と示せない")
    return problems


# ---------------------------------------------------------------- 時刻証明の照合


def ots_file_digest(ots_bytes):
    """.ots の先頭から、対象の sha256 を取り出す（ネットワークも外部の部品も使わない）。"""
    if not ots_bytes.startswith(OTS_MAGIC):
        raise LedgerError(".ots の先頭の印が違う")
    pos = len(OTS_MAGIC)
    if len(ots_bytes) < pos + 2 + 32:
        raise LedgerError(".ots が短すぎる")
    if ots_bytes[pos] != OTS_VERSION:
        raise LedgerError(".ots の版が %d でない" % OTS_VERSION)
    if ots_bytes[pos + 1] != OTS_OP_SHA256:
        raise LedgerError(".ots のハッシュの種類が sha256 でない")
    return ots_bytes[pos + 2:pos + 2 + 32].hex()


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


def check_anchors(data, sealed_dir, require_last=True):
    """各 .ots の対象が、記録の先頭 N 行の sha256 と一致するかを確かめる。

    require_last が真なら、最後の記録を覆う .ots（seq が最後の記録のもの）があることも
    求める。最後の行の書き換えや末尾の行の削除は、ここで検出する。
    [(seq, .ots のパス, digest)] を返す。
    """
    lines = split_lines(data)
    anchors = list_anchors(sealed_dir)
    result = []
    for seq, path in anchors:
        if seq > len(lines):
            raise LedgerError("%s は %d 行目までを対象にしているが、記録は %d 行しかない"
                              "（末尾の行が削除された）" % (os.path.basename(path), seq, len(lines)))
        with open(path, "rb") as f:
            digest = ots_file_digest(f.read())
        expect = prefix_digest(data, seq)
        if digest != expect:
            raise LedgerError("%s の対象のハッシュが、記録の先頭 %d 行と一致しない"
                              % (os.path.basename(path), seq))
        result.append((seq, path, digest))
    if require_last and lines and len(lines) not in {s for s, _ in anchors}:
        raise LedgerError("最後の記録（seq %d）を覆う時刻証明が無い" % len(lines))
    return result


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
