#!/usr/bin/env python3
"""順番5（タグの一覧の結果）の計算し直し（T-111）。統計係の src/stats/order5.py は使わない。

docs/stats/order5-tag-list.md 5章（第三者が order5.py に頼らずに計算し直す手順）のとおりに、封印済みの
src/stats/tagrules.py（stats-order1）・counting.py（stats-order1b）と、封印済みの入力（seq 12 のマニフェストの day の行、
seq 15 の欠けた日、区分表の result の行のファイル）だけから、main の正式な一覧と要約を計算する。

このファイルは、封印係の verify（verify.recompute_order5）が、封印済みの版のファイルだけを置いた空のフォルダに、このファイルの
バイト列と一緒に書き出して、-I・-B・空の pycache_prefix の Python で流す（引数は下の main）。照らす（main と比べる）のは
呼ぶ側で、このファイルは計算するだけ。

使い方（verify が使う形）：
    python -I -B -X pycache_prefix=<空> order5_recompute.py <書き出したフォルダ> <入力の JSON> <日の集計の置き場所>
      <区分表のファイル>
入力の JSON：{"block": [始め, 終わり], "missing_days": [日...], "rows": [{"day", "file_name", "sha256"}...],
             "themes_sha256": 区分表のファイルの sha256, "themes_rows": 行数}
標準出力：計算した値の JSON（compute() の返り値）。標準エラー：止まった理由だけ。
"""

import array
import collections.abc
import datetime
import fractions
import hashlib
import json
import os
import sys
import types

TABLE_HEADER = "THEME"


class RecomputeError(Exception):
    pass


def load(name, path, data, deps=()):
    """バイト列 data を compile して name のモジュールにする（import の仕組みを通さない）。deps は exec のあいだだけ置く。"""
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


def load_sealed(folder):
    """書き出したフォルダから、封印済みの版を読み込む。返り値：{"periods", "exclusion", "tagrules", "counting",
    "tagrules_1cb463a"}。sha256 は書き出した側（verify）が照らした。"""
    def rd(rel):
        with open(os.path.join(folder, *rel.split("/")), "rb") as f:
            return f.read()
    out = {}
    out["periods"] = load("periods", "src/stats/periods.py", rd("src/stats/periods.py"))
    out["exclusion"] = load("exclusion", "src/stats/exclusion.py", rd("src/stats/exclusion.py"))
    out["tagrules"] = load("tagrules", "src/stats/tagrules.py", rd("src/stats/tagrules.py"),
                           deps=(("exclusion", out["exclusion"]),))
    out["counting"] = load("counting", "src/stats/counting.py", rd("src/stats/counting.py"))
    out["tagrules_1cb463a"] = load("tagrules_1cb463a", "1cb463a:src/stats/tagrules.py", rd("v1cb463a/tagrules.py"))
    return out


class _Series(collections.abc.Mapping):
    """一つのテーマ・一つの欄の {日付: 件数}（0 の日は入れない）。触れたときだけ dict にする（一度に一つ）。"""

    __slots__ = ("_t", "_name", "_k")

    def __init__(self, table, name, k):
        self._t, self._name, self._k = table, name, k

    def _d(self):
        c = self._t.cache
        if c[0] is not self:
            ix, vals = self._t.rows[self._name]
            dates = self._t.dates
            c[1] = {dates[i]: v for i, v in zip(ix, vals[self._k]) if v}
            c[0] = self
        return c[1]

    def __getitem__(self, x):
        return self._d()[x]

    def __iter__(self):
        return iter(self._d())

    def __len__(self):
        return len(self._d())


class Table:
    """日ごとの分子（欄ごと・テーマごと）と分母（候補ごと）と欄の手厚さ。分子と分母は counting.candidate_counts だけで数える。"""

    def __init__(self, counting, dates):
        self.c = counting
        self.dates = list(dates)
        self.index = {d: i for i, d in enumerate(self.dates)}
        self.cols = list(counting.COLUMNS)
        self.col_of = {cid: col for cid, col, _den in counting.CANDIDATES}
        self.rows = {}
        self.totals = {cid: {} for cid in counting.CANDIDATE_IDS}
        self.coverage = {}
        self.cache = [None, None]

    def add(self, day, summary):
        i = self.index[day]
        by_col = {}
        for cid in self.c.CANDIDATE_IDS:
            counts, total = self.c.candidate_counts(summary, cid)
            col = self.col_of[cid]
            if col in by_col and by_col[col] != counts:
                raise RecomputeError("%s：分子の欄が同じ候補の分子が違う" % day)
            by_col.setdefault(col, counts)
            self.totals[cid][day] = total
        names = set()
        for counts in by_col.values():
            names.update(counts)
        for name in names:
            r = self.rows.get(name)
            if r is None:
                r = self.rows[name] = (array.array("H"), [array.array("Q") for _ in self.cols])
            r[0].append(i)
            for k, col in enumerate(self.cols):
                r[1][k].append(by_col.get(col, {}).get(name, 0))
        self.coverage[day] = self.c.coverage([summary])

    def counts(self, cid):
        k = self.cols.index(self.col_of[cid])
        return {name: _Series(self, name, k) for name, r in sorted(self.rows.items()) if any(r[1][k])}


def _days(start, end):
    out, d = [], start
    while d <= end:
        out.append(d)
        d += datetime.timedelta(days=1)
    return out


def _json(x):
    return json.loads(json.dumps(x, ensure_ascii=False, sort_keys=True, allow_nan=False))


def read_themes(data, sha, rows):
    """区分表のファイル（themes.build_output の形）：sha256 と頭の行と行数を照らし、名前の一覧を返す。"""
    if hashlib.sha256(data).hexdigest() != sha:
        raise RecomputeError("区分表のファイルの sha256 が、result の行と違う")
    text = data.decode("utf-8")
    if not text.endswith("\n"):
        raise RecomputeError("区分表のファイルの最後に改行が無い")
    lines = text[:-1].split("\n")
    if lines[0] != TABLE_HEADER or len(lines) - 1 != rows:
        raise RecomputeError("区分表のファイルの頭の行か行数が違う")
    return lines[1:]


def compute(mods, inp, read_day, themes_data):
    """計算し直す。read_day(file_name) は日の集計のバイト列を返す。返り値（JSON にできる形）：
      status（ok・stopped）、themes_table（名前の数・重なった行・日の集計の名前の形に合わない名前・データにあって区分表に無い名前の数）、
      candidates（C1〜C7：status・reason・zero_days・n_med・a・a_float・usable_day_count・tag_count）、
      ok のとき official（build_tag_list の出力から themes を除き、tag_count・reason_counts を足したもの）、
      comparisons（allset・1cb463a：compare_lists の出力と diff_count）、coverage（四半期ごとと全体の4つの数と日の数）。"""
    c, tr, old = mods["counting"], mods["tagrules"], mods["tagrules_1cb463a"]
    start = datetime.date.fromisoformat(inp["block"][0])
    end = datetime.date.fromisoformat(inp["block"][1])
    days = _days(start, end)
    missing = {datetime.date.fromisoformat(d) for d in inp["missing_days"]}
    rows = {r["day"]: r for r in inp["rows"]}
    if sorted(rows) != [d.isoformat() for d in days]:
        raise RecomputeError("day の行が区画のすべての日にちょうど一つずつでない")
    names = read_themes(themes_data, inp["themes_sha256"], inp["themes_rows"])
    unique = set(names)
    table = Table(c, days)
    for d in days:
        r = rows[d.isoformat()]
        data = read_day(r["file_name"])
        if hashlib.sha256(data).hexdigest() != r["sha256"]:
            raise RecomputeError("%s：日の集計の sha256 が day の行と違う" % d.isoformat())
        s = c.parse_day(data, expect_day=d.isoformat(), expect_mode=c.OFFICIAL_MODE)
        del data
        table.add(d, s)
        del s
    c7 = c.OFFICIAL_CANDIDATE
    statuses = {cid: c.order5_candidate_status(cid, table.totals[cid], missing, days) for cid in c.CANDIDATE_IDS}
    counts_c7 = table.counts(c7)
    outside = sorted(n for n in unique if not c.THEME_NAME_RE.fullmatch(n))
    out = {
        "themes_table": {"unique_names": len(unique), "duplicate_rows": len(names) - len(unique),
                         "names_not_in_day_aggregate_form": {"count": len(outside), "names": outside},
                         "official_data_themes_not_in_table": len(set(counts_c7) - unique)},
    }
    themes_arg = {n: None for n in sorted(unique)}

    def cand(cid, result):
        st = statuses[cid]
        col, den = {x[0]: (x[1], x[2]) for x in c.CANDIDATES}[cid]
        v = {"id": cid, "numerator_column": col, "denominator_kind": den, "status": st["status"], "reason": st["reason"],
             "zero_days": st["zero_days"]}
        if result is None:
            v.update(n_med=None, a=None, a_float=None, usable_day_count=None, tag_count=None)
        else:
            v.update(n_med=result["n_med"], a=result["a"], a_float=result["a_float"],
                     usable_day_count=result["usable_day_count"], tag_count=len(result["tag_list"]))
        return v
    if statuses[c7]["status"] != "ok":
        out.update(status="stopped", candidates=[cand(cid, None) for cid in c.CANDIDATE_IDS])
        return _json(out)
    official = tr.build_tag_list(themes_arg, counts_c7, table.totals[c7], missing, start, end)
    allset = tr.build_tag_list(themes_arg, counts_c7, table.totals[c7], missing, start, end,
                               optional=tr.OPTIONAL_CATEGORIES)
    results = {c7: official}
    for cid in c.CANDIDATE_IDS:
        if cid != c7 and statuses[cid]["status"] == "ok":
            results[cid] = tr.build_tag_list(themes_arg, table.counts(cid), table.totals[cid], missing, start, end)
    v1 = old.build_tag_list(themes_arg, counts_c7, table.totals[c7], missing, start, end)
    th = official["themes"]
    summary = {k: v for k, v in official.items() if k != "themes"}
    summary.update(tag_count=len(official["tag_list"]),
                   reason_counts={"all_themes": len(th),
                                  "in_list": sum(1 for r in th if r["in_list"]),
                                  "not_present_throughout": sum(1 for r in th if not r["present_throughout"]),
                                  "mean_below_a": sum(1 for r in th if not r["mean_ratio_at_least_a"]),
                                  "excluded": sum(1 for r in th if r["exclusion_matches"])})

    def cmp(old_result):
        m = tr.compare_lists(old_result, official)
        return dict(m, diff_count=len(m["only_in_old"]) + len(m["only_in_new"]))
    keys = ("docs_all_groups",) + tuple(sorted(c.S_UNCOVERED.values()))

    def total(ds):
        s = {k: sum(table.coverage[d][k] for d in ds) for k in keys}
        s["usable_days"] = len(ds)
        return s
    usable = [d for d in days if d not in missing]
    quarters = []
    for i, (qa, qb) in enumerate(tr.quarters(start, end)):
        q = total([d for d in usable if qa <= d <= qb])
        q.update(index=i, start=qa.isoformat(), end=qb.isoformat())
        quarters.append(q)
    out.update(status="ok", official=summary,
               candidates=[cand(cid, results.get(cid)) for cid in c.CANDIDATE_IDS],
               comparisons={"allset": cmp(allset), "1cb463a": cmp(v1)},
               coverage={"quarters": quarters, "total": total(usable)},
               # T-111 差し戻し1回目 中-2：detail（Git の外。tags-naive.md 154行で公開が必要）の中身も計算する
               detail={"official_result": official, "allset_result": allset, "versions": {"1cb463a": v1},
                       "candidate_lists": [{"id": cid, "official": cid == c7,
                                            "tag_list": (list(results[cid]["tag_list"]) if cid in results else None)}
                                           for cid in c.CANDIDATE_IDS]})
    return _json(out)


def compare_with_main(main, got):
    """計算し直した値（compute の返り値）と main を照らす。違う項目の名前の一覧を返す（空なら一致）。"""
    bad = []
    if main.get("status") != got["status"]:
        return ["status"]
    tt = main.get("themes_table") or {}
    for k, v in got["themes_table"].items():
        if _json(tt.get(k)) != v:
            bad.append("themes_table.%s" % k)
    mc = {x.get("id"): x for x in main.get("candidates") or []}
    for g in got["candidates"]:
        m = mc.get(g["id"]) or {}
        for k, v in g.items():
            if _json(m.get(k)) != v:
                bad.append("candidates.%s.%s" % (g["id"], k))
    if got["status"] != "ok":
        return bad
    mo = ((main.get("official") or {}).get("result")) or {}
    if (main.get("official") or {}).get("candidate") != "C7" or (main.get("official") or {}).get("official") is not True:
        bad.append("official.candidate")
    for k, v in got["official"].items():
        if _json(mo.get(k)) != v:
            bad.append("official.result.%s" % k)
    for name, g in got["comparisons"].items():
        m = (main.get("comparisons") or {}).get(name) or {}
        for k, v in g.items():
            if _json(m.get(k)) != v:
                bad.append("comparisons.%s.%s" % (name, k))
    cov = main.get("coverage") or {}
    mq = cov.get("quarters") or []
    if len(mq) != len(got["coverage"]["quarters"]):
        bad.append("coverage.quarters")
    pairs = list(zip(mq, got["coverage"]["quarters"])) + [(cov.get("total") or {}, got["coverage"]["total"])]
    for m, g in pairs:
        for k, v in g.items():
            if m.get(k) != v:
                bad.append("coverage.%s" % k)
        n = g["docs_all_groups"]
        for k in [k for k in g if k.startswith("docs_without_")]:
            want = None if not n else fractions.Fraction(g[k], n)
            r = (m.get("ratios") or {}).get(k)
            try:
                have = None if r is None else fractions.Fraction(r)
            except (TypeError, ValueError, ZeroDivisionError):
                have = "?"
            if have != want:
                bad.append("coverage.ratios.%s" % k)
    return sorted(set(bad))


DETAIL_FIXED = {"part": "detail", "in_git": False}


def compare_with_detail(detail, got, label, note, citation):
    """計算し直した値（compute の返り値の detail）と、Git の外の detail を照らす（T-111 差し戻し1回目 中-2）。
    official_result・allset_result・versions.1cb463a・candidate_lists と、label・part・in_git・note・citation。
    違う項目の名前の一覧を返す（空なら一致）。"""
    bad = []
    if not isinstance(detail, dict):
        return ["detail"]
    g = got.get("detail")
    if g is None:
        return ["detail（計算し直した値が無い）"]
    for k in ("official_result", "allset_result", "candidate_lists"):
        if _json(detail.get(k)) != g[k]:
            bad.append("detail.%s" % k)
    if _json((detail.get("versions") or {}).get("1cb463a")) != g["versions"]["1cb463a"] \
            or sorted(detail.get("versions") or {}) != ["1cb463a"]:
        bad.append("detail.versions")
    fixed = dict(DETAIL_FIXED, label=label, note=note, citation=list(citation))
    for k, v in fixed.items():
        if detail.get(k) != v:
            bad.append("detail.%s" % k)
    if set(detail) != set(fixed) | {"official_result", "allset_result", "versions", "candidate_lists"}:
        bad.append("detail のキー")
    return sorted(set(bad))


def main(argv):
    if len(argv) != 4:
        sys.stderr.write("order5_recompute: 引数が違う\n")
        return 2
    folder, inp_path, store, themes_path = argv
    with open(inp_path, encoding="utf-8") as f:
        inp = json.load(f)
    with open(themes_path, "rb") as f:
        themes_data = f.read()

    def read_day(name):
        if os.path.basename(name) != name:
            raise RecomputeError("日の集計の名前の形が違う")
        fd = os.open(os.path.join(store, name), os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(fd, "rb") as f:
            return f.read()
    try:
        got = compute(load_sealed(folder), inp, read_day, themes_data)
    except (RecomputeError, OSError, ValueError) as e:
        sys.stderr.write("order5_recompute: 止まった：%s: %s\n" % (type(e).__name__, e))
        return 1
    sys.stdout.write(json.dumps(got, ensure_ascii=False, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
