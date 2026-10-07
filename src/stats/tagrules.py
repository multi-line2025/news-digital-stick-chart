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
  テーマの名前と説明を tokens() で語の並びにし、有効な区分の EXCLUSION_TERMS の語に当たる
  ものが一つでもあれば外す。当たり方は、完全一致・形の変化（inflections()）と、名前の欄だけに
  使うくっつき一致（先頭：PREFIX_MIN_LEN 文字以上の語、末尾：どの長さの語も。どちらも残りが
  GLUE_MIN_REST 文字以上）だけ（_word_matches()）。
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
# 除外する規則の語の一覧（docs/stats/tags-naive.md 2章）
# 語は大文字の英字と数字。空白で区切ったものは語の並び（連続して現れたときだけ一致）。
# 語の形の変化（複数形・活用形）は inflections() の規則で機械的に作る。
# 区分の名前は報告のためのもので、有効な区分のどれに当たっても同じく外す。
# ---------------------------------------------------------------------------

EXCLUSION_TERMS = {
    "politics_election": (
        "ELECTION", "ELECTORAL", "ELECTED", "ELECTING", "VOTE", "BALLOT", "REFERENDUM", "POLL",
        "CANDIDATE", "INAUGURATION", "POLITICS", "POLITICAL", "POLITICIAN",
        "PARLIAMENT", "PARLIAMENTARY", "LEGISLATURE", "LEGISLATIVE", "LEGISLATOR",
        "CONGRESS", "SENATE", "SENATOR", "LAWMAKER", "PRESIDENT", "PRESIDENTIAL",
        "PRIME MINISTER", "MINISTER", "CHANCELLOR", "GOVERNOR", "MAYOR", "LEADER",
        "HEAD OF STATE", "CABINET", "COUP", "IMPEACH", "IMPEACHMENT", "REGIME",
        "DICTATOR", "DICTATORSHIP", "PROTEST", "DEMONSTRATOR", "SANCTION",
        "DIPLOMACY", "DIPLOMATIC", "DIPLOMAT", "EMBASSY", "AMBASSADOR", "PROPAGANDA",
        "LOBBYING", "LOBBYIST",
    ),
    "conflict_violence": (
        "WAR", "WARFARE", "MILITARY", "ARMY", "ARMED", "NAVY", "NAVAL", "AIR FORCE",
        "SOLDIER", "TROOP", "MILITIA", "INSURGENCY", "INSURGENT", "INSURRECTION",
        "REBEL", "REBELLION", "GUERRILLA", "SEPARATIST", "TERROR", "TERRORISM",
        "TERRORIST", "EXTREMISM", "EXTREMIST", "JIHAD", "JIHADIST", "CONFLICT",
        "VIOLENCE", "VIOLENT", "ATTACK", "BOMB", "BOMBING", "EXPLOSIVE", "EXPLOSION",
        "WEAPON", "GUN", "GUNMAN", "GUNMEN", "GUNFIRE", "FIREARM", "SHOOTING",
        "SHOOTER", "SNIPER", "MISSILE", "ARTILLERY", "AIRSTRIKE", "KILL", "KILLING", "MASSACRE",
        "GENOCIDE", "SLAUGHTER", "MANSLAUGHTER", "ASSASSIN", "ASSASSINATE", "ASSASSINATION",
        "EXECUTION", "BEHEADING", "STABBING", "LYNCHING", "CEASEFIRE", "PEACEKEEPING",
        "PEACEKEEPER", "INVASION", "HOSTAGE", "TORTURE", "RIOT", "UNREST",
        "CRACKDOWN", "PERSECUTION", "SIEGE", "BLOCKADE", "DEFENSE", "DEFENCE",
        "CONSCRIPTION", "REFUGEE", "DISPLACED", "ETHNIC CLEANSING",
    ),
    "crime": (
        "CRIME", "CRIMINAL", "MURDER", "HOMICIDE", "ASSAULT", "ROBBERY", "THEFT",
        "THIEF", "THIEVES", "BURGLARY", "FRAUD", "EMBEZZLEMENT", "CORRUPTION",
        "BRIBERY", "BRIBE", "SMUGGLING", "SMUGGLER", "TRAFFICKING", "TRAFFICKER",
        "NARCOTICS", "CARTEL", "GANG", "MAFIA", "LAUNDERING", "EXTORTION", "KIDNAP",
        "KIDNAPPING", "KIDNAPPED", "KIDNAPPER", "ABDUCTION", "RAPE", "HARASSMENT",
        "ABUSE", "ARREST", "DETAIN", "DETAINEE", "DETENTION", "POLICE", "PRISON",
        "JAIL", "INCARCERATION", "PROSECUTION", "PROSECUTOR", "INDICTMENT", "FELONY",
        "PIRACY", "SCAM", "VANDALISM", "ARSON", "POACHING", "COUNTERFEIT",
        "ESPIONAGE", "TREASON", "VICTIM", "CYBERCRIME",
    ),
    "specific_person": (
        "POPE", "KING", "QUEEN", "PRINCE", "PRINCESS", "MONARCH", "MONARCHY", "ROYAL",
        "EMPEROR", "EMPRESS", "CELEBRITY",
    ),
    "disaster": (
        "DISASTER", "EARTHQUAKE", "TSUNAMI", "FLOOD", "HURRICANE", "TYPHOON",
        "CYCLONE", "TORNADO", "WILDFIRE", "FIRE", "DROUGHT", "LANDSLIDE", "MUDSLIDE",
        "SINKHOLE", "VOLCANO", "VOLCANIC", "ERUPTION", "AVALANCHE", "HEATWAVE",
        "HEAT WAVE", "STORM", "BLIZZARD", "FAMINE", "CRASH", "DERAILMENT",
        "SHIPWRECK", "ACCIDENT", "EVACUATION", "CASUALTY", "FATALITY", "INJURED",
        "DEATH", "DEAD",
    ),
    "disease_general": (
        "EPIDEMIC", "PANDEMIC", "OUTBREAK", "DISEASE", "INFECTION", "INFECTIOUS",
        "CONTAGION", "CONTAGIOUS", "VIRUS", "PATHOGEN", "VACCINE", "VACCINATION",
        "QUARANTINE",
    ),
    # 病名。過去の流行の知識から選んだ（文書 7章）。入れるかはオーナーが選ぶ（2章 (4)）。
    "disease_named": (
        "INFLUENZA", "FLU", "EBOLA", "ZIKA", "CHOLERA", "MALARIA", "MEASLES", "HIV",
        "TUBERCULOSIS", "POLIO", "CORONAVIRUS", "COVID", "SARS", "SARSCOV", "MERS",
        "PLAGUE", "DENGUE", "ANTHRAX", "SMALLPOX", "HEPATITIS", "MENINGITIS", "RABIES",
        "H1N1", "H5N1",
    ),
    # CLAUDE.md の五つの区分の外。オーナーの承認が要る（文書 2章 (5)）。
    "ethnic_religious_group": (
        "ETHNIC", "ETHNICITY", "TRIBE", "TRIBAL", "RELIGION", "RELIGIOUS", "SECTARIAN",
    ),
}

# 区分と CLAUDE.md の五つの区分の対応。None は五つの区分の外。
CLAUDE_CATEGORY_OF = {
    "politics_election": "政治・選挙",
    "conflict_violence": "紛争・暴力",
    "crime": "犯罪",
    "specific_person": "特定の人物",
    "disaster": "災害・感染症",
    "disease_general": "災害・感染症",
    "disease_named": "災害・感染症",
    "ethnic_religious_group": None,
}
CLAUDE_CATEGORIES = ("政治・選挙", "紛争・暴力", "犯罪", "特定の人物", "災害・感染症")

# オーナーが選ぶ区分（文書 0章）。この提案では両方を有効にしている。
# オーナーの選択は、封印の前にこの定数に反映する（区分表を見る前なので選び出しにならない）。
OPTIONAL_CATEGORIES = ("disease_named", "ethnic_religious_group")
ENABLED_OPTIONAL_CATEGORIES = ("disease_named", "ethnic_religious_group")

# 照合に使う欄。区分表のこの二つの欄だけを使う（ほかの欄は、あっても使わない）。
MATCH_FIELDS = ("name", "description")

# くっつき一致（名前の欄だけ。文書 2章 (1)）の数値。
# 先頭での一致は、この文字数以上の語だけ。
PREFIX_MIN_LEN = 6
# 先頭でも末尾でも、名前の語から一覧の語を除いた残りが、この文字数以上の英字であること。
GLUE_MIN_REST = 4
# 末尾での一致を使わない語：4文字以下で、英語の語尾（ING, ED, ER, S）で終わる語（今は KING・SARS・MERS）。
# 短い語が別の語の語尾として偶然現れるのを防ぐため（BREAKING, SPEAKING など）。
SUFFIX_BLOCK_MAX_LEN = 4
SUFFIX_BLOCK_ENDINGS = ("ING", "ED", "ER", "S")
# くっつき一致を使う欄。
GLUE_FIELDS = ("name",)

_PIECES = re.compile(r"[A-Z]+|[0-9]+")
_TERM_OK = re.compile(r"\A[A-Z0-9]+( [A-Z0-9]+)*\Z")

ONE_DAY = datetime.timedelta(days=1)


def tokens(text):
    """大文字にし、英字の続きと数字の続きを一つずつの語にした並び。

    英字と数字以外（下線・空白・記号）は区切りとして捨てる。英字と数字の境目でも区切る
    （ELECTION2016 -> ELECTION, 2016）。None や空は空の並び。
    """
    if not text:
        return ()
    return tuple(_PIECES.findall(text.upper()))


def inflections(word):
    """語の形の変化（複数形・活用形）の集合。word 自身は含めない。英字だけの語に作る。

    - 常に +S
    - S, X, Z, CH, SH, O で終わる語に +ES
    - 子音 + Y で終わる語に Y を IES, IED に替えた形
    - E で終わる語に +D, +R, +RS と、E を除いて +ING
    - それ以外の語に +ED, +ING, +ER, +ERS
    子音を重ねる形（KIDNAP -> KIDNAPPING）は作らない（必要なものは語の一覧に書いた）。
    """
    if not word.isalpha():
        return frozenset()
    out = {word + "S"}
    if word.endswith(("S", "X", "Z", "CH", "SH", "O")):
        out.add(word + "ES")
    if len(word) >= 2 and word.endswith("Y") and word[-2] not in "AEIOU":
        out.update({word[:-1] + "IES", word[:-1] + "IED"})
    if word.endswith("E"):
        out.update({word + "D", word + "R", word + "RS", word[:-1] + "ING"})
    else:
        out.update({word + "ED", word + "ING", word + "ER", word + "ERS"})
    return frozenset(out)


def _suffix_allowed(word):
    return not (len(word) <= SUFFIX_BLOCK_MAX_LEN and word.endswith(SUFFIX_BLOCK_ENDINGS))


def _word_matches(word, tok, glue=True):
    """一つの語 word が、一つの語 tok に当たるか。当たり方の名前か None。

    exact       tok == word
    inflection  tok が word の形の変化
    glue        （glue が真で、word と tok が英字だけのとき）
                - 先頭：len(word) >= PREFIX_MIN_LEN で、tok が word で始まり、残りが GLUE_MIN_REST 文字以上
                - 末尾：_suffix_allowed(word) で、tok が word か word の形の変化で終わり、
                  その前の残りが GLUE_MIN_REST 文字以上
    """
    if tok == word:
        return "exact"
    if tok in inflections(word):
        return "inflection"
    if not (glue and word.isalpha() and tok.isalpha()):
        return None
    if len(word) >= PREFIX_MIN_LEN and tok.startswith(word) and len(tok) - len(word) >= GLUE_MIN_REST:
        return "glue-prefix"
    if _suffix_allowed(word):
        for form in (word,) + tuple(sorted(inflections(word))):
            if tok.endswith(form) and len(tok) - len(form) >= GLUE_MIN_REST:
                return "glue-suffix"
    return None


def _term_match(term, toks, glue=True):
    """語（または語の並び）term が、語の並び toks に当たるか。当たり方の名前か None。

    - 語が一つ：どれかの語に _word_matches が当たれば一致。
    - 語の並び：並びが連続して現れれば一致（最後の語だけ形の変化を認める）。
      加えて、glue が真のとき（名前の欄だけ）、並びをつなげた一語（AIR FORCE -> AIRFORCE）を、
      語が一つの場合と同じ規則で照合する。語がくっついた形への対応は、すべて名前の欄だけに使う。
    """
    tt = tokens(term)
    if len(tt) == 1:
        for t in toks:
            how = _word_matches(tt[0], t, glue)
            if how:
                return how
        return None
    n = len(tt)
    for i in range(len(toks) - n + 1):
        seg = toks[i:i + n]
        if seg[:-1] == tt[:-1] and (seg[-1] == tt[-1] or seg[-1] in inflections(tt[-1])):
            return "exact" if seg[-1] == tt[-1] else "inflection"
    joined = "".join(tt)
    if glue and joined.isalpha():
        for t in toks:
            how = _word_matches(joined, t, glue)
            if how:
                return "joined-" + how
    return None


def enabled_categories(optional=None):
    opt = ENABLED_OPTIONAL_CATEGORIES if optional is None else tuple(optional)
    for c in opt:
        if c not in OPTIONAL_CATEGORIES:
            raise ValueError("選べる区分ではない: %r" % c)
    return tuple(c for c in EXCLUSION_TERMS if c not in OPTIONAL_CATEGORIES or c in opt)


def exclusion_matches(name, description=None, optional=None):
    """名前と説明に一致した語の一覧 [(区分, 語, 欄, 当たり方)]。順番は区分・語・欄の定義順。

    optional：有効にする選べる区分（既定は ENABLED_OPTIONAL_CATEGORIES）。
    """
    fields = {"name": tokens(name), "description": tokens(description)}
    out = []
    for cat in enabled_categories(optional):
        for term in EXCLUSION_TERMS[cat]:
            for f in MATCH_FIELDS:
                how = _term_match(term, fields[f], f in GLUE_FIELDS)
                if how:
                    out.append((cat, term, f, how))
    return out


def is_excluded(name, description=None, optional=None):
    return bool(exclusion_matches(name, description, optional))


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


def compare_lists(old_result, new_result):
    """二つの版の build_tag_list() の結果を比べ、出入りしたテーマを返す（名前の順）。"""
    old, new = set(old_result["tag_list"]), set(new_result["tag_list"])
    return {"only_in_old": sorted(old - new), "only_in_new": sorted(new - old),
            "in_both": len(old & new)}


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
            "tokenize": "uppercase; maximal runs of A-Z and of 0-9 are tokens (letter/digit boundary "
                        "splits); every other character is a separator",
            "inflections": "+S always; +ES after S/X/Z/CH/SH/O; consonant+Y -> IES, IED; ending E -> +D, "
                           "+R, +RS, drop E +ING; otherwise +ED, +ING, +ER, +ERS; letters only; no "
                           "consonant doubling",
            "match": "single word: token equals the word or an inflection of it; in the name field only "
                     "(glue), both alphabetic: prefix if len(word) >= %d and the rest has >= %d letters; "
                     "suffix (word or an inflection of it) if the rest before it has >= %d letters, except "
                     "words of <= %d letters ending in %s; phrase: contiguous tokens (last may be "
                     "inflected), or (name field only) the joined phrase matched as a single word"
                     % (PREFIX_MIN_LEN, GLUE_MIN_REST, GLUE_MIN_REST, SUFFIX_BLOCK_MAX_LEN,
                        "/".join(SUFFIX_BLOCK_ENDINGS)),
            "prefix_min_len": PREFIX_MIN_LEN,
            "glue_min_rest": GLUE_MIN_REST,
            "suffix_block": {"max_len": SUFFIX_BLOCK_MAX_LEN, "endings": list(SUFFIX_BLOCK_ENDINGS)},
            "glue_fields": list(GLUE_FIELDS),
            "category_to_claude": CLAUDE_CATEGORY_OF,
            "claude_categories": list(CLAUDE_CATEGORIES),
            "optional_categories": list(OPTIONAL_CATEGORIES),
            "enabled_optional_categories": list(ENABLED_OPTIONAL_CATEGORIES),
            "terms": {k: list(v) for k, v in EXCLUSION_TERMS.items()},
            "per_theme_exceptions": "none",
            "organizations": "no separate rule; excluded only when a term of a category matches",
            "direction": "over-exclusion preferred (e.g. DEFENSE, DEATH, VACCINE, FIRE also hit neutral themes)",
        },
        "counting": "numerator and denominator of r(d) follow the counting method sealed by the collector "
                    "(T-018); this record is sealed only after, or together with, that counting method",
        "changes_after_seeing_table": "only fixes of defects reproducible by a test (exception, crash on "
                                      "empty input, etc.); no words, no numbers, no new kinds of match. "
                                      "New version, owner approval, before method-access; lists computed "
                                      "with both versions and themes that moved published. Theme names "
                                      "are never named",
        "sealed_versions": "the final version and the version of commit 1cb463a are both sealed; after the "
                           "category table is acquired both lists are computed and the themes that differ "
                           "are published (compare_lists)",
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
