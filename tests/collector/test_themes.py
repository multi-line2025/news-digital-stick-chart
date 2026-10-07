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
            mock.patch.object(socket, "getaddrinfo", _blocked)]


def setUpModule():
    for p in _patches:
        p.start()


EXCL_REF = {"seq": 7, "record_sha256": "e" * 64}


def no_gate(root):
    """0章の関門を通ったことにする（関門そのものは TestExclusionGate で確かめる）。"""
    return dict(EXCL_REF)


CODE_SHA = "ab" * 32


def no_code_gate(root):
    """0.1章のコードの関門を通ったことにする（関門そのものは TestCodeGate で確かめる）。
    返り値の2つ目は HEAD のマニフェスト（空）。"""
    return CODE_SHA, b""


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
        sha, head = self.mod._code_gate(self.root)
        self.assertEqual((sha, head), (self.mod.code_sha256(), b""))

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

    def test_attempt_line_deleted_after_commit_stops(self):
        """差し戻し2回目 軽-1：試行の行をコミットしたあと、作業ツリーから消しても2回目はできない。"""
        os.makedirs(os.path.join(self.root, "data", "manifest"))
        home = os.path.join(self.tmp, "home")
        os.makedirs(os.path.join(home, *themes.STORE_PARTS))
        gate = mock.patch.object(self.mod, "_exclusion_gate", no_gate)
        gate.start()
        self.addCleanup(gate.stop)
        tr = FakeTransport(GOOD, status=503)
        with self.assertRaises(self.mod.ThemesError):
            self.mod.run(root=self.root, home=home, transport=tr, clock=lambda: 0.0,
                         now=lambda: NOW)
        self.assertEqual(len(tr.calls), 1)
        mp = os.path.join(self.root, "data", "manifest", themes.MANIFEST_NAME)
        with open(mp, "rb") as f:
            line = json.loads(f.read())
        self.assertEqual((line["kind"], line["code_sha256"]), ("attempt", self.mod.code_sha256()))
        self.taf.git(self.root, "add", "data/manifest")
        self.taf.git(self.root, "commit", "-q", "-m", "試行の行")
        open(mp, "w").close()                          # コミットのあとで作業ツリーから消す
        tr2 = FakeTransport(GOOD)
        with self.assertRaisesRegex(self.mod.ThemesError, "既に試みた"):
            self.mod.run(root=self.root, home=home, transport=tr2, clock=lambda: 0.0,
                         now=lambda: NOW)
        self.assertEqual(tr2.calls, [])

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
        return themes.run(root=self.root, home=self.home, transport=self.tr,
                          clock=lambda: 0.0, now=lambda: NOW)

    def test_kind_undecided_stops_before_network(self):
        """今（T-021）は封印係の kind が未定なので、関門が必ず止まる。"""
        self.assertIsNone(themes.EXCLUSION_RULE_KIND)
        with self.assertRaisesRegex(themes.ExclusionRulesNotSealed, "まだ決まっていない"):
            self.run_themes()
        self.assertEqual(self.tr.calls, [])
        self.assertEqual(self.written(), [])

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
        load.assert_called_once_with(root or self.root)
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
        self.assertTrue(lines[2].startswith("sha_code, head_manifest = _code_gate(root)"),
                        lines[:4])
        self.assertTrue(lines[3].startswith("excl = _exclusion_gate(root)"), lines[:4])


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
        e = themes.run(root=root, home=home, url=URL, transport=FakeTransport(body),
                       clock=lambda: 0.0, now=lambda: NOW)
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

    def run_themes(self, body, url=URL, status=200):
        self.tr = FakeTransport(body, status)
        return themes.run(root=self.root, home=self.home, url=url, transport=self.tr,
                          clock=lambda: 0.0, now=lambda: NOW)

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
        """通信のあとで止まったとき：試行の行だけが残り、区分表の本体は書かれない。"""
        files = self.written()
        self.assertEqual(sorted(files), [themes.MANIFEST_NAME])
        lines = [json.loads(l) for l in files[themes.MANIFEST_NAME].splitlines()]
        self.assertEqual([l["kind"] for l in lines], ["attempt"])
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
        """差し戻し1回目 中3：失敗しても成功しても、2回目は通信せずに止まる。"""
        with self.assertRaises(themes.ThemesError):
            self.run_themes(GOOD, status=503)
        with self.assertRaisesRegex(themes.ThemesError, "既に試みた"):
            self.run_themes(GOOD)
        self.assertEqual(self.tr.calls, [])
        self.attempt_only()
        self.fresh()
        e = self.run_themes(GOOD)
        self.assertEqual(e["kind"], "result")
        with self.assertRaisesRegex(themes.ThemesError, "既に試みた"):
            self.run_themes(GOOD)
        self.assertEqual(self.tr.calls, [])
        lines = [json.loads(l) for l in self.written()[themes.MANIFEST_NAME].splitlines()]
        self.assertEqual([l["kind"] for l in lines], ["attempt", "result"])
        self.assertEqual(lines[1]["attempted_at"], lines[0]["attempted_at"])
        self.assertEqual(lines[1]["code_sha256"], CODE_SHA)

    def test_emptied_uncommitted_manifest_stops(self):
        """差し戻し2回目 軽-1（監査の再現 exp_th2）：コミット前に試行の行を消して空にしても止まる。"""
        with self.assertRaises(themes.ThemesError):
            self.run_themes(GOOD, status=503)
        open(os.path.join(self.root, "data", "manifest", themes.MANIFEST_NAME), "w").close()
        with self.assertRaisesRegex(themes.ThemesError, "既に試みた"):
            self.run_themes(GOOD)
        self.assertEqual(self.tr.calls, [])

    def test_gate_failure_writes_nothing(self):
        def stop(root):
            raise themes.ThemesError("見本")
        with mock.patch.object(themes, "_code_gate", stop):
            with self.assertRaises(themes.ThemesError):
                self.run_themes(GOOD)
        self.assertEqual(self.written(), {})
        self.assertEqual(self.tr.calls, [])

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


if __name__ == "__main__":
    unittest.main()
