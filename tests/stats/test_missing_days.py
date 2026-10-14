"""順番4：欠けた日の一覧（src/stats/missing_days.py）のテスト。T-087、T-089。

実行（プロジェクトのルートで）:
    PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -B -m unittest discover -s tests/stats -v

確かめること
  - 境目：72本ちょうどは欠けた日でない、71本は欠けた日。C7 の分母が0の日は、本数に依らず欠けた日
    （合成の日の集計。TestBoundaries）
  - C7 の分母は counting.candidate_counts(…, OFFICIAL_CANDIDATE) の値で、counting.py は順番1b の sha256 と同じ
  - 日の集計の sha256 が day の行と合わなければ止まる。day の行の検査に通らなければ、日の集計を1つも開かない
  - 出力に入るのは、日ごとの C7 の分母と、それが0かどうかだけ（テーマの名前やテーマごとの数は入らない）
  - day の行の入口は gkg.official_day_records() で、gkg-run-result の関門を通る。関門が無ければ
    マニフェストも日の集計も読まずに止まり、封印すれば通る（TestGateEndToEnd。tests/collector の合成の
    run の仕組みで、収集係のコードが書いた日の集計を読む。ネットワークは使わない）
  - 開くのは、day の行の file_name の日の集計だけ（open・os.open を記録して確かめる）
  - label は文書の版と同じ
本物の日の集計（LACIE SHARE）はテストでは開かない。本物のマニフェストでは day の行の検査だけを流し、
件数や日付は固定しない。
"""

import builtins
import copy
import datetime
import hashlib
import inspect
import json
import os
import re
import sys
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(os.path.dirname(HERE))
SRC = os.path.join(PROJECT, "src", "stats")
SCRIPT = os.path.join(SRC, "missing_days.py")
DOC = os.path.join(PROJECT, "docs", "stats", "missing-days-method.md")
COLLECTOR_TESTS = os.path.join(PROJECT, "tests", "collector")
sys.path.insert(0, SRC)

import candidates  # noqa: E402
import counting  # noqa: E402
import missing_days as md  # noqa: E402

D = datetime.date
BLOCK3 = (D(2015, 3, 2), D(2015, 3, 4))
DAYS3 = ("2015-03-02", "2015-03-03", "2015-03-04")
RID = "0123456789abcdef"
REFS = {"gkg_run_result_seq": 12, "gkg_run_result_record_sha256": "a" * 64,
        "manifest_path": "data/manifest/gdelt-gkg-method.jsonl", "manifest_lines": 5,
        "manifest_sha256": "b" * 64}

gkg = md._gkg()

# 文書（テーマの付き方）：(coll, v1, v2, translated)
THEMED = [("1", "ZZA;ZZB", "ZZA,10;ZZB,5", False), ("1", "ZZA", "ZZA,3", False),
          ("1", "", "", False)]
NO_THEMES = [("1", "", "", False), ("2", "", "", False)]
ONLY_TRANSLATED = [("1", "ZZA", "ZZA,1", True), ("1", "", "", False)]


def _line(ft, n, coll, v1, v2, tr):
    cols = [b""] * gkg.N_COLUMNS
    cols[gkg.I_ID] = ("%s-%s%d" % (ft, "T" if tr else "", n)).encode()
    cols[gkg.I_D21] = ft.encode()
    cols[gkg.I_COLL] = coll.encode()
    cols[gkg.I_V1T] = v1.encode()
    cols[gkg.I_V2T] = v2.encode()
    return b"\t".join(cols) + b"\n"


def make_day(day, docs_rows):
    """gkg.serialize_day の形の日の集計（gzip のバイト列）。"""
    ft = day.replace("-", "") + "120000"
    agg = gkg.Agg()
    vocab = {}
    for i, row in enumerate(docs_rows):
        gkg.add_line(agg, _line(ft, i, *row), ft.encode(), vocab)
    files = [{"file_time": ft, "result": "ok", "reason": None, "md5": "0" * 32, "size": 1,
              "sha256": "0" * 64, "attempts": 1, "docs": {g.decode(): n for g, n in agg.docs.items()}}]
    data = gkg.serialize_day(day, agg, files, "official")
    gkg.check_output_bytes(data, "テストの日の集計")
    return gkg.gzip_bytes(data)


class Fixture:
    """day の行と日の集計の組。reader は開いた名前を記録する。"""

    def __init__(self, spec, run_id=RID):
        # spec: {day: (files_ok, docs_rows)}
        self.files = {}
        self.rows = []
        for day, (ok, docs_rows) in spec.items():
            name = counting.day_file_name("official", run_id, day)
            data = make_day(day, docs_rows)
            self.files[name] = data
            self.rows.append({"kind": "day", "mode": "official", "official": True, "run_id": run_id,
                              "day": day, "files_listed": 96, "files_ok": ok,
                              "files_failed": 96 - ok, "docs": len(docs_rows), "file_name": name,
                              "sha256": hashlib.sha256(data).hexdigest()})
        self.opened = []

    def read(self, name):
        self.opened.append(name)
        return self.files.get(name, b"")

    def build(self, block=BLOCK3):
        return md.build(self.rows, block, self.read, dict(REFS))


class OpenRecorder:
    """builtins.open と os.open の呼び出しを記録する（中身はそのまま開く）。"""

    def __init__(self):
        self.paths = []
        self._open = builtins.open
        self._os_open = os.open

    def _b(self, file, *a, **k):
        if isinstance(file, (str, bytes, os.PathLike)):
            self.paths.append(os.fsdecode(file))
        return self._open(file, *a, **k)

    def _o(self, path, *a, **k):
        self.paths.append(os.fsdecode(path))
        return self._os_open(path, *a, **k)

    def __enter__(self):
        self._p1 = mock.patch.object(builtins, "open", self._b)
        self._p2 = mock.patch.object(os, "open", self._o)
        self._p1.start()
        self._p2.start()
        return self

    def __exit__(self, *exc):
        self._p2.stop()
        self._p1.stop()
        return False


class TestBoundaries(unittest.TestCase):

    def test_rule_constants_from_candidates(self):
        self.assertEqual(candidates.SLOTS_PER_DAY, 96)
        self.assertEqual(candidates.MIN_PRESENT_SLOTS, 72)
        self.assertEqual(counting.OFFICIAL_CANDIDATE, "C7")

    def test_c7_denominator_is_counting_value(self):
        for rows in (THEMED, NO_THEMES, ONLY_TRANSLATED):
            data = make_day("2015-03-02", rows)
            s = counting.parse_day(data, expect_day="2015-03-02", expect_mode="official")
            self.assertEqual(md.c7_denominator(data, "2015-03-02"),
                             counting.candidate_counts(s, "C7")[1])
        self.assertGreater(md.c7_denominator(make_day("2015-03-02", THEMED), "2015-03-02"), 0)
        self.assertEqual(md.c7_denominator(make_day("2015-03-02", NO_THEMES), "2015-03-02"), 0)
        self.assertEqual(md.c7_denominator(make_day("2015-03-02", ONLY_TRANSLATED), "2015-03-02"), 0)

    def test_72_71_and_zero_denominator(self):
        fx = Fixture({"2015-03-02": (72, THEMED), "2015-03-03": (71, THEMED),
                      "2015-03-04": (96, NO_THEMES)})
        rec = fx.build()
        got = {m["day"]: m for m in rec["missing_days"]}
        self.assertEqual(sorted(got), ["2015-03-03", "2015-03-04"])
        self.assertEqual(set(got["2015-03-03"]), {"day", "files_ok", "files_listed", "c7_denominator",
                                                  "below_min_files", "zero_c7_denominator"})
        self.assertTrue(got["2015-03-03"]["below_min_files"])
        self.assertFalse(got["2015-03-03"]["zero_c7_denominator"])
        self.assertFalse(got["2015-03-04"]["below_min_files"])
        self.assertTrue(got["2015-03-04"]["zero_c7_denominator"])
        self.assertEqual(got["2015-03-04"]["c7_denominator"], 0)
        self.assertEqual(rec["zero_c7_denominator_days"], ["2015-03-04"])
        self.assertEqual(rec["missing_count"], 2)
        self.assertEqual(rec["partial_days_count"], 1)      # 72本の日
        self.assertEqual(sorted(fx.opened), sorted(fx.files))  # 3日とも開く（欠けた日も分母を数える）

    def test_translated_only_day_is_missing(self):
        fx = Fixture({"2015-03-02": (96, ONLY_TRANSLATED), "2015-03-03": (96, THEMED),
                      "2015-03-04": (72, NO_THEMES)})
        rec = fx.build()
        self.assertEqual([m["day"] for m in rec["missing_days"]], ["2015-03-02", "2015-03-04"])
        self.assertTrue(all(m["zero_c7_denominator"] for m in rec["missing_days"]))
        self.assertEqual(rec["partial_days_count"], 0)

    def test_same_as_day_is_missing_for_every_count(self):
        for ok in range(0, 97):
            for rows in (THEMED, NO_THEMES):
                fx = Fixture({"2015-03-02": (ok, rows), "2015-03-03": (96, THEMED),
                              "2015-03-04": (96, THEMED)})
                rec = fx.build()
                den = md.c7_denominator(make_day("2015-03-02", rows), "2015-03-02")
                self.assertEqual(rec["missing_count"] == 1, candidates.day_is_missing(ok, den),
                                 (ok, den))


class TestStops(unittest.TestCase):

    def good(self):
        return Fixture({d: (96, THEMED) for d in DAYS3})

    def test_sha256_mismatch_stops(self):
        fx = self.good()
        name = fx.rows[1]["file_name"]
        fx.files[name] = make_day("2015-03-03", NO_THEMES)      # 中身が違う（分母0）
        with self.assertRaisesRegex(md.MissingDaysError, "sha256 が、day の行と一致しない"):
            fx.build()

    def test_absent_file_stops(self):
        fx = self.good()
        del fx.files[fx.rows[2]["file_name"]]
        with self.assertRaisesRegex(md.MissingDaysError, "sha256"):
            fx.build()

    def test_day_mismatch_inside_file_stops(self):
        fx = self.good()
        data = make_day("2015-03-02", THEMED)                     # 別の日の集計を、正しい sha256 で
        fx.files[fx.rows[1]["file_name"]] = data
        fx.rows[1]["sha256"] = hashlib.sha256(data).hexdigest()
        with self.assertRaises(md.counting.CountingError):
            fx.build()

    def test_bad_rows_stop_before_opening_any_file(self):
        def variants():
            fx = self.good()
            fx.rows = fx.rows[:2]
            yield "day の行が無い日", fx
            fx = self.good()
            fx.rows.append(dict(fx.rows[0], day="2015-03-05"))
            yield "区画の外", fx
            fx = self.good()
            fx.rows.append(dict(fx.rows[2]))
            yield "二つある", fx
            fx = self.good()
            fx.rows[2]["run_id"] = "fedcba9876543210"
            yield "run_id が1つでない", fx
            fx = self.good()
            fx.rows[2]["files_ok"], fx.rows[2]["files_listed"] = 90, 80
            yield "files_ok が files_listed より多い", fx
            fx = self.good()
            fx.rows[2]["files_ok"] = fx.rows[2]["files_listed"] = 97
            yield "1日のファイルの数", fx
            fx = self.good()
            fx.rows[2]["files_ok"] = True
            yield "0以上の整数でない", fx
            fx = self.good()
            fx.rows[2]["file_name"] = "../x.tsv.gz"
            yield "file_name が、決まった名前と違う", fx
            fx = self.good()
            fx.rows[2]["sha256"] = "X" * 64
            yield "sha256 の形", fx
            fx = self.good()
            fx.rows[0]["mode"] = "trial"
            yield "official", fx
        for msg, fx in variants():
            with self.assertRaisesRegex(md.MissingDaysError, msg):
                fx.build()
            self.assertEqual(fx.opened, [], msg)

    def test_code_sha_checked(self):
        """T-093：periods・candidates・counting のどれかの sha256 が違えば、何も読まずに止まる。"""
        got = md.check_stats_code()
        self.assertEqual(got, {"src/stats/periods.py": md.PERIODS_SHA256,
                               "src/stats/candidates.py": md.CANDIDATES_SHA256,
                               "src/stats/counting.py": md.COUNTING_SHA256})
        self.assertEqual(md.check_counting(), md.COUNTING_SHA256)
        for i, (rel, _sha, src) in enumerate(md.SEALED_CODE):
            bad = list(md.SEALED_CODE)
            bad[i] = (rel, "0" * 64, src)
            never = mock.Mock(side_effect=AssertionError("照合より前に記録を読んではいけない"))
            with mock.patch.object(md, "SEALED_CODE", tuple(bad)), \
                    mock.patch.object(md._gkg(), "official_day_records", never):
                with self.assertRaisesRegex(md.MissingDaysError, "%s の sha256 が、封印の記録の値と違う"
                                            % re.escape(rel)):
                    md.check_stats_code()
                with self.assertRaisesRegex(md.MissingDaysError, re.escape(rel)):
                    md.official_record("/nonexistent")
            never.assert_not_called()

    def test_module_path_checked(self):
        other = mock.Mock(__file__=os.path.join(PROJECT, "elsewhere", "periods.py"))
        with mock.patch.dict(md._MODULES, {"src/stats/periods.py": other}):
            with self.assertRaisesRegex(md.MissingDaysError, "src/stats/periods.py でない"):
                md.check_stats_code()

    def test_pins_match_real_ledger(self):
        """T-093：SEALED_CODE の値が、本物の封印の記録の該当する欄と同じ（記録は読むだけ）。"""
        sealed = os.path.join(PROJECT, "sealed")
        with open(os.path.join(sealed, "ledger.jsonl"), encoding="utf-8") as f:
            records = [json.loads(l) for l in f if l.strip()]

        def read_1b(r):
            (t,) = r["targets"]
            with open(os.path.join(PROJECT, t["path"]), "rb") as f:
                data = f.read()
            self.assertEqual(hashlib.sha256(data).hexdigest(), t["sha256"])
            return json.loads(data)
        md.check_sealed_code_in_ledger(records, read_1b)
        # 値を一つ変えると止まる。出どころの seq・kind が違っても止まる
        for i, (rel, _sha, src) in enumerate(md.SEALED_CODE):
            bad = list(md.SEALED_CODE)
            bad[i] = (rel, "1" * 64, src)
            with mock.patch.object(md, "SEALED_CODE", tuple(bad)):
                with self.assertRaisesRegex(md.MissingDaysError, re.escape(rel)):
                    md.check_sealed_code_in_ledger(records, read_1b)
        bad = [dict(r) for r in records]
        bad[0]["kind"] = "candidates"
        with self.assertRaisesRegex(md.MissingDaysError, "seq 1 が periods の記録でない"):
            md.check_sealed_code_in_ledger(bad, read_1b)
        with self.assertRaisesRegex(md.MissingDaysError, "seq 6"):
            md.check_sealed_code_in_ledger([r for r in records if r["seq"] != 6], read_1b)

    def test_refs_keys_checked(self):
        fx = Fixture({d: (96, THEMED) for d in DAYS3})
        for refs in ({}, dict(REFS, extra=1), {k: v for k, v in REFS.items() if k != "manifest_sha256"}):
            with self.assertRaisesRegex(md.MissingDaysError, "refs のキー"):
                md.build(fx.rows, BLOCK3, fx.read, refs)
        self.assertEqual(fx.opened, [])

    def test_counting_sha_matches_sealed_order1b(self):
        sealed = os.path.join(PROJECT, "sealed")
        docs = [f for f in os.listdir(sealed) if f.startswith("stats-order1b-") and f.endswith(".json")]
        self.assertEqual(len(docs), 1)
        with open(os.path.join(sealed, docs[0]), encoding="utf-8") as f:
            files = json.load(f)["files"]
        self.assertIn({"path": "src/stats/counting.py", "sha256": md.COUNTING_SHA256}, files)

    def test_store_reader_rejects_paths(self):
        read, opened = md.store_reader(os.environ.get("TMPDIR") or "/tmp")
        for bad in ("../a", "a/b", "", "..", "."):
            with self.assertRaises(md.MissingDaysError):
                read(bad)
        self.assertEqual(opened, [])
        with self.assertRaisesRegex(md.MissingDaysError, "ディレクトリでない"):
            md.store_reader(os.path.join(PROJECT, "no-such-dir"))


class TestOutputShape(unittest.TestCase):

    def test_only_denominators_from_day_files(self):
        fx = Fixture({"2015-03-02": (72, THEMED), "2015-03-03": (71, THEMED),
                      "2015-03-04": (96, NO_THEMES)})
        rec = fx.build()
        self.assertEqual(set(rec), {"label", "block", "rule", "input", "days_in_block", "missing_count",
                                    "missing_days", "zero_c7_denominator_days",
                                    "c7_denominator_by_day", "partial_days_count"})
        self.assertEqual(set(rec["c7_denominator_by_day"]), set(DAYS3))
        text = md.canonical_bytes(rec).decode("utf-8")
        for theme in ("ZZA", "ZZB"):
            self.assertNotIn(theme, text)       # テーマの名前もテーマごとの数も出さない
        # 日の集計から来る数は、C7 の分母だけ
        from_files = [rec["c7_denominator_by_day"][d] for d in DAYS3]
        self.assertEqual(from_files, [md.c7_denominator(fx.files[r["file_name"]], r["day"])
                                      for r in fx.rows])
        for m in rec["missing_days"]:
            self.assertEqual(m["c7_denominator"], rec["c7_denominator_by_day"][m["day"]])

    def test_output_same_as_plain_import(self):
        """T-096：照合したバイト列から読み込んだモジュールでも、ふつうに import したモジュール（T-093 の
        実行と同じ読み込み方。本物の src/stats に .pyc は無い）でも、出力のバイト列は同じ。"""
        import periods as plain_periods
        fx = Fixture({"2015-03-02": (72, THEMED), "2015-03-03": (71, THEMED),
                      "2015-03-04": (96, NO_THEMES)})
        a = md.canonical_bytes(fx.build())
        with mock.patch.object(md, "counting", counting), mock.patch.object(md, "candidates", candidates), \
                mock.patch.object(md, "periods", plain_periods):
            b = md.canonical_bytes(fx.build())
        self.assertIsNot(md.counting, counting)
        self.assertEqual(a, b)

    def test_canonical_json_and_sha256(self):
        fx = Fixture({d: (96, THEMED) for d in DAYS3})
        a = fx.build()
        fx.rows.reverse()
        b = fx.build()
        self.assertEqual(md.canonical_bytes(a), md.canonical_bytes(b))
        self.assertEqual(md.sha256_of(a), hashlib.sha256(md.canonical_bytes(a)).hexdigest())
        text = md.canonical_bytes(a).decode("utf-8")
        self.assertEqual(text, json.dumps(json.loads(text), ensure_ascii=False, sort_keys=True,
                                          indent=2) + "\n")

    def test_label_matches_doc(self):
        with open(DOC, encoding="utf-8") as f:
            doc = f.read()
        labels = set(re.findall(r"missing-days-method-v\d+", doc))
        self.assertIn(md.LABEL, labels)
        # T-096：今の版を書く3か所が、どれも LABEL と同じ
        heads = re.findall(r"^文書の版：`(missing-days-method-v\d+)`", doc, re.M)
        self.assertEqual(heads, [md.LABEL])
        rows = re.findall(r"^\| `label` \| `(missing-days-method-v\d+)`", doc, re.M)
        self.assertEqual(rows, [md.LABEL])
        this = re.findall(r"(v\d+) はこの版", doc)
        self.assertEqual(["missing-days-method-" + v for v in this], [md.LABEL])
        # 文書に出てくるほかの版は、今の版より小さい番号だけ
        cur = int(md.LABEL.rsplit("v", 1)[1])
        for v in re.findall(r"\bv(\d+) は", doc):
            self.assertLessEqual(int(v), cur)

    def test_method_block_matches_periods_and_gkg(self):
        self.assertEqual(md.method_block(), (D(2015, 3, 2), D(2020, 12, 14)))


class TestStalePycIgnored(unittest.TestCase):
    """T-096：__pycache__ に中身の違う古い .pyc があっても、照合したバイト列のコードが動く。
    写し（一時的なディレクトリ）の中で確かめる。本物の src/stats には .pyc を置かない。"""

    NAMES = ("periods", "candidates", "counting")

    def setUp(self):
        import py_compile
        import shutil
        import tempfile
        self.tmp = tempfile.mkdtemp(prefix="md-pyc-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.stats = os.path.join(self.tmp, "src", "stats")
        os.makedirs(os.path.join(self.stats, "__pycache__"))
        for n in ("missing_days",) + self.NAMES:
            shutil.copyfile(os.path.join(SRC, n + ".py"), os.path.join(self.stats, n + ".py"))
        # 中身の違う版（STALE_PYC を足したもの）を、元のソースを確かめない形の .pyc にして置く
        for n in self.NAMES:
            with open(os.path.join(SRC, n + ".py"), "rb") as f:
                src = f.read() + b"\nSTALE_PYC = True\n"
            alt = os.path.join(self.tmp, n + "_stale.py")
            with open(alt, "wb") as f:
                f.write(src)
            cfile = os.path.join(self.stats, "__pycache__",
                                 "%s.%s.pyc" % (n, sys.implementation.cache_tag))
            py_compile.compile(alt, cfile=cfile, doraise=True,
                               invalidation_mode=py_compile.PycInvalidationMode.UNCHECKED_HASH)

    def run_py(self, code):
        import subprocess
        r = subprocess.run([sys.executable, "-B", "-c", code], capture_output=True, cwd=self.tmp,
                           env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
        self.assertEqual(r.returncode, 0, r.stderr.decode(errors="replace"))
        return json.loads(r.stdout.decode())

    def test_plain_import_would_use_stale_pyc(self):
        """前提の確かめ：ふつうの import（-B を付けても）は、古い .pyc を読む。"""
        got = self.run_py("import sys, json; sys.path.insert(0, %r)\n"
                          "import periods, candidates, counting\n"
                          "print(json.dumps([hasattr(m, 'STALE_PYC') for m in (periods, candidates, counting)]))"
                          % self.stats)
        self.assertEqual(got, [True, True, True])

    def test_missing_days_runs_verified_bytes(self):
        got = self.run_py("import sys, json; sys.path.insert(0, %r)\n"
                          "import missing_days as md\n"
                          "md.check_stats_code()\n"
                          "print(json.dumps([hasattr(md.periods, 'STALE_PYC'), hasattr(md.candidates, 'STALE_PYC'),"
                          " hasattr(md.counting, 'STALE_PYC'), hasattr(md.candidates.periods, 'STALE_PYC'),"
                          " md.candidates.periods is md.periods, 'periods' in sys.modules,"
                          " sorted(md._LOADED_SHA.values()) == sorted(s for _r, s, _x in md.SEALED_CODE)]))"
                          % self.stats)
        self.assertEqual(got, [False, False, False, False, True, False, True])


class TestSourceShape(unittest.TestCase):
    """コードの形：day の行の入口は official_day_records だけ。マニフェストを直に読まない。"""

    def test_only_entry_is_official_day_records(self):
        with open(SCRIPT, encoding="utf-8") as f:
            src = f.read()
        self.assertIn("_gkg().official_day_records()", src)
        for bad in ("_day_records_of", "read_jsonl", "gdelt-gkg-method", "urllib", "socket",
                    "LACIE"):
            self.assertNotIn(bad, src.split('"""', 2)[2], bad)
        body = inspect.getsource(md.official_record).split('"""', 2)[2]
        self.assertLess(body.index("check_stats_code()"), body.index("official_day_records()"))
        self.assertLess(body.index("official_day_records()"), body.index("sealed_refs("))
        self.assertLess(body.index("sealed_refs("), body.index("store_reader("))

    def test_main_rejects_bad_args(self):
        for argv in ([], ["--sha256"], ["--store"], ["--store", "x", "--y"], ["--x", "y"]):
            self.assertEqual(md.main(argv), 2, argv)


def _load_e2e():
    if COLLECTOR_TESTS not in sys.path:
        sys.path.insert(0, COLLECTOR_TESTS)
    import test_acquire_gkg  # noqa: E402
    return test_acquire_gkg


tag = _load_e2e()
taf, tg, ledger = tag.taf, tag.tg, tag.ledger


class TestGateEndToEnd(tag.E2ECase):
    """合成の正式な run（3日：72本・71本・72本でテーマの付かない文書だけ）を写しの中で作り、
    関門を通して、収集係のコードが書いた日の集計から一覧を作る。"""

    COUNTS = {"20150302": 72, "20150303": 71, "20150304": 72}

    def rows_of(self, d, ts):
        if d == "20150304":
            return [tg.gkg_row(ts, i, themes1=(), themes2=()) for i in (1, 2)]
        return tg.standard_rows(ts)

    def setUp(self):
        # E2ECase.setUp と同じ手順で、日ごとの15分ファイルの本数と文書だけを変える
        taf.CopyCase.setUp(self)
        self.fs_check = lambda v: None
        self.gdrand = taf.FakeDrand(tg.NOW)
        self.gots = taf.FakeOts()
        self.zips = {}
        for d in self.DAYS:
            for i in range(self.COUNTS[d]):
                ts = tg.ts_of(d, i)
                self.zips[ts] = tg.make_zip(ts, self.rows_of(d, ts))
        lines = ["%d %s http://data.gdeltproject.org/gdeltv2/%s.gkg.csv.zip"
                 % (len(z), hashlib.md5(z).hexdigest(), ts) for ts, z in sorted(self.zips.items())]
        body = ("\n".join(lines) + "\n").encode()
        self.transport = tag.tf.FakeTransport(tag.tf.FakeResponse(body))
        taf.acq._acquire(_test=self.seams())
        self.order1_seq = tag.add_order_record(self.project, ledger.ORDER1_KIND, taf.NOW)
        self.order1b_seq = tag.add_order_record(self.project, ledger.ORDER1B_KIND, taf.NOW)
        self.volume = self.make_volume()
        self.gkg_store = os.path.join(self.volume, *tag.gkg.STORE_PARTS)
        os.makedirs(self.gkg_store)
        self.trial_store = os.path.join(self.volume, *tag.gkg.TRIAL_STORE_PARTS)
        os.makedirs(self.trial_store)
        self.check_volume = tag.fake_check_volume
        self.gkg_logs = []
        self.clock = tg.FakeClock()

    def full_official(self):
        self.add_method_access()
        out = self.acquire_official(self.gseams())
        self.commit_manifest("正式な run の結果")
        return out

    def seal_result(self, run_id):
        tag.seal_gkg_result.seal(self.project, "official", run_id, tg.NOW, "ots",
                                 runner=taf.FakeOts())
        taf.git(self.project, "add", "-A", "sealed")
        taf.git(self.project, "commit", "-q", "-m", "gkg-run-result")

    def entry(self, opened=None):
        return self.run_with_root(md.official_record, self.gkg_store, BLOCK3, opened)

    def test_stops_without_gate_then_passes(self):
        out = self.full_official()
        g = md._gkg()
        calls = []
        real_gate = ledger.require_gkg_run_result

        def gate(mode, run_id):
            calls.append((mode, run_id))
            return real_gate(mode, run_id)
        never = mock.Mock(side_effect=AssertionError("関門より前にマニフェストや日の集計を読んではいけない"))
        with mock.patch.object(ledger, "require_gkg_run_result", gate), \
                mock.patch.object(g, "read_bytes_nofollow", never):
            with self.assertRaises(g.GkgError) as cm:
                self.entry()
            self.assertEqual(self.run_with_root(md.main, ["--store", self.gkg_store, "--sha256"]), 1)
        never.assert_not_called()
        self.assertRegex(str(cm.exception), "gkg-run-result の関門を通らない")
        self.assertIsInstance(cm.exception.__cause__, ledger.GkgRunResultRequired)
        self.assertEqual(calls[0], ("official", out["run_id"]))

        self.seal_result(out["run_id"])
        # 写しの順番1b（seq 6）は仮の中身なので、counting.py の値と照らすと止まる（日の集計は開かない）
        opened = []
        with self.assertRaisesRegex(md.MissingDaysError, r"src/stats/counting.py の sha256 が、seq 6"):
            self.entry(opened)
        self.assertEqual(opened, [])
        # 写しでは、本物と同じ seq 1・2（periods・candidates）の照合だけを残して流す
        opened = []
        with mock.patch.object(md, "SEALED_CODE", md.SEALED_CODE[:2]), \
                mock.patch.object(ledger, "require_gkg_run_result", gate), OpenRecorder() as rec:
            got = self.entry(opened)
        self.assertEqual(calls[-1], ("official", out["run_id"]))
        names = [counting.day_file_name("official", out["run_id"], d) for d in DAYS3]
        self.assertEqual(opened, names)
        # 保存先で開いたのは、day の行の日の集計だけ。取得の記録やほかのファイルは開かない
        in_store = [p for p in rec.paths if os.path.abspath(p).startswith(self.volume)]
        self.assertEqual(sorted(os.path.basename(p) for p in in_store), sorted(names))
        self.assertFalse(any(os.path.abspath(p).startswith(self.home) for p in rec.paths))
        self.assertEqual(got["input"]["run_id"], out["run_id"])
        # gkg-run-result の記録の参照と、使ったマニフェストの sha256（T-093）
        led = ledger.verify_chain(ledger.read_ledger(os.path.join(self.project, "sealed", "ledger.jsonl")))
        (res,) = [r for r in led if r["kind"] == ledger.GKG_RESULT_KIND and r["seq"] == got["input"]["gkg_run_result_seq"]]
        self.assertEqual(got["input"]["gkg_run_result_record_sha256"],
                         hashlib.sha256(ledger.canonical_line(res)).hexdigest())
        mpath = os.path.join(self.project, *got["input"]["manifest_path"].split("/"))
        with open(mpath, "rb") as f:
            mlines = f.read().splitlines(keepends=True)
        self.assertEqual(hashlib.sha256(b"".join(mlines[:got["input"]["manifest_lines"]])).hexdigest(),
                         got["input"]["manifest_sha256"])
        self.assertEqual([(m["day"], m["files_ok"], m["below_min_files"], m["zero_c7_denominator"])
                          for m in got["missing_days"]],
                         [("2015-03-03", 71, True, False), ("2015-03-04", 72, False, True)])
        self.assertEqual(got["zero_c7_denominator_days"], ["2015-03-04"])
        self.assertGreater(got["c7_denominator_by_day"]["2015-03-02"], 0)
        self.assertEqual(got["partial_days_count"], 1)

        # 保存先の日の集計を書き換えると、sha256 で止まる
        path = os.path.join(self.gkg_store, names[0])
        with open(path, "rb") as f:
            body = f.read()
        with open(path, "wb") as f:
            f.write(make_day("2015-03-02", THEMED))
        with mock.patch.object(md, "SEALED_CODE", md.SEALED_CODE[:2]):
            with self.assertRaisesRegex(md.MissingDaysError, "sha256 が、day の行と一致しない"):
                self.entry()
        with open(path, "wb") as f:
            f.write(body)
        with mock.patch.object(md, "SEALED_CODE", md.SEALED_CODE[:2]):
            self.assertEqual(md.sha256_of(self.entry()), md.sha256_of(got))


class TestRealManifestRows(unittest.TestCase):
    """本物のマニフェスト（seq 12）で、day の行の検査だけを流す。日の集計は開かない。
    件数や日付はここでは固定しない（規則を結果に合わせて動かさないため）。"""

    def test_real_rows(self):
        if not os.path.exists(os.path.join(PROJECT, "data", "manifest", "gdelt-gkg-method.jsonl")):
            self.skipTest("マニフェストが無い")
        with OpenRecorder() as rec:
            want, rows, run_id = md.check_rows(md._gkg().official_day_records(), md.method_block())
        for p in rec.paths:
            ap = os.path.abspath(p)
            self.assertTrue(ap.startswith(PROJECT + os.sep), p)
            self.assertFalse(ap.endswith(".tsv.gz"), p)
        self.assertEqual(len(want), 2115)
        self.assertEqual(len(rows), 2115)
        self.assertEqual(run_id, "4199ae53d35b918a")


if __name__ == "__main__":
    unittest.main()
