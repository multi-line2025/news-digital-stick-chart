"""T-037 のテスト：統計係の順番1・順番1b の封印の kind（stats-order1・stats-order1b）と、
T-031 の監査の中2・軽1〜軽4。差し戻し1回目（中1〜中5・軽1〜軽5）を含む。

実行（プロジェクトのルートで）:
    PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest discover -s tests/sealer -v

ネットワークは使わない（drand・ots は偽物）。
  - StatsCase：git init した仮のプロジェクト（写し）に、統計係のファイルの代わり（引数なしで JSON を
    出す仮の exclusion.py・tagrules.py・counting.py、通る仮のテスト、表を持つ仮の seal-order1.md、承認の
    行を持つ仮の reviews/）を置き、ledger の決まった値（ORDER1_ANCESTORS・ORDER1_TARGET_NAMES・
    ORDER1_APPROVALS・OWNER_CHOICE・OWNER_DECISION）を、テストの中だけ仮の commit に差し替える。
    verify は、差し替えが効くように同じプロセスで動かす（run_verify_inproc）。
  - TestRealClone：本物のリポジトリを clone し、その HEAD で seal_order1 と seal_order1b（今の
    counting.md・counting.py）が通ること（決まった値は差し替えない。写しの上に書く）。
本物の sealed/ には書かない。
"""

import datetime
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
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
import seal_acquisition  # noqa: E402,F401
import seal_gkg_run  # noqa: E402
import seal_method  # noqa: E402
import seal_stats  # noqa: E402

DOC = os.path.join(tl.PROJECT, "docs", "verify", "periods-seal.md")
ROUND = 30_000_000
FILELIST = ledger.FILELIST_CODE_PATH
GKG_CODE = "src/collector/acquire_gkg.py"

EXCLUSION_PY = '''import json
STATUS = "decided"
print(json.dumps({"optional_choice_status": STATUS,
                  "owner_choice_source": %r}, sort_keys=True))
''' % seal_stats.OWNER_CHOICE_SOURCE
TAGRULES_PY = '''import json
print(json.dumps({"exclusion": {"optional_choice_status": "decided"}, "v": %d}, sort_keys=True))
'''
COUNTING_PY = '''import json
STATUS = "decided"
print(json.dumps({"candidates": [{"id": "C1"}, {"id": "C7"}], "criteria_ids": ["B1", "B2"],
                  "official_candidate": "C7", "official_status": STATUS,
                  "owner_decision": {"source_commit": %r, "source_path": "reviews/T-028.md",
                                     "source_line": %r, "decision_line_prefix": %r}}, sort_keys=True))
'''
OK_TEST = '''import unittest
class T(unittest.TestCase):
    def test_ok(self):
        self.assertTrue(True)
'''
T022 = ("# T-022\n\n> Kはいま封印していいよ\n\n> 2.数え方の候補を先に封印し、最後に全候補のタグの一覧を"
        "並べて公開する案でよいか\n> それでいいです。\n")
T024 = "# T-024\n\n> いいよ、正式に扱う基準は一つに絞ろう。\n"
T020 = ("# T-020\n\n## 2026-10-08 オーナーの発言（原文のまま記録）\n> 病名は案B\n"
        "> 民族、宗教の集団は除外の区分に加える。\n> そのほかこのまま承認の項目は承認します\n\n## 次\n")
T028 = ("# T-028\n\n" + ledger.OWNER_DECISION[2] + "\n\n" + ledger.OWNER_DECISION[3]
        + "分子は V1 か V2 の少なくとも一方、分母は同じ数え方の全テーマの合計。\n")
T036 = ("# T-036\n\n## 2026-10-08 再提出1回目\n- 合格\n\n" + ledger.OWNER_APPROVAL_1B[2] + "\n\n"
        + ledger.OWNER_APPROVAL_1B[3] + "\n")
ORDER1B_FILES = list(ledger.ORDER1B_REQUIRED_FILES)


class StatsCase(t14.Case):
    """順番1・1b を、書く仕組み（seal_stats）で写しの上に書けるようにした仮のプロジェクト。"""

    def setUp(self):
        super().setUp()
        self.write("src/collector/acquire_filelist.py", "# 一覧の取得（仮）\n")
        self.write(GKG_CODE, "# GKG の取得（仮）\n")
        self.write("src/stats/tagrules.py", TAGRULES_PY % 1)
        for name, text in (("T-022", T022), ("T-024", T024), ("T-020", T020), ("T-028", T028),
                           ("T-036", T036)):
            self.write("reviews/%s.md" % name, text)
        self.write(".gitignore", ".venv/\n")
        os.makedirs(os.path.join(self.root, ".venv", "bin"))
        os.symlink(sys.executable, os.path.join(self.root, ".venv", "bin", "python"))
        self.commit("昔の版")
        self.hist = self.git("rev-parse", "HEAD").decode().strip()
        self.short = self.hist[:7]
        names = tuple(n.replace("1cb463a:", self.short + ":").replace("2d23cdf:", self.short + ":")
                      for n in ledger.ORDER1_TARGET_NAMES)
        od = ledger.OWNER_DECISION
        for name, val in (("ORDER1_ANCESTORS", {self.short: self.hist}),
                          ("ORDER1_TARGET_NAMES", names),
                          ("ORDER1_APPROVALS", tuple((a[0], self.hist, a[2], a[3])
                                                     for a in ledger.ORDER1_APPROVALS)),
                          ("OWNER_CHOICE", (self.hist,) + tuple(ledger.OWNER_CHOICE[1:])),
                          ("OWNER_DECISION", (self.hist,) + tuple(od[1:])),
                          ("OWNER_APPROVAL_1B", (self.hist,) + tuple(ledger.OWNER_APPROVAL_1B[1:]))):
            p = mock.patch.object(ledger, name, val)
            p.start()
            self.addCleanup(p.stop)
        self.write("src/stats/tagrules.py", TAGRULES_PY % 2)
        self.write("src/stats/exclusion.py", EXCLUSION_PY)
        self.write("src/stats/counting.py", COUNTING_PY % (self.hist, od[2], od[3]))
        for t in ("test_exclusion", "test_tagrules", "test_counting"):
            self.write("tests/stats/%s.py" % t, OK_TEST)
        self.write("docs/stats/tags-naive.md", "# tags-naive（仮）\n")
        self.write("docs/stats/counting.md", "# counting（仮）\n")
        self.write_table()
        self.commit("今の版")

    # ---- verify は同じプロセスで（ledger の差し替えが効くように）
    def verify_ok(self, *args):
        code, out, err = tl.run_verify_inproc(self.root, *args)
        self.assertEqual(code, 0, err)
        return out

    def verify_fails(self, cmds, msg):
        for c in cmds:
            code, out, err = tl.run_verify_inproc(self.root, c)
            self.assertEqual(code, 1, (c, out[-500:]))
            self.assertIn(msg, err, c)

    def write(self, rel, text):
        full = os.path.join(self.root, rel)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w", encoding="utf-8") as f:
            f.write(text)

    def out(self, script):
        return subprocess.run([sys.executable, "-B", script], cwd=self.root, capture_output=True,
                              check=True).stdout

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

    def write_table(self, wrong=None, extra=()):
        lines = ["# 順番1（仮）", "", seal_stats.TABLE_MARKER, "| 対象 | sha256 |", "|---|---|"]
        lines += ["| `%s` | `%s` |" % r for r in list(self.table_rows(wrong)) + list(extra)]
        self.write(seal_stats.TABLE_DOC, "\n".join(lines) + "\n")

    def base(self):
        """periods・candidates と、手順3（一覧の取得。acquire_filelist.py）まで。"""
        self.seal()
        s, _r, _o = self.start(T0 + H, code=FILELIST)
        self.result(T0 + 2 * H, s["seq"])
        self.commit("手順3まで")

    def order1(self, now=T0 + 3 * H, project=None):
        rec, rel, _o = seal_stats.seal_order1(project or self.root, now, "ots", runner=tw.FakeOts())
        self.commit("順番1")
        return rec, rel

    def order1b(self, now=T0 + 4 * H, files=None, approvals=None):
        rec, rel, _o = seal_stats.seal_order1b(self.root, list(ORDER1B_FILES if files is None else files),
                                               approvals or [], now, "ots", runner=tw.FakeOts())
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
    def test_order1_then_method_and_gkg(self):
        """順番1・順番1b を書き、そのあと method-access と gkg-run-start が書ける。"""
        self.base()
        o1, rel = self.order1()
        doc = self.doc_of(rel)
        self.assertEqual(sorted(doc), list(ledger.ORDER1_DOC_KEYS))
        self.assertEqual(sorted(t["name"] for t in doc["targets"]), sorted(ledger.ORDER1_TARGET_NAMES))
        self.assertEqual(doc["head"], self.git("rev-parse", "HEAD~1").decode().strip())
        self.assertEqual(doc["python"]["path"], ".venv/bin/python")
        self.assertEqual([a["item"] for a in doc["approvals"]], ["A", "B", "B (ii)"])
        self.assertEqual(doc["checks"]["optional_choice_status"], "decided")
        self.assertEqual(doc["checks"]["stats_tests"], "OK (3 tests)")
        self.assertEqual(doc["checks"]["acquisition_starts"], ["seq 3: %s" % FILELIST])
        # 中4：対象だけを置いた写しで流した結果
        self.assertEqual(doc["checks"]["targets_only_copy"],
                         {"tests": "OK (2 tests)", "files": sorted(ledger.order1_copy_files())})
        b, brel = self.order1b()
        bdoc = self.doc_of(brel)
        self.assertEqual(bdoc["counting"]["official_candidate"], "C7")
        self.assertEqual(bdoc["counting"]["candidate_ids"], ["C1", "C7"])
        self.assertEqual(bdoc["counting"]["owner_decision"]["source"], "%s:reviews/T-028.md" % self.hist)
        self.assertEqual(bdoc["order1_ref"]["seq"], o1["seq"])
        m, _r, _o = self.method(T0 + 6 * H)
        self.commit("手順4")
        self.gkg_run(T0 + 7 * H, m["seq"])
        self.commit("試しの run")
        out = self.verify_ok("all", "--rev", "auto")
        self.assertIn("stats-order1 seq %d（順番1）: HEAD %s" % (o1["seq"], doc["head"]), out)
        self.assertIn("正式な数え方 C7（decided）", out)
        self.assertIn("除外の規則の kind（stats-order1）の記録：seq %d（1 件だけ）" % o1["seq"], out)
        self.assertIn("試しの run 1 回", out)

    def test_relative_project_path(self):
        """軽4：project を相対パスで渡しても動く。"""
        self.base()
        cwd = os.getcwd()
        os.chdir(os.path.dirname(self.root))
        try:
            rec, _rel = self.order1(project=os.path.basename(self.root))
        finally:
            os.chdir(cwd)
        self.assertEqual(rec["kind"], ledger.ORDER1_KIND)


# ---------------------------------------------------------------- 2. 区分表の取得（中1）


class TestThemesByGit(StatsCase):
    def themes_row(self, seq=None, sha=None):
        o1 = ledger.first_order1(self.records())
        return json.dumps({"kind": "attempt", "exclusion_rule_seq": o1["seq"] if seq is None else seq,
                           "exclusion_rule_record_sha256":
                               sha or hashlib.sha256(ledger.canonical_line(o1)).hexdigest()}) + "\n"

    def test_honest_themes_after_order1_passes(self):
        self.base()
        self.order1()
        self.write(seal_stats.THEMES_MANIFEST, self.themes_row())
        self.commit("区分表を取得した")
        out = self.verify_ok("stats-order")
        self.assertIn("行のある commit 1 件。どれも、親の sealed/ledger.jsonl に stats-order1 の行がある", out)
        self.assertIn("作業ツリーのマニフェストの 1 行の exclusion_rule_seq と sha256 は stats-order1 の記録と一致", out)

    def test_probe_p2_order1_v2_after_themes(self):
        """監査の test_probe37.py の test_p2：区分表の取得（マニフェストにだけ残る）のあとの順番1 の 2 件目は、
        書く仕組みが止め、飛ばして足すと verify が止まる（中5・中1）。"""
        self.base()
        self.order1()
        self.write(seal_stats.THEMES_MANIFEST, self.themes_row())
        self.commit("区分表を取得した")
        self.refuses(lambda: self.order1(T0 + 5 * H), "stats-order1 の記録が既にある")
        o2 = self.add_order1(T0 + 5 * H)
        self.commit("v2")
        self.verify_fails(("stats-order", "all"), "stats-order1（順番1）の記録が 2 件ある")
        self.assertTrue(o2)

    def test_order1_only_after_themes_fails(self):
        """区分表の取得のあとに初めて順番1 を足した記録は、git の履歴で見つかる（中1）。"""
        self.base()
        self.write(seal_stats.THEMES_MANIFEST, '{"kind":"attempt"}\n')
        self.commit("区分表を先に取得した")
        self.refuses(lambda: self.order1(), "gdelt-themes.jsonl に行がある")
        self.add_order1(T0 + 3 * H)
        self.commit("あとから順番1")
        self.verify_fails(("stats-order",), "どの親の sealed/ledger.jsonl にも stats-order1 の記録の行が無い")

    def test_themes_without_order1_fails(self):
        self.base()
        self.write(seal_stats.THEMES_MANIFEST, '{"kind":"attempt"}\n')
        self.commit("区分表")
        self.verify_fails(("stats-order", "all"), "stats-order1（順番1）の記録が無い")

    def test_manifest_ref_must_match(self):
        """マニフェストの行の exclusion_rule_seq と sha256 が stats-order1 の記録と違えば止まる（中1）。"""
        self.base()
        self.order1()
        self.write(seal_stats.THEMES_MANIFEST, self.themes_row(seq=1))
        self.commit("区分表")
        self.verify_fails(("stats-order",), "1 行目の exclusion_rule_seq 1（と sha256）が、stats-order1 の記録")
        self.write(seal_stats.THEMES_MANIFEST, self.themes_row(sha="0" * 64))
        self.commit("直す")
        self.verify_fails(("stats-order",), "1 行目の exclusion_rule_seq")


# ---------------------------------------------------------------- 3. 順番1 が無ければ止まる


class TestWithoutOrder1(StatsCase):
    def test_method_and_gkg_refused_without_order1(self):
        """T-041：順番1 が無ければ、method-access の書く仕組み（drand の前）・関門・verify が止まり、
        gkg-run-start も drand の前に止まる。そのあとでは順番1 も書けない。"""
        self.base()
        self.refuses(lambda: seal_method.seal(self.root, T0 + 3 * H, "ots", drand_fetch=t17.NoCall(),
                                              runner=tw.FakeOts()),
                     "stats-order1（順番1）の記録が無い。手順4は、順番1 の封印の後")
        m = self._append_doc(ledger.METHOD_ACCESS_KIND,
                             self._drand_doc(ledger.METHOD_ACCESS_KIND, ROUND, None), T0 + 3 * H)
        self.commit("順番1 の無いまま手順4（書く仕組みを飛ばした）")
        with self.assertRaisesRegex(ledger.MethodAccessRequired,
                                    "最初の method-access の記録（seq %d）より前に、stats-order1" % m):
            self.method_gate()
        self.verify_fails(("stats-order", "all"),
                          "最初の method-access の記録（seq %d）より前に、stats-order1（順番1）の記録が無い" % m)
        self.refuses(lambda: self.gkg_run(T0 + 4 * H, m, nocall=True),
                     "除外の規則の kind（stats-order1）の記録が無い")
        self.refuses(lambda: self.order1(T0 + 4 * H), "method-access の記録がある")

    def test_gkg_refused_without_order1b(self):
        self.base()
        self.order1()
        m, _r, _o = self.method(T0 + 4 * H)
        self.commit("手順4")
        self.refuses(lambda: self.gkg_run(T0 + 5 * H, m["seq"], nocall=True),
                     "順番1b（stats-order1b）の記録が無い")


# ---------------------------------------------------------------- 4. 順番1 の書く前の照合


class TestOrder1Refusals(StatsCase):
    def test_undecided_refused(self):
        """"undecided" で止まる。"""
        self.base()
        self.write("src/stats/exclusion.py", EXCLUSION_PY.replace('"decided"', '"undecided"'))
        self.write_table()
        self.commit("undecided")
        self.refuses(lambda: self.order1(), "除外の規則の出力 の optional_choice_status が 'undecided'")

    def test_sha256_mismatch_refused(self):
        """表と、封印係が計算し直した sha256 が食い違えば止まる。"""
        self.base()
        self.write_table(wrong="src/stats/tagrules.py の出力")
        self.commit("表の値が違う")
        self.refuses(lambda: self.order1(), "対象 src/stats/tagrules.py の出力 の sha256")

    def test_table_names_must_be_the_ten(self):
        """中3：表の行が決まった 10 件とちょうど一致しなければ止まる（足しても、外しても）。"""
        self.base()
        self.write_table(extra=[("src/stats/other.py", "a" * 64)])
        self.commit("表に足した")
        self.refuses(lambda: self.order1(), "決まった 10 件（ledger.ORDER1_TARGET_NAMES）とちょうど一致しない")

    def test_dirty_worktree_refused(self):
        self.base()
        self.write("untracked.txt", "x\n")
        self.refuses(lambda: self.order1(), "作業ツリーがきれいでない")

    def test_missing_approval_line_refused(self):
        self.base()
        with mock.patch.object(ledger, "ORDER1_APPROVALS",
                               (("A", self.hist, "reviews/T-022.md", ("> 無い行",)),)):
            self.refuses(lambda: self.order1(), "承認 A：")

    def test_not_ancestor_refused(self):
        self.base()
        with mock.patch.object(ledger, "ORDER1_ANCESTORS", {self.short: self.hist, "1234567": "1" * 40}):
            self.refuses(lambda: self.order1(), "短い ID 1234567")

    def test_owner_choice_line_missing_refused(self):
        self.base()
        with mock.patch.object(ledger, "OWNER_CHOICE",
                               (self.hist, "reviews/T-020.md", "## 2026-10-08 オーナーの発言（原文のまま記録）",
                                ("> 無い行",))):
            self.refuses(lambda: self.order1(), "見出しの節に、行")

    def test_themes_manifest_history_refused(self):
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
        self.refuses(lambda: self.order1(), "stats-order1 の記録が既にある")

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

    def test_targets_only_copy_catches_outside_read(self):
        """中4：対象の外のファイルを読んで通るテストは、写しでは通らないので止まる。"""
        self.base()
        self.write("tests/stats/test_exclusion.py", OK_TEST.replace(
            "self.assertTrue(True)", "self.assertTrue(open('reviews/T-024.md').read())"))
        self.write_table()
        self.commit("対象の外を読むテスト")
        self.refuses(lambda: self.order1(), "対象だけを置いた写しのテスト が通らない")

    def test_child_env_drops_python_vars(self):
        """軽2：子のプロセスに PYTHONPATH などを渡さない。"""
        with mock.patch.dict(os.environ, {"PYTHONPATH": "/x", "PYTHONPYCACHEPREFIX": "/y",
                                          "STATS_AUDIT_LOG": "/z", "PYTHONHOME": "/w"}):
            env = seal_stats.child_env()
        for k in ("PYTHONPATH", "PYTHONPYCACHEPREFIX", "STATS_AUDIT_LOG", "PYTHONHOME"):
            self.assertNotIn(k, env)
        self.assertEqual(env["PYTHONDONTWRITEBYTECODE"], "1")

    def test_head_rechecked_before_writing(self):
        """軽3：確かめているあいだに HEAD が変わったら書かない。"""
        self.base()
        real = seal_stats.run_stats_tests

        def moving(project, python):
            out = real(project, python)
            self.write("moved.txt", "x\n")
            self.commit("途中でコミット")
            return out
        with mock.patch.object(seal_stats, "run_stats_tests", moving):
            with self.assertRaisesRegex(ledger.LedgerError, "HEAD が変わった"):
                seal_stats.seal_order1(self.root, T0 + 3 * H, "ots", runner=tw.FakeOts())


class TestOrder1bRefusals(StatsCase):
    def test_probe_p1_trivial_order1b_refused(self):
        """監査の test_probe37.py の test_p1：counting.py を入れない順番1b は書けず、飛ばして足しても
        gkg-run-start（drand の前）と verify が止まる（中2）。"""
        self.base()
        self.order1()
        self.refuses(lambda: self.order1b(files=(".gitignore",)), "必ず入れるファイル")
        b = self.add_order1b(T0 + 5 * H, files=[{"path": ".gitignore", "sha256": "a" * 64}])
        msg = "seq %d の stats-order1b の files に、必ず入れるファイル" % b
        self.refuses(lambda: self.method(T0 + 6 * H), msg)     # method-access の書く仕組みも止まる
        m = self.add_method(T0 + 6 * H, ROUND)
        self.commit("m")
        self.refuses(lambda: self.gkg_run(T0 + 7 * H, m, nocall=True), msg)
        self.verify_fails(("stats-order", "all"), "seq %d の stats-order1b の files に、必ず入れるファイル" % b)

    def test_undecided_counting_refused(self):
        self.base()
        od = ledger.OWNER_DECISION
        self.write("src/stats/counting.py",
                   (COUNTING_PY % (self.hist, od[2], od[3])).replace('"decided"', '"inconsistent"'))
        self.commit("決まっていない")
        self.refuses(lambda: self.order1b(), "正式な数え方が決まっていない")

    def test_owner_decision_lines_checked(self):
        """出どころの「決定：」の行に、決まった語句が無ければ止まる。"""
        self.base()
        self.write("reviews/T-028.md", T028.replace("同じ数え方の全テーマの合計", "別の分母"))
        self.commit("決定の行の語句を変えた")
        newc = self.git("rev-parse", "HEAD").decode().strip()
        od = (newc,) + tuple(ledger.OWNER_DECISION[1:])
        with mock.patch.object(ledger, "OWNER_DECISION", od):
            self.write("src/stats/counting.py", COUNTING_PY % (newc, od[2], od[3]))
            self.commit("出どころを合わせた")
            self.refuses(lambda: self.order1b(), "「決定：」の行に、語句")

    def approval_variant(self, text):
        """reviews/T-036.md を text にした commit を作り、OWNER_APPROVAL_1B をその commit に向ける。"""
        self.write("reviews/T-036.md", text)
        self.commit("承認の記録を変えた")
        newc = self.git("rev-parse", "HEAD").decode().strip()
        p = mock.patch.object(ledger, "OWNER_APPROVAL_1B", (newc,) + tuple(ledger.OWNER_APPROVAL_1B[1:]))
        p.start()
        self.addCleanup(p.stop)

    def test_owner_approval_line_missing_refused(self):
        """中-B：承認の行が無ければ止まる（呼ぶ側の approvals には頼らない）。"""
        self.base()
        self.approval_variant(T036.replace(ledger.OWNER_APPROVAL_1B[3] + "\n", ""))
        self.refuses(lambda: self.order1b(), "が 0 行ある（ちょうど 1 行でない）")

    def test_owner_approval_heading_differs_refused(self):
        self.base()
        self.approval_variant(T036.replace(ledger.OWNER_APPROVAL_1B[2],
                                           "## 2026-10-08 オーナーの発言（別の件）"))
        self.refuses(lambda: self.order1b(), "の前で最も近い見出しが")

    def test_owner_approval_two_lines_refused(self):
        self.base()
        self.approval_variant(T036 + ledger.OWNER_APPROVAL_1B[3] + "\n")
        self.refuses(lambda: self.order1b(), "が 2 行ある（ちょうど 1 行でない）")

    def test_owner_approval_two_headings_refused(self):
        self.base()
        self.approval_variant(ledger.OWNER_APPROVAL_1B[2] + "\n- 前の行\n\n" + T036)
        self.refuses(lambda: self.order1b(), "見出し")

    def test_owner_approval_recorded_and_required_by_verify(self):
        self.base()
        _b, rel = self.order1b()
        self.assertEqual(self.doc_of(rel)["owner_approval"], ledger.expected_owner_approval_1b())
        self.assertIn("オーナーの承認：", self.verify_ok("stats-order"))

    def test_owner_approval_bad_raw_fails_verify(self):
        self.base()
        b = self.add_order1b(T0 + 4 * H, owner_approval={"source": "x", "heading": "y", "line": "z"})
        self.verify_fails(("stats-order",), "seq %d の stats-order1b の owner_approval が、決まった照らし方" % b)

    def test_official_candidate_must_be_c7(self):
        """中-A：正式な数え方が C7 でなければ、書く仕組みも verify も止まる。"""
        self.base()
        od = ledger.OWNER_DECISION
        self.write("src/stats/counting.py",
                   (COUNTING_PY % (self.hist, od[2], od[3])).replace('"official_candidate": "C7"',
                                                                      '"official_candidate": "C1"'))
        self.commit("C1 にした")
        self.refuses(lambda: self.order1b(), "official_candidate 'C1' が、決まった正式な数え方 C7 と違う")
        cnt = dict(tl.order_doc_for(b"", 1, ledger.ORDER1B_KIND)["counting"], official_candidate="C1")
        b = self.add_order1b(T0 + 4 * H, counting=cnt)
        self.verify_fails(("stats-order",), "seq %d の stats-order1b の counting.official_candidate 'C1'" % b)

    def test_owner_decision_source_must_match(self):
        """counting.py の出力の出どころが、ledger の決まった出どころと違えば止まる。"""
        self.base()
        od = ledger.OWNER_DECISION
        self.write("src/stats/counting.py", COUNTING_PY % ("f" * 40, od[2], od[3]))
        self.commit("別の出どころ")
        self.refuses(lambda: self.order1b(), "owner_decision の出どころが、決まった出どころ")

    def test_after_method_access_refused(self):
        self.base()
        self.order1()
        self.method(T0 + 4 * H)
        self.commit("手順4")
        self.refuses(lambda: self.order1b(T0 + 5 * H), "method-access の記録がある")

    def test_file_outside_head_refused(self):
        self.base()
        self.refuses(lambda: self.order1b(files=ORDER1B_FILES + ["docs/stats/none.md"]),
                     "docs/stats/none.md が無い")

    def test_bii_approval_always_checked(self):
        self.base()
        with mock.patch.object(ledger, "ORDER1_APPROVALS", ledger.ORDER1_APPROVALS[:2] + (
                ("B (ii)", self.hist, "reviews/T-024.md", ("> 無い行",)),)):
            self.refuses(lambda: self.order1b(), "承認 B (ii)：")


# ---------------------------------------------------------------- 5. verify の中身と位置の照合（軽5）


class TestStatsOrderVerify(t14.Case):
    def test_order1_after_method_access_fails(self):
        self.seal()
        self.step3(T0 + H, order1=False)
        # T-041：書く仕組みは順番1 の無い method-access を書かないので、飛ばして足す
        self._append_doc(ledger.METHOD_ACCESS_KIND,
                         self._drand_doc(ledger.METHOD_ACCESS_KIND, ROUND, None), T0 + 3 * H)
        o = self.add_order1(T0 + 4 * H)
        self.verify_fails(("stats-order", "all"), "stats-order1 の記録（seq %d）が、最初の method-access" % o)

    def test_order1b_after_method_access_fails(self):
        self.seal()
        self.step3(T0 + H)
        self.method(T0 + 3 * H)
        o = self.add_order1b(T0 + 4 * H)
        self.verify_fails(("stats-order",), "stats-order1b の記録（seq %d）が、最初の method-access" % o)

    def bad(self, kind, msg, **over):
        self.seal()
        o = (self.add_order1 if kind == ledger.ORDER1_KIND else self.add_order1b)(T0 + H, **over)
        self.verify_fails(("stats-order",), msg % o if "%d" in msg else msg)

    def test_contents_checked(self):
        """軽5：verify は形だけでなく、決まった値（名前の 10 件、承認、出どころ、祖先、写しの結果）と照らす。"""
        cases = [
            (ledger.ORDER1_KIND, "seq %d の stats-order1 の checks のキー", dict(checks={"worktree_clean": True})),
            (ledger.ORDER1_KIND, "決まった 10 件（ledger.ORDER1_TARGET_NAMES）とちょうど一致しない",
             dict(targets=[{"name": n, "sha256": "d" * 64} for n in ledger.ORDER1_TARGET_NAMES[:9]])),
            (ledger.ORDER1_KIND, "approvals が、決まった照らし方",
             dict(approvals=ledger.expected_order1_approvals()[:2])),
            (ledger.ORDER1_KIND, "owner_choice が、決まった出どころ",
             dict(owner_choice=dict(ledger.expected_owner_choice(), lines=["> x"]))),
            (ledger.ORDER1_KIND, "ancestors が、決まった 4 つ", dict(ancestors=["a" * 40])),
            (ledger.ORDER1B_KIND, "counting の正式な数え方が決まっていない",
             dict(counting=dict(tl.order_doc_for(b"", 1, ledger.ORDER1B_KIND)["counting"],
                                official_status="inconsistent"))),
            (ledger.ORDER1B_KIND, "counting.owner_decision が、決まった出どころ",
             dict(counting=dict(tl.order_doc_for(b"", 1, ledger.ORDER1B_KIND)["counting"],
                                owner_decision={"source": "x", "source_line": "y", "decision_line": "z"}))),
            (ledger.ORDER1B_KIND, "approvals に B (ii) の照らし方が無い",
             dict(approvals=[ledger.expected_order1_approvals()[0]])),
        ]
        for kind, msg, over in cases:
            self.tearDown()
            self.setUp()
            with self.subTest(msg=msg):
                self.bad(kind, msg, **over)

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


# ---------------------------------------------------------------- 6. 本物の clone の HEAD で


class TestVerifyGitNotes(StatsCase):
    """軽1・軽2：浅い clone と、.git の無い写しの表示。"""

    def tmp_dir(self):
        td = tempfile.TemporaryDirectory()      # TMPDIR の下。テストが終わると片づく
        self.addCleanup(td.cleanup)
        return td.name

    def test_no_git_is_reported_in_all(self):
        self.base()
        self.order1()
        nogit = os.path.join(self.tmp_dir(), "p")
        shutil.copytree(self.root, nogit, ignore=shutil.ignore_patterns(".git"), symlinks=True)
        code, out, err = tl.run_verify_inproc(nogit, "all")
        self.assertEqual(code, 0, err)
        self.assertIn("照らさなかった：git の履歴が無いので", out)
        self.assertIn("ただし、次は照らさなかった（終了コード 0 は、照らした検査がすべて通ったことだけを示す）："
                      "区分表の取得と順番1 の前後", out)

    def test_shallow_clone_explains(self):
        self.base()
        self.order1()
        d = os.path.join(self.tmp_dir(), "shallow")
        subprocess.run(["git", "clone", "-q", "--depth=1", "file://" + self.root, d], check=True,
                       capture_output=True)
        code, _out, err = tl.run_verify_inproc(d, "stats-order")
        self.assertEqual(code, 1)
        self.assertIn("浅い clone である。区分表の取得との前後の照合には履歴が要る", err)


class TestRealClone(unittest.TestCase):
    """本物のリポジトリの clone の HEAD で、seal_order1 と seal_order1b（今の counting.md・counting.py）が
    通ること。決まった値は差し替えない。clone の sealed/ にだけ書く（本物には書かない）。"""

    def test_seal_order1_and_order1b_on_clone(self):
        with tempfile.TemporaryDirectory() as d:
            c = os.path.join(d, "clone")
            subprocess.run(["git", "clone", "-q", tl.PROJECT, c], check=True, capture_output=True)
            os.makedirs(os.path.join(c, ".venv", "bin"))
            os.symlink(os.path.realpath(os.path.join(tl.PROJECT, ".venv", "bin", "python"))
                       if os.path.exists(os.path.join(tl.PROJECT, ".venv", "bin", "python")) else sys.executable,
                       os.path.join(c, ".venv", "bin", "python"))
            now = datetime.datetime.now(datetime.timezone.utc)
            rec, rel, _o = seal_stats.seal_order1(c, now, "ots", runner=tw.FakeOts())
            with open(os.path.join(c, rel), encoding="utf-8") as f:
                doc = json.load(f)
            self.assertEqual(sorted(t["name"] for t in doc["targets"]), sorted(ledger.ORDER1_TARGET_NAMES))
            subprocess.run(["git", "-C", c, "add", "-A"], check=True)
            subprocess.run(["git", "-C", c] + list(tw.AUTHOR) + ["commit", "-q", "-m", "順番1"], check=True)
            rec2, rel2, _o = seal_stats.seal_order1b(c, ORDER1B_FILES, [], now, "ots", runner=tw.FakeOts())
            with open(os.path.join(c, rel2), encoding="utf-8") as f:
                doc2 = json.load(f)
            self.assertEqual(doc2["counting"]["official_candidate"], "C7")
            # 中-B：承認（a970019 の reviews/T-036.md）を照らした上で通る
            self.assertEqual(doc2["owner_approval"], ledger.expected_owner_approval_1b())
            self.assertEqual(doc2["approvals"], [ledger.expected_order1_approvals()[2]])
            self.assertEqual(doc2["counting"]["official_status"], "decided")
            self.assertEqual(doc2["order1_ref"]["seq"], rec["seq"])
            code, out, err = tl.run_verify_inproc(c, "stats-order")
            self.assertEqual(code, 0, err)


# ---------------------------------------------------------------- 7. T-031 の監査の軽1 と手順書


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
                       "下の表の10だけ", "threshold-access の後の取得の続き",
                       "区分表の取得は ledger に記録を書かない", "stats-order1 は1件だけ",
                       "待つ記録は kind ではなく status で区別する", "`ledger.ORDER1_TARGET_NAMES`",
                       "対象だけを置いた写し", "この照合の根拠と限界", "暗号的に言える",
                       "push の前に履歴を書き換えたり", "コミットした位置", "clone から辿れる commit",
                       "浅い clone では照らせない", "終了コード 0 は、照らした検査がすべて通ったことだけを示す",
                       "`ledger.OWNER_APPROVAL_1B`", "`ledger.ORDER1B_OFFICIAL_CANDIDATE`"):
            self.assertIn(phrase, self.text)
        for k in ledger.ORDER1_DOC_KEYS + ledger.ORDER1B_DOC_KEYS + ledger.COUNTING_KEYS:
            self.assertIn("`%s`" % k, self.text)
        self.assertNotIn("acquisition-start のうち `fetch.code_path` が `src/collector/themes.py`", self.text)
        self.assertNotIn("照らす行は、承認を記録したときにリードが決める）と、B (ii)", self.text)


if __name__ == "__main__":
    unittest.main()
