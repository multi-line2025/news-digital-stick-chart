"""T-083 のテスト：--commit-written の前の照合（seal_order2.commit_written と check_written）の8つに、それぞれ外すと落ちる
テストを付ける（T-081 の監査 軽-1）。

8つ：targets の数、中身の kind、check_ledger_head、head、check_stats_order、check_privacy、check_sealed_inside、.ots の
バイト列の照合。どのテストも、その照合だけが知らせる理由の文まで見て、コミットしていないこと（HEAD が動かないこと）を確かめる。
理由の文を見るのは、ほかの照合も同じ形を後で止める場合があるため。T-083 で1つずつ外して確かめた結果：
  - kind を外すと check_stats_order が、check_sealed_inside を外すと stage_raw が、別の文で止める（テストは文の違いで落ちる）。
  - ほかの6つ（targets の数・ledger_head・head・check_stats_order・privacy・.ots）は、外すと何も止めずにコミットまで進む
    （テストは「LedgerError not raised」で落ちる）。

書いた記録を書き換える形は、.ots を作れず、コミットもできなかった形（test_t081.CommitWrittenCase の runner=FailingOts）で作る。
その形では最後の seq の .ots が無いので、最後の1行と中身を、鎖の形を保ったまま書き換えられる（check_written の限界。
手順書 16章）。照らすのは、書き換えたあとの記録と中身の形だけである。

実行（プロジェクトのルートで）:
    PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -B -m unittest discover -s tests/sealer -v

書くのは、仮のプロジェクト（test_t078.Synth）と一時のフォルダの中だけ。本物の sealed/・data/ には書かない。ネットワークと
LACIE SHARE には触れない。
"""

import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import test_t078 as t78  # noqa: E402
import test_t081 as t81  # noqa: E402

ledger = t81.ledger
seal_order2 = t81.seal_order2


class Case(t81.CommitWrittenCase):
    def no_ots(self):
        """.ots を作れず、コミットもできなかった形。返り値: (最後の記録, 中身)。"""
        rec = self.written_not_committed(runner=t78.FailingOts())
        self.assertFalse(os.path.exists(os.path.join(self.root, "sealed", ledger.ots_name(rec["seq"]))))
        with open(os.path.join(self.root, rec["targets"][0]["path"]), "rb") as f:
            return rec, json.loads(f.read())

    def rewrite_last(self, rec, doc=None, **over):
        """最後の1行（と、doc を渡せば中身のファイル）を、鎖の形を保ったまま書き換える。返り値: 書き換えた記録。"""
        targets = [dict(t) for t in rec["targets"]]
        if doc is not None:
            raw = ledger.canonical_line(doc) + b"\n"
            with open(os.path.join(self.root, targets[0]["path"]), "wb") as f:
                f.write(raw)
            targets[0]["sha256"] = ledger.sha256_hex(raw)
        new = dict(rec, targets=targets)
        new.update(over)
        lines = ledger.split_lines(self.ledger_bytes())
        with open(self.ledger, "wb") as f:
            f.write(b"".join(x + b"\n" for x in lines[:-1]) + ledger.canonical_line(new) + b"\n")
        self.assertEqual(ledger.verify_chain(self.ledger_bytes())[-1], new)       # 鎖の形には通る
        return new

    def refused_written(self, text):
        """check_written と main の両方が止め、HEAD が動かず、作業ツリーの変更が残る。"""
        self.refused(text)
        self.assertNotEqual(self.git("status", "--porcelain"), b"")


class TestTargetsCount(Case):
    """targets がちょうど1つでない（中身と別のファイルをもう1つ縛る）。"""

    def test_two_targets(self):
        rec, _doc = self.no_ots()
        rel = "sealed/t083-extra.json"
        raw = b'{"x":1}\n'
        with open(os.path.join(self.root, rel), "wb") as f:
            f.write(raw)
        extra = {"path": rel, "role": "extra", "sha256": ledger.sha256_hex(raw)}
        self.rewrite_last(rec, targets=rec["targets"] + [extra])
        self.refused_written("seq %d の targets がちょうど1つでない" % rec["seq"])


class TestKind(Case):
    def test_kind_changed(self):
        rec, doc = self.no_ots()
        self.rewrite_last(rec, dict(doc, kind="stats-order2x"))
        self.refused_written("seq %d の中身の kind が stats-order2 でない" % rec["seq"])


class TestLedgerHead(Case):
    def test_ledger_head_changed(self):
        rec, doc = self.no_ots()
        self.rewrite_last(rec, dict(doc, ledger_head="0" * 64))
        self.refused_written("seq %d の stats-order2 の中身の ledger_head が、直前の記録のハッシュと一致しない" % rec["seq"])


class TestHeadMoved(Case):
    """T-081 の監査の Aud3.test_40 の形：書いたあと（コミットの前）に、書いたものに触れないコミットを1つ足して HEAD を
    進める。HEAD の版の記録は書く前と同じなので、鎖・中身・ledger_head・順番の形には通る。中身の head だけが今の HEAD と
    違う。head の照合を外すと、何も止めずにコミットする。"""

    def test_head_moved_by_unrelated_commit(self):
        rec = self.written_not_committed()
        with open(os.path.join(self.root, "t083-unrelated.txt"), "w") as f:
            f.write("x\n")
        self.git("add", "--", "t083-unrelated.txt")
        self.git("commit", "-q", "-m", "書いたものに触れないコミット（テスト）")
        self.assertEqual(self.git("cat-file", "blob", "HEAD:sealed/ledger.jsonl"),
                         b"".join(x + b"\n" for x in ledger.split_lines(self.ledger_bytes())[:-1]))
        self.before = self.head()
        self.refused_written("seq %d の中身の head が、今の HEAD と違う" % rec["seq"])


class TestStatsOrder(Case):
    """中身の kind・ledger_head・head は正しいが、順番2の中身の形（ledger.check_stats_order）に通らない。"""

    def test_stop_kind_b_on_decided(self):
        rec, doc = self.no_ots()
        self.assertEqual(doc["counting_output"]["status"], "decided")
        self.rewrite_last(rec, dict(doc, stop_kind="b", status="stopped"))
        self.refused_written("stop_kind 'b' と counting_output の status 'decided' が合わない")


class TestPrivacy(Case):
    """最後の記録の note に、許可していないメールアドレスの形を入れる。ほかの照合は、どれも note を見ない。"""

    def test_address_in_note(self):
        rec, _doc = self.no_ots()
        self.rewrite_last(rec, note=rec["note"] + " " + t78.other_address("taro"))
        self.refused_written("stats-order2 の記録の行に、許可していないメールアドレスの形がある")


class TestSealedInside(Case):
    """sealed/ledger.jsonl を、同じバイト列のプロジェクトの外のファイルへのリンクに置き換える（git では型の変更として
    sealed/ledger.jsonl の変更に見える）。.ots の無い形では、load_checked（その中の check_sealed_inside）を通らないので、
    commit_written の先頭の check_sealed_inside が止める。"""

    def test_ledger_is_link(self):
        self.no_ots()
        outside = os.path.join(self.tmp, "ledger-outside.jsonl")
        os.rename(self.ledger, outside)
        os.symlink(outside, self.ledger)
        self.refused_written("sealed/ledger.jsonl の実体（.*）が、sealed/ の中の ledger.jsonl ではない")
        self.assertTrue(os.path.islink(self.ledger))


class TestOtsBytes(Case):
    """最後の seq の .ots のバイト列だけを変える（記録と中身はそのまま）。.ots の照合を外すと、何も止めずにコミットする。"""

    def test_last_ots_changed(self):
        rec = self.written_not_committed()
        path = os.path.join(self.root, "sealed", ledger.ots_name(rec["seq"]))
        with open(path, "rb") as f:
            raw = bytearray(f.read())
        i = raw.find(bytes.fromhex(ledger.sha256_hex(self.ledger_bytes())))
        self.assertGreater(i, 0)                              # .ots は記録の全体の sha256 を対象にしている
        raw[i] ^= 0xFF
        with open(path, "wb") as f:
            f.write(bytes(raw))
        self.refused_written(re.escape("%s の対象のハッシュが、記録の先頭 %d 行と一致しない"
                                       % (ledger.ots_name(rec["seq"]), rec["seq"])))
