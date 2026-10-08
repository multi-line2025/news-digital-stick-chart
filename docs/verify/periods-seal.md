# 期間の区切りと候補の封印を検証する手順（T-005、T-007、T-008、T-009、T-013、T-014、T-017、T-023、T-027、T-031、T-037、T-041、T-043、T-049、T-056、T-058、T-059、T-060、T-065、T-066、T-068、T-070、T-073、T-074）

この文書は、第三者が次のことを自分で確かめるための手順である。

1. 封印の記録（`sealed/ledger.jsonl`）の鎖が正しいこと
2. 封印した対象のファイルのハッシュが、記録と一致すること
3. 時刻証明（OpenTimestamps）の対象が記録と一致し、Pending の宛先が許可した4つのカレンダーであること
4. 採用される版。採用は鎖の順番で決まり、区切りは最初の `threshold-access` の記録である（T-007、T-008。1章）
5. 閾値を決める期間に触れる記録（`threshold-access`）と、試運転の手順3の取得の記録（`acquisition-start`・`acquisition-result`）の照合。何が示せて、何が示せないか（7章）
6. 閾値と判定期間の候補（`candidates`）の記録の形と、最初の `acquisition-start` より前に封印されたこと（9章。T-013）
7. 試運転の手順4（手法を作る期間のデータそのものの取得）の開始の記録（`method-access`）と、その関門（10章。T-014）
8. GKG の取得の run（試しの run・正式な run）の開始の記録（`gkg-run-start`）と、試しの run の回数（12章。T-031）
9. 統計係の順番1・順番1b の事前の封印（`stats-order1`・`stats-order1b`）と、その位置（13章。T-037）

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
| `kind` | 種類。下の表の11だけ（許可リスト。T-066 で `gkg-run-result` を加えた）。それ以外の `kind` があれば、鎖の検証（`chain`）で失敗になる |
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
| `gkg-run-result` | GKG の取得の run が終わったあと（run-complete のあと）に、そのマニフェストの先頭の行の sha256 を縛る記録。マニフェストの時刻証明（形式は 12章。T-066） | gkg-run-result | `src/sealer/seal_gkg_result.py` の `seal` |
| `stats-order1` | 統計係の順番1（除外の規則と入れる規則）の封印。除外の規則の kind（形式は 13章。T-037） | stats-order1 | `src/sealer/seal_stats.py` の `seal_order1` |
| `stats-order1b` | 統計係の順番1b（数え方の候補と基準の案）の封印（形式は 13章。T-037） | stats-order1b | `src/sealer/seal_stats.py` の `seal_order1b` |

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
  - `gkg-run-start`（GKG の取得の run の開始。12章。T-031）も、区切りに使わない。
  - `stats-order1`・`stats-order1b`（統計係の順番1・1b。13章。T-037）も、区切りに使わない。
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
- `stats-order`：`stats-order1`・`stats-order1b` の記録ごとに 13章の照合（中身の形、`ledger_head`、位置）をし、対象の名前と sha256 を並べる（T-037）。記録が無ければ、そう表示する。
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
- `stats-order`：「stats-order1・stats-order1b の記録：なし」。
- `candidates`：「candidates の 1 件目（seq 2）」。出力の sha256 は `027bde541f834a1a6644fe610323376cd26d1e1cbce99ef8fa7cafdf3da39ee5`。倍率 2, 3, 4, 6, 8, 12, 16、判定期間 14, 28, 56 日、組み合わせ 21。「J（判定が読む最後の日のずれ）の最大 56。periods の 1 件目の embargo_days 90 以下（区切りの作り直しは要らない）」。
- `adopted`：「採用は保留（threshold-access の記録が無いため）」。`periods` の仮の候補は seq 1、`candidates` の仮の候補は seq 2。
- 最後：「この検査で確かめていないこと：(1) … ヘッダが、Bitcoin の本当の鎖にあること … (2) drand の署名（BLS）は、オフラインでは検証していない …」。

`all` の代わりに `chain`、`anchors`、`targets`、`access`、`acquisition`、`stats-order`、`method`、`gkg-runs`、`periods`、`candidates`、`adopted` を一つずつ実行してもよい。

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
- 各行の `kind` が1章の10のどれかであること。
- 採用：`kind` が `threshold-access` の最初の行を探し、それより上の行のうち、種類ごとに一番下の行が採用である。

```sh
sed -n 1p sealed/ledger.jsonl | tr -d '\n' | shasum -a 256           # 2 行目の prev_hash と比べる
head -n 2 sealed/ledger.jsonl | shasum -a 256                         # seq000002.ots の対象と比べる
grep -n '"kind":"threshold-access"' sealed/ledger.jsonl | head -n 1   # 最初の threshold-access の行（区切り）
grep -o '"kind":"[^"]*"' sealed/ledger.jsonl | sort | uniq -c         # kind の一覧（10の外があれば失敗）
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
      - `seal_periods.py` も、`threshold-access` の記録がまだ無いとき、2件目以降の版を書く前に照合する（T-031。`ledger.check_periods_version_append`）。`before_deadline` の版なら、`rebuild_triggers` が `periods-triggers` の最後の記録と一致し、既にある `before_deadline` の版とも一致し、J が null か `candidates` の J の最大と等しいこと。`candidates` の記録がまだ無いうちは、J が null でない版は書かない（T-031 の差し戻し1回目の軽4。あとで J の最大が違うと、値を変えられずに行き詰まるため）。`after_deadline` の版は書かない（T-031 の差し戻し1回目の中4。下の代償）。きっかけの値が無い版は `deadline_status` が null であること。通らなければ何も書かない。
      - `method-access` の関門（`require_method_access`）と書く仕組み（`seal_method.py`。T-031 の差し戻し1回目の軽2）は、`threshold-access` がまだ無ければ、`periods-triggers` の最後の記録を仮の採用として、`verify.py periods` と同じ規則で `deadline_status` を照合する（T-031。`ledger.check_deadline_statuses(provisional=True)`）。関門が止まる状態の記録は、`seal_method.py` も書かない。
      - `seal_triggers.py` は、`threshold-access` の記録がまだ無く、`before_deadline` の `periods` の版があるとき、その版の `rebuild_triggers` と違う値の追記を拒む（`ledger.check_triggers_against_rebuilds`）。同じ値の言い直しは拒まない。`threshold-access` の後の追記は採用されないので、今までどおり拒まない。
      - `seal_access.py` と `threshold-access` の関門（`require_threshold_access`）は、`verify.py periods` と同じ規則で `deadline_status` を照合し（`ledger.check_deadline_statuses`）、通らなければ止まる。書く仕組みを飛ばしてこの形の記録を作っても、閾値を決める期間には進めない。
      - 代償（T-031 で正確に書き直した。T-027 の監査 軽1）：作り直した `before_deadline` の版が一つでもできた後は、期限（最初の `threshold-access`）の前には、きっかけの値を変えられない（`periods-triggers` も `periods` の版も、その版と同じ値しか書けない）。作り直しが要る場合（J の最大 > 90）は、`method-access` の前に J だけで作り直すので、そのあと網の日数などを足すことはできない。この代償は、(i) が決まるまでのものである。
      - **after_deadline の申告を、期限の前に使ってはいけない。** docs/stats/periods.md 8章 (2) で、`after_deadline` は期限の後に、オーナーの承認を得て作り直すときの申告で、統計係は期限の後に自分で作り直さない。T-031 の初回までは、期限の前に `after_deadline` と申告した版を書けば、上の代償を避けて値を変えられた（S3・S4、T-031 の監査 中4）。差し戻し1回目で、`seal_periods.py` は期限の前の `after_deadline` の版を書かないようにした。また、`seal_triggers.py` は、`after_deadline` の版（書く仕組みを飛ばして作ったもの）と同じ値の追記も拒む（`ledger.check_triggers_against_rebuilds`。採用されると、その版が「`after_deadline` と申告しているが一致する」になるため）。書く仕組みを飛ばして期限の前に `after_deadline` の版を作った場合は、`verify.py periods` の出力に各版の申告が並ぶので、期限より前の seq に `after_deadline` の版があることを第三者が見つけられる。
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
- **関門を呼んだコードが、手順4のコードかどうかは確かめない。** `method-access` の中身には、取得のコードのパスや sha256 は入れていない。何を取得したかを時刻証明で示す手段は、今は限られている。マニフェスト（`data/manifest/`）には、T-066 までは OpenTimestamps の時刻証明が付いていなかった（Git の履歴に入っているだけで、コミットの日時は申告である）。T-066 から、run が終わったあとに `gkg-run-result` の記録でマニフェストの先頭の行を縛れる（12章の「マニフェストの時刻証明」）。封印の記録の時刻証明に含まれているのは、手順3の `acquisition-result` の中身の `kept_rows_sha256`（取得したファイル一覧の本体の sha256。記録の対象の sha256 を通じて、その seq の `.ots` の対象に入る）だけである。手順4で取得するデータには、まだ何も時刻証明が無い。
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
- **取得の計画（T-068。T-066 の監査 中-3）**：上の13個に `days`（取得する日の数）と `files_selected`（取得するファイルの数）を足した15個の形もある（`ledger.GKG_RUN_PLAN_KEYS`）。値は、収集係のマニフェストの run-start の行の `days`・`files_selected` と同じで、データを受け取る前（GKG への要求を送る前）に縛る。verify は、計画のある記録について、run-start の行の `days`・`files_selected` が記録と同じであることを照らす。run-complete の `days` と day の行の数、day の行の `files_listed` の合計は、run-start の行と照らすので、計画とも合う。
  - **正式な run は必ず計画を持つ**（T-074。`ledger.GKG_RUN_PLAN_REQUIRED_FOR_OFFICIAL` は True）。official の記録は、下の `plan_sha256` まで含む16個の形でなければならず、それ以外の形（13個・15個）は、書く仕組み（`seal_gkg_run.start`）も verify（`ledger.check_gkg_run_doc`）も止める。収集係の取得のコードは、official の start に計画を渡す（T-071）。この値を True にしたコミットは履歴に残り、それより前に official の記録は無い（本物の記録は seq 1〜8 で、seq 8 は試しの run）。
  - 試しの run は、どちらの形でもよい。既にある seq 8（試しの run）は計画の無い古い形で、追記のみなので書き換えない。試しの run の日は `trial_days` で決まっている。試しの run の `days`（記録の計画と、マニフェストの run-start の行）は、`trial_days` の数とちょうど同じでなければならない（T-070。T-068 の監査 軽-B。決まった3日のうち1日を後から抜けないように）。
- **計画の一覧の sha256（T-070。T-068 の監査 中-B）**：さらに `plan_sha256` を足した16個の形もある（`ledger.GKG_RUN_PLAN_SHA_KEY`）。`days`・`files_selected` は数だけを縛り、どの日のどのファイルかは縛らないので、取得する日とファイルの一覧そのものの sha256 を、データを受け取る前に縛る。
  - 一覧の正規の形（`ledger.gkg_plan_canonical`）：収集係の `select_files` の出力（試しの run は `trial_plan` で3日に絞ったもの）`{日付: [entry, ...]}` を、`[[日付, [[file_time, size, md5], ...]], ...]` の形にし、日付の順、各日は `file_time` の順に並べ、`json.dumps(…, separators=(",", ":"), ensure_ascii=True)` で書いた ASCII のバイト列（末尾の改行なし）。`entry` の `ambiguous` は入れない。`plan_sha256` はこのバイト列の sha256。
  - マニフェストの run-start の行にも同じ `plan_sha256` を書き、verify は記録と照らす（違えば止める）。
  - **計画の本体はどこにも置かない。verify が、封印済みのファイル一覧から作り直して照らす**（T-070 差し戻し2回目。差し戻し1回目の「Git に置く」方式はやめた：本体を記録より後のコミットに入れると clone の深さで結論が分かれ、official の本体は約 12.5MB で、データの保存の決まりとも食い違うため）。
    - `verify.py gkg-runs`（と `all`）に `--filelist <封印済みのファイル一覧の本体>` を渡すと、sha256 が記録の `filelist_sha256`（＝ `acquisition-result` の `kept_rows_sha256`）と同じ本体だけを使い、その run の取得のコードが固定している版の `select_files`（試しの run は `trial_plan` も）で計画を作り直す（`verify.rebuild_plan`）。
    - 版の固定の連なり：記録の `code_sha256` → その sha256 の `acquire_gkg.py`（git の履歴から sha256 で探す）→ その中の `PINNED_SHA256`（実行せずに読む）→ `gkg.py`・`filelist.py`・`privacy_scan.py` など、固定されたすべてのファイル（それぞれ git の履歴から sha256 で探す）。HEAD の版は使わない。取り出したファイルだけを空のフォルダに書き（13章の `_BoundDir` と同じ）、`-I -B -X pycache_prefix=<空のフォルダ>` で流す。
    - 作り直した計画の `ledger.gkg_plan_sha256` が記録の `plan_sha256` と違えば止める。同じなら、日の数とファイルの数が `days`・`files_selected` と同じこと、試しの run は日が `trial_days` と同じこと、マニフェストの day の行の日付がどれも計画の日で、`files_listed` がその日の計画のファイルの数と同じで、`failed_files` がその日の計画のファイルであること、run-complete があれば day の行の日付の集まりが計画の日の集まりと同じことを照らす（`ledger.check_plan_rows`）。マニフェストに行が無いときは、day の行との照合はせず「照らさなかった」と出す。
    - 一覧の本体を渡さないとき（第三者の通常の場合）、渡した本体の sha256 が `filelist_sha256` と違うとき、git の履歴が無いとき、浅い clone のとき（T-073）は、trial も official も「照らさなかった」と出す。浅い clone は、13章の stats-order と同じやり方（`git rev-parse --is-shallow-repository` を、`GIT_` で始まる環境変数を固定して動かす。`verify._not_shallow`）で見分け、「照らさなかった：浅い clone なので、…」と出す。浅い clone では、記録が固定する版が履歴に無いことがあり、正直な記録でも「版が git の履歴に無い」で止まって改ざんのように見えるため（T-070 再提出2回目の監査 中-1）。記録に `plan_sha256` が無いのに run-start の行にだけあれば止める。`plan_sha256` の無い記録（T-070 より前の形の試しの run。本物の seq 8）は、これまでどおり数と `trial_days` だけを照らし、何も出さずに抜けずに「照らさなかった：seq 8 の gkg-run-start（trial）は、計画の sha256（plan_sha256）が無い記録（T-070 より前）なので、どの日のどのファイルかを、データを受け取る前の記録と照らしていない」と出す（`all` の最後の行にも出す。T-074。T-071 の監査）。
  - **第三者が照らす手順と限界**（T-070 差し戻し1回目 中-2、差し戻し2回目）：封印済みのファイル一覧の本体は Git の外にあり、公開していない。第三者は次の手順で作り直して照らす。
    1. GDELT の公開のファイル一覧（`https://data.gdeltproject.org/gdeltv2/masterfilelist.txt`。`data/manifest/gdelt-filelist.jsonl` の `source_url` と同じ）を取る。
    2. 封印した規則で絞り、3 の照合までを1つのコマンドで行う（T-073）。`acquisition-start` の `fetch.code_sha256` が固定する版（その sha256 の `acquire_filelist.py` → その中の `PINNED_SHA256` → `src/collector/filelist.py`・`privacy_scan.py`。どれも git の履歴から sha256 で探し、HEAD の版は使わない）を、12章の計画の作り直しと同じく、取り出したファイルだけの空のフォルダに書いて `-I -B` で流す。取得のときと同じ関数（`_read_kept_lines`：2020-12-14 以前と判定できた行だけを残す、`parse_kept_line`：`file_time`・`file_type`・`size_bytes`・`md5` の4項目、`serialize_rows`：本体の書き方）で、本体と同じ形のバイト列を作る。
    3. その sha256 を、`gkg-run-start` が使う一覧（最初の `method-access` より前のただ1件の `acquisition-result`）の `kept_rows_sha256`（＝ `filelist_sha256`）と照らす。一致すれば 0 で終わり、`--out` のファイルに作った本体を新しく書く（既にあるファイルは上書きしない）。一致しなければ 1 で終わり、何も書かない。git の履歴が無いとき、浅い clone のときも、版を探せないので 1 で終わる。
    4. `verify.py gkg-runs --filelist <作ったファイル>` で、計画を作り直して `plan_sha256` と照らす。

    ```sh
    curl -sS -o masterfilelist.txt https://data.gdeltproject.org/gdeltv2/masterfilelist.txt   # 1（ネットワークを使う）
    PYTHONDONTWRITEBYTECODE=1 python3 -B src/sealer/verify.py filelist-rebuild --masterfilelist masterfilelist.txt --out kept.tsv   # 2・3
    PYTHONDONTWRITEBYTECODE=1 python3 -B src/sealer/verify.py gkg-runs --filelist kept.tsv   # 4
    ```
    `filelist-rebuild` は `all` には入らない（公開の一覧のファイルを渡したときだけ流す）。テストは `tests/sealer/test_t073.py` の `TestFilelistRebuild`（本物の seq 3 が固定する版の連なりで作り直せること、一致しなければ 1、一致すれば `--out` に1回だけ書くこと、浅い clone で 1）。
    - 限界：GDELT が公開の一覧を後から変えた（行を足した・消した・md5 を直した）場合は、3 の sha256 が合わず、照らせない（`filelist-rebuild` は 1 で終わり、`gkg-runs` は「照らさなかった」と出す）。**結論：GDELT が一覧を変えたあとは、封印した一覧が規則どおりだったことの証拠は、運営の手元の一覧の本体だけになる。その本体は公開していない（Git の外にある）ので、第三者は永久に照らせない。** 一覧を変えたことと、運営が規則どおりでない一覧を封印したことは、3 の不一致からは区別できない。手元の写しを持っている第三者（取得と同じ頃に公開の一覧を自分で保存した人）は、その写しで 2〜4 を流せる。また、照らせるのは「計画が、封印済みの一覧から、固定された版の規則で作ったものと同じ」ことまでで、取得がその計画どおりに行われたこと（どのファイルを実際に取ったか）は、下の (a) の限界のとおり、`gkg-run-result` の記録までは縛られない。
  - `GKG_RUN_PLAN_REQUIRED_FOR_OFFICIAL` は True（T-074）。official は `plan_sha256` を含む16個の形でなければならない（書く仕組みも verify も止める）。テストは `tests/sealer/test_t068.py` の `test_official_without_plan_stops_verify`・`test_official_doc_without_plan_rejected`・`test_official_without_plan_refused`、`tests/sealer/test_t070.py` の `TestRequiredFlag`、`tests/sealer/test_t074.py` の `TestFlag`。

### 照合（`ledger.check_gkg_run_doc`・`ledger.check_gkg_runs`。書く仕組みと `verify.py gkg-runs`・`all` が同じ照合をする）

- `ledger_head`・drand の回は、7章の `threshold-access` などと同じ（`check_drand_record`）。`step` は 4。
- `mode` は `trial` か `official`。
- `code_path` は相対パスの正規の形、`code_sha256` は 64 桁の16進。`run_id` は `code_sha256` の先頭16桁（収集係の run_id の決め方。gkg.py 5章）。書く仕組みは、取得のコードが HEAD のコミットの中身と同じでなければ書かない（`acquisition-start` と同じ）。
- `filelist_sha256` は、最初の `method-access` より前の、ただ1件の `acquisition-result` の `kept_rows_sha256` と同じ（`ledger.gkg_filelist_sha256`。2件以上あれば、どの一覧かを決められないので書けない）。手順3で封印した一覧だけを使い、試しの run のあとで手順3をやり直した一覧に替えることはできない（T-031 の差し戻し1回目の中1）。
- `method_access_seq` は、最初の `method-access` の記録の seq。
- `trial_days`：`trial` なら、日付（YYYY-MM-DD）の狭義に増える1〜3日の一覧（`ledger.TRIAL_DAYS_MAX`。収集係の `TRIAL_DAYS` の3日と揃える。T-031 の差し戻し1回目の中3）で、すべて `periods` の1件目の `method` の区画の中。`official` なら null。
- `exclusion_rule_seq` は、除外の規則の kind（`stats-order1`。13章）の最初の記録の seq（T-037。T-031 の監査 中2）。`exclusion_rule_record_sha256` は、その記録の行の正規の形（`ledger.canonical_line`。末尾の改行を含めない）の sha256。その記録は `method-access` より前にあるので、最初の `gkg-run-start` より前でもある（T-031 の差し戻し1回目の中1 の照合も続けて行う）。`stats-order1` の記録が無いうちは、書く仕組みは drand の前に止まる。
- **どの run も同じ入力**：すべての `gkg-run-start` で、`filelist_sha256`・`exclusion_rule_seq`・`exclusion_rule_record_sha256`・`method_access_seq` が同じ（`ledger.check_gkg_run_common`）。試しの run を見たあとで、正式な run の入力を選び直せない。
- **順序**：どの `gkg-run-start` も、最初の `method-access` より後で、最初の `threshold-access` より前にある（閾値を決める期間に触れたあとで、手法を作る期間の GKG の取得を始めない。T-031 の差し戻し1回目の中2。CLAUDE.md の試運転の手順4）。`official` の記録は1件だけ（0件は可）。`trial` の記録は、`official` の記録より前にだけある。`trial` の記録どうしで `run_id` は重ならない（下の「run の単位」）。
- **run の単位（T-031 の差し戻し1回目の中3）**：`gkg-run-start` は、収集係のマニフェストの run-start の行1件につき1件だけ書く。run の最初の実行（run-start の行を書く実行）で、GKG への要求を送る前に1回だけ書き、同じ run の再開では書かない。正式な run の2回目の実行（1回目は run-start を書いて止まる。src/collector/gkg.py 5章）でも書かない。そのため、試しの run の回数は `trial` の記録の件数と同じになる。同じ run_id の `trial` を2件書こうとすると、書く仕組みも verify も止まる。
- どれかが成り立たなければ、`verify.py gkg-runs` と `all` は失敗し、書く仕組みは何も書かない。

### 書く仕組み（収集係が呼ぶ入口）

```python
import seal_gkg_run   # src/sealer/seal_gkg_run.py
rec, rel, ots_path = seal_gkg_run.start(
    project, mode, code_rel, run_id, filelist_sha256, method_access_seq, trial_days,
    exclusion_rule_seq, exclusion_rule_record_sha256, now, ots_cmd)
```

- 形は `seal_acquisition.start` と同じで、返り値は（記録、中身のパス、その seq 自身の `.ots` のパス）。drand と ots の通信を使う。
- `method-access` の記録が無い、`threshold-access` の記録がある、`official` が既にある（`trial` も `official` も書けない）、同じ run_id の `trial` が既にある、`trial_days` が1〜3日でない、のどれかなら、drand を取りにいく前に止まる。取得のコードがコミットされていないときと、run_id がその sha256 の先頭16桁でないときも、drand の前に止まる。そのほかの中身の照合（一覧、除外の規則の記録、ほかの run と同じ入力など）は、drand を取ったあと、書く前に行い、通らなければ何も書かない（T-031 の差し戻し1回目の軽5）。
- **使い回し（T-043。T-041 の監査 中-1）**：同じ mode・run_id の `gkg-run-start` が既にあり、入力（`code_sha256`・`filelist_sha256`・`method_access_seq`・`exclusion_rule_seq`・`exclusion_rule_record_sha256`・`trial_days`）がすべて同じで、マニフェスト（作業ツリーと HEAD の版）にまだその run-start の行が無ければ、`seal_gkg_run.start` は新しく書かずにその記録を返す（drand は呼ばない）。ots の stamp が失敗したあと（記録は ledger に残る）や、記録を書いたあと run-start の行を書く前に止まったあとの、正直なやり直しで、記録が先へ進めなくならないようにするため。
  - stamp が失敗したときは、記録に `.ots` が無いので、鎖の検証（`anchors` と `all`）と、次の書く仕組みが止まる。`PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -B src/sealer/stamp.py stamp --seq N` で `.ots` を作ってから、同じコマンドでやり直す。
  - 入力が一つでも違えば、使い回さずに止まる。run-start の行が既にある記録（run が始まっている）も使い回さない。official の記録があれば、trial の記録は使い回さない。そのため、結果を見てから run や入力を選び直す道にはならない。
  - 収集係の `make_start_hook`（`src/collector/acquire_gkg.py`）は、同じ mode・run_id の記録が既にあれば、`seal_gkg_run.start` を呼ばずにその記録を使う（入力と run-start の行は照らさない）。その場合でも、run-start の行を書いたあとの`verify.py gkg-runs` が、行の指す記録の mode・run_id を照らす。入力の一致は、`seal_gkg_run.start` を呼ぶ形にすれば、封印係の側でも照らせる（収集係への申し送り）。

### 確かめるコマンド

<!-- test:offline -->
```sh
PYTHONDONTWRITEBYTECODE=1 python3 -B src/sealer/verify.py gkg-runs
grep -n '"kind":"gkg-run-start"' sealed/ledger.jsonl | cut -d: -f1 || true
```

- 出力の「試しの run N 回、正式な run M 回」は、記録の件数から数える（自己申告ではない）。各 run の行に、seq、`run_id`、`code_sha256`（とコードのパス）、日（試しの run の日。正式な run は区画の全体）、一覧の sha256、`method-access` の seq、除外の規則の記録の seq を並べる。
- `code_sha256` は、その記録を含むコミットの中の取得のコードと照らせる（`git show <コミット>:src/collector/acquire_gkg.py | shasum -a 256`）。

### 収集係のマニフェストとの照合（T-041。T-031 の監査 中1 の残り）

収集係の GKG の取得（`src/collector/acquire_gkg.py`）は、GKG に要求を送る前に `seal_gkg_run.start` を呼び、マニフェスト（試しの run は `data/manifest/gdelt-gkg-trial.jsonl`、正式な run は `data/manifest/gdelt-gkg-method.jsonl`）の run-start の行に、その記録の seq（`gkg_run_seq`）と行の sha256（`gkg_run_record_sha256`）を書く（src/collector/README.md 6.5.5）。`verify.py gkg-runs`（と `all`）は、作業ツリーのマニフェストと記録を照らす（`ledger.check_gkg_manifests`）。

- 各 run-start の行の `gkg_run_seq` の記録があり、kind が `gkg-run-start`、行の正規の形の sha256 が `gkg_run_record_sha256` と同じ、中身の `mode`（そのマニフェストの mode）と `run_id` が行と同じであること（収集係の `gkg.check_sealed_run` と同じ照らし方）。
- 試しの run の数え方は「**異なる run_id の数**」である。マニフェストの run-start の行の異なる run_id の数が、その mode の `gkg-run-start` の記録の件数と同じであること。同じ run_id の run-start の行が2行以上あるのは、正直なやり直しとして通す（同じ run の記録を指す）。
- 記録を書かずに行った試しの run は、run-start の行が記録を指せないか、数が合わないので見つかる。
- マニフェストが無い mode で、その mode の `gkg-run-start` の記録が1件以上あれば失敗にする（記録だけあって run-start の行が無い。T-043。T-041 の監査 軽-1）。記録が0件でマニフェストも無い mode は照らさず、「照らさなかった」と表示し、`all` の最後の行にも出す（13章の区分表と同じ形。終了コードは 0 のまま）。マニフェストが通常のファイルでない（symlink やディレクトリ）ときは失敗にする。
- 正式な run の run-start の行の `trial_run_ids` は、`official` の記録より前の `trial` の記録の run_id を、記録の seq の順に並べた一覧と同じでなければならない（T-043。T-041 の監査 軽-2）。
  - この並べ方は、収集係が T-045 で決めた並べ方と同じである（src/collector/README.md 6.5.5 の3。第三者の照らし方3 も同じ）。
  - 使い回しのために、マニフェストの run-start の行の順と記録の seq の順がずれることがある。たとえば、記録だけ書いて止まった run A のあとに別の run B を行い、A に戻して記録を使い回すと、行の順は B・A、seq の順は A・B になる。照合は seq の順で比べるので、この流れでも通る（T-046。テスト `tests/sealer/test_t041.py` の `test_trial_run_ids_follow_seq_order_after_reuse`）。
  - `trial_manifest_sha256`（正式な run を始めた時点の試しの run のマニフェストの全体の sha256）は、収集係の関門が、正式な run の開始と再開のたびに照らす。verify は、R（試しの run のマニフェストの、行の並びで最初の run-start の run）の `gkg-run-result` があれば、どの run-start の行の `trial_manifest_sha256` も、その記録が縛る試しの run のマニフェスト（先頭 `manifest_lines` 行）の sha256（`manifest_sha256`）と同じであることを照らす（T-074。T-073 の監査 軽-1。`ledger.check_official_trial_manifest_sha`）。違えば止める。
    - 照らす理由：順番2の decide() は、この値と試しの run のマニフェストの全体を照らし、合わなければ段に進む前に止まる（(b)。14章）。最初のコミットの前にこの値を書き換えれば (b) を固められる（正式な run は二度と再開できなくなるが）。
    - ただ一つの例外：R のあとにも試しの run の行がある（試しのマニフェストが R の縛る先頭より長い）ときは、今の試しのマニフェストの全体の sha256 と同じなら通す。R のあとに試しの run をした正直な流れである。この形では、試しのマニフェストの全体が R の縛るバイト列と違うので、順番2の関門も verify の行き先の照合も止まり、(b) は固められない。
    - R の `gkg-run-result` が無いとき、R が決まらないときは、「照らさなかった：R（run_id …）の gkg-run-result の記録が無いので、data/manifest/gdelt-gkg-method.jsonl の run-start の行の trial_manifest_sha256 を、…照らしていない」と出す（`all` の最後の行にも出す）。正式な run のマニフェストが無い、または run-start の行が無いときは、照らすものが無いので何も出さない（本物の記録の今の状態）。
    - テストは `tests/sealer/test_t074.py` の `TestOfficialTrialSha`。
- **run-start の行の入力の値（T-066。T-063 の採点 中-1）**：run-start の行の `mode`・`run_id`・`code_path`・`code_sha256`・`filelist_sha256`・`method_access_seq`・`exclusion_rule_seq`・`exclusion_rule_record_sha256` が、指している `gkg-run-start` の中身と同じであること。試しの run は `trial` が true で `trial_days` が中身と同じ、正式な run は `trial_days` を持たないこと。区画（`block_start`・`block_end`）が、`method_access_seq` の `method-access` の区画と同じであること。`days`・`files_selected` が 0 以上の整数で、試しの run の `days` は `trial_days` の数と同じ（T-070。`ledger.check_gkg_manifest_rows`）。T-065 までは `gkg_run_seq`・`gkg_run_record_sha256`・`mode`・`run_id` だけを照らしていて、ほかの値を書き換えても検証は 0 のままだった。
- **ほかの行（T-066）**：どの行も、kind が `run-start`・`run-resume`・`run-stop`・`day`・`run-complete` のどれかで、その run_id の最初の行が run-start、共通の欄（`code_path`・`code_sha256`・`filelist_sha256`・`method_access_seq`・`mode`・`official`）がその run-start と同じ。
  - day の行：`day` が日付で、その run の区画の中（試しの run は `trial_days`、正式な run は `method-access` の区画）、同じ run の中で日付が重ならない、`file_name` が `gkg-<mode>-<run_id>-day-<YYYYMMDD>.tsv.gz`、`sha256` が 64 桁、`files_ok` + `files_failed` = `files_listed`、`failed_files` の数 = `files_failed`。
  - run-complete の行：run ごとに多くて1行で、その run の最後の行。`days` が day の行の数と run-start の `days` に等しく、`files_ok`・`files_failed` が day の行の合計に等しく、day の行の `files_listed` の合計が run-start の `files_selected` に等しい。
  - run-complete が無い run は、取得の途中か止まっている run として通し、そう表示する。
- **日の集計の sha256（T-066）**：日の集計は Git の外にある。day の行の `sha256`（と run-complete の取得の記録の `fetch_log_sha256`・`fetch_log_size`）は、`--day-files <置き場所>` を渡したときだけ、その置き場所のファイルと照らす（違えば失敗、置き場所に無いものは「照らさなかった」）。渡さなければ「照らさなかった」と出す。第三者は日の集計を持たない（Git の外に置く決まり）ので、日の集計は、下の `gkg-run-result` で縛ったマニフェストの day の行の sha256 を通じて縛られる。
  ```sh
  PYTHONDONTWRITEBYTECODE=1 python3 -B src/sealer/verify.py gkg-runs --day-files "/Volumes/LACIE SHARE/news-stick-data/gkg-trial"
  ```

### マニフェストの時刻証明（gkg-run-result。T-066）

決定事項「Git にはマニフェストだけを入れ、マニフェストに時刻証明を付ける」のための記録である（T-063 の採点 中-1）。採用の区切りには使わない。

- **書く仕組み**：`src/sealer/seal_gkg_result.py seal --mode <trial|official> --run-id <16桁>`。run-complete の行まで書いたマニフェストをコミットしたあとに、1つの run に1回だけ実行する（ots の通信を使う。drand は使わない）。
  ```sh
  PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -B src/sealer/seal_gkg_result.py seal --mode trial --run-id <run_id>
  ```
- **中身**（11個のキー）：`kind`、`mode`・`run_id`、`gkg_run_seq`・`gkg_run_record_sha256`（その run の `gkg-run-start`）、`manifest_path`、`manifest_lines`（書いた時点のマニフェストの行の数）、`manifest_sha256`（その先頭 `manifest_lines` 行のバイト列の sha256）、`run_complete_line_sha256`（その run の run-complete の行の sha256）、`manifest_commit`（書いた時点の HEAD。マニフェストはこの版と同じ）、`ledger_head`。
- **書く前に確かめること**（どれかが合わなければ何も書かない）：鎖と .ots、その mode・run_id の `gkg-run-start` がちょうど1件、同じ run の `gkg-run-result` がまだ無い、マニフェストが HEAD の版と同じ（コミットしていない行が無い）で改行で終わる、マニフェストが上の照合に通る、その run の run-complete の行がある。
- **verify が照らすこと**（`ledger.check_gkg_result_doc`・`ledger.check_gkg_results`。`gkg-runs` と `all`）：中身の形、`ledger_head`、指す `gkg-run-start`（seq・行の sha256・mode・run_id）、同じ run の記録は1件だけ、作業ツリーのマニフェストの先頭 `manifest_lines` 行の sha256 が `manifest_sha256` と同じ（マニフェストは追記のみなので、後ろに行が増えても先頭は変わらない）、その中に run-complete の行があって sha256 が同じ。git の履歴があれば、`manifest_commit` の版のマニフェストの先頭も同じ。run-complete まである run に `gkg-run-result` が無ければ「照らさなかった：…マニフェストの時刻証明（gkg-run-result の記録が無い）」と出す（終了コードは 0 のまま）。
- **書く時機と、守れること・守れないこと**：この記録は、データを受け取ったあと（run-complete のあと）に書く。そのため次のことが言える（前提 → 結論）。
  - 前提：day の行に日の集計の sha256 が入っていて、記録がマニフェストの先頭の行の sha256 を縛る。結論：記録の .ots の確定時刻より後に、マニフェストも日の集計も差し替えられない（差し替えれば verify が止まる。日の集計は `--day-files` で照らせる）。
  - 前提：マニフェストの行と日の集計を縛るのはこの記録だけで、それより前は、取得の開始（`gkg-run-start` の記録。マニフェストでは run-start の `started_at`、または最初の day の行）から、何も縛っていない。結論：縛られない時間は、取得の開始からこの記録までで、**正式な run では取得の全期間（数日から数週間）にわたる**（T-068 で書き方を直した。T-066 の監査 中-3）。その間に、マニフェストと日の集計を選び直す余地は、この記録では閉じられない。たとえば次のことができる。
    - 別の内容で取り直した日の集計と day の行に入れ替える。
    - **件数をそろえて日を抜く**：都合の悪い日の day の行を書かず、run-complete の数（`days`・`files_ok` など）を day の行の合計にそろえる。計画が無い場合は、抜いた日の数に合わせて run-start の行の `days`・`files_selected` も書き換えれば、行の照合は通る（T-070 で書き方を直した。T-068 の監査 軽-A）。計画（`days`・`files_selected`）のある `gkg-run-start` では、日の数とファイルの数が取得の前に縛られているので、日を抜けば数が合わずに止まる。
    - 計画のある場合に、数をそろえたまま行える選び直しと、計画の一覧の sha256（`plan_sha256`）で閉じるか（T-070。T-068 の監査 中-B）：
      - (a) **都合の悪いファイルを failed_files に回す**（取得できたファイルを、取得に失敗したことにして日の集計から外す）。`files_listed` は変わらず、`files_ok` と `files_failed` の和も変わらないので、数の照合も、計画の一覧の照合も通る。**ファイルごとの成否は、この記録までの間は縛られないので、この選び直しは `plan_sha256` でも閉じない。** 残る限界である。verify は、run ごとに `files_failed` の合計を表示する（多ければ読む人が気づけるように）。失敗の理由と試行の回数は取得の記録（fetch log。sha256 は run-complete の行にある）にあるが、その中身も、この記録までは縛られない。
      - (b) **計画に無い日に差し替える**（区画の中の別の日の day の行にする）。日の数は変わらない。`plan_sha256` があり、封印済みのファイル一覧の本体（`--filelist`）から計画を作り直せれば、day の行の日付が計画の日でないので止まる（一覧の本体が手元にある場合だけ。無ければ「照らさなかった」）。試しの run は、日が `trial_days` で決まっているので、本体が無くても止まる。
      - (c) **日ごとの files_listed を付け替える**（ある日の数を増やし、別の日の数を減らして、合計を `files_selected` にそろえる）。`plan_sha256` があり、計画を作り直せれば、日ごとの数が計画と合わないので止まる（一覧の本体が手元にある場合だけ）。
  - 閉じているのは、`gkg-run-start`（取得の前の記録）が縛る入力の値（コード・一覧・試しの日・計画）と、上の行の照合で見つかる食い違いまでである。
  - 前提：記録の .ots は、run-complete のあと、結果を見る前に作る運用である。結論：run-complete から記録までを短くしても、取得の間の選び直しの余地は残る。長さは、記録の `recorded_at`（申告）と、run-start の `started_at`・run-complete の `completed_at`（申告）の差で読むしかなく、証明ではない。
- **試しの run にも後から付けられる**：既にコミットされている `data/manifest/gdelt-gkg-trial.jsonl`（run_id e15ed53595c70035）にも、同じコマンドで記録を足せる（記録の時点のマニフェスト全体を縛る）。本物の記録への書き込みはオーナーの承認を得てから行う（T-066 では書いていない）。それまで、verify は「照らさなかった」と出す。
  - **事後の縛りでしかない（T-068。T-066 の監査 軽-3）**：試しの run の結果は、オーナーが既に見ている（T-063）。そのため、後から付ける `gkg-run-result` が示すのは「記録の時点より後に変えていない」ことだけで、結果を見る前のマニフェストがこれと同じだったことは示せない。
  - 試しのマニフェストは、正式な run の run-start の行の `trial_manifest_sha256`（試しのマニフェストの全体の sha256）でも縛られる。正式な run を始めた時点（収集係の関門が照らす）より後に変えれば、正式な run の再開が止まる。その値は正式な run のマニフェストの行で、時刻証明は正式な run の `gkg-run-result` を通じてしか付かない。R の `gkg-run-result` があれば、verify はこの値を R の縛るバイト列と照らす（T-074。12章の上の `trial_manifest_sha256` の項）。
- **まとめの「照らさなかった」（T-068。T-066 の監査 中-2）**：verify は、`gkg-run-result` の無い run を、`gkg-run-start` の記録ごとに「照らさなかった：…マニフェストの時刻証明（gkg-run-result の記録が無い。<状態>）」と出す。状態は「run-complete まである」「終わっていない run（run-complete の行が無い）」「マニフェストに行が無い」のどれか。記録ごとに数えるので、マニフェストの run-complete の行を消しても、この数は減らない（T-066 までは、run-complete の行がある run だけを出していた）。
- **関門の位置（提案）**：日の集計を使うコード（正式な run の結果を集計に使う統計係・収集係のコード）は、最初に `ledger.require_gkg_run_result(mode, run_id)` を呼ぶ。鎖と .ots、マニフェストの照合、その run の `gkg-run-result` の照合に通るときだけ記録を返し、そうでなければ `GkgRunResultRequired` で止まる。正式な run は、この関門を通るまで「完了」と扱わない（例：`gkg.official_day_records` が run-complete に加えてこの関門を求める）。どこから呼ぶかは、リードが収集係・統計係に割り振る。統計係の順番2（counting.py）は封印済みで直せないので、封印係の側で、counting.py を動かす前にこの関門を呼ぶ（T-073。14章）。
- **照らす時機（T-043。T-041 の監査 軽-3）**：試しの run のマニフェストは、run が終わってからコミットされる（src/collector/README.md 6.4）。封印の記録（`gkg-run-start`）は run の前に書かれ、ハッシュは24時間以内に投稿されるので、記録だけ先に公開された間は、マニフェストの行が無いか件数が合わず、この照合は失敗することがある。第三者は、マニフェストのコミットのあとで照らす。
- 限界：コミットと、記録のハッシュの公開（X への投稿）の前に、記録の末尾の行と中身のファイルとマニフェストの行をまとめて戻すことは見つけられない。戻したあとの記録とマニフェストは、互いにつじつまが合うからである。7章の「別の系列が無かったこと」と同じ限界で、記録の先頭のハッシュを公開した時点より前の部分だけが固まる。末尾の行と中身とマニフェストの行をまとめて戻すことを見つけるには、投稿したハッシュと照らす（docs/verify/x-post.md）。

### 示せないこと

- **除外の規則の記録の中身。** `exclusion_rule_seq` が `stats-order1` の最初の記録であることは照合する（T-037）。その記録の10件の sha256 が、統計係の表と同じであることは、`stats-order1` を書く仕組みが書く前に確かめる（13章）。gkg-run-start の照合は、その中身を作業ツリーと照らし直さない（3章 (1) の手順で別に照らす。docs/stats/seal-order1.md 3章 (1)）。
- **記録に無い run。** `gkg-run-start` を書かずに GKG に要求を送ることは、記録からは検出できない（10章の関門の限界と同じ）。数えられるのは、記録に残した run だけである。マニフェストに run-start の行を書いた run は、上の「収集係のマニフェストとの照合」で、記録が無ければ見つかる（T-041）。マニフェストにも書かなかった run は見つからない。
- **threshold-access の後の取得の続き（T-037。T-031 の監査 軽4）。** `gkg-run-start` は run の最初の実行で書き、再開では書かない。そのため、`threshold-access` より前に始めた run を、`threshold-access` の後に再開して続けること（正式な run の2回目の実行を含む）は、この記録からは検出できない。照らせるのは、収集係のマニフェスト（run-resume・day の行の時刻と commit）だけである。
- **試しの run の日。** `trial_days` は、収集係の `TRIAL_DAYS`（2015-03-02・03・04 の3日）とちょうど同じでなければならない（`ledger.TRIAL_DAYS`。T-037。T-031 の監査 軽1）。値は `ledger.py` に写してあり、テスト（`tests/sealer/test_t037.py` の `TestTrialDaysMatchCollector`）が `src/collector/gkg.py` と同じことを確かめる。
- **run を始めたあとの経過。** 記録が示すのは、run の開始が drand の回の公開時刻より後（drand の署名を確かめた場合に限る）で、その seq の `.ots` の確定時刻＋2時間より前（ヘッダが本当の鎖にある場合に限る）だったことまでである。run の結果は、収集係のマニフェスト（src/collector/README.md）で扱い、`gkg-run-result` の記録で、そのマニフェストに時刻証明を付ける（上の「マニフェストの時刻証明」。T-066）。

## 13. 統計係の順番1・順番1b の封印（stats-order1・stats-order1b。T-037）

統計係の順番1（除外の規則と入れる規則。封印の対象10件）と順番1b（数え方の候補と基準の案）を、データに触れる前に封印する記録である（docs/stats/seal-order1.md、docs/stats/counting.md 7章）。採用の区切りには使わない。

### 二つの kind にした理由

一つの kind に「順番」の欄を持たせず、`stats-order1` と `stats-order1b` の二つにした。理由（前提 → 結論）：
- 前提：収集係の関門（`themes.require_exclusion_rules_sealed`）と `gkg-run-start` の `exclusion_rule_seq` は、「除外の規則の kind の記録」を指す（src/collector/README.md 6.5.3）。前提：順番1b は順番1 と前後を問わず封印できる（seal-order1.md 3章 (3)）。結論：kind を一つにすると、その kind の最初の記録が順番1b になりうるので、「最初の記録」が除外の規則を指すとは限らなくなる。二つに分ければ、`stats-order1` の記録が常に除外の規則である。
- 前提：前に要る位置と、封印の前に確かめることと、中身の形が違う。結論：kind で分けると、それぞれを kind ごとに一つの規則で書ける。

### stats-order1 は1件だけ（T-037 の差し戻し1回目 中5）

- `stats-order1` の記録は1件に限る。2件目は、書く仕組み（`seal_stats.seal_order1`）が書く前に止め、書く仕組みを飛ばして足しても、`verify.py stats-order` と `all`、関門、ほかの書く仕組みが止まる（`ledger.check_stats_order`）。
- 理由：「どの順番1 か」が、場所によって最初（収集係の README 6.5.3、gkg-run-start の `exclusion_rule_seq`）と最後（seal-order1.md 3章 (1) の照らし方）で食い違わないようにするため。1件なら、最初と最後は同じ記録である。
- 規則を直す必要が出たときの新しい版の扱い（tags-naive.md 2章 (6)、5章 (2)）は、別に決める。それまでは2件目を書けない。

### 記録の形

`stats-order1` の中身（`sealed/stats-order1-<sha256>.json`。キーはこの9個だけ：`ancestors`・`approvals`・`checks`・`head`・`kind`・`ledger_head`・`owner_choice`・`python`・`targets`）：
- `head`：封印した時点の HEAD の40桁。`ancestors`：祖先であることを確かめた commit の40桁（`ledger.ORDER1_ANCESTORS` の4つ。1cb463a・2d23cdf・8f0f4ec・0f98e62）。
- `python`：`{"path": ".venv/bin/python", "version": "Python 3.14.2"}` の形。
- `targets`：対象の名前と sha256（`[{"name", "sha256"}]`）。名前は `ledger.ORDER1_TARGET_NAMES` の10件にちょうど一致しなければならない（T-037 の差し戻し1回目 中3。seal-order1.md 1章の表の「対象」の列と同じ文字列。表の行が足りなくても多くても、書く仕組みは止まる）。
- `approvals`：承認の照らし方（`[{"item", "source", "lines"}]`）。`ledger.ORDER1_APPROVALS` の A・B・B (ii) と同じでなければならない。
- `owner_choice`：2d23cdf の版の reviews/T-020.md の見出しと三行（`{"source", "heading", "lines"}`。`ledger.OWNER_CHOICE`）。
- `checks`：`worktree_clean`・`not_shallow`・`method_access_absent`・`themes_manifest_absent`・`gkg_manifests_absent`（どれも true）、`optional_choice_status`（"decided"）、`acquisition_starts`（照らした acquisition-start の一覧）、`stats_tests`（"OK (N tests)"）、`targets_only_copy`（`{"tests": "OK (N tests)", "files": [写しに置いた5件]}`。下の項目10）。
- `ledger_head`：この行を足す前の記録の先頭 seq 行の sha256。
- **記録の行の `recorded_at` は、封印を始めた時刻である**（T-049。T-048 の監査 軽-2）。`seal_stats.seal_order1`・`seal_order1b` は、始めた時点の時計の時刻を `recorded_at` に入れ、そのあとで関門の確認、10件の計算、`tests/stats`、対象だけの写しのテストを行ってから、ledger に書く。そのため、ledger に書いた時刻は `recorded_at` より後になる。ledger に書いた時刻そのものは記録に残らないので、第三者は確かめられない。目安として、T-048 の監査は seq 5 について、`recorded_at` 23:14:39Z、OpenTimestamps のカレンダーが受け取った時刻 23:15:06〜07Z、コミット 23:15:26Z（どれも 2026-10-07、UTC）を観測した（reviews/T-048.md）。`recorded_at` とカレンダーの受け取りの差（約27秒）は、ledger に書くまでの遅れの上限の目安（書き込みの遅れの上限の目安）で、書き込みの遅れそのものではない（書いたのは、受け取りより前の、stamp を始める直前である）。カレンダーの時刻は .ots の Pending からは読めず、確かめられる値ではない（T-056。T-052 の監査 軽-4）。どちらも記録した機械の時計による申告で、証明ではない（1章）。書いた時刻の上限は、その seq の `.ots` の確定時刻で決まる。

`stats-order1b` の中身（キーはこの11個だけ：`ancestors`・`approvals`・`checks`・`counting`・`files`・`head`・`kind`・`ledger_head`・`order1_ref`・`owner_approval`・`python`）：
- `files`：封印の対象のファイルのパスと sha256（`[{"path", "sha256"}]`）。`ledger.ORDER1B_REQUIRED_FILES`（`docs/stats/counting.md`・`src/stats/counting.py`・`tests/stats/test_counting.py`・`docs/stats/seal-order1.md`）のちょうど4件で、それ以外のファイルは入れられない（T-037 の差し戻し1回目 中2。T-060 で、5つ目以降と重複も「記録と合わない」にした。T-059 の監査 重大-1：5つ目に標準ライブラリを隠す `src/stats/fractions.py` を足すと、`counting.py` を変えずに出力を変えられたため）。`ledger.check_order1b_doc`（verify・関門・ほかの書く仕組みが通る）と `seal_stats.seal_order1b` の両方で確かめる。
- `counting`（キーはこの6個：`candidate_ids`・`criteria_ids`・`official_candidate`・`official_status`・`output_sha256`・`owner_decision`）：`PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -B src/stats/counting.py` を引数なしで実行した出力から、候補の識別子（C1〜C7）、参考の基準の案の識別子（B1〜B5）、正式な数え方（`official_status` が "decided" で、候補の中にあり、`ledger.ORDER1B_OFFICIAL_CANDIDATE` の "C7"（`counting.OFFICIAL_CANDIDATE` と同じ。2026-10-08 オーナー決定）と一致すること。C1 などなら、書く仕組みも照合も止まる。T-037 再提出1回目 中-A）、出力の sha256。`owner_decision` は、正式な数え方の出どころの照らし方（`{"source", "source_line", "decision_line"}`。`ledger.OWNER_DECISION`：`9c85f58f054a679b8e5f40fcd7adbb17536f6366:reviews/T-028.md` で、オーナーの発言の行がちょうど1行、`- 決定：正式に使う数え方は、` で始まる行がちょうど1行で、その行に `V1 か V2 の少なくとも一方` と `同じ数え方の全テーマの合計` の両方を含むこと。counting.md 0章 (1)）。
- `approvals`：B (ii) の照らし方（必ず入れる）と、呼ぶ側が渡すほかの照らし方（任意。無くてよい）。順番1b の承認事項へのオーナーの承認は、呼ぶ側に頼らず、下の `owner_approval` で照らす。
- `owner_approval`：順番1b の承認事項へのオーナーの承認の照らし方（`{"source", "heading", "line"}`。`ledger.OWNER_APPROVAL_1B`。T-037 再提出1回目 中-B）。`git show a970019c61808738b02629b14f68b3171c4ddd57:reviews/T-036.md` の中で、`> 承認します` の行がちょうど1つあり、その行より前で最も近い `## ` の見出しが `## 2026-10-08 オーナーの発言（原文のまま記録。順番1b の承認事項）` と行の全体で一致し、その見出しの行もちょうど1つあること。書く仕組みが照らして結果を写し、`check_order1b_doc`（verify・関門・書く仕組み）が決まった値と一致することを求める。
- **verify の `owner_approval` と `owner_decision` の照合は、記録に写した値と定数を比べるもの**である（T-041。T-037 の監査 軽-b）。書く仕組みは、封印のときに `git show` で reviews/ の行を照らして結果を写す。`check_order1b_doc` は、写した値が `ledger.OWNER_APPROVAL_1B`・`ledger.OWNER_DECISION` の決まった値と同じことだけを確かめ、reviews/ のファイルは読まない。第三者は、`git show a970019c61808738b02629b14f68b3171c4ddd57:reviews/T-036.md` と `git show 9c85f58f054a679b8e5f40fcd7adbb17536f6366:reviews/T-028.md` を自分で見て、照らした行がその中にあることを確かめる。
- `order1_ref`：順番1 の記録があれば、その `{"seq", "record_sha256"}`。無ければ null。
- `checks`：`worktree_clean`・`not_shallow`・`method_access_absent`・`gkg_manifests_absent`（どれも true）。

### 書く仕組みが、書く前に確かめること（`src/sealer/seal_stats.py`）

```python
import seal_stats   # src/sealer/seal_stats.py
rec, rel, ots_path = seal_stats.seal_order1(project, now, ots_cmd)
rec, rel, ots_path = seal_stats.seal_order1b(project, files, approvals, now, ots_cmd)
```

- `seal_stats.seal_order1` は、seal-order1.md 2章の項目1〜10 を確かめる。`stats-order1` がまだ無い、作業ツリーがきれい（追跡していないファイルも無い）、浅い clone でない、祖先、承認の行、出どころの見出しと三行、10件の sha256 を自分で計算し直して表（HEAD の版の seal-order1.md）と照らす、"undecided" を拒む、区分表と GKG のマニフェストが作業ツリーにも履歴にも無い、`method-access` が無い、すべての `acquisition-start` のコードが `src/collector/acquire_filelist.py`、`tests/stats` が通る。一つでも通らなければ何も書かない。
- **項目10（対象だけを置いた写し。T-037 の差し戻し1回目 中4）**：tempfile の一時フォルダ（終わると自動で消える）に、HEAD の版の5件（`ledger.order1_copy_files()`）と、1cb463a・2d23cdf の履歴（深さ1の fetch。取る元はプロジェクトのフォルダで、ネットワークは使わない）だけを置き、見張りの環境変数を付けずに `tests/stats/test_exclusion.py`・`tests/stats/test_tagrules.py` を流す。通ること、流したあとに写しの中のファイルが置いた5件だけであることを確かめ、結果を `checks.targets_only_copy` に入れる。統計係のテスト `test_sealed_tests_pass_in_targets_only_copy` と同じ形である。
- 子のプロセスには、`PYTHON` で始まる環境変数（`PYTHONPATH`・`PYTHONPYCACHEPREFIX`・`PYTHONHOME` など）と `STATS_AUDIT_LOG` を渡さず、`PYTHONDONTWRITEBYTECODE=1` だけを足す（軽2）。書く直前に、HEAD と作業ツリーがはじめと同じことをもう一度確かめる（軽3）。`project` は絶対パスにしてから使う（軽4）。
- `seal_stats.seal_order1b` は、3章 (3) の項目1・2・3・4・5・6 を確かめる。`method-access` と GKG の跡が無い、`files` が `ORDER1B_REQUIRED_FILES` のちょうど4件（外のファイルや同じパスの重複は拒む。T-060）で、それぞれ HEAD に含まれ作業ツリーと同じ、`counting.py` の出力の正式な数え方が "decided"、出力の `owner_decision` の出どころが `ledger.OWNER_DECISION` と同じ、出どころの2行、正式な数え方が C7、順番1b の承認（`owner_approval`）、承認の行（B (ii) を含む）、作業ツリーがきれい、浅い clone でない。項目0（試しの run の作りを直すタスクの合格）は確かめない（reviews/ の記録でリードが確かめる）。

### 位置の照合

- `ledger.check_stats_order`（書く仕組みのすべて、`method-access` の関門、`seal_gkg_run` の drand の前、`verify.py stats-order` と `all`）：`stats-order1` は1件だけ、各記録の中身が上の照合に通る、`stats-order1`・`stats-order1b` は最初の `method-access` より前、最初の `gkg-run-start` の前に `stats-order1b`。
- **区分表の取得は ledger に記録を書かない**（T-037 の差し戻し1回目 中1。初回の版は「acquisition-start のうち区分表のもの」を照らしていたが、その道は本物の流れに無かった）。収集係の `src/collector/themes.py` は、試行と結果を `data/manifest/gdelt-themes.jsonl` に書く。そのため、区分表の取得との前後は git の履歴で照らす（`ledger.check_order1_before_themes`。`verify.py stats-order` と `all`）：
  - F = `git log --all --full-history --format=%H -- data/manifest/gdelt-themes.jsonl` の commit のうち、その版のマニフェストに空でない行があるもの（集合として扱い、並び順と時刻は使わない）。
  - F のどの commit についても、その親（`git rev-parse <C>^@`）のうち少なくとも一つの版の `sealed/ledger.jsonl` に、`stats-order1` の記録の行（正規の形のバイト列）がある。F が空でないのに `stats-order1` が無いとき、親の無い commit が F にあるときも失敗する（seal-order1.md 3章 (2) と同じ考え方）。
  - 作業ツリーのマニフェストの各行の `exclusion_rule_seq`・`exclusion_rule_record_sha256` が、`stats-order1` の記録の seq と行の sha256 と一致する（`ledger.check_themes_manifest_refs`）。
  - git の履歴が無いところ（`.git` の無い写し）では、この照合を行わず、そう表示する（止めない）。`verify.py all` は最後の行に「ただし、次は照らさなかった（終了コード 0 は、照らした検査がすべて通ったことだけを示す）：区分表の取得と順番1 の前後」と出す。**終了コード 0 は、照らした検査がすべて通ったことだけを示す。** 照らさなかったものがあるかは、出力の最後の行で確かめる（T-037 再提出1回目 軽2）。`--rev auto` は git の履歴を要るので、第三者は履歴のある clone で確かめる。
  - **浅い clone では照らせない。** `verify.py stats-order`（と `all`）は、git の履歴があって浅い clone のとき、マニフェストに行のある commit が0件でも、浅い clone なら止まる（「浅い clone である。区分表の取得との前後の照合には履歴が要る」と出して終了コード 1。照合を始める前に `git rev-parse --is-shallow-repository` で確かめるため。浅い clone では、行のある commit が本当に0件かどうかも、親の版も確かめられない）。`--depth` を付けずに clone する（`git fetch --unshallow` でもよい）（T-037 再提出1回目 軽1、T-041 で書き方を実際の条件に合わせた）。浅い clone の確かめ（`--is-shallow-repository`）は、`seal_stats.py` でも `verify.py` でも、GIT_ で始まる環境変数を決めたもの（`GIT_NO_REPLACE_OBJECTS=1` と、存在しないパスの `GIT_GRAFT_FILE`）だけに固定した環境で行う（`ledger.fixed_git_env`。docs/stats/counting.md 4章 (3) と同じ固定の仕方。T-056。T-054 の軽-1）。
  - 書く仕組みの側は、`seal_order1` が、区分表のマニフェストが作業ツリーにも履歴にも無いことを確かめる（2章の項目2）。
  - **この照合の根拠と限界（T-037 再提出1回目 中-C）。**
    - 根拠：区分表のマニフェストの各行には `exclusion_rule_record_sha256`（`stats-order1` の記録の行の sha256）が入り、上の照合はそれが記録と一致することを求める。sha256 は、記録の行ができる前には作れない（記録の行には、直前の行のハッシュ `prev_hash` と `recorded_at`、中身のファイル（封印した時点の HEAD と10件の sha256 を含む）の sha256 が入る）。そのため、照合に通る行は、`stats-order1` の記録ができたあとに書かれたものである。「マニフェストの行を書いたのは順番1 より後」は、暗号的に言える。
    - 限界(1)：push の前に履歴を書き換えたり、ブランチを消したりすれば、git の履歴の照合（F と親の照合）は見つけられない。消された commit は clone に無い。手元の改ざんを防ぐものではない。
    - 限界(2)：照らせるのは、マニフェストの行を**コミットした位置**だけで、区分表を**取得した時点**ではない。取得してから、順番1 のあとにマニフェストを書いてコミットすれば、照合は通る。マニフェストを通さない取得（収集係のコードを通らない取得）は、どこにも跡が残らない。
    - 限界(3)：照らせるのは、clone から辿れる commit（`git log --all` に出るもの）だけである。clone に含まれないブランチや、公開していない commit は照らせない。
    - したがって、この照合が示すのは「公開された履歴の中で、マニフェストの行は順番1 の記録を含む commit の後に入り、その行の中身は順番1 の記録を前提に作られた」ことまでで、「区分表の取得そのものが順番1 より後だった」ことの証明ではない。
- **最初の method-access の前に `stats-order1` の記録が要る**（T-041。T-037 で保留していたもの。収集係のテストが、method-access の前に `stats-order1` と `stats-order1b` の記録を置く形になった（T-032）ので入れた）。`seal_method.py` は、`stats-order1` が無ければ drand を取りにいく前に止まる。書く仕組みを飛ばして足した `method-access` は、`method-access` の関門（`require_method_access`）、ほかの書く仕組み、`verify.py stats-order` と `all` が止める（`ledger.check_stats_order`）。テストは `tests/sealer/test_t037.py` の `TestWithoutOrder1.test_method_and_gkg_refused_without_order1`。
- **最初の method-access の前に `stats-order1b` の記録も要る**（T-043。T-041 の監査 軽-4）。順番1b が無いまま `method-access` を書くと、そのあと順番1b も `gkg-run-start` も書けず、記録が先へ進めなくなるため。`seal_method.py` は、`stats-order1b` が無ければ drand を取りにいく前に止まり、`method-access` の関門（`require_method_access`）、ほかの書く仕組み、`verify.py stats-order`・`all` も止める。関門で照らすのは T-046 から（T-043 では、収集係のテスト `test_sealer_gate_stops_without_order1b` が関門の文言を受け付けなかったので外していた。T-045 で受け付ける形になった）。正規の流れは 順番1 → 順番1b → `method-access` である。

### 確かめるコマンド

<!-- test:offline -->
```sh
PYTHONDONTWRITEBYTECODE=1 python3 -B src/sealer/verify.py stats-order
grep -n '"kind":"stats-order1' sealed/ledger.jsonl | cut -d: -f1 || true
```

- **`verify.py stats-order` と `all` は、`--rev` が `working` でないとき（`--rev auto` で使う。コミットを渡しても同じで、その値は使わない）、順番1・1b の値を、記録の head の版から計算し直して照らす（T-056。T-055 の監査 中-1、T-048 の軽-1）。**（T-049 の時点では計算し直さなかった。）計算し直しに使うのは、`--rev` の値ではなく、記録の `head` である。照らすこと（`verify.recompute_orders`）：
  - **Python の要らない照合（必ず行う）**：記録の `head` の commit がリポジトリにあり、その版の `sealed/ledger.jsonl` が、その記録を足す直前の記録（先頭 seq−1 行）とバイト列で同じであること。`ancestors` の各 commit が `head` の祖先であること。順番1 の対象のうちファイルのもの（`head` の版のファイルと、`1cb463a:`・`2d23cdf:` で始まるものの `git show` の出力）の sha256。順番1b の `files` の各 sha256（`head` の版）と、`order1_ref`（`stats-order1` の記録の seq と行の sha256）。
  - **Python の要る照合**：順番1 の「の出力」と、順番1b の `counting`（`counting.py` を流した出力の sha256 と、`candidate_ids`・`criteria_ids`・`official_candidate`・`official_status`）。
  - **流すフォルダには、記録が sha256 で縛っているファイルだけを置く（T-059。T-058 の監査 重大-A）**。順番1b は記録の `files`（`ORDER1B_REQUIRED_FILES` のちょうど4件。5つ目以降のある記録は、それより前に「記録と合わない」で止まる。T-060）、順番1 は記録の `targets` のうちファイルそのもの（「の出力」でないもの）を、commit ごとに分けて使う（`head` の版の5つと、`1cb463a:` の `src/stats/tagrules.py`）。それぞれを `git show <commit>:<path>` のバイト列から、空の新しいフォルダの同じパスに書き出し、書いたあとに読み戻して sha256 を記録と照らす。git archive は使わない。`__pycache__`・ほかの `.py`・`.pth`・`.gitattributes` など、縛られていないファイルは置かない。そのため、偽る側が commit に足したファイル（`src/stats/__pycache__` の .pyc、標準ライブラリを隠す `src/stats/fractions.py`、`Src/stats/counting.py` など）は流れない。流すスクリプトが縛られたファイルでない、縛られたファイルの名前が大文字小文字か Unicode の正規化（NFD にそろえて casefold。NFC と NFD は同じに扱う）だけで重なる、書き出せない、書いたフォルダの中身が縛られたファイルと違う、なら「記録と合わない」として止める（T-058 の名前のぶつかりの照合は、この名前に当てる形で残した）。
  - **Python の流し方（T-059）**：`<python> -I -B -X pycache_prefix=<空の一時フォルダ> -c <起こすプログラム> <スクリプト>`（`verify.python_command`）。`-I` で環境変数（`PYTHONPATH` など）・利用者の site・カレントフォルダを使わない。`-B` で .pyc を書かない。`-I` では `PYTHONPYCACHEPREFIX` が読まれないので、`-X pycache_prefix=` で空のフォルダを指し、.pyc をそこからしか読ませない（スクリプトの隣の `__pycache__` も、macOS の `/usr/bin/python3` が既定で使う `~/Library/Caches/com.apple.python` も読まない）。`-I` はスクリプトのフォルダも `sys.path` に入れないが、順番1 の `tagrules.py` は同じフォルダの `exclusion.py`（縛られたファイル）を読み込むので、起こすプログラム（`verify.RUNNER`）が、スクリプトのフォルダだけを `sys.path` の先頭に戻してから `runpy.run_path` で流す（ふつうにスクリプトを流したときと同じ並び。そのフォルダには縛られたファイルしか無い）。
  - 計算し直しの git（`cat-file`・`show`・`merge-base`）は、GIT_ で始まる環境変数を固定した環境（`ledger.fixed_git_env`）で行う。
  - 流す Python は、verify を動かしている Python（`sys.executable`）である。動作を確かめた版は、Python 3.14.2（`.venv/bin/python`）と 3.9.6（macOS の `/usr/bin/python3`）で、どちらでも本物の記録（seq 1〜6）で終了コード 0、照らした項目は 25 で、値は記録と一致した（T-056 差し戻し1回目。T-059 の形（縛られたファイルだけ、`-I`）でも同じ）。
  - **止めるとき**：値が一つでも違うとき。`head` の版のスクリプトが 0 以外で終わる、または出力が読めないときも、「記録と合わない」として終了コード 1 で止める（記録は、その版で流した出力があると主張しているため。リードの判断）。
  - **照らさなかったとするとき**：利用者の環境の都合で計算し直せない項目だけ。具体的には、Python を起動できない、git の履歴が無い、の2つに限る（T-056 再提出1回目 中-A。T-059 で git archive をやめたので、「git archive ができない」は無くなった。記録の head の commit や縛られたファイルを git が読めないときは、「記録と合わない」で止まる）。止めずに、項目ごとに「照らさなかった：順番1・1b の値：<項目>（理由）」と出し、`all` の最後の行にも並べる。照らさなかった項目があっても、ほかの項目と記録の照合は続ける。`--rev working`（既定）でも計算し直さず、そう表示する（テスト用の仮の記録（実在しない head を持つもの）を使うテストが `--rev working` で verify を流すため）。第三者は `--rev auto` で確かめ、最後の行を読む。
  - **記録を作る側の commit の中身で起こせることは、どれも「照らさなかった」にしない**（T-056 再提出1回目 中-A）。縛られていないファイルは置かないので、commit に足した名前（長すぎる名前、UTF-8 でない名前、`Src/` など）は流れに関わらない。縛られたファイルが流したときに 0 以外で終わる、時間内（`verify.RUN_TIMEOUT_SECONDS`、1800 秒）に終わらない、出力が読めない、なら「記録と合わない」で止まる。
  - **信用できない記録を確かめるとき**：計算し直すと、記録の `head` の版のコード（`counting.py` など）が手元で動く。記録やリポジトリを信用できないときは、隔離した環境（使い捨ての仮想の機械やコンテナ）で、ネットワークを切って流す（T-056 差し戻し1回目 軽-1）。
  - これで照らせるのは「記録の値が、`head` の版から計算した値と同じ」ことまでである。作業ツリーの今のファイルが封印したときと同じか（凍結）は、docs/stats/seal-order1.md 3章 (1) の手順で、作業ツリーの値を計算して記録と比べる。
- **verify を使わずに手で確かめる手順（T-056、T-059）**：記録の中身のファイル（`sealed/stats-order1-….json`・`sealed/stats-order1b-….json`）の `head` を H、その記録の seq を N とする。上の注意のとおり、信用できない記録は隔離した環境で行う。bash・zsh・macOS の `/bin/sh` のどれでも動く書き方にしてある。
  ```sh
  PY=/usr/bin/python3                                                           # 使う Python を決めて書く。.venv/bin/python（3.14.2。記録を作った版）でも同じ値になる（T-059 で両方を確かめた）
  H=<記録の head の40桁>; N=<記録の seq>                                          # zsh でも同じに動くよう、変数は "${H}" の形で使う
  # verify と同じく、git は GIT_ の環境変数を固定して動かす（replace・grafts で読む版が変わらないように）。
  # ほかの GIT_ の環境変数（GIT_DIR など）は、次の1行で外す（何も無くても失敗しない）
  for v in $(env | sed -n 's/^\(GIT_[A-Za-z0-9_]*\)=.*/\1/p'); do unset "$v"; done
  env | grep ^GIT_ || echo none                                                 # none と出ること
  export GIT_NO_REPLACE_OBJECTS=1 GIT_GRAFT_FILE=/dev/null/no-graft-file
  git cat-file -e "${H}^{commit}" && echo ok                                    # head の commit がある
  head -n $((N-1)) sealed/ledger.jsonl > before.jsonl                           # その記録の直前までの記録（場所は自分で決める）
  git show "${H}:sealed/ledger.jsonl" | cmp - before.jsonl && echo same         # head の版の記録とバイト列で同じ
  git merge-base --is-ancestor <ancestors の各 commit> "${H}" && echo ok
  git show "${H}:docs/stats/counting.md" | shasum -a 256                        # files の各パスも同じ形
  # 計算し直し：記録が sha256 で縛っているファイルだけを、git show から空の新しいフォルダに書く（git archive は使わない）。
  # mktemp -d には必ず場所を付ける（macOS では、場所を付けないと TMPDIR を見ない）
  C=$(mktemp -d "${TMPDIR:-/tmp}/pycache.XXXXXX")                             # 空の pycache_prefix
  R='import os, runpy, sys; p = sys.argv[1]; sys.argv = sys.argv[1:]; sys.path.insert(0, os.path.dirname(os.path.abspath(p))); runpy.run_path(p, run_name="__main__")'
  # 順番1b（stats-order1b）のとき：files が決まった4件と一致することを先に確かめる（T-060。ok と出ること）。
  # そのうえで、その4つだけを書いて、counting.py を流す
  "$PY" -B -c 'import json, sys; d = json.load(open(sys.argv[1])); p = [f["path"] for f in d["files"]]; print("ok" if sorted(p) == sorted(["docs/stats/counting.md", "src/stats/counting.py", "tests/stats/test_counting.py", "docs/stats/seal-order1.md"]) else p)' sealed/stats-order1b-<…>.json
  D=$(mktemp -d "${TMPDIR:-/tmp}/verify.XXXXXX")
  for p in docs/stats/counting.md src/stats/counting.py tests/stats/test_counting.py docs/stats/seal-order1.md; do mkdir -p "$D/$(dirname "$p")" && git show "${H}:$p" > "$D/$p" && shasum -a 256 "$D/$p"; done   # 各 sha256 が files と同じこと
  (cd "$D" && find . -type f | sort)                                            # 書いた4つだけがあること
  (cd "$D" && "$PY" -I -B -X pycache_prefix="$C" -c "$R" src/stats/counting.py | shasum -a 256)    # counting.output_sha256
  # 順番1（stats-order1）のとき：targets の名前が決まった10件と一致することを先に確かめる（T-065。ok と出ること）。
  # そのうえで、別の空のフォルダに、targets のファイル（「の出力」でないもの）のうち head の版の5つを書いて流す
  "$PY" -B -c 'import json, sys; d = json.load(open(sys.argv[1])); n = [t["name"] for t in d["targets"]]; print("ok" if sorted(n) == sorted(["src/stats/exclusion.py", "src/stats/exclusion.py の出力", "tests/stats/test_exclusion.py", "src/stats/tagrules.py", "src/stats/tagrules.py の出力", "tests/stats/test_tagrules.py", "docs/stats/tags-naive.md", "1cb463a:src/stats/tagrules.py", "1cb463a:src/stats/tagrules.py の出力", "2d23cdf:reviews/T-020.md"]) else n)' sealed/stats-order1-<…>.json
  D=$(mktemp -d "${TMPDIR:-/tmp}/verify.XXXXXX")
  for p in src/stats/exclusion.py tests/stats/test_exclusion.py src/stats/tagrules.py tests/stats/test_tagrules.py docs/stats/tags-naive.md; do mkdir -p "$D/$(dirname "$p")" && git show "${H}:$p" > "$D/$p" && shasum -a 256 "$D/$p"; done   # 各 sha256 が targets と同じこと
  (cd "$D" && find . -type f | sort)                                            # 書いた5つだけがあること
  (cd "$D" && "$PY" -I -B -X pycache_prefix="$C" -c "$R" src/stats/exclusion.py | shasum -a 256)   # 「src/stats/exclusion.py の出力」
  (cd "$D" && "$PY" -I -B -X pycache_prefix="$C" -c "$R" src/stats/tagrules.py | shasum -a 256)    # 「src/stats/tagrules.py の出力」
  # 順番1 の 1cb463a の版：もう一つ別の空のフォルダに、その1つだけを書いて流す
  E=$(mktemp -d "${TMPDIR:-/tmp}/verify.XXXXXX"); mkdir -p "$E/src/stats" && git show 1cb463a:src/stats/tagrules.py > "$E/src/stats/tagrules.py"
  (cd "$E" && "$PY" -I -B -X pycache_prefix="$C" -c "$R" src/stats/tagrules.py | shasum -a 256)    # 「1cb463a:src/stats/tagrules.py の出力」
  sed -n 5p sealed/ledger.jsonl | tr -d '\n' | shasum -a 256                      # order1_ref.record_sha256（seq 5 の行）
  ```
  `R` は verify の `RUNNER` と同じで、`-I` が外すスクリプトのフォルダだけを戻す（`tagrules.py` が同じフォルダの `exclusion.py` を読むため）。1cb463a の版は、seal-order1.md 1章では `tagrules.py` として書く形だが、`src/stats/tagrules.py` として書いても出力は同じ（verify はこちらの形）。書き出すファイルの名前は、決まった一覧（順番1b は `ledger.ORDER1B_REQUIRED_FILES` の4件、順番1 は `ledger.ORDER1_TARGET_NAMES` のうちファイルそのものの名前）として手順の `for` の行に固定で書いてある（シェルの変数に並べて分けると、zsh では分かれないため）。記録の `files`・`targets` がその一覧とちょうど一致することは、書き出す前の確認の行（`ok` と出ること）で確かめる（T-065。T-060 の軽-1）。確認の行は、`tests/sealer/test_t065.py` が本物の記録で `ok` を出し、1件足した中身では `ok` を出さないことを、両方の Python で確かめている。
- **テストを流す Python（T-068。T-065 の監査 中-1）**：`tests/sealer` の `test_t037.TestRealClone.test_before_order1_at_77d0dd2` は、順番1 の封印の直前の commit（77d0dd2）の clone で順番1 と順番1b を封印し直し、その版の `tests/stats` を流す。流す Python は、順番1 の記録の `python.version`（3.14.2）と同じ版（3.14）に固定する。プロジェクトの `.venv/bin/python` があればそれを使い、無ければテストを流している Python が同じ版のときだけ使い、どちらも無ければ skip する（3.9 では 77d0dd2 の `tests/stats` の test_t019 の2件が、開くファイルが違って落ちるため。T-059 の報告）。第三者は、`python3 -m venv .venv`（3.14）を用意してから `tests/sealer` を流す。また、この clone は `git init` と、その commit だけの `git fetch` で作る（後の参照を持たない。T-065）。参照でない commit を取るのは git の protocol v2 に頼るので、テストは `-c protocol.version=2` を付ける（git 2.18 以降）。
- 記録の10件の sha256 を作業ツリーで計算し直して照らす手順は、docs/stats/seal-order1.md 3章 (1) のとおり（`shasum -a 256 <ファイル>`、`git show <commit>:<path> | shasum -a 256`、`PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -B src/stats/exclusion.py | shasum -a 256` など）。順番1b の `counting.output_sha256` は `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -B src/stats/counting.py | shasum -a 256` と照らす。

### 順番2 への申し送り（統計係の T-036 の監査の軽-4）

- 順番2 の記録で、待つ（pending）・止まった（stopped）・封印した結果を区別するときは、**待つ記録は kind ではなく status で区別する**。kind を分けると、「順番2 の記録が何件あるか」「どの記録を参照するか」の規則（seal-order1.md 3章 (2)）が kind ごとに分かれ、数え方が自己申告に近くなるため。順番2 の kind は `stats-order2`（`ledger.ORDER2_KIND`。T-073 で決めた。14章）。記録の中身のうち、使った run を示す3つのキーは T-073 で決めた。残りの形は、順番2を封印するタスクで決める。

### 収集係への申し送り（src/collector は封印係の範囲の外）

- `themes.EXCLUSION_RULE_KIND` に入れる値は `"stats-order1"`（`ledger.ORDER1_KIND`）。
- 関門が照らす記録は `ledger.first_order1(records)`（`stats-order1` は1件だけなので、その1件）。
- 記録の中身は `ledger.read_target_json(root, rec, "stats-order1")` で読める（sha256 を照らしたうえで JSON を返す）。`ledger.check_order1_doc(rec, doc)` が中身を照らし、`{対象の名前: sha256}` を返す。名前は `ledger.ORDER1_TARGET_NAMES`（seal-order1.md 1章の表の「対象」の列）と同じ文字列なので、収集係が持つ10件と比べれば、どの規則を封印したかを照らせる。
- 区分表のマニフェストの各行の `exclusion_rule_seq`・`exclusion_rule_record_sha256` は、verify が上のとおり照らす。区分表の取得のコミットは、`stats-order1` の記録を含む commit の後に作る。

## 14. 順番2の前の関門（T-073）

統計係の `src/stats/counting.py`（順番2で当てはめるコード）は、日の集計を自分で読み、`ledger.require_gkg_run_result` を呼ばない。そのため、counting.py だけでは、使う run のマニフェストの時刻証明（`gkg-run-result`。12章）を封印する前に集計できる（T-069 の監査 中-1）。counting.py は順番1b（seq 6）で sha256 を封印したコードなので直せない（reviews/T-072.md）。そこで、関門を封印係の側に置く。順番2は、封印係が封印した版の counting.py を当てはめる形のままである（docs/stats/counting.md 4章、docs/stats/seal-order1.md 3章 (2)）。

関門と記録は、次の固定の規則で縛る（T-073 差し戻し2回目）。R は、試しの run のマニフェストの、行の並びで最初の `run-start` の run である（counting.md 4章 (2) の R と同じ）。

- 順番2の記録は、`stop_kind` が何であっても、R の `gkg-run-result` を持つ。
- 試しの run のマニフェストは、ファイル全体のバイト列が、R の `gkg-run-result` が縛るバイト列と同じでなければならない。R は完了しているので、あとに行が足されることを許さない。
- decide() が正式な run X の段に進む形なら、X の `gkg-run-result` も持つ。
- 記録の行き先（`stop_kind`・`input_run`・段の記録）は、マニフェストから計算し直して照らす。書く仕組みは HEAD の版で、verify は記録を最初に含んだコミットの版で計算する。

### 封印係の順番2の手順（この順で行い、途中で止まったら、それより後のことはしない）

1. **関門**：counting.py を動かす前に、次を流す。
   ```sh
   PYTHONDONTWRITEBYTECODE=1 python3 -B src/sealer/order2_gate.py
   ```
   - (1) **git の確かめ**：二つのマニフェストについて、counting.md 4章 (1) と同じ条件を確かめる。一つは、作業ツリーと HEAD が同じであること（どちらにも無いのは同じとみなす。通常のファイルでなければ違う）。もう一つは、`git log --all --full-history --format=%H -- <パス>` の各 commit の版（無い版は空）が、HEAD の版の先頭と同じであること。通らなければ閉じる。git は `GIT_` の環境変数を固定して動かす。
   - (2) **R の gkg-run-result**：HEAD の版から R を決め、`ledger.require_gkg_run_result("trial", R)` を必ず呼ぶ。この呼び出しは、鎖とすべての `.ots`、マニフェストの照合、R の記録を確かめる。さらに、試しの run のマニフェストの全体（行の数と sha256）が、その記録の `manifest_lines`・`manifest_sha256` と同じことを確かめる。R が決まらない（`run-start` が無い、形が違う）とき、R の記録が無いとき、全体が違うときは閉じる。
   - (3) **行き先**：`ledger.order2_plan` で decide() の行き先を決める（下の「行き先の決め方」）。待つなら閉じる。正式な run X の段に進む形なら、`require_gkg_run_result("official", X)` も呼び、通らなければ閉じる。
   - 開けば、順番2の記録に入れる `trial_result`・`input_run`・`gkg_run_result` と、決めた行き先（`plan`）を JSON で書き、0 で終わる。
   - 閉じれば理由を書いて 1 で終わる。**このときは counting.py を動かさず、順番2の記録も作らない。止まった (b) としても記録しない。** 理由（前提 → 結論）：
     - 前提1：順番3は、順番2の記録のうち、待つを除いて seq の最も小さいものを恒久に参照する（`counting.select_order2_record`。counting.md 4章 (3) の 5）。
     - 前提2：関門が閉じる条件は、どれも日の集計の値には依らない。条件は五つある。git の確かめに通らない、R が決まらない・R の時刻証明が無い・全体が違う、待つ、正式な run の段で X の時刻証明が無い、マニフェストが記録と合わない。
     - 結論：関門の失敗を記録すると、その記録が順番2として固まり、あとで正しく行った順番2が参照されなくなる。前提2 から、記録しないことで、結果を見て選べる余地は増えない。
   - git の確かめに通らないとき、封印した規則（counting.md 4章 (1)）では decide() に None を渡して (b) で止まる。関門はその前に閉じるので、(b) は記録されない。前提：作業ツリーを汚すこと（コミットしていない行を足すなど）は、運営がいつでもでき、いつでも戻せる。結論：これを (b) として恒久に記録すると、運営が作業ツリーをわざと汚して (b) を固め、基準 B1〜B5 の結果と欄の手厚さを出さないことを選べる。関門で閉じれば、その選び方はできない。
2. seal-order1.md 3章 (2) の (a)（時機の条件）と (c)（コードの sha256）を確かめる。どちらかで止まれば、decide() は流さない。順番1b の記録の版の counting.py を `apply` で当てはめる。
3. 順番2の記録（kind は `stats-order2`。`ledger.ORDER2_KIND`）の中身に、次を入れる。記録は、マニフェストを変えないコミットに入れる（verify は、記録を最初に含んだコミットのマニフェストで行き先を計算し直す）。ほかのキー（参照する順番1b、時機の条件の確かめなど）は、順番2を封印するタスクで決める。
   - `stop_kind`：null（決まった・待つ）か、`"a"`・`"b"`・`"c"`（seal-order1.md 172行。止まった記録は、どの条件で止まったかを stop_kind で残す）。
   - `trial_result`・`input_run`・`gkg_run_result`：1 の出力をそのまま入れる。(a)・(c) で止まった記録にも入れる。
     - `trial_result` は R の `gkg-run-result`（`{seq, record_sha256}`）で、どの記録も必ず持つ。
     - `input_run` は decide() が段に進む run（`{mode, run_id}`）。段に進む前に止まる形のときだけ null。
     - `gkg_run_result` は `input_run` の run の `gkg-run-result`。`input_run` と一緒に null になり、`input_run` が R なら `trial_result` と同じ。
   - `counting_output`：decide() の出力そのもの。**decide() を流した記録（stop_kind が null か `"b"`）だけが持つ。** (a)・(c) は decide() を流す前に決まるので持たない。

`stats-order2` は、まだ許可リスト（`ledger.ALLOWED_KINDS`）に入れていない。記録の形の残りが決まるまで、この kind の記録は鎖の検査で止まる（形の決まっていない記録を通さないため）。許可リストに入れるのは、順番2を封印するタスクである。

### 記録の照合

**形の照合（`ledger.check_order2_run`）**：`ledger.check_stats_order` が、`stats-order2` の記録ごとに照らす。書く仕組み（`seal_records.check_new`）は、どの種類を書くときも、追記したあとの記録に対して `check_stats_order` を呼ぶ。`verify.py stats-order`・`all` も同じ関数を呼ぶ。
- 中身に `stop_kind`・`trial_result`・`input_run`・`gkg_run_result` がある。`stop_kind` は null か a・b・c。
- `trial_result` は、**鎖の中でこの記録より前の**、mode が trial の `gkg-run-result`（行の sha256 が同じ）。それが R であることは、下の行き先の照合でマニフェストから確かめる。
- `counting_output`：(a)・(c) の記録は持たない。null と b の記録は持つ。null なら status は decided か pending、b なら stopped。
- `input_run` と `gkg_run_result` は、両方 null か両方ある。ある場合、`gkg_run_result` は鎖の中でこの記録より前の、`input_run` の mode・run_id の `gkg-run-result`。`input_run` が trial なら、`gkg_run_result` は `trial_result` と同じ。
- `counting_output` があれば、次を照らす。
  - `runs.trial.run_id` が R。
  - `input_run` があれば、段（`trial`・`official`）の記録があって `input_run` と同じ（trial なら run_id も）。`runs.<mode>.run_id` が `input_run` の run_id。decided なら `input_mode`・`input_run_id` も同じ。
  - `input_run` が null なら、stopped で段の記録が無い。

**行き先の照合（`ledger.check_order2_plan`）**：形の照合のうえで、マニフェストから R と行き先を計算し直し、記録と照らす。
- 書く仕組み（`seal_records.check_new`）は、HEAD の版のマニフェストで計算する。
- `verify.py stats-order`・`all` は、記録を最初に含んだコミット（`--rev auto` と同じ探し方）の版で計算する。HEAD の版は使わない。git の履歴が無いとき、浅い clone のとき、記録がまだコミットされていないとき（T-074。T-073 の監査 軽-3）は、「照らさなかった」と出す。まだコミットされていない記録は、コミットしたあとで流せば照らす（`--rev auto` の `targets` は、これまでどおり、コミットに無い記録で失敗する）。
- 照らすこと：
  - R が決まり、`trial_result` の run_id が R。
  - 試しの run のマニフェストの全体が、`trial_result` の縛るバイト列と同じ。
  - 行き先が待つなら、記録があること自体が食い違い。
  - 段に進む前に止まる形なら、`input_run` は null で、`stop_kind` は null でない。
  - 段に進む形なら、`input_run` がその mode・run_id。

テストは `tests/sealer/test_t073.py` にある。
- `TestChainUnit`：形の照合。R の時刻証明が後にある・無い（stop_kind が何でも）、別の run の時刻証明（G4）、行の sha256 が違う、decide() の出力と食い違う、stop_kind と counting_output が合わない、のどれでも止まる。
- `TestPlanCheck`：行き先の照合。監査の中-1 の形（改行を足して正式な run の `trial_manifest_sha256` を合わなくした、段に進む前に止まる形）も、全体の照合で止まる。
- `TestChainWriterAndVerify`：書く仕組みが、行き先の食い違う記録を書かないこと。照合を飛ばして足した記録を verify が止めること。浅い clone では「照らさなかった」になること。
- `TestGate`：R の時刻証明の前は閉じ、封印のあとに開くこと。全体が違えば閉じること。改行を足してコミットすると閉じること。作業ツリーが HEAD と違うとき、過去の版が先頭と同じでないときに閉じること。

`tests/sealer/test_t074.py` にもある（T-074。T-073 の監査 軽-2・軽-3。どれも、照合を外す・変えると落ちる）。
- `TestN8FirstCommit`：記録を最初に含んだコミットの版では行き先が「段に進む前に止まる」、HEAD の版では「試しの run の段」になる流れで、試しの run の段の形の記録を verify が止めること（HEAD の版を使えば通ってしまう）。
- `TestN11N12`：`input_run` が R なのに、`gkg_run_result` が R の時刻証明と同じ中身の別の記録を指すと止まること（N11）。計算し直した行き先が「待つ」なら止まること（N12）。
- `TestUncommittedOrder2`：まだコミットされていない記録は「照らさなかった：記録がまだコミットされていないので、…」で 0 になり、コミットしたあとは照らすこと。

### 行き先の決め方（`ledger.order2_plan`。decide() と同じ）

counting.decide()（counting.md 4章 (2) の表の 1〜7）と同じ順と条件で、日の集計を読まずに、行き先を次の三つのどれかに決める。基準は、形の照合と同じ「decide() の出力に段（trial・official）の記録があるか」である（差し戻し2回目 3）。
- 待つ（pending）
- 段に進む前に止まる（stop）
- run X の段に進む（stage）。段に進んだあとは、日の集計を読むか、正式な run の day の行の形が違えば、読む前に止まる。

`TestPlanSameAsDecide` は、監査の組み合わせ（`a73fuzz.py`）を広げた形で確かめる。試しの run の11通りと、正式な run の21通りの、それぞれの組み合わせについて、封印済みの counting.decide() を流し（日の集計は読ませない）、次の三つが一致することを比べる。
- decide() が pending を返すことと、待つ。
- decide() が段の記録なしに止まることと、stop。
- decide() の段の記録（と runs）と、stage の run。

監査が見つけた形は、次のようにそろえた。
- (i) 試しの run の最初の run-start の形が違う：stop。
- (ii) 正式な run の3日の day の行がまだ無い：待つ（閉じる）。
- (iii) 正式な run の day の行の形が違う：decide() は段（official）を記録してから止まるので、stage。

counting.py は読み込むだけで変えない。そろえられない形は見つかっていない。

この決め方と固定の規則から、次のことが従う。
- R が決まらない、または R の `gkg-run-result` が無いうちは、順番2は行えない。試しの run の無い形（counting.md 4章 (2) の2段目の一部）では、順番2は行えない。本物の記録には試しの run（seq 8）があるので、R の `gkg-run-result` を封印すれば行える。
- 2段目（正式な run の段）に進む形では、正式な run の `gkg-run-result` も要る。`gkg-run-result` は `run-complete` の行を求める（12章）ので、正式な run の全体が終わり、そのマニフェストを封印したあとになる。
- 待つ場合は関門が閉じるので、待った試みは記録しない。counting.md 4章 (2) の「待つを含めて毎回記録する」提案は、この場合には当たらない。待った回数は第三者には分からない。ただし待つは、順番3の参照先の選び方に入らない（`select_order2_record` は待つを数えない）。そのため、参照先は変わらない。
- 段に進む前に止まる形（正式な run の `trial_manifest_sha256` が合わないなど）は、(b) として記録される。これは封印した規則のとおりである。ただし、R の `gkg-run-result` を封印したあとは、試しの run のマニフェストを1バイトも変えられない（改行を足すのも、全体の照合で止まる）。マニフェストには空の行を置けない（`ledger.manifest_rows` と `check_gkg_manifests` が拒む。差し戻し2回目 5）ので、空の行を足してから R の時刻証明を付けることもできない。残るのは、正式な run のマニフェストの行（収集係のコードが書き、`check_gkg_manifests` が gkg-run-start の記録と照らす）で決まる形である。

### 正式な run が始まっているときの、試しの run での順番2（統計係の指摘の確認）

統計係の指摘は次のとおり：decide() は、正式な run の `run-start` の `trial_manifest_sha256` を照らすので、最初に正式な run のマニフェストを読む。そのため、正式な run が始まっていて `gkg-run-result` がまだ無い期間は、試しの run での順番2もできなくなるかもしれない。確かめた結果は次のとおり。

- decide() が正式な run のマニフェストから読むのは、最初の `run-start` の `trial_manifest_sha256` と `trial_run_ids` だけで、ledger は読まない。関門が求める時刻証明は、R のものと、段に進む run のものだけである。前提：R が終わっていれば、段に進む run は R である。結論：正式な run の `gkg-run-result` が無くても、試しの run での順番2は、その理由では止まらない。指摘のとおりにはならない。
- ただし、正式な run の取得の途中では、関門が閉じる（記録は作らない）。理由は次の二つ。
  - 正式な run のマニフェストに、コミットしていない行があるとき。1 の git の確かめで閉じる。
  - 正式な run の `gkg-run-start` の記録があるのに、作業ツリーにマニフェストが無いとき。`require_gkg_run_result` の照合で閉じる。
  - どちらも、取得が終わってコミットしたあとで、やり直せる。
- 順番の上の結論：試しの run での順番2は、R の `gkg-run-result` を封印したあと、正式な run を始める前に行うのが早い。正式な run を始めたあとでも、マニフェストをコミットし、取得の処理が書いていない間なら行える。

### 限界

- **counting.py を手で直接動かせば、`gkg-run-result` の封印より前に集計できる。** counting.py は関門を呼ばず、封印済みなので直せない。この関門で防げるのは、封印係の手順（`order2_gate.py`）を通る場合だけである。手で先に動かして結果を見たこと自体は、どこにも記録されない。そこで、記録の側を、**鎖の順序で事後に見つけられる**形にした。順番2の記録は、R の `gkg-run-result`（段に進む run が正式な run なら、その記録も）より後にしか書けない。より前に置かれた記録や、マニフェストから計算し直した行き先と食い違う記録は、verify が止める。見つけられるのは、記録の並びとマニフェストに現れる場合だけである。
- 手で先に集計できる窓は、run の `run-complete` から `gkg-run-result` の封印までのあいだである。窓を短くするため、`gkg-run-result` は `run-complete` のすぐあとに封印する（12章「マニフェストの時刻証明」）。
- 関門が閉じた試みは記録しないので、閉じた回数は第三者には分からない。閉じる条件は、日の集計の値に依らない（上の手順1の前提2）。
- (a)・(c) の記録は decide() の出力を持たないので、記録の中の出力とは照らせない。照らすのは、R（と段の run）の時刻証明が鎖の中で前にあることと、マニフェストから計算し直した行き先と食い違わないことまでである。
- verify の行き先の照合は、記録を最初に含んだコミットのマニフェストを使う。記録とマニフェストの変更を同じコミットに入れると、書く仕組みが見た HEAD の版と違う版で計算することになる（食い違えば止まる）。そのため、記録はマニフェストを変えないコミットに入れる。
- `counting_output.inputs`（3日のファイルの名前と sha256）と、`gkg-run-result` で縛ったマニフェストの day の行との照合は、順番2を封印するタスクで扱う（T-073 の採点の申し送り）。
