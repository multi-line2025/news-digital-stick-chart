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

import test_ledger as tl  # noqa: E402
import test_t031 as t31  # noqa: E402
from test_ledger import T0, H  # noqa: E402

ledger = tl.ledger
DOC = os.path.join(tl.PROJECT, "docs", "verify", "periods-seal.md")
TRIAL = ledger.GKG_MANIFESTS["trial"]
OFFICIAL = ledger.GKG_MANIFESTS["official"]


class TestGkgManifests(t31.GkgCase):
    change_code = t31.TestGkgRunStart.change_code     # 取得のコードを直してコミットする（run_id が変わる）

    def row(self, rec, **over):
        """run-start の行（収集係の gkg.py の形のうち、照らす欄だけ）。"""
        doc = self.doc_of([t for t in rec["targets"]][0]["path"])
        r = {"kind": "run-start", "mode": doc["mode"], "run_id": doc["run_id"],
             "gkg_run_seq": rec["seq"],
             "gkg_run_record_sha256": hashlib.sha256(ledger.canonical_line(rec)).hexdigest()}
        r.update(over)
        return r

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

    def test_missing_manifest_is_reported(self):
        self.ready()
        self.start_run(T0 + 4 * H)
        out = self.verify_ok("all")
        self.assertIn("照らさなかった：%s が無いので" % TRIAL, out)
        self.assertIn("ただし、次は照らさなかった（終了コード 0 は、照らした検査がすべて通ったことだけを示す）：", out)
        self.assertIn("%s の run-start の行と gkg-run-start の記録の照合（マニフェストが無い）" % OFFICIAL, out)

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


if __name__ == "__main__":
    unittest.main()
