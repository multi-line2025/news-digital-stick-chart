"""GKG の取得と集計（src/collector/gkg.py）のテスト。T-018。

実行（プロジェクトのルートで）:
    PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest discover -s tests/collector -v

ネットワークは使わない（モジュールの読み込みの時点で socket の接続を塞ぐ）。GKG のファイルは、
27欄の架空の行で作った zip をメモリの上で返す差し替え（FakeTransport）で置き換える。
捨てる欄には目印（人物名・組織名・記事の URL・座標・メールアドレスの形・地名など）を入れ、
書かれたすべてのファイルとログに目印が無いことを確かめる。
保存先は一時的なディレクトリの下の仮のホームとプロジェクトで、本物には書かない。

このファイルには、メールアドレスの形の文字列をそのまま書かない（実行中に組み立てる）。
"""

import base64
import datetime
import gzip
import hashlib
import importlib.util
import io
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import unittest
import zipfile
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(os.path.dirname(HERE))
SRC = os.path.join(PROJECT, "src", "collector")


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


gkg = _load("gkg", os.path.join(SRC, "gkg.py"))
periods = _load("periods_for_gkg_test", os.path.join(PROJECT, "src", "stats", "periods.py"))
privacy_scan = gkg.privacy_scan

UTC = datetime.timezone.utc
NOW = datetime.datetime(2026, 10, 8, 0, 0, 0, tzinfo=UTC)
CODE_SHA = "ab" * 32
RUN_ID = CODE_SHA[:16]


class NetworkUsed(AssertionError):
    pass


def _blocked(*a, **k):
    raise NetworkUsed("テストの中でネットワークに接続しようとした")


_patches = [mock.patch.object(socket.socket, "connect", _blocked),
            mock.patch.object(socket.socket, "connect_ex", _blocked),
            mock.patch.object(socket, "create_connection", _blocked),
            mock.patch.object(socket, "getaddrinfo", _blocked)]


def setUpModule():
    for p in _patches:
        p.start()


def tearDownModule():
    for p in _patches:
        p.stop()


# --- 捨てる欄の目印 ------------------------------------------------------------

ADDRESS = "kaku.shimei" + "@" + "example" + ".org"
MARKERS = {
    "V2SOURCECOMMONNAME": "markersource.example",
    "V2DOCUMENTIDENTIFIER": "https://markersource.example/news/secretpath?u=" + ADDRESS,
    "V1COUNTS": "KILL#7#MARKERCOUNT#1#Markerville#US#USTX#31.1#-97.2#123",
    "V2.1COUNTS": "KILL#7#MARKERCOUNTTWO#1#Markerville#US#USTX#31.1#-97.2#123#55",
    "V2ENHANCEDLOCATIONS": "4#Markerville, Texas#US#USTX#48201#29.7604#-95.3698#-12345#99",
    "V1PERSONS": "markerperson tanaka;" + ADDRESS,
    "V2ENHANCEDPERSONS": "markerperson tanaka,10",
    "V1ORGANIZATIONS": "markerorganization inc",
    "V2ENHANCEDORGANIZATIONS": "markerorganization inc,20",
    "V1.5TONE": "-3.1415,1.2,4.3,5.5,20.1,0.0,777",
    "V2.1ENHANCEDDATES": "1#1#1#2019#150",
    "V2GCAM": "wc:777,c1.1:3,v42.1:0.31415",
    "V2.1SHARINGIMAGE": "https://markersource.example/img.jpg",
    "V2.1RELATEDIMAGES": "https://markersource.example/rel.jpg",
    "V2.1SOCIALIMAGEEMBEDS": "https://markersocial.example/p/1",
    "V2.1SOCIALVIDEOEMBEDS": "https://markervideo.example/v/1",
    "V2.1QUOTATIONS": "12|30||markerquotation said something",
    "V2.1ALLNAMES": "Markername Allnames,40",
    "V2.1AMOUNTS": "31415,markeramount,50",
    "V2EXTRASXML": "<PAGE_AUTHORS>" + ADDRESS + "</PAGE_AUTHORS>",
}
# 残す欄の中の、捨てる部分の目印（地名・ADM1・座標・FeatureID・文中の位置・ENG の知らない部分）
PARTIAL_MARKERS = ["Markertown", "USMK", "31.4159", "-271828", "MARKERENGINE", "98765"]


def all_markers():
    out = [v for v in MARKERS.values()]
    out += ["markersource", "markerperson", "markerorganization", "markerquotation",
            "Markername", "markeramount", "Markerville", "MARKERCOUNT", "secretpath", "29.7604",
            "-95.3698", "kaku.shimei"]
    out += PARTIAL_MARKERS
    return [m.encode() for m in out]


def gkg_row(ts, n, themes1=("QQ_ALPHA", "QQ_BETA_TWO"),
            themes2=(("QQ_ALPHA", 10), ("QQ_ALPHA", 90), ("QQ_BETA_TWO", 40)),
            countries=("JA", "US"), coll="1", translated=False, srclc=None, eng=None, d21=None,
            rid_ts=None):
    cols = dict(MARKERS)
    cols["GKGRECORDID"] = "%s-%s%d" % (rid_ts or ts, "T" if translated else "", n)
    cols["V2.1DATE"] = d21 if d21 is not None else ts
    cols["V2SOURCECOLLECTIONIDENTIFIER"] = coll
    cols["V1THEMES"] = ";".join(themes1) + (";" if themes1 else "")
    cols["V2ENHANCEDTHEMES"] = ";".join("%s,%d98765" % (t, o) for t, o in themes2) + ";"
    cols["V1LOCATIONS"] = ";".join("1#Markertown#%s#%sMK#31.4159#-271828#-271828" % (c, c[:1])
                                   for c in countries)
    parts = []
    if srclc:
        parts.append("srclc:%s" % srclc)
    if eng:
        parts.append("eng:%s" % eng)
    cols["V2.1TRANSLATIONINFO"] = ";".join(parts)
    return "\t".join(cols[c] for c in gkg.GKG_COLUMNS).encode()


def make_zip(ts, rows, name=None):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(name or (ts + ".gkg.csv"), b"\n".join(rows) + b"\n")
    return buf.getvalue()


def standard_rows(ts):
    return [gkg_row(ts, 1),
            gkg_row(ts, 2, themes1=("QQ_ALPHA",), themes2=(("QQ_ALPHA", 5),),
                    countries=("JA",), translated=True, srclc="jpn",
                    eng="GT-JPN 1.0 / MARKERENGINE x"),
            gkg_row(ts, 3, themes1=(), themes2=(), countries=(), coll="2")]


# --- 差し替えの通信 -----------------------------------------------------------

class FakeHeaders(dict):
    def get(self, k, default=None):
        return dict.get(self, k, default)


class FakeResponse:
    def __init__(self, body=b"", status=200, headers=None, fail=False):
        self.status, self.body, self.pos = status, body, 0
        self.headers = FakeHeaders(headers or {})
        self.fail = fail
        self.closed = False

    def read(self, n=-1):
        if self.fail:
            raise ConnectionResetError("見本の切断")
        chunk = self.body[self.pos:self.pos + n]
        self.pos += len(chunk)
        return chunk

    def close(self):
        self.closed = True


class FakeTransport:
    """file_time ごとの応答の列を返す。列が尽きたら最後の応答をくり返す。"""

    def __init__(self, by_time):
        self.by_time = {k: list(v) for k, v in by_time.items()}
        self.calls = []

    def __call__(self, url, timeout):
        gkg.validate_gkg_url(url)
        ts = url.rsplit("/", 1)[1][:14]
        self.calls.append(ts)
        seq = self.by_time[ts]
        r = seq.pop(0) if len(seq) > 1 else seq[0]
        if callable(r):
            r = r()
        return FakeResponse(r.body, r.status, dict(r.headers), r.fail)


class FakeClock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def ok_response(data):
    return FakeResponse(data)


def listing(ts, data):
    return (ts, "gkg", len(data), hashlib.md5(data).hexdigest())


def ts_of(day, i):
    """日 day（YYYYMMDD）の i 本目の15分の時刻。"""
    return "%s%02d%02d00" % (day, i // 4, (i % 4) * 15)


# --- 定数 -----------------------------------------------------------------------

class TestConstants(unittest.TestCase):
    def test_block_matches_periods(self):
        method = [b for b in periods.FROZEN_BLOCKS if b[0] == "method"][0]
        self.assertEqual(gkg.METHOD_BLOCK, (method[1].isoformat(), method[2].isoformat()))
        self.assertEqual(gkg.METHOD_BLOCK_END, method[2])
        self.assertEqual(gkg.DATA_START, periods.DATA_START)

    def test_limits_are_explicit(self):
        self.assertEqual(gkg.MAX_ZIP_BYTES, 200_000_000)
        self.assertEqual(gkg.MAX_UNZIPPED_BYTES, 1_000_000_000)
        self.assertEqual(gkg.MAX_ATTEMPTS_PER_FILE, 3)
        self.assertEqual(gkg.RETRY_WAIT_SECONDS, (30, 120))
        self.assertEqual(gkg.MIN_REQUEST_INTERVAL_SECONDS, 1.0)
        self.assertEqual(len(gkg.RETRY_WAIT_SECONDS), gkg.MAX_ATTEMPTS_PER_FILE - 1)
        doc = gkg.__doc__
        for name in ("MIN_REQUEST_INTERVAL_SECONDS", "MAX_ATTEMPTS_PER_FILE", "RETRY_WAIT_SECONDS",
                     "MAX_CONSECUTIVE_TRANSIENT_FAILURES", "MAX_ZIP_BYTES", "MAX_UNZIPPED_BYTES",
                     "MAX_PAIR_KEYS", "MIN_FREE_DISK_BYTES"):
            self.assertIn(name, doc)
        self.assertIn("公式の値ではない", doc)

    def test_citation_and_columns(self):
        self.assertIn("Data: The GDELT Project (https://www.gdeltproject.org/).",
                      " ".join(gkg.__doc__.split()))
        self.assertEqual(gkg.N_COLUMNS, 27)
        self.assertEqual(set(gkg.KEPT_COLUMNS) - set(gkg.GKG_COLUMNS), set())
        for dropped in ("V1PERSONS", "V2DOCUMENTIDENTIFIER", "V1ORGANIZATIONS",
                        "V2ENHANCEDLOCATIONS", "V2EXTRASXML"):
            self.assertNotIn(dropped, gkg.KEPT_COLUMNS)

    def test_day_rule_is_filelist_rule(self):
        self.assertIs(gkg.filelist.file_day.__code__.co_filename,
                      gkg.filelist.file_day.__code__.co_filename)
        self.assertEqual(os.path.realpath(gkg.filelist.__file__),
                         os.path.realpath(os.path.join(SRC, "filelist.py")))


class TestUrl(unittest.TestCase):
    def test_allowed_and_rejected(self):
        self.assertEqual(gkg.gkg_url("20150302000000"),
                         "https://data.gdeltproject.org/gdeltv2/20150302000000.gkg.csv.zip")
        for bad in ("http://data.gdeltproject.org/gdeltv2/20150302000000.gkg.csv.zip",
                    "https://api.gdeltcloud.com/gdeltv2/20150302000000.gkg.csv.zip",
                    "https://data.gdeltproject.org/gdeltv2/20150302000000.translation.gkg.csv.zip",
                    "https://data.gdeltproject.org/gdeltv2/../x/20150302000000.gkg.csv.zip",
                    "https://data.gdeltproject.org:8443/gdeltv2/20150302000000.gkg.csv.zip",
                    "https://data.gdeltproject.org/gdeltv2/20150302000000.gkg.csv.zip?x=1", None):
            with self.assertRaises(gkg.GkgError):
                gkg.validate_gkg_url(bad)
        with self.assertRaises(gkg.GkgError):
            gkg.urllib_transport("https://example.org/x", 1)


# --- 対象の選び方 -----------------------------------------------------------------

class TestSelect(unittest.TestCase):
    def test_data_start_and_types_and_days(self):
        rows = [("20150301234500", "gkg", 1, "0" * 32),     # DATA_START より前の日：除く
                ("20150218230000", "gkg", 1, "1" * 32),     # 除く（T-016 の監査 軽1）
                ("20150302000000", "gkg", 2, "2" * 32),
                ("20150302000000", "export", 2, "3" * 32),  # gkg 以外：除く
                ("20150302235000", "gkg", 2, "4" * 32),     # 刻みに揃わない：翌日の日
                ("20201214234500", "gkg", 2, "5" * 32),
                ("20201215000000", "gkg", 2, "6" * 32)]     # 区画の後：除く
        plan = gkg.select_files(rows)
        self.assertEqual(list(plan), ["2015-03-02", "2015-03-03", "2020-12-14"])
        self.assertEqual([e["file_time"] for e in plan["2015-03-02"]], ["20150302000000"])
        self.assertEqual([e["file_time"] for e in plan["2015-03-03"]], ["20150302235000"])
        for e in sum(plan.values(), []):
            self.assertGreaterEqual(gkg.filelist.file_day(gkg.filelist.parse_file_time(
                e["file_time"])), gkg.DATA_START)

    def test_duplicates(self):
        rows = [("20150302000000", "gkg", 2, "a" * 32), ("20150302000000", "gkg", 2, "a" * 32),
                ("20150302001500", "gkg", 2, "a" * 32), ("20150302001500", "gkg", 3, "b" * 32)]
        plan = gkg.select_files(rows)["2015-03-02"]
        self.assertEqual([(e["file_time"], e["ambiguous"]) for e in plan],
                         [("20150302000000", False), ("20150302001500", True)])

    def test_parse_filelist(self):
        data = b"file_time\tfile_type\tsize_bytes\tmd5\n20150302000000\tgkg\t5\t" + b"a" * 32 + b"\n"
        self.assertEqual(gkg.parse_filelist(data), [("20150302000000", "gkg", 5, "a" * 32)])
        for bad in (b"x\n", data.replace(b"gkg", b"zzz"), data[:-1]):
            with self.assertRaises(gkg.GkgError):
                gkg.parse_filelist(bad)


# --- 欄を捨てることと集計 ----------------------------------------------------------

class TestAggregate(unittest.TestCase):
    TS = "20150302000000"

    def agg(self, rows):
        return gkg.aggregate_zip(make_zip(self.TS, rows), self.TS, {})

    def test_counts(self):
        a = self.agg(standard_rows(self.TS))
        T = a.tables
        self.assertEqual(a.docs, {b"1": 1, b"1T": 1, b"2": 1})
        self.assertEqual(T["t1"][b"1"], {b"QQ_ALPHA": 1, b"QQ_BETA_TWO": 1})
        self.assertEqual(T["t2m"][b"1"], {b"QQ_ALPHA": 2, b"QQ_BETA_TWO": 1})
        self.assertEqual(T["t2"][b"1"], {b"QQ_ALPHA": 1, b"QQ_BETA_TWO": 1})
        self.assertEqual(T["c1"][b"1"][(b"QQ_ALPHA", b"JA")], 1)
        self.assertEqual(T["c2m"][b"1"][(b"QQ_ALPHA", b"US")], 2)
        self.assertEqual(T["l1"][b"1T"], {(b"QQ_ALPHA", b"jpn"): 1})
        self.assertEqual(T["l1"][b"1"], {(b"QQ_ALPHA", b"-"): 1,
                                         (b"QQ_BETA_TWO", b"-"): 1})
        self.assertEqual(T["p1"][b"1"], {(b"QQ_ALPHA", b"QQ_BETA_TWO"): 1})
        self.assertEqual(T["p2"][b"1"], {(b"QQ_ALPHA", b"QQ_BETA_TWO"): 1})
        self.assertEqual(T["eng"][b"1T"], {b"GT-JPN 1.0": 1})
        self.assertEqual(a.stats["eng_other_tokens"], 1)          # 知らない部分は件数だけ
        self.assertEqual(T["nc"][b"1"], {b"JA": 1, b"US": 1})
        self.assertEqual(a.stats["docs_translated_mark"], 1)
        self.assertEqual(a.stats["d21_same_as_file"], 3)
        self.assertEqual(a.stats["docs_without_v1_theme"], 1)

    def test_bad_rows_are_counted_and_dropped(self):
        ts = self.TS
        rows = standard_rows(ts) + [
            b"too\tfew\tcolumns",
            gkg_row(ts, 9).replace(b"%s-9" % ts.encode(), b"NOTANID"),
            gkg_row(ts, 10, themes1=("QQ_ALPHA", "lower case theme", "X@Y"),
                    countries=("JA", "J1"), srclc="Japanese", coll="abc", d21="0"),
            gkg_row(ts, 12, rid_ts="20150302001500"),          # ずれるが区画の中：残す
            gkg_row(ts, 13, rid_ts="20150301000000"),          # 区画の前：数えて捨てる
        ]
        a = self.agg(rows)
        st = a.stats
        self.assertEqual(st["rows_bad_columns"], 1)
        self.assertEqual(st["rows_bad_id"], 1)
        self.assertEqual(st["rows_id_time_differs"], 2)
        self.assertEqual(st["rows_id_time_before_block"], 1)
        self.assertEqual(st["rows"], len(rows))
        self.assertEqual(st["theme_tokens_invalid_v1"], 2)
        self.assertEqual(st["country_codes_invalid"], 1)
        self.assertEqual(st["srclc_other"], 1)
        self.assertEqual(st["d21_zero"], 1)
        self.assertEqual(a.docs[b"X"], 1)
        self.assertEqual(sum(a.docs.values()), 5)

    def test_post_block_rows_are_dropped_without_counting(self):
        """区画の後ろの時刻の行は、どの件数にも入らない（行の数が変わっても出力は同じ）。"""
        ts = self.TS
        base = standard_rows(ts)
        files = [{"file_time": ts, "result": "ok", "reason": "", "md5": "a" * 32, "size": 9,
                  "sha256": "b" * 64, "attempts": 1, "docs": {"1": 1}}]
        outs = []
        for n in (0, 1, 5):
            post = [gkg_row(ts, 100 + i, rid_ts=t, themes1=("QQ_POSTMARK",))
                    for i, t in enumerate(["20201214234501", "20201215000000", "99991231235959",
                                           "20231107000000", "20201299999999"][:n])]
            a = gkg.aggregate_zip(make_zip(ts, base + post), ts, {})
            outs.append(gkg.serialize_day("2015-03-02", a, files))
        self.assertEqual(outs[0], outs[1])
        self.assertEqual(outs[0], outs[2])
        self.assertNotIn(b"QQ_POSTMARK", outs[2])
        self.assertEqual(gkg.LAST_KEPT_TS.decode(),
                         gkg.filelist.LAST_KEPT_TIME.strftime("%Y%m%d%H%M%S"))

    def test_zip_checks(self):
        ts = self.TS
        with self.assertRaisesRegex(gkg.GkgFormatError, "zip_member_name"):
            gkg.aggregate_zip(make_zip(ts, [gkg_row(ts, 1)], name="other.csv"), ts, {})
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr(ts + ".gkg.csv", b"x")
            zf.writestr("b.csv", b"y")
        with self.assertRaisesRegex(gkg.GkgFormatError, "zip_members"):
            gkg.aggregate_zip(buf.getvalue(), ts, {})
        with self.assertRaisesRegex(gkg.GkgFormatError, "zip"):
            gkg.aggregate_zip(b"not a zip", ts, {})
        with mock.patch.object(gkg, "MAX_UNZIPPED_BYTES", 100):
            with self.assertRaisesRegex(gkg.GkgFormatError, "too_large_unzipped"):
                gkg.aggregate_zip(make_zip(ts, standard_rows(ts)), ts, {})
        with mock.patch.object(gkg, "MAX_LINE_BYTES", 50):
            a = gkg.aggregate_zip(make_zip(ts, standard_rows(ts)), ts, {})
            self.assertEqual(a.stats["rows_too_long"], 3)
            self.assertEqual(sum(a.docs.values()), 0)

    def test_serialized_day_has_only_allowlisted_values(self):
        a = self.agg(standard_rows(self.TS) + [gkg_row(self.TS, 7, countries=("JA",))])
        files = [{"file_time": self.TS, "result": "ok", "reason": "", "md5": "a" * 32, "size": 9,
                  "sha256": "b" * 64, "attempts": 1, "docs": {"1": 2}}]
        data = gkg.serialize_day("2015-03-02", a, files)
        gkg.check_output_bytes(data, "日の集計")
        for m in all_markers():
            self.assertNotIn(m, data, m)
        self.assertEqual(privacy_scan.find_in_bytes(data), {})
        self.assertEqual(gkg.serialize_day("2015-03-02", a, files), data)   # 決まった並べ方
        lines = data.decode().splitlines()
        self.assertEqual(lines[0], "#\tgkg-day\t1\t2015-03-02")
        tags = {l.split("\t")[0] for l in lines}
        self.assertTrue({"F", "FD", "V", "D", "T", "C", "L", "P1", "P2", "NC", "NL", "E", "S"}
                        <= tags)
        v = {l.split("\t")[2]: l.split("\t")[1] for l in lines if l.startswith("V\t")}
        self.assertIn("\t".join(["P1", "1", v["QQ_ALPHA"], v["QQ_BETA_TWO"], "2"]),
                      lines)
        self.assertEqual(gzip.decompress(gkg.gzip_bytes(data)), data)
        self.assertEqual(gkg.gzip_bytes(data), gkg.gzip_bytes(data))

    def test_output_alphabet_check(self):
        with self.assertRaises(gkg.GkgError):
            gkg.check_output_bytes(b"T\t1\tA@B\n", "x")
        with self.assertRaises(gkg.GkgError):
            gkg.check_output_bytes(("T\t" + ADDRESS + "\n").encode(), "x")


# --- 取得と再試行 ------------------------------------------------------------------

class TestFetch(unittest.TestCase):
    TS = "20150302000000"

    def setUp(self):
        self.data = make_zip(self.TS, standard_rows(self.TS))
        self.entry = {"file_time": self.TS, "size": len(self.data),
                      "md5": hashlib.md5(self.data).hexdigest(), "ambiguous": False}
        self.clock = FakeClock()
        self.waits = []

    def sleep(self, s):
        self.waits.append(s)
        self.clock.t += s

    def fetch(self, responses):
        tr = FakeTransport({self.TS: responses})
        r = gkg.fetch_file(self.entry, tr, self.sleep, self.clock,
                           gkg.Pacer(self.clock, self.sleep), lambda m: None)
        return r, tr

    def test_ok(self):
        r, tr = self.fetch([ok_response(self.data)])
        self.assertEqual((r.result, r.attempts, r.data), ("ok", 1, self.data))

    def test_retry_limit_and_waits(self):
        r, tr = self.fetch([FakeResponse(status=503)])
        self.assertEqual((r.result, r.reason, r.transient), ("failed", "http_503", True))
        self.assertEqual(len(tr.calls), gkg.MAX_ATTEMPTS_PER_FILE)
        self.assertEqual(self.waits, list(gkg.RETRY_WAIT_SECONDS))

    def test_retry_then_ok(self):
        r, tr = self.fetch([FakeResponse(fail=True), ok_response(self.data)])
        self.assertEqual((r.result, r.attempts), ("ok", 2))

    def test_404_not_retried(self):
        r, tr = self.fetch([FakeResponse(status=404)])
        self.assertEqual((r.result, r.reason, r.transient, len(tr.calls)),
                         ("failed", "http_404", False, 1))

    def test_md5_mismatch_retried_then_failed(self):
        bad = bytearray(self.data)
        bad[-1] ^= 1
        r, tr = self.fetch([ok_response(bytes(bad))])
        self.assertEqual((r.result, r.reason, len(tr.calls)), ("failed", "md5_mismatch", 3))

    def test_too_large_not_retried(self):
        with mock.patch.object(gkg, "MAX_ZIP_BYTES", 10):
            r, tr = self.fetch([ok_response(self.data)])
        self.assertEqual((r.result, r.reason, len(tr.calls)), ("failed", "too_large", 1))

    def test_retry_after_too_long(self):
        r, tr = self.fetch([FakeResponse(status=429, headers={"Retry-After": "100000"})])
        self.assertEqual((r.reason, len(tr.calls)), ("retry_after_too_long", 1))

    def test_pacer(self):
        p = gkg.Pacer(self.clock, self.sleep)
        p.wait()
        self.clock.t += 0.25
        p.wait()
        self.assertEqual(self.waits, [0.75])


# --- 取得の全体 --------------------------------------------------------------------

class RunCase(unittest.TestCase):
    DAYS = ("20150302", "20150303")
    N = 4

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="gkg-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.root = os.path.join(self.tmp, "proj")
        os.makedirs(os.path.join(self.root, "data", "manifest"))
        os.makedirs(os.path.join(self.root, ".git"))
        self.home = os.path.join(self.tmp, "home")
        self.store = os.path.join(self.home, *gkg.STORE_PARTS)
        os.makedirs(self.store)
        self.zips = {}
        for d in self.DAYS:
            for i in range(self.N):
                ts = ts_of(d, i)
                self.zips[ts] = make_zip(ts, standard_rows(ts))
        self.rows = [listing(ts, z) for ts, z in sorted(self.zips.items())]
        self.rows.append(("20150301000000", "gkg", 1, "0" * 32))     # DATA_START より前
        self.responses = {ts: [ok_response(z)] for ts, z in self.zips.items()}
        self.clock = FakeClock()
        self.logs = []
        self.free = 100 * 1024 ** 3
        self.low_after = None      # 何回目の確かめから空きが無くなるか（None なら常に十分）
        self.free_calls = 0

    def disk_free(self, path):
        self.free_calls += 1
        if self.low_after is not None and self.free_calls > self.low_after:
            return 0
        return self.free

    def sleep(self, s):
        self.clock.t += s

    def run_gkg(self, **kw):
        self.transport = FakeTransport(self.responses)
        args = dict(root=self.root, home=self.home, filelist_rows=self.rows,
                    filelist_sha256="c" * 64, method_access_seq=5, code_sha256=CODE_SHA,
                    transport=self.transport, sleep=self.sleep, clock=self.clock,
                    now=lambda: NOW, log=self.logs.append, disk_free=self.disk_free)
        args.update(kw)
        return gkg.run_gkg(**args)

    def manifest(self):
        return gkg.read_jsonl(os.path.join(self.root, "data", "manifest", gkg.MANIFEST_NAME))

    def fetch_log(self):
        return gkg.read_jsonl(os.path.join(self.store, gkg.fetch_log_name(RUN_ID)))

    def written(self):
        out = {}
        for top in (self.store, os.path.join(self.root, "data")):
            for d, _ds, fs in os.walk(top):
                for n in fs:
                    with open(os.path.join(d, n), "rb") as f:
                        b = f.read()
                    out[os.path.join(d, n)] = gzip.decompress(b) if n.endswith(".gz") else b
        out["log"] = "\n".join(self.logs).encode()
        return out


class TestRun(RunCase):
    def test_normal_run(self):
        done = self.run_gkg()
        m = self.manifest()
        self.assertEqual([e["kind"] for e in m], ["run-start", "day", "day", "run-complete"])
        self.assertEqual(m[0]["files_selected"], len(self.zips))
        self.assertEqual(done["files_ok"], len(self.zips))
        self.assertEqual(sorted(os.listdir(self.store)),
                         sorted([gkg.fetch_log_name(RUN_ID)]
                                + [gkg.day_file_name(RUN_ID, "%s-%s-%s" % (d[:4], d[4:6], d[6:]))
                                   for d in self.DAYS]))
        for e in m[1:3]:
            with open(os.path.join(self.store, e["file_name"]), "rb") as f:
                self.assertEqual(hashlib.sha256(f.read()).hexdigest(), e["sha256"])
        log = self.fetch_log()
        self.assertEqual(len(log), len(self.zips))
        for e in log:
            self.assertEqual(e["sha256"], hashlib.sha256(self.zips[e["file_time"]]).hexdigest())
            self.assertEqual(e["listed_md5"], hashlib.md5(self.zips[e["file_time"]]).hexdigest())
        self.assertNotIn("20150301000000", self.transport.calls)    # DATA_START より前は取らない
        with open(os.path.join(self.store, gkg.fetch_log_name(RUN_ID)), "rb") as f:
            self.assertEqual(hashlib.sha256(f.read()).hexdigest(), done["fetch_log_sha256"])
        with self.assertRaisesRegex(gkg.GkgError, "完了している"):    # 完了したら取り直さない
            self.run_gkg()

    def test_written_files_and_logs_have_no_markers_or_addresses(self):
        self.responses[ts_of(self.DAYS[0], 1)] = [FakeResponse(status=404)]
        self.run_gkg()
        files = self.written()
        self.assertGreater(len(files), 4)
        for name, data in files.items():
            self.assertEqual(privacy_scan.find_in_bytes(data), {}, name)
            for mk in all_markers():
                self.assertNotIn(mk, data, (name, mk))
            self.assertNotIn(self.home.encode(), data, name)
            self.assertNotIn(self.root.encode(), data, name)

    def test_missing_file_is_recorded(self):
        ts = ts_of(self.DAYS[0], 2)
        self.responses[ts] = [FakeResponse(status=404)]
        self.run_gkg()
        log = {e["file_time"]: e for e in self.fetch_log()}
        self.assertEqual((log[ts]["result"], log[ts]["reason"]), ("failed", "http_404"))
        day = [e for e in self.manifest() if e.get("kind") == "day"][0]
        self.assertEqual((day["files_listed"], day["files_ok"], day["files_failed"]),
                         (self.N, self.N - 1, 1))
        with open(os.path.join(self.store, day["file_name"]), "rb") as f:
            text = gzip.decompress(f.read()).decode()
        self.assertIn("F\t%s\tfailed\thttp_404\t" % ts, text)

    def test_ambiguous_listing_not_fetched(self):
        ts = ts_of(self.DAYS[0], 0)
        self.rows.append((ts, "gkg", 1, "f" * 32))
        self.run_gkg()
        self.assertNotIn(ts, self.transport.calls)
        log = {e["file_time"]: e for e in self.fetch_log()}
        self.assertEqual(log[ts]["reason"], "ambiguous_listing")

    def test_failed_files_are_not_retried_on_resume(self):
        """failed は再開しても取り直さない。止まった日の ok のファイルは取り直す。"""
        bad = ts_of(self.DAYS[0], 1)
        self.responses[bad] = [FakeResponse(status=404)]
        self.low_after = 1
        with self.assertRaises(gkg.RunInterrupted):        # 日の集計を書く前に止まる
            self.run_gkg()
        self.assertEqual([e["kind"] for e in self.manifest()], ["run-start"])
        self.responses[bad] = [ok_response(self.zips[bad])]   # 相手が直っても
        self.low_after = None
        self.run_gkg()
        self.assertNotIn(bad, self.transport.calls)          # 取り直さない
        self.assertIn(ts_of(self.DAYS[0], 0), self.transport.calls)   # ok は取り直す
        kinds = [e["kind"] for e in self.manifest()]
        self.assertEqual(kinds, ["run-start", "run-resume", "day", "day", "run-complete"])
        day = [e for e in self.manifest() if e.get("kind") == "day"][0]
        self.assertEqual(day["files_failed"], 1)

    def test_transient_breaker_and_resume(self):
        """一時的な失敗が続けば止まり、続いたファイルは interrupted。再開で取り直す。"""
        times = sorted(self.zips)
        for ts in times[:gkg.MAX_CONSECUTIVE_TRANSIENT_FAILURES]:
            self.responses[ts] = [FakeResponse(status=503)]
        with self.assertRaises(gkg.RunInterrupted):
            self.run_gkg()
        log = self.fetch_log()
        inter = [e["file_time"] for e in log if e["result"] == "interrupted"]
        self.assertEqual(inter, times[:gkg.MAX_CONSECUTIVE_TRANSIENT_FAILURES])
        for ts in times:
            self.responses[ts] = [ok_response(self.zips[ts])]
        done = self.run_gkg()
        self.assertEqual(done["files_failed"], 0)
        self.assertEqual(sorted(set(self.transport.calls)), times)

    def test_streak_across_days_keeps_previous_day_unwritten(self):
        """日をまたいで続いた一時的な失敗も interrupted になり、前の日はまだ書かれていない。"""
        times = sorted(self.zips)
        streak = times[self.N - 2:self.N - 2 + gkg.MAX_CONSECUTIVE_TRANSIENT_FAILURES]
        for ts in streak:
            self.responses[ts] = [FakeResponse(status=503)]
        with self.assertRaises(gkg.RunInterrupted):
            self.run_gkg()
        self.assertEqual([e["kind"] for e in self.manifest()], ["run-start"])
        inter = [e["file_time"] for e in self.fetch_log() if e["result"] == "interrupted"]
        self.assertEqual(inter, streak)

    def test_interrupted_retry_only_once_per_run(self):
        """interrupted で取り直すのは run の中で1回だけ。2回目の連続した失敗は failed で確定する。"""
        self.assertEqual(gkg.MAX_INTERRUPTED_RETRIES_PER_RUN, 1)
        times = sorted(self.zips)
        streak = times[:gkg.MAX_CONSECUTIVE_TRANSIENT_FAILURES]
        for ts in times:
            self.responses[ts] = [FakeResponse(status=503)]
        with self.assertRaisesRegex(gkg.RunInterrupted, "1回だけ取り直す"):
            self.run_gkg()
        with self.assertRaisesRegex(gkg.RunInterrupted, "使い切った"):
            self.run_gkg()                       # 1回目の取り直し。また続けて失敗する
        self.assertEqual(sorted(set(self.transport.calls)), streak)
        for ts in times:                         # 相手が直っても
            self.responses[ts] = [ok_response(self.zips[ts])]
        done = self.run_gkg()
        for ts in streak:
            self.assertNotIn(ts, self.transport.calls)   # 2回目は取り直さない
        self.assertEqual(done["files_failed"], len(streak))
        trips = {e.get("trip") for e in self.fetch_log() if e["result"] == "interrupted"}
        self.assertEqual(trips, {1})

    def test_official_run_is_first_run_start(self):
        self.run_gkg()
        with self.assertRaisesRegex(gkg.GkgError, "別の run"):
            self.run_gkg(code_sha256="cd" * 32)
        m = self.manifest()
        self.assertEqual(gkg.official_run_id(m), RUN_ID)
        self.assertTrue(m[0]["official"])
        days = gkg.official_day_records(m)
        self.assertEqual([d["day"] for d in days], ["2015-03-02", "2015-03-03"])

    def test_new_run_refused_even_if_first_did_not_finish(self):
        self.low_after = 1
        with self.assertRaises(gkg.RunInterrupted):
            self.run_gkg()
        self.low_after = None
        with self.assertRaisesRegex(gkg.GkgError, "別の run"):
            self.run_gkg(code_sha256="cd" * 32)
        with self.assertRaisesRegex(gkg.GkgError, "終わっていない"):
            gkg.official_day_records(self.manifest())

    def test_format_breaker(self):
        for ts in self.zips:
            z = make_zip(ts, [gkg_row(ts, 1)], name="x.csv")
            self.responses[ts] = [ok_response(z)]
            self.rows = [r for r in self.rows if r[0] != ts] + [listing(ts, z)]
        with mock.patch.object(gkg, "MAX_CONSECUTIVE_FORMAT_FAILURES", 3):
            with self.assertRaisesRegex(gkg.RunInterrupted, "形式の失敗"):
                self.run_gkg()

    def test_pair_limit_stops(self):
        with mock.patch.object(gkg, "MAX_PAIR_KEYS", 0):
            with self.assertRaisesRegex(gkg.RunInterrupted, "組の種類"):
                self.run_gkg()

    def test_resume_requires_same_inputs(self):
        self.low_after = 1
        with self.assertRaises(gkg.RunInterrupted):
            self.run_gkg()
        self.low_after = None
        with self.assertRaisesRegex(gkg.GkgError, "filelist_sha256"):
            self.run_gkg(filelist_sha256="d" * 64)

    def test_store_checks(self):
        shutil.rmtree(self.store)
        with self.assertRaisesRegex(gkg.GkgError, "無い"):
            self.run_gkg()
        os.makedirs(os.path.join(self.tmp, "else"))
        os.symlink(os.path.join(self.tmp, "else"), self.store)
        with self.assertRaisesRegex(gkg.GkgError, "シンボリックリンク"):
            self.run_gkg()
        os.remove(self.store)
        os.makedirs(self.store)
        os.makedirs(os.path.join(self.home, "Desktop", ".git"))
        with self.assertRaisesRegex(gkg.GkgError, "Git の作業ツリー"):
            self.run_gkg()
        self.assertEqual(self.manifest(), [])

    def test_no_temp_files(self):
        """tempfile を使わない（Actions の上で一時ファイルを作らない）。"""
        with mock.patch("tempfile.mkstemp", side_effect=AssertionError("tempfile")), \
                mock.patch("tempfile.NamedTemporaryFile", side_effect=AssertionError("tempfile")), \
                mock.patch("tempfile.TemporaryFile", side_effect=AssertionError("tempfile")), \
                mock.patch("tempfile.SpooledTemporaryFile", side_effect=AssertionError("tempfile")):
            self.run_gkg()
        with open(os.path.join(SRC, "gkg.py"), encoding="utf-8") as f:
            self.assertNotIn("import tempfile", f.read())


CHILD_SCRIPT = os.path.join(HERE, "gkg_child.py")


class ChildRun:
    """GKG の取得（または集計だけ）を子プロセス（gkg_child.py）で、audit hook の見張りの下で動かす。

    返り値："report"（子の結果と、止めた記録 violations）、"files"（root・store・outside の下の
    全ファイル。.gz は展開した中身）、"outside"（outside の下の名前の一覧）、stdout・stderr。
    source_mutation を与えると、gkg.py の写しを置き換えて子に読み込ませる。
    """

    DAYS = ("20150302", "20150303")

    def __init__(self, tc):
        self.tc = tc

    def __call__(self, mode="run", mutation=None, source_mutation=None):
        tops = {k: tempfile.mkdtemp(prefix="gkg-child-%s-" % k)
                for k in ("root", "home", "outside", "code")}
        try:
            mdir = os.path.join(tops["root"], "data", "manifest")
            os.makedirs(mdir)
            store = os.path.join(tops["home"], *gkg.STORE_PARTS)
            os.makedirs(store)
            zips = {}
            for d in self.DAYS:
                for i in range(2):
                    ts = ts_of(d, i)
                    zips[ts] = make_zip(ts, standard_rows(ts))
            rows = [listing(ts, z) for ts, z in sorted(zips.items())]
            gkg_path = os.path.join(SRC, "gkg.py")
            if source_mutation:
                with open(gkg_path, encoding="utf-8") as f:
                    src = f.read()
                for a, b in source_mutation:
                    self.tc.assertEqual(src.count(a), 1, a)
                    src = src.replace(a, b.replace("OUTSIDE", tops["outside"]))
                gkg_path = os.path.join(tops["code"], "gkg.py")
                with open(gkg_path, "w", encoding="utf-8") as f:
                    f.write(src)
                for name in ("filelist.py", "privacy_scan.py"):
                    shutil.copyfile(os.path.join(SRC, name), os.path.join(tops["code"], name))
            real_store = os.path.realpath(store)
            allowed = []
            if mode == "run":
                allowed = [os.path.join(os.path.realpath(mdir), gkg.MANIFEST_NAME),
                           os.path.join(real_store, gkg.fetch_log_name(RUN_ID))]
                allowed += [os.path.join(real_store, gkg.day_file_name(
                    RUN_ID, "%s-%s-%s" % (d[:4], d[4:6], d[6:]))) for d in self.DAYS]
            report = tempfile.TemporaryFile()
            vio = tempfile.TemporaryFile()
            try:
                cfg = {"report_fd": report.fileno(), "violation_fd": vio.fileno(),
                       "gkg_path": gkg_path, "root": tops["root"], "home": tops["home"],
                       "outside": tops["outside"], "mode": mode, "mutation": mutation,
                       "allowed": allowed, "code_sha": CODE_SHA, "now": NOW.isoformat(),
                       "rows": rows,
                       "zips": {k: base64.b64encode(v).decode() for k, v in zips.items()}}
                env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
                proc = subprocess.run([sys.executable, "-B", CHILD_SCRIPT],
                                      input=json.dumps(cfg).encode(), capture_output=True,
                                      pass_fds=(report.fileno(), vio.fileno()), env=env,
                                      timeout=120)
                report.seek(0)
                raw = report.read()
                vio.seek(0)
                vraw = vio.read()
            finally:
                report.close()
                vio.close()
            self.tc.assertEqual(proc.returncode, 0, proc.stderr.decode(errors="replace"))
            rep = json.loads(raw)
            rep["violations"] = [json.loads(l) for l in vraw.decode("ascii").splitlines()]
            files = {}
            for k in ("root", "home", "outside"):
                for d, _ds, fs in os.walk(tops[k]):
                    for n in fs:
                        with open(os.path.join(d, n), "rb") as f:
                            b = f.read()
                        files[os.path.join(k, os.path.relpath(os.path.join(d, n), tops[k]))] = (
                            gzip.decompress(b) if n.endswith(".gz") else b)
            outside = sorted(os.listdir(tops["outside"]))
            return {"report": rep, "files": files, "outside": outside, "stdout": proc.stdout,
                    "stderr": proc.stderr}
        finally:
            for t in tops.values():
                shutil.rmtree(t, ignore_errors=True)


class TestChildGuard(unittest.TestCase):
    """保存先の外への書き込み（監査 中2）を、子プロセスの見張りで捕まえる。"""

    def setUp(self):
        self.child = ChildRun(self)

    def check_clean_outputs(self, r):
        for name, data in r["files"].items():
            for mk in all_markers():
                self.assertNotIn(mk, data, (name, mk))
            self.assertEqual(privacy_scan.find_in_bytes(data), {}, name)
        for stream in (r["stdout"], r["stderr"]):
            for mk in all_markers():
                self.assertNotIn(mk, stream)

    def test_normal_run_under_guard(self):
        r = self.child("run")
        rep = r["report"]
        self.assertIsNone(rep["error"], rep)
        self.assertEqual(rep["violations"], [])
        self.assertEqual(rep["out"]["files_ok"], 4)
        self.assertEqual(r["outside"], [])
        self.assertEqual(sorted(n.split(os.sep)[0] for n in r["files"]),
                         ["home"] * 3 + ["root"])
        self.check_clean_outputs(r)

    def test_aggregate_under_guard_writes_nothing(self):
        r = self.child("aggregate")
        self.assertIsNone(r["report"]["error"], r["report"])
        self.assertEqual(r["report"]["violations"], [])
        self.assertEqual(r["report"]["out"]["docs"], 3)
        self.assertEqual(r["files"], {})

    def test_raw_zip_leak_mutation_is_caught(self):
        """監査の変異：fr.data を手放す直前に、生の zip を保存先の外へ書く。"""
        leak = ('            fr.data = None',
                '            open("OUTSIDE/raw.zip", "wb").write(fr.data)\n'
                '            fr.data = None')
        r = self.child("run", source_mutation=[leak])
        self.assertTrue(r["report"]["violations"], r["report"])
        self.assertEqual(r["report"]["violations"][0][0], "open")
        self.assertEqual(r["report"]["error"][0], "Blocked")
        self.assertEqual(r["outside"], [])
        self.check_clean_outputs(r)

    def test_leak_into_store_dir_with_other_name_is_caught(self):
        """保存先のフォルダの中でも、決まった名前以外のファイルには書けない。"""
        leak = ('            fr.data = None',
                '            open(os.path.join(os.path.dirname(log_path), "raw.zip"), "wb")'
                '.write(fr.data)\n            fr.data = None')
        r = self.child("run", source_mutation=[leak])
        self.assertTrue(r["report"]["violations"])
        self.assertEqual(r["report"]["violations"][0][0], "open")
        self.assertFalse(any(n.endswith("raw.zip") for n in r["files"]))
        self.check_clean_outputs(r)

    def test_runtime_mutations_are_caught(self):
        for name in ("fileio", "makedirs", "symlink", "subprocess", "system", "sqlite3",
                     "os_open", "open_append", "fork_exec", "getframe", "tb_frame"):
            with self.subTest(mutation=name):
                r = self.child("aggregate", mutation=name)
                self.assertTrue(r["report"]["violations"], name)
                self.assertEqual(r["outside"], [], name)


class TestNoNetworkGuard(unittest.TestCase):
    def test_guard_active(self):
        with self.assertRaises(NetworkUsed):
            socket.create_connection(("192.0.2.1", 443), timeout=1)


if __name__ == "__main__":
    unittest.main()
