# 期間の区切りと候補の封印を検証する手順（T-005、T-007、T-008、T-009、T-013、T-014、T-017、T-023、T-027、T-031）

この文書は、第三者が次のことを自分で確かめるための手順である。

1. 封印の記録（`sealed/ledger.jsonl`）の鎖が正しいこと
2. 封印した対象のファイルのハッシュが、記録と一致すること
3. 時刻証明（OpenTimestamps）の対象が記録と一致し、Pending の宛先が許可した4つのカレンダーであること
4. 採用される版。採用は鎖の順番で決まり、区切りは最初の `threshold-access` の記録である（T-007、T-008。1章）
5. 閾値を決める期間に触れる記録（`threshold-access`）と、試運転の手順3の取得の記録（`acquisition-start`・`acquisition-result`）の照合。何が示せて、何が示せないか（7章）
6. 閾値と判定期間の候補（`candidates`）の記録の形と、最初の `acquisition-start` より前に封印されたこと（9章。T-013）
7. 試運転の手順4（手法を作る期間のデータそのものの取得）の開始の記録（`method-access`）と、その関門（10章。T-014）
8. GKG の取得の run（試しの run・正式な run）の開始の記録（`gkg-run-start`）と、試しの run の回数（12章。T-031）

封印したことは、現時点では公開していない（オーナーの決定）。公開するかどうかは、試運転のあとでオーナーが判断する。オーナーは、封印のハッシュを公開する前に手順3（ファイル一覧の取得）へ進むと決めた（案B。reviews/T-013.md の末尾）。そのため、別の系列が無いことは示せない（7章の「示せないこと」）。

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
| `kind` | 種類。下の表の8つだけ（許可リスト）。それ以外の `kind` があれば、鎖の検証（`chain`）で失敗になる |
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
| `candidates` | 閾値と判定期間の候補（docs/stats/candidates.md。形式は 9章。T-013） | doc / code / test / import / output | `src/sealer/seal_candidates.py` |
| `method-access` | 試運転の手順4（手法を作る期間の区画のデータそのもの）に初めて触れる直前の記録。前に `candidates` と `acquisition-result` が要る（形式は 10章。T-014） | method-access | `src/sealer/seal_method.py` |
| `gkg-run-start` | GKG の取得の run（試しの run・正式な run）の開始の記録。最初の `method-access` より後（形式は 12章。T-031） | gkg-run-start | `src/sealer/seal_gkg_run.py` の `start` |

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
  - 採用するのは、**最初の `kind=threshold-access` の記録より `seq` が小さい記録のうち、その種類（`periods`、`periods-triggers`、`candidates`）の最後のもの**である。
  - `candidates` には、これに加えて「すべての `candidates` の記録が、最初の `acquisition-start` の記録より前にある」ことを求める。後ろにあれば検証は失敗する（9章）。`acquisition-start` があるなら、その前に `candidates` の記録が1件以上なければならない。無ければ検証は失敗する（T-014）。
  - `threshold-access` は、閾値を決める期間の区画（2020-12-15 以降）の情報を初めて「扱う」直前に、鎖へ追記する記録である。「扱う」の定義は docs/stats/periods.md 8章 (2) に従う。ディスクに書く（プロジェクトと Git の外の一時的な置き場を含む）、画面に表示する、集計する、ログに出すことを指す。メモリの上で受け取り、ディスクに書く前に捨てることは含めない。
  - `method-access`（試運転の手順4の開始。10章）も、区切りに使わない。区切りは `threshold-access` のまま（T-014 のリードの指示）。
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
  - **時刻証明とヘッダが作業ツリーから外されていないこと（T-023。T-017 の再提出1回目の監査 軽1）。** `anchors` などの検査は作業ツリーの `sealed/` を読む。そのため、コミットにある `.bitcoin.ots` とヘッダを作業ツリーからまとめて外すと、確定した seq が「Pending」と表示されたまま検査が通ってしまう。これを止めるため、`--rev auto` では、HEAD の履歴の中で `sealed/` に足されたことのある時刻証明（`ledger.jsonl.seqNNNNNN.ots`・`ledger.jsonl.seqNNNNNN.bitcoin.ots`）とヘッダ（`bitcoin-header-<高さ>.hex`）が、すべて作業ツリーにあり、足したコミットの中身と同じであることを確かめる。`--rev <コミット>` では、そのコミットの `sealed/` にあるものについて同じことを確かめる。一つでも無いか違えば失敗する。`--rev working`（既定）では確かめない。
  - **マージコミットも見る（T-027。T-023 の監査 軽A）。** `git log` は、既定ではマージコミットの差分を出さない。そのため T-023 の版では、マージコミットの中で足した `.bitcoin.ots` とヘッダが照合から漏れた。作業ツリーから外しても `--rev auto` が通り、確定した seq を「Pending」に見せられた（drand の照合も「保留」になる）。今は `git log -m`（マージコミットの差分を、親ごとに出す）で集める。
  - **消したコミットがあれば失敗する（T-027）。** 時刻証明とヘッダは追記のみである。そのため、`--rev auto` と `--rev <コミット>` のどちらでも、HEAD の履歴に `sealed/` の時刻証明かヘッダを消したコミットが一つでもあれば、失敗にする。マージコミットを含み、名前の変更も「消した」に数える（`git log -m --no-renames --diff-filter=D`）。
  - 自分で同じことを確かめるコマンド（どちらも何も出なければよい。二つ目は、足したものが作業ツリーにあるかを見る。中身の一致は見ない）。対象の範囲は、検証のコード（`verify.py` の `REV_ANCHOR_RE`）と同じで、`sealed/` の直下の `ledger.jsonl.seqNNNNNN.ots`・`ledger.jsonl.seqNNNNNN.bitcoin.ots`・`bitcoin-header-<高さ>.hex` だけである（T-027 の差し戻し1回目の軽2 で合わせた）：
    ```sh
    git log -m --no-renames --diff-filter=D --format=%H --name-only HEAD -- sealed/ | grep -E '^sealed/(ledger\.jsonl\.seq[0-9]{6}(\.bitcoin)?\.ots|bitcoin-header-[0-9]+\.hex)$'
    git log -m --no-renames --diff-filter=A --format= --name-only HEAD -- sealed/ | sort -u | grep -E '^sealed/(ledger\.jsonl\.seq[0-9]{6}(\.bitcoin)?\.ots|bitcoin-header-[0-9]+\.hex)$' | while read f; do [ -f "$f" ] || echo "無い: $f"; done
    ```
  - 限界：Git の履歴そのものから外したもの（履歴を書き換えて、コミットに一度も入っていない形にしたもの）は、この照合では見つからない。履歴の書き換えは、公開した記録の先頭のハッシュと見比べることでしか分からない（7章の「別の系列」）。`--rev working`（既定）は、この照合をしない。
- `access`：`threshold-access` の記録ごとに、7章の照合（`ledger_head`、drand の回、`block_start`）をする。あわせて、最初の `threshold-access` より前に `candidates` の記録があること（関門と同じ候補の順序の照合。T-017。T-014 の監査 軽2）を確かめる。記録が無ければ、そう表示する。
- `acquisition`：`acquisition-start` の記録ごとに 7章の照合（`ledger_head`、drand の回）をし、`acquisition-result` との対応を照合する。最初の `acquisition-start` より前に `candidates` の記録があることも確かめる（T-014）。記録が無ければ、そう表示する。
- `method`：`method-access` の記録ごとに 10章の照合（`ledger_head`、drand の回、`step`、区画、前に `candidates` と `acquisition-result` があること）をする。記録が無ければ、そう表示する。
- `gkg-runs`：`gkg-run-start` の記録ごとに 12章の照合（`ledger_head`、drand の回、中身、順序）をし、試しの run の回数と、各 run の `run_id`・`code_sha256`・日を並べる（T-031）。記録が無ければ、そう表示する。
- `periods`：
  - すべての版の区画の境目が、1件目と一致することを確かめる。
  - `deadline_status` を記録と照合する。`threshold-access` の記録が無いうちは保留する。
- `candidates`：`candidates` の記録ごとに、対象の形・出力の形・最初の `acquisition-start` との順番を照合する（9章）。J の最大と `periods` の `embargo_days` の照合もする（9章の「J とエンバーゴ」。T-017）。記録が無ければ、そう表示する。
- `adopted`：採用の規則と、種類ごとの採用される版を表示する。
  - 採用が決まっているときは、「採用 = seq N」に条件を付けて出す。条件は二つある。この記録の系列が公開されたものと同じであること。時刻の主張は、照合したヘッダが Bitcoin の本当の鎖にある場合に限ること（この検査では確かめていない）。

**この検査で確かめていないことが二つある。** 出力の最後にも、そう表示する。

- ヘッダが Bitcoin の本当の鎖にあること。5章の `ots verify` か、自分の Bitcoin のノードで確かめる。
- drand の署名（BLS）。7章の方法で確かめる。

現在の記録（T-017 の時点。seq 1 が `periods`、seq 2 が `candidates`、seq 3 が `acquisition-start`、seq 4 が `acquisition-result`。seq 1〜4 はすべて Bitcoin で確定。`threshold-access` と `method-access` の記録は無い）では、次のように出る。

- `anchors`：
  - 「seq 1: Bitcoin で確定（ヘッダの時刻 2026-10-05T21:56:43+00:00 …）」。`sealed/ledger.jsonl.seq000001.bitcoin.ots` の中の高さ 970086・970136・970137 の証明を、`sealed/bitcoin-header-<高さ>.hex` と照合する。最も早いのは高さ 970086（ブロックのハッシュ `00000000000000000000634c077d16d3ea811af7b74f6bbb393ef28421fd0296`）。
  - 「seq 2: Bitcoin で確定（ヘッダの時刻 2026-10-06T10:38:55+00:00 …）」。`sealed/ledger.jsonl.seq000002.bitcoin.ots` の中の高さ 970161・970162・970187 の証明を照合する。最も早いのは高さ 970161（ブロックのハッシュ `00000000000000000000a5912145cd91ef70f4934355505fc03d5d156264256b`）。
  - 「seq 3: Bitcoin で確定（ヘッダの時刻 2026-10-07T14:56:14+00:00 …）」「seq 4: Bitcoin で確定（同じ時刻）」。`sealed/ledger.jsonl.seq000003.bitcoin.ots` と `seq000004.bitcoin.ots` の中の証明は、どちらも高さ 970352（ブロックのハッシュ `000000000000000000000661478887c03e0bfe0eb0a0f1e42a249c9527afd3f2`）だけである。
- `access`：「threshold-access の記録：なし」。
- `acquisition`：「acquisition-start seq 3 ← acquisition-result seq 4」。seq 3 の drand の回の公開時刻は 2026-10-07T13:45:09+00:00 で、seq 3 自身の確定時刻（ヘッダの時刻 2026-10-07T14:56:14+00:00）に2時間を足した時刻より前である（照合に通る）。
- `method`：「method-access の記録：なし」。
- `gkg-runs`：「gkg-run-start の記録：なし」。
- `candidates`：「candidates の 1 件目（seq 2）」。出力の sha256 は `027bde541f834a1a6644fe610323376cd26d1e1cbce99ef8fa7cafdf3da39ee5`。倍率 2, 3, 4, 6, 8, 12, 16、判定期間 14, 28, 56 日、組み合わせ 21。「J（判定が読む最後の日のずれ）の最大 56。periods の 1 件目の embargo_days 90 以下（区切りの作り直しは要らない）」。
- `adopted`：「採用は保留（threshold-access の記録が無いため）」。`periods` の仮の候補は seq 1、`candidates` の仮の候補は seq 2。
- 最後：「この検査で確かめていないこと：(1) … ヘッダが、Bitcoin の本当の鎖にあること … (2) drand の署名（BLS）は、オフラインでは検証していない …」。

`all` の代わりに `chain`、`anchors`、`targets`、`access`、`acquisition`、`method`、`gkg-runs`、`periods`、`candidates`、`adopted` を一つずつ実行してもよい。

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
- 各行の `kind` が1章の8つのどれかであること。
- 採用：`kind` が `threshold-access` の最初の行を探し、それより上の行のうち、種類ごとに一番下の行が採用である。

```sh
sed -n 1p sealed/ledger.jsonl | tr -d '\n' | shasum -a 256           # 2 行目の prev_hash と比べる
head -n 2 sealed/ledger.jsonl | shasum -a 256                         # seq000002.ots の対象と比べる
grep -n '"kind":"threshold-access"' sealed/ledger.jsonl | head -n 1   # 最初の threshold-access の行（区切り）
grep -o '"kind":"[^"]*"' sealed/ledger.jsonl | sort | uniq -c         # kind の一覧（8つの外があれば失敗）
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
# 証明を確かめる（Bitcoin のノードか、下の代わりの方法が要る）。確定した証明は .bitcoin.ots の方にある
.venv/bin/ots verify -d "$(head -n 1 sealed/ledger.jsonl | shasum -a 256 | cut -d' ' -f1)" \
    sealed/ledger.jsonl.seq000001.bitcoin.ots
```

- `ots info` の `File sha256 hash` が、4章の最後のコマンドの値と同じであること。
- `ots verify` は、Bitcoin で確定していれば「Success! Bitcoin block <高さ> attests existence as of <時刻>」と出す。この時刻はブロックのヘッダの時刻である。先頭 N 行が存在した時刻の上限は、ヘッダの時刻＋2時間とする（ヘッダの時刻は実際より前に書かれうるため。幅の根拠は 7章）。
  - ブロックを確かめるために、手元の Bitcoin Core のノード（刈り込んだものでもよい）が要る。
  - ノードが無い場合は、https://opentimestamps.org/ の画面に、`.ots` と `head -n 1 sealed/ledger.jsonl` で作ったファイルを渡して確かめる。
  - または、`ots info` が示すブロックの高さとマークルルートを、複数のブロックエクスプローラーで見比べる。
- 確定前の `.ots` では「Pending confirmation in Bitcoin blockchain」と出る。この段階では、カレンダーが受け取ったことしか示せない。しかも、それすら手元では確かめられない（下の「オフラインで偽造した Pending」）。
  - seq 1 の stamp の `.ots`（`ledger.jsonl.seq000001.ots`）は封印の直後のもので、この状態のまま残してある（追記のみ）。2026-10-06 に運営側が upgrade し、確定を加えたものを `ledger.jsonl.seq000001.bitcoin.ots` として別に置いた。中には高さ 970086・970136・970137 の証明がある（カレンダーごとに別のブロック）。最も早いのは高さ 970086、ヘッダの時刻 2026-10-05T21:56:43Z である。
  - seq 2 も同じ形で、stamp の `.ots` を残したまま、2026-10-07 に運営側が upgrade した（T-017）。`ledger.jsonl.seq000002.bitcoin.ots` の中には高さ 970161・970162・970187 の証明がある。最も早いのは高さ 970161、ヘッダの時刻 2026-10-06T10:38:55Z である。
  - seq 3・4 も同じ形で upgrade した（T-017）。2026-10-07T14:00Z〜15:31Z（UTC）の upgrade では未確定で、何も書かなかった。15:46Z の upgrade で確定し、`ledger.jsonl.seq000003.bitcoin.ots`・`seq000004.bitcoin.ots` と、高さ 970352 のヘッダ（ヘッダの時刻 2026-10-07T14:56:14Z）を書いた。

### 確定した時刻を verify.py に渡す（自由な値では通らない）

`verify.py` は、確定の時刻を、利用者が入力した時刻からは取らない。取り方は次のとおり。

- seq の `.ots` の中の Bitcoin の証明（高さ）に対して、その高さのブロックのヘッダ（80 バイト）を照合する。照合に通ったヘッダの時刻を使う。
- ヘッダは、`sealed/bitcoin-header-<高さ>.hex` のファイル（運営側の仕組み `src/sealer/seal_bitcoin.py` が書く。下の「運営側の upgrade」）、`--ots-dir` のディレクトリの中の同じ名前のファイル、または `--btc-header <高さ>=<ヘッダの16進>` で渡す。
- 照合する中身（`src/sealer/otsfile.py`）は次の三つで、どれかが通らなければ失敗になる。
  1. ヘッダのマークルルートが、`.ots` の証明の木で計算した値と一致すること
  2. ヘッダのハッシュが、ヘッダ自身の目標値以下であること（作業量の証明）
  3. その目標値が、下限（2^77 回分のハッシュ）より難しいこと
- `.ots` の中に無い高さのヘッダを渡すと、エラーで止まる。
- 逆に、`sealed/` か `--ots-dir` の `.ots` に Bitcoin の証明がある高さは、すべてヘッダが要る。ヘッダが無い高さがあれば、検証は失敗する（T-017 の差し戻し1回目の軽2）。置いたヘッダを外すことで、確定時刻を黙って後にずらしたり、「保留」のまま検証を通したりできないようにするため。自分で upgrade した `.ots` を `--ots-dir` で読ませるときは、新しい高さのヘッダも `--btc-header` などで渡す。
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
# 一つずつ行う場合（upgrade が .bitcoin.ots を書いたら、中のすべての高さについて header を続けて実行する）
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -B src/sealer/seal_bitcoin.py upgrade --seq 1
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -B src/sealer/seal_bitcoin.py header --height <高さ>
```

- **一つずつ行うときは、`upgrade` のあとに `header` を続けて実行する（T-023。T-017 の再提出1回目の監査 軽4）。** `upgrade` が `.bitcoin.ots` を書いた時点から、その中の Bitcoin の証明の高さのヘッダがすべて揃うまで、`verify.py`（`anchors` と `all`）は「ヘッダが無い」で失敗する（5章の「確定した時刻を verify.py に渡す」）。`.bitcoin.ots` の中の高さは `upgrade` の出力か `ots info` で分かる。`confirm` は両方をまとめて行うので、この間が空かない。

`stamp.py upgrade --seq N` も、`seal_bitcoin.py upgrade` と同じ動き（同じ関数）である。

### 第三者が自分で upgrade した .ots を検証に読ませる（--ots-dir）

第三者は、運営側の upgrade を待たずに、自分の写しで upgrade してよい。upgrade した `.ots` は、`--ots-dir <ディレクトリ>` で `verify.py` に読ませる。

1. 自分のディレクトリに `.ots` を写す。名前は変えない（`ledger.jsonl.seqNNNNNN.ots`）。
2. そのディレクトリで `ots upgrade` を実行する（ネットワークを使う）。`ots` は元のファイルを `.bak` に移すが、`verify.py` は `.bak` を読まない。
3. upgrade で Bitcoin の証明が入った `.ots` があれば、その中のすべての高さのヘッダを用意する（`ots info` で高さを見る）。ヘッダは、自分のディレクトリに `bitcoin-header-<高さ>.hex`（80 バイトの16進を1行）として置くか、`--btc-header <高さ>=<ヘッダの16進>` で渡す。`sealed/` に同じ高さのヘッダがあれば、それも読まれる。**用意しない高さが一つでもあれば、検証は失敗する**（T-017 の差し戻し1回目の軽2。上の「確定した時刻を verify.py に渡す」）。まだ確定していない（Pending だけの）`.ots` には、ヘッダは要らない。
4. `--ots-dir` を付けて検証する。

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

### オフラインで偽造した Pending の `.ots` は、見分けられない（T-009 の監査 軽4）

- Pending の証明が持つのは、カレンダーの宛先（URL）と、そこへ送ったはずの値までの計算の道筋だけである。カレンダーの署名や受領の証拠は入っていない。
- そのため、カレンダーに何も送らずに、手元で Pending の `.ots` を作ることができる。宛先を1章の4つのどれかにし、対象を記録の先頭 N 行の sha256 にすれば、`verify.py` の検査（対象のハッシュ、Pending の宛先）にも、関門（`require_threshold_access`・`require_method_access`。すべての seq に `.ots` があること）にも通る。オフラインの検査では、本当に送った `.ots` と見分けられない。
- 見分けられるのは、upgrade を試したときだけである。偽造した `.ots` は、カレンダーがその値を受け取っていないので、いつまでも Bitcoin で確定しない。
- 影響：採用は変わらない（採用は鎖の順番だけで決まる）。失うのは、その seq の時刻の主張である。Pending の `.ots` は、確定するまで時刻について何も示さないものとして扱う。時刻の主張に使うのは、Bitcoin で確定した証明（`.bitcoin.ots` と、照合したヘッダ）だけである。

### upgrade を出さないことで、何が変わり、何が変わらないか

- **採用は変わらない。** 採用は鎖の順番だけで決まり、時刻も Pending かどうかも使わない（1章）。運営側が、ある seq の upgrade を出す・出さない、Pending のままにする、のどれを選んでも、採用される版は同じである。テスト（`tests/sealer/test_ledger.py` の `TestAuditRepro`）で、seq 2 の upgrade を出す場合と出さない場合、seq 2 を自前のカレンダーの Pending にした場合、drand の回を前後に動かした場合を試し、採用が変わらないことを確かめている。自前のカレンダーの場合は、検証そのものが失敗する。
- **変わりうるのは、時刻の主張を示せるかどうかだけである。** 運営側が upgrade を出さなければ、その seq が存在した時刻の上限は、運営側の出したファイルからは示せない。第三者は、上の手順で自分で upgrade して補える。補えるのは、Pending の宛先を1章の4つに限っているからである。
- 自分で補えるのは、4つのカレンダーのどれかが、その証明の Bitcoin への確定を返す間に限る。4つとも応答しなくなれば、Pending の `.ots` は確定させられない。そのときは、その seq の時刻の主張は示せない（採用は変わらない）。

### 通信するもの

- `ots stamp` が公開カレンダーに送るのは、記録の先頭 N 行の sha256 に 16 バイトのランダムな値（nonce）を付けて、もう一度 sha256 にしたものだけである。記録の中身も、記録の sha256 そのものも送らない。
- seq 1 の封印のとき（2026-10-05T21:41Z ごろ、UTC）と seq 2 の封印のとき（2026-10-06T09:59Z ごろ、UTC）に送った先は、1章の表の左側の4つである。`.ots` の中の Pending の宛先は、表の右側の4つである。
- T-017 の upgrade（seq 2・3・4。`seal_bitcoin.py confirm`）で通信した先は、`.ots` の中の Pending の宛先（1章の表の右側の4つ）と、ヘッダを取る2つのブロックエクスプローラー（`blockstream.info`、`mempool.space`）だけである。
- 封印の仕組みが通信する先は、次のものだけである（コードに固定してある。`ots` のカレンダーは `ledger.STAMP_CALENDARS`、それ以外は `src/sealer/netfetch.py` の許可リスト。許可リストの外の URL には送る前に止まる）。待ち時間の上限は 20 秒、再試行は 3 回まで、再試行の間は 5 秒待つ。
- `netfetch.py` は、リダイレクト（3xx）についていかない（T-014。T-009 の監査 軽1）。リダイレクトの応答を受けたら、転送先には何も送らずに止まり、再試行もしない。許可リストの中の別の宛先への転送も同じく拒む。応答の URL が要求した URL と違う場合も止まる。
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

**stamp が失敗しても、記録は鎖に入り、区切りが決まる**（T-009 の監査 軽3）。

- 5 で追記した行は、6 の stamp が失敗しても鎖に残る。記録は追記のみなので、取り消すことも、書き直すこともしない。
- `threshold-access` なら、5 の時点で採用の区切りが決まる。stamp を作り直しても、作れないままでも、区切りの位置は変わらない。区切りの後に足した `periods`・`periods-triggers`・`candidates` は採用されない。
- `acquisition-start` なら、5 の時点で「手順3を始めた」記録になる。`.ots` が無いまま取得に進まない。`stamp.py stamp --seq N` で `.ots` を作り、`verify.py all` が通ってから取得する。`method-access` も同じ。
- `.ots` が無い間は、検証（`verify.py`）も、次の追記も、関門も止まる。運用では、stamp が失敗したら、通信を直して `stamp.py stamp --seq N` を再実行する。別の記録を足して埋め合わせることはしない。
- stamp を遅れて作ると、その `.ots` が示す時刻は、遅れた分だけ後になる。drand の回の公開時刻との区間（7章の「示せること」の 3）が広がり、時刻の主張が弱くなる。採用は変わらない。

このほかに拒むこと。

- `seal_access.py seal`：`candidates` の記録が無い、または候補の順序の照合（下の「関門」の最後の項目）に通らなければ止める（T-014）。drand を取りにいく前に止める。
- `seal_acquisition.py start`：`candidates` の記録が1件も無ければ止める（T-014。T-013 の監査 B-1）。drand を取りにいく前に止める。
- `seal_acquisition.py start`：取得のコードが、HEAD のコミットの中身と同じでなければ止める（コミットしていない、作業ツリーで変えている）。第三者が `fetch.code_sha256` を、`fetch.code_path` のコミットの中のファイルと照らせるようにするため。
- `seal_acquisition.py result`：`start_seq` が `acquisition-start` の記録でない、その start に result が既にある、のどちらかなら止める。

通信の部分（drand、`ots`）は、関数の引数で差し替えられる。テスト（`tests/sealer/test_writers.py`）は差し替えたものを使い、ネットワークを使わない。

### 関門

閾値を決める期間の区画（2020-12-15 以降）のデータに触れるコードは、最初に `ledger.require_threshold_access()` を呼ぶ。

- 鎖に `threshold-access` の記録が無ければ、例外（`ledger.ThresholdAccessRequired`）で止める。`acquisition-start`・`acquisition-result` があっても開かない。
- 記録があっても、鎖か `.ots` の検証に通らない、中身のファイルが記録の sha256 と一致しない、`ledger_head`・drand・`block_start` の照合に通らない、のどれかなら止める。
- **候補の順序の検査（T-014。T-013 の申し送り）。** 次のどれかなら止める。
  - 最初の `threshold-access` より前に `candidates` の記録が無い（採用される候補が無いまま、閾値を決める期間に進まないため）。
  - `candidates` の記録が、最初の `acquisition-start` より後にある。`acquisition-start` より前に `candidates` が無い。
  - `candidates` の記録の形（9章）、または出力のファイルの sha256 と形の照合に通らない。
- **関門が読むのは、このリポジトリのルートに固定である（T-014。T-009 の監査 軽2。T-017 で改めた）。** ルートは `ledger.py` の置き場から決まる（`ledger.PROJECT_ROOT`）。関門の関数は引数を一つも取らず、`gate` のコマンドは `--root` を受け付けない（渡すと終了コード 2）。
  - T-014 まであったテスト用のキーワード引数は外した（T-014 の監査 軽1。一時的なディレクトリの下という制限では偽の root を防げず、テストの結果も TMPDIR で変わったため）。テストは、テストの中だけ `ledger.PROJECT_ROOT` を差し替える形で仮のプロジェクトを読ませ、抜けるときに戻す。`src/` の下に、関門に引数を渡すコードと `PROJECT_ROOT` を書き換えるコードが無いことは、テスト（`tests/sealer/test_t017.py`）で確かめる。
  - 限界：同じ Python のプロセスの中で、モジュールの変数を書き換えることは防げない。これは言語の上の限界で、関門を呼ばずにデータに触れられるのと同じ種類のものである（下の「限界」）。
- **`sealed/` がシンボリックリンクで別の場所を指していたら止める（T-017。T-015 の監査 軽1・軽5 の封印係の側）。** 確かめること（`ledger.check_sealed_inside`）：
  - `realpath(<ルート>/sealed)` が `join(realpath(<ルート>), "sealed")` と同じであること。プロジェクトの外を指すリンクも、プロジェクトの中の別のフォルダを指すリンクも拒む（T-017 の差し戻し1回目の軽1）。
  - `sealed/ledger.jsonl` があれば、その実体が `sealed/` の実体の中の `ledger.jsonl` であること。
  - 書く先のファイルがもうあれば、その実体が `sealed/` の中の同じ名前であること（`ledger.check_sealed_path`）。
  - 書く先のファイルがもうあれば、そのリンク数（`st_nlink`）が 1 であること（T-023。T-017 の再提出1回目の監査 軽3）。下の「ハードリンクの限界」。
- **この検査は、`sealed/` に書くすべての経路が通る（T-017 の差し戻し1回目の中1）。** 共通の入口 `ledger.append_record`・`ledger.write_once`・`stamp.stamp_seq`・`stamp.upgrade_seq` が、書く前に `check_sealed_path` を呼ぶ。書く先は、渡したルートの `sealed/` の中に限る（パスの親のフォルダの名前が `sealed` で、そのフォルダが、渡したルートについての上の検査に通ること）。渡したルートがこのリポジトリのルート（`ledger.PROJECT_ROOT`）であることは、書く仕組みでは確かめない。`seal_access.py`・`seal_method.py`・`seal_acquisition.py` などは `--root` で別のルートを受け付けるためである（T-023。T-017 の再提出1回目の監査 軽2 で、この書き方に直した）。関門は `--root` を受け付けず、`PROJECT_ROOT` に固定である（上）。あわせて、各書く仕組み（`seal_periods`・`seal_triggers`・`seal_candidates`・`seal_records`（`seal_access`・`seal_acquisition`・`seal_method` が使う）・`seal_bitcoin`）も、最初に `check_sealed_inside` を呼ぶ。そのため、ots・drand・ヘッダの取得に通信する前に止まる。関門と `verify.py` も同じ検査をする。
  - テスト（`tests/sealer/test_t017.py` の `TestEveryWriterRefusesLinks`）は、14 の書く経路を、三つの置き方（`sealed/` を外へのリンク、`sealed/` をプロジェクトの中の別のフォルダへのリンク、`ledger.jsonl` を外へのリンク）のそれぞれで試す。どの組でも止まり、プロジェクトの中にも外にも1バイトも書かれず、通信の部分が呼ばれないことを確かめる。
  - 限界：検査のあとで置き換えること（検査と使用のあいだの競合）は防げない。
  - **ハードリンクの限界（T-023。T-017 の再提出1回目の監査 軽3）。** ハードリンクは、同じ実体に二つ以上の名前を付けるもので、`realpath` では見分けられない。`sealed/ledger.jsonl` が外のファイルとハードリンクでつながっていると、`sealed/` への追記が外の名前にも及ぶ。書く仕組みは、書く先のリンク数が 2 以上なら書かずに止まる（上の `st_nlink` の検査）。ただし次のことはできない。
    - もう一方の名前がどこにあるかは分からない（ファイルシステムの全体を探さない）。
    - 検査のあとでハードリンクを作られることは防げない（上の競合と同じ）。
    - `verify.py` と関門は、リンク数を確かめない。読むのは同じ実体のバイト列なので、検証の結論は変わらない（ハードリンクがあっても、証明力は落ちない）。
    - ディレクトリのハードリンク（macOS の古い Time Machine など）は対象にしていない。
- **J とエンバーゴの照合（T-017、T-023）。** 9章の「J とエンバーゴ」の照合に通らなければ止める。
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
  - 代償：この照合から言えるのは、「記録は T より後に作られ、Tq ＋ 2 時間 より前に存在した」ことまでである。ただし、「T より後に作られた」は drand の署名（BLS）を確かめた場合に限る（この検査では署名を確かめていない。下の「drand の署名」）。「Tq ＋ 2 時間 より前に存在した」は、照合したヘッダが Bitcoin の本当の鎖にある場合に限る（5章）。
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
  - **オーナーは、封印のハッシュを（X などで）公開する前に、手順3へ進むと決めた（案B。reviews/T-013.md の末尾のオーナーの発言）。** そのため、手順3の取得の記録（`acquisition-start`・`acquisition-result`）と、それより前の記録（`periods`・`candidates`）について、別の系列が無いことは示せない。運営側が、複数の系列で手順3を進め、取得の結果を見てから一つを選ぶことができる。それを外から見分ける方法は無い。
  - 後で記録の先頭のハッシュを公開しても、示せるのは「公開した時点で、その系列が存在した」ことまでである。公開より前に入った記録について、ほかの系列が無かったことは、さかのぼって示せない。手順4（`method-access`）と `threshold-access` も、公開より後に入るのでなければ、同じ限界を持つ。
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

- **オフラインで偽造した Pending の `.ots`。** 5章のとおり、オフラインの検査では本物と見分けられない。Pending の `.ots` は、時刻について何も示さないものとして扱う。

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

## 9. 閾値と判定期間の候補（candidates）の検証（T-013）

CLAUDE.md の「閾値の決め方」は、閾値と判定期間の候補を「手法を作る期間のデータに触れる前に」決めて封印すると定めている。候補は docs/stats/candidates.md（T-011。2026-10-06 にオーナーが承認）で、値は `src/stats/candidates.py` の出力である。

### 記録の形

`kind` は `candidates`。対象（`targets`）は次の5つだけで、`role` とパスの組は固定である（`ledger.CANDIDATES_SOURCES`）。ほかの対象があっても、どれかが欠けても、パスが違っても、検証は失敗する。

| `role` | パス | 理由 |
|---|---|---|
| `doc` | `docs/stats/candidates.md` | 候補と規則の説明 |
| `code` | `src/stats/candidates.py` | 出力を作るコード |
| `test` | `tests/stats/test_candidates.py` | 文書の表とコードの値の照合 |
| `import` | `src/stats/periods.py` | `candidates.py` が読み込む。出力を作り直すのに要る |
| `output` | `sealed/candidates-output-<sha256>.json` | `PYTHONDONTWRITEBYTECODE=1 python3 -B src/stats/candidates.py` の標準出力そのもの |

- `output` のファイル名の `<sha256>` は、記録の `output` の `sha256` と同じでなければならない。
- 出力の JSON は、次を満たさなければならない（`ledger.check_candidates_output`）。
  - `threshold_multipliers` と `horizon_days` が、正の整数の、狭義に増える空でない一覧。
  - `combinations` が、倍率と判定期間のすべての組（`[倍率, 判定期間]`）とちょうど一致し、重複が無い。`combination_count` がその数。

**出力の形の検査の範囲**（T-013 の監査 軽3）。

- 検証のコードが中身として確かめるのは、上の三つ（倍率の一覧、判定期間の一覧、組み合わせとその数）の形だけである。値が妥当か（倍率が 2 以上か、判定期間が何日以内か）は確かめない。
- 出力のほかの項目（判定の定義、選ぶ規則、注記など）と、docs/stats/candidates.md に書かれた判定の定義・選ぶ規則・`src/stats/candidates.py` の中身は、検証のコードでは読まない。これらが封印した時点から変わっていないことは、記録の sha256（`doc`・`code`・`test`・`import`・`output` の5つ）による固定だけに頼っている。
- そのため、判定の定義や選ぶ規則が妥当か、文書と出力が食い違っていないかは、第三者が封印したコミットの文書とコードを自分で読んで確かめる。`tests/stats/test_candidates.py`（`test`）は文書の表とコードの値を照合するが、これは統計係のテストで、検証のコードの一部ではない。

### 順番の照合

- **すべての `candidates` の記録が、最初の `acquisition-start` の記録より前にあること**（`ledger.check_candidates_order`）。後ろに一つでもあれば、`verify.py candidates` と `all` は失敗する。
- **`acquisition-start` があるなら、その前に `candidates` の記録が1件以上あること**（T-014。T-013 の監査 B-1）。無ければ `verify.py acquisition`・`candidates`・`all` は失敗する。書く仕組み（`seal_acquisition.py start`）も、`candidates` が無ければ追記しない。
  - 採用の区切り（最初の `threshold-access`）より強い条件である。手順3の取得（ファイル一覧）が手法を作る期間のデータに触れる最初の正式な記録なので、それより前を求める（T-013 の指示）。
  - 区切りは「最初の」`acquisition-start` である。その `acquisition-result` の後や、二つ目の `acquisition-start` の前に足した `candidates` も失敗になる。
- 採用は1章の規則（`periods` と同じ）。最初の `threshold-access` より前の、`candidates` の最後の記録を採用する。`threshold-access` が無いうちは保留で、仮の候補を示す。

### J とエンバーゴ（T-017。T-014 の監査 軽4。差し戻し1回目の中2 と、T-023 で改めた）

J は、予言日 t の判定が読むデータの最後の日を t + J とするときのずれである（docs/stats/periods.md）。J は `candidates` の封印で決まっている。出力の `last_read_offset_days`（判定期間 H ごとの J。今の候補では J = H）の最大は 56 で、`periods` の1件目の出力の `embargo_days`（90）以下である。このとき区切りは作り直さなくてよい。

- `verify.py candidates`（と `all`）は、次を確かめる（`ledger.check_horizon_embargo`）。
  - 各 `candidates` の出力の `last_read_offset_days` のキーが `horizon_days` とちょうど一致し、各 J が H 以上の整数であること。J の最大は、すべての `candidates` の記録の J の最大である。
  - **`method-access` の後の `periods-triggers` の J は、null か J の最大と等しい値に限る（T-023 の中1、T-027 で改めた）。** docs/stats/periods.md 8章 (2) の「J は試運転の手順4の前に決めて封印の記録に追記する。J は手法を作る期間のデータを見ずに決まる」による。J は `candidates` の出力で決まり、その値は J の最大である（8章 (2) の案B）。`candidates` は `method-access` より前に要る（10章）。最初の `method-access` より後に、J の最大と違う J を持つ `periods-triggers` が一つでもあれば、採用されるかどうかに関わらず失敗する（`ledger.check_j_triggers_before_method`）。
  - **T-027 で、J の最大と等しい J を `method-access` の後にも許した理由（T-023 の監査 軽B）。** 監査の案は二つあった。(a) `method-access` の後の J は、J の最大と等しい場合に限り許す。(b) 作り直しが要る場合、`seal_triggers.py` が J が null の追記を拒む。(a) を選んだ。理由は次のとおり。
    1. 前提：periods.md 8章 (2) は、J 以外の三つのきっかけ（共起の網の日数など）を、手法を作る期間のデータを見て決めてよいとしている。前提：採用されるのは、その時点より前の最後の `periods-triggers` で、その一件が四つの値をすべて持つ。前提：作り直しが要る場合（J の最大 > 1件目の `embargo_days`）、採用される `periods-triggers` の J が null だと照合 (2) に通らない。結論：作り直しが要る場合に `method-access` の後で三つのきっかけを追記するには、同じ記録に J も要る。
    2. 前提：T-023 の版は、`method-access` の後の J を一律に拒んでいた。結論：作り直しが要る場合、`method-access` の後に三つのきっかけを書く方法が無く、J が null の記録を足すと threshold-access が二度と通らなかった（行き詰まり）。(b) だけでは、行き詰まる記録を書けなくなるだけで、8章 (2) が許す追記の道は閉じたままである。
    3. 前提：(a) で許す J は、`method-access` より前に封印した `candidates` の J の最大と等しい値だけである。前提：採用される `periods` の `embargo_days` は、max(1件目の `embargo_days`, J の最大) と等しくなければならない（下の照合 1）。結論：手法を作る期間のデータを見たあとでも、J とエンバーゴは一つの値に決まっていて動かせない。8章 (1) の「きっかけの無い変更はしない」と、8章 (2) の「J は試運転の手順4の前に決めて封印の記録に追記する」とも食い違わない（決めた値を書き直せるのではなく、同じ値を繰り返して書けるだけである）。
    - あわせて、(b) の形の書く前の検査も入れた。作り直しが要る場合、`seal_triggers.py` は J が null の追記を拒み、J の最大も渡すよう求める（`ledger.check_triggers_append`）。この記録は採用されると必ず照合に通らないので、書く理由が無いためである。書く仕組みを飛ばしてその記録を足しても、J の最大を持つ `periods-triggers` を後から足せば、それが採用されて先へ進める（行き詰まらない）。
    - テスト（`tests/sealer/test_t027.py` の `TestRebuildAfterMethod`）は、監査の再現（作り直しが要る場合に、`method-access` の後で共起の網の日数を足す）が、J の最大を一緒に渡せば threshold-access まで通ることを確かめる。また、`method-access` の後に J やエンバーゴを別の値にすると、書く仕組み・検証・関門が止まることも確かめる。
    - **未解決（T-027 で報告）：作り直した版のあとの periods-triggers で、`verify.py periods` が失敗し続ける形。**
      - 起きること：`deadline_status` の照合（`ledger.judge_deadline_status`）は、すべての `periods` の版の `rebuild_triggers` を、「採用された」`periods-triggers`（最初の `threshold-access` より前の最後の記録）と比べる。そのため、作り直した版（`deadline_status` が `before_deadline`）のあとに、その版の `rebuild_triggers` と違う値の `periods-triggers` を一件でも足し、それが採用されると、前の版が「`before_deadline` と申告しているが一致しない」になる。`verify.py periods` と `all` が失敗し、その行は追記のみの記録から消せない。
      - 範囲：作り直しが要る場合（J の最大 > 1件目の `embargo_days`）に限らない。今の本物の記録（J の最大 56）でも、正直な流れで入りうる。例えば、手法を作る期間のデータを見て網の日数を決めて作り直し、そのあと同じ週の年数も決めて作り直す流れ（再現1）や、作り直しのあとに J を言い直す流れ（再現2）である。
      - どの `periods-triggers` と比べるべきか（その版より前の最後の記録か、採用された記録か）は、docs/stats/periods.md 8章 (2) の「記録に追記した値」の読み方で決まる。封印係では決めず、リードが統計係に判断を求めている。
    - **決まるまでの扱い（T-027 の差し戻し1回目の中1 (ii)、T-031 で足した）。** この形の記録を作らないよう、次の書く仕組みと関門で止める。T-027 の時点では `seal_periods.py` に照合が無く、`seal_periods.py` だけでこの形の記録を作れた（T-027 の監査 中1。S1・S2・S5）。その時点の「書く仕組みと関門で止める」という書き方は、`seal_periods.py` については事実でなかった。
      - `seal_periods.py` も、`threshold-access` の記録がまだ無いとき、2件目以降の版を書く前に照合する（T-031。`ledger.check_periods_version_append`）。`before_deadline` の版なら、`rebuild_triggers` が `periods-triggers` の最後の記録と一致し、既にある `before_deadline` の版とも一致し、J が null か `candidates` の J の最大と等しいこと（`candidates` の記録が無いうちは J は照合しない）。`after_deadline` の版なら、`rebuild_triggers` が `periods-triggers` の最後の記録と一致しないこと。きっかけの値が無い版は `deadline_status` が null であること。通らなければ何も書かない。
      - `method-access` の関門（`require_method_access`）は、`threshold-access` がまだ無ければ、`periods-triggers` の最後の記録を仮の採用として、`verify.py periods` と同じ規則で `deadline_status` を照合する（T-031。`ledger.check_deadline_statuses(provisional=True)`）。`seal_method.py` の書く仕組みには、この照合を入れていない（関門で止まる）。
      - `seal_triggers.py` は、`threshold-access` の記録がまだ無く、`before_deadline` の `periods` の版があるとき、その版の `rebuild_triggers` と違う値の追記を拒む（`ledger.check_triggers_against_rebuilds`）。同じ値の言い直しは拒まない。`threshold-access` の後の追記は採用されないので、今までどおり拒まない。
      - `seal_access.py` と `threshold-access` の関門（`require_threshold_access`）は、`verify.py periods` と同じ規則で `deadline_status` を照合し（`ledger.check_deadline_statuses`）、通らなければ止まる。書く仕組みを飛ばしてこの形の記録を作っても、閾値を決める期間には進めない。
      - 代償（T-031 で正確に書き直した。T-027 の監査 軽1）：作り直した `before_deadline` の版が一つでもできた後は、`before_deadline` の申告のままでは、きっかけの値を変えられない（`periods-triggers` も `periods` の版も、その版と同じ値しか書けない）。作り直しが要る場合（J の最大 > 90）は、`method-access` の前に J だけで作り直すので、そのあと網の日数などを `before_deadline` で足すことはできない。この代償は、(i) が決まるまでのものである。
      - **形の上では、`after_deadline` と申告した版を書けば、値を変えられる。** `after_deadline` の版は、`rebuild_triggers` が採用される `periods-triggers` と違えば照合に通る（S3・S4 の形）。しかし、**after_deadline の申告を、期限の前に使ってはいけない。** docs/stats/periods.md 8章 (2) で、`after_deadline` は期限（最初の `threshold-access`）の後に、オーナーの承認を得て作り直すときの申告で、統計係は期限の後に自分で作り直さない。期限の前にこの申告で値を変えることは、手順に反する。照合は申告と記録が矛盾しないことしか確かめず、期限の前の `after_deadline` を止めない。`verify.py periods` の出力には、各版の申告が並ぶので、期限より前の seq に `after_deadline` の版があれば、第三者はそれを見つけられる。
      - テスト：`tests/sealer/test_t031.py` の `TestSealPeriodsPrecheck`（S1・S2・S5 が `seal_periods.py` で止まり、飛ばして作っても関門と verify で止まる）・`TestFirstStatusGate`、`tests/sealer/test_t027.py` の `TestDeadlineRepro`（再現1・2 が書く仕組みで止まり、飛ばして作っても `seal_access`・関門・verify で止まる）と、`TestRebuildAfterMethod` の `test_gap_is_stopped_by_writers_and_gate`。
    - **T-027 の初回のコミット（58df044）の説明の訂正。** コミットの説明と、初回のこの節は、未解決の形を「作り直しが二度要る正直な流れ」で「今の本物の記録はこの流れに入らない」と書いた。これは事実より狭い。正しくは上の「範囲」のとおりで、作り直した版のあとに違う値の `periods-triggers` を足せば、J の最大に関わらず入る（T-027 の差し戻し1回目の中2）。コミットの説明は書き換えられないので、ここで訂正する。
  - **照合する時点** は、最初の `method-access` と最初の `threshold-access`（あるものすべて）。J は手順4の前、かつ期限（`threshold-access`）より前に決める（docs/stats/periods.md 8章 (2)）。
  - **照合の相手** は、その時点で採用される版である。その時点の記録より前にある `periods` の最後の記録と、`periods-triggers` の最後の記録を使う。時点が `threshold-access` なら、1章の採用の規則で採用される版と同じになる。それより前の古い版は使わない（初回の提出では、期限より前のどれかの `periods-triggers` で通り、`periods` は1件目と比べていた。中2 の (a)・(b)）。
  - **期待するエンバーゴ** E = max(`periods` の1件目の `embargo_days`, J の最大)。docs/stats/periods.md 8章 (1) の表の「EMBARGO_DAYS = max(90, J)」で、1件目の `embargo_days` は 90 である。今の記録では E = max(90, 56) = 90。
  - 時点ごとに、次のどれかなら失敗する。
    1. 採用される `periods` の `rules.embargo_days` が E と等しくない。J の最大より小さい（区切りが J を覆わない）ものも、E より大きい（きっかけの無い延長。docs/stats/periods.md 8章 (1)「きっかけの無い変更はしない」）ものも拒む（T-023）。
    2. J の最大が `periods` の1件目の `embargo_days` を超えている（作り直しが要る）のに、採用される `periods-triggers` が無いか、その `last_read_offset_days` が null か、J の最大より小さい。`periods-triggers` を求めるのは、超えたときに限り、である。
    3. 採用される `periods-triggers` の `last_read_offset_days` が null でなく、J の最大と等しくない。小さすぎる値も、大きすぎる値も拒む（T-023。以前は大きい値を通していた）。
  - 照合する時点の記録がまだ無いうちは、J を持つ `periods-triggers` の位置の照合のほかは失敗にしない。作り直しが要るなら「保留」と表示する。
  - これらは docs/stats/periods.md 8章 (2) の「案B なら、候補の中で最大の J を使う」と、8章 (1) の表から機械的に決まる値との一致を求めるもので、値を選ぶ余地を残さない。
- 関門（`require_threshold_access`・`require_method_access`）と、書く仕組み（`seal_access.py`・`seal_method.py`）も同じ照合をし、通らなければ止まる（何も書かない）。`seal_triggers.py` も、鎖に `method-access` があれば、J の最大と違う J（`--last-read-offset-days`）を渡した追記を拒む。作り直しが要る場合は、J を渡さない追記も拒む（追記のみの記録に、検証に通らない行を残さないため。T-023、T-027）。
- 監査の再現（T-017 の再提出1回目の P2・P2b）は、テスト（`tests/sealer/test_t023.py` の `TestAuditP2`）で、検証・両方の関門・書く仕組みが止まることを確かめている。
  - P2：作り直しの要らない候補（J の最大 28、1件目の `embargo_days` 90）のまま、`method-access` の後に J 200 の `periods-triggers` を足す。
  - P2b：同じ候補で、`method-access` の後に J 120 の `periods-triggers` と、エンバーゴを 120 にした `periods` を足す。
- 今の記録では「J（判定が読む最後の日のずれ）の最大 56。periods の 1 件目の embargo_days 90 以下（区切りの作り直しは要らない）」と出る。照合する時点の記録はまだ無い。`periods-triggers` の記録も無い。
- 今の記録のまま `method-access` を足すなら、採用される `periods` は1件目（`embargo_days` 90 = E）で照合に通る。その後に `periods-triggers` を足すなら、J は渡さないか 56 だけである。J を `periods-triggers` として明示するなら 56 を渡す（`--last-read-offset-days 56`）。それ以外の値は、書く仕組みが拒み、検証も失敗する。ただし、作り直した `periods` の版（`before_deadline`）が一つでもできたあとは、その版の `rebuild_triggers` と同じ値しか追記できない（上の「決まるまでの扱い」）。J を言い直すなら、作り直しより前に、ほかのきっかけと一緒に渡す。

### 書く仕組み

```sh
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -B src/sealer/seal_candidates.py \
    --expect-output-sha256 <出力の sha256>
```

次のどれかに当たれば、何も書かずに止まる。

- 記録の鎖か `.ots` の検証に通らない。`periods` の記録が無い。
- `acquisition-start` の記録がある。`threshold-access` の記録がある。
- `data/` の下に `.gitkeep` 以外のファイルがある（このリポジトリの `data/` だけを調べる手元の検査）。
- 対象の4つのファイル（`output` 以外）が、HEAD のコミットの中身と違う。
- 出力の sha256 が `--expect-output-sha256` と違う。出力の形が上の照合に通らない。

### 確かめるコマンド

<!-- test:offline -->
```sh
PYTHONDONTWRITEBYTECODE=1 python3 -B src/sealer/verify.py candidates
# 記録の行（targets の sha256 を、次のコマンドの値と見比べる）
grep '"kind":"candidates"' sealed/ledger.jsonl
shasum -a 256 docs/stats/candidates.md src/stats/candidates.py tests/stats/test_candidates.py \
    src/stats/periods.py sealed/candidates-output-*.json
# 出力を自分で作り直す。sha256 が記録の output と同じになる
PYTHONDONTWRITEBYTECODE=1 python3 -B src/stats/candidates.py | shasum -a 256
# seq 2 の .ots の対象：記録のファイルの先頭 2 行の sha256
head -n 2 sealed/ledger.jsonl | shasum -a 256
```

標準の道具で順番を確かめるには、`candidates` の行番号と、最初の `acquisition-start` の行番号を比べる（`acquisition-start` が無ければ、二つ目のコマンドは何も出さない）。

```sh
grep -n '"kind":"candidates"' sealed/ledger.jsonl | cut -d: -f1
grep -n '"kind":"acquisition-start"' sealed/ledger.jsonl | head -n 1 | cut -d: -f1
```

対象のファイルが後で書き換えられている場合は、4章と同じく、記録を含んだ最初のコミットで確かめる（`verify.py all --rev auto` はそうしている）。

### 何が示せて、何が示せないか

示せること。

1. この系列の記録では、`candidates` の記録は、最初の `acquisition-start`（と `threshold-access`）より前に鎖に入った。鎖は行を消せず、順番も入れ替えられない。
2. seq 2 の `.ots` が Bitcoin で確定すれば、候補の出力（sha256 `027bde54…`）と、それを作ったコード・文書は、そのヘッダの時刻＋2時間には決まっていた。
3. 出力は、封印した版のコード（`candidates.py` と `periods.py`）から誰でも作り直せる。

示せないこと。

- **記録に無い接触が、先にあったこと。** `candidates` の記録より前に、記録を残さずに手法を作る期間のデータを見ていたとしても、この照合では分からない。記録の順番が示すのは、正式な取得の記録（`acquisition-start`）より前に封印したことまでである。
- **別の系列が無かったこと。** 封印を公開していないので、7章の「示せないこと」と同じ限界がある。
- `data/` の下の検査は手元のもので、Git の外の置き場や、ほかの機械は調べられない。

## 10. 試運転の手順4の開始（method-access）と関門（T-014）

手順4は、手法を作る期間の区画（`periods` の1件目の出力の `method` の区画。2015-03-02 〜 2020-12-14）のデータそのものを取得し、触れる段階である。その直前に `method-access` の記録を鎖に足し、データに触れるコードは最初に関門を呼ぶ。`method-access` は採用の区切りには使わない（区切りは `threshold-access` のまま）。

### 記録の形

```json
{
  "kind": "method-access",
  "step": 4,
  "block_start": "2015-03-02",
  "block_end": "2020-12-14",
  "drand": {"chain_hash": "...", "round": 12345678, "randomness": "...", "signature": "..."},
  "ledger_head": {"seq": 6, "sha256": "<この行を足す前の、記録の先頭 seq 行の sha256>"}
}
```

- キーはこの6つだけ。`block_start`・`block_end` は `periods` の1件目の出力の `method` の区画で、引数では渡せない。
- 中身は `sealed/method-access-<sha256>.json` として新しく書き、記録の `targets` に `role` = `method-access` で1件だけ載せる。

### 前提と照合

- その記録より前に、`candidates` の記録と `acquisition-result` の記録が、それぞれ1件以上あること（`ledger.check_method_access_order`）。手順4は、候補の封印と手順3の取得の記録の後に行う。
- `ledger_head`・drand の回の照合は、7章の `threshold-access`・`acquisition-start` と同じ（`check_drand_record`）。`step` は 4。
- 区画は、`periods` の1件目の `method` の区画と一致すること（`check_method_access_doc`）。
- どれかが成り立たなければ、`verify.py method` と `all` は失敗する。書く仕組みは、追記の前に同じ照合をし、通らなければ何も書かない。

### 書く仕組みと関門

```sh
# 手順4のデータに初めて触れる直前（ots と drand の通信を使う）
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -B src/sealer/seal_method.py seal
# 関門を手元で確かめる（ネットワークを使わない。通れば 0、止まれば 1。--root は受け付けない）
PYTHONDONTWRITEBYTECODE=1 python3 -B src/sealer/seal_method.py gate
```

- 手法を作る期間のデータに触れるコードは、最初に `ledger.require_method_access()` を引数なしで呼ぶ。通れば最初の `method-access` の記録を返し、通らなければ `ledger.MethodAccessRequired`（`LedgerError` の一種）で止まる。
- 関門が確かめること：鎖とすべての seq の `.ots`、最初の `method-access` の中身のファイルの sha256、`step`・`ledger_head`・drand・区画、前に `candidates` と `acquisition-result` があること、`acquisition-start` と `acquisition-result` の対応、候補の順序（7章の「関門」と同じ）。
- 関門が読むのは、このリポジトリのルートに固定である（7章の「関門」）。

### 確かめるコマンド

<!-- test:offline -->
```sh
PYTHONDONTWRITEBYTECODE=1 python3 -B src/sealer/verify.py method
# method-access の行と、その前の candidates・acquisition-result の行番号（標準の道具で順番を確かめる）
grep -n '"kind":"method-access"' sealed/ledger.jsonl | cut -d: -f1 || true
grep -n '"kind":"candidates"\|"kind":"acquisition-result"' sealed/ledger.jsonl | cut -d: -f1 || true
```

`method-access` の行番号が、`candidates` の行番号の一つ以上と、`acquisition-result` の行番号の一つ以上より大きければよい。

### 手順4の記録と関門の限界（T-013 の監査 軽1）

- **関門を飛ばしたかどうかは、記録からは検出できない。** `require_method_access()` を呼ばずに手法を作る期間のデータに触れるコードを書くことも、`method-access` を足す前にデータに触れることもできる。記録に残るのは「`method-access` を追記した」ことだけで、「それより前に触れなかった」ことは示せない。関門は、正直な運用で手順を飛ばす誤りを防ぐためのもので、証明ではない。
- **関門を呼んだコードが、手順4のコードかどうかは確かめない。** `method-access` の中身には、取得のコードのパスや sha256 は入れていない。何を取得したかを時刻証明で示す手段は、今は限られている。マニフェスト（`data/manifest/`）には、OpenTimestamps の時刻証明は付いていない（Git の履歴に入っているだけで、コミットの日時は申告である）。封印の記録の時刻証明に含まれているのは、手順3の `acquisition-result` の中身の `kept_rows_sha256`（取得したファイル一覧の本体の sha256。記録の対象の sha256 を通じて、その seq の `.ots` の対象に入る）だけである。手順4で取得するデータには、まだ何も時刻証明が無い。
- **手順4のデータの中身は、この記録では示せない。** 生データは Git の外に置く決まりで、記録が示すのは手順4を始めた記録の位置と、drand の回の公開時刻より後に作られたこと（drand の署名（BLS）を確かめた場合に限る）までである。手法を作る期間の区画の外（2020-12-15 以降）のデータに触れなかったことも、この記録では示せない。
- **`method-access` が無くても、それより後の記録は失敗にならない。** 検証が求めるのは「`method-access` があるなら、その前に `candidates` と `acquisition-result` がある」ことだけで、`threshold-access` の前に `method-access` があることは求めない。
- **`method-access` は二つ以上足せる。** 関門が使うのは最初の記録で、何件あるかは記録の長さから数えられる。
- **J（判定が読む最後の日のずれ）は、`periods-triggers` の追記を求めない場合がある。** J は `candidates` の封印で決まっている。J の最大は 56 で、`periods` の `embargo_days`（90）以下なので、区切りの作り直しは要らず、`periods-triggers` は求めない。J の最大が `embargo_days` を超えたときに限り、`method-access`（または `threshold-access`）より前に `periods-triggers` の記録を求める（9章の「J とエンバーゴ」。T-017）。
  - `periods-triggers` に J を書くなら、値は J の最大と等しくなければならない（`method-access` の後でも同じ。T-023、T-027）。採用される `periods` の `embargo_days` は、max(1件目の `embargo_days`, J の最大) と等しくなければならない（T-023）。そのため、`method-access` の後に J を変えてエンバーゴを動かすことはできない。
  - J を `periods-triggers` に書かない場合、手順4の前に封印の記録に入っている J は、`candidates` の出力の `last_read_offset_days` である（`candidates` は `method-access` より前に要る。10章の「前提と照合」）。
- **別の系列が無いことは示せない**（7章。案B）。

## 11. 引用

この封印の対象（期間の区切りと、閾値と判定期間の候補）は、GDELT のデータに適用するためのものである。区切りと候補を決めるときに GDELT のデータは使っていない。

Data: The GDELT Project (https://www.gdeltproject.org/). This project is not affiliated with or endorsed by the GDELT Project.
データ出典：GDELT Project（https://www.gdeltproject.org/）。本プロジェクトは GDELT Project と提携・承認の関係にありません。

## 12. GKG の取得の run の開始（gkg-run-start。T-031）

手順4の GKG の取得には、正式な run の前に、最初の数日だけを取る試しの run がある（src/collector/gkg.py 5.1章）。試しの run を何回行ったか、どの run を入力に使ったか（正式な run）を、追記のみで時刻証明の付く記録から第三者が数えられるように、run を始める前（GKG への要求を送る前）に `gkg-run-start` の記録を鎖に足す（reviews/T-030.md）。採用の区切りには使わない（区切りは `threshold-access` のまま）。

### 記録の形

```json
{
  "kind": "gkg-run-start",
  "step": 4,
  "mode": "trial",
  "run_id": "<code_sha256 の先頭 16 桁>",
  "code_path": "src/collector/acquire_gkg.py",
  "code_sha256": "<取得の入口のコードの sha256>",
  "filelist_sha256": "<acquisition-result の kept_rows_sha256>",
  "method_access_seq": 6,
  "trial_days": ["2015-03-02", "2015-03-03", "2015-03-04"],
  "exclusion_rule_seq": 7,
  "exclusion_rule_record_sha256": "<その記録の行の sha256>",
  "drand": {"chain_hash": "...", "round": 12345678, "randomness": "...", "signature": "..."},
  "ledger_head": {"seq": 8, "sha256": "<この行を足す前の、記録の先頭 seq 行の sha256>"}
}
```

- キーはこの13個だけ（`ledger.GKG_RUN_DOC_KEYS`：`code_path`・`code_sha256`・`drand`・`exclusion_rule_record_sha256`・`exclusion_rule_seq`・`filelist_sha256`・`kind`・`ledger_head`・`method_access_seq`・`mode`・`run_id`・`step`・`trial_days`）。公開してよい値だけで、保存先（ディスク・フォルダ）、ユーザー名、VolumeUUID は入れない。パスは、リポジトリの中の取得のコードの相対パスだけである。
- 中身は `sealed/gkg-run-start-<sha256>.json` として新しく書き、記録の `targets` に `role` = `gkg-run-start` で1件だけ載せる。

### 照合（`ledger.check_gkg_run_doc`・`ledger.check_gkg_runs`。書く仕組みと `verify.py gkg-runs`・`all` が同じ照合をする）

- `ledger_head`・drand の回は、7章の `threshold-access` などと同じ（`check_drand_record`）。`step` は 4。
- `mode` は `trial` か `official`。
- `code_path` は相対パスの正規の形、`code_sha256` は 64 桁の16進。`run_id` は `code_sha256` の先頭16桁（収集係の run_id の決め方。gkg.py 5章）。書く仕組みは、取得のコードが HEAD のコミットの中身と同じでなければ書かない（`acquisition-start` と同じ）。
- `filelist_sha256` は、それより前の `acquisition-result` の `kept_rows_sha256` のどれかと同じ（手順3で封印した一覧を使う）。
- `method_access_seq` は、最初の `method-access` の記録の seq。
- `trial_days`：`trial` なら、日付（YYYY-MM-DD）の狭義に増える空でない一覧で、すべて `periods` の1件目の `method` の区画の中。`official` なら null。
- `exclusion_rule_seq` は、それより前の記録の seq。`exclusion_rule_record_sha256` は、その記録の行の正規の形（`ledger.canonical_line`。末尾の改行を含めない）の sha256。
- **順序**：どの `gkg-run-start` も、最初の `method-access` より後にある。`official` の記録は1件だけ（0件は可）。`trial` の記録は、`official` の記録より前にだけある。
- どれかが成り立たなければ、`verify.py gkg-runs` と `all` は失敗し、書く仕組みは何も書かない。

### 書く仕組み（収集係が呼ぶ入口）

```python
import seal_gkg_run   # src/sealer/seal_gkg_run.py
rec, rel, ots_path = seal_gkg_run.start(
    project, mode, code_rel, run_id, filelist_sha256, method_access_seq, trial_days,
    exclusion_rule_seq, exclusion_rule_record_sha256, now, ots_cmd)
```

- 形は `seal_acquisition.start` と同じで、返り値は（記録、中身のパス、その seq 自身の `.ots` のパス）。drand と ots の通信を使う。
- `method-access` の記録が無い、`official` が既にある（`trial` も `official` も書けない）、取得のコードがコミットされていない、のどれかなら、drand を取りにいく前に止まる。

### 確かめるコマンド

<!-- test:offline -->
```sh
PYTHONDONTWRITEBYTECODE=1 python3 -B src/sealer/verify.py gkg-runs
grep -n '"kind":"gkg-run-start"' sealed/ledger.jsonl | cut -d: -f1 || true
```

- 出力の「試しの run N 回、正式な run M 回」は、記録の件数から数える（自己申告ではない）。各 run の行に、seq、`run_id`、`code_sha256`（とコードのパス）、日（試しの run の日。正式な run は区画の全体）、一覧の sha256、`method-access` の seq、除外の規則の記録の seq を並べる。
- `code_sha256` は、その記録を含むコミットの中の取得のコードと照らせる（`git show <コミット>:src/collector/acquire_gkg.py | shasum -a 256`）。

### 示せないこと

- **除外の規則の記録の種類。** `exclusion_rule_seq` が指す記録の `kind` が「除外の規則」の kind であることは、まだ照合しない。除外の規則の kind が決まっていないため（src/collector/themes.py の `EXCLUSION_RULE_KIND`）。決まったら、照合を足す（別のタスク）。
- **記録に無い run。** `gkg-run-start` を書かずに GKG に要求を送ることは、記録からは検出できない（10章の関門の限界と同じ）。数えられるのは、記録に残した run だけである。
- **run を始めたあとの経過。** 記録が示すのは、run の開始が drand の回の公開時刻より後（drand の署名を確かめた場合に限る）で、その seq の `.ots` の確定時刻＋2時間より前（ヘッダが本当の鎖にある場合に限る）だったことまでである。run の結果は、収集係のマニフェスト（src/collector/README.md）で扱う。
