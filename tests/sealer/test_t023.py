"""T-017 の再提出1回目の監査（中1、軽1〜軽4）への対応のテスト。T-023。

実行（プロジェクトのルートで）:
    PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest discover -s tests/sealer -v

ネットワークは使わない（drand・ots は偽物）。仮のプロジェクトで動かし、本物の sealed/ には
書かない。各項目について、わざと壊して止まることと、壊さなければ通ることの両方を確かめる。
  1. 中1：J を持つ periods-triggers は最初の method-access より前に限る。採用される
     periods-triggers の J（null でなければ）は candidates の J の最大と等しい。採用される
     periods の embargo_days は max(1 件目の embargo_days, J の最大) と等しい。
     監査の再現 P2・P2b を含め、verify・両方の関門・書く仕組みで止まる。
  2. 軽1：--rev で選んだコミットの sealed/ の .bitcoin.ots とヘッダが、作業ツリーにも要る。
  3. 軽3：書く先の ledger.jsonl がハードリンクなら、書く仕組みは止まる。
  4. 軽2・軽3・軽4：手順書の記述。
"""

import datetime
import os
import re
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import test_ledger as tl  # noqa: E402
import test_t017 as t17  # noqa: E402
import test_writers as tw  # noqa: E402
from test_ledger import T0, H, run_verify  # noqa: E402

ledger = tl.ledger
import seal_access  # noqa: E402
import seal_bitcoin  # noqa: E402
import seal_triggers  # noqa: E402

DOC = os.path.join(tl.PROJECT, "docs", "verify", "periods-seal.md")
ROUND = 30_000_000


def _strip_parent_tests(cls):
    """TestHorizonEmbargo から受け継ぐ test_ を、このファイルでは走らせない（二重に走らせない）。"""
    for name in dir(t17.TestHorizonEmbargo):
        if name.startswith("test_") and name not in cls.__dict__:
            setattr(cls, name, None)
    return cls


@_strip_parent_tests
class JCase(t17.TestHorizonEmbargo):
    """TestHorizonEmbargo の道具（seal・step3・method・seal_long・rebuilt_periods など）を使う。
    親のテストを二重に走らせないよう、下の各クラスは test_ で始まる親のメソッドを持たない形にする。"""

    def raw_triggers(self, now, **values):
        """periods-triggers を、書く仕組みを通さずに足す（書く仕組みを飛ばした場合の再現）。"""
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

    def write_access(self, now):
        return seal_access.seal(self.root, now, "ots", drand_fetch=tw.FakeDrand(now),
                                runner=tw.FakeOts())

    def assert_writer_refuses(self, fn, msg):
        before, data = self.snapshot(), self.ledger_bytes()
        with self.assertRaisesRegex(ledger.LedgerError, re.escape(msg)):
            fn()
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.ledger_bytes(), data)

    def assert_gates_stop(self, msg, threshold=True, method=True):
        if method:
            with self.assertRaisesRegex(ledger.MethodAccessRequired, msg):
                self.method_gate()
        if threshold:
            with self.assertRaisesRegex(ledger.ThresholdAccessRequired, msg):
                self.threshold_gate()


# ---------------------------------------------------------------- 1. 中1：監査の再現 P2・P2b


class TestAuditP2(JCase):
    """T-017 の再提出1回目の監査の再現（scratchpad/au17r1/probe/test_c.py の P2、test_c2.py の P2b）。
    T-017 の時点ではどちらも verify が終了コード 0 で通った。今は失敗しなければならない。"""

    def test_p2_j_trigger_after_method_access(self):
        """P2：作り直しの要らない候補（J の最大 28、embargo 90）のまま、method-access の後に
        J 200 の periods-triggers を足す。"""
        self.seal()
        self.step3(T0 + H)
        self.method(T0 + 3 * H)
        # 書く仕組みは J を拒む（何も書かない）
        self.assert_writer_refuses(
            lambda: seal_triggers.seal(self.root, {"last_read_offset_days": 200}, T0 + 4 * H, None),
            "method-access の記録（seq 5）がある")
        # 書く仕組みを飛ばして足した場合
        trg = self.raw_triggers(T0 + 4 * H, last_read_offset_days=200)
        want = "periods-triggers（seq %d）が J（last_read_offset_days 200）を持ち、最初の " \
               "method-access（seq 5）より後にあるが、candidates の J の最大 28 と等しくない" % trg
        self.verify_fails(("candidates", "all"), want)
        self.assert_gates_stop("最初の method-access", threshold=False)
        self.assert_writer_refuses(lambda: self.write_access(T0 + 5 * H), "最初の method-access")
        self.assert_writer_refuses(lambda: self.method(T0 + 5 * H), "最初の method-access")
        # 監査の再現のとおり threshold-access も（書く仕組みを飛ばして）足す
        self.add_access(T0 + 5 * H, ROUND)
        self.verify_fails(("candidates", "all"), want)
        self.assert_gates_stop("最初の method-access")

    def test_p2b_rebuilt_embargo_after_method_access(self):
        """P2b：同じ候補で、method-access の後に J 120 の periods-triggers と、エンバーゴを 120 に
        した periods を足す。T-017 の時点では threshold-access の書く仕組みと関門まで通った。"""
        self.seal()
        self.step3(T0 + H)
        self.method(T0 + 3 * H)
        self.assert_writer_refuses(
            lambda: seal_triggers.seal(self.root, {"last_read_offset_days": 120}, T0 + 4 * H, None),
            "method-access の記録（seq 5）がある")
        self.raw_triggers(T0 + 4 * H, last_read_offset_days=120)
        self.rebuilt_periods(T0 + 5 * H)
        self.verify_fails(("candidates", "all"), "最初の method-access（seq 5）より後にある")
        self.assert_gates_stop("最初の method-access", threshold=False)
        self.assert_writer_refuses(lambda: self.write_access(T0 + 6 * H), "最初の method-access")
        self.add_access(T0 + 6 * H, ROUND)
        self.verify_fails(("candidates", "all"), "最初の method-access（seq 5）より後にある")
        self.assert_gates_stop("最初の method-access")

    def test_p2b_values_alone_also_fail(self):
        """P2b の値そのもの（J 120 の triggers と embargo 120 の periods。候補の J の最大は 28）は、
        method-access より前に置いても、値の照合で失敗する（位置の照合に頼らない）。"""
        self.seal()
        self.raw_triggers(T0 + H / 2, last_read_offset_days=120)
        self.rebuilt_periods(T0 + H)
        self.step3(T0 + 2 * H)
        self.assert_writer_refuses(lambda: self.method(T0 + 4 * H), "と等しくない")
        self.add_method(T0 + 4 * H, ROUND)
        self.verify_fails(("candidates", "all"), "embargo_days 120 が、max(periods の 1 件目の "
                                                 "embargo_days 90, candidates の J の最大 28) = 90 と等しくない")
        self.assert_gates_stop("と等しくない", threshold=False)


# ---------------------------------------------------------------- 1. 中1：値の照合


class TestJEquality(JCase):
    def test_too_large_j_before_method_fails(self):
        """作り直しが要らない場合でも、採用される triggers の J が候補の J の最大より大きければ失敗。
        T-017 の時点では通った（監査 中1 の「大きすぎる J も通す」）。"""
        self.seal()
        self.seal_triggers(T0 + H / 2, last_read_offset_days=40)
        self.step3(T0 + H)
        self.assert_writer_refuses(lambda: self.method(T0 + 3 * H),
                                   "last_read_offset_days 40 が、candidates の J の最大 28 と等しくない")
        self.assert_writer_refuses(lambda: self.write_access(T0 + 3 * H), "40 が")
        self.add_method(T0 + 3 * H, ROUND)
        self.verify_fails(("candidates", "all"), "last_read_offset_days 40 が、candidates の J の最大 28 と"
                                                 "等しくない")
        self.assert_gates_stop("40 が", threshold=False)

    def test_too_large_j_when_rebuild_needed_fails(self):
        """作り直しが要る場合（J の最大 120）も、大きすぎる J（150）は失敗。"""
        self.seal_long()
        self.seal_triggers(T0 + H, last_read_offset_days=150)
        self.rebuilt_periods(T0 + 2 * H)
        self.add_access(T0 + 3 * H, ROUND)
        self.verify_fails(("candidates",), "last_read_offset_days 150 が、candidates の J の最大 120 と"
                                           "等しくない")

    def test_equal_j_before_method_passes(self):
        """J の最大と等しい J を method-access の前に置けば、すべて通る。method-access の後の
        J の無い triggers（共起の網の日数）は、書く仕組みも検証も拒まない。"""
        self.seal()
        trec = self.seal_triggers(T0 + H / 2, last_read_offset_days=28)
        self.step3(T0 + H)
        rec, _rel, _o = self.method(T0 + 3 * H)
        self.seal_triggers(T0 + 4 * H, network_window_days=500)
        out = self.verify_ok("candidates")
        self.assertIn("method-access（seq %d）の時点で採用される periods（seq 1）の embargo_days 90 = "
                      "max(1 件目の embargo_days, J の最大)。periods-triggers：seq %d、"
                      "last_read_offset_days 28（= J の最大）" % (rec["seq"], trec["seq"]), out)
        self.assertIn("最初の method-access より後の periods-triggers の J は、null か J の最大と等しい",
                      out)
        self.method_gate()
        self.write_access(T0 + 5 * H)
        self.verify_ok("all")
        self.method_gate()
        self.threshold_gate()

    def test_embargo_extended_without_trigger_fails(self):
        """きっかけの無いエンバーゴの延長（embargo 120、triggers 無し、J の最大 28）は失敗。
        T-017 の時点では「embargo ≥ J の最大」しか見ていなかったので通った。"""
        self.seal()
        self.seal(args=["--e120"], sha=ledger.sha256_hex(
            tl.seal_periods.run_periods(self.root, ["--e120"])), now=T0 + H / 2, with_cand=False)
        self.step3(T0 + H)
        msg = "embargo_days 120 が、max(periods の 1 件目の embargo_days 90, candidates の J の最大 28) = 90"
        self.assert_writer_refuses(lambda: self.method(T0 + 3 * H), msg)
        self.assert_writer_refuses(lambda: self.write_access(T0 + 3 * H), msg)
        self.add_method(T0 + 3 * H, ROUND)
        self.verify_fails(("candidates", "all"), msg)
        self.assert_gates_stop("と等しくない", threshold=False)

    def test_rebuild_needed_but_adopted_j_null_fails(self):
        """作り直しが要るのに、採用される triggers の J が null（ほかのきっかけだけ）なら失敗。"""
        self.seal_long()
        self.seal_triggers(T0 + H, last_read_offset_days=120)
        self.rebuilt_periods(T0 + 2 * H)
        # T-027：書く仕組みはこの追記を拒むので、飛ばして足す
        self.raw_triggers(T0 + 3 * H, network_window_days=500)
        self.add_access(T0 + 4 * H, ROUND)
        self.verify_fails(("candidates",), "seq 5、None")

    def test_j_trigger_after_method_fails_unless_equal_even_if_not_adopted(self):
        """method-access の後の J を持つ triggers は、threshold-access より後で採用されなくても、
        J の最大と等しくなければ失敗。T-027 で、等しい J（28）は通すことにした（T-023 の監査 軽B）。"""
        self.seal()
        self.step3(T0 + H)
        self.method(T0 + 3 * H)
        self.write_access(T0 + 4 * H)
        self.verify_ok("all")
        self.raw_triggers(T0 + 5 * H, last_read_offset_days=28)
        self.verify_ok("all")
        self.method_gate()
        self.threshold_gate()
        trg = self.raw_triggers(T0 + 6 * H, last_read_offset_days=29)
        self.verify_fails(("candidates", "all"),
                          "periods-triggers（seq %d）が J（last_read_offset_days 29）を持ち" % trg)
        self.assert_gates_stop("最初の method-access")

    def test_trigger_writer_allows_j_before_method_and_non_j_after(self):
        self.seal()
        self.seal_triggers(T0 + H / 2, last_read_offset_days=28)       # 書く仕組みを通す
        self.step3(T0 + H)
        self.method(T0 + 3 * H)
        self.seal_triggers(T0 + 4 * H, same_week_years=3)               # J の無いものは通る
        self.seal_triggers(T0 + 5 * H, last_read_offset_days=28, same_week_years=3)  # T-027：等しい J
        self.assert_writer_refuses(
            lambda: seal_triggers.seal(self.root, {"last_read_offset_days": 29,
                                                   "same_week_years": 3}, T0 + 6 * H, None),
            "その後に書ける J（last_read_offset_days）は、candidates の J の最大 28 だけ")

    def test_real_record_passes_new_rules(self):
        """本物の記録：J の最大 56、1 件目の embargo_days 90、periods-triggers 無し、
        method-access 無し。新しい照合に通り、状態は within。"""
        root = tl.PROJECT
        records = ledger.verify_chain(ledger.read_ledger(os.path.join(root, "sealed",
                                                                      "ledger.jsonl")))
        hz = ledger.check_horizon_embargo(
            records, lambda r, role: ledger.read_target_json(root, r, role))
        self.assertEqual((hz["j_max"], hz["embargo_first"], hz["embargo_expected"], hz["status"]),
                         (56, 90, 90, "within"))


# ---------------------------------------------------------------- 2. 軽1：--rev と時刻証明


class TestRevAnchorFiles(t17.TestHeadersRequired):
    """--rev で選んだコミットの sealed/ の .bitcoin.ots とヘッダが、作業ツリーにも要る。"""

    test_missing_header_fails = None
    test_removing_placed_header_fails = None

    def confirmed_committed(self):
        self.confirmed()
        data = ledger.read_ledger(self.ledger)
        hdr = tl.mine_header(tw.tip_for_digest(bytes.fromhex(ledger.prefix_digest(data, 1))),
                             T0 + H)
        self.hdr_path = os.path.join(self.sealed, seal_bitcoin.header_name(900123))
        with open(self.hdr_path, "w") as f:
            f.write(hdr.hex() + "\n")
        self.bit_path = os.path.join(self.sealed, ledger.ots_name(1, bitcoin=True))
        self.commit("確定")
        for rev in ("auto", "HEAD", "working"):
            code, out, err = tl.run_verify_inproc(self.root, "all", "--rev", rev)
            self.assertEqual(code, 0, (rev, err))
            self.assertIn("seq 1: Bitcoin で確定", out)
        return hdr

    def test_removing_both_fails_with_rev(self):
        """監査 軽1：.bitcoin.ots とヘッダをまとめて外すと、--rev working では「Pending」のまま通る
        （限界。手順書に書いた）が、--rev auto と --rev <コミット> では失敗する。"""
        self.confirmed_committed()
        os.rename(self.bit_path, os.path.join(self.root, "moved.bitcoin.ots"))
        os.rename(self.hdr_path, os.path.join(self.root, "moved.hex"))
        code, out, _err = tl.run_verify_inproc(self.root, "all", "--rev", "working")
        self.assertEqual(code, 0)
        self.assertIn("seq 1: Pending", out)
        for rev in ("auto", "HEAD"):
            code, _out, err = tl.run_verify_inproc(self.root, "all", "--rev", rev)
            self.assertEqual(code, 1, rev)
            self.assertIn("ledger.jsonl.seq000001.bitcoin.ots（コミット", err)
            self.assertIn("bitcoin-header-900123.hex（コミット", err)
            self.assertIn("作業ツリーに無い", err)
            code, _out, err = tl.run_verify_inproc(self.root, "targets", "--rev", rev)
            self.assertEqual(code, 1, rev)

    def test_removed_in_a_later_commit_still_fails_with_auto(self):
        """外したことをコミットしても、--rev auto は失敗する（T-027 からは、消したコミットが履歴に
        あることで失敗する。--rev HEAD でも同じ）。"""
        self.confirmed_committed()
        os.rename(self.bit_path, os.path.join(self.root, "moved.bitcoin.ots"))
        os.rename(self.hdr_path, os.path.join(self.root, "moved.hex"))
        self.commit("外した")
        for rev in ("auto", "HEAD"):
            code, _out, err = tl.run_verify_inproc(self.root, "all", "--rev", rev)
            self.assertEqual(code, 1, rev)
            self.assertIn("sealed/ の時刻証明・ヘッダを消したコミットが履歴にある", err)

    def test_changed_content_fails(self):
        """中身を変えたもの（ヘッダの行に空白を足す。ヘッダとしては同じ値に読める）も失敗する。"""
        self.confirmed_committed()
        with open(self.hdr_path, "a") as f:
            f.write("\n")
        code, _out, _err = tl.run_verify_inproc(self.root, "all", "--rev", "working")
        self.assertEqual(code, 0)
        code, _out, err = tl.run_verify_inproc(self.root, "all", "--rev", "auto")
        self.assertEqual(code, 1)
        self.assertIn("作業ツリーの中身が、コミット", err)

    def test_symlinked_file_fails(self):
        """作業ツリーのヘッダを、同じ中身の別のファイルへのシンボリックリンクにしても失敗する。"""
        self.confirmed_committed()
        moved = os.path.join(self.root, "elsewhere.hex")
        os.rename(self.hdr_path, moved)
        os.symlink(moved, self.hdr_path)
        code, _out, err = tl.run_verify_inproc(self.root, "all", "--rev", "auto")
        self.assertEqual(code, 1)
        self.assertIn("作業ツリーに無い", err)

    def test_passes_and_reports_count(self):
        self.confirmed_committed()
        code, out, err = tl.run_verify_inproc(self.root, "all", "--rev", "auto")
        self.assertEqual(code, 0, err)
        # seq 1 の .ots・.bitcoin.ots、seq 2（candidates）の .ots、ヘッダ 1 つ
        self.assertIn("--rev auto で選んだコミットの sealed/ にある時刻証明（.ots・.bitcoin.ots）と"
                      "ヘッダ 4 件は、作業ツリーにも同じ中身である", out)


# ---------------------------------------------------------------- 3. 軽3：ハードリンク


class TestHardLink(t17.t14.Case):
    def test_writers_refuse_hardlinked_ledger(self):
        self.seal()
        other = os.path.join(self.root, "ledger-copy.jsonl")   # sealed/ の外の、別の名前
        os.link(self.ledger, other)
        try:
            before = self.ledger_bytes()
            with self.assertRaisesRegex(ledger.LedgerError, "リンク数が 2"):
                seal_triggers.seal(self.root, {"same_week_years": 3}, T0 + H, None)
            with self.assertRaisesRegex(ledger.LedgerError, "リンク数が 2"):
                ledger.append_record(self.ledger, ledger.TRIGGERS_KIND, [tl.target("a/x")], "",
                                     T0 + H)
            with self.assertRaisesRegex(ledger.LedgerError, "リンク数が 2"):
                self.start(T0 + H)
            self.assertEqual(self.ledger_bytes(), before)
            with open(other, "rb") as f:
                self.assertEqual(f.read(), before)
            # 検証は同じ実体のバイト列を読むので、結論は変わらない（限界として手順書に書いた）
            self.verify_ok("all")
        finally:
            os.rename(other, os.path.join(self.sealed, "..", "unlinked-name.jsonl"))
        self.assertEqual(os.lstat(self.ledger).st_nlink, 2)
        with self.assertRaisesRegex(ledger.LedgerError, "リンク数が 2"):
            seal_triggers.seal(self.root, {"same_week_years": 3}, T0 + H, None)

    def test_writer_works_without_hardlink(self):
        self.seal()
        self.assertEqual(os.lstat(self.ledger).st_nlink, 1)
        seal_triggers.seal(self.root, {"same_week_years": 3}, T0 + H, None)


# ---------------------------------------------------------------- 4. 手順書


class TestDocT023(unittest.TestCase):
    def setUp(self):
        with open(DOC, encoding="utf-8") as f:
            self.text = f.read()

    def test_j_rules(self):
        for phrase in ("`method-access` の後の `periods-triggers` の J は、null か J の最大と等しい値に限る",
                       "E = max(`periods` の1件目の `embargo_days`, J の最大)",
                       "小さすぎる値も、大きすぎる値も拒む", "`TestAuditP2`",
                       "`--last-read-offset-days 56`"):
            self.assertIn(phrase, self.text)
        self.assertNotIn("その `last_read_offset_days` が J の最大より小さい。`periods-triggers` を"
                         "求めるのは", self.text)

    def test_rev_statement(self):
        self.assertIn("時刻証明とヘッダが作業ツリーから外されていないこと", self.text)
        self.assertIn("`--rev working`（既定）では確かめない", self.text)

    def test_root_statement(self):
        """軽2：「<プロジェクト>/sealed/ の中でないパスにも書かない」は言い過ぎなので直した。"""
        self.assertNotIn("`<プロジェクト>/sealed/` の中でないパスにも書かない", self.text)
        self.assertIn("書く先は、渡したルートの `sealed/` の中に限る", self.text)

    def test_hardlink_statement(self):
        self.assertIn("ハードリンクの限界", self.text)
        self.assertIn("`st_nlink`", self.text)

    def test_light4_statements(self):
        self.assertIn("「T より後に作られた」は drand の署名（BLS）を確かめた場合に限る", self.text)
        self.assertIn("`upgrade` のあとに `header` を続けて実行する", self.text)
        self.assertIn("用意しない高さが一つでもあれば、検証は失敗する", self.text)
        self.assertNotIn("`--ots-dir` を付けて検証する。必要ならヘッダも渡す。", self.text)


if __name__ == "__main__":
    unittest.main()
