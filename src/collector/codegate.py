#!/usr/bin/env python3
"""取得の入口のスクリプトが共通に使う関門の部品（T-018。T-015 の監査 軽1・軽2・軽5 への対応）。

データ出典
    Data: The GDELT Project (https://www.gdeltproject.org/). This project is not
    affiliated with or endorsed by the GDELT Project.
    データ出典：GDELT Project（https://www.gdeltproject.org/）。本プロジェクトは
    GDELT Project と提携・承認の関係にありません。

使うのは入口のスクリプト（acquire_filelist.py、acquire_gkg.py）だけ。ネットワークは使わない。
入口のスクリプトは、このファイルの sha256 を PINNED_SHA256 に固定する。

------------------------------------------------------------------------
1. git の実行（T-015 の監査 軽2：GIT_DIR などの環境変数の抜け道）
------------------------------------------------------------------------
    git は次の形でだけ実行する（run_git）。
      - 環境変数は、呼び出し元から受け継がない。GIT_DIR・GIT_WORK_TREE・GIT_INDEX_FILE・
        GIT_OBJECT_DIRECTORY・GIT_CONFIG_* などは一つも渡さない。渡すのは GIT_ENV の固定の値
        （PATH・LC_ALL と、利用者全体とシステム全体の設定を読まない指定）だけである。
      - --git-dir=<project>/.git と --work-tree=<project> を必ず付ける。<project>/.git は、
        シンボリックリンクでない既にあるフォルダでなければならない（.git がファイルの形の
        「gitdir:」で別の場所を指す場合も止まる）。
      - core.fsmonitor を切る（リポジトリの設定から外部のコマンドを動かさないため）。
    確かめないこと：git の実行ファイル（/usr/bin/git など、PATH の固定の値で見つかるもの）が
    本物であること。リポジトリの .git/config のうち、上で切った以外の設定。

------------------------------------------------------------------------
2. 未コミットの変更が無いこと（check_clean。T-015 の監査 軽2）
------------------------------------------------------------------------
    paths（例："src/collector"、"src/sealer"）の下について、次のどれかがあれば止まる。
      (a) git status に出る変更（ステージ済み・未ステージ・未追跡のファイル）
      (b) 無視されるファイル（.gitignore に当たるもの。__pycache__ の .pyc を含む）。
          Python は、-B を付けても既にある .pyc を読むことがあるので、無視されるファイルは
          取得のコードを差し替える経路になる
      (c) skip-worktree か assume-unchanged の印が付いたファイル（git ls-files -v の頭の字が
          "H" でないもの）。この印があると、作業ツリーの変更が git status に出ない
    そのうえで、files に挙げたファイルの作業ツリーの中身が、HEAD のコミットの中身と
    バイト単位で同じであることを確かめ、その中身を返す（committed_bytes）。

------------------------------------------------------------------------
3. プロジェクトの中の書き込み先（check_project_dirs。T-015 の監査 軽1・軽5）
------------------------------------------------------------------------
    sealed/、data/、data/manifest/ が、どれもシンボリックリンクでない既にあるフォルダで、
    realpath が <project の realpath>/sealed などと一致することを確かめる。リンクで別の
    場所の記録やマニフェストへ書かせないため。テストの差し替え（一時的なディレクトリの写し）
    でも、本番でも、同じ検査を通す。
    限界：確かめてから書くまでのあいだに、同じ利用者の別のプロセスがフォルダを差し替える
    競合は防げない。

外部のライブラリは使わない（Python 3 の標準ライブラリだけ）。
"""

import os
import stat
import subprocess

GIT_TIMEOUT_SECONDS = 60
# git に渡す環境変数（固定。呼び出し元の環境変数は使わない）。
GIT_ENV = {
    "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
    "LC_ALL": "C",
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_TERMINAL_PROMPT": "0",
    "GIT_OPTIONAL_LOCKS": "0",
}
PROJECT_DIRS = (("sealed",), ("data",), ("data", "manifest"))


class CodeGateError(Exception):
    """関門で止まった。何も書いていない。"""


def _real_dir(path, label):
    try:
        st = os.lstat(path)
    except OSError:
        raise CodeGateError("%s が無い" % label) from None
    if not stat.S_ISDIR(st.st_mode):
        raise CodeGateError("%s が、シンボリックリンクかフォルダでない" % label)


def git_dir_of(project):
    """<project>/.git が、リンクでないフォルダであることを確かめて返す。"""
    d = os.path.join(project, ".git")
    _real_dir(d, ".git（Git の作業ツリーでない）")
    return d


def run_git(project, *args):
    """git を固定の環境変数と --git-dir・--work-tree で実行する。返り値: (終了コード, 標準出力)。"""
    cmd = ["git", "--git-dir=" + git_dir_of(project), "--work-tree=" + project,
           "-c", "core.fsmonitor=false", "-C", project] + list(args)
    r = subprocess.run(cmd, capture_output=True, timeout=GIT_TIMEOUT_SECONDS, env=dict(GIT_ENV))
    return r.returncode, r.stdout


def committed_bytes(project, rel):
    """rel の作業ツリーの中身。HEAD のコミットの中身と同じでなければ CodeGateError。"""
    full = os.path.join(project, rel)
    try:
        st = os.lstat(full)
    except OSError:
        raise CodeGateError("取得のコードが無い: %s" % rel) from None
    if not stat.S_ISREG(st.st_mode):
        raise CodeGateError("取得のコードが通常のファイルでない: %s" % rel)
    with open(full, "rb") as f:
        work = f.read()
    code, head = run_git(project, "show", "HEAD:%s" % rel)
    if code != 0:
        raise CodeGateError("取得のコードが HEAD のコミットに無い: %s" % rel)
    if head != work:
        raise CodeGateError("取得のコードが HEAD のコミットの中身と違う: %s" % rel)
    return work


def _names(out):
    return sorted({e[3:].decode("utf-8", "replace") for e in out.split(b"\0") if e})


def check_clean(project, paths, files):
    """2章の (a)(b)(c) を確かめ、files の中身（{rel: バイト列}）を返す。"""
    code, out = run_git(project, "status", "--porcelain=v1", "-z", "--untracked-files=all",
                        "--ignored=matching", "--", *paths)
    if code != 0:
        raise CodeGateError("git status が失敗した（Git の作業ツリーでない）")
    entries = [e for e in out.split(b"\0") if e]
    ignored = [e for e in entries if e.startswith(b"!! ")]
    changed = [e for e in entries if not e.startswith(b"!! ")]
    if changed:
        raise CodeGateError("取得のコードに未コミットの変更がある: %s"
                            % ", ".join(_names(b"\0".join(changed))))
    if ignored:
        raise CodeGateError("取得のコードのフォルダに、無視されるファイルがある（.pyc など）: %s"
                            % ", ".join(_names(b"\0".join(ignored))))
    code, out = run_git(project, "ls-files", "-v", "-z", "--", *paths)
    if code != 0:
        raise CodeGateError("git ls-files が失敗した")
    marked = [e[2:].decode("utf-8", "replace") for e in out.split(b"\0")
              if e and not e.startswith(b"H ")]
    if marked:
        raise CodeGateError("skip-worktree か assume-unchanged の印が付いたファイルがある: %s"
                            % ", ".join(sorted(marked)))
    return {rel: committed_bytes(project, rel) for rel in files}


def check_project_dirs(project):
    """3章。sealed/・data/・data/manifest/ がリンクでないフォルダで、場所が正しいこと。"""
    real = os.path.realpath(project)
    for parts in PROJECT_DIRS:
        p = os.path.join(project, *parts)
        label = "/".join(parts) + "/"
        _real_dir(p, label)
        if os.path.realpath(p) != os.path.join(real, *parts):
            raise CodeGateError("%s の実際の場所がプロジェクトの下でない（途中にリンクがある）" % label)
