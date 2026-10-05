"""公開前のメールアドレス検査（src/collector/privacy_scan.py）のテスト\u3002T-003\u3002

実行（プロジェクトのルートで\u3002__pycache__ を作らないよう、必ず次の形で）:
    PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest discover -s tests/collector -v

このファイルには、アドレスの形の文字列をそのまま書かない\u3002
検査に使う文字列は、実行中に部品を組み立てて作り、一時ディレクトリにだけ書く\u3002
ネットワークは使わない（Git のテストも、一時ディレクトリの中のリポジトリだけを使う）\u3002
"""

import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(os.path.dirname(HERE))
SRC = os.path.join(PROJECT, "src", "collector")
SCRIPT = os.path.join(SRC, "privacy_scan.py")
HOOK = os.path.join(SRC, "hooks", "pre-push")
sys.path.insert(0, SRC)

import privacy_scan  # noqa: E402

AT = "@"
ALLOWED = next(iter(privacy_scan.ALLOWED_ADDRESSES))
ALLOWED_LOCAL, ALLOWED_DOMAIN = ALLOWED.split(AT)


def make_address():
    """毎回ちがう部品で組み立てる\u3002出力に漏れていないかを、部品ごとに確かめるため\u3002"""
    local = "u" + uuid.uuid4().hex[:10]
    domain = "d" + uuid.uuid4().hex[:10] + ".example"
    return local, domain, local + AT + domain


def run_scan(root, extra=(), stdin=b""):
    proc = subprocess.run(
        [sys.executable, "-B", SCRIPT, "--root", root, *extra],
        input=stdin,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return proc.returncode, proc.stdout.decode("utf-8"), proc.stderr.decode("utf-8")


class TmpDirCase(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="privscan-")

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def write(self, rel, data):
        path = os.path.join(self.root, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        mode = "wb" if isinstance(data, bytes) else "w"
        with open(path, mode) as f:
            f.write(data)

    def assert_no_leak(self, out, err, *parts):
        for p in parts:
            self.assertNotIn(p, out)
            self.assertNotIn(p, err)


class DetectionTest(TmpDirCase):
    def assert_found(self, text, msg=None):
        local, domain, _ = make_address()
        self.write("a.txt", "first line\n" + text.format(l=local, d=domain) + "\n")
        code, out, err = run_scan(self.root)
        self.assertEqual(code, 1, msg or text)
        self.assertIn("a.txt", out)
        self.assertIn("行=2", out)
        self.assert_no_leak(out, err, local, domain)

    def test_plain(self):
        self.assert_found("contact: {l}" + AT + "{d} now")

    def test_mailto(self):
        self.assert_found('<a href="mailto:{l}' + AT + '{d}">x</a>')

    def test_mailto_percent(self):
        self.assert_found("mailto:{l}" + "%" + "40" + "{d}")

    def test_percent_encoded(self):
        self.assert_found("{l}" + "%" + "40" + "{d}")

    def test_double_percent_encoded(self):
        self.assert_found("{l}" + "%" + "2540" + "{d}")

    def test_html_decimal(self):
        self.assert_found("{l}" + "&" + "#64;" + "{d}")

    def test_html_hex(self):
        self.assert_found("{l}" + "&" + "#x40;" + "{d}")

    def test_html_named(self):
        self.assert_found("{l}" + "&" + "commat;" + "{d}")

    def test_bracket_at(self):
        self.assert_found("{l} " + "[" + "at" + "] " + "{d}")

    def test_paren_at_upper(self):
        self.assert_found("{l}" + "(" + "AT" + ")" + "{d}")

    def test_bracket_dot(self):
        def fmt(local, domain):
            return local + " [" + "at" + "] " + domain.replace(".", " (" + "dot" + ") ")
        local, domain, _ = make_address()
        self.write("a.txt", "x\n" + fmt(local, domain) + "\n")
        code, out, err = run_scan(self.root)
        self.assertEqual(code, 1)
        self.assert_no_leak(out, err, local, domain)

    def test_unicode_escape(self):
        self.assert_found("{l}" + "\\" + "u0040" + "{d}")

    def test_fullwidth_at(self):
        self.assert_found("{l}" + "\uff20" + "{d}")

    def test_binary_file(self):
        local, domain, addr = make_address()
        data = bytes(range(256)) + b"\x00\xff" + addr.encode() + b"\x00\x01\x02" + bytes(range(255, -1, -1))
        self.write("blob.bin", data)
        code, out, err = run_scan(self.root)
        self.assertEqual(code, 1)
        self.assertIn("blob.bin", out)
        self.assert_no_leak(out, err, local, domain)

    def test_binary_utf16(self):
        local, domain, addr = make_address()
        self.write("u16.bin", b"\xff\xfe" + addr.encode("utf-16-le"))
        code, out, err = run_scan(self.root)
        self.assertEqual(code, 1)
        self.assert_no_leak(out, err, local, domain)

    def test_count_and_line(self):
        local, domain, addr = make_address()
        self.write("m.txt", "a\nb\n" + addr + " and " + addr + "\n")
        code, out, _ = run_scan(self.root)
        self.assertEqual(code, 1)
        self.assertIn("m.txt 行=3 件数=2", out)

    def test_address_in_file_name_is_detected_and_withheld(self):
        local, domain, addr = make_address()
        self.write(os.path.join("sub", addr + ".txt"), "nothing here\n")
        code, out, err = run_scan(self.root)
        self.assertEqual(code, 1)
        self.assertIn("ファイル名を伏せた", out)
        self.assert_no_leak(out, err, local, domain)


class AllowListTest(TmpDirCase):
    def test_allowed_passes(self):
        self.write("a.txt", "Author <" + ALLOWED + ">\n")
        self.write("b.txt", "mailto:" + ALLOWED + "\n")
        self.write("c.txt", ALLOWED + ".\n")  # 文末の句点
        code, out, err = run_scan(self.root)
        self.assertEqual(code, 0, out + err)
        self.assertIn("OK", out)

    def assert_similar_found(self, text):
        self.write("a.txt", text + "\n")
        code, out, err = run_scan(self.root)
        self.assertEqual(code, 1, "similar address must be found")
        self.assert_no_leak(out, err, text)

    def test_prefix_letter(self):
        self.assert_similar_found("x" + ALLOWED)

    def test_prefix_digit(self):
        self.assert_similar_found("1" + ALLOWED)

    def test_prefix_dot(self):
        self.assert_similar_found("." + ALLOWED)

    def test_other_domain(self):
        self.assert_similar_found(ALLOWED_LOCAL + AT + "users.noreply.gitlab.com")

    def test_lookalike_domain(self):
        self.assert_similar_found(ALLOWED_LOCAL + AT + "users-noreply.github.com")

    def test_domain_suffix(self):
        self.assert_similar_found(ALLOWED + ".example")

    def test_domain_tld_appended(self):
        self.assert_similar_found(ALLOWED + "x")

    def test_other_local_same_domain(self):
        self.assert_similar_found("someone" + AT + ALLOWED_DOMAIN)

    def test_case_differs(self):
        self.assert_similar_found(ALLOWED.upper())


class CleanAndIgnoreTest(TmpDirCase):
    def test_clean_exits_zero(self):
        self.write("a.txt", "no addresses here; decorators @property and x@y are fine\n")
        self.write("b.bin", bytes(range(256)))
        code, out, err = run_scan(self.root)
        self.assertEqual(code, 0, out + err)
        self.assertEqual(err, "")

    def test_gitignore_respected(self):
        local, domain, addr = make_address()
        self.write(".gitignore", "secret/\n*.log\n!keep.log\n")
        self.write(os.path.join("secret", "a.txt"), addr + "\n")
        self.write("x.log", addr + "\n")
        code, out, err = run_scan(self.root)
        self.assertEqual(code, 0, out + err)
        self.write("keep.log", addr + "\n")
        code, out, err = run_scan(self.root)
        self.assertEqual(code, 1)
        self.assertIn("keep.log", out)
        self.assert_no_leak(out, err, local, domain)

    def test_unreadable_file_fails_closed(self):
        if os.geteuid() == 0:
            self.skipTest("root では読み取り権限を外せない")
        self.write("locked.txt", "x\n")
        os.chmod(os.path.join(self.root, "locked.txt"), 0)
        try:
            code, out, err = run_scan(self.root)
        finally:
            os.chmod(os.path.join(self.root, "locked.txt"), 0o600)
        self.assertEqual(code, 2)
        self.assertIn("ERROR", err)


class ProjectSourceIsCleanTest(unittest.TestCase):
    """このタスクで作ったソース自体が、検査に引っかからないこと\u3002"""

    def test_sources_clean(self):
        for d in (SRC, HERE, os.path.join(PROJECT, ".github", "workflows")):
            code, out, err = run_scan(d)
            self.assertEqual(code, 0, d + "\n" + out + err)


GIT = shutil.which("git")


@unittest.skipIf(GIT is None, "git が無い環境")
class GitTest(TmpDirCase):
    def setUp(self):
        super().setUp()
        self.repo = os.path.join(self.root, "repo")
        os.makedirs(self.repo)
        self.env = dict(os.environ)
        # 利用者の Git 設定やフックの影響を受けないようにする
        self.env.update({
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_TERMINAL_PROMPT": "0",
        })
        self.set_identity(ALLOWED)
        self.git("init", "-q", "-b", "main")
        self.git("config", "commit.gpgsign", "false")

    def set_identity(self, addr):
        for k in ("GIT_AUTHOR_EMAIL", "GIT_COMMITTER_EMAIL"):
            self.env[k] = addr
        self.env["GIT_AUTHOR_NAME"] = "Tester"
        self.env["GIT_COMMITTER_NAME"] = "Tester"

    def git(self, *args, cwd=None, check=True):
        proc = subprocess.run(
            ["git", *args], cwd=cwd or self.repo, env=self.env,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        if check and proc.returncode != 0:
            raise AssertionError("git %s failed" % args[0])
        return proc

    def put(self, rel, text):
        path = os.path.join(self.repo, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(text)

    def commit(self, rel, text, msg="c"):
        self.put(rel, text)
        self.git("add", rel)
        self.git("commit", "-q", "-m", msg)
        return self.git("rev-parse", "HEAD").stdout.decode().strip()

    def test_clean_repo_with_allowed_identity(self):
        self.commit("a.txt", "hello\n")
        code, out, err = run_scan(self.repo)
        self.assertEqual(code, 0, out + err)
        self.assertIn("Git のリポジトリ", out)

    def test_author_address_detected(self):
        local, domain, addr = make_address()
        self.env["GIT_AUTHOR_EMAIL"] = addr
        sha = self.commit("a.txt", "hello\n")
        code, out, err = run_scan(self.repo)
        self.assertEqual(code, 1)
        self.assertIn("commit " + sha, out)
        self.assert_no_leak(out, err, local, domain)

    def test_committer_address_detected(self):
        local, domain, addr = make_address()
        self.env["GIT_COMMITTER_EMAIL"] = addr
        sha = self.commit("a.txt", "hello\n")
        code, out, err = run_scan(self.repo)
        self.assertEqual(code, 1)
        self.assertIn("commit " + sha, out)
        self.assert_no_leak(out, err, local, domain)

    def test_commit_message_trailer_detected(self):
        local, domain, addr = make_address()
        sha = self.commit("a.txt", "hello\n", msg="x\n\nCo-Authored-By: Bot <" + addr + ">")
        code, out, err = run_scan(self.repo)
        self.assertEqual(code, 1)
        self.assertIn("commit " + sha, out)
        self.assert_no_leak(out, err, local, domain)

    def test_address_removed_later_still_in_history(self):
        local, domain, addr = make_address()
        first = self.commit("a.txt", addr + "\n")
        self.commit("a.txt", "clean\n")
        code, out, err = run_scan(self.repo)
        self.assertEqual(code, 1)
        self.assertIn("commit " + first, out)
        self.assert_no_leak(out, err, local, domain)

    def test_staged_only_file_detected(self):
        self.commit("a.txt", "hello\n")
        local, domain, addr = make_address()
        self.put("b.txt", addr + "\n")
        self.git("add", "b.txt")
        code, out, err = run_scan(self.repo)
        self.assertEqual(code, 1)
        self.assertIn("b.txt", out)
        self.assert_no_leak(out, err, local, domain)

    def test_staged_content_differs_from_worktree(self):
        self.commit("a.txt", "hello\n")
        local, domain, addr = make_address()
        self.put("a.txt", addr + "\n")
        self.git("add", "a.txt")
        self.put("a.txt", "clean again\n")  # 作業ツリーだけ戻す
        code, out, err = run_scan(self.repo)
        self.assertEqual(code, 1)
        self.assertIn("index:a.txt", out)
        self.assert_no_leak(out, err, local, domain)

    def test_untracked_ignored_by_git_mode(self):
        self.commit("a.txt", "hello\n")
        local, domain, addr = make_address()
        self.put(".gitignore", "local/\n")
        self.git("add", ".gitignore")
        self.git("commit", "-q", "-m", "ignore")
        self.put(os.path.join("local", "x.txt"), addr + "\n")
        code, out, err = run_scan(self.repo)
        self.assertEqual(code, 0, out + err)

    def make_remote(self, name="origin"):
        bare = os.path.join(self.root, name + ".git")
        self.git("init", "-q", "--bare", bare, cwd=self.root)
        self.git("remote", "add", name, bare)
        return bare

    def test_default_mode_excludes_only_upstream_remote(self):
        """指定なしのモード：除くのは上流のリモート（pub）に push 済みのものだけ\u3002

        別のリモート（priv）に push 済みのコミットは、検査の対象に残る\u3002
        """
        self.make_remote("pub")
        self.make_remote("priv")
        local, domain, addr = make_address()
        self.env["GIT_AUTHOR_EMAIL"] = addr
        on_pub = self.commit("a.txt", "hello\n")
        self.git("push", "-q", "--no-verify", "-u", "pub", "main")
        code, out, err = run_scan(self.repo)
        self.assertEqual(code, 0, out + err)  # 上流に push 済みのものは除く
        self.assertIn("コミット=0", out)

        on_priv = self.commit("b.txt", "more\n")
        self.git("push", "-q", "--no-verify", "priv", "main")
        code, out, err = run_scan(self.repo)
        self.assertEqual(code, 1)
        self.assertIn("commit " + on_priv, out)
        self.assertNotIn("commit " + on_pub, out)
        self.assert_no_leak(out, err, local, domain)

    def test_full_history_without_upstream(self):
        self.make_remote()
        local, domain, addr = make_address()
        self.env["GIT_AUTHOR_EMAIL"] = addr
        old = self.commit("a.txt", "hello\n")
        self.git("push", "-q", "--no-verify", "origin", "main")  # 上流は設定しない
        self.set_identity(ALLOWED)
        self.commit("b.txt", "more\n")
        code, out, err = run_scan(self.repo)
        self.assertEqual(code, 1)
        self.assertIn("commit " + old, out)
        self.assert_no_leak(out, err, local, domain)

    def test_annotated_tag_detected(self):
        self.commit("a.txt", "hello\n")
        local, domain, addr = make_address()
        self.env["GIT_COMMITTER_EMAIL"] = addr  # タグ作成者
        self.git("tag", "-a", "v0", "-m", "t")
        code, out, err = run_scan(self.repo)
        self.assertEqual(code, 1)
        self.assertIn("tag ", out)
        self.assert_no_leak(out, err, local, domain)

    def install_hook(self):
        dst = os.path.join(self.repo, "src", "collector")
        os.makedirs(os.path.join(dst, "hooks"))
        shutil.copy(SCRIPT, dst)
        shutil.copy(HOOK, os.path.join(dst, "hooks"))
        os.chmod(os.path.join(dst, "hooks", "pre-push"), 0o755)
        self.git("config", "core.hooksPath", "src/collector/hooks")
        self.put(".gitignore", "__pycache__/\n")
        self.git("add", ".")
        self.git("commit", "-q", "-m", "tooling")

    def test_force_push_amended_with_bad_author_is_blocked(self):
        """F1：push 済みのコミットを、アドレス入りの作成者で作り直して force push する。"""
        self.install_hook()
        pub = self.make_remote("pub")
        self.commit("a.txt", "a\n")
        self.git("push", "-q", "pub", "main")
        before = self.git("--git-dir=" + pub, "rev-parse", "refs/heads/main").stdout
        local, domain, addr = make_address()
        self.set_identity(addr)
        self.git("commit", "-q", "--amend", "--reset-author", "-m", "a2")
        self.set_identity(ALLOWED)
        ng = self.git("push", "-f", "pub", "main", check=False)
        self.assertNotEqual(ng.returncode, 0)
        both = (ng.stdout + ng.stderr).decode("utf-8", "replace")
        self.assertIn("push を止める", both)
        self.assert_no_leak(both, "", local, domain)
        after = self.git("--git-dir=" + pub, "rev-parse", "refs/heads/main").stdout
        self.assertEqual(before, after)

    def test_force_push_with_unknown_remote_sha_scans_full_history(self):
        """F2：push 先が手元に無いコミットまで進んでいる状態で force push する。"""
        self.install_hook()
        pub = self.make_remote("pub")
        self.commit("a.txt", "a\n")
        self.git("push", "-q", "pub", "main")
        other = os.path.join(self.root, "other")
        self.git("clone", "-q", "-b", "main", pub, other, cwd=self.root)
        self.git("config", "commit.gpgsign", "false", cwd=other)
        with open(os.path.join(other, "o.txt"), "w") as f:
            f.write("o\n")
        self.git("add", "o.txt", cwd=other)
        self.git("commit", "-q", "-m", "other", cwd=other)
        self.git("push", "-q", "--no-verify", "origin", "main", cwd=other)
        remote_head = self.git("--git-dir=" + pub, "rev-parse", "refs/heads/main").stdout
        remote_sha = remote_head.decode().strip()
        self.assertNotEqual(
            self.git("cat-file", "-e", remote_sha, check=False).returncode, 0,
            "remote sha が手元に無い状態を作れていない")

        local, domain, addr = make_address()
        self.env["GIT_AUTHOR_EMAIL"] = addr
        bad = self.commit("b.txt", "b\n")
        self.set_identity(ALLOWED)
        ng = self.git("push", "-f", "pub", "main", check=False)
        self.assertNotEqual(ng.returncode, 0)
        both = (ng.stdout + ng.stderr).decode("utf-8", "replace")
        self.assertIn("push を止める", both)
        self.assert_no_leak(both, "", local, domain)
        self.assertEqual(self.git("--git-dir=" + pub, "rev-parse", "refs/heads/main").stdout,
                         remote_head)

        # 対照：アドレスの入ったコミットを捨てて作り直せば、force push は通る
        self.git("reset", "-q", "--hard", "HEAD~1")
        ok = self.git("push", "-f", "pub", "main", check=False)
        self.assertEqual(ok.returncode, 0, ok.stderr.decode("utf-8", "replace"))
        self.assertNotIn(bad.encode(), self.git("--git-dir=" + pub, "rev-list", "--all").stdout)

    def test_pre_push_hook_blocks_and_allows(self):
        self.make_remote()
        self.install_hook()
        ok = self.git("push", "-q", "origin", "main", check=False)
        self.assertEqual(ok.returncode, 0, ok.stderr.decode("utf-8", "replace"))

        local, domain, addr = make_address()
        self.env["GIT_AUTHOR_EMAIL"] = addr
        self.commit("bad.txt", "hello\n")
        ng = self.git("push", "origin", "main", check=False)
        self.assertNotEqual(ng.returncode, 0)
        both = (ng.stdout + ng.stderr).decode("utf-8", "replace")
        self.assertIn("push を止める", both)
        self.assert_no_leak(both, "", local, domain)
        # リモート側の main が、止めたコミットに進んでいないこと
        bare = os.path.join(self.root, "origin.git")
        bare_head = self.git("--git-dir=" + bare, "rev-parse", "refs/heads/main")
        local_head = self.git("rev-parse", "HEAD")
        self.assertNotEqual(bare_head.stdout, local_head.stdout)

    def test_pre_push_mode_reads_stdin(self):
        self.make_remote()
        self.commit("a.txt", "hello\n")
        self.git("push", "-q", "--no-verify", "-u", "origin", "main")
        local, domain, addr = make_address()
        self.env["GIT_AUTHOR_EMAIL"] = addr
        sha = self.commit("b.txt", "x\n")
        line = ("refs/heads/main %s refs/heads/main %s\n" % (sha, "0" * 40)).encode()
        code, out, err = run_scan(self.repo, ["--pre-push"], stdin=line)
        self.assertEqual(code, 1)
        self.assertIn("commit " + sha, out)
        self.assert_no_leak(out, err, local, domain)

    def test_pre_push_bad_stdin_fails_closed(self):
        self.commit("a.txt", "hello\n")
        code, out, err = run_scan(self.repo, ["--pre-push"], stdin=b"a --output=x b c\n")
        self.assertEqual(code, 2)



    # --- 差し戻し 1 回目（2026-10-06）の指摘の再現 ---

    def test_ci_checkout_sets_upstream_so_all_history_is_required(self):
        """actions/checkout と同じ手順（fetch と checkout -B）で上流が設定される\u3002

        指定なしのモードでは履歴を検査しなくなるので、CI は --all-history を使う\u3002
        """
        origin = self.make_remote("origin")
        local, domain, addr = make_address()
        self.env["GIT_AUTHOR_EMAIL"] = addr
        bad = self.commit("a.txt", "hello\n")
        self.set_identity(ALLOWED)
        self.commit("b.txt", "clean\n")
        self.git("push", "-q", "--no-verify", "origin", "main")

        ci = os.path.join(self.root, "ci")
        os.makedirs(ci)
        self.git("init", "-q", cwd=ci)
        self.git("remote", "add", "origin", origin, cwd=ci)
        self.git("fetch", "-q", "--prune", "--no-recurse-submodules", "origin",
                 "+refs/heads/*:refs/remotes/origin/*", "+refs/tags/*:refs/tags/*", cwd=ci)
        self.git("checkout", "-q", "--force", "-B", "main", "refs/remotes/origin/main", cwd=ci)
        up = self.git("rev-parse", "--abbrev-ref", "@{upstream}", cwd=ci).stdout.decode().strip()
        self.assertEqual(up, "origin/main")

        code, out, _ = run_scan(ci)  # 指定なし：上流があるので履歴は 0 件になる
        self.assertIn("コミット=0", out)
        code, out, err = run_scan(ci, ["--all-history"])
        self.assertEqual(code, 1)
        self.assertIn("commit " + bad, out)
        self.assert_no_leak(out, err, local, domain)

    def test_stash_is_part_of_all_history(self):
        """--all には refs/stash も入る\u3002stash の中のアドレスも失敗になる（安全側）\u3002"""
        self.commit("a.txt", "hello\n")
        local, domain, addr = make_address()
        self.put("a.txt", addr + "\n")
        self.git("stash", "-q")
        code, out, err = run_scan(self.repo, ["--all-history"])
        self.assertEqual(code, 1)
        self.assert_no_leak(out, err, local, domain)

    def test_pre_push_to_public_scans_commits_already_on_private(self):
        """非公開のリモート priv に push 済みでも、公開のリモート pub への push は止まる\u3002"""
        self.make_remote("priv")
        pub = self.make_remote("pub")
        self.install_hook()
        local, domain, addr = make_address()
        self.env["GIT_AUTHOR_EMAIL"] = addr
        self.commit("bad.txt", "hello\n")
        self.git("push", "-q", "--no-verify", "-u", "priv", "main")

        ng = self.git("push", "pub", "main", check=False)
        self.assertNotEqual(ng.returncode, 0)
        both = (ng.stdout + ng.stderr).decode("utf-8", "replace")
        self.assertIn("push を止める", both)
        self.assert_no_leak(both, "", local, domain)
        refs = self.git("--git-dir=" + pub, "for-each-ref").stdout
        self.assertEqual(refs, b"")  # pub には何も届いていない

    def test_pre_push_mode_excludes_only_remote_sha(self):
        """除外の基準は標準入力の remote sha だけ。追跡参照には依らない。"""
        self.make_remote("priv")
        self.make_remote("pub")
        local, domain, addr = make_address()
        self.env["GIT_AUTHOR_EMAIL"] = addr
        bad = self.commit("bad.txt", "hello\n")
        self.git("push", "-q", "--no-verify", "priv", "main")  # 追跡参照 priv/main ができる
        # 新しいブランチ（remote sha が全 0）：全履歴を検査する
        line = ("refs/heads/main %s refs/heads/main %s\n" % (bad, "0" * 40)).encode()
        code, out, err = run_scan(self.repo, ["--pre-push"], stdin=line)
        self.assertEqual(code, 1)
        self.assertIn("commit " + bad, out)
        self.assert_no_leak(out, err, local, domain)
        # remote sha が手元に無い：全履歴を検査する
        line = ("refs/heads/main %s refs/heads/main %s\n" % (bad, "e" * 40)).encode()
        code, out, err = run_scan(self.repo, ["--pre-push"], stdin=line)
        self.assertEqual(code, 1)
        self.assertIn("commit " + bad, out)
        # push 先が bad を持っていると答えた場合だけ、bad を除く
        self.set_identity(ALLOWED)
        new = self.commit("ok.txt", "fine\n")
        line = ("refs/heads/main %s refs/heads/main %s\n" % (new, bad)).encode()
        code, out, err = run_scan(self.repo, ["--pre-push"], stdin=line)
        self.assertEqual(code, 0, out + err)
        self.assertIn("コミット=1", out)

    def test_remote_option_is_rejected(self):
        """--remote は廃止した。古いフックから渡されたら、安全側に倒して止める。"""
        self.commit("a.txt", "hello\n")
        code, out, err = run_scan(self.repo, ["--pre-push", "--remote=origin"], stdin=b"")
        self.assertEqual(code, 2)

    def assert_push_blocked(self, target, pub_bare, local, domain):
        ng = self.git("push", target, "main", check=False)
        self.assertNotEqual(ng.returncode, 0)
        both = (ng.stdout + ng.stderr).decode("utf-8", "replace")
        self.assertIn("push を止める", both)
        self.assert_no_leak(both, "", local, domain)
        self.assertEqual(self.git("--git-dir=" + pub_bare, "for-each-ref").stdout, b"")

    def bad_commit(self):
        local, domain, addr = make_address()
        self.env["GIT_AUTHOR_EMAIL"] = addr
        self.commit("bad.txt", "hello\n")
        self.set_identity(ALLOWED)
        return local, domain

    def test_hook_blocks_after_set_url(self):
        """非公開を指していたリモートの URL を、公開側に付け替えても止まる。"""
        self.install_hook()
        priv = os.path.join(self.root, "priv.git")
        pub = os.path.join(self.root, "pub.git")
        self.git("init", "-q", "--bare", priv, cwd=self.root)
        self.git("init", "-q", "--bare", pub, cwd=self.root)
        self.git("remote", "add", "origin", priv)
        local, domain = self.bad_commit()
        self.git("push", "-q", "--no-verify", "-u", "origin", "main")
        self.git("remote", "set-url", "origin", pub)
        self.assert_push_blocked("origin", pub, local, domain)

    def test_hook_blocks_after_rename(self):
        """非公開のリモートの名前を変え、公開側に向けても止まる。"""
        self.install_hook()
        self.make_remote("priv")
        pub = os.path.join(self.root, "pub.git")
        self.git("init", "-q", "--bare", pub, cwd=self.root)
        local, domain = self.bad_commit()
        self.git("push", "-q", "--no-verify", "-u", "priv", "main")
        self.git("remote", "rename", "priv", "pub")
        self.git("remote", "set-url", "pub", pub)
        self.assert_push_blocked("pub", pub, local, domain)

    def test_hook_blocks_with_slash_in_remote_name(self):
        """非公開のリモートの名前が pub/priv（追跡参照が refs/remotes/pub/priv/*）でも止まる。"""
        self.install_hook()
        pub = self.make_remote("pub")
        priv = os.path.join(self.root, "privslash.git")
        self.git("init", "-q", "--bare", priv, cwd=self.root)
        self.git("remote", "add", "pub/priv", priv)
        local, domain = self.bad_commit()
        self.git("push", "-q", "--no-verify", "pub/priv", "main")
        self.assert_push_blocked("pub", pub, local, domain)

    def test_hook_blocks_with_rewritten_fetch_refspec(self):
        """非公開のリモートの fetch の行き先が refs/remotes/pub/* でも止まる。"""
        self.install_hook()
        pub = self.make_remote("pub")
        self.make_remote("priv")
        self.git("config", "remote.priv.fetch", "+refs/heads/*:refs/remotes/pub/*")
        local, domain = self.bad_commit()
        self.git("push", "-q", "--no-verify", "priv", "main")
        self.git("fetch", "-q", "priv")
        self.assertEqual(self.git("rev-parse", "refs/remotes/pub/main").returncode, 0)
        self.assert_push_blocked("pub", pub, local, domain)

    def test_hook_blocks_push_by_url(self):
        self.install_hook()
        self.make_remote("priv")
        url = os.path.join(self.root, "byurl.git")
        self.git("init", "-q", "--bare", url, cwd=self.root)
        local, domain = self.bad_commit()
        self.git("push", "-q", "--no-verify", "priv", "main")
        self.assert_push_blocked(url, url, local, domain)

    def test_branch_name_detected_and_withheld(self):
        self.commit("a.txt", "hello\n")
        local, domain, addr = make_address()
        self.git("branch", "feature/" + addr)
        code, out, err = run_scan(self.repo)
        self.assertEqual(code, 1)
        self.assertIn("参照の名前の中", out)
        self.assert_no_leak(out, err, local, domain)

    def test_tag_name_detected_and_withheld(self):
        self.commit("a.txt", "hello\n")
        local, domain, addr = make_address()
        self.git("tag", "v-" + addr)
        code, out, err = run_scan(self.repo, ["--all-history"])
        self.assertEqual(code, 1)
        self.assert_no_leak(out, err, local, domain)

    def test_pre_push_stdin_ref_names_detected(self):
        sha = self.commit("a.txt", "hello\n")
        for which in (0, 1):
            local, domain, addr = make_address()
            refs = ["refs/heads/main", "refs/heads/main"]
            refs[which] = "refs/heads/" + addr
            line = ("%s %s %s %s\n" % (refs[0], sha, refs[1], "0" * 40)).encode()
            code, out, err = run_scan(self.repo, ["--pre-push"], stdin=line)
            self.assertEqual(code, 1, which)
            self.assertIn("参照の名前の中", out)
            self.assert_no_leak(out, err, local, domain)

    def test_pre_push_stdin_wrong_field_count_fails(self):
        sha = self.commit("a.txt", "hello\n")
        for line in ("refs/heads/main %s refs/heads/main\n" % sha,
                     "refs/heads/main %s refs/heads/main %s extra\n" % (sha, "0" * 40)):
            code, out, err = run_scan(self.repo, ["--pre-push"],
                                      stdin=line.encode())
            self.assertEqual(code, 2, line)

    def test_submodule_in_index_fails(self):
        sha = self.commit("a.txt", "hello\n")
        self.git("update-index", "--add", "--cacheinfo", "160000,%s,sub" % sha)
        code, out, err = run_scan(self.repo)
        self.assertEqual(code, 2)
        self.assertIn("サブモジュール", err)

    def test_submodule_in_history_fails(self):
        sha = self.commit("a.txt", "hello\n")
        self.git("update-index", "--add", "--cacheinfo", "160000,%s,sub" % sha)
        self.git("commit", "-q", "-m", "sub")
        self.git("rm", "-q", "--cached", "sub")
        self.git("commit", "-q", "-m", "unsub")  # インデックスからは消えても、履歴に残る
        code, out, err = run_scan(self.repo, ["--all-history"])
        self.assertEqual(code, 2)
        self.assertIn("サブモジュール", err)

    def test_lfs_pointer_fails(self):
        self.commit("big.bin", "version https://git-lfs.github.com/spec/v1\n"
                    "oid sha256:" + "0" * 64 + "\nsize 12\n")
        code, out, err = run_scan(self.repo, ["--all-history"])
        self.assertEqual(code, 2)
        self.assertIn("LFS", err)

    def test_lightweight_tag_to_blob_fails(self):
        self.commit("a.txt", "hello\n")
        blob = self.git("rev-parse", "HEAD:a.txt").stdout.decode().strip()
        self.git("tag", "b", blob)
        code, out, err = run_scan(self.repo)
        self.assertEqual(code, 2)

    def test_annotated_tag_to_blob_fails(self):
        self.commit("a.txt", "hello\n")
        blob = self.git("rev-parse", "HEAD:a.txt").stdout.decode().strip()
        self.git("tag", "-a", "b", "-m", "t", blob)
        code, out, err = run_scan(self.repo)
        self.assertEqual(code, 2)
        self.assertIn("タグ", err)

    def test_bad_arguments_do_not_echo(self):
        local, domain, addr = make_address()
        code, out, err = run_scan(self.repo, ["--remote=" + addr, "--unknown", addr])
        self.assertEqual(code, 2)
        self.assert_no_leak(out, err, local, domain)


class AllowListFixedTest(unittest.TestCase):
    """許可の一覧を固定する\u3002件数は 1 件で、値は CLAUDE.md の作成者の行と一致する\u3002"""

    def test_exactly_one(self):
        self.assertEqual(len(privacy_scan.ALLOWED_ADDRESSES), 1)

    def test_matches_claude_md(self):
        with open(os.path.join(PROJECT, "CLAUDE.md"), encoding="utf-8") as f:
            text = f.read()
        section = text.split("### 作成者と個人情報", 1)[1]
        m = re.search(r"Git の作成者は `[^<`]*<([^>`]+)>`", section)
        self.assertIsNotNone(m)
        self.assertEqual(privacy_scan.ALLOWED_ADDRESSES, frozenset({m.group(1)}))


class HardenedDetectionTest(TmpDirCase):
    """差し戻し 1 回目の指摘 7（検出の穴）の再現\u3002"""

    def assert_found_fn(self, build):
        local, domain, _ = make_address()
        self.write("a.txt", "first\n" + build(local, domain) + "\n")
        code, out, err = run_scan(self.root)
        self.assertEqual(code, 1, repr(build(local, domain)))
        self.assertIn("行=2", out)
        self.assert_no_leak(out, err, local, domain)

    def test_nfkc_fullwidth_everything(self):
        def fw(s):
            return "".join(chr(ord(c) + 0xFEE0) if "!" <= c <= "~" else c for c in s)
        self.assert_found_fn(lambda l, d: fw(l + AT + d))

    def test_zero_width_space(self):
        self.assert_found_fn(lambda l, d: l + "\u200b" + AT + "\u200b" + d.replace(".", "\u200b."))

    def test_zero_width_joiner_and_bom(self):
        self.assert_found_fn(lambda l, d: l[:3] + "\u200d" + l[3:] + AT + "\ufeff" + d)

    def test_soft_hyphen(self):
        self.assert_found_fn(lambda l, d: l[:2] + "\u00ad" + l[2:] + AT + d)

    def test_spaces_around_at_and_dot(self):
        self.assert_found_fn(lambda l, d: l + " " + AT + " " + d.replace(".", " . "))

    def test_ideographic_full_stop(self):
        self.assert_found_fn(lambda l, d: l + AT + d.replace(".", "\u3002"))

    def test_fullwidth_full_stop(self):
        self.assert_found_fn(lambda l, d: l + AT + d.replace(".", "\uff0e"))

    def test_encoded_dot_percent(self):
        self.assert_found_fn(lambda l, d: l + AT + d.replace(".", "%" + "2E"))

    def test_encoded_dot_html(self):
        self.assert_found_fn(lambda l, d: l + AT + d.replace(".", "&" + "#46;"))

    def test_backslash_at(self):
        self.assert_found_fn(lambda l, d: l + "\\" + AT + d)

    def test_quoted_printable(self):
        self.assert_found_fn(lambda l, d: l + "=" + "40" + d)

    def test_hex_escape(self):
        self.assert_found_fn(lambda l, d: l + "\\" + "x40" + d)

    def test_html_entity_double_encoded(self):
        self.assert_found_fn(lambda l, d: l + "&" + "amp;" + "#64;" + d)

    def test_allowed_with_zero_width_still_allowed(self):
        self.write("a.txt", ALLOWED.replace(AT, "\u200b" + AT) + "\n")
        code, out, err = run_scan(self.root)
        self.assertEqual(code, 0, out + err)



def workflow_scan_commands(text):
    """yml の中で検査のスクリプトを呼ぶコマンドを、すべて取り出す（標準ライブラリだけ）。

    - コメント（行頭の # と、空白に続く # 以降）を除く
    - privacy_scan を含む行を見つけたら、行末の \\ で続く行をつなげて 1 つのコマンドにする
    - `run: 1 行` と `run: |` / `run: >` のブロックの形の、どちらでも同じに扱う
      （ブロックの中も 1 行ずつ見るため。フラグを別の行に分けて書くと、
      \\ でつながない限り「付いていない」と判定する。安全側）
    """
    lines = []
    for raw in text.splitlines():
        line = re.sub(r"(^|\s)#.*$", "", raw)
        lines.append(line)
    commands = []
    i = 0
    while i < len(lines):
        if "privacy_scan" in lines[i]:
            cmd = lines[i]
            while cmd.rstrip().endswith("\\") and i + 1 < len(lines):
                i += 1
                cmd = cmd.rstrip()[:-1] + " " + lines[i]
            commands.append(cmd)
        i += 1
    return commands


def check_workflow(text):
    """問題の一覧を返す（空なら合格）。"""
    problems = []
    commands = workflow_scan_commands(text)
    if not commands:
        problems.append("検査のスクリプトを呼んでいない")
    for cmd in commands:
        if not re.search(r"(^|\s)--all-history(\s|$)", cmd):
            problems.append("--all-history が付いていない呼び出しがある")
        if "||" in cmd:
            problems.append("失敗を握りつぶせる形（||）がある")
        if not re.match(r"^\s*(?:-\s*)?(?:run\s*:\s*)?python3?(?:\s|$)", cmd):
            problems.append("呼び出しの行が python / python3 で始まっていない")
    body = "\n".join(_strip_comments(text))
    if re.search(r"continue-on-error", body):
        problems.append("continue-on-error がある")
    # step にも job にも if: を置かない（ファイルのどこにも置かない、で確かめる）
    if re.search(r"(?m)^\s*(?:-\s*)?if\s*:", body):
        problems.append("if: がある")
    if re.search(r"(?m)\bset\s+[+]e\b|\bset\s+[+]o\s+errexit\b", body):
        problems.append("set +e がある")
    if re.search(r"\bexit\s+0\b", body):
        problems.append("exit 0 がある")
    problems += check_triggers(body)
    return problems


def _strip_comments(text):
    return [re.sub(r"(^|\s)#.*$", "", raw) for raw in text.splitlines()]


_FILTER_KEYS = {"branches", "branches-ignore", "paths", "paths-ignore", "tags", "tags-ignore"}


def check_triggers(body):
    """on: に push と pull_request があり、どちらにも絞り込みが無いことを確かめる。"""
    lines = body.splitlines()
    idx = next((i for i, l in enumerate(lines)
                if re.match(r"""^(?:on|"on"|'on')\s*:""", l)), None)
    if idx is None:
        return ["on: が無い"]
    inline = lines[idx].split(":", 1)[1].strip()
    if inline:
        events = {e.strip() for e in inline.strip("[]").split(",") if e.strip()}
        missing = {"push", "pull_request"} - events
        return ["on: に %s が無い" % sorted(missing)] if missing else []
    block = []
    for l in lines[idx + 1:]:
        if not l.strip():
            continue
        if not l.startswith((" ", "\t")):
            break
        block.append(l)
    if not block:
        return ["on: が空"]
    base = min(len(l) - len(l.lstrip()) for l in block)
    events = {}
    current = None
    for l in block:
        indent = len(l) - len(l.lstrip())
        key, _, value = l.strip().partition(":")
        if indent == base:
            current = key.strip()
            events[current] = []
            if value.strip() not in ("", "null", "~", "{}"):
                events[current].append("(1 行で書いた設定)")
        elif current is not None:
            events[current].append(key.strip().lstrip("- ").strip())
    problems = []
    for ev in ("push", "pull_request"):
        if ev not in events:
            problems.append("on: に %s が無い" % ev)
            continue
        for k in events[ev]:
            if k in _FILTER_KEYS or k == "(1 行で書いた設定)":
                problems.append("on.%s に絞り込み（%s）がある" % (ev, k))
    return problems


class WorkflowTest(unittest.TestCase):
    """CI が全履歴を検査していることを、yml の全体から確かめる。"""

    def test_real_workflow(self):
        path = os.path.join(PROJECT, ".github", "workflows", "privacy-scan.yml")
        with open(path, encoding="utf-8") as f:
            text = f.read()
        self.assertEqual(check_workflow(text), [])
        self.assertGreaterEqual(len(workflow_scan_commands(text)), 1)

    def test_checker_handles_block_forms(self):
        good_block = (
            "steps:\n  - run: |\n      echo hi\n"
            "      python3 -B src/collector/privacy_scan.py --root x --all-history\n"
        )
        bad_block = (
            "steps:\n  - run: |\n      echo hi\n"
            "      python3 -B src/collector/privacy_scan.py --root x\n"
        )
        bad_second = good_block + "  - run: python3 src/collector/privacy_scan.py\n"
        bad_folded = (
            "steps:\n  - run: >\n      python3 src/collector/privacy_scan.py\n"
            "      --all-history\n"
        )
        good_continued = (
            "steps:\n  - run: |\n      python3 src/collector/privacy_scan.py \\\n"
            "        --all-history\n"
        )
        bad_comment = "steps:\n  - run: python3 src/collector/privacy_scan.py # --all-history\n"
        bad_none = "steps:\n  - run: echo nothing\n"
        bad_or_true = (
            "steps:\n  - run: python3 src/collector/privacy_scan.py --all-history || true\n"
        )
        bad_continue = good_block + "    continue-on-error: true\n"
        on = "on:\n  push:\n  pull_request:\n"
        good_block = on + good_block
        good_continued = on + good_continued
        bad_block, bad_second, bad_folded, bad_comment, bad_none, bad_or_true, bad_continue = (
            on + x for x in (bad_block, bad_second, bad_folded, bad_comment, bad_none,
                             bad_or_true, bad_continue))
        self.assertEqual(check_workflow(good_block), [])
        self.assertEqual(check_workflow(good_continued), [])
        for bad in (bad_block, bad_second, bad_folded, bad_comment, bad_none,
                    bad_or_true, bad_continue):
            self.assertNotEqual(check_workflow(bad), [], bad)


class WorkflowGuardTest(unittest.TestCase):
    """差し戻し 3 回目の指摘 3：if:・on:・python で始まること・set +e・exit 0。"""

    def setUp(self):
        path = os.path.join(PROJECT, ".github", "workflows", "privacy-scan.yml")
        with open(path, encoding="utf-8") as f:
            self.real = f.read()
        self.step = next(l for l in self.real.splitlines() if "privacy_scan.py" in l
                         and l.strip().startswith("run:"))

    def assert_rejected(self, text):
        self.assertNotEqual(text, self.real, "置き換えが効いていない")
        self.assertNotEqual(check_workflow(text), [], text)

    def test_real_passes(self):
        self.assertEqual(check_workflow(self.real), [])

    def test_step_if(self):
        self.assert_rejected(self.real.replace(self.step, "        if: false\n" + self.step))

    def test_job_if(self):
        self.assert_rejected(self.real.replace("    runs-on:", "    if: ${{ false }}\n    runs-on:"))

    def test_on_without_push_or_pr(self):
        self.assert_rejected(self.real.replace("on:\n  push:\n  pull_request:",
                                               "on:\n  workflow_dispatch:"))
        self.assert_rejected(self.real.replace("on:\n  push:\n  pull_request:",
                                               "on:\n  push:"))
        self.assert_rejected(self.real.replace("on:\n  push:\n  pull_request:",
                                               "on: [push]"))

    def test_on_inline_both_is_ok(self):
        text = self.real.replace("on:\n  push:\n  pull_request:", "on: [push, pull_request]")
        self.assertNotEqual(text, self.real)
        self.assertEqual(check_workflow(text), [])

    def test_trigger_filters(self):
        for ev in ("push", "pull_request"):
            for key, val in (("branches", "[nothing]"), ("paths", "['x/**']"),
                             ("tags", "['v*']"), ("branches-ignore", "[main]"),
                             ("paths-ignore", "['**']"), ("tags-ignore", "['*']")):
                self.assert_rejected(self.real.replace(
                    "  %s:\n" % ev, "  %s:\n    %s: %s\n" % (ev, key, val), 1))
        self.assert_rejected(self.real.replace("  push:\n", "  push: {branches: [x]}\n", 1))

    def test_echo_only(self):
        self.assert_rejected(self.real.replace(
            self.step, '        run: echo "privacy_scan --all-history skipped"'))

    def test_set_plus_e_and_exit_0(self):
        cmd = "python3 -B src/collector/privacy_scan.py --all-history"
        for body in ("set +e\n          " + cmd,
                     cmd + "\n          exit 0",
                     "set +o errexit\n          " + cmd):
            self.assert_rejected(self.real.replace(
                self.step, "        run: |\n          " + body))


class Round3DetectionTest(TmpDirCase):
    """差し戻し 2 回目の指摘 2・4・5・6 の再現。"""

    def assert_found_text(self, text):
        self.write("a.txt", "first\n" + text + "\n")
        code, out, err = run_scan(self.root)
        self.assertEqual(code, 1, repr(text))
        self.assertIn("行=2", out)
        return out, err

    def test_percent_5_to_7_layers(self):
        for n in (5, 6, 7):
            local, domain, _ = make_address()
            enc = "%" + "25" * (n - 1) + "40"
            out, err = self.assert_found_text(local + enc + domain)
            self.assert_no_leak(out, err, local, domain)

    def test_html_amp_5_to_7_layers(self):
        for n in (5, 6, 7):
            local, domain, _ = make_address()
            enc = "&" + "amp;" * (n - 1) + "#64;"
            out, err = self.assert_found_text(local + enc + domain)
            self.assert_no_leak(out, err, local, domain)

    def test_decode_limit_fails_closed(self):
        local, domain, _ = make_address()
        enc = "%" + "25" * (privacy_scan.DECODE_LIMIT + 5) + "40"
        self.write("a.txt", local + enc + domain + "\n")
        code, out, err = run_scan(self.root)
        self.assertEqual(code, 2)
        self.assertIn("符号化", err)
        self.assert_no_leak(out, err, local, domain)

    def test_upper_u_four_digits(self):
        local, domain, _ = make_address()
        self.assert_found_text(local + "\\" + "U0040" + domain)

    def test_upper_u_eight_digits(self):
        local, domain, _ = make_address()
        self.assert_found_text(local + "\\" + "U00000040" + domain)

    def test_uppercase_named_entities(self):
        local, domain, _ = make_address()
        self.assert_found_text(local + "&" + "COMMAT;" + domain.replace(".", "&" + "PERIOD;"))

    def test_brackets_in_local_part(self):
        local, domain, _ = make_address()
        self.assert_found_text(local[:3] + "[" + local[3:] + "]" + AT + domain)

    def test_quoted_local_part(self):
        local, domain, _ = make_address()
        self.assert_found_text('"' + local + " x" + '"' + AT + domain)

    def test_bracket_before_allowed_local_is_found(self):
        self.assert_found_text(ALLOWED_LOCAL + "]" + AT + "x" + ALLOWED_DOMAIN)

    def test_delimited_allowed_still_allowed(self):
        for text in ("<" + ALLOWED + ">", "(" + ALLOWED + ")", '"' + ALLOWED + '"',
                     "[" + ALLOWED + "]"):
            self.write("a.txt", text + "\n")
            code, out, err = run_scan(self.root)
            self.assertEqual(code, 0, text + out + err)

    def test_long_whitespace_line_is_linear(self):
        for line in (" " * 80000 + "x", " " * 80000 + AT, "a" + AT + "." * 80000,
                     "[" + " " * 80000 + "x", AT.join([" " * 20000] * 4)):
            start = time.monotonic()
            privacy_scan.find_in_bytes(line.encode())
            self.assertLess(time.monotonic() - start, 1.0, repr(line[:10]))



class SentenceEndTest(TmpDirCase):
    """差し戻し 3 回目の指摘 1：アドレスの直後に句点・ピリオドと数字が続く形。"""

    def sentences(self, addr):
        return [
            "連絡は" + addr + "\u3002" + "3日以内に",
            "連絡先\uff1a" + addr + "\u3002" + "2026年から",
            addr + "\uff0e" + "\uff13" + "件",
            "Email " + addr + ". 2 people replied",
            addr + " . 3",
            addr + ".3",
        ]

    def test_six_sentences_detected(self):
        for i in range(6):
            local, domain, addr = make_address()
            text = self.sentences(addr)[i]
            self.write("a.txt", "first\n" + text + "\n")
            code, out, err = run_scan(self.root)
            self.assertEqual(code, 1, i)
            self.assertIn("行=2", out)
            self.assert_no_leak(out, err, local, domain)

    def test_allowed_followed_by_kuten_digit_is_allowed(self):
        for text in ["連絡は" + ALLOWED + "\u3002" + "3日以内に",
                     ALLOWED + "\u3002" + "3", ALLOWED + ". 2 people", ALLOWED + ".3"]:
            self.write("a.txt", text + "\n")
            code, out, err = run_scan(self.root)
            self.assertEqual(code, 0, repr(text) + out + err)

    def test_numeric_only_domain_is_not_address(self):
        self.write("a.txt", "pkg" + AT + "1.2.3\n")
        code, out, err = run_scan(self.root)
        self.assertEqual(code, 0, out + err)

    def test_backslash_runs_are_linear(self):
        for n in (80000, 160000):
            for line in ("\\" * n + "x", "\\" * n + AT + "x", ("\\" * 100 + AT) * (n // 100)):
                start = time.monotonic()
                privacy_scan.find_in_bytes(line.encode())
                self.assertLess(time.monotonic() - start, 1.0, (n, line[-3:]))

    def test_backslash_at_still_detected(self):
        local, domain, _ = make_address()
        self.write("a.txt", local + "\\" * 5 + AT + domain + "\n")
        code, out, err = run_scan(self.root)
        self.assertEqual(code, 1)


if __name__ == "__main__":
    unittest.main()
