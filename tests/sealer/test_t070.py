"""T-070 のテスト：gkg-run-start の計画の一覧の sha256（plan_sha256）と、その本体との照合（T-068 の監査 中-B・
軽-B）、GKG_RUN_PLAN_REQUIRED_FOR_OFFICIAL を True にしたときに plan_sha256 も必須になること。

実行（プロジェクトのルートで）:
    PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest discover -s tests/sealer -v

仮のプロジェクト（test_t031.GkgCase）と、本物の clone（test_t066.Clone）の中だけで書く。ots・drand は偽物。
本物の sealed/・data/manifest/ には書かない。ネットワークと LACIE SHARE には触れない（計画の本体と日の集計は
仮の置き場所に作る）。収集係の src/collector/gkg.py は、select_files を呼ぶためだけに読み込む（書かない）。
"""

import importlib.util
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import test_ledger as tl  # noqa: E402
import test_t031 as t31  # noqa: E402
from test_ledger import T0, H  # noqa: E402
from test_t066 import Clone, dump, rows_of  # noqa: E402

ledger = tl.ledger
DOC = os.path.join(tl.PROJECT, "docs", "verify", "periods-seal.md")
OFFICIAL = ledger.GKG_MANIFESTS["official"]


def load_gkg():
    spec = importlib.util.spec_from_file_location("gkg_for_t070", os.path.join(tl.PROJECT, "src", "collector", "gkg.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def md5(i):
    return "%032x" % i


# 2日・5ファイルの計画（select_files の出力の形）
PLAN = {"2015-03-02": [{"file_time": "20150302000000", "size": 10, "md5": md5(1), "ambiguous": False},
                       {"file_time": "20150302001500", "size": 11, "md5": md5(2), "ambiguous": True},
                       {"file_time": "20150302003000", "size": 12, "md5": md5(3), "ambiguous": False}],
        "2015-03-03": [{"file_time": "20150303000000", "size": 13, "md5": md5(4), "ambiguous": False},
                       {"file_time": "20150303001500", "size": 14, "md5": md5(5), "ambiguous": False}]}


class TestCanonical(unittest.TestCase):
    def test_form(self):
        b = ledger.gkg_plan_canonical(PLAN)
        self.assertTrue(b.startswith(b'[["2015-03-02",[["20150302000000",10,"'))
        self.assertNotIn(b" ", b)
        self.assertNotIn(b"ambiguous", b)
        # 並べ方によらない（日・file_time の順に並べ直す）
        shuffled = {"2015-03-03": list(reversed(PLAN["2015-03-03"])), "2015-03-02": PLAN["2015-03-02"]}
        self.assertEqual(ledger.gkg_plan_canonical(shuffled), b)
        self.assertEqual(ledger.parse_gkg_plan(b)["2015-03-03"][1]["file_time"], "20150303001500")
        for bad in (b + b"\n", b.replace(b",", b", ", 1), b"[]x", json.dumps([["2015-03-03", []], ["2015-03-02", []]],
                                                                         separators=(",", ":")).encode()):
            with self.subTest(bad=bad[:40]):
                with self.assertRaises(ledger.LedgerError):
                    ledger.parse_gkg_plan(bad)

    def test_from_collector_select_files(self):
        """一覧の正規の形は、収集係の select_files の出力から決まる（読むだけ）。"""
        gkg = load_gkg()
        rows = [("20150302000000", "gkg", 10, md5(1)), ("20150302001500", "gkg", 11, md5(2)),
                ("20150302001500", "gkg", 99, md5(9)), ("20150302003000", "gkg", 12, md5(3)),
                ("20150303000000", "gkg", 13, md5(4)), ("20150303001500", "gkg", 14, md5(5)),
                ("20150303001500", "export", 1, md5(7))]
        plan = gkg.select_files(rows)
        self.assertEqual(ledger.gkg_plan_canonical(plan), ledger.gkg_plan_canonical(PLAN))


class PlanRun(t31.GkgCase):
    """計画の一覧つきの run を、マニフェスト（run-start・day・run-complete）と計画の本体（Git の data/manifest）まで
    作る。日の集計の置き場所（--day-files）は、このテストの一時フォルダの中だけに作る（差し戻し1回目 軽-6）。"""

    def setUp(self):
        super().setUp()
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        self.store = os.path.join(td.name, "store")
        os.makedirs(self.store)

    def official_with_plan(self, plan=PLAN, body=None, in_git=True, git_body=None):
        self.ready()
        self.start_run(T0 + 4 * H)
        data = ledger.gkg_plan_canonical(plan) if body is None else body
        sha = ledger.sha256_hex(data)
        nplan = ledger.parse_gkg_plan(data)
        off, rel, _o = self.start_run(T0 + 5 * H, mode="official", manifest=False,
                                      plan=(len(plan), sum(len(v) for v in plan.values())), plan_sha256=sha)
        self.off = off
        doc = self.doc_of(rel)
        self.assertEqual(doc["plan_sha256"], sha)
        self.assertEqual(tuple(sorted(doc)), ledger.GKG_RUN_DOC_KEYS_PLAN_SHA)
        start = self.manifest_row(off)
        self.rid = start["run_id"]
        base = {k: start[k] for k in ledger.GKG_ROW_BASE}
        base["run_id"] = start["run_id"]
        rows = [start]
        for day, files in sorted(nplan.items()):
            rows.append(dict(base, kind="day", day=day, file_name="gkg-official-%s-day-%s.tsv.gz"
                             % (start["run_id"], day.replace("-", "")), sha256="a" * 64, files_listed=len(files),
                             files_ok=len(files), files_failed=0, failed_files=[]))
        rows.append(dict(base, kind="run-complete", days=len(nplan), files_ok=sum(len(v) for v in nplan.values()),
                         files_failed=0, fetch_log_file="gkg-official-%s-fetch-log.jsonl" % start["run_id"],
                         fetch_log_sha256="b" * 64))
        self.rows = rows
        self.write_rows(rows)
        if in_git:
            with open(self.plan_path(), "wb") as f:
                f.write(data if git_body is None else git_body)
        self.commit("正式な run と計画の本体")
        return start["run_id"]

    def plan_path(self):
        return os.path.join(self.root, "data", "manifest", "gkg-official-%s-plan.json" % self.rid)

    def write_rows(self, rows):
        with open(os.path.join(self.root, OFFICIAL), "w", encoding="utf-8") as f:
            f.write("".join(json.dumps(r, sort_keys=True) + "\n" for r in rows))

    def verify_gkg(self, *extra):
        return tl.run_verify_inproc(self.root, "gkg-runs", *extra)


class TestPlanBody(PlanRun):
    def test_honest_passes_and_mutations(self):
        rid = self.official_with_plan()
        code, out, err = self.verify_gkg()
        self.assertEqual(code, 0, err)
        self.assertIn("計画の本体 data/manifest/gkg-official-%s-plan.json（Git の" % rid, out)
        self.assertIn("day の行の日付・files_listed・failed_files はその一覧と合う", out)
        self.assertIn("files_failed の合計 0", out)

        def mutated(mutate):
            rows = [dict(r) for r in self.rows]
            mutate(rows)
            self.write_rows(rows)
            return self.verify_gkg()
        # (b) 計画に無い日に差し替える（区画の中の日）
        code, _o, err = mutated(lambda r: r[2].update(day="2015-03-05", file_name=r[2]["file_name"].replace(
            "20150303", "20150305")))
        self.assertEqual(code, 1)
        self.assertIn("計画に無い日", err)

        # (c) 日ごとの files_listed を付け替える（合計はそのまま）
        def swap(r):
            r[1].update(files_listed=2, files_ok=2)
            r[2].update(files_listed=3, files_ok=3)
        code, _o, err = mutated(swap)
        self.assertEqual(code, 1)
        self.assertIn("files_listed", err)
        # failed_files に計画に無いファイル
        code, _o, err = mutated(lambda r: (r[1].update(files_ok=2, files_failed=1, failed_files=[
            {"file_time": "20150302999999"}]), r[3].update(files_ok=4, files_failed=1)))
        self.assertEqual(code, 1)
        self.assertIn("計画の本体のその日に無いファイル", err)
        # (a) 都合の悪いファイルを failed_files に回す：計画の照合でも止まらない（残る限界。手順書のとおり）
        code, out, err = mutated(lambda r: (r[1].update(files_ok=2, files_failed=1, failed_files=[
            {"file_time": "20150302001500"}]), r[3].update(files_ok=4, files_failed=1)))
        self.assertEqual(code, 0, err)
        self.assertIn("files_failed の合計 1", out)
        # run-start の行の plan_sha256 を変える
        code, _o, err = mutated(lambda r: r[0].update(plan_sha256="c" * 64))
        self.assertEqual(code, 1)
        self.assertIn("plan_sha256", err)
        self.write_rows(self.rows)
        # 作業ツリーの本体だけを変える → Git の版と違うので止まる
        with open(self.plan_path(), "ab") as f:
            f.write(b" ")
        code, _o, err = self.verify_gkg()
        self.assertEqual(code, 1)
        self.assertIn("Git", err)
        # 変えた本体を後からコミットしても、verify は記録を最初に含んだコミットの版を読むので、止まったまま
        self.commit("本体を変える")
        code, _o, err = self.verify_gkg()
        self.assertEqual(code, 1)
        self.assertIn("Git", err)

    def test_git_body_sha_mismatch(self):
        """記録と同じコミットにある本体の sha256 が、記録の plan_sha256 と違えば止まる。"""
        other = {"2015-03-02": PLAN["2015-03-02"], "2015-03-03": [dict(PLAN["2015-03-03"][0], size=99),
                                                                  PLAN["2015-03-03"][1]]}
        self.official_with_plan(git_body=ledger.gkg_plan_canonical(other))
        code, _o, err = self.verify_gkg()
        self.assertEqual(code, 1)
        self.assertIn("plan_sha256 と違う", err)

    def test_official_body_missing_in_git_stops(self):
        rid = self.official_with_plan(in_git=False)
        with open(os.path.join(self.store, "gkg-official-%s-plan.json" % rid), "wb") as f:
            f.write(ledger.gkg_plan_canonical(PLAN))
        code, _o, err = self.verify_gkg("--day-files", self.store)      # 置き場所にあっても、official は止まる
        self.assertEqual(code, 1)
        self.assertIn("Git に計画の本体", err)

    def test_m11_counts_vs_record(self):
        """本体の数と days・files_selected の照合（M11）を外すと落ちる：本体を 2 日・4 ファイルにし、記録は
        2 日・5 ファイルと書く（day の行は本体どおり）。"""
        small = {"2015-03-02": PLAN["2015-03-02"][:2], "2015-03-03": PLAN["2015-03-03"]}
        self.ready()
        self.start_run(T0 + 4 * H)
        data = ledger.gkg_plan_canonical(small)
        off, rel, _o = self.start_run(T0 + 5 * H, mode="official", plan=(2, 5), plan_sha256=ledger.sha256_hex(data))
        self.rid = self.doc_of(rel)["run_id"]
        with open(self.plan_path(), "wb") as f:
            f.write(data)
        self.commit("計画")
        code, _o, err = self.verify_gkg()
        self.assertEqual(code, 1)
        self.assertIn("日の数・ファイルの数が", err)


class TestPlanUnit(unittest.TestCase):
    def test_m6_day_set(self):
        """日の集まりの照合（M6）を外すと落ちる：run-complete がある run で、計画の日が1日欠けている。"""
        plan = ledger.parse_gkg_plan(ledger.gkg_plan_canonical(PLAN))
        run = {"days": [{"day": "2015-03-02", "files_listed": 3, "failed_files": []}], "complete": {"kind": "run-complete"}}
        with self.assertRaisesRegex(ledger.LedgerError, "日の集まり"):
            ledger.check_plan_rows(plan, run, "見本")
        run["complete"] = None                    # 終わっていない run は、途中までの日でよい
        ledger.check_plan_rows(plan, run, "見本")

    def test_canonical_types_and_duplicates(self):
        bad_types = {"2015-03-02": [{"file_time": "20150302000000", "size": "10", "md5": md5(1)}]}
        with self.assertRaises(ledger.LedgerError):
            ledger.gkg_plan_canonical(bad_types)
        with self.assertRaises(ledger.LedgerError):
            ledger.gkg_plan_canonical({"2015-03-02": [{"file_time": "20150302000000", "size": True, "md5": md5(1)}]})
        same_day = {"2015-03-02": [{"file_time": "20150302000000", "size": 1, "md5": md5(1)},
                                   {"file_time": "20150302000000", "size": 2, "md5": md5(2)}]}
        with self.assertRaisesRegex(ledger.LedgerError, "2回ある"):
            ledger.gkg_plan_canonical(same_day)
        other_day = {"2015-03-02": [{"file_time": "20150302000000", "size": 1, "md5": md5(1)}],
                     "2015-03-03": [{"file_time": "20150302000000", "size": 1, "md5": md5(1)}]}
        with self.assertRaisesRegex(ledger.LedgerError, "2回ある"):
            ledger.gkg_plan_canonical(other_day)

    def test_run_none_is_unchecked(self):
        """軽-4：マニフェストに行が無いときは「合う」と言わず「照らさなかった」。"""
        data = ledger.gkg_plan_canonical(PLAN)

        class St:
            unchecked = []
            root = "/nonexistent-t070"
            records = []
            data = b""
        import contextlib
        import io
        with mock.patch.object(tl.verify, "_plan_from_git", return_value=(data, "見本", False)), \
                contextlib.redirect_stdout(io.StringIO()):
            tl.verify._check_plan_body(St, {"seq": 9}, {"mode": "official", "run_id": "f" * 16, "days": 2,
                                                         "files_selected": 5, "plan_sha256": ledger.sha256_hex(data)},
                                       None, [])
        self.assertTrue(any("day の行と計画の本体の照合" in u for u in St.unchecked), St.unchecked)


class TestRequiredFlag(t31.GkgCase):
    """GKG_RUN_PLAN_REQUIRED_FOR_OFFICIAL を True にすると、official は plan_sha256 まで必須（T-070 の 5）。"""

    def test_required_includes_sha(self):
        self.ready()
        self.start_run(T0 + 4 * H)
        self.commit("試し")
        before = self.ledger_bytes()
        with mock.patch.object(ledger, "GKG_RUN_PLAN_REQUIRED_FOR_OFFICIAL", True):
            with self.assertRaisesRegex(ledger.LedgerError, "plan_sha256"):
                self.start_run(T0 + 5 * H, mode="official", manifest=False, plan=(2, 5))
            self.assertEqual(self.ledger_bytes(), before)
        # False（今）のままなら書ける。そのあと True にすると verify が止める
        off, _rel, _o = self.start_run(T0 + 5 * H, mode="official", plan=(2, 5))
        code, out, err = tl.run_verify_inproc(self.root, "gkg-runs")
        self.assertEqual(code, 0, err)
        self.assertIn("seq %d の gkg-run-start（official）に plan_sha256 が無い" % off["seq"], out)
        with mock.patch.object(ledger, "GKG_RUN_PLAN_REQUIRED_FOR_OFFICIAL", True):
            code, _out, err = tl.run_verify_inproc(self.root, "gkg-runs")
        self.assertEqual(code, 1)
        self.assertIn("plan_sha256", err)
        self.assertFalse(ledger.GKG_RUN_PLAN_REQUIRED_FOR_OFFICIAL)        # 今回は False のまま

    def test_sha_needs_counts(self):
        self.ready()
        with self.assertRaisesRegex(ledger.LedgerError, "days・files_selected も渡す"):
            self.start_run(T0 + 4 * H, manifest=False, plan_sha256="d" * 64)


class TestTrialDaysEqual(Clone):
    """軽-B：試しの run の days は trial_days の数とちょうど同じ。seq 8 は通る。"""

    def test_row(self):
        ledger.check_gkg_manifests(self.records(), self.read, {"trial": self.body, "official": None})
        rows = rows_of(self.body)
        rows[0]["days"] = 2
        with self.assertRaisesRegex(ledger.LedgerError, "trial_days の数と同じでない"):
            ledger.check_gkg_manifests(self.records(), self.read, {"trial": dump(rows), "official": None})


class TestTrialPlanEqual(t31.GkgCase):
    def test_record(self):
        self.ready()
        with self.assertRaisesRegex(ledger.LedgerError, "trial_days の数と同じでない"):
            self.start_run(T0 + 4 * H, manifest=False, plan=(2, 10))
        rec, rel, _o = self.start_run(T0 + 4 * H, plan=(3, 288), plan_sha256="e" * 64)
        self.assertEqual(self.doc_of(rel)["days"], 3)


TRIAL_PLAN = {d: [{"file_time": d.replace("-", "") + "000000", "size": 1, "md5": md5(i)}]
              for i, d in enumerate(t31.TRIAL_DAYS)}


class TestTrialPlanBody(PlanRun):
    """試しの run の計画の本体：Git に無ければ --day-files を探し、そこにも無ければ「照らさなかった」。M9。"""

    def trial(self, body, in_git=False):
        self.ready()
        rec, rel, _o = self.start_run(T0 + 4 * H, plan=(3, 3), plan_sha256=ledger.sha256_hex(body))
        self.rid = self.doc_of(rel)["run_id"]
        if in_git:                                  # 記録と同じコミットに本体を入れる
            with open(os.path.join(self.root, "data", "manifest", "gkg-trial-%s-plan.json" % self.rid), "wb") as f:
                f.write(body)
        self.commit("試しの run")
        return rec

    def test_missing_then_day_files(self):
        body = ledger.gkg_plan_canonical(TRIAL_PLAN)
        rec = self.trial(body)
        code, out, err = self.verify_gkg()
        self.assertEqual(code, 0, err)
        self.assertIn("seq %d の run の計画の本体 data/manifest/gkg-trial-%s-plan.json が、Git にも" % (rec["seq"], self.rid),
                      out)
        with open(os.path.join(self.store, "gkg-trial-%s-plan.json" % self.rid), "wb") as f:
            f.write(body)
        code, out, err = self.verify_gkg("--day-files", self.store)
        self.assertEqual(code, 0, err)
        self.assertIn("（--day-files の置き場所）の sha256 は plan_sha256 と同じ", out)

    def test_m9_days_vs_trial_days(self):
        """本体と trial_days の照合（M9）を外すと落ちる：本体の3日が trial_days と違う（数は同じ）。"""
        other = {d: v for d, v in zip(("2015-03-05", "2015-03-06", "2015-03-07"), TRIAL_PLAN.values())}
        body = ledger.gkg_plan_canonical(other)
        self.trial(body, in_git=True)
        code, _o, err = self.verify_gkg()
        self.assertEqual(code, 1)
        self.assertIn("trial_days と違う", err)

    def test_row_only_plan_sha_stops(self):
        """軽-3：記録に plan_sha256 が無く、run-start の行にだけある。"""
        self.ready()
        rec, _rel, _o = self.start_run(T0 + 4 * H, manifest=False, plan=(3, 3))
        self.append_manifest(rec, plan_sha256="9" * 64)
        code, _o, err = self.verify_gkg()
        self.assertEqual(code, 1)
        self.assertIn("中身には無い", err)


class TestDocT070(unittest.TestCase):
    def test_statements(self):
        with open(DOC, encoding="utf-8") as f:
            text = f.read()
        for phrase in ("計画の一覧の sha256（T-070", "gkg_plan_canonical", "gkg-<mode>-<run_id>-plan.json",
                       "都合の悪いファイルを failed_files に回す", "`plan_sha256` でも閉じない",
                       "計画に無い日に差し替える", "日ごとの files_listed を付け替える",
                       "抜いた日の数に合わせて run-start の行の `days`・`files_selected` も書き換えれば",
                       "`trial_days` の数とちょうど同じ", "計画の本体の置き場所は Git の中",
                       "`data/manifest/gkg-<mode>-<run_id>-plan.json`", "run-start より前にコミットする",
                       "限界（T-070 差し戻し1回目 中-2）", "GDELT の公開のファイル一覧"):
            self.assertIn(phrase, text)


if __name__ == "__main__":
    unittest.main()
