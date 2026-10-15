#!/usr/bin/env python3
"""順番5（タグの一覧の結果。docs/stats/order5-tag-list.md）の試みと記録を書く入口（kind: stats-order5-attempt と
stats-order5）。T-111。手順は docs/verify/periods-seal.md 19章。

使い方（プロジェクトのルートで。ots の通信を使うので .venv の python で実行する。root はこのファイルの場所から決まる）
    PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -B src/sealer/seal_order5.py \\
        --store <正式な run の日の集計の置き場所> --themes-store <区分表のファイルの置き場所> \\
        --outside-dir <Git の外の detail・extra を置くフォルダ（あって、空の新しいフォルダを中に作る）>
    PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -B src/sealer/seal_order5.py --commit-written

順番5は手で流さない（order5-tag-list.md 4章 (1)）。この入口の中でだけ流し、書いてコミットするまで結果を表示しない。

1回の実行は、次の順で進む。
  0. 記録の鎖とすべての .ots を検証する。作業ツリーがきれいで、HEAD（A）が決まる。
  1. 書く前の確かめ（どれも結果に依らない。止まれば何も書かない）：位置（順番4のあと、threshold-access の前、順番5の記録が
     まだ無い。ledger.check_order5_position）、参照（ledger.order5_refs）、封印済みのコードの値（ledger.order5_sealed_code）、
     HEAD の版から作った code（verify.order5_code）、置き場所がフォルダであること、Git の外のフォルダがプロジェクトと Git の外に
     あること。
  2. **試みの記録を書いてコミットする**（.ots も作る。HEAD は B になる）。流した回数は、試みの記録の数で数える
     （T-110 の監査 中-1 の申し送り）。
  3. HEAD（B）の版のファイルを空のフォルダに取り出し、その中の order5.py を -I・-B・空の pycache_prefix の Python で流す
     （verify.run_order5。--store・--themes-store・--out-dir・--repo）。--out-dir は Git の外のフォルダの中に新しく作る
     order5-seq<試みの seq>。終了コード 0（できた）か 3（C7 で止まった。main だけ）のほかは止まる（試みは記録に残る）。
  4. main のバイト列が決まった形の JSON であること（ledger.order5_main_bytes）。HEAD と作業ツリーが B のままであること。
  5. 順番5の記録を書く。書く前の照合（seal_records.check_new）は、order5.py に頼らずに日の集計と区分表から計算し直して main
     と照らし（verify.recompute_order5。2〜4時間）、Git の外の detail・extra の sha256 を照らす。中身のファイルは追記のあとで
     書く。recorded_at は追記の直前に取る（T-112）。.ots を作り、パス指定でコミットする。
  6. 結果（status と一覧の件数）は、コミットのあとで画面に出す。書いたあとで止まったときは Order5Written で知らせる。

ネットワークは ots の stamp だけ。
"""

import argparse
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import ledger  # noqa: E402
import seal_order2  # noqa: E402
import seal_records  # noqa: E402
import stamp  # noqa: E402
import verify  # noqa: E402

ATTEMPT_MESSAGE = "順番5の試みの記録（stats-order5-attempt。src/sealer/seal_order5.py が書いてコミットした）"
ORDER5_MESSAGE = "順番5の記録（stats-order5。src/sealer/seal_order5.py が書いてコミットした）"
MESSAGES = {ledger.ORDER5_ATTEMPT_KIND: ATTEMPT_MESSAGE, ledger.ORDER5_KIND: ORDER5_MESSAGE}


class Order5Written(ledger.LedgerError):
    """記録（試み、または試みと順番5の記録）は書いたが、そのあとの段で止まった。「何も書いていない」とは表示しない。"""


def _dir(path, what):
    if not path or not os.path.isdir(path):
        raise ledger.LedgerError("%s %s がフォルダでない。書かない" % (what, path))
    return os.path.realpath(path)


def check_outside(root, path):
    """Git の外のフォルダ：あって、プロジェクトの外で、どの Git の作業ツリーと .git の中でもないこと。"""
    real = _dir(path, "Git の外のフォルダ")
    rr = os.path.realpath(root)
    if real == rr or real.startswith(rr + os.sep):
        raise ledger.LedgerError("Git の外のフォルダ %s がプロジェクトの中にある。書かない" % path)
    r = subprocess.run(["git", "-C", real, "rev-parse", "--is-inside-work-tree", "--is-inside-git-dir"],
                       capture_output=True, env=ledger.fixed_git_env())
    if r.returncode == 0 and b"true" in r.stdout:
        raise ledger.LedgerError("Git の外のフォルダ %s が Git の作業ツリーか .git の中にある。書かない" % path)
    return real


def build_attempt(root, data, records):
    """手順 1。返り値：試みの中身。"""
    repo = verify.Repo(root)
    head = seal_order2.clean_head(repo)
    seq = len(records) + 1
    ledger.check_order5_position(records, {"seq": seq, "kind": ledger.ORDER5_ATTEMPT_KIND})
    read = lambda r, role: ledger.read_target_json(root, r, role)  # noqa: E731
    refs = ledger.order5_refs(records, seq, read)
    sealed = ledger.order5_sealed_code(records, read)
    code = verify.order5_code(repo, head, verify.order4_tree(repo, head), sealed)
    return {"kind": ledger.ORDER5_ATTEMPT_KIND, "ledger_head": ledger.expected_ledger_head(data, seq), "head": head,
            "refs": refs, "code": code, "python": sys.version.split()[0]}


def _write(root, kind, doc, data, records, note, now, ots_cmd, runner, **kw):
    """記録を1件書き、.ots を作り、コミットする（seal_order3._write と同じ扱い）。追記の前で止まれば LedgerError。
    追記のあとで止まれば Order5Written。返り値：(記録, 中身のパス, .ots のパスか None, コミット)。"""
    repo = verify.Repo(root)
    try:
        rec, rel, ots_path = seal_records.write_doc_record(root, kind, doc, data, note, now, ots_cmd, runner=runner, **kw)
    except ledger.LedgerError as e:
        after = ledger.verify_chain(ledger.read_ledger(os.path.join(root, "sealed", "ledger.jsonl")))
        if len(after) <= len(records):
            raise
        last = after[-1]
        if not os.path.isfile(os.path.join(root, last["targets"][0]["path"])):
            raise Order5Written("記録 seq %d（%s）を追記したが、中身を書けなかった（%s）。コミットしていない。消さずにリードに報告する"
                                % (last["seq"], kind, e)) from None
        try:
            c = seal_order2.commit_record(repo, root, last, None, MESSAGES[kind])
        except ledger.LedgerError as e2:
            raise Order5Written("記録 seq %d（%s）と中身を作業ツリーに書いたが、.ots を作れず（%s）、コミットもしていない（%s）。"
                                "消さずに、原因を直してから seal_order5.py --commit-written でコミットし、stamp.py stamp --seq %d"
                                " で .ots を作る" % (last["seq"], kind, e, e2, last["seq"])) from None
        raise Order5Written("記録 seq %d（%s）と中身を書いてコミット %s に入れたが、.ots を作れなかった（%s）。stamp.py stamp "
                            "--seq %d で .ots を作ってコミットする" % (last["seq"], kind, c[:12], e, last["seq"])) from None
    try:
        commit = seal_order2.commit_record(repo, root, rec, ots_path, MESSAGES[kind])
    except ledger.LedgerError as e:
        raise Order5Written("記録 seq %d（%s）・中身・.ots を作業ツリーに書いたが、コミットしていない（%s）。消さずに、原因を"
                            "直してから seal_order5.py --commit-written でコミットする（手順書19章）" % (rec["seq"], kind, e)) from None
    return rec, rel, ots_path, commit


def run_and_build(root, data, records, att_rec, store, themes_store, outside, tmp):
    """手順 3〜4。返り値：(順番5の記録の中身, 出力のフォルダ)。"""
    repo = verify.Repo(root)
    head = seal_order2.clean_head(repo)
    out_dir = os.path.join(outside, "order5-seq%d" % att_rec["seq"])
    os.mkdir(out_dir)                                     # 新しく作る（既にあれば止まる）
    tree = verify.order4_tree(repo, head)
    what = "順番5（HEAD %s の版の %s）" % (head[:12], ledger.ORDER5_SCRIPT)
    try:
        verify.run_order5(tree, store, themes_store, out_dir, root, tmp, what)
    except verify.Unchecked as e:
        raise ledger.LedgerError("order5.py を流せない（%s）" % e) from None
    path = os.path.join(out_dir, ledger.ORDER5_OUT_NAMES["main"])
    with open(path, "rb") as f:
        raw = f.read()
    import json
    try:
        main = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise ledger.LedgerError("%s の出力の main が JSON でない" % ledger.ORDER5_SCRIPT) from None
    if ledger.order5_main_bytes(main) != raw:
        raise ledger.LedgerError("%s の出力の main が、決まった形（sort_keys、区切りに空白なし、末尾に改行1つ）でない"
                                 % ledger.ORDER5_SCRIPT)
    if seal_order2.clean_head(repo) != head:
        raise ledger.LedgerError("流しているあいだに HEAD が変わった。書かない")
    read = lambda r, role: ledger.read_target_json(root, r, role)  # noqa: E731
    seq = len(records) + 1
    adoc = ledger.read_target_json(root, att_rec, ledger.ORDER5_ATTEMPT_KIND)
    code = verify.order5_code(repo, head, tree, ledger.order5_sealed_code(records, read))
    doc = {"kind": ledger.ORDER5_KIND, "ledger_head": ledger.expected_ledger_head(data, seq), "head": head,
           "attempt": ledger.record_ref(att_rec), "refs": ledger.order5_refs(records, seq, read), "code": code,
           "main": main, "main_sha256": ledger.sha256_hex(raw), "status": main.get("status"),
           "outside": main.get("outside"), "python": sys.version.split()[0]}
    if {k: code[k] for k in ("script", "docs", "sealed")} != {k: adoc["code"][k] for k in ("script", "docs", "sealed")}:
        raise ledger.LedgerError("流したコードの版が、試みの記録の版と違う。書かない")
    return doc, out_dir


def seal(store, themes_store, outside_dir, now, ots_cmd, runner=subprocess.run):
    """試みを書いてコミットし、order5.py を流して、順番5の記録を書いてコミットする。
    返り値：{"attempt": (記録, 中身のパス, .ots, 中身, コミット), "order5": 同じ形か None, "out_dir": 出力のフォルダか None}。"""
    root = ledger.check_sealed_inside(ledger.PROJECT_ROOT)
    store, themes_store = _dir(store, "日の集計の置き場所"), _dir(themes_store, "区分表の置き場所")
    outside = check_outside(root, outside_dir)
    data, records = seal_records.load_checked(root, ots_cmd, runner=runner)
    adoc = build_attempt(root, data, records)
    note = ("統計係の順番5の試み（docs/stats/order5-tag-list.md）。stats-order5-attempt の %d 件目。order5.py を流す前に書いた。"
            "採用の区切りには使わない。" % (sum(1 for r in records if r["kind"] == ledger.ORDER5_ATTEMPT_KIND) + 1))
    arec, arel, aots, acommit = _write(root, ledger.ORDER5_ATTEMPT_KIND, adoc, data, records, note, now, ots_cmd, runner)
    out = {"attempt": (arec, arel, aots, adoc, acommit), "order5": None, "out_dir": None}
    try:
        data, records = seal_records.load_checked(root, ots_cmd, runner=runner)
        with tempfile.TemporaryDirectory() as tmp:
            doc, out_dir = run_and_build(root, data, records, arec, store, themes_store, outside, tmp)
        out["out_dir"] = out_dir
        note5 = ("統計係の順番5（タグの一覧の結果。docs/stats/order5-tag-list.md）。試み seq %d、順番4 seq %d。main の sha256 %s。"
                 "採用の区切りには使わない。" % (arec["seq"], doc["refs"]["order4"]["seq"], doc["main_sha256"]))
        o = _write(root, ledger.ORDER5_KIND, doc, data, records, note5, now, ots_cmd, runner, content_after_append=True,
                   order5_inputs={"store": store, "themes_store": themes_store, "outside_dir": out_dir})
    except Order5Written:
        raise
    except (ledger.LedgerError, OSError) as e:
        raise Order5Written("順番5の試みの記録 seq %d は書いてコミット %s に入れたが、順番5の記録は書いていない（%s）。原因を直して"
                            "から、もう一度この入口を流す（新しい試みとして記録される）" % (arec["seq"], acommit[:12], e)) from None
    out["order5"] = (o[0], o[1], o[2], doc, o[3])
    return out


def main(argv=None):
    p = argparse.ArgumentParser(allow_abbrev=False, description=__doc__.splitlines()[0])
    p.add_argument("--store", help="正式な run の日の集計の置き場所")
    p.add_argument("--themes-store", help="区分表のファイルの置き場所")
    p.add_argument("--outside-dir", help="Git の外の detail・extra を置くフォルダ（中に order5-seq<N> を新しく作る）")
    p.add_argument("--ots", default=stamp.DEFAULT_OTS)
    p.add_argument("--commit-written", action="store_true",
                   help="書いたがコミットしていない最後の stats-order5-attempt・stats-order5 の記録をコミットする")
    a = p.parse_args(argv)
    if a.commit_written:
        try:
            c = seal_order2.commit_written(ledger.check_sealed_inside(ledger.PROJECT_ROOT),
                                           (ledger.ORDER5_ATTEMPT_KIND, ledger.ORDER5_KIND), MESSAGES)
        except ledger.LedgerError as e:
            print("失敗（コミットしていない）: %s" % e, file=sys.stderr)
            return 1
        print("コミット: %s" % c)
        return 0
    if not (a.store and a.themes_store and a.outside_dir):
        p.error("--store・--themes-store・--outside-dir が要る")
    try:
        # T-112：recorded_at は、記録ごとに追記の直前に取る（now に None を渡す）
        out = seal(a.store, a.themes_store, a.outside_dir, None, a.ots)
    except Order5Written as e:
        print("止まった（順番5の試みの記録は書いた）: %s" % e, file=sys.stderr)
        return 1
    except ledger.LedgerError as e:
        print("失敗（順番5の記録は書いていない）: %s" % e, file=sys.stderr)
        return 1
    rec, rel, ots_path, _doc, commit = out["attempt"]
    print(ledger.canonical_line(rec).decode("utf-8"))
    print("試み：コミット %s" % commit)
    rec5, rel5, ots5, doc5, c5 = out["order5"]
    print(ledger.canonical_line(rec5).decode("utf-8"))
    print("順番5：status %s、main の sha256 %s、正式な一覧 %s 件、Git の外のファイル：%s"
          % (doc5["status"], doc5["main_sha256"],
             ((doc5["main"].get("official") or {}).get("result") or {}).get("tag_count", "—"), out["out_dir"]))
    print("コミット: %s（記録・中身・.ots。結果は、このコミットのあとで表示している）" % c5)
    return 0


if __name__ == "__main__":
    sys.exit(main())
