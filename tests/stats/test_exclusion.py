"""除外の規則（src/stats/exclusion.py）のテスト（T-019〜T-022）。

実行（プロジェクトのルートで）:
    PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest discover -s tests/stats -v

データもネットワークも使わない。照合に使う名前は、すべてテストのために作ったもの。
このファイルは、除外の規則・入れる規則と一緒に、区分表の取得より前に順番1で封印する対象である
（docs/stats/tags-naive.md 5章）。読むのは src/stats/exclusion.py、同じく順番1で封印する
docs/stats/tags-naive.md、git の履歴の 2d23cdf の版の reviews/T-020.md（`git show`）だけで、
作業中の reviews/ は読まない（追記で見出しが増えても結果が変わらないようにするため）。
K（タグを入れる規則の数値）の値には触れない。
"""

import ast
import json
import os
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(os.path.dirname(HERE))
SRC = os.path.join(PROJECT, "src", "stats")
DOC = os.path.join(PROJECT, "docs", "stats", "tags-naive.md")
SCRIPT = os.path.join(SRC, "exclusion.py")
sys.path.insert(0, SRC)

import exclusion  # noqa: E402


def read_table(name):
    with open(DOC, encoding="utf-8") as f:
        lines = f.read().splitlines()
    i = lines.index("<!-- table:%s -->" % name)
    rows = []
    for line in lines[i + 1:]:
        if not line.startswith("|"):
            break
        rows.append([c.strip() for c in line.strip().strip("|").split("|")])
    return rows[0], rows[2:]


def _git_show(spec):
    """git の履歴の版を読む。git が使えなければ失敗にする（飛ばさない）。"""
    r = subprocess.run(["git", "show", spec], capture_output=True, cwd=PROJECT)
    if r.returncode != 0:
        raise AssertionError("git show %s に失敗：%s" % (spec, r.stderr.decode("utf-8", "replace")))
    return r.stdout


def owner_section(text, heading):
    """text のうち、行の全体が "## " + heading に一致する見出しの節（次の "## " の前まで）。

    一致する見出しがちょうど一つでなければ AssertionError。前方一致は使わない。
    """
    lines = text.splitlines()
    starts = [k for k, line in enumerate(lines) if line == "## " + heading]
    if len(starts) != 1:
        raise AssertionError("見出し「%s」が %d 個ある（ちょうど一つであること）" % (heading, len(starts)))
    k = starts[0]
    end = next((m for m in range(k + 1, len(lines)) if lines[m].startswith("## ")), len(lines))
    return "\n".join(lines[k:end]).rstrip()   # 末尾の空行は節に含めない


V1_TERMS = (
        "ELECTION", "ELECTIONS", "ELECTORAL", "ELECTED", "VOTE", "VOTES", "VOTING", "VOTER",
        "VOTERS", "BALLOT", "BALLOTS", "REFERENDUM", "REFERENDUMS", "POLITICS", "POLITICAL",
        "POLITICIAN", "POLITICIANS", "PARLIAMENT", "PARLIAMENTARY", "LEGISLATURE",
        "LEGISLATIVE", "CONGRESS", "SENATE", "SENATOR", "SENATORS", "LAWMAKER", "LAWMAKERS",
        "PRESIDENT", "PRESIDENTS", "PRESIDENTIAL", "PRIME MINISTER", "MINISTER", "MINISTERS",
        "GOVERNOR", "GOVERNORS", "MAYOR", "MAYORS", "LEADER", "LEADERS", "HEAD OF STATE",
        "CABINET", "COUP", "COUPS", "IMPEACH", "IMPEACHMENT", "REGIME", "REGIMES", "DICTATOR",
        "DICTATORS", "DICTATORSHIP", "PROTEST", "PROTESTS", "PROTESTER", "PROTESTERS",
        "DEMONSTRATOR", "DEMONSTRATORS", "SANCTION", "SANCTIONS", "DIPLOMACY", "DIPLOMATIC",
        "DIPLOMAT", "DIPLOMATS", "EMBASSY", "AMBASSADOR", "PROPAGANDA", "LOBBYING", "WAR",
        "WARS", "WARFARE", "MILITARY", "ARMY", "ARMIES", "ARMED", "NAVY", "AIR FORCE",
        "SOLDIER", "SOLDIERS", "TROOP", "TROOPS", "MILITIA", "MILITIAS", "INSURGENCY",
        "INSURGENT", "INSURGENTS", "REBEL", "REBELS", "REBELLION", "TERROR", "TERRORISM",
        "TERRORIST", "TERRORISTS", "EXTREMISM", "EXTREMIST", "EXTREMISTS", "JIHAD", "JIHADIST",
        "JIHADISTS", "CONFLICT", "CONFLICTS", "VIOLENCE", "VIOLENT", "ATTACK", "ATTACKS",
        "BOMB", "BOMBS", "BOMBING", "BOMBINGS", "EXPLOSIVE", "EXPLOSIVES", "WEAPON", "WEAPONS",
        "GUN", "GUNS", "FIREARM", "FIREARMS", "SHOOTING", "SHOOTINGS", "MISSILE", "MISSILES",
        "AIRSTRIKE", "AIRSTRIKES", "KILL", "KILLS", "KILLED", "KILLING", "KILLINGS", "MASSACRE",
        "MASSACRES", "GENOCIDE", "CEASEFIRE", "PEACEKEEPING", "PEACEKEEPER", "PEACEKEEPERS",
        "INVASION", "HOSTAGE", "HOSTAGES", "TORTURE", "RIOT", "RIOTS", "UNREST", "CRACKDOWN",
        "PERSECUTION", "SIEGE", "BLOCKADE", "DEFENSE", "DEFENCE", "REFUGEE", "REFUGEES",
        "DISPLACED", "ETHNIC CLEANSING", "CRIME", "CRIMES", "CRIMINAL", "CRIMINALS", "MURDER",
        "MURDERS", "HOMICIDE", "HOMICIDES", "ASSAULT", "ASSAULTS", "ROBBERY", "THEFT",
        "BURGLARY", "FRAUD", "CORRUPTION", "BRIBERY", "BRIBE", "BRIBES", "SMUGGLING",
        "TRAFFICKING", "NARCOTICS", "CARTEL", "CARTELS", "GANG", "GANGS", "MAFIA", "LAUNDERING",
        "EXTORTION", "KIDNAP", "KIDNAPPING", "KIDNAPPINGS", "RAPE", "HARASSMENT", "ABUSE",
        "ARREST", "ARRESTS", "ARRESTED", "POLICE", "PRISON", "PRISONS", "PRISONER", "PRISONERS",
        "JAIL", "INCARCERATION", "PROSECUTION", "PROSECUTOR", "PROSECUTORS", "INDICTMENT",
        "PIRACY", "SCAM", "SCAMS", "VANDALISM", "ARSON", "CYBERCRIME", "POPE", "KING", "KINGS",
        "QUEEN", "QUEENS", "PRINCE", "PRINCES", "PRINCESS", "MONARCH", "MONARCHY", "ROYAL",
        "ROYALS", "EMPEROR", "EMPRESS", "CELEBRITY", "CELEBRITIES", "DISASTER", "DISASTERS",
        "EARTHQUAKE", "EARTHQUAKES", "TSUNAMI", "TSUNAMIS", "FLOOD", "FLOODS", "FLOODING",
        "HURRICANE", "HURRICANES", "TYPHOON", "TYPHOONS", "CYCLONE", "CYCLONES", "TORNADO",
        "TORNADOES", "WILDFIRE", "WILDFIRES", "FIRE", "FIRES", "DROUGHT", "DROUGHTS",
        "LANDSLIDE", "LANDSLIDES", "VOLCANO", "VOLCANOES", "VOLCANIC", "ERUPTION", "AVALANCHE",
        "HEATWAVE", "HEAT WAVE", "STORM", "STORMS", "BLIZZARD", "FAMINE", "CASUALTY",
        "CASUALTIES", "FATALITY", "FATALITIES", "DEATH", "DEATHS", "DEAD", "EPIDEMIC",
        "EPIDEMICS", "PANDEMIC", "PANDEMICS", "OUTBREAK", "OUTBREAKS", "DISEASE", "DISEASES",
        "INFECTION", "INFECTIONS", "INFECTIOUS", "VIRUS", "VIRUSES", "INFLUENZA", "FLU",
        "EBOLA", "ZIKA", "CHOLERA", "MALARIA", "MEASLES", "HIV", "TUBERCULOSIS", "POLIO",
        "CORONAVIRUS", "COVID", "SARS", "MERS", "PLAGUE", "DENGUE", "VACCINE", "VACCINES",
        "VACCINATION", "QUARANTINE", "ETHNIC", "ETHNICITY", "ETHNICITIES", "TRIBE", "TRIBES",
        "TRIBAL", "RELIGION", "RELIGIONS", "RELIGIOUS", "SECTARIAN",
)


# 選べる区分の設定。2026-10-08 のオーナーの決定（0章7：案B、0章8：民族・宗教の集団を加える）。
# 出どころは exclusion.OWNER_CHOICE_SOURCE。テスト test_owner_choice_source が 2d23cdf の版の記録と照らす。
OWNER_CHOICE = ("ethnic_religious_group",)
# 規則そのもののテストは、選べる区分をすべて有効にして行う（オーナーの選択に依らないようにするため）。
ALL = exclusion.OPTIONAL_CATEGORIES


class TestExclusion(unittest.TestCase):
    # テストに使う名前は、すべてテストのために作ったもの。

    def terms_hit(self, name, desc=None, optional=ALL):
        return [(m[1], m[3]) for m in exclusion.exclusion_matches(name, desc, optional)]

    def ex(self, name, desc=None):
        return exclusion.is_excluded(name, desc, ALL)

    def test_tokens(self):
        self.assertEqual(exclusion.tokens("AB_123_Fragility-Conflict and violence"),
                         ("AB", "123", "FRAGILITY", "CONFLICT", "AND", "VIOLENCE"))
        self.assertEqual(exclusion.tokens("ELECTION2016"), ("ELECTION", "2016"))
        self.assertEqual(exclusion.tokens("x_covid19_y"), ("X", "COVID", "19", "Y"))
        self.assertEqual(exclusion.tokens(None), ())
        self.assertEqual(exclusion.tokens(""), ())

    def test_inflections(self):
        f = exclusion.inflections
        self.assertEqual(f("WAR"), {"WARS", "WARED", "WARING", "WARER", "WARERS"})
        self.assertEqual(f("VOTE"), {"VOTES", "VOTED", "VOTER", "VOTERS", "VOTING"})
        self.assertIn("ARMIES", f("ARMY"))
        self.assertIn("CASUALTIES", f("CASUALTY"))
        self.assertIn("TORNADOES", f("TORNADO"))
        self.assertIn("CRASHES", f("CRASH"))
        self.assertNotIn("GANGES", f("GANG"))
        self.assertNotIn("KIDNAPPING", f("KIDNAP"))   # 子音を重ねる形は作らない
        self.assertEqual(f("H1N1"), frozenset())

    def test_exact_and_inflection(self):
        self.assertIn(("WAR", "exact"), self.terms_hit("QQ_WAR_DAMAGE"))
        self.assertIn(("ELECTION", "exact"), self.terms_hit("x", "about the election results"))
        self.assertIn(("POLICE", "exact"), self.terms_hit("ab_cd_police"))
        self.assertIn(("WAR", "inflection"), self.terms_hit("AB_WARS"))
        self.assertIn(("KILL", "inflection"), self.terms_hit("AB_KILLED"))
        self.assertIn(("VOTE", "inflection"), self.terms_hit("AB_VOTING"))

    def test_digits_glued(self):
        self.assertIn(("ELECTION", "exact"), self.terms_hit("ELECTION2016"))
        self.assertIn(("COVID", "exact"), self.terms_hit("AB_COVID19"))
        self.assertIn(("H1N1", "exact"), self.terms_hit("AB_DISEASE_H1N1"))
        self.assertIn(("SARSCOV", "exact"), self.terms_hit("SARSCOV2"))

    def test_words_glued(self):
        self.assertIn(("CRASH", "glue-suffix"), self.terms_hit("AB_PLANECRASH"))
        self.assertIn(("ATTACK", "glue-suffix"), self.terms_hit("CYBERATTACK"))
        self.assertIn(("ATTACK", "glue-suffix"), self.terms_hit("CYBERATTACKS"))
        self.assertIn(("MILITARY", "glue-suffix"), self.terms_hit("PARAMILITARY"))
        self.assertIn(("CRIME", "glue-suffix"), self.terms_hit("AB_GENERALCRIME"))
        self.assertIn(("POLICE", "glue-prefix"), self.terms_hit("POLICEOFFICER"))
        self.assertIn(("AIR FORCE", "joined-exact"), self.terms_hit("AB_AIRFORCE"))
        self.assertIn(("PRIME MINISTER", "joined-exact"), self.terms_hit("PRIMEMINISTER"))

    def test_added_terms(self):
        for name in ("ASSASSINATION", "EXECUTION", "STABBING", "EXPLOSION", "PLANE_CRASH",
                     "CYBERATTACK", "ELECTION2016", "AB_ASSASSINATIONS", "AB_STABBINGS"):
            self.assertTrue(exclusion.is_excluded(name), name)

    def test_v1_terms_still_excluded(self):
        # 1cb463a の版の語（CRISISLEX を除く）は、今の版でもすべて外れる（後戻りが無いこと）。
        # V1_TERMS は git show 1cb463a:src/stats/tagrules.py の EXCLUSION_TERMS の写し。
        # 名前の欄と説明の欄の両方で確かめる（説明の欄ではくっつき一致を使わないため、別に見る）。
        for t in V1_TERMS:
            self.assertTrue(self.ex(t.replace(" ", "_")), t)
            self.assertTrue(self.ex("QQ_X", t), t)
            self.assertTrue(self.ex("QQ_X", "about " + t.lower() + " today"), t)

    def test_crisislex_removed(self):
        allt = [t for ts in exclusion.EXCLUSION_TERMS.values() for t in ts]
        self.assertNotIn("CRISISLEX", allt)
        self.assertFalse(exclusion.is_excluded("CRISISLEX_AB_CD"))

    def test_no_substring_match(self):
        for name in ("SOFTWARE", "AWARD", "WARNING", "WARM", "FARMS", "GRAPE", "AIDGROUPS",
                     "STOCKMARKET", "KINGDOM_TRAVEL", "FIREWORKS", "FLUENT", "COUPON", "PATRIOT",
                     "POLLEN", "GANGES", "SCAMPI", "DEADLINE", "GUNPOWDER", "EXECUTIVE"):
            self.assertFalse(exclusion.is_excluded(name), name)

    def test_glue_numbers(self):
        self.assertEqual((exclusion.PREFIX_MIN_LEN, exclusion.GLUE_MIN_REST), (6, 4))
        self.assertEqual(exclusion.SUFFIX_BLOCK_MAX_LEN, 4)
        self.assertEqual(exclusion.SUFFIX_BLOCK_ENDINGS, ("ING", "ED", "ER", "S"))
        self.assertEqual(exclusion.GLUE_FIELDS, ("name",))
        self.assertNotIn("ELECT", [t for ts in exclusion.EXCLUSION_TERMS.values() for t in ts])

    def test_prefix_needs_six_letters_and_rest(self):
        w = exclusion._word_matches
        self.assertEqual(w("POLICE", "POLICEABCD"), "glue-prefix")    # 6文字、残り4
        self.assertIsNone(w("POLICE", "POLICEABC"))                   # 残り3
        self.assertIsNone(w("CRASH", "CRASHABCDEF"))                  # 5文字は先頭で当たらない
        self.assertIsNone(w("WAR", "WARABCDEF"))
        for t in [t for ts in exclusion.EXCLUSION_TERMS.values() for t in ts]:
            tt = exclusion.tokens(t)
            if len(tt) == 1 and len(tt[0]) < exclusion.PREFIX_MIN_LEN:
                self.assertNotEqual(w(tt[0], tt[0] + "QQQQQQ"), "glue-prefix", t)

    def test_suffix_needs_rest(self):
        w = exclusion._word_matches
        self.assertEqual(w("WAR", "ABCDWAR"), "glue-suffix")
        self.assertIsNone(w("WAR", "ABCWAR"))
        self.assertEqual(w("CRASH", "ABCDCRASHES"), "glue-suffix")
        self.assertIsNone(w("KING", "ABCDKING"))     # 4文字以下で ING で終わる語は末尾で当たらない
        self.assertIsNone(w("CRASH", "ABCDCRASHXY"))  # 途中は見ない
        self.assertIsNone(w("COVID", "COVID19"))      # 数字を含む語には使わない（先に区切る）

    def test_glue_not_in_description(self):
        self.assertEqual(exclusion.exclusion_matches(
            "QQ_SOLAR_ENERGY", "Electricity from solar power, leadership in renewables, brainstorm"), [])
        self.assertTrue(exclusion.is_excluded("BRAINSTORM_SESSION"))
        self.assertTrue(exclusion.is_excluded("QQ_SOLAR_ENERGY", "Solar storms and grids"))  # 説明でも形の変化は当たる

    # 監査係が作った名前（差し戻しで示されたもの）と、統計係が作った名前。
    # 結果を既知の例として固定する（文書 2章 (1) の表 known-examples）。
    KNOWN_KEPT = (
        "ELECTRIC_POWER", "ELECTRONICS", "QUEENSLAND_TOURISM", "SOFTWARE", "AWARD", "WARNING", "WARM",
        "STEWARD", "FIREWORKS", "KINGDOM", "BOOKING", "BREAKING_NEWS", "SPEAKING", "THINKING", "PARKING",
        "GRAPE", "DRAPE", "PATRIOT", "BEGUN", "SKILLS", "RECOUP", "COUPON", "POLLEN", "SCAMPI", "GANGES",
        "PRINCETON", "STORMWATER", "PROTESTANT", "CABINETRY", "AIDGROUPS", "STOCKMARKET", "FLUENT",
        "DEADLINE", "GUNPOWDER", "EXECUTIVE",
    )
    KNOWN_MISSED = (
        "GUNCONTROL", "COUPATTEMPT", "HIVAIDS", "CARBOMB", "MINISTERIAL", "DEADLY",
    )
    KNOWN_OVEREXCLUDED = (
        "LEADERSHIP_TRAINING", "BRAINSTORM_SESSION", "ANTIVIRUS_SOFTWARE", "COMPATRIOT", "CAMPFIRE",
        "MARKETCRASH", "TEAMLEADER", "ROADKILL", "DEFENSELESS", "HEART_ATTACK", "AB_DEFENSE_ATTORNEY",
        "OBITUARY_DEATH", "AB_VACCINE_POLICY", "AB_FIRED", "HEARTATTACK", "SNOWSTORM",
        "SKYSCRAPER", "PAINKILLER", "SOFTSKILLS", "CABINETMAKER", "REGIMENTAL", "PROTESTANTISM",
    )
    KNOWN_EXCLUDED = (
        "CIVILWAR", "COLDWAR", "BIRDFLU", "SWINEFLU", "PLANECRASH", "CYBERATTACK", "PARAMILITARY",
        "MANSLAUGHTER", "TIMEBOMB", "SHOTGUN", "HANDGUN", "POLICEOFFICER", "ELECTION2016",
        "PRIMEMINISTER", "AIRFORCE", "DRUGABUSE", "IDENTITYTHEFT",
    )

    def test_known_examples(self):
        for n in self.KNOWN_KEPT + self.KNOWN_MISSED:
            self.assertFalse(self.ex(n), n)
        for n in self.KNOWN_OVEREXCLUDED + self.KNOWN_EXCLUDED:
            self.assertTrue(self.ex(n), n)

    def test_doc_known_examples(self):
        head, rows = read_table("known-examples")
        got = {r[0]: tuple(x.strip() for x in r[1].split(",")) for r in rows}
        self.assertEqual(got, {"残す（正しく残す）": self.KNOWN_KEPT, "残る（取りこぼし）": self.KNOWN_MISSED,
                               "外れる（外しすぎ）": self.KNOWN_OVEREXCLUDED,
                               "外れる（正しく外す）": self.KNOWN_EXCLUDED})

    def test_phrase_needs_contiguous_tokens(self):
        self.assertTrue(exclusion.is_excluded("AB_CD_PRIME_MINISTER"))
        self.assertEqual(exclusion.exclusion_matches("PRIME_RATE"), [])
        self.assertIn(("politics_election", "HEAD OF STATE", "description", "exact"),
                      exclusion.exclusion_matches("X", "visit by a head of state"))
        self.assertFalse(exclusion.is_excluded("HEAD_STATE_OF"))

    def test_description_used_and_reported(self):
        m = exclusion.exclusion_matches("QQ_GENERAL", "Outbreak of cholera", ALL)
        self.assertIn(("disease_general", "OUTBREAK", "description", "exact"), m)
        self.assertIn(("disease_named", "CHOLERA", "description", "exact"), m)

    def test_optional_categories(self):
        self.assertEqual(exclusion.OPTIONAL_CATEGORIES, ("disease_named", "ethnic_religious_group"))
        # 案B：病名を使わない
        self.assertTrue(exclusion.is_excluded("AB_EBOLA", optional=ALL))
        self.assertFalse(exclusion.is_excluded("AB_EBOLA", optional=("ethnic_religious_group",)))
        self.assertTrue(exclusion.is_excluded("AB_DISEASE", optional=()))
        self.assertFalse(exclusion.is_excluded("AB_ETHNICITY_X", optional=("disease_named",)))
        with self.assertRaises(ValueError):
            exclusion.is_excluded("X", optional=("crime",))

    def test_owner_choice(self):
        # 既定の有効な区分は、オーナーの決定（OWNER_CHOICE）と同じでなければならない。
        self.assertEqual(exclusion.ENABLED_OPTIONAL_CATEGORIES, OWNER_CHOICE)
        self.assertEqual(exclusion.enabled_categories(),
                         tuple(c for c in exclusion.EXCLUSION_TERMS
                               if c not in exclusion.OPTIONAL_CATEGORIES or c in OWNER_CHOICE))
        rec = json.loads(exclusion.canonical_json())
        self.assertEqual(rec["enabled_optional_categories"], list(OWNER_CHOICE))
        self.assertEqual(rec["owner_choice_source"], exclusion.OWNER_CHOICE_SOURCE)
        self.assertEqual(rec["optional_choice_status"], "decided")
        # 案B：病名だけのテーマは外れない。民族・宗教の語は外れる。
        self.assertFalse(exclusion.is_excluded("AB_EBOLA"))
        self.assertTrue(exclusion.is_excluded("AB_DISEASE"))
        self.assertTrue(exclusion.is_excluded("AB_ETHNICITY_X"))

    def test_status_is_computed_from_source(self):
        # 状態は出どころの有無から計算する（直書きしない）。
        saved = exclusion.OWNER_CHOICE_SOURCE
        try:
            exclusion.OWNER_CHOICE_SOURCE = None
            self.assertEqual(exclusion.optional_choice_status(), "undecided")
            self.assertEqual(json.loads(exclusion.canonical_json())["optional_choice_status"], "undecided")
        finally:
            exclusion.OWNER_CHOICE_SOURCE = saved
        self.assertEqual(exclusion.optional_choice_status(), "decided")

    def test_owner_choice_source(self):
        # 出どころ（commit:ファイル と見出し）が git の履歴に実在し、その節にオーナーの決定の文があること。
        # 作業中の reviews/T-020.md は読まない。2d23cdf の版を git show で読む。
        spec, heading = exclusion.OWNER_CHOICE_SOURCE.split(" ", 1)
        self.assertEqual(spec, "2d23cdf:reviews/T-020.md")
        section = owner_section(_git_show(spec).decode("utf-8"), heading)
        self.assertIn("> 病名は案B", section)
        self.assertIn("> 民族、宗教の集団は除外の区分に加える。", section)
        self.assertIn("> そのほかこのまま承認の項目は承認します", section)

    def test_owner_section_exact_heading(self):
        # 見出しは完全一致で照らす。同じ日の別の見出しが後から追記されても、節は一つに決まる。
        text = _git_show("2d23cdf:reviews/T-020.md").decode("utf-8")
        heading = exclusion.OWNER_CHOICE_SOURCE.split(" ", 1)[1]
        want = owner_section(text, heading)
        appended = text + "\n## 2026-10-08 オーナーの発言（追記）\n\n> 別の発言\n" \
                          "\n## %s 2\n\n> さらに別の発言\n" % heading
        self.assertEqual(owner_section(appended, heading), want)
        with self.assertRaises(AssertionError):
            owner_section(text + "\n## %s\n" % heading, heading)   # 完全に同じ見出しが二つなら止まる
        with self.assertRaises(AssertionError):
            owner_section(text, "2026-10-08 オーナーの発言")          # 前方一致では当たらない

    # 選べる区分を外すと結果が変わる、作った名前の例（文書 2章 (8)）。
    OPTION_SENSITIVE = {
        "disease_named": ("BIRDFLU", "SWINEFLU", "AB_EBOLA", "AB_COVID19", "AB_CHOLERA_X", "SARSCOV2"),
        "ethnic_religious_group": ("AB_ETHNICITY_X", "AB_TRIBAL_LAND", "AB_RELIGIOUS_X"),
    }

    def test_option_sensitive_examples(self):
        for cat, names in self.OPTION_SENSITIVE.items():
            without = tuple(c for c in ALL if c != cat)
            for n in names:
                self.assertTrue(exclusion.is_excluded(n, optional=ALL), n)
                self.assertFalse(exclusion.is_excluded(n, optional=without), n)

    def test_doc_option_sensitive(self):
        head, rows = read_table("option-sensitive")
        got = {r[0]: tuple(x.strip() for x in r[1].split(",")) for r in rows}
        self.assertEqual(got, self.OPTION_SENSITIVE)

    def test_joined_only_in_name(self):
        self.assertIn(("AIR FORCE", "joined-exact"), self.terms_hit("AB_AIRFORCE"))
        self.assertEqual(exclusion.exclusion_matches("QQ_X", "the airforce base", ALL), [])
        self.assertTrue(self.ex("QQ_X", "the air force base"))
        rec = json.loads(exclusion.canonical_json())
        self.assertIn("(name field only) the joined phrase", rec["match"])

    def test_suffix_block_words(self):
        blocked = [w for ts in exclusion.EXCLUSION_TERMS.values() for w in ts
                   if " " not in w and not exclusion._suffix_allowed(w)]
        self.assertEqual(blocked, ["KING", "SARS", "MERS"])

    def test_cybercrime_restored(self):
        self.assertIn("CYBERCRIME", exclusion.EXCLUSION_TERMS["crime"])
        self.assertTrue(self.ex("QQ_X", "rise of cybercrime"))

    def test_neutral_examples_kept(self):
        for name, desc in (("QQ_STOCKMARKET", "Stock market"), ("EDUCATION", None),
                           ("QQ_SOLAR", "Solar power"), ("QQ_INNOVATION", ""),
                           ("AB_AGRICULTURE", "Farming and crops"), ("AB_TOURISM", None)):
            self.assertFalse(exclusion.is_excluded(name, desc), name)

    def test_terms_wellformed(self):
        allt = [t for ts in exclusion.EXCLUSION_TERMS.values() for t in ts]
        self.assertEqual(len(allt), len(set(allt)))
        for t in allt:
            self.assertRegex(t, r"\A[A-Z0-9]+( [A-Z0-9]+)*\Z")
        self.assertEqual(set(exclusion.EXCLUSION_TERMS), set(exclusion.CLAUDE_CATEGORY_OF))
        self.assertEqual(set(v for v in exclusion.CLAUDE_CATEGORY_OF.values() if v),
                         set(exclusion.CLAUDE_CATEGORIES))
        self.assertEqual(len(exclusion.CLAUDE_CATEGORIES), 6)
        self.assertEqual(exclusion.CLAUDE_CATEGORY_OF["ethnic_religious_group"], "民族・宗教の集団")

    def test_no_per_theme_exception_mechanism(self):
        # 一件ずつの例外を持たない：照合は名前と説明と語の一覧だけで決まる。
        with open(os.path.join(SRC, "exclusion.py"), encoding="utf-8") as f:
            src = f.read()
        for word in ("ALLOWLIST", "DENYLIST", "EXCEPTIONS =", "FORCE_INCLUDE", "FORCE_EXCLUDE"):
            self.assertNotIn(word, src)

    def test_doc_terms_table(self):
        head, rows = read_table("terms")
        self.assertEqual(head, ["区分", "CLAUDE.md の区分", "語"])
        got = {r[0]: tuple(x.strip() for x in r[2].split(",")) for r in rows}
        self.assertEqual(got, exclusion.EXCLUSION_TERMS)
        self.assertEqual([r[0] for r in rows], list(exclusion.EXCLUSION_TERMS))
        for r in rows:
            want = exclusion.CLAUDE_CATEGORY_OF[r[0]]
            self.assertEqual(r[1], want)


class TestExclusionOutput(unittest.TestCase):
    def run_cli(self, *args):
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
        return subprocess.run([sys.executable, "-B", SCRIPT, *args],
                              capture_output=True, text=True, env=env, cwd=PROJECT)

    def test_cli_deterministic(self):
        a, b = self.run_cli(), self.run_cli()
        self.assertEqual(a.returncode, 0, a.stderr)
        self.assertEqual(a.stdout, b.stdout)
        self.assertEqual(a.stdout, exclusion.canonical_json())
        rec = json.loads(a.stdout)
        self.assertEqual(rec["per_theme_exceptions"], "none")
        self.assertEqual(rec["prefix_min_len"], 6)
        self.assertEqual(rec["glue_min_rest"], 4)
        self.assertIn("only fixes of defects", rec["changes_after_seeing_table"])
        self.assertIn("1cb463a", rec["sealed_versions"])
        self.assertEqual(rec["terms"], {k: list(v) for k, v in exclusion.EXCLUSION_TERMS.items()})

    def test_no_k_in_output(self):
        # 除外の規則の出力は、入れる規則（tagrules.py）と分けたファイルの出力で、K の値を含まない。
        # 二つは同じ順番1で封印する（docs/stats/tags-naive.md 5章）。分けたままにするのは、この性質を確かめるため。
        rec = json.loads(exclusion.canonical_json())
        self.assertNotIn("k_articles_per_day", json.dumps(rec))
        self.assertNotIn("inclusion", rec)

    def test_cli_rejects_args(self):
        self.assertEqual(self.run_cli("--x").returncode, 2)


class TestExclusionNoDataNoNetwork(unittest.TestCase):
    def test_imports_clock_files(self):
        with open(SCRIPT, encoding="utf-8") as f:
            tree = ast.parse(f.read())
        names = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names.update(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom):
                names.add((node.module or "").split(".")[0])
            if isinstance(node, ast.Attribute):
                self.assertNotIn(node.attr, {"today", "now", "utcnow", "time"})
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                self.assertNotEqual(node.func.id, "open")
        self.assertEqual(names - {"json", "re", "sys"}, set())


if __name__ == "__main__":
    unittest.main()
