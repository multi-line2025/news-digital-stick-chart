# 順番1の封印：封印係への申し送り（T-022、T-024、T-025、T-028）

封印の順番と、その理由は `docs/stats/tags-naive.md` 5章にある。この文書は、順番1（除外の規則と入れる規則）を封印するときに、封印係が確かめることと、封印の対象の sha256 をまとめたものである。T-024 で、順番1b（数え方の候補の一覧）の関門の条件を 3章 (3) に足した。T-025 で、`docs/stats/tags-naive.md` 0章の B (ii)（選ぶ基準）の承認を書き入れた。T-028 で、順番2の基準の入力を一つに決める規則と、入力のファイルの照合（3章 (2)）、順番2で止まったあとの扱い、git の条件の `F` の決め方を足し、理由の書き方を直した（T-025 の監査の中2・軽1・軽2・軽4）。T-028 の差し戻し1回目で、止まったあとの行き先（代わりの候補、入力の2段目、待つ条件）を順番1b で封印する形にし（差し戻し2回目で、2段目に進む場合を絞り、ほかは止まる形に直した）、時機の条件を git だけで決まる形にし、試しの run の作りを直すタスクの合格を順番1b の前提にした。T-028 の再提出3回目で、マニフェストのファイルが無いときに止まる形にした（`counting.py apply`）。T-036 で、2026-10-08 のオーナーの決定に合わせ、正式な数え方を C7（V1 か V2 の少なくとも一方に付いた文書の数 ÷ 同じ数え方の全テーマの合計）に決め打ちにし、B1〜B5 と C1〜C6 を参考とした。それに合わせて、順番2の記録の中身（3章 (2)）、順番2で止まったあとの扱い、順番5の記録、順番1b の関門の4（3章 (3)）を直した。数え方の候補、正式な数え方、参考の基準の案そのものは `docs/stats/counting.md` と `src/stats/counting.py` にある。

- 手順で使う Python は `.venv/bin/python`（プロジェクトの仮想環境。Homebrew の Python 3.14.2 で作ったもの）に一つに決める（T-024）。テストや出力の結果を見てから、別の Python に替えて流し直さない。

- 統計係は封印しない。記録の種類（kind）の名前と照合の仕組みは、封印係が決める。
- この文書は順番1の封印の対象ではない。対象の sha256 を書くための申し送りで、対象のどのテストもこの文書を読まない。

## 1. 封印の対象と sha256

表は、統計係がこのコミットの作業ツリーから計算した値である（`src/stats/order1_digests.py` の出力と同じ）。テスト `test_seal_targets`（`tests/stats/test_t019.py`）が、今のファイルと git の履歴から計算し直して照合する。

<!-- table:seal-targets -->
| 対象 | sha256 |
|---|---|
| `src/stats/exclusion.py` | `22bc0ed138a42b95c36797bbe5b41163c871af14f32be590dafde20fe16fdd1d` |
| `src/stats/exclusion.py の出力` | `681cf5bb698e72097ee17b3516c96d89c69ae70e862122616e678e0b0a5363b8` |
| `tests/stats/test_exclusion.py` | `245d61ec2539cfacc9b111a2397a2c7a7912e108645d738be4190fd23580ae97` |
| `src/stats/tagrules.py` | `63b0e005ce85344675651264b4a14453a167a28d56d3333a7503b55db04218ee` |
| `src/stats/tagrules.py の出力` | `c3a4480b1cb2f034f1598dcee5f6c85bf52e92e94d7b06cc52ccaa4889737b39` |
| `tests/stats/test_tagrules.py` | `06da4a16796dcb4540d84f4179ed05f73a14213b3dbfab34d62cb20c44895405` |
| `docs/stats/tags-naive.md` | `9405ffb9a7a2c89e1bfa8271ad5773d55825b17bbd6a1552d52151de20f664b5` |
| `1cb463a:src/stats/tagrules.py` | `f7c325cb21bcf39c42e6d785deacbe47eacec7fb2834d2927634e446b62ce57a` |
| `1cb463a:src/stats/tagrules.py の出力` | `98926edbbbc7ac0375aee97aa7be0b1a5e3fcf3bc4acbadfa99f5d17362f7b8a` |
| `2d23cdf:reviews/T-020.md` | `0b80ec29a994e04224900b3aafbc56a78d5cd9d4cee6e8d3df6c82a211cf46e7` |

- ファイルの sha256 は、ファイルのバイト列そのもの。
- 「の出力」は、プロジェクトのルートで `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -B src/stats/exclusion.py`（`tagrules.py` も同じ）を引数なしで実行した標準出力のバイト列。
- `1cb463a:` と `2d23cdf:` で始まるものは、`git show <commit>:<path>` の標準出力のバイト列。1cb463a の版の出力は、そのファイルを一時のディレクトリに取り出して（`git show 1cb463a:src/stats/tagrules.py > tagrules.py`）、同じように引数なしで実行した標準出力のバイト列。
- 統計係が計算したときの Python の版：3.14.2（`.venv/bin/python`）。T-024 で、Homebrew の `python3`（3.14.2）でも10件が同じ値になり、stats のテストがすべて通ることを確かめた。
- 順番1で封印したあとは、この表も `docs/stats/tags-naive.md` も直さない（tags-naive.md 5章 (2)）。凍結を確かめる根拠は封印の記録で、照らす手順は3章 (1)。
- 移した `docs/stats/naive-scoring.md`（素朴な予測と採点計画の一部）は、順番1の対象に入れない。最初の threshold-access より前なら改訂できる章で、封印は `naive.py`・`scoring.py` と一緒に順番6〜8で行う。順番1で封印する二つのテストは、この文書を読まない（`test_sealed_tests_read_only_targets`）。

## 2. 封印の前に、封印係が確かめること

次のどれか一つでも満たさなければ、封印しない。確かめた結果は、封印の記録に入れる。

1. **オーナーの承認を、記録と機械的に照らすこと**（T-024 で、リードが reviews/T-024.md の「2026-10-08 割り振りの前にリードが決めたこと」の「オーナーの承認の出どころの照らし方」で決めた照らし方に置き換えた）：`docs/stats/tags-naive.md` 0章の A（入れる規則を順番1で封印する変更）と B（数え方の候補の一覧を先に封印する案）について、次を確かめる。見出しでは照らさない（同じ日の同じ見出しが、そのファイルに2つあるため）。
   - 照らすファイル：A と B は `git show 8f0f4ec233acdef6e3d6bd7144fa1523be389308:reviews/T-022.md` の標準出力、B (ii) は下のとおり 0f98e62 の reviews/T-024.md。commit を40桁で指定する。作業中の reviews/ は読まない。
   - A：行の全体が `> Kはいま封印していいよ` と一致する行が、ちょうど1つあること。
   - B：行の全体が `> それでいいです。` と一致する行がちょうど1つあり、その直前の行の全体が `> 2.数え方の候補を先に封印し、最後に全候補のタグの一覧を並べて公開する案でよいか` と一致すること。
   - B (ii)（候補の中から選ぶ基準。T-025）：`git show 0f98e62b2810011c269efdd5836bd7cf3a5d5fce:reviews/T-024.md` の標準出力で、行の全体が `> いいよ、正式に扱う基準は一つに絞ろう。` と一致する行がちょうど1つあること（統計係が T-025 で確かめた時点では36行目）。
   - 封印の記録に、出どころ（`8f0f4ec233acdef6e3d6bd7144fa1523be389308:reviews/T-022.md` と `0f98e62b2810011c269efdd5836bd7cf3a5d5fce:reviews/T-024.md`）と、照らした行（A は1行、B は2行、B (ii) は1行）をそのまま写す。
   - B (ii) の中身（検討した基準の案をすべて method-access より前に封印し、正式に使う基準を一つ決めて一緒に封印する）は順番1b で行う。順番1の対象には基準の案は入らない。2026-10-08 のオーナーの決定で、正式な数え方は基準で選ばず C7 に決め打ちになり、基準の案は参考として封印する（`counting.md` 0章）。
   - 封印する二つのテストには、この照らし方を入れていない。入れると、封印するテストが読むもの（`git show 8f0f4ec…:reviews/T-022.md` と `git show 0f98e62…:reviews/T-024.md`）と封印の対象の表が増えるが、承認の確認は封印の時点で一度行えば足り、その結果は封印の記録に残るため（統計係の判断。T-024 の割り振りで、足すかどうかは統計係に委ねられた）。
2. **区分表の取得と method-access がまだ無いこと**：次のすべてを、封印する時点の作業ツリーと履歴で確かめる。
   - 区分表の取得は ledger に acquisition-start を書かない。収集係の `src/collector/themes.py` は、取得の試行と結果を `data/manifest/gdelt-themes.jsonl` に書く（試行の行の `kind` は `attempt`、結果の行は `result`。行の中の `code_path` は `src/collector/themes.py`）。このファイルが作業ツリーに無いこと、または行が一つも無いこと。さらに `git log --all --oneline -- data/manifest/gdelt-themes.jsonl` の出力が空であること（一度でもコミットされていれば、取得を試みたことになる）。
   - `sealed/ledger.jsonl` に、`kind` が `method-access` の記録が一件も無いこと。
   - GKG（手法を作る期間の報道量）の取得も、まだ無いこと。収集係の GKG の取得は、取得の記録を `data/manifest/gdelt-gkg-method.jsonl`（正式の取得）と `data/manifest/gdelt-gkg-trial.jsonl`（試しの run）に書く。この二つのファイルが作業ツリーに無いこと、または行が一つも無いこと。さらに `git log --all --oneline -- data/manifest/gdelt-gkg-method.jsonl data/manifest/gdelt-gkg-trial.jsonl` の出力が空であること。
     - マニフェストも直接確かめる理由（T-028 で直した。T-025 の監査の軽4）：今のコードでは、試しの run も正式な run も、入口のスクリプト `src/collector/acquire_gkg.py` が `ledger.require_method_access()` で method-access の記録を求める。しかし `gkg.run_gkg` は、受け取った `method_access_seq` をマニフェストに書くだけで、鎖の上の method-access の記録とは照らさない（`gkg.py` の `run_gkg`）。入口のスクリプトを通らずに `run_gkg` を呼んだ取得や、関門のコードが変わったあとの取得は、method-access の記録が無いままマニフェストに行を残しうる。method-access の記録が無いことは「入口のスクリプトの関門を通った取得が無い」ことしか示さないので、マニフェストに取得の跡が無いことも確かめる。
   - `sealed/ledger.jsonl` の `kind` が `acquisition-start` のすべての記録について、次を確かめる。ledger の行そのものには `fetch` は無い。`fetch.code_path` は、行の `targets` が指すファイルの中にある（T-024 M-d で直した。前の版の「記録の最上位の `fetch`」は誤り）。
     - 行の `targets` の各要素の `path` のファイルを読み、その sha256 を封印係のコードで計算して、要素の `sha256` と一致すること。
     - そのファイルの JSON の `fetch.code_path` が `src/collector/acquire_filelist.py` であること。
     - 次のどれかに当たれば拒む（封印しない）：`targets` が無いか空、ファイルが無い、sha256 が合わない、JSON として読めない、`fetch` が無い、`fetch.code_path` が無い、`fetch.code_path` が `src/collector/acquire_filelist.py` でない。
   - 統計係が 2026-10-08 に確かめた時点では、ledger は4件（periods、candidates、acquisition-start（`targets` のファイル `sealed/acquisition-start-cf4bab28….json` の sha256 は `targets` と一致し、その `fetch.code_path` は `src/collector/acquire_filelist.py`）、acquisition-result）で、`data/manifest/` には `gdelt-filelist.jsonl` だけがあり、`gdelt-themes.jsonl`・`gdelt-gkg-method.jsonl`・`gdelt-gkg-trial.jsonl` の履歴は無かった（2026-10-08、差し戻し3回目の時点でも、T-024 の時点でも同じ）。封印係は、封印する時点で自分で確かめ直すこと。
3. **作業ツリーがきれいなこと**：封印する時点で `git status --porcelain` の出力が空であること。追跡していないファイルや、コミットしていない変更（ほかの係のものを含む）があれば封印しない。
4. **commit ID と祖先と Python の版を記録に入れること**：
   - 封印の記録に、封印した時点の HEAD の commit ID を40桁で入れる（`git rev-parse HEAD`。短い ID は使わない）。
   - その commit の祖先に、次の二つの commit があることを確かめる：`git merge-base --is-ancestor 1cb463acfcf15ba315e6c454625ad681e86bbc2a HEAD` と `git merge-base --is-ancestor 2d23cdf6e01de5129fc7b0a5d85e89bf02e892c6 HEAD` が、どちらも0で終わること。短い ID の `1cb463a`・`2d23cdf` がこの40桁の ID を指すことも、`git rev-parse` で確かめる。
   - 承認の出どころの commit も祖先であることを確かめる（T-025 L4）：`git merge-base --is-ancestor 8f0f4ec233acdef6e3d6bd7144fa1523be389308 HEAD` と `git merge-base --is-ancestor 0f98e62b2810011c269efdd5836bd7cf3a5d5fce HEAD` が、どちらも0で終わること。
   - 出力を作るのに使った Python のパス（`.venv/bin/python`）と版（`.venv/bin/python --version` の出力）を入れる。出力の JSON は Python の版で変わらないはずだが、第三者が同じ版で計算し直せるようにするため。
5. **浅い clone では確かめないこと**：`git rev-parse --is-shallow-repository` が `false` であること。浅い clone では `git show 1cb463a:…` と `git show 2d23cdf:…` が取れず、テストと照合ができない。第三者向けの検証の手順にも、履歴をすべて取る clone が要ると書く（封印係の docs/verify/ への提案）。
6. **sha256 を自分で計算し直すこと**：上の表の値を写さず、封印係のコードで、1章のバイト列の定義どおりに計算し直す。表の値と一つでも違えば封印しない（その場合は統計係に差し戻す）。封印の記録には、10件の対象の名前と sha256 をすべて入れる。
7. **出どころの確認は 2d23cdf の版で行うこと**：除外の規則の出力の `owner_choice_source` は `"2d23cdf:reviews/T-020.md 2026-10-08 オーナーの発言（原文のまま記録）"` である。これを、作業中の reviews/T-020.md ではなく、`git show 2d23cdf:reviews/T-020.md` の中身で確かめる。行の全体が `## 2026-10-08 オーナーの発言（原文のまま記録）` に一致する見出しがちょうど一つあり、その節に次の三行があること。
   - `> 病名は案B`
   - `> 民族、宗教の集団は除外の区分に加える。`
   - `> そのほかこのまま承認の項目は承認します`
8. **"undecided" の封印を拒むこと**：除外の規則の出力の JSON の `optional_choice_status` が `"decided"` であること。`"undecided"` なら封印しない（`tagrules.py` の出力の中の `exclusion` の欄も同じ）。
9. **テストが通ること**：封印する commit で `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -B -m unittest discover -s tests/stats` がすべて通ること。この中の `test_sealed_tests_read_only_targets` と `test_sealed_tests_source` が、封印する二つのテストが対象の外を読まないことを確かめる（限界は tags-naive.md 5章 (1) のあと）。`test_doc_is_frozen` が、tags-naive.md が `test_tagrules.py` の定数と同じであることを確かめる。
10. **対象だけを置いた写しで、見張りを付けずに流すこと**（T-024 M-b）：実行の見張りとソースの検査では、許可したモジュールの属性を通る os・sys の使い方、許可した形で読んだ環境変数による分岐、日付による分岐が止まらない（tags-naive.md 5章 (1) の限界）。これを補うため、封印係は次を行い、通らなければ封印しない。
    - プロジェクトと Git の外に、空のフォルダ `C` を作る（`P` はプロジェクトのルート、`H` は封印する commit の40桁の ID）。
    - 履歴は、1cb463a と 2d23cdf の参照に要る分だけを置く：`git -C "$C" init -q`、`git -C "$C" fetch -q --depth=1 "$P" 1cb463acfcf15ba315e6c454625ad681e86bbc2a 2d23cdf6e01de5129fc7b0a5d85e89bf02e892c6`。
    - 封印の対象のうちファイルの5件（`src/stats/exclusion.py`、`src/stats/tagrules.py`、`tests/stats/test_exclusion.py`、`tests/stats/test_tagrules.py`、`docs/stats/tags-naive.md`）だけを、`git -C "$P" show "$H":<path>` で `C` の同じパスに置く。10件のうち残りの5件は、この5件を実行した出力（2件）と、上の履歴から `git show` で読むもの（3件）である。
    - 見張りの環境変数を付けずに流す：`C` で `env -u STATS_AUDIT_LOG -u PYTHONPATH -u PYTHONPYCACHEPREFIX PYTHONDONTWRITEBYTECODE=1 "$P/.venv/bin/python" -B -m unittest tests/stats/test_exclusion.py tests/stats/test_tagrules.py` がすべて通ること。
    - 流したあと、`C` の中（`.git` を除く）に、置いた5件のほかのファイルが無いこと。
    - 結果（テストの件数と OK）と、`C` の中のファイルの一覧を、封印の記録に入れる。
    - これで見つかるもの：見張りの有無で分岐して対象の外を読む書き方と、対象の外のファイルを読んで通る書き方（写しには無いので失敗する）。見つからないもの：対象の外のファイルが無いときに別の道で通る書き方と、日付による分岐。統計係のテスト `test_sealed_tests_pass_in_targets_only_copy`（`tests/stats/test_t019.py`）が、同じ形の写し（作業ツリーのファイルを置く）で確かめている。
    - 写しのフォルダの扱い（残すか消すか）は、CLAUDE.md の削除の規則に従う。

**記録の種類（kind）と収集係の関門について（提案。src/collector と src/sealer は統計係の範囲の外）**
- 収集係の関門（`src/collector/themes.py` の `require_exclusion_rules_sealed`。GKG の取得も同じ関門を使う）は、今は、決まった kind の記録が ledger に1件以上あることだけを確かめ、記録の中身（どの規則を封印したか）を照らさない（themes.py の0章「確かめないこと」）。そのため、`tagrules.py` を含まない記録や、別の版の sha256 の記録でも、関門を通れる。
- 収集係の関門は、その kind の記録の中身が、この表の10件の対象の名前と sha256 と一致すること（少なくとも `src/stats/exclusion.py`、`src/stats/tagrules.py` とそれぞれの出力が入っていること）を照らすべきである。どう照らすか（表をコードに写すか、記録の対象を読むか）と kind の名前は、封印係と収集係が決める。統計係はリードに提案として伝える。

## 3. 封印のあと

### (1) 順番1の記録と作業ツリーの10件を照らす手順
順番1の記録ができたあと、凍結を確かめるのは、封印していないこの表やテスト（`test_seal_targets`）ではなく、ledger の記録である。次の手順で照らす。封印係の検証（docs/verify/）と、統計係・監査係が順番2以降の作業を始める前に、毎回行うことを提案する。

1. `sealed/ledger.jsonl` の鎖と、すべての seq の .ots を、封印係の検証の手順で確かめる（`src/sealer/verify.py`）。
2. 順番1の記録を ledger から選ぶ：kind が `stats-order1` の記録は、ledger の中で1件だけである（封印係の T-037 で、2件目は書けず、検証でも止まる。`src/sealer/ledger.py` の `check_stats_order`・`first_order1`）。その唯一の記録を読む（T-039 で、以前の「seq が最も大きいもの」から直した）。一件も無ければ止める。二件以上あれば、封印係の検証で止まる。新しい版で封印し直す必要が出た場合（tags-naive.md 2章 (6)、5章 (2)）の扱いは、今の仕組みには無く、オーナーの判断と封印係の別のタスクが要る。読んだ記録から、10件の対象の名前と sha256、封印した commit の40桁の ID を読む（2章の項目4・6で記録に入れたもの）。（stats-order1 は1件だけなので、照らす版を選ぶことは無い。T-039 差し戻し1回目 軽-C で、以前の「前の版の seq を指定して照らす」を削った。）
3. 作業ツリーで、10件の sha256 を計算し直す。**封印係は、自分のコードで、1章のバイト列の定義どおりに計算する**（T-024 L-c。たとえば `shasum -a 256 <ファイル>`、`git show <commit>:<path> | shasum -a 256`、`PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -B src/stats/exclusion.py | shasum -a 256`、1cb463a の版の出力は一時のフォルダに取り出して実行した出力を `shasum -a 256`）。`src/stats/order1_digests.py` は封印の対象の外にあるので、照合の根拠にしない。使う場合は、自分のコードの値と比べる参考に限る。第三者も同じ。
4. 3 の10件が、2 の記録の10件と名前も値もすべて一致することを確かめる。一件でも違えば、凍結が破られたか、封印したものと違うコードやテストが作業ツリーにある。その場合は作業を止め、リードに報告する。
   - とくに `tests/stats/test_tagrules.py` の sha256 が一致すれば、その中の定数 `TAGS_NAIVE_SHA256` は封印したときの値である。そのうえで `test_doc_is_frozen` が通れば、`docs/stats/tags-naive.md` は封印したときと同じである。表（この文書）と `test_t019.py` は封印していないので、照合の根拠にしない。
5. 2 の commit が、今の HEAD の祖先であることを確かめる（`git merge-base --is-ancestor <40桁の ID> HEAD`）。
6. 封印したテストを流す：`PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -B -m unittest tests/stats/test_exclusion.py tests/stats/test_tagrules.py` がすべて通ること。

順番1の封印のあとで、規則やテストを直す必要が出た場合は、作業ツリーのファイルを直す前に、新しい版として扱う（tags-naive.md 2章 (6)、5章 (2)）。この表は直さず、新しい版の表を別の文書に作る。

### (2) 順番2・3・5の記録
- 順番3（数え方とのつながり）の記録には、この順番1の記録の seq と sha256 を参照として入れる。順番2の記録の seq と sha256 も参照として入れる。順番3の関門と参照する記録の決め方は `counting.md` 4章 (3) と `counting.order3_gate()` のとおり（T-038・T-039）：(1) 参照する順番1b の記録は、順番3の時点の ledger の順番1b の kind の記録のうち seq が最も大きいもの（順番2と同じ決め方）。(2) 数える順番2の記録は、その順番1b の記録を参照したものだけ。(3) 封印係が、その順番1b の記録の時機の条件を順番3の時点で確かめ直し、確かめた内容（結果、HEAD、F の集合の各 commit と親、`git for-each-ref` の参照の一覧、理由）を組で渡す。満たさなければ封印しない（順番2のあとで判明した (a) の破れもここで止まる）。(3b) 前の順番3の試みで時機の条件の破れが記録されていれば、恒久に封印しない。(4) 数える記録に (a) で止まった記録が一つでもあれば封印しない。(5) 待つの記録を除き seq が最も小さいものを参照する。0件なら封印しない。(6) 順番3の試みは、通った場合も止まった場合も毎回 ledger に記録して公開する（`order3_gate()` の `record`）。時機の条件の破れで止めて公開し、扱いをオーナーが決めることは、オーナーの承認（承認事項3）の中にある。(1)(2)、順番3の時点での確かめ直し、(3b)、(5)、(6) の記録の規定は、承認のあとでリードの割り振りにより足した細目で、承認の範囲の外である。入れる規則の定数と式は、順番3で足したり変えたりしない（`docs/stats/tags-naive.md` 5章）。
- 順番2の記録には、参照する順番1b の記録の seq と sha256、正式な数え方の識別子（`C7`。順番1b で決まったもの）とそれが入力で計算できたか、参考の基準の案 B1〜B5 を入力に当てはめた結果（どれも「正式ではない」）、入力の日ごとの欄の手厚さ（`counting.md` 5章。S の `docs_without_v1_theme`・`docs_without_v2_theme`・`docs_without_any_theme` と、すべての組の D の和）、当てはめに使った入力の sha256 を入れる（T-036 で直した）。
  - **参照する順番1b の記録の決め方**（T-025 差し戻し1回目 中1）：ledger の中で、順番1b の kind の記録のうち seq が最も大きいものを参照する。それが下の時機の条件を満たさなければ、順番2を封印しない（それより前の順番1b の記録に戻って使うこともしない）。理由（前提 → 結論）：
    - 前提1：参照する記録を、ledger の並びだけから決まる規則で決めれば、試運転の結果を見てから参照する記録を選ぶ余地は無い。
    - 前提2：順番1b の記録が二つ以上できるのは、データに触れる前に誤りを直して封印し直す場合でありうる。「ちょうど一件でなければ封印しない」とすると、その場合に順番2へ進めなくなる。
    - 前提3：「時機の条件を満たす中で最大の seq」とすると、データに触れたあとに封印された順番1b の記録があっても、黙って前の記録が使われ、関門の破れが表に出ない。
    - 前提1・2 から、決め方は「最大の seq」にし、ちょうど一件は求めない。前提3 から、最大の seq の記録が時機の条件を満たさなければ、前の記録で代えずに止める。ほかの順番1b の記録（前の版）も消えず、順番5でそのまま公開する。
  - **時機の条件**（参照する順番1b の記録が、試運転のデータより前に封印されたこと）：
    - ledger で、参照する順番1b の記録の seq が、`kind` が `method-access` の最初の記録の seq より小さいこと（method-access の記録が無ければ、この条件は満たす）。
    - git の履歴で、参照する順番1b の記録が、GKG のマニフェストに行が入るより前の commit にあること（T-028 差し戻し1回目 中4 で、`L` を封印の記録の値（自己申告）から決める形をやめ、git だけから決める形にした。T-025 の監査の軽1 のとおり、commit の時刻で決まる並びは使わない）。
      - `X`：参照する順番1b の記録の、`sealed/ledger.jsonl` の行のバイト列（改行を除く）。
      - `F` の集合：`git log --all --full-history --format=%H -- data/manifest/gdelt-gkg-trial.jsonl data/manifest/gdelt-gkg-method.jsonl` が出すすべての commit のうち、その commit の版で二つのマニフェストのどちらかに行が一つ以上あるもの。並び順は使わず、集合として扱う。
      - F を数える範囲（T-040 中-1 (b) で定義の中に書いた）：`--all` が辿る始まりは、`git for-each-ref` のすべての参照の先と、`git worktree list --porcelain` の各 worktree の HEAD である。順番3の試みの記録には、この二つ（refs と worktree_heads）を入れ、F はそれらから辿れる commit で数える。関門は本体の worktree（clone した最初の作業ツリー）で動かす。そうした場合に `git log --all` と同じ範囲になることを `tests/stats/test_counting.py` の `TestFScope` で確かめた（`counting.md` 4章 (3)。別の worktree の中だけの参照は、どちらの範囲にも入らない。T-040 差し戻し1回目 軽-A）。
      - `F` の集合のすべての commit `C` について、`C` の親（`git rev-parse "C^@"` が出すもの）のうち少なくとも一つの版の `sealed/ledger.jsonl` に、行の全体が `X` と一致する行があること。親が無い commit（最初の commit）が `F` の集合にあれば止める。一つでも満たさなければ止める。
      - これで確かめられること：どの履歴の線でも、マニフェストに行が入った commit の手前に、順番1b の記録を含む commit がある。`F` の集合の中で最も手前の commit について、その親は順番1b の記録を含み、かつ（`F` の集合に入らないので）マニフェストに行が無い。ledger は追記のみなので、それより後の commit にも記録は残る。だれかが選んだ commit の ID は使わない。
      - 二つのパスを変えていない commit でも、マニフェストに行があれば、行を入れた commit の子孫である。親をたどる確かめは `F` の集合の commit について行えば足りる。
      - 順番2はふつう試しの run のあとなので、`F` の集合は空でないはずである。空なら、この条件は満たす（ただし下の入力の規則で待つ）。
    - **git replace を使わせない**（T-044。T-040 初回の監査の軽-B）：この条件の git の計算（`git log`、親の読み出し、`git merge-base` など）は、すべて環境変数 `GIT_NO_REPLACE_OBJECTS=1` を付けて行う。計算の前に `git for-each-ref refs/replace/` を確かめ、一つでも参照があれば計算せずに止める（収集係の `src/collector/codegate.py` の `GIT_NO_REPLACE_OBJECTS` と `check_clean` の refs/replace の確かめと同じ形）。置き換えの参照があると、commit の親を差し替えて、F の集合や親子の関係を変えられるため。順番2と順番3の両方で同じにする。
    - **graft と浅い clone も使わせない**（T-051。T-044 の監査の軽-3 (a)）：`.git/info/grafts` と浅い clone（`.git/shallow`）は、`GIT_NO_REPLACE_OBJECTS=1` を付けても commit の親を変える（統計係が scratchpad で、grafts の行で親が差し替わり、`GIT_GRAFT_FILE` を存在しないパスにすると元の親に戻ることを確かめた）。そこで、この条件の git の計算は、`GIT_NO_REPLACE_OBJECTS=1` に加えて、環境変数 `GIT_GRAFT_FILE` を存在しないパス（たとえば一時の場所の、作っていないファイルの名前）にして行う。さらに、計算の前に graft のファイルが無いことと、`git rev-parse --is-shallow-repository` が `false` であることを確かめ、どちらかに当たれば計算せずに止める（graft のファイルがあるときは、`GIT_GRAFT_FILE` で無効にしたうえで、なお止める。置いてあること自体を、記録に残る止まりにするため）。graft のファイルの場所は、`GIT_GRAFT_FILE` に左右されない形で決め打ちにする：`git rev-parse --path-format=absolute --git-common-dir` の出力の下の `info/grafts`（T-053。`git rev-parse --git-path info/grafts` は `GIT_GRAFT_FILE` を付けるとそのパスを返すので使わない。統計係が scratchpad で確かめた）。順番2と順番3の両方で同じにする。
    - **GIT_ で始まる環境変数を固定する**（T-053。T-051 の監査の軽-1）：時機の条件の git の計算は、`GIT_` で始まる環境変数を、決めたもの（`GIT_NO_REPLACE_OBJECTS=1` と、存在しないパスの `GIT_GRAFT_FILE`）だけに固定して行う。ほかの `GIT_` で始まる環境変数（`GIT_SHALLOW_FILE`、`GIT_DIR`、`GIT_OBJECT_DIRECTORY`、`GIT_ALTERNATE_OBJECT_DIRECTORIES` など）は、呼び出す前の環境から外す。これらは、親や object の見え方、読むリポジトリを変えうるため。順番2と順番3の両方で同じにする。
    - 時刻（recorded_at やマニフェストの行の時刻）は、記録した機械の時計なので、この条件には使わない。照らすのは ledger の seq と git の親子の関係だけである。
  - **基準の入力を一つに決める規則と、止まったあとの行き先**（T-028。T-025 の監査の中2、T-028 差し戻し1回目 中3）：規則は `docs/stats/counting.md` 4章と `src/stats/counting.py` の `decide()` で、順番1b で一緒に封印する。要点は次のとおり。
    - 読むマニフェストは、順番2を封印する HEAD（40桁）の `data/manifest/gdelt-gkg-trial.jsonl` と `data/manifest/gdelt-gkg-method.jsonl`（`git show <HEAD>:<パス>` のバイト列。無ければ空）。封印係は、それぞれについて、作業ツリーのファイルと同じであること、`git log --all --full-history --format=%H -- <パス>` のすべての commit の版がこのバイト列の先頭と同じであること（追記だけ。並び順は使わない）を、自分のコードで確かめる。通らないマニフェストは「使えない」として `decide()` に渡す（`counting.py apply` では `FAILED`）。
    - 手順と行き先は `counting.md` 4章 (2) の表のとおり（T-028 差し戻し2回目 中-B1・中-B2、3回目 中-3 で直した）。要点：
      - 二つのマニフェストのどちらかが git の確かめに通らなければ、止まる。マニフェストのファイルが読めないときも止まる（HEAD にファイルが無いことは、`counting.py apply` では `EMPTY` と書いて示す）。
      - 正式な run の `run-start` があれば、試しの run のマニフェスト（HEAD の版）の sha256 がその `trial_manifest_sha256` と一致し、`trial_run_ids` の最初が R（試しの run の最初の `run-start` の run）であること。満たさなければ止まる。正式な run の開始のあとで試しの run のマニフェストに `run-complete` などを書き足すと、ここで止まる。
      - 1段目：R に `run-complete` があれば、R の3日の集計を使う。
      - 待つ：試しの run が無いか R に `run-complete` が無く、正式な run の `run-start` がまだ無いとき。2段目の3日の `day` の行がまだそろっていないとき。データの値を見て決まる条件ではない。そろったあと、同じ順番1b の記録で同じ手順をもう一度行う。封印係は、順番2を試みるたびに結果（待つを含む）を ledger に記録することを提案する（待った回数を第三者が数えられるようにするため）。
      - 2段目：正式な run の `run-start` があり、かつ試しの run の `run-start` が一つも無いか、試しの run の `run-start` が R の一つだけで R に `day` の行が一つも無いときだけ、正式な run（最初の `run-start` の run）の同じ3日の集計を使う。
      - 正式な run の `run-start` があり、R に `run-complete` が無く、R に `day` の行があるか、試しの run の `run-start` が二つ以上あるときは止まる。
      - ファイルが無い・sha256 が合わない・頭の行が合わない・正式な数え方 C7 が計算できない（T-036）、は**2段目に進まず止まる**（1段目でも2段目でも）。
    - **入力のファイルの照合**：封印係は、入力の各日のファイル（`gkg-<mode>-<run_id>-day-<YYYYMMDD>.tsv.gz`）のバイト列の sha256 を自分のコードで計算し、上のコミットしたマニフェストの、その日の `day` の行の `sha256` と一致することを確かめる。**一致しなければ、封印しない（止まる）。** 頭の行の日と mode も確かめる。
    - 基準が該当なしのときは、`counting.FALLBACK_ORDER` のその基準の順で使える最初の候補にする（`counting.md` 3章 (1) の表）。
    - 記録には、使った段、run_id、二つのマニフェストの HEAD の版の sha256、3日のファイルの名前と sha256、通った手順と止まった理由（`decide()` の `steps`）、**二つの run（試しの run R と正式な run）の run_id と、両方の run の3日の `failed_files`**（`decide()` の `runs`）を入れる。順番5の公開物でも並べて示す。
  - **当てはめ（封印係の計算を正とする）**（T-025 差し戻し1回目 中2。T-028 差し戻し1回目 中3 で直した）：封印係は、順番1b の記録の sha256 と一致する `src/stats/counting.py` を自分で実行し、上の規則で決まった入力に当てはめる。その結果を順番2の結果とする。収集係など、ほかの者が示した結果と違っても止めず、違ったことを記録に入れる。出力の正式な数え方が、順番1b の記録の正式な数え方（C7）と違えば、封印しない（コードが封印したものと違う）。
  - **順番2で止まったあとの扱い**（T-028。T-025 の監査の軽2、T-028 差し戻し1回目 中3）：
    - 止まるのは、(a) 時機の条件を満たさないとき、(b) `decide()` が stopped を返したとき、(c) 参照する順番1b の記録のコードの sha256 が合わないときだけである。待つ（pending）は止まったことにしない。
    - 止まった事実を記録して公開する：封印係が、どの条件で止まったか、参照した順番1b の記録の seq、`decide()` の出力（各段の理由と、分かっている範囲の入力の sha256・当てはめの結果）を ledger に記録する（kind は封印係が決める）。順番5の公開物にも載せる。止まったことを記録せずに、黙って作業を続けたりやり直したりしない。
    - 止まったあとの行き先（T-036 で直した。`counting.md` 4章 (3)）：
      - (b) と (c) の場合：正式な数え方 C7 は順番1b で決まっていて、順番2の入力に依らないので、変えない・代えない。新しい版の順番1b には進まない。止まった事実を順番2の記録として封印する。順番3は、上の選び方（seq が最も小さいもの）で選んだ順番2の記録を参照して進む。参考の基準の結果と欄の手厚さは、この入力からは出さず、順番5で手法を作る期間の全体について出す。(c) の場合に、封印係が順番1b の記録のコードで当てはめ直して、決まった記録をもう一つ封印してもよいが、順番3が参照するのは seq の小さい (c) の止まった記録である（参考の結果と欄の手厚さは順番5で出す）。
      - (a) の場合：順番1b が試運転のデータに触れたあとに封印されたことになり、正式な数え方を決めた時機が保証されない。止まった事実を記録して公開し、その版の扱い（新しい版として封印し直すか、どの限界を付けて公開するか）は、オーナーが決める（統計係の範囲の外。リードに報告する）。今の封印係の仕組み（`src/sealer/ledger.py` の `check_stats_order`）は、最初の method-access より後の stats-order1b の記録を拒むので、method-access のあとに新しい版の順番1b を封印することはできない。新しい版を作るには、オーナーの判断と封印係の仕組みの変更が要る。作った場合でも、その版は時機の条件を満たさないので、結果は「試運転のデータに触れたあとに決めた版」と明記して公開する（T-039 差し戻し1回目で、今の check_stats_order に合わせて直した）。前の版の記録と止まった事実は消さず、版ごとに別々に扱う（CLAUDE.md「一覧は途中で足したり外したりしない。変える場合は新しい版として封印し直し、版ごとに別々に採点する」と同じ扱い）。
    - (b) には、運営側が起こせる操作（試しの run のファイルを消す・差し替える、正式な run の開始のあとで試しの run のマニフェストを書き足す、マニフェストの履歴を書き換える、試しの run を途中で止めたまま正式な run を始める、試しの run を二つ以上行う）で至る。これらは代わりの入力に進ませず止まり、止まったことが公開される。正式な数え方は C7 に決め打ちなので、これらの操作で変わりうるのは、参考の結果と順番2の欄の手厚さが出るかどうかだけである（T-028 差し戻し2回目 中-B2、3回目 中-3、T-036）。
- 順番5（タグの一覧の結果）の記録には、順番1と順番1bと順番3の記録の seq と sha256 を参照として入れる。順番5を始める前に、(1) の照合を行う。順番5の記録には、順番1b で封印した候補のすべての数え方（C1〜C7）での一覧と N_med・A と、封印したすべての参考の基準の案が入っていること（候補と基準の案の数と識別子が順番1b の記録と一致すること）を確かめる。正式な結果は C7 の一つだけとし、記録の中で正式な結果がちょうど一つに印されていること、ほかの候補の結果と基準の案に「比べるための参考で、正式ではない」が付いていることを確かめる。公開のときも同じ区別で並べる（tags-naive.md 0章の B (ii)、2026-10-08 のオーナーの決定）。順番5の記録には、欄の手厚さ（`counting.md` 5章）を、手法を作る期間の暦の四半期ごとと期間全体について入れる。欠けた日でない日に C7 の分母が 0 の日があれば、順番5を封印せず、止まった事実を記録して公開し、リードを通してオーナーに報告する（ほかの候補に代えない。`counting.md` 4章 (3)）。参考の候補（C1〜C6）の分母が 0 の日がある場合は、その候補を「計算できない（理由と日の一覧）」と記録して並べ、順番5は止めない（T-036 差し戻し1回目 中-3。`counting.order5_candidate_status()`）。

### (3) 順番1b（数え方の候補の一覧と、選ぶ基準）の封印の関門（T-024、T-025。tags-naive.md 0章の B (i)・(ii) の承認による）
候補の一覧と基準の案そのものは、収集係と統計係の別のタスクで作る。ここに書くのは、順番と、封印係が封印の前に確かめる条件だけである。次のどれか一つでも満たさなければ、封印しない。
0. **試しの run の作りを直すタスクが合格していること**（T-028 差し戻し1回目 中2）：試しの run は、マニフェストのコミットと時刻証明より前に、3日分の集計を見て取り直せる（`docs/stats/counting.md` 4章 (4)）。これを塞ぐ収集係（と封印係）の別のタスクを、リードが割り振る。そのタスクの合格が `reviews/` に記録されるまで、順番1b を封印しない。そのタスクで試しの run の記録の形が変わる場合は、`counting.md` 4章の入力の規則と `counting.py` を、順番1b の封印の前に合わせて直す。
1. **method-access と手法を作る期間の報道量の取得がまだ無いこと**：2章の項目2のうち、`sealed/ledger.jsonl` に `kind` が `method-access` の記録が無いこと、GKG のマニフェスト（`data/manifest/gdelt-gkg-method.jsonl`・`data/manifest/gdelt-gkg-trial.jsonl`）が作業ツリーに無いか行が無く、`git log --all --oneline` の履歴も空であること。マニフェストも直接確かめる理由は、2章の項目2と同じ（method-access の記録が無いことは、入口のスクリプトの関門を通った取得が無いことしか示さず、`gkg.run_gkg` を直接呼んだ取得の跡はマニフェストにだけ残るため。T-028 で直した）。
2. **候補の一覧が有限で、一つずつ識別子があること**：一覧のファイルの sha256 を封印係のコードで計算して記録に入れる。候補の数と識別子の一覧も記録に入れる。
3. **候補の一覧へのオーナーの承認が記録と照らせること**：承認の発言を記録した commit の40桁の ID と、承認の引用の行を、2章の項目1と同じ形（commit を指定した `git show` と、行の全体の一致）で照らし、記録に写す。counting-v1 の承認（T-038 で書き入れた）は、`git show a970019c61808738b02629b14f68b3171c4ddd57:reviews/T-036.md` で、(i) 行の全体が `> 承認します` と一致する行がファイルの中でちょうど1つあり、(ii) その行より前で最も近い `## ` の見出しの行の全体が `## 2026-10-08 オーナーの発言（原文のまま記録。順番1b の承認事項）` と一致し、(iii) その見出しの行もファイルの中でちょうど1つあること（`counting.OWNER_APPROVAL_1B`・`counting.approval_line_ok()`）。見出しと組で照らすのは、同じ行が別の節にあとで記録されても一つに決まるようにするため。この承認は、候補の一覧（7つ）、参考の基準の案（5つ）、うまくいかなかったときの行き先、欄の手厚さの公開をまとめて承認したもの。**承認の範囲の外**（T-039 で注記し、差し戻し1回目 軽-B で細目に限り、T-040 軽-3 で分け直した）：次の細目は、承認のあとでリードの割り振りにより足したもので、オーナーが承認した内容には入らない。順番2の記録の選び方（待つ以外で seq が最も小さいもの、0件なら封印しない。T-038）、順番3が参照する順番1b の記録の選び方（seq が最も大きいもの）と ref_1b_seq での絞り込み、順番3の時点で時機の条件を確かめ直すこと、順番3の試みのうち通った場合も記録すること、試みの記録の中身（timing_check の項目、F を数える範囲、git bundle。T-039・T-040）。一方、時機の条件の破れが分かったら止めて公開し、扱いをオーナーが決めることは、承認事項3の中にある。順番3の試みのうち止まった場合の記録は、この「公開」にあたるので、承認の中である。封印の記録に承認を写すときは、この区別も写す（`counting.as_record()` の `outside_owner_approval`）。
4. **基準の案の一覧が記録され、正式な数え方がちょうど一つ決まり、すべての案が決定的な規則であること**（tags-naive.md 0章の B (ii)。T-025。T-036 で、正式な数え方をオーナーの決定から決める形に直した）：
   - 基準の案の一覧（採らなかった案を含む）のファイルの sha256 を封印係のコードで計算して記録に入れる。案の数と識別子の一覧も記録に入れる。
   - 正式な数え方：`counting.official_candidate()` が、`counting.OWNER_DECISION`（分子の欄と分母）に当たる候補を候補の一覧からちょうど一つ引き、`counting.OFFICIAL_CANDIDATE` と一致し、`counting.official_status()` が `"decided"` であること。counting-v1 では `C7`。`OWNER_DECISION` の出どころを、2章の項目1と同じ形で照らして記録に写す：`9c85f58f054a679b8e5f40fcd7adbb17536f6366:reviews/T-028.md` の中で、(i) 行の全体が `> 作り方2を、新しい候補として加え、正式に使う数え方にしよう` と一致する行がちょうど1つあること、(ii) 先頭が `- 決定：正式に使う数え方は、` の行がちょうど1つあり、その行に `V1 か V2 の少なくとも一方` と `同じ数え方の全テーマの合計` の両方が含まれること（T-036 差し戻し1回目 中-4。`counting.DECISION_PHRASES`）。満たさなければ封印しない。基準の案 B1〜B5 は参考で、どれも正式ではない。
   - **すべての案が決定的な規則であること**（T-025 差し戻し1回目 中2）：案ごとに、次の4つが書かれていること。一つでも欠ければ封印しない。
     - 入力：試運転のあとに分かる、どのデータ（収集係の集計のどの欄、どのファイル）を読むか。
     - 出力：候補の一覧の識別子のちょうど一つ。
     - 同点：二つ以上の候補が同じ評価になったときに一つに決める規則（例：候補の識別子の順で最初のもの）。
     - 該当なし：どの候補も条件を満たさないときの結果（決まった一つの候補にするか、順番2を封印しないで止めるか）。
     - 規則をコードで書く場合は、そのコードのファイルのパスと sha256 を記録に入れる（ファイルは6と同じく、プロジェクトの中で HEAD に含まれること）。文書で書く場合も、同じ入力から同じ出力が一つに決まる書き方であること。
     - **止まったあとの行き先が決まっていること**（T-028 差し戻し1回目 中3）：該当なしのときの代わりの候補、入力の段（どの場合に2段目を使い、どの場合に止まるか）、待つ条件が、基準の案と同じ記録に入っていること。counting-v1 では `counting.md` 3章 (1)・4章と `counting.py` の `FALLBACK_ORDER`・`decide()`。
     - **入力を一つに決める規則**（T-028。T-025 の監査の中2）：試しの run の記録のうち、どの run のどのファイルを入力にするかを決める規則が、基準の案と同じ記録に入っていること。無ければ封印しない。T-028 の提案（counting-v1）では、規則は `docs/stats/counting.md` 4章と `src/stats/counting.py` の `select_trial_input()` で、順番2での照らし方は3章 (2) に書いた。
   - 基準の案の一覧へのオーナーの承認を、3と同じ形で照らして記録に写す（counting-v1 では、3の承認と同じ行）。
   - B (ii) の承認の出どころ（`0f98e62b2810011c269efdd5836bd7cf3a5d5fce:reviews/T-024.md` の、2章の項目1の行）も記録に写す。
   - **限界**（T-025 差し戻し1回目 軽3）：関門で照らせるのは、記録に入った案の一覧について、正式な数え方がちょうど一つ決まり、すべての案が決定的な規則で、一覧がオーナーの承認したものと一致すること（3と同じ照らし方）までである。作る人が検討したのに一覧に載せなかった案があるかどうかは、記録からも関門からも確かめられない。「検討した案をすべて」は、一覧を作るタスクで作る人が守ることで、関門の条件ではない。この限界は順番5の公開物にも書く。
5. **作業ツリーがきれいで、HEAD を40桁で記録すること**：2章の項目3・4と同じ。
6. **候補の一覧と基準の案のファイルがプロジェクトの中にあり、記録する HEAD に含まれること**（T-025 L5）：二つのファイル（一つにまとめてもよい）のパスがプロジェクトのルートの下の相対パスで、`git cat-file -e <HEAD の40桁>:<パス>` が0で終わり、`git show <HEAD>:<パス>` の sha256 が、作業ツリーのファイルの sha256 と、記録に入れる sha256 の両方と一致すること。プロジェクトの外のファイルや、コミットしていないファイルは封印しない。
- 監査の申し送り（候補の一覧を作る別のタスクへ。T-025）：候補は、どれも収集係の集計の形（保存する項目の一覧で絞ったあとのデータ）から計算できるものに限る必要がある。集計の形から計算できない候補を入れると、その候補の結果は順番5で計算できず、全候補を並べて公開する約束（tags-naive.md 0章の B (i)）を守れない。候補の一覧を作るタスクでは、候補ごとに、収集係の集計のどの欄から計算するかを書き、計算できることを確かめること。（T-028 で対応：`docs/stats/counting.md` 2章の表に候補ごとの欄を書き、`tests/stats/test_counting.py` が収集係の `gkg.serialize_day` で作った集計から候補を計算して確かめる。T-036 で、版3の集計から C7 を含む7つの候補を計算する形にした。）
- 順番1との前後は問わない。順番1のあとに封印する場合は、順番1の記録の seq と sha256 を参照として入れる。
- 収集係の GKG の取得の関門（`require_exclusion_rules_sealed` と同じ形）に、順番1b の記録があることを足すかは、封印係と収集係が決める（統計係の範囲の外。リードへの提案）。

**封印係への申し送り（T-038。順番1b・順番2・順番3の関門を実装するとき。統計係の範囲の外なので提案）**
- 順番2の試みの記録は、待つ（pending）・決まった（decided）・止まった（stopped）を、kind ではなく記録の中の status で区別する。kind を分けると、待つの記録を順番2の記録の kind で数えてしまう誤りや、kind の選び方で数えるかどうかを変える余地が出るため。止まった記録には、(a)（時機の条件）・(b)（`decide()` が stopped）・(c)（コードの sha256 が合わない）のどれかを stop_kind として入れる。
- 順番3の関門は、`counting.order3_gate()` と同じ規則を、封印係のコードで行う（参照する順番1b の記録は seq が最も大きいもの、数える順番2の記録はそれを参照したものだけ、順番3の時点で時機の条件を確かめ直す、前の試みで破れが記録されていれば恒久に止める、(a) の記録が一つでもあれば止める、待つ以外のうち seq が最も小さいものを参照、0件なら止める）。順番2の記録には、参照した順番1b の記録の seq（ref_1b_seq にあたるもの）を入れる。
- **順番3の試みの記録**（T-039 差し戻し1回目 中-A）：順番3を試みるたびに、通った場合も止まった場合も、1件の記録を ledger に追記する。kind は封印係が決める（待つ・通った・止まったを kind で分けず、記録の中で区別する）。中身は `counting.order3_gate()` の `record` と同じ項目：may_seal、reason、ref_1b_seq（順番1b の記録が無ければ null）、chosen_order2_seq、timing_check（ok、ref_1b_seq、head（40桁）、f_set（各 commit の40桁の ID と親の一覧）、refs（`git for-each-ref --format='%(refname) %(objectname)'` の全行。参照の名前と40桁の ID）、worktree_heads（`git worktree list --porcelain` の各 `HEAD` の行の40桁の ID。T-040）、reason）。照合では、f_set と親が、記録した refs と worktree_heads の commit から辿って git で計算し直したものと一致すること、ok がその f_set から時機の条件で計算した結果と一致することを確かめる。
  - **前の試みの渡し方**（T-040 軽-2）：前の試みの記録は、`counting.attempt_from_record(その記録の seq, 記録の中身)` で order3_attempts の要素（seq、ref_1b_seq、may_seal、timing_ok）にする。timing_ok は記録の timing_check.ok から取る。順番1b の記録が無かった試み（ref_1b_seq が null）もそのまま渡す。
  - **記録の形と、前の試みとの噛み合わせ**（T-040 差し戻し1回目 軽-C）：試みの記録は `{"gate": <order3_gate() の record。キーはちょうど5個>, "bundle": <下の bundle の欄>}` の二つに分ける。前の試みを渡すときは、gate の部分だけを `counting.attempt_from_record()` に渡す（bundle の欄を含めると、キーが5個でないので止まる）。
  - **commit の実体の保存と公開**（T-040 中-1 (a)）：試みのたびに、`git for-each-ref` と `git worktree list --porcelain` を記録したあとで、`git bundle create <file> --all` で bundle を作る。一時の参照は付けない（`--all` の bundle は、ほかの worktree の HEAD も `worktrees/<名前>/HEAD` として入れ、切り離した HEAD の commit も含む。統計係が scratchpad で確かめた）。bundle の欄には、bundle のバイト列の sha256、公開したか（published）、公開しなかった理由（reason）を入れる。bundle は下の検査に通ったときだけ、公開できる場所（リリースの添付など）に置く。bundle の作り方の細部と置き場所は封印係が決める。
  - **記録と bundle の一致**（T-044 軽-2）：bundle を作ったあと、`git bundle list-heads <file>` の結果が、記録した refs と worktree_heads と一致することを確かめる。具体的には、記録した refs の各（名前、commit）が list-heads にそのまま現れ、list-heads の `refs/` で始まる参照がすべて記録した refs にあり、list-heads の `HEAD` と `worktrees/<名前>/HEAD` の commit の集合が、記録した worktree_heads の集合と一致すること。合わなければ（記録してから bundle を作るまでに参照が変わった場合など）、その試みは関門の結果を出さずに止まる。止まったことは、封印係が試みの記録として残す（時機の条件を確かめた結果ではないので、破れとしては数えない）。
  - **bundle を公開する前の検査**（T-040 差し戻し1回目 中-1、T-044 中-α。CLAUDE.md「push 以外の公開も、公開の前に同じ検査を通す」「公開される場所に置けるのは、項目の一覧で絞ったあとのデータだけ」）：bundle には push していない commit も入るので、公開の前に次を行う。
    - (0) 検査の範囲をそろえる：bundle をプロジェクトと Git の外の一時の場所に clone する（`git clone <bundle> <clone>`）。clone だけでは、参照は `refs/heads/*` からしか作られず、`refs/stash` や `worktrees/<名前>/HEAD` の先の commit は検査されない（`git bundle unbundle` も参照を作らない）。そこで、`git bundle list-heads <bundle>` のすべての行（`refs/stash`、`HEAD`、`worktrees/*/HEAD` を含む）について、その名前を clone の一時の参照に fetch する：`git -C <clone> fetch <bundle> "<名前>:refs/bundle-heads/<通し番号>"`。
    - (1) その clone に `src/collector/privacy_scan.py --root <clone> --all-history` を通す。許可していないメールアドレスの形が一つでもあれば公開しない。
    - (2) 同じ clone で、`git -C <clone> log --all --name-only --format=` などで、すべての参照から辿れる commit の版のファイルの一覧を取り、GDELT の元のファイル（一括ファイルの zip や csv など）や、項目の一覧で絞る前のデータが無いことを確かめる。確かめ方（パスと形の規則）は封印係と収集係が決める。
    - 統計係が scratchpad で確かめたこと（T-044）：作り物のリポジトリで、作り物のアドレス（example.invalid の4つ）を、本体のブランチの commit、stash、ブランチの上の worktree の commit、切り離した HEAD の worktree の commit に一つずつ入れ、`git bundle create --all` で bundle を作った。clone だけでは、本体のブランチと、ブランチの上の worktree の commit（clone でも `refs/heads` に入る）の2つしか見つからず、stash と切り離した HEAD の2つは見つからなかった。(0) のとおり list-heads の6つの参照をすべて fetch してから流すと、4つとも見つかった。
    - **検査に通らなかった bundle の扱い**（T-044 軽-3。リードの判断、reviews/T-040.md の判定）：プロジェクトと Git の外の決まった場所に置き、公開しない。他人のメールアドレスを含む場合は、CLAUDE.md の「プロジェクトと Git の外に一時的に入ったものは、オーナーの承認を得て削除する」に従う。試みの記録の bundle の欄には、公開できないことと理由だけを入れる（見つかった文字列や、捨てるべき中身は書かない）。その試みについては、第三者が commit の実体を照らせない（`counting.md` 8章の (a) の限界に回す）。一時の clone の扱いも、CLAUDE.md の削除の規則に従う。
  - **「試み」の意味と書く順**（T-040 中-1 (d)）：「順番3の試み」は、封印係の順番3の関門のコードを一回動かすことを指す（結果が通るか止まるかによらない）。関門のコードは、`order3_gate()` の結果を画面に出したり、順番3の封印に進んだりする前に、試みの記録を ledger に追記する。追記できなければ、結果を出さずに止まる。記録を書かずに時機の条件や関門の結果を確かめるだけの使い方（確かめるだけの引数、乾式の実行など）は作らない。手で git を打って確かめることは防げない（`counting.md` 8章の (d)）。
- 順番1b の関門で、`OWNER_DECISION` の2つ目の出どころ（`9c85f58f054a679b8e5f40fcd7adbb17536f6366:reviews/T-028.md` の、先頭が `- 決定：正式に使う数え方は、` の行がちょうど1つあり、`counting.DECISION_PHRASES` の語句をすべて含むこと）を、封印係のコードで照らす（T-036 再提出1回目の監査の軽-4）。承認の出どころ（3の照らし方）も、封印係のコードで照らす。
- 順番2の試みは、待つ場合も含めて毎回記録する（待った回数を第三者が数えられるようにする。`counting.md` 4章 (2)）。

## 4. 引用
Data: The GDELT Project (https://www.gdeltproject.org/). This project is not affiliated with or endorsed by the GDELT Project.
データ出典：GDELT Project（https://www.gdeltproject.org/）。本プロジェクトは GDELT Project と提携・承認の関係にありません。
（この文書は GDELT のデータを使っていないが、規則は GDELT のデータに適用するため付ける。）
