"""T-112 のテスト（封印係）。
  1. 書く入口の recorded_at は、書く前の照合のあと、追記の直前に取る（seal_records.write_doc_record に now=None。T-105 の監査
     軽-1）。
  2. GKG の追記だけの照合に、作業ツリーの版を渡す（working=）。作業ツリーの GKG のマニフェストを短くすると止まる（T-104 の監査
     軽-1）。

実行（プロジェクトのルートで）:
    PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -B -m unittest discover -s tests/sealer -v

書くのは、本物の記録の固定したコミットの clone の中だけ（test_t095.Clone・test_t103.CloneCase）。日の集計は合成。
"""

import datetime
import os
import sys
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import fixed_records  # noqa: E402
import test_ledger as tl  # noqa: E402
import test_t095 as t95  # noqa: E402
import test_t103 as t103  # noqa: E402
import test_writers as tw  # noqa: E402

ledger = tl.ledger
verify = tl.verify
import seal_order4  # noqa: E402
import seal_records  # noqa: E402

UTC = datetime.timezone.utc


class TestRecordedAtLate(t95.Clone):
    def test_recorded_at_is_just_before_append(self):
        """now=None なら、照合（check_new）は仮の時刻 T1 の記録で行い、追記する記録の recorded_at は照合のあとに取った T2。"""
        t1 = datetime.datetime(2026, 10, 16, 1, 0, 0, tzinfo=UTC)
        t2 = datetime.datetime(2026, 10, 16, 3, 5, 0, tzinfo=UTC)
        seen = []
        real = seal_records.check_new

        def spy(project, data_after, records_after, rec, doc, **kw):
            seen.append(rec["recorded_at"])
            return real(project, data_after, records_after, rec, doc, **kw)
        with mock.patch.object(seal_records, "utc_now", side_effect=[t1, t2]), \
                mock.patch.object(seal_records, "check_new", spy), \
                mock.patch.object(ledger, "PROJECT_ROOT", self.c), self.sealed_rows():
            rec, _rel, _o, _doc, _c = seal_order4.seal(self.store, None, "ots", runner=tw.FakeOts())
        self.assertEqual(seen, ["2026-10-16T01:00:00Z"])
        self.assertEqual(rec["recorded_at"], "2026-10-16T03:05:00Z")
        self.assertEqual(self.records()[-1], rec)
        self.verify_zero("all", "--rev", "auto")

    def test_main_passes_none(self):
        """入口の main は、seal に now=None を渡す（実行を始めた時刻を使わない）。"""
        with mock.patch.object(seal_order4, "seal", side_effect=ledger.LedgerError("止めた（テスト）")) as m:
            seal_order4.main(["--store", self.store])
        self.assertIsNone(m.call_args[0][1])


class TestGkgWorkingTree(t103.CloneCase):
    commit_id = fixed_records.ORDER3_COMMIT

    def test_short_working_gkg_manifest_stops(self):
        """作業ツリーの GKG の試しの run のマニフェストを1行短くすると、追記だけの照合（作業ツリーの版を渡す）が止める。"""
        rel = ledger.GKG_MANIFESTS["trial"]
        body = self.read(rel)
        self.put(b"".join(x + b"\n" for x in body.split(b"\n")[:-2]), rel)
        st = verify.State(self.c, None)
        with self.assertRaisesRegex(ledger.LedgerError, "作業ツリーの data/manifest/gdelt-gkg-trial.jsonl が、HEAD の版を先頭に持たない"):
            verify.gkg_manifests_append_only(st)
        with self.assertRaisesRegex(ledger.LedgerError, "HEAD の版を先頭に持たない"):
            verify.check_manifest_append_only(verify.Repo(self.c), rel, working=self.read(rel))


if __name__ == "__main__":
    unittest.main()
