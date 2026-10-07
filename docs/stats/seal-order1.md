# 順番1の封印：封印係への申し送り（T-022）

封印の順番と、その理由は `docs/stats/tags-naive.md` 5章にある。この文書は、順番1（除外の規則と入れる規則）を封印するときに、封印係が確かめることと、封印の対象の sha256 をまとめたものである。

- 統計係は封印しない。記録の種類（kind）の名前と照合の仕組みは、封印係が決める。
- この文書は順番1の封印の対象ではない。対象の sha256 を書くための申し送りで、対象のどのテストもこの文書を読まない。

## 1. 封印の対象と sha256

表は、統計係がこのコミットの作業ツリーから計算した値である。テスト `test_seal_targets`（`tests/stats/test_t019.py`）が、今のファイルと git の履歴から計算し直して照合する。

<!-- table:seal-targets -->
| 対象 | sha256 |
|---|---|
| `src/stats/exclusion.py` | `22bc0ed138a42b95c36797bbe5b41163c871af14f32be590dafde20fe16fdd1d` |
| `src/stats/exclusion.py の出力` | `681cf5bb698e72097ee17b3516c96d89c69ae70e862122616e678e0b0a5363b8` |
| `tests/stats/test_exclusion.py` | `d3ebd3e7938e3b04a158c633f3dea76020d54d2bc970e9eea68075358670e85d` |
| `src/stats/tagrules.py` | `63b0e005ce85344675651264b4a14453a167a28d56d3333a7503b55db04218ee` |
| `src/stats/tagrules.py の出力` | `c3a4480b1cb2f034f1598dcee5f6c85bf52e92e94d7b06cc52ccaa4889737b39` |
| `tests/stats/test_tagrules.py` | `b2ce6b22d4fd8f8bc72dcbc9c85c848268e56c10e186c36f2d6bb207d2f0e9dd` |
| `docs/stats/tags-naive.md` | `65f822fe48b7c37cb885fe933bc7b1db0cc21c72cf99eb262bdf47122ab0feae` |
| `1cb463a:src/stats/tagrules.py` | `f7c325cb21bcf39c42e6d785deacbe47eacec7fb2834d2927634e446b62ce57a` |
| `1cb463a:src/stats/tagrules.py の出力` | `98926edbbbc7ac0375aee97aa7be0b1a5e3fcf3bc4acbadfa99f5d17362f7b8a` |
| `2d23cdf:reviews/T-020.md` | `0b80ec29a994e04224900b3aafbc56a78d5cd9d4cee6e8d3df6c82a211cf46e7` |

- ファイルの sha256 は、ファイルのバイト列そのもの。
- 「の出力」は、プロジェクトのルートで `PYTHONDONTWRITEBYTECODE=1 python3 -B src/stats/exclusion.py`（`tagrules.py` も同じ）を引数なしで実行した標準出力のバイト列。
- `1cb463a:` と `2d23cdf:` で始まるものは、`git show <commit>:<path>` の標準出力のバイト列。1cb463a の版の出力は、そのファイルを一時のディレクトリに取り出して（`git show 1cb463a:src/stats/tagrules.py > tagrules.py`）、同じように引数なしで実行した標準出力のバイト列。
- 統計係が計算したときの Python の版：3.14.2（`.venv/bin/python` と `python3` のどちらも）。

## 2. 封印の前に、封印係が確かめること

次のどれか一つでも満たさなければ、封印しない。確かめた結果は、封印の記録に入れる。

1. **オーナーの承認**：`docs/stats/tags-naive.md` 0章の「承認をお願いすること」（入れる規則を順番1で封印する変更）について、オーナーの承認の発言が reviews/ に記録されていること。
2. **区分表の取得と method-access がまだ無いこと**：`sealed/ledger.jsonl` に、テーマの区分表の取得の記録（`kind` が `acquisition-start` で、`fetch.code_path` が `src/collector/themes.py` のもの）と、`kind` が `method-access` の記録が、一件も無いこと。
   - 統計係が 2026-10-08 にこの文書を書いた時点の ledger は4件で、種類は periods、candidates、acquisition-start（`src/collector/acquire_filelist.py`、GDELT のファイル一覧）、acquisition-result だった。封印係は、封印する時点の ledger で自分で確かめ直すこと。
3. **作業ツリーがきれいなこと**：封印する時点で `git status --porcelain` の出力が空であること。追跡していないファイルや、コミットしていない変更があれば封印しない。
4. **commit ID と Python の版を記録に入れること**：封印の記録に、封印した時点の HEAD の commit ID（40桁）と、出力を作るのに使った Python の版（`python3 --version` の出力）を入れる。出力の JSON は Python の版で変わらないはずだが、第三者が同じ版で計算し直せるようにするため。
5. **sha256 を自分で計算し直すこと**：上の表の値を写さず、封印係のコードで、1章のバイト列の定義どおりに計算し直す。表の値と一つでも違えば封印しない（その場合は統計係に差し戻す）。
6. **出どころの確認は 2d23cdf の版で行うこと**：除外の規則の出力の `owner_choice_source` は `"2d23cdf:reviews/T-020.md 2026-10-08 オーナーの発言（原文のまま記録）"` である。これを、作業中の reviews/T-020.md ではなく、`git show 2d23cdf:reviews/T-020.md` の中身で確かめる。行の全体が `## 2026-10-08 オーナーの発言（原文のまま記録）` に一致する見出しがちょうど一つあり、その節に次の三行があること。
   - `> 病名は案B`
   - `> 民族、宗教の集団は除外の区分に加える。`
   - `> そのほかこのまま承認の項目は承認します`
7. **"undecided" の封印を拒むこと**：除外の規則の出力の JSON の `optional_choice_status` が `"decided"` であること。`"undecided"` なら封印しない（`tagrules.py` の出力の中の `exclusion` の欄も同じ）。
8. **テストが通ること**：封印する commit で `PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest discover -s tests/stats` がすべて通ること。

## 3. 封印のあと

- 順番3（数え方とのつながり）の記録には、この順番1の記録の seq と sha256 を参照として入れる。入れる規則の定数と式は、順番3で足したり変えたりしない（`docs/stats/tags-naive.md` 5章）。
- 順番5（タグの一覧の結果）の記録には、順番1と順番3の記録の seq と sha256 を参照として入れる。

## 4. 引用
Data: The GDELT Project (https://www.gdeltproject.org/). This project is not affiliated with or endorsed by the GDELT Project.
データ出典：GDELT Project（https://www.gdeltproject.org/）。本プロジェクトは GDELT Project と提携・承認の関係にありません。
（この文書は GDELT のデータを使っていないが、規則は GDELT のデータに適用するため付ける。）
