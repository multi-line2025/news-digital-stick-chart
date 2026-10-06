# 収集係のコード（src/collector）：試運転の手順3 ファイル一覧の取得の手順書（T-015）

データ出典：GDELT Project（https://www.gdeltproject.org/）。本プロジェクトは GDELT Project と提携・承認の関係にありません。
Data: The GDELT Project (https://www.gdeltproject.org/).

| ファイル | 役割 |
|---|---|
| `acquire_filelist.py` | 入口のスクリプト。関門、封印の仕組みにつなぐアダプタ、取得のコードの sha256 の固定 |
| `filelist.py` | 一覧の取得、2020-12-15 以降の行の破棄、項目の絞り込み、保存、マニフェストの追記 |
| `privacy_scan.py` | メールアドレスの形の文字列の検査（filelist.py が書く前に使う。コミットの前と後にも実行する） |

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

1. 関門（ネットワークを使わない）。次の4つのどれかが欠ければ、何も書かずに終了コード 1 で止まる。
   - periods と candidates の記録があり、記録の鎖と .ots が検証に通る
   - 区切りの封印（periods）の時刻証明が Bitcoin で確定している
   - 保存先の2段のフォルダがある
   - 取得のコードに未コミットの変更が無い。filelist.py と privacy_scan.py の sha256 が、入口のスクリプトに固定した値と一致する
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
