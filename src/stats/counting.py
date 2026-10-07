#!/usr/bin/env python3
"""報道量の数え方の候補と、候補から一つを選ぶ基準の案（T-028。順番1b で封印する提案）。

文書は docs/stats/counting.md。ここの定数と関数が正本で、文書の表はその写しである
（tests/stats/test_counting.py で照合する）。

- この版は「提案」で、オーナーの承認のあと封印係が順番1b で封印する。統計係は封印しない。
- 正式に使う基準はオーナーが決める。決まるまで OFFICIAL_CRITERION は None で、
  official_criterion_status() は "undecided" を返す。"undecided" のまま封印しない
  （docs/stats/seal-order1.md 3章 (3) の4）。
- GKG のデータ、区分表、ネットワークには触れていない。このモジュールは現在の日時を読まない。
- 入力の形は、収集係の日の集計（src/collector/gkg.py 6章、serialize_day が書く形。形式の版
  "gkg-day" 2）である。gkg.py は読み込まない（取り込むと、収集係のコードが変わったときに、この
  ファイルの sha256 が同じでも結果が変わりうるため）。形が合うことは、テストが gkg.serialize_day
  で作った日の集計で確かめる。

候補（CANDIDATES）
  r(d) = 分子 / 分母。どの候補も、翻訳の印 T の付いた組 g（"1T" など）を数えない（オーナーの
  決定、案a。reviews/T-016.md）。数える組は COUNTED_GROUP_RULE（g の最後の文字が T でないもの。
  形の違う X も含む）。
    分子：日の集計の T の行の、v1_docs・v2_docs・v2_mentions のどれか一つの欄を、数える組で
          足したもの（テーマごと）。
    分母："docs"（D の行の文書数を、数える組で足したもの）か、"same"（分子と同じ欄を、
          数える組とすべてのテーマで足したもの）。

基準の案（CRITERIA）
  入力は、試しの run の3日分の日の集計（TRIAL_DAYS）。どれの入力にするかは select_trial_input()
  の規則で、試しの run のマニフェストだけから決まる。出力は候補の識別子ちょうど一つか、
  None（該当なし。順番2を封印しない）。比べるのは分数（fractions.Fraction）で、丸めは入れない。

使い方
  .venv/bin/python -B src/stats/counting.py
      候補と基準の案の定義を JSON（キー順・UTF-8）で出力する（データは読まない）
  .venv/bin/python -B src/stats/counting.py apply <試しの run のマニフェスト> <日の集計のフォルダ>
      順番2の当てはめ（封印係が当てはめ直すときに使う）。マニフェストの規則で入力を決め、
      日の集計の sha256 をマニフェストの day の行と照らし、すべての基準の案を当てはめた結果を
      JSON で出力する。照らせなければ終了コード 1 で止まる。
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
DAY_FORMAT_VERSION = "2"
TRIAL_MODE = "trial"
# gkg.TRIAL_DAYS と同じ（tests/stats/test_counting.py で照合する）
TRIAL_DAYS = ("2015-03-02", "2015-03-03", "2015-03-04")
TRIAL_MANIFEST_PATH = "data/manifest/gdelt-gkg-trial.jsonl"
COLUMNS = ("v1_docs", "v2_docs", "v2_mentions")       # T の行の3つの数の欄（この順）
DENOMINATORS = ("docs", "same")
S_UNCOVERED = {"V1": "docs_without_v1_theme", "V2": "docs_without_v2_theme"}

COUNTED_GROUP_RULE = "g does not end with 'T' (translated documents are not counted; 'X' is counted)"

_RUN_ID_RE = re.compile(r"\A[0-9a-f]{16}\Z")
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
)
CANDIDATE_IDS = tuple(c[0] for c in CANDIDATES)
_CAND = {c[0]: (c[1], c[2]) for c in CANDIDATES}

# ---------------------------------------------------------------------------
# 基準の案
# ---------------------------------------------------------------------------

CRITERIA_IDS = ("B1", "B2", "B3", "B4", "B5")
RECOMMENDED_CRITERION = "B1"
OFFICIAL_CRITERION = None          # オーナーが決める。決まるまで None（"undecided"）
B4_SPREAD_LIMIT = Fr(11, 10)       # 1日あたりのテーマの数の、最大と最小の比の上限
B5_MENTION_LIMIT = Fr(21, 20)      # 言及の回数と文書の数の比の上限


def official_criterion_status():
    if OFFICIAL_CRITERION is None:
        return "undecided"
    if OFFICIAL_CRITERION not in CRITERIA_IDS:
        raise ValueError("OFFICIAL_CRITERION が基準の案の一覧に無い")
    return "decided"


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

    読む行：頭の行（#）、V、D、T、S。ほかの行（F、FD、C、L、P1、P2、NC、NL、E）は読み飛ばす。
    戻り値：{"day", "mode", "docs": {g: n}, "themes": {名前: {g: (v1_docs, v2_docs, v2_mentions)}},
             "stats": {名前: n}}
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
        raise CountingError("頭の行の形式が gkg-day 2 でない")
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
                if len(f) != 5:
                    raise CountingError("T の行の欄の数が違う")
                t_rows.append((f[0], _int(f[1], "T の番号"),
                               tuple(_int(x, "T の数") for x in f[2:5])))
            elif tag == "S":
                f = rest.split("\t")
                if len(f) != 2:
                    raise CountingError("S の行の欄の数が違う")
                if f[0] in stats:
                    raise CountingError("S の行の名前が重なっている")
                stats[f[0]] = _int(f[1], "S の数")
    except (OSError, EOFError, UnicodeDecodeError) as e:
        raise CountingError("日の集計を読めない: %s" % e) from None
    themes = {}
    for g, i, nums in t_rows:
        if i not in vocab:
            raise CountingError("T の行の番号が V に無い")
        per_g = themes.setdefault(vocab[i], {})
        if g in per_g:
            raise CountingError("T の行の（組、テーマ）が重なっている")
        if g not in docs:
            raise CountingError("T の行の組が D に無い")
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
    分けていないため。docs/stats/counting.md 3章）。
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
    """B1（おすすめ）：欄はテーマの付かない文書が少ない方（同じなら V1）。単位は文書。分母は同じ単位の和。"""
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


def apply_all(summaries):
    """すべての基準の案を当てはめる。正式な基準の結果に official: true を付ける。"""
    out = {}
    for bid in CRITERIA_IDS:
        r = CRITERIA[bid](summaries)
        r["official"] = (bid == OFFICIAL_CRITERION)
        out[bid] = r
    return out


# ---------------------------------------------------------------------------
# 基準の入力を、試しの run のマニフェストから一つに決める（T-025 の監査の中2）
# ---------------------------------------------------------------------------

def trial_day_file_name(run_id, day):
    """gkg.day_file_name(run_id, day, "trial") と同じ名前（テストで照合する）。"""
    return "gkg-%s-%s-day-%s.tsv.gz" % (TRIAL_MODE, run_id, day.replace("-", ""))


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


def select_trial_input(manifest_bytes):
    """試しの run のマニフェスト（コミットした版のバイト列）から、基準の入力を一つに決める。

    規則（docs/stats/counting.md 4章）
      1. 行の並びで最初の kind == "run-start" の行の run_id を R とする。R の run だけを使い、
         ほかの run は使わない（ほかの run の結果が良くても代えない）。
      2. その run-start の mode が "trial"、trial が true であること。
      3. R の run-complete の行があること。
      4. R の day の行が、TRIAL_DAYS の各日についてちょうど一つずつあり、ほかの日が無いこと。
         各行の mode が "trial"、file_name が trial_day_file_name(R, 日)、sha256 が16進64字。
    どれか一つでも満たさなければ CountingError（順番2を封印しない）。
    戻り値：{"run_id": R, "days": [{"day", "file_name", "sha256"}]}（TRIAL_DAYS の順）
    """
    entries = _manifest_entries(manifest_bytes)
    start = next((e for e in entries if e.get("kind") == "run-start"), None)
    if start is None:
        raise CountingError("試しの run のマニフェストに run-start が無い")
    rid = start.get("run_id")
    if not isinstance(rid, str) or not _RUN_ID_RE.fullmatch(rid):
        raise CountingError("最初の run-start の run_id の形が違う")
    if start.get("mode") != TRIAL_MODE or start.get("trial") is not True:
        raise CountingError("最初の run-start が試しの run の行でない")
    mine = [e for e in entries if e.get("run_id") == rid]
    if not any(e.get("kind") == "run-complete" for e in mine):
        raise CountingError("最初の試しの run（%s）が run-complete まで終わっていない" % rid)
    days = {}
    for e in mine:
        if e.get("kind") != "day":
            continue
        d = e.get("day")
        if d not in TRIAL_DAYS:
            raise CountingError("試しの run の day の行に、TRIAL_DAYS の外の日がある")
        if d in days:
            raise CountingError("試しの run に、同じ日の day の行が二つある（%s）" % d)
        if e.get("mode") != TRIAL_MODE:
            raise CountingError("day の行の mode が trial でない（%s）" % d)
        if e.get("file_name") != trial_day_file_name(rid, d):
            raise CountingError("day の行の file_name が決まった名前でない（%s）" % d)
        sha = e.get("sha256")
        if not isinstance(sha, str) or not _SHA_RE.fullmatch(sha):
            raise CountingError("day の行の sha256 の形が違う（%s）" % d)
        days[d] = {"day": d, "file_name": e["file_name"], "sha256": sha}
    missing = [d for d in TRIAL_DAYS if d not in days]
    if missing:
        raise CountingError("試しの run の day の行が無い日がある: %s" % ", ".join(missing))
    return {"run_id": rid, "days": [days[d] for d in TRIAL_DAYS]}


def check_prefix_versions(head_bytes, versions):
    """マニフェストのコミットされたすべての版が、HEAD の版の先頭と同じであること（追記だけ）。

    versions は、`git log --all --full-history --format=%H -- <マニフェスト>` の各 commit の版の
    バイト列（並び順は問わない。ファイルが無い版は b""）。一つでも先頭が合わなければ CountingError。
    """
    for v in versions:
        if not head_bytes.startswith(v):
            raise CountingError("試しの run のマニフェストの過去の版が、HEAD の版の先頭と合わない"
                                "（コミットした行が書き換えられたか消された）")


def apply_to_inputs(manifest_bytes, read_day_file):
    """順番2の当てはめ。read_day_file(file_name) は日の集計のバイト列を返す関数。

    1. select_trial_input() で入力を決める。
    2. 各日のファイルの sha256 が、マニフェストの day の行の sha256 と一致すること。
    3. 頭の行の日と mode が合うこと。
    4. すべての基準の案を当てはめる。
    """
    sel = select_trial_input(manifest_bytes)
    summaries = []
    inputs = []
    for d in sel["days"]:
        data = read_day_file(d["file_name"])
        sha = hashlib.sha256(data).hexdigest()
        if sha != d["sha256"]:
            raise CountingError("日の集計 %s の sha256 が、マニフェストの day の行と一致しない"
                                % d["file_name"])
        summaries.append(parse_day(data, expect_day=d["day"], expect_mode=TRIAL_MODE))
        inputs.append({"day": d["day"], "file_name": d["file_name"], "sha256": sha})
    return {
        "proposed_label": PROPOSED_LABEL,
        "trial_run_id": sel["run_id"],
        "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
        "inputs": inputs,
        "official_criterion": OFFICIAL_CRITERION,
        "official_criterion_status": official_criterion_status(),
        "results": apply_all(summaries),
    }


# ---------------------------------------------------------------------------
# 機械可読の定義
# ---------------------------------------------------------------------------

def as_record():
    return {
        "proposed_label": PROPOSED_LABEL,
        "input_format": "src/collector/gkg.py section 6 day aggregate, header '# gkg-day 2 <day> <mode>'",
        "counted_groups": COUNTED_GROUP_RULE,
        "candidates": [
            {"id": cid, "numerator": "sum over counted groups of the T-row column %s, per theme" % col,
             "denominator": ("sum over counted groups of the D-row docs" if den == "docs" else
                             "sum over counted groups and all themes of the T-row column %s" % col),
             "numerator_column": col, "denominator_kind": den}
            for cid, col, den in CANDIDATES],
        "criteria": {
            "input": "the three trial day aggregates (TRIAL_DAYS) chosen by select_trial_input() from the "
                     "committed trial manifest; each file's sha256 must equal its day row",
            "output": "exactly one candidate id, or none (order 2 is not sealed)",
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
        "recommended_criterion": RECOMMENDED_CRITERION,
        "official_criterion": OFFICIAL_CRITERION,
        "official_criterion_status": official_criterion_status(),
        "trial_days": list(TRIAL_DAYS),
        "trial_input_rule": "first run-start line of the committed trial manifest gives run R; R must be "
                            "trial, have run-complete, and exactly one day row for each TRIAL_DAYS day with "
                            "the fixed file name; no other run is used; every committed version of the "
                            "manifest must be a prefix of the HEAD version",
        "no_translation": "groups ending with T are never counted (owner decision, plan a, reviews/T-016.md)",
    }


def canonical_json():
    return json.dumps(as_record(), ensure_ascii=False, sort_keys=True, indent=2) + "\n"


_NAME_RE = re.compile(r"\Agkg-trial-[0-9a-f]{16}-day-[0-9]{8}\.tsv\.gz\Z")


def main(argv=None):
    if argv is None:
        argv = sys.argv[1:]
    if not argv:
        sys.stdout.write(canonical_json())
        return 0
    if len(argv) != 3 or argv[0] != "apply":
        sys.stderr.write("counting: 引数なしか、apply <マニフェスト> <日の集計のフォルダ>\n")
        return 2
    manifest_path, store = argv[1], argv[2]
    with open(manifest_path, "rb") as f:
        manifest_bytes = f.read()

    def read_day_file(name):
        if not _NAME_RE.fullmatch(name):
            raise CountingError("日の集計の名前の形が違う")
        with open(store.rstrip("/") + "/" + name, "rb") as f:
            return f.read()

    try:
        out = apply_to_inputs(manifest_bytes, read_day_file)
    except (CountingError, OSError) as e:
        sys.stderr.write("counting: 止まった: %s\n" % e)
        return 1
    sys.stdout.write(json.dumps(out, ensure_ascii=False, sort_keys=True, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
