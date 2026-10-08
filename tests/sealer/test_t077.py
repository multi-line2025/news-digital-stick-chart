"""T-077 のテスト：tests/sealer が、本物の封印の記録の今の状態（HEAD）に頼らないことを守らせる。

実行（プロジェクトのルートで）:
    PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest discover -s tests/sealer -v

規則（tests/sealer/fixed_records.py の冒頭と、docs/verify/periods-seal.md 15章「テストと本物の記録」に同じ文）:
  1. テストは、HEAD の本物の sealed/ledger.jsonl・sealed/・data/manifest/ の今の状態を前提にしない。
  2. 本物の記録を使うテストは、固定したコミット（テストの中の定数。40 桁の sha）の版を git から取り出して使う
     （fixed_records.checkout・fixed_records.show）。そうでなければ、合成の鎖を使う。
  3. HEAD の本物の記録をそのまま読んでよいのは、「本物の記録で verify が 0 になる」ことを確かめるテストだけ
     （下の HEAD_READERS）。記録が増えても壊れない書き方にする。

TestRuleScan は、tests/sealer の .py（fixed_records.py を除く）を ast で読み、本物のプロジェクトの記録に届きうる
箇所を数える。数えた箇所が HEAD_READERS の一覧と件数まで同じでなければ落ちる（一覧に無い箇所が1つ増えても
落ちる。一覧にあって無くなったものも落ちる。一覧は手で直す）。数える箇所は scan_sites の説明のとおり。

ネットワークと LACIE SHARE は使わない。本物の sealed/・data/ には書かない。
"""

import ast
import contextlib
import io
import json
import os
import posixpath
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import fixed_records  # noqa: E402
import test_ledger as tl  # noqa: E402
import test_t073 as t73  # noqa: E402
from unittest import mock  # noqa: E402

import order2_gate  # noqa: E402
import post_text  # noqa: E402

ledger = tl.ledger
verify = tl.verify
DOC = os.path.join(tl.PROJECT, "docs", "verify", "periods-seal.md")

# ---------------------------------------------------------------- 1. 規則を守らせる検査

# HEAD の本物の記録を読んでよいテスト（ファイル名, クラス名.関数名）→ 数える箇所の件数。
# 「本物の記録で verify が 0 になる」ことを確かめるテストだけを入れる。
HEAD_READERS = {
    # 本物の作業ツリーのルートで verify all --rev auto（同じプロセス）。記録の件数・kind に頼らない
    ("test_t077.py", "TestRealHeadVerify.test_verify_all_rev_auto_is_zero"): 1,
    # 手順書（periods-seal.md）の塊を、HEAD の clone で第三者の立場で流し、すべて 0 で終わる
    ("test_verify_doc.py", "TestDocProcedureHead.make_clone"): 1,
    # 本物の作業ツリーの全記録で、recorded_at が Bitcoin の確定時刻 + 3 時間より後でない（post_text の照合。
    # verify には入っていない）。どの記録にも違反が無いことだけを見る（T-077 差し戻し1回目 中-3）
    ("test_t077.py", "TestRealHeadVerify.test_recorded_at_not_after_btc_time"): 1,
}

# 本物のプロジェクトのルートを指す名前（Name か、属性の名前）
P_NAMES = {"PROJECT", "PROJECT_ROOT"}
# os.path.join(<ルート>, ...) で読んでよい場所（記録でないもの：コード・テスト・手順書・CLAUDE.md・.venv）
SAFE_PREFIXES = ("src/", "tests/", "docs/verify/", ".venv/", "CLAUDE.md")
# 引数を取らず、ledger.PROJECT_ROOT の記録を読む関門
GATE_ATTRS = {"require_method_access", "require_threshold_access", "require_gkg_run_result", "require_order2_gate"}
GATE_MODULE_FUNCS = {("order2_gate", "gate"), ("order2_gate", "main"), ("order2_gate", "gate_with_manifests"),
                     # T-078：順番2の書く入口（root は ledger.PROJECT_ROOT に固定。引数で変えられない）
                     ("seal_order2", "seal"), ("seal_order2", "main"), ("seal_order2", "build_doc")}
# この属性を差し替える with の中では、関門は本物の記録を読まない
SAFE_PATCH_ATTRS = {"PROJECT_ROOT", "_load_for_gate"}
SAFE_WITH_FUNCS = {"gate_project"}
SUBPROCESS_FUNCS = {"subprocess.run", "subprocess.call", "subprocess.check_call", "subprocess.check_output",
                    "subprocess.Popen"}
SCRIPT_NAMES = {"VERIFY"}
MAIN_MODULES = {"verify", "post_text", "stamp", "seal_access", "seal_acquisition", "seal_bitcoin",
                "seal_candidates", "seal_gkg_result", "seal_gkg_run", "seal_method", "seal_periods", "seal_records",
                "seal_stats", "seal_triggers"}
READ_FUNCS = {"open", "io.open", "glob.glob", "os.listdir", "os.scandir", "os.path.exists", "os.path.isfile",
              "os.path.lexists", "read_ledger", "ledger.read_ledger", "tl.ledger.read_ledger"}
RECORD_REL_PREFIXES = ("sealed", "data/manifest", "data")
EXCLUDED_FILES = {"fixed_records.py"}
# fixed_records のうち、外から使ってはいけない名前（HEAD を指す値・本物のルート）。_ で始まる名前もすべて
FIXED_PRIVATE = {"head_sha", "PROJECT"}


def norm_rel(rel):
    """相対パスを正規化する（"./" と重なった "/" を取る）。".." を含むものは None（安全とみなさない）。"""
    parts = rel.replace("\\", "/").split("/")
    if ".." in parts:
        return None
    return posixpath.normpath(rel) if rel else rel


def dotted(node):
    """a.b.c の形なら "a.b.c"、そうでなければ None。"""
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
        return ".".join(reversed(parts))
    return None


def is_p(node):
    return ((isinstance(node, ast.Name) and node.id in P_NAMES)
            or (isinstance(node, ast.Attribute) and node.attr in P_NAMES))


def module_constants(tree):
    """モジュールの最上位の `名前 = "文字列"` と `名前 = os.path.join(文字列, ...)` を解決した表。"""
    consts = {}
    for st in tree.body:
        if isinstance(st, ast.Assign) and len(st.targets) == 1 and isinstance(st.targets[0], ast.Name):
            v = literal_path(st.value, consts)
            if v is not None:
                consts[st.targets[0].id] = v
    return consts


def literal_path(node, consts):
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Name) and node.id in consts:
        return consts[node.id]
    if isinstance(node, ast.Call) and dotted(node.func) == "os.path.join" and not node.keywords:
        parts = [literal_path(a, consts) for a in node.args]
        if all(p is not None for p in parts) and parts:
            return "/".join(parts)
    return None


class _Scanner(ast.NodeVisitor):
    def __init__(self, fname, consts):
        self.fname, self.consts = fname, consts
        self.stack, self.parents, self.withs = [], [], []
        self.sites = {}

    def qual(self):
        return ".".join(self.stack) if self.stack else "<module>"

    def add(self, why):
        k = (self.fname, self.qual())
        self.sites.setdefault(k, []).append(why)

    def generic_visit(self, node):
        self.parents.append(node)
        super().generic_visit(node)
        self.parents.pop()

    def visit_ClassDef(self, node):
        self.stack.append(node.name)
        self.generic_visit(node)
        self.stack.pop()

    def visit_FunctionDef(self, node):
        self.stack.append(node.name)
        self.generic_visit(node)
        self.stack.pop()

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_With(self, node):
        safe = False
        for item in node.items:
            e = item.context_expr
            if isinstance(e, ast.Call):
                name = dotted(e.func) or ""
                if name.split(".")[-1] in SAFE_WITH_FUNCS:
                    safe = True
                if name.endswith("patch.object") and len(e.args) >= 2 and isinstance(e.args[1], ast.Constant) \
                        and e.args[1].value in SAFE_PATCH_ATTRS:
                    safe = True
        self.withs.append(safe)
        self.generic_visit(node)
        self.withs.pop()

    def nearest_call(self, start_index):
        """parents[start_index] から上へ、最初の Call（文に当たれば None）。(Call, その位置)。"""
        for i in range(start_index, -1, -1):
            p = self.parents[i]
            if isinstance(p, ast.stmt):
                return None, i
            if isinstance(p, ast.Call):
                return p, i
        return None, -1

    def visit_Name(self, node):
        self.check_p(node)

    def visit_ImportFrom(self, node):
        if node.module == "fixed_records":
            for a in node.names:
                if a.name == "*" or a.name.startswith("_") or a.name in FIXED_PRIVATE:
                    self.add("fixed_records から %s を取り込む（%s 行）" % (a.name, node.lineno))
        self.generic_visit(node)

    def visit_Attribute(self, node):
        if isinstance(node.value, ast.Name) and node.value.id == "fixed_records" and \
                (node.attr.startswith("_") or node.attr in FIXED_PRIVATE):
            self.add("fixed_records.%s を外から使う（%s 行）" % (node.attr, node.lineno))
            return
        if is_p(node):
            self.check_p(node)
        else:
            self.generic_visit(node)

    def check_p(self, node):
        if not is_p(node) or not isinstance(node.ctx, ast.Load):
            return
        call, i = self.nearest_call(len(self.parents) - 1)
        if call is None:
            st = self.parents[i] if i >= 0 else None
            if (not self.stack and isinstance(st, ast.Assign) and st.value is node
                    and all(isinstance(t, ast.Name) and t.id in P_NAMES for t in st.targets)):
                return                                    # モジュールの最上位で、名前を定めるだけ
            self.add("ルートの名前をそのまま使う（%s 行）" % node.lineno)
            return
        name = dotted(call.func)
        if node in call.args[:1]:
            if name == "os.path.join":
                rest = [literal_path(a, self.consts) for a in call.args[1:]]
                if rest and all(r is not None for r in rest) and not call.keywords:
                    rel = norm_rel("/".join(rest))
                    if rel is not None and any(rel == p.rstrip("/") or rel.startswith(p) for p in SAFE_PREFIXES):
                        return
            if name in ("os.path.realpath", "os.path.abspath") and len(call.args) == 1:
                outer, _j = self.nearest_call(i - 1)
                if outer is None or (isinstance(outer.func, ast.Attribute)
                                     and outer.func.attr.startswith("assert")):
                    return                                # パスを比べるだけ（読まない）
        self.add("ルートを %s に渡す（%s 行）" % (name or "式", node.lineno))

    def visit_Call(self, node):
        name = dotted(node.func) or ""
        last = name.split(".")[-1]
        mod = name.split(".")[-2] if "." in name else ""
        strs = [a.value for a in node.args if isinstance(a, ast.Constant) and isinstance(a.value, str)]
        # 関門（引数なしで ledger.PROJECT_ROOT を読む）
        if last in GATE_ATTRS or (mod, last) in GATE_MODULE_FUNCS:
            argstrs = [e.value for a in node.args if isinstance(a, (ast.List, ast.Tuple)) for e in a.elts
                       if isinstance(e, ast.Constant)]
            if not any(self.withs) and "--root" not in argstrs:
                self.add("関門 %s を、ルートを差し替えずに呼ぶ（%s 行）" % (name, node.lineno))
        # 今のフォルダからの相対のパスで記録を読む（テストはプロジェクトのルートで流す）
        if name in READ_FUNCS and node.args:
            rel = literal_path(node.args[0], self.consts)
            n = norm_rel(rel) if rel is not None else None
            if rel is not None and (n is None or n.split("/")[0] in ("sealed", "data")):
                self.add("相対パス %s を読む（%s 行）" % (rel, node.lineno))
        # このファイルの場所から .. でプロジェクトへ上る
        if name == "os.path.join" and node.args and any(s == ".." or s.startswith("../") for s in strs):
            first = node.args[0]
            if (isinstance(first, ast.Name) and first.id == "HERE") or any(
                    isinstance(x, ast.Name) and x.id == "__file__" for x in ast.walk(first)):
                self.add("os.path.join の ..（%s 行）" % node.lineno)
        # src のスクリプト（.py）を、--root を渡さずに subprocess で動かす。スクリプトの既定のルートは、今の
        # フォルダ（verify.py）か、スクリプトの場所（post_text.py）。相対パス（src/…）を cwd の中で動かすものは、
        # cwd の写しのスクリプトなので数えない
        if name in SUBPROCESS_FUNCS and node.args and isinstance(node.args[0], (ast.List, ast.Tuple)):
            elts = node.args[0].elts
            is_git = bool(elts) and isinstance(elts[0], ast.Constant) and elts[0].value == "git"
            has_root = any(isinstance(e, ast.Constant) and e.value == "--root" for e in elts)
            has_cwd = any(k.arg == "cwd" for k in node.keywords)
            absolute, relative = False, False
            for e in elts:
                v = literal_path(e, self.consts)
                if v is not None and v.endswith(".py"):
                    relative = True
                elif (isinstance(e, ast.Call) and dotted(e.func) == "os.path.join" and e.args
                      and isinstance(e.args[-1], ast.Constant) and str(e.args[-1].value).endswith(".py")) or \
                        (isinstance(e, (ast.Name, ast.Attribute)) and (getattr(e, "id", None) or e.attr) in SCRIPT_NAMES):
                    absolute = True
            if not is_git and not has_root and (absolute or (relative and not has_cwd)):
                self.add("src のスクリプトを --root を渡さずに動かす（%s 行）" % node.lineno)
        # 同じプロセスの main（既定のルートは今のフォルダかスクリプトの場所）を、--root を渡さずに呼ぶ
        if last == "main" and mod in MAIN_MODULES and not any(self.withs):
            lit = node.args[0] if node.args else ast.List(elts=[])
            if isinstance(lit, (ast.List, ast.Tuple)) and not any(
                    isinstance(e, ast.Constant) and e.value == "--root" for e in lit.elts):
                self.add("%s を --root を渡さずに呼ぶ（%s 行）" % (name, node.lineno))
        self.generic_visit(node)


def scan_file(path):
    with open(path, encoding="utf-8") as f:
        tree = ast.parse(f.read(), path)
    s = _Scanner(os.path.basename(path), module_constants(tree))
    s.visit(tree)
    return s.sites


def scan_sites(folder):
    """{(ファイル名, 関数の名前): [箇所の説明]}。数えるもの：
      - 本物のルートの名前（PROJECT・PROJECT_ROOT。属性も）を、os.path.join(ルート, <src/・tests/・docs/verify/・
        .venv/・CLAUDE.md の下の決まった文字列>) と、assert で比べるだけの os.path.realpath・abspath 以外で使う箇所
        （git -C ルート、git clone ルート、関数にルートを渡す、別の名前に入れる、など）
      - 関門（require_method_access・require_threshold_access・require_gkg_run_result・require_order2_gate・
        order2_gate.gate・order2_gate.main・order2_gate.gate_with_manifests、T-078 の seal_order2.seal・main・build_doc）を、
        PROJECT_ROOT・_load_for_gate を差し替える with の外で呼ぶ箇所
      - 相対パスの sealed/・data/ を読む箇所、HERE・__file__ から os.path.join の .. で上る箇所
      - src のスクリプト（.py）を、--root を渡さずに subprocess で動かす箇所（相対パスのスクリプトを cwd を
        渡して動かすものは除く）。同じプロセスの main（verify・post_text・seal_* など）を、--root の無い引数の
        一覧で呼ぶ箇所（引数が一覧の字面でないときは数えない。限界）
    fixed_records.py（固定したコミットを取り出す入口）は数えない。"""
    out = {}
    for name in sorted(os.listdir(folder)):
        if name.endswith(".py") and name not in EXCLUDED_FILES:
            out.update(scan_file(os.path.join(folder, name)))
    return out


class TestRuleScan(unittest.TestCase):
    def test_only_allowed_tests_read_head(self):
        sites = scan_sites(HERE)
        got = {k: len(v) for k, v in sites.items()}
        extra = {k: sites[k] for k in got if got[k] != HEAD_READERS.get(k)}
        missing = {k: n for k, n in HEAD_READERS.items() if got.get(k) != n}
        self.assertEqual((extra, missing), ({}, {}),
                         "HEAD の本物の記録に届きうる箇所が、許可した一覧（HEAD_READERS）と違う")

    def write(self, d, name, text):
        with open(os.path.join(d, name), "w", encoding="utf-8") as f:
            f.write(text)

    def test_detects_added_head_reader(self):
        """わざと HEAD の本物の記録を読むテストを足すと、一覧に無い箇所として数える（形ごと）。"""
        bad = {
            "join の sealed": 'def test_x():\n    open(os.path.join(tl.PROJECT, "sealed", "ledger.jsonl"))\n',
            "data/manifest": 'def test_x():\n    open(os.path.join(PROJECT, "data", "manifest", "a.jsonl"))\n',
            "git show HEAD": 'def test_x():\n    subprocess.run(["git", "-C", PROJECT, "show", "HEAD:sealed/ledger.jsonl"])\n',
            "git clone": 'def test_x():\n    subprocess.run(["git", "clone", "-q", tl.PROJECT, "c"])\n',
            "verify にルート": 'def test_x():\n    tl.run_verify_inproc(tl.PROJECT, "all")\n',
            "別の名前": 'def test_x():\n    root = tl.PROJECT\n',
            "PROJECT_ROOT": 'def test_x():\n    ledger.read_ledger(os.path.join(ledger.PROJECT_ROOT, "sealed", "x"))\n',
            "関門": 'def test_x():\n    ledger.require_method_access()\n',
            "order2_gate": 'def test_x():\n    order2_gate.gate()\n',
            "seal_order2（T-078）": 'def test_x():\n    seal_order2.seal({}, "b", now, "ots")\n',
            "相対パス": 'def test_x():\n    ledger.read_ledger("sealed/ledger.jsonl")\n',
            "post_text.main": 'def test_x():\n    post_text.main([])\n',
            "cwd でも絶対パスのスクリプト": 'def test_x():\n    subprocess.run([py, os.path.join(SRC, "post_text.py")], cwd=c)\n',
            "..": 'def test_x():\n    open(os.path.join(HERE, "..", "..", "sealed", "ledger.jsonl"))\n',
            "スクリプト": 'def test_x():\n    subprocess.run([sys.executable, os.path.join(SRC, "verify.py"), "all"])\n',
            "realpath を渡す": 'def test_x():\n    f(os.path.realpath(PROJECT))\n',
            # T-077 差し戻し1回目 中-2 の3つの形
            "head_sha を渡す": 'def test_x():\n    fixed_records.checkout(d, fixed_records.head_sha())\n',
            "_head_sha を渡す": 'def test_x():\n    fixed_records.checkout(d, fixed_records._head_sha())\n',
            "head_sha を取り込む": 'def test_x():\n    from fixed_records import head_sha\n',
            "src/.. を含むパス": 'def test_x():\n    open(os.path.join(PROJECT, "src", "..", "sealed", "ledger.jsonl"))\n',
            "src/.. を1つの文字列で": 'def test_x():\n    open(os.path.join(PROJECT, "src/../sealed/ledger.jsonl"))\n',
            "./sealed": 'def test_x():\n    ledger.read_ledger("./sealed/ledger.jsonl")\n',
            "相対の ..": 'def test_x():\n    open("../sealed/ledger.jsonl")\n',
            "docs/stats": 'def test_x():\n    open(os.path.join(PROJECT, "docs", "stats", "periods.md"))\n',
        }
        ok = {
            "src": 'def test_x():\n    open(os.path.join(tl.PROJECT, "src", "sealer", "ledger.py"))\n',
            "手順書": 'DOC_REL = os.path.join("docs", "verify", "x.md")\ndef test_x():\n    open(os.path.join(PROJECT, DOC_REL))\n',
            "realpath を比べる": 'def test_x(self):\n    self.assertEqual(os.path.realpath(a), os.path.realpath(PROJECT))\n',
            "差し替えた関門": 'def test_x():\n    with mock.patch.object(ledger, "PROJECT_ROOT", c):\n'
                              '        ledger.require_method_access()\n',
            "--root の付いたスクリプト": 'def test_x():\n    subprocess.run([sys.executable, VERIFY, "--root", r])\n',
            "名前を定める": 'PROJECT = tl.PROJECT\n',
            "./src": 'def test_x():\n    open(os.path.join(PROJECT, "./src/sealer/ledger.py"))\n',
            "固定の入口": 'def test_x():\n    fixed_records.show("sealed/ledger.jsonl", fixed_records.RESULT_COMMIT)\n',
            "cwd の写しのスクリプト": 'def test_x():\n    subprocess.run([py, "-B", "src/sealer/post_text.py"], cwd=c)\n',
            "git の中の .py": 'def test_x():\n    subprocess.run(["git", "-C", wt, "add", "src/stats/counting.py"])\n',
            "仮の場所の ..": 'def test_x():\n    os.path.join(self.sealed, "..", "x")\n',
            "--root の付いた main": 'def test_x():\n    post_text.main(["check-posts", p, "--root", d])\n',
        }
        with tempfile.TemporaryDirectory() as d:
            for name, text in bad.items():
                with self.subTest(bad=name):
                    self.write(d, "test_bad.py", text)
                    self.assertEqual(len(scan_file(os.path.join(d, "test_bad.py")).get(("test_bad.py", "test_x"), [])),
                                     1, name)
            for name, text in ok.items():
                with self.subTest(ok=name):
                    self.write(d, "test_ok.py", text)
                    self.assertEqual(scan_file(os.path.join(d, "test_ok.py")), {}, name)

    def test_scan_fails_when_a_reader_is_added(self):
        """tests/sealer の写しに、HEAD の本物の記録を読むテストを1つ足すと、一覧との照合が落ちる。"""
        with tempfile.TemporaryDirectory() as d:
            for name in os.listdir(HERE):
                if name.endswith(".py"):
                    with open(os.path.join(HERE, name), "rb") as f, open(os.path.join(d, name), "wb") as g:
                        g.write(f.read())
            sites = {k: len(v) for k, v in scan_sites(d).items()}
            self.assertEqual(sites, HEAD_READERS)
            with open(os.path.join(d, "test_ledger.py"), "a", encoding="utf-8") as f:
                f.write('\n\nclass TestAddedHeadReader(unittest.TestCase):\n'
                        '    def test_real_count(self):\n'
                        '        data = ledger.read_ledger(os.path.join(PROJECT, "sealed", "ledger.jsonl"))\n'
                        '        self.assertEqual(len(ledger.split_lines(data)), 9)\n')
            sites = {k: len(v) for k, v in scan_sites(d).items()}
            self.assertNotEqual(sites, HEAD_READERS)
            self.assertEqual(sites.get(("test_ledger.py", "TestAddedHeadReader.test_real_count")), 1)

    def test_pinned_commit_constant(self):
        """固定したコミットは 40 桁の sha。HEAD や枝の名前は、取り出す入口が拒む。"""
        self.assertRegex(fixed_records.PINNED_COMMIT, r"\A[0-9a-f]{40}\Z")
        for bad in ("HEAD", "main", "5ce3943", "HEAD~1", None):
            with self.assertRaises(ValueError):
                fixed_records.show("sealed/ledger.jsonl", bad)
            with tempfile.TemporaryDirectory() as d:
                with self.assertRaises(ValueError):
                    fixed_records.checkout(os.path.join(d, "c"), bad)

    def test_pinned_state(self):
        """固定したコミットの記録は seq 1〜8 で、gkg-run-result が無い（T-066・T-073・T-074 のテストの前提）。"""
        records = ledger.verify_chain(fixed_records.show("sealed/ledger.jsonl"))
        self.assertEqual([r["seq"] for r in records], list(range(1, 9)))
        self.assertNotIn(ledger.GKG_RESULT_KIND, [r["kind"] for r in records])
        body = fixed_records.show(ledger.GKG_MANIFESTS["trial"])
        self.assertEqual(len(body.splitlines()), 5)

    def test_checkout_has_no_later_refs(self):
        with tempfile.TemporaryDirectory() as d:
            c = fixed_records.checkout(os.path.join(d, "c"))
            refs = subprocess.run(["git", "-C", c, "for-each-ref", "--format=%(refname)"], check=True,
                                  capture_output=True).stdout.decode().split()
            self.assertEqual(refs, ["refs/heads/main"])
            parent = subprocess.run(["git", "-C", c, "rev-parse", "HEAD~1"], check=True,
                                    capture_output=True).stdout.decode().strip()
            self.assertEqual(parent, fixed_records.PINNED_COMMIT)
            with open(os.path.join(c, "sealed", "ledger.jsonl"), "rb") as f:
                self.assertEqual(f.read(), fixed_records.show("sealed/ledger.jsonl"))
            st = subprocess.run(["git", "-C", c, "status", "--porcelain"], check=True, capture_output=True).stdout
            self.assertEqual(st, b"")
            code, _out, err = tl.run_verify_inproc(c, "all", "--rev", "auto")
            self.assertEqual(code, 0, err)


# ---------------------------------------------------------------- 2. 許可したテスト：本物の記録で verify が 0


class TestRealHeadVerify(unittest.TestCase):
    """HEAD の本物の記録（作業ツリー）で verify all --rev auto が 0。記録の件数・kind・最後の seq には頼らない
    （記録が増えても壊れない）。作業ツリーの sealed/ がコミットと違えば、それも失敗として出る。"""

    def test_verify_all_rev_auto_is_zero(self):
        code, out, err = tl.run_verify_inproc(tl.PROJECT, "all", "--rev", "auto")
        self.assertEqual(code, 0, err[-3000:])
        self.assertIn("すべての検査に通った。", out)

    def test_recorded_at_not_after_btc_time(self):
        """どの記録の recorded_at も、Bitcoin の確定時刻（確定していれば）+ 3 時間より後でない。記録の件数・
        どれが確定済みかには頼らない（違反の一覧が空であることだけを見る）。"""
        st = post_text.verify.State(tl.PROJECT, None)
        self.assertEqual(post_text.check_recorded_vs_btc(st.records, st.times), [])


class TestOrder2GateAtResultCommit(unittest.TestCase):
    """T-077 差し戻し1回目 4（T-077 の監査 軽-1）：2つ目の固定コミット（fixed_records.RESULT_COMMIT。seq 9 の
    R の gkg-run-result まで）で、順番2の関門（order2_gate.gate・main、ledger.require_order2_gate）が開き、
    R（試しの run e15ed53595c70035）の段を返す。"""

    RID = "e15ed53595c70035"

    def test_gate_opens(self):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        c = fixed_records.checkout(os.path.join(td.name, "c"), fixed_records.RESULT_COMMIT)
        records = ledger.verify_chain(fixed_records.show("sealed/ledger.jsonl", fixed_records.RESULT_COMMIT))
        res = [r for r in records if r["kind"] == ledger.GKG_RESULT_KIND]
        self.assertEqual([r["seq"] for r in res], [9])
        ref = {"seq": 9, "record_sha256": ledger.sha256_hex(ledger.canonical_line(res[0]))}
        want = {"trial_result": ref, "input_run": {"mode": "trial", "run_id": self.RID}, "gkg_run_result": ref,
                "plan": {"action": "stage", "mode": "trial", "run_id": self.RID}}
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(ledger, "PROJECT_ROOT", c):
            self.assertEqual(ledger.require_gkg_run_result("trial", self.RID), res[0])
            got = order2_gate.gate()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = order2_gate.main([])
        self.assertEqual(got, want)
        self.assertEqual(code, 0, err.getvalue())
        self.assertEqual(json.loads(out.getvalue()), want)
        # 1つ目の固定コミット（R の gkg-run-result が無い）では閉じる
        c0 = fixed_records.checkout(os.path.join(td.name, "c0"))
        with mock.patch.object(ledger, "PROJECT_ROOT", c0):
            with self.assertRaisesRegex(ledger.Order2GateClosed, "gkg-run-result の記録が無い"):
                order2_gate.gate()


# ---------------------------------------------------------------- 3. T-074 の軽-2：正式な run の2行目以降の run-start

class TestOfficialTrialShaAllStarts(t73.Order2Case):
    """check_official_trial_manifest_sha は、正式な run のマニフェストの1行目だけでなく、2行目以降の run-start の
    行の trial_manifest_sha256 も照らす（固定したコミットの記録に、clone の中で R の gkg-run-result を足して試す）。"""

    def check(self, official):
        return ledger.check_official_trial_manifest_sha(self.read, {"trial": self.body, "official": official},
                                                        {("trial", self.rid): self.res})

    def test_later_run_start_checked(self):
        self.sealed()
        good = t73.ostart(self.body, [self.rid])
        bad = dict(good, trial_manifest_sha256="0" * 64)
        d = t73.day("official", t73.OF, "2015-03-02")
        got = self.check(t73.jl([good, d, good]))
        self.assertEqual((got["checked"], got["rows"]), (True, 2))
        # 1行目は正しく、2行目以降の run-start だけが違う形。どの位置でも、その行の番号で止まる
        for rows, line in (([good, bad], 2), ([good, d, bad], 3), ([good, d, good, bad], 4), ([bad, good], 1)):
            with self.subTest(line=line):
                with self.assertRaisesRegex(ledger.LedgerError, "の %d 行目（正式な run の run-start）の "
                                                                "trial_manifest_sha256 '0{64}'" % line):
                    self.check(t73.jl(rows))
        # 2行目の run-start の値が欠けている（None）形も止まる
        with self.assertRaisesRegex(ledger.LedgerError, "の 2 行目（正式な run の run-start）"):
            self.check(t73.jl([good, dict(good, trial_manifest_sha256=None)]))


# ---------------------------------------------------------------- 4. 手順書


class TestDocT077(unittest.TestCase):
    def setUp(self):
        with open(DOC, encoding="utf-8") as f:
            self.text = f.read()

    def test_statements(self):
        for phrase in ("テストと本物の記録（T-077）", "fixed_records.PINNED_COMMIT", "HEAD_READERS",
                       "R の gkg-run-result は最後の試しの run のあとに封印する",
                       "先に封印して試しの run をもう一度すると、順番2はできなくなる",
                       "本プロジェクトでは試しの run は seq 8 で終わりとした（reviews/T-074.md）"):
            self.assertIn(phrase, self.text)


if __name__ == "__main__":
    unittest.main()
