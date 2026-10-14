"""T-090 のテスト：順番3（数え方とのつながり）の試みの記録（stats-order3-attempt）と順番3の記録（stats-order3）を書く入口
（src/sealer/seal_order3.py）と、それを照らす仕組み（ledger.check_order3_records、verify.check_order3_git・
recompute_order3_gate）。あわせて T-083 の監査の残り（軽-1：seal_order2.check_written の .ots の else の側、軽-2：
stats-order2 の targets がちょうど1つ）。

実行（プロジェクトのルートで）:
    PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -B -m unittest discover -s tests/sealer -v

書くのは、仮のプロジェクト（test_t078.Synth・test_writers.WriterCase）と、本物の記録の固定したコミット
（fixed_records.ORDER2_COMMIT。seq 1〜10）の clone の中だけ。ots は偽物。本物の sealed/・data/ には書かない。順番3を本物の
記録で実行しない。ネットワークと LACIE SHARE には触れない。統計係の文書 docs/stats/seal-order3.md は、仮のプロジェクトと
clone の中にだけ、テストの中身で置く。封印した版の src/stats/counting.py は、固定したコミットから git で取り出したもの
（test_t078.SEALED_COUNTING）を、仮のプロジェクトの履歴に置く。
"""

import contextlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import fixed_records  # noqa: E402
import test_ledger as tl  # noqa: E402
import test_t078 as t78  # noqa: E402
import test_t083 as t83  # noqa: E402
import test_writers as tw  # noqa: E402
from test_ledger import T0, H  # noqa: E402

ledger = tl.ledger
verify = tl.verify
import seal_order2  # noqa: E402
import seal_order3  # noqa: E402
import seal_records  # noqa: E402

A3 = ledger.ORDER3_ATTEMPT_KIND
O3 = ledger.ORDER3_KIND
O2 = ledger.ORDER2_KIND
READING = ledger.ORDER3_READING_DOC
READING_TEXT = "# 順番3（テストの仮の文書）\n\nC7 では、K は「記事の数で、全体の報道量が中央値の日に1日あたり K 本」と読む。\n"
DOC = os.path.join(tl.PROJECT, "docs", "verify", "periods-seal.md")
WHO = "%s <%s>" % (seal_order2.AUTHOR_NAME, seal_order2.AUTHOR_EMAIL)

R_NO_O2 = "参照する順番1b の記録に対する順番2の記録が無い"
R_TIMING = "(a) 参照する順番1b の記録が時機の条件を満たさない（順番3の時点で確かめ直した）"
R_PERM = "(a) 前の順番3の試みで、時機の条件の破れが記録されている（恒久に止まる）"
R_O2A = "(a) 時機の条件で止まった順番2の記録がある"
GATE_DIFF = re.escape("gate が、封印した版の order3_gate() を記録から計算し直した結果と違う")


def write_reading(root):
    path = os.path.join(root, *READING.split("/"))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(READING_TEXT)


def rehead(doc, head):
    """作り物の試みの中身の head を head にし、読んだ参照・list-heads・timing_check・gate を、それに合う形にそろえる
    （worktree の HEAD は head の1つ）。"""
    refs = doc["refs_read"]["refs"]
    out = dict(doc, head=head, refs_read={"head": head, "refs": refs, "worktree_heads": [head]},
               bundle_heads=[{"name": r["ref"], "commit": r["commit"]} for r in refs] + [{"name": "HEAD", "commit": head}])
    if doc["timing_check"] is not None:
        out["timing_check"] = dict(doc["timing_check"], head=head, worktree_heads=[head])
    if doc["gate"] is not None:
        out["gate"] = dict(doc["gate"], timing_check=out["timing_check"])
    return out


def order3_blocks():
    with open(DOC, encoding="utf-8") as f:
        return re.findall(r"<!-- test:order3 -->\n```sh\n(.*?)```", f.read(), re.S)


class O3Case(t78.Synth):
    """順番2の手前（R の gkg-run-result まで）に、統計係の文書（テストの仮のもの）をコミットした仮のプロジェクト。"""

    def setUp(self):
        super().setUp()
        write_reading(self.root)
        self.commit("順番3の文書（テストの仮のもの）")

    def o2(self, store=None):
        """順番2の試みを書く（入口がコミットする）。返り値: (記録, 中身)。"""
        rec, _rel, _o, doc = self.write(None if store is None else {"trial": store, "official": None})
        return rec, doc

    def attempt(self, runner=None):
        with mock.patch.object(ledger, "PROJECT_ROOT", self.root):
            return seal_order3.seal(self.bundle_path(), self.tick(), "ots", runner=runner or tw.FakeOts())

    def build_attempt(self):
        data = self.ledger_bytes()
        return seal_order3.build_attempt(self.root, data, ledger.verify_chain(data), self.bundle_path())

    def gate(self, out):
        return out["attempt"][3]["gate"]

    def remove_branch(self, name="side"):
        self.git("branch", "-D", name)

    def raw(self, kind, doc, targets_extra=None):
        """書く仕組みの照合（check_new）を飛ばして足し、コミットする（作り物の記録）。"""
        with mock.patch.object(seal_records, "check_new", lambda *a, **k: None):
            rec, _rel, _o = seal_records.write_doc_record(self.root, kind, doc, self.ledger_bytes(), "作り物（テスト）",
                                                          self.tick(), "ots", runner=tw.FakeOts())
        self.commit("作り物の %s（テスト）" % kind)
        return rec

    def refuses(self, kind, doc, text):
        """書く仕組みは何も書かない。"""
        before = self.ledger_bytes()
        with self.assertRaisesRegex(ledger.LedgerError, text):
            seal_records.write_doc_record(self.root, kind, doc, before, "作り物（テスト）", self.tick(), "ots",
                                          runner=tw.FakeOts())
        self.assertEqual(self.ledger_bytes(), before)

    def forged(self, kind, doc, text):
        self.refuses(kind, doc, text)
        self.raw(kind, doc)
        self.verify_stops(text, "all")

    def next_head(self, doc):
        """作り物の中身の ledger_head・head を、今の記録と HEAD に合わせる。"""
        return dict(doc, ledger_head=ledger.expected_ledger_head(self.ledger_bytes(), len(self.records()) + 1),
                    head=self.head())


# ---------------------------------------------------------------- 1. 通った場合

class TestPass(O3Case):
    def test_pass_writes_attempt_and_order3(self):
        r2, d2 = self.o2()
        self.assertEqual(d2["status"], "decided")
        out = self.attempt()
        arec, _arel, aots, adoc, acommit = out["attempt"]
        self.assertEqual(arec["kind"], A3)
        self.assertEqual(sorted(adoc), sorted(ledger.ORDER3_ATTEMPT_KEYS))
        g = adoc["gate"]
        self.assertEqual(sorted(g), sorted(ledger.ORDER3_GATE_KEYS))
        self.assertEqual((g["may_seal"], g["reason"], g["chosen_order2_seq"], g["ref_1b_seq"]),
                         (True, None, r2["seq"], d2["ref_1b_seq"]))
        self.assertIsNone(adoc["halt"])
        self.assertEqual(g["timing_check"], adoc["timing_check"])
        self.assertTrue(adoc["timing_check"]["ok"])
        self.assertEqual(adoc["code"], {"path": ledger.COUNTING_SCRIPT, "sha256": t78.SEALED_SHA, "found": True,
                                        "commit": self.counting_commit})
        self.assertEqual(adoc["ref_1b"]["seq"], d2["ref_1b_seq"])
        self.assertIsNotNone(aots)
        o3rec, _rel3, ots3, o3doc, c3 = out["order3"]
        self.assertEqual(o3rec["seq"], arec["seq"] + 1)
        self.assertEqual(sorted(o3doc), sorted(ledger.ORDER3_DOC_KEYS))
        self.assertEqual(o3doc["attempt"], ledger.record_ref(arec))
        self.assertEqual(o3doc["ref_order2"], ledger.record_ref(r2))
        self.assertEqual(o3doc["ref_order1"], ledger.record_ref(ledger.first_order1(self.records())))
        self.assertEqual(o3doc["counting"], {"official_candidate": "C7", "official_status": d2["counting_output"]
                                             ["official_status"]})
        self.assertEqual(o3doc["reading"], {"path": READING, "sha256": ledger.sha256_hex(READING_TEXT.encode())})
        self.assertIsNotNone(ots3)
        # 入口の中で、試みと順番3の記録を別々にコミットした（作成者とコミッタは noreply の1件、本文は決まった1行）
        self.assertEqual(self.head(), c3)
        self.assertEqual(self.git("rev-parse", "HEAD~1").decode().strip(), acommit)
        for c, msg in ((acommit, seal_order3.ATTEMPT_MESSAGE), (c3, seal_order3.ORDER3_MESSAGE)):
            got = self.git("log", "-1", "--format=%an <%ae>|%cn <%ce>|%B", c).decode().rstrip("\n")
            self.assertEqual(got, WHO + "|" + WHO + "|" + msg)
        self.assertEqual(self.git("status", "--porcelain"), b"")
        out_v = self.verify_zero("all")
        self.assertIn("%s seq %d（順番3の試み）: 通った（順番2の記録 seq %d を参照）" % (A3, arec["seq"], r2["seq"]), out_v)
        self.assertIn("%s seq %d（順番3）: 試み seq %d" % (O3, o3rec["seq"], arec["seq"]), out_v)
        self.assertIn("封印した版の order3_gate()", out_v)
        # 同じ順番1b に二度目は書かない（試みも書かない）
        before = self.ledger_bytes()
        with self.assertRaisesRegex(ledger.LedgerError, "順番3の記録は、もう seq %d にある" % o3rec["seq"]):
            self.attempt()
        self.assertEqual(self.ledger_bytes(), before)

    def test_choose_smallest_non_pending(self):
        """順番2の記録が二つ（seq の小さい (b) と、あとの決まった記録）なら、seq の小さい (b) を参照する（counting.md 4章 (3)
        の 5）。"""
        empty = os.path.join(self.tmp, "empty")
        os.makedirs(empty)
        rb, db = self.o2(empty)
        self.assertEqual(db["stop_kind"], "b")
        rd, dd = self.o2()
        self.assertEqual(dd["status"], "decided")
        out = self.attempt()
        self.assertEqual(self.gate(out)["chosen_order2_seq"], rb["seq"])
        self.assertEqual(out["order3"][3]["ref_order2"], ledger.record_ref(rb))
        self.verify_zero("all")


# ---------------------------------------------------------------- 2. 止まった場合

class TestStops(O3Case):
    def test_zero_order2_then_pass(self):
        """順番2の記録が0件なら止まり、記録する。0件は恒久の停止ではない（順番2を書けば通る）。"""
        out = self.attempt()
        g = self.gate(out)
        self.assertEqual((g["may_seal"], g["reason"], g["chosen_order2_seq"]), (False, R_NO_O2, None))
        self.assertIsNone(out["order3"])
        self.assertEqual(self.records()[-1]["kind"], A3)
        self.assertEqual(self.git("status", "--porcelain"), b"")
        out_v = self.verify_zero("all")
        self.assertIn("止まった（%s）" % R_NO_O2, out_v)
        self.o2()
        out2 = self.attempt()
        self.assertTrue(self.gate(out2)["may_seal"])
        self.assertIsNotNone(out2["order3"])
        self.verify_zero("all")

    def test_timing_rechecked_at_order3(self):
        """順番2のときは時機の条件を満たしていても、順番3の時点の参照で破れていれば止まる（確かめ直し）。"""
        _r2, d2 = self.o2()
        self.assertTrue(d2["timing_check"]["ok"])
        bad = self.side_branch_violation()
        out = self.attempt()
        g, tc = self.gate(out), out["attempt"][3]["timing_check"]
        self.assertFalse(g["may_seal"])
        self.assertTrue(g["reason"].startswith(R_TIMING), g["reason"])
        self.assertFalse(tc["ok"])
        self.assertIn(bad, [c["commit"] for c in tc["f_set"]])
        self.assertIn("refs/heads/side", [r["ref"] for r in tc["refs"]])
        self.assertIsNone(out["order3"])
        self.verify_zero("all")

    def test_permanent_stop(self):
        """破れを一度記録したら、あとで枝を消して時機の条件が通るようになっても止まる（3b）。"""
        self.o2()
        self.side_branch_violation()
        first = self.attempt()
        self.assertTrue(self.gate(first)["reason"].startswith(R_TIMING))
        self.remove_branch()
        for _ in range(2):
            out = self.attempt()
            g = self.gate(out)
            self.assertTrue(out["attempt"][3]["timing_check"]["ok"])
            self.assertEqual((g["may_seal"], g["reason"]), (False, R_PERM))
            self.assertIsNone(out["order3"])
        self.verify_zero("all")

    def test_order2_a_record(self):
        """順番2の記録に (a) が一つでもあれば止まる（4）。順番3の時点の時機の条件は満たしていても止まる。"""
        self.side_branch_violation()
        _r2, d2 = self.o2()
        self.assertEqual(d2["stop_kind"], "a")
        self.remove_branch()
        self.o2()                                    # あとの決まった記録があっても (a) で止まる
        out = self.attempt()
        g = self.gate(out)
        self.assertTrue(out["attempt"][3]["timing_check"]["ok"])
        self.assertEqual((g["may_seal"], g["reason"]), (False, R_O2A))
        self.verify_zero("all")

    def test_bundle_halt_without_timing(self):
        """参照を読んでから bundle を作るまでに参照が変わる（ここでは、読んだ直後に枝を1つ足す）と、bundle の list-heads が読んだ
        参照と合わない。そのときは時機の条件（F と ok）を計算せず、関門も流さずに halt（bundle）を記録する（seal-order1.md
        177・178行。T-091）。make_bundle・bundle の照らし方は差し替えない。破れの枝があっても記録に ok は入らない。"""
        self.o2()
        self.side_branch_violation()
        real = verify.read_refs_now

        def read_then_change(repo, label="順番2"):
            snap = real(repo, label)
            self.git("branch", "race-extra")
            return snap
        with mock.patch.object(verify, "read_refs_now", read_then_change), \
                mock.patch.object(verify, "timing_from_refs", side_effect=AssertionError("計算してはいけない")):
            out = self.attempt()
        adoc = out["attempt"][3]
        self.assertIsNone(adoc["gate"])
        self.assertEqual(adoc["halt"]["cause"], "bundle")
        self.assertIsNone(adoc["timing_check"])
        self.assertIn({"name": "refs/heads/race-extra", "commit": adoc["head"]}, adoc["bundle_heads"])
        self.assertNotIn("refs/heads/race-extra", [r["ref"] for r in adoc["refs_read"]["refs"]])
        self.assertIsNone(out["order3"])
        out_v = self.verify_zero("all")
        self.assertIn("関門の結果を出さずに止まった（bundle：", out_v)
        self.assertIn("時機の条件 計算していない", out_v)
        self.remove_branch()
        self.remove_branch("race-extra")
        out2 = self.attempt()
        self.assertTrue(self.gate(out2)["may_seal"])
        self.verify_zero("all")


class TestHaltCode(O3Case):
    """順番1b の記録が縛る counting.py の版が履歴に無い：関門を流せないので、halt（cause "code"）を記録する。"""
    one_b_sha = "c" * 64
    put_counting = False

    def test_halt_code(self):
        _r2, d2 = self.o2()
        self.assertEqual(d2["stop_kind"], "c")
        out = self.attempt()
        adoc = out["attempt"][3]
        self.assertIsNone(adoc["gate"])
        self.assertEqual(adoc["halt"]["cause"], "code")
        self.assertEqual(adoc["code"], {"path": ledger.COUNTING_SCRIPT, "sha256": "c" * 64, "found": False,
                                        "commit": None})
        self.assertIsNone(out["order3"])
        out_v = self.verify_zero("all")
        self.assertIn("関門の結果を出さずに止まった（code：", out_v)


class TestNo1b(tw.WriterCase):
    """順番1b の記録が無い仮のプロジェクト（periods と candidates だけ）：ref_1b は null、timing_check.ok は false で F を数えず、
    封印した版が決まらないので halt（code）。"""

    def test_no_1b(self):
        self.seal()
        write_reading(self.root)
        self.commit("periods・candidates と順番3の文書（テスト）")
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        with mock.patch.object(ledger, "PROJECT_ROOT", self.root):
            out = seal_order3.seal(os.path.join(td.name, "b.bundle"), T0 + 5 * H, "ots", runner=tw.FakeOts())
        adoc = out["attempt"][3]
        self.assertIsNone(adoc["ref_1b"])
        self.assertEqual((adoc["timing_check"]["ref_1b_seq"], adoc["timing_check"]["ok"], adoc["timing_check"]["f_set"]),
                         (None, False, []))
        self.assertEqual(adoc["halt"]["cause"], "code")
        self.assertEqual(adoc["code"], {"path": ledger.COUNTING_SCRIPT, "sha256": None, "found": False, "commit": None})
        r = tl.run_verify(self.root, "stats-order", "--rev", "auto")
        self.assertEqual(r.returncode, 0, r.stderr.decode())
        self.assertIn("参照する順番1b は 無し", r.stdout.decode())


class TestBeforeAttempt(O3Case):
    """試みを書く前の確かめ（関門の結果に依らないもの）で止まれば、何も書かない。"""

    def test_reading_doc_required(self):
        self.o2()
        self.git("rm", "-q", "--", READING)
        self.commit("文書を外す（テスト）")
        before = self.ledger_bytes()
        with self.assertRaisesRegex(ledger.LedgerError, "HEAD に無い"):
            self.attempt()
        self.assertEqual(self.ledger_bytes(), before)

    def test_dirty_tree_refused(self):
        with open(os.path.join(self.root, "untracked.txt"), "w") as f:
            f.write("x")
        before = self.ledger_bytes()
        with self.assertRaisesRegex(ledger.LedgerError, "作業ツリーがきれいでない"):
            self.attempt()
        self.assertEqual(self.ledger_bytes(), before)


# ---------------------------------------------------------------- 3. 版の固定（作業ツリー・HEAD の counting.py は使わない）

class TestPinnedVersion(O3Case):
    def changed_counting(self):
        """HEAD の counting.py を、order3_gate() の止まる理由の文と、通る判定を変えた版にしてコミットする。"""
        changed = t78.SEALED_COUNTING.replace(R_NO_O2.encode(), "HEAD の版の理由（テスト）".encode())
        changed = changed.replace(b"    if any(r[\"ref_1b_seq\"] == ref and not r[\"timing_ok\"] for r in order3_attempts):",
                                  b"    if False:")
        self.assertNotEqual(changed, t78.SEALED_COUNTING)
        with open(os.path.join(self.root, ledger.COUNTING_SCRIPT), "wb") as f:
            f.write(changed)
        self.commit("HEAD の counting.py を変える（テスト）")
        return changed

    def test_writer_uses_sealed_version(self):
        self.changed_counting()
        out = self.attempt()
        self.assertEqual(self.gate(out)["reason"], R_NO_O2)
        self.assertEqual(out["attempt"][3]["code"]["commit"], self.counting_commit)
        self.verify_zero("all")

    def test_permanent_stop_with_head_version_changed(self):
        """HEAD の版から恒久の停止を外しても、封印した版で流すので止まる。"""
        self.o2()
        self.side_branch_violation()
        self.attempt()
        self.remove_branch()
        self.changed_counting()
        out = self.attempt()
        self.assertEqual(self.gate(out)["reason"], R_PERM)
        self.verify_zero("all")

    def test_verify_uses_sealed_version(self):
        """HEAD の版で計算した gate（理由の文が違う）を書くと、verify は封印した版で計算し直して止める。"""
        self.changed_counting()
        doc = self.build_attempt()
        doc = dict(doc, gate=dict(doc["gate"], reason="HEAD の版の理由（テスト）"))
        self.forged(A3, doc, GATE_DIFF)


# ---------------------------------------------------------------- 4. 作り物の記録

class TestForgeries(O3Case):
    def test_forged_pass_after_breach(self):
        """恒久に止まる形で、gate を通ったことにする。書く仕組みも verify も、封印した版で計算し直して止める。"""
        r2, _d2 = self.o2()
        self.side_branch_violation()
        self.attempt()
        self.remove_branch()
        doc = self.build_attempt()
        self.assertEqual(doc["gate"]["reason"], R_PERM)
        doc = dict(doc, gate=dict(doc["gate"], may_seal=True, reason=None, chosen_order2_seq=r2["seq"]))
        self.forged(A3, doc, GATE_DIFF)

    def test_forged_timing_ok(self):
        """時機の条件が破れているのに、f_set から破れの commit を外して ok を true にし、gate を通ったことにする。gate だけを
        計算し直しても通ってしまうので、F の集合の計算し直しが止める。"""
        r2, _d2 = self.o2()
        bad = self.side_branch_violation()
        doc = self.build_attempt()
        tc = doc["timing_check"]
        self.assertFalse(tc["ok"])
        tc = dict(tc, ok=True, reason=None, f_set=[c for c in tc["f_set"] if c["commit"] != bad])
        doc = dict(doc, timing_check=tc, gate=dict(doc["gate"], may_seal=True, reason=None, chosen_order2_seq=r2["seq"],
                                                    timing_check=tc))
        self.forged(A3, doc, "timing_check.f_set が、記録した refs・worktree_heads から計算し直した F の集合と親と違う")

    def test_forged_chosen(self):
        """関門が選ぶ順番2の記録（seq の小さいもの）と違う記録を選んだことにする（参照の食い違い）。"""
        empty = os.path.join(self.tmp, "empty")
        os.makedirs(empty)
        self.o2(empty)
        rd, _dd = self.o2()
        doc = self.build_attempt()
        doc = dict(doc, gate=dict(doc["gate"], chosen_order2_seq=rd["seq"]))
        self.forged(A3, doc, GATE_DIFF)

    def test_forged_ref_1b(self):
        self.o2()
        doc = self.build_attempt()
        doc = dict(doc, ref_1b=dict(doc["ref_1b"], record_sha256="0" * 64))
        self.forged(A3, doc, "ref_1b .* が、この記録より前の stats-order1b の seq の最大")

    def test_forged_halt_code_with_version(self):
        """封印した版が履歴にあるのに、halt（code）にする。"""
        self.o2()
        doc = self.build_attempt()
        doc = dict(doc, gate=None, halt={"cause": "code", "reason": "作り物"}, code=dict(doc["code"], found=False,
                                                                                         commit=None))
        self.forged(A3, doc, r"code（found False・commit None）が、git の履歴から探し直した結果")

    def test_order3_without_passed_attempt(self):
        out = self.attempt()
        arec = out["attempt"][0]
        self.assertFalse(self.gate(out)["may_seal"])
        recs = self.records()
        bad = self.next_head({"kind": O3, "attempt": ledger.record_ref(arec), "ref_1b": out["attempt"][3]["ref_1b"],
                              "ref_order1": ledger.record_ref(ledger.first_order1(recs)), "ref_order2": None,
                              "counting": {"official_candidate": "C7", "official_status": "decided"},
                              "reading": {"path": READING, "sha256": ledger.sha256_hex(READING_TEXT.encode())}})
        self.forged(O3, bad, "関門を通っていない")

    def passed_without_order3(self):
        """関門を通った試みだけを書き、順番3の記録は書かない形（順番3の記録を作る段で止める）。"""
        self.o2()
        with mock.patch.object(seal_order3, "build_order3", side_effect=ledger.LedgerError("止める（テスト）")), \
                self.assertRaisesRegex(seal_order3.Order3Written, "順番3の記録は書いていない"):
            self.attempt()
        self.assertEqual(self.git("status", "--porcelain"), b"")
        data = self.ledger_bytes()
        recs = ledger.verify_chain(data)
        arec = recs[-1]
        self.assertEqual(arec["kind"], A3)
        adoc = ledger.read_target_json(self.root, arec, A3)
        self.assertTrue(adoc["gate"]["may_seal"])
        with mock.patch.object(ledger, "PROJECT_ROOT", self.root):
            return seal_order3.build_order3(self.root, data, recs, arec, adoc)

    def test_order3_wrong_reading(self):
        doc = self.passed_without_order3()
        self.verify_zero("all")
        self.forged(O3, dict(doc, reading=dict(doc["reading"], sha256="0" * 64)), "reading.sha256 が、head")

    def test_order3_wrong_order2(self):
        doc = self.passed_without_order3()
        o1 = ledger.record_ref(ledger.first_order1(self.records()))
        self.forged(O3, dict(doc, ref_order2=o1), "ref_order2 が、試みが選んだ順番2の記録")

    def test_attempt_after_order3(self):
        """順番3の記録のあとに、同じ順番1b への試みを足す（一つの順番1b に1件だけの決まりをすり抜けるため）。"""
        self.o2()
        out = self.attempt()
        self.assertIsNotNone(out["order3"])
        doc = self.next_head(out["attempt"][3])
        self.raw(A3, rehead(doc, doc["head"]))
        self.verify_stops("のあとにある", "all")


# ---------------------------------------------------------------- 4b. T-091（T-090 の監査 中-2）：照合を1つずつ外すと落ちる単体のテスト

class TestLedgerUnits(O3Case):
    """ledger.check_order3_records の照合のうち、ほかの照合（git・関門の計算し直し）では止まらないものを、1つずつ確かめる。
    次の記録として足した形にして、git を使わない照合だけを流す。どのテストも、その照合だけが出す文まで見る。"""

    def check(self, kind, doc, text):
        data = self.ledger_bytes()
        content = ledger.canonical_line(doc) + b"\n"
        sha = ledger.sha256_hex(content)
        _r, rec, line = ledger.build_next_record(
            data, kind, [{"path": "sealed/%s-%s.json" % (kind, sha), "role": kind, "sha256": sha}], "", self.tick())
        recs = ledger.verify_chain(data + line)

        def read(r, role):
            return doc if r["seq"] == rec["seq"] else ledger.read_target_json(self.root, r, role)
        ledger.check_order3_records(recs, read)                      # 元の中身は通る（下の変えた形と比べるため）
        return recs, read

    def refused(self, kind, doc, bad, text):
        recs, read = self.check(kind, doc, text)
        read2 = lambda r, role: bad if r["seq"] == recs[-1]["seq"] else read(r, role)  # noqa: E731
        with self.assertRaisesRegex(ledger.LedgerError, text):
            ledger.check_order3_records(recs, read2)

    def attempt_doc(self):
        self.o2()
        return self.build_attempt()

    def test_head_not_in_worktree_heads(self):
        doc = self.attempt_doc()
        other = self.git("rev-parse", "HEAD~1").decode().strip()
        bad = rehead(doc, doc["head"])
        bad["refs_read"]["worktree_heads"] = [other]
        bad["timing_check"] = dict(bad["timing_check"], worktree_heads=[other])
        bad["gate"] = dict(bad["gate"], timing_check=bad["timing_check"])
        bad["bundle_heads"] = [h if h["name"] != "HEAD" else {"name": "HEAD", "commit": other} for h in bad["bundle_heads"]]
        self.refused(A3, doc, bad, "の head が refs_read.worktree_heads に無い")

    def test_ok_with_graft(self):
        doc = self.attempt_doc()
        self.assertTrue(doc["timing_check"]["ok"])
        bad = dict(doc, timing_guards=dict(doc["timing_guards"], graft_file=True))
        self.refused(A3, doc, bad, "timing_check.ok が True なのに、graft のファイル")

    def test_halt_code_with_version(self):
        doc = self.attempt_doc()
        bad = dict(doc, gate=None, halt={"cause": "code", "reason": "作り物"})
        self.refused(A3, doc, bad, "halt の cause が code なのに、code.found が true")

    def test_halt_input_without_version(self):
        doc = self.attempt_doc()
        bad = dict(doc, gate=None, halt={"cause": "input", "reason": "作り物"},
                   code=dict(doc["code"], found=False, commit=None))
        self.refused(A3, doc, bad, "halt の cause が input なのに、code.found が false")

    def test_halt_bundle_but_matched(self):
        doc = self.attempt_doc()
        bad = dict(doc, gate=None, halt={"cause": "bundle", "reason": "作り物"}, timing_check=None)
        self.refused(A3, doc, bad, "bundle_heads と refs_read が合うのに halt（bundle）")

    def test_unmatched_without_halt(self):
        doc = self.attempt_doc()
        bad = dict(doc, bundle_heads=doc["bundle_heads"] + [{"name": "refs/heads/zz", "commit": doc["head"]}])
        self.refused(A3, doc, bad, "bundle_heads と refs_read が合わないのに halt（bundle）でない")

    def test_halt_bundle_with_timing(self):
        doc = self.attempt_doc()
        bad = dict(doc, gate=None, halt={"cause": "bundle", "reason": "作り物"},
                   bundle_heads=doc["bundle_heads"] + [{"name": "refs/heads/zz", "commit": doc["head"]}])
        self.refused(A3, doc, bad, "halt（bundle）なのに timing_check がある")

    def test_timing_refs_not_read(self):
        doc = self.attempt_doc()
        tc = dict(doc["timing_check"], refs=doc["timing_check"]["refs"] + [{"ref": "refs/heads/zz", "commit": doc["head"]}])
        bad = dict(doc, timing_check=tc, gate=dict(doc["gate"], timing_check=tc))
        self.refused(A3, doc, bad, "timing_check の head・refs・worktree_heads が refs_read と違う")

    def order3_doc(self):
        return TestForgeries.passed_without_order3(self)

    def test_ref_order1(self):
        doc = self.order3_doc()
        self.refused(O3, doc, dict(doc, ref_order1=doc["ref_order2"]), "ref_order1 が、stats-order1 の記録")

    def test_counting(self):
        doc = self.order3_doc()
        self.refused(O3, doc, dict(doc, counting=dict(doc["counting"], official_candidate="C1")),
                     "counting が、参照する順番1b の記録の official_candidate")


class TestRecordHead(O3Case):
    """verify.check_order3_git の、head の版の記録（先頭 seq−1 行）と、head が base の祖先であることの照合。"""

    def prepared(self):
        doc = TestForgeries.passed_without_order3(self)
        data = self.ledger_bytes()
        content = ledger.canonical_line(doc) + b"\n"
        sha = ledger.sha256_hex(content)
        _r, rec, line = ledger.build_next_record(
            data, O3, [{"path": "sealed/%s-%s.json" % (O3, sha), "role": O3, "sha256": sha}], "", self.tick())
        recs = ledger.verify_chain(data + line)
        read = lambda r, role: doc if r["seq"] == rec["seq"] else ledger.read_target_json(self.root, r, role)  # noqa: E731
        repo = verify.Repo(self.root)
        self.assertEqual(verify.check_order3_git(repo, data + line, recs, rec, doc, self.head(), read), [])
        return doc, data + line, recs, rec, read, repo

    def test_head_with_other_ledger(self):
        doc, data, recs, rec, read, repo = self.prepared()
        older = self.git("rev-parse", "HEAD~1").decode().strip()            # 試みの記録の前の commit（順3の文書はある）
        with self.assertRaisesRegex(ledger.LedgerError, "の版の sealed/ledger.jsonl が、この記録を足す直前の記録"):
            verify.check_order3_git(repo, data, recs, rec, dict(doc, head=older), self.head(), read)

    def test_head_not_ancestor(self):
        doc, data, recs, rec, read, repo = self.prepared()
        base = self.head()
        branch = self.git("symbolic-ref", "--short", "HEAD").decode().strip()
        self.git("checkout", "-q", "-b", "elsewhere")
        with open(os.path.join(self.root, "elsewhere.txt"), "w") as f:
            f.write("x\n")
        self.commit("祖先でない commit（テスト）")
        side = self.head()
        self.git("checkout", "-q", branch)
        with self.assertRaisesRegex(ledger.LedgerError, "の祖先でない"):
            verify.check_order3_git(repo, data, recs, rec, dict(doc, head=side), base, read)


class TestOrder2BundleOrder(t78.Synth):
    """T-091：順番2も seal-order1.md 177行の順（参照を読む → bundle を作って照らす → 合ったときだけ F と ok を計算する）。
    参照を読んだ直後に枝を足すと、bundle が合わずに何も書かずに止まり、時機の条件は計算しない。"""

    def test_order2_reads_then_bundle_then_timing(self):
        real = verify.read_refs_now

        def read_then_change(repo, label="順番2"):
            snap = real(repo, label)
            self.git("branch", "race-extra")
            return snap
        before = self.ledger_bytes()
        with mock.patch.object(verify, "read_refs_now", read_then_change), \
                mock.patch.object(verify, "timing_from_refs", side_effect=AssertionError("計算してはいけない")), \
                self.assertRaisesRegex(ledger.LedgerError, "list-heads が、記録する refs・worktree の HEAD と合わない"):
            self.write()
        self.assertEqual(self.ledger_bytes(), before)
        self.git("branch", "-D", "race-extra")
        _rec, _rel, _o, doc = self.write()                     # 参照が変わらなければ、計算して書く
        self.assertEqual(doc["status"], "decided")
        self.verify_zero("all")


class TestBundleMatchUnit(unittest.TestCase):
    """ledger.bundle_heads_match（seal-order1.md 178行の照らし方）。"""

    A, B = "a" * 40, "b" * 40

    def test_cases(self):
        refs = [{"ref": "refs/heads/main", "commit": self.A}]
        ok = [{"name": "HEAD", "commit": self.A}, {"name": "refs/heads/main", "commit": self.A}]
        self.assertTrue(ledger.bundle_heads_match(refs, [self.A], ok))
        self.assertFalse(ledger.bundle_heads_match(refs, [self.A], ok + [{"name": "refs/heads/x", "commit": self.B}]))
        self.assertFalse(ledger.bundle_heads_match(refs + [{"ref": "refs/heads/y", "commit": self.B}], [self.A], ok))
        self.assertFalse(ledger.bundle_heads_match(refs, [self.A, self.B], ok))
        self.assertTrue(ledger.bundle_heads_match(refs, [self.A, self.B],
                                                  ok + [{"name": "worktrees/w/HEAD", "commit": self.B}]))
        self.assertFalse(ledger.bundle_heads_match(refs, [self.A], [{"name": "HEAD", "commit": self.A},
                                                                   {"name": "refs/heads/main", "commit": self.B}]))


class TestHaltInput(O3Case):
    """封印した版の order3_gate() が ValueError で入力を受け付けないときも、試みとして記録する（halt、cause "input"。
    T-091。T-090 の監査 軽-2）。今の照合を通った記録からは起きないので、入力を作る関数を差し替えて起こす。verify は、
    同じ差し替えのもとでは通り、差し替えなしで計算し直すと（入力を受け付けるので）止める。"""

    def test_halt_input(self):
        self.o2()
        real = ledger.order3_gate_inputs

        def broken(records, seq, tc, read_json):
            d = real(records, seq, tc, read_json)
            return dict(d, order2_records=d["order2_records"] + [{"seq": 1, "status": "decided", "stop_kind": None,
                                                                  "ref_1b_seq": 999}])
        with mock.patch.object(ledger, "order3_gate_inputs", broken):
            out = self.attempt()
            adoc = out["attempt"][3]
            self.assertIsNone(adoc["gate"])
            self.assertEqual(adoc["halt"]["cause"], "input")
            self.assertIn("ValueError: ", adoc["halt"]["reason"])
            self.assertTrue(adoc["code"]["found"])
            self.assertIsNone(out["order3"])
            out_v = self.verify_zero("all")
            self.assertIn("記録の halt（input） と同じ", out_v)
        self.verify_stops(re.escape("halt（input）なのに、封印した版の order3_gate() を記録から計算し直すと入力を受け付ける"), "all")


# ---------------------------------------------------------------- 5. targets の数と role（stats-order2・stats-order3-attempt・stats-order3）

class TestTargets(O3Case):
    def two_targets(self, kind, doc):
        """中身と、もう1つのファイルを縛る記録を、書く仕組みを通さずに足す。返り値: その記録。"""
        content = ledger.canonical_line(doc) + b"\n"
        sha = ledger.sha256_hex(content)
        rel = "sealed/%s-%s.json" % (kind, sha)
        ledger.write_once(os.path.join(self.root, rel), content)
        extra_rel = "predictions/t090-extra.json"
        os.makedirs(os.path.join(self.root, "predictions"), exist_ok=True)
        with open(os.path.join(self.root, extra_rel), "wb") as f:
            f.write(b'{"x":1}\n')
        targets = [{"path": rel, "role": kind, "sha256": sha},
                   {"path": extra_rel, "role": "extra", "sha256": ledger.sha256_hex(b'{"x":1}\n')}]
        path = os.path.join(self.root, "sealed", "ledger.jsonl")
        after = ledger.append_record(path, kind, targets, "作り物（テスト）", self.tick())
        rec = after[-1]
        with open(os.path.join(self.root, "sealed", ledger.ots_name(rec["seq"])), "xb") as f:
            f.write(tl.build_ots(ledger.prefix_bytes(self.ledger_bytes(), rec["seq"])))
        return rec

    def check_both(self, kind, doc, text):
        # 書く仕組み：照合（check_new）は、targets が2つの記録を通さない
        data = self.ledger_bytes()
        _r, rec, line = ledger.build_next_record(data, kind, [
            {"path": "sealed/%s-%s.json" % (kind, "a" * 64), "role": kind, "sha256": "a" * 64},
            {"path": "predictions/x.json", "role": "extra", "sha256": "b" * 64}], "", self.tick())
        with self.assertRaisesRegex(ledger.LedgerError, text):
            seal_records.check_new(self.root, data + line, ledger.verify_chain(data + line), rec, doc)
        # verify：書く仕組みを通さずに足した記録を止める
        self.two_targets(kind, doc)
        self.commit("targets が2つの作り物（テスト）")
        self.verify_stops(text, "all")

    def test_order2_two_targets(self):
        doc = self.build()
        self.check_both(O2, doc, "targets がちょうど1つでない（2 個）")

    def test_attempt_two_targets(self):
        self.o2()
        self.check_both(A3, self.build_attempt(), "targets がちょうど1つでない（2 個）")

    def test_order3_two_targets(self):
        doc = TestForgeries.passed_without_order3(self)
        self.check_both(O3, doc, "targets がちょうど1つでない（2 個）")

    def test_role_fixed(self):
        """targets は1つでも、path が決まった形でなければ止まる。"""
        doc = self.build()
        content = ledger.canonical_line(doc) + b"\n"
        sha = ledger.sha256_hex(content)
        rel = "sealed/other-%s.json" % sha
        ledger.write_once(os.path.join(self.root, rel), content)
        path = os.path.join(self.root, "sealed", "ledger.jsonl")
        rec = ledger.append_record(path, O2, [{"path": rel, "role": O2, "sha256": sha}], "作り物（テスト）",
                                   self.tick())[-1]
        with open(os.path.join(self.root, "sealed", ledger.ots_name(rec["seq"])), "xb") as f:
            f.write(tl.build_ots(ledger.prefix_bytes(self.ledger_bytes(), rec["seq"])))
        self.commit("path の違う作り物（テスト）")
        self.verify_stops("targets の role・path が、決まった形", "all")


# ---------------------------------------------------------------- 6. 浅い clone と git の履歴の無い写し

class TestUnchecked(O3Case):
    def test_shallow_and_no_git(self):
        """浅い clone と git の履歴の無い写しでは、順番3の git からの計算し直し（作り物の gate も含む）を「照らさなかった」と
        する。"""
        r2, _d2 = self.o2()
        self.side_branch_violation()
        self.attempt()
        self.remove_branch()
        doc = self.build_attempt()
        doc = dict(doc, gate=dict(doc["gate"], may_seal=True, reason=None, chosen_order2_seq=r2["seq"]))
        rec = self.raw(A3, doc)
        shallow = os.path.join(self.tmp, "shallow")
        subprocess.run(["git", "clone", "-q", "--depth", "1", "file://" + self.root, shallow], check=True,
                       capture_output=True)
        plain = os.path.join(self.tmp, "plain")
        shutil.copytree(self.root, plain, ignore=shutil.ignore_patterns(".git"))
        for where, why in ((shallow, "浅い clone"), (plain, "git の履歴が無い")):
            with self.subTest(why=why):
                st = verify.State(where, None)
                got = ledger.check_stats_order(st.records, st.file_json)
                with contextlib.redirect_stdout(io.StringIO()) as out:
                    verify.check_order3_entries(st, got["order3_attempt"], got["order3"])
                self.assertIn("照らさなかった：%s なので、seq %d の時機の条件・コードの版・関門を git から計算し直していない"
                              % (why, rec["seq"]), out.getvalue())
                self.assertTrue(any(why in u for u in st.unchecked))
        # 履歴のある本体では止まる
        self.verify_stops(GATE_DIFF, "all")


# ---------------------------------------------------------------- 7. 書いたあとで止まったとき（コミットの失敗と --commit-written）

class TestCommitWritten(O3Case):
    def test_commit_fails_then_commit_written(self):
        """試みを書いたあとでコミットが失敗したら、「書いた、コミットしていない」と知らせ、--commit-written で入口と同じ固定の
        しかたでコミットできる。"""
        before = self.head()
        with t78.write_with(lambda p: open(os.path.join(p, ".git", "index.lock"), "w").close()), \
                self.assertRaisesRegex(seal_order3.Order3Written, "作業ツリーに書いたが、コミットしていない"):
            self.attempt()
        os.rename(os.path.join(self.root, ".git", "index.lock"), os.path.join(self.tmp, "index.lock.moved"))
        self.assertEqual(self.head(), before)
        self.assertEqual(self.records()[-1]["kind"], A3)
        err = io.StringIO()
        with mock.patch.object(ledger, "PROJECT_ROOT", self.root), contextlib.redirect_stdout(io.StringIO()), \
                contextlib.redirect_stderr(err):
            code = seal_order3.main(["--commit-written"])
        self.assertEqual(code, 0, err.getvalue())
        got = self.git("log", "-1", "--format=%an <%ae>|%cn <%ce>|%B").decode().rstrip("\n")
        self.assertEqual(got, WHO + "|" + WHO + "|" + seal_order3.ATTEMPT_MESSAGE)
        self.verify_zero("all")

    def test_commit_written_refuses_order2_entry_for_order3(self):
        """順番2の入口の --commit-written は、最後の記録が順番3の kind のときはコミットしない。"""
        with t78.write_with(lambda p: open(os.path.join(p, ".git", "index.lock"), "w").close()), \
                self.assertRaises(seal_order3.Order3Written):
            self.attempt()
        os.rename(os.path.join(self.root, ".git", "index.lock"), os.path.join(self.tmp, "index.lock.moved"))
        with self.assertRaisesRegex(ledger.LedgerError, "最後の記録が stats-order2 でない"):
            seal_order2.commit_written(self.root)


# ---------------------------------------------------------------- 8. 本物の記録の固定したコミット（seq 1〜10）の clone

class TestRealClone(unittest.TestCase):
    """本物の記録（fixed_records.ORDER2_COMMIT。seq 10 が順番2の決まった記録）の clone に、統計係の文書（テストの仮のもの）を
    置いて順番3を書くと、試みは通り、順番3の記録が順番2の seq 10 を参照し、verify all --rev auto が 0。手順書17章の第三者の
    塊（<!-- test:order3 -->）もこの clone で 0 で終わり、作り物を足すと止まる。"""

    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.addCleanup(self.td.cleanup)
        self.c = os.path.join(self.td.name, "c")
        code = "worktree" if os.environ.get("SEALER_DOC_TEST_WORKTREE") == "1" else "head"
        fixed_records.checkout(self.c, fixed_records.ORDER2_COMMIT, code=code)

    def git(self, *args):
        return subprocess.run(["git", "-C", self.c] + list(tl.AUTHOR) + list(args), check=True,
                              capture_output=True).stdout

    def run_blocks(self):
        out = []
        for block in order3_blocks():
            out.append(subprocess.run(["bash", "-e", "-o", "pipefail", "-c", block], cwd=self.c, capture_output=True,
                                      env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1")))
        self.assertTrue(out)
        return out

    def test_real_order2_then_order3(self):
        write_reading(self.c)
        self.git("add", "--", READING)
        self.git("commit", "-q", "-m", "順番3の文書（テストの仮のもの。clone の中だけ）")
        with mock.patch.object(ledger, "PROJECT_ROOT", self.c):
            out = seal_order3.seal(os.path.join(self.td.name, "b.bundle"), t78.T0.replace(year=2026, month=10, day=16),
                                   "ots", runner=tw.FakeOts())
        arec, _rel, _o, adoc, _c = out["attempt"]
        self.assertEqual(arec["seq"], 11)
        self.assertEqual((adoc["gate"]["may_seal"], adoc["gate"]["chosen_order2_seq"], adoc["ref_1b"]["seq"]),
                         (True, 10, 6))
        self.assertEqual(adoc["code"]["commit"], "8e2c29b1afe7a9dc494e298b04b53dbbe115eaab")
        self.assertEqual(out["order3"][0]["seq"], 12)
        self.assertEqual(out["order3"][3]["ref_order1"]["seq"], 5)
        code, out_v, err = tl.run_verify_inproc(self.c, "all", "--rev", "auto")
        self.assertEqual(code, 0, err)
        self.assertIn("封印した版の order3_gate()", out_v)
        for r in self.run_blocks():
            self.assertEqual(r.returncode, 0, r.stderr.decode())
            self.assertIn("stats-order3-attempt seq 11（順番3の試み）: 通った（順番2の記録 seq 10 を参照）", r.stdout.decode())
        # 作り物（試みの gate の理由を変える）を足すと、同じ塊が止まる
        data = ledger.read_ledger(os.path.join(self.c, "sealed", "ledger.jsonl"))
        recs = ledger.verify_chain(data)
        bad = dict(adoc, gate=dict(adoc["gate"], may_seal=False, reason="作り物", chosen_order2_seq=None))
        head = self.git("rev-parse", "HEAD").decode().strip()
        bad = rehead(dict(bad, ledger_head=ledger.expected_ledger_head(data, len(recs) + 1)), head)
        with mock.patch.object(seal_records, "check_new", lambda *a, **k: None):
            seal_records.write_doc_record(self.c, A3, bad, data, "作り物（テスト）",
                                          t78.T0.replace(year=2026, month=10, day=17), "ots", runner=tw.FakeOts())
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "作り物（テスト）")
        for r in self.run_blocks():
            self.assertNotEqual(r.returncode, 0)


# ---------------------------------------------------------------- 9. T-083 の監査の残り：軽-1（.ots の else の側）

class TestCheckWrittenOtsElse(t83.Case):
    """最後の seq の .ots が無い形（.ots を作れず、コミットもできなかった）で、一つ前の記録（コミット済み）の行を書き換え、
    最後の行の prev_hash を合わせる（鎖の形には通り、作業ツリーの変更は sealed/ledger.jsonl だけ）。一つ前の seq の .ots は
    書き換えた先頭 N−1 行と合わないので、seal_order2.check_written の else の側（ledger.check_anchors(prefix, sealed)）が
    止める。そこを外すと、次の「HEAD の版の sealed/ledger.jsonl が…」の照合が別の文で止めるので、このテストは落ちる。"""

    def test_earlier_line_rewritten(self):
        rec, _doc = self.no_ots()
        prev = rec["seq"] - 1
        lines = ledger.split_lines(self.ledger_bytes())
        p = json.loads(lines[-2])
        p["note"] = p["note"] + "（書き換え。テスト）"
        last = json.loads(lines[-1])
        last["prev_hash"] = ledger.sha256_hex(ledger.canonical_line(p))
        with open(self.ledger, "wb") as f:
            f.write(b"".join(x + b"\n" for x in lines[:-2]) + ledger.canonical_line(p) + b"\n"
                    + ledger.canonical_line(last) + b"\n")
        self.assertEqual(len(ledger.verify_chain(self.ledger_bytes())), rec["seq"])     # 鎖の形には通る
        self.refused_written(re.escape("%s の対象のハッシュが、記録の先頭 %d 行と一致しない" % (ledger.ots_name(prev), prev)))


# ---------------------------------------------------------------- 10. 許可リスト・書く仕組み・手順書

class TestAllowedAndDoc(unittest.TestCase):
    def test_allowed(self):
        for k in (A3, O3):
            self.assertIn(k, ledger.ALLOWED_KINDS)
            self.assertIn(k, seal_records.WRITTEN_KINDS)
        self.assertEqual(len(ledger.ALLOWED_KINDS), 14)

    def test_gate_keys_match_sealed(self):
        """ledger の gate のキーは、封印した版の order3_gate() の record のキーと同じ。"""
        c = t78.COUNTING
        tc = {"ok": False, "ref_1b_seq": None, "head": "a" * 40, "f_set": [], "refs": [{"ref": "refs/heads/main",
                                                                                         "commit": "a" * 40}],
              "worktree_heads": ["a" * 40], "reason": "x"}
        got = c.order3_gate([], [], tc, [])
        self.assertEqual(tuple(sorted(got["record"])), ledger.ORDER3_GATE_KEYS)

    def test_doc_chapters(self):
        with open(DOC, encoding="utf-8") as f:
            text = f.read()
        for phrase in ("## 17. 順番3の封印（stats-order3-attempt・stats-order3。T-090、T-091）", "### 決まりの字面と違う点（結果は同じ）",
                       "`--commit-written` は関門を計算し直さない", "記録の欄の分け方と 176行", "順番1b の記録が無いとき",
                       "src/sealer/seal_order3.py \\\n  --bundle-out", "seal_order3.py --commit-written", READING,
                       "<!-- test:order3 -->", "/usr/bin/python3", "この2件は skip になる", "Python 3.14 で作る",
                       "python3.14 -m venv .venv"):
            self.assertIn(phrase, text)
        self.assertNotIn("`tests/sealer` は、`/usr/bin/python3 -B` でも全件通る。", text)


if __name__ == "__main__":
    unittest.main()
