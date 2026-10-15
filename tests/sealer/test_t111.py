"""T-111 のテスト：順番5（タグの一覧の結果）の試みの記録（stats-order5-attempt）と順番5の記録（stats-order5）を書く入口
（src/sealer/seal_order5.py）と、それを照らす仕組み（ledger.check_order5_records、verify.check_order5_git・recompute_order5、
src/sealer/order5_recompute.py）。

実行（プロジェクトのルートで）:
    PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -B -m unittest discover -s tests/sealer -v

書くのは、本物の記録の固定したコミット（fixed_records.ORDER5_CODE_COMMIT。seq 1〜15）の clone の中だけ。順番5を本物の記録で
実行しない。日の集計（LACIE SHARE）と本物の区分表のファイルは読まない。
- clone の中で src/stats/order5.py を、テストの仮のコード（FAKE5）に置き換える。仮のコードは、合成の日の集計と合成の区分表から、
  封印係の order5_recompute.compute()（封印済みの tagrules.py・counting.py を使う）で値を作り、本物の order5.py と同じ名前・同じ
  形の main・detail・extra を書く。規則を偽る形（一覧にテーマを足す）も作れる。
- 合成のファイルの sha256 は、本物の day の行と区分表の result の行の値と違う。そこで、書く仕組みと verify の計算し直しでは、
  本物の照合（マニフェストの先頭の sha256、区分表の result の行）を通ったあとの値だけを、合成のファイルの値に置き換える
  （synthetic()）。
"""

import contextlib
import datetime
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import fixed_records  # noqa: E402
import test_ledger as tl  # noqa: E402
import test_t078 as t78  # noqa: E402
import test_t095 as t95  # noqa: E402
import test_writers as tw  # noqa: E402

ledger = tl.ledger
verify = tl.verify
import seal_order2  # noqa: E402
import seal_order5  # noqa: E402
import seal_records  # noqa: E402

A5, O5 = ledger.ORDER5_ATTEMPT_KIND, ledger.ORDER5_KIND
UTC = datetime.timezone.utc
DOC = os.path.join(tl.PROJECT, "docs", "verify", "periods-seal.md")
WHO = "%s <%s>" % (seal_order2.AUTHOR_NAME, seal_order2.AUTHOR_EMAIL)
THEME_NAMES = ["ZZ_A", "ZZ_B", "ZZ_C", "AB-C", "ZZ_A"]          # 重なった行1つ、記号を含む名前1つ

FAKE5 = r'''#!/usr/bin/env python3
"""テストの仮の順番5のコード（T-111 のテストが clone の中だけに置く）。"""
import hashlib
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "src", "sealer"))
import ledger  # noqa: E402
import order5_recompute as rc  # noqa: E402

EXTRA_TAG = @EXTRA@
DETAIL_EXTRA_TAG = @DETAIL@


def canon(x):
    return (json.dumps(x, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()


def main(argv):
    a = dict(zip(argv[0::2], argv[1::2]))
    store, tstore, out, repo = a["--store"], a["--themes-store"], a["--out-dir"], a["--repo"]
    recs = ledger.verify_chain(ledger.read_ledger(os.path.join(ROOT, "sealed", "ledger.jsonl")))
    read = lambda r, role: ledger.read_target_json(ROOT, r, role)  # noqa: E731
    seq = len(recs) + 1
    refs = ledger.order5_refs(recs, seq, read)
    sealed = ledger.order5_sealed_code(recs, read)
    g = [r for r in recs if r["seq"] == refs["gkg_run_result"]["seq"]][0]
    gdoc = read(g, ledger.GKG_RESULT_KIND)
    with open(os.path.join(ROOT, gdoc["manifest_path"]), "rb") as f:
        body = f.read()
    rows = ledger.order4_day_rows(body, gdoc, ledger._block_days("2015-03-02", "2020-12-14"))
    o4 = [r for r in recs if r["seq"] == refs["order4"]["seq"]][0]
    missing = sorted(m["day"] for m in read(o4, ledger.ORDER4_KIND)["list"]["missing_days"])
    with open(os.path.join(ROOT, ledger.THEMES_MANIFEST), "rb") as f:
        trow = [json.loads(x) for x in f.read().split(b"\n") if x.strip()][-1]
    with open(os.path.join(tstore, trow["file_name"]), "rb") as f:
        tdata = f.read()
    folder = os.path.join(out, ".fake-sealed")
    os.makedirs(os.path.join(folder, "src", "stats"))
    os.makedirs(os.path.join(folder, "v1cb463a"))
    for n in ("periods", "exclusion", "tagrules", "counting"):
        with open(os.path.join(ROOT, "src", "stats", n + ".py"), "rb") as f:
            data = f.read()
        with open(os.path.join(folder, "src", "stats", n + ".py"), "wb") as f:
            f.write(data)
    v1 = subprocess.run(["git", "-C", repo, "show", "%s:src/stats/tagrules.py" % ledger.ORDER5_1CB463A_COMMIT],
                        capture_output=True, check=True).stdout
    with open(os.path.join(folder, "v1cb463a", "tagrules.py"), "wb") as f:
        f.write(v1)

    def read_day(name):
        with open(os.path.join(store, name), "rb") as f:
            return f.read()
    day_rows = []
    for d in sorted(rows):
        sha = hashlib.sha256(read_day(rows[d]["file_name"])).hexdigest()
        day_rows.append({"day": d, "file_name": rows[d]["file_name"], "sha256": sha})
    inp = {"block": ["2015-03-02", "2020-12-14"], "missing_days": missing, "rows": day_rows,
           "themes_sha256": hashlib.sha256(tdata).hexdigest(), "themes_rows": len(tdata.decode().splitlines()) - 1}
    mods = rc.load_sealed(folder)
    got = rc.compute(mods, inp, read_day, tdata)
    if EXTRA_TAG and got["status"] == "ok":
        got["official"]["tag_list"] = sorted(got["official"]["tag_list"] + ["ZZ_FAKE"])
        got["official"]["tag_count"] += 1
    import fractions
    cov = got.get("coverage")
    if cov:
        for q in cov["quarters"] + [cov["total"]]:
            n = q["docs_all_groups"]
            q["ratios"] = {k: (None if not n else "%d/%d" % (fractions.Fraction(q[k], n).numerator,
                                                             fractions.Fraction(q[k], n).denominator))
                           for k in q if k.startswith("docs_without_")}
    counting = mods["counting"]
    cols = {cid: (col, den) for cid, col, den in counting.CANDIDATES}
    cands = [dict(x, official=x["id"] == "C7", note=None if x["id"] == "C7" else ledger.ORDER5_REF_NOTE)
             for x in got["candidates"]]
    by = {r["seq"]: r for r in recs}
    d1b = read(by[refs["order1b"]["seq"]], ledger.ORDER1B_KIND)
    rc_ref = ledger.order5_reference_criteria(refs, read(by[refs["order2"]["seq"]], ledger.ORDER2_KIND),
                                              d1b["counting"]["criteria_ids"])
    digest = hashlib.sha256("".join("%s\t%s\t%s\n" % (d, rows[d]["file_name"], rows[d]["sha256"])
                                    for d in sorted(rows)).encode("ascii")).hexdigest()   # マニフェストの day の行から
    inp_rec = {"entry": ledger.ORDER5_ENTRY, "run_id": gdoc["run_id"], "day_rows": len(day_rows),
               "day_files_read": len(day_rows), "day_files_sha256_checked": True, "c7_denominators_match_order4": True,
               "gkg_run_result_seq": g["seq"], "gkg_run_result_record_sha256": refs["gkg_run_result"]["record_sha256"],
               "manifest_path": gdoc["manifest_path"], "manifest_lines": gdoc["manifest_lines"],
               "manifest_sha256": gdoc["manifest_sha256"], "day_files_digest": digest}
    tt = dict(got["themes_table"], file_name=trow["file_name"], sha256=trow["sha256"], rows=trow["rows"],
              kept_columns=trow["kept_columns"], headerless=trow.get("headerless"), description_column=False)
    detail = extra = None
    if got["status"] == "ok":
        dd = got["detail"]
        detail = {"label": ledger.ORDER5_LABEL, "part": "detail", "in_git": False, "note": ledger.ORDER5_DETAIL_NOTE,
                  "official_result": dd["official_result"], "allset_result": dd["allset_result"],
                  "versions": dd["versions"], "candidate_lists": dd["candidate_lists"],
                  "citation": list(ledger.ORDER5_CITATION)}
        if DETAIL_EXTRA_TAG:
            detail["candidate_lists"][0]["tag_list"] = (detail["candidate_lists"][0]["tag_list"] or []) + ["ZZ_FAKE"]
        extra = {"label": ledger.ORDER5_LABEL, "part": "extra-versions"}
    main = {"label": ledger.ORDER5_LABEL, "status": got["status"],
            "block": {"name": "method", "start": "2015-03-02", "end": "2020-12-14"}, "refs": refs,
            "code": {"sealed": [{"name": n, "sha256": sealed[n],
                                 "sources": [{"periods": "seq 1 periods targets:code", "stats-order1b": "seq 6 stats-order1b files"
                                              }.get(k, "seq 5 stats-order1 order1:targets")]}
                                for n, k, _f in ledger.ORDER5_SEALED],
                     "versions": [{"name": n, "commit": c, "path": "src/stats/tagrules.py",
                                   "sha256": sealed["1cb463a:src/stats/tagrules.py"] if s_ is None else s_, "sealed": sl}
                                  for n, c, s_, sl in ledger.ORDER5_VERSIONS]},
            "input": inp_rec, "themes_table": tt, "reference_criteria": rc_ref, "a_equals_v": True,
            "limits": list(ledger.ORDER5_LIMITS), "citation": list(ledger.ORDER5_CITATION),
            "missing_days": {"source": "order4", "count": len(missing), "days": missing},
            "candidates": cands}
    if got["status"] == "ok":
        main.update(official={"candidate": "C7", "version": "current", "setting": "owner_choice", "official": True,
                              "result": got["official"]},
                    comparisons={k: dict(v, official=False, note=ledger.ORDER5_REF_NOTE) for k, v in got["comparisons"].items()},
                    coverage=cov,
                    outside={"detail": {"file_name": "order5-detail.json", "sha256": hashlib.sha256(canon(detail)).hexdigest()},
                             "extra": {"file_name": "order5-extra.json", "sha256": hashlib.sha256(canon(extra)).hexdigest()}})
        for n, x in (("order5-detail.json", detail), ("order5-extra.json", extra)):
            with open(os.path.join(out, n), "wb") as f:
                f.write(canon(x))
    else:
        main["outside"] = None
    with open(os.path.join(out, "order5-main.json"), "wb") as f:
        f.write(canon(main))
    return 0 if got["status"] == "ok" else 3


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
'''


def fake5(extra=False, detail=False):
    return FAKE5.replace("@EXTRA@", "True" if extra else "False").replace("@DETAIL@", "True" if detail else "False")


def order5_blocks():
    with open(DOC, encoding="utf-8") as f:
        return re.findall(r"<!-- test:order5 -->\n```sh\n(.*?)```", f.read(), re.S)


class Case(t95.Clone):
    """本物の記録（seq 1〜15）の clone。src/stats/order5.py を仮のコードにしてコミットし、合成の日の集計（C7 の分母が0の日が
    無いもの）と合成の区分表と、Git の外のフォルダを用意する。"""

    commit_id = fixed_records.ORDER5_CODE_COMMIT
    fake = False
    zero = ()

    def setUp(self):
        super().setUp()
        self.store5, self.shas5 = self.make_store("store5", self.zero)
        self.tstore = os.path.join(self.tmp, "themes")
        os.makedirs(self.tstore)
        self.trow = self.real_themes_row()
        self.tdata = ("THEME\n" + "".join(n + "\n" for n in THEME_NAMES)).encode()
        with open(os.path.join(self.tstore, self.trow["file_name"]), "wb") as f:
            f.write(self.tdata)
        self.outside = os.path.join(self.tmp, "outside")
        os.makedirs(self.outside)
        self.put5(fake5())
        self.now = datetime.datetime(2026, 10, 16, 0, 0, 0, tzinfo=UTC)

    def real_themes_row(self):
        with open(os.path.join(self.c, ledger.THEMES_MANIFEST), "rb") as f:
            return [json.loads(x) for x in f.read().split(b"\n") if x.strip()][-1]

    def put5(self, text, msg="テストの仮の順番5のコード（clone の中だけ）"):
        with open(os.path.join(self.c, *ledger.ORDER5_SCRIPT.split("/")), "w", encoding="utf-8") as f:
            f.write(text)
        self.git("add", "--", ledger.ORDER5_SCRIPT)
        self.git("commit", "-q", "-m", msg)

    @contextlib.contextmanager
    def synthetic(self):
        """計算し直しの入力の sha256 を、合成のファイルの値にする（本物の照合を通ったあとで置き換える）。"""
        real_rows, real_trow = verify.order5_day_rows, verify.order5_themes_row
        import hashlib

        def rows(root, gdoc, block):
            return {d: dict(r, sha256=self.shas5[d]) for d, r in real_rows(root, gdoc, block).items()}

        def trow(root):
            r = real_trow(root)
            return dict(r, sha256=hashlib.sha256(self.tdata).hexdigest(), rows=len(THEME_NAMES))
        with mock.patch.object(verify, "order5_day_rows", rows), mock.patch.object(verify, "order5_themes_row", trow):
            yield

    def seal5(self, store=None, runner=None):
        with mock.patch.object(ledger, "PROJECT_ROOT", self.c), self.synthetic():
            return seal_order5.seal(store or self.store5, self.tstore, self.outside, self.tick(), "ots",
                                    runner=runner or tw.FakeOts())

    def verify(self, *args):
        """verify を流す。--store を渡すと、順番4（seq 15）の C7 の分母も同じ置き場所で数え直すが、合成の日の集計は本物の
        seq 15 の一覧と合わない。順番4の数え直しは tests/sealer/test_t095.py で確かめているので、ここでは差し替える。"""
        with self.synthetic(), mock.patch.object(verify, "recount_order4", lambda *a, **k: 0):
            return tl.run_verify_inproc(self.c, *args)

    def full(self, *extra):
        return ("all", "--rev", "auto", "--store", self.store5, "--themes-store", self.tstore) + extra

    def raw5(self, kind, doc):
        with mock.patch.object(seal_records, "check_new", lambda *a, **k: None):
            rec, _rel, _o = seal_records.write_doc_record(self.c, kind, doc, self.ledger_bytes(), "作り物（テスト）",
                                                          self.tick(), "ots", runner=tw.FakeOts())
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "作り物の %s（テスト）" % kind)
        return rec

    def refuses5(self, kind, doc, text, **kw):
        before = self.ledger_bytes()
        with self.synthetic(), self.assertRaisesRegex(ledger.LedgerError, text):
            seal_records.write_doc_record(self.c, kind, doc, before, "作り物（テスト）", self.tick(), "ots",
                                          runner=tw.FakeOts(), **kw)
        self.assertEqual(self.ledger_bytes(), before)

    def inputs(self, out):
        return {"store": self.store5, "themes_store": self.tstore, "outside_dir": out["out_dir"]}


# ---------------------------------------------------------------- 1. 書く → コミット → verify

class TestWrite(Case):
    def test_write_commit_verify(self):
        head0 = self.head()
        out = self.seal5()
        arec, _arel, aots, adoc, acommit = out["attempt"]
        rec, rel, ots, doc, commit = out["order5"]
        self.assertEqual((arec["seq"], arec["kind"], rec["seq"], rec["kind"]), (16, A5, 17, O5))
        self.assertEqual(sorted(adoc), sorted(ledger.ORDER5_ATTEMPT_KEYS))
        self.assertEqual(sorted(doc), sorted(ledger.ORDER5_DOC_KEYS))
        self.assertEqual(adoc["head"], head0)
        self.assertEqual(doc["head"], acommit)                       # 試みをコミットしたあとの HEAD で流した
        self.assertEqual(doc["attempt"], ledger.record_ref(arec))
        self.assertEqual({k: v["seq"] for k, v in doc["refs"].items()},
                         {"order1": 5, "order1b": 6, "order2": 10, "order3": 14, "order4": 15, "gkg_run_result": 12})
        self.assertEqual(doc["refs"]["order4"]["list_sha256"], "6343bcc7d1ad2b406cdb2a5013b029a750c476f93098715f1a822831f283a35d")
        self.assertEqual(doc["status"], "ok")
        self.assertEqual(doc["main_sha256"], ledger.sha256_hex(ledger.order5_main_bytes(doc["main"])))
        self.assertEqual(doc["code"]["script"]["sha256"], ledger.sha256_hex(fake5().encode()))
        self.assertEqual([x["name"] for x in doc["code"]["sealed"]], [n for n, _k, _f in ledger.ORDER5_SEALED])
        self.assertEqual(sorted(os.listdir(out["out_dir"])),
                         [".fake-sealed", ".link-probe", ".link-probe-2", "order5-detail.json", "order5-extra.json",
                          "order5-main.json"])
        for c, msg in ((acommit, seal_order5.ATTEMPT_MESSAGE), (commit, seal_order5.ORDER5_MESSAGE)):
            got = self.git("log", "-1", "--format=%an <%ae>|%cn <%ce>|%B", c).decode().rstrip("\n")
            self.assertEqual(got, WHO + "|" + WHO + "|" + msg)
        self.assertEqual(self.head(), commit)
        self.assertEqual(self.git("status", "--porcelain"), b"")
        # verify：--store・--themes-store なしでは計算し直しは「照らさなかった」
        out_v = self.verify_zero("all", "--rev", "auto")
        self.assertIn("%s seq 16（順番5の試み）" % A5, out_v)
        self.assertIn("%s seq 17（順番5）: status ok" % O5, out_v)
        self.assertIn("照らさなかった：日の集計と区分表の置き場所（--store・--themes-store）を渡していないので、seq 17", out_v)
        # 渡せば、order5.py に頼らずに計算し直して照らす。Git の外のファイルも照らす
        out_v = self.verify_zero(*self.full("--order5-outside", out["out_dir"]))
        self.assertIn("正式な一覧と要約を計算し直した。main と同じ", out_v)
        self.assertIn("Git の外のファイル order5-detail.json・order5-extra.json の sha256 は、記録の outside と同じ", out_v)
        # detail を1バイト変えると止まる
        with open(os.path.join(out["out_dir"], "order5-detail.json"), "ab") as f:
            f.write(b" ")
        self.verify_stops("order5-detail.json の sha256 が、記録の outside.detail と違う",
                          *self.full("--order5-outside", out["out_dir"]))
        # 手順書の第三者の塊（日の集計を使わない塊）
        for r in self.run_blocks5():
            self.assertEqual(r.returncode, 0, r.stderr.decode())

    def run_blocks5(self):
        out = []
        for block in order5_blocks():
            out.append(subprocess.run(["bash", "-e", "-o", "pipefail", "-c", block], cwd=self.c, capture_output=True,
                                      env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1")))
        self.assertTrue(out)
        return out

    def test_twice_and_attempt_after(self):
        """一度だけ：順番5の記録のあとは、試みも順番5の記録も書かない。"""
        out = self.seal5()
        before = self.ledger_bytes()
        with self.assertRaisesRegex(ledger.LedgerError, "順番5（stats-order5）の記録は、もう seq 17 にある"):
            self.seal5()
        self.assertEqual(self.ledger_bytes(), before)
        adoc = out["attempt"][3]
        self.raw5(A5, dict(adoc, ledger_head=ledger.expected_ledger_head(self.ledger_bytes(), 18), head=self.head()))
        self.verify_stops("もう seq 17 にある")

    def test_run_failure_leaves_attempt(self):
        """order5.py が止まった（日の集計が無い）：試みの記録は残り（コミット済み）、順番5の記録は書かない。もう一度流すと、
        新しい試みとして記録される（流した回数は試みの記録の数）。"""
        empty, _s = self.make_store("empty")
        with self.assertRaisesRegex(seal_order5.Order5Written, "順番5の記録は書いていない"):
            self.seal5(empty)
        self.assertEqual([r["kind"] for r in self.records()[-1:]], [A5])
        self.assertEqual(self.git("status", "--porcelain"), b"")
        out = self.seal5()
        self.assertEqual([r["kind"] for r in self.records()[15:]], [A5, A5, O5])
        self.assertEqual(out["order5"][3]["attempt"]["seq"], 17)
        self.verify_zero(*self.full())


class TestStopped(Case):
    """C7 の分母が 0 の日（欠けた日でない日）がある合成の日の集計：main は stopped、outside は null。止まった事実の記録として
    書かれる（seal-order1.md 143行）。"""

    zero = ("2016-06-01",)

    def test_stopped(self):
        out = self.seal5()
        doc = out["order5"][3]
        self.assertEqual((doc["status"], doc["outside"]), ("stopped", None))
        self.assertEqual(sorted(os.listdir(out["out_dir"])), [".fake-sealed", ".link-probe", ".link-probe-2",
                                                              "order5-main.json"])
        out_v = self.verify_zero(*self.full())
        self.assertIn("status stopped", out_v)


# ---------------------------------------------------------------- 2. 偽り

class TestForgeries(Case):
    def test_doctored_list_refused_and_verify_stops(self):
        """一覧にテーマを足す版の order5.py で書こうとすると、書く仕組みの計算し直しが止める（試みは残る）。照合を飛ばして足すと、
        --store の verify が止める（--store なしでは見つからない）。"""
        self.put5(fake5(extra=True))
        with self.assertRaisesRegex(seal_order5.Order5Written, "main の値が、封印済みのコードで計算し直した値と違う"):
            self.seal5()
        self.assertEqual(self.records()[-1]["kind"], A5)
        data = self.ledger_bytes()
        records = ledger.verify_chain(data)
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(ledger, "PROJECT_ROOT", self.c):
            doc, out_dir = seal_order5.run_and_build(self.c, data, records, records[-1], self.store5, self.tstore,
                                                     seal_order5.prepare_out_dir(self.outside_new(), records[-1]["seq"]), tmp)
        self.raw5(O5, doc)
        self.verify_zero("all", "--rev", "auto")
        self.verify_stops("official.result.tag_count", *self.full())

    def outside_new(self):
        p = os.path.join(self.tmp, "outside2")
        os.makedirs(p, exist_ok=True)
        return p

    def honest(self):
        """試みを書き、順番5の記録の中身を作る（まだ書かない）。返り値：(中身, 出力のフォルダ)。"""
        data = self.ledger_bytes()
        records = ledger.verify_chain(data)
        adoc = seal_order5.build_attempt(self.c, data, records)
        with mock.patch.object(ledger, "PROJECT_ROOT", self.c):
            seal_order5._write(self.c, A5, adoc, data, records, "試み（テスト）", self.tick(), "ots", tw.FakeOts())
        data = self.ledger_bytes()
        records = ledger.verify_chain(data)
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(ledger, "PROJECT_ROOT", self.c), self.synthetic():
            return seal_order5.run_and_build(self.c, data, records, records[-1], self.store5, self.tstore,
                                             seal_order5.prepare_out_dir(self.outside_new(), records[-1]["seq"]), tmp)

    def test_forgeries_refused(self):
        doc, out_dir = self.honest()
        inp = {"order5_inputs": {"store": self.store5, "themes_store": self.tstore, "outside_dir": out_dir}}
        main = doc["main"]
        cases = {
            "main_sha256": (dict(doc, main_sha256="0" * 64), "main_sha256 が"),
            "refs": (dict(doc, refs=dict(doc["refs"], order4=dict(doc["refs"]["order4"], list_sha256="0" * 64))),
                     "refs が、記録から決まる参照と違う"),
            "attempt": (dict(doc, attempt={"seq": 15, "record_sha256": "0" * 64}), "attempt が"),
            "code の版": (dict(doc, code=dict(doc["code"], script={"path": ledger.ORDER5_SCRIPT, "sha256": "a" * 64})),
                       "直前の試みの記録と違う"),
            "status": (dict(doc, status="stopped"), "status が main の status"),
            "outside": (dict(doc, outside=None), "outside が main の outside と違う"),
            "欠けた日": (self.resha(doc, dict(main, missing_days=dict(main["missing_days"], days=main["missing_days"]["days"][1:]))),
                     "main.missing_days"),
            "main の参照": (self.resha(doc, dict(main, refs=dict(main["refs"], order3={"seq": 13, "record_sha256": "0" * 64}))),
                       "main.refs"),
            "封印済みのコード": (self.resha(doc, dict(main, code=dict(main["code"], sealed=[{"name": "src/stats/tagrules.py",
                                                                                    "sha256": "b" * 64}]))),
                         "main.code.sealed"),
            "比べる版": (self.resha(doc, dict(main, code=dict(main["code"], versions=main["code"]["versions"][:2]))),
                     "main.code（sealed の値と出どころ、versions の3行）"),
            "分子の欄": (self.resha(doc, dict(main, candidates=[dict(x, numerator_column="v2_docs") if x["id"] == "C1" else x
                                                               for x in main["candidates"]])),
                     "candidates.C1.numerator_column"),
            "置き場所なし": (doc, "計算し直してからでなければ書かない"),
            # T-111 差し戻し1回目 中-1：seal-order1.md 143行の確かめと、記録とマニフェストから決まる値
            "candidates の official": (self.resha(doc, dict(main, candidates=[dict(x, official=True) if x["id"] == "C1" else x
                                                                             for x in main["candidates"]])),
                                      "正式な結果がちょうど一つ"),
            "candidates の注記": (self.resha(doc, dict(main, candidates=[dict(x, note=None) if x["id"] == "C2" else x
                                                                       for x in main["candidates"]])), "注記が違う"),
            "comparisons の official": (self.resha(doc, dict(main, comparisons=dict(
                main["comparisons"], allset=dict(main["comparisons"]["allset"], official=True)))), "main.comparisons"),
            "reference_criteria の official": (self.resha(doc, dict(main, reference_criteria=dict(
                main["reference_criteria"], official=True))), "reference_criteria"),
            "reference_criteria の値": (self.resha(doc, dict(main, reference_criteria=dict(
                main["reference_criteria"], computed=dict(main["reference_criteria"]["computed"], input_run_id="0" * 16)))),
                "reference_criteria"),
            "基準の案が足りない": (self.resha(doc, dict(main, reference_criteria=dict(
                main["reference_criteria"], criteria_ids=["B1", "B2"]))), "reference_criteria"),
            "label": (self.resha(doc, dict(main, label="order5-tag-list-v9")), "label・limits・citation"),
            "limits": (self.resha(doc, dict(main, limits=main["limits"][:-1])), "label・limits・citation"),
            "citation": (self.resha(doc, dict(main, citation=[])), "label・limits・citation"),
            "input の run_id": (self.resha(doc, dict(main, input=dict(main["input"], run_id="0" * 16))), "main.input の run_id"),
            "input の manifest_lines": (self.resha(doc, dict(main, input=dict(main["input"], manifest_lines=1))),
                                       "main.input の manifest_lines"),
            "input の day_files_digest": (self.resha(doc, dict(main, input=dict(main["input"], day_files_digest="0" * 64))),
                                         "day_files_digest"),
            "themes_table の sha256": (self.resha(doc, dict(main, themes_table=dict(main["themes_table"], sha256="0" * 64))),
                                      "themes_table の sha256"),
            "themes_table の rows": (self.resha(doc, dict(main, themes_table=dict(main["themes_table"], rows=1))),
                                    "themes_table の rows"),
            # 流したコードの版を偽る（試みと同じに保つ欄は変えず、取り出したファイルの数だけ変える）：git の照合が止める
            "code の tree": (dict(doc, code=dict(doc["code"], tree=dict(doc["code"]["tree"],
                                                                       files=doc["code"]["tree"]["files"] + 1))),
                            "順番5を流したコードの版を偽っている"),
        }
        for name, (bad, text) in cases.items():
            with self.subTest(name=name):
                self.refuses5(O5, bad, text, **({} if name == "置き場所なし" else inp))
        # 一覧を偽る（つじつまは合わせ、main_sha256 も合わせる）：計算し直しで止まる
        off = dict(main["official"], result=dict(main["official"]["result"], tag_count=99))
        self.refuses5(O5, self.resha(doc, dict(main, official=off)), "official.result.tag_count", **inp)
        # Git の外のファイルが無い
        os.rename(os.path.join(out_dir, "order5-extra.json"), os.path.join(out_dir, "moved.json"))
        self.refuses5(O5, doc, "Git の外のファイル（order5-extra.json）が置き場所に無い", **inp)

    def test_detail_forged(self):
        """T-111 差し戻し1回目 中-2：detail の中身を偽る版の order5.py（C1 の一覧にテーマを足し、main の outside の sha256 は
        合わせる）は、書く仕組みが detail を計算し直した値と照らして止める。照合を飛ばして足すと、--store と --order5-outside を
        渡した verify が止める（--order5-outside だけでは sha256 が合うので見つからない）。"""
        self.put5(fake5(detail=True))
        with self.assertRaisesRegex(seal_order5.Order5Written, "detail の値が、封印済みのコードで計算し直した値と違う（detail.candidate_lists）"):
            self.seal5()
        data = self.ledger_bytes()
        records = ledger.verify_chain(data)
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(ledger, "PROJECT_ROOT", self.c):
            doc, out_dir = seal_order5.run_and_build(self.c, data, records, records[-1], self.store5, self.tstore,
                                                     seal_order5.prepare_out_dir(self.outside_new(), records[-1]["seq"]), tmp)
        self.raw5(O5, doc)
        out_v = self.verify_zero("all", "--rev", "auto", "--order5-outside", out_dir)
        self.assertIn("detail の中身は、--store と --themes-store も渡したときだけ", out_v)
        self.verify_stops("detail.candidate_lists", *self.full("--order5-outside", out_dir))

    def test_hardlink_probe(self):
        """T-111 差し戻し1回目 軽-4：Git の外のフォルダでハードリンクを作れなければ、試みを書かずに止まる。"""
        before = self.ledger_bytes()
        with mock.patch.object(seal_order5.os, "link", side_effect=OSError("リンクを作れない（テスト）")), \
                self.assertRaisesRegex(ledger.LedgerError, "ハードリンクを作れない") as cm:
            self.seal5()
        self.assertNotIsInstance(cm.exception, seal_order5.Order5Written)
        self.assertEqual(self.ledger_bytes(), before)
        self.assertEqual(self.git("status", "--porcelain"), b"")
        # 確かめの途中で止まったフォルダ（確かめのファイルだけ）は、次の実行でそのまま使う
        out = self.seal5()
        self.assertEqual(out["order5"][0]["kind"], O5)

    def test_attempt_code_forged(self):
        """試みの記録の order5.py の sha256 を偽ると、書く仕組み（git の照合）が書かず、照合を飛ばして足すと verify が止める。"""
        data = self.ledger_bytes()
        adoc = seal_order5.build_attempt(self.c, data, ledger.verify_chain(data))
        bad = dict(adoc, code=dict(adoc["code"], script={"path": ledger.ORDER5_SCRIPT, "sha256": "c" * 64}))
        self.refuses5(A5, bad, "順番5を流したコードの版を偽っている")
        self.raw5(A5, bad)
        self.verify_stops("順番5を流したコードの版を偽っている", "all", "--rev", "auto")

    @staticmethod
    def resha(doc, main):
        return dict(doc, main=main, main_sha256=ledger.sha256_hex(ledger.order5_main_bytes(main)))


class TestOrderUnit(unittest.TestCase):
    """位置の照合（ledger.check_order5_position）を、記録の並びだけで確かめる。"""

    def recs(self, kinds):
        return [{"seq": i + 1, "kind": k} for i, k in enumerate(kinds)]

    def test_position(self):
        O4, TA = ledger.ORDER4_KIND, ledger.THRESHOLD_ACCESS_KIND
        ok = ["periods", ledger.ORDER3_KIND, O4]
        ledger.check_order5_position(self.recs(ok), {"seq": 4, "kind": A5})
        ledger.check_order5_position(self.recs(ok + [A5]), {"seq": 5, "kind": O5})
        ledger.check_order5_position(self.recs(ok + [A5, A5]), {"seq": 6, "kind": O5})
        cases = {
            "順番4が無い": (["periods", ledger.ORDER3_KIND], A5, "順番4（stats-order4）の記録がちょうど1件ない"),
            "threshold-access のあと": (ok + [TA], A5, "threshold-access の記録（seq 4）より後に"),
            "順番5のあとの試み": (ok + [A5, O5], A5, "もう seq 5 にある"),
            "順番5が2件": (ok + [A5, O5, A5], O5, "もう seq 5 にある"),
            "直前が試みでない": (ok, O5, "直前の記録が、試み"),
        }
        for name, (kinds, kind, text) in cases.items():
            with self.subTest(name=name), self.assertRaisesRegex(ledger.LedgerError, re.escape(text)):
                ledger.check_order5_position(self.recs(kinds), {"seq": len(kinds) + 1, "kind": kind})
        # 順番5の kind のあとに順番4は置けない（ORDER4_BEFORE_KINDS）
        with self.assertRaisesRegex(ledger.LedgerError, "stats-order5-attempt の記録"):
            ledger.check_order4_position(self.recs(["periods", ledger.ORDER3_KIND, A5]), 4)

    def test_kinds(self):
        for k in (A5, O5):
            self.assertIn(k, ledger.ALLOWED_KINDS)
            self.assertIn(k, seal_records.WRITTEN_KINDS)
            self.assertIn(k, ledger.ORDER4_BEFORE_KINDS)
        self.assertEqual(ledger.ORDER5_BEFORE_KINDS, (ledger.THRESHOLD_ACCESS_KIND,))


class TestConstantsSameAsOrder5(unittest.TestCase):
    """ledger の決まった値（label・limits・citation・注記）が、統計係の src/stats/order5.py の定数と、文書の付録Aと同じ。
    order5.py は ast で読むだけ（作業ツリーのファイル。HEAD を git で読むことは tests/sealer の規則で限っているため。合否は
    コミットしたあとに流した結果で判断する）。"""

    def test_same(self):
        import ast
        with open(os.path.join(tl.PROJECT, "src", "stats", "order5.py"), encoding="utf-8") as f:
            tree = ast.parse(f.read())
        c = {}
        for st in tree.body:
            if isinstance(st, ast.Assign) and len(st.targets) == 1 and isinstance(st.targets[0], ast.Name):
                try:
                    c[st.targets[0].id] = ast.literal_eval(st.value)
                except ValueError:
                    pass
        self.assertEqual(c["LABEL"], ledger.ORDER5_LABEL)
        self.assertEqual(c["REF_NOTE"], ledger.ORDER5_REF_NOTE)
        self.assertEqual(tuple(c["LIMITS"]), ledger.ORDER5_LIMITS)
        self.assertEqual(tuple(c["CITATION"]), ledger.ORDER5_CITATION)
        self.assertEqual(c["ENTRY"], ledger.ORDER5_ENTRY)
        with open(os.path.join(tl.PROJECT, "docs", "stats", "order5-tag-list.md"), encoding="utf-8") as f:
            doc = f.read()
        for text in ledger.ORDER5_LIMITS + ledger.ORDER5_CITATION + (ledger.ORDER5_DETAIL_NOTE, ledger.ORDER5_REF_NOTE):
            self.assertIn(text, doc)


class TestRealOrder5Build(unittest.TestCase):
    """T-111 差し戻し1回目 軽-1：本物の src/stats/order5.py の build() の出力（合成のデータ。tests/stats/test_order5.py の
    Fixture）を、封印係の order5_recompute.compute() で計算し直した値と照らすと一致する（通常・C2 が計算できない・C7 で止まる）。"""

    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, os.path.join(tl.PROJECT, "tests", "stats"))
        import test_order5 as to5
        import order5_recompute as rc
        cls.to5, cls.rc = to5, rc
        cls.mods = {"periods": to5.o5.periods, "exclusion": to5.o5.exclusion, "tagrules": to5.o5.tagrules,
                    "counting": to5.o5.counting, "tagrules_1cb463a": to5.VERSIONS["1cb463a"]}

    def check(self, fx, status):
        main, detail, _extra = fx.build()
        self.assertEqual(main["status"], status)
        inp = {"block": [self.to5.BLOCK[0].isoformat(), self.to5.BLOCK[1].isoformat()],
               "missing_days": sorted(m["day"] for m in fx.order4["missing_days"]),
               "rows": [{"day": r["day"], "file_name": r["file_name"], "sha256": r["sha256"]} for r in fx.rows],
               "themes_sha256": fx.result_row["sha256"], "themes_rows": fx.result_row["rows"]}
        got = self.rc.compute(self.mods, inp, fx.read, fx.table_bytes)
        self.assertEqual(self.rc.compare_with_main(main, got), [])
        if status == "ok":
            self.assertEqual(self.rc.compare_with_detail(detail, got, ledger.ORDER5_LABEL, ledger.ORDER5_DETAIL_NOTE,
                                                         ledger.ORDER5_CITATION), [])
            bad = dict(detail, allset_result=dict(detail["allset_result"], tag_list=[]))
            self.assertIn("detail.allset_result", self.rc.compare_with_detail(bad, got, ledger.ORDER5_LABEL,
                                                                              ledger.ORDER5_DETAIL_NOTE, ledger.ORDER5_CITATION))
        return main, got

    def test_standard(self):
        main, _got = self.check(self.to5.Fixture(self.to5.standard_spec()), "ok")
        self.assertTrue(main["official"]["result"]["tag_list"])
        # 本物の order5.py の main の code・決まった文・注記・reference_criteria の形が、ledger の決まった値と同じ
        o5 = self.to5.o5
        sealed = {n: sha for n, sha, _src in o5.SEALED_CODE}
        srcs = {"periods": "seq 1 periods targets:code", "stats-order1": "seq 5 stats-order1 order1:targets",
                "stats-order1b": "seq 6 stats-order1b files"}
        self.assertEqual(main["code"], {
            "sealed": [{"name": n, "sha256": sealed[n], "sources": [srcs[k]]} for n, k, _f in ledger.ORDER5_SEALED],
            "versions": [{"name": n, "commit": c, "path": "src/stats/tagrules.py",
                          "sha256": sealed["1cb463a:src/stats/tagrules.py"] if s_ is None else s_, "sealed": sl}
                         for n, c, s_, sl in ledger.ORDER5_VERSIONS]})
        self.assertEqual((main["label"], main["limits"], main["citation"]),
                         (ledger.ORDER5_LABEL, list(ledger.ORDER5_LIMITS), list(ledger.ORDER5_CITATION)))
        self.assertEqual([x["note"] for x in main["candidates"]], [ledger.ORDER5_REF_NOTE] * 6 + [None])
        self.assertEqual(sorted(main["input"]), sorted(["entry", "run_id", "day_rows", "day_files_read",
                                                        "day_files_sha256_checked", "c7_denominators_match_order4",
                                                        "gkg_run_result_seq", "gkg_run_result_record_sha256",
                                                        "manifest_path", "manifest_lines", "manifest_sha256",
                                                        "day_files_digest"]))
        rc = main["reference_criteria"]
        self.assertEqual(sorted(rc), ["computed", "criteria_ids", "note", "official", "order2_status", "source"])

    def test_c2_not_computable(self):
        main, _got = self.check(self.to5.Fixture(self.to5.standard_spec(v1_empty_day="2015-03-31")), "ok")
        self.assertIn("not_computable", [x["status"] for x in main["candidates"]])

    def test_c7_stopped(self):
        spec = self.to5.standard_spec()
        spec["2015-03-31"] = [("2", "", "", False)] * 2           # 欠けた日でない日に、テーマの付いた文書が無い
        self.check(self.to5.Fixture(spec), "stopped")


class TestRecomputeUnit(unittest.TestCase):
    """order5_recompute.compare_with_main は、どの欄が違っても名前を返す。"""

    def test_compare(self):
        import order5_recompute as rc
        got = {"status": "ok", "themes_table": {"unique_names": 3}, "candidates": [{"id": "C7", "n_med": "1/1"}],
               "official": {"tag_list": ["A"], "tag_count": 1}, "comparisons": {"allset": {"diff_count": 0}},
               "coverage": {"quarters": [{"docs_all_groups": 4, "docs_without_any_theme": 1, "usable_days": 2}],
                            "total": {"docs_all_groups": 4, "docs_without_any_theme": 1, "usable_days": 2}}}
        q = {"docs_all_groups": 4, "docs_without_any_theme": 1, "usable_days": 2, "ratios": {"docs_without_any_theme": "1/4"}}
        main = {"status": "ok", "themes_table": {"unique_names": 3}, "candidates": [{"id": "C7", "n_med": "1/1"}],
                "official": {"candidate": "C7", "official": True, "result": {"tag_list": ["A"], "tag_count": 1}},
                "comparisons": {"allset": {"diff_count": 0}}, "coverage": {"quarters": [dict(q)], "total": dict(q)}}
        self.assertEqual(rc.compare_with_main(main, got), [])
        self.assertEqual(rc.compare_with_main(dict(main, status="stopped"), got), ["status"])
        bad = json.loads(json.dumps(main))
        bad["coverage"]["total"]["ratios"]["docs_without_any_theme"] = "1/3"
        self.assertEqual(rc.compare_with_main(bad, got), ["coverage.ratios.docs_without_any_theme"])
        bad = json.loads(json.dumps(main))
        bad["official"]["result"]["tag_list"] = ["A", "B"]
        self.assertEqual(rc.compare_with_main(bad, got), ["official.result.tag_list"])


if __name__ == "__main__":
    unittest.main()
