#!/usr/bin/env python3
"""試運転の手順4：手法を作る期間の GKG を取得して集計する入口のスクリプト（T-018。実行は別のタスク）。

データ出典
    Data: The GDELT Project (https://www.gdeltproject.org/). This project is not
    affiliated with or endorsed by the GDELT Project.
    データ出典：GDELT Project（https://www.gdeltproject.org/）。本プロジェクトは
    GDELT Project と提携・承認の関係にありません。

使い方（プロジェクトのルートで。引数は受け付けない。手順の全体は src/collector/README.md）
    env -u GIT_DIR -u GIT_WORK_TREE -u PYTHONPATH PYTHONDONTWRITEBYTECODE=1 \\
        .venv/bin/python -I -B src/collector/acquire_gkg.py
    終了コード  0: 全部の日が終わった（マニフェストに run-complete）
                1: 関門で止まった（何も書いていない）
                3: 止まる条件（gkg.py 5章）で止まった。同じコードでもう一度実行すると続きから再開する

このスクリプトがすること（この順。途中で止まれば、それより後のことはしない）
    0. 最初に ledger.require_method_access() を引数なしで呼ぶ（T-014）。鎖に method-access の
       記録が無いか、検証に通らなければ、ほかのことを何もせずに止まる。
    1. 関門（check_gate）。ネットワークは使わない。どれか1つでも欠ければ GateError で止まり、
       何も書かない。
         (1) method-access の記録の中身の区画が、gkg.METHOD_BLOCK（2015-03-02〜2020-12-14）と同じ
         (2) codegate.py の sha256 が PINNED_SHA256 と一致し、src/collector・src/sealer に未コミット
             の変更・無視されるファイル・skip-worktree などの印が無い。入口・gkg.py・filelist.py・
             privacy_scan.py・codegate.py の中身が HEAD と同じで、PINNED_SHA256 と一致する
             （codegate.py の docstring）。sealed/・data/manifest/ がリンクでない
         (3) ファイル一覧：data/manifest/gdelt-filelist.jsonl がちょうど1行で、その sha256 が、
             封印の記録のただ1件の acquisition-result の kept_rows_sha256 と同じ。その行の
             acquisition_start_seq が、result の start_seq と同じ。保存先の本体を O_NOFOLLOW で
             読み、sha256 が同じ
         (4) 保存先 ~/Desktop/news-stick-data/gkg-method がリンクでない既にあるフォルダ
    2. gkg.py を、関門で照合したバイト列そのものとして読み込み、3つのファイルを読み直して
       変わっていないことを確かめる。
    3. gkg.run_gkg を1回動かす（取得・集計・保存・マニフェスト。gkg.py の docstring）。

固定するもの（本番では差し替えを受け付けない）
    - main() は引数を受け付けない。プロジェクトのルートは、このファイルの置き場所から決める。
      ホームは環境変数 HOME ではなく利用者のデータベース（pwd）から決める。
    - テストのための差し替えは _acquire(_test=_TestSeams(...)) からだけ渡せる。project と home は
      一時的なディレクトリの下に限り、本物のプロジェクト・ホームを指せない。写しの中の sealed/・
      data/・data/manifest/ がリンクのときも拒む。関門 ledger.require_method_access() は、
      本番でもテストでも引数なしで呼ぶ（T-017 で関門は引数を取らなくなった）。関門が読む
      ledger.PROJECT_ROOT と、このスクリプトが使う project の実際の場所が違えば止まる
      （テストは ledger.PROJECT_ROOT を写しに差し替える）。
    - このファイルのコードは os.environ を読まない。git には環境変数を渡さない（codegate.py）。
      Python の処理系そのものの環境変数の影響を避けるため、上の使い方のとおり -I で実行する。

取得のコードのハッシュの範囲
    マニフェストの行の code_sha256 は、このファイルの sha256 である。このファイルは
    gkg.py・filelist.py・privacy_scan.py・codegate.py の sha256 を PINNED_SHA256 に固定するので、
    この1つの値で取得のコードの5つのファイルが決まる。範囲の外：src/sealer の封印の仕組み
    （関門で未コミットの変更が無いことだけを確かめる）、Python の処理系。

限界
    - 関門は、正直な運用で手順を飛ばす誤りを防ぐためのもので、証明ではない。このスクリプトを
      使わずに GKG に触れることは、記録からは検出できない（ledger.require_method_access の注記）。
    - 再開する時機は人が決める（gkg.py 5章）。
"""

import datetime
import hashlib
import os
import pwd
import stat
import subprocess
import sys
import tempfile
import time
import types

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(os.path.dirname(HERE))
SEALER_DIR = os.path.join(PROJECT, "src", "sealer")
sys.path.insert(0, SEALER_DIR)

import ledger  # noqa: E402

CODE_REL = "src/collector/acquire_gkg.py"
GKG_REL = "src/collector/gkg.py"
FILELIST_REL = "src/collector/filelist.py"
PRIVACY_SCAN_REL = "src/collector/privacy_scan.py"
CODEGATE_REL = "src/collector/codegate.py"

# 取得のコードのうち、このファイル以外の4つの sha256。変えたらここも直してコミットする
# （テストが照合する）。
PINNED_SHA256 = (
    (GKG_REL, "7ad15493002af9579335056289d0f7ba65ca6361e6c047695cdfd1511d9476a7"),
    (FILELIST_REL, "afd7a9dd47bc052a691e1a4cd558b211f4d72cf1ce1f451fa9f3016540cd04a7"),
    (PRIVACY_SCAN_REL, "68d8836d56489ca5df9f2f55e24a2642ebf3aa14afdc2e0120577c7b6c6cb887"),
    (CODEGATE_REL, "945adb339c6c38585d331546d61c940a1862d53f7f94e3db8aec63da4ce107c4"),
)
CLEAN_PATHS = ("src/collector", "src/sealer")
FILELIST_MANIFEST_REL = ("data", "manifest", "gdelt-filelist.jsonl")


class GateError(Exception):
    """関門で止まった。何も書いていない。"""


def _sha256(data):
    return hashlib.sha256(data).hexdigest()


def production_home():
    return pwd.getpwuid(os.getuid()).pw_dir


# ---------------------------------------------------------------------------
# 差し替え（テストだけ）
# ---------------------------------------------------------------------------

class _Seams:
    FIELDS = ("project", "home", "transport", "sleep", "clock", "now", "log", "disk_free")
    __slots__ = FIELDS

    def __init__(self, **kw):
        for k in _Seams.FIELDS:
            object.__setattr__(self, k, kw.pop(k))
        if kw:
            raise TypeError("知らない部品: %s" % ", ".join(sorted(kw)))

    def __setattr__(self, k, v):
        raise AttributeError("部品は作ったあとで変えられない")


def _utc_now():
    return datetime.datetime.now(datetime.timezone.utc)


def _production_seams():
    return _Seams(project=PROJECT, home=production_home(), transport=None, sleep=time.sleep,
                  clock=time.monotonic, now=_utc_now, log=None, disk_free=None)


class _TestSeams(_Seams):
    __slots__ = ()


def _under_tmp(path):
    tmp = os.path.realpath(tempfile.gettempdir())
    real = os.path.realpath(path)
    return real != tmp and os.path.commonpath([tmp, real]) == tmp


def _checked_test_seams(t):
    if type(t) is not _TestSeams:
        raise TypeError("_test には _TestSeams だけを渡せる")
    for label, p in (("project", t.project), ("home", t.home)):
        if not _under_tmp(p):
            raise ValueError("テストの %s は、一時的なディレクトリの下でなければならない" % label)
    if os.path.realpath(t.project) == os.path.realpath(PROJECT):
        raise ValueError("テストの project が本物のプロジェクトを指している")
    if os.path.realpath(t.home) == os.path.realpath(production_home()):
        raise ValueError("テストの home が本物のホームを指している")
    for parts in (("sealed",), ("data",), ("data", "manifest")):
        p = os.path.join(t.project, *parts)
        if os.path.islink(p) or not _under_tmp(os.path.realpath(p)):
            raise ValueError("テストの project の %s が、リンクか一時的なディレクトリの外を指す"
                             % "/".join(parts))
    return t


def _method_access_gate(s):
    """手順0。関門を引数なしで呼ぶ。関門が読んだプロジェクトと s.project が同じであることも確かめる。"""
    rec = ledger.require_method_access()
    if os.path.realpath(ledger.PROJECT_ROOT) != os.path.realpath(s.project):
        raise GateError("関門が読んだプロジェクトと、取得に使うプロジェクトが違う")
    return rec


# ---------------------------------------------------------------------------
# 関門
# ---------------------------------------------------------------------------

def _exec_module(name, path, source):
    mod = types.ModuleType(name)
    mod.__file__ = path
    exec(compile(source, path, "exec"), mod.__dict__)
    return mod


def _load_codegate(project):
    path = os.path.join(project, CODEGATE_REL)
    try:
        st = os.lstat(path)
    except OSError:
        raise GateError("取得のコードが無い: %s" % CODEGATE_REL) from None
    if not stat.S_ISREG(st.st_mode):
        raise GateError("取得のコードが通常のファイルでない: %s" % CODEGATE_REL)
    with open(path, "rb") as f:
        source = f.read()
    if _sha256(source) != dict(PINNED_SHA256)[CODEGATE_REL]:
        raise GateError("%s の sha256 が、入口のスクリプトに固定した値と違う" % CODEGATE_REL)
    return _exec_module("codegate", path, source), source


def _check_code(project):
    cg, cg_source = _load_codegate(project)
    try:
        codes = cg.check_clean(project, CLEAN_PATHS, (CODE_REL,) + tuple(r for r, _ in
                                                                          PINNED_SHA256))
        cg.check_project_dirs(project)
    except cg.CodeGateError as e:
        raise GateError(str(e)) from None
    except (OSError, subprocess.SubprocessError):
        raise GateError("git の実行に失敗した") from None
    if codes[CODEGATE_REL] != cg_source:
        raise GateError("関門のあいだに取得のコードが変わった: %s" % CODEGATE_REL)
    for rel, want in PINNED_SHA256:
        if _sha256(codes[rel]) != want:
            raise GateError("%s の sha256 が、入口のスクリプトに固定した値と違う" % rel)
    return codes


def _read_nofollow(path, what):
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    except OSError:
        raise GateError("%s を開けない（無いか、シンボリックリンク）" % what) from None
    with os.fdopen(fd, "rb") as f:
        if not stat.S_ISREG(os.fstat(f.fileno()).st_mode):
            raise GateError("%s が通常のファイルでない" % what)
        return f.read()


def _check_filelist(project, home, gkg):
    """関門 (3)。返り値: (行の list, sha256)。"""
    import json
    import re
    try:
        data = ledger.read_ledger(os.path.join(project, "sealed", "ledger.jsonl"))
        records = ledger.verify_chain(data)
        results = [r for _v, r in ledger.records_of_kind(records, ledger.ACQ_RESULT_KIND)]
        if len(results) != 1:
            raise GateError("acquisition-result の記録がちょうど1件でない（どの一覧を使うかを"
                            "決められない）")
        doc = ledger.read_target_json(project, results[0], ledger.ACQ_RESULT_KIND)
    except ledger.LedgerError as e:
        raise GateError("封印の記録を読めない: %s" % e) from None
    raw = _read_nofollow(os.path.join(project, *FILELIST_MANIFEST_REL), "ファイル一覧のマニフェスト")
    lines = [l for l in raw.splitlines() if l.strip()]
    if len(lines) != 1:
        raise GateError("ファイル一覧のマニフェストがちょうど1行でない")
    entry = json.loads(lines[0])
    name = entry.get("file_name", "")
    if not re.fullmatch(r"masterfilelist-kept-\d{8}T\d{6}Z\.tsv", name):
        raise GateError("ファイル一覧のマニフェストの file_name が決めた形でない")
    if entry.get("sha256") != doc.get("kept_rows_sha256"):
        raise GateError("ファイル一覧のマニフェストの sha256 が、acquisition-result と違う")
    if entry.get("acquisition_start_seq") != doc.get("start_seq"):
        raise GateError("ファイル一覧のマニフェストの acquisition_start_seq が、result と違う")
    body = _read_nofollow(os.path.join(home, *gkg.FILELIST_STORE_PARTS, name), "ファイル一覧の本体")
    sha = _sha256(body)
    if sha != entry["sha256"]:
        raise GateError("ファイル一覧の本体の sha256 が、マニフェストと違う")
    try:
        rows = gkg.parse_filelist(body)
    except gkg.GkgError as e:
        raise GateError(str(e)) from None
    return rows, sha


def check_gate(s, method_rec, gkg_loader=None):
    """関門 (1)〜(4)。通れば dict を返す。"""
    try:
        doc = ledger.read_target_json(s.project, method_rec, ledger.METHOD_ACCESS_KIND)
    except ledger.LedgerError as e:
        raise GateError("method-access の中身を読めない: %s" % e) from None
    codes = _check_code(s.project)
    gkg = _exec_module("gkg", os.path.join(s.project, GKG_REL), codes[GKG_REL])
    if (doc.get("block_start"), doc.get("block_end")) != gkg.METHOD_BLOCK:
        raise GateError("method-access の区画が、gkg.METHOD_BLOCK と違う")
    rows, fl_sha = _check_filelist(s.project, s.home, gkg)
    try:
        gkg.resolve_paths(s.project, s.home)
    except gkg.GkgError as e:
        raise GateError(str(e)) from None
    for rel, data in codes.items():
        with open(os.path.join(s.project, rel), "rb") as f:
            if f.read() != data:
                raise GateError("関門のあとで取得のコードが変わった: %s" % rel)
    return {"codes": codes, "code_sha256": _sha256(codes[CODE_REL]), "gkg": gkg,
            "filelist_rows": rows, "filelist_sha256": fl_sha, "method_access_seq":
            method_rec["seq"]}


# ---------------------------------------------------------------------------
# 本体
# ---------------------------------------------------------------------------

def _acquire(_test=None):
    """手順0 → 関門 → 取得。_test はテストだけが渡す（_TestSeams）。"""
    s = _production_seams() if _test is None else _checked_test_seams(_test)
    method_rec = _method_access_gate(s)
    gate = check_gate(s, method_rec)
    gkg = gate["gkg"]
    kw = {}
    for name in ("transport", "log", "disk_free"):
        v = getattr(s, name)
        if v is not None:
            kw[name] = v
    return gkg.run_gkg(root=s.project, home=s.home, filelist_rows=gate["filelist_rows"],
                       filelist_sha256=gate["filelist_sha256"],
                       method_access_seq=gate["method_access_seq"],
                       code_sha256=gate["code_sha256"], sleep=s.sleep, clock=s.clock,
                       now=s.now, **kw)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else list(argv)
    if argv:
        print("引数は受け付けない。手順は src/collector/README.md", file=sys.stderr)
        return 2
    try:
        out = _acquire()
    except ledger.MethodAccessRequired as e:
        print("関門で止まった（何も書いていない）: %s" % e, file=sys.stderr)
        return 1
    except GateError as e:
        print("関門で止まった（何も書いていない）: %s" % e, file=sys.stderr)
        return 1
    except Exception as e:
        if type(e).__name__ == "RunInterrupted":
            print("止まった（同じコードで再実行すると再開する）: %s" % e, file=sys.stderr)
            return 3
        raise
    print("run_id: %s 日数: %d ok: %d failed: %d" % (out["run_id"], out["days"], out["files_ok"],
                                                    out["files_failed"]))
    print("データ出典：GDELT Project（https://www.gdeltproject.org/）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
