"""手順4の入口のスクリプト（src/collector/acquire_gkg.py）のテスト。T-018。

実行（プロジェクトのルートで）:
    PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest discover -s tests/collector -v

確かめること
  - 最初に ledger.require_method_access() を呼ぶ。本番の経路では引数なしで呼ぶ。止まれば、
    ほかのことを何もしない（TestMethodAccessFirst）
  - プロジェクトの写しで、手順3（ファイル一覧の取得。差し替えの通信）と method-access の記録を
    作ってから、関門 → GKG の取得 → 集計 → マニフェストまで通して動かす。関門の各条件が欠ければ
    止まり、何も書かない（TestEndToEnd）
  - 本番の部品は固定で、差し替えは一時的なディレクトリの下しか指せない（TestProductionPath）
ネットワークは使わない（test_acquire_filelist が socket を塞ぐ。drand・ots・通信は差し替え）。
本物の sealed/・data/manifest・~/Desktop/news-stick-data・/Volumes/LACIE SHARE には書かない。
保存先のディスクは、一時的なディレクトリ（FAT32 のテストではイメージのマウント先）で置き換える。
"""

import hashlib
import importlib.util
import inspect
import io
import json
import os
import plistlib
import pwd
import shutil
import subprocess
import sys
import tempfile
import time
import types
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(os.path.dirname(HERE))
SRC = os.path.join(PROJECT, "src", "collector")
ENTRY = os.path.join(SRC, "acquire_gkg.py")
sys.path.insert(0, HERE)

import test_acquire_filelist as taf  # noqa: E402
import test_filelist as tf  # noqa: E402
import test_gkg as tg  # noqa: E402


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ag = _load("acquire_gkg", ENTRY)
ledger = ag.ledger
stamp = ag.stamp
seal_method = importlib.import_module("seal_method")
seal_gkg_result = importlib.import_module("seal_gkg_result")
gkg = tg.gkg


def fake_check_volume(volume):
    """一時的なディレクトリはマウント先でないので、マウントの検査だけを差し替える。"""
    return os.lstat(volume).st_dev


def filelist_entry(project):
    with open(os.path.join(project, "data", "manifest", "gdelt-filelist.jsonl"), "rb") as f:
        return json.loads(f.read())


def setUpModule():
    # test_acquire_filelist の tearDownModule が写しを消したあとでも、作り直させる
    taf._PRISTINE.clear()
    taf.setUpModule()


def tearDownModule():
    taf.tearDownModule()


EXCL_REF = {"seq": 7, "record_sha256": "e" * 64}

_SEALER_TESTS = os.path.join(PROJECT, "tests", "sealer", "test_ledger.py")
_sealer_test_ledger = None


def add_order_record(project, kind, now):
    """写しの封印の記録に、統計係の順番1・1b の記録（照合に通る仮の中身）を足す（T-032）。

    中身は封印係のテストの order_doc_for で作る（ledger の決まった値を、その時点の値で使う）。
    書く仕組み（seal_stats）を通さない。本物の sealed/ には書かない。返り値: seq。
    """
    global _sealer_test_ledger
    if _sealer_test_ledger is None:
        _sealer_test_ledger = _load("sealer_test_ledger_for_collector", _SEALER_TESTS)
    path = os.path.join(project, "sealed", "ledger.jsonl")
    data = ledger.read_ledger(path)
    seq = len(ledger.verify_chain(data)) + 1
    doc = _sealer_test_ledger.order_doc_for(data, seq, kind)
    content = ledger.canonical_line(doc) + b"\n"
    sha = ledger.sha256_hex(content)
    rel = "sealed/%s-%s.json" % (kind, sha)
    ledger.write_once(os.path.join(project, rel), content)
    ledger.append_record(path, kind, [{"path": rel, "role": kind, "sha256": sha}], "", now)
    stamp.stamp_seq(path, seq, "ots", runner=taf.FakeOts())
    return seq


def gkg_run_docs_unchecked(project):
    """写しの封印の記録の gkg-run-start の記録（.ots の照合をしない。鎖の照合だけ）。"""
    data = ledger.read_ledger(os.path.join(project, "sealed", "ledger.jsonl"))
    return [r for r in ledger.verify_chain(data) if r["kind"] == ledger.GKG_RUN_KIND]


def gkg_run_docs(project):
    """写しの封印の記録の gkg-run-start の [(記録, 中身)]。"""
    data = ledger.read_ledger(os.path.join(project, "sealed", "ledger.jsonl"))
    return [(r, ledger.read_target_json(project, r, ledger.GKG_RUN_KIND))
            for r in ledger.verify_chain(data) if r["kind"] == ledger.GKG_RUN_KIND]


def pass_exclusion_gate(s, codes):
    """除外の規則の封印の関門を通ったことにする（関門そのものは TestExclusionGateFirst）。"""
    return dict(EXCL_REF)


def file_codes(*a, **k):
    """手順000 のコードの関門の差し替え：作業ツリーのファイルをそのまま返す（git を使わない）。"""
    codes = {}
    for rel in (ag.CODE_REL,) + tuple(r for r, _ in ag.PINNED_SHA256):
        with open(os.path.join(PROJECT, rel), "rb") as f:
            codes[rel] = f.read()
    return codes, None


FAKE_THEMES = """
class ThemesError(Exception):
    pass
def require_exclusion_rules_sealed():
    if MODE == "boom":
        raise ThemesError("見本")
    return {"seq": 9}, ROOT
def exclusion_rule_ref(rec):
    return {"seq": rec["seq"], "record_sha256": "f" * 64}
"""


class TestExclusionGateFirst(unittest.TestCase):
    """重1・差し戻し2回目 軽-2：コードの関門 → 除外の規則の封印の関門 → method-access の関門の順。"""

    def mini_project(self, kinds):
        """仮の封印の記録（kinds）だけを持つ小さなプロジェクトを、一時的なディレクトリに作る（T-050）。

        本物の封印の記録の状態（stats-order1 があるか、件数など）に頼らないため。除外の規則の関門が
        読み込む themes.py と privacy_scan.py は、本物のものを写す。返り値: プロジェクトのパス。
        """
        tmp = tempfile.mkdtemp(prefix="gkg-mini-")
        self.addCleanup(shutil.rmtree, tmp, True)
        col = os.path.join(tmp, "src", "collector")
        os.makedirs(col)
        for n in ("themes.py", "privacy_scan.py"):
            shutil.copyfile(os.path.join(PROJECT, "src", "collector", n), os.path.join(col, n))
        tg.make_sealed_project(tmp, kinds)
        return tmp

    def run_production_on(self, project):
        """本番の経路（_acquire と main）を、project を本番のプロジェクトとして動かす。"""
        seams = ag._production_seams()
        fields = {k: getattr(seams, k) for k in ag._Seams.FIELDS}
        fields["project"] = project
        mini = ag._Seams(**fields)
        return mock.patch.object(ag, "_production_seams", lambda: mini), \
            mock.patch.object(ledger, "PROJECT_ROOT", project)

    def test_real_gate_stops_first_without_order1(self):
        """封印の記録に stats-order1 が無ければ、本物の除外の規則の関門が、method-access の関門と
        ほかの関門より前に止める（試しの run も正式な run も）。T-050：本物の記録の状態に頼らず、
        順番1b・method-access・gkg-run-start はあるが stats-order1 の無い仮の記録で確かめる。"""
        for kinds in ((), tg.KINDS_WITHOUT_ORDER1):
            with self.subTest(kinds=kinds):
                project = self.mini_project(kinds)
                never = mock.Mock(side_effect=AssertionError("除外の規則の関門より先に進んではいけない"))
                p1, p2 = self.run_production_on(project)
                with p1, p2, mock.patch.object(ag, "_check_code", file_codes), \
                        mock.patch.object(ledger, "require_method_access", never), \
                        mock.patch.object(ag, "check_gate", never):
                    for mode in ("official", "trial"):
                        with self.assertRaisesRegex(ag.GateError, "除外の規則.*stats-order1）が無い"):
                            ag._acquire(mode)
                    with mock.patch("sys.stderr"):
                        self.assertEqual(ag.main([]), 1)
                        self.assertEqual(ag.main(["--trial"]), 1)
                never.assert_not_called()

    def test_real_gate_passes_with_order1(self):
        """対照：仮の記録の7種類（stats-order1 の無い並び）の後ろに stats-order1 を1件足すと、除外の規則の
        関門は通り、次の method-access の関門まで進む（ほかの種類が並ぶ中から読めていることの確かめ）。"""
        project = self.mini_project(tg.KINDS_WITH_ORDER1)
        stop = mock.Mock(side_effect=ledger.MethodAccessRequired("見本：次の関門"))
        p1, p2 = self.run_production_on(project)
        with p1, p2, mock.patch.object(ag, "_check_code", file_codes), \
                mock.patch.object(ledger, "require_method_access", stop):
            with self.assertRaisesRegex(ledger.MethodAccessRequired, "次の関門"):
                ag._acquire("trial")
        stop.assert_called_once_with()

    def test_code_gate_runs_before_exclusion_gate(self):
        order = []
        with mock.patch.object(ag, "_check_code",
                               side_effect=lambda p: order.append("code") or file_codes()), \
                mock.patch.object(ag, "_exclusion_gate",
                                  side_effect=lambda s, c: order.append("excl") or dict(EXCL_REF)), \
                mock.patch.object(ledger, "require_method_access",
                                  side_effect=ledger.MethodAccessRequired("見本")):
            with self.assertRaises(ledger.MethodAccessRequired):
                ag._acquire()
        self.assertEqual(order, ["code", "excl"])
        bad = ag.GateError("未コミット")
        never = mock.Mock(side_effect=AssertionError("コードの関門より先に進んではいけない"))
        with mock.patch.object(ag, "_check_code", side_effect=bad), \
                mock.patch.object(ag, "_exclusion_gate", never):
            with self.assertRaisesRegex(ag.GateError, "未コミット"):
                ag._acquire()
        never.assert_not_called()

    def gate_with(self, mode, root):
        src = ("MODE = %r\nROOT = %r\n" % (mode, root) + FAKE_THEMES).encode()
        return ag._exclusion_gate(ag._production_seams(), {ag.THEMES_REL: src})

    def test_gate_uses_checked_bytes_and_root(self):
        self.assertEqual(self.gate_with("ok", ag.PROJECT), {"seq": 9, "record_sha256": "f" * 64})
        with self.assertRaisesRegex(ag.GateError, "プロジェクトが違う"):
            self.gate_with("ok", "/")
        with self.assertRaisesRegex(ag.GateError, "見本"):
            self.gate_with("boom", ag.PROJECT)


class TestFilesystemCheck(unittest.TestCase):
    """ディスクの形式だけを diskutil で確かめる（ここでは diskutil を差し替える）。
    VolumeUUID は取り出さず、返しもしない（オーナーの決定「記録に残さず、公開もしない」）。"""

    def run_with(self, info, code=0):
        out = types.SimpleNamespace(returncode=code, stdout=plistlib.dumps(info))
        with mock.patch.object(ag.subprocess, "run", return_value=out) as r:
            v = ag.check_filesystem("/x")
        self.assertEqual(r.call_args.args[0], [ag.DISKUTIL, "info", "-plist", "/x"])
        return v

    def test_cases(self):
        self.assertIsNone(self.run_with({"FilesystemType": "msdos", "VolumeUUID": "U-1"}))
        for info, code, pattern in (({"FilesystemType": "exfat", "VolumeUUID": "U"}, 0, "msdos"),
                                    ({"VolumeUUID": "U"}, 0, "msdos"),
                                    ({"FilesystemType": "msdos", "VolumeUUID": "U"}, 1, "読めない")):
            with self.assertRaisesRegex(ag.GateError, pattern):
                self.run_with(info, code)

    def test_no_volume_uuid_in_entry_code(self):
        with open(ENTRY, encoding="utf-8") as f:
            code = f.read().split('"""', 2)[2]
        self.assertNotIn("volume_id", code)
        self.assertNotIn('get("VolumeUUID")', code)


class TestMethodAccessFirst(unittest.TestCase):
    def setUp(self):
        for p in (mock.patch.object(ag, "_exclusion_gate", pass_exclusion_gate),
                  mock.patch.object(ag, "_check_code", file_codes)):
            p.start()
            self.addCleanup(p.stop)

    def test_production_calls_gate_without_arguments_first(self):
        calls = []
        gate = mock.Mock(side_effect=ledger.MethodAccessRequired("見本"))
        never = mock.Mock(side_effect=AssertionError("関門より先に進んではいけない"))
        with mock.patch.object(ledger, "require_method_access", gate), \
                mock.patch.object(ag, "check_gate", never), \
                mock.patch.object(ag, "_check_filelist", never):
            with self.assertRaises(ledger.MethodAccessRequired):
                ag._acquire()
            with mock.patch("sys.stderr"):
                self.assertEqual(ag.main([]), 1)
        gate.assert_called_with()
        self.assertEqual(gate.call_count, 2)
        never.assert_not_called()

    def test_source_calls_gate_before_anything(self):
        src = inspect.getsource(ag._acquire)
        body = src.split('"""', 2)[2]
        first = [l.strip() for l in body.splitlines() if l.strip()]
        self.assertTrue(first[0].startswith("s = "))
        self.assertEqual(first[1], "code = _check_code(s.project)")
        self.assertEqual(first[2], "exclusion_rule = _exclusion_gate(s, code[0])")
        self.assertTrue(first[3].startswith("method_rec = _method_access_gate("))
        self.assertIn("rec = ledger.require_method_access()\n",
                      inspect.getsource(ag._method_access_gate))


class E2ECase(taf.CopyCase):
    """写しで、手順3（差し替えの通信）と method-access を作ってからコミットする。"""

    DAYS = ("20150302", "20150303", "20150304")     # 試しの run の3日（封印係が3日ちょうどを求める）

    def setUp(self):
        super().setUp()
        # T-032：除外の規則の関門（stats-order1）と、run の開始の封印の記録（gkg-run-start）は、
        # 写しの封印の記録の上で本物を動かす。drand と ots は差し替える
        self.fs_check = lambda v: None
        self.gdrand = taf.FakeDrand(tg.NOW)
        self.gots = taf.FakeOts()
        self.zips = {}
        for d in self.DAYS:
            for i in range(3):
                ts = tg.ts_of(d, i)
                self.zips[ts] = tg.make_zip(ts, tg.standard_rows(ts))
        lines = ["%d %s http://data.gdeltproject.org/gdeltv2/%s.gkg.csv.zip"
                 % (len(z), hashlib.md5(z).hexdigest(), ts) for ts, z in sorted(self.zips.items())]
        lines.append("5 %s http://data.gdeltproject.org/gdeltv2/20150218230000.gkg.csv.zip"
                     % ("0" * 32))                     # DATA_START より前
        body = ("\n".join(lines) + "\n").encode()
        self.transport = tf.FakeTransport(tf.FakeResponse(body))
        taf.acq._acquire(_test=self.seams())           # 手順3（seq 3・4）
        # T-032：method-access を書く前の状態に、統計係の順番1・1b（stats-order1・stats-order1b）の
        # 記録を置く（封印係が「順番1 が無ければ method-access も止まる」を入れても壊れないように）
        self.order1_seq = add_order_record(self.project, ledger.ORDER1_KIND, taf.NOW)
        self.order1b_seq = add_order_record(self.project, ledger.ORDER1B_KIND, taf.NOW)
        self.volume = self.make_volume()
        self.gkg_store = os.path.join(self.volume, *gkg.STORE_PARTS)
        os.makedirs(self.gkg_store)
        self.trial_store = os.path.join(self.volume, *gkg.TRIAL_STORE_PARTS)
        os.makedirs(self.trial_store)
        self.check_volume = fake_check_volume
        self.gkg_logs = []
        self.clock = tg.FakeClock()

    def make_volume(self):
        v = os.path.join(self.tmp, "vol")
        os.makedirs(v)
        return v

    def add_method_access(self):
        rec, _rel, _o = seal_method.seal(self.project, taf.NOW, "ots",
                                         drand_fetch=taf.FakeDrand(taf.NOW), runner=taf.FakeOts())
        taf.git(self.project, "add", "-A")
        taf.git(self.project, "commit", "-q", "-m", "手順3と method-access")
        return rec

    def change_code(self, tag):
        """入口のスクリプトを写しの中で変えてコミットする（run_id が変わる）。"""
        p = os.path.join(self.project, "src", "collector", "acquire_gkg.py")
        with open(p, "ab") as f:
            f.write(("# %s\n" % tag).encode())
        taf.git(self.project, "commit", "-q", "-am", tag)

    def run_with_root(self, fn, *a, **k):
        """関門が読むルート（ledger.PROJECT_ROOT）を、この中だけ写しに差し替える。"""
        with mock.patch.object(ledger, "PROJECT_ROOT", self.project):
            return fn(*a, **k)

    def acquire(self, s, mode="official"):
        return self.run_with_root(ag._acquire, mode, _test=s)

    def commit_manifest(self, msg="run-start"):
        taf.git(self.project, "add", "data/manifest")
        taf.git(self.project, "commit", "-q", "-m", msg)

    def acquire_official(self, s):
        """1回目は run-start を書いて止まる。コミットしてから、もう一度実行する。"""
        with self.assertRaises(Exception) as cm:
            self.acquire(s)
        self.assertEqual(type(cm.exception).__name__, "RunStartWritten")
        self.assertEqual(self.gtransport.calls, [])
        self.commit_manifest()
        return self.acquire(self.gseams())

    def gate(self, s):
        return self.run_with_root(lambda: ag.check_gate(s, ag._method_access_gate(s)))

    def gseams(self, **kw):
        self.gtransport = tg.FakeTransport({ts: [tg.ok_response(z)]
                                            for ts, z in self.zips.items()})
        base = dict(project=self.project, home=self.home, volume=self.volume,
                    transport=self.gtransport, sleep=lambda s: None, clock=self.clock,
                    now=lambda: tg.NOW, log=self.gkg_logs.append,
                    disk_free=lambda p: 100 * 1024 ** 3, check_volume=self.check_volume,
                    fs_check=self.fs_check, drand_fetch=self.gdrand, ots_cmd="ots",
                    ots_runner=self.gots)
        base.update(kw)
        return ag._TestSeams(**base)

    def gsnapshot(self):
        return {"sealed": taf.tree_files(os.path.join(self.project, "sealed")),
                "manifest": taf.tree_files(os.path.join(self.project, "data", "manifest")),
                "store": taf.tree_files(self.gkg_store),
                "trial": taf.tree_files(self.trial_store)}

    def refuse(self, pattern, mode="official", **kw):
        before = self.gsnapshot()
        s = self.gseams(**kw)
        with self.assertRaises(ag.GateError) as cm:
            self.acquire(s, mode)
        self.assertRegex(str(cm.exception), pattern)
        self.assertEqual(self.gtransport.calls, [])
        self.assertEqual(self.gsnapshot(), before)


class TestEndToEnd(E2ECase):
    def test_stops_without_method_access(self):
        taf.git(self.project, "add", "-A")
        taf.git(self.project, "commit", "-q", "-m", "手順3")
        before = self.gsnapshot()
        s = self.gseams()
        with self.assertRaisesRegex(ledger.MethodAccessRequired, "method-access の記録が鎖に無い"):
            self.acquire(s)
        self.assertEqual(self.gtransport.calls, [])
        self.assertEqual(self.gsnapshot(), before)

    def test_full_run(self):
        rec = self.add_method_access()
        out = self.acquire_official(self.gseams())
        self.assertEqual(out["files_ok"], len(self.zips))
        self.assertEqual(sorted(self.gtransport.calls), sorted(self.zips))
        man = gkg.read_jsonl(os.path.join(self.project, "data", "manifest", gkg.MANIFEST_NAME))
        self.assertEqual([e["kind"] for e in man],
                         ["run-start", "run-resume"] + ["day"] * len(self.DAYS) + ["run-complete"])
        self.assertEqual(man[0]["store_location"], "LACIE SHARE:/news-stick-data/gkg-method")
        runs = gkg_run_docs(self.project)                  # T-032：封印の記録に1件
        self.assertEqual([d["mode"] for _r, d in runs], ["official"])
        r, d = runs[0]
        self.assertEqual(man[0]["gkg_run_seq"], r["seq"])
        self.assertEqual(man[0]["gkg_run_record_sha256"],
                         ledger.sha256_hex(ledger.canonical_line(r)))
        self.assertEqual((d["run_id"], d["code_sha256"], d["exclusion_rule_seq"]),
                         (man[0]["run_id"], man[0]["code_sha256"], man[0]["exclusion_rule_seq"]))
        # T-069：取得の計画（days・files_selected）が、run-start の行と同じ値で記録に入る
        self.assertEqual((d["days"], d["files_selected"]), (man[0]["days"], man[0]["files_selected"]))
        self.assertEqual((d["days"], d["files_selected"]), (len(self.DAYS), len(self.zips)))
        with open(ENTRY, "rb") as f:
            entry_sha = hashlib.sha256(f.read()).hexdigest()
        self.assertEqual(man[0]["code_sha256"], entry_sha)
        self.assertEqual(man[0]["run_id"], entry_sha[:16])
        self.assertEqual(man[0]["method_access_seq"], rec["seq"])
        fl = filelist_entry(self.project)
        self.assertEqual(man[0]["filelist_sha256"], fl["sha256"])
        # 書いたものとログに、捨てた欄の目印もメールアドレスの形も無い
        written = {}
        for top in (self.gkg_store, os.path.join(self.project, "data", "manifest")):
            for n in os.listdir(top):
                if n.startswith("._"):
                    continue                           # macOS の付属のファイル（FAT32）
                with open(os.path.join(top, n), "rb") as f:
                    b = f.read()
                written[n] = tg.gzip.decompress(b) if n.endswith(".gz") else b
        written["log"] = "\n".join(self.gkg_logs).encode()
        for name, data in written.items():
            self.assertEqual(gkg.privacy_scan.find_in_bytes(data), {}, name)
            for mk in tg.all_markers():
                self.assertNotIn(mk, data, (name, mk))
            self.assertNotIn(self.home.encode(), data, name)
            self.assertNotIn(self.volume.encode(), data, name)
            self.assertNotIn(self.tmp.encode(), data, name)

    def test_uncommitted_run_start_stops_before_any_request(self):
        """T-018 の監査 軽2：run-start をコミットしないまま再実行しても、要求を送らない。"""
        self.add_method_access()
        with self.assertRaises(Exception) as cm:
            self.acquire(self.gseams())
        self.assertEqual(type(cm.exception).__name__, "RunStartWritten")
        before = self.gsnapshot()
        with self.assertRaises(Exception) as cm:
            self.acquire(self.gseams())
        self.assertEqual(type(cm.exception).__name__, "GkgError")
        self.assertIn("コミットされていない", str(cm.exception))
        self.assertEqual(self.gtransport.calls, [])
        self.assertEqual(self.gsnapshot(), before)

    def test_trial_run_then_official(self):
        self.add_method_access()
        out = self.acquire(self.gseams(), mode="trial")
        self.assertEqual(out["days"], 3)               # 写しの一覧の3日は、どれも試しの run の日
        self.assertEqual({c[:8] for c in self.gtransport.calls},
                         {"20150302", "20150303", "20150304"})
        tm0 = gkg.read_jsonl(os.path.join(self.project, "data", "manifest",
                                          gkg.TRIAL_MANIFEST_NAME))[0]
        self.assertEqual((tm0["official"], tm0["trial"]), (False, True))
        self.assertFalse(os.path.exists(os.path.join(self.project, "data", "manifest",
                                                     gkg.MANIFEST_NAME)))
        tm = gkg.read_jsonl(os.path.join(self.project, "data", "manifest",
                                         gkg.TRIAL_MANIFEST_NAME))
        self.assertEqual(tm[0]["store_location"], "LACIE SHARE:/news-stick-data/gkg-trial")
        self.assertEqual(os.listdir(self.gkg_store), [])
        with self.assertRaises(Exception) as cm:              # 試しの run を未コミットのまま
            self.acquire(self.gseams())
        self.assertIn("全部コミットされていない", str(cm.exception))
        self.assertFalse(os.path.exists(os.path.join(self.project, "data", "manifest",
                                                     gkg.MANIFEST_NAME)))
        self.commit_manifest("試しの run")
        out = self.acquire_official(self.gseams())
        self.assertEqual(out["days"], len(self.DAYS))
        man = gkg.read_jsonl(os.path.join(self.project, "data", "manifest", gkg.MANIFEST_NAME))
        self.assertEqual(man[0]["trial_run_ids"], [out["run_id"]])
        with self.assertRaises(Exception) as cm:
            self.acquire(self.gseams(), mode="trial")
        self.assertIn("試しの run はしない", str(cm.exception))

    def test_gate_conditions(self):
        self.add_method_access()
        self.gate(self.gseams())   # 通る
        # 取得のコードの未コミットの変更
        p = os.path.join(self.project, "src", "collector", "gkg.py")
        with open(p, "ab") as f:
            f.write(b"# x\n")
        self.refuse("未コミットの変更")
        taf.git(self.project, "commit", "-q", "-am", "gkg を変える")
        self.refuse("固定した値と違う")
        taf.git(self.project, "revert", "--no-edit", "HEAD")
        # ファイル一覧の本体が違う
        fl = filelist_entry(self.project)
        body = os.path.join(self.home, *gkg.FILELIST_STORE_PARTS, fl["file_name"])
        with open(body, "ab") as f:
            f.write(b"x")
        self.refuse("本体の sha256")
        with open(body, "rb") as f:
            data = f.read()
        with open(body, "wb") as f:
            f.write(data[:-1])
        # 保存先が無い
        os.rmdir(self.gkg_store)
        self.refuse("gkg-method が無い")
        os.makedirs(self.gkg_store)
        os.rmdir(self.trial_store)
        self.refuse("gkg-trial が無い", mode="trial")
        os.makedirs(self.trial_store)
        # 保存先のディスクがマウントされていない・読み取り専用（本物の検査を使う）
        self.refuse("マウントされていない", check_volume=None)
        with mock.patch.object(os.path, "ismount", return_value=True), \
                mock.patch.object(os, "statvfs", return_value=mock.Mock(f_flag=os.ST_RDONLY)):
            self.refuse("読み取り専用", check_volume=None)
        self.gate(self.gseams())

    def test_project_root_must_match(self):
        """関門が読んだプロジェクト（本物）と、差し替えの project が違えば止まる。"""
        self.add_method_access()
        with mock.patch.object(ledger, "require_method_access", return_value={"seq": 5}), \
                mock.patch.object(ag, "_exclusion_gate", pass_exclusion_gate):
            with self.assertRaisesRegex(ag.GateError, "プロジェクトが違う"):
                ag._acquire(_test=self.gseams())

    def test_method_block_must_match(self):
        rec = self.add_method_access()
        with mock.patch.object(ledger, "read_target_json",
                               return_value={"block_start": "2015-03-01",
                                             "block_end": "2020-12-14"}):
            with self.assertRaisesRegex(ag.GateError, "区画"):
                ag.check_gate(self.gseams(), rec, "official")

    def test_two_filelist_manifest_lines_refused(self):
        self.add_method_access()
        p = os.path.join(self.project, "data", "manifest", "gdelt-filelist.jsonl")
        with open(p, "rb") as f:
            line = f.read()
        with open(p, "ab") as f:
            f.write(line)
        self.refuse("ちょうど1行")


@unittest.skipUnless(os.environ.get(tg.FAT32_ENV), "FAT32 のイメージのマウント先が渡されていない "
                     "（%s。手順は src/collector/README.md 7章）" % tg.FAT32_ENV)
class TestEndToEndOnFat32(E2ECase):
    """FAT32 のイメージを保存先のディスクにして、関門（本物の check_volume）から取得まで通す（T-021）。

    TMPDIR をイメージのある場所（scratchpad）にして実行する（テストの差し替えは一時的な
    ディレクトリの下しか指せないため）。
    """

    def make_volume(self):
        v = tg._fat32_mount(tg.FAT32_ENV)
        if not ag._under_tmp(v):
            self.fail("TMPDIR を、イメージのマウント先を含む場所にして実行する（README 7.1）")
        base = os.path.join(v, gkg.STORE_PARTS[0])
        if os.path.lexists(base):
            self.fail("イメージの直下に news-stick-data が既にある（前のテストの残り）")
        self.addCleanup(shutil.rmtree, base, True)     # テスト用のイメージの中だけ
        return v

    def setUp(self):
        super().setUp()
        self.check_volume = None                       # 関門と取得で本物の gkg.check_volume
        self.fs_check = None                           # 本物の diskutil で形式を確かめる

    def test_trial_and_official_on_fat32(self):
        self.add_method_access()
        self.acquire(self.gseams(), mode="trial")
        self.commit_manifest("試しの run")
        out = self.acquire_official(self.gseams())
        self.assertEqual(out["files_ok"], len(self.zips))
        man = gkg.read_jsonl(os.path.join(self.project, "data", "manifest", gkg.MANIFEST_NAME))
        # オーナーの決定：イメージの VolumeUUID が、どの記録にも書かれていないこと
        info = plistlib.loads(subprocess.run(["/usr/sbin/diskutil", "info", "-plist", self.volume],
                                             capture_output=True, timeout=60).stdout)
        uuid = info["VolumeUUID"].encode()
        for top in (os.path.join(self.project, "data", "manifest"), self.gkg_store,
                    self.trial_store):
            for n in os.listdir(top):
                with open(os.path.join(top, n), "rb") as f:
                    b = f.read()
                if n.endswith(".gz") and not n.startswith("._"):   # ._ は macOS の付属のファイル
                    b = tg.gzip.decompress(b)
                for form in (uuid, uuid.lower(), hashlib.sha256(uuid).hexdigest().encode()):
                    self.assertNotIn(form, b, n)
                self.assertNotIn(b"volume_id", b, n)
        self.assertNotIn(uuid, "\n".join(self.gkg_logs).encode())
        for e in man:
            if e["kind"] == "day":
                with open(os.path.join(self.gkg_store, e["file_name"]), "rb") as f:
                    self.assertEqual(hashlib.sha256(f.read()).hexdigest(), e["sha256"])

    def test_case_variant_folder_refused_by_gate(self):
        self.add_method_access()
        os.rename(self.gkg_store, os.path.join(os.path.dirname(self.gkg_store), "Gkg-Method"))
        self.refuse("大文字と小文字")


class TestSealGkgRun(E2ECase):
    """T-032：試しの run と正式な run の開始を、写しの封印の記録に gkg-run-start として書く。"""

    def test_two_trial_runs_leave_two_records(self):
        self.add_method_access()
        self.acquire(self.gseams(), mode="trial")
        self.commit_manifest("試しの run 1")
        self.change_code("試しの run 2 のための変更")
        self.acquire(self.gseams(), mode="trial")
        runs = gkg_run_docs(self.project)
        self.assertEqual([d["mode"] for _r, d in runs], ["trial", "trial"])
        self.assertNotEqual(runs[0][1]["run_id"], runs[1][1]["run_id"])
        self.assertEqual(runs[0][1]["trial_days"], ["2015-03-02", "2015-03-03", "2015-03-04"])
        for _r, d in runs:
            self.assertEqual(d["exclusion_rule_seq"], self.order1_seq)
        tm = gkg.read_jsonl(os.path.join(self.project, "data", "manifest", gkg.TRIAL_MANIFEST_NAME))
        starts = [e for e in tm if e["kind"] == "run-start"]
        self.assertEqual([e["gkg_run_seq"] for e in starts], [r["seq"] for r, _d in runs])
        self.assertEqual([e["run_id"] for e in starts], [d["run_id"] for _r, d in runs])
        # T-069：試しの run も、取得の計画を run-start の行と同じ値で記録に入れる
        self.assertEqual([(d["days"], d["files_selected"]) for _r, d in runs],
                         [(e["days"], e["files_selected"]) for e in starts])
        self.assertEqual([d["days"] for _r, d in runs], [3, 3])

    def test_resume_writes_no_second_record(self):
        self.add_method_access()
        calls = []

        def disk_free(p):                              # run-start を書いたあと、日の集計の前に止まる
            calls.append(p)
            return 100 * 1024 ** 3 if len(calls) == 1 else 0
        s = self.gseams(disk_free=disk_free)
        with self.assertRaises(Exception) as cm:
            self.acquire(s, mode="trial")
        self.assertEqual(type(cm.exception).__name__, "RunInterrupted")
        self.assertEqual(len(gkg_run_docs(self.project)), 1)
        self.acquire(self.gseams(), mode="trial")
        self.assertEqual(len(gkg_run_docs(self.project)), 1)

    def test_seal_failure_sends_no_request(self):
        self.add_method_access()
        before = self.gsnapshot()

        def broken(url):
            raise OSError("見本：drand に届かない")
        for mode in ("trial", "official"):
            with self.subTest(mode=mode):
                s = self.gseams(drand_fetch=broken)
                with self.assertRaises(Exception) as cm:
                    self.acquire(s, mode)
                self.assertIn("gkg-run-start を書けなかった", str(cm.exception))
                self.assertEqual(self.gtransport.calls, [])
                self.assertEqual(self.gsnapshot(), before)
                self.assertEqual(gkg_run_docs(self.project), [])

    def test_sealer_gate_stops_without_order1b(self):
        """順番1b の無い封印の記録では、封印係の関門が drand の前に止め、要求は送らない。"""
        self.add_method_access()
        with mock.patch.object(ledger, "ORDER1B_KIND", "stats-order1b-none"):
            s = self.gseams()
            with self.assertRaises(Exception) as cm:
                self.acquire(s, "trial")
        # 封印係が関門（method-access の関門など）に順番1b の照合を入れても通るように、関門の文言も受け付ける
        self.assertRegex(str(cm.exception),
                         "gkg-run-start を書けなかった|stats-order1b（順番1b）の記録が無い")
        self.assertEqual(self.gtransport.calls, [])
        self.assertEqual(self.gdrand.urls, [])

    def test_existing_record_is_reused_when_manifest_line_missing(self):
        """記録を書いたあと run-start の行を書く前に止まった跡：同じ run の記録を新しく書かない。"""
        self.add_method_access()
        stop = RuntimeError("見本：run-start の行を書く前に止まる")
        orig_exec = ag._exec_module
        calls = []

        def exec_module(name, path, source):
            mod = orig_exec(name, path, source)
            if name == "gkg" and not calls:
                calls.append(1)

                def mark(*a, **k):
                    raise stop
                mod.write_volume_mark = mark
            return mod
        with mock.patch.object(ag, "_exec_module", exec_module):
            with self.assertRaises(RuntimeError):
                self.acquire(self.gseams(), mode="trial")
        self.assertEqual(len(gkg_run_docs(self.project)), 1)
        self.acquire(self.gseams(), mode="trial")
        runs = gkg_run_docs(self.project)
        self.assertEqual(len(runs), 1)
        tm = gkg.read_jsonl(os.path.join(self.project, "data", "manifest", gkg.TRIAL_MANIFEST_NAME))
        self.assertEqual(tm[0]["gkg_run_seq"], runs[0][0]["seq"])


class FailingStampOts(taf.FakeOts):
    """ots --version は通し、ots stamp だけ失敗する（通信の失敗の見本）。"""

    def __call__(self, cmd, input=None, capture_output=True, timeout=None):
        if cmd[1:] == ["--version"]:
            return super().__call__(cmd, input, capture_output, timeout)
        self.calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 1, stdout=b"", stderr=b"stamp failed")


class TestT045(E2ECase):
    """T-045：make_start_hook は常に seal_gkg_run.start を呼び、使い回しの判断は start に任せる。"""

    def ledger_path(self):
        return os.path.join(self.project, "sealed", "ledger.jsonl")

    def stop_before_row(self, **kw):
        """gkg-run-start を書いたあと、印のファイルと run-start の行を書く前に止める。"""
        orig = ag._exec_module
        n = []

        def exec_module(name, path, source):
            mod = orig(name, path, source)
            if name == "gkg" and not n:
                n.append(1)

                def mark(*a, **k):
                    raise RuntimeError("見本：行を書く前に止まる")
                mod.write_volume_mark = mark
            return mod
        with mock.patch.object(ag, "_exec_module", exec_module):
            with self.assertRaises(RuntimeError):
                self.acquire(self.gseams(**kw), mode="trial")
        self.assertEqual(self.gtransport.calls, [])

    def test_hook_always_calls_start(self):
        self.add_method_access()
        calls = []
        real = ag.seal_gkg_run.start

        def spy(*a, **k):
            calls.append(a[1])
            return real(*a, **k)
        self.stop_before_row()
        with mock.patch.object(ag.seal_gkg_run, "start", spy):
            self.acquire(self.gseams(), mode="trial")       # 既にある記録でも start を通る
        self.assertEqual(calls, ["trial"])
        self.assertEqual(len(gkg_run_docs(self.project)), 1)
        src = inspect.getsource(ag.make_start_hook)
        self.assertNotIn("verify_chain", src)
        self.assertNotIn("read_target_json", src)

    def test_stamp_failure_then_rerun_without_ots_stops_then_stamp_and_retry_passes(self):
        """T-043 の流れ：stamp の失敗 → .ots を作らずに再実行すると要求0件で止まる → stamp.py の
        手順で .ots を作る → 同じ run_id でやり直すと、記録を使い回して進む。"""
        self.add_method_access()
        before = self.gsnapshot()["store"], self.gsnapshot()["trial"]
        with self.assertRaises(Exception) as cm:
            self.acquire(self.gseams(ots_runner=FailingStampOts()), mode="trial")
        self.assertIn("gkg-run-start を書けなかった", str(cm.exception))
        self.assertEqual(self.gtransport.calls, [])
        runs = gkg_run_docs_unchecked(self.project)
        self.assertEqual(len(runs), 1)                      # 記録は残り、.ots は無い
        seq = runs[0]["seq"]
        self.assertFalse(os.path.exists(os.path.join(self.project, "sealed", ledger.ots_name(seq))))
        with self.assertRaises(Exception) as cm:
            self.acquire(self.gseams(), mode="trial")       # .ots を作らずに再実行
        # 止まる理由：その seq の .ots が無い（最初に照らす関門の check_anchors が見つける。
        # 関門より先に進んでも、seal_gkg_run.start の最初の load_checked が同じ照合で止める）
        self.assertIn("seq %d の記録に、その seq 自身の時刻証明（.ots）が無い" % seq, str(cm.exception))
        self.assertEqual(self.gtransport.calls, [])
        self.assertEqual((self.gsnapshot()["store"], self.gsnapshot()["trial"]), before)
        stamp.stamp_seq(self.ledger_path(), seq, "ots", runner=taf.FakeOts())   # stamp.py の手順
        out = self.acquire(self.gseams(), mode="trial")
        self.assertEqual(out["days"], len(self.DAYS))
        runs = gkg_run_docs(self.project)
        self.assertEqual([r["seq"] for r, _d in runs], [seq])
        tm = gkg.read_jsonl(os.path.join(self.project, "data", "manifest", gkg.TRIAL_MANIFEST_NAME))
        self.assertEqual(tm[0]["gkg_run_seq"], seq)

    def test_different_inputs_stop_with_no_request(self):
        self.add_method_access()
        self.stop_before_row()
        real = ag.make_start_hook

        def other_inputs(s, gate, exclusion_rule):
            return real(s, dict(gate, filelist_sha256="0" * 64), exclusion_rule)
        with mock.patch.object(ag, "make_start_hook", other_inputs):
            with self.assertRaises(Exception) as cm:
                self.acquire(self.gseams(), mode="trial")
        self.assertIn("filelist_sha256", str(cm.exception))
        self.assertEqual(self.gtransport.calls, [])
        self.assertEqual(len(gkg_run_docs(self.project)), 1)

    def test_honest_resume(self):
        self.add_method_access()
        calls = []

        def disk_free(p):
            calls.append(p)
            return 100 * 1024 ** 3 if len(calls) == 1 else 0
        with self.assertRaises(Exception):
            self.acquire(self.gseams(disk_free=disk_free), mode="trial")
        out = self.acquire(self.gseams(), mode="trial")
        self.assertEqual(out["days"], len(self.DAYS))
        self.assertEqual(len(gkg_run_docs(self.project)), 1)

    def test_trial_run_ids_follow_record_seq_order(self):
        """監査の a43probe の流れ：A の記録（行の前で止まる）→ B の記録と run → A に戻して使い回し
        → 正式な run。マニフェストの行の順（B, A）と記録の seq の順（A, B）がずれても、
        trial_run_ids は記録の seq の順になり、封印係の照合（verify.py gkg-runs）が通る。"""
        self.add_method_access()
        code = os.path.join(self.project, "src", "collector", "acquire_gkg.py")
        with open(code, "rb") as f:
            orig = f.read()
        self.stop_before_row()                               # A：記録だけ
        self.change_code("コード B")
        self.acquire(self.gseams(), mode="trial")            # B：記録と行
        with open(code, "wb") as f:
            f.write(orig)
        taf.git(self.project, "commit", "-q", "-am", "コード A に戻す")
        self.acquire(self.gseams(), mode="trial")            # A：使い回し
        runs = gkg_run_docs(self.project)
        self.assertEqual(len(runs), 2)
        tm = gkg.read_jsonl(os.path.join(self.project, "data", "manifest", gkg.TRIAL_MANIFEST_NAME))
        row_order = [e["run_id"] for e in tm if e["kind"] == "run-start"]
        seq_order = [d["run_id"] for _r, d in runs]
        self.assertEqual(row_order, list(reversed(seq_order)))   # 行の順と seq の順がずれている
        self.commit_manifest("試しの run")
        out = self.acquire_official(self.gseams())
        man = gkg.read_jsonl(os.path.join(self.project, "data", "manifest", gkg.MANIFEST_NAME))
        self.assertEqual(man[0]["trial_run_ids"], seq_order)
        self.commit_manifest("正式な run")
        self.assertEqual(out["files_failed"], 0)
        # 封印係の照合（verify.py gkg-runs が使う ledger.check_gkg_manifests）を、写しの上で直接呼ぶ。
        # 写しの sealed/ には本物の Bitcoin のヘッダが写っていて、テストの .ots と合わないので、
        # verify.py の .ots の照合は通さず、マニフェストの照合だけを行う
        data = ledger.read_ledger(self.ledger_path())
        records = ledger.verify_chain(data)
        manifests = {}
        for mode, rel in ledger.GKG_MANIFESTS.items():
            with open(os.path.join(self.project, rel), "rb") as f:
                manifests[mode] = f.read()
        got = ledger.check_gkg_manifests(
            records, lambda r, role: ledger.read_target_json(self.project, r, role), manifests)
        self.assertEqual(got["trial"], (2, 2))
        self.assertEqual(got["official"], (1, 1))
        # 行の順で並べた一覧は、封印係の照合で止まる（並べ方を決めた理由）
        rows = [json.loads(l) for l in manifests["official"].splitlines() if l.strip()]
        rows[0]["trial_run_ids"] = row_order
        bad = b"".join(json.dumps(r, sort_keys=True, ensure_ascii=True).encode() + b"\n" for r in rows)
        with self.assertRaisesRegex(ledger.LedgerError, "trial_run_ids"):
            ledger.check_gkg_manifests(
                records, lambda r, role: ledger.read_target_json(self.project, r, role),
                dict(manifests, official=bad))


class TestSealedRunCheck(E2ECase):
    """T-032 の差し戻し1回目 中-1（監査の test_forged_row_skips_hook の形）：手で書いた run-start の行を
    置いても、再開のときに封印の記録と照らして止まり、gkg-run-start を書かずに試しの run は走らない。"""

    def forge_start(self, ref):
        """gkg-run-start を書く代わりに ref を返す（記録を書かない）形で run-start の行を書き、
        要求を送る前に止める。返り値なし。"""
        orig = ag._exec_module
        n = []

        def exec_module(name, path, source):
            mod = orig(name, path, source)
            if name == "gkg" and not n:
                n.append(1)
                mod._seal_run_start = lambda *a, **k: dict(ref)

                def stop(*a, **k):
                    raise mod.RunInterrupted("見本：要求を送る前に止める")
                mod._run_plan = stop
            return mod
        with mock.patch.object(ag, "_exec_module", exec_module):
            with self.assertRaises(Exception) as cm:
                self.acquire(self.gseams(), mode="trial")
        self.assertEqual(type(cm.exception).__name__, "RunInterrupted")
        self.assertEqual(self.gtransport.calls, [])

    def assert_resume_stops(self, pattern):
        before = self.gsnapshot()
        n_runs = len(gkg_run_docs(self.project))
        s = self.gseams()
        with self.assertRaises(Exception) as cm:
            self.acquire(s, mode="trial")
        self.assertEqual(type(cm.exception).__name__, "GkgError")
        self.assertRegex(str(cm.exception), pattern)
        self.assertEqual(self.gtransport.calls, [])
        self.assertEqual(self.gsnapshot(), before)
        self.assertEqual(len(gkg_run_docs(self.project)), n_runs)

    def test_forged_row_pointing_at_other_kind(self):
        self.add_method_access()
        self.forge_start({"seq": 1, "record_sha256": "0" * 64})       # seq 1 は periods
        self.assert_resume_stops("gkg-run-start でない")

    def test_forged_row_with_missing_seq(self):
        self.add_method_access()
        self.forge_start({"seq": 999, "record_sha256": "0" * 64})
        self.assert_resume_stops("封印の記録に無い")

    def real_trial_record(self):
        """本物の試しの run を1回行い（コード A）、その gkg-run-start の記録を返す。"""
        self.add_method_access()
        self.acquire(self.gseams(), mode="trial")
        self.commit_manifest("試しの run A")
        (r, d), = gkg_run_docs(self.project)
        return r, d

    def test_forged_row_with_sha_mismatch(self):
        r, _d = self.real_trial_record()
        self.change_code("コード B")
        self.forge_start({"seq": r["seq"], "record_sha256": "0" * 64})
        self.assert_resume_stops("一致しない")

    def test_forged_row_pointing_at_other_run_id(self):
        r, _d = self.real_trial_record()
        self.change_code("コード B")
        self.forge_start({"seq": r["seq"],
                          "record_sha256": ledger.sha256_hex(ledger.canonical_line(r))})
        self.assert_resume_stops("この run")

    def test_honest_resume_after_real_record_passes(self):
        self.add_method_access()
        calls = []

        def disk_free(p):
            calls.append(p)
            return 100 * 1024 ** 3 if len(calls) == 1 else 0
        with self.assertRaises(Exception):
            self.acquire(self.gseams(disk_free=disk_free), mode="trial")
        out = self.acquire(self.gseams(), mode="trial")
        self.assertEqual(out["days"], len(self.DAYS))
        self.assertEqual(len(gkg_run_docs(self.project)), 1)


class TestCodeScope(unittest.TestCase):
    def test_pins_match_current_files(self):
        self.assertEqual([r for r, _ in ag.PINNED_SHA256],
                         ["src/collector/gkg.py", "src/collector/filelist.py",
                          "src/collector/privacy_scan.py", "src/collector/codegate.py",
                          "src/collector/themes.py"])
        for rel, want in ag.PINNED_SHA256:
            self.assertEqual(taf.sha_file(os.path.join(PROJECT, rel)), want, rel)
        self.assertEqual(ag.CODE_REL, gkg.CODE_REL)
        self.assertEqual(ag.CLEAN_PATHS, ("src/collector", "src/sealer"))

    def test_citation(self):
        self.assertIn("Data: The GDELT Project (https://www.gdeltproject.org/).",
                      " ".join(ag.__doc__.split()))


class TestProductionPath(unittest.TestCase):
    def test_main_rejects_arguments(self):
        never = mock.Mock(side_effect=AssertionError("呼んではいけない"))
        with mock.patch.object(ag, "_acquire", never), mock.patch("sys.stderr"):
            for argv in (["--root", "/tmp/x"], ["-h"], ["x"], ["--trial", "x"], ["--official"],
                         ["--TRIAL"], ["trial"]):
                self.assertEqual(ag.main(argv), 2)
        never.assert_not_called()

    def test_main_modes(self):
        done = {"run_id": "a" * 16, "days": 1, "files_ok": 1, "files_failed": 0}
        got = mock.Mock(return_value=done)
        out = io.StringIO()
        with mock.patch.object(ag, "_acquire", got), mock.patch("sys.stdout", out):
            self.assertEqual(ag.main([]), 0)
            self.assertEqual(ag.main(["--trial"]), 0)
        text = " ".join(out.getvalue().split())
        self.assertIn("Data: The GDELT Project (https://www.gdeltproject.org/). This project is not "
                      "affiliated with or endorsed by the GDELT Project.", text)
        self.assertIn("データ出典：GDELT Project（https://www.gdeltproject.org/）。本プロジェクトは "
                      "GDELT Project と提携・承認の関係にありません。", text)
        self.assertEqual([c.args for c in got.call_args_list], [("official",), ("trial",)])
        with mock.patch.object(ledger, "require_method_access", return_value={"seq": 1}), \
                mock.patch.object(ag, "_exclusion_gate", pass_exclusion_gate), \
                mock.patch.object(ag, "_check_code", file_codes), \
                mock.patch.object(ag, "check_gate", side_effect=AssertionError("進まない")):
            with self.assertRaises(ValueError):
                ag._acquire("other")

    def test_main_exit_codes(self):
        with mock.patch.object(ag, "_acquire", mock.Mock(side_effect=gkg.RunInterrupted("x"))), \
                mock.patch("sys.stderr"):
            self.assertEqual(ag.main([]), 3)
        with mock.patch.object(ag, "_acquire", mock.Mock(side_effect=ag.GateError("x"))), \
                mock.patch("sys.stderr"):
            self.assertEqual(ag.main([]), 1)
        with mock.patch.object(ag, "_acquire", mock.Mock(side_effect=gkg.RunStartWritten("x"))), \
                mock.patch("sys.stderr"):
            self.assertEqual(ag.main([]), 4)
        with mock.patch.object(ag, "_acquire", mock.Mock(side_effect=gkg.GkgError("x"))), \
                mock.patch("sys.stderr"):
            self.assertEqual(ag.main([]), 1)
        boom = RuntimeError("見本")
        with mock.patch.object(ag, "_acquire", mock.Mock(side_effect=boom)):
            with self.assertRaises(RuntimeError):
                ag.main([])

    def test_production_seams_fixed(self):
        fake = tempfile.mkdtemp(prefix="gkg-env-")
        self.addCleanup(shutil.rmtree, fake, True)
        with mock.patch.dict(os.environ, {"HOME": fake, "TMPDIR": fake}):
            s = ag._production_seams()
        self.assertEqual(s.project, PROJECT)
        self.assertEqual(s.home, pwd.getpwuid(os.getuid()).pw_dir)
        self.assertIsNone(s.transport)
        self.assertIsNone(s.volume)                    # 関門で gkg.VOLUME_MOUNT に決まる
        self.assertIsNone(s.check_volume)              # 関門で gkg.check_volume に決まる
        self.assertIsNone(s.fs_check)                  # 関門で check_filesystem に決まる
        self.assertIs(s.sleep, time.sleep)
        self.assertIs(type(s), ag._Seams)
        with self.assertRaises(AttributeError):
            s.project = "/tmp"

    def test_entry_reads_no_environment(self):
        with open(ENTRY, encoding="utf-8") as f:
            code = f.read().split('"""', 2)[2]
        for word in ("os.environ", "getenv", "argparse", "expanduser"):
            self.assertNotIn(word, code)

    def test_test_seams_cannot_point_at_real_places(self):
        tmp = tempfile.mkdtemp(prefix="gkg-seam-")
        self.addCleanup(shutil.rmtree, tmp, True)

        def seams(**kw):
            base = dict(project=tmp, home=tmp, volume=tmp, transport=None, sleep=None,
                        clock=None, now=None, log=None, disk_free=None, check_volume=None,
                        fs_check=None, drand_fetch=None, ots_cmd=None, ots_runner=None)
            base.update(kw)
            return ag._TestSeams(**base)

        gate = mock.Mock(side_effect=AssertionError("関門まで進んではいけない"))
        with mock.patch.object(ledger, "require_method_access", gate):
            for bad in (seams(project=PROJECT), seams(home=pwd.getpwuid(os.getuid()).pw_dir),
                        seams(project="/"), seams(volume="/Volumes/LACIE SHARE"),
                        seams(volume=None), seams(volume="/Volumes")):
                with self.assertRaises(ValueError):
                    ag._acquire(_test=bad)
            for bad in (ag._production_seams(), object()):
                with self.assertRaises(TypeError):
                    ag._acquire(_test=bad)
            os.makedirs(os.path.join(tmp, "data"))
            os.symlink(PROJECT + "/sealed", os.path.join(tmp, "sealed"))
            with self.assertRaises(ValueError):
                ag._acquire(_test=seams())
        gate.assert_not_called()

    def test_script_with_argument_does_nothing(self):
        r = subprocess.run([sys.executable, "-B", ENTRY, "--x"], capture_output=True, timeout=60,
                           env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
        self.assertEqual(r.returncode, 2)
        self.assertEqual(r.stdout, b"")


class TestOfficialResultGate(E2ECase):
    """T-069：正式な run の結果を使う入口（gkg.official_day_records）は、最初に封印係の関門
    ledger.require_gkg_run_result("official", run_id) を呼ぶ。gkg-run-result の無い run では、
    マニフェストも日の集計も読まずに止まり、ある run では通る。"""

    def full_official(self):
        self.add_method_access()
        out = self.acquire_official(self.gseams())
        self.commit_manifest("正式な run の結果")
        return out

    def entry(self):
        return self.run_with_root(gkg.official_day_records)

    def manifest_rows(self):
        return gkg.read_jsonl(os.path.join(self.project, "data", "manifest", gkg.MANIFEST_NAME))

    def seal_result(self, run_id):
        rec, _rel, _o = seal_gkg_result.seal(self.project, "official", run_id, tg.NOW, "ots",
                                             runner=taf.FakeOts())
        taf.git(self.project, "add", "-A", "sealed")
        taf.git(self.project, "commit", "-q", "-m", "gkg-run-result")
        return rec

    def assert_stops_before_reading(self, pattern):
        never = mock.Mock(side_effect=AssertionError("関門より前に、マニフェストを読んではいけない"))
        with mock.patch.object(gkg, "read_bytes_nofollow", never), \
                mock.patch.object(gkg, "read_jsonl", never), \
                mock.patch.object(gkg, "day_records_of", never):
            with self.assertRaises(gkg.GkgError) as cm:
                self.entry()
        self.assertRegex(str(cm.exception), pattern)
        never.assert_not_called()
        return cm.exception

    def test_stops_without_result_then_passes_with_result(self):
        out = self.full_official()
        calls = []
        real_gate = ledger.require_gkg_run_result

        def gate(mode, run_id):
            calls.append((mode, run_id))
            return real_gate(mode, run_id)
        with mock.patch.object(ledger, "require_gkg_run_result", gate):
            e = self.assert_stops_before_reading("gkg-run-result の関門を通らない")
        self.assertIsInstance(e.__cause__, ledger.GkgRunResultRequired)
        self.assertEqual(calls, [("official", out["run_id"])])
        self.seal_result(out["run_id"])
        with mock.patch.object(ledger, "require_gkg_run_result", gate):
            days = self.entry()
        self.assertEqual(calls[-1], ("official", out["run_id"]))
        self.assertEqual(days, gkg.day_records_of(self.manifest_rows()))
        self.assertEqual(len(days), len(self.DAYS))

    def test_stops_on_rewrite_before_or_after_gate(self):
        out = self.full_official()
        self.seal_result(out["run_id"])
        want = self.entry()
        path = os.path.join(self.project, "data", "manifest", gkg.MANIFEST_NAME)
        with open(path, "rb") as f:
            body = f.read()
        bad = body.replace(b'"2015-03-02"', b'"2015-03-12"', 1)
        self.assertNotEqual(bad, body)
        # 封印した先頭の書き換え：関門が止める（マニフェストを読まない）
        with open(path, "wb") as f:
            f.write(bad)
        self.assert_stops_before_reading("gkg-run-result の関門を通らない")
        # 関門を通ったあと、読む前に書き換わった場合：読み直したバイト列の sha256 で止まる
        with open(path, "wb") as f:
            f.write(body)
        real_gate = ledger.require_gkg_run_result

        def gate_then_rewrite(mode, run_id):
            rec = real_gate(mode, run_id)
            with open(path, "wb") as f:
                f.write(bad)
            return rec
        with mock.patch.object(ledger, "require_gkg_run_result", gate_then_rewrite):
            with self.assertRaisesRegex(gkg.GkgError, "関門のあとで変わった"):
                self.entry()
        with open(path, "wb") as f:
            f.write(body)
        self.assertEqual(self.entry(), want)

    def test_stops_without_official_run(self):
        self.add_method_access()
        self.acquire(self.gseams(), mode="trial")
        self.commit_manifest("試しの run")
        never = mock.Mock(side_effect=AssertionError("関門まで進んではいけない"))
        with mock.patch.object(ledger, "require_gkg_run_result", never):
            with self.assertRaisesRegex(gkg.GkgError, "正式な run（official）の gkg-run-start が 0 件"):
                self.entry()
        never.assert_not_called()

    def test_entry_takes_no_arguments_and_calls_gate_first(self):
        self.assertEqual(list(inspect.signature(gkg.official_day_records).parameters), [])
        src = inspect.getsource(gkg.official_day_records).split('"""', 2)[2]
        gate_at = src.index("ledger.require_gkg_run_result(\"official\", run_id)")
        for later in ("read_bytes_nofollow(", "manifest_prefix(", "day_records_of("):
            self.assertLess(gate_at, src.index(later), later)


# --- T-069：封印係が ledger.GKG_RUN_PLAN_REQUIRED_FOR_OFFICIAL を True にしたあとも通ること ---------

class _PlanRequired:
    """ledger.GKG_RUN_PLAN_REQUIRED_FOR_OFFICIAL を True に差し替えて、同じテストを流す（T-069）。"""

    def setUp(self):
        p = mock.patch.object(ledger, "GKG_RUN_PLAN_REQUIRED_FOR_OFFICIAL", True)
        p.start()
        self.addCleanup(p.stop)
        super().setUp()


class TestPlanRequiredSwitch(E2ECase):
    """差し替えが封印係の書く側（seal_gkg_run.start）に届いていることの確かめ（対照）。"""

    def setUp(self):
        super().setUp()
        p = mock.patch.object(ledger, "GKG_RUN_PLAN_REQUIRED_FOR_OFFICIAL", True)
        p.start()
        self.addCleanup(p.stop)

    def test_same_ledger_module(self):
        self.assertIs(ag.seal_gkg_run.ledger, ledger)

    def test_official_without_plan_is_refused(self):
        """計画を渡さない hook（T-069 より前の形）なら、正式な run は gkg-run-start を書けずに止まる。"""
        self.add_method_access()
        real = ag.seal_gkg_run.start

        def without_plan(*a, days=None, files_selected=None, **k):
            return real(*a, **k)
        with mock.patch.object(ag.seal_gkg_run, "start", without_plan):
            with self.assertRaises(Exception) as cm:
                self.acquire(self.gseams())
        self.assertIn("取得の計画", str(cm.exception))
        self.assertEqual(self.gtransport.calls, [])
        self.assertEqual(gkg_run_docs(self.project), [])


for _base in (TestEndToEnd, TestEndToEndOnFat32, TestSealGkgRun, TestT045, TestSealedRunCheck,
              TestOfficialResultGate):
    _name = _base.__name__ + "PlanRequired"
    globals()[_name] = type(_name, (_PlanRequired, _base),
                            {"__doc__": "%s を、GKG_RUN_PLAN_REQUIRED_FOR_OFFICIAL = True で流す（T-069）。"
                                        % _base.__name__})
del _base, _name


if __name__ == "__main__":
    unittest.main()
