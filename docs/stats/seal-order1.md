# 順番1の封印：封印係への申し送り（T-022）

封印の順番と、その理由は `docs/stats/tags-naive.md` 5章にある。この文書は、順番1（除外の規則と入れる規則）を封印するときに、封印係が確かめることと、封印の対象の sha256 をまとめたものである。

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
| `tests/stats/test_tagrules.py` | `52a63b3425ed9d6cb13a2bd00fd0fb32823939197988892b93a8d190d0098f51` |
| `docs/stats/tags-naive.md` | `de54364e20ce491a772bb9b487a403e8d11ff9eb2cb9ebd85a01b2de08bb937e` |
| `1cb463a:src/stats/tagrules.py` | `f7c325cb21bcf39c42e6d785deacbe47eacec7fb2834d2927634e446b62ce57a` |
| `1cb463a:src/stats/tagrules.py の出力` | `98926edbbbc7ac0375aee97aa7be0b1a5e3fcf3bc4acbadfa99f5d17362f7b8a` |
| `2d23cdf:reviews/T-020.md` | `0b80ec29a994e04224900b3aafbc56a78d5cd9d4cee6e8d3df6c82a211cf46e7` |

- ファイルの sha256 は、ファイルのバイト列そのもの。
- 「の出力」は、プロジェクトのルートで `PYTHONDONTWRITEBYTECODE=1 python3 -B src/stats/exclusion.py`（`tagrules.py` も同じ）を引数なしで実行した標準出力のバイト列。
- `1cb463a:` と `2d23cdf:` で始まるものは、`git show <commit>:<path>` の標準出力のバイト列。1cb463a の版の出力は、そのファイルを一時のディレクトリに取り出して（`git show 1cb463a:src/stats/tagrules.py > tagrules.py`）、同じように引数なしで実行した標準出力のバイト列。
- 統計係が計算したときの Python の版：3.14.2（`.venv/bin/python` と `python3` のどちらも）。
- 順番1で封印したあとは、この表も `docs/stats/tags-naive.md` も直さない（tags-naive.md 5章 (2)）。凍結を確かめる根拠は封印の記録で、照らす手順は3章 (1)。
- 移した `docs/stats/naive-scoring.md`（素朴な予測と採点計画の一部）は、順番1の対象に入れない。最初の threshold-access より前なら改訂できる章で、封印は `naive.py`・`scoring.py` と一緒に順番6〜8で行う。順番1で封印する二つのテストは、この文書を読まない（`test_sealed_tests_read_only_targets`）。

## 2. 封印の前に、封印係が確かめること

次のどれか一つでも満たさなければ、封印しない。確かめた結果は、封印の記録に入れる。

1. **オーナーの承認を、記録と機械的に照らすこと**：`docs/stats/tags-naive.md` 0章の A（入れる規則を順番1で封印する変更）について、オーナーの承認の発言が reviews/ に記録され、commit されていること。照らし方は、6 の出どころの確認と同じ形にする。
   - 封印の記録に、承認の出どころを「承認を記録した commit の40桁の ID:reviews/ のファイル名」と「見出しの行から `## ` を除いた全体」で入れる。
   - その commit の版を `git show` で読み、行の全体が一致する見出しがちょうど一つあり、その節に、承認の発言の原文（`>` で始まる行）があることを確かめる。原文の行も封印の記録に写す。
   - 0章の B（数え方の候補の一覧）の判断も同じ形で記録する。B の判断が出ていなくても順番1は封印できるが、その場合は「B は判断待ち」と記録に書く。
2. **区分表の取得と method-access がまだ無いこと**：次のすべてを、封印する時点の作業ツリーと履歴で確かめる。
   - 区分表の取得は ledger に acquisition-start を書かない。収集係の `src/collector/themes.py` は、取得の試行と結果を `data/manifest/gdelt-themes.jsonl` に書く（試行の行の `kind` は `attempt`、結果の行は `result`。行の中の `code_path` は `src/collector/themes.py`）。このファイルが作業ツリーに無いこと、または行が一つも無いこと。さらに `git log --all --oneline -- data/manifest/gdelt-themes.jsonl` の出力が空であること（一度でもコミットされていれば、取得を試みたことになる）。
   - `sealed/ledger.jsonl` に、`kind` が `method-access` の記録が一件も無いこと。
   - GKG（手法を作る期間の報道量）の取得も、まだ無いこと。収集係の GKG の取得は、取得の記録を `data/manifest/gdelt-gkg-method.jsonl`（正式の取得）と `data/manifest/gdelt-gkg-trial.jsonl`（試しの run）に書く。この二つのファイルが作業ツリーに無いこと、または行が一つも無いこと。さらに `git log --all --oneline -- data/manifest/gdelt-gkg-method.jsonl data/manifest/gdelt-gkg-trial.jsonl` の出力が空であること。method-access の記録が無いことだけでは、試しの run の取得を見落とすため、マニフェストも直接確かめる。
   - `sealed/ledger.jsonl` の `acquisition-start` の記録の `fetch.code_path`（記録の最上位の `fetch` の中の `code_path`）が、`src/collector/acquire_filelist.py` 以外のものが無いこと。
   - 統計係が 2026-10-08 に確かめた時点では、ledger は4件（periods、candidates、acquisition-start（`fetch.code_path` は `src/collector/acquire_filelist.py`）、acquisition-result）で、`data/manifest/` には `gdelt-filelist.jsonl` だけがあり、`gdelt-themes.jsonl`・`gdelt-gkg-method.jsonl`・`gdelt-gkg-trial.jsonl` の履歴は無かった（2026-10-08、差し戻し3回目の時点でも同じ）。封印係は、封印する時点で自分で確かめ直すこと。
3. **作業ツリーがきれいなこと**：封印する時点で `git status --porcelain` の出力が空であること。追跡していないファイルや、コミットしていない変更（ほかの係のものを含む）があれば封印しない。
4. **commit ID と祖先と Python の版を記録に入れること**：
   - 封印の記録に、封印した時点の HEAD の commit ID を40桁で入れる（`git rev-parse HEAD`。短い ID は使わない）。
   - その commit の祖先に、次の二つの commit があることを確かめる：`git merge-base --is-ancestor 1cb463acfcf15ba315e6c454625ad681e86bbc2a HEAD` と `git merge-base --is-ancestor 2d23cdf6e01de5129fc7b0a5d85e89bf02e892c6 HEAD` が、どちらも0で終わること。短い ID の `1cb463a`・`2d23cdf` がこの40桁の ID を指すことも、`git rev-parse` で確かめる。
   - 出力を作るのに使った Python の版（`python3 --version` の出力）を入れる。出力の JSON は Python の版で変わらないはずだが、第三者が同じ版で計算し直せるようにするため。
5. **浅い clone では確かめないこと**：`git rev-parse --is-shallow-repository` が `false` であること。浅い clone では `git show 1cb463a:…` と `git show 2d23cdf:…` が取れず、テストと照合ができない。第三者向けの検証の手順にも、履歴をすべて取る clone が要ると書く（封印係の docs/verify/ への提案）。
6. **sha256 を自分で計算し直すこと**：上の表の値を写さず、封印係のコードで、1章のバイト列の定義どおりに計算し直す。表の値と一つでも違えば封印しない（その場合は統計係に差し戻す）。封印の記録には、10件の対象の名前と sha256 をすべて入れる。
7. **出どころの確認は 2d23cdf の版で行うこと**：除外の規則の出力の `owner_choice_source` は `"2d23cdf:reviews/T-020.md 2026-10-08 オーナーの発言（原文のまま記録）"` である。これを、作業中の reviews/T-020.md ではなく、`git show 2d23cdf:reviews/T-020.md` の中身で確かめる。行の全体が `## 2026-10-08 オーナーの発言（原文のまま記録）` に一致する見出しがちょうど一つあり、その節に次の三行があること。
   - `> 病名は案B`
   - `> 民族、宗教の集団は除外の区分に加える。`
   - `> そのほかこのまま承認の項目は承認します`
8. **"undecided" の封印を拒むこと**：除外の規則の出力の JSON の `optional_choice_status` が `"decided"` であること。`"undecided"` なら封印しない（`tagrules.py` の出力の中の `exclusion` の欄も同じ）。
9. **テストが通ること**：封印する commit で `PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest discover -s tests/stats` がすべて通ること。この中の `test_sealed_tests_read_only_targets` と `test_sealed_tests_source` が、封印する二つのテストが対象の外を読まないことを確かめる（限界は tags-naive.md 5章 (1) のあと）。`test_doc_is_frozen` が、tags-naive.md が `test_tagrules.py` の定数と同じであることを確かめる。

**記録の種類（kind）と収集係の関門について（提案。src/collector と src/sealer は統計係の範囲の外）**
- 収集係の関門（`src/collector/themes.py` の `require_exclusion_rules_sealed`。GKG の取得も同じ関門を使う）は、今は、決まった kind の記録が ledger に1件以上あることだけを確かめ、記録の中身（どの規則を封印したか）を照らさない（themes.py の0章「確かめないこと」）。そのため、`tagrules.py` を含まない記録や、別の版の sha256 の記録でも、関門を通れる。
- 収集係の関門は、その kind の記録の中身が、この表の10件の対象の名前と sha256 と一致すること（少なくとも `src/stats/exclusion.py`、`src/stats/tagrules.py` とそれぞれの出力が入っていること）を照らすべきである。どう照らすか（表をコードに写すか、記録の対象を読むか）と kind の名前は、封印係と収集係が決める。統計係はリードに提案として伝える。

## 3. 封印のあと

### (1) 順番1の記録と作業ツリーの10件を照らす手順
順番1の記録ができたあと、凍結を確かめるのは、封印していないこの表やテスト（`test_seal_targets`）ではなく、ledger の記録である。次の手順で照らす。封印係の検証（docs/verify/）と、統計係・監査係が順番2以降の作業を始める前に、毎回行うことを提案する。

1. `sealed/ledger.jsonl` の鎖と、すべての seq の .ots を、封印係の検証の手順で確かめる（`src/sealer/verify.py`）。
2. 順番1の記録（kind は封印係が決める）がちょうど一件あることを確かめ、その記録から、10件の対象の名前と sha256、封印した commit の40桁の ID を読む（2章の項目4・6で記録に入れたもの）。
3. 作業ツリーで、10件の sha256 を計算し直す。`PYTHONDONTWRITEBYTECODE=1 python3 -B src/stats/order1_digests.py` が `{対象の名前: sha256}` の JSON を出す。封印係と第三者は、このスクリプトを使わずに1章のバイト列の定義から計算してもよい（同じ値になる。テスト `test_digest_script_agrees`）。
4. 3 の10件が、2 の記録の10件と名前も値もすべて一致することを確かめる。一件でも違えば、凍結が破られたか、封印したものと違うコードやテストが作業ツリーにある。その場合は作業を止め、リードに報告する。
   - とくに `tests/stats/test_tagrules.py` の sha256 が一致すれば、その中の定数 `TAGS_NAIVE_SHA256` は封印したときの値である。そのうえで `test_doc_is_frozen` が通れば、`docs/stats/tags-naive.md` は封印したときと同じである。表（この文書）と `test_t019.py` は封印していないので、照合の根拠にしない。
5. 2 の commit が、今の HEAD の祖先であることを確かめる（`git merge-base --is-ancestor <40桁の ID> HEAD`）。
6. 封印したテストを流す：`PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest tests/stats/test_exclusion.py tests/stats/test_tagrules.py` がすべて通ること。

順番1の封印のあとで、規則やテストを直す必要が出た場合は、作業ツリーのファイルを直す前に、新しい版として扱う（tags-naive.md 2章 (6)、5章 (2)）。この表は直さず、新しい版の表を別の文書に作る。

### (2) 順番3と順番5の記録
- 順番3（数え方とのつながり）の記録には、この順番1の記録の seq と sha256 を参照として入れる。入れる規則の定数と式は、順番3で足したり変えたりしない（`docs/stats/tags-naive.md` 5章）。
- 順番5（タグの一覧の結果）の記録には、順番1と順番3の記録の seq と sha256 を参照として入れる。順番5を始める前に、(1) の照合を行う。

## 4. 引用
Data: The GDELT Project (https://www.gdeltproject.org/). This project is not affiliated with or endorsed by the GDELT Project.
データ出典：GDELT Project（https://www.gdeltproject.org/）。本プロジェクトは GDELT Project と提携・承認の関係にありません。
（この文書は GDELT のデータを使っていないが、規則は GDELT のデータに適用するため付ける。）
