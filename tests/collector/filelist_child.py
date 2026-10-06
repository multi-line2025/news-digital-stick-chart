"""test_filelist.py が子プロセスとして動かす、取得の本体の見張り（T-012、T-015。T-010 の監査 B-2、
T-012 の監査 軽1）。

単独では使わない。unittest の対象にもならない（名前が test で始まらない）。

動き
    1. 標準入力から設定（JSON）を読む。見張りの部品と、変異で使うモジュールを読み込む。
    2. sys.addaudithook で見張りを入れる。入れたあとは外せない（子プロセスにした理由）。
       **filelist.py を読み込むのは、見張りを入れた後である**（T-012 の監査 軽1）。そのため、
       filelist.py の読み込みの時点で動くコード（書き込みのモードで開く、sys.addaudithook を
       置き換える、など）も見張りの下にある。
    3. filelist.py を読み込み、見本の通信・時計・フックを作り、filelist.run_acquisition() を
       1回だけ動かす。
    4. 結果を、親が渡したファイル記述子（report_fd）に os.write で書く。

見張りが止めるもの
    - **許すイベントの一覧（ALLOWED_EVENTS）に無いイベントは、すべて止める。** 一覧は、
      見張りの下で filelist.py を読み込んで run_acquisition() を動かしたときに、実際に出る
      イベントだけにした。一覧に無いイベントの例：sys._getframe・sys._current_frames・
      gc.get_referrers・gc.get_objects・object.__getattr__（例外の tb_frame など）・
      _posixsubprocess.fork_exec・subprocess.Popen・os.system・os.posix_spawn・os.mkdir・
      os.symlink・os.rename・os.remove・sqlite3.connect・ctypes.dlopen・socket.*・
      sys.settrace・sys.setprofile・sys.addaudithook。
    - 一覧にあるイベントでも、次のものは止める。
        open：書き込みのモード（mode に w・a・x・+ のどれか、または flags に
          O_WRONLY・O_RDWR・O_CREAT・O_APPEND・O_TRUNC のどれか）で、パスの realpath が
          allowed（本体の保存先のファイルと、マニフェスト）に無いもの。記述子の番号での
          書き込みの open は常に止める。builtins.open、io.open、os.open、_io.FileIO、
          os.fdopen がこのイベントを出す。
        object.__setattr__：属性の名前が SETATTR_NAMES（__doc__・__module__・__defaults__。
          標準ライブラリの namedtuple などが読み込みのときに使う）に無いもの。関数の
          __code__ の差し替えなどは止まる。
    止めるときは、Blocked（BaseException の子）を投げる。取得のコードの except Exception では
    捕まらない。

見張りの状態の置き場所（T-012 の監査 軽1(b)）
    - 見張りを外す・弱める状態（以前の active のような旗）は持たない。見張りは一度入れたら、
      子プロセスが終わるまで同じ判定をする。
    - 判定に使う値（許すイベント・許すパス・許す属性の名前）は frozenset で、見張りの関数の
      クロージャの中だけにある。モジュールの変数としては置かない。クロージャやフレームに
      届く経路（sys._getframe、例外の tb_frame、gc.get_referrers など）は、上の一覧で止める。
    - 止めた記録（violations）は、リストに溜めずに、止めたその時に violation_fd へ os.write で
      1行ずつ書く。後から取得のコードがリストを消しても、書いた記録は消せない。
      os.write は audit のイベントを出さないので、見張りの中で使っても見張りに掛からない。

見張りの範囲（これより外は見ていない。事実どおりに書く）
    - audit のイベントを出さない操作は見えない。os.write・os.close・os.dup2 などは
      イベントを出さないので、既に開いている記述子への書き込みは止まらない。子プロセスが
      開いている記述子は、0・1・2 と report_fd・violation_fd と、Python の処理系が内部で
      開くものである。1・2 は親がパイプで受け取って比べる。report_fd と violation_fd に
      余計なものが書かれれば、JSON が壊れて親のテストが失敗する。
      見張りを入れる前に開いた記述子はこれだけで、見張りを入れた後に書き込みのモードで
      開こうとすると止まる（filelist.py の読み込みの時点を含む）。
    - C の拡張が audit のイベントを出さずに行う操作は見えない。
    - os.path.realpath などの判定に使う関数は、見張りを入れる時点のものをクロージャに
      持っている。ただし、その関数が中で使う標準ライブラリのモジュールの変数（posixpath の
      中の os など）を書き換えられると、判定を誤らせうる。
"""

import base64
import datetime
import importlib.util
import io
import json
import os
import sys

# 変異で使うモジュールは、見張りを入れる前に読み込んでおく（読み込みそのものの
# イベントで、変異の前に止まらないようにするため）。
import _io  # noqa: F401
import _posixsubprocess  # noqa: F401
import ctypes  # noqa: F401
import gc  # noqa: F401
import sqlite3  # noqa: F401
import subprocess  # noqa: F401

# 見張りの下で filelist.py を読み込み、run_acquisition() を動かしたときに出るイベント。
# これ以外は止める。
ALLOWED_EVENTS = frozenset({
    "open", "import", "exec", "compile", "marshal.loads", "os.listdir",
    "sys._getframemodulename", "object.__setattr__",
})
SETATTR_NAMES = frozenset({"__doc__", "__module__", "__defaults__"})
WRITE_FLAGS = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_APPEND | os.O_TRUNC


class Blocked(BaseException):
    """見張りが止めた操作。取得のコードの except Exception に捕まらない。"""


def make_hook(allowed_paths, violation_fd):
    """見張りの関数を作る。判定に使う値は、すべてこのクロージャの中にだけある。"""
    allowed = frozenset(os.path.realpath(p) for p in allowed_paths)
    events = ALLOWED_EVENTS
    setattr_names = SETATTR_NAMES
    write_flags = WRITE_FLAGS
    realpath, fsdecode, write, dumps = os.path.realpath, os.fsdecode, os.write, json.dumps
    blocked = Blocked

    def report(kind, detail):
        write(violation_fd, (dumps([kind, detail], ensure_ascii=True) + "\n").encode("ascii"))

    def hook(event, args):
        if event not in events:
            report(event, None)
            raise blocked(event)
        if event == "open":
            path, mode, flags = (tuple(args) + (None, None, None))[:3]
            writing = ((isinstance(mode, str) and any(c in mode for c in "wax+"))
                       or (isinstance(flags, int) and bool(flags & write_flags)))
            if not writing:
                return
            if isinstance(path, int):
                report("open-fd", path)
                raise blocked("記述子の番号での書き込みの open")
            rp = realpath(fsdecode(path))
            if rp not in allowed:
                report("open", rp)
                raise blocked("許していない書き込み")
            return
        if event == "object.__setattr__":
            name = args[1] if len(args) > 1 else None
            if name not in setattr_names:
                report(event, str(name))
                raise blocked(event)

    return hook


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class _Headers(dict):
    def get(self, k, default=None):
        return dict.get(self, k, default)


class _Response:
    def __init__(self, spec):
        self._buf = io.BytesIO(base64.b64decode(spec.get("body", "")))
        self.status = spec.get("status", 200)
        self.headers = _Headers(spec.get("headers") or {})
        self._fail_after = spec.get("fail_after")
        self._fail_at_eof = spec.get("fail_at_eof", False)
        self._reads = 0

    def readline(self, limit=-1):
        self._reads += 1
        if self._fail_after is not None and self._reads > self._fail_after:
            raise ConnectionResetError("見本の失敗")
        line = self._buf.readline(limit)
        if not line and self._fail_at_eof:
            raise ConnectionResetError("見本の失敗（終わりの直前）")
        return line

    def close(self):
        pass


def _mutation(name, outside):
    """監査が挙げた変異（取得の途中で動くもの）。見張りの外へ書こうとする。例外は握りつぶす。"""

    def touch_fork_exec():
        r, w = os.pipe()
        _posixsubprocess.fork_exec(
            [b"/usr/bin/touch", os.path.join(outside, "forked").encode()],
            [b"/usr/bin/touch"], True, (w,), None, None,
            -1, -1, -1, -1, -1, -1, r, w, False, False, -1, None, None, -1, -1, None)

    def getframe_walk():
        f = sys._getframe()
        while f is not None:
            f = f.f_back
        open(os.path.join(outside, "after-getframe.txt"), "a")

    def referrers():
        gc.get_referrers(os.write)
        open(os.path.join(outside, "after-referrers.txt"), "a")

    def tb_frame():
        try:
            raise ValueError("x")
        except ValueError as e:
            e.__traceback__.tb_frame  # noqa: B018
        open(os.path.join(outside, "after-tb.txt"), "a")

    actions = {
        "fileio": lambda: _io.FileIO(os.path.join(outside, "fileio.txt"), "w"),
        "makedirs": lambda: os.makedirs(os.path.join(outside, "made", "deep")),
        "symlink": lambda: os.symlink(outside, os.path.join(outside, "link")),
        "rename": lambda: os.rename(os.path.join(outside, "x"), os.path.join(outside, "y")),
        "subprocess": lambda: subprocess.run(["/usr/bin/touch",
                                              os.path.join(outside, "touched")]),
        "system": lambda: os.system("true"),
        "posix_spawn": lambda: os.posix_spawn("/usr/bin/true", ["/usr/bin/true"], {}),
        "sqlite3": lambda: sqlite3.connect(os.path.join(outside, "db.sqlite3")),
        "ctypes": lambda: ctypes.CDLL(None),
        "open_append": lambda: open(os.path.join(outside, "appended.txt"), "a"),
        "os_open": lambda: os.open(os.path.join(outside, "osopen.txt"),
                                   os.O_WRONLY | os.O_CREAT, 0o644),
        "fork_exec": touch_fork_exec,
        "getframe": getframe_walk,
        "get_referrers": referrers,
        "tb_frame": tb_frame,
        "settrace": lambda: sys.settrace(lambda *a: None),
        "print": lambda: print("MUTATION-STDOUT"),
        "stderr_fd": lambda: os.write(2, b"MUTATION-FD2\n"),
    }
    act = actions[name]

    def run():
        try:
            act()
        except BaseException:
            pass  # 握りつぶしても、violations は書いた時点で親に届いている
    return run


def main():
    cfg = json.loads(sys.stdin.read())
    report_fd = cfg["report_fd"]
    violation_fd = cfg["violation_fd"]
    responses = list(cfg["responses"])
    times = [datetime.datetime.fromisoformat(t) for t in cfg["now"]]
    mutation = _mutation(cfg["mutation"], cfg["outside"]) if cfg.get("mutation") else None

    # 見張りを入れる。これより後に filelist.py を読み込む。
    sys.addaudithook(make_hook(cfg["allowed"], violation_fd))

    report = {"out": None, "error": None, "loaded": False}
    try:
        filelist = _load("filelist", cfg["filelist_path"])
        report["loaded"] = True
    except BaseException as e:  # noqa: B902 （読み込みの時点で止まった変異）
        report["error"] = [type(e).__name__, str(e)]
        filelist = None

    calls = []

    def transport(url, timeout):
        calls.append([url, timeout])
        spec = responses.pop(0)
        if "exc" in spec:
            raise {"ConnectionResetError": ConnectionResetError,
                   "TimeoutError": TimeoutError}[spec["exc"]]("見本")
        return _Response(spec)

    clock_t = [0.0]
    sleeps = []

    def sleep(s):
        sleeps.append(s)
        clock_t[0] += s

    def now():
        return times.pop(0) if len(times) > 1 else times[0]

    events, start_args, result_args, logs = [], [], [], []

    def start_hook(**kw):
        events.append("start")
        start_args.append(kw)
        return cfg.get("seq", 7)

    def result_hook(**kw):
        events.append("result")
        result_args.append(kw)

    if filelist is not None:
        if mutation is not None:
            real_fetch = filelist.fetch_kept_lines

            def fetch(*a, **k):
                mutation()
                return real_fetch(*a, **k)
            filelist.fetch_kept_lines = fetch
        try:
            out = filelist.run_acquisition(
                start_hook=start_hook, result_hook=result_hook, root=cfg["root"],
                store_dir=cfg["store_dir"], home=cfg["home"], url=cfg["url"],
                transport=transport, sleep=sleep, clock=lambda: clock_t[0], now=now,
                log=logs.append)
            out = dict(out)
            out["path"] = os.path.basename(out["path"])
            report["out"] = out
        except BaseException as e:  # noqa: B902 （Blocked も含めて親に返す）
            report["error"] = [type(e).__name__, str(e)]
    report.update({"events": events, "start_args": start_args, "result_args": result_args,
                   "logs": logs, "sleeps": sleeps, "calls": calls})
    data = json.dumps(report, sort_keys=True, ensure_ascii=True).encode("ascii")
    view = memoryview(data)
    while view:
        n = os.write(report_fd, view)
        view = view[n:]
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(0)


if __name__ == "__main__":
    main()
