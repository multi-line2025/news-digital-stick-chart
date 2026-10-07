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
  r(d) = 分子 / 分母。どの候補も、翻訳の印 T の付いた組 g（"1T" など）を数えない。出どころは
  reviews/T-016.md（コミット 4e7c511）：オーナーの発言は「翻訳の記事については案aで良いです」で、
  案a の中身（v0 では翻訳の記事を使わない）は、同じ節のリードの理解の行にある。数える組は
  COUNTED_GROUP_RULE（g の最後の文字が T でないもの。形の違う X も含む）。
    分子：日の集計の T の行の、v1_docs・v2_docs・v2_mentions のどれか一つの欄を、数える組で
          足したもの（テーマごと）。
    分母："docs"（D の行の文書数を、数える組で足したもの）か、"same"（分子と同じ欄を、
          数える組とすべてのテーマで足したもの）。

基準の案（CRITERIA）
  入力は3日分（TRIAL_DAYS）の日の集計。どの run の集計にするかは decide() の規則（1段目は最初の
  試しの run、2段目は正式な run の同じ3日）で、マニフェストだけから決まる。出力は候補の識別子
  ちょうど一つ。基準が該当なしなら FALLBACK_ORDER の順で使える最初の候補（apply_all の decided）。
  比べるのは分数（fractions.Fraction）で、丸めは入れない。

使い方
  .venv/bin/python -B src/stats/counting.py
      候補と基準の案の定義を JSON（キー順・UTF-8）で出力する（データは読まない）
  .venv/bin/python -B src/stats/counting.py apply <試しの run のマニフェスト> <正式な run のマニフェスト>
          <試しの run の保存先> <正式な run の保存先>
      順番2の当てはめ（封印係が当てはめ直すときに使う）。マニフェストは、git の確かめに通った
      コミットした版を渡す（通らなければ FAILED と書く）。結果を JSON で出力する。終了コードは
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
DAY_FORMAT_VERSION = "2"
TRIAL_MODE = "trial"
OFFICIAL_MODE = "official"
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
RECOMMENDED_CRITERION = "B2"      # T-028 差し戻し1回目で B1 から変えた（counting.md 3章 (3)）
OFFICIAL_CRITERION = None          # オーナーが決める。決まるまで None（"undecided"）
B4_SPREAD_LIMIT = Fr(11, 10)       # 1日あたりのテーマの数の、最大と最小の比の上限
B5_MENTION_LIMIT = Fr(21, 20)      # 言及の回数と文書の数の比の上限
# 基準の結果が該当なしのときの代わり：この順で、入力のすべての日で使える最初の候補（T-028 差し戻し1回目 中3）
FALLBACK_ORDER = ("C1", "C3", "C2", "C4", "C5", "C6")


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


def fallback_candidate(summaries):
    """基準の結果が該当なしのときの代わり（T-028 差し戻し1回目 中3）。

    FALLBACK_ORDER の順で、入力のすべての日で使える（usable）最初の候補。どれも使えなければ None。
    """
    for cid in FALLBACK_ORDER:
        if usable(summaries, cid):
            return cid
    return None


def apply_all(summaries):
    """すべての基準の案を当てはめる。各案の結果に、該当なしのときの代わりを足した decided を付け、
    正式な基準の結果に official: true を付ける。"""
    out = {}
    fb = fallback_candidate(summaries)
    for bid in CRITERIA_IDS:
        r = CRITERIA[bid](summaries)
        if r["candidate"] is not None:
            r["decided"], r["decided_by"] = r["candidate"], "criterion"
        else:
            r["decided"], r["decided_by"] = fb, ("fallback" if fb is not None else "none")
        r["official"] = (bid == OFFICIAL_CRITERION)
        out[bid] = r
    return out


# ---------------------------------------------------------------------------
# 基準の入力を一つに決める（T-025 の監査の中2。T-028 差し戻し1回目 中3 で、止まったあとの行き先を足した）
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
    start = next((e for e in entries if e.get("kind") == "run-start"), None)
    if start is None:
        raise InputNotReady("%s のマニフェストに run-start が無い" % mode)
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
        days[d] = {"day": d, "file_name": e["file_name"], "sha256": sha}
    missing = [d for d in TRIAL_DAYS if d not in days]
    if missing:
        msg = "day の行が無い日がある: %s" % ", ".join(missing)
        raise (CountingError(msg) if need_all else InputNotReady(msg))
    return [days[d] for d in TRIAL_DAYS]


def select_trial_input(manifest_bytes):
    """試しの run のマニフェスト（コミットした版のバイト列）から、1段目の入力を決める（counting.md 4章）。

    1. 行の並びで最初の run-start の run_id を R とする。ほかの run は使わない。run-start が無ければ
       InputNotReady。
    2. その run-start の mode が trial、trial が true、official が false。
    3. R の run-complete の行が無ければ InputNotReady。
    4. R の day の行が TRIAL_DAYS の各日にちょうど一つずつ（ほかの日は無い）、mode が trial、file_name が
       決まった名前、sha256 が16進64字。満たさなければ CountingError。
    戻り値：{"mode", "run_id", "days": [{"day", "file_name", "sha256"}]}（TRIAL_DAYS の順）
    """
    entries = _manifest_entries(manifest_bytes)
    _start, rid = _first_start(entries, TRIAL_MODE)
    mine = [e for e in entries if e.get("run_id") == rid]
    if not any(e.get("kind") == "run-complete" for e in mine):
        raise InputNotReady("最初の試しの run（%s）が run-complete まで終わっていない" % rid)
    return {"mode": TRIAL_MODE, "run_id": rid, "days": _day_rows(entries, rid, TRIAL_MODE, True)}


def select_official_input(manifest_bytes):
    """正式な run のマニフェストから、2段目の入力（正式な run の、TRIAL_DAYS と同じ3日の集計）を決める。

    最初の run-start の run（正式な run。gkg.official_run_id と同じ決め方）の、TRIAL_DAYS の3日の
    day の行。run-complete は求めない。日がそろっていなければ InputNotReady。
    """
    entries = _manifest_entries(manifest_bytes)
    _start, rid = _first_start(entries, OFFICIAL_MODE)
    return {"mode": OFFICIAL_MODE, "run_id": rid,
            "days": _day_rows(entries, rid, OFFICIAL_MODE, False)}


def official_trial_run_ids(official_manifest_bytes):
    """正式な run の最初の run-start の trial_run_ids（run-start が無ければ None）。"""
    entries = _manifest_entries(official_manifest_bytes)
    start = next((e for e in entries if e.get("kind") == "run-start"), None)
    if start is None:
        return None
    ids = start.get("trial_run_ids")
    if not isinstance(ids, list):
        raise CountingError("正式な run の run-start に trial_run_ids が無い")
    return ids


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


def decide(trial_manifest, official_manifest, read_day_file):
    """順番2の当てはめ（counting.md 4章の行き先の表）。

    trial_manifest・official_manifest：コミットした版のバイト列（ファイルが無ければ b""）。git の
      確かめ（作業ツリーと HEAD が同じ、過去の版が先頭と同じ）に通らなかったマニフェストは None を渡す。
    read_day_file(mode, file_name)：日の集計のバイト列を返す関数。
    戻り値の status：
      "decided"  入力が決まり、正式な基準（決まっていなければ、すべての案）を当てはめた
      "pending"  入力がまだそろっていない。そろってから同じ手順をもう一度行う
      "stopped"  どの段でも決まらない。新しい版の順番1b へ（counting.md 4章 (3)）
    """
    tiers = []
    official_started = None
    if official_manifest is not None:
        try:
            official_started = official_trial_run_ids(official_manifest) is not None
        except CountingError as e:
            tiers.append({"tier": "official_manifest", "error": str(e)})
            official_manifest = None
    # 1段目：試しの run
    t1 = {"tier": TRIAL_MODE}
    tiers.append(t1)
    if trial_manifest is None:
        t1["error"] = "試しの run のマニフェストが git の確かめに通らない"
    else:
        try:
            sel = select_trial_input(trial_manifest)
            if official_started:
                ids = official_trial_run_ids(official_manifest)
                if not ids or ids[0] != sel["run_id"]:
                    raise CountingError("正式な run の trial_run_ids の最初が R でない")
            summaries, inputs = _load(sel, read_day_file)
            results = apply_all(summaries)
            if fallback_candidate(summaries) is None:
                raise CountingError("試しの run の入力で、使える候補が一つも無い")
            return _decided(sel, inputs, results, tiers)
        except InputNotReady as e:
            if not official_started:
                t1["error"] = str(e)
                return _out("pending", tiers)
            t1["error"] = "正式な run が始まった時点で、試しの run の入力がそろっていない: %s" % e
        except CountingError as e:
            t1["error"] = str(e)
    # 2段目：正式な run の同じ3日
    t2 = {"tier": OFFICIAL_MODE}
    tiers.append(t2)
    if official_manifest is None:
        t2["error"] = "正式な run のマニフェストが git の確かめに通らない"
        return _out("stopped", tiers)
    try:
        sel = select_official_input(official_manifest)
        summaries, inputs = _load(sel, read_day_file)
        results = apply_all(summaries)
        if fallback_candidate(summaries) is None:
            raise CountingError("正式な run の同じ3日の入力で、使える候補が一つも無い")
        return _decided(sel, inputs, results, tiers)
    except InputNotReady as e:
        t2["error"] = str(e)
        return _out("pending", tiers)
    except CountingError as e:
        t2["error"] = str(e)
        return _out("stopped", tiers)


def _out(status, tiers, **kw):
    d = {"proposed_label": PROPOSED_LABEL, "status": status, "tiers": tiers,
         "official_criterion": OFFICIAL_CRITERION,
         "official_criterion_status": official_criterion_status()}
    d.update(kw)
    return d


def _decided(sel, inputs, results, tiers):
    tiers[-1]["used"] = True
    official = results[OFFICIAL_CRITERION]["decided"] if OFFICIAL_CRITERION else None
    return _out("decided", tiers, input_mode=sel["mode"], input_run_id=sel["run_id"], inputs=inputs,
                results=results, official_candidate=official)


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
            "input": "three day aggregates (TRIAL_DAYS) chosen by decide(): tier 1 the first trial run, "
                     "tier 2 the official run's same three days; each file's sha256 must equal its day row",
            "output": "exactly one candidate id; if the criterion gives none, the first usable candidate in "
                      "FALLBACK_ORDER",
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
        "fallback_order": list(FALLBACK_ORDER),
        "recommended_criterion": RECOMMENDED_CRITERION,
        "official_criterion": OFFICIAL_CRITERION,
        "official_criterion_status": official_criterion_status(),
        "trial_days": list(TRIAL_DAYS),
        "input_rule": {
            "tier1": "first run-start line of the committed trial manifest gives run R; R must be trial, "
                     "have run-complete, and exactly one day row for each TRIAL_DAYS day with the fixed "
                     "file name; no other trial run is used; if the official run has started, its "
                     "trial_run_ids[0] must be R",
            "tier1_wait": "if R is not complete (or there is no trial run-start) and the official run has "
                          "not started: pending; once the official run-start exists, tier 1 fails",
            "tier2": "first run-start of the committed official manifest gives run O; O's day rows for the "
                     "TRIAL_DAYS days (pending until all three exist)",
            "tier_fail": "tier 1 fails on any check (git, manifest, sha256, header, no usable candidate) "
                         "-> tier 2; tier 2 fails -> stopped -> new version of order 1b",
            "git": "every committed version of each manifest must be a prefix of the HEAD version; the "
                   "working tree file must equal the HEAD version; otherwise the manifest is treated as "
                   "failing (None)",
            "authority": "the sealer's own run of this sealed code on the verified inputs is the result",
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
                         "FAILED と書く。ファイルが無ければ空として読む）\n")
        return 2

    def manifest(path):
        if path == "FAILED":
            return None
        try:
            with open(path, "rb") as f:
                return f.read()
        except FileNotFoundError:
            return b""

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
