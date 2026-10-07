#!/usr/bin/env python3
"""GKG のテーマの区分表（名前と説明の一覧）を取得し、件数の欄を捨てて保存する（T-018・T-021。コードだけ）。

データ出典
    Data: The GDELT Project (https://www.gdeltproject.org/). This project is not
    affiliated with or endorsed by the GDELT Project.
    データ出典：GDELT Project（https://www.gdeltproject.org/）。本プロジェクトは
    GDELT Project と提携・承認の関係にありません。

まだ一度も取得していない。区分表の取得は、統計係の除外の規則の封印のあとの別のタスクで行う
（オーナーの決定。reviews/T-016.md の 2026-10-08 の発言：「件数の欄を捨てる条件で、区分表を
1回取得してよい」。取得元は同じサーバーの /api/v2/guides/）。

------------------------------------------------------------------------
0. 取得の前の関門（require_exclusion_rules_sealed。T-021）
------------------------------------------------------------------------
    区分表は、統計係の除外の規則を封印したあとでだけ取得する（docs/stats/tags-naive.md 5章の
    順番1：除外の規則を区分表の取得より前に封印する）。run() は、通信の前に最初にこの関門を
    呼ぶ。関門が確かめること：
      - 除外の規則の封印の記録の種類（EXCLUSION_RULE_KIND）が決まっている。**T-021 の時点では
        封印係の側でまだ決まっていない（None）。そのため、今は関門が必ず止まり、区分表は
        取得できない。** kind が決まったら、その名前をここに書いてコミットする（別のタスク）。
      - その kind が、封印の記録の種類の許可リスト（src/sealer/ledger.py の ALLOWED_KINDS）に
        入っている。
      - 封印の記録（sealed/ledger.jsonl）の鎖と、すべての seq の .ots が検証に通る
        （ledger._load_for_gate。プロジェクトのルートは ledger.PROJECT_ROOT に固定）。
      - その kind の記録が1件以上ある。
      - run() に渡した root が、関門が読んだプロジェクトと同じ。
    確かめないこと：記録の中身（どの規則を封印したか）の照合。それは封印係が kind と一緒に
    決める照合の仕組みで行う。

------------------------------------------------------------------------
0.1 コードの関門と「1回だけ」の記録（T-021 の差し戻し1回目 中3）
------------------------------------------------------------------------
    順番：コードの関門を先に、除外の規則の関門をそのあとに通す（差し戻し2回目 軽-2。関門が
    読み込む ledger.py を含めて、固定したコードで動くことを先に確かめる）。
    - コードの関門（_code_gate）：src/collector と src/sealer に未コミットの変更・無視される
      ファイル・skip-worktree の印が無く（codegate.check_clean）、動いている themes.py と privacy_scan.py
      が HEAD にコミットした中身と同じであること。区分表の取得は、このファイル（2.1 の名前の欄
      だけを残す規則を含む）をコミットしたあとの、その code_sha256 のコードでだけ行う。
    - 1回だけの取得（オーナーの承認「1回取得してよい」）：通信の前に、マニフェスト
      data/manifest/gdelt-themes.jsonl に試行の行（kind が attempt。code_sha256・source_url・
      attempted_at・除外の規則の封印の記録の seq と sha256）を書く。作業ツリーにマニフェストの
      ファイルがあるか（空にしたファイルを含む）、HEAD にマニフェストがあれば（前の試行が成功
      しても失敗しても）、通信せずに止まる（差し戻し2回目 軽-1）。失敗した取得も、試行の行として記録に残る。
      取得に成功すれば、結果の行（kind が result）を書く。
      限界：コミットする前にマニフェストのファイルごと消すと（rm など）、HEAD にも無いので
      見つけられない。試行の行は、取得のあとすぐにコミットする。
    - 結果の行と試行の行には、除外の規則の関門が返した記録の seq と sha256
      （exclusion_rule_seq・exclusion_rule_record_sha256）を書く（差し戻し2回目 中-B）。

------------------------------------------------------------------------
1. 取得元と通信
------------------------------------------------------------------------
    - https://data.gdeltproject.org/api/v2/guides/<名前> の形で、名前が ALLOWED_GUIDE_FILES
      （LOOKUP-GKGTHEMES.TXT の1つだけ。全テーマの区分表。オーナーの承認の範囲）に入るものだけを
      許す（validate_doc_url）。大文字と小文字も同じでなければならない。ほかの名前（言語・国・
      画像のタグなどの一覧）、ほかのパス（/documentation/ を含む）、ほかのホスト
      （gdeltcloud.com を含む）、http、ポート・クエリ・フラグメント・「..」・「%」は拒む。
    - 要求は1回だけ（MAX_ATTEMPTS = 1。再試行しない）。リダイレクトとプロキシは使わない。
      待ちの上限は REQUEST_TIMEOUT_SECONDS（60秒）、全体の上限 TOTAL_DEADLINE_SECONDS（300秒）、
      応答の長さの上限 MAX_BYTES（50 MB）。1回だけなので、速度の制限に当たる量ではない。
    - 応答はメモリの上だけで扱い、元の応答をそのままディスクに書かない。応答全体の sha256 も
      長さも記録しない（件数の欄を含む元の中身に結びつくため）。

------------------------------------------------------------------------
2. 欄の見出しの確認と、件数の欄を捨てる規則（classify_columns）
------------------------------------------------------------------------
    件数・報道量・頻度の欄は、2020-12-15 以降を含む全期間の情報になりうるので、ディスクに書く
    前に捨てる。規則（見出しの名前と値だけで機械的に決まる）：
      - 見出しの行が無い形（1行目の値に数字だけの欄がある、など）は、どれが件数の欄かを見出しで
        確かめられないので、何も書かずに止まる（ThemesError）。
      - 見出しが KEEP_HEADER_RE（名前・説明・種類など）に当たらない欄、DROP_HEADER_RE（件数・
        頻度など）に当たる欄は、すべて捨てる。知らない欄は捨てる側に倒す。
      - テーマの名前の欄（見出しが NAME_HEADER_RE に当たる欄）は、すべての値が THEME_NAME_RE
        （英大文字で始まり、英大文字・数字・下線だけ）に完全に合わなければならない。合わない値が
        1つでもあれば、何も書かずに止まる（「QQ_A (1234)」のように名前に件数を足した形を
        書かないため）。名前の欄が1つも無い場合も止まる。
      - 名前以外の残す欄（説明・種類など）は、数字（半角・全角）を含む値が1つでもあれば、
        欄ごと捨てる（「Seen in 1,234,567 articles」「12.3k」「1 234」のような件数を書かない
        ため）。数字の判定（has_numeric）は、Unicode で数を表す文字すべて（str.isnumeric。
        半角・全角・アラビア文字などの十進の数字、上付き・下付きの数字（² ₃）、丸付きの数字、
        分数（½）、ローマ数字（Ⅻ）、漢数字（一・万）など）を数字とみなす（T-021。T-018 の監査
        軽3）。止まらずに欄ごと捨てる理由：取得は1回だけなので、止めると名前の欄まで失う。
        名前の欄が残れば区分表の目的（除外の規則をテーマの名前に当てる）は果たせ、捨てた欄の
        見出しはマニフェストの dropped_columns に残る。
      - 見出しの行の判定も同じ数字の判定を使う。見出しの値が、数字と区切り（, . 空白 + - _ '）
        だけでできていれば（「１２３」「²³」を含む）、見出しの無い形とみなして止まる。
      - 捨てた欄の見出しの名前はマニフェストの dropped_columns に出す。ただし、見出しに数字が
        あれば、名前の代わりに欄の位置（column_A、column_B …。英字だけ）を出す（見出しに件数が
        紛れた形「Count (1,234,567)」を書かないため）。
      - xlsx のシート名：シートが複数あるときは、シート名を sheet の欄の値として書く。シート名に
        数字があれば、すべてのシートの名前の代わりに位置（sheet_A、sheet_B …）を書き、
        マニフェストの sheet_names_replaced を true にする（「Themes (12,345)」を書かないため）。
        シートが1つのときは、シート名を書かない。
      - 限界：数字を使わずに書いた量（「one million」など）は見分けられない。
    保存するのは、残した欄の見出しと値だけ。

------------------------------------------------------------------------
2.1 見出しの無い「名前・件数」の2欄の表（T-021 の差し戻し1回目。リードの判断、監査の条件）
------------------------------------------------------------------------
    1行目の値に数字だけの値がある（見出しの無い形）とき、次の条件をすべて満たす場合に限り、
    名前の欄だけを残す（headerless_name_count）。満たさなければ、これまでどおり止まる。
      (1) どの行も、欄がちょうど2つ。
      (2) 一方の欄の値がすべて THEME_NAME_RE に合い、もう一方の欄の値がすべて ASCII の数字
          （0〜9）だけ。判定は欄の位置ではなく値の形で行う。
      (3) (2) に合う割り当て（どちらが名前の欄か）が、ちょうど1つ。両方の割り当てが合う場合と、
          どちらも合わない場合は止まる。
      (4) 残すのは名前の欄だけで、見出しは THEME とする。件数の欄はメモリの上で捨て、見出しの
          代わりに欄の位置（column_A か column_B）をマニフェストの dropped_columns に書く。
          行は並べ替えてから書く（元の並び＝件数の順を残さないため）。マニフェストの
          headerless を true にする。
    限界：区分表は取得した時点の全テーマの一覧なので、2020-12-15 以降に生まれたテーマの名前も
    入る。名前があることは、そのテーマが後ろの期間に使われたことを示しうる。タグの一覧の規則は
    手法を作る期間のデータで存在を確かめるので、名前だけでは一覧に入らない。

------------------------------------------------------------------------
3. 読める形
------------------------------------------------------------------------
    タブ区切りか、カンマ区切りの文字（.txt・.tsv・.csv。UTF-8）と、.xlsx（zip の中の XML を
    標準ライブラリで読む。最初の行を見出しとし、シートが複数あれば sheet の欄を足す）。
    それ以外の形は止まる。

------------------------------------------------------------------------
4. 保存とマニフェスト
------------------------------------------------------------------------
    本体：<home>/Desktop/news-stick-data/gdelt-themes-<UTC 時刻>.tsv（Git の外。見出し＋行。
    行は値の順に並べ替える。改行は LF、UTF-8）。O_CREAT | O_EXCL | O_NOFOLLOW で書く。
    マニフェスト：<root>/data/manifest/gdelt-themes.jsonl に1行追記（file_name、sha256、rows、
    kept_columns、dropped_columns、fetched_at、source_url、code_path、code_sha256、
    store_location）。
    書く前に privacy_scan.find_in_bytes で調べ、メールアドレスの形があれば書かずに止まる。

外部のライブラリは使わない（Python 3 の標準ライブラリだけ）。
"""

import csv
import datetime
import hashlib
import importlib.util
import io
import json
import os
import re
import socket
import stat
import sys
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))

ALLOWED_HOST = "data.gdeltproject.org"
# 1章：許す名前（オーナーの承認の範囲：全テーマの区分表だけ）
ALLOWED_GUIDE_FILES = ("LOOKUP-GKGTHEMES.TXT",)
THEMES_URL = "https://data.gdeltproject.org/api/v2/guides/" + ALLOWED_GUIDE_FILES[0]
_DOC_URL_RE = re.compile(
    r"\Ahttps://data\.gdeltproject\.org/api/v2/guides/([A-Za-z0-9][A-Za-z0-9._-]{0,127})\Z")
# 0章：除外の規則の封印の記録の種類。封印係が決める。T-021 の時点では未定（関門が必ず止まる）
EXCLUSION_RULE_KIND = None
MAX_ATTEMPTS = 1
REQUEST_TIMEOUT_SECONDS = 60
TOTAL_DEADLINE_SECONDS = 300
MAX_BYTES = 50 * 1024 * 1024
MAX_XLSX_PART_BYTES = 200 * 1024 * 1024
USER_AGENT = "news-digital-stick-chart-collector/0"

KEEP_HEADER_RE = re.compile(
    r"\A(?:theme|themes|name|names|category|categories|label|description|desc|definition|"
    r"meaning|type|category ?type|kind|tag|theme ?name|category ?name|notes?)\Z", re.I)
DROP_HEADER_RE = re.compile(
    r"count|freq|volume|number|\bnum\b|total|articles|\bdocs?\b|documents|occurr|mentions|"
    r"hits|popular|\bn\b|cnt|rank|percent|share|ratio", re.I)
NAME_HEADER_RE = re.compile(
    r"\A(?:theme|themes|name|names|theme ?name|category ?name|tag)\Z", re.I)
ASCII_DIGITS_RE = re.compile(r"\A[0-9]+\Z")
NUMBER_SEPARATORS = frozenset(",. +-_'\u00a0\u202f")
THEME_NAME_RE = re.compile(r"\A[A-Z][A-Z0-9_]{0,159}\Z")

STORE_PARTS = ("Desktop", "news-stick-data")
STORE_LOCATION_NAME = "~/" + "/".join(STORE_PARTS)
MANIFEST_DIR_PARTS = ("data", "manifest")
MANIFEST_NAME = "gdelt-themes.jsonl"
CODE_REL = "src/collector/themes.py"


class ThemesError(Exception):
    """止まった。文には、表の値を入れない（見出しの名前だけ）。"""


class ExclusionRulesNotSealed(ThemesError):
    """0章の関門で止まった。通信も書き込みもしていない。"""


def has_numeric(text):
    """2章：数を表す文字（Unicode の Numeric_Type を持つ文字。str.isnumeric）が1つでもあれば True。"""
    return any(ch.isnumeric() for ch in text)


def looks_like_number(text):
    """2章：数字と区切りだけでできた値（見出しの無い形の判定）。"""
    t = text.strip()
    return bool(t) and has_numeric(t) and all(ch.isnumeric() or ch in NUMBER_SEPARATORS
                                              for ch in t)


def _letters(i):
    """0 → A、25 → Z、26 → AA。位置の名前（数字を使わない）。"""
    out = ""
    i += 1
    while i:
        i, r = divmod(i - 1, 26)
        out = chr(65 + r) + out
    return out


def _load_privacy_scan():
    spec = importlib.util.spec_from_file_location("privacy_scan",
                                                  os.path.join(HERE, "privacy_scan.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


privacy_scan = _load_privacy_scan()


def validate_doc_url(url):
    if not isinstance(url, str):
        raise ThemesError("URL が決まっていない")
    m = _DOC_URL_RE.match(url)
    if m is None or ".." in m.group(1):
        raise ThemesError("URL が data.gdeltproject.org/api/v2/guides/ の下の決めた形でない")
    if m.group(1) not in ALLOWED_GUIDE_FILES:
        raise ThemesError("/api/v2/guides/ の下で許すのは、全テーマの区分表（%s）だけ"
                          % ", ".join(ALLOWED_GUIDE_FILES))
    return m.group(1)


def _import_ledger():
    sealer = os.path.join(os.path.dirname(os.path.dirname(HERE)), "src", "sealer")
    if sealer not in sys.path:
        sys.path.insert(0, sealer)
    import ledger
    return ledger


def require_exclusion_rules_sealed():
    """0章の関門。引数は取らない（プロジェクトは ledger.PROJECT_ROOT）。返り値: (記録, root)。"""
    kind = EXCLUSION_RULE_KIND
    if kind is None:
        raise ExclusionRulesNotSealed("除外の規則の封印の記録の種類（kind）が、まだ決まっていない"
                                      "（封印係）。区分表は取得しない")
    ledger = _import_ledger()
    if kind not in ledger.ALLOWED_KINDS:
        raise ExclusionRulesNotSealed("kind %s が、封印の記録の種類の許可リストに無い" % kind)
    try:
        root = ledger._gate_root()
        _data, records = ledger._load_for_gate(root)
    except ledger.LedgerError as e:
        raise ExclusionRulesNotSealed("封印の記録を検証できない: %s" % e) from None
    recs = [r for r in records if r["kind"] == kind]
    if not recs:
        raise ExclusionRulesNotSealed("除外の規則の封印の記録（kind %s）が無い。区分表は取得しない"
                                      % kind)
    return recs[0], root


def exclusion_rule_ref(rec):
    """関門が返した記録の {"seq", "record_sha256"}（記録の行の正規の形の sha256）。中-B。"""
    ledger = _import_ledger()
    return {"seq": rec["seq"], "record_sha256": hashlib.sha256(ledger.canonical_line(rec)).hexdigest()}


def _exclusion_gate(root):
    """0章。返り値：exclusion_rule_ref。"""
    rec, gate_root = require_exclusion_rules_sealed()
    if os.path.realpath(gate_root) != os.path.realpath(root):
        raise ExclusionRulesNotSealed("関門が読んだプロジェクトと、run() の root が違う")
    return exclusion_rule_ref(rec)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def urllib_transport(url, timeout):
    validate_doc_url(url)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT,
                                               "Accept-Encoding": "identity"})
    try:
        return opener.open(req, timeout=timeout)
    except urllib.error.HTTPError as e:
        return e


def fetch_once(url, transport, clock):
    """1回だけ取得し、メモリの上のバイト列を返す。失敗は ThemesError（再試行しない）。"""
    validate_doc_url(url)
    deadline = clock() + TOTAL_DEADLINE_SECONDS
    resp = None
    try:
        resp = transport(url, REQUEST_TIMEOUT_SECONDS)
        status = getattr(resp, "status", None) or getattr(resp, "code", None)
        if status != 200:
            raise ThemesError("HTTP %s。再試行しない" % status)
        if resp.headers.get("Content-Encoding") not in (None, "", "identity"):
            raise ThemesError("応答が圧縮されている")
        buf = bytearray()
        while True:
            if clock() > deadline:
                raise ThemesError("時間の上限を超えた")
            chunk = resp.read(1 << 20)
            if not chunk:
                return bytes(buf)
            buf += chunk
            if len(buf) > MAX_BYTES:
                raise ThemesError("応答の長さの上限を超えた")
    except (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionError, OSError):
        raise ThemesError("通信の失敗。再試行しない") from None
    finally:
        if resp is not None:
            try:
                resp.close()
            except Exception:
                pass


# ---------------------------------------------------------------------------
# 3章：表を読む
# ---------------------------------------------------------------------------

_NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_RNS = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"


def _col_index(ref):
    letters = re.match(r"[A-Z]+", ref or "")
    if not letters:
        return None
    n = 0
    for ch in letters.group(0):
        n = n * 26 + ord(ch) - 64
    return n - 1


def _read_part(zf, name):
    info = zf.getinfo(name)
    if info.file_size > MAX_XLSX_PART_BYTES:
        raise ThemesError("xlsx の中のファイルが大きすぎる")
    return zf.read(name)


def read_xlsx(data):
    """[(シート名, [[セルの文字列, ...], ...]), ...]。数式は値のキャッシュを使う。"""
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
        names = set(zf.namelist())
        shared = []
        if "xl/sharedStrings.xml" in names:
            root = ET.fromstring(_read_part(zf, "xl/sharedStrings.xml"))
            for si in root.iter(_NS + "si"):
                shared.append("".join(t.text or "" for t in si.iter(_NS + "t")))
        wb = ET.fromstring(_read_part(zf, "xl/workbook.xml"))
        rels = ET.fromstring(_read_part(zf, "xl/_rels/workbook.xml.rels"))
        target = {r.get("Id"): r.get("Target") for r in rels}
        out = []
        for sh in wb.iter(_NS + "sheet"):
            t = target.get(sh.get(_RNS + "id"), "")
            path = t.lstrip("/") if t.startswith("/") else "xl/" + t
            root = ET.fromstring(_read_part(zf, path))
            rows = []
            for r in root.iter(_NS + "row"):
                cells = {}
                for c in r.iter(_NS + "c"):
                    i = _col_index(c.get("r"))
                    if i is None:
                        i = len(cells)
                    typ = c.get("t")
                    v = c.find(_NS + "v")
                    if typ == "s" and v is not None:
                        val = shared[int(v.text)]
                    elif typ == "inlineStr":
                        val = "".join(x.text or "" for x in c.iter(_NS + "t"))
                    else:
                        val = v.text if v is not None and v.text is not None else ""
                    cells[i] = val
                if cells:
                    rows.append([cells.get(i, "") for i in range(max(cells) + 1)])
            out.append((sh.get("name") or "", rows))
        return out
    except ThemesError:
        raise
    except (zipfile.BadZipFile, KeyError, ET.ParseError, ValueError, IndexError):
        raise ThemesError("xlsx として読めない") from None


def read_delimited(data):
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise ThemesError("UTF-8 として読めない") from None
    first = text.split("\n", 1)[0]
    delim = "\t" if "\t" in first else ","
    rows = [r for r in csv.reader(io.StringIO(text), delimiter=delim) if any(x.strip() for x in r)]
    return [("", rows)]


def read_table(data, name):
    low = name.lower()
    if low.endswith(".xlsx"):
        return read_xlsx(data)
    if low.endswith((".txt", ".tsv", ".csv")):
        return read_delimited(data)
    raise ThemesError("読める形（.txt・.tsv・.csv・.xlsx）でない")


# ---------------------------------------------------------------------------
# 2章：欄の分類
# ---------------------------------------------------------------------------

def classify_columns(header, rows):
    """返り値: (残す欄の番号の list, 捨てる欄の見出しの list)。止まるときは ThemesError。"""
    header = [h.strip() for h in header]
    if not header or any(not h for h in header) or len(set(h.lower() for h in header)) != len(header):
        raise ThemesError("見出しの行が無いか、空・重なった見出しがある（件数の欄を見出しで"
                          "確かめられない）")
    if any(looks_like_number(h) for h in header):
        raise ThemesError("1行目に数字だけの値がある（見出しの行が無い形とみなして止まる）")
    keep, drop, names = [], [], []
    for i, h in enumerate(header):
        col = [(r[i] if i < len(r) else "").strip() for r in rows]
        if not KEEP_HEADER_RE.match(h) or DROP_HEADER_RE.search(h):
            # 件数・頻度の欄と、知らない欄。見出しに数字があれば位置の名前で記録する
            drop.append("column_" + _letters(i) if has_numeric(h) else h)
        elif NAME_HEADER_RE.match(h):
            bad = sum(1 for v in col if not THEME_NAME_RE.match(v))
            if bad:
                raise ThemesError("テーマの名前の欄「%s」に、名前の形に合わない値が %d 件ある"
                                  "（件数が紛れている可能性があるので止まる）" % (h, bad))
            keep.append(i)
            names.append(i)
        elif any(has_numeric(v) for v in col):
            drop.append(h)                          # 数字の入った値がある欄は欄ごと捨てる
        else:
            keep.append(i)
    if not names:
        raise ThemesError("テーマの名前の欄が無い")
    return keep, drop


def build_output(sheets):
    """表から残す欄だけの TSV を作る。

    返り値: (バイト列, 行数, 残した見出し, 捨てた見出し, シート名を位置に替えたか,
             見出しの無い2欄の表として読んだか)。
    """
    data_sheets = [(n, rows) for n, rows in sheets if rows]
    if not data_sheets:
        raise ThemesError("表に行が無い")
    out_header, out_rows, dropped = None, [], []
    multi = len(data_sheets) > 1
    replaced = multi and any(has_numeric(n) for n, _rows in data_sheets)
    if replaced:
        data_sheets = [("sheet_" + _letters(i), rows) for i, (_n, rows) in enumerate(data_sheets)]
    headerless = False
    for sname, rows in data_sheets:
        if any(looks_like_number(h) for h in rows[0]):
            name_i, count_i = headerless_name_count(rows)     # 2.1章。合わなければ止まる
            headerless = True
            header = ["", ""]
            header[name_i] = "THEME"
            body = rows
            keep, drop = [name_i], ["column_" + _letters(count_i)]
        else:
            header, body = rows[0], rows[1:]
            keep, drop = classify_columns(header, body)
        h = [header[i].strip() for i in keep]
        if multi:
            h = ["sheet"] + h
        if out_header is None:
            out_header = h
        elif out_header != h:
            raise ThemesError("シートごとに残す欄が違う")
        dropped.extend(d for d in drop if d not in dropped)
        for r in body:
            vals = [(r[i] if i < len(r) else "").strip() for i in keep]
            if not any(vals):
                continue
            vals = [" ".join(v.split()) for v in vals]    # タブ・改行を空白1つにする
            out_rows.append(([sname] if multi else []) + vals)
    out_rows.sort()
    text = "\n".join("\t".join(r) for r in [out_header] + out_rows) + "\n"
    return text.encode("utf-8"), len(out_rows), out_header, dropped, replaced, headerless


def headerless_name_count(rows):
    """2.1章。返り値：(名前の欄の位置, 件数の欄の位置)。条件に合わなければ ThemesError。"""
    if any(len(r) != 2 for r in rows):
        raise ThemesError("1行目に数字だけの値がある（見出しの行が無い形）。欄がちょうど2つでない"
                          "ので、名前の欄を決められず止まる")
    cols = [[r[i].strip() for r in rows] for i in (0, 1)]

    def names(c):
        return all(THEME_NAME_RE.match(v) for v in c)

    def counts(c):
        return all(ASCII_DIGITS_RE.match(v) for v in c)
    fits = [(a, b) for a, b in ((0, 1), (1, 0)) if names(cols[a]) and counts(cols[b])]
    if len(fits) != 1:
        raise ThemesError("1行目に数字だけの値がある（見出しの行が無い形）。名前の欄と数字の欄を"
                          "値の形で一つに決められないので止まる")
    return fits[0]


# ---------------------------------------------------------------------------
# 4章：保存
# ---------------------------------------------------------------------------

def code_sha256():
    with open(os.path.join(HERE, "themes.py"), "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


_LOADED_SHA256 = code_sha256()          # 読み込んだ時点の themes.py（_code_gate が照らす）


def _iso(dt):
    return dt.astimezone(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _resolve(root, home):
    for depth in (1, 2):
        d = os.path.join(home, *STORE_PARTS[:depth])
        try:
            st = os.lstat(d)
        except OSError:
            raise ThemesError("保存先のフォルダが無い") from None
        if depth == 2 and not stat.S_ISDIR(st.st_mode):
            raise ThemesError("保存先が、シンボリックリンクかフォルダでない")
    store = os.path.realpath(os.path.join(home, *STORE_PARTS))
    root_real = os.path.realpath(root)
    if store == root_real or store.startswith(root_real + os.sep):
        raise ThemesError("保存先がプロジェクトの下にある")
    mdir = os.path.join(root, *MANIFEST_DIR_PARTS)
    if (os.path.islink(mdir) or os.path.islink(os.path.join(root, "data"))
            or os.path.realpath(mdir) != os.path.join(root_real, *MANIFEST_DIR_PARTS)):
        raise ThemesError("マニフェストのフォルダが、リンクかプロジェクトの外")
    return store, os.path.join(root_real, *MANIFEST_DIR_PARTS, MANIFEST_NAME)


def _load_codegate():
    spec = importlib.util.spec_from_file_location("codegate_for_themes",
                                                  os.path.join(HERE, "codegate.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _code_gate(root):
    """0.1章。返り値：(themes.py の code_sha256, HEAD のマニフェストのバイト列)。

    通らなければ ThemesError（何も書かない）。src/collector と src/sealer の両方を確かめる
    （除外の規則の関門が読み込む ledger.py は src/sealer にあるため。差し戻し2回目 軽-2）。
    """
    import subprocess
    if os.path.realpath(HERE) != os.path.join(os.path.realpath(root), "src", "collector"):
        raise ThemesError("動いている themes.py が、root のプロジェクトのものでない")
    cg = _load_codegate()
    try:
        codes = cg.check_clean(root, ("src/collector", "src/sealer"),
                               (CODE_REL, "src/collector/privacy_scan.py"))
        rel = "/".join(MANIFEST_DIR_PARTS + (MANIFEST_NAME,))
        code, _o = cg.run_git(root, "cat-file", "-e", "HEAD:%s" % rel)
        head_manifest = b""
        if code == 0:
            code, head_manifest = cg.run_git(root, "cat-file", "blob", "HEAD:%s" % rel)
            if code != 0:
                raise ThemesError("コードの関門：HEAD のマニフェストを読めない")
    except cg.CodeGateError as e:
        raise ThemesError("コードの関門：%s" % e) from None
    except (OSError, subprocess.SubprocessError):
        raise ThemesError("コードの関門：git の実行に失敗した") from None
    sha = hashlib.sha256(codes[CODE_REL]).hexdigest()
    if sha != _LOADED_SHA256 or sha != code_sha256():
        raise ThemesError("動いている themes.py が、HEAD にコミットした中身と違う")
    return sha, head_manifest


def _read_manifest(path):
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    except FileNotFoundError:
        return b""
    except OSError:
        raise ThemesError("マニフェストを開けない（シンボリックリンクなど）") from None
    with os.fdopen(fd, "rb") as f:
        return f.read()


def _append_line(path, entry, what):
    line = (json.dumps(entry, sort_keys=True, ensure_ascii=True) + "\n").encode("ascii")
    if privacy_scan.find_in_bytes(line):
        raise ThemesError("%s にメールアドレスの形の文字列があるので書かずに止まる" % what)
    fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC,
                 0o644)
    try:
        os.write(fd, line)
        os.fsync(fd)
    finally:
        os.close(fd)


def run(*, root, home, url=None, transport=urllib_transport, clock=time.monotonic,
        now=lambda: datetime.datetime.now(datetime.timezone.utc)):
    """1回だけ取得し、件数の欄を捨てて保存する（ThemesError で止まる）。

    関門（0章・0.1章）で止まるときは何も書かない。通信の直前に試行の行を書くので、通信の
    あとで止まったときは、試行の行だけが残る（区分表の本体は書かない）。
    """
    url = THEMES_URL if url is None else url
    name = validate_doc_url(url)
    sha_code, head_manifest = _code_gate(root)       # 0.1章。固定したコードで動くことを先に
    excl = _exclusion_gate(root)                      # 0章。通信の前に確かめる
    store, manifest = _resolve(root, home)
    if os.path.lexists(manifest) or head_manifest:
        # 行が1つも無い（空にした）ファイルがあっても止まる（差し戻し2回目 軽-1）
        raise ThemesError("区分表の取得は既に試みた（作業ツリーか HEAD にマニフェストがある）。"
                          "2回目は取得しない")
    stamp = now().astimezone(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    file_name = "gdelt-themes-%s.tsv" % stamp
    out_path = os.path.join(store, file_name)
    if os.path.lexists(out_path):
        raise ThemesError("同じ名前のファイルが既にある")
    attempted_at = _iso(now())
    _append_line(manifest, {"kind": "attempt", "attempted_at": attempted_at, "source_url": url,
                            "code_path": CODE_REL, "code_sha256": sha_code,
                            "exclusion_rule_seq": excl["seq"],
                            "exclusion_rule_record_sha256": excl["record_sha256"]},
                 "マニフェストの行")
    raw = fetch_once(url, transport, clock)
    fetched_at = _iso(now())
    sheets = read_table(raw, name)
    del raw                                           # 元の応答はここで手放す
    data, nrows, kept, dropped, replaced, headerless = build_output(sheets)
    del sheets
    entry = {"kind": "result", "file_name": file_name, "sha256": hashlib.sha256(data).hexdigest(),
             "rows": nrows, "kept_columns": kept, "dropped_columns": dropped,
             "fetched_at": fetched_at, "attempted_at": attempted_at,
             "sheet_names_replaced": replaced, "headerless": headerless,
             "source_url": url, "code_path": CODE_REL, "code_sha256": sha_code,
             "exclusion_rule_seq": excl["seq"],
             "exclusion_rule_record_sha256": excl["record_sha256"],
             "store_location": STORE_LOCATION_NAME}
    line = (json.dumps(entry, sort_keys=True, ensure_ascii=True) + "\n").encode("ascii")
    for what, b in (("区分表", data), ("マニフェストの行", line)):
        if privacy_scan.find_in_bytes(b):
            raise ThemesError("%s にメールアドレスの形の文字列があるので書かずに止まる" % what)
    fd = os.open(out_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                 0o644)
    try:
        view = memoryview(data)
        while view:
            view = view[os.write(fd, view):]
        os.fsync(fd)
    finally:
        os.close(fd)
    _append_line(manifest, entry, "マニフェストの行")
    return entry


if __name__ == "__main__":
    print("区分表の取得は、統計係の除外の規則の封印のあとの別のタスクで行う（除外の規則の封印の"
          "記録の種類は未定）。", file=sys.stderr)
    sys.exit(2)
