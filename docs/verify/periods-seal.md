# 期間の区切りの封印を検証する手順（T-005）

この文書は、第三者が次の四つを自分で確かめるための手順である。

1. 封印の記録（`sealed/ledger.jsonl`）の鎖が正しいこと
2. 封印した対象のファイルのハッシュが、記録と一致すること
3. 時刻証明（OpenTimestamps）が正しいこと
4. 封印と、試運転の手順3（GDELT のファイル一覧の取得）との前後。何が示せて、何が示せないか（7章）

封印したことは、現時点では公開していない（オーナーの決定）。公開するかどうかは、試運転のあとでオーナーが判断する。

`<!-- test:offline -->` の印が付いたコマンドの塊は、`tests/sealer/test_verify_doc.py` が実行する。このテストは、リポジトリを手元に複製し、この文書からコマンドを取り出して、そのまま実行する。壊した複製では同じコマンドが失敗することも、同じテストで確かめている。

## 0. 用意

- 必要なもの：git、python3（標準ライブラリだけを使う）、`shasum`（Linux では `sha256sum` でもよい）。
- 時刻証明が Bitcoin に入っていることを確かめるときだけ、OpenTimestamps のクライアント（`ots`）を使う。
  ```sh
  python3 -m venv .venv
  .venv/bin/pip install opentimestamps-client
  ```
- コマンドはすべて、リポジトリのルートで実行する。`__pycache__` を作らないよう、python には `-B` と `PYTHONDONTWRITEBYTECODE=1` を付ける。

## 1. 記録の形と規則

記録は JSON Lines で、1 行が 1 件。各行のキーは次の6つだけで、ほかのキーがあれば検証で失敗になる。

| キー | 中身 |
|---|---|
| `seq` | 通し番号。1 から始まり、行の順に 1 ずつ増える |
| `prev_hash` | 直前の行のバイト列（末尾の改行を含めない）の sha256。1 行目は 0 が 64 個 |
| `kind` | 種類。下の表 |
| `targets` | 対象のファイル。各要素は `path`（ルートからの相対パス）、`role`、`sha256` |
| `recorded_at` | 記録した日時（UTC）。記録した機械の時計による申告で、証明ではない |
| `note` | 注記 |

| `kind` | 中身 | 対象の `role` | 作る仕組み |
|---|---|---|---|
| `periods` | 期間の区切り | doc / code / test / output | `src/sealer/seal_periods.py` |
| `periods-triggers` | 区切りを作り直すきっかけの値（docs/stats/periods.md 8章 (2)） | triggers | `src/sealer/seal_triggers.py` |
| `acquisition` | 試運転の手順3の取得の記録（形式の案は 7章。まだ無い） | acquisition | 後のタスク |

行は正規の形（キーを並べ替え、区切りに空白を入れず、UTF-8）で書く。同じ中身を別の書き方で書いた行は、検証で失敗になる。

規則（コードは `src/sealer/ledger.py`）。

- **追記のみ。**
  - 記録の仕組みは、記録のファイルを追記のモードでだけ開く。
  - 出力の JSON・きっかけの値の JSON・`.ots` は、新しいファイルとしてだけ作る。既にあれば上書きしない。
  - 誤りの訂正は、新しい番号の記録として出す。
- **すべての seq に、その seq 自身の時刻証明が要る。**
  - 記録を 1 件追記するたびに、先頭からその行までに `.ots` を付ける（`sealed/ledger.jsonl.seqNNNNNN.ots`）。
  - どれか一つでも欠けていれば、検証は失敗する。途中の `.ots` を出すか出さないかで、採用される版を選べないようにするため。
- **版の番号は記録に書かない。** その種類の記録の何件目かで決まる（`version_of`）。`periods` の1件目が v1 である。
- **採用の規則。** 同じ種類の記録が期限前に複数ある場合は、**期限前の最後の追記**（`seq` が最大のもの）だけを有効とする（`adopted_record`）。
  - 「期限前」は `recorded_at`（申告）では決めない。時刻証明で決める。
  - 記録 k の時刻には、**seq k 自身の `.ots`**（と、その upgrade の `.bitcoin.ots`）が Bitcoin で確定した時刻だけを使う。後の seq の `.ots` の時刻では代わりにしない。
  - Bitcoin で確定していない（Pending の）記録は、「期限前とは示せない」として扱う。
  - 確定した時刻に安全の幅 3 時間を足しても期限より前なら、期限前とする。
  - 期限は、手順3の取得の記録（`kind` が `acquisition` の最初の記録）に入れた drand の回の公開時刻とする（7章）。その記録が無いうちは、期限は未確定で、採用の判定は保留する。
- **安全の幅 3 時間の根拠。**
  - Bitcoin のブロックに書く時刻は、直前 11 ブロックの時刻の中央値より後であればよい（median time past の決まり）。
  - 中央値は 6 ブロック前、平均で約 1 時間前にあたる。そのため、ブロックの時刻は、実際に掘られた時刻より 1 時間ほど早く書かれうる。
  - その 1 時間に、ブロックの間隔のばらつきの分の余裕を足して 3 時間とした。
  - 掘り手の大多数が共謀して時刻をずらす場合は、この幅では足りない。この前提を置いている。
- **きっかけの値と deadline_status の照合**（`judge_deadline_status`）。
  - `periods` の出力の `rebuild_triggers` を、期限前と示せる最後の `periods-triggers` の記録と比べる。完全に一致すれば `before_deadline`、そうでなければ `after_deadline` が、記録から決まる値である。
  - 出力の `deadline_status`（統計係の申告）がこれと違えば、失敗になる。次の二つの誤りを、どちらも検出する。
    - `before_deadline` と申告したが、期限前とは示せない場合
    - `after_deadline` と申告したが、期限前と示せる場合
  - きっかけの値が無い出力（v1 の形）では、`deadline_status` は null でなければならない。
  - 期限が未確定のうちは、この照合を保留し、そのことを出力に出す。
- **区画の一致。**
  - `periods` の2件目以降の出力の `block_start` と `block_end` は、1件目（最初に封印した版）の出力と一致しなければならない（`check_blocks`）。
  - 封印の仕組みは、一致しない版を追記しない。仕組みを通さずに追記された場合も、3章の検証（`periods`）で見つかる。
- **最初の版を封印する時機。**
  - 封印の仕組み（`src/sealer/seal_periods.py`）は、`data/` の下のどこか（`.gitignore` の対象の `data/raw` を含む、すべてのサブフォルダ）に `.gitkeep` 以外のファイルがあれば、`periods` の1件目を封印しない。
  - 調べるのは、このリポジトリの `data/` の下だけである。Git の外の置き場や、ほかの機械は調べられない。そのため、これは手元の検査にすぎない。

## 2. リポジトリを手元に用意する

```sh
git clone <リポジトリの場所> stick-chart-check
cd stick-chart-check
```

## 3. 記録の鎖・対象のハッシュ・区画・期限をまとめて確かめる

<!-- test:offline -->
```sh
PYTHONDONTWRITEBYTECODE=1 python3 -B src/sealer/verify.py all --rev auto
```

終了コードが 0 で「すべての検査に通った。」と出れば、次のことが確かめられている。

- `chain`：各行が正規の形であることを確かめる。あわせて、`seq` が 1, 2, 3, … と欠番なく続き、`prev_hash` が直前の行の sha256 と一致することも確かめる。
  - 行の書き換え・削除・挿入・入れ替えがあれば失敗する。
  - 最後の行の書き換えと、末尾の行の削除は、次の `anchors` で見つかる。
- `anchors`：
  - すべての seq に、その seq 自身の `.ots` があることを確かめる。
  - 各 `.ots` の対象のハッシュが、記録の先頭 N 行の sha256 と一致することを確かめる。
  - 各 `.ots` の証明の状態（Pending か、Bitcoin のどの高さか）を表示する。
- `targets --rev auto`：
  - 各記録について、その記録を最初に含んだコミットを Git の履歴から探す。そのコミットの中の対象のファイルの sha256 が、記録と一致することを確かめる。
  - 対象のファイルが後で書き換えられても、封印した時点の中身で確かめられる。
  - 履歴の中で記録そのものが書き換えられていれば失敗する。
- `periods`：
  - すべての版の区画の境目が、1件目と一致することを確かめる。
  - `deadline_status` を記録と照合する。期限が未確定のうちは保留する。
- `adopted`：期限（未確定ならそのこと）と、各記録の状態を表示する。状態は「期限前と示せる」「期限前とは示せない（Pending）」「期限前とは示せない（期限以後）」「保留」のどれか。採用される版も表示する。

**この検査では、時刻証明が Bitcoin の本当の鎖に入っているかは確かめない。** それは 5章の `ots verify` で確かめる。出力の最後にも、そう表示する。

現在の記録（seq 1 だけ、`.ots` は Pending、取得の記録は無い）では、次のように出る。

- `anchors`：seq 1 が「Pending」で、Bitcoin で確定していない。
- `adopted`：「期限：未確定」。seq 1 は「保留（期限が未確定）。この seq 自身の .ots は Pending」。

`all` の代わりに `chain`、`anchors`、`targets`、`periods`、`adopted` を一つずつ実行してもよい。

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

記録が2件以上になったら、次のことも確かめる。

- N 行目の `prev_hash` が、N−1 行目の末尾の改行を除いたバイト列の sha256 と一致すること。
- 先頭 N 行の sha256 が、`sealed/ledger.jsonl.seq00000N.ots` の対象と一致すること。

```sh
sed -n 1p sealed/ledger.jsonl | tr -d '\n' | shasum -a 256      # 2 行目の prev_hash と比べる
head -n 2 sealed/ledger.jsonl | shasum -a 256                    # seq000002.ots の対象と比べる
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
# 証明を確かめる（Bitcoin のノードか、下の代わりの方法が要る）
.venv/bin/ots verify -d "$(head -n 1 sealed/ledger.jsonl | shasum -a 256 | cut -d' ' -f1)" \
    sealed/ledger.jsonl.seq000001.ots
```

- `ots info` の `File sha256 hash` が、4章の最後のコマンドの値と同じであること。
- `ots verify` は、Bitcoin で確定していれば「Success! Bitcoin block <高さ> attests existence as of <時刻>」と出す。この時刻が、seq N の記録が存在した時刻の上限である。
  - ブロックを確かめるために、手元の Bitcoin Core のノード（刈り込んだものでもよい）が要る。
  - ノードが無い場合は、https://opentimestamps.org/ の画面に、`.ots` と `head -n 1 sealed/ledger.jsonl` で作ったファイルを渡して確かめる。
  - または、`ots info` が示すブロックの高さとマークルルートを、複数のブロックエクスプローラーで見比べる。
- 確定前の `.ots` では「Pending confirmation in Bitcoin blockchain」と出る。seq 1 の `.ots` は封印の直後のもので、この状態である。この段階では、カレンダーが受け取ったことしか示せない。

### 確定した時刻を verify.py に渡す（自由な値では通らない）

`verify.py` は、期限との比較に使う確定の時刻を、**利用者が入力した時刻からは取らない**。取り方は次のとおり。

- seq 自身の `.ots` の中の Bitcoin の証明（高さ）に対して、その高さのブロックのヘッダ（80 バイト）を照合する。照合に通ったヘッダの時刻を使う。
- ヘッダは、`sealed/bitcoin-header-<高さ>.hex` のファイル（後のタスクで仕組みが書く）か、`--btc-header <高さ>=<ヘッダの16進>` で渡す。
- 照合する中身（`src/sealer/otsfile.py`）は次の三つで、どれかが通らなければ失敗になる。
  1. ヘッダのマークルルートが、`.ots` の証明の木で計算した値と一致すること
  2. ヘッダのハッシュが、ヘッダ自身の目標値以下であること（作業量の証明）
  3. その目標値が、下限（2^77 回分のハッシュ）より難しいこと
- `.ots` の中に無い高さのヘッダを渡すと、エラーで止まる。
- ヘッダが本当の鎖の、その高さのブロックかどうかは確かめない。出力されるブロックのハッシュを、自分のノードやエクスプローラーで見比べること。

```sh
# 自分の Bitcoin のノードからヘッダを取る例
H=<.ots の中の高さ>
HDR=$(bitcoin-cli getblockheader "$(bitcoin-cli getblockhash $H)" false)
PYTHONDONTWRITEBYTECODE=1 python3 -B src/sealer/verify.py adopted --btc-header "$H=$HDR"
```

### 確定前の .ots を upgrade する

`ots upgrade` は、そのままでは `.ots` を書き換える。封印済みのファイルは追記のみなので、運営側は次の仕組みを使う。

- 元の `.ots` の写しを、一時的な場所で upgrade する。
- Bitcoin の確定が入っていれば、元の `.ots` を残したまま `sealed/ledger.jsonl.seqNNNNNN.bitcoin.ots` を新しく書く。
- まだ確定していなければ、何も書かずに終了コード 1 で終わる。時間をおいて再実行する。

```sh
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -B src/sealer/stamp.py upgrade --seq 1
```

第三者は、運営側の upgrade を待たずに、自分の写しで upgrade してよい。

- カレンダーは、誰にでも同じ証明を返す。そのため運営側は、upgrade を出さないことで結果を変えられない。
- どの seq の `.ots` も、第三者が自分で確定させられる。

```sh
cp sealed/ledger.jsonl.seq000001.ots /tmp/check.ots
.venv/bin/ots upgrade /tmp/check.ots
.venv/bin/ots verify -d "$(head -n 1 sealed/ledger.jsonl | shasum -a 256 | cut -d' ' -f1)" /tmp/check.ots
```

### 通信するもの

- `ots stamp` が公開カレンダーに送るのは、記録の先頭 N 行の sha256 に 16 バイトのランダムな値（nonce）を付けて、もう一度 sha256 にしたものだけである。記録の中身も、記録の sha256 そのものも送らない。
- seq 1 の封印のとき（2026-10-05T21:41Z ごろ、UTC）に送った先は、次の4つである。
  - `https://a.pool.opentimestamps.org`
  - `https://b.pool.opentimestamps.org`
  - `https://a.pool.eternitywall.com`
  - `https://ots.btc.catallaxy.com`
- `ots info` に出るカレンダー（`alice.btc.calendar.opentimestamps.org` など）は、これらの集約先の実際のカレンダーである。

## 6. 採用される版を確かめる

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -B src/sealer/verify.py adopted [--btc-header <高さ>=<ヘッダ>] ...
```

- 期限は、記録の中の取得の記録（7章）から決まる。コマンドの引数で期限を渡すことはできない。
- 各記録の状態と、種類ごとの採用される版が出る。
  - 期限前と示せる記録が無ければ、「採用される版は無い」と出る。
  - 期限が未確定なら、「保留」と出る。

## 7. 封印と試運転の手順3との前後

### 取得の記録の形式（案。後のタスクで作る）

手順3でファイル一覧を取得する仕組みは、次の順で動くことを提案する。

1. drand の最新の回（回の番号・randomness・signature）を取る。
2. 下の JSON を `sealed/acquisition-<sha256>.json` として書き、記録に `kind: "acquisition"` の行を 1 件追記する。その seq 自身の `.ots` を作る。
3. そのあとで、ファイル一覧を取得する。

```json
{
  "step": 3,
  "drand": {
    "chain_hash": "52db9ba70e0cc0f6eaf7803dd07447a1f5477735fd3f661792ba94600c84e971",
    "round": 12345678,
    "randomness": "<signature の sha256 の16進>",
    "signature": "<16進>"
  },
  "ledger_head": {"seq": 1, "sha256": "<この行を足す前の、記録の先頭 seq 行の sha256>"},
  "fetch": {"code_sha256": "<取得のコードの sha256>", "kept_rows_sha256": "<捨てたあとの一覧の sha256>"}
}
```

- 検証のコード（`deadline_from_acquisition`）が今確かめるのは、次の三つである。
  - `step` が 3 であること
  - `randomness` が `signature` の sha256 であること（drand の決まり）
  - `chain_hash` が知っている鎖であること（quicknet：公開の間隔 3 秒、default：30 秒）
- 期限 T3 は、その回の公開時刻（genesis の時刻 ＋（回の番号 − 1）× 間隔）とする。
- 署名（BLS）が正しいかは、drand の公開の API（`https://api.drand.sh/<chain_hash>/public/<round>`）か drand の検証の道具で確かめる。
- 取得の記録が無いうちは、`verify.py` は「期限：未確定」と出し、採用の判定と deadline_status の照合を保留する。

### 何が示せて、何が示せないか

seq 1 の `.ots` が Bitcoin で確定し、その時刻を T1 とする。取得の記録の drand の回の公開時刻を T3 とする。T1 + 3 時間 < T3 のとき、示せるのは次の二つだけである。

1. **この系列の記録（このリポジトリの `sealed/ledger.jsonl`）の先頭 1 行は、T1 の時点で存在した。** 区切りの中身は、その行の `targets` の sha256 で固定されている。
2. **取得の記録は、T3 より後に作られた。** drand の値は T3 より前には誰にも分からないからである。

次のことは、この照合では示せない。

- **別の系列が無かったこと。**
  - 封印を公開していないので、運営側は、別の区切りを封印した別の記録をいくつか作っておき、後から一つを選んで出すことができる。それを外から見分ける方法は無い。
  - 示すには、封印した時点で、記録の先頭のハッシュ（または `.ots`）を公開しておく必要がある。
  - 公開するかどうかは、オーナーの判断を待っている。
- **記録に無い取得が、先にあったこと。**
  - 取得の記録より前に、記録を残さずにファイル一覧を取得していたとしても、この照合では分からない。
  - 示せるのは「記録に結び付いた正式な取得が T3 より後だった」ことまでである。
- **T1 + 3 時間 ≥ T3 の場合。** 封印が取得の記録より前だったとは示せない。その場合は、示せなかったことを公開物に書く。

取得の記録を同じ記録の `periods` の後の行として追記すれば、鎖の順でも前後が分かる。ただし、行の順は運営側が決められる。そのため、前後の根拠には時刻（T1 と T3）を使う。

### データの手元の跡

封印した時点で `data/` の下に `.gitkeep` 以外のファイルが無かったことは、seq 1 を含むコミット（4章の `git log` で探したもの）の中身で確かめられる。

```sh
git ls-tree -r --name-only <seq 1 を含むコミット> -- data/
```

`.gitkeep` 以外が出なければ、そのコミットにはデータが無い。`.gitignore` の対象（`data/raw`）と Git の外の置き場は、この方法では確かめられない。

## 8. 引用

この封印の対象（期間の区切り）は、GDELT のデータに適用するためのものである。区切りを決めるときに GDELT のデータは使っていない。

Data: The GDELT Project (https://www.gdeltproject.org/). This project is not affiliated with or endorsed by the GDELT Project.
データ出典：GDELT Project（https://www.gdeltproject.org/）。本プロジェクトは GDELT Project と提携・承認の関係にありません。
