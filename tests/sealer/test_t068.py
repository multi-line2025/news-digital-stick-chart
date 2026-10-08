"""T-068 のテスト（T-066 の監査 中-2・中-3・軽-1・軽-2、T-065 の監査の残り）。

実行（プロジェクトのルートで）:
    PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest discover -s tests/sealer -v

本物の記録と試しの run のマニフェストを使うものは、clone の中だけで書き換える（test_t066.Clone）。計画（days・
files_selected）の書き込みは、仮のプロジェクト（test_t031.GkgCase）で行う。ots・drand は偽物。本物の sealed/・
data/manifest/ には書かない。ネットワークと LACIE SHARE には触れない。
"""

import json
import os
import sys
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import test_ledger as tl  # noqa: E402
import test_t031 as t31  # noqa: E402
from test_ledger import T0, H  # noqa: E402
from test_t066 import Clone, dump, rows_of  # noqa: E402

ledger = tl.ledger
DOC = os.path.join(tl.PROJECT, "docs", "verify", "periods-seal.md")
TRIAL = ledger.GKG_MANIFESTS["trial"]


def unchecked_line(out):
    return [l for l in out.splitlines() if l.startswith("ただし、次は照らさなかった")][0]


class TestSummaryDoesNotShrink(Clone):
    """中-2：run-complete の行を消しても、まとめの「照らさなかった」からマニフェストの時刻証明が消えない。"""

    def test_remove_run_complete(self):
        code, out, err = tl.run_verify_inproc(self.c, "all", "--rev", "auto")
        self.assertEqual(code, 0, err)
        before = unchecked_line(out)
        self.assertIn("run_id %s のマニフェストの時刻証明（gkg-run-result の記録が無い。run-complete まである）"
                      % self.rid, before)
        self.write_manifest(dump(rows_of(self.body)[:-1]))
        code, out, err = tl.run_verify_inproc(self.c, "all", "--rev", "auto")
        self.assertEqual(code, 0, err)
        after = unchecked_line(out)
        self.assertIn("run_id %s のマニフェストの時刻証明（gkg-run-result の記録が無い。終わっていない run（run-complete "
                      "の行が無い））" % self.rid, after)
        self.assertEqual(before.count("マニフェストの時刻証明"), after.count("マニフェストの時刻証明"))
        self.assertEqual(before.count("、"), after.count("、"))      # 項目の数も減らない

    def test_orphan_day_row_stops(self):
        """軽-1：持ち主の run（run-start の行）が無い day の行で止まる。"""
        rows = rows_of(self.body)
        rows.insert(1, dict(rows[1], run_id="0" * 16))
        with self.assertRaisesRegex(ledger.LedgerError, "最初の行が run-start でない"):
            ledger.check_gkg_manifests(self.records(), self.read, {"trial": dump(rows), "official": None})
        rows = rows_of(self.body)
        rows.insert(0, dict(rows[1]))                 # run-start より前の day の行
        with self.assertRaisesRegex(ledger.LedgerError, "最初の行が run-start でない"):
            ledger.check_gkg_manifests(self.records(), self.read, {"trial": dump(rows), "official": None})

    def test_fetch_log_file_name(self):
        """軽-2：run-complete の fetch_log_file は gkg-<mode>-<run_id>-fetch-log.jsonl。"""
        rows = rows_of(self.body)
        self.assertEqual(rows[-1]["fetch_log_file"], "gkg-trial-%s-fetch-log.jsonl" % self.rid)
        for bad in ("gkg-trial-%s-fetch-log.jsonl.bak" % self.rid, "../x", None, "gkg-official-%s-fetch-log.jsonl" % self.rid):
            rr = rows_of(self.body)
            rr[-1]["fetch_log_file"] = bad
            with self.subTest(bad=bad):
                with self.assertRaisesRegex(ledger.LedgerError, "fetch_log_file"):
                    ledger.check_gkg_manifests(self.records(), self.read, {"trial": dump(rr), "official": None})

    def test_real_seq8_old_form_passes(self):
        """既にある seq 8（試しの run）は計画の無い古い形で、そのまま通る。"""
        rec = [r for r in self.records() if r["kind"] == ledger.GKG_RUN_KIND][0]
        doc = self.read(rec, ledger.GKG_RUN_KIND)
        self.assertNotIn("days", doc)
        self.assertEqual(tuple(sorted(doc)), ledger.GKG_RUN_DOC_KEYS)


class TestPlan(t31.GkgCase):
    """中-3：取得の計画（days・files_selected）を gkg-run-start に入れ、run-start の行と照らす。"""

    def test_official_with_plan(self):
        self.ready()
        self.start_run(T0 + 4 * H)
        _off, rel, _o = self.start_run(T0 + 5 * H, mode="official", plan=(2115, 203040))
        doc = self.doc_of(rel)
        self.assertEqual((doc["days"], doc["files_selected"]), (2115, 203040))
        self.assertEqual(tuple(sorted(doc)), ledger.GKG_RUN_DOC_KEYS_PLAN)
        self.commit("正式な run")
        out = self.verify_ok("gkg-runs")
        self.assertNotIn("取得の計画", out)
        # run-start の行の days・files_selected を、記録の計画と違う値にすると止まる
        path = os.path.join(self.root, ledger.GKG_MANIFESTS["official"])
        with open(path, encoding="utf-8") as f:
            rows = [json.loads(l) for l in f.read().splitlines() if l.strip()]
        for k, v in (("days", 2114), ("files_selected", 203041)):
            with open(path, "w", encoding="utf-8") as f:
                f.write(json.dumps(dict(rows[0], **{k: v}), sort_keys=True) + "\n")
            self.verify_fails(("gkg-runs", "all"), "の計画の")

    def test_official_without_plan_is_unchecked_until_t069(self):
        self.ready()
        self.start_run(T0 + 4 * H)
        off, _rel, _o = self.start_run(T0 + 5 * H, mode="official")
        self.commit("正式な run（計画なし）")
        code, out, err = tl.run_verify_inproc(self.root, "gkg-runs")
        self.assertEqual(code, 0, err)
        self.assertIn("seq %d の gkg-run-start（official）に取得の計画（days・files_selected）が無い" % off["seq"], out)
        # T-069 のあと（True）は、計画の無い official を verify が止め、書く仕組みも書かない
        with mock.patch.object(ledger, "GKG_RUN_PLAN_REQUIRED_FOR_OFFICIAL", True):
            code, _out, err = tl.run_verify_inproc(self.root, "gkg-runs")
            self.assertEqual(code, 1)
            self.assertIn("取得の計画", err)

    def test_official_without_plan_refused_when_required(self):
        self.ready()
        self.start_run(T0 + 4 * H)
        self.commit("試し")
        before = self.ledger_bytes()
        with mock.patch.object(ledger, "GKG_RUN_PLAN_REQUIRED_FOR_OFFICIAL", True):
            with self.assertRaisesRegex(ledger.LedgerError, "取得の計画"):
                self.start_run(T0 + 5 * H, mode="official", manifest=False)
        self.assertEqual(self.ledger_bytes(), before)

    def test_plan_shape_and_reuse(self):
        self.ready()
        for plan, text in (((0, 5), "1 以上の整数"), ((2, None), "両方渡す"), ((4, 10), "trial_days の数と同じでない")):
            with self.subTest(plan=plan):
                with self.assertRaisesRegex(ledger.LedgerError, text):
                    self.start_run(T0 + 4 * H, manifest=False, plan=plan)
        # 計画を持つ試しの run の記録は、同じ計画でなければ使い回さない
        self.start_run(T0 + 4 * H, manifest=False, plan=(3, 288))
        with self.assertRaisesRegex(ledger.LedgerError, "files_selected が違う"):
            self.start_run(T0 + 5 * H, manifest=False, plan=(3, 287))


class TestDocT068(unittest.TestCase):
    def test_statements(self):
        with open(DOC, encoding="utf-8") as f:
            text = f.read()
        for phrase in ("正式な run では取得の全期間", "件数をそろえて日を抜く", "事後の縛りでしかない",
                       "`trial_manifest_sha256`（試しのマニフェストの全体の sha256）でも縛られる",
                       "取得の計画（T-068", "GKG_RUN_PLAN_REQUIRED_FOR_OFFICIAL", "テストを流す Python（T-068",
                       "-c protocol.version=2", "まとめの「照らさなかった」（T-068"):
            self.assertIn(phrase, text)


if __name__ == "__main__":
    unittest.main()
