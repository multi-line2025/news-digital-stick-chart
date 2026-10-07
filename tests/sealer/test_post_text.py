"""鎖の先頭の投稿文（src/sealer/post_text.py）と、照らす手順（docs/verify/x-post.md）のテスト。T-029。

実行（プロジェクトのルートで）:
    PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest discover -s tests/sealer -v

ネットワークは使わない。プロジェクトのファイルには何も書かない（仮の記録と複製は一時的な場所に作る）。
- 文字数の数え方（重み 1 と 2、URL の 23、URL の末尾の句読点、安全側の上乗せ、NFC、上限で止まること）
- 引用の固定文が CLAUDE.md の行と一字一句同じこと。一字でも違えば止まること
- メールアドレス・絶対パス・UUID・IPv4・この機械に固有の文字列が入ると止まり、何も出力しないこと
- 本物の記録で投稿文が作れ、ハッシュが記録の先頭 N 行・seq N の .ots の対象と同じであること
- 壊した記録（書き換え・切り詰め・コミットしていない変更）では投稿文を作らないこと
- 手順書の塊を、リポジトリの複製の中でそのまま実行し、壊した複製・違う投稿の値では失敗すること
"""

import contextlib
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

    def test_url_is_23(self):
        self.assertEqual(self.W("https://www.gdeltproject.org/"), 23)
        self.assertEqual(self.W("http://a.co"), 23)
        self.assertEqual(self.W("https://example.org/" + "x" * 200), 23)

    def test_url_trailing_punctuation_not_in_url(self):
        # "(" 1 + URL 23 + ")." 2
        self.assertEqual(self.W("(https://www.gdeltproject.org/)."), 26)
        # 全角の括弧で終わる（日本語の引用の形）。"（" 2 + URL 23 + "）。" 4
        self.assertEqual(self.W("（https://www.gdeltproject.org/）。"), 29)

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
        # 内訳を手で数えた値。英語：25 + 23 + 2 + 70。日本語：12 + 13 + 2 + 23 + 4 + 16 + 15 + 32。
        self.assertEqual(self.W(post_text.CITATION_EN), 120)
        self.assertEqual(self.W(post_text.CITATION_JA), 117)

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
        bad = post_text.body(SAMPLE_FACTS).replace("lines", "/Users/someone lines")
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


# ---------------------------------------------------------------- 照らす手順（第三者）


@unittest.skipUnless(has_head(), "コミットがまだ無いので、複製して手順を試せない")
class TestDocProcedure(unittest.TestCase):
    def setUp(self):
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
        # 第三者の立場：複製の中で投稿文を作り直す（運営側と同じ値になる）
        r = subprocess.run([sys.executable, "-B", "src/sealer/post_text.py"], cwd=self.clone,
                           capture_output=True, env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
        self.assertEqual(r.returncode, 0, r.stderr.decode())
        m = post_text.TEMPLATE_RE.match(r.stdout.decode().rstrip("\n"))
        self.assertIsNotNone(m)
        self.post = {"SEQ": m.group("seq"), "POSTED": m.group("hash"),
                     "RECORDED": m.group("time"), "BTC": m.group("btc")}

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def git(self, *args):
        subprocess.run(["git", "-C", self.clone] + list(tl.AUTHOR) + list(args),
                       check=True, capture_output=True)

    def blocks(self):
        with open(os.path.join(self.clone, DOC_REL), encoding="utf-8") as f:
            return BLOCK_RE.findall(f.read())

    def run_blocks(self, **override):
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", **self.post)
        env.update(override)
        out = []
        for block in self.blocks():
            r = subprocess.run(["bash", "-e", "-o", "pipefail", "-c", block], cwd=self.clone,
                               capture_output=True, env=env, timeout=300)
            out.append((r.returncode, r.stdout.decode("utf-8", "replace")))
        return out

    def assertFails(self, **override):
        codes = [c for c, _o in self.run_blocks(**override)]
        self.assertTrue(codes and any(c != 0 for c in codes), codes)

    def test_same_text_as_project(self):
        if WORKTREE_MODE or not sealed_clean():
            self.skipTest("作業ツリーの記録が HEAD と同じときだけ比べる")
        text = post_text.build(PROJECT)[0]
        self.assertIn(self.post["POSTED"], text)

    def test_intact_clone_matches_post(self):
        self.assertEqual(len(self.blocks()), 1)
        results = self.run_blocks()
        for code, out in results:
            self.assertEqual(code, 0, out)
        self.assertIn("投稿と記録は一致する", results[0][1])
        self.assertIn(self.post["POSTED"], results[0][1])

    def test_other_posted_hash_fails(self):
        wrong = ("0" if self.post["POSTED"][0] != "0" else "1") + self.post["POSTED"][1:]
        self.assertFails(POSTED=wrong)

    def test_other_recorded_at_fails(self):
        self.assertFails(RECORDED="2000-01-01T00:00:00Z")

    def test_other_height_fails(self):
        if self.post["BTC"] == "pending":
            self.skipTest("投稿に高さが無い")
        self.assertFails(BTC="1")

    def test_rewritten_record_fails(self):
        path = os.path.join(self.clone, "sealed", "ledger.jsonl")
        with open(path, "rb") as f:
            data = f.read()
        i = data.index(b'"recorded_at":"') + len(b'"recorded_at":"2')
        data = data[:i] + (b"1" if data[i:i + 1] != b"1" else b"2") + data[i + 1:]
        with open(path, "wb") as f:
            f.write(data)
        self.git("commit", "-q", "-am", "書き換え")
        self.assertFails()

    def test_truncated_record_fails(self):
        path = os.path.join(self.clone, "sealed", "ledger.jsonl")
        with open(path, "rb") as f:
            lines = f.read().split(b"\n")[:-1]
        with open(path, "wb") as f:
            f.write(b"".join(l + b"\n" for l in lines[:-1]))
        self.git("commit", "-q", "-am", "切り詰め")
        self.assertFails()

    def test_later_append_still_matches(self):
        """投稿のあとに記録が増えても、先頭 N 行の値は変わらない（仮の追記。stamp はしないので
        verify.py は失敗する。(2) までが通ることを確かめる）。"""
        path = os.path.join(self.clone, "sealed", "ledger.jsonl")
        data = ledger.read_ledger(path)
        n = int(self.post["SEQ"])
        _recs, _rec, line = ledger.build_next_record(
            data, "periods", [tl.target("a/x.md")], "仮", ledger.parse_time("2099-01-01T00:00:00Z"))
        with open(path, "ab") as f:
            f.write(line)
        got = ledger.prefix_digest(ledger.read_ledger(path), n)
        self.assertEqual(got, self.post["POSTED"])
        block = self.blocks()[0].split("# (3)")[0]
        env = dict(os.environ, **self.post)
        r = subprocess.run(["bash", "-e", "-o", "pipefail", "-c", block], cwd=self.clone,
                           capture_output=True, env=env)
        self.assertEqual(r.returncode, 0, r.stdout.decode() + r.stderr.decode())


if __name__ == "__main__":
    unittest.main()
