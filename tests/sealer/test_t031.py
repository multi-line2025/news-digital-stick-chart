"""T-031 のテスト：GKG の取得の run の開始（kind: gkg-run-start）と、T-027 の監査の中1・軽1〜軽3。

実行（プロジェクトのルートで）:
    PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest discover -s tests/sealer -v

ネットワークは使わない（drand・ots は偽物）。仮のプロジェクト（git init したもの）で動かし、
本物の sealed/ には書かない。
  1. gkg-run-start：試しの run を 2 件書くと verify が 2 件を並べて表示する。official のあとに
     trial を書こうとすると止まる。method-access より前に書こうとすると止まる。中身のキーと値の照合。
     既存の採用の規則が変わらないこと。
  2. T-027 の監査の中1：seal_periods の書く前の照合（S1・S2・S5。scratchpad/au27r1.wBmY/probe_r1.py）と、
     method-access の関門の仮の採用での照合。軽2：1 件目の deadline_status が null でない記録で
     関門が止まる。
"""

import hashlib
import os
import re
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import test_ledger as tl  # noqa: E402
import test_t023 as t23  # noqa: E402
import test_writers as tw  # noqa: E402
from test_ledger import T0, H, run_verify  # noqa: E402

ledger = tl.ledger
import seal_gkg_run  # noqa: E402
import seal_records  # noqa: E402
import seal_triggers  # noqa: E402

DOC = os.path.join(tl.PROJECT, "docs", "verify", "periods-seal.md")
ROUND = 30_000_000
KEPT = "e" * 64                       # WriterCase.result の既定の kept_rows_sha256
TRIAL_DAYS = ["2015-03-02", "2015-03-03", "2015-03-04"]


class GkgCase(t23.JCase):
    """periods・candidates・手順3・method-access まで進めた仮のプロジェクトで、gkg-run-start を書く。"""

    def code_sha(self):
        with open(os.path.join(self.root, tw.CODE_REL), "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()

    def ready(self):
        self.seal()
        self.step3(T0 + H)
        self.method_rec, _r, _o = self.method(T0 + 3 * H)
        self.commit("手順4まで")

    def excl(self, seq=1):
        rec = [r for r in self.records() if r["seq"] == seq][0]
        return seq, hashlib.sha256(ledger.canonical_line(rec)).hexdigest()

    def start_run(self, now, mode="trial", days=TRIAL_DAYS, **over):
        ex_seq, ex_sha = self.excl()
        args = dict(mode=mode, code_rel=tw.CODE_REL, run_id=self.code_sha()[:16],
                    filelist_sha256=KEPT, method_access_seq=self.method_rec["seq"],
                    trial_days=days if mode == "trial" else None, exclusion_rule_seq=ex_seq,
                    exclusion_rule_record_sha256=ex_sha)
        args.update(over)
        return seal_gkg_run.start(self.root, now=now, ots_cmd="ots", drand_fetch=tw.FakeDrand(now),
                                  runner=tw.FakeOts(), **args)

    def raw_run(self, now, doc_over=None, mode="trial"):
        """gkg-run-start を、書く仕組みを通さずに足す（書く仕組みを飛ばした場合の再現）。"""
        data = self.ledger_bytes()
        seq = len(self.records()) + 1
        ex_seq, ex_sha = self.excl()
        m = next((r for r in self.records() if r["kind"] == ledger.METHOD_ACCESS_KIND), None)
        sha = self.code_sha()
        doc = {"kind": ledger.GKG_RUN_KIND, "step": 4, "mode": mode, "run_id": sha[:16],
               "code_path": tw.CODE_REL, "code_sha256": sha, "filelist_sha256": KEPT,
               "method_access_seq": None if m is None else m["seq"],
               "trial_days": TRIAL_DAYS if mode == "trial" else None,
               "exclusion_rule_seq": ex_seq, "exclusion_rule_record_sha256": ex_sha,
               "drand": tl.drand_doc(ledger.GKG_RUN_KIND, ROUND)["drand"],
               "ledger_head": ledger.expected_ledger_head(data, seq)}
        doc.update(doc_over or {})
        return self._append_doc(ledger.GKG_RUN_KIND, doc, now)


class TestGkgRunStart(GkgCase):
    def test_kind_is_allowed_with_drand_and_not_a_cut(self):
        self.assertIn("gkg-run-start", ledger.ALLOWED_KINDS)
        self.assertIn(ledger.GKG_RUN_KIND, ledger.DRAND_RECORD_KINDS)
        self.assertEqual(ledger.DRAND_RECORD_STEP[ledger.GKG_RUN_KIND], 4)
        self.assertIn(ledger.GKG_RUN_KIND, seal_records.WRITTEN_KINDS)
        self.assertNotIn(ledger.GKG_RUN_KIND, ledger.ADOPTED_KINDS)
        self.assertEqual(len(ledger.GKG_RUN_DOC_KEYS), 13)

    def test_two_trials_listed_by_verify(self):
        """完了条件：試しの run を 2 件書くと、verify が 2 件を並べて表示する。"""
        self.ready()
        r1, rel1, _o = self.start_run(T0 + 4 * H)
        r2, _rel2, _o = self.start_run(T0 + 5 * H, days=["2015-03-02"])
        self.assertEqual(self.doc_of(rel1)["trial_days"], TRIAL_DAYS)
        self.commit("試しの run")
        for args in (("gkg-runs",), ("all", "--rev", "auto")):
            out = self.verify_ok(*args)
            self.assertIn("試しの run 2 回、正式な run 0 回", out)
            rid = self.code_sha()[:16]
            self.assertIn("  seq %d  試しの run（trial）  run_id %s  code_sha256 %s（%s）  日 %s"
                          % (r1["seq"], rid, self.code_sha(), tw.CODE_REL, "、".join(TRIAL_DAYS)), out)
            self.assertIn("  seq %d  試しの run（trial）  run_id %s" % (r2["seq"], rid), out)
            self.assertIn("日 2015-03-02  一覧", out)
            self.assertLess(out.index("seq %d  試しの run" % r1["seq"]),
                            out.index("seq %d  試しの run" % r2["seq"]))

    def test_trial_after_official_refused(self):
        """完了条件：official の記録のあとに trial の記録を書こうとすると止まる。"""
        self.ready()
        self.start_run(T0 + 4 * H)
        off, _rel, _o = self.start_run(T0 + 5 * H, mode="official")
        self.verify_ok("gkg-runs")
        self.assert_writer_refuses(lambda: self.start_run(T0 + 6 * H),
                                   "official の記録（seq %d）より後に" % off["seq"])
        self.assert_writer_refuses(lambda: self.start_run(T0 + 6 * H, mode="official"),
                                   "official の gkg-run-start が 2 件ある")
        # 書く仕組みを飛ばして足しても、verify が止まる
        self.raw_run(T0 + 6 * H)
        self.verify_fails(("gkg-runs", "all"), "official の記録（seq %d）より後に" % off["seq"])

    def test_before_method_access_refused(self):
        """完了条件：method-access より前に書こうとすると止まる。"""
        self.seal()
        self.step3(T0 + H)
        self.commit("手順3まで")
        self.assert_writer_refuses(
            lambda: seal_gkg_run.start(self.root, "trial", tw.CODE_REL, self.code_sha()[:16], KEPT,
                                       5, TRIAL_DAYS, 1, self.excl()[1], T0 + 2 * H, "ots",
                                       drand_fetch=t23.t17.NoCall(),
                                       runner=tw.FakeOts()),
            "method-access の記録が無い")
        # 書く仕組みを飛ばして足しても、verify が止まる。あとで method-access を足しても止まる
        g = self.raw_run(T0 + 2 * H)
        self.verify_fails(("gkg-runs", "all"), "gkg-run-start の記録（seq %d）が、最初の method-access の"
                                               "記録より前にある" % g)
        self.add_method(T0 + 3 * H, ROUND)
        self.verify_fails(("gkg-runs",), "gkg-run-start の記録（seq %d）が、最初の method-access の"
                                         "記録（seq %d）より前にある" % (g, g + 1))

    def test_doc_values_checked(self):
        self.ready()
        sha = self.code_sha()
        cases = [
            (dict(run_id="0" * 16), "run_id"),
            (dict(filelist_sha256="f" * 64), "filelist_sha256"),
            (dict(method_access_seq=1), "method_access_seq"),
            (dict(days=["2015-03-03", "2015-03-02"]), "trial_days"),
            (dict(days=[]), "trial_days"),
            (dict(days=["2021-01-01"]), "区画"),
            (dict(days=["2015-02-30"]), "trial_days"),
            (dict(exclusion_rule_seq=99), "exclusion_rule_seq"),
            (dict(exclusion_rule_record_sha256="0" * 64), "exclusion_rule_record_sha256"),
            (dict(mode="other"), "mode"),
        ]
        for over, msg in cases:
            self.assert_writer_refuses(lambda: self.start_run(T0 + 4 * H, **over), msg)
        # official に trial_days を入れたもの・キーを足したもの（書く仕組みを飛ばす）は verify で止まる
        self.assertTrue(sha)
        g = self.raw_run(T0 + 4 * H, {"mode": "official", "trial_days": TRIAL_DAYS}, mode="official")
        self.verify_fails(("gkg-runs",), "seq %d の gkg-run-start（official）の trial_days が null でない" % g)

    def test_extra_key_refused(self):
        self.ready()
        g = self.raw_run(T0 + 4 * H, {"store": "/Volumes/x"})
        self.verify_fails(("gkg-runs", "all"), "seq %d の gkg-run-start の中身のキーが、決まった 13 個" % g)

    def test_uncommitted_code_refused(self):
        self.ready()
        with open(os.path.join(self.root, tw.CODE_REL), "a") as f:
            f.write("# changed\n")
        self.assert_writer_refuses(lambda: self.start_run(T0 + 4 * H), "HEAD のコミットの中身と違う")

    def test_adoption_unchanged(self):
        """gkg-run-start は採用の区切りにならない（threshold-access のまま）。"""
        self.ready()
        self.start_run(T0 + 4 * H)
        out = self.verify_ok("adopted")
        self.assertIn("採用は保留（threshold-access の記録が無いため）", out)
        access, _r, _o = self.write_access(T0 + 5 * H)
        self.start_run(T0 + 6 * H, mode="official")
        out = self.verify_ok("all")
        self.assertIn("区切り：最初の threshold-access の記録 = seq %d" % access["seq"], out)
        self.assertIn("試しの run 1 回、正式な run 1 回", out)

    def test_cli_rejects_unknown_mode_and_abbreviation(self):
        for argv in (["start", "--mode", "other"], ["start", "--mod", "trial"]):
            with self.assertRaises(SystemExit) as cm, \
                    tl.contextlib.redirect_stderr(tl.io.StringIO()):
                seal_gkg_run.main(argv)
            self.assertEqual(cm.exception.code, 2)


# ---------------------------------------------------------------- 2. T-027 の監査の中1・軽2


class TestSealPeriodsPrecheck(t23.JCase):
    """seal_periods の、threshold-access より前の 2 件目以降の版の書く前の照合（T-027 の監査 中1）。"""

    def rebuilt(self, args, now):
        sha = ledger.sha256_hex(tl.seal_periods.run_periods(self.root, args))
        return self.seal(args=args, sha=sha, now=now, with_cand=False)

    def nw_rebuilt(self):
        self.seal()
        self.step3(T0 + H)
        self.method(T0 + 3 * H)
        self.seal_triggers(T0 + 4 * H, network_window_days=500)
        return self.rebuilt(["--nwonly", "before_deadline"], T0 + 5 * H)

    def test_s1_second_rebuild_without_triggers(self):
        """S1：triggers を足さずに 3 件目の版（網の日数と同じ週の年数）を書く。"""
        prec = self.nw_rebuilt()
        self.assert_periods_writer_refuses(["--nwonly", "--sw3", "before_deadline"], T0 + 6 * H,
                                           "periods-triggers の最後の記録（seq 6、")
        # 先に triggers を足そうとしても、既にある before_deadline の版と違うので止まる（T-027）
        self.assert_writer_refuses(
            lambda: seal_triggers.seal(self.root, {"network_window_days": 500, "same_week_years": 3},
                                       T0 + 6 * H, None),
            "periods の 2 件目（seq %d）が before_deadline" % prec["seq"])
        self.method_gate()
        self.write_access(T0 + 7 * H)
        self.verify_ok("all")

    def test_s2_j_differs_from_candidates(self):
        """S2：候補の J の最大（28）と違う J（60）で版を書く（triggers 無しでも、先に足しても止まる）。"""
        self.seal()
        self.step3(T0 + H)
        self.assert_periods_writer_refuses(["--j60", "before_deadline"], T0 + 2 * H,
                                           "periods-triggers の最後の記録（無し）")
        self.seal_triggers(T0 + 2 * H, last_read_offset_days=60)
        self.assert_periods_writer_refuses(["--j60", "before_deadline"], T0 + 3 * H,
                                           "J（last_read_offset_days 60）が、candidates の J の最大 28 と違う")
        # 書く仕組みを飛ばすと、method-access の書く仕組みと関門で止まる（J の照合）
        self.raw_periods(["--j60", "before_deadline"], T0 + 3 * H)
        self.assert_writer_refuses(lambda: self.method(T0 + 4 * H), "60")

    def test_s5_after_label_with_same_values(self):
        """S5：最後の triggers と同じ値の版に after_deadline と申告する。"""
        self.nw_rebuilt()
        self.assert_periods_writer_refuses(["--nwonly", "after_deadline"], T0 + 6 * H,
                                           "after_deadline の版の rebuild_triggers")
        # 書く仕組みを飛ばすと、method-access の関門（仮の採用）・seal_access・関門で止まる
        v = self.raw_periods(["--nwonly", "after_deadline"], T0 + 6 * H)
        msg = "3 件目（seq %d）: after_deadline と申告しているが" % v
        with self.assertRaisesRegex(ledger.MethodAccessRequired, re.escape(msg)):
            self.method_gate()
        with self.assertRaisesRegex(ledger.MethodAccessRequired, "仮の採用"):
            self.method_gate()
        self.assert_writer_refuses(lambda: self.write_access(T0 + 7 * H), msg)
        self.add_access(T0 + 7 * H, ROUND)
        self.verify_fails(("periods", "all"), "3 件目: after_deadline と申告しているが")
        with self.assertRaisesRegex(ledger.ThresholdAccessRequired, re.escape(msg)):
            self.threshold_gate()

    def test_after_deadline_with_different_values_is_not_refused(self):
        """after_deadline は、最後の triggers と違う値なら書ける（S3・S4 の形）。この申告を期限の前に
        使ってはいけないことは、手順書にだけ書いてある（照合では止めない。軽1）。"""
        self.nw_rebuilt()
        self.rebuilt(["--nwonly", "--sw3", "after_deadline"], T0 + 6 * H)
        self.method_gate()
        self.write_access(T0 + 7 * H)
        out = self.verify_ok("periods")
        self.assertIn("deadline_status の申告 after_deadline、記録から決まる値 after_deadline", out)

    def test_null_status_with_triggers_refused(self):
        self.seal()
        self.seal_triggers(T0 + H, network_window_days=500)
        self.assert_periods_writer_refuses(["--nwonly", "unknown"], T0 + 2 * H,
                                           "きっかけの値があるのに deadline_status が 'unknown'")

    def test_matching_rebuild_passes(self):
        self.nw_rebuilt()
        self.rebuilt(["--nwonly", "before_deadline"], T0 + 6 * H)     # 同じ値の版はもう一度書ける
        self.method_gate()
        self.write_access(T0 + 7 * H)
        self.verify_ok("all")
        self.threshold_gate()

    def test_after_threshold_access_not_checked(self):
        """threshold-access の後の版は、今までどおり書く前に止めない（採用されない）。"""
        self.seal()
        self.step3(T0 + H)
        self.write_access(T0 + 2 * H)
        self.rebuilt(["--j60", "before_deadline"], T0 + 3 * H)

    def test_method_gate_provisional(self):
        """method-access の関門は、threshold-access がまだ無ければ、最後の triggers を仮の採用として
        deadline_status を照合する。"""
        self.nw_rebuilt()
        self.method_gate()
        self.raw_triggers(T0 + 6 * H, network_window_days=600)
        with self.assertRaisesRegex(ledger.MethodAccessRequired,
                                    "仮の採用として比べた）: 2 件目（seq 7）: before_deadline と申告"):
            self.method_gate()


class TestFirstStatusGate(t23.JCase):
    """軽2：periods の 1 件目の deadline_status が null でない記録で、関門と seal_access が止まる。"""

    def test_first_version_status_not_null(self):
        # 1 件目を、書く仕組みを飛ばして deadline_status 付きで足す
        self.raw_periods(["--j60", "before_deadline"], T0)
        self.add_cand(T0 + H / 2)
        self.step3(T0 + H)
        self.method(T0 + 3 * H)
        msg = "1 件目: deadline_status が null でない"
        with self.assertRaisesRegex(ledger.MethodAccessRequired, msg):
            self.method_gate()
        self.assert_writer_refuses(lambda: self.write_access(T0 + 4 * H), msg)
        self.add_access(T0 + 4 * H, ROUND)
        with self.assertRaisesRegex(ledger.ThresholdAccessRequired, msg):
            self.threshold_gate()
        self.verify_fails(("periods",), "最初の版の deadline_status が null でない")


# ---------------------------------------------------------------- 3. 手順書


class TestDocT031(unittest.TestCase):
    def setUp(self):
        with open(DOC, encoding="utf-8") as f:
            self.text = f.read()

    def test_kind_table_and_chapter(self):
        self.assertIn("下の表の8つだけ", self.text)
        self.assertIn("| `gkg-run-start` |", self.text)
        self.assertIn("## 12. GKG の取得の run の開始（gkg-run-start。T-031）", self.text)
        for k in ledger.GKG_RUN_DOC_KEYS:
            self.assertIn("`%s`" % k, self.text)

    def test_light1_and_mid1_statements(self):
        self.assertIn("after_deadline の申告を、期限の前に使ってはいけない", self.text)
        self.assertIn("`ledger.check_periods_version_append`", self.text)
        self.assertIn("`seal_periods.py` も", self.text)


if __name__ == "__main__":
    unittest.main()
