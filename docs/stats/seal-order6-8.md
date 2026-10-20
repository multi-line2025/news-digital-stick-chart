# 順番6〜8 と採点計画の封印の対象の一覧（T-143、封印の前）

この文書は、最初の threshold-access の記録より前に封印するもののうち、統計係の分をまとめたものである。封印係が読む前提で書いた。
統計係は封印しない（封印は封印係の T-144）。順番の番号は tags-naive.md 5章の表のもの。

- 出どころ：オーナーの決定（2026-10-20、reviews/T-143.md）。普段の水準は直近365日の中央値のまま（未決事項2。過去数年の同じ週の案は採らない）。冷却と「対象なし」の規則は改訂しない（順番6）。
- sha256 は、この文書を書いた時点のファイルのもの。封印係は、封印する commit で同じ値になることを確かめる。
- この文書のファイル自身の sha256 は、この中には書けない（自分の sha256 は自分の中に書けないため）。

## 1. 順番6：冷却と「対象なし」の規則の改訂（改訂なし）

- 決定：改訂しない（reviews/T-143.md、2026-10-20 オーナー）。
- 改訂しないので、規則は次のファイルの今の版のとおり。新しい版は作らない。
  - `src/stats/scoring.py`（target_status()・recently_jumped()・week_summary()。JUMP_MULTIPLIER = 2、COOLDOWN_DAYS = 56）
  - `docs/stats/naive-scoring.md` 4章 (1)（一度跳ねたタグの扱い）と (2)（「対象なし」の週の数え方）
- 封印の記録に書く内容の案：「順番6：改訂なし。規則は src/stats/scoring.py（sha256 は 4章の表）と docs/stats/naive-scoring.md 4章 (1)(2) のとおり。決定は reviews/T-143.md」。
- この二つのファイルは、順番8の対象にも入る（3章）。

## 2. 順番7：naive_history_days = 399

- 値：399。素朴な予測の特徴量が読む最も古い日が t-399 であることによる（去年の同じ時期の広げた期間の始まり t+1−365−35）。
- どのコードの定数か：`src/stats/naive.py` の `naive_lookback_days()`（引数なしで、判定期間の候補 14・28・56 日の全体での最大を返す）。定数そのものは SEASON_SHIFT_DAYS = 365・SEASON_MARGIN_DAYS = 35（periods.SEASONAL_MARGIN_DAYS）から計算される。
- どの文書か：`docs/stats/naive-scoring.md` 3章 (4) の表（lookback）と手順1。
- 出力：`periods-order7.json`（次のコマンドの標準出力。4章の表）。
  ```
  PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -B src/stats/periods.py --naive-history-days 399 --deadline-status before_deadline
  ```
  - 399 は periods.py の LOOKBACK_DAYS（400）以下なので、区切りは変わらない（出力の区画と予言日の範囲は v1 と同じ）。
  - `deadline_status` は、値を封印の記録に追記する時点が期限（閾値を決める期間の区画の情報を最初に扱う時点）より前であることの申告である（periods.md 8章 (2)）。照合は封印係の検証手順。
- ほかのきっかけの値（periods.md 8章 (1)）
  - 過去数年の同じ週の年数 N：使わない（未決事項2 の決定。同じ週の案は採らない）。
  - 共起の網を作る期間：統計係は、この出力に値を入れていない。4章の注を見てほしい（封印係・リードの判断が要る）。
  - J：candidates の封印済みの値のとおり（この文書では扱わない）。

## 3. 順番8：素朴な予測の最後の版と21組の係数

- 素朴な予測の最後の版：`src/stats/naive.py`（PROPOSED_LABEL = naive-v1。改訂なし。特徴量は naive-scoring.md 3章 (1) の7つ）と `src/stats/scoring.py`。
- 出力：`naive.json`・`scoring.json`（それぞれ `naive.py`・`scoring.py` を引数なしで流した標準出力）。
- 21組の係数：`naive_coefs.tsv`。倍率 2・3・4・6・8・12・16 × 判定期間 14・28・56 日。
  - 行：手法を作る期間のすべての予言日（periods.py の予言の曜日。今は月曜で 232 回）の、状態が target で、判定期間の7つの倍率の判定がどれも判定不能でない行。判定期間ごとに 292625 行。判定不能の行は0件だった。
  - 推定：naive-scoring.md 3章 (2) の手順（係数0から始めるニュートン法、リッジ 1（切片にも掛ける）、一歩を半分に最大30回、TOL 1e-10、100回まで）。行は予言日・タグ名の昇順。計算は em.fit_logistic_cols で行った（naive.fit_logistic とビット単位で同じ結果になることを、tests/stats/test_explore_models.py と tests/stats/test_order8_fit.py の test_same_as_naive_fit_rows で確かめている）。21組すべて収まった。
- テスト：`tests/stats/test_t019.py`（naive.py・scoring.py の定数と文書の表の照合、読む日の確かめなど）。

## 4. 封印の対象の一覧

### (1) 順番6〜8

| 対象 | sha256 | 最後に変えたコミット |
|---|---|---|
| src/stats/naive.py | 859947f442b6843a332922d5ee1159403e36e38394bfa99f64594b229c35373a | 82e0424a3c08ac5ec7d4c7a9c7e984df3532e045 |
| src/stats/scoring.py | ae30815f5690bf3d9faaabcdb25cce821c8c627282620e1e705220f79a9a4300 | 82e0424a3c08ac5ec7d4c7a9c7e984df3532e045 |
| src/stats/periods.py | 81de229d065196a26e15d90c5a80eb1043ca534a6eaf66cdebd36285ae087605 | 265ab14a6f4ad41d2d35b0b281d2df58853f4069 |
| docs/stats/naive-scoring.md | ef2a32bc1f224fbeec2e6046577bbf39e4757a7609c01f801efb78b529bac301 | 33154f10e3fa6128b646812a8f251813e64c0d1e |
| tests/stats/test_t019.py | 6b159f8b796cc8fe664b16b975047e23baa678be1bcc4661798c8605bff74a5c | 98510c18927e1d84c972573259e771642971bb4f |
| tests/stats/test_periods.py | 653e96509b89006466c69954d4c2af0cbcf14e6f14ecc470e25cc6e7a1e914d7 | 265ab14a6f4ad41d2d35b0b281d2df58853f4069 |
| docs/stats/order8-t143/periods-order7.json（順番7の出力） | 00cc722724347c6e8fe38d6bde1d6ecd21abcf80c8baec31e59b75bebcf2b02c | この文書と同じコミット |
| docs/stats/order8-t143/naive.json（順番8の出力） | 3fa64ef423e948446f5696e31ebd621440cb9910dbbf8ce40f67c0726b80951b | この文書と同じコミット |
| docs/stats/order8-t143/scoring.json（順番8の出力） | dbbad062aade5eb0578e4b9a13cf4ef2cad3fdd8e3ec5105b3c461f64d87e2bb | この文書と同じコミット |
| docs/stats/order8-t143/naive_coefs.tsv（21組の係数） | 684a196098b60340a8f4d09320b515d072c195a4a015f887a4b8ecfabdf2ceb5 | この文書と同じコミット |

### (2) 採点計画と、比べる段の形・係数

| 対象 | sha256 | 最後に変えたコミット |
|---|---|---|
| docs/stats/claims-scoring-plan.md | 74cd2071f4b6777769abe1ee1d15acc195ce8c6deade6cf7392828012a26b906 | 7850119848c86b943026f0e210ce5f0feca27444 |
| docs/stats/tiers-select-t142/tiers_select.tsv（21組の選んだ形） | 13a2784652964f0e1da23d28cba0970744ab8aadcbc715a35edfcf982ffc30b6 | c27890895497ae0fac1229d10f553dee5f57406d |
| docs/stats/tiers-select-t142/tiers_select_all.tsv（全形の対数損失） | 7678f199260ac268686bfaa8eaa281852f712239b3d9b86a60daa726a499707b | c27890895497ae0fac1229d10f553dee5f57406d |
| docs/stats/tiers-select-t142/summary.md | 6be938e7934ae0928546d1fbd82ccbd7ffe6c7cd203c2e79edadfef8b897736c | c27890895497ae0fac1229d10f553dee5f57406d |
| src/stats/tiers_select.py | 19e4b858109741e33ea3befa66561462bdc46710e03addcb76300de2bee3c331 | 7850119848c86b943026f0e210ce5f0feca27444 |
| tests/stats/test_tiers_select.py | 45c3029af2e3489a02a956cc58dc4e2d2c29db9c0cd498e51ff13ea5815f5b25 | 7850119848c86b943026f0e210ce5f0feca27444 |
| src/stats/explore_tiers.py（段1・段2・段4 の作り方） | 9fc7aae626c9445cb980fa059b5f0dab96b81e2d4c672adecd847e1a4c73e84c | c4ff224959b39bc256242ca7b384f19630fdfd77 |
| src/stats/order8_fit.py | a136e4a7f14582f602baf76e805f2e512fa65fd6194225156b6743312bf5e58b | 8ac714c0c41035e4785ddce3c1eec45086887257 |
| tests/stats/test_order8_fit.py | a0c000bff37957917b0241add04662989ed784da968f2604ff345ba94bad1978 | 8ac714c0c41035e4785ddce3c1eec45086887257 |
| docs/stats/order8-t143/tier4_coefs.tsv（段4 の21組の係数） | 57680479f8f2d36799f0744aba92867fb95104a7420d36dacef9c72691cdede1 | この文書と同じコミット |
| docs/stats/order8-t143/n3_coefs.tsv（N3 の21組の係数） | 6aca62f54355aa1bfc8a00c4a4cb95bd79eb6bb493247e19dcedae53816cad3c | この文書と同じコミット |
| docs/stats/order8-t143/n4_coefs.tsv（N4 の21組の係数） | 8b4e8f212bf562a25d4d8facb6b5cb368d0f96a60ab4362a6b1d02a24f237bce | この文書と同じコミット |
| docs/stats/order8-t143/tier1_null_fix.tsv（段1 の null_fix の定数） | 0de7a69c5540012babfb5b41ce30c36e8a03091df4da496c4b603b21aa15083b | この文書と同じコミット |
| docs/stats/order8-t143/forms.tsv（21組の選んだ形と、段2 の W・a、段4 の列） | b5dbb9813c9527fe8692343b82468d11b4bfda7ce42bdc39d4c688236334421c | この文書と同じコミット |
| docs/stats/order8-t143/run.json（計算に使ったコードの sha256 の一覧を含む） | 2e0eb5b7fb916892029d9cefb2784cd7609874d8f52380cdabc7543f216d382f | この文書と同じコミット |
| docs/stats/order8-t143/summary.md | 664acb98e67c40d8a72dbccbf0abc4df4eb23940fc22b7503bc25fd0bd2e3214 | この文書と同じコミット |

- docs/stats/order8-t143/ のファイルは、$HOME/Desktop/news-stick-data/order8-t143/ の出力と同じバイト列（写し）。
- 計算に使ったコード（explore_islands.py から explore_tiers.py・tiers_select.py・order8_fit.py まで）の sha256 は、run.json の `code` にある。

## 5. 出力を作り直す手順

プロジェクトのルートで、TMPDIR を一時のフォルダにして流す。書き出す先に同じ名前のファイルがあれば止まる（上書きしない）。

1. 順番7・順番8・段の係数（11ファイル。約14分、10コア）
   ```
   .venv/bin/python -B src/stats/order8_fit.py --t117-cache <explore-t117-cache/run2> --out-dir <新しいフォルダ>
   ```
   - 入力：手法を作る期間の日の集計から作ったキャッシュ（explore-t117-cache/run2。phase1.json の sha256 は 3c71b39e14ed657365ed538ac912e971ac66c47c6a0ed79aceb336af0a36caa5（explore_signals の KNOWN_CACHE_PHASE1_SHA256）で、キャッシュの中のファイルは phase1.json に書いた sha256 と照らしてから読む）、封印の記録から読むタグの一覧・V・欠けた日（explore_islands.load_context）、21組の表（docs/stats/tiers-select-t142/tiers_select.tsv。sha256 を照らしてから読む）。
   - Python 3.14.2 で流した。統計係の流し直し（別のフォルダ）で、11ファイルすべての sha256 が同じだった。
2. 21組の表（4ファイル。約13分）
   ```
   .venv/bin/python -B src/stats/tiers_select.py --t117-cache <explore-t117-cache/run2> --out-dir <新しいフォルダ>
   ```
3. 順番7・順番8 の JSON だけなら、データは要らない。
   ```
   PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -B src/stats/periods.py --naive-history-days 399 --deadline-status before_deadline
   PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -B src/stats/naive.py
   PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -B src/stats/scoring.py
   ```

## 6. 閾値を決める期間・基準値を測る期間のデータに触れていないことの確かめ方

- 入力のキャッシュ：`es.load_cache()` は、キャッシュの日の一覧が、封印の記録から読んだ手法を作る期間の区画の日（2015-03-02〜2020-12-14）と一致しなければ止まる。区画の外の日の集計はキャッシュに入っていない。
- 読んだ日：日の比率は ReadGuard を通して読み、読んだ日の最小と最大を run.json の `info` に記録した（2015-03-09〜2020-11-09）。最大が区画の終わり（2020-12-14）を超えれば、order8_fit.py・tiers_select.py は止まる。
- 網：予言日ごとに、網の最後の日 < 予言日を確かめた（es.check_network_before）。網の月は区画の中だけ。
- 順番7・順番8 の JSON は、データを読まないコードの出力である（periods.py・naive.py・scoring.py は日の集計を開かない）。
- 封印の記録に threshold-access の記録が無いこと（今の ledger の kind の一覧に threshold-access は無い）。閾値を決める期間の区画のデータの取得の記録（収集係のマニフェスト）が無いことは、封印係・収集係の記録で確かめる。
- 限界：手元で区画の外のデータを見たかどうかは、記録からは分からない。上の確かめは、封印する出力が区画の中のデータだけから第三者に作り直せることを示す。

## 7. 気づいたこと（判断が要るもの。統計係は決めていない）

1. 予言の曜日：periods.py の PREDICTION_WEEKDAY = 0（月曜）は提案値で、前向きの予言の曜日はまだ決まっていない（periods.md 2章）。21組の係数と21組の表は月曜の予言日で作った。前向きの曜日が月曜でなければ、学習の行（予言日）が変わるので、係数と表を作り直す必要がある。
2. 共起の網を作る期間（periods.md 8章 (1) のきっかけ）：採点計画で段4・N3・N4 の封印を決めたので、網（予言日を含む月の前の12か月の月ごとの網）も予言の入力になる。網が読む最も古い日は予言日の最大 396 日前（12か月が366日の年と、月の31日目の予言日）で、LOOKBACK_DAYS（400）以下である。このきっかけの値を封印の記録に追記するかどうかは、封印係とリードの判断が要る。
3. 順番6の「改訂なし」を記録にどう書くか（kind の名前と、何を参照するか）は、封印係が決める。

## 引用
Data: The GDELT Project (https://www.gdeltproject.org/). This project is not affiliated with or endorsed by the GDELT Project.

データ出典：GDELT Project（https://www.gdeltproject.org/）。本プロジェクトは GDELT Project と提携・承認の関係にありません。
