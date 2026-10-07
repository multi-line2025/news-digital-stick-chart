# タグの一覧の規則、素朴な予測、採点計画の一部（T-019）

仮の名前：tagrules-v1（タグの一覧の規則）、naive-v1（素朴な予測）、scoring-partial-v1（採点計画の一部）。
どれも正式な版の番号ではない。正式な番号は、封印係の追記のみの記録で何件目かによって決まる。

この文書は、手順4（手法を作る期間のデータで試運転する）の前に決めて封印する「決め方」をまとめた提案である。
数値のうち A（＝最低の報道量 V）だけは、ここで決めた式に手法を作る期間のデータを入れて決まる。

- 値と語の一覧は `src/stats/tagrules.py`・`src/stats/naive.py`・`src/stats/scoring.py` の定数で、この文書の表はその写しである。`tests/stats/test_t019.py` で照合する。
- GDELT のデータ、ファイル一覧、テーマの区分表、ネットワークは使っていない（7章）。
- 封印はしていない。封印は、オーナーの承認のあと封印係が行う（5章）。

再計算の手順（プロジェクトのルートで）：

```
PYTHONDONTWRITEBYTECODE=1 python3 -B src/stats/tagrules.py
PYTHONDONTWRITEBYTECODE=1 python3 -B src/stats/naive.py
PYTHONDONTWRITEBYTECODE=1 python3 -B src/stats/scoring.py
PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest discover -s tests/stats -v
```

## 0. オーナーに承認をお願いしたい点

1. **A の決め方**（1章 (2)）：A = 10 ÷ N_med。N_med は、手法を作る期間の区画で、欠けた日でない日の全体の報道量の中央値。「全体の報道量が普段どおりの日に、1日あたり平均10件」に当たる比率である。V は A と同じ値にする（T-011 で決定済み）。
2. **「全体にわたって存在する」の定義**（1章 (1)）：区画を暦の四半期（24個）に分け、どの四半期でも、欠けた日でない日の報道量の合計が1件以上あること。
3. **除外の規則**（2章）：テーマの名前と説明を語に区切り、決めた語の一覧（2章 (2) の表）と完全に一致する語があれば外す。部分一致と語幹の処理はしない。一件ずつの例外は持たない。
4. **民族・宗教の集団の区分を足すか**（2章 (4)）：CLAUDE.md の5つの区分の外にある。統計係の推奨は「足す」。足す場合は CLAUDE.md の決定事項の変更になる。
5. **組織名**（2章 (4)）：別の規則を作らない。5つの区分の語に当たる組織のテーマだけが外れる。
6. **区分表を見たあとで語を変える手順**（2章 (5)）：新しい版として封印し、オーナーの承認を得る。変えてよいのは語だけで、テーマ名を名指しで足したり外したりしない。手順4の開始（method-access）のあとは、v0 の一覧を変えない。
7. **素朴な予測の形**（3章）：特徴量6つと切片のロジスティック回帰を、21組それぞれで作る。手法を作る期間での改訂は、特徴量を足すことだけを認める。
8. **素朴な予測の過去分**（3章 (4)）：7日のまとまりの分を含めて399日。periods.py の LOOKBACK_DAYS（400日）に収まり、区切りの作り直しは要らない。399 をきっかけの値として、封印の記録に追記する。
9. **一度跳ねたタグ**（4章 (1)）：直近56日のうちに、7日の平均が max(2 × B(t), V) を超えたタグは、その週の対象にしない。
10. **「対象なし」の週**（4章 (2)）：試行として数えない。記録は残し、件数と種類を公開する。
11. **封印の順番**（5章）：この文書の規則は、テーマの区分表の取得（T-018）より前に封印する必要がある。T-018 の取得がこれより先になると、「区分表を見る前に決めた」ことを記録で示せなくなる。

## 1. タグを入れる規則の数値の決め方（未決事項3）

規則（CLAUDE.md）：手法を作る期間の全体にわたって存在し、平均報道量が下限 A 以上のテーマ。

<!-- table:tag-constants -->
| 定数 | 値 | 意味 |
|---|---|---|
| K_ARTICLES_PER_DAY | 10 | A = K ÷ N_med の K（1日あたりの件数） |
| MIN_COUNT_PER_QUARTER | 1 | 存在の条件：各四半期の報道量の合計の下限 |
| 四半期の数 | 24 | 手法を作る期間の区画（2015-03-02 から 2020-12-14）を暦の四半期で区切った数 |

### (1) 全体にわたって存在する
- 区画を暦の四半期で区切る。最初は 2015-03-02 から 2015-03-31、最後は 2020-10-01 から 2020-12-14 で、どちらも区画の端で切る。
- どの四半期でも、欠けた日でない日のそのテーマの報道量の合計が1件以上なら、存在するとみなす。
- 欠けた日でない日が一日も無い四半期は、条件から外す。外した四半期の番号は出力に残し、公開する。
- 理由：
  - データ源は、テーマの体系に無いテーマを付けない。そのため、1件でも付いていれば、その四半期にテーマが体系に入っていたと読める。件数の大きさは (2) の A で見るので、ここでは存在だけを見る。
  - 月ごとにすると、季節にだけ現れるテーマが外れやすくなる。季節や予定された行事のテーマは、素朴な予測が取るべき島なので、一覧から外したくない。年ごとにすると、区画の途中で生まれたテーマを見落とす。四半期はその間をとった。
- 代償：一つの四半期まるごと報道が無い季節のテーマ（たとえば4年に1度の行事だけのテーマ）は、この規則で外れる。この規則は量ではなく存在を見るためのもので、データを見ずにこれ以上細かく分けられない。

### (2) A の決め方
- テーマの平均報道量は、区画の欠けた日でない日の比率 r(d) の単純平均とする（日ごとに同じ重み）。r(d) の分子と分母の数え方は、収集係が決める報道量の数え方に従う。
- **A = K ÷ N_med、K = 10**。N_med は、欠けた日でない日の全体の報道量（r(d) の分母）の中央値。日数が偶数なら真ん中の二つの平均。
- 平均が A 以上なら入れる。平均は浮動小数点で計算し（math.fsum）、A（分数）との比較は、その値を分数に直して行う。比較のところで丸めは入れない（`build_tag_list()`）。
- V = A（docs/stats/candidates.md 3章 (4)）。島の判定には「7日の平均 > V」が要るので、全体の報道量が普段どおりの週なら、島になるには7日で70件を超える報道が要る。
- 分位で決める案（例：全テーマの平均の上位何%）を採らなかった理由：分位はテーマの体系にどれだけ細かいテーマが多いかで動き、件数の少なさから来るばらつきとは関係がない。V の役目は、少ない件数のばらつきで島にならないようにすることである。そのため、件数で決める形にした。
- K = 10 にした理由：7日で70件なら、件数の偶然のばらつき（ポアソン分布なら標準偏差は約8.4件）に比べて十分大きい。1日に1本の記事も無いテーマを「ニュースになった」と呼ばないための下限でもある。この値はデータを見ずに決めた。
- 結果の一覧の件数が多すぎても少なすぎても、K を変えない。変える場合は、手法を作る期間のデータを見たあとの変更として、新しい版で封印し、オーナーの承認を得て、前の版の結果と並べて公開する。

### (3) 一覧を作る手順（`build_tag_list()`）
- 対象のテーマは、区分表に載っているテーマと、手法を作る期間のデータに現れたテーマを合わせたもの。
- 入力は、手法を作る期間の区画のデータだけ。引数に区画の外の日付が一つでもあれば止まる（テスト `test_rejects_dates_outside_block`）。閾値を決める期間より後のデータを、渡す余地を無くすため。
- 欠けた日の一覧は、封印したもの（candidates.md 3章 (5)）を使う。欠けた日の報道量は、存在の条件にも平均にも入れない。
- 出力には、テーマごとに四半期ごとの件数、平均、A 以上か、一致した除外の語（区分・語・名前と説明のどちらの欄か）、一覧に入ったかを載せる。一覧に入らなかったテーマとその理由も、すべて公開する。

## 2. 除外の規則の作り方（未決事項5）

### (1) 照合のしかた
- 使うのは区分表の **名前** と **説明** の二つの欄だけ。ほかの欄があっても使わない。説明が無ければ名前だけで照合する。
- 名前と説明を大文字にし、英字と数字以外（下線、空白、記号）で区切って語の並びにする（`tokens()`）。
- 一覧の語が、語の並びの中に完全に一致して現れれば外す。複数の語からなるもの（例：PRIME MINISTER）は、続けて現れたときだけ一致とする。
- 部分一致はしない。たとえば WAR は SOFTWARE や AWARD に一致しない（テスト `test_no_substring_match`）。
- 語幹の処理もしない。単数形と複数形などは、一覧に一つずつ書いた。
- どの区分の語に当たっても同じく外す。区分の名前は、報告のためだけに使う。
- 名前と説明のどちらかで当たれば外す。説明に語が付随して出てくるだけのテーマも外れることになる。外しすぎの方向の誤りを選んだ。5つの区分のテーマが一覧に残る誤りの方が、プロジェクトの目的に反するため。

### (2) 語の一覧

<!-- table:terms -->
| 区分 | 語 |
|---|---|
| politics_election | ELECTION, ELECTIONS, ELECTORAL, ELECTED, VOTE, VOTES, VOTING, VOTER, VOTERS, BALLOT, BALLOTS, REFERENDUM, REFERENDUMS, POLITICS, POLITICAL, POLITICIAN, POLITICIANS, PARLIAMENT, PARLIAMENTARY, LEGISLATURE, LEGISLATIVE, CONGRESS, SENATE, SENATOR, SENATORS, LAWMAKER, LAWMAKERS, PRESIDENT, PRESIDENTS, PRESIDENTIAL, PRIME MINISTER, MINISTER, MINISTERS, GOVERNOR, GOVERNORS, MAYOR, MAYORS, LEADER, LEADERS, HEAD OF STATE, CABINET, COUP, COUPS, IMPEACH, IMPEACHMENT, REGIME, REGIMES, DICTATOR, DICTATORS, DICTATORSHIP, PROTEST, PROTESTS, PROTESTER, PROTESTERS, DEMONSTRATOR, DEMONSTRATORS, SANCTION, SANCTIONS, DIPLOMACY, DIPLOMATIC, DIPLOMAT, DIPLOMATS, EMBASSY, AMBASSADOR, PROPAGANDA, LOBBYING |
| conflict_violence | WAR, WARS, WARFARE, MILITARY, ARMY, ARMIES, ARMED, NAVY, AIR FORCE, SOLDIER, SOLDIERS, TROOP, TROOPS, MILITIA, MILITIAS, INSURGENCY, INSURGENT, INSURGENTS, REBEL, REBELS, REBELLION, TERROR, TERRORISM, TERRORIST, TERRORISTS, EXTREMISM, EXTREMIST, EXTREMISTS, JIHAD, JIHADIST, JIHADISTS, CONFLICT, CONFLICTS, VIOLENCE, VIOLENT, ATTACK, ATTACKS, BOMB, BOMBS, BOMBING, BOMBINGS, EXPLOSIVE, EXPLOSIVES, WEAPON, WEAPONS, GUN, GUNS, FIREARM, FIREARMS, SHOOTING, SHOOTINGS, MISSILE, MISSILES, AIRSTRIKE, AIRSTRIKES, KILL, KILLS, KILLED, KILLING, KILLINGS, MASSACRE, MASSACRES, GENOCIDE, CEASEFIRE, PEACEKEEPING, PEACEKEEPER, PEACEKEEPERS, INVASION, HOSTAGE, HOSTAGES, TORTURE, RIOT, RIOTS, UNREST, CRACKDOWN, PERSECUTION, SIEGE, BLOCKADE, DEFENSE, DEFENCE, REFUGEE, REFUGEES, DISPLACED, ETHNIC CLEANSING |
| crime | CRIME, CRIMES, CRIMINAL, CRIMINALS, MURDER, MURDERS, HOMICIDE, HOMICIDES, ASSAULT, ASSAULTS, ROBBERY, THEFT, BURGLARY, FRAUD, CORRUPTION, BRIBERY, BRIBE, BRIBES, SMUGGLING, TRAFFICKING, NARCOTICS, CARTEL, CARTELS, GANG, GANGS, MAFIA, LAUNDERING, EXTORTION, KIDNAP, KIDNAPPING, KIDNAPPINGS, RAPE, HARASSMENT, ABUSE, ARREST, ARRESTS, ARRESTED, POLICE, PRISON, PRISONS, PRISONER, PRISONERS, JAIL, INCARCERATION, PROSECUTION, PROSECUTOR, PROSECUTORS, INDICTMENT, PIRACY, SCAM, SCAMS, VANDALISM, ARSON, CYBERCRIME |
| specific_person | POPE, KING, KINGS, QUEEN, QUEENS, PRINCE, PRINCES, PRINCESS, MONARCH, MONARCHY, ROYAL, ROYALS, EMPEROR, EMPRESS, CELEBRITY, CELEBRITIES |
| disaster_disease | DISASTER, DISASTERS, EARTHQUAKE, EARTHQUAKES, TSUNAMI, TSUNAMIS, FLOOD, FLOODS, FLOODING, HURRICANE, HURRICANES, TYPHOON, TYPHOONS, CYCLONE, CYCLONES, TORNADO, TORNADOES, WILDFIRE, WILDFIRES, FIRE, FIRES, DROUGHT, DROUGHTS, LANDSLIDE, LANDSLIDES, VOLCANO, VOLCANOES, VOLCANIC, ERUPTION, AVALANCHE, HEATWAVE, HEAT WAVE, STORM, STORMS, BLIZZARD, FAMINE, CRISISLEX, CASUALTY, CASUALTIES, FATALITY, FATALITIES, DEATH, DEATHS, DEAD, EPIDEMIC, EPIDEMICS, PANDEMIC, PANDEMICS, OUTBREAK, OUTBREAKS, DISEASE, DISEASES, INFECTION, INFECTIONS, INFECTIOUS, VIRUS, VIRUSES, INFLUENZA, FLU, EBOLA, ZIKA, CHOLERA, MALARIA, MEASLES, HIV, TUBERCULOSIS, POLIO, CORONAVIRUS, COVID, SARS, MERS, PLAGUE, DENGUE, VACCINE, VACCINES, VACCINATION, QUARANTINE |
| ethnic_religious_group | ETHNIC, ETHNICITY, ETHNICITIES, TRIBE, TRIBES, TRIBAL, RELIGION, RELIGIONS, RELIGIOUS, SECTARIAN |

### (3) 語の選び方と、区分ごとの境目
語は、区分の意味から一般の英語の語を挙げて選んだ。区分表は見ていない。
- 政治・選挙：選挙と投票、議会、国や地方の首長と閣僚、政変、抗議行動、外交と制裁。GOVERNMENT と GOVERNANCE は入れていない。行政一般のテーマ（予算、公共事業など）まで外れるため。移民などの政策の論点も入れていない。
- 紛争・暴力：戦争と軍、武装集団、テロ、攻撃と武器、殺害、暴動、難民。SECURITY は入れていない（食料安全保障、サイバーセキュリティなども外れるため）。DEFENSE は入れた（法廷の弁護側も外れるが、外しすぎの方向の誤りとして受け入れる）。
- 犯罪：犯罪の種類、汚職、組織犯罪、逮捕・警察・刑務所・訴追。
- 特定の人物：GDELT のテーマの欄は分類の名前で、人物名は別の欄（人物の欄）に入る（T-001）。この欄は、収集係の項目の一覧に入れず、取得もしない。テーマの名前で一人の人物を指しやすいのは、君主・教皇などの地位と、有名人の分類なので、それらの語を入れた。大統領・首相などは政治・選挙の区分で外れる。
- 災害・感染症：自然災害、火災、飢饉、死傷、感染症とワクチン。CRISISLEX は、GDELT の公開文書でテーマの体系の一つ（危機の際の言葉の一覧）として名前が挙がっていることを、一般の知識として知っていたので入れた。
- 例外：ATTACK は HEART ATTACK（心臓発作）にも当たる。DEAD と DEATH は訃報のテーマにも当たる。どちらも外しすぎの方向の誤りとして受け入れる。

**区分表を見ずに決めたことの限界**：
- GDELT のテーマ名の一部（KILL、ARREST、PROTEST など）が一般の英語と同じ形であることは、一般の知識として知っている。知っているテーマ名に合わせて語を足し引きしてはいないが、その知識の影響を完全に切り離したとは言えない。
- 区分表の名前には、語をつなげて一語にしたもの（例：二つの語の間に区切りの無い名前）があるかもしれない。この規則は部分一致をしないので、そうした名前の中の語には当たらない。説明の欄で当たらなければ、一覧に残る。
- 説明の欄が無い区分表なら、名前だけで照合することになり、取りこぼしが増える。

### (4) 組織名と民族集団のテーマ（T-001 の申し送り）
T-001 の報告では、テーマの欄に組織名と民族集団が入ることがある（codebook）。

**民族・宗教の集団：外す区分を足すことを推奨する（オーナーの承認が要る）**
- CLAUDE.md の5つの区分は「特定の人物」で、集団は入らない。そのため、この区分を足すことは CLAUDE.md の決定事項の変更になる。
- 推奨の理由：
  - 特定の民族・宗教の集団が来週ニュースになる、という予言を公開すること自体に、迫害や衝突を予告する読まれ方をする危うさがある。
  - そうしたテーマの報道が跳ねるのは、多くが紛争・暴力や犯罪の報道と重なると考えられる。しかし、その重なりは区分表の名前と説明の語では捕まえられない。
- 語は `ethnic_religious_group` の行（ETHNIC、RELIGIOUS など）。言語の分類（言語の名前）は入れていない。言語の名前は、場所や報道の言語として付くことが多いと考えたため。
- オーナーが足さないと決めた場合は、この行を除いた版を封印する。区分表を見る前なので、どちらを選んでも選び出しにはならない。

**組織名：別の規則を作らない**
- 組織そのものは、CLAUDE.md の5つの区分に入らない。武装集団や政党などの組織のテーマは、TERROR、POLITICAL などの語で外れる。
- 名前と説明だけから「組織の名前であること」を機械的に見分ける規則は、区分表を見ずには作れない。区分表を見てから作れば、一件ずつの判断に近くなる。

### (5) 区分表を見たあとで語を変えたくなった場合
- 統計係は、自分で語を変えない。変えたい語と理由をリードに報告する。
- 変える場合は、次のすべてを満たす。
  - オーナーの承認を得て、新しい版として封印する。前の版は消さず、版ごとの一覧を並べて公開する。
  - 変えるのは語だけ。テーマ名を名指しで足したり外したりしない（CLAUDE.md「一件ずつ人の判断で入れたり外したりしない」）。足す語は、その区分の意味を表す一般の英語の語であること。
  - 変更点（足した語・除いた語）と、その変更で一覧の出入りが変わるテーマの一覧を公開する。
  - 手順4の開始（method-access の記録）より前に封印する。区分表には件数が無いので、この時点で変えても、報道量の動きを見て選ぶことにはならない。
- method-access のあと（手法を作る期間の報道量を見たあと）は、v0 の一覧の除外の規則を変えない。変える必要が出た場合は、CLAUDE.md のとおり別の版として封印し直し、版ごとに別々に採点する。
- 版の番号は、追記のみの記録で、この規則の封印が何件目かで決まる。

## 3. 素朴な予測の設計

### (1) 何を使うか
CLAUDE.md の定義（直近の報道量、季節性、予定された行事＝去年の同じ時期の報道量）に従う。物差しは、普段の水準・判定と同じ7日の平均で、欠けた日を含むまとまりは使わない。

予言日 t、倍率 m、判定期間 H、最低の報道量 V について、次の値を t-1 以前のデータだけから計算する。

- B(t)：普段の水準（candidates.baseline_level）
- c(t)：予言の時点の報道量（candidates.current_level）
- P：終わりの日が t-28 から t-1 の7日の平均の最大（直近の山）。無ければ c(t)
- S0：去年の判定期間 [t+1-365, t+H-365] に完全に収まる7日の平均の最大（去年のちょうど同じ時期）
- S35：同じ期間を前後35日ずつ広げた中の最大（日付の動く行事のための幅）

特徴量は、島の判定の限界 L = max(m × B(t), V) に対する比の対数で表す。g(x) = log((x + V) / (L + V))。

<!-- table:naive-features -->
| 特徴量 | 定義 |
|---|---|
| intercept | 1 |
| recent | g(c(t)) |
| recent_peak | g(P) |
| season_exact | g(S0)。S0 が無く S35 があれば S0 = S35 |
| season_wide | g(S35) |
| season_none | S35 が無ければ 1（このとき season_exact と season_wide は 0）、あれば 0 |
| size | log((B(t) + V) / V) |

- 限界 L との比にした理由：島は「7日の平均が L を超える」ことなので、去年の同じ時期の山が今年の L を超えていたか、を直接表せる。L は t の時点で決まる。
- V を足してから比をとる理由：B(t) と c(t) が0のタグがある（オーナーの決定で対象に残る）。0 の対数を避け、V より十分小さい値どうしの差を大きく扱わないため。
- 前後35日の幅：periods.py の SEASONAL_MARGIN_DAYS（35日）。日付の動く行事（年によって最大35日ずれる移動祝日など）を拾うための幅である。ちょうどの期間（S0）と広げた期間（S35）を両方入れ、どちらが効くかはモデルの係数に任せる。

### (2) モデル
- 組み合わせ（倍率7 × 判定期間3 = 21組）ごとのロジスティック回帰。係数は、手法を作る期間の予言日（月曜）の対象のタグ（4章の冷却を含む対象の規則）と、その判定（candidates.judge。判定不能は除く）だけで決める。
- 推定の手順は固定する（`fit_logistic()`）：係数0から始め、リッジの重み1.0（切片にも掛ける）を付けたニュートン法。目的関数が減らなければ一歩を半分にする（最大30回）。係数の変化が 1e-10 未満で止める。100回で収まらなければ、そのモデルは使わず、作業を止めて報告する。
- リッジを付けた理由：ある特徴量で完全に分かれるデータや、島が一つも無い組み合わせ（大きい倍率と短い判定期間では起こりうる）でも、係数が無限に発散しないようにするため。島が一つも無いと切片が発散するので、切片にも掛ける。件数が多ければ、重み1.0の影響は小さい。
- 確率は、封印した係数と上の特徴量から `predict()` で計算する。スティックチャートのモデルにも、同じ特徴量を入力として入れる（method.md 3章）。

<!-- table:naive-constants -->
| 定数 | 値 |
|---|---|
| SEASON_SHIFT_DAYS | 365 |
| SEASON_MARGIN_DAYS | 35 |
| RECENT_PEAK_DAYS | 28 |
| RIDGE_LAMBDA | 1.0 |
| MAX_ITER | 100 |
| TOL | 1e-10 |

### (3) 改訂の規則
- 手法を作る期間は自由に探索してよい期間なので、素朴な予測の特徴量を見直すことはありうる。ただし、改訂は **特徴量を足すことだけ** とし、除いたり定義を変えたりしない。足した特徴量は、スティックチャートのモデルの入力にも足す。
- 改訂は新しい版として封印し、naive-v1 の結果も並べて公開する。
- 理由：素朴な予測を弱くする向きの変更（効いている特徴量を外すなど）ができると、スティックチャートが上回ったように見せられる。足すだけなら、手法を作る期間の上で素朴な予測が弱くなることはない。
- 最後の版は、最初の threshold-access の記録より前に封印する（candidates.md 6章）。

**限界**：
- 去年の同じ時期だけを見るので、4年に1度の行事などは素朴な予測に入らない。何年分も見ると過去分が延び、手法を作る期間の予言の回数が減る（periods.md 3章 (5) の表。4年では75回）。v0 ではこの限界を公開物に書く。
- 予定された行事のカレンダーを外から入れることはしない。人の判断が入るため。

### (4) 過去分の日数と periods.py との関係（T-011 の申し送り）

<!-- table:lookback -->
| 何に使うか | 読む日 | 日数 |
|---|---|---|
| 普段の水準 B(t) | t-371 から t-1 | 371 |
| 予言の時点の報道量 c(t) | t-13 から t-1 | 13 |
| 直近の山 P | t-34 から t-1 | 34 |
| 冷却（4章 (1)） | t-62 から t-1 | 62 |
| 去年の同じ時期（H = 14） | t-399 から t-316 | 399 |
| 去年の同じ時期（H = 28） | t-399 から t-302 | 399 |
| 去年の同じ時期（H = 56） | t-399 から t-274 | 399 |
| 素朴な予測の全体 | t-399 から t-1 | 399 |

- 去年の同じ時期の最も古い日は t+1-365-35 = t-399。7日のまとまりは広げた期間の中に完全に収める（最初のまとまりの終わりの日が t-393）ので、まとまりの分の6日はこの中に入っている。
- 399日は periods.py の LOOKBACK_DAYS（400日）以下で、区切りの作り直しは要らない（`naive.periods_trigger()`、テスト `test_lookback_within_periods`）。
- candidates.md 7章で「365 + 35 + 6 = 406日」と見積もったのは、去年の期間を t-365 から始め、まとまりが広げた期間の前にはみ出してよいとした場合の上限である。この設計では、去年の期間を判定期間と同じく t+1 からずらして取り、まとまりを期間の中に収めたので、399日になる。candidates.md と test_candidates.py は封印済みの版なので直さない。
- 手順：
  1. 最初の threshold-access の記録より前に、`naive_history_days = 399` をきっかけの値として封印の記録に追記する（periods.md 8章 (2)）。400 以下なので、区切りは変わらない（`periods.rebuild_periods(naive_history_days=399)` の区画と予言日の範囲は v1 と同じ。テスト `test_rebuild_with_trigger_is_v1`）。
  2. 改訂（(3)）で過去分が延びた場合は、`naive_lookback_days()` の新しい値をきっかけの値として、期限より前に追記する。400 を超えれば、periods.md 8章の手順で作り直す。区画の境目は変わらず、手法を作る期間の予言日の範囲の始まりが遅れる。期限を過ぎていれば、統計係は作り直さず、リードに報告する。

### (5) 予言の時点 t 以降のデータを読まないこと
- 特徴量は `raw_levels()` で、t-399 から t-1 の日だけを読む見張り（candidates._cached）を通して計算する。範囲の外の日を読もうとすると止まる。
- テスト `TestNaiveReadsOnlyPast` で、判定期間の候補の三つすべてについて、読んだ日がすべて t-399 から t-1 に入ること、t 以降の値を変えても特徴量が変わらないことを確かめる。
- これは日付の単位の確かめである。前向きの予言で、予言の時点にどのデータが入手できたか（ファイルの時刻と公開の遅れ）は、予言の手順を決めるタスクで扱う（T-011 の監査 M-1、T-001 の申し送り）。

## 4. 採点計画のうち、このタスクで決めるもの

### (1) 一度跳ねたタグの扱い
規則（`scoring.target_status()`）：
- 予言日 t に、終わりの日が t-56 から t-1 の、欠けた日を含まない7日の平均のどれかが **max(2 × B(t), V)** より大きいタグは、その週の対象にしない（状態 "cooldown"）。
- 判断に使うのは t-62 から t-1 のデータと、t の時点の B(t) と V だけ。判定期間が終わっていない予言の判定は使わない。
- この規則は、もともとの対象の条件（c(t) ≤ B(t)。candidates.md 3章 (6)）に加えて掛かる。

<!-- table:scoring-constants -->
| 定数 | 値 | 決め方 |
|---|---|---|
| JUMP_MULTIPLIER | 2 | 倍率の候補の最小 |
| COOLDOWN_DAYS | 56 | 判定期間の候補の最大 |

理由：
- CLAUDE.md の例「普段の水準以下に戻るまで対象外」は、もともとの対象の条件と同じで、何も足さない（candidates.md 3章 (7)）。一度大きく跳ねたタグは、跳ねたあと普段の水準以下に戻っても、同じ出来事の続きでもう一度跳ねやすい。それを「静かなタグが島になった」と数えると、一つの出来事を何週も続けて数えることになる。
- 倍率と期間を候補の端の値（最小の倍率2、最大の判定期間56日）にしたので、新しい数字を選んでいない。どちらも21組で共通なので、対象は組み合わせに依らず、candidates.select() の表の検査（同じ判定期間で対象の件数が同じ）を保つ。
- 倍率ごとの島の判定で「跳ねた」を決める形は採らない。対象の件数が倍率で変わり、表の検査で止まるため（candidates.md 3章 (7)）。
- 代償：跳ねた直後の余震のような島は、スティックチャートと素朴な予測のどちらの対象にも入らない。対象が減るので、成功率も下がる方向に動く。どちらも閾値を決める期間の割合の表を作る前に決まるので、表を見て選ぶことにはならない。
- スティックチャート、素朴な予測、閾値を決める期間の割合の表、基準値を測る期間、前向きの予言のすべてに同じ規則を使う。
- 冷却で外れたタグの件数は、週ごとに公開する。

### (2) 「対象なし」の週の数え方
週の種類（`scoring.week_summary()`）：

| 種類 | 意味 |
|---|---|
| has_targets | 対象が1件以上 |
| no_target_missing | 対象が0件で、すべてのタグが no_baseline か no_current（データの欠けによる） |
| no_target_quiet | 対象が0件で、それ以外（どのタグも普段の水準より上か、冷却中） |

- 対象が0件の週は、試行として数えない。確率を付けず、採点せず、閾値を決める期間の割合の表にも入れない。
- ただし記録は残す。前向きの予言では、予言の件数0件の週の記録として、ほかの週と同じく封印の鎖に入れる。週を飛ばした記録を作らないことで、都合の悪い週を黙って抜く余地を無くすため。
- 種類ごとの週の数を公開する。スティックチャート・素朴な予測・基準値で同じ週の記録を使う。
- 対象はあるが、対象の判定がすべて判定不能の週は、「判定不能の週」として別に数えて公開する。判定不能の予言は採点しない（candidates.md 3章 (5)）。
- 束ねた評価で、採点する予言が一つも無い時期のまとまりは、信頼区間の計算から除き、除いた数を公開する。

### (3) このタスクで決めないこと（次のタスクへの申し送り）
- **束ねた評価の単位と信頼区間、検出力の見積もり**：
  - 時期のまとまり：判定期間 H の予言は、続く H/7 − 1 週の予言と判定期間が重なる。重ならない連続した週のまとまり（H = 28 なら4週）を単位にする案がある。
  - 出来事のまとまり：同じ週に跳ねたタグを、予言の時点で分かる情報（共起の網など）でつないでまとめる案がある。判定のあとに人がまとめることはしない。
  - どちらも、閾値を決める期間の割合の表を見る前に決めて封印する。
- **長いあいだ0が続いたテーマの印**（CLAUDE.md「タグの一覧」）：印の付け方と採点での扱い。案として、予言日 t の直前365日の欠けた日でない日で報道量の合計が0のタグに印を付け、主の採点には含め、印の付いたタグを除いた採点も並べて公開する形がある。
- **採点の指標**（スティックチャートと素朴な予測の比べ方。確率の当てはまりの指標と「今週の島」の当たりの数え方）。

## 5. 封印の手順と順番（封印係への申し送り）

封印は封印係の仕組みで行う。記録の種類（kind）の名前と照合の仕組みは、封印係が決める。統計係からの提案は次のとおり。

| 順番 | 封印するもの | 時機 |
|---|---|---|
| 1 | この文書、3つのコードの出力（JSON）、3つのコード、`tests/stats/test_t019.py` | **テーマの区分表の取得（T-018 の acquisition-start）より前**、かつ method-access より前 |
| 2 | 区分表を見たあとの語の変更（あれば） | method-access より前。オーナーの承認のあと |
| 3 | タグの一覧の結果（`build_tag_list()` の出力。A = V、テーマごとの判定と理由を含む）と、入力のデータのハッシュ | 手法を作る期間のデータで作ったあと、モデルより前 |
| 4 | `naive_history_days = 399`（periods のきっかけの値） | 最初の threshold-access より前 |
| 5 | 素朴な予測の最後の版と、21組の係数 | 最初の threshold-access より前 |

- 1 を区分表の取得より前にする理由：区分表を見てから語を決めると、名前を見ながら一件ずつ外すのと区別がつかない。記録の順番（1 の記録が区分表の取得の記録より前にあること）で、第三者が確かめられる。
- 3 では、規則（1 と 2）と結果をまとめて一つの記録にする（CLAUDE.md「入れる規則・除外する規則・その結果の一覧を、まとめて封印する」）。結果を再計算できるように、入力（区分表と、手法を作る期間の日ごとの件数と全体の報道量）のハッシュも入れる。
- 検証の手順（docs/verify/）で、3 の結果が、封印した規則のコードと封印した入力から同じに再計算できることを確かめる手順を作ることを提案する。

## 6. 方針書との関係
- CLAUDE.md の5つの区分の外の区分（民族・宗教の集団）を足す点は、CLAUDE.md の決定事項の変更になる。オーナーの承認を得るまで、この行は提案である（0章の4）。
- 一度跳ねたタグの冷却は、CLAUDE.md の「予言の対象」に条件を一つ足すことになる。CLAUDE.md の「採点計画で必ず扱うこと」が、この扱いを採点計画で決めるとしているので、その範囲の提案とした。
- それ以外は、CLAUDE.md と docs/method.md の範囲で決めた。

## 7. 使った情報（データを見ていないことの宣言）
- 次の文書と発言だけを使った：CLAUDE.md、docs/method.md、docs/stats/periods.md、docs/stats/candidates.md、src/stats/periods.py、src/stats/candidates.py、reviews/T-001.md・T-011.md・T-016.md。
- 一般の知識として、次のものを使った。
  - 英語の語彙（2章の語）
  - GDELT のテーマの欄が分類の名前で、人物名は別の欄に入ること（T-001）
  - CrisisLex がテーマの体系の一つとして使われていること（2章 (3)）
  - 移動祝日などで行事の日付が年によって動くこと（3章 (1)）
  - 件数のばらつきの大きさ（ポアソン分布。1章 (2)）
- GDELT のデータ、ファイル一覧、テーマの区分表、GDELT のどのページにもアクセスしていない。ネットワークは使っていない。
- 3つのコードは、データのファイルを開かず、現在の日時を読まない（テスト `TestNoDataNoNetwork`）。

## 8. 引用
Data: The GDELT Project (https://www.gdeltproject.org/). This project is not affiliated with or endorsed by the GDELT Project.
データ出典：GDELT Project（https://www.gdeltproject.org/）。本プロジェクトは GDELT Project と提携・承認の関係にありません。
（この文書は GDELT のデータを使っていないが、規則は GDELT のデータに適用するため付ける。）
