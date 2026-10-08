"""T-074 のテスト：正式な run は必ず計画を持つ（GKG_RUN_PLAN_REQUIRED_FOR_OFFICIAL を True にした）こと、
T-071・T-073 の監査で残った軽い点の直し。

実行（プロジェクトのルートで）:
    PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest discover -s tests/sealer -v

  1. フラグが True（書く仕組みと verify が、計画の無い official を止めることは test_t068・test_t070 が確かめる）。
  2. plan_sha256 の無い試しの run の記録（本物の seq 8）を、verify が「照らさなかった」と出す（T-071 の監査）。
  3. 正式な run の run-start の行の trial_manifest_sha256 を、R の gkg-run-result が縛る試しの run のマニフェストと
     照らす。R の gkg-run-result が無ければ「照らさなかった」（T-073 の監査 軽-1）。
  4. N8（記録を最初に含んだコミットのマニフェストを使う）・N11（input_run が R なら gkg_run_result は
     trial_result と同じ）・N12（行き先が「待つ」なら止める）の、誤りを入れると落ちるテスト（T-073 の監査 軽-2）。
  5. まだコミットされていない順番2の記録は「照らさなかった」（T-073 の監査 軽-3）。

本物のリポジトリの clone（test_t066.Clone）の中だけで書く。ots は偽物（test_writers.FakeOts）。本物の sealed/・
data/manifest/ には書かない。順番2の kind は、テストの中だけ許可リストに入れる（本物の定数は変えない）。
ネットワークと LACIE SHARE には触れない。
"""

import contextlib
import hashlib
import io
import os
import sys
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import test_ledger as tl  # noqa: E402
import test_t073 as t73  # noqa: E402
from test_t073 import O2, jl, line_sha, order2_allowed, ostart  # noqa: E402

ledger = tl.ledger
verify = tl.verify
DOC = os.path.join(tl.PROJECT, "docs", "verify", "periods-seal.md")
OFFICIAL = ledger.GKG_MANIFESTS["official"]


def official_manifest(trial_sha_body=None, want=None, rid=None):
    """正式な run のマニフェスト（run-start の行 1 行）。want を渡せば trial_manifest_sha256 をその値にする。"""
    row = ostart(trial_sha_body or b"", [rid] if rid else [])
    if want is not None:
        row["trial_manifest_sha256"] = want
    return jl([row])


class TestFlag(unittest.TestCase):
    def test_flag_true_and_doc(self):
        self.assertTrue(ledger.GKG_RUN_PLAN_REQUIRED_FOR_OFFICIAL)
        with open(DOC, encoding="utf-8") as f:
            text = f.read()
        self.assertIn("正式な run は必ず計画を持つ", text)
        self.assertNotIn("今は False", text)


# ---- 2. plan_sha256 の無い記録の「照らさなかった」

class TestNoPlanShaUnchecked(t73.Order2Case):
    def test_real_seq8(self):
        recs = [r for r in self.records() if r["kind"] == ledger.GKG_RUN_KIND]
        trial = [r for r in recs if self.read(r, ledger.GKG_RUN_KIND)["mode"] == "trial"
                 and ledger.GKG_RUN_PLAN_SHA_KEY not in self.read(r, ledger.GKG_RUN_KIND)]
        self.assertTrue(trial)
        code, out, err = tl.run_verify_inproc(self.c, "gkg-runs")
        self.assertEqual(code, 0, err)
        for r in trial:
            self.assertIn("照らさなかった：seq %d の gkg-run-start（trial）は、計画の sha256（plan_sha256）が無い記録"
                          "（T-070 より前）なので" % r["seq"], out)
        code, out, err = tl.run_verify_inproc(self.c, "all")
        self.assertEqual(code, 0, err)
        last = [l for l in out.splitlines() if l.startswith("ただし、次は照らさなかった")][0]
        for r in trial:
            self.assertIn("seq %d の gkg-run-start（trial）の計画の一覧（計画の sha256 が無い記録。T-070 より前）" % r["seq"],
                          last)


# ---- 3. 正式な run の run-start の trial_manifest_sha256

class TestOfficialTrialSha(t73.Order2Case):
    def results(self):
        return {("trial", self.rid): self.res} if getattr(self, "res", None) else {}

    def check(self, trial, official):
        return ledger.check_official_trial_manifest_sha(self.read, {"trial": trial, "official": official},
                                                        self.results())

    def test_unit(self):
        self.sealed()
        rdoc = self.read(self.res, ledger.GKG_RESULT_KIND)
        self.assertEqual(rdoc["manifest_sha256"], hashlib.sha256(self.body).hexdigest())
        # 照らすものが無い
        self.assertIsNone(self.check(self.body, None))
        self.assertIsNone(self.check(self.body, b""))
        # 同じなら通る
        got = self.check(self.body, official_manifest(self.body, rid=self.rid))
        self.assertEqual((got["checked"], got["run_id"], got["result_seq"], got["later"]),
                         (True, self.rid, self.res["seq"], False))
        # 違えば止まる（最初のコミットの前に書き換えて (b) を固める形）
        for want in ("0" * 64, None, hashlib.sha256(self.body + b"\n").hexdigest()):
            with self.subTest(want=want):
                with self.assertRaisesRegex(ledger.LedgerError, "trial_manifest_sha256"):
                    self.check(self.body, official_manifest(want=want, rid=self.rid))
        # R のあとにも試しの run の行がある：今の全体の sha256 と同じなら通す。R の縛る先頭と同じでも通す
        more = self.body + jl([t73.tstart(t73.S)])
        got = self.check(more, official_manifest(more, rid=self.rid))
        self.assertTrue(got["later"])
        self.check(more, official_manifest(self.body, rid=self.rid))
        with self.assertRaisesRegex(ledger.LedgerError, "trial_manifest_sha256"):
            self.check(more, official_manifest(want="0" * 64, rid=self.rid))
        # 先頭が足りない（R の終わる前に正式な run を始めた形）も止まる
        short = self.body.split(b"\n", 1)[0] + b"\n"
        with self.assertRaisesRegex(ledger.LedgerError, "trial_manifest_sha256"):
            self.check(self.body, official_manifest(short, rid=self.rid))

    def test_unit_unchecked(self):
        got = self.check(self.body, official_manifest(want="0" * 64, rid=self.rid))       # R の結果が無い
        self.assertFalse(got["checked"])
        self.assertIn("R（run_id %s）の gkg-run-result の記録が無い" % self.rid, got["reason"])
        got = self.check(b"", official_manifest(want=None))
        self.assertFalse(got["checked"])
        self.assertIn("R", got["reason"])

    def run_gkg_runs(self, official):
        """正式な run のマニフェストを置いて verify gkg-runs を流す。正式な run の gkg-run-start の記録は本物の鎖に
        足せないので、マニフェストと記録の照合（check_gkg_manifests）の official の側だけを照らさない形にする
        （それ以外の verify はそのまま）。"""
        with open(os.path.join(self.c, OFFICIAL), "wb") as f:
            f.write(official)
        real = ledger.check_gkg_manifests

        def only_trial(records, read_json, manifests):
            got = real(records, read_json, dict(manifests, official=None))
            return got
        with mock.patch.object(ledger, "check_gkg_manifests", only_trial):
            return tl.run_verify_inproc(self.c, "gkg-runs")

    def test_verify(self):
        """verify gkg-runs が照らす。違えば 1。R の gkg-run-result が無ければ「照らさなかった」（0）。"""
        code, out, err = self.run_gkg_runs(official_manifest(want="0" * 64, rid=self.rid))
        self.assertEqual(code, 0, err)
        self.assertIn("照らさなかった：R（run_id %s）の gkg-run-result の記録が無いので、%s の run-start の行の "
                      "trial_manifest_sha256 を" % (self.rid, OFFICIAL), out)
        with open(os.path.join(self.c, OFFICIAL), "wb") as f:      # 記録の無い run-start の行は、封印の前に空にする
            f.write(b"")
        self.sealed()
        self.commit("gkg-run-result")
        code, out, err = self.run_gkg_runs(official_manifest(self.body, rid=self.rid))
        self.assertEqual(code, 0, err)
        self.assertIn("%s の run-start の行 1 行の trial_manifest_sha256 は、R（run_id %s）の gkg-run-result（seq %d）が"
                      "縛る試しの run のマニフェスト" % (OFFICIAL, self.rid, self.res["seq"]), out)
        code, _out, err = self.run_gkg_runs(official_manifest(want="0" * 64, rid=self.rid))
        self.assertEqual(code, 1)
        self.assertIn("trial_manifest_sha256", err)


# ---- 4. N8・N11・N12

class TestN8FirstCommit(t73.Order2Case):
    def test_first_commit_manifest_used(self):
        """N8：記録を最初に含んだコミットでは、正式な run の run-start の trial_manifest_sha256 が合わず、行き先は
        「段に進む前に止まる」。HEAD では正式な run のマニフェストを空にし、行き先は試しの run の段になる。記録は
        試しの run の段の形。verify は最初のコミットの版で計算し直すので止まる（HEAD の版を使えば通ってしまう）。"""
        self.sealed()
        self.commit("gkg-run-result")
        path = os.path.join(self.c, OFFICIAL)
        bad = official_manifest(want="0" * 64, rid=self.rid)
        self.assertEqual(ledger.order2_plan(self.body, bad)["action"], "stop")
        self.assertEqual(ledger.order2_plan(self.body, b"")["action"], "stage")
        with order2_allowed():
            t73.TestChainWriterAndVerify.write(self, self.doc(), 2)       # 書く時点（HEAD）では正しい
            with open(path, "wb") as f:
                f.write(bad)
            self.commit("順番2の記録と、合わない正式な run のマニフェスト（同じコミット）")
            with open(path, "wb") as f:
                f.write(b"")
            self.commit("正式な run のマニフェストを空にする")
            code, _out, err = tl.run_verify_inproc(self.c, "stats-order")
        self.assertEqual(code, 1)
        self.assertIn("計算し直した行き先は「段に進む前に止まる」", err)


class TestN11N12(t73.Order2Case):
    def setUp(self):
        super().setUp()
        self.sealed()

    def test_n11_trial_input_needs_same_result(self):
        """N11：input_run が R（試しの run）なら、gkg_run_result は trial_result と同じでなければならない。R の
        gkg-run-result と同じ中身の別の記録（mode・run_id は R）を指すと止まる。"""
        n = self.res["seq"]
        dup = {"seq": n + 1, "kind": ledger.GKG_RESULT_KIND, "targets": [], "note": "R の結果の写し（テスト）"}
        o2 = {"seq": n + 2, "kind": O2}
        doc = self.doc(gkg_ref={"seq": dup["seq"], "record_sha256": line_sha(dup)})
        extra = {dup["seq"]: self.read(self.res, ledger.GKG_RESULT_KIND)}
        with self.assertRaisesRegex(ledger.LedgerError, "input_run が試しの run なのに、R（trial_result）と違う"):
            ledger.check_order2_run(self.recs + [dup, o2], o2, doc, self.reader(o2, doc, extra))
        # 同じ記録を指せば通る
        ok = self.doc()
        ledger.check_order2_run(self.recs + [dup, o2], o2, ok, self.reader(o2, ok, extra))

    def test_n12_pending_stops(self):
        """N12：計算し直した行き先が「待つ」なら止める。R の run-complete の前のマニフェストを縛る（形だけの）R の
        gkg-run-result の中身を読ませると、行き先は「待つ」になる。"""
        trial = self.body.split(b"\n", 1)[0] + b"\n"                     # R の run-start の行だけ
        self.assertEqual(ledger.order2_plan(trial, b"")["action"], "pending")
        rdoc = dict(self.read(self.res, ledger.GKG_RESULT_KIND), manifest_lines=1,
                    manifest_sha256=hashlib.sha256(trial).hexdigest())
        doc = self.doc()
        read = self.reader(self.o2, doc, {self.res["seq"]: rdoc})
        with self.assertRaisesRegex(ledger.LedgerError, "計算し直した行き先は「待つ」"):
            ledger.check_order2_plan(self.recs + [self.o2], self.o2, doc, read, trial, b"")


# ---- 5. まだコミットされていない順番2の記録

class TestUncommittedOrder2(t73.Order2Case):
    def test_uncommitted_is_unchecked(self):
        self.sealed()
        self.commit("gkg-run-result")
        with order2_allowed():
            rec, _rel, _ots = t73.TestChainWriterAndVerify.write(self, self.doc(), 2)
            code, out, err = tl.run_verify_inproc(self.c, "stats-order")
            self.assertEqual(code, 0, err)
            self.assertIn("照らさなかった：記録がまだコミットされていないので、seq %d の順番2の行き先" % rec["seq"], out)
            st = verify.State(self.c, None)
            got = ledger.check_stats_order(st.records, st.file_json)
            with contextlib.redirect_stdout(io.StringIO()):
                verify.check_order2_plans(st, got["order2"])
            self.assertIn("seq %d の順番2の行き先の計算し直し（記録がまだコミットされていない）" % rec["seq"], st.unchecked)
            # コミットしたあとは照らす
            self.commit("順番2（テスト）")
            code, out, err = tl.run_verify_inproc(self.c, "stats-order")
        self.assertEqual(code, 0, err)
        self.assertNotIn("記録がまだコミットされていない", out)
        self.assertIn("のマニフェストから計算し直した行き先（trial の段）と R は、記録と同じ", out)

    def test_commit_for_seq_strict_by_default(self):
        """partial を渡さない呼び方（targets --rev auto など）は、これまでどおりコミットに無い記録で失敗する。"""
        self.sealed()
        repo = verify.Repo(self.c)
        data = self.ledger_bytes()
        with self.assertRaisesRegex(ledger.LedgerError, "含むコミットが無い"):
            repo.commit_for_seq(data)
        got = repo.commit_for_seq(data, partial=True)
        self.assertNotIn(self.res["seq"], got)
        self.assertIn(self.res["seq"] - 1, got)


if __name__ == "__main__":
    unittest.main()
