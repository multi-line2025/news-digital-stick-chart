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
  2. 参照する順番1b の記録：この記録より前の stats-order1b の seq の最大（counting.expected_ref_1b と同じ決め方）。
  3. 時機の条件（(a)）：seal-order1.md 177行の順に行う（T-091）。まず参照を読み（verify.read_refs_now：for-each-ref、
     worktree の一覧、graft・浅い clone）、git bundle create --all を --bundle-out に作り、list-heads が読んだ refs と
     worktree の HEAD と合うことを確かめる（合わなければ何も書かない。F と ok はまだ計算していない）。合ったときだけ、
     読んだ参照から F の集合と親、ledger の条件を計算する（verify.timing_from_refs）。確かめた内容を timing_check と
     timing_guards に組で入れ、sha256 を bundle に入れる。
  4. コードの版：参照する順番1b の記録が縛る src/stats/counting.py の sha256 の版を、git の履歴から探す
     （verify.find_order2_code。作業ツリーの counting.py は使わない）。
  5. 行き先：(a) を満たさなければ stop_kind "a"。満たし、版が履歴に無ければ "c"。どちらでもなければ、見つかった版の
     counting.py だけを置いた空のフォルダで、-I・-B の Python で decide() を流す（verify.run_order2_decide。
     `counting.py apply`）。stopped なら "b"、decided（と pending）なら null。日の集計を開くのは、この decide() だけ。
  6. HEAD と作業ツリーがはじめと同じことを確かめ直し、seal_records.write_doc_record で書く（書く前の照合：
     ledger.check_order2_run・check_order2_doc・check_order2_plan と verify.check_order2_git。どれかに通らなければ
     何も書かない。記録の行と中身に privacy_scan と同じ検査もかける。差し戻し1回目 中-3）。そのあと、その seq の .ots を作る。
  7. 書いた記録・中身・.ots だけをパス指定で index に入れ、続けてコミットする（作成者とコミッタは noreply の1件、追記行なし。
     global・system の設定を読まず、フックと署名を止める。コミットのあとに作成者・本文・ファイルを確かめる。差し戻し1回目
     中-2、差し戻し2回目 中-A）。index にはディスクのバイト列を filter・attributes を通さずに入れ、コミットのあとに、
     コミットしたバイト列がディスクと同じことを確かめる（T-081）。結果は、コミットのあとで画面に出す。書いたあとで止まったときは Order2Written で知らせ、
     「書いていない」とは表示しない（差し戻し2回目 中-B）。

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

# コミットの作成者とコミッタ（CLAUDE.md「作成者と個人情報」の1件）。privacy_scan の許可の一覧とちょうど同じであることを、
# コミットの前に確かめる（T-078 差し戻し2回目 軽-c）
AUTHOR_NAME = "Multi-line"
AUTHOR_EMAIL = "197505900+multi-line2025@users.noreply.github.com"
COMMIT_MESSAGE = "順番2の試みの記録（stats-order2。src/sealer/seal_order2.py が書いてコミットした）"


class Order2Written(ledger.LedgerError):
    """記録は書いた（鎖に追記した）が、そのあとの段（.ots・コミット・コミットの確かめ）で止まった。T-078 差し戻し2回目 中-B。
    「何も書いていない」とは表示しない。"""

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


def commit_env():
    """入口の中のコミットに使う環境（T-078 差し戻し2回目 中-A）。GIT_ で始まる環境変数を決めたものだけにし（ledger.fixed_git_env）、
    global と system の git の設定を読まない（GIT_CONFIG_GLOBAL=/dev/null、GIT_CONFIG_NOSYSTEM=1）。"""
    env = ledger.fixed_git_env()
    env["GIT_CONFIG_GLOBAL"] = os.devnull
    env["GIT_CONFIG_NOSYSTEM"] = "1"
    return env


def author_config():
    """作成者とコミッタを固定し、フックと署名を止める -c の並び。アドレスは定数で持ち、privacy_scan の許可の一覧と
    ちょうど同じであることを確かめる（違えばコミットしない）。"""
    allowed = seal_records.load_privacy_scan().ALLOWED_ADDRESSES
    if set(allowed) != {AUTHOR_EMAIL}:
        raise ledger.LedgerError("作成者のアドレスの定数が、privacy_scan の許可の一覧（%d 件）とちょうど同じでない。コミットしない"
                                 % len(allowed))
    out = []
    for k, v in (("user.name", AUTHOR_NAME), ("user.email", AUTHOR_EMAIL), ("author.name", AUTHOR_NAME),
                 ("author.email", AUTHOR_EMAIL), ("committer.name", AUTHOR_NAME), ("committer.email", AUTHOR_EMAIL),
                 ("core.hooksPath", os.devnull), ("commit.gpgSign", "false")):
        out += ["-c", "%s=%s" % (k, v)]
    return out


def _cgit(root, *args):
    r = subprocess.run(["git", "-C", root] + author_config() + list(args), capture_output=True, env=commit_env())
    if r.returncode != 0:
        raise ledger.LedgerError("git %s が失敗した（%s）" % (" ".join(args[:1]), r.stderr.decode("utf-8", "replace").strip()[:300]))
    return r.stdout


def stage_raw(root, paths):
    """paths を、ディスクのバイト列のまま index に入れる（T-081。T-078 軽-1）。git add を使わず、
    git hash-object -w --no-filters でバイト列をそのまま blob にし、git update-index --cacheinfo で入れる。
    --no-filters なので、filter（clean・process）・.gitattributes・.git/info/attributes・core.attributesFile・
    core.autocrlf・working-tree-encoding のどれも効かない。ファイルは、リンクでない普通のファイルに限る（mode 100644）。"""
    for p in paths:
        full = os.path.join(root, p)
        if os.path.islink(full) or not os.path.isfile(full):
            raise ledger.LedgerError("%s が普通のファイルでない（リンクか、無い）。コミットしない" % p)
        blob = _cgit(root, "hash-object", "-w", "--no-filters", "--", p).decode().strip()
        if not ledger.HEX40.match(blob):
            raise ledger.LedgerError("%s の blob の ID が 40 桁の16進でない。コミットしない" % p)
        _cgit(root, "update-index", "--add", "--cacheinfo", "100644,%s,%s" % (blob, p))


def check_committed_bytes(root, commit, paths):
    """コミットした各ファイルの blob（git cat-file blob <commit>:<path>。filter も textconv も通らない。replace は
    commit_env で切ってある）のバイト列が、ディスクのファイルのバイト列と同じことを確かめる（T-081。T-078 軽-1）。
    違えば LedgerError（push しない）。"""
    bad = []
    for p in paths:
        got = _cgit(root, "cat-file", "blob", "%s:%s" % (commit, p))
        with open(os.path.join(root, p), "rb") as f:
            disk = f.read()
        if got != disk:
            bad.append(p)
    if bad:
        raise ledger.LedgerError("コミット %s に入った %s のバイト列が、ディスクのファイルと違う（filter などで変わった）。"
                                 "このコミットを push しない。リードに報告する" % (commit, "、".join(bad)))


def commit_record(repo, root, rec, ots_path, message=COMMIT_MESSAGE):
    """書いた記録・中身・.ots（あれば）だけを、パスを指定して index に入れ、続けてコミットする。T-078 差し戻し1回目 中-2・
    差し戻し2回目 中-A：global・system の設定を読まず、作成者とコミッタを -c で固定し、フック（core.hooksPath と --no-verify）と
    署名を止める。T-081：index にはディスクのバイト列をそのまま入れ（stage_raw。filter・attributes を効かせない）、コミットの
    あとに、各ファイルのコミットしたバイト列がディスクと同じことを確かめる（check_committed_bytes）。コミットのあとに、
    作成者・コミッタ・本文・入ったファイルも確かめ、決めた値と違えば止める。
    message はコミットの本文（決まった1行。T-090 で順番3の入口も使うので引数にした。既定は順番2の文）。
    返り値: コミットの 40 桁。失敗すれば LedgerError（呼ぶ側が「記録は書いた、コミットしていない」と知らせる）。"""
    paths = ["sealed/ledger.jsonl"] + [t["path"] for t in rec["targets"]]
    if ots_path is not None:
        paths.append(os.path.relpath(ots_path, root).replace(os.sep, "/"))
    stage_raw(root, paths)
    staged = set(_cgit(root, "diff", "--cached", "--name-only").decode("utf-8").split())
    if staged != set(paths):
        raise ledger.LedgerError("コミットに入るファイル（%s）が、書いたもの（%s）と違う。コミットしない"
                                 % ("、".join(sorted(staged)), "、".join(paths)))
    _cgit(root, "commit", "-q", "--no-verify", "--cleanup=verbatim", "-m", message)
    commit = _cgit(root, "rev-parse", "HEAD").decode().strip()
    got = _cgit(root, "log", "-1", "--format=%an%x00%ae%x00%cn%x00%ce%x00%B", commit).decode("utf-8").split("\x00")
    who = [AUTHOR_NAME, AUTHOR_EMAIL, AUTHOR_NAME, AUTHOR_EMAIL]
    files = set(_cgit(root, "show", "--name-only", "--format=", commit).decode("utf-8").split())
    if got[:4] != who or got[4].rstrip("\n") != message or files != set(paths):
        raise ledger.LedgerError("コミット %s の作成者・コミッタ・本文・ファイルが、決めた値と違う（作成者とコミッタは %s、本文は"
                                 "決まった1行で追記行なし、ファイルは書いたものだけ）。このコミットを push しない。リードに報告する"
                                 % (commit, AUTHOR_NAME))
    check_committed_bytes(root, commit, paths)
    return commit


def check_written(root, repo, data, rec, kinds=(ledger.ORDER2_KIND,)):
    """--commit-written でコミットする前に、書いた記録と中身を照らす（T-081。T-078 軽-2）。どれかに通らなければ
    LedgerError（コミットしない）。
      - .ots：最後の seq の .ots があれば、すべての seq の .ots を記録の先頭 N 行と照らす（ledger.check_anchors。
        seal_records.load_checked と同じ）。無ければ（.ots を作れなかった形）、seq 1〜N−1 の .ots を先頭 N−1 行と照らす。
      - 鎖：HEAD の版の sealed/ledger.jsonl が、今の記録から最後の1行を除いたものとバイト列で同じ（コミットしていないのは
        最後の1件だけ）。
      - 中身：targets がちょうど1つで、そのファイルの sha256 が記録の値と同じ（ledger.read_target_json）。中身の kind、
        ledger_head、head が今の HEAD、順番1・1b・2 の形（ledger.check_stats_order）、privacy_scan と同じ検査。
    kinds：最後の記録の kind として受け付けるもの（T-090 で順番3の入口も使うので引数にした。既定は stats-order2 だけ）。"""
    sealed = os.path.join(root, "sealed")
    lines = ledger.split_lines(data)
    prefix = b"".join(x + b"\n" for x in lines[:-1])
    if os.path.isfile(os.path.join(sealed, ledger.ots_name(rec["seq"]))):
        seal_records.load_checked(root, None)
    else:
        ledger.check_anchors(prefix, sealed)
    head = _git(repo, "rev-parse", "--verify", "HEAD^{commit}").decode().strip()
    r = subprocess.run(["git", "-C", root, "cat-file", "blob", "HEAD:sealed/ledger.jsonl"], capture_output=True,
                       env=ledger.fixed_git_env())
    if r.returncode != 0 or r.stdout != prefix:
        raise ledger.LedgerError("HEAD の版の sealed/ledger.jsonl が、今の記録から最後の seq %d を除いたものと同じでない"
                                 "（コミットしていない記録が最後の1件だけでない）。コミットしない" % rec["seq"])
    if len(rec["targets"]) != 1:
        raise ledger.LedgerError("seq %d の targets がちょうど1つでない。コミットしない" % rec["seq"])
    if rec["kind"] not in kinds:
        raise ledger.LedgerError("seq %d の kind が %s でない。コミットしない" % (rec["seq"], "・".join(kinds)))
    doc = ledger.read_target_json(root, rec, rec["kind"])
    if not isinstance(doc, dict) or doc.get("kind") != rec["kind"]:
        raise ledger.LedgerError("seq %d の中身の kind が %s でない。コミットしない" % (rec["seq"], rec["kind"]))
    ledger.check_ledger_head(data, rec, doc)
    if doc.get("head") != head:
        raise ledger.LedgerError("seq %d の中身の head が、今の HEAD と違う。コミットしない" % rec["seq"])
    ledger.check_stats_order(ledger.verify_chain(data), lambda x, role: ledger.read_target_json(root, x, role))
    seal_records.check_privacy(rec, doc)


def commit_written(root, kinds=(ledger.ORDER2_KIND,), messages=None):
    """書いたがコミットしていない順番2の記録を、入口と同じ固定のしかたでコミットする（--commit-written。差し戻し2回目
    中-B）。最後の記録が stats-order2 で、作業ツリーの変更がその記録・中身・.ots（あれば）だけのときに限る。
    T-081：コミットの前に、記録と中身を照らす（check_written）。
    T-090：順番3の入口（seal_order3.py --commit-written）も使う。kinds は最後の記録の kind として受け付けるもの、messages は
    kind ごとのコミットの本文（既定は stats-order2 と COMMIT_MESSAGE）。"""
    messages = messages or {ledger.ORDER2_KIND: COMMIT_MESSAGE}
    repo = verify.Repo(root)
    ledger.check_sealed_inside(root)
    data = ledger.read_ledger(os.path.join(root, "sealed", "ledger.jsonl"))
    rec = ledger.verify_chain(data)[-1]
    if rec["kind"] not in kinds:
        raise ledger.LedgerError("最後の記録が %s でない。コミットしない" % "・".join(kinds))
    ots = os.path.join(root, "sealed", ledger.ots_name(rec["seq"]))
    ots = ots if os.path.isfile(ots) else None
    paths = {"sealed/ledger.jsonl"} | {t["path"] for t in rec["targets"]}
    if ots is not None:
        paths.add(os.path.relpath(ots, root).replace(os.sep, "/"))
    changed = set()
    for line in _git(repo, "status", "--porcelain", "--untracked-files=all").decode("utf-8").splitlines():
        changed.add(line[3:])
    if not changed or not changed <= paths:
        raise ledger.LedgerError("作業ツリーの変更（%s）が、最後の %s の記録・中身・.ots だけでない。コミットしない"
                                 % ("、".join(sorted(changed)), rec["kind"]))
    check_written(root, repo, data, rec, kinds)
    return commit_record(repo, root, rec, ots, messages[rec["kind"]])


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


def create_bundle(repo, root, path):
    """git bundle create <path> --all を作り（一時の参照は付けない。seal-order1.md 177行）、そのバイト列の sha256 と
    `git bundle list-heads` の出力を返す。返り値: (記録の bundle の欄, [{"name", "commit"}...]（list-heads の行の順）)。
    パスの誤り（既にある・プロジェクトか Git の中）は LedgerError（何も書かない）。T-091 で make_bundle から分けた。"""
    path = os.path.abspath(path)
    if os.path.lexists(path):
        raise ledger.LedgerError("bundle のパス %s が既にある。上書きしない。書かない" % path)
    _outside(root, path)
    _git(repo, "bundle", "create", "-q", path, "--all")
    heads = []
    for line in _git(repo, "bundle", "list-heads", path).decode("utf-8").splitlines():
        sha, _sp, name = line.partition(" ")
        heads.append({"name": name, "commit": sha})
    with open(path, "rb") as f:
        sha = hashlib.sha256(f.read()).hexdigest()
    return {"sha256": sha, "published": False, "reason": BUNDLE_REASON}, heads


def make_bundle(repo, root, path, snap):
    """bundle を作り、list-heads が snap（verify.read_refs_now で読んだ参照。refs・worktree_heads を持つもの）と合うことを
    確かめる（seal-order1.md 3章 (3) の 177・178行。照らし方は ledger.bundle_heads_match）。返り値: 記録の bundle の欄。
    合わなければ LedgerError（何も書かない。作った bundle のファイルは消さずに残す）。T-091：時機の条件（F と ok）は、
    これが通ったあとで計算する。"""
    field, heads = create_bundle(repo, root, path)
    if not ledger.bundle_heads_match(snap["refs"], snap["worktree_heads"], heads):
        raise ledger.LedgerError("bundle（%s）の list-heads が、記録する refs・worktree の HEAD と合わない（参照を読んでから bundle を"
                                 "作るまでに参照が変わった）。書かない（bundle のファイルは残してある）" % os.path.abspath(path))
    return field


def build_doc(root, data, records, stores, bundle_out):
    """手順 1〜5。返り値: 書く中身。"""
    repo = verify.Repo(root)
    head = clean_head(repo)
    got, trial, official = order2_gate.gate_with_manifests()              # 1. 関門
    run = got["input_run"]
    stores = check_stores(stores, run)
    seq = len(records) + 1
    ref = ledger.order2_ref_1b(records, seq)                                # 2. 参照する順番1b
    if ref is None:
        raise ledger.LedgerError("stats-order1b（順番1b）の記録が無い。書かない")
    d1b = ledger.read_target_json(root, ref, ledger.ORDER1B_KIND)
    code_sha = {f["path"]: f["sha256"] for f in d1b["files"]}[ledger.COUNTING_SCRIPT]
    snap = verify.read_refs_now(repo)                                      # 3. 参照を読む → bundle を照らす →
    bundle = make_bundle(repo, root, bundle_out, snap)                     #    合ったときだけ時機の条件（T-091。
    tc, guards = verify.timing_from_refs(repo, records, ref, snap)         #    seal-order1.md 177行の順）
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
        if len(after) <= len(records):
            raise                              # 追記の前で止まった：何も書いていない
        # 追記したあと（.ots の段）で止まった：記録と中身だけをコミットする
        last = after[-1]
        try:
            c = commit_record(repo, root, last, None)
        except ledger.LedgerError as e2:
            raise Order2Written("記録 seq %d と中身を作業ツリーに書いたが、.ots を作れず（%s）、コミットもしていない（%s）。"
                                "消さずに、原因を直してから seal_order2.py --commit-written でコミットし、stamp.py stamp --seq %d で"
                                ".ots を作る" % (last["seq"], e, e2, last["seq"])) from None
        raise Order2Written("記録 seq %d と中身を書いてコミット %s に入れたが、.ots を作れなかった（%s）。stamp.py stamp --seq %d で"
                            ".ots を作ってコミットする" % (last["seq"], c[:12], e, last["seq"])) from None
    try:
        commit = commit_record(repo, root, rec, ots_path)
    except ledger.LedgerError as e:
        raise Order2Written("記録 seq %d・中身・.ots を作業ツリーに書いたが、コミットしていない（%s）。消さずに、原因を直してから "
                            "seal_order2.py --commit-written でコミットする（手順書16章）" % (rec["seq"], e)) from None
    return rec, rel, ots_path, doc, commit


def main(argv=None):
    p = argparse.ArgumentParser(allow_abbrev=False, description=__doc__.splitlines()[0])
    p.add_argument("--trial-store", help="試しの run の日の集計の置き場所（decide() が試しの run の段に進むときに要る）")
    p.add_argument("--official-store", help="正式な run の日の集計の置き場所（正式な run の段に進むときに要る）")
    p.add_argument("--bundle-out", help="git bundle を書くパス（プロジェクトと Git の外。まだ無いもの）")
    p.add_argument("--ots", default=stamp.DEFAULT_OTS)
    p.add_argument("--commit-written", action="store_true",
                   help="書いたがコミットしていない最後の stats-order2 の記録を、入口と同じ固定のしかたでコミットする")
    a = p.parse_args(argv)
    if a.commit_written:
        try:
            c = commit_written(ledger.check_sealed_inside(ledger.PROJECT_ROOT))
        except ledger.LedgerError as e:
            print("失敗（コミットしていない）: %s" % e, file=sys.stderr)
            return 1
        print("コミット: %s" % c)
        return 0
    if not a.bundle_out:
        p.error("--bundle-out が要る")
    now = datetime.datetime.now(datetime.timezone.utc)
    try:
        rec, rel, ots_path, doc, commit = seal({"trial": a.trial_store, "official": a.official_store}, a.bundle_out, now,
                                               a.ots)
    except Order2Written as e:
        print("止まった（順番2の記録は書いた）: %s" % e, file=sys.stderr)
        return 1
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
