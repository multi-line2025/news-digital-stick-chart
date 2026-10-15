# 順番5：タグの一覧の結果（T-109、T-110）

文書の版：`order5-tag-list-v2`

この文書は、順番5（タグの一覧の結果）で何を計算し、どの形で出すかを、封じた決まりの行を引いて並べる。
新しい決まりは足さない。計算のコードは `src/stats/order5.py`、テストは `tests/stats/test_order5.py`。
封印は封印係が行う。統計係はこの文書とコードを作るだけで、封印しない。

- T-109（この文書とコードを作ったタスク）と T-110（出力の作り直しと流し方の書き直し）では、本物のデータで流していない。
  日の集計も、区分表のファイルも開いていない。テストは合成の正式な run・合成の欠けた日・合成の区分表だけを使う。
- **順番5は手で流さない。** 封印係の入口の中で流し、書いてコミットするまで結果を表示しない（4章。reviews/T-109.md の
  リードの判断、中-1 への対処）。
- v1（T-109）からの変更：Git に入れる本体（main）を絞り、一覧の全体を Git の外のファイル（detail・extra）に移した
  （リードの判断4・6）。流し方を封印係の入口の形にし、第三者が order5.py に頼らずに計算し直す手順を5章に書いた。

引く文書と、行の番号の版（どれも封印済み。文言は変えない）：

| 文書 | sha256 | 封印 |
|---|---|---|
| docs/stats/tags-naive.md | `9405ffb9a7a2c89e1bfa8271ad5773d55825b17bbd6a1552d52151de20f664b5` | 順番1（seq 5） |
| docs/stats/counting.md | `5cd1499cca2618db4c891818135a0e64132a7bd229d9f7d29540dac6f60b6b44` | 順番1b（seq 6） |
| docs/stats/seal-order1.md | `cf6692bdaa492da4a6247434d13890259be83281d4b7ff955827789b215544fb` | 順番1b（seq 6） |
| docs/stats/missing-days-method.md | `bafe4d0c3e6f50ce841e5153b05bdf79d93a18b67736b319823fd1317b4a1dd7` | 順番4（seq 15） |

## 1. 引いた決まり

順番5の中身を決める行は次のとおり（行の番号は上の版のもの）。

- **tags-naive.md 370行**（5章の表の順番5の行）：「タグの一覧の結果（`build_tag_list()` の出力。A = V、テーマごとの判定と理由を含む）、1 と 1b と 3 の記録の参照、入力のデータのハッシュ、二つの版と二つの設定の比べた結果、順番1b で封印した候補のすべての数え方での一覧と N_med・A、すべての基準の案（採用した数え方の一覧と並べ、正式な結果は一つだけ。ほかは「比べるための参考で、正式ではない」と明記する。0章の B (ii)）」。時機は「3・4 のあと、モデルより前」。
- **counting.md 85行**（370行の置き換え）：候補のすべての数え方（C1〜C7）で一覧を作って並べ、正式な結果は C7 の一つだけ。参考の候補が計算できない場合は「計算できない（理由）」と記録して止めない。欄の手厚さを入れる。
- **tags-naive.md 423〜428行**（二つの版の比べ方）：
  1. 同じ入力で、最終の版と 1cb463a の版の `build_tag_list()` を両方実行する。1cb463a の版は git の履歴から取り出して実行する（区分は 1cb463a の版の定義のまま）。
  2. `compare_lists()` で、片方の版だけで一覧に入ったテーマを出す。1cb463a の版の結果には設定の値が無いので、old は None になる。
  3. 二つの版の出力と、出入りしたテーマの一覧を順番5の記録に入れる。0e14f3b の版と 247fc1d の版も、同じ手順で計算して公開する（封印の対象にはしない。git の履歴で時刻が分かる）。
  4. 二つの設定（オーナーの選択どおりと、選べる区分をすべて有効）の比べた結果も、同じ記録に入れる。
  5. 採点に使うのは最終の版で、オーナーの選択どおりの一覧だけ。
- **tags-naive.md 334〜342行**（2章 (8) の手順6）：二つの設定の呼び方（`chosen` は `optional` を渡さない、`allset` は `optional=tagrules.OPTIONAL_CATEGORIES`、`moved = compare_lists(allset, chosen)`）。三つ（chosen、allset、moved）をすべて記録に入れる。
- **tags-naive.md 151〜154行**（1章 (3)）：対象のテーマは、区分表に載っているテーマと、手法を作る期間のデータに現れたテーマを合わせたもの。入力は手法を作る期間の区画のデータだけ。欠けた日は封印した一覧を使い、存在の条件にも平均にも入れない。出力には、テーマごとの四半期ごとの件数、平均、A 以上か、一致した除外の語、一覧に入ったかを載せ、一覧に入らなかったテーマとその理由もすべて公開する。
- **tags-naive.md 136〜140行**（1章 (2)）：A = K ÷ N_med、K = 10。N_med は欠けた日でない日の全体の報道量（r(d) の分母）の中央値。V = A。
- **tags-naive.md 123〜126行**（1章 (1)）：暦の四半期ごとに、欠けた日でない日の報道量の合計が1件以上。欠けた日でない日が一日も無い四半期は条件から外し、番号を出力に残す。
- **tags-naive.md 159行**：説明が無ければ名前だけで照合する。
- **seal-order1.md 143行**：順番5の記録には、順番1・1b・3 の記録の seq と sha256、候補のすべての数え方（C1〜C7）での一覧と N_med・A、封印したすべての参考の基準の案が入る（数と識別子が順番1b の記録と一致すること）。正式な結果はちょうど一つに印され、ほかの候補の結果と基準の案には「比べるための参考で、正式ではない」が付く。欄の手厚さを、手法を作る期間の暦の四半期ごとと期間全体について入れる。欠けた日でない日に C7 の分母が 0 の日があれば順番5を封印せず止める（ほかの候補に代えない）。参考の候補（C1〜C6）の分母が 0 の日があれば、その候補を「計算できない（理由と日の一覧）」と記録して並べ、順番5は止めない。
- **counting.md 125行**：7つの候補すべてで `build_tag_list()` を実行し、候補ごとの一覧と N_med・A を並べる。
- **counting.md 259行・261行**：上の 143行と同じ止まり方（`counting.order5_candidate_status()`）。
- **counting.md 279行**：欄の手厚さは、正式な run の手法を作る期間について、暦の四半期ごと（`tagrules.quarters()` の区切り）と期間全体の、欠けた日でない日の合計。値は 276行（S の行の `docs_without_v1_theme`・`docs_without_v2_theme`・`docs_without_any_theme` と、すべての組の D の和 `docs_all_groups`。割合はそれぞれを `docs_all_groups` で割ったもの）。
- **counting.md 234行**：順番2が止まった場合だけ、参考の基準の結果を順番5で出す。順番2（seq 10）は `decided` で止まっていないので、参考の基準の結果は seq 10 の記録から写す（下の 2章の 9。reviews/T-109.md のリードの判断1）。
- **missing-days-method.md 141〜142行**（6章）：順番5の記録は、参照に順番4の記録（seq と出力の sha256）を入れる。欠けた日の比率は値なし。どの日が欠けた日かは順番4の一覧だけで決め、順番5の中で数え直さない。
- **reviews/T-085.md のリードの判断 2**：順番5の参照に順番4を入れる。
- **reviews/T-109.md のリードの判断4・6**：Git に入れて封印する本体は、正式な一覧、各候補の要約、欄の手厚さ、区分表の数、参照に絞る。すべて有効の設定と 1cb463a の版は、比較の要約（差の件数と差のあるテーマの名前）だけを本体に入れる。一覧の全体と 0e14f3b・247fc1d の版の結果は Git の外に置き、sha256 を本体に入れる。
- **reviews/T-107.md の監査の中-1**：記号を含むテーマ名は区分表には入るが、取得のときの `THEME_RE`（古い形）に合わず日の集計に数えられない。順番5の出力と文書に、この数と限界を出す。

## 2. 計算するもの

正式な結果は、**C7・今の版・オーナーの選択どおりの設定**の一覧の一つだけ。ほかはすべて「比べるための参考で、正式ではない」。

| | 計算するもの | 版 | 設定 | 数え方 | main（Git に入れる） | Git の外 |
|---|---|---|---|---|---|---|
| 1 | 正式な一覧 | 今の版 | オーナーの選択 | C7 | `official`：一覧と、テーマごとの行を除いた値（A・N_med・四半期など）、理由ごとの件数 | detail の `official_result`（`build_tag_list()` の出力の全体） |
| 2 | すべて有効の設定の一覧と `compare_lists(allset, chosen)` | 今の版 | すべて有効 | C7 | `comparisons.allset`：差のあるテーマの名前と差の件数 | detail の `allset_result` |
| 3 | 1cb463a の版の一覧と `compare_lists(1cb463a, chosen)` | 1cb463a | 版の既定 | C7 | `comparisons.1cb463a`：同上 | detail の `versions.1cb463a` |
| 4 | 0e14f3b・247fc1d の版の一覧と比較 | 0e14f3b・247fc1d | 版の既定 | C7 | sha256 だけ（`outside.extra`） | extra（封印の対象にしない） |
| 5 | 候補ごとの要約（N_med・A・status・一覧の件数） | 今の版 | オーナーの選択 | C1〜C7 | `candidates` | detail の `candidate_lists`（候補ごとの一覧） |
| 6 | 欄の手厚さ（四半期ごとと期間全体） | — | — | — | `coverage` | — |
| 7 | 区分表の数（記号を含む名前の数と一覧を含む） | — | — | — | `themes_table` | — |
| 8 | 欠けた日（順番4の一覧から写す） | — | — | — | `missing_days` | — |
| 9 | 参考の基準の案 B1〜B5 の結果（順番2の記録 seq 10 から写す） | — | — | — | `reference_criteria` | — |
| 10 | 参照と入力のハッシュ、Git の外のファイルの sha256、引用 | — | — | — | `refs`・`code`・`input`・`outside`・`citation` | — |

**比べる各版の既定**（軽-4。どの版の `build_tag_list()` にも、このコードは設定を渡さない。版の定義のまま実行する）：

| 版 | 除外に使う区分 | 照合のしかた |
|---|---|---|
| 今の版（正式） | 5つの区分（`disease_named` を除く）と `ethnic_religious_group`。`exclusion.ENABLED_OPTIONAL_CATEGORIES = ("ethnic_religious_group",)`（オーナーの決定 2026-10-08） | 完全一致・形の変化・名前の欄だけのくっつき一致（tags-naive.md 2章） |
| 今の版・すべて有効（2） | 上に `disease_named` を足したもの（`optional=tagrules.OPTIONAL_CATEGORIES`、つまり `("disease_named", "ethnic_religious_group")`） | 同上 |
| 1cb463a | その版の `CLAUDE_CATEGORIES`（politics_election・conflict_violence・crime・specific_person・disaster_disease。病名を含む）と `EXTRA_CATEGORIES_NEEDING_APPROVAL`（ethnic_religious_group）のすべて。設定の引数は無い | 語の完全一致だけ（形の変化・くっつき一致は無い） |
| 0e14f3b | その版の `ENABLED_OPTIONAL_CATEGORIES = ("disease_named", "ethnic_religious_group")`（当時の仮の値。両方とも有効） | 形の変化と、名前と説明の両方に掛かるくっつき一致（5文字以上） |
| 247fc1d | 同じく `("disease_named", "ethnic_religious_group")`（両方とも有効） | 形の変化と、名前の欄だけのくっつき一致（先頭6文字以上・末尾は残り4文字以上） |

- 1cb463a の版の結果には `enabled_optional_categories` が無いので、比較の `enabled_optional_categories.old` は None になる（tags-naive.md 425行）。0e14f3b・247fc1d も同じ。
- 2〜5 は、1 と同じ入力（区分表の名前、同じ日の集計、同じ欠けた日、同じ区画）で計算する。`compare_lists()` は、二つが同じ入力から作られたことを確かめ、違えば止まる。
- 5 で計算できない参考の候補は、`build_tag_list()` を呼ばず、`status: "not_computable"`、理由、分母が 0 の日を記録する（要約の N_med・A・件数は null）。C7 が `stop` なら、一覧を一つも作らず、`status: "stopped"` の main だけを出す（detail・extra は出さない）。
- 7 の「日の集計の名前の形に合わない名前」は、区分表の名前のうち `\A[A-Z][A-Z0-9_]{0,159}\Z`（`counting.THEME_NAME_RE`。`gkg.THEME_RE` と同じ形）に合わないもの。日の集計に数えられないので件数は 0 で、存在の条件で一覧に入らない（T-107 の監査の中-1）。T-106 の診断では36個と見込まれている（reviews/T-098.md）。main が数と名前の一覧を出す。
- 9：順番2は `decided`（seq 10）なので、試しの run の3日（2015-03-02〜04）で計算済みの B1〜B5 の結果を写す。写す前に、結果のキーがちょうど B1〜B5（`counting.CRITERIA_IDS`）で、どれも `official: false` であることを確かめる。候補と基準の案の識別子が、順番1b の記録の `candidate_ids`・`criteria_ids` と同じことも確かめる。

## 3. 入力と照合

照合に一つでも合わなければ、何も書かずに止まる。順は次のとおりで、前の照合が通るまで次のものを読まない（テスト `test_source_shape`）。

1. **コード**（T-096 と同じ形）：`periods.py`・`exclusion.py`・`tagrules.py`・`counting.py` は、ファイルを1回だけ読み、そのバイト列の sha256 を確かめ、同じバイト列を compile して使う（`__pycache__` の古い .pyc を読まない。テスト `TestStalePycIgnored`）。`tagrules.py` が読み込む `exclusion` も、照らしたバイト列から作ったものにする。

   | ファイル | sha256 | 照らす記録の欄 |
   |---|---|---|
   | `src/stats/periods.py` | `81de229d065196a26e15d90c5a80eb1043ca534a6eaf66cdebd36285ae087605` | seq 1（periods）の targets の role `code` |
   | `src/stats/exclusion.py` | `22bc0ed138a42b95c36797bbe5b41163c871af14f32be590dafde20fe16fdd1d` | seq 5（stats-order1）の中身の targets |
   | `src/stats/tagrules.py` | `63b0e005ce85344675651264b4a14453a167a28d56d3333a7503b55db04218ee` | seq 5（stats-order1）の中身の targets |
   | `src/stats/counting.py` | `6f25985b21cd8ac93680b81308f3d1860b4ae6496577e10141d1e17ecf8c9fd3` | seq 6（stats-order1b）の中身の files |
   | `1cb463a:src/stats/tagrules.py` | `f7c325cb21bcf39c42e6d785deacbe47eacec7fb2834d2927634e446b62ce57a` | seq 5（stats-order1）の中身の targets |

2. **比べる版**：`git show <commit>:src/stats/tagrules.py` のバイト列の sha256 を照らしてから実行する。git のリポジトリは引数 `--repo` で渡す（無ければ order5.py のあるプロジェクト）。バイト列を sha256 で照らすので、どのリポジトリから取っても結果は変わらない。

   | 版 | commit | sha256 | 封印の対象 |
   |---|---|---|---|
   | 1cb463a | `1cb463acfcf15ba315e6c454625ad681e86bbc2a` | `f7c325cb21bcf39c42e6d785deacbe47eacec7fb2834d2927634e446b62ce57a` | seq 5 |
   | 0e14f3b | `0e14f3b36f012098fc53d9456e6c4d9d5231e43b` | `8ed1613885d7e64ebdca47c97c4781fa3b42f735b37e91901321a38ef8328956` | しない（426行） |
   | 247fc1d | `247fc1de62e32322207f9576480deb9536eb8dd5` | `3a688f94c1aff8e67a2d8e94072e29569f15699be2f569b7840dea22635a70ba` | しない（426行） |

3. **day の行**：`src/collector/gkg.py` の `official_day_records()` だけから取る（関門 `ledger.require_gkg_run_result("official", run_id)`。seq 12）。関門を通らなければ、マニフェストも日の集計も区分表も読まない（テスト `TestGateEndToEnd`）。
4. **封印の記録**：関門のあと、鎖とすべての .ots を検証した記録（`ledger._load_for_gate`）から読む。
   - 1 の表の値を、表の欄と照らす。
   - 順番3（stats-order3）はちょうど1件。その `ref_order1`・`ref_1b`・`ref_order2` を記録の行（seq と行の sha256）と照らす。順番1 はちょうど1件、順番1b は seq の最も大きいもので、どちらも順番3の参照と同じ。
   - 順番4（stats-order4）はちょうど1件で、seq 15、順番3より後。中身の `list` のバイト列（`ledger.order4_list_bytes` と同じ形）の sha256 が、中身の `list_sha256` と、決めた値 `6343bcc7d1ad2b406cdb2a5013b029a750c476f93098715f1a822831f283a35d` の両方と同じ。
   - 一覧の区画・run_id・gkg-run-result の seq と行の sha256・マニフェストのパスと行数と sha256 が、関門を通ったものと同じ。
   - 順番2 は順番3が参照したもの（seq 10）。その `ref_1b_seq` が参照する順番1b の seq と同じ。参考の基準の結果は 2章の 9 のとおり照らす（テスト `TestOrder2Criteria`）。
5. **区分表**：
   - マニフェスト `data/manifest/gdelt-themes.jsonl` を、封印係の照合 `ledger.check_themes_manifest_refs` に通す（行の形、並び、順番1の記録への参照）。最後の行がただ一つの result の行であること。
   - result の行の `sha256` が `21aef57175e66e3cb9e0ba574d0b7dc628f8f23f7ecb7a29498ad67b50ca9203`、`rows` が 59315、`kept_columns` が `["THEME"]`、`file_name` が `gdelt-themes-<時刻>.tsv` の形。
   - 引数 `--themes-store` の置き場所から `file_name` のファイルだけを開き（リンクをたどらない）、sha256 を result の行と照らす。頭の行が `THEME`、行の数が `rows`、どの名前も `\A[A-Z][\x21-\x60\x7B-\x7E]{0,159}\Z`（`themes.THEME_NAME_RE`。T-107 で広げた形）に合うこと。
   - git の履歴とマニフェストの照合（追記だけか、attempt のコードの版など）は、封印係の `verify` が行う。このコードは行わない。
6. **日の集計**：day の行の検査（区画の日にちょうど一つずつ、run_id が一つ、`file_name` が決まった名前、`sha256` の形）が通ってから、`file_name` のファイルだけを `--store` から開く。開いたバイト列の sha256 を day の行と照らす。`counting.parse_day()` が頭の行の日と mode を照らす。
7. **C7 の分母と順番4の一覧**：日ごとの C7 の分母が、順番4の一覧の `c7_denominator_by_day` と同じであることを確かめる。違えば止まる（日の集計が順番4のあとで変わったことになる）。欠けた日を数え直すことではない（リードの判断5）。

## 4. 流し方と出力の形

### (1) 手で流さない。封印係の入口の中で流す（中-1 への対処）
- 順番5は、封印係の入口（T-111 で作る）の中でだけ流す。統計係もリードも、order5.py を本物の入力で手で流さない。
- 封印係の入口は、順番4（`src/sealer/seal_order4.py`、`verify.run_order4`）と同じ形で、HEAD の版のファイル（`src/`・`sealed/`・`data/manifest/` の下）を git から**空のフォルダ**に取り出し、その中の `src/stats/order5.py` を流す。作業ツリーの order5.py は使わない。
- 流したあと、出力のファイルを書いて記録をコミットするまで、結果（一覧・件数・数）を画面に出さない。order5.py は、標準出力に書いたファイルの名前と sha256 だけを出し、標準エラーには開いたファイルの数と所要時間だけを出す（止まったときは止まった理由）。
- 理由（前提 → 結論）：前提1：order5.py は順番5の前に封じられていない。前提2：手で流して結果を見られると、結果を見てから order5.py を直してコミットし、そのあとで封印する道が残る（監査の中-1）。前提3：封印係の入口の中で HEAD の版を流し、書いてコミットするまで表示しなければ、結果を見る前に使ったコードの版がコミットに固定される。結論：手で流さず、封印係の入口の中で流す。直した版で流し直した場合も、入口の記録（封印係が作る）に残る。

### (2) Python の流し方の前提（軽-3）
- order5.py は、封じた4つのファイル（periods・exclusion・tagrules・counting）を、照らしたバイト列から読み込む（import の仕組みを通さない）。
- 一方で、次のものは **Python の import の仕組み**で読まれる：`src/collector/gkg.py`（`importlib.util.spec_from_file_location`）、`gkg.py` が読む `filelist.py`・`privacy_scan.py`・`themes.py`、`themes.py` が `sys.path` に足して読む `src/sealer/ledger.py`。import の仕組みは、`__pycache__` の .pyc（`-B` は書かないだけで、読むことは止めない）や、環境変数（`PYTHONPATH` など）、利用者の site-packages に左右されうる。
- そのため、封印係の入口は次の形で流す前提とする：取り出した空のフォルダ（`.pyc` も `__pycache__` も無い）の中で、`-I`（環境変数・利用者の site を読まない。スクリプトのフォルダを `sys.path` に足さない）・`-B`・`-X pycache_prefix=<空のフォルダ>`（.pyc をその場所にだけ探す）を付ける。こうすれば、上のファイルも HEAD の版のバイト列だけから読まれる。
- 取り出したフォルダには `.git` が無いので、比べる版を取り出す git のリポジトリを `--repo` で渡す（3章の2）。

### (3) コマンド（封印係の入口が使う形）

```
<.venv の python> -I -B -X pycache_prefix=<空のフォルダ> <取り出したフォルダ>/src/stats/order5.py \
    --store <日の集計の置き場所> --themes-store <区分表の置き場所> --out-dir <書き出すディレクトリ> --repo <本体のリポジトリ>
```

- 終わり値：0 できた、3 C7 で止まった（main だけ書く）、1 照合・入力・書き出しで止まった（本来の名前のファイルは一つも書かない）、2 引数が違うか、書き出すディレクトリが無いか、同じ名前（`.partial` を含む）のファイルがある。
- 書き出し（`write_outputs()`）：三つの記録をすべて作り終え、三つとも `check_public()` を通してから書く。すべてのバイト列を先に作り、一時の名前（`<名前>.partial`）に O_EXCL で書き、全部を書けてから detail・extra・main の順に本来の名前へ移す（main が最後）。一時の名前に書く途中で失敗したら、本来の名前のファイルは一つも無い（`.partial` は消さずに残す。削除はリードを通す）。テスト `TestWriteOutputs`。
- JSON は UTF-8、キーの順（`sort_keys`）、区切りは `,` と `:`（空白なし）、末尾に改行1つ。NaN は使わない。sha256 は、このバイト列全体の値。置き場所のパスと実行の日時は出力に入れない。

### (4) main（`order5-main.json`。Git に入れて封印する本体）

| キー | 中身 |
|---|---|
| `label` | `order5-tag-list-v2` |
| `status` | `ok` か `stopped`（C7 の分母が 0 の欠けた日でない日がある） |
| `block` | 区画の名前と端 |
| `refs` | 順番1・1b・2・3（seq・`record_sha256`）、順番4（seq・`record_sha256`・`list_sha256`）、gkg-run-result（seq・`record_sha256`） |
| `code` | 3章の1の表（`sealed`）と2の表（`versions`） |
| `input` | 入口、run_id、day の行の数、開いた日の集計の数、sha256 を照らしたこと、日・ファイル名・sha256 の並びの sha256（`day_files_digest`）、gkg-run-result の seq と行の sha256、マニフェストのパス・行数・sha256、C7 の分母が順番4と一致したこと |
| `themes_table` | 区分表のファイル名・sha256・行数・残した欄・`headerless`・説明の欄が無いこと・名前の数・重なった行の数・日の集計の名前の形に合わない名前（`names_not_in_day_aggregate_form` の `count` と `names`）・C7 のデータに現れて区分表に無い名前の数 |
| `missing_days` | 出どころ（order4）、数、日の一覧 |
| `official` | `candidate: C7`、`version: current`、`setting: owner_choice`、`official: true`、`result`：`build_tag_list()` の出力からテーマごとの行（`themes`）を除いたもの（`proposed_label`・`block_start`・`block_end`・`usable_day_count`・`quarters`・`quarters_without_usable_days`・`n_med`・`a`・`a_float`・`v_equals_a`・`enabled_optional_categories`・`tag_list`）と、`tag_count`、`reason_counts`（全テーマの数・一覧に入った数・存在の条件を満たさない数・平均が A 未満の数・除外の語に当たった数。一つのテーマが二つ以上の理由に数えられることがある） |
| `candidates` | C1〜C7 の順に、識別子・正式か・分子の欄・分母の種類・計算できるか（`status`・`reason`・`zero_days`）・N_med・A・A の浮動小数・欠けた日でない日の数・一覧の件数・注記（C7 以外は「比べるための参考で、正式ではない」）。一覧そのものは detail |
| `comparisons` | `allset` と `1cb463a`：`compare_lists()` の出力（`only_in_old`・`only_in_new`・`in_both`・`enabled_optional_categories`）、差の件数 `diff_count`、`official: false`、注記 |
| `reference_criteria` | 出どころ（順番2の seq と行の sha256）、順番2の status、基準の案の識別子、`computed`（入力の mode・run_id・3日と、B1〜B5 の結果をそのまま）、`official: false`、注記 |
| `coverage` | `quarters`（四半期ごと：番号・端・欠けた日でない日の数・`docs_all_groups`・3つの `docs_without_*`・割合）と `total` |
| `outside` | `detail` と `extra` の、ファイル名と sha256（`stopped` のときは null） |
| `a_equals_v` | true |
| `limits` | 6章の限界の要約（決まった文） |
| `citation` | GDELT の引用（英語と日本語） |

`status: stopped` のときは、`official`・`comparisons`・`coverage` を出さず、`candidates` の N_med・A・件数は null。

### (5) Git の外のファイル（sha256 は main の `outside` に入る。置き場所はリードとオーナーが決める）

- **detail**（`order5-detail.json`）：`label`、`part: detail`、`in_git: false`、注記、`official_result`（正式な一覧の `build_tag_list()` の出力の全体。テーマごとの四半期の件数・平均・A 以上か・当たった除外の語・一覧に入ったか。tags-naive.md 154行の「一覧に入らなかったテーマとその理由も、すべて公開する」はこのファイルで満たす）、`allset_result`（全体）、`versions.1cb463a`（全体）、`candidate_lists`（C1〜C7 の一覧。計算できない候補は null）、`citation`。
- **extra**（`order5-extra.json`。封印の対象にしない。公開するかは試運転の手順5でオーナーが決める。リードの判断4）：`label`、`part: extra-versions`、`in_git: false`、`sealed: false`、注記、`versions`（0e14f3b・247fc1d の `result`（全体）と `compare_with_official`、`official: false`、注記）、`citation`。

**公開してよいものだけであることの確かめ**（`check_public()`。書く前に三つすべてに行う）：
- キーが決めた一覧（`ALLOWED_KEYS`）の中だけ。人物名・組織名・URL・場所・座標などの項目のキーは一覧に無い。日の集計の読み取りで使うのは V・D・T・S の行だけで、ほかの行（場所など）は `parse_day()` が読み飛ばす。
- メールアドレスの形の文字列が無い（`src/collector/privacy_scan.py` の `has_address`）。区分表の名前の形は `@` を許すので、念のため出力全体で確かめる。
- 置き場所の絶対パス（`/Users/`・`/Volumes/`）が無い。
- 値に入る文字列は、テーマの名前、決まった語、日付、16進のハッシュ、分数の文字列だけになる。

## 5. 第三者が order5.py に頼らずに計算し直す手順（tags-naive.md 428行・429行）

封印係の `verify`（T-111）と第三者は、封印済みの `tagrules.py`（seq 5）・`counting.py`（seq 6）と封印済みの入力だけから、main の正式な一覧と要約を計算し直して照らす。この章だけで再現できるように書く（order5.py は読まなくてよい）。

**入力**
1. 区画：2015-03-02〜2020-12-14（両端を含む。seq 1 の `periods.py` の `FROZEN_BLOCKS` の method）。日は `datetime.date`。
2. 欠けた日 `missing`：seq 15 の記録の中身の `list.missing_days` の各要素の `day` を `datetime.date` にした集合（48日）。数え直さない。
3. 日の集計：seq 12 で封印したマニフェスト（`gkg-run-result` の中身の `manifest_lines` 行）の、正式な run の `day` の行（区画の各日にちょうど一つ）。各行の `file_name` のファイルを開き、sha256 を行の `sha256` と照らす。
4. 区分表：`data/manifest/gdelt-themes.jsonl` の最後の行（`kind: result`）の `file_name` のファイル。sha256 を `21aef571…`（その行の `sha256`）と照らす。UTF-8 で、改行で区切り、1行目（`THEME`）を除いた各行が名前。名前の**集合**（重なりは一つにまとめる）を `T` とする。

**正式な一覧（main の `official`）**
1. 各日 d について、`s = counting.parse_day(日の集計のバイト列, expect_day=d の文字列, expect_mode="official")`、`counts_d, total_d = counting.candidate_counts(s, "C7")`。
   - 同じことを平易に言うと：T の行のうち、組（2番目の欄）が `T` で終わらないものについて、テーマ（V の行で番号から名前にする）ごとに7番目の欄（`v1_or_v2_docs`）を足したものが分子で、0 のテーマは入れない。分母はその分子の全テーマの和。
2. `counts = {名前: {d: counts_d[名前] （0 でない日だけ）}}`、`totals = {d: total_d}`（区画のすべての日。欠けた日も入れてよい）。
3. `themes = {名前: None for 名前 in T}`（区分表に説明の欄は無い）。
4. `result = tagrules.build_tag_list(themes, counts, totals, missing, date(2015,3,2), date(2020,12,14))`。`optional` は渡さない（オーナーの選択 `("ethnic_religious_group",)` が使われる）。
5. main の `official.result` は、`result` から `themes` を除いたものに、`tag_count = len(result["tag_list"])` と `reason_counts` を足したもの。`reason_counts` は `result["themes"]` の行について、`all_themes`＝行の数、`in_list`＝`in_list` が真の数、`not_present_throughout`＝`present_throughout` が偽の数、`mean_below_a`＝`mean_ratio_at_least_a` が偽の数、`excluded`＝`exclusion_matches` が空でない数。detail の `official_result` は `result` そのもの。

**各候補の要約（main の `candidates`）**：候補 c（C1〜C7）ごとに、1・2 の `"C7"` を c に替えて `counts_c`・`totals_c` を作る。`counting.order5_candidate_status(c, totals_c, missing, 区画のすべての日)` の `status` が `ok` なら、`build_tag_list(themes, counts_c, totals_c, missing, 区画の端)`（`optional` なし）の `n_med`・`a`・`a_float`・`usable_day_count`・`len(tag_list)` が要約。`ok` でなければそれらは null。C7 の `status` が `stop` なら、main は `stopped`。

**比較の要約（main の `comparisons`）**：
- `allset`：`build_tag_list(..., optional=tagrules.OPTIONAL_CATEGORIES)` を `old`、正式な `result` を `new` として `tagrules.compare_lists(old, new)`。`diff_count` は `only_in_old` と `only_in_new` の件数の和。
- `1cb463a`：`git show 1cb463a:src/stats/tagrules.py`（sha256 `f7c325cb…`。seq 5 の対象）を読み込んだモジュールの `build_tag_list(themes, counts, totals, missing, 区画の端)`（引数は6つ）を `old` にして同じく。

**欄の手厚さ（main の `coverage`）**：各日の `counting.coverage([s])` の4つの値を、欠けた日でない日について、`tagrules.quarters(区画の端)` の四半期ごとと期間全体で足す。割合は、それぞれを `docs_all_groups` で割った既約分数の文字列（`docs_all_groups` が 0 なら null）。

照らすのは、計算し直した値と main の値が同じこと。main の `outside` の sha256 と、Git の外に置いた detail・extra のバイト列の sha256 が同じことも照らせる。

## 6. 限界

- 区分表は名前の欄だけを取得した（件数の欄は捨てた。説明の欄はもともと無い）。除外の規則は名前の欄だけで照合する（tags-naive.md 159・224行）。名前に区分の語が無く、説明にだけある、というテーマは外れない。
- 記号（下線以外）を含むテーマ名は、日の集計に数えられていないので、一覧に入らない（T-107 の監査の中-1）。区分表を取得したコード（themes.py）が名前の形を広げたのは T-107 で、取得のコード（gkg.py の `THEME_RE`）と数え方のコード（counting.py。順番1b で封印）は古い形のまま。どちらもデータを見る前に封じたコードで決まっているので、選び出しの余地にはならない。数と名前は main の `themes_table.names_not_in_day_aggregate_form` に出る。
- 区分表の重なった行は、名前の集合として一つにまとめる（リードの判断2）。数は `duplicate_rows` に出る。
- 区分表は取得した時点の全テーマの一覧なので、手法を作る期間のあとに生まれたテーマの名前も入りうる。名前だけでは一覧に入らない（存在の条件）。
- 翻訳の印の付いた組の記事は数えない（counting.md 98行）。V1 と V2 で名前が違う同じテーマは、別々のテーマとして数える（counting.md 104行）。
- 欠けた日は順番4の一覧だけで決め、数え直さない。C7 の分母は、順番4の一覧の値と同じであることを確かめるだけ。
- 参考の基準の案 B1〜B5 の結果は、試しの run の3日の値で、手法を作る期間の全体の値ではない（counting.md 315行）。
- main に入れるのは要約で、テーマごとの理由は Git の外の detail にある。detail の中身は main の sha256 で縛られるが、detail を失えば理由は5章の手順で計算し直すしかない。extra は封印の対象にせず（tags-naive.md 426行）、sha256 だけが main に入る。
- order5.py は順番5の前に封じられていない。結果を見てから直す道は、手で流さないこと（4章 (1)）と、第三者の計算し直し（5章）で塞ぐ。封印係の入口を通らずに手で流すことは、コードでは止められない（流したことは記録に残らない）。
- 照らすのは、ファイルのバイト列と記録の値の一致まで。収集係のコードの誤りで、形は合うが数が違う日の集計は見分けられない（counting.md 1章）。
- 順番5を始める前に封印係が行う照合（seal-order1.md 143行の「(1) の照合」）と、順番5の kind・記録の中身・時機の照合（3・4 のあと、モデルより前）は、封印係の範囲（T-111）で、このコードは行わない。

## 7. 所要時間と大きさ（見込み。実測ではない）

- 日の集計の読み取り：順番4（`missing_days.py`）は、2115個の日の集計を開いて `parse_day()` を通し、C7 の分母を数えるのに 64〜92分かかった（reviews/T-105.md、missing-days-method.md 4章）。順番5は同じ読み取りに加えて、日ごとに7つの候補の `candidate_counts()` を呼び、テーマごとの数を配列に足す。
- `build_tag_list()`：区分表とデータのテーマ（5万9千以上）について、欠けた日でない日（2067日）ごとの比率を足すので、1回あたり数分〜十数分と見込む。呼ぶのは最大で11回（C1〜C7 の7回、すべて有効の設定1回、三つの版の3回）。
- 合わせて **2〜4時間** と見込む。メモリは、テーマと日の組の数に比例する（1組あたり約18バイトの配列）。数千万組なら 1GB 前後と見込む。
- **main の大きさ**：決まった部分が約15KB（合成のテストでは約10KB。本物では四半期が24個、欠けた日が48日、B1〜B5 の値が長いので増える）に、名前1つあたり約30バイト（名前の長さ＋引用符と区切り）×（正式な一覧の件数 ＋ 二つの比較の差のある名前の数 ＋ 記号を含む名前36個）を足したもの。正式な一覧が1千〜1万件、比較の差が数百〜数千件なら、**およそ 50KB〜400KB**。一覧の件数は、日の集計を開かないと分からない。
- detail は、テーマごとの行（約6万）を三つの全体の結果に持つので数十MB、extra は二つの全体の結果で十数〜数十MB と見込む。

## 8. 何を知っていた時点で書いたか

- 順番1〜4 の決まりと記録（seq 1〜15）、区分表のマニフェストの result の行（行数と sha256）、T-106 の診断の数（記号を含む名前が36個）、reviews/T-109.md のリードの判断と監査の所見を知っていた。
- 区分表のファイル、日の集計、テーマごとの数は開いていない。この文書の決め方は、それらの結果に依らない。

## 9. 引用

Data: The GDELT Project (https://www.gdeltproject.org/). This project is not affiliated with or endorsed by the GDELT Project.
データ出典：GDELT Project（https://www.gdeltproject.org/）。本プロジェクトは GDELT Project と提携・承認の関係にありません。
