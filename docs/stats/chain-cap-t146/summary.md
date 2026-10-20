# chain の続いた週数 d の上限 52 の確かめ（T-146、手法を作る期間）

この文書は `src/stats/chain_cap_check.py` が出力したもので、手で書き足していない。係数は作り直していない。

- 「高い」状態の続いた週数 d が 52 を超えたタグと予言日の組：0（タグ 0、すべてのタグ・すべての予言日。d の最大 36）。
- そのうち対象の行（状態 target）の組：0（対象の行 292625）。
- d を min(d, 52) にしたときの、対象の行の chain の4つの列（D = 1、λ = 2）の差の絶対値の最大：0.0。
- 重み：d > 52 のとき、上限なしの重みは 5.109089028063325e-12 以下、上限を付けた重みは 8.423463754468647e-12。1つのタグあたりの差はこれ以下で、重み付き平均の差もこれ以下になる。
- 読んだ日の範囲：2015-03-09〜2020-10-12（区画の中）。Python 3.14.2。

- src/stats/candidates.py：sha256 21b5838782991596057be2fdffdeac596bf4548517ef077e5c4547a719512e89
- src/stats/chain_cap_check.py：sha256 c95412c1d9b2ed52fb55aaff86b919639d1ad65dbfe55d2cbc78b1752bce262a
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
- src/stats/periods.py：sha256 81de229d065196a26e15d90c5a80eb1043ca534a6eaf66cdebd36285ae087605
- src/stats/scoring.py：sha256 ae30815f5690bf3d9faaabcdb25cce821c8c627282620e1e705220f79a9a4300

## 引用
Data: The GDELT Project (https://www.gdeltproject.org/). This project is not affiliated with or endorsed by the GDELT Project.

データ出典：GDELT Project（https://www.gdeltproject.org/）。本プロジェクトは GDELT Project と提携・承認の関係にありません。
