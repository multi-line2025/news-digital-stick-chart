"""T-037 のテスト：統計係の順番1・順番1b の封印の kind（stats-order1・stats-order1b）と、
T-031 の監査の中2・軽1〜軽4。

実行（プロジェクトのルートで）:
    PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest discover -s tests/sealer -v

ネットワークは使わない（drand・ots は偽物）。git init した仮のプロジェクト（写し）に、統計係の
ファイルの代わり（引数なしで JSON を出す仮の exclusion.py・tagrules.py、通る仮のテスト、表を持つ
仮の seal-order1.md、承認の行を持つ仮の reviews/）を置き、封印係のコードの決まった commit の定数
（seal_stats.ORDER1_ANCESTORS など）を、テストの中だけ仮の commit に差し替える。本物の sealed/ には
書かない。
  1. 順番1 を書き、そのあと区分表の取得の記録・method-access・gkg-run-start が書けること。
  2. 順番1 が無ければ、それらが（drand の前に）止まること。
  3. "undecided"、sha256 の食い違い、作業ツリーの汚れ、承認の行の欠け、祖先でない commit、
     区分表の取得や GKG の跡、method-access があるときに止まること。
  4. verify：順番1・1b の位置、除外の規則の kind の最初の記録、順番1b が gkg-run-start の前に要ること。
  5. T-031 の監査の軽1（trial_days は収集係の TRIAL_DAYS と同じ 3 日ちょうど）。
"""

import hashlib
import json
import os
import re
import subprocess
import sys
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import test_ledger as tl  # noqa: E402
import test_t014 as t14  # noqa: E402
import test_t017 as t17  # noqa: E402
import test_writers as tw  # noqa: E402
from test_ledger import T0, H  # noqa: E402

ledger = tl.ledger
import seal_acquisition  # noqa: E402
import seal_gkg_run  # noqa: E402
import seal_stats  # noqa: E402

DOC = os.path.join(tl.PROJECT, "docs", "verify", "periods-seal.md")
ROUND = 30_000_000
FILELIST = ledger.FILELIST_CODE_PATH
THEMES = ledger.THEMES_CODE_PATH
GKG_CODE = "src/collector/acquire_gkg.py"

EXCLUSION_PY = '''import json
STATUS = "decided"
print(json.dumps({"optional_choice_status": STATUS,
                  "owner_choice_source": %r}, sort_keys=True))
''' % seal_stats.OWNER_CHOICE_SOURCE
TAGRULES_PY = '''import json
print(json.dumps({"exclusion": {"optional_choice_status": "decided"}, "v": %d}, sort_keys=True))
'''
OK_TEST = '''import unittest
class T(unittest.TestCase):
    def test_ok(self):
        self.assertTrue(True)
'''
T022 = "# T-022\n\n> Kはいま封印していいよ\n\n> 2.数え方の候補を先に封印し、最後に全候補のタグの一覧を並べて公開する案でよいか\n> それでいいです。\n"
T024 = "# T-024\n\n> いいよ、正式に扱う基準は一つに絞ろう。\n"
T020 = ("# T-020\n\n## 2026-10-08 オーナーの発言（原文のまま記録）\n> 病名は案B\n"
        "> 民族、宗教の集団は除外の区分に加える。\n> そのほかこのまま承認の項目は承認します\n\n## 次\n")


class StatsCase(t14.Case):
    """順番1・1b を、書く仕組み（seal_stats）で写しの上に書けるようにした仮のプロジェクト。"""

    def setUp(self):
        super().setUp()
        self.write("src/collector/acquire_filelist.py", "# 一覧の取得（仮）\n")
        self.write(THEMES, "# 区分表の取得（仮）\n")
        self.write(GKG_CODE, "# GKG の取得（仮）\n")
        self.write("src/stats/tagrules.py", TAGRULES_PY % 1)
        self.write("reviews/T-022.md", T022)
        self.write("reviews/T-024.md", T024)
        self.write("reviews/T-020.md", T020)
        self.write(".gitignore", ".venv/\n")
        os.makedirs(os.path.join(self.root, ".venv", "bin"))
        os.symlink(sys.executable, os.path.join(self.root, ".venv", "bin", "python"))
        self.commit("昔の版")
        self.hist = self.git("rev-parse", "HEAD").decode().strip()
        self.short = self.hist[:7]
        for name, val in (("ORDER1_ANCESTORS", {self.short: self.hist}),
                          ("ORDER1_APPROVALS", tuple((a[0], self.hist, a[2], a[3])
                                                     for a in seal_stats.ORDER1_APPROVALS)),
                          ("OWNER_CHOICE", (self.hist,) + tuple(seal_stats.OWNER_CHOICE[1:]))):
            p = mock.patch.object(seal_stats, name, val)
            p.start()
            self.addCleanup(p.stop)
        self.write("src/stats/tagrules.py", TAGRULES_PY % 2)
        self.write("src/stats/exclusion.py", EXCLUSION_PY)
        self.write("tests/stats/test_exclusion.py", OK_TEST)
        self.write("tests/stats/test_tagrules.py", OK_TEST)
        self.write("docs/stats/tags-naive.md", "# tags-naive（仮）\n")
        self.write("docs/stats/counting.md", "# counting（仮）\n")
        self.write_table()
        self.commit("今の版")

    def write(self, rel, text):
        full = os.path.join(self.root, rel)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w", encoding="utf-8") as f:
            f.write(text)

    def out(self, script, cwd=None):
        return subprocess.run([sys.executable, "-B", script], cwd=cwd or self.root,
                              capture_output=True, check=True).stdout

    def table_rows(self, wrong=None):
        rows = []
        for rel in ("src/stats/exclusion.py", "tests/stats/test_exclusion.py", "src/stats/tagrules.py",
                    "tests/stats/test_tagrules.py", "docs/stats/tags-naive.md"):
            with open(os.path.join(self.root, rel), "rb") as f:
                rows.append((rel, hashlib.sha256(f.read()).hexdigest()))
        for rel in ("src/stats/exclusion.py", "src/stats/tagrules.py"):
            rows.append((rel + " の出力", hashlib.sha256(self.out(rel)).hexdigest()))
        old = (TAGRULES_PY % 1).encode()
        rows.append(("%s:src/stats/tagrules.py" % self.short, hashlib.sha256(old).hexdigest()))
        rows.append(("%s:src/stats/tagrules.py の出力" % self.short, hashlib.sha256(
            subprocess.run([sys.executable, "-B", "-c", old.decode()], capture_output=True,
                           check=True).stdout).hexdigest()))
        rows.append(("%s:reviews/T-020.md" % self.short, hashlib.sha256(T020.encode()).hexdigest()))
        if wrong is not None:
            rows = [(n, "0" * 64 if n == wrong else s) for n, s in rows]
        return rows

    def write_table(self, wrong=None):
        lines = ["# 順番1（仮）", "", seal_stats.TABLE_MARKER, "| 対象 | sha256 |", "|---|---|"]
        lines += ["| `%s` | `%s` |" % r for r in self.table_rows(wrong)]
        self.write(seal_stats.TABLE_DOC, "\n".join(lines) + "\n")

    def base(self):
        """periods・candidates と、手順3（一覧の取得。acquire_filelist.py）まで。"""
        self.seal()
        s, _r, _o = self.start(T0 + H, code=FILELIST)
        self.result(T0 + 2 * H, s["seq"])
        self.commit("手順3まで")

    def order1(self, now=T0 + 3 * H):
        rec, rel, _o = seal_stats.seal_order1(self.root, now, "ots", runner=tw.FakeOts())
        self.commit("順番1")
        return rec, rel

    def order1b(self, now=T0 + 4 * H, files=("docs/stats/counting.md",)):
        approvals = [{"item": "候補の一覧", "commit": self.hist, "path": "reviews/T-022.md",
                      "lines": ["> それでいいです。"]}]
        rec, rel, _o = seal_stats.seal_order1b(self.root, list(files), approvals, now, "ots",
                                               runner=tw.FakeOts())
        self.commit("順番1b")
        return rec, rel

    def gkg_sha(self):
        with open(os.path.join(self.root, GKG_CODE), "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()

    def gkg_run(self, now, method_seq, nocall=False):
        o1 = ledger.first_order1(self.records())
        return seal_gkg_run.start(
            self.root, "trial", GKG_CODE, self.gkg_sha()[:16], "e" * 64, method_seq,
            list(ledger.TRIAL_DAYS), o1["seq"] if o1 else 1,
            hashlib.sha256(ledger.canonical_line(o1)).hexdigest() if o1 else "0" * 64, now, "ots",
            drand_fetch=t17.NoCall() if nocall else tw.FakeDrand(now), runner=tw.FakeOts())

    def refuses(self, fn, msg):
        before, data = self.snapshot(), self.ledger_bytes()
        with self.assertRaises(ledger.LedgerError) as cm:
            fn()
        self.assertIn(msg, str(cm.exception))
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.ledger_bytes(), data)


# ---------------------------------------------------------------- 1. 書けること


class TestOrder1Flow(StatsCase):
    def test_order1_then_themes_method_and_gkg(self):
        """完了条件：順番1 を書き、そのあと区分表の取得の記録・method-access・gkg-run-start が書ける。"""
        self.base()
        o1, rel = self.order1()
        doc = self.doc_of(rel)
        self.assertEqual(sorted(doc), list(ledger.ORDER1_DOC_KEYS))
        self.assertEqual(len(doc["targets"]), 10)
        self.assertEqual(doc["head"], self.git("rev-parse", "HEAD~1").decode().strip())
        self.assertEqual(doc["python"]["path"], ".venv/bin/python")
        self.assertEqual([a["item"] for a in doc["approvals"]], ["A", "B", "B (ii)"])
        self.assertEqual(doc["checks"]["optional_choice_status"], "decided")
        self.assertEqual(doc["checks"]["stats_tests"], "OK (2 tests)")
        self.assertEqual(doc["checks"]["acquisition_starts"], ["seq 3: %s" % FILELIST])
        self.order1b()
        th, _r, _o = self.start(T0 + 5 * H, code=THEMES)
        m, _r, _o = self.method(T0 + 6 * H)
        self.commit("手順4")
        g, _r, _o = self.gkg_run(T0 + 7 * H, m["seq"])
        self.commit("試しの run")
        out = self.verify_ok("all", "--rev", "auto")
        self.assertIn("stats-order1 seq %d（順番1）: HEAD %s" % (o1["seq"], doc["head"]), out)
        self.assertIn("除外の規則の kind（stats-order1）の最初の記録：seq %d" % o1["seq"], out)
        self.assertIn("試しの run 1 回", out)
        self.method_gate()

    def test_order1b_records_order1_ref(self):
        self.base()
        o1, _rel = self.order1()
        _o1b, rel = self.order1b()
        doc = self.doc_of(rel)
        self.assertEqual(doc["order1_ref"]["seq"], o1["seq"])
        self.assertEqual(doc["files"][0]["path"], "docs/stats/counting.md")
        self.assertEqual([a["item"] for a in doc["approvals"]], ["候補の一覧", "B (ii)"])
        self.verify_ok("stats-order")


# ---------------------------------------------------------------- 2. 順番1 が無ければ止まる


class TestWithoutOrder1(StatsCase):
    def test_themes_and_gkg_refused_without_order1(self):
        """完了条件：順番1 が無ければ、区分表の取得の記録と gkg-run-start が（drand の前に）止まる。
        method-access は止めない（リードへの報告：収集係のテストが順番1 の無い写しに method-access を
        書くため。手順書 13章の限界）。その代わり、method-access のあとでは順番1 を書けず、
        gkg-run-start も書けないこと（先へ進めないこと）を確かめる。"""
        self.base()
        self.refuses(lambda: seal_acquisition.start(self.root, THEMES, T0 + 3 * H, "ots",
                                                    drand_fetch=t17.NoCall(), runner=tw.FakeOts()),
                     "区分表の取得（src/collector/themes.py）は、順番1（stats-order1）の記録の後")
        m, _r, _o = self.method(T0 + 3 * H)
        self.commit("順番1 の無いまま手順4")
        self.refuses(lambda: self.gkg_run(T0 + 4 * H, m["seq"], nocall=True),
                     "除外の規則の kind（stats-order1）の記録が無い")
        self.refuses(lambda: self.order1(T0 + 4 * H), "method-access の記録がある")
        # 書く仕組みを飛ばして順番1 を足しても、verify が止まる
        o = self.add_order1(T0 + 4 * H)
        self.verify_fails(("stats-order", "all"), "stats-order1 の記録（seq %d）が、最初の method-access" % o)

    def add_method_raw(self, now):
        doc = self._drand_doc(ledger.METHOD_ACCESS_KIND, ROUND, None)
        return self._append_doc(ledger.METHOD_ACCESS_KIND, doc, now)

    def test_gkg_refused_without_order1b(self):
        self.base()
        self.order1()
        m, _r, _o = self.method(T0 + 4 * H)
        self.commit("手順4")
        self.refuses(lambda: self.gkg_run(T0 + 5 * H, m["seq"], nocall=True), "順番1b（stats-order1b）の記録が無い")

    def test_themes_raw_without_order1_fails_verify(self):
        self.base()
        doc = self._drand_doc(ledger.ACQ_START_KIND, ROUND, None)
        doc.update({"step": 3, "fetch": {"code_path": THEMES, "code_sha256": "a" * 64}})
        t = self._append_doc(ledger.ACQ_START_KIND, doc, T0 + 3 * H)
        self.verify_fails(("stats-order", "all"),
                          "最初の 区分表の取得（acquisition-start） の記録（seq %d）より前に、stats-order1" % t)


# ---------------------------------------------------------------- 3. 順番1 の書く前の照合


class TestOrder1Refusals(StatsCase):
    def test_undecided_refused(self):
        """完了条件："undecided" で止まる。"""
        self.base()
        self.write("src/stats/exclusion.py", EXCLUSION_PY.replace('"decided"', '"undecided"'))
        self.write_table()
        self.commit("undecided")
        self.refuses(lambda: self.order1(), "除外の規則の出力 の optional_choice_status が 'undecided'")

    def test_sha256_mismatch_refused(self):
        """完了条件：表と、封印係が計算し直した sha256 が食い違えば止まる。"""
        self.base()
        self.write_table(wrong="src/stats/tagrules.py の出力")
        self.commit("表の値が違う")
        self.refuses(lambda: self.order1(), "対象 src/stats/tagrules.py の出力 の sha256")

    def test_dirty_worktree_refused(self):
        self.base()
        self.write("untracked.txt", "x\n")
        self.refuses(lambda: self.order1(), "作業ツリーがきれいでない")

    def test_missing_approval_line_refused(self):
        self.base()
        with mock.patch.object(seal_stats, "ORDER1_APPROVALS",
                               (("A", self.hist, "reviews/T-022.md", ("> 無い行",)),)):
            self.refuses(lambda: self.order1(), "承認 A：")

    def test_not_ancestor_refused(self):
        self.base()
        with mock.patch.object(seal_stats, "ORDER1_ANCESTORS", {"1234567": "1" * 40}):
            self.refuses(lambda: self.order1(), "短い ID 1234567")

    def test_owner_choice_line_missing_refused(self):
        self.base()
        with mock.patch.object(seal_stats, "OWNER_CHOICE",
                               (self.hist, "reviews/T-020.md", "## 2026-10-08 オーナーの発言（原文のまま記録）",
                                ("> 無い行",))):
            self.refuses(lambda: self.order1(), "見出しの節に、行")

    def test_themes_manifest_refused(self):
        self.base()
        self.write(seal_stats.THEMES_MANIFEST, '{"kind":"attempt"}\n')
        self.commit("区分表の取得を試みた")
        self.refuses(lambda: self.order1(), "gdelt-themes.jsonl に行がある")

    def test_themes_manifest_history_refused(self):
        """作業ツリーで空にしても、履歴に行があれば止まる。"""
        self.base()
        self.write(seal_stats.THEMES_MANIFEST, '{"kind":"attempt"}\n')
        self.commit("試みた")
        self.write(seal_stats.THEMES_MANIFEST, "")
        self.commit("空にした")
        self.refuses(lambda: self.order1(), "gdelt-themes.jsonl の履歴が空でない")

    def test_gkg_manifest_refused(self):
        self.base()
        self.write(seal_stats.GKG_MANIFESTS[1], '{"kind":"run-start"}\n')
        self.commit("試しの run")
        self.refuses(lambda: self.order1(), "gdelt-gkg-trial.jsonl に行がある")

    def test_method_access_refused(self):
        self.base()
        self.add_order1(T0 + 3 * H)
        self.method(T0 + 4 * H)
        self.commit("手順4")
        self.refuses(lambda: self.order1(), "method-access の記録がある")

    def test_wrong_acquisition_code_refused(self):
        self.seal()
        self.start(T0 + H)          # 一覧の取得のコードでない（tw.CODE_REL）
        self.commit("手順3")
        self.refuses(lambda: self.order1(), "fetch.code_path が src/collector/acquire_filelist.py でない")

    def test_failing_stats_tests_refused(self):
        self.base()
        self.write("tests/stats/test_fail.py", OK_TEST.replace("assertTrue(True)", "assertTrue(False)"))
        self.commit("通らないテスト")
        self.refuses(lambda: self.order1(), "tests/stats が通らない")


class TestOrder1bRefusals(StatsCase):
    def test_after_method_access_refused(self):
        self.base()
        self.order1()
        self.method(T0 + 4 * H)
        self.commit("手順4")
        self.refuses(lambda: self.order1b(T0 + 5 * H), "method-access の記録がある")

    def test_uncommitted_file_refused(self):
        self.base()
        self.write("docs/stats/new.md", "x\n")
        self.git("add", "docs/stats/new.md")
        self.refuses(lambda: self.order1b(files=("docs/stats/new.md",)), "作業ツリーがきれいでない")

    def test_file_outside_head_refused(self):
        self.base()
        self.refuses(lambda: self.order1b(files=("docs/stats/none.md",)), "docs/stats/none.md が無い")

    def test_bii_approval_always_checked(self):
        self.base()
        with mock.patch.object(seal_stats, "ORDER1_APPROVALS", seal_stats.ORDER1_APPROVALS[:2] + (
                ("B (ii)", self.hist, "reviews/T-024.md", ("> 無い行",)),)):
            self.refuses(lambda: self.order1b(), "承認 B (ii)：")


# ---------------------------------------------------------------- 4. verify の位置の照合


class TestStatsOrderVerify(t14.Case):
    def test_order1_after_method_access_fails(self):
        self.seal()
        self.step3(T0 + H)               # 順番1 を足す
        self.method(T0 + 3 * H)
        o = self.add_order1(T0 + 4 * H)
        self.verify_fails(("stats-order", "all"), "stats-order1 の記録（seq %d）が、最初の method-access" % o)

    def test_order1b_after_method_access_fails(self):
        self.seal()
        self.step3(T0 + H)
        self.method(T0 + 3 * H)
        o = self.add_order1b(T0 + 4 * H)
        self.verify_fails(("stats-order",), "stats-order1b の記録（seq %d）が、最初の method-access" % o)

    def test_bad_doc_shape_fails(self):
        self.seal()
        o = self.add_order1(T0 + H, checks={"worktree_clean": False})
        self.verify_fails(("stats-order", "all"), "seq %d の stats-order1 の checks のキー" % o)
        self.tearDown()
        self.setUp()
        self.seal()
        o = self.add_order1(T0 + H, targets=[{"name": "src/stats/exclusion.py", "sha256": "a" * 64}])
        self.verify_fails(("stats-order",), "targets に src/stats/exclusion.py の出力")

    def test_ledger_head_checked(self):
        self.seal()
        o = self.add_order1(T0 + H, ledger_head={"seq": 1, "sha256": "0" * 64})
        self.verify_fails(("stats-order",), "seq %d の stats-order1 の中身の ledger_head" % o)

    def test_not_a_cut(self):
        self.assertNotIn(ledger.ORDER1_KIND, ledger.ADOPTED_KINDS)
        self.assertNotIn(ledger.ORDER1B_KIND, ledger.ADOPTED_KINDS)
        self.seal()
        self.add_order1(T0 + H)
        out = self.verify_ok("adopted")
        self.assertIn("stats-order1・stats-order1b は区切りに使わない", out)


# ---------------------------------------------------------------- 5. T-031 の監査の軽1


class TestTrialDaysMatchCollector(unittest.TestCase):
    def test_same_as_collector(self):
        """ledger.TRIAL_DAYS が、収集係の src/collector/gkg.py の TRIAL_DAYS と同じ（読むだけ）。"""
        with open(os.path.join(tl.PROJECT, "src", "collector", "gkg.py"), encoding="utf-8") as f:
            m = re.search(r"^TRIAL_DAYS = (\(.*\))$", f.read(), re.M)
        self.assertIsNotNone(m)
        self.assertEqual(ledger.TRIAL_DAYS, tuple(json.loads("[" + m.group(1)[1:-1] + "]")))


class TestDocT037(unittest.TestCase):
    def setUp(self):
        with open(DOC, encoding="utf-8") as f:
            self.text = f.read()

    def test_statements(self):
        for phrase in ("## 13. 統計係の順番1・順番1b の封印（stats-order1・stats-order1b。T-037）",
                       "二つの kind にした理由", "収集係への申し送り", "`seal_stats.seal_order1`",
                       "下の表の10だけ", "threshold-access の後の取得の続き"):
            self.assertIn(phrase, self.text)
        for k in ledger.ORDER1_DOC_KEYS + ledger.ORDER1B_DOC_KEYS:
            self.assertIn("`%s`" % k, self.text)


if __name__ == "__main__":
    unittest.main()
