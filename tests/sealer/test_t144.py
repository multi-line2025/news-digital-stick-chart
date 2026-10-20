"""T-144 のテスト：順番6〜8 と採点計画の記録（stats-order6-8）を書く入口（src/sealer/seal_order6_8.py）と、それを照らす仕組み
（ledger.check_order68_records・check_threshold_access_after_order68、verify.check_order68_git・rerun_order68）。

実行（プロジェクトのルートで）:
    PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -B -m unittest discover -s tests/sealer -v

書くのは、本物の記録の固定したコミット（fixed_records.ORDER68_COMMIT。seq 1〜17）の clone の中だけ。本物の記録に書き足さない。
手法を作る期間のキャッシュ（Git の外）は読まない。キャッシュが要るスクリプト（order8_fit.py・tiers_select.py・
chain_cap_check.py）を流す verify.run_order68_script だけを、clone の git の版の出力のファイルを書き出す仮のもの（FakeRun）に
差し替える（流すフォルダの組み立て、封印したコードとの照合、出力の sha256 の比べ方は本物のまま）。データを使わない出力
（periods.py・naive.py・scoring.py）は、本物のまま流し直す。
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
import test_writers as tw  # noqa: E402

ledger = tl.ledger
verify = tl.verify
import seal_access  # noqa: E402
import seal_order2  # noqa: E402
import seal_order6_8  # noqa: E402
import seal_records  # noqa: E402
import seal_triggers  # noqa: E402

O68, TRG, TA = ledger.ORDER68_KIND, ledger.TRIGGERS_KIND, ledger.THRESHOLD_ACCESS_KIND
UTC = datetime.timezone.utc
DOC = os.path.join(tl.PROJECT, "docs", "verify", "periods-seal.md")
WHO = "%s <%s>" % (seal_order2.AUTHOR_NAME, seal_order2.AUTHOR_EMAIL)
LIST = ledger.ORDER68_LIST_DOC


def order68_blocks():
    with open(DOC, encoding="utf-8") as f:
        return re.findall(r"<!-- test:order68 -->\n```sh\n(.*?)```", f.read(), re.S)


class FakeRun:
    """verify.run_order68_script の代わり：流すフォルダ（bound_dir）に置かれたファイルを確かめ、clone の git の版の出力のファイルを
    out_dir に書く。change を渡すと、その名前のファイルのバイト列を変えて書く（流し直しの結果が記録と違う形）。"""

    def __init__(self, clone, change=None):
        self.c, self.change, self.calls = clone, change, []

    def __call__(self, bound_dir, script, cache, out_dir, what):
        self.calls.append((script, sorted(os.listdir(os.path.join(bound_dir, "src", "stats")))))
        assert os.path.isfile(os.path.join(bound_dir, script)), script
        assert os.path.isfile(os.path.join(bound_dir, "sealed", "ledger.jsonl"))
        os.makedirs(out_dir)
        for s, d, names, _extra in ledger.ORDER68_RERUNS:
            if s != script:
                continue
            for n in names:
                data = subprocess.run(["git", "-C", self.c, "show", "HEAD:%s/%s" % (d, n)], check=True,
                                      capture_output=True).stdout
                if n == self.change:
                    data += b"\n"
                with open(os.path.join(out_dir, n), "wb") as f:
                    f.write(data)


class Clone(unittest.TestCase):
    """本物の記録（seq 1〜17）の clone。手法を作る期間のキャッシュの代わりの空のフォルダ（Git の外）を用意する。"""

    commit_id = fixed_records.ORDER68_COMMIT

    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.addCleanup(self.td.cleanup)
        self.tmp = self.td.name
        self.c = os.path.join(self.tmp, "c")
        code = "worktree" if os.environ.get("SEALER_DOC_TEST_WORKTREE") == "1" else "head"
        fixed_records.checkout(self.c, self.commit_id, code=code)
        self.cache = os.path.join(self.tmp, "cache")
        os.makedirs(self.cache)
        self.now = datetime.datetime(2026, 10, 21, 0, 0, 0, tzinfo=UTC)
        self.run = FakeRun(self.c)

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

    def read(self):
        return lambda r, role: ledger.read_target_json(self.c, r, role)

    @contextlib.contextmanager
    def patched(self, run=None):
        with mock.patch.object(ledger, "PROJECT_ROOT", self.c), \
                mock.patch.object(verify, "run_order68_script", run or self.run):
            yield

    def seal(self, run=None, cache=None):
        with self.patched(run):
            return seal_order6_8.seal(cache or self.cache, self.tick(), "ots", runner=tw.FakeOts())

    def verify(self, *args, run=None):
        with mock.patch.object(verify, "run_order68_script", run or self.run):
            return tl.run_verify_inproc(self.c, *args)

    def verify_zero(self, *args, run=None):
        code, out, err = self.verify(*(args or ("all", "--rev", "auto")), run=run)
        self.assertEqual(code, 0, err)
        return out

    def verify_stops(self, text, *args):
        code, _out, err = self.verify(*(args or ("all", "--rev", "auto")))
        self.assertEqual(code, 1, err)
        self.assertRegex(err, text)

    def write_triggers(self, values=None, check=True):
        """periods-triggers を1件書いてコミットする（check が偽なら、書く仕組みの照合を飛ばす）。"""
        values = dict(ledger.ORDER7_TRIGGERS) if values is None else values
        ctx = contextlib.ExitStack()
        if not check:
            ctx.enter_context(mock.patch.object(ledger, "check_triggers_append", lambda *a, **k: None))
        with ctx:
            rec, ots, _s = seal_triggers.seal(self.c, values, self.tick(), "ots", runner=tw.FakeOts())
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "periods-triggers（テスト）")
        return rec

    def build(self):
        """書かずに中身だけを作る（作り物の記録の元）。最後の periods-triggers を指す。"""
        data = self.ledger_bytes()
        recs = ledger.verify_chain(data)
        return seal_order6_8.build_doc(self.c, data, recs, ledger._last_before(recs, TRG, len(recs) + 1))

    def refuses(self, doc, text, run=None):
        """書く仕組み（check_new）は何も書かない。"""
        before = self.ledger_bytes()
        with self.patched(run), self.assertRaisesRegex(ledger.LedgerError, text):
            seal_records.write_doc_record(self.c, O68, doc, before, "作り物（テスト）", self.tick(), "ots",
                                          runner=tw.FakeOts(), order68_inputs={"cache": self.cache})
        self.assertEqual(self.ledger_bytes(), before)

    def raw(self, doc, kind=O68):
        """書く仕組みの照合（check_new）を飛ばして足し、コミットする（作り物の記録）。"""
        with mock.patch.object(seal_records, "check_new", lambda *a, **k: None):
            rec, _rel, _o = seal_records.write_doc_record(self.c, kind, doc, self.ledger_bytes(), "作り物（テスト）",
                                                          self.tick(), "ots", runner=tw.FakeOts())
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "作り物の %s（テスト）" % kind)
        return rec

    def forged(self, doc, text):
        self.refuses(doc, text)
        self.raw(doc)
        self.verify_stops(text)

    def commit_file(self, rel, data, msg="ファイルを変えた（テスト）"):
        with open(os.path.join(self.c, *rel.split("/")), "wb") as f:
            f.write(data)
        self.git("add", "--", rel)
        self.git("commit", "-q", "-m", msg)

    def file(self, rel):
        with open(os.path.join(self.c, *rel.split("/")), "rb") as f:
            return f.read()

    def set_list_sha(self, rel, data):
        """一覧の文書の、rel の行の sha256 を data の sha256 にする（統計係が一覧を直した形）。"""
        text = self.file(LIST).decode("utf-8")
        old = ledger.sha256_hex(self.file(rel))
        self.assertIn(old, text)
        return text.replace(old, ledger.sha256_hex(data)).encode("utf-8")

    def retarget(self, rel, new):
        """対象のファイル rel を new に変えてコミットし、一覧の文書の rel の行の sha256 と「最後に変えたコミット」を合わせて
        コミットする（統計係が対象と一覧を一緒に直した形）。"""
        lst = self.set_list_sha(rel, new)
        self.commit_file(rel, new)
        lines = lst.decode("utf-8").split("\n")
        lines = [re.sub(r"[0-9a-f]{40} \|$", self.head() + " |", x) if x.startswith("| " + rel) else x for x in lines]
        self.commit_file(LIST, "\n".join(lines).encode("utf-8"))

    def access(self):
        now = self.tick()
        with mock.patch.object(ledger, "PROJECT_ROOT", self.c):
            return seal_access.seal(self.c, now, "ots", drand_fetch=tw.FakeDrand(now), runner=tw.FakeOts())


# ---------------------------------------------------------------- 1. 書く → コミット → verify

class TestWrite(Clone):
    def test_write_commit_verify(self):
        before = self.head()
        out = self.seal()
        trec, _tots, tcommit = out["triggers"]
        rec, rel, ots, doc, commit = out["order68"]
        self.assertEqual((trec["seq"], trec["kind"], rec["seq"], rec["kind"]), (18, TRG, 19, O68))
        self.assertEqual(ledger.read_target_json(self.c, trec, "triggers"), ledger.ORDER7_TRIGGERS)
        self.assertEqual(rec["targets"], [{"path": rel, "role": O68, "sha256": rec["targets"][0]["sha256"]}])
        self.assertEqual(sorted(doc), sorted(ledger.ORDER68_DOC_KEYS))
        self.assertEqual(doc["head"], tcommit)
        self.assertEqual(self.git("rev-parse", tcommit + "^").decode().strip(), before)
        self.assertEqual(len(doc["targets"]), 43)
        self.assertEqual(doc["order7"]["triggers"], dict(ledger.record_ref(trec), values=ledger.ORDER7_TRIGGERS))
        self.assertEqual(doc["decisions"], ledger.expected_order68_decisions())
        self.assertFalse(doc["periods"]["rebuild"])
        self.assertEqual((doc["periods"]["lookback_days"], doc["periods"]["embargo_days"]), (400, 90))
        self.assertEqual(self.head(), commit)
        for c, msg, n in ((tcommit, seal_order6_8.TRIGGERS_MESSAGE, 3), (commit, seal_order6_8.ORDER68_MESSAGE, 3)):
            log = self.git("log", "-1", "--format=%an <%ae>%x00%cn <%ce>%x00%B", c).decode().split("\x00")
            self.assertEqual(log[:2], [WHO, WHO])
            self.assertEqual(log[2].rstrip("\n"), msg)                      # 追記行なし
            self.assertEqual(len(self.git("show", "--name-only", "--format=", c).decode().split()), n)
        self.assertEqual(self.git("status", "--porcelain"), b"")
        # キャッシュが要る3つのスクリプトは、書く前の確かめで1回ずつ流した（書く前の照合は、その結果を使う）
        self.assertEqual([s for s, _f in self.run.calls], [s for s, _d, _n, _e in ledger.ORDER68_RERUNS])
        for script, files in self.run.calls:
            self.assertNotIn("order5.py", files)                            # 閉包に無いコードは置かない
            self.assertIn("periods.py", files)
        o = self.verify_zero()
        self.assertIn("stats-order6-8 seq 19（順番6〜8 と採点計画）", o)
        self.assertIn("データを使わない出力 3 件を封印したコードで流し直した。記録と同じ", o)
        self.assertIn("--t117-cache を渡していない", o)
        o = self.verify_zero("stats-order", "--rev", "auto", "--t117-cache", self.cache)
        self.assertIn("3 個のスクリプト", o)
        self.assertNotIn("--t117-cache を渡していない", o)

    def test_reuse_triggers(self):
        """順番7の値の periods-triggers が最後の記録なら、書き足さない。"""
        t = self.write_triggers()
        out = self.seal()
        self.assertIsNone(out["triggers"])
        self.assertEqual(out["order68"][3]["order7"]["triggers"]["seq"], t["seq"])
        self.assertEqual(len(self.records()), 19)
        self.verify_zero()

    def test_second_record(self):
        """誤りの訂正は新しい記録（2件目）。関門は最後の記録を使う。"""
        self.seal()
        out = self.seal()
        self.assertIsNone(out["triggers"])
        self.assertIn("stats-order6-8 の 2 件目", out["order68"][0]["note"])
        self.verify_zero()

    def test_dirty_tree_refused(self):
        before = self.ledger_bytes()
        with open(os.path.join(self.c, "x.txt"), "w") as f:
            f.write("x")
        with self.assertRaisesRegex(ledger.LedgerError, "作業ツリーがきれいでない"):
            self.seal()
        self.assertEqual(self.ledger_bytes(), before)

    def test_rerun_mismatch_writes_nothing(self):
        """キャッシュが要る出力を流し直した結果が記録と違えば、periods-triggers も含めて何も書かない（書く前の確かめで止まる）。"""
        before, head = self.ledger_bytes(), self.head()
        with self.assertRaisesRegex(ledger.LedgerError, "流し直した出力の n3_coefs.tsv の sha256 が、記録と違う"):
            self.seal(run=FakeRun(self.c, change="n3_coefs.tsv"))
        self.assertEqual((self.ledger_bytes(), self.head()), (before, head))

    def test_python_differs_unchecked(self):
        """流し直しの Python の版が記録の python と違えば、照らせない（Unchecked）。書く仕組みはそれを理由に書かない。"""
        self.write_triggers()
        doc = self.build()
        doc = dict(doc, python="0.0.0", reruns=[dict(x, python="0.0.0") for x in doc["reruns"]])
        with self.patched(), tempfile.TemporaryDirectory() as tmp, self.assertRaisesRegex(verify.Unchecked, "0.0.0"):
            verify.rerun_order68(verify.Repo(self.c), doc, self.cache, tmp, "テスト")
        self.refuses(doc, "流し直せない")

    def test_no_cache_refused(self):
        self.write_triggers()
        self.refuses_without_cache()

    def refuses_without_cache(self):
        doc = self.build()
        before = self.ledger_bytes()
        with self.patched(), self.assertRaisesRegex(ledger.LedgerError, "キャッシュ（--t117-cache）で係数と表を流し直してから"):
            seal_records.write_doc_record(self.c, O68, doc, before, "作り物（テスト）", self.tick(), "ots", runner=tw.FakeOts())
        self.assertEqual(self.ledger_bytes(), before)

    def test_doc_blocks(self):
        """手順書20章の第三者の確かめ方の塊を、書いたあとの clone で流すと 0 で終わり、順番6〜8 の行が出る。"""
        self.seal()
        blocks = order68_blocks()
        self.assertTrue(blocks)
        for block in blocks:
            r = subprocess.run(["bash", "-e", "-o", "pipefail", "-c", block], cwd=self.c, capture_output=True,
                               env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
            self.assertEqual(r.returncode, 0, r.stderr.decode("utf-8", "replace")[-500:])
            self.assertIn("（順番6〜8 と採点計画）", r.stdout.decode("utf-8"))


# ---------------------------------------------------------------- 2. 改ざん・差し替えの作り物（書く仕組みも verify も止める）

class TestForgeries(Clone):
    def setUp(self):
        super().setUp()
        self.write_triggers()
        self.doc = self.build()

    def test_forged_docs(self):
        d = self.doc
        t0 = dict(d["targets"][0], sha256="0" * 64)
        cases = [
            ("対象の sha256 を偽る", dict(d, targets=[t0] + d["targets"][1:]), "targets が、head .* の版のファイル"),
            ("対象を1つ外す", dict(d, targets=d["targets"][1:]), "targets のパスと節が"),
            ("対象を足す", dict(d, targets=d["targets"] + [dict(d["targets"][0], path="src/stats/x.py")]),
             "targets のパスと節が"),
            ("一覧の文書の sha256", dict(d, list_doc=dict(d["list_doc"], sha256="1" * 64)), "list_doc が"),
            ("オーナーの決定の行", dict(d, decisions=[dict(d["decisions"][0], lines=["> 別の行"])] + d["decisions"][1:]),
             "decisions が"),
            ("オーナーの決定を外す", dict(d, decisions=d["decisions"][1:]), "decisions が"),
            ("順番6 を改訂ありにする", dict(d, order6=dict(d["order6"], revised=True)), "order6 が"),
            ("順番7 の値", dict(d, order7=dict(d["order7"], naive_history_days=400)), "order7 が"),
            ("順番7 の periods-triggers の参照", dict(d, order7=dict(d["order7"], triggers=dict(d["order7"]["triggers"], seq=1))),
             "order7.triggers が"),
            ("区切りの作り直しを要るにする", dict(d, periods=dict(d["periods"], rebuild=True)), "の periods が"),
            ("区画の過去分", dict(d, periods=dict(d["periods"], lookback_days=399)), "の periods が"),
            ("データを使わない出力の sha256", dict(d, data_free=[dict(d["data_free"][1], sha256="2" * 64)] + d["data_free"][1:]),
             "data_free が"),
            ("流し直しの commit", dict(d, reruns=[dict(d["reruns"][0], commit=d["head"])] + d["reruns"][1:]),
             "reruns の src/stats/order8_fit.py の commit が"),
            ("流し直しの出力", dict(d, reruns=[dict(d["reruns"][0], files=d["reruns"][0]["files"][1:])] + d["reruns"][1:]),
             "reruns の src/stats/order8_fit.py の files"),
            ("封印済みのコード", dict(d, sealed_code=d["sealed_code"][1:]), "sealed_code が"),
            ("キーを足す", dict(d, extra=1), "中身のキーが"),
        ]
        for name, doc, text in cases:
            with self.subTest(name):
                self.refuses(doc, text)

    def test_forged_target_stops_verify(self):
        """書く仕組みの照合を飛ばして、対象の sha256 を偽った記録を足すと、verify が止める。"""
        t0 = dict(self.doc["targets"][0], sha256="0" * 64)
        self.raw(dict(self.doc, targets=[t0] + self.doc["targets"][1:]))
        self.verify_stops("targets が、head .* の版のファイル")

    def test_forged_head_stops_verify(self):
        self.raw(dict(self.doc, head=self.git("rev-parse", "HEAD~1").decode().strip()))
        self.verify_stops("sealed/ledger.jsonl が、この記録を足す直前の記録")

    def test_triggers_not_last(self):
        """T-148（T-144 の監査 軽-1 の M4）：order7.triggers が、この記録より前の最後の periods-triggers でなく、それより前の
        同じ値の periods-triggers を指す記録。書く仕組みは書かず、照合を飛ばして足すと verify が止める。"""
        first = self.records()[-1]
        self.assertEqual(first["kind"], TRG)
        self.write_triggers()                                  # 同じ値の periods-triggers をもう1件（これが最後）
        doc = self.build()
        self.assertNotEqual(doc["order7"]["triggers"]["seq"], first["seq"])
        doc = dict(doc, order7=dict(doc["order7"], triggers=dict(ledger.record_ref(first), values=dict(ledger.ORDER7_TRIGGERS))))
        self.forged(doc, re.escape("order7.triggers が、この記録より前の最後の periods-triggers の記録でない"))

    def test_decision_moved_to_later_commit(self):
        """T-148（T-144 の監査 軽-1 の M7）：オーナーの決定の行を、その行を入れたコミットでなく、あとのコミット（行は第一の親の版
        にもある）に付け替えた出どころ。決まった出どころ（ORDER68_DECISIONS）ごと付け替えた場合も、git の照合が止める。"""
        later = fixed_records.ORDER68_COMMIT
        moved = tuple((i, later if n == 7 else c, p, h, ls) for n, (i, c, p, h, ls) in enumerate(ledger.ORDER68_DECISIONS, 1))
        text = "前向きの入力の作り方」（%s:reviews/T-145.md）：第一の親の版にも同じ行がある" % later[:12]
        with mock.patch.object(ledger, "ORDER68_DECISIONS", moved):
            doc = self.build()
            self.assertEqual(doc["decisions"][6]["source"], "%s:reviews/T-145.md" % later)
            self.forged(doc, re.escape(text))
        # 付け替えた出どころは、決まった出どころ（ledger の定数）と違うので、定数を戻せば git を使わない照合でも止まる
        self.verify_stops("decisions が、決まったオーナーの決定の出どころ")

    def test_head_not_current_refused(self):
        self.refuses(dict(self.doc, head=self.git("rev-parse", "HEAD~1").decode().strip()), "今の HEAD")


class TestTamperedFiles(Clone):
    """封印する前に、ファイルが一覧と食い違う・変えられた形。入口は何も書かない。"""

    def stops(self, text, run=None):
        before, head = self.ledger_bytes(), self.head()
        with self.assertRaisesRegex(ledger.LedgerError, text):
            self.seal(run=run)
        self.assertEqual((self.ledger_bytes(), self.head()), (before, head))

    def test_target_changed_without_list(self):
        """対象のファイルを変えたのに一覧の文書を直していない。"""
        self.commit_file("docs/stats/claims-scoring-plan.md", self.file("docs/stats/claims-scoring-plan.md") + b"\n")
        self.stops("一覧の文書 .* の4章の表（節・パス・sha256）が、封印する対象と同じでない")

    def test_list_row_removed(self):
        """一覧の文書から行を1つ消す（選び出し）。"""
        text = self.file(LIST).decode("utf-8").split("\n")
        text = [x for x in text if not x.startswith("| docs/stats/order8-t143/n4_coefs.tsv")]
        self.commit_file(LIST, "\n".join(text).encode("utf-8"))
        self.stops("4章の表（節・パス・sha256）が、封印する対象と同じでない")

    def test_list_commit_wrong(self):
        text = self.file(LIST).decode("utf-8").replace("82e0424a3c08ac5ec7d4c7a9c7e984df3532e045",
                                                      "265ab14a6f4ad41d2d35b0b281d2df58853f4069", 1)
        self.commit_file(LIST, text.encode("utf-8"))
        self.stops("のコミット 265ab14a6f4a が、最後に変えたコミット 82e0424a3c08 と違う")

    def test_list_commit_not_hex(self):
        """T-148：一覧の文書の「最後に変えたコミット」の欄が40桁でない行（T-147 より前の書き方）は、照らせないので止める。"""
        lines = self.file(LIST).decode("utf-8").split("\n")
        rel = "docs/stats/order8-t145/n3_coefs.tsv"
        lines = [re.sub(r"[0-9a-f]{40} \|$", "この文書と同じコミット |", x) if x.startswith("| " + rel) else x for x in lines]
        self.commit_file(LIST, "\n".join(lines).encode("utf-8"))
        self.stops(re.escape("%s の行の「最後に変えたコミット」の欄が40桁でない" % rel))

    def test_data_free_output_changed(self):
        """データを使わない出力を差し替え、一覧の sha256 も合わせた。封印したコードで流し直すと違う。"""
        rel = "docs/stats/order8-t145/naive.json"
        new = self.file(rel).replace(b"naive", b"naivE", 1)
        self.retarget(rel, new)
        self.stops("naive.py  を流し直した出力の sha256 .* が、記録の docs/stats/order8-t145/naive.json")

    def test_unsealed_code_used(self):
        """封印の対象に無いコードを、流すコードが読み込む（一覧に載っていない入力の作り方）。"""
        rel = "src/stats/explore_tiers.py"
        new = self.file(rel).replace(b"\nimport ", b"\nimport zz_extra  # noqa\nimport ", 1)
        with open(os.path.join(self.c, "src", "stats", "zz_extra.py"), "w") as f:
            f.write("X = 1\n")
        self.git("add", "--", "src/stats/zz_extra.py")
        self.retarget(rel, new)
        self.stops("zz_extra.py（commit .*）は、この記録で封印したコード（targets・sealed_code）でない")

    def test_order7_output_changed(self):
        """順番7の出力の区切りを変える（rebuild_triggers は同じ）。"""
        rel = ledger.ORDER7_OUTPUT
        out = json.loads(self.file(rel))
        out["rules"]["lookback_days"] = 401
        new = (json.dumps(out, sort_keys=True) + "\n").encode("utf-8")
        self.retarget(rel, new)
        self.stops("periods-order7.json の rules が periods の1件目の出力と違う")

    def test_decision_line_rewritten(self):
        """reviews のオーナーの発言の行を書き換える（追記だけの決まりに反する）。"""
        rel = "reviews/T-143.md"
        self.commit_file(rel, self.file(rel).replace("  > Bでいこう".encode(), "  > Aでいこう".encode()))
        self.stops("オーナーの決定「N3・N4 の学習の行」.*head .* の版で、見出しの下の決まった行が変わった")

    def test_rerun_mismatch_stops_verify(self):
        """書いたあとの verify で、流し直した出力が記録と違えば止まる。"""
        self.seal()
        code, _o, err = self.verify("stats-order", "--rev", "auto", "--t117-cache", self.cache,
                                    run=FakeRun(self.c, change="chain_cap.json"))
        self.assertEqual(code, 1)
        self.assertIn("chain_cap_check.py を流し直した出力の chain_cap.json の sha256 が、記録と違う", err)


# ---------------------------------------------------------------- 3. 欠番・行の削除

class TestMissing(Clone):
    def setUp(self):
        super().setUp()
        self.seal()
        self.path = os.path.join(self.c, "sealed", "ledger.jsonl")

    def put(self, lines):
        with open(self.path, "wb") as f:
            f.write(b"".join(x + b"\n" for x in lines))

    def test_remove_triggers_line(self):
        """periods-triggers（seq 18）の行を消すと、欠番か prev_hash で止まる。"""
        lines = ledger.split_lines(self.ledger_bytes())
        self.put(lines[:17] + lines[18:])
        code, _o, err = self.verify("all", "--rev", "auto")
        self.assertEqual(code, 1)
        self.assertRegex(err, "seq|prev_hash")

    def test_remove_last_line(self):
        """順番6〜8（seq 19）の最後の行を消すと、時刻証明（.ots）が残っているので止まる。"""
        lines = ledger.split_lines(self.ledger_bytes())
        self.put(lines[:18])
        code, _o, err = self.verify("all", "--rev", "auto")
        self.assertEqual(code, 1)
        self.assertIn("19", err)


# ---------------------------------------------------------------- 4. threshold-access の関門

class TestThresholdGate(Clone):
    def test_refused_before_order68_then_allowed(self):
        text = re.escape("threshold-access の記録（seq 18）より前に、順番6〜8（stats-order6-8）の記録が無い")
        before = self.ledger_bytes()
        with self.assertRaisesRegex(ledger.LedgerError, text):
            self.access()
        self.assertEqual(self.ledger_bytes(), before)
        self.seal()
        rec, _rel, _o = self.access()
        self.assertEqual((rec["seq"], rec["kind"]), (20, TA))
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "threshold-access（テスト）")
        self.verify_zero()
        with mock.patch.object(ledger, "PROJECT_ROOT", self.c):
            self.assertEqual(ledger.require_threshold_access()["seq"], 20)
        # threshold-access のあとに、順番6〜8 は書けない
        with self.assertRaisesRegex(ledger.LedgerError, "threshold-access の記録（seq 20）より後に、順番6〜8 の記録は置けない"):
            self.seal()

    def test_forged_access_stops_verify_and_gate(self):
        """書く仕組みの照合を飛ばして、順番6〜8 より前に threshold-access を足すと、verify と関門が止める。"""
        now = self.tick()
        with mock.patch.object(seal_records, "check_new", lambda *a, **k: None), \
                mock.patch.object(ledger, "PROJECT_ROOT", self.c):
            seal_access.seal(self.c, now, "ots", drand_fetch=tw.FakeDrand(now), runner=tw.FakeOts())
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "作り物の threshold-access（テスト）")
        self.verify_stops(re.escape("より前に、順番6〜8（stats-order6-8）の記録が無い"))
        with mock.patch.object(ledger, "PROJECT_ROOT", self.c), \
                self.assertRaisesRegex(ledger.ThresholdAccessRequired, "順番6〜8"):
            ledger.require_threshold_access()

    def test_triggers_changed_after_order68(self):
        """順番6〜8 のあとに違う値のきっかけの値を書く仕組みは拒む。照合を飛ばして足すと、threshold-access は書けない。"""
        self.seal()
        other = dict(ledger.ORDER7_TRIGGERS, network_window_days=396)
        with self.assertRaisesRegex(ledger.LedgerError, "順番6〜8 の記録（seq 19）がある。そのあとに書けるきっかけの値は"):
            with mock.patch.object(ledger, "PROJECT_ROOT", self.c):
                seal_triggers.seal(self.c, other, self.tick(), "ots", runner=tw.FakeOts())
        self.write_triggers(other, check=False)
        with self.assertRaisesRegex(ledger.LedgerError, "採用される periods-triggers（seq 20）が、最後の順番6〜8 の記録"):
            self.access()


class TestGateUnit(unittest.TestCase):
    """記録の並びだけで確かめる（read_json は、順番5の status・順番6〜8 の参照・gkg-run-result の mode を返す）。"""

    def recs(self, kinds):
        return [{"seq": i + 1, "kind": k, "note": "", "prev_hash": "0" * 64, "recorded_at": "x", "targets": []}
                for i, k in enumerate(kinds)]

    def check(self, kinds, status="ok", ref_seq=None):
        recs = self.recs(kinds)
        trg = [r for r in recs if r["kind"] == TRG]
        ref = ledger.record_ref(trg[-1] if ref_seq is None else recs[ref_seq - 1]) if trg else {"seq": 0, "record_sha256": "0"}

        def read(r, role):
            if role == ledger.ORDER5_KIND:
                return {"status": status}
            if role == O68:
                return {"order7": {"triggers": ref}}
            return {"mode": "official"}
        ledger.check_threshold_access_after_order68(recs, read)

    def test_rule(self):
        G, O3, O4, O5 = ledger.GKG_RESULT_KIND, ledger.ORDER3_KIND, ledger.ORDER4_KIND, ledger.ORDER5_KIND
        for kinds in (["periods", TA], ["periods", G, O3, O4, O5, TRG, O68, TA], ["periods", TA, G, O3],
                      ["periods", G, O3, O4, O5, TRG, O68, O68, TA]):
            with self.subTest(kinds=kinds):
                self.check(kinds)
        for kinds, text in ((["periods", G, O3, O4, TA], "status が ok の順番5"),
                            (["periods", G, O3, O4, O5, TA], "順番6〜8（stats-order6-8）の記録が無い"),
                            (["periods", G, O3, O4, O5, TA, TRG, O68], "順番6〜8（stats-order6-8）の記録が無い")):
            with self.subTest(kinds=kinds), self.assertRaisesRegex(ledger.LedgerError, re.escape(text)):
                self.check(kinds)
        with self.assertRaisesRegex(ledger.LedgerError, "status が ok の順番5"):
            self.check(["periods", G, O3, O4, O5, TRG, O68, TA], status="stopped")
        with self.assertRaisesRegex(ledger.LedgerError, "採用される periods-triggers"):
            self.check(["periods", G, O3, O4, O5, TRG, TRG, O68, TA], ref_seq=6)

    def test_position(self):
        O5 = ledger.ORDER5_KIND
        recs = self.recs(["periods", O5, TRG, O68])
        ledger.check_order68_position(recs, recs[3], lambda r, role: {"status": "ok"})
        with self.assertRaisesRegex(ledger.LedgerError, "status が ok でない"):
            ledger.check_order68_position(recs, recs[3], lambda r, role: {"status": "stopped"})
        recs = self.recs(["periods", TRG, O68])
        with self.assertRaisesRegex(ledger.LedgerError, "順番5（stats-order5）の記録がちょうど1件ない"):
            ledger.check_order68_position(recs, recs[2], lambda r, role: {"status": "ok"})
        recs = self.recs(["periods", O5, TA, O68])
        with self.assertRaisesRegex(ledger.LedgerError, "threshold-access の記録（seq 3）より後に"):
            ledger.check_order68_position(recs, recs[3], lambda r, role: {"status": "ok"})


# ---------------------------------------------------------------- 5. 部品

class TestUnits(unittest.TestCase):
    def test_closure(self):
        blobs = {"src/stats/a.py": b"import b\nimport os\nX = 'src/stats/c.py'\n", "src/stats/b.py": b"from d import x\n",
                 "src/stats/c.py": b"", "src/stats/d.py": b"", "src/stats/e.py": b""}
        self.assertEqual(verify.stats_import_closure(blobs, "src/stats/a.py"),
                         ["src/stats/a.py", "src/stats/b.py", "src/stats/c.py", "src/stats/d.py"])
        for bad in (b"m = __import__('b')\n", b"import importlib\nimportlib.import_module('b')\n"):
            with self.subTest(bad=bad), self.assertRaisesRegex(ledger.LedgerError, "静的にたどれない"):
                verify.stats_import_closure(dict(blobs, **{"src/stats/a.py": bad}), "src/stats/a.py")

    def test_run_bound(self):
        """本物の起こし方（-I・-B・空の pycache_prefix）で、同じフォルダのモジュールを読み込むスクリプトと、出力のフォルダに書く
        スクリプトを流せる。"""
        with tempfile.TemporaryDirectory() as d:
            os.makedirs(os.path.join(d, "src", "stats"))
            with open(os.path.join(d, "src", "stats", "m.py"), "w") as f:
                f.write("V = 'm'\n")
            with open(os.path.join(d, "src", "stats", "s.py"), "w") as f:
                f.write("import sys\nimport m\nprint(m.V, sys.argv[1:], sys.flags.isolated)\n")
            with open(os.path.join(d, "src", "stats", "w.py"), "w") as f:
                f.write("import os, sys\na = dict(zip(sys.argv[1::2], sys.argv[2::2]))\nos.makedirs(a['--out-dir'])\n"
                        "open(os.path.join(a['--out-dir'], 'o.txt'), 'w').write(a['--t117-cache'])\n")
            out = verify._run_bound(d, "src/stats/s.py", ["--x", "1"], "テスト", 60)
            self.assertEqual(out.decode().strip(), "m ['--x', '1'] 1")
            verify.run_order68_script(d, "src/stats/w.py", "/cache", os.path.join(d, "out"), "テスト")
            with open(os.path.join(d, "out", "o.txt")) as f:
                self.assertEqual(f.read(), "/cache")
            with self.assertRaisesRegex(ledger.LedgerError, "終了コード 1"):
                verify._run_bound(d, "src/stats/nothing.py", [], "テスト", 60)

    def test_list_rows(self):
        text = ("## 4. 一覧\n### (1) a\n| 対象 | sha256 | 最後に変えたコミット |\n|---|---|---|\n"
                "| src/x.py（説明） | %s | %s |\n| y | %s | この文書と同じコミット |\n## 5. 次\n| z | %s | %s |\n"
                % ("a" * 64, "b" * 40, "c" * 64, "d" * 64, "e" * 40))
        self.assertEqual(verify.order68_list_rows(text),
                         [("4(1)", "src/x.py", "a" * 64, "b" * 40), ("4(1)", "y", "c" * 64, None)])

    def test_constants_match_stats_code(self):
        """順番7の値 399 と、流し直すスクリプトの出力の名前が、固定したコミットの統計係のコードと同じ（import せずに ast で読む）。"""
        import ast
        c = fixed_records.ORDER68_COMMIT

        def consts(rel):
            tree = ast.parse(fixed_records.show(rel, c).decode("utf-8"))
            return {t.id: ast.literal_eval(n.value) for n in tree.body if isinstance(n, ast.Assign)
                    for t in n.targets if isinstance(t, ast.Name) and isinstance(n.value, (ast.Constant, ast.Tuple))
                    and t.id in ("NAIVE_HISTORY_DAYS", "OUT_NAMES")}
        o8 = consts("src/stats/order8_fit.py")
        self.assertEqual(o8["NAIVE_HISTORY_DAYS"], ledger.ORDER7_NAIVE_HISTORY_DAYS)
        self.assertEqual(o8["OUT_NAMES"], ledger.ORDER68_RERUNS[0][2])
        ts = consts("src/stats/tiers_select.py")
        self.assertEqual(set(ts["OUT_NAMES"]) - {"run.json"}, set(ledger.ORDER68_RERUNS[1][2]))
        rows = verify.order68_list_rows(fixed_records.show(LIST, c).decode("utf-8"))
        self.assertEqual([(s, p) for s, p, _h, _c in rows], list(ledger.ORDER68_TARGETS))


if __name__ == "__main__":
    unittest.main()
