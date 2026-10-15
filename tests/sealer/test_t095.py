"""T-095 のテスト：順番4（手法を作る期間の区画の、欠けた日の一覧）の記録（stats-order4）を書く入口
（src/sealer/seal_order4.py）と、それを照らす仕組み（ledger.check_order4_records、verify.check_order4_git・
check_order4_rules・recount_order4）。あわせて、順番5の記録が順番4を参照することを求める関数（ledger.check_ref_order4）と、
T-091 の監査の軽-2（halt（input）の reason の照合）。差し戻し1回目で、一覧を封印済みのコード（candidates.py・counting.py）と
マニフェストだけで照らす形（中-1）、追記の前に止まったときに中身を残さない順（軽-1）、照合を外すと落ちるテスト（軽-2）を足した。

実行（プロジェクトのルートで）:
    PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -B -m unittest discover -s tests/sealer -v

書くのは、本物の記録の固定したコミット（fixed_records.ORDER3_COMMIT。seq 1〜14。fixed_records.ORDER2_COMMIT。seq 1〜10）の
clone と、仮のプロジェクト（test_t090.O3Case）の中だけ。ots は偽物。本物の sealed/・data/ には書かない。順番4を本物の記録で
実行しない。日の集計（LACIE SHARE）は読まない。
- 書く→コミット→verify の流れは、clone の中で src/stats/missing_days.py をテストの仮の一覧のコード（fake()）に置き換えて
  確かめる。仮のコードは、clone のマニフェスト（本物。seq 12 が縛る先頭）の day の行の files_ok と、合成の置き場所の日の集計
  （test_t078.day_gz。本物の file_name で置く）から一覧を作る。72本の条件と、分母を0とみなす条件は、引数で変えられる
  （規則を変えた仮のコードのテスト）。
- 合成の日の集計の sha256 は、本物の day の行の sha256 と違う。そこで verify の C7 の分母の数え直し（--store）だけは、
  ledger.order4_day_rows を包んで、本物のマニフェストの照合（先頭の sha256）を通ったあとの day の行の sha256 を、合成の
  置き場所の値に置き換える（sealed_rows）。files_ok などほかの欄は変えない。
- 本物の missing_days.py（T-093 の版）は、clone の中で固定した版のフォルダに取り出し、空の置き場所で流して、関門と
  コードの照合を通ったあとで、最初の日の集計の sha256 の照合で止まることだけを確かめる（本物の日の集計は開かない）。
"""

import contextlib
import datetime
import glob
import io
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

# テストの仮の一覧のコード（clone の中の src/stats/missing_days.py に置く）。流したフォルダの封印の記録から正式な run の
# gkg-run-result を探し、それが縛るマニフェストの先頭の day の行の files_ok と、置き場所の日の集計の C7 の分母（同じ
# フォルダの counting.py で数える）から、本物の missing_days.py と同じ形の JSON を出す。
# @MIN@：欠けた日とする本数の下限（規則どおりは 72）。@ZERO@：この値より小さい分母を0とみなす（規則どおりは 1）。
# @VARIANT@：rule.source の末尾に入る値（版を変えると出力が変わるようにするため）。
FAKE_TEMPLATE = r'''#!/usr/bin/env python3
"""テストの仮の一覧のコード（T-095 のテストが clone の中だけに置く）。"""
import datetime
import hashlib
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "src", "sealer"))
sys.path.insert(0, HERE)
import counting  # noqa: E402
import ledger  # noqa: E402

MIN_FILES = @MIN@
ZERO_BELOW = @ZERO@
VARIANT = @VARIANT@
C7_ADD = @C7ADD@


def sha(rel):
    with open(os.path.join(ROOT, rel), "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def main(argv):
    if len(argv) != 2 or argv[0] != "--store":
        sys.stderr.write("missing_days: 使い方は --store <置き場所>\n")
        return 2
    store = argv[1]
    recs = ledger.verify_chain(ledger.read_ledger(os.path.join(ROOT, "sealed", "ledger.jsonl")))
    read = lambda r, role: ledger.read_target_json(ROOT, r, role)  # noqa: E731
    rec = [r for r in recs if r["kind"] == ledger.GKG_RESULT_KIND and read(r, r["kind"])["mode"] == "official"][0]
    doc = read(rec, ledger.GKG_RESULT_KIND)
    with open(os.path.join(ROOT, doc["manifest_path"]), "rb") as f:
        prefix = b"".join(x + b"\n" for x in f.read().split(b"\n")[:doc["manifest_lines"]])
    rows = {}
    for raw in prefix.split(b"\n"):
        if raw.strip():
            r = json.loads(raw)
            if r.get("kind") == "day" and r.get("run_id") == doc["run_id"]:
                rows[r["day"]] = r
    days = sorted(rows)
    c7 = {}
    for x in days:
        path = os.path.join(store, rows[x]["file_name"])
        if not os.path.isfile(path):
            sys.stderr.write("missing_days: 止まった：日の集計 %s が無い\n" % rows[x]["file_name"])
            return 1
        with open(path, "rb") as f:
            s = counting.parse_day(f.read(), expect_day=x, expect_mode="official")
        v = counting.candidate_counts(s, counting.OFFICIAL_CANDIDATE)[1]
        c7[x] = 0 if v < ZERO_BELOW else v + C7_ADD
    missing, partial = [], 0
    for x in days:
        f = rows[x]["files_ok"]
        if f < MIN_FILES or c7[x] == 0:
            missing.append({"day": x, "files_ok": f, "files_listed": rows[x]["files_listed"], "c7_denominator": c7[x],
                            "below_min_files": f < 72, "zero_c7_denominator": c7[x] == 0})
        elif f < 96:
            partial += 1
    out = {
        "label": "missing-days-method-v3",
        "block": {"name": "method", "start": days[0], "end": days[-1]},
        "rule": {"source": "docs/stats/candidates.md 3章 (5)（seq 2）（VARIANT %d）" % VARIANT,
                 "function": "src/stats/candidates.py day_is_missing(present_slots, total_volume)",
                 "slots_per_day": 96, "min_present_slots": 72, "present_slots": "files_ok of the manifest day row",
                 "total_volume": "official C7 denominator of the day", "official_candidate": counting.OFFICIAL_CANDIDATE,
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


def fake(min_files=72, zero_below=1, variant=0, c7_add=0):
    """c7_add：0 でない分母に足す値（分母を偽る版。T-100）。"""
    return (FAKE_TEMPLATE.replace("@MIN@", str(min_files)).replace("@ZERO@", str(zero_below))
            .replace("@VARIANT@", str(variant)).replace("@C7ADD@", str(c7_add)))


# 合成の置き場所で C7 の分母が0になる日（どれも、本物の files_ok では72本以上の日）
ZERO_DAYS = ("2016-06-01", "2018-02-03")


def order4_blocks():
    with open(DOC, encoding="utf-8") as f:
        return re.findall(r"<!-- test:order4 -->\n```sh\n(.*?)```", f.read(), re.S)


class Clone(unittest.TestCase):
    """本物の記録の固定したコミットの clone。fake が真なら、src/stats/missing_days.py をテストの仮の一覧のコード（規則
    どおりの版）にしてコミットする（clone の中だけ）。正式な run の gkg-run-result がある clone では、合成の置き場所
    （ZERO_DAYS の分母が0）を作る。"""

    commit_id = fixed_records.ORDER3_COMMIT
    fake = True

    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.addCleanup(self.td.cleanup)
        self.tmp = self.td.name
        self.c = os.path.join(self.tmp, "c")
        code = "worktree" if os.environ.get("SEALER_DOC_TEST_WORKTREE") == "1" else "head"
        fixed_records.checkout(self.c, self.commit_id, code=code)
        self.now = datetime.datetime(2026, 10, 16, 0, 0, 0, tzinfo=UTC)
        self.rows = self.manifest_rows()
        self.store, self.store_shas = self.make_store("store", ZERO_DAYS)
        if self.fake:
            self.put_script(fake())
            self.git("add", "--", ledger.ORDER4_SCRIPT)
            self.git("commit", "-q", "-m", "テストの仮の一覧のコード（clone の中だけ）")

    def manifest_rows(self):
        """clone の正式な run の day の行（gkg-run-result が縛る先頭から）。正式な run の結果が無ければ {}。"""
        records = self.records()
        read = lambda r, role: ledger.read_target_json(self.c, r, role)  # noqa: E731
        res = [r for r in records if r["kind"] == ledger.GKG_RESULT_KIND and read(r, r["kind"])["mode"] == "official"]
        if not res:
            return {}
        gdoc = read(res[0], ledger.GKG_RESULT_KIND)
        with open(os.path.join(self.c, gdoc["manifest_path"]), "rb") as f:
            body = f.read()
        return ledger.order4_day_rows(body, gdoc, ledger._block_days("2015-03-02", "2020-12-14"))

    def make_store(self, name, zero_days=None):
        """合成の置き場所。zero_days が None なら空のフォルダ。返り値: (パス, {日: sha256})。"""
        path = os.path.join(self.tmp, name)
        os.makedirs(path)
        shas = {}
        if zero_days is not None:
            for d, r in self.rows.items():
                data = t78.day_gz(d, "official", c7=d not in zero_days)
                with open(os.path.join(path, r["file_name"]), "wb") as f:
                    f.write(data)
                shas[d] = ledger.sha256_hex(data)
        return path, shas

    @contextlib.contextmanager
    def sealed_rows(self):
        """verify の数え直しが使う day の行の sha256 を、合成の置き場所（self.store）の値にする（本物のマニフェストの照合を
        通ったあとで置き換える）。"""
        real = ledger.order4_day_rows

        def wrapped(body, gdoc, days):
            return {d: dict(r, sha256=self.store_shas[d]) for d, r in real(body, gdoc, days).items()}
        with mock.patch.object(ledger, "order4_day_rows", wrapped):
            yield

    def want_missing(self):
        return sorted({d for d, r in self.rows.items() if r["files_ok"] < 72} | set(ZERO_DAYS))

    def put_script(self, text):
        with open(os.path.join(self.c, *ledger.ORDER4_SCRIPT.split("/")), "w", encoding="utf-8") as f:
            f.write(text)

    def commit_script(self, text, msg="仮の一覧のコードの別の版（テスト）"):
        self.put_script(text)
        self.git("commit", "-q", "-am", msg)

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
        """入口で書く。書く前の照合（check_new）の C7 の分母の数え直しは、合成の置き場所の sha256 で行う（sealed_rows）。"""
        with mock.patch.object(ledger, "PROJECT_ROOT", self.c), self.sealed_rows():
            return seal_order4.seal(store or self.store, self.tick(), "ots", runner=runner or tw.FakeOts())

    def build(self, store=None):
        """書かずに中身だけを作る（作り物の記録の元）。"""
        data = self.ledger_bytes()
        with tempfile.TemporaryDirectory() as tmp:
            return seal_order4.build_doc(self.c, data, ledger.verify_chain(data), store or self.store, tmp)

    def verify(self, *args):
        with self.sealed_rows():
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

    def refuses(self, doc, text, note="作り物（テスト）"):
        """書く仕組み（check_new）は何も書かない。"""
        before = self.ledger_bytes()
        with self.assertRaisesRegex(ledger.LedgerError, text):
            seal_records.write_doc_record(self.c, O4, doc, before, note, self.tick(), "ots", runner=tw.FakeOts())
        self.assertEqual(self.ledger_bytes(), before)

    def forged(self, doc, text):
        self.refuses(doc, text)
        self.raw(doc)
        self.verify_stops(text)

    def content_files(self):
        return sorted(os.path.basename(x) for x in glob.glob(os.path.join(self.c, "sealed", O4 + "-*.json")))

    def run_blocks(self):
        out = []
        for block in order4_blocks():
            out.append(subprocess.run(["bash", "-e", "-o", "pipefail", "-c", block], cwd=self.c, capture_output=True,
                                      env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1")))
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
        self.assertEqual([m["day"] for m in lst["missing_days"]], self.want_missing())
        self.assertEqual((lst["missing_count"], lst["days_in_block"]), (48 + len(ZERO_DAYS), 2115))
        self.assertEqual(lst["input"]["run_id"], "4199ae53d35b918a")
        self.assertEqual(doc["list_sha256"], ledger.sha256_hex(ledger.order4_list_bytes(lst)))
        self.assertEqual({k: v["seq"] for k, v in doc["refs"].items()},
                         {"gkg_run_result": 12, "order3": 14, "periods": 1, "candidates": 2, "order1b": 6})
        self.assertEqual(doc["code"]["script"], {"path": ledger.ORDER4_SCRIPT,
                                                 "sha256": ledger.sha256_hex(fake().encode("utf-8"))})
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
        # verify：72本の条件はいつも照らす。--store を渡さなければ C7 の分母の数え直しは「照らさなかった」（0）
        out = self.verify_zero("all", "--rev", "auto")
        self.assertIn("%s seq 15（順番4）: 一覧の sha256 %s" % (O4, doc["list_sha256"]), out)
        self.assertIn("を git から照らした。記録と同じ", out)
        self.assertIn("72本の条件：マニフェストの day の行 2115 日の files_ok に、封印済みの candidates.py", out)
        self.assertIn("照らさなかった：日の集計の置き場所（--store）を渡していないので、seq 15 の C7 の分母を数え直していない", out)
        last = [l for l in out.splitlines() if l.startswith("ただし、次は照らさなかった")][0]
        self.assertIn("seq 15 の順番4の C7 の分母の数え直し（日の集計の置き場所 --store を渡していない）", last)
        # --store を渡すと、封印済みの counting.py で数え直して照らす（missing_days.py は流さない）
        out = self.verify_zero("stats-order", "--store", self.store)
        self.assertIn("封印済みの counting.py で、日の集計 2115 個", out)
        self.verify_zero("all", "--rev", "auto", "--store", self.store)
        # 中身の違う置き場所（day の行の sha256 と合わない）では止まる
        other, _s = self.make_store("other", ("2017-01-01",))
        self.verify_stops("day の行の sha256 と違う", "stats-order", "--store", other)
        # 手順書の第三者の塊も 0 で終わる（日の集計を使わない塊）
        blocks = self.run_blocks()
        for r in blocks:
            self.assertEqual(r.returncode, 0, r.stderr.decode())
        self.assertIn("（順番4）", blocks[0].stdout.decode())
        self.assertIn("72本の条件", blocks[0].stdout.decode())

    def test_store_failure_writes_nothing(self):
        """一覧のコードが止まれば（置き場所に日の集計が無い）、何も書かない。中身のファイルも残らない。"""
        before, head = self.ledger_bytes(), self.head()
        empty, _s = self.make_store("empty")
        for store, text in ((empty, "終了コード 1.*日の集計 .* が無い"), (os.path.join(self.tmp, "none"), "フォルダでない")):
            with self.subTest(store=store), self.assertRaisesRegex(ledger.LedgerError, text):
                self.seal(store)
            self.assertEqual((self.ledger_bytes(), self.head()), (before, head))
        self.assertEqual(self.git("status", "--porcelain"), b"")
        self.assertEqual(self.content_files(), [])

    def test_dirty_tree_refused(self):
        self.put_script(fake(variant=5))
        before = self.ledger_bytes()
        with self.assertRaisesRegex(ledger.LedgerError, "作業ツリーがきれいでない"):
            self.seal()
        self.assertEqual(self.ledger_bytes(), before)

    def test_main_prints_after_commit(self):
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(ledger, "PROJECT_ROOT", self.c), mock.patch.object(seal_order4.stamp, "check_ots"), \
                self.sealed_rows(), \
                mock.patch.object(seal_records.stamp, "stamp_seq", side_effect=ledger.LedgerError("ots が無い（テスト）")), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = seal_order4.main(["--store", self.store])
        # .ots を作れなかった：記録と中身はコミットしてある。「書いた」と知らせる
        self.assertEqual(code, 1)
        self.assertIn("止まった（順番4の記録は書いた）", err.getvalue())
        self.assertEqual(self.records()[-1]["kind"], O4)
        self.assertEqual(self.git("status", "--porcelain"), b"")
        self.assertEqual(out.getvalue(), "")


# ---------------------------------------------------------------- 1b. 差し戻し1回目 軽-1：追記の前に止まったら、中身を残さない

class TestNoLeftover(Clone):
    def test_append_fails(self):
        """記録への追記が失敗したら、何も書いていない（一覧の入った中身のファイルも作業ツリーに無い）。"""
        before = self.ledger_bytes()
        with mock.patch.object(ledger, "append_record", side_effect=ledger.LedgerError("追記の失敗（テスト）")), \
                self.assertRaisesRegex(ledger.LedgerError, "追記の失敗（テスト）") as cm:
            self.seal()
        self.assertNotIsInstance(cm.exception, seal_order4.Order4Written)
        self.assertEqual(self.ledger_bytes(), before)
        self.assertEqual(self.content_files(), [])
        self.assertEqual(self.git("status", "--porcelain"), b"")

    def test_check_new_fails(self):
        """書く前の照合で止まったときも、中身のファイルは残らない。"""
        with mock.patch.object(verify, "check_order4_git", side_effect=ledger.LedgerError("照合の失敗（テスト）")), \
                self.assertRaisesRegex(ledger.LedgerError, "照合の失敗（テスト）"):
            self.seal()
        self.assertEqual(self.content_files(), [])
        self.assertEqual(self.git("status", "--porcelain"), b"")

    def test_content_write_fails_after_append(self):
        """追記のあとで中身を書けなかったときは、「書いた」と知らせ（Order4Written）、コミットしない。"""
        real = ledger.write_once

        def failing(path, content):
            if os.path.basename(path).startswith(O4 + "-"):
                raise ledger.LedgerError("中身を書けない（テスト）")
            return real(path, content)
        with mock.patch.object(ledger, "write_once", failing), \
                self.assertRaisesRegex(seal_order4.Order4Written, "中身を書けなかった"):
            self.seal()
        self.assertEqual(self.records()[-1]["kind"], O4)
        self.assertEqual(self.content_files(), [])


# ---------------------------------------------------------------- 2. 版の固定（作業ツリーのコードを使わない）

class TestPinnedVersion(Clone):
    def test_worktree_script_not_used(self):
        """作業ツリーの missing_days.py を、git status に出ない形（assume-unchanged）で別の版にしても、入口は HEAD の版を流し、
        記録の code.script も HEAD の版の sha256。"""
        head_sha = ledger.sha256_hex(self.git("cat-file", "blob", "HEAD:" + ledger.ORDER4_SCRIPT))
        self.git("update-index", "--assume-unchanged", "--", ledger.ORDER4_SCRIPT)
        self.put_script(fake(variant=7))
        self.assertEqual(self.git("status", "--porcelain"), b"")
        _rec, _rel, _o, doc, _c = self.seal()
        self.assertEqual(doc["code"]["script"]["sha256"], head_sha)
        self.assertTrue(doc["list"]["rule"]["source"].endswith("（VARIANT 0）"))      # HEAD の版の出力

    def test_new_head_version_is_pinned(self):
        """HEAD の版を（規則を変えずに）変えてコミットすれば、記録はその版を縛る。照合は封印済みのコードで行うので、
        規則どおりの版なら --store の数え直しも通る。"""
        self.commit_script(fake(variant=3))
        _rec, _rel, _o, doc, _c = self.seal()
        self.assertTrue(doc["list"]["rule"]["source"].endswith("（VARIANT 3）"))
        self.verify_zero("all", "--rev", "auto", "--store", self.store)


# ---------------------------------------------------------------- 2b. 差し戻し1回目 中-1：規則を変えた一覧のコード

class TestDoctoredRules(Clone):
    def test_min_files_changed(self):
        """72本の条件を10本に変えた版をコミットしてから書く：書く仕組みは何も書かない（封印済みの candidates.py をマニフェストの
        files_ok に当てた結果と合わない）。照合を飛ばして足すと、日の集計を持たない verify が止める。"""
        text = "below_min_files が、封印済みの candidates.py の day_is_missing をマニフェストの files_ok に当てた結果と違う"
        self.commit_script(fake(min_files=10))
        before = self.ledger_bytes()
        with self.assertRaisesRegex(ledger.LedgerError, text):
            self.seal()
        self.assertEqual(self.ledger_bytes(), before)
        self.assertEqual(self.content_files(), [])
        doc = self.next_head(self.build())
        self.assertLess(doc["list"]["missing_count"], 48)
        self.raw(doc)
        self.verify_stops(text)                                  # --store なし
        code, out, err = tl.run_verify_inproc(self.c, "stats-order")
        self.assertEqual(code, 1)

    def test_zero_rule_changed(self):
        """分母を0とみなす条件を変えた版（分母が12より小さい日を0にする）：一覧の中のつじつまは合い、72本の条件も合う。
        書く仕組みは、置き場所の日の集計を封印済みの counting.py で数え直して止める（T-100）。照合を飛ばして足すと、--store
        なしの verify は止められず、--store の verify が止める。"""
        text = "C7 の分母が、封印済みの counting.py で日の集計から数え直した値と違う"
        self.commit_script(fake(zero_below=12))
        before = self.ledger_bytes()
        with self.assertRaisesRegex(ledger.LedgerError, text):
            self.seal()
        self.assertEqual(self.ledger_bytes(), before)
        self.assertEqual(self.content_files(), [])
        doc = self.next_head(self.build())
        self.assertEqual(doc["list"]["missing_count"], 2115)
        self.raw(doc)
        self.verify_zero("all", "--rev", "auto")
        self.verify_stops(text, "all", "--rev", "auto", "--store", self.store)

    def test_c7_values_changed(self):
        """T-100（監査 P1）：分母の値そのものを偽る版（0 でない分母に 5 を足す。欠けた日は変わらない）で書こうとすると、書く
        仕組みが止める（何も書かない）。"""
        self.commit_script(fake(c7_add=5))
        before = self.ledger_bytes()
        with self.assertRaisesRegex(ledger.LedgerError, "C7 の分母が、封印済みの counting.py で日の集計から数え直した値と違う"):
            self.seal()
        self.assertEqual(self.ledger_bytes(), before)
        self.assertEqual(self.content_files(), [])
        self.assertEqual(self.git("status", "--porcelain"), b"")

    def test_writer_needs_store(self):
        """書く仕組みは、置き場所を渡さなければ順番4の記録を書かない（入口を通さずに write_doc_record を呼んだ形）。"""
        doc = self.next_head(self.build())
        self.refuses(doc, "C7 の分母を数え直してからでなければ書かない")


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
        lst = dict(doc["list"], c7_denominator_by_day=dict(doc["list"]["c7_denominator_by_day"], **{"2016-06-02": 999}))
        self.forged(dict(doc, list=lst), "list_sha256 が、list の JSON")
        doc2 = dict(doc, list_sha256="0" * 64)
        self.refuses(self.next_head(doc2), "list_sha256 が、list の JSON")

    def test_list_inconsistent(self):
        """一覧の中のつじつまを壊す（list_sha256 は合わせる）：分母が0の日を欠けた日から外す、件数、72本以上の日を欠けた日に
        する、区画、参照、マニフェスト、コードの sha256、72。"""
        doc = self.next_head(self.build())
        lst = doc["list"]
        z = ZERO_DAYS[0]
        cases = {
            "分母が0の日を外す": (dict(lst, missing_days=[m for m in lst["missing_days"] if m["day"] != z],
                                    missing_count=lst["missing_count"] - 1), "zero_c7_denominator_days"),
            "件数": (dict(lst, missing_count=2), "missing_count"),
            "72本以上なのに欠けた日": (dict(lst, missing_days=[dict(m, files_ok=80, below_min_files=False)
                                                       if m["day"] == "2015-05-29" else m for m in lst["missing_days"]]),
                                "欠けた日の規則"),
            "区画": (dict(lst, block=dict(lst["block"], end="2020-12-13")), "method の区画"),
            "gkg-run-result": (dict(lst, input=dict(lst["input"], gkg_run_result_seq=9)), "gkg-run-result の seq"),
            "マニフェスト": (dict(lst, input=dict(lst["input"], manifest_lines=2117)), "manifest_lines"),
            "コードの sha256": (dict(lst, rule=dict(lst["rule"], counting_py_sha256="a" * 64)), "counting_py_sha256"),
            "72": (dict(lst, rule=dict(lst["rule"], min_present_slots=71)), "96・72"),
            # 軽-2：below_min_files だけが files_ok と合わない（分母が0の日なので、欠けた日の規則そのものには当たる）
            "below_min_files": (dict(lst, missing_days=[dict(m, below_min_files=True) if m["day"] == z else m
                                                        for m in lst["missing_days"]]), "欠けた日の規則"),
            # 中-1：72本未満の日を欠けた日から外す（一覧の中のつじつまは合う）。マニフェストの files_ok で止まる
            "72本未満の日を外す": (dict(lst, missing_days=[m for m in lst["missing_days"] if m["day"] != "2015-05-29"],
                                     missing_count=lst["missing_count"] - 1, partial_days_count=lst["partial_days_count"] + 1),
                                "below_min_files が、封印済みの candidates.py"),
            "欠けた日の files_ok": (dict(lst, missing_days=[dict(m, files_listed=m["files_listed"] + 1) if m["day"] == "2015-05-29"
                                                         else m for m in lst["missing_days"]]),
                                 "欠けた日の files_ok・files_listed が、マニフェストの day の行と違う"),
            "一部が欠けた日の数": (dict(lst, partial_days_count=lst["partial_days_count"] - 1), "partial_days_count"),
        }
        for name, (bad, text) in cases.items():
            with self.subTest(name=name):
                self.refuses(resha(dict(doc, list=bad)), text)
        self.forged(resha(dict(doc, list=cases["72本未満の日を外す"][0])), "below_min_files が、封印済みの candidates.py")

    def test_list_content_consistent_forgery(self):
        """一覧の中身を偽る（欠けた日でない日の分母を変える。つじつまも72本の条件も合わせ、list_sha256 も合わせる）：
        日の集計を持たない verify では見つからない。--store の数え直しで止まる。"""
        doc = self.next_head(self.build())
        lst = dict(doc["list"], c7_denominator_by_day=dict(doc["list"]["c7_denominator_by_day"], **{"2016-06-02": 999}))
        self.raw(resha(dict(doc, list=lst)))
        out = self.verify_zero("all", "--rev", "auto")
        self.assertIn("C7 の分母を数え直していない", out)
        self.verify_stops("C7 の分母が、封印済みの counting.py", "all", "--rev", "auto", "--store", self.store)

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

    def test_privacy(self):
        """軽-2：記録の行（注記）に許可していないメールアドレスの形があれば、書く仕組みは何も書かない（順番4の privacy の検査）。"""
        doc = self.next_head(self.build())
        self.refuses(doc, "許可していないメールアドレスの形", note="作り物（テスト）" + t78.other_address("someone"))
        self.assertEqual(self.content_files(), [])


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
        self.assertEqual(ledger.ORDER4_BEFORE_KINDS, (ledger.THRESHOLD_ACCESS_KIND, ledger.ORDER5_ATTEMPT_KIND,
                                                     ledger.ORDER5_KIND))     # T-111 で順番5の二つを足した
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
        empty, _s = self.make_store("empty")
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
        self.assertEqual(len(order4_blocks()), 1)
        self.assertNotIn("選べるのは「封印するかどうか」だけ", text)
        self.assertNotIn("0ff14106", text[text.index("## 18."):])                 # 軽-3：値をそのまま書かない
        self.assertIn(".pth", text[text.index("## 16."):text.index("## 17.")])     # 軽-4
        self.assertIn(".pth", text[text.index("## 18."):])
        self.assertNotIn("この文書は、まだ無い", text)                       # T-091 の軽-1
        self.assertIn("seal_order4.py --store", text)


if __name__ == "__main__":
    unittest.main()
