"""GDELT のファイル一覧の取得（src/collector/filelist.py）のテスト。T-010、T-012。

実行（プロジェクトのルートで。__pycache__ を作らないよう、必ず次の形で）:
    PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest discover -s tests/collector -v

書き込みと出力の見張りは二段ある。
  - 子プロセスの見張り（ChildRun、filelist_child.py）：取得の本体を子プロセスで動かし、
    sys.addaudithook で書き込みのモードの open・os.mkdir・os.symlink・os.rename・
    subprocess.Popen・os.system・os.posix_spawn・sqlite3.connect・ctypes.dlopen ほか
    （filelist_child.BLOCKED_EVENTS）を止める。許すのは本体の保存先のファイルとマニフェストへの
    書き込みだけ。stdout・stderr（記述子 1・2）は親がパイプで受け取って比べる。
    2020-12-15 以降の行が出ないことの検査（TestPostCutoffInvisible）と、監査 B-2 の変異の検査
    （TestChildGuard）は、この形で動かす。
  - 同じプロセスの見張り（IOGuard）：それ以外のテスト（再試行・フックの順番・保存先の確認など）
    で使う補助。builtins.open・io.open・os.open と tempfile の関数だけを差し替えるので、
    _io.FileIO・os.makedirs・os.symlink・subprocess・sqlite3 などの経路は見ていない。

ネットワークは使わない。モジュールの読み込みの時点で socket の接続を塞ぎ、
通信を試みたら失敗するようにしている。通信の部分は、作った見本の一覧を返す
差し替えの関数（FakeTransport）に置き換える。見本の行は、実在のファイル名に似せた
架空の行である（md5 と大きさは作った値）。

このファイルには、メールアドレスの形の文字列をそのまま書かない。必要なときは、
実行中に部品を組み立てて作る。
"""

import builtins
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
CHILD_SCRIPT = os.path.join(HERE, "filelist_child.py")


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


def extreme_rows(salt="x"):
    """暦の最後に近い、極端な時刻の行（2020-12-15 以降。t + 15分 で日付を作れないものを含む）。"""
    return [
        row("99991231234500", "export", size=987654311, md5=md5_of(salt, "x1")),
        row("99991231234501", "export", size=987654312, md5=md5_of(salt, "x2")),
        row("99991231235959", "gkg", size=987654313, md5=md5_of(salt, "x3")),
        "1 2 %s99991231235959.export.CSV.zip" % BASE,
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
    ] + extreme_rows(salt)
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
    def __init__(self, body=b"", status=200, headers=None, fail_after=None, fail_at_eof=False,
                 on_read=None):
        self._buf = io.BytesIO(body)
        self.status = status
        self.headers = FakeHeaders(headers or {})
        self._fail_after = fail_after
        self._fail_at_eof = fail_at_eof
        self._on_read = on_read
        self._reads = 0
        self.closed = False

    def readline(self, limit=-1):
        self._reads += 1
        if self._fail_after is not None and self._reads > self._fail_after:
            raise ConnectionResetError("見本の失敗")
        if self._on_read is not None:
            self._on_read()
        line = self._buf.readline(limit)
        if not line and self._fail_at_eof:
            raise ConnectionResetError("見本の失敗（終わりの直前）")
        return line

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


class GuardViolation(BaseException):
    """許していない書き込み。BaseException にして、取得のコードの except に捕まらないようにする。"""


_WRITE_FLAGS = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_APPEND | os.O_TRUNC


class IOGuard:
    """取得のあいだ、出力と書き込みを見張る。

    - sys.stdout と sys.stderr を StringIO に差し替え、さらにファイル記述子 1 と 2 も
      一時ファイルに付け替えて、中身を取り込む（os.write(2, ...) のような経路も拾う）。
    - builtins.open、io.open、os.open を差し替え、書き込みのモードで開くのは allowed の
      パスだけを許す。それ以外は GuardViolation にし、violations にも記録する。
    - tempfile の関数は、呼ばれた時点で GuardViolation にする。

    見ていない経路：_io.FileIO、os.makedirs・os.mkdir、os.symlink、os.rename、subprocess、
    sqlite3、ctypes など。これらは子プロセスの見張り（ChildRun）で止める。
    """

    TEMPFILE_FUNCS = ("mkstemp", "mkdtemp", "NamedTemporaryFile", "TemporaryFile",
                      "SpooledTemporaryFile", "TemporaryDirectory", "mktemp")

    def __init__(self, allowed):
        self.allowed = {os.path.realpath(p) for p in allowed}
        self.violations = []
        self.stdout = ""
        self.stderr = ""
        self.fd_output = b""

    def _check(self, path, writing):
        if not writing or isinstance(path, int):
            return
        rp = os.path.realpath(os.fspath(path))
        if rp not in self.allowed:
            self.violations.append(rp)
            raise GuardViolation("許していない書き込み")

    def __enter__(self):
        self._sink = tempfile.TemporaryFile()  # 見張りを始める前に作る
        sys.stdout.flush()
        sys.stderr.flush()
        self._saved_fds = (os.dup(1), os.dup(2))
        os.dup2(self._sink.fileno(), 1)
        os.dup2(self._sink.fileno(), 2)
        self._out, self._err = io.StringIO(), io.StringIO()
        self._saved_std = (sys.stdout, sys.stderr)
        sys.stdout, sys.stderr = self._out, self._err

        real_open, real_os_open = builtins.open, os.open
        guard = self

        def g_open(file, mode="r", *a, **k):
            guard._check(file, any(c in mode for c in "wax+"))
            return real_open(file, mode, *a, **k)

        def g_os_open(path, flags, *a, **k):
            guard._check(path, bool(flags & _WRITE_FLAGS))
            return real_os_open(path, flags, *a, **k)

        def g_temp(*a, **k):
            guard.violations.append("tempfile")
            raise GuardViolation("tempfile は使えない")

        self._patches = [mock.patch.object(builtins, "open", g_open),
                         mock.patch.object(io, "open", g_open),
                         mock.patch.object(os, "open", g_os_open)]
        self._patches += [mock.patch.object(tempfile, n, g_temp) for n in self.TEMPFILE_FUNCS]
        for p in self._patches:
            p.start()
        return self

    def __exit__(self, *exc):
        for p in reversed(self._patches):
            p.stop()
        sys.stdout, sys.stderr = self._saved_std
        os.dup2(self._saved_fds[0], 1)
        os.dup2(self._saved_fds[1], 2)
        for fd in self._saved_fds:
            os.close(fd)
        self.stdout, self.stderr = self._out.getvalue(), self._err.getvalue()
        self._sink.seek(0)
        self.fd_output = self._sink.read()
        self._sink.close()
        return False

    def captured(self):
        return {"stdout": self.stdout, "stderr": self.stderr, "fd": self.fd_output,
                "violations": list(self.violations)}


def written_files(**dirs):
    found = {}
    for label, top in dirs.items():
        for d, subdirs, files in os.walk(top):
            for f in files + [x for x in subdirs if os.path.islink(os.path.join(d, x))]:
                p = os.path.join(d, f)
                key = "%s/%s" % (label, os.path.relpath(p, top).replace(os.sep, "/"))
                if os.path.islink(p):
                    found[key] = ("link", os.readlink(p))
                else:
                    with open(p, "rb") as fh:
                        found[key] = fh.read()
    return found


class RunCase(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="filelist-")
        self.manifest_dir = os.path.join(self.root, "data", "manifest")
        os.makedirs(self.manifest_dir)
        # 本体の保存先は root の外（Git の外）
        self.store = tempfile.mkdtemp(prefix="filelist-store-")
        self._store_tmp = self.store  # テストが self.store を差し替えても、これを片付ける
        self.logs = []
        self.sleeps = []
        self.events = []
        self.clock = FakeClock()

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)
        shutil.rmtree(self._store_tmp, ignore_errors=True)

    def sleep(self, s):
        self.sleeps.append(s)
        self.clock.t += s

    def expected_path(self, t):
        return os.path.join(os.path.realpath(self.store),
                            "masterfilelist-kept-%s.tsv" % t.strftime("%Y%m%dT%H%M%SZ"))

    def manifest_path(self):
        return os.path.join(self.manifest_dir, filelist.MANIFEST_NAME)

    def run_acq(self, transport, rec=None, now=FIXED_NOW, url=filelist.MASTERFILELIST_URL,
                guard=True):
        """取得を1回動かす。now は datetime か、datetime の list（呼ばれるたびに順に返す）。

        guard=True なら IOGuard の中で動かす。書いてよいのは、最初の now の時刻の名前の
        保存先と、マニフェストだけ。見張りの結果は self.guard に残る。
        """
        rec = rec or Recorder(self.events)
        times = list(now) if isinstance(now, list) else None
        first = times[0] if times else now
        now_fn = (lambda: times.pop(0)) if times else (lambda: now)
        allowed = [self.expected_path(first), self.manifest_path()]
        self.guard = IOGuard(allowed) if guard else None

        def call():
            return filelist.run_acquisition(
                start_hook=rec.start, result_hook=rec.result, root=self.root,
                manifest_dir=self.manifest_dir, store_dir=self.store, url=url,
                transport=transport, sleep=self.sleep, clock=self.clock,
                now=now_fn, log=self.logs.append)

        if self.guard is None:
            return call(), rec
        try:
            with self.guard:
                out = call()
        finally:
            # 例外で終わった場合も、許していない書き込みが無かったことを確かめる
            if self.guard.violations:
                raise AssertionError("許していない書き込み：%r" % self.guard.violations)
        return out, rec

    def all_written(self):
        """root と本体の保存先の下のすべてのファイル（"root/…"・"store/…" → 中身）。

        シンボリックリンクは辿らず、リンクとして記録する。
        """
        return written_files(root=self.root, store=self.store)


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

    def test_env_proxy_not_used(self):
        """環境変数にプロキシがあっても使わない。"""
        env = {k: "http://proxy.invalid:9" for k in
               ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY", "all_proxy",
                "ALL_PROXY")}
        with mock.patch.dict(os.environ, env):
            self.assertTrue(urllib.request.getproxies())  # 前提：環境変数が読まれる状態
            opener = filelist.build_opener()
        # ProxyHandler({}) は処理する方式を持たないので、opener の一覧には入らない。
        # 既定の ProxyHandler（環境変数を読む）が入っていれば、proxies が空でなくなる。
        used = [h for h in opener.handlers
                if isinstance(h, urllib.request.ProxyHandler) and h.proxies]
        self.assertEqual(used, [])
        self.assertFalse(any(hasattr(h, "https_open") and isinstance(
            h, urllib.request.ProxyHandler) for h in opener.handlers))


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
        with open(self.manifest_path(), "rb") as f:
            entries = [json.loads(l) for l in f.read().splitlines()]
        self.assertEqual(len(entries), 1)
        e = entries[0]
        self.assertEqual(e["sha256"], sha)
        self.assertEqual(e["kept_rows"], len(PRE_ROWS))
        self.assertEqual(e["source_url"], filelist.MASTERFILELIST_URL)
        self.assertEqual(e["fetched_at"], "2026-10-07T01:02:03Z")
        self.assertEqual(e["acquisition_start_seq"], 7)
        self.assertEqual(e["code_sha256"], filelist.code_sha256())
        self.assertEqual(e["file_name"], os.path.basename(out["path"]))
        self.assertEqual(out["path"], self.expected_path(FIXED_NOW))
        with open(out["path"], "rb") as f:
            self.assertEqual(len(f.read().splitlines()), e["kept_rows"] + 1)  # 見出しの1行

    def test_saved_items_are_allowlist_only(self):
        out, _ = self.run_acq(FakeTransport(FakeResponse(build_list(post_rows(5)))))
        written = self.all_written()
        self.assertEqual(sorted(written), ["root/data/manifest/" + filelist.MANIFEST_NAME,
                                           "store/" + os.path.basename(out["path"])])
        for rel, data in written.items():
            if rel.startswith("root/"):
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
        with open(self.manifest_path()) as f:
            e = json.loads(f.readline())
        self.assertEqual(set(e), {"file_name", "sha256", "fetched_at", "source_url",
                                  "kept_rows", "code_sha256", "acquisition_start_seq"})
        self.assertEqual(tuple(sorted(e)), filelist.MANIFEST_KEYS)


class ChildRun:
    """取得の本体を子プロセス（filelist_child.py）で、audit hook の見張りの下で1回動かす。

    root（data/manifest を持つ）と本体の保存先 store と、変異の書き込み先 outside を、
    それぞれ新しい一時フォルダに作る。返り値の "files" は root・store・outside の下の全ファイル。
    """

    def __init__(self, testcase):
        self.tc = testcase

    def __call__(self, responses, now=(FIXED_NOW,), mutation=None, seq=7,
                 url=filelist.MASTERFILELIST_URL):
        tops = {k: tempfile.mkdtemp(prefix="filelist-child-%s-" % k)
                for k in ("root", "store", "outside")}
        try:
            manifest_dir = os.path.join(tops["root"], "data", "manifest")
            os.makedirs(manifest_dir)
            name = "masterfilelist-kept-%s.tsv" % now[0].strftime("%Y%m%dT%H%M%SZ")
            report = tempfile.TemporaryFile()
            try:
                cfg = {
                    "report_fd": report.fileno(),
                    "filelist_path": os.path.join(SRC, "filelist.py"),
                    "root": tops["root"], "manifest_dir": manifest_dir,
                    "store_dir": tops["store"], "outside": tops["outside"], "url": url,
                    "allowed": [os.path.join(tops["store"], name),
                                os.path.join(manifest_dir, filelist.MANIFEST_NAME)],
                    "responses": [self._spec(r) for r in responses],
                    "now": [t.isoformat() for t in now], "mutation": mutation, "seq": seq,
                }
                env = {k: v for k, v in os.environ.items() if k != filelist.STORE_ENV}
                env["PYTHONDONTWRITEBYTECODE"] = "1"
                proc = subprocess.run([sys.executable, "-B", CHILD_SCRIPT],
                                      input=json.dumps(cfg).encode(), stdout=subprocess.PIPE,
                                      stderr=subprocess.PIPE, pass_fds=(report.fileno(),),
                                      env=env, timeout=120)
                report.seek(0)
                raw = report.read()
            finally:
                report.close()
            self.tc.assertEqual(proc.returncode, 0, proc.stderr.decode(errors="replace"))
            rep = json.loads(raw)
            return {"report": rep, "stdout": proc.stdout, "stderr": proc.stderr,
                    "files": written_files(**tops)}
        finally:
            for t in tops.values():
                shutil.rmtree(t, ignore_errors=True)

    @staticmethod
    def _spec(r):
        if isinstance(r, BaseException):
            return {"exc": type(r).__name__}
        return {"body": __import__("base64").b64encode(r._buf.getvalue()).decode("ascii"),
                "status": r.status, "headers": dict(r.headers),
                "fail_after": r._fail_after, "fail_at_eof": r._fail_at_eof}


class TestPostCutoffInvisible(unittest.TestCase):
    """2020-12-15 以降の行が、ディスク・出力・ログ・フックの引数のどこにも出ないこと。

    取得は子プロセス（ChildRun）で、audit hook の見張りの下で動かす。
    """

    def setUp(self):
        self.child = ChildRun(self)

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
        obs = self.child([FakeResponse(build_list(post, order))])
        self.assertEqual(obs["report"]["violations"], [])
        self.assertIsNone(obs["report"]["error"])
        return obs

    def test_markers_absent(self):
        post = post_rows(200, salt="mark")
        obs = self.observe(post)
        blob = b"\n".join(v for v in obs["files"].values() if isinstance(v, bytes))
        r = obs["report"]
        text = (json.dumps(r, ensure_ascii=False).encode() + obs["stdout"] + obs["stderr"])
        for m in self.markers(post):
            with self.subTest(m=m):
                self.assertNotIn(m, blob)
                self.assertNotIn(m, text)
        for y in (b"2021", b"2022", b"2023"):
            self.assertNotIn(y, blob)
        self.assertNotIn(b"20201215", blob)

    def test_outputs_independent_of_post_cutoff_rows(self):
        """2020-12-15 以降の行の数や中身を変えても、出るものは1バイトも変わらない。

        比べるもの：root・本体の保存先・変異の書き込み先の下の全ファイル（名前と中身）、
        ログ、返り値、フックの引数、子プロセスの stdout・stderr（記述子 1・2 に書かれた
        すべて）、audit hook の見張りの記録（許していない書き込みや操作の試み）。
        子プロセスの記述子は 0・1・2 と結果を返す記述子だけで、ほかの記述子への出力の
        経路は無い（filelist_child.py の「見張りの範囲」）。
        捨てた行の件数が、これらのどこにも出ていないことの検査。
        """
        variants = [[], extreme_rows("e"), post_rows(0, "a"), post_rows(3, "b"),
                    post_rows(5000, "c")]
        observed = [self.observe(v) for v in variants]
        observed.append(self.observe(post_rows(50, "d"), order="sorted"))
        for o in observed[1:]:
            self.assertEqual(o, observed[0])
        self.assertEqual(observed[0]["stdout"], b"")
        self.assertEqual(observed[0]["stderr"], b"")

    def test_errors_do_not_reveal(self):
        """失敗したときの例外の文とログにも、2020-12-15 以降の行が出ない。"""
        post = post_rows(20, salt="err")
        body = build_list(post, order="sorted")
        obs = self.child([FakeResponse(body, fail_after=len(body.splitlines()) - 3)
                          for _ in range(filelist.MAX_ATTEMPTS)])
        r = obs["report"]
        self.assertEqual(r["error"][0], "FilelistError")
        self.assertEqual(r["violations"], [])
        text = json.dumps(r, ensure_ascii=False).encode() + obs["stdout"] + obs["stderr"]
        for m in self.markers(post):
            self.assertNotIn(m, text)
        self.assertEqual(obs["files"], {})

    def observe_error(self, post):
        """読みの途中で失敗する取得を動かし、外に出たもの（例外の文を含む）を返す。"""
        body = build_list(post, order="sorted")
        # すべての行を読んだあと、終わりの直前で通信が切れる（3回とも）
        obs = self.child([FakeResponse(body, fail_at_eof=True)
                          for _ in range(filelist.MAX_ATTEMPTS)])
        self.assertEqual(obs["report"]["error"][0], "FilelistError")
        return obs

    def test_error_outputs_independent_of_post_cutoff_rows(self):
        """失敗した場合も、出るもの（例外の文、stdout・stderr を含む）は 2020-12-15 以降の行で
        変わらない。"""
        obs = [self.observe_error(p) for p in
               ([], extreme_rows("f"), post_rows(10, "g"), post_rows(300, "h"))]
        for o in obs[1:]:
            self.assertEqual(o, obs[0])

    def test_extreme_rows_do_not_raise(self):
        for r in extreme_rows("z"):
            self.assertFalse(filelist._is_kept_line(r.encode()))
        t = filelist.parse_file_time("99991231234501")
        self.assertEqual(filelist.file_day(t), datetime.date.max)


class TestChildGuard(unittest.TestCase):
    """子プロセスの見張りが、監査 B-2 の変異を捕まえること。"""

    def setUp(self):
        self.child = ChildRun(self)

    def test_clean_run_has_no_violation(self):
        obs = self.child([FakeResponse(build_list(post_rows(3)))])
        r = obs["report"]
        self.assertIsNone(r["error"])
        self.assertEqual(r["violations"], [])
        self.assertEqual(sorted(obs["files"]),
                         ["root/data/manifest/" + filelist.MANIFEST_NAME,
                          "store/" + r["out"]["file_name"]])
        self.assertEqual((obs["stdout"], obs["stderr"]), (b"", b""))

    def test_write_mutations_are_caught(self):
        expected = {
            "fileio": "open", "makedirs": "os.mkdir", "symlink": "os.symlink",
            "rename": "os.rename", "subprocess": "subprocess.Popen", "system": "os.system",
            "posix_spawn": "os.posix_spawn", "sqlite3": "sqlite3.connect",
            "ctypes": "ctypes.dlopen", "open_append": "open", "os_open": "open",
        }
        for mutation, event in expected.items():
            with self.subTest(mutation=mutation):
                obs = self.child([FakeResponse(build_list(post_rows(2)))], mutation=mutation)
                events = [v[0] for v in obs["report"]["violations"]]
                self.assertIn(event, events)
                # 変異の書き込み先には何もできていない
                self.assertEqual([k for k in obs["files"] if k.startswith("outside/")], [])

    def test_output_mutations_are_visible(self):
        """stdout・記述子 2 への出力は、親が受け取るので、比べる検査で必ず差になる。"""
        obs = self.child([FakeResponse(build_list([]))], mutation="print")
        self.assertIn(b"MUTATION-STDOUT", obs["stdout"])
        obs = self.child([FakeResponse(build_list([]))], mutation="stderr_fd")
        self.assertIn(b"MUTATION-FD2", obs["stderr"])


class TestStorageLocation(RunCase):
    """本体は Git の外、リポジトリの中にはマニフェストだけ（T-012）。監査 B-3 の再現を拒む。"""

    def outside_dir(self):
        d = tempfile.mkdtemp(prefix="filelist-outside-")
        self.addCleanup(shutil.rmtree, d, True)
        return d

    def refuse(self, before_start=True, **kw):
        self.events.clear()
        tr = kw.pop("transport", None) or FakeTransport(FakeResponse(build_list([])),
                                                        events=self.events)
        with self.assertRaises(filelist.FilelistError):
            self.run_acq(tr, guard=False, **kw)
        if before_start:
            self.assertEqual(self.events, [])
        self.assertNotIn("result", self.events)

    def test_body_outside_git_only_manifest_inside(self):
        os.makedirs(os.path.join(self.root, ".git"))  # root を Git の作業ツリーに見立てる
        before = written_files(root=self.root)
        out, _ = self.run_acq(FakeTransport(FakeResponse(build_list(post_rows(4)))))
        after = written_files(root=self.root)
        self.assertEqual(sorted(set(after) - set(before)),
                         ["root/data/manifest/" + filelist.MANIFEST_NAME])
        store = written_files(store=self.store)
        self.assertEqual(sorted(store), ["store/" + out["file_name"]])
        self.assertFalse(filelist._is_strictly_under(os.path.realpath(out["path"]),
                                                     os.path.realpath(self.root)))
        with open(self.manifest_path()) as f:
            lines = f.read().splitlines()
        self.assertEqual(len(lines), 1)
        e = json.loads(lines[0])
        self.assertEqual(e["file_name"], out["file_name"])
        self.assertEqual(e["sha256"], hashlib.sha256(store["store/" + out["file_name"]])
                         .hexdigest())

    def test_default_store_dir_is_outside_project(self):
        """既定は Path.home() / "news-stick-data" / "gdelt-filelist"（オーナーの決定）。

        実際のホームには触れない。Path.home を一時フォルダに差し替えて確かめる。
        """
        fake_home = self.outside_dir()
        with mock.patch.object(filelist.pathlib.Path, "home",
                               classmethod(lambda cls: cls(fake_home))):
            d = filelist.default_store_dir({})
        self.assertEqual(d, os.path.join(fake_home, "news-stick-data", "gdelt-filelist"))
        with open(os.path.join(SRC, "filelist.py"), encoding="utf-8") as f:
            src = f.read()
        self.assertIn('DEFAULT_STORE_PARTS = ("news-stick-data", "gdelt-filelist")', src)
        self.assertIn("pathlib.Path.home().joinpath(*DEFAULT_STORE_PARTS)", src)
        # 実際の既定（書かずに場所だけ計算する）も、プロジェクトの外
        d = filelist.default_store_dir({})
        real_project = os.path.realpath(PROJECT)
        self.assertFalse(filelist._is_strictly_under(os.path.realpath(d), real_project))
        self.assertNotEqual(os.path.realpath(d), real_project)
        self.assertNotIn(os.path.join("data", "raw"), d)
        self.assertEqual(filelist.default_store_dir({filelist.STORE_ENV: "/x/y"}), "/x/y")

    def test_default_store_dir_used_when_none(self):
        """store_dir も環境変数も無いときは既定の場所に書く（Path.home を一時フォルダに差し替え）。"""
        fake_home = self.outside_dir()
        default = os.path.join(fake_home, "news-stick-data", "gdelt-filelist")
        os.makedirs(default)
        self.store = None
        rec = Recorder(self.events)
        env = {k: v for k, v in os.environ.items() if k != filelist.STORE_ENV}
        with mock.patch.dict(os.environ, env, clear=True), \
                mock.patch.object(filelist.pathlib.Path, "home",
                                  classmethod(lambda cls: cls(fake_home))):
            out = filelist.run_acquisition(
                start_hook=rec.start, result_hook=rec.result, root=self.root,
                manifest_dir=self.manifest_dir,
                transport=FakeTransport(FakeResponse(build_list([]))), sleep=self.sleep,
                clock=self.clock, now=lambda: FIXED_NOW, log=self.logs.append)
        self.assertEqual(os.path.dirname(out["path"]), os.path.realpath(default))
        self.assertEqual(os.listdir(default), [out["file_name"]])

    def test_store_dir_from_env(self):
        rec = Recorder(self.events)
        with mock.patch.dict(os.environ, {filelist.STORE_ENV: self.store}):
            out = filelist.run_acquisition(
                start_hook=rec.start, result_hook=rec.result, root=self.root,
                manifest_dir=self.manifest_dir,
                transport=FakeTransport(FakeResponse(build_list([]))), sleep=self.sleep,
                clock=self.clock, now=lambda: FIXED_NOW, log=self.logs.append)
        self.assertEqual(out["path"], self.expected_path(FIXED_NOW))

    def test_store_under_root_refused(self):
        raw = os.path.join(self.root, "data", "raw")
        os.makedirs(raw)
        for store in (raw, self.root, os.path.join(self.root, "data")):
            with self.subTest(store=store):
                self.store = store
                self.refuse()
        self.assertEqual(written_files(root=self.root), {})

    def test_store_symlink_into_root_refused(self):
        """保存先をリンクで root の中に向けても、realpath で比べるので拒む。"""
        raw = os.path.join(self.root, "data", "raw")
        os.makedirs(raw)
        link = os.path.join(self.outside_dir(), "store-link")
        os.symlink(raw, link)
        self.store = link
        self.refuse()
        self.assertEqual(os.listdir(raw), [])

    def test_store_inside_git_worktree_refused(self):
        other = self.outside_dir()
        for git in ("dir", "file"):
            with self.subTest(git=git):
                repo = tempfile.mkdtemp(prefix="filelist-repo-", dir=other)
                g = os.path.join(repo, ".git")
                if git == "dir":
                    os.makedirs(g)
                else:
                    with open(g, "w") as f:
                        f.write("gitdir: elsewhere\n")
                self.store = os.path.join(repo, "a", "b")
                os.makedirs(self.store)
                self.refuse()

    def test_missing_store_dir_refused(self):
        """保存先のフォルダは作らない（無ければ取得の前に止まる）。"""
        self.store = os.path.join(self.outside_dir(), "missing")
        self.refuse()
        self.assertFalse(os.path.lexists(self.store))

    def test_manifest_dir_outside_root_refused(self):
        outside = self.outside_dir()
        self.manifest_dir = outside
        self.refuse()
        self.assertEqual(os.listdir(outside), [])

    def test_manifest_dir_symlink_to_outside_refused(self):
        """監査 B-3 の再現：root の中のリンクで、マニフェストのフォルダを root の外に向ける。"""
        outside = self.outside_dir()
        link = os.path.join(self.root, "data", "manifest-link")
        os.symlink(outside, link)
        self.manifest_dir = link
        self.refuse()
        self.assertEqual(os.listdir(outside), [])

    def test_manifest_file_symlink_refused(self):
        """監査 B-3 の再現：マニフェストのファイルを root の外へのリンクにする。"""
        target = os.path.join(self.outside_dir(), "victim.jsonl")
        with open(target, "wb") as f:
            f.write(b'{"old": 1}\n')
        os.symlink(target, self.manifest_path())
        self.refuse()
        with open(target, "rb") as f:
            self.assertEqual(f.read(), b'{"old": 1}\n')
        self.assertEqual(os.listdir(self.store), [])

    def test_manifest_file_swapped_to_symlink_during_fetch(self):
        """取得のあいだにマニフェストがリンクになっても、O_NOFOLLOW で追記しない。"""
        target = os.path.join(self.outside_dir(), "victim.jsonl")
        with open(target, "wb") as f:
            f.write(b'{"old": 1}\n')

        def transport(url, timeout):
            os.symlink(target, self.manifest_path())
            return FakeResponse(build_list([]))

        self.refuse(before_start=False, transport=transport)
        with open(target, "rb") as f:
            self.assertEqual(f.read(), b'{"old": 1}\n')
        self.assertTrue(os.path.islink(self.manifest_path()))

    def test_store_link_repointed_during_fetch(self):
        """取得のあいだに保存先のリンクを root の中に向け直しても、書く直前の確認で止まる。"""
        real_store = self.store
        raw = os.path.join(self.root, "data", "raw")
        os.makedirs(raw)
        link = os.path.join(self.outside_dir(), "store-link")
        os.symlink(real_store, link)
        self.store = link

        def transport(url, timeout):
            tmp = link + ".new"
            os.symlink(raw, tmp)
            os.replace(tmp, link)
            return FakeResponse(build_list([]))

        self.refuse(before_start=False, transport=transport)
        self.assertEqual(os.listdir(raw), [])
        self.assertEqual(os.listdir(real_store), [])
        self.assertFalse(os.path.exists(self.manifest_path()))

    def test_planned_name_is_symlink_refused(self):
        """本体の名前に、保存先の外へのリンクが置かれていたら、辿らずに止まる。"""
        target = os.path.join(self.outside_dir(), "victim.tsv")
        with open(target, "wb") as f:
            f.write(b"victim\n")
        os.symlink(target, self.expected_path(FIXED_NOW))
        self.refuse()

        def transport(url, timeout):  # 書く直前にリンクが置かれる場合
            return FakeResponse(build_list([]))
        os.replace(self.expected_path(FIXED_NOW), os.path.join(self.store, "moved-link"))

        def racing(url, timeout):
            os.symlink(target, self.expected_path(FIXED_NOW))
            return transport(url, timeout)

        self.refuse(before_start=False, transport=racing)
        with open(target, "rb") as f:
            self.assertEqual(f.read(), b"victim\n")
        self.assertFalse(os.path.exists(self.manifest_path()))

    def test_manifest_has_no_abs_path_or_username(self):
        out, _ = self.run_acq(FakeTransport(FakeResponse(build_list(post_rows(2)))))
        with open(self.manifest_path(), "rb") as f:
            line = f.read().decode("ascii")
        e = json.loads(line)
        home = os.path.expanduser("~")
        for p in (self.root, os.path.realpath(self.root), self.store,
                  os.path.realpath(self.store), home, os.path.realpath(home), out["path"]):
            self.assertNotIn(p, line)
        users = {os.path.basename(home)}
        try:
            users.add(__import__("getpass").getuser())
        except Exception:
            pass
        for key in ("file_name", "fetched_at", "source_url"):
            for u in users:
                self.assertNotIn(u, e[key])
        # パスの区切りが出るのは、取得元の URL の中だけ
        self.assertNotIn("/", e["file_name"])
        self.assertNotIn(os.sep, json.dumps({k: v for k, v in e.items() if k != "source_url"}))
        self.assertRegex(e["file_name"], filelist.STORE_NAME_RE)

    def test_manifest_check_refuses_local_info(self):
        paths = filelist._resolve_paths(self.root, self.manifest_dir, self.store)
        good = {"file_name": "masterfilelist-kept-20261007T010203Z.tsv", "sha256": "0" * 64,
                "kept_rows": 1, "fetched_at": "2026-10-07T01:02:03Z",
                "source_url": filelist.MASTERFILELIST_URL, "acquisition_start_seq": 1,
                "code_sha256": "0" * 64}

        def line(e):
            return (json.dumps(e, sort_keys=True) + "\n").encode("ascii")

        filelist._check_manifest_entry(good, line(good), paths)
        bad_entries = [
            dict(good, file_name=os.path.join(paths["store_dir"], good["file_name"])),
            dict(good, file_name="../" + good["file_name"]),
            dict(good, extra=paths["store_dir"]),
            dict(good, source_url="https://gdeltcloud.com/gdeltv2/masterfilelist.txt"),
        ]
        for e in bad_entries:
            with self.subTest(e=e):
                with self.assertRaises(filelist.FilelistError):
                    filelist._check_manifest_entry(e, line(e), paths)
        # 決めた項目の中に手元のパスが紛れた場合（行の文字列で調べる）
        with self.assertRaises(filelist.FilelistError):
            filelist._check_manifest_entry(good, line(good)[:-1] + paths["root"].encode()
                                           + b"\n", paths)
        with mock.patch.object(filelist.getpass, "getuser", lambda: "kept"):
            with self.assertRaises(filelist.FilelistError):
                filelist._check_manifest_entry(good, line(good), paths)


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
            filelist.run_acquisition(root=self.root, store_dir=self.store,
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

    def test_name_fixed_before_start(self):
        """名前は start の前の時刻で一度だけ決める。fetched_at は取得の完了の時刻。"""
        t1, t2 = FIXED_NOW, FIXED_NOW + datetime.timedelta(minutes=7)
        out, _ = self.run_acq(FakeTransport(FakeResponse(build_list([]))), now=[t1, t2])
        self.assertEqual(out["path"], self.expected_path(t1))
        self.assertEqual(out["fetched_at"], "2026-10-07T01:09:03Z")

    def test_existing_file_with_planned_name(self):
        """前もっての確認と書き込みで同じ名前を使う（後の時刻の名前が既にあっても関係ない）。"""
        t1, t2 = FIXED_NOW, FIXED_NOW + datetime.timedelta(minutes=7)
        with open(self.expected_path(t2), "wb") as f:
            f.write(b"other\n")
        out, _ = self.run_acq(FakeTransport(FakeResponse(build_list([]))), now=[t1, t2])
        self.assertEqual(out["path"], self.expected_path(t1))
        with open(self.expected_path(t1), "wb") as f:
            pass
        self.events.clear()
        tr = FakeTransport(FakeResponse(build_list([])), events=self.events)
        with self.assertRaises(filelist.FilelistError):
            self.run_acq(tr, now=[t1, t2])
        self.assertEqual(self.events, [])

    def test_collision_at_write_is_filelist_error(self):
        """書く直前に同じ名前ができていた場合も、FilelistError で止まり、上書きしない。"""
        path = self.expected_path(FIXED_NOW)

        def racing_transport(url, timeout):
            with open(path, "wb") as f:
                f.write(b"racer\n")
            return FakeResponse(build_list([]))

        with self.assertRaises(filelist.FilelistError):
            self.run_acq(racing_transport, rec=Recorder(self.events))
        with open(path, "rb") as f:
            self.assertEqual(f.read(), b"racer\n")
        self.assertNotIn("result", self.events)

    def test_manifest_without_trailing_newline(self):
        mpath = self.manifest_path()
        with open(mpath, "wb") as f:
            f.write(b'{"a": 1}')
        tr = FakeTransport(FakeResponse(build_list([])), events=self.events)
        with self.assertRaises(filelist.FilelistError):
            self.run_acq(tr)
        self.assertEqual(self.events, [])
        with open(mpath, "rb") as f:
            self.assertEqual(f.read(), b'{"a": 1}')

    def test_manifest_newline_checked_again_before_append(self):
        """取得のあいだに改行の無い行が足された場合も、追記しない。"""
        mpath = self.manifest_path()

        def transport(url, timeout):
            with open(mpath, "ab") as f:
                f.write(b'{"b": 2}')
            return FakeResponse(build_list([]))

        with self.assertRaises(filelist.FilelistError):
            self.run_acq(transport)
        with open(mpath, "rb") as f:
            self.assertEqual(f.read(), b'{"b": 2}')
        self.assertNotIn("result", self.events)

    def test_result_hook_failure_leaves_file_and_manifest(self):
        class FailingResult(Recorder):
            def result(self, **kw):
                super().result(**kw)
                raise RuntimeError("封印の失敗")
        rec = FailingResult(self.events, seq=11)
        with self.assertRaises(RuntimeError):
            self.run_acq(FakeTransport(FakeResponse(build_list([]))), rec=rec)
        path = self.expected_path(FIXED_NOW)
        with open(path, "rb") as f:
            sha = hashlib.sha256(f.read()).hexdigest()
        with open(self.manifest_path()) as f:
            e = json.loads(f.readline())
        self.assertEqual(e["acquisition_start_seq"], 11)
        self.assertEqual(e["sha256"], sha)
        self.assertEqual(rec.result_args, [{"start_seq": 11, "kept_rows_sha256": sha}])

    def test_manifest_is_append_only(self):
        self.run_acq(FakeTransport(FakeResponse(build_list([]))))
        mpath = self.manifest_path()
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

    def test_deadline_during_read(self):
        """読みの途中で時間の上限を超えたら、読み終える前に打ち切る（再試行しない）。"""
        def tick():
            self.clock.t += 100
        body = build_list(post_rows(0), order="sorted")
        tr = FakeTransport(FakeResponse(body, on_read=tick), FakeResponse(build_list([])))
        with self.assertRaises(filelist.FilelistError):
            self.run_acq(tr)
        self.assertEqual(len(tr.calls), 1)
        self.assertEqual(self.all_written(), {})

    def test_response_size_limit_short_lines(self):
        """短い行だけの応答でも、全体の長さの上限で打ち切る（外側の検査）。"""
        body = ("\n".join(PRE_ROWS * 3) + "\n").encode()
        with mock.patch.object(filelist, "MAX_RESPONSE_BYTES", len(body) // 2):
            with self.assertRaises(filelist.FilelistError):
                self.run_acq(FakeTransport(FakeResponse(body)))
        self.assertEqual(self.all_written(), {})

    def test_response_size_limit_inside_long_line(self):
        """長すぎる行を読み飛ばしている途中でも、全体の長さの上限で打ち切る（内側の検査）。"""
        body = b"x" * 20000 + b"\n"
        with mock.patch.object(filelist, "MAX_RESPONSE_BYTES", 6000):
            with self.assertRaises(filelist.FilelistError):
                self.run_acq(FakeTransport(FakeResponse(body)))
        self.assertEqual(self.all_written(), {})

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
        for top in (self.root, self.store):
            proc = subprocess.run([sys.executable, "-B", PRIVACY_SCRIPT, "--root", top],
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
        for p in (os.path.join(SRC, "filelist.py"), os.path.abspath(__file__), CHILD_SCRIPT):
            with open(p, "rb") as f:
                self.assertEqual(privacy_scan.find_in_bytes(f.read()), {}, p)


class TestIOGuard(unittest.TestCase):
    """見張り（IOGuard）そのものが、許していない書き込みと出力を捕まえること。"""

    def test_catches_writes_and_output(self):
        d = tempfile.mkdtemp(prefix="filelist-guard-")
        try:
            ok = os.path.join(d, "ok")
            bad = os.path.join(d, "bad")
            g = IOGuard([ok])
            with g:
                with open(ok, "w") as f:
                    f.write("x")
                with open(ok, "r") as f:
                    f.read()
                for act in (lambda: open(bad, "a"),
                            lambda: io.open(bad, "wb"),
                            lambda: os.open(bad, os.O_WRONLY | os.O_CREAT),
                            lambda: tempfile.NamedTemporaryFile(),
                            lambda: tempfile.mkstemp()):
                    with self.assertRaises(GuardViolation):
                        act()
                print("out-marker")
                print("err-marker", file=sys.stderr)
                os.write(2, b"fd-marker\n")
            self.assertEqual(len(g.violations), 5)
            self.assertFalse(os.path.exists(bad))
            self.assertIn("out-marker", g.stdout)
            self.assertIn("err-marker", g.stderr)
            self.assertIn(b"fd-marker", g.fd_output)
        finally:
            shutil.rmtree(d, ignore_errors=True)


class TestNoNetworkGuard(unittest.TestCase):
    def test_guard_active(self):
        with self.assertRaises(NetworkUsed):
            socket.create_connection(("192.0.2.1", 443), timeout=1)


if __name__ == "__main__":
    unittest.main()
