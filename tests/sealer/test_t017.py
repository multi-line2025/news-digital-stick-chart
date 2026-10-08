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
import fixed_records  # noqa: E402
import test_t014 as t14  # noqa: E402
import test_writers as tw  # noqa: E402
from test_ledger import T0, H, run_verify  # noqa: E402

ledger = tl.ledger
import seal_access  # noqa: E402
import seal_acquisition  # noqa: E402
import seal_candidates  # noqa: E402
import seal_records  # noqa: E402
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
        # T-077：元のルートを名前に入れずに、差し替えのあとで元（このリポジトリ）に戻っていることを比べる
        rec = self.threshold_gate()
        self.assertEqual(rec["kind"], ledger.THRESHOLD_ACCESS_KIND)
        self.assertEqual(os.path.realpath(ledger.PROJECT_ROOT), os.path.realpath(PROJECT))

    def test_patch_restored_on_failure(self):
        with self.assertRaises(ledger.ThresholdAccessRequired):
            self.threshold_gate()
        self.assertEqual(os.path.realpath(ledger.PROJECT_ROOT), os.path.realpath(PROJECT))

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
    """照合の相手は、その時点（最初の method-access・最初の threshold-access）で採用される
    periods と periods-triggers である（差し戻し1回目の中2 の (a)・(b)）。"""

    def seal_long(self):
        """periods（embargo 90）と、J の最大が 120 の candidates。"""
        self.seal(with_cand=False)
        self.cand_seq = self.add_cand(T0 + datetime.timedelta(minutes=1), output=CAND_LONG)

    def rebuilt_periods(self, now):
        """J = 120 で作り直した periods（embargo 120）を封印する。"""
        args = ["--j120", "before_deadline"]
        sha = ledger.sha256_hex(tl.seal_periods.run_periods(self.root, args))
        return self.seal(args=args, sha=sha, now=now, with_cand=False)

    def raw_triggers(self, now, **values):
        """periods-triggers を、書く仕組みを通さずに足す（書く仕組みを飛ばした場合の再現）。
        T-027 の差し戻し1回目で test_t023.py の JCase から移した。"""
        doc = {k: values.get(k) for k in ledger.TRIGGER_KEYS}
        content = ledger.canonical_line(doc) + b"\n"
        sha = ledger.sha256_hex(content)
        rel = "sealed/periods-triggers-%s.json" % sha
        ledger.write_once(os.path.join(self.root, rel), content)
        ledger.append_record(self.ledger, ledger.TRIGGERS_KIND,
                             [{"path": rel, "role": "triggers", "sha256": sha}], "", now)
        seq = len(self.records())
        tl.stamp.stamp_seq(self.ledger, seq, "ots", runner=tl.FakeRun())
        return seq

    def raw_periods(self, args, now):
        """periods の版を、書く仕組み（seal_periods）を通さずに足す（書く仕組みを飛ばした場合の
        再現）。T-031：seal_periods に書く前の照合が入ったので、その照合を飛ばした記録を作るため。"""
        out = tl.seal_periods.run_periods(self.root, list(args))
        sha = ledger.sha256_hex(out)
        rel = "sealed/periods-output-%s.json" % sha
        ledger.write_once(os.path.join(self.root, rel), out)
        targets = [{"path": p, "role": r, "sha256": ledger.sha256_file(os.path.join(self.root, p))}
                   for p, r in tl.seal_periods.SOURCES]
        targets.append({"path": rel, "role": "output", "sha256": sha})
        ledger.append_record(self.ledger, ledger.PERIODS_KIND, targets, "", now)
        seq = len(self.records())
        tl.stamp.stamp_seq(self.ledger, seq, "ots", runner=tl.FakeRun())
        return seq

    def assert_periods_writer_refuses(self, args, now, msg):
        """seal_periods が msg を含む理由で、何も書かずに止まること。"""
        before, data = self.snapshot(), self.ledger_bytes()
        sha = ledger.sha256_hex(tl.seal_periods.run_periods(self.root, list(args)))
        with self.assertRaises(ledger.LedgerError) as cm:
            self.seal(args=list(args), sha=sha, now=now, with_cand=False)
        self.assertIn(msg, str(cm.exception))
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.ledger_bytes(), data)

    def test_real_values_within(self):
        """本物の封印の値：candidates の J の最大 56、periods の 1 件目の embargo_days 90。
        どのファイルを使うかは、本物の記録の順番（periods の 1 件目、すべての candidates）で選ぶ
        （差し戻し1回目の軽4。sealed/ の中のファイルの数には頼らない）。
        T-077：HEAD ではなく、固定したコミット（fixed_records.PINNED_COMMIT）の記録を取り出して読む。"""
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        root = fixed_records.checkout(os.path.join(td.name, "c"), code=None)
        records = ledger.verify_chain(ledger.read_ledger(
            os.path.join(root, "sealed", "ledger.jsonl")))
        first = ledger.records_of_kind(records, ledger.PERIODS_KIND)[0][1]
        cands = [r for _v, r in ledger.records_of_kind(records, ledger.CANDIDATES_KIND)]
        self.assertTrue(cands)
        self.assertEqual(ledger.periods_embargo_days(
            ledger.read_target_json(root, first, "output")), 90)
        self.assertEqual(max(ledger.candidates_max_j(ledger.read_target_json(root, c, "output"))
                             for c in cands), 56)

    def test_within_needs_no_triggers(self):
        self.seal()
        self.step3(T0 + H)
        self.method(T0 + 3 * H)
        self.access(T0 + 4 * H)
        out = self.verify_ok("candidates")
        self.assertIn("J（判定が読む最後の日のずれ）の最大 28。periods の 1 件目の embargo_days 90 以下",
                      out)
        self.assertIn("method-access（seq", out)
        self.verify_ok("all")
        self.method_gate()
        self.threshold_gate()

    def test_within_but_adopted_triggers_j_smaller_fails(self):
        """作り直しが要らなくても、採用される periods-triggers の J が候補の J より小さければ失敗。"""
        self.seal()
        self.seal_triggers(T0 + H / 2, last_read_offset_days=20)
        self.add_access(T0 + H, 30_000_000)
        self.verify_fails(("candidates", "all"), "last_read_offset_days 20 が")

    def test_exceeding_is_held_until_deadline(self):
        self.seal_long()
        self.step3(T0 + H)
        out = self.verify_ok("candidates")
        self.assertIn("保留：method-access・threshold-access の記録がまだ無い", out)

    def test_exceeding_without_triggers_fails_at_threshold_access(self):
        self.seal_long()
        access = self.add_access(T0 + H, 30_000_000)
        self.verify_fails(("candidates", "all"),
                          "threshold-access の記録（seq %d）の時点で採用される periods（seq 1）の "
                          "embargo_days 90 が" % access)
        with self.assertRaisesRegex(ledger.ThresholdAccessRequired, "embargo_days"):
            self.threshold_gate()

    def test_exceeding_without_triggers_fails_at_method_access(self):
        self.seal_long()
        self.step3(T0 + H)
        method = self.add_method(T0 + 3 * H, 30_000_000)
        self.verify_fails(("candidates", "all"), "method-access の記録（seq %d）の時点" % method)
        with self.assertRaisesRegex(ledger.MethodAccessRequired, "embargo_days"):
            self.method_gate()

    def test_writers_refuse_without_triggers(self):
        self.seal_long()
        self.step3(T0 + H)
        before, data = self.snapshot(), self.ledger_bytes()
        with self.assertRaisesRegex(ledger.LedgerError, "embargo_days 90 が"):
            self.method(T0 + 3 * H)
        with self.assertRaisesRegex(ledger.LedgerError, "embargo_days 90 が"):
            seal_access.seal(self.root, T0 + 3 * H, "ots", drand_fetch=tw.FakeDrand(T0 + 3 * H),
                             runner=tw.FakeOts())
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.ledger_bytes(), data)

    def test_b_triggers_without_rebuilt_periods_fails(self):
        """(b)：triggers が J を覆っていても、採用される periods の embargo_days が J より小さければ
        失敗。T-017 の初回は periods の 1 件目と比べず triggers だけを見ていたので、これが通った。"""
        self.seal_long()
        self.seal_triggers(T0 + H, last_read_offset_days=120)
        self.add_access(T0 + 2 * H, 30_000_000)
        self.verify_fails(("candidates", "all"), "embargo_days 90 が、candidates の J の最大 120")

    def test_b_rebuilt_periods_after_deadline_fails(self):
        """(b)：作り直した periods が threshold-access の後なら採用されないので、失敗。"""
        self.seal_long()
        self.seal_triggers(T0 + H, last_read_offset_days=120)
        self.add_access(T0 + 2 * H, 30_000_000)
        self.rebuilt_periods(T0 + 3 * H)
        self.verify_fails(("candidates", "all"), "embargo_days 90 が")

    def test_a_old_triggers_not_adopted_fails(self):
        """(a)：古い triggers（J 120）があっても、採用される最後の triggers（J 100）が小さければ失敗。
        T-017 の初回は、期限より前のどれかの triggers で通っていた。"""
        self.seal_long()
        self.seal_triggers(T0 + H, last_read_offset_days=120)
        self.rebuilt_periods(T0 + 2 * H)
        # T-027 の差し戻し1回目：書く仕組みは、before_deadline の版と食い違う値を拒むので、飛ばして足す
        with self.assertRaisesRegex(ledger.LedgerError, "before_deadline で、その rebuild_triggers"):
            tl.seal_triggers.seal(self.root, {"last_read_offset_days": 100}, T0 + 3 * H, None)
        self.raw_triggers(T0 + 3 * H, last_read_offset_days=100)
        self.add_access(T0 + 4 * H, 30_000_000)
        self.verify_fails(("candidates",), "seq 5、100")
        # T-031（T-027 の監査 軽3）：all の失敗も文言まで確かめる。all は periods の照合を先にするので、
        # 2 件目（J 120 の版）の申告が採用された triggers（J 100）と一致しないことで止まる
        self.verify_fails(("all",), "2 件目: before_deadline と申告しているが")

    def test_triggers_after_deadline_fails(self):
        self.seal_long()
        self.add_access(T0 + H, 30_000_000)
        self.seal_triggers(T0 + 2 * H, last_read_offset_days=120)
        self.rebuilt_periods(T0 + 3 * H)
        self.verify_fails(("candidates",), "embargo_days 90 が")
        self.assertEqual(run_verify(self.root, "all").returncode, 1)

    def test_adopted_triggers_and_periods_pass(self):
        self.seal_long()
        trec = self.seal_triggers(T0 + H, last_read_offset_days=120)
        prec = self.rebuilt_periods(T0 + 2 * H)
        self.step3(T0 + 3 * H)
        rec, _rel, _o = self.method(T0 + 5 * H)
        out = self.verify_ok("candidates")
        self.assertIn("method-access（seq %d）の時点で採用される periods（seq %d）の embargo_days 120 "
                      "= max(1 件目の embargo_days, J の最大)。periods-triggers：seq %d、"
                      "last_read_offset_days 120（= J の最大）"
                      % (rec["seq"], prec["seq"], trec["seq"]), out)
        self.verify_ok("all")
        self.method_gate()
        arec, _r, _o = self.access(T0 + 6 * H)
        self.verify_ok("all")
        self.threshold_gate()

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


class NoCall:
    """呼ばれたら記録する runner・drand・ヘッダの取得の代わり（呼ばれないことを確かめる）。"""

    def __init__(self):
        self.calls = []

    def __call__(self, *a, **k):
        self.calls.append(a)
        raise AssertionError("書く前に止まるはずなのに、外部の手順が呼ばれた: %r" % (a,))


class TestEveryWriterRefusesLinks(t14.Case):
    """sealed/ に書くすべての仕組みが、sealed/ や ledger.jsonl のリンクで何も書かずに止まる。

    差し戻し1回目の中1（書く仕組みの一部にしか検査が無かった）と軽1（プロジェクトの中の別の
    場所を指すリンクが通った）。三つの置き方それぞれで、すべての書く仕組みを試し、
    (1) LedgerError で止まる、(2) プロジェクトの中にも外にも、1 バイトも書かれない、
    (3) ots・drand・ヘッダの取得が呼ばれない、ことを確かめる。
    """

    LAYOUTS = ("sealed-outside", "sealed-inside-other", "ledger-outside")

    def setUp(self):
        super().setUp()
        self.outside = tempfile.mkdtemp()
        self.seal()
        self.step3(T0 + H)

    def tearDown(self):
        shutil.rmtree(self.outside)
        super().tearDown()

    def link(self, layout):
        if layout == "sealed-outside":
            dst = os.path.join(self.outside, "sealed")
            shutil.move(self.sealed, dst)
            os.symlink(dst, self.sealed)
        elif layout == "sealed-inside-other":
            dst = os.path.join(self.root, "elsewhere")
            shutil.move(self.sealed, dst)
            os.symlink(dst, self.sealed)
        else:
            dst = os.path.join(self.outside, "ledger.jsonl")
            shutil.move(self.ledger, dst)
            os.symlink(dst, self.ledger)

    def tree(self):
        out = {}
        for base in (self.root, self.outside):
            for dirpath, dirs, files in os.walk(base):
                for name in dirs + files:
                    full = os.path.join(dirpath, name)
                    if os.path.islink(full):
                        out[full] = ("link", os.readlink(full))
                    elif os.path.isfile(full):
                        with open(full, "rb") as f:
                            out[full] = f.read()
                    else:
                        out[full] = "dir"
        return out

    def writers(self):
        now = T0 + 5 * H
        nc = NoCall()
        data = ledger.read_ledger(self.ledger) if os.path.exists(self.ledger) else b""
        doc = tl.drand_doc(ledger.THRESHOLD_ACCESS_KIND, 30_000_000)
        return nc, [
            ("ledger.append_record", lambda: ledger.append_record(
                self.ledger, ledger.TRIGGERS_KIND, [tl.target("x")], "", now)),
            ("ledger.write_once", lambda: ledger.write_once(
                os.path.join(self.sealed, "x.json"), b"x")),
            ("stamp.stamp_seq", lambda: tl.stamp.stamp_seq(self.ledger, 1, "ots", runner=nc)),
            ("stamp.upgrade_seq", lambda: tl.stamp.upgrade_seq(self.ledger, 1, "ots", runner=nc)),
            ("seal_bitcoin.confirm", lambda: seal_bitcoin.confirm(self.root, 1, "ots", nc,
                                                                  runner=nc)),
            ("seal_bitcoin.write_header", lambda: seal_bitcoin.write_header(self.root, 900123, nc)),
            ("seal_triggers.seal", lambda: tl.seal_triggers.seal(
                self.root, {"last_read_offset_days": 120}, now, "ots", runner=nc)),
            ("seal_periods.seal", lambda: tl.seal_periods.seal(self.root, self.out_sha, [], now,
                                                                "ots", runner=nc)),
            ("seal_candidates.seal", lambda: seal_candidates.seal(
                self.root, "0" * 64, now, "ots", runner=nc, require_committed=False)),
            ("seal_records.write_doc_record", lambda: seal_records.write_doc_record(
                self.root, ledger.THRESHOLD_ACCESS_KIND, doc, data, "", now, "ots", runner=nc)),
            ("seal_access.seal", lambda: seal_access.seal(self.root, now, "ots", drand_fetch=nc,
                                                          runner=nc)),
            ("seal_acquisition.start", lambda: seal_acquisition.start(
                self.root, tw.CODE_REL, now, "ots", drand_fetch=nc, runner=nc)),
            ("seal_acquisition.result", lambda: seal_acquisition.result(
                self.root, 3, "e" * 64, now, "ots", runner=nc)),
            ("seal_method.seal", lambda: seal_method.seal(self.root, now, "ots", drand_fetch=nc,
                                                          runner=nc)),
        ]

    def test_every_writer_refuses_every_layout(self):
        for layout in self.LAYOUTS:
            self.link(layout)
            nc, writers = self.writers()
            self.assertEqual(len(writers), 14)
            for name, fn in writers:
                with self.subTest(layout=layout, writer=name):
                    before = self.tree()
                    with self.assertRaisesRegex(ledger.LedgerError, "実体"):
                        fn()
                    self.assertEqual(self.tree(), before)
            self.assertEqual(nc.calls, [], layout)
            self.unlink(layout)

    def unlink(self, layout):
        """リンクを外して元に戻す（同じ仮のプロジェクトで次の置き方を試すため）。"""
        if layout == "ledger-outside":
            os.remove(self.ledger)
            shutil.move(os.path.join(self.outside, "ledger.jsonl"), self.ledger)
            return
        target = os.readlink(self.sealed)
        os.remove(self.sealed)
        shutil.move(target, self.sealed)

    def test_writers_work_without_links(self):
        """リンクが無ければ、同じ仕組みで書ける（止まる理由がリンクであることの対照）。"""
        rec, _rel, _o = self.access(T0 + 5 * H)
        self.assertEqual(rec["kind"], ledger.THRESHOLD_ACCESS_KIND)
        self.seal_triggers(T0 + 6 * H, last_read_offset_days=120)

    def test_link_inside_project_refused_by_check(self):
        """軽1：プロジェクトの中の別のフォルダを指す sealed/ も拒む。"""
        self.link("sealed-inside-other")
        with self.assertRaisesRegex(ledger.LedgerError, "sealed/ の実体"):
            ledger.check_sealed_inside(self.root)
        with self.assertRaisesRegex(ledger.ThresholdAccessRequired, "sealed/ の実体"):
            self.threshold_gate()
        self.verify_fails(("chain", "all"), "sealed/ の実体")

    def test_link_of_a_single_file_refused(self):
        """sealed/ の中の書く先のファイルが外へのリンクなら、write_once は書かない。"""
        target = os.path.join(self.outside, "x.json")
        os.symlink(target, os.path.join(self.sealed, "x.json"))
        with self.assertRaisesRegex(ledger.LedgerError, "実体"):
            ledger.write_once(os.path.join(self.sealed, "x.json"), b"x")
        self.assertFalse(os.path.exists(target))
        os.remove(os.path.join(self.sealed, "x.json"))

    def test_path_outside_sealed_refused(self):
        with self.assertRaisesRegex(ledger.LedgerError, "sealed/ の中のファイルではない"):
            ledger.write_once(os.path.join(self.root, "x.json"), b"x")
        self.assertFalse(os.path.exists(os.path.join(self.root, "x.json")))


class TestHeadersRequired(t14.Case):
    """差し戻し1回目の軽2：.ots に Bitcoin の証明がある高さのヘッダが無ければ、検証は失敗する。"""

    def confirmed(self):
        self.seal()
        up = tw.FakeUpgrade(height=900123)
        dst = tl.stamp.upgrade_seq(self.ledger, 1, "ots", runner=up)
        return dst

    def test_missing_header_fails(self):
        self.confirmed()
        self.verify_fails(("anchors", "all"), "高さ 900123 の Bitcoin の証明が .ots の中にあるが、"
                                              "そのヘッダが無い")

    def test_removing_placed_header_fails(self):
        """置いたヘッダを外すと、確定時刻を黙って変えたり保留にしたりせず、失敗する。"""
        self.confirmed()
        data = ledger.read_ledger(self.ledger)
        hdr = tl.mine_header(tw.tip_for_digest(bytes.fromhex(ledger.prefix_digest(data, 1))),
                             T0 + H)
        path = os.path.join(self.sealed, seal_bitcoin.header_name(900123))
        with open(path, "w") as f:
            f.write(hdr.hex() + "\n")
        # テストのヘッダは易しい目標値で掘るので、作業量の下限だけを下げた同じプロセスの検証を使う。
        code, out, err = tl.run_verify_inproc(self.root, "all")
        self.assertEqual(code, 0, err)
        self.assertIn("seq 1: Bitcoin で確定", out)
        os.rename(path, os.path.join(self.root, "removed.hex"))
        code, out, err = tl.run_verify_inproc(self.root, "all")
        self.assertEqual(code, 1)
        self.assertIn("そのヘッダが無い", err)
        self.assertNotIn("seq 1: Pending", out)
        code, out, err = tl.run_verify_inproc(self.root, "all", "--btc-header",
                                              "900123=" + hdr.hex())
        self.assertEqual(code, 0, err)


# ---------------------------------------------------------------- 3. 手順書（軽3・軽4、T-017）


class TestDocT017(unittest.TestCase):
    def setUp(self):
        with open(DOC, encoding="utf-8") as f:
            self.text = f.read()

    def test_manifest_statement_is_factual(self):
        self.assertNotIn("マニフェスト（`data/manifest/`）と、その時刻証明で確かめる", self.text)
        # T-066：gkg-run-result でマニフェストに時刻証明を付けられるようになったので、文言を今の形に直した
        self.assertIn("マニフェスト（`data/manifest/`）には、T-066 までは OpenTimestamps の時刻証明が付いていなかった",
                      self.text)
        self.assertIn("`gkg-run-result` の記録でマニフェストの先頭の行を縛れる", self.text)
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

    def test_resubmission_statements(self):
        """差し戻し1回目の中1・中2・軽1・軽2・軽3 の記述。"""
        for phrase in ("`ledger.check_sealed_path`", "`TestEveryWriterRefusesLinks`",
                       "プロジェクトの中の別のフォルダを指すリンクも拒む",
                       "その時点で採用される版", "ヘッダが無い高さがあれば、検証は失敗する",
                       "drand の署名（BLS）を確かめた場合に限る"):
            self.assertIn(phrase, self.text)

    def test_access_statement(self):
        self.assertIn("最初の `threshold-access` より前に `candidates` の記録があること", self.text)


if __name__ == "__main__":
    unittest.main()
