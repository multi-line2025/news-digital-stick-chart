"""GDELT のファイル一覧の取得（src/collector/filelist.py）のテスト。T-010。

実行（プロジェクトのルートで。__pycache__ を作らないよう、必ず次の形で）:
    PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest discover -s tests/collector -v

ネットワークは使わない。モジュールの読み込みの時点で socket の接続を塞ぎ、
通信を試みたら失敗するようにしている。通信の部分は、作った見本の一覧を返す
差し替えの関数（FakeTransport）に置き換える。見本の行は、実在のファイル名に似せた
架空の行である（md5 と大きさは作った値）。

このファイルには、メールアドレスの形の文字列をそのまま書かない。必要なときは、
実行中に部品を組み立てて作る。
"""

import datetime
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
import urllib.error
import urllib.request
import uuid
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(os.path.dirname(HERE))
SRC = os.path.join(PROJECT, "src", "collector")
PRIVACY_SCRIPT = os.path.join(SRC, "privacy_scan.py")


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


filelist = _load("filelist", os.path.join(SRC, "filelist.py"))
privacy_scan = filelist.privacy_scan
periods = _load("periods_for_filelist_test", os.path.join(PROJECT, "src", "stats", "periods.py"))


# --- ネットワークを塞ぐ -----------------------------------------------------

class NetworkUsed(AssertionError):
    pass


def _blocked(*args, **kwargs):
    raise NetworkUsed("テストの中でネットワークに接続しようとした")


_patches = [
    mock.patch.object(socket.socket, "connect", _blocked),
    mock.patch.object(socket.socket, "connect_ex", _blocked),
    mock.patch.object(socket, "create_connection", _blocked),
    mock.patch.object(socket, "getaddrinfo", _blocked),
]


def setUpModule():
    for p in _patches:
        p.start()


def tearDownModule():
    for p in _patches:
        p.stop()


# --- 見本の一覧 ---------------------------------------------------------------

BASE = "http://data.gdeltproject.org/gdeltv2/"
SUFFIX = {"export": "export.CSV.zip", "mentions": "mentions.CSV.zip", "gkg": "gkg.csv.zip"}


def md5_of(*parts):
    return hashlib.md5(("|".join(parts)).encode()).hexdigest()


def row(ts, kind, size=None, md5=None, base=BASE):
    size = size if size is not None else 100000 + int(ts[-6:-2])
    md5 = md5 or md5_of(ts, kind)
    return "%d %s %s%s.%s" % (size, md5, base, ts, SUFFIX[kind])


# 残る行（2020-12-14 以前）
PRE_ROWS = [
    row("20150218230000", "export"),      # DATA_START より前（一覧の段階では残す）
    row("20150302000000", "export"),
    row("20150302000000", "mentions"),
    row("20150302000000", "gkg"),
    row("20180607121500", "gkg"),
    row("20201214234500", "export"),      # 境目の直前（残す）
    row("20201214234500", "mentions"),
    row("20201214234500", "gkg"),
]
# 2020-12-14 以前と判定できるが、形式の合わない行（保存しない。件数は出してよい）
PRE_REJECTED = [
    "123 nothex %s20160101000000.export.CSV.zip" % BASE,                       # md5 が違う
    "12x %s %s20160101001500.export.CSV.zip" % (md5_of("a"), BASE),            # 大きさが違う
    "456 %s https://api.gdeltcloud.com/gdeltv2/20160101003000.export.CSV.zip" % md5_of("b"),
    "789 %s http://data.gdeltproject.org/other/20160101004500.export.CSV.zip" % md5_of("c"),
    "321 %s %s20160101010000.translation.export.CSV.zip" % (md5_of("d"), BASE),
]
# 判定できない行（捨てる。数えない）
UNCLASSIFIABLE = [
    "",
    "garbage",
    "1 2",
    "1 2 3 4",
    "100 %s %s2016010100000.export.CSV.zip" % (md5_of("e"), BASE),   # 13桁
    "100 %s %s20161301000000.export.CSV.zip" % (md5_of("f"), BASE),  # 13月
    "x" * 10000,                                                     # 長すぎる行
]


def post_rows(n, salt="p"):
    """2020-12-15 以降の行。目印として、ほかに出てこない値を使う。"""
    out = [
        # 境目のファイル（捨てる）
        row("20201215000000", "export", size=987654301, md5=md5_of(salt, "b1")),
        row("20201215000000", "mentions", size=987654302, md5=md5_of(salt, "b2")),
        row("20201215000000", "gkg", size=987654303, md5=md5_of(salt, "b3")),
        # 刻みに揃わない時刻（ファイルの日は 2020-12-15。捨てる）
        row("20201214235000", "export", size=987654304, md5=md5_of(salt, "b4")),
        # 2020-12-15 以降で形式の合わない行（数えてはいけない）
        "12x nothex %s20210101000000.export.CSV.zip" % BASE,
        "999 %s https://api.gdeltcloud.com/gdeltv2/20220101000000.gkg.csv.zip" % md5_of(salt, "c"),
    ]
    start = datetime.datetime(2020, 12, 15, 0, 15)
    for i in range(n):
        t = start + datetime.timedelta(minutes=15 * i)
        out.append(row(t.strftime("%Y%m%d%H%M%S"), ("export", "mentions", "gkg")[i % 3],
                       size=900000000 + i, md5=md5_of(salt, str(i))))
    return out


def build_list(post, order="mixed"):
    lines = PRE_ROWS + PRE_REJECTED + UNCLASSIFIABLE + post
    if order == "mixed":
        # 時刻の順に並んでいないことを想定する（行の順番に頼らないことを確かめる）
        lines = lines[::2] + lines[1::2]
    return ("\n".join(lines) + "\n").encode("ascii")


class FakeHeaders(dict):
    def get(self, k, default=None):
        return dict.get(self, k, default)


class FakeResponse:
    def __init__(self, body=b"", status=200, headers=None, fail_after=None):
        self._buf = io.BytesIO(body)
        self.status = status
        self.headers = FakeHeaders(headers or {})
        self._fail_after = fail_after
        self._reads = 0
        self.closed = False

    def readline(self, limit=-1):
        self._reads += 1
        if self._fail_after is not None and self._reads > self._fail_after:
            raise ConnectionResetError("見本の失敗")
        return self._buf.readline(limit)

    def close(self):
        self.closed = True


class FakeTransport:
    """呼ばれるたびに、用意した応答（または例外）を順に返す。"""

    def __init__(self, *responses, events=None):
        self.responses = list(responses)
        self.calls = []
        self.events = events

    def __call__(self, url, timeout):
        self.calls.append((url, timeout))
        if self.events is not None:
            self.events.append("fetch")
        r = self.responses.pop(0)
        if isinstance(r, BaseException):
            raise r
        return r


class FakeClock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


class Recorder:
    def __init__(self, events, seq=7, start_exc=None):
        self.events = events
        self.seq = seq
        self.start_exc = start_exc
        self.start_args = []
        self.result_args = []

    def start(self, **kw):
        self.events.append("start")
        self.start_args.append(kw)
        if self.start_exc:
            raise self.start_exc
        return self.seq

    def result(self, **kw):
        self.events.append("result")
        self.result_args.append(kw)


FIXED_NOW = datetime.datetime(2026, 10, 7, 1, 2, 3, tzinfo=datetime.timezone.utc)


class RunCase(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="filelist-")
        self.processed = os.path.join(self.root, "data", "processed")
        self.manifest_dir = os.path.join(self.root, "data", "manifest")
        self.logs = []
        self.sleeps = []
        self.events = []
        self.clock = FakeClock()

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def sleep(self, s):
        self.sleeps.append(s)
        self.clock.t += s

    def run_acq(self, transport, rec=None, now=FIXED_NOW, url=filelist.MASTERFILELIST_URL):
        rec = rec or Recorder(self.events)
        out = filelist.run_acquisition(
            start_hook=rec.start, result_hook=rec.result, root=self.root,
            processed_dir=self.processed, manifest_dir=self.manifest_dir, url=url,
            transport=transport, sleep=self.sleep, clock=self.clock,
            now=lambda: now, log=self.logs.append)
        return out, rec

    def all_written(self):
        """root の下に書かれたすべてのファイル（相対パス → 中身）。"""
        found = {}
        for d, _, files in os.walk(self.root):
            for f in files:
                p = os.path.join(d, f)
                with open(p, "rb") as fh:
                    found[os.path.relpath(p, self.root)] = fh.read()
        return found


# --- テスト本体 ---------------------------------------------------------------

class TestConstants(unittest.TestCase):
    def test_cutoff_matches_periods(self):
        threshold = [b for b in periods.FROZEN_BLOCKS if b[0] == "threshold"][0]
        self.assertEqual(filelist.CUTOFF_DAY, threshold[1])
        method = [b for b in periods.FROZEN_BLOCKS if b[0] == "method"][0]
        self.assertEqual(method[2] + datetime.timedelta(days=1), filelist.CUTOFF_DAY)

    def test_limits_are_explicit(self):
        self.assertEqual(filelist.MAX_ATTEMPTS, 3)
        self.assertEqual(len(filelist.RETRY_WAIT_SECONDS), filelist.MAX_ATTEMPTS - 1)
        self.assertGreater(filelist.REQUEST_TIMEOUT_SECONDS, 0)
        self.assertGreater(filelist.TOTAL_DEADLINE_SECONDS, sum(filelist.RETRY_WAIT_SECONDS))
        self.assertIn("公式の値", filelist.__doc__)

    def test_citation_in_docstring(self):
        self.assertIn("Data: The GDELT Project (https://www.gdeltproject.org/). This project "
                      "is not affiliated with or endorsed by the GDELT Project.",
                      " ".join(filelist.__doc__.split()))


class TestUrlAllowlist(unittest.TestCase):
    def test_allowed(self):
        filelist.validate_url(filelist.MASTERFILELIST_URL)
        self.assertEqual(filelist.MASTERFILELIST_URL,
                         "https://data.gdeltproject.org/gdeltv2/masterfilelist.txt")

    def test_rejected(self):
        at = "@"
        bad = [
            "https://gdeltcloud.com/gdeltv2/masterfilelist.txt",
            "https://api.gdeltcloud.com/gdeltv2/masterfilelist.txt",
            "https://www.gdeltcloud.com/",
            "https://www.gdeltproject.org/gdeltv2/masterfilelist.txt",
            "https://api.gdeltproject.org/gdeltv2/masterfilelist.txt",
            "https://example.com/gdeltv2/masterfilelist.txt",
            "https://data.gdeltproject.org.example.com/gdeltv2/masterfilelist.txt",
            "https://example.com/data.gdeltproject.org/gdeltv2/masterfilelist.txt",
            "https://data.gdeltproject.org./gdeltv2/masterfilelist.txt",
            "https://DATA.gdeltproject.org/gdeltv2/masterfilelist.txt",
            "http://data.gdeltproject.org/gdeltv2/masterfilelist.txt",
            "ftp://data.gdeltproject.org/gdeltv2/masterfilelist.txt",
            "https://data.gdeltproject.org:443/gdeltv2/masterfilelist.txt",
            "https://u" + at + "data.gdeltproject.org/gdeltv2/masterfilelist.txt",
            "https://data.gdeltproject.org" + at + "example.com/gdeltv2/masterfilelist.txt",
            "https://data.gdeltproject.org/gdeltv2/masterfilelist.txt?x=1",
            "https://data.gdeltproject.org/gdeltv2/masterfilelist.txt?",
            "https://data.gdeltproject.org/gdeltv2/masterfilelist.txt#a",
            "https://data.gdeltproject.org/documentation/../gdeltv2/masterfilelist.txt",
            "https://data.gdeltproject.org/gdeltv2/./masterfilelist.txt",
            "https://data.gdeltproject.org//gdeltv2/masterfilelist.txt",
            "https://data.gdeltproject.org/gdeltv2/%6Dasterfilelist.txt",
            "https://data.gdeltproject.org/gdeltv2/masterfilelist.txt ",
            "https://data.gdeltproject.org\\gdeltv2/masterfilelist.txt",
            "https://data.gdeltproject.org/gdeltv2/20150218230000.export.CSV.zip",
            "https://data.gdeltproject.org/gdeltv2/masterfilelist-translation.txt",
            "https://dаta.gdeltproject.org/gdeltv2/masterfilelist.txt",  # キリル文字の а
            b"https://data.gdeltproject.org/gdeltv2/masterfilelist.txt",
            None,
        ]
        for u in bad:
            with self.subTest(u=u):
                with self.assertRaises(filelist.FilelistError) as cm:
                    filelist.validate_url(u)
                # 例外の文に URL を入れない
                if isinstance(u, str):
                    self.assertNotIn(u, str(cm.exception))

    def test_default_transport_rejects_before_network(self):
        with self.assertRaises(filelist.FilelistError):
            filelist.urllib_transport("https://gdeltcloud.com/gdeltv2/masterfilelist.txt", 1)


class TestRedirect(unittest.TestCase):
    def test_redirect_handler_refuses(self):
        h = filelist._NoRedirect()
        req = urllib.request.Request(filelist.MASTERFILELIST_URL)
        for code in (301, 302, 303, 307, 308):
            self.assertIsNone(h.redirect_request(req, None, code, "x", {},
                                                 "https://gdeltcloud.com/"))

    def test_opener_has_only_our_redirect_handler(self):
        opener = filelist.build_opener()
        redirects = [h for h in opener.handlers
                     if isinstance(h, urllib.request.HTTPRedirectHandler)]
        self.assertEqual(len(redirects), 1)
        self.assertIsInstance(redirects[0], filelist._NoRedirect)
        proxies = [h for h in opener.handlers if isinstance(h, urllib.request.ProxyHandler)]
        for p in proxies:
            self.assertEqual(p.proxies, {})


class TestFileDay(unittest.TestCase):
    def t(self, s):
        return filelist.parse_file_time(s)

    def test_rule(self):
        cases = {
            "20201214234500": datetime.date(2020, 12, 14),
            "20201215000000": datetime.date(2020, 12, 15),
            "20201214235000": datetime.date(2020, 12, 15),
            "20201214235959": datetime.date(2020, 12, 15),
            "20201214234459": datetime.date(2020, 12, 14),
            "20150302000000": datetime.date(2015, 3, 2),
            "20150301234500": datetime.date(2015, 3, 1),
        }
        for s, d in cases.items():
            with self.subTest(s=s):
                self.assertEqual(filelist.file_day(self.t(s)), d)

    def test_boundary_safe_under_both_assumptions(self):
        """残るファイルは、始まり・終わりのどちらの前提でも 2020-12-15 より前のデータだけ。"""
        cutoff = datetime.datetime(2020, 12, 15, tzinfo=datetime.timezone.utc)
        span = filelist.FILE_SPAN
        start = datetime.datetime(2020, 12, 14, 22, 0, tzinfo=datetime.timezone.utc)
        for i in range(0, 4 * 3600, 60):  # 22:00〜翌 02:00 を1分ごと
            t = start + datetime.timedelta(seconds=i)
            kept = filelist.file_day(t) < filelist.CUTOFF_DAY
            as_start_end = t + span      # 始まりを指す場合の区間の終わり
            as_end_end = t               # 終わりを指す場合の区間の終わり
            if kept:
                self.assertLessEqual(as_start_end, cutoff, t)
                self.assertLessEqual(as_end_end, cutoff, t)
            else:
                # 捨てるのは、どちらかの前提で cutoff 以降を含みうるものだけ
                self.assertGreater(as_start_end, cutoff, t)

    def test_no_later_data_in_any_day(self):
        """どの日の区切りでも、日 D のファイルは D より後のデータを含まない（どちらの前提でも）。"""
        start = datetime.datetime(2016, 3, 1, 23, 0, tzinfo=datetime.timezone.utc)
        for i in range(0, 2 * 3600, 900):
            t = start + datetime.timedelta(seconds=i)
            d = filelist.file_day(t)
            last_possible = t + filelist.FILE_SPAN - filelist.TIME_RESOLUTION
            self.assertLessEqual(last_possible.date(), d)

    def test_minus_15_rule_would_leak(self):
        """割り振りの例（t − 15分 の日付）では、境目のファイルが 12-14 に入ってしまう。"""
        t = self.t("20201215000000")
        self.assertEqual((t - filelist.FILE_SPAN).date(), datetime.date(2020, 12, 14))
        self.assertEqual(filelist.file_day(t), datetime.date(2020, 12, 15))

    def test_invalid_times(self):
        for s in ("2020121500000", "202012150000000", "20201301000000", "2020123x000000",
                  "20200230000000", "20201215250000"):
            self.assertIsNone(filelist.parse_file_time(s), s)


class TestParseAndSerialize(unittest.TestCase):
    def test_fields_only(self):
        line = (row("20150302000000", "gkg", size=12345, md5="a" * 32) + "\n").encode()
        self.assertEqual(filelist.parse_kept_line(line),
                         ("20150302000000", "gkg", "12345", "a" * 32))
        data = filelist.serialize_rows([filelist.parse_kept_line(line)])
        self.assertEqual(data, b"file_time\tfile_type\tsize_bytes\tmd5\n"
                               b"20150302000000\tgkg\t12345\t" + b"a" * 32 + b"\n")

    def test_order_independent(self):
        rows = [filelist.parse_kept_line(r.encode()) for r in PRE_ROWS]
        self.assertEqual(filelist.serialize_rows(rows), filelist.serialize_rows(rows[::-1]))

    def test_rejected_forms(self):
        for r in PRE_REJECTED:
            self.assertIsNone(filelist.parse_kept_line(r.encode()), r)


class TestAcquisition(RunCase):
    def test_normal_run(self):
        tr = FakeTransport(FakeResponse(build_list(post_rows(30))))
        out, rec = self.run_acq(tr)
        self.assertEqual(out["kept_rows"], len(PRE_ROWS))
        self.assertEqual(out["rejected_rows"], len(PRE_REJECTED))
        self.assertEqual(tr.calls, [(filelist.MASTERFILELIST_URL,
                                     filelist.REQUEST_TIMEOUT_SECONDS)])
        with open(out["path"], "rb") as f:
            data = f.read()
        lines = data.decode("ascii").splitlines()
        self.assertEqual(lines[0], "file_time\tfile_type\tsize_bytes\tmd5")
        times = [l.split("\t")[0] for l in lines[1:]]
        self.assertEqual(times, sorted(times))
        self.assertIn("20201214234500", times)          # 境目の直前は残る
        self.assertNotIn("20201215000000", times)       # 境目のファイルは捨てる
        self.assertNotIn("20201214235000", times)       # 刻みに揃わない境目のファイルも捨てる
        self.assertTrue(all(filelist.parse_file_time(t) for t in times))
        self.assertTrue(all(filelist.file_day(filelist.parse_file_time(t)) < filelist.CUTOFF_DAY
                            for t in times))

    def test_sha256_matches_file_manifest_and_hook(self):
        out, rec = self.run_acq(FakeTransport(FakeResponse(build_list(post_rows(5)))))
        with open(out["path"], "rb") as f:
            sha = hashlib.sha256(f.read()).hexdigest()
        self.assertEqual(out["kept_rows_sha256"], sha)
        self.assertEqual(rec.result_args, [{"start_seq": 7, "kept_rows_sha256": sha}])
        with open(os.path.join(self.manifest_dir, filelist.MANIFEST_NAME), "rb") as f:
            entries = [json.loads(l) for l in f.read().splitlines()]
        self.assertEqual(len(entries), 1)
        e = entries[0]
        self.assertEqual(e["sha256"], sha)
        self.assertEqual(e["source_url"], filelist.MASTERFILELIST_URL)
        self.assertEqual(e["fetched_at"], "2026-10-07T01:02:03Z")
        self.assertEqual(e["acquisition_start_seq"], 7)
        self.assertEqual(e["code_sha256"], filelist.code_sha256())
        self.assertEqual(os.path.join(self.root, *e["file"].split("/")), out["path"])
        self.assertTrue(e["file"].startswith("data/processed/gdelt-filelist/"))

    def test_saved_items_are_allowlist_only(self):
        out, _ = self.run_acq(FakeTransport(FakeResponse(build_list(post_rows(5)))))
        written = self.all_written()
        self.assertEqual(len(written), 2)
        for rel, data in written.items():
            if rel.startswith(os.path.join("data", "manifest")):
                # マニフェストに入る URL は、取得元（データ源）の URL の1件だけ
                self.assertEqual(data.count(b"http"), 1, rel)
                self.assertIn(filelist.MASTERFILELIST_URL.encode(), data)
            else:
                self.assertNotIn(b"http", data, rel)
                self.assertNotIn(b"gdeltproject", data, rel)
        with open(out["path"], "rb") as f:
            lines = f.read().decode("ascii").splitlines()
        for l in lines[1:]:
            ts, kind, size, md5 = l.split("\t")
            self.assertRegex(ts, r"\A\d{14}\Z")
            self.assertIn(kind, ("export", "mentions", "gkg"))
            self.assertRegex(size, r"\A\d+\Z")
            self.assertRegex(md5, r"\A[0-9a-f]{32}\Z")
        # マニフェストの URL は取得元（データ源）の URL だけ
        with open(os.path.join(self.manifest_dir, filelist.MANIFEST_NAME)) as f:
            e = json.loads(f.readline())
        self.assertEqual(set(e), {"file", "sha256", "fetched_at", "source_url", "kept_rows",
                                  "code_sha256", "acquisition_start_seq"})


class TestPostCutoffInvisible(RunCase):
    """2020-12-15 以降の行が、ディスク・出力・ログ・フックの引数のどこにも出ないこと。"""

    def markers(self, post):
        out = []
        for line in post:
            f = line.split()
            if len(f) == 3:
                out += [f[0].encode(), f[1].encode()]
                name = f[2].rsplit("/", 1)[-1]
                out.append(name[:14].encode())
        return [m for m in out if len(m) >= 8]

    def observe(self, post, order="mixed"):
        root_before = self.root
        self.root = tempfile.mkdtemp(prefix="filelist-")
        self.processed = os.path.join(self.root, "data", "processed")
        self.manifest_dir = os.path.join(self.root, "data", "manifest")
        self.logs = []
        self.events = []
        try:
            out, rec = self.run_acq(FakeTransport(FakeResponse(build_list(post, order))))
            files = self.all_written()
            out = dict(out)
            out["path"] = os.path.relpath(out["path"], self.root)
            return {"files": files, "logs": list(self.logs), "out": out,
                    "start": rec.start_args, "result": rec.result_args}
        finally:
            shutil.rmtree(self.root, ignore_errors=True)
            self.root = root_before

    def test_markers_absent(self):
        post = post_rows(200, salt="mark")
        obs = self.observe(post)
        blob = b"\n".join(obs["files"].values())
        text = ("\n".join(obs["logs"]) + repr(obs["out"]) + repr(obs["start"])
                + repr(obs["result"])).encode()
        for m in self.markers(post):
            with self.subTest(m=m):
                self.assertNotIn(m, blob)
                self.assertNotIn(m, text)
        for y in (b"2021", b"2022", b"2023"):
            self.assertNotIn(y, blob)
        self.assertNotIn(b"20201215", blob)

    def test_outputs_independent_of_post_cutoff_rows(self):
        """2020-12-15 以降の行の数や中身を変えても、出るものは1バイトも変わらない。

        捨てた行の件数が、どこにも（ログ・返り値・ファイル・フックの引数）出ていないことの検査。
        """
        variants = [[], post_rows(0, "a"), post_rows(3, "b"), post_rows(5000, "c")]
        observed = [self.observe(v) for v in variants]
        observed.append(self.observe(post_rows(50, "d"), order="sorted"))
        for o in observed[1:]:
            self.assertEqual(o, observed[0])

    def test_errors_do_not_reveal(self):
        """失敗したときの例外の文とログにも、2020-12-15 以降の行が出ない。"""
        post = post_rows(20, salt="err")
        body = build_list(post, order="sorted")
        tr = FakeTransport(*[FakeResponse(body, fail_after=len(body.splitlines()) - 3)
                             for _ in range(filelist.MAX_ATTEMPTS)])
        with self.assertRaises(filelist.FilelistError) as cm:
            self.run_acq(tr)
        text = (str(cm.exception) + "\n".join(self.logs)).encode()
        for m in self.markers(post):
            self.assertNotIn(m, text)
        self.assertEqual(self.all_written(), {})


class TestHookOrder(RunCase):
    def test_start_fetch_result_order(self):
        tr = FakeTransport(FakeResponse(build_list(post_rows(2))), events=self.events)
        out, rec = self.run_acq(tr)
        self.assertEqual(self.events, ["start", "fetch", "result"])
        self.assertEqual(rec.start_args, [{"code_sha256": filelist.code_sha256(),
                                           "source_url": filelist.MASTERFILELIST_URL}])

    def test_start_failure_means_no_fetch(self):
        tr = FakeTransport(FakeResponse(build_list([])), events=self.events)
        rec = Recorder(self.events, start_exc=RuntimeError("封印の失敗"))
        with self.assertRaises(RuntimeError):
            self.run_acq(tr, rec=rec)
        self.assertEqual(self.events, ["start"])
        self.assertEqual(tr.calls, [])
        self.assertEqual(self.all_written(), {})

    def test_start_bad_seq_means_no_fetch(self):
        for seq in (None, 0, -1, True, "3", 1.0):
            with self.subTest(seq=seq):
                self.events.clear()
                tr = FakeTransport(FakeResponse(build_list([])), events=self.events)
                with self.assertRaises(filelist.FilelistError):
                    self.run_acq(tr, rec=Recorder(self.events, seq=seq))
                self.assertEqual(self.events, ["start"])
                self.assertEqual(tr.calls, [])

    def test_bad_url_means_no_start(self):
        tr = FakeTransport(FakeResponse(build_list([])), events=self.events)
        with self.assertRaises(filelist.FilelistError):
            self.run_acq(tr, url="https://gdeltcloud.com/gdeltv2/masterfilelist.txt")
        self.assertEqual(self.events, [])

    def test_fetch_failure_means_no_result(self):
        tr = FakeTransport(FakeResponse(status=404), events=self.events)
        with self.assertRaises(filelist.FilelistError):
            self.run_acq(tr)
        self.assertEqual(self.events, ["start", "fetch"])
        self.assertEqual(self.all_written(), {})

    def test_hooks_are_required(self):
        with self.assertRaises(TypeError):
            filelist.run_acquisition(root=self.root, processed_dir=self.processed,
                                     manifest_dir=self.manifest_dir,
                                     transport=FakeTransport())

    def test_existing_file_not_overwritten(self):
        out, _ = self.run_acq(FakeTransport(FakeResponse(build_list([]))))
        with open(out["path"], "rb") as f:
            before = f.read()
        self.events.clear()
        tr = FakeTransport(FakeResponse(build_list([])), events=self.events)
        with self.assertRaises(filelist.FilelistError):
            self.run_acq(tr)
        self.assertEqual(self.events, [])  # start も呼ばない
        with open(out["path"], "rb") as f:
            self.assertEqual(f.read(), before)

    def test_manifest_is_append_only(self):
        self.run_acq(FakeTransport(FakeResponse(build_list([]))))
        mpath = os.path.join(self.manifest_dir, filelist.MANIFEST_NAME)
        with open(mpath, "rb") as f:
            first = f.read()
        later = FIXED_NOW + datetime.timedelta(hours=1)
        self.run_acq(FakeTransport(FakeResponse(build_list(post_rows(4)))), now=later)
        with open(mpath, "rb") as f:
            both = f.read()
        self.assertTrue(both.startswith(first))
        self.assertEqual(len(both.splitlines()), 2)


class TestRetry(RunCase):
    def test_retry_then_success(self):
        body = build_list(post_rows(3))
        tr = FakeTransport(FakeResponse(status=503), ConnectionResetError("x"),
                           FakeResponse(body))
        out, _ = self.run_acq(tr)
        self.assertEqual(len(tr.calls), 3)
        self.assertEqual(self.sleeps, list(filelist.RETRY_WAIT_SECONDS))
        self.assertEqual(out["kept_rows"], len(PRE_ROWS))

    def test_partial_read_is_discarded(self):
        body = build_list(post_rows(3))
        tr = FakeTransport(FakeResponse(body, fail_after=5), FakeResponse(body))
        out, _ = self.run_acq(tr)
        self.assertEqual(out["kept_rows"], len(PRE_ROWS))  # 重複しない

    def test_attempt_limit(self):
        tr = FakeTransport(*[FakeResponse(status=503) for _ in range(5)], events=self.events)
        with self.assertRaises(filelist.FilelistError):
            self.run_acq(tr)
        self.assertEqual(len(tr.calls), filelist.MAX_ATTEMPTS)
        self.assertNotIn("result", self.events)

    def test_no_retry_on_redirect_or_404(self):
        for status in (301, 302, 307, 308, 403, 404):
            with self.subTest(status=status):
                tr = FakeTransport(FakeResponse(status=status), FakeResponse(build_list([])))
                with self.assertRaises(filelist.FilelistError):
                    self.run_acq(tr)
                self.assertEqual(len(tr.calls), 1)

    def test_retry_after(self):
        tr = FakeTransport(FakeResponse(status=429, headers={"Retry-After": "120"}),
                           FakeResponse(build_list([])))
        self.run_acq(tr)
        self.assertEqual(self.sleeps, [120])
        tr = FakeTransport(FakeResponse(status=429, headers={
            "Retry-After": str(filelist.MAX_RETRY_AFTER_SECONDS + 1)}))
        with self.assertRaises(filelist.FilelistError):
            self.run_acq(tr, now=FIXED_NOW + datetime.timedelta(hours=2))

    def test_deadline(self):
        self.clock.t = 0
        with mock.patch.object(filelist, "TOTAL_DEADLINE_SECONDS", 50):
            tr = FakeTransport(FakeResponse(status=503), FakeResponse(build_list([])))
            with self.assertRaises(filelist.FilelistError):
                self.run_acq(tr)
        self.assertEqual(self.sleeps, [])

    def test_response_size_limit(self):
        with mock.patch.object(filelist, "MAX_RESPONSE_BYTES", 200):
            tr = FakeTransport(FakeResponse(build_list(post_rows(3))))
            with self.assertRaises(filelist.FilelistError):
                self.run_acq(tr)
        self.assertEqual(self.all_written(), {})

    def test_compressed_response_refused(self):
        tr = FakeTransport(FakeResponse(build_list([]), headers={"Content-Encoding": "gzip"}))
        with self.assertRaises(filelist.FilelistError):
            self.run_acq(tr)


class TestPrivacy(RunCase):
    """保存したファイルとログに、メールアドレスの形の文字列が無いこと（privacy_scan を使う）。"""

    def make_address(self):
        return "u" + uuid.uuid4().hex[:8] + "@" + "d" + uuid.uuid4().hex[:8] + ".example"

    def test_files_and_logs_have_no_address(self):
        a1, a2, a3 = self.make_address(), self.make_address(), self.make_address()
        extra_pre = [
            # URL に利用者情報としてアドレスを入れた行（ホストが違うので保存しない）
            "100 %s http://%s/gdeltv2/20160202000000.export.CSV.zip" % (md5_of("q"), a1),
            "%s %s %s20160202001500.export.CSV.zip" % (a2, md5_of("r"), BASE),
        ]
        extra_post = ["100 %s http://%s/gdeltv2/20220202000000.export.CSV.zip"
                      % (md5_of("s"), a3)]
        body = ("\n".join(PRE_ROWS + extra_pre + extra_post) + "\n").encode()
        out, rec = self.run_acq(FakeTransport(FakeResponse(body)))
        files = self.all_written()
        self.assertTrue(files)
        for rel, data in files.items():
            self.assertEqual(privacy_scan.find_in_bytes(data), {}, rel)
        log_bytes = "\n".join(self.logs).encode()
        self.assertEqual(privacy_scan.find_in_bytes(log_bytes), {})
        for a in (a1, a2, a3):
            for part in a.split("@"):
                self.assertNotIn(part.encode(), b"".join(files.values()) + log_bytes)

    def test_privacy_scan_cli_on_written_tree(self):
        self.run_acq(FakeTransport(FakeResponse(build_list(post_rows(10)))))
        with open(os.path.join(self.root, "run.log"), "w", encoding="utf-8") as f:
            f.write("\n".join(self.logs) + "\n")
        proc = subprocess.run([sys.executable, "-B", PRIVACY_SCRIPT, "--root", self.root],
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)

    def test_refuses_to_write_address(self):
        a = self.make_address()
        with mock.patch.object(filelist, "serialize_rows", lambda rows: a.encode() + b"\n"):
            with self.assertRaises(filelist.FilelistError) as cm:
                self.run_acq(FakeTransport(FakeResponse(build_list([]))))
        self.assertNotIn(a, str(cm.exception))
        self.assertEqual(self.all_written(), {})

    def test_source_has_no_address(self):
        for p in (os.path.join(SRC, "filelist.py"), os.path.abspath(__file__)):
            with open(p, "rb") as f:
                self.assertEqual(privacy_scan.find_in_bytes(f.read()), {}, p)


class TestNoNetworkGuard(unittest.TestCase):
    def test_guard_active(self):
        with self.assertRaises(NetworkUsed):
            socket.create_connection(("192.0.2.1", 443), timeout=1)


if __name__ == "__main__":
    unittest.main()
