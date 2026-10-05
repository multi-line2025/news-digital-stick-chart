# 期間の区切りの封印を検証する手順（T-005、T-007、T-008、T-009）

この文書は、第三者が次のことを自分で確かめるための手順である。

1. 封印の記録（`sealed/ledger.jsonl`）の鎖が正しいこと
2. 封印した対象のファイルのハッシュが、記録と一致すること
3. 時刻証明（OpenTimestamps）の対象が記録と一致し、Pending の宛先が許可した4つのカレンダーであること
4. 採用される版。採用は鎖の順番で決まり、区切りは最初の `threshold-access` の記録である（T-007、T-008。1章）
5. 閾値を決める期間に触れる記録（`threshold-access`）と、試運転の手順3の取得の記録（`acquisition-start`・`acquisition-result`）の照合。何が示せて、何が示せないか（7章）

封印したことは、現時点では公開していない（オーナーの決定）。公開するかどうかは、試運転のあとでオーナーが判断する。

`<!-- test:offline -->` の印が付いたコマンドの塊は、`tests/sealer/test_verify_doc.py` が実行する。このテストは、リポジトリを手元に複製し、複製の中のこの文書からコマンドを取り出して、そのまま実行する。使うのはコミットされた版だけで、作業ツリーのファイルは重ねない。壊した複製では同じコマンドが失敗することも、同じテストで確かめている。

## 0. 用意

- 必要なもの：git、python3（標準ライブラリだけを使う）、`shasum`（Linux では `sha256sum` でもよい）。
- 時刻証明を Bitcoin で確かめるときと、自分で upgrade するときだけ、OpenTimestamps のクライアント（`ots`）を使う。
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
| `kind` | 種類。下の表の5つだけ（許可リスト）。それ以外の `kind` があれば、鎖の検証（`chain`）で失敗になる |
| `targets` | 対象のファイル。各要素は `path`（ルートからの相対パス）、`role`、`sha256` |
| `recorded_at` | 記録した日時（UTC）。記録した機械の時計による申告で、証明ではない |
| `note` | 注記 |

| `kind` | 中身 | 対象の `role` | 作る仕組み |
|---|---|---|---|
| `periods` | 期間の区切り | doc / code / test / output | `src/sealer/seal_periods.py` |
| `periods-triggers` | 区切りを作り直すきっかけの値（docs/stats/periods.md 8章 (2)） | triggers | `src/sealer/seal_triggers.py` |
| `threshold-access` | 閾値を決める期間の区画（2020-12-15 以降）の情報を初めて「扱う」直前の記録。採用の区切り（形式は 7章） | threshold-access | `src/sealer/seal_access.py` |
| `acquisition-start` | 試運転の手順3の取得を始める前の記録（形式は 7章） | acquisition-start | `src/sealer/seal_acquisition.py` の `start` |
| `acquisition-result` | 試運転の手順3の取得の後の記録。対応する `acquisition-start` の seq を参照する（形式は 7章） | acquisition-result | `src/sealer/seal_acquisition.py` の `result` |

- T-007 の案にあった `acquisition` は、二つ（`acquisition-start` と `acquisition-result`）に分けたので、許可リストに無い。今の記録にも無い。
- 許可リストに限る理由：決めていない名前の `kind` を受け付けると、正式な取得や閾値の期間への接触を別の名前で記録して、規則の区切りから外せてしまうため。

行は正規の形（キーを並べ替え、区切りに空白を入れず、UTF-8）で書く。同じ中身を別の書き方で書いた行は、検証で失敗になる。

規則（コードは `src/sealer/ledger.py`）。

- **追記のみ。**
  - 記録の仕組みは、記録のファイルを追記のモードでだけ開く。
  - 出力の JSON・きっかけの値の JSON・`.ots` は、新しいファイルとしてだけ作る。既にあれば上書きしない。
  - 誤りの訂正は、新しい番号の記録として出す。
- **版の番号は記録に書かない。** その種類の記録の何件目かで決まる（`version_of`）。`periods` の1件目が v1 である。
- **採用の規則（T-007 で鎖の順番で決める形にし、T-008 で区切りを改めた。`adoption`）。**
  - 採用するのは、**最初の `kind=threshold-access` の記録より `seq` が小さい記録のうち、その種類（`periods`、`periods-triggers`）の最後のもの**である。
  - `threshold-access` は、閾値を決める期間の区画（2020-12-15 以降）の情報を初めて「扱う」直前に、鎖へ追記する記録である。「扱う」の定義は docs/stats/periods.md 8章 (2) に従う。ディスクに書く（プロジェクトと Git の外の一時的な置き場を含む）、画面に表示する、集計する、ログに出すことを指す。メモリの上で受け取り、ディスクに書く前に捨てることは含めない。
  - `acquisition-start`・`acquisition-result`（試運転の手順3の取得）は、区切りに使わない。8章 (2) は、手順3でファイル一覧の 2020-12-15 以降の行をメモリの上で捨てるなら、手順3は期限に当たらないとしている。また、きっかけの値の一部（共起の網の期間など）は、手順3の後に手法を作る期間のデータを見て決めてよいとしている。そのため、手順3の後に追記したきっかけの値も、最初の `threshold-access` より前なら採用される。
  - `threshold-access` の記録がまだ無いうちは、「採用は保留」とする。仮の候補として、今ある最後の記録を示す。
  - 区切りの後に `periods`・`periods-triggers` を追記することは、封印の仕組みでは拒まない（関門は設けない。監査の所見による）。期限の後の作り直しは、追記したうえで、検証が「採用しない」と表示するだけである。
  - 時刻（Bitcoin で確定した時刻、drand の回の公開時刻）は、採用の判定に使わない。Pending かどうかも使わない。`recorded_at`（申告）も使わない。`adoption` の引数は、記録の一覧と種類の二つだけである。
  - 理由：鎖は行を消せず、順番も入れ替えられない（3章の `chain`）。そのため、`.ots` を Pending のままにする、upgrade を出さない、drand のどの回を書く、のどれを選んでも、採用は変わらない。T-005 の監査の R-1 と、R-2 のうち採用を選べる部分は、この規則で無くなる。
- **すべての seq に、その seq 自身の時刻証明が要る。**
  - 記録を 1 件追記するたびに、先頭からその行までに `.ots` を付ける（`sealed/ledger.jsonl.seqNNNNNN.ots`）。どれか一つでも欠けていれば、検証は失敗する。
  - `.ots` が示すのは「記録の先頭から seq N 行目までが、Bitcoin で確定した時刻に存在した」ことだけである。採用の判定には使わない。
- **Pending の宛先は4つに限る。**
  - `.ots` の Pending の証明の宛先は、stamp で使った4つの公開カレンダーが返す、次の4つの実体のカレンダーに限る（`ledger.STAMP_CALENDARS`）。それ以外の宛先が1つでもあれば、検証は失敗する。
    | stamp で送る先 | Pending の宛先（`.ots` の中） |
    |---|---|
    | `https://a.pool.opentimestamps.org` | `https://alice.btc.calendar.opentimestamps.org` |
    | `https://b.pool.opentimestamps.org` | `https://bob.btc.calendar.opentimestamps.org` |
    | `https://a.pool.eternitywall.com` | `https://finney.calendar.eternitywall.com` |
    | `https://ots.btc.catallaxy.com` | `https://btc.calendar.catallaxy.com` |
  - 理由：運営側が自前のカレンダーの Pending を入れると、第三者がその証明を upgrade できない。許可した4つなら、第三者は自分で upgrade できる（5章）。
  - 集約先（表の左側）が、返す実体のカレンダー（表の右側）を変えた場合は、新しい宛先が `.ots` に入ると検証が失敗するので、許可リスト（`ledger.STAMP_CALENDARS`）を更新する。更新はコードの変更としてコミットする。前の宛先はリストから消さずに残す（既にある `.ots` が通らなくなるため）。
- **きっかけの値と deadline_status の照合**（`judge_deadline_status`）。
  - `periods` の出力の `rebuild_triggers` を、**採用された** `periods-triggers` の記録と比べる。完全に一致すれば `before_deadline`、そうでなければ `after_deadline` が、記録から決まる値である。
  - docs/stats/periods.md 8章 (2) の「期限前に追記した」とは、「最初の `threshold-access` の記録より前に鎖に入った」ことである。
  - periods.md 8章 (2) は、きっかけの値を追記した時刻と、閾値を決める期間の区画の情報を最初に扱った時刻を比べる照合（時刻による照合）を求めている。この手順では、それを鎖の順番による照合（最初の `threshold-access` の記録より前に鎖に入ったか）に置き換えた。置き換えはリードの決定で、reviews/T-007.md に記録がある。
  - 出力の `deadline_status`（統計係の申告）がこれと違えば、失敗になる。次の二つの誤りを、どちらも検出する。
    - `before_deadline` と申告したが、きっかけの値が採用された記録と一致しない（または採用された記録が無い）場合
    - `after_deadline` と申告したが、採用された記録と一致する場合
  - きっかけの値が無い出力（v1 の形）では、`deadline_status` は null でなければならない。
  - `threshold-access` の記録が無いうちは、この照合を保留し、そのことを出力に出す。
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

## 3. 記録の鎖・対象のハッシュ・区画・採用をまとめて確かめる

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
  - Pending の宛先が、1章の4つのどれかであることを確かめる。
  - 各 seq の証明の状態（Pending か、Bitcoin のどの高さか）を表示する。
- `targets --rev auto`：
  - 各記録について、その記録を最初に含んだコミットを Git の履歴から探す。そのコミットの中の対象のファイルの sha256 が、記録と一致することを確かめる。
  - 対象のファイルが後で書き換えられても、封印した時点の中身で確かめられる。
  - 履歴の中で記録そのものが書き換えられていれば失敗する。
- `access`：`threshold-access` の記録ごとに、7章の照合（`ledger_head`、drand の回、`block_start`）をする。記録が無ければ、そう表示する。
- `acquisition`：`acquisition-start` の記録ごとに 7章の照合（`ledger_head`、drand の回）をし、`acquisition-result` との対応を照合する。記録が無ければ、そう表示する。
- `periods`：
  - すべての版の区画の境目が、1件目と一致することを確かめる。
  - `deadline_status` を記録と照合する。`threshold-access` の記録が無いうちは保留する。
- `adopted`：採用の規則と、種類ごとの採用される版を表示する。
  - 採用が決まっているときは、「採用 = seq N」に条件を付けて出す。条件は二つある。この記録の系列が公開されたものと同じであること。時刻の主張は、照合したヘッダが Bitcoin の本当の鎖にある場合に限ること（この検査では確かめていない）。

**この検査で確かめていないことが二つある。** 出力の最後にも、そう表示する。

- ヘッダが Bitcoin の本当の鎖にあること。5章の `ots verify` か、自分の Bitcoin のノードで確かめる。
- drand の署名（BLS）。7章の方法で確かめる。

現在の記録（seq 1 だけ、`.ots` は Pending、`threshold-access` と取得の記録は無い）では、次のように出る。

- `anchors`：「seq 1: Pending」。Pending の宛先は1章の4つ。
- `access`：「threshold-access の記録：なし」。
- `acquisition`：「acquisition-start・acquisition-result の記録：なし」。
- `adopted`：「採用は保留（threshold-access の記録が無いため）」。`periods` の仮の候補は seq 1。
- 最後：「この検査で確かめていないこと：(1) … ヘッダが、Bitcoin の本当の鎖にあること … (2) drand の署名（BLS）は、オフラインでは検証していない …」。

`all` の代わりに `chain`、`anchors`、`targets`、`access`、`acquisition`、`periods`、`adopted` を一つずつ実行してもよい。

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
- 各行の `kind` が1章の5つのどれかであること。
- 採用：`kind` が `threshold-access` の最初の行を探し、それより上の行のうち、種類ごとに一番下の行が採用である。

```sh
sed -n 1p sealed/ledger.jsonl | tr -d '\n' | shasum -a 256           # 2 行目の prev_hash と比べる
head -n 2 sealed/ledger.jsonl | shasum -a 256                         # seq000002.ots の対象と比べる
grep -n '"kind":"threshold-access"' sealed/ledger.jsonl | head -n 1   # 最初の threshold-access の行（区切り）
grep -o '"kind":"[^"]*"' sealed/ledger.jsonl | sort | uniq -c         # kind の一覧（5つの外があれば失敗）
```

対象のファイルが後で書き換えられている場合は、その記録を含んだ最初のコミットに戻してから確かめる。

```sh
git log --reverse --format='%H %ad' --date=iso-strict -- sealed/ledger.jsonl | head -n 1
git show <そのコミット>:docs/stats/periods.md | shasum -a 256
```

## 5. 時刻証明を確かめる

`.ots` は、記録の先頭 N 行のバイト列を対象にしている。ファイル名は `sealed/ledger.jsonl.seqNNNNNN.ots`。時刻証明は、採用の判定には使わない。示すのは「先頭 N 行が、その時刻に存在した」ことだけである。

```sh
# .ots の対象のハッシュ（File sha256 hash）と、カレンダーの一覧を見る（ネットワークを使わない）
.venv/bin/ots info sealed/ledger.jsonl.seq000001.ots
# 証明を確かめる（Bitcoin のノードか、下の代わりの方法が要る）
.venv/bin/ots verify -d "$(head -n 1 sealed/ledger.jsonl | shasum -a 256 | cut -d' ' -f1)" \
    sealed/ledger.jsonl.seq000001.ots
```

- `ots info` の `File sha256 hash` が、4章の最後のコマンドの値と同じであること。
- `ots verify` は、Bitcoin で確定していれば「Success! Bitcoin block <高さ> attests existence as of <時刻>」と出す。この時刻はブロックのヘッダの時刻である。先頭 N 行が存在した時刻の上限は、ヘッダの時刻＋2時間とする（ヘッダの時刻は実際より前に書かれうるため。幅の根拠は 7章）。
  - ブロックを確かめるために、手元の Bitcoin Core のノード（刈り込んだものでもよい）が要る。
  - ノードが無い場合は、https://opentimestamps.org/ の画面に、`.ots` と `head -n 1 sealed/ledger.jsonl` で作ったファイルを渡して確かめる。
  - または、`ots info` が示すブロックの高さとマークルルートを、複数のブロックエクスプローラーで見比べる。
- 確定前の `.ots` では「Pending confirmation in Bitcoin blockchain」と出る。seq 1 の `.ots` は封印の直後のもので、この状態である。この段階では、カレンダーが受け取ったことしか示せない。

### 確定した時刻を verify.py に渡す（自由な値では通らない）

`verify.py` は、確定の時刻を、利用者が入力した時刻からは取らない。取り方は次のとおり。

- seq の `.ots` の中の Bitcoin の証明（高さ）に対して、その高さのブロックのヘッダ（80 バイト）を照合する。照合に通ったヘッダの時刻を使う。
- ヘッダは、`sealed/bitcoin-header-<高さ>.hex` のファイル（運営側の仕組み `src/sealer/seal_bitcoin.py` が書く。下の「運営側の upgrade」）、`--ots-dir` のディレクトリの中の同じ名前のファイル、または `--btc-header <高さ>=<ヘッダの16進>` で渡す。
- 照合する中身（`src/sealer/otsfile.py`）は次の三つで、どれかが通らなければ失敗になる。
  1. ヘッダのマークルルートが、`.ots` の証明の木で計算した値と一致すること
  2. ヘッダのハッシュが、ヘッダ自身の目標値以下であること（作業量の証明）
  3. その目標値が、下限（2^77 回分のハッシュ）より難しいこと
- `.ots` の中に無い高さのヘッダを渡すと、エラーで止まる。
- ヘッダが本当の鎖の、その高さのブロックかどうかは確かめない。出力されるブロックのハッシュを、自分のノードやエクスプローラーで見比べること。
- 確定時刻を使うのは、7章の drand の照合（`threshold-access`、`acquisition-start`）と、表示だけである。採用は変わらない。

```sh
# 自分の Bitcoin のノードからヘッダを取る例
H=<.ots の中の高さ>
HDR=$(bitcoin-cli getblockheader "$(bitcoin-cli getblockhash $H)" false)
PYTHONDONTWRITEBYTECODE=1 python3 -B src/sealer/verify.py all --rev auto --btc-header "$H=$HDR"
```

### 運営側の upgrade とヘッダの書き込み（T-009）

`ots upgrade` は、そのままでは `.ots` を書き換える。封印済みのファイルは追記のみなので、運営側は次の仕組み（`src/sealer/seal_bitcoin.py`）を使う。どれも新しいファイルだけを書き、既にあれば上書きしない。通信を使うので、実行は通信の許可を得てから行う。

- `upgrade --seq N`
  - 元の `.ots` の写しを、一時的な場所で upgrade する。`ots` が作る `.bak` も一時的な場所に残り、`sealed/` には入らない。
  - upgrade した写しを、このリポジトリのコード（`otsfile`）で読む。Bitcoin の証明が入っていれば、対象のハッシュが記録の先頭 N 行と一致し、Pending の宛先が1章の4つの中にあることを確かめてから、元の `.ots` を残したまま `sealed/ledger.jsonl.seqNNNNNN.bitcoin.ots` を新しく書く。
  - まだ確定していなければ、何も書かずに終了コード 1 で終わる。時間をおいて再実行する。
- `header --height H`
  - 高さ H のブロックのヘッダ（80 バイト）を取り、`sealed/bitcoin-header-<H>.hex` に書く。
  - 取り方は、既定では2つのブロックエクスプローラー（https://blockstream.info/api と https://mempool.space/api）の両方から取り、同じヘッダで、ヘッダのハッシュが返されたブロックのハッシュと一致するときだけ使う。`--source bitcoin-cli` なら手元のノードから取る。
  - 書く前に、`sealed/` の `.ots` の中に高さ H の Bitcoin の証明があること、ヘッダがその証明と照合に通ること（5章の三つ）を確かめる。通らなければ書かない。
  - ヘッダが Bitcoin の本当の鎖にあることは、この仕組みでも証明しない。第三者は、上の `ots verify` や自分のノードで確かめる。
- `confirm --seq N`：`upgrade`（`.bitcoin.ots` が既にあれば飛ばす）と、その中のすべての高さの `header` をまとめて行う。

```sh
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -B src/sealer/seal_bitcoin.py confirm --seq 1
# 一つずつ行う場合
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -B src/sealer/seal_bitcoin.py upgrade --seq 1
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -B src/sealer/seal_bitcoin.py header --height <高さ>
```

`stamp.py upgrade --seq N` も、`seal_bitcoin.py upgrade` と同じ動き（同じ関数）である。

### 第三者が自分で upgrade した .ots を検証に読ませる（--ots-dir）

第三者は、運営側の upgrade を待たずに、自分の写しで upgrade してよい。upgrade した `.ots` は、`--ots-dir <ディレクトリ>` で `verify.py` に読ませる。

1. 自分のディレクトリに `.ots` を写す。名前は変えない（`ledger.jsonl.seqNNNNNN.ots`）。
2. そのディレクトリで `ots upgrade` を実行する（ネットワークを使う）。`ots` は元のファイルを `.bak` に移すが、`verify.py` は `.bak` を読まない。
3. `--ots-dir` を付けて検証する。必要ならヘッダも渡す。

```sh
mkdir -p my-ots
cp sealed/ledger.jsonl.seq*.ots my-ots/
.venv/bin/ots upgrade my-ots/ledger.jsonl.seq*.ots
PYTHONDONTWRITEBYTECODE=1 python3 -B src/sealer/verify.py all --rev auto --ots-dir my-ots \
    [--btc-header <高さ>=<ヘッダの16進>] ...
```

- `--ots-dir` の `.ots` も、`sealed/` の `.ots` と同じ検査を受ける。対象のハッシュが記録の先頭 N 行と一致しなければ、また Pending の宛先が1章の4つの外なら、失敗になる。
- `--ots-dir` の `.ots` は、`sealed/` の必須の `.ots`（その seq 自身の stamp の `.ots`）の代わりにはならない。必須の `.ots` が欠けていれば、`--ots-dir` を付けても失敗する。
- 次のブロックは、upgrade せずに写しを読ませる形で、コマンドの形が通ることを確かめる（テストが実行する）。

<!-- test:offline -->
```sh
mkdir -p my-ots
cp sealed/ledger.jsonl.seq*.ots my-ots/
PYTHONDONTWRITEBYTECODE=1 python3 -B src/sealer/verify.py all --rev auto --ots-dir my-ots
```

### upgrade を出さないことで、何が変わり、何が変わらないか

- **採用は変わらない。** 採用は鎖の順番だけで決まり、時刻も Pending かどうかも使わない（1章）。運営側が、ある seq の upgrade を出す・出さない、Pending のままにする、のどれを選んでも、採用される版は同じである。テスト（`tests/sealer/test_ledger.py` の `TestAuditRepro`）で、seq 2 の upgrade を出す場合と出さない場合、seq 2 を自前のカレンダーの Pending にした場合、drand の回を前後に動かした場合を試し、採用が変わらないことを確かめている。自前のカレンダーの場合は、検証そのものが失敗する。
- **変わりうるのは、時刻の主張を示せるかどうかだけである。** 運営側が upgrade を出さなければ、その seq が存在した時刻の上限は、運営側の出したファイルからは示せない。第三者は、上の手順で自分で upgrade して補える。補えるのは、Pending の宛先を1章の4つに限っているからである。
- 自分で補えるのは、4つのカレンダーのどれかが、その証明の Bitcoin への確定を返す間に限る。4つとも応答しなくなれば、Pending の `.ots` は確定させられない。そのときは、その seq の時刻の主張は示せない（採用は変わらない）。

### 通信するもの

- `ots stamp` が公開カレンダーに送るのは、記録の先頭 N 行の sha256 に 16 バイトのランダムな値（nonce）を付けて、もう一度 sha256 にしたものだけである。記録の中身も、記録の sha256 そのものも送らない。
- seq 1 の封印のとき（2026-10-05T21:41Z ごろ、UTC）に送った先は、1章の表の左側の4つである。`.ots` の中の Pending の宛先は、表の右側の4つである。
- 封印の仕組みが通信する先は、次のものだけである（コードに固定してある。`ots` のカレンダーは `ledger.STAMP_CALENDARS`、それ以外は `src/sealer/netfetch.py` の許可リスト。許可リストの外の URL には送る前に止まる）。待ち時間の上限は 20 秒、再試行は 3 回まで、再試行の間は 5 秒待つ。
  | 目的 | 宛先 | 送るもの |
  |---|---|---|
  | `.ots` を作る（`ots stamp`） | 1章の表の左側の4つ | 上のとおり、nonce を付けたハッシュだけ |
  | upgrade（`ots upgrade`） | `.ots` の中の Pending の宛先（1章の表の右側の4つ） | `.ots` の中の、カレンダーに送った値 |
  | drand の最新の回（quicknet） | `https://api.drand.sh/<鎖のハッシュ>/public/latest`。応答が無いか検査に落ちれば、`https://api2.drand.sh/…`、`https://api3.drand.sh/…`、`https://drand.cloudflare.com/…` の順に試す | GET の要求だけ |
  | ブロックのヘッダ | `https://blockstream.info/api/block-height/<高さ>`、`https://blockstream.info/api/block/<ハッシュ>/header`、`https://mempool.space/api/block-height/<高さ>`、`https://mempool.space/api/block/<ハッシュ>/header` | GET の要求だけ |
  - `<鎖のハッシュ>` は quicknet の `52db9ba70e0cc0f6eaf7803dd07447a1f5477735fd3f661792ba94600c84e971`。

## 6. 採用される版を確かめる

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -B src/sealer/verify.py adopted
```

- 採用は、記録の中の最初の `threshold-access` の記録の位置だけで決まる。`acquisition-start`・`acquisition-result` の位置は使わない。コマンドの引数（`--btc-header`、`--ots-dir`）で採用は変わらない。期限や時刻を引数で渡すこともできない。
- 出力の形。
  - `threshold-access` の記録が無い：「採用は保留（threshold-access の記録が無いため）」。種類ごとに「仮の候補 = seq N」。
  - `threshold-access` の記録がある：種類ごとに「採用 = seq N（…）。条件：…」。その種類の記録が `threshold-access` より前に無ければ、「採用される版は無い」。`threshold-access` より後の記録は「採用しない」と表示する。

## 7. 閾値の期間に触れる記録と取得の記録、何が示せて何が示せないか

### 記録の形式と、書く仕組み（T-009）

記録は三つの種類に分ける。中身の JSON は `sealed/<kind>-<sha256>.json` として新しく書き、記録の `targets` に `role` = `kind` で1件だけ載せる。中身の `kind` は、記録の `kind` と同じでなければならない（別の種類の中身を流用できないようにするため）。

**手順3の取得（ファイル一覧）は、次の順で動く。**

1. drand の最新の回（回の番号・randomness・signature）を取る。
2. `acquisition-start` の中身を書き、記録に1件追記する。その seq 自身の `.ots` を作る。この中身には、取得の前に決まる値だけを入れる。
3. ファイル一覧を取得する。2020-12-15 以降の行は、メモリの上で捨ててからディスクに書く（docs/stats/periods.md 8章 (2)）。
4. `acquisition-result` の中身を書き、記録に1件追記する。その seq 自身の `.ots` を作る。この中身には、取得の後でなければ作れない値（捨てたあとの一覧の sha256 など）を入れ、2 の seq を `start_seq` で参照する。

1・2 は `seal_acquisition.py start`、4 は `seal_acquisition.py result` が行う（下の「書く仕組み」）。

```json
{
  "kind": "acquisition-start",
  "step": 3,
  "drand": {
    "chain_hash": "52db9ba70e0cc0f6eaf7803dd07447a1f5477735fd3f661792ba94600c84e971",
    "round": 12345678,
    "randomness": "<signature の sha256 の16進>",
    "signature": "<16進>"
  },
  "ledger_head": {"seq": 3, "sha256": "<この行を足す前の、記録の先頭 seq 行の sha256>"},
  "fetch": {"code_path": "<取得のコードの、ルートからの相対パス>", "code_sha256": "<取得のコードの sha256>"}
}
```

```json
{
  "kind": "acquisition-result",
  "start_seq": 4,
  "kept_rows_sha256": "<2020-12-15 以降の行を捨てたあとの一覧の sha256>"
}
```

**閾値を決める期間の区画の情報を初めて扱う直前に、次の順で動く。**

1. drand の最新の回を取る。
2. `threshold-access` の中身を書き、記録に1件追記する。その seq 自身の `.ots` を作る。
3. そのあとで、2020-12-15 以降の情報を扱う（ディスクに書く・表示する・集計する・ログに出す）。扱うコードは、最初に関門（下の「関門」）を呼ぶ。

1・2 は `seal_access.py seal` が行う。

```json
{
  "kind": "threshold-access",
  "block_start": "2020-12-15",
  "drand": {"chain_hash": "...", "round": 12345999, "randomness": "...", "signature": "..."},
  "ledger_head": {"seq": 6, "sha256": "<この行を足す前の、記録の先頭 seq 行の sha256>"}
}
```

### 書く仕組み

```sh
# 閾値を決める期間の区画の情報を初めて扱う直前
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -B src/sealer/seal_access.py seal
# 試運転の手順3：取得の前と後（取得のコードは、コミットしてから使う）
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -B src/sealer/seal_acquisition.py start --code <取得のコードのパス>
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -B src/sealer/seal_acquisition.py result --start-seq <start の seq> --kept-rows-sha256 <64 桁の16進>
```

三つとも、同じ手順で動く（`src/sealer/seal_records.py`）。途中で失敗したら、それより後のことはしない。

1. 今の記録の鎖と、すべての seq の `.ots` を検証する。`periods` の記録が無ければ止める。
2. 中身を作る。drand を使う種類では、1 の後で drand の最新の回を取る。回の公開時刻が、記録する機械の時計で5分より古いか、1分より先なら止める（時計は申告で、証明ではない）。`ledger_head` は 1 で読んだ記録から作る。`threshold-access` の `block_start` は、`periods` の1件目の出力の閾値の期間の始まりで、引数では渡せない。
3. 追記する行を作り、「今の記録＋その行」に、検証のコード（下の「検証のコードが照合すること」）と同じ照合をする。`kind` が許可リストにあること、中身の `kind`、`ledger_head`、drand、`block_start`、`step`、`fetch`、`start_seq` と `kept_rows_sha256` の形、start と result の対応（一つの start に result は一つだけ）。通らなければ何も書かない。
4. 中身を `sealed/<kind>-<sha256>.json` として新しく書く。
5. 記録に1件追記する。1 で読んだ時点から記録が変わっていれば、追記しない。
6. その seq 自身の `.ots` を作る。6 が失敗すると、記録はあるが `.ots` が無い状態になり、次の追記と検証が止まる。`stamp.py stamp --seq N` で `.ots` を作ってから進める。

このほかに拒むこと。

- `seal_acquisition.py start`：取得のコードが、HEAD のコミットの中身と同じでなければ止める（コミットしていない、作業ツリーで変えている）。第三者が `fetch.code_sha256` を、`fetch.code_path` のコミットの中のファイルと照らせるようにするため。
- `seal_acquisition.py result`：`start_seq` が `acquisition-start` の記録でない、その start に result が既にある、のどちらかなら止める。

通信の部分（drand、`ots`）は、関数の引数で差し替えられる。テスト（`tests/sealer/test_writers.py`）は差し替えたものを使い、ネットワークを使わない。

### 関門

閾値を決める期間の区画（2020-12-15 以降）のデータに触れるコードは、最初に `ledger.require_threshold_access()` を呼ぶ。

- 鎖に `threshold-access` の記録が無ければ、例外（`ledger.ThresholdAccessRequired`）で止める。`acquisition-start`・`acquisition-result` があっても開かない。
- 記録があっても、鎖か `.ots` の検証に通らない、中身のファイルが記録の sha256 と一致しない、`ledger_head`・drand・`block_start` の照合に通らない、のどれかなら止める。
- 手元で確かめるコマンド（ネットワークを使わない。通れば終了コード 0、止まれば 1）：
  ```sh
  PYTHONDONTWRITEBYTECODE=1 python3 -B src/sealer/seal_access.py gate
  ```
- **限界：関門を飛ばしたかどうかは、記録からは検出できない。** 関門を呼ばずにデータに触れるコードを書くことも、関門の前に触れることもできる。記録に残るのは「`threshold-access` を追記した」ことだけである。関門は、手順を飛ばす誤りを防ぐためのもので、証明ではない。下の「示せないこと」の「記録に無い接触」と同じ限界である。

### 検証のコードが照合すること

**drand を持つ記録（`threshold-access`、`acquisition-start`。`check_drand_record`）**

- **ledger_head が、直前の記録のハッシュと一致すること。** 記録が seq N なら、`ledger_head` は `{"seq": N−1, "sha256": 先頭 N−1 行の sha256}` でなければならない。この値は seq N−1 の `.ots` の対象と同じである。一致しなければ失敗になる。
  ```sh
  head -n <N−1> sealed/ledger.jsonl | shasum -a 256   # 中身の ledger_head.sha256 と比べる
  ```
- **drand の回の公開時刻 T が、その記録自身の `.ots` の確定時刻 Tq に、幅 2 時間を足した時刻より前であること**（T < Tq ＋ 2 時間）。
  - 回の公開時刻は、genesis の時刻 ＋（回の番号 − 1）× 間隔（quicknet：3 秒、default：30 秒）。
  - Tq は、照合したブロックのヘッダに書かれた時刻である。その記録自身の `.ots` が Bitcoin で確定していれば比べる。幅を超えて T が後なら（T ≥ Tq ＋ 2 時間）失敗になる。
  - Pending のうちは、この照合を保留し、そのことを出力に出す。
  - **幅の値は 2 時間（`ledger.DRAND_HEADER_SLACK`）。** 根拠：正しく作った記録がこの照合に落ちるのは、ヘッダの時刻が、実際に掘られた時刻より前に書かれた場合である。ヘッダの時刻をどこまで前に書けるかは、Bitcoin の決まりのうち「直前の 11 ブロックの時刻の中央値より後であること」が決める。この中央値は、おおむね 6 ブロック前（約 1 時間前）に当たる。ブロックの間隔はばらつくので、余裕を見て 2 時間とする。幅が無いと、正しく作った記録でも、ヘッダの時刻が drand の回の公開時刻より前に見えて失敗してしまう。
  - 代償：この照合から言えるのは、「記録は T より後に作られ、Tq ＋ 2 時間 より前に存在した」ことまでである。
- `threshold-access` では、中身の `block_start` が、`periods` の1件目（最初に封印した版）の出力の閾値の期間（threshold）の `block_start` と一致すること。`acquisition-start` では、`step` が 3 であること、`fetch` のキーが `code_path`（相対パス）と `code_sha256`（64 桁の16進）だけであること。
- `randomness` が `signature` の sha256 であること、`chain_hash` が知っている鎖であること。
- **drand の署名（BLS）は、オフラインでは検証していない。** 出力にもそう表示する。署名が正しいかは、drand の公開の API（`https://api.drand.sh/<chain_hash>/public/<round>`）の値と見比べるか、drand の検証の道具で確かめる。

**取得の前と後の対応（`check_acquisition_pairs`）**

- `acquisition-result` が参照する `start_seq` が、`kind=acquisition-start` の記録として実在すること。
- `acquisition-result` の seq が、参照する `acquisition-start` の seq より後であること。
- 一つの `acquisition-start` に、`acquisition-result` が一つだけであること。
- どれかが成り立たなければ失敗になる。`acquisition-result` の無い `acquisition-start` は、取得の途中か失敗として表示する（失敗にはしない）。
- `start_seq` は正の整数、`kept_rows_sha256` は 64 桁の16進でなければならない。

### 何が示せて、何が示せないか

採用された記録を seq a、最初の `threshold-access` の記録を seq q（a < q）とする。その drand の回の公開時刻を T とする。

示せること。

1. **この系列の記録では、seq a は seq q より前に鎖に入った。** 鎖は行を消せず、順番も入れ替えられない。採用はこの順番だけで決まる。
2. **seq q の記録は、T より後に作られた。** drand の値は T より前には誰にも分からないからである（署名が正しいことは、上の方法で別に確かめる）。
3. seq q の `.ots` が Bitcoin で確定し、そのヘッダの時刻を Tq とする。**先頭 q 行（採用された記録と、threshold-access の記録を含む）は、Tq ＋ 2 時間 の時点で存在した。** 2 と合わせて、threshold-access の記録は T と Tq ＋ 2 時間 の間に作られたことになる。この区間の幅は、出力に出る二つの時刻で確かめられる。
4. seq a 自身の `.ots` が確定し、その時刻 Ta ＋ 2 時間 が T より前なら、**採用された記録は、threshold-access の記録より前の時刻に存在した**ことも示せる。これは時刻の主張の上乗せで、採用には影響しない。
5. `acquisition-start` についても、2 と 3 と同じ形で、取得を始めた記録が作られた時刻の区間が示せる。`acquisition-result` は start より後の seq にあるので、start の drand の回の公開時刻より後に追記された。その `.ots` が確定していれば、`kept_rows_sha256` の値が、そのヘッダの時刻＋2時間には決まっていたことも示せる。示せるのはここまでで、一覧の中身や、行を捨てたことは示せない（下の「示せないこと」）。

次のことは、この照合では示せない。

- **別の系列が無かったこと。**
  - 封印を公開していないので、運営側は、別の区切りを封印した別の記録をいくつか作っておき、後から一つを選んで出すことができる。それを外から見分ける方法は無い。
  - 示すには、封印した時点で、記録の先頭のハッシュ（または `.ots`）を公開しておく必要がある。
  - 公開するかどうかは、オーナーの判断を待っている。
- **記録に無い接触が、先にあったこと。**
  - `threshold-access` の記録より前に、記録を残さずに閾値を決める期間の情報を扱っていたとしても、この照合では分からない。取得についても同じである。
  - 示せるのは「記録に結び付いた正式な接触が T より後だった」ことまでである。
- **drand の回が、記録の直前の回であること。** 運営側は、古い回を書くことができる。古い回を書いても採用は変わらない。ただし、3 の区間が広がり、時刻の主張が弱くなる。区間の幅は出力で確かめる。
- 4 の Ta ＋ 2 時間 が T 以後、または seq a が Pending の場合は、採用された記録が threshold-access より前の時刻に存在したことを、時刻では示せない。示せるのは 1 の順番だけである。
- **result の無い start が、取得の失敗か、結果を出さなかったものか。**
  - 検証も書く仕組みも、`acquisition-result` の無い `acquisition-start` を許している（失敗にしない）。
  - そのため運営側は、取得を何度か始めて、都合のよい回にだけ result を書くことができる。result の無い start は記録に残り、検証の出力に「対応する acquisition-result は無い」と表示されるので、何回始めたかは記録の長さから数えられる。しかし、result を出さなかった理由は、記録からは分からない。
- **kept_rows_sha256 だけで、2020-12-15 以降の行を捨てたこと。**
  - `kept_rows_sha256` は、捨てたあとの一覧の sha256 である。一覧そのものは記録に無い。
  - 一覧が手に入っても、その sha256 が一致することから分かるのは「この一覧が、その時点で決まっていた」ことまでである。取得した元の一覧に 2020-12-15 以降の行があったか、それをメモリの上で捨てたか、ディスクや画面に一度も出さなかったかは示せない。

### データの手元の跡

封印した時点で `data/` の下に `.gitkeep` 以外のファイルが無かったことは、seq 1 を含むコミット（4章の `git log` で探したもの）の中身で確かめられる。

```sh
git ls-tree -r --name-only <seq 1 を含むコミット> -- data/
```

`.gitkeep` 以外が出なければ、そのコミットにはデータが無い。`.gitignore` の対象（`data/raw`）と Git の外の置き場は、この方法では確かめられない。

## 8. 検証の手順のテストを、コミットの前に試す

`tests/sealer/test_verify_doc.py` は、既定ではコミットされた版（HEAD）だけを複製して試す。コミットの前に、作業ツリーのコードと手順書を試すときは、次のようにする。テストは複製の中で一時的にコミットしてから試す。元のリポジトリには何も書かない。この結果は、コミットされた版の検証にはならない。

```sh
SEALER_DOC_TEST_WORKTREE=1 PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest discover -s tests/sealer
```

## 9. 引用

この封印の対象（期間の区切り）は、GDELT のデータに適用するためのものである。区切りを決めるときに GDELT のデータは使っていない。

Data: The GDELT Project (https://www.gdeltproject.org/). This project is not affiliated with or endorsed by the GDELT Project.
データ出典：GDELT Project（https://www.gdeltproject.org/）。本プロジェクトは GDELT Project と提携・承認の関係にありません。
