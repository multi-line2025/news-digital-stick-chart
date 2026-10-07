"""入口のスクリプト（src/collector/acquire_filelist.py）のテスト。T-015。

実行（プロジェクトのルートで。__pycache__ を作らないよう、必ず次の形で）:
    PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest discover -s tests/collector -v

確かめること
  - 関門：4つの条件（periods と candidates の記録、区切りの封印の時刻証明の確定、保存先の
    2段のフォルダ、取得のコードに未コミットの変更が無いこと）のどれか1つが欠ければ止まり、
    封印の記録・マニフェスト・保存先のどこにも書かず、通信もしない（TestGate）
  - アダプタ：関門 → acquisition-start → 取得 → acquisition-result の順。code_rel は固定で、
    filelist・封印の仕組み・関門の3つの sha256 が一致しなければ、封印の記録を書く前に止まる。
    source_url の照合。例外は握りつぶさない（TestAdapter）
  - 本番の経路：main() は引数を受け付けず、_acquire() を引数なしで呼ぶだけ。本番の部品は
    固定で、環境変数で変わらない。テストの差し替えは、一時的なディレクトリの下しか指せない
    （TestProductionPath）

どう動かすか
  プロジェクトの作業ツリーの写し（.git・.venv を除く）を一時的なディレクトリに作り、その中で
  git init とコミットをしてから、写しの中で関門・封印の記録・取得を通して動かす。封印の記録は
  本物の sealed/ の写し（periods の seq 1 は Bitcoin で確定済み、candidates の seq 2）を使う。
  drand の応答と ots は差し替えたものを使う。一覧の取得も差し替えた見本（test_filelist.py の
  build_list）を返す。ネットワークは使わない（モジュールの読み込みの時点で socket の接続を塞ぐ）。
  本物のプロジェクトの sealed/・data/manifest と、本物の ~/Desktop/news-stick-data には書かない。

このファイルには、メールアドレスの形の文字列をそのまま書かない。
"""

import datetime
import hashlib
import importlib.util
import inspect
import json
import os
import pwd
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(os.path.dirname(HERE))
SRC = os.path.join(PROJECT, "src", "collector")
ENTRY = os.path.join(SRC, "acquire_filelist.py")
sys.path.insert(0, HERE)

import test_filelist as tf  # noqa: E402  （見本の一覧と通信の差し替えを使う）


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


acq = _load("acquire_filelist", ENTRY)
ledger = acq.ledger
stamp = acq.stamp
otsfile = importlib.import_module("otsfile")  # acq が src/sealer を sys.path に入れている
filelist_mod = tf.filelist

UTC = datetime.timezone.utc
NOW = datetime.datetime(2026, 10, 7, 1, 2, 3, tzinfo=UTC)
GENESIS = 1692803367  # drand quicknet
NOREPLY = "197505900+multi-line2025" + "@" + "users.noreply.github.com"
GIT_AUTHOR = ("-c", "user.name=Multi-line", "-c", "user.email=" + NOREPLY,
              "-c", "commit.gpgsign=false", "-c", "core.hooksPath=/dev/null")


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


# --- 差し替えの部品 ---------------------------------------------------------

def drand_body(now):
    rnd = int((now - datetime.timedelta(seconds=2)).timestamp() - GENESIS) // 3 + 1
    sig = hashlib.sha256(str(rnd).encode()).digest() * 3
    return json.dumps({"round": rnd, "randomness": hashlib.sha256(sig).hexdigest(),
                       "signature": sig.hex()}).encode()


class FakeDrand:
    """netfetch.http_get の代わり。"""

    def __init__(self, now, events=None):
        self.now, self.urls, self.events = now, [], events

    def __call__(self, url):
        self.urls.append(url)
        if self.events is not None:
            self.events.append("drand")
        return drand_body(self.now)


def _varuint(n):
    out = bytearray()
    while True:
        b = n & 0x7f
        n >>= 7
        if n:
            out.append(b | 0x80)
        else:
            out.append(b)
            return bytes(out)


def _varbytes(b):
    return _varuint(len(b)) + b


def pending_ots(prefix):
    """記録の先頭のバイト列に対する、Pending の .ots（許可したカレンダーの宛先）。"""
    uri = sorted(ledger.ALLOWED_PENDING_URIS)[0]
    att = b"\x00" + otsfile.TAG_PENDING + _varbytes(_varbytes(uri.encode()))
    return (otsfile.MAGIC + b"\x01\x08" + hashlib.sha256(prefix).digest()
            + b"\xf0" + _varbytes(b"\x11" * 16) + b"\x08" + att)


class FakeOts:
    """subprocess.run の代わり（ots --version と ots stamp）。"""

    def __init__(self, events=None):
        self.calls, self.events = [], events

    def __call__(self, cmd, input=None, capture_output=True, timeout=None):
        self.calls.append(cmd)
        if cmd[1:] == ["--version"]:
            return subprocess.CompletedProcess(cmd, 0, stdout=b"v0.7.2", stderr=b"")
        if self.events is not None:
            self.events.append("ots-stamp")
        err = "".join("Submitting to remote calendar %s\n" % c for c in stamp.CALENDARS)
        return subprocess.CompletedProcess(cmd, 0, stdout=pending_ots(input),
                                           stderr=err.encode())


def sha_file(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def tree_files(top):
    """top の下のすべてのファイル（相対パス → 中身）。リンクはリンクとして記録する。"""
    out = {}
    for d, ds, fs in os.walk(top):
        for n in fs + [x for x in ds if os.path.islink(os.path.join(d, x))]:
            p = os.path.join(d, n)
            rel = os.path.relpath(p, top)
            if os.path.islink(p):
                out[rel] = ("link", os.readlink(p))
            else:
                with open(p, "rb") as f:
                    out[rel] = f.read()
    return out


# --- プロジェクトの写し -----------------------------------------------------

_PRISTINE = {}


def pristine_copy():
    """作業ツリーの写しを1回だけ作り、git init してコミットする（.git・.venv は写さない）。"""
    if "path" not in _PRISTINE:
        base = tempfile.mkdtemp(prefix="acq-pristine-")
        dst = os.path.join(base, "proj")
        shutil.copytree(PROJECT, dst, symlinks=True, ignore=shutil.ignore_patterns(
            ".git", ".venv", "__pycache__", ".DS_Store", ".claude"))
        rollback_to_before_step3(dst)
        git(dst, "init", "-q")
        git(dst, "add", "-A")
        git(dst, "commit", "-q", "-m", "写し")
        _PRISTINE["base"], _PRISTINE["path"] = base, dst
    return _PRISTINE["path"]


def rollback_to_before_step3(dst):
    """写しを、T-016（手順3の本番の取得）より前の状態に戻す（T-018）。

    本物の記録には T-016 の seq 3・4 があるので、そのままでは手順3の取得をもう一度通せない。
    写しの中だけで、periods（seq 1）と candidates（seq 2）より後の記録の行・中身・.ots を外し、
    ファイル一覧のマニフェストを空にする。本物には触れない。
    """
    sealed = os.path.join(dst, "sealed")
    path = os.path.join(sealed, "ledger.jsonl")
    with open(path, "rb") as f:
        lines = f.read().splitlines(keepends=True)
    kinds = [json.loads(l)["kind"] for l in lines]
    keep = 0
    while keep < len(kinds) and kinds[keep] in ("periods", "candidates"):
        keep += 1
    with open(path, "wb") as f:
        f.write(b"".join(lines[:keep]))
    for name in os.listdir(sealed):
        m = re.match(r"ledger\.jsonl\.seq(\d{6})(\.bitcoin)?\.ots\Z", name)
        if (m and int(m.group(1)) > keep) or name.startswith(("acquisition-", "method-access-",
                                                              "threshold-access-")):
            os.remove(os.path.join(sealed, name))
    open(os.path.join(dst, "data", "manifest", "gdelt-filelist.jsonl"), "wb").close()


def tearDownModule():
    for p in _patches:
        p.stop()
    if "base" in _PRISTINE:
        shutil.rmtree(_PRISTINE["base"], ignore_errors=True)


def git(root, *args):
    r = subprocess.run(["git", "-C", root] + list(GIT_AUTHOR) + list(args),
                       capture_output=True)
    if r.returncode != 0:
        raise AssertionError("git %s: %s" % (args[:1], r.stderr.decode(errors="replace")))
    return r.stdout


class CopyCase(unittest.TestCase):
    """プロジェクトの写し（project）と仮のホーム（home）を、一時的なディレクトリに作る。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="acq-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.project = os.path.join(self.tmp, "proj")
        shutil.copytree(pristine_copy(), self.project, symlinks=True)
        self.home = os.path.join(self.tmp, "home")
        self.store = os.path.join(self.home, "Desktop", "news-stick-data", "gdelt-filelist")
        os.makedirs(self.store)
        self.events = []
        self.logs = []
        self.post = tf.post_rows(40, salt="acq")
        self.transport = tf.FakeTransport(tf.FakeResponse(tf.build_list(self.post)),
                                          events=self.events)
        self.ots = FakeOts(self.events)
        self.drand = FakeDrand(NOW, self.events)

    def seams(self, **kw):
        base = dict(project=self.project, home=self.home, transport=self.transport,
                    sleep=lambda s: None, clock=lambda: 0.0, now=lambda: NOW,
                    log=self.logs.append, drand_fetch=self.drand, ots_cmd="ots",
                    ots_runner=self.ots)
        base.update(kw)
        return acq._TestSeams(**base)

    def ledger_bytes(self):
        with open(os.path.join(self.project, "sealed", "ledger.jsonl"), "rb") as f:
            return f.read()

    def snapshot(self):
        """書かれうる場所の全体（封印の記録、マニフェスト、保存先）。"""
        return {"sealed": tree_files(os.path.join(self.project, "sealed")),
                "manifest": tree_files(os.path.join(self.project, "data", "manifest")),
                "home": tree_files(self.home)}

    def assert_nothing_written(self, before):
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.transport.calls, [])
        self.assertEqual(self.drand.urls, [])
        self.assertEqual([c for c in self.ots.calls if c[1:] != ["--version"]], [])

    def move_out(self, rel):
        """写しの中のファイルを、写しの外（同じ一時フォルダ）へ移す。"""
        aside = os.path.join(self.tmp, "aside")
        os.makedirs(aside, exist_ok=True)
        os.rename(os.path.join(self.project, rel), os.path.join(aside, os.path.basename(rel)))


# --- 関門 -------------------------------------------------------------------

class TestGate(CopyCase):
    def test_passes_on_copy(self):
        g = acq.check_gate(self.seams())
        self.assertEqual(g["periods_seqs"], [1])
        self.assertEqual(g["candidates_seqs"], [2])
        self.assertIn(1, g["confirmed"])
        self.assertEqual(g["code_sha256"], sha_file(ENTRY))

    def refuse(self, pattern):
        before = self.snapshot()
        with self.assertRaises(acq.GateError) as cm:
            acq._acquire(_test=self.seams())
        self.assertRegex(str(cm.exception), pattern)
        self.assert_nothing_written(before)
        return cm.exception

    def test_missing_periods_and_candidates(self):
        """periods と candidates の記録が無ければ止まる。"""
        path = os.path.join(self.project, "sealed", "ledger.jsonl")
        with open(path, "rb") as f:
            lines = f.read().splitlines(keepends=True)
        with open(path, "wb") as f:
            f.write(lines[0])  # periods（seq 1）だけ
        self.move_out("sealed/ledger.jsonl.seq000002.ots")
        if os.path.exists(os.path.join(self.project, "sealed", "ledger.jsonl.seq000002.bitcoin.ots")):
            self.move_out("sealed/ledger.jsonl.seq000002.bitcoin.ots")
        git(self.project, "add", "-A")
        git(self.project, "commit", "-q", "-m", "candidates の無い記録")
        self.refuse("candidates")
        with open(path, "wb") as f:
            pass  # 記録が空（periods も無い）
        self.move_out("sealed/ledger.jsonl.seq000001.ots")
        self.move_out("sealed/ledger.jsonl.seq000001.bitcoin.ots")
        self.refuse("periods")

    def test_broken_chain(self):
        path = os.path.join(self.project, "sealed", "ledger.jsonl")
        with open(path, "ab") as f:
            f.write(b"{}\n")
        self.refuse("封印の記録の検証に通らない")

    def test_period_seal_not_confirmed(self):
        """区切りの封印（periods の seq 1）の Bitcoin の確定が無ければ止まる。"""
        sealed = os.path.join(self.project, "sealed")
        for name in os.listdir(sealed):
            if name.startswith("bitcoin-header-"):
                self.move_out("sealed/" + name)
        self.refuse("確定していない")

    def test_period_seal_bitcoin_ots_missing(self):
        self.move_out("sealed/ledger.jsonl.seq000001.bitcoin.ots")
        # .bitcoin.ots が無ければ、ヘッダは使われずに残る。確定は数えない
        self.refuse("確定していない")

    def test_store_dirs_required(self):
        """保存先の2段のフォルダが無ければ止まる（作らない）。リンクでも止まる。"""
        os.rmdir(self.store)
        self.refuse("gdelt-filelist")
        self.assertFalse(os.path.lexists(self.store))
        parent = os.path.dirname(self.store)
        os.rmdir(parent)
        self.refuse("news-stick-data")
        self.assertFalse(os.path.lexists(parent))
        elsewhere = os.path.join(self.tmp, "elsewhere")
        os.makedirs(os.path.join(elsewhere, "gdelt-filelist"))
        os.symlink(elsewhere, parent)
        self.refuse("シンボリックリンク")
        self.assertEqual(os.listdir(os.path.join(elsewhere, "gdelt-filelist")), [])

    def test_uncommitted_changes_refused(self):
        """src/collector・src/sealer の未コミットの変更（未追跡を含む）があれば止まる。"""
        cases = [
            ("src/collector/filelist.py", b"# x\n"),
            ("src/collector/privacy_scan.py", b"# x\n"),
            ("src/collector/acquire_filelist.py", b"# x\n"),
            ("src/sealer/seal_acquisition.py", b"# x\n"),
            ("src/sealer/new_untracked.py", None),
            ("src/collector/new_untracked.txt", None),
        ]
        for rel, extra in cases:
            with self.subTest(rel=rel):
                p = os.path.join(self.project, rel)
                if extra is None:
                    with open(p, "wb") as f:
                        f.write(b"x\n")
                    self.refuse("未コミットの変更")
                    os.rename(p, os.path.join(self.tmp, "aside-" + os.path.basename(p)))
                else:
                    with open(p, "rb") as f:
                        orig = f.read()
                    with open(p, "ab") as f:
                        f.write(extra)
                    self.refuse("未コミットの変更")
                    with open(p, "wb") as f:
                        f.write(orig)
        acq.check_gate(self.seams())  # 戻せば通る

    def test_pinned_sha_mismatch_refused(self):
        """filelist.py か privacy_scan.py を変えてコミットしても、固定した sha256 と違えば止まる。"""
        for rel in (acq.FILELIST_REL, acq.PRIVACY_SCAN_REL):
            with self.subTest(rel=rel):
                p = os.path.join(self.project, rel)
                with open(p, "rb") as f:
                    orig = f.read()
                with open(p, "ab") as f:
                    f.write(b"# changed\n")
                git(self.project, "commit", "-q", "-am", "変える")
                self.refuse("固定した値と違う")
                with open(p, "wb") as f:
                    f.write(orig)
                git(self.project, "commit", "-q", "-am", "戻す")

    def test_not_a_git_worktree_refused(self):
        os.rename(os.path.join(self.project, ".git"), os.path.join(self.tmp, "dotgit"))
        self.refuse("Git の作業ツリーでない")

    def test_each_condition_alone(self):
        """4つの条件のうち1つだけを欠いた写しを作り、それぞれで止まることを確かめる。"""
        breakers = {
            "records": lambda: self.move_out("sealed/ledger.jsonl.seq000002.ots"),
            "confirmed": lambda: self.move_out("sealed/ledger.jsonl.seq000001.bitcoin.ots"),
            "store": lambda: os.rmdir(self.store),
            "clean": lambda: open(os.path.join(self.project, "src", "sealer", "z.py"),
                                  "w").close(),
        }
        for name, brk in breakers.items():
            with self.subTest(condition=name):
                self.setUp()
                acq.check_gate(self.seams())  # 壊す前は通る
                brk()
                self.refuse(".")


# --- アダプタ -----------------------------------------------------------------

class TestAdapter(CopyCase):
    def run_recorded(self, **kw):
        """関門・封印の start・取得・封印の result の順を記録して、_acquire を動かす。"""
        real_gate = acq.check_gate
        real_start, real_result = acq.seal_acquisition.start, acq.seal_acquisition.result
        start_args = []

        def gate(s):
            self.events.append("gate")
            return real_gate(s)

        def start(*a, **k):
            self.events.append("seal-start")
            start_args.append((a, k))
            return real_start(*a, **k)

        def result(*a, **k):
            self.events.append("seal-result")
            return real_result(*a, **k)

        lines_at_fetch = []
        inner = self.transport

        def transport(url, timeout):
            lines_at_fetch.append(len(self.ledger_bytes().splitlines()))
            return inner(url, timeout)

        with mock.patch.object(acq, "check_gate", gate), \
                mock.patch.object(acq.seal_acquisition, "start", start), \
                mock.patch.object(acq.seal_acquisition, "result", result):
            out = acq._acquire(_test=self.seams(transport=transport, **kw))
        return out, start_args, lines_at_fetch

    def test_order_and_records(self):
        out, start_args, lines_at_fetch = self.run_recorded()
        self.assertEqual(self.events, ["gate", "seal-start", "drand", "ots-stamp", "fetch",
                                       "seal-result", "ots-stamp"])
        self.assertEqual(lines_at_fetch, [3])  # 取得の時点で acquisition-start が鎖にある
        # code_rel は固定
        (a, _k), = start_args
        self.assertEqual(a[0], self.project)
        self.assertEqual(a[1], "src/collector/acquire_filelist.py")
        self.assertEqual(acq.CODE_REL, filelist_mod.CODE_REL)

        data = self.ledger_bytes()
        records = ledger.verify_chain(data)
        ledger.check_anchors(data, os.path.join(self.project, "sealed"))
        self.assertEqual([r["kind"] for r in records],
                         ["periods", "candidates", "acquisition-start", "acquisition-result"])
        sdoc = ledger.read_target_json(self.project, records[2], "acquisition-start")
        rdoc = ledger.read_target_json(self.project, records[3], "acquisition-result")
        entry_sha = sha_file(ENTRY)
        self.assertEqual(sdoc["fetch"], {"code_path": "src/collector/acquire_filelist.py",
                                         "code_sha256": entry_sha})
        self.assertEqual(sdoc["step"], 3)
        self.assertEqual(rdoc, {"kind": "acquisition-result", "start_seq": 3,
                                "kept_rows_sha256": out["kept_rows_sha256"]})
        ledger.check_acquisition_pairs(records, {4: 3})
        ledger.check_candidates_ready(self.project, records, 3)

        with open(os.path.join(self.project, "data", "manifest", "gdelt-filelist.jsonl")) as f:
            entries = [json.loads(l) for l in f.read().splitlines()]
        self.assertEqual(len(entries), 1)
        e = entries[0]
        self.assertEqual(e["acquisition_start_seq"], 3)
        self.assertEqual(e["code_sha256"], entry_sha)
        self.assertEqual(e["code_path"], "src/collector/acquire_filelist.py")
        self.assertEqual(e["store_location"], "~/Desktop/news-stick-data/gdelt-filelist")
        self.assertEqual(e["source_url"], filelist_mod.MASTERFILELIST_URL)
        self.assertEqual(e["sha256"], out["kept_rows_sha256"])
        self.assertEqual(os.listdir(self.store), [e["file_name"]])
        self.assertEqual(sha_file(os.path.join(self.store, e["file_name"])), e["sha256"])
        self.assertEqual(out["code_sha256"], entry_sha)
        self.assertEqual(out["start_seq"], 3)

    def test_outputs_have_no_address_or_post_cutoff_rows(self):
        before = self.snapshot()
        self.run_recorded()
        after = self.snapshot()
        new = []
        for k in after:
            for rel, data in after[k].items():
                if before[k].get(rel) != data:
                    new.append((k + "/" + rel, data))
        self.assertTrue(new)
        log = "\n".join(self.logs).encode()
        markers = tf.TestPostCutoffInvisible.markers(None, self.post)
        for name, data in new + [("log", log)]:
            self.assertIsInstance(data, bytes, name)
            self.assertEqual(filelist_mod.privacy_scan.find_in_bytes(data), {}, name)
            for m in markers:
                self.assertNotIn(m, data, name)
            self.assertNotIn(self.home.encode(), data, name)
            self.assertNotIn(self.project.encode(), data, name)

    def test_sealer_sha_mismatch_stops_before_start(self):
        """封印の仕組みが計算する sha256 が違えば、封印の記録を書く前に止まる。"""
        before = self.snapshot()
        with mock.patch.object(acq.seal_acquisition, "committed_code_sha256",
                               lambda project, rel: (rel, "0" * 64)):
            with self.assertRaises(acq.AdapterError):
                acq._acquire(_test=self.seams())
        self.assert_nothing_written(before)

    def test_filelist_sha_mismatch_stops_before_start(self):
        """filelist が渡す code_sha256 が違えば、封印の記録を書く前に止まる。"""
        before = self.snapshot()
        real_load = acq._load_filelist

        def load(project, source):
            mod = real_load(project, source)
            mod.code_sha256 = lambda: "1" * 64
            return mod

        with mock.patch.object(acq, "_load_filelist", load):
            with self.assertRaises(acq.AdapterError):
                acq._acquire(_test=self.seams())
        self.assert_nothing_written(before)

    def test_entry_changed_after_gate(self):
        """関門のあとで入口のスクリプトが書き換えられたら、封印の記録を書く前に止まる。"""
        before = self.snapshot()
        real_gate = acq.check_gate
        entry = os.path.join(self.project, acq.CODE_REL)

        def gate(s):
            g = real_gate(s)
            with open(entry, "ab") as f:
                f.write(b"# after gate\n")
            return g

        with mock.patch.object(acq, "check_gate", gate):
            with self.assertRaises(acq.GateError):
                acq._acquire(_test=self.seams())
        self.assert_nothing_written(before)

    def test_entry_changed_just_before_start_propagates(self):
        """封印の仕組みが読む直前に変われば、封印の仕組みの例外がそのまま出る（握りつぶさない）。"""
        before = self.snapshot()
        real = acq.seal_acquisition.committed_code_sha256
        entry = os.path.join(self.project, acq.CODE_REL)

        def changed(project, rel):
            with open(entry, "ab") as f:
                f.write(b"# racing\n")
            return real(project, rel)

        with mock.patch.object(acq.seal_acquisition, "committed_code_sha256", changed):
            with self.assertRaises(ledger.LedgerError) as cm:
                acq._acquire(_test=self.seams())
        self.assertIn("HEAD", str(cm.exception))
        self.assert_nothing_written(before)

    def test_exceptions_propagate_unchanged(self):
        before = self.snapshot()
        boom = RuntimeError("封印の失敗（見本）")

        def failing(*a, **k):
            raise boom

        with mock.patch.object(acq.seal_acquisition, "start", failing):
            with self.assertRaises(RuntimeError) as cm:
                acq._acquire(_test=self.seams())
        self.assertIs(cm.exception, boom)
        self.assert_nothing_written(before)

        boom2 = RuntimeError("result の失敗（見本）")
        with mock.patch.object(acq.seal_acquisition, "result",
                               mock.Mock(side_effect=boom2)):
            with self.assertRaises(RuntimeError) as cm:
                acq._acquire(_test=self.seams())
        self.assertIs(cm.exception, boom2)
        # result の無い start と、本体・マニフェストが残る（消さない）
        records = ledger.verify_chain(self.ledger_bytes())
        self.assertEqual(records[-1]["kind"], "acquisition-start")
        self.assertEqual(len(os.listdir(self.store)), 1)

    def test_fetch_failure_propagates_and_no_result(self):
        self.transport.responses = [tf.FakeResponse(status=404)]
        with self.assertRaises(Exception) as cm:
            acq._acquire(_test=self.seams())
        self.assertEqual(type(cm.exception).__name__, "FilelistError")
        records = ledger.verify_chain(self.ledger_bytes())
        self.assertEqual([r["kind"] for r in records][-1], "acquisition-start")
        self.assertEqual(os.listdir(self.store), [])

    def adapter(self):
        s = self.seams()
        g = acq.check_gate(s)
        mod = acq._load_filelist(self.project, g["codes"][acq.FILELIST_REL])
        return acq._Adapter(s, mod, g["code_sha256"]), g

    def test_source_url_must_be_the_fixed_one(self):
        before = self.snapshot()
        ad, g = self.adapter()
        for url in ("https://data.gdeltproject.org/gdeltv2/lastupdate.txt",
                    "https://api.gdeltcloud.com/gdeltv2/masterfilelist.txt",
                    "http://data.gdeltproject.org/gdeltv2/masterfilelist.txt"):
            with self.subTest(url=url):
                with self.assertRaises(acq.AdapterError):
                    ad.start(code_sha256=g["code_sha256"], source_url=url)
        self.assert_nothing_written(before)

    def test_result_must_match_start(self):
        ad, g = self.adapter()
        before = self.snapshot()
        with self.assertRaises(acq.AdapterError):  # start の前の result
            ad.result(start_seq=3, kept_rows_sha256="0" * 64)
        self.assertEqual(self.snapshot(), before)
        seq = ad.start(code_sha256=g["code_sha256"],
                       source_url=acq._load_filelist(self.project, g["codes"][acq.FILELIST_REL])
                       .MASTERFILELIST_URL)
        self.assertEqual(seq, 3)
        mid = self.snapshot()
        with self.assertRaises(acq.AdapterError):
            ad.result(start_seq=2, kept_rows_sha256="0" * 64)
        self.assertEqual(self.snapshot(), mid)
        with self.assertRaises(acq.AdapterError):  # start は1回だけ
            ad.start(code_sha256=g["code_sha256"], source_url="x")
        self.assertEqual(ad.result(start_seq=3, kept_rows_sha256="a" * 64), 4)


# --- ハッシュの範囲と定数 -------------------------------------------------------

class TestCodeScope(unittest.TestCase):
    def test_pins_match_current_files(self):
        """PINNED_SHA256 が、今の filelist.py・privacy_scan.py・codegate.py の sha256 と一致する。"""
        self.assertEqual([r for r, _ in acq.PINNED_SHA256],
                         ["src/collector/filelist.py", "src/collector/privacy_scan.py",
                          "src/collector/codegate.py"])
        for rel, want in acq.PINNED_SHA256:
            self.assertEqual(sha_file(os.path.join(PROJECT, rel)), want, rel)

    def test_constants_agree_with_filelist(self):
        self.assertEqual(acq.CODE_REL, "src/collector/acquire_filelist.py")
        self.assertEqual(acq.CODE_REL, filelist_mod.CODE_REL)
        self.assertEqual(acq.STORE_PARTS, filelist_mod.FIXED_STORE_PARTS)
        self.assertEqual(acq.CLEAN_PATHS, ("src/collector", "src/sealer"))
        self.assertEqual(filelist_mod.code_sha256(), sha_file(ENTRY))

    def test_citation(self):
        self.assertIn("Data: The GDELT Project (https://www.gdeltproject.org/).",
                      " ".join(acq.__doc__.split()))
        with open(os.path.join(SRC, "README.md"), encoding="utf-8") as f:
            self.assertIn("https://www.gdeltproject.org/", f.read())


# --- 本番の経路 ---------------------------------------------------------------

class TestProductionPath(unittest.TestCase):
    def test_main_rejects_any_argument(self):
        never = mock.Mock(side_effect=AssertionError("_acquire を呼んではいけない"))
        with mock.patch.object(acq, "_acquire", never):
            for argv in (["--store", "/tmp/x"], ["--root", "/tmp/x"], ["-h"], ["x"],
                         ["--transport=fake"], [""]):
                with self.subTest(argv=argv):
                    with mock.patch("sys.stderr"):
                        self.assertEqual(acq.main(argv), 2)
        never.assert_not_called()

    def test_main_calls_acquire_without_arguments(self):
        out = {"start_seq": 3, "file_name": "masterfilelist-kept-20261007T010203Z.tsv",
               "kept_rows": 1, "rejected_rows": 0, "kept_rows_sha256": "0" * 64,
               "code_sha256": "1" * 64}
        m = mock.Mock(return_value=out)
        with mock.patch.object(acq, "_acquire", m), mock.patch("sys.stdout"):
            self.assertEqual(acq.main([]), 0)
        m.assert_called_once_with()
        m = mock.Mock(side_effect=acq.GateError("見本"))
        with mock.patch.object(acq, "_acquire", m), mock.patch("sys.stderr"):
            self.assertEqual(acq.main([]), 1)
        m.assert_called_once_with()

    def test_main_does_not_catch_other_exceptions(self):
        boom = RuntimeError("見本")
        with mock.patch.object(acq, "_acquire", mock.Mock(side_effect=boom)):
            with self.assertRaises(RuntimeError) as cm:
                acq.main([])
        self.assertIs(cm.exception, boom)

    def test_signatures(self):
        self.assertEqual(list(inspect.signature(acq.main).parameters), ["argv"])
        self.assertEqual(list(inspect.signature(acq._acquire).parameters), ["_test"])
        self.assertEqual(list(inspect.signature(acq.check_gate).parameters), ["s"])

    def test_production_seams_are_fixed(self):
        """本番の部品は固定。環境変数（HOME など）を変えても変わらない。"""
        fake = tempfile.mkdtemp(prefix="acq-env-")
        self.addCleanup(shutil.rmtree, fake, True)
        expected_home = pwd.getpwuid(os.getuid()).pw_dir
        for env in ({}, {"HOME": fake, "NDSC_GDELT_FILELIST_STORE": fake, "TMPDIR": fake}):
            with self.subTest(env=sorted(env)):
                with mock.patch.dict(os.environ, env):
                    s = acq._production_seams()
                self.assertEqual(s.project, PROJECT)
                self.assertEqual(s.home, expected_home)
                self.assertIsNone(s.transport)
                self.assertIsNone(s.log)
                self.assertIsNone(s.drand_fetch)
                self.assertIs(s.sleep, time.sleep)
                self.assertIs(s.clock, time.monotonic)
                self.assertIs(s.now, acq._utc_now)
                self.assertIs(s.ots_runner, subprocess.run)
                self.assertEqual(s.ots_cmd, os.path.join(PROJECT, ".venv", "bin", "ots"))
                self.assertIs(type(s), acq._Seams)

    def test_entry_reads_no_environment(self):
        with open(ENTRY, encoding="utf-8") as f:
            src = f.read()
        code = src.split('"""', 2)[2]  # docstring を除いた本体
        for word in ("os.environ", "getenv", "argparse", "expanduser", "Path.home"):
            self.assertNotIn(word, code)

    def test_seams_are_immutable(self):
        s = acq._production_seams()
        with self.assertRaises(AttributeError):
            s.project = "/tmp"
        with self.assertRaises(AttributeError):
            s.transport = lambda u, t: None

    def test_test_seams_cannot_point_at_real_places(self):
        tmp = tempfile.mkdtemp(prefix="acq-seam-")
        self.addCleanup(shutil.rmtree, tmp, True)

        def seams(**kw):
            base = dict(project=tmp, home=tmp, transport=None, sleep=None, clock=None,
                        now=None, log=None, drand_fetch=None, ots_cmd="ots", ots_runner=None)
            base.update(kw)
            return acq._TestSeams(**base)

        never = mock.Mock(side_effect=AssertionError("関門まで進んではいけない"))
        with mock.patch.object(acq, "check_gate", never):
            for bad in (seams(project=PROJECT), seams(home=pwd.getpwuid(os.getuid()).pw_dir),
                        seams(project="/"), seams(home=os.path.dirname(PROJECT))):
                with self.assertRaises(ValueError):
                    acq._acquire(_test=bad)
            for bad in (acq._production_seams(), object(), {"project": tmp}):
                with self.assertRaises(TypeError):
                    acq._acquire(_test=bad)
        never.assert_not_called()

    def test_script_with_argument_does_nothing(self):
        """スクリプトとして実行しても、引数があれば何もせずに終了コード 2。"""
        r = subprocess.run([sys.executable, "-B", ENTRY, "--store", "/tmp/x"],
                           capture_output=True, timeout=60,
                           env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
        self.assertEqual(r.returncode, 2, r.stderr.decode(errors="replace"))
        self.assertEqual(r.stdout, b"")


class TestGateHardening(CopyCase):
    """T-015 の監査 軽1・軽2・軽5 への対応（T-018。codegate.py）。"""

    def refuse(self, pattern, seams=None):
        before = self.snapshot()
        with self.assertRaises(acq.GateError) as cm:
            acq._acquire(_test=seams or self.seams())
        self.assertRegex(str(cm.exception), pattern)
        self.assert_nothing_written(before)

    def test_skip_worktree_and_assume_unchanged_refused(self):
        rel = "src/sealer/seal_acquisition.py"
        p = os.path.join(self.project, rel)
        for flag in ("--skip-worktree", "--assume-unchanged"):
            with self.subTest(flag=flag):
                git(self.project, "update-index", flag, rel)
                with open(p, "rb") as f:
                    orig = f.read()
                with open(p, "ab") as f:
                    f.write(b"# hidden\n")
                # git status には出ない
                self.assertEqual(git(self.project, "status", "--porcelain", "--", rel), b"")
                self.refuse("skip-worktree か assume-unchanged")
                with open(p, "wb") as f:
                    f.write(orig)
                git(self.project, "update-index", flag.replace("--", "--no-"), rel)
        acq.check_gate(self.seams())

    def test_git_replace_refused(self):
        """T-018 の監査 軽1：git replace で HEAD の中身を偽れないこと。"""
        rel = "src/collector/filelist.py"
        p = os.path.join(self.project, rel)
        with open(p, "rb") as f:
            orig = f.read()
        with open(p, "ab") as f:
            f.write(b"# replaced\n")
        fake = git(self.project, "hash-object", "-w", rel).strip().decode()
        real = git(self.project, "rev-parse", "HEAD:" + rel).strip().decode()
        git(self.project, "replace", real, fake)
        # 置き換えがあると、普通の git の HEAD の中身は書き換えた中身に見える
        self.assertEqual(git(self.project, "show", "HEAD:" + rel), orig + b"# replaced\n")
        self.refuse("git replace|未コミット")
        git(self.project, "replace", "-d", real)
        with open(p, "wb") as f:
            f.write(orig)
        acq.check_gate(self.seams())
        self.assertEqual(acq._load_codegate(self.project)[0].GIT_ENV["GIT_NO_REPLACE_OBJECTS"], "1")

    def test_replace_ref_alone_refused(self):
        """作業ツリーを変えずに、関係の無いオブジェクトの置き換えだけがあっても止まる。"""
        a = git(self.project, "rev-parse", "HEAD:README.md").strip().decode() \
            if os.path.exists(os.path.join(self.project, "README.md")) else \
            git(self.project, "rev-parse", "HEAD:CLAUDE.md").strip().decode()
        b = git(self.project, "rev-parse", "HEAD:src/collector/README.md").strip().decode()
        git(self.project, "replace", a, b)
        self.refuse("git replace")

    def test_ignored_files_refused(self):
        d = os.path.join(self.project, "src", "sealer", "__pycache__")
        os.makedirs(d)
        with open(os.path.join(d, "ledger.cpython-314.pyc"), "wb") as f:
            f.write(b"x")
        self.refuse("無視されるファイル")
        shutil.rmtree(d)
        acq.check_gate(self.seams())

    def test_git_env_is_not_inherited(self):
        """GIT_DIR・GIT_WORK_TREE・GIT_INDEX_FILE で別の場所を指しても、写しの .git を見る。"""
        other = os.path.join(self.tmp, "other")
        os.makedirs(other)
        git(other, "init", "-q")
        with open(os.path.join(self.project, "src", "sealer", "z.py"), "wb") as f:
            f.write(b"x\n")
        env = {"GIT_DIR": os.path.join(other, ".git"), "GIT_WORK_TREE": other,
               "GIT_INDEX_FILE": os.path.join(other, ".git", "index")}
        with mock.patch.dict(os.environ, env):
            self.refuse("未コミットの変更")

    def test_dot_git_must_be_a_real_directory(self):
        real = os.path.join(self.tmp, "realgit")
        os.rename(os.path.join(self.project, ".git"), real)
        with open(os.path.join(self.project, ".git"), "w") as f:
            f.write("gitdir: %s\n" % real)
        self.refuse("Git の作業ツリーでない")
        os.remove(os.path.join(self.project, ".git"))
        os.symlink(real, os.path.join(self.project, ".git"))
        self.refuse("Git の作業ツリーでない")

    def _link(self, rel):
        target = os.path.join(self.tmp, "elsewhere-" + rel.replace("/", "-"))
        src = os.path.join(self.project, rel)
        shutil.copytree(src, target, symlinks=True)
        shutil.rmtree(src)
        os.symlink(target, src)
        return target

    def test_test_seams_reject_linked_sealed_and_manifest(self):
        """軽1：写しの sealed/・data/manifest/ がリンクなら、差し替えを受け付けない。"""
        for rel in ("sealed", "data/manifest"):
            with self.subTest(rel=rel):
                self.setUp()
                self._link(rel)
                with self.assertRaises(ValueError):
                    acq._acquire(_test=self.seams())
        self.setUp()
        acq._checked_test_seams(self.seams())

    def test_gate_rejects_linked_project_dirs(self):
        """軽5：本番と同じ関門（check_gate）も、sealed/・data/manifest/ のリンクで止まる。"""
        for rel in ("sealed", "data/manifest"):
            with self.subTest(rel=rel):
                self.setUp()
                self._link(rel)
                git(self.project, "add", "-A")
                git(self.project, "commit", "-q", "-m", "link")
                with self.assertRaises(acq.GateError):
                    acq.check_gate(self.seams())

    def test_codegate_pinned_and_executed_from_checked_bytes(self):
        p = os.path.join(self.project, acq.CODEGATE_REL)
        with open(p, "ab") as f:
            f.write(b"# changed\n")
        git(self.project, "commit", "-q", "-am", "変える")
        self.refuse("固定した値と違う")

    def test_docstring_no_longer_overclaims(self):
        doc = " ".join(acq.__doc__.split())
        self.assertNotIn("環境変数も読まない", doc)
        self.assertNotIn("本物の sealed/・ data/manifest・保存先に書くことはできない", doc)
        self.assertIn("os.environ を読まない", doc)


class TestNoNetworkGuard(unittest.TestCase):
    def test_guard_active(self):
        with self.assertRaises(NetworkUsed):
            socket.create_connection(("192.0.2.1", 443), timeout=1)


if __name__ == "__main__":
    unittest.main()
