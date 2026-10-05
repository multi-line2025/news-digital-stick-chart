#!/usr/bin/env python3
"""OpenTimestamps の .ots を、ネットワークも外部の部品も使わずに読む。T-005。

できること
  - .ots の対象のハッシュ（file digest）を取り出す。
  - 証明の木をたどり、各証明（attestation）について、そこに届く値（msg）を計算する。
    Pending（カレンダーの受付のみ）と Bitcoin（ブロックの高さ）を見分ける。
  - Bitcoin の証明について、渡されたブロックのヘッダ（80 バイト）を照合する。
      1. ヘッダのマークルルートが、証明の木で計算した値と一致すること
      2. ヘッダのハッシュが、ヘッダ自身の nBits の目標値以下であること（作業量の証明）
      3. その目標値が MIN_WORK_BITS で決めた下限より難しいこと（安く作ったヘッダを拒む）
    通ればヘッダの時刻（UTC）とブロックのハッシュを返す。

できないこと（ots verify や Bitcoin のノードで確かめる）
  - そのヘッダが、Bitcoin の本当の鎖の、その高さのブロックであること。
    ここでは、ヘッダの値を自由に入れても通らないこと（対象のハッシュに結び付き、
    大きな作業量を持つこと）までしか確かめない。出力するブロックのハッシュを、
    `bitcoin-cli getblockhash <高さ>` などと見比べるのは検証する人の仕事である。

形式（python-opentimestamps の serialize と同じ）
  先頭の印、版（varuint で 1）、ハッシュの種類の札（1 バイト）、対象のハッシュ、証明の木。
  証明の木: 札 0xff が続く限り枝。札 0x00 は証明（8 バイトの種類の札 + varbytes）。
  それ以外の札は演算で、その結果から下の木が続く。
"""

import datetime
import hashlib

MAGIC = (b"\x00OpenTimestamps\x00\x00Proof\x00"
         b"\xbf\x89\xe2\xe8\x84\xe8\x92\x94")
MAJOR_VERSION = 1

TAG_BITCOIN = bytes.fromhex("0588960d73d71901")
TAG_PENDING = bytes.fromhex("83dfe30d2ef90c8e")

UNARY = {0x08: "sha256", 0x02: "sha1", 0x03: "ripemd160", 0x67: "keccak256",
         0xf2: "reverse", 0xf3: "hexlify"}
BINARY = {0xf0: "append", 0xf1: "prepend"}
DIGEST_LEN = {0x08: 32, 0x02: 20, 0x03: 20, 0x67: 32}

MAX_DEPTH = 256
MAX_ARG = 4096
MAX_MSG = 4096

# 作業量の下限：ヘッダの目標値が 2^256 / 2^MIN_WORK_BITS 以下であること。
# 2^77 回のハッシュは、Bitcoin の全体の計算力（2026 年におよそ 2^70 回/秒）で 2 分ほど、
# その 1% の計算力なら 4 時間ほどにあたる。本物のブロックは 2025 年の時点でおよそ 2^78.7 回
# で、下限の 3 倍ほど難しい。下限は偽のヘッダを高くつかせるためのもので、本当の鎖に
# あることの証明ではない（それは ots verify か Bitcoin のノードで確かめる）。
MIN_WORK_BITS = 77


class OtsError(Exception):
    """.ots を読めない、または照合に失敗した。"""


class _Reader:
    def __init__(self, data):
        self.data = data
        self.pos = 0

    def read(self, n):
        if self.pos + n > len(self.data):
            raise OtsError(".ots が途中で切れている")
        out = self.data[self.pos:self.pos + n]
        self.pos += n
        return out

    def byte(self):
        return self.read(1)[0]

    def varuint(self):
        value = 0
        shift = 0
        while True:
            b = self.byte()
            value |= (b & 0x7f) << shift
            if not b & 0x80:
                return value
            shift += 7
            if shift > 63:
                raise OtsError("varuint が長すぎる")

    def varbytes(self, limit=MAX_ARG):
        n = self.varuint()
        if n > limit:
            raise OtsError("varbytes が長すぎる")
        return self.read(n)


def _apply(tag, msg, arg=None):
    name = UNARY.get(tag) or BINARY.get(tag)
    if name == "sha256":
        out = hashlib.sha256(msg).digest()
    elif name == "sha1":
        out = hashlib.sha1(msg).digest()
    elif name == "ripemd160":
        try:
            out = hashlib.new("ripemd160", msg).digest()
        except ValueError:
            raise OtsError("この python では ripemd160 を計算できない") from None
    elif name == "keccak256":
        raise OtsError("keccak256 の演算には対応していない")
    elif name == "reverse":
        out = msg[::-1]
    elif name == "hexlify":
        out = msg.hex().encode()
    elif name == "append":
        out = msg + arg
    elif name == "prepend":
        out = arg + msg
    else:
        raise OtsError("知らない演算の札 0x%02x" % tag)
    if len(out) > MAX_MSG:
        raise OtsError("演算の結果が長すぎる")
    return out


def _walk(r, msg, depth, out):
    if depth > MAX_DEPTH:
        raise OtsError("証明の木が深すぎる")

    def one(tag):
        if tag == 0x00:
            kind = r.read(8)
            payload = r.varbytes(8192)
            if kind == TAG_BITCOIN:
                pr = _Reader(payload)
                height = pr.varuint()
                out.append({"type": "bitcoin", "height": height, "msg": msg})
            elif kind == TAG_PENDING:
                pr = _Reader(payload)
                uri = pr.varbytes(1000).decode("utf-8", "replace")
                out.append({"type": "pending", "uri": uri, "msg": msg})
            else:
                out.append({"type": "unknown", "tag": kind.hex(), "msg": msg})
        elif tag in BINARY:
            arg = r.varbytes()
            _walk(r, _apply(tag, msg, arg), depth + 1, out)
        elif tag in UNARY:
            _walk(r, _apply(tag, msg), depth + 1, out)
        else:
            raise OtsError("知らない札 0x%02x" % tag)

    tag = r.byte()
    while tag == 0xff:
        one(r.byte())
        tag = r.byte()
    one(tag)


def parse(data):
    """(対象のハッシュの16進, 証明の一覧) を返す。末尾に余りがあれば失敗。"""
    if not data.startswith(MAGIC):
        raise OtsError(".ots の先頭の印が違う")
    r = _Reader(data)
    r.read(len(MAGIC))
    if r.varuint() != MAJOR_VERSION:
        raise OtsError(".ots の版が %d でない" % MAJOR_VERSION)
    hash_tag = r.byte()
    if hash_tag != 0x08:
        raise OtsError(".ots のハッシュの種類が sha256 でない")
    digest = r.read(DIGEST_LEN[hash_tag])
    atts = []
    _walk(r, digest, 0, atts)
    if r.pos != len(data):
        raise OtsError(".ots の末尾に余分なバイトがある")
    return digest.hex(), atts


def target_from_bits(bits):
    exp = bits >> 24
    mant = bits & 0x007fffff
    if bits & 0x00800000:
        raise OtsError("nBits が負の値を表している")
    if exp <= 3:
        return mant >> (8 * (3 - exp))
    return mant << (8 * (exp - 3))


def check_header(header, msg, min_work_bits=MIN_WORK_BITS):
    """ヘッダを証明の値 msg と照合し、(時刻, ブロックのハッシュの16進) を返す。"""
    if len(header) != 80:
        raise OtsError("ヘッダが 80 バイトでない")
    if header[36:68] != msg:
        raise OtsError("ヘッダのマークルルートが、証明の木の値と一致しない")
    bits = int.from_bytes(header[72:76], "little")
    target = target_from_bits(bits)
    if target <= 0 or target > (1 << 256) >> min_work_bits:
        raise OtsError("ヘッダの目標値が、作業量の下限（2^%d）より易しい" % min_work_bits)
    h = hashlib.sha256(hashlib.sha256(header).digest()).digest()
    if int.from_bytes(h, "little") > target:
        raise OtsError("ヘッダのハッシュが目標値を超えている（作業量の証明が無い）")
    t = int.from_bytes(header[68:72], "little")
    when = datetime.datetime.fromtimestamp(t, datetime.timezone.utc)
    return when, h[::-1].hex()
