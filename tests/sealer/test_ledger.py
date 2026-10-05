"""封印の記録（src/sealer/）のテスト。T-005。

実行（プロジェクトのルートで）:
    PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest discover -s tests/sealer -v

ネットワークは使わない。OpenTimestamps のクライアントは呼ばず、偽の応答で置き換える。
Bitcoin の証明は、テストの中で作った .ots と、易しい目標値で掘ったヘッダで試す。
わざと壊した記録（書き換え・削除・入れ替え・欠番・末尾の削除・途中の .ots の欠け）で、
検証が失敗することを確かめる。
"""

import datetime
import hashlib
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
import otsfile  # noqa: E402
import seal_periods  # noqa: E402
import seal_triggers  # noqa: E402
import stamp  # noqa: E402

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


def build_ots(prefix, pending=("https://cal.example",), heights=()):
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
    """期限前の最後の追記。時刻は各 seq 自身の .ots の Bitcoin の確定だけから決める。"""

    def setUp(self):
        super().setUp()
        self.recs = self.add(n=3)
        for s in (1, 2, 3):
            self.stamp(s)
        self.deadline = T0 + 24 * H

    def times(self, confirmed):
        """confirmed: {seq: (高さ, 時刻)}。.bitcoin.ots とヘッダを作り、確定時刻を得る。"""
        headers = {}
        for seq, (height, when) in confirmed.items():
            headers[height] = self.stamp_bitcoin(seq, height, when)
        anchors = ledger.check_anchors(self.data(), self.tmp)
        times, _d, unused = ledger.confirmed_times(anchors, headers, min_work_bits=1)
        self.assertEqual(unused, [])
        return times

    def test_last_before_deadline_is_adopted(self):
        times = self.times({1: (100, T0 + H), 2: (101, T0 + 3 * H), 3: (102, T0 + 30 * H)})
        rec, st = ledger.adopted_record(self.recs, "periods", self.deadline, times)
        self.assertEqual(rec["seq"], 2)
        self.assertEqual(st, {1: ledger.BEFORE, 2: ledger.BEFORE, 3: ledger.LATE})

    def test_audit_repro_1_3(self):
        """監査の再現：記録 3 件で、.ots を {1,2,3} 出すか {1,3} だけ出すかで採用が変わった。

        今は {1,3} だけでは検証が失敗する（seq 2 自身の .ots が要る）。
        また、seq 2 の確定が無いときに seq 3 の時刻で代わりにしない。
        """
        os.rename(os.path.join(self.tmp, ledger.ots_name(2)), os.path.join(self.tmp, "x"))
        with self.assertRaisesRegex(ledger.LedgerError, "seq 2 の記録に"):
            ledger.check_anchors(self.data(), self.tmp)
        os.rename(os.path.join(self.tmp, "x"), os.path.join(self.tmp, ledger.ots_name(2)))
        # {1,2,3} の .ots があり、Bitcoin で確定したのが 1 と 3 だけの場合。
        times = self.times({1: (100, T0 + H), 3: (102, T0 + 2 * H)})
        self.assertEqual(sorted(times), [1, 3])
        rec, st = ledger.adopted_record(self.recs, "periods", self.deadline, times)
        self.assertEqual(st[2], ledger.PENDING)
        self.assertEqual(rec["seq"], 3)
        # seq 3 の時刻が期限後なら、seq 2 はその時刻を借りず Pending のまま。採用は seq 1。
        rec, st = ledger.adopted_record(self.recs, "periods", self.deadline,
                                        {1: T0 + H, 3: T0 + 30 * H})
        self.assertEqual(rec["seq"], 1)
        self.assertEqual(st, {1: ledger.BEFORE, 2: ledger.PENDING, 3: ledger.LATE})

    def test_pending_middle_is_not_shown_before(self):
        """途中の .ots が Pending なら、その記録は期限前とは示せない（S-1）。"""
        times = self.times({1: (100, T0 + H)})
        rec, st = ledger.adopted_record(self.recs, "periods", self.deadline, times)
        self.assertEqual(rec["seq"], 1)
        self.assertEqual(st[2], ledger.PENDING)
        self.assertIn("期限前とは示せない", ledger.STATUS_TEXT[st[2]])

    def test_recorded_at_is_not_used(self):
        """recorded_at はすべて期限前だが、確定が無ければ採用しない。"""
        rec, st = ledger.adopted_record(self.recs, "periods", self.deadline, {})
        self.assertIsNone(rec)
        self.assertEqual(set(st.values()), {ledger.PENDING})

    def test_margin_applied(self):
        times = {1: self.deadline - 2 * H}
        rec, st = ledger.adopted_record(self.recs, "periods", self.deadline, times)
        self.assertIsNone(rec)
        self.assertEqual(st[1], ledger.LATE)

    def test_deadline_unknown_is_held(self):
        rec, st = ledger.adopted_record(self.recs, "periods", None, {1: T0})
        self.assertIsNone(rec)
        self.assertEqual(set(st.values()), {ledger.HELD})

    def test_naive_deadline_refused(self):
        with self.assertRaises(ValueError):
            ledger.adopted_record(self.recs, "periods", self.deadline.replace(tzinfo=None), {})

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


# ---------------------------------------------------------------- 期限


def acquisition_doc(round_no=1000, chain=QUICKNET, signature="ab" * 48):
    return {"step": 3, "drand": {"chain_hash": chain, "round": round_no,
                                 "signature": signature,
                                 "randomness": ledger.sha256_hex(bytes.fromhex(signature))}}


class TestDeadline(unittest.TestCase):
    def test_round_time(self):
        d = ledger.deadline_from_acquisition(acquisition_doc(1))
        self.assertEqual(int(d.timestamp()), 1692803367)
        d = ledger.deadline_from_acquisition(acquisition_doc(101))
        self.assertEqual(int(d.timestamp()), 1692803367 + 300)

    def test_bad_randomness(self):
        doc = acquisition_doc()
        doc["drand"]["randomness"] = "00" * 32
        with self.assertRaisesRegex(ledger.LedgerError, "randomness"):
            ledger.deadline_from_acquisition(doc)

    def test_unknown_chain_and_missing_fields(self):
        with self.assertRaises(ledger.LedgerError):
            ledger.deadline_from_acquisition(acquisition_doc(chain="00" * 32))
        with self.assertRaises(ledger.LedgerError):
            ledger.deadline_from_acquisition({"step": 3})
        with self.assertRaises(ledger.LedgerError):
            ledger.deadline_from_acquisition(acquisition_doc(0))


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
if "--move" in sys.argv:
    blocks[1] = ["threshold", "2020-12-20", "2023-11-06"]
if "--j120" in sys.argv:
    trig["last_read_offset_days"] = 120
    status = sys.argv[-1]
print(json.dumps({"deadline_status": status, "rebuild_triggers": trig,
    "periods": [{"name": n, "block_start": s, "block_end": e} for n, s, e in blocks]}))
""" % ([list(b) for b in V1],)


def run_verify(root, *args):
    return subprocess.run([sys.executable, "-B", VERIFY, "--root", root] + list(args),
                          capture_output=True)


class TestSealPeriods(unittest.TestCase):
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
        self.assertIn("期限：未確定", text)
        self.assertIn("Pending", text)
        self.assertIn("保留", text)
        self.assertIn("ots verify で確かめる", text)

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

    def add_acquisition(self, now, round_no):
        content = json.dumps(acquisition_doc(round_no), sort_keys=True).encode()
        sha = ledger.sha256_hex(content)
        rel = "sealed/acquisition-%s.json" % sha
        ledger.write_once(os.path.join(self.root, rel), content)
        ledger.append_record(self.ledger, ledger.ACQUISITION_KIND,
                             [{"path": rel, "role": "acquisition", "sha256": sha}], "", now)
        rec = ledger.verify_chain(ledger.read_ledger(self.ledger))[-1]
        stamp.stamp_seq(self.ledger, rec["seq"], "ots", runner=FakeRun())

    def test_deadline_from_acquisition_record_and_pending(self):
        """取得の記録があれば期限が決まる。Pending の記録は期限前とは示せない。"""
        self.seal()
        self.seal_triggers(T0 + H, last_read_offset_days=120)
        args = ["--j120", "before_deadline"]
        sha = ledger.sha256_hex(seal_periods.run_periods(self.root, args))
        self.seal(args=args, sha=sha, now=T0 + 2 * H)
        self.add_acquisition(T0 + 3 * H, 30_000_000)
        r = run_verify(self.root, "adopted")
        self.assertEqual(r.returncode, 0, r.stderr.decode())
        text = r.stdout.decode()
        self.assertIn("期限：", text)
        self.assertNotIn("未確定（手順3", text)
        self.assertIn("期限前とは示せない（この seq の .ots が Bitcoin で確定していない）", text)
        # before_deadline の申告は、期限前と示せる triggers の記録が無いので失敗になる。
        r = run_verify(self.root, "periods")
        self.assertEqual(r.returncode, 1)
        self.assertIn("before_deadline と申告", r.stderr.decode())

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


if __name__ == "__main__":
    unittest.main()
