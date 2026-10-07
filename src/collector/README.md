# 収集係のコード（src/collector）：試運転の手順3・手順4 の取得の手順書（T-015、T-018）

データ出典：GDELT Project（https://www.gdeltproject.org/）。本プロジェクトは GDELT Project と提携・承認の関係にありません。
Data: The GDELT Project (https://www.gdeltproject.org/).

| ファイル | 役割 |
|---|---|
| `acquire_filelist.py` | 手順3の入口のスクリプト。関門、封印の仕組みにつなぐアダプタ、取得のコードの sha256 の固定 |
| `filelist.py` | 一覧の取得、2020-12-15 以降の行の破棄、項目の絞り込み、保存、マニフェストの追記。ファイルの日の規則（4章）は gkg.py も使う |
| `codegate.py` | 入口のスクリプトが共通に使う関門の部品（git を環境変数なしで動かす、未コミット・無視されるファイル・skip-worktree の検査、sealed/・data/manifest のリンクの検査）。T-018 |
| `acquire_gkg.py` | 手順4の入口のスクリプト。最初に `ledger.require_method_access()` を引数なしで呼び、関門のあとで gkg.py を動かす。T-018。まだ実行していない |
| `gkg.py` | 手法を作る期間の GKG 2.1 の取得、メモリの上での欄の破棄と集計、日ごとの集計の保存、取得の記録とマニフェスト。T-018 |
| `themes.py` | テーマの区分表の取得（件数の欄を捨てる）。T-018 ではコードだけで、取得元の URL は未定。取得は統計係の除外の規則の封印のあとの別のタスク |
| `privacy_scan.py` | メールアドレスの形の文字列の検査（filelist.py・gkg.py・themes.py が書く前に使う。コミットの前と後にも実行する） |

細かい決まりは、各ファイルの docstring に書いてある。この文書は、実行の手順と限界をまとめる。

## 1. 実行の前にオーナーがすること

1. 保存先のフォルダを2段、前もって作る。スクリプトはフォルダを作らない。
   ```sh
   mkdir ~/Desktop/news-stick-data
   mkdir ~/Desktop/news-stick-data/gdelt-filelist
   ```
   - 2段とも、シンボリックリンクではない普通のフォルダにする（リンクだと関門で止まる）。
   - Git の作業ツリーの中に作らない（`~/Desktop` や `~` に `.git` があると止まる）。
   - 中身は空でよい。同じ名前のファイルがあれば、上書きせずに止まる。
2. Mac の iCloud の「デスクトップと書類フォルダ」を使っているかを確かめる。使っていれば、ファイル一覧の本体（約40 MB）は iCloud にも送られる。スクリプトはこれを確かめない。送られてよいかは、オーナーが判断する。
3. `.venv` に OpenTimestamps のクライアントがあることを確かめる（`.venv/bin/ots --version`）。
4. 封印係の T-014 と、このタスク T-015 が合格し、コミットされていること。`src/collector` と `src/sealer` に未コミットの変更が無いこと（`git status`）。あれば関門で止まる。
5. 通信を許可する（下の 3章の宛先だけ）。

関門で確かめるが、オーナーが前もって知っておくこと。

- 区切りの封印（periods。今は seq 1）の時刻証明が Bitcoin で確定していること。seq 1 は 2026-10-06 に確定済み（`sealed/ledger.jsonl.seq000001.bitcoin.ots` とヘッダ）。
- candidates の記録（今は seq 2）があること。candidates の時刻証明の確定は、関門では求めない。

## 2. 実行するコマンド（T-016）

プロジェクトのルートで、次の1行だけを実行する。引数は受け付けない（保存先・通信・時計などは固定）。

```sh
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -B src/collector/acquire_filelist.py
```

動きの順番（`acquire_filelist.py` の docstring に詳しく書いた）。

1. 関門（ネットワークを使わない）。次の5つのどれかが欠ければ、何も書かずに終了コード 1 で止まる（T-018 で (4) を強め、(5) を加えた）。
   - periods と candidates の記録があり、記録の鎖と .ots が検証に通る
   - 区切りの封印（periods）の時刻証明が Bitcoin で確定している
   - 保存先の2段のフォルダがある
   - 取得のコードに未コミットの変更・無視されるファイル・skip-worktree などの印が無い（git は環境変数を受け継がずに実行する）。filelist.py・privacy_scan.py・codegate.py の sha256 が、入口のスクリプトに固定した値と一致する
   - sealed/・data/・data/manifest/ がシンボリックリンクでなく、プロジェクトの下にある
2. `seal_acquisition.start`：drand の最新の回を取り、`acquisition-start` を記録に追記し、`.ots` を作る（通信あり）。
3. 一覧を取得する（通信あり）。2020-12-15 以降の行はメモリの上で捨てる。本体を保存先に書き、`data/manifest/gdelt-filelist.jsonl` に1行追記する。
4. `seal_acquisition.result`：`acquisition-result` を記録に追記し、`.ots` を作る（通信あり）。
5. 結果（seq、ファイル名、行数、sha256）を表示する。

実行のあとにすること（T-016 の範囲。ここでは手順だけ）。

- `data/manifest/gdelt-filelist.jsonl` と `sealed/` の新しいファイルをコミットする。本体（`~/Desktop/news-stick-data/gdelt-filelist/` の下）はコミットしない。
- コミットの前と後に `python3 -B src/collector/privacy_scan.py` と `--all-history` を実行する。

途中で止まったとき。

| 止まった場所 | 残るもの | すること |
|---|---|---|
| 関門 | 何も書かない | 理由を直して、もう一度実行する |
| 2 の途中 | 封印の記録だけ（.ots が無いこともある） | リードに報告する（`stamp.py stamp --seq N` が要る場合がある） |
| 3 | result の無い `acquisition-start` | リードに報告する。記録は消さない |
| 4 | 本体とマニフェストの行、result の無い `acquisition-start` | リードに報告する。result を後から書くか、やり直すかはリードが決める |

どの場合も、ファイルは消さない（削除はリードを通してオーナーの承認を得る）。

## 3. 通信先

取得の1回で通信するのは、次の宛先だけ。

| 目的 | 宛先 | コード |
|---|---|---|
| ファイル一覧 | `https://data.gdeltproject.org/gdeltv2/masterfilelist.txt`（GET 1件。再試行は最大2回） | `filelist.py`（ホストの許可リストは data.gdeltproject.org だけ。リダイレクトとプロキシを使わない） |
| drand の最新の回（quicknet） | `https://api.drand.sh/…`。応答が無ければ `https://api2.drand.sh/…`、`https://api3.drand.sh/…`、`https://drand.cloudflare.com/…` の順 | `src/sealer/netfetch.py` |
| 時刻証明（`ots stamp`。start と result の2回） | `https://a.pool.opentimestamps.org`、`https://b.pool.opentimestamps.org`、`https://a.pool.eternitywall.com`、`https://ots.btc.catallaxy.com` | `src/sealer/stamp.py`（`ledger.STAMP_CALENDARS`） |

- GDELT Cloud（gdeltcloud.com）には送らない。許可リストの外の URL は、送る前に止まる。
- `ots stamp` が送るのは、記録の先頭のハッシュに乱数を付けて、もう一度ハッシュにしたものだけ。
- Bitcoin のブロックのヘッダの取得（blockstream.info、mempool.space）は、取得の1回には含まれない。後で `seal_bitcoin.py confirm` を実行するときに使う（封印係の手順）。
- 宛先と待ち時間・再試行の上限の値は、`filelist.py` の docstring の2章と、`docs/verify/periods-seal.md` の5章「通信するもの」にある。

## 4. 第三者が確かめられること、確かめられないこと

確かめられること。

- 封印の記録の `acquisition-start` の `fetch.code_sha256` と一致する `src/collector/acquire_filelist.py` を、Git の履歴から探せる。その中の `PINNED_SHA256` と、同じコミットの `filelist.py`・`privacy_scan.py` の sha256 を照らせば、取得のコードの3つのファイルが決まる。
- 取得元の URL は `filelist.py` の定数なので、上の sha256 から決まる。
- `acquisition-result` の `kept_rows_sha256` と、マニフェストの行の `sha256` が同じであること。マニフェストの行の `acquisition_start_seq` が、その start の seq であること。
- start と result の時刻の区間（drand の回と、.ots の確定の時刻。`docs/verify/periods-seal.md` の7章）。

確かめられないこと（限界）。

- **ファイル一覧の本体は公開していない。** 第三者は本体を持っていないので、`kept_rows_sha256` が正しい一覧の sha256 であることを確かめるには、自分で取得をやり直すしかない。やり直した場合も、GDELT の一覧はあとで変わりうる（行が足される、直される）ので、同じ sha256 になるとは限らない。同じにならなかったときに、変わったのが GDELT の側か、こちらの側かは分からない。
- 取得した元の一覧に 2020-12-15 以降の行があったか、それをメモリの上で捨てたか、ディスクや画面に一度も出さなかったかは示せない（`docs/verify/periods-seal.md` 7章）。
- このスクリプトを使わずに取得すること、関門の前に取得することは、記録からは検出できない。関門は手順を飛ばす誤りを防ぐもので、証明ではない。
- 封印を公開していないので、別の系列の記録が無いことは示せない（`docs/verify/periods-seal.md` 7章。オーナーが X での公開の前に手順3へ進むと決めた。reviews/T-013.md）。
- 取得のコードの sha256 の範囲に、`src/sealer` の封印の仕組み、Python の処理系、ots のクライアントは入らない。

## 5. テスト（ネットワークを使わない）

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest discover -s tests/collector -v
```

- `tests/collector/test_acquire_filelist.py`：関門（どれか1つが欠ければ止まる）、アダプタの順番と sha256 の照合、本番の経路で差し替えを受け付けないこと。プロジェクトの写しを一時的なディレクトリに作り、その中で封印の記録まで通して動かす（drand と ots は差し替え）。本物の `sealed/`・`data/manifest`・`~/Desktop/news-stick-data` には書かない。
- `tests/collector/test_filelist.py`：取得の本体。子プロセスの見張り（`filelist_child.py`）は、filelist.py を読み込む前に audit hook を入れ、許すイベントの一覧に無いイベントを止める。

## 6. 手順4：手法を作る期間の GKG の取得（T-018 でコードとテスト。実行は別のタスク）

細かい決まりは `gkg.py`・`acquire_gkg.py`・`codegate.py` の docstring にある。ここには実行の手順だけを書く。

実行の前にオーナー（と封印係）がすること
1. 保存先のフォルダを作る：`mkdir ~/Desktop/news-stick-data/gkg-method`（シンボリックリンクにしない。スクリプトは作らない）。
2. 封印係が `src/sealer/seal_method.py seal` で method-access を追記し、コミットする（無ければ関門で止まる）。
3. `src/collector`・`src/sealer` に未コミットの変更・無視されるファイル（`__pycache__` など）・skip-worktree の印が無いこと。
4. 通信の承認：data.gdeltproject.org の `/gdeltv2/<14桁>.gkg.csv.zip` だけ。198,226 本、約 1.79 TB。
5. ディスクの空き：日の集計は全体で 20〜200 GB の見込み（`gkg.py` 6章）。空きが 10 GiB を下回ると止まる。

実行するコマンド（プロジェクトのルートで。引数は受け付けない）

```sh
env -u GIT_DIR -u GIT_WORK_TREE -u PYTHONPATH PYTHONDONTWRITEBYTECODE=1 \
    .venv/bin/python -I -B src/collector/acquire_gkg.py
```

- 終了コード 0：全部の日が終わった。1：関門で止まった（何も書いていない）。3：止まる条件で止まった（同じコードでもう一度実行すると続きから。再開は、手法を作る期間の欠けた日の一覧の封印より前にだけ行う）。
- 書くもの：`~/Desktop/news-stick-data/gkg-method/` の日の集計と取得の記録（Git の外）、`data/manifest/gdelt-gkg-method.jsonl`（Git に入れる）。
- 実行のあと：マニフェストをコミットする。前と後に `privacy_scan.py` と `--all-history` を実行する。ファイルは消さない。

### 6.1 本番の規模に合わせた運用（T-018 の差し戻し1回目）

規模：198,226 本、約 1.79 TB の通信、2,115 日。要求の間隔だけで約55時間、全体で60〜120時間の見込み。

**正式な run は、マニフェストの最初の run-start の run だけである**（`gkg.py` 5章）。最初の数日の測定も、正式な run の始まりとして行う（測定のための別の run は作らない。作るとコードの違う run が二つになり、結果の良い方を選べてしまうため）。コードは、別の run_id の run-start があると新しい run を始めない。

最初の数日で止めて、大きさとメモリを測る手順
1. 上の 6章のコマンドを、`/usr/bin/time -l` を前に付けて実行する（終了のときに最大のメモリ（maximum resident set size）が出る）。
2. `data/manifest/gdelt-gkg-method.jsonl` に day の行が3つ書かれたら、Ctrl-C で止める。止めた日の集計は書かれず、再開のときにその日の ok のファイルを取り直す（`gkg.py` 5章の (b)。failed のファイルは取り直さない）。
3. 測るもの（どれも件数と大きさだけ。中身は見ない）
   - 日の集計の大きさ：`ls -l ~/Desktop/news-stick-data/gkg-method/`（3日の平均 × 2,115 日で全体を見積もる）
   - 最大のメモリ：手順1の表示
   - 1日の組の種類：日の集計を `gzip -dc <名前> | grep -c '^P1'`（P2 も同じ）。MAX_PAIR_KEYS（4千万）との比を見る
4. 見積もりが、保存先の空きと、メモリ（このパソコンは 16 GB）に収まれば、同じコマンドで再開する（終了コード 3 で止まった場合も同じ）。
5. 収まらなければ、再開せずにリードに報告する（下の「次の手」）。

メモリの見込み（データを見ていない見積もり）
- テーマの組1種類あたり約 110 バイト（Counter の項目と tuple）。1日の組の種類を V1・V2 それぞれ 200万〜1,000万と見込み、合わせて 0.4〜2.2 GB。
- そのほか：zip（最大 200 MB）、1ファイル分の集計、テーマ×国（1日 10万〜100万種類、約 0.1 GB）、テーマの名前の一覧。
- 日の集計を書くときは、組を並べ替えた一覧と書き出しの文字列を一時的に作るので、組の部分が最大で約2倍になる。
- まとめ：ふつうの日で 1〜5 GB、上限（組 4千万種類）に近い日で 9〜10 GB。上限を超えた日は、書かずに止まる。

止まったときの次の手（どれもファイルを削除しない）
- **ディスクの空きが 10 GiB を下回った**（終了コード 3。日の集計は書かない）：
  1. 他の作業をせず、リードに報告する。手元のファイルは消さない。
  2. オーナーの決定（集計は 1TB の外付けディスクに置ける）のとおり、保存先を外付けディスクに変える。これは保存先の定数を変えるコードの変更なので、別のタスクにする。正式な run の始まった後なら、run_id が変わるので、続け方（規則の変更を含む）をオーナーが決める。
  3. 既にある日の集計と取得の記録は、新しい保存先に写す（消さない）。写した先の sha256 がマニフェストと同じことを確かめる。
- **1日の組の種類が上限を超えた**（終了コード 3）：
  1. 再開しない（同じ日でまた止まる）。リードに報告する。
  2. 集計の形を見直す案（組を週ごとにまとめる、P2 をやめるなど）は、コードの変更なので別のタスクにする。正式な run との関係は、上と同じくオーナーが決める。
- **一時的な失敗が続いた**（終了コード 3）：通信が戻ってから、同じコマンドで再開する。続いた失敗のファイルを取り直すのは run の中で1回だけで、2回目以降は failed で確定する（`gkg.py` 5章）。
- **形式の失敗が続いた**（終了コード 3）：コードとデータの形が合っていない。再開せずにリードに報告する。

## 7. テスト（手順4・区分表・関門。ネットワークを使わない）

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest discover -s tests/collector -v
```

- `tests/collector/test_gkg.py`：欄を捨てること（目印を入れた欄がどのファイルとログにも出ない）、集計、DATA_START より前の除外、区画の後ろの時刻の行を数えずに捨てること、欠けたファイルの記録、再試行の上限、止まる条件と再開の規則、正式な run の規則、一時ファイルを作らないこと。`TestChildGuard` は、取得と集計を子プロセス（`gkg_child.py`）で audit hook の見張りの下で動かし、保存先の決まったファイルの外への書き込み（生の zip を外へ書く変異など）を捕まえる。
- `tests/collector/test_acquire_gkg.py`：最初に引数なしの関門を呼ぶこと、写しの上で手順3と method-access を作ってからの通しの動き、関門の各条件。
- `tests/collector/test_themes.py`：区分表の件数の欄を捨てること、見出しの無い形で止まること、1回だけの取得。
- `tests/collector/test_acquire_filelist.py` の `TestGateHardening`：T-015 の監査 軽1・軽2・軽5 の対応。
