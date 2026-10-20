"""T-100 のテスト（封印係）：順番4を実行する前の直し。
  1. 書く仕組み（check_new）でも、日の集計の置き場所で C7 の分母を封印済みの counting.py で数え直す（T-095 の監査 P1）。
     規則を変えた仮のコードのテストは tests/sealer/test_t095.py の TestDoctoredRules（test_c7_values_changed など）。
  2. 追記のあとで中身を書けなかった記録を戻す入口 seal_order4.py --write-content（監査 P2）。
  3. order4_day_rows のマニフェストの先頭の sha256 の照合（N8）を外すと落ちるテスト。
  4. 正式な run の gkg-run-result か順番3があるのに、順番4より前に threshold-access がある並びを、書く仕組み（seal_access）と
     verify が止める（T-097。監査 probe A）。

実行（プロジェクトのルートで）:
    PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -B -m unittest discover -s tests/sealer -v

書くのは、本物の記録の固定したコミット（fixed_records.ORDER3_COMMIT）の clone と、一時のフォルダの中だけ（test_t095.Clone）。
ots と drand は偽物。日の集計は合成（LACIE SHARE は読まない）。
"""

import contextlib
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import test_ledger as tl  # noqa: E402
import test_t095 as t95  # noqa: E402
import test_writers as tw  # noqa: E402

ledger = tl.ledger
verify = tl.verify
import seal_access  # noqa: E402
import seal_order4  # noqa: E402
import seal_records  # noqa: E402
import stamp  # noqa: E402

O4 = ledger.ORDER4_KIND
TA = ledger.THRESHOLD_ACCESS_KIND


def failing_content_write():
    """順番4の中身のファイルだけを書けなくする（追記のあとで中身を書けなかった形）。"""
    real = ledger.write_once

    def failing(path, content):
        if os.path.basename(path).startswith(O4 + "-"):
            raise ledger.LedgerError("中身を書けない（テスト）")
        return real(path, content)
    return mock.patch.object(ledger, "write_once", failing)


# ---------------------------------------------------------------- 2. --write-content

class TestWriteContent(t95.Clone):
    def write_content(self, store):
        err = io.StringIO()
        with mock.patch.object(ledger, "PROJECT_ROOT", self.c), self.sealed_rows(), \
                contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
            code = seal_order4.main(["--write-content", "--store", store])
        return code, err.getvalue()

    def fail_once(self):
        with failing_content_write(), self.assertRaisesRegex(seal_order4.Order4Written, "--write-content"):
            self.seal()
        self.assertEqual(self.content_files(), [])
        return self.records()[-1]

    def test_write_content_restores_and_commits(self):
        rec = self.fail_once()
        head = self.head()
        code, err = self.write_content(self.store)
        self.assertEqual(code, 0, err)
        self.assertEqual(self.git("rev-parse", "HEAD~1").decode().strip(), head)
        self.assertEqual(self.content_files(), [os.path.basename(rec["targets"][0]["path"])])
        self.assertEqual(self.git("status", "--porcelain"), b"")
        got = self.git("log", "-1", "--format=%an <%ae>|%B").decode().rstrip("\n")
        self.assertEqual(got, t95.WHO + "|" + seal_order4.ORDER4_MESSAGE)
        # .ots を作ってコミットすれば、verify が通る（--store の数え直しも）
        stamp.stamp_seq(os.path.join(self.c, "sealed", "ledger.jsonl"), rec["seq"], "ots", runner=tw.FakeOts())
        self.git("add", "--", "sealed/" + ledger.ots_name(rec["seq"]))
        self.git("commit", "-q", "-m", ".ots（テスト）")
        self.verify_zero("all", "--rev", "auto", "--store", self.store)

    def test_write_content_refuses_other_bytes(self):
        """置き場所が違えば（流し直した中身が記録の sha256 と合わない）書かない。中身があれば書かない。最後が順番4でなければ書かない。"""
        self.fail_once()
        other, _s = self.make_store("other", ("2017-01-01",))
        code, err = self.write_content(other)
        self.assertEqual(code, 1)
        self.assertIn("流し直した中身の sha256", err)
        self.assertEqual(self.content_files(), [])
        code, err = self.write_content(self.store)
        self.assertEqual(code, 0, err)
        code, err = self.write_content(self.store)
        self.assertEqual(code, 1)
        self.assertIn("は既にある", err)                              # 書いたので、2回目は書かない

    def test_write_content_refuses_other_changes(self):
        self.fail_once()
        with open(os.path.join(self.c, "extra.txt"), "w") as f:
            f.write("x\n")
        code, err = self.write_content(self.store)
        self.assertEqual(code, 1)
        self.assertIn("作業ツリーの変更", err)


# ---------------------------------------------------------------- 3. マニフェストの先頭の sha256（N8）

class TestManifestPrefixSha(t95.Clone):
    def test_working_manifest_rewritten(self):
        """作業ツリーのマニフェストの先頭の day の行（2015-05-29 の files_ok）を書き換えると、72本の条件の照合は、先頭の sha256 が
        gkg-run-result の記録と合わないことで止まる（ほかの照合より前に）。"""
        doc = self.build()
        path = os.path.join(self.c, ledger.GKG_MANIFESTS["official"])
        with open(path, "rb") as f:
            body = f.read()
        old = b'"day": "2015-05-29"'
        i = body.index(old)
        line_start = body.rindex(b"\n", 0, i) + 1
        line_end = body.index(b"\n", i)
        row = json.loads(body[line_start:line_end])
        row["files_ok"] = 96
        new = body[:line_start] + json.dumps(row, sort_keys=True).encode() + body[line_end:]
        with open(path, "wb") as f:
            f.write(new)
        data = self.ledger_bytes()
        records = ledger.verify_chain(data)
        _r, rec, line = ledger.build_next_record(data, O4, [{"path": "sealed/x.json", "role": O4, "sha256": "a" * 64}], "",
                                                 self.tick())
        read = lambda r, role: ledger.read_target_json(self.c, r, role)  # noqa: E731
        with tempfile.TemporaryDirectory() as tmp, \
                self.assertRaisesRegex(ledger.LedgerError, re.escape("の先頭 2118 行の sha256 が、gkg-run-result の記録の "
                                                                     "manifest_sha256 と違う")):
            verify.check_order4_rules(self.c, records + [rec], rec, doc, read, tmp)


# ---------------------------------------------------------------- 4. threshold-access と順番4（T-097）

class TestThresholdAccess(t95.Clone):
    def access(self):
        now = self.tick()
        with mock.patch.object(ledger, "PROJECT_ROOT", self.c):
            return seal_access.seal(self.c, now, "ots", drand_fetch=tw.FakeDrand(now), runner=tw.FakeOts())

    def test_refused_before_order4_then_allowed(self):
        """正式な run の gkg-run-result（seq 12）と順番3（seq 14）がある記録で、順番4より前の threshold-access は書かない。
        T-144 から、順番4を書いたあとも、順番5（ok）と順番6〜8 が無ければ書かない（書ける並びは tests/sealer/test_t144.py の
        TestThresholdGate が確かめる）。"""
        text = re.escape("threshold-access の記録（seq 15）より前に、順番4（stats-order4）の記録が無い")
        before = self.ledger_bytes()
        with self.assertRaisesRegex(ledger.LedgerError, text):
            self.access()
        self.assertEqual(self.ledger_bytes(), before)
        self.seal()
        before = self.ledger_bytes()
        with self.assertRaisesRegex(ledger.LedgerError, re.escape("status が ok の順番5（stats-order5）の記録が無い")):
            self.access()
        self.assertEqual(self.ledger_bytes(), before)
        self.verify_zero("stats-order")

    def test_forged_threshold_access_stops_verify(self):
        """書く仕組みの照合を飛ばして、順番4より前に threshold-access を足すと、verify が止める（監査 probe A）。"""
        now = self.tick()
        with mock.patch.object(seal_records, "check_new", lambda *a, **k: None), \
                mock.patch.object(ledger, "PROJECT_ROOT", self.c):
            seal_access.seal(self.c, now, "ots", drand_fetch=tw.FakeDrand(now), runner=tw.FakeOts())
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "作り物の threshold-access（テスト）")
        self.verify_stops(re.escape("より前に、順番4（stats-order4）の記録が無い"))
        with self.assertRaisesRegex(ledger.LedgerError, "threshold-access の記録（seq 15）より後に、順番4の記録は置けない"):
            self.seal()


class TestThresholdUnit(unittest.TestCase):
    """記録の並びだけで確かめる（read_json は gkg-run-result の mode だけを返す）。"""

    def recs(self, kinds):
        return [{"seq": i + 1, "kind": k} for i, k in enumerate(kinds)]

    def check(self, kinds, mode="official"):
        ledger.check_threshold_access_after_order4(self.recs(kinds), lambda r, role: {"mode": mode})

    def test_rule(self):
        G, O3 = ledger.GKG_RESULT_KIND, ledger.ORDER3_KIND
        for kinds in (["periods", TA], ["periods", G, TA], ["periods", O3, O4, TA], ["periods", G, O4, TA],
                      ["periods", G, O3, O4, TA, TA], ["periods", TA, G, O3]):
            mode = "trial" if kinds == ["periods", G, TA] else "official"
            with self.subTest(kinds=kinds):
                self.check(kinds, mode)
        for kinds in (["periods", G, TA], ["periods", O3, TA], ["periods", G, O3, TA, O4], ["periods", G, TA, O4]):
            with self.subTest(kinds=kinds), self.assertRaisesRegex(ledger.LedgerError, "順番4（stats-order4）の記録が無い"):
                self.check(kinds)


if __name__ == "__main__":
    unittest.main()
