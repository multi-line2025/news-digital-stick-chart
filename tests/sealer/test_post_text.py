"""鎖の先頭の投稿文（src/sealer/post_text.py）と、照らす手順（docs/verify/x-post.md）のテスト。T-029。

実行（プロジェクトのルートで）:
    PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest discover -s tests/sealer -v

ネットワークは使わない。プロジェクトのファイルには何も書かない（仮の記録と複製は一時的な場所に作る）。
- 文字数の数え方（重み 1 と 2、URL の 23、URL の末尾の句読点、安全側の上乗せ、NFC、上限で止まること）
- 引用の固定文が CLAUDE.md の行と一字一句同じこと。一字でも違えば止まること
- メールアドレス・絶対パス・UUID・IPv4・この機械に固有の文字列が入ると止まり、何も出力しないこと
- 本物の記録で投稿文が作れ、ハッシュが記録の先頭 N 行・seq N の .ots の対象と同じであること
- 壊した記録（書き換え・切り詰め・コミットしていない変更）では投稿文を作らないこと
- 手順書の塊を、文書のとおりファイルに保存し、-e を付けずに bash と zsh で実行する（S-1）。
  壊した複製・違う投稿の値では終了コード 1 で止まり、どの検査が合わないかを出すこと
- 投稿の一覧を投稿の決まり（すべての記録を recorded_at から 24 時間以内。seq 1・2 は決まりの前の
  例外）と照らすこと（M-2。2026-10-08 オーナー決定。T-034 で例外を seq 1・2 に正した）
- 最初の投稿（アカウントと投稿は手順書から読む）を照らし、seq 3・4 が決まりを守っていること（T-034）
- 投稿の ID から時刻を計算すること、遅れの上限の値の形、recorded_at と確定時刻の照合、保留（T-034）
"""

import contextlib
import datetime
import io
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(os.path.dirname(HERE))
SRC = os.path.join(PROJECT, "src", "sealer")
sys.path.insert(0, SRC)
sys.path.insert(0, HERE)

import ledger  # noqa: E402
import otsfile  # noqa: E402
import post_text  # noqa: E402
import test_ledger as tl  # noqa: E402

DOC_REL = os.path.join("docs", "verify", "x-post.md")
BLOCK_RE = re.compile(r"<!-- test:x-post -->\n```sh\n(.*?)```", re.S)
WORKTREE_MODE = os.environ.get("SEALER_DOC_TEST_WORKTREE") == "1"
OVERLAY = ("src/sealer", "tests/sealer", "docs/verify")


def has_head():
    r = subprocess.run(["git", "-C", PROJECT, "rev-parse", "--verify", "-q", "HEAD"],
                       capture_output=True)
    return r.returncode == 0


def sealed_clean():
    r = subprocess.run(["git", "-C", PROJECT, "status", "--porcelain", "--untracked-files=all",
                        "--", "sealed/"], capture_output=True)
    return r.returncode == 0 and not r.stdout.strip()


def claude_citations():
    """CLAUDE.md の「引用」の下の 2 行（"  - " の後ろ）。"""
    with open(os.path.join(PROJECT, "CLAUDE.md"), encoding="utf-8") as f:
        lines = f.read().split("\n")
    i = next(n for n, l in enumerate(lines) if l.startswith("- 引用："))
    return [lines[i + 1][len("  - "):], lines[i + 2][len("  - "):]]


SAMPLE_FACTS = {"seq": 4, "hash": "a" * 64, "recorded_at": "2026-10-07T13:45:22Z", "height": 970352}


def sample_text():
    (_lang, text, _w), _c = post_text.choose_citation(post_text.body(SAMPLE_FACTS))
    return text


# ---------------------------------------------------------------- 文字数


class TestWeight(unittest.TestCase):
    W = staticmethod(post_text.weighted_length)

    def test_ascii_is_one(self):
        self.assertEqual(self.W("abc 123\n"), 8)
        self.assertEqual(self.W("a" * 280), 280)

    def test_japanese_and_fullwidth_are_two(self):
        self.assertEqual(self.W("あ"), 2)
        self.assertEqual(self.W("漢字カナ"), 8)
        self.assertEqual(self.W("（）。・："), 10)

    def test_weight_one_ranges_edges(self):
        self.assertEqual(self.W("\u10ff"), 1)
        self.assertEqual(self.W("\u1100"), 2)
        self.assertEqual(self.W("\u2014"), 1)   # em dash（U+2010–U+201F）
        self.assertEqual(self.W("\u2020"), 2)
        self.assertEqual(self.W("\u2032"), 1)
        self.assertEqual(self.W("\u2038"), 2)
        self.assertEqual(self.W("\u200d"), 1)
        self.assertEqual(self.W("\u200e"), 2)

    def test_nfc_before_counting(self):
        self.assertEqual(self.W("e\u0301"), 1)   # 合成すると é の 1 文字

    def test_url_is_max_of_length_and_23(self):
        """L-2：X がリンクにしてもしなくても少なく数えないよう、max(実際の長さ, 23)。"""
        self.assertEqual(self.W("https://www.gdeltproject.org/"), 29)
        self.assertEqual(self.W("http://a.co"), 23)
        self.assertEqual(self.W("https://example.org/" + "x" * 200), 220)

    def test_url_trailing_punctuation_not_in_url(self):
        # "(" 1 + URL 29 + ")." 2
        self.assertEqual(self.W("(https://www.gdeltproject.org/)."), 32)
        # 全角の括弧で終わる（日本語の引用の形）。"（" 2 + URL 29 + "）。" 4
        self.assertEqual(self.W("（https://www.gdeltproject.org/）。"), 35)

    def test_bare_domain_counts_at_least_23(self):
        self.assertEqual(self.W("ledger.jsonl"), 23)
        self.assertEqual(self.W("verify.py"), 23)
        self.assertEqual(self.W("a" * 30 + ".com"), 34)
        self.assertEqual(self.W("sealed/ledger.jsonl"), 7 + 23)
        self.assertEqual(self.W("1.5"), 3)            # 最後のラベルに英字が無い
        self.assertEqual(self.W("Project."), 8)       # 点の後ろにラベルが無い

    def test_emoji_not_undercounted(self):
        self.assertGreaterEqual(self.W("\U0001F600"), 2)

    def test_fixed_citations(self):
        # 内訳を手で数えた値。英語：25 + 29 + 2 + 70。日本語：12 + 13 + 2 + 29 + 4 + 16 + 15 + 32。
        self.assertEqual(self.W(post_text.CITATION_EN), 126)
        self.assertEqual(self.W(post_text.CITATION_JA), 123)

    def test_unicode_digits_not_accepted(self):
        """L-3：数字は [0-9] だけ。"""
        text = sample_text()
        self.assertIsNone(post_text.TEMPLATE_RE.match(text.replace("2026", "\u0662026")))
        self.assertIsNone(post_text.TEMPLATE_RE.match(text.replace("seq 1-4", "seq 1-\u0664")))
        with self.assertRaises(post_text.PostError):
            post_text.body(dict(SAMPLE_FACTS, recorded_at="\u0662026-10-07T13:45:22Z"))

    def test_over_limit_stops(self):
        facts = dict(SAMPLE_FACTS, seq=10 ** 60)
        with self.assertRaises(post_text.PostError):
            post_text.choose_citation(post_text.body(facts))

    def test_choice_prefers_smaller_then_japanese(self):
        (lang, text, w), cands = post_text.choose_citation(post_text.body(SAMPLE_FACTS))
        self.assertEqual(lang, "ja")
        self.assertEqual(w, min(c[2] for c in cands))
        # 日本語だけが上限を超える本文なら、英語を選ぶ
        with mock.patch.object(post_text, "CITATIONS",
                               (("ja", post_text.CITATION_JA + "あ" * 10), ("en", post_text.CITATION_EN))):
            (lang, _t, _w), _c = post_text.choose_citation(post_text.body(SAMPLE_FACTS))
        self.assertEqual(lang, "en")
        # 同じ重みなら日本語
        with mock.patch.object(post_text, "CITATIONS", (("ja", "x"), ("en", "y"))):
            (lang, _t, _w), _c = post_text.choose_citation("b\n")
        self.assertEqual(lang, "ja")


# ---------------------------------------------------------------- 引用の固定文


class TestCitation(unittest.TestCase):
    def test_constants_equal_claude_md(self):
        en, ja = claude_citations()
        self.assertEqual(post_text.CITATION_EN, en)
        self.assertEqual(post_text.CITATION_JA, ja)
        self.assertEqual(post_text.CITATION_EN.encode("utf-8"), en.encode("utf-8"))
        self.assertEqual(post_text.CITATION_JA.encode("utf-8"), ja.encode("utf-8"))

    def test_text_ends_with_exact_citation(self):
        text = sample_text()
        self.assertIn(text.split("\n")[-1], claude_citations())
        post_text.check_publishable(text, identifiers=[])

    def test_one_char_changed_citation_stops(self):
        text = sample_text()
        for bad in (text + " ", text.replace("。本", ".本"), text.replace("提携", "堤携"),
                    text.replace("GDELT Project と", "GDELT project と"),
                    text.replace("https://www.gdeltproject.org/", "https://gdeltproject.org/")):
            with self.subTest(bad=bad[-40:]):
                with self.assertRaises(post_text.PostError):
                    post_text.check_publishable(bad, identifiers=[])

    def test_doc_cites_gdelt(self):
        with open(os.path.join(PROJECT, DOC_REL), encoding="utf-8") as f:
            self.assertIn(post_text.CITATION_JA, f.read())


# ---------------------------------------------------------------- 外の情報


class TestPrivacy(unittest.TestCase):
    def inject(self, s):
        text = sample_text()
        lines = text.split("\n")
        return "\n".join([lines[0] + " " + s] + lines[1:])

    def assertStops(self, s, identifiers=()):
        with self.assertRaises(post_text.PostError) as cm:
            post_text.check_publishable(self.inject(s), identifiers=list(identifiers))
        return str(cm.exception)

    def test_email_stops_and_is_not_echoed(self):
        # アドレスの形は、このファイル自身が privacy_scan に掛からないよう、実行時に組み立てる。
        forms = (("@", "."), ("＠", "．"), (" [at] ", " [dot] "), ("%40", "."), ("&#64;", "."))
        for at, dot in forms:
            addr = "someone" + at + "example" + dot + "com"
            with self.subTest(addr=addr):
                msg = self.assertStops(addr)
                self.assertNotIn("example", msg)

    def test_allowed_author_address_still_not_in_template(self):
        self.assertStops("197505900+multi-line2025@users.noreply.github.com")

    def test_absolute_paths_stop(self):
        for p in ("/Users/someone/x", "/home/someone", "/private/tmp/x", "/var/folders/ab",
                  "/Volumes/Disk", "C:\\Users\\x", "C:/Users/x", "~/Desktop", "a\\b"):
            with self.subTest(p=p):
                self.assertStops(p)

    def test_uuid_and_ip_stop(self):
        self.assertStops("12345678-ABCD-1234-abcd-1234567890AB")
        self.assertStops("192.168.1.10")

    def test_machine_identifiers_stop(self):
        self.assertStops("hostname-xyz", identifiers=["hostname-xyz"])
        self.assertStops("SOMEUSER", identifiers=["someuser"])

    def test_local_identifiers_include_user_and_project(self):
        ids = post_text.local_identifiers()
        self.assertIn(PROJECT, ids)
        self.assertTrue(all(len(i) >= 3 for i in ids))

    def test_extra_url_stops(self):
        self.assertStops("https://example.org/x")

    def test_main_prints_nothing_when_stopped(self):
        """build の中で検査に当たれば、標準出力に何も出さず、終了コード 1。"""
        bad = post_text.body(SAMPLE_FACTS).replace("seq 1-", "/Users/someone seq 1-")
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(post_text, "head_facts", return_value=SAMPLE_FACTS), \
                mock.patch.object(post_text, "body", return_value=bad), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = post_text.main([])
        self.assertEqual(code, 1)
        self.assertEqual(out.getvalue(), "")
        self.assertIn("止めた", err.getvalue())
        self.assertNotIn("someone", err.getvalue())

    def test_bad_fact_values_stop(self):
        for k, v in (("seq", 0), ("seq", "4"), ("hash", "A" * 64), ("hash", "a" * 63),
                     ("recorded_at", "2026-10-07 13:45:22"), ("height", 0), ("height", "1")):
            with self.subTest(k=k, v=v):
                with self.assertRaises(post_text.PostError):
                    post_text.body(dict(SAMPLE_FACTS, **{k: v}))


# ---------------------------------------------------------------- 本物の記録


@unittest.skipUnless(has_head(), "コミットがまだ無い")
class TestRealLedger(unittest.TestCase):
    def setUp(self):
        if not sealed_clean():
            self.skipTest("sealed/ にコミットしていない変更がある（post_text は止まる）")

    def test_build_from_real_records(self):
        text, lang, cands, facts = post_text.build(PROJECT)
        m = post_text.TEMPLATE_RE.match(text)
        self.assertIsNotNone(m)
        data = subprocess.run(["git", "-C", PROJECT, "show", "HEAD:sealed/ledger.jsonl"],
                              check=True, capture_output=True).stdout
        records = ledger.verify_chain(data)
        n = len(records)
        self.assertEqual(int(m.group("seq")), n)
        self.assertEqual(m.group("hash"), ledger.sha256_hex(data))       # 投稿の時点のファイル全体
        self.assertEqual(m.group("hash"), ledger.prefix_digest(data, n))
        with open(os.path.join(PROJECT, "sealed", ledger.ots_name(n)), "rb") as f:
            self.assertEqual(otsfile.parse(f.read())[0], m.group("hash"))  # seq N の .ots の対象
        self.assertEqual(m.group("time"), records[-1]["recorded_at"])
        self.assertLessEqual(post_text.weighted_length(text), 280)
        self.assertIn(lang, ("ja", "en"))
        self.assertEqual(post_text.check_publishable(text), post_text.weighted_length(text))

    def test_each_earlier_seq(self):
        """--seq N：前の seq の文（投稿の決まりはすべての記録の投稿を求める）。"""
        data = subprocess.run(["git", "-C", PROJECT, "show", "HEAD:sealed/ledger.jsonl"],
                              check=True, capture_output=True).stdout
        records = ledger.verify_chain(data)
        for r in records:
            text, _l, _c, facts = post_text.build(PROJECT, r["seq"])
            m = post_text.TEMPLATE_RE.match(text)
            self.assertEqual(int(m.group("seq")), r["seq"])
            self.assertEqual(m.group("hash"), ledger.prefix_digest(data, r["seq"]))
            self.assertEqual(m.group("time"), r["recorded_at"])
        for bad in (0, len(records) + 1):
            with self.assertRaises(post_text.PostError):
                post_text.build(PROJECT, bad)

    def test_first_post_follows_rule(self):
        """T-034：最初の投稿（手順書 4.2。ID から 2026-10-07T18:24:30.169Z）を照らす。seq 3・4 は
        決まりの中（約 4.66 時間）、seq 1・2 は決まりの前の例外。アカウントと投稿は手順書から読む。"""
        account = doc_fixed(PROJECT, "account")
        posts = post_text.parse_posts(doc_fixed(PROJECT, "first"))
        self.assertEqual(len(posts), 1)
        _n, when, seq, h, acc = posts[0]
        self.assertEqual(post_text._iso(when), "2026-10-07T18:24:30.169Z")
        self.assertEqual((seq, acc), (4, account))
        data = subprocess.run(["git", "-C", PROJECT, "show", "HEAD:sealed/ledger.jsonl"],
                              check=True, capture_output=True).stdout
        self.assertEqual(h, ledger.prefix_digest(data, 4))
        # 手順書の 4.2 の投稿文は、post_text の seq 4 の文と同じ
        with open(os.path.join(PROJECT, DOC_REL), encoding="utf-8") as f:
            doc = f.read()
        self.assertIn("\n".join("  " + l for l in post_text.build(PROJECT, 4)[0].split("\n")), doc)
        out = io.StringIO()
        # T-049：照らす時刻を最初の投稿の時点に固定する。本物の記録が伸びても、それより後の記録は
        # 「保留」（まだ期限の前）になり、この投稿の照合の結果は変わらない
        bad = post_text.check_posts(PROJECT, posts, account=account,
                                    now=ledger.parse_time("2026-10-07T18:25:00Z"), out=out)
        self.assertEqual(bad, [], out.getvalue())
        text = out.getvalue()
        for k in (1, 2):
            self.assertRegex(text, r"seq %d: 最初に投稿された時刻 2026-10-07T18:24:30\.169Z.*例外" % k)
        self.assertRegex(text, r"seq 3: 最初に投稿された時刻 2026-10-07T18:24:30\.169Z、遅れ 4\.66 時間.*"
                               r"上限 24 時間の中")
        self.assertRegex(text, r"seq 4: 最初に投稿された時刻 2026-10-07T18:24:30\.169Z、遅れ 4\.65 時間.*"
                               r"上限 24 時間の中")
        # 同じ投稿が 24 時間を超えて遅れていれば、seq 3・4 は合わない（例外は seq 1・2 だけ）
        late = [(1, when + datetime.timedelta(hours=20), 4, h, acc)]
        # T-049：照らす時刻は、遅れた投稿の時点（本物の記録が伸びても、それより後の記録は保留になる）
        bad = post_text.check_posts(PROJECT, late, account=account, out=io.StringIO(),
                                    now=when + datetime.timedelta(hours=20, minutes=1))
        self.assertEqual([b.split(":")[0] for b in bad], ["seq 3", "seq 4"])

    def test_second_post_seq5_follows_rule(self):
        """T-049：2 つめの投稿（seq 1-5。ID 2107974118754980205、reviews/T-048.md のオーナーの発言）を、
        最初の投稿と並べて照らす。照らす時刻は 2 つめの投稿の時点に固定する（それより後の記録は保留）。"""
        data = subprocess.run(["git", "-C", PROJECT, "show", "HEAD:sealed/ledger.jsonl"],
                              check=True, capture_output=True).stdout
        if len(ledger.verify_chain(data)) < 5:
            self.skipTest("記録に seq 5 が無い")
        account = doc_fixed(PROJECT, "account")
        # T-052（T-049 の監査 軽-1）：一覧のハッシュは、実際に投稿した値の固定の文字列（reviews/T-048.md）。
        # 記録から計算した値をそのまま入れると、記録が書き換わっても一致してしまうため
        posted5 = "6c44e4cbd5ae6a8f7839141b33dc010f518cd0a3c333acefa7bc4096d4958b1b"
        posted4 = "186d3c6db7447d80a13566ec134db6b0e27cad738e518e80bf48559f6d811cdb"
        self.assertEqual(ledger.prefix_digest(data, 5), posted5)
        self.assertEqual(ledger.prefix_digest(data, 4), posted4)
        listing = "\n".join([
            "https://x.com/%s/status/2107899885177704739 4 %s" % (account, posted4),
            "https://x.com/%s/status/2107974118754980205 5 %s" % (account, posted5)])
        posts = post_text.parse_posts(listing)
        second = posts[1][1]
        self.assertEqual(post_text._iso(second), "2026-10-07T23:19:28.833Z")
        out = io.StringIO()
        bad = post_text.check_posts(PROJECT, posts, account=account,
                                    now=second + datetime.timedelta(minutes=1), out=out)
        self.assertEqual(bad, [], out.getvalue())
        self.assertRegex(out.getvalue(), r"seq 5: 最初に投稿された時刻 2026-10-07T23:19:28\.833Z、遅れ 0\.08 時間"
                                         r".*上限 24 時間の中")

    def test_real_recorded_at_before_headers(self):
        """本物の記録では、どの seq の recorded_at も確定時刻 + 3 時間より前。"""
        st = post_text.verify.State(PROJECT, None)
        self.assertEqual(post_text.check_recorded_vs_btc(st.records, st.times), [])

    def test_build_stops_when_recorded_after_header(self):
        real = post_text.verify.State

        def fake(root, headers):
            st = real(root, headers)
            st.times = dict(st.times)
            st.times[1] = ledger.parse_time(st.records[0]["recorded_at"]) - datetime.timedelta(hours=4)
            return st
        with mock.patch.object(post_text.verify, "State", side_effect=fake):
            with self.assertRaisesRegex(post_text.PostError, "seq 1: recorded_at"):
                post_text.build(PROJECT)

    def test_cli_both_pythons(self):
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
        outs = []
        for py in (sys.executable, "python3"):
            r = subprocess.run([py, "-B", os.path.join(SRC, "post_text.py")], cwd=PROJECT,
                               capture_output=True, env=env)
            self.assertEqual(r.returncode, 0, r.stderr.decode())
            self.assertIn("合計:", r.stderr.decode())
            outs.append(r.stdout)
        self.assertEqual(outs[0], outs[1])
        self.assertEqual(outs[0].decode(), post_text.build(PROJECT)[0] + "\n")


# ---------------------------------------------------------------- 仮の記録（壊したとき）


class TestSyntheticLedger(tl.LedgerCase):
    """self.base を仮のプロジェクトのルートにし、Git のリポジトリにする。"""

    def setUp(self):
        super().setUp()
        self.git("init", "-q")
        self.add(n=3)
        for s in (1, 2, 3):
            self.stamp(s)
        self.commit()

    def git(self, *args):
        return subprocess.run(["git", "-C", self.base] + list(tl.AUTHOR) + list(args),
                              check=True, capture_output=True).stdout

    def commit(self):
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "c")

    def test_pending_head(self):
        text, _lang, _c, facts = post_text.build(self.base)
        self.assertEqual(facts["seq"], 3)
        self.assertIsNone(facts["height"])
        self.assertIn("/ BTC pending\n", text)
        self.assertIn(ledger.prefix_digest(self.data(), 3), text)

    def test_uncommitted_append_stops(self):
        self.add(start=3)
        self.stamp(4)
        with self.assertRaisesRegex(post_text.PostError, "コミットしていない"):
            post_text.build(self.base)

    def test_rewritten_line_stops(self):
        lines = self.lines()
        lines[0] = lines[0].replace("注記 0".encode(), "注記 9".encode())
        self.write_lines(lines)
        self.commit()
        with self.assertRaisesRegex(post_text.PostError, "検証に失敗"):
            post_text.build(self.base)

    def test_truncated_ledger_stops(self):
        self.write_lines(self.lines()[:2])
        self.commit()
        with self.assertRaisesRegex(post_text.PostError, "検証に失敗"):
            post_text.build(self.base)

    def test_missing_ots_stops(self):
        self.git("rm", "-q", "sealed/" + ledger.ots_name(3))
        self.git("commit", "-q", "-m", "c")
        with self.assertRaisesRegex(post_text.PostError, "検証に失敗"):
            post_text.build(self.base)

    def test_not_a_repo_stops(self):
        shutil.rmtree(os.path.join(self.base, ".git"))
        with self.assertRaises(post_text.PostError):
            post_text.build(self.base)


# ---------------------------------------------------------------- 投稿の一覧と投稿の決まり（M-2、T-034）


def doc_fixed(root, tag):
    """手順書の `<!-- x-post:<tag> -->` の直後の塊の中身（1 行）。アカウントと最初の投稿は、手順書に
    だけ書き、テストはそこから読む（承認は手順書に書くことへのもの）。"""
    with open(os.path.join(root, DOC_REL), encoding="utf-8") as f:
        m = re.search(r"<!-- x-post:%s -->\n```\n(.*?)\n```" % re.escape(tag), f.read(), re.S)
    return m.group(1).strip()


def post_line(when, seq, h):
    return "%s %d %s" % (ledger.format_time(when), seq, h)


def x_url(account, when):
    """時刻 when の投稿の ID を作り、URL にする（仮の投稿。ID の下位 22 ビットは 0）。"""
    ms = int(round(when.timestamp() * 1000))
    return "https://x.com/%s/status/%d" % (account, (ms - post_text.X_EPOCH_MS) << 22)


class TestXId(unittest.TestCase):
    def test_first_post_id_time(self):
        url = doc_fixed(PROJECT, "first").split()[0]
        m = post_text.X_URL_RE.match(url)
        self.assertEqual(m.group(1), doc_fixed(PROJECT, "account"))
        t = post_text.x_id_time(m.group(2))
        self.assertEqual(post_text._iso(t), "2026-10-07T18:24:30.169Z")
        self.assertEqual((int(m.group(2)) >> 22) + 1288834974657, 1791397470169)

    def test_round_trip(self):
        when = ledger.parse_time("2026-10-08T01:02:03Z")
        m = post_text.X_URL_RE.match(x_url("someone", when))
        self.assertEqual(post_text.x_id_time(m.group(2)), when)

    def test_small_id_rejected(self):
        with self.assertRaises(post_text.PostError):
            post_text.x_id_time(12345)

    def test_url_forms(self):
        ok = ("https://x.com/a_b/status/2107899885177704739",
              "https://twitter.com/a/status/2107899885177704739?s=20")
        for u in ok:
            self.assertIsNotNone(post_text.X_URL_RE.match(u), u)
        for u in ("http://x.com/a/status/1", "https://x.com/a/status/abc",
                  "https://x.com/a-b/status/2107899885177704739", "https://evil.com/a/status/1"):
            self.assertIsNone(post_text.X_URL_RE.match(u), u)


class TestMaxDelay(unittest.TestCase):
    def test_rejects_nan_inf_negative(self):
        for v in ("nan", "inf", "-inf", "-1", "abc", None, "NaN"):
            with self.subTest(v=v):
                with self.assertRaises(post_text.PostError):
                    post_text.check_max_delay(v)

    def test_accepts_finite(self):
        self.assertEqual(post_text.check_max_delay("24"), 24)
        self.assertEqual(post_text.check_max_delay(0), 0)
        self.assertEqual(post_text.check_max_delay("1.5"), 1.5)


class TestRecordedVsBtc(unittest.TestCase):
    def test_slack_is_three_hours(self):
        self.assertEqual(post_text.RECORDED_AT_HEADER_SLACK, datetime.timedelta(hours=3))

    def test_check(self):
        recs = [{"seq": 1, "recorded_at": "2026-10-07T13:00:00Z"},
                {"seq": 2, "recorded_at": "2026-10-07T16:00:00Z"},
                {"seq": 3, "recorded_at": "2026-10-07T16:00:01Z"}]
        hdr = ledger.parse_time("2026-10-07T13:00:00Z")
        times = {1: hdr, 2: hdr, 3: hdr}
        bad = post_text.check_recorded_vs_btc(recs, times)
        self.assertEqual(len(bad), 1)
        self.assertIn("seq 3", bad[0])
        self.assertEqual(post_text.check_recorded_vs_btc(recs, {}), [])   # 未確定なら照らさない


class TestCheckPosts(tl.LedgerCase):
    """仮の記録 6 件：seq 1 は T0、seq 2 は T0+30 時間、seq 3〜6 は T0+48〜51 時間。"""

    OFFSETS = (0, 30, 48, 49, 50, 51)

    def setUp(self):
        super().setUp()
        for off in self.OFFSETS:
            self.add(start=off)
        for s in range(1, 7):
            self.stamp(s)
        self.d = self.data()

    def rec(self, seq):
        return tl.T0 + self.OFFSETS[seq - 1] * tl.H

    def h(self, seq):
        return ledger.prefix_digest(self.d, seq)

    def check(self, lines, now=None, **kw):
        out = io.StringIO()
        posts = post_text.parse_posts("\n".join(lines))
        bad = post_text.check_posts(self.base, posts, now=now or self.rec(6) + 1000 * tl.H,
                                    out=out, **kw)
        return bad, out.getvalue()

    def test_rule_constants(self):
        self.assertEqual(post_text.RULE_MAX_DELAY_HOURS, 24)
        self.assertEqual(post_text.PRE_RULE_LAST_SEQ, 2)

    def test_one_head_post_covers_all(self):
        bad, out = self.check([post_line(self.rec(6) + tl.H, 6, self.h(6))])
        self.assertEqual(bad, [])
        self.assertIn("seq 1: 最初に投稿された時刻", out)
        self.assertIn("決まりの前の例外なので", out)
        self.assertIn("seq 3: 最初に投稿された時刻", out)
        self.assertRegex(out, r"seq 3: .*遅れ 4\.00 時間.*上限 24 時間の中")

    def test_seq1_2_exempt_but_seq3_judged(self):
        """M-a：seq 3 は決まりの対象（例外は seq 1・2 だけ）。"""
        bad, out = self.check([post_line(self.rec(3) + 25 * tl.H, 6, self.h(6))])
        self.assertEqual(len(bad), 1, bad)
        self.assertIn("seq 3", bad[0])
        self.assertIn("上限 24 時間を超える", bad[0])
        self.assertRegex(out, r"seq 1: .*遅れ 73\.00 時間.*例外")
        self.assertRegex(out, r"seq 4: .*遅れ 24\.00 時間.*上限 24 時間の中")   # ちょうど 24 は中

    def test_late_seq4_fails(self):
        """T-029 では seq 4 を 1 年後に投稿しても「守っている」になった（M-a）。今は合わない。"""
        bad, _ = self.check([post_line(self.rec(4) + 365 * 24 * tl.H, 4, self.h(4)),
                             post_line(self.rec(6) + 365 * 24 * tl.H, 6, self.h(6))])
        self.assertTrue(any(b.startswith("seq 3") for b in bad), bad)
        self.assertTrue(any(b.startswith("seq 4") for b in bad), bad)

    def test_later_post_covers_earlier_seq(self):
        bad, out = self.check([post_line(self.rec(4) + tl.H, 4, self.h(4)),
                               post_line(self.rec(6) + tl.H, 6, self.h(6))])
        self.assertEqual(bad, [])
        self.assertRegex(out, r"seq 5: .*遅れ 2\.00 時間")

    def test_earliest_covering_post_counts(self):
        bad, _ = self.check([post_line(self.rec(6) + 30 * tl.H, 6, self.h(6)),
                             post_line(self.rec(6) + tl.H, 6, self.h(6))])
        self.assertEqual(bad, [])

    def test_pending_before_deadline(self):
        """L-c：24 時間たっていない seq は保留（合わないとしない）。"""
        lines = [post_line(self.rec(5) + 0.5 * tl.H, 5, self.h(5))]
        bad, out = self.check(lines, now=self.rec(6) + 23 * tl.H)
        self.assertEqual(bad, [])
        self.assertIn("seq 6: 保留", out)
        self.assertIn("保留の seq: 6", out)
        bad, out = self.check(lines, now=self.rec(6) + 25 * tl.H)
        self.assertEqual(len(bad), 1, bad)
        self.assertIn("seq 6: 投稿が無い", bad[0])
        self.assertIn("期限を過ぎた", bad[0])

    def test_no_valid_post_fails_exempt_too(self):
        bad, _ = self.check([post_line(self.rec(6) + tl.H, 6, "0" * 64)])
        self.assertTrue(any(b.startswith("seq 1: 投稿が無い") for b in bad), bad)

    def test_wrong_hash_fails(self):
        bad, _ = self.check([post_line(self.rec(6) + tl.H, 6, self.h(6)),
                             post_line(self.rec(5) + tl.H, 5, self.h(4))])
        self.assertTrue(any("ハッシュ" in b for b in bad), bad)

    def test_post_before_recorded_at_fails(self):
        bad, _ = self.check([post_line(self.rec(6) - tl.H, 6, self.h(6))])
        self.assertTrue(any("recorded_at より前" in b for b in bad), bad)

    def test_seq_beyond_ledger_fails(self):
        bad, _ = self.check([post_line(self.rec(6) + tl.H, 6, self.h(6)),
                             post_line(self.rec(6) + tl.H, 7, "b" * 64)])
        self.assertTrue(any("記録は 6 件しかない" in b for b in bad), bad)

    def test_broken_ledger_fails(self):
        self.write_lines(self.lines()[:5])
        bad, _ = self.check([post_line(self.rec(6) + tl.H, 6, self.h(6))])
        self.assertTrue(bad and "検証に失敗" in bad[0], bad)

    def test_account(self):
        url = x_url("Dummy_Acct", self.rec(6) + tl.H)
        line = "%s 6 %s" % (url, self.h(6))
        self.assertEqual(self.check([line], account="dummy_acct")[0], [])      # 大文字小文字は区別しない
        bad, _ = self.check([line], account="OtherAcct")
        self.assertTrue(any("照らす対象の @OtherAcct でない" in b for b in bad), bad)
        bad, out = self.check([post_line(self.rec(6) + tl.H, 6, self.h(6))], account="OtherAcct")
        self.assertEqual(bad, [])
        self.assertIn("アカウントは照らしていない", out)

    def test_id_time_used(self):
        url = x_url("a", self.rec(3) + 25 * tl.H)
        bad, _ = self.check(["%s 6 %s" % (url, self.h(6))])
        self.assertTrue(any(b.startswith("seq 3") for b in bad), bad)

    def test_other_max_delay_is_reported(self):
        _bad, out = self.check([post_line(self.rec(6) + tl.H, 6, self.h(6))], max_delay_hours="48")
        self.assertIn("決まりと違う値で照らした", out)
        _bad, out = self.check([post_line(self.rec(6) + tl.H, 6, self.h(6))])
        self.assertNotIn("決まりと違う値", out)
        for v in ("nan", "inf", "-1"):
            with self.assertRaises(post_text.PostError):
                self.check([post_line(self.rec(6) + tl.H, 6, self.h(6))], max_delay_hours=v)

    def test_recorded_after_header_fails(self):
        """L-b：recorded_at が確定時刻 + 3 時間より後なら合わない（確定時刻は差し替えて試す）。"""
        real = post_text.verify.State

        def fake(root, headers):
            st = real(root, headers)
            st.times = {4: self.rec(4) - 4 * tl.H}
            return st
        with mock.patch.object(post_text.verify, "State", side_effect=fake):
            bad, _ = self.check([post_line(self.rec(6) + tl.H, 6, self.h(6))])
        self.assertTrue(any("seq 4: recorded_at" in b for b in bad), bad)

    def test_btc_delay_only_when_given(self):
        self.assertEqual(self.check([post_line(self.rec(6) + tl.H, 6, self.h(6))],
                                    max_delay_after_btc_hours=0)[0], [])

    def test_parse_errors(self):
        h = "a" * 64
        for text in ("", "# だけ", "2026-10-08T00:00:00Z 4", "2026-10-08 00:00:00 4 " + h,
                     "2026-10-08T00:00:00Z ４ " + h, "2026-10-08T00:00:00Z 4 " + "A" * 64,
                     "٢026-10-08T00:00:00Z 4 " + h, "https://x.com/a/status/12 4 " + h,
                     "https://example.org/a/status/2107899885177704739 4 " + h):
            with self.subTest(text=text):
                with self.assertRaises(post_text.PostError):
                    post_text.parse_posts(text)

    def test_cli(self):
        path = os.path.join(self.base, "posts.txt")
        with open(path, "w", encoding="utf-8") as f:
            f.write("# 一覧\n" + post_line(self.rec(6) + tl.H, 6, "0" * 64) + "\n")
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = post_text.main(["check-posts", path, "--root", self.base])
        self.assertEqual(code, 1)
        self.assertIn("合わない:", out.getvalue())
        with open(path, "w", encoding="utf-8") as f:
            f.write(post_line(self.rec(6) + tl.H, 6, self.h(6)) + "\n")
        for extra, want in (([], 0), (["--max-delay-hours", "nan"], 1),
                            (["--max-delay-hours", "-3"], 1), (["--account", "x"], 0)):
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = post_text.main(["check-posts", path, "--root", self.base] + extra)
            self.assertEqual(code, want, (extra, out.getvalue()))

    def test_cli_cannot_change_exception(self):
        for opt in ("--require-every-seq-from", "--delay-exempt-through", "--pre-rule-last-seq"):
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                post_text.main(["check-posts", "x", opt, "9"])


# ---------------------------------------------------------------- 照らす手順（第三者）

SHELLS = [sh for sh in ("bash", "zsh") if shutil.which(sh)]


@unittest.skipUnless(has_head(), "コミットがまだ無いので、複製して手順を試せない")
class TestDocProcedure(unittest.TestCase):
    """手順書の塊をファイルに保存し、-e を付けずに `bash ファイル` と `zsh ファイル` で実行する
    （文書に書いたとおりの使い方。S-1）。"""

    def setUp(self):
        self.assertIn("bash", SHELLS)
        self.tmp = tempfile.mkdtemp()
        self.clone = os.path.join(self.tmp, "stick-chart-x-post")
        subprocess.run(["git", "clone", "-q", "--no-hardlinks", PROJECT, self.clone],
                       check=True, capture_output=True)
        if WORKTREE_MODE:
            for rel in OVERLAY:
                shutil.rmtree(os.path.join(self.clone, rel), ignore_errors=True)
                shutil.copytree(os.path.join(PROJECT, rel), os.path.join(self.clone, rel),
                                ignore=shutil.ignore_patterns("__pycache__"))
            self.git("add", "-A", "--", *OVERLAY)
            self.git("commit", "-q", "--allow-empty", "-m", "一時的なコミット（テストの中だけ）")
        # 塊を、複製の中の文書から取り出して、リポジトリの外のファイルに保存する
        with open(os.path.join(self.clone, DOC_REL), encoding="utf-8") as f:
            blocks = BLOCK_RE.findall(f.read())
        self.assertEqual(len(blocks), 2)
        self.scripts = []
        for i, b in enumerate(blocks):
            path = os.path.join(self.tmp, "x-post-block%d.sh" % i)
            with open(path, "w", encoding="utf-8") as f:
                f.write(b)
            self.scripts.append(path)
        # 第三者の立場：複製の中で投稿文を作り直す（運営側と同じ値になる）
        self.post = self.make_post()

    def make_post(self, seq=None):
        cmd = [sys.executable, "-B", "src/sealer/post_text.py"] + ([] if seq is None else ["--seq", str(seq)])
        r = subprocess.run(cmd, cwd=self.clone, capture_output=True,
                           env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
        self.assertEqual(r.returncode, 0, r.stderr.decode())
        m = post_text.TEMPLATE_RE.match(r.stdout.decode().rstrip("\n"))
        self.assertIsNotNone(m)
        return {"SEQ": m.group("seq"), "POSTED": m.group("hash"),
                "RECORDED": m.group("time"), "BTC": m.group("btc")}

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def git(self, *args):
        subprocess.run(["git", "-C", self.clone] + list(tl.AUTHOR) + list(args),
                       check=True, capture_output=True)

    def run_script(self, idx, **override):
        """[(シェル, 終了コード, 出力)]。-e なし。"""
        env = {k: v for k, v in os.environ.items()
               if k not in ("SEQ", "POSTED", "RECORDED", "BTC", "POSTS", "ENV", "BASH_ENV")}
        env.update(PYTHONDONTWRITEBYTECODE="1", **(self.post if idx == 0 else {}))
        env.update(override)
        out = []
        for sh in SHELLS:
            r = subprocess.run([sh, self.scripts[idx]], cwd=self.clone, capture_output=True,
                               env=env, timeout=300)
            out.append((sh, r.returncode, (r.stdout + r.stderr).decode("utf-8", "replace")))
        return out

    def assertMatches(self, **override):
        for sh, code, out in self.run_script(0, **override):
            self.assertEqual(code, 0, "%s: %s" % (sh, out))
            self.assertIn("投稿と記録は一致する", out, sh)

    def assertStopsAt(self, check, **override):
        """終了コード 1 で止まり、どの検査が合わないかを出し、一致したとは出さない。"""
        for sh, code, out in self.run_script(0, **override):
            self.assertEqual(code, 1, "%s: %s" % (sh, out))
            self.assertIn("合わない: (%d)" % check, out, sh)
            self.assertNotIn("一致する", out, sh)

    def ledger_path(self):
        return os.path.join(self.clone, "sealed", "ledger.jsonl")

    # 順番1 の封印の直前の commit（本物の記録は seq 1〜4）。T-052：本物の記録の件数に頼らずに、
    # 「記録が 4 件のとき」の手順を試すため、複製の sealed/ をこの commit の状態にそろえる
    FOUR_RECORDS = "77d0dd22d8e397a9b1e53b079a31bb93db765452"

    def use_sealed_at(self, commit):
        """複製の sealed/ を commit の版にそろえてコミットする（複製の中だけ）。その commit に無い
        sealed/ のファイルは、消さずに複製の外（self.tmp の下）へ移す。投稿文を作り直す。"""
        self.git("checkout", "-q", commit, "--", "sealed")
        keep = set(subprocess.run(["git", "-C", self.clone, "ls-tree", "--name-only", commit, "sealed/"],
                                  check=True, capture_output=True).stdout.decode().split())
        aside = os.path.join(self.tmp, "aside")
        os.makedirs(aside, exist_ok=True)
        for name in os.listdir(os.path.join(self.clone, "sealed")):
            if "sealed/" + name not in keep:
                os.rename(os.path.join(self.clone, "sealed", name), os.path.join(aside, name))
        self.git("add", "-A", "sealed")
        self.git("commit", "-q", "--allow-empty", "-m", "sealed/ を %s の版に（テストの中だけ）" % commit[:7])
        self.post = self.make_post()

    def append_fake_record(self, when):
        """仮の seq 5 を足し、許可したカレンダーの Pending の .ots を作ってコミットする（複製の中だけ）。"""
        data = ledger.read_ledger(self.ledger_path())
        _r, rec, line = ledger.build_next_record(data, "periods", [tl.target("a/x.md")], "仮", when)
        with open(self.ledger_path(), "ab") as f:
            f.write(line)
        n = rec["seq"]
        with open(os.path.join(self.clone, "sealed", ledger.ots_name(n)), "xb") as f:
            f.write(tl.build_ots(ledger.prefix_bytes(ledger.read_ledger(self.ledger_path()), n)))
        self.git("add", "-A", "sealed")
        self.git("commit", "-q", "-m", "仮の追記")
        return n

    # ---- 投稿 1 件（3章）

    def test_shells_available(self):
        self.assertEqual(SHELLS, ["bash", "zsh"])

    def test_same_text_as_project(self):
        if WORKTREE_MODE or not sealed_clean():
            self.skipTest("作業ツリーの記録が HEAD と同じときだけ比べる")
        self.assertIn(self.post["POSTED"], post_text.build(PROJECT)[0])

    def test_intact_clone_matches(self):
        results = self.run_script(0)
        for sh, _c, out in results:
            self.assertIn(self.post["POSTED"], out, sh)
            for k in (2, 3, 4):
                self.assertIn("(%d) " % k, out, sh)
            # 変数の直後に日本語の文字が続いても、bash 3.2 で文字が化けないこと（${SEQ} の形で書く）
            self.assertIn("(3) %s 行目は seq %s、recorded_at %s" % (self.post["SEQ"], self.post["SEQ"],
                                                                   self.post["RECORDED"]), out, sh)
            self.assertNotIn("\ufffd", out, sh)
        self.assertMatches()

    def test_earlier_post_matches(self):
        self.post = self.make_post(2)
        self.assertEqual(self.post["SEQ"], "2")
        self.assertMatches()

    def test_bad_input_stops_at_0(self):
        self.assertStopsAt(0, SEQ="abc")
        self.assertStopsAt(0, POSTED="xyz")
        self.assertStopsAt(0, BTC="")

    def test_truncated_record_stops_at_1(self):
        with open(self.ledger_path(), "rb") as f:
            lines = f.read().split(b"\n")[:-1]
        with open(self.ledger_path(), "wb") as f:
            f.write(b"".join(l + b"\n" for l in lines[:-1]))
        self.git("commit", "-q", "-am", "切り詰め")
        self.assertStopsAt(1)

    def test_other_posted_hash_stops_at_2(self):
        wrong = ("0" if self.post["POSTED"][0] != "0" else "1") + self.post["POSTED"][1:]
        self.assertStopsAt(2, POSTED=wrong)

    def test_rewritten_record_stops_at_2(self):
        with open(self.ledger_path(), "rb") as f:
            data = f.read()
        i = data.index(b'"recorded_at":"') + len(b'"recorded_at":"2')
        data = data[:i] + (b"1" if data[i:i + 1] != b"1" else b"2") + data[i + 1:]
        with open(self.ledger_path(), "wb") as f:
            f.write(data)
        self.git("commit", "-q", "-am", "書き換え")
        self.assertStopsAt(2)

    def test_other_recorded_at_stops_at_3(self):
        self.assertStopsAt(3, RECORDED="2000-01-01T00:00:00Z")

    def test_verify_failure_stops_at_4(self):
        """先頭 N 行は同じまま、.ots の無い行を後ろに足す。(1)〜(3) は通り、(4) で止まる。"""
        data = ledger.read_ledger(self.ledger_path())
        _r, _rec, line = ledger.build_next_record(
            data, "periods", [tl.target("a/x.md")], "仮", ledger.parse_time("2099-01-01T00:00:00Z"))
        with open(self.ledger_path(), "ab") as f:
            f.write(line)
        self.git("commit", "-q", "-am", "追記（.ots なし）")
        self.assertEqual(ledger.prefix_digest(ledger.read_ledger(self.ledger_path()),
                                              int(self.post["SEQ"])), self.post["POSTED"])
        self.assertStopsAt(4)

    def test_other_height_stops_at_5(self):
        """T-052：高さのある seq 4（Bitcoin で確定済み）の投稿に固定する（最新の seq の確定の状態に頼らない）。"""
        self.post = self.make_post(4)
        self.assertNotEqual(self.post["BTC"], "pending")
        self.assertMatches()
        self.assertStopsAt(5, BTC="1")

    # ---- 投稿の一覧と投稿の決まり（4章）

    def write_posts(self, lines):
        path = os.path.join(self.tmp, "posts.txt")
        with open(path, "w", encoding="utf-8") as f:
            f.write("# <投稿の URL> <seq> <64 桁>\n" + "\n".join(lines) + "\n")
        return path

    def run_list(self, lines):
        return self.run_script(1, POSTS=self.write_posts(lines))

    def assertListOk(self, lines):
        for sh, code, out in self.run_list(lines):
            self.assertEqual(code, 0, "%s: %s" % (sh, out))
            self.assertIn("投稿の決まりを守っている", out, sh)

    def assertListFails(self, lines, text):
        for sh, code, out in self.run_list(lines):
            self.assertEqual(code, 1, "%s: %s" % (sh, out))
            self.assertIn(text, out, sh)
            self.assertNotIn("守っている", out, sh)

    def first_line(self):
        return doc_fixed(self.clone, "first")

    def test_list_first_post_ok(self):
        """最初の投稿（手順書 4.2）は、決まりを守っている（seq 3・4 は約 4.66 時間）。
        T-052：記録が 4 件の状態（77d0dd2 の sealed/）に固定して試す。"""
        self.use_sealed_at(self.FOUR_RECORDS)
        self.assertEqual(self.post["SEQ"], "4")
        for sh, code, out in self.run_list([self.first_line()]):
            self.assertEqual(code, 0, "%s: %s" % (sh, out))
            self.assertIn("投稿の決まりを守っている", out, sh)
            self.assertRegex(out, r"seq 3: .*遅れ 4\.66 時間.*上限 24 時間の中")
            self.assertRegex(out, r"seq 4: .*遅れ 4\.65 時間.*上限 24 時間の中")

    def test_list_other_account_fails(self):
        url, seq, h = self.first_line().split()
        other = url.replace("/" + doc_fixed(self.clone, "account") + "/", "/SomeoneElse/")
        self.assertListFails(["%s %s %s" % (other, seq, h)], "照らす対象の @")

    def test_list_late_seq4_fails(self):
        """T-029 では「守っている」になった、24 時間を過ぎた seq 4 の投稿（M-a）。"""
        h4 = ledger.prefix_digest(ledger.read_ledger(self.ledger_path()), 4)
        late = x_url(doc_fixed(self.clone, "account"), ledger.parse_time("2026-10-09T00:00:00Z"))
        self.assertListFails(["%s 4 %s" % (late, h4)], "上限 24 時間を超える")

    def test_list_wrong_hash_fails(self):
        url, seq, _h = self.first_line().split()
        self.assertListFails(["%s %s %s" % (url, seq, "0" * 64)], "ハッシュ")

    def test_list_missing_file_fails(self):
        for sh, code, out in self.run_script(1, POSTS=os.path.join(self.tmp, "無い.txt")):
            self.assertEqual(code, 1, sh)
            self.assertIn("合わない:", out, sh)

    def test_list_seq5_rule(self):
        """T-052：記録が 4 件の状態（77d0dd2 の sealed/）に固定し、仮の seq 5 を足して試す。"""
        self.use_sealed_at(self.FOUR_RECORDS)
        self.assertEqual(self.post["SEQ"], "4")
        acc = doc_fixed(self.clone, "account")
        rec5 = ledger.parse_time("2026-10-07T14:00:00Z")
        n = self.append_fake_record(rec5)
        h5 = ledger.prefix_digest(ledger.read_ledger(self.ledger_path()), n)
        ok5 = "%s %d %s" % (x_url(acc, rec5 + 23 * tl.H), n, h5)
        late5 = "%s %d %s" % (x_url(acc, rec5 + 25 * tl.H), n, h5)
        self.assertListOk([self.first_line(), ok5])
        self.assertListFails([self.first_line(), late5], "上限 24 時間を超える")
        # seq 5 の投稿が無いとき：今が recorded_at から 24 時間の中なら保留、過ぎていれば合わない
        now = datetime.datetime.now(datetime.timezone.utc)
        if now - rec5 <= datetime.timedelta(hours=24):
            for sh, code, out in self.run_list([self.first_line()]):
                self.assertEqual(code, 0, "%s: %s" % (sh, out))
                self.assertIn("seq 5: 保留", out, sh)
        else:
            self.assertListFails([self.first_line()], "seq 5: 投稿が無い")


if __name__ == "__main__":
    unittest.main()
