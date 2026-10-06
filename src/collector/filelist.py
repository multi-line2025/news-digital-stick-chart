#!/usr/bin/env python3
"""GDELT 2.0 のファイル一覧（masterfilelist）の取得（T-010、保存先は T-012・T-015。試運転の手順3）。

データ出典
    Data: The GDELT Project (https://www.gdeltproject.org/). This project is not
    affiliated with or endorsed by the GDELT Project.
    データ出典：GDELT Project（https://www.gdeltproject.org/）。本プロジェクトは
    GDELT Project と提携・承認の関係にありません。

このモジュールは、実際の取得をまだ一度も行っていない（T-010・T-012・T-015 はコードとテスト
だけ）。取得の実行は、入口のスクリプト acquire_filelist.py から行う（T-016）。このモジュールを
直接実行しても取得はしない。入口のスクリプトと手順は src/collector/README.md。

------------------------------------------------------------------------
1. 取得元
------------------------------------------------------------------------
    MASTERFILELIST_URL = https://data.gdeltproject.org/gdeltv2/masterfilelist.txt

    - 取得するホストは data.gdeltproject.org だけ（T-001 の申し送り）。スキームは https
      だけ、パスは ALLOWED_LIST_PATHS に完全に一致するものだけを許す。ポート・利用者情報
      （ホスト名の前に利用者名を書く形）・クエリ・フラグメント・パーセント符号化・「..」「//」を含む URL は
      拒む（「/documentation/../」の形の抜け道を塞ぐため。T-001 の申し送り）。
      gdeltcloud.com を含め、ほかのホストはすべて拒む。
    - 自動のリダイレクトは切っている（_NoRedirect）。3xx の応答は失敗として扱い、再試行も
      しない。環境変数のプロキシも使わない（ProxyHandler({})）。
    - https で取れることは、まだ確かめていない（ネットワークを使わないタスクのため）。
      一覧の中の URL は http:// で書かれていることが知られている。https で取れない場合は、
      このコードを直さずに止まり、別のタスクで判断する。

------------------------------------------------------------------------
2. 待ち時間・再試行・打ち切り（CLAUDE.md「取得は…待ち時間と再試行の上限をコードに明記する」）
------------------------------------------------------------------------
    GDELT は data.gdeltproject.org の一括ファイルについて、速度制限・待ち時間・再試行の
    公式の値を公表していない（T-001 で確認した範囲では見つからなかった）。
    下の値は、このプロジェクトが控えめに決めた値であり、公式の値ではない。

    REQUEST_TIMEOUT_SECONDS   60    接続と、1回の読み込みごとの待ちの上限（ソケット単位）
    TOTAL_DEADLINE_SECONDS    1800  取得全体（再試行と待ちを含む）の上限。超えたら打ち切る
    MAX_ATTEMPTS              3     試行の回数の上限（最初の1回を含む）
    RETRY_WAIT_SECONDS        (60, 300)  2回目・3回目の試行の前に待つ秒数
    MAX_RETRY_AFTER_SECONDS   900   Retry-After がこれを超えたら、待たずに打ち切る
    MAX_LINE_BYTES            4096  1行の長さの上限。超えた行は分類できない行として捨てる
    MAX_RESPONSE_BYTES        2 GiB 応答の全体の長さの上限。超えたら打ち切る

    再試行するのは、通信の失敗（接続・読み込みの途中の失敗、タイムアウト）と、HTTP の
    429・500・502・503・504 だけ。それ以外（3xx、404 など）は再試行せずに打ち切る。
    再試行のときは、それまでに読んだ行をすべて捨ててから最初から読み直す。
    一覧は1回の取得で1件の要求だけを送る。

    上限 MAX_RESPONSE_BYTES で打ち切った場合、「一覧の全体が上限を超えた」という1ビットが
    分かる。上限は一覧の大きさの見込み（数百 MB）より十分大きく取っているので、閾値を
    決める期間の量について意味のある情報にはならないと判断した。

    時間の上限 TOTAL_DEADLINE_SECONDS（30分）で打ち切った場合も、分かるのは「取得が30分の
    うちに終わらなかった」という1ビットだけである。打ち切りの文には、読んだ量も行の中身も
    入れない。

------------------------------------------------------------------------
3. 2020-12-15 以降の行を、ほかのどの処理よりも先に捨てる
------------------------------------------------------------------------
    docs/stats/periods.md 8章 (2) により、2020-12-15 以降の行を「扱う」（ディスクに書く・
    表示する・集計する・ログに出す）と、きっかけの値の期限に当たる。そこで、
    _read_kept_lines() は応答を1行ずつ読み、各行について最初に次だけを行う。

      (a) 行を空白で分け、3つ目の欄のファイル名から14桁の時刻を取り出す
      (b) 時刻 t を LAST_KEPT_TIME（2020-12-14 23:45:00 UTC）と比べる。t がそれより後なら、
          4章の規則でファイルの日が CUTOFF_DAY（2020-12-15）以降になるので、その行を
          その場で捨てる。日付の計算（t + 15分）は、比べたあとの残す行にだけ行う。
          そのため、9999年のような極端な時刻の行でも、例外を出さずに捨てられる。

    (a) で時刻を取り出せない行（欄の数が違う・14桁の時刻が無い・暦として正しくない・
    長すぎる）は、どの期間の行かを判定できないので、同じくその場で捨てる。
    (a)(b) は、どんな中身の行でも例外を出さない（テストで極端な行を入れて確かめている）。

    捨てた行（(c) と、判定できなかった行）は、表示も集計もせず、ログにも例外の文にも
    出さない。件数も数えない。件数から一覧の全体の量が分かってしまうため。
    応答全体のハッシュや長さは、記録しない・出力しない。
    数えて出すのは、残した行（2020-12-14 以前と判定できた行）についての件数だけである。

    取得にかかった時間は、このモジュールは記録も出力もしない。ただし、マニフェストの
    fetched_at（取得の完了の時刻）と、acquisition-start の記録の drand の回の時刻との差から、
    おおよその時間が分かる。そこから分かりうるのは、通信の速さで割った一覧の全体の長さ
    （の大まかな見当）だけで、行の中身や、2020-12-15 以降の行だけの量は分からない。

    応答の本体は、ディスクにも一時ファイルにも書かない。

------------------------------------------------------------------------
4. 15分ファイルの時刻と UTC の暦日の対応
------------------------------------------------------------------------
    確かめていない前提
      - ファイル名の時刻（YYYYMMDDHHMMSS、UTC とみなす）が、そのファイルの15分の区間の
        「始まり」を指すのか「終わり」を指すのかは、一次資料では確かめていない。
      - 時刻が UTC であることも、一次資料の文言としては確かめていない（GDELT の
        文書の一般的な扱いに従った前提）。
      - 1つのファイルが覆う区間は15分以内である、という前提を置く。

    規則
      ファイル名の時刻を t とする。そのファイルが含みうるデータの区間は、
        始まりを指す場合：[t, t + 15分)
        終わりを指す場合：[t - 15分, t)
      の二通りある。両方を合わせた範囲の最後の時刻は t + 15分 の直前である。

      **ファイルの日 = (t + 15分 − 1秒) の UTC の日付**
      （ファイル名の時刻の分解能は1秒なので、1秒を引けば「t + 15分 の直前」になる）

      つまり、そのファイルが含みうるデータの、最も遅い日をファイルの日とする。
      15分の刻みに揃った時刻（分が 00/15/30/45、秒が 00）では、これはファイル名の日付と
      同じになる。刻みに揃わない時刻（例：23:50:00）では、翌日になることがある。

    根拠
      - 区画の境目（2020-12-14 と 2020-12-15 のあいだ）では、どちらの前提でも、
        2020-12-15 00:00 以降のデータを含みうるファイルは必ず 2020-12-15 以降の日になり、
        捨てられる。残すファイルは、どちらの前提でも 2020-12-15 00:00 より前のデータしか
        含まない（t + 15分 ≤ 2020-12-15 00:00）。
          20201214234500 → 日は 2020-12-14、残す（どちらの前提でも 12-14 のデータだけ）
          20201215000000 → 日は 2020-12-15、捨てる（始まりなら 12-15 のデータ、
                           終わりなら 12-14 23:45〜24:00 のデータ。後者でも捨てる）
          20201214235000 → 日は 2020-12-15、捨てる（始まりなら 12-15 にかかる）
      - 予言日 d の予言は d−1 以前のデータだけを使う（periods.md 1章）。日の区切り
        すべてで、この規則はファイルを「含みうる最も遅い日」に入れるので、どちらの前提でも
        日 D のファイルに D より後のデータは入らない。前提が「終わり」だった場合は、
        日 D の最後の15分のデータが日 D+1 に入る（1日あたり96区間のうち1区間がずれる）。
        ずれは常に「遅い側」なので、先のデータが混ざることはない。
      - 割り振りで例に挙がった「t − 15分 の日付」は採らなかった。その規則では
        20201215000000 が 2020-12-14 の日になる。前提が「始まり」なら、このファイルは
        2020-12-15 00:00〜00:15 のデータを含むので、閾値を決める期間のデータが残ってしまう。
      - 代償：前提が「終わり」だった場合、手法を作る期間の最後の15分
        （2020-12-14 23:45〜24:00）のデータを失う。

------------------------------------------------------------------------
5. 保存する項目（許可リスト）と保存先
------------------------------------------------------------------------
    一覧の各行は「大きさ md5 URL」の3つの欄である。残した行から、次の項目だけを保存する。

      file_time   ファイル名の14桁の時刻（YYYYMMDDHHMMSS）
      file_type   export / mentions / gkg のどれか（ファイル名の接尾辞
                  .export.CSV.zip / .mentions.CSV.zip / .gkg.csv.zip から決める）
      size_bytes  一覧に書かれたファイルの大きさ（10進の整数）
      md5         一覧に書かれたファイルの md5（16進の小文字32桁）

    保存しないもの：URL の欄（ホスト・パス・スキームを含む。file_time と file_type から
    https://data.gdeltproject.org/gdeltv2/<file_time>.<接尾辞> の形で決まるため、
    保存する必要が無い）、行の元の文字列、ファイルの日（4章の規則で file_time から決まる）。
    一覧は記事の URL・人物名・組織名を含まないが、含んでいたとしても、この4項目以外は
    ディスクに書く前に捨てる。

    残した行のうち、次のどれかに当たるものは「形式の合わない行」として保存しない。
    これらは 2020-12-14 以前と判定できた行なので、件数（rejected_rows）を出してよい。
      - 欄が3つでない、大きさが10進の整数でない、md5 が32桁の16進でない
      - URL のホストが data.gdeltproject.org でない、パスが /gdeltv2/ の直下でない、
        スキームが http / https でない、接尾辞が上の3種類でない

    書き方：1行目に見出し "file_time\tfile_type\tsize_bytes\tmd5"、2行目からタブ区切りの
    行を (file_time, file_type, size_bytes, md5) の順に並べ替えて書く。改行は LF、文字は
    ASCII。並べ替えるのは、GDELT の一覧の行の順番が変わっても、同じ中身なら同じ
    sha256 になるようにするため。まったく同じ行が二つあれば、二つとも残す。

    保存先（T-012、T-015。オーナーの決定「git に入れずハッシュのみ記録する」）
      一覧の本体は Git の外に書く。リポジトリの中（data/manifest/）には、ハッシュの一覧
      （マニフェスト）の行だけを追記する。

      本体：<home>/Desktop/news-stick-data/gdelt-filelist/masterfilelist-kept-<取得を始める直前の
        UTC 時刻>.tsv
        保存先は FIXED_STORE_PARTS（Desktop / news-stick-data / gdelt-filelist）で固定する。
        2026-10-06 のオーナーの決定「デスクトップ直下」（reviews/T-011.md の末尾）による。
        引数 store_dir の realpath が <home>/Desktop/news-stick-data/gdelt-filelist の realpath と
        一致しなければ止まる。news-stick-data と gdelt-filelist の2段は、どちらもシンボリック
        リンクでない既にあるフォルダでなければならない（リンクで別の場所に向けられないように）。
        home は引数で受け取る。本番の入口（acquire_filelist.py）は、環境変数 HOME ではなく
        利用者のデータベース（pwd）から決めたホームを渡す。環境変数で保存先を変える口は無い
        （T-012 の NDSC_GDELT_FILELIST_STORE と既定の ~/news-stick-data は T-015 で外した）。
        フォルダは前もってオーナーが作る。このモジュールはフォルダを作らない
        （os.mkdir を呼ばない。テストの見張りでも mkdir を許していない）。
        名前は start_hook を呼ぶ前に一度だけ決め、前もっての確認と実際の書き込みに同じ名前を
        使う。マニフェストの fetched_at は取得の完了の時刻で、名前の時刻とは別である。
        本体は、Git の外の一時領域と同じ扱いになる（後で GitHub のリリースなどに置くかは、
        別のタスクで決める）。大きさの見込みは約60万行、約40 MB。

      マニフェスト：<root>/data/manifest/gdelt-filelist.jsonl に、1回の取得につき1行を追記する。
        置き場は data/manifest に固定で、引数では変えられない（T-015。T-012 の監査 軽3）。
        過去の行は書き換えない。1行は次の項目だけの JSON（キーの順に並べ、ASCII）。
          file_name              本体のファイル名（名前だけ。パスは入れない）
          sha256                 本体のバイト列の sha256（書いたファイルから計算し直して照合）
          kept_rows              本体のデータの行数（見出しの1行を除く）
          fetched_at             取得の完了の時刻（UTC、ISO 8601）
          source_url             取得元の URL（データ源の URL。記事の URL ではない）
          acquisition_start_seq  start_hook が返した acquisition-start の seq
          code_path              取得のコードの、ルートからの相対パス（CODE_REL。入口のスクリプト）
          code_sha256            取得のコード（入口のスクリプト acquire_filelist.py）の sha256。
                                 入口のスクリプトは、このファイルと privacy_scan.py の sha256 を
                                 中に固定しているので、この値がその二つも縛る（6章）
          store_location         本体の保存先の名前の形 STORE_LOCATION_NAME
                                 （"~/Desktop/news-stick-data/gdelt-filelist"）。絶対パスではない。
                                 実際の保存先が、この決まった場所であることを確かめてから書く
                                 （T-015。T-012 の監査 軽4）
        手元の絶対パス・ユーザー名・ホームのパスは入れない。追記の前に、行がそれらを
        含まないこと、file_name が上の名前の形であることを確かめ、違えば書かずに止まる。

    保存先の確認（T-010 の監査 B-3 への対応。T-015 で場所を固定）
      確かめること
        - root、マニフェストのフォルダ、store_dir を realpath にしてから比べる（途中の
          シンボリックリンクを解いた実際の場所で比べる）。
        - マニフェストのフォルダの realpath は、root の realpath に data/manifest を足したものと
          一致しなければならない（途中にリンクがあれば一致しないので止まる）。その途中に
          .git があれば止まる（T-012 の監査 軽3）。
        - store_dir の実際の場所は root の下でも root そのものでもなく、それ自身とその上の
          どのフォルダにも .git が無い（Git の作業ツリーの外）。さらに上の「本体」の決まった
          場所と一致する。どちらも既にあるフォルダであること。
        - この確認を、取得の前（start_hook より前）と、書く直前の2回行う。2回の結果
          （realpath と、フォルダの装置番号・i ノード番号）が違えば、書かずに止まる。
        - 本体は realpath にしたフォルダの下の名前を O_CREAT | O_EXCL | O_NOFOLLOW で開く。
          同じ名前のもの（シンボリックリンクを含む）があれば開かずに止まる。開いたあと、
          通常のファイルであること、リンクの数が1であること、フォルダの realpath と
          i ノード番号が変わっていないことを確かめる。
        - マニフェストは realpath にしたフォルダの下の名前を O_NOFOLLOW で開く（読むときも
          追記のときも）。シンボリックリンクなら開けずに止まる。開いたあと、通常のファイル
          であることを確かめる。最後の行に改行があるかは、追記に使う同じ記述子で確かめる。
        - root に対する相対の位置は、realpath どうしで計算する（マニフェストの行には
          パスを入れないので、相対パスは確認にだけ使う）。
      確かめられないこと
        - 確かめてから開くまでのあいだに、同じ利用者の別のプロセスが途中のフォルダを
          差し替える競合は、開いたあとの照合で見つけて止まる。ただし、その時点で書いて
          しまったものは消さない（ファイルを削除する処理は無い）。
        - root が本当にプロジェクトのルートであるかは、呼び出し側の引数に頼る（本番の入口は
          自分の置き場所から決めた root を渡し、引数では変えさせない）。
        - .git の有無で Git の外かを判定するので、GIT_DIR などの環境変数で作業ツリーを
          別の場所に指定している場合は見分けられない。
        - 保存先が同期フォルダ（iCloud の「デスクトップと書類」など）の中にあるかは確かめない。
          デスクトップを同期している場合、本体は同期先にも送られる（手順書に書いた）。

    同じ名前のファイルがあれば上書きせずに止まる（取得の前に確かめ、書くときにも O_EXCL で
    確かめる。書くときに重なった場合も FilelistError で止まる）。マニフェストの最後の行に
    改行が無い場合は、追記すると前の行とつながってしまうので、取得の前とも追記の直前とも、
    止まる。ファイルを削除する処理は無い。

    書く前に、書く中身（一覧とマニフェストの行）を privacy_scan.find_in_bytes() で
    調べ、メールアドレスの形の文字列があれば書かずに止まる。

------------------------------------------------------------------------
6. 封印の記録を呼ぶ口（acquisition-start と acquisition-result）
------------------------------------------------------------------------
    run_acquisition() の流れは次の順に固定している（docs/verify/periods-seal.md 7章）。

      1. URL を許可リストで調べる。5章の保存先の確認をし、同じ名前のファイルが無いこと、
         マニフェストの最後の行に改行があることを確かめる。どれかが違えば止まる
      2. start_hook(code_sha256=..., source_url=...) を呼ぶ。
         acquisition-start の記録を追記し、その seq（正の整数）を返すこと。
         例外が出るか、正の整数（bool を除く）が返らなければ、取得せずに止まる
      3. 一覧を取得し、3章のとおり 2020-12-15 以降の行を捨て、項目を絞る
      4. 保存先の確認をもう一度行い、本体を Git の外に書き、sha256 を書いたファイルから
         計算し直して照合する。マニフェストに1行追記する
      5. result_hook(start_seq=<2の seq>, kept_rows_sha256=<4の sha256>) を呼ぶ

    3 か 4 で失敗した場合、result_hook は呼ばない（result の無い start は、取得の途中か
    失敗として verify に表示される）。

    5 の result_hook が失敗した場合（例外は呼び出し元にそのまま出る）は、次の状態で残る。
      - 一覧のファイルとマニフェストの行は、書かれたまま残る（消さない）。
      - 封印の記録は、result の無い acquisition-start になる。
      - マニフェストの行の acquisition_start_seq が、その start の seq を指すので、どの start の
        取得だったかは照合できる。マニフェストの sha256 を使って result を後から追記するか、
        取得をやり直すかは、このモジュールでは決めない（リードに報告する）。

    start_hook と result_hook は、入口のスクリプト acquire_filelist.py のアダプタが封印係の
    seal_acquisition（T-009）につなぐ。このモジュールには既定の値を置かない（呼び忘れて
    記録なしで取得できないように、必須の引数にしている）。

    code_sha256 は、入口のスクリプト（CODE_REL = src/collector/acquire_filelist.py。この
    ファイルと同じフォルダの ENTRY_NAME）のバイト列の sha256 である（T-015。T-009 の監査 M-2）。
    封印の仕組みも同じパスのファイルの sha256 を計算し、アダプタが二つを照合する。
    入口のスクリプトは、このファイル（filelist.py）と privacy_scan.py の sha256 を定数として
    中に持ち、実行の最初に照合する。そのため、入口のスクリプトの sha256 が決まれば、
    取得のコードの3つのファイルがすべて決まる。

外部のライブラリは使わない（Python 3 の標準ライブラリだけ）。
"""

import datetime
import getpass
import hashlib
import http.client
import importlib.util
import json
import os
import re
import socket
import stat
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

# ---------------------------------------------------------------------------
# 定数（2章・3章・4章）
# ---------------------------------------------------------------------------

ALLOWED_SCHEME = "https"
ALLOWED_HOST = "data.gdeltproject.org"
ALLOWED_LIST_PATHS = frozenset({"/gdeltv2/masterfilelist.txt"})
MASTERFILELIST_URL = "https://data.gdeltproject.org/gdeltv2/masterfilelist.txt"

# 公式の値は無い（2章）。このプロジェクトが決めた値。
REQUEST_TIMEOUT_SECONDS = 60
TOTAL_DEADLINE_SECONDS = 1800
MAX_ATTEMPTS = 3
RETRY_WAIT_SECONDS = (60, 300)
MAX_RETRY_AFTER_SECONDS = 900
MAX_LINE_BYTES = 4096
MAX_RESPONSE_BYTES = 2 * 1024 ** 3
RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})
READ_ERRORS = (urllib.error.URLError, socket.timeout, TimeoutError,
               ConnectionError, http.client.HTTPException, OSError)

USER_AGENT = "news-digital-stick-chart-collector/0"

# 閾値を決める期間の区画の始まり（docs/stats/periods.md 1章、src/stats/periods.py の
# FROZEN_BLOCKS）。テストが periods.py の値と照合する。
CUTOFF_DAY = datetime.date(2020, 12, 15)
FILE_SPAN = datetime.timedelta(minutes=15)
TIME_RESOLUTION = datetime.timedelta(seconds=1)
# 残す行の最後の時刻。t <= LAST_KEPT_TIME と file_day(t) < CUTOFF_DAY は同じ条件である
# （ファイル名の時刻の分解能は1秒）。テストが両者の一致を確かめる。
LAST_KEPT_TIME = (datetime.datetime.combine(CUTOFF_DAY, datetime.time(),
                                            tzinfo=datetime.timezone.utc)
                  - FILE_SPAN)

# 保存する項目（5章）。この順に書く。
FIELDS = ("file_time", "file_type", "size_bytes", "md5")
FILE_TYPES = {
    b"export.CSV.zip": "export",
    b"mentions.CSV.zip": "mentions",
    b"gkg.csv.zip": "gkg",
}

MANIFEST_NAME = "gdelt-filelist.jsonl"
# マニフェストの置き場（5章）。root からの相対で固定。
MANIFEST_DIR_PARTS = ("data", "manifest")
# 本体の保存先（5章）。ホームからの相対で固定。プロジェクトの外。
FIXED_STORE_PARTS = ("Desktop", "news-stick-data", "gdelt-filelist")
STORE_LOCATION_NAME = "~/" + "/".join(FIXED_STORE_PARTS)
STORE_NAME_RE = re.compile(r"\Amasterfilelist-kept-\d{8}T\d{6}Z\.tsv\Z")
MANIFEST_KEYS = ("acquisition_start_seq", "code_path", "code_sha256", "fetched_at", "file_name",
                 "kept_rows", "sha256", "source_url", "store_location")
# 取得のコード（6章）。入口のスクリプト。封印の記録の fetch.code_path と同じ値。
ENTRY_NAME = "acquire_filelist.py"
CODE_REL = "src/collector/" + ENTRY_NAME

_TS_IN_NAME = re.compile(rb"/(\d{14})\.[^/]*\Z")
_SIZE = re.compile(rb"\A[0-9]{1,15}\Z")
_MD5 = re.compile(rb"\A[0-9a-f]{32}\Z")
_ROW_URL = re.compile(
    rb"\Ahttps?://data\.gdeltproject\.org/gdeltv2/(\d{14})\.("
    + b"|".join(re.escape(k) for k in FILE_TYPES)
    + rb")\Z")

HERE = os.path.dirname(os.path.abspath(__file__))


class FilelistError(Exception):
    """取得・保存の失敗。文には、捨てた行・応答の中身・URL を入れない。"""


# ---------------------------------------------------------------------------
# privacy_scan（同じフォルダ）
# ---------------------------------------------------------------------------

def _load_privacy_scan():
    path = os.path.join(HERE, "privacy_scan.py")
    spec = importlib.util.spec_from_file_location("privacy_scan", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


privacy_scan = _load_privacy_scan()


# ---------------------------------------------------------------------------
# 1章：URL の許可リスト
# ---------------------------------------------------------------------------

def validate_url(url):
    """許可した取得元の URL なら None を返し、そうでなければ FilelistError。

    文には URL を入れない（利用者情報の形でメールアドレスが入りうるため）。
    """
    if not isinstance(url, str) or not url.isascii():
        raise FilelistError("URL が ASCII の文字列でない")
    if any(c in url for c in "%\\@ \t\r\n") or "//" in url.partition("://")[2]:
        raise FilelistError("URL に許可しない文字か形がある")
    parts = urllib.parse.urlsplit(url)
    if parts.scheme != ALLOWED_SCHEME:
        raise FilelistError("URL のスキームが https でない")
    if parts.username is not None or parts.password is not None:
        raise FilelistError("URL に利用者情報がある")
    if parts.netloc != ALLOWED_HOST or parts.hostname != ALLOWED_HOST:
        raise FilelistError("URL のホストが許可リストに無い")
    if parts.port is not None:
        raise FilelistError("URL にポートがある")
    if parts.query or parts.fragment or url.endswith(("?", "#")):
        raise FilelistError("URL にクエリかフラグメントがある")
    segments = parts.path.split("/")
    if "." in segments or ".." in segments:
        raise FilelistError("URL のパスに . か .. がある")
    if parts.path not in ALLOWED_LIST_PATHS:
        raise FilelistError("URL のパスが許可リストに無い")
    if url != "%s://%s%s" % (ALLOWED_SCHEME, ALLOWED_HOST, parts.path):
        raise FilelistError("URL が正規の形でない")


# ---------------------------------------------------------------------------
# 通信（差し替えられる部分）
# ---------------------------------------------------------------------------

class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """自動のリダイレクトをしない。None を返すと、urllib は 3xx を HTTPError にする。"""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def build_opener():
    return urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect)


def urllib_transport(url, timeout):
    """既定の通信。応答（.status、.headers.get、.readline(n)、.close() を持つ）を返す。

    HTTP の失敗の応答（4xx・5xx・3xx）は、例外にせず応答として返す。
    """
    validate_url(url)
    req = urllib.request.Request(url, headers={
        "User-Agent": USER_AGENT,
        "Accept-Encoding": "identity",
    })
    try:
        return build_opener().open(req, timeout=timeout)
    except urllib.error.HTTPError as e:
        return e


# ---------------------------------------------------------------------------
# 4章：ファイルの日
# ---------------------------------------------------------------------------

def parse_file_time(ts):
    """14桁の時刻（bytes か str）を UTC の datetime にする。正しくなければ None。"""
    if isinstance(ts, bytes):
        ts = ts.decode("ascii")
    if len(ts) != 14 or not ts.isdigit():
        return None
    try:
        return datetime.datetime.strptime(ts, "%Y%m%d%H%M%S").replace(
            tzinfo=datetime.timezone.utc)
    except ValueError:
        return None


def file_day(t):
    """ファイル名の時刻 t（UTC の datetime）からファイルの日を決める（4章）。

    暦の最後（9999-12-31 23:45:01 以降）で日付を作れない場合は date.max を返す
    （含みうる最も遅い日なので、どの区画の境目よりも後になる）。
    """
    try:
        return (t + FILE_SPAN - TIME_RESOLUTION).date()
    except OverflowError:
        return datetime.date.max


def _is_kept_line(line):
    """3章の (a)(b)。2020-12-14 以前と判定できた行なら True、それ以外は False。

    どんな中身の行でも例外を出さない。日付の計算より先に、時刻を LAST_KEPT_TIME と比べる。
    """
    try:
        fields = line.split()
        if len(fields) != 3:
            return False
        m = _TS_IN_NAME.search(fields[2])
        if m is None:
            return False
        t = parse_file_time(m.group(1))
        if t is None or t > LAST_KEPT_TIME:
            return False
        return file_day(t) < CUTOFF_DAY
    except Exception:
        return False


# ---------------------------------------------------------------------------
# 3章：読みながら捨てる
# ---------------------------------------------------------------------------

def _read_kept_lines(resp, clock, deadline):
    """応答を1行ずつ読み、2020-12-14 以前と判定できた行だけを返す。

    各行について最初に行うのは、ファイルの日の判定と、CUTOFF_DAY 以降の行の破棄である。
    捨てた行は数えず、どこにも出さない。
    """
    kept = []
    total = 0
    while True:
        if clock() > deadline:
            raise FilelistError("取得全体の時間の上限を超えたので打ち切った")
        line = resp.readline(MAX_LINE_BYTES + 1)
        if not line:
            break
        total += len(line)
        if total > MAX_RESPONSE_BYTES:
            raise FilelistError("応答の長さの上限を超えたので打ち切った")
        if len(line) > MAX_LINE_BYTES and not line.endswith(b"\n"):
            # 長すぎる行：残りを読み飛ばし、判定できない行として捨てる
            while line and not line.endswith(b"\n"):
                line = resp.readline(MAX_LINE_BYTES + 1)
                total += len(line)
                if total > MAX_RESPONSE_BYTES:
                    raise FilelistError("応答の長さの上限を超えたので打ち切った")
            continue
        if not _is_kept_line(line):
            continue  # 捨てる。数えない・出さない
        kept.append(line)
    return kept


# ---------------------------------------------------------------------------
# 5章：項目を絞る
# ---------------------------------------------------------------------------

def parse_kept_line(line):
    """2020-12-14 以前と判定済みの行から、許可リストの項目だけを取り出す。

    形式が合わなければ None。返り値は (file_time, file_type, size_bytes, md5) の str。
    """
    fields = line.split()
    if len(fields) != 3:
        return None
    size, md5, url = fields
    if not _SIZE.match(size) or not _MD5.match(md5):
        return None
    m = _ROW_URL.match(url)
    if m is None:
        return None
    ts, suffix = m.group(1), m.group(2)
    return (ts.decode("ascii"), FILE_TYPES[suffix],
            str(int(size.decode("ascii"))), md5.decode("ascii"))


def serialize_rows(rows):
    """5章の書き方でバイト列にする。"""
    out = ["\t".join(FIELDS)]
    for r in sorted(rows, key=lambda r: (r[0], r[1], int(r[2]), r[3])):
        out.append("\t".join(r))
    return ("\n".join(out) + "\n").encode("ascii")


# ---------------------------------------------------------------------------
# 取得（再試行つき）
# ---------------------------------------------------------------------------

def _retry_after(resp):
    try:
        value = resp.headers.get("Retry-After")
    except Exception:
        return None
    if value is None:
        return None
    value = str(value).strip()
    return int(value) if value.isdigit() else None


def fetch_kept_lines(url, transport, sleep, clock, log):
    """一覧を取得し、2020-12-14 以前と判定できた行（bytes の list）を返す。"""
    validate_url(url)
    deadline = clock() + TOTAL_DEADLINE_SECONDS
    for attempt in range(1, MAX_ATTEMPTS + 1):
        log("一覧の取得：試行 %d/%d" % (attempt, MAX_ATTEMPTS))
        wait = None
        resp = None
        try:
            resp = transport(url, REQUEST_TIMEOUT_SECONDS)
            status = getattr(resp, "status", None)
            if status is None:
                status = getattr(resp, "code", None)
            if status == 200:
                enc = resp.headers.get("Content-Encoding")
                if enc not in (None, "", "identity"):
                    raise FilelistError("応答が圧縮されている（Content-Encoding）")
                return _read_kept_lines(resp, clock, deadline)
            if isinstance(status, int) and status in RETRY_STATUSES:
                ra = _retry_after(resp)
                if ra is not None and ra > MAX_RETRY_AFTER_SECONDS:
                    raise FilelistError("HTTP %d。Retry-After が上限を超えたので打ち切った"
                                        % status)
                wait = ra
                log("HTTP %d" % status)
            else:
                raise FilelistError("HTTP %s。再試行しない応答なので打ち切った" % status)
        except FilelistError:
            raise
        except READ_ERRORS as e:
            log("通信の失敗（%s）" % type(e).__name__)
        finally:
            if resp is not None:
                try:
                    resp.close()
                except Exception:
                    pass
        if attempt == MAX_ATTEMPTS:
            break
        base = RETRY_WAIT_SECONDS[attempt - 1]
        wait = base if wait is None else max(base, wait)
        if clock() + wait > deadline:
            raise FilelistError("取得全体の時間の上限を超えるので打ち切った")
        log("%d 秒待って再試行する" % wait)
        sleep(wait)
    raise FilelistError("試行の回数の上限（%d 回）に達したので打ち切った" % MAX_ATTEMPTS)


# ---------------------------------------------------------------------------
# 6章：取得の流れ（start → 取得 → 保存 → result）
# ---------------------------------------------------------------------------

def code_sha256():
    """取得のコード（入口のスクリプト ENTRY_NAME）のバイト列の sha256（6章）。"""
    with open(os.path.join(HERE, ENTRY_NAME), "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def _utc_now():
    return datetime.datetime.now(datetime.timezone.utc)


def _stamp(dt):
    return dt.astimezone(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _iso(dt):
    return dt.astimezone(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _stderr_log(msg):
    print("filelist: " + msg, file=sys.stderr)


def _check_no_address(data, what):
    if privacy_scan.find_in_bytes(data):
        raise FilelistError("%s にメールアドレスの形の文字列があるので書かずに止まる" % what)


def fixed_store_dir(home):
    """本体の保存先（5章）。<home>/Desktop/news-stick-data/gdelt-filelist。"""
    return os.path.join(home, *FIXED_STORE_PARTS)


def _is_strictly_under(path_real, root_real):
    """realpath どうしで、path が root の下にあり root そのものでなければ True。"""
    if os.path.commonpath([path_real, root_real]) != root_real or path_real == root_real:
        return False
    rel = os.path.relpath(path_real, root_real)
    return rel != os.curdir and not rel.startswith(os.pardir)


def _inside_git_worktree(path_real):
    """path かその上のどれかのフォルダに .git があれば True。"""
    d = path_real
    while True:
        if os.path.lexists(os.path.join(d, ".git")):
            return True
        parent = os.path.dirname(d)
        if parent == d:
            return False
        d = parent


def _dir_id(path_real):
    st = os.stat(path_real, follow_symlinks=False)
    if not stat.S_ISDIR(st.st_mode):
        raise FilelistError("保存先がフォルダでない")
    return (st.st_dev, st.st_ino)


def _resolve_paths(root, store_dir, home):
    """5章の保存先の確認。realpath にした場所と、フォルダの識別子を返す。"""
    root_real = os.path.realpath(root)
    manifest_dir = os.path.join(root, *MANIFEST_DIR_PARTS)
    manifest_real = os.path.realpath(manifest_dir)
    store_real = os.path.realpath(store_dir)
    for d in (root_real, manifest_real, store_real):
        if not os.path.isdir(d):
            raise FilelistError("root・マニフェスト・本体の保存先のどれかが既にあるフォルダでない")
    if not _is_strictly_under(manifest_real, root_real):
        raise FilelistError("マニフェストの保存先が root の下に無い")
    rel_parts = os.path.relpath(manifest_real, root_real).split(os.sep)
    if ".git" in rel_parts:
        raise FilelistError("マニフェストの保存先が .git の下にある")
    if manifest_real != os.path.join(root_real, *MANIFEST_DIR_PARTS):
        raise FilelistError("マニフェストの保存先が root の data/manifest でない"
                            "（途中にシンボリックリンクがある）")
    if store_real == root_real or _is_strictly_under(store_real, root_real):
        raise FilelistError("本体の保存先が root の下にある（Git の外に置く）")
    if _inside_git_worktree(store_real):
        raise FilelistError("本体の保存先が Git の作業ツリーの中にある（Git の外に置く）")
    fixed = fixed_store_dir(home)
    if store_real != os.path.realpath(fixed):
        raise FilelistError("本体の保存先が、決まった場所 %s でない" % STORE_LOCATION_NAME)
    for depth in (1, 2):  # news-stick-data と gdelt-filelist の2段
        d = os.path.join(home, *FIXED_STORE_PARTS[:len(FIXED_STORE_PARTS) - 2 + depth])
        try:
            st = os.lstat(d)
        except OSError:
            raise FilelistError("本体の保存先のフォルダが無い（%s）" % STORE_LOCATION_NAME) from None
        if not stat.S_ISDIR(st.st_mode):
            raise FilelistError("本体の保存先の2段のフォルダのどちらかが、シンボリックリンクか"
                                "フォルダでない（%s）" % STORE_LOCATION_NAME)
    manifest_path = os.path.join(manifest_real, MANIFEST_NAME)
    if not _is_strictly_under(manifest_path, root_real):
        raise FilelistError("マニフェストが root の下に無い")
    return {
        "root": root_real,
        "manifest_dir": manifest_real,
        "manifest_path": manifest_path,
        "store_dir": store_real,
        "ids": (_dir_id(root_real), _dir_id(manifest_real), _dir_id(store_real)),
    }


def _open_manifest(path, flags):
    """マニフェストを O_NOFOLLOW で開き、通常のファイルであることを確かめた fd を返す。"""
    try:
        fd = os.open(path, flags | os.O_NOFOLLOW | os.O_CLOEXEC, 0o644)
    except FileNotFoundError:
        raise
    except OSError:
        raise FilelistError("マニフェストを開けない（シンボリックリンクか、開けないもの）") from None
    if not stat.S_ISREG(os.fstat(fd).st_mode):
        os.close(fd)
        raise FilelistError("マニフェストが通常のファイルでない")
    return fd


def _fd_ends_with_newline(fd):
    size = os.fstat(fd).st_size
    if size == 0:
        return True
    return os.pread(fd, 1, size - 1) == b"\n"


def _manifest_ends_with_newline(path):
    """マニフェストが無いか空か、最後が改行で終わっていれば True。"""
    try:
        fd = _open_manifest(path, os.O_RDONLY)
    except FileNotFoundError:
        return True
    try:
        return _fd_ends_with_newline(fd)
    finally:
        os.close(fd)


def _write_all(fd, data):
    view = memoryview(data)
    while view:
        n = os.write(fd, view)
        view = view[n:]


def _write_store(paths, name, data, sha):
    """本体を Git の外の保存先に書き、書いたものの sha256 を照合する（5章）。"""
    out_path = os.path.join(paths["store_dir"], name)
    try:
        fd = os.open(out_path, os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
                     | os.O_CLOEXEC, 0o644)
    except FileExistsError:
        raise FilelistError("同じ名前のファイルが書く直前にできていた（上書きしない）") from None
    except OSError:
        raise FilelistError("本体の保存先に書けない") from None
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or st.st_nlink != 1:
            raise FilelistError("本体が通常のファイルでない")
        if (os.path.realpath(os.path.dirname(out_path)) != paths["store_dir"]
                or _dir_id(paths["store_dir"]) != paths["ids"][2]):
            raise FilelistError("本体の保存先が書くあいだに変わった")
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
            raise FilelistError("書いたファイルの sha256 が一致しない")
    finally:
        os.close(fd)
    return out_path


def _append_manifest(paths, data):
    try:
        fd = _open_manifest(paths["manifest_path"], os.O_RDWR | os.O_APPEND | os.O_CREAT)
    except FileNotFoundError:
        raise FilelistError("マニフェストの保存先が追記のあいだに無くなった") from None
    try:
        if (os.path.realpath(paths["manifest_path"]) != paths["manifest_path"]
                or _dir_id(paths["manifest_dir"]) != paths["ids"][1]):
            raise FilelistError("マニフェストの保存先が追記のあいだに変わった")
        if not _fd_ends_with_newline(fd):
            raise FilelistError("マニフェストの最後の行に改行が無いので追記しない")
        _write_all(fd, data)
        os.fsync(fd)
    finally:
        os.close(fd)


def _local_markers(paths):
    """マニフェストに入ってはいけない、手元のパスとユーザー名。"""
    paths_out = {paths["root"], paths["store_dir"], paths["manifest_dir"],
                 os.path.realpath(os.path.expanduser("~")), os.path.expanduser("~")}
    users = set()
    try:
        users.add(getpass.getuser())
    except Exception:
        pass
    users.add(os.path.basename(os.path.expanduser("~")))
    return {p for p in paths_out if len(p) > 1}, {u for u in users if u}


def _check_manifest_entry(entry, line, paths):
    """マニフェストの行に、パス・ユーザー名・決めていない項目が無いことを確かめる。"""
    if tuple(sorted(entry)) != MANIFEST_KEYS:
        raise FilelistError("マニフェストの項目が決めた一覧と違う")
    if not STORE_NAME_RE.match(entry["file_name"]):
        raise FilelistError("マニフェストの file_name が決めた形でない")
    validate_url(entry["source_url"])
    text = line.decode("ascii")
    local_paths, users = _local_markers(paths)
    for p in local_paths:
        if p in text:
            raise FilelistError("マニフェストの行に手元のパスがあるので書かない")
    if entry["code_path"] != CODE_REL or entry["store_location"] != STORE_LOCATION_NAME:
        raise FilelistError("マニフェストの code_path か store_location が決めた値でない")
    # ユーザー名は、16進の値（sha256 など）と偶然に重なりうるので、文字列の項目だけで調べる
    for key in ("file_name", "fetched_at", "source_url", "store_location"):
        for u in users:
            if u in entry[key]:
                raise FilelistError("マニフェストの行にユーザー名があるので書かない")


def run_acquisition(*, start_hook, result_hook, root, store_dir, home,
                    url=MASTERFILELIST_URL, transport=urllib_transport,
                    sleep=time.sleep, clock=time.monotonic, now=_utc_now,
                    log=_stderr_log):
    """試運転の手順3。6章の順に動き、結果を dict で返す。

    start_hook(code_sha256=str, source_url=str) -> int（acquisition-start の seq）
    result_hook(start_seq=int, kept_rows_sha256=str) -> 何でもよい
    root: プロジェクトのルート。マニフェストは root/data/manifest に固定（5章）
    store_dir: 本体の保存先（Git の外）。<home>/Desktop/news-stick-data/gdelt-filelist と
        同じ場所でなければ止まる（5章）
    home: 利用者のホーム。本番の入口は pwd から決めたものを渡す
    返り値の "path" は本体の絶対パス（呼び出し側に返すだけで、どこにも書かない）。
    """
    validate_url(url)
    paths = _resolve_paths(root, store_dir, home)
    # 名前は一度だけ決め、前もっての確認と実際の書き込みに同じものを使う
    name = "masterfilelist-kept-%s.tsv" % _stamp(now())
    if os.path.lexists(os.path.join(paths["store_dir"], name)):
        raise FilelistError("同じ名前のファイルが既にある（上書きしない）")
    if not _manifest_ends_with_newline(paths["manifest_path"]):
        raise FilelistError("マニフェストの最後の行に改行が無いので取得しない")

    code_hash = code_sha256()
    seq = start_hook(code_sha256=code_hash, source_url=url)
    if isinstance(seq, bool) or not isinstance(seq, int) or seq <= 0:
        raise FilelistError("start_hook が正の整数の seq を返さなかったので取得しない")

    lines = fetch_kept_lines(url, transport, sleep, clock, log)
    fetched_at = now()

    rows = []
    rejected = 0
    for line in lines:
        r = parse_kept_line(line)
        if r is None:
            rejected += 1
        else:
            rows.append(r)
    del lines
    data = serialize_rows(rows)
    sha = hashlib.sha256(data).hexdigest()

    entry = {
        "file_name": name,
        "sha256": sha,
        "kept_rows": len(rows),
        "fetched_at": _iso(fetched_at),
        "source_url": url,
        "acquisition_start_seq": seq,
        "code_path": CODE_REL,
        "code_sha256": code_hash,
        "store_location": STORE_LOCATION_NAME,
    }
    manifest_line = (json.dumps(entry, sort_keys=True, ensure_ascii=True) + "\n").encode("ascii")

    _check_no_address(data, "一覧")
    _check_no_address(manifest_line, "マニフェストの行")
    # 書く直前にもう一度確かめる。取得の前と違えば書かない
    if _resolve_paths(root, store_dir, home) != paths:
        raise FilelistError("保存先が取得のあいだに変わったので書かない")
    _check_manifest_entry(entry, manifest_line, paths)
    out_path = _write_store(paths, name, data, sha)
    _append_manifest(paths, manifest_line)

    log("残した行：%d 件（2020-12-14 以前と判定できた行のうち、形式の合うもの）" % len(rows))
    log("形式の合わない行：%d 件（2020-12-14 以前と判定できた行のうち）" % rejected)
    log("保存：%s sha256=%s（本体は Git の外）" % (name, sha))

    result_hook(start_seq=seq, kept_rows_sha256=sha)
    return {
        "path": out_path,
        "file_name": name,
        "kept_rows_sha256": sha,
        "kept_rows": len(rows),
        "rejected_rows": rejected,
        "fetched_at": _iso(fetched_at),
        "start_seq": seq,
    }


if __name__ == "__main__":
    print("このモジュールはライブラリとしてだけ使う。取得は入口のスクリプト "
          "src/collector/acquire_filelist.py から行う（手順は src/collector/README.md）。",
          file=sys.stderr)
    sys.exit(2)
