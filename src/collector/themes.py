#!/usr/bin/env python3
"""GKG のテーマの区分表（名前と説明の一覧）を取得し、件数の欄を捨てて保存する（T-018。コードだけ）。

データ出典
    Data: The GDELT Project (https://www.gdeltproject.org/). This project is not
    affiliated with or endorsed by the GDELT Project.
    データ出典：GDELT Project（https://www.gdeltproject.org/）。本プロジェクトは
    GDELT Project と提携・承認の関係にありません。

まだ一度も取得していない。T-018 の途中でリードの指示により、区分表の取得は、統計係の除外の
規則の封印のあとの別のタスクに移った。そのため取得元の URL（THEMES_URL）はまだ決めていない
（None）。None のままでは run() は通信の前に止まる。URL を決めて THEMES_URL に書き、コミット
してから実行する。

------------------------------------------------------------------------
1. 取得元と通信
------------------------------------------------------------------------
    - https://data.gdeltproject.org/documentation/<名前> の形だけを許す（validate_doc_url）。
      名前は英数字・点・下線・ハイフンだけ（「..」「/」「%」・クエリ・フラグメント・ポートは拒む）。
      ほかのホスト（gdeltcloud.com を含む）、/api/ などほかのパスは拒む。
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
        ため）。止まらずに欄ごと捨てる理由：取得は1回だけなので、止めると名前の欄まで失う。
        名前の欄が残れば区分表の目的（除外の規則をテーマの名前に当てる）は果たせ、捨てた欄の
        見出しはマニフェストの dropped_columns に残る。
      - 限界：数字を使わずに書いた量（「one million」など）は見分けられない。
    保存するのは、残した欄の見出しと値だけ。捨てた欄は、見出しの名前だけを報告とマニフェストに
    出す（値は出さない）。

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

THEMES_URL = None          # 取得のタスクで決める（上の注記）
ALLOWED_HOST = "data.gdeltproject.org"
_DOC_URL_RE = re.compile(
    r"\Ahttps://data\.gdeltproject\.org/documentation/([A-Za-z0-9][A-Za-z0-9._-]{0,127})\Z")
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
DIGIT_RE = re.compile(r"[0-9\uff10-\uff19]")
NUMERIC_RE = re.compile(r"\A[-+]?[0-9][0-9,]*(?:\.[0-9]+)?(?:[eE][-+]?[0-9]+)?\Z")
THEME_NAME_RE = re.compile(r"\A[A-Z][A-Z0-9_]{0,159}\Z")

STORE_PARTS = ("Desktop", "news-stick-data")
STORE_LOCATION_NAME = "~/" + "/".join(STORE_PARTS)
MANIFEST_DIR_PARTS = ("data", "manifest")
MANIFEST_NAME = "gdelt-themes.jsonl"
CODE_REL = "src/collector/themes.py"


class ThemesError(Exception):
    """止まった。文には、表の値を入れない（見出しの名前だけ）。"""


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
        raise ThemesError("URL が data.gdeltproject.org/documentation/ の下の決めた形でない")
    return m.group(1)


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

def _is_numeric_column(values):
    vals = [v.strip() for v in values if v.strip()]
    return bool(vals) and all(NUMERIC_RE.match(v) for v in vals)


def classify_columns(header, rows):
    """返り値: (残す欄の番号の list, 捨てる欄の見出しの list)。止まるときは ThemesError。"""
    header = [h.strip() for h in header]
    if not header or any(not h for h in header) or len(set(h.lower() for h in header)) != len(header):
        raise ThemesError("見出しの行が無いか、空・重なった見出しがある（件数の欄を見出しで"
                          "確かめられない）")
    if any(NUMERIC_RE.match(h) for h in header):
        raise ThemesError("1行目に数字だけの値がある（見出しの行が無い形とみなして止まる）")
    keep, drop, names = [], [], []
    for i, h in enumerate(header):
        col = [(r[i] if i < len(r) else "").strip() for r in rows]
        if not KEEP_HEADER_RE.match(h) or DROP_HEADER_RE.search(h):
            drop.append(h)                          # 件数・頻度の欄と、知らない欄
        elif NAME_HEADER_RE.match(h):
            bad = sum(1 for v in col if not THEME_NAME_RE.match(v))
            if bad:
                raise ThemesError("テーマの名前の欄「%s」に、名前の形に合わない値が %d 件ある"
                                  "（件数が紛れている可能性があるので止まる）" % (h, bad))
            keep.append(i)
            names.append(i)
        elif any(DIGIT_RE.search(v) for v in col):
            drop.append(h)                          # 数字の入った値がある欄は欄ごと捨てる
        else:
            keep.append(i)
    if not names:
        raise ThemesError("テーマの名前の欄が無い")
    return keep, drop


def build_output(sheets):
    """表から残す欄だけの TSV を作る。返り値: (バイト列, 行数, 残した見出し, 捨てた見出し)。"""
    data_sheets = [(n, rows) for n, rows in sheets if rows]
    if not data_sheets:
        raise ThemesError("表に行が無い")
    out_header, out_rows, dropped = None, [], []
    multi = len(data_sheets) > 1
    for sname, rows in data_sheets:
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
    return text.encode("utf-8"), len(out_rows), out_header, dropped


# ---------------------------------------------------------------------------
# 4章：保存
# ---------------------------------------------------------------------------

def code_sha256():
    with open(os.path.join(HERE, "themes.py"), "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


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


def run(*, root, home, url=None, transport=urllib_transport, clock=time.monotonic,
        now=lambda: datetime.datetime.now(datetime.timezone.utc)):
    """1回だけ取得し、件数の欄を捨てて保存する。止まるときは何も書かない（ThemesError）。"""
    url = THEMES_URL if url is None else url
    name = validate_doc_url(url)
    store, manifest = _resolve(root, home)
    stamp = now().astimezone(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    file_name = "gdelt-themes-%s.tsv" % stamp
    out_path = os.path.join(store, file_name)
    if os.path.lexists(out_path):
        raise ThemesError("同じ名前のファイルが既にある")
    raw = fetch_once(url, transport, clock)
    fetched_at = _iso(now())
    sheets = read_table(raw, name)
    del raw                                           # 元の応答はここで手放す
    data, nrows, kept, dropped = build_output(sheets)
    del sheets
    entry = {"file_name": file_name, "sha256": hashlib.sha256(data).hexdigest(), "rows": nrows,
             "kept_columns": kept, "dropped_columns": dropped, "fetched_at": fetched_at,
             "source_url": url, "code_path": CODE_REL, "code_sha256": code_sha256(),
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
    fd = os.open(manifest, os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC,
                 0o644)
    try:
        os.write(fd, line)
        os.fsync(fd)
    finally:
        os.close(fd)
    return entry


if __name__ == "__main__":
    print("区分表の取得は、統計係の除外の規則の封印のあとの別のタスクで行う（THEMES_URL は未定）。",
          file=sys.stderr)
    sys.exit(2)
