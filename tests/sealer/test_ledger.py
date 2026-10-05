"""封印の記録（src/sealer/）のテスト。T-005。

実行（プロジェクトのルートで）:
    PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest discover -s tests/sealer -v

ネットワークは使わない。OpenTimestamps のクライアントは呼ばず、偽の応答で置き換える。
わざと壊した記録（書き換え・削除・入れ替え・欠番・末尾の削除）で、検証が失敗することを確かめる。
"""

import datetime
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(os.path.dirname(HERE))
SRC = os.path.join(PROJECT, "src", "sealer")
sys.path.insert(0, SRC)

import ledger  # noqa: E402
import seal_periods  # noqa: E402
import stamp  # noqa: E402

UTC = datetime.timezone.utc
T0 = datetime.datetime(2026, 10, 6, 12, 0, 0, tzinfo=UTC)
H = datetime.timedelta(hours=1)
VERIFY = os.path.join(SRC, "verify.py")
# Git の作成者として許されたアドレス（CLAUDE.md）。一時的なリポジトリのコミットに使う。
AUTHOR = ("-c", "user.name=Multi-line", "-c",
          "user.email=197505900+multi-line2025@users.noreply.github.com")


def target(path, content=b"x"):
    return {"path": path, "role": "doc", "sha256": ledger.sha256_hex(content)}


def fake_ots(prefix):
    """ots の .ots の先頭だけを真似たバイト列（対象の sha256 を含む）。"""
    return (ledger.OTS_MAGIC + bytes([ledger.OTS_VERSION, ledger.OTS_OP_SHA256])
            + bytes.fromhex(ledger.sha256_hex(prefix)) + b"\xf0\x10" + b"\x00" * 16)


class FakeRun:
    """subprocess.run の代わり。ots stamp の偽の応答を返す。"""

    def __init__(self):
        self.calls = []

    def __call__(self, cmd, input=None, capture_output=True, timeout=None):
        self.calls.append((cmd, input))
        err = "".join("Submitting to remote calendar %s\n" % c for c in stamp.CALENDARS)
        return subprocess.CompletedProcess(cmd, 0, stdout=fake_ots(input), stderr=err.encode())


class LedgerCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.path = os.path.join(self.tmp, "ledger.jsonl")

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def add(self, kind="periods", n=1, start=0):
        recs = None
        for i in range(n):
            recs = ledger.append_record(self.path, kind, [target("a/%d.md" % (start + i))],
                                        "注記 %d" % i, T0 + (start + i) * H)
        return recs

    def lines(self):
        with open(self.path, "rb") as f:
            return f.read().split(b"\n")[:-1]

    def write_lines(self, lines):
        with open(self.path, "wb") as f:
            f.write(b"".join(l + b"\n" for l in lines))

    def data(self):
        return ledger.read_ledger(self.path)


class TestChain(LedgerCase):
    def test_valid_chain(self):
        recs = self.add(n=3)
        self.assertEqual([r["seq"] for r in recs], [1, 2, 3])
        self.assertEqual(recs[0]["prev_hash"], ledger.GENESIS_PREV)
        self.assertEqual(recs[1]["prev_hash"], ledger.sha256_hex(self.lines()[0]))
        self.assertEqual(ledger.verify_chain(self.data()), recs)

    def test_record_has_only_the_six_keys(self):
        rec = self.add()[0]
        self.assertEqual(sorted(rec), sorted(ledger.RECORD_KEYS))
        self.assertNotIn("version", rec)

    def test_tamper_one_byte_detected(self):
        self.add(n=3)
        lines = self.lines()
        lines[0] = lines[0].replace("注記 0".encode(), "注記 9".encode())
        self.write_lines(lines)
        with self.assertRaisesRegex(ledger.LedgerError, "2 行目: prev_hash"):
            ledger.verify_chain(self.data())

    def test_tamper_target_hash_detected(self):
        self.add(n=2)
        lines = self.lines()
        rec = json.loads(lines[0])
        rec["targets"][0]["sha256"] = "f" * 64
        lines[0] = ledger.canonical_line(rec)
        self.write_lines(lines)
        with self.assertRaises(ledger.LedgerError):
            ledger.verify_chain(self.data())

    def test_delete_middle_line_detected(self):
        self.add(n=3)
        lines = self.lines()
        del lines[1]
        self.write_lines(lines)
        with self.assertRaisesRegex(ledger.LedgerError, "seq が 3"):
            ledger.verify_chain(self.data())

    def test_delete_first_line_detected(self):
        self.add(n=3)
        self.write_lines(self.lines()[1:])
        with self.assertRaises(ledger.LedgerError):
            ledger.verify_chain(self.data())

    def test_swap_lines_detected(self):
        self.add(n=3)
        lines = self.lines()
        lines[1], lines[2] = lines[2], lines[1]
        self.write_lines(lines)
        with self.assertRaises(ledger.LedgerError):
            ledger.verify_chain(self.data())

    def test_swap_and_renumber_detected(self):
        """入れ替えたうえで seq を振り直しても、prev_hash で見つかる。"""
        self.add(n=3)
        lines = [json.loads(l) for l in self.lines()]
        a, b = lines[1], lines[2]
        a["seq"], b["seq"] = 3, 2
        self.write_lines([ledger.canonical_line(r) for r in (lines[0], b, a)])
        with self.assertRaisesRegex(ledger.LedgerError, "prev_hash"):
            ledger.verify_chain(self.data())

    def test_non_canonical_detected(self):
        self.add(n=1)
        rec = json.loads(self.lines()[0])
        self.write_lines([json.dumps(rec, sort_keys=True).encode()])
        with self.assertRaisesRegex(ledger.LedgerError, "正規の形"):
            ledger.verify_chain(self.data())

    def test_extra_key_rejected(self):
        self.add(n=1)
        rec = json.loads(self.lines()[0])
        rec["version"] = 1
        self.write_lines([ledger.canonical_line(rec)])
        with self.assertRaisesRegex(ledger.LedgerError, "キー"):
            ledger.verify_chain(self.data())

    def test_truncated_file_detected(self):
        self.add(n=2)
        with open(self.path, "rb") as f:
            data = f.read()
        with self.assertRaisesRegex(ledger.LedgerError, "改行で終わっていない"):
            ledger.verify_chain(data[:-5])

    def test_time_going_back_refused(self):
        ledger.append_record(self.path, "periods", [target("a")], "", T0)
        with self.assertRaises(ledger.LedgerError):
            ledger.append_record(self.path, "periods", [target("b")], "", T0 - H)
        self.assertEqual(len(self.lines()), 1)

    def test_append_refuses_on_broken_chain(self):
        self.add(n=2)
        lines = self.lines()
        lines[0] = lines[0].replace(b"a/0.md", b"a/X.md")
        self.write_lines(lines)
        with self.assertRaises(ledger.LedgerError):
            self.add(n=1, start=5)
        self.assertEqual(len(self.lines()), 2)

    def test_append_keeps_existing_bytes(self):
        self.add(n=2)
        before = self.data()
        self.add(n=1, start=2)
        self.assertTrue(self.data().startswith(before))

    def test_write_once_does_not_overwrite(self):
        p = os.path.join(self.tmp, "o.json")
        self.assertTrue(ledger.write_once(p, b"a"))
        self.assertFalse(ledger.write_once(p, b"a"))
        with self.assertRaises(ledger.LedgerError):
            ledger.write_once(p, b"b")
        with open(p, "rb") as f:
            self.assertEqual(f.read(), b"a")


class TestAnchors(LedgerCase):
    def stamp(self, seq):
        stamp.stamp_seq(self.path, seq, "ots", runner=FakeRun())

    def test_anchor_matches_prefix(self):
        self.add(n=1)
        self.stamp(1)
        self.add(n=1, start=1)
        self.stamp(2)
        got = ledger.check_anchors(self.data(), self.tmp)
        self.assertEqual([s for s, _p, _d in got], [1, 2])

    def test_stamp_sends_only_prefix_to_ots(self):
        self.add(n=2)
        run = FakeRun()
        stamp.stamp_seq(self.path, 1, "ots", runner=run)
        self.assertEqual(run.calls[0][1], ledger.prefix_bytes(self.data(), 1))
        for c in stamp.CALENDARS:
            self.assertIn(c, run.calls[0][0])

    def test_stamp_does_not_overwrite(self):
        self.add(n=1)
        self.stamp(1)
        with self.assertRaises(ledger.LedgerError):
            self.stamp(1)

    def test_last_line_tamper_detected_by_anchor(self):
        self.add(n=2)
        self.stamp(2)
        lines = self.lines()
        lines[1] = lines[1].replace("注記 1".encode(), "注記 7".encode())
        self.write_lines(lines)
        ledger.verify_chain(self.data())  # 鎖だけでは見つからない
        with self.assertRaisesRegex(ledger.LedgerError, "一致しない"):
            ledger.check_anchors(self.data(), self.tmp)

    def test_tail_deletion_detected_by_anchor(self):
        self.add(n=2)
        self.stamp(1)
        self.stamp(2)
        self.write_lines(self.lines()[:1])
        with self.assertRaisesRegex(ledger.LedgerError, "末尾の行が削除"):
            ledger.check_anchors(self.data(), self.tmp)

    def test_missing_anchor_for_last_record(self):
        self.add(n=1)
        self.stamp(1)
        self.add(n=1, start=1)
        with self.assertRaisesRegex(ledger.LedgerError, "時刻証明が無い"):
            ledger.check_anchors(self.data(), self.tmp)

    def test_bad_ots_header(self):
        with self.assertRaises(ledger.LedgerError):
            ledger.ots_file_digest(b"not an ots file" * 5)


class TestVersions(LedgerCase):
    def test_version_from_count(self):
        ledger.append_record(self.path, "periods", [target("p")], "", T0)
        ledger.append_record(self.path, "other", [target("o")], "", T0 + H)
        recs = ledger.append_record(self.path, "periods", [target("p")], "", T0 + 2 * H)
        self.assertEqual(ledger.version_of(recs, 1), 1)
        self.assertEqual(ledger.version_of(recs, 2), 1)
        self.assertEqual(ledger.version_of(recs, 3), 2)
        self.assertEqual([v for v, _r in ledger.records_of_kind(recs, "periods")], [1, 2])

    def test_version_unknown_seq(self):
        recs = self.add(n=1)
        with self.assertRaises(ledger.LedgerError):
            ledger.version_of(recs, 5)


class TestAdoption(LedgerCase):
    def setUp(self):
        super().setUp()
        ledger.append_record(self.path, "periods", [target("p1")], "", T0)
        ledger.append_record(self.path, "other", [target("o")], "", T0 + H)
        ledger.append_record(self.path, "periods", [target("p2")], "", T0 + 2 * H)
        self.recs = ledger.append_record(self.path, "periods", [target("p3")], "", T0 + 30 * H)
        self.deadline = T0 + 24 * H

    def test_last_before_deadline_is_adopted(self):
        anchors = {1: T0 + H, 3: T0 + 3 * H, 4: T0 + 31 * H}
        r = ledger.adopted_record(self.recs, "periods", self.deadline, anchors)
        self.assertEqual(r["seq"], 3)
        self.assertEqual(ledger.version_of(self.recs, r["seq"]), 2)

    def test_recorded_at_is_not_used(self):
        """recorded_at は期限前でも、時刻証明が期限後なら採用しない。"""
        anchors = {1: T0 + H, 4: T0 + 31 * H}
        r = ledger.adopted_record(self.recs, "periods", self.deadline, anchors)
        self.assertEqual(r["seq"], 1)

    def test_later_anchor_covers_earlier_records(self):
        anchors = {4: T0 + 5 * H}
        r = ledger.adopted_record(self.recs, "periods", self.deadline, anchors)
        self.assertEqual(r["seq"], 4)
        self.assertEqual(ledger.proven_time_of(1, anchors), T0 + 5 * H)

    def test_margin_applied(self):
        anchors = {1: self.deadline - 2 * H}
        self.assertIsNone(ledger.adopted_record(self.recs, "periods", self.deadline, anchors))
        r = ledger.adopted_record(self.recs, "periods", self.deadline, anchors,
                                  margin=datetime.timedelta(hours=1))
        self.assertEqual(r["seq"], 1)

    def test_no_proof_no_adoption(self):
        self.assertIsNone(ledger.adopted_record(self.recs, "periods", self.deadline, {}))

    def test_naive_deadline_refused(self):
        with self.assertRaises(ValueError):
            ledger.adopted_record(self.recs, "periods", self.deadline.replace(tzinfo=None), {})


def periods_out(blocks, status=None, triggers=None):
    return {
        "deadline_status": status,
        "rebuild_triggers": triggers or {"last_read_offset_days": None},
        "periods": [{"name": n, "block_start": s, "block_end": e} for n, s, e in blocks],
    }


V1 = [("method", "2015-03-02", "2020-12-14"), ("threshold", "2020-12-15", "2023-11-06"),
      ("baseline", "2023-11-07", "2026-09-30")]


class TestBlocks(unittest.TestCase):
    def test_same_blocks_ok(self):
        later = periods_out(V1, "before_deadline", {"last_read_offset_days": 120})
        self.assertEqual(ledger.check_blocks(periods_out(V1), later), [])

    def test_moved_boundary_detected(self):
        moved = [V1[0], ("threshold", "2020-12-16", "2023-11-06"), V1[2]]
        self.assertEqual(len(ledger.check_blocks(periods_out(V1), periods_out(moved))), 1)

    def test_missing_period_detected(self):
        self.assertTrue(ledger.check_blocks(periods_out(V1), periods_out(V1[:2])))

    def test_deadline_status_checks(self):
        self.assertEqual(ledger.check_deadline_status(periods_out(V1), None), [])
        trig = {"last_read_offset_days": 120}
        self.assertEqual(ledger.check_deadline_status(
            periods_out(V1, "before_deadline", trig), True), [])
        self.assertTrue(ledger.check_deadline_status(
            periods_out(V1, "before_deadline", trig), False))
        self.assertTrue(ledger.check_deadline_status(periods_out(V1, None, trig), None))
        self.assertTrue(ledger.check_deadline_status(periods_out(V1, "before_deadline"), None))


FAKE_PERIODS = """import json, sys
blocks = %r
if "--move" in sys.argv:
    blocks[1] = ["threshold", "2020-12-20", "2023-11-06"]
print(json.dumps({"deadline_status": None, "rebuild_triggers": {},
    "periods": [{"name": n, "block_start": s, "block_end": e} for n, s, e in blocks]}))
""" % ([list(b) for b in V1],)


class TestSealPeriods(unittest.TestCase):
    """仮のプロジェクトで seal_periods.seal を動かす（本物の sealed/ には書かない）。"""

    def setUp(self):
        self.root = tempfile.mkdtemp()
        for rel, _role in seal_periods.SOURCES:
            os.makedirs(os.path.join(self.root, os.path.dirname(rel)), exist_ok=True)
            with open(os.path.join(self.root, rel), "w") as f:
                f.write(FAKE_PERIODS if rel.endswith("periods.py") else "# %s\n" % rel)
        for d in seal_periods.DATA_DIRS + ("sealed",):
            os.makedirs(os.path.join(self.root, d), exist_ok=True)
            open(os.path.join(self.root, d, ".gitkeep"), "w").close()
        self.out_sha = ledger.sha256_hex(seal_periods.run_periods(self.root, []))
        self.ledger = os.path.join(self.root, "sealed", "ledger.jsonl")

    def tearDown(self):
        shutil.rmtree(self.root)

    def seal(self, args=(), sha=None, now=T0):
        rec, _p, _s = seal_periods.seal(self.root, sha or self.out_sha, list(args), now, None)
        stamp.stamp_seq(self.ledger, rec["seq"], "ots", runner=FakeRun())
        return rec

    def test_seal_writes_record_output_and_anchor(self):
        rec = self.seal()
        self.assertEqual(rec["kind"], "periods")
        self.assertEqual(sorted(t["role"] for t in rec["targets"]),
                         ["code", "doc", "output", "test"])
        out = os.path.join(self.root, "sealed", "periods-output-%s.json" % self.out_sha)
        self.assertEqual(ledger.sha256_file(out), self.out_sha)
        data = ledger.read_ledger(self.ledger)
        self.assertEqual(len(ledger.check_anchors(data, os.path.join(self.root, "sealed"))), 1)
        r = subprocess.run([sys.executable, "-B", VERIFY, "--root", self.root, "all"],
                           capture_output=True)
        self.assertEqual(r.returncode, 0, r.stderr.decode())

    def test_wrong_expected_hash_writes_nothing(self):
        with self.assertRaises(ledger.LedgerError):
            self.seal(sha="0" * 64)
        self.assertFalse(os.path.exists(self.ledger))
        self.assertEqual(sorted(os.listdir(os.path.join(self.root, "sealed"))), [".gitkeep"])

    def test_first_version_refused_after_data_arrived(self):
        with open(os.path.join(self.root, "data", "manifest", "list.json"), "w") as f:
            f.write("{}")
        with self.assertRaisesRegex(ledger.LedgerError, "データの取得が始まっている"):
            self.seal()
        self.assertFalse(os.path.exists(self.ledger))

    def test_first_version_refused_when_raw_exists(self):
        os.makedirs(os.path.join(self.root, "data", "raw"))
        with self.assertRaises(ledger.LedgerError):
            self.seal()

    def test_second_version_counts_and_blocks_checked(self):
        self.seal()
        rec2 = self.seal(now=T0 + H)
        recs = ledger.verify_chain(ledger.read_ledger(self.ledger))
        self.assertEqual(ledger.version_of(recs, rec2["seq"]), 2)
        moved_sha = ledger.sha256_hex(seal_periods.run_periods(self.root, ["--move"]))
        with self.assertRaisesRegex(ledger.LedgerError, "区画の境目"):
            self.seal(args=["--move"], sha=moved_sha, now=T0 + 2 * H)
        self.assertEqual(len(ledger.verify_chain(ledger.read_ledger(self.ledger))), 2)

    def test_verify_detects_moved_blocks_in_later_record(self):
        """仕組みを通さずに区画の違う版を追記しても、verify periods が見つける。"""
        self.seal()
        moved = seal_periods.run_periods(self.root, ["--move"])
        sha = ledger.sha256_hex(moved)
        rel = "sealed/periods-output-%s.json" % sha
        ledger.write_once(os.path.join(self.root, rel), moved)
        ledger.append_record(self.ledger, "periods",
                             [{"path": rel, "role": "output", "sha256": sha}], "", T0 + H)
        stamp.stamp_seq(self.ledger, 2, "ots", runner=FakeRun())
        r = subprocess.run([sys.executable, "-B", VERIFY, "--root", self.root, "periods"],
                           capture_output=True)
        self.assertEqual(r.returncode, 1)

    def test_verify_targets_detects_changed_file(self):
        self.seal()
        with open(os.path.join(self.root, "docs", "stats", "periods.md"), "a") as f:
            f.write("後から足した行\n")
        r = subprocess.run([sys.executable, "-B", VERIFY, "--root", self.root, "targets"],
                           capture_output=True)
        self.assertEqual(r.returncode, 1)

    def test_rev_auto_uses_commit_of_record(self):
        """対象を後で書き換えても、--rev auto は封印した時点のコミットで照合する。"""
        self.seal()

        def git(*a):
            subprocess.run(["git", "-C", self.root] + list(AUTHOR) + list(a),
                           check=True, capture_output=True)
        git("init", "-q")
        git("add", "-A")
        git("commit", "-q", "-m", "seal")
        with open(os.path.join(self.root, "docs", "stats", "periods.md"), "a") as f:
            f.write("後の版\n")
        git("commit", "-q", "-am", "edit")
        run = lambda *a: subprocess.run([sys.executable, "-B", VERIFY, "--root", self.root] + list(a),
                                        capture_output=True).returncode
        self.assertEqual(run("targets"), 1)
        self.assertEqual(run("all", "--rev", "auto"), 0)
        # 履歴の中の記録を書き換えたコミットがあれば、--rev auto は失敗する。
        with open(self.ledger, "rb") as f:
            data = f.read()
        with open(self.ledger, "wb") as f:
            f.write(data.replace("periods の 1 件目".encode(), "periods の 9 件目".encode()))
        git("commit", "-q", "-am", "tamper")
        self.assertEqual(run("targets", "--rev", "auto"), 1)


if __name__ == "__main__":
    unittest.main()
