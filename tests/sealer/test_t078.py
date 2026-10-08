"""T-078 のテスト：順番2の試みを書く入口（src/sealer/seal_order2.py）と、それを照らす仕組み（ledger.check_order2_doc、
ledger.check_order2_plan の runs・inputs、verify.check_order2_git、verify の --day-files の流し直し）、stats-order2 の
許可リスト、T-077 の監査の残り（M3・M6）。

実行（プロジェクトのルートで）:
    PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest discover -s tests/sealer -v

書くのは、仮のプロジェクト（test_t031.GkgCase。合成のマニフェストと、合成の日の集計を一時の置き場所に置く）と、本物の
固定したコミット（fixed_records.PINNED_COMMIT と、その上で R の gkg-run-result を封印したもの）の clone の中だけ。ots・
drand は偽物。本物の sealed/・data/ には書かない。順番2を本物の記録で実行しない。ネットワークと LACIE SHARE には触れない。
統計係の src/stats/counting.py は、順番1b（seq 6）が縛る版を固定したコミット（fixed_records.RESULT_COMMIT）から git で
取り出し、仮のプロジェクトの履歴に置くか、同じプロセスで読み込んで比べるだけ（書き換えない）。
"""

import builtins
import datetime
import gzip
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import types
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import fixed_records  # noqa: E402
import test_ledger as tl  # noqa: E402
import test_t031 as t31  # noqa: E402
import test_t073 as t73  # noqa: E402
import test_writers as tw  # noqa: E402
from test_ledger import T0, H  # noqa: E402

ledger = tl.ledger
verify = tl.verify
import order2_gate  # noqa: E402
import seal_gkg_result  # noqa: E402
import seal_order2  # noqa: E402
import seal_records  # noqa: E402

DOC = os.path.join(tl.PROJECT, "docs", "verify", "periods-seal.md")
O2 = ledger.ORDER2_KIND
COUNTING_REL = ledger.COUNTING_SCRIPT
TRIAL = ledger.GKG_MANIFESTS["trial"]

# 順番1b（seq 6）が縛る版の counting.py（sha256 6f25985b…）。固定したコミットから取り出す（作業ツリーは読まない）
SEALED_COUNTING = fixed_records.show(COUNTING_REL, fixed_records.RESULT_COMMIT)
SEALED_SHA = ledger.sha256_hex(SEALED_COUNTING)


def sealed_counting():
    """封印した版の counting.py を、同じプロセスのモジュールとして読み込む（比べるためだけ）。"""
    mod = types.ModuleType("counting_sealed_for_t078")
    exec(compile(SEALED_COUNTING, "counting_sealed_for_t078.py", "exec"), mod.__dict__)
    return mod


COUNTING = sealed_counting()


def no_day_file(mode, name):
    raise COUNTING.CountingError("日の集計を読めない（テストでは置かない）")


def day_gz(day, mode="trial"):
    """合成の日の集計（形式の版3。parse_day に通り、C7 が使える）。gzip の時刻は 0 にして、バイト列を決まったものにする。"""
    lines = ["#\tgkg-day\t3\t%s\t%s" % (day, mode), "V\t0\tZZ_A", "V\t1\tZZ_B", "D\t1\t10", "D\t2T\t3",
             "T\t1\t0\t5\t4\t6\t7", "T\t1\t1\t2\t3\t3\t4", "T\t2T\t0\t1\t1\t1\t1",
             "S\tdocs_without_v1_theme\t2", "S\tdocs_without_v2_theme\t1", "S\tdocs_without_any_theme\t1"]
    return gzip.compress(("\n".join(lines) + "\n").encode("ascii"), mtime=0)


def rows_of(body):
    return [json.loads(x) for x in body.split(b"\n") if x.strip()]


# ---------------------------------------------------------------- 仮のプロジェクト（合成のマニフェストと日の集計）

class Synth(t31.GkgCase):
    """periods・候補・手順3・順番1・順番1b・method-access・試しの run（3日の day の行と run-complete）・R の gkg-run-result
    まで進めた仮のプロジェクト。順番1b の記録は、counting.py の sha256 を one_b_sha（既定は封印した版）にし、候補と基準の案の
    識別子を封印した版と同じにする。counting.py の封印した版は、履歴に置く（put_counting が False なら置かない）。"""

    one_b_sha = SEALED_SHA
    put_counting = True

    def add_order1b(self, now, **over):
        over.setdefault("files", [{"path": p, "sha256": self.one_b_sha if p == COUNTING_REL else "f" * 64}
                                  for p in ledger.ORDER1B_REQUIRED_FILES])
        cnt = tl.order_doc_for(b"", 1, ledger.ORDER1B_KIND)["counting"]
        over.setdefault("counting", dict(cnt, candidate_ids=list(COUNTING.CANDIDATE_IDS),
                                         criteria_ids=list(COUNTING.CRITERIA_IDS)))
        return super().add_order1b(now, **over)

    def setUp(self):
        super().setUp()
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        self.tmp = td.name
        self.store = os.path.join(self.tmp, "store")
        os.makedirs(self.store)
        self.nb = 0
        self.now = T0 + 10 * H
        if self.put_counting:
            path = os.path.join(self.root, COUNTING_REL)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "wb") as f:
                f.write(SEALED_COUNTING)
            self.commit("封印した版の counting.py（テストの仮のプロジェクト）")
            self.counting_commit = self.head()
        self.ready()
        self.run_trial()

    def head(self):
        return self.git("rev-parse", "HEAD").decode().strip()

    def manifest(self):
        with open(os.path.join(self.root, TRIAL), "rb") as f:
            return f.read()

    def run_trial(self):
        rec, _rel, _o = self.start_run(T0 + 4 * H)
        start = rows_of(self.manifest())[0]
        self.rid = start["run_id"]
        base = {k: start[k] for k in ledger.GKG_ROW_BASE}
        rows = []
        for d in COUNTING.TRIAL_DAYS:
            data = day_gz(d)
            name = COUNTING.day_file_name("trial", self.rid, d)
            with open(os.path.join(self.store, name), "wb") as f:
                f.write(data)
            rows.append(dict(base, kind="day", run_id=self.rid, day=d, file_name=name, sha256=ledger.sha256_hex(data),
                             files_listed=0, files_ok=0, files_failed=0, failed_files=[]))
        rows.append(dict(base, kind="run-complete", run_id=self.rid, days=3, files_ok=0, files_failed=0,
                         fetch_log_sha256="a" * 64, fetch_log_file="gkg-trial-%s-fetch-log.jsonl" % self.rid))
        with open(os.path.join(self.root, TRIAL), "a", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, sort_keys=True) + "\n")
        self.commit("試しの run（合成。3日と run-complete）")
        self.result_rec, _r, _o = seal_gkg_result.seal(self.root, "trial", self.rid, T0 + 5 * H, "ots", runner=tw.FakeOts())
        self.commit("R の gkg-run-result")

    def bundle_path(self):
        self.nb += 1
        return os.path.join(self.tmp, "order2-%d.bundle" % self.nb)

    def tick(self):
        self.now += H
        return self.now

    def write(self, stores=None):
        stores = stores if stores is not None else {"trial": self.store, "official": None}
        with mock.patch.object(ledger, "PROJECT_ROOT", self.root):
            return seal_order2.seal(stores, self.bundle_path(), self.tick(), "ots", runner=tw.FakeOts())

    def build(self, stores=None):
        """書かずに中身だけを作る（作り物の記録の元）。"""
        stores = stores if stores is not None else {"trial": self.store, "official": None}
        data = self.ledger_bytes()
        with mock.patch.object(ledger, "PROJECT_ROOT", self.root):
            return seal_order2.build_doc(self.root, data, ledger.verify_chain(data), stores, self.bundle_path())

    def raw_write(self, doc):
        """書く仕組みの照合（check_new）を飛ばして足す（作り物の記録）。"""
        with mock.patch.object(seal_records, "check_new", lambda *a, **k: None):
            return seal_records.write_doc_record(self.root, O2, doc, self.ledger_bytes(), "作り物（テスト）", self.tick(),
                                                 "ots", runner=tw.FakeOts())

    def writer_refuses(self, doc, text):
        before = self.ledger_bytes()
        with self.assertRaisesRegex(ledger.LedgerError, text):
            seal_records.write_doc_record(self.root, O2, doc, before, "作り物（テスト）", self.tick(), "ots",
                                          runner=tw.FakeOts())
        self.assertEqual(self.ledger_bytes(), before)

    def verify(self, *args):
        return tl.run_verify_inproc(self.root, *args)

    def verify_zero(self, *args):
        code, out, err = self.verify(*args)
        self.assertEqual(code, 0, err)
        return out

    def verify_stops(self, text, *args):
        code, _out, err = self.verify(*(args or ("stats-order",)))
        self.assertEqual(code, 1)
        self.assertRegex(err, text)

    def sealed_decide(self):
        """封印した版の decide() を同じプロセスで、置き場所の3日のファイルに当てはめた出力。"""
        def read(mode, name):
            with open(os.path.join(self.store, name), "rb") as f:
                return f.read()
        return COUNTING.decide(self.manifest(), b"", read)

    def side_branch_violation(self):
        """最初の commit（順番1b の記録より前）から枝を作り、試しの run のマニフェストの先頭の1行（HEAD の版の先頭と同じ。
        関門の git の確かめには通る）だけを置いた commit を足す。F の集合に、親に順番1b の行が無い commit が入る。"""
        branch = self.git("symbolic-ref", "--short", "HEAD").decode().strip()
        first = self.git("rev-list", "--max-parents=0", "HEAD").decode().split()[0]
        line = self.manifest().split(b"\n")[0] + b"\n"
        self.git("checkout", "-q", "-b", "side", first)
        with open(os.path.join(self.root, TRIAL), "wb") as f:
            f.write(line)
        self.commit("枝：マニフェストの先頭の行だけ（テスト）")
        bad = self.head()
        self.git("checkout", "-q", branch)
        return bad


# ---------------------------------------------------------------- 1. 決まった（decided）

class TestDecided(Synth):
    def test_write_commit_verify(self):
        rec, rel, _o, doc = self.write()
        self.assertEqual(rec["kind"], O2)
        self.assertEqual((doc["status"], doc["stop_kind"]), ("decided", None))
        self.assertEqual(doc["input_run"], {"mode": "trial", "run_id": self.rid})
        self.assertEqual(doc["code"], {"path": COUNTING_REL, "sha256": SEALED_SHA, "found": True,
                                       "commit": self.counting_commit})
        self.assertTrue(doc["timing_check"]["ok"])
        self.assertTrue(doc["timing_check"]["f_set"])
        self.assertEqual(doc["manifest_sha256"], {"trial": ledger.sha256_hex(self.manifest()), "official": None})
        self.assertEqual(doc["ref_1b_seq"], [r for r in self.records() if r["kind"] == ledger.ORDER1B_KIND][-1]["seq"])
        # 書いた decide() の出力は、封印した版の decide() を同じ3日に当てはめた出力と同じ
        self.assertEqual(doc["counting_output"], self.sealed_decide())
        self.assertEqual(doc["counting_output"]["official_candidate"], "C7")
        self.assertEqual([x["sha256"] for x in doc["counting_output"]["inputs"]],
                         [r["sha256"] for r in rows_of(self.manifest()) if r["kind"] == "day"])
        with open(os.path.join(self.root, rel), "rb") as f:
            self.assertEqual(json.loads(f.read()), doc)
        self.commit("順番2（決まった）")
        out = self.verify_zero("all")
        self.assertIn("status decided、参照する順番1b は seq %d、時機の条件 満たす、コードの版 履歴にある" % doc["ref_1b_seq"], out)
        self.assertIn("照らさなかった：seq %d の順番2の decide() の流し直し" % rec["seq"], out)
        out = self.verify_zero("stats-order", "--day-files", self.store)
        self.assertIn("流し直した出力は、記録の counting_output と同じ", out)
        # bundle は書いたパスにあり、sha256 が記録と同じ
        with open(os.path.join(self.tmp, "order2-1.bundle"), "rb") as f:
            self.assertEqual(ledger.sha256_hex(f.read()), doc["bundle"]["sha256"])

    def test_day_files_opened_only_by_decide(self):
        """この入口のプロセスは、置き場所の日の集計を開かない（開くのは、別のプロセスで流す decide() だけ）。"""
        seen = []
        real_open = builtins.open
        store = os.path.realpath(self.store)

        def spy(path, *a, **k):
            p = os.path.realpath(os.fspath(path)) if isinstance(path, (str, bytes, os.PathLike)) else ""
            if isinstance(p, str) and p.startswith(store):
                seen.append(p)
            return real_open(path, *a, **k)
        with mock.patch.object(builtins, "open", spy), mock.patch.object(io, "open", spy):
            _rec, _rel, _o, doc = self.write()
        self.assertEqual(doc["status"], "decided")
        self.assertEqual(seen, [])

    def test_working_tree_counting_not_used(self):
        """HEAD（作業ツリー）の counting.py を、出力の変わる版に変えてコミットしても、書く仕組みは順番1b が縛る版を git の
        履歴から取り出して流す。"""
        changed = SEALED_COUNTING.replace(b'PROPOSED_LABEL = "counting-v1"', b'PROPOSED_LABEL = "counting-HEAD"')
        self.assertNotEqual(changed, SEALED_COUNTING)
        with open(os.path.join(self.root, COUNTING_REL), "wb") as f:
            f.write(changed)
        self.commit("HEAD の counting.py を変える（テスト）")
        _rec, _rel, _o, doc = self.write()
        self.assertEqual(doc["counting_output"]["proposed_label"], "counting-v1")
        self.assertEqual(doc["code"]["commit"], self.counting_commit)
        self.assertEqual(doc["counting_output"], self.sealed_decide())
        self.commit("順番2")
        self.verify_zero("stats-order", "--day-files", self.store)

    def test_stores_and_bundle_arguments(self):
        """試しの run の段なのに試しの置き場所が無い、置き場所がフォルダでない、bundle をプロジェクトの中や既にある
        パスに置く、は何も書かずに止まる。"""
        before = self.ledger_bytes()
        cases = (({"trial": None, "official": self.store}, None, "--trial-store"),
                 ({"trial": os.path.join(self.tmp, "none"), "official": None}, None, "フォルダでない"),
                 (None, os.path.join(self.root, "x.bundle"), "プロジェクトの中"))
        for stores, bundle, text in cases:
            with self.subTest(text=text):
                with mock.patch.object(ledger, "PROJECT_ROOT", self.root), \
                        self.assertRaisesRegex(ledger.LedgerError, re.escape(text)):
                    seal_order2.seal(stores or {"trial": self.store, "official": None}, bundle or self.bundle_path(),
                                     self.tick(), "ots", runner=tw.FakeOts())
        existing = os.path.join(self.tmp, "exists.bundle")
        with open(existing, "wb") as f:
            f.write(b"x")
        with mock.patch.object(ledger, "PROJECT_ROOT", self.root), \
                self.assertRaisesRegex(ledger.LedgerError, "既にある"):
            seal_order2.seal({"trial": self.store, "official": None}, existing, self.tick(), "ots", runner=tw.FakeOts())
        self.assertEqual(self.ledger_bytes(), before)

    def test_dirty_worktree_refused(self):
        with open(os.path.join(self.root, "untracked.txt"), "w") as f:
            f.write("x")
        before = self.ledger_bytes()
        with self.assertRaisesRegex(ledger.LedgerError, "作業ツリーがきれいでない"):
            self.write()
        self.assertEqual(self.ledger_bytes(), before)


# ---------------------------------------------------------------- 2. 待つ（pending）

class TestPending(Synth):
    """待つ：関門は R の gkg-run-result を求め、gkg-run-result は R の run-complete を求める。そのため、関門が開いたあとに
    decide() が待つことは無く、待った試みは関門で閉じて、記録に残らない（手順書14章・16章）。"""

    def test_not_complete_closes_gate_and_writes_nothing(self):
        # run-complete の無い試しの run（R）：封印した decide() は待つ。関門は閉じ、何も書かない
        rows = rows_of(self.manifest())[:1]
        trial = (json.dumps(rows[0], sort_keys=True) + "\n").encode()
        self.assertEqual(COUNTING.decide(trial, b"", no_day_file)["status"], "pending")
        self.assertEqual(ledger.order2_plan(trial, b""), {"action": "pending"})
        with open(os.path.join(self.root, TRIAL), "wb") as f:
            f.write(trial)
        self.commit("R の run-complete の前の形（テスト）")
        before = self.ledger_bytes()
        path = self.bundle_path()
        with mock.patch.object(ledger, "PROJECT_ROOT", self.root), \
                self.assertRaises(ledger.Order2GateClosed):
            seal_order2.seal({"trial": self.store, "official": None}, path, self.tick(), "ots", runner=tw.FakeOts())
        self.assertEqual(self.ledger_bytes(), before)
        self.assertFalse(os.path.exists(path))

    def test_pending_unreachable_after_result(self):
        """試しの run のマニフェストの最初の run（R）に run-complete がある形では、order2_plan（と封印した decide()）は
        待つにならない（監査の組み合わせ 231 通りで確かめる）。"""
        n = 0
        for name, trial, official in t73.fuzz_cases():
            try:
                rid = ledger.order2_trial_run(trial)
            except ledger.Order2GateClosed:
                continue
            rows = [json.loads(x) for x in trial.splitlines() if x.strip()]
            if not any(r.get("kind") == "run-complete" and r.get("run_id") == rid for r in rows):
                continue
            n += 1
            with self.subTest(name=name):
                self.assertNotEqual(ledger.order2_plan(trial, official)["action"], "pending")
                self.assertNotEqual(COUNTING.decide(trial, official, no_day_file)["status"], "pending")
        self.assertGreater(n, 50)


class TestM6PendingCloses(unittest.TestCase):
    """M6（T-077 の監査 軽-4）：require_order2_gate の、行き先が待つなら閉じる部分。本物の流れでは R の gkg-run-result が
    あれば待つにならない（TestPending）ので、R の確かめを置き換えて行き先だけを待つにして確かめる。この部分を外すと、
    関門は開いて値を返すので、このテストは落ちる。"""

    def test_pending_plan_closes_gate(self):
        fake = {"seq": 9, "kind": ledger.GKG_RESULT_KIND, "prev_hash": "0" * 64, "recorded_at": "2026-10-08T00:00:00Z",
                "targets": [], "note": ""}
        trial = t73.jl([t73.tstart(t73.R)])
        with mock.patch.object(ledger, "PROJECT_ROOT", tempfile.gettempdir()), \
                mock.patch.object(ledger, "_gate_root", lambda: tempfile.gettempdir()), \
                mock.patch.object(ledger, "require_gkg_run_result", lambda mode, rid: fake), \
                mock.patch.object(ledger, "read_target_json", lambda root, rec, role: {}), \
                mock.patch.object(ledger, "check_trial_manifest_sealed", lambda body, doc: None), \
                mock.patch.object(ledger, "order2_plan", lambda t, o: {"action": "pending"}):
            with self.assertRaisesRegex(ledger.Order2GateClosed, "待つ"):
                ledger.require_order2_gate(trial, b"")
            # 行き先が段なら開く（置き換えが効いていることの確かめ）
            with mock.patch.object(ledger, "order2_plan", lambda t, o: {"action": "stage", "mode": "trial",
                                                                         "run_id": t73.R}):
                got = ledger.require_order2_gate(trial, b"")
        self.assertEqual(got["input_run"], {"mode": "trial", "run_id": t73.R})


# ---------------------------------------------------------------- 3. (a) 時機の条件

class TestStopA(Synth):
    def test_side_branch(self):
        bad = self.side_branch_violation()
        rec, _rel, _o, doc = self.write()
        self.assertEqual((doc["status"], doc["stop_kind"]), ("stopped", "a"))
        self.assertNotIn("counting_output", doc)
        tc = doc["timing_check"]
        self.assertFalse(tc["ok"])
        self.assertIn(bad, [c["commit"] for c in tc["f_set"]])
        self.assertIn("refs/heads/side", [r["ref"] for r in tc["refs"]])
        self.assertIn(bad[:12], tc["reason"])
        self.commit("順番2（(a)）")
        out = self.verify_zero("all")
        self.assertIn("stop_kind a", out)
        self.assertIn("時機の条件 満たさない", out)

    def test_graft_file(self):
        common = self.git("rev-parse", "--path-format=absolute", "--git-common-dir").decode().strip()
        os.makedirs(os.path.join(common, "info"), exist_ok=True)
        with open(os.path.join(common, "info", "grafts"), "w") as f:
            f.write("")
        _rec, _rel, _o, doc = self.write()
        self.assertEqual(doc["stop_kind"], "a")
        self.assertEqual(doc["timing_guards"], {"graft_file": True, "shallow": False})
        self.assertEqual(doc["timing_check"]["f_set"], [])
        self.commit("順番2（(a)、graft）")
        self.verify_zero("all")

    def test_replace_ref(self):
        ba = subprocess.run(["git", "-C", self.root, "hash-object", "-w", "--stdin"], input=b"a\n", check=True,
                            capture_output=True).stdout.decode().strip()
        bb = subprocess.run(["git", "-C", self.root, "hash-object", "-w", "--stdin"], input=b"b\n", check=True,
                            capture_output=True).stdout.decode().strip()
        self.git("replace", ba, bb)
        _rec, _rel, _o, doc = self.write()
        self.assertEqual(doc["stop_kind"], "a")
        self.assertIn("refs/replace/" + ba, [r["ref"] for r in doc["timing_check"]["refs"]])
        self.assertIn("refs/replace/", doc["timing_check"]["reason"])
        self.commit("順番2（(a)、replace）")
        self.verify_zero("all")


# ---------------------------------------------------------------- 4. (b) decide() が止まる

class TestStopB(Synth):
    def test_missing_file(self):
        name = COUNTING.day_file_name("trial", self.rid, COUNTING.TRIAL_DAYS[1])
        os.rename(os.path.join(self.store, name), os.path.join(self.tmp, name))
        rec, _rel, _o, doc = self.write()
        self.assertEqual((doc["status"], doc["stop_kind"]), ("stopped", "b"))
        out = doc["counting_output"]
        self.assertEqual([s["step"] for s in out["steps"]], ["trial", "stop"])
        self.assertIn("../store-trial/", out["steps"][-1]["reason"])          # 手元の絶対パスを記録に入れない
        self.assertNotIn(self.tmp, json.dumps(doc, ensure_ascii=False))
        self.assertNotIn(os.path.realpath(self.tmp), json.dumps(doc, ensure_ascii=False))
        self.commit("順番2（(b)）")
        self.verify_zero("all")

    def test_changed_file(self):
        name = COUNTING.day_file_name("trial", self.rid, COUNTING.TRIAL_DAYS[0])
        with open(os.path.join(self.store, name), "wb") as f:
            f.write(day_gz(COUNTING.TRIAL_DAYS[0]) + b"x")
        _rec, _rel, _o, doc = self.write()
        self.assertEqual(doc["stop_kind"], "b")
        self.assertIn("sha256 が、マニフェストの day の行と一致しない", doc["counting_output"]["steps"][-1]["reason"])
        self.commit("順番2（(b)）")
        self.verify_zero("all")


# ---------------------------------------------------------------- 5. (c) 版が履歴に無い

class TestStopC(Synth):
    one_b_sha = "c" * 64              # 順番1b の記録が縛る counting.py の版は、どこにも無い
    put_counting = False

    def test_version_not_in_history(self):
        _rec, _rel, _o, doc = self.write()
        self.assertEqual((doc["status"], doc["stop_kind"]), ("stopped", "c"))
        self.assertEqual(doc["code"], {"path": COUNTING_REL, "sha256": "c" * 64, "found": False, "commit": None})
        self.assertNotIn("counting_output", doc)
        self.commit("順番2（(c)）")
        out = self.verify_zero("all")
        self.assertIn("コードの版 履歴に無い", out)


# ---------------------------------------------------------------- 6. 作り物の記録

class TestForgeries(Synth):
    """書く仕組みを通らずに足した作り物の記録は、verify が止める。同じ中身を書く仕組みに渡すと、何も書かない。"""

    def forged(self, doc, text, *args):
        self.writer_refuses(doc, text)
        self.raw_write(doc)
        self.commit("作り物の順番2（テスト）")
        self.verify_stops(text, *args)

    def honest(self):
        doc = self.build()
        self.assertEqual(doc["stop_kind"], None)
        return doc

    def test_stop_kind_b_on_decided(self):
        doc = dict(self.honest(), stop_kind="b", status="stopped")
        self.forged(doc, "stop_kind 'b' と counting_output の status 'decided' が合わない")

    def test_stop_kind_a_with_ok_timing(self):
        doc = self.honest()
        doc = dict({k: v for k, v in doc.items() if k != "counting_output"}, stop_kind="a", status="stopped")
        self.forged(doc, "stop_kind 'a' と timing_check.ok True が合わない")

    def test_a_content_ok_false(self):
        """(a) の内容を偽る：時機の条件を満たすのに、満たさないと書いて (a) にする。計算し直した ok と違うので止まる。"""
        doc = self.honest()
        doc = dict({k: v for k, v in doc.items() if k != "counting_output"}, stop_kind="a", status="stopped",
                   timing_check=dict(doc["timing_check"], ok=False, reason="偽の理由"))
        self.forged(doc, r"timing_check\.ok False が、記録した f_set と sealed/ledger\.jsonl から計算し直した")

    def test_a_content_f_set(self):
        """(a) の内容を偽る：枝の commit を f_set から外す・親を変える。計算し直した F の集合と違うので止まる。"""
        bad = self.side_branch_violation()
        doc = self.build()
        self.assertEqual(doc["stop_kind"], "a")
        tc = doc["timing_check"]
        dropped = dict(doc, timing_check=dict(tc, f_set=[c for c in tc["f_set"] if c["commit"] != bad]))
        self.forged(dropped, r"timing_check\.f_set が、記録した refs・worktree_heads から計算し直した")

    def test_a_content_parents(self):
        bad = self.side_branch_violation()
        doc = self.build()
        tc = doc["timing_check"]
        f = [dict(c, parents=[self.head()]) if c["commit"] == bad else c for c in tc["f_set"]]
        self.forged(dict(doc, timing_check=dict(tc, f_set=f)), r"timing_check\.f_set")

    def test_counting_output_runs(self):
        doc = self.honest()
        out = doc["counting_output"]
        runs = json.loads(json.dumps(out["runs"]))
        runs["trial"]["failed_files"][COUNTING.TRIAL_DAYS[0]] = ["20150302000000"]
        self.forged(dict(doc, counting_output=dict(out, runs=runs)), r"counting_output\.runs")

    def test_counting_output_official(self):
        doc = self.honest()
        self.forged(dict(doc, counting_output=dict(doc["counting_output"], official_candidate="C1")),
                    "正式な数え方 'C1'")

    def test_counting_output_results_need_day_files(self):
        """基準の結果だけを偽ると、日の集計なしでは照らせない（照らさなかった）。--day-files で流し直すと止まる。"""
        doc = self.honest()
        out = json.loads(json.dumps(doc["counting_output"]))
        b1 = out["results"]["B1"]
        b1["decided"] = "C4" if b1["decided"] != "C4" else "C2"
        doc = dict(doc, counting_output=out)
        self.raw_write(doc)
        self.commit("作り物の順番2（基準の結果だけ）")
        out_text = self.verify_zero("stats-order")
        self.assertIn("decide() の流し直し（--day-files", out_text)
        self.verify_stops("流し直した出力が、記録の counting_output と違う", "stats-order", "--day-files", self.store)

    def test_inputs(self):
        doc = self.honest()
        out = json.loads(json.dumps(doc["counting_output"]))
        out["inputs"][1]["sha256"] = "0" * 64
        self.forged(dict(doc, counting_output=out), r"counting_output\.inputs が、gkg-run-result（seq \d+）が縛る")

    def test_c_with_version_in_history(self):
        """履歴に版があるのに (c) を書く（found を False にして形の照合を通す）。git の履歴から探し直すと版があるので止まる。"""
        doc = self.honest()
        doc = dict({k: v for k, v in doc.items() if k != "counting_output"}, stop_kind="c", status="stopped",
                   code=dict(doc["code"], found=False, commit=None))
        self.forged(doc, r"\(c\)（コードの sha256 が合わない）で止まった記録なのに、.*版が\s*git の履歴")

    def test_c_with_found_true(self):
        doc = self.honest()
        doc = dict({k: v for k, v in doc.items() if k != "counting_output"}, stop_kind="c", status="stopped")
        self.forged(doc, "版が git の履歴に\\s*ある|版が履歴にあれば")

    def test_manifest_sha256(self):
        doc = self.honest()
        self.forged(dict(doc, manifest_sha256=dict(doc["manifest_sha256"], official="0" * 64)),
                    "manifest_sha256 が、head [0-9a-f]{12} の版の二つのマニフェストの sha256 と違う")

    def test_head_not_current(self):
        doc = self.honest()
        self.commit("空のコミット（HEAD を進める）")
        self.writer_refuses(doc, "今の HEAD")


# ---------------------------------------------------------------- 7. 本物の固定したコミットの clone

class TestRealClone(t73.Order2Case):
    """本物の記録（固定したコミット。seq 1〜8 と試しの run のマニフェスト）に R の gkg-run-result を封印した clone で、
    空の置き場所（日の集計を置かない）で順番2を書くと (b) になり、verify all --rev auto が 0 で通る。順番1b（seq 6）が縛る
    counting.py の版は、その記録の head（8e2c29b）の版として見つかる。"""

    def test_b_with_rev_auto_and_doc_block(self):
        self.sealed()
        self.commit("gkg-run-result")
        store = os.path.join(self.td.name, "empty-store")
        os.makedirs(store)
        with mock.patch.object(ledger, "PROJECT_ROOT", self.c):
            rec, _rel, _o, doc = seal_order2.seal({"trial": store, "official": None},
                                                  os.path.join(self.td.name, "b.bundle"), t73.NOW, "ots",
                                                  runner=tw.FakeOts())
        self.assertEqual(rec["seq"], self.res["seq"] + 1)
        self.assertEqual((doc["stop_kind"], doc["ref_1b_seq"]), ("b", 6))
        self.assertEqual(doc["code"]["sha256"], SEALED_SHA)
        self.assertEqual(doc["code"]["commit"], "8e2c29b1afe7a9dc494e298b04b53dbbe115eaab")
        self.assertTrue(doc["timing_check"]["ok"])
        self.commit("順番2（(b)、テスト）")
        code, out, err = tl.run_verify_inproc(self.c, "all", "--rev", "auto")
        self.assertEqual(code, 0, err)
        self.assertIn("25 項目を head の版から計算し直して照らした", out)
        # 手順書16章の第三者の手順の塊（<!-- test:order2 -->）を、この clone で流すと 0 で終わる
        for block in order2_blocks():
            r = subprocess.run(["bash", "-e", "-o", "pipefail", "-c", block], cwd=self.c, capture_output=True,
                               env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
            self.assertEqual(r.returncode, 0, r.stderr.decode())
            self.assertIn("stats-order2 seq %d（順番2）" % rec["seq"], r.stdout.decode())
        # 作り物（(c) を書いたのに版が履歴にある）を足すと、同じ塊が止まる
        bad = dict({k: v for k, v in doc.items() if k != "counting_output"}, stop_kind="c", status="stopped",
                   code=dict(doc["code"], found=False, commit=None),
                   ledger_head=ledger.expected_ledger_head(self.ledger_bytes(), rec["seq"] + 1))
        with mock.patch.object(seal_records, "check_new", lambda *a, **k: None):
            seal_records.write_doc_record(self.c, O2, bad, self.ledger_bytes(), "作り物（テスト）",
                                          t73.NOW + datetime.timedelta(hours=1), "ots", runner=tw.FakeOts())
        self.commit("作り物（テスト）")
        for block in order2_blocks():
            r = subprocess.run(["bash", "-e", "-o", "pipefail", "-c", block], cwd=self.c, capture_output=True,
                               env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
            self.assertNotEqual(r.returncode, 0)


def order2_blocks():
    with open(DOC, encoding="utf-8") as f:
        return re.findall(r"<!-- test:order2 -->\n```sh\n(.*?)```", f.read(), re.S)


# ---------------------------------------------------------------- 8. 許可リスト、runs の決め方、M3

class TestAllowedAndRuns(unittest.TestCase):
    def test_allowed(self):
        self.assertIn(O2, ledger.ALLOWED_KINDS)
        self.assertIn(O2, seal_records.WRITTEN_KINDS)
        self.assertEqual(len(ledger.ALLOWED_KINDS), 12)

    def test_runs_record_same_as_sealed(self):
        """ledger.order2_runs_record は、封印した版の counting.runs_record と同じ（監査の組み合わせ 231 通り）。"""
        for name, trial, official in t73.fuzz_cases():
            with self.subTest(name=name):
                self.assertEqual(ledger.order2_runs_record(trial, official), COUNTING.runs_record(trial, official))

    def test_ref_1b_same_as_expected_ref_1b(self):
        """参照する順番1b の決め方（ledger.order2_ref_1b）は、封印した版の counting.expected_ref_1b と同じ。"""
        for kinds in (["a", "b", "a", "b", "b"], ["b", "a", "a"], ["a", "a"], ["b"] * 4):
            recs = [{"seq": i + 1, "kind": ledger.ORDER1B_KIND if k == "b" else "x"} for i, k in enumerate(kinds)]
            seqs = [r["seq"] for r in recs if r["kind"] == ledger.ORDER1B_KIND]
            for seq in range(1, len(recs) + 2):
                got = ledger.order2_ref_1b(recs, seq)
                self.assertEqual(None if got is None else got["seq"], COUNTING.expected_ref_1b(seq, seqs), (kinds, seq))

    def test_exit_codes_and_names(self):
        self.assertEqual(verify.ORDER2_EXIT_STATUS, {v: k for k, v in COUNTING.EXIT_CODES.items()})
        self.assertEqual(ledger.ORDER2_TIMING_KEYS, tuple(sorted(("f_set", "head", "ok", "reason", "ref_1b_seq", "refs",
                                                                  "worktree_heads"))))

    def test_timing_shape_same_as_sealed(self):
        """timing_check の形の決まりは、封印した版の counting.check_timing_check と同じものを通し、同じものを拒む。"""
        h = "1" * 40
        good = {"ok": True, "ref_1b_seq": 6, "head": h, "f_set": [{"commit": h, "parents": [h]}],
                "refs": [{"ref": "refs/heads/main", "commit": h}], "worktree_heads": [h], "reason": None}
        variants = [good, dict(good, ok=False), dict(good, ok=False, reason="r"), dict(good, reason="r"),
                    dict(good, refs=[]), dict(good, worktree_heads=[h, h]), dict(good, head="x"),
                    dict(good, f_set=[{"commit": h, "parents": []}, {"commit": h, "parents": []}]),
                    dict(good, extra=1)]
        for v in variants:
            try:
                COUNTING.check_timing_check(v)
                want = True
            except ValueError:
                want = False
            try:
                ledger.check_order2_timing_shape(v, "t")
                got = True
            except ledger.LedgerError:
                got = False
            self.assertEqual(got, want, v)


class TestM3PlanShaRow(t31.GkgCase):
    """M3（T-077 の監査 軽-4）：run-start の行の plan_sha256 を、gkg-run-start の記録の plan_sha256 と照らす部分
    （ledger.check_gkg_manifest_rows）。行の値だけを変えると止まる。この照合を外すと、このテストは落ちる。"""

    def test_row_plan_sha_must_match_record(self):
        self.ready()
        rec, _rel, _o = self.start_run(T0 + 4 * H, manifest=False, plan=(3, 5), plan_sha256="d" * 64)
        read = lambda r, role: ledger.read_target_json(self.root, r, role)  # noqa: E731
        good = json.dumps(self.manifest_row(rec), sort_keys=True).encode() + b"\n"
        ledger.check_gkg_manifest_rows(self.records(), read, "trial", good)
        bad = json.dumps(self.manifest_row(rec, plan_sha256="e" * 64), sort_keys=True).encode() + b"\n"
        with self.assertRaisesRegex(ledger.LedgerError, "plan_sha256 'e{64}' が、gkg-run-start（seq %d）の計画の"
                                    % rec["seq"]):
            ledger.check_gkg_manifest_rows(self.records(), read, "trial", bad)


# ---------------------------------------------------------------- 9. 手順書

class TestDocT078(unittest.TestCase):
    def test_statements(self):
        with open(DOC, encoding="utf-8") as f:
            text = f.read()
        for phrase in ("## 16. 順番2の封印（stats-order2。T-078）", "src/sealer/seal_order2.py", "--trial-store",
                       "--bundle-out", "24時間以内", "ref_1b_seq", "timing_check", "timing_guards", "code.found",
                       "counting_output.inputs", "--day-files", "待った試みは記録に残らない", "<!-- test:order2 -->",
                       "getattr", "git rev-parse HEAD", "load_counting", "bound_paths"):
            self.assertIn(phrase, text)
        self.assertNotIn("`stats-order2` は、まだ許可リスト（`ledger.ALLOWED_KINDS`）に入れていない", text)

    def test_bound_paths_docstring(self):
        self.assertIn("拾わない", fixed_records.bound_paths.__doc__)
        self.assertIn("漏れる", fixed_records.bound_paths.__doc__)


if __name__ == "__main__":
    unittest.main()
