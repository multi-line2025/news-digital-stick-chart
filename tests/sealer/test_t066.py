"""T-066 のテスト：マニフェストの行の照合（run-start の入力の値・day・run-complete）、マニフェストの時刻証明
（gkg-run-result）、日の集計の sha256 の照合（--day-files）、関門 require_gkg_run_result。

実行（プロジェクトのルートで）:
    PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest discover -s tests/sealer -v

本物のリポジトリの、固定したコミット（fixed_records.PINNED_COMMIT。seq 1〜8 と、コミット済みの試しの run の
マニフェスト。T-077 で HEAD から固定に変えた）の版を一時フォルダに取り出し、その中だけで書く・書き換える。ots は偽物（test_writers.FakeOts）。本物の sealed/・data/manifest/ には書かない。ネットワークと
LACIE SHARE には触れない（日の集計は仮の置き場所に作る）。
"""

import datetime
import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import test_ledger as tl  # noqa: E402
import test_writers as tw  # noqa: E402
import fixed_records  # noqa: E402

ledger = tl.ledger
verify = tl.verify
sys.path.insert(0, os.path.join(tl.PROJECT, "src", "sealer"))
import seal_gkg_result  # noqa: E402

DOC = os.path.join(tl.PROJECT, "docs", "verify", "periods-seal.md")
TRIAL = ledger.GKG_MANIFESTS["trial"]
NOW = datetime.datetime(2026, 10, 9, tzinfo=datetime.timezone.utc)


def git(c, *args, **kw):
    return subprocess.run(["git", "-C", c] + list(args), check=True, capture_output=True, **kw).stdout


def rows_of(body):
    return [json.loads(l) for l in body.split(b"\n") if l.strip()]


def dump(rows):
    return b"".join(json.dumps(r, sort_keys=True, ensure_ascii=False).encode("utf-8") + b"\n" for r in rows)


class Clone(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.c = os.path.join(self.td.name, "clone")
        # T-077：HEAD ではなく、固定したコミット（fixed_records.PINNED_COMMIT。seq 1〜8 と試しの run の
        # マニフェスト。gkg-run-result はまだ無い）の記録を取り出す。コードと手順書は HEAD の版
        fixed_records.checkout(self.c)
        with open(os.path.join(self.c, TRIAL), "rb") as f:
            self.body = f.read()
        if not rows_of(self.body):
            raise unittest.SkipTest("試しの run のマニフェストが無い")
        self.rid = rows_of(self.body)[0]["run_id"]

    def tearDown(self):
        self.td.cleanup()

    def records(self):
        return ledger.verify_chain(ledger.read_ledger(os.path.join(self.c, "sealed", "ledger.jsonl")))

    def read(self, r, role):
        return ledger.read_target_json(self.c, r, role)

    def write_manifest(self, body):
        with open(os.path.join(self.c, TRIAL), "wb") as f:
            f.write(body)

    def commit(self, msg):
        git(self.c, "add", "-A")
        git(self.c, *(list(tl.AUTHOR) + ["commit", "-q", "-m", msg]))

    def verify(self, *extra):
        return tl.run_verify_inproc(self.c, "gkg-runs", *extra)

    def seal_result(self):
        return seal_gkg_result.seal(self.c, "trial", self.rid, NOW, "ots", runner=tw.FakeOts())


# 改変（監査の試したもの）。どれも、gkg-run-result が無くても、マニフェストの行の照合だけで止まる
def _set(i, k, v):
    def m(rows):
        rows[i][k] = v
    return m


ROW_MUTATIONS = [
    ("run-start の code_sha256", _set(0, "code_sha256", "0" * 64), "code_sha256"),
    ("run-start の trial_days", _set(0, "trial_days", ["2015-03-02", "2015-03-03"]), "trial_days"),
    ("run-start の method_access_seq", _set(0, "method_access_seq", 6), "method_access_seq"),
    ("run-start の filelist_sha256", _set(0, "filelist_sha256", "1" * 64), "filelist_sha256"),
    ("run-start の exclusion_rule_seq", _set(0, "exclusion_rule_seq", 6), "exclusion_rule_seq"),
    ("run-start の exclusion_rule_record_sha256", _set(0, "exclusion_rule_record_sha256", "2" * 64),
     "exclusion_rule_record_sha256"),
    ("run-start の区画", _set(0, "block_end", "2020-12-15"), "区画"),
    ("day の行を消す", lambda rows: rows.pop(2), "day の行から数えた"),
    ("day の日付を区画の外にする", _set(1, "day", "2015-03-05"), "の外"),
    ("day の日付を重ねる", _set(2, "day", "2015-03-02"), None),
    ("day の files_ok を変える", _set(1, "files_ok", 95), "files_listed"),
    ("day の sha256 の形を壊す", _set(1, "sha256", "xyz"), "sha256 の形"),
    ("run-complete の files_ok を変える", _set(-1, "files_ok", 287), "files_ok"),
    ("run-complete より後に行を足す", lambda rows: rows.append(dict(rows[1])), "run-complete"),
    ("day の code_sha256 を変える", _set(1, "code_sha256", "3" * 64), "code_sha256"),
    ("知らない kind の行", lambda rows: rows.insert(1, dict(rows[1], kind="note")), "kind"),
]


class TestManifestRows(Clone):
    def test_real_manifest_passes(self):
        runs = ledger.check_gkg_manifest_rows(self.records(), self.read, "trial", self.body)
        run = runs[self.rid]
        self.assertEqual(len(run["days"]), 3)
        self.assertIsNotNone(run["complete"])

    def test_mutations_stop_without_result(self):
        for name, mutate, text in ROW_MUTATIONS:
            rows = rows_of(self.body)
            mutate(rows)
            with self.subTest(name=name):
                with self.assertRaises(ledger.LedgerError) as cm:
                    ledger.check_gkg_manifests(self.records(), self.read, {"trial": dump(rows), "official": None})
                if text:
                    self.assertIn(text, str(cm.exception))
                # verify gkg-runs と all も止まる
                self.write_manifest(dump(rows))
                code, _out, err = self.verify()
                self.assertEqual(code, 1, name)
        self.write_manifest(self.body)
        code, out, err = self.verify()
        self.assertEqual(code, 0, err)

    def test_canonical_rewrite_still_passes(self):
        """行の書き方（キーの順・空白）だけを変えても、値が同じなら行の照合は通る（値を照らしている）。"""
        ledger.check_gkg_manifests(self.records(), self.read, {"trial": dump(rows_of(self.body)), "official": None})


class TestGkgRunResult(Clone):
    def test_seal_and_verify(self):
        code, out, _err = self.verify()
        self.assertEqual(code, 0)
        self.assertIn("gkg-run-result の記録が無い", out)
        rec, rel, _ots = self.seal_result()
        self.assertEqual(rec["kind"], ledger.GKG_RESULT_KIND)
        with open(os.path.join(self.c, rel), "rb") as f:
            doc = json.loads(f.read())
        self.assertEqual(doc["manifest_sha256"], ledger.sha256_hex(self.body))
        self.assertEqual(doc["manifest_lines"], self.body.count(b"\n"))
        self.assertEqual(doc["gkg_run_seq"], rows_of(self.body)[0]["gkg_run_seq"])
        self.assertEqual(doc["manifest_commit"], git(self.c, "rev-parse", "HEAD").decode().strip())
        self.commit("gkg-run-result")
        code, out, err = self.verify()
        self.assertEqual(code, 0, err)
        self.assertIn("gkg-run-result（seq %d）の manifest_sha256 は" % rec["seq"], out)
        self.assertIn("manifest_commit", out)
        code, out, err = tl.run_verify_inproc(self.c, "all", "--rev", "auto")
        self.assertEqual(code, 0, err)
        self.assertNotIn("gkg-run-result の記録が無い", out)
        # 封印のあとの改変：値が同じ形に収まる改変（day の sha256 を別の 64 桁にする、run-complete を消す、
        # 行を足す）も止まる
        rows = rows_of(self.body)
        cases = {
            "day の sha256 を別の値にする": lambda r: r[1].__setitem__("sha256", "4" * 64),
            "run-complete を消す": lambda r: r.pop(),
            "fetch_log_sha256 を変える": lambda r: r[-1].__setitem__("fetch_log_sha256", "5" * 64),
        }
        for name, mutate in cases.items():
            rr = rows_of(self.body)
            mutate(rr)
            self.write_manifest(dump(rr))
            code, _out, err = self.verify()
            self.assertEqual(code, 1, name)
            self.assertIn("gkg-run-result", err, name)
        self.write_manifest(self.body)
        code, _out, err = self.verify()
        self.assertEqual(code, 0, err)

    def test_writer_refusals(self):
        with self.assertRaisesRegex(ledger.LedgerError, "gkg-run-start の記録が 0 件"):
            seal_gkg_result.seal(self.c, "trial", "0" * 16, NOW, "ots", runner=tw.FakeOts())
        # コミットしていない行
        self.write_manifest(self.body + b"\n")
        with self.assertRaisesRegex(ledger.LedgerError, "HEAD の版と違う"):
            self.seal_result()
        # run-complete の無い（終わっていない）run
        self.write_manifest(dump(rows_of(self.body)[:-1]))
        self.commit("run-complete の前")
        with self.assertRaisesRegex(ledger.LedgerError, "run-complete の行が無い"):
            self.seal_result()
        self.write_manifest(self.body)
        self.commit("run-complete")
        before = open(os.path.join(self.c, "sealed", "ledger.jsonl"), "rb").read()
        self.assertEqual(len(ledger.split_lines(before)), len(self.records()))
        self.seal_result()
        self.commit("result")
        with self.assertRaisesRegex(ledger.LedgerError, "既にある"):
            self.seal_result()

    def test_result_checks_in_ledger(self):
        rec, _rel, _ots = self.seal_result()
        records = self.records()
        doc = self.read(rec, ledger.GKG_RESULT_KIND)
        ledger.check_gkg_results(records, self.read, {"trial": self.body, "official": None})
        bad_reads = {
            "gkg_run_seq": dict(doc, gkg_run_seq=7),
            "mode": dict(doc, mode="official"),
            "manifest_lines": dict(doc, manifest_lines=3),
            "run_complete_line_sha256": dict(doc, run_complete_line_sha256="6" * 64),
        }
        for name, bad in bad_reads.items():
            def read(r, role, bad=bad):
                return bad if r["seq"] == rec["seq"] else self.read(r, role)
            with self.subTest(name=name):
                with self.assertRaises(ledger.LedgerError):
                    ledger.check_gkg_results(records, read, {"trial": self.body, "official": None})

    def test_gate(self):
        with mock.patch.object(ledger, "PROJECT_ROOT", self.c):
            with self.assertRaisesRegex(ledger.GkgRunResultRequired, "gkg-run-result の記録が無い"):
                ledger.require_gkg_run_result("trial", self.rid)
            rec, _rel, _ots = self.seal_result()
            self.assertEqual(ledger.require_gkg_run_result("trial", self.rid), rec)
            rows = rows_of(self.body)
            rows[1]["sha256"] = "7" * 64
            self.write_manifest(dump(rows))
            with self.assertRaisesRegex(ledger.GkgRunResultRequired, "manifest_sha256"):
                ledger.require_gkg_run_result("trial", self.rid)


class TestDayFiles(Clone):
    """--day-files：仮の置き場所の日の集計（と取得の記録）の sha256 を照らす。"""

    def test_day_files(self):
        rows = rows_of(self.body)
        store = os.path.join(self.td.name, "store")
        os.makedirs(store)
        for r in rows:
            if r["kind"] == "day":
                data = ("day " + r["day"]).encode()
                r["sha256"] = ledger.sha256_hex(data)
                with open(os.path.join(store, r["file_name"]), "wb") as f:
                    f.write(data)
            if r["kind"] == "run-complete":
                data = b"log\n"
                r["fetch_log_sha256"], r["fetch_log_size"] = ledger.sha256_hex(data), len(data)
                with open(os.path.join(store, r["fetch_log_file"]), "wb") as f:
                    f.write(data)
        self.write_manifest(dump(rows))
        code, out, err = self.verify()
        self.assertEqual(code, 0, err)
        self.assertIn("--day-files で置き場所を渡したときだけ照らす", out)
        code, out, err = self.verify("--day-files", store)
        self.assertEqual(code, 0, err)
        self.assertIn("4 件を、置き場所のファイルの sha256 と照らし", out)
        # 1 バイト変える → 止まる
        name = rows[2]["file_name"]
        with open(os.path.join(store, name), "ab") as f:
            f.write(b"x")
        code, _out, err = self.verify("--day-files", store)
        self.assertEqual(code, 1)
        self.assertIn(name, err)
        # 置き場所に無いものは「照らさなかった」
        other = os.path.join(self.td.name, "other")
        os.makedirs(other)
        code, out, err = self.verify("--day-files", other)
        self.assertEqual(code, 0, err)
        self.assertIn("置き場所に無い 4 件", out)


class TestDocT066(unittest.TestCase):
    def test_statements(self):
        with open(DOC, encoding="utf-8") as f:
            text = f.read()
        for phrase in ("マニフェストの時刻証明（gkg-run-result。T-066）", "守れること・守れないこと",
                       "seal_gkg_result.py seal", "--day-files", "require_gkg_run_result",
                       "選び直す余地"):
            self.assertIn(phrase, text)


class TestOldLineFixed(unittest.TestCase):
    def test_no_old_line(self):
        with open(os.path.join(tl.PROJECT, "src", "sealer", "verify.py"), encoding="utf-8") as f:
            self.assertNotIn("まだ照合しない（kind が決まっていない）", f.read())


if __name__ == "__main__":
    unittest.main()
