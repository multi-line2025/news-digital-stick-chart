# デジタル・スティックチャート：ニュースの島プロジェクト

English summary: This repository records a pre-registered attempt to predict which currently quiet news themes (from GDELT theme coverage) will later become news. At this stage it publishes only a trial run on the oldest of three historical periods (the method-building period, 2015-2020). No forward predictions have been made yet, and the data of the other two periods have not been touched. Seals are recorded in an append-only hash chain with OpenTimestamps proofs.

## 1. 目的

ニュースの話題を表すタグの一覧を、事前に機械的な規則で決めて封印する。予言の時点で報道の少ないタグのうち、一定期間のあとにニュースになるもの（このプロジェクトでは「島」と呼ぶ）を、対象のタグすべてに確率として付けて予言し、封印したうえで後から答え合わせをする。比べる相手は素朴な予測（静かなタグは静かなまま、予定された行事は予定どおり）である。後から選んだり直したりしていないことを、第三者が記録から確かめられる形にすることを目指している。

## 2. 今の段階

- このリポジトリで公開しているのは、試運転の結果である。試運転には、過去データを三つに分けた期間のうち、最も古い「手法を作る期間」の区画（2015-03-02〜2020-12-14）のデータだけを使った。
- ほかの二期間（閾値を決める期間・基準値を測る期間）のデータには手を付けていない。
- 前向きの予言はまだ始めていない。predictions/ に予言は無い。
- 試運転の結果を公開するかどうかは、オーナーが結果を見てから決めた（reviews/T-130.md）。
- 期間の区切りの日付は docs/stats/periods.md 1章にある。

## 3. どこに何があるか

| 場所 | 中身 |
|---|---|
| sealed/ | 封印の記録。sealed/ledger.jsonl が追記のみの記録の鎖（1行1件、各行に直前の行のハッシュを含む）で、封印した中身のファイル（JSON）が同じフォルダにある。時刻証明は OpenTimestamps の `ledger.jsonl.seqNNNNNN.ots`（確定したものは `.bitcoin.ots` と、照合に使う Bitcoin のブロックのヘッダ `bitcoin-header-<高さ>.hex`）。取得の開始などの一部の記録は、中身に drand の回を含む |
| docs/verify/ | 第三者向けの検証の手順。封印の記録の照合は docs/verify/periods-seal.md、X に投稿したハッシュとの照らし方は docs/verify/x-post.md |
| docs/stats/ | 統計係の文書。期間の区切り（periods.md）、閾値と判定期間の候補（candidates.md）、報道量の数え方（counting.md）、タグの一覧の規則と素朴な予測・採点計画の一部（tags-naive.md、naive-scoring.md）、タグの一覧の結果（order5-tag-list.md）など |
| docs/stats/explore/ | 試運転の探索の要約。docs/stats/explore/README.md に読む順と、各要約が何を見たかがある |
| docs/stats/trial-limits.md | 試運転の公開物の限界。事実と出どころを並べている |
| docs/method.md | オーナーの手法の方針書 |
| CLAUDE.md | プロジェクトの決定事項と、チームの運用の規則 |
| src/、tests/ | コードとテスト。係ごとに collector（収集）・sealer（封印）・stats（統計）に分かれる |
| data/manifest/ | 生データの各ファイルのハッシュ値・取得日時・取得元の一覧。生データの本体は Git の外に置き、このリポジトリには入れていない |
| reviews/ | チームの採点の記録と、オーナーの発言の原文 |
| .github/workflows/privacy-scan.yml | push のたびに、全履歴にメールアドレスの形の文字列が無いことを確かめる |

### 履歴の作り直し

2026-10-19 に、オーナーの承認を得て、Git の履歴を一度だけ作り直した。公開の前の監査で、島の結果の公開では伏せると決めていたテーマの名前が、履歴の中の2か所に残っていたためである。作り直したのは 2026-10-16 の採点の記録から後のコミットで、封印の記録を含むそれより前のコミットのハッシュは変わっていない。作成者・日時・メッセージは元のままで、変えたのはファイルの中身だけである。古いハッシュと新しいハッシュの対応表は reviews/T-133.md にある。経緯は reviews/T-130.md と docs/stats/trial-limits.md 4.2 にある。

## 4. 封印の照合の始め方

必要なのは git と python3（標準ライブラリだけ）である。リポジトリを clone し、そのルートで次を実行する。

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -B src/sealer/verify.py all --rev auto
```

終了コードが 0 で「すべての検査に通った。」と出れば、記録の鎖、時刻証明の対象、封印した対象のファイルのハッシュなどの照合が通っている。終了コード 0 は、照らした検査が通ったことだけを示す。Git の外のファイルを渡さなかったために照らさなかった項目は、出力の最後の行に並ぶ。この検査で確かめていないこと（ヘッダが Bitcoin の本当の鎖にあること、drand の署名）と、それぞれの確かめ方は、docs/verify/periods-seal.md の 3章・5章・7章にある。

## 5. タグの一覧の detail

- タグの一覧の要約（main）は、封印の記録 seq 17 の中身 sealed/stats-order5-2c7a584ec7891d23bca65c3eb39fb04991cdade3975ccfa4bfb5bcf0b48aeaae.json に入っている。
- テーマごとの理由（四半期ごとの件数・平均・当たった除外の語など）を含む detail（ファイル名 `order5-detail.json`、数十MB）は Git に入れず、このリポジトリの GitHub のリリースに置く予定である。
- リリースから取ったファイルは、seq 17 の記録の main.outside.detail の sha256 と比べて確かめられる。

```sh
shasum -a 256 order5-detail.json
python3 -c "import json; print(json.load(open('sealed/stats-order5-2c7a584ec7891d23bca65c3eb39fb04991cdade3975ccfa4bfb5bcf0b48aeaae.json'))['main']['outside']['detail']['sha256'])"
```

- 二つの値が同じであればよい。記録にある値は `e1dbd35e85451bf1718956a90369bdb5c4ebadca48be75fdc04af97be787b5cd` である。
- 検証のコードで照らす場合は、detail を置いたフォルダを渡す（docs/verify/periods-seal.md 19章）。extra は今回のリリースに置かないので「置き場所に無い」と出る。

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -B src/sealer/verify.py stats-order --order5-outside <detail を置いたフォルダ>
```
- リリースには、GDELT の元のファイルと、公開しないと決めた表は置かない。

## 6. X への投稿

X に投稿しているのは、封印の証明（記録の鎖の先頭のハッシュと時刻）だけである。投稿したハッシュの照らし方は docs/verify/x-post.md にある。

## 7. データの出典

Data: The GDELT Project (<https://www.gdeltproject.org/>). This project is not affiliated with or endorsed by the GDELT Project.

データ出典：GDELT Project（<https://www.gdeltproject.org/>）。本プロジェクトは GDELT Project と提携・承認の関係にありません。
