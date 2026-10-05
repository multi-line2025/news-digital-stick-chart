"""docs/verify/periods-seal.md の手順を、第三者の立場で実行するテスト。T-005。

実行（プロジェクトのルートで）:
    PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest discover -s tests/sealer -v

- このリポジトリを一時的な場所に git clone し（手元の複製。ネットワークは使わない）、
  文書の `<!-- test:offline -->` の付いたコマンドの塊を、文書から取り出してそのまま実行する。
- 壊さない複製では、すべての塊が終了コード 0 で終わり、記録の値が出力に現れること。
- わざと壊した複製（記録の書き換え・記録の削除・.ots の削除・履歴の書き換え）では、
  同じ手順が失敗すること。
- 検証のコード（src/sealer/）と手順書（docs/verify/）は、作業ツリーのものを複製に重ねる。
  記録・時刻証明・対象のファイルは、コミットされたものだけを使う。
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
DOC = os.path.join(PROJECT, "docs", "verify", "periods-seal.md")
sys.path.insert(0, os.path.join(PROJECT, "src", "sealer"))

import ledger  # noqa: E402

AUTHOR = ("-c", "user.name=Multi-line", "-c",
          "user.email=197505900+multi-line2025@users.noreply.github.com")
BLOCK_RE = re.compile(r"<!-- test:offline -->\n```sh\n(.*?)```", re.S)


def offline_blocks():
    with open(DOC, encoding="utf-8") as f:
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
        # 作業中の検証のコードと手順書を、複製に重ねる（コミットの前でも、今のコードと
        # 今の手順書で試すため。コミットの後は同じ中身なので何も変わらない）。
        for rel in ("src/sealer", "docs/verify"):
            shutil.rmtree(os.path.join(self.clone, rel), ignore_errors=True)
            shutil.copytree(os.path.join(PROJECT, rel), os.path.join(self.clone, rel),
                            ignore=shutil.ignore_patterns("__pycache__"))

    def tearDown(self):
        if hasattr(self, "tmp"):
            shutil.rmtree(self.tmp)

    def run_blocks(self):
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
        results = []
        for block in offline_blocks():
            r = subprocess.run(["bash", "-e", "-o", "pipefail", "-c", block], cwd=self.clone,
                               capture_output=True, env=env, timeout=120)
            results.append((r.returncode, r.stdout.decode("utf-8", "replace")))
        return results

    def git(self, *args):
        subprocess.run(["git", "-C", self.clone] + list(AUTHOR) + list(args),
                       check=True, capture_output=True)

    def test_doc_has_offline_blocks(self):
        self.assertGreaterEqual(len(offline_blocks()), 2)

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
        # 期限が未確定のうちは、そのことと Pending の状態が出力に出る。
        if not any(r["kind"] == ledger.ACQUISITION_KIND for r in records):
            self.assertIn("期限：未確定", results[0][1])
        self.assertIn("ots verify で確かめる", results[0][1])

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
