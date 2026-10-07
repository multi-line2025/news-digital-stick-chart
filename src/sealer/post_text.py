#!/usr/bin/env python3
"""鎖の先頭のハッシュを X に投稿する文を作る。T-029。

投稿はしない（オーナーが自分で投稿する）。ネットワークは使わない。ファイルは書かない。
標準出力に投稿文だけを出し、文字数の数え方の内訳は標準エラーに出す。

使い方（プロジェクトのルートで）
    PYTHONDONTWRITEBYTECODE=1 python3 -B src/sealer/post_text.py [--seq N]
    （--seq を付けなければ最後の seq。付ければその seq の時点の文）
    終了コード 0: 投稿文を出した  1: 止めた（理由は標準エラー）  2: 引数の誤り

    PYTHONDONTWRITEBYTECODE=1 python3 -B src/sealer/post_text.py check-posts <投稿の一覧のファイル>
        [--account A] [--max-delay-hours H] [--max-delay-after-btc-hours H]
    第三者が、X の投稿の一覧を記録と照らす（T-029 差し戻し1回目の M-2、T-034）。既定の値は投稿の決まり
    （すべての記録を recorded_at から 24 時間以内。seq 1・2 は決まりの前の例外）。check_posts の注記。
    終了コード 0: すべて合う  1: 合わないものがある（どれが、なぜ、を標準出力に出す）  2: 引数の誤り

投稿はオーナーの明示の承認（reviews/ に原文で記録）のあとに限る（T-029 差し戻し1回目の M-1）。
承認は 2026-10-08 に記録された（reviews/T-029.md の最後の節）。投稿の決まり：封印の記録を
書き足すたびに、すべての記録を、recorded_at から 24 時間以内に投稿する（CLAUDE.md「公開前の検査」）。

何を出すか（docs/verify/x-post.md の 1章）
    sha256(sealed/ledger.jsonl seq 1-N)
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
    - どれかの seq の recorded_at が、その seq の最も早い確定時刻（ヘッダの時刻）+ 3 時間より後
      （check_recorded_vs_btc。T-034）
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
    - http:// か https:// で始まる URL は、X がリンクにすれば長さによらず 23、リンクにしなければ
      実際の長さ。どちらになるかを前提にしないため、max(実際の長さ, 23) と数える（T-029 差し戻し
      1回目の L-2）。URL の末尾の . , ; : ! ? ' " と、対応する ( の無い ) は URL に含めない。
    - 次の範囲の文字は 1、それ以外の文字は 2。
        U+0000–U+10FF、U+2000–U+200D、U+2010–U+201F、U+2032–U+2037
      日本語の文字（ひらがな・カタカナ・漢字・全角の記号）は 2。改行は 1。
    - 安全側の上乗せ：http(s):// の無い「ラベル.ラベル」の形（最後のラベルに英字を含むもの。
      例 ledger.jsonl）は、X がリンクにすると 23 と数えるかもしれないので、
      max(実際の長さ, 23) と数える。X が使うトップレベルドメインの一覧を、ネットワークを
      使わずに確かめられないため。絵文字の並びも、符号位置ごとに 2 と数える（X は並び全体で 2）。
      どちらも X の数え方より少なくならない方向にしか外さない。
    したがって、ここで 280 以下なら、X でも 280 以下である（X が URL をリンクにするかどうかに
    よらない）。

引用の選び方（choose_citation）
    英語の固定文と日本語の固定文のそれぞれで全文を作り、280 以下に収まるものだけを候補にする。
    両方が収まるときは、重みの小さい方（上限までの余裕が大きい方）を選ぶ。同じなら日本語。
    理由：引用はどちらも固定文で、どちらを使っても決定事項を満たす。余裕の大きい方を選べば、
    seq や高さの桁が増えても止まりにくい。選び方を数だけで決め、人が選べないようにする。
    どちらも収まらなければ止める。
"""

import argparse
import datetime
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
# 数字は [0-9] だけ（\d は Unicode の数字にも一致するため。T-029 差し戻し1回目の L-3）。
TIME_RE = re.compile(r"\A[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z\Z")
TEMPLATE_RE = re.compile(
    r"\Asha256\(sealed/ledger\.jsonl seq 1-(?P<seq>[1-9][0-9]*)\)\n"
    r"(?P<hash>[0-9a-f]{64})\n"
    r"(?P<time>[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z)"
    r" / BTC (?P<btc>[1-9][0-9]*|pending)\n"
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
    url（max(長さ, 23)）、bare（max(長さ, 23)。安全側の上乗せ）、w1（1 の文字）、w2（2 の文字）。"""
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
            w = max(len(seg), URL_WEIGHT)
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
    urls = [(s, w) for k, s, w in parts if k == "url"]
    bares = [(s, w) for k, s, w in parts if k == "bare"]
    lines = ["重み 1 の文字: %d 個 → %d" % (n1, n1),
             "重み 2 の文字: %d 個 → %d" % (n2, 2 * n2),
             "URL: %d 個 → %d（%s。max(実際の長さ, 23)）"
             % (len(urls), sum(w for _s, w in urls),
                ", ".join("%s は %d 文字" % (s, len(s)) for s, _w in urls))]
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


def head_facts(root, seq=None):
    """{"seq", "hash", "recorded_at", "height"}。height は Bitcoin で確定していなければ None。
    seq を渡さなければ最後の seq。渡せば、その seq（その時点の鎖の先頭）の文を作る。投稿の決まりは
    すべての記録の投稿を求めるので、24 時間のうちに二つ以上を書き足したときに、前の seq の文も要る。"""
    committed = require_committed(root)
    try:
        st = verify.State(root, None)
    except ledger.LedgerError as e:
        raise PostError("記録の検証に失敗した: %s" % e) from None
    if st.data != committed:
        raise PostError("作業ツリーの記録が HEAD の記録と違う")
    if st.records[-1]["seq"] != len(st.records):
        raise PostError("最後の seq が記録の件数と合わない")
    if seq is None:
        seq = len(st.records)
    if not (isinstance(seq, int) and 1 <= seq <= len(st.records)):
        raise PostError("seq %r の記録は無い（記録は %d 件）" % (seq, len(st.records)))
    last = st.records[seq - 1]
    bad = check_recorded_vs_btc(st.records, st.times)
    if bad:
        raise PostError("; ".join(bad))
    found = sorted((when, height) for s, height, when, _b in st.detail if s == seq)
    return {"seq": seq,
            "hash": ledger.prefix_digest(st.data, seq),
            "recorded_at": last["recorded_at"],
            "height": found[0][1] if found else None}


# ---------------------------------------------------------------- 文を作る


def body(facts):
    if not (isinstance(facts["seq"], int) and facts["seq"] >= 1):
        raise PostError("seq の形が違う")
    if not isinstance(facts["hash"], str) or not ledger.HEX64.match(facts["hash"]):
        raise PostError("ハッシュの形が違う")
    if not isinstance(facts["recorded_at"], str) or not TIME_RE.match(facts["recorded_at"]):
        raise PostError("時刻の形が違う")
    h = facts["height"]
    if h is not None and not (isinstance(h, int) and h >= 1):
        raise PostError("高さの形が違う")
    return ("sha256(sealed/ledger.jsonl seq 1-%d)\n%s\n%s / BTC %s\n"
            % (facts["seq"], facts["hash"], facts["recorded_at"],
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


def build(root, seq=None):
    facts = head_facts(root, seq)
    (lang, text, _w), cands = choose_citation(body(facts))
    check_publishable(text)
    return text, lang, cands, facts


# ---------------------------------------------------------------- 投稿の一覧を照らす（第三者）

# X の投稿の ID（snowflake）は、上位のビット（ID を 22 ビット右へずらした値）が、起点からのミリ秒の
# 時刻である。起点は 1288834974657（2010-11-04T01:42:54.657Z）。ネットワークを使わずに、ID から
# 投稿の時刻を計算できる（T-034）。
X_EPOCH_MS = 1288834974657
X_URL_RE = re.compile(r"\Ahttps://(?:x|twitter)\.com/([A-Za-z0-9_]{1,15})/status/([1-9][0-9]{0,19})"
                      r"(?:\?[^\s]*)?\Z")
TIME_TOKEN_RE = re.compile(r"\A[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z\Z")
SEQ_RE = re.compile(r"\A[1-9][0-9]*\Z")


def x_id_time(status_id):
    """X の投稿の ID から、投稿の時刻（UTC、ミリ秒まで）を計算する。"""
    status_id = int(status_id)
    if status_id < (1 << 22):
        raise PostError("投稿の ID が小さすぎる（時刻を含む形でない）")
    ms = (status_id >> 22) + X_EPOCH_MS
    return datetime.datetime.fromtimestamp(ms / 1000.0, datetime.timezone.utc).replace(
        microsecond=(ms % 1000) * 1000)


def parse_posts(text):
    """投稿の一覧を読む。1 行に 1 件で「<投稿の URL か時刻> <seq> <64 桁>」。# で始まる行と空行は飛ばす。

    投稿の URL（https://x.com/<アカウント>/status/<ID>）を書けば、時刻は ID から計算し、
    アカウントも照らせる。時刻（YYYY-MM-DDTHH:MM:SSZ、UTC）を書いた行は、アカウントを照らせない。
    返り値: [(行番号, 投稿の時刻, seq, ハッシュ, アカウント か None)]。形が違う行があれば PostError。
    """
    out = []
    for n, line in enumerate(text.split("\n"), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if (len(parts) != 3 or not SEQ_RE.match(parts[1]) or not ledger.HEX64.match(parts[2])):
            raise PostError("投稿の一覧の %d 行目の形が違う（<投稿の URL か時刻> <seq> "
                            "<64 桁の小文字の16進>）" % n)
        m = X_URL_RE.match(parts[0])
        if m:
            when, account = x_id_time(m.group(2)), m.group(1)
        elif TIME_TOKEN_RE.match(parts[0]):
            when, account = ledger.parse_time(parts[0]), None
        else:
            raise PostError("投稿の一覧の %d 行目の 1 つ目が、投稿の URL（https://x.com/<アカウント>/"
                            "status/<ID>）でも時刻（YYYY-MM-DDTHH:MM:SSZ）でもない" % n)
        out.append((n, when, int(parts[1]), parts[2], account))
    if not out:
        raise PostError("投稿の一覧が空")
    return out


def _hours(td):
    return td.total_seconds() / 3600.0


def _iso(t):
    return t.isoformat(timespec="milliseconds").replace("+00:00", "Z")


# 投稿の決まり（2026-10-08 オーナー決定。CLAUDE.md「公開前の検査」、reviews/T-029.md）。
# 封印の記録を書き足すたびに、すべての記録を、recorded_at から 24 時間以内に投稿する。
RULE_MAX_DELAY_HOURS = 24
# 決まりの前の例外（T-034。T-029 の監査 M-a）。決まりを決めた時点（コミット 80f7edd、
# 2026-10-07T17:57:02Z）で recorded_at から 24 時間を過ぎていたのは seq 1（2026-10-05T21:41:03Z）と
# seq 2（2026-10-06T09:58:57Z）だけである。seq 3（2026-10-07T13:45:11Z）と seq 4（13:45:22Z）は、
# 約 4 時間しかたっていなかったので、決まりの対象である。T-029 では例外を seq 1〜4 としていたが、
# それはリードが「seq 1〜4 は既に 24 時間を過ぎている」と伝えた事実の誤りによる。
# seq 1・2 は遅れの判定から外す（投稿に含まれていることは求める）。この値は定数で、引数では変えられない。
PRE_RULE_LAST_SEQ = 2
# recorded_at（申告）と、その seq の .ots の最も早い確定時刻（ヘッダの時刻）の比較の余裕（T-034。
# T-029 の監査 L-b）。記録は stamp の前に書くので、recorded_at は確定時刻より前のはずである。
# ヘッダの時刻は、実際に掘られた時刻より前（直近 11 ブロックの中央値を 1 秒でも超えればよいので、
# 1 時間ほど前になりうる）にも、後（ノードは 2 時間先までを受け入れる）にもなりうる。そのため 3 時間の
# 余裕を取り、recorded_at がヘッダの時刻 + 3 時間より後なら、記録の時刻の申告が合わないとして止める。
RECORDED_AT_HEADER_SLACK = datetime.timedelta(hours=3)


def check_recorded_vs_btc(records, times, slack=RECORDED_AT_HEADER_SLACK):
    """recorded_at が、その seq の最も早い確定時刻 + slack より後の seq の一覧（合わないもの）。"""
    bad = []
    for r in records:
        t = times.get(r["seq"])
        if t is not None and ledger.parse_time(r["recorded_at"]) > t + slack:
            bad.append("seq %d: recorded_at %s が、Bitcoin の確定時刻（ヘッダ）%s + %d 時間より後"
                       "（記録の時刻の申告が合わない）"
                       % (r["seq"], r["recorded_at"], _iso(t), slack.total_seconds() // 3600))
    return bad


def check_max_delay(value):
    """遅れの上限の値の形。有限で 0 以上の数だけを受け付ける（T-034。T-029 の監査 L-a）。"""
    try:
        v = float(value)
    except (TypeError, ValueError):
        raise PostError("遅れの上限が数でない") from None
    if v != v or v in (float("inf"), float("-inf")) or v < 0:
        raise PostError("遅れの上限は、有限で 0 以上の数でなければならない（nan・inf・負の数は使えない）")
    return int(v) if v.is_integer() else v


def check_posts(root, posts, max_delay_hours=RULE_MAX_DELAY_HOURS, max_delay_after_btc_hours=None,
                account=None, now=None, out=None):
    """投稿の一覧を、記録と投稿の決まりに照らす。T-029 の M-2、T-034。既定の値は投稿の決まり。

    投稿ごとに
      - account を渡したときは、URL で書いた投稿のアカウントがそれと同じこと（大文字小文字は区別しない）。
        時刻で書いた投稿は、アカウントを照らせないことを表示する
      - seq が記録の件数以下で、ハッシュが記録の先頭 seq 行の sha256 と同じこと
      - 投稿の時刻が、その seq の recorded_at（申告）より後であること
    seq k ごとに
      - 投稿された時刻 = seq k 以上の投稿（ハッシュの合うもの）のうち最も早い時刻。先頭 m 行の
        ハッシュは、k ≤ m のすべての行を固定するため
      - seq 1・2（PRE_RULE_LAST_SEQ まで）は、決まりの前の例外として遅れを判定しない。投稿されて
        いることは求める
      - seq 3 以降：投稿されていれば、遅れ（投稿 − recorded_at）が max_delay_hours 以下であること。
        投稿されていなければ、now − recorded_at が max_delay_hours 以下なら「保留」（まだ期限の前）、
        超えていれば合わない（T-029 の監査 L-c）
      - max_delay_after_btc_hours を渡したときは、投稿 − 最も早い確定時刻 もその値以下（決まりには無い）
    記録全体について
      - recorded_at が、その seq の最も早い確定時刻 + 3 時間より後でないこと（check_recorded_vs_btc）
    検証（verify.State）に通らなければ失敗。返り値: 合わなかった項目の一覧（空なら全部合う）。
    """
    w = (out or sys.stdout).write
    max_delay_hours = check_max_delay(max_delay_hours)
    if max_delay_after_btc_hours is not None:
        max_delay_after_btc_hours = check_max_delay(max_delay_after_btc_hours)
    now = now or datetime.datetime.now(datetime.timezone.utc)
    w("照らす値：遅れの上限 %s 時間（seq %d より後）、確定時刻からの上限 %s、照らすアカウント %s、"
      "今の時刻 %s\n"
      % (max_delay_hours, PRE_RULE_LAST_SEQ,
         "なし" if max_delay_after_btc_hours is None else "%s 時間" % max_delay_after_btc_hours,
         "@" + account if account else "なし", _iso(now)))
    if max_delay_hours != RULE_MAX_DELAY_HOURS:
        w("注意：遅れの上限が決まりの値（%d 時間）と違う。決まりと違う値で照らした\n" % RULE_MAX_DELAY_HOURS)
    try:
        st = verify.State(root, None)
    except ledger.LedgerError as e:
        return ["記録の検証に失敗した: %s" % e]
    n = len(st.records)
    bad = check_recorded_vs_btc(st.records, st.times)
    valid = []
    for lineno, when, seq, h, acc in posts:
        label = "一覧の %d 行目（seq %d、投稿 %s）" % (lineno, seq, _iso(when))
        if account is not None:
            if acc is None:
                w("%s: 時刻で書いた行なので、アカウントは照らしていない\n" % label)
            elif acc.lower() != account.lower():
                bad.append("%s: 投稿のアカウント @%s は、照らす対象の @%s でない" % (label, acc, account))
                continue
        if seq > n:
            bad.append("%s: 記録は %d 件しかない（末尾が切り詰められたか、別の系列）" % (label, n))
            continue
        got = ledger.prefix_digest(st.data, seq)
        if got != h:
            bad.append("%s: 投稿のハッシュが、記録の先頭 %d 行の sha256 %s と違う" % (label, seq, got))
            continue
        rec_at = ledger.parse_time(st.records[seq - 1]["recorded_at"])
        if when < rec_at:
            bad.append("%s: 投稿の時刻が recorded_at より前（記録の時刻の申告と合わない）" % label)
            continue
        w("%s: ハッシュは合う\n" % label)
        valid.append((when, seq))
    pending = []
    for r in st.records:
        k = r["seq"]
        rec_at = ledger.parse_time(r["recorded_at"])
        covering = [when for when, seq in valid if seq >= k]
        btc = st.times.get(k)
        if covering:
            first = min(covering)
            d = _hours(first - rec_at)
            msg = "seq %d: 最初に投稿された時刻 %s、遅れ %.2f 時間" % (k, _iso(first), d)
            if btc:
                msg += "、確定時刻（ヘッダ）からは %.2f 時間" % _hours(first - btc)
            if k <= PRE_RULE_LAST_SEQ:
                w(msg + "。決まりの前の例外なので、遅れは判定しない\n")
            elif d > max_delay_hours:
                bad.append(msg + "。上限 %s 時間を超える" % max_delay_hours)
            else:
                w(msg + "。上限 %s 時間の中\n" % max_delay_hours)
            if (max_delay_after_btc_hours is not None and btc
                    and _hours(first - btc) > max_delay_after_btc_hours):
                bad.append("seq %d: 確定時刻からの遅れ %.2f 時間が上限 %s 時間を超える"
                           % (k, _hours(first - btc), max_delay_after_btc_hours))
        elif k > PRE_RULE_LAST_SEQ and _hours(now - rec_at) <= max_delay_hours:
            pending.append(k)
            w("seq %d: 保留。まだ投稿が無いが、recorded_at から %.2f 時間で、期限（%s 時間）の前\n"
              % (k, _hours(now - rec_at), max_delay_hours))
        else:
            bad.append("seq %d: 投稿が無い（この seq 以上の投稿でハッシュの合うものが一覧に無い）%s"
                       % (k, "" if k <= PRE_RULE_LAST_SEQ else
                          "。recorded_at から %.2f 時間で、期限を過ぎた" % _hours(now - rec_at)))
    w("記録は %d 件。保留の seq: %s\n" % (n, ", ".join(map(str, pending)) or "なし"))
    return bad


def main_check_posts(argv):
    p = argparse.ArgumentParser(prog="post_text.py check-posts",
                                description="X の投稿の一覧を記録と照らす（第三者向け）。既定の値は投稿の決まり")
    p.add_argument("posts", help="投稿の一覧のファイル（1 行に「<投稿の URL か時刻> <seq> <64 桁>」）")
    p.add_argument("--root", default=os.getcwd(), help="リポジトリのルート（既定は今の場所）")
    p.add_argument("--account", default=None,
                   help="照らす対象の X のアカウント（@ を除く）。docs/verify/x-post.md に固定したもの")
    p.add_argument("--max-delay-hours", default=str(RULE_MAX_DELAY_HOURS),
                   help="遅れの上限（既定 24。決まりの値。有限で 0 以上）")
    p.add_argument("--max-delay-after-btc-hours", default=None,
                   help="確定時刻からの遅れの上限（既定は判定しない。決まりには無い）")
    a = p.parse_args(argv)
    try:
        with open(a.posts, encoding="utf-8") as f:
            posts = parse_posts(f.read())
        bad = check_posts(os.path.abspath(a.root), posts, a.max_delay_hours,
                          a.max_delay_after_btc_hours, a.account)
    except (OSError, UnicodeDecodeError) as e:
        print("合わない: 投稿の一覧を読めない: %s" % type(e).__name__)
        return 1
    except PostError as e:
        print("合わない: %s" % e)
        return 1
    for b in bad:
        print("合わない: %s" % b)
    if bad:
        return 1
    print("投稿の一覧と記録は合う")
    return 0


def main(argv=None):
    argv = sys.argv[1:] if argv is None else list(argv)
    if argv[:1] == ["check-posts"]:
        return main_check_posts(argv[1:])
    p = argparse.ArgumentParser(description="鎖の先頭のハッシュを X に投稿する文を作る（投稿はしない）")
    p.add_argument("--root", default=PROJECT, help="プロジェクトのルート（既定はこのファイルの場所から）")
    p.add_argument("--seq", type=int, default=None,
                   help="この seq の時点の文を作る（既定は最後の seq）")
    a = p.parse_args(argv)
    root = os.path.abspath(a.root)
    try:
        text, lang, cands, facts = build(root, a.seq)
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
