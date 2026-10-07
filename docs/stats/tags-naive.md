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

タグの一覧（1章・2章）
1. **A の決め方**（1章 (2)）：A = 10 ÷ N_med。N_med は、手法を作る期間の区画のうち欠けた日でない日の、全体の報道量の中央値。「全体の報道量が普段どおりの日に、1日あたり平均10件」に当たる比率である。V は A と同じ値にする（T-011 で決定済み）。
2. **「全体にわたって存在する」の定義**（1章 (1)）：区画を暦の四半期（24個）に分け、どの四半期でも、欠けた日でない日の報道量の合計が1件以上あること。
3. **報道量の数え方を先に封印すること**（1章 (2)、5章）：r(d) の分子と分母の単位は、収集係が T-018 で決める。K（と A の式）は、その数え方が封印されるまで封印しない。数え方の封印は、この文書の規則の封印と同時か、それより前に行う。
4. **除外の照合のしかた**（2章 (1)）：名前と説明を語に区切り（英字と数字の境目でも区切る。ELECTION2016 は ELECTION と 2016）、語の一覧の語に次のどれかで当たれば外す。一件ずつの例外は持たない。
   - 完全一致と形の変化（複数形・活用形を規則で作る）：名前と説明の両方に使う。
   - くっつき一致：**名前の欄だけ** に使う。数値は次のとおり。
     - 先頭での一致：**6文字以上**（PREFIX_MIN_LEN = 6）の語が名前の語の先頭にあり、残りが **4文字以上**（GLUE_MIN_REST = 4）。例：POLICEOFFICER は POLICE に当たる。
     - 末尾での一致：どの長さの語でも、名前の語の末尾にあり、その前の残りが **4文字以上**。例：CIVILWAR は WAR、BIRDFLU は FLU、PLANECRASH は CRASH に当たる。ただし **4文字以下で ING・ED・ER・S で終わる語**（今は KING だけ）は末尾で当たらない（BREAKING、SPEAKING などを防ぐため）。
   - 既知の外しすぎ（2章 (1) の表）：LEADERSHIP_TRAINING、BRAINSTORM_SESSION、ANTIVIRUS_SOFTWARE、COMPATRIOT、CAMPFIRE、MARKETCRASH、TEAMLEADER、ROADKILL、DEFENSELESS、HEARTATTACK。既知の取りこぼし：GUNCONTROL、COUPATTEMPT、HIVAIDS、CARBOMB、MINISTERIAL、DEADLY。
5. **外しすぎの方向を選ぶ方針**（2章 (1)・(3)）：5つの区分のテーマが一覧に残るより、関係の無いテーマが外れる方を選ぶ。たとえば DEFENSE（法廷の弁護側も外れる）、DEATH と DEAD（訃報も外れる）、VACCINE（予防接種の制度も外れる）、FIRE（解雇の意味の FIRED も外れる）、ATTACK（HEARTATTACK の心臓発作も外れる）、LEADER（LEADERSHIP も外れる）、VIRUS（ANTIVIRUS も外れる）、STORM（BRAINSTORM も外れる）。
6. **語の一覧**（2章 (2)）。1cb463a の版からの変更は、出どころを付けて 2章 (7) の表にまとめた（CRISISLEX と ELECT を外し、ASSASSINATION、EXECUTION、STABBING、EXPLOSION、CRASH、ELECTED、MANSLAUGHTER、KILLING などを足した）。
7. **病名の扱い**（2章 (4)）：次の二つから選ぶ。
   - 案A（今の案）：一般の語（DISEASE、VIRUS、EPIDEMIC など）に加えて、病名（EBOLA、ZIKA、COVID など）の区分 `disease_named` も使う。
   - 案B：一般の語だけを使い、`disease_named` を使わない。
   - 病名は過去の流行の知識から選んだ（7章）。案Bなら、その知識は規則に入らない。代わりに、名前と説明に一般の語が無い病気のテーマが一覧に残る。
8. **民族・宗教の集団の区分を足すか**（2章 (5)）：CLAUDE.md の5つの区分の外にある。統計係の推奨は「足す」。足す場合は CLAUDE.md の決定事項の変更になる。
9. **組織名**（2章 (5)）：別の規則を作らない。5つの区分の語に当たる組織のテーマだけが外れる。
10. **区分表を見たあとの変更の範囲**（2章 (6)）：**テストで再現できる不具合の修正だけ** を認める（例外が出る、空の名前で落ちる、など）。語、数値（PREFIX_MIN_LEN、GLUE_MIN_REST など）、当たり方の種類は変えない。
    - 危うさ：区分表を見たあとで規則を変えると、名前を見ながら、どのテーマを外すかを実質的に選べる。たとえば GLUE_MIN_REST を4から3に変えるだけで、特定の名前の群れを外したり残したりできる。語を一つ足すのも同じである。数値と当たり方を変えないのは、この余地を無くすためである。
    - それでも変える場合は、新しい版として、オーナーの承認を得て、method-access より前に封印する。前の版と新しい版の両方で一覧を計算し、出入りしたテーマを並べて公開することを必須とする。
11. **記憶にある名前で照合を試したこと**（7章）：統計係（0e14f3b の版を作る途中）と監査係（1cb463a の版の監査）は、記憶にある GDELT のテーマ名の形の名前を照合に通して、当たり方を見た。監査係の例は差し戻しを通して、0e14f3b と今回の版の語と規則に入った。そのため、「区分表を見る前に決めた」という主張は、「区分表を取得する前に決めた。ただし作成者と監査係はテーマ名の一部を記憶しており、それを照合で試した」に弱まる。統計係が試した名前の一覧は 7章に残した。リードの決定（2026-10-07）により、これ以降は記憶にある名前を照合に通さない。この事実を承知したうえで、規則を承認するかを判断してほしい。

素朴な予測（3章）
12. **素朴な予測の形**（3章 (1)(2)）：特徴量6つと切片のロジスティック回帰を、21組それぞれで作る。
13. **推定の手順と行の並べ方の固定**（3章 (2)(3)）：推定の定数（RIDGE_LAMBDA、MAX_ITER、TOL）、推定の手順、学習データの選び方、行の並べ方（予言日、タグ名の順）は naive-v1 の値に固定する。改訂で変えてよいのは、特徴量を足すことだけ。
14. **素朴な予測の過去分**（3章 (4)）：7日のまとまりの分を含めて399日。periods.py の LOOKBACK_DAYS（400日）に収まり、区切りの作り直しは要らない。399 をきっかけの値として、封印の記録に追記する。

採点計画（4章）
15. **一度跳ねたタグ**（4章 (1)）：直近56日のうちに、7日の平均が max(2 × B(t), V) を超えたタグは、その週の対象にしない。
16. **「対象なし」の週**（4章 (2)）：試行として数えない。記録は残し、件数と種類を公開する。
17. **冷却と「対象なし」の規則の改訂の可否**（4章 (3)）：手法を作る期間の作業中に限り、新しい版として、オーナーの承認を得て、最初の threshold-access より前に封印すれば改訂してよい。threshold-access のあとは変えない。

封印（5章）
18. **封印の順番**（5章）：この文書の規則は、テーマの区分表の取得（T-018）より前に封印する。最終の版と 1cb463a の版の両方を封印し、区分表の取得のあとで両方の一覧を計算して、出入りしたテーマを公開する。手法を作る期間の区画の欠けた日の一覧は、タグの一覧の結果より前に封印する。

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
- 四半期の端の扱いと限界：
  - 最初の四半期（2015-03-02 から 2015-03-31、30日）と最後の四半期（2020-10-01 から 2020-12-14、75日）は、ほかの四半期（90日前後）より短い。短い四半期では、件数の少ないテーマが偶然0件になりやすく、存在の条件で外れやすい。
  - 区画の最初の四半期の途中で生まれたテーマ（たとえば 2015-03-20 に体系に加わったもの）も、その四半期に1件あれば条件を満たす。区画の最後の四半期の途中で消えたテーマも同じ。生まれた日と消えた日は、四半期より細かくは見ない。
  - 欠けた日の多い四半期では、使える日が少ないので、同じく0件になりやすい。使える日が一日も無い四半期だけは条件から外すが、少ないだけの四半期は外さない。外す基準を件数で決めると、データを見て決める数がもう一つ増えるため。

### (2) A の決め方
- テーマの平均報道量は、区画の欠けた日でない日の比率 r(d) の単純平均とする（日ごとに同じ重み）。r(d) の分子と分母の数え方は、収集係が決める報道量の数え方に従う。
- **A = K ÷ N_med、K = 10**。N_med は、欠けた日でない日の全体の報道量（r(d) の分母）の中央値。日数が偶数なら真ん中の二つの平均。
- 平均が A 以上なら入れる。平均は浮動小数点で計算し（math.fsum）、A（分数）との比較は、その値を分数に直して行う。比較のところで丸めは入れない（`build_tag_list()`）。
- V = A（docs/stats/candidates.md 3章 (4)）。島の判定には「7日の平均 > V」が要るので、全体の報道量が普段どおりの週なら、島になるには7日で70件を超える報道が要る。
- 分位で決める案（例：全テーマの平均の上位何%）を採らなかった理由：分位はテーマの体系にどれだけ細かいテーマが多いかで動き、件数の少なさから来るばらつきとは関係がない。V の役目は、少ない件数のばらつきで島にならないようにすることである。そのため、件数で決める形にした。
- K = 10 にした理由：7日で70件なら、件数の偶然のばらつき（ポアソン分布なら標準偏差は約8.4件）に比べて十分大きい。1日に1本の記事も無いテーマを「ニュースになった」と呼ばないための下限でもある。この値はデータを見ずに決めた。
- **V は比率で固定される**ことの限界：A と V は手法を作る期間の N_med で決まる比率で、三つの期間と前向きの予言で同じ値を使う。全体の報道量（r(d) の分母）が期間によって増減すると、同じ V が別の件数に当たる。たとえば全体の報道量が手法を作る期間の倍になれば、V は1日あたり約20件に当たり、半分になれば約5件に当たる。V を件数で固定せず比率で固定したのは、CLAUDE.md が報道量を比率で扱うと決めているためである。各期間の全体の報道量の中央値は公開し、V が何件に当たるかを読めるようにする。
- **数え方への依存**：r(d) の分子と分母の単位（記事の数え方、重複のまとめ方、どのテーマの欄を数えるか）は、収集係が T-018 で決める。K = 10 の意味（1日あたり10件）はその単位に依る。そのため、**数え方が封印されるまで、K は封印しない**。数え方の封印は、この文書の規則の封印と同時か、それより前に行う（5章）。
- 結果の一覧の件数が多すぎても少なすぎても、K を変えない。変える場合は、手法を作る期間のデータを見たあとの変更として、新しい版で封印し、オーナーの承認を得て、前の版の結果と並べて公開する。

### (3) 一覧を作る手順（`build_tag_list()`）
- 対象のテーマは、区分表に載っているテーマと、手法を作る期間のデータに現れたテーマを合わせたもの。
- 入力は、手法を作る期間の区画のデータだけ。引数に区画の外の日付が一つでもあれば止まる（テスト `test_rejects_dates_outside_block`）。閾値を決める期間より後のデータを、渡す余地を無くすため。
- 欠けた日の一覧は、封印したもの（candidates.md 3章 (5)）を使う。欠けた日の報道量は、存在の条件にも平均にも入れない。
- 出力には、テーマごとに四半期ごとの件数、平均、A 以上か、一致した除外の語（区分・語・名前と説明のどちらの欄か・当たり方）、一覧に入ったかを載せる。一覧に入らなかったテーマとその理由も、すべて公開する。

## 2. 除外の規則の作り方（未決事項5）

### (1) 照合のしかた
- 使うのは区分表の **名前** と **説明** の二つの欄だけ。ほかの欄があっても使わない。説明が無ければ名前だけで照合する。
- **語に区切る**（`tokens()`）：大文字にし、英字の続きと数字の続きを一つずつの語とする。英字と数字以外（下線、空白、記号）は区切りとして捨てる。英字と数字の境目でも区切る。たとえば ELECTION2016 は ELECTION と 2016、COVID19 は COVID と 19 になる。
- **当たり方**（`_word_matches()`）
  1. 完全一致：語が、一覧の語と同じ。
  2. 形の変化：語が、一覧の語の形の変化（`inflections()`）と同じ。形の変化は次の規則で機械的に作る。
     - 常に +S
     - S, X, Z, CH, SH, O で終わる語に +ES
     - 子音 + Y で終わる語は、Y を IES、IED に替えた形
     - E で終わる語は +D、+R、+RS と、E を除いて +ING
     - それ以外の語は +ED、+ING、+ER、+ERS
     - 子音を重ねる形（KIDNAP から KIDNAPPING）は作らない。要るものは語の一覧に書いた。
  3. くっつき一致（**名前の欄だけ**。一覧の語と名前の語が英字だけのとき）
     - 先頭：一覧の語が **6文字以上** で、名前の語がその語で始まり、残りが **4文字以上**。
     - 末尾：名前の語が一覧の語（またはその形の変化）で終わり、その前の残りが **4文字以上**。一覧の語の長さは問わない。ただし、4文字以下で ING・ED・ER・S で終わる一覧の語（今は KING）には使わない。
- 語の並び（例：PRIME MINISTER）は、続けて現れたときに一致とする（最後の語だけ形の変化を認める）。加えて、名前の欄では、並びをつなげた一語（PRIMEMINISTER、AIRFORCE）を上の規則で照合する。
- **数値と条件の理由**（データを見ずに、英語の語の作りだけから決めた）
  - 先頭を6文字以上にした：5文字以下の語は、関係の無い長い語の頭に現れやすい（ELECT が ELECTRIC に、STORM が STORMWATER に、QUEEN が QUEENSLAND に当たる）。前回の ELECT はこの誤りの元だったので外し、ELECTED と ELECTING を語として書いた。
  - 残りを4文字以上にした：残りが3文字以下だと、英語の接頭辞や語尾の一部（PAT+RIOT、G+RAPE、BE+GUN、PRINCE+TON など）で偶然当たる。4文字以上なら、残りが一つの語であることが多い（CIVIL+WAR、BIRD+FLU、PLANE+CRASH）。
  - 末尾は短い語にも許した：取りこぼしの多くは「修飾語 + 短い語」の形（CIVILWAR、COLDWAR、SWINEFLU、SHOTGUN）だったため。SOFTWARE は末尾が WARE で、WAR では終わらないので当たらない。
  - KING を末尾から外す条件：KING は英語の語尾 ING を含み、BREAKING、SPEAKING、THINKING のように、残りが4文字以上の語の末尾に多く現れる。特定の語を名指しせず、「4文字以下で語尾の形をした語」という形の条件にした。
  - 説明の欄ではくっつき一致を使わない：説明は空白で区切られた文なので、語がくっつくことは少ない。くっつき一致を使うと、ELECTRICITY、LEADERSHIP、BRAINSTORM のような普通の語で外しすぎが増える。SOLAR_ENERGY の説明に electricity や leadership があっても、外れない（テスト `test_glue_not_in_description`）。説明の欄でも、語の完全一致と形の変化（storms など）には当たる。
  - 監査の提案（先頭は6文字以上、末尾は短い語にも許す）を採り、残りの文字数と KING の条件、説明の欄の扱いを足した。監査の提案では、COUPATTEMPT、GUNCONTROL、HIVAIDS も当たる案だったが、これらは短い語（COUP、GUN、HIV）が **先頭** にある形で、先頭の一致を短い語に許すと COUPON、HIVE のような誤りが出る。そのため取りこぼしとして残した。
- **既知の例**：監査係が作った名前と統計係が作った名前で、結果を次のとおり固定した（テスト `test_known_examples`）。どれもテストのために作った名前である。

<!-- table:known-examples -->
| 結果 | 名前 |
|---|---|
| 残す（正しく残す） | ELECTRIC_POWER, ELECTRONICS, QUEENSLAND_TOURISM, SOFTWARE, AWARD, WARNING, WARM, STEWARD, FIREWORKS, KINGDOM, BOOKING, BREAKING_NEWS, SPEAKING, THINKING, PARKING, GRAPE, DRAPE, PATRIOT, BEGUN, SKILLS, RECOUP, COUPON, POLLEN, SCAMPI, GANGES, PRINCETON, STORMWATER, PROTESTANT, CABINETRY, AIDGROUPS, STOCKMARKET, FLUENT, DEADLINE, GUNPOWDER, EXECUTIVE |
| 残る（取りこぼし） | GUNCONTROL, COUPATTEMPT, HIVAIDS, CARBOMB, MINISTERIAL, DEADLY |
| 外れる（外しすぎ） | LEADERSHIP_TRAINING, BRAINSTORM_SESSION, ANTIVIRUS_SOFTWARE, COMPATRIOT, CAMPFIRE, MARKETCRASH, TEAMLEADER, ROADKILL, DEFENSELESS, HEART_ATTACK, AB_DEFENSE_ATTORNEY, OBITUARY_DEATH, AB_VACCINE_POLICY, AB_FIRED, HEARTATTACK, SNOWSTORM |
| 外れる（正しく外す） | CIVILWAR, COLDWAR, BIRDFLU, SWINEFLU, PLANECRASH, CYBERATTACK, PARAMILITARY, MANSLAUGHTER, TIMEBOMB, SHOTGUN, HANDGUN, POLICEOFFICER, ELECTION2016, PRIMEMINISTER, AIRFORCE, DRUGABUSE, IDENTITYTHEFT |

- どの区分の語に当たっても同じく外す。区分の名前は、報告のためだけに使う。出力には、当たった語・欄・当たり方を、テーマごとにすべて載せる。
- 名前と説明のどちらかで当たれば外す。説明に語が付随して出てくるだけのテーマも外れる。**外しすぎの方向の誤りを選んだ。** 5つの区分のテーマが一覧に残る誤りの方が、プロジェクトの目的に反するため。この方針で外れる例は 0章の5。

### (2) 語の一覧

<!-- table:terms -->
| 区分 | CLAUDE.md の区分 | 語 |
|---|---|---|
| politics_election | 政治・選挙 | ELECTION, ELECTORAL, ELECTED, ELECTING, VOTE, BALLOT, REFERENDUM, POLL, CANDIDATE, INAUGURATION, POLITICS, POLITICAL, POLITICIAN, PARLIAMENT, PARLIAMENTARY, LEGISLATURE, LEGISLATIVE, LEGISLATOR, CONGRESS, SENATE, SENATOR, LAWMAKER, PRESIDENT, PRESIDENTIAL, PRIME MINISTER, MINISTER, CHANCELLOR, GOVERNOR, MAYOR, LEADER, HEAD OF STATE, CABINET, COUP, IMPEACH, IMPEACHMENT, REGIME, DICTATOR, DICTATORSHIP, PROTEST, DEMONSTRATOR, SANCTION, DIPLOMACY, DIPLOMATIC, DIPLOMAT, EMBASSY, AMBASSADOR, PROPAGANDA, LOBBYING, LOBBYIST |
| conflict_violence | 紛争・暴力 | WAR, WARFARE, MILITARY, ARMY, ARMED, NAVY, NAVAL, AIR FORCE, SOLDIER, TROOP, MILITIA, INSURGENCY, INSURGENT, INSURRECTION, REBEL, REBELLION, GUERRILLA, SEPARATIST, TERROR, TERRORISM, TERRORIST, EXTREMISM, EXTREMIST, JIHAD, JIHADIST, CONFLICT, VIOLENCE, VIOLENT, ATTACK, BOMB, BOMBING, EXPLOSIVE, EXPLOSION, WEAPON, GUN, GUNMAN, GUNMEN, GUNFIRE, FIREARM, SHOOTING, SHOOTER, SNIPER, MISSILE, ARTILLERY, AIRSTRIKE, KILL, KILLING, MASSACRE, GENOCIDE, SLAUGHTER, MANSLAUGHTER, ASSASSIN, ASSASSINATE, ASSASSINATION, EXECUTION, BEHEADING, STABBING, LYNCHING, CEASEFIRE, PEACEKEEPING, PEACEKEEPER, INVASION, HOSTAGE, TORTURE, RIOT, UNREST, CRACKDOWN, PERSECUTION, SIEGE, BLOCKADE, DEFENSE, DEFENCE, CONSCRIPTION, REFUGEE, DISPLACED, ETHNIC CLEANSING |
| crime | 犯罪 | CRIME, CRIMINAL, MURDER, HOMICIDE, ASSAULT, ROBBERY, THEFT, THIEF, THIEVES, BURGLARY, FRAUD, EMBEZZLEMENT, CORRUPTION, BRIBERY, BRIBE, SMUGGLING, SMUGGLER, TRAFFICKING, TRAFFICKER, NARCOTICS, CARTEL, GANG, MAFIA, LAUNDERING, EXTORTION, KIDNAP, KIDNAPPING, KIDNAPPED, KIDNAPPER, ABDUCTION, RAPE, HARASSMENT, ABUSE, ARREST, DETAIN, DETAINEE, DETENTION, POLICE, PRISON, JAIL, INCARCERATION, PROSECUTION, PROSECUTOR, INDICTMENT, FELONY, PIRACY, SCAM, VANDALISM, ARSON, POACHING, COUNTERFEIT, ESPIONAGE, TREASON, VICTIM |
| specific_person | 特定の人物 | POPE, KING, QUEEN, PRINCE, PRINCESS, MONARCH, MONARCHY, ROYAL, EMPEROR, EMPRESS, CELEBRITY |
| disaster | 災害・感染症 | DISASTER, EARTHQUAKE, TSUNAMI, FLOOD, HURRICANE, TYPHOON, CYCLONE, TORNADO, WILDFIRE, FIRE, DROUGHT, LANDSLIDE, MUDSLIDE, SINKHOLE, VOLCANO, VOLCANIC, ERUPTION, AVALANCHE, HEATWAVE, HEAT WAVE, STORM, BLIZZARD, FAMINE, CRASH, DERAILMENT, SHIPWRECK, ACCIDENT, EVACUATION, CASUALTY, FATALITY, INJURED, DEATH, DEAD |
| disease_general | 災害・感染症 | EPIDEMIC, PANDEMIC, OUTBREAK, DISEASE, INFECTION, INFECTIOUS, CONTAGION, CONTAGIOUS, VIRUS, PATHOGEN, VACCINE, VACCINATION, QUARANTINE |
| disease_named | 災害・感染症 | INFLUENZA, FLU, EBOLA, ZIKA, CHOLERA, MALARIA, MEASLES, HIV, TUBERCULOSIS, POLIO, CORONAVIRUS, COVID, SARS, SARSCOV, MERS, PLAGUE, DENGUE, ANTHRAX, SMALLPOX, HEPATITIS, MENINGITIS, RABIES, H1N1, H5N1 |
| ethnic_religious_group | （5つの区分の外） | ETHNIC, ETHNICITY, TRIBE, TRIBAL, RELIGION, RELIGIOUS, SECTARIAN |

### (3) 語の選び方と、区分ごとの境目
語は、区分の意味から英語の語を挙げて選んだ。区分表は見ていない。ただし、語を選ぶのに使った知識は一般の英語だけではない（7章）。
- 政治・選挙：選挙と投票、候補と世論調査、議会、国や地方の首長と閣僚、政変、抗議行動、外交と制裁。GOVERNMENT と GOVERNANCE は入れていない。行政一般のテーマ（予算、公共事業など）まで外れるため。移民などの政策の論点も入れていない。
- 紛争・暴力：戦争と軍、武装集団、テロ、攻撃と武器、殺害と暗殺・処刑、暴動、難民。SECURITY は入れていない（食料安全保障、サイバーセキュリティなども外れるため）。DEFENSE は入れた。
- 犯罪：犯罪の種類、汚職、組織犯罪、逮捕・拘束・警察・刑務所・訴追、被害者。
- 特定の人物：GDELT のテーマの欄は分類の名前で、人物名は別の欄（人物の欄）に入る（T-001）。この欄は、収集係の項目の一覧に入れず、取得もしない。テーマの名前で一人の人物を指しやすいのは、君主・教皇などの地位と、有名人の分類なので、それらの語を入れた。大統領・首相などは政治・選挙の区分で外れる。
- 災害（disaster）：自然災害、火災、飢饉、事故（墜落・脱線・難破）、避難、死傷。
- 感染症（disease_general と disease_named）：一般の語は disease_general、病名は disease_named に分けた（(4)）。
- 1cb463a の版の CRISISLEX は外した。一般の英語の語ではなく、GDELT のテーマの体系の名前を知っていたことから入れた語だったため。

**区分表を見ずに決めたことの限界**：
- 名前の語の中で、一覧の語が真ん中にある場合や、短い語が先頭にある場合（COUPATTEMPT、GUNCONTROL）は当たらない。説明の欄で当たらなければ、一覧に残る。
- 説明の欄が無い区分表なら、名前だけで照合することになり、取りこぼしが増える。
- 名前が略語だけでできているテーマには当たらない。

### (4) 病名（案A と案B）
- 病名（`disease_named` の行）は、一般の英語の語ではなく、過去の流行の知識から選んだ（7章）。CLAUDE.md の「データ源の区分を使って機械的に判定する」に照らすと、知識から名前を選ぶことは、テーマを名指しする判断に近づく。
- そのため、次の二つを並べてオーナーに選んでもらう。
  - 案A（今のコードの既定）：`disease_general` と `disease_named` の両方を使う。名前と説明に一般の語が無い病気のテーマも外れる。
  - 案B：`disease_general` だけを使う。知識から選んだ病名は規則に入らない。代わりに、名前が病名だけで説明にも一般の語が無いテーマは一覧に残る。
- どちらを選ぶかは、封印の前に `ENABLED_OPTIONAL_CATEGORIES` に反映する。区分表を見る前なので、どちらを選んでも選び出しにはならない。

### (5) 組織名と民族集団のテーマ（T-001 の申し送り）
T-001 の報告では、テーマの欄に組織名と民族集団が入ることがある（codebook）。

**民族・宗教の集団：外す区分を足すことを推奨する（オーナーの承認が要る）**
- CLAUDE.md の5つの区分は「特定の人物」で、集団は入らない。そのため、この区分を足すことは CLAUDE.md の決定事項の変更になる。
- 推奨の理由：
  - 特定の民族・宗教の集団が来週ニュースになる、という予言を公開すること自体に、迫害や衝突を予告する読まれ方をする危うさがある。
  - そうしたテーマの報道が跳ねるのは、多くが紛争・暴力や犯罪の報道と重なると考えられる。しかし、その重なりは区分表の名前と説明の語では捕まえられない。
- 語は `ethnic_religious_group` の行（ETHNIC、RELIGIOUS など）。言語の分類（言語の名前）は入れていない。言語の名前は、場所や報道の言語として付くことが多いと考えたため。
- オーナーが足さないと決めた場合は、`ENABLED_OPTIONAL_CATEGORIES` からこの区分を除いた版を封印する。

**組織名：別の規則を作らない**
- 組織そのものは、CLAUDE.md の5つの区分に入らない。武装集団や政党などの組織のテーマは、TERROR、POLITICAL などの語で外れる。
- 名前と説明だけから「組織の名前であること」を機械的に見分ける規則は、区分表を見ずには作れない。区分表を見てから作れば、一件ずつの判断に近くなる。

### (6) 区分表を見たあとで変えたくなった場合
- 統計係は、自分で変えない。変えたい点と理由をリードに報告する。
- **認める変更は、テストで再現できる不具合の修正だけ** とする。不具合とは、例外が出る、空の名前や説明で落ちる、文字の扱いで止まる、のように、決めた規則のとおりに動かないことを指す。
- 次のものは変えない。
  - 語（足すことも、消すことも、不規則な形を足すこともしない）
  - 数値（PREFIX_MIN_LEN、GLUE_MIN_REST、SUFFIX_BLOCK_MAX_LEN、SUFFIX_BLOCK_ENDINGS）
  - 当たり方の種類（新しい種類の当たり方を足さない。くっつき一致を使う欄も変えない）
- 理由：区分表を見たあとで語・数値・当たり方を変えると、名前を見ながら、どのテーマを外すかを実質的に選べる。区分表には件数が無くても、名前を見て選ぶことは CLAUDE.md の「一件ずつ人の判断で入れたり外したりしない」に反する。
- 不具合の修正をする場合も、次のすべてを満たす。
  - 不具合を再現するテストを、作った名前で書く。区分表の名前をテストに書かない。
  - オーナーの承認を得て、新しい版として、method-access より前に封印する。前の版は消さない。
  - **前の版と新しい版の両方で一覧を計算し、出入りしたテーマを並べて公開する**（`compare_lists()`）。
- method-access のあと（手法を作る期間の報道量を見たあと）は、v0 の一覧の除外の規則を変えない。変える必要が出た場合は、CLAUDE.md のとおり別の版として封印し直し、版ごとに別々に採点する。
- 版の番号は、追記のみの記録で、この規則の封印が何件目かで決まる。

### (7) 版ごとの差分と出どころ
1cb463a（初回の提出）、0e14f3b（再提出1回目）、今回の版の差分。出どころは「区分の意味」（区分の意味から統計係が挙げた）、「監査の例」（差し戻しで示された例。監査係は記憶にある名前で照合を試していた）、「記憶の名前による照合」（統計係が記憶にある名前を照合に通した結果から変えたもの）のどれか。「記憶の名前による照合」に当たる変更は無い。統計係が記憶にある名前で試したのは 0e14f3b の語と規則を決めたあとで、その結果を見て語や規則を変えてはいない（7章）。

1cb463a から 0e14f3b

| 種類 | 中身 | 出どころ |
|---|---|---|
| 変えた規則 | 英字と数字の境目でも区切る | 監査の例（ELECTION2016） |
| 変えた規則 | 形の変化を規則で作る（inflections）。一覧の複数形・活用形（WARS、KILLED、VOTERS など103語）を消し、規則に置き換えた。消した形はすべて規則で作られる | 区分の意味（一覧を基本形にそろえるため） |
| 変えた規則 | くっつき一致（5文字以上の語が名前の語の先頭か末尾） | 監査の例（PLANE_CRASH、CYBERATTACK） |
| 消した語 | CRISISLEX | 監査の例（テーマの体系の名前で、一般の語でない） |
| 消した語 | CYBERCRIME（くっつき一致で CRIME に当たるため） | 区分の意味 |
| 消した語 | KILLINGS（一覧の基本形に置き換えた。0e14f3b では当たらなくなっていた。今回 KILLING を足して直した） | 区分の意味 |
| 足した語 | ASSASSINATION、EXECUTION、STABBING、EXPLOSION、CRASH | 監査の例 |
| 足した語 | ASSASSIN、ASSASSINATE、ELECT、CANDIDATE、POLL、INAUGURATION、LEGISLATOR、CHANCELLOR、LOBBYIST、NAVAL、GUERRILLA、SEPARATIST、INSURRECTION、GUNMAN、GUNMEN、GUNFIRE、SHOOTER、SNIPER、ARTILLERY、SLAUGHTER、BEHEADING、LYNCHING、CONSCRIPTION、THIEF、THIEVES、EMBEZZLEMENT、SMUGGLER、TRAFFICKER、KIDNAPPED、KIDNAPPER、ABDUCTION、DETAIN、DETAINEE、DETENTION、FELONY、POACHING、COUNTERFEIT、ESPIONAGE、TREASON、VICTIM、MUDSLIDE、SINKHOLE、DERAILMENT、SHIPWRECK、ACCIDENT、EVACUATION、INJURED、CONTAGION、CONTAGIOUS、PATHOGEN | 区分の意味 |
| 足した語 | ANTHRAX、SMALLPOX、HEPATITIS、MENINGITIS、RABIES、SARSCOV、H1N1、H5N1 | 区分の意味（病名は過去の流行の知識。7章） |
| 変えた規則 | 病名の区分（disease_named）と民族・宗教の区分を、オーナーが選ぶ区分にした | 監査の例（病名の知識の指摘） |

0e14f3b から今回の版

| 種類 | 中身 | 出どころ |
|---|---|---|
| 消した語 | ELECT（ELECTRIC、ELECTRONICS に当たっていた） | 監査の例 |
| 足した語 | ELECTED、ELECTING | 監査の例 |
| 足した語 | MANSLAUGHTER（残りの条件で SLAUGHTER の末尾一致から外れたため） | 区分の意味 |
| 足した語 | KILLING（1cb463a の KILLINGS を取り戻すため。版の差分を作るときに見つけた） | 区分の意味 |
| 変えた規則 | 先頭の一致は6文字以上の語だけ | 監査の例 |
| 変えた規則 | 末尾の一致はどの長さの語にも許す | 監査の例（CIVILWAR、BIRDFLU など） |
| 変えた規則 | くっつき一致の残りは4文字以上 | 区分の意味（作った名前 PATRIOT、GRAPE、PRINCETON などで確かめた） |
| 変えた規則 | 4文字以下で ING・ED・ER・S で終わる語は末尾で当たらない | 区分の意味（作った名前 BREAKING、SPEAKING などで確かめた） |
| 変えた規則 | くっつき一致は名前の欄だけ | 監査の例（SOLAR_ENERGY の説明） |

- 1cb463a の版の語（CRISISLEX を除く）が、今回の版でもすべて外れることを、テスト `test_v1_terms_still_excluded` で確かめている。

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
- 学習データの選び方（固定）：手法を作る期間の予言日の範囲にある、予言の曜日のすべての予言日。封印したタグの一覧のすべてのタグのうち、状態が "target" のもの。正解は、封印した V で計算した candidates.judge の値。判定不能の行だけを除き、ほかには何も除かない。
- 行の並べ方（固定）：推定の前に、行を（予言日、タグ名）の昇順に並べ直す（`sort_rows()`、`fit_rows()`）。前提として、タグ名はタグの一覧の中で一意である（一覧はテーマ名の集合から作るので重複しない）。そのため（予言日、タグ名）で行の順が一つに決まる。同じ予言日とタグの行が二つあれば止まる。浮動小数点の足し算は順番で結果がわずかに変わるので、第三者が計算し直したときに同じ係数になるよう、並べ方を規則で決めた。入力の順を変えても係数が同じになることを、テスト `test_row_order_fixed` で確かめる。
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
- 手法を作る期間は自由に探索してよい期間なので、素朴な予測の特徴量を見直すことはありうる。ただし、改訂で変えてよいのは **特徴量を足すことだけ** とし、除いたり定義を変えたりしない。足した特徴量は、スティックチャートのモデルの入力にも足す。
- 次のものは naive-v1 の値に固定し、改訂でも変えない：推定の定数（RIDGE_LAMBDA = 1.0、MAX_ITER = 100、TOL = 1e-10）、推定の手順（係数0から始めるニュートン法と一歩を半分にする規則）、学習データの選び方、行の並べ方。
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
- 冷却が効くのは、跳ねたことが分かった **あと** の週だけである。跳ねる **前** の週の予言は、判定期間が重なるので、そろって島になる。たとえば判定期間28日なら、出来事の前の最大4週の予言が、一つの出来事で同時に島になる。この重なりは冷却では除けないので、束ねた評価で扱う（(4) の申し送り）。

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

### (3) 冷却と「対象なし」の規則の改訂
- 手法を作る期間の作業中に限り、改訂してよい。改訂は新しい版として、オーナーの承認を得て、**最初の threshold-access の記録より前に** 封印する。前の版も並べて公開する。
- 改訂した規則は、スティックチャート・素朴な予測・閾値を決める期間の割合の表・基準値・前向きの予言のすべてに同じく使う。
- threshold-access のあとは変えない。閾値を決める期間の割合は、対象の規則に依るため。
- 素朴な予測とスティックチャートのモデルは、対象の規則に依る。規則を改訂したら、両方のモデルを改訂した規則で作り直し、そのうえで封印する。

### (4) このタスクで決めないこと（次のタスクへの申し送り）
- **束ねた評価の単位と信頼区間、検出力の見積もり**：
  - 時期のまとまり：判定期間 H の予言は、続く H/7 − 1 週の予言と判定期間が重なる。重ならない連続した週のまとまり（H = 28 なら4週）を単位にする案がある。
  - 出来事のまとまり：同じ週に跳ねたタグを、予言の時点で分かる情報（共起の網など）でつないでまとめる案がある。判定のあとに人がまとめることはしない。
  - 跳ねる前の週の予言がそろって島になる重なり（(1) の最後）を、時期のまとまりで扱う。冷却はこの重なりを除かない。
  - どちらも、閾値を決める期間の割合の表を見る前に決めて封印する。
- **長いあいだ0が続いたテーマの印**（CLAUDE.md「タグの一覧」）：印の付け方と採点での扱い。案として、予言日 t の直前365日の欠けた日でない日で報道量の合計が0のタグに印を付け、主の採点には含め、印の付いたタグを除いた採点も並べて公開する形がある。
- **採点の指標**（スティックチャートと素朴な予測の比べ方。確率の当てはまりの指標と「今週の島」の当たりの数え方）。

## 5. 封印の手順と順番（封印係への申し送り）

封印は封印係の仕組みで行う。記録の種類（kind）の名前と照合の仕組みは、封印係が決める。統計係からの提案は次のとおり。

| 順番 | 封印するもの | 時機 |
|---|---|---|
| 0 | 報道量の数え方（r(d) の分子と分母の単位。収集係が T-018 で決める） | 1 と同時か、1 より前 |
| 1 | この文書、3つのコードの出力（JSON）、3つのコード、`tests/stats/test_t019.py` | 0 の封印のあと（同時でもよい）。**テーマの区分表の取得（T-018 の acquisition-start）より前**、かつ method-access より前 |
| 2 | 区分表を見たあとの変更（2章 (6) の二つだけ。あれば） | method-access より前。オーナーの承認のあと |
| 3 | 手法を作る期間の区画の欠けた日の一覧（candidates.md 3章 (5)） | 4 より前 |
| 4 | タグの一覧の結果（`build_tag_list()` の出力。A = V、テーマごとの判定と理由を含む）と、入力のデータのハッシュ | 手法を作る期間のデータで作ったあと、モデルより前 |
| 5 | 冷却と「対象なし」の規則の改訂（4章 (3)。あれば） | 最初の threshold-access より前 |
| 6 | `naive_history_days = 399`（periods のきっかけの値） | 最初の threshold-access より前 |
| 7 | 素朴な予測の最後の版と、21組の係数 | 最初の threshold-access より前 |

- 0 を 1 より前にする理由：K = 10 の意味（1日あたり10件）は数え方に依る。数え方が決まる前に K を封印すると、あとで数え方を選ぶことで A を動かせる。統計係の側では、**数え方が封印されるまで K を封印しない**。
- 1 を区分表の取得より前にする理由：区分表を見てから語を決めると、名前を見ながら一件ずつ外すのと区別がつかない。記録の順番（1 の記録が区分表の取得の記録より前にあること）で、第三者が確かめられる。0 の封印が遅れる場合は、1 を待ち、区分表の取得も 1 のあとまで待つ。
- 3 を 4 より前にする理由：タグの一覧の結果（存在の条件と平均）は、欠けた日の一覧に依る。一覧の結果を見てから欠けた日を決め直す余地を無くすため。
- 4 では、規則（1 と 2）と結果をまとめて一つの記録にする（CLAUDE.md「入れる規則・除外する規則・その結果の一覧を、まとめて封印する」）。結果を再計算できるように、入力（区分表と、手法を作る期間の日ごとの件数と全体の報道量）のハッシュも入れる。
- **二つの版の封印**：順番1では、最終の版に加えて、1cb463a の版（`git show 1cb463a:src/stats/tagrules.py` とその出力）も封印する。統計係と監査係が記憶にある名前で照合を試したあとに語と規則が変わったので、変わる前の版の結果も並べて示せるようにするため。
- **二つの版の一覧の比べ方**（順番4のとき）：
  1. 区分表と手法を作る期間のデータを取得したあと、同じ入力で、最終の版の `build_tag_list()` と、1cb463a の版の `build_tag_list()` を両方実行する。1cb463a の版は、git の履歴からそのファイルを取り出して実行する（区分は1cb463a の版の定義のまま）。
  2. `compare_lists()` で、片方の版だけで一覧に入ったテーマを出す。
  3. 二つの版の出力と、出入りしたテーマの一覧を、順番4の記録に入れて封印し、公開する。0e14f3b の版も、同じ手順で計算して公開する（封印の対象にはしない。git の履歴で時刻が分かる）。
  4. 採点に使うのは最終の版の一覧だけ。比べた結果を見て、版を選び直すことはしない。
- 検証の手順（docs/verify/）で、4 の結果が、封印した規則のコードと封印した入力から同じに再計算できることを確かめる手順を作ることを提案する。

## 6. 方針書との関係
- CLAUDE.md の5つの区分の外の区分（民族・宗教の集団）を足す点は、CLAUDE.md の決定事項の変更になる。オーナーの承認を得るまで、この行は提案である（0章の8）。
- 病名の区分（disease_named）は、CLAUDE.md の「災害・感染症」の範囲だが、語を知識から選んだ点でオーナーの選択に委ねる（0章の7）。
- 一度跳ねたタグの冷却は、CLAUDE.md の「予言の対象」に条件を一つ足すことになる。CLAUDE.md の「採点計画で必ず扱うこと」が、この扱いを採点計画で決めるとしているので、その範囲の提案とした。
- それ以外は、CLAUDE.md と docs/method.md の範囲で決めた。

## 7. 使った情報（データを見ていないことの宣言）
- 次の文書と発言だけを使った：CLAUDE.md、docs/method.md、docs/stats/periods.md、docs/stats/candidates.md、src/stats/periods.py、src/stats/candidates.py、reviews/T-001.md・T-011.md・T-016.md・T-019.md。
- GDELT のデータ、ファイル一覧、テーマの区分表、GDELT のどのページにもアクセスしていない。ネットワークは使っていない。
- 3つのコードは、データのファイルを開かず、現在の日時を読まない（テスト `TestNoDataNoNetwork`）。

**語の一覧に入った知識**（区分表は見ていないが、次の知識が語の選び方に入った）：
- 英語の語彙。
- **病名は、過去の流行の知識から選んだ。** EBOLA、ZIKA、COVID、SARS、MERS、H1N1、H5N1 などは、実際に大きく報じられた流行を知っていたから挙げた語である。そのため、病名の区分を使うかを案A・案Bとしてオーナーに選んでもらう（2章 (4)）。
- **GDELT のテーマ名の形の知識。** テーマ名が、分類の体系の名前を頭に付け、下線で語をつないだ形（TAX_ETHNICITY_…、TAX_FNCACT_…、WB_…、CRISISLEX_… など）であること、KILL、ARREST、PROTEST などの一般の語がそのままテーマ名にもなっていることを知っている。この知識は、次の点で語の選び方に入った。
  - 民族の区分に ETHNICITY を入れたこと、POLICE や LEADER などの役職・立場の語を入れたこと。
  - 下線で区切る照合を基本にしたこと。
  - 前回の案の CRISISLEX（今回は外した）。
- **規則を確かめるときに、覚えているテーマ名の形を試しに照合した。** 0e14f3b の版を作る途中で、語と規則を決めたあと、名前の一覧を `exclusion_matches()` に通して当たり方を見た。その結果を見てから語や規則を変えてはいない。ただし、覚えている名前で確かめたこと自体は、区分表の一部を記憶から見たのに近い。通した名前は次の52個（入力のまま）。このうち、記憶にある GDELT のテーマ名の形のものは、SOC_POINTSOFINTEREST_AIRPORT、WB_621_HEALTH_NUTRITION_AND_POPULATION、USPEC_POLICY1、ECON_TAXATION、MEDIA_MSM、FOOD_SECURITY、CRISISLEX_T03_DEAD、UNGP_FORESTS_RIVERS_OCEANS、SOC_GENERALCRIME、ECON_STOCKMARKET、TAX_DISEASE_H1N1、ENV_SOLAR の12個で、ほかは一般の語か統計係が作った名前である。
  - ELECTION2016, PLANECRASH, CYBERATTACK, SOFTWARE, AWARD, WARNING, WARM, FIREWORKS, KINGDOM, FLUENT, GRAPE, GANGES, WARES, PRINCETON, STORMWATER, COVID19, TAX_DISEASE_H1N1, AIRFORCE, ECON_STOCKMARKET, SOC_POINTSOFINTEREST_AIRPORT, EDUCATION, ENV_SOLAR, PATRIOT, COUPON, POLLEN, SCAMPI, LEADERBOARD, DEADLINE, ACCIDENTAL, DEFENSELESS, KIDNAPPERS, ASSASSINATIONS, MANSLAUGHTER, PARAMILITARY, SARSCOV2, HEADOFSTATE, FIREFIGHTER, GUNPOWDER, PROTESTANT, WB_621_HEALTH_NUTRITION_AND_POPULATION, USPEC_POLICY1, ECON_TAXATION, MEDIA_MSM, FOOD_SECURITY, AGRICULTURE, TOURISM, CRISISLEX_T03_DEAD, STRIKE, UNGP_FORESTS_RIVERS_OCEANS, SOC_GENERALCRIME, EXECUTIVE, DEADLY
  - 一般の語の形の名前（EDUCATION、AGRICULTURE、TOURISM、STRIKE など）も、記憶にあるテーマ名と同じ形でありうる。どこまでが記憶から来たかは、統計係にも切り分けられない。
  - 1cb463a と 0e14f3b の版のテストには、記憶にある形の頭の名前（TAX_FNCACT_、ECON_、ENV_、SOC_、WB_）を付けた名前も使っていた（tax_fncact_police、TAX_FNCACT_PRIME_MINISTER、ECON_WAR_DAMAGE、WB_123_Fragility-Conflict and violence、SOC_GENERAL、ECON_STOCKMARKET、ENV_SOLAR、SOC_INNOVATION と、ECON_A から ECON_Z のような合成の名前）。今回の版のテストでは、これらを頭の名前の無い作った名前（QQ_、AB_ など）に置き換えた。CRISISLEX の2つの名前は、CRISISLEX を外したことを確かめるテストに残している。
  - 監査係が試した名前の一覧は、統計係は持っていない。リードが reviews/ に記録することを提案する。
  - 今回の版（0e14f3b のあと）では、記憶にある名前を照合に通していない。確かめに使ったのは、監査係と統計係が作った名前（2章 (1) の既知の例の表）だけである。
- **今回足した語の出どころ**：ASSASSINATION、EXECUTION、STABBING、EXPLOSION、CRASH、CYBERATTACK（くっつき一致で拾う）と、語と数字がくっついた形は、リードの差し戻し（監査の所見）で挙がった例である。それ以外に足した語（GUNMAN、DETENTION、VICTIM、EVACUATION など）は、同じ区分の意味から統計係が挙げた。
- 世の中の出来事の知識：病名のほかに、行事の日付が年によって動くこと（移動祝日など。3章 (1)）を使った。
- 統計の一般の知識：件数のばらつきの大きさ（ポアソン分布。1章 (2)）。

## 8. 引用
Data: The GDELT Project (https://www.gdeltproject.org/). This project is not affiliated with or endorsed by the GDELT Project.
データ出典：GDELT Project（https://www.gdeltproject.org/）。本プロジェクトは GDELT Project と提携・承認の関係にありません。
（この文書は GDELT のデータを使っていないが、規則は GDELT のデータに適用するため付ける。）
