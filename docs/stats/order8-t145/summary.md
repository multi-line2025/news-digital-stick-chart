# 順番7・順番8 と段4・N3・N4 の係数（T-145、封印の前の出力）

この文書は `src/stats/order8_fit.py` が出力したもので、手で書き足していない。封印していない（封印は封印係が行う）。テーマの名前は載せていない。

## 1. ファイル

| ファイル | 中身 | sha256 |
|---|---|---|
| periods-order7.json | 順番7：periods.py --naive-history-days 399 --deadline-status before_deadline の出力 | 00cc722724347c6e8fe38d6bde1d6ecd21abcf80c8baec31e59b75bebcf2b02c |
| naive.json | 順番8：naive.py の出力（引数なし） | 3fa64ef423e948446f5696e31ebd621440cb9910dbbf8ce40f67c0726b80951b |
| scoring.json | 順番8：scoring.py の出力（引数なし） | dbbad062aade5eb0578e4b9a13cf4ef2cad3fdd8e3ec5105b3c461f64d87e2bb |
| naive_coefs.tsv | 順番8：素朴な予測の21組の係数 | 684a196098b60340a8f4d09320b515d072c195a4a015f887a4b8ecfabdf2ceb5 |
| tier4_coefs.tsv | 段4 の21組の係数（21組の表の選んだ形） | 57680479f8f2d36799f0744aba92867fb95104a7420d36dacef9c72691cdede1 |
| n3_coefs.tsv | N3 の21組の係数 | 0c4cb4c26b177ef2a72139c79520a0b5510dd2401797ab28d77cb7af0325e15a |
| n4_coefs.tsv | N4 の21組の係数 | f8e0a2c353add2b1fe9c03489940fa188cb8321b4f57a9297f8d0e1215aecfe9 |
| tier1_null_fix.tsv | 段1 の null_fix の定数（全21組） | 0de7a69c5540012babfb5b41ce30c36e8a03091df4da496c4b603b21aa15083b |
| forms.tsv | 21組の選んだ形（tiers-select-t142 の表から） | b5dbb9813c9527fe8692343b82468d11b4bfda7ce42bdc39d4c688236334421c |

## 2. 当てはめ
- 行：手法を作る期間のすべての予言日（method period, 232 dates）の、状態が target で、判定期間 H の7つの倍率の判定がどれも判定不能でない行。行の数：H = 14 で 292625、H = 28 で 292625、H = 56 で 292625。
- 行は予言日・タグ名の昇順。推定は em.fit_logistic_cols（naive.fit_logistic とビット単位で同じ）、リッジ 1（切片にも掛ける）。当てはめは 84 個で、すべて収まった。
- N3・N4 の学習の行（v2。オーナーの決定 B、2026-10-20。T-143 の係数を見たあとの規則の変更）：予言日の時点で判定が確定した予言日（2016-04-11 から数えた月曜。タグによらない週の数）が 52 以上の行だけ。行の数：H = 14 で 216373、H = 28 で 214304、H = 56 で 209829。段3・段4 の行は上と同じ（変えていない）。変更前（T-143、order8-t143）の係数も残して公開する。
- 段2 の確率（N3・N4 の入力）は、行の予言日の時点で判定が確定した行だけで作った（全期間は 2016-04-11 から）。
- 21組の表：docs/stats/tiers-select-t142/tiers_select.tsv（sha256 13a2784652964f0e1da23d28cba0970744ab8aadcbc715a35edfcf982ffc30b6 を照らしてから読んだ）。
- 日の比率は ReadGuard（入力は t-399〜t-1、判定は t+1〜t+H）。読んだ日の範囲は 2015-03-09〜2020-11-09（区画の終わり 2020-12-14 より前）。網は予言日ごとに網の最後の日 < 予言日を確かめた（最後の日 − 予言日の最大 -1 日）。

## 3. 再計算
```
.venv/bin/python -B src/stats/order8_fit.py --t117-cache <explore-t117-cache/run2> --out-dir <書き出す先>
```
- Python 3.14.2。
- src/stats/candidates.py：sha256 21b5838782991596057be2fdffdeac596bf4548517ef077e5c4547a719512e89
- src/stats/counting.py：sha256 6f25985b21cd8ac93680b81308f3d1860b4ae6496577e10141d1e17ecf8c9fd3
- src/stats/explore_chain.py：sha256 f384b64eff9799933218cf70c67d31d57fefd5b067a3ab062e5927db0254f0cb
- src/stats/explore_denominator.py：sha256 55f292c869915006f771b49aa062c84ca5ce1928e204f6a858345b31b3062588
- src/stats/explore_diffusion.py：sha256 05bcc0598dc59aaf098c92c0411b8d6475bbdf7dad2b17ffe78fbc6165b291bd
- src/stats/explore_diffusion2.py：sha256 31826ada9946166c64d689634e555a9b77db5e56fa6ce37f6abc18e64d8d8d22
- src/stats/explore_graph.py：sha256 e13ec18c180e29cd45a56d31453e333d0d86b11de51741e8f4d56dcd4cfbac55
- src/stats/explore_islands.py：sha256 ed8231f3fc9b6975bf72de52a02bc425aff82b1cc81eb02a7ff1ef876fd58a48
- src/stats/explore_models.py：sha256 bae60264bf66af1c512d85d500725b28e0f9982780ea074bb09e1359ec72f432
- src/stats/explore_sea.py：sha256 1fe1854fb176adfbcc2d353331f4e230e72e95ad7dd7ce651f363c1363472d54
- src/stats/explore_signals.py：sha256 ac29132784462c254b27bdf57c698965eec275412753e5add573a33686084613
- src/stats/explore_tiers.py：sha256 9fc7aae626c9445cb980fa059b5f0dab96b81e2d4c672adecd847e1a4c73e84c
- src/stats/naive.py：sha256 859947f442b6843a332922d5ee1159403e36e38394bfa99f64594b229c35373a
- src/stats/order8_fit.py：sha256 d7c6c469b9376a60d6a74971bb95ffee93357bc1284ae48c677f4eb550aad877
- src/stats/periods.py：sha256 81de229d065196a26e15d90c5a80eb1043ca534a6eaf66cdebd36285ae087605
- src/stats/scoring.py：sha256 ae30815f5690bf3d9faaabcdb25cce821c8c627282620e1e705220f79a9a4300
- src/stats/tiers_select.py：sha256 19e4b858109741e33ea3befa66561462bdc46710e03addcb76300de2bee3c331

## 引用
Data: The GDELT Project (https://www.gdeltproject.org/). This project is not affiliated with or endorsed by the GDELT Project.

データ出典：GDELT Project（https://www.gdeltproject.org/）。本プロジェクトは GDELT Project と提携・承認の関係にありません。
