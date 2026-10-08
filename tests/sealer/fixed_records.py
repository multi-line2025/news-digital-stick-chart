"""本物の記録を使うテストの共通の入口（T-077）。テストではない（unittest の discover は読まない）。

tests/sealer のテストが従う規則（test_t077.TestRuleScan が、ast で数えて守らせる）:
  1. テストは、プロジェクトの HEAD の sealed/（sealed/ledger.jsonl を含む）・data/manifest/ の今の状態を
     前提にしない。封印の記録が1件増えても、どのテストの結果も変わらないようにする。
  2. 本物の記録を使うテストは、このモジュールの checkout()・show() で、定数に書いたコミット（40 桁の sha。
     既定は PINNED_COMMIT）の版を git から取り出して使う。そうでなければ、合成の鎖を使う。
  3. HEAD の本物の記録をそのまま読んでよいのは、「本物の記録で verify が 0 になる」ことを確かめるテスト
     だけ（test_t077.HEAD_READERS の一覧）。そのテストは、記録が増えても壊れない書き方にする。

このモジュールは、プロジェクトのファイルに何も書かない。プロジェクトの git から読むのは、
定数のコミットの版と、checkout(code="head") のときの HEAD のコミットの版（sealed/・data/・reviews/ を除く
ファイル。コードと手順書）だけ。
"""

import os
import re
import shutil
import subprocess

PROJECT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 本物の記録を使うテストが既定で取り出すコミット（T-075 の削除の結果を記録したコミット）。
# このコミットの版：sealed/ledger.jsonl は seq 1〜8。試しの run（run_id e15ed53595c70035）のマニフェスト
# data/manifest/gdelt-gkg-trial.jsonl は 5 行（run-complete まで）。gkg-run-result（seq 9。コミット 220297a）は
# まだ無い。T-066・T-068・T-073・T-074 のテストは、この「R の gkg-run-result がまだ無い」状態を前提にする。
PINNED_COMMIT = "5ce3943b827ff67f4f7e7db811525946bafdea46"

# checkout(code="head") で、HEAD の版にそろえないパス（固定したコミットの版のまま使う。記録とデータ）
RECORD_PATHS = ("sealed", "data", "reviews")

AUTHOR = ("-c", "user.name=Multi-line", "-c",
          "user.email=197505900+multi-line2025@users.noreply.github.com")
SHA_RE = re.compile(r"\A[0-9a-f]{40}\Z")
# SEALER_DOC_TEST_WORKTREE=1 のとき、作業ツリーから写すフォルダ（test_verify_doc・test_post_text と同じ）
WORKTREE_OVERLAY = ("src/sealer", "tests/sealer", "docs/verify")


def _commit(commit):
    """40 桁の sha だけを受け付ける（HEAD・枝の名前・短い sha は、指す先が後で変わりうるので拒む）。"""
    if not isinstance(commit, str) or not SHA_RE.match(commit):
        raise ValueError("コミットは 40 桁の sha で書く（HEAD や枝の名前は使わない）: %r" % (commit,))
    return commit


def _git(*args, cwd=None):
    cmd = ["git"] + (["-C", cwd] if cwd else []) + list(args)
    return subprocess.run(cmd, check=True, capture_output=True).stdout


def show(rel, commit=PINNED_COMMIT):
    """プロジェクトの git から、commit の版の rel のバイト列を返す（作業ツリーは読まない）。"""
    return _git("show", "%s:%s" % (_commit(commit), rel), cwd=PROJECT)


def ls(prefix, commit=PINNED_COMMIT):
    """commit の版で、prefix（例 "sealed/"）の下にあるファイルのパスの一覧。"""
    out = _git("ls-tree", "-r", "--name-only", _commit(commit), "--", prefix, cwd=PROJECT)
    return out.decode("utf-8").splitlines()


def overlay_worktree(dest):
    """dest（取り出したリポジトリか、HEAD の clone）の src/sealer・tests/sealer・docs/verify を、プロジェクトの
    作業ツリーの版に置き換えて、dest の中で一時的にコミットする（SEALER_DOC_TEST_WORKTREE=1 のとき。
    プロジェクトには何も書かない。sealed/・data/ は写さない）。"""
    for rel in WORKTREE_OVERLAY:
        shutil.rmtree(os.path.join(dest, rel), ignore_errors=True)
        shutil.copytree(os.path.join(PROJECT, rel), os.path.join(dest, rel),
                        ignore=shutil.ignore_patterns("__pycache__"))
    _git("add", "-A", "--", *WORKTREE_OVERLAY, cwd=dest)
    _git(*(list(AUTHOR) + ["commit", "-q", "--allow-empty", "-m", "一時的なコミット（テストの中だけ）"]), cwd=dest)


def head_sha():
    """プロジェクトの HEAD のコミットの sha（checkout(code="head") がコードを写すのに使う）。"""
    return _git("rev-parse", "--verify", "-q", "HEAD^{commit}", cwd=PROJECT).decode("ascii").strip()


def checkout(dest, commit=PINNED_COMMIT, code="head"):
    """dest に、commit とその祖先だけを取り込んだ git のリポジトリを作る。dest を返す。

    commit より後を指す参照は作らない（git log --all が後の記録・マニフェストの履歴を見つけないように。
    T-065 の test_t037 と同じ作り）。参照は refs/heads/main の1つだけ。
      code=None     : commit の版をそのまま取り出す。
      code="head"   : sealed/・data/・reviews/ は commit の版のまま、それ以外のファイル（コード・手順書）を
                      プロジェクトの HEAD のコミットの版にそろえ、1つのコミットにする（記録は固定、コードは今の版）。
                      commit が HEAD の祖先でなければ止める。
      code="worktree": "head" のうえで、src/sealer・tests/sealer・docs/verify を作業ツリーの版にして、もう1つ
                      コミットする（SEALER_DOC_TEST_WORKTREE=1 で、コミットの前の版を試すとき）。
    """
    commit = _commit(commit)
    if code not in (None, "head", "worktree"):
        raise ValueError("code は None・head・worktree のどれか: %r" % (code,))
    _git("init", "-q", dest)
    want = [commit]
    head = None
    if code is not None:
        head = head_sha()
        want.append(head)
    # protocol v2 でないと、参照でないコミットを取れない（T-068）
    _git("-c", "protocol.version=2", "fetch", "-q", "--no-tags", PROJECT, *want, cwd=dest)
    _git("checkout", "-q", "-B", "main", commit, cwd=dest)
    if code is not None:
        r = subprocess.run(["git", "-C", dest, "merge-base", "--is-ancestor", commit, head], capture_output=True)
        if r.returncode != 0:
            raise RuntimeError("固定したコミット %s が、プロジェクトの HEAD の祖先でない（履歴が書き換えられた？）"
                               % commit)
        spec = ["."] + [":(exclude)%s" % p for p in RECORD_PATHS]
        gone = _git("diff", "--name-only", "--no-renames", "--diff-filter=D", commit, head, "--", *spec,
                    cwd=dest).decode("utf-8").splitlines()
        if gone:
            _git("rm", "-q", "--", *gone, cwd=dest)
        _git("checkout", "-q", head, "--", *spec, cwd=dest)
        _git(*(list(AUTHOR) + ["commit", "-q", "--allow-empty", "-m",
                                "テストの中だけ：記録は %s の版、コードと手順書は HEAD の版" % commit[:12]]), cwd=dest)
    if code == "worktree":
        overlay_worktree(dest)
    refs = _git("for-each-ref", "--format=%(refname)", cwd=dest).decode("utf-8").split()
    if refs != ["refs/heads/main"]:
        raise RuntimeError("取り出したリポジトリに、main 以外の参照がある: %r" % refs)
    return dest
