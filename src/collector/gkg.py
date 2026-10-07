#!/usr/bin/env python3
"""手法を作る期間の GKG 2.1 の15分ファイルを取得し、ディスクに書く前に集計する（T-018。試運転の手順4）。

データ出典
    Data: The GDELT Project (https://www.gdeltproject.org/). This project is not
    affiliated with or endorsed by the GDELT Project.
    データ出典：GDELT Project（https://www.gdeltproject.org/）。本プロジェクトは
    GDELT Project と提携・承認の関係にありません。

このモジュールは、実際の取得をまだ一度も行っていない（T-018 はコードとテストだけ）。取得の実行は
入口のスクリプト acquire_gkg.py から行う（オーナーの承認のあとの別のタスク）。このモジュールを
直接実行しても取得はしない。

------------------------------------------------------------------------
1. 対象のファイル
------------------------------------------------------------------------
    ファイル一覧：T-016 で取得した本体（~/Desktop/news-stick-data/gdelt-filelist/ の下。名前は
    data/manifest/gdelt-filelist.jsonl の1行から決まる）。入口のスクリプトが、マニフェストの
    sha256、封印の記録の acquisition-result の kept_rows_sha256、読んだバイト列の sha256 の3つが
    一致することを確かめてから渡す（load_filelist_rows）。
    選ぶ規則（select_files）
      - file_type が gkg の行だけ。
      - ファイルの日は filelist.file_day（filelist.py 4章の規則。T-010 の申し送りで共通にした）。
      - DATA_START（2015-03-02）≦ ファイルの日 ≦ METHOD_BLOCK_END（2020-12-14）。
        DATA_START より前の行（一覧には 2015-02-18〜2015-03-01 の行が残っている。T-016 の監査
        軽1）は、ここで除く。どちらの値も src/stats/periods.py の値とテストで照合する。
      - 同じ file_time の行が二つ以上あり、大きさか md5 が食い違う場合は、どれを取るかを決め
        られないので取得せず、結果 failed（理由 ambiguous_listing）として記録する。まったく同じ
        行の重なりは1本として扱う。
    ファイルの URL は https://data.gdeltproject.org/gdeltv2/<file_time>.gkg.csv.zip に固定
    （validate_gkg_url。ホスト・スキーム・パスの形を完全一致で照合する。リダイレクトと
    プロキシは使わない）。
    英語の流れだけである点に注意：ファイル一覧（masterfilelist.txt）には翻訳の流れ
    （*.translation.gkg.csv.zip。masterfilelist-translation.txt に載る）が入っていない。
    そのため、取得するファイルの行には翻訳の印 T がほとんど付かず、SRCLC（元の言語）も
    ほとんど空になる見込みである。翻訳の流れを加えるかは、別のタスクで決める。

------------------------------------------------------------------------
2. 待ち時間・再試行・打ち切り（CLAUDE.md「待ち時間と再試行の上限をコードに明記する」）
------------------------------------------------------------------------
    GDELT は data.gdeltproject.org の一括ファイルについて、速度制限・待ち時間・再試行の
    公式の値を公表していない（T-001 で確認した範囲）。下の値は、このプロジェクトが控えめに
    決めた値であり、公式の値ではない。
      MIN_REQUEST_INTERVAL_SECONDS   1.0   要求を送り始める間隔の下限（前の要求の開始から）。
                                           要求は1本ずつ順に送り、同時に二つ以上は送らない
      REQUEST_TIMEOUT_SECONDS        60    接続と、1回の読み込みごとの待ちの上限
      ATTEMPT_DEADLINE_SECONDS       900   1回の試行（ダウンロード全体）の上限
      MAX_ATTEMPTS_PER_FILE          3     1本のファイルの試行の回数の上限（最初の1回を含む）
      RETRY_WAIT_SECONDS             (30, 120)  2回目・3回目の試行の前に待つ秒数
      MAX_RETRY_AFTER_SECONDS        900   Retry-After がこれを超えたら、待たずにそのファイルを
                                           打ち切る
      MAX_CONSECUTIVE_TRANSIENT_FAILURES  5    一時的な失敗（通信の失敗・時間切れ・429・5xx）で
                                           終わったファイルが続けてこの本数になったら、取得の
                                           全体を止める（相手か手元の通信が止まっている）
      MAX_INTERRUPTED_RETRIES_PER_RUN 1    連続した失敗で止まったとき、その失敗のファイルを
                                           interrupted（再開で取り直す印）にするのは、1つの run
                                           の中で1回だけ（5章）
      MAX_CONSECUTIVE_FORMAT_FAILURES    10    形式の失敗（md5 は合うのに zip や行の形が想定と
                                           違う）が続けてこの本数になったら、全体を止める
                                           （コードとデータの形が合っていない）
    値の理由
      - 1秒に1件を超えない間隔で、1本ずつ順に取る。ブラウザで1つずつ落とすのと同じ程度の
        負荷にとどめるため。ファイルは平均で約 9 MB あり、多くの場合、ダウンロードそのものに
        1秒以上かかるので、この間隔で実際に待つことは少ない。
      - 再試行は、相手の一時的な不調（5xx・429）と通信の切れだけを対象にし、待ち時間を
        30秒・120秒と延ばす。404・403・410 は再試行しない（ファイルが無いことは、何度
        取り直しても変わらない）。
      - md5 か大きさが一覧と合わない場合は、途中で切れた可能性があるので再試行する
        （上の回数の内）。
    再試行するかどうかは、上の規則だけで決まる。コードの外で、特定のファイルを選んで手で
    取り直す口は無い（docs/stats/candidates.md 3章 (5)。5章も見ること）。

------------------------------------------------------------------------
3. 受け取りの上限（T-001 の案：圧縮 200MB、展開後 1GB）と、一時ファイルを作らないこと
------------------------------------------------------------------------
      MAX_ZIP_BYTES        200,000,000    応答の本体（zip）の長さの上限。超えたら読むのを
                                          やめ、そのファイルは failed（too_large）
      MAX_UNZIPPED_BYTES 1,000,000,000    展開した中身の長さの上限。zip の中の申告の大きさと、
                                          実際に展開した長さの両方で確かめる
      MAX_LINE_BYTES        16,777,216    1行の長さの上限。超えた行は読み飛ばし、件数だけ数える
    zip はメモリの上（io.BytesIO）で開き、中身は1行ずつ展開して読む。zip も展開した中身も、
    ディスクにも一時ファイルにも書かない（GitHub Actions の上でも同じ。このモジュールは
    tempfile を使わない）。zip の中のファイルは1つだけで、名前が <file_time>.gkg.csv（大文字
    小文字は問わない）でなければ形式の失敗とする。

------------------------------------------------------------------------
4. 項目の一覧（許可リスト。T-001 の6章）と、メモリの上で捨てるもの
------------------------------------------------------------------------
    GKG 2.1 の1行はタブ区切りの27欄（GKG_COLUMNS）。欄の数が27でない行は捨てて件数だけ数える。
    残すのは次の7欄の、さらに決まった部分だけである（add_line）。行を27欄に分けた直後に、
    この7欄の値だけを取り出し、残りの20欄を指す名前を消す。
      GKGRECORDID                  頭の14桁の時刻と、翻訳の印 T（あるか無いか）だけ。
                                   通し番号は使わない
      V2.1DATE                     ファイルの時刻と同じか・0か・別の14桁か・形が違うかの件数だけ
      V2SOURCECOLLECTIONIDENTIFIER 1〜2桁の数字。形が違えば X
      V1THEMES                     テーマの名前だけ（セミコロン区切り）
      V2ENHANCEDTHEMES             テーマの名前だけ（各ブロックの最初の欄。文中の位置は捨てる）
      V1LOCATIONS                  各ブロックの CountryCode（3番目の欄。FIPS の2文字）だけ。
                                   種別・地名・ADM1・緯度・経度・FeatureID は捨てる
      V2.1TRANSLATIONINFO          SRCLC（3文字の小文字。形が違えば OTHER、無ければ -）と、
                                   ENG のうち既知の書式（ENG_TOKEN_PATTERNS）に完全に合う部分
                                   だけ。合わない部分は OTHER の件数として数えるだけ
    捨てる欄（一覧に入れない）：V2SOURCECOMMONNAME、V2DOCUMENTIDENTIFIER（記事の URL）、
    V1COUNTS、V2.1COUNTS、V2ENHANCEDLOCATIONS、V1PERSONS・V2ENHANCEDPERSONS（人物名）、
    V1ORGANIZATIONS・V2ENHANCEDORGANIZATIONS（組織名）、V1.5TONE、V2.1ENHANCEDDATES、V2GCAM、
    画像・動画・SNS の欄、V2.1QUOTATIONS、V2.1ALLNAMES、V2.1AMOUNTS、V2EXTRASXML。
    残す値も、形を正規表現で確かめる（テーマの名前は英大文字・数字・下線だけ、160字まで）。
    形が合わない値は捨てて件数だけ数える。そのため、捨てた欄の中身が、形の合わない値として
    紛れ込むこともない。
    文書の「組」（以下 g）：V2SOURCECOLLECTIONIDENTIFIER の値に、翻訳の印があれば T を付けた
    もの（例 "1"、"1T"、"2"）。分母と数え方は試運転のあとで決めるので、どの集計も g ごとに
    分けて持ち、あとで組を選んで足せるようにする。
    行の時刻：GKGRECORDID の時刻が 2020-12-14 23:45:00 より後（ファイルの日の規則で
    METHOD_BLOCK_END より後。区画の後ろの期間）の行は、どの件数にも入れずに捨てる（rows にも
    数えない。後ろの期間の量を扱わないため）。それ以外で、行の時刻がファイルの時刻と違う行は
    件数（rows_id_time_differs）を数え、DATA_START より前なら（rows_id_time_before_block）集計に
    入れずに捨てる。行はファイルの日に入れる（行の時刻では日を決めない）。
    欄の数や ID の形が違う行（時刻が分からない行）は、ファイルの日（区画の中）の行として
    件数だけ数える。

------------------------------------------------------------------------
5. 取得の記録、取り直し、途中で止まったとき
------------------------------------------------------------------------
    run_id：入口のスクリプトの sha256 の先頭16桁。コードが同じなら同じ run_id になり、
    途中で止まった取得を続きから再開する。
    正式な run（T-018 の差し戻し1回目のリードの指示）
      - 正式な run は、マニフェスト gdelt-gkg-method.jsonl の「最初の run-start」の run である。
        run-start の行には official: true を書く。
      - run-start は、コミットしてからでないと取得を始めない（T-021。T-018 の監査 軽2）。
        最初の実行は、run-start を書いたところで RunStartWritten で止まる（GKG にはまだ一度も
        要求を送っていない。入口のスクリプトは終了コード 4）。オーナー（または実行の担当）が
        マニフェストをコミットしてから（リモートがあれば push もしてから）、同じコマンドで
        もう一度実行する。2回目からは、
        入口のスクリプトが git から読んだ HEAD のマニフェスト（committed_manifest）について
          (i)  作業ツリーのマニフェストが、HEAD のマニフェストのバイト列で始まる（コミットした
               行を書き換えていない。そのあとは追記だけ）
          (ii) 最初の run-start の行が、HEAD のマニフェストの中にある
        を確かめ、どちらかが欠ければ要求を送らずに止まる（GkgError）。
        こうするのは、データを1本も受け取らないうちに、正式な run の始まりを Git の履歴に
        入れるためである。マニフェストはコミットの前なら消せるので、最初の run-start を消して
        別の run を正式にする（結果の良い run を選ぶ）余地が残っていた。コミットのあとに消すには
        履歴を書き換える必要があり、push したあとなら第三者の写しと食い違う。
        限界：コミットと push は人の操作で、封印の記録（OpenTimestamps）には入らない。履歴を
        書き換えること（コミットを消して別の run を始めるなど）は、写しを持たない第三者には
        見えない。2026-10-08 の時点でリポジトリにリモートは無い。封印の記録への追記は
        封印係の範囲なので、T-021 の報告で提案した。
      - マニフェストに別の run_id の run-start が既にあれば、新しい run は始めずに止まる
        （GkgError）。コードを変えると run_id が変わるので、run-start のあとでコードを変えた
        場合は、取得を続けられない。続けるかどうか、規則を変えるかはオーナーが決める（別の
        タスク。前の run のファイルと記録は消さずに残る）。こうするのは、コードを少し変えて
        新しい run を作り、欠けたファイルを取り直す（結果の良い run を選ぶ）余地を無くすため。
      - 手法を作る期間の欠けた日の一覧は、正式な run の記録（マニフェストの day の行と、日の
        集計の F の行）だけから作る（official_day_records）。
    取得の記録（保存先の gkg-<run_id>-fetch-log.jsonl。Git の外。追記のみ）
      置き場所は、日の集計と同じ外付けディスクの同じフォルダとする（T-021。理由は7章）。
      15分ファイル1本につき、結果が決まるたびに1行を追記する。項目：file_time、listed_md5、
      listed_size（一覧の値）、sha256（受け取った zip のバイト列。成功したときだけ）、result
      （ok / failed / interrupted）、reason、attempts、transient、docs（g ごとの文書数）、stats
      （行の件数の内訳）、finished_at、run_id。欠けたファイル（failed）も必ず1行書く。
      試行の行（T-021。T-018 の監査 軽1）：要求を1回送る直前に、毎回 result が attempt の行
      （run_id、file_time、attempt（何回目か）、at）を追記する。書けなければ要求を送らない。
    取り直しの規則（コードに固定。手で取り直す口は無い）
      - 1本のファイルの中の再試行は2章の値だけ。
      - 試行の回数は、止まって再開しても引き継ぐ（T-021。T-018 の監査 軽1）。再開のときに、
        各ファイルについて「最後の結果の行（ok・failed・interrupted）より後の attempt の行の数」
        を、使った試行の回数とする。残りが無ければ要求を送らずに failed（attempts_exhausted）
        とする。残りがあれば、2章の待ち時間（RETRY_WAIT_SECONDS の、使った回数に当たる値）を
        待ってから続きの試行をする。再試行を待っているあいだにプロセスを止めても、試行の
        回数は戻らない。
        回数を 0 に戻すのは、結果の行が書かれたあとだけである：ok（下の (b) で、その日の集計を
        書く前に止まったときの取り直し）と interrupted（下の (a) の1回だけの取り直し）。
      - failed になったファイルは、再開しても取り直さない。結果はそのまま。
      - 取り直すのは次の二つだけで、どちらも人が個々のファイルを選ぶものではない。
        (a) 2章の「続けて失敗したら全体を止める」で止まったとき、その連続した失敗の
            ファイルを interrupted として記録する。再開すると、interrupted のファイルは
            取り直す。ただし、interrupted にするのは1つの run の中で1回だけ
            （MAX_INTERRUPTED_RETRIES_PER_RUN）。2回目以降に連続した失敗で止まったときは、
            その失敗のファイルを failed のまま確定させて止まる（再開しても取り直さない）。
            通信を止めるなどして連続した失敗を起こさせ、選んだファイルを何度も取り直させる
            余地を、run の中で1回に限るため。代償：2回目の通信の不調で失敗したファイルは
            欠けたまま残る。
            一時的な失敗が続いている途中で日が変わった場合、前の日の集計はまだ書かない
            （続きで止まる条件に達したら、日をまたいだ失敗も interrupted にして取り直せる
            ようにするため）。連続が途切れた時点（成功か、一時的でない結果）で、待たせた日を
            順に書く。最後の日のあとは、連続の途中でも書く。
        (b) その日の集計を書く前に止まった日（停電・Ctrl-C・ディスクの残りの不足など）は、
            再開のときにその日の ok のファイルを取り直して集計し直す（集計はファイルに
            書いていないため）。failed のファイルは取り直さない。
      - 取得が全部の日について終わったら、マニフェストに run-complete を書く。そのあとは、
        同じ run_id で取得を始めようとしても止まる。
    いつ再開するかは人が決める。この余地は、(a)(b) に当たるファイルだけに限られ、記録には
    すべての試行と時刻が残る。手法を作る期間の欠けた日の一覧は、モデルより前に封印する
    （candidates.md 3章 (5)）ので、再開はその封印より前にだけ行う。
    止まる条件（RunInterrupted。入口のスクリプトは終了コード 3）
      - 2章の連続した失敗の上限に達した
      - 保存先のディスクの空きが MIN_FREE_DISK_BYTES（10 GiB）を下回った（日の集計を書く前に
        確かめる）
      - 1日分のテーマの組の種類が MAX_PAIR_KEYS（合わせて4千万）を超えた（メモリの上限。
        切り捨てて続けることはしない。集計の形を見直すかはリードが決める）
      - 保存先のディスクが外れた、読み取り専用になった、保存先のフォルダが別のものに
        変わった（保存先に書く前に毎回確かめる。8章）。保存先に書く途中で OSError が出た
      - 書こうとしたファイルが FAT32 の1ファイルの上限（FAT32_MAX_FILE_BYTES）を超える（8章）

------------------------------------------------------------------------
5.1 試しの run（T-021。T-018 の申し送り）
------------------------------------------------------------------------
    正式な run の前に、最初の数日だけを取って、日の集計の大きさとメモリを測るための run。
      - 日：TRIAL_DAYS（2015-03-02・03・04 の3日。手法を作る期間の最初の3日）に固定する。
        これより多くも、ほかの日も取れない。手法を作る期間の外の日は入らない（テストで照合）。
      - 保存先：TRIAL_STORE_PARTS（LACIE SHARE の news-stick-data/gkg-trial）。正式な run の
        保存先とは別のフォルダ。マニフェストも別（data/manifest/gdelt-gkg-trial.jsonl）。
        行には official: false、trial: true を書く。
      - 正式な run の判定（gdelt-gkg-method.jsonl の最初の run-start）には数えない。正式な run の
        マニフェストには何も書かない。
      - 正式な run の run-start が既にあれば、試しの run は始めない（GkgError）。試しの run は
        正式な run の前にだけ行う。
      - 試しの run の run-start は、コミットを待たずに取得を始める（正式な run を選ぶ余地に
        関わらないため）。マニフェストは、終わったあとにコミットする。
      - 取得・集計・試行の規則は、正式な run と同じコードで同じに動く（run_id も同じ）。
      - 正式な run は、試しの run の3日も含めて、全部の日を取り直す。試しの run の集計は、
        正式な run の結果として使わない。
      - 試しの run の印（T-021 の差し戻し1回目 中2）：日の集計と取得の記録のファイル名に mode
        （trial・official）を入れる（gkg-<mode>-<run_id>-day-<日>.tsv.gz、
        gkg-<mode>-<run_id>-fetch-log.jsonl）。取得の記録の各行と、マニフェストの各行に mode を
        書く。日の集計の頭の行（# の行）にも mode を書く（形式の版 2）。取得の記録に、別の
        run_id か別の mode の行が1つでもあれば止まる。
        mode の印は、行の中の文字なので書き換えられる。試しの run の記録の mode を書き換えて
        正式な run の場所に置くことを止めるのは、5.2章の控えの照合である（run-start のあとの
        取得の記録の大きさは控えとちょうど同じでなければならないので、置いた記録で止まる）。
      - 試しの run の回数と範囲（中4）：正式な run は、試しの run のマニフェスト
        （gdelt-gkg-trial.jsonl）が全部コミットされていなければ始めない（作業ツリーの中身が
        HEAD の中身と同じであること。無ければ両方とも空）。正式な run の run-start には、試しの
        run の run_id の一覧（trial_run_ids。各 run-start の行の gkg_run_seq の小さい順。T-045）と、
        試しの run のマニフェストの sha256（trial_manifest_sha256）を書く。再開のたびに、試しの run のマニフェストがこの sha256 の
        ままであることを確かめる。
      - 試しの run の保存先の照合（差し戻し2回目 中-C・3回目 中-2。check_trial_folder）：
        正式な run の run-start の前と再開のたびに、gkg-trial のフォルダを一覧する
        （check_store_listing。5.4章）。フォルダにある run_id がすべて試しの run の
        マニフェストに載っていて、マニフェストに載っているすべての run の取得の記録が、
        フォルダにあって最後の控えと大きさも sha256 も同じでなければ止まる。
        限界：試しの run のファイルを全部フォルダの外へ移し、コミットの前にマニフェストの行も
        消せば見つからない。試しの run の run_id はコードの sha256 から決まるので、
        試しの run のあとでコードを変えたかどうかは、run_id の一覧と正式な run の run_id を
        比べて分かる。

------------------------------------------------------------------------
5.2 run と run のあいだの書き換えと、ディスクの取り違え（T-021 の差し戻し1回目 中1・軽3）
------------------------------------------------------------------------
    取得の記録の大きさと sha256 の控え（中1）
      - マニフェスト（Git に入る側）の run-start・run-resume・day・run-stop・run-complete の
        行に、その時点の取得の記録の大きさ（fetch_log_size）と sha256（fetch_log_sha256）を
        書く。run-stop は、取得の途中でどの例外で止まっても書く（RunInterrupted・GkgError・
        Ctrl-C など。差し戻し2回目 軽-6）。書けなければ書かない。kill -9 と停電では書けない。
      - 再開のときは、最後に控えた行の値について、取得の記録の先頭からその大きさまでの
        sha256 が一致することを確かめる。一致しなければ（行を消した・書き換えた）、要求を
        送らずに GkgError で止まる。
      - 最後の控えが run-start か run-stop（きちんと止まった）なら、取得の記録の大きさが控えと
        ちょうど同じでなければならない。止まったあとに足した行（偽の failed の行など）や、
        置き換えた記録があれば止まる（差し戻し2回目 中-A）。
      - 最後の控えより後ろの行（控えを書けずに止まった跡）は、信用しない範囲として、再開の
        ときに run-resume の行の untrusted_ranges（取得の記録のバイトの [始め, 終わり) の一覧）に
        書き、前の run-resume の範囲も引き継ぐ（差し戻し3回目 中-1）。以後、何回再開しても、
        その範囲に始まる結果の行（ok・failed・interrupted）は使わず、そのファイルは取り直す。
        その範囲の attempt の行は試行の回数に数えるが、それだけでは使い切らせない（範囲の
        attempt の行があるファイルは、回数を最大 MAX_ATTEMPTS_PER_FILE − 1 にして、少なくとも
        1回は要求を送る）。
      - 正式な run は、再開のたびに、作業ツリーのマニフェストが HEAD とちょうど同じ（全部
        コミットされている）ことを求める。止まるたびに、マニフェストをコミットしてから再開する。
        これが止めるのは、前のコミットより前に書いた行（コミット済みの控え・範囲）の書き換え
        である。その回に書いた行（止まってから次のコミットまでのあいだ、作業ツリーにだけある
        day・run-resume の行）をコミットの前に書き換えることは見分けられない（T-026 中-1）。
        たとえば kill -9 のあと、まだコミットしていない day の行の控えを、偽の failed の行を
        足した取得の記録に合わせて書き直すと、偽の行が使われる。これは day の行の
        failed_files（第三者が GDELT と照らせる。README 6.5.1）で扱う。
      - 限界：信用しない範囲の attempt の行で、そのファイルの試行の回数が増える（残り1回まで）。
        kill -9 の直前に本当に送った要求の結果も、範囲の中なので取り直しになる。そのため、
        1本のファイルへの要求の総数は、MAX_ATTEMPTS_PER_FILE に kill -9 の回数を足した数まで
        増えうる（T-026 軽-2）。実際に送った数（attempt の行の数）は、day の行の requests_sent と、
        failed_files の各項目の requests_sent に書く。
      - 日の集計を書いたあと day の行を書く前に止まった場合（T-026 軽-1）：再開のときにその日を
        取り直して作った集計が、既にある日の集計と、F の行の attempts の欄のほかがすべて同じなら、
        既にあるファイルをそのまま使い、day の行に reused_existing_day_file: true を書く
        （attempts の欄は、信用しない範囲の試行の行を数えるかどうかで変わるため比べない）。
        中身が違えば止まる（上書きしない）。取り直しで結果が変わると、何回再開しても止まり続ける
        （README 6.7 の次の手）。使った日の集計の F の行の attempts と、day の行の failed_files の
        attempts（今回の取り直しの数）は違うことがある。
      - 既にある日の集計をそのまま使う前に、展開した中身に check_output_bytes をかけ、F の行の
        attempts の欄が 0〜MAX_ATTEMPTS_PER_FILE の形であることを確かめる（T-030 軽-A）。
      - 通信の失敗の reason は network_<例外の名前> で、名前は固定の一覧 NETWORK_ERROR_NAMES の
        どれか（無い名前は network_Other と書く。T-030 軽-D）。
      - 取得の記録の行の形（T-026 軽-4。_check_log_lines）：結果の行の reason が決まった語
        （valid_reason）で、attempts が 0〜MAX_ATTEMPTS_PER_FILE の整数であること、attempt の行の
        attempt が 1〜MAX_ATTEMPTS_PER_FILE の整数であること、file_time が14桁の数字であることを
        確かめ、合わなければ止まる。偽の行の任意の語や数が failed_files に載らないようにする。
        試しの run のマニフェストは、正式な run の前まではコミットを求めない（5.1章の照合で補う）。
      - 主な防御は手元の検査ではなく、day の行の failed_files（その日の failed のファイルの一覧。
        各項目は file_time・reason・attempts・requests_sent・listed_size・listed_md5）である。第三者は、封印済みのファイル一覧と GDELT の
        サーバーと照らして、そのファイルが今は取れるかを確かめられる（README 6.5.1）。
    ディスクの同一性（軽3。オーナーの決定「記録に残さず、公開もしない」2026-10-08）
      - VolumeUUID は、マニフェスト・取得の記録・日の集計・ログのどこにも書かない。
      - 代わりに、run を始めるとき（run-start の行を書く前）に、保存先のフォルダの中に印の
        ファイル gkg-<mode>-<run_id>-volume-mark を作り、乱数（secrets.token_hex(32)）を書く。
        印の値も、そのハッシュも、マニフェストには書かない（Git に入らず、公開されない）。
      - 再開のたびに、保存先のフォルダに印のファイルがあり、通常のファイル（リンクでない）で、
        決めた形（16進64字と改行）であることを確かめる。無ければ止まる。
      - 限界：印の値と照らす相手は、公開される場所には置けない。そのため、決めた形の値なら
        どんな値でも通る（印のファイルを作り直せば、違うディスクでも通る）。違うディスクを
        つないだ場合に主に止めるのは、取得の記録の控えの照合である（記録が無いか違うので合わない）。
      - ディスクの形式（msdos でなければ止まる）は、入口のスクリプトの関門で確かめる（記録には
        何も書かない）。
    0バイトの日の集計（軽3）
      - 日の集計のファイルを作った直後（中身を書く前）に止まると、0バイトのファイルが残る。
        再開のときに同じ名前の0バイトのファイルがあれば、消さずに、そこへ中身を書き足す
        （write_new_file）。マニフェストの day の行に refilled_empty_file: true を書く。
      - 中身のある違うファイルがあれば、これまでどおり止まる（リードに報告）。

------------------------------------------------------------------------
5.3 除外の規則の封印の記録（差し戻し2回目 中-B）
------------------------------------------------------------------------
    run_gkg は exclusion_rule（除外の規則の封印の記録の seq と、記録の行の正規の形の sha256）を
    受け取り、run-start に exclusion_rule_seq・exclusion_rule_record_sha256 として書く。
    run_gkg の中でも、themes.require_exclusion_rules_sealed()（入口のスクリプトの関門と同じ）を
    もう一度呼び、鎖の上の記録と同じであることを確かめる（chain_exclusion_ref）。再開のときは、
    run-start に書いた値とも照らす。そのため、入口のスクリプトを通らずにこの関数を呼んでも、
    鎖に除外の規則の記録が無ければ、何も書かずに止まる。kind が未決のあいだは必ず止まる。
    照合のしかた（第三者向け。差し戻し3回目 軽-3）：exclusion_rule_seq は、sealed/ledger.jsonl の
    除外の規則の kind の記録のうち seq の順で最初の1件の seq（同じ kind が複数あっても最初の
    1件）。exclusion_rule_record_sha256 は、その記録の行の正規の形のバイト列
    （ledger.canonical_line。末尾の改行を含めない）の sha256 で、ledger.jsonl のその行（改行を
    除く）の sha256 と同じになる。

------------------------------------------------------------------------
5.4 保存先の一覧の照合（check_store_listing。差し戻し3回目 中-1・中-2）
------------------------------------------------------------------------
    run を始めるときと再開のたびに、その mode の保存先のフォルダを一覧する。許すのは、
    gkg-<mode>-<run_id>-（day-<日>.tsv.gz | fetch-log.jsonl | volume-mark）の名前の通常の
    ファイルと、その名前に「._」を付けたもの（macOS の付属のファイル）だけ。正式な run では
    run_id もこの run のものに限る。ほかの名前（名前を変えた日の集計、「.」で始まるほかの名前、
    フォルダ、リンク）があれば止まる。
    止めないもの：フォルダの外へ移したもの。日の集計を書いたあと day の行を書く前に止まった
    場合、その日の中身は保存先にあり、見ることができる。見てから外へ移し、取得の記録に偽の
    行を足しても、偽の行は信用しない範囲に入るので使われない（5.2章）。

------------------------------------------------------------------------
5.5 run の開始を封印の記録に書く（gkg-run-start。T-032）
------------------------------------------------------------------------
    run の最初の実行（run-start の行を書く実行）で、run-start の行を書く前、印のファイルを
    書く前、GKG への要求を送る前に、start_hook を1回だけ呼ぶ。入口のスクリプトは、封印係の
    seal_gkg_run.start（src/sealer。docs/verify/periods-seal.md 12章）で封印の記録に
    gkg-run-start を書く（mode・run_id・code_sha256・filelist_sha256・method_access_seq・
    trial_days・除外の規則の記録の seq と sha256）。書けなければ（関門で止まった・通信の失敗
    など）、何も書かずに GkgError で止まり、要求は1件も送らない。
    run-start の行には、その記録の seq（gkg_run_seq）と、記録の行の正規の形の sha256
    （gkg_run_record_sha256）を書く。同じ run の再開と、正式な run の2回目の実行では呼ばない。
    再開のとき（run-start の行が既にあるとき）は、その行の gkg_run_seq の記録を封印の記録から
    読み、kind が gkg-run-start で、行の sha256 が gkg_run_record_sha256 と同じで、中身の mode と
    run_id がこの run と同じことを確かめる（check_sealed_run。T-032 の差し戻し1回目 中-1）。
    無い・合わなければ、要求を送らず、何も書かずに止まる。そのため、このスクリプトで行った
    試しの run の回数（異なる run_id の数）は、封印の記録の gkg-run-start（trial）の件数と同じに
    なる。同じ run_id の試しの run は、記録を使い回すので1件と数える。

------------------------------------------------------------------------
6. 集計の単位と形（ディスクに書く前に集計する。行単位のデータは保存しない）
------------------------------------------------------------------------
    15分ファイルごと：文書数（g ごと）と行の件数の内訳。取得の記録と、日の集計の F・FD の行に
    書く。マニフェストの day の行には、failed のファイルの一覧 failed_files（file_time・reason・
    attempts・requests_sent・listed_size・listed_md5）と、その日に送った要求の数 requests_sent を
    書く（README 6.5.1。第三者が GDELT と照らすため）。
    日ごと（その日の取得できたファイルの合計）：下の表。1日につき1つのファイル
    gkg-<run_id>-day-<YYYYMMDD>.tsv.gz（gzip、mtime は 0。中身はタブ区切りの ASCII）。
      #   形式の名前と版、日付
      F   file_time result reason listed_md5 listed_size sha256 attempts docs
      FD  file_time g docs
      V   id theme                    （その日に出たテーマの名前と、その日の中だけの番号）
      D   g docs                      （文書数。比率の分母の候補）
      T   g theme_id v1_docs v2_docs v2_mentions v1_or_v2_docs   （版3で v1_or_v2_docs を足した）
      C   g theme_id country v1_docs v2_docs v2_mentions   （テーマ×国）
      L   g theme_id lang v1_docs v2_docs v2_mentions      （テーマ×言語）
      P1  g theme_id_a theme_id_b docs  （V1THEMES の組。a < b、文書の数）
      P2  g theme_id_a theme_id_b docs  （V2ENHANCEDTHEMES の名前の組）
      NC  g country docs ・ NL g lang docs ・ E g eng_token docs
      S   name value                  （行の件数の内訳の合計。OTHER の件数を含む）
    v1_docs は V1THEMES にそのテーマがある文書の数、v2_docs は V2ENHANCEDTHEMES にある文書の
    数、v2_mentions は V2ENHANCEDTHEMES の言及の回数（同じ文書で複数回なら回数分）。
    v1_or_v2_docs は、V1THEMES か V2ENHANCEDTHEMES の少なくとも一方にそのテーマが付いた文書の
    数（同じ文書で両方に付いても1回。T-035。2026-10-08 のオーナーの決定で、正式に使う報道量の
    分子。分母は同じ数え方の全テーマの合計）。v1_docs + v2_docs − v1_or_v2_docs が、両方に
    付いた文書の数になる。
    名前の取り出し方と、同じテーマかの決め方（T-035）
      - V1THEMES：「;」で区切った各部分をそのまま名前とする。
      - V2ENHANCEDTHEMES：「;」で区切った各ブロックの、最初の「,」より前を名前とする（後ろの
        文中の位置の数は捨てる）。
      - どちらも THEME_RE（英大文字で始まり、英大文字・数字・下線だけ、160字まで）に完全に
        合うものだけを数える。合わないものは件数（theme_tokens_invalid_v1・_v2）だけ数える。
        名前の辞書（同じ名前のバイト列を使い回すための入れ物）は、テーマ・国・言語・ENG の語で
        別々にする（T-032。_vocabs）。テーマの辞書には THEME_RE に合った名前だけが入るので、
        同じプロセスで先に言語の符号や ENG の語を見ても、テーマの数は変わらない。
      - 同じ文書の同じ欄に同じ名前が2回あっても、v1_docs・v2_docs・v1_or_v2_docs は1回と数える
        （v2_mentions は回数分）。空の部分（「;;」）は読み飛ばす。
      - 同じテーマかどうかは、こうして取り出した名前のバイト列が完全に一致するかで決める。
      - 限界：V1 と V2 で同じテーマに違う名前が付いている場合（V2 だけの名前・付け方の違い）、
        別々のテーマとして数えられ、v1_or_v2_docs で1つにまとまらない。名前の対応表は使わない。
    S の行の docs_without_any_theme は、V1THEMES にも V2ENHANCEDTHEMES にもテーマが一つも
    付かない文書の数（T-035。欄の手厚さの推移を公開するため）。docs_without_v1_theme・
    docs_without_v2_theme は、それぞれ片方に一つも付かない文書の数。形の合わない名前しか
    付かない欄は、一つも付かない欄と同じに数える。どの組（g）も合わせた日の合計である。
    docs_without_any_theme ≤ min(docs_without_v1_theme, docs_without_v2_theme) が成り立つ。
    S の行は、値が 0 の名前を書かない（T-035 の監査 軽-2）。読む側は、無い名前を 0 と読む。
    テーマの数え方（文書の有無か、言及の回数か）は試運転のあとで決めるので、どちらでも
    数えられるように四つとも持つ。
    大きさの見込み（データを見ていないので幅は大きい。根拠は GKG の一般的な性質と、ファイル
    一覧の大きさ）
      - 対象は 198,226 本、圧縮で約 1.79 TB（一覧の size_bytes の合計）。1本あたり約 9 MB、
        1日あたり約 0.85 GB の zip。
      - 1日の文書数は 10万〜20万、1文書のテーマは V1 で 10〜50 種類と見込む。
      - T・L：1日に数千〜2万行。C：1日に 10万〜100万行。T の行は版3で欄が1つ増え、1行あたり
        数バイト大きくなる（全体への影響は P1・P2 に比べて小さい）。
      - メモリ：v1_or_v2_docs のための入れ物（テーマごとの数）が1日分の T の表に1つ増える
        （1日に数千〜2万項目で、数 MB）。
      - P1・P2（共起の網）：1文書の組は n(n−1)/2 で、1日の組の種類は 200万〜1,000万と見込む。
        1行は約 20 バイト（テーマは番号で書く）で、gzip で 4〜6 分の1になるとして、1日 10〜
        100 MB、全体で 20〜200 GB。保存先の LACIE SHARE の空き（2026-10-08 の時点で約 372 GB）
        に収まる見込みだが、上の幅は見積もりなので、5章のとおり、ディスクの空きが 10 GiB を
        下回ったら止まる。
      - メモリ：組1種類あたり約 110 バイト（Counter の項目と tuple）。1日 1,000万種類で
        約 1.1 GB（P1・P2 で約 2.2 GB）。上限 MAX_PAIR_KEYS（4千万、約 4.4 GB）で止まる。
        日の集計を書くときは、並べ替えた一覧と書き出しの文字列を一時的に作るので、組の部分が
        最大で約2倍になる（上限の近くで 9〜10 GB）。運用の手順は src/collector/README.md 6.1。
    本番の取得の最初の数日で実際の大きさを測り、見込みを超える場合は、止まったところで
    リードに報告する（組を週ごとにまとめる、P2 をやめるなど、形の見直しは別のタスク）。

------------------------------------------------------------------------
7. 書くもの・書く前の検査
------------------------------------------------------------------------
    保存先（T-021。オーナーの決定「LACIE SHARE を保存先にしよう」）
      外付けディスク LaCie の FAT32 の区画「LACIE SHARE」の、決まったフォルダに固定する。
        正式な run   VOLUME_MOUNT（/Volumes/LACIE SHARE）/news-stick-data/gkg-method
        試しの run   VOLUME_MOUNT/news-stick-data/gkg-trial
      同じディスクの NTFS の区画「LaCie」は、Mac から読むことしかできないので使わない。
      どちらのフォルダも、オーナーが前もって作る。このモジュールはフォルダを作らない。
      日の集計と取得の記録だけを書く。
      マニフェストの store_location には、絶対パスでなく名前の形
      （STORE_LOCATION_NAME = "LACIE SHARE:/news-stick-data/gkg-method"）を書く。
    取得の記録の置き場所：日の集計と同じフォルダ（外付けディスク）にする。理由
      - 再開の規則（5章）は、取得の記録と日の集計の両方を読む。二つを同じディスクに置けば、
        ディスクがつながっていないときは両方とも無いので、片方だけを見て再開する（記録の
        無いまま取り直す、など）ことが起きない。
      - 一つの run の成果が一つのフォルダにまとまり、写す・確かめるときの単位が一つになる。
      - 手元のデスクトップは iCloud に送られることがある（README 1章）。取得の記録は
        数百 MB になりうるので、送らない側に置く。
      代償：外付けディスクが壊れると、日の集計と取得の記録を一緒に失う。日の集計の sha256 は
      マニフェスト（Git）に残るが、取得の記録の sha256 は run-complete まで残らない。
    保存先の検査（resolve_paths。書く前に毎回 _guard_store）
      - VOLUME_MOUNT がシンボリックリンクでないフォルダで、マウントされている
        （os.path.ismount）。マウントが外れていれば、/Volumes の下に同じ名前の普通の
        フォルダがあっても止まる。
      - 読み取り専用でマウントされていない（statvfs の ST_RDONLY）。
      - 2段のフォルダが、どちらもシンボリックリンクでない既にあるフォルダで、名前の大文字と
        小文字まで決めた名前と同じ（親のフォルダの一覧で確かめる。FAT32 は大文字と小文字を
        区別しないので、lstat だけでは「GKG-Method」も通ってしまう）。
      - realpath がディスクの realpath の下の決めた場所で、st_dev がディスクと同じ。
      - プロジェクトの下でなく、Git の作業ツリーの中でない。
      - 書く前に毎回（_guard_store）：ディスクがマウントされたまま書き込めること、保存先の
        フォルダの (st_dev, st_ino) が最初に確かめたものと同じこと。違えば書かずに
        RunInterrupted で止まる。
    マニフェスト：<root>/data/manifest/gdelt-gkg-method.jsonl（試しの run は
    gdelt-gkg-trial.jsonl）に追記する（過去の行は書き換えない）。マニフェストは手元の
    プロジェクトの中（APFS）で、外付けディスクには置かない。
      run-start   取得の最初の要求より前に1回（run_id、code_sha256、filelist_sha256、
                  method_access_seq、選んだファイルと日の数、started_at）
      run-resume  再開のたび
      day         日の集計を書くたび（file_name、sha256、files_listed・ok・failed、docs）
      run-complete 全部の日が終わったとき（取得の記録のファイル名と sha256）
    書く前に、中身（日の集計・取得の記録の行・マニフェストの行）を privacy_scan.find_in_bytes で
    調べ、メールアドレスの形の文字列があれば書かずに止まる。日の集計は、使ってよい文字
    （英数字・下線・タブ・改行・ハイフン・点・空白・#）だけでできていることも確かめる。
    ログ（標準エラー）には、日付・file_time・結果の種類・件数だけを出し、行の中身は出さない。
    ファイルを削除する処理は無い。

------------------------------------------------------------------------
8. FAT32 の上での検査（T-021）
------------------------------------------------------------------------
    LACIE SHARE と同じ形式（hdiutil の "MS-DOS FAT32"。macOS の msdos のドライバ）のディスクの
    イメージを作り、その上で次を確かめた（2026-10-08。tests/collector/test_gkg.py の
    TestOnFat32 が、環境変数 GKG_FAT32_TEST_VOLUME にイメージのマウント先を渡したときに
    同じことを確かめる）。
      シンボリックリンク：msdos のドライバは、リンクを中身に印を付けたファイルとして作れる。
        lstat は S_ISLNK を返し、O_NOFOLLOW で開くと ELOOP で失敗する。そのため、リンクを
        拒む検査（O_NOFOLLOW、lstat の S_ISDIR・S_ISREG）は FAT32 の上でもそのまま働く。
      i ノード番号：空のファイルの番号は、中身を書くと変わる（作った直後の番号は仮の値）。
        フォルダの番号は、マウントしているあいだは変わらない。マウントし直すと st_dev は
        変わりうる。そのため、ファイルの i ノード番号は検査に使わない。フォルダの
        (st_dev, st_ino) は、1回の実行の中で保存先が変わっていないかを確かめるのにだけ使う
        （_guard_store）。実行をまたいでは比べない。
      リンクの数：ハードリンクは作れない（ENOTSUP）。st_nlink は常に 1 なので、
        write_new_file の「st_nlink が 1」の検査は FAT32 の上では何も止めない（害は無い）。
      大文字と小文字：区別しない。O_EXCL で、大文字と小文字だけが違う名前は FileExistsError に
        なる。このモジュールが書く名前はすべて小文字の英数字と「-」「.」なので、書く名前どうしは
        ぶつからない。保存先のフォルダの名前は、上の 7章のとおり一覧で確かめる。realpath は
        大文字と小文字を正規の形に直さないので、realpath の比較だけには頼らない。
      1ファイルの大きさ：4 GiB − 1 バイトまで。FAT32_MAX_FILE_BYTES を超える日の集計は書かず、
        取得の記録はこの大きさを超える追記をしない（どちらも RunInterrupted）。
      時刻の分解能：2秒（書いた時刻は切り捨てられる）。このモジュールは、ファイルの時刻を
        どの判定にも使わない（日の集計の gzip の時刻は 0 に固定）。
      フォルダの中の項目の数：FAT32 は1つのフォルダに 65,534 項目まで。長い名前は1つの
        ファイルで複数の項目を使う。macOS は、書いたファイルごとに「._」で始まる付属の
        ファイル（拡張属性。AppleDouble）を作る。正式な run は、日の集計 2,115 個と取得の
        記録1つと、それぞれの付属のファイルで、約 21,200 項目の見込み（テストで計算する）。
        付属のファイルは、このモジュールが書くものではなく、中身は macOS の拡張属性だけで
        ある。消さない。
      fsync・O_APPEND・pread：普通に働く。
    マウントが外れている、または読み取り専用なら、何も書かずに止まる（7章）。
    限界
      - 保存先を確かめてから書くまでのあいだに、ディスクを外す・差し替える競合は防げない
        （外れれば書き込みが OSError になり、RunInterrupted で止まる）。行の途中で外れた
        取得の記録は、最後の行に改行が無い形で残り、再開のときに止まる（リードに報告する）。
      - ディスクの形式（FAT32 かどうか）は確かめない。確かめるのは、マウントされていて
        書き込めることだけである。1ファイルの上限は、形式によらず FAT32 の値で止める。

外部のライブラリは使わない（Python 3 の標準ライブラリだけ）。
"""

import datetime
import gzip
import hashlib
import http.client
import importlib.util
import io
import itertools
import json
import os
import re
import secrets
import shutil
import socket
import stat
import sys
import time
import urllib.error
import urllib.request
import zipfile
import zlib
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))


def _load_sibling(name):
    spec = importlib.util.spec_from_file_location(name, os.path.join(HERE, name + ".py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


filelist = _load_sibling("filelist")
privacy_scan = filelist.privacy_scan

# ---------------------------------------------------------------------------
# 1章：期間と対象
# ---------------------------------------------------------------------------

DATA_START = datetime.date(2015, 3, 2)
METHOD_BLOCK_END = datetime.date(2020, 12, 14)
# 行の時刻（14桁）がこれより後なら、ファイルの日の規則で METHOD_BLOCK_END より後になる
# （filelist.LAST_KEPT_TIME と同じ時刻。テストで照合する）。14桁の数字どうしは文字列で比べられる。
LAST_KEPT_TS = b"20201214234500"
METHOD_BLOCK = (DATA_START.isoformat(), METHOD_BLOCK_END.isoformat())

ALLOWED_HOST = "data.gdeltproject.org"
GKG_URL_FMT = "https://data.gdeltproject.org/gdeltv2/%s.gkg.csv.zip"
_GKG_URL_RE = re.compile(r"\Ahttps://data\.gdeltproject\.org/gdeltv2/(\d{14})\.gkg\.csv\.zip\Z")
FILELIST_FIELDS = ("file_time", "file_type", "size_bytes", "md5")
FILELIST_MANIFEST = "gdelt-filelist.jsonl"
FILELIST_STORE_PARTS = ("Desktop", "news-stick-data", "gdelt-filelist")

# ---------------------------------------------------------------------------
# 2章・3章：待ち時間・再試行・上限（公式の値は無い。このプロジェクトが決めた値）
# ---------------------------------------------------------------------------

MIN_REQUEST_INTERVAL_SECONDS = 1.0
REQUEST_TIMEOUT_SECONDS = 60
ATTEMPT_DEADLINE_SECONDS = 900
MAX_ATTEMPTS_PER_FILE = 3
RETRY_WAIT_SECONDS = (30, 120)
MAX_RETRY_AFTER_SECONDS = 900
MAX_CONSECUTIVE_TRANSIENT_FAILURES = 5
MAX_CONSECUTIVE_FORMAT_FAILURES = 10
MAX_INTERRUPTED_RETRIES_PER_RUN = 1
RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})
FINAL_STATUSES = frozenset({403, 404, 410})
READ_ERRORS = (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionError,
               http.client.HTTPException, OSError)
USER_AGENT = "news-digital-stick-chart-collector/0"

MAX_ZIP_BYTES = 200_000_000
MAX_UNZIPPED_BYTES = 1_000_000_000
MAX_LINE_BYTES = 16 * 1024 * 1024
READ_CHUNK_BYTES = 1 << 20
MIN_FREE_DISK_BYTES = 10 * 1024 ** 3
MAX_PAIR_KEYS = 40_000_000

# ---------------------------------------------------------------------------
# 4章：GKG 2.1 の欄と、残す値の形
# ---------------------------------------------------------------------------

GKG_COLUMNS = (
    "GKGRECORDID", "V2.1DATE", "V2SOURCECOLLECTIONIDENTIFIER", "V2SOURCECOMMONNAME",
    "V2DOCUMENTIDENTIFIER", "V1COUNTS", "V2.1COUNTS", "V1THEMES", "V2ENHANCEDTHEMES",
    "V1LOCATIONS", "V2ENHANCEDLOCATIONS", "V1PERSONS", "V2ENHANCEDPERSONS", "V1ORGANIZATIONS",
    "V2ENHANCEDORGANIZATIONS", "V1.5TONE", "V2.1ENHANCEDDATES", "V2GCAM", "V2.1SHARINGIMAGE",
    "V2.1RELATEDIMAGES", "V2.1SOCIALIMAGEEMBEDS", "V2.1SOCIALVIDEOEMBEDS", "V2.1QUOTATIONS",
    "V2.1ALLNAMES", "V2.1AMOUNTS", "V2.1TRANSLATIONINFO", "V2EXTRASXML",
)
N_COLUMNS = len(GKG_COLUMNS)
KEPT_COLUMNS = ("GKGRECORDID", "V2.1DATE", "V2SOURCECOLLECTIONIDENTIFIER", "V1THEMES",
                "V2ENHANCEDTHEMES", "V1LOCATIONS", "V2.1TRANSLATIONINFO")
_I = {name: i for i, name in enumerate(GKG_COLUMNS)}
I_ID, I_D21, I_COLL = _I["GKGRECORDID"], _I["V2.1DATE"], _I["V2SOURCECOLLECTIONIDENTIFIER"]
I_V1T, I_V2T, I_V1LOC = _I["V1THEMES"], _I["V2ENHANCEDTHEMES"], _I["V1LOCATIONS"]
I_TINFO = _I["V2.1TRANSLATIONINFO"]
V1LOCATION_FIELDS = 7      # Type#FullName#CountryCode#ADM1Code#Lat#Long#FeatureID
V1LOCATION_COUNTRY = 2

_ID_RE = re.compile(rb"(\d{14})-(T?)\d{1,12}")
_D14_RE = re.compile(rb"\d{14}")
_COLL_RE = re.compile(rb"[0-9]{1,2}")
THEME_RE = re.compile(rb"[A-Z][A-Z0-9_]{0,159}")
COUNTRY_RE = re.compile(rb"[A-Z]{2}")
LANG_RE = re.compile(rb"[a-z]{3}")
ENG_TOKEN_PATTERNS = (
    rb"GT-[A-Z]{3} [0-9]{1,3}(?:\.[0-9]{1,3}){0,3}",   # GDELT Translingual の言語別のモデル
    rb"Moses [0-9]{1,3}(?:\.[0-9]{1,3}){0,3}",          # Moses の版
    rb"MosesCore Europarl [a-z]{2}-[a-z]{2}",          # Moses のモデル
    rb"Stanford PKU",                                  # 中国語の分かち書き
)
ENG_RE = re.compile(b"(?:" + b"|".join(ENG_TOKEN_PATTERNS) + b")")
NO_LANG = b"-"
OTHER = b"OTHER"
BAD_COLL = b"X"

# 日の集計に使ってよい文字（7章）
OUTPUT_ALPHABET = frozenset(
    b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_\t\n-. #")
DAY_FORMAT = b"gkg-day\t3"          # 版2：頭の行に mode（T-021）。版3：T の行に v1_or_v2_docs、S に docs_without_any_theme（T-035）
DAY_TABLES = ("t1", "t2", "t2m", "t12", "c1", "c2", "c2m", "l1", "l2", "l2m", "p1", "p2",
              "nc", "nl", "eng")

# 7章：保存先（T-021。外付けディスク LACIE SHARE。FAT32）
VOLUME_MOUNT = "/Volumes/LACIE SHARE"
VOLUME_NAME = "LACIE SHARE"
STORE_PARTS = ("news-stick-data", "gkg-method")
TRIAL_STORE_PARTS = ("news-stick-data", "gkg-trial")
STORE_LOCATION_NAME = VOLUME_NAME + ":/" + "/".join(STORE_PARTS)
TRIAL_STORE_LOCATION_NAME = VOLUME_NAME + ":/" + "/".join(TRIAL_STORE_PARTS)
MANIFEST_DIR_PARTS = ("data", "manifest")
MANIFEST_NAME = "gdelt-gkg-method.jsonl"
TRIAL_MANIFEST_NAME = "gdelt-gkg-trial.jsonl"
MODES = ("official", "trial")
# 5.1章：試しの run で取ってよい日（手法を作る期間の最初の3日。これより多くは取れない）
TRIAL_DAYS = ("2015-03-02", "2015-03-03", "2015-03-04")
# 8章：FAT32 の1ファイルの大きさの上限（4 GiB − 1 バイト）と、1つのフォルダの項目の数の上限
FAT32_MAX_FILE_BYTES = 4 * 1024 ** 3 - 1
FAT32_MAX_DIR_ENTRIES = 65_534
CODE_REL = "src/collector/acquire_gkg.py"
_RUN_ID_RE = re.compile(r"\A[0-9a-f]{16}\Z")


class GkgError(Exception):
    """取得・保存の失敗。文には、行の中身・応答の中身・手元のパスを入れない。"""


class GkgFormatError(Exception):
    """1本のファイルの形式の失敗。文は理由の短い名前だけ。"""


class RunInterrupted(Exception):
    """5章の止まる条件。再開できる（同じ run_id）。"""


class RunStartWritten(Exception):
    """正式な run の run-start を書いて止まった（5章）。コミットしてから同じコマンドで再実行する。"""


# ---------------------------------------------------------------------------
# URL と通信
# ---------------------------------------------------------------------------

def gkg_url(file_time):
    url = GKG_URL_FMT % file_time
    validate_gkg_url(url)
    return url


def validate_gkg_url(url):
    if not isinstance(url, str) or not _GKG_URL_RE.match(url):
        raise GkgError("GKG のファイルの URL が決めた形でない")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def build_opener():
    return urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect)


def urllib_transport(url, timeout):
    """既定の通信。応答（.status、.headers.get、.read(n)、.close()）を返す。4xx・5xx も応答として返す。"""
    validate_gkg_url(url)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT,
                                               "Accept-Encoding": "identity"})
    try:
        return build_opener().open(req, timeout=timeout)
    except urllib.error.HTTPError as e:
        return e


class Pacer:
    """要求を送り始める間隔を MIN_REQUEST_INTERVAL_SECONDS 以上にする。"""

    def __init__(self, clock, sleep):
        self.clock, self.sleep, self.last = clock, sleep, None

    def wait(self):
        if self.last is not None:
            gap = self.last + MIN_REQUEST_INTERVAL_SECONDS - self.clock()
            if gap > 0:
                self.sleep(gap)
        self.last = self.clock()


def _retry_after(resp):
    try:
        v = resp.headers.get("Retry-After")
    except Exception:
        return None
    if v is None:
        return None
    v = str(v).strip()
    return int(v) if v.isdigit() else None


def _read_body(resp, clock, deadline):
    buf = bytearray()
    while True:
        if clock() > deadline:
            raise TimeoutError("attempt deadline")
        chunk = resp.read(READ_CHUNK_BYTES)
        if not chunk:
            return bytes(buf)
        buf += chunk
        if len(buf) > MAX_ZIP_BYTES:
            raise GkgFormatError("too_large")


class FetchResult:
    __slots__ = ("result", "reason", "transient", "data", "attempts")

    def __init__(self, result, reason, transient, data, attempts):
        self.result, self.reason, self.transient = result, reason, transient
        self.data, self.attempts = data, attempts


def fetch_file(entry, transport, sleep, clock, pacer, log, used=0, on_attempt=None):
    """1本の zip を取得する（2章の規則）。返り値 FetchResult。data は成功したときだけ。

    used：止まる前に使った試行の回数（5章。再開のときに取得の記録から数える）。
    on_attempt(n)：n 回目の要求を送る直前に呼ぶ（取得の記録に attempt の行を書く）。
    """
    url = gkg_url(entry["file_time"])
    reason, transient = "none", False
    if used >= MAX_ATTEMPTS_PER_FILE:
        return FetchResult("failed", "attempts_exhausted", False, None, used)
    if used > 0:
        wait = RETRY_WAIT_SECONDS[used - 1]
        log("%s：止まる前の試行 %d 回を引き継ぐ。%d 秒待って再試行する（%d/%d）"
            % (entry["file_time"], used, wait, used + 1, MAX_ATTEMPTS_PER_FILE))
        sleep(wait)
    for attempt in range(used + 1, MAX_ATTEMPTS_PER_FILE + 1):
        wait = None
        resp = None
        pacer.wait()
        if on_attempt is not None:
            on_attempt(attempt)
        try:
            resp = transport(url, REQUEST_TIMEOUT_SECONDS)
            status = getattr(resp, "status", None)
            if status is None:
                status = getattr(resp, "code", None)
            if status == 200:
                enc = resp.headers.get("Content-Encoding")
                if enc not in (None, "", "identity"):
                    return FetchResult("failed", "content_encoding", False, None, attempt)
                data = _read_body(resp, clock, clock() + ATTEMPT_DEADLINE_SECONDS)
                if len(data) != entry["size"]:
                    reason, transient = "size_mismatch", False
                elif hashlib.md5(data).hexdigest() != entry["md5"]:
                    reason, transient = "md5_mismatch", False
                else:
                    return FetchResult("ok", "", False, data, attempt)
            elif isinstance(status, int) and status in RETRY_STATUSES:
                reason, transient = "http_%d" % status, True
                ra = _retry_after(resp)
                if ra is not None and ra > MAX_RETRY_AFTER_SECONDS:
                    return FetchResult("failed", "retry_after_too_long", True, None, attempt)
                wait = ra
            elif isinstance(status, int) and status in FINAL_STATUSES:
                return FetchResult("failed", "http_%d" % status, False, None, attempt)
            else:
                return FetchResult("failed", "http_%s" % status, False, None, attempt)
        except GkgFormatError as e:
            return FetchResult("failed", str(e), False, None, attempt)
        except READ_ERRORS as e:
            reason, transient = network_reason(e), True
        finally:
            if resp is not None:
                try:
                    resp.close()
                except Exception:
                    pass
        if attempt == MAX_ATTEMPTS_PER_FILE:
            break
        base = RETRY_WAIT_SECONDS[attempt - 1]
        wait = base if wait is None else max(base, wait)
        log("%s：%s。%d 秒待って再試行する（%d/%d）"
            % (entry["file_time"], reason, wait, attempt + 1, MAX_ATTEMPTS_PER_FILE))
        sleep(wait)
    return FetchResult("failed", reason, transient, None, MAX_ATTEMPTS_PER_FILE)


# ---------------------------------------------------------------------------
# 4章：行の読み取りと、メモリの上での集計
# ---------------------------------------------------------------------------

class Agg:
    """集計の入れ物（15分ファイル1本分、または1日分）。行そのものは持たない。"""

    def __init__(self):
        self.docs = Counter()                      # g -> 文書数
        self.tables = {name: defaultdict(Counter) for name in DAY_TABLES}
        self.stats = Counter()

    def merge(self, other):
        self.docs.update(other.docs)
        for name in DAY_TABLES:
            mine = self.tables[name]
            for g, c in other.tables[name].items():
                mine[g].update(c)
        self.stats.update(other.stats)

    def pair_keys(self):
        return sum(len(c) for name in ("p1", "p2") for c in self.tables[name].values())


def _ts_inside_block(ts):
    """14桁の時刻（bytes）のファイルの日が、DATA_START〜METHOD_BLOCK_END の中なら True。"""
    t = filelist.parse_file_time(ts)
    if t is None:
        return False
    return DATA_START <= filelist.file_day(t) <= METHOD_BLOCK_END


def _vocabs(vocab):
    """名前の辞書を種類ごとに分けて返す（T-032。T-035 の監査 中-1）。

    テーマ・国・言語・ENG の語で別々の辞書を使う。同じ辞書を使うと、先に言語の符号や ENG の語として
    入れた文字列が、テーマの欄では THEME_RE の検査を飛ばしてテーマとして数えられ、その日の数字が、
    同じプロセスで先に処理したファイルに左右される。テーマの辞書には THEME_RE に合った名前だけが入る。
    """
    return (vocab.setdefault("theme", {}), vocab.setdefault("country", {}),
            vocab.setdefault("lang", {}), vocab.setdefault("eng", {}))


def add_line(agg, line, file_time_b, vocab):
    """1行を読み、4章の許可リストの値だけを集計に加える。一覧にない欄はここで捨てる。"""
    tvocab, cvocab, lvocab, evocab = _vocabs(vocab)
    st = agg.stats
    if line.endswith(b"\n"):
        line = line[:-1]
    if line.endswith(b"\r"):
        line = line[:-1]
    if not line:
        st["rows"] += 1
        st["rows_empty"] += 1
        return
    f = line.split(b"\t")
    if len(f) != N_COLUMNS:
        st["rows"] += 1
        st["rows_bad_columns"] += 1
        return
    rid, d21, coll = f[I_ID], f[I_D21], f[I_COLL]
    v1t, v2t, v1loc, tinfo = f[I_V1T], f[I_V2T], f[I_V1LOC], f[I_TINFO]
    del f, line                                    # 残りの20欄は、ここで手放す
    m = _ID_RE.fullmatch(rid)
    if m is None:
        st["rows"] += 1
        st["rows_bad_id"] += 1
        return
    ts, tmark = m.group(1), m.group(2)
    if ts != file_time_b:
        if ts > LAST_KEPT_TS:
            return          # 区画の後ろの時刻の行：数えずに捨てる（どの件数にも入れない）
        st["rows"] += 1
        st["rows_id_time_differs"] += 1
        if not _ts_inside_block(ts):
            st["rows_id_time_before_block"] += 1
            return
    else:
        st["rows"] += 1
    if d21 == file_time_b:
        st["d21_same_as_file"] += 1
    elif d21 == b"0":
        st["d21_zero"] += 1
    elif _D14_RE.fullmatch(d21):
        st["d21_other"] += 1
    else:
        st["d21_invalid"] += 1
    g = (coll if _COLL_RE.fullmatch(coll) else BAD_COLL) + tmark
    if tmark:
        st["docs_translated_mark"] += 1

    s1 = set()
    if v1t:
        for t in v1t.split(b";"):
            if not t:
                continue
            c = tvocab.get(t)
            if c is None:
                if THEME_RE.fullmatch(t) is None:
                    st["theme_tokens_invalid_v1"] += 1
                    continue
                c = tvocab.setdefault(t, t)
            s1.add(c)
    m2 = Counter()
    if v2t:
        for blk in v2t.split(b";"):
            if not blk:
                continue
            t = blk.partition(b",")[0]
            c = tvocab.get(t)
            if c is None:
                if THEME_RE.fullmatch(t) is None:
                    st["theme_tokens_invalid_v2"] += 1
                    continue
                c = tvocab.setdefault(t, t)
            m2[c] += 1
    s2 = set(m2)
    cs = set()
    if v1loc:
        for blk in v1loc.split(b";"):
            if not blk:
                continue
            parts = blk.split(b"#")
            if len(parts) != V1LOCATION_FIELDS:
                st["location_blocks_invalid"] += 1
                continue
            cc = parts[V1LOCATION_COUNTRY]
            if COUNTRY_RE.fullmatch(cc):
                cs.add(cvocab.setdefault(cc, cc))
            else:
                st["country_codes_invalid"] += 1
    lang = NO_LANG
    engs = set()
    if tinfo:
        for part in tinfo.split(b";"):
            part = part.strip()
            if not part:
                continue
            key, _sep, val = part.partition(b":")
            key = key.strip().lower()
            val = val.strip()
            if key == b"srclc":
                if LANG_RE.fullmatch(val):
                    lang = lvocab.setdefault(val, val)
                else:
                    lang = OTHER
                    st["srclc_other"] += 1
            elif key == b"eng":
                for tok in val.split(b"/"):
                    tok = tok.strip()
                    if not tok:
                        continue
                    if ENG_RE.fullmatch(tok):
                        engs.add(evocab.setdefault(tok, tok))
                    else:
                        st["eng_other_tokens"] += 1
            else:
                st["translationinfo_other_parts"] += 1

    agg.docs[g] += 1
    T = agg.tables
    if not s1:
        st["docs_without_v1_theme"] += 1
    if not s2:
        st["docs_without_v2_theme"] += 1
    if not s1 and not s2:
        st["docs_without_any_theme"] += 1
    if not cs:
        st["docs_without_country"] += 1
    T["t1"][g].update(s1)
    T["t2"][g].update(s2)
    T["t2m"][g].update(m2)
    # 正式な数え方（2026-10-08 オーナー決定）の分子：V1THEMES か V2ENHANCEDTHEMES の少なくとも
    # 一方に付いた文書の数。同じ文書で両方に付いても1回。同じテーマかは名前のバイト列の一致で決める
    T["t12"][g].update(s1 | s2)
    if cs:
        T["c1"][g].update((t, c) for t in s1 for c in cs)
        T["c2"][g].update((t, c) for t in s2 for c in cs)
        T["c2m"][g].update({(t, c): n for t, n in m2.items() for c in cs})
        T["nc"][g].update(cs)
    T["l1"][g].update((t, lang) for t in s1)
    T["l2"][g].update((t, lang) for t in s2)
    T["l2m"][g].update({(t, lang): n for t, n in m2.items()})
    T["nl"][g][lang] += 1
    if len(s1) > 1:
        T["p1"][g].update(itertools.combinations(sorted(s1), 2))
    if len(s2) > 1:
        T["p2"][g].update(itertools.combinations(sorted(s2), 2))
    if engs:
        T["eng"][g].update(engs)


def aggregate_zip(data, file_time, vocab):
    """メモリの上の zip を1行ずつ展開して集計する（3章・4章）。形が違えば GkgFormatError。"""
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
        infos = zf.infolist()
    except (zipfile.BadZipFile, zipfile.LargeZipFile, ValueError, EOFError):
        raise GkgFormatError("zip") from None
    if len(infos) != 1:
        raise GkgFormatError("zip_members")
    info = infos[0]
    if info.is_dir() or info.filename.lower() != (file_time + ".gkg.csv"):
        raise GkgFormatError("zip_member_name")
    if info.flag_bits & 0x1:
        raise GkgFormatError("zip_encrypted")
    if info.file_size > MAX_UNZIPPED_BYTES:
        raise GkgFormatError("too_large_unzipped")
    ftb = file_time.encode("ascii")
    agg = Agg()
    total = 0
    try:
        with zf.open(info) as fp:
            while True:
                line = fp.readline(MAX_LINE_BYTES + 1)
                if not line:
                    break
                total += len(line)
                if total > MAX_UNZIPPED_BYTES:
                    raise GkgFormatError("too_large_unzipped")
                if len(line) > MAX_LINE_BYTES and not line.endswith(b"\n"):
                    while line and not line.endswith(b"\n"):
                        line = fp.readline(MAX_LINE_BYTES + 1)
                        total += len(line)
                        if total > MAX_UNZIPPED_BYTES:
                            raise GkgFormatError("too_large_unzipped")
                    agg.stats["rows"] += 1
                    agg.stats["rows_too_long"] += 1
                    continue
                add_line(agg, line, ftb, vocab)
    except (zipfile.BadZipFile, EOFError, ValueError, OSError, NotImplementedError):
        raise GkgFormatError("zip_read") from None
    return agg


# ---------------------------------------------------------------------------
# 1章：ファイル一覧の読み取りと、対象の選び方
# ---------------------------------------------------------------------------

def parse_filelist(data):
    """T-016 の本体（見出しつきの TSV）を読み、(file_time, file_type, size, md5) の list を返す。"""
    lines = data.split(b"\n")
    if lines[-1] != b"" or lines[0] != "\t".join(FILELIST_FIELDS).encode("ascii"):
        raise GkgError("ファイル一覧の見出しか終わりの形が違う")
    out = []
    for raw in lines[1:-1]:
        f = raw.split(b"\t")
        if (len(f) != 4 or not re.fullmatch(rb"\d{14}", f[0])
                or f[1] not in (b"export", b"mentions", b"gkg")
                or not re.fullmatch(rb"[0-9]{1,15}", f[2])
                or not re.fullmatch(rb"[0-9a-f]{32}", f[3])):
            raise GkgError("ファイル一覧に形の違う行がある")
        out.append((f[0].decode(), f[1].decode(), int(f[2]), f[3].decode()))
    return out


def select_files(rows):
    """1章の規則。返り値：{日付の文字列: [entry, ...]}（日付の順、各日は file_time の順）。

    entry = {"file_time", "size", "md5", "ambiguous"}。
    """
    by_time = {}
    for ft, kind, size, md5 in rows:
        if kind != "gkg":
            continue
        t = filelist.parse_file_time(ft)
        if t is None:
            continue
        day = filelist.file_day(t)
        if not (DATA_START <= day <= METHOD_BLOCK_END):
            continue
        by_time.setdefault(ft, (day, set()))[1].add((size, md5))
    days = {}
    for ft in sorted(by_time):
        day, variants = by_time[ft]
        (size, md5) = sorted(variants)[0]
        days.setdefault(day.isoformat(), []).append(
            {"file_time": ft, "size": size, "md5": md5, "ambiguous": len(variants) > 1})
    return dict(sorted(days.items()))


# ---------------------------------------------------------------------------
# 7章：保存先とマニフェスト
# ---------------------------------------------------------------------------

def _inside_git_worktree(path_real):
    d = path_real
    while True:
        if os.path.lexists(os.path.join(d, ".git")):
            return True
        parent = os.path.dirname(d)
        if parent == d:
            return False
        d = parent


def check_volume(volume):
    """7章：保存先のディスクがマウントされていて、書き込めることを確かめる。返り値：st_dev。

    何も書かない。つながっていない・マウントされていない・読み取り専用なら GkgError。
    """
    try:
        st = os.lstat(volume)
    except OSError:
        raise GkgError("保存先のディスク %s がつながっていない（マウントされていない）"
                       % VOLUME_NAME) from None
    if not stat.S_ISDIR(st.st_mode):
        raise GkgError("保存先のディスク %s のマウント先が、シンボリックリンクかフォルダでない"
                       % VOLUME_NAME)
    if not os.path.ismount(volume):
        raise GkgError("保存先のディスク %s がマウントされていない（マウント先の場所に、普通の"
                       "フォルダがあるだけ）" % VOLUME_NAME)
    try:
        sv = os.statvfs(volume)
    except OSError:
        raise GkgError("保存先のディスク %s の状態を読めない" % VOLUME_NAME) from None
    if sv.f_flag & os.ST_RDONLY:
        raise GkgError("保存先のディスク %s が読み取り専用でマウントされている" % VOLUME_NAME)
    return st.st_dev


def store_spec(mode):
    """mode ごとの (保存先のフォルダの2段, store_location の名前, マニフェストの名前)。"""
    if mode == "official":
        return STORE_PARTS, STORE_LOCATION_NAME, MANIFEST_NAME
    if mode == "trial":
        return TRIAL_STORE_PARTS, TRIAL_STORE_LOCATION_NAME, TRIAL_MANIFEST_NAME
    raise GkgError("mode は official か trial だけ")


def resolve_paths(root, volume, mode="official", check_volume=check_volume):
    """保存先（Git の外。外付けディスク）とマニフェストの場所を確かめて返す（7章）。

    フォルダは作らない。何も書かない。volume は本番では VOLUME_MOUNT（入口のスクリプトが固定）。
    """
    parts, location, manifest_name = store_spec(mode)
    dev = check_volume(volume)
    root_real = os.path.realpath(root)
    d = volume
    for depth, name in enumerate(parts, 1):
        parent, d = d, os.path.join(d, name)
        label = VOLUME_NAME + ":/" + "/".join(parts[:depth])
        try:
            st = os.lstat(d)
        except OSError:
            raise GkgError("保存先のフォルダ %s が無い（オーナーが前もって作る）" % label) from None
        if not stat.S_ISDIR(st.st_mode):
            raise GkgError("保存先 %s が、シンボリックリンクかフォルダでない" % label)
        try:
            names = os.listdir(parent)
        except OSError:
            raise GkgError("保存先 %s の親のフォルダの一覧を読めない" % label) from None
        if name not in names:
            raise GkgError("保存先 %s の名前の大文字と小文字が、決めた名前と違う" % label)
    store_real = os.path.realpath(d)
    if store_real != os.path.join(os.path.realpath(volume), *parts):
        raise GkgError("保存先の実際の場所が、ディスクの下の決めた場所でない（途中にリンクがある）")
    sst = os.stat(store_real)
    if sst.st_dev != dev:
        raise GkgError("保存先のフォルダが、ディスク %s の上に無い" % VOLUME_NAME)
    if store_real == root_real or store_real.startswith(root_real + os.sep):
        raise GkgError("保存先がプロジェクトの下にある（Git の外に置く）")
    if _inside_git_worktree(store_real):
        raise GkgError("保存先が Git の作業ツリーの中にある（Git の外に置く）")
    mdir = os.path.join(root, *MANIFEST_DIR_PARTS)
    for mparts in (MANIFEST_DIR_PARTS[:1], MANIFEST_DIR_PARTS):
        p = os.path.join(root, *mparts)
        if os.path.islink(p) or not os.path.isdir(p):
            raise GkgError("マニフェストのフォルダが、リンクかフォルダでない")
    if os.path.realpath(mdir) != os.path.join(root_real, *MANIFEST_DIR_PARTS):
        raise GkgError("マニフェストのフォルダの実際の場所がプロジェクトの下でない")
    return {"mode": mode, "store": store_real, "store_id": (sst.st_dev, sst.st_ino),
            "volume": volume, "check_volume": check_volume, "location": location,
            "manifest": os.path.join(root_real, *MANIFEST_DIR_PARTS, manifest_name),
            "official_manifest": os.path.join(root_real, *MANIFEST_DIR_PARTS, MANIFEST_NAME),
            "trial_manifest": os.path.join(root_real, *MANIFEST_DIR_PARTS, TRIAL_MANIFEST_NAME)}


def _guard_store(paths):
    """保存先に書く直前の検査（7章・8章）。違えば書かずに RunInterrupted で止まる。"""
    try:
        dev = paths["check_volume"](paths["volume"])
        st = os.lstat(paths["store"])
    except (GkgError, OSError):
        raise RunInterrupted("保存先のディスク %s が外れたか、読み取り専用になった（書かずに"
                             "止めた）" % VOLUME_NAME) from None
    if (not stat.S_ISDIR(st.st_mode) or st.st_dev != dev
            or (st.st_dev, st.st_ino) != paths["store_id"]):
        raise RunInterrupted("保存先のフォルダが、確かめたときと違うものになった（書かずに止めた）")


def _open_append(path):
    try:
        fd = os.open(path, os.O_RDWR | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC,
                     0o644)
    except OSError:
        raise GkgError("追記するファイルを開けない（シンボリックリンクなど）") from None
    st = os.fstat(fd)
    if not stat.S_ISREG(st.st_mode):
        os.close(fd)
        raise GkgError("追記するファイルが通常のファイルでない")
    if st.st_size and os.pread(fd, 1, st.st_size - 1) != b"\n":
        os.close(fd)
        raise GkgError("追記するファイルの最後の行に改行が無い")
    return fd


def _write_all(fd, data):
    view = memoryview(data)
    while view:
        n = os.write(fd, view)
        view = view[n:]


def _check_no_address(data, what):
    if privacy_scan.find_in_bytes(data):
        raise GkgError("%s にメールアドレスの形の文字列があるので書かずに止まる" % what)


def append_jsonl(path, obj, what, max_bytes=None):
    """1行を追記する。max_bytes を渡したときは、追記したあとの大きさがそれを超えるなら書かない。"""
    line = (json.dumps(obj, sort_keys=True, ensure_ascii=True) + "\n").encode("ascii")
    _check_no_address(line, what)
    fd = _open_append(path)
    try:
        if max_bytes is not None and os.fstat(fd).st_size + len(line) > max_bytes:
            raise RunInterrupted("%s が FAT32 の1ファイルの大きさの上限を超えるので、書かずに"
                                 "止めた（リードに報告）" % what)
        _write_all(fd, line)
        os.fsync(fd)
    finally:
        os.close(fd)


def append_store_jsonl(paths, path, obj, what):
    """保存先（外付けディスク）の取得の記録に1行を追記する。書く前に _guard_store。"""
    _guard_store(paths)
    try:
        append_jsonl(path, obj, what, FAT32_MAX_FILE_BYTES)
    except OSError:
        raise RunInterrupted("保存先に書けなかった（ディスクが外れたなど）。%s の最後の行が"
                             "途中で切れていれば、再開のときに止まる（リードに報告）" % what) from None


def read_jsonl(path):
    """無ければ空の list。O_NOFOLLOW で読む。"""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    except FileNotFoundError:
        return []
    except OSError:
        raise GkgError("記録のファイルを開けない（シンボリックリンクなど）") from None
    with os.fdopen(fd, "rb") as f:
        data = f.read()
    out = []
    for raw in data.splitlines():
        if raw.strip():
            try:
                out.append(json.loads(raw))
            except ValueError:
                raise GkgError("記録のファイルに JSON でない行がある") from None
    return out


def read_bytes_nofollow(path):
    """無ければ b""。O_NOFOLLOW で読む。"""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    except FileNotFoundError:
        return b""
    except OSError:
        raise GkgError("記録のファイルを開けない（シンボリックリンクなど）") from None
    with os.fdopen(fd, "rb") as f:
        return f.read()


def write_new_file(store, name, data):
    """保存先に新しいファイルを書く。返り値：(sha256, 空のファイルを埋めたか)。

    同じ名前があれば、中身が同じときだけ書かずに認める。0バイトのファイルがあれば（作った直後に
    止まった跡。7章）、それに書き足す。中身のある違うファイルがあれば止まる（上書きしない）。
    """
    if len(data) > FAT32_MAX_FILE_BYTES:
        raise RunInterrupted("%s が FAT32 の1ファイルの大きさの上限を超えるので、書かずに止めた"
                             "（リードに報告）" % name)
    path = os.path.join(store, name)
    sha = hashlib.sha256(data).hexdigest()
    try:
        fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                     0o644)
    except FileExistsError:
        return _existing_file(path, data, sha)
    try:
        st = os.fstat(fd)
        # st_nlink は FAT32 では常に 1（8章）。APFS などでの検査として残す
        if not stat.S_ISREG(st.st_mode) or st.st_nlink != 1:
            raise GkgError("書いたものが通常のファイルでない")
        _write_all(fd, data)
        os.fsync(fd)
        os.lseek(fd, 0, os.SEEK_SET)
        h = hashlib.sha256()
        while True:
            chunk = os.read(fd, 1 << 20)
            if not chunk:
                break
            h.update(chunk)
        if h.hexdigest() != sha:
            raise GkgError("書いたファイルの sha256 が一致しない")
    finally:
        os.close(fd)
    return sha, False


def _existing_file(path, data, sha):
    try:
        fd = os.open(path, os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC)
    except OSError:
        raise GkgError("同じ名前のものがあり、通常のファイルとして開けない") from None
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode):
            raise GkgError("同じ名前のものがあり、通常のファイルでない")
        if st.st_size == 0:
            # 0バイト：作った直後（書く前）に止まった跡。消さずに、そこへ書き足す（7章）
            _write_all(fd, data)
            os.fsync(fd)
            os.lseek(fd, 0, os.SEEK_SET)
            if hashlib.sha256(_read_all(fd)).hexdigest() != sha:
                raise GkgError("書いたファイルの sha256 が一致しない")
            return sha, True
        if hashlib.sha256(_read_all(fd)).hexdigest() != sha:
            raise GkgError("同じ名前で中身の違うファイルが既にある（上書きしない。リードに報告）")
        return sha, False
    finally:
        os.close(fd)


def _read_all(fd):
    out = bytearray()
    while True:
        chunk = os.read(fd, 1 << 20)
        if not chunk:
            return bytes(out)
        out += chunk


# ---------------------------------------------------------------------------
# 6章：日の集計の書き方
# ---------------------------------------------------------------------------

def _b(n):
    return b"%d" % n


def serialize_day(day, agg, files, mode="official"):
    """6章の形のバイト列（gzip の前）。行の順はすべて決まった並べ方。頭の行に mode を書く。"""
    store_spec(mode)
    out = [b"#\t" + DAY_FORMAT + b"\t" + day.encode("ascii") + b"\t" + mode.encode("ascii")]
    for f in files:
        out.append(b"\t".join([b"F", f["file_time"].encode(), f["result"].encode(),
                               (f["reason"] or "-").encode(), f["md5"].encode(),
                               _b(f["size"]), (f["sha256"] or "-").encode(),
                               _b(f["attempts"]), _b(sum(f["docs"].values()))]))
    for f in files:
        for g in sorted(f["docs"]):
            out.append(b"\t".join([b"FD", f["file_time"].encode(), g.encode(),
                                   _b(f["docs"][g])]))
    T = agg.tables
    names = set()
    for key in ("t1", "t2"):
        for c in T[key].values():
            names.update(c)
    ids = {t: i for i, t in enumerate(sorted(names))}
    for t, i in sorted(ids.items(), key=lambda x: x[1]):
        out.append(b"V\t" + _b(i) + b"\t" + t)
    for g in sorted(agg.docs):
        out.append(b"D\t" + g + b"\t" + _b(agg.docs[g]))
    groups = sorted(set(agg.docs))
    for g in groups:
        t1, t2, t2m = T["t1"].get(g, {}), T["t2"].get(g, {}), T["t2m"].get(g, {})
        t12 = T["t12"].get(g, {})
        for t in sorted(set(t1) | set(t2), key=ids.get):
            out.append(b"\t".join([b"T", g, _b(ids[t]), _b(t1.get(t, 0)), _b(t2.get(t, 0)),
                                   _b(t2m.get(t, 0)), _b(t12.get(t, 0))]))
    for tag, k1, k2, km in ((b"C", "c1", "c2", "c2m"), (b"L", "l1", "l2", "l2m")):
        for g in groups:
            a, b, m = T[k1].get(g, {}), T[k2].get(g, {}), T[km].get(g, {})
            for t, x in sorted(set(a) | set(b), key=lambda k: (ids[k[0]], k[1])):
                out.append(b"\t".join([tag, g, _b(ids[t]), x, _b(a.get((t, x), 0)),
                                       _b(b.get((t, x), 0)), _b(m.get((t, x), 0))]))
    for tag, key in ((b"P1", "p1"), (b"P2", "p2")):
        for g in groups:
            c = T[key].get(g, {})
            for (a, b2), n in sorted(((ids[a], ids[b2]), n) for (a, b2), n in c.items()):
                out.append(b"\t".join([tag, g, _b(a), _b(b2), _b(n)]))
    for tag, key in ((b"NC", "nc"), (b"NL", "nl"), (b"E", "eng")):
        for g in groups:
            for x, n in sorted(T[key].get(g, {}).items()):
                out.append(b"\t".join([tag, g, x, _b(n)]))
    for name, n in sorted(agg.stats.items()):
        out.append(b"S\t" + name.encode("ascii") + b"\t" + _b(n))
    return b"\n".join(out) + b"\n"


def check_output_bytes(data, what):
    """7章：使ってよい文字だけか、メールアドレスの形が無いかを確かめる。"""
    if data.translate(None, bytes(OUTPUT_ALPHABET)):
        raise GkgError("%s に、使ってよい文字の外の文字がある" % what)
    _check_no_address(data, what)


def gzip_bytes(data):
    return gzip.compress(data, compresslevel=6, mtime=0)


def day_file_name(run_id, day, mode="official"):
    """日の集計の名前。mode（official・trial）を名前に入れる（T-021 の差し戻し1回目 中2）。"""
    store_spec(mode)
    return "gkg-%s-%s-day-%s.tsv.gz" % (mode, run_id, day.replace("-", ""))


def fetch_log_name(run_id, mode="official"):
    """取得の記録の名前。mode を名前に入れる。"""
    store_spec(mode)
    return "gkg-%s-%s-fetch-log.jsonl" % (mode, run_id)


# ---------------------------------------------------------------------------
# 5章：取得の全体
# ---------------------------------------------------------------------------

def _iso(dt):
    return dt.astimezone(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _stderr_log(msg):
    print("gkg: " + msg, file=sys.stderr)


def _disk_free(path):
    return shutil.disk_usage(path).free


def official_run_id(manifest):
    """正式な run の run_id（マニフェストの最初の run-start）。run-start が無ければ None。"""
    for e in manifest:
        if e.get("kind") == "run-start":
            return e.get("run_id")
    return None


def official_day_records(manifest):
    """正式な run の day の行（日付の順）。欠けた日の一覧は、これと日の集計の F の行から作る。

    正式な run が run-complete まで終わっていなければ GkgError。
    """
    rid = official_run_id(manifest)
    if rid is None:
        raise GkgError("run-start が無い")
    mine = [e for e in manifest if e.get("run_id") == rid]
    if not any(e.get("kind") == "run-complete" for e in mine):
        raise GkgError("正式な run が終わっていない")
    days = {}
    for e in mine:
        if e.get("kind") == "day":
            if e["day"] in days:
                raise GkgError("正式な run に同じ日の day の行が二つある")
            days[e["day"]] = e
    return [days[d] for d in sorted(days)]


def trial_plan(plan):
    """5.1章：試しの run の日（TRIAL_DAYS）だけの plan。手法を作る期間の外の日は入れない。"""
    for d in TRIAL_DAYS:
        if not (DATA_START.isoformat() <= d <= METHOD_BLOCK_END.isoformat()):
            raise GkgError("試しの run の日が、手法を作る期間の外にある")
    out = {d: plan[d] for d in TRIAL_DAYS if d in plan}
    if not out:
        raise GkgError("試しの run の日が、ファイル一覧に1日も無い")
    return out


def check_committed_start(manifest_bytes, committed):
    """5章：正式な run の最初の run-start がコミットされていることを確かめる。

    committed は HEAD のマニフェストのバイト列（無ければ b""）。入口のスクリプトが git から読む。
    """
    if not isinstance(committed, bytes):
        raise GkgError("HEAD のマニフェストを受け取っていない（入口のスクリプトから実行する）")
    if committed and not committed.endswith(b"\n"):
        raise GkgError("HEAD のマニフェストの最後の行に改行が無い")
    if not manifest_bytes.startswith(committed):
        raise GkgError("マニフェストの、コミットした部分が書き換わっている（追記だけを認める）")
    end = 0
    for raw in manifest_bytes.splitlines(keepends=True):
        end += len(raw)
        if not raw.strip():
            continue
        try:
            kind = json.loads(raw).get("kind")
        except ValueError:
            raise GkgError("マニフェストに JSON でない行がある") from None
        if kind == "run-start":
            if end > len(committed):
                raise GkgError("正式な run の run-start がコミットされていない。マニフェストを"
                               "コミットしてから、同じコマンドでもう一度実行する")
            return
    raise GkgError("マニフェストに run-start が無い")


def _log_state(log_path):
    """取得の記録の今の (大きさ, sha256)。無ければ (0, 空のバイト列の sha256)。"""
    data = read_bytes_nofollow(log_path)
    return len(data), hashlib.sha256(data).hexdigest()


def check_log_checkpoint(log_path, mine):
    """5.2章：取得の記録を、マニフェストに書いた最後の控えと照らす。返り値：控えの大きさ。

    - 取得の記録の先頭から控えの大きさまでの sha256 が、控えと一致すること。
    - 最後の控えが run-start か run-stop（きちんと止まった）なら、取得の記録の大きさが
      控えとちょうど同じであること（止まったあとに足した行・写した記録を拒む。差し戻し2回目 中-A）。
    違えば GkgError（run と run のあいだの書き換え）。
    """
    last = None
    for e in mine:
        if "fetch_log_size" in e:
            last = e
    if last is None:
        raise GkgError("マニフェストに、取得の記録の大きさと sha256 の行が無い")
    data = read_bytes_nofollow(log_path)
    size = last["fetch_log_size"]
    if len(data) < size or hashlib.sha256(data[:size]).hexdigest() != last["fetch_log_sha256"]:
        raise GkgError("取得の記録が、マニフェストに書いた時点（%s）から書き換わっている"
                       "（行を消した・差し替えたなど。リードに報告）" % last.get("kind"))
    if last.get("kind") in ("run-start", "run-stop") and len(data) != size:
        raise GkgError("取得の記録に、止まったあと（%s のあと）で足した行がある（リードに報告）"
                       % last.get("kind"))
    return size


# 5.2章（T-026 軽-4・T-030 軽-D）：network_ のあとに書く・認める例外の名前の一覧。固定する
# （Python の版や import の順で変わらないようにするため）。一覧に無い例外は network_Other と書く。
NETWORK_ERROR_NAMES = frozenset({
    "URLError", "ContentTooShortError", "TimeoutError", "timeout", "OSError", "ConnectionError",
    "ConnectionResetError", "ConnectionRefusedError", "ConnectionAbortedError", "BrokenPipeError",
    "HTTPException", "IncompleteRead", "RemoteDisconnected", "BadStatusLine", "LineTooLong",
    "gaierror", "herror", "SSLError", "SSLEOFError", "SSLZeroReturnError", "SSLSyscallError",
    "SSLCertVerificationError", "Other",
})


def network_reason(exc):
    """通信の失敗の reason。例外の名前が NETWORK_ERROR_NAMES に無ければ network_Other。"""
    name = type(exc).__name__
    return "network_" + (name if name in NETWORK_ERROR_NAMES else "Other")


_FORMAT_REASONS = frozenset({"zip", "zip_members", "zip_member_name", "zip_encrypted",
                             "too_large_unzipped", "zip_read"})
_FIXED_REASONS = frozenset({"", "retry_after_too_long", "attempts_exhausted", "ambiguous_listing",
                            "content_encoding", "size_mismatch", "md5_mismatch", "too_large",
                            "consecutive_transient_failures"})
_HTTP_REASON_RE = re.compile(r"\Ahttp_(?:[0-9]{3}|None)\Z")
_RESULTS = frozenset({"ok", "failed", "interrupted"})


def valid_reason(reason):
    """reason が、このモジュールが書く決まった語の形なら True。"""
    if not isinstance(reason, str):
        return False
    if reason in _FIXED_REASONS or _HTTP_REASON_RE.match(reason):
        return True
    if reason.startswith("network_"):
        return reason[len("network_"):] in NETWORK_ERROR_NAMES
    if reason.startswith("format_"):
        return reason[len("format_"):] in _FORMAT_REASONS
    return False


def _check_log_lines(entries, run_id, mode):
    """取得の記録の行が、どれもこの run_id と mode のもので、決まった形であること。

    中2：run_id と mode。T-026 軽-4：結果の行（ok・failed・interrupted）の reason が決まった語で、
    attempts が 0〜MAX_ATTEMPTS_PER_FILE の整数であること。attempt の行の attempt が
    1〜MAX_ATTEMPTS_PER_FILE の整数であること。file_time が14桁の数字であること。合わなければ
    止まる（day の行の failed_files に、決まった形でない語や数が載らないようにするため）。
    """
    for e in entries:
        if e.get("run_id") != run_id or e.get("mode") != mode:
            raise GkgError("取得の記録に、別の run か別の mode（試しの run と正式な run）の行がある")
        ft = e.get("file_time")
        if not (isinstance(ft, str) and re.fullmatch(r"[0-9]{14}", ft)):
            raise GkgError("取得の記録に、file_time の形が違う行がある（リードに報告）")
        result = e.get("result")
        if result == "attempt":
            n = e.get("attempt")
            if type(n) is not int or not 1 <= n <= MAX_ATTEMPTS_PER_FILE:
                raise GkgError("取得の記録の attempt の行の回数の形が違う（リードに報告）")
        elif result in _RESULTS:
            n = e.get("attempts")
            if type(n) is not int or not 0 <= n <= MAX_ATTEMPTS_PER_FILE:
                raise GkgError("取得の記録の結果の行の attempts の形が違う（リードに報告）")
            if not valid_reason(e.get("reason")):
                raise GkgError("取得の記録の結果の行の reason が、決まった語でない（リードに報告）")
        else:
            raise GkgError("取得の記録に、知らない result の行がある（リードに報告）")


def chain_exclusion_ref(root):
    """鎖の上の除外の規則の封印の記録の {"seq", "record_sha256"}（themes の関門をもう一度通す）。"""
    themes = _load_sibling("themes")
    try:
        rec, gate_root = themes.require_exclusion_rules_sealed()
    except themes.ThemesError as e:
        raise GkgError("除外の規則の封印の関門：%s" % e) from None
    if os.path.realpath(gate_root) != os.path.realpath(root):
        raise GkgError("除外の規則の関門が読んだプロジェクトが、root と違う")
    return themes.exclusion_rule_ref(rec)


_MARK_RE = re.compile(rb"\A[0-9a-f]{64}\n\Z")


def volume_mark_name(run_id, mode="official"):
    """5.2章：ディスクの同一性の印のファイルの名前（保存先のフォルダの中。Git に入らない）。"""
    store_spec(mode)
    return "gkg-%s-%s-volume-mark" % (mode, run_id)


def write_volume_mark(paths, run_id, mode):
    """5.2章：run を始めるときに、乱数の印を保存先に書く。値はどの記録にも書かない。"""
    _guard_store(paths)
    path = os.path.join(paths["store"], volume_mark_name(run_id, mode))
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                     0o644)
    except FileExistsError:
        raise GkgError("run-start の前なのに、ディスクの印のファイルが既にある（リードに報告）") from None
    except OSError:
        raise GkgError("ディスクの印のファイルを書けない") from None
    try:
        _write_all(fd, (secrets.token_hex(32) + "\n").encode("ascii"))
        os.fsync(fd)
    finally:
        os.close(fd)


def check_volume_mark(paths, run_id, mode):
    """5.2章：再開のときに、印のファイルが保存先にあり、決めた形であることを確かめる。"""
    path = os.path.join(paths["store"], volume_mark_name(run_id, mode))
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    except OSError:
        raise GkgError("保存先にディスクの印のファイルが無い（run-start のときと違うディスク。"
                       "リードに報告）") from None
    with os.fdopen(fd, "rb") as f:
        if not stat.S_ISREG(os.fstat(f.fileno()).st_mode):
            raise GkgError("ディスクの印のファイルが通常のファイルでない")
        data = f.read(200)
    if not _MARK_RE.match(data):
        raise GkgError("ディスクの印のファイルの形が違う（リードに報告）")


def check_exclusion_record(root, ref, s0):
    """5.3章（差し戻し2回目 中-B）：渡された除外の規則の封印の記録が、鎖の上の記録であること。

    themes.require_exclusion_rules_sealed() を、ここでもう一度呼んで照らす（関門と同じ検査）。
    再開のときは、run-start に書いた seq と sha256 とも同じであること。
    """
    if not isinstance(ref, dict) or set(ref) != {"seq", "record_sha256"}:
        raise GkgError("除外の規則の封印の記録を受け取っていない（入口のスクリプトから実行する）")
    if chain_exclusion_ref(root) != ref:
        raise GkgError("渡された除外の規則の封印の記録が、鎖の上の記録と違う")
    if s0 is not None and (s0.get("exclusion_rule_seq"), s0.get("exclusion_rule_record_sha256")) \
            != (ref["seq"], ref["record_sha256"]):
        raise GkgError("除外の規則の封印の記録が、run-start に書いたものと違う")


_STORE_KINDS = r"(?:day-\d{8}\.tsv\.gz|fetch-log\.jsonl|volume-mark)"


def check_store_listing(store, mode, run_id=None):
    """5.4章（差し戻し3回目 中-1・中-2）：保存先のフォルダの一覧を照らす。返り値：run_id の集合。

    許す名前は、決まった形の名前（mode が official なら run_id もこの run のもの）と、
    「._」にその名前を続けたもの（macOS の付属のファイル）だけ。どれも通常のファイルで
    なければならない。ほかの名前（「.」で始まるほかの名前・フォルダ・リンク）があれば止まる。
    """
    rid = re.escape(run_id) if run_id is not None else "([0-9a-f]{16})"
    if run_id is not None:
        rid = "(" + rid + ")"
    pat = re.compile(r"\Agkg-%s-%s-%s\Z" % (re.escape(mode), rid, _STORE_KINDS))
    ids = set()
    for name in sorted(os.listdir(store)):
        base = name[2:] if name.startswith("._") else name
        m = pat.match(base)
        st = os.lstat(os.path.join(store, name))
        if m is None or not stat.S_ISREG(st.st_mode):
            raise GkgError("保存先（%s）に、決まった名前でないもの（「.」で始まる名前・フォルダ・"
                           "リンクを含む）がある（リードに報告）" % mode)
        if not name.startswith("._"):
            ids.add(m.group(1))
    return ids


def check_trial_folder(root, volume, check_volume, trial_bytes, trial_run_ids):
    """5.1章（差し戻し2回目 中-C・3回目 中-2）：試しの run の保存先とマニフェストを両方向に照らす。

    - 保存先の一覧が check_store_listing に通ること。
    - 保存先にある run がすべてマニフェストに載っていること。
    - マニフェストに載っている run のすべてについて、保存先の取得の記録の大きさと sha256 が、
      マニフェストのその run の最後の控えと同じであること（ファイルが無くなっていれば止まる。
      取得の記録をまだ作っていない run は、控えも 0 バイトなので、無いままで合う）。
    """
    tpaths = resolve_paths(root, volume, "trial", check_volume)
    entries = _parse_log_lines(trial_bytes)
    ids = check_store_listing(tpaths["store"], "trial")
    for rid in sorted(ids):
        if rid not in trial_run_ids:
            raise GkgError("試しの run の保存先に、マニフェストに載っていない run（%s）のファイルが"
                           "ある（リードに報告）" % rid)
    for rid in trial_run_ids:
        last = None
        for e in entries:
            if e.get("run_id") == rid and "fetch_log_size" in e:
                last = e
        size, sha = _log_state(os.path.join(tpaths["store"], fetch_log_name(rid, "trial")))
        if last is None or (last["fetch_log_size"], last["fetch_log_sha256"]) != (size, sha):
            raise GkgError("試しの run（%s）の取得の記録が、マニフェストの控えと合わない"
                           "（無くなった・書き換わったなど。リードに報告）" % rid)


def _trial_info(paths):
    """試しの run のマニフェストのバイト列と、trial_run_ids・trial_manifest_sha256。

    trial_run_ids の並べ方（T-045。T-043 の監査 軽-A）：試しの run の run-start の行の run_id を、
    その行の gkg_run_seq（封印の記録の gkg-run-start（trial）の seq）の小さい順に並べ、重なりを除く。
    マニフェストの行の順ではない。封印の記録を使い回すと（T-043）、行の順と記録の seq の順がずれる
    ことがあるため。封印係の照合（記録の seq の順）と同じ並べ方になる。
    """
    data = read_bytes_nofollow(paths["trial_manifest"])
    pairs = []
    for raw in data.splitlines():
        if raw.strip():
            try:
                e = json.loads(raw)
            except ValueError:
                raise GkgError("試しの run のマニフェストに JSON でない行がある") from None
            if e.get("kind") == "run-start":
                seq = e.get("gkg_run_seq")
                if type(seq) is not int or seq < 1:
                    raise GkgError("試しの run の run-start の行に gkg_run_seq が無い（リードに報告）")
                pairs.append((seq, e.get("run_id")))
    ids = []
    for _seq, rid in sorted(pairs):
        if rid not in ids:
            ids.append(rid)
    return data, {"trial_run_ids": ids,
                  "trial_manifest_sha256": hashlib.sha256(data).hexdigest() if data else None}


def run_gkg(*, root, volume, filelist_rows, filelist_sha256, method_access_seq, code_sha256,
            mode="official", committed_manifest=None, committed_trial_manifest=None,
            exclusion_rule=None, start_hook=None, transport=urllib_transport, sleep=time.sleep,
            clock=time.monotonic, now=lambda: datetime.datetime.now(datetime.timezone.utc),
            log=_stderr_log, disk_free=_disk_free, check_volume=check_volume):
    """5章の取得の全体。全部の日が終われば dict を返す。

    止まる条件では RunInterrupted。正式な run の最初の実行は、run-start を書いたところで
    RunStartWritten（5章）。mode が trial なら 5.1章の試しの run。
    committed_trial_manifest：HEAD の試しの run のマニフェスト（正式な run だけ。5.1章）。
    exclusion_rule：除外の規則の封印の記録の {"seq", "record_sha256"}（5.3章）。ここでも鎖の上の
      記録と照らす（関門を通らずにこの関数を呼んでも、取得は始まらない）。
    start_hook(mode=, run_id=, trial_days=)：run の最初の実行で、run-start の行を書く前（要求を
      送る前）に1回だけ呼ぶ。封印の記録に gkg-run-start を書き、その記録の
      {"seq", "record_sha256"} を返す（5.5章。T-032）。入口のスクリプトが渡す。無ければ止まる。
    """
    if not re.fullmatch(r"[0-9a-f]{64}", code_sha256 or ""):
        raise GkgError("code_sha256 の形が違う")
    run_id = code_sha256[:16]
    paths = resolve_paths(root, volume, mode, check_volume)
    plan = select_files(filelist_rows)
    if not plan:
        raise GkgError("対象のファイルが1本も無い")
    official_manifest = read_jsonl(paths["official_manifest"])
    official = official_run_id(official_manifest)
    if mode == "trial":
        if official is not None:
            raise GkgError("正式な run の run-start があるので、試しの run はしない（試しの run は"
                           "正式な run の前にだけ行う）")
        plan = trial_plan(plan)
        manifest = read_jsonl(paths["manifest"])
    else:
        manifest = official_manifest
        if official is not None and official != run_id:
            raise GkgError("マニフェストに別の run（%s）の run-start がある。正式な run は最初の "
                           "run-start の run なので、新しい run は始めない" % official)
    mine = [e for e in manifest if e.get("run_id") == run_id]
    if any(e.get("kind") == "run-complete" for e in mine):
        raise GkgError("この run_id の取得は完了している（取り直さない）")
    start = [e for e in mine if e.get("kind") == "run-start"]
    n_files = sum(len(v) for v in plan.values())
    base = {"run_id": run_id, "mode": mode, "code_path": CODE_REL, "code_sha256": code_sha256,
            "filelist_sha256": filelist_sha256, "method_access_seq": method_access_seq,
            "official": mode == "official"}
    log_path = os.path.join(paths["store"], fetch_log_name(run_id, mode))
    check_store_listing(paths["store"], mode, run_id if mode == "official" else None)
    if mode == "official":
        trial_bytes, trial = _trial_info(paths)
        if not isinstance(committed_trial_manifest, bytes) or trial_bytes != committed_trial_manifest:
            raise GkgError("試しの run のマニフェストが、全部コミットされていない（正式な run の前に"
                           "コミットする。5.1章）")
        check_trial_folder(root, volume, check_volume, trial_bytes, trial["trial_run_ids"])
    if start:
        s0 = start[0]
        for k in ("code_sha256", "filelist_sha256", "method_access_seq", "mode"):
            if s0.get(k) != base[k]:
                raise GkgError("再開しようとした run の %s が、最初の run-start と違う" % k)
        if mode == "official":
            current = read_bytes_nofollow(paths["manifest"])
            check_committed_start(current, committed_manifest)
            if current != committed_manifest:
                raise GkgError("正式な run のマニフェストに、コミットしていない行がある。再開の"
                               "前に、マニフェストを全部コミットする（5.2章）")
            if s0.get("trial_manifest_sha256") != trial["trial_manifest_sha256"]:
                raise GkgError("試しの run のマニフェストが、正式な run の run-start のあとで変わった")
            if s0.get("trial_run_ids") != trial["trial_run_ids"]:
                raise GkgError("試しの run の一覧が、正式な run の run-start のあとで変わった")
        check_exclusion_record(root, exclusion_rule, s0)
        check_sealed_run(root, s0, mode, run_id)
        check_volume_mark(paths, run_id, mode)
        trusted_size = check_log_checkpoint(log_path, mine)
        if disk_free(paths["store"]) < MIN_FREE_DISK_BYTES:
            raise RunInterrupted("保存先のディスクの空きが足りない")
        size, sha = _log_state(log_path)
        untrusted = untrusted_ranges(mine, trusted_size, size)
        append_jsonl(paths["manifest"], dict(base, kind="run-resume", at=_iso(now()),
                                             fetch_log_size=size, fetch_log_sha256=sha,
                                             untrusted_ranges=untrusted),
                     "マニフェストの行")
    else:
        if disk_free(paths["store"]) < MIN_FREE_DISK_BYTES:
            raise RunInterrupted("保存先のディスクの空きが足りない")
        if os.path.lexists(log_path):
            raise GkgError("run-start の前なのに、取得の記録が既にある（リードに報告）")
        check_exclusion_record(root, exclusion_rule, None)
        run_ref = _seal_run_start(start_hook, mode, run_id,
                                  sorted(plan) if mode == "trial" else None)
        write_volume_mark(paths, run_id, mode)
        size, sha = _log_state(log_path)
        untrusted = []
        head = dict(base, kind="run-start", started_at=_iso(now()), files_selected=n_files,
                    days=len(plan), block_start=METHOD_BLOCK[0], block_end=METHOD_BLOCK[1],
                    store_location=paths["location"],
                    fetch_log_size=size, fetch_log_sha256=sha,
                    exclusion_rule_seq=exclusion_rule["seq"],
                    exclusion_rule_record_sha256=exclusion_rule["record_sha256"],
                    gkg_run_seq=run_ref["seq"], gkg_run_record_sha256=run_ref["record_sha256"])
        if mode == "trial":
            head.update(trial=True, trial_days=sorted(plan))
        else:
            head.update(trial)
        append_jsonl(paths["manifest"], head, "マニフェストの行")
        if mode == "official":
            raise RunStartWritten("正式な run の run-start を書いた（GKG にはまだ要求を送って"
                                  "いない）。data/manifest/%s をコミットしてから（リモートが"
                                  "あれば push も）、同じコマンドでもう一度実行する" % MANIFEST_NAME)
    try:
        return _run_plan(plan, mine, base, paths, log_path, run_id, mode, transport, sleep,
                         clock, now, log, disk_free, untrusted)
    except BaseException:
        # どの例外で止まっても（RunInterrupted・GkgError・Ctrl-C など）控えを書く（軽-6）。
        # kill -9 と停電では書けない（5.2章の限界）
        _write_stop(paths, base, log_path, now)
        raise


def sealed_run_record(root, seq):
    """封印の記録 sealed/ledger.jsonl の seq の記録の (行の正規の形のバイト列, kind, 中身)。

    無ければ None。gkg-run-start でなければ中身は None。鎖の検証に通らなければ GkgError。
    封印係の ledger.py を読む（読むだけ。書かない）。
    """
    themes = _load_sibling("themes")
    ledger = themes._import_ledger()
    try:
        data = ledger.read_ledger(os.path.join(root, "sealed", "ledger.jsonl"))
        rec = next((r for r in ledger.verify_chain(data) if r["seq"] == seq), None)
        if rec is None:
            return None
        doc = (ledger.read_target_json(root, rec, rec["kind"])
               if rec["kind"] == ledger.GKG_RUN_KIND else None)
    except ledger.LedgerError as e:
        raise GkgError("封印の記録を読めない: %s" % e) from None
    return ledger.canonical_line(rec), rec["kind"], doc


GKG_RUN_KIND = "gkg-run-start"      # 封印係の ledger.GKG_RUN_KIND と同じ（テストで照らす）


def check_sealed_run(root, s0, mode, run_id):
    """5.5章（T-032 の差し戻し1回目 中-1）：再開のときに、既にある run-start の行の gkg_run_seq と
    gkg_run_record_sha256 を封印の記録と照らす。

    その seq の記録があり、kind が gkg-run-start で、行の正規の形の sha256 が
    gkg_run_record_sha256 と同じで、中身の mode と run_id がこの run と同じでなければ、
    要求を送らず、何も書かずに止まる（手で書いた run-start の行を置いて、gkg-run-start を書かずに
    試しの run を走らせる道を塞ぐ）。
    """
    seq, sha = s0.get("gkg_run_seq"), s0.get("gkg_run_record_sha256")
    if (type(seq) is not int or seq < 1 or not isinstance(sha, str)
            or not re.fullmatch(r"[0-9a-f]{64}", sha)):
        raise GkgError("run-start の行に、gkg-run-start の記録の seq と sha256 が無いか、形が違う"
                       "（リードに報告）")
    got = sealed_run_record(root, seq)
    if got is None:
        raise GkgError("run-start の行の gkg_run_seq %d の記録が、封印の記録に無い（リードに報告）" % seq)
    line, kind, doc = got
    if kind != GKG_RUN_KIND:
        raise GkgError("run-start の行の gkg_run_seq %d の記録が gkg-run-start でない（%s。リードに報告）"
                       % (seq, kind))
    if hashlib.sha256(line).hexdigest() != sha:
        raise GkgError("run-start の行の gkg_run_record_sha256 が、封印の記録の seq %d の行と一致しない"
                       "（リードに報告）" % seq)
    if not isinstance(doc, dict) or doc.get("mode") != mode or doc.get("run_id") != run_id:
        raise GkgError("封印の記録の seq %d の gkg-run-start が、この run（%s・%s）のものでない"
                       "（リードに報告）" % (seq, mode, run_id))


def _seal_run_start(start_hook, mode, run_id, trial_days):
    """5.5章（T-032）：封印の記録に gkg-run-start を書く。書けなければ何も書かずに止まる。"""
    if start_hook is None:
        raise GkgError("封印の記録（gkg-run-start）に書く仕組みを受け取っていない（入口のスクリプト"
                       "から実行する）")
    try:
        ref = start_hook(mode=mode, run_id=run_id, trial_days=trial_days)
    except (GkgError, RunInterrupted):
        raise
    except Exception as e:
        raise GkgError("封印の記録に gkg-run-start を書けなかったので、取得を始めない：%s"
                       % e) from None
    if (not isinstance(ref, dict) or set(ref) != {"seq", "record_sha256"}
            or type(ref["seq"]) is not int or ref["seq"] < 1
            or not isinstance(ref["record_sha256"], str)
            or not re.fullmatch(r"[0-9a-f]{64}", ref["record_sha256"])):
        raise GkgError("gkg-run-start の記録の seq と sha256 の形が違う")
    return ref


def _write_stop(paths, base, log_path, now):
    """止まったときに、取得の記録の大きさと sha256 をマニフェストに書く（中1。書けなければ書かない）。"""
    try:
        size, sha = _log_state(log_path)
        append_jsonl(paths["manifest"], dict(base, kind="run-stop", at=_iso(now()),
                                             fetch_log_size=size, fetch_log_sha256=sha),
                     "マニフェストの行")
    except (GkgError, OSError):
        pass


def untrusted_ranges(mine, trusted_size, size):
    """5.2章（差し戻し3回目 中-1）：信用しない範囲（取得の記録のバイトの [始め, 終わり)）の一覧。

    前の run-resume の行に書いた範囲を引き継ぎ、今回の最後の控えより後ろ（控えを書けずに
    止まった跡）を足す。run-resume の行に書いて、以後の読み取りでも除く。
    """
    prev = []
    for e in mine:
        if "untrusted_ranges" in e:
            prev = [list(r) for r in e["untrusted_ranges"]]
    for r in prev:
        if not (isinstance(r, list) and len(r) == 2 and all(isinstance(x, int) for x in r)
                and 0 <= r[0] < r[1] <= trusted_size):
            raise GkgError("マニフェストの信用しない範囲の形が違う（リードに報告）")
    if size > trusted_size:
        prev.append([trusted_size, size])
    return prev


def _parse_log_lines(data):
    out = []
    for raw in data.splitlines():
        if raw.strip():
            try:
                out.append(json.loads(raw))
            except ValueError:
                raise GkgError("取得の記録に JSON でない行がある") from None
    return out


def _run_plan(plan, mine, base, paths, log_path, run_id, mode, transport, sleep, clock, now,
              log, disk_free, untrusted):
    done_days = {e["day"] for e in mine if e.get("kind") == "day"}
    latest, trips = {}, set()
    used_ok, used_bad = Counter(), Counter()     # 信用する試行の行・信用しない範囲の試行の行
    data = read_bytes_nofollow(log_path)
    lines, pos = [], 0
    for raw in data.splitlines(keepends=True):
        bad = any(a <= pos < b for a, b in untrusted)
        pos += len(raw)
        if raw.strip():
            lines.append((bad, _parse_log_lines(raw)[0]))
    del data
    _check_log_lines([e for _b, e in lines], run_id, mode)
    sent = Counter()                             # 実際に送った要求の数（attempt の行の数。軽-2）
    for bad, e in lines:
        if "file_time" not in e:
            continue
        ft = e["file_time"]
        if e.get("result") == "attempt":
            sent[ft] += 1
            (used_bad if bad else used_ok)[ft] += 1    # 最後の結果の行より後の試行の回数（5章）
            continue
        if bad:
            # 信用しない範囲の結果の行（ok・failed・interrupted）は使わず、そのファイルは取り直す
            continue
        latest[ft] = e
        used_ok[ft] = used_bad[ft] = 0
        if e.get("result") == "interrupted":
            trips.add(e.get("trip"))
    used = Counter()
    for ft in set(used_ok) | set(used_bad):
        n = used_ok[ft] + used_bad[ft]
        if used_bad[ft]:
            # 信用しない範囲の試行の行だけでは使い切らせない（少なくとも1回は要求を送る。中-1）
            n = min(n, MAX_ATTEMPTS_PER_FILE - 1)
        used[ft] = n
    del lines
    state = {"transient": [], "format": 0, "retries_used": len(trips)}
    ctx = {"paths": paths, "log_path": log_path, "run_id": run_id, "mode": mode, "now": now,
           "sent": sent}
    pacer = Pacer(clock, sleep)
    vocab = {}
    totals = Counter()
    pending = []

    def flush():
        while pending:
            day, n_listed, day_agg, files = pending.pop(0)
            info = _write_day(day, day_agg, files, run_id, paths, disk_free)
            size, sha = _log_state(log_path)
            dline = dict(base, kind="day", day=day, file_name=info["file_name"],
                         sha256=info["sha256"], files_listed=n_listed,
                         files_ok=info["ok"], files_failed=info["failed"], docs=info["docs"],
                         written_at=_iso(now()), store_location=paths["location"],
                         fetch_log_size=size, fetch_log_sha256=sha,
                         failed_files=[{"file_time": f["file_time"], "reason": f["reason"],
                                        "attempts": f["attempts"],
                                        "requests_sent": sent[f["file_time"]],
                                        "listed_size": f["size"], "listed_md5": f["md5"]}
                                       for f in files if f["result"] != "ok"],
                         requests_sent=sum(sent[f["file_time"]] for f in files))
            if info["refilled"]:
                dline["refilled_empty_file"] = True
            if info["reused"]:
                dline["reused_existing_day_file"] = True
            append_jsonl(paths["manifest"], dline, "マニフェストの行")
            log("%s：ok %d・failed %d・文書 %d" % (day, info["ok"], info["failed"],
                                                 info["docs"]))

    for day, entries in plan.items():
        if day in done_days:
            continue
        day_agg, files = _run_day(day, entries, latest, used, state, pacer, vocab, ctx,
                                  transport, sleep, clock, log)
        pending.append((day, len(entries), day_agg, files))
        # 一時的な失敗が続いている途中なら、その日はまだ書かない（続きで止まる条件に達したら、
        # 続いた失敗のファイルを日をまたいでも interrupted にして取り直せるようにするため）
        if not state["transient"]:
            flush()
    flush()
    for e in read_jsonl(paths["manifest"]):
        if e.get("run_id") == run_id and e.get("kind") == "day":
            totals["days"] += 1
            totals["files_ok"] += e["files_ok"]
            totals["files_failed"] += e["files_failed"]
    if totals["days"] != len(plan):
        raise GkgError("マニフェストの day の行の数が、日の数と合わない")
    size, log_sha = _log_state(log_path)
    done = dict(base, kind="run-complete", completed_at=_iso(now()), days=totals["days"],
                files_ok=totals["files_ok"], files_failed=totals["files_failed"],
                fetch_log_file=fetch_log_name(run_id, mode), fetch_log_sha256=log_sha,
                fetch_log_size=size, store_location=paths["location"])
    append_jsonl(paths["manifest"], done, "マニフェストの行")
    return done


def _log_file(ctx, entry, result, reason, transient, attempts, sha, docs, stats, trip=None):
    rec = {"run_id": ctx["run_id"], "mode": ctx["mode"], "file_time": entry["file_time"],
           "listed_md5": entry["md5"],
           "listed_size": entry["size"], "result": result, "reason": reason,
           "transient": transient, "attempts": attempts, "sha256": sha,
           "docs": {g.decode() if isinstance(g, bytes) else g: n for g, n in sorted(docs.items())},
           "stats": dict(sorted(stats.items())), "finished_at": _iso(ctx["now"]())}
    if trip is not None:
        rec["trip"] = trip
    append_store_jsonl(ctx["paths"], ctx["log_path"], rec, "取得の記録の行")
    return rec


def _log_attempt(ctx, entry, n):
    """要求を送る直前の試行の行（5章。T-018 の監査 軽1）。書けなければ要求を送らない。"""
    rec = {"run_id": ctx["run_id"], "mode": ctx["mode"], "file_time": entry["file_time"],
           "result": "attempt",
           "attempt": n, "at": _iso(ctx["now"]())}
    append_store_jsonl(ctx["paths"], ctx["log_path"], rec, "取得の記録の行")
    ctx["sent"][entry["file_time"]] += 1


def _run_day(day, entries, latest, used, state, pacer, vocab, ctx, transport, sleep, clock, log):
    """1日分のファイルを取得して集計する（書かない）。返り値: (日の集計, ファイルの一覧)。"""
    day_agg = Agg()
    files = []
    for entry in entries:
        prev = latest.get(entry["file_time"])
        if prev is not None and prev.get("result") == "failed":
            files.append({"file_time": entry["file_time"], "result": "failed",
                          "reason": prev.get("reason") or "-", "md5": entry["md5"],
                          "size": entry["size"], "sha256": None,
                          "attempts": prev.get("attempts", 0), "docs": {}})
            continue
        if entry["ambiguous"]:
            rec = _log_file(ctx, entry, "failed", "ambiguous_listing", False, 0, None, {}, {})
            latest[entry["file_time"]] = rec
            files.append({"file_time": entry["file_time"], "result": "failed",
                          "reason": "ambiguous_listing", "md5": entry["md5"],
                          "size": entry["size"], "sha256": None, "attempts": 0, "docs": {}})
            continue
        fr = fetch_file(entry, transport, sleep, clock, pacer, log,
                        used.get(entry["file_time"], 0),
                        lambda n, e=entry: _log_attempt(ctx, e, n))
        used[entry["file_time"]] = 0
        sha, agg, reason = None, None, fr.reason
        if fr.result == "ok":
            sha = hashlib.sha256(fr.data).hexdigest()
            try:
                agg = aggregate_zip(fr.data, entry["file_time"], vocab)
            except GkgFormatError as e:
                reason = "format_%s" % e
            fr.data = None
        if agg is not None:
            state["transient"] = []
            state["format"] = 0
            day_agg.merge(agg)
            if day_agg.pair_keys() > MAX_PAIR_KEYS:
                raise RunInterrupted("1日分のテーマの組の種類が上限を超えた（%s）" % day)
            docs = {g.decode(): n for g, n in agg.docs.items()}
            rec = _log_file(ctx, entry, "ok", "", False, fr.attempts, sha, docs, agg.stats)
            files.append({"file_time": entry["file_time"], "result": "ok", "reason": "",
                          "md5": entry["md5"], "size": entry["size"], "sha256": sha,
                          "attempts": fr.attempts, "docs": docs})
        else:
            transient = fr.result != "ok" and fr.transient
            rec = _log_file(ctx, entry, "failed", reason, transient, fr.attempts, sha, {}, {})
            log("%s：failed（%s）" % (entry["file_time"], reason))
            files.append({"file_time": entry["file_time"], "result": "failed", "reason": reason,
                          "md5": entry["md5"], "size": entry["size"], "sha256": sha,
                          "attempts": fr.attempts, "docs": {}})
            if transient:
                state["transient"].append(entry)
                state["format"] = 0
            elif reason.startswith("format_"):
                state["transient"] = []
                state["format"] += 1
            else:
                state["transient"] = []
                state["format"] = 0
            if len(state["transient"]) >= MAX_CONSECUTIVE_TRANSIENT_FAILURES:
                if state["retries_used"] < MAX_INTERRUPTED_RETRIES_PER_RUN:
                    trip = state["retries_used"] + 1
                    for e in state["transient"]:
                        latest[e["file_time"]] = _log_file(
                            ctx, e, "interrupted", "consecutive_transient_failures",
                            True, 0, None, {}, {}, trip=trip)
                    raise RunInterrupted("一時的な失敗が %d 本続いたので止めた（再開すると、続いた"
                                         "失敗のファイルを1回だけ取り直す）"
                                         % MAX_CONSECUTIVE_TRANSIENT_FAILURES)
                state["transient"] = []
                latest[entry["file_time"]] = rec
                raise RunInterrupted("一時的な失敗が %d 本続いたので止めた。この run の取り直しは"
                                     "使い切ったので、続いた失敗のファイルは failed のまま確定した"
                                     % MAX_CONSECUTIVE_TRANSIENT_FAILURES)
            if state["format"] >= MAX_CONSECUTIVE_FORMAT_FAILURES:
                raise RunInterrupted("形式の失敗が %d 本続いたので止めた。コードとデータの形が"
                                     "合っていない（リードに報告）"
                                     % MAX_CONSECUTIVE_FORMAT_FAILURES)
        latest[entry["file_time"]] = rec
    return day_agg, files


def _write_day(day, day_agg, files, run_id, paths, disk_free):
    data = serialize_day(day, day_agg, files, paths["mode"])
    check_output_bytes(data, "日の集計")
    gz = gzip_bytes(data)
    del data
    _guard_store(paths)
    if disk_free(paths["store"]) < MIN_FREE_DISK_BYTES:
        raise RunInterrupted("保存先のディスクの空きが足りない（%s の集計を書く前）" % day)
    name = day_file_name(run_id, day, paths["mode"])
    reused = False
    existing = _existing_day_file(paths["store"], name)
    if existing:
        check_existing_day_file(existing, day)
        # 日の集計を書いたあと day の行を書く前に止まった跡（5.2章。T-026 軽-1）。取り直して
        # 作った集計と、F の行の attempts の欄のほかがすべて同じなら、そのファイルを使う
        if not same_day_except_attempts(existing, gz):
            raise GkgError("%s の日の集計が既にあり、取り直した集計と中身が違う（上書きしない。"
                           "リードに報告）" % day)
        sha, refilled, reused = hashlib.sha256(existing).hexdigest(), False, True
    else:
        try:
            sha, refilled = write_new_file(paths["store"], name, gz)
        except OSError:
            raise RunInterrupted("保存先に書けなかった（ディスクが外れたなど）。%s の集計が途中まで"
                                 "書かれていれば、再開のときに止まる（リードに報告）" % day) from None
    ok = sum(1 for f in files if f["result"] == "ok")
    return {"file_name": name, "sha256": sha, "ok": ok, "failed": len(files) - ok,
            "docs": sum(day_agg.docs.values()), "refilled": refilled, "reused": reused}


def _existing_day_file(store, name):
    """中身のある日の集計が既にあれば、そのバイト列（0バイト・無ければ b""）。"""
    path = os.path.join(store, name)
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    except FileNotFoundError:
        return b""
    except OSError:
        raise GkgError("同じ名前のものがあり、通常のファイルとして開けない") from None
    with os.fdopen(fd, "rb") as f:
        if not stat.S_ISREG(os.fstat(f.fileno()).st_mode):
            raise GkgError("同じ名前のものがあり、通常のファイルでない")
        return f.read()


_F_ATTEMPTS_FIELD = 7        # serialize_day の F の行の attempts の欄（0 から数えて）
_F_ATTEMPTS_RE = re.compile(rb"\A[0-%d]\Z" % MAX_ATTEMPTS_PER_FILE)


_GZIP_FIXED_HEAD = b"\x1f\x8b\x08\x00\x00\x00\x00\x00"   # 魔法の数・deflate・FLG 0・MTIME 0


def check_existing_day_file(gz, day):
    """既にある日の集計をそのまま使う前の検査（T-030 軽-A・T-032）。合わなければ GkgError で止まる。

    ファイルのバイト列について（T-032。T-030 の監査 中-1。リードの前回の指示の訂正）：
      - gzip の頭が、このモジュールが書く形（gzip_bytes）と同じであること：魔法の数 1f 8b、
        圧縮の方式 8（deflate）、旗（FLG）が 0（FTEXT・FHCRC・FEXTRA・FNAME・FCOMMENT のどれも
        無い）、時刻（MTIME）が 0。任意の語を入れられる欄（FEXTRA・FNAME・FCOMMENT）を持つ
        ファイルは、そのまま使わない。
      - gzip の部分（member）がちょうど1つで、その後ろに何も無いこと（空の部分や任意のバイトを
        後ろに足したファイルは、そのまま使わない）。
    展開した中身について：check_output_bytes（使ってよい文字だけ・メールアドレスの形が無い）を
    かけ、F の行の attempts の欄が 0〜MAX_ATTEMPTS_PER_FILE の1桁の数字であることを確かめる。
    attempts の欄は same_day_except_attempts で比べないので、ここで形を確かめる。
    照らす範囲（T-032 の差し戻し1回目 軽-2）：頭の1〜8バイト目、任意の語を入れられる欄の有無、
    後ろ、展開した中身（deflate の部分は展開した中身として。最後の8バイトの CRC32 と大きさは
    展開のときに zlib が確かめる）。頭の9・10バイト目（XFL と OS。圧縮の度合いと書いた OS を示す
    1バイトずつ）は照らさない。別の圧縮器や OS で書いた正直なファイルも通すためで、この2バイトに
    は任意の値を置ける（2バイトだけで、語やメールアドレスの形は入らない）。
    """
    if len(gz) < 18 or gz[:8] != _GZIP_FIXED_HEAD:
        raise GkgError("%s の既にある日の集計の gzip の頭が、このコードの書く形でない"
                       "（FNAME・FCOMMENT・FEXTRA などの欄がある。リードに報告）" % day)
    d = zlib.decompressobj(31)
    try:
        text = d.decompress(gz) + d.flush()
    except zlib.error:
        raise GkgError("%s の既にある日の集計を展開できない（リードに報告）" % day) from None
    if not d.eof or d.unused_data:
        raise GkgError("%s の既にある日の集計の gzip の後ろに、別の部分かバイトがある"
                       "（リードに報告）" % day)
    check_output_bytes(text, "既にある日の集計")
    for line in text.split(b"\n"):
        if line.startswith(b"F\t"):
            f = line.split(b"\t")
            if len(f) <= _F_ATTEMPTS_FIELD or not _F_ATTEMPTS_RE.match(f[_F_ATTEMPTS_FIELD]):
                raise GkgError("%s の既にある日の集計の F の行の attempts の欄の形が違う"
                               "（リードに報告）" % day)


def same_day_except_attempts(old_gz, new_gz):
    """二つの日の集計が、F の行の attempts の欄のほかはバイト単位で同じなら True。"""
    try:
        old = gzip.decompress(old_gz)
    except (OSError, EOFError, ValueError):
        return False
    new = gzip.decompress(new_gz)
    a, b = old.split(b"\n"), new.split(b"\n")
    if len(a) != len(b):
        return False
    for x, y in zip(a, b):
        if x == y:
            continue
        if not (x.startswith(b"F\t") and y.startswith(b"F\t")):
            return False
        fx, fy = x.split(b"\t"), y.split(b"\t")
        if len(fx) != len(fy) or len(fx) <= _F_ATTEMPTS_FIELD:
            return False
        if fx[:_F_ATTEMPTS_FIELD] + fx[_F_ATTEMPTS_FIELD + 1:] != \
                fy[:_F_ATTEMPTS_FIELD] + fy[_F_ATTEMPTS_FIELD + 1:]:
            return False
    return True


if __name__ == "__main__":
    print("このモジュールはライブラリとしてだけ使う。取得は入口のスクリプト "
          "src/collector/acquire_gkg.py から行う（手順は src/collector/README.md）。",
          file=sys.stderr)
    sys.exit(2)
