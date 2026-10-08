"""T-059 のテスト：計算し直しで流すフォルダには、記録が sha256 で縛っているファイルだけを git show から書き出し、
Python は -I・-B・空の pycache_prefix で流すこと（T-058 の監査 重大-A）。

実行（プロジェクトのルートで）:
    PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest discover -s tests/sealer -v

監査の再現（scratchpad/a58pyc.sh、a58shadow.sh）を、偽る側が作れる commit として作り、記録の値をその偽の出力に
合わせて差し替える（T-058 の版の verify では、a58pyc は .venv で、a58shadow は両方の Python で「一致」になった）。
照合は .venv の Python と /usr/bin/python3 の両方で、別のプロセスとして流す。本物の sealed/ には書かない。
ネットワークは使わない。
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import test_ledger as tl  # noqa: E402
from test_t056 import pythons  # noqa: E402
from test_t058 import ForgeBase, git  # noqa: E402

ledger = tl.ledger
verify = tl.verify
SEALER = os.path.join(tl.PROJECT, "src", "sealer")
DOC = os.path.join(tl.PROJECT, "docs", "verify", "periods-seal.md")

COMPILE = r"""
import os, py_compile, sys
src = sys.argv[1]
# cache_from_source は使わない（macOS の /usr/bin/python3 は既定の pycache_prefix（~/Library/Caches の下）を
# 持ち、そこに書いてしまうため）。src の隣の __pycache__ に、その版の名前で書く
cfile = os.path.join(os.path.dirname(src), "__pycache__",
                     os.path.basename(src)[:-3] + "." + sys.implementation.cache_tag + ".pyc")
py_compile.compile(src, cfile=cfile, doraise=True, invalidation_mode=py_compile.PycInvalidationMode.UNCHECKED_HASH)
print(cfile)
"""


def compile_unchecked(py, src):
    """py の版の unchecked-hash の .pyc を、src の隣の __pycache__ に作る。返り値: .pyc のパス。"""
    r = subprocess.run([py, "-c", COMPILE, src], capture_output=True, check=True)
    return r.stdout.decode().strip()


def printer(data):
    return b"import os, sys\nsys.stdout.buffer.write(%s)\nsys.stdout.flush()\nos._exit(0)\n" % repr(data).encode("ascii")


class TestAuditReproductions(ForgeBase):
    def test_a58pyc_unchecked_pyc(self):
        """seq 5 の head に src/stats/__pycache__/exclusion.cpython-XY.pyc（偽の出力を書く unchecked-hash の
        .pyc。両方の Python の版）を足す。ソースはそのまま。tagrules.py の出力の値を偽の出力に合わせる。"""
        wt = self.worktree(self.d1["head"])
        real = self.real_output(wt, "src/stats/tagrules.py")
        fake = real + b" "
        with tempfile.TemporaryDirectory() as d:
            src = os.path.join(d, "exclusion.py")
            with open(src, "wb") as f:
                f.write(printer(fake))
            files = {}
            for py in pythons():
                pyc = compile_unchecked(py, src)
                with open(pyc, "rb") as f:
                    files["src/stats/__pycache__/" + os.path.basename(pyc)] = f.read()
        self.assertTrue(files)      # 流す Python の版ごとに一つ（同じ版の Python が2つなら一つになる）
        head = self.commit(wt, files, "偽の版 pyc")
        spec = {str(self.o1["seq"]): {"head": head, "targets": {"src/stats/tagrules.py の出力": ledger.sha256_hex(fake)}}}
        self.assert_mismatch(self.check(spec), "の対象 src/stats/tagrules.py の出力 の sha256")

    def test_a58shadow_stdlib(self):
        """seq 6 の head に src/stats/fractions.py（標準ライブラリを隠し、偽の出力を書く）を足す。"""
        wt = self.worktree(self.d1b["head"])
        real = self.real_output(wt, ledger.COUNTING_SCRIPT)
        fake = real + b" "
        head = self.commit(wt, {"src/stats/fractions.py": printer(fake)}, "偽の版 shadow")
        spec = {str(self.o1b["seq"]): {"head": head, "output_sha256": ledger.sha256_hex(fake)}}
        self.assert_mismatch(self.check(spec), "counting.output_sha256")

    def test_unbound_files_in_order1_head(self):
        """seq 5 の head に、標準ライブラリを隠す src/stats/json.py・.pth・.gitattributes を足しても、
        それらは置かれず、本物が流れて止まる。"""
        wt = self.worktree(self.d1["head"])
        real = self.real_output(wt, "src/stats/exclusion.py")
        fake = b" " + real
        head = self.commit(wt, {"src/stats/json.py": printer(fake), "src/stats/x.pth": b"import os\n",
                                ".gitattributes": b"* export-subst\n"}, "偽の版 json")
        spec = {str(self.o1["seq"]): {"head": head, "targets": {"src/stats/exclusion.py の出力": ledger.sha256_hex(fake)}}}
        self.assert_mismatch(self.check(spec), "の対象 src/stats/exclusion.py の出力 の sha256")


CHILD = r"""
import sys
sys.path.insert(0, sys.argv[1])
import verify
sys.stdout.buffer.write(verify._run_script(sys.argv[2], sys.argv[3], "見本"))
"""


class TestRunnerFlags(unittest.TestCase):
    """流し方（python_command）：-I・-B・空の pycache_prefix。両方の Python で確かめる。"""

    def run_child(self, py, cwd, rel, env=None):
        r = subprocess.run([py, "-B", "-c", CHILD, SEALER, cwd, rel], capture_output=True,
                           env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1", **(env or {})))
        self.assertEqual(r.returncode, 0, (py, r.stderr.decode()[-2000:]))
        return r.stdout

    def test_flags_and_path(self):
        with tempfile.TemporaryDirectory() as d:
            os.makedirs(os.path.join(d, "src"))
            with open(os.path.join(d, "src", "show.py"), "w") as f:
                f.write("import json, os, sys\nprint(json.dumps([sys.flags.isolated, sys.flags.dont_write_bytecode,"
                        " sys.flags.ignore_environment, sys.pycache_prefix is not None,"
                        " os.path.realpath(sys.path[0]) == os.path.realpath(os.path.dirname(os.path.abspath(__file__))),"
                        " '' in sys.path or os.getcwd() in sys.path, os.environ.get('PYTHONPATH'), sys.argv[0]]))\n")
            for py in pythons():
                out = json.loads(self.run_child(py, d, "src/show.py", {"PYTHONPATH": d}))
                self.assertEqual(out, [1, 1, 1, True, True, False, None, "src/show.py"], py)

    def test_pycache_is_not_read(self):
        """スクリプトの隣の __pycache__ に unchecked-hash の偽の .pyc があっても、読まずにソースから流す。
        （-I では PYTHONPYCACHEPREFIX が読まれないので、-X pycache_prefix で読ませない。）"""
        for py in pythons():
            with tempfile.TemporaryDirectory() as d:
                m = os.path.join(d, "m.py")
                with open(m, "w") as f:
                    f.write("print('fake')\n")
                compile_unchecked(py, m)
                with open(m, "w") as f:
                    f.write("print('real')\n")
                with open(os.path.join(d, "main.py"), "w") as f:
                    f.write("import m\n")
                plain = subprocess.run([py, "-B", "-c", "import sys; print(sys.pycache_prefix is None)"],
                                       capture_output=True, env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
                if plain.stdout == b"True\n":
                    plain = subprocess.run([py, "-B", "main.py"], cwd=d, capture_output=True,
                                           env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
                    self.assertEqual(plain.stdout, b"fake\n", py)    # ふつうに流すと偽の .pyc が読まれる
                self.assertEqual(self.run_child(py, d, "main.py"), b"real\n", py)
                self.assertEqual(len(os.listdir(os.path.join(d, "__pycache__"))), 1, py)   # 書き足しもしない

    def test_cwd_shadow_is_not_read(self):
        """流すフォルダの根（カレントフォルダ）に標準ライブラリを隠すファイルがあっても読まない（-I）。"""
        with tempfile.TemporaryDirectory() as d:
            os.makedirs(os.path.join(d, "src"))
            with open(os.path.join(d, "fractions.py"), "w") as f:
                f.write("print('fake')\n")
            with open(os.path.join(d, "src", "a.py"), "w") as f:
                f.write("import fractions\nprint(fractions.Fraction(1, 2))\n")
            for py in pythons():
                self.assertEqual(self.run_child(py, d, "src/a.py"), b"1/2\n", py)


class TestDocT059(unittest.TestCase):
    def test_statements(self):
        with open(DOC, encoding="utf-8") as f:
            text = f.read()
        for phrase in ("記録が sha256 で縛っているファイルだけ", "T-059", "-I -B -X pycache_prefix=",
                       'mktemp -d "${TMPDIR:-/tmp}/', "PY=/usr/bin/python3", "git archive は使わない", "/bin/sh"):
            self.assertIn(phrase, text)
        self.assertNotIn("D=$(mktemp -d) ", text)
        self.assertNotIn("env -i HOME", text)


if __name__ == "__main__":
    unittest.main()
