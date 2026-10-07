#!/usr/bin/env python3
"""除外の規則（T-019・T-020・T-022。未決事項5）。

タグの一覧の除外する規則（CLAUDE.md「タグの一覧」2）を、入れる規則（tagrules.py の K など）から
分けたもの。分けた理由：除外の規則は区分表の取得より前に今すぐ封印するが、K は報道量の数え方が
封印されるまで封印しない（docs/stats/tags-naive.md 5章）。この二つを別々の記録で封印できるように、
ファイルと出力を分けた。規則の中身は T-020 の合格の版（2f4b3ce の tagrules.py）と同じで、変えたのは
オーナーの決定（選べる区分と、その出どころ）の反映だけである。

- データは読まない。ネットワークは使わない。現在の日時を読まない。ファイルを開かない。
- 区分表（GDELT のテーマの区分表）も読まない。この規則を決めた時点で、区分表は取得されていない。
- 封印はしない。封印は封印係が行う。

照合のしかた
  テーマの名前と説明を tokens() で語の並びにし、有効な区分の EXCLUSION_TERMS の語に当たる
  ものが一つでもあれば外す。当たり方は、完全一致・形の変化（inflections()）と、名前の欄だけに
  使うくっつき一致（先頭：PREFIX_MIN_LEN 文字以上の語、末尾：どの長さの語も。どちらも残りが
  GLUE_MIN_REST 文字以上）だけ（_word_matches()）。
  一件ずつの例外（特定のテーマ名を足す・外す）は持たない。

使い方
  python3 -B src/stats/exclusion.py
      除外の規則の定数と語の一覧を JSON（キー順・UTF-8）で出力する
"""

import json
import re
import sys

PROPOSED_LABEL = "exclusion-v1"

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
    # 病名。過去の流行の知識から選んだ（文書 7章）。2026-10-08 のオーナーの決定（案B）で使わない。
    # 語は記録のために残す（文書 2章 (4)・(8)）。
    "disease_named": (
        "INFLUENZA", "FLU", "EBOLA", "ZIKA", "CHOLERA", "MALARIA", "MEASLES", "HIV",
        "TUBERCULOSIS", "POLIO", "CORONAVIRUS", "COVID", "SARS", "SARSCOV", "MERS",
        "PLAGUE", "DENGUE", "ANTHRAX", "SMALLPOX", "HEPATITIS", "MENINGITIS", "RABIES",
        "H1N1", "H5N1",
    ),
    # 2026-10-08 のオーナーの決定で、CLAUDE.md の除外の区分に加わった（文書 2章 (5)）。使う。
    "ethnic_religious_group": (
        "ETHNIC", "ETHNICITY", "TRIBE", "TRIBAL", "RELIGION", "RELIGIOUS", "SECTARIAN",
    ),
}

# 区分と CLAUDE.md の区分の対応。
CLAUDE_CATEGORY_OF = {
    "politics_election": "政治・選挙",
    "conflict_violence": "紛争・暴力",
    "crime": "犯罪",
    "specific_person": "特定の人物",
    "disaster": "災害・感染症",
    "disease_general": "災害・感染症",
    "disease_named": "災害・感染症",
    "ethnic_religious_group": "民族・宗教の集団",
}
# CLAUDE.md「除外する規則」の区分。民族・宗教の集団は 2026-10-08 のオーナーの決定で加わった。
CLAUDE_CATEGORIES = ("政治・選挙", "紛争・暴力", "犯罪", "特定の人物", "災害・感染症", "民族・宗教の集団")

# オーナーが選ぶ区分（文書 0章の7・8）。2026-10-08 にオーナーが決めた。
#   0章7 病名の扱い：案B（disease_named を使わない）
#   0章8 民族・宗教の集団：除外の区分に加える（ethnic_religious_group を使う）
# 決定の出どころは OWNER_CHOICE_SOURCE（reviews/ の記録のファイルと見出し）。
# 出どころが None なら「未決」で、封印係は封印を拒む（optional_choice_status）。
OPTIONAL_CATEGORIES = ("disease_named", "ethnic_religious_group")
ENABLED_OPTIONAL_CATEGORIES = ("ethnic_religious_group",)
OWNER_CHOICE_SOURCE = "reviews/T-020.md 2026-10-08 オーナーの発言"

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


def optional_choice_status():
    """出どころ（OWNER_CHOICE_SOURCE）があれば "decided"、無ければ "undecided"。直書きしない。"""
    return "decided" if OWNER_CHOICE_SOURCE else "undecided"


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




def as_record():
    return {
        "proposed_label": PROPOSED_LABEL,
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
        "optional_choice_status": optional_choice_status(),
        "owner_choice_source": OWNER_CHOICE_SOURCE,
        "terms": {k: list(v) for k, v in EXCLUSION_TERMS.items()},
        "per_theme_exceptions": "none",
        "organizations": "no separate rule; excluded only when a term of a category matches",
        "direction": "over-exclusion preferred (e.g. DEFENSE, DEATH, VACCINE, FIRE also hit neutral themes)",
        "changes_after_seeing_table": "only fixes of defects reproducible by a test (exception, crash on "
                                      "empty input, etc.); no words, no numbers, no new kinds of match. "
                                      "New version, owner approval, before method-access; lists computed "
                                      "with both versions and themes that moved published. Theme names "
                                      "are never named",
        "sealed_versions": "this version and the tagrules.py of commit 1cb463a (comparison only, not "
                           "adopted) are both sealed; after the category table is acquired both lists are "
                           "computed and the themes that differ are published (tagrules.compare_lists)",
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
        sys.stderr.write("exclusion: 引数は取らない\n")
        return 2
    sys.stdout.write(canonical_json())
    return 0


if __name__ == "__main__":
    sys.exit(main())
