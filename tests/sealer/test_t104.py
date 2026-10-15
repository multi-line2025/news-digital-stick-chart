"""T-104 のテスト（封印係）：区分表のマニフェストの行と git の履歴の照合（verify.check_themes_attempt_code）。T-102 の監査の残り。
  - 中-1：attempt の行は、その行を初めて含んだコミット C の版の themes.py とだけ照らす（親の版は使わない。監査 pB）。
  - 中-3：fetch の行は、C の第一の親の版で、マニフェストが直前の attempt で終わり、themes.py が同じ版であること。failed・
    result の行は、直前の fetch と同じコミットで入ったこと。
  - 軽-2：同じバイト列の attempt の行が2つあっても、何行目かで別々に結びつける。
  - 軽-4：コミットしていない行の「照らさなかった」が、verify all の最後の一覧に入る。

実行（プロジェクトのルートで）:
    PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -B -m unittest discover -s tests/sealer -v

本物の記録は固定したコミット（fixed_records.THEMES_FAILED_COMMIT）を git から取り出した clone で使う。書くのは clone の中だけ。
"""

import os
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import test_ledger as tl  # noqa: E402
import test_t099 as t99  # noqa: E402
import test_t103 as t103  # noqa: E402

ledger = tl.ledger
verify = tl.verify
REL = ledger.THEMES_MANIFEST
CODE = "src/collector/themes.py"


class Case(t103.CloneCase):
    def rows(self):
        return t99.rows_of(self.read())

    def append(self, rows, extra=None, msg="行を足した（テスト）"):
        with open(os.path.join(self.c, REL), "ab") as f:
            f.write(t99.body_of(rows))
        paths = [REL]
        if extra is not None:
            with open(os.path.join(self.c, CODE), "a", encoding="utf-8") as f:
                f.write(extra)
            paths.append(CODE)
        if msg:
            self.git("add", "--", *paths)
            self.git("commit", "-q", "-m", msg)

    def sha(self):
        with open(os.path.join(self.c, CODE), "rb") as f:
            return ledger.sha256_hex(f.read())

    def retry(self, day="16"):
        a = self.rows()[0]
        return dict(a, attempted_at="2026-10-%sT01:00:00Z" % day, code_sha256=self.sha())

    def fetch_failed(self, sha, day="16"):
        """fetch と failed の行。failed の形は、その版の themes.py が書く形（固定コミットの版 73877f10… は stage を書かない）。"""
        failed = {"kind": "failed", "at": "2026-10-%sT02:00:01Z" % day, "reason": "ThemesError"}
        if sha != ledger.THEMES_LEGACY_FAILED_CODE_SHA256:
            failed["stage"] = "shape"
        return [{"kind": "fetch", "at": "2026-10-%sT02:00:00Z" % day, "code_sha256": sha}, failed]


class TestAttemptOwnCommit(Case):
    def test_honest(self):
        a2 = self.retry()
        self.append([a2])
        self.append(self.fetch_failed(a2["code_sha256"]))
        rc, out, err = self.verify("all", "--rev", "auto")
        self.assertEqual(rc, 0, err)
        self.assertIn("attempt の行 2 行の code_sha256 は、その行を初めて含んだコミットの版の themes.py と同じ", out)
        self.assertIn("fetch の行 2 行は、その行を初めて含んだコミットの第一の親の版で", out)
        self.assertIn("failed・result の行 2 行は、直前の fetch と同じコミットで入った", out)

    def test_attempt_and_code_change_in_same_commit(self):
        """監査 pB：試行の行と themes.py の変更を同じコミットに入れる（試行の行の値は変える前の版）。C の版と合わないので止まる。"""
        a2 = self.retry()                                   # 変える前の版の sha256
        self.append([a2], extra="# 変えた（テスト）\n")
        self.stops("4 行目（attempt）の code_sha256")


class TestFetchHistory(Case):
    def test_fetch_without_committed_attempt(self):
        """試行の行をコミットせずに通信した形（attempt・fetch・failed を1つのコミットで足す）は止まる。"""
        a2 = self.retry()
        self.append([a2] + self.fetch_failed(a2["code_sha256"]))
        self.stops("第一の親")

    def test_fetch_code_differs_from_parent(self):
        """試行の行をコミットしたあとで themes.py を変えてコミットし、その版で通信した形（fetch の code_sha256 は試行の行と
        同じ値に書いた）。fetch の第一の親の版の themes.py と合わないので止まる。"""
        a2 = self.retry()
        self.append([a2])
        with open(os.path.join(self.c, CODE), "a", encoding="utf-8") as f:
            f.write("# 変えた（テスト）\n")
        self.git("add", "--", CODE)
        self.git("commit", "-q", "-m", "themes.py を変えた（テスト）")
        self.append(self.fetch_failed(a2["code_sha256"]))
        self.stops("第一の親")

    def test_failed_in_later_commit(self):
        """fetch の行だけをコミットし、あとで failed の行を足した形は止まる。"""
        a2 = self.retry()
        self.append([a2])
        f, fl = self.fetch_failed(a2["code_sha256"])
        self.append([f])
        self.append([fl])
        self.stops("直前の fetch の行と同じコミットで入っていない")


class TestSameBytesAttempts(Case):
    def test_two_identical_attempt_lines(self):
        """同じバイト列の attempt の行が2つあるとき（取り直しで同じ時刻・同じ版の行を書いた作り物）、2つ目は自分のコミットの版と
        照らす。2つ目を足すときに themes.py を変えると、2つ目のコミットの版と合わないので止まる（1つ目のコミットと結びつけると
        通ってしまう形）。"""
        a2 = self.retry()
        self.append([a2])
        ff = [dict(r, at=a2["attempted_at"]) for r in self.fetch_failed(a2["code_sha256"])]   # 時刻が戻らないよう同じ時刻
        self.append(ff)
        self.append([a2], extra="# 変えた（テスト）\n")
        rows = self.rows()
        self.assertEqual(t99.body_of([rows[3]]), t99.body_of([rows[6]]))
        self.stops("7 行目（attempt）の code_sha256")


class TestUncommittedListed(Case):
    def test_uncommitted_rows_in_final_list(self):
        """コミットしていない行の「照らさなかった」は、verify all の最後の一覧に入る（終了コードは 0）。"""
        a2 = self.retry()
        self.append([a2], msg=None)
        rc, out, err = self.verify("all", "--rev", "auto")
        self.assertEqual(rc, 0, err)
        last = [l for l in out.splitlines() if l.startswith("ただし、次は照らさなかった")][0]
        self.assertIn("区分表のマニフェストの attempt の行（attempted_at 2026-10-16T01:00:00Z）の code_sha256（その行がまだ"
                      "コミットされていない）", last)
        self.append(self.fetch_failed(a2["code_sha256"]), msg=None)
        rc, out, err = self.verify("all", "--rev", "auto")
        self.assertEqual(rc, 0, err)
        last = [l for l in out.splitlines() if l.startswith("ただし、次は照らさなかった")][0]
        self.assertIn("区分表のマニフェストの 5 行目（fetch）の git の履歴との照合（その行がまだコミットされていない）", last)
        self.assertIn("区分表のマニフェストの 6 行目（failed）の git の履歴との照合（その行がまだコミットされていない）", last)


if __name__ == "__main__":
    unittest.main()
