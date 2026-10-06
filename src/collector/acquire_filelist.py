#!/usr/bin/env python3
"""試運転の手順3：GDELT のファイル一覧を取得する入口のスクリプト（T-015。実行は T-016）。

データ出典
    Data: The GDELT Project (https://www.gdeltproject.org/). This project is not
    affiliated with or endorsed by the GDELT Project.
    データ出典：GDELT Project（https://www.gdeltproject.org/）。本プロジェクトは
    GDELT Project と提携・承認の関係にありません。

使い方（プロジェクトのルートで。引数は受け付けない。手順の全体は src/collector/README.md）
    PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -B src/collector/acquire_filelist.py

このスクリプトがすること（この順。途中で止まれば、それより後のことはしない）
    1. 関門（check_gate）。ネットワークは使わない。どれか1つでも欠ければ GateError で止まり、
       何も書かない（封印の記録にも、保存先にも）。
         (1) 封印の記録の鎖と、すべての seq の .ots が検証に通る。periods の記録と candidates の
             記録が、それぞれ1件以上ある。candidates はすべて最初の acquisition-start より前に
             あり、形と出力の照合に通る（T-014 の ledger.check_candidates_ready。封印の仕組みの
             seal_acquisition.start も、candidates が無ければ書かずに止まる）
         (2) 区切りの封印（periods の記録のすべての seq）の時刻証明が Bitcoin で確定している。
             sealed/ の .ots の Bitcoin の証明を、sealed/bitcoin-header-<高さ>.hex のヘッダで
             照合して確かめる（ledger.confirmed_times。ヘッダが本当の鎖にあることは確かめない）
         (3) 保存先のフォルダ <home>/Desktop/news-stick-data と、その下の gdelt-filelist の2段が、
             どちらもシンボリックリンクでない既にあるフォルダである（このスクリプトは作らない）
         (4) 作業ツリーに、取得のコードの未コミットの変更が無い。
             - src/collector と src/sealer の下に、git status で出る変更（未追跡のファイルを
               含む）が無い
             - 入口のスクリプト・filelist.py・privacy_scan.py の中身が、HEAD のコミットの中身と
               同じ
             - filelist.py と privacy_scan.py の sha256 が、下の PINNED_SHA256 と一致する
    2. filelist.py を読み込む。関門で sha256 を照合したバイト列そのものを実行する
       （照合のあとでファイルが差し替えられても、照合していないものは実行しない）。
    3. filelist.run_acquisition を、下のアダプタにつないで1回だけ動かす。
         - start_hook（アダプタの start）：source_url が filelist.MASTERFILELIST_URL と同じこと、
           filelist が渡した code_sha256・封印の仕組みが計算する sha256
           （seal_acquisition.committed_code_sha256）・関門で計算した sha256 の3つが一致する
           ことを確かめてから、seal_acquisition.start を呼ぶ。書かれた中身の fetch が
           {code_path: CODE_REL, code_sha256: その値} であることを確かめ、記録の seq を返す
         - 取得：filelist の中で、2020-12-15 以降の行をメモリの上で捨て、許可リストの4項目だけを
           Git の外の保存先に書き、data/manifest/gdelt-filelist.jsonl に1行追記する
         - result_hook（アダプタの result）：start の seq と同じ start_seq であることを確かめて
           から、seal_acquisition.result で acquisition-result を書く
       アダプタは例外を握りつぶさない。封印の仕組みの例外（ledger.LedgerError、
       netfetch.FetchError など）も、filelist の例外も、そのまま呼び出し元に出る。
    4. 結果（ファイル名・行数・sha256・seq）を標準出力に出す。絶対パスは出さない。

固定するもの（本番では差し替えを受け付けない。T-010 の監査 中3）
    - main() は引数を1つも受け付けない（何か渡せば終了コード 2 で、何もしない）。
      環境変数も読まない（このファイルは os.environ を使わない）。
    - プロジェクトのルート PROJECT：このファイルの置き場所から決める。
    - 保存先：<home>/Desktop/news-stick-data/gdelt-filelist（filelist.FIXED_STORE_PARTS）。
      home は環境変数 HOME ではなく、利用者のデータベース（pwd.getpwuid(os.getuid())）から
      決める。
    - マニフェスト：<PROJECT>/data/manifest/gdelt-filelist.jsonl（filelist が固定）。
    - 通信：一覧は filelist.urllib_transport（data.gdeltproject.org だけ）、待ちは time.sleep、
      時計は time.monotonic と UTC の現在時刻、ログは標準エラー。drand は netfetch.http_get、
      ots は stamp.DEFAULT_OTS（.venv/bin/ots）を subprocess.run で実行する。
    テストのための差し替えは、_acquire(_test=_TestSeams(...)) からだけ渡せる。main() は
    _acquire() を引数なしで呼ぶだけなので、本番の経路からは渡せない。さらに _TestSeams の
    project と home は、システムの一時的なディレクトリ（tempfile.gettempdir()）の下でなければ
    拒む。本物のプロジェクトとホームはその外にあるので、差し替えを使って本物の sealed/・
    data/manifest・保存先に書くことはできない（ledger._gate_root と同じ考え方）。

取得のコードのハッシュの範囲（T-009 の監査 M-2）：入口のスクリプトに、ほかの2つを固定する
    封印の記録（acquisition-start の fetch）に入るのは、code_path = CODE_REL（このファイル）と、
    その sha256 の1組だけである（ledger.acquisition_start_fields が決めた形。T-014 でも同じ）。
    そこで、このファイルの中に filelist.py と privacy_scan.py の sha256 を PINNED_SHA256 として
    書き、関門で照合する。このファイルの sha256 が決まれば PINNED_SHA256 の値も決まるので、
    封印の記録の sha256 1つで、取得のコードの3つのファイルがすべて決まる。
    HEAD のコミットのハッシュを記録する案は採らなかった。理由：
      - acquisition-start の中身の形（fetch のキーは code_path と code_sha256 だけ）に、
        コミットのハッシュを入れる場所が無い。形を変えるのは封印係の範囲である。
      - マニフェストにコミットのハッシュを書いても、マニフェストは取得の後に書くので、
        取得の前に封印したことにならない。
    第三者は、封印の記録の code_sha256 と一致する acquire_filelist.py を履歴から探し、その中の
    PINNED_SHA256 と、同じコミットの filelist.py・privacy_scan.py の sha256 を照らせばよい。
    この範囲に入らないもの：src/sealer の封印の仕組み（関門 (4) で、未コミットの変更が無い
    ことだけを確かめる）、Python の処理系と標準ライブラリ、ots のクライアント。

source_url の扱い
    封印の仕組み（seal_acquisition.start）には渡さない。acquisition-start の中身の形に
    source_url の欄が無く、形を変えるのは封印係の範囲だからである。代わりに、
      - アダプタは、filelist が渡した source_url が filelist.MASTERFILELIST_URL と同じで
        なければ、封印の記録を書く前に止める。
      - MASTERFILELIST_URL は filelist.py の定数で、filelist.py の sha256 は PINNED_SHA256 で
        このファイルに固定され、このファイルの sha256 は封印の記録に入る。したがって、取得元の
        URL は、取得の前に封印した sha256 から決まる。
      - マニフェストの行にも source_url を書く（データ源の URL。記事の URL ではない）。

限界
    - 関門は、正直な運用で手順を飛ばす誤りを防ぐためのもので、証明ではない。このスクリプトを
      使わずに取得することは、記録からは検出できない（docs/verify/periods-seal.md 7章）。
    - ファイルの差し替えの競合について。filelist.py は、関門で照合したバイト列そのものを
      実行する。privacy_scan.py は filelist.py が自分でファイルから読み込むので、関門の照合と
      読み込みのあいだに差し替えられうる。そこで、読み込みの後に3つのファイルを読み直し、
      関門で照合したバイト列と同じかを確かめる（_recheck_code）。そのあと封印の記録を書く
      直前に、封印の仕組みが入口のスクリプトを読み直して sha256 を計算し、アダプタが関門の値と
      照合する。どれかで違えば、封印の記録を書く前に止まる。最後の照合のあとに書き換えても、
      実行中のコードは変わらない（読み込みは済んでいる）。
    - 第三者は、ファイル一覧の本体を持っていない。本体を確かめるには、自分で取得をやり直す
      しかない（README の「第三者が確かめられること」）。
"""

import datetime
import hashlib
import os
import pwd
import re
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
import seal_acquisition  # noqa: E402
import stamp  # noqa: E402

# 封印の記録の fetch.code_path。filelist.CODE_REL と同じ値（テストが照合する）。
CODE_REL = "src/collector/acquire_filelist.py"
FILELIST_REL = "src/collector/filelist.py"
PRIVACY_SCAN_REL = "src/collector/privacy_scan.py"

# 取得のコードのうち、このファイル以外の2つの sha256（上の「ハッシュの範囲」）。
# filelist.py か privacy_scan.py を変えたら、ここも直してコミットする（テストが照合する）。
PINNED_SHA256 = (
    (FILELIST_REL, "afd7a9dd47bc052a691e1a4cd558b211f4d72cf1ce1f451fa9f3016540cd04a7"),
    (PRIVACY_SCAN_REL, "68d8836d56489ca5df9f2f55e24a2642ebf3aa14afdc2e0120577c7b6c6cb887"),
)

# 関門 (4)：未コミットの変更が無いことを確かめるフォルダ。
CLEAN_PATHS = ("src/collector", "src/sealer")
# 関門 (3)：保存先の2段（filelist.FIXED_STORE_PARTS の後ろの2つ。テストが照合する）。
STORE_PARTS = ("Desktop", "news-stick-data", "gdelt-filelist")
HEADER_FILE_RE = re.compile(r"\Abitcoin-header-(\d+)\.hex\Z")
GIT_TIMEOUT_SECONDS = 60


class GateError(Exception):
    """関門で止まった。何も書いていない。"""


class AdapterError(Exception):
    """アダプタの照合に通らなかった。文に、どこまで書いたかを入れる。"""


def _sha256(data):
    return hashlib.sha256(data).hexdigest()


def production_home():
    """利用者のホーム。環境変数 HOME ではなく、利用者のデータベースから決める。"""
    return pwd.getpwuid(os.getuid()).pw_dir


# ---------------------------------------------------------------------------
# 差し替え（テストだけ）
# ---------------------------------------------------------------------------

class _Seams:
    """_acquire が使う部品。本番は _production_seams() だけが作る。"""

    FIELDS = ("project", "home", "transport", "sleep", "clock", "now", "log",
              "drand_fetch", "ots_cmd", "ots_runner")
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
                  clock=time.monotonic, now=_utc_now, log=None, drand_fetch=None,
                  ots_cmd=stamp.DEFAULT_OTS, ots_runner=subprocess.run)


class _TestSeams(_Seams):
    """テストのための差し替え。project と home は一時的なディレクトリの下に限る。"""

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
    return t


# ---------------------------------------------------------------------------
# 関門
# ---------------------------------------------------------------------------

def _git(project, *args):
    r = subprocess.run(["git", "-C", project] + list(args), capture_output=True,
                       timeout=GIT_TIMEOUT_SECONDS)
    return r.returncode, r.stdout


def _committed_bytes(project, rel):
    """rel の作業ツリーの中身。HEAD のコミットの中身と同じでなければ GateError。"""
    full = os.path.join(project, rel)
    try:
        st = os.lstat(full)
    except OSError:
        raise GateError("取得のコードが無い: %s" % rel) from None
    if not stat.S_ISREG(st.st_mode):
        raise GateError("取得のコードが通常のファイルでない: %s" % rel)
    with open(full, "rb") as f:
        work = f.read()
    code, head = _git(project, "show", "HEAD:%s" % rel)
    if code != 0:
        raise GateError("取得のコードが HEAD のコミットに無い: %s" % rel)
    if head != work:
        raise GateError("取得のコードが HEAD のコミットの中身と違う: %s" % rel)
    return work


def _check_records(project):
    """関門 (1)(2)。返り値: (periods の seq の一覧, candidates の seq の一覧, {seq: 確定時刻})。"""
    sealed = os.path.join(project, "sealed")
    try:
        data = ledger.read_ledger(os.path.join(sealed, "ledger.jsonl"))
        records = ledger.verify_chain(data)
        anchors = ledger.check_anchors(data, sealed)
        periods = [r["seq"] for _v, r in ledger.records_of_kind(records, ledger.PERIODS_KIND)]
        cands = [r for _v, r in ledger.records_of_kind(records, ledger.CANDIDATES_KIND)]
        if not periods:
            raise GateError("periods の記録が無い（期間の区切りの封印が先）")
        if not cands:
            raise GateError("candidates の記録が無い（閾値と判定期間の候補の封印が先）")
        # T-014 の検査と同じもの（次に追記する acquisition-start より前に candidates がある）
        ledger.check_candidates_ready(project, records, len(records) + 1)
        headers = {}
        for name in sorted(os.listdir(sealed)):
            m = HEADER_FILE_RE.match(name)
            if m:
                with open(os.path.join(sealed, name), encoding="ascii") as f:
                    hx = f.read().strip()
                try:
                    hdr = bytes.fromhex(hx)
                except ValueError:
                    raise GateError("%s が16進でない" % name) from None
                if len(hdr) != 80:
                    raise GateError("%s が 80 バイトでない" % name)
                headers[int(m.group(1))] = hdr
        times, _detail, _unused = ledger.confirmed_times(anchors, headers)
    except ledger.LedgerError as e:
        raise GateError("封印の記録の検証に通らない: %s" % e) from None
    pending = [s for s in periods if s not in times]
    if pending:
        raise GateError("区切りの封印（periods の seq %s）の時刻証明が、Bitcoin で確定していない"
                        "（sealed/ の .bitcoin.ots とヘッダが要る）"
                        % ", ".join(map(str, pending)))
    return periods, [r["seq"] for r in cands], {s: times[s] for s in periods}


def _check_store(home):
    """関門 (3)。2段のフォルダが、リンクでない既にあるフォルダであること。"""
    for depth in (2, 3):
        rel = "/".join(STORE_PARTS[:depth])
        try:
            st = os.lstat(os.path.join(home, *STORE_PARTS[:depth]))
        except OSError:
            raise GateError("保存先のフォルダ ~/%s が無い（オーナーが前もって作る）" % rel) from None
        if not stat.S_ISDIR(st.st_mode):
            raise GateError("保存先 ~/%s が、シンボリックリンクかフォルダでない" % rel)


def _check_code(project):
    """関門 (4)。返り値: {rel: バイト列}（入口・filelist・privacy_scan）。"""
    code, out = _git(project, "status", "--porcelain=v1", "-z", "--untracked-files=all",
                     "--", *CLEAN_PATHS)
    if code != 0:
        raise GateError("git status が失敗した（Git の作業ツリーでない）")
    if out:
        names = sorted({e[3:].decode("utf-8", "replace") for e in out.split(b"\0") if e})
        raise GateError("取得のコードに未コミットの変更がある: %s" % ", ".join(names))
    codes = {rel: _committed_bytes(project, rel)
             for rel in (CODE_REL, FILELIST_REL, PRIVACY_SCAN_REL)}
    for rel, want in PINNED_SHA256:
        if _sha256(codes[rel]) != want:
            raise GateError("%s の sha256 が、入口のスクリプトに固定した値と違う" % rel)
    return codes


def check_gate(s):
    """関門の4つ。通れば dict を返し、どれかが欠ければ GateError（何も書かない）。"""
    periods, cands, confirmed = _check_records(s.project)
    _check_store(s.home)
    codes = _check_code(s.project)
    return {"periods_seqs": periods, "candidates_seqs": cands, "confirmed": confirmed,
            "codes": codes, "code_sha256": _sha256(codes[CODE_REL])}


# ---------------------------------------------------------------------------
# filelist の読み込み
# ---------------------------------------------------------------------------

def _load_filelist(project, source):
    """照合済みのバイト列 source を、filelist モジュールとして実行する。"""
    path = os.path.join(project, FILELIST_REL)
    mod = types.ModuleType("filelist")
    mod.__file__ = path
    exec(compile(source, path, "exec"), mod.__dict__)
    return mod


def _recheck_code(project, gate):
    """読み込みの後に、3つのファイルがまだ関門で照合したものと同じかを確かめる。"""
    for rel, data in gate["codes"].items():
        with open(os.path.join(project, rel), "rb") as f:
            if f.read() != data:
                raise GateError("関門のあとで取得のコードが変わった: %s" % rel)


# ---------------------------------------------------------------------------
# アダプタ（T-009 の監査 M-1）
# ---------------------------------------------------------------------------

class _Adapter:
    """filelist の start_hook・result_hook を seal_acquisition につなぐ。例外は握りつぶさない。"""

    def __init__(self, s, filelist, gate_sha):
        self.s = s
        self.filelist = filelist
        self.gate_sha = gate_sha
        self.start_seq = None

    def start(self, *, code_sha256, source_url):
        if self.start_seq is not None:
            raise AdapterError("start は1回だけ")
        if source_url != self.filelist.MASTERFILELIST_URL:
            raise AdapterError("source_url が filelist.MASTERFILELIST_URL と違う（何も書いていない）")
        _path, sealer_sha = seal_acquisition.committed_code_sha256(self.s.project, CODE_REL)
        if not (code_sha256 == sealer_sha == self.gate_sha):
            raise AdapterError("取得のコードの sha256 が一致しない（filelist・封印の仕組み・関門。"
                               "何も書いていない）")
        rec, _rel, _ots = seal_acquisition.start(self.s.project, CODE_REL, self.s.now(),
                                                 self.s.ots_cmd, drand_fetch=self.s.drand_fetch,
                                                 runner=self.s.ots_runner)
        doc = ledger.read_target_json(self.s.project, rec, ledger.ACQ_START_KIND)
        if doc.get("fetch") != {"code_path": CODE_REL, "code_sha256": code_sha256}:
            raise AdapterError("書いた acquisition-start（seq %d）の fetch が、照合した値と違う。"
                               "記録は残っている。リードに報告する" % rec["seq"])
        self.start_seq = rec["seq"]
        return rec["seq"]

    def result(self, *, start_seq, kept_rows_sha256):
        if self.start_seq is None or start_seq != self.start_seq:
            raise AdapterError("result の start_seq が、このアダプタが書いた start の seq と違う"
                               "（何も書いていない）")
        rec, _rel, _ots = seal_acquisition.result(self.s.project, start_seq, kept_rows_sha256,
                                                  self.s.now(), self.s.ots_cmd,
                                                  runner=self.s.ots_runner)
        doc = ledger.read_target_json(self.s.project, rec, ledger.ACQ_RESULT_KIND)
        if (doc.get("start_seq"), doc.get("kept_rows_sha256")) != (start_seq, kept_rows_sha256):
            raise AdapterError("書いた acquisition-result（seq %d）の中身が、渡した値と違う。"
                               "記録は残っている。リードに報告する" % rec["seq"])
        return rec["seq"]


# ---------------------------------------------------------------------------
# 本体
# ---------------------------------------------------------------------------

def _acquire(_test=None):
    """関門 → 読み込み → 取得（start → 取得 → 保存 → result）。返り値は filelist の dict。

    _test はテストだけが渡す（_TestSeams）。main() は渡さない。
    """
    s = _production_seams() if _test is None else _checked_test_seams(_test)
    gate = check_gate(s)
    filelist = _load_filelist(s.project, gate["codes"][FILELIST_REL])
    _recheck_code(s.project, gate)
    adapter = _Adapter(s, filelist, gate["code_sha256"])
    kw = {}
    for name in ("transport", "log"):
        v = getattr(s, name)
        if v is not None:
            kw[name] = v
    out = filelist.run_acquisition(
        start_hook=adapter.start, result_hook=adapter.result, root=s.project,
        store_dir=filelist.fixed_store_dir(s.home), home=s.home,
        sleep=s.sleep, clock=s.clock, now=s.now, **kw)
    out = dict(out)
    out["code_sha256"] = gate["code_sha256"]
    return out


def main(argv=None):
    argv = sys.argv[1:] if argv is None else list(argv)
    if argv:
        print("引数は受け付けない（保存先・通信・時計などは固定）。手順は src/collector/README.md",
              file=sys.stderr)
        return 2
    try:
        out = _acquire()
    except GateError as e:
        print("関門で止まった（何も書いていない）: %s" % e, file=sys.stderr)
        return 1
    print("acquisition-start の seq: %d" % out["start_seq"])
    print("本体: %s（%s の下）" % (out["file_name"], "~/" + "/".join(STORE_PARTS)))
    print("残した行: %d、形式の合わない行: %d" % (out["kept_rows"], out["rejected_rows"]))
    print("kept_rows_sha256: %s" % out["kept_rows_sha256"])
    print("code_sha256（%s）: %s" % (CODE_REL, out["code_sha256"]))
    print("データ出典：GDELT Project（https://www.gdeltproject.org/）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
