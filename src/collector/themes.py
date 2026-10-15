#!/usr/bin/env python3
"""GKG のテーマの区分表（名前と説明の一覧）を取得し、件数の欄を捨てて保存する（T-018・T-021・T-098）。

データ出典
    Data: The GDELT Project (https://www.gdeltproject.org/). This project is not
    affiliated with or endorsed by the GDELT Project.
    データ出典：GDELT Project（https://www.gdeltproject.org/）。本プロジェクトは
    GDELT Project と提携・承認の関係にありません。

区分表は、統計係の除外の規則の封印（stats-order1）のあとで1回だけ取得する（オーナーの決定。
reviews/T-016.md の 2026-10-08 の発言：「件数の欄を捨てる条件で、区分表を1回取得してよい」。
取得元は同じサーバーの /api/v2/guides/）。取得したかどうかは、このファイルではなく、マニフェスト
data/manifest/gdelt-themes.jsonl の行で決まる。実行の入口は5章（T-098）。

------------------------------------------------------------------------
0. 取得の前の関門（require_exclusion_rules_sealed。T-021）
------------------------------------------------------------------------
    区分表は、統計係の除外の規則を封印したあとでだけ取得する（docs/stats/tags-naive.md 5章の
    順番1：除外の規則を区分表の取得より前に封印する）。run() は、通信の前に最初にこの関門を
    呼ぶ。関門が確かめること：
      - 除外の規則の封印の記録の種類（EXCLUSION_RULE_KIND）は "stats-order1"（統計係の順番1。
        封印係の T-037 で決まった。src/sealer/ledger.py の ORDER1_KIND と同じことをテストで
        確かめる。T-032）。
      - その kind が、封印の記録の種類の許可リスト（src/sealer/ledger.py の ALLOWED_KINDS）に
        入っている。
      - 封印の記録（sealed/ledger.jsonl）の鎖と、すべての seq の .ots が検証に通る
        （ledger._load_for_gate。プロジェクトのルートは ledger.PROJECT_ROOT に固定）。
      - その kind の記録がちょうど1件ある（封印係の check_stats_order が、stats-order1 を1件に
        限っている。0件なら止まり、2件以上でも止まる）。
      - run() に渡した root が、関門が読んだプロジェクトと同じ。
    確かめないこと：記録の中身（どの規則を封印したか）の照合。それは封印係が kind と一緒に
    決める照合の仕組みで行う。

------------------------------------------------------------------------
0.1 コードの関門と「1回だけ」の記録（T-021 の差し戻し1回目 中3）
------------------------------------------------------------------------
    順番：コードの関門を先に、除外の規則の関門をそのあとに通す（差し戻し2回目 軽-2。関門が
    読み込む ledger.py を含めて、固定したコードで動くことを先に確かめる）。
    - コードの関門（_code_gate）：src/collector と src/sealer に未コミットの変更・無視される
      ファイル・skip-worktree の印が無く（codegate.check_clean）、動いている themes.py と privacy_scan.py
      が HEAD にコミットした中身と同じであること。区分表の取得は、このファイル（2.1 の名前の欄
      だけを残す規則を含む）をコミットしたあとの、その code_sha256 のコードでだけ行う。
    - 1回だけの取得（オーナーの承認「1回取得してよい」）は2段で行う（差し戻し3回目 軽-2）。
      1段目：マニフェスト data/manifest/gdelt-themes.jsonl が作業ツリーにも HEAD にも無ければ、
      試行の行（kind が attempt。code_sha256・source_url・attempted_at・除外の規則の封印の記録の
      seq と sha256）を書いて AttemptRecorded で止まる（通信しない）。
      2段目（試行の行をコミットしたあと）：作業ツリーのマニフェストが HEAD とちょうど同じで、
      中身がこのコードとこの除外の規則の記録の試行の行1行だけのときに限り、kind が fetch の
      行を書いてから通信する。止まれば failed の行、成功すれば result の行を書く。
      それ以外（コミットしていない変更がある・並びが違う）なら、通信せずに止まる。取り直しは 0.2章。
      1段目の前提（T-026 軽-3）：git log --all -- data/manifest/gdelt-themes.jsonl が空である
      こと（マニフェストを git mv で別の名前に移しても、元の名前の履歴が残るので止まる）と、
      保存先（~/Desktop/news-stick-data）に gdelt-themes- で始まるファイルが無いこと。
      限界：履歴そのものを書き換えること（git reset・rebase・filter-branch など）は見分けられない。
      失敗した取得は fetch と failed の行として記録に残る。
      限界（前提 → 結論）：通信のあとの行（fetch・failed）は、コミットする前は作業ツリーに
      だけある → その行を消して HEAD と同じ形に戻すと、もう一度通信できる。2段目のあとすぐに
      コミットする。
    - 結果の行と試行の行には、除外の規則の関門が返した記録の seq と sha256
      （exclusion_rule_seq・exclusion_rule_record_sha256）を書く（差し戻し2回目 中-B）。

------------------------------------------------------------------------
0.2 取り直し（T-101。オーナーの承認：reviews/T-098.md の 2026-10-15 の発言「あと2回」）
------------------------------------------------------------------------
    - マニフェストは追記だけ。前の行は消さず、変えない。行の並び（MANIFEST_NEXT）：
        attempt → fetch → failed か result。failed のあとは次の attempt だけ。result のあとは無し。
      並びが違えば止まる（parse_manifest）。
    - 回数は記録から数える：マニフェストの attempt の行の数。上限は MAX_TOTAL_ATTEMPTS（3。最初の
      1回と承認の2回）。自分で番号を書くことはしない（取り直しの attempt の行は、最初の attempt と
      同じキー：kind・attempted_at・code_path・code_sha256・source_url・exclusion_rule_seq・
      exclusion_rule_record_sha256）。
    - 作業ツリーのマニフェストが HEAD と同じことを、毎回はじめに求める（2段の手順は毎回同じ）。
      最後の行で決める：
        failed：取り直しの1段目。attempt の行がすでに上限の数なら、何も書かず、通信せずに止まる。
                そうでなければ新しい attempt の行を追記して AttemptRecorded で止まる。
        attempt：2段目。その行がこのコードとこの除外の規則のものなら、fetch の行を書いて通信する。
        result：それ以上は取得しない。fetch：前の通信の途中で止まった跡なので止まる。
    - 1段目と2段目の前に、保存先に gdelt-themes- で始まるファイルが無いことを確かめる（failed の
      取得はファイルを書かないので、あれば別の跡）。
    - failed の行の形（T-101 差し戻し1回目 中-3）：キーは at・kind・reason・stage。stage は止まった
      段を FAILED_STAGES の固定の語で書く（fetch：通信、read：表として読む、shape：欄の判定、
      write：書く前のメールアドレスの形の検査）。reason は今までどおり例外の型の名前。

------------------------------------------------------------------------
0.3 追記だけであることの関門（T-101 差し戻し1回目 重大-1）
------------------------------------------------------------------------
    - コードの関門のすぐあとで、git log --all --full-history に現れるマニフェストの各版
      （_manifest_versions。その commit で消した版は空）が、どれも HEAD の版の先頭部分であることを
      求める（check_append_only）。行を消して普通にコミットし直した跡、途中の1組だけを消した跡、
      行を変えた跡があれば、通信の前に止まる。
    - 回数は、履歴の各版の attempt の行の数の最大値と、HEAD の版の数のうち大きい方で数える。
    - 浅い clone と graft のファイルがあれば止まる（check_no_graft_or_shallow。差し戻し2回目 中-2）。
      置き換えの参照（refs/replace/）は、コードの関門（codegate.check_clean）が止める。
    - 履歴は --reflog も合わせて見る（差し戻し2回目 中-2）。理由（前提 → 結論）：この関門は取得する
      機械の上で、取得の前に動く。reflog はその機械にある → 枝を消す・reset・amend で --all から
      外れた過去の版も、reflog の期限（既定で90日、届かない commit は30日）までは見つかる。止める
      方向にしか働かない（版が増えても、追記だけなら先頭部分であることは変わらない）。
    - 限界：過去の版を履歴と reflog の両方から消すこと（reset・rebase・filter-branch・枝を消すこと
      （orphan で始め直して元の枝を消す）のあとで reflog を消すか期限切れにして gc する）は
      見分けられない。reflog は clone に入らないので、第三者の照合（verify）には使えない。

------------------------------------------------------------------------
1. 取得元と通信
------------------------------------------------------------------------
    - https://data.gdeltproject.org/api/v2/guides/<名前> の形で、名前が ALLOWED_GUIDE_FILES
      （LOOKUP-GKGTHEMES.TXT の1つだけ。全テーマの区分表。オーナーの承認の範囲）に入るものだけを
      許す（validate_doc_url）。大文字と小文字も同じでなければならない。ほかの名前（言語・国・
      画像のタグなどの一覧）、ほかのパス（/documentation/ を含む）、ほかのホスト
      （gdeltcloud.com を含む）、http、ポート・クエリ・フラグメント・「..」・「%」は拒む。
    - 要求は1回だけ（MAX_ATTEMPTS = 1。再試行しない）。リダイレクトとプロキシは使わない。
      待ちの上限は REQUEST_TIMEOUT_SECONDS（60秒）、全体の上限 TOTAL_DEADLINE_SECONDS（300秒）、
      応答の長さの上限 MAX_BYTES（50 MB）。1回だけなので、速度の制限に当たる量ではない。
    - 応答はメモリの上だけで扱い、元の応答をそのままディスクに書かない。応答全体の sha256 も
      長さも記録しない（件数の欄を含む元の中身に結びつくため）。

------------------------------------------------------------------------
2. 欄の見出しの確認と、件数の欄を捨てる規則（classify_columns）
------------------------------------------------------------------------
    件数・報道量・頻度の欄は、2020-12-15 以降を含む全期間の情報になりうるので、ディスクに書く
    前に捨てる。規則（見出しの名前と値だけで機械的に決まる）：
      - 見出しの行が無い形（1行目の値に数字だけの欄がある、など）は、どれが件数の欄かを見出しで
        確かめられないので、何も書かずに止まる（ThemesError）。
      - 見出しが KEEP_HEADER_RE（名前・説明・種類など）に当たらない欄、DROP_HEADER_RE（件数・
        頻度など）に当たる欄は、すべて捨てる。知らない欄は捨てる側に倒す。
      - テーマの名前の欄（見出しが NAME_HEADER_RE に当たる欄）は、すべての値が THEME_NAME_RE
        （英大文字で始まり、英大文字・数字・下線だけ）に完全に合わなければならない。合わない値が
        1つでもあれば、何も書かずに止まる（「QQ_A (1234)」のように名前に件数を足した形を
        書かないため）。名前の欄が1つも無い場合も止まる。
      - 名前以外の残す欄（説明・種類など）は、数字（半角・全角）を含む値が1つでもあれば、
        欄ごと捨てる（「Seen in 1,234,567 articles」「12.3k」「1 234」のような件数を書かない
        ため）。数字の判定（has_numeric）は、Unicode で数を表す文字すべて（str.isnumeric。
        半角・全角・アラビア文字などの十進の数字、上付き・下付きの数字（² ₃）、丸付きの数字、
        分数（½）、ローマ数字（Ⅻ）、漢数字（一・万）など）を数字とみなす（T-021。T-018 の監査
        軽3）。止まらずに欄ごと捨てる理由：取得は1回だけなので、止めると名前の欄まで失う。
        名前の欄が残れば区分表の目的（除外の規則をテーマの名前に当てる）は果たせ、捨てた欄の
        見出しはマニフェストの dropped_columns に残る。
      - 見出しの行の判定も同じ数字の判定を使う。見出しの値が、数字と区切り（, . 空白 + - _ '）
        だけでできていれば（「１２３」「²³」を含む）、見出しの無い形とみなして止まる。
      - 捨てた欄の見出しの名前はマニフェストの dropped_columns に出す。ただし、見出しに数字が
        あれば、名前の代わりに欄の位置（column_A、column_B …。英字だけ）を出す（見出しに件数が
        紛れた形「Count (1,234,567)」を書かないため）。
      - xlsx のシート名：シートが複数あるときは、シート名を sheet の欄の値として書く。シート名に
        数字があれば、すべてのシートの名前の代わりに位置（sheet_A、sheet_B …）を書き、
        マニフェストの sheet_names_replaced を true にする（「Themes (12,345)」を書かないため）。
        シートが1つのときは、シート名を書かない。
      - 限界：数字を使わずに書いた量（「one million」など）は見分けられない。
    保存するのは、残した欄の見出しと値だけ。

------------------------------------------------------------------------
2.1 見出しの無い「名前・件数」の2欄の表（T-021 の差し戻し1回目。リードの判断、監査の条件）
------------------------------------------------------------------------
    1行目の値に数字だけの値がある（見出しの無い形）とき、次の条件をすべて満たす場合に限り、
    名前の欄だけを残す（headerless_name_count）。満たさなければ、これまでどおり止まる。
      (1) どの行も、欄がちょうど2つ。
      (2) 一方の欄の値がすべて THEME_NAME_RE に合い、もう一方の欄の値がすべて ASCII の数字
          （0〜9）だけ。判定は欄の位置ではなく値の形で行う。
      (3) (2) に合う割り当て（どちらが名前の欄か）が、ちょうど1つ。両方の割り当てが合う場合と、
          どちらも合わない場合は止まる。
      (4) 残すのは名前の欄だけで、見出しは THEME とする。件数の欄はメモリの上で捨て、見出しの
          代わりに欄の位置（column_A か column_B）をマニフェストの dropped_columns に書く。
          行は並べ替えてから書く（元の並び＝件数の順を残さないため）。マニフェストの
          headerless を true にする。
    限界：区分表は取得した時点の全テーマの一覧なので、2020-12-15 以降に生まれたテーマの名前も
    入る。名前があることは、そのテーマが後ろの期間に使われたことを示しうる。タグの一覧の規則は
    手法を作る期間のデータで存在を確かめるので、名前だけでは一覧に入らない。

------------------------------------------------------------------------
3. 読める形
------------------------------------------------------------------------
    タブ区切りか、カンマ区切りの文字（.txt・.tsv・.csv。UTF-8）と、.xlsx（zip の中の XML を
    標準ライブラリで読む。最初の行を見出しとし、シートが複数あれば sheet の欄を足す）。
    それ以外の形は止まる。

------------------------------------------------------------------------
4. 保存とマニフェスト
------------------------------------------------------------------------
    本体：<home>/Desktop/news-stick-data/gdelt-themes-<UTC 時刻>.tsv（Git の外。見出し＋行。
    行は値の順に並べ替える。改行は LF、UTF-8）。O_CREAT | O_EXCL | O_NOFOLLOW で書く。
    マニフェスト：<root>/data/manifest/gdelt-themes.jsonl に1行追記（file_name、sha256、rows、
    kept_columns、dropped_columns、fetched_at、source_url、code_path、code_sha256、
    store_location）。
    書く前に privacy_scan.find_in_bytes で調べ、メールアドレスの形があれば書かずに止まる。

------------------------------------------------------------------------
5. 入口のコマンド（main。T-098）
------------------------------------------------------------------------
    プロジェクトのルートで、1段目と2段目とも同じコマンドを使う：
        .venv/bin/python -B src/collector/themes.py
    - 引数は受け付けない（取得元・保存先・時計は固定。引数があれば何もせずに終わり値 2）。
    - root はこのファイルの場所から決まるプロジェクトのルート（PROJECT）、home は環境変数 HOME
      ではなく利用者のデータベース（pwd.getpwuid(os.getuid())）から決める。
    - 終わり値：0 は取得して保存した（2段目）。3 は試行の行を書いて止まった（1段目。通信して
      いない。マニフェストをコミットしてから、同じコマンドをもう一度）。1 は関門や取得の失敗で
      止まった。2 は引数があった。
    - 表示するのは、ファイルの名前・行数・残した欄と捨てた欄の見出し・headerless・sha256・
      code_sha256・除外の規則の記録の seq と出典だけ。区分表の値（テーマの名前）は表示しない。

------------------------------------------------------------------------
6. 形の判定で止まったときの診断（diagnose_shape。T-101）
------------------------------------------------------------------------
    build_output（2章・2.1章の判定）で止まったとき、表の数と文字の種類だけを標準エラーに1行で
    出す。ファイル・マニフェストには書かない。failed の行の reason は今までどおり例外の型の名前で、
    stage は shape。診断の計算や出力が落ちても、failed の行は書く（軽-8）。
    名前の規則に合わない値のうち、数の形（NUMBER_SHAPE_RE：ASCII の数字と , . だけで、数字を含む）の
    値は、文字の種類の内訳などから外し、nonmatch_number_shaped に数だけを数える（差し戻し2回目
    中-3・軽-4）。合わない値の過半数が数の形の欄は、件数の欄らしい欄として count_like: true と
    values・ascii_digits_only・number_shaped だけを出す（捨てる欄から導いた数を出さない。軽-5）。
    そのほかの欄は count_like: false と下の数を出す。
    限界：エージェントが流すと、標準エラーの出力は会話の記録に残る（軽-6）。合わない値が1つだけの
    ときは、その長さの範囲と文字の種類ごとの数が分かる（テーマの名前は個人情報ではない）。
    値・テーマの名前・その断片・長さの一覧は出さない。出すもの：
      sheets（シートの数）、rows（行の数）、column_count_distribution（欄の数ごとの行の数）、
      columns_not_shown（DIAG_MAX_COLUMNS を超えて数を出さなかった欄の数）、
      first_row_numeric_columns（1行目で数字だけの値の欄の数）、
      columns（先頭から DIAG_MAX_COLUMNS 欄まで、欄ごとに）：values・empty・theme_name_match・
        theme_name_nonmatch・ascii_digits_only・nonmatch_number_shaped・
        nonmatch_first_char_not_upper・nonmatch_too_long
        （161文字以上）・nonmatch_values_with（合わない値のうち、その種類の文字を含む値の数）・
        nonmatch_chars（合わない値に含まれるその種類の文字の数）。文字の種類は upper・lower・
        digit・underscore・space・symbol（そのほかの ASCII）・non_ascii。
    読めなかった（UTF-8 でない・形式が違う）・通信の失敗のときは、表が無いので診断は出さない。

外部のライブラリは使わない（Python 3 の標準ライブラリだけ）。
"""

import csv
import datetime
import hashlib
import importlib.util
import io
import json
import os
import re
import socket
import stat
import sys
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))

ALLOWED_HOST = "data.gdeltproject.org"
# 1章：許す名前（オーナーの承認の範囲：全テーマの区分表だけ）
ALLOWED_GUIDE_FILES = ("LOOKUP-GKGTHEMES.TXT",)
THEMES_URL = "https://data.gdeltproject.org/api/v2/guides/" + ALLOWED_GUIDE_FILES[0]
_DOC_URL_RE = re.compile(
    r"\Ahttps://data\.gdeltproject\.org/api/v2/guides/([A-Za-z0-9][A-Za-z0-9._-]{0,127})\Z")
# 0章：除外の規則の封印の記録の種類。封印係の T-037 で決まった（ledger.ORDER1_KIND と同じ。T-032）
EXCLUSION_RULE_KIND = "stats-order1"
MAX_ATTEMPTS = 1                 # 1回の取得（attempt 1つ）の中で送る要求の数。再試行しない
# 0.2章：取得の試み（マニフェストの attempt の行）の合計の上限（T-101）。オーナーの承認：最初の1回と、
# 2026-10-15 の「あと2回」（reviews/T-098.md）。回数はマニフェストの attempt の行の数で数える
MAX_TOTAL_ATTEMPTS = 3
# 0.2章：failed の行の stage（止まった段。T-101 差し戻し1回目 中-3）。fetch：通信（HTTP・時間・長さ・
# 通信の失敗）、read：表として読む（UTF-8・形式）、shape：欄の判定（2章・2.1章）、write：書く前の検査
FAILED_STAGES = ("fetch", "read", "shape", "write")
# 0.2章：マニフェストの行の形（T-101 差し戻し2回目 4）。kind ごとのキーの集まり（並べ替えた形。行は
# sort_keys で書く）。_append_line は、書く前にこの形と照らす。封印係の照合（T-103）はこの定数と照らす。
# failed の stage の値は FAILED_STAGES。e3784c2 の本物の1回目の failed の行は stage を持たない（追記だけ
# なので直さない）。その形は MANIFEST_LEGACY_FAILED_KEYS（書くことはない。照合のための記録）
MANIFEST_ROW_KEYS = {
    "attempt": ("attempted_at", "code_path", "code_sha256", "exclusion_rule_record_sha256",
                "exclusion_rule_seq", "kind", "source_url"),
    "fetch": ("at", "code_sha256", "kind"),
    "failed": ("at", "kind", "reason", "stage"),
    "result": ("attempted_at", "code_path", "code_sha256", "dropped_columns",
               "exclusion_rule_record_sha256", "exclusion_rule_seq", "fetched_at", "file_name",
               "headerless", "kept_columns", "kind", "rows", "sha256", "sheet_names_replaced",
               "source_url", "store_location"),
}
MANIFEST_LEGACY_FAILED_KEYS = ("at", "kind", "reason")
DIAG_MAX_COLUMNS = 8             # 6章：診断で欄ごとの数を出す欄の数の上限
REQUEST_TIMEOUT_SECONDS = 60
TOTAL_DEADLINE_SECONDS = 300
MAX_BYTES = 50 * 1024 * 1024
MAX_XLSX_PART_BYTES = 200 * 1024 * 1024
USER_AGENT = "news-digital-stick-chart-collector/0"

KEEP_HEADER_RE = re.compile(
    r"\A(?:theme|themes|name|names|category|categories|label|description|desc|definition|"
    r"meaning|type|category ?type|kind|tag|theme ?name|category ?name|notes?)\Z", re.I)
DROP_HEADER_RE = re.compile(
    r"count|freq|volume|number|\bnum\b|total|articles|\bdocs?\b|documents|occurr|mentions|"
    r"hits|popular|\bn\b|cnt|rank|percent|share|ratio", re.I)
NAME_HEADER_RE = re.compile(
    r"\A(?:theme|themes|name|names|theme ?name|category ?name|tag)\Z", re.I)
ASCII_DIGITS_RE = re.compile(r"\A[0-9]+\Z")
NUMBER_SHAPE_RE = re.compile(r"\A(?=[^0-9]*[0-9])[0-9,.]+\Z")   # 6章：数の形（ASCII の数字と , . だけ）
NUMBER_SEPARATORS = frozenset(",. +-_'\u00a0\u202f")
THEME_NAME_RE = re.compile(r"\A[A-Z][A-Z0-9_]{0,159}\Z")

STORE_PARTS = ("Desktop", "news-stick-data")
STORE_LOCATION_NAME = "~/" + "/".join(STORE_PARTS)
MANIFEST_DIR_PARTS = ("data", "manifest")
MANIFEST_NAME = "gdelt-themes.jsonl"
CODE_REL = "src/collector/themes.py"


class ThemesError(Exception):
    """止まった。文には、表の値を入れない（見出しの名前だけ）。"""


class AttemptRecorded(ThemesError):
    """0.1章の1段目：試行の行を書いて止まった（通信はしていない）。コミットしてから再実行する。"""


class ExclusionRulesNotSealed(ThemesError):
    """0章の関門で止まった。通信も書き込みもしていない。"""


def has_numeric(text):
    """2章：数を表す文字（Unicode の Numeric_Type を持つ文字。str.isnumeric）が1つでもあれば True。"""
    return any(ch.isnumeric() for ch in text)


def looks_like_number(text):
    """2章：数字と区切りだけでできた値（見出しの無い形の判定）。"""
    t = text.strip()
    return bool(t) and has_numeric(t) and all(ch.isnumeric() or ch in NUMBER_SEPARATORS
                                              for ch in t)


def _letters(i):
    """0 → A、25 → Z、26 → AA。位置の名前（数字を使わない）。"""
    out = ""
    i += 1
    while i:
        i, r = divmod(i - 1, 26)
        out = chr(65 + r) + out
    return out


def _load_privacy_scan():
    spec = importlib.util.spec_from_file_location("privacy_scan",
                                                  os.path.join(HERE, "privacy_scan.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


privacy_scan = _load_privacy_scan()


def validate_doc_url(url):
    if not isinstance(url, str):
        raise ThemesError("URL が決まっていない")
    m = _DOC_URL_RE.match(url)
    if m is None or ".." in m.group(1):
        raise ThemesError("URL が data.gdeltproject.org/api/v2/guides/ の下の決めた形でない")
    if m.group(1) not in ALLOWED_GUIDE_FILES:
        raise ThemesError("/api/v2/guides/ の下で許すのは、全テーマの区分表（%s）だけ"
                          % ", ".join(ALLOWED_GUIDE_FILES))
    return m.group(1)


def _import_ledger():
    sealer = os.path.join(os.path.dirname(os.path.dirname(HERE)), "src", "sealer")
    if sealer not in sys.path:
        sys.path.insert(0, sealer)
    import ledger
    return ledger


def require_exclusion_rules_sealed():
    """0章の関門。引数は取らない（プロジェクトは ledger.PROJECT_ROOT）。返り値: (記録, root)。"""
    kind = EXCLUSION_RULE_KIND
    if kind is None:
        raise ExclusionRulesNotSealed("除外の規則の封印の記録の種類（kind）が、まだ決まっていない"
                                      "（封印係）。区分表は取得しない")
    ledger = _import_ledger()
    if kind not in ledger.ALLOWED_KINDS:
        raise ExclusionRulesNotSealed("kind %s が、封印の記録の種類の許可リストに無い" % kind)
    try:
        root = ledger._gate_root()
        _data, records = ledger._load_for_gate(root)
    except ledger.LedgerError as e:
        raise ExclusionRulesNotSealed("封印の記録を検証できない: %s" % e) from None
    recs = [r for r in records if r["kind"] == kind]
    if not recs:
        raise ExclusionRulesNotSealed("除外の規則の封印の記録（kind %s）が無い。区分表は取得しない"
                                      % kind)
    if len(recs) != 1:
        raise ExclusionRulesNotSealed("除外の規則の封印の記録（kind %s）が %d 件ある。1件だけの決まり"
                                      "（リードに報告）" % (kind, len(recs)))
    return recs[0], root


def exclusion_rule_ref(rec):
    """関門が返した記録の {"seq", "record_sha256"}（記録の行の正規の形の sha256）。中-B。"""
    ledger = _import_ledger()
    return {"seq": rec["seq"], "record_sha256": hashlib.sha256(ledger.canonical_line(rec)).hexdigest()}


def _exclusion_gate(root):
    """0章。返り値：exclusion_rule_ref。"""
    rec, gate_root = require_exclusion_rules_sealed()
    if os.path.realpath(gate_root) != os.path.realpath(root):
        raise ExclusionRulesNotSealed("関門が読んだプロジェクトと、run() の root が違う")
    return exclusion_rule_ref(rec)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def urllib_transport(url, timeout):
    validate_doc_url(url)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT,
                                               "Accept-Encoding": "identity"})
    try:
        return opener.open(req, timeout=timeout)
    except urllib.error.HTTPError as e:
        return e


def fetch_once(url, transport, clock):
    """1回だけ取得し、メモリの上のバイト列を返す。失敗は ThemesError（再試行しない）。"""
    validate_doc_url(url)
    deadline = clock() + TOTAL_DEADLINE_SECONDS
    resp = None
    try:
        resp = transport(url, REQUEST_TIMEOUT_SECONDS)
        status = getattr(resp, "status", None) or getattr(resp, "code", None)
        if status != 200:
            raise ThemesError("HTTP %s。再試行しない" % status)
        if resp.headers.get("Content-Encoding") not in (None, "", "identity"):
            raise ThemesError("応答が圧縮されている")
        buf = bytearray()
        while True:
            if clock() > deadline:
                raise ThemesError("時間の上限を超えた")
            chunk = resp.read(1 << 20)
            if not chunk:
                return bytes(buf)
            buf += chunk
            if len(buf) > MAX_BYTES:
                raise ThemesError("応答の長さの上限を超えた")
    except (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionError, OSError):
        raise ThemesError("通信の失敗。再試行しない") from None
    finally:
        if resp is not None:
            try:
                resp.close()
            except Exception:
                pass


# ---------------------------------------------------------------------------
# 3章：表を読む
# ---------------------------------------------------------------------------

_NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_RNS = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"


def _col_index(ref):
    letters = re.match(r"[A-Z]+", ref or "")
    if not letters:
        return None
    n = 0
    for ch in letters.group(0):
        n = n * 26 + ord(ch) - 64
    return n - 1


def _read_part(zf, name):
    info = zf.getinfo(name)
    if info.file_size > MAX_XLSX_PART_BYTES:
        raise ThemesError("xlsx の中のファイルが大きすぎる")
    return zf.read(name)


def read_xlsx(data):
    """[(シート名, [[セルの文字列, ...], ...]), ...]。数式は値のキャッシュを使う。"""
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
        names = set(zf.namelist())
        shared = []
        if "xl/sharedStrings.xml" in names:
            root = ET.fromstring(_read_part(zf, "xl/sharedStrings.xml"))
            for si in root.iter(_NS + "si"):
                shared.append("".join(t.text or "" for t in si.iter(_NS + "t")))
        wb = ET.fromstring(_read_part(zf, "xl/workbook.xml"))
        rels = ET.fromstring(_read_part(zf, "xl/_rels/workbook.xml.rels"))
        target = {r.get("Id"): r.get("Target") for r in rels}
        out = []
        for sh in wb.iter(_NS + "sheet"):
            t = target.get(sh.get(_RNS + "id"), "")
            path = t.lstrip("/") if t.startswith("/") else "xl/" + t
            root = ET.fromstring(_read_part(zf, path))
            rows = []
            for r in root.iter(_NS + "row"):
                cells = {}
                for c in r.iter(_NS + "c"):
                    i = _col_index(c.get("r"))
                    if i is None:
                        i = len(cells)
                    typ = c.get("t")
                    v = c.find(_NS + "v")
                    if typ == "s" and v is not None:
                        val = shared[int(v.text)]
                    elif typ == "inlineStr":
                        val = "".join(x.text or "" for x in c.iter(_NS + "t"))
                    else:
                        val = v.text if v is not None and v.text is not None else ""
                    cells[i] = val
                if cells:
                    rows.append([cells.get(i, "") for i in range(max(cells) + 1)])
            out.append((sh.get("name") or "", rows))
        return out
    except ThemesError:
        raise
    except (zipfile.BadZipFile, KeyError, ET.ParseError, ValueError, IndexError):
        raise ThemesError("xlsx として読めない") from None


def read_delimited(data):
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise ThemesError("UTF-8 として読めない") from None
    first = text.split("\n", 1)[0]
    delim = "\t" if "\t" in first else ","
    rows = [r for r in csv.reader(io.StringIO(text), delimiter=delim) if any(x.strip() for x in r)]
    return [("", rows)]


def read_table(data, name):
    low = name.lower()
    if low.endswith(".xlsx"):
        return read_xlsx(data)
    if low.endswith((".txt", ".tsv", ".csv")):
        return read_delimited(data)
    raise ThemesError("読める形（.txt・.tsv・.csv・.xlsx）でない")


# ---------------------------------------------------------------------------
# 2章：欄の分類
# ---------------------------------------------------------------------------

def classify_columns(header, rows):
    """返り値: (残す欄の番号の list, 捨てる欄の見出しの list)。止まるときは ThemesError。"""
    header = [h.strip() for h in header]
    if not header or any(not h for h in header) or len(set(h.lower() for h in header)) != len(header):
        raise ThemesError("見出しの行が無いか、空・重なった見出しがある（件数の欄を見出しで"
                          "確かめられない）")
    if any(looks_like_number(h) for h in header):
        raise ThemesError("1行目に数字だけの値がある（見出しの行が無い形とみなして止まる）")
    keep, drop, names = [], [], []
    for i, h in enumerate(header):
        col = [(r[i] if i < len(r) else "").strip() for r in rows]
        if not KEEP_HEADER_RE.match(h) or DROP_HEADER_RE.search(h):
            # 件数・頻度の欄と、知らない欄。見出しに数字があれば位置の名前で記録する
            drop.append("column_" + _letters(i) if has_numeric(h) else h)
        elif NAME_HEADER_RE.match(h):
            bad = sum(1 for v in col if not THEME_NAME_RE.match(v))
            if bad:
                raise ThemesError("テーマの名前の欄「%s」に、名前の形に合わない値が %d 件ある"
                                  "（件数が紛れている可能性があるので止まる）" % (h, bad))
            keep.append(i)
            names.append(i)
        elif any(has_numeric(v) for v in col):
            drop.append(h)                          # 数字の入った値がある欄は欄ごと捨てる
        else:
            keep.append(i)
    if not names:
        raise ThemesError("テーマの名前の欄が無い")
    return keep, drop


def build_output(sheets):
    """表から残す欄だけの TSV を作る。

    返り値: (バイト列, 行数, 残した見出し, 捨てた見出し, シート名を位置に替えたか,
             見出しの無い2欄の表として読んだか)。
    """
    data_sheets = [(n, rows) for n, rows in sheets if rows]
    if not data_sheets:
        raise ThemesError("表に行が無い")
    out_header, out_rows, dropped = None, [], []
    multi = len(data_sheets) > 1
    replaced = multi and any(has_numeric(n) for n, _rows in data_sheets)
    if replaced:
        data_sheets = [("sheet_" + _letters(i), rows) for i, (_n, rows) in enumerate(data_sheets)]
    headerless = False
    for sname, rows in data_sheets:
        if any(looks_like_number(h) for h in rows[0]):
            name_i, count_i = headerless_name_count(rows)     # 2.1章。合わなければ止まる
            headerless = True
            header = ["", ""]
            header[name_i] = "THEME"
            body = rows
            keep, drop = [name_i], ["column_" + _letters(count_i)]
        else:
            header, body = rows[0], rows[1:]
            keep, drop = classify_columns(header, body)
        h = [header[i].strip() for i in keep]
        if multi:
            h = ["sheet"] + h
        if out_header is None:
            out_header = h
        elif out_header != h:
            raise ThemesError("シートごとに残す欄が違う")
        dropped.extend(d for d in drop if d not in dropped)
        for r in body:
            vals = [(r[i] if i < len(r) else "").strip() for i in keep]
            if not any(vals):
                continue
            vals = [" ".join(v.split()) for v in vals]    # タブ・改行を空白1つにする
            out_rows.append(([sname] if multi else []) + vals)
    out_rows.sort()
    text = "\n".join("\t".join(r) for r in [out_header] + out_rows) + "\n"
    return text.encode("utf-8"), len(out_rows), out_header, dropped, replaced, headerless


def headerless_name_count(rows):
    """2.1章。返り値：(名前の欄の位置, 件数の欄の位置)。条件に合わなければ ThemesError。"""
    if any(len(r) != 2 for r in rows):
        raise ThemesError("1行目に数字だけの値がある（見出しの行が無い形）。欄がちょうど2つでない"
                          "ので、名前の欄を決められず止まる")
    cols = [[r[i].strip() for r in rows] for i in (0, 1)]

    def names(c):
        return all(THEME_NAME_RE.match(v) for v in c)

    def counts(c):
        return all(ASCII_DIGITS_RE.match(v) for v in c)
    fits = [(a, b) for a, b in ((0, 1), (1, 0)) if names(cols[a]) and counts(cols[b])]
    if len(fits) != 1:
        raise ThemesError("1行目に数字だけの値がある（見出しの行が無い形）。名前の欄と数字の欄を"
                          "値の形で一つに決められないので止まる")
    return fits[0]


# ---------------------------------------------------------------------------
# 4章：保存
# ---------------------------------------------------------------------------

def code_sha256():
    with open(os.path.join(HERE, "themes.py"), "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


_LOADED_SHA256 = code_sha256()          # 読み込んだ時点の themes.py（_code_gate が照らす）


def _iso(dt):
    return dt.astimezone(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _resolve(root, home):
    for depth in (1, 2):
        d = os.path.join(home, *STORE_PARTS[:depth])
        try:
            st = os.lstat(d)
        except OSError:
            raise ThemesError("保存先のフォルダが無い") from None
        if depth == 2 and not stat.S_ISDIR(st.st_mode):
            raise ThemesError("保存先が、シンボリックリンクかフォルダでない")
    store = os.path.realpath(os.path.join(home, *STORE_PARTS))
    root_real = os.path.realpath(root)
    if store == root_real or store.startswith(root_real + os.sep):
        raise ThemesError("保存先がプロジェクトの下にある")
    mdir = os.path.join(root, *MANIFEST_DIR_PARTS)
    if (os.path.islink(mdir) or os.path.islink(os.path.join(root, "data"))
            or os.path.realpath(mdir) != os.path.join(root_real, *MANIFEST_DIR_PARTS)):
        raise ThemesError("マニフェストのフォルダが、リンクかプロジェクトの外")
    return store, os.path.join(root_real, *MANIFEST_DIR_PARTS, MANIFEST_NAME)


def _load_codegate():
    spec = importlib.util.spec_from_file_location("codegate_for_themes",
                                                  os.path.join(HERE, "codegate.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _code_gate(root):
    """0.1章。返り値：(themes.py の code_sha256, HEAD のマニフェストのバイト列,
    マニフェストの名前の履歴があるか（git log --all -- <マニフェスト>）)。

    通らなければ ThemesError（何も書かない）。src/collector と src/sealer の両方を確かめる
    （除外の規則の関門が読み込む ledger.py は src/sealer にあるため。差し戻し2回目 軽-2）。
    """
    import subprocess
    if os.path.realpath(HERE) != os.path.join(os.path.realpath(root), "src", "collector"):
        raise ThemesError("動いている themes.py が、root のプロジェクトのものでない")
    cg = _load_codegate()
    try:
        codes = cg.check_clean(root, ("src/collector", "src/sealer"),
                               (CODE_REL, "src/collector/privacy_scan.py"))
        rel = "/".join(MANIFEST_DIR_PARTS + (MANIFEST_NAME,))
        code, hist = cg.run_git(root, "log", "--all", "--format=%H", "--", rel)
        if code != 0:
            raise ThemesError("コードの関門：git log を実行できない")
        has_history = bool(hist.strip())
        code, _o = cg.run_git(root, "cat-file", "-e", "HEAD:%s" % rel)
        head_manifest = b""
        if code == 0:
            code, head_manifest = cg.run_git(root, "cat-file", "blob", "HEAD:%s" % rel)
            if code != 0:
                raise ThemesError("コードの関門：HEAD のマニフェストを読めない")
    except cg.CodeGateError as e:
        raise ThemesError("コードの関門：%s" % e) from None
    except (OSError, subprocess.SubprocessError):
        raise ThemesError("コードの関門：git の実行に失敗した") from None
    sha = hashlib.sha256(codes[CODE_REL]).hexdigest()
    if sha != _LOADED_SHA256 or sha != code_sha256():
        raise ThemesError("動いている themes.py が、HEAD にコミットした中身と違う")
    return sha, head_manifest, has_history


def _read_manifest(path):
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    except FileNotFoundError:
        return b""
    except OSError:
        raise ThemesError("マニフェストを開けない（シンボリックリンクなど）") from None
    with os.fdopen(fd, "rb") as f:
        return f.read()


def check_row_shape(entry):
    """書く行が MANIFEST_ROW_KEYS の形（と failed の stage が FAILED_STAGES）であること。"""
    kind = entry.get("kind")
    if kind not in MANIFEST_ROW_KEYS or tuple(sorted(entry)) != MANIFEST_ROW_KEYS[kind]:
        raise ThemesError("マニフェストの行の形が、MANIFEST_ROW_KEYS と違う（コードの誤り）")
    if kind == "failed" and entry["stage"] not in FAILED_STAGES:
        raise ThemesError("failed の行の stage が FAILED_STAGES に無い（コードの誤り）")


def _append_line(path, entry, what):
    check_row_shape(entry)
    line = (json.dumps(entry, sort_keys=True, ensure_ascii=True) + "\n").encode("ascii")
    if privacy_scan.find_in_bytes(line):
        raise ThemesError("%s にメールアドレスの形の文字列があるので書かずに止まる" % what)
    fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC,
                 0o644)
    try:
        os.write(fd, line)
        os.fsync(fd)
    finally:
        os.close(fd)


def _count_attempts(data):
    n = 0
    for raw in data.split(b"\n"):
        try:
            row = json.loads(raw.decode("ascii")) if raw.strip() else None
        except (UnicodeDecodeError, ValueError):
            continue
        if isinstance(row, dict) and row.get("kind") == "attempt":
            n += 1
    return n


def _manifest_versions(root):
    """0.3章。git log --all --full-history に現れるマニフェストの各版のバイト列（その commit に
    ファイルが無い版は空のバイト列）。git を動かせなければ ThemesError。"""
    import subprocess
    cg = _load_codegate()
    rel = "/".join(MANIFEST_DIR_PARTS + (MANIFEST_NAME,))
    try:
        check_no_graft_or_shallow(root, cg)
        code, out = cg.run_git(root, "log", "--all", "--reflog", "--full-history", "--format=%H",
                               "--", rel)
        if code != 0:
            raise ThemesError("履歴の関門：git log を実行できない")
        versions = []
        for c in out.decode("ascii").split():
            code, _o = cg.run_git(root, "cat-file", "-e", "%s:%s" % (c, rel))
            if code != 0:
                versions.append(b"")                  # その commit で消した版
                continue
            code, body = cg.run_git(root, "cat-file", "blob", "%s:%s" % (c, rel))
            if code != 0:
                raise ThemesError("履歴の関門：マニフェストの過去の版を読めない")
            versions.append(body)
    except cg.CodeGateError as e:
        raise ThemesError("履歴の関門：%s" % e) from None
    except (OSError, subprocess.SubprocessError, UnicodeDecodeError):
        raise ThemesError("履歴の関門：git の実行に失敗した") from None
    return versions


def check_no_graft_or_shallow(root, cg=None):
    """0.3章（T-101 差し戻し2回目 中-2）。浅い clone（.git/shallow）と graft のファイルは、commit の
    親を変えて、履歴の版を見えなくできる。どちらかがあれば止まる。graft のファイルの場所は
    git rev-parse --path-format=absolute --git-common-dir の下の info/grafts で決める
    （docs/stats/seal-order1.md と同じやり方。GIT_GRAFT_FILE に左右されない。codegate の git は
    環境変数を固定して動かすので、GIT_GRAFT_FILE・GIT_SHALLOW_FILE は渡らない）。"""
    cg = cg or _load_codegate()
    code, out = cg.run_git(root, "rev-parse", "--is-shallow-repository")
    if code != 0 or out.strip() not in (b"true", b"false"):
        raise ThemesError("履歴の関門：浅い clone かどうかを確かめられない")
    if out.strip() != b"false":
        raise ThemesError("履歴の関門：浅い clone（.git/shallow）なので、履歴の版を確かめられない。"
                          "取得しない（リードに報告）")
    code, out = cg.run_git(root, "rev-parse", "--path-format=absolute", "--git-common-dir")
    common = out.decode("utf-8", "replace").strip() if code == 0 else ""
    if not common or not os.path.isabs(common):
        raise ThemesError("履歴の関門：git の共通のディレクトリを決められない")
    if os.path.lexists(os.path.join(common, "info", "grafts")):
        raise ThemesError("履歴の関門：graft のファイル（info/grafts）がある。commit の親を変えられる"
                          "ので取得しない（リードに報告）")


def check_append_only(versions, head_manifest):
    """0.3章。履歴の各版が HEAD の版の先頭部分（追記だけ）であることを求める。返り値：各版の
    attempt の行の数の最大値。行を消した・変えた・並べ替えた版があれば ThemesError。"""
    for v in versions:
        if not head_manifest.startswith(v):
            raise ThemesError("区分表のマニフェストの過去の版が、今の版の先頭部分でない（行を消した・"
                              "変えた跡）。取得しない（リードに報告）")
    return max((_count_attempts(v) for v in versions), default=0)


MANIFEST_NEXT = {None: ("attempt",), "attempt": ("fetch",), "fetch": ("failed", "result"),
                 "failed": ("attempt",), "result": ()}


def parse_manifest(data):
    """0.2章。マニフェストのバイト列を行の一覧にする。並びは attempt → fetch → failed か result、
    failed のあとは次の attempt だけ、result のあとは何も無い（MANIFEST_NEXT）。合わなければ止まる。"""
    rows, prev = [], None
    for raw in data.split(b"\n"):
        if not raw.strip():
            continue
        try:
            row = json.loads(raw.decode("ascii"))
        except (UnicodeDecodeError, ValueError):
            raise ThemesError("マニフェストの行が JSON として読めない（リードに報告）") from None
        kind = row.get("kind") if isinstance(row, dict) else None
        if kind not in MANIFEST_NEXT[prev]:
            raise ThemesError("マニフェストの行の並びが違う（%s のあとに %s）。取得しない（リードに報告）"
                              % (prev or "先頭", kind if kind in MANIFEST_NEXT else "知らない kind"))
        rows.append(row)
        prev = kind
    if not rows:
        raise ThemesError("マニフェストが空（コミットしたあとで消した跡）。取得しない（リードに報告）")
    return rows


def _check_store_empty(store):
    if any(n.startswith("gdelt-themes-") for n in os.listdir(store)):
        raise ThemesError("保存先に区分表のファイルが既にある。取得しない（リードに報告）")


# ---------------------------------------------------------------------------
# 6章：形の判定で止まったときの診断（T-101）
# ---------------------------------------------------------------------------

def _char_classes(v):
    """値に含まれる文字の種類ごとの文字の数。名前の欄の規則 THEME_NAME_RE に照らすための分類。"""
    c = {"upper": 0, "lower": 0, "digit": 0, "underscore": 0, "space": 0, "symbol": 0,
         "non_ascii": 0}
    for ch in v:
        if ch.isascii():
            if "A" <= ch <= "Z":
                c["upper"] += 1
            elif "a" <= ch <= "z":
                c["lower"] += 1
            elif "0" <= ch <= "9":
                c["digit"] += 1
            elif ch == "_":
                c["underscore"] += 1
            elif ch.isspace():
                c["space"] += 1
            else:
                c["symbol"] += 1
        else:
            c["non_ascii"] += 1
    return c


def diagnose_shape(sheets):
    """表の形の数と種類だけを数える（値・名前・断片は返さない）。返り値は数だけの dict。

    T-101 差し戻し2回目 中-3・軽-4：名前の規則に合わない値のうち、数の形（NUMBER_SHAPE_RE。ASCII の
    数字と , . だけ）の値は、文字の種類の内訳から外して数だけを数える（nonmatch_number_shaped）。
    合わない値の過半数が数の形の欄は、件数の欄らしい欄（count_like）とし、values・ascii_digits_only・
    number_shaped だけを出す。"""
    out = {"sheets": len(sheets), "rows": 0, "column_count_distribution": {}, "columns": []}
    cols = []
    for _n, rows in sheets:
        for r in rows:
            out["rows"] += 1
            k = str(len(r))
            out["column_count_distribution"][k] = out["column_count_distribution"].get(k, 0) + 1
            for i, v in enumerate(r[:DIAG_MAX_COLUMNS]):
                while len(cols) <= i:
                    cols.append({"values": 0, "empty": 0, "theme_name_match": 0,
                                 "theme_name_nonmatch": 0, "ascii_digits_only": 0,
                                 "nonmatch_number_shaped": 0,
                                 "nonmatch_first_char_not_upper": 0, "nonmatch_too_long": 0,
                                 "nonmatch_values_with": {}, "nonmatch_chars": {}})
                d = cols[i]
                v = v.strip()
                d["values"] += 1
                if not v:
                    d["empty"] += 1
                if ASCII_DIGITS_RE.match(v):
                    d["ascii_digits_only"] += 1
                if THEME_NAME_RE.match(v):
                    d["theme_name_match"] += 1
                    continue
                d["theme_name_nonmatch"] += 1
                if NUMBER_SHAPE_RE.match(v):
                    d["nonmatch_number_shaped"] += 1      # 数だけを数え、内訳に入れない
                    continue
                if v and not ("A" <= v[0] <= "Z"):
                    d["nonmatch_first_char_not_upper"] += 1
                if len(v) > 160:
                    d["nonmatch_too_long"] += 1
                for cls, n in _char_classes(v).items():
                    if n:
                        d["nonmatch_values_with"][cls] = d["nonmatch_values_with"].get(cls, 0) + 1
                        d["nonmatch_chars"][cls] = d["nonmatch_chars"].get(cls, 0) + n
    out["columns"] = [{"count_like": True, "values": d["values"],
                       "ascii_digits_only": d["ascii_digits_only"],
                       "number_shaped": d["nonmatch_number_shaped"]}
                      if is_count_like(d) else dict(d, count_like=False) for d in cols]
    out["columns_not_shown"] = max(0, max((len(r) for _n, rows in sheets for r in rows), default=0)
                                   - DIAG_MAX_COLUMNS)
    out["first_row_numeric_columns"] = sum(
        1 for _n, rows in sheets[:1] for v in (rows[0] if rows else []) if looks_like_number(v))
    return out


def is_count_like(d):
    """件数の欄らしい欄：名前の規則に合わない値の過半数が、数の形（NUMBER_SHAPE_RE）。"""
    return d["nonmatch_number_shaped"] * 2 > d["theme_name_nonmatch"]


def format_diagnosis(d):
    """診断を1行の文にする。中身は数と、固定の名前の鍵だけ（json の鍵は上のコードの定数）。"""
    return "診断（数と種類だけ。値は出さない）: " + json.dumps(d, sort_keys=True, ensure_ascii=True)


def _stderr_diag(text):
    print(text, file=sys.stderr)


def run(*, root, home, url=None, transport=urllib_transport, clock=time.monotonic,
        now=lambda: datetime.datetime.now(datetime.timezone.utc), diag=_stderr_diag):
    """1回だけ取得し、件数の欄を捨てて保存する（ThemesError で止まる）。2段で動く（0.1章）。

    1段目：マニフェストが作業ツリーにも HEAD にも無ければ、試行の行を書いて AttemptRecorded で
      止まる（通信しない）。オーナー（または実行の担当）がコミットしてから、もう一度実行する。
    2段目：作業ツリーのマニフェストが HEAD と同じで、中身がこのコードとこの除外の規則の記録の
      試行の行ちょうど1行のときだけ、通信の直前に fetch の行を書いてから通信する。通信や形の
      誤りで止まったときは failed の行を書く。成功すれば結果の行を書く。
    関門（0章・0.1章）で止まるときは何も書かない。
    """
    url = THEMES_URL if url is None else url
    name = validate_doc_url(url)
    sha_code, head_manifest, has_history = _code_gate(root)   # 0.1章。固定したコードで動くことを先に
    hist_attempts = check_append_only(_manifest_versions(root), head_manifest)   # 0.3章
    excl = _exclusion_gate(root)                      # 0章。通信の前に確かめる
    store, manifest = _resolve(root, home)
    attempt = {"kind": "attempt", "source_url": url, "code_path": CODE_REL,
               "code_sha256": sha_code, "exclusion_rule_seq": excl["seq"],
               "exclusion_rule_record_sha256": excl["record_sha256"]}
    if not os.path.lexists(manifest) and not head_manifest:
        # 1段目の前提（T-026 軽-3）：マニフェストの名前に Git の履歴が無いこと（git mv で名前を
        # 変えて残した場合も、元の名前の履歴が残る）と、保存先に区分表のファイルが無いこと
        if has_history:
            raise ThemesError("区分表のマニフェストの名前に Git の履歴がある（前に試みた跡）。"
                              "マニフェストが無いので取り直しもしない（リードに報告）")
        _check_store_empty(store)
        _append_line(manifest, dict(attempt, attempted_at=_iso(now())), "マニフェストの行")
        raise AttemptRecorded("試行の行を書いた（1回目。通信はしていない）。data/manifest/%s を"
                              "コミットしてから、同じコマンドでもう一度実行する" % MANIFEST_NAME)
    working = _read_manifest(manifest)
    if working != head_manifest:
        raise ThemesError("区分表のマニフェストに、コミットしていない変更がある（前の取得の途中か"
                          "あとの跡。取得しない。リードに報告）")
    rows = parse_manifest(working)                    # 0.2章。並びが違えば止まる
    # 0.3章：回数は、履歴の各版と HEAD の attempt の行の数のうち、いちばん大きいもの
    n_attempts = max(hist_attempts, sum(1 for r in rows if r["kind"] == "attempt"))
    if n_attempts > MAX_TOTAL_ATTEMPTS:
        raise ThemesError("マニフェストの attempt の行が %d 行あり、上限 %d を超えている。取得しない"
                          "（リードに報告）" % (n_attempts, MAX_TOTAL_ATTEMPTS))
    last = rows[-1]["kind"]
    if last == "result":
        raise ThemesError("区分表は既に取得した（result の行がある）。それ以上は取得しない")
    if last == "fetch":
        raise ThemesError("前の取得が fetch の行で終わっている（通信の途中で止まった跡）。取り直さない"
                          "（リードに報告）")
    if last == "failed":
        # 0.2章：取り直しの1段目。上限に達していれば、何も書かずに止まる（通信もしない）
        if n_attempts >= MAX_TOTAL_ATTEMPTS:
            raise ThemesError("取得の試みは上限の %d 回に達した（attempt の行 %d 行）。取り直さない。"
                              "それ以上はオーナーに聞く" % (MAX_TOTAL_ATTEMPTS, n_attempts))
        _check_store_empty(store)
        _append_line(manifest, dict(attempt, attempted_at=_iso(now())), "マニフェストの行")
        raise AttemptRecorded("取り直しの試行の行を書いた（%d 回目。上限 %d 回。通信はしていない）。"
                              "data/manifest/%s をコミットしてから、同じコマンドでもう一度実行する"
                              % (n_attempts + 1, MAX_TOTAL_ATTEMPTS, MANIFEST_NAME))
    # last == "attempt"：2段目。最後の attempt の行が、このコードとこの除外の規則のものであること
    only = rows[-1]
    if {k: v for k, v in only.items() if k != "attempted_at"} != attempt:
        raise ThemesError("マニフェストの最後の試行の行が、このコードかこの除外の規則のものでない。"
                          "取得しない（コードを変えたなら、試行の行を書く前に戻す。リードに報告）")
    _check_store_empty(store)
    attempted_at = only.get("attempted_at")
    stamp = now().astimezone(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    file_name = "gdelt-themes-%s.tsv" % stamp
    out_path = os.path.join(store, file_name)
    if os.path.lexists(out_path):
        raise ThemesError("同じ名前のファイルが既にある")
    _append_line(manifest, {"kind": "fetch", "at": _iso(now()), "code_sha256": sha_code},
                 "マニフェストの行")
    try:
        return _fetch_and_write(url, name, transport, clock, now, attempted_at, sha_code, excl,
                                file_name, out_path, manifest, diag)
    except ThemesError as e:
        stage = getattr(e, "stage", "fetch")
        if stage not in FAILED_STAGES:
            stage = "fetch"
        _append_line(manifest, {"kind": "failed", "at": _iso(now()), "stage": stage,
                                "reason": type(e).__name__}, "マニフェストの行")
        raise


def _fetch_and_write(url, name, transport, clock, now, attempted_at, sha_code, excl, file_name,
                     out_path, manifest, diag):
    def at(stage, fn, *a):
        try:
            return fn(*a)
        except ThemesError as e:
            e.stage = stage                           # failed の行の stage（FAILED_STAGES）
            raise
    raw = at("fetch", fetch_once, url, transport, clock)
    fetched_at = _iso(now())
    sheets = at("read", read_table, raw, name)
    del raw                                           # 元の応答はここで手放す
    try:
        data, nrows, kept, dropped, replaced, headerless = build_output(sheets)
    except ThemesError as e:
        e.stage = "shape"
        try:                                          # 軽-8：診断が落ちても failed の行は書く
            diag(format_diagnosis(diagnose_shape(sheets)))   # 6章：数と種類だけ。標準エラーだけ
        except Exception:
            try:
                diag("診断を出せなかった")
            except Exception:
                pass
        raise
    del sheets
    entry = {"kind": "result", "file_name": file_name, "sha256": hashlib.sha256(data).hexdigest(),
             "rows": nrows, "kept_columns": kept, "dropped_columns": dropped,
             "fetched_at": fetched_at, "attempted_at": attempted_at,
             "sheet_names_replaced": replaced, "headerless": headerless,
             "source_url": url, "code_path": CODE_REL, "code_sha256": sha_code,
             "exclusion_rule_seq": excl["seq"],
             "exclusion_rule_record_sha256": excl["record_sha256"],
             "store_location": STORE_LOCATION_NAME}
    line = (json.dumps(entry, sort_keys=True, ensure_ascii=True) + "\n").encode("ascii")
    for what, b in (("区分表", data), ("マニフェストの行", line)):
        if privacy_scan.find_in_bytes(b):
            e = ThemesError("%s にメールアドレスの形の文字列があるので書かずに止まる" % what)
            e.stage = "write"
            raise e
    fd = os.open(out_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                 0o644)
    try:
        view = memoryview(data)
        while view:
            view = view[os.write(fd, view):]
        os.fsync(fd)
    finally:
        os.close(fd)
    _append_line(manifest, entry, "マニフェストの行")
    return entry


# ---------------------------------------------------------------------------
# 5章：入口のコマンド（T-098）
# ---------------------------------------------------------------------------

PROJECT = os.path.dirname(os.path.dirname(HERE))
EXIT_OK, EXIT_STOPPED, EXIT_USAGE, EXIT_ATTEMPT_RECORDED = 0, 1, 2, 3


def production_home():
    """利用者のホーム。環境変数 HOME ではなく、利用者のデータベースから決める。"""
    import pwd
    return pwd.getpwuid(os.getuid()).pw_dir


def main(argv=None):
    argv = sys.argv[1:] if argv is None else list(argv)
    if argv:
        print("引数は受け付けない（取得元・保存先・時計は固定）。手順は src/collector/README.md 8章",
              file=sys.stderr)
        return EXIT_USAGE
    try:
        entry = run(root=PROJECT, home=production_home())
    except AttemptRecorded as e:
        print("1段目：%s" % e, file=sys.stderr)
        return EXIT_ATTEMPT_RECORDED
    except ThemesError as e:
        print("止まった（%s）: %s" % (type(e).__name__, e), file=sys.stderr)
        return EXIT_STOPPED
    print("2段目：取得して保存した")
    print("本体: %s（%s の下）" % (entry["file_name"], entry["store_location"]))
    print("行数: %d" % entry["rows"])
    print("残した欄: %s" % ", ".join(entry["kept_columns"]))
    print("捨てた欄: %s" % ", ".join(entry["dropped_columns"]))
    print("headerless: %s" % json.dumps(entry["headerless"]))
    print("sha256: %s" % entry["sha256"])
    print("code_sha256（%s）: %s" % (entry["code_path"], entry["code_sha256"]))
    print("除外の規則の記録: seq %d" % entry["exclusion_rule_seq"])
    print("データ出典：GDELT Project（https://www.gdeltproject.org/）")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
