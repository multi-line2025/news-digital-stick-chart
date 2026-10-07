"""報道量の数え方の候補と、選ぶ基準の案のテスト（T-028。src/stats/counting.py、docs/stats/counting.md）。

実行（プロジェクトのルートで）:
    PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -B -m unittest discover -s tests/stats -v

データもネットワークも使わない。GKG の行は、このテストの中で作る合成の行で、テーマの名前は
実在の区分表から取ったものではない（ZZ で始まる作り物）。日の集計は、収集係の
src/collector/gkg.py の add_line と serialize_day で作る（読むだけ。収集係のコードは変えない）。
これで、候補が収集係の集計の形から計算できることを確かめる。
"""

import ast
import gzip
import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from fractions import Fraction as Fr

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(os.path.dirname(HERE))
SRC = os.path.join(PROJECT, "src", "stats")
DOC = os.path.join(PROJECT, "docs", "stats", "counting.md")
sys.path.insert(0, SRC)

import counting  # noqa: E402


def _load_gkg():
    path = os.path.join(PROJECT, "src", "collector", "gkg.py")
    spec = importlib.util.spec_from_file_location("gkg_for_counting_test", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


gkg = _load_gkg()

FT = {"2015-03-02": "20150302120000", "2015-03-03": "20150303120000", "2015-03-04": "20150304120000"}


def gkg_line(file_time, n, coll="1", v1="", v2="", translated=False):
    cols = [b""] * gkg.N_COLUMNS
    cols[gkg.I_ID] = ("%s-%s%d" % (file_time, "T" if translated else "", n)).encode()
    cols[gkg.I_D21] = file_time.encode()
    cols[gkg.I_COLL] = coll.encode()
    cols[gkg.I_V1T] = v1.encode()
    cols[gkg.I_V2T] = v2.encode()
    return b"\t".join(cols) + b"\n"


def make_day(day, rows, mode="trial"):
    """rows: [(coll, v1, v2, translated)] の文書。gkg.serialize_day の形の gzip のバイト列を返す。"""
    ft = FT[day]
    agg = gkg.Agg()
    vocab = {}
    for i, (coll, v1, v2, tr) in enumerate(rows):
        gkg.add_line(agg, gkg_line(ft, i, coll, v1, v2, tr), ft.encode(), vocab)
    files = [{"file_time": ft, "result": "ok", "reason": None, "md5": "0" * 32, "size": 1,
              "sha256": "0" * 64, "attempts": 1, "docs": {g.decode(): n for g, n in agg.docs.items()}}]
    data = gkg.serialize_day(day, agg, files, mode)
    gkg.check_output_bytes(data, "テストの日の集計")
    return gkg.gzip_bytes(data)


# 1日分の基本の文書。V1 と V2 の付き方を少し変えてある。
BASE_ROWS = [
    ("1", "ZZA;ZZB", "ZZA,10;ZZA,40;ZZB,5", False),     # V2 で ZZA は2回
    ("1", "ZZA", "ZZA,3", False),
    ("2", "ZZB;ZZC", "ZZC,8", False),                   # V2 に ZZB が無い
    ("1", "", "ZZD,1", False),                          # V1 にテーマが無い
    ("1", "", "", False),                               # どちらにも無い
    ("1", "ZZA", "ZZA,1;ZZA,2;ZZA,3", True),            # 翻訳の印（数えない）
    ("X1", "ZZC", "ZZC,4", False),                      # 組の形が違う（X。数える）
]


def base_summaries(rows_by_day=None):
    out = []
    for d in counting.TRIAL_DAYS:
        rows = BASE_ROWS if rows_by_day is None else rows_by_day[d]
        out.append(counting.parse_day(make_day(d, rows), expect_day=d, expect_mode="trial"))
    return out


class TestFormatAgreesWithCollector(unittest.TestCase):
    def test_trial_days(self):
        self.assertEqual(counting.TRIAL_DAYS, gkg.TRIAL_DAYS)

    def test_day_file_name(self):
        for d in counting.TRIAL_DAYS:
            self.assertEqual(counting.trial_day_file_name("0123456789abcdef", d),
                             gkg.day_file_name("0123456789abcdef", d, "trial"))

    def test_day_format(self):
        self.assertEqual(gkg.DAY_FORMAT, ("%s\t%s" % (counting.DAY_FORMAT_NAME,
                                                      counting.DAY_FORMAT_VERSION)).encode())

    def test_manifest_path(self):
        self.assertEqual("/".join(gkg.MANIFEST_DIR_PARTS + (gkg.TRIAL_MANIFEST_NAME,)),
                         counting.TRIAL_MANIFEST_PATH)

    def test_s_names_exist_in_collector(self):
        with open(os.path.join(PROJECT, "src", "collector", "gkg.py"), encoding="utf-8") as f:
            src = f.read()
        for name in counting.S_UNCOVERED.values():
            self.assertIn('st["%s"]' % name, src)


class TestCandidates(unittest.TestCase):
    """各候補を、収集係の形の日の集計から計算できること（手で数えた値と一致）。"""

    def test_all_candidates_from_collector_format(self):
        s = base_summaries()[0]
        # 数える組：1・2・X（"X1" は形が違うので X になる）。翻訳の 1T は数えない。
        self.assertEqual(sorted(s["docs"]), ["1", "1T", "2", "X"])
        expect = {
            "C1": ({"ZZA": 2, "ZZB": 2, "ZZC": 2}, 6),
            "C2": ({"ZZA": 2, "ZZB": 2, "ZZC": 2}, 6),
            "C3": ({"ZZA": 2, "ZZB": 1, "ZZC": 2, "ZZD": 1}, 6),
            "C4": ({"ZZA": 2, "ZZB": 1, "ZZC": 2, "ZZD": 1}, 6),
            "C5": ({"ZZA": 3, "ZZB": 1, "ZZC": 2, "ZZD": 1}, 6),
            "C6": ({"ZZA": 3, "ZZB": 1, "ZZC": 2, "ZZD": 1}, 7),
        }
        for cid in counting.CANDIDATE_IDS:
            with self.subTest(cid=cid):
                self.assertEqual(counting.candidate_counts(s, cid), expect[cid])

    def test_translated_groups_never_counted(self):
        rows = [("1", "ZZA", "ZZA,1", True)] * 3
        s = counting.parse_day(make_day("2015-03-02", rows))
        for cid in counting.CANDIDATE_IDS:
            self.assertEqual(counting.candidate_counts(s, cid), ({}, 0))
        self.assertFalse(counting.counted_group("1T"))
        self.assertFalse(counting.counted_group("XT"))
        self.assertTrue(counting.counted_group("X"))
        self.assertTrue(counting.counted_group("12"))

    def test_counts_are_nonnegative_ints(self):
        s = base_summaries()[0]
        for cid in counting.CANDIDATE_IDS:
            counts, total = counting.candidate_counts(s, cid)
            self.assertIsInstance(total, int)
            for v in counts.values():
                self.assertIsInstance(v, int)
                self.assertGreater(v, 0)

    def test_unknown_candidate(self):
        with self.assertRaises(ValueError):
            counting.candidate_counts(base_summaries()[0], "C7")

    def test_candidate_table(self):
        self.assertEqual(counting.CANDIDATE_IDS, ("C1", "C2", "C3", "C4", "C5", "C6"))
        cols = {c[1] for c in counting.CANDIDATES}
        self.assertEqual(cols, set(counting.COLUMNS))
        self.assertEqual({(c[1], c[2]) for c in counting.CANDIDATES},
                         {(a, b) for a in counting.COLUMNS for b in counting.DENOMINATORS})


class TestParseDay(unittest.TestCase):
    def test_header_checks(self):
        gz = make_day("2015-03-02", BASE_ROWS)
        with self.assertRaises(counting.CountingError):
            counting.parse_day(gz, expect_day="2015-03-03")
        with self.assertRaises(counting.CountingError):
            counting.parse_day(gz, expect_mode="official")
        with self.assertRaises(counting.CountingError):
            counting.parse_day(b"not gzip")
        bad = gzip.compress(b"#\tgkg-day\t1\t2015-03-02\ttrial\n", mtime=0)
        with self.assertRaises(counting.CountingError):
            counting.parse_day(bad)

    def _raw(self, body):
        return gzip.compress(b"#\tgkg-day\t2\t2015-03-02\ttrial\n" + body, mtime=0)

    def test_malformed_rows(self):
        cases = [
            b"V\t0\tZZA\nV\t0\tZZB\n",                      # 番号の重なり
            b"D\t1\t3\nD\t1\t4\n",                          # 組の重なり
            b"V\t0\tZZA\nD\t1\t3\nT\t1\t1\t1\t1\n",         # 欄の数
            b"V\t0\tZZA\nD\t1\t3\nT\t1\t5\t1\t1\t1\n",      # V に無い番号
            b"V\t0\tZZA\nD\t1\t3\nT\t2\t0\t1\t1\t1\n",      # D に無い組
            b"V\t0\tZZA\nD\t1\t3\nT\t1\t0\t1\t1\t1\nT\t1\t0\t1\t1\t1\n",   # 重なり
            b"V\t0\tZZA\nD\t1\t-3\n",                       # 負の数
            b"S\ta\t1\nS\ta\t2\n",                          # S の重なり
        ]
        for body in cases:
            with self.subTest(body=body):
                with self.assertRaises(counting.CountingError):
                    counting.parse_day(self._raw(body))

    def test_ignores_other_tables(self):
        s = base_summaries()[0]
        self.assertIn("docs_without_v1_theme", s["stats"])


def rows_with(v1_uncovered, v2_uncovered, both=4):
    """V1 だけが無い文書 v1_uncovered 本、V2 だけが無い文書 v2_uncovered 本、両方ある文書 both 本。"""
    rows = [("1", "ZZA", "ZZA,1", False)] * both
    rows += [("1", "", "ZZA,1", False)] * v1_uncovered
    rows += [("1", "ZZA", "", False)] * v2_uncovered
    return {d: rows for d in counting.TRIAL_DAYS}


class TestCriteria(unittest.TestCase):
    def test_b1_b2_field_choice(self):
        for u1, u2, b1, b2 in ((1, 2, "C2", "C1"), (2, 1, "C4", "C3"), (2, 2, "C2", "C1")):
            with self.subTest(u1=u1, u2=u2):
                s = base_summaries(rows_with(u1, u2))
                self.assertEqual(counting.criterion_b1(s)["candidate"], b1)
                self.assertEqual(counting.criterion_b2(s)["candidate"], b2)

    def test_b1_none_when_no_themed_docs(self):
        rows = {d: [("1", "", "", False)] * 3 for d in counting.TRIAL_DAYS}
        s = base_summaries(rows)
        self.assertIsNone(counting.criterion_b1(s)["candidate"])
        self.assertIsNone(counting.criterion_b2(s)["candidate"])
        self.assertIsNone(counting.criterion_b3(s)["candidate"])

    def test_b1_none_when_candidate_not_usable_on_a_day(self):
        rows = rows_with(0, 1)
        rows["2015-03-03"] = [("1", "", "ZZA,1", False)]     # この日だけ V1 が空
        s = base_summaries(rows)
        # 3日の和：V1 の付かない文書 0+1+0=1、V2 の付かない文書 1+0+1=2 → 欄は V1、候補は C2。
        # 2日目は C2 の分子が 0 なので、使えない → 該当なし（ほかの候補に代えない）
        r1 = counting.criterion_b1(s)
        self.assertEqual((r1["values"]["docs_without_v1_theme"], r1["values"]["docs_without_v2_theme"]), (1, 2))
        self.assertIsNone(r1["candidate"])
        self.assertEqual(r1["reason"], "not_usable")
        self.assertIsNone(counting.criterion_b3(s)["candidate"])

    def test_b3_fixed(self):
        self.assertEqual(counting.criterion_b3(base_summaries())["candidate"], "C1")

    def test_b4_spread(self):
        # 1文書あたりの V1 のテーマ数：1日目 1、2日目 q、3日目 1
        def rows(themes_day2_num, docs_day2_den):
            out = {}
            for d in counting.TRIAL_DAYS:
                out[d] = [("1", "ZZA", "ZZA,1", False)] * 10
            # 2日目：10文書のうち、ZZB も付く文書の数を変える
            out["2015-03-03"] = ([("1", "ZZA;ZZB", "ZZA,1", False)] * themes_day2_num
                                 + [("1", "ZZA", "ZZA,1", False)] * (docs_day2_den - themes_day2_num))
            return out
        # q = 11/10 ちょうど（上限と等しい）→ C1
        s = base_summaries(rows(1, 10))
        r = counting.criterion_b4(s)
        self.assertEqual(r["values"]["spread"], "11/10")
        self.assertEqual(r["candidate"], "C1")
        # q = 12/10 → C2
        s = base_summaries(rows(2, 10))
        self.assertEqual(counting.criterion_b4(s)["candidate"], "C2")

    def test_b4_none(self):
        rows = {d: [("1", "", "ZZA,1", False)] * 3 for d in counting.TRIAL_DAYS}
        self.assertIsNone(counting.criterion_b4(base_summaries(rows))["candidate"])
        rows = {d: [("1T", "ZZA", "ZZA,1", True)] * 3 for d in counting.TRIAL_DAYS}
        r = counting.criterion_b4(base_summaries(rows))
        self.assertIsNone(r["candidate"])
        self.assertEqual(r["reason"], "no_docs")

    def test_b5_ratio(self):
        def rows(extra_mentions):
            out = {}
            for d in counting.TRIAL_DAYS:
                out[d] = [("1", "ZZA", "ZZA,1", False)] * 20
            out["2015-03-02"] = ([("1", "ZZA", "ZZA,1;ZZA,2", False)] * extra_mentions
                                 + [("1", "ZZA", "ZZA,1", False)] * (20 - extra_mentions))
            return out
        # 文書 60、言及 60 + 3 → 63/60 = 21/20（等しい）→ C4
        r = counting.criterion_b5(base_summaries(rows(3)))
        self.assertEqual(r["values"]["ratio"], "21/20")
        self.assertEqual(r["candidate"], "C4")
        r = counting.criterion_b5(base_summaries(rows(4)))
        self.assertEqual(r["candidate"], "C6")
        rows0 = {d: [("1", "ZZA", "", False)] for d in counting.TRIAL_DAYS}
        self.assertIsNone(counting.criterion_b5(base_summaries(rows0))["candidate"])

    def test_every_criterion_outputs_one_candidate_or_none(self):
        variants = [None, rows_with(1, 2), rows_with(2, 1), rows_with(3, 3)]
        for v in variants:
            s = base_summaries(v)
            out = counting.apply_all(s)
            self.assertEqual(list(out), list(counting.CRITERIA_IDS))
            for bid, r in out.items():
                self.assertTrue(r["candidate"] is None or r["candidate"] in counting.CANDIDATE_IDS, bid)
                self.assertEqual(r, counting.CRITERIA[bid](s) | {"official": bid == counting.OFFICIAL_CRITERION})

    def test_input_must_be_trial_days_in_order(self):
        s = base_summaries()
        for bid in counting.CRITERIA_IDS:
            with self.assertRaises(counting.CountingError):
                counting.CRITERIA[bid](list(reversed(s)))
            with self.assertRaises(counting.CountingError):
                counting.CRITERIA[bid](s[:2])

    def test_criteria_do_not_take_tag_list(self):
        """基準は、日の集計（summaries）だけを引数に取る。タグの一覧は受け取れない。"""
        import inspect
        for bid, fn in counting.CRITERIA.items():
            self.assertEqual(list(inspect.signature(fn).parameters), ["summaries"], bid)

    def test_official_undecided(self):
        self.assertIsNone(counting.OFFICIAL_CRITERION)
        self.assertEqual(counting.official_criterion_status(), "undecided")
        self.assertIn(counting.RECOMMENDED_CRITERION, counting.CRITERIA_IDS)


RID = "0123456789abcdef"
RID2 = "fedcba9876543210"


def manifest(rows):
    return b"".join(json.dumps(r, sort_keys=True).encode() + b"\n" for r in rows)


def trial_rows(rid, days, complete=True, shas=None):
    out = [{"kind": "run-start", "run_id": rid, "mode": "trial", "trial": True, "official": False}]
    for d in days:
        sha = (shas or {}).get(d, hashlib.sha256(d.encode()).hexdigest())
        out.append({"kind": "day", "run_id": rid, "mode": "trial", "day": d,
                    "file_name": counting.trial_day_file_name(rid, d), "sha256": sha})
    if complete:
        out.append({"kind": "run-complete", "run_id": rid, "mode": "trial"})
    return out


class TestTrialInputRule(unittest.TestCase):
    def test_normal(self):
        sel = counting.select_trial_input(manifest(trial_rows(RID, counting.TRIAL_DAYS)))
        self.assertEqual(sel["run_id"], RID)
        self.assertEqual([d["day"] for d in sel["days"]], list(counting.TRIAL_DAYS))

    def test_first_run_start_only(self):
        # 最初の run が終わっていなければ、あとの完了した run があっても代えずに止まる
        m = manifest(trial_rows(RID, counting.TRIAL_DAYS[:1], complete=False)
                     + trial_rows(RID2, counting.TRIAL_DAYS))
        with self.assertRaises(counting.CountingError):
            counting.select_trial_input(m)
        # 最初の run が終わっていれば、あとの run は使わない
        m = manifest(trial_rows(RID, counting.TRIAL_DAYS) + trial_rows(RID2, counting.TRIAL_DAYS))
        self.assertEqual(counting.select_trial_input(m)["run_id"], RID)

    def test_rejections(self):
        good = trial_rows(RID, counting.TRIAL_DAYS)
        cases = {
            "no_start": [r for r in good if r["kind"] != "run-start"],
            "missing_day": [r for r in good if r.get("day") != "2015-03-03"],
            "dup_day": good[:2] + [good[1]] + good[2:],
            "other_day": good + [dict(good[1], day="2015-03-05",
                                      file_name=counting.trial_day_file_name(RID, "2015-03-05"))],
            "bad_name": [dict(r, file_name="x.tsv.gz") if r["kind"] == "day" else r for r in good],
            "bad_mode": [dict(r, mode="official") if r["kind"] == "day" else r for r in good],
            "start_not_trial": [dict(r, trial=False) if r["kind"] == "run-start" else r for r in good],
            "bad_sha": [dict(r, sha256="0") if r["kind"] == "day" else r for r in good],
            "bad_run_id": [dict(r, run_id="xyz") for r in good],
        }
        for name, rows in cases.items():
            with self.subTest(name=name):
                with self.assertRaises(counting.CountingError):
                    counting.select_trial_input(manifest(rows))
        with self.assertRaises(counting.CountingError):
            counting.select_trial_input(b"{not json\n")

    def test_prefix_versions(self):
        head = manifest(trial_rows(RID, counting.TRIAL_DAYS))
        counting.check_prefix_versions(head, [b"", head[:10], head])
        with self.assertRaises(counting.CountingError):
            counting.check_prefix_versions(head, [b"x" + head[1:20]])


class TestApply(unittest.TestCase):
    def _inputs(self):
        files = {}
        shas = {}
        for d in counting.TRIAL_DAYS:
            gz = make_day(d, BASE_ROWS)
            files[counting.trial_day_file_name(RID, d)] = gz
            shas[d] = hashlib.sha256(gz).hexdigest()
        return manifest(trial_rows(RID, counting.TRIAL_DAYS, shas=shas)), files

    def test_apply(self):
        m, files = self._inputs()
        out = counting.apply_to_inputs(m, files.__getitem__)
        self.assertEqual(out["trial_run_id"], RID)
        self.assertEqual(out["official_criterion_status"], "undecided")
        self.assertEqual(set(out["results"]), set(counting.CRITERIA_IDS))
        self.assertEqual(out, counting.apply_to_inputs(m, files.__getitem__))

    def test_sha_mismatch_stops(self):
        m, files = self._inputs()
        name = counting.trial_day_file_name(RID, "2015-03-03")
        files[name] = make_day("2015-03-03", BASE_ROWS[:3])
        with self.assertRaises(counting.CountingError):
            counting.apply_to_inputs(m, files.__getitem__)

    def test_wrong_day_in_file_stops(self):
        m, files = self._inputs()
        # 2日目の名前に1日目の中身を置き、sha256 もそれに合わせたマニフェスト
        a = counting.trial_day_file_name(RID, "2015-03-02")
        b = counting.trial_day_file_name(RID, "2015-03-03")
        files[b] = files[a]
        rows = [dict(r, sha256=hashlib.sha256(files[r["file_name"]]).hexdigest()) if r["kind"] == "day" else r
                for r in json_rows(m)]
        with self.assertRaises(counting.CountingError):
            counting.apply_to_inputs(manifest(rows), files.__getitem__)

    def test_cli(self):
        m, files = self._inputs()
        with tempfile.TemporaryDirectory() as d:
            mp = os.path.join(d, "trial.jsonl")
            with open(mp, "wb") as f:
                f.write(m)
            for name, gz in files.items():
                with open(os.path.join(d, name), "wb") as f:
                    f.write(gz)
            env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
            r = subprocess.run([sys.executable, "-B", os.path.join(SRC, "counting.py"), "apply", mp, d],
                               capture_output=True, env=env, cwd=PROJECT)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(json.loads(r.stdout), counting.apply_to_inputs(m, files.__getitem__))
            r = subprocess.run([sys.executable, "-B", os.path.join(SRC, "counting.py"), "apply", mp,
                                os.path.join(d, "nowhere")], capture_output=True, env=env, cwd=PROJECT)
            self.assertEqual(r.returncode, 1)


def json_rows(m):
    return [json.loads(x) for x in m.splitlines() if x.strip()]


class TestRecordAndDoc(unittest.TestCase):
    def test_cli_record_deterministic(self):
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
        outs = [subprocess.run([sys.executable, "-B", os.path.join(SRC, "counting.py")],
                               capture_output=True, env=env, cwd=PROJECT).stdout for _ in range(2)]
        self.assertEqual(outs[0], outs[1])
        self.assertEqual(outs[0].decode("utf-8"), counting.canonical_json())
        rec = json.loads(outs[0])
        self.assertEqual([c["id"] for c in rec["candidates"]], list(counting.CANDIDATE_IDS))
        self.assertEqual(rec["official_criterion_status"], "undecided")

    def test_cli_rejects_args(self):
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
        r = subprocess.run([sys.executable, "-B", os.path.join(SRC, "counting.py"), "x"],
                           capture_output=True, env=env, cwd=PROJECT)
        self.assertEqual(r.returncode, 2)

    def _table(self, name):
        with open(DOC, encoding="utf-8") as f:
            lines = f.read().split("\n")
        i = lines.index("<!-- table:%s -->" % name)
        rows = []
        for line in lines[i + 3:]:
            if not line.startswith("|"):
                break
            rows.append([c.strip() for c in line.strip("|").split("|")])
        return rows

    def test_doc_candidate_table(self):
        rows = self._table("candidates")
        self.assertEqual([r[0] for r in rows], ["`%s`" % c for c in counting.CANDIDATE_IDS])
        for r, (cid, col, den) in zip(rows, counting.CANDIDATES):
            self.assertEqual(r[1], "`%s`" % col, cid)
            self.assertEqual(r[2], "`%s`" % den, cid)
            # 集計のどの欄から計算するかが書いてある
            self.assertIn("T", r[3], cid)
            self.assertIn("D" if den == "docs" else "T", r[4], cid)

    def test_doc_criteria_table(self):
        rows = self._table("criteria")
        self.assertEqual([r[0] for r in rows], ["`%s`" % b for b in counting.CRITERIA_IDS])
        rec = [r for r in rows if "おすすめ" in r[1]]
        self.assertEqual([r[0] for r in rec], ["`%s`" % counting.RECOMMENDED_CRITERION])

    def test_doc_constants(self):
        with open(DOC, encoding="utf-8") as f:
            text = f.read()
        self.assertIn("11/10", text)
        self.assertIn("21/20", text)
        self.assertEqual(str(counting.B4_SPREAD_LIMIT), "11/10")
        self.assertEqual(str(counting.B5_MENTION_LIMIT), "21/20")
        for d in counting.TRIAL_DAYS:
            self.assertIn(d, text)


class TestNoDataNoClock(unittest.TestCase):
    ALLOWED_IMPORTS = {"fractions", "gzip", "hashlib", "io", "json", "re", "sys"}

    def test_imports_and_clock(self):
        with open(os.path.join(SRC, "counting.py"), encoding="utf-8") as f:
            tree = ast.parse(f.read())
        names = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names.update(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom):
                names.add((node.module or "").split(".")[0])
            if isinstance(node, ast.Attribute):
                self.assertNotIn(node.attr, {"today", "now", "utcnow", "time", "environ"})
        self.assertEqual(names - self.ALLOWED_IMPORTS, set())

    def test_open_only_in_main(self):
        with open(os.path.join(SRC, "counting.py"), encoding="utf-8") as f:
            tree = ast.parse(f.read())
        for fn in tree.body:
            if isinstance(fn, ast.FunctionDef) and fn.name != "main":
                for node in ast.walk(fn):
                    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                        self.assertNotEqual(node.func.id, "open", fn.name)


if __name__ == "__main__":
    unittest.main()
