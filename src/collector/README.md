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
- **2つのフォルダ（gkg-trial・gkg-method）には、スクリプトが書くもののほかに何も置かない。** スクリプトは毎回フォルダの一覧を照らし、決まった名前のファイルと、その名前に「._」を付けた macOS の付属のファイルのほかに何かあれば止まる（「.」で始まるほかの名前・フォルダ・リンクを含む）。Finder でこの2つのフォルダを開くと `.DS_Store` ができて止まるので、開かない（できてしまったら、消さずにリードに報告する）。
- 実行のあいだ、ディスクを取り出さない。外れる・スリープで切れる・読み取り専用になると、書かずに止まる（終了コード 3）。つなぎ直して、同じコマンドで再開する。

### 6.3 実行の前に（オーナーと封印係）

1. 6.2 のフォルダを作る。
2. 封印係が `src/sealer/seal_method.py seal` で method-access を追記し、コミットする（無ければ関門で止まる）。
3. `src/collector`・`src/sealer` に未コミットの変更・無視されるファイル（`__pycache__` など）・skip-worktree の印が無いこと。
4. 通信の承認：data.gdeltproject.org の `/gdeltv2/<14桁>.gkg.csv.zip` と、run の開始を封印の記録に書くための drand と OpenTimestamps のカレンダー（3章の表と同じ宛先。6.5.5。T-032）。GKG は正式な run は 198,226 本、約 1.79 TB。試しの run は 3日分（約 288 本、約 2.6 GB の見込み）。
5. ディスクの空き：日の集計は全体で 20〜200 GB の見込み（`gkg.py` 6章）。LACIE SHARE の空きは約 372 GB（2026-10-08）。空きが 10 GiB を下回ると止まる。

### 6.4 試しの run（正式な run の前に、最初の数日の大きさとメモリを測る）

```sh
/usr/bin/time -l env -u GIT_DIR -u GIT_WORK_TREE -u PYTHONPATH PYTHONDONTWRITEBYTECODE=1 \
    .venv/bin/python -I -B src/collector/acquire_gkg.py --trial
```

- 取る日は `gkg.TRIAL_DAYS`（2015-03-02・03・04 の3日）に固定。上限は3日で、手法を作る期間の最初の3日だけ。ほかの日は取れない。
- 書くもの：`/Volumes/LACIE SHARE/news-stick-data/gkg-trial/` と `data/manifest/gdelt-gkg-trial.jsonl`（行に `official: false`、`trial: true`）。
- 要求を送る前に、封印の記録に `gkg-run-start`（mode が trial）を1件書く（6.5.5）。2回目以降の試しの run も同じく記録に残るので、何回試したか（異なる run_id の数）は封印の記録から数えられる。
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

### 6.4.1 試しの run と正式な run の区別（T-021 の差し戻し1回目・2回目）

- 日の集計と取得の記録の名前に mode を入れる：`gkg-trial-<run_id>-day-<日>.tsv.gz`、`gkg-official-<run_id>-fetch-log.jsonl` など。日の集計の頭の行、取得の記録の各行、マニフェストの各行にも `mode` を書く。取得の記録に別の mode か別の run_id の行があれば止まる。
- mode の印は行の中の文字なので、書き換えれば合わせられる。試しの run の記録の mode を書き換えて正式な run の場所に置くことを止めるのは、取得の記録の控え（`gkg.py` 5.2章）である。正式な run の run-start のあとは、取得の記録の大きさが控え（0バイト）とちょうど同じでなければならないので、置いた記録で止まる。
- 正式な run は、`data/manifest/gdelt-gkg-trial.jsonl` が**全部コミットされていなければ始まらない**（試しの run をしていなければ、無いままでよい）。正式な run の run-start には、試しの run の run_id の一覧（`trial_run_ids`）とマニフェストの sha256（`trial_manifest_sha256`）を書き、再開のたびに照らす。
- 正式な run の run-start の前と再開のたびに、`gkg-trial` のフォルダを一覧する。試しの run の決まった名前のファイルと、その名前に「._」を付けたもののほかに何かあれば止まる（「.」で付け直した名前・「.」で始まるフォルダを含む）。フォルダにある run_id がすべて試しの run のマニフェストに載っていて、逆にマニフェストに載っているすべての run の取得の記録が、フォルダにあって最後の控えと同じでなければ止まる（中-C・差し戻し3回目 中-2）。止めないもの：試しの run のファイルを全部フォルダの外へ移し、コミットの前にマニフェストの行も消すこと（6.5.2）。

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

正式な run の規則（`gkg.py` 5章・5.2章・5.3章・5.4章）
- 最初に、除外の規則の封印の関門を通す（試しの run も同じ）。**封印係の kind が決まるまでは、ここで必ず止まる（GKG も取得しない）。**
- 正式な run は、`gdelt-gkg-method.jsonl` の最初の run-start の run だけ。別の run_id の run-start があると、新しい run は始めない。
- **正式な run は、再開のたびに、マニフェストが全部コミットされていることを求める。** 止まるたびに、手順2の形でマニフェストをコミットしてから再開する。
- 試行の回数は、止まって再開しても引き継ぐ。要求を送る直前に、毎回取得の記録に `attempt` の行を書く。
- 日の集計のファイルが0バイトで残っていれば（作った直後に止まった跡）、消さずにそこへ書き足し、day の行に `refilled_empty_file: true` を書く。中身のある違うファイルなら止まる。
- 封印の記録（OpenTimestamps）への run-start の追記は、封印係の範囲なので、このスクリプトはしない。

#### 6.5.1 主な防御：day の行の failed のファイルの一覧（第三者が GDELT と照らせる）

リードの方針（T-021 の差し戻し3回目）：運営側の手元のディスクの上のファイルは、運営側がいつでも書き換えられる。手元の検査だけで、すべての書き換えを防ぐことはできない。そこで、取れなかったファイルの一覧を Git に入るマニフェストに書き、第三者が GDELT と照らせるようにする。

- day の行（`data/manifest/gdelt-gkg-method.jsonl`）に、その日の failed のファイルの一覧 `failed_files` を書く。各項目は `file_time`・`reason`・`attempts`（規則で数えた試行の回数）・`requests_sent`（実際に送った要求の数。取得の記録の attempt の行の数）・`listed_size`・`listed_md5`（ファイル一覧の値。GDELT が公開している値）。数は `files_failed` と同じ。day の行には、その日に実際に送った要求の総数 `requests_sent` も書く。
- **第三者が確かめる手順**（T-026 で直した）
  1. 封印の記録の acquisition-result の `kept_rows_sha256` と同じ sha256 のファイル一覧（手順3の本体）を用意する。本体は公開していないので、自分で `https://data.gdeltproject.org/gdeltv2/masterfilelist.txt` を取って作り直す（T-026 で直した）。作り直し方は、取得のときと同じ固定のコード（`src/collector/filelist.py`）の関数を、この順に使う。
     - 取った一覧の本体を、**文字に直さずバイト列（bytes）のまま** 行に分ける（`本体.split(b"\n")` だけを使う。T-030 軽-B・T-032。取得のときの経路は改行（`\n`）でだけ行を分けるので、`splitlines` は単独の `\r` などでも分けてしまい、合わなくなる）。以下の関数は行をバイト列で受け取る。文字列（str）で渡すと、どの行も残らない（0件になる）。
     - 元の一覧の各行（バイト列）について `filelist._is_kept_line(行)` が真の行だけを残す（ファイル名の14桁の時刻を `LAST_KEPT_TIME`＝2020-12-14 23:45:00 と比べ、それより後の行と、時刻を読めない行を捨てる。4章のファイルの日の規則）。
     - 残した各行を `filelist.parse_kept_line(行)` で (file_time, file_type, size_bytes, md5) にし、None（形の合わない行）を除く。
     - `filelist.serialize_rows(行の一覧)` で、見出しつき・並べ替え済みのバイト列にする（5章の形）。
     - そのバイト列の sha256 を `kept_rows_sha256` と比べる。GDELT の一覧はあとで変わりうるので、合うとは限らない（README 4章）。
  2. マニフェストの正式な run（最初の run-start の run_id）の day の行ごとに、次を確かめる。
     - `files_listed` が、手順1のバイト列の gkg の行のうち、ファイルの日（`gkg.py` 1章の規則。2015-03-02 より前は入れない）がその日のものの、**異なる file_time の数** と同じこと（同じ file_time の行が二つ以上あれば1本と数える。`gkg.select_files` と同じ数え方）。
     - `files_ok` と `files_failed` の和が `files_listed` と同じこと。
     - `failed_files` の数が `files_failed` と同じこと。
     - 各項目の `requests_sent`（実際に送った要求の数）と `attempts`（規則で数えた試行の回数）を照らす（T-026 軽-5）。正直な運用では `requests_sent` は `attempts` 以上である（多いのは、止めて再開した・1回だけの取り直しをした跡）。`requests_sent` が `attempts` より少ない項目と、`reason` が `ambiguous_listing`（要求を送らない）でないのに `requests_sent` が 0 の項目は、取得の記録と合わない（手元で作られた行の疑い）。
  3. `failed_files` の各項目について、`https://data.gdeltproject.org/gdeltv2/<file_time>.gkg.csv.zip` を取得し、大きさと md5 が `listed_size`・`listed_md5` と合うかを見る（この2つは day の行にあるので、一覧の本体が無くても照らせる）。合えば、そのファイルは今は取れる。見方は `reason` によって3つに分かれる（T-026 中-1）。

     | 分け方 | reason | 今は合うファイルが取れるときの見方 | 確かめ方 |
     |---|---|---|---|
     | 取れなかった（一覧の値と合うファイルを受け取れなかった） | `http_404`・`http_403`・`http_410`、そのほかの `http_<3桁>`（再試行しない値。3xx はリダイレクトを追わないので取れなかった扱い、501 なども含む）、`http_None`（状態の番号の無い応答）、`size_mismatch`・`md5_mismatch`（3回受け取っても一覧の値と合わなかった） | 取得のときに本当に取れなかったのかを疑う理由になる。ただし、GDELT があとでファイルを置いた・直した可能性もある | URL を取り、状態の番号・リダイレクトの有無・大きさと md5 を見る |
     | 取れたが、このプロジェクトの規則で落とした | `too_large`（受け取った zip が `MAX_ZIP_BYTES`＝2億バイトを超えた。下の確かめ方の2つの場合を見る）、`format_…`（md5 は合ったが、zip や行の形が規則に合わなかった。`format_too_large_unzipped` は展開後の上限）、`content_encoding`（応答が圧縮の指定つきで返った）、`ambiguous_listing`（一覧に同じ file_time の違う行があったので、要求を送らなかった） | 今取れることは反証にならない（正直な失敗でも今は取れる）。規則に当たるかを確かめる | `too_large`（T-030 軽-C）：(i) `listed_size` が `MAX_ZIP_BYTES` を超えるなら、一覧どおりの大きさのファイルは必ずこの規則で落ちるので、規則のとおり。(ii) `listed_size` が `MAX_ZIP_BYTES` 以下なら、一覧より大きいものを受け取ったという意味なので、「取れなかった」の行と同じに扱い、今取れるファイルの大きさと md5 を一覧の値と比べる（合うものが今取れるなら、取得のときに本当に大きすぎたのかを疑う理由になる）。`format_…`：取ったファイルを、run-start の `code_sha256` の版の `gkg.aggregate_zip` にかけ、同じ形の誤りになるかを見る。`content_encoding`：同じ URL の応答のヘッダの Content-Encoding を見る。`ambiguous_listing`：手順1の一覧に、その file_time の違う行が二つ以上あるかを見る |
     | 一時的 | `http_429`、`http_500`・`http_502`・`http_503`・`http_504`、`network_…`（通信の失敗。例外の名前は `gkg.NETWORK_ERROR_NAMES` の固定の一覧のどれかで、一覧に無いものは `network_Other`。T-030 軽-D）、`retry_after_too_long`、`attempts_exhausted` | 今取れることは反証にならない（そのとき相手か通信が不調だったという主張） | 数が多い日、決まった時期への偏り、`requests_sent` と `attempts` の差を見る |

  4. failed の数の多い日、決まった時期に偏った failed、`reason` の偏りを並べて見る。
- **一覧の本体が手に入らないときに確かめられないこと**：手順2の `files_listed` の照合（その日のファイルの数を、運営側が少なく数えていないか）は、一覧の本体か、取り直した一覧が要る。取り直した一覧が封印の時の一覧と違えば（sha256 が合わなければ）、数の違いが GDELT の側の変化か、運営側の数え違いかは分からない。手順3（failed のファイルが今は取れるか）は、day の行だけでできる。
- **確かめられないこと**：取得したときに GDELT の側で取れなかったこと（一時的な不調・あとで足されたファイル）は、あとからは示せない。照らして分かるのは「今は取れる」ことまでで、それを運営側の選び出しの疑いとして公開の場で問える、ということである。

#### 6.5.2 手元の検査：何を止め、何を止めないか

| 検査 | 止めるもの | 止めないもの（限界） |
|---|---|---|
| 取得の記録の控え（run-start・run-resume・day・run-stop・run-complete の行の `fetch_log_size`・`fetch_log_sha256`） | 控えより前の行を消す・書き換える。最後の控えが run-start か run-stop のときに、あとから行を足す・記録を置き換える | 控えを書けずに止まった（kill -9・停電）あとに足した行は、控えでは見分けられない（下の「信用しない範囲」で扱う）。マニフェストをコミットの前に書き換えること（下の「全部コミット」で扱う） |
| 信用しない範囲（`untrusted_ranges`。差し戻し3回目 中-1） | 控えより後ろの行の範囲を run-resume の行に書いて引き継ぎ、以後、何回再開しても、その範囲の結果の行（ok・failed・interrupted）は使わずに取り直す。その範囲の attempt の行は回数に数えるが、それだけで使い切らせない（少なくとも1回は要求を送る） | 範囲の中の attempt の行で、そのファイルの試行の回数が増える（最大で残り1回まで減る）。kill -9 の直前に本当に送った要求も、範囲の中なので、結果は取り直しになる。**そのため、1本のファイルへの要求の総数は、上限（`MAX_ATTEMPTS_PER_FILE` = 3）に kill -9 の回数を足した数まで増えうる**（T-026 軽-2）。実際に送った数は `failed_files` の `requests_sent` と day の行の `requests_sent` に書く。第三者は 6.5.1 の手順2で `requests_sent` と `attempts` を照らして見つけられる |
| 取得の記録の行の形（T-026 軽-4） | 結果の行の `reason` が、このモジュールが書く決まった語（`http_<3桁>`・`http_None`、`network_` と固定の一覧（`gkg.NETWORK_ERROR_NAMES`）の名前、`format_` と決まった語、そのほかの決まった語）でない行、`attempts` が 0〜3 の整数でない行、attempt の行の回数が 1〜3 の整数でない行があれば止まる。偽の行で、人名などの任意の語や数が day の行の `failed_files` に載ることを止める | 決まった語の中から選んだ偽の reason（たとえば `http_404`）は形では見分けられない。6.5.1 で扱う |
| 再開のたびに、正式な run のマニフェストを全部コミット | 前のコミットより前に書いた行（コミット済みの控え・範囲）を書き換えること | その回に書いた行（止まってから次のコミットまでのあいだ、作業ツリーにだけある day・run-resume の行の控えや範囲）を、コミットの前に書き換えること。たとえば kill -9 のあと、まだコミットしていない day の行の控えを、偽の failed の行を足した取得の記録に合わせて書き直すと、偽の行が使われる。見分けられないので、6.5.1（偽の failed は `failed_files` に載り、第三者が GDELT と照らせる）で扱う。履歴そのものを書き換えること（リモートが無いので、写しを持たない第三者には見えない） |
| 保存先の一覧（gkg-method・gkg-trial。中-1・中-2） | 決まった名前でないもの（`aside-…` などに名前を変えた日の集計、「.」で始まる名前・フォルダ、リンク）がある。gkg-method に別の run のファイルがある | フォルダの外（同じディスクの別の場所や、別のディスク）へ移したもの。日の集計を書いたあと day の行を書く前に kill -9 し、中身を見てからフォルダの外へ移すことは止められない（そのあとの選び出しは、上の「信用しない範囲」と、6.5.1 の failed の一覧で扱う） |
| 試しの run の照合（中-2・T-032） | 試しの run のマニフェストに載っていない run のファイルがある。載っている run の取得の記録が、無い・控えと合わない。再開のときに、run-start の行の `gkg_run_seq` の記録が無い・合わない（6.5.5） | 試しの run のファイルを全部フォルダの外へ移し、コミットの前にマニフェストの行も消すことは、手元の検査では見分けられない。ただし T-032 のあとは、その run の `gkg-run-start`（trial）の記録が、**コミットして公開した封印の記録に残っていれば**、記録の件数（異なる run_id の数）と、試しの run のマニフェストの run-start の行の**異なる run_id の数**の食い違いとして、第三者が見つけられる（6.5.5 の第三者の照らし方の3）。同じ run_id の行が2行以上あるのは、正直なやり直しでも起こるので、行の数そのものでは比べない。記録をコミットと公開の前に戻した場合は、6.5.5 の「示せないこと」のとおり見つからない |
| ディスクの印（`gkg-<mode>-<run_id>-volume-mark`。オーナーの決定で、値もハッシュも記録しない） | 印のファイルが無い（印を作っていないディスクをつないだ）・形が違う・リンク | **決めた形（16進64字と改行）の値なら、どんな値でも通る**。照らす相手を公開される場所に置けないため。違うディスクをつないだ場合に主に止めるのは、取得の記録の控え（記録が無い・違うので合わない）の方である |
| 既にある日の集計をそのまま使う前の検査（T-030 軽-A・T-032。`gkg.check_existing_day_file`） | ファイルのバイト列について：gzip の頭がこのコードの書く形でない（FEXTRA・FNAME・FCOMMENT などの欄がある、時刻が 0 でない）、gzip の部分の後ろに別の部分かバイトがある。展開した中身について：使ってよい文字の外の文字やメールアドレスの形がある、F の行の attempts の欄が 0〜3 の1桁の数字でない。どれも、day の行を書かずに止まる | attempts の欄を 0〜3 の範囲で書き換えること（比べない欄なので見分けられない。day の行の `failed_files` の `attempts` は今回の取り直しの数で、照らす相手にならない）。gzip の頭の9・10バイト目（XFL・OS。1バイトずつ）は照らさない（別の圧縮器や OS で書いた正直なファイルも通すため）ので、この2バイトには任意の値を置ける（語やメールアドレスの形は入らない） |
| 除外の規則の封印の記録（5.3章） | 鎖に除外の規則の記録が無い・違うのに取得を始めること（`run_gkg` を直接呼んでも止まる） | 記録の中身（どの規則を封印したか）の照合は、封印係の仕組みで行う |

- VolumeUUID は、マニフェスト・取得の記録・日の集計・ログのどこにも書かない（オーナーの決定「記録に残さず、公開もしない」）。ディスクの形式（msdos でなければ止まる）は diskutil で確かめるが、形式も記録には書かない。

#### 6.5.3 除外の規則の封印の記録の照合のしかた（第三者向け。差し戻し3回目 軽-3）

- run-start の `exclusion_rule_seq` は、封印の記録 `sealed/ledger.jsonl` の、除外の規則の kind（`themes.EXCLUSION_RULE_KIND` = `stats-order1`。統計係の順番1。封印係の `ledger.ORDER1_KIND` と同じ）の記録の seq である。この kind の記録は1件だけに限られている（封印係の `ledger.check_stats_order` が2件目を止め、収集係の関門も2件以上なら止まる。T-032）。
- `exclusion_rule_record_sha256` は、その記録の行の**正規の形のバイト列（`ledger.canonical_line`：キーを並べ替え、区切りに空白を入れない UTF-8 の JSON。末尾の改行を含めない）の sha256** である。記録の行は正規の形で書かれているので、`sealed/ledger.jsonl` のその行のバイト列（改行を除く）の sha256 と同じになる。
- 確かめ方：`sealed/ledger.jsonl` の seq がその値の行を取り出し、改行を除いて sha256 を計算し、マニフェストの値と比べる。その行の kind が `stats-order1` であること、ほかに同じ kind の行が無いことも確かめる。区分表のマニフェストの試行の行と結果の行にも、同じ2つの値を書く。

#### 6.5.4 日の集計の形（版3。T-035）

- 頭の行（タブ区切り）：`# gkg-day 3 <日> <mode>`。
- T の行（タブ区切り。7つの欄）：`T g theme_id v1_docs v2_docs v2_mentions v1_or_v2_docs`。`v1_or_v2_docs` は、そのテーマが V1THEMES か V2ENHANCEDTHEMES の少なくとも一方に付いた文書の数（同じ文書で両方に付いても1回）。2026-10-08 のオーナーの決定で、正式に使う報道量の分子。分母は同じ数え方の全テーマの合計。`v1_docs + v2_docs − v1_or_v2_docs` が、両方に付いた文書の数。
- S の行：`docs_without_any_theme`（V1 にも V2 にもテーマが一つも付かない文書の数）を足した。`docs_without_v1_theme`・`docs_without_v2_theme` は前のまま。形の合わない名前しか付かない欄は、一つも付かない欄と同じに数える。`docs_without_any_theme` は、ほかの2つの値のどちらよりも大きくならない。**S の行は、値が 0 の名前を書かない**（T-035 の監査 軽-2）。読む側は、無い名前を 0 と読む。
- 名前の取り出し方：V1THEMES は「;」で区切った各部分、V2ENHANCEDTHEMES は「;」で区切った各ブロックの最初の「,」より前（文中の位置の数を捨てる）。どちらも英大文字で始まり英大文字・数字・下線だけの名前（160字まで）だけを数える。名前の辞書はテーマ・国・言語・ENG の語で別々にしてあり（T-032。T-035 の監査 中-1）、同じプロセスで先に言語の符号などを見ても、テーマの数は変わらない。同じ文書の同じ欄に同じ名前が2回あっても、文書の数は1回と数える。同じテーマかどうかは、取り出した名前の文字列が完全に一致するかで決める。
- 限界：V1 と V2 で同じテーマに違う名前が付いている場合は、別々のテーマとして数えられ、`v1_or_v2_docs` で1つにまとまらない。名前の対応表は使わない。

#### 6.5.5 run の開始の封印の記録（gkg-run-start。T-032）

- 試しの run と正式な run のどちらも、run の最初の実行（マニフェストに run-start の行を書く実行）で、run-start の行を書く前・印のファイルを書く前・GKG に要求を送る前に、封印係の `seal_gkg_run.start`（`src/sealer/seal_gkg_run.py`。`docs/verify/periods-seal.md` 12章）で、封印の記録 `sealed/ledger.jsonl` に `gkg-run-start` を1件書く。中身は、mode・run_id・取得のコードのパスと sha256・ファイル一覧の sha256・method-access の seq・試しの run の日（正式な run は null）・除外の規則の記録（`stats-order1`）の seq と sha256・drand・ledger_head だけ（保存先・ユーザー名・VolumeUUID は入れない）。
- 書くときに、drand（`api.drand.sh` ほか）と OpenTimestamps のカレンダーに通信する（3章の表と同じ宛先）。書けなければ（封印係の関門で止まった・通信の失敗など）、マニフェスト・印のファイル・取得の記録のどれも書かずに止まり、GKG への要求は1件も送らない。
- 同じ run の再開と、正式な run の2回目の実行（1回目は run-start を書いて止まる）では書かない。記録を書いたあと run-start の行を書く前に止まった場合は、次の実行で、同じ mode・run_id の記録を新しく書かずに使う。
- **再開のときの照合**（T-032 の差し戻し1回目 中-1）：run-start の行が既にあるとき（再開・正式な run の2回目の実行）は、その行の `gkg_run_seq` の記録を封印の記録から読み、kind が `gkg-run-start` で、行の正規の形の sha256 が `gkg_run_record_sha256` と同じで、中身の mode と run_id がこの run と同じことを確かめる。無い・合わなければ、要求を送らず、何も書かずに止まる。手で書いた run-start の行を置いて、記録を書かずに試しの run を走らせる道は、ここで止まる。
- そのため、**このスクリプトで行った試しの run の回数（異なる run_id の数）は、封印の記録の `gkg-run-start`（mode が trial）の件数と同じ** になる。同じ run_id で試しの run をやり直しても（記録を書いたあとに止まった run・マニフェストの行を消してから同じコードで走らせた run）、記録を使い回すので1件と数える。同じ run_id の run は同じコードと同じ入力なので、入力を選び直す余地にはならない。
- マニフェストの run-start の行（`gdelt-gkg-trial.jsonl`・`gdelt-gkg-method.jsonl`）には、その記録の seq（`gkg_run_seq`）と、記録の行の正規の形の sha256（`gkg_run_record_sha256`）を書く。
- **第三者の照らし方**（verify 側の照合は封印係の別のタスクで足す）
  1. マニフェストの各 run-start の行について、`sealed/ledger.jsonl` の seq が `gkg_run_seq` の行を取り出し、改行を除いたバイト列の sha256 が `gkg_run_record_sha256` と同じことを確かめる。その行の kind が `gkg-run-start` であること。
  2. その記録の中身（`sealed/gkg-run-start-<sha256>.json`）の `mode`・`run_id`・`code_sha256`・`filelist_sha256`・`method_access_seq`・`exclusion_rule_seq`・`exclusion_rule_record_sha256` が、run-start の行の同じ名前の値（mode は行の `mode`）と同じこと。試しの run なら `trial_days` が行の `trial_days` と同じこと。
  3. **試しの run の回数と入力**：`verify.py gkg-runs` が数える trial の記録の件数が、試しの run のマニフェストの run-start の行の異なる run_id の数と同じで、各 run_id が1対1に対応すること（同じ run_id の試しの run は記録を使い回すので、1件と数える）。正式な run の run-start の行の `trial_run_ids` が、official の記録より前の trial の記録の run_id の一覧と同じこと。一覧に無い試しの run（記録だけあって行が無い、または行だけあって記録が無い）は、隠した試しの run か、手順を飛ばした跡である。
  4. 各 run の `code_sha256` を、その記録を含むコミットの中の `src/collector/acquire_gkg.py` と照らす。
- **示せないこと**（照らしたあとに残る限界）
  - このスクリプトを使わない取得（コードを変えて照合を外して動かす・別のプログラムで GKG を取る）は、記録からは検出できない（封印係の 12章の「記録に無い run」）。照らせるのは、このスクリプトを通した run だけである。
  - 同じ run_id で試しの run をやり直した回数は、記録の件数には出ない（上のとおり1件と数える）。やり直したことは、試しの run のマニフェストの行（コミットしたもの）と、保存先の取得の記録・日の集計からしか分からない。
  - 試しの run の結果を見たあとで、別の run_id（コードを変えたもの）で取り直すことは止めない。ただし、そのたびに記録が1件増え、記録の件数（異なる run_id の数）として数えられる（記録をコミットして公開した場合。次の項）。
  - **記録を書いたあと、コミットとハッシュの公開の前に、まとめて戻すこと**（T-042。T-032 の監査 中-A）：gkg-run-start を書いて試しの run を走らせたあと、結果を見てから、封印の記録 `sealed/ledger.jsonl` の末尾の行、その中身（`sealed/gkg-run-start-<sha256>.json`）、その seq の `.ots`、試しの run のマニフェストの行を、まとめて書く前の形に戻すことは、記録からは見つからない。戻したあとの封印の記録は、鎖としては正しいままだからである。これはこのスクリプトで塞げる種類ではなく、封印の記録全体の限界で、`docs/verify/periods-seal.md` 7章の「別の系列」と同じものである。時間の幅は、封印の記録を書き足すたびに、記録の時刻から24時間以内にハッシュを X に投稿する決まり（CLAUDE.md の「公開前の検査」）で限られる。投稿したハッシュと、あとで公開する封印の記録の先頭のハッシュを見比べれば、投稿のあとに戻したことは見つかる。投稿の前（24時間以内）に戻したことは見つからない。

### 6.6 本番の規模とメモリ

規模：198,226 本、約 1.79 TB の通信、2,115 日。要求の間隔だけで約55時間、全体で60〜120時間の見込み。試行の行を書くたびに外付けディスクで fsync するので、その分も少し延びる。

メモリの見込み（データを見ていない見積もり。試しの run で測る）
- テーマの組1種類あたり約 110 バイト（Counter の項目と tuple）。1日の組の種類を V1・V2 それぞれ 200万〜1,000万と見込み、合わせて 0.4〜2.2 GB。
- そのほか：zip（最大 200 MB）、1ファイル分の集計、テーマ×国（1日 10万〜100万種類、約 0.1 GB）、テーマの名前の一覧。
- 日の集計を書くときは、組を並べ替えた一覧と書き出しの文字列を一時的に作るので、組の部分が最大で約2倍になる。
- 版3（T-035）で、T の表に `v1_or_v2_docs` の入れ物が1つ増える（1日に数千〜2万項目、数 MB）。日の集計の T の行は1行あたり数バイト大きくなるが、全体の大きさは P1・P2 の行で決まるので、見込み（全体で 20〜200 GB）は変わらない。
- まとめ：ふつうの日で 1〜5 GB、上限（組 4千万種類）に近い日で 9〜10 GB。上限を超えた日は、書かずに止まる。

### 6.7 止まったときの次の手（どれもファイルを削除しない）

- **ディスクが外れた・読み取り専用になった・保存先のフォルダが変わった**（終了コード 3。書かずに止まる）：ディスクをつなぎ直し、`mount` で `/Volumes/LACIE SHARE` が msdos で読み書きできることを確かめてから、同じコマンドで再開する。マウント先の名前が `LACIE SHARE 1` などに変わった場合は、その名前では動かない（止まる）。ディスクを取り出してつなぎ直す。
- **書いている途中でディスクが外れた**：取得の記録の最後の行が途中で切れていると、再開のときに「最後の行に改行が無い」で止まる。日の集計が0バイトなら、再開のときに書き足す（上の規則）。中身が途中まで書かれていると、取り直した集計と比べて「取り直した集計と中身が違う」で止まる（次の項と同じ扱い）。止まった場合はリードに報告する（直し方はリードが決める。ファイルは消さない）。
- **取得の記録が控えと合わない**（終了コード 1）：run と run のあいだに取得の記録が書き換わった。再開しない。リードに報告する。
- **日の集計を書いたあと、day の行を書く前に止まった**（kill -9・停電・Ctrl-C。T-026 軽-1）：同じコマンドで再開する。再開のときに、その日のファイルを取り直して集計を作り直し、既にある日の集計と、F の行の attempts の欄のほかがすべて同じなら、そのファイルをそのまま使う（day の行に `reused_existing_day_file: true`）。このとき day の行の `failed_files` の `attempts` は今回の取り直しの数で、使った日の集計の F の行の attempts とは違うことがある（比べない欄なので）。
  - 取り直しで結果が変わると（止まる前に failed だったファイルが ok になった、failed の理由が変わった、ok だったファイルが failed になった。T-026 軽-2）、中身が違うので「取り直した集計と中身が違う」で止まる。**何回再開しても止まり続ける**（テスト `TestChangedResultOnHonestResume`）。再開をくり返さず、リードに報告する。抜け出すには、その日の集計を保存先の外へ移す必要がある（移せば、次の再開で作り直す）。ファイルを消す必要があるなら、リードを通してオーナーの承認を得てから行う（承認は reviews/ に記録する）。移したファイルも消さずに残し、その場所をリードに報告する。
- **既にある日の集計の検査で止まった**（「gzip の頭が、このコードの書く形でない」「後ろに、別の部分かバイトがある」「使ってよい文字の外の文字がある」「attempts の欄の形が違う」。T-030・T-032）：正直な運用では起きない（このコードの書いた日の集計がそのまま残っていれば通る）。再開をくり返さず、リードに報告する。抜け出すには、その日の集計を保存先の外へ移す必要がある（移せば、次の再開で作り直す）。ファイルを消す必要があるなら、リードを通してオーナーの承認を得てから行う。移したファイルも消さずに残し、その場所をリードに報告する。
- **印のファイルを書いたあと、run-start の行を書く前に止まった**（T-026 軽-4）：再開すると「run-start の前なのに、ディスクの印のファイルが既にある」で止まり、そのあとも止まり続ける。再開をくり返さず、リードに報告する。印のファイル（`gkg-<mode>-<run_id>-volume-mark`）を保存先から外す必要があり、ファイルの削除が要るなら、リードを通してオーナーの承認を得てから行う（承認は reviews/ に記録する）。保存先の外へ移すだけでも、移したファイルの扱いをリードに報告する。
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
- 差し戻し3回目：`test_gkg.py` の `TestRound3Reproductions`（監査の再現 Y1・Y2・exp_peek、2回・3回の再開、day の行の `failed_files`）、`TestRound3Trial`（exp_trial2）、`TestHiddenTrial` の一覧の照合。`test_themes.py` の2段の取得（`test_first_phase_does_not_fetch`、`test_committed_attempt_must_match_code_and_rule`、`TestCodeGate.test_two_phase_with_real_git`）と、限界を確かめる `test_reverting_to_committed_attempt_allows_refetch_limit`。
- T-026：`test_gkg.py` の `TestT026`（日の集計を書いたあとに止まった正直な再開、実際に送った要求の数）、`test_day_line_lists_failed_files`（`listed_size`・`listed_md5`・`requests_sent`、和の照合）。`test_themes.py` の `TestCodeGate.test_git_mv_after_fetch_stops`・`test_existing_themes_file_in_store_stops`・`test_reset_of_history_is_a_documented_limit`。
- T-026 差し戻し1回目：`test_gkg.py` の `TestT026Round2`（reason・attempts の形。監査の probe_c の偽の語で止まること）、`TestChangedResultOnHonestResume`（監査の probe_b4。取り直しで結果が変わると止まり続け、日の集計を保存先の外へ移すと続けられること）。
- T-030：`test_gkg.py` の `TestT030`（既にある日の集計の検査、network_ の名前の固定）。
- T-035：`test_gkg.py` の `TestT035`（V1 と V2 で同じ名前・違う名前・片方だけ・同じ文書で両方、`docs_without_any_theme`、頭の行の版3）。
- T-032 差し戻し1回目：`test_acquire_gkg.py` の `TestSealedRunCheck`（手で書いた run-start の行、seq の欠け、sha256 の食い違い、別の run_id・別の kind の記録を指す行で、再開が要求0件で止まること）、`test_gkg.py` の `TestCheckSealedRun`。
- T-032：`test_gkg.py` の `TestT032`（start_hook の呼び方、書けなければ要求0件、vocab の分け方、日の集計のファイルのバイト列の検査、T-035 の軽-1）。`test_acquire_gkg.py` の `TestSealGkgRun`（一時の写しの封印の記録に、試しの run 2回で2件、正式な run で1件。書けなければ要求0件）。
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

- **`TMPDIR` は必ず、イメージのマウント先を含む場所（上の例では `$SP`）にする。** テストの差し替えは一時的なディレクトリの下しか指せないので、指定しないと `TestEndToEndOnFat32` の2件が止まる（その場合は、TMPDIR を指定するよう求める文で失敗する）。
- 読み取り専用の検査：別のイメージを `hdiutil attach -readonly -nobrowse -mountpoint <場所> <イメージ>` でマウントし、`GKG_FAT32_TEST_VOLUME_RO=<場所>` を付けて `tests.collector.test_gkg.TestOnFat32ReadOnly` を動かす。
- 確かめること（`gkg.py` 8章）：シンボリックリンク（msdos のドライバが作る印のリンク）を保存先・取得の記録の場所に置くと止まること、大文字と小文字だけが違うフォルダの名前で止まること、大文字と小文字だけが違うファイルの名前で上書きしないこと、保存先のフォルダの (st_dev, st_ino) が書き込みのあいだ変わらないこと、試しの run と正式な run を通しで動かして sha256 がマニフェストと一致すること、試行の回数の引き継ぎ。
- テストはイメージの直下に `news-stick-data` を作り、終わると消す（イメージの中だけ）。既にあれば、何もせずに失敗する。

## 8. 区分表の取得（themes.py。T-021。実行は別のタスク）

- 取得元は `https://data.gdeltproject.org/api/v2/guides/LOOKUP-GKGTHEMES.TXT` だけ。オーナーの承認は「件数の欄を捨てる条件で、1回取得してよい」。
- 通信の前に、順に：コードの関門（`src/collector` と `src/sealer` に未コミットの変更が無く、動いている themes.py が HEAD と同じ。除外の規則の関門が読み込む ledger.py を含めて先に確かめる）、除外の規則の封印の関門（kind は未定なので今は必ず止まる）、保存先の確認。
- **2段で取得する**（差し戻し3回目 軽-2。GKG の run-start と同じ形）。
  1. 1段目：`data/manifest/gdelt-themes.jsonl` が作業ツリーにも HEAD にも無ければ、試行の行（`kind: attempt`、`code_sha256`、除外の規則の封印の記録の seq と sha256）を書いて止まる（`AttemptRecorded`。通信しない）。
  2. 試行の行をコミットする（前と後に privacy_scan）。
  3. 2段目：同じコマンドをもう一度実行する。作業ツリーのマニフェストが HEAD とちょうど同じで、中身がこのコードとこの除外の規則の記録の試行の行1行だけのときに限り、`kind: fetch` の行を書いてから通信する。止まったときは `kind: failed` の行を、成功すれば `kind: result` の行を書く。
  4. すぐにマニフェストをコミットする。
- 止めるもの：コミットの前に試行の行を消しても、まだ通信していないので、1段目からやり直すだけになる。通信のあと（fetch・failed・result の行がある）、コミットしていない変更があれば止まる。コミットしたあとで行を消したり空にしたりしても、HEAD と合わないので止まる。マニフェストに試行の行のほかの行があれば止まる（2回目はしない）。
- 1段目の前提（T-026 軽-3）：`git log --all -- data/manifest/gdelt-themes.jsonl` が空であること（マニフェストを `git mv` で別の名前に移してコミットしても、元の名前の履歴が残るので止まる）と、保存先（`~/Desktop/news-stick-data`）に `gdelt-themes-` で始まるファイルが無いこと。
- **止めないもの（限界）**：履歴そのものを書き換えること（`git reset --hard`・rebase・filter-branch などで、試行や結果のコミットを消すこと）は、手元の検査では見分けられない（テスト `test_reset_of_history_is_a_documented_limit`）。リモートが無いので、写しを持たない第三者にも見えない。前提：通信のあとの行（fetch・failed）は、コミットする前は作業ツリーにだけある。→ 結論：その行を消して作業ツリーを HEAD と同じ形（試行の行1行）に戻すと、もう一度通信できる。手元の検査では見分けられない（テスト `test_reverting_to_committed_attempt_allows_refetch_limit` で、この限界を確かめている）。2段目のあとすぐにコミットすることで、時間の幅を小さくする。
- **見出しの無い「名前・件数」の2欄の表**（リードの判断。監査の条件 (1)〜(4)）：1行目に数字だけの値があるとき、どの行も欄がちょうど2つで、一方の欄の値がすべてテーマの名前の形、もう一方がすべて ASCII の数字だけ、という割り当てがちょうど1つに決まる場合に限り、名前の欄だけを残す。判定は欄の位置ではなく値の形で行う。両方の割り当てが合う場合、どちらも合わない場合は止まる。件数の欄はメモリの上で捨て、行を並べ替えてから書く。マニフェストに `headerless: true` と、捨てた欄の位置（`column_A` か `column_B`）を書く。この規則は取得の前にコミットし、試行の行の `code_sha256` で固定する。
- **限界**：区分表は取得した時点の全テーマの一覧なので、2020-12-15 以降に生まれたテーマの名前も入る。名前があることは、そのテーマが後ろの期間に使われたことを示しうる。タグの一覧の規則は、手法を作る期間のデータでテーマの存在を確かめるので、名前だけでは一覧に入らない。
