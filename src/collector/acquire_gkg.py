#!/usr/bin/env python3
"""試運転の手順4：手法を作る期間の GKG を取得して集計する入口のスクリプト（T-018・T-021。実行は別のタスク）。

データ出典
    Data: The GDELT Project (https://www.gdeltproject.org/). This project is not
    affiliated with or endorsed by the GDELT Project.
    データ出典：GDELT Project（https://www.gdeltproject.org/）。本プロジェクトは
    GDELT Project と提携・承認の関係にありません。

使い方（プロジェクトのルートで。手順の全体は src/collector/README.md）
    正式な run（引数なし）
      env -u GIT_DIR -u GIT_WORK_TREE -u PYTHONPATH PYTHONDONTWRITEBYTECODE=1 \\
          .venv/bin/python -I -B src/collector/acquire_gkg.py
    試しの run（gkg.py 5.1章。引数は --trial の1つだけ）
      env -u GIT_DIR -u GIT_WORK_TREE -u PYTHONPATH PYTHONDONTWRITEBYTECODE=1 \\
          .venv/bin/python -I -B src/collector/acquire_gkg.py --trial
    ほかの引数は受け付けない（終了コード 2。何もしない）。
    終了コード  0: 全部の日が終わった（マニフェストに run-complete）
                1: 関門で止まった（何も書いていない）。または gkg.GkgError で止まった（run-start が
                   コミットされていない場合は、要求を送る前に止まり、何も書いていない）
                2: 引数が違う（何もしない）
                3: 止まる条件（gkg.py 5章）で止まった。同じコードでもう一度実行すると続きから再開する
                4: 正式な run の run-start を書いて止まった（GKG にはまだ要求を送っていない）。
                   マニフェストをコミットしてから（リモートがあれば push も）、同じコマンドで
                   もう一度実行する
                   （gkg.py 5章。T-018 の監査 軽2）

このスクリプトがすること（この順。途中で止まれば、それより後のことはしない）
    000. 最初に、コードの関門（下の 1 の (2)。_check_code）を通す（差し戻し2回目 軽-2。
       除外の規則の関門が読み込む themes.py・ledger.py を含め、固定したコードで動くことを先に
       確かめる）。ただし ledger.py は、このファイルを読み込んだ時点で既に読み込まれている。
    00. 次に、除外の規則の封印の関門（themes.require_exclusion_rules_sealed。区分表の取得と
       同じ関門）を通す（T-021 の差し戻し1回目 重1。試しの run と正式な run の両方）。GKG の
       集計にはテーマの名前と件数が出るので、除外の規則の封印より前には取得しない。themes.py は
       手順000 で HEAD と PINNED_SHA256 に照らしたバイト列から読み込む。関門が返した記録の seq と
       sha256 を gkg.run_gkg に渡し、run-start に書く。gkg.run_gkg の中でも鎖の上の記録と照らす。**封印係の kind が未決のあいだは、
       ここで必ず止まる（GKG も取得しない）。** ledger の側の検査（method-access より前に除外の
       規則の封印があること）は、封印係の別のタスクで行う。
    0. 次に ledger.require_method_access() を引数なしで呼ぶ（T-014）。鎖に method-access の
       記録が無いか、検証に通らなければ、ほかのことを何もせずに止まる。
    1. 関門（check_gate）。ネットワークは使わない。どれか1つでも欠ければ GateError で止まり、
       何も書かない。
         (1) method-access の記録の中身の区画が、gkg.METHOD_BLOCK（2015-03-02〜2020-12-14）と同じ
         (2) codegate.py の sha256 が PINNED_SHA256 と一致し、src/collector・src/sealer に未コミット
             の変更・無視されるファイル・skip-worktree などの印が無い。入口・gkg.py・filelist.py・
             privacy_scan.py・codegate.py・themes.py の中身が HEAD と同じで、PINNED_SHA256 と一致する
             （codegate.py の docstring）。sealed/・data/manifest/ がリンクでない
         (3) ファイル一覧：data/manifest/gdelt-filelist.jsonl がちょうど1行で、その sha256 が、
             封印の記録のただ1件の acquisition-result の kept_rows_sha256 と同じ。その行の
             acquisition_start_seq が、result の start_seq と同じ。保存先の本体を O_NOFOLLOW で
             読み、sha256 が同じ
         (4) 保存先（gkg.py 7章。正式な run は LACIE SHARE の news-stick-data/gkg-method、
             試しの run は news-stick-data/gkg-trial）：ディスクがマウントされていて読み取り
             専用でなく、2段のフォルダがリンクでない既にあるフォルダで、名前の大文字と小文字
             まで同じ（gkg.resolve_paths）。外れていれば、何も書かずに止まる。
             さらに diskutil でディスクの形式を読み、msdos（FAT32）でなければ止まる。形式は
             どの記録にも書かない。VolumeUUID は取り出さない・書かない（オーナーの決定。ディスクの
             同一性は、保存先の中の印のファイルで確かめる。gkg.py 5.2章）
         (5) 正式な run では、HEAD のコミットの中のマニフェスト（data/manifest/
             gdelt-gkg-method.jsonl と gdelt-gkg-trial.jsonl。無ければ空）を git から読み、
             gkg.run_gkg に渡す。run-start がコミットされていなければ、また試しの run の
             マニフェストが全部コミットされていなければ、gkg.run_gkg が要求を送る前に止まる
    2. gkg.py を、関門で照合したバイト列そのものとして読み込み、3つのファイルを読み直して
       変わっていないことを確かめる。
    （3 の中で）run の最初の実行（マニフェストに run-start の行を書く実行）では、gkg.run_gkg が、run-start の
       行を書く前・要求を送る前に、封印係の seal_gkg_run.start で封印の記録に gkg-run-start を
       書く（make_start_hook。T-032）。drand と OpenTimestamps の通信を使う。書けなければ、
       何も書かずに止まり、要求は1件も送らない。同じ run の再開と、正式な run の2回目の実行では
       書かない。
    3. gkg.run_gkg を1回動かす（取得・集計・保存・マニフェスト。gkg.py の docstring）。

固定するもの（本番では差し替えを受け付けない）
    - main() が受け付ける引数は --trial だけ。プロジェクトのルートは、このファイルの置き場所から
      決める。ホーム（ファイル一覧の本体の置き場所）は環境変数 HOME ではなく利用者の
      データベース（pwd）から決める。保存先のディスクは gkg.VOLUME_MOUNT に固定する。
    - テストのための差し替えは _acquire(_test=_TestSeams(...)) からだけ渡せる。project と home は
      一時的なディレクトリの下に限り、本物のプロジェクト・ホーム・保存先のディスク
      （/Volumes の下）を指せない。写しの中の sealed/・
      data/・data/manifest/ がリンクのときも拒む。関門 ledger.require_method_access() は、
      本番でもテストでも引数なしで呼ぶ（T-017 で関門は引数を取らなくなった）。関門が読む
      ledger.PROJECT_ROOT と、このスクリプトが使う project の実際の場所が違えば止まる
      （テストは ledger.PROJECT_ROOT を写しに差し替える）。
    - このファイルのコードは os.environ を読まない。git には環境変数を渡さない（codegate.py）。
      Python の処理系そのものの環境変数の影響を避けるため、上の使い方のとおり -I で実行する。

取得のコードのハッシュの範囲
    マニフェストの行の code_sha256 は、このファイルの sha256 である。このファイルは
    gkg.py・filelist.py・privacy_scan.py・codegate.py・themes.py の sha256 を PINNED_SHA256 に固定
    するので、この1つの値で取得のコードの6つのファイルが決まる。範囲の外：src/sealer の封印の仕組み
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
import seal_gkg_run  # noqa: E402  （T-032：run の開始を封印の記録に書く。src/sealer の入口）
import stamp  # noqa: E402

CODE_REL = "src/collector/acquire_gkg.py"
GKG_REL = "src/collector/gkg.py"
FILELIST_REL = "src/collector/filelist.py"
PRIVACY_SCAN_REL = "src/collector/privacy_scan.py"
CODEGATE_REL = "src/collector/codegate.py"
THEMES_REL = "src/collector/themes.py"
DISKUTIL = "/usr/sbin/diskutil"
DISKUTIL_TIMEOUT_SECONDS = 60

# 取得のコードのうち、このファイル以外の5つ（gkg.py・filelist.py・privacy_scan.py・codegate.py・
# themes.py）の sha256。変えたらここも直してコミットする（テストが照合する）。
PINNED_SHA256 = (
    (GKG_REL, "d2b85960d23db8ca96ef01fd8de19b5254cd026753e9ef774f6e5d6efe594dc2"),
    (FILELIST_REL, "afd7a9dd47bc052a691e1a4cd558b211f4d72cf1ce1f451fa9f3016540cd04a7"),
    (PRIVACY_SCAN_REL, "68d8836d56489ca5df9f2f55e24a2642ebf3aa14afdc2e0120577c7b6c6cb887"),
    (CODEGATE_REL, "d422be41dc59c4be50689a2426453db965be506a9981770ab3eb7557ed078769"),
    (THEMES_REL, "903ab2cafb02a739006e8167319127692fa762f1560662d3f5f6e89caa902086"),
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
    FIELDS = ("project", "home", "volume", "transport", "sleep", "clock", "now", "log", "disk_free",
              "check_volume", "fs_check", "drand_fetch", "ots_cmd", "ots_runner")
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
    return _Seams(project=PROJECT, home=production_home(), volume=None, transport=None,
                  sleep=time.sleep, clock=time.monotonic, now=_utc_now, log=None, disk_free=None,
                  check_volume=None, fs_check=None, drand_fetch=None, ots_cmd=stamp.DEFAULT_OTS,
                  ots_runner=subprocess.run)


class _TestSeams(_Seams):
    __slots__ = ()


def _under_tmp(path):
    tmp = os.path.realpath(tempfile.gettempdir())
    real = os.path.realpath(path)
    return real != tmp and os.path.commonpath([tmp, real]) == tmp


def _checked_test_seams(t):
    if type(t) is not _TestSeams:
        raise TypeError("_test には _TestSeams だけを渡せる")
    for label, p in (("project", t.project), ("home", t.home), ("volume", t.volume)):
        if not isinstance(p, str) or not _under_tmp(p):
            raise ValueError("テストの %s は、一時的なディレクトリの下でなければならない" % label)
    vreal = os.path.realpath(t.volume)
    if vreal == "/Volumes" or vreal.startswith("/Volumes/"):
        raise ValueError("テストの volume が /Volumes の下（本物のディスク）を指している")
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


def _exclusion_gate(s, codes):
    """手順00（重1）。区分表の取得と同じ、除外の規則の封印の関門。通らなければ GateError。

    themes.py は、手順000 のコードの関門で HEAD と PINNED_SHA256 に照らしたバイト列（codes）から
    読み込む。返り値：除外の規則の封印の記録の {"seq", "record_sha256"}（run-start に書く。中-B）。
    """
    themes = _exec_module("themes", os.path.join(s.project, THEMES_REL), codes[THEMES_REL])
    try:
        rec, root = themes.require_exclusion_rules_sealed()
    except themes.ThemesError as e:
        raise GateError("除外の規則の封印の関門：%s" % e) from None
    if os.path.realpath(root) != os.path.realpath(s.project):
        raise GateError("除外の規則の関門が読んだプロジェクトと、取得に使うプロジェクトが違う")
    return themes.exclusion_rule_ref(rec)


def check_filesystem(volume):
    """関門 (4)。diskutil でディスクの形式だけを読み、msdos（FAT32）でなければ止まる。

    diskutil の出力のうち、FilesystemType だけを見る。ほかの値（VolumeUUID など）は取り出さず、
    どこにも書かない（オーナーの決定「記録に残さず、公開もしない」）。
    """
    import plistlib
    try:
        r = subprocess.run([DISKUTIL, "info", "-plist", volume], capture_output=True,
                           timeout=DISKUTIL_TIMEOUT_SECONDS, env={"PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
                                                                  "LC_ALL": "C"})
        info = plistlib.loads(r.stdout) if r.returncode == 0 else None
    except (OSError, subprocess.SubprocessError, ValueError):
        info = None
    if not isinstance(info, dict):
        raise GateError("保存先のディスクの情報を diskutil で読めない")
    fs = info.get("FilesystemType")
    del info
    if fs != "msdos":
        raise GateError("保存先のディスクの形式が msdos（FAT32）でない")


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
    """返り値: (codes, codegate のモジュール)。"""
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
    return codes, cg


def _committed_manifest(cg, project, rel):
    """関門 (5)。rel の HEAD のコミットの中のバイト列。HEAD に無ければ b""。"""
    try:
        code, _out = cg.run_git(project, "cat-file", "-e", "HEAD:%s" % rel)
        if code != 0:
            return b""
        code, out = cg.run_git(project, "cat-file", "blob", "HEAD:%s" % rel)
    except cg.CodeGateError as e:
        raise GateError(str(e)) from None
    except (OSError, subprocess.SubprocessError):
        raise GateError("git の実行に失敗した") from None
    if code != 0:
        raise GateError("HEAD のコミットの中のマニフェストを読めない")
    return out


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


def check_gate(s, method_rec, mode="official", code=None):
    """関門 (1)〜(5)。通れば dict を返す。code は手順000 の _check_code の返り値。"""
    try:
        doc = ledger.read_target_json(s.project, method_rec, ledger.METHOD_ACCESS_KIND)
    except ledger.LedgerError as e:
        raise GateError("method-access の中身を読めない: %s" % e) from None
    codes, cg = _check_code(s.project) if code is None else code
    gkg = _exec_module("gkg", os.path.join(s.project, GKG_REL), codes[GKG_REL])
    if (doc.get("block_start"), doc.get("block_end")) != gkg.METHOD_BLOCK:
        raise GateError("method-access の区画が、gkg.METHOD_BLOCK と違う")
    rows, fl_sha = _check_filelist(s.project, s.home, gkg)
    volume = gkg.VOLUME_MOUNT if s.volume is None else s.volume
    check_volume = gkg.check_volume if s.check_volume is None else s.check_volume
    try:
        gkg.resolve_paths(s.project, volume, mode, check_volume)
    except gkg.GkgError as e:
        raise GateError(str(e)) from None
    (check_filesystem if s.fs_check is None else s.fs_check)(volume)
    committed = committed_trial = None
    if mode == "official":
        committed = _committed_manifest(
            cg, s.project, "/".join(gkg.MANIFEST_DIR_PARTS + (gkg.MANIFEST_NAME,)))
        committed_trial = _committed_manifest(
            cg, s.project, "/".join(gkg.MANIFEST_DIR_PARTS + (gkg.TRIAL_MANIFEST_NAME,)))
    for rel, data in codes.items():
        with open(os.path.join(s.project, rel), "rb") as f:
            if f.read() != data:
                raise GateError("関門のあとで取得のコードが変わった: %s" % rel)
    return {"codes": codes, "code_sha256": _sha256(codes[CODE_REL]), "gkg": gkg,
            "filelist_rows": rows, "filelist_sha256": fl_sha, "method_access_seq":
            method_rec["seq"], "volume": volume, "check_volume": check_volume,
            "committed_manifest": committed, "committed_trial_manifest": committed_trial}


# ---------------------------------------------------------------------------
# 本体
# ---------------------------------------------------------------------------

def record_ref(rec):
    """封印の記録の {"seq", "record_sha256"}（記録の行の正規の形の sha256）。"""
    return {"seq": rec["seq"], "record_sha256": ledger.sha256_hex(ledger.canonical_line(rec))}


def plan_of_gate(gate, mode):
    """T-071：関門で封印済みと照らしたファイル一覧の行から作った取得の計画の
    (日の数, ファイルの数, plan_sha256)。計画は gkg.select_files の出力（試しの run は gkg.trial_plan の
    あと）、plan_sha256 は ledger.gkg_plan_sha256(計画)。"""
    gkg = gate["gkg"]
    plan = gkg.select_files(gate["filelist_rows"])
    if mode == "trial":
        plan = gkg.trial_plan(plan)
    return len(plan), sum(len(v) for v in plan.values()), ledger.gkg_plan_sha256(plan)


def make_start_hook(s, gate, exclusion_rule):
    """手順3a（T-032・T-045）：gkg.run_gkg が run の最初の実行で呼ぶ。封印係の seal_gkg_run.start で
    gkg-run-start を封印の記録に書き、その記録の {"seq", "record_sha256"} を返す。

    常に seal_gkg_run.start を呼ぶ（T-045。T-043 の監査 軽-C）。同じ mode・run_id の記録が既に
    あるときに使い回すかどうかの判断と照合（入力がすべて同じ・run-start の行がまだ無い・.ots が
    ある・trial なら official がまだ無い）は、start に任せる。このスクリプトは自分で使い回さない。
    書けなければ（使い回せない場合を含む）例外を出し、gkg.run_gkg は何も書かずに止まる
    （要求を1件も送らない）。
    T-069：取得の計画（days・files_selected。gkg.py が run-start の行に書く値と同じ）も、試しの run・
    正式な run のどちらでも start に渡す（封印係の T-068）。
    T-071：計画の一覧の sha256（plan_sha256）も、試しの run・正式な run のどちらでも start に渡す
    （封印係の T-070）。計画は、関門で封印済みと照らしたファイル一覧の行（gate["filelist_rows"]）から
    gkg.select_files で作ったもの（試しの run は gkg.trial_plan のあと）。plan_sha256 は
    ledger.gkg_plan_sha256(計画) で、gkg.run_gkg が run-start の行に書く値と同じ。計画の本体は
    どこにも書かない。hook は、関門で照らした一覧から計画を自分でも作り直し、gkg.run_gkg から
    受け取った days・files_selected・plan_sha256 と同じことを確かめてから start を呼ぶ（違えば
    GateError。何も書かない）。
    """
    def hook(*, mode, run_id, trial_days, days, files_selected, plan_sha256):
        want = plan_of_gate(gate, mode)
        if (days, files_selected, plan_sha256) != want:
            raise GateError("取得の計画（days・files_selected・plan_sha256）が、関門で照らしたファイル"
                            "一覧から作り直した計画と違う")
        rec, _rel, _ots = seal_gkg_run.start(
            s.project, mode, CODE_REL, run_id, gate["filelist_sha256"],
            gate["method_access_seq"], trial_days, exclusion_rule["seq"],
            exclusion_rule["record_sha256"], s.now(), s.ots_cmd, drand_fetch=s.drand_fetch,
            runner=s.ots_runner, days=days, files_selected=files_selected, plan_sha256=plan_sha256)
        return record_ref(rec)
    return hook


def _acquire(mode="official", _test=None):
    """手順00 → 手順0 → 関門 → 取得。mode は official か trial。_test はテストだけが渡す。"""
    s = _production_seams() if _test is None else _checked_test_seams(_test)
    code = _check_code(s.project)
    exclusion_rule = _exclusion_gate(s, code[0])
    method_rec = _method_access_gate(s)
    if mode not in ("official", "trial"):
        raise ValueError("mode は official か trial だけ")
    gate = check_gate(s, method_rec, mode, code)
    gkg = gate["gkg"]
    kw = {}
    for name in ("transport", "log", "disk_free"):
        v = getattr(s, name)
        if v is not None:
            kw[name] = v
    return gkg.run_gkg(root=s.project, volume=gate["volume"], mode=mode,
                       filelist_rows=gate["filelist_rows"],
                       filelist_sha256=gate["filelist_sha256"],
                       method_access_seq=gate["method_access_seq"],
                       code_sha256=gate["code_sha256"],
                       committed_manifest=gate["committed_manifest"],
                       committed_trial_manifest=gate["committed_trial_manifest"],
                       exclusion_rule=exclusion_rule,
                       start_hook=make_start_hook(s, gate, exclusion_rule),
                       check_volume=gate["check_volume"], sleep=s.sleep, clock=s.clock,
                       now=s.now, **kw)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else list(argv)
    if argv == []:
        mode = "official"
    elif argv == ["--trial"]:
        mode = "trial"
    else:
        print("受け付ける引数は --trial だけ。手順は src/collector/README.md", file=sys.stderr)
        return 2
    try:
        out = _acquire(mode)
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
        if type(e).__name__ == "RunStartWritten":
            print("止まった: %s" % e, file=sys.stderr)
            return 4
        if type(e).__name__ == "GkgError":
            print("止まった（リードに報告。run-start のコミットが無いときは、要求を送る前に"
                  "止まっている）: %s" % e, file=sys.stderr)
            return 1
        raise
    print("%s run_id: %s 日数: %d ok: %d failed: %d"
          % ("正式な run" if mode == "official" else "試しの run", out["run_id"], out["days"],
             out["files_ok"], out["files_failed"]))
    print("データ出典：GDELT Project（https://www.gdeltproject.org/）。本プロジェクトは "
          "GDELT Project と提携・承認の関係にありません。")
    print("Data: The GDELT Project (https://www.gdeltproject.org/). This project is not "
          "affiliated with or endorsed by the GDELT Project.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
