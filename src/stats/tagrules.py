#!/usr/bin/env python3
"""タグの一覧を作る規則（T-019。未決事項3の「入れる規則の数値の決め方」と未決事項5）。

データを見ずに決めた「決め方」を、機械可読な形で出す。文書は docs/stats/tags-naive.md。
- データは読まない。ネットワークは使わない。現在の日時を読まない。
  区分表（GDELT のテーマの区分表）も読まない。この版を作った時点で、統計係は区分表を見ていない。
- 一覧を作る関数 build_tag_list() は、手法を作る期間の区画のデータを「メモリの上の引数」として
  受け取る。ファイルは開かない。区画の外の日付が一つでも入っていれば止まる。
- この版は「提案」で、オーナーの承認のあと封印係が封印する。統計係は封印しない。

入れる規則（CLAUDE.md「タグの一覧」1）
  (1) 全体にわたって存在する：手法を作る期間の区画を暦の四半期に分け、欠けた日でない日の
      報道量の合計が、どの四半期でも MIN_COUNT_PER_QUARTER（1件）以上。
      欠けた日でない日が一日も無い四半期は数えない（その四半期は条件から外す）。
  (2) 平均報道量：欠けた日でない日の比率 r(d) の単純平均が A 以上。
      A = K_ARTICLES_PER_DAY / N_med。N_med は、欠けた日でない日の全体の報道量（r の分母）の
      中央値。A は「全体の報道量が普段どおりの日に、1日あたり平均 K 件」に当たる比率。
      最低の報道量 V は A と同じ値（docs/stats/candidates.md 3章 (4)）。
除外する規則（CLAUDE.md「タグの一覧」2）
  テーマの名前と説明を、英字と数字以外で区切って大文字の語の並びにし、EXCLUSION_TERMS の
  語（または連続する語の並び）と完全に一致するものが一つでもあれば外す。部分一致はしない。
  一件ずつの例外（特定のテーマ名を足す・外す）は持たない。

使い方
  python3 -B src/stats/tagrules.py
      規則の定数と語の一覧を JSON（キー順・UTF-8）で出力する
"""

import datetime
import fractions
import json
import math
import re
import sys

PROPOSED_LABEL = "tagrules-v1"

# ---------------------------------------------------------------------------
# 入れる規則の数値の決め方
# ---------------------------------------------------------------------------

# A = K / N_med。K は「1日あたりの件数」。値は比率（分母が全体の報道量）で持つ。
K_ARTICLES_PER_DAY = 10

# 存在の確かめ方：暦の四半期ごとに、欠けた日でない日の報道量の合計がこれ以上。
MIN_COUNT_PER_QUARTER = 1

# ---------------------------------------------------------------------------
# 除外する規則の語の一覧
# 語は大文字の英字と数字だけ。複数の語の並びは、連続して現れたときだけ一致とする。
# 単数形と複数形などの形は、一つずつ書く（語幹の処理はしない）。
# 区分の名前は報告のためのもので、どの区分に当たっても同じく外す。
# ---------------------------------------------------------------------------

EXCLUSION_TERMS = {
    "politics_election": (
        "ELECTION", "ELECTIONS", "ELECTORAL", "ELECTED", "VOTE", "VOTES", "VOTING",
        "VOTER", "VOTERS", "BALLOT", "BALLOTS", "REFERENDUM", "REFERENDUMS",
        "POLITICS", "POLITICAL", "POLITICIAN", "POLITICIANS",
        "PARLIAMENT", "PARLIAMENTARY", "LEGISLATURE", "LEGISLATIVE", "CONGRESS",
        "SENATE", "SENATOR", "SENATORS", "LAWMAKER", "LAWMAKERS",
        "PRESIDENT", "PRESIDENTS", "PRESIDENTIAL", "PRIME MINISTER", "MINISTER",
        "MINISTERS", "GOVERNOR", "GOVERNORS", "MAYOR", "MAYORS", "LEADER", "LEADERS",
        "HEAD OF STATE", "CABINET", "COUP", "COUPS", "IMPEACH", "IMPEACHMENT",
        "REGIME", "REGIMES", "DICTATOR", "DICTATORS", "DICTATORSHIP",
        "PROTEST", "PROTESTS", "PROTESTER", "PROTESTERS", "DEMONSTRATOR",
        "DEMONSTRATORS", "SANCTION", "SANCTIONS", "DIPLOMACY", "DIPLOMATIC",
        "DIPLOMAT", "DIPLOMATS", "EMBASSY", "AMBASSADOR", "PROPAGANDA", "LOBBYING",
    ),
    "conflict_violence": (
        "WAR", "WARS", "WARFARE", "MILITARY", "ARMY", "ARMIES", "ARMED", "NAVY",
        "AIR FORCE", "SOLDIER", "SOLDIERS", "TROOP", "TROOPS", "MILITIA", "MILITIAS",
        "INSURGENCY", "INSURGENT", "INSURGENTS", "REBEL", "REBELS", "REBELLION",
        "TERROR", "TERRORISM", "TERRORIST", "TERRORISTS", "EXTREMISM", "EXTREMIST",
        "EXTREMISTS", "JIHAD", "JIHADIST", "JIHADISTS",
        "CONFLICT", "CONFLICTS", "VIOLENCE", "VIOLENT", "ATTACK", "ATTACKS",
        "BOMB", "BOMBS", "BOMBING", "BOMBINGS", "EXPLOSIVE", "EXPLOSIVES",
        "WEAPON", "WEAPONS", "GUN", "GUNS", "FIREARM", "FIREARMS", "SHOOTING",
        "SHOOTINGS", "MISSILE", "MISSILES", "AIRSTRIKE", "AIRSTRIKES",
        "KILL", "KILLS", "KILLED", "KILLING", "KILLINGS", "MASSACRE", "MASSACRES",
        "GENOCIDE", "CEASEFIRE", "PEACEKEEPING", "PEACEKEEPER", "PEACEKEEPERS",
        "INVASION", "HOSTAGE", "HOSTAGES", "TORTURE", "RIOT", "RIOTS", "UNREST",
        "CRACKDOWN", "PERSECUTION", "SIEGE", "BLOCKADE", "DEFENSE", "DEFENCE",
        "REFUGEE", "REFUGEES", "DISPLACED", "ETHNIC CLEANSING",
    ),
    "crime": (
        "CRIME", "CRIMES", "CRIMINAL", "CRIMINALS", "MURDER", "MURDERS", "HOMICIDE",
        "HOMICIDES", "ASSAULT", "ASSAULTS", "ROBBERY", "THEFT", "BURGLARY", "FRAUD",
        "CORRUPTION", "BRIBERY", "BRIBE", "BRIBES", "SMUGGLING", "TRAFFICKING",
        "NARCOTICS", "CARTEL", "CARTELS", "GANG", "GANGS", "MAFIA", "LAUNDERING",
        "EXTORTION", "KIDNAP", "KIDNAPPING", "KIDNAPPINGS", "RAPE", "HARASSMENT",
        "ABUSE", "ARREST", "ARRESTS", "ARRESTED", "POLICE", "PRISON", "PRISONS",
        "PRISONER", "PRISONERS", "JAIL", "INCARCERATION", "PROSECUTION",
        "PROSECUTOR", "PROSECUTORS", "INDICTMENT", "PIRACY", "SCAM", "SCAMS",
        "VANDALISM", "ARSON", "CYBERCRIME",
    ),
    "specific_person": (
        "POPE", "KING", "KINGS", "QUEEN", "QUEENS", "PRINCE", "PRINCES", "PRINCESS",
        "MONARCH", "MONARCHY", "ROYAL", "ROYALS", "EMPEROR", "EMPRESS",
        "CELEBRITY", "CELEBRITIES",
    ),
    "disaster_disease": (
        "DISASTER", "DISASTERS", "EARTHQUAKE", "EARTHQUAKES", "TSUNAMI", "TSUNAMIS",
        "FLOOD", "FLOODS", "FLOODING", "HURRICANE", "HURRICANES", "TYPHOON",
        "TYPHOONS", "CYCLONE", "CYCLONES", "TORNADO", "TORNADOES", "WILDFIRE",
        "WILDFIRES", "FIRE", "FIRES", "DROUGHT", "DROUGHTS", "LANDSLIDE",
        "LANDSLIDES", "VOLCANO", "VOLCANOES", "VOLCANIC", "ERUPTION", "AVALANCHE",
        "HEATWAVE", "HEAT WAVE", "STORM", "STORMS", "BLIZZARD", "FAMINE",
        "CRISISLEX", "CASUALTY", "CASUALTIES", "FATALITY", "FATALITIES",
        "DEATH", "DEATHS", "DEAD",
        "EPIDEMIC", "EPIDEMICS", "PANDEMIC", "PANDEMICS", "OUTBREAK", "OUTBREAKS",
        "DISEASE", "DISEASES", "INFECTION", "INFECTIONS", "INFECTIOUS", "VIRUS",
        "VIRUSES", "INFLUENZA", "FLU", "EBOLA", "ZIKA", "CHOLERA", "MALARIA",
        "MEASLES", "HIV", "TUBERCULOSIS", "POLIO", "CORONAVIRUS", "COVID", "SARS",
        "MERS", "PLAGUE", "DENGUE", "VACCINE", "VACCINES", "VACCINATION",
        "QUARANTINE",
    ),
    # CLAUDE.md の五つの区分の外。オーナーの承認が要る（docs/stats/tags-naive.md 2章 (4)）。
    "ethnic_religious_group": (
        "ETHNIC", "ETHNICITY", "ETHNICITIES", "TRIBE", "TRIBES", "TRIBAL",
        "RELIGION", "RELIGIONS", "RELIGIOUS", "SECTARIAN",
    ),
}

# 五つの区分（CLAUDE.md）と、その外の区分。
CLAUDE_CATEGORIES = (
    "politics_election", "conflict_violence", "crime", "specific_person", "disaster_disease",
)
EXTRA_CATEGORIES_NEEDING_APPROVAL = ("ethnic_religious_group",)

# 照合に使う欄。区分表のこの二つの欄だけを使う（ほかの欄は、あっても使わない）。
MATCH_FIELDS = ("name", "description")

_SPLIT = re.compile(r"[^A-Z0-9]+")
_TERM_OK = re.compile(r"\A[A-Z0-9]+( [A-Z0-9]+)*\Z")

ONE_DAY = datetime.timedelta(days=1)


def tokens(text):
    """大文字にして、英字と数字以外で区切った語の並び。None や空は空の並び。"""
    if not text:
        return ()
    return tuple(t for t in _SPLIT.split(text.upper()) if t)


def _term_tokens(term):
    return tuple(term.split(" "))


def _contains(seq, sub):
    n = len(sub)
    return any(seq[i:i + n] == sub for i in range(len(seq) - n + 1))


def exclusion_matches(name, description=None):
    """名前と説明に一致した語の一覧 [(区分, 語, 欄)]。順番は区分・語・欄の定義順。"""
    fields = {"name": tokens(name), "description": tokens(description)}
    out = []
    for cat in CLAUDE_CATEGORIES + EXTRA_CATEGORIES_NEEDING_APPROVAL:
        for term in EXCLUSION_TERMS[cat]:
            tt = _term_tokens(term)
            for f in MATCH_FIELDS:
                if _contains(fields[f], tt):
                    out.append((cat, term, f))
    return out


def is_excluded(name, description=None):
    return bool(exclusion_matches(name, description))


# ---------------------------------------------------------------------------
# 入れる規則
# ---------------------------------------------------------------------------

def quarters(block_start, block_end):
    """区画を暦の四半期で区切った [(始まり, 終わり)]。最初と最後は区画で切る。"""
    out = []
    d = block_start
    while d <= block_end:
        q_month = 3 * ((d.month - 1) // 3) + 1
        if q_month + 3 > 12:
            nxt = datetime.date(d.year + 1, 1, 1)
        else:
            nxt = datetime.date(d.year, q_month + 3, 1)
        end = min(nxt - ONE_DAY, block_end)
        out.append((d, end))
        d = end + ONE_DAY
    return out


def _median(xs):
    xs = sorted(xs)
    n = len(xs)
    if n == 0:
        raise ValueError("中央値を取る値が無い")
    if n % 2 == 1:
        return fractions.Fraction(xs[n // 2])
    return fractions.Fraction(xs[n // 2 - 1] + xs[n // 2], 2)


def threshold_a(totals, missing_days):
    """A = K / N_med（分数）。N_med は欠けた日でない日の全体の報道量の中央値。"""
    usable = [v for d, v in totals.items() if d not in missing_days]
    n_med = _median(usable)
    if n_med <= 0:
        raise ValueError("全体の報道量の中央値が 0")
    return fractions.Fraction(K_ARTICLES_PER_DAY) / n_med, n_med


def _check_dates(dates, block_start, block_end, what):
    for d in dates:
        if not isinstance(d, datetime.date) or isinstance(d, datetime.datetime):
            raise ValueError("%s の日付の形が違う" % what)
        if d < block_start or d > block_end:
            raise ValueError("%s に区画の外の日付がある（%s）" % (what, d.isoformat()))


def _int_count(v):
    if isinstance(v, bool) or not isinstance(v, int) or v < 0:
        raise ValueError("件数は 0 以上の整数")
    return v


def build_tag_list(themes, counts, totals, missing_days, block_start, block_end):
    """タグの一覧を作る（手法を作る期間の区画のデータだけで）。

    themes:  {テーマ名: 説明}。区分表の名前と説明（説明が無ければ None か ""）。
    counts:  {テーマ名: {日付: 件数}}。件数 0 の日は省いてよい。
    totals:  {日付: 全体の報道量}。区画のすべての日が要る（欠けた日は値があってもなくてもよい）。
    missing_days: 欠けた日の集合（封印した一覧）。
    どの引数にも区画の外の日付があれば止まる。区画の外のデータを渡す余地を無くすため。

    対象のテーマは、区分表のテーマと、データに現れたテーマの和集合（名前の順）。
    戻り値は、規則の値（A・N_med・四半期）とテーマごとの判定を含む dict。
    """
    if block_end < block_start:
        raise ValueError("区画が逆")
    _check_dates(totals.keys(), block_start, block_end, "totals")
    _check_dates(missing_days, block_start, block_end, "missing_days")
    for name, per_day in counts.items():
        _check_dates(per_day.keys(), block_start, block_end, "counts[%s]" % name)
    usable_days = []
    d = block_start
    while d <= block_end:
        if d not in missing_days:
            if d not in totals:
                raise ValueError("欠けた日でない日の全体の報道量が無い（%s）" % d.isoformat())
            if _int_count(totals[d]) <= 0:
                raise ValueError("欠けた日でない日の全体の報道量が 0（%s）。欠けた日の規則と食い違う" % d.isoformat())
            usable_days.append(d)
        d += ONE_DAY
    if not usable_days:
        raise ValueError("欠けた日でない日が無い")
    a, n_med = threshold_a({d: totals[d] for d in usable_days}, set())
    qs = quarters(block_start, block_end)
    q_of_day = {}
    for i, (qa, qb) in enumerate(qs):
        x = qa
        while x <= qb:
            q_of_day[x] = i
            x += ONE_DAY
    q_has_data = [False] * len(qs)
    for x in usable_days:
        q_has_data[q_of_day[x]] = True
    names = sorted(set(themes) | set(counts))
    rows = []
    for name in names:
        per_day = counts.get(name, {})
        for v in per_day.values():
            _int_count(v)
        q_counts = [0 if has else None for has in q_has_data]
        for x, v in per_day.items():
            if x not in missing_days:
                q_counts[q_of_day[x]] += v
        present = all(c is None or c >= MIN_COUNT_PER_QUARTER for c in q_counts)
        mean = math.fsum(per_day.get(x, 0) / totals[x] for x in usable_days) / len(usable_days)
        volume_ok = fractions.Fraction(mean) >= a
        desc = themes.get(name)
        matches = exclusion_matches(name, desc)
        rows.append({
            "name": name,
            "in_category_table": name in themes,
            "quarter_counts": q_counts,
            "present_throughout": present,
            "mean_ratio": mean,
            "mean_ratio_at_least_a": volume_ok,
            "exclusion_matches": [list(m) for m in matches],
            "in_list": bool(present and volume_ok and not matches),
        })
    return {
        "proposed_label": PROPOSED_LABEL,
        "block_start": block_start.isoformat(),
        "block_end": block_end.isoformat(),
        "usable_day_count": len(usable_days),
        "quarters": [[qa.isoformat(), qb.isoformat()] for qa, qb in qs],
        "quarters_without_usable_days": [i for i, h in enumerate(q_has_data) if not h],
        "n_med": "%d/%d" % (n_med.numerator, n_med.denominator),
        "a": "%d/%d" % (a.numerator, a.denominator),
        "a_float": float(a),
        "v_equals_a": True,
        "themes": rows,
        "tag_list": [r["name"] for r in rows if r["in_list"]],
    }


def as_record():
    return {
        "proposed_label": PROPOSED_LABEL,
        "inclusion": {
            "presence": "every calendar quarter of the method block (clipped at block ends) with at "
                        "least one usable day has total count >= %d on usable days; quarters "
                        "without usable days are skipped" % MIN_COUNT_PER_QUARTER,
            "min_count_per_quarter": MIN_COUNT_PER_QUARTER,
            "mean": "simple mean of daily ratio r(d) over usable (non-missing) days of the method block",
            "a_rule": "A = K / N_med, N_med = median daily total count over usable days of the method block "
                      "(even count -> mean of two middle values); compare mean >= A exactly",
            "k_articles_per_day": K_ARTICLES_PER_DAY,
            "v_rule": "V = A (docs/stats/candidates.md 3 (4))",
            "universe": "union of themes in the category table and themes appearing in method-block data",
            "data_scope": "method block only; any date outside the block in the inputs stops the build",
        },
        "exclusion": {
            "fields": list(MATCH_FIELDS),
            "tokenize": "uppercase, split on any character other than A-Z and 0-9, drop empty",
            "match": "a term (one or more tokens) matches if its tokens appear contiguously in the "
                     "token sequence of the name or the description; no substring or stem matching",
            "claude_categories": list(CLAUDE_CATEGORIES),
            "extra_categories_needing_owner_approval": list(EXTRA_CATEGORIES_NEEDING_APPROVAL),
            "terms": {k: list(v) for k, v in EXCLUSION_TERMS.items()},
            "per_theme_exceptions": "none",
            "organizations": "no separate rule; excluded only when a term of a category matches",
        },
        "changes_after_seeing_table": "new version only, with owner approval; terms only (never theme "
                                      "names); before method-access; diff and affected themes published",
    }


def canonical_json():
    return json.dumps(as_record(), ensure_ascii=False, sort_keys=True, indent=2) + "\n"


def _validate_terms():
    seen = set()
    for cat, terms in EXCLUSION_TERMS.items():
        for t in terms:
            if not _TERM_OK.match(t):
                raise ValueError("語の形が違う: %r" % t)
            if t in seen:
                raise ValueError("語が重複している: %r" % t)
            seen.add(t)


_validate_terms()


def main(argv=None):
    if argv is None:
        argv = sys.argv[1:]
    if argv:
        sys.stderr.write("tagrules: 引数は取らない\n")
        return 2
    sys.stdout.write(canonical_json())
    return 0


if __name__ == "__main__":
    sys.exit(main())
