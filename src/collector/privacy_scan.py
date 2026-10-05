#!/usr/bin/env python3
"""公開前のメールアドレス検査（T-003）。

目的
    公開物（push されるもの）に、メールアドレスの形の文字列が入っていないことを
    機械的に確かめる。許すのは、Git の作成者用の noreply アドレス 1 件だけ
    （下の ALLOWED_ADDRESSES。設定ファイルにはしない）。

使い方
    python3 src/collector/privacy_scan.py [--root DIR] [--all-history]
    python3 src/collector/privacy_scan.py [--root DIR] --pre-push
                                           （pre-push フックから呼ぶ形）

    終了コード  0: 見つからなかった
                1: 1 件以上見つかった（push を止める）
                2: 検査を最後までできなかった、または中身を検査できないものがあった
                   （安全側に倒して失敗扱い）

    出力するのは、ファイル名（またはコミットのハッシュ）・行番号・件数だけ。
    一致した文字列そのものは、標準出力・標準エラー・例外のメッセージのどこにも出さない。
    ファイル名や参照の名前（ブランチ名・タグ名）にアドレスの形が含まれる場合は、
    その名前も伏せる。参照の名前は、見つかった場合でも常に伏せて表示する。
    ログのファイルは書かない。

検査する対象
    Git のリポジトリの場合（どのモードでも）
      - git ls-files で追跡されているファイル（作業ツリーの中身とファイル名）
      - インデックス（ステージ済み）の中身とファイル名
      - git for-each-ref で得られるすべての参照の名前
      - すべての注釈付きタグのオブジェクト（タグ作成者・メッセージ）。
        タグを辿った先がコミットでない（ブロブやツリーを指す）タグがあれば終了コード 2
      - 下の「コミットの範囲」にある各コミットのオブジェクト全体（作成者・
        コミッター・メッセージ。Co-authored-by などの追記行も含む）と、
        そのコミットのツリーにあるすべてのファイルの中身とファイル名
    コミットの範囲
      --all-history       git rev-list --all（全履歴）。CI は必ずこれを使う。
                          --all には refs/stash も含まれるので、stash に入った
                          変更にアドレスがあれば失敗になる（安全側の失敗）。
      --pre-push          標準入力（<local ref> <local sha> <remote ref> <remote sha>）
                          を読む。除外に使うのは、標準入力の remote sha（push 先が
                          「いま持っている」と Git に答えたコミット）から辿れるものだけ。
                            - すべての行の remote sha が手元にあれば:
                                git rev-list <local sha...> --not <remote sha...>
                            - remote sha が全 0（新しいブランチ）の行、または
                              remote sha が手元に無い行が 1 つでもあれば: 全履歴
                                git rev-list --all <local sha...>
                          refs/remotes（追跡参照）は除外に使わない。追跡参照は、
                          remote set-url・remote rename・名前に / を含むリモート・
                          fetch の行き先の書き換えで、push 先の中身と食い違うため。
                          標準入力の local ref と remote ref の名前も検査する。
                          欄が 4 つでない行があれば終了コード 2。
      指定なし            手元で確かめるためのモード。公開してよいかの判定には使えない。
                          現在のブランチに上流があれば、上流のリモートの追跡参照から
                          辿れるコミットを除く（追跡参照は上の理由で当てにならない）。
                          上流が無い（detached HEAD を含む）ときは全履歴。
                          公開の判定には --all-history（CI）か --pre-push を使う。
    リポジトリでない場合
      - ルートの下の全ファイル（.gitignore を考慮。.git ディレクトリは除く）

    中身を検査できないものは、見つけたら終了コード 2 で止める。
      - サブモジュール（gitlink。モード 160000）
      - Git LFS のポインタ（実体は Git の外にあり、ここでは検査できない）
      - コミット以外を指すタグ

検出する形（それぞれ「@」と「.」に戻してから照合する）
    前処理（行ごと）
      - NUL バイトを取り除く（UTF-16/UTF-32 で書かれた ASCII も拾うため）
      - UTF-8 として読む（読めないバイトは区切りとして扱う）
      - Unicode の NFKC で正規化する（全角の英数字・＠・．などを半角に戻す）
      - Unicode の Cf 類（ゼロ幅の文字、ソフトハイフン、BOM など）を取り除く
      - 符号化を戻す。変化が無くなるまでくり返す。64 回くり返しても変化が
        止まらない（63 重を超える符号化）場合は、終了コード 2 で止める
          URL の %XX（%2540 のような多重の符号化も）
          HTML の文字参照（&#64; &#x40; &commat; &period; など、すべて。
                          &COMMAT; &PERIOD; のような大文字の形も）
          quoted-printable の =XX（=40 など。ASCII の印字可能な文字だけ）
          \\uXXXX、\\u{X}、\\UXXXXXXXX、\\UXXXX、\\xXX の形の逃がし
      - 括弧で書いた形を戻す: [at] (at) {at} <at>、[dot] (dot) {dot} <dot>
        （大文字小文字を問わない）
      - 「。」「｡」を「.」として扱う（「．」は NFKC で「.」になる）
      - \\@ の形の逃がし文字を取り除く
      - 「@」と「.」の前後の空白を詰める
    照合
      @ の直後にドメイン部 [A-Za-z0-9.-]+ がある形を探す。ドメイン部の末尾から、
      「.」「-」と、英字を含まないラベルをくり返し取り除く（文末の「。3日」「. 2 people」
      が「.」を詰めた結果ドメインにつながる場合のため）。残りの「.」で区切ったラベルが
      2 つ以上あり、最後のラベルに英字を含み、かつ @ の直前が空白でも行頭でもないものを、
      アドレスの形とみなす。許可の照合も、取り除いた後のドメインで行う。
      @ の直前から [A-Za-z0-9._%+-] が続く部分を local 部として取り出し、
      「local 部 @ ドメイン部」が許可の一覧と完全に一致するものだけを許す。
      @ の直前がそれ以外の文字（角括弧・引用符・括弧など）なら、local 部に
      角括弧や引用符を含む形として、常に検出する。
      （大文字小文字の違い・前後に文字が付いたもの・ドメインの違いは、すべて検出する）
    誤検出は安全側として許容する（たとえば、文末の句点の直後に許可のアドレスを
    続けて書くと、空白を詰めた結果ちがう文字列になり、検出される）。

許容した穴（この検査では拾えない形）
    - 語で書いた at と dot（括弧の無いもの。例: 名前のあとに at、ドメインの間に dot）
    - IP アドレスをドメインにした形（[192.0.2.1] のような角括弧の形を含む）
    - base64 や圧縮（zip、gzip、PDF の圧縮ストリームなど）の中にあるもの
    - 行をまたいで書いたもの（quoted-printable の折り返しを含む）
    - IDN（英字以外の文字を含むドメイン）
    - local 部の途中に空白があり、@ の直前が英数字の形（例: 引用符の中に空白を含み、
      空白の後ろの部分だけが local 部として取り出される形は、取り出した部分で
      照合するので検出はするが、許可のアドレスと一致すれば見落とす）
    - UTF-16 などで書いた、ASCII 以外の文字（全角の＠など）
    - 許可のアドレスの local 部の直前に、local 部として取り出さない文字
      （/ ' ! # $ & * = ? ^ ` { | } ~ など、RFC 5322 では local 部に使える文字）を
      付けた形。取り出した local 部は許可のアドレスと一致するので、許可として通る。
      これは許容する。許可のアドレスのドメイン users.noreply.github.com は GitHub の
      noreply 用で、受信箱が無い（どの local 部でも、実在の個人に届くアドレスに
      ならない）ため。ドメインが違う形・local 部の文字が違う形は、すべて検出する。

許可の一覧の固定と、残る穴
    tests/collector/test_privacy_scan.py が、ALLOWED_ADDRESSES がちょうど 1 件で、
    その値が CLAUDE.md の「作成者と個人情報」の行から取り出したアドレスと
    一致することを確かめる。ただし、この検査器は push される側の作業ツリーから
    実行されるので、同じ push の中で検査器とテスト（と CLAUDE.md）を一緒に
    書き換えれば、この固定は外せる。差分の確認（レビュー）でしか防げない。

pre-push フックの導入と限界
    src/collector/hooks/pre-push の冒頭の注記を参照。

外部のライブラリは使わない（Python 3 の標準ライブラリだけ）。ネットワークは使わない。
"""

import argparse
import html
import os
import re
import subprocess
import sys
import unicodedata
import urllib.parse

# 許可する一覧。完全に一致するものだけを許す。設定ファイルにはしない。
# tests/collector/test_privacy_scan.py が、件数（1 件）と値を CLAUDE.md と照合する。
ALLOWED_ADDRESSES = frozenset({
    "197505900+multi-line2025@users.noreply.github.com",
})

PROG = "privacy_scan"
EXIT_OK = 0
EXIT_FOUND = 1
EXIT_ERROR = 2

_ZERO_SHA = re.compile(r"^0+$")
_SHA = re.compile(r"^[0-9a-f]{40}(?:[0-9a-f]{24})?$")
_LFS_POINTER = b"version https://git-lfs.github.com/spec/"

# --- 正規化 ---
_QP = re.compile(r"=([2-7][0-9A-Fa-f])")
_ESC = re.compile(
    r"\\u\{([0-9A-Fa-f]{1,6})\}|\\U([0-9A-Fa-f]{8})|\\U([0-9A-Fa-f]{4})"
    r"|\\u([0-9A-Fa-f]{4})|\\x([0-9A-Fa-f]{2})"
)
_NAMED_ANYCASE = re.compile(r"&(commat|period);?", re.IGNORECASE)
# 前後の空白は付けない（空白の長い行で 2 乗の時間がかかるため）。
# 括弧の前後の空白は、後の「@ と . の前後の空白を詰める」処理で詰める。
_BRACKET_AT = re.compile(r"[\[\(\{<][^\S\n]{0,8}at[^\S\n]{0,8}[\]\)\}>]", re.IGNORECASE)
_BRACKET_DOT = re.compile(r"[\[\(\{<][^\S\n]{0,8}dot[^\S\n]{0,8}[\]\)\}>]", re.IGNORECASE)
_DOMAIN_AFTER_AT = re.compile(r"@([A-Za-z0-9.-]+)")
_LOCAL_CHARS = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._%+-")
_HAS_LETTER = re.compile(r"[A-Za-z]")
DECODE_LIMIT = 64


def _qp_char(m):
    v = int(m.group(1), 16)
    return chr(v) if 0x21 <= v <= 0x7E else m.group(0)


def _named_char(m):
    return "@" if m.group(1).lower() == "commat" else "."


def _esc_char(m):
    digits = next(g for g in m.groups() if g is not None)
    v = int(digits, 16)
    if v <= 0x10FFFF:
        return chr(v)
    if m.group(2) is not None:
        # \U の後ろの 8 桁が文字にならないときは、4 桁の \UXXXX として読む
        return chr(int(digits[:4], 16)) + digits[4:]
    return m.group(0)


def _nfkc_strip_cf(s):
    if s.isascii():
        return s
    s = unicodedata.normalize("NFKC", s)
    return "".join(c for c in s if unicodedata.category(c) != "Cf")


def normalize_line(raw):
    """1 行（NUL を除いたバイト列）を、照合できる文字列にする。"""
    s = raw.decode("utf-8", "replace")
    for _ in range(DECODE_LIMIT):
        prev = s
        s = _nfkc_strip_cf(s)
        if "&" in s:
            s = _NAMED_ANYCASE.sub(_named_char, s)
            s = html.unescape(s)
        if "%" in s:
            s = urllib.parse.unquote(s, errors="replace")
        if "=" in s:
            s = _QP.sub(_qp_char, s)
        if "\\" in s:
            s = _ESC.sub(_esc_char, s)
        if s == prev:
            break
    else:
        raise ScanError("符号化を戻す処理が %d 回で止まらなかった" % DECODE_LIMIT)
    s = _nfkc_strip_cf(s)
    s = _BRACKET_AT.sub("@", s)
    s = _BRACKET_DOT.sub(".", s)
    s = s.replace("\u3002", ".").replace("\uff61", ".")
    if "\\@" in s:
        # \@ の逃がし文字を取り除く。正規表現を使わず、行の長さに比例する時間で終える。
        parts = s.split("@")
        s = "@".join([p.rstrip("\\") for p in parts[:-1]] + [parts[-1]])
    if "@" in s:
        s = _join_strip(s, "@")
        s = _join_strip(s, ".")
    return s


def _join_strip(s, sep):
    """sep の前後の空白を詰める。split と strip だけで書き、行の長さに比例する時間で終える。"""
    parts = s.split(sep)
    if len(parts) == 1:
        return s
    last = len(parts) - 1
    return sep.join(
        p if (i == 0 and last == 0) else
        p.rstrip() if i == 0 else
        p.lstrip() if i == last else
        p.strip()
        for i, p in enumerate(parts)
    )


def _trim_domain(domain):
    """末尾の「.」「-」と、英字を含まないラベルを取り除く。"""
    domain = domain.rstrip(".-")
    while "." in domain:
        head, _, last = domain.rpartition(".")
        if _HAS_LETTER.search(last):
            break
        domain = head.rstrip(".-")
    return domain


def _is_address_shape(domain):
    labels = [x for x in domain.split(".") if x]
    if len(labels) < 2:
        return False
    return bool(_HAS_LETTER.search(labels[-1]))


def find_in_bytes(data):
    """許可されないアドレスの形を探し、{行番号: 件数} を返す。

    一致した文字列は返さない（呼び出し側が誤って出力できないようにするため）。
    """
    result = {}
    for lineno, raw in enumerate(data.replace(b"\x00", b"").split(b"\n"), start=1):
        line = normalize_line(raw)
        if "@" not in line:
            continue
        count = 0
        for m in _DOMAIN_AFTER_AT.finditer(line):
            at = m.start()
            if at == 0 or line[at - 1].isspace():
                continue  # @ の直前に何も無い（デコレーターなど）
            domain = _trim_domain(m.group(1))
            if not _is_address_shape(domain):
                continue
            start = at
            while start > 0 and line[start - 1] in _LOCAL_CHARS:
                start -= 1
            # @ の直前が local 部の文字でない（角括弧・引用符など）なら、常に検出する
            if start < at and line[start:at] + "@" + domain in ALLOWED_ADDRESSES:
                continue
            count += 1
        if count:
            result[lineno] = count
    return result


def has_address(data):
    return bool(find_in_bytes(data))


# --- 出力（一致した文字列は決して出さない） ---

class ScanError(Exception):
    """検査を完了できなかった。メッセージには固定の文と、伏せた表示だけを入れる。"""


class Report:
    def __init__(self):
        self.findings = []  # (場所の表示, 行番号 or None, 件数)
        self.files = 0
        self.blobs = 0
        self.commits = 0
        self.tags = 0
        self.refs = 0
        self._withheld = 0

    def display_path(self, path_bytes):
        """表示用のファイル名。アドレスの形を含むなら伏せる。"""
        if has_address(path_bytes):
            self._withheld += 1
            return "<ファイル名を伏せた #%d>" % self._withheld
        text = path_bytes.decode("utf-8", "backslashreplace")
        return "".join(c if c.isprintable() else "\\x%02x" % ord(c) for c in text)

    def add_content(self, label, data):
        for lineno, count in sorted(find_in_bytes(data).items()):
            self.findings.append((label, lineno, count))

    def add_name(self, label, name_bytes, kind):
        hits = find_in_bytes(name_bytes)
        if hits:
            self.findings.append((label + " (%sの中)" % kind, None, sum(hits.values())))

    def add_path(self, label_fn, path_bytes):
        hits = find_in_bytes(path_bytes)
        if hits:
            self.findings.append((label_fn() + " (ファイル名の中)", None, sum(hits.values())))

    def emit(self, out):
        for label, lineno, count in self.findings:
            if lineno is None:
                out.write("%s: FOUND %s 件数=%d\n" % (PROG, label, count))
            else:
                out.write("%s: FOUND %s 行=%d 件数=%d\n" % (PROG, label, lineno, count))
        total = sum(c for _, _, c in self.findings)
        out.write(
            "%s: 検査した数 ファイル=%d 中身(blob)=%d コミット=%d タグ=%d 参照名=%d\n"
            % (PROG, self.files, self.blobs, self.commits, self.tags, self.refs)
        )
        if total:
            out.write(
                "%s: NG 許可されないメールアドレスの形が %d 件（%d か所）。"
                "一致した文字列は表示しない。\n" % (PROG, total, len(self.findings))
            )
        else:
            out.write("%s: OK 許可されないメールアドレスの形は見つからなかった。\n" % PROG)
        return EXIT_FOUND if total else EXIT_OK


# --- Git ---

def _git_env():
    env = dict(os.environ)
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["GIT_OPTIONAL_LOCKS"] = "0"
    env["LC_ALL"] = "C"
    return env


def git(root, *args, stdin=None, check=True):
    """git を実行する。標準エラーは捨てる（中身を出さない）。"""
    try:
        proc = subprocess.run(
            ["git", *args],
            cwd=root,
            input=stdin,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            env=_git_env(),
        )
    except OSError:
        raise ScanError("git を実行できなかった")
    if check and proc.returncode != 0:
        raise ScanError("git %s が失敗した" % args[0])
    return proc


def is_git_repo(root):
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            cwd=root,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            env=_git_env(),
        )
    except OSError:
        if os.path.exists(os.path.join(root, ".git")):
            raise ScanError(".git があるのに git を実行できなかった")
        return False
    return proc.returncode == 0 and proc.stdout.strip() == b"true"


def cat_file_batch(root, shas):
    """git cat-file --batch で中身を読む。{sha: (型, 中身)} を返す。"""
    shas = list(dict.fromkeys(shas))
    if not shas:
        return {}
    data = b"\n".join(s.encode("ascii") for s in shas) + b"\n"
    out = git(root, "cat-file", "--batch", stdin=data).stdout
    result = {}
    pos = 0
    for sha in shas:
        nl = out.index(b"\n", pos)
        header = out[pos:nl].split(b" ")
        if len(header) != 3:
            raise ScanError("git cat-file の出力を読めなかった")
        size = int(header[2])
        result[sha] = (header[1].decode("ascii"), out[nl + 1:nl + 1 + size])
        pos = nl + 1 + size + 1
    return result


def object_exists(root, sha):
    return git(root, "cat-file", "-e", sha + "^{commit}", check=False).returncode == 0


def configured_remotes(root):
    return set(git(root, "remote").stdout.decode("utf-8", "surrogateescape").split())


def remote_exclusion(root, name):
    """指定なしのモードだけで使う。上流のリモートの追跡参照を除く引数を作る。"""
    if name is None or name not in configured_remotes(root):
        return []
    if any(c in name for c in "*?[\\"):
        raise ScanError("リモートの名前に、照合に使えない文字がある")
    return ["--remotes=" + name]


def upstream_remote(root):
    head = git(root, "symbolic-ref", "-q", "HEAD", check=False)
    if head.returncode != 0:
        return None  # detached HEAD
    ref = head.stdout.decode("utf-8", "surrogateescape").strip()
    name = git(root, "for-each-ref", "--format=%(upstream:remotename)", ref).stdout
    name = name.decode("utf-8", "surrogateescape").strip()
    if not name or name == ".":
        return None
    return name


def parse_pre_push_stdin(raw):
    """pre-push の標準入力を読む。欄が 4 つでない行があれば ScanError。"""
    lines = []
    for line in raw.split(b"\n"):
        if not line.strip():
            continue
        parts = line.split(b" ")
        if len(parts) != 4:
            raise ScanError("pre-push の標準入力に、欄が 4 つでない行がある")
        local_ref, local_sha, remote_ref, remote_sha = parts
        try:
            local_sha = local_sha.decode("ascii")
            remote_sha = remote_sha.decode("ascii")
        except UnicodeDecodeError:
            raise ScanError("pre-push の標準入力を読めなかった")
        if not (_SHA.match(local_sha) and _SHA.match(remote_sha)):
            raise ScanError("pre-push の標準入力を読めなかった")
        lines.append((local_ref, local_sha, remote_ref, remote_sha))
    return lines


def select_commits(root, mode, push_lines):
    if mode == "all":
        return git(root, "rev-list", "--all").stdout.decode("ascii").split()
    if mode == "pre-push":
        tips = [l[1] for l in push_lines if not _ZERO_SHA.match(l[1])]
        if not tips:
            return []
        excl = []
        full = False
        for l in push_lines:
            if _ZERO_SHA.match(l[1]):
                continue  # ブランチの削除。送る中身は無い。
            if _ZERO_SHA.match(l[3]) or not object_exists(root, l[3]):
                full = True  # 新しいブランチ、または push 先の中身が手元で分からない
            else:
                excl.append(l[3])
        if full:
            args = ["rev-list", "--all", *tips]
        else:
            # --not はそれ以降の指定の意味を反転させるので、1 回だけ置く
            args = ["rev-list", *tips, "--not", *excl]
        return git(root, *args).stdout.decode("ascii").split()
    # 指定なし
    up = upstream_remote(root)
    excl = remote_exclusion(root, up)
    args = ["rev-list", "--all"] + (["--not", *excl] if excl else [])
    return git(root, *args).stdout.decode("ascii").split()


def check_blob(report, label, data):
    if data.startswith(_LFS_POINTER):
        raise ScanError("Git LFS のポインタがあり、中身を検査できない: " + label)
    report.blobs += 1
    report.add_content(label, data)


def scan_tag_chain(root, report, sha, seen):
    """注釈付きタグを辿り、各タグのオブジェクトを検査する。行き先がコミット以外なら止める。"""
    typ = cat_file_batch(root, [sha])[sha][0]
    while typ == "tag":
        if sha in seen:
            return
        seen.add(sha)
        body = cat_file_batch(root, [sha])[sha][1]
        report.tags += 1
        report.add_content("tag " + sha, body)
        m = re.match(rb"object ([0-9a-f]+)\ntype (\w+)\n", body)
        if not m:
            raise ScanError("タグのオブジェクトを読めなかった: tag " + sha)
        sha, typ = m.group(1).decode("ascii"), m.group(2).decode("ascii")
    if typ != "commit":
        raise ScanError("コミット以外（%s）を指すタグがあり、検査の対象外になる" % typ)


def scan_git(root, report, mode, push_lines):
    # 1) 追跡されているファイル（作業ツリーの中身）
    tracked = [p for p in git(root, "ls-files", "-z").stdout.split(b"\x00") if p]
    for p in dict.fromkeys(tracked):
        scan_worktree_file(root, p, report)

    # 2) インデックス（ステージ済み）の中身
    index_entries = []
    for entry in git(root, "ls-files", "-s", "-z").stdout.split(b"\x00"):
        if not entry:
            continue
        meta, path = entry.split(b"\t", 1)
        mode_bits, sha, _stage = meta.split(b" ")
        if mode_bits == b"160000":
            raise ScanError("サブモジュールがあり、中身を検査できない: index:"
                            + report.display_path(path))
        index_entries.append((sha.decode("ascii"), path))
    blobs = cat_file_batch(root, [s for s, _ in index_entries])
    for sha, path in index_entries:
        check_blob(report, "index:" + report.display_path(path), blobs[sha][1])

    # 3) 参照の名前（すべて）と、注釈付きタグ
    refs = git(root, "for-each-ref", "--format=%(objectname) %(objecttype) %(refname)").stdout
    seen_tags = set()
    for i, line in enumerate(l for l in refs.split(b"\n") if l):
        sha, typ, name = line.split(b" ", 2)
        report.refs += 1
        report.add_name("参照 #%d" % (i + 1), name, "参照の名前")
        typ = typ.decode("ascii")
        if typ == "tag":
            scan_tag_chain(root, report, sha.decode("ascii"), seen_tags)
        elif typ != "commit":
            raise ScanError("コミット以外（%s）を指す参照があり、検査の対象外になる" % typ)

    # 4) pre-push の標準入力の参照の名前と、push するオブジェクト
    for i, (local_ref, local_sha, remote_ref, _r) in enumerate(push_lines):
        report.refs += 2
        report.add_name("push の行 %d の local ref" % (i + 1), local_ref, "参照の名前")
        report.add_name("push の行 %d の remote ref" % (i + 1), remote_ref, "参照の名前")
        if not _ZERO_SHA.match(local_sha):
            scan_tag_chain(root, report, local_sha, seen_tags)

    # 5) コミットの範囲
    commits = select_commits(root, mode, push_lines)
    objects = cat_file_batch(root, commits)
    blob_where = {}
    for c in commits:
        report.commits += 1
        report.add_content("commit " + c, objects[c][1])
        tree = git(root, "ls-tree", "-r", "-z", "--full-tree", c).stdout
        for entry in tree.split(b"\x00"):
            if not entry:
                continue
            meta, path = entry.split(b"\t", 1)
            mode_bits, typ, sha = meta.split(b" ")
            if typ != b"blob":
                raise ScanError("サブモジュールがあり、中身を検査できない: commit %s path:%s"
                                % (c, report.display_path(path)))
            report.add_path(
                lambda c=c, path=path: "commit %s path:%s" % (c, report.display_path(path)),
                path,
            )
            sha = sha.decode("ascii")
            if sha not in blob_where:
                blob_where[sha] = (c, path)
    contents = cat_file_batch(root, list(blob_where))
    for sha, (c, path) in blob_where.items():
        check_blob(report, "commit %s file:%s" % (c, report.display_path(path)),
                   contents[sha][1])


def scan_worktree_file(root, rel, report):
    """作業ツリーのファイル 1 つを、ファイル名と中身の両方で検査する。"""
    full = os.path.join(os.fsencode(root), rel)
    label = report.display_path(rel)
    report.add_path(lambda: label, rel)
    if os.path.islink(full):
        report.files += 1
        report.add_content(label, os.readlink(full))
        return
    if not os.path.isfile(full):
        return  # 作業ツリーから消えたファイル（インデックス側で検査する）
    report.files += 1
    try:
        with open(full, "rb") as f:
            data = f.read()
    except OSError:
        raise ScanError("ファイルを読めなかった: " + label)
    if data.startswith(_LFS_POINTER):
        raise ScanError("Git LFS のポインタがあり、中身を検査できない: " + label)
    report.add_content(label, data)


# --- リポジトリでない場合: .gitignore を考慮してルートの下を歩く ---

def _gitignore_to_regex(pat):
    """.gitignore の 1 行を、(正規表現, 否定か, ディレクトリだけか) にする。"""
    negate = False
    if pat.startswith("!"):
        negate, pat = True, pat[1:]
    elif pat.startswith("\\!") or pat.startswith("\\#"):
        pat = pat[1:]
    dir_only = pat.endswith("/")
    pat = pat.rstrip("/")
    if not pat:
        return None
    anchored = "/" in pat
    pat = pat.lstrip("/")
    i, out = 0, []
    while i < len(pat):
        if pat.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
        elif pat.startswith("/**", i) and i + 3 == len(pat):
            out.append("/.*")
            i += 3
        elif pat.startswith("**", i):
            out.append(".*")
            i += 2
        elif pat[i] == "*":
            out.append("[^/]*")
            i += 1
        elif pat[i] == "?":
            out.append("[^/]")
            i += 1
        elif pat[i] == "[":
            j = pat.find("]", i + 1)
            if j == -1:
                out.append(re.escape("["))
                i += 1
            else:
                body = pat[i + 1:j]
                if body.startswith("!"):
                    body = "^" + body[1:]
                out.append("[" + body.replace("\\", "\\\\") + "]")
                i = j + 1
        elif pat[i] == "\\" and i + 1 < len(pat):
            out.append(re.escape(pat[i + 1]))
            i += 2
        else:
            out.append(re.escape(pat[i]))
            i += 1
    body = "".join(out)
    rx = ("^" if anchored else "^(?:.*/)?") + body + "$"
    return re.compile(rx), negate, dir_only


def load_gitignore(dir_path):
    rules = []
    path = os.path.join(dir_path, ".gitignore")
    if not os.path.isfile(path):
        return rules
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.read().splitlines()
    except OSError:
        raise ScanError(".gitignore を読めなかった")
    for line in lines:
        if not line or line.startswith("#"):
            continue
        stripped = line.rstrip(" ")
        if stripped.endswith("\\") and len(stripped) < len(line):
            stripped += " "
        rule = _gitignore_to_regex(stripped)
        if rule:
            rules.append(rule)
    return rules


def is_ignored(stack, rel_path, is_dir):
    """stack は [(基準ディレクトリの相対パス, 規則の一覧)]。後の規則ほど優先。"""
    ignored = False
    for base, rules in stack:
        sub = rel_path[len(base) + 1:] if base else rel_path
        for rx, negate, dir_only in rules:
            if dir_only and not is_dir:
                continue
            if rx.match(sub):
                ignored = not negate
    return ignored


def scan_tree(root, report):
    def walk(rel_dir, stack):
        abs_dir = os.path.join(root, rel_dir) if rel_dir else root
        stack = stack + [(rel_dir, load_gitignore(abs_dir))]
        try:
            names = sorted(os.listdir(abs_dir))
        except OSError:
            raise ScanError("ディレクトリを読めなかった")
        for name in names:
            if name == ".git":
                continue
            rel = rel_dir + "/" + name if rel_dir else name
            full = os.path.join(abs_dir, name)
            is_dir = os.path.isdir(full) and not os.path.islink(full)
            if is_ignored(stack, rel, is_dir):
                continue
            if is_dir:
                walk(rel, stack)
            else:
                scan_worktree_file(root, os.fsencode(rel), report)

    walk("", [])


# --- 入口 ---

def default_root():
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.dirname(os.path.dirname(here))


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        # 引数の値を表示しない（リモートの URL などが混ざるおそれがあるため）
        raise ScanError("引数が正しくない")


def run(argv, stdin, out):
    parser = _Parser(prog=PROG, description="公開前のメールアドレス検査")
    parser.add_argument("--root", default=None,
                        help="検査するルート（省略時はこのスクリプトから見たプロジェクトのルート）")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--all-history", action="store_true",
                       help="全履歴を検査する（CI は必ずこれを使う）")
    group.add_argument("--pre-push", action="store_true",
                       help="pre-push フックから呼ぶ。標準入力の push 対象を検査する")
    args = parser.parse_args(argv)
    root = os.path.abspath(args.root or default_root())
    if not os.path.isdir(root):
        raise ScanError("ルートがディレクトリではない")

    report = Report()
    if is_git_repo(root):
        mode = "all" if args.all_history else "pre-push" if args.pre_push else "default"
        out.write("%s: Git のリポジトリとして検査する（モード: %s）\n" % (PROG, mode))
        push_lines = []
        if args.pre_push:
            raw = stdin.buffer.read() if hasattr(stdin, "buffer") else stdin.read()
            push_lines = parse_pre_push_stdin(raw)
        scan_git(root, report, mode, push_lines)
    else:
        if args.pre_push or args.all_history:
            raise ScanError("Git のリポジトリではないのに、Git のモードが指定された")
        out.write("%s: リポジトリではないので、.gitignore を考慮してルートの下を検査する\n" % PROG)
        scan_tree(root, report)
    return report.emit(out)


def main(argv=None):
    try:
        code = run(sys.argv[1:] if argv is None else argv, sys.stdin, sys.stdout)
    except ScanError as e:
        # ScanError のメッセージは、固定の文と伏せた表示だけ（一致した文字列を含まない）。
        sys.stdout.flush()
        sys.stderr.write("%s: ERROR %s。検査を完了できなかったので失敗として扱う。\n" % (PROG, e))
        code = EXIT_ERROR
    except SystemExit:
        raise
    except BaseException as e:  # noqa: BLE001
        # 例外のメッセージは出さない（中身が混ざるおそれがあるため）。型の名前だけを出す。
        sys.stdout.flush()
        sys.stderr.write(
            "%s: ERROR %s。検査を完了できなかったので失敗として扱う。\n"
            % (PROG, type(e).__name__)
        )
        code = EXIT_ERROR
    sys.stdout.flush()
    return code


if __name__ == "__main__":
    sys.exit(main())
