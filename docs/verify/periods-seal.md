# 期間の区切りの封印を検証する手順（T-005）

この文書は、第三者が次の四つを自分で確かめるための手順である。

1. 封印の記録（`sealed/ledger.jsonl`）の鎖が正しいこと
2. 封印した対象のファイルのハッシュが、記録と一致すること
3. 時刻証明（OpenTimestamps）が正しいこと
4. 封印が、試運転の手順3（GDELT のファイル一覧の取得）より前であること

封印したことは、現時点では公開していない（オーナーの決定）。公開するかどうかは、試運転のあとでオーナーが判断する。

`<!-- test:offline -->` の印が付いたコマンドの塊は、`tests/sealer/test_verify_doc.py` が、リポジトリを手元に複製したうえで、この文書から取り出してそのまま実行する。壊した複製では同じコマンドが失敗することも、同じテストで確かめている。

## 0. 用意

- 必要なもの：git、python3（3.9 以上。標準ライブラリだけを使う）、`shasum`（Linux では `sha256sum` でもよい）。
- 時刻証明を確かめるときだけ、OpenTimestamps のクライアント（`ots`）を使う。
  ```sh
  python3 -m venv .venv
  .venv/bin/pip install opentimestamps-client
  ```
- コマンドはすべて、リポジトリのルートで実行する。`__pycache__` を作らないよう、python には `-B` と `PYTHONDONTWRITEBYTECODE=1` を付ける。

## 1. 記録の形と採用の規則

記録は JSON Lines で、1 行が 1 件。各行のキーは次の6つだけで、ほかのキーがあれば検証で失敗になる。

| キー | 中身 |
|---|---|
| `seq` | 通し番号。1 から始まり、行の順に 1 ずつ増える |
| `prev_hash` | 直前の行のバイト列（末尾の改行を含めない）の sha256。1 行目は 0 が 64 個 |
| `kind` | 種類。期間の区切りは `periods` |
| `targets` | 対象のファイル。各要素は `path`（ルートからの相対パス）、`role`（doc / code / test / output）、`sha256` |
| `recorded_at` | 記録した日時（UTC）。記録した機械の時計による申告で、証明ではない |
| `note` | 注記 |

行は正規の形（キーを並べ替え、区切りに空白を入れず、UTF-8）で書く。同じ中身を別の書き方で書いた行は、検証で失敗になる。

規則（コードは `src/sealer/ledger.py`）。

- **追記のみ。** 記録の仕組みは、記録のファイルを追記のモードでだけ開く。出力の JSON と `.ots` は新しいファイルとしてだけ作る（既にあれば上書きしない）。誤りの訂正は、新しい番号の記録として出す。
- **版の番号は記録に書かない。** その種類の記録の何件目かで決まる（`version_of`）。`periods` の1件目が v1 である。区切りを作り直して封印すると、件数が一つ増える。
- **採用の規則。** 同じ種類の記録が期限前に複数ある場合は、**期限前の最後の追記**（`seq` が最大のもの）だけを有効とする（`adopted_record`）。
  - 「期限前」は `recorded_at`（申告）では決めない。時刻証明で決める。
  - 記録 k が存在した時刻の上限は、`seq` が k 以上の `.ots` のうち、Bitcoin で確定した時刻の最小値である。記録は追記のみで、`.ots` は先頭から N 行目までを対象にしているので、後の `.ots` は前の記録も覆う。
  - この時刻に安全の幅（既定 3 時間）を足しても期限より前なら、期限前とみなす。Bitcoin のブロックに書かれた時刻は、実際の時刻から数時間ずれうるため。
  - 期限は docs/stats/periods.md 8章 (2) のとおり、閾値を決める期間の区画（2020-12-15 以降）の情報を最初に「扱う」時点である。
- **区画の一致。** `periods` の2件目以降の出力の `block_start` と `block_end` は、1件目（最初に封印した版）の出力と一致しなければならない（`check_blocks`）。封印の仕組みは、一致しない版を追記しない。仕組みを通さずに追記された場合も、手順 5 の検証で見つかる。
- **最初の版を封印する時機。** 封印の仕組み（`src/sealer/seal_periods.py`）は、`periods` の1件目を、データの取得が始まった跡（`data/manifest`・`data/processed`・`data/archives` に `.gitkeep` 以外のファイルがある、または `data/raw` がある）があれば封印しない。ただし、これは手元の検査にすぎない。封印が手順3より前であることの証明は、手順 7 の照合で行う。

## 2. リポジトリを手元に用意する

```sh
git clone <リポジトリの場所> stick-chart-check
cd stick-chart-check
```

## 3. 記録の鎖・対象のハッシュ・区画をまとめて確かめる

<!-- test:offline -->
```sh
PYTHONDONTWRITEBYTECODE=1 python3 -B src/sealer/verify.py all --rev auto
```

終了コードが 0 で、最後に「すべての検査に通った。」と出れば、次のことが確かめられている。

- `chain`：各行が正規の形で、`seq` が 1, 2, 3, … と欠番なく続き、`prev_hash` が直前の行の sha256 と一致する。行の書き換え・削除・挿入・入れ替えがあれば失敗する（最後の行の書き換えと末尾の行の削除は、次の `anchors` で見つかる）。
- `anchors`：各 `.ots` の対象のハッシュが、記録の先頭 N 行の sha256 と一致する。最後の記録を覆う `.ots` があることも確かめる。
- `targets --rev auto`：各記録について、その記録を最初に含んだコミットを Git の履歴から探し、そのコミットの中の対象のファイルの sha256 が記録と一致することを確かめる。対象のファイルが後で書き換えられても、封印した時点の中身で確かめられる。履歴の中で記録そのものが書き換えられていれば失敗する。
- `periods`：`periods` のすべての版の区画の境目が、1件目と一致する。1件目の `deadline_status` は null である。

`all` の代わりに `chain`、`anchors`、`targets`、`periods` を一つずつ実行してもよい。

## 4. 検証のコードを使わずに確かめる

検証のコード（`src/sealer/verify.py`）を信用しなくても、標準の道具で同じことを確かめられる。

<!-- test:offline -->
```sh
# 記録の中身（1 行目）
head -n 1 sealed/ledger.jsonl
# 対象のファイルの sha256。記録の targets の sha256 と見比べる
shasum -a 256 docs/stats/periods.md src/stats/periods.py tests/stats/test_periods.py sealed/periods-output-*.json
# 出力を自分で作り直す。sha256 が記録の output と同じになる
PYTHONDONTWRITEBYTECODE=1 python3 -B src/stats/periods.py | shasum -a 256
# 時刻証明の対象：記録のファイルの先頭 1 行（改行を含む）の sha256
head -n 1 sealed/ledger.jsonl | shasum -a 256
```

記録が2件以上になったら、2行目の `prev_hash` は次の値と一致する（1行目の末尾の改行を除いたバイト列の sha256）。

```sh
head -n 1 sealed/ledger.jsonl | tr -d '\n' | shasum -a 256
```

対象のファイルが後で書き換えられている場合は、その記録を含んだ最初のコミットに戻してから確かめる。

```sh
git log --reverse --format='%H %ad' --date=iso-strict -- sealed/ledger.jsonl | head -n 1
git show <そのコミット>:docs/stats/periods.md | shasum -a 256
```

## 5. 時刻証明を確かめる

`.ots` は、記録の先頭 N 行のバイト列を対象にしている。ファイル名は `sealed/ledger.jsonl.seqNNNNNN.ots`。

```sh
# .ots の対象のハッシュ（File sha256 hash）と、カレンダーの一覧を見る（ネットワークを使わない）
.venv/bin/ots info sealed/ledger.jsonl.seq000001.ots
# 証明を確かめる（下の注意を参照）
.venv/bin/ots verify -d "$(head -n 1 sealed/ledger.jsonl | shasum -a 256 | cut -d' ' -f1)" \
    sealed/ledger.jsonl.seq000001.ots
```

- `ots info` の `File sha256 hash` が、手順 4 の最後のコマンドの値と同じであること。
- `ots verify` は、Bitcoin に確定していれば「Success! Bitcoin block <高さ> attests existence as of <時刻>」と出す。この時刻が、記録の先頭 N 行が存在した時刻の上限である。
  - Bitcoin のブロックを確かめるため、手元の Bitcoin Core のノード（刈り込んだものでもよい）が要る。ノードが無い場合は、https://opentimestamps.org/ の画面に `.ots` と `head -n 1 sealed/ledger.jsonl` で作ったファイルを渡して確かめるか、`ots info` が示すブロックの高さとマークルルートを、複数のブロックエクスプローラーで見比べる。
- 確定前の `.ots` では「Pending confirmation in Bitcoin blockchain」と出る。封印の直後の `.ots` はこの状態である（Bitcoin への確定には数時間かかる）。この段階では、カレンダーが受け取ったことしか示せない。

### 確定前の .ots を upgrade する

`ots upgrade` は、そのままでは `.ots` を書き換える。封印済みのファイルは追記のみなので、運営側は次の仕組みで行う。元の `.ots` の写しを一時的な場所で upgrade し、Bitcoin の確定が入っていれば、元の `.ots` を残したまま `sealed/ledger.jsonl.seqNNNNNN.bitcoin.ots` を新しく書く。まだ確定していなければ、何も書かずに終了コード 1 で終わるので、時間をおいて再実行する。

```sh
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -B src/sealer/stamp.py upgrade --seq 1
```

第三者は、運営側の upgrade を待たずに、自分の写しで upgrade してよい。カレンダーは誰にでも同じ証明を返すので、運営側は upgrade を止められない。

```sh
cp sealed/ledger.jsonl.seq000001.ots /tmp/check.ots
.venv/bin/ots upgrade /tmp/check.ots
.venv/bin/ots verify -d "$(head -n 1 sealed/ledger.jsonl | shasum -a 256 | cut -d' ' -f1)" /tmp/check.ots
```

`.bitcoin.ots` があれば、`verify.py anchors` はその対象のハッシュも記録と照合する。

### 通信するもの

- `ots stamp` が公開カレンダーに送るのは、記録の先頭 N 行の sha256 に 16 バイトのランダムな値（nonce）を付けて、もう一度 sha256 にしたものだけである。記録の中身も、記録の sha256 そのものも送らない。
- 封印のとき（2026-10-05T21:41Z ごろ、UTC）に送った先：`https://a.pool.opentimestamps.org`、`https://b.pool.opentimestamps.org`、`https://a.pool.eternitywall.com`、`https://ots.btc.catallaxy.com`。`ots info` に出るカレンダー（`alice.btc.calendar.opentimestamps.org` など）は、これらの集約先の実際のカレンダーである。

## 6. 採用される版を確かめる（期限が決まったあと）

期限（手順 7 で決まる）と、`ots verify` が示した Bitcoin の時刻を渡すと、採用される版が出る。

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -B src/sealer/verify.py adopted \
    --deadline <期限。例 2026-10-07T00:00:00Z> \
    --anchor-time 1=<seq 1 の .ots の Bitcoin の時刻。例 2026-10-06T01:23:45Z>
```

- 期限前と時刻証明で示せる記録が無ければ、終了コード 1 で失敗する（申告の `recorded_at` は使わない）。
- 採用された `periods` の版の出力が `before_deadline` 以外の作り直しであれば、`deadline_status` の申告と記録が食い違っていないかも確かめる（docs/stats/periods.md 8章 (2)）。

## 7. 封印が試運転の手順3より前であることの照合

手順3（GDELT のファイル一覧の取得）の記録の形は、後のタスクで作る。ここでは照合のしかただけを書く。

示したいのは「封印した時刻 ＜ 手順3でファイル一覧を取得した時刻」である。そのために、両側を次のように押さえる。

1. **封印の時刻の上限。** 手順 5 で、seq 1 の `.ots` が示す Bitcoin の時刻 T1 を得る。区切りは T1 には存在していた。安全の幅として 3 時間を足し、T1 + 3 時間を封印の時刻の上限とする。
2. **取得の時刻の下限。** 手順3の取得の記録には、取得の時点より前には誰にも分からなかった値を入れる必要がある（後のタスクへの申し送り）。例えば、取得の直前の drand の公開乱数（回の番号と値）や、直前の Bitcoin のブロックのハッシュである。その値が公開された時刻 T3 が、取得の時刻の下限になる。
   - 取得の記録の時刻（ファイルの日時、`recorded_at`、Git のコミットの日時）は、運営側が書ける申告なので、下限の根拠にしない。
   - ファイル一覧の中身（最新のファイルの日付）は、閾値を決める期間以降の行を捨ててから書く決まり（docs/stats/periods.md 8章 (2)）なので、下限の根拠には使えない。
3. **照合。** T1 + 3 時間 ＜ T3 であれば、封印は手順3より前である。
   - 取得の記録を、この記録（`sealed/ledger.jsonl`）に `periods` の後の行として追記すれば、鎖の順でも前後が示せる。ただし行の順は運営側が決められるので、時刻の照合（T1 と T3）を正とする。
   - T1 + 3 時間 ≥ T3 なら、封印が手順3より前とは示せない。この場合は、示せなかったことを公開物に書く。
4. **データの手元の跡。** 封印の時点で `data/manifest`・`data/processed`・`data/archives` に `.gitkeep` 以外のファイルが無かったことは、seq 1 を含むコミット（手順 4 の `git log` で探したもの）の中身で確かめられる。

```sh
git ls-tree -r --name-only <seq 1 を含むコミット> -- data/
```

`.gitkeep` 以外が出なければ、そのコミットにはデータが無い（Git の外の置き場は、この方法では確かめられない）。

## 8. 引用

この封印の対象（期間の区切り）は、GDELT のデータに適用するためのものである。区切りを決めるときに GDELT のデータは使っていない。

Data: The GDELT Project (https://www.gdeltproject.org/). This project is not affiliated with or endorsed by the GDELT Project.
データ出典：GDELT Project（https://www.gdeltproject.org/）。本プロジェクトは GDELT Project と提携・承認の関係にありません。
