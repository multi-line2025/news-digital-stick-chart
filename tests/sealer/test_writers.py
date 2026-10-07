"""threshold-access・acquisition-start・acquisition-result を書く仕組み、関門、upgrade と
ヘッダの書き込みのテスト。T-009。

実行（プロジェクトのルートで）:
    PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest discover -s tests/sealer -v

ネットワークは使わない。drand の応答、ots（stamp・upgrade）、ブロックのヘッダの取得は、
すべて差し替えたものを使う。仮のプロジェクト（一時的なディレクトリ）で動かし、本物の
sealed/ には書かない。
わざと壊すもの：二つ目の result、start でない seq を指す result、periods の無い状態、
コミットしていない取得のコード、古い drand の回、randomness の食い違い、許可していない宛先、
途中で別の記録が追記された状態、書いた中身の改ざん、threshold-access の .ots の欠け、
許可していないカレンダーの Pending を返す upgrade、照合に通らないヘッダ。
"""

import contextlib
import datetime
import hashlib
import json
import os
import subprocess
import sys
import unittest
import urllib.error

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import test_ledger as tl  # noqa: E402
from test_ledger import AUTHOR, FakeRun, T0, H  # noqa: E402

ledger = tl.ledger
otsfile = tl.otsfile
stamp = tl.stamp

import netfetch  # noqa: E402
import seal_access  # noqa: E402
import seal_acquisition  # noqa: E402
import seal_bitcoin  # noqa: E402

CODE_REL = "src/collector/fetch_list.py"
GENESIS = 1692803367


def drand_body(now, age=datetime.timedelta(seconds=2), bad_randomness=False):
    rnd = int((now - age).timestamp() - GENESIS) // 3 + 1
    sig = hashlib.sha256(str(rnd).encode()).digest() * 3
    rand = "00" * 32 if bad_randomness else hashlib.sha256(sig).hexdigest()
    return json.dumps({"round": rnd, "randomness": rand, "signature": sig.hex()}).encode()


class FakeOts(FakeRun):
    """ots の偽物。--version にも答える（check_ots を通すため）。"""

    def __call__(self, cmd, input=None, capture_output=True, timeout=None):
        if cmd[1:] == ["--version"]:
            return subprocess.CompletedProcess(cmd, 0, stdout=b"v0.7.2", stderr=b"")
        return super().__call__(cmd, input=input, capture_output=capture_output, timeout=timeout)


class FakeDrand:
    """netfetch.http_get の代わり。drand の応答を返し、呼ばれた URL を控える。"""

    def __init__(self, now, **kw):
        self.now, self.kw, self.urls = now, kw, []

    def __call__(self, url):
        self.urls.append(url)
        return drand_body(self.now, **self.kw)


class FakeUpgrade:
    """subprocess.run の代わり。ots upgrade の偽の応答。

    confirmed が真なら、写しの .ots を、Bitcoin の証明（高さ height）を持つものに書き換える。
    extra_pending があれば、その宛先の Pending も足す。
    """

    def __init__(self, confirmed=True, height=900123, extra_pending=()):
        self.confirmed, self.height, self.extra_pending = confirmed, height, extra_pending
        self.calls = []

    def __call__(self, cmd, input=None, capture_output=True, timeout=None):
        self.calls.append(cmd)
        if cmd[1] == "upgrade" and self.confirmed:
            path = cmd[2]
            with open(path, "rb") as f:
                digest = bytes.fromhex(otsfile.parse(f.read())[0])
            with open(path + ".bak", "wb") as f:
                f.write(b"backup")
            with open(path, "wb") as f:
                f.write(ots_for_digest(digest, self.height, self.extra_pending))
        return subprocess.CompletedProcess(cmd, 0, stdout=b"", stderr=b"")


def ots_for_digest(digest, height, extra_pending=()):
    atts = [b"\x00" + otsfile.TAG_PENDING + tl.varbytes(tl.varbytes(u.encode()))
            for u in (tl.ALLOWED_CAL,) + tuple(extra_pending)]
    atts.append(b"\x00" + otsfile.TAG_BITCOIN + tl.varbytes(tl.varuint(height)))
    tree = b"".join(b"\xff" + a for a in atts[:-1]) + atts[-1]
    return (otsfile.MAGIC + b"\x01\x08" + digest + b"\xf0" + tl.varbytes(tl.NONCE) + b"\x08"
            + tree)


def tip_for_digest(digest):
    return hashlib.sha256(digest + tl.NONCE).digest()


def copy_sealer(root):
    """src/sealer の .py を仮のプロジェクトに写す（その写しの PROJECT_ROOT は root になる）。"""
    dst = os.path.join(root, "src", "sealer")
    os.makedirs(dst, exist_ok=True)
    for name in os.listdir(tl.SRC):
        if name.endswith(".py"):
            with open(os.path.join(tl.SRC, name), "rb") as f:
                data = f.read()
            with open(os.path.join(dst, name), "wb") as f:
                f.write(data)


@contextlib.contextmanager
def gate_project(root):
    """関門が読むルート（ledger.PROJECT_ROOT）を、テストの中だけ仮のプロジェクトに差し替える。

    T-017（T-014 の監査 軽1）。関門は引数を取らないので、テストはこの形でだけ仮のプロジェクトを
    読ませる。抜けるときに必ず元に戻す。TMPDIR には左右されない。
    """
    old = ledger.PROJECT_ROOT
    ledger.PROJECT_ROOT = root
    try:
        yield
    finally:
        ledger.PROJECT_ROOT = old


class WriterCase(tl.SealCase):
    def threshold_gate(self):
        with gate_project(self.root):
            return ledger.require_threshold_access()

    def method_gate(self):
        with gate_project(self.root):
            return ledger.require_method_access()

    def setUp(self):
        super().setUp()
        os.makedirs(os.path.join(self.root, "src", "collector"))
        with open(os.path.join(self.root, CODE_REL), "w") as f:
            f.write("# 取得のコード（テストの仮のもの）\n")
        self.git("init", "-q")
        self.commit("最初")
        self.sealed = os.path.join(self.root, "sealed")

    def git(self, *args):
        return subprocess.run(["git", "-C", self.root] + list(AUTHOR) + list(args),
                              check=True, capture_output=True).stdout

    def seal(self, *args, with_cand=True, **kw):
        """periods を封印し、続けて candidates の記録を足す（T-014。取得と threshold-access の
        前提）。with_cand=False なら periods だけ。"""
        rec = super().seal(*args, **kw)
        if with_cand:
            self.cand_seq = self.add_cand(kw.get("now", T0) + datetime.timedelta(minutes=1))
        return rec

    def commit(self, msg):
        self.git("add", "-A")
        self.git("commit", "-q", "--allow-empty", "-m", msg)

    def snapshot(self):
        """sealed/ のファイルの名前と中身。何も書かれていないことを確かめるため。"""
        out = {}
        for name in sorted(os.listdir(self.sealed)):
            with open(os.path.join(self.sealed, name), "rb") as f:
                out[name] = f.read()
        return out

    def access(self, now):
        return seal_access.seal(self.root, now, "ots", drand_fetch=FakeDrand(now),
                                runner=FakeOts())

    def start(self, now, code=CODE_REL):
        return seal_acquisition.start(self.root, code, now, "ots", drand_fetch=FakeDrand(now),
                                      runner=FakeOts())

    def result(self, now, start_seq, kept="e" * 64):
        return seal_acquisition.result(self.root, start_seq, kept, now, "ots", runner=FakeOts())

    def verify_ok(self, *args):
        r = tl.run_verify(self.root, *args)
        self.assertEqual(r.returncode, 0, r.stderr.decode())
        return r.stdout.decode()

    def doc_of(self, rel):
        with open(os.path.join(self.root, rel), "rb") as f:
            return json.loads(f.read())


# ---------------------------------------------------------------- 三種類の書き込み


class TestWriteThreeKinds(WriterCase):
    def test_threshold_access_written_and_verified(self):
        self.seal()
        rec, rel, ots_path = self.access(T0 + H)
        self.assertEqual(rec["seq"], 3)
        self.assertEqual(rec["kind"], ledger.THRESHOLD_ACCESS_KIND)
        self.assertEqual(rec["targets"], [{"path": rel, "role": "threshold-access",
                                           "sha256": ledger.sha256_file(
                                               os.path.join(self.root, rel))}])
        doc = self.doc_of(rel)
        self.assertEqual(doc["block_start"], "2020-12-15")
        data = ledger.read_ledger(self.ledger)
        self.assertEqual(doc["ledger_head"], {"seq": 2, "sha256": ledger.prefix_digest(data, 2)})
        self.assertEqual(doc["drand"]["chain_hash"], netfetch.QUICKNET)
        self.assertTrue(os.path.exists(ots_path))
        self.assertEqual(os.path.basename(ots_path), ledger.ots_name(3))
        out = self.verify_ok("all")
        self.assertIn("区切り：最初の threshold-access の記録 = seq 3", out)
        self.assertIn("threshold-access seq 3: ledger_head は直前の記録", out)

    def test_start_and_result_written_and_verified(self):
        self.seal()
        srec, srel, _ = self.start(T0 + H)
        sdoc = self.doc_of(srel)
        self.assertEqual(sdoc["step"], 3)
        with open(os.path.join(self.root, CODE_REL), "rb") as f:
            self.assertEqual(sdoc["fetch"], {"code_path": CODE_REL,
                                             "code_sha256": ledger.sha256_hex(f.read())})
        rrec, rrel, _ = self.result(T0 + 2 * H, srec["seq"], "d" * 64)
        self.assertEqual(self.doc_of(rrel), {"kind": "acquisition-result", "start_seq": 3,
                                             "kept_rows_sha256": "d" * 64})
        out = self.verify_ok("all")
        self.assertIn("acquisition-start seq 3 ← acquisition-result seq 4", out)
        self.assertIn(CODE_REL, out)
        self.assertIn("採用は保留（threshold-access の記録が無いため）", out)

    def test_all_three_then_verify_all_rev_auto(self):
        """三種類を書いてコミットし、verify.py all --rev auto が通る。"""
        self.seal()
        s, _r, _o = self.start(T0 + H)
        self.result(T0 + 2 * H, s["seq"])
        # T-023：candidates の J の最大（28）と食い違う J は置けないので、J の無いきっかけにする
        self.seal_triggers(T0 + 3 * H, network_window_days=500)
        self.access(T0 + 4 * H)
        self.commit("記録")
        out = self.verify_ok("all", "--rev", "auto")
        self.assertIn("すべての検査に通った。", out)
        self.assertIn("periods-triggers: 採用 = seq 5", out)

    def test_drand_is_fetched_from_allowed_urls_only(self):
        self.seal()
        fake = FakeDrand(T0 + H)
        seal_access.seal(self.root, T0 + H, "ots", drand_fetch=fake, runner=FakeOts())
        self.assertEqual(fake.urls, [netfetch.DRAND_URLS[0]])


# ---------------------------------------------------------------- 拒むこと


class TestRefusals(WriterCase):
    def test_access_refused_without_periods(self):
        before = self.snapshot()
        with self.assertRaisesRegex(ledger.LedgerError, "periods の記録が無い"):
            self.access(T0)
        self.assertEqual(self.snapshot(), before)
        self.assertFalse(os.path.exists(self.ledger))

    def test_acquisition_refused_without_periods(self):
        with self.assertRaisesRegex(ledger.LedgerError, "periods の記録が無い"):
            self.start(T0)
        with self.assertRaisesRegex(ledger.LedgerError, "periods の記録が無い"):
            self.result(T0, 1)
        self.assertFalse(os.path.exists(self.ledger))

    def test_second_result_refused(self):
        self.seal()
        s, _r, _o = self.start(T0 + H)
        self.result(T0 + 2 * H, s["seq"])
        before = self.snapshot()
        with self.assertRaisesRegex(ledger.LedgerError, "二つ以上"):
            self.result(T0 + 3 * H, s["seq"], "f" * 64)
        self.assertEqual(self.snapshot(), before)
        self.verify_ok("all")

    def test_result_pointing_to_non_start_refused(self):
        self.seal()
        self.start(T0 + H)
        before = self.snapshot()
        for bad in (1, 2, 99):   # seq 1 は periods、seq 2 は candidates、seq 99 は無い
            with self.assertRaisesRegex(ledger.LedgerError, "acquisition-start の記録ではない"):
                self.result(T0 + 2 * H, bad)
        with self.assertRaisesRegex(ledger.LedgerError, "start_seq が正の整数でない"):
            self.result(T0 + 2 * H, "3")
        with self.assertRaisesRegex(ledger.LedgerError, "kept_rows_sha256 の形"):
            self.result(T0 + 2 * H, 3, "E" * 64)
        self.assertEqual(self.snapshot(), before)

    def test_start_refuses_uncommitted_or_changed_code(self):
        self.seal()
        before = self.snapshot()
        with open(os.path.join(self.root, CODE_REL), "a") as f:
            f.write("# 作業ツリーで変えた\n")
        with self.assertRaisesRegex(ledger.LedgerError, "HEAD のコミットの中身と違う"):
            self.start(T0 + H)
        with open(os.path.join(self.root, "src", "collector", "new.py"), "w") as f:
            f.write("x\n")
        with self.assertRaisesRegex(ledger.LedgerError, "HEAD のコミットに無い"):
            self.start(T0 + H, code="src/collector/new.py")
        for bad in ("../x.py", "/etc/hosts", "src/collector/missing.py"):
            with self.assertRaises(ledger.LedgerError):
                self.start(T0 + H, code=bad)
        self.assertEqual(self.snapshot(), before)

    def test_stale_or_bad_drand_refused(self):
        self.seal()
        before = self.snapshot()
        old = FakeDrand(T0 + H, age=datetime.timedelta(minutes=10))
        with self.assertRaisesRegex(netfetch.FetchError, "古すぎる"):
            seal_access.seal(self.root, T0 + H, "ots", drand_fetch=old, runner=FakeOts())
        self.assertEqual(len(old.urls), len(netfetch.DRAND_URLS))
        bad = FakeDrand(T0 + H, bad_randomness=True)
        with self.assertRaisesRegex(netfetch.FetchError, "randomness"):
            seal_access.seal(self.root, T0 + H, "ots", drand_fetch=bad, runner=FakeOts())
        ahead = FakeDrand(T0 + H, age=-datetime.timedelta(minutes=10))
        with self.assertRaisesRegex(netfetch.FetchError, "より先"):
            seal_access.seal(self.root, T0 + H, "ots", drand_fetch=ahead, runner=FakeOts())
        self.assertEqual(self.snapshot(), before)

    def test_refused_when_existing_ots_missing(self):
        self.seal()
        os.rename(os.path.join(self.sealed, ledger.ots_name(1)),
                  os.path.join(self.root, "moved.ots"))
        before = self.snapshot()
        with self.assertRaisesRegex(ledger.LedgerError, "時刻証明"):
            self.access(T0 + H)
        self.assertEqual(self.snapshot(), before)

    def test_append_refused_if_ledger_changed_after_doc_built(self):
        """中身（ledger_head）を作ったあとで別の記録が先に入ったら、追記しない。"""
        self.seal()
        data = ledger.read_ledger(self.ledger)
        self.seal_triggers(T0 + H, last_read_offset_days=120)
        changed = ledger.read_ledger(self.ledger)
        with self.assertRaisesRegex(ledger.LedgerError, "変わっている"):
            ledger.append_record(self.ledger, ledger.THRESHOLD_ACCESS_KIND,
                                 [tl.target("a/x")], "", T0 + 2 * H, expected_data=data)
        self.assertEqual(ledger.read_ledger(self.ledger), changed)

    def test_precheck_uses_verify_rules(self):
        """照合に通らない中身は、書く前に止まる（例：ledger_head の食い違い、kind の違い）。"""
        import seal_records
        self.seal()
        data = ledger.read_ledger(self.ledger)
        before = self.snapshot()
        doc = tl.drand_doc(ledger.THRESHOLD_ACCESS_KIND, 30_000_000,
                           head={"seq": 1, "sha256": "0" * 64})
        with self.assertRaisesRegex(ledger.LedgerError, "ledger_head"):
            seal_records.write_doc_record(self.root, ledger.THRESHOLD_ACCESS_KIND, doc, data, "",
                                          T0 + H, "ots", runner=FakeOts())
        doc = tl.drand_doc(ledger.THRESHOLD_ACCESS_KIND, 30_000_000,
                           head=ledger.expected_ledger_head(data, 3))
        doc["block_start"] = "2020-12-20"
        with self.assertRaisesRegex(ledger.LedgerError, "block_start"):
            seal_records.write_doc_record(self.root, ledger.THRESHOLD_ACCESS_KIND, doc, data, "",
                                          T0 + H, "ots", runner=FakeOts())
        with self.assertRaisesRegex(ledger.LedgerError, "この仕組みが書く種類ではない"):
            seal_records.write_doc_record(self.root, "periods", {"kind": "periods"}, data, "",
                                          T0 + H, "ots", runner=FakeOts())
        with self.assertRaisesRegex(ledger.LedgerError, "許可リストに無い"):
            seal_records.write_doc_record(self.root, "acquisition", {"kind": "acquisition"},
                                          data, "", T0 + H, "ots", runner=FakeOts())
        self.assertEqual(self.snapshot(), before)

    def test_tampered_written_doc_fails_verify(self):
        self.seal()
        _rec, rel, _o = self.access(T0 + H)
        with open(os.path.join(self.root, rel), "rb") as f:
            raw = f.read()
        with open(os.path.join(self.root, rel), "wb") as f:
            f.write(raw.replace(b"2020-12-15", b"2020-12-16"))
        r = tl.run_verify(self.root, "all")
        self.assertEqual(r.returncode, 1)


# ---------------------------------------------------------------- 関門


class TestGate(WriterCase):
    def test_gate_stops_without_record_and_passes_with_it(self):
        self.seal()
        with self.assertRaisesRegex(ledger.ThresholdAccessRequired, "threshold-access の記録が鎖に無い"):
            self.threshold_gate()
        # 取得の記録（start・result）は関門を開けない。
        s, _r, _o = self.start(T0 + H)
        self.result(T0 + 2 * H, s["seq"])
        with self.assertRaises(ledger.ThresholdAccessRequired):
            self.threshold_gate()
        rec, _rel, _o = self.access(T0 + 3 * H)
        self.assertEqual(self.threshold_gate(), rec)

    def test_gate_stops_on_empty_ledger(self):
        with self.assertRaises(ledger.ThresholdAccessRequired):
            self.threshold_gate()

    def test_gate_is_a_ledger_error(self):
        self.assertTrue(issubclass(ledger.ThresholdAccessRequired, ledger.LedgerError))

    def test_gate_stops_when_access_doc_tampered(self):
        self.seal()
        _rec, rel, _o = self.access(T0 + H)
        with open(os.path.join(self.root, rel), "ab") as f:
            f.write(b" ")
        with self.assertRaisesRegex(ledger.ThresholdAccessRequired, "一致しない"):
            self.threshold_gate()

    def test_gate_stops_when_access_ots_missing(self):
        self.seal()
        rec, _rel, ots_path = self.access(T0 + H)
        os.rename(ots_path, os.path.join(self.root, "moved.ots"))
        with self.assertRaisesRegex(ledger.ThresholdAccessRequired, "時刻証明"):
            self.threshold_gate()

    def test_gate_stops_on_record_not_written_by_mechanism(self):
        """仕組みを通さずに、block_start の違う threshold-access を足しても関門は開かない。"""
        self.seal()
        self.add_access(T0 + H, 30_000_000, block_start="2021-01-01")
        with self.assertRaisesRegex(ledger.ThresholdAccessRequired, "block_start"):
            self.threshold_gate()

    def test_gate_stops_on_broken_chain(self):
        self.seal()
        self.access(T0 + H)
        with open(self.ledger, "rb") as f:
            lines = f.read().split(b"\n")
        lines[0] = lines[0].replace(b"periods", b"periodz", 1)
        with open(self.ledger, "wb") as f:
            f.write(b"\n".join(lines))
        with self.assertRaises(ledger.ThresholdAccessRequired):
            self.threshold_gate()

    def test_gate_cli(self):
        """gate の CLI は --root を受け付けず、コードの置き場のプロジェクトを読む（T-014）。
        仮のプロジェクトに封印のコードを写して、その写しの gate を実行する。"""
        self.seal()
        copy_sealer(self.root)
        cmd = [sys.executable, "-B", os.path.join(self.root, "src", "sealer", "seal_access.py"),
               "gate"]
        r = subprocess.run(cmd + ["--root", self.root], capture_output=True)
        self.assertEqual(r.returncode, 2)
        r = subprocess.run(cmd, capture_output=True)
        self.assertEqual(r.returncode, 1)
        self.assertIn("threshold-access の記録が鎖に無い", r.stderr.decode())
        self.access(T0 + H)
        r = subprocess.run(cmd, capture_output=True)
        self.assertEqual(r.returncode, 0, r.stderr.decode())
        self.assertIn("記録からは検出できない", r.stdout.decode())

    def test_gate_docstring_states_the_limit(self):
        self.assertIn("記録からは検出できない", ledger.require_threshold_access.__doc__)


# ---------------------------------------------------------------- upgrade とヘッダ


class TestBitcoin(WriterCase):
    HEIGHT = 900123

    def setUp(self):
        super().setUp()
        self.seal()                 # seq 1 periods、seq 2 candidates
        self.access(T0 + H)         # seq 3 threshold-access
        self.ledger_bytes = ledger.read_ledger(self.ledger)

    def original(self, seq):
        with open(os.path.join(self.sealed, ledger.ots_name(seq)), "rb") as f:
            return f.read()

    def header_for(self, seq, when):
        digest = bytes.fromhex(ledger.prefix_digest(self.ledger_bytes, seq))
        return tl.mine_header(tip_for_digest(digest), when)

    def test_upgrade_keeps_original_ots(self):
        orig = self.original(3)
        up = FakeUpgrade(height=self.HEIGHT)
        path = stamp.upgrade_seq(self.ledger, 3, "ots", runner=up)
        self.assertEqual(os.path.basename(path), ledger.ots_name(3, bitcoin=True))
        self.assertEqual(self.original(3), orig)
        self.assertEqual(stamp.bitcoin_heights(path), [self.HEIGHT])
        # ots upgrade は写しに対して実行し、sealed/ の .ots は渡さない。
        self.assertNotIn(self.sealed, up.calls[0][2])
        self.assertFalse(any(n.endswith(".bak") for n in os.listdir(self.sealed)))
        with self.assertRaisesRegex(ledger.LedgerError, "上書きしない"):
            stamp.upgrade_seq(self.ledger, 3, "ots", runner=up)

    def test_upgrade_not_confirmed_writes_nothing(self):
        before = self.snapshot()
        self.assertIsNone(stamp.upgrade_seq(self.ledger, 3, "ots",
                                            runner=FakeUpgrade(confirmed=False)))
        self.assertEqual(self.snapshot(), before)

    def test_upgrade_with_foreign_pending_refused(self):
        before = self.snapshot()
        with self.assertRaisesRegex(ledger.LedgerError, "許可していないカレンダー"):
            stamp.upgrade_seq(self.ledger, 3, "ots",
                              runner=FakeUpgrade(extra_pending=(tl.OWN_CAL,)))
        self.assertEqual(self.snapshot(), before)

    def test_write_header_and_verify(self):
        stamp.upgrade_seq(self.ledger, 3, "ots", runner=FakeUpgrade(height=self.HEIGHT))
        hdr = self.header_for(3, T0 + 3 * H)
        path, when, block = seal_bitcoin.write_header(self.root, self.HEIGHT, lambda h: hdr,
                                                      min_work_bits=1)
        self.assertEqual(os.path.basename(path), "bitcoin-header-%d.hex" % self.HEIGHT)
        with open(path) as f:
            self.assertEqual(f.read(), hdr.hex() + "\n")
        self.assertEqual(when, T0 + 3 * H)
        self.assertEqual(block, netfetch.block_hash_of(hdr))
        code, out, err = tl.run_verify_inproc(self.root, "all")
        self.assertEqual(code, 0, err)
        self.assertIn("seq 3: Bitcoin で確定", out)
        self.assertIn("この記録自身の .ots の確定時刻（ヘッダの時刻）", out)

    def test_header_refused_when_not_matching_or_unknown_height(self):
        stamp.upgrade_seq(self.ledger, 3, "ots", runner=FakeUpgrade(height=self.HEIGHT))
        before = self.snapshot()
        wrong = self.header_for(1, T0 + 3 * H)   # seq 1 の値で掘ったヘッダ
        with self.assertRaisesRegex(ledger.LedgerError, "照合に通らない"):
            seal_bitcoin.write_header(self.root, self.HEIGHT, lambda h: wrong, min_work_bits=1)
        with self.assertRaisesRegex(ledger.LedgerError, ".ots の中に無い"):
            seal_bitcoin.write_header(self.root, self.HEIGHT + 1, lambda h: wrong,
                                      min_work_bits=1)
        # 本番の作業量の下限では、易しく掘ったヘッダは通らない。
        easy = self.header_for(3, T0 + 3 * H)
        with self.assertRaisesRegex(ledger.LedgerError, "作業量の下限"):
            seal_bitcoin.write_header(self.root, self.HEIGHT, lambda h: easy)

        def fail(_h):
            raise netfetch.FetchError("取得先によって違う")
        with self.assertRaisesRegex(ledger.LedgerError, "取れなかった"):
            seal_bitcoin.write_header(self.root, self.HEIGHT, fail, min_work_bits=1)
        self.assertEqual(self.snapshot(), before)

    def test_confirm_does_upgrade_and_header(self):
        orig = self.original(3)
        hdr = self.header_for(3, T0 + 3 * H)
        path, written = seal_bitcoin.confirm(self.root, 3, "ots", lambda h: hdr,
                                             runner=FakeUpgrade(height=self.HEIGHT),
                                             min_work_bits=1)
        self.assertEqual(self.original(3), orig)
        self.assertEqual([os.path.basename(w) for w in written],
                         ["bitcoin-header-%d.hex" % self.HEIGHT])
        # もう一度実行しても、何も書き換えない。
        self.assertEqual(seal_bitcoin.confirm(self.root, 3, "ots", lambda h: hdr,
                                              runner=FakeUpgrade(), min_work_bits=1),
                         (path, []))
        self.assertIsNone(seal_bitcoin.confirm(self.root, 1, "ots", lambda h: hdr,
                                               runner=FakeUpgrade(confirmed=False))[0])


class TestFetchers(unittest.TestCase):
    def test_disallowed_url_is_not_requested(self):
        called = []
        with self.assertRaisesRegex(netfetch.FetchError, "許可していない宛先"):
            netfetch.http_get("https://example.com/x", opener=lambda *a, **k: called.append(a))
        self.assertEqual(called, [])

    def test_retry_limit_and_wait(self):
        sleeps, calls = [], []

        def opener(req, timeout):
            calls.append((req.full_url, timeout))
            raise urllib.error.URLError("down")
        with self.assertRaisesRegex(netfetch.FetchError, "%d 回" % netfetch.MAX_TRIES):
            netfetch.http_get(netfetch.DRAND_URLS[0], sleep=sleeps.append, opener=opener)
        self.assertEqual(len(calls), netfetch.MAX_TRIES)
        self.assertEqual(sleeps, [netfetch.WAIT_SECONDS] * (netfetch.MAX_TRIES - 1))
        self.assertTrue(all(t == netfetch.TIMEOUT_SECONDS for _u, t in calls))

    def test_drand_falls_back_to_next_url(self):
        now = T0
        urls = []

        def fetch(url):
            urls.append(url)
            if len(urls) == 1:
                raise netfetch.FetchError("down")
            return drand_body(now)
        d = netfetch.latest_drand(now, fetch=fetch)
        self.assertEqual(urls, list(netfetch.DRAND_URLS[:2]))
        self.assertEqual(sorted(d), ["chain_hash", "randomness", "round", "signature"])

    def make_explorer(self, header, other=None, bad_hash=False):
        bhash = netfetch.block_hash_of(header)

        def fetch(url):
            self.assertTrue(url.startswith(netfetch.ALLOWED_URL_PREFIXES))
            hdr = other if (other and url.startswith(netfetch.HEADER_SOURCES[1])) else header
            if url.endswith("/header"):
                return hdr.hex().encode()
            return (("00" * 32) if bad_hash else netfetch.block_hash_of(hdr)).encode()
        return fetch, bhash

    def test_header_from_explorers(self):
        hdr = tl.mine_header(b"\x01" * 32, T0)
        fetch, _ = self.make_explorer(hdr)
        self.assertEqual(netfetch.header_from_explorers(5, fetch=fetch), hdr)
        other = tl.mine_header(b"\x02" * 32, T0)
        fetch, _ = self.make_explorer(hdr, other=other)
        with self.assertRaisesRegex(netfetch.FetchError, "取得先によって違う"):
            netfetch.header_from_explorers(5, fetch=fetch)
        fetch, _ = self.make_explorer(hdr, bad_hash=True)
        with self.assertRaisesRegex(netfetch.FetchError, "一致しない"):
            netfetch.header_from_explorers(5, fetch=fetch)

    def test_header_from_bitcoin_cli(self):
        hdr = tl.mine_header(b"\x01" * 32, T0)
        calls = []

        def runner(cmd, capture_output=True, timeout=None):
            calls.append(cmd)
            out = netfetch.block_hash_of(hdr) if cmd[1] == "getblockhash" else hdr.hex()
            return subprocess.CompletedProcess(cmd, 0, stdout=(out + "\n").encode(), stderr=b"")
        self.assertEqual(netfetch.header_from_bitcoin_cli(7, runner=runner), hdr)
        self.assertEqual(calls[0], ["bitcoin-cli", "getblockhash", "7"])


if __name__ == "__main__":
    unittest.main()
