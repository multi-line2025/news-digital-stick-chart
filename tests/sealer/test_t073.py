"""T-073 のテスト：順番2の前の関門（使う run の gkg-run-result が鎖の中で順番2の記録より前にあること）と、
T-070 の残り（浅い clone の扱い、第三者の一覧の作り直しのコマンド、手順書）。

実行（プロジェクトのルートで）:
    PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest discover -s tests/sealer -v

本物のリポジトリの clone（test_t066.Clone）と、仮のプロジェクト（test_t070.RebuildCase）の中だけで書く。ots は偽物
（test_writers.FakeOts）。本物の sealed/・data/manifest/ には書かない。順番2は実行しない（記録の形の照合と関門だけ）。
ネットワークと LACIE SHARE には触れない。統計係の src/stats/counting.py は、decide() の段の決め方と関門の
決め方が同じことを確かめるためだけに読み込む（書かない・変えない）。
"""

import contextlib
import datetime
import hashlib
import importlib.util
import io
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
from test_t066 import Clone, NOW, git  # noqa: E402
import test_t070 as t70  # noqa: E402

ledger = tl.ledger
verify = tl.verify
sys.path.insert(0, os.path.join(tl.PROJECT, "src", "sealer"))
import order2_gate  # noqa: E402
import seal_records  # noqa: E402

DOC = os.path.join(tl.PROJECT, "docs", "verify", "periods-seal.md")
O2 = ledger.ORDER2_KIND


def load_counting():
    spec = importlib.util.spec_from_file_location("counting_for_t073",
                                                  os.path.join(tl.PROJECT, "src", "stats", "counting.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


counting = load_counting()


def jl(rows):
    return b"".join(json.dumps(r, sort_keys=True).encode() + b"\n" for r in rows)


def no_day_file(mode, name):
    raise counting.CountingError("日の集計を読めない（テストでは置かない）")


def line_sha(rec):
    return ledger.sha256_hex(ledger.canonical_line(rec))


@contextlib.contextmanager
def order2_allowed():
    """順番2の kind を、このテストの中だけ許可リストと書く仕組みに入れる（本物の定数は変えない）。"""
    with mock.patch.object(ledger, "ALLOWED_KINDS", ledger.ALLOWED_KINDS + (O2,)), \
            mock.patch.object(seal_records, "WRITTEN_KINDS", tuple(seal_records.WRITTEN_KINDS) + (O2,)):
        yield


# ---- 使う run の決め方が、counting.decide() の段の決め方と同じこと

R, S, OF = "a" * 16, "b" * 16, "c" * 16


def tstart(rid):
    return {"kind": "run-start", "run_id": rid, "mode": "trial", "trial": True, "official": False}


def ostart(trial_body, ids):
    return {"kind": "run-start", "run_id": OF, "mode": "official", "trial": False, "official": True,
            "trial_manifest_sha256": hashlib.sha256(trial_body).hexdigest() if trial_body else None,
            "trial_run_ids": ids}


def day(mode, rid, d):
    return {"kind": "day", "run_id": rid, "mode": mode, "day": d, "sha256": "d" * 64,
            "file_name": counting.day_file_name(mode, rid, d), "failed_files": []}


def comp(rid):
    return {"kind": "run-complete", "run_id": rid}


def fuzz_cases():
    """監査の a73fuzz.py と同じ組み合わせ（試しの run の9通り × 正式な run の13通り）。(名前, 試し, 正式)"""
    td = counting.TRIAL_DAYS
    tparts = {
        "none": [], "R": [tstart(R)], "Rd1": [tstart(R), day("trial", R, td[0])],
        "Rdone": [tstart(R)] + [day("trial", R, d) for d in td] + [comp(R)],
        "Rcomp_nodays": [tstart(R), comp(R)],
        "RS": [tstart(R), tstart(S)], "SRdone": [tstart(S), tstart(R)] + [day("trial", R, d) for d in td] + [comp(R)],
        "Rdone_S": [tstart(R)] + [day("trial", R, d) for d in td] + [comp(R), tstart(S)],
        "badmode": [dict(tstart(R), trial=False)],
        "badday": [tstart(R), dict(day("trial", R, td[0]), sha256="x")] + [day("trial", R, d) for d in td[1:]] + [comp(R)],
        "notjson": None,
    }
    out = []
    for tn, tr in tparts.items():
        tb = b"{not json\n" if tr is None else jl(tr)
        offs = {"none": b""}
        firsts = [json.loads(x)["run_id"] for x in tb.splitlines() if tr is not None and json.loads(x)["kind"] == "run-start"][:1]
        for ids_name, ids in (("ok", firsts), ("empty", []), ("wrong", [S])):
            for days in (0, 2, 3):
                for shaok in (True, False):
                    rows = [ostart(tb if shaok else b"x", ids)] + [day("official", OF, d) for d in td[:days]]
                    offs["%s_%d_%s" % (ids_name, days, shaok)] = jl(rows)
        offs["badofficial"] = jl([dict(ostart(tb, firsts), trial=True)])
        for on, ob in offs.items():
            out.append(("%s/%s" % (tn, on), tb, ob))
    return out


def decide_route(trial, official):
    """封印済みの counting.decide() を流し、最初に読もうとした日の集計の mode と、status を返す（読ませない）。"""
    reads = []

    def read(mode, name):
        reads.append(mode)
        raise counting.CountingError("読ませない")
    out = counting.decide(trial, official, read)
    return out, (reads[0] if reads else None)


class TestPlanSameAsDecide(unittest.TestCase):
    """関門の開け閉め（ledger.order2_plan）が、decide() の行き先と同じこと（T-073 差し戻し1回目 軽-2）。"""

    def check_case(self, name, trial, official):
        out, read_mode = decide_route(trial, official)
        plan = ledger.order2_plan(trial, official)
        if out["status"] == "pending":
            self.assertEqual(plan, {"action": "pending"}, name)
        elif read_mode is None:
            self.assertEqual(out["status"], "stopped", name)
            self.assertEqual(plan["action"], "stop", name)
        else:
            self.assertEqual(plan["action"], "read", name)
            self.assertEqual(plan["mode"], read_mode, name)
            self.assertEqual(out["runs"][plan["mode"]]["run_id"], plan["run_id"], name)
        return plan

    def test_all_cases(self):
        cases = fuzz_cases()
        self.assertGreater(len(cases), 150)
        kinds = set()
        for name, trial, official in cases:
            with self.subTest(name=name):
                kinds.add(self.check_case(name, trial, official)["action"])
        self.assertEqual(kinds, {"pending", "stop", "read"})

    def test_audit_forms(self):
        """監査が見つけた2つの形。(i) 試しの run の最初の run-start の形が違う：decide() は日の集計を読む前に止まり、
        関門は run に結び付けずに開く。(ii) 正式な run の3日の day の行がまだ無い：decide() は待ち、関門は閉じる。"""
        bad = jl([dict(tstart(R), trial=False)])
        plan = self.check_case("(i)", bad, b"")
        self.assertEqual(plan["action"], "stop")
        self.assertIsNone(ledger.order2_input_run(bad, b""))
        t_open = jl([tstart(R)])
        for n in (0, 2):
            official = jl([ostart(t_open, [R])] + [day("official", OF, d) for d in counting.TRIAL_DAYS[:n]])
            self.assertEqual(self.check_case("(ii)", t_open, official), {"action": "pending"})
            with self.assertRaises(ledger.Order2GateClosed):
                ledger.order2_input_run(t_open, official)

    def test_constants(self):
        self.assertEqual(ledger.ORDER2_STATUSES, counting.ORDER2_STATUSES)
        self.assertEqual(ledger.ORDER2_STOP_KINDS, counting.ORDER2_STOP_KINDS)
        self.assertEqual(ledger.ORDER2_TRIAL_DAYS, counting.TRIAL_DAYS)


# ---- 鎖の照合（check_stats_order → check_order2_run）

class Order2Case(Clone):
    def output(self):
        """本物の試しの run のマニフェストに decide() を当てはめた出力（日の集計は置かないので (b) で止まる）。"""
        return counting.decide(self.body, b"", no_day_file)

    def doc(self, res, mode="trial", rid=None, output=None, ref_sha=None, stop_kind="b"):
        rid = rid or self.rid
        d = {"kind": O2, "stop_kind": stop_kind, "input_run": {"mode": mode, "run_id": rid},
             "gkg_run_result": {"seq": res["seq"], "record_sha256": ref_sha or line_sha(res)}}
        if stop_kind not in ("a", "c"):
            d["counting_output"] = output if output is not None else self.output()
        return d

    def ledger_bytes(self):
        with open(os.path.join(self.c, "sealed", "ledger.jsonl"), "rb") as f:
            return f.read()

    def check(self, records, o2, doc, extra=None):
        extra = dict(extra or {})
        extra[o2["seq"]] = doc

        def read(r, role):
            return extra[r["seq"]] if r["seq"] in extra else self.read(r, role)
        return ledger.check_stats_order(records + [o2] if o2 not in records else records, read)


class TestChainUnit(Order2Case):
    def setUp(self):
        super().setUp()
        self.res, _rel, _ots = self.seal_result()
        self.recs = self.records()
        self.o2 = {"seq": self.res["seq"] + 1, "kind": O2}

    def test_output_is_real_stop(self):
        out = self.output()
        self.assertEqual(out["status"], "stopped")
        self.assertIn({"step": "trial", "run_id": self.rid}, out["steps"])

    def test_honest_passes(self):
        got = self.check(self.recs, self.o2, self.doc(self.res))
        self.assertEqual(got["order2"], [self.o2])
        decided = dict(self.output(), status="decided", input_mode="trial", input_run_id=self.rid)
        self.check(self.recs, self.o2, self.doc(self.res, output=decided, stop_kind=None))

    def test_result_after_order2_stops(self):
        """順序の照合：gkg-run-result が順番2の記録より後にあれば止まる（中身が正しくても）。"""
        before = [r for r in self.recs if r["seq"] < self.res["seq"]]
        o2 = {"seq": self.res["seq"], "kind": O2}
        late = dict(self.res, seq=self.res["seq"] + 1)
        doc = self.doc(late)
        with self.assertRaisesRegex(ledger.LedgerError, "鎖の中でこの記録より前に無い"):
            self.check(before + [o2, late], o2, doc)

    def test_no_result_stops(self):
        before = [r for r in self.recs if r["seq"] < self.res["seq"]]
        o2 = {"seq": self.res["seq"], "kind": O2}
        start = [r for r in before if r["kind"] == ledger.GKG_RUN_KIND][0]
        with self.assertRaisesRegex(ledger.LedgerError, "鎖の中でこの記録より前に無い"):
            self.check(before, o2, self.doc(start))

    def test_result_of_other_run_stops(self):
        """G4：別の run の正しい gkg-run-result を指すと、gkg-run-result の mode・run_id と input_run の照合だけが
        止める（input_run と counting_output は本物の run R で食い違わない）。"""
        rdoc = self.read(self.res, ledger.GKG_RESULT_KIND)
        sdoc = self.read(self.recs[rdoc["gkg_run_seq"] - 1], ledger.GKG_RUN_KIND)
        n = self.res["seq"]
        fstart = {"seq": n + 1, "kind": ledger.GKG_RUN_KIND, "targets": [], "note": "別の run（テスト）"}
        fres = {"seq": n + 2, "kind": ledger.GKG_RESULT_KIND, "targets": [], "note": "別の run の結果（テスト）"}
        extra = {n + 1: dict(sdoc, run_id="f" * 16),
                 n + 2: dict(rdoc, run_id="f" * 16, gkg_run_seq=n + 1, gkg_run_record_sha256=line_sha(fstart))}
        o2 = {"seq": n + 3, "kind": O2}
        doc = self.doc(fres)
        with self.assertRaisesRegex(ledger.LedgerError, "の記録で、input_run（trial・%s）と違う" % self.rid):
            self.check(self.recs + [fstart, fres], o2, doc, extra)

    def test_stop_kinds(self):
        """(a)・(c) の記録は counting_output を持たず、stop_kind・input_run・gkg_run_result を持つ（seal-order1.md 172行）。"""
        for sk in ("a", "c"):
            with self.subTest(stop_kind=sk):
                self.check(self.recs, self.o2, self.doc(self.res, stop_kind=sk))
                null = dict(self.doc(self.res, stop_kind=sk), input_run=None, gkg_run_result=None)
                self.check(self.recs, self.o2, null)
                with self.assertRaisesRegex(ledger.LedgerError, "counting_output を持たない"):
                    self.check(self.recs, self.o2, dict(self.doc(self.res, stop_kind=sk), counting_output=self.output()))
        decided = dict(self.output(), status="decided", input_mode="trial", input_run_id=self.rid)
        bad = {
            "null なのに stopped": (self.doc(self.res, stop_kind=None), "stop_kind"),
            "b なのに decided": (self.doc(self.res, output=decided), "stop_kind"),
            "知らない stop_kind": (self.doc(self.res, stop_kind="d"), "stop_kind"),
        }
        nod = self.doc(self.res, stop_kind=None)
        del nod["counting_output"]
        bad["null なのに counting_output が無い"] = (nod, "counting_output")
        for name, (doc, text) in bad.items():
            with self.subTest(name=name):
                with self.assertRaisesRegex(ledger.LedgerError, text):
                    self.check(self.recs, self.o2, doc)

    def test_null_run(self):
        """decide() が日の集計を読む前に止まった記録だけが、input_run・gkg_run_result を null にできる。"""
        early = counting.decide(jl([dict(tstart(R), trial=False)]), b"", no_day_file)
        self.assertEqual([s["step"] for s in early["steps"]], ["stop"])
        ok = {"kind": O2, "stop_kind": "b", "input_run": None, "gkg_run_result": None, "counting_output": early}
        self.check(self.recs, self.o2, ok)
        for name, doc, text in (
                ("段に進んだ出力", dict(ok, counting_output=self.output()), "日の集計を読む段"),
                ("片方だけ null", dict(self.doc(self.res), gkg_run_result=None), "両方 null"),
                ("run があるのに段が無い", dict(self.doc(self.res), counting_output=dict(early, runs=self.output()["runs"])),
                 "段（trial・official）が無い")):
            with self.subTest(name=name):
                with self.assertRaisesRegex(ledger.LedgerError, text):
                    self.check(self.recs, self.o2, doc)

    def test_mismatches_stop(self):
        out = self.output()
        other = dict(out, runs=dict(out["runs"], trial=dict(out["runs"]["trial"], run_id="f" * 16)))
        decided_other = dict(out, status="decided", input_mode="trial", input_run_id="f" * 16)
        steps_official = dict(out, steps=[{"step": "official", "reason": "trial_no_trial"}])
        bad = {
            "別の run の gkg-run-result": (self.doc(self.res, rid="f" * 16), "input_run"),
            "mode が違う": (self.doc(self.res, mode="official"), "input_run"),
            "record_sha256 が違う": (self.doc(self.res, ref_sha="0" * 64), "record_sha256"),
            "runs の run_id が違う": (self.doc(self.res, output=other), "runs"),
            "決まった入力の run が違う": (self.doc(self.res, output=decided_other, stop_kind=None), "input_run_id"),
            "段が違う": (self.doc(self.res, output=steps_official), "steps"),
            "status が無い": (self.doc(self.res, output={"runs": {}, "steps": []}), "counting_output"),
        }
        for name, (doc, text) in bad.items():
            with self.subTest(name=name):
                with self.assertRaisesRegex(ledger.LedgerError, text):
                    self.check(self.recs, self.o2, doc)
        for k in ledger.ORDER2_RUN_KEYS:
            doc = self.doc(self.res)
            del doc[k]
            with self.subTest(missing=k):
                with self.assertRaisesRegex(ledger.LedgerError, "決まったキー"):
                    self.check(self.recs, self.o2, doc)


class TestChainWriterAndVerify(Order2Case):
    """書く仕組み（seal_records.write_doc_record の check_new → check_stats_order）と verify が同じ照合をする。
    順番2の kind は、このテストの中だけ許可する。"""

    def write(self, doc, seq_hint):
        data = ledger.read_ledger(os.path.join(self.c, "sealed", "ledger.jsonl"))
        return seal_records.write_doc_record(self.c, O2, doc, data, "順番2（テスト）", NOW + datetime.timedelta(hours=seq_hint),
                                             "ots", runner=tw.FakeOts())

    def test_writer_refuses_without_result(self):
        recs = self.records()
        start = [r for r in recs if r["kind"] == ledger.GKG_RUN_KIND][0]
        before = self.ledger_bytes()
        with order2_allowed():
            with self.assertRaisesRegex(ledger.LedgerError, "鎖の中でこの記録より前に無い"):
                self.write(self.doc(start), 1)
        self.assertEqual(self.ledger_bytes(), before)

    def test_writer_and_verify_after_result(self):
        res, _rel, _ots = self.seal_result()
        self.commit("gkg-run-result")
        with order2_allowed():
            rec, _rel, _ots = self.write(self.doc(res), 2)
            self.commit("順番2（テスト）")
            code, out, err = tl.run_verify_inproc(self.c, "stats-order")
        self.assertEqual(code, 0, err)
        self.assertIn("%s seq %d（順番2）: stop_kind b。使った run trial・run_id %s。その run の gkg-run-result（seq %d）は、"
                      "鎖の中でこの記録より前にある" % (O2, rec["seq"], self.rid, res["seq"]), out)
        # 許可リストに入れていない今の仕組みでは、順番2の kind の記録は鎖の検査で止まる
        code, _out, err = tl.run_verify_inproc(self.c, "stats-order")
        self.assertEqual(code, 1)
        self.assertIn(O2, err)

    def test_verify_stops_record_without_result(self):
        """書く仕組みを通らずに足した（照合を飛ばした）順番2の記録も、verify が止める。"""
        recs = self.records()
        start = [r for r in recs if r["kind"] == ledger.GKG_RUN_KIND][0]
        with order2_allowed():
            with mock.patch.object(seal_records, "check_new", lambda *a, **k: None):
                self.write(self.doc(start), 1)
            code, _out, err = tl.run_verify_inproc(self.c, "stats-order")
        self.assertEqual(code, 1)
        self.assertIn("鎖の中でこの記録より前に無い", err)


# ---- 関門（order2_gate.py）

class TestGate(Order2Case):
    def run_main(self):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = order2_gate.main([])
        return code, out.getvalue(), err.getvalue()

    def test_gate(self):
        with mock.patch.object(ledger, "PROJECT_ROOT", self.c):
            # gkg-run-result の前：関門が閉じる（counting.py を動かさず、記録も作らない）
            before = self.ledger_bytes()
            with self.assertRaisesRegex(ledger.Order2GateClosed, "gkg-run-result の記録が無い"):
                order2_gate.gate()
            code, _out, err = self.run_main()
            self.assertEqual(code, 1)
            self.assertIn("順番2の記録も作らない", err)
            self.assertEqual(self.ledger_bytes(), before)
            # 封印のあと：通り、記録に入れる値を返す
            res, _rel, _ots = self.seal_result()
            self.commit("gkg-run-result")
            got = order2_gate.gate()
            self.assertEqual(got["input_run"], {"mode": "trial", "run_id": self.rid})
            self.assertEqual(got["gkg_run_result"], {"seq": res["seq"], "record_sha256": line_sha(res)})
            self.assertEqual(got["plan"], {"action": "read", "mode": "trial", "run_id": self.rid})
            code, out, _err = self.run_main()
            self.assertEqual(code, 0)
            self.assertEqual(json.loads(out), got)
            # 関門の値で作った順番2の中身は、鎖の照合に通る
            doc = {"kind": O2, "stop_kind": "b", "input_run": got["input_run"],
                   "gkg_run_result": got["gkg_run_result"], "counting_output": self.output()}
            self.check(self.records(), {"seq": res["seq"] + 1, "kind": O2}, doc)

    def gate_after_result(self):
        self.seal_result()
        self.commit("gkg-run-result")
        with mock.patch.object(ledger, "PROJECT_ROOT", self.c):
            order2_gate.gate()

    def assert_closed_but_result_ok(self, text):
        """関門は git の確かめで閉じる。require_gkg_run_result だけなら通る形（git の確かめが無ければ開いた）。"""
        with mock.patch.object(ledger, "PROJECT_ROOT", self.c):
            ledger.require_gkg_run_result("trial", self.rid)
            before = self.ledger_bytes()
            with self.assertRaisesRegex(ledger.Order2GateClosed, text):
                order2_gate.gate()
            code, _out, err = self.run_main()
            self.assertEqual(code, 1)
            self.assertEqual(self.ledger_bytes(), before)

    def test_dirty_worktree_closes(self):
        """中-1：作業ツリーのマニフェストが HEAD の版と違う（取得の途中のコミットしていない行など）と閉じる。"""
        self.gate_after_result()
        path = os.path.join(self.c, ledger.GKG_MANIFESTS["trial"])
        with open(path, "ab") as f:
            f.write(b"\n")
        self.assert_closed_but_result_ok("HEAD の版と違う")
        with open(path, "wb") as f:
            f.write(self.body)
        with mock.patch.object(ledger, "PROJECT_ROOT", self.c):
            order2_gate.gate()
        # HEAD に無い正式な run のマニフェストが作業ツリーにだけある
        off = os.path.join(self.c, ledger.GKG_MANIFESTS["official"])
        with open(off, "wb") as f:
            f.write(b"")
        self.assert_closed_but_result_ok("HEAD の版と違う")

    def test_rewritten_history_closes(self):
        """中-1：過去の版が HEAD の版の先頭と同じでない（コミットした行を書き換えて戻した）と閉じる。"""
        self.gate_after_result()
        path = os.path.join(self.c, ledger.GKG_MANIFESTS["trial"])
        with open(path, "wb") as f:
            f.write(self.body.replace(b'"kind"', b'"kind" ', 1))
        self.commit("行を書き換えた版（テスト）")
        with open(path, "wb") as f:
            f.write(self.body)
        self.commit("元に戻した版（テスト）")
        self.assert_closed_but_result_ok("先頭と合わない")

    def test_head_without_manifest(self):
        """HEAD にも作業ツリーにも無い版で、過去の版があれば閉じる（追記だけでない）。"""
        git(self.c, "mv", ledger.GKG_MANIFESTS["trial"], "data/manifest/moved-for-test.jsonl")
        self.commit("マニフェストを外した版（テスト）")
        with mock.patch.object(ledger, "PROJECT_ROOT", self.c):
            with self.assertRaisesRegex(ledger.Order2GateClosed, "先頭と合わない"):
                order2_gate.gate()

    def test_rejects_args(self):
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(order2_gate.main(["--root", "/"]), 2)


# ---- T-070 の残り：浅い clone

class TestShallowPlan(t70.RebuildCase):
    def test_shallow_clone_unchecked(self):
        """浅い clone で --filelist を渡すと、正直な記録でも版が履歴に無いことがあるので「照らさなかった：浅い clone」。
        普通の clone では作り直して照らす。"""
        self.ready()
        rec = self.run_with_plan("trial", t70.plan_of(t70.FAKE_GKG_V1, "trial"))
        self.put_code(t70.FAKE_GKG_V2)          # 記録が固定する版は HEAD に無い
        full = os.path.join(self.tmp, "full")
        shallow = os.path.join(self.tmp, "shallow")
        subprocess.run(["git", "clone", "-q", self.root, full], check=True, capture_output=True)
        subprocess.run(["git", "clone", "-q", "--depth", "1", "file://" + self.root, shallow], check=True,
                       capture_output=True)
        self.assertEqual(git(shallow, "rev-parse", "--is-shallow-repository").strip(), b"true")
        code, out, err = tl.run_verify_inproc(full, "gkg-runs", "--filelist", self.filelist)
        self.assertEqual(code, 0, err)
        self.assertIn("seq %d の run：封印済みのファイル一覧から" % rec["seq"], out)
        code, out, err = tl.run_verify_inproc(shallow, "gkg-runs", "--filelist", self.filelist)
        self.assertEqual(code, 0, err)
        self.assertIn("照らさなかった：浅い clone なので、seq %d の run の計画の作り直し はしていない" % rec["seq"], out)


# ---- T-070 の残り：第三者の一覧の作り直し（filelist-rebuild）

def master_lines():
    """GDELT の公開の一覧の形の見本（2020-12-14 以前の行、以後の行、形の合わない行）。"""
    base = "http://data.gdeltproject.org/gdeltv2/"
    rows = [("100", "1" * 32, base + "20150302000000.gkg.csv.zip"),
            ("200", "2" * 32, base + "20150302000000.export.CSV.zip"),
            ("300", "3" * 32, base + "20201214234500.mentions.CSV.zip"),
            ("400", "4" * 32, base + "20201214234501.gkg.csv.zip"),       # 2020-12-15 の日になる：捨てる
            ("500", "5" * 32, base + "20210101000000.gkg.csv.zip"),
            ("xx", "6" * 32, base + "20150303000000.gkg.csv.zip")]       # 形の合わない行
    return ("".join("%s %s %s\n" % r for r in rows) + "garbage\n").encode("ascii")


def expected_body(master):
    spec = importlib.util.spec_from_file_location("filelist_for_t073",
                                                  os.path.join(tl.PROJECT, "src", "collector", "filelist.py"))
    fl = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fl)
    kept = [x for x in master.splitlines(True) if fl._is_kept_line(x)]
    return fl.serialize_rows([r for r in (fl.parse_kept_line(x) for x in kept) if r is not None])


class TestFilelistRebuild(unittest.TestCase):
    def setUp(self):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        self.tmp = td.name
        self.master = os.path.join(self.tmp, "masterfilelist.txt")
        with open(self.master, "wb") as f:
            f.write(master_lines())
        self.c = os.path.join(self.tmp, "clone")
        subprocess.run(["git", "clone", "-q", tl.PROJECT, self.c], check=True, capture_output=True)

    def source(self):
        st = verify.State(self.c, None)
        return verify.filelist_source(st.records, st.file_json)

    def test_pinned_chain_of_real_record(self):
        """本物の acquisition-start（seq 3）が固定する版（acquire_filelist.py → PINNED_SHA256 → filelist.py）で作り直す。"""
        code_rel, code_sha, kept, res_seq = self.source()
        self.assertEqual((code_rel, res_seq), ("src/collector/acquire_filelist.py", 4))
        with tempfile.TemporaryDirectory(dir=self.tmp) as t:
            body = verify.rebuild_filelist(verify.Repo(self.c), code_rel, code_sha, self.master, t, {}, "見本")
        self.assertEqual(body, expected_body(master_lines()))
        self.assertEqual(body.decode("ascii").splitlines(),
                         ["file_time\tfile_type\tsize_bytes\tmd5", "20150302000000\texport\t200\t" + "2" * 32,
                          "20150302000000\tgkg\t100\t" + "1" * 32, "20201214234500\tmentions\t300\t" + "3" * 32])

    def test_mismatch_fails(self):
        code, _out, err = tl.run_verify_inproc(self.c, "filelist-rebuild", "--masterfilelist", self.master)
        self.assertEqual(code, 1)
        self.assertIn("kept_rows_sha256", err)
        self.assertIn("一致しない", err)

    def test_match_writes_out_once(self):
        code_rel, code_sha, _kept, res_seq = self.source()
        body = expected_body(master_lines())
        out_path = os.path.join(self.tmp, "kept.tsv")
        with mock.patch.object(verify, "filelist_source",
                               return_value=(code_rel, code_sha, ledger.sha256_hex(body), res_seq)):
            code, out, err = tl.run_verify_inproc(self.c, "filelist-rebuild", "--masterfilelist", self.master,
                                                  "--out", out_path)
            self.assertEqual(code, 0, err)
            self.assertIn("kept_rows_sha256 と同じ", out)
            with open(out_path, "rb") as f:
                self.assertEqual(f.read(), body)
            code, _out, err = tl.run_verify_inproc(self.c, "filelist-rebuild", "--masterfilelist", self.master,
                                                   "--out", out_path)
            self.assertEqual(code, 1)
            self.assertIn("上書きしない", err)

    def test_shallow_fails(self):
        shallow = os.path.join(self.tmp, "shallow")
        subprocess.run(["git", "clone", "-q", "--depth", "1", "file://" + tl.PROJECT, shallow], check=True,
                       capture_output=True)
        code, _out, err = tl.run_verify_inproc(shallow, "filelist-rebuild", "--masterfilelist", self.master)
        self.assertEqual(code, 1)
        self.assertIn("浅い clone", err)


# 固定した版と HEAD の版で結果が違う、小さな filelist.py（取得のときの関数の名前だけを持つ）
FAKE_FILELIST = b"""def _read_kept_lines(resp, clock, deadline):
    return [x for x in resp.read().splitlines() if x.strip()]


def parse_kept_line(line):
    f = line.split()
    if len(f) != 3%s:
        return None
    return (f[2].decode()[-26:-12], "gkg", f[0].decode(), f[1].decode())


def serialize_rows(rows):
    return ("file_time\\tfile_type\\tsize_bytes\\tmd5\\n" + "".join("\\t".join(r) + "\\n" for r in sorted(rows))).encode()
"""
FAKE_FILELIST_V1 = FAKE_FILELIST % b""
FAKE_FILELIST_V2 = FAKE_FILELIST % b" or f[0] == b'100'"


def fake_acquire(filelist_bytes):
    return ('FILELIST_REL = "src/collector/filelist.py"\nPINNED_SHA256 = (\n    (FILELIST_REL, "%s"),\n)\n'
            % ledger.sha256_hex(filelist_bytes)).encode()


class TestFilelistPinnedNotHead(unittest.TestCase):
    """H4：filelist-rebuild は、acquisition-start の code_sha256 が固定する版の acquire_filelist.py（と、その
    PINNED_SHA256 の filelist.py）を使い、HEAD の版は使わない（T-070 の test_pinned_version_not_head と同じ作り）。"""

    def test_pinned_version_not_head(self):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        root = os.path.join(td.name, "repo")
        os.makedirs(os.path.join(root, "src", "collector"))
        git(td.name, "init", "-q", root)

        def put(fl):
            with open(os.path.join(root, verify.FILELIST_REL), "wb") as f:
                f.write(fl)
            with open(os.path.join(root, "src", "collector", "acquire_filelist.py"), "wb") as f:
                f.write(fake_acquire(fl))
            git(root, "add", "-A")
            git(root, *(list(tl.AUTHOR) + ["commit", "-q", "-m", "取得のコード（テスト）"]))
        put(FAKE_FILELIST_V1)
        code_sha = ledger.sha256_hex(fake_acquire(FAKE_FILELIST_V1))
        put(FAKE_FILELIST_V2)                                  # HEAD は v2。固定した版（v1）は HEAD に無い
        master = os.path.join(td.name, "master.txt")
        with open(master, "wb") as f:
            f.write(master_lines())
        with tempfile.TemporaryDirectory(dir=td.name) as t:
            body = verify.rebuild_filelist(verify.Repo(root), "src/collector/acquire_filelist.py", code_sha, master, t,
                                           {}, "見本")
        self.assertIn(b"\t100\t" + b"1" * 32, body)            # v1 は size 100 の行を残す（v2 は捨てる）
        ns1, ns2 = {}, {}
        exec(FAKE_FILELIST_V1.decode(), ns1)
        exec(FAKE_FILELIST_V2.decode(), ns2)
        rows = [x for x in master_lines().splitlines() if x.strip()]
        want = ns1["serialize_rows"]([r for r in map(ns1["parse_kept_line"], rows) if r is not None])
        head = ns2["serialize_rows"]([r for r in map(ns2["parse_kept_line"], rows) if r is not None])
        self.assertNotEqual(want, head)
        self.assertEqual(body, want)


class TestDocT073(unittest.TestCase):
    def test_statements(self):
        with open(DOC, encoding="utf-8") as f:
            text = f.read()
        self.assertNotIn("http://data.gdeltproject.org/gdeltv2/masterfilelist.txt", text)
        self.assertIn("https://data.gdeltproject.org/gdeltv2/masterfilelist.txt", text)
        for phrase in ("verify.py filelist-rebuild --masterfilelist", "照らさなかった：浅い clone",
                       "第三者は永久に照らせない", "運営の手元の一覧の本体だけ",
                       "## 14. 順番2の前の関門", "src/sealer/order2_gate.py", "止まった (b) としても記録しない",
                       "counting.py を手で直接動かせば", "鎖の順序で事後に見つけられる", ledger.ORDER2_KIND,
                       "作業ツリーと HEAD が同じ", "stop_kind", "日の集計を読む前に止まる"):
            self.assertIn(phrase, text)


if __name__ == "__main__":
    unittest.main()
