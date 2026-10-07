#!/usr/bin/env python3
"""順番1の封印の対象10件の sha256 を、作業ツリーと git の履歴から計算する（T-022）。

docs/stats/seal-order1.md の1章の表と、3章の照合の手順で使う。この表と手順は統計係の提案で、
封印は封印係が行う。封印係は、このスクリプトに頼らず自分のコードで計算し直す（2章の項目6）。
このスクリプトは、統計係のテスト（tests/stats/test_t019.py の test_seal_targets）と、封印のあとの
照合（3章）を、同じバイト列の定義で行うためのもの。

バイト列の定義（seal-order1.md 1章と同じ）
  - ファイル：作業ツリーのファイルのバイト列そのもの。
  - 「の出力」：プロジェクトのルートで `python3 -B <コード>` を引数なしで実行した標準出力。
  - `<commit>:<path>`：`git show <commit>:<path>` の標準出力。
  - 1cb463a の版の出力：そのファイルを一時のフォルダに取り出し、引数なしで実行した標準出力。

データは読まない。ネットワークは使わない。書くのは一時のフォルダ（tempfile。TMPDIR に従う）の中の
1cb463a の版の tagrules.py だけで、終われば消える。

使い方
  python3 -B src/stats/order1_digests.py
      {対象の名前: sha256} の JSON（キー順・UTF-8）を出力する
"""

import hashlib
import json
import os
import subprocess
import sys
import tempfile

PROJECT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

FILES = (
    "src/stats/exclusion.py",
    "tests/stats/test_exclusion.py",
    "src/stats/tagrules.py",
    "tests/stats/test_tagrules.py",
    "docs/stats/tags-naive.md",
)
OUTPUTS = ("src/stats/exclusion.py", "src/stats/tagrules.py")
OLD_TAGRULES = "1cb463a:src/stats/tagrules.py"
OWNER_RECORD = "2d23cdf:reviews/T-020.md"


class DigestError(Exception):
    pass


def _env():
    return dict(os.environ, PYTHONDONTWRITEBYTECODE="1")


def git_show(spec, project=PROJECT):
    r = subprocess.run(["git", "show", spec], capture_output=True, cwd=project)
    if r.returncode != 0:
        raise DigestError("git show %s に失敗：%s" % (spec, r.stderr.decode("utf-8", "replace")))
    return r.stdout


def run_output(rel, project=PROJECT):
    r = subprocess.run([sys.executable, "-B", os.path.join(project, rel)], capture_output=True,
                       env=_env(), cwd=project)
    if r.returncode != 0:
        raise DigestError("%s の実行に失敗：%s" % (rel, r.stderr.decode("utf-8", "replace")))
    return r.stdout


def run_old_output(code_bytes):
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "tagrules.py")
        with open(path, "wb") as f:
            f.write(code_bytes)
        r = subprocess.run([sys.executable, "-B", path], capture_output=True, env=_env(), cwd=d)
    if r.returncode != 0:
        raise DigestError("1cb463a の版の実行に失敗：%s" % r.stderr.decode("utf-8", "replace"))
    return r.stdout


def target_bytes(project=PROJECT):
    """対象の名前（seal-order1.md の表の左の欄）からバイト列への dict。"""
    out = {}
    for rel in FILES:
        with open(os.path.join(project, rel), "rb") as f:
            out[rel] = f.read()
    for rel in OUTPUTS:
        out[rel + " の出力"] = run_output(rel, project)
    old = git_show(OLD_TAGRULES, project)
    out[OLD_TAGRULES] = old
    out[OLD_TAGRULES + " の出力"] = run_old_output(old)
    out[OWNER_RECORD] = git_show(OWNER_RECORD, project)
    return out


def digests(project=PROJECT):
    return {k: hashlib.sha256(v).hexdigest() for k, v in target_bytes(project).items()}


def main(argv=None):
    if argv is None:
        argv = sys.argv[1:]
    if argv:
        sys.stderr.write("order1_digests: 引数は取らない\n")
        return 2
    try:
        d = digests()
    except DigestError as e:
        sys.stderr.write("order1_digests: %s\n" % e)
        return 1
    sys.stdout.write(json.dumps(d, ensure_ascii=False, sort_keys=True, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
