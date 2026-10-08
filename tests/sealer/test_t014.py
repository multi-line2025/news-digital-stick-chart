"""取得の前の関門と、申し送りの修正のテスト。T-014。

実行（プロジェクトのルートで）:
    PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest discover -s tests/sealer -v

ネットワークは使わない（drand・ots は偽物、HTTP は差し替えた handler）。仮のプロジェクトで動かし、
本物の sealed/ には書かない。各項目について、止まることと通ることの両方を確かめる。
  1. acquisition-start の前に candidates が要る（書く仕組みと検証。T-013 の監査 B-1）
  2. 手順4の開始の記録（method-access）と関門 require_method_access
  3. threshold-access の関門の、候補の順序の検査
  4. netfetch がリダイレクトを拒む（T-009 の監査 軽1）
  5. 関門の root はプロジェクトのルートに固定（T-009 の監査 軽2）
  6. 手順書の記述（T-009 の軽3・軽4、T-013 の軽1・軽3、案B）
"""

import datetime
import email.message
import inspect
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import urllib.error
import urllib.request
import urllib.response

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import test_ledger as tl  # noqa: E402
import test_writers as tw  # noqa: E402
from test_ledger import T0, H, run_verify  # noqa: E402

ledger = tl.ledger
import netfetch  # noqa: E402
import seal_access  # noqa: E402
import seal_acquisition  # noqa: E402
import seal_method  # noqa: E402
import seal_records  # noqa: E402

PROJECT = tl.PROJECT
DOC = os.path.join(PROJECT, "docs", "verify", "periods-seal.md")
MIN = datetime.timedelta(minutes=1)


class Case(tw.WriterCase):
    def method(self, now, fetch=None):
        return seal_method.seal(self.root, now, "ots", drand_fetch=fetch or tw.FakeDrand(now),
                                runner=tw.FakeOts())

    def step3(self, now, order1=True):
        """手順3（acquisition-start と result）。T-037：method-access の前には順番1（stats-order1）が
        要るので、order1 が真なら、まだ無ければ result のあとに仮の順番1の記録を足す。"""
        s, _r, _o = self.start(now)
        r, _r2, _o2 = self.result(now + H, s["seq"])
        if order1:
            self.ensure_order1(now + H)
        return s["seq"], r["seq"]

    def ledger_bytes(self):
        return ledger.read_ledger(self.ledger)

    def records(self):
        return ledger.verify_chain(self.ledger_bytes())

    def verify_fails(self, cmds, msg):
        for c in cmds:
            r = run_verify(self.root, c)
            self.assertEqual(r.returncode, 1, (c, r.stdout.decode()))
            self.assertIn(msg, r.stderr.decode(), c)


# ---------------------------------------------------------------- 1. acquisition-start の前の candidates


class TestCandidatesBeforeStart(Case):
    def test_writer_refuses_start_without_candidates(self):
        self.seal(with_cand=False)
        before, data = self.snapshot(), self.ledger_bytes()
        fake = tw.FakeDrand(T0 + H)
        with self.assertRaisesRegex(ledger.LedgerError, "candidates の記録が無い"):
            seal_acquisition.start(self.root, tw.CODE_REL, T0 + H, "ots", drand_fetch=fake,
                                   runner=tw.FakeOts())
        self.assertEqual(fake.urls, [])           # drand を取りにいく前に止まる
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.ledger_bytes(), data)

    def test_precheck_refuses_start_without_candidates(self):
        """書く仕組みの入口を飛ばして共通の手順を直接呼んでも、追記の前の照合で止まる。"""
        self.seal(with_cand=False)
        data = self.ledger_bytes()
        before = self.snapshot()
        doc = tl.drand_doc(ledger.ACQ_START_KIND, 30_000_000,
                           head=ledger.expected_ledger_head(data, 2))
        with self.assertRaisesRegex(ledger.LedgerError, "より前に、candidates の記録が無い"):
            seal_records.write_doc_record(self.root, ledger.ACQ_START_KIND, doc, data, "",
                                          T0 + H, "ots", runner=tw.FakeOts())
        self.assertEqual(self.snapshot(), before)

    def test_writer_passes_with_candidates(self):
        self.seal()
        s, _rel, _o = self.start(T0 + H)
        self.assertEqual(s["seq"], self.cand_seq + 1)
        out = self.verify_ok("all")
        self.assertIn("最初の acquisition-start（seq %d）より前に candidates の記録がある" % s["seq"],
                      out)

    def test_verify_fails_on_start_without_candidates(self):
        """仕組みを通さずに candidates の無いまま acquisition-start を足すと、検証が失敗する。"""
        self.seal(with_cand=False)
        start = self.add_start(T0 + H, 30_000_000)
        self.verify_fails(("acquisition", "candidates", "all"),
                          "acquisition-start の記録（seq %d）より前に、candidates の記録が無い"
                          % start)

    def test_verify_fails_when_candidates_only_after_start(self):
        self.seal(with_cand=False)
        self.add_start(T0 + H, 30_000_000)
        self.add_cand(T0 + 2 * H)
        r = run_verify(self.root, "all")
        self.assertEqual(r.returncode, 1)

    def test_verify_passes_when_candidates_before_start(self):
        self.seal(with_cand=False)
        self.add_cand(T0 + H)
        start = self.add_start(T0 + 2 * H, 30_000_000)
        self.add_result(T0 + 3 * H, start)
        for c in ("acquisition", "candidates", "all"):
            r = run_verify(self.root, c)
            self.assertEqual(r.returncode, 0, (c, r.stderr.decode()))


# ---------------------------------------------------------------- 2. method-access と関門


class TestMethodAccessWriter(Case):
    def test_kind_is_allowed_and_not_a_cut(self):
        self.assertIn("method-access", ledger.ALLOWED_KINDS)
        self.assertIn(ledger.METHOD_ACCESS_KIND, ledger.DRAND_RECORD_KINDS)
        self.assertNotIn(ledger.METHOD_ACCESS_KIND, ledger.ADOPTED_KINDS)

    def test_written_and_verified(self):
        self.seal()
        _s, rseq = self.step3(T0 + H, order1=False)
        self.add_order1(T0 + 2 * H)               # T-037：method-access の前の順番1
        rseq = self.add_order1b(T0 + 2 * H)       # T-043：method-access の前の順番1b
        rec, rel, ots_path = self.method(T0 + 3 * H)
        self.assertEqual(rec["seq"], rseq + 1)
        self.assertEqual(rec["kind"], "method-access")
        self.assertEqual(os.path.basename(ots_path), ledger.ots_name(rec["seq"]))
        doc = self.doc_of(rel)
        self.assertEqual(sorted(doc), list(ledger.METHOD_DOC_KEYS))
        self.assertEqual(doc["step"], 4)
        self.assertEqual((doc["block_start"], doc["block_end"]), ("2015-03-02", "2020-12-14"))
        self.assertEqual(doc["ledger_head"],
                         {"seq": rseq, "sha256": ledger.prefix_digest(self.ledger_bytes(), rseq)})
        self.assertEqual(doc["drand"]["chain_hash"], netfetch.QUICKNET)
        out = self.verify_ok("all")
        self.assertIn("method-access seq %d: ledger_head は直前の記録" % rec["seq"], out)
        self.assertIn("区画 2015-03-02〜2020-12-14 は periods の 1 件目の method の区画と一致", out)
        self.assertIn("採用は保留（threshold-access の記録が無いため）", out)
        self.commit("記録")
        # T-056：仮の順番1・1b の記録（head が実在しない）では、--rev auto の順番1・1b の計算し直しが止まるので、
        # 時刻証明と対象のファイルは targets --rev auto で、残りは all（working）で確かめる
        self.verify_ok("targets", "--rev", "auto")
        self.verify_ok("all")

    def test_refused_without_candidates(self):
        self.seal(with_cand=False)
        before = self.snapshot()
        fake = tw.FakeDrand(T0 + H)
        with self.assertRaisesRegex(ledger.LedgerError, "candidates の記録が無い"):
            self.method(T0 + H, fetch=fake)
        self.assertEqual(fake.urls, [])
        self.assertEqual(self.snapshot(), before)

    def test_refused_without_acquisition_result(self):
        self.seal()
        before = self.snapshot()
        with self.assertRaisesRegex(ledger.LedgerError, "acquisition-result の記録が無い"):
            self.method(T0 + H)
        self.start(T0 + H)                         # start だけで result が無い
        before = self.snapshot()
        with self.assertRaisesRegex(ledger.LedgerError, "acquisition-result の記録が無い"):
            self.method(T0 + 2 * H)
        self.assertEqual(self.snapshot(), before)

    def test_precheck_refuses_bad_docs(self):
        """共通の手順を直接呼んでも、区画・step・キー・ledger_head・前提の照合で止まる。"""
        self.seal()
        self.step3(T0 + H)
        data = self.ledger_bytes()
        n = len(self.records()) + 1
        head = ledger.expected_ledger_head(data, n)
        before = self.snapshot()
        bad = {
            "区画": dict(tl.drand_doc("method-access", 30_000_000, head=head),
                       block_end="2020-12-15"),
            "step が 4 でない": dict(tl.drand_doc("method-access", 30_000_000, head=head), step=3),
            "キー": dict(tl.drand_doc("method-access", 30_000_000, head=head), extra=1),
            "ledger_head": tl.drand_doc("method-access", 30_000_000,
                                        head={"seq": 1, "sha256": "0" * 64}),
        }
        for msg, doc in bad.items():
            with self.assertRaisesRegex(ledger.LedgerError, msg):
                seal_records.write_doc_record(self.root, ledger.METHOD_ACCESS_KIND, doc, data, "",
                                              T0 + 3 * H, "ots", runner=tw.FakeOts())
        self.assertEqual(self.snapshot(), before)

    def test_method_access_does_not_change_adoption(self):
        """method-access の後・threshold-access の前の triggers は採用される（区切りは変わらない）。
        T-023：method-access の後に J を持つ triggers は置けないので、J の無いきっかけ
        （共起の網の日数）で確かめる。"""
        self.seal()
        self.step3(T0 + H)
        self.method(T0 + 3 * H)
        trec = self.seal_triggers(T0 + 4 * H, network_window_days=500)
        out = self.verify_ok("adopted")
        self.assertIn("採用は保留（threshold-access の記録が無いため）", out)
        access, _rel, _o = self.access(T0 + 5 * H)
        out = self.verify_ok("all")
        self.assertIn("区切り：最初の threshold-access の記録 = seq %d" % access["seq"], out)
        self.assertIn("periods-triggers: 採用 = seq %d" % trec["seq"], out)
        self.assertIn("candidates: 採用 = seq %d" % self.cand_seq, out)


class TestMethodAccessVerify(Case):
    """仕組みを通さずに足した、壊れた method-access で検証が失敗する。"""

    def test_without_result_fails(self):
        self.seal()
        self.start(T0 + H)
        m = self.add_method(T0 + 2 * H, 30_000_000)
        self.verify_fails(("method", "all"),
                          "method-access の記録（seq %d）より前に、acquisition-result の記録が無い" % m)

    def test_without_candidates_fails(self):
        self.seal(with_cand=False)
        m = self.add_method(T0 + H, 30_000_000)
        self.verify_fails(("method", "all"),
                          "method-access の記録（seq %d）より前に、candidates の記録が無い" % m)

    def test_wrong_block_fails(self):
        self.seal()
        self.step3(T0 + H)
        self.add_method(T0 + 3 * H, 30_000_000, block_start="2015-01-01")
        self.verify_fails(("method", "all"), "method の区画")

    def test_wrong_step_and_extra_key_fail(self):
        for kw, msg in (({"step": 3}, "step が 4 でない"), ({"fetch": {}}, "キー")):
            self.tearDown()
            self.setUp()
            self.seal()
            self.step3(T0 + H)
            self.add_method(T0 + 3 * H, 30_000_000, **kw)
            self.verify_fails(("method", "all"), msg)

    def test_ledger_head_mismatch_fails(self):
        self.seal()
        self.step3(T0 + H)
        self.add_method(T0 + 3 * H, 30_000_000, head={"seq": 1, "sha256": "0" * 64})
        self.verify_fails(("method", "all"), "ledger_head")

    def test_tampered_doc_fails(self):
        self.seal()
        self.step3(T0 + H)
        _rec, rel, _o = self.method(T0 + 3 * H)
        with open(os.path.join(self.root, rel), "ab") as f:
            f.write(b" ")
        self.verify_fails(("method", "all"), "一致しない")

    def test_no_method_access_is_reported(self):
        self.seal()
        out = self.verify_ok("method")
        self.assertIn("method-access の記録：なし", out)


class TestMethodGate(Case):
    def gate(self):
        return self.method_gate()

    def test_stops_until_record_then_passes(self):
        self.seal()
        with self.assertRaisesRegex(ledger.MethodAccessRequired, "method-access の記録が鎖に無い"):
            self.gate()
        self.step3(T0 + H)
        with self.assertRaises(ledger.MethodAccessRequired):
            self.gate()
        self.access(T0 + 3 * H)                    # threshold-access でも開かない
        with self.assertRaises(ledger.MethodAccessRequired):
            self.gate()
        rec, _rel, _o = self.method(T0 + 4 * H)
        self.assertEqual(self.gate(), rec)
        self.assertTrue(issubclass(ledger.MethodAccessRequired, ledger.LedgerError))

    def ready(self):
        self.seal()
        self.step3(T0 + H)
        return self.method(T0 + 3 * H)

    def test_stops_on_tampered_doc(self):
        _rec, rel, _o = self.ready()
        with open(os.path.join(self.root, rel), "ab") as f:
            f.write(b" ")
        with self.assertRaisesRegex(ledger.MethodAccessRequired, "一致しない"):
            self.gate()

    def test_stops_on_missing_ots(self):
        _rec, _rel, ots_path = self.ready()
        os.rename(ots_path, os.path.join(self.root, "moved.ots"))
        with self.assertRaisesRegex(ledger.MethodAccessRequired, "時刻証明"):
            self.gate()

    def test_stops_on_tampered_result_doc(self):
        self.ready()
        r = [x for x in self.records() if x["kind"] == ledger.ACQ_RESULT_KIND][0]
        path = os.path.join(self.root, r["targets"][0]["path"])
        with open(path, "ab") as f:
            f.write(b" ")
        with self.assertRaisesRegex(ledger.MethodAccessRequired, "acquisition-result"):
            self.gate()

    def test_stops_on_tampered_candidates_output(self):
        self.ready()
        c = [x for x in self.records() if x["kind"] == ledger.CANDIDATES_KIND][0]
        out = ledger.output_target(c)
        with open(os.path.join(self.root, out["path"]), "ab") as f:
            f.write(b" ")
        with self.assertRaisesRegex(ledger.MethodAccessRequired,
                                    "seq %d の output のファイルが記録と一致しない" % c["seq"]):
            self.gate()

    def test_stops_on_bypass_record_without_prerequisites(self):
        self.seal()
        self.add_method(T0 + H, 30_000_000)
        with self.assertRaisesRegex(ledger.MethodAccessRequired, "acquisition-result の記録が無い"):
            self.gate()

    def test_stops_on_bypass_record_with_wrong_block(self):
        self.seal()
        self.step3(T0 + H)
        self.add_method(T0 + 3 * H, 30_000_000, block_end="2020-12-31")
        with self.assertRaisesRegex(ledger.MethodAccessRequired, "method の区画"):
            self.gate()

    def test_gate_cli_fixed_root(self):
        self.seal()
        tw.copy_sealer(self.root)
        cmd = [sys.executable, "-B", os.path.join(self.root, "src", "sealer", "seal_method.py"),
               "gate"]
        r = subprocess.run(cmd + ["--root", self.root], capture_output=True)
        self.assertEqual(r.returncode, 2)
        r = subprocess.run(cmd, capture_output=True)
        self.assertEqual(r.returncode, 1)
        self.assertIn("method-access の記録が鎖に無い", r.stderr.decode())
        self.step3(T0 + H)
        self.method(T0 + 3 * H)
        r = subprocess.run(cmd, capture_output=True)
        self.assertEqual(r.returncode, 0, r.stderr.decode())
        self.assertIn("記録からは検出できない", r.stdout.decode())

    def test_docstring_states_the_limit(self):
        self.assertIn("記録からは検出できない", ledger.require_method_access.__doc__)


# ---------------------------------------------------------------- 3. threshold-access の関門の候補の順序


class TestThresholdGateCandidates(Case):
    def gate(self):
        return self.threshold_gate()

    def test_passes_with_candidates_before(self):
        self.seal()
        rec, _rel, _o = self.access(T0 + H)
        self.assertEqual(self.gate(), rec)

    def test_writer_refuses_without_candidates(self):
        self.seal(with_cand=False)
        before = self.snapshot()
        fake = tw.FakeDrand(T0 + H)
        with self.assertRaisesRegex(ledger.LedgerError, "candidates の記録が無い"):
            seal_access.seal(self.root, T0 + H, "ots", drand_fetch=fake, runner=tw.FakeOts())
        self.assertEqual(fake.urls, [])
        self.assertEqual(self.snapshot(), before)

    def test_stops_without_candidates(self):
        self.seal(with_cand=False)
        self.add_access(T0 + H, 30_000_000)
        with self.assertRaisesRegex(ledger.ThresholdAccessRequired, "candidates の記録が無い"):
            self.gate()

    def test_stops_when_candidates_only_after_access(self):
        self.seal(with_cand=False)
        access = self.add_access(T0 + H, 30_000_000)
        self.add_cand(T0 + 2 * H)
        with self.assertRaisesRegex(ledger.ThresholdAccessRequired,
                                    "seq %d より前に candidates の記録が無い" % access):
            self.gate()

    def test_stops_when_candidates_after_acquisition_start(self):
        self.seal()
        self.start(T0 + H)
        self.add_cand(T0 + 2 * H)                  # 仕組みを通さずに足した遅い候補
        self.add_access(T0 + 3 * H, 30_000_000)
        with self.assertRaisesRegex(ledger.ThresholdAccessRequired, "より後にある"):
            self.gate()

    def test_stops_when_candidates_output_tampered(self):
        self.seal()
        self.access(T0 + H)
        c = [x for x in self.records() if x["kind"] == ledger.CANDIDATES_KIND][0]
        with open(os.path.join(self.root, ledger.output_target(c)["path"]), "ab") as f:
            f.write(b" ")
        with self.assertRaisesRegex(ledger.ThresholdAccessRequired,
                                    "seq %d の output のファイルが記録と一致しない" % c["seq"]):
            self.gate()


# ---------------------------------------------------------------- 4. リダイレクトを拒む


class FakeHTTPS(urllib.request.BaseHandler):
    """https の通信の代わり。routes = {URL: (状態, 転送先 か None, 本文)}。要求を控える。"""

    handler_order = 100   # 本物の HTTPSHandler より先に呼ばれるようにする（通信しない）

    def __init__(self, routes):
        self.routes, self.seen = routes, []

    def https_open(self, req):
        self.seen.append(req.full_url)
        code, location, body = self.routes[req.full_url]
        headers = email.message.Message()
        if location:
            headers["Location"] = location
        resp = urllib.response.addinfourl(io.BytesIO(body), headers, req.full_url, code)
        resp.msg = "fake"
        return resp


class TestRedirect(unittest.TestCase):
    URL = netfetch.DRAND_URLS[0]

    def opener(self, routes):
        h = FakeHTTPS(routes)
        op = netfetch.build_no_redirect_opener(h)
        return h, (lambda req, timeout: op.open(req, timeout=timeout))

    def test_redirect_refused_without_following_or_retry(self):
        for code in (301, 302, 303, 307, 308):
            target = "https://example.com/elsewhere"
            h, op = self.opener({self.URL: (code, target, b"")})
            sleeps = []
            with self.assertRaisesRegex(netfetch.RedirectRefused, "リダイレクト"):
                netfetch.http_get(self.URL, sleep=sleeps.append, opener=op)
            self.assertEqual(h.seen, [self.URL], code)     # 転送先には送っていない
            self.assertEqual(sleeps, [])                   # 再試行もしない

    def test_redirect_inside_allowed_host_also_refused(self):
        other = netfetch.DRAND_URLS[1]
        h, op = self.opener({self.URL: (302, other, b""), other: (200, None, b"x")})
        with self.assertRaises(netfetch.RedirectRefused):
            netfetch.http_get(self.URL, sleep=lambda s: None, opener=op)
        self.assertEqual(h.seen, [self.URL])

    def test_plain_response_passes(self):
        h, op = self.opener({self.URL: (200, None, b"body")})
        self.assertEqual(netfetch.http_get(self.URL, opener=op), b"body")
        self.assertEqual(h.seen, [self.URL])

    def test_response_url_differs_is_refused(self):
        class Resp(io.BytesIO):
            def geturl(self):
                return "https://example.com/other"

        def op(req, timeout):
            return Resp(b"x")
        with self.assertRaises(netfetch.RedirectRefused):
            netfetch.http_get(self.URL, sleep=lambda s: None, opener=op)

    def test_default_opener_refuses_redirects(self):
        default = inspect.signature(netfetch.http_get).parameters["opener"].default
        self.assertIs(default, netfetch.no_redirect_urlopen)
        self.assertIsNot(default, urllib.request.urlopen)
        self.assertTrue(any(isinstance(h, netfetch._RefuseRedirect)
                            for h in netfetch._OPENER.handlers))
        self.assertTrue(issubclass(netfetch.RedirectRefused, netfetch.FetchError))


# ---------------------------------------------------------------- 5. 関門の root の固定


class TestGateRoot(Case):
    def test_signatures_take_no_root(self):
        """関門は引数を一つも取らない（T-017。テスト用の root の引数も外した）。"""
        for fn in (ledger.require_threshold_access, ledger.require_method_access):
            self.assertEqual(list(inspect.signature(fn).parameters), [], fn.__name__)
            with self.assertRaises(TypeError):
                fn(self.root)                      # 位置で root を渡すことはできない
            with self.assertRaises(TypeError):
                fn(_test_root=self.root)           # 名前で渡すこともできない

    def test_project_root_is_this_repository(self):
        self.assertEqual(os.path.realpath(ledger.PROJECT_ROOT), os.path.realpath(PROJECT))

    def test_default_reads_project_not_a_fake_folder(self):
        """偽の記録で関門が通る仮のプロジェクトがあっても、差し替えない関門は本物を読む。"""
        self.seal()
        self.step3(T0 + H)
        self.method(T0 + 3 * H)
        self.access(T0 + 4 * H)
        self.method_gate()
        self.threshold_gate()
        self.assertEqual(os.path.realpath(ledger.PROJECT_ROOT), os.path.realpath(PROJECT))
        real = ledger.verify_chain(ledger.read_ledger(
            os.path.join(PROJECT, "sealed", "ledger.jsonl")))
        kinds = {r["kind"] for r in real}
        if ledger.METHOD_ACCESS_KIND not in kinds:
            with self.assertRaisesRegex(ledger.MethodAccessRequired,
                                        "method-access の記録が鎖に無い"):
                ledger.require_method_access()
        if ledger.THRESHOLD_ACCESS_KIND not in kinds:
            with self.assertRaisesRegex(ledger.ThresholdAccessRequired,
                                        "threshold-access の記録が鎖に無い"):
                ledger.require_threshold_access()

    def test_access_gate_cli_rejects_root(self):
        r = subprocess.run([sys.executable, "-B", os.path.join(tl.SRC, "seal_access.py"), "gate",
                            "--root", self.root], capture_output=True)
        self.assertEqual(r.returncode, 2)


# ---------------------------------------------------------------- 6. 手順書


class TestDocStatements(unittest.TestCase):
    def setUp(self):
        with open(DOC, encoding="utf-8") as f:
            self.text = f.read()

    def test_required_statements(self):
        for phrase in (
                "stamp が失敗しても",                       # T-009 軽3
                "オフラインで偽造した Pending の `.ots` は",  # T-009 軽4
                "出力の形の検査の範囲",                      # T-013 軽3
                "手順4の記録と関門の限界",                    # T-013 軽1
                "案B",                                     # オーナーの決定
                "require_method_access()",
                "method-access",
                "リダイレクト"):
            self.assertIn(phrase, self.text)

    def test_kind_count_is_seven(self):
        self.assertIn("下の表の10だけ", self.text)   # T-031・T-037 で kind を加えた
        self.assertIn("| `method-access` |", self.text)


if __name__ == "__main__":
    unittest.main()
