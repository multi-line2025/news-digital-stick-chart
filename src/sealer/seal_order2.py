#!/usr/bin/env python3
"""順番2（統計係の docs/stats/counting.md 4章、docs/stats/seal-order1.md 3章 (2)）の試みを、1回ごとに ledger に
記録する入口（kind: stats-order2）。T-078。手順は docs/verify/periods-seal.md 16章。

使い方（プロジェクトのルートで。ots の通信を使うので .venv の python で実行する。root はこのファイルの場所から決まり、
引数では変えられない。order2_gate.py と同じ）
    PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -B src/sealer/seal_order2.py \\
        --trial-store <試しの run の日の集計の置き場所> [--official-store <正式な run の日の集計の置き場所>] \\
        --bundle-out <プロジェクトと Git の外の、まだ無いファイルのパス>

1回の実行は、次の順で進む。途中で止まったら、それより後のことはしない。
  0. 記録の鎖とすべての .ots を検証する（seal_records.load_checked）。作業ツリーがきれい（git status --porcelain が空）で、
     HEAD が決まる。
  1. 関門（order2_gate.gate_with_manifests → ledger.require_order2_gate）。閉じていれば、何も書かずに止まる（待つ形も
     ここで閉じる。手順書14章）。開けば、記録に入れる trial_result・input_run・gkg_run_result と、git の確かめに通った
     HEAD の版のマニフェストのバイト列が決まる。input_run の mode の置き場所が引数に無ければ、何も書かずに止まる。
     input_run の run の3日のファイルが置き場所にあることを、開かずに isfile で確かめる（無ければ何も書かない。
     差し戻し1回目 中-2）。
  2. 参照する順番1b の記録：この記録より前の stats-order1b の seq の最大（counting.expected_ref_1b と同じ決め方）。
  3. 時機の条件（(a)）：verify.order2_timing_now（graft・浅い clone・refs/replace/ の確かめ、for-each-ref、worktree の
     一覧、F の集合と親、ledger の条件）。確かめた内容を timing_check と timing_guards に組で入れる。続けて
     git bundle create --all を --bundle-out に作り、list-heads が記録した refs と worktree の HEAD と合うことを確かめる
     （合わなければ何も書かない）。sha256 を bundle に入れる。
  4. コードの版：参照する順番1b の記録が縛る src/stats/counting.py の sha256 の版を、git の履歴から探す
     （verify.find_order2_code。作業ツリーの counting.py は使わない）。
  5. 行き先：(a) を満たさなければ stop_kind "a"。満たし、版が履歴に無ければ "c"。どちらでもなければ、見つかった版の
     counting.py だけを置いた空のフォルダで、-I・-B の Python で decide() を流す（verify.run_order2_decide。
     `counting.py apply`）。stopped なら "b"、decided（と pending）なら null。日の集計を開くのは、この decide() だけ。
  6. HEAD と作業ツリーがはじめと同じことを確かめ直し、seal_records.write_doc_record で書く（書く前の照合：
     ledger.check_order2_run・check_order2_doc・check_order2_plan と verify.check_order2_git。どれかに通らなければ
     何も書かない。記録の行と中身に privacy_scan と同じ検査もかける。差し戻し1回目 中-3）。そのあと、その seq の .ots を作る。
  7. 書いた記録・中身・.ots だけをパス指定で add し、続けてコミットする（作成者とコミッタは noreply の1件、追記行なし。
     差し戻し1回目 中-2）。結果は、コミットのあとで画面に出す。

(a)・(b)・(c) と決まった記録は、どれも書く。待つ（decide() が pending）は、関門が開いたあとでは起きない（関門は R の
gkg-run-result を求め、gkg-run-result は R の run-complete を求めるので、decide() は試しの run の段に進む）。そのため、
待った試みは記録に残らない（手順書14章・16章の限界）。

ネットワークは ots の stamp だけ。drand は使わない。
"""

import argparse
import datetime
import hashlib
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import ledger  # noqa: E402
import order2_gate  # noqa: E402
import seal_records  # noqa: E402
import stamp  # noqa: E402
import verify  # noqa: E402

privacy_scan = seal_records.load_privacy_scan()   # 収集係の検査器（読むだけ）。コミットの作成者のアドレスの許可の一覧に使う

# コミットの作成者とコミッタ（CLAUDE.md「作成者と個人情報」）。アドレスは privacy_scan の許可の一覧の1件から取る
AUTHOR_NAME = "Multi-line"
COMMIT_MESSAGE = "順番2の試みの記録（stats-order2。src/sealer/seal_order2.py が書いてコミットした）"

BUNDLE_REASON = ("書いた時点では公開していない。公開は、手順書16章の公開の前の検査（個人情報と、置けるデータの制限）に"
                 "通ったときだけ、このバイト列のまま行う")


def _git(repo, *args):
    return verify._rgit(repo, *args)


def clean_head(repo):
    """作業ツリーがきれい（git status --porcelain が空。追跡していないファイルも含む）で、HEAD の 40 桁を返す。"""
    if _git(repo, "status", "--porcelain").strip():
        raise ledger.LedgerError("作業ツリーがきれいでない（git status --porcelain が空でない）。書かない")
    head = _git(repo, "rev-parse", "--verify", "HEAD^{commit}").decode().strip()
    if not ledger.HEX40.match(head):
        raise ledger.LedgerError("HEAD の commit ID が 40 桁の16進でない。書かない")
    return head


def check_stores(stores, run):
    """置き場所の引数を確かめる。input_run の mode の置き場所は必ず要る（無ければ書かない）。ほかの mode は decide() が
    読まないので、無くてよい。置き場所は、あるフォルダの絶対パスにする。中のファイルは開かない。"""
    out = {}
    for mode, path in stores.items():
        if path is None:
            out[mode] = None
            continue
        if not os.path.isdir(path):
            raise ledger.LedgerError("%s の置き場所 %s がフォルダでない。書かない" % (mode, path))
        out[mode] = os.path.realpath(path)
    if run is not None and out.get(run["mode"]) is None:
        raise ledger.LedgerError("decide() が %s の run（run_id %s）の段に進む形なのに、その置き場所が引数に無い"
                                 "（--%s-store）。書かない" % (run["mode"], run["run_id"], run["mode"]))
    return out


def check_day_files_present(stores, run):
    """decide() の前に、input_run の run の3日のファイル（gkg-<mode>-<run_id>-day-<YYYYMMDD>.tsv.gz）が置き場所にあることを、
    開かずに os.path.isfile で確かめる（T-078 差し戻し1回目 中-2）。無ければ何も書かずに止まる。空の置き場所や違う置き場所を
    渡して (b) を作ることを、これで止める（ファイルの中身が違う・壊れているときは、decide() が (b) で止まる）。"""
    if run is None:
        return
    missing = []
    for d in ledger.ORDER2_TRIAL_DAYS:
        name = "gkg-%s-%s-day-%s.tsv.gz" % (run["mode"], run["run_id"], d.replace("-", ""))
        if not os.path.isfile(os.path.join(stores[run["mode"]], name)):
            missing.append(name)
    if missing:
        raise ledger.LedgerError("%s の置き場所に、日の集計 %s が無い。置き場所を確かめる。書かない"
                                 % (run["mode"], "、".join(missing)))


def author_args():
    allowed = sorted(privacy_scan.ALLOWED_ADDRESSES)
    if len(allowed) != 1:
        raise ledger.LedgerError("作成者のアドレスが1件に決まらない。コミットしない")
    return ["-c", "user.name=" + AUTHOR_NAME, "-c", "user.email=" + allowed[0]]


def commit_record(repo, root, rec, ots_path):
    """書いた記録・中身・.ots（あれば）だけを、パスを指定して add し、続けてコミットする（作成者とコミッタは noreply の1件、
    追記行なし）。T-078 差し戻し1回目 中-2：書いたあとにコミットを待つ間を作らない。返り値: コミットの 40 桁。"""
    paths = ["sealed/ledger.jsonl"] + [t["path"] for t in rec["targets"]]
    if ots_path is not None:
        paths.append(os.path.relpath(ots_path, root).replace(os.sep, "/"))
    _git(repo, "add", "--", *paths)
    staged = set(_git(repo, "diff", "--cached", "--name-only").decode("utf-8").split())
    if staged != set(paths):
        raise ledger.LedgerError("コミットに入るファイル（%s）が、書いたものと違う。コミットしない" % "、".join(sorted(staged)))
    _git(repo, *(author_args() + ["commit", "-q", "-m", COMMIT_MESSAGE]))
    return _git(repo, "rev-parse", "HEAD").decode().strip()


def _outside(root, path):
    """path（まだ無いファイル）が、プロジェクトの外で、どの Git の作業ツリーと .git の中でもないこと。"""
    parent = os.path.dirname(os.path.abspath(path))
    if not os.path.isdir(parent):
        raise ledger.LedgerError("bundle を置くフォルダ %s が無い。書かない" % parent)
    rp, rr = os.path.realpath(parent), os.path.realpath(root)
    if rp == rr or rp.startswith(rr + os.sep):
        raise ledger.LedgerError("bundle をプロジェクトの中（%s）に置こうとしている。プロジェクトと Git の外に置く。書かない" % path)
    r = subprocess.run(["git", "-C", parent, "rev-parse", "--is-inside-work-tree", "--is-inside-git-dir"],
                       capture_output=True, env=ledger.fixed_git_env())
    if r.returncode == 0 and b"true" in r.stdout:
        raise ledger.LedgerError("bundle を Git の作業ツリーか .git の中（%s）に置こうとしている。Git の外に置く。書かない" % path)


def make_bundle(repo, root, path, tc):
    """git bundle create <path> --all を作り、list-heads が timing_check の refs・worktree_heads と合うことを確かめる
    （seal-order1.md 3章 (3) の 177・178行と同じ形）。返り値: 記録の bundle の欄。合わなければ LedgerError（何も書かない。
    作った bundle のファイルは消さずに残す）。"""
    path = os.path.abspath(path)
    if os.path.lexists(path):
        raise ledger.LedgerError("bundle のパス %s が既にある。上書きしない。書かない" % path)
    _outside(root, path)
    _git(repo, "bundle", "create", "-q", path, "--all")
    heads = []
    for line in _git(repo, "bundle", "list-heads", path).decode("utf-8").splitlines():
        sha, _sp, name = line.partition(" ")
        heads.append((name, sha))
    recorded = {(r["ref"], r["commit"]) for r in tc["refs"]}
    listed_refs = {(n, c) for n, c in heads if n.startswith("refs/")}
    wt = {c for n, c in heads if n == "HEAD" or (n.startswith("worktrees/") and n.endswith("/HEAD"))}
    if not recorded <= set(heads) or not listed_refs <= recorded or wt != set(tc["worktree_heads"]):
        raise ledger.LedgerError("bundle（%s）の list-heads が、記録する refs・worktree の HEAD と合わない（確かめてから bundle を"
                                 "作るまでに参照が変わった）。書かない（bundle のファイルは残してある）" % path)
    with open(path, "rb") as f:
        sha = hashlib.sha256(f.read()).hexdigest()
    return {"sha256": sha, "published": False, "reason": BUNDLE_REASON}


def build_doc(root, data, records, stores, bundle_out):
    """手順 1〜5。返り値: 書く中身。"""
    repo = verify.Repo(root)
    head = clean_head(repo)
    got, trial, official = order2_gate.gate_with_manifests()              # 1. 関門
    run = got["input_run"]
    stores = check_stores(stores, run)
    check_day_files_present(stores, run)
    seq = len(records) + 1
    ref = ledger.order2_ref_1b(records, seq)                                # 2. 参照する順番1b
    if ref is None:
        raise ledger.LedgerError("stats-order1b（順番1b）の記録が無い。書かない")
    d1b = ledger.read_target_json(root, ref, ledger.ORDER1B_KIND)
    code_sha = {f["path"]: f["sha256"] for f in d1b["files"]}[ledger.COUNTING_SCRIPT]
    tc, guards = verify.order2_timing_now(repo, records, ref)              # 3. 時機の条件
    bundle = make_bundle(repo, root, bundle_out, tc)
    commit, code = verify.find_order2_code(repo, head, d1b)               # 4. コードの版（git の履歴から）
    out = None
    if not tc["ok"]:                                                        # 5. 行き先
        stop_kind = "a"
    elif commit is None:
        stop_kind = "c"
    else:
        with tempfile.TemporaryDirectory() as tmp:
            empty = tempfile.mkdtemp(prefix="empty-store-", dir=tmp)
            full = {m: (stores.get(m) or empty) for m in ("trial", "official")}
            out = verify.run_order2_decide(code, code_sha, trial, official, full, tmp, "順番2の decide()")
        stop_kind = "b" if out["status"] == "stopped" else None
    doc = {
        "kind": ledger.ORDER2_KIND,
        "ledger_head": ledger.expected_ledger_head(data, seq),
        "head": head,
        "manifest_sha256": {"trial": ledger.sha256_hex(trial) if trial else None,
                            "official": ledger.sha256_hex(official) if official else None},
        "status": "stopped" if stop_kind is not None else out["status"],
        "stop_kind": stop_kind,
        "trial_result": got["trial_result"],
        "input_run": got["input_run"],
        "gkg_run_result": got["gkg_run_result"],
        "ref_1b_seq": ref["seq"],
        "ref_1b_record_sha256": ledger.sha256_hex(ledger.canonical_line(ref)),
        "timing_check": tc,
        "timing_guards": guards,
        "code": {"path": ledger.COUNTING_SCRIPT, "sha256": code_sha, "found": commit is not None, "commit": commit},
        "bundle": bundle,
        "python": sys.version.split()[0],
    }
    if out is not None:
        doc["counting_output"] = out
    if clean_head(repo) != head:                                            # 6. 書く直前の確かめ直し
        raise ledger.LedgerError("確かめているあいだに HEAD が変わった。書かない")
    return doc


def seal(stores, bundle_out, now, ots_cmd, runner=subprocess.run):
    """順番2の試みを 1 件追記し、続けてコミットする。stores は {"trial": パスか None, "official": パスか None}。
    返り値: (記録, 中身のパス, .ots のパス か None, 中身, コミット)。
    .ots を作れなかったとき（記録は鎖に残る）も、記録と中身をコミットしてから止まる（コミットを待つ間を作らない）。"""
    root = ledger.check_sealed_inside(ledger.PROJECT_ROOT)
    repo = verify.Repo(root)
    data, records = seal_records.load_checked(root, ots_cmd, runner=runner)
    doc = build_doc(root, data, records, stores, bundle_out)
    n = sum(1 for r in records if r["kind"] == ledger.ORDER2_KIND) + 1
    note = ("統計係の順番2の試み（docs/stats/counting.md 4章、docs/stats/seal-order1.md 3章 (2)）。stats-order2 の %d 件目。"
            "status %s、stop_kind %s。参照する順番1b は seq %d。採用の区切りには使わない。"
            % (n, doc["status"], doc["stop_kind"] or "null", doc["ref_1b_seq"]))
    try:
        rec, rel, ots_path = seal_records.write_doc_record(root, ledger.ORDER2_KIND, doc, data, note, now, ots_cmd,
                                                           runner=runner)
    except ledger.LedgerError as e:
        after = ledger.verify_chain(ledger.read_ledger(os.path.join(root, "sealed", "ledger.jsonl")))
        if len(after) > len(records):          # 追記したあと（.ots の段）で止まった：記録と中身だけをコミットする
            c = commit_record(repo, root, after[-1], None)
            raise ledger.LedgerError("%s（記録 seq %d と中身はコミット %s に入れた。stamp.py stamp --seq %d で .ots を作って"
                                     "コミットする）" % (e, after[-1]["seq"], c[:12], after[-1]["seq"])) from None
        raise
    commit = commit_record(repo, root, rec, ots_path)
    return rec, rel, ots_path, doc, commit


def main(argv=None):
    p = argparse.ArgumentParser(allow_abbrev=False, description=__doc__.splitlines()[0])
    p.add_argument("--trial-store", help="試しの run の日の集計の置き場所（decide() が試しの run の段に進むときに要る）")
    p.add_argument("--official-store", help="正式な run の日の集計の置き場所（正式な run の段に進むときに要る）")
    p.add_argument("--bundle-out", required=True, help="git bundle を書くパス（プロジェクトと Git の外。まだ無いもの）")
    p.add_argument("--ots", default=stamp.DEFAULT_OTS)
    a = p.parse_args(argv)
    now = datetime.datetime.now(datetime.timezone.utc)
    try:
        rec, rel, ots_path, doc, commit = seal({"trial": a.trial_store, "official": a.official_store}, a.bundle_out, now,
                                               a.ots)
    except ledger.LedgerError as e:
        print("失敗（順番2の記録は書いていない）: %s" % e, file=sys.stderr)
        return 1
    print(ledger.canonical_line(rec).decode("utf-8"))
    print("中身: %s" % rel)
    print("順番2の試み：status %s、stop_kind %s、参照する順番1b は seq %d、時機の条件 %s、コードの版 %s"
          % (doc["status"], doc["stop_kind"] or "null", doc["ref_1b_seq"], "満たす" if doc["timing_check"]["ok"] else
             "満たさない", "履歴にある" if doc["code"]["found"] else "履歴に無い"))
    print("bundle: sha256 %s（公開していない）" % doc["bundle"]["sha256"])
    print("コミット: %s（記録・中身・.ots。結果は、このコミットのあとで表示している）" % commit)
    if ots_path is not None:
        print("時刻証明: %s" % os.path.relpath(ots_path, ledger.PROJECT_ROOT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
