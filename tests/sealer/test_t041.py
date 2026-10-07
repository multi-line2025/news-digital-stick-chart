"""T-041 のテスト：gkg-run-start の記録と、収集係のマニフェストの run-start の行の照合
（T-031 の監査 中1 の残り）と、手順書の記述。

実行（プロジェクトのルートで）:
    PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest discover -s tests/sealer -v

ネットワークは使わない（drand・ots は偽物）。仮のプロジェクトで動かし、本物の sealed/ には書かない。
「順番1 が無ければ method-access も止まる」のテストは tests/sealer/test_t037.py の
TestWithoutOrder1.test_method_and_gkg_refused_without_order1 にある。
"""

import hashlib
import json
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import subprocess  # noqa: E402
import test_ledger as tl  # noqa: E402
import test_t031 as t31  # noqa: E402
import seal_gkg_run  # noqa: E402
from test_ledger import T0, H  # noqa: E402

ledger = tl.ledger
DOC = os.path.join(tl.PROJECT, "docs", "verify", "periods-seal.md")
TRIAL = ledger.GKG_MANIFESTS["trial"]
OFFICIAL = ledger.GKG_MANIFESTS["official"]


class FailStamp(t31.tw.FakeOts):
    """ots stamp だけが失敗する runner（監査のプローブ scratchpad/a41probe と同じ）。"""

    def __call__(self, cmd, input=None, capture_output=True, timeout=None):
        if "stamp" in cmd:
            return subprocess.CompletedProcess(cmd, 1, stdout=b"", stderr=b"calendar down")
        return super().__call__(cmd, input=input, capture_output=capture_output, timeout=timeout)


class TestGkgManifests(t31.GkgCase):
    change_code = t31.TestGkgRunStart.change_code     # 取得のコードを直してコミットする（run_id が変わる）

    def row(self, rec, **over):
        """run-start の行（収集係の gkg.py の形のうち、照らす欄だけ。正式な run は trial_run_ids も）。"""
        return self.manifest_row(rec, **over)

    def write_manifest(self, rel, rows):
        full = os.path.join(self.root, rel)
        with open(full, "w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, sort_keys=True) + "\n")

    def test_honest_trial_and_official(self):
        """正直な流れ：試しの run 2 回（コードを直して）と正式な run 1 回。同じ run_id の行が 2 行ある
        （やり直し）のは通す。"""
        self.ready()
        t1, _r, _o = self.start_run(T0 + 4 * H)
        self.change_code()
        t2, _r, _o = self.start_run(T0 + 5 * H)
        off, _r, _o = self.start_run(T0 + 6 * H, mode="official")
        self.write_manifest(TRIAL, [self.row(t1), {"kind": "day", "run_id": "x"}, self.row(t1),
                                    self.row(t2)])
        self.write_manifest(OFFICIAL, [self.row(off)])
        out = self.verify_ok("gkg-runs")
        self.assertIn("%s：run-start の行 3 行、異なる run_id 2 個" % TRIAL, out)
        self.assertIn("%s：run-start の行 1 行、異なる run_id 1 個" % OFFICIAL, out)
        out = self.verify_ok("all")
        self.assertNotIn("ただし、次は照らさなかった", out)

    def test_missing_manifest_without_records_is_reported(self):
        """記録が 0 件でマニフェストも無いときは、今のまま「照らさなかった」（終了コード 0）。"""
        self.ready()
        out = self.verify_ok("all")
        self.assertIn("照らさなかった：%s が無いので" % TRIAL, out)
        self.assertIn("ただし、次は照らさなかった（終了コード 0 は、照らした検査がすべて通ったことだけを示す）：", out)
        self.assertIn("%s の run-start の行と gkg-run-start の記録の照合（マニフェストが無い）" % OFFICIAL, out)

    def test_missing_manifest_with_records_fails(self):
        """軽-1：その mode の記録が 1 件以上あるのにマニフェストが無ければ失敗。"""
        self.ready()
        t1, _r, _o = self.start_run(T0 + 4 * H, manifest=False)
        self.verify_fails(("gkg-runs", "all"), "%s が無いのに、mode trial の gkg-run-start の記録がある（seq %d）"
                          % (TRIAL, t1["seq"]))

    def test_manifest_not_regular_file_fails(self):
        """軽-1：マニフェストが symlink やディレクトリなら失敗。"""
        self.ready()
        os.makedirs(os.path.join(self.root, TRIAL))
        self.verify_fails(("gkg-runs",), "%s が通常のファイルでない" % TRIAL)
        self.tearDown()
        self.setUp()
        self.ready()
        other = os.path.join(self.root, "elsewhere.jsonl")
        open(other, "w").close()
        os.symlink(other, os.path.join(self.root, TRIAL))
        self.verify_fails(("gkg-runs",), "%s が通常のファイルでない" % TRIAL)

    def test_official_trial_run_ids_checked(self):
        """軽-2：正式な run の run-start の行の trial_run_ids が、official より前の trial の記録の run_id の一覧
        と同じでなければ失敗。"""
        self.ready()
        t1, _r, _o = self.start_run(T0 + 4 * H)
        off, _r, _o = self.start_run(T0 + 5 * H, mode="official", manifest=False)
        self.write_manifest(OFFICIAL, [self.row(off)])
        self.verify_ok("gkg-runs")
        for bad in ([], ["0" * 16], None):
            with self.subTest(bad=bad):
                self.write_manifest(OFFICIAL, [self.row(off, trial_run_ids=bad)])
                self.verify_fails(("gkg-runs",), "1 行目の trial_run_ids %r が、official の記録（seq %d）より前の"
                                  % (bad, off["seq"]))

    def test_trial_run_ids_follow_seq_order_after_reuse(self):
        """T-046（T-043 の監査 軽-A、scratchpad/a43probe）：記録だけ書いて止まった run A → 別の run B →
        A に戻して使い回す、の流れでは、マニフェストの行の順（B, A）と記録の seq の順（A, B）がずれる。
        trial_run_ids は seq の順（収集係の T-045 の並べ方）で比べるので、seq の順なら通り、行の順なら止まる。"""
        self.ready()
        path = os.path.join(self.root, t31.tw.CODE_REL)
        with open(path, encoding="utf-8") as f:
            orig = f.read()
        a, _r, _o = self.start_run(T0 + 4 * H, manifest=False)          # A：記録だけ（行の前で止まった）
        with open(path, "w", encoding="utf-8") as f:
            f.write(orig + "# B\n")
        self.commit("B")
        b, _r, _o = self.start_run(T0 + 5 * H)                          # B：記録と行
        with open(path, "w", encoding="utf-8") as f:
            f.write(orig)
        self.commit("A に戻す")
        a2, _r, _o = self.start_run(T0 + 6 * H)                         # A を使い回し、行を足す
        self.assertEqual(a2, a)
        off, _r, _o = self.start_run(T0 + 7 * H, mode="official", manifest=False)
        run_id = lambda r: ledger.read_target_json(self.root, r, ledger.GKG_RUN_KIND)["run_id"]  # noqa: E731
        seq_order = [run_id(a), run_id(b)]
        row_order = [run_id(b), run_id(a)]
        self.write_manifest(OFFICIAL, [self.row(off, trial_run_ids=seq_order)])
        out = self.verify_ok("gkg-runs")
        self.assertIn("%s：run-start の行 2 行、異なる run_id 2 個" % TRIAL, out)
        self.write_manifest(OFFICIAL, [self.row(off, trial_run_ids=row_order)])
        self.verify_fails(("gkg-runs",), "1 行目の trial_run_ids %r が、official の記録（seq %d）より前の"
                          % (row_order, off["seq"]))

    def test_probe_a41_stamp_failure_then_retry(self):
        """中-1：監査のプローブの流れ（stamp の失敗 → .ots を stamp.py で作り直す → 同じ run_id でやり直す →
        別の run）で、記録が先へ進めなくならず、verify が通る。"""
        self.ready()
        with self.assertRaises(ledger.LedgerError):
            seal_gkg_run.start(self.root, "trial", t31.tw.CODE_REL, self.code_sha()[:16], t31.KEPT,
                               self.method_rec["seq"], t31.TRIAL_DAYS, self.excl()[0], self.excl()[1],
                               T0 + 4 * H, "ots", drand_fetch=t31.tw.FakeDrand(T0 + 4 * H),
                               runner=FailStamp())
        recs = [r for r in self.records() if r["kind"] == ledger.GKG_RUN_KIND]
        self.assertEqual(len(recs), 1)
        # .ots が無いうちは、鎖の検証が止まる（書く仕組みも）
        self.verify_fails(("anchors",), "時刻証明")
        tl.stamp.stamp_seq(self.ledger, recs[0]["seq"], "ots", runner=t31.tw.FakeOts())
        # 同じ run_id でやり直す：新しく書かずに、同じ記録を返す（drand は呼ばない）
        before = self.ledger_bytes()
        again, _rel, _o = seal_gkg_run.start(
            self.root, "trial", t31.tw.CODE_REL, self.code_sha()[:16], t31.KEPT, self.method_rec["seq"],
            t31.TRIAL_DAYS, self.excl()[0], self.excl()[1], T0 + 5 * H, "ots",
            drand_fetch=t31.t23.t17.NoCall(), runner=t31.tw.FakeOts())
        self.assertEqual(again, recs[0])
        self.assertEqual(self.ledger_bytes(), before)
        self.append_manifest(again)
        # 別の run（コードを直したもの）
        self.change_code()
        self.start_run(T0 + 6 * H)
        out = self.verify_ok("all")
        self.assertIn("異なる run_id 2 個", out)

    def test_reuse_refused_when_input_differs(self):
        """中-1：使い回せるのは、入力がすべて同じで、まだ run-start の行が無い記録だけ。"""
        self.ready()
        t1, _r, _o = self.start_run(T0 + 4 * H, manifest=False)
        self.assert_writer_refuses(lambda: self.start_run(T0 + 5 * H, filelist_sha256="d" * 64),
                                   "filelist_sha256")
        self.assert_writer_refuses(lambda: self.start_run(T0 + 5 * H, days=["2015-03-02"]),
                                   "trial_days が違う")
        self.append_manifest(t1)
        self.assert_writer_refuses(lambda: self.start_run(T0 + 5 * H, manifest=False),
                                   "run-start の行が既にある")

    def test_reuse_refused_when_row_only_in_head(self):
        """run-start の行が HEAD の版のマニフェストにだけあっても、使い回さない。"""
        self.ready()
        t1, _r, _o = self.start_run(T0 + 4 * H)
        self.commit("マニフェスト")
        with open(os.path.join(self.root, TRIAL), "w"):
            pass
        self.assert_writer_refuses(lambda: self.start_run(T0 + 5 * H, manifest=False),
                                   "run-start の行が既にある")
        self.assertTrue(t1)

    def test_trial_run_without_record_fails(self):
        """記録を書かずに行った試しの run（マニフェストに run-start がある）は、数が合わないので止まる。"""
        self.ready()
        t1, _r, _o = self.start_run(T0 + 4 * H)
        self.change_code()
        t2, _r, _o = self.start_run(T0 + 5 * H)
        self.write_manifest(TRIAL, [self.row(t1), self.row(t1, run_id="f" * 16)])
        self.write_manifest(OFFICIAL, [])
        self.verify_fails(("gkg-runs", "all"), "2 行目（mode 'trial'・run_id '%s'）が、seq %d の gkg-run-start"
                          % ("f" * 16, t1["seq"]))
        self.write_manifest(TRIAL, [self.row(t1)])
        self.verify_fails(("gkg-runs",), "%s の run-start の異なる run_id の数 1 が、mode trial の gkg-run-start の"
                                         "記録の件数 2 と違う" % TRIAL)
        self.assertTrue(t2)

    def test_row_must_point_to_matching_record(self):
        self.ready()
        t1, _r, _o = self.start_run(T0 + 4 * H)
        self.write_manifest(OFFICIAL, [])
        cases = [
            ({"gkg_run_seq": None}, "に gkg_run_seq・gkg_run_record_sha256 が無いか、形が違う"),
            ({"gkg_run_seq": 1}, "の gkg_run_seq 1 の記録が、gkg-run-start でない"),
            ({"gkg_run_seq": 999}, "の gkg_run_seq 999 の記録が、gkg-run-start でない（または無い）"),
            ({"gkg_run_record_sha256": "0" * 64}, "の gkg_run_record_sha256 が、seq %d の記録の行と一致しない" % t1["seq"]),
            ({"mode": "official"}, "（mode 'official'・run_id"),
            ({"run_id": "0" * 16}, "run_id '%s'）が、seq %d の gkg-run-start" % ("0" * 16, t1["seq"])),
        ]
        for over, msg in cases:
            with self.subTest(over=over):
                self.write_manifest(TRIAL, [self.row(t1, **over)])
                self.verify_fails(("gkg-runs",), msg)

    def test_official_in_trial_manifest_fails(self):
        self.ready()
        off, _r, _o = self.start_run(T0 + 4 * H, mode="official")
        self.write_manifest(TRIAL, [self.row(off)])
        self.write_manifest(OFFICIAL, [])
        self.verify_fails(("gkg-runs",), "1 行目（mode 'official'")

    def test_manifest_rows_without_any_record_fail(self):
        self.ready()
        self.write_manifest(TRIAL, [{"kind": "run-start", "mode": "trial", "run_id": "a" * 16,
                                     "gkg_run_seq": 1, "gkg_run_record_sha256": "0" * 64}])
        self.verify_fails(("gkg-runs", "all"), "の gkg_run_seq 1 の記録が、gkg-run-start でない")


class TestDocT041(unittest.TestCase):
    def setUp(self):
        with open(DOC, encoding="utf-8") as f:
            self.text = f.read()

    def test_statements(self):
        for phrase in ("収集係のマニフェストとの照合（T-041。T-031 の監査 中1 の残り）", "異なる run_id の数",
                       "正直なやり直しとして通す", "末尾の行と中身とマニフェストの行をまとめて戻すこと",
                       "マニフェストに行のある commit が0件でも、浅い clone なら止まる",
                       "記録に写した値と定数を比べるもの",
                       "git show a970019c61808738b02629b14f68b3171c4ddd57:reviews/T-036.md",
                       "git show 9c85f58f054a679b8e5f40fcd7adbb17536f6366:reviews/T-028.md",
                       "最初の method-access の前に `stats-order1` の記録が要る"):
            self.assertIn(phrase, self.text)
        self.assertNotIn("`method-access` の前に `stats-order1` を求めることは、まだしていない", self.text)


class TestDocT049(unittest.TestCase):
    def test_statements(self):
        with open(DOC, encoding="utf-8") as f:
            text = f.read()
        for phrase in ("`verify.py all`（と `stats-order`）は、順番1 の10件の sha256 を計算し直さない",
                       "docs/stats/seal-order1.md 3章 (1) の手順で、自分で計算し直して行う",
                       "記録の行の `recorded_at` は、封印を始めた時刻である",
                       "ledger に書いた時刻は `recorded_at` より後になる"):
            self.assertIn(phrase, text)


class TestDocT043(unittest.TestCase):
    def setUp(self):
        with open(DOC, encoding="utf-8") as f:
            self.text = f.read()

    def test_statements(self):
        for phrase in ("使い回し（T-043。T-041 の監査 中-1）", "stamp.py stamp --seq N",
                       "結果を見てから run や入力を選び直す道にはならない", "`make_start_hook`",
                       "記録が0件でマニフェストも無い mode は照らさず", "通常のファイルでない",
                       "`trial_run_ids` が、`official` の記録より前の `trial` の記録の run_id の一覧",
                       "第三者は、マニフェストのコミットのあとで照らす",
                       "最初の method-access の前に `stats-order1b` の記録も要る",
                       "関門で照らすのは T-046 から", "収集係が T-045 で決めた並べ方",
                       "`test_trial_run_ids_follow_seq_order_after_reuse`"):
            self.assertIn(phrase, self.text)
        self.assertNotIn("- マニフェストが無い mode は照らさず、", self.text)


if __name__ == "__main__":
    unittest.main()
