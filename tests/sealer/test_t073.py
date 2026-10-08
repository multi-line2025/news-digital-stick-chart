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


def scenarios():
    """(名前, 試しの run のマニフェスト, 正式な run のマニフェスト, 期待する run か None)"""
    t_done = jl([tstart(R)] + [day("trial", R, d) for d in counting.TRIAL_DAYS] + [{"kind": "run-complete", "run_id": R}])
    t_open = jl([tstart(R)])
    t_open_day = jl([tstart(R), day("trial", R, counting.TRIAL_DAYS[0])])
    o_days = [day("official", OF, d) for d in counting.TRIAL_DAYS]
    return [
        ("1段目：試しの run が終わり、正式な run は無い", t_done, b"", ("trial", R)),
        ("1段目：試しの run が終わり、正式な run も始まっている", t_done, jl([ostart(t_done, [R])] + o_days), ("trial", R)),
        ("2段目：試しの run が無く、正式な run がある", b"", jl([ostart(b"", [])] + o_days), ("official", OF)),
        ("2段目：R に day の行が無い", t_open, jl([ostart(t_open, [R])] + o_days), ("official", OF)),
        ("止まる：R に day の行があり終わっていない", t_open_day, jl([ostart(t_open_day, [R])]), ("official", OF)),
        ("止まる：試しの run が二つ", jl([tstart(R), tstart(S)]), jl([ostart(jl([tstart(R), tstart(S)]), [R, S])]),
         ("official", OF)),
        ("待つ：何も無い", b"", b"", None),
        ("待つ：R が終わらず、正式な run も無い", t_open, b"", None),
    ]


class TestInputRun(unittest.TestCase):
    def test_same_as_decide(self):
        """関門が決める run は、decide() が見る run と同じ（段の記録と runs）。待つ場合は関門が閉じる。"""
        for name, trial, official, want in scenarios():
            with self.subTest(name=name):
                out = counting.decide(trial, official, no_day_file)
                if want is None:
                    self.assertEqual(out["status"], "pending")
                    with self.assertRaises(ledger.Order2GateClosed):
                        ledger.order2_input_run(trial, official)
                    continue
                got = ledger.order2_input_run(trial, official)
                self.assertEqual((got["mode"], got["run_id"]), want)
                self.assertEqual(out["runs"][want[0]]["run_id"], want[1])
                stages = [s for s in out["steps"] if s.get("step") in ("trial", "official")]
                for s in stages:
                    self.assertEqual(s["step"], want[0])
                    if s["step"] == "trial":
                        self.assertEqual(s["run_id"], want[1])

    def test_constants(self):
        self.assertEqual(ledger.ORDER2_STATUSES, counting.ORDER2_STATUSES)

    def test_bad_first_start(self):
        bad = jl([dict(tstart(R), trial=False)])
        with self.assertRaises(ledger.Order2GateClosed):
            ledger.order2_input_run(bad, b"")
        with self.assertRaises(ledger.Order2GateClosed):
            ledger.order2_input_run(b"{not json\n", b"")


# ---- 鎖の照合（check_stats_order → check_order2_run）

class Order2Case(Clone):
    def output(self):
        """本物の試しの run のマニフェストに decide() を当てはめた出力（日の集計は置かないので (b) で止まる）。"""
        return counting.decide(self.body, b"", no_day_file)

    def doc(self, res, mode="trial", rid=None, output=None, ref_sha=None):
        rid = rid or self.rid
        return {"kind": O2, "input_run": {"mode": mode, "run_id": rid},
                "gkg_run_result": {"seq": res["seq"], "record_sha256": ref_sha or line_sha(res)},
                "counting_output": output if output is not None else self.output()}

    def ledger_bytes(self):
        with open(os.path.join(self.c, "sealed", "ledger.jsonl"), "rb") as f:
            return f.read()

    def check(self, records, o2, doc):
        def read(r, role):
            return doc if r["seq"] == o2["seq"] else self.read(r, role)
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
        self.check(self.recs, self.o2, self.doc(self.res, output=decided))

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
            "決まった入力の run が違う": (self.doc(self.res, output=decided_other), "input_run_id"),
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
                with self.assertRaisesRegex(ledger.LedgerError, "使った run を示すキー"):
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
        self.assertIn("%s seq %d（順番2）: 使った run trial・run_id %s。その run の gkg-run-result（seq %d）は、"
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
            self.assertEqual(got, {"input_run": {"mode": "trial", "run_id": self.rid},
                                   "gkg_run_result": {"seq": res["seq"], "record_sha256": line_sha(res)}})
            code, out, _err = self.run_main()
            self.assertEqual(code, 0)
            self.assertEqual(json.loads(out), got)
            # 関門の値で作った順番2の中身は、鎖の照合に通る
            self.check(self.records(), {"seq": res["seq"] + 1, "kind": O2}, dict(got, kind=O2, counting_output=self.output()))
            # マニフェストを封印のあとで書き換えると、関門は閉じる
            with open(os.path.join(self.c, ledger.GKG_MANIFESTS["trial"]), "ab") as f:
                f.write(b"\n{}\n")
            with self.assertRaises(ledger.Order2GateClosed):
                order2_gate.gate()

    def test_gate_reads_head_version(self):
        """使う run は HEAD の版のマニフェストで決める（counting.md 4章 (1) と同じ版）。HEAD に無ければ待つ。"""
        git(self.c, "rm", "-q", "--cached", ledger.GKG_MANIFESTS["trial"])
        git(self.c, *(list(tl.AUTHOR) + ["commit", "-q", "-m", "マニフェストを外した版（テスト）"]))
        with mock.patch.object(ledger, "PROJECT_ROOT", self.c):
            with self.assertRaisesRegex(ledger.Order2GateClosed, "使う run がまだ無い"):
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


class TestDocT073(unittest.TestCase):
    def test_statements(self):
        with open(DOC, encoding="utf-8") as f:
            text = f.read()
        self.assertNotIn("http://data.gdeltproject.org/gdeltv2/masterfilelist.txt", text)
        self.assertIn("https://data.gdeltproject.org/gdeltv2/masterfilelist.txt", text)
        for phrase in ("verify.py filelist-rebuild --masterfilelist", "照らさなかった：浅い clone",
                       "第三者は永久に照らせない", "運営の手元の一覧の本体だけ",
                       "## 14. 順番2の前の関門", "src/sealer/order2_gate.py", "止まった (b) としても記録しない",
                       "counting.py を手で直接動かせば", "鎖の順序で事後に見つけられる", ledger.ORDER2_KIND):
            self.assertIn(phrase, text)


if __name__ == "__main__":
    unittest.main()
