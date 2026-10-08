"""T-060 のテスト：順番1b の files を、ORDER1B_REQUIRED_FILES のちょうど4件に限ること（T-059 の監査 重大-1）。

実行（プロジェクトのルートで）:
    PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest discover -s tests/sealer -v

監査の再現（scratchpad/a59r/a59x_bound）：seq 6 の head に src/stats/fractions.py（標準ライブラリを隠し、偽の
出力を書く）を足した commit を作り、記録の files にそのファイルを足し、output_sha256 を偽の出力に合わせる。
T-059 の版の verify では、両方の Python で「一致」になった。照合は .venv の Python と /usr/bin/python3 の両方で、
別のプロセスとして流す。本物の sealed/ には書かない。ネットワークは使わない。
"""

import copy
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import test_ledger as tl  # noqa: E402
import test_t037 as t37  # noqa: E402
from test_t058 import ForgeBase  # noqa: E402
from test_t059 import printer  # noqa: E402

ledger = tl.ledger
verify = tl.verify
DOC = os.path.join(tl.PROJECT, "docs", "verify", "periods-seal.md")
EXTRA = "決まった 4 件（ORDER1B_REQUIRED_FILES）の外のファイル"


class TestBoundExtraFilesBothPythons(ForgeBase):
    def forge(self, path):
        wt = self.worktree(self.d1b["head"])
        real = self.real_output(wt, ledger.COUNTING_SCRIPT)
        fake = real + b" "
        shadow = printer(fake)
        head = self.commit(wt, {path: shadow}, "偽の版 " + path)
        return {str(self.o1b["seq"]): {"head": head, "output_sha256": ledger.sha256_hex(fake),
                                        "add_files": [{"path": path, "sha256": ledger.sha256_hex(shadow)}]}}

    def test_a59x_bound_module(self):
        self.assert_mismatch(self.check(self.forge("src/stats/fractions.py")), EXTRA)

    def test_a59x_bound_package(self):
        self.assert_mismatch(self.check(self.forge("src/stats/fractions/__init__.py")), EXTRA)

    def test_real_records_pass(self):
        for py, line in self.check({}).items():
            self.assertEqual(line, "OK", py)


class TestCheckOrder1bDocExact(ForgeBase):
    """ledger.check_order1b_doc（verify・関門・ほかの書く仕組みが通るもの）が、ちょうど4件に限ること。"""

    def test_real_passes_and_variants_fail(self):
        self.assertEqual(sorted(ledger.check_order1b_doc(self.o1b, self.d1b)), sorted(ledger.ORDER1B_REQUIRED_FILES))
        cases = [
            (lambda d: d["files"].append({"path": "src/stats/fractions.py", "sha256": "a" * 64}), EXTRA),
            (lambda d: d["files"].append(dict(d["files"][0])), "重なる"),
            (lambda d: d["files"].pop(), "必ず入れるファイル"),
            (lambda d: d["files"].__setitem__(0, {"path": "docs/stats/other.md", "sha256": "a" * 64}),
             "必ず入れるファイル"),
        ]
        for mutate, text in cases:
            d = copy.deepcopy(self.d1b)
            mutate(d)
            with self.subTest(text=text):
                with self.assertRaisesRegex(ledger.LedgerError, text):
                    ledger.check_order1b_doc(self.o1b, d)


class TestSealOrder1bExact(t37.StatsCase):
    """seal_order1b は、5件の files と、同じパスが2回ある files を拒む（書かない）。"""

    def test_five_files_refused(self):
        self.base()
        self.order1()
        for extra in ("src/stats/fractions.py", "src/stats/fractions/__init__.py"):
            with self.subTest(extra=extra):
                self.refuses(lambda: self.order1b(files=t37.ORDER1B_FILES + [extra]), "外のファイル %s がある" % extra)

    def test_duplicate_refused(self):
        self.base()
        self.order1()
        self.refuses(lambda: self.order1b(files=t37.ORDER1B_FILES + [t37.ORDER1B_FILES[0]]), "同じパスが2回ある")


class TestDocT060(unittest.TestCase):
    def test_statements(self):
        with open(DOC, encoding="utf-8") as f:
            text = f.read()
        for phrase in ("ちょうど4件", "files が決まった4件と一致することを先に確かめる", "T-060"):
            self.assertIn(phrase, text)


if __name__ == "__main__":
    unittest.main()
