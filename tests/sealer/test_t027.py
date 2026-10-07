"""T-023 の監査（軽A・軽B）への対応のテスト。T-027。

実行（プロジェクトのルートで）:
    PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest discover -s tests/sealer -v

ネットワークは使わない（drand・ots は偽物）。仮のプロジェクト（git init したもの）で動かし、
本物の sealed/ には書かない。
  1. 軽A：--rev auto は、マージコミットで足した .bitcoin.ots とヘッダも集める。HEAD の履歴に、
     時刻証明かヘッダを消したコミット（マージ・名前の変更を含む）があれば失敗する。
     監査の再現（scratchpad/au23probe/probe23.py の Merge.test_evil_merge）を含む。
  2. 軽B：作り直しが要る場合、method-access の後でも、J の最大と等しい J と一緒なら、ほかの
     きっかけを追記して threshold-access まで進める（行き詰まらない）。J とエンバーゴは、
     データを見たあとに別の値へ動かせない。監査の再現（Rebuild.test_rebuild_other_trigger_after_method）を含む。
"""

import os
import re
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import test_ledger as tl  # noqa: E402
import test_t023 as t23  # noqa: E402
import test_writers as tw  # noqa: E402
from test_ledger import T0, H, run_verify  # noqa: E402

ledger = tl.ledger
import seal_bitcoin  # noqa: E402
import seal_triggers  # noqa: E402

DOC = os.path.join(tl.PROJECT, "docs", "verify", "periods-seal.md")
ROUND = 30_000_000
REMOVED = "sealed/ の時刻証明・ヘッダを消したコミットが履歴にある"
# 手順書のコマンドの範囲（verify.py の REV_ANCHOR_RE と同じ。差し戻し1回目の軽2）
ANCHOR_GREP = "'^sealed/(ledger\\.jsonl\\.seq[0-9]{6}(\\.bitcoin)?\\.ots|bitcoin-header-[0-9]+\\.hex)$'"


# ---------------------------------------------------------------- 1. 軽A：マージと削除


class TestMergeAndRemoval(t23.TestRevAnchorFiles):
    """マージコミットで足したもの・消したものも、--rev auto の照合に入る。"""

    # 親のテストは test_t023 で走らせる（ここでは二重に走らせない）
    test_removing_both_fails_with_rev = None
    test_removed_in_a_later_commit_still_fails_with_auto = None
    test_changed_content_fails = None
    test_symlinked_file_fails = None
    test_passes_and_reports_count = None

    def branch_point(self):
        """seal して base をコミットし、side の枝を作って main に戻る。"""
        self.seal()
        self.commit("base")
        self.git("checkout", "-qb", "side")
        self.commit("side")
        self.git("checkout", "-q", "-")
        self.commit("main")

    def add_confirmation(self):
        """seq 1 の .bitcoin.ots とヘッダを sealed/ に置く（まだコミットしない）。"""
        tl.stamp.upgrade_seq(self.ledger, 1, "ots", runner=tw.FakeUpgrade(height=900123))
        data = ledger.read_ledger(self.ledger)
        hdr = tl.mine_header(tw.tip_for_digest(bytes.fromhex(ledger.prefix_digest(data, 1))),
                             T0 + H)
        self.hdr_path = os.path.join(self.sealed, seal_bitcoin.header_name(900123))
        with open(self.hdr_path, "w") as f:
            f.write(hdr.hex() + "\n")
        self.bit_path = os.path.join(self.sealed, ledger.ots_name(1, bitcoin=True))

    def evil_merge(self):
        """監査の再現：マージコミットの中で .bitcoin.ots とヘッダを足す。"""
        self.branch_point()
        self.add_confirmation()
        self.git("merge", "-q", "--no-commit", "side")
        self.commit("evil merge adds bitcoin.ots + header")
        code, out, err = tl.run_verify_inproc(self.root, "all", "--rev", "auto")
        self.assertEqual(code, 0, err)
        self.assertIn("seq 1: Bitcoin で確定", out)

    def move_out(self):
        os.rename(self.bit_path, os.path.join(self.root, "moved.bitcoin.ots"))
        os.rename(self.hdr_path, os.path.join(self.root, "moved.hex"))

    def test_evil_merge_then_uncommitted_removal_fails(self):
        """probe23.py の Merge.test_evil_merge の前半。T-023 の版では --rev auto が終了コード 0 で、
        seq 1 が Pending と表示された。"""
        self.evil_merge()
        self.move_out()
        code, out, _err = tl.run_verify_inproc(self.root, "all", "--rev", "working")
        self.assertEqual(code, 0)              # 限界（手順書）：--rev working は照合しない
        self.assertIn("seq 1: Pending", out)
        for rev in ("auto", "HEAD"):
            code, _out, err = tl.run_verify_inproc(self.root, "all", "--rev", rev)
            self.assertEqual(code, 1, rev)
            self.assertIn("ledger.jsonl.seq000001.bitcoin.ots（コミット", err)
            self.assertIn("作業ツリーに無い", err)

    def test_evil_merge_then_committed_removal_fails(self):
        """probe23.py の後半：外したことをコミットしても失敗（消したコミットが履歴にある）。"""
        self.evil_merge()
        self.move_out()
        self.commit("remove")
        for rev in ("auto", "HEAD"):
            code, _out, err = tl.run_verify_inproc(self.root, "all", "--rev", rev)
            self.assertEqual(code, 1, rev)
            self.assertIn(REMOVED, err)
            self.assertIn("ledger.jsonl.seq000001.bitcoin.ots（コミット", err)
            self.assertIn("bitcoin-header-900123.hex（コミット", err)

    def test_merge_that_drops_files_fails(self):
        """main で足してコミットした .bitcoin.ots とヘッダを、マージコミットの中で消す。
        git log は既定ではマージの差分を出さないので、-m が無いと見つからない。"""
        self.branch_point()
        self.add_confirmation()
        self.commit("確定")
        self.git("merge", "-q", "--no-commit", "side")
        self.git("rm", "-q", "--cached", os.path.relpath(self.bit_path, self.root),
                 os.path.relpath(self.hdr_path, self.root))
        self.move_out()
        self.git("commit", "-q", "-m", "merge drops")
        self.assertTrue(self.git("rev-parse", "-q", "--verify", "HEAD^2").strip())
        code, _out, err = tl.run_verify_inproc(self.root, "all", "--rev", "auto")
        self.assertEqual(code, 1)
        self.assertIn(REMOVED, err)
        # 戻しても、消したコミットは履歴に残るので失敗のまま
        os.rename(os.path.join(self.root, "moved.bitcoin.ots"), self.bit_path)
        os.rename(os.path.join(self.root, "moved.hex"), self.hdr_path)
        self.commit("戻した")
        code, _out, err = tl.run_verify_inproc(self.root, "all", "--rev", "auto")
        self.assertEqual(code, 1)
        self.assertIn(REMOVED, err)

    def test_rename_counts_as_removal(self):
        self.seal()
        self.add_confirmation()
        self.commit("確定")
        self.git("mv", os.path.relpath(self.hdr_path, self.root), "sealed/renamed.hex")
        self.commit("名前を変えた")
        with open(self.hdr_path, "w") as f:          # 作業ツリーには元の名前でも置く
            with open(os.path.join(self.sealed, "renamed.hex")) as g:
                f.write(g.read())
        code, _out, err = tl.run_verify_inproc(self.root, "all", "--rev", "auto")
        self.assertEqual(code, 1)
        self.assertIn(REMOVED, err)

    def test_ordinary_merge_passes(self):
        """改ざんの無いマージ（side は確定より前に分かれた枝）は通る。マージで「足した」と数えられる
        ものも、作業ツリーと同じ中身なので照合に通る。消したとは数えない。"""
        self.branch_point()
        self.add_confirmation()
        self.commit("確定")
        self.git("checkout", "-q", "side")
        with open(os.path.join(self.root, "side.txt"), "w") as f:
            f.write("side\n")
        self.commit("side の変更")
        self.git("checkout", "-q", "-")
        self.git("merge", "-q", "--no-edit", "side")
        self.assertTrue(self.git("rev-parse", "-q", "--verify", "HEAD^2").strip())
        code, out, err = tl.run_verify_inproc(self.root, "all", "--rev", "auto")
        self.assertEqual(code, 0, err)
        self.assertIn("seq 1: Bitcoin で確定", out)

    def test_doc_grep_matches_verify_pattern(self):
        """差し戻し1回目の軽2：手順書のコマンドの範囲が、検証のコードの範囲（REV_ANCHOR_RE）と同じ。"""
        import verify
        pat = re.compile(ANCHOR_GREP.strip("'"))
        names = ["sealed/ledger.jsonl.seq000001.ots", "sealed/ledger.jsonl.seq000001.bitcoin.ots",
                 "sealed/bitcoin-header-970086.hex", "sealed/other.ots", "sealed/x.hex",
                 "sealed/sub/ledger.jsonl.seq000001.ots", "sealed/ledger.jsonl.seq1.ots",
                 "sealed/periods-output-ab.json", "sealed/ledger.jsonl.seq000001.ots.bak"]
        for n in names:
            self.assertEqual(bool(pat.search(n)), bool(verify.REV_ANCHOR_RE.match(n)), n)
        self.assertEqual(_doc_text().count("grep -E " + ANCHOR_GREP), 2)

    def test_doc_commands_agree(self):
        """手順書の、検証のコードを使わないコマンドが、同じ結論を出す（消したコミットを見つける）。"""
        self.evil_merge()
        self.move_out()
        self.commit("remove")
        cmd = ("git log -m --no-renames --diff-filter=D --format=%H --name-only HEAD -- sealed/ "
               "| grep -E " + ANCHOR_GREP)
        self.assertIn(cmd, _doc_text())
        out = subprocess.run(["sh", "-c", cmd], cwd=self.root, capture_output=True).stdout.decode()
        self.assertIn("sealed/ledger.jsonl.seq000001.bitcoin.ots", out)
        self.assertIn("sealed/bitcoin-header-900123.hex", out)


# ---------------------------------------------------------------- 2. 軽B：作り直しと method-access


class TestRebuildAfterMethod(t23.JCase):
    """作り直しが要る（候補の J の最大 120 > 1 件目の embargo 90）場合の、method-access の後の追記。"""

    J_NW = ["--j120", "--nw500", "before_deadline"]

    def to_method(self):
        """J 120 の triggers と、作り直した periods（embargo 120）を method-access の前に置き、
        手順3と method-access まで進める。"""
        self.seal_long()
        self.seal_triggers(T0 + H, last_read_offset_days=120)
        self.rebuilt_periods(T0 + 2 * H)
        self.step3(T0 + 3 * H)
        rec, _rel, _o = self.method(T0 + 5 * H)
        return rec

    def rebuilt_with_network(self, now):
        sha = ledger.sha256_hex(tl.seal_periods.run_periods(self.root, self.J_NW))
        return self.seal(args=self.J_NW, sha=sha, now=now, with_cand=False)

    def test_probe_rebuild_other_trigger_after_method(self):
        """probe23.py の Rebuild.test_rebuild_other_trigger_after_method。T-023 の版では、
        網の日数だけを渡すと受け付けられ、そのあと threshold-access が二度と通らなかった。
        T-027 の初回では J と一緒なら受け付けたが、前の版（J だけで作り直した before_deadline）が
        verify periods で失敗し続けた（差し戻し1回目の中1）。今は、どちらの追記も書く仕組みが拒む。
        前の版と同じ値のままなら、threshold-access まで進め、verify all も通る。"""
        self.to_method()
        self.assert_writer_refuses(
            lambda: seal_triggers.seal(self.root, {"network_window_days": 500}, T0 + 6 * H, None),
            "J が null の periods-triggers は追記しない")
        self.assert_writer_refuses(
            lambda: seal_triggers.seal(self.root, {"last_read_offset_days": 120,
                                                   "network_window_days": 500}, T0 + 6 * H, None),
            "periods の 2 件目（seq 4）が before_deadline で、その rebuild_triggers")
        # 前の版と同じ値（J 120 だけ）を言い直すことは拒まない
        self.seal_triggers(T0 + 6 * H, last_read_offset_days=120)
        arec, _r, _o = self.write_access(T0 + 7 * H)
        out = self.verify_ok("all")
        self.assertIn("threshold-access（seq %d）の時点で採用される periods（seq 4）の embargo_days 120"
                      % arec["seq"], out)
        self.method_gate()
        self.threshold_gate()

    def test_gap_is_stopped_by_writers_and_gate(self):
        """T-027 の初回で開示した形（J だけの版のあとに J と網の日数を足し、作り直す）を、書く仕組みを
        飛ばして作る。verify periods・all は前の版の申告で失敗し、seal_access と threshold-access の
        関門も、verify periods と同じ照合で止まる（差し戻し1回目の中1 (ii)・軽1）。"""
        self.to_method()
        self.raw_triggers(T0 + 6 * H, last_read_offset_days=120, network_window_days=500)
        # T-031：seal_periods も、既にある before_deadline の版と違う版を拒むので、飛ばして足す
        self.assert_periods_writer_refuses(self.J_NW, T0 + 7 * H, "既にある before_deadline の版")
        self.raw_periods(self.J_NW, T0 + 7 * H)
        msg = "2 件目（seq 4）: before_deadline と申告しているが"
        self.assert_writer_refuses(lambda: self.write_access(T0 + 8 * H), msg)
        self.add_access(T0 + 8 * H, ROUND)
        self.verify_fails(("periods", "all"), "2 件目: before_deadline と申告しているが")
        with self.assertRaisesRegex(ledger.ThresholdAccessRequired, re.escape(msg)):
            self.threshold_gate()
        self.verify_ok("candidates")        # J とエンバーゴの照合は通る（食い違いは deadline_status だけ）

    def test_bypassed_null_j_trigger_does_not_dead_end(self):
        """書く仕組みを飛ばして J が null の triggers を足しても、前の版と同じ値（J の最大）の
        triggers を後から足せば、それが採用されて先へ進める（T-023 の監査 軽B の行き詰まりが無い）。"""
        self.to_method()
        self.raw_triggers(T0 + 6 * H, network_window_days=500)
        self.assert_writer_refuses(lambda: self.write_access(T0 + 7 * H), "None")
        self.seal_triggers(T0 + 7 * H, last_read_offset_days=120)
        self.write_access(T0 + 8 * H)
        self.verify_ok("all")
        self.threshold_gate()

    def test_j_cannot_move_after_method(self):
        """データを見たあと（method-access の後）に J を別の値にすることはできない。"""
        self.to_method()
        for j in (119, 121, 150):
            self.assert_writer_refuses(
                lambda: seal_triggers.seal(self.root, {"last_read_offset_days": j,
                                                       "network_window_days": 500}, T0 + 6 * H, None),
                "candidates の J の最大 120 だけ")
        trg = self.raw_triggers(T0 + 6 * H, last_read_offset_days=150)
        msg = ("periods-triggers（seq %d）が J（last_read_offset_days 150）を持ち、最初の method-access"
               % trg)
        self.verify_fails(("candidates", "all"), msg)
        self.assert_gates_stop("150", threshold=False)   # threshold-access はまだ無い
        self.assert_writer_refuses(lambda: self.write_access(T0 + 7 * H), "150")

    def test_embargo_cannot_move_after_method(self):
        """method-access の後に、エンバーゴを別の値にした periods（v1 の形、embargo 90 に戻す）を
        足しても、採用されれば失敗する。"""
        self.to_method()
        self.seal(now=T0 + 7 * H, with_cand=False)       # embargo 90 の periods（戻す）
        msg = "embargo_days 90 が、candidates の J の最大 120 より小さい"
        self.assert_writer_refuses(lambda: self.write_access(T0 + 8 * H), msg)
        self.add_access(T0 + 8 * H, ROUND)
        # 差し戻し1回目の軽1：all の失敗も、文言まで確かめる（ほかの理由の失敗で通らないように）
        self.verify_fails(("candidates", "all"), msg)
        self.verify_ok("periods")
        self.assert_gates_stop(msg, method=False)

    def test_embargo_cannot_be_extended_after_method_in_within_case(self):
        """作り直しの要らない候補（J の最大 28）で、method-access の後に J 28 と一緒にエンバーゴを
        延ばした periods（embargo 120）を足しても、失敗する。"""
        self.seal()
        self.step3(T0 + H)
        self.method(T0 + 3 * H)
        self.seal_triggers(T0 + 4 * H, last_read_offset_days=28, network_window_days=500)
        sha = ledger.sha256_hex(tl.seal_periods.run_periods(self.root, ["--e120"]))
        self.seal(args=["--e120"], sha=sha, now=T0 + 5 * H, with_cand=False)
        msg = "embargo_days 120 が、max(periods の 1 件目の embargo_days 90, candidates の J の最大 28) = 90"
        self.assert_writer_refuses(lambda: self.write_access(T0 + 6 * H), msg)
        self.add_access(T0 + 6 * H, ROUND)
        self.verify_fails(("candidates", "all"), msg)

    def test_null_j_before_method_refused_when_rebuild_needed(self):
        self.seal_long()
        self.assert_writer_refuses(
            lambda: seal_triggers.seal(self.root, {"network_window_days": 500}, T0 + H, None),
            "--last-read-offset-days 120 も渡す")

    def test_null_j_allowed_when_rebuild_not_needed(self):
        self.seal()
        self.step3(T0 + H)
        self.method(T0 + 3 * H)
        self.seal_triggers(T0 + 4 * H, network_window_days=500)
        self.write_access(T0 + 5 * H)
        self.verify_ok("candidates")


# ---------------------------------------------------------------- 2b. 差し戻し1回目の中1 の再現（作り直しの要らない場合）


class TestDeadlineRepro(t23.JCase):
    """監査の再現（scratchpad/au27probe_x/probe_within.py）。J の最大 28（≤ 90。今の本物の記録と
    同じく作り直しは要らない）でも、作り直した版（before_deadline）のあとに、それと違う
    periods-triggers を足すと、前の版が verify periods で失敗し続けた。今は書く仕組みが止める。"""

    def rebuilt(self, args, now):
        sha = ledger.sha256_hex(tl.seal_periods.run_periods(self.root, args))
        return self.seal(args=args, sha=sha, now=now, with_cand=False)

    def first_rebuild(self):
        self.seal()
        self.step3(T0 + H)
        self.method(T0 + 3 * H)
        self.seal_triggers(T0 + 4 * H, network_window_days=500)
        return self.rebuilt(["--nwonly", "before_deadline"], T0 + 5 * H)

    def test_repro1_second_rebuild_refused(self):
        """再現1：網の日数で作り直したあと、同じ週の年数も決めて二度目の作り直しをする。"""
        prec = self.first_rebuild()
        self.assert_writer_refuses(
            lambda: seal_triggers.seal(self.root, {"network_window_days": 500, "same_week_years": 3},
                                       T0 + 6 * H, None),
            "periods の 2 件目（seq %d）が before_deadline で、その rebuild_triggers" % prec["seq"])
        # 飛ばして作った場合：seal_access・関門・verify が止まる
        self.raw_triggers(T0 + 6 * H, network_window_days=500, same_week_years=3)
        self.assert_periods_writer_refuses(["--nwonly", "--sw3", "before_deadline"], T0 + 7 * H,
                                           "既にある before_deadline の版")
        self.raw_periods(["--nwonly", "--sw3", "before_deadline"], T0 + 7 * H)   # T-031
        msg = "2 件目（seq %d）: before_deadline と申告しているが" % prec["seq"]
        self.assert_writer_refuses(lambda: self.write_access(T0 + 8 * H), msg)
        self.add_access(T0 + 8 * H, ROUND)
        self.verify_fails(("periods", "all"), "2 件目: before_deadline と申告しているが")
        with self.assertRaisesRegex(ledger.ThresholdAccessRequired, re.escape(msg)):
            self.threshold_gate()

    def test_repro2_restated_j_refused(self):
        """再現2：作り直しのあとに、手順書の案内どおり J（28）を言い直す。"""
        prec = self.first_rebuild()
        self.assert_writer_refuses(
            lambda: seal_triggers.seal(self.root, {"last_read_offset_days": 28,
                                                   "network_window_days": 500}, T0 + 6 * H, None),
            "periods の 2 件目（seq %d）が before_deadline で、その rebuild_triggers" % prec["seq"])
        self.raw_triggers(T0 + 6 * H, last_read_offset_days=28, network_window_days=500)
        msg = "2 件目（seq %d）: before_deadline と申告しているが" % prec["seq"]
        self.assert_writer_refuses(lambda: self.write_access(T0 + 8 * H), msg)
        self.add_access(T0 + 8 * H, ROUND)
        self.verify_fails(("periods", "all"), "2 件目: before_deadline と申告しているが")
        with self.assertRaisesRegex(ledger.ThresholdAccessRequired, re.escape(msg)):
            self.threshold_gate()

    def test_one_rebuild_passes_and_same_values_allowed(self):
        """作り直し一回なら通る。同じ値の言い直しも拒まない。threshold-access の後の追記は、
        採用されないので拒まない（今までどおり）。"""
        self.first_rebuild()
        self.seal_triggers(T0 + 6 * H, network_window_days=500)
        self.write_access(T0 + 7 * H)
        self.verify_ok("all")
        self.threshold_gate()
        self.seal_triggers(T0 + 8 * H, network_window_days=600)
        self.verify_ok("all")

    def test_before_any_rebuild_any_values_allowed(self):
        """before_deadline の版がまだ無ければ、値の食い違いの検査はしない。"""
        self.seal()
        self.seal_triggers(T0 + H, network_window_days=500)
        self.seal_triggers(T0 + 2 * H, network_window_days=600, same_week_years=3)


# ---------------------------------------------------------------- 3. 手順書


def _doc_text():
    with open(DOC, encoding="utf-8") as f:
        return f.read()


class TestDocT027(unittest.TestCase):
    def setUp(self):
        self.text = _doc_text()

    def test_merge_statement(self):
        for phrase in ("マージコミットも見る（T-027。T-023 の監査 軽A）", "`git log -m`",
                       "消したコミットがあれば失敗する（T-027）"):
            self.assertIn(phrase, self.text)

    def test_choice_statement(self):
        self.assertIn("(a) を選んだ", self.text)
        # 前提 → 結論の形で書いてある
        block = self.text[self.text.index("(a) を選んだ"):]
        block = block[:block.index("`TestRebuildAfterMethod`")]
        self.assertGreaterEqual(len(re.findall("前提：", block)), 4)
        self.assertGreaterEqual(len(re.findall("結論：", block)), 3)

    def test_known_gap_statement(self):
        self.assertIn("未解決（T-027 で報告）", self.text)
        self.assertIn("決まるまでの扱い（T-027 の差し戻し1回目の中1 (ii)", self.text)   # T-031 で見出しに足した
        self.assertIn("今の本物の記録（J の最大 56）でも、正直な流れで入りうる", self.text)
        self.assertIn("T-027 の初回のコミット（58df044）の説明の訂正", self.text)


if __name__ == "__main__":
    unittest.main()
