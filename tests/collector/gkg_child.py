"""test_gkg.py が子プロセスとして動かす、GKG の取得と集計の見張り（T-018 の差し戻し1回目。監査 中2）。

単独では使わない。unittest の対象にもならない（名前が test で始まらない）。

動き（filelist_child.py と同じ見張りを使う）
    1. 標準入力から設定（JSON）を読む。filelist_child（見張りの部品と変異）を読み込む。
    2. sys.addaudithook で、filelist_child.make_hook の見張りを入れる。許すイベントの一覧
       （filelist_child.ALLOWED_EVENTS）に無いイベントは止め、書き込みの open は、親が渡した
       パス（allowed：日の集計・取得の記録・マニフェスト）のほかはすべて止める。
       **gkg.py（と、それが読み込む filelist.py・privacy_scan.py）を読み込むのは、見張りを
       入れた後である。**
    3. mode が "run" なら gkg.run_gkg を、"aggregate" なら gkg.aggregate_zip を1回動かす
       （aggregate のときは allowed は空で、書き込みは一つも許さない）。
    4. 結果を report_fd に os.write で書く。止めた記録は、止めたその時に violation_fd に書く
       （filelist_child.make_hook）。
見張りの範囲と限界は filelist_child.py の docstring と同じ。
"""

import base64
import datetime
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import filelist_child as fc  # noqa: E402  （見張りの部品。変異のモジュールもここで読み込む）


class _Headers(dict):
    def get(self, k, default=None):
        return dict.get(self, k, default)


class _Response:
    def __init__(self, body):
        self.body, self.pos, self.status = body, 0, 200
        self.headers = _Headers()

    def read(self, n=-1):
        c = self.body[self.pos:self.pos + n]
        self.pos += len(c)
        return c

    def close(self):
        pass


def main():
    cfg = json.loads(sys.stdin.read())
    report_fd, violation_fd = cfg["report_fd"], cfg["violation_fd"]
    zips = {k: base64.b64decode(v) for k, v in cfg["zips"].items()}
    mutation = fc._mutation(cfg["mutation"], cfg["outside"]) if cfg.get("mutation") else None
    now = datetime.datetime.fromisoformat(cfg["now"])

    sys.addaudithook(fc.make_hook(cfg["allowed"], violation_fd))

    report = {"out": None, "error": None, "loaded": False, "calls": [], "logs": []}
    try:
        gkg = fc._load("gkg", cfg["gkg_path"])
        report["loaded"] = True
    except BaseException as e:  # noqa: B902
        report["error"] = [type(e).__name__, str(e)]
        gkg = None

    def transport(url, timeout):
        ts = url.rsplit("/", 1)[1][:14]
        report["calls"].append(ts)
        return _Response(zips[ts])

    clock = [0.0]

    def sleep(s):
        clock[0] += s

    if gkg is not None:
        if mutation is not None:
            real = gkg.aggregate_zip

            def aggregate(*a, **k):
                mutation()
                return real(*a, **k)
            gkg.aggregate_zip = aggregate
        try:
            if cfg["mode"] == "run":
                out = gkg.run_gkg(
                    root=cfg["root"], home=cfg["home"],
                    filelist_rows=[tuple(r) for r in cfg["rows"]],
                    filelist_sha256="c" * 64, method_access_seq=5, code_sha256=cfg["code_sha"],
                    transport=transport, sleep=sleep, clock=lambda: clock[0], now=lambda: now,
                    log=report["logs"].append, disk_free=lambda p: 100 * 1024 ** 3)
                report["out"] = dict(out)
            else:
                ts, data = sorted(zips.items())[0]
                agg = gkg.aggregate_zip(data, ts, {})
                report["out"] = {"docs": sum(agg.docs.values())}
        except BaseException as e:  # noqa: B902 （見張りの Blocked も含めて親に返す）
            report["error"] = [type(e).__name__, str(e)]
    data = json.dumps(report, sort_keys=True, ensure_ascii=True).encode("ascii")
    view = memoryview(data)
    while view:
        view = view[os.write(report_fd, view):]
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(0)


if __name__ == "__main__":
    main()
