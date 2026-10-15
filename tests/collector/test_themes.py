"""テーマの区分表の取得（src/collector/themes.py）のテスト。T-018・T-021。ネットワークは使わない。

実行（プロジェクトのルートで）:
    PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest discover -s tests/collector -v

区分表は架空の表（テーマの名前・説明・件数の欄など）を作り、メモリの上で返す差し替えの通信で
置き換える。件数の欄の値（目印の数）が、書いたファイルとマニフェストのどこにも無いことを
確かめる。このファイルには、メールアドレスの形の文字列をそのまま書かない。
除外の規則の封印の関門（0章）は、関門そのもののテスト（TestExclusionGate）のほかは差し替える。
"""

import datetime
import hashlib
import importlib.util
import io
import json
import os
import shutil
import socket
import sys
import tempfile
import unittest
import zipfile
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
PROJECT = os.path.dirname(os.path.dirname(HERE))
SRC = os.path.join(PROJECT, "src", "collector")


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


themes = _load("themes", os.path.join(SRC, "themes.py"))
UTC = datetime.timezone.utc
NOW = datetime.datetime(2026, 10, 8, 1, 2, 3, tzinfo=UTC)
URL = "https://data.gdeltproject.org/api/v2/guides/LOOKUP-GKGTHEMES.TXT"


class NetworkUsed(AssertionError):
    pass


def _blocked(*a, **k):
    raise NetworkUsed("ネットワークに接続しようとした")


_patches = [mock.patch.object(socket.socket, "connect", _blocked),
            mock.patch.object(socket, "create_connection", _blocked),
            mock.patch.object(socket, "getaddrinfo", _blocked),
            # 0.3章の履歴の関門は、git の無い一時のフォルダでは差し替える（本物の git で確かめるのは
            # TestCodeGate・TestAppendOnly。そちらは themes.py の写しのモジュールを使う）
            mock.patch.object(themes, "_manifest_versions", lambda root: [])]


def setUpModule():
    for p in _patches:
        p.start()


EXCL_REF = {"seq": 7, "record_sha256": "e" * 64}


def no_gate(root):
    """0章の関門を通ったことにする（関門そのものは TestExclusionGate で確かめる）。"""
    return dict(EXCL_REF)


CODE_SHA = "ab" * 32


def run_two_phase(call, manifest_path):
    """0.1章の2段：1段目（試行の行を書いて止まる）→ その行をコミットしたとみなす → 2段目。

    1段目で AttemptRecorded 以外で止まれば、その例外をそのまま出す。返り値：(2段目の返り値, HEAD)。
    """
    with mock.patch.object(themes, "_code_gate", lambda root: (CODE_SHA, b"", False)):
        try:
            call()
        except themes.AttemptRecorded:
            pass
        else:
            raise AssertionError("1段目で止まらなかった")
    with open(manifest_path, "rb") as f:
        head = f.read()
    with mock.patch.object(themes, "_code_gate", lambda root: (CODE_SHA, head, True)):
        return call(), head


def no_code_gate(root):
    """0.1章のコードの関門を通ったことにする（関門そのものは TestCodeGate で確かめる）。
    返り値の2つ目は HEAD のマニフェスト（空）。"""
    return CODE_SHA, b"", False


def tearDownModule():
    for p in _patches:
        p.stop()


COUNT_MARKS = ["7123457", "8123459", "9123461"]


def tsv(header, rows):
    return ("\n".join("\t".join(r) for r in [header] + rows) + "\n").encode()


GOOD = tsv(["THEME", "DESCRIPTION", "COUNT"],
           [["QQ_ALPHA", "Alpha desc", COUNT_MARKS[0]],
            ["QQ_BETA_TWO", "Beta desc", COUNT_MARKS[1]],
            ["QQ_7_GAMMA", "Gamma desc", COUNT_MARKS[2]]])


class FakeResponse:
    def __init__(self, body, status=200):
        self.body, self.status, self.pos = body, status, 0
        self.headers = {}

    def read(self, n=-1):
        c = self.body[self.pos:self.pos + n]
        self.pos += len(c)
        return c

    def close(self):
        pass


class FakeTransport:
    def __init__(self, body, status=200):
        self.body, self.status, self.calls = body, status, []

    def __call__(self, url, timeout):
        themes.validate_doc_url(url)
        self.calls.append(url)
        return FakeResponse(self.body, self.status)


def xlsx(rows):
    """標準ライブラリで作る最小の xlsx（共有文字列とシート1つ）。"""
    strings = sorted({c for r in rows for c in r if not c.isdigit()})
    idx = {s: i for i, s in enumerate(strings)}
    ns = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
    sst = "<sst %s>%s</sst>" % (ns, "".join("<si><t>%s</t></si>" % s for s in strings))
    cells = []
    for ri, r in enumerate(rows, 1):
        cs = []
        for ci, v in enumerate(r):
            ref = chr(65 + ci) + str(ri)
            if v.isdigit():
                cs.append('<c r="%s"><v>%s</v></c>' % (ref, v))
            else:
                cs.append('<c r="%s" t="s"><v>%d</v></c>' % (ref, idx[v]))
        cells.append('<row r="%d">%s</row>' % (ri, "".join(cs)))
    sheet = "<worksheet %s><sheetData>%s</sheetData></worksheet>" % (ns, "".join(cells))
    wb = ('<workbook %s xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/'
          'relationships"><sheets><sheet name="Themes" sheetId="1" r:id="rId1"/></sheets>'
          '</workbook>' % ns)
    rels = ('<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Target="worksheets/sheet1.xml"/></Relationships>')
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("xl/sharedStrings.xml", sst)
        zf.writestr("xl/workbook.xml", wb)
        zf.writestr("xl/_rels/workbook.xml.rels", rels)
        zf.writestr("xl/worksheets/sheet1.xml", sheet)
    return buf.getvalue()


class TestUrl(unittest.TestCase):
    def test_allowed_and_rejected(self):
        """T-021：/api/v2/guides/ の下の、全テーマの区分表の1つだけを許す。"""
        self.assertEqual(themes.ALLOWED_GUIDE_FILES, ("LOOKUP-GKGTHEMES.TXT",))
        self.assertEqual(themes.THEMES_URL, URL)
        self.assertEqual(themes.validate_doc_url(URL), "LOOKUP-GKGTHEMES.TXT")
        g = "https://data.gdeltproject.org/api/v2/guides/"
        for bad in (None, "http://data.gdeltproject.org/api/v2/guides/LOOKUP-GKGTHEMES.TXT",
                    "https://data.gdeltproject.org/documentation/LOOKUP-GKGTHEMES.TXT",
                    "https://data.gdeltproject.org/documentation/TEST-THEMES.TXT",
                    g + "LOOKUP-LANGUAGES.TXT", g + "LOOKUP-COUNTRIES.TXT",
                    g + "LOOKUP-IMAGETAGS.TXT", g + "lookup-gkgthemes.txt",
                    g + "LOOKUP-GKGTHEMES.TXT?x=1", g + "LOOKUP-GKGTHEMES.TXT#x",
                    g + "../guides/LOOKUP-GKGTHEMES.TXT", g + "x/LOOKUP-GKGTHEMES.TXT",
                    g + "LOOKUP-GKGTHEMES%2ETXT",
                    "https://data.gdeltproject.org:443/api/v2/guides/LOOKUP-GKGTHEMES.TXT",
                    "https://api.gdeltcloud.com/api/v2/guides/LOOKUP-GKGTHEMES.TXT",
                    "https://data.gdeltproject.org/api/v2/LOOKUP-GKGTHEMES.TXT"):
            with self.subTest(url=bad):
                with self.assertRaises(themes.ThemesError):
                    themes.validate_doc_url(bad)
        with self.assertRaises(themes.ThemesError):
            themes.urllib_transport(g + "LOOKUP-LANGUAGES.TXT", 1)


class TestHeaderlessRule(unittest.TestCase):
    """質問 G の条件 (1)〜(4)。判定は値の形で、欄の位置によらない。"""

    def build(self, rows):
        return themes.build_output([("", rows)])

    def test_count_column_first_is_also_found_by_shape(self):
        data, n, kept, dropped, _r, headerless = self.build(
            [["123", "QQ_B"], ["45", "QQ_A"]])
        self.assertTrue(headerless)
        self.assertEqual((kept, dropped, n), (["THEME"], ["column_A"], 2))
        self.assertEqual(data, b"THEME\nQQ_A\nQQ_B\n")

    def test_stops_unless_exactly_one_assignment(self):
        for rows in ([["QQ_A", "1"], ["QQ_B", "x"]],         # 数字でない値
                     [["QQ_A", "1"], ["qq_b", "2"]],          # 名前の形でない値
                     [["QQ_A", "1", "2"]],                    # 欄が3つ
                     [["QQ_A", "1"], ["QQ_B"]],               # 欄が1つの行
                     [["QQ_A", "1,234"]],                     # ASCII の数字だけでない
                     [["QQ_A", "\uff11"]],                    # 全角の数字
                     [["\u00b2", "\u00b3"]],                   # どちらの割り当ても合わない
                     [["1", "2"]]):
            with self.subTest(rows=rows):
                with self.assertRaises(themes.ThemesError):
                    self.build(rows)

    def test_both_assignments_fit_stops(self):
        with mock.patch.object(themes, "THEME_NAME_RE", themes.re.compile(r"\A[A-Z0-9_]+\Z")):
            with self.assertRaisesRegex(themes.ThemesError, "一つに決められない"):
                self.build([["1", "2"], ["3", "4"]])

    def test_header_rows_are_not_affected(self):
        _d, _n, kept, dropped, _r, headerless = self.build([["THEME", "COUNT"], ["QQ_A", "5"]])
        self.assertFalse(headerless)
        self.assertEqual((kept, dropped), (["THEME"], ["COUNT"]))


class TestCodeGate(unittest.TestCase):
    """差し戻し1回目 中3：区分表の取得は、コミットした themes.py のコードでだけ行う。"""

    def setUp(self):
        import test_acquire_filelist as taf
        self.taf = taf
        self.tmp = tempfile.mkdtemp(prefix="themes-code-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.root = os.path.join(self.tmp, "proj")
        col = os.path.join(self.root, "src", "collector")
        os.makedirs(col)
        for n in ("themes.py", "privacy_scan.py", "codegate.py"):
            shutil.copyfile(os.path.join(SRC, n), os.path.join(col, n))
        taf.git(self.root, "init", "-q")
        taf.git(self.root, "add", "-A")
        taf.git(self.root, "commit", "-q", "-m", "x")
        self.mod = _load("themes_copy", os.path.join(col, "themes.py"))

    def test_committed_code_passes(self):
        sha, head, hist = self.mod._code_gate(self.root)
        self.assertEqual((sha, head, hist), (self.mod.code_sha256(), b"", False))

    def test_uncommitted_change_stops(self):
        with open(os.path.join(self.root, "src", "collector", "privacy_scan.py"), "ab") as f:
            f.write(b"# x\n")
        with self.assertRaisesRegex(self.mod.ThemesError, "コードの関門"):
            self.mod._code_gate(self.root)

    def test_running_code_differs_from_head_stops(self):
        p = os.path.join(self.root, "src", "collector", "themes.py")
        with open(p, "ab") as f:
            f.write(b"# x\n")
        self.taf.git(self.root, "commit", "-q", "-am", "y")   # 読み込んだあとでコミットを変える
        with self.assertRaisesRegex(self.mod.ThemesError, "HEAD にコミットした中身と違う"):
            self.mod._code_gate(self.root)

    def test_sealer_change_stops(self):
        """差し戻し2回目 軽-2：src/sealer の未コミットの変更でも止まる（ledger.py を読み込む前に）。"""
        os.makedirs(os.path.join(self.root, "src", "sealer"))
        with open(os.path.join(self.root, "src", "sealer", "ledger.py"), "wb") as f:
            f.write(b"# x\n")
        with self.assertRaisesRegex(self.mod.ThemesError, "コードの関門"):
            self.mod._code_gate(self.root)

    def test_two_phase_with_real_git(self):
        """軽-1・軽-2：試行の行をコミットしてから通信する。コミットしたあとで消しても2回目はできない。"""
        os.makedirs(os.path.join(self.root, "data", "manifest"))
        home = os.path.join(self.tmp, "home")
        os.makedirs(os.path.join(home, *themes.STORE_PARTS))
        gate = mock.patch.object(self.mod, "_exclusion_gate", no_gate)
        gate.start()
        self.addCleanup(gate.stop)
        mp = os.path.join(self.root, "data", "manifest", themes.MANIFEST_NAME)

        def run(tr):
            return self.mod.run(root=self.root, home=home, transport=tr, clock=lambda: 0.0,
                                now=lambda: NOW)
        tr = FakeTransport(GOOD, status=503)
        with self.assertRaises(self.mod.AttemptRecorded):
            run(tr)
        self.assertEqual(tr.calls, [])
        with open(mp, "rb") as f:
            line = json.loads(f.read())
        self.assertEqual((line["kind"], line["code_sha256"]), ("attempt", self.mod.code_sha256()))
        self.taf.git(self.root, "add", "data/manifest")
        self.taf.git(self.root, "commit", "-q", "-m", "試行の行")
        with self.assertRaises(self.mod.ThemesError):
            run(tr)                                        # 2段目：通信して 503
        self.assertEqual(len(tr.calls), 1)
        self.taf.git(self.root, "add", "data/manifest")
        self.taf.git(self.root, "commit", "-q", "-m", "失敗の行")
        open(mp, "w").close()                              # コミットのあとで作業ツリーから消す
        tr2 = FakeTransport(GOOD)
        with self.assertRaisesRegex(self.mod.ThemesError, "コミットしていない変更"):
            run(tr2)
        self.assertEqual(tr2.calls, [])

    def _prep_run(self):
        os.makedirs(os.path.join(self.root, "data", "manifest"))
        self.home = os.path.join(self.tmp, "home")
        os.makedirs(os.path.join(self.home, *themes.STORE_PARTS))
        gate = mock.patch.object(self.mod, "_exclusion_gate", no_gate)
        gate.start()
        self.addCleanup(gate.stop)

    def run_mod(self, tr):
        return self.mod.run(root=self.root, home=self.home, transport=tr, clock=lambda: 0.0,
                            now=lambda: NOW)

    # ---- T-101 差し戻し1回目 重大-1：追記だけの関門（0.3章）を本物の git で確かめる

    def _mp(self):
        return os.path.join(self.root, "data", "manifest", themes.MANIFEST_NAME)

    def _commit(self, msg):
        self.taf.git(self.root, "add", "data/manifest")
        self.taf.git(self.root, "commit", "-q", "-m", msg)

    def _fail_cycle(self):
        """1段目（試行の行）→ コミット → 2段目（503 で failed）→ コミット。"""
        tr = FakeTransport(GOOD, status=503)
        with self.assertRaises(self.mod.AttemptRecorded):
            self.run_mod(tr)
        self.assertEqual(tr.calls, [])
        self._commit("試行の行")
        with self.assertRaises(self.mod.ThemesError):
            self.run_mod(tr)
        self.assertEqual(len(tr.calls), 1)
        self._commit("失敗の行")

    def _rewrite(self, lines):
        with open(self._mp(), "wb") as f:
            f.write(b"".join(l + b"\n" for l in lines))
        self._commit("行を消してコミットし直す")

    def _assert_stops_without_network(self, pattern):
        before = open(self._mp(), "rb").read()
        tr = FakeTransport(GOOD)
        with self.assertRaisesRegex(self.mod.ThemesError, pattern):
            self.run_mod(tr)
        self.assertEqual(tr.calls, [])
        self.assertEqual(open(self._mp(), "rb").read(), before)

    def test_honest_appends_pass_append_only_gate(self):
        self._prep_run()
        self._fail_cycle()
        self._fail_cycle()
        self.assertEqual(len(self.mod._manifest_versions(self.root)), 4)
        with self.assertRaisesRegex(self.mod.AttemptRecorded, "3 回目"):
            self.run_mod(FakeTransport(GOOD))
        self._commit("3回目の試行の行")
        e = self.run_mod(FakeTransport(GOOD))
        self.assertEqual(e["kind"], "result")

    def test_deleting_lines_and_recommitting_cannot_reset_the_count(self):
        """監査の再現：3回失敗したあと、6行を消して普通にコミットし直しても、通信できない。"""
        self._prep_run()
        for _ in range(3):
            self._fail_cycle()
        lines = open(self._mp(), "rb").read().splitlines()
        self.assertEqual(len(lines), 9)
        self._rewrite(lines[:3])
        self._assert_stops_without_network("先頭部分でない")

    def test_deleting_one_middle_set_stops(self):
        self._prep_run()
        for _ in range(3):
            self._fail_cycle()
        lines = open(self._mp(), "rb").read().splitlines()
        self._rewrite(lines[:3] + lines[6:])                   # 2回目の1組（3行）だけを消す
        self._assert_stops_without_network("先頭部分でない")

    def test_changing_a_past_line_stops(self):
        self._prep_run()
        self._fail_cycle()
        lines = open(self._mp(), "rb").read().splitlines()
        self._rewrite(lines[:2] + [lines[2].replace(b"ThemesError", b"OtherError")])
        self._assert_stops_without_network("先頭部分でない")

    def test_deleting_the_file_and_starting_over_stops(self):
        self._prep_run()
        self._fail_cycle()
        self.taf.git(self.root, "rm", "-q", "data/manifest/" + themes.MANIFEST_NAME)
        self.taf.git(self.root, "commit", "-q", "-m", "消す")
        tr = FakeTransport(GOOD)
        with self.assertRaisesRegex(self.mod.ThemesError, "Git の履歴がある|先頭部分でない"):
            self.run_mod(tr)
        self.assertEqual(tr.calls, [])
        self.assertFalse(os.path.exists(self._mp()))

    def test_count_uses_history_maximum(self):
        a = b'{"kind": "attempt"}\n'
        f = b'{"kind": "fetch"}\n{"kind": "failed"}\n'
        head = (a + f) * 2
        self.assertEqual(self.mod.check_append_only([b"", a, a + f, head], head), 2)
        self.assertEqual(self.mod.check_append_only([], head), 0)
        with self.assertRaises(self.mod.ThemesError):
            self.mod.check_append_only([(a + f) * 3], head)

    def test_git_mv_after_fetch_stops(self):
        """T-026 軽-3 (b)：マニフェストを git mv で別の名前に移してコミットしても、2回目はできない。"""
        self._prep_run()
        tr = FakeTransport(GOOD)
        with self.assertRaises(self.mod.AttemptRecorded):
            self.run_mod(tr)
        self.taf.git(self.root, "add", "data/manifest")
        self.taf.git(self.root, "commit", "-q", "-m", "試行の行")
        self.run_mod(tr)
        self.taf.git(self.root, "add", "data/manifest")
        self.taf.git(self.root, "commit", "-q", "-m", "結果の行")
        self.taf.git(self.root, "mv", "data/manifest/" + themes.MANIFEST_NAME,
                     "data/manifest/old-themes.jsonl")
        self.taf.git(self.root, "commit", "-q", "-m", "名前を変える")
        for n in os.listdir(os.path.join(self.home, *themes.STORE_PARTS)):
            os.rename(os.path.join(self.home, *themes.STORE_PARTS, n), os.path.join(self.tmp, n))
        tr2 = FakeTransport(GOOD)
        # T-101 差し戻し1回目：今は 0.3章の追記だけの関門が先に止める（消した版は空で、過去の版は
        # その先頭部分でない）。どちらでも、通信の前に止まる
        with self.assertRaisesRegex(self.mod.ThemesError, "Git の履歴がある|先頭部分でない"):
            self.run_mod(tr2)
        self.assertEqual(tr2.calls, [])
        self.assertFalse(os.path.exists(os.path.join(self.root, "data", "manifest",
                                                     themes.MANIFEST_NAME)))

    def test_existing_themes_file_in_store_stops(self):
        self._prep_run()
        with open(os.path.join(self.home, *themes.STORE_PARTS, "gdelt-themes-x.tsv"), "wb") as f:
            f.write(b"THEME\n")
        tr = FakeTransport(GOOD)
        with self.assertRaisesRegex(self.mod.ThemesError, "保存先に区分表のファイルが既にある"):
            self.run_mod(tr)
        self.assertEqual(tr.calls, [])
        self.assertFalse(os.path.exists(os.path.join(self.root, "data", "manifest",
                                                     themes.MANIFEST_NAME)))

    def test_reset_of_history_is_a_documented_limit(self):
        """限界（README 8章）：git reset で履歴そのものを戻すと、手元の検査では見分けられない。"""
        self._prep_run()
        tr = FakeTransport(GOOD, status=503)
        with self.assertRaises(self.mod.AttemptRecorded):
            self.run_mod(tr)
        self.taf.git(self.root, "add", "data/manifest")
        self.taf.git(self.root, "commit", "-q", "-m", "試行の行")
        with self.assertRaises(self.mod.ThemesError):
            self.run_mod(tr)
        self.taf.git(self.root, "add", "data/manifest")
        self.taf.git(self.root, "commit", "-q", "-m", "失敗の行")
        self.taf.git(self.root, "reset", "-q", "--hard", "HEAD~1")
        tr2 = FakeTransport(GOOD)
        self.run_mod(tr2)
        self.assertEqual(len(tr2.calls), 1)

    def test_other_root_stops(self):
        with self.assertRaisesRegex(themes.ThemesError, "root のプロジェクトのものでない"):
            themes._code_gate(self.root)


class TestExclusionGate(unittest.TestCase):
    """T-021：統計係の除外の規則の封印より前には、区分表を取得しない。"""

    def setUp(self):
        p = mock.patch.object(themes, "_code_gate", no_code_gate)
        p.start()
        self.addCleanup(p.stop)
        self.tmp = tempfile.mkdtemp(prefix="themes-gate-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.root = os.path.join(self.tmp, "proj")
        os.makedirs(os.path.join(self.root, "data", "manifest"))
        self.home = os.path.join(self.tmp, "home")
        os.makedirs(os.path.join(self.home, *themes.STORE_PARTS))
        self.ledger = themes._import_ledger()

    def written(self):
        out = []
        for top in (self.root, self.home):
            for d, _ds, fs in os.walk(top):
                out += fs
        return out

    def run_themes(self):
        self.tr = FakeTransport(GOOD)
        out, _head = run_two_phase(
            lambda: themes.run(root=self.root, home=self.home, transport=self.tr,
                               clock=lambda: 0.0, now=lambda: NOW),
            os.path.join(self.root, "data", "manifest", themes.MANIFEST_NAME))
        return out

    def test_kind_is_stats_order1(self):
        """T-032：除外の規則の kind は stats-order1（封印係の ledger.ORDER1_KIND と同じ）。"""
        self.assertEqual(themes.EXCLUSION_RULE_KIND, "stats-order1")
        self.assertEqual(themes.EXCLUSION_RULE_KIND, self.ledger.ORDER1_KIND)
        self.assertIn(themes.EXCLUSION_RULE_KIND, self.ledger.ALLOWED_KINDS)

    @staticmethod
    def files_under(top, skip=None):
        out = []
        for d, ds, fs in os.walk(top):
            if skip is not None and d == top and skip in ds:
                ds.remove(skip)
            out += [os.path.relpath(os.path.join(d, f), top) for f in fs]
        return sorted(out)

    def test_ledger_without_order1_stops_before_network(self):
        """封印の記録に stats-order1 の記録が無ければ、関門が通信の前に止まる。T-050：本物の記録の
        状態に頼らず（本物には seq 5 に stats-order1 がある）、順番1b・method-access・gkg-run-start は
        あるが stats-order1 の無い仮の記録で確かめる。"""
        import test_gkg as tg
        for kinds in ((), tg.KINDS_WITHOUT_ORDER1):
            with self.subTest(kinds=kinds):
                root = tempfile.mkdtemp(prefix="themes-noorder1-")
                self.addCleanup(shutil.rmtree, root, True)
                os.makedirs(os.path.join(root, "data", "manifest"))
                tg.make_sealed_project(root, kinds)
                with mock.patch.object(self.ledger, "PROJECT_ROOT", root):
                    self.tr = FakeTransport(GOOD)
                    with self.assertRaisesRegex(themes.ExclusionRulesNotSealed, "stats-order1）が無い"):
                        themes.run(root=root, home=self.home, transport=self.tr,
                                   clock=lambda: 0.0, now=lambda: NOW)
                self.assertEqual(self.tr.calls, [])
                # 書き込み0件：root（仮の封印の記録のほか）と home の全体に、何も書かれていない
                self.assertEqual(self.files_under(root, skip="sealed"), [])
                self.assertEqual(self.files_under(self.home), [])

    def test_ledger_with_order1_passes_the_gate(self):
        """対照：仮の記録の7種類（stats-order1 の無い並び）の後ろに stats-order1 を1件足すと、関門を通る
        （ほかの種類が並ぶ中から読めていることの確かめ）。"""
        import test_gkg as tg
        root = tempfile.mkdtemp(prefix="themes-order1-")
        self.addCleanup(shutil.rmtree, root, True)
        recs = tg.make_sealed_project(root, tg.KINDS_WITH_ORDER1)
        with mock.patch.object(self.ledger, "PROJECT_ROOT", root):
            rec, gate_root = themes.require_exclusion_rules_sealed()
        self.assertEqual((rec["seq"], rec["kind"]), (recs[-1]["seq"], "stats-order1"))
        self.assertEqual(os.path.realpath(gate_root), os.path.realpath(root))

    def test_two_records_of_kind_stop(self):
        with self.assertRaisesRegex(themes.ExclusionRulesNotSealed, "2 件ある"):
            self.gate_with(self.records(["periods", "exclusion-rules", "exclusion-rules"]))
        self.assertEqual(self.tr.calls, [])

    def records(self, kinds):
        return [{"seq": i + 1, "kind": k} for i, k in enumerate(kinds)]

    def gate_with(self, records, kind="exclusion-rules", allowed=True, root=None):
        kinds = self.ledger.ALLOWED_KINDS + ((kind,) if allowed else ())
        with mock.patch.object(themes, "EXCLUSION_RULE_KIND", kind), \
                mock.patch.object(self.ledger, "ALLOWED_KINDS", kinds), \
                mock.patch.object(self.ledger, "_gate_root", return_value=root or self.root), \
                mock.patch.object(self.ledger, "_load_for_gate",
                                  return_value=(b"", records)) as load:
            out = self.run_themes()
        load.assert_called_with(root or self.root)
        return out

    def test_kind_not_in_allowed_list(self):
        with self.assertRaisesRegex(themes.ExclusionRulesNotSealed, "許可リスト"):
            self.gate_with(self.records(["periods"]), allowed=False)
        self.assertEqual(self.tr.calls, [])

    def test_no_record_of_kind(self):
        with self.assertRaisesRegex(themes.ExclusionRulesNotSealed, "記録.*が無い"):
            self.gate_with(self.records(["periods", "candidates"]))
        self.assertEqual(self.tr.calls, [])
        self.assertEqual(self.written(), [])

    def test_ledger_invalid(self):
        bad = mock.Mock(side_effect=self.ledger.LedgerError("見本"))
        with mock.patch.object(themes, "EXCLUSION_RULE_KIND", "periods"), \
                mock.patch.object(self.ledger, "_gate_root", return_value=self.root), \
                mock.patch.object(self.ledger, "_load_for_gate", bad):
            with self.assertRaisesRegex(themes.ExclusionRulesNotSealed, "検証できない"):
                self.run_themes()
        self.assertEqual(self.tr.calls, [])

    def test_other_root_refused(self):
        with self.assertRaisesRegex(themes.ExclusionRulesNotSealed, "root が違う"):
            self.gate_with(self.records(["periods", "exclusion-rules"]), root=self.tmp)
        self.assertEqual(self.tr.calls, [])

    def test_passes_with_record(self):
        recs = self.records(["periods", "exclusion-rules"])
        e = self.gate_with(recs)
        self.assertEqual(len(self.tr.calls), 1)
        want = self.ledger.canonical_line(recs[1])
        self.assertEqual((e["exclusion_rule_seq"], e["exclusion_rule_record_sha256"]),
                         (2, hashlib.sha256(want).hexdigest()))
        self.assertEqual(e["source_url"], URL)

    def test_gate_is_first_in_run(self):
        import inspect
        body = inspect.getsource(themes.run).split('"""', 2)[2]
        lines = [l.strip() for l in body.splitlines() if l.strip()]
        self.assertTrue(lines[2].startswith("sha_code, head_manifest, has_history = _code_gate(root)"),
                        lines[:4])
        self.assertTrue(lines[3].startswith(
            "hist_attempts = check_append_only(_manifest_versions(root), head_manifest)"), lines[:5])
        self.assertTrue(lines[4].startswith("excl = _exclusion_gate(root)"), lines[:5])


class TestClassify(unittest.TestCase):
    def test_count_and_unknown_columns_dropped(self):
        header = ["THEME", "Description", "Count", "Frequency", "Mystery", "Type"]
        rows = [["QQ_X", "d", "5", "6", "abc", "THEME"], ["QQ_Z", "e", "7", "8", "def", "THEME"]]
        keep, drop = themes.classify_columns(header, rows)
        self.assertEqual([header[i] for i in keep], ["THEME", "Description", "Type"])
        self.assertEqual(drop, ["Count", "Frequency", "Mystery"])

    def test_counts_hidden_in_kept_columns(self):
        """監査の5つの形：説明・種類・注記・kind の中の数、名前の欄の中の数。"""
        base = [["QQ_A", "plain", "x", "y", "k"], ["QQ_B", "plain", "x", "y", "k"]]
        header = ["Theme", "Description", "Type", "Notes", "kind"]
        cases = {
            "Description": "Seen in 1,234,567 articles",
            "Type": "1234",
            "Notes": "12.3k",
            "kind": "1 234",
        }
        for col, val in cases.items():
            with self.subTest(col=col):
                rows = [list(r) for r in base]
                rows[0][header.index(col)] = val
                if col == "Type":
                    rows[1][header.index(col)] = "N/A"
                keep, drop = themes.classify_columns(header, rows)
                self.assertIn(col, drop)
                self.assertNotIn(header.index(col), keep)
        rows = [list(r) for r in base]
        rows[0][0] = "QQ_A (1234)"
        with self.assertRaisesRegex(themes.ThemesError, "名前の形に合わない"):
            themes.classify_columns(header, rows)

    @mock.patch.object(themes, "_exclusion_gate", no_gate)
    @mock.patch.object(themes, "_code_gate", no_code_gate)
    def test_hidden_counts_never_written(self):
        tmp = tempfile.mkdtemp(prefix="themes-hidden-")
        self.addCleanup(shutil.rmtree, tmp, True)
        root, home = os.path.join(tmp, "p"), os.path.join(tmp, "h")
        os.makedirs(os.path.join(root, "data", "manifest"))
        os.makedirs(os.path.join(home, *themes.STORE_PARTS))
        body = tsv(["Theme", "Description", "Type", "Notes", "kind"],
                   [["QQ_A", "Seen in 7,123,457 articles", "8123459", "12.3k", "9 123461"],
                    ["QQ_B", "plain", "N/A", "none", "k"]])
        e, _head = run_two_phase(
            lambda: themes.run(root=root, home=home, url=URL, transport=FakeTransport(body),
                               clock=lambda: 0.0, now=lambda: NOW),
            os.path.join(root, "data", "manifest", themes.MANIFEST_NAME))
        self.assertEqual(e["kept_columns"], ["Theme"])
        for top in (os.path.join(home, *themes.STORE_PARTS), os.path.join(root, "data", "manifest")):
            for n in os.listdir(top):
                with open(os.path.join(top, n), "rb") as f:
                    data = f.read()
                for m in (b"7,123,457", b"8123459", b"12.3k", b"123461", b"Seen in"):
                    self.assertNotIn(m, data)

    def test_unicode_numbers_in_kept_columns(self):
        """T-018 の監査 軽3：Unicode の数字・上付きの数字・丸付き・分数・ローマ数字・漢数字。"""
        header = ["Theme", "Description"]
        for val in ("Seen in \u0661\u0662\u0663 articles", "x\u00b2", "n\u2083", "\u2460 item",
                    "\u00bd of all", "\u216b", "\u4e00\u4e07 articles", "\uff11\uff12",
                    "\U0001d7cf", "\u0967\u0968"):
            with self.subTest(val=val):
                keep, drop = themes.classify_columns(header, [["QQ_A", val], ["QQ_B", "plain"]])
                self.assertEqual((keep, drop), ([0], ["Description"]))
                self.assertTrue(themes.has_numeric(val))
        for val in ("plain", "Theme of ECON", "a-b_c"):
            self.assertFalse(themes.has_numeric(val))

    def test_unicode_numeric_header_means_headerless(self):
        for h in ("\uff11\uff12\uff13", "\u00b2\u00b3", "1 234", "\u0661\u0662", "12.5"):
            with self.subTest(h=h):
                with self.assertRaisesRegex(themes.ThemesError, "見出しの行が無い"):
                    themes.classify_columns(["THEME", h], [["QQ_A", "x"]])

    def test_dropped_header_with_number_is_not_written(self):
        keep, drop = themes.classify_columns(
            ["THEME", "Count (1,234,567)", "Mystery\u00b2", "Frequency"],
            [["QQ_A", "5", "x", "6"]])
        self.assertEqual(drop, ["column_B", "column_C", "Frequency"])

    def test_sheet_names_with_numbers_are_replaced(self):
        rows = [["THEME", "DESCRIPTION"], ["QQ_A", "alpha"]]
        data, n, kept, dropped, replaced, _h = themes.build_output(
            [("Themes (12,345)", rows), ("Other", [["THEME", "DESCRIPTION"], ["QQ_B", "beta"]])])
        self.assertTrue(replaced)
        text = data.decode()
        self.assertNotIn("12,345", text)
        self.assertEqual(text.splitlines()[0], "sheet\tTHEME\tDESCRIPTION")
        self.assertIn("sheet_A\tQQ_A\talpha", text)
        self.assertIn("sheet_B\tQQ_B\tbeta", text)
        for name in ("\u2460", "\u00b2x", "\u0661"):
            _d, _n, _k, _dr, rep2, _h = themes.build_output([(name, rows), ("Other", rows)])
            self.assertTrue(rep2, name)
        data, _n, _k, _d, replaced, _h = themes.build_output([("Alpha", rows), ("Beta", rows)])
        self.assertFalse(replaced)
        self.assertIn("Alpha\tQQ_A", data.decode())
        data, _n, _k, _d, replaced, _h = themes.build_output([("Themes 2024", rows)])
        self.assertFalse(replaced)                     # シートが1つならシート名は書かない
        self.assertNotIn("2024", data.decode())

    def test_numeric_values_dropped_even_with_keep_header(self):
        keep, drop = themes.classify_columns(["NAME", "TYPE"], [["QQ_X", "12"], ["QQ_Y", "3"]])
        self.assertEqual((keep, drop), ([0], ["TYPE"]))

    def test_headerless_or_bad_shapes_stop(self):
        for header, rows in (
                (["QQ_X", "123"], [["QQ_Y", "4"]]),          # 見出しの無い形（件数が見出しに）
                (["", "NAME"], [["a", "QQ_X"]]),
                (["NAME", "name"], [["QQ_X", "QQ_Y"]]),
                (["COUNT"], [["5"]]),                           # 残す欄が無い
                (["DESCRIPTION"], [["some text"]])):           # テーマの名前の欄が無い
            with self.subTest(header=header):
                with self.assertRaises(themes.ThemesError):
                    themes.classify_columns(header, rows)


class RunCase(unittest.TestCase):
    def setUp(self):
        for p in (mock.patch.object(themes, "_exclusion_gate", no_gate),
                  mock.patch.object(themes, "_code_gate", no_code_gate)):
            p.start()
            self.addCleanup(p.stop)
        self.tmp = tempfile.mkdtemp(prefix="themes-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.root = os.path.join(self.tmp, "proj")
        os.makedirs(os.path.join(self.root, "data", "manifest"))
        self.home = os.path.join(self.tmp, "home")
        self.store = os.path.join(self.home, *themes.STORE_PARTS)
        os.makedirs(self.store)

    def manifest_path(self):
        return os.path.join(self.root, "data", "manifest", themes.MANIFEST_NAME)

    def run_themes(self, body, url=URL, status=200):
        """マニフェストが無ければ2段で、あれば今の HEAD（self.head）で1回動かす。"""
        self.tr = FakeTransport(body, status)

        def call():
            return themes.run(root=self.root, home=self.home, url=url, transport=self.tr,
                              clock=lambda: 0.0, now=lambda: NOW)
        if not os.path.lexists(self.manifest_path()):
            with mock.patch.object(themes, "_code_gate", lambda root: (CODE_SHA, b"", False)):
                with self.assertRaises(themes.AttemptRecorded):
                    call()                             # 1段目：試行の行だけ
            self.commit_all()                          # その行をコミットしたとみなす
        with mock.patch.object(themes, "_code_gate", lambda root: (CODE_SHA, self.head, bool(self.head))):
            return call()

    def commit_all(self):
        with open(self.manifest_path(), "rb") as f:
            self.head = f.read()

    def written(self):
        out = {}
        for top in (self.store, os.path.join(self.root, "data", "manifest")):
            for n in os.listdir(top):
                with open(os.path.join(top, n), "rb") as f:
                    out[n] = f.read()
        return out


class TestRun(RunCase):
    def test_counts_dropped_before_writing(self):
        e = self.run_themes(GOOD)
        self.assertEqual(len(self.tr.calls), 1)
        self.assertEqual(e["kept_columns"], ["THEME", "DESCRIPTION"])
        self.assertEqual(e["dropped_columns"], ["COUNT"])
        self.assertEqual(e["rows"], 3)
        files = self.written()
        self.assertEqual(sorted(files), [e["file_name"], themes.MANIFEST_NAME])
        for name, data in files.items():
            for m in COUNT_MARKS:
                self.assertNotIn(m.encode(), data, name)
            self.assertEqual(themes.privacy_scan.find_in_bytes(data), {}, name)
        body = files[e["file_name"]].decode()
        self.assertEqual(body.splitlines()[0], "THEME\tDESCRIPTION")
        self.assertIn("QQ_ALPHA\tAlpha desc", body)
        line = json.loads(files[themes.MANIFEST_NAME].splitlines()[-1])
        self.assertEqual(line["sha256"], e["sha256"])
        self.assertEqual(line["source_url"], URL)
        self.assertNotIn(self.home, files[themes.MANIFEST_NAME].decode())

    def test_xlsx(self):
        data = xlsx([["NAME", "DESCRIPTION", "NUMARTS"],
                     ["QQ_ALPHA", "Alpha", COUNT_MARKS[0]],
                     ["QQ_BETA_TWO", "Beta", COUNT_MARKS[1]]])
        name = "LOOKUP-GKGTHEMES.xlsx"                 # 形を確かめるためだけに名前を足す
        with mock.patch.object(themes, "ALLOWED_GUIDE_FILES", themes.ALLOWED_GUIDE_FILES + (name,)):
            e = self.run_themes(data, url=URL.replace("LOOKUP-GKGTHEMES.TXT", name))
        self.assertEqual(e["dropped_columns"], ["NUMARTS"])
        self.assertFalse(e["sheet_names_replaced"])
        for data in self.written().values():
            for m in COUNT_MARKS:
                self.assertNotIn(m.encode(), data)

    def attempt_only(self):
        """通信のあとで止まったとき：試行・fetch・failed の行だけが残り、区分表の本体は書かれない。"""
        files = self.written()
        self.assertEqual(sorted(files), [themes.MANIFEST_NAME])
        lines = [json.loads(l) for l in files[themes.MANIFEST_NAME].splitlines()]
        self.assertEqual([l["kind"] for l in lines], ["attempt", "fetch", "failed"])
        self.assertEqual(lines[0]["code_sha256"], CODE_SHA)
        self.assertEqual(lines[0]["source_url"], URL)

    def fresh(self):
        shutil.rmtree(self.tmp, True)
        self.setUp()

    def test_stops_without_writing(self):
        cases = [tsv(["QQ_X", "5", "x"], [["QQ_Y", "6", "y"]]),  # 見出しが無く、欄が3つ
                 GOOD.replace(b"QQ_ALPHA", b"see " + b"a" + b"@" + b"b.org" * 1),
                 b"\xff\xfe broken"]
        for body in cases:
            with self.subTest(body=body[:20]):
                self.fresh()
                with self.assertRaises(themes.ThemesError):
                    self.run_themes(body)
                self.attempt_only()

    def test_single_attempt_no_retry(self):
        with self.assertRaises(themes.ThemesError):
            self.run_themes(GOOD, status=503)
        self.assertEqual(len(self.tr.calls), 1)
        self.attempt_only()

    def test_size_limit(self):
        with mock.patch.object(themes, "MAX_BYTES", 10):
            with self.assertRaises(themes.ThemesError):
                self.run_themes(GOOD)
        self.attempt_only()

    def test_only_one_attempt_ever(self):
        """差し戻し1回目 中3（T-101 で改めた）：失敗のあとは、コミットしてから新しい attempt の行を書く
        だけで通信しない。成功（result）のあとは、もう取得しない。"""
        with self.assertRaises(themes.ThemesError):
            self.run_themes(GOOD, status=503)
        with self.assertRaisesRegex(themes.ThemesError, "コミットしていない変更"):
            self.run_themes(GOOD)
        self.commit_all()
        with self.assertRaisesRegex(themes.AttemptRecorded, "取り直し"):
            self.run_themes(GOOD)
        self.assertEqual(self.tr.calls, [])
        files = self.written()
        self.assertEqual(sorted(files), [themes.MANIFEST_NAME])
        self.assertEqual([json.loads(l)["kind"] for l in files[themes.MANIFEST_NAME].splitlines()],
                         ["attempt", "fetch", "failed", "attempt"])
        self.fresh()
        e = self.run_themes(GOOD)
        self.assertEqual(e["kind"], "result")
        self.commit_all()
        with self.assertRaisesRegex(themes.ThemesError, "既に取得した"):
            self.run_themes(GOOD)
        self.assertEqual(self.tr.calls, [])
        lines = [json.loads(l) for l in self.written()[themes.MANIFEST_NAME].splitlines()]
        self.assertEqual([l["kind"] for l in lines], ["attempt", "fetch", "result"])
        self.assertEqual(lines[2]["attempted_at"], lines[0]["attempted_at"])
        self.assertEqual(lines[2]["code_sha256"], CODE_SHA)

    def test_emptied_uncommitted_manifest_stops(self):
        """差し戻し2回目 軽-1（監査の再現 exp_th2）：コミット前に試行の行を消して空にしても止まる。"""
        with self.assertRaises(themes.ThemesError):
            self.run_themes(GOOD, status=503)
        open(os.path.join(self.root, "data", "manifest", themes.MANIFEST_NAME), "w").close()
        with self.assertRaisesRegex(themes.ThemesError, "コミットしていない変更"):
            self.run_themes(GOOD)
        self.assertEqual(self.tr.calls, [])

    def test_first_phase_does_not_fetch(self):
        """差し戻し3回目 軽-2：1段目は試行の行を書いて止まり、通信しない。"""
        tr = FakeTransport(GOOD)
        with self.assertRaises(themes.AttemptRecorded):
            themes.run(root=self.root, home=self.home, transport=tr, clock=lambda: 0.0,
                       now=lambda: NOW)
        self.assertEqual(tr.calls, [])
        lines = [json.loads(l) for l in self.written()[themes.MANIFEST_NAME].splitlines()]
        self.assertEqual([l["kind"] for l in lines], ["attempt"])
        with self.assertRaisesRegex(themes.ThemesError, "コミットしていない変更"):
            themes.run(root=self.root, home=self.home, transport=tr, clock=lambda: 0.0,
                       now=lambda: NOW)                # コミットしないまま2段目
        self.assertEqual(tr.calls, [])

    def test_deleting_uncommitted_attempt_before_fetch_is_harmless(self):
        """コミット前に試行の行を消しても、まだ通信していないので、1段目からやり直すだけ。"""
        tr = FakeTransport(GOOD)
        with self.assertRaises(themes.AttemptRecorded):
            themes.run(root=self.root, home=self.home, transport=tr, clock=lambda: 0.0,
                       now=lambda: NOW)
        os.rename(self.manifest_path(), os.path.join(self.tmp, "aside"))
        with self.assertRaises(themes.AttemptRecorded):
            themes.run(root=self.root, home=self.home, transport=tr, clock=lambda: 0.0,
                       now=lambda: NOW)
        self.assertEqual(tr.calls, [])

    def test_committed_attempt_must_match_code_and_rule(self):
        tr = FakeTransport(GOOD)
        with self.assertRaises(themes.AttemptRecorded):
            themes.run(root=self.root, home=self.home, transport=tr, clock=lambda: 0.0,
                       now=lambda: NOW)
        self.commit_all()
        with mock.patch.object(themes, "_code_gate", lambda root: ("cd" * 32, self.head, True)):
            with self.assertRaisesRegex(themes.ThemesError, "このコードかこの除外の規則のものでない"):
                themes.run(root=self.root, home=self.home, transport=tr, clock=lambda: 0.0,
                           now=lambda: NOW)
        with mock.patch.object(themes, "_code_gate", lambda root: (CODE_SHA, self.head, bool(self.head))), \
                mock.patch.object(themes, "_exclusion_gate",
                                  lambda root: {"seq": 8, "record_sha256": "e" * 64}):
            with self.assertRaisesRegex(themes.ThemesError, "このコードかこの除外の規則のものでない"):
                themes.run(root=self.root, home=self.home, transport=tr, clock=lambda: 0.0,
                           now=lambda: NOW)
        self.assertEqual(tr.calls, [])

    def test_reverting_to_committed_attempt_allows_refetch_limit(self):
        """限界（README 8章）：通信のあとの行をコミット前に消して HEAD と同じに戻すと、もう一度通信
        できる。手元の検査では止められない。"""
        with self.assertRaises(themes.ThemesError):
            self.run_themes(GOOD, status=503)
        with open(self.manifest_path(), "wb") as f:
            f.write(self.head)
        self.run_themes(GOOD)
        self.assertEqual(len(self.tr.calls), 1)

    def test_gate_failure_writes_nothing(self):
        def stop(root):
            raise themes.ThemesError("見本")
        tr = FakeTransport(GOOD)
        with mock.patch.object(themes, "_code_gate", stop):
            with self.assertRaises(themes.ThemesError):
                themes.run(root=self.root, home=self.home, transport=tr, clock=lambda: 0.0,
                           now=lambda: NOW)
        self.assertEqual(self.written(), {})
        self.assertEqual(tr.calls, [])

    def test_headerless_name_and_count(self):
        """リードの判断（質問 G）：見出しの無い「名前・件数」の2欄なら、名前の欄だけを残す。"""
        body = tsv(["QQ_ZETA", COUNT_MARKS[0]],
                   [["QQ_ALPHA", COUNT_MARKS[1]], ["QQ_MID_7", COUNT_MARKS[2]]])
        e = self.run_themes(body)
        self.assertTrue(e["headerless"])
        self.assertEqual((e["kept_columns"], e["dropped_columns"]), (["THEME"], ["column_B"]))
        out = self.written()[e["file_name"]].decode()
        self.assertEqual(out.splitlines(), ["THEME", "QQ_ALPHA", "QQ_MID_7", "QQ_ZETA"])  # 並べ替え
        for data in self.written().values():
            for m in COUNT_MARKS:
                self.assertNotIn(m.encode(), data)

    def test_citation(self):
        self.assertIn("Data: The GDELT Project (https://www.gdeltproject.org/).",
                      " ".join(themes.__doc__.split()))


class TestRetry(RunCase):
    """T-101：取り直し（0.2章）。追記だけ、回数は attempt の行の数、上限 MAX_TOTAL_ATTEMPTS。"""

    def call(self, body=GOOD, status=200, head=None):
        self.tr = FakeTransport(body, status)
        head = self.head if head is None else head
        with mock.patch.object(themes, "_code_gate", lambda root: (CODE_SHA, head, True)):
            return themes.run(root=self.root, home=self.home, url=URL, transport=self.tr,
                              clock=lambda: 0.0, now=lambda: NOW, diag=lambda t: None)

    def manifest(self):
        with open(self.manifest_path(), "rb") as f:
            return f.read()

    def kinds(self):
        return [json.loads(l)["kind"] for l in self.manifest().splitlines()]

    def fail_once(self):
        """1段目（試行の行）→ コミット → 2段目（503 で failed）→ コミット。"""
        if os.path.lexists(self.manifest_path()):
            with self.assertRaises(themes.AttemptRecorded):
                self.call()
            self.assertEqual(self.tr.calls, [])            # 1段目は通信しない
        else:
            with self.assertRaises(themes.ThemesError):
                self.run_themes(GOOD, status=503)
            self.commit_all()
            return
        self.commit_all()
        with self.assertRaises(themes.ThemesError):
            self.call(status=503)
        self.assertEqual(len(self.tr.calls), 1)
        self.commit_all()

    def test_constant(self):
        self.assertEqual(themes.MAX_TOTAL_ATTEMPTS, 3)
        self.assertEqual(themes.MAX_ATTEMPTS, 1)

    def test_retry_appends_only_and_succeeds(self):
        self.fail_once()
        before = self.manifest()
        with self.assertRaisesRegex(themes.AttemptRecorded, "2 回目"):
            self.call()
        self.assertEqual(self.tr.calls, [])
        self.assertTrue(self.manifest().startswith(before))   # 前の行は変えない
        new = json.loads(self.manifest()[len(before):])
        self.assertEqual(sorted(new), ["attempted_at", "code_path", "code_sha256",
                                       "exclusion_rule_record_sha256", "exclusion_rule_seq",
                                       "kind", "source_url"])
        first = json.loads(before.splitlines()[0])
        self.assertEqual(sorted(new), sorted(first))          # 最初の attempt と同じキー
        self.commit_all()
        e = self.call()
        self.assertEqual(e["kind"], "result")
        self.assertEqual(self.kinds(), ["attempt", "fetch", "failed", "attempt", "fetch", "result"])
        self.assertTrue(self.manifest().startswith(before))
        self.assertEqual(e["attempted_at"], new["attempted_at"])

    def test_retry_attempt_must_be_committed_before_fetch(self):
        self.fail_once()
        with self.assertRaises(themes.AttemptRecorded):
            self.call()
        with self.assertRaisesRegex(themes.ThemesError, "コミットしていない変更"):
            self.call()                                        # HEAD は failed で終わる版
        self.assertEqual(self.tr.calls, [])

    def test_cap_stops_before_network_and_writes_nothing(self):
        for _ in range(themes.MAX_TOTAL_ATTEMPTS):
            self.fail_once()
        self.assertEqual(self.kinds().count("attempt"), 3)
        before = self.manifest()
        with self.assertRaisesRegex(themes.ThemesError, "上限の 3 回に達した"):
            self.call()
        self.assertEqual(self.tr.calls, [])
        self.assertEqual(self.manifest(), before)

    def test_too_many_attempts_in_record_stops_before_network(self):
        self.fail_once()
        a = self.manifest().splitlines()[0]
        tail = b"\n".join([a, b'{"at": "2026-10-08T01:02:03Z", "code_sha256": "%s", "kind": "fetch"}'
                           % CODE_SHA.encode(), b'{"at": "2026-10-08T01:02:03Z", "kind": "failed", '
                           b'"reason": "ThemesError"}']) + b"\n"
        with open(self.manifest_path(), "ab") as f:
            f.write(tail + tail + a + b"\n")                   # attempt が4行（最後は attempt）
        self.commit_all()
        with self.assertRaisesRegex(themes.ThemesError, "上限 3 を超えている"):
            self.call()
        self.assertEqual(self.tr.calls, [])

    def test_bad_orders_stop(self):
        a = b'{"kind": "attempt"}'
        fe = b'{"kind": "fetch"}'
        fa = b'{"kind": "failed"}'
        r = b'{"kind": "result"}'
        cases = {"failed のあとに failed": [a, fe, fa, fa], "先頭が fetch": [fe],
                 "attempt のあとに attempt": [a, a], "result のあと": [a, fe, r, a],
                 "知らない kind": [a, b'{"kind": "other"}'], "JSON でない": [b"x"],
                 "attempt のあとに failed": [a, fa]}
        for what, lines in cases.items():
            with self.subTest(what):
                with self.assertRaises(themes.ThemesError):
                    themes.parse_manifest(b"\n".join(lines) + b"\n")
        with self.assertRaisesRegex(themes.ThemesError, "空"):
            themes.parse_manifest(b"")
        self.assertEqual(len(themes.parse_manifest(b"\n".join([a, fe, fa, a, fe, r]) + b"\n")), 6)

    def test_manifest_ending_in_fetch_stops(self):
        self.fail_once()
        body = b"\n".join(self.manifest().splitlines()[:2]) + b"\n"    # attempt, fetch
        with open(self.manifest_path(), "wb") as f:
            f.write(body)
        self.commit_all()
        with self.assertRaisesRegex(themes.ThemesError, "fetch の行で終わっている"):
            self.call()
        self.assertEqual(self.tr.calls, [])

    def test_result_stops_retry(self):
        self.run_themes(GOOD)
        self.commit_all()
        before = self.manifest()
        with self.assertRaisesRegex(themes.ThemesError, "既に取得した"):
            self.call()
        self.assertEqual((self.tr.calls, self.manifest()), ([], before))

    def test_existing_store_file_stops_retry(self):
        self.fail_once()
        open(os.path.join(self.store, "gdelt-themes-x.tsv"), "w").close()
        before = self.manifest()
        with self.assertRaisesRegex(themes.ThemesError, "保存先に区分表のファイル"):
            self.call()
        self.assertEqual(self.manifest(), before)


# 診断のテストに使う名前。どの4文字の断片も、診断の鍵（英小文字の語）に現れない形にする
DIAG_NAMES = ["ZQXJ_Wvkq", "ZQXJ-PFFB", "ZQXJ PFFB", "\u00c4ZQXJ_K", "9ZQXJ_K", "ZQXJ_OK",
              "QZXJ_" + "K" * 170]
DIAG_COUNTS = ["7123457", "8123459", "91234x61", "1234", "5678", "9012", "3456"]


def diag_table():
    return ("\n".join("%s\t%s" % (a, b) for a, b in zip(DIAG_NAMES, DIAG_COUNTS)) + "\n").encode()


class TestDiagnosis(RunCase):
    """T-101：形の判定で止まったときの診断（6章）。数と種類だけ。値・名前の断片は出さない。"""

    def run_diag(self, body, status=200):
        got = []
        self.tr = FakeTransport(body, status)

        def call():
            return themes.run(root=self.root, home=self.home, url=URL, transport=self.tr,
                              clock=lambda: 0.0, now=lambda: NOW, diag=got.append)
        with mock.patch.object(themes, "_code_gate", lambda root: (CODE_SHA, b"", False)):
            with self.assertRaises(themes.AttemptRecorded):
                call()
        self.commit_all()
        with mock.patch.object(themes, "_code_gate", lambda root: (CODE_SHA, self.head, True)):
            with self.assertRaises(themes.ThemesError) as cm:
                call()
        return got, cm.exception

    def assert_no_fragments(self, text, values):
        for v in values:
            for i in range(len(v) - 3):
                self.assertNotIn(v[i:i + 4], text, "値の断片が診断に出た")

    def test_headerless_shape_failure_emits_counts_only(self):
        got, exc = self.run_diag(diag_table())
        self.assertEqual(len(got), 1)
        text = got[0]
        self.assert_no_fragments(text, DIAG_NAMES + DIAG_COUNTS)
        self.assertFalse(themes.privacy_scan.find_in_bytes(text.encode()))
        d = json.loads(text.split(": ", 1)[1])
        self.assertEqual((d["rows"], d["column_count_distribution"]), (7, {"2": 7}))
        self.assertEqual(d["first_row_numeric_columns"], 1)
        c0, c1 = d["columns"]
        self.assertEqual((c0["theme_name_match"], c0["theme_name_nonmatch"]), (1, 6))
        self.assertEqual(c0["nonmatch_values_with"],
                         {"upper": 6, "lower": 1, "underscore": 4, "symbol": 1, "space": 1,
                          "non_ascii": 1, "digit": 1})
        self.assertEqual(c0["nonmatch_chars"]["lower"], 3)
        self.assertEqual((c0["nonmatch_first_char_not_upper"], c0["nonmatch_too_long"]), (2, 1))
        # 軽-5：件数の欄らしい欄は values と ascii_digits_only だけ（digit などの数を出さない）
        self.assertEqual(c1, {"count_like": True, "values": 7, "ascii_digits_only": 6})
        self.assertFalse(c0["count_like"])
        # 失敗の行の reason は今までどおり。ファイルは書かない
        lines = [json.loads(l) for l in self.written()[themes.MANIFEST_NAME].splitlines()]
        self.assertEqual([l["kind"] for l in lines], ["attempt", "fetch", "failed"])
        self.assertEqual(lines[2], {"at": "2026-10-08T01:02:03Z", "kind": "failed",
                                    "reason": "ThemesError", "stage": "shape"})
        self.assertEqual(set(self.written()), {themes.MANIFEST_NAME})
        self.assert_no_fragments(self.written()[themes.MANIFEST_NAME].decode(), DIAG_NAMES)

    def test_header_shape_failure_also_emits(self):
        body = tsv(["THEME", "COUNT"], [["ZQXJ_Wvkq", "1"], ["ZQXJ_OK", "2"]])
        got, _e = self.run_diag(body)
        self.assertEqual(len(got), 1)
        self.assert_no_fragments(got[0], ["ZQXJ_Wvkq", "ZQXJ_OK"])

    def test_no_diagnosis_for_network_failure(self):
        got, _e = self.run_diag(GOOD, status=503)
        self.assertEqual(got, [])

    def test_failed_line_stage(self):
        """中-3：failed の行に止まった段（stage）を固定の語で書く。"""
        cases = [("fetch", GOOD, 503), ("read", b"\xff\xfe broken", 200),
                 ("shape", diag_table(), 200),
                 ("write", GOOD.replace(b"Alpha desc", b"see a" + b"@" + b"b.org"), 200)]
        for stage, body, status in cases:
            with self.subTest(stage):
                self.fresh()
                self.run_diag(body, status)
                lines = [json.loads(l) for l in self.written()[themes.MANIFEST_NAME].splitlines()]
                self.assertEqual(sorted(lines[-1]), ["at", "kind", "reason", "stage"])
                self.assertEqual((lines[-1]["kind"], lines[-1]["stage"], lines[-1]["reason"]),
                                 ("failed", stage, "ThemesError"))
                self.assertIn(lines[-1]["stage"], themes.FAILED_STAGES)
        self.assertEqual(themes.FAILED_STAGES, ("fetch", "read", "shape", "write"))

    def test_diagnosis_failure_still_writes_failed_line(self):
        """軽-8：診断が落ちても failed の行を書き、もとの ThemesError で止まる。"""
        def boom(sheets):
            raise RuntimeError("x")
        with mock.patch.object(themes, "diagnose_shape", boom):
            got, exc = self.run_diag(diag_table())
        self.assertIsInstance(exc, themes.ThemesError)
        self.assertEqual(got, ["診断を出せなかった"])
        lines = [json.loads(l) for l in self.written()[themes.MANIFEST_NAME].splitlines()]
        self.assertEqual((lines[-1]["kind"], lines[-1]["stage"]), ("failed", "shape"))

    def test_diag_sink_failure_still_writes_failed_line(self):
        self.tr = FakeTransport(diag_table())

        def sink(text):
            raise OSError("標準エラーに書けない")
        call = lambda: themes.run(root=self.root, home=self.home, url=URL, transport=self.tr,
                                  clock=lambda: 0.0, now=lambda: NOW, diag=sink)
        with mock.patch.object(themes, "_code_gate", lambda root: (CODE_SHA, b"", False)):
            with self.assertRaises(themes.AttemptRecorded):
                call()
        self.commit_all()
        with mock.patch.object(themes, "_code_gate", lambda root: (CODE_SHA, self.head, True)):
            with self.assertRaises(themes.ThemesError):
                call()
        lines = [json.loads(l) for l in self.written()[themes.MANIFEST_NAME].splitlines()]
        self.assertEqual([l["kind"] for l in lines], ["attempt", "fetch", "failed"])

    def fresh(self):
        shutil.rmtree(self.tmp, True)
        self.setUp()

    def test_many_columns_are_capped(self):
        rows = [["1"] + ["ZQXJ_Wvkq"] * 11]
        d = themes.diagnose_shape([("", rows)])
        self.assertEqual((len(d["columns"]), d["columns_not_shown"]),
                         (themes.DIAG_MAX_COLUMNS, 12 - themes.DIAG_MAX_COLUMNS))

    def test_default_goes_to_stderr_only(self):
        self.tr = FakeTransport(diag_table())
        call = lambda: themes.run(root=self.root, home=self.home, url=URL, transport=self.tr,
                                  clock=lambda: 0.0, now=lambda: NOW)
        with mock.patch.object(themes, "_code_gate", lambda root: (CODE_SHA, b"", False)):
            with self.assertRaises(themes.AttemptRecorded):
                call()
        self.commit_all()
        err, out = io.StringIO(), io.StringIO()
        with mock.patch.object(themes, "_code_gate", lambda root: (CODE_SHA, self.head, True)), \
                mock.patch("sys.stderr", err), mock.patch("sys.stdout", out):
            with self.assertRaises(themes.ThemesError):
                call()
        self.assertIn("診断", err.getvalue())
        self.assertEqual(out.getvalue(), "")
        self.assert_no_fragments(err.getvalue(), DIAG_NAMES + DIAG_COUNTS)


class TestMain(unittest.TestCase):
    """T-098：入口のコマンド（5章）。本物の run は呼ばない（差し替える）。"""

    ENTRY = {"kind": "result", "file_name": "gdelt-themes-20261008T010203Z.tsv",
             "sha256": "c" * 64, "rows": 3, "kept_columns": ["THEME"],
             "dropped_columns": ["column_B"], "headerless": True,
             "store_location": themes.STORE_LOCATION_NAME, "code_path": themes.CODE_REL,
             "code_sha256": CODE_SHA, "exclusion_rule_seq": 5}

    def call(self, argv, run):
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(themes, "run", run), \
                mock.patch("sys.stdout", out), mock.patch("sys.stderr", err):
            code = themes.main(argv)
        return code, out.getvalue(), err.getvalue()

    def test_arguments_refused_without_running(self):
        run = mock.Mock()
        code, _o, err = self.call(["--url", URL], run)
        self.assertEqual(code, themes.EXIT_USAGE)
        run.assert_not_called()
        self.assertIn("README.md 8章", err)

    def test_root_and_home_are_fixed(self):
        run = mock.Mock(return_value=dict(self.ENTRY))
        with mock.patch.dict(os.environ, {"HOME": "/nonexistent-home"}):
            code, _o, _e = self.call([], run)
        self.assertEqual(code, themes.EXIT_OK)
        kw = run.call_args.kwargs
        self.assertEqual(set(kw), {"root", "home"})       # url・transport・時計は既定のまま
        self.assertEqual(os.path.realpath(kw["root"]), os.path.realpath(PROJECT))
        import pwd
        self.assertEqual(kw["home"], pwd.getpwuid(os.getuid()).pw_dir)

    def test_first_phase_exit_code(self):
        def run(**kw):
            raise themes.AttemptRecorded("試行の行を書いた")
        code, out, err = self.call([], run)
        self.assertEqual((code, out), (themes.EXIT_ATTEMPT_RECORDED, ""))
        self.assertIn("1段目", err)

    def test_stopped_exit_code(self):
        for exc in (themes.ThemesError("x"), themes.ExclusionRulesNotSealed("y")):
            def run(**kw):
                raise exc
            code, out, _err = self.call([], run)
            self.assertEqual((code, out), (themes.EXIT_STOPPED, ""))

    def test_success_prints_summary_and_citation_only(self):
        code, out, _e = self.call([], mock.Mock(return_value=dict(self.ENTRY)))
        self.assertEqual(code, themes.EXIT_OK)
        for want in ("行数: 3", "sha256: " + "c" * 64, "headerless: true",
                     "捨てた欄: column_B", "seq 5", "https://www.gdeltproject.org/"):
            self.assertIn(want, out)
        self.assertFalse(themes.privacy_scan.find_in_bytes(out.encode()))

    def test_success_with_real_run_prints_no_theme_names(self):
        """差し替えの通信で本物の run を2段で動かし、表示にテーマの名前と件数が出ないこと。"""
        tmp = tempfile.mkdtemp(prefix="themes-main-")
        self.addCleanup(shutil.rmtree, tmp, True)
        root, home = os.path.join(tmp, "proj"), os.path.join(tmp, "home")
        os.makedirs(os.path.join(root, "data", "manifest"))
        os.makedirs(os.path.join(home, *themes.STORE_PARTS))
        real_run = themes.run
        tr = FakeTransport(GOOD)

        def run(**kw):
            return real_run(root=root, home=home, transport=tr, clock=lambda: 0.0,
                            now=lambda: NOW)
        mp = os.path.join(root, "data", "manifest", themes.MANIFEST_NAME)
        with mock.patch.object(themes, "_exclusion_gate", no_gate):
            with mock.patch.object(themes, "_code_gate", lambda r: (CODE_SHA, b"", False)):
                code1, out1, _e = self.call([], run)
            with open(mp, "rb") as f:
                head = f.read()
            with mock.patch.object(themes, "_code_gate", lambda r: (CODE_SHA, head, True)):
                code2, out2, _e = self.call([], run)
        self.assertEqual((code1, out1), (themes.EXIT_ATTEMPT_RECORDED, ""))
        self.assertEqual(code2, themes.EXIT_OK)
        self.assertEqual(len(tr.calls), 1)
        for v in ["QQ_ALPHA", "QQ_BETA_TWO", "QQ_7_GAMMA"] + COUNT_MARKS:
            self.assertNotIn(v, out2)

    def test_script_refuses_arguments_in_subprocess(self):
        """スクリプトとして動かしても、引数があれば関門にも通信にも進まない（終わり値 2）。"""
        import subprocess
        r = subprocess.run([sys.executable, "-B", os.path.join(SRC, "themes.py"), "x"],
                           capture_output=True, env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
        self.assertEqual(r.returncode, 2)
        self.assertEqual(r.stdout, b"")

    def test_no_stale_wording(self):
        with open(os.path.join(SRC, "themes.py"), encoding="utf-8") as f:
            src = f.read()
        self.assertNotIn("未定", src.split('if __name__ == "__main__":')[-1])
        self.assertNotIn("まだ一度も取得していない", src)


if __name__ == "__main__":
    unittest.main()
