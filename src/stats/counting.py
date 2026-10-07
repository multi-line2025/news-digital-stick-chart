#!/usr/bin/env python3
"""報道量の数え方の候補と、正式に使う数え方、参考の基準の案（T-028・T-036。順番1b で封印する提案）。

文書は docs/stats/counting.md。ここの定数と関数が正本で、文書の表はその写しである
（tests/stats/test_counting.py で照合する）。

- この版は「提案」で、オーナーの承認のあと封印係が順番1b で封印する。統計係は封印しない。
- 正式に使う数え方は、2026-10-08 のオーナーの決定（OWNER_DECISION）で決め打ちにした。分子は
  T の行の v1_or_v2_docs（V1 か V2 の少なくとも一方にそのテーマが付いた文書の数）、分母は同じ欄の
  全テーマの合計。正式な候補 OFFICIAL_CANDIDATE は、この決定の（分子の欄、分母）に当たる候補を
  CANDIDATES から機械的に引いて決まる（official_candidate()）。手で候補の識別子を書く場所は無い
  （T-028 の監査の軽-2）。B1〜B5 と、C7 のほかの候補は、比べるための参考で、正式ではない。
- GKG のデータ、区分表、ネットワークには触れていない。このモジュールは現在の日時を読まない。
- 入力の形は、収集係の日の集計（src/collector/gkg.py 6章、serialize_day が書く形。形式の版
  "gkg-day" 3。T-035）である。gkg.py は読み込まない（取り込むと、収集係のコードが変わったときに、この
  ファイルの sha256 が同じでも結果が変わりうるため）。形が合うことは、テストが gkg.serialize_day
  で作った日の集計で確かめる。

候補（CANDIDATES）
  r(d) = 分子 / 分母。どの候補も、翻訳の印 T の付いた組 g（"1T" など）を数えない。出どころは
  reviews/T-016.md（コミット 4e7c511）：オーナーの発言は「翻訳の記事については案aで良いです」で、
  案a の中身（v0 では翻訳の記事を使わない）は、同じ節のリードの理解の行にある。数える組は
  COUNTED_GROUP_RULE（g の最後の文字が T でないもの。形の違う X も含む）。
    分子：日の集計の T の行の、v1_docs・v2_docs・v2_mentions・v1_or_v2_docs のどれか一つの欄を、
          数える組で足したもの（テーマごと）。正式に使うのは C7（v1_or_v2_docs、分母 same）。
    分母："docs"（D の行の文書数を、数える組で足したもの）か、"same"（分子と同じ欄を、
          数える組とすべてのテーマで足したもの）。

基準の案（CRITERIA。B1〜B5 はどれも比べるための参考で、正式ではない。T-036）
  入力は3日分（TRIAL_DAYS）の日の集計。どの run の集計にするかは decide() の規則（1段目は最初の
  試しの run、2段目は正式な run の同じ3日）で、マニフェストだけから決まる。出力は候補の識別子
  ちょうど一つ。基準が該当なしなら FALLBACK_ORDER[基準] の順で使える最初の候補（apply_all の decided）。
  比べるのは分数（fractions.Fraction）で、丸めは入れない。

使い方
  .venv/bin/python -B src/stats/counting.py
      候補・正式な数え方・参考の基準の案の定義を JSON（キー順・UTF-8）で出力する（データは読まない）
  .venv/bin/python -B src/stats/counting.py apply <試しの run のマニフェスト> <正式な run のマニフェスト>
          <試しの run の保存先> <正式な run の保存先>
      順番2の当てはめ（封印係が当てはめ直すときに使う。正式な数え方が入力で計算できるかの確かめ、
      参考の基準の案の結果、欄の手厚さ）。マニフェストは、git の確かめに通った
      コミットした版を渡す（通らなければ FAILED、HEAD にファイルが無ければ EMPTY と書く。
      それ以外で読めないパスは、確かめに通らないものとして止まる）。結果を JSON で出力する。終了コードは
      decided 0、stopped 1、pending 3。
"""

import fractions
import gzip
import hashlib
import io
import json
import re
import sys

PROPOSED_LABEL = "counting-v1"

Fr = fractions.Fraction

# ---------------------------------------------------------------------------
# 入力の形（src/collector/gkg.py 6章）
# ---------------------------------------------------------------------------

DAY_FORMAT_NAME = "gkg-day"
DAY_FORMAT_VERSION = "3"
TRIAL_MODE = "trial"
OFFICIAL_MODE = "official"
# gkg.TRIAL_DAYS と同じ（tests/stats/test_counting.py で照合する）
TRIAL_DAYS = ("2015-03-02", "2015-03-03", "2015-03-04")
TRIAL_MANIFEST_PATH = "data/manifest/gdelt-gkg-trial.jsonl"
COLUMNS = ("v1_docs", "v2_docs", "v2_mentions", "v1_or_v2_docs")   # T の行の4つの数の欄（この順。版3）
DENOMINATORS = ("docs", "same")
S_UNCOVERED = {"V1": "docs_without_v1_theme", "V2": "docs_without_v2_theme", "ANY": "docs_without_any_theme"}

COUNTED_GROUP_RULE = "g does not end with 'T' (translated documents are not counted; 'X' is counted)"

_RUN_ID_RE = re.compile(r"\A[0-9a-f]{16}\Z")
# gkg.THEME_RE・gkg の組の作り方と同じ形（テストで照合する）
THEME_NAME_RE = re.compile(r"\A[A-Z][A-Z0-9_]{0,159}\Z")
GROUP_RE = re.compile(r"\A(?:[0-9]{1,2}|X)T?\Z")
# 中身を読まない決まった行の種類（gkg.serialize_day が書くもの）
_SKIPPED_TAGS = frozenset({"F", "FD", "C", "L", "P1", "P2", "NC", "NL", "E"})
_SHA_RE = re.compile(r"\A[0-9a-f]{64}\Z")
_INT_RE = re.compile(r"\A(?:0|[1-9][0-9]*)\Z")


def counted_group(g):
    """g を数えるか（翻訳の印 T の付いた組は数えない）。"""
    return not g.endswith("T")


# ---------------------------------------------------------------------------
# 候補
# ---------------------------------------------------------------------------

# (識別子, 分子の欄, 分母)
CANDIDATES = (
    ("C1", "v1_docs", "docs"),
    ("C2", "v1_docs", "same"),
    ("C3", "v2_docs", "docs"),
    ("C4", "v2_docs", "same"),
    ("C5", "v2_mentions", "docs"),
    ("C6", "v2_mentions", "same"),
    ("C7", "v1_or_v2_docs", "same"),       # T-036。2026-10-08 のオーナーの決定で正式に使う
)
CANDIDATE_IDS = tuple(c[0] for c in CANDIDATES)
_CAND = {c[0]: (c[1], c[2]) for c in CANDIDATES}
REFERENCE_CANDIDATE_IDS = ("C1", "C2", "C3", "C4", "C5", "C6")   # 基準の案 B1〜B5 が選ぶ候補（参考）

# 正式に使う数え方（2026-10-08 オーナー決定。counting.md 0章）。出どころは commit を40桁で指定した
# reviews/T-028.md の2つの行：オーナーの発言の行（行の全体が一致）と、リードの整理の「決定：」の行
# （先頭が一致する行がちょうど1つで、DECISION_PHRASES の語句をすべて含む。T-036 差し戻し1回目 中-4）。
OWNER_DECISION = {
    "numerator_column": "v1_or_v2_docs",
    "denominator": "same",
    "source_commit": "9c85f58f054a679b8e5f40fcd7adbb17536f6366",
    "source_path": "reviews/T-028.md",
    "source_line": "> 作り方2を、新しい候補として加え、正式に使う数え方にしよう",
    "decision_line_prefix": "- 決定：正式に使う数え方は、",
}
# 「決定：」の行の語句と、それが決める OWNER_DECISION の項目と値。official_candidate() は、
# OWNER_DECISION の分子の欄と分母が、この対応と一致することを求める（中身を出どころの語句で縛る）
DECISION_PHRASES = (
    ("V1 か V2 の少なくとも一方", "numerator_column", "v1_or_v2_docs"),
    ("同じ数え方の全テーマの合計", "denominator", "same"),
)


# 順番1b の承認事項（候補7つ、参考の基準の案5つ、うまくいかなかったときの行き先、欄の手厚さの公開）への
# オーナーの承認（2026-10-08。T-038）。照らし方：commit を40桁で指定した reviews/T-036.md で、行の全体が
# line と一致する行がファイルの中でちょうど1つあり、その行より前で最も近い「## 」の見出しの行の全体が
# heading と一致し、その見出しの行もファイルの中でちょうど1つあること（counting.md 冒頭）。
OWNER_APPROVAL_1B = {
    "source_commit": "a970019c61808738b02629b14f68b3171c4ddd57",
    "source_path": "reviews/T-036.md",
    "heading": "## 2026-10-08 オーナーの発言（原文のまま記録。順番1b の承認事項）",
    "line": "> 承認します",
}


def approval_line_ok(text, approval=None):
    """OWNER_APPROVAL_1B の照らし方を text（その commit のファイルの中身）に当てはめる。合えば True。"""
    a = OWNER_APPROVAL_1B if approval is None else approval
    lines = text.split("\n")
    if lines.count(a["line"]) != 1 or lines.count(a["heading"]) != 1:
        return False
    i = lines.index(a["line"])
    heads = [j for j in range(i) if lines[j].startswith("## ")]
    return bool(heads) and lines[heads[-1]] == a["heading"]


def official_candidate():
    """OWNER_DECISION の（分子の欄、分母）に当たる候補の識別子。

    OWNER_DECISION の分子の欄と分母が DECISION_PHRASES の対応と一致しない場合と、当たる候補が
    ちょうど一つでない場合は ValueError。
    """
    for _phrase, key, value in DECISION_PHRASES:
        if OWNER_DECISION.get(key) != value:
            raise ValueError("OWNER_DECISION の %s が、出どころの語句の対応と一致しない" % key)
    hit = [cid for cid, col, den in CANDIDATES
           if (col, den) == (OWNER_DECISION["numerator_column"], OWNER_DECISION["denominator"])]
    if len(hit) != 1:
        raise ValueError("オーナーの決定に当たる候補が、ちょうど一つでない")
    return hit[0]


OFFICIAL_CANDIDATE = official_candidate()

# ---------------------------------------------------------------------------
# 基準の案
# ---------------------------------------------------------------------------

CRITERIA_IDS = ("B1", "B2", "B3", "B4", "B5")
B4_SPREAD_LIMIT = Fr(11, 10)       # 1日あたりのテーマの数の、最大と最小の比の上限
B5_MENTION_LIMIT = Fr(21, 20)      # 言及の回数と文書の数の比の上限
# 基準の結果が該当なしのときの代わり：この順で、入力のすべての日で使える最初の候補（T-028 差し戻し1回目 中3）
_FB_SAME = ("C2", "C4", "C1", "C3", "C6", "C5")     # 分母「同じ数え方の合計」を先にする順
_FB_DOCS = ("C1", "C3", "C2", "C4", "C5", "C6")     # 分母「全体の記事の数」を先にする順
# 基準ごとの代わりの順（該当なしのとき）。その基準が選びうる分母の種類を先にする（counting.md 3章 (1)）
FALLBACK_ORDER = {"B1": _FB_SAME, "B2": _FB_DOCS, "B3": _FB_DOCS, "B4": _FB_DOCS, "B5": _FB_SAME}


def official_status():
    """正式な数え方が決まっているか。OWNER_DECISION から機械的に決まるので、決まっていれば "decided"。"""
    return "decided" if official_candidate() == OFFICIAL_CANDIDATE else "inconsistent"


class CountingError(Exception):
    """入力が規則の形に合わない。順番2を封印しない。"""


# ---------------------------------------------------------------------------
# 日の集計を読む
# ---------------------------------------------------------------------------

def _int(x, what):
    if not _INT_RE.fullmatch(x):
        raise CountingError("%s が0以上の整数でない" % what)
    return int(x)


def parse_day(gz_bytes, expect_day=None, expect_mode=None):
    """日の集計（gzip のバイト列）から、候補と基準に要る行だけを読む。

    読む行：頭の行（#）、V、D、T、S。ほかの決まった行（F、FD、C、L、P1、P2、NC、NL、E）は中身を
    読み飛ばす。知らない種類の行があれば止まる。
    確かめること（T-036 差し戻し1回目 軽-1）：版3、欄の数、0以上の整数、番号と組の重なり、
    テーマの名前の形（THEME_NAME_RE）、組の形（GROUP_RE）、T の行の数どうしの関係
    （max(v1, v2) <= v1_or_v2 <= v1 + v2、v2 <= v2_mentions）、T の行の文書の数がその組の D を超えない、
    S の docs_without_* がすべての組の D の和を超えない。
    戻り値：{"day", "mode", "docs": {g: n},
             "themes": {名前: {g: (v1_docs, v2_docs, v2_mentions, v1_or_v2_docs)}}, "stats": {名前: n}}
    """
    try:
        text = gzip.GzipFile(fileobj=io.BytesIO(gz_bytes), mode="rb")
        lines = iter(text)
        head = next(lines, None)
    except (OSError, EOFError) as e:
        raise CountingError("gzip として読めない: %s" % e) from None
    if head is None:
        raise CountingError("頭の行が無い")
    h = head.rstrip(b"\n").decode("ascii", "replace").split("\t")
    if len(h) != 5 or h[0] != "#" or h[1] != DAY_FORMAT_NAME or h[2] != DAY_FORMAT_VERSION:
        raise CountingError("頭の行の形式が gkg-day 3 でない")
    day, mode = h[3], h[4]
    if expect_day is not None and day != expect_day:
        raise CountingError("頭の行の日 %s が、求めた日 %s と違う" % (day, expect_day))
    if expect_mode is not None and mode != expect_mode:
        raise CountingError("頭の行の mode %s が、求めた mode %s と違う" % (mode, expect_mode))
    vocab = {}
    docs = {}
    t_rows = []
    stats = {}
    try:
        for raw in lines:
            line = raw.rstrip(b"\n").decode("ascii")
            tag, _sep, rest = line.partition("\t")
            if tag == "V":
                f = rest.split("\t")
                if len(f) != 2:
                    raise CountingError("V の行の欄の数が違う")
                i = _int(f[0], "V の番号")
                if i in vocab:
                    raise CountingError("V の番号が重なっている")
                vocab[i] = f[1]
            elif tag == "D":
                f = rest.split("\t")
                if len(f) != 2:
                    raise CountingError("D の行の欄の数が違う")
                if f[0] in docs:
                    raise CountingError("D の行の組が重なっている")
                docs[f[0]] = _int(f[1], "D の文書数")
            elif tag == "T":
                f = rest.split("\t")
                if len(f) != 6:
                    raise CountingError("T の行の欄の数が違う")
                nums = tuple(_int(x, "T の数") for x in f[2:6])
                v1, v2, v2m, v12 = nums
                # 数どうしの関係（版3）：両方に付いても1回なので max(v1, v2) <= v12 <= v1 + v2。
                # 言及の回数は文書の数以上（v2 <= v2m）。合わなければ形が違う
                if not (max(v1, v2) <= v12 <= v1 + v2 and v2 <= v2m):
                    raise CountingError("T の行の数どうしの関係が合わない")
                t_rows.append((f[0], _int(f[1], "T の番号"), nums))
            elif tag in _SKIPPED_TAGS:
                continue
            elif tag == "S":
                f = rest.split("\t")
                if len(f) != 2:
                    raise CountingError("S の行の欄の数が違う")
                if f[0] in stats:
                    raise CountingError("S の行の名前が重なっている")
                stats[f[0]] = _int(f[1], "S の数")
            else:
                raise CountingError("知らない種類の行がある")
    except (OSError, EOFError, UnicodeDecodeError) as e:
        raise CountingError("日の集計を読めない: %s" % e) from None
    for name in vocab.values():
        if not THEME_NAME_RE.fullmatch(name):
            raise CountingError("V の行のテーマの名前の形が違う")
    for g in docs:
        if not GROUP_RE.fullmatch(g):
            raise CountingError("D の行の組の形が違う")
    total_docs = sum(docs.values())
    for name in S_UNCOVERED.values():
        if stats.get(name, 0) > total_docs:
            raise CountingError("S の %s が、すべての組の文書の数を超える" % name)
    themes = {}
    for g, i, nums in t_rows:
        if i not in vocab:
            raise CountingError("T の行の番号が V に無い")
        per_g = themes.setdefault(vocab[i], {})
        if g in per_g:
            raise CountingError("T の行の（組、テーマ）が重なっている")
        if g not in docs:
            raise CountingError("T の行の組が D に無い")
        if max(nums[0], nums[1], nums[3]) > docs[g]:
            raise CountingError("T の行の文書の数が、その組の D を超える")
        per_g[g] = nums
    return {"day": day, "mode": mode, "docs": docs, "themes": themes, "stats": stats}


# ---------------------------------------------------------------------------
# 候補の計算
# ---------------------------------------------------------------------------

def candidate_counts(summary, cid):
    """候補 cid の、その日の (分子 {テーマ名: 件数}, 分母)。件数 0 のテーマは入れない。

    分子は、数える組（counted_group）の T の行の欄を、テーマごとに足したもの。
    分母は "docs" なら数える組の D の行の和、"same" なら分子のすべてのテーマの和。
    どの数も0以上の整数（tagrules.build_tag_list() の入力の条件）。
    """
    if cid not in _CAND:
        raise ValueError("候補の一覧に無い識別子: %r" % (cid,))
    col, den = _CAND[cid]
    k = COLUMNS.index(col)
    counts = {}
    for name in sorted(summary["themes"]):
        n = sum(v[k] for g, v in summary["themes"][name].items() if counted_group(g))
        if n:
            counts[name] = n
    if den == "docs":
        total = sum(n for g, n in summary["docs"].items() if counted_group(g))
    else:
        total = sum(counts.values())
    return counts, total


def column_total(summary, col):
    """数える組とすべてのテーマで、欄 col を足したもの。"""
    k = COLUMNS.index(col)
    return sum(v[k] for per_g in summary["themes"].values() for g, v in per_g.items()
               if counted_group(g))


def counted_docs(summary):
    return sum(n for g, n in summary["docs"].items() if counted_group(g))


def usable(summaries, cid):
    """候補 cid が、入力のすべての日で、分母 > 0 かつ分子の和 > 0 か。"""
    for s in summaries:
        counts, total = candidate_counts(s, cid)
        if total <= 0 or sum(counts.values()) <= 0:
            return False
    return True


# ---------------------------------------------------------------------------
# 基準の案（入力：TRIAL_DAYS の3日分の summary。出力：候補の識別子か None）
# ---------------------------------------------------------------------------

def _check_input(summaries):
    days = [s["day"] for s in summaries]
    if tuple(days) != TRIAL_DAYS:
        raise CountingError("基準の入力が TRIAL_DAYS の3日（この順）でない: %r" % (days,))


def _finish(cid, values, reason):
    return {"candidate": cid, "values": values, "reason": reason}


def _field_by_coverage(summaries):
    """B1・B2 の欄の選び方。テーマの付かない文書の数が少ない欄。同じなら V1。

    戻り値 (欄 "V1"/"V2" か None, values)。None は該当なし。
    S の行の数とすべての組の D の和は、翻訳の印の付いた組と X を含む（gkg.py の S は組ごとに
    分けていないため。docs/stats/counting.md 3章 (1) の基準の表のあとの注）。
    """
    u1 = sum(s["stats"].get(S_UNCOVERED["V1"], 0) for s in summaries)
    u2 = sum(s["stats"].get(S_UNCOVERED["V2"], 0) for s in summaries)
    n = sum(sum(s["docs"].values()) for s in summaries)
    values = {"docs_all_groups": n, "docs_without_v1_theme": u1, "docs_without_v2_theme": u2}
    if n <= 0 or u1 > n or u2 > n:
        return None, values
    field = "V1" if u1 <= u2 else "V2"
    if (u1 if field == "V1" else u2) >= n:
        return None, values           # 選んだ欄でも、テーマの付いた文書が一件も無い
    return field, values


def criterion_b1(summaries):
    """B1：欄はテーマの付かない文書が少ない方（同じなら V1）。単位は文書。分母は同じ単位の和。"""
    _check_input(summaries)
    field, values = _field_by_coverage(summaries)
    if field is None:
        return _finish(None, values, "no_field")
    cid = "C2" if field == "V1" else "C4"
    if not usable(summaries, cid):
        return _finish(None, values, "not_usable")
    return _finish(cid, values, "field_%s" % field)


def criterion_b2(summaries):
    """B2：欄の選び方は B1 と同じ。単位は文書。分母は文書の数 D。"""
    _check_input(summaries)
    field, values = _field_by_coverage(summaries)
    if field is None:
        return _finish(None, values, "no_field")
    cid = "C1" if field == "V1" else "C3"
    if not usable(summaries, cid):
        return _finish(None, values, "not_usable")
    return _finish(cid, values, "field_%s" % field)


def criterion_b3(summaries):
    """B3：決め打ちで C1。データは使えるかの確かめだけに使う。"""
    _check_input(summaries)
    if not usable(summaries, "C1"):
        return _finish(None, {}, "not_usable")
    return _finish("C1", {}, "fixed")


def criterion_b4(summaries):
    """B4：V1 の文書。1文書あたりのテーマの数の日ごとの比の最大÷最小が B4_SPREAD_LIMIT を
    超えれば分母は同じ単位の和（C2）、超えなければ（等しいときを含む）文書の数（C1）。"""
    _check_input(summaries)
    qs = []
    for s in summaries:
        d = counted_docs(s)
        if d <= 0:
            return _finish(None, {}, "no_docs")
        qs.append(Fr(column_total(s, "v1_docs"), d))
    values = {"themes_per_doc": [str(q) for q in qs]}
    if min(qs) <= 0:
        return _finish(None, values, "no_themes")
    spread = max(qs) / min(qs)
    values["spread"] = str(spread)
    cid = "C2" if spread > B4_SPREAD_LIMIT else "C1"
    if not usable(summaries, cid):
        return _finish(None, values, "not_usable")
    return _finish(cid, values, "spread")


def criterion_b5(summaries):
    """B5：V2。3日の言及の回数の和÷文書の数の和が B5_MENTION_LIMIT 以下なら文書（C4）、
    超えれば言及の回数（C6）。分母はどちらも同じ単位の和。"""
    _check_input(summaries)
    m = sum(column_total(s, "v2_mentions") for s in summaries)
    d = sum(column_total(s, "v2_docs") for s in summaries)
    values = {"v2_mentions": m, "v2_docs": d}
    if d <= 0:
        return _finish(None, values, "no_v2")
    ratio = Fr(m, d)
    values["ratio"] = str(ratio)
    cid = "C4" if ratio <= B5_MENTION_LIMIT else "C6"
    if not usable(summaries, cid):
        return _finish(None, values, "not_usable")
    return _finish(cid, values, "mentions_ratio")


CRITERIA = {"B1": criterion_b1, "B2": criterion_b2, "B3": criterion_b3, "B4": criterion_b4,
            "B5": criterion_b5}


def fallback_candidate(summaries, bid):
    """基準 bid の結果が該当なしのときの代わり（counting.md 3章 (1)）。

    FALLBACK_ORDER[bid] の順で、入力のすべての日で使える（usable）最初の候補。どれも使えなければ None。
    """
    for cid in FALLBACK_ORDER[bid]:
        if usable(summaries, cid):
            return cid
    return None


ORDER2_STATUSES = ("decided", "stopped", "pending")
ORDER2_STOP_KINDS = ("a", "b", "c")     # seal-order1.md 3章 (2) の (a) 時機 (b) decide() (c) コードの sha256


def select_order2_record(records):
    """順番3が参照する順番2の記録を、機械的に一つ選ぶ（T-038。T-036 再提出1回目の監査の中-1。案(ロ)）。

    records：参照する順番1b の記録に対する、順番2の試みの記録の一覧。各要素は
      {"seq": ledger の seq（整数）, "status": "decided" | "stopped" | "pending",
       "stop_kind": status が stopped なら "a" | "b" | "c"、ほかは None}
    status が pending の記録（待つ）は数えない。残りのうち seq が最も小さいものを返す。無ければ None。
    並び順や中身の良し悪しでは選ばない。
    """
    seen = set()
    chosen = None
    for r in records:
        _check_order2_record(r)
        seq = r["seq"]
        if seq in seen:
            raise ValueError("順番2の記録の seq が重なっている")
        seen.add(seq)
        if r["status"] == "pending":
            continue
        if chosen is None or seq < chosen["seq"]:
            chosen = r
    return chosen


def _check_order2_record(r):
    """順番2の記録の形（seq は整数、status は決まった値、stopped なら stop_kind は (a)(b)(c) のどれか、
    それ以外なら stop_kind は None）。合わなければ ValueError。"""
    if not isinstance(r, dict):
        raise ValueError("順番2の記録が dict でない")
    if type(r.get("seq")) is not int:
        raise ValueError("順番2の記録の seq が整数でない")
    if r.get("status") not in ORDER2_STATUSES:
        raise ValueError("順番2の記録の status が決まった値でない")
    if r["status"] == "stopped":
        if r.get("stop_kind") not in ORDER2_STOP_KINDS:
            raise ValueError("止まった順番2の記録の stop_kind が決まった値でない")
    elif r.get("stop_kind") is not None:
        raise ValueError("止まっていない順番2の記録に stop_kind がある")


def order3_may_seal(chosen):
    """select_order2_record() の結果で順番3を封印してよいか（入力の形も確かめる。T-039 軽-4）。

    記録が無い（None）とき、(a)（時機の条件を満たさない）で止まった記録のときは False（順番3を封印せず、
    0件ならリードに報告、(a) ならオーナーが扱いを決める）。それ以外（決まった記録、(b)・(c) で止まった記録）は True。
    pending の記録は select_order2_record() が選ばないので、渡されたら ValueError。
    順番3の関門としては、これだけでなく order3_gate() を使う（あとから判明した (a) と、参照する順番1b）。
    """
    if chosen is None:
        return False
    _check_order2_record(chosen)
    if chosen["status"] == "pending":
        raise ValueError("待つ（pending）の記録は、順番3が参照する記録にならない")
    return not (chosen["status"] == "stopped" and chosen["stop_kind"] == "a")


_HEX40_RE = re.compile(r"\A[0-9a-f]{40}\Z")


def check_timing_check(tc):
    """順番3の時点で封印係が時機の条件を確かめた内容（timing_check）の形を確かめる。合わなければ ValueError。

    tc = {"ok": True/False,                       確かめた結果
          "ref_1b_seq": 整数か None,               確かめた順番1b の記録の seq（順番1b の記録が無ければ None。
                                                   そのとき ok は False）
          "head": 40桁,                            確かめたときの HEAD
          "f_set": [{"commit": 40桁, "parents": [40桁, ...]}, ...],
                                                   確かめた F の集合（seal-order1.md 3章 (2) の時機の条件）。
                                                   各 commit の ID と親。重なりなし
          "refs": [{"ref": 参照の名前, "commit": 40桁}, ...],
                                                   `git for-each-ref` の参照の一覧（名前の重なりなし。空でない）
          "worktree_heads": [40桁, ...],           `git worktree list --porcelain` の各 worktree の HEAD
                                                   （重なりなし。空でない。T-040）。F を数える範囲は、refs と
                                                   worktree_heads から辿れる commit（`git log --all` と同じ。
                                                   counting.md 4章 (3)）
          "reason": ok が False なら空でない文字列、True なら None}
    """
    keys = ("f_set", "head", "ok", "reason", "ref_1b_seq", "refs", "worktree_heads")
    if not isinstance(tc, dict) or tuple(sorted(tc)) != keys:
        raise ValueError("timing_check のキーが決まった %d 個（%s）でない" % (len(keys), "、".join(keys)))
    if not isinstance(tc["ok"], bool):
        raise ValueError("timing_check.ok が True か False でない")
    if tc["ref_1b_seq"] is not None and type(tc["ref_1b_seq"]) is not int:
        raise ValueError("timing_check.ref_1b_seq が整数か None でない")
    if tc["ref_1b_seq"] is None and tc["ok"]:
        raise ValueError("順番1b の記録が無い（ref_1b_seq が None）のに、timing_check.ok が True")
    if not isinstance(tc["head"], str) or not _HEX40_RE.fullmatch(tc["head"]):
        raise ValueError("timing_check.head が40桁の16進でない")
    if not isinstance(tc["f_set"], list):
        raise ValueError("timing_check.f_set が一覧でない")
    seen = set()
    for c in tc["f_set"]:
        if not isinstance(c, dict) or sorted(c) != ["commit", "parents"] \
                or not isinstance(c["commit"], str) or not _HEX40_RE.fullmatch(c["commit"]) \
                or not isinstance(c["parents"], list) \
                or not all(isinstance(x, str) and _HEX40_RE.fullmatch(x) for x in c["parents"]):
            raise ValueError("timing_check.f_set の要素が {commit: 40桁, parents: [40桁...]} でない")
        if c["commit"] in seen:
            raise ValueError("timing_check.f_set の commit が重なっている")
        seen.add(c["commit"])
    if not isinstance(tc["refs"], list) or not tc["refs"]:
        raise ValueError("timing_check.refs が空でない一覧でない")
    names = set()
    for r in tc["refs"]:
        if not isinstance(r, dict) or sorted(r) != ["commit", "ref"] or not isinstance(r["ref"], str) \
                or not r["ref"] or not isinstance(r["commit"], str) or not _HEX40_RE.fullmatch(r["commit"]):
            raise ValueError("timing_check.refs の要素が {ref: 名前, commit: 40桁} でない")
        if r["ref"] in names:
            raise ValueError("timing_check.refs の名前が重なっている")
        names.add(r["ref"])
    wh = tc["worktree_heads"]
    if not isinstance(wh, list) or not wh or len(set(wh)) != len(wh) \
            or not all(isinstance(x, str) and _HEX40_RE.fullmatch(x) for x in wh):
        raise ValueError("timing_check.worktree_heads が、重ならない40桁の16進の空でない一覧でない")
    if tc["ok"]:
        if tc["reason"] is not None:
            raise ValueError("timing_check.ok が True なのに reason がある")
    elif not isinstance(tc["reason"], str) or not tc["reason"]:
        raise ValueError("timing_check.ok が False なのに reason が無い")


def _check_order3_attempt(r):
    """前の順番3の試みの記録（ledger に封印係が書いたもの）の形。"""
    keys = ("may_seal", "ref_1b_seq", "seq", "timing_ok")
    if not isinstance(r, dict) or tuple(sorted(r)) != keys:
        raise ValueError("順番3の試みの記録のキーが決まった %d 個（%s）でない" % (len(keys), "、".join(keys)))
    if type(r["seq"]) is not int:
        raise ValueError("順番3の試みの記録の seq が整数でない")
    if r["ref_1b_seq"] is not None and type(r["ref_1b_seq"]) is not int:
        raise ValueError("順番3の試みの記録の ref_1b_seq が整数か None でない")
    if not isinstance(r["may_seal"], bool) or not isinstance(r["timing_ok"], bool):
        raise ValueError("順番3の試みの記録の may_seal・timing_ok が True か False でない")
    if r["may_seal"] and not r["timing_ok"]:
        raise ValueError("順番3の試みの記録で、timing_ok が False なのに may_seal が True")
    if r["ref_1b_seq"] is None and (r["may_seal"] or r["timing_ok"]):
        raise ValueError("順番1b の記録が無いときの試みの記録で、may_seal か timing_ok が True")


def attempt_from_record(seq, record):
    """封印係が ledger に書いた順番3の試みの記録（order3_gate() の record）と、その記録の seq から、
    order3_gate() の order3_attempts の1要素を作る（T-040 軽-2）。timing_ok は record の timing_check.ok。"""
    if not isinstance(record, dict) or sorted(record) != ["chosen_order2_seq", "may_seal", "reason",
                                                          "ref_1b_seq", "timing_check"]:
        raise ValueError("順番3の試みの記録のキーが、order3_gate() の record と違う")
    check_timing_check(record["timing_check"])
    if record["timing_check"]["ref_1b_seq"] != record["ref_1b_seq"]:
        raise ValueError("順番3の試みの記録の ref_1b_seq と timing_check.ref_1b_seq が違う")
    out = {"seq": seq, "ref_1b_seq": record["ref_1b_seq"], "may_seal": record["may_seal"],
           "timing_ok": record["timing_check"]["ok"]}
    _check_order3_attempt(out)
    return out


def order3_gate(order1b_seqs, order2_records, timing_check, order3_attempts):
    """順番3を封印してよいかと、参照する記録を決め、ledger に書く記録の中身を返す（T-039、差し戻し1回目
    中-A・軽-D。T-038 の監査の中-1・中-2。counting.md 4章 (3)）。

    order1b_seqs：順番3の時点の ledger にある、順番1b の kind の記録の seq の一覧。
    order2_records：順番2の試みの記録の一覧。各要素は select_order2_record() の形に、
      "ref_1b_seq"（その記録が参照した順番1b の記録の seq）を足したもの。
    timing_check：封印係が、順番3の時点で、参照する順番1b の記録について時機の条件（seal-order1.md 3章 (2)。
      ledger の seq と git の親子の関係だけで決まる）を確かめ直した内容（check_timing_check() の形）。
      真偽値だけでなく、確かめた F の集合・HEAD・参照の一覧を組で受け取り、記録に写す。
    order3_attempts：これまでの順番3の試みの記録（封印係が ledger に書いたもの）の一覧。各要素は
      {"seq", "ref_1b_seq", "may_seal", "timing_ok"}で、attempt_from_record() で記録から作る
      （timing_ok は記録の timing_check.ok。順番1b の記録が無かった試みは ref_1b_seq が None）。
    規則：
      1. 参照する順番1b の記録は、order1b_seqs の最大の seq（順番2と同じ決め方）。無ければ封印しない。
      2. 順番2の記録は、ref_1b_seq がその seq のものだけを数える。
      3. timing_check の ref_1b_seq が 1 と違えば ValueError（別の1b を確かめた内容を使わない）。
      4. order3_attempts の中に、1 の seq について timing_ok が False の記録が一つでもあれば封印しない
         （(a) の破れを一度記録したら、以後は恒久に止まる。あとで参照を消して条件が通っても戻さない）。
      5. timing_check.ok が False なら封印しない。
      6. 2 の記録の中に、(a) で止まった記録が一つでもあれば封印しない（seq の大小によらない）。
      7. 2 の記録から select_order2_record() で選ぶ。無ければ封印しない。
    つじつまの合わない入力（ref_1b_seq がどの順番1b の記録にも無い順番2の記録・試みの記録、参照した
    順番1b の記録より seq が小さい順番2の記録・試みの記録、seq の重なり）は ValueError。
    戻り値：{"may_seal", "ref_1b_seq", "chosen", "reason", "record"}。record は、通った場合も止まった
      場合も、封印係がこの試みの記録として ledger に書く中身（counting.md 4章 (3)）：
      {"may_seal", "reason", "ref_1b_seq", "chosen_order2_seq", "timing_check"}。
    """
    if not isinstance(order1b_seqs, list) or not all(type(x) is int for x in order1b_seqs) \
            or len(set(order1b_seqs)) != len(order1b_seqs):
        raise ValueError("order1b_seqs が、重ならない整数の一覧でない")
    if not isinstance(order2_records, list) or not isinstance(order3_attempts, list):
        raise ValueError("order2_records・order3_attempts が一覧でない")
    check_timing_check(timing_check)
    known = set(order1b_seqs)
    seqs = set(order1b_seqs)
    for r in order2_records:
        _check_order2_record(r)
        if type(r.get("ref_1b_seq")) is not int:
            raise ValueError("順番2の記録の ref_1b_seq が整数でない")
        if r["ref_1b_seq"] not in known:
            raise ValueError("順番2の記録の ref_1b_seq %d が、どの順番1b の記録にも無い" % r["ref_1b_seq"])
        if r["seq"] <= r["ref_1b_seq"]:
            raise ValueError("順番2の記録の seq %d が、参照した順番1b の記録の seq 以下" % r["seq"])
        if r["seq"] in seqs:
            raise ValueError("seq %d が重なっている" % r["seq"])
        seqs.add(r["seq"])
    for r in order3_attempts:
        _check_order3_attempt(r)
        if r["ref_1b_seq"] is None:
            if r["seq"] in seqs:
                raise ValueError("seq %d が重なっている" % r["seq"])
            seqs.add(r["seq"])
            continue
        if r["ref_1b_seq"] not in known:
            raise ValueError("順番3の試みの記録の ref_1b_seq %d が、どの順番1b の記録にも無い" % r["ref_1b_seq"])
        if r["seq"] <= r["ref_1b_seq"]:
            raise ValueError("順番3の試みの記録の seq %d が、参照した順番1b の記録の seq 以下" % r["seq"])
        if r["seq"] in seqs:
            raise ValueError("seq %d が重なっている" % r["seq"])
        seqs.add(r["seq"])

    def result(ok, ref, chosen, reason):
        rec = {"may_seal": ok, "reason": reason, "ref_1b_seq": ref,
               "chosen_order2_seq": None if chosen is None else chosen["seq"],
               "timing_check": timing_check}
        return {"may_seal": ok, "ref_1b_seq": ref, "chosen": chosen, "reason": reason, "record": rec}

    if not order1b_seqs:
        if timing_check["ref_1b_seq"] is not None:
            raise ValueError("順番1b の記録が無いのに、timing_check.ref_1b_seq が None でない")
        return result(False, None, None, "順番1b の記録が無い")
    ref = max(order1b_seqs)
    if timing_check["ref_1b_seq"] != ref:
        raise ValueError("timing_check.ref_1b_seq %r が、参照する順番1b の記録の seq %d と違う"
                         % (timing_check["ref_1b_seq"], ref))
    if any(r["ref_1b_seq"] == ref and not r["timing_ok"] for r in order3_attempts):
        return result(False, ref, None, "(a) 前の順番3の試みで、時機の条件の破れが記録されている（恒久に止まる）")
    if not timing_check["ok"]:
        return result(False, ref, None, "(a) 参照する順番1b の記録が時機の条件を満たさない（順番3の時点で確かめ直した）: "
                      + timing_check["reason"])
    mine = [r for r in order2_records if r["ref_1b_seq"] == ref]
    if any(r["status"] == "stopped" and r["stop_kind"] == "a" for r in mine):
        return result(False, ref, None, "(a) 時機の条件で止まった順番2の記録がある")
    chosen = select_order2_record([{k: r[k] for k in ("seq", "status", "stop_kind")} for r in mine])
    if chosen is None:
        return result(False, ref, None, "参照する順番1b の記録に対する順番2の記録が無い")
    chosen = next(r for r in mine if r["seq"] == chosen["seq"])
    return result(True, ref, chosen, None)


def order5_candidate_status(cid, totals, missing_days, days):
    """順番5で、候補 cid が手法を作る期間で計算できるか（T-036 差し戻し1回目 中-3。counting.md 4章 (3)）。

    totals：{日付: その候補の分母}。missing_days：欠けた日の集合。days：手法を作る期間の区画のすべての日。
    欠けた日でない日で分母が 0（または totals に値が無い）の日があれば、正式な候補なら "stop"（順番5を止める）、参考の候補なら "not_computable"
    （その候補だけ「計算できない（理由）」と記録し、順番5は止めない）。無ければ "ok"。
    """
    if cid not in _CAND:
        raise ValueError("候補の一覧に無い識別子: %r" % (cid,))
    zero = sorted(d for d in days if d not in missing_days and totals.get(d, 0) <= 0)
    official = (cid == OFFICIAL_CANDIDATE)
    if not zero:
        status = "ok"
    else:
        status = "stop" if official else "not_computable"
    return {"candidate": cid, "official": official, "status": status,
            "reason": ("欠けた日でない日に分母が 0 の日がある" if zero else None),
            "zero_days": [str(d) for d in zero]}


def coverage(summaries):
    """欄の手厚さ（T-036。順番2・順番5の記録に入れる）：入力の日々の合計で、すべての組の文書の数と、
    テーマが一つも付かない文書の数（V1・V2・どちらにも）。S の行が無ければ 0。"""
    out = {"docs_all_groups": sum(sum(s["docs"].values()) for s in summaries)}
    for key, name in sorted(S_UNCOVERED.items()):
        out[name] = sum(s["stats"].get(name, 0) for s in summaries)
    return out


def apply_all(summaries):
    """すべての基準の案を当てはめる。各案の結果に、該当なしのときの代わりを足した decided を付け、
    正式な基準の結果に official: true を付ける。"""
    out = {}
    for bid in CRITERIA_IDS:
        r = CRITERIA[bid](summaries)
        if r["candidate"] is not None:
            r["decided"], r["decided_by"] = r["candidate"], "criterion"
        else:
            fb = fallback_candidate(summaries, bid)
            r["decided"], r["decided_by"] = fb, ("fallback" if fb is not None else "none")
        r["official"] = False       # B1〜B5 はどれも参考（T-036）
        out[bid] = r
    return out


# ---------------------------------------------------------------------------
# 基準の入力を一つに決める（T-025 の監査の中2。T-028 差し戻し1回目 中3、2回目 中-B1・中-B2）
# ---------------------------------------------------------------------------

class InputNotReady(CountingError):
    """入力がまだそろっていない（待てばそろいうる）。"""


def day_file_name(mode, run_id, day):
    """gkg.day_file_name(run_id, day, mode) と同じ名前（テストで照合する）。"""
    if mode not in (TRIAL_MODE, OFFICIAL_MODE):
        raise ValueError("mode は trial か official")
    return "gkg-%s-%s-day-%s.tsv.gz" % (mode, run_id, day.replace("-", ""))


def trial_day_file_name(run_id, day):
    return day_file_name(TRIAL_MODE, run_id, day)


def _manifest_entries(manifest_bytes):
    out = []
    for raw in manifest_bytes.splitlines():
        if not raw.strip():
            continue
        try:
            e = json.loads(raw)
        except ValueError:
            raise CountingError("マニフェストに JSON でない行がある") from None
        if not isinstance(e, dict):
            raise CountingError("マニフェストに JSON の object でない行がある")
        out.append(e)
    return out


def _first_start(entries, mode):
    """最初の run-start の行と run_id。run-start が無ければ (None, None)。"""
    start = next((e for e in entries if e.get("kind") == "run-start"), None)
    if start is None:
        return None, None
    rid = start.get("run_id")
    if not isinstance(rid, str) or not _RUN_ID_RE.fullmatch(rid):
        raise CountingError("最初の run-start の run_id の形が違う")
    if start.get("mode") != mode or start.get("trial") is not (mode == TRIAL_MODE) \
            or start.get("official") is not (mode == OFFICIAL_MODE):
        raise CountingError("最初の run-start が %s の run の行でない" % mode)
    return start, rid


def _day_rows(entries, rid, mode, need_all):
    days = {}
    for e in entries:
        if e.get("run_id") != rid or e.get("kind") != "day":
            continue
        d = e.get("day")
        if mode == TRIAL_MODE and d not in TRIAL_DAYS:
            raise CountingError("試しの run の day の行に、TRIAL_DAYS の外の日がある")
        if d not in TRIAL_DAYS:
            continue                    # 正式な run のほかの日は使わない
        if d in days:
            raise CountingError("同じ日の day の行が二つある（%s）" % d)
        if e.get("mode") != mode:
            raise CountingError("day の行の mode が %s でない（%s）" % (mode, d))
        if e.get("file_name") != day_file_name(mode, rid, d):
            raise CountingError("day の行の file_name が決まった名前でない（%s）" % d)
        sha = e.get("sha256")
        if not isinstance(sha, str) or not _SHA_RE.fullmatch(sha):
            raise CountingError("day の行の sha256 の形が違う（%s）" % d)
        if "failed_files" in e and not isinstance(e["failed_files"], list):
            raise CountingError("day の行の failed_files が一覧でない（%s）" % d)
        days[d] = {"day": d, "file_name": e["file_name"], "sha256": sha}
    missing = [d for d in TRIAL_DAYS if d not in days]
    if missing:
        msg = "day の行が無い日がある: %s" % ", ".join(missing)
        raise (CountingError(msg) if need_all else InputNotReady(msg))
    return [days[d] for d in TRIAL_DAYS]


def select_trial_input(manifest_bytes):
    """試しの run のマニフェストから、1段目の入力を決める（counting.md 4章）。

    行の並びで最初の run-start の run_id を R とする（ほかの run は使わない）。
    run-start が無ければ {"status": "no_trial"}。R に run-complete が無ければ
    {"status": "not_complete", "run_id": R, "start_runs": 試しの run の run-start の run_id の種類の数,
    "day_rows": R の day の行の数}。終わっていれば、TRIAL_DAYS の各日の day の行がちょうど
    一つずつ（ほかの日は無い）、mode が trial、file_name が決まった名前、sha256 が16進64字であること
    （満たさなければ CountingError）を確かめ、{"status": "complete", "mode", "run_id", "days"} を返す。
    """
    entries = _manifest_entries(manifest_bytes)
    _start, rid = _first_start(entries, TRIAL_MODE)
    if rid is None:
        return {"status": "no_trial"}
    mine = [e for e in entries if e.get("run_id") == rid]
    if not any(e.get("kind") == "run-complete" for e in mine):
        start_runs = len({e.get("run_id") for e in entries if e.get("kind") == "run-start"})
        day_rows = sum(1 for e in mine if e.get("kind") == "day")
        return {"status": "not_complete", "run_id": rid, "start_runs": start_runs, "day_rows": day_rows}
    return {"status": "complete", "mode": TRIAL_MODE, "run_id": rid,
            "days": _day_rows(entries, rid, TRIAL_MODE, True)}


def official_start(manifest_bytes):
    """正式な run のマニフェストの最初の run-start の行（無ければ None）。"""
    start, _rid = _first_start(_manifest_entries(manifest_bytes), OFFICIAL_MODE)
    return start


def select_official_input(manifest_bytes):
    """正式な run の、TRIAL_DAYS と同じ3日の入力（2段目）。

    最初の run-start の run（gkg.official_run_id と同じ決め方）の、3日の day の行。run-complete は
    求めない。run-start が無いか、3日の day の行がそろっていなければ InputNotReady。
    """
    entries = _manifest_entries(manifest_bytes)
    _start, rid = _first_start(entries, OFFICIAL_MODE)
    if rid is None:
        raise InputNotReady("正式な run の run-start が無い")
    return {"mode": OFFICIAL_MODE, "run_id": rid,
            "days": _day_rows(entries, rid, OFFICIAL_MODE, False)}


def runs_record(trial_manifest, official_manifest):
    """二つの run の run_id と、3日の failed_files（counting.md 4章 (2) の「出力と記録に入れるもの」）。

    形：{mode: {"run_id": run_id か None, "failed_files": {日: day の行の failed_files の値} か None}}。
    - run_id と failed_files が None：その run の run-start が無い（またはマニフェストが読めない）。
    - failed_files の dict に日が無い：その日の day の行がまだ無い。
    - 日の値が []：day の行があり、取れなかったファイルが無い。値が None：day の行に failed_files の
      項目が無い。
    止まるかどうかは decide() が決める。ここは記録だけ。
    """
    out = {}
    for mode, data in ((TRIAL_MODE, trial_manifest), (OFFICIAL_MODE, official_manifest)):
        rec = {"run_id": None, "failed_files": None}
        try:
            entries = _manifest_entries(data) if data is not None else []
            _s, rid = _first_start(entries, mode)
        except CountingError:
            rid = None
        if rid is not None:
            rec["run_id"] = rid
            ff = {}
            for e in entries:
                if e.get("run_id") == rid and e.get("kind") == "day" and e.get("day") in TRIAL_DAYS:
                    ff[e["day"]] = e.get("failed_files")
            rec["failed_files"] = {d: ff[d] for d in TRIAL_DAYS if d in ff}
        out[mode] = rec
    return out


def check_prefix_versions(head_bytes, versions):
    """マニフェストのコミットされたすべての版が、HEAD の版の先頭と同じであること（追記だけ）。

    versions は、`git log --all --full-history --format=%H -- <マニフェスト>` の各 commit の版の
    バイト列（並び順は問わない。ファイルが無い版は b""）。一つでも先頭が合わなければ CountingError。
    """
    for v in versions:
        if not head_bytes.startswith(v):
            raise CountingError("マニフェストの過去の版が、HEAD の版の先頭と合わない"
                                "（コミットした行が書き換えられたか消された）")


def _load(sel, read_day_file):
    summaries, inputs = [], []
    for d in sel["days"]:
        data = read_day_file(sel["mode"], d["file_name"])
        sha = hashlib.sha256(data).hexdigest()
        if sha != d["sha256"]:
            raise CountingError("日の集計 %s の sha256 が、マニフェストの day の行と一致しない"
                                % d["file_name"])
        summaries.append(parse_day(data, expect_day=d["day"], expect_mode=sel["mode"]))
        inputs.append({"day": d["day"], "file_name": d["file_name"], "sha256": sha})
    return summaries, inputs


def _apply_input(sel, read_day_file):
    summaries, inputs = _load(sel, read_day_file)
    if not usable(summaries, OFFICIAL_CANDIDATE):
        raise CountingError("入力の3日で、正式な数え方 %s が計算できない" % OFFICIAL_CANDIDATE)
    return inputs, apply_all(summaries), [dict(coverage([s]), day=s["day"]) for s in summaries]


def decide(trial_manifest, official_manifest, read_day_file):
    """順番2の当てはめ（counting.md 4章 (2) の表）。

    trial_manifest・official_manifest：コミットした版のバイト列（ファイルが無ければ b""）。git の
      確かめ（作業ツリーと HEAD が同じ、過去の版が先頭と同じ）に通らなかったマニフェストは None。
    read_day_file(mode, file_name)：日の集計のバイト列を返す関数（無ければ例外）。
    status：
      "decided"  入力が決まり、正式な数え方 C7 が3日のどの日でも計算でき、参考の基準の案 B1〜B5 の結果
                 （どれも official: false）と、日ごとの欄の手厚さ（coverage）を出した
      "pending"  入力がまだそろっていない。そろってから同じ手順をもう一度行う（順番2の記録としては
                 数えない。select_order2_record()）
      "stopped"  止まる。参考の基準の結果と欄の手厚さは、この入力からは出さない。止まった事実を
                 記録して公開する（counting.md 4章 (3)。正式な数え方 C7 は順番1b で決まっているので
                 変わらない）。これは seal-order1.md 3章 (2) の (b) にあたる。(a)（時機の条件）と (c)
                 （コードの sha256）は、封印係が decide() の外で確かめる。
    2段目（正式な run の同じ3日）に進むのは、正式な run の run-start があり、かつ (i) 試しの run の
    run-start が一つも無いか、(ii) 試しの run の run-start が R の一つだけで、R に day の行が一つも無い
    ときだけ。R が終わっていないのに、R に day の行があるか、ほかの試しの run の run-start がある
    ときは止まる。
    ファイルが無い・sha256 が合わない・形の合わない集計・git の確かめに通らない・trial_run_ids や
    trial_manifest_sha256 が合わない・正式な数え方 C7 が計算できない、は2段目に進まず止まる。
    止まっても、新しい版の順番1b には進まない（正式な数え方 C7 は順番2の入力に依らない）。
    順番3を封印してよいか、どの記録を参照するかは order3_gate() で決める（counting.md 4章 (3)）。
    """
    runs = runs_record(trial_manifest, official_manifest)
    steps = []

    def out(status, **kw):
        d = {"proposed_label": PROPOSED_LABEL, "status": status, "steps": steps, "runs": runs,
             "official_candidate": OFFICIAL_CANDIDATE, "official_status": official_status()}
        d.update(kw)
        return d

    def stop(msg):
        steps.append({"step": "stop", "reason": msg})
        return out("stopped")

    if trial_manifest is None:
        return stop("試しの run のマニフェストが git の確かめに通らない")
    if official_manifest is None:
        return stop("正式な run のマニフェストが git の確かめに通らない")
    try:
        start = official_start(official_manifest)
        trial = select_trial_input(trial_manifest)
    except CountingError as e:
        return stop(str(e))
    if start is not None:
        # 正式な run が始まっている：試しの run のマニフェストが、開始のときのまま（中-B1）
        want = start.get("trial_manifest_sha256")
        have = hashlib.sha256(trial_manifest).hexdigest() if trial_manifest else None
        if want != have:
            return stop("試しの run のマニフェストの sha256 が、正式な run の run-start の "
                        "trial_manifest_sha256 と一致しない")
        ids = start.get("trial_run_ids")
        if not isinstance(ids, list):
            return stop("正式な run の run-start に trial_run_ids が無い")
        first = ids[0] if ids else None
        if first != trial.get("run_id"):
            return stop("正式な run の trial_run_ids の最初が、試しの run の最初の run と一致しない")
    if trial["status"] == "complete":
        steps.append({"step": TRIAL_MODE, "run_id": trial["run_id"]})
        try:
            inputs, results, cov = _apply_input(trial, read_day_file)
        except CountingError as e:  # ファイルが無い・読めない・sha256・頭の行・候補なし：止まる
            return stop("1段目の入力を使えない: %s" % e)
        return _decided(out, trial, inputs, results, cov)
    # 試しの run が無いか、終わっていない
    if start is None:
        steps.append({"step": "wait", "reason": trial["status"]})
        return out("pending")
    # 正式な run が始まっている。2段目に進むのは、試しの run の run-start が一つも無いか、
    # R に day の行が一つも無く、試しの run の run-start が R の一つだけのとき（T-028 差し戻し3回目 中-3）
    if trial["status"] == "not_complete":
        if trial["start_runs"] >= 2:
            return stop("試しの run の run-start が二つ以上あり、最初の run（R）が正式な run の開始までに"
                        "終わっていない")
        if trial["day_rows"] > 0:
            return stop("最初の試しの run（R）に day の行があるのに、正式な run の開始までに終わっていない")
    steps.append({"step": OFFICIAL_MODE, "reason": "trial_" + trial["status"]})
    try:
        sel = select_official_input(official_manifest)
    except InputNotReady as e:
        steps.append({"step": "wait", "reason": str(e)})
        return out("pending")
    except CountingError as e:
        return stop(str(e))
    try:
        inputs, results, cov = _apply_input(sel, read_day_file)
    except CountingError as e:
        return stop("2段目の入力を使えない: %s" % e)
    return _decided(out, sel, inputs, results, cov)


def _decided(out, sel, inputs, results, cov):
    return out("decided", input_mode=sel["mode"], input_run_id=sel["run_id"], inputs=inputs,
               results=results, coverage=cov)


# ---------------------------------------------------------------------------
# 機械可読の定義
# ---------------------------------------------------------------------------

def as_record():
    return {
        "proposed_label": PROPOSED_LABEL,
        "input_format": "src/collector/gkg.py section 6 day aggregate, header '# %s %s <day> <mode>'"
                        % (DAY_FORMAT_NAME, DAY_FORMAT_VERSION),
        "counted_groups": COUNTED_GROUP_RULE,
        "candidates": [
            {"id": cid, "numerator": "sum over counted groups of the T-row column %s, per theme" % col,
             "denominator": ("sum over counted groups of the D-row docs" if den == "docs" else
                             "sum over counted groups and all themes of the T-row column %s" % col),
             "numerator_column": col, "denominator_kind": den}
            for cid, col, den in CANDIDATES],
        "criteria": {
            "input": "three day aggregates (TRIAL_DAYS) chosen by decide(): step 1 the first trial run, "
                     "step 2 the official run's same three days; each file's sha256 must equal its day row",
            "output": "exactly one candidate id; if the criterion gives none, the first usable candidate in "
                      "FALLBACK_ORDER[criterion]",
            "B1": "field = V1 if docs_without_v1_theme <= docs_without_v2_theme (S rows, summed over the "
                  "three days) else V2; tie -> V1; candidate C2 (V1) or C4 (V2); none if total docs of all "
                  "groups is 0, if the chosen field has no themed document, or if the candidate is not "
                  "usable",
            "B2": "field as B1; candidate C1 (V1) or C3 (V2); none as B1",
            "B3": "C1 fixed; none if C1 is not usable",
            "B4": "q(d) = sum of v1_docs / counted docs per day; C2 if max q / min q > 11/10 else C1 "
                  "(equal -> C1); none if a day has no counted docs or min q is 0, or not usable",
            "B5": "R = sum of v2_mentions / sum of v2_docs over the three days; C4 if R <= 21/20 else C6; "
                  "none if sum of v2_docs is 0, or not usable",
            "usable": "for every input day, denominator > 0 and sum of numerator > 0",
            "comparison": "exact fractions, no rounding",
        },
        "criteria_ids": list(CRITERIA_IDS),
        "fallback_order": {k: list(v) for k, v in sorted(FALLBACK_ORDER.items())},
        "official_candidate": OFFICIAL_CANDIDATE,
        "official_status": official_status(),
        "owner_decision": dict(OWNER_DECISION),
        "decision_phrases": [list(x) for x in DECISION_PHRASES],
        "owner_approval_1b": dict(OWNER_APPROVAL_1B),
        "order3_gate": "order 3 references the order 1b record with the largest seq at the time of order 3 (same "
                       "rule as order 2) and counts only order 2 records that reference it; the sealer rechecks the "
                       "timing condition (a) for that order 1b record at order 3 and passes what it checked (F set "
                       "with parents, HEAD, git for-each-ref refs, worktree HEADs; F is counted over commits "
                       "reachable from those refs and worktree HEADs, the same as git log --all); every order 3 attempt, stopped or passed, is "
                       "recorded in the ledger with that content; once an attempt recorded a broken timing "
                       "condition, order 3 stays stopped for that order 1b record; if any of the order 2 records "
                       "stopped on (a), order 3 is not sealed; otherwise order2_record_rule (order3_gate)",
        "outside_owner_approval": "inside the owner's approval (item 3): when the timing condition is found "
                                  "broken, stop, publish (recording the stopped order 3 attempt) and leave the "
                                  "decision to the owner. Outside the approval, details added by the lead's "
                                  "assignment (T-038 to T-040): the smallest-seq rule for order 2 records, the "
                                  "largest-seq rule for the referenced order 1b record, counting only order 2 "
                                  "records whose ref_1b_seq is that record, rechecking the timing condition at "
                                  "order 3, recording passed order 3 attempts, and the content of the attempt "
                                  "record (timing_check, git bundle)",
        "order2_record_rule": "among the order 2 records for the referenced order 1b record, ignore status "
                              "pending; order 3 references the one with the smallest seq (decided, or stopped "
                              "of kind b or c); if there is none, order 3 is not sealed; if any of those records "
                              "stopped on the timing condition (a), whatever its seq, order 3 is not sealed and "
                              "the owner decides (select_order2_record, order3_gate)",
        "reference_only": "B1-B5 and every candidate other than the official one are references for "
                          "comparison, not official",
        "coverage": "S rows docs_without_v1_theme, docs_without_v2_theme, docs_without_any_theme (0 if absent) "
                    "and D of all groups, recorded in order 2 (per input day) and order 5 (per calendar "
                    "quarter of the period and for the whole period)",
        "trial_days": list(TRIAL_DAYS),
        "input_rule": {
            "manifests": "HEAD versions of the trial and official manifests; each must equal the working tree "
                         "file and every committed version must be a prefix of it; otherwise stopped",
            "official_started": "if the official run-start exists: sha256 of the trial manifest must equal its "
                                "trial_manifest_sha256 (None for an empty manifest) and trial_run_ids[0] must be "
                                "the first trial run-start's run_id (None if none); otherwise stopped",
            "step1": "first trial run-start gives R; if R has run-complete: its three day rows and files are the "
                     "input; any missing file, sha256 or header mismatch, malformed aggregate, or the "
                     "official candidate not usable on some day -> stopped",
            "wait": "no trial run-start, or R without run-complete, while the official run has not started -> "
                    "pending",
            "step2": "only if the official run has started and either there is no trial run-start, or the only "
                     "trial run-start is R's and R has no day row: the official run's three day rows; pending "
                     "until all three exist; any file or check failure -> stopped",
            "stop_unfinished": "if the official run has started and R has no run-complete while R has a day row "
                               "or another trial run-start exists -> stopped",
            "stopped": "the stop is recorded and published; it never leads to a new order 1b (the official "
                       "candidate does not depend on the order 2 input); order 3 references the order 2 record "
                       "chosen by order2_record_rule (except a stop on the timing condition (a)); reference "
                       "results and coverage come from order 5 instead",
            "order5": "a non-missing day with zero denominator: official candidate -> order 5 stops and is "
                      "reported; reference candidate -> recorded as not computable with the days, order 5 "
                      "continues (order5_candidate_status)",
            "authority": "the sealer's own run of this sealed code on the verified inputs is the result",
            "runs": "both run_ids and the three days' failed_files of both runs are in the output",
        },
        "no_translation": "groups ending with T are never counted (reviews/T-016.md: owner said plan a; "
                          "the lead recorded plan a as not using translated articles)",
    }


def canonical_json():
    return json.dumps(as_record(), ensure_ascii=False, sort_keys=True, indent=2) + "\n"


_NAME_RE = re.compile(r"\Agkg-(trial|official)-[0-9a-f]{16}-day-[0-9]{8}\.tsv\.gz\Z")
EXIT_CODES = {"decided": 0, "stopped": 1, "pending": 3}


def main(argv=None):
    if argv is None:
        argv = sys.argv[1:]
    if not argv:
        sys.stdout.write(canonical_json())
        return 0
    if len(argv) != 5 or argv[0] != "apply":
        sys.stderr.write("counting: 引数なしか、apply <試しの run のマニフェスト> <正式な run のマニフェスト> "
                         "<試しの run の保存先> <正式な run の保存先>（マニフェストが git の確かめに通らないときは "
                         "FAILED、HEAD にそのファイルが無いときは EMPTY と書く。読めないパスは止まる）\n")
        return 2

    def manifest(path):
        if path == "FAILED":
            return None
        if path == "EMPTY":
            return b""
        try:
            with open(path, "rb") as f:
                return f.read()
        except OSError:
            return None             # ファイルが無い・読めない：止まる（T-028 差し戻し3回目 軽-4）

    stores = {TRIAL_MODE: argv[3], OFFICIAL_MODE: argv[4]}

    def read_day_file(mode, name):
        m = _NAME_RE.fullmatch(name)
        if not m or m.group(1) != mode:
            raise CountingError("日の集計の名前の形が違う")
        try:
            with open(stores[mode].rstrip("/") + "/" + name, "rb") as f:
                return f.read()
        except OSError as e:
            raise CountingError("日の集計を読めない: %s" % e) from None

    out = decide(manifest(argv[1]), manifest(argv[2]), read_day_file)
    sys.stdout.write(json.dumps(out, ensure_ascii=False, sort_keys=True, indent=2) + "\n")
    return EXIT_CODES[out["status"]]


if __name__ == "__main__":
    sys.exit(main())
