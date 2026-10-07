"""T-014 の残り（軽1〜軽4）と、T-015 の監査 軽1・軽5 の sealer の側のテスト。T-017。

実行（プロジェクトのルートで）:
    PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest discover -s tests/sealer -v

ネットワークは使わない（drand・ots は偽物）。仮のプロジェクトで動かし、本物の sealed/ には
書かない。各項目について、わざと壊して止まることと、壊さなければ通ることの両方を確かめる。
  1. 関門は引数を取らず、テストは ledger.PROJECT_ROOT の差し替えだけで仮のプロジェクトを読ませる。
     src/ の下にテスト用の root の引数（_test_root）を渡すコードが無い。TMPDIR に左右されない。（軽1）
  2. verify access が「最初の threshold-access より前に candidates があること」を確かめる。（軽2）
  3. 手順書の10章の記述（マニフェストの時刻証明、J）。（軽3・軽4）
  4. candidates の J の最大 ≤ periods の embargo_days。超えたときに限り、期限より前に
     periods-triggers を求める（verify・関門・書く仕組み）。（軽4）
  5. sealed/ と記録のファイルがシンボリックリンクで別の場所を指していたら、関門・書く仕組み・
     検証・ヘッダの書き込みが止まる。（T-015 の監査 軽1・軽5）
"""

import datetime
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import test_ledger as tl  # noqa: E402
import test_t014 as t14  # noqa: E402
import test_writers as tw  # noqa: E402
from test_ledger import T0, H, run_verify  # noqa: E402

ledger = tl.ledger
import seal_access  # noqa: E402
import seal_bitcoin  # noqa: E402
import seal_method  # noqa: E402

PROJECT = tl.PROJECT
SRC_ROOT = os.path.join(PROJECT, "src")
DOC = os.path.join(PROJECT, "docs", "verify", "periods-seal.md")

# J が 90 日を超える候補（判定期間 120 日）。形の照合には通る。
CAND_LONG = {"threshold_multipliers": [2, 3], "horizon_days": [14, 120],
             "combinations": [[2, 14], [2, 120], [3, 14], [3, 120]], "combination_count": 4,
             "last_read_offset_days": {"14": 14, "120": 120}}


def src_py_files():
    out = []
    for dirpath, _dirs, files in os.walk(SRC_ROOT):
        for name in files:
            if name.endswith(".py"):
                out.append(os.path.join(dirpath, name))
    return sorted(out)


# ---------------------------------------------------------------- 1. 関門の root（軽1）


class TestGateRootFixed(tw.WriterCase):
    def test_no_test_root_in_src(self):
        """src/ の下のどの .py にも、テスト用の root の引数の名前が無い。"""
        files = src_py_files()
        self.assertTrue(any(f.endswith(os.path.join("sealer", "ledger.py")) for f in files))
        self.assertTrue(any(os.sep + "collector" + os.sep in f for f in files))
        for path in files:
            with open(path, encoding="utf-8") as f:
                self.assertNotIn("_test_root", f.read(), path)

    def test_no_code_in_src_replaces_project_root_or_passes_gate_args(self):
        """src/ の下に、PROJECT_ROOT を書き換えるコードも、関門に引数を渡すコードも無い。"""
        assign = re.compile(r"(\bledger\s*\.\s*PROJECT_ROOT\s*=(?!=))|(setattr\s*\(\s*ledger\b)")
        call = re.compile(r"require_(threshold|method)_access\s*\(\s*[^)\s]")
        for path in src_py_files():
            with open(path, encoding="utf-8") as f:
                text = f.read()
            self.assertIsNone(assign.search(text), path)
            self.assertIsNone(call.search(text), path)
        with open(os.path.join(tl.SRC, "ledger.py"), encoding="utf-8") as f:
            text = f.read()
        self.assertEqual(len(re.findall(r"^PROJECT_ROOT\s*=", text, re.M)), 1)

    def test_gates_take_no_arguments(self):
        import inspect
        for fn in (ledger.require_threshold_access, ledger.require_method_access,
                   ledger._gate_root):
            self.assertEqual(list(inspect.signature(fn).parameters), [], fn.__name__)

    def test_gate_root_does_not_depend_on_tmpdir(self):
        """関門の root の決め方は、一時的なディレクトリ（TMPDIR）を読まない。"""
        with open(os.path.join(tl.SRC, "ledger.py"), encoding="utf-8") as f:
            text = f.read()
        for word in ("tempfile", "gettempdir", "TMPDIR"):
            self.assertNotIn(word, text)

    def test_patch_reads_fake_project_and_is_restored(self):
        self.seal()
        self.access(T0 + H)
        before = ledger.PROJECT_ROOT
        rec = self.threshold_gate()
        self.assertEqual(rec["kind"], ledger.THRESHOLD_ACCESS_KIND)
        self.assertEqual(ledger.PROJECT_ROOT, before)
        self.assertEqual(os.path.realpath(before), os.path.realpath(PROJECT))

    def test_patch_restored_on_failure(self):
        before = ledger.PROJECT_ROOT
        with self.assertRaises(ledger.ThresholdAccessRequired):
            self.threshold_gate()
        self.assertEqual(ledger.PROJECT_ROOT, before)

    def test_gate_tests_pass_with_other_tmpdirs(self):
        """TMPDIR を変えて、関門のテストを別のプロセスで実行しても結果が変わらない。

        T-014 の失敗は、TMPDIR がプロジェクトの祖先のときに起きた。プロジェクトの外に書かない
        ため、ここでは、一時的なディレクトリの中に作った深い場所と、その親の二つで試す。
        どちらでも、関門の root は TMPDIR を読まない（上のテスト）ので結果は同じになる。
        """
        base = tempfile.mkdtemp()
        try:
            deep = os.path.join(base, "a", "b")
            os.makedirs(deep)
            names = ["test_t014.TestGateRoot", "test_t014.TestMethodGate",
                     "test_t014.TestThresholdGateCandidates", "test_writers.TestGate",
                     "test_t017.TestSymlinkedSealed"]
            for tmp in (deep, base):
                env = dict(os.environ, TMPDIR=tmp, PYTHONDONTWRITEBYTECODE="1")
                r = subprocess.run([sys.executable, "-B", "-m", "unittest"] + names, cwd=HERE,
                                   env=env, capture_output=True, timeout=300)
                self.assertEqual(r.returncode, 0, r.stderr.decode()[-3000:])
        finally:
            shutil.rmtree(base)


# ---------------------------------------------------------------- 2. verify access と candidates（軽2）


class TestVerifyAccessCandidates(t14.Case):
    def test_access_without_candidates_before_fails(self):
        """candidates を threshold-access の後に足しても（acquisition-start は無い）、
        verify access と all は失敗する。T-014 までは、この形が検証を通っていた。"""
        self.seal(with_cand=False)
        access = self.add_access(T0 + H, 30_000_000)
        self.add_cand(T0 + 2 * H)
        self.verify_fails(("access", "all"),
                          "seq %d より前に candidates の記録が無い" % access)

    def test_access_with_no_candidates_at_all_fails(self):
        self.seal(with_cand=False)
        self.add_access(T0 + H, 30_000_000)
        self.verify_fails(("access", "all"), "candidates の記録が無い")

    def test_access_with_tampered_candidates_output_fails(self):
        self.seal()
        self.access(T0 + H)
        c = [x for x in self.records() if x["kind"] == ledger.CANDIDATES_KIND][0]
        with open(os.path.join(self.root, ledger.output_target(c)["path"]), "ab") as f:
            f.write(b" ")
        self.verify_fails(("access",), "seq %d の output のファイルが記録と一致しない" % c["seq"])

    def test_access_with_candidates_before_passes(self):
        self.seal()
        rec, _rel, _o = self.access(T0 + H)
        out = self.verify_ok("access")
        self.assertIn("最初の threshold-access（seq %d）より前に candidates の記録がある"
                      % rec["seq"], out)
        self.verify_ok("all")


# ---------------------------------------------------------------- 4. J とエンバーゴ（軽4）


class TestHorizonEmbargo(t14.Case):
    def seal_long(self):
        """periods（embargo 90）と、J の最大が 120 の candidates。"""
        self.seal(with_cand=False)
        self.cand_seq = self.add_cand(T0 + datetime.timedelta(minutes=1), output=CAND_LONG)

    def test_real_values_within(self):
        """本物の封印の値：candidates の J の最大 56、periods の embargo_days 90。"""
        sealed = os.path.join(PROJECT, "sealed")
        cand = glob.glob(os.path.join(sealed, "candidates-output-*.json"))
        per = glob.glob(os.path.join(sealed, "periods-output-*.json"))
        self.assertEqual(len(cand), 1)
        self.assertEqual(len(per), 1)
        with open(cand[0], encoding="utf-8") as f:
            self.assertEqual(ledger.candidates_max_j(json.load(f)), 56)
        with open(per[0], encoding="utf-8") as f:
            self.assertEqual(ledger.periods_embargo_days(json.load(f)), 90)

    def test_within_needs_no_triggers(self):
        self.seal()
        self.step3(T0 + H)
        self.method(T0 + 3 * H)
        self.access(T0 + 4 * H)
        out = self.verify_ok("candidates")
        self.assertIn("J（判定が読む最後の日のずれ）の最大 28 は、periods の 1 件目の "
                      "embargo_days 90 以下", out)
        self.verify_ok("all")
        self.method_gate()
        self.threshold_gate()

    def test_exceeding_is_held_until_deadline(self):
        self.seal_long()
        self.step3(T0 + H)
        out = self.verify_ok("candidates")
        self.assertIn("保留：J の最大 120 が embargo_days 90 を超える", out)

    def test_exceeding_without_triggers_fails_at_threshold_access(self):
        self.seal_long()
        access = self.add_access(T0 + H, 30_000_000)
        self.verify_fails(("candidates", "all"),
                          "threshold-access の記録（seq %d）より前に、last_read_offset_days が "
                          "120 以上の periods-triggers の記録が要る" % access)
        with self.assertRaisesRegex(ledger.ThresholdAccessRequired, "periods-triggers"):
            self.threshold_gate()

    def test_exceeding_without_triggers_fails_at_method_access(self):
        self.seal_long()
        self.step3(T0 + H)
        method = self.add_method(T0 + 3 * H, 30_000_000)
        self.verify_fails(("candidates", "all"),
                          "method-access の記録（seq %d）より前に" % method)
        with self.assertRaisesRegex(ledger.MethodAccessRequired, "periods-triggers"):
            self.method_gate()

    def test_writers_refuse_without_triggers(self):
        self.seal_long()
        self.step3(T0 + H)
        before, data = self.snapshot(), self.ledger_bytes()
        with self.assertRaisesRegex(ledger.LedgerError, "periods-triggers の記録が要る"):
            self.method(T0 + 3 * H)
        with self.assertRaisesRegex(ledger.LedgerError, "periods-triggers の記録が要る"):
            seal_access.seal(self.root, T0 + 3 * H, "ots", drand_fetch=tw.FakeDrand(T0 + 3 * H),
                             runner=tw.FakeOts())
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.ledger_bytes(), data)

    def test_triggers_too_small_fails(self):
        self.seal_long()
        self.seal_triggers(T0 + H, last_read_offset_days=100)
        self.add_access(T0 + 2 * H, 30_000_000)
        self.verify_fails(("candidates", "all"), "120 以上の periods-triggers")

    def test_triggers_after_deadline_fails(self):
        self.seal_long()
        self.add_access(T0 + H, 30_000_000)
        self.seal_triggers(T0 + 2 * H, last_read_offset_days=120)
        self.verify_fails(("candidates", "all"), "120 以上の periods-triggers")

    def test_triggers_before_deadline_passes(self):
        self.seal_long()
        trec = self.seal_triggers(T0 + H, last_read_offset_days=120)
        self.step3(T0 + 2 * H)
        rec, _rel, _o = self.method(T0 + 4 * H)
        out = self.verify_ok("candidates")
        self.assertIn("J の最大 120 が embargo_days 90 を超える。method-access（seq %d）より前の "
                      "periods-triggers（seq %d）の last_read_offset_days が 120 以上"
                      % (rec["seq"], trec["seq"]), out)
        self.verify_ok("all")
        self.method_gate()

    def test_malformed_j_fails(self):
        good = dict(tl.CAND_OUTPUT)
        self.assertEqual(ledger.candidates_max_j(good), 28)
        for bad in (
                {k: v for k, v in good.items() if k != "last_read_offset_days"},
                dict(good, last_read_offset_days={"14": 14}),
                dict(good, last_read_offset_days={"14": 14, "28": 27}),
                dict(good, last_read_offset_days={"14": 14, "28": 28.0}),
                dict(good, last_read_offset_days={"14": 14, "28": 28, "56": 56})):
            with self.assertRaises(ledger.LedgerError):
                ledger.candidates_max_j(bad)
        for bad in ({}, {"rules": {}}, {"rules": {"embargo_days": 0}},
                    {"rules": {"embargo_days": "90"}}):
            with self.assertRaises(ledger.LedgerError):
                ledger.periods_embargo_days(bad)

    def test_malformed_j_in_sealed_output_fails_verify(self):
        self.seal(with_cand=False)
        self.add_cand(T0 + H, output=dict(tl.CAND_OUTPUT,
                                          last_read_offset_days={"14": 14, "28": 7}))
        self.verify_fails(("candidates", "all"), "last_read_offset_days")


# ---------------------------------------------------------------- 5. sealed/ のシンボリックリンク


class TestSymlinkedSealed(t14.Case):
    def setUp(self):
        super().setUp()
        self.outside = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.outside)
        super().tearDown()

    def move_sealed_out(self):
        """仮のプロジェクトの sealed/ を外に移し、sealed/ をそこへのリンクにする。"""
        dst = os.path.join(self.outside, "sealed")
        shutil.move(self.sealed, dst)
        os.symlink(dst, self.sealed)
        return dst

    def move_ledger_out(self):
        dst = os.path.join(self.outside, "ledger.jsonl")
        shutil.move(self.ledger, dst)
        os.symlink(dst, self.ledger)
        return dst

    def outside_bytes(self, path):
        with open(path, "rb") as f:
            return f.read()

    def test_check_sealed_inside_passes_normally(self):
        self.seal()
        self.assertEqual(ledger.check_sealed_inside(self.root), os.path.realpath(self.root))

    def test_gates_stop_on_symlinked_sealed(self):
        self.seal()
        self.step3(T0 + H)
        self.method(T0 + 3 * H)
        self.access(T0 + 4 * H)
        self.threshold_gate()
        self.method_gate()
        self.move_sealed_out()
        with self.assertRaisesRegex(ledger.ThresholdAccessRequired, "sealed/ の実体"):
            self.threshold_gate()
        with self.assertRaisesRegex(ledger.MethodAccessRequired, "sealed/ の実体"):
            self.method_gate()

    def test_gates_stop_on_symlinked_ledger(self):
        self.seal()
        self.access(T0 + H)
        self.move_ledger_out()
        with self.assertRaisesRegex(ledger.ThresholdAccessRequired, "ledger.jsonl の実体"):
            self.threshold_gate()

    def test_writers_do_not_append_outside(self):
        self.seal()
        dst = self.move_sealed_out()
        led = os.path.join(dst, "ledger.jsonl")
        before = self.outside_bytes(led)
        names = sorted(os.listdir(dst))
        fake = tw.FakeDrand(T0 + H)
        with self.assertRaisesRegex(ledger.LedgerError, "sealed/ の実体"):
            seal_access.seal(self.root, T0 + H, "ots", drand_fetch=fake, runner=tw.FakeOts())
        with self.assertRaisesRegex(ledger.LedgerError, "sealed/ の実体"):
            self.start(T0 + H)
        with self.assertRaisesRegex(ledger.LedgerError, "sealed/ の実体"):
            seal_method.seal(self.root, T0 + H, "ots", drand_fetch=fake, runner=tw.FakeOts())
        self.assertEqual(fake.urls, [])           # drand を取りにいく前に止まる
        self.assertEqual(self.outside_bytes(led), before)
        self.assertEqual(sorted(os.listdir(dst)), names)

    def test_writers_do_not_append_to_symlinked_ledger(self):
        self.seal()
        dst = self.move_ledger_out()
        before = self.outside_bytes(dst)
        with self.assertRaisesRegex(ledger.LedgerError, "ledger.jsonl の実体"):
            seal_access.seal(self.root, T0 + H, "ots", drand_fetch=tw.FakeDrand(T0 + H),
                             runner=tw.FakeOts())
        self.assertEqual(self.outside_bytes(dst), before)

    def test_bitcoin_writer_refuses(self):
        self.seal()
        dst = self.move_sealed_out()
        names = sorted(os.listdir(dst))
        up = tw.FakeUpgrade()
        with self.assertRaisesRegex(ledger.LedgerError, "sealed/ の実体"):
            seal_bitcoin.confirm(self.root, 1, "ots", lambda h: b"\0" * 80, runner=up)
        with self.assertRaisesRegex(ledger.LedgerError, "sealed/ の実体"):
            seal_bitcoin.write_header(self.root, 900123, lambda h: b"\0" * 80)
        self.assertEqual(up.calls, [])           # upgrade の前に止まる
        self.assertEqual(sorted(os.listdir(dst)), names)

    def test_verify_fails_on_symlinked_sealed(self):
        self.seal()
        self.verify_ok("all")
        self.move_sealed_out()
        self.verify_fails(("chain", "all"), "sealed/ の実体")

    def test_sealed_pointing_at_project_root_is_refused(self):
        """sealed/ がプロジェクトのルートそのものを指すリンクでも止まる（下にあるとは言えない）。"""
        self.seal()
        shutil.move(self.sealed, os.path.join(self.outside, "moved"))
        os.symlink(self.root, self.sealed)
        with self.assertRaisesRegex(ledger.LedgerError, "sealed/ の実体"):
            ledger.check_sealed_inside(self.root)


# ---------------------------------------------------------------- 3. 手順書（軽3・軽4、T-017）


class TestDocT017(unittest.TestCase):
    def setUp(self):
        with open(DOC, encoding="utf-8") as f:
            self.text = f.read()

    def test_manifest_statement_is_factual(self):
        self.assertNotIn("マニフェスト（`data/manifest/`）と、その時刻証明で確かめる", self.text)
        self.assertIn("マニフェスト（`data/manifest/`）には、OpenTimestamps の時刻証明は付いていない",
                      self.text)
        self.assertIn("`kept_rows_sha256`", self.text)

    def test_j_statement(self):
        self.assertNotIn("J（判定が読む最後の日のずれ）の追記は確かめない", self.text)
        for phrase in ("J は `candidates` の封印で決まっている", "最大は 56",
                       "`embargo_days`（90）以下", "超えたときに限り"):
            self.assertIn(phrase, self.text)

    def test_gate_root_statement(self):
        self.assertNotIn("_test_root", self.text)
        self.assertIn("`ledger.PROJECT_ROOT` を差し替える", self.text)
        self.assertIn("シンボリックリンク", self.text)

    def test_access_statement(self):
        self.assertIn("最初の `threshold-access` より前に `candidates` の記録があること", self.text)


if __name__ == "__main__":
    unittest.main()
