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
import json
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
        # T-037：gkg-run-start の前に順番1・順番1b が要り、どちらも method-access より前に置く
        # （どちらも step3 が足す。T-043）
        self.method_rec, _r, _o = self.method(T0 + 3 * H)
        self.commit("手順4まで")

    def excl(self, seq=None):
        """除外の規則の記録の seq と行の sha256。既定は stats-order1 の最初の記録（T-037）。"""
        if seq is None:
            seq = ledger.first_order1(self.records())["seq"]
        rec = [r for r in self.records() if r["seq"] == seq][0]
        return seq, hashlib.sha256(ledger.canonical_line(rec)).hexdigest()

    def start_run(self, now, mode="trial", days=TRIAL_DAYS, manifest=True, **over):
        ex_seq, ex_sha = self.excl()
        args = dict(mode=mode, code_rel=tw.CODE_REL, run_id=self.code_sha()[:16],
                    filelist_sha256=KEPT, method_access_seq=self.method_rec["seq"],
                    trial_days=days if mode == "trial" else None, exclusion_rule_seq=ex_seq,
                    exclusion_rule_record_sha256=ex_sha)
        args.update(over)
        got = seal_gkg_run.start(self.root, now=now, ots_cmd="ots", drand_fetch=tw.FakeDrand(now),
                                 runner=tw.FakeOts(), **args)
        if manifest:
            self.append_manifest(got[0])
        return got

    # ---- 収集係のマニフェストの run-start の行（T-043：記録があるのに行が無ければ verify が止まるので、
    # 収集係と同じく、記録を書いたら行を足す）
    def manifest_row(self, rec, **over):
        doc = ledger.read_target_json(self.root, rec, ledger.GKG_RUN_KIND)
        row = {"kind": "run-start", "mode": doc["mode"], "run_id": doc["run_id"],
               "gkg_run_seq": rec["seq"],
               "gkg_run_record_sha256": hashlib.sha256(ledger.canonical_line(rec)).hexdigest()}
        if doc["mode"] == "official":
            row["trial_run_ids"] = [ledger.read_target_json(self.root, r, ledger.GKG_RUN_KIND)["run_id"]
                                    for r in self.records() if r["kind"] == ledger.GKG_RUN_KIND
                                    and r["seq"] < rec["seq"]
                                    and ledger.read_target_json(self.root, r, ledger.GKG_RUN_KIND)["mode"]
                                    == "trial"]
        row.update(over)
        return row

    def append_manifest(self, rec, **over):
        doc = ledger.read_target_json(self.root, rec, ledger.GKG_RUN_KIND)
        rel = ledger.GKG_MANIFESTS[doc["mode"]]
        full = os.path.join(self.root, rel)
        with open(full, "a", encoding="utf-8") as f:
            f.write(json.dumps(self.manifest_row(rec, **over), sort_keys=True) + "\n")
        for other in ledger.GKG_MANIFESTS.values():      # もう一方の mode は空のマニフェストを置く
            if not os.path.exists(os.path.join(self.root, other)):
                open(os.path.join(self.root, other), "a").close()

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

    def change_code(self):
        """取得のコードを変えてコミットする（run_id が変わる。2 件目の試しの run のため）。"""
        with open(os.path.join(self.root, tw.CODE_REL), "a") as f:
            f.write("# 試しの run のあとで直した\n")
        self.commit("コードを直した")

    def test_two_trials_listed_by_verify(self):
        """完了条件：試しの run を 2 件書くと、verify が 2 件を並べて表示する。2 件目は、コードを
        直したあとの別の run（同じ run_id の trial は 2 件書けない。差し戻し1回目の中3）。"""
        self.ready()
        sha1 = self.code_sha()
        r1, rel1, _o = self.start_run(T0 + 4 * H)
        self.change_code()
        sha2 = self.code_sha()
        r2, _rel2, _o = self.start_run(T0 + 5 * H)
        self.assertEqual(self.doc_of(rel1)["trial_days"], TRIAL_DAYS)
        self.commit("試しの run")
        # T-056：仮の順番1・1b の記録（head が実在しない）では、--rev auto の順番1・1b の計算し直しが止まるので、
        # 時刻証明と対象のファイルは targets --rev auto で、残りは all（working）で確かめる
        self.verify_ok("targets", "--rev", "auto")
        for args in (("gkg-runs",), ("all",)):
            out = self.verify_ok(*args)
            self.assertIn("試しの run 2 回、正式な run 0 回", out)
            self.assertIn("  seq %d  試しの run（trial）  run_id %s  code_sha256 %s（%s）  日 %s"
                          % (r1["seq"], sha1[:16], sha1, tw.CODE_REL, "、".join(TRIAL_DAYS)), out)
            self.assertIn("  seq %d  試しの run（trial）  run_id %s  code_sha256 %s"
                          % (r2["seq"], sha2[:16], sha2), out)
            self.assertIn("日 2015-03-02、2015-03-03、2015-03-04  一覧", out)
            self.assertLess(out.index("seq %d  試しの run" % r1["seq"]),
                            out.index("seq %d  試しの run" % r2["seq"]))

    def test_trial_after_official_refused(self):
        """完了条件：official の記録のあとに trial の記録を書こうとすると止まる。"""
        self.ready()
        self.start_run(T0 + 4 * H)
        off, _rel, _o = self.start_run(T0 + 5 * H, mode="official")
        self.verify_ok("gkg-runs")
        # 同じ run_id の trial（使い回しの候補）は、official があるので使い回さない（T-043）
        self.assert_writer_refuses(lambda: self.start_run(T0 + 6 * H),
                                   "official の記録があるので、試しの run の記録")
        # 別の run_id の trial は、official より後には書けない
        self.change_code()
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
        self.add_order1b(T0 + 2 * H)       # T-037：順番1（step3 が足す）と順番1b はある
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
        """gkg-run-start は採用の区切りにならない（threshold-access のまま）。差し戻し1回目の中2：
        threshold-access の後には書けない（書く仕組みは drand の前に止まり、飛ばすと verify で止まる）。"""
        self.ready()
        self.start_run(T0 + 4 * H)
        self.start_run(T0 + 5 * H, mode="official")
        out = self.verify_ok("adopted")
        self.assertIn("採用は保留（threshold-access の記録が無いため）", out)
        self.assertIn("acquisition-result・method-access・gkg-run-start・stats-order1・stats-order1b は"
                      "区切りに使わない", out)
        access, _r, _o = self.write_access(T0 + 6 * H)
        out = self.verify_ok("all")
        self.assertIn("区切り：最初の threshold-access の記録 = seq %d" % access["seq"], out)
        self.assertIn("試しの run 1 回、正式な run 1 回", out)

    def test_probe_b_after_threshold_access_refused(self):
        """監査の probe31.py の test_b：threshold-access の後の trial・official は、drand の前に止まる。"""
        self.ready()
        access, _r, _o = self.write_access(T0 + 4 * H)
        for mode in ("trial", "official"):
            self.assert_writer_refuses(
                lambda: seal_gkg_run.start(self.root, mode, tw.CODE_REL, self.code_sha()[:16], KEPT,
                                           self.method_rec["seq"],
                                           TRIAL_DAYS if mode == "trial" else None,
                                           self.excl()[0], self.excl()[1], T0 + 5 * H, "ots",
                                           drand_fetch=t23.t17.NoCall(), runner=tw.FakeOts()),
                "threshold-access の記録（seq %d）がある" % access["seq"])
        g = self.raw_run(T0 + 5 * H)
        self.verify_fails(("gkg-runs", "all"), "gkg-run-start の記録（seq %d）が、最初の threshold-access の"
                                               "記録（seq %d）より後にある" % (g, access["seq"]))

    def test_probe_a_inputs_cannot_be_reselected(self):
        """監査の probe31.py の test_a：試しの run のあとで、新しい手順3の一覧や、試しの run の記録を
        除外の規則として指す正式な run は書けない（差し戻し1回目の中1）。"""
        self.ready()
        tr, _r, _o = self.start_run(T0 + 4 * H)
        s, _r1, _o1 = self.start(T0 + 5 * H)
        self.result(T0 + 6 * H, s["seq"], kept="d" * 64)
        trec = [x for x in self.records() if x["seq"] == tr["seq"]][0]
        tr_sha = hashlib.sha256(ledger.canonical_line(trec)).hexdigest()
        o1 = self.excl()[0]
        self.assert_writer_refuses(
            lambda: self.start_run(T0 + 7 * H, mode="official", filelist_sha256="d" * 64,
                                   exclusion_rule_seq=tr["seq"], exclusion_rule_record_sha256=tr_sha),
            "exclusion_rule_seq %d が、除外の規則の kind（stats-order1）の最初の記録の seq %d でない"
            % (tr["seq"], o1))
        self.assert_writer_refuses(
            lambda: self.start_run(T0 + 7 * H, mode="official", filelist_sha256="d" * 64),
            "filelist_sha256")
        seq2 = self.excl(2)
        self.assert_writer_refuses(
            lambda: self.start_run(T0 + 7 * H, mode="official", exclusion_rule_seq=seq2[0],
                                   exclusion_rule_record_sha256=seq2[1]),
            "exclusion_rule_seq 2 が、除外の規則の kind（stats-order1）の最初の記録の seq %d でない" % o1)
        # 書く仕組みを飛ばして、試しの run の記録を除外の規則として指すと、verify で止まる
        g = self.raw_run(T0 + 7 * H, {"exclusion_rule_seq": tr["seq"],
                                     "exclusion_rule_record_sha256": tr_sha}, mode="official")
        self.verify_fails(("gkg-runs",), "seq %d の gkg-run-start の exclusion_rule_seq %d が、除外の規則の "
                                         "kind（stats-order1）の最初の記録の seq（%d）でない" % (g, tr["seq"], o1))

    def test_probe_a_honest_official_passes(self):
        """正直な流れ（同じ一覧・同じ除外の規則の記録）は止まらない。"""
        self.ready()
        self.start_run(T0 + 4 * H)
        self.start_run(T0 + 5 * H, mode="official")
        self.verify_ok("gkg-runs")

    def test_filelist_needs_single_result_before_method(self):
        """最初の method-access より前の acquisition-result が 2 件なら、どの一覧かを決められないので止まる。"""
        self.seal()
        self.step3(T0 + H)
        self.step3(T0 + 2 * H)
        self.add_order1b(T0 + 3 * H)
        self.method_rec, _r, _o = self.method(T0 + 4 * H)
        self.commit("手順4まで")
        self.assert_writer_refuses(lambda: self.start_run(T0 + 5 * H), "ちょうど 1 件でない")

    def test_probe_c_duplicate_trial_and_days(self):
        """監査の probe31.py の test_c：同じ run_id の trial の 2 件目と、4 日以上の trial は、drand の前に
        止まる（差し戻し1回目の中3）。"""
        self.ready()
        tr, _r, _o = self.start_run(T0 + 4 * H)
        nocall = dict(drand_fetch=t23.t17.NoCall())
        self.assert_writer_refuses(
            lambda: seal_gkg_run.start(self.root, "trial", tw.CODE_REL, self.code_sha()[:16], KEPT,
                                       self.method_rec["seq"], TRIAL_DAYS, self.excl()[0], self.excl()[1],
                                       T0 + 5 * H, "ots", runner=tw.FakeOts(), **nocall),
            # T-043：同じ run_id の trial は使い回しを試み、run-start の行が既にあるので止まる
            "gkg-run-start（seq %d）には run-start の行が既にある" % tr["seq"])
        self.change_code()
        import datetime as _dt
        d0 = _dt.date(2015, 3, 2)
        for n in (4, 400):
            days = [(d0 + _dt.timedelta(days=k)).isoformat() for k in range(n)]
            self.assert_writer_refuses(
                lambda: seal_gkg_run.start(self.root, "trial", tw.CODE_REL, self.code_sha()[:16], KEPT,
                                           self.method_rec["seq"], days, self.excl()[0], self.excl()[1],
                                           T0 + 5 * H, "ots", runner=tw.FakeOts(), **nocall),
                "trial_days は 1〜3 日の一覧")
        # 書く仕組みを飛ばした場合：同じ run_id の trial と、4 日の trial は verify で止まる
        self.change_code()
        g = self.raw_run(T0 + 5 * H, {"trial_days": ["2015-03-02", "2015-03-03", "2015-03-04",
                                                     "2015-03-05"]})
        self.verify_fails(("gkg-runs",), "seq %d の gkg-run-start（trial）の trial_days" % g)

    def test_duplicate_trial_run_id_fails_verify(self):
        self.ready()
        tr, _r, _o = self.start_run(T0 + 4 * H)
        g = self.raw_run(T0 + 5 * H)
        self.verify_fails(("gkg-runs", "all"), "run_id %s が、seq %d と同じ" % (self.code_sha()[:16], tr["seq"]))

    def test_verify_checks_run_id_and_exclusion_position(self):
        """軽1：verify の側の run_id の照合と、exclusion_rule_seq の位置の照合（書く仕組みを飛ばす）。"""
        self.ready()
        g = self.raw_run(T0 + 4 * H, {"run_id": "0" * 16})
        self.verify_fails(("gkg-runs", "all"), "seq %d の gkg-run-start の run_id が、code_sha256 の先頭" % g)

    def test_verify_checks_exclusion_position(self):
        self.ready()
        data = self.ledger_bytes()
        seq = len(self.records()) + 1
        # 自分自身の seq を指す（sha256 は合わせようがないので、位置の照合で止まることを見る）
        g = self.raw_run(T0 + 4 * H, {"exclusion_rule_seq": seq})
        self.assertEqual(g, seq)
        self.assertTrue(data)
        self.verify_fails(("gkg-runs", "all"),
                          "seq %d の gkg-run-start の exclusion_rule_seq %d が、除外の規則の kind（stats-order1）の"
                          "最初の記録の seq（%d）でない" % (g, g, self.excl()[0]))

    def test_precheck_stops_before_drand(self):
        """軽1：official が既にあるときと、method-access が無いときは、drand を呼ぶ前に止まる。"""
        self.ready()
        self.start_run(T0 + 4 * H, mode="official")
        for mode in ("trial", "official"):
            self.assert_writer_refuses(
                lambda: seal_gkg_run.start(self.root, mode, tw.CODE_REL, self.code_sha()[:16], KEPT,
                                           self.method_rec["seq"],
                                           TRIAL_DAYS if mode == "trial" else None,
                                           self.excl()[0], self.excl()[1], T0 + 5 * H, "ots",
                                           drand_fetch=t23.t17.NoCall(), runner=tw.FakeOts()),
                # T-043：同じ run_id の official は使い回しを試み、run-start の行があるので止まる
                "official" if mode == "trial" else "run-start の行が既にある")

    def test_honest_flow_passes(self):
        """正直な流れ：試しの run 2 回（コードを直して）、正式な run 1 回、そのあと threshold-access。"""
        self.ready()
        self.start_run(T0 + 4 * H)
        self.change_code()
        self.start_run(T0 + 5 * H)
        self.start_run(T0 + 6 * H, mode="official")
        self.write_access(T0 + 7 * H)
        self.commit("記録")
        # T-056：仮の順番1・1b の記録（head が実在しない）では、--rev auto の順番1・1b の計算し直しが止まるので、
        # 時刻証明と対象のファイルは targets --rev auto で、残りは all（working）で確かめる
        self.verify_ok("targets", "--rev", "auto")
        out = self.verify_ok("all")
        self.assertIn("試しの run 2 回、正式な run 1 回", out)
        self.method_gate()
        self.threshold_gate()

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
        last_t = [r for r in self.records() if r["kind"] == ledger.TRIGGERS_KIND][-1]
        self.assert_periods_writer_refuses(["--nwonly", "--sw3", "before_deadline"], T0 + 6 * H,
                                           "periods-triggers の最後の記録（seq %d、" % last_t["seq"])
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
                                           "deadline_status が after_deadline の版")
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

    def test_after_deadline_before_deadline_refused(self):
        """差し戻し1回目の中4：期限（threshold-access）の前の after_deadline の版は、値に関わらず
        書かない（S3・S4、probe31.py の test_e）。期限の後なら今までどおり書ける。"""
        self.nw_rebuilt()
        self.assert_periods_writer_refuses(["--nwonly", "--sw3", "after_deadline"], T0 + 6 * H,
                                           "deadline_status が after_deadline の版")
        self.write_access(T0 + 7 * H)
        self.seal_triggers(T0 + 8 * H, network_window_days=500, same_week_years=3)
        self.rebuilt(["--nwonly", "--sw3", "after_deadline"], T0 + 9 * H)
        out = self.verify_ok("periods")
        self.assertIn("deadline_status の申告 after_deadline、記録から決まる値 after_deadline", out)

    def test_probe_e_after_deadline_without_triggers(self):
        """probe31.py の test_e と probe31b.py：triggers の無いまま after_deadline の版を書く。"""
        self.seal()
        self.step3(T0 + H)
        self.assert_periods_writer_refuses(["--nwonly", "after_deadline"], T0 + 2 * H,
                                           "deadline_status が after_deadline の版")
        # 正直な流れ（triggers を足してから before_deadline で作り直す）は止まらない
        self.seal_triggers(T0 + 3 * H, network_window_days=500)
        self.rebuilt(["--nwonly", "before_deadline"], T0 + 4 * H)
        self.method(T0 + 5 * H)
        self.method_gate()

    def test_triggers_same_as_after_deadline_version_refused(self):
        """差し戻し1回目の中4：after_deadline の版（書く仕組みを飛ばして作ったもの）と同じ値の
        periods-triggers は、seal_triggers が拒む。"""
        self.seal()
        self.step3(T0 + H)
        v = self.raw_periods(["--nwonly", "after_deadline"], T0 + 2 * H)
        self.assert_writer_refuses(
            lambda: seal_triggers.seal(self.root, {"network_window_days": 500}, T0 + 3 * H, None),
            "periods の 2 件目（seq %d）が after_deadline で、その rebuild_triggers と" % v)

    def test_probe_d_method_writer_provisional(self):
        """probe31.py の test_d：仮の採用での deadline_status の照合に通らないとき、seal_method も書かない
        （差し戻し1回目の軽2）。"""
        self.seal()
        self.step3(T0 + H)
        self.seal_triggers(T0 + 2 * H, network_window_days=500)
        prec = self.rebuilt(["--nwonly", "before_deadline"], T0 + 3 * H)
        self.raw_triggers(T0 + 4 * H, network_window_days=600)
        self.assert_writer_refuses(lambda: self.method(T0 + 5 * H),
                                   "2 件目（seq %d）: before_deadline と申告しているが" % prec["seq"])
        # 直す：前の版と同じ値の triggers を足せば、それが仮の採用になり、書ける
        self.seal_triggers(T0 + 5 * H, network_window_days=500)
        self.method(T0 + 6 * H)
        self.method_gate()

    def test_status_without_triggers_refused(self):
        """軽1：きっかけの値が無いのに deadline_status が null でない版は書かない。"""
        self.seal()
        self.assert_periods_writer_refuses(["--stonly", "before_deadline"], T0 + H,
                                           "きっかけの値が無いのに deadline_status が 'before_deadline'")

    def test_j_version_before_candidates_refused(self):
        """軽4：candidates の記録がまだ無いうちは、J を持つ版を書かない（あとで J の最大が違うと
        行き詰まるため）。"""
        self.seal(with_cand=False)
        self.seal_triggers(T0 + H, last_read_offset_days=60)
        self.assert_periods_writer_refuses(["--j60", "before_deadline"], T0 + 2 * H,
                                           "candidates の記録がまだ無いので")

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
        prec = [r for r in self.records() if r["kind"] == ledger.PERIODS_KIND][1]
        with self.assertRaisesRegex(ledger.MethodAccessRequired,
                                    "仮の採用として比べた）: 2 件目（seq %d）: before_deadline と申告" % prec["seq"]):
            self.method_gate()


class TestFirstStatusGate(t23.JCase):
    """軽2：periods の 1 件目の deadline_status が null でない記録で、関門と seal_access が止まる。"""

    def test_first_version_status_not_null(self):
        # 1 件目を、書く仕組みを飛ばして deadline_status 付きで足す
        self.raw_periods(["--j60", "before_deadline"], T0)
        self.add_cand(T0 + H / 2)
        self.step3(T0 + H)
        msg = "1 件目: deadline_status が null でない"
        # T-031 の差し戻し1回目の軽2：seal_method も書かない。飛ばして足す
        self.assert_writer_refuses(lambda: self.method(T0 + 3 * H), msg)
        self.add_method(T0 + 3 * H, ROUND)
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
        self.assertIn("下の表の10だけ", self.text)   # T-037
        self.assertIn("| `gkg-run-start` |", self.text)
        self.assertIn("## 12. GKG の取得の run の開始（gkg-run-start。T-031）", self.text)
        for k in ledger.GKG_RUN_DOC_KEYS:
            self.assertIn("`%s`" % k, self.text)

    def test_resubmission1_statements(self):
        """差し戻し1回目の中1〜中4・軽2・軽4・軽5 の記述。"""
        for phrase in ("run の単位（T-031 の差し戻し1回目の中3）", "同じ run の再開では書かない",
                       "最初の `threshold-access` より前にある", "ただ1件の `acquisition-result`",
                       "どの run も同じ入力", "除外の規則の kind（`stats-order1`。13章）の最初の記録の seq",   # T-037
                       "期限の前の `after_deadline` の版を書かない", "`candidates` の記録がまだ無いうちは",
                       "書く仕組み（`seal_method.py`。T-031 の差し戻し1回目の軽2）",
                       "drand を取ったあと、書く前に行い", "`gkg-run-start`（GKG の取得の run の開始。12章。T-031）も、区切りに使わない"):
            self.assertIn(phrase, self.text)
        self.assertNotIn("**形の上では、`after_deadline` と申告した版を書けば、値を変えられる。**", self.text)

    def test_light1_and_mid1_statements(self):
        self.assertIn("after_deadline の申告を、期限の前に使ってはいけない", self.text)
        self.assertIn("`ledger.check_periods_version_append`", self.text)
        self.assertIn("`seal_periods.py` も", self.text)


if __name__ == "__main__":
    unittest.main()
