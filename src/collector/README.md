# 収集係のコード（src/collector）：試運転の手順3・手順4 の取得の手順書（T-015、T-018、T-021）

データ出典：GDELT Project（https://www.gdeltproject.org/）。本プロジェクトは GDELT Project と提携・承認の関係にありません。
Data: The GDELT Project (https://www.gdeltproject.org/). This project is not affiliated with or endorsed by the GDELT Project.

| ファイル | 役割 |
|---|---|
| `acquire_filelist.py` | 手順3の入口のスクリプト。関門、封印の仕組みにつなぐアダプタ、取得のコードの sha256 の固定 |
| `filelist.py` | 一覧の取得、2020-12-15 以降の行の破棄、項目の絞り込み、保存、マニフェストの追記。ファイルの日の規則（4章）は gkg.py も使う |
| `codegate.py` | 入口のスクリプトが共通に使う関門の部品（git を環境変数なしで動かす、未コミット・無視されるファイル・skip-worktree の検査、sealed/・data/manifest のリンクの検査）。T-018 |
| `acquire_gkg.py` | 手順4の入口のスクリプト。最初に除外の規則の封印の関門（`themes.require_exclusion_rules_sealed()`。区分表の取得と同じ）を通し、次に `ledger.require_method_access()` を引数なしで呼び、関門のあとで gkg.py を動かす。`--trial` で試しの run。T-018・T-021。まだ実行していない |
| `gkg.py` | 手法を作る期間の GKG 2.1 の取得、メモリの上での欄の破棄と集計、日ごとの集計の保存（外付けディスク LACIE SHARE。FAT32）、取得の記録とマニフェスト、試しの run。T-018・T-021 |
| `themes.py` | テーマの区分表の取得（件数の欄を捨てる）。取得元は `https://data.gdeltproject.org/api/v2/guides/LOOKUP-GKGTHEMES.TXT` だけ（T-021）。除外の規則の封印の記録が無ければ通信の前に止まる（その記録の種類は封印係の側で未定なので、今は必ず止まる）。コミットしたコードでだけ動き、取得の試みは1回だけ（マニフェストに試行の行）。見出しの無い「名前・件数」の2欄なら名前の欄だけを残す（8章）。コードだけで、まだ取得していない |
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

## 6. 手順4：手法を作る期間の GKG の取得（T-018・T-021 でコードとテスト。実行は別のタスク）

細かい決まりは `gkg.py`・`acquire_gkg.py`・`codegate.py` の docstring にある（保存先は `gkg.py` 7章、FAT32 は 8章、試しの run は 5.1章）。ここには実行の手順だけを書く。

### 6.1 保存先（T-021。オーナーの決定「LACIE SHARE を保存先にしよう」）

| 何 | 場所 | Git |
|---|---|---|
| 正式な run の日の集計と取得の記録 | `/Volumes/LACIE SHARE/news-stick-data/gkg-method/` | 入れない |
| 試しの run の日の集計と取得の記録 | `/Volumes/LACIE SHARE/news-stick-data/gkg-trial/` | 入れない |
| 正式な run のマニフェスト | `data/manifest/gdelt-gkg-method.jsonl` | 入れる |
| 試しの run のマニフェスト | `data/manifest/gdelt-gkg-trial.jsonl` | 入れる |
| ファイル一覧の本体（手順3。変わらない） | `~/Desktop/news-stick-data/gdelt-filelist/` | 入れない |

- 保存先は、外付けディスク LaCie の FAT32 の区画「LACIE SHARE」に固定した（`gkg.VOLUME_MOUNT`）。同じディスクの NTFS の区画「LaCie」は、Mac からは読むことしかできないので使わない。
- **取得の記録は、日の集計と同じフォルダ（外付けディスク）に置く。** 理由：再開の規則は取得の記録と日の集計の両方を読むので、同じディスクにあれば、ディスクが無いときは両方とも無く、片方だけを見て再開することが起きない。一つの run の成果が一つのフォルダにまとまる。手元のデスクトップは iCloud に送られることがある。代償：ディスクが壊れると両方を一緒に失う（日の集計の sha256 はマニフェストに残る）。
- マニフェストの `store_location` には、絶対パスやユーザー名を書かず、`LACIE SHARE:/news-stick-data/gkg-method`（試しの run は `…/gkg-trial`）と書く。
- 保存先のフォルダには、macOS が書いたファイルごとに「`._`」で始まる付属のファイル（拡張属性）を作る。スクリプトが書くものではない。消さない。

### 6.2 オーナーが前もって作るフォルダ（スクリプトはフォルダを作らない）

ディスク「LACIE SHARE」をつないだ状態で、次の3つを作る。

```sh
mkdir "/Volumes/LACIE SHARE/news-stick-data"
mkdir "/Volumes/LACIE SHARE/news-stick-data/gkg-trial"
mkdir "/Volumes/LACIE SHARE/news-stick-data/gkg-method"
```

- 名前は上のとおり、すべて小文字にする。FAT32 は大文字と小文字を区別しないが、スクリプトはフォルダの一覧で名前が完全に同じことを確かめる（`GKG-Method` などでは止まる）。
- シンボリックリンクにしない。中身は空でよい。
- 実行のあいだ、ディスクを取り出さない。外れる・スリープで切れる・読み取り専用になると、書かずに止まる（終了コード 3）。つなぎ直して、同じコマンドで再開する。

### 6.3 実行の前に（オーナーと封印係）

1. 6.2 のフォルダを作る。
2. 封印係が `src/sealer/seal_method.py seal` で method-access を追記し、コミットする（無ければ関門で止まる）。
3. `src/collector`・`src/sealer` に未コミットの変更・無視されるファイル（`__pycache__` など）・skip-worktree の印が無いこと。
4. 通信の承認：data.gdeltproject.org の `/gdeltv2/<14桁>.gkg.csv.zip` だけ。正式な run は 198,226 本、約 1.79 TB。試しの run は 3日分（約 288 本、約 2.6 GB の見込み）。
5. ディスクの空き：日の集計は全体で 20〜200 GB の見込み（`gkg.py` 6章）。LACIE SHARE の空きは約 372 GB（2026-10-08）。空きが 10 GiB を下回ると止まる。

### 6.4 試しの run（正式な run の前に、最初の数日の大きさとメモリを測る）

```sh
/usr/bin/time -l env -u GIT_DIR -u GIT_WORK_TREE -u PYTHONPATH PYTHONDONTWRITEBYTECODE=1 \
    .venv/bin/python -I -B src/collector/acquire_gkg.py --trial
```

- 取る日は `gkg.TRIAL_DAYS`（2015-03-02・03・04 の3日）に固定。上限は3日で、手法を作る期間の最初の3日だけ。ほかの日は取れない。
- 書くもの：`/Volumes/LACIE SHARE/news-stick-data/gkg-trial/` と `data/manifest/gdelt-gkg-trial.jsonl`（行に `official: false`、`trial: true`）。
- **正式な run の判定には数えない。** 正式な run のマニフェスト（`gdelt-gkg-method.jsonl`）には何も書かない。正式な run の run-start がある場合は、試しの run は始まらない（試しの run は正式な run の前にだけ）。
- 正式な run は、試しの run の3日も含めて全部の日を取り直す。試しの run の集計は、正式な run の結果に使わない。
- 終了コード 0：3日が終わった。1：関門。3：止まる条件（同じコマンドで再開）。
- 測るもの（どれも件数と大きさだけ。テーマごとの報道量などの中身は見ない）
  - 日の集計の大きさ：`stat -f '%z %N' "/Volumes/LACIE SHARE/news-stick-data/gkg-trial/"gkg-trial-*-day-*`（バイト数と名前だけが出る。`ls -l` は所有者のユーザー名も出すので使わない）。3日の平均 × 2,115 日で全体を見積もる
  - 記録（reviews/ や報告）に写すのは、大きさ・メモリ・組の種類の**数字だけ**とする。パス・ユーザー名・コマンドの出力そのものは写さない
  - 最大のメモリ：`/usr/bin/time -l` の maximum resident set size
  - 1日の組の種類：`gzip -dc <日の集計> | grep -c '^P1'`（P2 も同じ）。`MAX_PAIR_KEYS`（4千万）との比
- 終わったら、`data/manifest/gdelt-gkg-trial.jsonl` をコミットする（前と後に privacy_scan。6.5 の手順2と同じ）。試しの run のファイルは消さない。
- 限界：2015年3月の最初の3日は、のちの年より文書が少ない可能性がある。その場合、3日の平均からの見積もりは小さく出る。正式な run でも、空きが 10 GiB を下回ったとき・組の種類が上限を超えたときに止まる仕組みは残る。

**試しの run の結果を使って規則を変えることはあり得る。** 大きさかメモリが収まらない場合、集計の形（組を週ごとにまとめる、P2 をやめる、上限の値など）を変える必要が出る。その扱い：

1. 試しの run を理由に変えてよいのは、集計の形・上限・保存の仕方など、大きさとメモリに関わるものだけ。タグの規則・除外の規則・閾値・信号の定義は、試しの run を理由に変えない。
2. 変える根拠にしてよいのは、上の「測るもの」（大きさ・メモリ・組の種類の数）だけ。日の集計の中身（テーマごとの数）は見ない。
3. 変えるかどうかはリードとオーナーが決め、別のタスクで、正式な run の run-start より前に行う。理由と、試しの run の測定の数字をタスクの記録（reviews/）に残す。
4. コードを変えると run_id が変わる。測り直す場合は、新しい run_id の試しの run を同じ3日で行う。前の試しの run のマニフェストの行とファイルは残す（消さない）。
5. 正式な run の run-start のあとは、試しの run はできない（コードで止まる）。正式な run の途中で形を変える場合は、6.7 の「次の手」のとおり、続け方をオーナーが決める。

### 6.4.1 試しの run と正式な run の区別（T-021 の差し戻し1回目 中2・中4）

- 日の集計と取得の記録の名前に mode を入れる：`gkg-trial-<run_id>-day-<日>.tsv.gz`、`gkg-official-<run_id>-fetch-log.jsonl` など。日の集計の頭の行、取得の記録の各行、マニフェストの各行にも `mode` を書く。取得の記録に別の mode か別の run_id の行があれば止まる（試しの run の記録を写しても、正式な run には引き継がれない）。
- 正式な run は、`data/manifest/gdelt-gkg-trial.jsonl` が**全部コミットされていなければ始まらない**（試しの run をしていなければ、無いままでよい）。正式な run の run-start には、試しの run の run_id の一覧（`trial_run_ids`）とマニフェストの sha256（`trial_manifest_sha256`）を書き、再開のたびに照らす。

### 6.5 正式な run

```sh
env -u GIT_DIR -u GIT_WORK_TREE -u PYTHONPATH PYTHONDONTWRITEBYTECODE=1 \
    .venv/bin/python -I -B src/collector/acquire_gkg.py
```

1. **1回目は、run-start を書いたところで止まる（終了コード 4）。** GKG にはまだ一度も要求を送っていない。
2. **すぐに run-start をコミットする。リモートがあれば push もする**（T-018 の監査 軽2。正式な run の始まりを、データを1本も受け取る前に Git の履歴に入れるため）。作成者は noreply（CLAUDE.md）。2026-10-08 の時点で、このリポジトリにはリモートが無い。そのため、コミットを消して（`git reset` など）別の run を正式にすることは、手元の履歴だけからは見分けられない。封印の記録への追記（OpenTimestamps）で固める案を、封印係への提案として T-021 の報告に書いた。
   ```sh
   python3 -B src/collector/privacy_scan.py
   git add data/manifest/gdelt-gkg-method.jsonl
   git commit -m "GKG の正式な run の run-start"
   python3 -B src/collector/privacy_scan.py
   python3 -B src/collector/privacy_scan.py --all-history
   git push    # リモートがある場合だけ
   ```
3. 同じコマンドをもう一度実行する。関門が、HEAD のマニフェストに最初の run-start があること、作業ツリーのマニフェストが HEAD のマニフェストで始まる（コミットした行を書き換えていない）ことを確かめてから、取得を始める。コミットしていなければ、要求を送らずに止まる。
4. 終了コード 0：全部の日が終わった。1：関門で止まった（何も書いていない）、または規則の検査で止まった（run-start のコミットが無い場合は、要求を送らず、何も書かずに止まる）。3：止まる条件で止まった（同じコマンドで続きから。再開は、手法を作る期間の欠けた日の一覧の封印より前にだけ行う）。
5. 終わったら（途中で長く止める場合も）、マニフェストをコミットする（手順2と同じ形）。日の集計と取得の記録（外付けディスク）はコミットしない。ファイルは消さない。

正式な run の規則（`gkg.py` 5章・5.2章）
- 最初に、除外の規則の封印の関門を通す（試しの run も同じ。T-021 の差し戻し1回目 重1）。**封印係の kind が決まるまでは、ここで必ず止まる（GKG も取得しない）。**
- 取得の記録の大きさと sha256 を、マニフェストの run-start・run-resume・day・run-stop・run-complete の行に控える。再開のときに、取得の記録の先頭がその控えと一致しなければ止まる（行を消して取り直させる書き換えを見つける。中1）。控えのあとに書いた行（停電で run-stop を書けなかったときの、最後の day の行より後）は確かめられない。
- diskutil で読んだディスクの VolumeUUID を run-start に書き、再開のたびに照らす。形式が msdos でなければ関門で止まる（軽3）。
- 日の集計のファイルが0バイトで残っていれば（作った直後に止まった跡）、消さずにそこへ書き足し、day の行に `refilled_empty_file: true` を書く。中身のある違うファイルなら止まる（軽3）。
- 正式な run は、`gdelt-gkg-method.jsonl` の最初の run-start の run だけ。別の run_id の run-start があると、新しい run は始めない。
- 試行の回数は、止まって再開しても引き継ぐ（T-018 の監査 軽1）。要求を送る直前に、毎回取得の記録に `attempt` の行を書く。再試行を待っているあいだに止めても、回数は戻らない。
- 封印の記録（OpenTimestamps）への run-start の追記は、封印係の範囲なので、このスクリプトはしない（T-021 の報告で提案した）。

### 6.6 本番の規模とメモリ

規模：198,226 本、約 1.79 TB の通信、2,115 日。要求の間隔だけで約55時間、全体で60〜120時間の見込み。試行の行を書くたびに外付けディスクで fsync するので、その分も少し延びる。

メモリの見込み（データを見ていない見積もり。試しの run で測る）
- テーマの組1種類あたり約 110 バイト（Counter の項目と tuple）。1日の組の種類を V1・V2 それぞれ 200万〜1,000万と見込み、合わせて 0.4〜2.2 GB。
- そのほか：zip（最大 200 MB）、1ファイル分の集計、テーマ×国（1日 10万〜100万種類、約 0.1 GB）、テーマの名前の一覧。
- 日の集計を書くときは、組を並べ替えた一覧と書き出しの文字列を一時的に作るので、組の部分が最大で約2倍になる。
- まとめ：ふつうの日で 1〜5 GB、上限（組 4千万種類）に近い日で 9〜10 GB。上限を超えた日は、書かずに止まる。

### 6.7 止まったときの次の手（どれもファイルを削除しない）

- **ディスクが外れた・読み取り専用になった・保存先のフォルダが変わった**（終了コード 3。書かずに止まる）：ディスクをつなぎ直し、`mount` で `/Volumes/LACIE SHARE` が msdos で読み書きできることを確かめてから、同じコマンドで再開する。マウント先の名前が `LACIE SHARE 1` などに変わった場合は、その名前では動かない（止まる）。ディスクを取り出してつなぎ直す。
- **書いている途中でディスクが外れた**：取得の記録の最後の行が途中で切れていると、再開のときに「最後の行に改行が無い」で止まる。日の集計が0バイトなら、再開のときに書き足す（上の規則）。中身が途中まで書かれていると「同じ名前で中身の違うファイル」で止まる。止まった場合はリードに報告する（直し方はリードが決める。ファイルは消さない）。
- **取得の記録が控えと合わない**（終了コード 1）：run と run のあいだに取得の記録が書き換わった。再開しない。リードに報告する。
- **ディスクの空きが 10 GiB を下回った**（終了コード 3）：他の作業をせず、リードに報告する。保存先を変えるのはコードの変更なので、別のタスクにする。正式な run の始まった後なら、続け方をオーナーが決める。既にある日の集計と取得の記録は、新しい保存先に写し（消さない）、sha256 がマニフェストと同じことを確かめる。
- **1つのファイルが FAT32 の上限（4 GiB − 1 バイト）を超える**（終了コード 3）：再開しない（同じところでまた止まる）。リードに報告する。
- **1日の組の種類が上限を超えた**（終了コード 3）：再開しない。リードに報告する。集計の形を見直す案（組を週ごとにまとめる、P2 をやめるなど）は別のタスク。
- **一時的な失敗が続いた**（終了コード 3）：通信が戻ってから、同じコマンドで再開する。続いた失敗のファイルを取り直すのは run の中で1回だけで、2回目以降は failed で確定する（`gkg.py` 5章）。
- **形式の失敗が続いた**（終了コード 3）：コードとデータの形が合っていない。再開せずにリードに報告する。

## 7. テスト（手順4・区分表・関門。ネットワークを使わない）

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest discover -s tests/collector -v
```

- `tests/collector/test_gkg.py`：欄を捨てること（目印を入れた欄がどのファイルとログにも出ない）、集計、DATA_START より前の除外、区画の後ろの時刻の行を数えずに捨てること、欠けたファイルの記録、再試行の上限、止まる条件と再開の規則、正式な run の規則、一時ファイルを作らないこと。T-021：保存先のディスクの検査（`TestVolume`。マウントされていない・つながっていない・リンク・読み取り専用）、書く前の検査（`TestStoreGuard`。途中で外れる・フォルダが替わる・別のディスク・大文字と小文字・FAT32 の1ファイルの上限）、試行の記録と回数の引き継ぎ（`TestAttempts`）、run-start のコミット（`TestRunStartCommit`）、試しの run（`TestTrial`）。`TestChildGuard` は、取得と集計を子プロセス（`gkg_child.py`）で audit hook の見張りの下で動かし、保存先の決まったファイルの外への書き込みを捕まえる。
- `tests/collector/test_acquire_gkg.py`：最初に引数なしの関門を呼ぶこと、写しの上で手順3と method-access を作ってからの通しの動き、関門の各条件（保存先のディスク・試しの run の保存先を含む）、run-start のコミットの関門、試しの run、引数（`--trial` だけ）と終了コード。
- `tests/collector/test_themes.py`：区分表の件数の欄を捨てること、見出しの無い形で止まること、1回だけの取得。T-021：取得元は `/api/v2/guides/LOOKUP-GKGTHEMES.TXT` の1つだけ、除外の規則の封印の関門（`TestExclusionGate`）、Unicode の数字・上付きの数字・シート名・見出しの数字。差し戻し1回目：コードの関門（`TestCodeGate`）、試行の行と2回目の拒否（`test_only_one_attempt_ever`）、見出しの無い2欄の規則（`TestHeaderlessRule`、`test_headerless_name_and_count`）。
- 差し戻し1回目の GKG 側：`test_gkg.py` の `TestLogCheckpoint`（中1）、`TestModeMarks`（中2）、`TestTrialRecordInOfficial`（中4）、`TestVolumeIdAndEmptyFile`（軽3）。`test_acquire_gkg.py` の `TestExclusionGateFirst`（重1）、`TestVolumeIdentity`（軽3）、`test_main_modes`（引用の全文）。
- `tests/collector/test_acquire_filelist.py` の `TestGateHardening`：T-015 の監査 軽1・軽2・軽5 の対応。
- テストは、本物の `/Volumes/LACIE SHARE` を使わない。保存先のディスクは一時的なディレクトリで置き換え、マウントの検査だけを差し替える（本物の検査は `TestVolume` と、下の FAT32 のテストで確かめる）。

### 7.1 FAT32 のイメージの上でのテスト（T-021）

LACIE SHARE と同じ形式のイメージを作業用の場所（例：scratchpad）に作ってマウントし、その上で書き込みと関門のテストを動かす。**本物の `/Volumes/LACIE SHARE` を渡してはいけない**（テストは `/Volumes` の下を渡されると止まる。msdos でないマウント先でも止まる）。

```sh
SP=<作業用の場所>
hdiutil create -size 300m -fs "MS-DOS FAT32" -volname LACIETEST -layout NONE "$SP/fat32-t021.dmg"
mkdir -p "$SP/fatmnt/LACIE SHARE"
hdiutil attach -nobrowse -mountpoint "$SP/fatmnt/LACIE SHARE" "$SP/fat32-t021.dmg"
TMPDIR="$SP" GKG_FAT32_TEST_VOLUME="$SP/fatmnt/LACIE SHARE" PYTHONDONTWRITEBYTECODE=1 \
    python3 -B -m unittest -v tests.collector.test_gkg.TestOnFat32 \
    tests.collector.test_acquire_gkg.TestEndToEndOnFat32
hdiutil detach "$SP/fatmnt/LACIE SHARE"
```

- `TMPDIR` をイメージのある場所にするのは、テストの差し替えが一時的なディレクトリの下しか指せないため。
- 読み取り専用の検査：別のイメージを `hdiutil attach -readonly -nobrowse -mountpoint <場所> <イメージ>` でマウントし、`GKG_FAT32_TEST_VOLUME_RO=<場所>` を付けて `tests.collector.test_gkg.TestOnFat32ReadOnly` を動かす。
- 確かめること（`gkg.py` 8章）：シンボリックリンク（msdos のドライバが作る印のリンク）を保存先・取得の記録の場所に置くと止まること、大文字と小文字だけが違うフォルダの名前で止まること、大文字と小文字だけが違うファイルの名前で上書きしないこと、保存先のフォルダの (st_dev, st_ino) が書き込みのあいだ変わらないこと、試しの run と正式な run を通しで動かして sha256 がマニフェストと一致すること、試行の回数の引き継ぎ。
- テストはイメージの直下に `news-stick-data` を作り、終わると消す（イメージの中だけ）。既にあれば、何もせずに失敗する。

## 8. 区分表の取得（themes.py。T-021。実行は別のタスク）

- 取得元は `https://data.gdeltproject.org/api/v2/guides/LOOKUP-GKGTHEMES.TXT` だけ。オーナーの承認は「件数の欄を捨てる条件で、1回取得してよい」。
- 通信の前に、順に：除外の規則の封印の関門（kind は未定なので今は必ず止まる）、コードの関門（`src/collector` に未コミットの変更が無く、動いている themes.py が HEAD と同じ）、保存先の確認、**1回だけの確認**（`data/manifest/gdelt-themes.jsonl` に行が1つでもあれば止まる）。そのあと試行の行（`kind: attempt`、`code_sha256`）を書いてから通信する。失敗しても試行の行は残り、2回目はできない。取得のあとすぐにマニフェストをコミットする。
- **見出しの無い「名前・件数」の2欄の表**（リードの判断。監査の条件 (1)〜(4)）：1行目に数字だけの値があるとき、どの行も欄がちょうど2つで、一方の欄の値がすべてテーマの名前の形、もう一方がすべて ASCII の数字だけ、という割り当てがちょうど1つに決まる場合に限り、名前の欄だけを残す。判定は欄の位置ではなく値の形で行う。両方の割り当てが合う場合、どちらも合わない場合は止まる。件数の欄はメモリの上で捨て、行を並べ替えてから書く。マニフェストに `headerless: true` と、捨てた欄の位置（`column_A` か `column_B`）を書く。この規則は取得の前にコミットし、試行の行の `code_sha256` で固定する。
- **限界**：区分表は取得した時点の全テーマの一覧なので、2020-12-15 以降に生まれたテーマの名前も入る。名前があることは、そのテーマが後ろの期間に使われたことを示しうる。タグの一覧の規則は、手法を作る期間のデータでテーマの存在を確かめるので、名前だけでは一覧に入らない。
