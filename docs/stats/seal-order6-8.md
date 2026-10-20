# 順番6〜8 と採点計画の封印の対象の一覧（T-143・T-145、封印の前）

この文書は、最初の threshold-access の記録より前に封印するもののうち、統計係の分をまとめたものである。封印係が読む前提で書いた。
統計係は封印しない（封印は封印係の T-144）。順番の番号は tags-naive.md 5章の表のもの。

- 出どころ：オーナーの決定（2026-10-20、reviews/T-143.md）。普段の水準は直近365日の中央値のまま（未決事項2。過去数年の同じ週の案は採らない）。冷却と「対象なし」の規則は改訂しない（順番6）。前向きの予言日は月曜日。N3・N4 の学習の行は、判定が確定した予言日の数が52以上の行だけ（決定 B）。
- T-145 で、N3・N4 の係数を決定 B の行で当てはめ直した（docs/stats/order8-t145/）。T-143 の出力（docs/stats/order8-t143/）は変更前の版として残して公開する。
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
- ほかのきっかけの値と、予言の入力が読む過去の整理は 7章 (2)。

## 3. 順番8：素朴な予測の最後の版と21組の係数

- 素朴な予測の最後の版：`src/stats/naive.py`（PROPOSED_LABEL = naive-v1。改訂なし。特徴量は naive-scoring.md 3章 (1) の7つ）と `src/stats/scoring.py`。
- 出力：`naive.json`・`scoring.json`（それぞれ `naive.py`・`scoring.py` を引数なしで流した標準出力）。
- 21組の係数：`naive_coefs.tsv`。倍率 2・3・4・6・8・12・16 × 判定期間 14・28・56 日。
  - 行：手法を作る期間の予言日の範囲にある、予言の曜日（月曜。前向きも月曜：2026-10-20 オーナー決定）のすべての予言日（232 回）の、封印したタグの一覧のすべてのタグのうち状態が target の行。正解は封印した V で計算した candidates.judge の値で、判定不能の行だけを除く（naive-scoring.md 3章 (2) と同じ書き方）。コードは判定期間 H ごとに「7つの倍率の判定がどれも判定不能でない行」を選ぶが、判定不能は倍率に依らず、この期間では判定不能の行が0件だったので、選ばれる行は同じ（判定期間ごとに 292625 行）。
  - 推定：naive-scoring.md 3章 (2) の手順（係数0から始めるニュートン法、リッジ 1（切片にも掛ける）、一歩を半分に最大30回、TOL 1e-10、100回まで）。行は予言日・タグ名の昇順。計算は em.fit_logistic_cols で行った（naive.fit_logistic とビット単位で同じ結果になることを、tests/stats/test_explore_models.py と tests/stats/test_order8_fit.py の test_same_as_naive_fit_rows で確かめている）。21組すべて収まった。
- テスト：`tests/stats/test_t019.py`（naive.py・scoring.py の定数と文書の表の照合、読む日の確かめなど）。

## 3b. 段4・N3・N4 の係数（採点計画 2章 (6)・8章 (3)）

- 段4：手法を作る期間の全部の行（3章と同じ行）で当てはめた。T-145 でも変えていない（tier4_coefs.tsv は T-143 と同じバイト列）。
- N3・N4：決定 B（2026-10-20 オーナー、reviews/T-143.md 末尾）により、予言日 t の時点で判定が確定した予言日の数が52以上の行だけで当てはめた。
  - 判定が確定した予言日の数：2016-04-11 から数えた月曜のうち、判定期間が t-1 までに終わったものの数（週の番号 ti − ceil((H + 1) / 7) + 1）。タグによらない週の数（src/stats/order8_fit.py の MIN_KNOWN_WEEKS = 52 と known_weeks()。流す前にコミット 7f85bfb で固定した）。
  - 行の数：H = 14 で 216373、H = 28 で 214304、H = 56 で 209829。
  - これは T-143 の係数を見たあとの規則の変更である。手法を作る期間の中での変更で、閾値を決める期間・基準値を測る期間のデータには触れていない。変更前の係数（docs/stats/order8-t143/n3_coefs.tsv・n4_coefs.tsv）も残して公開する。
  - logit(段2) の係数の範囲（21組）：N3 は 0.080〜0.321（T-143）から 0.169〜0.574（T-145）、N4 は 0.080〜0.312 から 0.164〜0.554。
- 段1・段2・段3：T-145 でも変えていない（naive_coefs.tsv・tier1_null_fix.tsv・forms.tsv は T-143 と同じバイト列）。

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
| docs/stats/order8-t145/periods-order7.json（順番7の出力） | 00cc722724347c6e8fe38d6bde1d6ecd21abcf80c8baec31e59b75bebcf2b02c | 310e24d82943154b2b457b08629cdf2fc3ea1bae |
| docs/stats/order8-t145/naive.json（順番8の出力） | 3fa64ef423e948446f5696e31ebd621440cb9910dbbf8ce40f67c0726b80951b | 310e24d82943154b2b457b08629cdf2fc3ea1bae |
| docs/stats/order8-t145/scoring.json（順番8の出力） | dbbad062aade5eb0578e4b9a13cf4ef2cad3fdd8e3ec5105b3c461f64d87e2bb | 310e24d82943154b2b457b08629cdf2fc3ea1bae |
| docs/stats/order8-t145/naive_coefs.tsv（21組の係数） | 684a196098b60340a8f4d09320b515d072c195a4a015f887a4b8ecfabdf2ceb5 | 310e24d82943154b2b457b08629cdf2fc3ea1bae |

- 上の4つの出力は、docs/stats/order8-t143/ の同じ名前のファイルと同じバイト列である。

### (2) 採点計画と、比べる段の形・係数

| 対象 | sha256 | 最後に変えたコミット |
|---|---|---|
| docs/stats/claims-scoring-plan.md | 7af787865ac11516ef890e7221c17682c72d488b296587985b180ecba2f91d57 | 1d644e909909abb1bd609f253812bccdd43aabeb |
| docs/stats/tiers-select-t142/tiers_select.tsv（21組の選んだ形） | 13a2784652964f0e1da23d28cba0970744ab8aadcbc715a35edfcf982ffc30b6 | c27890895497ae0fac1229d10f553dee5f57406d |
| docs/stats/tiers-select-t142/tiers_select_all.tsv（全形の対数損失） | 7678f199260ac268686bfaa8eaa281852f712239b3d9b86a60daa726a499707b | c27890895497ae0fac1229d10f553dee5f57406d |
| docs/stats/tiers-select-t142/summary.md | 6be938e7934ae0928546d1fbd82ccbd7ffe6c7cd203c2e79edadfef8b897736c | c27890895497ae0fac1229d10f553dee5f57406d |
| src/stats/tiers_select.py | 19e4b858109741e33ea3befa66561462bdc46710e03addcb76300de2bee3c331 | 7850119848c86b943026f0e210ce5f0feca27444 |
| tests/stats/test_tiers_select.py | 45c3029af2e3489a02a956cc58dc4e2d2c29db9c0cd498e51ff13ea5815f5b25 | 7850119848c86b943026f0e210ce5f0feca27444 |
| src/stats/order8_fit.py（v2） | d7c6c469b9376a60d6a74971bb95ffee93357bc1284ae48c677f4eb550aad877 | 7f85bfbdc0683dc24db6169d29b1b47461048801 |
| tests/stats/test_order8_fit.py | 2a7d3035e712544874f3a25931748da3bfa3c38f3ea607abd0fea0c90eeab8f3 | 7f85bfbdc0683dc24db6169d29b1b47461048801 |
| docs/stats/order8-t145/tier4_coefs.tsv（段4 の21組の係数） | 57680479f8f2d36799f0744aba92867fb95104a7420d36dacef9c72691cdede1 | 310e24d82943154b2b457b08629cdf2fc3ea1bae |
| docs/stats/order8-t145/n3_coefs.tsv（N3 の21組の係数。決定 B の行） | 0c4cb4c26b177ef2a72139c79520a0b5510dd2401797ab28d77cb7af0325e15a | 310e24d82943154b2b457b08629cdf2fc3ea1bae |
| docs/stats/order8-t145/n4_coefs.tsv（N4 の21組の係数。決定 B の行） | f8e0a2c353add2b1fe9c03489940fa188cb8321b4f57a9297f8d0e1215aecfe9 | 310e24d82943154b2b457b08629cdf2fc3ea1bae |
| docs/stats/order8-t145/tier1_null_fix.tsv（段1 の null_fix の定数） | 0de7a69c5540012babfb5b41ce30c36e8a03091df4da496c4b603b21aa15083b | 310e24d82943154b2b457b08629cdf2fc3ea1bae |
| docs/stats/order8-t145/forms.tsv（21組の選んだ形と、段2 の W・a、段4 の列） | b5dbb9813c9527fe8692343b82468d11b4bfda7ce42bdc39d4c688236334421c | 310e24d82943154b2b457b08629cdf2fc3ea1bae |
| docs/stats/order8-t145/run.json（計算に使ったコードの sha256 の一覧を含む） | 5b0c96948c7af88c6f02f67c2e6c492a4af377a579abd5363f3c6a00605441ff | 310e24d82943154b2b457b08629cdf2fc3ea1bae |
| docs/stats/order8-t145/summary.md | 460157f65faadb9aeced7678f12e054cf9a6e227801af8be083e6f37619de57d | 310e24d82943154b2b457b08629cdf2fc3ea1bae |

### (2b) 変更前（公開・封印するが採点に使わない）

N3・N4 を全部の行で当てはめた T-143 の版。決定 B（2026-10-20 オーナー）による規則の変更の前の記録として、公開し、封印するが、採点には使わない。

| 対象 | sha256 | 最後に変えたコミット |
|---|---|---|
| docs/stats/order8-t143/n3_coefs.tsv | 6aca62f54355aa1bfc8a00c4a4cb95bd79eb6bb493247e19dcedae53816cad3c | 90154f0d1203c5f3aed55d0017bf7561ef5477d5 |
| docs/stats/order8-t143/n4_coefs.tsv | 8b4e8f212bf562a25d4d8facb6b5cb368d0f96a60ab4362a6b1d02a24f237bce | 90154f0d1203c5f3aed55d0017bf7561ef5477d5 |
| docs/stats/order8-t143/run.json | 2e0eb5b7fb916892029d9cefb2784cd7609874d8f52380cdabc7543f216d382f | 90154f0d1203c5f3aed55d0017bf7561ef5477d5 |

### (2c) chain の d の上限の確かめ（参考。封印の対象にするかは封印係が決める）

| 対象 | sha256 | 最後に変えたコミット |
|---|---|---|
| src/stats/chain_cap_check.py | c95412c1d9b2ed52fb55aaff86b919639d1ad65dbfe55d2cbc78b1752bce262a | e5a2ba770aa1839ba589550e2b3950c3b50cb1be |
| tests/stats/test_chain_cap_check.py | c479ccc7b89661d2706b3a9de4a792e95c8f11c03a46b804d9818abbc860d8d3 | e5a2ba770aa1839ba589550e2b3950c3b50cb1be |
| docs/stats/chain-cap-t146/chain_cap.json | 7a9428f4f3086b44f5a59c317fa00964c099a6e2a1c00a0bad63dfa7ac19449a | 1d644e909909abb1bd609f253812bccdd43aabeb |
| docs/stats/chain-cap-t146/summary.md | 4805b9bf9d01273dc5f196397333ea52090c36750ff735efc504a51f13de7dbc | 1d644e909909abb1bd609f253812bccdd43aabeb |

### (3) 段1〜段4・N3・N4 の入力の作り方と推定を定めるコード

段の確率の入力（素朴な予測の特徴量、段2 の確率、網の手がかり nbwave、連鎖の励起 chain）と推定は、次のファイルの関数で定まる（tiers_select.py・order8_fit.py が import でつないで使う）。

| 対象 | 何を定めるか | sha256 | 最後に変えたコミット |
|---|---|---|---|
| src/stats/explore_islands.py | 封印の記録の読み込み（タグの一覧・V・欠けた日）、ReadGuard、予言日、照らして読む candidates・scoring・counting・periods | ed8231f3fc9b6975bf72de52a02bc425aff82b1cc81eb02a7ff1ef876fd58a48 | c3ebb2bc4aa66194a425880d2d6e818e3589e217 |
| src/stats/explore_signals.py | キャッシュの読み込み、日の比率、状態・B・c・判定、網の月と網の最後の日の確かめ、隣の一覧（lift10）、対数損失・AUC・束ねたブートストラップ | ac29132784462c254b27bdf57c698965eec275412753e5add573a33686084613 | cac1d110c90f0e4cb262aa882ede5e3067c8da2c |
| src/stats/explore_models.py | ロジスティック回帰の推定（fit_logistic_cols。naive.fit_logistic とビット単位で同じ）と予測 | bae60264bf66af1c512d85d500725b28e0f9982780ea074bb09e1359ec72f432 | cac1d110c90f0e4cb262aa882ede5e3067c8da2c |
| src/stats/explore_graph.py | ラベル伝播・無向グラフ（2歩先の隣は explore_chain.hop_lists。T-119 の hop_signals と同じ値になることをテストで確かめた） | e13ec18c180e29cd45a56d31453e333d0d86b11de51741e8f4d56dcd4cfbac55 | fea6a30141b14a4f50e45e8531392cf82c203aa5 |
| src/stats/explore_denominator.py | 分け方（split_rows）、素朴な予測の列の名前（import でつながる） | 55f292c869915006f771b49aa062c84ca5ce1928e204f6a858345b31b3062588 | b319313b50494f5328a2a49fefe55dcaf10a66d5 |
| src/stats/explore_diffusion.py | （import でつながる。段の計算では使う関数は無いが、読み込まれる） | 05bcc0598dc59aaf098c92c0411b8d6475bbdf7dad2b17ffe78fbc6165b291bd | 7fd8c47d69747c2ef16a943995d577bf478777cb |
| src/stats/explore_diffusion2.py | （import でつながる。own_code_shas） | 31826ada9946166c64d689634e555a9b77db5e56fa6ce37f6abc18e64d8d8d22 | c81ed9629b65682d10709743e97f1906f29da436 |
| src/stats/explore_sea.py | 系統の海域（family_seas）など | 1fe1854fb176adfbcc2d353331f4e230e72e95ad7dd7ce651f363c1363472d54 | 9c918b0c58ba3fbe17dbd966da2592eb6a7e7a0f |
| src/stats/explore_chain.py | 連鎖の励起（高い状態・続いた週数・重み・1歩・2歩・系統・群れの平均）、月ごとの網 | f384b64eff9799933218cf70c67d31d57fefd5b067a3ab062e5927db0254f0cb | 9d98f45675133759a119679ecda8169e7f9a2a4a |
| src/stats/explore_tiers.py | 段1・段2 の確率、nbwave、段4 の列の名前 | 9fc7aae626c9445cb980fa059b5f0dab96b81e2d4c672adecd847e1a4c73e84c | c4ff224959b39bc256242ca7b384f19630fdfd77 |
| tests/stats/test_explore_models.py | fit_logistic_cols と naive.fit_logistic がビット単位で同じことの確かめ | 92615f85bf2d6b85b46794f72cf724e688b797db538e557dd649841e3d9e85d2 | cac1d110c90f0e4cb262aa882ede5e3067c8da2c |

- run.json の `code` の欄にある残りの candidates.py・counting.py は、順番1〜5 などで封印済みの版を、explore_islands.py が sha256 で照らしてから読む。
- docs/stats/order8-t145/ のファイルは、$HOME/Desktop/news-stick-data/order8-t145/ の出力と同じバイト列（写し）。

## 5. 出力を作り直す手順

プロジェクトのルートで、TMPDIR を一時のフォルダにして流す。書き出す先に同じ名前のファイルがあれば止まる（上書きしない）。

1. 順番7・順番8・段の係数（11ファイル。約14分、10コア）
   ```
   .venv/bin/python -B src/stats/order8_fit.py --t117-cache <explore-t117-cache/run2> --out-dir <新しいフォルダ>
   ```
   - 入力：手法を作る期間の日の集計から作ったキャッシュ（explore-t117-cache/run2。phase1.json の sha256 は 3c71b39e14ed657365ed538ac912e971ac66c47c6a0ed79aceb336af0a36caa5（explore_signals の KNOWN_CACHE_PHASE1_SHA256）で、キャッシュの中のファイルは phase1.json に書いた sha256 と照らしてから読む）、封印の記録から読むタグの一覧・V・欠けた日（explore_islands.load_context）、21組の表（docs/stats/tiers-select-t142/tiers_select.tsv。sha256 を照らしてから読む）。
   - Python 3.14.2 で流した（v2、T-145。約14分）。統計係の流し直し（別のフォルダ）で、11ファイルすべての sha256 が同じだった。
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

## 7. 前向きの入力の作り方と、periods のきっかけの値の整理

### (1) 前向きの入力の作り方（決定（2026-10-20 オーナー、reviews/T-145.md）。採点計画 2章 (7)）
- 段2 の履歴：2016-04-11 から t − ceil((H + 1) / 7) 週までの月曜の状態と判定を、手法を作る期間と同じ規則で数える。案A（採った形）：区画の境目とエンバーゴの週を含むすべての月曜を続けて数える。案B（採らなかった）：各期間の予言日の範囲の月曜だけを数える。
- chain の続いた週数 d：案C（採った形）：予言日から前へ最大52個の月曜までだけを数える（d ≤ 52）。案A（採らなかった）：2016-04-11 から区画の境目で数え直さずに続けて数える（当てはめと同じ数え方）。案B（採らなかった）：前向きの最初の予言日から数え始める（その時点で続いている「高い」状態が終わるまで、当てはめとずれる）。
  - 当てはめ（d に上限なし）との差：d > 52 のときの重みは、上限なしで exp(−26) ≈ 5.1e-12 以下、上限ありで exp(−51/2) ≈ 8.4e-12。手法を作る期間のすべてのタグ・すべての予言日で d の最大は 36 で、d > 52 の組は0件、上限を付けても対象の行の chain の値は変わらなかった（T-146、docs/stats/chain-cap-t146/）。
- 欠けた日：それぞれの区画で封印した欠けた日の一覧と、前向きの予言の欠けた日の決まりで決める。判定不能の行は数えない。

### (2) 予言の入力が読む過去と、periods のきっかけの値（事実と案）
事実（periods.md 8章 (1) のきっかけの値は、手法を作る期間の予言日の範囲の始まり（区画の始まり + 400日）を決めるためのもの）
| 入力 | 予言日 t の入力が読む最も古い日 | 手法を作る期間の中で |
|---|---|---|
| 素朴な予測の特徴量 | t-399 | 区画の中（naive_history_days = 399 ≤ 400） |
| 普段の水準・冷却 | t-371・t-62 | 区画の中 |
| 共起の網（予言日を含む月の前の12か月） | 最大 t-396（12か月が366日の年と、月の31日目の予言日） | 区画の中（≤ 400） |
| 段2 の履歴（全期間、2016-04-11 から） | 2016-04-11 の予言日の入力の最も古い日（2015-03-09）。t によらず一定で、t が進むと t からの日数は延びる | 区画の中（履歴は手法を作る期間の予言日だけで、読む日は 2015-03-09 以降） |
| chain の d（案C。採った形） | 約 t-728 で一定（51週の月曜と、そのそれぞれの普段の水準が読む371日） | 区画の中（手法を作る期間では d を 2016-04-11 からしか数えないので、読む日は 2015-03-09 以降） |
| chain の d（案A。採らなかった） | 段2 と同じ（2015-03-09） | 区画の中 |

- 手法を作る期間では、段2 と chain の履歴は 2016-04-11 から始まるので、読む日はすべて区画の中（2015-03-02 以降）に収まり、periods の区切りの作り直しは要らない。
- 閾値を決める期間・基準値を測る期間・前向きの予言では、段2 は前の区画のデータを過去として読む（400日を超え、時間とともに延びる）。chain（案C）も約728日を読むので、400日を超える。periods.md 3章 (3) は、過去の方向に入り込むことを許している（状態も前の区画のデータから続けて計算する、と書いている）。判定が読むデータは、エンバーゴでそれぞれの区画の中で終わる。
- きっかけの値の整理（案。periods の記録に何を足すかは封印係と決める）
  - 素朴な予測の過去分：399（順番7。この文書の 2章）。
  - 共起の網を作る期間：最大 396 日。400 以下なので区切りは変わらない。採点計画で網を段4・N3・N4 の入力にすると決めたので、きっかけの値として記録に足す案がある。
  - 段2 の履歴と chain の d（約728日）：手法を作る期間の中では区画の中に収まり、手法を作る期間の予言日の範囲の始まりを変えない。periods.md 8章 (1) の四つのきっかけのどれにも当たらない。記録には「区画をまたいで過去を読む入力」として、読む範囲（上の表）を書き添える案がある。
  - 過去数年の同じ週の年数 N：使わない（未決事項2 の決定）。
  - J：candidates の封印済みの値のとおり（この文書では扱わない）。

## 8. 気づいたこと（判断が要るもの。統計係は決めていない）

1. 予言の曜日：前向きの予言日は月曜に決まった（2026-10-20 オーナー、reviews/T-143.md）。21組の係数と21組の表は月曜の予言日で作ったので、作り直しは要らない。
2. 7章 (1) の前向きの入力の作り方は、2026-10-20 にオーナーが決めた（段2 は案A、chain の d は案C。reviews/T-145.md）。
3. 順番6の「改訂なし」を記録にどう書くか（kind の名前と、何を参照するか）は、封印係が決める。

## 引用
Data: The GDELT Project (https://www.gdeltproject.org/). This project is not affiliated with or endorsed by the GDELT Project.

データ出典：GDELT Project（https://www.gdeltproject.org/）。本プロジェクトは GDELT Project と提携・承認の関係にありません。
