"""固定 PDF.js 資產的原始位元組、真實 HTTP MIME 與私人網站轉送契約。"""
from functools import partial
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
VENDOR = ROOT / 'assets/vendor/pdfjs/6.3.289'
sys.path.insert(0, str(ROOT / 'server'))
try:
    import private_web_gateway as gateway
except ModuleNotFoundError as error:
    if error.name != 'private_web_gateway':
        raise
    gateway = None  # 分享包不包含私人網站；仍驗證資產雜湊與中文測試文件。

SPEC = importlib.util.spec_from_file_location('st_pdf_asset_server_test', ROOT / 'server/server.py')
ST = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ST)


class PdfAssetsTests(unittest.TestCase):
    def test_vendor_bytes_match_official_package_inventory(self):
        manifest = json.loads((VENDOR / '來源資訊.json').read_text(encoding='utf-8'))
        self.assertEqual(manifest['版本'], '6.3.289')
        self.assertEqual(manifest['SHA512'], 'sha512-ZHjSVpDa3D6izMq8/04lvkhkATUmL9px6ChPaXc1k6nU2Mrhlg1/7F0bdUqCwUjw3NsPTfPZsMDUU6ZIcRaeQw==')
        expected = manifest['檔案SHA256']
        self.assertEqual(set(expected), {p.relative_to(VENDOR).as_posix() for p in VENDOR.rglob('*')
                                         if p.is_file() and p.name != '來源資訊.json'})
        for rel, digest in expected.items():
            with self.subTest(asset=rel):
                target = VENDOR / rel
                self.assertTrue(target.resolve().is_relative_to(VENDOR.resolve()))
                self.assertEqual(hashlib.sha256(target.read_bytes()).hexdigest(), digest)
        for required in ('pdf.min.mjs', 'pdf.worker.min.mjs', 'LICENSE', 'cmaps/UniCNS-UCS2-H.bcmap',
                         'cmaps/LICENSE', 'standard_fonts/LICENSE_FOXIT', 'wasm/LICENSE_OPENJPEG'):
            self.assertIn(required, expected)

    def test_chinese_fixture_matches_cns_character_collection(self):
        data = (ROOT / 'tests/fixtures/pdf_import/中文多頁計畫.pdf').read_bytes()
        self.assertIn(b'/UniCNS-UCS2-H', data)
        self.assertIn(b'/Ordering (CNS1)', data)
        self.assertNotIn(b'/UniGB-UCS2-H', data)

    @unittest.skipIf(gateway is None, '分享包不包含私人網站模組')
    def test_modules_and_auxiliary_assets_through_real_server_and_gateway(self):
        with tempfile.TemporaryDirectory() as temp:
            upstream = ThreadingHTTPServer(('127.0.0.1', 0), partial(ST.Handler, directory=str(ROOT)))
            settings = gateway.Settings(
                listen_host='127.0.0.1', listen_port=0, upstream_host='127.0.0.1',
                upstream_port=upstream.server_port, owner_token='pdf-test-owner', read_token='pdf-test-reader',
                allowed_hosts=('127.0.0.1',), allowed_host_suffixes=('.ts.net',),
                max_body_bytes=1024, read_rate_per_minute=100, write_rate_per_minute=100,
                upstream_timeout_seconds=5, audit_path=Path(temp) / 'audit.jsonl',
                access_request_path=Path(temp) / 'access.json', client_trace_path=Path(temp) / 'client.jsonl',
            )
            private = gateway.PrivateWebServer(('127.0.0.1', 0), gateway.Handler, settings)
            servers = (upstream, private)
            threads = [threading.Thread(target=s.serve_forever, daemon=True) for s in servers]
            for thread in threads:
                thread.start()
            try:
                wasm = next((VENDOR / 'wasm').glob('*.wasm')).relative_to(VENDOR).as_posix()
                cases = [('pdf.min.mjs', 'text/javascript'), ('pdf.worker.min.mjs', 'text/javascript'),
                         ('cmaps/UniCNS-UCS2-H.bcmap', None), (wasm, 'application/wasm')]
                for port, token in ((upstream.server_port, None), (private.server_port, 'pdf-test-owner'),
                                    (private.server_port, 'pdf-test-reader')):
                    for rel, mime in cases:
                        with self.subTest(port=port, role=token, asset=rel):
                            headers = {'Authorization': 'Bearer ' + token} if token else {}
                            req = Request(f'http://127.0.0.1:{port}/assets/vendor/pdfjs/6.3.289/{rel}', headers=headers)
                            with urlopen(req, timeout=5) as response:
                                self.assertEqual(response.read(), (VENDOR / rel).read_bytes())
                                if mime:
                                    self.assertEqual(response.headers.get_content_type(), mime)
                                if rel.endswith('.mjs'):
                                    self.assertIn('no-store', response.headers['Cache-Control'])
            finally:
                for server in reversed(servers):
                    server.shutdown()
                    server.server_close()
                for thread in threads:
                    thread.join(timeout=2)


if __name__ == '__main__':
    unittest.main()
