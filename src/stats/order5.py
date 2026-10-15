#!/usr/bin/env python3
"""順番5：タグの一覧の結果（T-109）。文書は docs/stats/order5-tag-list.md。

封じた決まり（tags-naive.md 370行・423〜428行・334〜342行、seal-order1.md 143行、counting.md 85・125・259・261・
279行、missing-days-method.md 6章）を、封じたコードで当てはめて、順番5の記録に入れる中身（JSON）を作る。
新しい決まりは足さない。封印はしない（封印係が行う）。

入力（どれも照らしてから使う）
- 正式な run の day の行：src/collector/gkg.py の official_day_records() だけ（gkg-run-result の関門。seq 12）。
- 欠けた日：順番4の記録（seq 15）の一覧。一覧のバイト列の sha256 を記録の list_sha256 と PINS と照らす。
  数え直さない（missing-days-method.md 6章）。
- 区分表：data/manifest/gdelt-themes.jsonl の result の行が指すファイル。sha256 を result の行と PINS と照らす。
- コード：periods.py・exclusion.py・tagrules.py・counting.py は、ファイルを1回だけ読み、そのバイト列の sha256 を
  確かめ、同じバイト列を compile して使う（T-096 と同じ形。_load_verified）。値は封印の記録（seq 1・5・6）と照らす。
  比べる版（1cb463a・0e14f3b・247fc1d の tagrules.py）は git show で取り出し、sha256 を照らしてから使う。
- 日の集計：day の行の file_name のファイルだけを開き、sha256 を day の行と照らす。

出力は三つの JSON（UTF-8、sort_keys、区切りは "," と ":"、末尾に改行1つ）
- main：Git に入れて封印する本体。正式な一覧（C7・今の版・オーナーの選択）、各候補の要約、すべて有効の設定と
  1cb463a の版との比較の要約、欄の手厚さ、区分表の数、欠けた日、B1〜B5、参照、入力のハッシュ、引用、
  Git の外の二つのファイルの sha256。
- detail（Git の外）：正式・すべて有効・1cb463a の版の build_tag_list() の出力の全体と、候補ごとの一覧。
- extra（Git の外）：0e14f3b と 247fc1d の版の結果（tags-naive.md 426行。封印の対象にしない）。
入るのはテーマの名前と数と決まった語だけ（キーの許可リストとメールアドレスの形の検査で確かめる）。

流し方（docs/stats/order5-tag-list.md 4章）：手で流さない。封印係の入口の中で、HEAD の版を空のフォルダに
書き出し、そこで python -I -B -X pycache_prefix=<空のフォルダ> で流し、書いてコミットするまで結果を表示しない。
  python -I -B -X pycache_prefix=<空> src/stats/order5.py --store <日の集計の置き場所> \
      --themes-store <区分表の置き場所> --out-dir <書き出すディレクトリ> --repo <本体のリポジトリ>
  標準出力には、書いたファイルの名前と sha256 だけを出す。終わり値：0 できた、3 C7 で止まった（main だけ書く）、
  1 照合・入力・書き出しで止まった（本来の名前のファイルは書かない）、2 引数か書き出す先が違う。
"""

import array
import collections.abc
import datetime
import fractions
import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(os.path.dirname(HERE))
GKG_PATH = os.path.join(PROJECT, "src", "collector", "gkg.py")

_LOADED_SHA = {}


def _exec_bytes(name, path, data, deps=()):
    """バイト列 data を compile/exec してモジュールにする。deps は exec のあいだだけ sys.modules に置く。"""
    import types
    mod = types.ModuleType(name)
    mod.__file__ = path
    saved = {n: sys.modules.get(n) for n, _m in deps}
    try:
        for n, m in deps:
            sys.modules[n] = m
        exec(compile(data, path, "exec", dont_inherit=True), mod.__dict__)
    finally:
        for n, old in saved.items():
            if old is None:
                sys.modules.pop(n, None)
            else:
                sys.modules[n] = old
    return mod


def _load_verified(name, rel, deps=()):
    """src/stats のファイルを1回だけ読み、そのバイト列の sha256 を記録し、同じバイト列を使う（T-096 と同じ形）。
    import の仕組みを通さないので、__pycache__ の .pyc は読まない。"""
    path = os.path.join(PROJECT, *rel.split("/"))
    with open(path, "rb") as f:
        data = f.read()
    _LOADED_SHA[rel] = hashlib.sha256(data).hexdigest()
    return _exec_bytes(name, path, data, deps)


periods = _load_verified("periods", "src/stats/periods.py")
exclusion = _load_verified("exclusion", "src/stats/exclusion.py")
tagrules = _load_verified("tagrules", "src/stats/tagrules.py", deps=(("exclusion", exclusion),))
counting = _load_verified("counting", "src/stats/counting.py")

# 出力の label。文書（docs/stats/order5-tag-list.md）の版と1対1にする（テストで照合する）。
LABEL = "order5-tag-list-v2"

PERIODS_SHA256 = "81de229d065196a26e15d90c5a80eb1043ca534a6eaf66cdebd36285ae087605"
EXCLUSION_SHA256 = "22bc0ed138a42b95c36797bbe5b41163c871af14f32be590dafde20fe16fdd1d"
TAGRULES_SHA256 = "63b0e005ce85344675651264b4a14453a167a28d56d3333a7503b55db04218ee"
COUNTING_SHA256 = "6f25985b21cd8ac93680b81308f3d1860b4ae6496577e10141d1e17ecf8c9fd3"
TAGRULES_1CB463A_SHA256 = "f7c325cb21bcf39c42e6d785deacbe47eacec7fb2834d2927634e446b62ce57a"

# 照らす値の出どころ：(名前, sha256, ((seq, kind, 欄), ...))。欄は、記録の targets の role（targets:<role>）、
# stats-order1 の中身の targets の name（order1:targets）、stats-order1b の中身の files（files）
SEALED_CODE = (
    ("src/stats/periods.py", PERIODS_SHA256, ((1, "periods", "targets:code"),)),
    ("src/stats/exclusion.py", EXCLUSION_SHA256, ((5, "stats-order1", "order1:targets"),)),
    ("src/stats/tagrules.py", TAGRULES_SHA256, ((5, "stats-order1", "order1:targets"),)),
    ("src/stats/counting.py", COUNTING_SHA256, ((6, "stats-order1b", "files"),)),
    ("1cb463a:src/stats/tagrules.py", TAGRULES_1CB463A_SHA256, ((5, "stats-order1", "order1:targets"),)),
)
_MODULES = {"src/stats/periods.py": periods, "src/stats/exclusion.py": exclusion,
            "src/stats/tagrules.py": tagrules, "src/stats/counting.py": counting}

# 比べる版（tags-naive.md 423〜428行）：(名前, commit, sha256, 封印の対象か)。1cb463a は seq 5 の対象。
# 0e14f3b と 247fc1d は封印の対象ではない（426行）。値は git show の出力のバイト列の sha256。
OLD_VERSIONS = (
    ("1cb463a", "1cb463acfcf15ba315e6c454625ad681e86bbc2a", TAGRULES_1CB463A_SHA256, True),
    ("0e14f3b", "0e14f3b36f012098fc53d9456e6c4d9d5231e43b",
     "8ed1613885d7e64ebdca47c97c4781fa3b42f735b37e91901321a38ef8328956", False),
    ("247fc1d", "247fc1de62e32322207f9576480deb9536eb8dd5",
     "3a688f94c1aff8e67a2d8e94072e29569f15699be2f569b7840dea22635a70ba", False),
)
OLD_VERSION_PATH = "src/stats/tagrules.py"

# 記録と取得の結果から写した値（T-109 の割り振り。reviews/T-105.md・data/manifest/gdelt-themes.jsonl）
PINS = {
    "order4_seq": 15,
    "order4_list_sha256": "6343bcc7d1ad2b406cdb2a5013b029a750c476f93098715f1a822831f283a35d",
    "themes_table_sha256": "21aef57175e66e3cb9e0ba574d0b7dc628f8f23f7ecb7a29498ad67b50ca9203",
    "themes_table_rows": 59315,
}

# 区分表の名前の形（src/collector/themes.py の THEME_NAME_RE。T-107 で広げた形）。テストで themes.py と照合する。
TABLE_NAME_RE = re.compile(r"\A[A-Z][\x21-\x60\x7B-\x7E]{0,159}\Z")
TABLE_HEADER = "THEME"

BLOCK_NAME = "method"
ENTRY = "src/collector/gkg.py official_day_records()"
OFFICIAL_SETTING = "owner_choice"
REF_NOTE = "比べるための参考で、正式ではない"
CITATION = (
    "Data: The GDELT Project (https://www.gdeltproject.org/). This project is not affiliated with or "
    "endorsed by the GDELT Project.",
    "データ出典：GDELT Project（https://www.gdeltproject.org/）。本プロジェクトは GDELT Project と提携・承認の"
    "関係にありません。",
)
LIMITS = (
    "区分表は名前の欄だけを取得した（説明の欄は無い）。除外の規則は名前の欄だけで照合した（tags-naive.md 159・224行）。",
    "記号（下線以外）を含むテーマ名は、区分表には入るが、取得のときの THEME_RE（src/collector/gkg.py。"
    "counting.THEME_NAME_RE と同じ形）に合わないので日の集計に数えられていない。そのため件数は0で、一覧に入らない"
    "（themes_table.names_not_in_day_aggregate_form。T-107 の監査の中-1）。",
    "翻訳の印の付いた組の記事は数えていない（外国語の報道は数えていない。counting.md 98行）。",
    "V1 と V2 で名前が違う同じテーマは、別々のテーマとして数える（counting.md 104行）。",
    "欠けた日は順番4の一覧（seq 15）だけで決め、数え直していない（missing-days-method.md 6章）。",
    "手法を作る期間の全体にわたって存在しないテーマは扱わない（CLAUDE.md）。区分表には、この期間のあとに生まれた"
    "テーマの名前も入りうるが、名前だけでは一覧に入らない。",
    "参考の基準の案 B1〜B5 の結果は、順番2の記録（試しの run の3日）から写した。手法を作る期間の全体では計算していない。",
    "数え方の候補の一覧に、作る人が検討して載せなかった案があるかは、記録からは確かめられない（seal-order1.md 164行）。",
)


class Order5Error(Exception):
    """入力・照合が決まりの前提に合わない。何も書かずに止まる。"""


_GKG = None


def _gkg():
    """src/collector/gkg.py を読み込む（1回だけ）。読むだけで、収集係のコードは変えない。"""
    global _GKG
    if _GKG is None:
        spec = importlib.util.spec_from_file_location("gkg_for_stats_order5", GKG_PATH)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _GKG = mod
    return _GKG


def _ledger():
    return _gkg()._load_sibling("themes")._import_ledger()


# ---------------------------------------------------------------------------
# コードの照合
# ---------------------------------------------------------------------------

def check_stats_code():
    """動いている periods・exclusion・tagrules・counting が src/stats のそのファイルから作ったもので、
    そのバイト列（_load_verified が読んで compile したもの）の sha256 が SEALED_CODE と同じか。"""
    out = {}
    for rel, want, _src in SEALED_CODE:
        if rel not in _MODULES:
            continue
        path = os.path.join(PROJECT, *rel.split("/"))
        if os.path.realpath(_MODULES[rel].__file__) != os.path.realpath(path):
            raise Order5Error("読み込んだモジュールが %s でない" % rel)
        if _LOADED_SHA.get(rel) != want:
            raise Order5Error("%s の sha256 が、封印の記録の値と違う" % rel)
        out[rel] = want
    if tagrules.exclusion is not exclusion:
        raise Order5Error("tagrules が、照合した exclusion を使っていない")
    return out


def _git_show(commit, path, repo=None):
    """git show <commit>:<path> の標準出力のバイト列。repo は git のリポジトリ（既定はこのファイルのプロジェクト）。
    封印係の入口は HEAD の版を .git の無い空のフォルダに書き出して流すので、本体のリポジトリを --repo で渡す。
    取り出したバイト列は OLD_VERSIONS の sha256 と照らすので、どのリポジトリから取っても結果は変わらない。"""
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env["GIT_NO_REPLACE_OBJECTS"] = "1"
    r = subprocess.run(["git", "-C", repo or PROJECT, "show", "%s:%s" % (commit, path)],
                       capture_output=True, env=env)
    if r.returncode != 0:
        raise Order5Error("git show %s:%s が失敗した" % (commit[:7], path))
    return r.stdout


def load_old_versions(show=None, repo=None):
    """比べる版の tagrules.py を取り出し、sha256 を OLD_VERSIONS と照らしてからモジュールにする。
    返り値：{名前: モジュール}。合わなければ何も読み込まずに止まる。"""
    show = show or (lambda c, p: _git_show(c, p, repo))
    out = {}
    for name, commit, want, _sealed in OLD_VERSIONS:
        data = show(commit, OLD_VERSION_PATH)
        if hashlib.sha256(data).hexdigest() != want:
            raise Order5Error("%s の版の tagrules.py の sha256 が、決めた値と違う" % name)
        out[name] = _exec_bytes("tagrules_%s" % name, "%s:%s" % (commit, OLD_VERSION_PATH), data)
    return out


def check_sealed_code_in_ledger(records, read_json):
    """SEALED_CODE の値が、封印の記録の該当する欄と同じか。read_json(record, role) は記録の中身を返す。"""
    by_seq = {r.get("seq"): r for r in records}
    for rel, want, sources in SEALED_CODE:
        for seq, kind, field in sources:
            r = by_seq.get(seq)
            if r is None or r.get("kind") != kind:
                raise Order5Error("seq %d が %s の記録でない" % (seq, kind))
            if field.startswith("targets:"):
                role = field.split(":", 1)[1]
                got = [t.get("sha256") for t in r.get("targets", [])
                       if t.get("path") == rel and t.get("role") == role]
            elif field == "order1:targets":
                got = [t.get("sha256") for t in read_json(r, kind).get("targets", []) if t.get("name") == rel]
            elif field == "files":
                got = [f.get("sha256") for f in read_json(r, kind).get("files", []) if f.get("path") == rel]
            else:
                raise Order5Error("知らない欄 %s" % field)
            if got != [want]:
                raise Order5Error("%s の sha256 が、seq %d（%s）の %s の値と違う" % (rel, seq, kind, field))


# ---------------------------------------------------------------------------
# 封印の記録から読むもの（参照・欠けた日・参考の基準の結果）
# ---------------------------------------------------------------------------

def _record_ref(ledger, rec):
    return {"seq": rec["seq"], "record_sha256": ledger.sha256_hex(ledger.canonical_line(rec))}


def _one_of_kind(records, kind):
    got = [r for r in records if r["kind"] == kind]
    if len(got) != 1:
        raise Order5Error("封印の記録に %s の記録が %d 件ある（1件のときだけ読む）" % (kind, len(got)))
    return got[0]


def _by_ref(ledger, records, ref, kind, what):
    if not isinstance(ref, dict):
        raise Order5Error("%s の参照の形が違う" % what)
    got = [r for r in records if r["seq"] == ref.get("seq")]
    if len(got) != 1 or got[0]["kind"] != kind or _record_ref(ledger, got[0]) != {
            "seq": ref.get("seq"), "record_sha256": ref.get("record_sha256")}:
        raise Order5Error("%s の参照（seq %r）が、封印の記録の %s の行と合わない" % (what, ref.get("seq"), kind))
    return got[0]


def order4_list_bytes(lst):
    """順番4の一覧のバイト列（missing_days.canonical_bytes・ledger.order4_list_bytes と同じ形）。"""
    return (json.dumps(lst, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")


def context_from_records(ledger, records, read_json):
    """封印の記録から、参照（順番1・1b・2・3・4）、欠けた日の一覧、参考の基準の結果を読む。

    - 順番3（stats-order3）はちょうど1件。その ref_order1・ref_1b・ref_order2 の参照を、記録の行と照らす。
    - 順番1 はちょうど1件で、順番3の参照と同じ。順番1b は seq が最も大きいもので、順番3の参照と同じ。
    - 順番1b の候補と基準の案の識別子が、counting の CANDIDATE_IDS・CRITERIA_IDS と同じ。正式な候補は C7。
    - 順番4 はちょうど1件で seq が PINS と同じ。順番3より後。一覧のバイト列の sha256 が list_sha256 と PINS と同じ。
    - 順番2 は順番3が参照したもの（seq 10）。参考の基準の結果（B1〜B5）を写す。
    """
    o3 = _one_of_kind(records, ledger.ORDER3_KIND)
    d3 = read_json(o3, ledger.ORDER3_KIND)
    o1 = _one_of_kind(records, ledger.ORDER1_KIND)
    if _by_ref(ledger, records, d3.get("ref_order1"), ledger.ORDER1_KIND, "順番3の ref_order1") is not o1:
        raise Order5Error("順番3の ref_order1 が、順番1の記録と違う")
    b1 = [r for r in records if r["kind"] == ledger.ORDER1B_KIND]
    if not b1:
        raise Order5Error("順番1b の記録が無い")
    o1b = max(b1, key=lambda r: r["seq"])
    if _by_ref(ledger, records, d3.get("ref_1b"), ledger.ORDER1B_KIND, "順番3の ref_1b") is not o1b:
        raise Order5Error("順番3の ref_1b が、seq の最も大きい順番1b の記録と違う")
    o2 = _by_ref(ledger, records, d3.get("ref_order2"), ledger.ORDER2_KIND, "順番3の ref_order2")
    d1b = read_json(o1b, ledger.ORDER1B_KIND)
    c = d1b.get("counting") or {}
    if (list(c.get("candidate_ids") or []) != list(counting.CANDIDATE_IDS)
            or list(c.get("criteria_ids") or []) != list(counting.CRITERIA_IDS)
            or c.get("official_candidate") != counting.OFFICIAL_CANDIDATE
            or counting.OFFICIAL_CANDIDATE != "C7"):
        raise Order5Error("順番1b の記録の候補・基準の案・正式な候補が、counting.py と合わない")
    o4 = _one_of_kind(records, ledger.ORDER4_KIND)
    if o4["seq"] != PINS["order4_seq"] or o4["seq"] < o3["seq"]:
        raise Order5Error("順番4の記録の seq（%d）が決めた値と違うか、順番3より前" % o4["seq"])
    d4 = read_json(o4, ledger.ORDER4_KIND)
    lst = d4.get("list")
    if not isinstance(lst, dict):
        raise Order5Error("順番4の記録に一覧が無い")
    sha = hashlib.sha256(order4_list_bytes(lst)).hexdigest()
    if sha != d4.get("list_sha256") or sha != PINS["order4_list_sha256"]:
        raise Order5Error("順番4の一覧の sha256 が、記録の list_sha256 か決めた値と違う")
    d2 = read_json(o2, ledger.ORDER2_KIND)
    if d2.get("ref_1b_seq") != o1b["seq"]:
        raise Order5Error("順番2の記録の ref_1b_seq が、参照する順番1b と違う")
    out2 = d2.get("counting_output") or {}
    crit = None
    if out2.get("status") == "decided":
        res = out2.get("results") or {}
        if sorted(res) != sorted(counting.CRITERIA_IDS) or any(v.get("official") is not False
                                                               for v in res.values()):
            raise Order5Error("順番2の記録の参考の基準の結果が、基準の案の一覧と合わない")
        crit = {"input_mode": out2.get("input_mode"), "input_run_id": out2.get("input_run_id"),
                "input_days": [x.get("day") for x in out2.get("inputs") or []], "results": res}
    refs = {
        "order1": _record_ref(ledger, o1),
        "order1b": _record_ref(ledger, o1b),
        "order2": _record_ref(ledger, o2),
        "order3": _record_ref(ledger, o3),
        "order4": dict(_record_ref(ledger, o4), list_sha256=sha),
    }
    return {"refs": refs, "order4_list": lst, "criteria": crit, "order2_status": out2.get("status")}


def sealed_context(run_id):
    """関門を通ったあとで、封印の記録を検証して読み、コードの値を照らし、参照と一覧を返す。"""
    ledger = _ledger()
    rec = ledger.require_gkg_run_result("official", run_id)
    root = ledger._gate_root()
    _data, records = ledger._load_for_gate(root)
    same = [r for r in records if r["seq"] == rec["seq"]]
    if len(same) != 1 or ledger.canonical_line(same[0]) != ledger.canonical_line(rec):
        raise Order5Error("関門の返した gkg-run-result の記録が、封印の記録の中に無い")

    def read(r, role):
        return ledger.read_target_json(root, r, role)
    check_sealed_code_in_ledger(records, read)
    doc = read(rec, ledger.GKG_RESULT_KIND)
    if doc.get("mode") != "official" or doc.get("run_id") != run_id:
        raise Order5Error("gkg-run-result の記録が、この run のものでない")
    ctx = context_from_records(ledger, records, read)
    ctx["refs"]["gkg_run_result"] = _record_ref(ledger, rec)
    ctx["gkg"] = {"gkg_run_result_seq": rec["seq"],
                  "gkg_run_result_record_sha256": ctx["refs"]["gkg_run_result"]["record_sha256"],
                  "manifest_path": doc["manifest_path"], "manifest_lines": doc["manifest_lines"],
                  "manifest_sha256": doc["manifest_sha256"]}
    ctx["root"] = root
    ctx["records"] = records
    return ctx


# ---------------------------------------------------------------------------
# 区分表
# ---------------------------------------------------------------------------

def themes_result_row(ledger, records, manifest_bytes):
    """区分表のマニフェストを封印係の照合（check_themes_manifest_refs）に通し、最後の result の行を返す。"""
    if manifest_bytes is None:
        raise Order5Error("区分表のマニフェストが無い")
    try:
        ledger.check_themes_manifest_refs(records, manifest_bytes)
    except ledger.LedgerError as e:
        raise Order5Error("区分表のマニフェストが照合に通らない：%s" % e) from None
    rows = [json.loads(x.decode("utf-8")) for x in manifest_bytes.split(b"\n") if x.strip()]
    results = [r for r in rows if r.get("kind") == "result"]
    if len(results) != 1 or rows[-1] is not results[0]:
        raise Order5Error("区分表のマニフェストの result の行が、最後の1行でない")
    r = results[0]
    if r.get("sha256") != PINS["themes_table_sha256"] or r.get("rows") != PINS["themes_table_rows"]:
        raise Order5Error("区分表の result の行の sha256 か行数が、決めた値と違う")
    if r.get("kept_columns") != [TABLE_HEADER] or not ledger.THEMES_FILE_RE.fullmatch(str(r.get("file_name"))):
        raise Order5Error("区分表の result の行の残した欄かファイルの名前の形が違う")
    return r


def parse_themes_table(data, result_row):
    """区分表のファイル（themes.build_output の形）を読む。sha256・頭の行・行数・名前の形を照らす。
    返り値：{"names": 名前の一覧（行の順）, "unique": 名前の集合}。"""
    if hashlib.sha256(data).hexdigest() != result_row["sha256"]:
        raise Order5Error("区分表のファイルの sha256 が、result の行と一致しない")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        raise Order5Error("区分表のファイルが UTF-8 でない") from None
    if not text.endswith("\n"):
        raise Order5Error("区分表のファイルの最後に改行が無い")
    lines = text[:-1].split("\n")
    if lines[0] != TABLE_HEADER:
        raise Order5Error("区分表のファイルの頭の行が %s でない" % TABLE_HEADER)
    names = lines[1:]
    if len(names) != result_row["rows"]:
        raise Order5Error("区分表のファイルの行数が、result の行と違う")
    for n in names:
        if not TABLE_NAME_RE.fullmatch(n):
            raise Order5Error("区分表のファイルに、名前の形に合わない行がある")
    return {"names": names, "unique": set(names)}


def themes_table_summary(table, result_row, data_themes):
    """出力の themes_table。T-107 の監査の中-1 の数（日の集計の名前の形に合わない名前）を入れる。"""
    old_re = counting.THEME_NAME_RE
    outside = sorted(n for n in table["unique"] if not old_re.fullmatch(n))
    return {
        "file_name": result_row["file_name"],
        "sha256": result_row["sha256"],
        "rows": result_row["rows"],
        "kept_columns": list(result_row["kept_columns"]),
        "headerless": result_row.get("headerless"),
        "description_column": False,
        "unique_names": len(table["unique"]),
        "duplicate_rows": len(table["names"]) - len(table["unique"]),
        "names_not_in_day_aggregate_form": {"count": len(outside), "names": outside},
        "official_data_themes_not_in_table": len(set(data_themes) - table["unique"]),
    }


# ---------------------------------------------------------------------------
# day の行と日の集計
# ---------------------------------------------------------------------------

def method_block():
    """手法を作る期間の区画 (start, end)。periods と gkg の両方と照合する。"""
    blocks = [b for b in periods.FROZEN_BLOCKS if b[0] == BLOCK_NAME]
    if len(blocks) != 1:
        raise Order5Error("periods.FROZEN_BLOCKS に手法を作る期間の区画が1つでない")
    _n, start, end = blocks[0][:3]
    g = _gkg()
    if (g.DATA_START, g.METHOD_BLOCK_END) != (start, end):
        raise Order5Error("gkg の区画が periods の区画と違う")
    return start, end


def _days(start, end):
    out, d = [], start
    while d <= end:
        out.append(d)
        d += datetime.timedelta(days=1)
    return out


def check_rows(day_records, block):
    """day の行を検査し、(区画の日の一覧（date）, {日の文字列: 行}, run_id) を返す。日の集計はまだ開かない。"""
    want = _days(*block)
    rows, run_ids = {}, set()
    for r in day_records:
        if not isinstance(r, dict) or r.get("kind") != "day" or r.get("mode") != "official":
            raise Order5Error("正式な run の day の行でないものがある")
        d = r.get("day")
        if d in rows:
            raise Order5Error("同じ日（%s）の day の行が二つある" % d)
        rows[d] = r
        run_ids.add(r.get("run_id"))
    if len(run_ids) != 1:
        raise Order5Error("day の行の run_id が1つでない")
    run_id = run_ids.pop()
    keys = [d.isoformat() for d in want]
    if set(rows) != set(keys):
        raise Order5Error("day の行の日が、区画の日とちょうど同じでない")
    for d in keys:
        r = rows[d]
        if r.get("file_name") != counting.day_file_name(counting.OFFICIAL_MODE, run_id, d):
            raise Order5Error("%s：day の行の file_name が、決まった名前と違う" % d)
        sha = r.get("sha256")
        if not (isinstance(sha, str) and re.fullmatch(r"[0-9a-f]{64}", sha)):
            raise Order5Error("%s：day の行の sha256 の形が違う" % d)
    return want, rows, run_id


def missing_from_order4(lst, block, run_id, gkg_refs):
    """順番4の一覧から欠けた日の集合（date）と、日ごとの C7 の分母を取る。一覧が、この区画・この run・
    この gkg-run-result のものであることを照らす。欠けた日は数え直さない。"""
    start, end = block
    if lst.get("block") != {"name": BLOCK_NAME, "start": start.isoformat(), "end": end.isoformat()}:
        raise Order5Error("順番4の一覧の区画が違う")
    inp = lst.get("input") or {}
    if inp.get("run_id") != run_id:
        raise Order5Error("順番4の一覧の run_id が、正式な run と違う")
    for k in ("gkg_run_result_seq", "gkg_run_result_record_sha256", "manifest_path", "manifest_lines",
              "manifest_sha256"):
        if inp.get(k) != gkg_refs[k]:
            raise Order5Error("順番4の一覧の %s が、関門を通った gkg-run-result と違う" % k)
    days = [m.get("day") for m in lst.get("missing_days") or []]
    if len(days) != lst.get("missing_count") or len(set(days)) != len(days):
        raise Order5Error("順番4の一覧の missing_days と missing_count が合わない")
    out = set()
    for d in days:
        try:
            x = datetime.date.fromisoformat(d)
        except (TypeError, ValueError):
            raise Order5Error("順番4の一覧の日の形が違う") from None
        if not (start <= x <= end):
            raise Order5Error("順番4の一覧に区画の外の日がある")
        out.add(x)
    denom = lst.get("c7_denominator_by_day")
    if not isinstance(denom, dict) or set(denom) != {d.isoformat() for d in _days(start, end)}:
        raise Order5Error("順番4の一覧の c7_denominator_by_day が区画の日とそろわない")
    return out, denom


class _Entry:
    __slots__ = ("ix", "vals")

    def __init__(self, ncol):
        self.ix = array.array("H")
        self.vals = [array.array("I") for _ in range(ncol)]


class DaySeries(collections.abc.Mapping):
    """一つのテーマ・一つの欄の {日付: 件数}（件数 0 の日は入れない。counting.candidate_counts と同じ）。
    中身は store の配列から、触れたときだけ dict にする（一度に一つだけ持つ）。build_tag_list の引数の形。"""

    __slots__ = ("_store", "_entry", "_k")

    def __init__(self, store, entry, k):
        self._store, self._entry, self._k = store, entry, k

    def _d(self):
        c = self._store._cache
        if c[0] is not self:
            dates = self._store.dates
            c[1] = {dates[i]: v for i, v in zip(self._entry.ix, self._entry.vals[self._k]) if v}
            c[0] = self
        return c[1]

    def __getitem__(self, x):
        return self._d()[x]

    def __iter__(self):
        return iter(self._d())

    def __len__(self):
        return len(self._d())

    def __contains__(self, x):
        return x in self._d()

    def get(self, x, default=None):
        return self._d().get(x, default)

    def keys(self):
        return self._d().keys()

    def values(self):
        return self._d().values()

    def items(self):
        return self._d().items()


class DayStore:
    """日の集計から、7つの候補の分子（テーマごと・日ごと）と分母（日ごと）、欄の手厚さを集める。

    分子と分母は counting.candidate_counts(summary, 候補) の値だけを使う（数え方を新しく書かない）。
    分子の欄が同じ候補（C1 と C2 など）は、日ごとの分子が同じであることを確かめて、一度だけ持つ。"""

    def __init__(self, dates):
        self.dates = list(dates)
        self.index = {d: i for i, d in enumerate(self.dates)}
        self.cols = list(counting.COLUMNS)
        self.col_of = {cid: col for cid, col, _den in counting.CANDIDATES}
        self.den_of = {cid: den for cid, _col, den in counting.CANDIDATES}
        self.entries = {}
        self.totals = {cid: {} for cid in counting.CANDIDATE_IDS}
        self.coverage = {}
        self._cache = [None, None]

    def add(self, day, summary):
        i = self.index[day]
        by_col = {}
        for cid in counting.CANDIDATE_IDS:
            counts, total = counting.candidate_counts(summary, cid)
            col = self.col_of[cid]
            if col in by_col:
                if by_col[col] != counts:
                    raise Order5Error("%s：分子の欄が同じ候補の分子が違う" % day.isoformat())
            else:
                by_col[col] = counts
            self.totals[cid][day] = total
        names = set()
        for counts in by_col.values():
            names.update(counts)
        try:
            for name in names:
                e = self.entries.get(name)
                if e is None:
                    e = self.entries[name] = _Entry(len(self.cols))
                e.ix.append(i)
                for k, col in enumerate(self.cols):
                    e.vals[k].append(by_col.get(col, {}).get(name, 0))
        except OverflowError:
            raise Order5Error("%s：件数が持てる範囲を超える" % day.isoformat()) from None
        self.coverage[day] = counting.coverage([summary])

    def counts_for(self, cid):
        """build_tag_list の counts 引数（{テーマ名: DaySeries}）。その候補の分子が一度でも 0 でないテーマだけ。"""
        k = self.cols.index(self.col_of[cid])
        return {name: DaySeries(self, e, k) for name, e in sorted(self.entries.items()) if any(e.vals[k])}


def read_days(want, rows, read_day_file):
    """区画の各日の日の集計を開き、sha256 を day の行と照らし、DayStore に集める。返り値：(store, 入力の要約)。"""
    store = DayStore(want)
    lines = []
    for d in want:
        r = rows[d.isoformat()]
        data = read_day_file(r["file_name"])
        if hashlib.sha256(data).hexdigest() != r["sha256"]:
            raise Order5Error("%s：日の集計 %s の sha256 が、day の行と一致しない" % (d.isoformat(), r["file_name"]))
        summary = counting.parse_day(data, expect_day=d.isoformat(), expect_mode=counting.OFFICIAL_MODE)
        del data
        store.add(d, summary)
        del summary
        lines.append("%s\t%s\t%s\n" % (d.isoformat(), r["file_name"], r["sha256"]))
    digest = hashlib.sha256("".join(lines).encode("ascii")).hexdigest()
    return store, digest


# ---------------------------------------------------------------------------
# 決まりの当てはめ
# ---------------------------------------------------------------------------

def _frac(x):
    return "%d/%d" % (x.numerator, x.denominator)


def coverage_record(store, want, missing, block):
    """欄の手厚さ（counting.md 279行）：暦の四半期ごと（tagrules.quarters）と期間全体の、欠けた日でない日の合計。"""
    keys = ("docs_all_groups",) + tuple(sorted(counting.S_UNCOVERED.values()))

    def total(days):
        s = {k: 0 for k in keys}
        for d in days:
            for k in keys:
                s[k] += store.coverage[d][k]
        out = dict(s, usable_days=len(days))
        n = s["docs_all_groups"]
        out["ratios"] = {k: (_frac(fractions.Fraction(s[k], n)) if n else None) for k in keys[1:]}
        return out
    usable = [d for d in want if d not in missing]
    qs = []
    for i, (qa, qb) in enumerate(tagrules.quarters(*block)):
        q = total([d for d in usable if qa <= d <= qb])
        q.update(index=i, start=qa.isoformat(), end=qb.isoformat())
        qs.append(q)
    return {"quarters": qs, "total": total(usable)}


_RESULT_SCALARS = ("proposed_label", "block_start", "block_end", "usable_day_count", "quarters",
                   "quarters_without_usable_days", "n_med", "a", "a_float", "v_equals_a",
                   "enabled_optional_categories")


def official_summary(result):
    """main に入れる正式な一覧：build_tag_list() の出力から、テーマごとの行（themes）を除いたものと一覧、
    一覧に入らなかった理由の件数。テーマごとの行の全体は detail に入る（Git の外）。"""
    out = {k: result[k] for k in _RESULT_SCALARS if k in result}
    rows = result["themes"]
    out.update(tag_list=list(result["tag_list"]), tag_count=len(result["tag_list"]),
               reason_counts={"all_themes": len(rows),
                              "in_list": sum(1 for r in rows if r["in_list"]),
                              "not_present_throughout": sum(1 for r in rows if not r["present_throughout"]),
                              "mean_below_a": sum(1 for r in rows if not r["mean_ratio_at_least_a"]),
                              "excluded": sum(1 for r in rows if r["exclusion_matches"])})
    return out


def compare_summary(moved):
    """比較の要約：compare_lists() の出力（差のあるテーマの名前を含む）と、差の件数。"""
    return dict(moved, diff_count=len(moved["only_in_old"]) + len(moved["only_in_new"]),
                official=False, note=REF_NOTE)


def _summary(cid, status, result):
    col, den = counting.CANDIDATES[counting.CANDIDATE_IDS.index(cid)][1:]
    official = cid == counting.OFFICIAL_CANDIDATE
    out = {"id": cid, "official": official, "numerator_column": col, "denominator_kind": den,
           "status": status["status"], "reason": status["reason"], "zero_days": status["zero_days"],
           "note": None if official else REF_NOTE}
    if result is None:
        out.update(n_med=None, a=None, a_float=None, usable_day_count=None, tag_count=None)
    else:
        out.update(n_med=result["n_med"], a=result["a"], a_float=result["a_float"],
                   usable_day_count=result["usable_day_count"], tag_count=len(result["tag_list"]))
    return out


def build(day_records, block, read_day_file, ctx, table, result_row, versions):
    """順番5の中身を作る。返り値：(main, detail, extra)。C7 で止まったときは detail と extra は None。

    main：Git に入れて封印する本体（正式な一覧・各候補の要約・比較の要約・欄の手厚さ・区分表の数・欠けた日・
          B1〜B5・参照・入力のハッシュ・引用と、Git の外の二つのファイルの sha256）。
    detail：Git の外。正式・すべて有効・1cb463a の版の build_tag_list() の出力の全体と、候補ごとの一覧。
    extra：Git の外。0e14f3b・247fc1d の版の結果（tags-naive.md 426行。封印の対象にしない）。
    三つとも、作り終えてから check_public() を通す。一つでも通らなければ止まる（何も返さない）。"""
    want, rows, run_id = check_rows(day_records, block)
    missing, c7_by_day = missing_from_order4(ctx["order4_list"], block, run_id, ctx["gkg"])
    store, digest = read_days(want, rows, read_day_file)
    c7 = counting.OFFICIAL_CANDIDATE
    if any(store.totals[c7][d] != c7_by_day[d.isoformat()] for d in want):
        raise Order5Error("C7 の分母が、順番4の一覧の c7_denominator_by_day と違う（日の集計が変わった）")
    statuses = {cid: counting.order5_candidate_status(cid, store.totals[cid], missing, want)
                for cid in counting.CANDIDATE_IDS}
    start, end = block
    themes_arg = {n: None for n in sorted(table["unique"])}
    counts_c7 = store.counts_for(c7)
    base = {
        "label": LABEL,
        "block": {"name": BLOCK_NAME, "start": start.isoformat(), "end": end.isoformat()},
        "refs": dict(ctx["refs"]),
        "code": {
            "sealed": [{"name": rel, "sha256": sha, "sources": ["seq %d %s %s" % s for s in src]}
                       for rel, sha, src in SEALED_CODE],
            "versions": [{"name": n, "commit": c, "path": OLD_VERSION_PATH, "sha256": s, "sealed": sealed}
                         for n, c, s, sealed in OLD_VERSIONS],
        },
        "input": dict(ctx["gkg"], entry=ENTRY, run_id=run_id, day_rows=len(rows), day_files_read=len(want),
                      day_files_sha256_checked=True, day_files_digest=digest,
                      c7_denominators_match_order4=True),
        "themes_table": themes_table_summary(table, result_row, counts_c7),
        "missing_days": {"source": "order4", "count": len(missing),
                         "days": sorted(d.isoformat() for d in missing)},
        "reference_criteria": {"source": ctx["refs"]["order2"], "order2_status": ctx["order2_status"],
                               "criteria_ids": list(counting.CRITERIA_IDS),
                               "computed": ctx["criteria"], "official": False, "note": REF_NOTE},
        "a_equals_v": True,
        "limits": list(LIMITS),
        "citation": list(CITATION),
    }
    if statuses[c7]["status"] != "ok":
        main = dict(base, status="stopped", outside=None,
                    candidates=[_summary(cid, statuses[cid], None) for cid in counting.CANDIDATE_IDS])
        check_public(main)
        return main, None, None
    official = tagrules.build_tag_list(themes_arg, counts_c7, store.totals[c7], missing, start, end)
    allset = tagrules.build_tag_list(themes_arg, counts_c7, store.totals[c7], missing, start, end,
                                     optional=tagrules.OPTIONAL_CATEGORIES)
    results = {c7: official}
    for cid in counting.CANDIDATE_IDS:
        if cid != c7 and statuses[cid]["status"] == "ok":
            results[cid] = tagrules.build_tag_list(themes_arg, store.counts_for(cid), store.totals[cid],
                                                   missing, start, end)
    vers = {}
    for name, _c, _s, _sealed in OLD_VERSIONS:
        r = versions[name].build_tag_list(themes_arg, counts_c7, store.totals[c7], missing, start, end)
        vers[name] = {"result": r, "compare_with_official": tagrules.compare_lists(r, official)}
    detail = {
        "label": LABEL, "part": "detail", "in_git": False,
        "note": "Git の外に置く。sha256 は main の outside に入る",
        "official_result": official,
        "allset_result": allset,
        "versions": {"1cb463a": vers["1cb463a"]["result"]},
        "candidate_lists": [{"id": cid, "official": cid == c7,
                             "tag_list": (list(results[cid]["tag_list"]) if cid in results else None)}
                            for cid in counting.CANDIDATE_IDS],
        "citation": list(CITATION),
    }
    extra = {"label": LABEL, "part": "extra-versions", "in_git": False, "sealed": False,
             "note": "0e14f3b と 247fc1d の版（tags-naive.md 426行。封印の対象にしない。git の履歴で時刻が分かる）",
             "versions": {n: dict(v, official=False, note=REF_NOTE) for n, v in vers.items() if n != "1cb463a"},
             "citation": list(CITATION)}
    check_public(detail)
    check_public(extra)
    main = dict(
        base, status="ok",
        official={"candidate": c7, "version": "current", "setting": OFFICIAL_SETTING, "official": True,
                  "result": official_summary(official)},
        candidates=[_summary(cid, statuses[cid], results.get(cid)) for cid in counting.CANDIDATE_IDS],
        comparisons={"allset": compare_summary(tagrules.compare_lists(allset, official)),
                     "1cb463a": compare_summary(vers["1cb463a"]["compare_with_official"])},
        coverage=coverage_record(store, want, missing, block),
        outside={"detail": {"file_name": DETAIL_NAME, "sha256": sha256_of(detail)},
                 "extra": {"file_name": EXTRA_NAME, "sha256": sha256_of(extra)}},
    )
    check_public(main)
    return main, detail, extra


# ---------------------------------------------------------------------------
# 出力の形と、公開してよいものだけであることの確かめ
# ---------------------------------------------------------------------------

ALLOWED_KEYS = frozenset("""
label status block name start end refs order1 order1b order2 order3 order4 gkg_run_result seq record_sha256
list_sha256 code sealed sha256 sources versions commit path input entry run_id day_rows day_files_read
day_files_sha256_checked day_files_digest c7_denominators_match_order4 gkg_run_result_seq
gkg_run_result_record_sha256 manifest_path manifest_lines manifest_sha256 themes_table file_name rows
kept_columns headerless description_column unique_names duplicate_rows names_not_in_day_aggregate_form count
names official_data_themes_not_in_table missing_days source days a_equals_v limits citation candidates id
official numerator_column denominator_kind reason zero_days note n_med a a_float usable_day_count tag_count
tag_list candidate version setting result proposed_label block_start block_end quarters
quarters_without_usable_days v_equals_a enabled_optional_categories themes in_category_table quarter_counts
present_throughout mean_ratio mean_ratio_at_least_a exclusion_matches in_list
only_in_old only_in_new in_both old new compare_with_official 1cb463a 0e14f3b 247fc1d reference_criteria
order2_status criteria_ids computed input_mode input_run_id input_days results B1 B2 B3 B4 B5 decided
decided_by values docs_all_groups docs_without_v1_theme docs_without_v2_theme docs_without_any_theme spread
themes_per_doc ratio v2_docs v2_mentions coverage total usable_days ratios index part
reason_counts not_present_throughout mean_below_a excluded comparisons allset diff_count outside detail extra
in_git official_result allset_result candidate_lists all_themes
""".split())


def _keys(obj, out):
    if isinstance(obj, dict):
        for k, v in obj.items():
            out.add(k)
            _keys(v, out)
    elif isinstance(obj, list):
        for v in obj:
            _keys(v, out)
    return out


def check_public(record):
    """出力に入るのが、決まったキーと、テーマの名前・数・決まった語だけであることを確かめる。
    - キーが ALLOWED_KEYS の中だけ（人物名・組織名・URL・場所などの項目のキーは無い）
    - メールアドレスの形の文字列が無い（src/collector/privacy_scan.py の has_address）
    - 置き場所の絶対パス（/Users/、/Volumes/）が無い"""
    extra = _keys(record, set()) - ALLOWED_KEYS
    if extra:
        raise Order5Error("出力に、決めていないキーがある：%s" % sorted(extra)[:5])
    data = canonical_bytes(record)
    if _gkg().privacy_scan.has_address(data):
        raise Order5Error("出力に、メールアドレスの形の文字列がある")
    for bad in (b"/Users/", b"/Volumes/"):
        if bad in data:
            raise Order5Error("出力に、置き場所の絶対パスがある")
    return True


def canonical_bytes(record):
    return (json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
            + "\n").encode("utf-8")


def sha256_of(record):
    return hashlib.sha256(canonical_bytes(record)).hexdigest()


# ---------------------------------------------------------------------------
# 入口（封印係の入口から呼ぶ。手で流さない。docs/stats/order5-tag-list.md 4章）
# ---------------------------------------------------------------------------

def _reader(store, opened):
    if not os.path.isdir(store):
        raise Order5Error("置き場所がディレクトリでない")

    def read(name):
        if os.path.basename(name) != name or name in ("", ".", ".."):
            raise Order5Error("ファイルの名前の形が違う")
        opened.append(name)
        return _gkg().read_bytes_nofollow(os.path.join(store, name))
    return read


def official_record(store, themes_store, _test_block=None, _opened=None, _show=None, repo=None):
    """正式な run の記録から順番5の中身を作る。返り値：(main, detail, extra)。

    順：コードの照合 → 比べる版の照合 → official_day_records()（関門）→ 封印の記録（コードの値・参照・順番4）
    → 区分表のマニフェストとファイル → 日の集計。_test_block・_opened・_show はテストのためのもの。"""
    check_stats_code()
    versions = load_old_versions(_show, repo)
    block = method_block() if _test_block is None else _test_block
    day_records = _gkg().official_day_records()
    run_ids = {r.get("run_id") for r in day_records if isinstance(r, dict)}
    if len(run_ids) != 1:
        raise Order5Error("day の行の run_id が1つでない")
    ctx = sealed_context(run_ids.pop())
    ledger = _ledger()
    mpath = os.path.join(ctx["root"], *ledger.THEMES_MANIFEST.split("/"))
    mbytes = _gkg().read_bytes_nofollow(mpath) if os.path.lexists(mpath) else None
    row = themes_result_row(ledger, ctx["records"], mbytes)
    opened = [] if _opened is None else _opened
    table = parse_themes_table(_reader(themes_store, opened)(row["file_name"]), row)
    return build(day_records, block, _reader(store, opened), ctx, table, row, versions)


def _parse_args(argv):
    """--store・--themes-store・--out-dir（必ず）と --repo（任意。比べる版を取り出す git のリポジトリ）。"""
    keys = {"--store", "--themes-store", "--out-dir"}
    if len(argv) not in (6, 8) or len(argv) % 2:
        return None
    names = argv[0::2]
    if len(set(names)) != len(names) or not keys <= set(names) or not set(names) <= keys | {"--repo"}:
        return None
    d = dict(zip(names, argv[1::2]))
    return d["--store"], d["--themes-store"], d["--out-dir"], d.get("--repo")


MAIN_NAME = "order5-main.json"
DETAIL_NAME = "order5-detail.json"
EXTRA_NAME = "order5-extra.json"
OUT_NAMES = (MAIN_NAME, DETAIL_NAME, EXTRA_NAME)
PARTIAL_SUFFIX = ".partial"


def _write_new(path, data):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o644)
    with os.fdopen(fd, "wb") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())


def _out_dir_ok(out_dir):
    return os.path.isdir(out_dir) and not any(
        os.path.lexists(os.path.join(out_dir, n + s)) for n in OUT_NAMES for s in ("", PARTIAL_SUFFIX))


def write_outputs(out_dir, parts):
    """parts：[(名前, 記録)]。すべてのバイト列を先に作り、一時の名前（.partial）にすべて書いてから、
    detail・extra・main の順に本来の名前へ移す。一時の名前に書く途中で失敗したら、本来の名前のファイルは
    一つも無い（.partial は消さずに残す。削除はリードを通す）。返り値：[(名前, sha256)]。"""
    if not _out_dir_ok(out_dir):
        raise Order5Error("書き出すディレクトリが無いか、同じ名前のファイルがある")
    blobs = [(name, canonical_bytes(rec)) for name, rec in parts]
    for name, data in blobs:
        _write_new(os.path.join(out_dir, name + PARTIAL_SUFFIX), data)
    order = sorted(blobs, key=lambda b: b[0] == MAIN_NAME)      # main を最後に
    for name, _data in order:
        dst = os.path.join(out_dir, name)
        if os.path.lexists(dst):
            raise Order5Error("移す先に同じ名前のファイルがある")
        os.rename(os.path.join(out_dir, name + PARTIAL_SUFFIX), dst)
    return [(name, hashlib.sha256(data).hexdigest()) for name, data in blobs]


def main(argv=None):
    """封印係の入口から呼ぶ（手で流さない）。標準出力に出すのは、書いたファイルの名前と sha256 だけ。"""
    if argv is None:
        argv = sys.argv[1:]
    parsed = _parse_args(list(argv))
    if parsed is None:
        sys.stderr.write("order5: 使い方は --store <置き場所> --themes-store <置き場所> --out-dir <ディレクトリ>\n")
        return 2
    store, themes_store, out_dir, repo = parsed
    if not _out_dir_ok(out_dir):
        sys.stderr.write("order5: 書き出すディレクトリが無いか、同じ名前のファイルがある\n")
        return 2
    opened = []
    t0 = time.monotonic()
    try:
        main_rec, detail, extra = official_record(store, themes_store, _opened=opened, repo=repo)
        parts = [(MAIN_NAME, main_rec)]
        if detail is not None:
            parts = [(DETAIL_NAME, detail), (EXTRA_NAME, extra)] + parts
        written = write_outputs(out_dir, parts)
    except Exception as e:  # 関門・照合・入力の誤り・書き出しの失敗で止まる。本来の名前のファイルは書かない
        sys.stderr.write("order5: 止まった：%s: %s\n" % (type(e).__name__, e))
        return 1
    sys.stderr.write("order5: ファイルを %d 個開いた（%.1f 秒）\n" % (len(opened), time.monotonic() - t0))
    for name, sha in written:
        sys.stdout.write("%s  %s\n" % (sha, name))
    return 0 if main_rec["status"] == "ok" else 3


if __name__ == "__main__":
    sys.exit(main())
