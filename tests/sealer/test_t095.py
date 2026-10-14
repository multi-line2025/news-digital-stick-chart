"""T-095 のテスト：順番4（手法を作る期間の区画の、欠けた日の一覧）の記録（stats-order4）を書く入口
（src/sealer/seal_order4.py）と、それを照らす仕組み（ledger.check_order4_records、verify.check_order4_git・rerun_order4）。
あわせて、順番5の記録が順番4を参照することを求める関数（ledger.check_ref_order4）と、T-091 の監査の軽-2（halt（input）の
reason の照合）。

実行（プロジェクトのルートで）:
    PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -B -m unittest discover -s tests/sealer -v

書くのは、本物の記録の固定したコミット（fixed_records.ORDER3_COMMIT。seq 1〜14。fixed_records.ORDER2_COMMIT。seq 1〜10）の
clone と、仮のプロジェクト（test_t090.O3Case）の中だけ。ots は偽物。本物の sealed/・data/ には書かない。順番4を本物の記録で
実行しない。日の集計（LACIE SHARE）は読まない。
- 書く→コミット→verify の流れは、clone の中で src/stats/missing_days.py をテストの仮の一覧のコード（FAKE_SCRIPT。合成の
  置き場所の c7.json だけを読み、本物と同じ形の JSON を出す）に置き換えて確かめる。
- 本物の missing_days.py（T-093 の版）は、clone の中で固定した版のフォルダに取り出し、空の置き場所で流して、関門と
  コードの照合を通ったあとで、最初の日の集計の sha256 の照合で止まることだけを確かめる（本物の日の集計は開かない）。
"""

import contextlib
import datetime
import io
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
import test_t090 as t90  # noqa: E402
import test_writers as tw  # noqa: E402

ledger = tl.ledger
verify = tl.verify
import seal_order2  # noqa: E402
import seal_order4  # noqa: E402
import seal_records  # noqa: E402

O4 = ledger.ORDER4_KIND
UTC = datetime.timezone.utc
DOC = os.path.join(tl.PROJECT, "docs", "verify", "periods-seal.md")
WHO = "%s <%s>" % (seal_order2.AUTHOR_NAME, seal_order2.AUTHOR_EMAIL)
T093_SHA = "0ff14106b5a3a736b179d2f8f360394d81f4aa3e605c4c3312bb05be01e8586e"

# テストの仮の一覧のコード（clone の中の src/stats/missing_days.py に置く）。置き場所の c7.json（合成）だけを読み、
# 流したフォルダの封印の記録から正式な run の gkg-run-result を探して、本物の missing_days.py と同じ形の JSON を出す。
# VARIANT は、版を変えると出力が変わるようにするための値（版の固定のテスト）。
FAKE_SCRIPT = r'''#!/usr/bin/env python3
"""テストの仮の一覧のコード（T-095 のテストが clone の中だけに置く）。"""
import datetime
import hashlib
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "src", "sealer"))
import ledger  # noqa: E402

VARIANT = %d


def sha(rel):
    with open(os.path.join(ROOT, rel), "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def main(argv):
    if len(argv) != 2 or argv[0] != "--store":
        sys.stderr.write("missing_days: 使い方は --store <置き場所>\n")
        return 2
    path = os.path.join(argv[1], "c7.json")
    if not os.path.isfile(path):
        sys.stderr.write("missing_days: 止まった：c7.json が無い\n")
        return 1
    with open(path, encoding="utf-8") as f:
        spec = json.load(f)
    recs = ledger.verify_chain(ledger.read_ledger(os.path.join(ROOT, "sealed", "ledger.jsonl")))
    read = lambda r, role: ledger.read_target_json(ROOT, r, role)  # noqa: E731
    rec = [r for r in recs if r["kind"] == ledger.GKG_RESULT_KIND and read(r, r["kind"])["mode"] == "official"][0]
    doc = read(rec, ledger.GKG_RESULT_KIND)
    days, d = [], datetime.date(2015, 3, 2)
    while d <= datetime.date(2020, 12, 14):
        days.append(d.isoformat())
        d += datetime.timedelta(days=1)
    c7 = {x: spec.get("c7", {}).get(x, 1000 + VARIANT) for x in days}
    ok = spec.get("files_ok", {})
    missing, partial = [], 0
    for x in days:
        f = ok.get(x, 96)
        if f < 72 or c7[x] == 0:
            missing.append({"day": x, "files_ok": f, "files_listed": 96, "c7_denominator": c7[x],
                            "below_min_files": f < 72, "zero_c7_denominator": c7[x] == 0})
        elif f < 96:
            partial += 1
    out = {
        "label": "missing-days-method-v3",
        "block": {"name": "method", "start": days[0], "end": days[-1]},
        "rule": {"source": "docs/stats/candidates.md 3章 (5)（seq 2）",
                 "function": "src/stats/candidates.py day_is_missing(present_slots, total_volume)",
                 "slots_per_day": 96, "min_present_slots": 72, "present_slots": "files_ok of the manifest day row",
                 "total_volume": "official C7 denominator of the day", "official_candidate": "C7",
                 "counting_py_sha256": sha("src/stats/counting.py"), "candidates_py_sha256": sha("src/stats/candidates.py"),
                 "periods_py_sha256": sha("src/stats/periods.py")},
        "input": {"entry": "src/collector/gkg.py official_day_records()", "run_id": doc["run_id"],
                  "day_rows": len(days), "day_files_read": len(days), "day_files_sha256_checked": True,
                  "gkg_run_result_seq": rec["seq"],
                  "gkg_run_result_record_sha256": ledger.sha256_hex(ledger.canonical_line(rec)),
                  "manifest_path": doc["manifest_path"], "manifest_lines": doc["manifest_lines"],
                  "manifest_sha256": doc["manifest_sha256"]},
        "days_in_block": len(days), "missing_count": len(missing), "missing_days": missing,
        "zero_c7_denominator_days": [x for x in days if c7[x] == 0], "c7_denominator_by_day": c7,
        "partial_days_count": partial,
    }
    sys.stdout.buffer.write((json.dumps(out, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8"))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
'''

# 合成の置き場所の中身：72本未満の日が2つ（1つは一部が欠けた日の手前）、C7 の分母が0の日が1つ、一部が欠けた日が1つ
SPEC = {"files_ok": {"2015-05-29": 0, "2020-10-01": 10, "2016-01-05": 80}, "c7": {"2015-10-21": 0}}
WANT_MISSING = ["2015-05-29", "2015-10-21", "2020-10-01"]


def order4_blocks():
    with open(DOC, encoding="utf-8") as f:
        return re.findall(r"<!-- test:order4 -->\n```sh\n(.*?)```", f.read(), re.S)


class Clone(unittest.TestCase):
    """本物の記録の固定したコミットの clone。fake が真なら、src/stats/missing_days.py をテストの仮の一覧のコードにして
    コミットする（clone の中だけ）。"""

    commit_id = fixed_records.ORDER3_COMMIT
    fake = True

    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.addCleanup(self.td.cleanup)
        self.tmp = self.td.name
        self.c = os.path.join(self.tmp, "c")
        code = "worktree" if os.environ.get("SEALER_DOC_TEST_WORKTREE") == "1" else "head"
        fixed_records.checkout(self.c, self.commit_id, code=code)
        self.store = self.make_store("store", SPEC)
        self.now = datetime.datetime(2026, 10, 16, 0, 0, 0, tzinfo=UTC)
        if self.fake:
            self.put_script(FAKE_SCRIPT % 0)
            self.git("add", "--", ledger.ORDER4_SCRIPT)
            self.git("commit", "-q", "-m", "テストの仮の一覧のコード（clone の中だけ）")

    def make_store(self, name, spec):
        path = os.path.join(self.tmp, name)
        os.makedirs(path)
        if spec is not None:
            with open(os.path.join(path, "c7.json"), "w", encoding="utf-8") as f:
                json.dump(spec, f)
        return path

    def put_script(self, text):
        with open(os.path.join(self.c, *ledger.ORDER4_SCRIPT.split("/")), "w", encoding="utf-8") as f:
            f.write(text)

    def git(self, *args):
        return subprocess.run(["git", "-C", self.c] + list(tl.AUTHOR) + list(args), check=True,
                              capture_output=True).stdout

    def head(self):
        return self.git("rev-parse", "HEAD").decode().strip()

    def ledger_bytes(self):
        return ledger.read_ledger(os.path.join(self.c, "sealed", "ledger.jsonl"))

    def records(self):
        return ledger.verify_chain(self.ledger_bytes())

    def tick(self):
        self.now += datetime.timedelta(hours=1)
        return self.now

    def seal(self, store=None, runner=None):
        with mock.patch.object(ledger, "PROJECT_ROOT", self.c):
            return seal_order4.seal(store or self.store, self.tick(), "ots", runner=runner or tw.FakeOts())

    def build(self, store=None):
        """書かずに中身だけを作る（作り物の記録の元）。"""
        data = self.ledger_bytes()
        with tempfile.TemporaryDirectory() as tmp:
            return seal_order4.build_doc(self.c, data, ledger.verify_chain(data), store or self.store, tmp)

    def verify(self, *args):
        return tl.run_verify_inproc(self.c, *args)

    def verify_zero(self, *args):
        code, out, err = self.verify(*args)
        self.assertEqual(code, 0, err)
        return out

    def verify_stops(self, text, *args):
        code, _out, err = self.verify(*(args or ("all", "--rev", "auto")))
        self.assertEqual(code, 1, err)
        self.assertRegex(err, text)

    def next_head(self, doc):
        return dict(doc, ledger_head=ledger.expected_ledger_head(self.ledger_bytes(), len(self.records()) + 1),
                    head=self.head())

    def raw(self, doc):
        """書く仕組みの照合（check_new）を飛ばして足し、コミットする（作り物の記録）。"""
        with mock.patch.object(seal_records, "check_new", lambda *a, **k: None):
            rec, _rel, _o = seal_records.write_doc_record(self.c, O4, doc, self.ledger_bytes(), "作り物（テスト）",
                                                          self.tick(), "ots", runner=tw.FakeOts())
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "作り物の stats-order4（テスト）")
        return rec

    def refuses(self, doc, text):
        """書く仕組み（check_new）は何も書かない。"""
        before = self.ledger_bytes()
        with self.assertRaisesRegex(ledger.LedgerError, text):
            seal_records.write_doc_record(self.c, O4, doc, before, "作り物（テスト）", self.tick(), "ots",
                                          runner=tw.FakeOts())
        self.assertEqual(self.ledger_bytes(), before)

    def forged(self, doc, text):
        self.refuses(doc, text)
        self.raw(doc)
        self.verify_stops(text)

    def run_blocks(self, store):
        out = []
        for block in order4_blocks():
            out.append(subprocess.run(["bash", "-e", "-o", "pipefail", "-c", block], cwd=self.c, capture_output=True,
                                      env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1", STORE=store)))
        self.assertTrue(out)
        return out


def resha(doc):
    """list を変えた作り物の list_sha256 を、list に合わせる。"""
    return dict(doc, list_sha256=ledger.sha256_hex(ledger.order4_list_bytes(doc["list"])))


# ---------------------------------------------------------------- 1. 書く → コミット → verify

class TestWrite(Clone):
    def test_write_commit_verify(self):
        before = self.head()
        rec, rel, ots, doc, commit = self.seal()
        self.assertEqual((rec["seq"], rec["kind"]), (15, O4))
        self.assertEqual(rec["targets"], [{"path": rel, "role": O4, "sha256": rec["targets"][0]["sha256"]}])
        self.assertEqual(sorted(doc), sorted(ledger.ORDER4_DOC_KEYS))
        self.assertEqual(doc["head"], before)
        lst = doc["list"]
        self.assertEqual([m["day"] for m in lst["missing_days"]], WANT_MISSING)
        self.assertEqual((lst["missing_count"], lst["partial_days_count"], lst["days_in_block"]), (3, 1, 2115))
        self.assertEqual(lst["input"]["run_id"], "4199ae53d35b918a")
        self.assertEqual(doc["list_sha256"], ledger.sha256_hex(ledger.order4_list_bytes(lst)))
        self.assertEqual({k: v["seq"] for k, v in doc["refs"].items()},
                         {"gkg_run_result": 12, "order3": 14, "periods": 1, "candidates": 2, "order1b": 6})
        want_script = ledger.sha256_hex((FAKE_SCRIPT % 0).encode("utf-8"))
        self.assertEqual(doc["code"]["script"], {"path": ledger.ORDER4_SCRIPT, "sha256": want_script})
        self.assertEqual([x["sha256"][:8] for x in doc["code"]["imports"]], ["81de229d", "21b58387", "6f25985b"])
        self.assertEqual([x["path"] for x in doc["code"]["docs"]], list(ledger.ORDER4_DOC_FILES))
        self.assertIsNotNone(ots)
        # 入口の中でコミットした（作成者とコミッタは noreply の1件、本文は決まった1行、ファイルは記録・中身・.ots だけ）
        self.assertEqual(self.head(), commit)
        got = self.git("log", "-1", "--format=%an <%ae>|%cn <%ce>|%B", commit).decode().rstrip("\n")
        self.assertEqual(got, WHO + "|" + WHO + "|" + seal_order4.ORDER4_MESSAGE)
        files = set(self.git("show", "--name-only", "--format=", commit).decode().split())
        self.assertEqual(files, {"sealed/ledger.jsonl", rel, "sealed/" + os.path.basename(ots)})
        self.assertEqual(self.git("status", "--porcelain"), b"")
        # verify：--store を渡さなければ作り直しは「照らさなかった」（0）
        out = self.verify_zero("all", "--rev", "auto")
        self.assertIn("%s seq 15（順番4）: 一覧の sha256 %s" % (O4, doc["list_sha256"]), out)
        self.assertIn("を git から照らした。記録と同じ", out)
        self.assertIn("照らさなかった：日の集計の置き場所（--store）を渡していないので、seq 15 の一覧を作り直していない", out)
        last = [l for l in out.splitlines() if l.startswith("ただし、次は照らさなかった")][0]
        self.assertIn("seq 15 の順番4の一覧の作り直し（日の集計の置き場所 --store を渡していない）", last)
        # --store を渡すと、固定した版のコードで作り直して照らす
        out = self.verify_zero("stats-order", "--rev", "auto", "--store", self.store)
        self.assertIn("一覧を作り直した。sha256 は記録の list_sha256 と同じ", out)
        self.verify_zero("all", "--rev", "auto", "--store", self.store)
        # 中身の違う置き場所では、作り直した一覧が合わない
        other = self.make_store("other", dict(SPEC, c7={"2015-10-21": 0, "2017-01-01": 0}))
        self.verify_stops("作り直した一覧の sha256", "stats-order", "--rev", "auto", "--store", other)
        # 手順書の第三者の塊も 0 で終わる。中身の違う置き場所を渡すと、作り直しの塊が止まる
        blocks = self.run_blocks(self.store)
        for r in blocks:
            self.assertEqual(r.returncode, 0, r.stderr.decode())
        self.assertIn("（順番4）", blocks[0].stdout.decode())
        self.assertIn("一覧を作り直した", blocks[1].stdout.decode())
        self.assertNotEqual(self.run_blocks(other)[1].returncode, 0)

    def test_store_failure_writes_nothing(self):
        """一覧のコードが止まれば（置き場所の中身が無い）、何も書かない。"""
        before, head = self.ledger_bytes(), self.head()
        for store, text in ((self.make_store("empty", None), "終了コード 1.*c7.json が無い"),
                            (os.path.join(self.tmp, "none"), "フォルダでない")):
            with self.subTest(store=store), self.assertRaisesRegex(ledger.LedgerError, text):
                self.seal(store)
            self.assertEqual((self.ledger_bytes(), self.head()), (before, head))
        self.assertEqual(self.git("status", "--porcelain"), b"")

    def test_dirty_tree_refused(self):
        self.put_script(FAKE_SCRIPT % 5)
        before = self.ledger_bytes()
        with self.assertRaisesRegex(ledger.LedgerError, "作業ツリーがきれいでない"):
            self.seal()
        self.assertEqual(self.ledger_bytes(), before)

    def test_main_prints_after_commit(self):
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(ledger, "PROJECT_ROOT", self.c), mock.patch.object(seal_order4.stamp, "check_ots"), \
                mock.patch.object(seal_records.stamp, "stamp_seq", side_effect=ledger.LedgerError("ots が無い（テスト）")), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = seal_order4.main(["--store", self.store])
        # .ots を作れなかった：記録と中身はコミットしてある。「書いた」と知らせる
        self.assertEqual(code, 1)
        self.assertIn("止まった（順番4の記録は書いた）", err.getvalue())
        self.assertEqual(self.records()[-1]["kind"], O4)
        self.assertEqual(self.git("status", "--porcelain"), b"")
        self.assertEqual(out.getvalue(), "")


# ---------------------------------------------------------------- 2. 版の固定（作業ツリーのコードを使わない）

class TestPinnedVersion(Clone):
    def test_worktree_script_not_used(self):
        """作業ツリーの missing_days.py を、git status に出ない形（assume-unchanged）で別の版にしても、入口は HEAD の版を流し、
        記録の code.script も HEAD の版の sha256。"""
        head_sha = ledger.sha256_hex(self.git("cat-file", "blob", "HEAD:" + ledger.ORDER4_SCRIPT))
        self.git("update-index", "--assume-unchanged", "--", ledger.ORDER4_SCRIPT)
        self.put_script(FAKE_SCRIPT % 7)
        self.assertEqual(self.git("status", "--porcelain"), b"")
        _rec, _rel, _o, doc, _c = self.seal()
        self.assertEqual(doc["code"]["script"]["sha256"], head_sha)
        self.assertEqual(doc["list"]["c7_denominator_by_day"]["2016-06-01"], 1000)   # HEAD の版（VARIANT 0）の値

    def test_new_head_version_is_pinned(self):
        """HEAD の版を変えてコミットすれば、記録はその版を縛り、verify もその版で作り直す。"""
        self.put_script(FAKE_SCRIPT % 3)
        self.git("commit", "-q", "-am", "仮の一覧のコードの別の版（テスト）")
        _rec, _rel, _o, doc, _c = self.seal()
        self.assertEqual(doc["list"]["c7_denominator_by_day"]["2016-06-01"], 1003)
        self.verify_zero("stats-order", "--rev", "auto", "--store", self.store)


# ---------------------------------------------------------------- 3. 作り物

class TestForgeries(Clone):
    def test_twice(self):
        """二度書く：入口は2件目を書かない。照合を飛ばして足した2件目は verify が止める。"""
        rec, _rel, _o, doc, _c = self.seal()
        before = self.ledger_bytes()
        with self.assertRaisesRegex(ledger.LedgerError, "もう seq %d にある" % rec["seq"]):
            self.seal()
        self.assertEqual(self.ledger_bytes(), before)
        self.forged(self.next_head(dict(doc, refs=doc["refs"])), "もう seq %d にある" % rec["seq"])

    def test_list_sha_not_matching(self):
        """一覧を変えて、list_sha256 をそのままにする。"""
        doc = self.next_head(self.build())
        lst = dict(doc["list"], c7_denominator_by_day=dict(doc["list"]["c7_denominator_by_day"], **{"2016-06-01": 999}))
        self.forged(dict(doc, list=lst), "list_sha256 が、list の JSON")
        doc2 = dict(doc, list_sha256="0" * 64)
        self.refuses(self.next_head(doc2), "list_sha256 が、list の JSON")

    def test_list_inconsistent(self):
        """一覧の中のつじつまを壊す（list_sha256 は合わせる）：分母が0の日を欠けた日から外す、件数、72本以上の日を欠けた日に
        する、区画、参照、マニフェスト、コードの sha256、72。72本未満の日を欠けた日から外す形は、記録だけでは見つけられない
        （欠けた日でない日の files_ok は一覧に無い）。それは --store の作り直しで止まる（test_list_content_consistent_forgery と
        同じ）。"""
        doc = self.next_head(self.build())
        lst = doc["list"]
        cases = {
            "分母が0の日を外す": (dict(lst, missing_days=[m for m in lst["missing_days"] if m["day"] != "2015-10-21"],
                                    missing_count=2), "zero_c7_denominator_days"),
            "件数": (dict(lst, missing_count=2), "missing_count"),
            "72本以上なのに欠けた日": (dict(lst, missing_days=[dict(m, files_ok=80, below_min_files=False)
                                                       if m["day"] == "2020-10-01" else m for m in lst["missing_days"]]),
                                "欠けた日の規則"),
            "区画": (dict(lst, block=dict(lst["block"], end="2020-12-13")), "method の区画"),
            "gkg-run-result": (dict(lst, input=dict(lst["input"], gkg_run_result_seq=9)), "gkg-run-result の seq"),
            "マニフェスト": (dict(lst, input=dict(lst["input"], manifest_lines=2117)), "manifest_lines"),
            "コードの sha256": (dict(lst, rule=dict(lst["rule"], counting_py_sha256="a" * 64)), "counting_py_sha256"),
            "72": (dict(lst, rule=dict(lst["rule"], min_present_slots=71)), "96・72"),
        }
        for name, (bad, text) in cases.items():
            with self.subTest(name=name):
                self.refuses(resha(dict(doc, list=bad)), text)
        self.forged(resha(dict(doc, list=cases["分母が0の日を外す"][0])), "zero_c7_denominator_days")

    def test_list_content_consistent_forgery(self):
        """一覧の中身を偽る（つじつまは合わせ、list_sha256 も合わせる）：記録だけでは見つけられない。--store で作り直すと止まる。"""
        doc = self.next_head(self.build())
        lst = dict(doc["list"], c7_denominator_by_day=dict(doc["list"]["c7_denominator_by_day"], **{"2016-06-01": 999}))
        self.raw(resha(dict(doc, list=lst)))
        out = self.verify_zero("all", "--rev", "auto")
        self.assertIn("一覧を作り直していない", out)
        self.verify_stops("作り直した一覧の sha256", "all", "--rev", "auto", "--store", self.store)

    def test_code_version(self):
        """コードの版を偽る：script の sha256 を T-093 の版のものに、imports・docs・tree を別の値に。"""
        doc = self.next_head(self.build())
        code = doc["code"]
        cases = {
            "imports": (dict(code, imports=[dict(code["imports"][0], sha256="b" * 64)] + code["imports"][1:]),
                        "封印の記録（periods・candidates・順番1b）が縛る値と違う"),
            "docs": (dict(code, docs=[dict(code["docs"][0], sha256="c" * 64), code["docs"][1]]), "コードの版を偽っている"),
            "tree": (dict(code, tree=dict(code["tree"], files=code["tree"]["files"] + 1)), "コードの版を偽っている"),
        }
        for name, (bad, text) in cases.items():
            with self.subTest(name=name):
                self.refuses(dict(doc, code=bad), text)
        self.forged(dict(doc, code=dict(code, script=dict(code["script"], sha256=T093_SHA))), "コードの版を偽っている")

    def test_head_not_written_head(self):
        """head を、記録を足す直前の記録を持たない commit（順番3の記録の一つ前のコミット）にする。書く仕組みは head が今の
        HEAD でないので書かず、照合を飛ばして足すと、verify が head の版の記録で止める。"""
        doc = self.build()
        prev = self.git("rev-parse", fixed_records.ORDER3_COMMIT + "~1").decode().strip()
        bad = dict(self.next_head(doc), head=prev)
        self.refuses(bad, "の記録の head %s が、今の HEAD" % prev[:12])
        self.raw(bad)
        self.verify_stops("の版の sealed/ledger.jsonl が、この記録を足す直前の記録")

    def test_refs(self):
        doc = self.next_head(self.build())
        for k, seq in (("gkg_run_result", 9), ("order3", 13), ("order1b", 5)):
            with self.subTest(ref=k):
                rec = [r for r in self.records() if r["seq"] == seq][0]
                self.refuses(dict(doc, refs=dict(doc["refs"], **{k: ledger.record_ref(rec)})), "refs が、記録から決まる参照")


class TestOrderBeforeOrder3(Clone):
    """順序を偽る：順番3の記録の無い記録（seq 1〜10）の clone では、入口は書かず、照合を飛ばして足した記録は verify が止める。"""

    commit_id = fixed_records.ORDER2_COMMIT

    def test_before_order3(self):
        text = "順番3（stats-order3）の記録より前に、順番4の記録は置けない"
        before = self.ledger_bytes()
        with self.assertRaisesRegex(ledger.LedgerError, text):
            self.seal()
        self.assertEqual(self.ledger_bytes(), before)
        doc = self.next_head({"kind": O4, "list": {}, "list_sha256": "0" * 64, "refs": {}, "code": {}, "python": "3"})
        self.forged(doc, text)


class TestPositionUnit(unittest.TestCase):
    """位置の照合（ledger.check_order4_position）を、記録の並びだけで確かめる。"""

    def recs(self, kinds):
        return [{"seq": i + 1, "kind": k} for i, k in enumerate(kinds)]

    def test_position(self):
        ok = ["periods", "candidates", ledger.ORDER3_ATTEMPT_KIND, ledger.ORDER3_KIND]
        ledger.check_order4_position(self.recs(ok), 5)
        cases = {
            "順番3が無い": (["periods", ledger.ORDER3_ATTEMPT_KIND], "順番3（stats-order3）の記録より前"),
            "threshold-access のあと": (ok + [ledger.THRESHOLD_ACCESS_KIND], "threshold-access の記録（seq 5）より後"),
            "threshold-access が順番3より前": ([ledger.THRESHOLD_ACCESS_KIND] + ok, "threshold-access の記録（seq 1）より後"),
            "二度目": (ok + [O4], "もう seq 5 にある"),
        }
        for name, (kinds, text) in cases.items():
            with self.subTest(name=name), self.assertRaisesRegex(ledger.LedgerError, re.escape(text)):
                ledger.check_order4_position(self.recs(kinds), len(kinds) + 1)
        # 順番4のあとの threshold-access は、順番4の位置を変えない
        ledger.check_order4_position(self.recs(ok + [O4, ledger.THRESHOLD_ACCESS_KIND]), 5)

    def test_before_kinds(self):
        self.assertEqual(ledger.ORDER4_BEFORE_KINDS, (ledger.THRESHOLD_ACCESS_KIND,))
        self.assertIn(O4, ledger.ALLOWED_KINDS)
        self.assertIn(O4, seal_records.WRITTEN_KINDS)


# ---------------------------------------------------------------- 4. 順番5の記録が順番4を参照すること

class TestOrder5Ref(Clone):
    def test_ref_order4(self):
        rec, _rel, _o, doc, _c = self.seal()
        records = self.records()
        read = lambda r, role: ledger.read_target_json(self.c, r, role)  # noqa: E731
        o5 = {"seq": rec["seq"] + 1, "kind": "stats-order5"}
        want = dict(ledger.record_ref(rec), list_sha256=doc["list_sha256"])
        self.assertEqual(ledger.order4_ref(records, o5["seq"], read), want)
        ledger.check_ref_order4(records, o5, want, read)
        bad = {
            "seq": dict(want, seq=14),
            "行の sha256": dict(want, record_sha256="0" * 64),
            "一覧の sha256": dict(want, list_sha256="0" * 64),
            "参照が無い": None,
        }
        for name, ref in bad.items():
            with self.subTest(name=name), self.assertRaisesRegex(ledger.LedgerError, "順番4の記録（seq 15）"):
                ledger.check_ref_order4(records, o5, ref, read)
        # 順番4より前の記録（順番4が無い位置）は、順番4を参照できない
        with self.assertRaisesRegex(ledger.LedgerError, "順番4（stats-order4）の記録が無い"):
            ledger.check_ref_order4(records, {"seq": rec["seq"], "kind": "stats-order5"}, want, read)
        # 順番4が2件ある並び（照合を飛ばした形）でも止まる
        two = records + [dict(rec, seq=rec["seq"] + 1)]
        with self.assertRaisesRegex(ledger.LedgerError, "2 件ある"):
            ledger.order4_ref(two, rec["seq"] + 2, read)


# ---------------------------------------------------------------- 5. --commit-written

class TestCommitWritten(Clone):
    def test_commit_fails_then_commit_written(self):
        before = self.head()
        with t78.write_with(lambda p: open(os.path.join(p, ".git", "index.lock"), "w").close()), \
                self.assertRaisesRegex(seal_order4.Order4Written, "作業ツリーに書いたが、コミットしていない"):
            self.seal()
        os.rename(os.path.join(self.c, ".git", "index.lock"), os.path.join(self.tmp, "index.lock.moved"))
        self.assertEqual(self.head(), before)
        self.assertEqual(self.records()[-1]["kind"], O4)
        # 順番3の入口の --commit-written は、最後の記録が順番4のときはコミットしない
        with self.assertRaisesRegex(ledger.LedgerError, "最後の記録が stats-order3-attempt・stats-order3 でない"):
            seal_order2.commit_written(self.c, ledger.ORDER3_KINDS, {})
        err = io.StringIO()
        with mock.patch.object(ledger, "PROJECT_ROOT", self.c), contextlib.redirect_stdout(io.StringIO()), \
                contextlib.redirect_stderr(err):
            code = seal_order4.main(["--commit-written"])
        self.assertEqual(code, 0, err.getvalue())
        got = self.git("log", "-1", "--format=%an <%ae>|%cn <%ce>|%B").decode().rstrip("\n")
        self.assertEqual(got, WHO + "|" + WHO + "|" + seal_order4.ORDER4_MESSAGE)
        self.verify_zero("all", "--rev", "auto", "--store", self.store)


# ---------------------------------------------------------------- 6. 本物の一覧のコード（T-093 の版）を固定した版のフォルダで流す

class TestRealScriptGate(Clone):
    """clone（seq 1〜14）の HEAD の版の本物の missing_days.py を、固定した版のフォルダで空の置き場所に当てて流す。関門
    （official_day_records・gkg-run-result）と中で使うコードの照合を通り、最初の日の集計の sha256 の照合で止まる。"""

    fake = False

    def test_real_script(self):
        repo = verify.Repo(self.c)
        head = self.head()
        tree = verify.order4_tree(repo, head)
        code = verify.order4_code(repo, head, tree)
        self.assertEqual(code["script"]["sha256"], T093_SHA)
        records = self.records()
        read = lambda r, role: ledger.read_target_json(self.c, r, role)  # noqa: E731
        refs = ledger.order4_refs(records, len(records) + 1, read)
        ledger.check_order4_imports(refs, read, {x["path"]: x["sha256"] for x in code["imports"]}, "テスト")
        empty = self.make_store("empty", None)
        with tempfile.TemporaryDirectory() as tmp, \
                self.assertRaisesRegex(ledger.LedgerError, "終了コード 1.*2015-03-02：日の集計 gkg-official-4199ae53d35b918a-day-"
                                                           "20150302.tsv.gz の sha256 が、day の行と一致しない"):
            verify.run_order4(tree, empty, tmp, "テスト")
        before = self.ledger_bytes()
        with self.assertRaisesRegex(ledger.LedgerError, "day の行と一致しない"):
            self.seal(empty)
        self.assertEqual(self.ledger_bytes(), before)


# ---------------------------------------------------------------- 7. T-091 の軽-2：halt（input）の reason の照合

class TestHaltInputReason(t90.O3Case):
    """halt（input）の試みの reason を書き換えた作り物は、同じ入力の差し替えのもとでも verify が止める（reason の文の照合を
    外すと、このテストは落ちる）。"""

    def test_reason_checked(self):
        self.o2()
        real = ledger.order3_gate_inputs

        def broken(records, seq, tc, read_json):
            d = real(records, seq, tc, read_json)
            return dict(d, order2_records=d["order2_records"] + [{"seq": 1, "status": "decided", "stop_kind": None,
                                                                  "ref_1b_seq": 999}])
        with mock.patch.object(ledger, "order3_gate_inputs", broken):
            adoc = self.attempt()["attempt"][3]
            self.assertEqual(adoc["halt"]["cause"], "input")
            self.verify_zero("all")
            bad = dict(adoc, halt=dict(adoc["halt"], reason=verify.order3_input_halt_reason("作り物の文")))
            self.raw(t90.A3, t90.rehead(self.next_head(bad), self.head()))
            self.verify_stops(re.escape("入力を受け付けない（ValueError: ") + ".*" + re.escape("記録の halt の reason と合わない"),
                              "all")


# ---------------------------------------------------------------- 8. 手順書

class TestDoc(unittest.TestCase):
    def test_doc_mentions(self):
        with open(DOC, encoding="utf-8") as f:
            text = f.read()
        self.assertIn("## 18. 順番4の封印（stats-order4。T-095）", text)
        self.assertEqual(len(order4_blocks()), 2)
        self.assertNotIn("この文書は、まだ無い", text)                       # T-091 の軽-1
        self.assertIn("seal_order4.py --store", text)


if __name__ == "__main__":
    unittest.main()
