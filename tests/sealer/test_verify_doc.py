"""docs/verify/periods-seal.md の手順を、第三者の立場で実行するテスト。T-005、T-007。

実行（プロジェクトのルートで）:
    PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest discover -s tests/sealer -v

- このリポジトリを一時的な場所に git clone し（手元の複製。ネットワークは使わない）、
  複製の中の文書から `<!-- test:offline -->` の付いたコマンドの塊を取り出して、そのまま実行する。
- 既定では、コミットされた版（HEAD）だけを使う。作業ツリーのファイルは何も重ねない。
  複製の作業ツリーが HEAD と同じであることも確かめる。
- コミットの前に作業ツリーのコードと手順書を試すときは、環境変数
  SEALER_DOC_TEST_WORKTREE=1 を付ける。このときは、複製の中で src/sealer・tests/sealer・
  docs/verify を作業ツリーのものに置き換えて、複製の中で一時的にコミットしてから試す
  （元のリポジトリには何も書かない）。この結果は、コミットされた版の検証にはならない。
- 壊さない複製では、すべての塊が終了コード 0 で終わり、記録の値が出力に現れること。
- わざと壊した複製（記録の書き換え・記録の削除・.ots の削除・履歴の書き換え・
  許可していないカレンダーの Pending）では、同じ手順が失敗すること。
- コミットがまだ無いときは、複製できないので飛ばす（理由を表示する）。
"""

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(os.path.dirname(HERE))
DOC_REL = os.path.join("docs", "verify", "periods-seal.md")
sys.path.insert(0, os.path.join(PROJECT, "src", "sealer"))
WORKTREE_MODE = os.environ.get("SEALER_DOC_TEST_WORKTREE") == "1"
OVERLAY = ("src/sealer", "tests/sealer", "docs/verify")

import ledger  # noqa: E402

AUTHOR = ("-c", "user.name=Multi-line", "-c",
          "user.email=197505900+multi-line2025@users.noreply.github.com")
BLOCK_RE = re.compile(r"<!-- test:offline -->\n```sh\n(.*?)```", re.S)


def offline_blocks(root):
    with open(os.path.join(root, DOC_REL), encoding="utf-8") as f:
        return BLOCK_RE.findall(f.read())


def has_head():
    r = subprocess.run(["git", "-C", PROJECT, "rev-parse", "--verify", "-q", "HEAD"],
                       capture_output=True)
    return r.returncode == 0


class TestDocProcedure(unittest.TestCase):
    def setUp(self):
        if not has_head():
            self.skipTest("コミットがまだ無いので、複製して手順を試せない")
        self.tmp = tempfile.mkdtemp()
        self.clone = os.path.join(self.tmp, "stick-chart-check")
        subprocess.run(["git", "clone", "-q", "--no-hardlinks", PROJECT, self.clone],
                       check=True, capture_output=True)
        if WORKTREE_MODE:
            # 複製の中で一時的にコミットする（元のリポジトリには書かない）。
            for rel in OVERLAY:
                shutil.rmtree(os.path.join(self.clone, rel), ignore_errors=True)
                shutil.copytree(os.path.join(PROJECT, rel), os.path.join(self.clone, rel),
                                ignore=shutil.ignore_patterns("__pycache__"))
            self.git("add", "-A", "--", *OVERLAY)
            self.git("commit", "-q", "--allow-empty", "-m", "一時的なコミット（テストの中だけ）")
        # 複製の作業ツリーが、複製の HEAD と同じであること（作業ツリーのファイルを重ねていない）。
        st = subprocess.run(["git", "-C", self.clone, "status", "--porcelain"],
                            check=True, capture_output=True).stdout
        self.assertEqual(st, b"")

    def tearDown(self):
        if hasattr(self, "tmp"):
            shutil.rmtree(self.tmp)

    def run_blocks(self):
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
        results = []
        for block in offline_blocks(self.clone):
            r = subprocess.run(["bash", "-e", "-o", "pipefail", "-c", block], cwd=self.clone,
                               capture_output=True, env=env, timeout=120)
            results.append((r.returncode, r.stdout.decode("utf-8", "replace")))
        return results

    def git(self, *args):
        subprocess.run(["git", "-C", self.clone] + list(AUTHOR) + list(args),
                       check=True, capture_output=True)

    def test_doc_has_offline_blocks(self):
        self.assertGreaterEqual(len(offline_blocks(self.clone)), 2)

    def test_clone_code_is_committed_version(self):
        """複製の検証のコードは、複製の HEAD のコミットの中身そのものである。"""
        for rel in ("src/sealer/verify.py", "src/sealer/ledger.py", DOC_REL):
            blob = subprocess.run(["git", "-C", self.clone, "show", "HEAD:" + rel],
                                  check=True, capture_output=True).stdout
            with open(os.path.join(self.clone, rel), "rb") as f:
                self.assertEqual(f.read(), blob, rel)

    def test_intact_clone_passes_and_shows_recorded_values(self):
        results = self.run_blocks()
        for code, out in results:
            self.assertEqual(code, 0, out)
        self.assertIn("すべての検査に通った。", results[0][1])
        data = ledger.read_ledger(os.path.join(self.clone, "sealed", "ledger.jsonl"))
        records = ledger.verify_chain(data)
        joined = "".join(out for _c, out in results)
        for r in records:
            for t in r["targets"]:
                self.assertIn(t["sha256"], joined)
        # 時刻証明の対象のハッシュが、標準の道具で出した値と一致する。
        for _seq, _path, digest, _atts in ledger.check_anchors(
                data, os.path.join(self.clone, "sealed")):
            self.assertIn(digest, joined)
        out = results[0][1]
        # acquisition の記録が無いうちは、採用は保留。各 seq の Pending の状態も出る。
        if not any(r["kind"] == ledger.ACQUISITION_KIND for r in records):
            self.assertIn("採用は保留（acquisition の記録が無いため）", out)
        for r in records:
            self.assertRegex(out, r"seq %d: (Pending|Bitcoin で確定)" % r["seq"])
        # 確かめていないこと（ヘッダが本当の鎖にあること、drand の署名）が出る。
        self.assertIn("ヘッダが、Bitcoin の本当の鎖にあること", out)
        self.assertIn("drand の署名（BLS）は、オフラインでは検証していない", out)

    def assertProcedureFails(self):
        codes = [c for c, _out in self.run_blocks()]
        self.assertTrue(any(c != 0 for c in codes), codes)

    def test_tampered_ledger_fails(self):
        p = os.path.join(self.clone, "sealed", "ledger.jsonl")
        with open(p, "rb") as f:
            data = f.read()
        rec = json.loads(data.split(b"\n")[0])
        rec["targets"][0]["sha256"] = "0" * 64
        with open(p, "wb") as f:
            f.write(ledger.canonical_line(rec) + b"\n" + data.split(b"\n", 1)[1])
        self.assertProcedureFails()

    def test_emptied_ledger_fails(self):
        open(os.path.join(self.clone, "sealed", "ledger.jsonl"), "wb").close()
        self.assertProcedureFails()

    def test_missing_ots_fails(self):
        for name in os.listdir(os.path.join(self.clone, "sealed")):
            if name.endswith(".ots"):
                os.rename(os.path.join(self.clone, "sealed", name),
                          os.path.join(self.tmp, name))
        self.assertProcedureFails()

    def test_own_calendar_pending_fails(self):
        """seq 1 の .ots を、許可していないカレンダーの Pending に差し替えると失敗する。"""
        sealed = os.path.join(self.clone, "sealed")
        data = ledger.read_ledger(os.path.join(sealed, "ledger.jsonl"))
        ots = os.path.join(sealed, ledger.ots_name(1))
        with open(ots, "rb") as f:
            raw = f.read()
        for uri in sorted(ledger.ALLOWED_PENDING_URIS):
            fake = "https://evil.example".ljust(len(uri), "x")[:len(uri)]
            raw = raw.replace(uri.encode(), fake.encode())
        with open(ots, "wb") as f:
            f.write(raw)
        self.assertEqual(ledger.ots_file_digest(raw), ledger.prefix_digest(data, 1))
        self.assertProcedureFails()

    def test_rewritten_history_fails(self):
        """封印した対象を書き換えた履歴を作り直しても（seq 1 を含む最初のコミットごと）見つかる。"""
        self.git("checkout", "-q", "--orphan", "rewritten")
        doc = os.path.join(self.clone, "docs", "stats", "periods.md")
        with open(doc, "a", encoding="utf-8") as f:
            f.write("履歴を書き換えて足した行\n")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "rewritten")
        self.assertProcedureFails()


if __name__ == "__main__":
    unittest.main()
