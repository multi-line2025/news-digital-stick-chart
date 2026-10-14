"""順番4：欠けた日の一覧（src/stats/missing_days.py）のテスト。T-087。

実行（プロジェクトのルートで）:
    PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -B -m unittest discover -s tests/stats -v

確かめること
  - 境目：72本ちょうどは欠けた日でない、71本は欠けた日、docs 0 は本数に依らず欠けた日（TestBoundaries）
  - 入口は gkg.official_day_records() で、gkg-run-result の関門を通る。関門が無ければマニフェストを
    読まずに止まり、封印すれば通る（TestGateEndToEnd。tests/collector の合成の run の仕組みを使う。
    ネットワークは使わない。写しの中で動き、本物の sealed/・data/manifest には書かない）
  - 日の集計のファイルを開かない（open・os.open を記録して確かめる）
  - 出力は決まった形の JSON（キー順）で、同じ入力から同じ sha256 が出る
"""

import builtins
import copy
import datetime
import hashlib
import inspect
import json
import os
import subprocess
import sys
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(os.path.dirname(HERE))
SRC = os.path.join(PROJECT, "src", "stats")
SCRIPT = os.path.join(SRC, "missing_days.py")
COLLECTOR_TESTS = os.path.join(PROJECT, "tests", "collector")
sys.path.insert(0, SRC)

import candidates  # noqa: E402
import missing_days as md  # noqa: E402

D = datetime.date
BLOCK3 = (D(2015, 3, 2), D(2015, 3, 4))


def row(day, files_ok, docs, files_listed=96, run_id="r1"):
    """マニフェストの day の行と同じ形の合成の行（数字の欄だけ意味を持つ）。"""
    return {"kind": "day", "mode": "official", "official": True, "run_id": run_id, "day": day,
            "files_listed": files_listed, "files_ok": files_ok,
            "files_failed": files_listed - files_ok, "docs": docs,
            "file_name": "gkg-official-x-day-%s.tsv.gz" % day.replace("-", ""), "sha256": "0" * 64}


class OpenRecorder:
    """builtins.open と os.open の呼び出しを記録する（中身はそのまま開く）。"""

    def __init__(self):
        self.paths = []
        self._open = builtins.open
        self._os_open = os.open

    def _b(self, file, *a, **k):
        if isinstance(file, (str, bytes, os.PathLike)):
            self.paths.append(os.fsdecode(file))
        return self._open(file, *a, **k)

    def _o(self, path, *a, **k):
        self.paths.append(os.fsdecode(path))
        return self._os_open(path, *a, **k)

    def __enter__(self):
        self._p1 = mock.patch.object(builtins, "open", self._b)
        self._p2 = mock.patch.object(os, "open", self._o)
        self._p1.start()
        self._p2.start()
        return self

    def __exit__(self, *exc):
        self._p2.stop()
        self._p1.stop()
        return False


class TestBoundaries(unittest.TestCase):

    def test_rule_constants_from_candidates(self):
        self.assertEqual(candidates.SLOTS_PER_DAY, 96)
        self.assertEqual(candidates.MIN_PRESENT_SLOTS, 72)

    def test_72_71_and_zero_docs(self):
        rows = [row("2015-03-02", 72, 10, files_listed=96),
                row("2015-03-03", 71, 10, files_listed=96),
                row("2015-03-04", 96, 0, files_listed=96)]
        rec = md.build(rows, BLOCK3)
        got = {m["day"]: m for m in rec["missing_days"]}
        self.assertEqual(sorted(got), ["2015-03-03", "2015-03-04"])
        self.assertEqual(got["2015-03-03"], {"day": "2015-03-03", "files_ok": 71, "files_listed": 96,
                                              "docs": 10, "below_min_files": True,
                                              "zero_docs": False})
        self.assertEqual(got["2015-03-04"]["zero_docs"], True)
        self.assertEqual(got["2015-03-04"]["below_min_files"], False)
        self.assertEqual(rec["missing_count"], 2)
        self.assertEqual(rec["partial_days_count"], 1)      # 72本の日（一部が欠けた日）
        self.assertEqual(rec["days_in_block"], 3)

    def test_72_with_zero_docs_is_missing_and_both_flags(self):
        rec = md.build([row("2015-03-02", 72, 0), row("2015-03-03", 0, 0, files_listed=0),
                        row("2015-03-04", 96, 1)], BLOCK3)
        got = {m["day"]: m for m in rec["missing_days"]}
        self.assertEqual(sorted(got), ["2015-03-02", "2015-03-03"])
        self.assertTrue(got["2015-03-03"]["below_min_files"] and got["2015-03-03"]["zero_docs"])
        self.assertEqual(rec["partial_days_count"], 0)

    def test_same_as_day_is_missing_for_every_count(self):
        for ok in range(0, 97):
            for docs in (0, 1):
                rec = md.build([row("2015-03-02", ok, docs), row("2015-03-03", 96, 5),
                                row("2015-03-04", 96, 5)], BLOCK3)
                self.assertEqual(rec["missing_count"] == 1, candidates.day_is_missing(ok, docs),
                                 (ok, docs))

    def test_stops_on_bad_input(self):
        good = [row("2015-03-02", 96, 1), row("2015-03-03", 96, 1), row("2015-03-04", 96, 1)]
        cases = {
            "day の行が無い日": good[:2],
            "区画の外": good + [row("2015-03-05", 96, 1)],
            "二つある": good + [row("2015-03-04", 96, 1)],
            "run_id が1つでない": good[:2] + [row("2015-03-04", 96, 1, run_id="r2")],
            "files_ok が files_listed より多い": good[:2] + [row("2015-03-04", 90, 1, files_listed=80)],
            "1日のファイルの数": good[:2] + [row("2015-03-04", 97, 1, files_listed=97)],
            "0以上の整数でない": good[:2] + [row("2015-03-04", 96, -1)],
        }
        for msg, rows in cases.items():
            with self.assertRaisesRegex(md.MissingDaysError, msg):
                md.build(rows, BLOCK3)
        bad = copy.deepcopy(good)
        bad[0]["mode"] = "trial"
        with self.assertRaisesRegex(md.MissingDaysError, "official"):
            md.build(bad, BLOCK3)
        bad = copy.deepcopy(good)
        bad[0]["docs"] = True
        with self.assertRaises(md.MissingDaysError):
            md.build(bad, BLOCK3)

    def test_canonical_json_and_sha256(self):
        rows = [row("2015-03-04", 96, 1), row("2015-03-02", 10, 1), row("2015-03-03", 96, 0)]
        a = md.build(rows, BLOCK3)
        b = md.build(list(reversed(rows)), BLOCK3)
        self.assertEqual(md.canonical_bytes(a), md.canonical_bytes(b))
        self.assertEqual(md.sha256_of(a), hashlib.sha256(md.canonical_bytes(a)).hexdigest())
        text = md.canonical_bytes(a).decode("utf-8")
        self.assertEqual(text, json.dumps(json.loads(text), ensure_ascii=False, sort_keys=True,
                                          indent=2) + "\n")
        self.assertEqual([m["day"] for m in a["missing_days"]], ["2015-03-02", "2015-03-03"])

    def test_method_block_matches_periods_and_gkg(self):
        self.assertEqual(md.method_block(), (D(2015, 3, 2), D(2020, 12, 14)))


class TestSourceShape(unittest.TestCase):
    """コードの形：入口は official_day_records だけ。日の集計やマニフェストを直に読まない。"""

    def test_only_entry_is_official_day_records(self):
        with open(SCRIPT, encoding="utf-8") as f:
            src = f.read()
        self.assertIn("_gkg().official_day_records()", src)
        for bad in ("_day_records_of", "read_jsonl", "read_bytes_nofollow", "gzip", "STORE",
                    "LACIE", "urllib", "socket", "datetime.now", "datetime.datetime.now"):
            self.assertNotIn(bad, src, bad)
        self.assertEqual(list(inspect.signature(md.main).parameters), ["argv"])

    def test_main_rejects_unknown_args(self):
        self.assertEqual(md.main(["--x"]), 2)


def _load_e2e():
    if COLLECTOR_TESTS not in sys.path:
        sys.path.insert(0, COLLECTOR_TESTS)
    import test_acquire_gkg  # noqa: E402
    return test_acquire_gkg


tag = _load_e2e()
taf, tg, ledger = tag.taf, tag.tg, tag.ledger


class TestGateEndToEnd(tag.E2ECase):
    """合成の正式な run（3日：72本・71本・3本）を写しの中で作り、関門を通して一覧を作る。"""

    COUNTS = {"20150302": 72, "20150303": 71, "20150304": 3}

    def setUp(self):
        # E2ECase.setUp と同じ手順で、日ごとの15分ファイルの本数だけを変える
        taf.CopyCase.setUp(self)
        self.fs_check = lambda v: None
        self.gdrand = taf.FakeDrand(tg.NOW)
        self.gots = taf.FakeOts()
        self.zips = {}
        for d in self.DAYS:
            for i in range(self.COUNTS[d]):
                ts = tg.ts_of(d, i)
                self.zips[ts] = tg.make_zip(ts, tg.standard_rows(ts))
        lines = ["%d %s http://data.gdeltproject.org/gdeltv2/%s.gkg.csv.zip"
                 % (len(z), hashlib.md5(z).hexdigest(), ts) for ts, z in sorted(self.zips.items())]
        body = ("\n".join(lines) + "\n").encode()
        self.transport = tag.tf.FakeTransport(tag.tf.FakeResponse(body))
        taf.acq._acquire(_test=self.seams())
        self.order1_seq = tag.add_order_record(self.project, ledger.ORDER1_KIND, taf.NOW)
        self.order1b_seq = tag.add_order_record(self.project, ledger.ORDER1B_KIND, taf.NOW)
        self.volume = self.make_volume()
        self.gkg_store = os.path.join(self.volume, *tag.gkg.STORE_PARTS)
        os.makedirs(self.gkg_store)
        self.trial_store = os.path.join(self.volume, *tag.gkg.TRIAL_STORE_PARTS)
        os.makedirs(self.trial_store)
        self.check_volume = tag.fake_check_volume
        self.gkg_logs = []
        self.clock = tg.FakeClock()

    def full_official(self):
        self.add_method_access()
        out = self.acquire_official(self.gseams())
        self.commit_manifest("正式な run の結果")
        return out

    def seal_result(self, run_id):
        tag.seal_gkg_result.seal(self.project, "official", run_id, tg.NOW, "ots",
                                 runner=taf.FakeOts())
        taf.git(self.project, "add", "-A", "sealed")
        taf.git(self.project, "commit", "-q", "-m", "gkg-run-result")

    def entry(self):
        return self.run_with_root(md.official_record, BLOCK3)

    def test_stops_without_gate_then_passes(self):
        out = self.full_official()
        g = md._gkg()
        calls = []
        real_gate = ledger.require_gkg_run_result

        def gate(mode, run_id):
            calls.append((mode, run_id))
            return real_gate(mode, run_id)
        never = mock.Mock(side_effect=AssertionError("関門より前にマニフェストを読んではいけない"))
        with mock.patch.object(ledger, "require_gkg_run_result", gate), \
                mock.patch.object(g, "read_bytes_nofollow", never):
            with self.assertRaises(g.GkgError) as cm:
                self.entry()
            self.assertEqual(self.run_with_root(md.main, ["--sha256"]), 1)
        never.assert_not_called()
        self.assertRegex(str(cm.exception), "gkg-run-result の関門を通らない")
        self.assertIsInstance(cm.exception.__cause__, ledger.GkgRunResultRequired)
        self.assertEqual(calls[0], ("official", out["run_id"]))

        self.seal_result(out["run_id"])
        with mock.patch.object(ledger, "require_gkg_run_result", gate), OpenRecorder() as rec:
            got = self.entry()
        self.assertEqual(calls[-1], ("official", out["run_id"]))
        # 日の集計（保存先）も、取得の記録も開かない
        for p in rec.paths:
            self.assertFalse(os.path.abspath(p).startswith(self.volume), p)
            self.assertFalse(os.path.abspath(p).startswith(self.home), p)
            self.assertFalse(p.endswith(".tsv.gz"), p)
        self.assertTrue(any(p.endswith(tag.gkg.MANIFEST_NAME) for p in rec.paths))
        self.assertEqual(got["input"]["run_id"], out["run_id"])
        self.assertEqual(got["days_in_block"], 3)
        self.assertEqual([(m["day"], m["files_ok"], m["below_min_files"])
                          for m in got["missing_days"]],
                         [("2015-03-03", 71, True), ("2015-03-04", 3, True)])
        self.assertEqual(got["partial_days_count"], 1)
        for m in got["missing_days"]:
            self.assertGreater(m["docs"], 0)


class TestRealManifestNoAggregates(unittest.TestCase):
    """本物のマニフェスト（seq 12）で動かし、日の集計を開かないことと、出力が毎回同じことを確かめる。
    件数や日付はここでは固定しない（規則を結果に合わせて動かさないため）。"""

    def test_real(self):
        if not os.path.exists(os.path.join(PROJECT, "data", "manifest", "gdelt-gkg-method.jsonl")):
            self.skipTest("マニフェストが無い")
        with OpenRecorder() as rec:
            a = md.official_record()
        for p in rec.paths:
            ap = os.path.abspath(p)
            self.assertTrue(ap.startswith(PROJECT + os.sep), p)
            self.assertFalse(ap.endswith(".tsv.gz"), p)
            self.assertNotIn("LACIE", ap)
        self.assertEqual(a["days_in_block"], 2115)
        self.assertEqual(a["input"]["day_rows"], 2115)
        b = md.official_record()
        self.assertEqual(md.sha256_of(a), md.sha256_of(b))
        r = subprocess.run([sys.executable, "-B", SCRIPT, "--sha256"], cwd=PROJECT,
                           capture_output=True, check=True,
                           env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
        self.assertEqual(r.stdout.decode().strip(), md.sha256_of(a))


if __name__ == "__main__":
    unittest.main()
