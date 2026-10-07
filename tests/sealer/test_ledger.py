"""封印の記録（src/sealer/）のテスト。T-005、T-007、T-008、T-014。

実行（プロジェクトのルートで）:
    PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest discover -s tests/sealer -v

ネットワークは使わない。OpenTimestamps のクライアントは呼ばず、偽の応答で置き換える。
Bitcoin の証明は、テストの中で作った .ots と、易しい目標値で掘ったヘッダで試す。
わざと壊した記録（書き換え・削除・入れ替え・欠番・末尾の削除・途中の .ots の欠け・
許可していないカレンダーの Pending・ledger_head の食い違い・drand の回と確定時刻の食い違い）で、
検証が失敗することを確かめる。
T-007：採用は鎖の順番で決まり、.ots を Pending のままにする・upgrade を出さない・drand の回を
動かす、のどれでも採用が変わらないことを確かめる（監査 R-1・R-2 の再現）。
T-008：区切りは最初の threshold-access の記録。acquisition-start の後・threshold-access の前に
追記したきっかけの値は採用され、threshold-access の後のものは採用されない。acquisition-start と
acquisition-result の対応、drand の照合の幅（幅の中は通り、外は失敗）、許可リストに無い kind を
拒むことを確かめる。
T-014：acquisition-start の前に candidates が要ること（SealCase.add_cand で足す）、kind の許可リストが
method-access を含む 7 つであること。
"""

import contextlib
import datetime
import functools
import hashlib
import inspect
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(os.path.dirname(HERE))
SRC = os.path.join(PROJECT, "src", "sealer")
sys.path.insert(0, SRC)

import ledger  # noqa: E402
import otsfile  # noqa: E402
import seal_periods  # noqa: E402
import seal_triggers  # noqa: E402
import stamp  # noqa: E402
import verify  # noqa: E402

UTC = datetime.timezone.utc
T0 = datetime.datetime(2026, 10, 6, 12, 0, 0, tzinfo=UTC)
H = datetime.timedelta(hours=1)
VERIFY = os.path.join(SRC, "verify.py")
# Git の作成者として許されたアドレス（CLAUDE.md）。一時的なリポジトリのコミットに使う。
AUTHOR = ("-c", "user.name=Multi-line", "-c",
          "user.email=197505900+multi-line2025@users.noreply.github.com")
QUICKNET = "52db9ba70e0cc0f6eaf7803dd07447a1f5477735fd3f661792ba94600c84e971"


# ---------------------------------------------------------------- .ots とヘッダを作る道具


def varuint(n):
    out = bytearray()
    while True:
        b = n & 0x7f
        n >>= 7
        if n:
            out.append(b | 0x80)
        else:
            out.append(b)
            return bytes(out)


def varbytes(b):
    return varuint(len(b)) + b


NONCE = b"\x11" * 16


def tip_msg(prefix):
    """build_ots の証明が付く値（対象のハッシュ + nonce の sha256）。"""
    return hashlib.sha256(hashlib.sha256(prefix).digest() + NONCE).digest()


ALLOWED_CAL = "https://alice.btc.calendar.opentimestamps.org"
OWN_CAL = "https://my-own-calendar.example"


def build_ots(prefix, pending=(ALLOWED_CAL,), heights=()):
    atts = [b"\x00" + otsfile.TAG_PENDING + varbytes(varbytes(u.encode())) for u in pending]
    atts += [b"\x00" + otsfile.TAG_BITCOIN + varbytes(varuint(h)) for h in heights]
    tree = b"".join(b"\xff" + a for a in atts[:-1]) + atts[-1]
    return (otsfile.MAGIC + b"\x01\x08" + hashlib.sha256(prefix).digest()
            + b"\xf0" + varbytes(NONCE) + b"\x08" + tree)


def mine_header(merkle, when, bits=0x207fffff):
    t = int(when.timestamp()).to_bytes(4, "little")
    target = otsfile.target_from_bits(bits)
    for nonce in range(1 << 20):
        hdr = (b"\x01\x00\x00\x00" + b"\x00" * 32 + merkle + t
               + bits.to_bytes(4, "little") + nonce.to_bytes(4, "little"))
        h = hashlib.sha256(hashlib.sha256(hdr).digest()).digest()
        if int.from_bytes(h, "little") <= target:
            return hdr
    raise AssertionError("掘れなかった")


class FakeRun:
    """subprocess.run の代わり。ots stamp の偽の応答（Pending の .ots）を返す。"""

    def __init__(self):
        self.calls = []

    def __call__(self, cmd, input=None, capture_output=True, timeout=None):
        self.calls.append((cmd, input))
        err = "".join("Submitting to remote calendar %s\n" % c for c in stamp.CALENDARS)
        return subprocess.CompletedProcess(cmd, 0, stdout=build_ots(input), stderr=err.encode())


def target(path, content=b"x"):
    return {"path": path, "role": "doc", "sha256": ledger.sha256_hex(content)}


class LedgerCase(unittest.TestCase):
    def setUp(self):
        # 書く仕組みの共通の入口は <プロジェクト>/sealed/ の中にだけ書く（T-017）。
        # self.tmp は仮のプロジェクトの sealed/ にする。
        self.base = tempfile.mkdtemp()
        self.tmp = os.path.join(self.base, "sealed")
        os.mkdir(self.tmp)
        self.path = os.path.join(self.tmp, "ledger.jsonl")

    def tearDown(self):
        shutil.rmtree(self.base)

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

    def stamp(self, seq):
        stamp.stamp_seq(self.path, seq, "ots", runner=FakeRun())

    def stamp_bitcoin(self, seq, height, when):
        """seq 自身の .bitcoin.ots を作り、その高さのヘッダを返す。"""
        prefix = ledger.prefix_bytes(self.data(), seq)
        with open(os.path.join(self.tmp, ledger.ots_name(seq, bitcoin=True)), "xb") as f:
            f.write(build_ots(prefix, heights=(height,)))
        return mine_header(tip_msg(prefix), when)


# ---------------------------------------------------------------- 鎖


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

    def test_unknown_kind_rejected_by_verify_chain(self):
        """許可リストに無い kind は、鎖が正しくても verify_chain で失敗する（T-008）。"""
        for bad in ("acquisition", "other", "threshold_access", "periods-trigger"):
            self.tearDown()
            self.setUp()
            self.add(n=1)
            rec = {"seq": 2, "prev_hash": ledger.sha256_hex(self.lines()[0]), "kind": bad,
                   "targets": [target("b")], "recorded_at": "2026-10-06T13:00:00Z", "note": ""}
            self.write_lines(self.lines() + [ledger.canonical_line(rec)])
            with self.assertRaisesRegex(ledger.LedgerError, "2 行目: kind .*は許可リストに無い"):
                ledger.verify_chain(self.data())

    def test_unknown_kind_not_appended(self):
        self.add(n=1)
        with self.assertRaisesRegex(ledger.LedgerError, "許可リスト"):
            ledger.append_record(self.path, "acquisition", [target("b")], "", T0 + H)
        self.assertEqual(len(self.lines()), 1)

    def test_allowed_kinds_are_the_seven(self):
        self.assertEqual(set(ledger.ALLOWED_KINDS),
                         {"periods", "periods-triggers", "threshold-access",
                          "acquisition-start", "acquisition-result", "candidates",
                          "method-access"})
        self.assertNotIn("acquisition", ledger.ALLOWED_KINDS)
        self.add(n=1)
        for i, k in enumerate(ledger.ALLOWED_KINDS):
            ledger.append_record(self.path, k, [target("k/%d" % i)], "", T0 + (i + 1) * H)
        self.assertEqual(len(ledger.verify_chain(self.data())), 1 + len(ledger.ALLOWED_KINDS))

    def test_write_once_does_not_overwrite(self):
        p = os.path.join(self.tmp, "o.json")
        self.assertTrue(ledger.write_once(p, b"a"))
        self.assertFalse(ledger.write_once(p, b"a"))
        with self.assertRaises(ledger.LedgerError):
            ledger.write_once(p, b"b")
        with open(p, "rb") as f:
            self.assertEqual(f.read(), b"a")


# ---------------------------------------------------------------- .ots の読み取りとヘッダ


class TestOtsFile(unittest.TestCase):
    def test_parse_real_pending_ots(self):
        """封印済みの seq 1 の .ots（Pending）を、外部の部品なしで読める。"""
        p = os.path.join(PROJECT, "sealed", "ledger.jsonl.seq000001.ots")
        led = os.path.join(PROJECT, "sealed", "ledger.jsonl")
        if not os.path.exists(p):
            self.skipTest("封印済みの .ots が無い")
        with open(p, "rb") as f:
            digest, atts = otsfile.parse(f.read())
        self.assertEqual(digest, ledger.prefix_digest(ledger.read_ledger(led), 1))
        self.assertTrue(atts)
        self.assertTrue(all(a["type"] == "pending" for a in atts))

    def test_parse_bitcoin_attestation(self):
        digest, atts = otsfile.parse(build_ots(b"abc\n", heights=(912345,)))
        self.assertEqual(digest, ledger.sha256_hex(b"abc\n"))
        btc = [a for a in atts if a["type"] == "bitcoin"]
        self.assertEqual(btc[0]["height"], 912345)
        self.assertEqual(btc[0]["msg"], tip_msg(b"abc\n"))

    def test_trailing_garbage_rejected(self):
        with self.assertRaises(otsfile.OtsError):
            otsfile.parse(build_ots(b"x\n") + b"\x00")

    def test_truncated_rejected(self):
        with self.assertRaises(otsfile.OtsError):
            otsfile.parse(build_ots(b"x\n")[:-3])

    def test_header_checks(self):
        msg = tip_msg(b"x\n")
        hdr = mine_header(msg, T0)
        when, block = otsfile.check_header(hdr, msg, min_work_bits=1)
        self.assertEqual(when, T0)
        self.assertEqual(len(block), 64)
        # 作業量の下限（既定）より易しいヘッダは拒む。
        with self.assertRaisesRegex(otsfile.OtsError, "下限"):
            otsfile.check_header(hdr, msg)
        # 別の値に結び付いたヘッダは拒む（時刻を自由に作れない）。
        with self.assertRaisesRegex(otsfile.OtsError, "マークルルート"):
            otsfile.check_header(hdr, tip_msg(b"y\n"), min_work_bits=1)
        with self.assertRaisesRegex(otsfile.OtsError, "目標値"):
            otsfile.check_header(hdr[:72] + (0x1d00ffff).to_bytes(4, "little") + hdr[76:],
                                 msg, min_work_bits=1)


# ---------------------------------------------------------------- 時刻証明の照合


class TestAnchors(LedgerCase):
    def test_anchor_matches_prefix(self):
        self.add(n=1)
        self.stamp(1)
        self.add(n=1, start=1)
        self.stamp(2)
        got = ledger.check_anchors(self.data(), self.tmp)
        self.assertEqual([s for s, _p, _d, _a in got], [1, 2])

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
        self.stamp(1)
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
        with self.assertRaisesRegex(ledger.LedgerError, "seq 2 の記録に"):
            ledger.check_anchors(self.data(), self.tmp)

    def test_missing_middle_anchor_detected(self):
        """途中の seq の .ots が欠けていれば、検証は失敗する（S-1）。"""
        self.add(n=3)
        self.stamp(1)
        self.stamp(3)
        with self.assertRaisesRegex(ledger.LedgerError, "seq 2 の記録に"):
            ledger.check_anchors(self.data(), self.tmp)

    def test_bitcoin_ots_alone_is_not_enough(self):
        """.bitcoin.ots だけでは、その seq 自身の stamp の .ots の代わりにならない。"""
        self.add(n=1)
        self.stamp_bitcoin(1, 100, T0)
        with self.assertRaises(ledger.LedgerError):
            ledger.check_anchors(self.data(), self.tmp)

    def test_bad_ots_header(self):
        with self.assertRaises(ledger.LedgerError):
            ledger.ots_file_digest(b"not an ots file" * 5)


# ---------------------------------------------------------------- 版と採用


class TestVersions(LedgerCase):
    def test_version_from_count(self):
        ledger.append_record(self.path, "periods", [target("p")], "", T0)
        ledger.append_record(self.path, "periods-triggers", [target("o")], "", T0 + H)
        recs = ledger.append_record(self.path, "periods", [target("p")], "", T0 + 2 * H)
        self.assertEqual(ledger.version_of(recs, 1), 1)
        self.assertEqual(ledger.version_of(recs, 2), 1)
        self.assertEqual(ledger.version_of(recs, 3), 2)
        self.assertEqual([v for v, _r in ledger.records_of_kind(recs, "periods")], [1, 2])

    def test_version_unknown_seq(self):
        recs = self.add(n=1)
        with self.assertRaises(ledger.LedgerError):
            ledger.version_of(recs, 5)


class TestConfirmedTimes(LedgerCase):
    def setUp(self):
        super().setUp()
        self.recs = self.add(n=3)
        for s in (1, 2, 3):
            self.stamp(s)

    def test_header_for_unknown_height_reported(self):
        anchors = ledger.check_anchors(self.data(), self.tmp)
        _t, _d, unused = ledger.confirmed_times(anchors, {999: b"\x00" * 80})
        self.assertEqual(unused, [999])

    def test_header_not_matching_fails(self):
        prefix = ledger.prefix_bytes(self.data(), 1)
        with open(os.path.join(self.tmp, ledger.ots_name(1, bitcoin=True)), "xb") as f:
            f.write(build_ots(prefix, heights=(100,)))
        anchors = ledger.check_anchors(self.data(), self.tmp)
        wrong = mine_header(tip_msg(b"other\n"), T0)
        with self.assertRaises(ledger.LedgerError):
            ledger.confirmed_times(anchors, {100: wrong}, min_work_bits=1)

    def test_own_seq_time_only(self):
        """seq 2 の確定時刻を、後の seq 3 の時刻で代わりにしない（表示の時刻の取り方）。"""
        headers = {101: self.stamp_bitcoin(1, 101, T0 + H), 103: self.stamp_bitcoin(3, 103, T0 + 2 * H)}
        anchors = ledger.check_anchors(self.data(), self.tmp)
        times, _d, _u = ledger.confirmed_times(anchors, headers, min_work_bits=1)
        self.assertEqual(sorted(times), [1, 3])


class TestCalendars(LedgerCase):
    def test_stamp_uses_the_four_calendars(self):
        self.assertEqual(stamp.CALENDARS, tuple(c for c, _u in ledger.STAMP_CALENDARS))
        self.assertEqual(len(ledger.ALLOWED_PENDING_URIS), 4)

    def test_real_seq1_pending_uris_are_allowed(self):
        p = os.path.join(PROJECT, "sealed", "ledger.jsonl.seq000001.ots")
        if not os.path.exists(p):
            self.skipTest("封印済みの .ots が無い")
        with open(p, "rb") as f:
            _d, atts = otsfile.parse(f.read())
        self.assertEqual({a["uri"] for a in atts if a["type"] == "pending"},
                         set(ledger.ALLOWED_PENDING_URIS))

    def test_own_calendar_pending_rejected(self):
        self.add(n=2)
        self.stamp(1)
        with open(os.path.join(self.tmp, ledger.ots_name(2)), "xb") as f:
            f.write(build_ots(ledger.prefix_bytes(self.data(), 2), pending=(OWN_CAL,)))
        with self.assertRaisesRegex(ledger.LedgerError, "許可していないカレンダー"):
            ledger.check_anchors(self.data(), self.tmp)

    def test_mixed_allowed_and_own_rejected(self):
        self.add(n=1)
        with open(os.path.join(self.tmp, ledger.ots_name(1)), "xb") as f:
            f.write(build_ots(ledger.prefix_bytes(self.data(), 1), pending=(ALLOWED_CAL, OWN_CAL)))
        with self.assertRaisesRegex(ledger.LedgerError, OWN_CAL):
            ledger.check_anchors(self.data(), self.tmp)

    def test_pool_submit_url_is_not_a_pending_uri(self):
        """stamp で送る先（集約先）の URL が Pending の宛先として出ることはない。許可しない。"""
        self.add(n=1)
        with open(os.path.join(self.tmp, ledger.ots_name(1)), "xb") as f:
            f.write(build_ots(ledger.prefix_bytes(self.data(), 1),
                              pending=("https://a.pool.opentimestamps.org",)))
        with self.assertRaises(ledger.LedgerError):
            ledger.check_anchors(self.data(), self.tmp)

    def test_extra_dir_checked_the_same_way(self):
        self.add(n=1)
        self.stamp(1)
        ext = os.path.join(self.tmp, "ext")
        os.mkdir(ext)
        with open(os.path.join(ext, ledger.ots_name(1)), "xb") as f:
            f.write(build_ots(ledger.prefix_bytes(self.data(), 1), pending=(OWN_CAL,)))
        with self.assertRaisesRegex(ledger.LedgerError, "許可していないカレンダー"):
            ledger.check_anchors(self.data(), self.tmp, [ext])

    def test_extra_dir_does_not_replace_required_ots(self):
        """外のディレクトリの .ots は、sealed/ の必須の .ots の代わりにならない。"""
        self.add(n=2)
        self.stamp(1)
        ext = os.path.join(self.tmp, "ext")
        os.mkdir(ext)
        with open(os.path.join(ext, ledger.ots_name(2)), "xb") as f:
            f.write(build_ots(ledger.prefix_bytes(self.data(), 2)))
        with self.assertRaisesRegex(ledger.LedgerError, "seq 2 の記録に"):
            ledger.check_anchors(self.data(), self.tmp, [ext])

    def test_extra_dir_wrong_target_rejected(self):
        self.add(n=2)
        self.stamp(1)
        self.stamp(2)
        ext = os.path.join(self.tmp, "ext")
        os.mkdir(ext)
        with open(os.path.join(ext, ledger.ots_name(2)), "xb") as f:
            f.write(build_ots(ledger.prefix_bytes(self.data(), 1)))
        with self.assertRaisesRegex(ledger.LedgerError, "一致しない"):
            ledger.check_anchors(self.data(), self.tmp, [ext])

    def test_missing_extra_dir_rejected(self):
        self.add(n=1)
        self.stamp(1)
        with self.assertRaises(ledger.LedgerError):
            ledger.check_anchors(self.data(), self.tmp, [os.path.join(self.tmp, "none")])


class TestAdoption(LedgerCase):
    """採用は鎖の順番だけで決まる（T-007）。区切りは最初の threshold-access（T-008）。"""

    def build(self, kinds):
        recs = None
        for i, k in enumerate(kinds):
            recs = ledger.append_record(self.path, k, [target("a/%d" % i)], "", T0 + i * H)
        return recs

    def test_signature_has_no_time_inputs(self):
        self.assertEqual(list(inspect.signature(ledger.adoption).parameters), ["records", "kind"])

    def test_held_without_threshold_access(self):
        recs = self.build(["periods", "periods", "periods-triggers"])
        rec, cand, cut = ledger.adoption(recs, "periods")
        self.assertIsNone(rec)
        self.assertIsNone(cut)
        self.assertEqual(cand["seq"], 2)
        rec, cand, _c = ledger.adoption(recs, "periods-triggers")
        self.assertIsNone(rec)
        self.assertEqual(cand["seq"], 3)

    def test_acquisition_records_do_not_cut(self):
        """acquisition-start・acquisition-result があっても、threshold-access が無ければ保留。"""
        recs = self.build(["periods", "acquisition-start", "acquisition-result",
                           "periods-triggers"])
        rec, cand, cut = ledger.adoption(recs, "periods-triggers")
        self.assertEqual((rec, cut, cand["seq"]), (None, None, 4))

    def test_last_before_first_threshold_access(self):
        recs = self.build(["periods", "periods", "periods-triggers", "threshold-access",
                           "periods", "periods-triggers", "threshold-access", "periods"])
        rec, cand, cut = ledger.adoption(recs, "periods")
        self.assertEqual((rec["seq"], cand, cut["seq"]), (2, None, 4))
        rec, _c, _a = ledger.adoption(recs, "periods-triggers")
        self.assertEqual(rec["seq"], 3)

    def test_triggers_after_step3_before_access_adopted(self):
        """手順3（acquisition-start・result）の後、threshold-access の前の triggers は採用される。"""
        recs = self.build(["periods", "periods-triggers", "acquisition-start",
                           "acquisition-result", "periods-triggers", "periods",
                           "threshold-access", "periods-triggers", "periods"])
        self.assertEqual(ledger.adoption(recs, "periods-triggers")[0]["seq"], 5)
        self.assertEqual(ledger.adoption(recs, "periods")[0]["seq"], 6)

    def test_nothing_before_threshold_access(self):
        recs = self.build(["periods", "threshold-access", "periods-triggers"])
        rec, cand, cut = ledger.adoption(recs, "periods-triggers")
        self.assertIsNone(rec)
        self.assertIsNone(cand)
        self.assertEqual(cut["seq"], 2)

    def test_recorded_at_is_not_used(self):
        """recorded_at を変えても（鎖を作り直しても）採用は順番どおり。"""
        recs = self.build(["periods", "periods", "threshold-access"])
        shifted = [dict(r, recorded_at="2030-01-01T00:00:00Z") if r["seq"] == 1 else r
                   for r in recs]
        self.assertEqual(ledger.adoption(shifted, "periods")[0]["seq"], 2)


# ---------------------------------------------------------------- drand を持つ記録


def drand_doc(kind="threshold-access", round_no=1000, chain=QUICKNET, signature="ab" * 48,
              head=None):
    """threshold-access・acquisition-start・method-access の中身（docs/verify/periods-seal.md
    7章・10章の形）。"""
    doc = {"kind": kind,
           "drand": {"chain_hash": chain, "round": round_no, "signature": signature,
                     "randomness": ledger.sha256_hex(bytes.fromhex(signature))}}
    if kind == "threshold-access":
        doc["block_start"] = "2020-12-15"
    elif kind == "method-access":
        doc["step"] = 4
        doc["block_start"], doc["block_end"] = "2015-03-02", "2020-12-14"
    else:
        doc["step"] = 3
        doc["fetch"] = {"code_path": "src/collector/fetch_list.py", "code_sha256": "c" * 64}
    if head is not None:
        doc["ledger_head"] = head
    return doc


class TestDrand(unittest.TestCase):
    def test_round_time(self):
        d = ledger.drand_time_of(drand_doc(round_no=1))
        self.assertEqual(int(d.timestamp()), 1692803367)
        d = ledger.drand_time_of(drand_doc(round_no=101))
        self.assertEqual(int(d.timestamp()), 1692803367 + 300)

    def test_bad_randomness(self):
        doc = drand_doc()
        doc["drand"]["randomness"] = "00" * 32
        with self.assertRaisesRegex(ledger.LedgerError, "randomness"):
            ledger.drand_time_of(doc)

    def test_unknown_chain_and_missing_fields(self):
        with self.assertRaises(ledger.LedgerError):
            ledger.drand_time_of(drand_doc(chain="00" * 32))
        with self.assertRaises(ledger.LedgerError):
            ledger.drand_time_of({"kind": "threshold-access"})
        with self.assertRaises(ledger.LedgerError):
            ledger.drand_time_of(drand_doc(round_no=0))

    def test_slack_value(self):
        self.assertEqual(ledger.DRAND_HEADER_SLACK, datetime.timedelta(hours=2))


class TestCheckDrandRecord(LedgerCase):
    """threshold-access と acquisition-start の照合（ledger_head と drand の回）。"""

    KIND = "threshold-access"

    def setUp(self):
        super().setUp()
        ledger.append_record(self.path, "periods", [target("p")], "", T0)
        ledger.append_record(self.path, "periods-triggers", [target("t")], "", T0 + H)
        self.recs = ledger.append_record(self.path, self.KIND, [target("a")], "", T0 + 2 * H)
        self.rec = self.recs[-1]
        self.head = {"seq": 2, "sha256": ledger.prefix_digest(self.data(), 2)}
        self.t3 = ledger.drand_round_time(QUICKNET, 1000)

    def check(self, head, own, **kw):
        doc = drand_doc(self.KIND, 1000, head=head)
        doc.update(kw)
        return ledger.check_drand_record(self.data(), self.rec, doc, own)

    def test_ok_and_pending(self):
        self.assertEqual(self.check(self.head, self.t3 + H), (self.t3, "ok"))
        self.assertEqual(self.check(self.head, None), (self.t3, "pending"))

    def test_ledger_head_mismatch_fails(self):
        for bad in ({"seq": 1, "sha256": ledger.prefix_digest(self.data(), 1)},
                    {"seq": 2, "sha256": "0" * 64},
                    {"seq": 3, "sha256": ledger.prefix_digest(self.data(), 3)}):
            with self.assertRaisesRegex(ledger.LedgerError, "ledger_head"):
                self.check(bad, None)
        with self.assertRaisesRegex(ledger.LedgerError, "ledger_head"):
            self.check(None, None)

    def test_within_slack_passes(self):
        """ヘッダの時刻が drand の回の公開時刻より前でも、幅（2 時間）の中なら通る。"""
        for lag in (datetime.timedelta(0), H, 2 * H - datetime.timedelta(seconds=1)):
            self.assertEqual(self.check(self.head, self.t3 - lag), (self.t3, "ok"), lag)

    def test_beyond_slack_fails(self):
        """幅を超えて drand の回の公開時刻が後なら失敗する（境目の 2 時間ちょうども失敗）。"""
        for lag in (2 * H, 2 * H + datetime.timedelta(seconds=1), 3 * H, 48 * H):
            with self.assertRaisesRegex(ledger.LedgerError, "より前でない"):
                self.check(self.head, self.t3 - lag)

    def test_doc_kind_must_match_record(self):
        with self.assertRaisesRegex(ledger.LedgerError, "中身の kind"):
            other = [k for k in ledger.DRAND_RECORD_KINDS if k != self.KIND][0]
            self.check(self.head, None, kind=other)

    def test_non_drand_kind_rejected(self):
        rec = dict(self.rec, kind="periods")
        with self.assertRaises(ledger.LedgerError):
            ledger.check_drand_record(self.data(), rec, drand_doc(head=self.head), None)


class TestCheckDrandStart(TestCheckDrandRecord):
    KIND = "acquisition-start"

    def test_step_must_be_3(self):
        with self.assertRaisesRegex(ledger.LedgerError, "step"):
            self.check(self.head, None, step=4)


class TestAcquisitionPairs(LedgerCase):
    """acquisition-start と acquisition-result の対応（T-008）。"""

    def build(self, kinds):
        recs = None
        for i, k in enumerate(kinds):
            recs = ledger.append_record(self.path, k, [target("a/%d" % i)], "", T0 + i * H)
        return recs

    def test_pair_ok_and_open_start(self):
        recs = self.build(["periods", "acquisition-start", "acquisition-result",
                           "acquisition-start"])
        self.assertEqual(ledger.check_acquisition_pairs(recs, {3: 2}), {2: 3, 4: None})

    def test_start_must_exist(self):
        recs = self.build(["periods", "acquisition-start", "acquisition-result"])
        for bad in (9, 1):   # 無い seq / acquisition-start でない seq
            with self.assertRaisesRegex(ledger.LedgerError, "acquisition-start の記録ではない"):
                ledger.check_acquisition_pairs(recs, {3: bad})

    def test_result_must_come_after_start(self):
        recs = self.build(["periods", "acquisition-result", "acquisition-start"])
        with self.assertRaisesRegex(ledger.LedgerError, "より前にある"):
            ledger.check_acquisition_pairs(recs, {2: 3})

    def test_one_result_per_start(self):
        recs = self.build(["periods", "acquisition-start", "acquisition-result",
                           "acquisition-result"])
        with self.assertRaisesRegex(ledger.LedgerError, "二つ以上"):
            ledger.check_acquisition_pairs(recs, {3: 2, 4: 2})

    def test_result_fields(self):
        recs = self.build(["periods", "acquisition-start", "acquisition-result"])
        good = {"kind": "acquisition-result", "start_seq": 2, "kept_rows_sha256": "d" * 64}
        self.assertEqual(ledger.acquisition_result_fields(recs[2], good), (2, "d" * 64))
        for bad in (dict(good, start_seq="2"), dict(good, start_seq=0),
                    dict(good, kept_rows_sha256="x"), dict(good, kind="acquisition-start"),
                    {k: v for k, v in good.items() if k != "start_seq"}):
            with self.assertRaises(ledger.LedgerError):
                ledger.acquisition_result_fields(recs[2], bad)


# ---------------------------------------------------------------- 区画と deadline_status


def periods_out(blocks, status=None, triggers=None):
    trig = {k: None for k in ledger.TRIGGER_KEYS}
    trig.update(triggers or {})
    return {
        "deadline_status": status,
        "rebuild_triggers": trig,
        "periods": [{"name": n, "block_start": s, "block_end": e} for n, s, e in blocks],
    }


V1 = [("method", "2015-03-02", "2020-12-14"), ("threshold", "2020-12-15", "2023-11-06"),
      ("baseline", "2023-11-07", "2026-09-30")]
TRIG = {"last_read_offset_days": 120, "naive_history_days": None,
        "network_window_days": None, "same_week_years": None}


class TestBlocks(unittest.TestCase):
    def test_same_blocks_ok(self):
        later = periods_out(V1, "before_deadline", {"last_read_offset_days": 120})
        self.assertEqual(ledger.check_blocks(periods_out(V1), later), [])

    def test_moved_boundary_detected(self):
        moved = [V1[0], ("threshold", "2020-12-16", "2023-11-06"), V1[2]]
        self.assertEqual(len(ledger.check_blocks(periods_out(V1), periods_out(moved))), 1)

    def test_missing_period_detected(self):
        self.assertTrue(ledger.check_blocks(periods_out(V1), periods_out(V1[:2])))


class TestDeadlineStatus(unittest.TestCase):
    def judge(self, status, triggers, known, adopted):
        return ledger.judge_deadline_status(periods_out(V1, status, triggers), known, adopted)

    def test_v1_shape(self):
        self.assertEqual(self.judge(None, None, True, None), (None, []))
        self.assertEqual(self.judge(None, None, False, None), (None, []))
        self.assertTrue(self.judge("before_deadline", None, True, None)[1])

    def test_before_matches_adopted_triggers(self):
        self.assertEqual(self.judge("before_deadline", TRIG, True, TRIG),
                         ("before_deadline", []))

    def test_before_but_not_shown(self):
        """before_deadline と申告したが、期限前と示せる triggers の記録が無い。"""
        exp, probs = self.judge("before_deadline", TRIG, True, None)
        self.assertEqual(exp, "after_deadline")
        self.assertIn("before_deadline と申告", probs[0])

    def test_before_but_values_differ(self):
        other = dict(TRIG, last_read_offset_days=100)
        exp, probs = self.judge("before_deadline", TRIG, True, other)
        self.assertEqual(exp, "after_deadline")
        self.assertTrue(probs)

    def test_after_but_shown_before(self):
        """after_deadline と申告したが、期限前と示せる記録と一致する。"""
        exp, probs = self.judge("after_deadline", TRIG, True, TRIG)
        self.assertEqual(exp, "before_deadline")
        self.assertIn("after_deadline と申告", probs[0])

    def test_after_correct(self):
        self.assertEqual(self.judge("after_deadline", TRIG, True, None), ("after_deadline", []))

    def test_held_when_deadline_unknown(self):
        self.assertEqual(self.judge("before_deadline", TRIG, False, None), ("held", []))

    def test_triggers_without_status(self):
        self.assertTrue(self.judge(None, TRIG, True, TRIG)[1])

    def test_triggers_values_shape(self):
        self.assertEqual(ledger.triggers_values(dict(TRIG)), TRIG)
        with self.assertRaises(ledger.LedgerError):
            ledger.triggers_values({k: None for k in ledger.TRIGGER_KEYS})
        with self.assertRaises(ledger.LedgerError):
            ledger.triggers_values(dict(TRIG, extra=1))
        with self.assertRaises(ledger.LedgerError):
            ledger.triggers_values(dict(TRIG, last_read_offset_days=0))


# ---------------------------------------------------------------- 封印の仕組みと検証のコマンド


FAKE_PERIODS = """import json, sys
blocks = %r
trig = {"last_read_offset_days": None, "naive_history_days": None,
        "network_window_days": None, "same_week_years": None}
status = None
embargo = 90
if "--move" in sys.argv:
    blocks[1] = ["threshold", "2020-12-20", "2023-11-06"]
if "--j120" in sys.argv:
    trig["last_read_offset_days"] = 120
    embargo = 120
    status = sys.argv[-1]
if "--e120" in sys.argv:        # T-023：きっかけの無いエンバーゴの延長（照合で拒まれる形）
    embargo = 120
print(json.dumps({"deadline_status": status, "rebuild_triggers": trig,
    "rules": {"embargo_days": embargo},
    "periods": [{"name": n, "block_start": s, "block_end": e} for n, s, e in blocks]}))
""" % ([list(b) for b in V1],)


CAND_OUTPUT = {"threshold_multipliers": [2, 3], "horizon_days": [14, 28],
               "combinations": [[2, 14], [2, 28], [3, 14], [3, 28]], "combination_count": 4,
               "last_read_offset_days": {"14": 14, "28": 28}}

# J の最大が 120 の候補（T-023）。FAKE_PERIODS の --j120（J 120、embargo 120）と組にする。
# 採用される periods-triggers の J は candidates の J の最大と等しく、採用される periods の
# embargo_days は max(1 件目の 90, J の最大) と等しくなければならないため。
CAND_J120 = {"threshold_multipliers": [2, 3], "horizon_days": [14, 120],
             "combinations": [[2, 14], [2, 120], [3, 14], [3, 120]], "combination_count": 4,
             "last_read_offset_days": {"14": 14, "120": 120}}


def run_verify(root, *args):
    return subprocess.run([sys.executable, "-B", VERIFY, "--root", root] + list(args),
                          capture_output=True)


class SealCase(unittest.TestCase):
    """仮のプロジェクトで封印の仕組みを動かす（本物の sealed/ には書かない）。"""

    def setUp(self):
        self.root = tempfile.mkdtemp()
        for rel, _role in seal_periods.SOURCES:
            os.makedirs(os.path.join(self.root, os.path.dirname(rel)), exist_ok=True)
            with open(os.path.join(self.root, rel), "w") as f:
                f.write(FAKE_PERIODS if rel.endswith("periods.py") else "# %s\n" % rel)
        for d in ("data/manifest", "data/processed", "data/archives", "sealed"):
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

    def seal_triggers(self, now, **values):
        rec, _p, _s = seal_triggers.seal(self.root, values, now, None)
        stamp.stamp_seq(self.ledger, rec["seq"], "ots", runner=FakeRun())
        return rec

    def _append_doc(self, kind, doc, now):
        """中身の JSON を sealed/<kind>-<sha256>.json に書き、記録に追記して .ots を作る。
        テストの中だけの道具（本番の仕組みは後のタスク）。"""
        data = ledger.read_ledger(self.ledger)
        seq = len(ledger.verify_chain(data)) + 1
        content = ledger.canonical_line(doc) + b"\n"
        sha = ledger.sha256_hex(content)
        rel = "sealed/%s-%s.json" % (kind, sha)
        ledger.write_once(os.path.join(self.root, rel), content)
        ledger.append_record(self.ledger, kind, [{"path": rel, "role": kind, "sha256": sha}],
                             "", now)
        stamp.stamp_seq(self.ledger, seq, "ots", runner=FakeRun())
        return seq

    def _drand_doc(self, kind, round_no, head, **kw):
        data = ledger.read_ledger(self.ledger)
        seq = len(ledger.verify_chain(data)) + 1
        if head is None:
            head = ledger.expected_ledger_head(data, seq)
        doc = drand_doc(kind, round_no, head=head)
        doc.update(kw)
        return doc

    def add_access(self, now, round_no, head=None, **kw):
        return self._append_doc(ledger.THRESHOLD_ACCESS_KIND,
                                self._drand_doc(ledger.THRESHOLD_ACCESS_KIND, round_no, head, **kw),
                                now)

    def add_start(self, now, round_no, head=None):
        return self._append_doc(ledger.ACQ_START_KIND,
                                self._drand_doc(ledger.ACQ_START_KIND, round_no, head), now)

    def add_result(self, now, start_seq):
        return self._append_doc(ledger.ACQ_RESULT_KIND,
                                {"kind": ledger.ACQ_RESULT_KIND, "start_seq": start_seq,
                                 "kept_rows_sha256": "e" * 64}, now)

    def add_method(self, now, round_no, head=None, **kw):
        return self._append_doc(ledger.METHOD_ACCESS_KIND,
                                self._drand_doc(ledger.METHOD_ACCESS_KIND, round_no, head, **kw),
                                now)

    def add_cand(self, now, output=None):
        """candidates の記録を、書く仕組みを通さずに足す（T-014。acquisition-start の前提）。
        対象の 4 つのファイルが無ければ仮のものを作り、形の照合に通る出力を書く。"""
        for rel, _role in ledger.CANDIDATES_SOURCES:
            full = os.path.join(self.root, rel)
            if not os.path.exists(full):
                os.makedirs(os.path.dirname(full), exist_ok=True)
                with open(full, "w") as f:
                    f.write("# %s\n" % rel)
        out = (json.dumps(output or CAND_OUTPUT, sort_keys=True, indent=2) + "\n").encode()
        sha = ledger.sha256_hex(out)
        rel = ledger.candidates_output_rel(sha)
        ledger.write_once(os.path.join(self.root, rel), out)
        targets = [{"path": p, "role": r, "sha256": ledger.sha256_file(os.path.join(self.root, p))}
                   for p, r in ledger.CANDIDATES_SOURCES]
        targets.append({"path": rel, "role": "output", "sha256": sha})
        ledger.append_record(self.ledger, ledger.CANDIDATES_KIND, targets, "", now)
        seq = len(ledger.verify_chain(ledger.read_ledger(self.ledger)))
        stamp.stamp_seq(self.ledger, seq, "ots", runner=FakeRun())
        return seq


class TestSealPeriods(SealCase):
    def test_seal_writes_record_output_and_anchor(self):
        rec = self.seal()
        self.assertEqual(rec["kind"], "periods")
        self.assertEqual(sorted(t["role"] for t in rec["targets"]),
                         ["code", "doc", "output", "test"])
        out = os.path.join(self.root, "sealed", "periods-output-%s.json" % self.out_sha)
        self.assertEqual(ledger.sha256_file(out), self.out_sha)
        r = run_verify(self.root, "all")
        self.assertEqual(r.returncode, 0, r.stderr.decode())
        text = r.stdout.decode()
        self.assertIn("採用は保留（threshold-access の記録が無いため）", text)
        self.assertIn("seq 1: Pending", text)
        self.assertIn("仮の候補 = seq 1", text)
        self.assertIn("ヘッダが、Bitcoin の本当の鎖にあること", text)
        self.assertIn("drand の署名（BLS）は、オフラインでは検証していない", text)

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

    def test_first_version_refused_when_raw_has_file(self):
        os.makedirs(os.path.join(self.root, "data", "raw"))
        with open(os.path.join(self.root, "data", "raw", "x.csv"), "w") as f:
            f.write("1")
        with self.assertRaises(ledger.LedgerError):
            self.seal()

    def test_first_version_refused_for_any_folder_under_data(self):
        os.makedirs(os.path.join(self.root, "data", "other", "deep"))
        with open(os.path.join(self.root, "data", "other", "deep", "x"), "w") as f:
            f.write("1")
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
        self.assertEqual(run_verify(self.root, "periods").returncode, 1)

    def test_verify_fails_when_middle_ots_removed(self):
        self.seal()
        self.seal(now=T0 + H)
        self.seal(now=T0 + 2 * H)
        os.rename(os.path.join(self.root, "sealed", ledger.ots_name(2)),
                  os.path.join(self.root, "moved.ots"))
        r = run_verify(self.root, "all")
        self.assertEqual(r.returncode, 1)
        self.assertIn("seq 2", r.stderr.decode())

    def test_triggers_record_and_held_status(self):
        self.seal()
        trec = self.seal_triggers(T0 + H, last_read_offset_days=120)
        self.assertEqual(trec["kind"], ledger.TRIGGERS_KIND)
        args = ["--j120", "before_deadline"]
        sha = ledger.sha256_hex(seal_periods.run_periods(self.root, args))
        self.seal(args=args, sha=sha, now=T0 + 2 * H)
        r = run_verify(self.root, "all")
        self.assertEqual(r.returncode, 0, r.stderr.decode())
        self.assertIn("照合を保留", r.stdout.decode())

    def test_triggers_need_periods(self):
        with self.assertRaises(ledger.LedgerError):
            seal_triggers.seal(self.root, {"last_read_offset_days": 120}, T0, None)

    def test_triggers_reject_empty(self):
        self.seal()
        with self.assertRaises(ledger.LedgerError):
            seal_triggers.seal(self.root, {}, T0 + H, None)

    def test_threshold_access_decides_adoption_and_status(self):
        """threshold-access の記録があれば採用が決まる。Pending でも採用は変わらない。"""
        self.seal()
        self.seal_triggers(T0 + H, last_read_offset_days=120)
        args = ["--j120", "before_deadline"]
        sha = ledger.sha256_hex(seal_periods.run_periods(self.root, args))
        self.seal(args=args, sha=sha, now=T0 + 2 * H)
        # T-017：threshold-access の前に candidates が要る。T-023：J の最大は triggers の J と同じ 120
        self.add_cand(T0 + 2 * H + H / 2, output=CAND_J120)
        self.add_access(T0 + 3 * H, 30_000_000)
        r = run_verify(self.root, "all")
        self.assertEqual(r.returncode, 0, r.stderr.decode())
        text = r.stdout.decode()
        self.assertIn("区切り：最初の threshold-access の記録 = seq 5", text)
        self.assertIn("periods: 採用 = seq 3（2 件目", text)
        self.assertIn("periods-triggers: 採用 = seq 2（1 件目", text)
        self.assertIn("ヘッダが本当の鎖にあることは、この検査では確かめていない", text)
        self.assertIn("確定時刻との照合は保留", text)
        self.assertIn("記録から決まる値 before_deadline", text)

    def test_acquisition_alone_keeps_adoption_held(self):
        """acquisition-start・result だけでは区切りにならず、採用は保留のまま。"""
        self.seal()
        self.add_cand(T0 + H / 2)
        start = self.add_start(T0 + H, 30_000_000)
        self.add_result(T0 + 2 * H, start)
        r = run_verify(self.root, "all")
        self.assertEqual(r.returncode, 0, r.stderr.decode())
        text = r.stdout.decode()
        self.assertIn("採用は保留（threshold-access の記録が無いため）", text)
        self.assertIn("acquisition-start seq 3 ← acquisition-result seq 4", text)

    def test_triggers_after_step3_adopted_and_after_access_not(self):
        """手順3（start の後）・threshold-access の前の triggers は採用され、before_deadline が通る。
        threshold-access の後に追記した triggers と periods は採用されない（追記は拒まない）。"""
        self.seal()
        self.add_cand(T0 + H / 2, output=CAND_J120)   # T-023：J の最大を triggers の J にそろえる
        start = self.add_start(T0 + H, 30_000_000)
        self.add_result(T0 + 2 * H, start)
        trec = self.seal_triggers(T0 + 3 * H, last_read_offset_days=120)
        args = ["--j120", "before_deadline"]
        sha = ledger.sha256_hex(seal_periods.run_periods(self.root, args))
        prec = self.seal(args=args, sha=sha, now=T0 + 4 * H)
        access = self.add_access(T0 + 5 * H, 30_000_000)
        late_t = self.seal_triggers(T0 + 6 * H, last_read_offset_days=150)   # 関門は無い
        late_p = self.seal(now=T0 + 7 * H)
        r = run_verify(self.root, "all")
        self.assertEqual(r.returncode, 0, r.stderr.decode())
        text = r.stdout.decode()
        self.assertIn("区切り：最初の threshold-access の記録 = seq %d" % access, text)
        self.assertIn("periods-triggers: 採用 = seq %d" % trec["seq"], text)
        self.assertIn("periods: 採用 = seq %d" % prec["seq"], text)
        self.assertIn("seq %d は threshold-access の記録より後なので、採用しない" % late_t["seq"],
                      text)
        self.assertIn("seq %d は threshold-access の記録より後なので、採用しない" % late_p["seq"],
                      text)
        self.assertIn("記録から決まる値 before_deadline", text)

    def test_before_deadline_claim_after_access_fails(self):
        """threshold-access の後に追記したきっかけの値に合わせて before_deadline と申告すると失敗。"""
        self.seal()
        self.add_access(T0 + H, 30_000_000)
        self.seal_triggers(T0 + 2 * H, last_read_offset_days=120)
        args = ["--j120", "before_deadline"]
        sha = ledger.sha256_hex(seal_periods.run_periods(self.root, args))
        self.seal(args=args, sha=sha, now=T0 + 3 * H)
        r = run_verify(self.root, "periods")
        self.assertEqual(r.returncode, 1)
        self.assertIn("before_deadline と申告", r.stderr.decode())

    def test_after_deadline_claim_after_access_passes(self):
        self.seal()
        self.add_cand(T0 + H / 2)                # T-017：threshold-access の前に candidates が要る
        self.add_access(T0 + H, 30_000_000)
        self.seal_triggers(T0 + 2 * H, last_read_offset_days=120)
        args = ["--j120", "after_deadline"]
        sha = ledger.sha256_hex(seal_periods.run_periods(self.root, args))
        self.seal(args=args, sha=sha, now=T0 + 3 * H)
        r = run_verify(self.root, "all")
        self.assertEqual(r.returncode, 0, r.stderr.decode())
        self.assertIn("記録から決まる値 after_deadline", r.stdout.decode())
        self.assertIn("periods-triggers: seq 3 より前に記録が無い", r.stdout.decode())

    def test_ledger_head_mismatch_fails_in_verify(self):
        for add, cmd in ((self.add_access, "access"), (self.add_start, "acquisition")):
            self.tearDown()
            self.setUp()
            self.seal()
            self.seal_triggers(T0 + H, last_read_offset_days=120)
            data = ledger.read_ledger(self.ledger)
            add(T0 + 2 * H, 30_000_000, head={"seq": 1, "sha256": ledger.prefix_digest(data, 1)})
            for c in (cmd, "all"):
                r = run_verify(self.root, c)
                self.assertEqual(r.returncode, 1, c)
                self.assertIn("ledger_head が、直前の記録のハッシュと一致しない", r.stderr.decode())

    def test_access_block_start_must_match_first_periods(self):
        self.seal()
        self.add_access(T0 + H, 30_000_000, block_start="2021-01-01")
        r = run_verify(self.root, "all")
        self.assertEqual(r.returncode, 1)
        self.assertIn("block_start 2021-01-01", r.stderr.decode())

    def test_result_pairing_broken_fails_in_verify(self):
        """result の参照先が無い・start より前・一つの start に二つ、のどれも verify で失敗。"""
        cases = {
            "missing": lambda: self.add_result(T0 + H, 7),
            "before": lambda: (self.add_result(T0 + H, 3), self.add_start(T0 + 2 * H, 30_000_000)),
            "twice": lambda: (self.add_start(T0 + H, 30_000_000), self.add_result(T0 + 2 * H, 2),
                              self.add_result(T0 + 3 * H, 2)),
        }
        msgs = {"missing": "実在しない", "before": "より前にある", "twice": "二つ以上"}
        for name, build in cases.items():
            self.tearDown()
            self.setUp()
            self.seal()
            build()
            for c in ("acquisition", "all"):
                r = run_verify(self.root, c)
                self.assertEqual(r.returncode, 1, (name, c))
                self.assertIn(msgs[name], r.stderr.decode(), name)

    def test_unknown_kind_fails_in_verify(self):
        """仕組みを通さずに許可リストに無い kind（T-007 の acquisition）を足すと、verify が失敗。"""
        self.seal()
        data = ledger.read_ledger(self.ledger)
        rec = {"seq": 2, "prev_hash": ledger.sha256_hex(ledger.split_lines(data)[-1]),
               "kind": "acquisition", "targets": [target("x")],
               "recorded_at": "2026-10-06T13:00:00Z", "note": ""}
        with open(self.ledger, "ab") as f:
            f.write(ledger.canonical_line(rec) + b"\n")
        for c in ("chain", "all", "adopted"):
            r = run_verify(self.root, c)
            self.assertEqual(r.returncode, 1, c)
            self.assertIn("許可リストに無い", r.stderr.decode())

    def test_btc_header_for_height_not_in_ots_rejected(self):
        """.ots の中に無い高さのヘッダを渡すと、エラーで止まる（自由な入力を受け付けない）。"""
        self.seal()
        r = run_verify(self.root, "adopted", "--btc-header", "123=" + "00" * 80)
        self.assertEqual(r.returncode, 1)
        self.assertIn("高さ 123", r.stderr.decode())
        r = run_verify(self.root, "adopted", "--btc-header", "123=00")
        self.assertEqual(r.returncode, 2)

    def test_removed_free_input_options(self):
        self.seal()
        for opt in ("--deadline", "--anchor-time", "--margin-hours"):
            r = run_verify(self.root, "adopted", opt, "2026-10-07T00:00:00Z")
            self.assertEqual(r.returncode, 2, opt)

    def test_verify_targets_detects_changed_file(self):
        self.seal()
        with open(os.path.join(self.root, "docs", "stats", "periods.md"), "a") as f:
            f.write("後から足した行\n")
        self.assertEqual(run_verify(self.root, "targets").returncode, 1)

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
        self.assertEqual(run_verify(self.root, "targets").returncode, 1)
        self.assertEqual(run_verify(self.root, "targets", "--rev", "auto").returncode, 0)
        # 履歴の中の記録を書き換えたコミットがあれば、--rev auto は失敗する。
        with open(self.ledger, "rb") as f:
            data = f.read()
        with open(self.ledger, "wb") as f:
            f.write(data.replace("periods の 1 件目".encode(), "periods の 9 件目".encode()))
        git("commit", "-q", "-am", "tamper")
        self.assertEqual(run_verify(self.root, "targets", "--rev", "auto").returncode, 1)


# ---------------------------------------------------------------- 監査 R-1・R-2 の再現（T-007）


def run_verify_inproc(root, *args, ots_dirs=()):
    """verify.main を同じプロセスで動かす。テストのヘッダは易しい目標値で掘るので、作業量の
    下限だけを 1 に下げる（本番の検証のコードは変えない）。"""
    out, err = io.StringIO(), io.StringIO()
    easy = functools.partial(otsfile.check_header, min_work_bits=1)
    argv = ["--root", root] + list(args)
    for d in ots_dirs:
        argv += ["--ots-dir", d]
    with mock.patch.object(otsfile, "check_header", easy), \
            contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = verify.main(argv)
    return code, out.getvalue(), err.getvalue()


def adoption_lines(text):
    return [l for l in text.splitlines()
            if l.startswith("  periods: ") or l.startswith("  periods-triggers: ")]


class TestAuditRepro(SealCase):
    """seq 1 periods、seq 2 periods、seq 3 periods-triggers、seq 4 candidates、
    seq 5 threshold-access、seq 6 periods。
    どの操作でも、採用は periods = seq 2、periods-triggers = seq 3 のまま。
    T-017：threshold-access の前に candidates が要る（verify access の照合）ので seq 4 に足した。
    T-023：J とエンバーゴの照合（採用される triggers の J = candidates の J の最大、採用される
    periods の embargo_days = max(90, J の最大)）に通るよう、candidates の J の最大を seq 3 の
    J（120）にそろえ（CAND_J120）、seq 2 を J 120 で作り直した periods（embargo 120）にした。"""

    ACQ_ROUND = 30_000_000   # 公開時刻は 2026 年の夏。下の確定時刻（T0 以後）より前。

    def build(self, round_no=ACQ_ROUND):
        self.seal()
        j120 = ["--j120", "before_deadline"]
        self.seal(args=j120, sha=ledger.sha256_hex(seal_periods.run_periods(self.root, j120)),
                  now=T0 + H)
        self.seal_triggers(T0 + 2 * H, last_read_offset_days=120)
        self.add_cand(T0 + 2 * H + H / 2, output=CAND_J120)   # T-023：J の最大 120
        self.add_access(T0 + 3 * H, round_no)
        args = ["--j120", "before_deadline"]
        sha = ledger.sha256_hex(seal_periods.run_periods(self.root, args))
        self.seal(args=args, sha=sha, now=T0 + 4 * H)
        self.sealed = os.path.join(self.root, "sealed")

    def confirm(self, seqs, directory=None, base=T0 + 6 * H):
        """seqs の .bitcoin.ots とヘッダを作る（directory が無ければ sealed/）。ヘッダ引数を返す。"""
        directory = directory or self.sealed
        data = ledger.read_ledger(self.ledger)
        args = []
        for seq in seqs:
            prefix = ledger.prefix_bytes(data, seq)
            height = 900000 + seq
            with open(os.path.join(directory, ledger.ots_name(seq, bitcoin=True)), "xb") as f:
                f.write(build_ots(prefix, pending=(), heights=(height,)))
            hdr = mine_header(tip_msg(prefix), base + seq * H)
            args += ["--btc-header", "%d=%s" % (height, hdr.hex())]
        return args

    def verify_all(self, *args, ots_dirs=()):
        code, out, err = run_verify_inproc(self.root, "all", *args, ots_dirs=ots_dirs)
        self.assertEqual(code, 0, err)
        return out

    def assertAdoption(self, out):
        lines = adoption_lines(out)
        self.assertEqual(len(lines), 2, out)
        self.assertTrue(lines[0].startswith("  periods: 採用 = seq 2（2 件目"), lines)
        self.assertTrue(lines[1].startswith("  periods-triggers: 採用 = seq 3（1 件目"), lines)
        return lines

    def test_baseline_all_pending(self):
        self.build()
        out = self.verify_all()
        self.assertAdoption(out)
        self.assertIn("seq 6 は threshold-access の記録より後なので、採用しない", out)
        self.assertIn("確定時刻との照合は保留", out)

    def test_withheld_upgrade_of_seq2_does_not_change_adoption(self):
        """R-1：seq 2 の upgrade を出す場合と出さない場合で、採用が同じ。"""
        self.build()
        full = self.verify_all(*self.confirm([1, 2, 3, 4, 5, 6]))
        os.rename(os.path.join(self.sealed, ledger.ots_name(2, bitcoin=True)),
                  os.path.join(self.root, "withheld.ots"))
        withheld = self.verify_all(*self.headers_for([1, 3, 4, 5, 6]))
        self.assertIn("seq 2: Pending", withheld)
        self.assertNotIn("seq 2: Pending", full)
        self.assertEqual(self.assertAdoption(full), self.assertAdoption(withheld))
        # 後の seq だけ確定、前の seq は Pending、の組み合わせでも同じ。
        for name in os.listdir(self.sealed):
            if name.endswith(".bitcoin.ots") and "seq000006" not in name:
                os.rename(os.path.join(self.sealed, name), os.path.join(self.root, name))
        only5 = self.verify_all(*self.headers_for([6]))
        self.assertEqual(self.assertAdoption(full), self.assertAdoption(only5))

    def headers_for(self, seqs):
        data = ledger.read_ledger(self.ledger)
        args = []
        for seq in seqs:
            hdr = mine_header(tip_msg(ledger.prefix_bytes(data, seq)), T0 + 6 * H + seq * H)
            args += ["--btc-header", "%d=%s" % (900000 + seq, hdr.hex())]
        return args

    def test_own_calendar_pending_for_seq2_is_rejected(self):
        """R-1：seq 2 の .ots を自前のカレンダーの Pending にしても、別の採用は出せない。
        許可していない宛先なので検証が失敗し、許可した宛先の Pending なら採用は同じ。"""
        self.build()
        base = self.assertAdoption(self.verify_all())
        p = os.path.join(self.sealed, ledger.ots_name(2))
        with open(p, "wb") as f:   # テストの中の仮のプロジェクトだけを書き換える
            f.write(build_ots(ledger.prefix_bytes(ledger.read_ledger(self.ledger), 2),
                              pending=(OWN_CAL,)))
        code, out, err = run_verify_inproc(self.root, "all")
        self.assertEqual(code, 1)
        self.assertIn("許可していないカレンダー", err)
        self.assertEqual(adoption_lines(out), [])
        # adopted だけを実行しても、同じ理由で止まる。
        code, out, err = run_verify_inproc(self.root, "adopted")
        self.assertEqual(code, 1)
        self.assertEqual(adoption_lines(out), [])
        # 自前のカレンダーの .ots を --ots-dir で読ませても止まる。
        with open(p, "wb") as f:
            f.write(build_ots(ledger.prefix_bytes(ledger.read_ledger(self.ledger), 2)))
        ext = os.path.join(self.root, "ext")
        os.mkdir(ext)
        with open(os.path.join(ext, ledger.ots_name(2)), "xb") as f:
            f.write(build_ots(ledger.prefix_bytes(ledger.read_ledger(self.ledger), 2),
                              pending=(OWN_CAL,)))
        code, _out, err = run_verify_inproc(self.root, "all", ots_dirs=[ext])
        self.assertEqual(code, 1)
        self.assertIn("許可していないカレンダー", err)
        os.remove(os.path.join(ext, ledger.ots_name(2)))
        self.assertEqual(self.assertAdoption(self.verify_all(ots_dirs=[ext])), base)

    def test_moving_drand_round_does_not_change_adoption(self):
        """R-2：drand の回を前後に動かしても、採用は同じ。"""
        results = []
        for rnd in (self.ACQ_ROUND - 1_000_000, self.ACQ_ROUND, self.ACQ_ROUND + 1_000_000):
            self.tearDown()
            self.setUp()
            self.build(rnd)
            pending = self.verify_all()
            confirmed = self.verify_all(*self.confirm([1, 2, 3, 4, 5, 6]))
            self.assertIn("drand の署名（BLS）を確かめた場合に限る", confirmed)
            results.append(self.assertAdoption(pending))
            results.append(self.assertAdoption(confirmed))
        self.assertTrue(all(r == results[0] for r in results), results)

    def test_drand_round_after_own_confirmation_fails(self):
        """drand の回の公開時刻が threshold-access の記録自身の確定時刻 + 幅 より後なら、失敗する。"""
        late_round = 40_000_000   # 公開時刻は 2027 年。
        self.build(late_round)
        self.assertAdoption(self.verify_all())   # Pending のうちは照合を保留
        args = self.confirm([5])
        code, _out, err = run_verify_inproc(self.root, "all", *args)
        self.assertEqual(code, 1)
        self.assertIn("より前でない", err)

    def test_drand_slack_end_to_end(self):
        """seq 5（threshold-access）の確定時刻（ヘッダの時刻）T0 + 11H に対し、回の公開時刻が 1 時間後なら通り、
        3 時間後なら失敗する。"""
        own = T0 + 6 * H + 5 * H
        genesis, period = ledger.DRAND_CHAINS[QUICKNET]
        for delta, ok in ((H, True), (3 * H, False)):
            self.tearDown()
            self.setUp()
            rnd = int((own + delta).timestamp() - genesis) // period + 1
            self.build(rnd)
            code, out, err = run_verify_inproc(self.root, "all", *self.confirm([5]))
            if ok:
                self.assertEqual(code, 0, err)
                self.assertAdoption(out)
            else:
                self.assertEqual(code, 1)
                self.assertIn("より前でない", err)

    def test_third_party_upgrade_via_ots_dir(self):
        """第三者が自分で upgrade した .ots を --ots-dir で読ませる。採用は変わらない。"""
        self.build()
        base = self.assertAdoption(self.verify_all())
        ext = os.path.join(self.root, "my-upgrades")
        os.mkdir(ext)
        args = self.confirm([1, 5], directory=ext)
        out = self.verify_all(*args, ots_dirs=[ext])
        self.assertIn("seq 1: Bitcoin で確定", out)
        self.assertIn("seq 5: Bitcoin で確定", out)
        self.assertIn("my-upgrades", out)
        self.assertEqual(self.assertAdoption(out), base)
        # 読ませたディレクトリの .ots の対象が違えば失敗。
        with open(os.path.join(ext, ledger.ots_name(2)), "xb") as f:
            f.write(build_ots(b"other\n"))
        code, _o, err = run_verify_inproc(self.root, "all", *args, ots_dirs=[ext])
        self.assertEqual(code, 1)
        self.assertIn("一致しない", err)

    def test_ots_dir_option_on_cli(self):
        self.build()
        r = run_verify(self.root, "all", "--ots-dir", os.path.join(self.root, "none"))
        self.assertEqual(r.returncode, 1)
        self.assertIn("ディレクトリが無い", r.stderr.decode())


if __name__ == "__main__":
    unittest.main()
