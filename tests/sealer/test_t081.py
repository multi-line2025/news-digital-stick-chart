"""T-081 のテスト：T-078・T-079 の監査で残った軽微な点の手直し。

1. seal_order2.commit_record は、ディスクのバイト列を filter・attributes を通さずに index に入れ（stage_raw）、コミットの
   あとに、コミットした blob のバイト列がディスクと同じことを確かめる（check_committed_bytes。違えば「push しない」）。
   filter.clean で中身を変える仮のリポジトリで確かめる（TestRawStaging）。
2. --commit-written は、コミットの前に記録と中身を照らす（check_written。TestCommitWrittenChecks）。
4. 変異で落ちるテスト：privacy_scan を sys.path の import に戻す形（TestPrivacyScanSysModules）、commit_written の kind の
   確かめと「変更が記録・中身・.ots だけ」の確かめを外す形（TestCommitWrittenRefusals）。
5. 手順書の `"$var:..."` の形（zsh では `:r`・`:s` などの修飾子として読まれる）を `"${var}:..."` に直したこと。直した2つの
   塊を、bash と zsh の両方で流す（TestDocShellVars）。

実行（プロジェクトのルートで）:
    PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest discover -s tests/sealer -v

書くのは、仮のプロジェクト（test_t078.Synth）と一時のフォルダの中だけ。本物の sealed/・data/ には書かない。ネットワークと
LACIE SHARE には触れない。
"""

import contextlib
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import types
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import test_ledger as tl  # noqa: E402
import test_t078 as t78  # noqa: E402
import test_writers as tw  # noqa: E402

ledger = tl.ledger
import seal_order2  # noqa: E402
import seal_records  # noqa: E402

O2 = ledger.ORDER2_KIND
DOC_DIR = os.path.join(tl.PROJECT, "docs", "verify")
DOC_NAMES = ("periods-seal.md", "x-post.md")
SEAL_DOC = os.path.join(tl.PROJECT, "docs", "verify", "periods-seal.md")
WHO = "%s <%s>" % (seal_order2.AUTHOR_NAME, seal_order2.AUTHOR_EMAIL)


def committed_files(case, commit="HEAD"):
    return set(case.git("show", "--name-only", "--format=", commit).decode().split())


def make_lock(project):
    with open(os.path.join(project, ".git", "index.lock"), "w") as f:
        f.write("")


# ---------------------------------------------------------------- 1. filter・attributes を効かせない add と、コミットのあとのバイト列の確かめ

class TestRawStaging(t78.Synth):
    """軽-1：ローカルの設定の filter.<名前>.clean と .git/info/attributes・core.attributesFile は、commit_env（global と system
    を読まない）でも効く。書いた直後（コミットの前）にそれを置いても、コミットした blob はディスクのバイト列と同じになる。"""

    def set_filter(self, project):
        """中身の末尾に1行足す clean の filter を、sealed/ のすべてのファイルにかける（ローカルの設定と、二つの attributes）。"""
        git = lambda *a: subprocess.run(["git", "-C", project] + list(a), check=True, capture_output=True)  # noqa: E731
        git("config", "filter.t081.clean", "cat; echo tampered-by-clean-filter")
        git("config", "filter.t081.smudge", "cat")
        attrs = os.path.join(project, ".git", "info", "attributes")
        os.makedirs(os.path.dirname(attrs), exist_ok=True)
        with open(attrs, "w") as f:
            f.write("sealed/** filter=t081\n")
        other = os.path.join(self.tmp, "attributes")
        with open(other, "w") as f:
            f.write("sealed/** filter=t081\n")
        git("config", "core.attributesFile", other)

    def unset_filter(self):
        with open(os.path.join(self.root, ".git", "info", "attributes"), "w") as f:
            f.write("")
        for k in ("filter.t081.clean", "filter.t081.smudge", "core.attributesFile"):
            self.git("config", "--unset", k)

    def test_filter_does_not_change_committed_bytes(self):
        with t78.write_with(self.set_filter):
            rec, rel, ots, _doc = self.write()
        paths = {"sealed/ledger.jsonl", rel, os.path.relpath(ots, self.root)}
        self.assertEqual(committed_files(self), paths)
        for p in paths:
            with open(os.path.join(self.root, p), "rb") as f:
                disk = f.read()
            self.assertEqual(self.git("cat-file", "blob", "HEAD:" + p), disk, p)
            self.assertNotIn(b"tampered-by-clean-filter", disk)
        # filter の効く git add なら、中身が変わっていたこと（このテストの仕掛けが効いていること）
        self.assertIn(b"tampered-by-clean-filter", self.filtered_blob(rel))
        self.unset_filter()
        self.verify_zero("all")

    def filtered_blob(self, rel):
        """filter を効かせた git hash-object（git add と同じ変換）で作った blob の中身。"""
        sha = self.git("hash-object", "-w", "--", rel).decode().strip()
        return self.git("cat-file", "blob", sha)

    def test_filtered_add_is_caught_after_commit(self):
        """index に入れる段を filter の効く git add に戻すと、コミットのあとのバイト列の確かめで止まり、push しないと知らせる。"""
        def plain_add(root, paths):
            seal_order2._cgit(root, "add", "--", *paths)
        before = len(self.records())
        with mock.patch.object(seal_order2, "stage_raw", plain_add), t78.write_with(self.set_filter), \
                self.assertRaisesRegex(seal_order2.Order2Written, "バイト列が、ディスクのファイルと違う.*push しない"):
            self.write()
        self.assertEqual(len(self.records()), before + 1)

    def test_stage_raw_refuses_link(self):
        os.symlink(os.path.join(self.root, "sealed", "ledger.jsonl"), os.path.join(self.root, "link.txt"))
        with self.assertRaisesRegex(ledger.LedgerError, "普通のファイルでない"):
            seal_order2.stage_raw(self.root, ["link.txt"])


# ---------------------------------------------------------------- 2. --commit-written の前の照合

class CommitWrittenCase(t78.Synth):
    def written_not_committed(self, runner=None):
        """書いたあとでコミットが失敗した状態を作る（index.lock）。そのあと lock を外へ移す（消さない）。返り値: 最後の記録。"""
        before = self.head()
        if runner is None:
            with t78.write_with(make_lock), \
                    self.assertRaisesRegex(seal_order2.Order2Written, "作業ツリーに書いたが、コミットしていない"):
                self.write()
        else:
            real = seal_records.write_doc_record

            def wrapped(project, *a, **k):
                try:
                    return real(project, *a, **k)
                finally:
                    make_lock(project)
            with mock.patch.object(seal_records, "write_doc_record", wrapped), \
                    mock.patch.object(ledger, "PROJECT_ROOT", self.root), \
                    self.assertRaisesRegex(seal_order2.Order2Written, r"(?s)\.ots を作れず.*コミットもしていない"):
                seal_order2.seal({"trial": self.store, "official": None}, self.bundle_path(), self.tick(), "ots",
                                 runner=runner)
        os.rename(os.path.join(self.root, ".git", "index.lock"), os.path.join(self.tmp, "index.lock.%d" % self.nb))
        self.assertEqual(self.head(), before)
        self.before = before
        return self.records()[-1]

    def commit_written_main(self):
        err = io.StringIO()
        with mock.patch.object(ledger, "PROJECT_ROOT", self.root), contextlib.redirect_stdout(io.StringIO()), \
                contextlib.redirect_stderr(err):
            code = seal_order2.main(["--commit-written"])
        return code, err.getvalue()

    def refused(self, text):
        with self.assertRaisesRegex(ledger.LedgerError, text):
            seal_order2.commit_written(self.root)
        code, err = self.commit_written_main()
        self.assertEqual(code, 1)
        self.assertIn("失敗（コミットしていない）", err)
        self.assertEqual(self.head(), self.before)


class TestCommitWrittenChecks(CommitWrittenCase):
    """軽-2：記録と中身が合わなければ、--commit-written はコミットしない。元に戻せばコミットでき、verify が 0。"""

    def test_content_changed(self):
        rec = self.written_not_committed()
        path = os.path.join(self.root, rec["targets"][0]["path"])
        with open(path, "rb") as f:
            orig = f.read()
        doc = json.loads(orig)
        doc["status"] = "stopped" if doc["status"] != "stopped" else "decided"
        with open(path, "wb") as f:
            f.write(ledger.canonical_line(doc) + b"\n")
        self.refused("ファイルが記録と一致しない")
        with open(path, "wb") as f:
            f.write(orig)
        code, err = self.commit_written_main()
        self.assertEqual(code, 0, err)
        self.assertEqual(self.git("log", "-1", "--format=%an <%ae>|%cn <%ce>").decode().strip(), WHO + "|" + WHO)
        self.verify_zero("all")

    def test_last_line_changed(self):
        """最後の行の note を書き換える（鎖の形は保つ）。.ots の対象（先頭 N 行の sha256）と合わないので止まる。"""
        rec = self.written_not_committed()
        lines = ledger.split_lines(self.ledger_bytes())
        forged = ledger.canonical_line(dict(rec, note=rec["note"] + "（書き換え）"))
        with open(self.ledger, "wb") as f:
            f.write(b"".join(x + b"\n" for x in lines[:-1]) + forged + b"\n")
        ledger.verify_chain(self.ledger_bytes())             # 鎖の形には通る
        self.refused("")

    def test_earlier_record_uncommitted(self):
        """HEAD の記録が、今の記録から最後の1行を除いたものでない（HEAD の ledger を1行戻したコミットを作る）と止まる。"""
        rec = self.written_not_committed()
        lines = ledger.split_lines(self.ledger_bytes())
        shorter = b"".join(x + b"\n" for x in lines[:-2])
        blob = subprocess.run(["git", "-C", self.root, "hash-object", "-w", "--stdin"], input=shorter, check=True,
                              capture_output=True).stdout.decode().strip()
        self.git("update-index", "--cacheinfo", "100644,%s,sealed/ledger.jsonl" % blob)
        self.git("commit", "-q", "-m", "HEAD の記録を1行戻す（テスト）")
        self.git("reset", "-q")                                 # index を HEAD に（作業ツリーはそのまま）
        self.before = self.head()
        with self.assertRaisesRegex(ledger.LedgerError, "最後の seq %d を除いたもの" % rec["seq"]):
            seal_order2.check_written(self.root, t78.verify.Repo(self.root), self.ledger_bytes(), rec)

    def test_without_ots(self):
        """.ots が作れず、コミットもできなかった形。.ots の無い最後の seq を除いて照らし、記録と中身だけをコミットする。"""
        rec = self.written_not_committed(runner=t78.FailingOts())
        self.assertFalse(os.path.exists(os.path.join(self.root, "sealed", ledger.ots_name(rec["seq"]))))
        code, err = self.commit_written_main()
        self.assertEqual(code, 0, err)
        self.assertEqual(committed_files(self), {"sealed/ledger.jsonl", rec["targets"][0]["path"]})
        self.assertEqual(self.git("status", "--porcelain"), b"")


class TestCommitWrittenRefusals(CommitWrittenCase):
    """軽-4：commit_written の kind の確かめと、「作業ツリーの変更が、その記録・中身・.ots だけ」の確かめ。どちらも、外すと
    ここが落ちる（止まる理由の文まで見る）。"""

    def test_last_record_not_order2(self):
        before = self.head()
        rel = "sealed/t081-other.json"
        content = b'{"kind":"x"}\n'
        with open(os.path.join(self.root, rel), "wb") as f:
            f.write(content)
        ledger.append_record(self.ledger, ledger.ORDER1B_KIND,
                             [{"path": rel, "role": "output", "sha256": ledger.sha256_hex(content)}],
                             "作り物（テスト）", self.tick())
        self.before = before
        self.refused("最後の記録が stats-order2 でない")

    def test_extra_untracked_file(self):
        self.written_not_committed()
        with open(os.path.join(self.root, "extra.txt"), "w") as f:
            f.write("x")
        self.refused("だけでない")

    def test_extra_tracked_change(self):
        self.written_not_committed()
        with open(os.path.join(self.root, t78.TRIAL), "a") as f:
            f.write("\n")
        self.refused("だけでない")


# ---------------------------------------------------------------- 4. privacy_scan を sys.modules・sys.path から選ばない

class TestPrivacyScanSysModules(unittest.TestCase):
    """軽-4：sys.modules に同じ名前の偽物が入っていても、sys.path の先頭に偽物があっても、load_privacy_scan は
    src/collector/privacy_scan.py を読む。sys.path の import（`import privacy_scan`）に戻すと、1つ目で落ちる。"""

    REAL = os.path.realpath(os.path.join(seal_records.COLLECTOR, "privacy_scan.py"))

    def fake(self):
        mod = types.ModuleType("privacy_scan")
        mod.ALLOWED_ADDRESSES = frozenset({t78.other_address("someone")})
        mod.find_in_bytes = lambda data: {}
        mod.__file__ = os.path.join(tempfile.gettempdir(), "privacy_scan.py")
        return mod

    def check_real(self, mod, fake):
        self.assertIsNot(mod, fake)
        self.assertEqual(os.path.realpath(mod.__file__), self.REAL)
        self.assertEqual(set(mod.ALLOWED_ADDRESSES), {seal_order2.AUTHOR_EMAIL})
        self.assertTrue(mod.find_in_bytes(t78.other_address("taro").encode()))

    def test_fake_in_sys_modules(self):
        fake = self.fake()
        with mock.patch.dict(sys.modules, {"privacy_scan": fake}), mock.patch.object(seal_records, "_PRIVACY_SCAN", []):
            self.check_real(seal_records.load_privacy_scan(), fake)
            seal_order2.author_config()

    def test_fake_on_path_without_cached_module(self):
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "privacy_scan.py"), "w") as f:
                f.write("ALLOWED_ADDRESSES = frozenset({%r})\ndef find_in_bytes(data):\n    return {}\n"
                        % t78.other_address("someone"))
            with mock.patch.dict(sys.modules), mock.patch.object(sys, "path", [d] + sys.path), \
                    mock.patch.object(seal_records, "_PRIVACY_SCAN", []):
                sys.modules.pop("privacy_scan", None)
                self.check_real(seal_records.load_privacy_scan(), None)


# ---------------------------------------------------------------- 5. 手順書のシェルの変数（zsh と bash）

def doc_text():
    with open(SEAL_DOC, encoding="utf-8") as f:
        return f.read()


def shells():
    return [s for s in ("/bin/bash", "/bin/zsh") if os.path.isfile(s)]


def run_sh(shell, script, cwd, env):
    return subprocess.run([shell, "-c", script], cwd=cwd, env=env, capture_output=True)


class TestDocShellVars(unittest.TestCase):
    """T-079 軽-4：zsh では `"$c:src/..."` の `:s` や `"$name:refs/..."` の `:r` が修飾子として読まれる。手順書には
    `"${c}:..."` の形だけを書き、直した2つの塊が bash と zsh の両方で同じ結果になることを確かめる。"""

    BARE = re.compile(r"\$[A-Za-z_][A-Za-z0-9_]*:")

    def test_no_bare_var_before_colon(self):
        for name in DOC_NAMES:
            with open(os.path.join(DOC_DIR, name), encoding="utf-8") as f:
                for i, line in enumerate(f, 1):
                    self.assertIsNone(self.BARE.search(line), "%s %d 行目: %s" % (name, i, line.strip()))

    def setUp(self):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        self.tmp = os.path.realpath(td.name)
        self.repo = os.path.join(self.tmp, "repo")
        self.env = dict(ledger.fixed_git_env(), TMPDIR=self.tmp, GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1")
        os.makedirs(os.path.join(self.repo, "src", "stats"))
        self.git("init", "-q", "-b", "main")
        self.versions = {}
        for body in (b"v1\n", b"v2\n"):
            with open(os.path.join(self.repo, "src", "stats", "counting.py"), "wb") as f:
                f.write(body)
            self.git("add", "--", "src/stats/counting.py")
            self.git("commit", "-q", "-m", "x")
            self.versions[self.git("rev-parse", "HEAD").decode().strip()] = ledger.sha256_hex(body)
        self.git("branch", "side.v1")

    def git(self, *a, cwd=None):
        return subprocess.run(["git", "-C", cwd or self.repo] + list(tl.AUTHOR) + list(a), check=True,
                              capture_output=True, env=self.env).stdout

    def test_code_version_loop(self):
        line = [x.strip() for x in doc_text().splitlines()
                if x.strip().startswith("for c in $(git rev-list HEAD -- src/stats/counting.py)")]
        self.assertEqual(len(line), 1)
        self.assertIn('"${c}:src/stats/counting.py"', line[0])
        want = {c: s for c, s in self.versions.items()}
        for sh in shells():
            r = run_sh(sh, line[0], self.repo, self.env)
            self.assertEqual(r.returncode, 0, (sh, r.stderr))
            got = {}
            for row in r.stdout.decode().splitlines():
                parts = row.split()
                got[parts[0]] = parts[1]
            self.assertEqual(got, want, sh)

    def bundle_block(self):
        text = doc_text()
        at = text.index("### bundle を公開する前の検査")
        body = text[text.index("```sh\n", at) + len("```sh\n"):]
        body = body[:body.index("```")]
        lines = body.splitlines()
        self.assertTrue(lines[0].startswith("B=<bundle>; "))
        self.assertIn('"${name}:refs/bundle-heads/$n"', body)
        # privacy_scan の行は、収集係の検査器を流す行なので、ここでは除く（シェルの変数の展開だけを確かめる）
        return [x for x in lines if "privacy_scan.py" not in x]

    def test_bundle_fetch_block(self):
        bundle = os.path.join(self.tmp, "t.bundle")
        self.git("bundle", "create", "-q", bundle, "--all")
        heads = self.git("bundle", "list-heads", bundle).decode().splitlines()
        lines = self.bundle_block()
        for sh in shells():
            script = "\n".join(["set -e", lines[0].replace("<bundle>", bundle, 1)] + lines[1:] + ['echo "W=$W"'])
            r = run_sh(sh, script, self.tmp, self.env)
            self.assertEqual(r.returncode, 0, (sh, r.stderr))
            w = [x for x in r.stdout.decode().splitlines() if x.startswith("W=")][-1][2:]
            self.assertTrue(os.path.realpath(w).startswith(self.tmp + os.sep), w)
            refs = self.git("for-each-ref", "--format=%(refname) %(objectname)", "refs/bundle-heads/",
                            cwd=os.path.join(w, "c")).decode().splitlines()
            # list-heads の各行が、順に refs/bundle-heads/1, 2, ... に取り込まれる（zsh の `$name:r` の形では、名前が崩れる）
            want = sorted("refs/bundle-heads/%d %s" % (i, h.split()[0]) for i, h in enumerate(heads, 1))
            self.assertEqual(sorted(refs), want, sh)
            self.assertIn("src/stats/counting.py", r.stdout.decode())


if __name__ == "__main__":
    unittest.main()
