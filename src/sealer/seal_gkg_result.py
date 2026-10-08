#!/usr/bin/env python3
"""GKG の取得の run が終わったあとに、マニフェストを封印の記録に縛る記録（kind: gkg-run-result）を書く仕組み。
T-066（T-063 の採点 中-1。決定事項「Git にはマニフェストだけを入れ、マニフェストに時刻証明を付ける」）。

手順書は docs/verify/periods-seal.md 12章の「マニフェストの時刻証明（gkg-run-result。T-066）」。

使い方（プロジェクトのルートで。ots の通信を使うので .venv の python で実行する。drand は使わない）
    PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -B src/sealer/seal_gkg_result.py seal --mode trial --run-id <16桁>

書く中身（ledger.GKG_RESULT_DOC_KEYS の 11 個）
    kind                       "gkg-run-result"
    mode・run_id               run の mode と run_id
    gkg_run_seq                その run の gkg-run-start の記録の seq
    gkg_run_record_sha256      その記録の行（正規の形）の sha256
    manifest_path              mode のマニフェスト（data/manifest/gdelt-gkg-trial.jsonl か gdelt-gkg-method.jsonl）
    manifest_lines             書いた時点のマニフェストの行の数（全部）
    manifest_sha256            その全部（先頭 manifest_lines 行）のバイト列の sha256
    run_complete_line_sha256   その run の run-complete の行（改行を除く）の sha256
    manifest_commit            書いた時点の HEAD の commit（マニフェストはこの版と同じであること）
    ledger_head                直前の記録までのハッシュ

拒むもの（何も書かずに止める。ots の通信の前）
  - 記録の鎖か .ots の検証に通らない。periods の記録が無い。
  - mode・run_id の gkg-run-start の記録が無い。同じ mode・run_id の gkg-run-result が既にある（1つの run に
    1件だけ）。
  - マニフェストが無い・通常のファイルでない・改行で終わっていない。作業ツリーの中身が HEAD の版と違う
    （コミットしていない行がある）。
  - マニフェストが照合（ledger.check_gkg_manifests。run-start の入力の値、day・run-complete の行）に通らない。
  - その run の run-complete の行が無い（run が終わっていない）。

いつ書くか
  run-complete の行を書いたマニフェストをコミットしたあと、すぐに（取得のあとで、集計の結果を見る前に）。
  データを受け取ったあとの記録なので、取得から封印までの間にマニフェストと日の集計を選び直す余地は残る
  （手順書の「守れること・守れないこと」）。試しの run（既にコミット済みの gdelt-gkg-trial.jsonl）にも、
  同じ形で後から付けられる。
"""

import argparse
import datetime
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import ledger  # noqa: E402
import seal_records  # noqa: E402
import stamp  # noqa: E402

PROJECT = os.path.dirname(os.path.dirname(HERE))


def _git(project, *args):
    r = subprocess.run(["git", "-C", project] + list(args), capture_output=True, env=ledger.fixed_git_env())
    if r.returncode != 0:
        raise ledger.LedgerError("git %s が失敗した。追記しない" % " ".join(args[:2]))
    return r.stdout


def read_manifests(project):
    """{mode: 作業ツリーのマニフェストのバイト列か None}（verify と同じ読み方）。"""
    out = {}
    for mode, rel in ledger.GKG_MANIFESTS.items():
        path = os.path.join(project, rel)
        out[mode] = None
        if os.path.lexists(path):
            if os.path.islink(path) or not os.path.isfile(path):
                raise ledger.LedgerError("%s が通常のファイルでない。追記しない" % rel)
            with open(path, "rb") as f:
                out[mode] = f.read()
    return out


def build_doc(project, data, records, mode, run_id):
    """書く中身を作る（照合を含む）。返り値: 中身の dict。"""
    if mode not in ledger.GKG_RUN_MODES:
        raise ledger.LedgerError("mode は trial か official だけ。追記しない")
    read = lambda r, role: ledger.read_target_json(project, r, role)  # noqa: E731
    starts = [r for r in records if r["kind"] == ledger.GKG_RUN_KIND
              and (read(r, ledger.GKG_RUN_KIND).get("mode"), read(r, ledger.GKG_RUN_KIND).get("run_id"))
              == (mode, run_id)]
    if len(starts) != 1:
        raise ledger.LedgerError("mode %s・run_id %s の gkg-run-start の記録が %d 件（ちょうど1件でない）。追記しない"
                                 % (mode, run_id, len(starts)))
    start = starts[0]
    for r in records:
        if r["kind"] == ledger.GKG_RESULT_KIND:
            d = read(r, ledger.GKG_RESULT_KIND)
            if (d.get("mode"), d.get("run_id")) == (mode, run_id):
                raise ledger.LedgerError("mode %s・run_id %s の gkg-run-result（seq %d）が既にある。1つの run に1件だけ。"
                                         "追記しない" % (mode, run_id, r["seq"]))
    rel = ledger.GKG_MANIFESTS[mode]
    manifests = read_manifests(project)
    body = manifests[mode]
    if body is None:
        raise ledger.LedgerError("%s が無い。追記しない" % rel)
    if not body.endswith(b"\n"):
        raise ledger.LedgerError("%s が改行で終わっていない（書き込みの途中）。追記しない" % rel)
    head = _git(project, "rev-parse", "HEAD").decode().strip()
    if _git(project, "show", "HEAD:%s" % rel) != body:
        raise ledger.LedgerError("%s が HEAD の版と違う（コミットしていない行がある）。コミットしてから書く。追記しない"
                                 % rel)
    ledger.check_gkg_manifests(records, read, manifests)
    runs = ledger.check_gkg_manifest_rows(records, read, mode, body)
    run = runs.get(run_id)
    if run is None or run["complete"] is None:
        raise ledger.LedgerError("%s に run_id %s の run-complete の行が無い（run が終わっていない）。追記しない"
                                 % (rel, run_id))
    line = body.split(b"\n")[run["complete_lineno"] - 1]
    return {
        "kind": ledger.GKG_RESULT_KIND,
        "mode": mode,
        "run_id": run_id,
        "gkg_run_seq": start["seq"],
        "gkg_run_record_sha256": ledger.sha256_hex(ledger.canonical_line(start)),
        "manifest_path": rel,
        "manifest_lines": body.count(b"\n"),
        "manifest_sha256": ledger.sha256_hex(body),
        "run_complete_line_sha256": ledger.sha256_hex(line),
        "manifest_commit": head,
        "ledger_head": ledger.expected_ledger_head(data, len(records) + 1),
    }


def seal(project, mode, run_id, now, ots_cmd, runner=subprocess.run):
    """gkg-run-result を 1 件追記する。返り値: (記録, 中身のパス, .ots のパス か None)。"""
    project = os.path.abspath(project)
    data, records = seal_records.load_checked(project, ots_cmd, runner=runner)
    doc = build_doc(project, data, records, mode, run_id)
    n = sum(1 for r in records if r["kind"] == ledger.GKG_RESULT_KIND) + 1
    note = ("GKG の取得の run の結果のマニフェストの封印（%s。run_id %s。%s の先頭 %d 行）。gkg-run-result の %d 件目。"
            "採用の区切りには使わない。" % ("試しの run" if mode == "trial" else "正式な run", run_id,
                                     doc["manifest_path"], doc["manifest_lines"], n))
    return seal_records.write_doc_record(project, ledger.GKG_RESULT_KIND, doc, data, note, now, ots_cmd,
                                         runner=runner)


def main(argv=None):
    p = argparse.ArgumentParser(allow_abbrev=False, description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest="action", required=True)
    s = sub.add_parser("seal", allow_abbrev=False)
    s.add_argument("--mode", required=True, choices=ledger.GKG_RUN_MODES)
    s.add_argument("--run-id", required=True)
    s.add_argument("--ots", default=stamp.DEFAULT_OTS)
    s.add_argument("--root", default=PROJECT)
    a = p.parse_args(argv)
    root = os.path.abspath(a.root)
    now = datetime.datetime.now(datetime.timezone.utc)
    try:
        rec, rel, ots_path = seal(root, a.mode, a.run_id, now, a.ots)
    except ledger.LedgerError as e:
        print("失敗: %s" % e, file=sys.stderr)
        return 1
    print(ledger.canonical_line(rec).decode("utf-8"))
    print("中身: %s" % rel)
    print("時刻証明: %s" % os.path.relpath(ots_path, root))
    return 0


if __name__ == "__main__":
    sys.exit(main())
