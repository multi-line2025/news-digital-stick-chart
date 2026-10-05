"""test_filelist.py が子プロセスとして動かす、取得の本体の見張り（T-012。T-010 の監査 B-2）。

単独では使わない。unittest の対象にもならない（名前が test で始まらない）。

動き
    1. 標準入力から設定（JSON）を読み、filelist.py を読み込み、見本の通信・時計・フックを作る。
    2. sys.addaudithook で見張りを入れる。入れたあとは外せない（子プロセスにした理由）。
    3. filelist.run_acquisition() を1回だけ動かす。
    4. 結果を、親が渡したファイル記述子（report_fd）に os.write で書く。os.write は
       audit のイベントを出さないので、見張りに掛からない。

見張りが止めるもの（BLOCKED_EVENTS と、書き込みのモードの open）
    - "open" のイベントのうち、書き込みのモード（mode に w・a・x・+ のどれか、または flags に
      O_WRONLY・O_RDWR・O_CREAT・O_APPEND・O_TRUNC のどれか）のもの。builtins.open、io.open、
      os.open、_io.FileIO、os.fdopen（記述子の番号での open）がこのイベントを出す。
      許すのは、allowed（本体の保存先のファイルと、マニフェスト）の realpath に一致するパス
      だけ。記述子の番号での書き込みの open は、常に止める。
    - BLOCKED_EVENTS のイベントは、引数にかかわらず止める。
    止めるときは、violations に記録し、BaseException の子の Blocked を投げる。取得のコードが
    例外を握りつぶしても、violations は親に届く。

見張りの範囲（これより外は見ていない）
    - audit のイベントを出さない経路（os.write で既にある記述子に書く、など）は、この見張り
      では止まらない。子プロセスが持つ記述子は 0・1・2 と report_fd だけである。1・2 は親が
      パイプで受けて比べ、report_fd に余計なものが書かれれば JSON が壊れて親のテストが失敗する。
    - C の拡張が audit のイベントを出さずに書く経路は見えない。
"""

import base64
import datetime
import importlib.util
import io
import json
import os
import sys

BLOCKED_EVENTS = frozenset({
    # 割り振りで挙がったもの
    "os.mkdir", "os.symlink", "os.rename", "subprocess.Popen", "os.system",
    "os.posix_spawn", "sqlite3.connect", "ctypes.dlopen",
    # それ以外に、ファイル・プロセス・ネットワークに触れるもの
    "os.link", "os.remove", "os.rmdir", "os.truncate", "os.chmod", "os.chown",
    "os.utime", "os.chflags", "os.lchflags", "os.setxattr", "os.removexattr",
    "os.mkfifo", "os.mknod", "os.fork", "os.forkpty", "os.exec", "os.spawn",
    "os.kill", "os.killpg", "os.putenv", "os.unsetenv", "os.chdir",
    "pty.spawn", "shutil.copyfile", "shutil.copymode", "shutil.copystat",
    "shutil.copytree", "shutil.move", "shutil.rmtree", "shutil.make_archive",
    "shutil.unpack_archive", "tempfile.mkstemp", "tempfile.mkdtemp",
    "socket.__new__", "socket.connect", "socket.bind", "socket.getaddrinfo",
    "socket.sendto", "socket.sendmsg", "http.client.connect", "urllib.Request",
    "ctypes.dlsym", "ctypes.dlsym/handle", "ctypes.cdata", "ctypes.call_function",
    "sqlite3.connect/handle", "sqlite3.enable_load_extension",
    "sqlite3.load_extension", "webbrowser.open", "mmap.__new__",
})

WRITE_FLAGS = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_APPEND | os.O_TRUNC


class Blocked(BaseException):
    """見張りが止めた操作。取得のコードの except Exception に捕まらない。"""


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
    """監査が挙げた変異。取得の途中で、見張りの外へ書こうとする。例外は握りつぶす。"""
    import _io
    import ctypes
    import sqlite3
    import subprocess

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
        "print": lambda: print("MUTATION-STDOUT"),
        "stderr_fd": lambda: os.write(2, b"MUTATION-FD2\n"),
    }
    act = actions[name]

    def run():
        try:
            act()
        except BaseException:
            pass  # 握りつぶしても、violations は親に届く
    return run


def main():
    cfg = json.loads(sys.stdin.read())
    report_fd = cfg["report_fd"]
    filelist = _load("filelist", cfg["filelist_path"])

    responses = list(cfg["responses"])
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

    times = [datetime.datetime.fromisoformat(t) for t in cfg["now"]]

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

    if cfg.get("mutation"):
        mut = _mutation(cfg["mutation"], cfg["outside"])
        real_fetch = filelist.fetch_kept_lines

        def fetch(*a, **k):
            mut()
            return real_fetch(*a, **k)
        filelist.fetch_kept_lines = fetch

    allowed = {os.path.realpath(p) for p in cfg["allowed"]}
    violations = []
    active = [True]
    realpath, fsdecode = os.path.realpath, os.fsdecode

    def hook(event, args):
        if not active[0]:
            return
        if event == "open":
            path, mode, flags = (tuple(args) + (None, None, None))[:3]
            writing = ((isinstance(mode, str) and any(c in mode for c in "wax+"))
                       or (isinstance(flags, int) and bool(flags & WRITE_FLAGS)))
            if not writing:
                return
            if isinstance(path, int):
                violations.append(["open-fd", path])
                raise Blocked("記述子の番号での書き込みの open")
            rp = realpath(fsdecode(path))
            if rp not in allowed:
                violations.append(["open", rp])
                raise Blocked("許していない書き込み")
            return
        if event in BLOCKED_EVENTS:
            violations.append([event, None])
            raise Blocked(event)

    sys.addaudithook(hook)

    report = {"out": None, "error": None}
    try:
        out = filelist.run_acquisition(
            start_hook=start_hook, result_hook=result_hook, root=cfg["root"],
            manifest_dir=cfg["manifest_dir"], store_dir=cfg["store_dir"], url=cfg["url"],
            transport=transport, sleep=sleep, clock=lambda: clock_t[0], now=now,
            log=logs.append)
        out = dict(out)
        out["path"] = os.path.basename(out["path"])
        report["out"] = out
    except BaseException as e:  # noqa: B902 （Blocked も含めて親に返す）
        report["error"] = [type(e).__name__, str(e)]
    active[0] = False
    report.update({"events": events, "start_args": start_args, "result_args": result_args,
                   "logs": logs, "sleeps": sleeps, "calls": calls,
                   "violations": violations})
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
