"""閾値と判定期間の候補の封印（kind: candidates）のテスト。T-013。

実行（プロジェクトのルートで）:
    PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest discover -s tests/sealer -v

ネットワークは使わない（ots は偽の応答。drand も使わない）。仮のプロジェクトで動かし、本物の
sealed/ には書かない。確かめること：
  - 記録の形の照合（対象の role とパスの組、output のファイル名と sha256、出力の形）
  - acquisition-start の後にある candidates の記録を、書く仕組みが拒み、検証が失敗にすること
  - 採用の規則（最初の threshold-access より前の、candidates の最後の記録）
  - わざと壊したもの（出力の書き換え、対象の差し替え、役割の欠け）で検証が失敗すること
"""

import json
import os
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import test_ledger as tl  # noqa: E402
from test_ledger import AUTHOR, FakeRun, T0, H, run_verify  # noqa: E402

import ledger  # noqa: E402
import seal_candidates  # noqa: E402
import stamp  # noqa: E402

PROJECT = tl.PROJECT

FAKE_CANDIDATES = """import json, sys
doc = {"threshold_multipliers": [2, 3], "horizon_days": [14, 28],
       "combinations": [[2, 14], [3, 14], [2, 28], [3, 28]], "combination_count": 4,
       "last_read_offset_days": {"14": 14, "28": 28}, "note": %r}
sys.stdout.write(json.dumps(doc, sort_keys=True, indent=2) + "\\n")
"""


def good_output():
    return {"threshold_multipliers": [2, 3], "horizon_days": [14, 28],
            "combinations": [[2, 14], [3, 14], [2, 28], [3, 28]], "combination_count": 4}


class CandCase(tl.SealCase):
    def setUp(self):
        super().setUp()
        for rel, _role in ledger.CANDIDATES_SOURCES:
            full = os.path.join(self.root, rel)
            if os.path.exists(full):      # src/stats/periods.py は SealCase が作った偽物
                continue
            os.makedirs(os.path.dirname(full), exist_ok=True)
            with open(full, "w") as f:
                f.write(FAKE_CANDIDATES % "v1" if rel.endswith("candidates.py")
                        else "# %s\n" % rel)
        self.cand_sha = ledger.sha256_hex(seal_candidates.run_candidates(self.root))

    def seal_cand(self, now, sha=None, **kw):
        rec, _p, _s = seal_candidates.seal(self.root, sha or self.cand_sha, now, None,
                                           require_committed=False, **kw)
        stamp.stamp_seq(self.ledger, rec["seq"], "ots", runner=FakeRun())
        return rec

    def change_candidates(self, label):
        with open(os.path.join(self.root, ledger.CANDIDATES_SCRIPT), "w") as f:
            f.write(FAKE_CANDIDATES % label)
        self.cand_sha = ledger.sha256_hex(seal_candidates.run_candidates(self.root))

    def append_raw(self, rec_kind, targets, now):
        """書く仕組みを通さずに記録を足し、.ots を付ける（壊した記録を作るため）。"""
        ledger.append_record(self.ledger, rec_kind, targets, "", now)
        seq = len(ledger.verify_chain(ledger.read_ledger(self.ledger)))
        stamp.stamp_seq(self.ledger, seq, "ots", runner=FakeRun())
        return seq

    def cand_targets(self, out_bytes=None):
        out = out_bytes if out_bytes is not None else seal_candidates.run_candidates(self.root)
        sha = ledger.sha256_hex(out)
        rel = ledger.candidates_output_rel(sha)
        ledger.write_once(os.path.join(self.root, rel), out)
        t = [{"path": p, "role": r, "sha256": ledger.sha256_file(os.path.join(self.root, p))}
             for p, r in ledger.CANDIDATES_SOURCES]
        return t + [{"path": rel, "role": "output", "sha256": sha}]

    def commit(self, msg="step"):
        """仮のプロジェクトを Git にコミットする（--rev auto で照合するため）。"""
        if not os.path.isdir(os.path.join(self.root, ".git")):
            subprocess.run(["git", "-C", self.root, "init", "-q"], check=True, capture_output=True)
        for args in (("add", "-A"), ("commit", "-q", "--allow-empty", "-m", msg)):
            subprocess.run(["git", "-C", self.root] + list(AUTHOR) + list(args), check=True,
                           capture_output=True)

    def files_in_sealed(self):
        return sorted(os.listdir(os.path.join(self.root, "sealed")))


# ---------------------------------------------------------------- 記録の形の照合


class TestRecordShape(CandCase):
    def test_seal_writes_record_with_five_targets_and_verify_passes(self):
        self.seal()
        rec = self.seal_cand(T0 + H)
        self.assertEqual(rec["kind"], "candidates")
        self.assertEqual(sorted((t["role"], t["path"]) for t in rec["targets"] if t["role"] != "output"),
                         sorted((r, p) for p, r in ledger.CANDIDATES_SOURCES))
        out = ledger.check_candidates_record(rec)
        self.assertEqual(out["sha256"], self.cand_sha)
        self.assertEqual(out["path"], "sealed/candidates-output-%s.json" % self.cand_sha)
        self.assertEqual(ledger.sha256_file(os.path.join(self.root, out["path"])), self.cand_sha)
        r = run_verify(self.root, "all")
        self.assertEqual(r.returncode, 0, r.stderr.decode())
        text = r.stdout.decode()
        self.assertIn("candidates の 1 件目（seq 2）", text)
        self.assertIn(self.cand_sha, text)
        self.assertIn("閾値の倍率 2, 3、判定期間（日）14, 28、組み合わせ 4", text)
        self.assertIn("candidates: 採用は保留。仮の候補 = seq 2", text)

    def _rec(self, targets):
        return {"seq": 5, "kind": "candidates", "targets": targets}

    def test_record_shape_rejections(self):
        self.seal()
        good = self.cand_targets()
        ledger.check_candidates_record(self._rec(good))
        cases = {
            "役割の欠け": [t for t in good if t["role"] != "test"],
            "役割の追加": good + [{"path": "x/y.md", "role": "extra", "sha256": "0" * 64}],
            "パスの差し替え": [dict(t, path="docs/stats/other.md") if t["role"] == "doc" else t
                          for t in good],
            "output の名前と sha256 の食い違い": [dict(t, sha256="0" * 64)
                                            if t["role"] == "output" else t for t in good],
            "output の置き場": [dict(t, path="sealed/output-%s.json" % t["sha256"])
                             if t["role"] == "output" else t for t in good],
            "役割の重複": good + [dict(good[0], path="docs/stats/x.md")],
        }
        for name, targets in cases.items():
            with self.assertRaises(ledger.LedgerError, msg=name):
                ledger.check_candidates_record(self._rec(targets))

    def test_output_shape_rejections(self):
        ledger.check_candidates_output(good_output())
        bad = {
            "倍率が増えない": dict(good_output(), threshold_multipliers=[3, 2]),
            "倍率が空": dict(good_output(), threshold_multipliers=[]),
            "判定期間が整数でない": dict(good_output(), horizon_days=[14, 28.0]),
            "組の欠け": dict(good_output(), combinations=[[2, 14], [3, 14], [2, 28]]),
            "組の重複": dict(good_output(), combinations=[[2, 14], [3, 14], [2, 28], [3, 28],
                                                          [3, 28]]),
            "組の数の食い違い": dict(good_output(), combination_count=5),
            "一覧でない": [],
        }
        for name, doc in bad.items():
            with self.assertRaises(ledger.LedgerError, msg=name):
                ledger.check_candidates_output(doc)

    def test_real_candidates_output_passes_shape_check(self):
        """本物の src/stats/candidates.py の出力が、出力の形の照合に通る（ネットワーク不要）。"""
        out = seal_candidates.run_candidates(PROJECT)
        ms, hs = ledger.check_candidates_output(json.loads(out.decode("utf-8")))
        self.assertEqual(ms, [2, 3, 4, 6, 8, 12, 16])
        self.assertEqual(hs, [14, 28, 56])

    def test_malformed_record_appended_bypassing_writer_fails_verify(self):
        self.seal()
        good = self.cand_targets()
        self.append_raw("candidates", [t for t in good if t["role"] != "import"], T0 + H)
        for c in ("candidates", "all"):
            r = run_verify(self.root, c)
            self.assertEqual(r.returncode, 1, c)
            self.assertIn("決まった 5 つ", r.stderr.decode())

    def test_bad_output_appended_bypassing_writer_fails_verify(self):
        self.seal()
        doc = dict(good_output(), combination_count=99)
        self.append_raw("candidates", self.cand_targets(json.dumps(doc).encode()), T0 + H)
        r = run_verify(self.root, "all")
        self.assertEqual(r.returncode, 1)
        self.assertIn("combination_count", r.stderr.decode())

    def test_tampered_output_file_fails_verify(self):
        self.seal()
        rec = self.seal_cand(T0 + H)
        out = os.path.join(self.root, ledger.check_candidates_record(rec)["path"])
        with open(out, "ab") as f:
            f.write(b" ")
        for c in ("candidates", "targets", "all"):
            self.assertEqual(run_verify(self.root, c).returncode, 1, c)

    def test_wrong_expected_hash_writes_nothing(self):
        self.seal()
        before = self.files_in_sealed()
        data = ledger.read_ledger(self.ledger)
        with self.assertRaisesRegex(ledger.LedgerError, "期待と違う"):
            self.seal_cand(T0 + H, sha="0" * 64)
        self.assertEqual(self.files_in_sealed(), before)
        self.assertEqual(ledger.read_ledger(self.ledger), data)

    def test_needs_periods_first(self):
        with self.assertRaisesRegex(ledger.LedgerError, "periods の記録が無い"):
            self.seal_cand(T0)
        self.assertFalse(os.path.exists(self.ledger))

    def test_refused_when_data_present(self):
        self.seal()
        with open(os.path.join(self.root, "data", "manifest", "list.json"), "w") as f:
            f.write("{}")
        with self.assertRaisesRegex(ledger.LedgerError, "データの取得が始まっている"):
            self.seal_cand(T0 + H)
        self.assertEqual(len(ledger.verify_chain(ledger.read_ledger(self.ledger))), 1)

    def test_uncommitted_sources_refused(self):
        """対象のファイルが HEAD のコミットの中身と違えば、封印しない。"""
        self.seal()

        def git(*a):
            subprocess.run(["git", "-C", self.root] + list(AUTHOR) + list(a),
                           check=True, capture_output=True)
        git("init", "-q")
        git("add", "-A")
        git("commit", "-q", "-m", "base")
        with open(os.path.join(self.root, "docs", "stats", "candidates.md"), "a") as f:
            f.write("コミットしていない行\n")
        with self.assertRaisesRegex(ledger.LedgerError, "HEAD のコミットの中身と違う"):
            seal_candidates.seal(self.root, self.cand_sha, T0 + H, None)
        git("commit", "-q", "-am", "doc")
        rec, _p, _s = seal_candidates.seal(self.root, self.cand_sha, T0 + H, None)
        self.assertEqual(rec["seq"], 2)


# ---------------------------------------------------------------- acquisition-start の後の記録


class TestOrder(CandCase):
    def test_writer_refuses_after_acquisition_start(self):
        self.seal()
        start = self.add_start(T0 + H, 30_000_000)
        before = self.files_in_sealed()
        data = ledger.read_ledger(self.ledger)
        with self.assertRaisesRegex(ledger.LedgerError, "acquisition-start の記録（seq %d）" % start):
            self.seal_cand(T0 + 2 * H)
        self.assertEqual(self.files_in_sealed(), before)
        self.assertEqual(ledger.read_ledger(self.ledger), data)

    def test_writer_refuses_after_threshold_access(self):
        self.seal()
        self.add_access(T0 + H, 30_000_000)
        with self.assertRaisesRegex(ledger.LedgerError, "threshold-access の記録"):
            self.seal_cand(T0 + 2 * H)

    def test_candidates_after_acquisition_start_fails_verify(self):
        """仕組みを通さずに acquisition-start の後へ candidates を足すと、検証が失敗する。"""
        self.seal()
        self.seal_cand(T0 + H)
        start = self.add_start(T0 + 2 * H, 30_000_000)
        late = self.append_raw("candidates", self.cand_targets(), T0 + 3 * H)
        for c in ("candidates", "all"):
            r = run_verify(self.root, c)
            self.assertEqual(r.returncode, 1, c)
            err = r.stderr.decode()
            self.assertIn("candidates の記録（seq %d）が、最初の acquisition-start の記録（seq %d）"
                          "より後にある" % (late, start), err)
        with self.assertRaises(ledger.LedgerError):
            ledger.check_candidates_order(ledger.verify_chain(ledger.read_ledger(self.ledger)))

    def test_candidates_after_result_of_first_start_fails_too(self):
        """区切りは「最初の」acquisition-start。result の後でも、二つ目の start の前でも失敗。"""
        self.seal()
        s1 = self.add_start(T0 + H, 30_000_000)
        self.add_result(T0 + 2 * H, s1)
        self.append_raw("candidates", self.cand_targets(), T0 + 3 * H)
        self.add_start(T0 + 4 * H, 30_000_100)
        self.assertEqual(run_verify(self.root, "all").returncode, 1)

    def test_candidates_before_acquisition_start_passes(self):
        self.seal()
        rec = self.seal_cand(T0 + H)
        start = self.add_start(T0 + 2 * H, 30_000_000)
        self.add_result(T0 + 3 * H, start)
        r = run_verify(self.root, "all")
        self.assertEqual(r.returncode, 0, r.stderr.decode())
        self.assertIn("最初の acquisition-start（seq %d）より前" % start, r.stdout.decode())
        self.assertIn("candidates: 採用は保留。仮の候補 = seq %d" % rec["seq"], r.stdout.decode())


# ---------------------------------------------------------------- 採用の規則


class TestAdoption(CandCase):
    def test_last_before_first_threshold_access_is_adopted(self):
        self.seal()
        c1 = self.seal_cand(T0 + H)
        self.commit("c1")
        self.change_candidates("v2")
        c2 = self.seal_cand(T0 + 2 * H)
        start = self.add_start(T0 + 3 * H, 30_000_000)
        self.add_result(T0 + 4 * H, start)
        access = self.add_access(T0 + 5 * H, 30_000_200)
        self.commit("c2")
        recs = ledger.verify_chain(ledger.read_ledger(self.ledger))
        adopted, cand, cut = ledger.adoption(recs, ledger.CANDIDATES_KIND)
        self.assertEqual((adopted["seq"], cand, cut["seq"]), (c2["seq"], None, access))
        self.assertEqual(ledger.version_of(recs, c2["seq"]), 2)
        # 1 件目の対象（変える前の candidates.py）は、その記録を含んだコミットで照合する。
        self.assertEqual(run_verify(self.root, "all").returncode, 1)
        r = run_verify(self.root, "all", "--rev", "auto")
        self.assertEqual(r.returncode, 0, r.stderr.decode())
        text = r.stdout.decode()
        self.assertIn("candidates: 採用 = seq %d（2 件目。seq %d の threshold-access より前の最後の記録）"
                      % (c2["seq"], access), text)
        self.assertNotIn("candidates: 採用 = seq %d" % c1["seq"], text)

    def test_held_until_threshold_access(self):
        self.seal()
        c1 = self.seal_cand(T0 + H)
        recs = ledger.verify_chain(ledger.read_ledger(self.ledger))
        adopted, cand, cut = ledger.adoption(recs, ledger.CANDIDATES_KIND)
        self.assertIsNone(adopted)
        self.assertIsNone(cut)
        self.assertEqual(cand["seq"], c1["seq"])

    def test_after_threshold_access_not_adopted(self):
        """threshold-access の後の candidates（acquisition-start は無い）は採用しない。"""
        self.seal()
        c1 = self.seal_cand(T0 + H)
        access = self.add_access(T0 + 2 * H, 30_000_000)
        self.commit("before late")
        self.change_candidates("late")
        late = self.append_raw("candidates", self.cand_targets(), T0 + 3 * H)
        self.commit("late")
        r = run_verify(self.root, "all", "--rev", "auto")
        self.assertEqual(r.returncode, 0, r.stderr.decode())
        text = r.stdout.decode()
        self.assertIn("candidates: 採用 = seq %d（1 件目。seq %d の threshold-access より前"
                      % (c1["seq"], access), text)
        self.assertIn("seq %d は threshold-access の記録より後なので、採用しない" % late, text)

    def test_no_candidates_before_access(self):
        self.seal()
        access = self.add_access(T0 + H, 30_000_000)
        r = run_verify(self.root, "adopted")
        self.assertEqual(r.returncode, 0, r.stderr.decode())
        self.assertIn("candidates: seq %d より前に記録が無い。採用される版は無い" % access,
                      r.stdout.decode())

    def test_adoption_ignores_time_arguments(self):
        """採用は鎖の順番だけで決まる（引数は記録の一覧と種類だけ）。"""
        import inspect
        self.assertEqual(list(inspect.signature(ledger.adoption).parameters), ["records", "kind"])


if __name__ == "__main__":
    unittest.main()
