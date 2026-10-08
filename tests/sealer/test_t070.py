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
    """計画の一覧つきの正式な run を、マニフェスト（run-start・day・run-complete）と置き場所まで作る。"""

    def official_with_plan(self, plan=PLAN):
        self.ready()
        self.start_run(T0 + 4 * H)
        sha = ledger.gkg_plan_sha256(plan)
        off, rel, _o = self.start_run(T0 + 5 * H, mode="official", manifest=False,
                                      plan=(len(plan), sum(len(v) for v in plan.values())), plan_sha256=sha)
        self.off = off
        doc = self.doc_of(rel)
        self.assertEqual(doc["plan_sha256"], sha)
        self.assertEqual(tuple(sorted(doc)), ledger.GKG_RUN_DOC_KEYS_PLAN_SHA)
        start = self.manifest_row(off)
        base = {k: start[k] for k in ledger.GKG_ROW_BASE}
        base["run_id"] = start["run_id"]
        rows = [start]
        for day, files in sorted(plan.items()):
            rows.append(dict(base, kind="day", day=day, file_name="gkg-official-%s-day-%s.tsv.gz"
                             % (start["run_id"], day.replace("-", "")), sha256="a" * 64, files_listed=len(files),
                             files_ok=len(files), files_failed=0, failed_files=[]))
        rows.append(dict(base, kind="run-complete", days=len(plan), files_ok=sum(len(v) for v in plan.values()),
                         files_failed=0, fetch_log_file="gkg-official-%s-fetch-log.jsonl" % start["run_id"],
                         fetch_log_sha256="b" * 64))
        self.rows = rows
        self.write_rows(rows)
        self.store = os.path.join(self.root, "..", "store-t070")
        os.makedirs(self.store, exist_ok=True)
        with open(os.path.join(self.store, "gkg-official-%s-plan.json" % start["run_id"]), "wb") as f:
            f.write(ledger.gkg_plan_canonical(plan))
        return start["run_id"]

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
        self.assertIn("計画の本体 gkg-official-%s-plan.json が、--day-files の置き場所に無い" % rid, out)
        self.assertIn("files_failed の合計 0", out)
        code, out, err = self.verify_gkg("--day-files", self.store)
        self.assertEqual(code, 0, err)
        self.assertIn("計画の本体 gkg-official-%s-plan.json の sha256 は plan_sha256 と同じ" % rid, out)

        def mutated(mutate):
            rows = [dict(r) for r in self.rows]
            mutate(rows)
            self.write_rows(rows)
            return self.verify_gkg("--day-files", self.store)
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
        # 本体の中身を変える（sha256 が合わない）
        self.write_rows(self.rows)
        with open(os.path.join(self.store, "gkg-official-%s-plan.json" % rid), "ab") as f:
            f.write(b" ")
        code, _o, err = self.verify_gkg("--day-files", self.store)
        self.assertEqual(code, 1)
        self.assertIn("plan_sha256 と違う", err)


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


class TestDocT070(unittest.TestCase):
    def test_statements(self):
        with open(DOC, encoding="utf-8") as f:
            text = f.read()
        for phrase in ("計画の一覧の sha256（T-070", "gkg_plan_canonical", "gkg-<mode>-<run_id>-plan.json",
                       "都合の悪いファイルを failed_files に回す", "`plan_sha256` でも閉じない",
                       "計画に無い日に差し替える", "日ごとの files_listed を付け替える",
                       "抜いた日の数に合わせて run-start の行の `days`・`files_selected` も書き換えれば",
                       "`trial_days` の数とちょうど同じ"):
            self.assertIn(phrase, text)


if __name__ == "__main__":
    unittest.main()
