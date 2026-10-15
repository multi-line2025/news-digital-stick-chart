"""T-103 のテスト（封印係）。
  1. 区分表のマニフェストが追記だけかを、verify が git の履歴で照らす（T-099 の監査 重大-1。verify.check_manifest_append_only）。
     各版に行の取り決めを当て、回数は履歴に現れた attempt の行の数の最大値。GKG の二つのマニフェストも、追記だけかを照らす。
  2. 最後の行の意味を出す（T-099 の監査 軽-4）。
  3. --write-content は、書く前に check_new を流し直す（T-100 の監査 軽-1）。HEAD の ledger と1行の差の照合（軽-3）。
  4. 行の形の定数が、収集係の themes.py（MANIFEST_ROW_KEYS・MANIFEST_LEGACY_FAILED_KEYS・FAILED_STAGES）と一致する。

実行（プロジェクトのルートで）:
    PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -B -m unittest discover -s tests/sealer -v

本物の記録は固定したコミット（fixed_records）を git から取り出して使う。書くのは一時のフォルダ（clone）の中だけ。
themes.py はファイルを読んで ast で定数を取り出すだけ（読み込まない・変えない）。
"""

import ast
import io
import contextlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import fixed_records  # noqa: E402
import test_ledger as tl  # noqa: E402
import test_t099 as t99  # noqa: E402
import test_t100 as t100  # noqa: E402

ledger = tl.ledger
verify = tl.verify
import seal_order4  # noqa: E402
import seal_records  # noqa: E402

REL = ledger.THEMES_MANIFEST
THEMES_PY = os.path.join(tl.PROJECT, "src", "collector", "themes.py")
NOT_PREFIX = "の版が、HEAD の版の先頭部分でない"


class CloneCase(unittest.TestCase):
    commit_id = fixed_records.THEMES_FAILED_COMMIT

    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.addCleanup(self.td.cleanup)
        self.c = os.path.join(self.td.name, "c")
        code = "worktree" if os.environ.get("SEALER_DOC_TEST_WORKTREE") == "1" else "head"
        fixed_records.checkout(self.c, self.commit_id, code=code)

    def git(self, *args):
        return subprocess.run(["git", "-C", self.c] + list(tl.AUTHOR) + list(args), check=True,
                              capture_output=True).stdout

    def read(self, rel=REL):
        with open(os.path.join(self.c, rel), "rb") as f:
            return f.read()

    def put(self, data, rel=REL, msg=None):
        with open(os.path.join(self.c, rel), "wb") as f:
            f.write(data)
        if msg:
            self.git("add", "--", rel)
            self.git("commit", "-q", "-m", msg)

    def verify(self, *args):
        return tl.run_verify_inproc(self.c, *(args or ("stats-order",)))

    def stops(self, text, *args):
        rc, _out, err = self.verify(*args)
        self.assertEqual(rc, 1, err)
        self.assertIn(text, err)


class TestThemesAppendOnly(CloneCase):
    def test_honest_passes_and_reports(self):
        rc, out, err = self.verify("all", "--rev", "auto")
        self.assertEqual(rc, 0, err)
        self.assertIn("追記だけ（T-103）：data/manifest/gdelt-themes.jsonl の版 2 個（git log --all --reflog --full-history）", out)
        self.assertIn("取得の試みの回数（履歴に現れた attempt の行の数の最大値）は 1（上限 3）。最後の行：failed", out)

    def test_delete_failed_line(self):
        """failed の行を消してコミットする（失敗の跡を消して、fetch で終わる形に見せる）と止まる。"""
        body = self.read()
        self.put(b"\n".join(body.split(b"\n")[:2]) + b"\n", msg="failed の行を消した（テスト）")
        self.stops(NOT_PREFIX)

    def test_recount_by_rewriting(self):
        """全部を消して、新しい試行の行1行から始め直す（回数を数え直させる）と止まる。"""
        first = self.read().split(b"\n")[0]
        self.put(b"", msg="空にした（テスト）")
        row = json.loads(first)
        row["attempted_at"] = "2026-10-16T00:00:00Z"
        self.put(json.dumps(row, sort_keys=True).encode() + b"\n", msg="始め直した（テスト）")
        self.stops(NOT_PREFIX)

    def test_deleted_file_counts_as_empty(self):
        """ファイルを消したコミットの版は空として扱う（空は先頭部分なので、それだけでは止まらない）。消す前の版が残る。"""
        body = self.read()
        self.git("rm", "-q", "--cached", "--", REL)
        self.git("commit", "-q", "-m", "マニフェストを索引から外した（テスト）")
        self.put(body, msg="同じ中身で戻した（テスト）")
        rc, out, err = self.verify()
        self.assertEqual(rc, 0, err)
        self.assertIn("の版 4 個", out)

    def test_rewrite_on_other_branch(self):
        """HEAD でない枝で書き換えても、--all で見つけて止まる。"""
        self.git("checkout", "-q", "-b", "side")
        body = self.read()
        self.put(body.replace(b'"reason": "ThemesError"', b'"reason": "OtherError"'), msg="枝で書き換えた（テスト）")
        self.git("checkout", "-q", "main")
        self.stops(NOT_PREFIX)

    def test_graft_does_not_hide(self):
        """書き換えたあとで、info/grafts で HEAD の親を切っても、照合は grafts を使わないので止まる。"""
        body = self.read()
        self.put(b"\n".join(body.split(b"\n")[:2]) + b"\n", msg="failed の行を消した（テスト）")
        head = self.git("rev-parse", "HEAD").decode().strip()
        os.makedirs(os.path.join(self.c, ".git", "info"), exist_ok=True)
        with open(os.path.join(self.c, ".git", "info", "grafts"), "w") as f:
            f.write(head + "\n")
        self.assertEqual(self.git("log", "--format=%H", "HEAD").decode().split(), [head])   # grafts は効いている
        with self.assertRaisesRegex(ledger.LedgerError, NOT_PREFIX):
            verify.check_manifest_append_only(verify.Repo(self.c), REL)
        rc, _out, _err = self.verify()
        self.assertEqual(rc, 1)

    def test_working_tree_rewrite(self):
        """作業ツリーだけで、コミットした行を消すと止まる。"""
        body = self.read()
        self.put(b"\n".join(body.split(b"\n")[:2]) + b"\n")
        self.stops("HEAD の版を先頭に持たない")

    def test_each_version_gets_rules(self):
        """各版に行の取り決めを当てる：途中の版にだけ並びの誤り（fetch のあとに attempt）があり、HEAD は先頭部分を持つ形。"""
        a, f, fl = t99.rows_of(self.read())
        bad_mid = t99.body_of([a, f])
        # 途中の版：attempt・fetch・（並びの誤りの）attempt。HEAD の版はその先頭部分にならないので、この形は追記だけの照合で
        # 止まる。取り決めの照合だけを確かめるため、関数を直接呼ぶ
        with self.assertRaisesRegex(ledger.LedgerError, "並びが違う"):
            ledger.check_themes_manifest_refs(ledger.verify_chain(self.read("sealed/ledger.jsonl")),
                                              bad_mid + t99.body_of([dict(a, attempted_at="2026-10-16T00:00:00Z")]))
        seen = []
        real = ledger.check_themes_manifest_refs

        def spy(records, body):
            seen.append(body)
            return real(records, body)
        with mock.patch.object(ledger, "check_themes_manifest_refs", spy):
            rc, _out, err = self.verify()
        self.assertEqual(rc, 0, err)
        self.assertIn(t99.body_of([a, f, fl]), seen)
        self.assertIn(t99.body_of([a]), seen)        # 履歴の途中の版（試行の行だけ。67ed3c1）にも当てた


class TestShallow(unittest.TestCase):
    def test_shallow_stops(self):
        with tempfile.TemporaryDirectory() as td:
            src = os.path.join(td, "src")
            fixed_records.checkout(src, fixed_records.THEMES_FAILED_COMMIT)
            c = os.path.join(td, "c")
            subprocess.run(["git", "clone", "-q", "--depth", "1", "file://" + src, c], check=True, capture_output=True)
            repo = verify.Repo(c)
            with self.assertRaisesRegex(ledger.LedgerError, "浅い clone"):
                verify.check_manifest_append_only(repo, REL)
            rc, _out, err = tl.run_verify_inproc(c, "stats-order")
            self.assertEqual(rc, 1)
            self.assertIn("浅い clone", err)


class TestGkgAppendOnly(CloneCase):
    def test_gkg_history_rewrite(self):
        """試しの run のマニフェストの1行を書き換えてコミットし、元に戻す（HEAD は元と同じなので、封印の照合には通る）。
        書き換えた版が履歴に残るので止まる。"""
        rel = ledger.GKG_MANIFESTS["trial"]
        body = self.read(rel)
        rc, out, err = self.verify("gkg-runs")
        self.assertEqual(rc, 0, err)
        self.assertIn("data/manifest/gdelt-gkg-trial.jsonl（trial）：版 1 個", out)
        self.put(body.replace(b'"kind": "run-complete"', b'"kind":  "run-complete"'), rel, msg="書き換え（テスト）")
        self.put(body, rel, msg="戻した（テスト）")
        self.stops(NOT_PREFIX, "gkg-runs")


class TestWriteContentChecks(t100.TestWriteContent):
    """--write-content の追加の照合（T-100 の監査 軽-1・軽-3）。test_t100.TestWriteContent の道具を使う（そのテストは継がない）。"""

    def test_write_content_runs_check_new(self):
        """書く前に check_new を流し直す：照合が止めれば、中身を書かない。"""
        self.fail_once()
        with mock.patch.object(verify, "check_order4_git", side_effect=ledger.LedgerError("照合の失敗（テスト）")):
            code, err = self.write_content(self.store)
        self.assertEqual(code, 1)
        self.assertIn("照合の失敗（テスト）", err)
        self.assertEqual(self.content_files(), [])

    def test_write_content_head_ledger(self):
        """記録の行をコミットしてしまった（HEAD の ledger が、最後の1行を除いたものでない）なら書かない。"""
        rec = self.fail_once()
        self.git("add", "--", "sealed/ledger.jsonl")
        self.git("commit", "-q", "-m", "記録の行だけをコミットした（テスト）")
        code, err = self.write_content(self.store)
        self.assertEqual(code, 1)
        self.assertIn("HEAD の版の sealed/ledger.jsonl が、今の記録から最後の seq %d を除いたものと同じでない" % rec["seq"], err)
        self.assertEqual(self.content_files(), [])


for _name in [n for n in dir(t100.TestWriteContent) if n.startswith("test_")]:
    setattr(TestWriteContentChecks, _name, None)


class TestRowKeysSameAsThemes(unittest.TestCase):
    """収集係の themes.py の行の形の定数（T-101 差し戻し2回目）と、ledger の取り決めが一致する。定数がまだ無い版なら飛ばす。"""

    def constants(self):
        with open(THEMES_PY, encoding="utf-8") as f:
            tree = ast.parse(f.read())
        out = {}
        for st in tree.body:
            if isinstance(st, ast.Assign) and len(st.targets) == 1 and isinstance(st.targets[0], ast.Name):
                try:
                    out[st.targets[0].id] = ast.literal_eval(st.value)
                except ValueError:
                    pass
        return out

    def test_same(self):
        c = self.constants()
        if "MANIFEST_ROW_KEYS" not in c:
            self.skipTest("themes.py に MANIFEST_ROW_KEYS がまだ無い")
        rows = c["MANIFEST_ROW_KEYS"]
        self.assertEqual(set(rows), set(ledger.THEMES_ROW_KEYS))
        for kind in ("attempt", "fetch", "result"):
            self.assertEqual(set(rows[kind]), set(ledger.THEMES_ROW_KEYS[kind]), kind)
        self.assertEqual(set(rows["failed"]), set(ledger.THEMES_FAILED_KEYS_WITH_STAGE))
        self.assertEqual(set(c["MANIFEST_LEGACY_FAILED_KEYS"]), set(ledger.THEMES_ROW_KEYS["failed"]))
        self.assertEqual(tuple(c["FAILED_STAGES"]), ledger.THEMES_FAILED_STAGES)
        self.assertEqual(c["MAX_TOTAL_ATTEMPTS"], ledger.THEMES_MAX_ATTEMPTS)


if __name__ == "__main__":
    unittest.main()
