"""T-073 のテスト：順番2の前の関門（使う run の gkg-run-result が鎖の中で順番2の記録より前にあること）と、
T-070 の残り（浅い clone の扱い、第三者の一覧の作り直しのコマンド、手順書）。

実行（プロジェクトのルートで）:
    PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest discover -s tests/sealer -v

本物のリポジトリの固定したコミットの版（test_t066.Clone・fixed_records.checkout。T-077）と、仮のプロジェクト（test_t070.RebuildCase）の中だけで書く。ots は偽物
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
import fixed_records  # noqa: E402
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
    """監査の a73fuzz.py を広げた組み合わせ（試しの run の11通り × 正式な run の21通り）。(名前, 試し, 正式)"""
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
        # 正式な run の day の行の形が違う（decide() は段を記録してから止まる。差し戻し2回目 3）
        offs["badofficialday"] = jl([ostart(tb, firsts), dict(day("official", OF, td[0]), sha256="x")]
                                    + [day("official", OF, d) for d in td[1:]])
        for on, ob in offs.items():
            out.append(("%s/%s" % (tn, on), tb, ob))
    return out


def decide_route(trial, official):
    """封印済みの counting.decide() を流した出力（日の集計は読ませない）。"""
    return counting.decide(trial, official, no_day_file)


class TestPlanSameAsDecide(unittest.TestCase):
    """関門の行き先（ledger.order2_plan）が、decide() の出力と、check_order2_run と同じ基準（段の記録の有無）で
    一致すること（T-073 差し戻し1回目 軽-2、差し戻し2回目 3）。"""

    def check_case(self, name, trial, official):
        out = decide_route(trial, official)
        plan = ledger.order2_plan(trial, official)
        stages = [x for x in out["steps"] if x.get("step") in ("trial", "official")]
        if out["status"] == "pending":
            self.assertEqual(plan, {"action": "pending"}, name)
        elif not stages:
            self.assertEqual(out["status"], "stopped", name)
            self.assertEqual(plan["action"], "stop", name)
        else:
            self.assertEqual(plan["action"], "stage", name)
            self.assertEqual([x["step"] for x in stages], [plan["mode"]], name)
            if plan["mode"] == "trial":
                self.assertEqual(stages[0]["run_id"], plan["run_id"], name)
            self.assertEqual(out["runs"][plan["mode"]]["run_id"], plan["run_id"], name)
        return plan

    def test_all_cases(self):
        cases = fuzz_cases()
        self.assertGreater(len(cases), 200)
        kinds = set()
        for name, trial, official in cases:
            with self.subTest(name=name):
                kinds.add(self.check_case(name, trial, official)["action"])
        self.assertEqual(kinds, {"pending", "stop", "stage"})

    def test_audit_forms(self):
        """(i) 試しの run の最初の run-start の形が違う：段に進む前に止まる。(ii) 正式な run の3日の day の行が
        まだ無い：待つ。(iii) 正式な run の day の行の形が違う：段（official）を記録してから止まるので stage。"""
        bad = jl([dict(tstart(R), trial=False)])
        self.assertEqual(self.check_case("(i)", bad, b"")["action"], "stop")
        t_open = jl([tstart(R)])
        for n in (0, 2):
            official = jl([ostart(t_open, [R])] + [day("official", OF, d) for d in counting.TRIAL_DAYS[:n]])
            self.assertEqual(self.check_case("(ii)", t_open, official), {"action": "pending"})
        official = jl([ostart(t_open, [R]), dict(day("official", OF, counting.TRIAL_DAYS[0]), sha256="x")])
        plan = self.check_case("(iii)", t_open, official)
        self.assertEqual(plan, {"action": "stage", "mode": "official", "run_id": OF})
        self.assertEqual(decide_route(t_open, official)["status"], "stopped")

    def test_constants(self):
        self.assertEqual(ledger.ORDER2_STATUSES, counting.ORDER2_STATUSES)
        self.assertEqual(ledger.ORDER2_STOP_KINDS, counting.ORDER2_STOP_KINDS)
        self.assertEqual(ledger.ORDER2_TRIAL_DAYS, counting.TRIAL_DAYS)


class TestBlankLines(unittest.TestCase):
    """差し戻し2回目 5：マニフェストに空の行を置かない（最後の改行のあとの空は行に数えない）。"""

    def test_reject(self):
        row = b'{"kind": "x"}'
        self.assertEqual(len(ledger.manifest_rows(row + b"\n" + row + b"\n", "m")), 2)
        self.assertEqual(ledger.manifest_rows(b"", "m"), [])
        for bad in (row + b"\n\n", row + b"\n\n" + row + b"\n", b"\n" + row + b"\n", row + b"\n \n"):
            with self.subTest(bad=bad):
                with self.assertRaisesRegex(ledger.LedgerError, "空の行"):
                    ledger.manifest_rows(bad, "m")


# ---- 鎖の照合（check_stats_order → check_order2_run）と、行き先の照合（check_order2_plan）

def o2_stub(seq):
    """照合の単体テストで使う順番2の記録の形（seq・kind と、書く仕組みが作る形の targets がちょうど1つ。T-090：
    ledger.check_order2_run が targets の数と形を照らすようになった）。"""
    return {"seq": seq, "kind": O2, "targets": [{"path": "sealed/%s-%s.json" % (O2, "0" * 64), "role": O2,
                                                 "sha256": "0" * 64}]}


class Order2Case(Clone):
    def output(self, official=b""):
        """本物の試しの run のマニフェストに decide() を当てはめた出力（日の集計は置かないので (b) で止まる）。"""
        return counting.decide(self.body, official, no_day_file)

    def sealed(self):
        self.res, _rel, _ots = self.seal_result()
        self.recs = self.records()
        self.o2 = o2_stub(self.res["seq"] + 1)

    def doc(self, stop_kind="b", output=None, input_run="R", gkg_ref="R", trial_ref=None):
        """順番2の中身。T-073 の4つのキーと counting_output に、T-078 のキー（ledger_head・head・status・参照する順番1b・
        時機の条件・コードの版・bundle・python）を、今の clone から計算して足す（verify.order2_timing_now・
        find_order2_code。(a) は ok を False にし、(c) は found を False にする）。"""
        ref = {"seq": self.res["seq"], "record_sha256": line_sha(self.res)}
        d = {"kind": O2, "stop_kind": stop_kind, "trial_result": trial_ref or ref,
             "input_run": {"mode": "trial", "run_id": self.rid} if input_run == "R" else input_run,
             "gkg_run_result": ref if gkg_ref == "R" else gkg_ref}
        if stop_kind not in ("a", "c"):
            d["counting_output"] = output if output is not None else self.output()
        d.update(self.t078_fields(stop_kind, d.get("counting_output")))
        return d

    def t078_fields(self, stop_kind, out):
        recs = self.records()
        seq = len(recs) + 1                                  # 書く仕組みで足すときの seq
        b = ledger.order2_ref_1b(recs, seq)
        repo = verify.Repo(self.c)
        tc, guards = verify.order2_timing_now(repo, [r for r in recs if r["seq"] < seq], b)
        d1b = self.read(b, ledger.ORDER1B_KIND)
        commit, _code = verify.find_order2_code(repo, tc["head"], d1b)
        if stop_kind == "a":
            tc = dict(tc, ok=False, reason="時機の条件を満たさない形（テスト）")
        if stop_kind == "c":
            commit = None
        status = "stopped" if stop_kind is not None else (out.get("status") if isinstance(out, dict) else None)
        ms = {m: verify._version_or_empty(repo, tc["head"], rel) for m, rel in ledger.GKG_MANIFESTS.items()}
        return {"ledger_head": ledger.expected_ledger_head(self.ledger_bytes(), seq), "head": tc["head"],
                "manifest_sha256": {m: ledger.sha256_hex(v) if v else None for m, v in ms.items()},
                "status": status, "ref_1b_seq": b["seq"], "ref_1b_record_sha256": line_sha(b),
                "timing_check": tc, "timing_guards": guards,
                "code": {"path": ledger.COUNTING_SCRIPT, "sha256": {f["path"]: f["sha256"] for f in d1b["files"]}
                         [ledger.COUNTING_SCRIPT], "found": commit is not None, "commit": commit},
                "bundle": {"sha256": "0" * 64, "published": False, "reason": "テスト"}, "python": "3"}

    def decided_output(self):
        """試しの run の段で決まった形の decide() の出力（日の集計は読まない。inputs はマニフェストの day の行から作る）。"""
        days = [r for r in (json.loads(x) for x in self.body.splitlines()) if r.get("kind") == "day"]
        return dict(self.output(), status="decided", steps=[{"step": "trial", "run_id": self.rid}],
                    input_mode="trial", input_run_id=self.rid,
                    inputs=[{"day": r["day"], "file_name": r["file_name"], "sha256": r["sha256"]} for r in days],
                    results={b: {"official": False} for b in counting.CRITERIA_IDS},
                    coverage=[{"day": d} for d in counting.TRIAL_DAYS])

    def stop_doc(self):
        """段に進む前に止まる形の中身（正式な run の trial_manifest_sha256 が合わない）。"""
        off = jl([ostart(b"x", [self.rid])])
        out = self.output(off)
        self.assertEqual([x["step"] for x in out["steps"]], ["stop"])
        return off, self.doc(output=out, input_run=None, gkg_ref=None)

    def ledger_bytes(self):
        with open(os.path.join(self.c, "sealed", "ledger.jsonl"), "rb") as f:
            return f.read()

    def reader(self, o2, doc, extra=None):
        extra = dict(extra or {})
        extra[o2["seq"]] = doc

        def read(r, role):
            return extra[r["seq"]] if r["seq"] in extra else self.read(r, role)
        return read

    def check(self, records, o2, doc, extra=None):
        return ledger.check_stats_order(records + [o2] if o2 not in records else records, self.reader(o2, doc, extra))

    def check_plan(self, doc, trial=None, official=b""):
        return ledger.check_order2_plan(self.recs + [self.o2], self.o2, doc, self.reader(self.o2, doc),
                                        self.body if trial is None else trial, official)


class TestChainUnit(Order2Case):
    def setUp(self):
        super().setUp()
        self.sealed()

    def test_output_is_real_stop(self):
        out = self.output()
        self.assertEqual(out["status"], "stopped")
        self.assertIn({"step": "trial", "run_id": self.rid}, out["steps"])

    def test_honest_passes(self):
        got = self.check(self.recs, self.o2, self.doc())
        self.assertEqual(got["order2"], [self.o2])
        self.check(self.recs, self.o2, self.doc(output=self.decided_output(), stop_kind=None))

    def test_result_after_order2_stops(self):
        """順序の照合：R の gkg-run-result が順番2の記録より後にあれば止まる（中身が正しくても）。"""
        before = [r for r in self.recs if r["seq"] < self.res["seq"]]
        o2 = o2_stub(self.res["seq"])
        late = dict(self.res, seq=self.res["seq"] + 1)
        ref = {"seq": late["seq"], "record_sha256": line_sha(late)}
        doc = self.doc(trial_ref=ref, gkg_ref=ref)
        with self.assertRaisesRegex(ledger.LedgerError, "鎖の中でこの記録より前に無い"):
            self.check(before + [o2, late], o2, doc)

    def test_no_result_stops(self):
        """R の gkg-run-result が無ければ、stop_kind が何でも止まる（(a)・(c)・段に進む前に止まる形も）。"""
        start = [r for r in self.recs if r["kind"] == ledger.GKG_RUN_KIND][0]
        ref = {"seq": start["seq"], "record_sha256": line_sha(start)}
        _off, null = self.stop_doc()
        for name, doc in (("b", self.doc(trial_ref=ref, gkg_ref=ref)), ("a", self.doc("a", trial_ref=ref, gkg_ref=ref)),
                          ("c", self.doc("c", trial_ref=ref, input_run=None, gkg_ref=None)),
                          ("null", dict(null, trial_result=ref))):
            with self.subTest(name=name):
                with self.assertRaisesRegex(ledger.LedgerError, "trial_result.*鎖の中でこの記録より前に無い"):
                    self.check(self.recs, self.o2, doc)
        with self.assertRaisesRegex(ledger.LedgerError, "決まったキー"):
            self.check(self.recs, self.o2, {k: v for k, v in null.items() if k != "trial_result"})

    def test_result_of_other_run_stops(self):
        """G4：正式な run の段の記録で、gkg_run_result が別の run の正しい gkg-run-result を指すと、gkg-run-result の
        run_id と input_run の照合だけが止める（input_run と counting_output は食い違わない）。"""
        rdoc = self.read(self.res, ledger.GKG_RESULT_KIND)
        sdoc = self.read(self.recs[rdoc["gkg_run_seq"] - 1], ledger.GKG_RUN_KIND)
        n = self.res["seq"]
        fstart = {"seq": n + 1, "kind": ledger.GKG_RUN_KIND, "targets": [], "note": "別の run（テスト）"}
        fres = {"seq": n + 2, "kind": ledger.GKG_RESULT_KIND, "targets": [], "note": "別の run の結果（テスト）"}
        extra = {n + 1: dict(sdoc, mode="official", run_id="f" * 16, trial_days=None),
                 n + 2: dict(rdoc, mode="official", run_id="f" * 16, manifest_path=ledger.GKG_MANIFESTS["official"],
                             gkg_run_seq=n + 1, gkg_run_record_sha256=line_sha(fstart))}
        o2 = o2_stub(n + 3)
        out = dict(self.output(), steps=[{"step": "official", "reason": "trial_not_complete"}, {"step": "stop"}],
                   runs={"trial": {"run_id": self.rid}, "official": {"run_id": OF}})
        doc = self.doc(output=out, input_run={"mode": "official", "run_id": OF},
                       gkg_ref={"seq": fres["seq"], "record_sha256": line_sha(fres)})
        with self.assertRaisesRegex(ledger.LedgerError, "gkg_run_result（seq %d）は mode official・run_id f{16} の記録で、"
                                                        "求める run（official・%s）と違う" % (fres["seq"], OF)):
            self.check(self.recs + [fstart, fres], o2, doc, extra)

    def test_stop_kinds(self):
        """(a)・(c) の記録は counting_output を持たず、stop_kind・trial_result・input_run・gkg_run_result を持つ。"""
        for sk in ("a", "c"):
            with self.subTest(stop_kind=sk):
                self.check(self.recs, self.o2, self.doc(sk))
                with self.assertRaisesRegex(ledger.LedgerError, "counting_output を持たない"):
                    self.check(self.recs, self.o2, dict(self.doc(sk), counting_output=self.output()))
        decided = dict(self.output(), status="decided", input_mode="trial", input_run_id=self.rid)
        nod = self.doc(stop_kind=None)
        del nod["counting_output"]
        bad = {"null なのに stopped": (self.doc(stop_kind=None), "stop_kind"),
               "b なのに decided": (self.doc(output=decided), "stop_kind"),
               "知らない stop_kind": (self.doc(stop_kind="d"), "stop_kind"),
               "null なのに counting_output が無い": (nod, "counting_output")}
        for name, (doc, text) in bad.items():
            with self.subTest(name=name):
                with self.assertRaisesRegex(ledger.LedgerError, text):
                    self.check(self.recs, self.o2, doc)

    def test_mismatches_stop(self):
        out = self.output()
        other = dict(out, runs=dict(out["runs"], trial=dict(out["runs"]["trial"], run_id="f" * 16)))
        decided_other = dict(out, status="decided", input_mode="trial", input_run_id="f" * 16)
        steps_official = dict(out, steps=[{"step": "official", "reason": "trial_no_trial"}])
        _off, null = self.stop_doc()
        bad = {
            "input_run が R でない": (self.doc(input_run={"mode": "trial", "run_id": "f" * 16}), "求める run（trial・f{16}）"),
            "record_sha256 が違う": (self.doc(gkg_ref={"seq": self.res["seq"], "record_sha256": "0" * 64}), "record_sha256"),
            "runs の run_id が違う": (self.doc(output=other), "runs.trial"),
            "決まった入力の run が違う": (self.doc(output=decided_other, stop_kind=None), "input_run_id"),
            "段が違う": (self.doc(output=steps_official), "steps"),
            "status が無い": (self.doc(output={"runs": {}, "steps": []}), "counting_output"),
            "片方だけ null": (self.doc(gkg_ref=None), "両方 null"),
            "null なのに段に進んだ出力": (dict(null, counting_output=out), "段に進んでいる"),
            "run があるのに段が無い": (self.doc(output=null["counting_output"]), "段（trial・official）が無い"),
        }
        for name, (doc, text) in bad.items():
            with self.subTest(name=name):
                with self.assertRaisesRegex(ledger.LedgerError, text):
                    self.check(self.recs, self.o2, doc)
        for k in ledger.ORDER2_RUN_KEYS:
            doc = self.doc()
            del doc[k]
            with self.subTest(missing=k):
                with self.assertRaisesRegex(ledger.LedgerError, "決まったキー"):
                    self.check(self.recs, self.o2, doc)


class TestPlanCheck(Order2Case):
    """行き先の照合（ledger.check_order2_plan）：マニフェストから R と行き先を計算し直して、記録と照らす。"""

    def setUp(self):
        super().setUp()
        self.sealed()

    def test_honest(self):
        self.assertEqual(self.check_plan(self.doc())["action"], "stage")
        for sk in ("a", "c"):
            self.check_plan(self.doc(sk))
        off, null = self.stop_doc()
        self.assertEqual(self.check_plan(null, official=off)["action"], "stop")
        self.check_plan(dict(self.doc("a"), input_run=None, gkg_run_result=None), official=off)

    def test_trial_manifest_whole(self):
        """R のマニフェストは全体が gkg-run-result の縛るバイト列と同じ（あとの行・改行を許さない）。監査の中-1 の形：
        改行を1つ足し、正式な run の trial_manifest_sha256 が合わなくなった「段に進む前に止まる」形も止まる。"""
        _off, null = self.stop_doc()
        trial = self.body + b"\n"
        official = jl([ostart(self.body, [self.rid])])
        self.assertEqual(ledger.order2_plan(trial, official)["action"], "stop")
        for doc in (null, self.doc()):
            with self.assertRaisesRegex(ledger.LedgerError, "全体"):
                self.check_plan(doc, trial=trial, official=official)

    def both_official(self):
        return jl([ostart(self.body, [self.rid])] + [day("official", OF, d) for d in counting.TRIAL_DAYS])

    def test_mismatches(self):
        off, null = self.stop_doc()
        cases = {
            "段の形なのに input_run が null": (null, None, b"", "input_run・stop_kind が合わない|段なのに"),
            "止まる形なのに input_run がある": (self.doc(), None, off, "input_run・stop_kind が合わない"),
            "R が違う": (self.doc(), jl([tstart(S)]) + self.body, b"", "マニフェストの R"),
            "R が決まらない": (self.doc(), b"", b"", "R"),
            "正式な run の段なのに試しの run": (self.doc(output=self.output(self.both_official())), None,
                                          self.both_official(), None),
            # T-078：counting_output.runs は、マニフェストから計算し直した二つの run と同じでなければならない
            "runs が正式な run のマニフェストと違う": (self.doc(), None, self.both_official(), "counting_output.runs"),
        }
        for name, (doc, trial, official, text) in cases.items():
            with self.subTest(name=name):
                if text is None:
                    # R が完了しているので、正式な run が始まっていても行き先は試しの run の段（通る）
                    self.check_plan(doc, trial=trial, official=official)
                    continue
                with self.assertRaisesRegex(ledger.LedgerError, text):
                    self.check_plan(doc, trial=trial, official=official)


class TestChainWriterAndVerify(Order2Case):
    """書く仕組み（seal_records.write_doc_record の check_new）と verify が同じ照合をする。順番2の kind は、この
    テストの中だけ許可する。"""

    def write(self, doc, hours):
        data = ledger.read_ledger(os.path.join(self.c, "sealed", "ledger.jsonl"))
        return seal_records.write_doc_record(self.c, O2, doc, data, "順番2（テスト）", NOW + datetime.timedelta(hours=hours),
                                             "ots", runner=tw.FakeOts())

    def test_writer_refuses_without_result(self):
        self.res = [r for r in self.records() if r["kind"] == ledger.GKG_RUN_KIND][0]   # R の結果ではない記録を指す
        before = self.ledger_bytes()
        with order2_allowed():
            with self.assertRaisesRegex(ledger.LedgerError, "鎖の中でこの記録より前に無い"):
                self.write(self.doc(), 1)
        self.assertEqual(self.ledger_bytes(), before)

    def test_writer_and_verify_after_result(self):
        self.sealed()
        self.commit("gkg-run-result")
        with order2_allowed():
            rec, _rel, _ots = self.write(self.doc(), 2)
            self.commit("順番2（テスト）")
            code, out, err = tl.run_verify_inproc(self.c, "stats-order")
        self.assertEqual(code, 0, err)
        self.assertIn("%s seq %d（順番2）: stop_kind b、input_run trial・%s、trial_result は seq %d"
                      % (O2, rec["seq"], self.rid, self.res["seq"]), out)
        self.assertIn("のマニフェストから計算し直した行き先（trial の段）と R は、記録と同じ", out)
        # T-078 で許可リストに入れたので、order2_allowed の外でも鎖の検査に通る
        self.assertIn(O2, ledger.ALLOWED_KINDS)
        code, _out, err = tl.run_verify_inproc(self.c, "stats-order")
        self.assertEqual(code, 0, err)

    def test_writer_refuses_wrong_plan(self):
        """形は通るが行き先が食い違う記録（試しの run の段の形なのに、段に進む前に止まったと申告する）は書かない。"""
        self.sealed()
        self.commit("gkg-run-result")
        _off, null = self.stop_doc()
        before = self.ledger_bytes()
        with order2_allowed():
            self.check(self.recs, self.o2, null)               # 形の照合だけなら通る
            with self.assertRaisesRegex(ledger.LedgerError, "計算し直した行き先"):
                self.write(null, 2)
        self.assertEqual(self.ledger_bytes(), before)

    def test_verify_recomputes_plan(self):
        """書く仕組みの照合を飛ばして足した、行き先の食い違う記録は、verify が計算し直して止める。浅い clone では
        「照らさなかった」。"""
        self.sealed()
        self.commit("gkg-run-result")
        _off, null = self.stop_doc()
        with order2_allowed():
            with mock.patch.object(seal_records, "check_new", lambda *a, **k: None):
                self.write(null, 2)
            self.commit("食い違う順番2（テスト）")
            code, _out, err = tl.run_verify_inproc(self.c, "stats-order")
            self.assertEqual(code, 1)
            self.assertIn("計算し直した行き先", err)
            shallow = os.path.join(self.td.name, "shallow")
            subprocess.run(["git", "clone", "-q", "--depth", "1", "file://" + self.c, shallow], check=True,
                           capture_output=True)
            st = verify.State(shallow, None)
            got = ledger.check_stats_order(st.records, st.file_json)
            with contextlib.redirect_stdout(io.StringIO()) as out:
                verify.check_order2_plans(st, got["order2"])
        self.assertIn("照らさなかった：浅い clone なので", out.getvalue())
        self.assertTrue(any("浅い clone" in u for u in st.unchecked))

    def test_verify_stops_record_without_result(self):
        """書く仕組みを通らずに足した、R の gkg-run-result を指さない記録も、verify が止める。"""
        self.res = [r for r in self.records() if r["kind"] == ledger.GKG_RUN_KIND][0]
        with order2_allowed():
            with mock.patch.object(seal_records, "check_new", lambda *a, **k: None):
                self.write(self.doc(), 1)
            code, _out, err = tl.run_verify_inproc(self.c, "stats-order")
        self.assertEqual(code, 1)
        self.assertIn("鎖の中でこの記録より前に無い", err)


# ---- 関門（order2_gate.py）

class TestGate(Order2Case):
    def run_main(self):
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(ledger, "PROJECT_ROOT", self.c), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = order2_gate.main([])
        return code, out.getvalue(), err.getvalue()

    def test_gate(self):
        with mock.patch.object(ledger, "PROJECT_ROOT", self.c):
            # R の gkg-run-result の前：関門が閉じる（counting.py を動かさず、記録も作らない）
            before = self.ledger_bytes()
            with self.assertRaisesRegex(ledger.Order2GateClosed, "gkg-run-result の記録が無い"):
                order2_gate.gate()
            code, _out, err = self.run_main()
            self.assertEqual(code, 1)
            self.assertIn("順番2の記録も作らない", err)
            self.assertEqual(self.ledger_bytes(), before)
            # 封印のあと：通り、記録に入れる値を返す
            self.sealed()
            self.commit("gkg-run-result")
            got = order2_gate.gate()
            ref = {"seq": self.res["seq"], "record_sha256": line_sha(self.res)}
            self.assertEqual(got, {"trial_result": ref, "input_run": {"mode": "trial", "run_id": self.rid},
                                   "gkg_run_result": ref,
                                   "plan": {"action": "stage", "mode": "trial", "run_id": self.rid}})
            code, out, _err = self.run_main()
            self.assertEqual(code, 0)
            self.assertEqual(json.loads(out), got)
            # 関門の値で作った順番2の中身は、形の照合にも行き先の照合にも通る
            doc = dict({k: got[k] for k in ("trial_result", "input_run", "gkg_run_result")},
                       kind=O2, stop_kind="b", counting_output=self.output())
            doc.update(self.t078_fields("b", doc["counting_output"]))
            self.check(self.records(), self.o2, doc)
            self.check_plan(doc)

    def test_whole_trial_manifest_required(self):
        """R のマニフェストの全体の照合：行の照合（require_gkg_run_result）が見落とす形でも、全体が縛るバイト列と
        違えば閉じる（require_gkg_run_result が通る形を作るため、ここだけ置き換える）。"""
        self.sealed()
        self.commit("gkg-run-result")
        with mock.patch.object(ledger, "PROJECT_ROOT", self.c), \
                mock.patch.object(ledger, "require_gkg_run_result", lambda mode, rid: self.res):
            ledger.require_order2_gate(self.body, b"")
            for extra in (b"\n", b'{"kind": "note"}\n'):
                with self.subTest(extra=extra):
                    with self.assertRaisesRegex(ledger.Order2GateClosed, "全体"):
                        ledger.require_order2_gate(self.body + extra, b"")

    def test_newline_after_result_closes(self):
        """監査の中-1 の形：R の封印のあとで、試しの run のマニフェストに改行を足してコミットすると閉じる。"""
        self.sealed()
        self.commit("gkg-run-result")
        with open(os.path.join(self.c, ledger.GKG_MANIFESTS["trial"]), "ab") as f:
            f.write(b"\n")
        self.commit("改行を足した（テスト）")
        with mock.patch.object(ledger, "PROJECT_ROOT", self.c):
            with self.assertRaises(ledger.Order2GateClosed):
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

    def gate_after_result(self):
        self.sealed()
        self.commit("gkg-run-result")
        with mock.patch.object(ledger, "PROJECT_ROOT", self.c):
            order2_gate.gate()

    def test_dirty_worktree_closes(self):
        """作業ツリーのマニフェストが HEAD の版と違う（取得の途中のコミットしていない行など）と閉じる。"""
        self.gate_after_result()
        off = os.path.join(self.c, ledger.GKG_MANIFESTS["official"])
        with open(off, "wb") as f:
            f.write(b"")
        self.assert_closed_but_result_ok("HEAD の版と違う")

    def test_rewritten_history_closes(self):
        """過去の版が HEAD の版の先頭と同じでない（コミットした行を書き換えて戻した）と閉じる。"""
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
        # T-077：HEAD ではなく、固定したコミットの記録（seq 3 の acquisition-start、seq 4 の result）を取り出す
        fixed_records.checkout(self.c)

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
        subprocess.run(["git", "clone", "-q", "--depth", "1", "file://" + self.c, shallow], check=True,
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
                       "作業ツリーと HEAD が同じ", "stop_kind", "trial_result", "記録を最初に含んだコミット",
                       "空の行"):
            self.assertIn(phrase, text)


if __name__ == "__main__":
    unittest.main()
