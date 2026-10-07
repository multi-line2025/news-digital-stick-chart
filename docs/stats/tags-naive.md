# タグの一覧の規則、素朴な予測、採点計画の一部（T-019〜T-022）

仮の名前：exclusion-v1（除外の規則）、tagrules-v1（タグを入れる規則）、naive-v1（素朴な予測）、scoring-partial-v1（採点計画の一部）。
どれも正式な版の番号ではない。正式な番号は、封印係の追記のみの記録で何件目かによって決まる。

この文書は、手順4（手法を作る期間のデータで試運転する）の前に決めて封印する「決め方」をまとめた提案である。
数値のうち A（＝最低の報道量 V）だけは、ここで決めた式に手法を作る期間のデータを入れて決まる。

- 値と語の一覧は `src/stats/exclusion.py`（除外の規則）と `src/stats/tagrules.py`（入れる規則）の定数で、この文書の表はその写しである。`tests/stats/test_exclusion.py`（除外の規則）と `tests/stats/test_tagrules.py`（入れる規則）で照合する。
- 素朴な予測と採点計画の一部（もとの3章・4章）は、T-022 の差し戻し3回目で `docs/stats/naive-scoring.md` に移した。その表は `tests/stats/test_t019.py` が `src/stats/naive.py`・`src/stats/scoring.py` と照合する。
- 除外の規則を `exclusion.py` に分けたのは T-022 である。規則の中身は変えていない。T-022 の差し戻し1回目で、入れる規則（K を含む）も除外の規則と同じ順番1で封印する形に直した（5章）。ファイルを分けたままにしているのは、除外の規則の出力に K が入らないことをテストで確かめるためである。
- 封印の対象の一覧と sha256、封印係が封印の前に確かめることは、`docs/stats/seal-order1.md`（封印係への申し送り）にまとめた。
- **この文書は、順番1で封印したあとは直さない（凍結する）。** 順番2以降の決定と、素朴な予測・採点計画の改訂は、docs/stats/ の別の文書に書く。理由は 5章 (2)。凍結を確かめるため、封印するテスト `test_tagrules.py` が、この文書の sha256 を定数として持つ（テスト `test_doc_is_frozen`）。
- GDELT のデータ、ファイル一覧、テーマの区分表、ネットワークは使っていない（7章）。
- 封印はしていない。封印は封印係が行う（5章）。

再計算の手順（プロジェクトのルートで）：

```
PYTHONDONTWRITEBYTECODE=1 python3 -B src/stats/exclusion.py
PYTHONDONTWRITEBYTECODE=1 python3 -B src/stats/tagrules.py
PYTHONDONTWRITEBYTECODE=1 python3 -B src/stats/naive.py
PYTHONDONTWRITEBYTECODE=1 python3 -B src/stats/scoring.py
PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest discover -s tests/stats -v
```

## 0. オーナーの承認事項と決定

**2026-10-08 のオーナーの決定**（reviews/T-020.md「2026-10-08 オーナーの発言」）：
- 7（病名の扱い）：**案B**。病名の区分 `disease_named` は使わない。
- 8（民族・宗教の集団）：**除外の区分に加える**。CLAUDE.md の「除外する規則」にも、リードが書き足した。
- そのほかの項目（1〜6・9〜18）は、すべて承認された。
- 決定はコードの `exclusion.ENABLED_OPTIONAL_CATEGORIES = ("ethnic_religious_group",)` と、出どころの `exclusion.OWNER_CHOICE_SOURCE` に反映した（2章 (8)）。

**承認をお願いすること（T-022。封印の前に要る）**

A. **入れる規則を順番1で封印する変更**（状態：オーナーの判断待ち）
- 変更の中身：承認済みの 0章3 は「K（と A の式）は、数え方が封印されるまで封印しない」としていた。これを、入れる規則の定数と式（K = 10、MIN_COUNT_PER_QUARTER = 1、四半期の規則、A の式、存在の条件）を除外の規則と同じ順番1で、区分表の取得と method-access より前に封印する形に変える。数え方は未決のままでよい。数え方が決まったあとの順番3では、数え方とのつながり（K をどの単位で読むか）だけを足し、K・存在の条件・A の式は変えない。値（K = 10 など）は変えない。
- 理由の要約：数え方は、K をいつ封印しても試運転のあとに決まる（T-001 のオーナーの決定）。K を数え方のあとに封印すると、数え方に加えて K も、区分表と手法を作る期間のデータを見てから選べてしまう。K を先に封印すれば、データを見てから選べるのは数え方だけになる。式は、数え方がどれに決まっても同じ形で計算できるので、先に封印できる。詳しくは 5章 (1)。
- 承認しない場合：0章3 のとおり、順番1は除外の規則だけにし、K と入れる規則は順番3（数え方の封印のあと）に封印する。統計係が、順番1の対象から `tagrules.py`・その出力・`test_tagrules.py` を外し、K を含むこの文書の扱い（K の節を別の文書に分けるか）を決め直した版を作り、sha256 の表を作り直す。その場合、K = 10 は git の履歴には残るが、封印による時刻証明は試運転のあとになり、K をデータを見てから選べる余地が残る。この限界を公開物に書く。
- この変更は承認済みの項目の変更なので、承認の発言が reviews/ に記録されるまで封印しない（`docs/stats/seal-order1.md` 2章の確認項目1）。

B. **数え方の選び方に残る自由への対策**（状態：オーナーの判断待ち）
- 残る自由：A が順番1で封印されても、数え方（r(d) の分子と分母の単位）を選ぶことで、K = 10 が記事の何件に当たるか（したがって A と V、一覧に入るテーマ）は動く。数え方は試運転のあとに決める（T-001 のオーナーの決定「分母とテーマの数え方はまずは試運転してからだ」）ので、この自由は A の承認・不承認に依らず残る。
- 前回の提出で書いた対策「試運転では `build_tag_list()` を実データで実行しない」は、守られても目的を果たさない（T-022 の監査 M-2）。規則のコードは公開されているので、試運転のデータがあれば、誰でも数え方の候補ごとに一覧を計算できる。そのため、この対策は取り下げる。
- 代わりの案：method-access より前に、数え方の候補の有限の一覧（例：テーマの欄の種類、記事の数か言及の回数か、重複のまとめ方の組み合わせ）を封印する。順番5では、封印した候補のすべてで `build_tag_list()` を実行し、候補ごとの一覧と N_med・A を並べて公開する。採点に使う一覧は、試運転のあとに選んだ一つの数え方のものだが、ほかの候補で一覧がどう変わったかを第三者が見られる。
  - この案は、試運転のあとに数え方を決めるというオーナーの決定の範囲で、選べる候補を前もって限る。候補の一覧を作るのは収集係と統計係で、オーナーの承認が要る。
  - 案を採る場合の、さらに強い選択肢：候補の一覧に加えて、候補の中から一つを選ぶ基準も、method-access より前に封印する。基準は、一覧の件数や中身を見ずに当てはめられるものに限る（例：試運転で分かるデータ源の性質だけで決まる条件。「欠けた日が最も少ない数え方」など）。この選択肢では、試運転のあとに残る自由は「基準を当てはめた結果」だけになる。代わりに、試運転の前に基準を決めることになるので、「まずは試運転してから」というオーナーの決定の範囲を、さらに狭める。
  - 判断していただくこと：(i) 代わりの案を採るか、(ii) 採る場合に、選ぶ基準も先に封印するか、(iii) どちらも採らず、残る自由を限界として公開するか。
  - 案を採らない場合も、順番5の記録に、選んだ数え方の N_med と A を載せ、K = 10 が何に当たるかを読めるようにする（5章 (1)）。

以下は承認をお願いしたときの項目で、記録のために残す。

タグの一覧（1章・2章）
1. **A の決め方**（1章 (2)）：A = 10 ÷ N_med。N_med は、手法を作る期間の区画のうち欠けた日でない日の、全体の報道量の中央値。「全体の報道量が普段どおりの日に、1日あたり平均10件」に当たる比率である。V は A と同じ値にする（T-011 で決定済み）。
2. **「全体にわたって存在する」の定義**（1章 (1)）：区画を暦の四半期（24個）に分け、どの四半期でも、欠けた日でない日の報道量の合計が1件以上あること。
3. **報道量の数え方を先に封印すること**（1章 (2)、5章）：r(d) の分子と分母の単位は、収集係が T-018 で決める。K（と A の式）は、その数え方が封印されるまで封印しない。数え方の封印は、この文書の規則の封印と同時か、それより前に行う。（T-022 で、この項目の変更を提案した。0章の「承認をお願いすること」の A。）
4. **除外の照合のしかた**（2章 (1)）：名前と説明を語に区切り（英字と数字の境目でも区切る。ELECTION2016 は ELECTION と 2016）、語の一覧の語に次のどれかで当たれば外す。一件ずつの例外は持たない。
   - 完全一致と形の変化（複数形・活用形を規則で作る）：名前と説明の両方に使う。
   - くっつき一致：**名前の欄だけ** に使う。数値は次のとおり。
     - 先頭での一致：**6文字以上**（PREFIX_MIN_LEN = 6）の語が名前の語の先頭にあり、残りが **4文字以上**（GLUE_MIN_REST = 4）。例：POLICEOFFICER は POLICE に当たる。
     - 末尾での一致：どの長さの語でも、名前の語の末尾にあり、その前の残りが **4文字以上**。例：CIVILWAR は WAR、BIRDFLU は FLU、PLANECRASH は CRASH に当たる。ただし **4文字以下で ING・ED・ER・S で終わる語**（今は KING・SARS・MERS の三つ）は末尾で当たらない（BREAKING、SPEAKING などを防ぐため）。
   - 語の並び（AIR FORCE など）をつなげた一語（AIRFORCE）の照合も、名前の欄だけに使う。
   - 既知の外しすぎ（2章 (1) の表）：LEADERSHIP_TRAINING、BRAINSTORM_SESSION、ANTIVIRUS_SOFTWARE、COMPATRIOT、CAMPFIRE、MARKETCRASH、TEAMLEADER、ROADKILL、DEFENSELESS、HEARTATTACK。
   - 形の変化を使った末尾の一致と、先頭の一致による外しすぎ：SKYSCRAPER（RAPE の形の変化 RAPER が末尾にある）、PAINKILLER（KILLER）、SOFTSKILLS（KILLS）、CABINETMAKER（CABINET が先頭）、REGIMENTAL（REGIME が先頭）、PROTESTANTISM（PROTEST が先頭）。規則は変えず、外しすぎの方向の誤りとして開示する。既知の取りこぼし：GUNCONTROL、COUPATTEMPT、HIVAIDS、CARBOMB、MINISTERIAL、DEADLY。
5. **外しすぎの方向を選ぶ方針**（2章 (1)・(3)）：5つの区分のテーマが一覧に残るより、関係の無いテーマが外れる方を選ぶ。たとえば DEFENSE（法廷の弁護側も外れる）、DEATH と DEAD（訃報も外れる）、VACCINE（予防接種の制度も外れる）、FIRE（解雇の意味の FIRED も外れる）、ATTACK（HEARTATTACK の心臓発作も外れる）、LEADER（LEADERSHIP も外れる）、VIRUS（ANTIVIRUS も外れる）、STORM（BRAINSTORM も外れる）。
6. **語の一覧**（2章 (2)）。1cb463a の版からの変更は、出どころを付けて 2章 (7) の表にまとめた（CRISISLEX と ELECT を外し、ASSASSINATION、EXECUTION、STABBING、EXPLOSION、CRASH、ELECTED、MANSLAUGHTER、KILLING などを足した。CYBERCRIME は 0e14f3b で語の一覧から消した。0e14f3b では、くっつき一致が説明の欄にも掛かっていたので、説明の欄でも外れていた。247fc1d でくっつき一致を名前の欄だけにしたときに、説明の欄の cybercrime で外れなくなる後戻りが出た。T-020 で語の一覧に戻した）。
7. **病名の扱い**（2章 (4)）：**決定：案B**（2026-10-08）。尋ねたときは次の二つから選んでもらった。当時のコードの既定は案A（仮の値）だった。
   - 案A：一般の語（DISEASE、VIRUS、EPIDEMIC など）に加えて、病名（EBOLA、ZIKA、COVID など）の区分 `disease_named` も使う。
   - 案B：一般の語だけを使い、`disease_named` を使わない。
   - 病名は過去の流行の知識から選んだ（7章）。案Bなら、その知識は規則に入らない。代わりに、名前と説明に一般の語が無い病気のテーマが一覧に残る。
   - 決定の反映（コードとテストの直し方、開示）の手順は 2章 (8)。
8. **民族・宗教の集団の区分を足すか**（2章 (5)）：**決定：加える**（2026-10-08。CLAUDE.md も書き足された）。尋ねたときは CLAUDE.md の5つの区分の外にあり、統計係の推奨は「足す」、当時のコードの既定も「足す」（仮の値）だった。足すことは CLAUDE.md の決定事項の変更だったので、リードが書き足した。決定の反映の手順は 2章 (8)。
9. **組織名**（2章 (5)）：別の規則を作らない。5つの区分の語に当たる組織のテーマだけが外れる。
10. **区分表を見たあとの変更の範囲**（2章 (6)）：**テストで再現できる不具合の修正だけ** を認める（例外が出る、空の名前で落ちる、など）。語、数値（PREFIX_MIN_LEN、GLUE_MIN_REST など）、当たり方の種類は変えない。
    - 危うさ：区分表を見たあとで規則を変えると、名前を見ながら、どのテーマを外すかを実質的に選べる。たとえば GLUE_MIN_REST を4から3に変えるだけで、特定の名前の群れを外したり残したりできる。語を一つ足すのも同じである。数値と当たり方を変えないのは、この余地を無くすためである。
    - それでも変える場合は、新しい版として、オーナーの承認を得て、method-access より前に封印する。前の版と新しい版の両方で一覧を計算し、出入りしたテーマを並べて公開することを必須とする。
11. **記憶にある名前で照合を試したこと**（7章）：統計係（0e14f3b の版を作る途中）と、1cb463a の版を監査した監査係は、記憶にある GDELT のテーマ名の形の名前を照合に通して、当たり方を見た。その監査係は所見を出し終えている。監査係の例は差し戻しを通して、0e14f3b と今回の版の語と規則に入った。そのため、「区分表を見る前に決めた」という主張は、「区分表を取得する前に決めた。ただし作成者と監査係はテーマ名の一部を記憶しており、それを照合で試した」に弱まる。統計係が試した名前の一覧は 7章に残した。その監査係が試した名前の全部の一覧は作れない。報告が「など」で終わっているためである。記録の欠けとして開示する。（エラーで止まったのは、247fc1d の監査を始めた別の監査係で、この件とは別である。）リードの決定（2026-10-07）により、これ以降は記憶にある名前を照合に通さない。この事実を承知したうえで、規則を承認するかを判断してほしい。

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
  - この根拠は、記事の数で数える場合の話である。言及の回数で数える場合は、1本の記事が複数回数えられるので、ばらつきはポアソン分布より大きくなり、70件は記事の数では70件より少ない。数え方が決まったら、順番3の文書で、その数え方でこの根拠を読み直して書く。K は変えない（読み直しの結果、根拠が弱いと分かっても、それは限界として公開する）。
- **V は比率で固定される**ことの限界：A と V は手法を作る期間の N_med で決まる比率で、三つの期間と前向きの予言で同じ値を使う。全体の報道量（r(d) の分母）が期間によって増減すると、同じ V が別の件数に当たる。たとえば全体の報道量が手法を作る期間の倍になれば、V は1日あたり約20件に当たり、半分になれば約5件に当たる。V を件数で固定せず比率で固定したのは、CLAUDE.md が報道量を比率で扱うと決めているためである。各期間の全体の報道量の中央値は公開し、V が何件に当たるかを読めるようにする。
- **数え方とのつながり**：r(d) の分子と分母の単位（記事の数え方、重複のまとめ方、どのテーマの欄を数えるか）は、オーナーの以前の決定で試運転のあとに決める（収集係）。K は「r(d) の分子の単位で、全体の報道量が中央値の日に1日あたり K」と読む。式 A = K ÷ N_med は、数え方がどれに決まっても同じ形で計算できる。そのため、**K・存在の条件・A の式は、数え方を待たずに順番1で封印する**（5章）。数え方が決まったあと（順番3）に足すのは、その数え方で K を何と読むか（例：記事の数か、言及の回数か）と、順番1の記録への参照だけで、ここの値と式は変えない。
  - 件数は0以上の整数であること（`build_tag_list()` は整数でない件数で止まる）。数え方が整数でない値（重み付きの件数など）を出す場合は、規則の変更になるので、新しい版としてオーナーの承認を得て封印し直す。
  - 存在の条件（各四半期に1件以上）は、記事の数で数えても言及の回数で数えても、「1本以上の記事に付いた」と同じ意味になる。
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
     - 末尾：名前の語が一覧の語（またはその形の変化）で終わり、その前の残りが **4文字以上**。一覧の語の長さは問わない。ただし、4文字以下で ING・ED・ER・S で終わる一覧の語（今は KING・SARS・MERS の三つ）には使わない。
- 語の並び（例：PRIME MINISTER）は、続けて現れたときに一致とする（最後の語だけ形の変化を認める）。これは名前と説明の両方に使う。加えて、**名前の欄だけ** で、並びをつなげた一語（PRIMEMINISTER、AIRFORCE）を上の規則で照合する。
  - 名前の欄だけにそろえた理由：つなげた一語の照合は、語がくっついた形への対応で、くっつき一致と同じ種類の規則である。くっつき一致を名前の欄だけに使うと決めたので、同じ欄にそろえた。説明は空白で区切った文なので、語の並びはそのまま「続けて現れる」で当たる。247fc1d のコードは説明の欄でもつなげた一語を照合しており、文書と食い違っていた。T-020 でコードを文書に合わせた（テスト `test_joined_only_in_name`）。
- **数値と条件の理由**（データを見ずに、英語の語の作りだけから決めた）
  - 先頭を6文字以上にした：5文字以下の語は、関係の無い長い語の頭に現れやすい（ELECT が ELECTRIC に、STORM が STORMWATER に、QUEEN が QUEENSLAND に当たる）。前回の ELECT はこの誤りの元だったので外し、ELECTED と ELECTING を語として書いた。
  - 残りを4文字以上にした：残りが3文字以下だと、英語の接頭辞や語尾の一部（PAT+RIOT、G+RAPE、BE+GUN、PRINCE+TON など）で偶然当たる。4文字以上なら、残りが一つの語であることが多い（CIVIL+WAR、BIRD+FLU、PLANE+CRASH）。
  - 末尾は短い語にも許した：取りこぼしの多くは「修飾語 + 短い語」の形（CIVILWAR、COLDWAR、SWINEFLU、SHOTGUN）だったため。SOFTWARE は末尾が WARE で、WAR では終わらないので当たらない。
  - KING を末尾から外す条件：KING は英語の語尾 ING を含み、BREAKING、SPEAKING、THINKING のように、残りが4文字以上の語の末尾に多く現れる。特定の語を名指しせず、「4文字以下で語尾の形をした語」という形の条件にした。この条件には KING のほかに SARS と MERS も当たる（S で終わるため）。この二つは末尾で当たらなくなるが、完全一致と形の変化では当たる。
  - 形の変化を使った末尾の一致は、短い語の形の変化（RAPER、KILLER、KILLS など）が、関係の無い長い語の末尾に現れるときに外しすぎを出す（SKYSCRAPER、PAINKILLER、SOFTSKILLS）。先頭の一致も、6文字以上の語が別の語の頭になっているときに外しすぎを出す（CABINETMAKER、REGIMENTAL、PROTESTANTISM）。規則は変えず、既知の外しすぎとして下の表に載せた。規則を直すと別の誤りが出ることを、これまでの版で繰り返したため。
  - 説明の欄ではくっつき一致を使わない：説明は空白で区切られた文なので、語がくっつくことは少ない。くっつき一致を使うと、ELECTRICITY、LEADERSHIP、BRAINSTORM のような普通の語で外しすぎが増える。SOLAR_ENERGY の説明に electricity や leadership があっても、外れない（テスト `test_glue_not_in_description`）。説明の欄でも、語の完全一致と形の変化（storms など）には当たる。
  - 監査の提案（先頭は6文字以上、末尾は短い語にも許す）を採り、残りの文字数と KING の条件、説明の欄の扱いを足した。監査の提案では、COUPATTEMPT、GUNCONTROL、HIVAIDS も当たる案だったが、これらは短い語（COUP、GUN、HIV）が **先頭** にある形で、先頭の一致を短い語に許すと COUPON、HIVE のような誤りが出る。そのため取りこぼしとして残した。
- **既知の例**：監査係が作った名前と統計係が作った名前で、結果を次のとおり固定した（テスト `test_known_examples`）。どれもテストのために作った名前である。結果は、選べる区分（病名と民族・宗教）をすべて有効にしたときのもの。オーナーの選択で変わる例は 2章 (8) の表に分けた。

<!-- table:known-examples -->
| 結果 | 名前 |
|---|---|
| 残す（正しく残す） | ELECTRIC_POWER, ELECTRONICS, QUEENSLAND_TOURISM, SOFTWARE, AWARD, WARNING, WARM, STEWARD, FIREWORKS, KINGDOM, BOOKING, BREAKING_NEWS, SPEAKING, THINKING, PARKING, GRAPE, DRAPE, PATRIOT, BEGUN, SKILLS, RECOUP, COUPON, POLLEN, SCAMPI, GANGES, PRINCETON, STORMWATER, PROTESTANT, CABINETRY, AIDGROUPS, STOCKMARKET, FLUENT, DEADLINE, GUNPOWDER, EXECUTIVE |
| 残る（取りこぼし） | GUNCONTROL, COUPATTEMPT, HIVAIDS, CARBOMB, MINISTERIAL, DEADLY |
| 外れる（外しすぎ） | LEADERSHIP_TRAINING, BRAINSTORM_SESSION, ANTIVIRUS_SOFTWARE, COMPATRIOT, CAMPFIRE, MARKETCRASH, TEAMLEADER, ROADKILL, DEFENSELESS, HEART_ATTACK, AB_DEFENSE_ATTORNEY, OBITUARY_DEATH, AB_VACCINE_POLICY, AB_FIRED, HEARTATTACK, SNOWSTORM, SKYSCRAPER, PAINKILLER, SOFTSKILLS, CABINETMAKER, REGIMENTAL, PROTESTANTISM |
| 外れる（正しく外す） | CIVILWAR, COLDWAR, BIRDFLU, SWINEFLU, PLANECRASH, CYBERATTACK, PARAMILITARY, MANSLAUGHTER, TIMEBOMB, SHOTGUN, HANDGUN, POLICEOFFICER, ELECTION2016, PRIMEMINISTER, AIRFORCE, DRUGABUSE, IDENTITYTHEFT |

- どの区分の語に当たっても同じく外す。区分の名前は、報告のためだけに使う。出力には、当たった語・欄・当たり方を、テーマごとにすべて載せる。
- 名前と説明のどちらかで当たれば外す。説明に語が付随して出てくるだけのテーマも外れる。**外しすぎの方向の誤りを選んだ。** 5つの区分のテーマが一覧に残る誤りの方が、プロジェクトの目的に反するため。この方針で外れる例は 0章の5。

### (2) 語の一覧

今の設定で使う区分は、`disease_named` を除くすべて（2026-10-08 のオーナーの決定）。`disease_named` の語は記録のために残している。

<!-- table:terms -->
| 区分 | CLAUDE.md の区分 | 語 |
|---|---|---|
| politics_election | 政治・選挙 | ELECTION, ELECTORAL, ELECTED, ELECTING, VOTE, BALLOT, REFERENDUM, POLL, CANDIDATE, INAUGURATION, POLITICS, POLITICAL, POLITICIAN, PARLIAMENT, PARLIAMENTARY, LEGISLATURE, LEGISLATIVE, LEGISLATOR, CONGRESS, SENATE, SENATOR, LAWMAKER, PRESIDENT, PRESIDENTIAL, PRIME MINISTER, MINISTER, CHANCELLOR, GOVERNOR, MAYOR, LEADER, HEAD OF STATE, CABINET, COUP, IMPEACH, IMPEACHMENT, REGIME, DICTATOR, DICTATORSHIP, PROTEST, DEMONSTRATOR, SANCTION, DIPLOMACY, DIPLOMATIC, DIPLOMAT, EMBASSY, AMBASSADOR, PROPAGANDA, LOBBYING, LOBBYIST |
| conflict_violence | 紛争・暴力 | WAR, WARFARE, MILITARY, ARMY, ARMED, NAVY, NAVAL, AIR FORCE, SOLDIER, TROOP, MILITIA, INSURGENCY, INSURGENT, INSURRECTION, REBEL, REBELLION, GUERRILLA, SEPARATIST, TERROR, TERRORISM, TERRORIST, EXTREMISM, EXTREMIST, JIHAD, JIHADIST, CONFLICT, VIOLENCE, VIOLENT, ATTACK, BOMB, BOMBING, EXPLOSIVE, EXPLOSION, WEAPON, GUN, GUNMAN, GUNMEN, GUNFIRE, FIREARM, SHOOTING, SHOOTER, SNIPER, MISSILE, ARTILLERY, AIRSTRIKE, KILL, KILLING, MASSACRE, GENOCIDE, SLAUGHTER, MANSLAUGHTER, ASSASSIN, ASSASSINATE, ASSASSINATION, EXECUTION, BEHEADING, STABBING, LYNCHING, CEASEFIRE, PEACEKEEPING, PEACEKEEPER, INVASION, HOSTAGE, TORTURE, RIOT, UNREST, CRACKDOWN, PERSECUTION, SIEGE, BLOCKADE, DEFENSE, DEFENCE, CONSCRIPTION, REFUGEE, DISPLACED, ETHNIC CLEANSING |
| crime | 犯罪 | CRIME, CRIMINAL, MURDER, HOMICIDE, ASSAULT, ROBBERY, THEFT, THIEF, THIEVES, BURGLARY, FRAUD, EMBEZZLEMENT, CORRUPTION, BRIBERY, BRIBE, SMUGGLING, SMUGGLER, TRAFFICKING, TRAFFICKER, NARCOTICS, CARTEL, GANG, MAFIA, LAUNDERING, EXTORTION, KIDNAP, KIDNAPPING, KIDNAPPED, KIDNAPPER, ABDUCTION, RAPE, HARASSMENT, ABUSE, ARREST, DETAIN, DETAINEE, DETENTION, POLICE, PRISON, JAIL, INCARCERATION, PROSECUTION, PROSECUTOR, INDICTMENT, FELONY, PIRACY, SCAM, VANDALISM, ARSON, POACHING, COUNTERFEIT, ESPIONAGE, TREASON, VICTIM, CYBERCRIME |
| specific_person | 特定の人物 | POPE, KING, QUEEN, PRINCE, PRINCESS, MONARCH, MONARCHY, ROYAL, EMPEROR, EMPRESS, CELEBRITY |
| disaster | 災害・感染症 | DISASTER, EARTHQUAKE, TSUNAMI, FLOOD, HURRICANE, TYPHOON, CYCLONE, TORNADO, WILDFIRE, FIRE, DROUGHT, LANDSLIDE, MUDSLIDE, SINKHOLE, VOLCANO, VOLCANIC, ERUPTION, AVALANCHE, HEATWAVE, HEAT WAVE, STORM, BLIZZARD, FAMINE, CRASH, DERAILMENT, SHIPWRECK, ACCIDENT, EVACUATION, CASUALTY, FATALITY, INJURED, DEATH, DEAD |
| disease_general | 災害・感染症 | EPIDEMIC, PANDEMIC, OUTBREAK, DISEASE, INFECTION, INFECTIOUS, CONTAGION, CONTAGIOUS, VIRUS, PATHOGEN, VACCINE, VACCINATION, QUARANTINE |
| disease_named | 災害・感染症 | INFLUENZA, FLU, EBOLA, ZIKA, CHOLERA, MALARIA, MEASLES, HIV, TUBERCULOSIS, POLIO, CORONAVIRUS, COVID, SARS, SARSCOV, MERS, PLAGUE, DENGUE, ANTHRAX, SMALLPOX, HEPATITIS, MENINGITIS, RABIES, H1N1, H5N1 |
| ethnic_religious_group | 民族・宗教の集団 | ETHNIC, ETHNICITY, TRIBE, TRIBAL, RELIGION, RELIGIOUS, SECTARIAN |

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
- そのため、次の二つを並べてオーナーに選んでもらった。**オーナーは案B を選んだ**（2026-10-08）。
  - 案A（当時のコードの既定。仮の値だった）：`disease_general` と `disease_named` の両方を使う。名前と説明に一般の語が無い病気のテーマも外れる。
  - 案B：`disease_general` だけを使う。知識から選んだ病名は規則に入らない。代わりに、名前が病名だけで説明にも一般の語が無いテーマは一覧に残る。
- 決定は `ENABLED_OPTIONAL_CATEGORIES` に反映した（手順は (8)）。区分表を見る前の決定なので、選び出しにはならない。`disease_named` の語は、記録のために一覧に残す（使わない）。

### (5) 組織名と民族集団のテーマ（T-001 の申し送り）
T-001 の報告では、テーマの欄に組織名と民族集団が入ることがある（codebook）。

**民族・宗教の集団：外す区分に加える（2026-10-08 オーナー決定）**
- 尋ねたときの CLAUDE.md の5つの区分は「特定の人物」で、集団は入らなかった。そのため、この区分を足すことは CLAUDE.md の決定事項の変更だった。オーナーが加えることを決め、リードが CLAUDE.md の「除外する規則」に書き足した。今の `CLAUDE_CATEGORY_OF` では、この区分は「民族・宗教の集団」に対応する。
- 推奨した理由：
  - 特定の民族・宗教の集団が来週ニュースになる、という予言を公開すること自体に、迫害や衝突を予告する読まれ方をする危うさがある。
  - そうしたテーマの報道が跳ねるのは、多くが紛争・暴力や犯罪の報道と重なると考えられる。しかし、その重なりは区分表の名前と説明の語では捕まえられない。
- 語は `ethnic_religious_group` の行（ETHNIC、RELIGIOUS など）。言語の分類（言語の名前）は入れていない。言語の名前は、場所や報道の言語として付くことが多いと考えたため。
- 決定は `ENABLED_OPTIONAL_CATEGORIES` に反映した（手順は (8)）。

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
1cb463a（初回の提出）、0e14f3b（再提出1回目）、247fc1d（再提出2回目）、ecd745f と 2f4b3ce（T-020）、今回の版（T-022）の差分。出どころは「区分の意味」（区分の意味から統計係が挙げた）、「監査の例」（差し戻しで示された例。監査係は記憶にある名前で照合を試していた）、「記憶の名前による照合」（統計係が記憶にある名前を照合に通した結果から変えたもの）のどれか。「記憶の名前による照合」に当たる変更は無い。統計係が記憶にある名前で試したのは 0e14f3b の語と規則を決めたあとで、その結果を見て語や規則を変えてはいない（7章）。

1cb463a から 0e14f3b

| 種類 | 中身 | 出どころ |
|---|---|---|
| 変えた規則 | 英字と数字の境目でも区切る | 監査の例（ELECTION2016） |
| 変えた規則 | 形の変化を規則で作る（inflections）。一覧の複数形・活用形（WARS、KILLED、VOTERS など103語）を消し、規則に置き換えた。消した形はすべて規則で作られる | 区分の意味（一覧を基本形にそろえるため） |
| 変えた規則 | くっつき一致（5文字以上の語が名前の語の先頭か末尾） | 監査の例（PLANE_CRASH、CYBERATTACK） |
| 消した語 | CRISISLEX | 監査の例（テーマの体系の名前で、一般の語でない） |
| 消した語 | CYBERCRIME（くっつき一致で CRIME に当たるため）。**後戻りがあった**：くっつき一致は名前の欄だけに使うので、247fc1d では説明の欄の cybercrime に当たらなくなっていた。T-020 で語の一覧に戻した（下の表） | 区分の意味 |
| 消した語 | KILLINGS（一覧の基本形に置き換えた。0e14f3b では当たらなくなっていた。今回 KILLING を足して直した） | 区分の意味 |
| 足した語 | ASSASSINATION、EXECUTION、STABBING、EXPLOSION、CRASH | 監査の例 |
| 足した語 | ASSASSIN、ASSASSINATE、ELECT、CANDIDATE、POLL、INAUGURATION、LEGISLATOR、CHANCELLOR、LOBBYIST、NAVAL、GUERRILLA、SEPARATIST、INSURRECTION、GUNMAN、GUNMEN、GUNFIRE、SHOOTER、SNIPER、ARTILLERY、SLAUGHTER、BEHEADING、LYNCHING、CONSCRIPTION、THIEF、THIEVES、EMBEZZLEMENT、SMUGGLER、TRAFFICKER、KIDNAPPED、KIDNAPPER、ABDUCTION、DETAIN、DETAINEE、DETENTION、FELONY、POACHING、COUNTERFEIT、ESPIONAGE、TREASON、VICTIM、MUDSLIDE、SINKHOLE、DERAILMENT、SHIPWRECK、ACCIDENT、EVACUATION、INJURED、CONTAGION、CONTAGIOUS、PATHOGEN | 区分の意味 |
| 足した語 | ANTHRAX、SMALLPOX、HEPATITIS、MENINGITIS、RABIES、SARSCOV、H1N1、H5N1 | 区分の意味（病名は過去の流行の知識。7章） |
| 変えた規則 | 区分の分け直し：disaster_disease を disaster（災害）・disease_general（感染症の一般の語）・disease_named（病名）の3つに分けた。CLAUDE.md の区分はどれも「災害・感染症」のまま | 監査の例（病名の知識の指摘。病名だけを選べるようにするため） |
| 変えた規則 | 病名の区分（disease_named）と民族・宗教の区分を、オーナーが選ぶ区分にした | 監査の例（病名の知識の指摘） |

0e14f3b から 247fc1d

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

247fc1d から 2f4b3ce（T-020）

| 種類 | 中身 | 出どころ |
|---|---|---|
| 足した語 | CYBERCRIME（説明の欄での後戻りを直すため） | 監査の例 |
| 変えた規則 | つなげた一語の照合を名前の欄だけにした（文書の記述にコードを合わせた）。結果：説明の欄だけに airforce、primeminister、headofstate、ethniccleansing（その複数形などの形の変化を含む）のようにつなげた形で現れ、ほかの語には当たらないテーマは、247fc1d では外れていたが、今回の版では一覧に残る。名前の欄の同じ形は今までどおり外れる | 監査の例 |
| 開示だけ | 形の変化を使った末尾の一致と先頭の一致の外しすぎ（SKYSCRAPER など6つ）を既知の例に足した。規則は変えていない | 監査の例 |
| 開示だけ | 末尾の一致を使わない語は KING・SARS・MERS の三つ（前回「KING だけ」と書いたのは誤り）。規則は変えていない | 監査の例 |

2f4b3ce から今回の版（T-022。オーナーの決定の反映と、封印の準備）

| 種類 | 中身 | 出どころ |
|---|---|---|
| 変えた設定 | `ENABLED_OPTIONAL_CATEGORIES` を仮の値（両方を有効）から `("ethnic_religious_group",)` に変えた。病名の区分は使わない | オーナーの決定（2026-10-08） |
| 足した定数 | `OWNER_CHOICE_SOURCE`（決定の出どころ）。`optional_choice_status()` はその有無から計算する | リードの指示（T-020 の監査 M-1） |
| 変えた対応 | `ethnic_religious_group` の CLAUDE.md の区分を「民族・宗教の集団」にした（CLAUDE.md の書き足しに合わせた） | オーナーの決定（2026-10-08） |
| ファイルの分け直し | 除外の規則を `tagrules.py` から `exclusion.py` に、そのテストを `test_exclusion.py` に分けた。語・数値・当たり方は変えていない。差し戻し1回目で、入れる規則のテストも `test_t019.py` から `test_tagrules.py` に分けた | 当初は K と別に封印するため。差し戻し1回目からは、どちらも順番1で封印し、除外の規則の出力に K が入らないことを確かめるため（5章） |
| 変えた関数 | `compare_lists()` が、二つの結果が同じ入力から作られたことを確かめ、両方の設定を出力に入れる | リードの指示（T-020 の監査 L-1） |
| 変えた関数 | `compare_lists()` の照合に、欠けた日でない日の数・四半期・テーマごとの四半期の件数と平均を足した（T-022 差し戻し1回目） | リードの指示（T-022 の監査 L-1） |
| 変えた定数 | `OWNER_CHOICE_SOURCE` を "2d23cdf:reviews/T-020.md 2026-10-08 オーナーの発言（原文のまま記録）" にした。照合は 2d23cdf の版を読み、見出しは完全一致（T-022 差し戻し1回目） | リードの指示（T-022 の監査 M-2） |

- 選べる区分（病名と民族・宗教）をすべて有効にしたとき、1cb463a の版の語（CRISISLEX を除く）が今回の版でもすべて外れることを、テスト `test_v1_terms_still_excluded` で確かめている。オーナーは案Bを選んだので、今の設定では 1cb463a の病名（EBOLA、ZIKA、COVID など）だけで当たるテーマは外れない。これは後戻りではなく、選択の結果として 2章 (8) の手順で開示する。民族・宗教の区分は使うので、ETHNIC などの語は今の設定でも外れる。名前の欄（語を下線でつないだ名前）と、説明の欄（語をそのまま置いた説明と、文の中に置いた説明）の両方を見る。

### (8) 選べる区分の決定を反映する手順
対象は、選べる区分（`disease_named`、`ethnic_religious_group`）についてオーナーが決めたとき。オーナーが仮の値を変えた場合も、仮の値どおりに承認した場合も、同じ手順で行う。どちらも、区分表を見る前に、封印の前に行う。

1. `src/stats/exclusion.py` の `ENABLED_OPTIONAL_CATEGORIES` を、オーナーの決定に合わせる。仮の値どおりに承認された場合は、値は変わらない。語の一覧（`EXCLUSION_TERMS`）は変えない。使わない区分の語も、封印する記録に残す。
2. `exclusion.OWNER_CHOICE_SOURCE` に、決定の記録の出どころを書く（「決定を記録した commit:reviews/ のファイル名」と「見出しの行から `## ` を除いた全体」を空白でつないだ文字列）。**仮の値どおりに承認された場合も、必ず書く。** 出どころが無ければ、状態 `optional_choice_status()` は "undecided" のままで、出力の JSON にもそう出る。状態は出どころの有無から計算し、直書きしない。封印係は "undecided" の出力の封印を拒む（封印係への申し送り）。
3. `tests/stats/test_exclusion.py` の `OWNER_CHOICE` を、同じ値に直す。テストが次を確かめる。
   - `test_owner_choice`：`ENABLED_OPTIONAL_CATEGORIES` と `OWNER_CHOICE` が同じで、出力の JSON の `enabled_optional_categories`・`owner_choice_source`・`optional_choice_status` がそれに合うこと。
   - `test_owner_choice_source`：出どころの commit の版のファイルを `git show` で読み、見出しの行の全体が一致する見出しがちょうど一つあり、その節にオーナーの決定の文（原文の引用）が含まれること。決定の文は、オーナーの発言の原文をテストに書き写す。作業中の reviews/ は読まない。
   - `test_owner_section_exact_heading`：同じ日の別の見出し（前方一致する見出しを含む）が追記されても、節が変わらないこと。
   - `test_status_is_computed_from_source`：出どころを消すと "undecided" になること。
4. ほかのテストは直さない。規則そのもののテスト（既知の例、1cb463a の語の後戻り、くっつき一致など）は、選べる区分をすべて有効にした状態（`ALL`）で行っており、オーナーの選択に依らない。
5. 選択で結果が変わる例は、下の表のとおり。テスト `test_option_sensitive_examples` が、区分を有効にすれば外れ、外せば残ることを確かめる。選択を変えても、この表とテストは直さない。
6. 開示：
   - 0章の7・8 の答えと、`ENABLED_OPTIONAL_CATEGORIES` と `OWNER_CHOICE_SOURCE` の値は、除外の規則の出力の JSON に入り、そのまま封印される。
   - 区分表の取得のあと（順番5）、オーナーの選択どおりの設定と、選べる区分をすべて有効にした設定の両方で `build_tag_list()` を実行し、`compare_lists()` で出入りしたテーマを公開する。呼び方は次のとおり（入力は同じものを渡す）。
     ```
     chosen = tagrules.build_tag_list(themes, counts, totals, missing, start, end)
     allset = tagrules.build_tag_list(themes, counts, totals, missing, start, end,
                                      optional=tagrules.OPTIONAL_CATEGORIES)
     moved = tagrules.compare_lists(allset, chosen)
     ```
     一つ目は `optional` を渡さないので、`ENABLED_OPTIONAL_CATEGORIES`（オーナーの選択）を使う。どちらの戻り値にも、使った設定が `enabled_optional_categories` として入る（テスト `test_two_settings_distinguishable`）。`compare_lists()` は、二つが同じ入力（区画・欠けた日でない日の数 `usable_day_count`・四半期・a・n_med・テーマの集合と、テーマごとの四半期の件数 `quarter_counts`・平均の比率・区分表にあるか）から作られたことを確かめ、一つでも違えば止まる（テスト `test_compare_lists_checks_usable_days_and_quarter_counts`）。戻り値には、両方の `enabled_optional_categories` が入る（テスト `test_compare_lists_requires_same_input`）。三つ（chosen、allset、moved）をすべて封印の記録に入れて公開する。
   - 採点に使うのは、オーナーの選択どおりの一覧だけ。比べた結果を見て、選択を変えない。
7. 今回（2026-10-08）の反映：案B と民族・宗教の集団の追加により、`ENABLED_OPTIONAL_CATEGORIES` を仮の値（両方を有効）から `("ethnic_religious_group",)` に変えた。`OWNER_CHOICE_SOURCE` は "2d23cdf:reviews/T-020.md 2026-10-08 オーナーの発言（原文のまま記録）" である（T-022。差し戻し1回目で、commit を付け、見出しを行の全体にした）。

<!-- table:option-sensitive -->
| 区分を外すと残る例 | 名前 |
|---|---|
| disease_named | BIRDFLU, SWINEFLU, AB_EBOLA, AB_COVID19, AB_CHOLERA_X, SARSCOV2 |
| ethnic_religious_group | AB_ETHNICITY_X, AB_TRIBAL_LAND, AB_RELIGIOUS_X |

## 3. 素朴な予測の設計

T-022 の差し戻し3回目で、この章を `docs/stats/naive-scoring.md` の 3章に移した（中身は同じ。章と節の番号もそのまま）。この文書の中の「3章」の参照は、移した先の 3章を指す。移した理由は 5章 (2)。

## 4. 採点計画のうち、このタスクで決めるもの

この章も `docs/stats/naive-scoring.md` の 4章に移した（中身と番号は同じ）。この文書の中の「4章」の参照は、移した先の 4章を指す。

## 5. 封印の手順と順番（封印係への申し送り）

封印は封印係の仕組みで行う。記録の種類（kind）の名前と照合の仕組みは、封印係が決める。統計係からの提案は次のとおり（T-022 で整理した）。

| 順番 | 封印するもの | 時機 |
|---|---|---|
| 1 | **除外の規則と入れる規則**：`src/stats/exclusion.py` とその出力（JSON）、`tests/stats/test_exclusion.py`、`src/stats/tagrules.py`（K = 10、MIN_COUNT_PER_QUARTER = 1、四半期の規則、A の式、存在の条件）とその出力、`tests/stats/test_tagrules.py`、この文書。比べるための **1cb463a の版**（`git show 1cb463a:src/stats/tagrules.py` とその出力）。オーナーの決定の記録（`git show 2d23cdf:reviews/T-020.md`）。対象と sha256 は `docs/stats/seal-order1.md` の表 | 0章の「承認をお願いすること」の承認のあと。テーマの区分表の取得（T-018 の acquisition-start）と method-access より前に、必ず封印する |
| 2 | 報道量の数え方（r(d) の分子と分母の単位。収集係が決める） | オーナーの以前の決定で「試運転のあとで決める」。3 と同時か、3 より前 |
| 3 | **数え方とのつながり**：順番1の記録（seq と sha256）と順番2の記録への参照と、その数え方で K を何と読むか（1章 (2)）。入れる規則の定数と式は足さない・変えない | 2 の封印のあと（同時でもよい）。4・5 より前 |
| 4 | 手法を作る期間の区画の欠けた日の一覧（candidates.md 3章 (5)） | 5 より前 |
| 5 | タグの一覧の結果（`build_tag_list()` の出力。A = V、テーマごとの判定と理由を含む）、1 と 3 の記録の参照、入力のデータのハッシュ、二つの版と二つの設定の比べた結果 | 3・4 のあと、モデルより前 |
| 6 | 冷却と「対象なし」の規則の改訂（4章 (3)。あれば） | 最初の threshold-access より前 |
| 7 | `naive_history_days = 399`（periods のきっかけの値） | 最初の threshold-access より前 |
| 8 | 素朴な予測の最後の版（`src/stats/naive.py`、`src/stats/scoring.py` とその出力）と、21組の係数 | 最初の threshold-access より前 |

**(1) 入れる規則を順番1で封印してよいか（判断：封印してよい。先に封印するべきである）**

T-022 の初回の提出では、K を数え方の封印のあと（順番3）に回していた。その判断の前提3 は、結論を支えていなかった（監査 M-1）。次のとおり直す。

- 前提1：除外の規則は、テーマの名前と説明の語だけで決まる（2章）。報道量の数え方にも K にも依らない。
- 前提2：入れる規則の式（A = K ÷ N_med、平均 r(d) ≥ A、各四半期に MIN_COUNT_PER_QUARTER 件以上）は、r(d) の分子と分母がどの数え方で数えられても、同じ形で計算できる。K は「r(d) の分子の単位で1日あたり」と読むので、数え方が決まっていなくても値として定まる（1章 (2)）。
- 前提3：数え方は、オーナーの以前の決定（reviews/T-001.md）で試運転のあとに決める。これは K をいつ封印しても変わらない。
- 前提4：区分表と手法を作る期間のデータを見たあとに K を封印すると、数え方に加えて K も、データを見てから選べる。先に封印すれば、選べるのは数え方だけになる。
- 前提2 から、K を数え方より先に封印することは、技術的にできる。前提3・4 から、先に封印しても選ぶ自由は増えず、後に回すと K の分だけ増える。よって、入れる規則の定数と式を、除外の規則と同じ順番1で、区分表の取得と method-access より前に封印する。
- 前提2 から、順番3で足すのは数え方とのつながり（その数え方で K を何と読むか）だけで足りる。
- 残る自由：数え方を選ぶことで、K = 10 が記事の何件に当たるか（したがって A）は動く。この自由は K の封印の時機に依らない（前提3）。対策は 0章の B（オーナーの判断待ち）。前回の提出の「試運転で `build_tag_list()` を動かさない」は、目的を果たさないので取り下げた。
  - どの場合も、順番5の記録に、その数え方で全体の報道量の中央値 N_med と A を載せ、K = 10 が何に当たるかを読めるようにする（1章 (2) の「V は比率で固定される」と同じ扱い）。
- 除外の規則は K に依らず（前提1）、A と存在の条件は除外の規則に依らない（1章 (1)(2)）。二つのファイル（`exclusion.py` と `tagrules.py`）に分けたままにするが、封印は同じ順番1で行う。CLAUDE.md の「入れる規則・除外する規則・その結果の一覧を、まとめて封印する」は、規則の二つを順番1で、結果を順番5で封印し、順番5の記録に順番1と3の記録（seq と sha256）を参照として入れて満たす。
- `tagrules.py` は `exclusion.py` を読み込んで使い、出力の中に除外の規則の出力をそのまま入れる（テスト `test_tagrules_output`）。除外の規則のコードと出力には K の値が入っていない（テスト `test_no_k_in_output`）。
- 1cb463a の版の `tagrules.py` にも K = 10 が入っているが、順番1でのこのファイルの封印は比べるためのもので、採用する記録ではない。採用するのは、今の版の `tagrules.py` とその出力である。

**順番1の対象と sha256**：`docs/stats/seal-order1.md`（封印係への申し送り）の表にまとめた。この文書自身も対象なので、この文書の中には sha256 を書かない（自分の sha256 は自分の中に書けないため）。表は、テスト `test_seal_targets`（`tests/stats/test_t019.py`）が、今のファイルと git の履歴から計算し直して照合する。

- 順番1で封印するテスト（`test_exclusion.py`、`test_tagrules.py`）が読むのは、順番1の対象（`exclusion.py`、`tagrules.py`、この文書）と、git の履歴の `2d23cdf:reviews/T-020.md`（`git show`）だけにする。作業中の reviews/ と、申し送りの文書と、`naive-scoring.md` は読まない。これを二つの方法で確かめる（どちらも `tests/stats/test_t019.py`）。
  - 実行の見張り（`test_sealed_tests_read_only_targets`）：二つのテストを子プロセスで流し、Python の audit hook で次の事象を集め、許可リストと照らす。開いたファイル（書き込みは一切認めない。読むのは対象の5つのファイルだけ）、フォルダの一覧（import の仕組みが読む sys.path のフォルダだけ）、`subprocess.Popen`（引数・cwd・環境変数の差がすべて許可リストと同じこと）、`_posixsubprocess.fork_exec`（Popen を通った起動と数が合うこと）、リンクの作成・ctypes・通信・ほかのプロセスの起こし方（一件でもあれば失敗）。パスは事象が起きた時点で realpath にするので、リンクを通して開けば指す先が記録される。見張りの一時のフォルダの中のファイルも、sitecustomize と pyc の置き場のほかは数える。
  - ソースの検査（`test_sealed_tests_source`）：二つのテストのソースを ast で調べ、使ってよいモジュール（ast、datetime、fractions、hashlib、json、os、random、subprocess、sys、unittest、exclusion、tagrules）と、os・subprocess・sys の使い方（`os.path.join`・`os.path.dirname`・`os.path.abspath`、子プロセスに渡す `dict(os.environ, ...)`、`subprocess.run`、`sys.executable`、`sys.path.insert`）を許可リストに限る。`from ... import`、`__import__`・`eval`・`exec`・`getattr` などの名前、`__dict__` などの属性、`STATS_` を含む文字列（見張りの環境変数の名前）は禁じる。audit hook で見えない読み方（`os.stat`、`os.path.exists` など）と、見張りの有無で振る舞いを変える書き方は、ここで止まる。
  - 回り道の例（監査が試した `_posixsubprocess.fork_exec`、`multiprocessing` の `spawnv_passfds`、ctypes、見張りの一時のフォルダへのリンク、環境変数の有無による分岐、`os.listdir`・`os.stat`・`os.path.exists` による分岐、許可した引数に別の env や cwd を渡すもの）を写しに足すと、どれもソースの検査か実行の見張りで止まることを、テスト `test_detours_are_caught_by_source_check` と `test_detours_are_caught_by_audit` で確かめる。
- 限界（二つの方法で塞げないもの）：
  - ソースの検査は、書かれた形を見る。許可した `subprocess.run` や `open` に、実行時に計算した値を渡す読み方は、ソースの検査では止まらない。それは実行の見張りで止まる（読んだパスと起動した引数を記録するため）。
  - 実行の見張りは、Python の audit hook を通る事象だけを見る。許可したモジュールの中の C のコードが、audit の事象を出さずにファイルを読む場合は見えない。ctypes と `_posixsubprocess` はソースの検査で禁じ、使えば ctypes の事象（`ctypes.dlopen` など）でも記録される。
  - 見張りのログは、テストと同じプロセスの中にある。ログのファイル記述子を探して書き換えるような書き方は、ソースの検査（禁じた名前・属性・`os` の使い方）で止まる形にしたが、許可したモジュールの組み合わせで同じことができないとは証明していない。
  - 見張りは、テストを流したその一回について確かめる。封印係が封印する commit で、このテストを流すこと（`docs/stats/seal-order1.md` 2章の項目9）。

**(2) 順番1のあと、この文書を凍結する（判断：凍結し、順番2以降は別の文書に書く）**

順番1で封印するテスト（`test_exclusion.py`、`test_tagrules.py`）は、作業ツリーのこの文書の表（terms、known-examples、option-sensitive、tag-constants）を読む。この文書には、順番3以降や素朴な予測の改訂（順番6・8）で直したくなる章（もとの3章・4章と、5章）も入っていた（T-022 の監査 M-3）。二つの直し方を比べた。

- 前提1：封印するテストのファイルに、そのファイル自身を含む commit の ID は書けない（ID はファイルの中身から決まる）。封印の commit の版を基準にするには、ID をテストの外から渡す（環境変数など）か、一つ前の commit を指す必要がある。
- 前提2：外から ID を渡す形では、どの commit を渡すかを、テストを流す人が選べる。違う commit を渡しても、テストはそれに合わせて通る。
- 前提2b：一つ前の commit を指す形なら選ぶ余地は無い。ただし、作業ツリーのこの文書は封印のあとも直せるので、封印した規則を説明する章（1章・2章）が、封印した版と作業ツリーの版の二つになる。読む人がどちらを見ているかは、ファイルからは分からない。封印するテストに `git show` がもう一つ増える。
- 前提3：この文書を凍結すれば、封印したテストが読むのは、封印したときと同じバイト列の文書だけになる。凍結は、封印するテスト `test_tagrules.py` の中の定数 `TAGS_NAIVE_SHA256` で確かめる（テスト `test_doc_is_frozen`）。この文書を直せば、このテストが失敗する。定数のほうを直せば `test_tagrules.py` のバイト列が変わり、順番1の封印の記録にある `test_tagrules.py` の sha256 と合わなくなる。封印していない表（`docs/stats/seal-order1.md`）とテスト（`test_t019.py`）だけに頼らず、封印の記録との照合で見つけられる（照らす手順は `docs/stats/seal-order1.md` 3章）。
- 前提4：T-022 の差し戻し2回目までは、封印しない `test_t019.py` が、この文書の3章・4章の表（naive-features、naive-constants、lookback、scoring-constants）を `naive.py`・`scoring.py` の定数と照らしていた。3章・4章は最初の threshold-access より前なら改訂できる（0章13・17）。そのため、凍結すると、改訂した定数と凍結した表が食い違い、`test_t019.py` が失敗するか、表を直して凍結を破るかのどちらかになっていた（T-022 の監査 M-2）。
- 前提4b：差し戻し3回目で、3章・4章を中身と番号を変えずに `docs/stats/naive-scoring.md` に移し、`test_t019.py` はそちらを読むようにした。移したあと、この文書を読むのは、封印する二つのテスト（1章・2章の表と、この文書の sha256）と、封印の対象の sha256 を計算する `test_seal_targets` だけである。
- 前提4c：順番3以降に書くこと（数え方とのつながり、素朴な予測と採点の改訂、採点計画の残り）は、1章・2章の表を変えない（入れる規則の定数と式、除外の規則は、順番3以降で変えない。1章 (2)、5章 (1)）。
- 前提1・2 から、ID を外から渡す形は、選ぶ余地（どの commit を渡すか）を一つ増やす。前提2b から、一つ前の commit を指す形は、封印した説明と作業ツリーの説明を二つにする。前提3・4b・4c から、凍結する形はどちらも起こさず、順番3以降の作業も妨げない。前提4 の食い違いは、前提4b の移しで無くなった。よって、**順番1の封印のあと、この文書は直さない。** 順番2以降の決定と改訂は、docs/stats/ の新しい文書に書き、その文書がこの文書のどの章を置き換えるかを書く。
- 凍結のあとで、この文書の誤りに気づいた場合も直さない。新しい文書に訂正として書き、公開する。
- 凍結の前（順番1の封印の前）に、0章の A・B のオーナーの判断を、この文書に書き入れる。書き入れたら、`test_tagrules.py` の `TAGS_NAIVE_SHA256` と sha256 の表を作り直す（統計係の作業）。

- **二つの版の封印と比べ方**：順番1で、最終の版に加えて 1cb463a の版も封印する。統計係と監査係が記憶にある名前で照合を試したあとに語と規則が変わったので、変わる前の版の結果も並べて示せるようにするため。順番5で次を行う。
  1. 区分表と手法を作る期間のデータを取得したあと、同じ入力で、最終の版の `build_tag_list()` と、1cb463a の版の `build_tag_list()` を両方実行する。1cb463a の版は、git の履歴からそのファイルを取り出して実行する（区分は1cb463a の版の定義のまま）。
  2. `compare_lists()` で、片方の版だけで一覧に入ったテーマを出す。`compare_lists()` は二つが同じ入力から作られたことを確かめる。1cb463a の版の結果には設定の値が無いので、`enabled_optional_categories` の old は None になる。
  3. 二つの版の出力と、出入りしたテーマの一覧を、順番5の記録に入れて封印し、公開する。0e14f3b の版と 247fc1d の版も、同じ手順で計算して公開する（封印の対象にはしない。git の履歴で時刻が分かる）。
  4. 二つの設定（オーナーの選択どおりと、選べる区分をすべて有効）の比べた結果も、同じ記録に入れる（2章 (8) の手順6）。
  5. 採点に使うのは最終の版で、オーナーの選択どおりの一覧だけ。比べた結果を見て、版や設定を選び直すことはしない。
- 検証の手順（docs/verify/）で、5 の結果が、封印した規則のコードと封印した入力から同じに再計算できることを確かめる手順を作ることを提案する。

## 6. 方針書との関係
- 民族・宗教の集団の区分は、尋ねたときは CLAUDE.md の5つの区分の外だった。2026-10-08 のオーナーの決定で加わり、CLAUDE.md の「除外する規則」にもリードが書き足した。今は CLAUDE.md の区分の一つである。
- 病名の区分（disease_named）は、CLAUDE.md の「災害・感染症」の範囲だが、語を知識から選んだ点でオーナーの選択に委ね、オーナーは使わないこと（案B）を選んだ。CLAUDE.md の書き足しにも「病名は使わず一般の語だけで照合する」とある。
- 一度跳ねたタグの冷却は、CLAUDE.md の「予言の対象」に条件を一つ足すことになる。CLAUDE.md の「採点計画で必ず扱うこと」が、この扱いを採点計画で決めるとしているので、その範囲の提案とした。オーナーは承認した（0章15）。
- 除外の規則と入れる規則は、別のファイルだが同じ順番1で封印する。結果の一覧は順番5で封印し、その記録に順番1と3の記録を参照として入れる。CLAUDE.md の「入れる規則・除外する規則・その結果の一覧を、まとめて封印する」は、この参照で満たす形にした（5章）。
- それ以外は、CLAUDE.md と docs/method.md の範囲で決めた。

## 7. 使った情報（データを見ていないことの宣言）
- 次の文書と発言だけを使った。
  - CLAUDE.md（2026-10-08 にリードが「除外する規則」を書き足した版を含む）、docs/method.md、docs/stats/periods.md、docs/stats/candidates.md、src/stats/periods.py、src/stats/candidates.py
  - reviews/T-001.md・T-004.md・T-011.md・T-016.md（オーナーの発言と申し送り）
  - reviews/T-019.md（採点と差し戻しの指示。監査係の所見と、監査係が作った名前の例を含む）
  - reviews/T-020.md（採点と差し戻しの指示、2026-10-08 のオーナーの決定）
  - reviews/T-022.md（採点と差し戻しの指示）、reviews/T-001.md の数え方についてのオーナーの発言、src/sealer/ledger.py と sealed/ の記録の種類（封印係への申し送りのため。データではない）
  - 1cb463a・0e14f3b・247fc1d・ecd745f・2f4b3ce の自分のコードと文書（版の差分を作るため）
- GDELT のデータ、ファイル一覧、テーマの区分表、GDELT のどのページにもアクセスしていない。ネットワークは使っていない。
- 4つのコード（exclusion.py、tagrules.py、naive.py、scoring.py）は、データのファイルを開かず、現在の日時を読まない（テスト `TestNoDataNoNetwork`、`TestExclusionNoDataNoNetwork`、`TestTagrulesNoDataNoNetwork`）。封印する二つのテストが読むものは、5章 (1) のあとの段落のとおり確かめる。テストの `test_owner_choice_source` は、git の履歴の 2d23cdf の版の reviews/T-020.md を `git show` で読む（作業中のファイルは読まない）。これはオーナーの決定の記録で、データではない。`test_t019.py` の `test_seal_targets` は `docs/stats/seal-order1.md` と git の履歴を読む。

**語の一覧に入った知識**（区分表は見ていないが、次の知識が語の選び方に入った）：
- 英語の語彙。
- **病名は、過去の流行の知識から選んだ。** EBOLA、ZIKA、COVID、SARS、MERS、H1N1、H5N1 などは、実際に大きく報じられた流行を知っていたから挙げた語である。そのため、病名の区分を使うかを案A・案Bとしてオーナーに選んでもらい、オーナーは使わないこと（案B）を選んだ（2章 (4)）。今の設定では、この知識は除外の判定に入らない。
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
