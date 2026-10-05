#!/usr/bin/env python3
"""封印の仕組みが通信する部分（drand の最新の回、Bitcoin のブロックのヘッダ）。T-009。

通信はすべて、この中の http_get を通る。呼ぶ側は fetch 引数で差し替えられる
（テストは差し替えたものを使い、ネットワークを使わない）。OpenTimestamps のカレンダーとの
通信は、ots のクライアント（stamp.py。runner 引数で差し替えられる）が行う。

通信の決まり（コードに固定する）
    - 宛先は、下の ALLOWED_URL_PREFIXES で始まる https の URL だけ。それ以外は送る前に止める。
    - 1 回の待ち時間の上限 TIMEOUT_SECONDS、再試行の上限 MAX_TRIES、再試行の間の待ち WAIT_SECONDS。
    - 応答の大きさの上限 MAX_BYTES。
    - 送るのは GET の要求だけで、本文は送らない。要求の URL には、回の番号・ブロックの高さ・
      ブロックのハッシュのほかは何も入れない。

drand（quicknet）
    最新の回を、DRAND_URLS の順に取りにいき、最初に検査に通ったものを使う。
    検査：JSON のキー、round が正の整数、signature が 16 進、randomness が signature の
    sha256、回の公開時刻が「今」から DRAND_MAX_AGE より古くなく、DRAND_MAX_AHEAD より先でない。
    「今」は記録する機械の時計で、証明ではない。署名（BLS）はここでも検証しない。

Bitcoin のヘッダ
    HEADER_SOURCES のすべて（2 つのブロックエクスプローラー）から、高さ→ブロックのハッシュ→
    ヘッダ（80 バイト）を取り、すべてが同じヘッダを返し、ヘッダのハッシュが返されたブロックの
    ハッシュと一致するときだけ使う。手元の Bitcoin のノードがあれば、bitcoin-cli を使う
    取り方（header_from_bitcoin_cli）もある。どちらでも、書く前に .ots の証明と照合する
    （seal_bitcoin.py）。
"""

import datetime
import hashlib
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import ledger  # noqa: E402

TIMEOUT_SECONDS = 20
MAX_TRIES = 3
WAIT_SECONDS = 5
MAX_BYTES = 1 << 16

QUICKNET = "52db9ba70e0cc0f6eaf7803dd07447a1f5477735fd3f661792ba94600c84e971"
assert QUICKNET in ledger.DRAND_CHAINS
DRAND_URLS = (
    "https://api.drand.sh/%s/public/latest" % QUICKNET,
    "https://api2.drand.sh/%s/public/latest" % QUICKNET,
    "https://api3.drand.sh/%s/public/latest" % QUICKNET,
    "https://drand.cloudflare.com/%s/public/latest" % QUICKNET,
)
DRAND_MAX_AGE = datetime.timedelta(minutes=5)
DRAND_MAX_AHEAD = datetime.timedelta(minutes=1)

HEADER_SOURCES = (
    "https://blockstream.info/api",
    "https://mempool.space/api",
)

ALLOWED_URL_PREFIXES = tuple(u.rsplit("/public/latest", 1)[0] + "/" for u in DRAND_URLS) + tuple(
    s + "/" for s in HEADER_SOURCES)


class FetchError(Exception):
    """通信に失敗した、または応答が検査に通らない。"""


def http_get(url, sleep=time.sleep, opener=urllib.request.urlopen):
    """url に GET を送り、応答の本文（バイト列）を返す。決まりは先頭の注記のとおり。"""
    if not url.startswith(ALLOWED_URL_PREFIXES):
        raise FetchError("許可していない宛先には送らない: %s" % url)
    last = None
    for i in range(MAX_TRIES):
        if i:
            sleep(WAIT_SECONDS)
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "stick-chart-sealer"})
            with opener(req, timeout=TIMEOUT_SECONDS) as r:
                body = r.read(MAX_BYTES + 1)
            if len(body) > MAX_BYTES:
                raise FetchError("応答が大きすぎる: %s" % url)
            return body
        except (urllib.error.URLError, OSError) as e:
            last = e
    raise FetchError("%d 回試して失敗した: %s（%s）" % (MAX_TRIES, url, type(last).__name__))


# ---------------------------------------------------------------- drand


def parse_drand(body, now):
    """drand の応答（JSON）を検査し、記録の中身に入れる形にして返す。"""
    try:
        j = json.loads(body.decode("utf-8"))
        rnd, randomness, signature = j["round"], j["randomness"], j["signature"]
    except (UnicodeDecodeError, ValueError, KeyError, TypeError):
        raise FetchError("drand の応答の形が違う") from None
    if type(rnd) is not int or rnd < 1:
        raise FetchError("drand の round が正の整数でない")
    try:
        sig = bytes.fromhex(signature)
    except (TypeError, ValueError):
        raise FetchError("drand の signature が16進でない") from None
    if not isinstance(randomness, str) or hashlib.sha256(sig).hexdigest() != randomness:
        raise FetchError("drand の randomness が signature の sha256 と一致しない")
    t = ledger.drand_round_time(QUICKNET, rnd)
    if t < now - DRAND_MAX_AGE:
        raise FetchError("drand の回（%d、%s）が古すぎる（今 %s）" % (rnd, t.isoformat(),
                                                                 now.isoformat()))
    if t > now + DRAND_MAX_AHEAD:
        raise FetchError("drand の回（%d、%s）が今（%s）より先" % (rnd, t.isoformat(),
                                                              now.isoformat()))
    return {"chain_hash": QUICKNET, "round": rnd, "randomness": randomness,
            "signature": signature}


def latest_drand(now, fetch=http_get):
    """drand（quicknet）の最新の回。DRAND_URLS の順に試し、最初に検査に通ったものを返す。"""
    errors = []
    for url in DRAND_URLS:
        try:
            return parse_drand(fetch(url), now)
        except FetchError as e:
            errors.append(str(e))
    raise FetchError("drand の最新の回を取れなかった: " + " / ".join(errors))


# ---------------------------------------------------------------- Bitcoin のヘッダ


def block_hash_of(header):
    return hashlib.sha256(hashlib.sha256(header).digest()).digest()[::-1].hex()


def _hex(text, n, what):
    try:
        b = bytes.fromhex(text.strip())
    except ValueError:
        raise FetchError("%s が16進でない" % what) from None
    if len(b) != n:
        raise FetchError("%s が %d バイトでない" % (what, n))
    return b


def header_from_explorers(height, fetch=http_get):
    """HEADER_SOURCES のすべてから高さ height のヘッダを取り、一致したときだけ返す。"""
    if type(height) is not int or height < 0:
        raise FetchError("高さが 0 以上の整数でない")
    got = []
    for base in HEADER_SOURCES:
        bhash = _hex(fetch("%s/block-height/%d" % (base, height)).decode("ascii", "replace"),
                     32, "ブロックのハッシュ").hex()
        hdr = _hex(fetch("%s/block/%s/header" % (base, bhash)).decode("ascii", "replace"),
                   80, "ヘッダ")
        if block_hash_of(hdr) != bhash:
            raise FetchError("%s のヘッダのハッシュが、返されたブロックのハッシュと一致しない" % base)
        got.append(hdr)
    if any(h != got[0] for h in got):
        raise FetchError("高さ %d のヘッダが、取得先によって違う" % height)
    return got[0]


def header_from_bitcoin_cli(height, runner=subprocess.run, cli="bitcoin-cli"):
    """手元の Bitcoin のノード（bitcoin-cli）から高さ height のヘッダを取る。"""
    def run(*args):
        r = runner([cli] + list(args), capture_output=True, timeout=60)
        if r.returncode != 0:
            raise FetchError("bitcoin-cli %s が失敗した" % args[0])
        return r.stdout.decode("ascii", "replace").strip()
    bhash = _hex(run("getblockhash", str(height)), 32, "ブロックのハッシュ").hex()
    hdr = _hex(run("getblockheader", bhash, "false"), 80, "ヘッダ")
    if block_hash_of(hdr) != bhash:
        raise FetchError("ヘッダのハッシュが、ノードの返したブロックのハッシュと一致しない")
    return hdr
