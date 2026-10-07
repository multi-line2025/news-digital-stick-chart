#!/usr/bin/env python3
"""統計係の事前の封印（順番1・順番1b）を書く仕組み。T-037。

kind は二つ（ledger.ORDER1_KIND = "stats-order1"、ledger.ORDER1B_KIND = "stats-order1b"）。
一つの kind に「順番」の欄を持たせない理由（docs/verify/periods-seal.md 13章）：
  - 収集係の関門（themes.require_exclusion_rules_sealed）と gkg-run-start の exclusion_rule_seq は、
    「除外の規則の kind の最初の記録」を指す。kind を一つにすると、最初の記録が順番1b のことがあり、
    その kind の最初の記録が除外の規則であるとは限らなくなる。
  - 前に要る位置が違う（順番1 は区分表の取得と method-access の前に必須、順番1b は最初の
    gkg-run-start の前に必須）。中身の形と、封印の前に確かめることも違う。

手順は docs/stats/seal-order1.md 2章（順番1）と 3章 (3)（順番1b）。機械で照らせる項目を、書く前に
すべて確かめ、結果を記録の中身に入れる。一つでも通らなければ何も書かない。

    import seal_stats
    rec, rel, ots_path = seal_stats.seal_order1(project, now, ots_cmd)
    rec, rel, ots_path = seal_stats.seal_order1b(project, files, approvals, now, ots_cmd)

    files      順番1b の封印の対象のファイルの、ルートからの相対パスの list。ledger.ORDER1B_REQUIRED_FILES
               （counting.md・counting.py・test_counting.py・seal-order1.md）を必ず含むこと（無ければ止める）。
               HEAD に含まれ、作業ツリーと同じであること
    approvals  オーナーの承認の照らし方の list。各要素は {"item": 名前, "commit": 40 桁, "path": パス,
               "lines": [行, ...]}。lines の最後の行が、その commit の版のファイルにちょうど 1 行あり、
               その前の行が lines の前の行と順に一致すること（seal-order1.md 2章の項目1 と同じ形）

順番1 で確かめること（seal-order1.md 2章。番号は 2章の項目）
  0  stats-order1 の記録がまだ無い（順番1 は 1 件だけ。T-037 の差し戻し1回目 中5）
  1  承認 A・B・B (ii) の行を、40 桁の commit の版の reviews/ で照らす（ledger.ORDER1_APPROVALS）
  2  区分表の取得のマニフェスト（data/manifest/gdelt-themes.jsonl）と GKG のマニフェスト
     （gdelt-gkg-method.jsonl・gdelt-gkg-trial.jsonl）が、作業ツリーに無いか行が無く、
     `git log --all` の履歴も空。ledger に method-access が無い。すべての acquisition-start の
     targets のファイルの sha256 が合い、fetch.code_path が src/collector/acquire_filelist.py
  3  作業ツリーがきれい（git status --porcelain が空。追跡していないファイルも含む）
  4  HEAD の 40 桁、祖先（ledger.ORDER1_ANCESTORS の 4 つ。短い ID がその 40 桁を指すことも）、
     Python のパスと版（.venv/bin/python に固定）
  5  浅い clone でない
  6  10 件（名前は ledger.ORDER1_TARGET_NAMES に固定。表の行がちょうどこの 10 件であること）の
     sha256 を、このコードで 1章のバイト列の定義どおりに計算し直し、docs/stats/seal-order1.md
     （HEAD の版）の表と照らす。一つでも違えば書かない
  7  2d23cdf の版の reviews/T-020.md の見出しと三行（ledger.OWNER_CHOICE）。除外の規則の出力の
     owner_choice_source が決まった文字列であること
  8  除外の規則の出力の optional_choice_status と、tagrules.py の出力の exclusion の
     optional_choice_status が "decided"（"undecided" なら書かない）
  9  `.venv/bin/python -B -m unittest discover -s tests/stats` がすべて通る
  10 対象だけを置いた写し（tempfile の一時フォルダ。終われば自動で消える）に、HEAD の版の 5 件と、
     1cb463a・2d23cdf の履歴（深さ 1 の fetch）だけを置き、見張りの環境変数を付けずに
     ORDER1_SEALED_TESTS を流して通ること。流したあと、写しの中のファイルが置いた 5 件だけであること。
     結果（件数とファイルの一覧）を checks.targets_only_copy に入れる（T-037 の差し戻し1回目 中4）
  最後に、HEAD と作業ツリーがはじめと同じことを、書く直前にもう一度確かめる（軽3）。
  子のプロセスには、PYTHON で始まる環境変数と STATS_AUDIT_LOG を渡さない（軽2）。
順番1b で確かめること（seal-order1.md 3章 (3)、docs/stats/counting.md 0章 (1)・7章）
  1  method-access が無い。GKG のマニフェストが無いか行が無く、履歴も空
  2・4・6  files（ORDER1B_REQUIRED_FILES を含む）の各ファイルが HEAD に含まれ、作業ツリーと同じ。
     sha256 をこのコードで計算する。counting.py を引数なしで実行し、出力の sha256、候補の識別子
     （candidates の id）、基準の案の識別子（criteria_ids）、正式な数え方（official_candidate。
     official_status が "decided" で、候補の中にあること）を記録に入れる
  3  approvals の照らし方。B (ii)（ledger.ORDER1_APPROVALS の 3 つめ）も必ず照らす。
     正式な数え方の出どころ（ledger.OWNER_DECISION）：9c85f58 の reviews/T-028.md で、オーナーの
     発言の行がちょうど 1 行、「- 決定：正式に使う数え方は、」で始まる行がちょうど 1 行で、その行に
     二つの語句を含むこと。counting.py の出力の owner_decision が同じ出どころであること
  5  作業ツリーがきれい、HEAD の 40 桁、浅い clone でない
  順番1 の記録があれば、その seq と行の sha256 を order1_ref に入れる
  確かめないこと：項目0（試しの run の作りを直すタスクの合格。reviews/ の記録でリードが確かめる）。

CLI（プロジェクトのルートで。ots の通信を使うので .venv の python で実行する）
    PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -B src/sealer/seal_stats.py order1
    PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -B src/sealer/seal_stats.py order1b \\
        --file <パス> [--file <パス> ...] --approvals-json <承認の照らし方の JSON のファイル>
"""

import argparse
import datetime
import json
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import ledger  # noqa: E402
import seal_records  # noqa: E402
import stamp  # noqa: E402

PROJECT = os.path.dirname(os.path.dirname(HERE))
PYTHON_REL = ".venv/bin/python"
TABLE_DOC = "docs/stats/seal-order1.md"
TABLE_MARKER = "<!-- table:seal-targets -->"
THEMES_MANIFEST = ledger.THEMES_MANIFEST
GKG_MANIFESTS = ("data/manifest/gdelt-gkg-method.jsonl", "data/manifest/gdelt-gkg-trial.jsonl")
OUTPUT_SUFFIX = " の出力"
OWNER_CHOICE_SOURCE = "2d23cdf:reviews/T-020.md 2026-10-08 オーナーの発言（原文のまま記録）"
EXCLUSION_SCRIPT = "src/stats/exclusion.py"
TAGRULES_SCRIPT = "src/stats/tagrules.py"
STATS_TIMEOUT_SECONDS = 1800


# ---------------------------------------------------------------- git と Python


def _git(project, *args, check=True):
    r = subprocess.run(["git", "-C", project] + list(args), capture_output=True)
    if check and r.returncode != 0:
        raise ledger.LedgerError("git %s が失敗した" % " ".join(args[:2]))
    return r


def git_state(project):
    """2章の項目3・5 と HEAD。返り値: HEAD の 40 桁。"""
    if _git(project, "status", "--porcelain").stdout.strip():
        raise ledger.LedgerError("作業ツリーがきれいでない（git status --porcelain が空でない）。封印しない")
    if _git(project, "rev-parse", "--is-shallow-repository").stdout.strip() != b"false":
        raise ledger.LedgerError("浅い clone である。封印しない")
    head = _git(project, "rev-parse", "HEAD").stdout.decode().strip()
    if not ledger.HEX40.match(head):
        raise ledger.LedgerError("HEAD の commit ID が 40 桁の16進でない")
    return head


def recheck_state(project, head):
    """書く直前に、HEAD と作業ツリーがはじめと同じことを確かめる（T-037 の差し戻し1回目 軽3）。"""
    if git_state(project) != head:
        raise ledger.LedgerError("確かめているあいだに HEAD が変わった。封印しない")


def check_ancestor(project, full, short=None):
    if short is not None:
        got = _git(project, "rev-parse", "--verify", "-q", short + "^{commit}", check=False)
        if got.returncode != 0 or got.stdout.decode().strip() != full:
            raise ledger.LedgerError("短い ID %s が %s を指さない" % (short, full))
    if _git(project, "merge-base", "--is-ancestor", full, "HEAD", check=False).returncode != 0:
        raise ledger.LedgerError("%s が HEAD の祖先でない。封印しない" % full)


def git_show(project, commit, path):
    r = _git(project, "show", "%s:%s" % (commit, path), check=False)
    if r.returncode != 0:
        raise ledger.LedgerError("git show %s:%s が失敗した" % (commit, path))
    return r.stdout


def child_env():
    """子のプロセスの環境変数（T-037 の差し戻し1回目 軽2）。PYTHON で始まるもの（PYTHONPATH・
    PYTHONPYCACHEPREFIX・PYTHONHOME など）と STATS_AUDIT_LOG を除き、PYTHONDONTWRITEBYTECODE=1 だけを足す。"""
    env = {k: v for k, v in os.environ.items()
           if not k.startswith("PYTHON") and k != "STATS_AUDIT_LOG"}
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


def python_info(project):
    """2章の項目4：Python のパス（.venv/bin/python に固定）と版。返り値: (絶対パス, 記録する dict)。"""
    full = os.path.join(project, PYTHON_REL)
    if not os.path.exists(full):
        raise ledger.LedgerError("%s が無い。封印しない" % PYTHON_REL)
    r = subprocess.run([full, "--version"], capture_output=True, env=child_env())
    version = (r.stdout or r.stderr).decode().strip()
    if r.returncode != 0 or not version.startswith("Python "):
        raise ledger.LedgerError("%s --version が失敗した" % PYTHON_REL)
    return full, {"path": PYTHON_REL, "version": version}


def run_script(python, cwd, script):
    """python -B script（引数なし）の標準出力のバイト列。"""
    r = subprocess.run([python, "-B", script], cwd=cwd, capture_output=True, env=child_env(),
                       timeout=STATS_TIMEOUT_SECONDS)
    if r.returncode != 0:
        raise ledger.LedgerError("%s の実行が失敗した（終了コード %d）" % (script, r.returncode))
    return r.stdout


def run_unittest(python, cwd, args, what):
    """python -B -m unittest args を流し、すべて通れば "OK (N tests)" を返す。"""
    r = subprocess.run([python, "-B", "-m", "unittest"] + list(args), cwd=cwd, capture_output=True,
                       env=child_env(), timeout=STATS_TIMEOUT_SECONDS)
    err = r.stderr.decode("utf-8", "replace")
    m = re.search(r"^Ran (\d+) tests? ", err, re.M)
    if r.returncode != 0 or m is None or not re.search(r"^OK", err, re.M):
        raise ledger.LedgerError("%s が通らない。封印しない" % what)
    return "OK (%s tests)" % m.group(1)


# ---------------------------------------------------------------- 承認と出どころ


def _lines_of(project, commit, path):
    return git_show(project, commit, path).decode("utf-8").split("\n")


def check_approval(project, item, commit, path, lines):
    """lines の最後の行が、commit の版の path にちょうど 1 行あり、その前の行が lines の前の行と
    順に一致すること。返り値: 記録に入れる dict。"""
    if not ledger.HEX40.match(commit):
        raise ledger.LedgerError("承認 %s の commit が 40 桁でない" % item)
    check_ancestor(project, commit)
    text = _lines_of(project, commit, path)
    lines = list(lines)
    idx = [i for i, l in enumerate(text) if l == lines[-1]]
    if len(idx) != 1:
        raise ledger.LedgerError("承認 %s：%s:%s で、行 %r が %d 行ある（ちょうど 1 行でない）"
                                 % (item, commit, path, lines[-1], len(idx)))
    i = idx[0]
    before = lines[:-1]
    if i < len(before) or text[i - len(before):i] != before:
        raise ledger.LedgerError("承認 %s：%s:%s で、行 %r の直前の行が違う" % (item, commit, path, lines[-1]))
    return {"item": item, "source": "%s:%s" % (commit, path), "lines": lines}


def check_owner_choice(project):
    """2章の項目7。返り値: 記録に入れる dict。"""
    commit, path, heading, lines = ledger.OWNER_CHOICE
    text = _lines_of(project, commit, path)
    idx = [i for i, l in enumerate(text) if l == heading]
    if len(idx) != 1:
        raise ledger.LedgerError("%s:%s の見出し %r が %d 個ある（ちょうど 1 個でない）"
                                 % (commit, path, heading, len(idx)))
    section = []
    for l in text[idx[0] + 1:]:
        if l.startswith("## "):
            break
        section.append(l)
    missing = [l for l in lines if l not in section]
    if missing:
        raise ledger.LedgerError("%s:%s の見出しの節に、行 %s が無い" % (commit, path, missing))
    return ledger.expected_owner_choice()


def check_owner_decision(project):
    """順番1b：正式な数え方の出どころ（ledger.OWNER_DECISION。counting.md 0章 (1)）。
    返り値: 記録に入れる dict（{source, source_line, decision_line}）。"""
    commit, path, source_line, prefix, phrases = ledger.OWNER_DECISION
    check_ancestor(project, commit)
    text = _lines_of(project, commit, path)
    n = sum(1 for l in text if l == source_line)
    if n != 1:
        raise ledger.LedgerError("%s:%s で、オーナーの発言の行 %r が %d 行ある（ちょうど 1 行でない）"
                                 % (commit, path, source_line, n))
    dec = [l for l in text if l.startswith(prefix)]
    if len(dec) != 1:
        raise ledger.LedgerError("%s:%s で、%r で始まる行が %d 行ある（ちょうど 1 行でない）"
                                 % (commit, path, prefix, len(dec)))
    missing = [p for p in phrases if p not in dec[0]]
    if missing:
        raise ledger.LedgerError("%s:%s の「決定：」の行に、語句 %s が無い" % (commit, path, missing))
    return {"source": "%s:%s" % (commit, path), "source_line": source_line, "decision_line": dec[0]}


# ---------------------------------------------------------------- 10 件の sha256


def read_table(project, head):
    """HEAD の版の docs/stats/seal-order1.md の表。返り値: [(名前, sha256)]。名前がちょうど
    ledger.ORDER1_TARGET_NAMES の 10 件でなければ止める（T-037 の差し戻し1回目 中3）。"""
    text = git_show(project, head, TABLE_DOC).decode("utf-8").split("\n")
    if TABLE_MARKER not in text:
        raise ledger.LedgerError("%s に表の印 %s が無い" % (TABLE_DOC, TABLE_MARKER))
    rows = []
    for l in text[text.index(TABLE_MARKER) + 1:]:
        if not l.startswith("|"):
            if rows:
                break
            continue
        m = re.match(r"\A\| `([^`]+)` \| `([0-9a-f]{64})` \|\Z", l)
        if m:
            rows.append((m.group(1), m.group(2)))
    names = [n for n, _ in rows]
    if sorted(names) != sorted(ledger.ORDER1_TARGET_NAMES) or len(set(names)) != len(names):
        raise ledger.LedgerError("%s の表の対象が、決まった 10 件（ledger.ORDER1_TARGET_NAMES）とちょうど一致"
                                 "しない。封印しない" % TABLE_DOC)
    return rows


def target_bytes(project, python, name):
    """1章のバイト列の定義どおりに、対象の名前からバイト列を作る。"""
    output = name.endswith(OUTPUT_SUFFIX)
    base = name[:-len(OUTPUT_SUFFIX)] if output else name
    m = re.match(r"\A([0-9a-f]{7,40}):(.+)\Z", base)
    if m:
        short, path = m.groups()
        full = ledger.ORDER1_ANCESTORS.get(short)
        if full is None:
            raise ledger.LedgerError("対象 %s の commit %s が、決まった祖先の一覧に無い" % (name, short))
        data = git_show(project, full, path)
        if not output:
            return data
        with tempfile.TemporaryDirectory() as tmp:
            script = os.path.join(tmp, os.path.basename(path))
            with open(script, "wb") as f:
                f.write(data)
            return run_script(python, tmp, script)
    path = os.path.normpath(base)
    if path.startswith("..") or os.path.isabs(path):
        raise ledger.LedgerError("対象 %s のパスがプロジェクトの中でない" % name)
    if output:
        return run_script(python, project, base)
    with open(os.path.join(project, path), "rb") as f:
        return f.read()


def targets_only_copy(project, python, head):
    """2章の項目10。tempfile の一時フォルダ（終われば消える）に、HEAD の版の 5 件と、履歴から読む
    commit（深さ 1）だけを置き、ledger.ORDER1_SEALED_TESTS を見張りなしで流す。返り値: 記録に入れる dict。"""
    files = sorted(ledger.order1_copy_files())
    with tempfile.TemporaryDirectory() as c:
        def git(*args):
            r = subprocess.run(["git", "-C", c] + list(args), capture_output=True)
            if r.returncode != 0:
                raise ledger.LedgerError("写しの git %s が失敗した" % " ".join(args[:2]))
        git("init", "-q")
        git("fetch", "-q", "--depth=1", project, *ledger.order1_history_commits())
        for rel in files:
            os.makedirs(os.path.join(c, os.path.dirname(rel)), exist_ok=True)
            with open(os.path.join(c, rel), "wb") as f:
                f.write(git_show(project, head, rel))
        tests = run_unittest(python, c, ledger.ORDER1_SEALED_TESTS, "対象だけを置いた写しのテスト")
        found = []
        for root, dirs, names in os.walk(c):
            dirs[:] = [d for d in dirs if not (root == c and d == ".git")]
            found += [os.path.relpath(os.path.join(root, n), c) for n in names]
        if sorted(found) != files:
            raise ledger.LedgerError("対象だけを置いた写しに、置いた 5 件のほかのファイルがある（%s）。封印しない"
                                     % ", ".join(sorted(set(found) - set(files))))
    return {"tests": tests, "files": files}


# ---------------------------------------------------------------- まだ無いことの確認


def manifest_absent(project, path):
    """作業ツリーに無いか行が無く、git log --all の履歴も空であること。"""
    full = os.path.join(project, path)
    if os.path.lexists(full):
        with open(full, "rb") as f:
            if any(l.strip() for l in f.read().split(b"\n")):
                raise ledger.LedgerError("%s に行がある（取得を始めている）。封印しない" % path)
    if _git(project, "log", "--all", "--oneline", "--", path).stdout.strip():
        raise ledger.LedgerError("%s の履歴が空でない（取得を試みたことがある）。封印しない" % path)
    return True


def no_method_access(records):
    if any(r["kind"] == ledger.METHOD_ACCESS_KIND for r in records):
        raise ledger.LedgerError("method-access の記録がある。封印しない")
    return True


def acquisition_starts_ok(project, records):
    """2章の項目2 の最後：すべての acquisition-start の targets のファイルの sha256 が合い、
    fetch.code_path が src/collector/acquire_filelist.py。返り値: 記録に入れる文字列の list。"""
    out = []
    for r in records:
        if r["kind"] != ledger.ACQ_START_KIND:
            continue
        if not r["targets"]:
            raise ledger.LedgerError("acquisition-start（seq %d）の targets が空" % r["seq"])
        doc = ledger.read_target_json(project, r, ledger.ACQ_START_KIND)
        path, _sha = ledger.acquisition_start_fields(doc)
        if path != ledger.FILELIST_CODE_PATH:
            raise ledger.LedgerError("acquisition-start（seq %d）の fetch.code_path が %s でない。封印しない"
                                     % (r["seq"], ledger.FILELIST_CODE_PATH))
        out.append("seq %d: %s" % (r["seq"], path))
    return out


def run_stats_tests(project, python):
    """2章の項目9。返り値: 記録に入れる文字列（"OK (N tests)"）。"""
    return run_unittest(python, project, ["discover", "-s", "tests/stats"], "tests/stats")


# ---------------------------------------------------------------- 書く入口


def seal_order1(project, now, ots_cmd, runner=subprocess.run):
    """stats-order1 を 1 件追記する。返り値: (記録, 中身のパス, .ots のパス か None)。"""
    project = os.path.abspath(project)        # 軽4：相対パスでも同じに動く
    data, records = seal_records.load_checked(project, ots_cmd, runner=runner)
    if ledger.first_order1(records) is not None:
        raise ledger.LedgerError("stats-order1 の記録が既にある。順番1 は 1 件だけ（新しい版の扱いは別に決める）。"
                                 "封印しない")
    head = git_state(project)
    checks = {"worktree_clean": True, "not_shallow": True}
    checks["method_access_absent"] = no_method_access(records)
    checks["themes_manifest_absent"] = manifest_absent(project, THEMES_MANIFEST)
    checks["gkg_manifests_absent"] = all(manifest_absent(project, p) for p in GKG_MANIFESTS)
    checks["acquisition_starts"] = acquisition_starts_ok(project, records)
    for short, full in sorted(ledger.ORDER1_ANCESTORS.items()):
        check_ancestor(project, full, short)
    approvals = [check_approval(project, *a) for a in ledger.ORDER1_APPROVALS]
    owner = check_owner_choice(project)
    python, py = python_info(project)
    targets = []
    for name, expected in read_table(project, head):
        got = ledger.sha256_hex(target_bytes(project, python, name))
        if got != expected:
            raise ledger.LedgerError("対象 %s の sha256 %s が、%s の表の値 %s と違う。封印しない"
                                     % (name, got, TABLE_DOC, expected))
        targets.append({"name": name, "sha256": got})
    ex = json.loads(target_bytes(project, python, EXCLUSION_SCRIPT + OUTPUT_SUFFIX).decode("utf-8"))
    tg = json.loads(target_bytes(project, python, TAGRULES_SCRIPT + OUTPUT_SUFFIX).decode("utf-8"))
    tg_ex = tg.get("exclusion") if isinstance(tg, dict) else None
    for what, value in (("除外の規則の出力", ex.get("optional_choice_status")),
                        ("tagrules.py の出力の exclusion",
                         tg_ex.get("optional_choice_status") if isinstance(tg_ex, dict) else None)):
        if value != "decided":
            raise ledger.LedgerError("%s の optional_choice_status が %r（decided でない）。封印しない"
                                     % (what, value))
    if ex.get("owner_choice_source") != OWNER_CHOICE_SOURCE:
        raise ledger.LedgerError("除外の規則の出力の owner_choice_source が %r でない。封印しない"
                                 % OWNER_CHOICE_SOURCE)
    checks["optional_choice_status"] = "decided"
    checks["stats_tests"] = run_stats_tests(project, python)
    checks["targets_only_copy"] = targets_only_copy(project, python, head)
    recheck_state(project, head)
    doc = {
        "kind": ledger.ORDER1_KIND,
        "head": head,
        "ancestors": sorted(ledger.ORDER1_ANCESTORS.values()),
        "python": py,
        "targets": targets,
        "approvals": approvals,
        "owner_choice": owner,
        "checks": checks,
        "ledger_head": ledger.expected_ledger_head(data, len(records) + 1),
    }
    note = ("統計係の順番1（除外の規則と入れる規則）の封印（docs/stats/seal-order1.md）。stats-order1 の "
            "1 件目。HEAD %s。" % head)
    return seal_records.write_doc_record(project, ledger.ORDER1_KIND, doc, data, note, now, ots_cmd,
                                         runner=runner)


def counting_summary(project, python):
    """順番1b：counting.py を引数なしで実行した出力から、記録に入れるもの（counting.md 7章）。"""
    out = run_script(python, project, ledger.COUNTING_SCRIPT)
    try:
        d = json.loads(out.decode("utf-8"))
        cands = [c["id"] for c in d["candidates"]]
        crit = list(d["criteria_ids"])
        official, status, od = d["official_candidate"], d["official_status"], d["owner_decision"]
    except (UnicodeDecodeError, ValueError, KeyError, TypeError):
        raise ledger.LedgerError("%s の出力から、候補・基準の案・正式な数え方を読めない。封印しない"
                                 % ledger.COUNTING_SCRIPT) from None
    if status != "decided" or official not in cands:
        raise ledger.LedgerError("%s の出力の正式な数え方が決まっていない（official_status %r、"
                                 "official_candidate %r）。封印しない" % (ledger.COUNTING_SCRIPT, status, official))
    commit, path, source_line, prefix, _phrases = ledger.OWNER_DECISION
    if not isinstance(od, dict) or (od.get("source_commit"), od.get("source_path"), od.get("source_line"),
                                    od.get("decision_line_prefix")) != (commit, path, source_line, prefix):
        raise ledger.LedgerError("%s の出力の owner_decision の出どころが、決まった出どころ（ledger.OWNER_DECISION）"
                                 "と違う。封印しない" % ledger.COUNTING_SCRIPT)
    return {"candidate_ids": cands, "criteria_ids": crit, "official_candidate": official,
            "official_status": status, "output_sha256": ledger.sha256_hex(out),
            "owner_decision": check_owner_decision(project)}


def seal_order1b(project, files, approvals, now, ots_cmd, runner=subprocess.run):
    """stats-order1b を 1 件追記する。返り値: (記録, 中身のパス, .ots のパス か None)。"""
    project = os.path.abspath(project)
    data, records = seal_records.load_checked(project, ots_cmd, runner=runner)
    head = git_state(project)
    checks = {"worktree_clean": True, "not_shallow": True}
    checks["method_access_absent"] = no_method_access(records)
    checks["gkg_manifests_absent"] = all(manifest_absent(project, p) for p in GKG_MANIFESTS)
    missing = [f for f in ledger.ORDER1B_REQUIRED_FILES if f not in files]
    if missing:
        raise ledger.LedgerError("files に、必ず入れるファイル %s が無い（ledger.ORDER1B_REQUIRED_FILES）。封印しない"
                                 % "、".join(missing))
    paths = list(dict.fromkeys(files))
    out_files = []
    for rel in paths:
        path, _ = ledger.acquisition_start_fields({"fetch": {"code_path": rel, "code_sha256": "0" * 64}})
        full = os.path.join(project, path)
        if os.path.islink(full) or not os.path.isfile(full):
            raise ledger.LedgerError("%s が無い（または通常のファイルでない）。封印しない" % path)
        if _git(project, "cat-file", "-e", "%s:%s" % (head, path), check=False).returncode != 0:
            raise ledger.LedgerError("%s が HEAD に含まれない。封印しない" % path)
        with open(full, "rb") as f:
            work = f.read()
        if git_show(project, head, path) != work:
            raise ledger.LedgerError("%s が HEAD の中身と違う。封印しない" % path)
        out_files.append({"path": path, "sha256": ledger.sha256_hex(work)})
    given = [(a["item"], a["commit"], a["path"], tuple(a["lines"])) for a in approvals]
    bii = ledger.ORDER1_APPROVALS[2]
    checked = [check_approval(project, *a) for a in given + [bii]]
    python, py = python_info(project)
    counting = counting_summary(project, python)
    o1 = ledger.first_order1(records)
    ref = None if o1 is None else {"seq": o1["seq"],
                                   "record_sha256": ledger.sha256_hex(ledger.canonical_line(o1))}
    recheck_state(project, head)
    doc = {
        "kind": ledger.ORDER1B_KIND,
        "head": head,
        "ancestors": sorted({a[1] for a in given + [bii]} | {ledger.OWNER_DECISION[0]}),
        "python": py,
        "files": out_files,
        "approvals": checked,
        "counting": counting,
        "order1_ref": ref,
        "checks": checks,
        "ledger_head": ledger.expected_ledger_head(data, len(records) + 1),
    }
    n = len(ledger.records_of_kind(records, ledger.ORDER1B_KIND)) + 1
    note = ("統計係の順番1b（数え方の候補と基準の案）の封印（docs/stats/seal-order1.md 3章 (3)）。"
            "stats-order1b の %d 件目。HEAD %s。" % (n, head))
    return seal_records.write_doc_record(project, ledger.ORDER1B_KIND, doc, data, note, now, ots_cmd,
                                         runner=runner)


def main(argv=None):
    p = argparse.ArgumentParser(allow_abbrev=False, description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest="action", required=True)
    o1 = sub.add_parser("order1", allow_abbrev=False)
    o1b = sub.add_parser("order1b", allow_abbrev=False)
    o1b.add_argument("--file", action="append", default=[])
    o1b.add_argument("--approvals-json", default=None)
    for q in (o1, o1b):
        q.add_argument("--ots", default=stamp.DEFAULT_OTS)
    a = p.parse_args(argv)
    now = datetime.datetime.now(datetime.timezone.utc)
    try:
        if a.action == "order1":
            rec, rel, ots_path = seal_order1(PROJECT, now, a.ots)
        else:
            approvals = []
            if a.approvals_json is not None:
                with open(a.approvals_json, encoding="utf-8") as f:
                    approvals = json.load(f)
            rec, rel, ots_path = seal_order1b(PROJECT, a.file, approvals, now, a.ots)
    except ledger.LedgerError as e:
        print("失敗: %s" % e, file=sys.stderr)
        return 1
    print(ledger.canonical_line(rec).decode("utf-8"))
    print("中身: %s" % rel)
    print("時刻証明: %s" % os.path.relpath(ots_path, PROJECT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
