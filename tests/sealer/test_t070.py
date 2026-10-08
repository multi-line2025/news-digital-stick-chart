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
import test_writers as tw  # noqa: E402
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


# 仮のプロジェクトの取得のコード（tw.CODE_REL）と、それが PINNED_SHA256 で固定する gkg.py（select_files・
# trial_plan・parse_filelist だけの小さなもの）。v2 は select_files が size 0 のファイルを外す、別の版
FAKE_GKG = b"""TRIAL_DAYS = ("2015-03-02", "2015-03-03", "2015-03-04")


def parse_filelist(data):
    lines = data.split(b"\\n")
    out = []
    for raw in lines[1:-1]:
        f = raw.split(b"\\t")
        out.append((f[0].decode(), f[1].decode(), int(f[2]), f[3].decode()))
    return out


def select_files(rows):
    days = {}
    for ft, kind, size, md5 in sorted(rows):
        if kind != "gkg"%s:
            continue
        day = "%%s-%%s-%%s" %% (ft[:4], ft[4:6], ft[6:8])
        days.setdefault(day, []).append({"file_time": ft, "size": size, "md5": md5, "ambiguous": False})
    return dict(sorted(days.items()))


def trial_plan(plan):
    return {d: plan[d] for d in TRIAL_DAYS if d in plan}
"""
FAKE_GKG_V1 = FAKE_GKG % b""
FAKE_GKG_V2 = FAKE_GKG % b" or size == 0"
GKG_REL = "src/collector/gkg.py"


def acquire_code(gkg_bytes):
    return ('GKG_REL = "%s"\nPINNED_SHA256 = (\n    (GKG_REL, "%s"),\n)\n'
            % (GKG_REL, ledger.sha256_hex(gkg_bytes))).encode()


def filelist_body(rows):
    return b"file_time\tfile_type\tsize_bytes\tmd5\n" + b"".join(
        ("%s\t%s\t%d\t%s\n" % r).encode() for r in rows)


# 封印済みのファイル一覧の本体（の見本）。2015-03-02〜05 の gkg と、ほかの種類の行
ROWS = [("20150302000000", "gkg", 10, md5(1)), ("20150302001500", "gkg", 0, md5(2)),
        ("20150302001500", "export", 5, md5(3)), ("20150303000000", "gkg", 11, md5(4)),
        ("20150304000000", "gkg", 12, md5(5)), ("20150304001500", "gkg", 13, md5(6)),
        ("20150305000000", "gkg", 14, md5(7))]
BODY = filelist_body(ROWS)


def plan_of(gkg_bytes, mode):
    ns = {}
    exec(gkg_bytes.decode(), ns)
    plan = ns["select_files"](ns["parse_filelist"](BODY))
    return ns["trial_plan"](plan) if mode == "trial" else plan


class RebuildCase(t31.GkgCase):
    """封印済みのファイル一覧（BODY）と、取得のコードが固定する gkg.py（FAKE_GKG_V1）を置いた仮のプロジェクト。
    ファイル一覧の本体と、日の集計の置き場所は、このテストの一時フォルダの中だけに置く。"""

    def setUp(self):
        super().setUp()
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        self.tmp = td.name
        self.filelist = os.path.join(self.tmp, "filelist.tsv")
        with open(self.filelist, "wb") as f:
            f.write(BODY)
        self.put_code(FAKE_GKG_V1)

    def result(self, now, start_seq, kept=None):
        return super().result(now, start_seq, ledger.sha256_hex(BODY))      # 一覧の sha256 を本体に合わせる

    def start_run(self, now, **kw):
        kw.setdefault("filelist_sha256", ledger.sha256_hex(BODY))
        return super().start_run(now, **kw)

    def put_code(self, gkg_bytes):
        os.makedirs(os.path.join(self.root, "src", "collector"), exist_ok=True)
        with open(os.path.join(self.root, GKG_REL), "wb") as f:
            f.write(gkg_bytes)
        with open(os.path.join(self.root, tw.CODE_REL), "wb") as f:
            f.write(acquire_code(gkg_bytes))
        self.git("add", "-A")
        self.git("commit", "-q", "--allow-empty", "-m", "取得のコード")

    def run_with_plan(self, mode, plan, now=T0 + 4 * H):
        sha = ledger.gkg_plan_sha256(plan)
        n = sum(len(v) for v in plan.values())
        rec, rel, _o = self.start_run(now, mode=mode, plan=(len(plan), n), plan_sha256=sha)
        self.commit("run")
        return rec

    def verify_gkg(self, *extra):
        return tl.run_verify_inproc(self.root, "gkg-runs", *extra)


class TestRebuild(RebuildCase):
    def test_honest_trial(self):
        self.ready()
        rec = self.run_with_plan("trial", plan_of(FAKE_GKG_V1, "trial"))
        code, out, err = self.verify_gkg("--filelist", self.filelist)
        self.assertEqual(code, 0, err)
        self.assertIn("seq %d の run：封印済みのファイル一覧から、記録が固定する版の select_files で作り直した計画の "
                      "sha256 は plan_sha256 と同じ" % rec["seq"], out)
        # 一覧の本体が無いとき（第三者の通常の場合）、sha256 の違う本体を渡したときは「照らさなかった」
        for extra in ((), ("--filelist", self.write_tmp("other.tsv", BODY + b"x"))):
            code, out, err = self.verify_gkg(*extra)
            self.assertEqual(code, 0, err)
            self.assertIn("照らさなかった：seq %d の run の plan_sha256 は、封印済みのファイル一覧" % rec["seq"], out)

    def write_tmp(self, name, data):
        p = os.path.join(self.tmp, name)
        with open(p, "wb") as f:
            f.write(data)
        return p

    def test_dropped_day_and_file_stop(self):
        """日を抜いた計画、ファイルを抜いた計画は、どちらも plan_sha256 が作り直した計画と合わずに止まる。"""
        self.ready()
        self.start_run(T0 + 4 * H)
        full = plan_of(FAKE_GKG_V1, "official")
        no_day = {d: v for d, v in full.items() if d != "2015-03-03"}
        rec = self.run_with_plan("official", no_day, now=T0 + 5 * H)
        code, _o, err = self.verify_gkg("--filelist", self.filelist)
        self.assertEqual(code, 1)
        self.assertIn("seq %d の gkg-run-start の plan_sha256" % rec["seq"], err)
        self.assertIn("作り直した計画の sha256", err)

    def test_dropped_file_stops(self):
        self.ready()
        trial = plan_of(FAKE_GKG_V1, "trial")
        no_file = dict(trial, **{"2015-03-04": trial["2015-03-04"][:1]})
        self.run_with_plan("trial", no_file)
        code, _o, err = self.verify_gkg("--filelist", self.filelist)
        self.assertEqual(code, 1)
        self.assertIn("作り直した計画の sha256", err)

    def test_pinned_version_not_head(self):
        """作り直しは、記録の code_sha256 が固定する版の gkg.py で行う（HEAD の版ではない）。記録のあとに gkg.py
        （と取得のコード）を v2 に変えてコミットしても、v1 で作った正直な計画は通る。HEAD の版で作り直すと合わない。"""
        self.ready()
        rec = self.run_with_plan("trial", plan_of(FAKE_GKG_V1, "trial"))
        self.assertNotEqual(ledger.gkg_plan_sha256(plan_of(FAKE_GKG_V1, "trial")),
                            ledger.gkg_plan_sha256(plan_of(FAKE_GKG_V2, "trial")))
        self.put_code(FAKE_GKG_V2)
        code, out, err = self.verify_gkg("--filelist", self.filelist)
        self.assertEqual(code, 0, err)
        self.assertIn("seq %d の run：封印済みのファイル一覧から" % rec["seq"], out)

    def test_day_rows_against_rebuilt_plan(self):
        """作り直した計画で check_plan_rows を流す：計画に無い日の day の行で止まる。"""
        self.ready()
        rec = self.run_with_plan("trial", plan_of(FAKE_GKG_V1, "trial"))
        path = os.path.join(self.root, ledger.GKG_MANIFESTS["trial"])
        with open(path, encoding="utf-8") as f:
            start = json.loads(f.read().splitlines()[0])
        base = {k: start[k] for k in ledger.GKG_ROW_BASE}
        base["run_id"] = start["run_id"]
        day = dict(base, kind="day", day="2015-03-03", file_name="gkg-trial-%s-day-20150303.tsv.gz" % start["run_id"],
                   sha256="a" * 64, files_listed=2, files_ok=2, files_failed=0, failed_files=[])
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(day, sort_keys=True) + "\n")
        code, _o, err = self.verify_gkg("--filelist", self.filelist)
        self.assertEqual(code, 1)
        self.assertIn("files_listed 2 が、計画の本体のその日のファイルの数 1 と違う", err)
        _ = rec


class TestRealChain(unittest.TestCase):
    """本物の seq 8 の code_sha256 が固定する版（acquire_gkg.py → PINNED_SHA256 → gkg.py・filelist.py・
    privacy_scan.py など）を git の履歴から取り出して、見本の一覧から試しの run の計画を作り直せる（両方の Python）。"""

    def test_real_pinned_versions(self):
        import glob
        from test_t056 import pythons
        d = json.load(open(glob.glob(os.path.join(tl.PROJECT, "sealed", "gkg-run-start-*.json"))[0], encoding="utf-8"))
        body = BODY
        code = r"""
import json, sys, tempfile
sys.path.insert(0, sys.argv[1])
import verify, ledger
d = json.loads(sys.argv[3])
with tempfile.TemporaryDirectory() as tmp:
    plan = verify.rebuild_plan(verify.Repo(sys.argv[2]), d, sys.argv[4].encode("ascii"), tmp, {}, "見本")
print(json.dumps({k: len(v) for k, v in sorted(plan.items())}))
"""
        import subprocess
        for py in pythons():
            r = subprocess.run([py, "-B", "-c", code, os.path.join(tl.PROJECT, "src", "sealer"), tl.PROJECT,
                                json.dumps(d), body.decode("ascii")],
                               capture_output=True, env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
            self.assertEqual(r.returncode, 0, (py, r.stderr.decode()[-2000:]))
            self.assertEqual(json.loads(r.stdout), {"2015-03-02": 2, "2015-03-03": 1, "2015-03-04": 2}, py)


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
        for phrase in ("計画の一覧の sha256（T-070", "gkg_plan_canonical",
                       "都合の悪いファイルを failed_files に回す", "`plan_sha256` でも閉じない",
                       "計画に無い日に差し替える", "日ごとの files_listed を付け替える",
                       "抜いた日の数に合わせて run-start の行の `days`・`files_selected` も書き換えれば",
                       "`trial_days` の数とちょうど同じ", "計画の本体はどこにも置かない",
                       "--filelist <封印済みのファイル一覧の本体>", "版の固定の連なり", "HEAD の版は使わない",
                       "第三者が照らす手順と限界", "masterfilelist.txt", "GDELT が公開の一覧を後から変えた"):
            self.assertIn(phrase, text)
        for gone in ("gkg-<mode>-<run_id>-plan.json", "計画の本体の置き場所は Git の中"):
            self.assertNotIn(gone, text)


if __name__ == "__main__":
    unittest.main()
