#!/usr/bin/env python3
"""鎖の先頭のハッシュを X に投稿する文を作る。T-029。

投稿はしない（オーナーが自分で投稿する）。ネットワークは使わない。ファイルは書かない。
標準出力に投稿文だけを出し、文字数の数え方の内訳は標準エラーに出す。

使い方（プロジェクトのルートで）
    PYTHONDONTWRITEBYTECODE=1 python3 -B src/sealer/post_text.py
    終了コード 0: 投稿文を出した  1: 止めた（理由は標準エラー）  2: 引数の誤り

何を出すか（docs/verify/x-post.md の 1章）
    seq N: sha256(sealed/ledger.jsonl lines 1-N)
    <記録のファイルの先頭 N 行（各行の末尾の改行を含む）のバイト列の sha256>
    <seq N の recorded_at（申告）> / BTC <seq N 自身の .ots が確定した Bitcoin のブロックの高さ | pending>
    <GDELT の引用の固定文（英語か日本語）>

    N は記録の最後の seq。ハッシュは ledger.prefix_digest(data, N)。記録のファイルが N 行の
    ときは、ファイル全体の sha256（shasum -a 256 sealed/ledger.jsonl）と同じで、
    seq N の .ots の対象（File sha256 hash）とも同じである。prev_hash の鎖と違い、最後の行も
    含むので、最後の行の書き換えと末尾の切り詰めも、この値との食い違いで分かる。
    記録の kind・note・targets は出さない（判定期間の前に投稿してよいのは、封印の証明
    （ハッシュと時刻）だけ。CLAUDE.md「公開前の検査」）。

止める条件（どれか一つでも当たれば、投稿文を出さずに終了コード 1）
    - verify.State の検査（鎖・各 seq の .ots・ヘッダの照合）に通らない
    - sealed/ にコミットしていない変更がある（投稿したハッシュを、公開されたリポジトリの
      記録と照らせなくなるため）。Git のリポジトリでない場合も止める
    - 文が決まった形（TEMPLATE_RE）に合わない
    - 引用の固定文が、CITATION_EN か CITATION_JA と一字一句同じ行として最後に無い
    - privacy_scan.find_in_bytes が、許可していないメールアドレスの形を見つけた
    - プロジェクトの外の情報：絶対パス・ホームの ~/・バックスラッシュ・UUID（VolumeUUID など）・
      IPv4 の形・この機械のユーザー名・ホーム・ホスト名・プロジェクトの絶対パス
    - 数えた重み（weighted_length）が 280 を超える

文字数の数え方（weighted_length。X の twitter-text v3 の規則に、安全側の上乗せを加えたもの）
    - 文字列を NFC に正規化してから数える（X と同じ）。
    - http:// か https:// で始まる URL は、長さによらず 23。URL の末尾の . , ; : ! ? ' " と、
      対応する ( の無い ) は URL に含めない。
    - 次の範囲の文字は 1、それ以外の文字は 2。
        U+0000–U+10FF、U+2000–U+200D、U+2010–U+201F、U+2032–U+2037
      日本語の文字（ひらがな・カタカナ・漢字・全角の記号）は 2。改行は 1。
    - 安全側の上乗せ：http(s):// の無い「ラベル.ラベル」の形（最後のラベルに英字を含むもの。
      例 ledger.jsonl）は、X がリンクにすると 23 と数えるかもしれないので、
      max(実際の長さ, 23) と数える。X が使うトップレベルドメインの一覧を、ネットワークを
      使わずに確かめられないため。絵文字の並びも、符号位置ごとに 2 と数える（X は並び全体で 2）。
      どちらも X の数え方より少なくならない方向にしか外さない。
    したがって、ここで 280 以下なら、X でも 280 以下である。

引用の選び方（choose_citation）
    英語の固定文と日本語の固定文のそれぞれで全文を作り、280 以下に収まるものだけを候補にする。
    両方が収まるときは、重みの小さい方（上限までの余裕が大きい方）を選ぶ。同じなら日本語。
    理由：引用はどちらも固定文で、どちらを使っても決定事項を満たす。余裕の大きい方を選べば、
    seq や高さの桁が増えても止まりにくい。選び方を数だけで決め、人が選べないようにする。
    どちらも収まらなければ止める。
"""

import argparse
import getpass
import os
import re
import socket
import subprocess
import sys
import unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(PROJECT, "src", "collector"))

import ledger  # noqa: E402
import privacy_scan  # noqa: E402  （収集係の検査器を読むだけ。書き換えない）
import verify  # noqa: E402

MAX_WEIGHT = 280
URL_WEIGHT = 23

# CLAUDE.md「データ源」の引用の固定文。tests/sealer/test_post_text.py が CLAUDE.md の行と
# 一字一句同じであることを確かめる。
CITATION_EN = ("Data: The GDELT Project (https://www.gdeltproject.org/). This project is not "
               "affiliated with or endorsed by the GDELT Project.")
CITATION_JA = ("データ出典：GDELT Project（https://www.gdeltproject.org/）。本プロジェクトは "
               "GDELT Project と提携・承認の関係にありません。")
CITATIONS = (("ja", CITATION_JA), ("en", CITATION_EN))   # 重みが同じときは前の方
GDELT_URL = "https://www.gdeltproject.org/"

LEDGER_REL = verify.LEDGER_REL

# 投稿文の形。引用以外の部分は、数字・16進・決まった語だけからなる。
TEMPLATE_RE = re.compile(
    r"\Aseq (?P<seq>[1-9][0-9]*): sha256\(sealed/ledger\.jsonl lines 1-(?P=seq)\)\n"
    r"(?P<hash>[0-9a-f]{64})\n"
    r"(?P<time>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z) / BTC (?P<btc>[1-9][0-9]*|pending)\n"
    r"(?P<citation>[^\n]+)\Z")

_WEIGHT1 = ((0x0000, 0x10FF), (0x2000, 0x200D), (0x2010, 0x201F), (0x2032, 0x2037))
_SCHEME_URL = re.compile(r"https?://[A-Za-z0-9\-._~:/?#\[\]@!$&'()*+,;=%]+", re.IGNORECASE)
_URL_TRAIL = ".,;:!?'\""
_BARE_DOMAIN = re.compile(r"(?<![A-Za-z0-9@_.\-])[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)+")

# プロジェクトの外の情報の形
_ABS_PATH = re.compile(r"(?<![A-Za-z0-9._~:/\-])/[A-Za-z0-9._~\-]")
_WIN_PATH = re.compile(r"(?<![A-Za-z])[A-Za-z]:[\\/]")
_UUID = re.compile(r"[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}")
_IPV4 = re.compile(r"(?<![0-9.])(?:[0-9]{1,3}\.){3}[0-9]{1,3}(?![0-9.])")


class PostError(Exception):
    """投稿文を出さずに止める。"""


# ---------------------------------------------------------------- 文字数


def char_weight(ch):
    cp = ord(ch)
    for lo, hi in _WEIGHT1:
        if lo <= cp <= hi:
            return 1
    return 2


def _trim_url(url):
    while url:
        if url[-1] in _URL_TRAIL:
            url = url[:-1]
        elif url[-1] == ")" and url.count(")") > url.count("("):
            url = url[:-1]
        else:
            break
    return url


def weigh(text):
    """(重みの合計, 内訳の一覧)。内訳は (種類, 文字列, 重み)。種類は
    url（23）、bare（max(長さ, 23)。安全側の上乗せ）、w1（1 の文字）、w2（2 の文字）。"""
    text = unicodedata.normalize("NFC", text)
    parts = []
    spans = []
    for m in _SCHEME_URL.finditer(text):
        url = _trim_url(m.group(0))
        spans.append((m.start(), m.start() + len(url), "url"))
    masked = list(text)
    for s, e, _k in spans:
        for i in range(s, e):
            masked[i] = " "
    masked = "".join(masked)
    for m in _BARE_DOMAIN.finditer(masked):
        labels = m.group(0).split(".")
        if re.search(r"[A-Za-z]", labels[-1]) and all(labels):
            spans.append((m.start(), m.end(), "bare"))
    spans.sort()
    total = 0
    i = 0
    for s, e, kind in spans + [(len(text), len(text), None)]:
        for ch in text[i:s]:
            w = char_weight(ch)
            parts.append(("w%d" % w, ch, w))
            total += w
        if kind is not None:
            seg = text[s:e]
            w = URL_WEIGHT if kind == "url" else max(len(seg), URL_WEIGHT)
            parts.append((kind, seg, w))
            total += w
        i = e
    return total, parts


def weighted_length(text):
    return weigh(text)[0]


def summary(text):
    """数え方の内訳を、人が読める行にする。"""
    total, parts = weigh(text)
    n1 = sum(1 for k, _s, _w in parts if k == "w1")
    n2 = sum(1 for k, _s, _w in parts if k == "w2")
    urls = [s for k, s, _w in parts if k == "url"]
    bares = [(s, w) for k, s, w in parts if k == "bare"]
    lines = ["重み 1 の文字: %d 個 → %d" % (n1, n1),
             "重み 2 の文字: %d 個 → %d" % (n2, 2 * n2),
             "URL: %d 個 × %d → %d（%s）" % (len(urls), URL_WEIGHT, URL_WEIGHT * len(urls),
                                         ", ".join(urls))]
    for s, w in bares:
        lines.append("安全側の上乗せ: %s（実際は %d 文字）→ %d" % (s, len(s), w))
    lines.append("合計: %d / %d（残り %d）" % (total, MAX_WEIGHT, MAX_WEIGHT - total))
    return lines


# ---------------------------------------------------------------- 外の情報の検査


def local_identifiers():
    """この機械に固有の文字列（ユーザー名・ホーム・ホスト名・プロジェクトの絶対パス）。
    ホスト名は socket.gethostname() で、ネットワークは使わない。3 文字未満のものは使わない。"""
    out = set()
    for v in (os.environ.get("USER"), os.environ.get("LOGNAME"), os.environ.get("HOME"),
              os.path.expanduser("~"), PROJECT):
        if v:
            out.add(v)
    try:
        out.add(getpass.getuser())
    except Exception:  # noqa: BLE001  取れなければ使わない
        pass
    try:
        host = socket.gethostname()
        out.add(host)
        out.add(host.split(".")[0])
    except OSError:
        pass
    return sorted(v for v in out if len(v) >= 3)


def check_publishable(text, identifiers=None):
    """公開してよいかを確かめる。だめなら PostError（一致した文字列はメッセージに入れない）。"""
    data = text.encode("utf-8")
    hits = privacy_scan.find_in_bytes(data)
    if hits:
        raise PostError("許可していないメールアドレスの形がある（%d か所。privacy_scan と同じ検査）"
                        % sum(hits.values()))
    if _ABS_PATH.search(text) or _WIN_PATH.search(text) or "~/" in text or "\\" in text:
        raise PostError("絶対パスの形がある")
    if _UUID.search(text):
        raise PostError("UUID の形（VolumeUUID など）がある")
    if _IPV4.search(text):
        raise PostError("IPv4 アドレスの形がある")
    low = text.lower()
    for ident in local_identifiers() if identifiers is None else identifiers:
        if ident.lower() in low:
            raise PostError("この機械に固有の文字列（ユーザー名・ホーム・ホスト名・プロジェクトの"
                            "場所のどれか）がある")
    urls = [_trim_url(m.group(0)) for m in _SCHEME_URL.finditer(text)]
    if urls != [GDELT_URL]:
        raise PostError("URL は GDELT の引用の 1 つだけでなければならない（%d 個ある）" % len(urls))
    m = TEMPLATE_RE.match(text)
    if not m:
        raise PostError("投稿文が決まった形に合わない")
    if m.group("citation") not in (CITATION_EN, CITATION_JA):
        raise PostError("最後の行が、GDELT の引用の固定文と一字一句同じでない")
    w = weighted_length(text)
    if w > MAX_WEIGHT:
        raise PostError("重みが %d で、上限 %d を超える" % (w, MAX_WEIGHT))
    return w


# ---------------------------------------------------------------- 記録を読む


def require_committed(root):
    """sealed/ にコミットしていない変更（追跡していないファイルを含む）が無いこと。"""
    r = subprocess.run(["git", "-C", root, "status", "--porcelain", "--untracked-files=all",
                        "--", "sealed/"], capture_output=True)
    if r.returncode != 0:
        raise PostError("git status が失敗した（Git のリポジトリでない？）")
    if r.stdout.strip():
        raise PostError("sealed/ にコミットしていない変更がある。コミットしてから作る")
    head = subprocess.run(["git", "-C", root, "show", "HEAD:" + LEDGER_REL], capture_output=True)
    if head.returncode != 0:
        raise PostError("HEAD に %s が無い" % LEDGER_REL)
    return head.stdout


def head_facts(root):
    """{"seq", "hash", "recorded_at", "height"}。height は Bitcoin で確定していなければ None。"""
    committed = require_committed(root)
    try:
        st = verify.State(root, None)
    except ledger.LedgerError as e:
        raise PostError("記録の検証に失敗した: %s" % e) from None
    if st.data != committed:
        raise PostError("作業ツリーの記録が HEAD の記録と違う")
    last = st.records[-1]
    seq = last["seq"]
    if seq != len(st.records):
        raise PostError("最後の seq が記録の件数と合わない")
    found = sorted((when, height) for s, height, when, _b in st.detail if s == seq)
    return {"seq": seq,
            "hash": ledger.prefix_digest(st.data, seq),
            "recorded_at": last["recorded_at"],
            "height": found[0][1] if found else None}


# ---------------------------------------------------------------- 文を作る


def body(facts):
    if not (isinstance(facts["seq"], int) and facts["seq"] >= 1):
        raise PostError("seq の形が違う")
    if not ledger.HEX64.match(facts["hash"]):
        raise PostError("ハッシュの形が違う")
    if not ledger.TIME_RE.match(facts["recorded_at"]):
        raise PostError("時刻の形が違う")
    h = facts["height"]
    if h is not None and not (isinstance(h, int) and h >= 1):
        raise PostError("高さの形が違う")
    return ("seq %d: sha256(sealed/ledger.jsonl lines 1-%d)\n%s\n%s / BTC %s\n"
            % (facts["seq"], facts["seq"], facts["hash"], facts["recorded_at"],
               "pending" if h is None else str(h)))


def choose_citation(text_body):
    """[(言語, 全文, 重み)] の候補から、収まるもののうち重みの小さい方を返す（同じなら日本語）。"""
    cands = [(lang, text_body + cit, weighted_length(text_body + cit)) for lang, cit in CITATIONS]
    fits = [c for c in cands if c[2] <= MAX_WEIGHT]
    if not fits:
        raise PostError("どちらの引用でも上限 %d を超える（%s）"
                        % (MAX_WEIGHT, ", ".join("%s %d" % (l, w) for l, _t, w in cands)))
    best = min(fits, key=lambda c: c[2])   # min は同じ値なら先のもの（日本語）を返す
    return best, cands


def build(root):
    facts = head_facts(root)
    (lang, text, _w), cands = choose_citation(body(facts))
    check_publishable(text)
    return text, lang, cands, facts


def main(argv=None):
    p = argparse.ArgumentParser(description="鎖の先頭のハッシュを X に投稿する文を作る（投稿はしない）")
    p.add_argument("--root", default=PROJECT, help="プロジェクトのルート（既定はこのファイルの場所から）")
    a = p.parse_args(argv)
    root = os.path.abspath(a.root)
    try:
        text, lang, cands, facts = build(root)
    except PostError as e:
        sys.stderr.write("post_text: 止めた: %s\n" % e)
        return 1
    err = sys.stderr
    err.write("post_text: seq %d、Bitcoin %s\n"
              % (facts["seq"], "未確定（pending）" if facts["height"] is None
                 else "高さ %d で確定" % facts["height"]))
    for l, _t, w in cands:
        err.write("post_text: 引用 %s の全文の重み %d%s\n"
                  % (l, w, "（上限を超える）" if w > MAX_WEIGHT else ""))
    err.write("post_text: 選んだ引用: %s（収まるもののうち重みの小さい方。同じなら日本語）\n" % lang)
    for line in summary(text):
        err.write("post_text: %s\n" % line)
    sys.stdout.write(text + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
