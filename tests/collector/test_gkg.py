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
import stat
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
        self.assertEqual(lines[0], "#\tgkg-day\t3\t2015-03-02\tofficial")
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

EXCL_REF = {"seq": 7, "record_sha256": "e" * 64}


def fake_check_volume(volume):
    """一時的なディレクトリはマウント先でないので、マウントの検査だけを差し替える（本物は TestVolume）。"""
    st = os.lstat(volume)
    if not os.path.isdir(volume) or os.path.islink(volume):
        raise gkg.GkgError("見本：フォルダでない")
    return st.st_dev


class RunCase(unittest.TestCase):
    DAYS = ("20150302", "20150303")
    N = 4
    real_chain_ref = staticmethod(gkg.chain_exclusion_ref)

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="gkg-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.root = os.path.join(self.tmp, "proj")
        os.makedirs(os.path.join(self.root, "data", "manifest"))
        os.makedirs(os.path.join(self.root, ".git"))
        self.volume = os.path.join(self.tmp, "vol")
        self.store = os.path.join(self.volume, *gkg.STORE_PARTS)
        os.makedirs(self.store)
        self.trial_store = os.path.join(self.volume, *gkg.TRIAL_STORE_PARTS)
        os.makedirs(self.trial_store)
        self.check_volume = fake_check_volume
        self.sealed_runs = []                # start_hook に渡された値（封印の記録に書いた run）
        # 除外の規則の封印の記録（鎖の上の記録の読み取りだけを差し替える。照らす規則は本物）
        self.excl = dict(EXCL_REF)
        p = mock.patch.object(gkg, "chain_exclusion_ref", lambda root: dict(EXCL_REF))
        p.start()
        self.addCleanup(p.stop)
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

    def manifest_path(self, name=None):
        return os.path.join(self.root, "data", "manifest", name or gkg.MANIFEST_NAME)

    def start_hook(self, *, mode, run_id, trial_days):
        """封印の記録に gkg-run-start を書く入口の差し替え（本物は acquire_gkg.make_start_hook）。"""
        self.sealed_runs.append((mode, run_id, trial_days))
        return {"seq": 20 + len(self.sealed_runs), "record_sha256": "9" * 64}

    def committed_now(self):
        """作業ツリーのマニフェストの全部をコミットした、とみなしたバイト列。"""
        return gkg.read_bytes_nofollow(self.manifest_path())

    def run_once(self, **kw):
        self.transport = FakeTransport(self.responses)
        args = dict(root=self.root, volume=self.volume, filelist_rows=self.rows,
                    filelist_sha256="c" * 64, method_access_seq=5, code_sha256=CODE_SHA,
                    transport=self.transport, sleep=self.sleep, clock=self.clock,
                    now=lambda: NOW, log=self.logs.append, disk_free=self.disk_free,
                    check_volume=self.check_volume, committed_manifest=self.committed_now(),
                    committed_trial_manifest=gkg.read_bytes_nofollow(
                        self.manifest_path(gkg.TRIAL_MANIFEST_NAME)),
                    exclusion_rule=self.excl, start_hook=self.start_hook)
        args.update(kw)
        return gkg.run_gkg(**args)

    def run_gkg(self, **kw):
        """正式な run：最初は run-start を書いて止まるので、コミットしたとみなして続ける。"""
        try:
            return self.run_once(**kw)
        except gkg.RunStartWritten:
            self.assertEqual(self.transport.calls, [])
            kw.pop("committed_manifest", None)
            return self.run_once(**kw)

    def manifest(self, name=None):
        return gkg.read_jsonl(self.manifest_path(name))

    def store_path(self, name):
        return os.path.join(self.store, name)

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
        self.assertEqual([e["kind"] for e in m],
                         ["run-start", "run-resume", "day", "day", "run-complete"])
        self.assertEqual(m[0]["files_selected"], len(self.zips))
        self.assertEqual(m[0]["store_location"], "LACIE SHARE:/news-stick-data/gkg-method")
        self.assertTrue(all(e["official"] for e in m))
        self.assertEqual(done["files_ok"], len(self.zips))
        self.assertEqual(sorted(os.listdir(self.store)),
                         sorted([gkg.fetch_log_name(RUN_ID), gkg.volume_mark_name(RUN_ID)]
                                + [gkg.day_file_name(RUN_ID, "%s-%s-%s" % (d[:4], d[4:6], d[6:]))
                                   for d in self.DAYS]))
        for e in m[2:4]:
            with open(os.path.join(self.store, e["file_name"]), "rb") as f:
                self.assertEqual(hashlib.sha256(f.read()).hexdigest(), e["sha256"])
        log = [e for e in self.fetch_log() if e["result"] != "attempt"]
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
            self.assertNotIn(self.volume.encode(), data, name)
            self.assertNotIn(self.root.encode(), data, name)
            self.assertNotIn(self.tmp.encode(), data, name)

    def test_missing_file_is_recorded(self):
        ts = ts_of(self.DAYS[0], 2)
        self.responses[ts] = [FakeResponse(status=404)]
        self.run_gkg()
        log = {e["file_time"]: e for e in self.fetch_log() if e["result"] != "attempt"}
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
        log = {e["file_time"]: e for e in self.fetch_log() if e["result"] != "attempt"}
        self.assertEqual(log[ts]["reason"], "ambiguous_listing")

    def test_failed_files_are_not_retried_on_resume(self):
        """failed は再開しても取り直さない。止まった日の ok のファイルは取り直す。"""
        bad = ts_of(self.DAYS[0], 1)
        self.responses[bad] = [FakeResponse(status=404)]
        self.low_after = 2          # run-start と run-resume の確かめは通し、日の集計の前で止める
        with self.assertRaises(gkg.RunInterrupted):        # 日の集計を書く前に止まる
            self.run_gkg()
        self.assertEqual([e["kind"] for e in self.manifest()],
                         ["run-start", "run-resume", "run-stop"])
        self.responses[bad] = [ok_response(self.zips[bad])]   # 相手が直っても
        self.low_after = None
        self.run_gkg()
        self.assertNotIn(bad, self.transport.calls)          # 取り直さない
        self.assertIn(ts_of(self.DAYS[0], 0), self.transport.calls)   # ok は取り直す
        kinds = [e["kind"] for e in self.manifest()]
        self.assertEqual(kinds, ["run-start", "run-resume", "run-stop", "run-resume", "day", "day",
                                 "run-complete"])
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
        self.assertEqual([e["kind"] for e in self.manifest()],
                         ["run-start", "run-resume", "run-stop"])
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
        self.low_after = 2          # run-start と run-resume の確かめは通し、日の集計の前で止める
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
        self.low_after = 2          # run-start と run-resume の確かめは通し、日の集計の前で止める
        with self.assertRaises(gkg.RunInterrupted):
            self.run_gkg()
        self.low_after = None
        with self.assertRaisesRegex(gkg.GkgError, "filelist_sha256"):
            self.run_gkg(filelist_sha256="d" * 64)

    def test_store_checks(self):
        os.rename(self.store, self.store + "-moved")
        with self.assertRaisesRegex(gkg.GkgError, "gkg-method が無い"):
            self.run_gkg()
        os.makedirs(os.path.join(self.tmp, "else"))
        os.symlink(os.path.join(self.tmp, "else"), self.store)
        with self.assertRaisesRegex(gkg.GkgError, "シンボリックリンク"):
            self.run_gkg()
        os.rename(self.store, self.store + "-link")
        os.rename(self.store + "-moved", self.store)
        os.makedirs(os.path.join(self.volume, ".git"))
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


# --- T-021：保存先のディスク（外付け・FAT32） -------------------------------------------

class Killed(BaseException):
    """プロセスを止めたことの見本（Ctrl-C・停電）。取得のコードの except Exception に捕まらない。"""


class TestVolume(unittest.TestCase):
    """本物の check_volume（マウントと読み取り専用の検査）。一時的なディレクトリだけを使う。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="gkg-vol-")
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def test_constants(self):
        self.assertEqual(gkg.VOLUME_MOUNT, "/Volumes/LACIE SHARE")
        self.assertEqual(gkg.STORE_PARTS, ("news-stick-data", "gkg-method"))
        self.assertEqual(gkg.TRIAL_STORE_PARTS, ("news-stick-data", "gkg-trial"))
        self.assertEqual(gkg.STORE_LOCATION_NAME, "LACIE SHARE:/news-stick-data/gkg-method")
        self.assertEqual(gkg.TRIAL_STORE_LOCATION_NAME, "LACIE SHARE:/news-stick-data/gkg-trial")
        for name in (gkg.STORE_LOCATION_NAME, gkg.TRIAL_STORE_LOCATION_NAME):
            self.assertNotIn("/Volumes", name)
            self.assertNotIn("/Users", name)
        self.assertEqual(gkg.FAT32_MAX_FILE_BYTES, 4 * 1024 ** 3 - 1)

    def test_not_mounted_or_missing_or_link(self):
        with self.assertRaisesRegex(gkg.GkgError, "マウントされていない"):
            gkg.check_volume(self.tmp)                 # 普通のフォルダ（マウント先でない）
        with self.assertRaisesRegex(gkg.GkgError, "つながっていない"):
            gkg.check_volume(os.path.join(self.tmp, "none"))
        link = os.path.join(self.tmp, "link")
        os.symlink(self.tmp, link)
        with self.assertRaisesRegex(gkg.GkgError, "シンボリックリンク"):
            gkg.check_volume(link)

    def test_read_only(self):
        with mock.patch.object(gkg.os.path, "ismount", return_value=True):
            self.assertEqual(gkg.check_volume(self.tmp), os.lstat(self.tmp).st_dev)
            ro = mock.Mock(f_flag=os.ST_RDONLY)
            with mock.patch.object(gkg.os, "statvfs", return_value=ro):
                with self.assertRaisesRegex(gkg.GkgError, "読み取り専用"):
                    gkg.check_volume(self.tmp)

    def test_resolve_paths_uses_real_check(self):
        """既定の check_volume は本物：マウント先でない一時的なディレクトリでは止まる。"""
        root = os.path.join(self.tmp, "proj")
        os.makedirs(os.path.join(root, "data", "manifest"))
        os.makedirs(os.path.join(self.tmp, "vol", *gkg.STORE_PARTS))
        with self.assertRaisesRegex(gkg.GkgError, "マウントされていない"):
            gkg.resolve_paths(root, os.path.join(self.tmp, "vol"))
        with self.assertRaisesRegex(gkg.GkgError, "official か trial"):
            gkg.resolve_paths(root, os.path.join(self.tmp, "vol"), "other", fake_check_volume)

    def test_fat32_dir_entries_bound(self):
        """8章：正式な run の保存先の項目の数（付属の ._ のファイルを含む）が FAT32 の上限に収まる。"""
        days = (gkg.METHOD_BLOCK_END - gkg.DATA_START).days + 1
        self.assertEqual(days, 2115)
        names = [gkg.day_file_name("0" * 16, "2015-03-02")] * days + [gkg.fetch_log_name("0" * 16)]

        def entries(n):                 # 長い名前は13字ごとに1項目、それに短い名前の1項目
            return -(-len(n) // 13) + 1
        total = sum(entries(n) + entries("._" + n) for n in names)
        self.assertLess(total, gkg.FAT32_MAX_DIR_ENTRIES)
        for n in names[:1] + names[-1:]:
            self.assertEqual(n, n.lower())             # 大文字と小文字でぶつからない


class TestStoreGuard(RunCase):
    """保存先のディスクが外れた・読み取り専用・別のものに変わったら、書かずに止まる。"""

    def store_files(self):
        out = {}
        for n in os.listdir(self.store):
            with open(os.path.join(self.store, n), "rb") as f:
                out[n] = f.read()
        return out

    def test_unmounted_at_start_writes_nothing(self):
        def gone(v):
            raise gkg.GkgError("見本：マウントされていない")
        self.check_volume = gone
        with self.assertRaisesRegex(gkg.GkgError, "見本"):
            self.run_gkg()
        self.assertEqual(self.manifest(), [])
        self.assertEqual(os.listdir(self.store), [])

    def test_unmounted_mid_run_stops_before_writing(self):
        state = {"ok": True, "calls": 0}

        def flaky(v):
            if not state["ok"]:
                raise gkg.GkgError("見本：外れた")
            return fake_check_volume(v)
        self.check_volume = flaky
        inner = FakeTransport(self.responses)

        def transport(url, timeout):
            state["calls"] += 1
            state["ok"] = False                        # 1本目を受け取った直後に外れる
            return inner(url, timeout)
        with self.assertRaisesRegex(gkg.RunInterrupted, "外れたか"):
            self.run_gkg(transport=transport)
        self.assertEqual(state["calls"], 1)            # 2本目の要求は送らない
        log = self.fetch_log()
        self.assertEqual([e["result"] for e in log], ["attempt"])
        state["ok"] = True
        done = self.run_gkg()                          # つなぎ直して再開する
        self.assertEqual(done["files_failed"], 0)
        first = sorted(self.zips)[0]
        rec = [e for e in self.fetch_log() if e["file_time"] == first and e["result"] == "ok"]
        self.assertEqual(rec[-1]["attempts"], 2)       # 止まる前の試行を引き継いだ

    def test_store_replaced_mid_run(self):
        inner = FakeTransport(self.responses)
        moved = []

        def transport(url, timeout):
            if not moved:
                os.rename(self.store, self.store + "-old")
                os.makedirs(self.store)                # 同じ名前の別のフォルダ
                moved.append(1)
            return inner(url, timeout)
        with self.assertRaisesRegex(gkg.RunInterrupted, "違うものになった"):
            self.run_gkg(transport=transport)
        self.assertEqual(os.listdir(self.store), [])

    def test_other_device_refused(self):
        self.check_volume = lambda v: fake_check_volume(v) + 1
        with self.assertRaisesRegex(gkg.GkgError, "LACIE SHARE の上に無い"):
            self.run_gkg()
        self.assertEqual(self.manifest(), [])

    def test_case_variant_folder_refused(self):
        os.rename(self.store, os.path.join(os.path.dirname(self.store), "GKG-METHOD"))
        with self.assertRaisesRegex(gkg.GkgError, "大文字と小文字|が無い"):
            self.run_gkg()
        self.assertEqual(self.manifest(), [])

    def test_fat32_file_limit(self):
        """書けば上限を超える取得の記録は書かず、書けなければ要求も送らない。"""
        with mock.patch.object(gkg, "FAT32_MAX_FILE_BYTES", 10):
            with self.assertRaisesRegex(gkg.RunInterrupted, "FAT32"):
                self.run_gkg()
        self.assertEqual(self.transport.calls, [])
        self.assertEqual(sorted(os.listdir(self.store)), sorted([gkg.fetch_log_name(RUN_ID), gkg.volume_mark_name(RUN_ID)]))
        self.assertEqual(self.store_files()[gkg.fetch_log_name(RUN_ID)], b"")
        with mock.patch.object(gkg, "FAT32_MAX_FILE_BYTES", 10):
            with self.assertRaisesRegex(gkg.RunInterrupted, "FAT32"):
                gkg.write_new_file(self.store, "x.tsv.gz", b"a" * 11)
        self.assertFalse(os.path.exists(os.path.join(self.store, "x.tsv.gz")))

    def test_os_error_while_writing_becomes_interrupted(self):
        real = gkg.write_new_file

        def broken(store, name, data):
            raise OSError(5, "見本：入出力の誤り")
        with mock.patch.object(gkg, "write_new_file", broken):
            with self.assertRaisesRegex(gkg.RunInterrupted, "書けなかった"):
                self.run_gkg()
        self.assertIs(gkg.write_new_file, real)


class TestAttempts(RunCase):
    """T-018 の監査 軽1：試行のたびに記録を書き、再開のときに試行の回数を引き継ぐ。"""

    def attempts_of(self, ts=None):
        return [e for e in self.fetch_log()
                if e["result"] == "attempt" and (ts is None or e["file_time"] == ts)]

    def test_attempt_line_written_before_every_request(self):
        bad = ts_of(self.DAYS[0], 1)
        self.responses[bad] = [FakeResponse(status=503), ok_response(self.zips[bad])]
        inner = FakeTransport(self.responses)
        seen = []

        def transport(url, timeout):
            ts = url.rsplit("/", 1)[1][:14]
            last = self.fetch_log()[-1]
            seen.append((last["result"], last["file_time"], last["attempt"]))
            return inner(url, timeout)
        self.run_gkg(transport=transport)
        self.assertEqual(len(seen), len(inner.calls))
        n = {}
        for (result, ft, attempt), ts in zip(seen, inner.calls):
            n[ts] = n.get(ts, 0) + 1
            self.assertEqual((result, ft, attempt), ("attempt", ts, n[ts]))
        self.assertEqual(len(self.attempts_of()), len(inner.calls))

    def test_kill_during_retry_wait_keeps_count(self):
        bad = sorted(self.zips)[0]
        self.responses[bad] = [FakeResponse(status=503)]

        def sleep_kill(s):
            if s == gkg.RETRY_WAIT_SECONDS[0]:
                raise Killed()                         # 再試行を待っているあいだに止める
            self.clock.t += s
        with self.assertRaises(Killed):
            self.run_gkg(sleep=sleep_kill)
        self.assertEqual(len(self.attempts_of(bad)), 1)
        waits = []

        def sleep_rec(s):
            waits.append(s)
            self.clock.t += s
        self.run_gkg(sleep=sleep_rec)                  # 相手は直っていない
        self.assertEqual(self.transport.calls.count(bad), gkg.MAX_ATTEMPTS_PER_FILE - 1)
        self.assertEqual(len(self.attempts_of(bad)), gkg.MAX_ATTEMPTS_PER_FILE)
        rec = [e for e in self.fetch_log() if e["file_time"] == bad and e["result"] == "failed"]
        self.assertEqual(rec[-1]["attempts"], gkg.MAX_ATTEMPTS_PER_FILE)
        self.assertEqual(waits[0], gkg.RETRY_WAIT_SECONDS[0])   # 引き継いだ待ち時間を待つ

    def test_exhausted_attempts_are_not_requested_again(self):
        bad = sorted(self.zips)[0]
        inner = FakeTransport(self.responses)
        n = [0]

        def transport(url, timeout):
            if url.rsplit("/", 1)[1][:14] == bad:
                n[0] += 1
                if n[0] == gkg.MAX_ATTEMPTS_PER_FILE:
                    raise Killed()                     # 最後の試行の途中で止める
                return FakeResponse(status=503)
            return inner(url, timeout)
        with self.assertRaises(Killed):
            self.run_gkg(transport=transport)
        self.assertEqual(len(self.attempts_of(bad)), gkg.MAX_ATTEMPTS_PER_FILE)
        self.run_gkg()
        self.assertNotIn(bad, self.transport.calls)
        rec = [e for e in self.fetch_log() if e["file_time"] == bad and e["result"] == "failed"]
        self.assertEqual((rec[-1]["reason"], rec[-1]["attempts"]),
                         ("attempts_exhausted", gkg.MAX_ATTEMPTS_PER_FILE))

    def test_interrupted_resets_count_once(self):
        """interrupted（1回だけの取り直し）のあとは、試行の回数を 0 から数える。"""
        times = sorted(self.zips)
        for ts in times[:gkg.MAX_CONSECUTIVE_TRANSIENT_FAILURES]:
            self.responses[ts] = [FakeResponse(status=503)]
        with self.assertRaises(gkg.RunInterrupted):
            self.run_gkg()
        for ts in times:
            self.responses[ts] = [ok_response(self.zips[ts])]
        self.run_gkg()
        self.assertEqual(self.transport.calls.count(times[0]), 1)
        self.assertEqual(len(self.attempts_of(times[0])), gkg.MAX_ATTEMPTS_PER_FILE + 1)

    def test_fetch_file_used_argument(self):
        data = self.zips[sorted(self.zips)[0]]
        entry = {"file_time": sorted(self.zips)[0], "size": len(data),
                 "md5": hashlib.md5(data).hexdigest(), "ambiguous": False}
        tr = FakeTransport({entry["file_time"]: [FakeResponse(status=503)]})
        got = []
        r = gkg.fetch_file(entry, tr, self.sleep, self.clock, gkg.Pacer(self.clock, self.sleep),
                           lambda m: None, used=gkg.MAX_ATTEMPTS_PER_FILE)
        self.assertEqual((r.result, r.reason, tr.calls), ("failed", "attempts_exhausted", []))
        r = gkg.fetch_file(entry, tr, self.sleep, self.clock, gkg.Pacer(self.clock, self.sleep),
                           lambda m: None, used=1, on_attempt=got.append)
        self.assertEqual(got, [2, 3])
        self.assertEqual(r.attempts, gkg.MAX_ATTEMPTS_PER_FILE)


class TestRunStartCommit(RunCase):
    """T-018 の監査 軽2：正式な run の run-start は、コミットしてからでないと取得を始めない。"""

    def test_first_run_writes_start_and_stops(self):
        with self.assertRaises(gkg.RunStartWritten):
            self.run_once()
        self.assertEqual(self.transport.calls, [])
        self.assertEqual([e["kind"] for e in self.manifest()], ["run-start"])
        self.assertTrue(self.manifest()[0]["official"])
        self.assertEqual(os.listdir(self.store), [gkg.volume_mark_name(RUN_ID)])

    def test_uncommitted_or_rewritten_start_refused(self):
        with self.assertRaises(gkg.RunStartWritten):
            self.run_once(committed_manifest=b"")
        data = self.committed_now()
        for committed, pattern in ((b"", "コミットされていない"), (None, "受け取っていない"),
                                   (data.replace(b"run-start", b"run-xtart"), "書き換わっている"),
                                   (data[:-1], "改行")):
            with self.subTest(committed=committed and committed[:10]):
                with self.assertRaisesRegex(gkg.GkgError, pattern):
                    self.run_once(committed_manifest=committed)
                self.assertEqual(self.transport.calls, [])
        self.assertEqual([e["kind"] for e in self.manifest()], ["run-start"])
        self.assertEqual(os.listdir(self.store), [gkg.volume_mark_name(RUN_ID)])
        done = self.run_once(committed_manifest=data)
        self.assertEqual(done["files_ok"], len(self.zips))

    def test_deleting_first_start_after_commit_is_refused(self):
        with self.assertRaises(gkg.RunStartWritten):
            self.run_once()
        committed = self.committed_now()
        with open(self.manifest_path(), "wb") as f:     # コミットのあとで消して作り直す
            f.write(b"")
        with self.assertRaisesRegex(gkg.GkgError, "決まった名前でない"):   # 前の run の印が残る
            self.run_once(committed_manifest=b"", code_sha256="cd" * 32)
        os.rename(self.store_path(gkg.volume_mark_name(RUN_ID)),
                  os.path.join(self.tmp, "mark-aside"))       # 印も保存先の外へ移した場合
        with self.assertRaises(gkg.RunStartWritten):
            self.run_once(committed_manifest=b"", code_sha256="cd" * 32)
        with self.assertRaisesRegex(gkg.GkgError, "書き換わっている"):
            self.run_once(committed_manifest=committed, code_sha256="cd" * 32)

    def test_check_committed_start_unit(self):
        line = (json.dumps({"kind": "run-start", "run_id": RUN_ID}) + "\n").encode()
        other = (json.dumps({"kind": "run-resume"}) + "\n").encode()
        gkg.check_committed_start(line + other, line)
        gkg.check_committed_start(line, line)
        for m, c in ((line, b""), (line + other, other), (other, other)):
            with self.assertRaises(gkg.GkgError):
                gkg.check_committed_start(m, c)


class TestTrial(RunCase):
    """5.1章：試しの run。日・保存先・マニフェストが別で、正式な run の判定に数えない。"""

    DAYS = ("20150302", "20150303", "20150304", "20150305")
    N = 2

    def run_trial(self, **kw):
        kw.setdefault("committed_manifest", None)
        return self.run_once(mode="trial", **kw)

    def test_trial_then_official(self):
        done = self.run_trial()
        self.assertEqual(sorted({c[:8] for c in self.transport.calls}),
                         ["20150302", "20150303", "20150304"])
        tm = self.manifest(gkg.TRIAL_MANIFEST_NAME)
        self.assertEqual([e["kind"] for e in tm], ["run-start", "day", "day", "day",
                                                   "run-complete"])
        self.assertTrue(all(e["official"] is False for e in tm))
        self.assertEqual(tm[0]["trial"], True)
        self.assertEqual(tm[0]["trial_days"], list(gkg.TRIAL_DAYS))
        self.assertEqual(tm[0]["store_location"], "LACIE SHARE:/news-stick-data/gkg-trial")
        self.assertEqual(done["days"], 3)
        self.assertFalse(os.path.exists(self.manifest_path()))   # 正式な run には何も書かない
        self.assertEqual(os.listdir(self.store), [])
        self.assertEqual(len([n for n in os.listdir(self.trial_store) if "-day-" in n]), 3)
        self.assertIsNone(gkg.official_run_id(self.manifest()))
        out = self.run_gkg()                                      # 正式な run は全部の日を取る
        self.assertEqual(out["days"], len(self.DAYS))
        self.assertEqual(sorted(set(self.transport.calls)), sorted(self.zips))
        m = self.manifest()
        self.assertEqual(gkg.official_run_id(m), RUN_ID)
        self.assertTrue(m[0]["official"])
        self.assertNotIn("trial", m[0])
        with self.assertRaisesRegex(gkg.GkgError, "試しの run はしない"):
            self.run_trial()                                      # 正式な run のあとは試さない

    def test_trial_refused_after_official_start(self):
        with self.assertRaises(gkg.RunStartWritten):
            self.run_once()
        with self.assertRaisesRegex(gkg.GkgError, "試しの run はしない"):
            self.run_trial()
        self.assertFalse(os.path.exists(self.manifest_path(gkg.TRIAL_MANIFEST_NAME)))
        self.assertEqual(os.listdir(self.trial_store), [])

    def test_trial_needs_its_own_folder(self):
        os.rename(self.trial_store, self.trial_store + "-x")
        with self.assertRaisesRegex(gkg.GkgError, "gkg-trial が無い"):
            self.run_trial()
        self.assertEqual(self.transport.calls, [])

    def test_trial_days_are_first_three_days_of_method_block(self):
        first = [(gkg.DATA_START + datetime.timedelta(days=i)).isoformat() for i in range(3)]
        self.assertEqual(gkg.TRIAL_DAYS, tuple(first))
        for d in gkg.TRIAL_DAYS:
            self.assertTrue(gkg.METHOD_BLOCK[0] <= d <= gkg.METHOD_BLOCK[1])
        plan = {d: [] for d in ("2015-03-02", "2015-03-03", "2015-03-04", "2015-03-05",
                                "2020-12-14")}
        self.assertEqual(list(gkg.trial_plan(plan)), list(gkg.TRIAL_DAYS))
        with mock.patch.object(gkg, "TRIAL_DAYS", ("2020-12-15",)):
            with self.assertRaisesRegex(gkg.GkgError, "期間の外"):
                gkg.trial_plan(plan)


class TestLogCheckpoint(RunCase):
    """差し戻し1回目 中1：run と run のあいだの取得の記録の書き換えを見つける。"""

    def log_path(self, mode="official"):
        folder = self.store if mode == "official" else self.trial_store
        return os.path.join(folder, gkg.fetch_log_name(RUN_ID, mode))

    def test_deleting_failed_line_between_runs_is_refused(self):
        bad = ts_of(self.DAYS[0], 1)
        self.responses[bad] = [FakeResponse(status=404)]
        self.low_after = 2                     # 日の集計を書く前に止まる（run-stop を書く）
        with self.assertRaises(gkg.RunInterrupted):
            self.run_gkg()
        self.assertEqual(self.manifest()[-1]["kind"], "run-stop")
        with open(self.log_path(), "rb") as f:
            lines = f.read().splitlines(keepends=True)
        kept = [l for l in lines if not (bad.encode() in l and b'"failed"' in l)]
        self.assertLess(len(kept), len(lines))
        with open(self.log_path(), "wb") as f:  # failed の行を消す（取り直させる書き換え）
            f.write(b"".join(kept))
        self.low_after = None
        self.responses[bad] = [ok_response(self.zips[bad])]
        with self.assertRaisesRegex(gkg.GkgError, "書き換わっている"):
            self.run_gkg()
        self.assertEqual(self.transport.calls, [])

    def test_deleted_log_is_refused(self):
        self.low_after = 2
        with self.assertRaises(gkg.RunInterrupted):
            self.run_gkg()
        os.rename(self.log_path(), os.path.join(self.tmp, "log-aside"))   # 保存先の外へ
        self.low_after = None
        with self.assertRaisesRegex(gkg.GkgError, "書き換わっている"):
            self.run_gkg()

    def test_every_checkpoint_matches_log_prefix(self):
        bad = sorted(self.zips)[0]
        self.responses[bad] = [FakeResponse(status=503), ok_response(self.zips[bad])]
        self.run_gkg()
        with open(self.log_path(), "rb") as f:
            data = f.read()
        marks = [e for e in self.manifest() if "fetch_log_size" in e]
        self.assertEqual([e["kind"] for e in marks],
                         ["run-start", "run-resume", "day", "day", "run-complete"])
        for e in marks:
            self.assertEqual(hashlib.sha256(data[:e["fetch_log_size"]]).hexdigest(),
                             e["fetch_log_sha256"], e["kind"])
        self.assertEqual(marks[-1]["fetch_log_size"], len(data))

    def test_log_before_run_start_is_refused(self):
        with open(self.log_path(), "wb") as f:
            f.write(b"")
        with self.assertRaisesRegex(gkg.GkgError, "run-start の前なのに"):
            self.run_gkg()
        self.assertEqual(self.manifest(), [])


class TestModeMarks(RunCase):
    """差し戻し1回目 中2：試しの run と正式な run を、名前と行の mode で分ける。"""

    DAYS = ("20150302", "20150303")
    N = 2

    def test_names_and_lines_carry_mode(self):
        self.run_once(mode="trial", committed_manifest=None)
        names = sorted(os.listdir(self.trial_store))
        self.assertEqual(names, sorted([gkg.fetch_log_name(RUN_ID, "trial"), gkg.volume_mark_name(RUN_ID, "trial")]
                                       + [gkg.day_file_name(RUN_ID, d, "trial")
                                          for d in ("2015-03-02", "2015-03-03")]))
        for n in names:
            self.assertTrue(n.startswith("gkg-trial-"), n)
        log = gkg.read_jsonl(os.path.join(self.trial_store, gkg.fetch_log_name(RUN_ID, "trial")))
        self.assertTrue(all(e["mode"] == "trial" for e in log))
        self.assertTrue(all(e["mode"] == "trial" for e in self.manifest(gkg.TRIAL_MANIFEST_NAME)))
        with open(os.path.join(self.trial_store, names[0]), "rb") as f:
            head = gzip.decompress(f.read()).split(b"\n", 1)[0]
        self.assertEqual(head, b"#\tgkg-day\t3\t2015-03-02\ttrial")
        self.run_gkg()
        self.assertTrue(all(n.startswith("gkg-official-") for n in os.listdir(self.store)))
        with self.assertRaises(gkg.GkgError):
            gkg.day_file_name(RUN_ID, "2015-03-02", "other")

    def test_trial_log_copied_into_official_is_refused(self):
        self.run_once(mode="trial", committed_manifest=None)
        with self.assertRaises(gkg.RunStartWritten):
            self.run_once()
        with open(os.path.join(self.trial_store, gkg.fetch_log_name(RUN_ID, "trial")), "rb") as f:
            trial_log = f.read()
        with open(os.path.join(self.store, gkg.fetch_log_name(RUN_ID)), "wb") as f:
            f.write(trial_log)                         # 試しの run の記録を写す
        with self.assertRaisesRegex(gkg.GkgError, "足した行"):
            self.run_once()
        self.assertEqual(self.transport.calls, [])


class TestTrialRecordInOfficial(RunCase):
    """差し戻し1回目 中4：試しの run の回数と範囲を、正式な run の run-start に記録して照らす。"""

    DAYS = ("20150302",)
    N = 2

    def test_uncommitted_trial_manifest_refused(self):
        self.run_once(mode="trial", committed_manifest=None)
        with self.assertRaisesRegex(gkg.GkgError, "試しの run のマニフェストが、全部コミット"):
            self.run_once(committed_trial_manifest=b"")
        self.assertFalse(os.path.exists(self.manifest_path()))
        with self.assertRaises(gkg.GkgError):
            self.run_once(committed_trial_manifest=None)

    def test_run_start_records_trials(self):
        self.run_once(mode="trial", committed_manifest=None)
        self.run_once(mode="trial", committed_manifest=None, code_sha256="cd" * 32)
        with open(self.manifest_path(gkg.TRIAL_MANIFEST_NAME), "rb") as f:
            trial_bytes = f.read()
        with self.assertRaises(gkg.RunStartWritten):
            self.run_once()
        s0 = self.manifest()[0]
        self.assertEqual(s0["trial_run_ids"], [RUN_ID, "cd" * 8])
        self.assertEqual(s0["trial_manifest_sha256"], hashlib.sha256(trial_bytes).hexdigest())
        with open(self.manifest_path(gkg.TRIAL_MANIFEST_NAME), "ab") as f:
            f.write(b'{"kind": "x"}\n')                # 正式な run が始まったあとで変える
        with self.assertRaisesRegex(gkg.GkgError, "試しの run のマニフェスト"):
            self.run_once()
        self.assertEqual(self.transport.calls, [])

    def test_no_trial(self):
        with self.assertRaises(gkg.RunStartWritten):
            self.run_once()
        s0 = self.manifest()[0]
        self.assertEqual((s0["trial_run_ids"], s0["trial_manifest_sha256"]), ([], None))


class TestVolumeIdAndEmptyFile(RunCase):
    """差し戻し1回目 軽3：ディスクの識別子を実行をまたいで照らす。0バイトの日の集計の扱い。"""

    def mark_path(self, mode="official"):
        folder = self.store if mode == "official" else self.trial_store
        return os.path.join(folder, gkg.volume_mark_name(RUN_ID, mode))

    def test_mark_written_but_not_recorded(self):
        """オーナーの決定：ディスクの印は保存先にだけ置き、記録には値もハッシュも書かない。"""
        with self.assertRaises(gkg.RunStartWritten):
            self.run_once()
        with open(self.mark_path(), "rb") as f:
            mark = f.read()
        self.assertRegex(mark, rb"\A[0-9a-f]{64}\n\Z")
        self.run_once()
        token = mark.strip()
        digests = [hashlib.sha256(x).hexdigest().encode() for x in (mark, token)]
        for name, data in self.written().items():
            if name == self.mark_path():
                continue
            self.assertNotIn(token, data, name)
            for d in digests:
                self.assertNotIn(d, data, name)
            self.assertNotIn(b"volume_id", data, name)
            self.assertNotIn(b"VolumeUUID", data, name)
            self.assertNotIn(b"TEST-VOLUME", data, name)

    def test_other_disk_without_mark_refused_on_resume(self):
        with self.assertRaises(gkg.RunStartWritten):
            self.run_once()
        os.rename(self.mark_path(), os.path.join(self.tmp, "mark-aside"))   # 別のディスクの形
        with self.assertRaisesRegex(gkg.GkgError, "印のファイルが無い"):
            self.run_once()
        self.assertEqual(self.transport.calls, [])

    def test_bad_mark_refused(self):
        with self.assertRaises(gkg.RunStartWritten):
            self.run_once()
        with open(self.mark_path(), "wb") as f:
            f.write(b"x\n")
        with self.assertRaisesRegex(gkg.GkgError, "印のファイルの形"):
            self.run_once()
        os.rename(self.mark_path(), os.path.join(self.tmp, "mark-aside"))
        os.symlink(self.mark_path() + "-elsewhere", self.mark_path())
        with self.assertRaisesRegex(gkg.GkgError, "決まった名前でない"):   # リンクは一覧で止まる
            self.run_once()

    def test_existing_mark_before_start_refused(self):
        with open(self.mark_path(), "wb") as f:
            f.write(b"0" * 64 + b"\n")
        with self.assertRaisesRegex(gkg.GkgError, "印のファイルが既にある"):
            self.run_once()
        self.assertEqual(self.manifest(), [])

    def test_empty_day_file_is_filled_not_replaced(self):
        name = gkg.day_file_name(RUN_ID, "2015-03-02")
        open(os.path.join(self.store, name), "wb").close()     # 作った直後に止まった跡
        self.run_gkg()
        day = [e for e in self.manifest() if e.get("kind") == "day"]
        self.assertTrue(day[0]["refilled_empty_file"])
        self.assertNotIn("refilled_empty_file", day[1])
        with open(os.path.join(self.store, name), "rb") as f:
            self.assertEqual(hashlib.sha256(f.read()).hexdigest(), day[0]["sha256"])

    def test_write_new_file_cases(self):
        self.assertEqual(gkg.write_new_file(self.store, "a.gz", b"abc")[1], False)
        self.assertEqual(gkg.write_new_file(self.store, "a.gz", b"abc")[1], False)
        with self.assertRaisesRegex(gkg.GkgError, "中身の違う"):
            gkg.write_new_file(self.store, "a.gz", b"abd")
        open(os.path.join(self.store, "b.gz"), "wb").close()
        sha, refilled = gkg.write_new_file(self.store, "b.gz", b"xyz")
        self.assertTrue(refilled)
        self.assertEqual(sha, hashlib.sha256(b"xyz").hexdigest())
        with open(os.path.join(self.store, "c.gz"), "wb") as f:
            f.write(b"x")                              # 途中まで書かれた（中身がある）
        with self.assertRaisesRegex(gkg.GkgError, "中身の違う"):
            gkg.write_new_file(self.store, "c.gz", b"xyz")


class TestAuditReproductions(RunCase):
    """差し戻し2回目：監査係の再現（scratchpad/exp）が、どれも止まること。"""

    DAYS = ("20150302", "20150303")
    N = 3

    def lp(self, mode="official"):
        folder = self.store if mode == "official" else self.trial_store
        return os.path.join(folder, gkg.fetch_log_name(RUN_ID, mode))

    def test_X1_trial_log_with_mode_rewritten_is_refused(self):
        bad = ts_of(self.DAYS[0], 1)
        self.responses[bad] = [FakeResponse(status=404)]
        self.run_once(mode="trial", committed_manifest=None)
        with self.assertRaises(gkg.RunStartWritten):
            self.run_once()
        with open(self.lp("trial"), "rb") as f:
            data = f.read().replace(b'"mode": "trial"', b'"mode": "official"')
        with open(self.lp(), "wb") as f:
            f.write(data)
        self.responses[bad] = [ok_response(self.zips[bad])]
        with self.assertRaisesRegex(gkg.GkgError, "足した行"):
            self.run_once()
        self.assertEqual(self.transport.calls, [])

    def test_X2_forged_failed_line_after_stop_is_refused(self):
        self.low_after = 2
        with self.assertRaises(gkg.RunInterrupted):
            self.run_gkg()
        self.assertEqual(self.manifest()[-1]["kind"], "run-stop")
        target = ts_of(self.DAYS[1], 2)
        forged = {"run_id": RUN_ID, "mode": "official", "file_time": target, "listed_md5": "0" * 32,
                  "listed_size": 1, "result": "failed", "reason": "http_404", "transient": False,
                  "attempts": 1, "sha256": None, "docs": {}, "stats": {}}
        with open(self.lp(), "ab") as f:
            f.write((json.dumps(forged) + "\n").encode())
        self.low_after = None
        with self.assertRaisesRegex(gkg.GkgError, "足した行"):
            self.run_gkg()
        self.assertEqual(self.transport.calls, [])

    def test_X3_deleting_tail_after_crash_is_refused(self):
        bad = ts_of(self.DAYS[0], 1)
        self.responses[bad] = [FakeResponse(status=404)]
        inner = FakeTransport(self.responses)

        def transport(url, timeout):
            if ts_of(self.DAYS[0], 2) in url:
                raise Killed()
            return inner(url, timeout)
        with self.assertRaises(Killed):
            self.run_gkg(transport=transport)
        self.assertEqual(self.manifest()[-1]["kind"], "run-stop")   # Killed でも控えを書く
        with open(self.lp(), "rb") as f:
            lines = f.read().splitlines(keepends=True)
        with open(self.lp(), "wb") as f:
            f.write(b"".join(l for l in lines if not (bad.encode() in l and b'"failed"' in l)))
        self.responses[bad] = [ok_response(self.zips[bad])]
        with self.assertRaisesRegex(gkg.GkgError, "書き換わっている"):
            self.run_gkg()
        self.assertEqual(self.transport.calls, [])

    def test_X4_uncommitted_checkpoint_edit_is_refused(self):
        bad = ts_of(self.DAYS[0], 1)
        self.responses[bad] = [FakeResponse(status=404)]
        self.low_after = 2
        with self.assertRaises(gkg.RunInterrupted):
            self.run_gkg()
        first = self.committed_now().splitlines(keepends=True)[0]   # コミットしたのは run-start だけ
        with open(self.lp(), "rb") as f:
            lines = f.read().splitlines(keepends=True)
        kept = b"".join(l for l in lines if not (bad.encode() in l and b'"failed"' in l))
        with open(self.lp(), "wb") as f:
            f.write(kept)
        m = self.manifest()
        m[-1]["fetch_log_size"] = len(kept)
        m[-1]["fetch_log_sha256"] = hashlib.sha256(kept).hexdigest()
        with open(self.manifest_path(), "w") as f:
            for e in m:
                f.write(json.dumps(e, sort_keys=True) + "\n")
        self.low_after = None
        self.responses[bad] = [ok_response(self.zips[bad])]
        with self.assertRaisesRegex(gkg.GkgError, "コミットしていない行"):
            self.run_once(committed_manifest=first)
        self.assertEqual(self.transport.calls, [])

    def test_resume_requires_whole_manifest_committed(self):
        self.low_after = 2
        with self.assertRaises(gkg.RunInterrupted):
            self.run_gkg()
        partial = b"".join(self.committed_now().splitlines(keepends=True)[:2])
        with self.assertRaisesRegex(gkg.GkgError, "コミットしていない行"):
            self.run_once(committed_manifest=partial)
        self.low_after = None
        self.run_gkg()                                  # 全部コミットしたとみなせば続く

    def test_tail_after_crash_is_not_trusted(self):
        """控えを書けずに止まった跡（kill -9 など）の、控えより後ろの結果の行は信用しない。"""
        bad = ts_of(self.DAYS[1], 0)
        self.responses[bad] = [FakeResponse(status=404)]
        inner = FakeTransport(self.responses)

        def transport(url, timeout):
            if ts_of(self.DAYS[1], 2) in url:
                raise Killed()
            return inner(url, timeout)
        with self.assertRaises(Killed):
            self.run_gkg(transport=transport)
        m = self.manifest()
        self.assertEqual(m[-1]["kind"], "run-stop")
        with open(self.manifest_path(), "w") as f:      # kill -9 で run-stop が書けなかった形
            for e in m[:-1]:
                f.write(json.dumps(e, sort_keys=True) + "\n")
        self.assertEqual(self.manifest()[-1]["kind"], "day")
        self.responses[bad] = [ok_response(self.zips[bad])]
        done = self.run_gkg()
        self.assertIn(bad, self.transport.calls)        # 控えの後ろの failed は取り直す
        self.assertEqual(done["files_failed"], 0)

    def test_tail_attempts_still_count(self):
        bad = ts_of(self.DAYS[1], 0)
        self.responses[bad] = [FakeResponse(status=503)]

        def sleep_kill(s):
            if s == gkg.RETRY_WAIT_SECONDS[0]:
                raise Killed()
            self.clock.t += s
        with self.assertRaises(Killed):
            self.run_gkg(sleep=sleep_kill)
        m = self.manifest()
        with open(self.manifest_path(), "w") as f:      # run-stop が書けなかった形
            for e in m[:-1]:
                f.write(json.dumps(e, sort_keys=True) + "\n")
        self.run_gkg()
        self.assertEqual(self.transport.calls.count(bad), gkg.MAX_ATTEMPTS_PER_FILE - 1)

    def test_other_mode_line_in_tail_is_refused(self):
        inner = FakeTransport(self.responses)

        def transport(url, timeout):
            if ts_of(self.DAYS[1], 1) in url:
                raise Killed()
            return inner(url, timeout)
        with self.assertRaises(Killed):
            self.run_gkg(transport=transport)
        m = self.manifest()
        with open(self.manifest_path(), "w") as f:
            for e in m[:-1]:
                f.write(json.dumps(e, sort_keys=True) + "\n")
        with open(self.lp(), "ab") as f:
            f.write((json.dumps({"run_id": RUN_ID, "mode": "trial", "file_time": ts_of(
                self.DAYS[1], 2), "result": "attempt", "attempt": 1}) + "\n").encode())
        with self.assertRaisesRegex(gkg.GkgError, "別の mode"):
            self.run_gkg()

    def test_run_stop_written_on_gkg_error(self):
        """差し戻し2回目 軽-6：GkgError で止まっても run-stop を書く。"""
        with mock.patch.object(gkg, "serialize_day", side_effect=gkg.GkgError("見本")):
            with self.assertRaisesRegex(gkg.GkgError, "見本"):
                self.run_gkg()
        last = self.manifest()[-1]
        self.assertEqual(last["kind"], "run-stop")
        size, sha = gkg._log_state(self.lp())
        self.assertEqual((last["fetch_log_size"], last["fetch_log_sha256"]), (size, sha))


class TestHiddenTrial(RunCase):
    """差し戻し2回目 中-C：コミットの前に試しの run のマニフェストの行を消しても、正式な run は止まる。"""

    DAYS = ("20150302",)
    N = 2

    def test_hidden_trial_run_is_refused(self):
        self.run_once(mode="trial", committed_manifest=None)                  # コード A
        open(self.manifest_path(gkg.TRIAL_MANIFEST_NAME), "w").close()       # コミット前に消す
        self.run_once(mode="trial", committed_manifest=None, code_sha256="cd" * 32)  # コード B
        with self.assertRaisesRegex(gkg.GkgError, "マニフェストに載っていない run"):
            self.run_once()
        self.assertFalse(os.path.exists(self.manifest_path()))

    def test_trial_log_must_match_manifest(self):
        self.run_once(mode="trial", committed_manifest=None)
        with open(os.path.join(self.trial_store, gkg.fetch_log_name(RUN_ID, "trial")), "ab") as f:
            f.write(b'{"x": 1}\n')
        with self.assertRaisesRegex(gkg.GkgError, "控えと合わない"):
            self.run_once()

    def test_unknown_file_in_trial_folder_is_refused(self):
        with open(os.path.join(self.trial_store, "raw.zip"), "wb") as f:
            f.write(b"x")
        with self.assertRaisesRegex(gkg.GkgError, "決まった名前でない"):
            self.run_once()

    def test_only_appledouble_of_known_names_is_allowed(self):
        """差し戻し3回目 中-2：飛ばすのは「._」に決まった名前を続けたものだけ。"""
        ok = "._" + gkg.fetch_log_name(RUN_ID, "trial")
        with open(os.path.join(self.trial_store, ok), "wb") as f:
            f.write(b"x")                                  # macOS の付属のファイルの形
        with self.assertRaises(gkg.RunStartWritten):
            self.run_once()

    def test_other_dot_names_and_folders_are_refused(self):
        for make in (lambda p: open(os.path.join(p, "._gkg-trial-x"), "wb").close(),
                     lambda p: open(os.path.join(p, "." + gkg.fetch_log_name(RUN_ID, "trial")),
                                    "wb").close(),
                     lambda p: os.mkdir(os.path.join(p, ".old"))):
            with self.subTest():
                self.tearDown_dir = tempfile.mkdtemp(prefix="gkg-dot-", dir=self.tmp)
                store = os.path.join(self.tearDown_dir, "vol", *gkg.TRIAL_STORE_PARTS)
                os.makedirs(store)
                os.makedirs(os.path.join(self.tearDown_dir, "vol", *gkg.STORE_PARTS))
                make(store)
                with self.assertRaisesRegex(gkg.GkgError, "決まった名前でない"):
                    self.run_once(volume=os.path.join(self.tearDown_dir, "vol"))


class TestExclusionRecord(RunCase):
    """差し戻し2回目 中-B：除外の規則の封印の記録を run-start に書き、run_gkg の中でも照らす。"""

    def test_recorded_in_run_start(self):
        with self.assertRaises(gkg.RunStartWritten):
            self.run_once()
        s0 = self.manifest()[0]
        self.assertEqual((s0["exclusion_rule_seq"], s0["exclusion_rule_record_sha256"]),
                         (7, "e" * 64))

    def test_missing_or_wrong_record_is_refused(self):
        for ref, pattern in ((None, "受け取っていない"), ({"seq": 7}, "受け取っていない"),
                             ({"seq": 8, "record_sha256": "e" * 64}, "鎖の上の記録と違う")):
            with self.subTest(ref=ref):
                with self.assertRaisesRegex(gkg.GkgError, pattern):
                    self.run_once(exclusion_rule=ref)
        self.assertEqual(self.manifest(), [])

    def test_changed_chain_record_refused_on_resume(self):
        with self.assertRaises(gkg.RunStartWritten):
            self.run_once()
        other = {"seq": 9, "record_sha256": "d" * 64}
        with mock.patch.object(gkg, "chain_exclusion_ref", lambda root: dict(other)):
            with self.assertRaisesRegex(gkg.GkgError, "run-start に書いたものと違う"):
                self.run_once(exclusion_rule=other)
        self.assertEqual(self.transport.calls, [])

    def test_real_chain_check_stops_without_order1_record(self):
        """関門を通らずに run_gkg を直接呼んでも、本物の封印の記録に stats-order1 が無いあいだは
        何も書かずに止まる（T-032：kind は stats-order1 に決まった）。"""
        with mock.patch.object(gkg, "chain_exclusion_ref", RunCase.real_chain_ref):
            with self.assertRaisesRegex(gkg.GkgError, "stats-order1）が無い"):
                self.run_once()
        self.assertEqual(self.sealed_runs, [])
        self.assertEqual(self.manifest(), [])


class Kill9(BaseException):
    """kill -9 の見本。run-stop も書かれない（_write_stop を外して使う）。"""


class _ForgeMixin:
    """監査の再現で使う部品（取得の記録への偽の行、kill -9 の見本）。"""

    def lp(self):
        return os.path.join(self.store, gkg.fetch_log_name(RUN_ID))

    def forged(self, ft, result="failed"):
        return {"run_id": RUN_ID, "mode": "official", "file_time": ft, "listed_md5": "0" * 32,
                "listed_size": 1, "result": result, "reason": "http_404", "transient": False,
                "attempts": 1, "sha256": None, "docs": {}, "stats": {},
                "finished_at": "2026-10-08T00:00:00Z"}

    def append_log(self, *objs):
        with open(self.lp(), "ab") as f:
            for o in objs:
                f.write((json.dumps(o) + "\n").encode())

    def kill_at(self, boom):
        inner = FakeTransport(self.responses)

        def transport(url, timeout):
            if boom in url:
                raise Kill9()
            return inner(url, timeout)
        with mock.patch.object(gkg, "_write_stop", lambda *a, **k: None):
            with self.assertRaises(Kill9):
                self.run_gkg(transport=transport)


class TestRound3Reproductions(_ForgeMixin, RunCase):
    """差し戻し3回目：監査係の再現（scratchpad/exp4）。止まるものと、止まらずに記録に残るもの。"""

    DAYS = ("20150302", "20150303", "20150304")
    N = 3

    def test_Y1_forged_failed_in_tail_is_not_laundered_by_two_resumes(self):
        target = ts_of(self.DAYS[2], 1)
        self.kill_at(ts_of(self.DAYS[1], 0))
        self.assertEqual(self.manifest()[-1]["kind"], "day")
        self.append_log(self.forged(target))
        self.free_calls, self.low_after = 0, 1             # 再開1：すぐ止まる
        with self.assertRaises(gkg.RunInterrupted):
            self.run_once()
        resume = [e for e in self.manifest() if e["kind"] == "run-resume"][-1]
        self.assertEqual(len(resume["untrusted_ranges"]), 1)
        self.low_after = None
        done = self.run_once()                               # 再開2
        self.assertIn(target, self.transport.calls)          # 偽の failed は使われない
        self.assertEqual(done["files_failed"], 0)

    def test_two_resumes_keep_ranges(self):
        self.kill_at(ts_of(self.DAYS[1], 0))
        self.append_log(self.forged(ts_of(self.DAYS[2], 0)))
        with mock.patch.object(gkg, "_write_stop", lambda *a, **k: None), \
                mock.patch.object(gkg, "_run_plan", side_effect=Kill9()):
            with self.assertRaises(Kill9):                  # 再開1：run-resume のあと kill -9
                self.run_once()
        self.append_log(self.forged(ts_of(self.DAYS[2], 1)))
        with mock.patch.object(gkg, "_write_stop", lambda *a, **k: None), \
                mock.patch.object(gkg, "_run_plan", side_effect=Kill9()):
            with self.assertRaises(Kill9):                  # 再開2
                self.run_once()
        ranges = [e for e in self.manifest() if e["kind"] == "run-resume"][-1]["untrusted_ranges"]
        self.assertEqual(len(ranges), 2)
        done = self.run_once()                               # 再開3
        for i in (0, 1):
            self.assertIn(ts_of(self.DAYS[2], i), self.transport.calls)
        self.assertEqual(done["files_failed"], 0)

    def test_peek_rename_in_store_is_refused(self):
        """exp_peek：日の集計を書いた直後に kill -9 し、保存先の中で名前を変える → 一覧で止まる。"""
        day = "2015-03-02"
        real = gkg.append_jsonl

        def app(path, obj, what, *a, **k):
            if obj.get("kind") == "day" and obj.get("day") == day:
                raise Kill9()
            return real(path, obj, what, *a, **k)
        with mock.patch.object(gkg, "append_jsonl", app), \
                mock.patch.object(gkg, "_write_stop", lambda *a, **k: None):
            with self.assertRaises(Kill9):
                self.run_gkg()
        name = gkg.day_file_name(RUN_ID, day)
        os.rename(os.path.join(self.store, name), os.path.join(self.store, "aside-" + name))
        with self.assertRaisesRegex(gkg.GkgError, "決まった名前でない"):
            self.run_once()
        self.assertEqual(self.transport.calls, [])

    def test_peek_move_out_then_forge_is_not_used(self):
        """exp_peek の変形：保存先の外へ移し、偽の failed を足し、2回再開しても、偽の行は使われない。"""
        day = "2015-03-02"
        real = gkg.append_jsonl

        def app(path, obj, what, *a, **k):
            if obj.get("kind") == "day" and obj.get("day") == day:
                raise Kill9()
            return real(path, obj, what, *a, **k)
        with mock.patch.object(gkg, "append_jsonl", app), \
                mock.patch.object(gkg, "_write_stop", lambda *a, **k: None):
            with self.assertRaises(Kill9):
                self.run_gkg()
        name = gkg.day_file_name(RUN_ID, day)
        os.rename(os.path.join(self.store, name), os.path.join(self.tmp, "aside"))
        target = ts_of(self.DAYS[0], 1)
        self.append_log(self.forged(target))
        with mock.patch.object(gkg, "_write_stop", lambda *a, **k: None), \
                mock.patch.object(gkg, "_run_plan", side_effect=Kill9()):
            with self.assertRaises(Kill9):
                self.run_once()
        done = self.run_once()
        self.assertIn(target, self.transport.calls)
        self.assertEqual(done["files_failed"], 0)

    def test_Y2_forged_attempts_in_tail_do_not_exhaust_without_request(self):
        target = ts_of(self.DAYS[2], 2)
        self.kill_at(ts_of(self.DAYS[1], 0))
        self.append_log(*[{"run_id": RUN_ID, "mode": "official", "file_time": target,
                           "result": "attempt", "attempt": n, "at": "2026-10-08T00:00:00Z"}
                          for n in (1, 2, 3)])
        self.run_once()
        self.assertEqual(self.transport.calls.count(target), 1)   # 少なくとも1回は要求を送る
        rec = [e for e in self.fetch_log() if e["file_time"] == target and e["result"] == "ok"]
        self.assertEqual(len(rec), 1)

    def test_day_line_lists_failed_files(self):
        """主な防御：day の行に failed のファイルの一覧（第三者が GDELT と照らせる）。"""
        bad = ts_of(self.DAYS[0], 1)
        self.responses[bad] = [FakeResponse(status=404)]
        self.run_gkg()
        days = [e for e in self.manifest() if e["kind"] == "day"]
        z = self.zips[bad]
        self.assertEqual(days[0]["failed_files"],
                         [{"file_time": bad, "reason": "http_404", "attempts": 1,
                           "requests_sent": 1, "listed_size": len(z),
                           "listed_md5": hashlib.md5(z).hexdigest()}])
        self.assertEqual(days[0]["requests_sent"], self.N)
        for d in days:
            self.assertEqual(d["files_ok"] + d["files_failed"], d["files_listed"])
        self.assertEqual(days[1]["failed_files"], [])
        for d in days:
            self.assertEqual(len(d["failed_files"]), d["files_failed"])


class TestT026(RunCase):
    """T-026：正直な再開（軽-1）、実際に送った要求の数（軽-2）。"""

    DAYS = ("20150302", "20150303")
    N = 3

    def lp(self):
        return os.path.join(self.store, gkg.fetch_log_name(RUN_ID))

    def stop_between_dayfile_and_dayline(self, exc, write_stop):
        day = "2015-03-02"
        real = gkg.append_jsonl

        def app(path, obj, what, *a, **k):
            if obj.get("kind") == "day" and obj.get("day") == day:
                raise exc()
            return real(path, obj, what, *a, **k)
        patches = [mock.patch.object(gkg, "append_jsonl", app)]
        if not write_stop:
            patches.append(mock.patch.object(gkg, "_write_stop", lambda *a, **k: None))
        for p in patches:
            p.start()
        try:
            with self.assertRaises(exc):
                self.run_gkg()
        finally:
            for p in reversed(patches):
                p.stop()
        self.assertTrue(os.path.exists(os.path.join(self.store, gkg.day_file_name(RUN_ID, day))))

    def test_honest_resume_after_kill9_between_dayfile_and_dayline(self):
        """軽-1（exp5 honest_kill_after_dayfile）：正直な再開は1回目で終わる。"""
        self.stop_between_dayfile_and_dayline(Kill9, write_stop=False)
        done = self.run_once()
        self.assertEqual((done["files_ok"], done["files_failed"]), (2 * self.N, 0))
        day = [e for e in self.manifest() if e["kind"] == "day"][0]
        self.assertTrue(day["reused_existing_day_file"])
        with open(os.path.join(self.store, day["file_name"]), "rb") as f:
            self.assertEqual(hashlib.sha256(f.read()).hexdigest(), day["sha256"])

    def test_honest_resume_after_ctrl_c_with_retried_file(self):
        """元の集計で attempts が 2 のファイル（503 のあと ok）があっても、再開は1回目で終わる。"""
        first = sorted(self.zips)[0]
        self.responses[first] = [FakeResponse(status=503), ok_response(self.zips[first]),
                                 ok_response(self.zips[first])]
        self.stop_between_dayfile_and_dayline(KeyboardInterrupt, write_stop=True)
        done = self.run_once()
        self.assertEqual(done["files_failed"], 0)

    def test_changed_existing_day_file_is_refused(self):
        self.stop_between_dayfile_and_dayline(Kill9, write_stop=False)
        p = os.path.join(self.store, gkg.day_file_name(RUN_ID, "2015-03-02"))
        with open(p, "rb") as f:
            text = gzip.decompress(f.read())
        with open(p, "wb") as f:
            f.write(gkg.gzip_bytes(text.replace(b"\nD\t1\t", b"\nD\t1\t9")))
        with self.assertRaisesRegex(gkg.GkgError, "取り直した集計と中身が違う"):
            self.run_once()

    def test_same_day_except_attempts(self):
        a = gkg.gzip_bytes(b"#\tx\nF\tt\tok\t-\tm\t1\ts\t1\t3\nD\t1\t3\n")
        b = gkg.gzip_bytes(b"#\tx\nF\tt\tok\t-\tm\t1\ts\t2\t3\nD\t1\t3\n")
        c = gkg.gzip_bytes(b"#\tx\nF\tt\tok\t-\tm\t1\ts\t2\t4\nD\t1\t3\n")
        self.assertTrue(gkg.same_day_except_attempts(a, b))
        self.assertFalse(gkg.same_day_except_attempts(a, c))
        self.assertFalse(gkg.same_day_except_attempts(b"not gzip", a))

    def test_requests_sent_can_exceed_limit_by_kills(self):
        """軽-2（exp5 extra_attempts）：kill -9 のたびに、要求の総数は上限を1回ずつ超えうる。
        実際に送った数を day の行の failed_files の requests_sent に書く。"""
        target = ts_of(self.DAYS[0], 1)
        sent = []

        def make(kill_on):
            inner = FakeTransport(self.responses)

            def tr(url, timeout):
                if target in url:
                    sent.append(url)
                    if len(sent) == kill_on:
                        raise Kill9()
                    return FakeResponse(status=503)
                return inner(url, timeout)
            return tr
        with mock.patch.object(gkg, "_write_stop", lambda *a, **k: None):
            with self.assertRaises(Kill9):
                self.run_gkg(transport=make(gkg.MAX_ATTEMPTS_PER_FILE))
            for _k in range(2):
                with self.assertRaises(Kill9):
                    self.run_once(transport=make(len(sent) + 1))
        self.run_once(transport=make(10 ** 6))
        self.assertEqual(len(sent), gkg.MAX_ATTEMPTS_PER_FILE + 3)
        day = [e for e in self.manifest() if e["kind"] == "day"][0]
        rec = [f for f in day["failed_files"] if f["file_time"] == target][0]
        self.assertEqual(rec["requests_sent"], len(sent))
        self.assertLess(rec["attempts"], rec["requests_sent"])


class TestT026Round2(_ForgeMixin, RunCase):
    """T-026 差し戻し1回目：reason・attempts の形（軽-4）、取り直しで結果が変わる正直な再開（軽-2）。"""

    DAYS = ("20150302", "20150303", "20150304")
    N = 3

    def forge_in_trusted(self, **changes):
        """監査の probe_c：kill -9 のあと、偽の行を足し、コミット前の day の行の控えを書き直す。"""
        target = ts_of(self.DAYS[2], 1)
        self.kill_at(ts_of(self.DAYS[1], 0))
        self.append_log(dict(self.forged(target), **changes))
        lines = open(self.manifest_path(), "rb").read().splitlines()
        last = json.loads(lines[-1])
        self.assertEqual(last["kind"], "day")
        with open(self.lp(), "rb") as f:
            data = f.read()
        last["fetch_log_size"] = len(data)
        last["fetch_log_sha256"] = hashlib.sha256(data).hexdigest()
        lines[-1] = json.dumps(last, sort_keys=True).encode()
        with open(self.manifest_path(), "wb") as f:
            f.write(b"\n".join(lines) + b"\n")

    def test_forged_reason_with_free_words_is_refused(self):
        self.forge_in_trusted(reason="Taro_Example")
        with self.assertRaisesRegex(gkg.GkgError, "決まった語でない"):
            self.run_once()
        self.assertEqual(self.transport.calls, [])
        for e in self.manifest():
            self.assertNotIn("Taro_Example", json.dumps(e))

    def test_forged_network_reason_with_free_words_is_refused(self):
        self.forge_in_trusted(reason="network_TaroExample")
        with self.assertRaisesRegex(gkg.GkgError, "決まった語でない"):
            self.run_once()

    def test_forged_attempts_out_of_range_is_refused(self):
        for bad in (999, -1, "1", 1.0, True):
            with self.subTest(bad=bad):
                self.tearDown_reset()
                self.forge_in_trusted(attempts=bad)
                with self.assertRaisesRegex(gkg.GkgError, "attempts の形"):
                    self.run_once()

    def tearDown_reset(self):
        shutil.rmtree(self.tmp, True)
        self.setUp()

    def test_attempt_line_count_out_of_range_is_refused(self):
        self.kill_at(ts_of(self.DAYS[1], 0))
        self.append_log({"run_id": RUN_ID, "mode": "official", "file_time": ts_of(self.DAYS[2], 0),
                         "result": "attempt", "attempt": 0, "at": "2026-10-08T00:00:00Z"})
        with self.assertRaisesRegex(gkg.GkgError, "attempt の行の回数"):
            self.run_once()

    def test_valid_reason_vocabulary(self):
        for r in ("", "http_404", "http_503", "http_None", "http_302", "network_URLError",
                  "network_ConnectionResetError", "network_TimeoutError", "network_IncompleteRead",
                  "retry_after_too_long", "attempts_exhausted", "ambiguous_listing",
                  "content_encoding", "size_mismatch", "md5_mismatch", "too_large",
                  "format_zip", "format_zip_read", "format_too_large_unzipped",
                  "consecutive_transient_failures"):
            self.assertTrue(gkg.valid_reason(r), r)
        for r in ("Taro_Example", "http_4040", "http_x", "network_", "network_Taro",
                  "format_other", "format_", None, 404, "ok"):
            self.assertFalse(gkg.valid_reason(r), r)


class TestChangedResultOnHonestResume(RunCase):
    """T-026 差し戻し1回目 軽-2（監査の probe_b4）：日の集計を書いたあと day の行の前に kill -9 し、
    取り直しで結果が変わると、何回再開しても止まり続ける。日の集計を保存先の外へ移せば続けられる。"""

    DAYS = ("20150302", "20150303")
    N = 3

    def kill_after_dayfile(self):
        day = "2015-03-02"
        real = gkg.append_jsonl

        def app(path, obj, what, *a, **k):
            if obj.get("kind") == "day" and obj.get("day") == day:
                raise Kill9()
            return real(path, obj, what, *a, **k)
        with mock.patch.object(gkg, "append_jsonl", app), \
                mock.patch.object(gkg, "_write_stop", lambda *a, **k: None):
            with self.assertRaises(Kill9):
                self.run_gkg()

    def check_stuck_then_move_out(self):
        for _i in range(2):
            with self.assertRaisesRegex(gkg.GkgError, "取り直した集計と中身が違う"):
                self.run_once()
        name = gkg.day_file_name(RUN_ID, "2015-03-02")
        os.rename(os.path.join(self.store, name), os.path.join(self.tmp, "moved-" + name))
        return self.run_once()

    def test_failed_then_ok(self):
        ft = ts_of(self.DAYS[0], 1)
        self.responses[ft] = [FakeResponse(status=503)]
        self.kill_after_dayfile()
        self.responses[ft] = [ok_response(self.zips[ft])]
        done = self.check_stuck_then_move_out()
        self.assertEqual(done["files_failed"], 0)

    def test_failed_reason_changes(self):
        ft = ts_of(self.DAYS[0], 1)
        self.responses[ft] = [FakeResponse(status=503)]
        self.kill_after_dayfile()
        self.responses[ft] = [FakeResponse(status=502)]
        done = self.check_stuck_then_move_out()
        self.assertEqual(done["files_failed"], 1)

    def test_ok_then_failed(self):
        ft = ts_of(self.DAYS[0], 1)
        self.kill_after_dayfile()
        self.responses[ft] = [FakeResponse(status=503)]
        done = self.check_stuck_then_move_out()
        self.assertEqual(done["files_failed"], 1)


class _DayFileMixin:
    """日の集計を書いたあと、day の行を書く前に止めて、その日の集計を書き換える部品。"""

    DAYS = ("20150302", "20150303")
    N = 3

    def kill_after_dayfile_and_edit(self, val):
        day = "2015-03-02"
        real = gkg.append_jsonl

        def app(path, obj, what, *a, **k):
            if obj.get("kind") == "day" and obj.get("day") == day:
                raise Kill9()
            return real(path, obj, what, *a, **k)
        with mock.patch.object(gkg, "append_jsonl", app), \
                mock.patch.object(gkg, "_write_stop", lambda *a, **k: None):
            with self.assertRaises(Kill9):
                self.run_gkg()
        p = os.path.join(self.store, gkg.day_file_name(RUN_ID, day))
        with open(p, "rb") as f:
            lines = gzip.decompress(f.read()).split(b"\n")
        for i, l in enumerate(lines):
            if l.startswith(b"F\t"):
                f = l.split(b"\t")
                f[7] = val
                lines[i] = b"\t".join(f)
                break
        with open(p, "wb") as f:
            f.write(gkg.gzip_bytes(b"\n".join(lines)))


class TestT030(_DayFileMixin, RunCase):
    """T-030：既にある日の集計をそのまま使う前の検査（軽-A。監査の probe_b5x）、network_ の名前（軽-D）。"""

    def assert_refused(self, val, pattern):
        self.kill_after_dayfile_and_edit(val)
        with self.assertRaisesRegex(gkg.GkgError, pattern):
            self.run_once()
        self.assertEqual([e for e in self.manifest() if e["kind"] == "day"], [])

    def test_free_word_in_attempts_field_is_refused(self):
        self.assert_refused(b"Taro_Example", "attempts の欄の形")

    def test_address_shape_in_attempts_field_is_refused(self):
        self.assert_refused(b"someone" + b"@" + b"example.com", "使ってよい文字の外")

    def test_out_of_range_attempts_field_is_refused(self):
        self.assert_refused(b"4", "attempts の欄の形")

    def test_in_range_attempts_field_is_reused(self):
        self.kill_after_dayfile_and_edit(b"3")
        self.run_once()
        day = [e for e in self.manifest() if e["kind"] == "day"][0]
        self.assertTrue(day["reused_existing_day_file"])

    def test_check_existing_day_file_unit(self):
        good = gkg.gzip_bytes(b"#\tgkg-day\t2\t2015-03-02\tofficial\nF\tt\tok\t-\tm\t1\ts\t0\t3\n")
        gkg.check_existing_day_file(good, "2015-03-02")
        with self.assertRaisesRegex(gkg.GkgError, "gzip の頭"):
            gkg.check_existing_day_file(b"not gzip", "2015-03-02")
        broken = good[:10] + b"\xff" * (len(good) - 10)          # 頭は正しく、中身が壊れている
        with self.assertRaisesRegex(gkg.GkgError, "展開できない"):
            gkg.check_existing_day_file(broken, "2015-03-02")

    def test_network_names_are_fixed(self):
        self.assertIsInstance(gkg.NETWORK_ERROR_NAMES, frozenset)
        self.assertEqual(gkg.network_reason(ConnectionResetError()), "network_ConnectionResetError")
        self.assertEqual(gkg.network_reason(TimeoutError()), "network_TimeoutError")

        class UnlistedNetError(OSError):
            pass
        self.assertEqual(gkg.network_reason(UnlistedNetError()), "network_Other")
        self.assertTrue(gkg.valid_reason("network_Other"))
        self.assertFalse(gkg.valid_reason("network_UnlistedNetError"))

    def test_unlisted_network_error_is_recorded_as_other(self):
        class UnlistedNetError(OSError):
            pass
        bad = sorted(self.zips)[0]
        inner = FakeTransport(self.responses)

        def transport(url, timeout):
            if bad in url:
                raise UnlistedNetError("見本")
            return inner(url, timeout)
        done = self.run_gkg(transport=transport)
        self.assertEqual(done["files_failed"], 1)
        day = [e for e in self.manifest() if e["kind"] == "day"][0]
        self.assertEqual(day["failed_files"][0]["reason"], "network_Other")


class TestT035(unittest.TestCase):
    """T-035：T の行の v1_or_v2_docs（V1 か V2 の少なくとも一方に付いた文書の数）と、
    S の行の docs_without_any_theme。架空のテーマ名だけを使う。"""

    TS = "20150302000000"

    def day_tables(self, rows):
        a = gkg.aggregate_zip(make_zip(self.TS, rows), self.TS, {})
        files = [{"file_time": self.TS, "result": "ok", "reason": "", "md5": "a" * 32, "size": 9,
                  "sha256": "b" * 64, "attempts": 1, "docs": {"1": len(rows)}}]
        data = gkg.serialize_day("2015-03-02", a, files)
        gkg.check_output_bytes(data, "日の集計")
        lines = data.decode().splitlines()
        names = {l.split("\t")[1]: l.split("\t")[2] for l in lines if l.startswith("V\t")}
        t = {}
        for l in lines:
            f = l.split("\t")
            if f[0] == "T":
                self.assertEqual(len(f), 7, l)
                t[(f[1], names[f[2]])] = tuple(int(x) for x in f[3:])
        st = {l.split("\t")[1]: int(l.split("\t")[2]) for l in lines if l.startswith("S\t")}
        return lines, t, st

    def test_same_different_one_side_and_both(self):
        ts = self.TS
        rows = [
            # 同じ文書で V1 と V2 の両方に同じ名前（V2 は2回言及）、V1 だけ、V2 だけ
            gkg_row(ts, 1, themes1=("QQ_SAME", "QQ_V1ONLY"),
                    themes2=(("QQ_SAME", 10), ("QQ_SAME", 50), ("QQ_V2ONLY", 20))),
            gkg_row(ts, 2, themes1=("QQ_SAME",), themes2=()),             # V1 だけに付いた文書
            gkg_row(ts, 3, themes1=(), themes2=(("QQ_SAME", 5),)),         # V2 だけに付いた文書
            # 同じ中身らしいが V1 と V2 で名前が違う：別々のテーマとして数える（限界）
            gkg_row(ts, 4, themes1=("QQ_ALIAS_A",), themes2=(("QQ_ALIAS_B", 1),)),
            gkg_row(ts, 5, themes1=(), themes2=()),                        # どちらにも無い
        ]
        lines, t, st = self.day_tables(rows)
        self.assertEqual(lines[0], "#\tgkg-day\t3\t2015-03-02\tofficial")
        # (v1_docs, v2_docs, v2_mentions, v1_or_v2_docs)
        self.assertEqual(t[("1", "QQ_SAME")], (2, 2, 3, 3))
        self.assertEqual(t[("1", "QQ_V1ONLY")], (1, 0, 0, 1))
        self.assertEqual(t[("1", "QQ_V2ONLY")], (0, 1, 1, 1))
        self.assertEqual(t[("1", "QQ_ALIAS_A")], (1, 0, 0, 1))
        self.assertEqual(t[("1", "QQ_ALIAS_B")], (0, 1, 1, 1))
        for (_g, _n), (v1, v2, _m, v12) in t.items():
            self.assertLessEqual(max(v1, v2), v12)
            self.assertLessEqual(v12, v1 + v2)
        self.assertEqual(st["docs_without_any_theme"], 1)
        self.assertEqual(st["docs_without_v1_theme"], 2)
        self.assertEqual(st["docs_without_v2_theme"], 2)

    def test_invalid_names_are_not_counted(self):
        ts = self.TS
        rows = [gkg_row(ts, 1, themes1=("QQ_OK", "lower case"), themes2=(("QQ_OK", 1),))]
        _lines, t, st = self.day_tables(rows)
        self.assertEqual(t[("1", "QQ_OK")], (1, 1, 1, 1))
        self.assertEqual(st["theme_tokens_invalid_v1"], 1)
        self.assertNotIn("docs_without_any_theme", st)       # 一つも無い文書が無ければ行は出ない

    def test_groups_are_separate(self):
        ts = self.TS
        rows = [gkg_row(ts, 1, themes1=("QQ_SAME",), themes2=(("QQ_SAME", 1),)),
                gkg_row(ts, 2, themes1=("QQ_SAME",), themes2=(), coll="2")]
        _lines, t, _st = self.day_tables(rows)
        self.assertEqual(t[("1", "QQ_SAME")], (1, 1, 1, 1))
        self.assertEqual(t[("2", "QQ_SAME")], (1, 0, 0, 1))


class TestT032(RunCase):
    """T-032：run の開始を封印の記録に書く入口（start_hook）の呼び方。"""

    def test_hook_called_once_per_run_before_any_request(self):
        seen = []
        inner_hook = self.start_hook

        def hook(**k):
            seen.append(("hook", list(self.transport.calls), os.listdir(self.trial_store)))
            return inner_hook(**k)
        self.run_once(mode="trial", committed_manifest=None, start_hook=hook)
        self.assertEqual(seen[0][1:], ([], []))                 # 要求も印のファイルもまだ無い
        self.assertEqual(self.sealed_runs, [("trial", RUN_ID, list(gkg.TRIAL_DAYS)[:len(self.DAYS)])])
        s0 = self.manifest(gkg.TRIAL_MANIFEST_NAME)[0]
        self.assertEqual((s0["gkg_run_seq"], s0["gkg_run_record_sha256"]), (21, "9" * 64))
        # 2回目の試しの run（コードが違う）：もう1件
        self.run_once(mode="trial", committed_manifest=None, code_sha256="cd" * 32)
        self.assertEqual([r[:2] for r in self.sealed_runs], [("trial", RUN_ID), ("trial", "cd" * 8)])
        # 正式な run：1回目（run-start を書いて止まる）で1件、2回目は書かない
        with self.assertRaises(gkg.RunStartWritten):
            self.run_once()
        self.assertEqual(self.sealed_runs[-1], ("official", RUN_ID, None))
        self.run_once()
        self.assertEqual(len(self.sealed_runs), 3)
        m0 = self.manifest()[0]
        self.assertEqual(m0["gkg_run_seq"], 23)

    def test_resume_does_not_write_again(self):
        self.low_after = 2
        with self.assertRaises(gkg.RunInterrupted):
            self.run_gkg()
        self.low_after = None
        self.run_gkg()
        self.assertEqual(len(self.sealed_runs), 1)

    def test_hook_failure_sends_no_request_and_writes_nothing(self):
        def boom(**k):
            raise RuntimeError("見本：封印の記録に書けない")
        for mode, kw in (("trial", {"committed_manifest": None}), ("official", {})):
            with self.subTest(mode=mode):
                with self.assertRaisesRegex(gkg.GkgError, "gkg-run-start を書けなかった"):
                    self.run_once(mode=mode, start_hook=boom, **kw)
                self.assertEqual(self.transport.calls, [])
                self.assertEqual(os.listdir(self.store), [])
                self.assertEqual(os.listdir(self.trial_store), [])
                self.assertFalse(os.path.exists(self.manifest_path()))
                self.assertFalse(os.path.exists(self.manifest_path(gkg.TRIAL_MANIFEST_NAME)))

    def test_missing_or_bad_hook_is_refused(self):
        for hook, pattern in ((None, "受け取っていない"),
                              (lambda **k: {"seq": 0, "record_sha256": "9" * 64}, "形が違う"),
                              (lambda **k: {"seq": 3}, "形が違う"),
                              (lambda **k: {"seq": 3, "record_sha256": "x"}, "形が違う")):
            with self.subTest(hook=hook):
                with self.assertRaisesRegex(gkg.GkgError, pattern):
                    self.run_once(start_hook=hook)
                self.assertEqual(self.transport.calls, [])
                self.assertFalse(os.path.exists(self.manifest_path()))


class TestT032Vocab(unittest.TestCase):
    """T-032（T-035 の監査 中-1。A3 と同じ形）：同じプロセスで先に言語の符号や ENG の語を見ても、
    テーマの数は変わらない。"""

    TS = "20150302000000"

    def tables(self, rows, vocab):
        a = gkg.aggregate_zip(make_zip(self.TS, rows), self.TS, vocab)
        files = [{"file_time": self.TS, "result": "ok", "reason": "", "md5": "a" * 32, "size": 9,
                  "sha256": "b" * 64, "attempts": 1, "docs": {"1": len(rows)}}]
        return gkg.serialize_day("2015-03-02", a, files)

    def test_other_vocab_kinds_do_not_leak_into_themes(self):
        ts = self.TS
        first = [gkg_row(ts, 1, translated=True, srclc="jpn", eng="GT-JPN 1.0",
                         countries=("JA",))]
        second = [gkg_row(ts, 2, themes1=("jpn", "GT-JPN 1.0", "QQ_REAL"),
                          themes2=(("jpn", 5), ("QQ_REAL", 1)))]
        shared = {}
        self.tables(first, shared)                       # 先に言語の符号と ENG の語を見る
        after = self.tables(second, shared)
        fresh = self.tables(second, {})
        self.assertEqual(after, fresh)
        self.assertNotIn(b"\tjpn\n", b"\n".join(l for l in after.split(b"\n") if l.startswith(b"V")) + b"\n")
        st = {l.split(b"\t")[1]: int(l.split(b"\t")[2]) for l in after.split(b"\n") if l.startswith(b"S\t")}
        self.assertEqual(st[b"theme_tokens_invalid_v1"], 2)
        self.assertEqual(st[b"theme_tokens_invalid_v2"], 1)

    def test_vocab_kinds_are_separate(self):
        v = {}
        t, c, l, e = gkg._vocabs(v)
        self.assertEqual(len({id(x) for x in (t, c, l, e)}), 4)
        self.assertEqual(sorted(v), ["country", "eng", "lang", "theme"])


class TestT035Light(unittest.TestCase):
    """T-035 の監査 軽-1：同じ文書の V1 に同じテーマが2回、形の合わない名前しか付かない文書、
    docs_without_any_theme とほかの2つの値の関係。"""

    TS = "20150302000000"

    def run_rows(self, rows):
        a = gkg.aggregate_zip(make_zip(self.TS, rows), self.TS, {})
        return a

    def test_cases(self):
        ts = self.TS
        rows = [gkg_row(ts, 1, themes1=("QQ_TWICE", "QQ_TWICE"), themes2=(("QQ_TWICE", 1),)),
                gkg_row(ts, 2, themes1=("lower one",), themes2=(("bad name", 1),)),
                gkg_row(ts, 3, themes1=("QQ_ONLY_V1",), themes2=()),
                gkg_row(ts, 4, themes1=(), themes2=(("QQ_ONLY_V2", 1),))]
        a = self.run_rows(rows)
        T = a.tables
        self.assertEqual(T["t1"][b"1"][b"QQ_TWICE"], 1)
        self.assertEqual(T["t12"][b"1"][b"QQ_TWICE"], 1)
        st = a.stats
        self.assertEqual(st["docs_without_any_theme"], 1)         # 形の合わない名前しか無い文書
        self.assertEqual(st["docs_without_v1_theme"], 2)
        self.assertEqual(st["docs_without_v2_theme"], 2)
        self.assertLessEqual(st["docs_without_any_theme"],
                             min(st["docs_without_v1_theme"], st["docs_without_v2_theme"]))
        # 少なくとも一方に付いた文書 = 全体 − どちらにも付かない文書
        self.assertEqual(sum(a.docs.values()) - st["docs_without_any_theme"], 3)


class TestT032DayFileBytes(_DayFileMixin, RunCase):
    """T-032（T-030 の監査 中-1）：既にある日の集計の、ファイルのバイト列の検査。"""

    def tamper_bytes(self, change):
        self.kill_after_dayfile_and_edit(b"1")
        p = os.path.join(self.store, gkg.day_file_name(RUN_ID, "2015-03-02"))
        with open(p, "rb") as f:
            gz = f.read()
        with open(p, "wb") as f:
            f.write(change(gz))

    def refused(self, change, pattern):
        self.tamper_bytes(change)
        with self.assertRaisesRegex(gkg.GkgError, pattern):
            self.run_once()
        self.assertEqual([e for e in self.manifest() if e["kind"] == "day"], [])

    def test_fname_with_address_shape(self):
        addr = b"someone" + b"@" + b"example.com"
        self.refused(lambda gz: gz[:3] + b"\x08" + gz[4:10] + addr + b"\x00" + gz[10:], "gzip の頭")

    def test_fcomment_with_free_word(self):
        self.refused(lambda gz: gz[:3] + b"\x10" + gz[4:10] + b"Taro Example\x00" + gz[10:],
                     "gzip の頭")

    def test_fextra(self):
        self.refused(lambda gz: gz[:3] + b"\x04" + gz[4:10] + b"\x05\x00Hello" + gz[10:],
                     "gzip の頭")

    def test_nonzero_mtime(self):
        self.refused(lambda gz: gz[:4] + b"\x01\x00\x00\x00" + gz[8:], "gzip の頭")

    def test_trailing_empty_member(self):
        self.refused(lambda gz: gz + gzip.compress(b"", mtime=0), "後ろに、別の部分かバイト")

    def test_trailing_bytes(self):
        self.refused(lambda gz: gz + b"Taro_Example", "後ろに、別の部分かバイト")

    def test_unchanged_file_is_reused(self):
        self.tamper_bytes(lambda gz: gz)
        self.run_once()
        day = [e for e in self.manifest() if e["kind"] == "day"][0]
        self.assertTrue(day["reused_existing_day_file"])


class TestRound3Trial(RunCase):
    """exp_trial2：試しの run を「.」で隠す・フォルダの外へ移す。"""

    DAYS = ("20150302",)
    N = 2

    def hide(self, how):
        self.run_once(mode="trial", committed_manifest=None)
        open(self.manifest_path(gkg.TRIAL_MANIFEST_NAME), "w").close()
        if how == "dot":
            for n in os.listdir(self.trial_store):
                os.rename(os.path.join(self.trial_store, n), os.path.join(self.trial_store, "." + n))
        else:
            os.mkdir(os.path.join(self.trial_store, ".old"))
            for n in os.listdir(self.trial_store):
                if n != ".old":
                    os.rename(os.path.join(self.trial_store, n),
                              os.path.join(self.trial_store, ".old", n))
        with self.assertRaisesRegex(gkg.GkgError, "決まった名前でない"):
            self.run_once(mode="trial", committed_manifest=None, code_sha256="cd" * 32)

    def test_dot(self):
        self.hide("dot")

    def test_subdir_dot(self):
        self.hide("subdir")

    def test_listed_trial_files_missing(self):
        self.run_once(mode="trial", committed_manifest=None)
        for n in os.listdir(self.trial_store):
            os.rename(os.path.join(self.trial_store, n), os.path.join(self.tmp, n))
        with self.assertRaisesRegex(gkg.GkgError, "控えと合わない"):
            self.run_once()
        self.assertFalse(os.path.exists(self.manifest_path()))


# --- T-021：FAT32 のイメージの上での検査（環境変数でイメージのマウント先を渡したときだけ） -----

FAT32_ENV = "GKG_FAT32_TEST_VOLUME"
FAT32_RO_ENV = "GKG_FAT32_TEST_VOLUME_RO"


def _fat32_mount(env):
    """環境変数のマウント先が、本物のディスクでない msdos のマウント先なら、その realpath を返す。"""
    v = os.environ.get(env)
    if not v:
        return None
    real = os.path.realpath(v)
    if real == "/Volumes" or real.startswith("/Volumes/"):
        raise RuntimeError("テストに本物のディスク（/Volumes の下）を渡してはいけない")
    out = subprocess.run(["/sbin/mount"], capture_output=True, timeout=30).stdout.decode()
    lines = [l for l in out.splitlines() if (" on %s (" % real) in l]
    if len(lines) != 1 or "(msdos," not in lines[0]:
        raise RuntimeError("%s が msdos（FAT32）のマウント先でない" % env)
    if not os.path.ismount(real):
        raise RuntimeError("%s がマウント先でない" % env)
    return v


@unittest.skipUnless(os.environ.get(FAT32_ENV), "FAT32 のイメージのマウント先が渡されていない "
                     "（%s。手順は src/collector/README.md 7章）" % FAT32_ENV)
class TestOnFat32(RunCase):
    """FAT32 のイメージの上で、本物の check_volume を使って、書き込みと関門の検査を確かめる（8章）。"""

    def setUp(self):
        super().setUp()
        self.volume = _fat32_mount(FAT32_ENV)
        base = os.path.join(self.volume, gkg.STORE_PARTS[0])
        if os.path.lexists(base):
            self.fail("イメージの直下に news-stick-data が既にある（前のテストの残り）")
        self.store = os.path.join(self.volume, *gkg.STORE_PARTS)
        self.trial_store = os.path.join(self.volume, *gkg.TRIAL_STORE_PARTS)
        os.makedirs(self.store)
        os.makedirs(self.trial_store)
        self.addCleanup(shutil.rmtree, base, True)     # テスト用のイメージの中だけ
        self.check_volume = gkg.check_volume           # 本物

    def test_full_trial_and_official_runs(self):
        self.run_once(mode="trial", committed_manifest=None)
        done = self.run_gkg()
        self.assertEqual(done["files_ok"], len(self.zips))
        for name in (gkg.TRIAL_MANIFEST_NAME, gkg.MANIFEST_NAME):
            folder = self.trial_store if name == gkg.TRIAL_MANIFEST_NAME else self.store
            for e in self.manifest(name):
                if e["kind"] == "day":
                    p = os.path.join(folder, e["file_name"])
                    self.assertTrue(e["file_name"] in os.listdir(folder))
                    st = os.lstat(p)
                    self.assertTrue(stat.S_ISREG(st.st_mode))
                    self.assertEqual(st.st_nlink, 1)
                    with open(p, "rb") as f:
                        self.assertEqual(hashlib.sha256(f.read()).hexdigest(), e["sha256"])
        with open(os.path.join(self.store, gkg.fetch_log_name(RUN_ID)), "rb") as f:
            self.assertEqual(hashlib.sha256(f.read()).hexdigest(), done["fetch_log_sha256"])
        for name, data in self.written_fat().items():
            self.assertEqual(privacy_scan.find_in_bytes(data), {}, name)
            for mk in all_markers():
                self.assertNotIn(mk, data, (name, mk))
            self.assertNotIn(self.volume.encode(), data, name)

    def written_fat(self):
        out = {}
        for top in (self.store, self.trial_store, os.path.join(self.root, "data")):
            for d, _ds, fs in os.walk(top):
                for n in fs:
                    if n.startswith("._"):
                        continue                       # macOS の付属のファイル（8章）
                    with open(os.path.join(d, n), "rb") as f:
                        b = f.read()
                    out[os.path.join(d, n)] = gzip.decompress(b) if n.endswith(".gz") else b
        out["log"] = "\n".join(self.logs).encode()
        return out

    def test_symlinked_store_refused(self):
        os.rename(self.store, self.store + "-real")
        os.symlink(self.store + "-real", self.store)   # msdos のドライバが作る印のリンク
        self.assertTrue(stat.S_ISLNK(os.lstat(self.store).st_mode))
        with self.assertRaisesRegex(gkg.GkgError, "シンボリックリンク"):
            self.run_gkg()
        self.assertEqual(self.manifest(), [])

    def test_symlinked_fetch_log_refused(self):
        target = os.path.join(self.volume, gkg.STORE_PARTS[0], "elsewhere.jsonl")
        with self.assertRaises(gkg.RunStartWritten):
            self.run_once()
        os.symlink(target, os.path.join(self.store, gkg.fetch_log_name(RUN_ID)))
        with self.assertRaisesRegex(gkg.GkgError, "決まった名前でない"):   # 一覧でリンクを止める
            self.run_once()
        with self.assertRaisesRegex(gkg.GkgError, "開けない"):           # 一覧の後ろの O_NOFOLLOW
            gkg.read_bytes_nofollow(os.path.join(self.store, gkg.fetch_log_name(RUN_ID)))
        self.assertEqual(self.transport.calls, [])
        self.assertFalse(os.path.lexists(target))

    def test_case_variant_store_refused(self):
        os.rename(self.store, os.path.join(os.path.dirname(self.store), "GKG-METHOD"))
        self.assertTrue(os.path.isdir(self.store))     # FAT32 は大文字と小文字を区別しない
        with self.assertRaisesRegex(gkg.GkgError, "大文字と小文字"):
            self.run_gkg()
        self.assertEqual(self.manifest(), [])

    def test_case_insensitive_names_do_not_overwrite(self):
        gkg.write_new_file(self.store, "a.txt", b"one")
        with self.assertRaisesRegex(gkg.GkgError, "中身の違う"):
            gkg.write_new_file(self.store, "A.TXT", b"two")
        with open(os.path.join(self.store, "a.txt"), "rb") as f:
            self.assertEqual(f.read(), b"one")

    def test_store_id_is_stable_while_mounted(self):
        p1 = gkg.resolve_paths(self.root, self.volume, "official", gkg.check_volume)
        gkg.write_new_file(self.store, "x.bin", b"x" * 100000)
        gkg.append_store_jsonl(p1, os.path.join(self.store, "y.jsonl"), {"a": 1}, "見本")
        p2 = gkg.resolve_paths(self.root, self.volume, "official", gkg.check_volume)
        self.assertEqual(p1["store_id"], p2["store_id"])

    def test_kill_during_retry_wait_on_fat32(self):
        bad = sorted(self.zips)[0]
        self.responses[bad] = [FakeResponse(status=503)]

        def sleep_kill(s):
            if s == gkg.RETRY_WAIT_SECONDS[0]:
                raise Killed()
            self.clock.t += s
        with self.assertRaises(Killed):
            self.run_gkg(sleep=sleep_kill)
        self.run_gkg()
        self.assertEqual(self.transport.calls.count(bad), gkg.MAX_ATTEMPTS_PER_FILE - 1)


@unittest.skipUnless(os.environ.get(FAT32_RO_ENV), "読み取り専用の FAT32 のイメージが渡されていない")
class TestOnFat32ReadOnly(unittest.TestCase):
    def test_read_only_volume_refused(self):
        v = _fat32_mount(FAT32_RO_ENV)
        with self.assertRaisesRegex(gkg.GkgError, "読み取り専用"):
            gkg.check_volume(v)


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
                for k in ("root", "vol", "outside", "code")}
        try:
            mdir = os.path.join(tops["root"], "data", "manifest")
            os.makedirs(mdir)
            store = os.path.join(tops["vol"], *gkg.STORE_PARTS)
            os.makedirs(store)
            os.makedirs(os.path.join(tops["vol"], *gkg.TRIAL_STORE_PARTS))
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
                           os.path.join(real_store, gkg.fetch_log_name(RUN_ID)),
                           os.path.join(real_store, gkg.volume_mark_name(RUN_ID))]
                allowed += [os.path.join(real_store, gkg.day_file_name(
                    RUN_ID, "%s-%s-%s" % (d[:4], d[4:6], d[6:]))) for d in self.DAYS]
            report = tempfile.TemporaryFile()
            vio = tempfile.TemporaryFile()
            try:
                cfg = {"report_fd": report.fileno(), "violation_fd": vio.fileno(),
                       "gkg_path": gkg_path, "root": tops["root"], "volume": tops["vol"],
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
            for k in ("root", "vol", "outside"):
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
                         ["root"] + ["vol"] * 4)
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
                '            open(os.path.join(os.path.dirname(ctx["log_path"]), "raw.zip"), "wb")'
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
