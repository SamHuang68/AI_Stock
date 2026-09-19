"""PDF 匯出依賴的官方位元組、發行必要檔案及 HTTP 讀取契約。"""
from functools import partial
import hashlib
import importlib.util
import json
from pathlib import Path, PurePosixPath
import re
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
from http.server import ThreadingHTTPServer
from urllib.parse import quote
from urllib.request import Request, urlopen
import zipfile


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
sys.path.insert(0, str(ROOT / 'server'))
import build_dist as dist

try:
    import private_web_gateway as gateway
    import private_web_release as release
except ModuleNotFoundError as error:
    if error.name not in ('private_web_gateway', 'private_web_release'):
        raise
    gateway = release = None  # 分享包仍執行資產、HTTP 與隱私檢查。

SPEC = importlib.util.spec_from_file_location('st_pdf_export_asset_server', ROOT / 'server/server.py')
ST = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ST)

# 雜湊另行固定於測試，不讓修改資產及來源清單同時通過原檔驗證。
PACKAGES = {
    'html2canvas': {
        'version': '1.4.1',
        'integrity': 'sha512-fPU6BHNpsyIhr8yyMpTLLxAbkaK8ArIBcmZIRiBLiDhjeqvXolaEmDGmELFuX9I4xDcaKKcJl+TKZLqruBbmWA==',
        'files': {
            'html2canvas.min.js': 'e87e550794322e574a1fda0c1549a3c70dae5a93d9113417a429016838eab8cb',
            'LICENSE': '86200ce4e92d9a22c41c8647a55f7a5fddff304ff89b4d36ecc699ed8c123d2c',
        },
    },
    'jspdf': {
        'version': '4.2.1',
        'integrity': 'sha512-YyAXyvnmjTbR4bHQRLzex3CuINCDlQnBqoSYyjJwTP2x9jDLuKDzy7aKUl0hgx3uhcl7xzg32agn5vlie6HIlQ==',
        'files': {
            'jspdf.umd.min.js': 'e6551fcdc32f09d6853b2c5126d18d01d9447e0da618a41a11ebeee0f6c20d54',
            'LICENSE': 'dc388ec35ff463288cdde3588a36fd4ed12a45deff053243b37309acc9ef583b',
        },
    },
}
ASSETS = tuple(f'assets/vendor/{name}/{spec["version"]}/{filename}'
               for name, spec in PACKAGES.items()
               for filename in (*spec['files'], '來源資訊.json'))
REQUIRED = {*ASSETS, 'tests/test_PDF匯出資產.py'}
JSPDF = 'assets/vendor/jspdf/4.2.1/jspdf.umd.min.js'


class PdfExportAssetsTests(unittest.TestCase):
    def test_official_inventory_and_raw_bytes_are_pinned(self):
        for name, expected in PACKAGES.items():
            vendor = ROOT / f'assets/vendor/{name}/{expected["version"]}'
            manifest = json.loads((vendor / '來源資訊.json').read_text(encoding='utf-8'))
            with self.subTest(package=name):
                self.assertEqual(manifest['package'], name)
                self.assertEqual(manifest['version'], expected['version'])
                self.assertEqual(manifest['integrity'], expected['integrity'])
                self.assertEqual(manifest['tarballUrl'],
                                 f'https://registry.npmjs.org/{name}/-/{name}-{expected["version"]}.tgz')
                self.assertEqual(manifest['files'], expected['files'])
                self.assertEqual({p.relative_to(vendor).as_posix() for p in vendor.rglob('*') if p.is_file()},
                                 {*expected['files'], '來源資訊.json'})
            for relative, digest in manifest['files'].items():
                with self.subTest(package=name, asset=relative):
                    path = PurePosixPath(relative)
                    self.assertFalse(path.is_absolute())
                    self.assertNotIn('..', path.parts)
                    self.assertNotIn('\\', relative)
                    self.assertNotIn(':', relative)
                    self.assertEqual(path.as_posix(), relative)
                    target = vendor / relative
                    self.assertFalse(target.is_symlink())
                    self.assertTrue(target.resolve().is_relative_to(vendor.resolve()))
                    self.assertEqual(hashlib.sha256(target.read_bytes()).hexdigest(), digest)

    @unittest.skipIf(release is None, '分享包不包含私人網站發布模組')
    def test_private_release_rejects_each_missing_export_asset(self):
        self.assertTrue(REQUIRED <= release.REQUIRED_RELEASE_FILES)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for relative in release.REQUIRED_RELEASE_FILES:
                target = root / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(b'x')
            release._validate_release(root)
            for relative in REQUIRED:
                with self.subTest(asset=relative):
                    target = root / relative
                    target.unlink()
                    try:
                        with self.assertRaises(RuntimeError):
                            release._validate_release(root)
                    finally:
                        target.write_bytes(b'x')

    def test_share_preflight_rejects_missing_and_untracked_export_assets(self):
        self.assertTrue(REQUIRED <= set(dist.REQUIRED_SHARE_FILES))
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for relative in dist.REQUIRED_SHARE_FILES:
                target = root / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(b'x')
            with patch.object(dist, 'ROOT', root), patch.object(dist, 'TRACKED_FILES', set(dist.REQUIRED_SHARE_FILES)):
                dist.validate_required_share_files()
                for relative in REQUIRED:
                    with self.subTest(asset=relative):
                        target = root / relative
                        target.unlink()
                        try:
                            with self.assertRaises(RuntimeError):
                                dist.validate_required_share_files()
                        finally:
                            target.write_bytes(b'x')
                        with patch.object(dist, 'TRACKED_FILES', set(dist.REQUIRED_SHARE_FILES) - {relative}):
                            with self.assertRaises(RuntimeError):
                                dist.validate_required_share_files()

    def test_filtered_share_archive_preserves_all_export_asset_bytes(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            stage = root / dist.STAGE_NAME
            with patch.object(dist, 'TRACKED_FILES', set(ASSETS)):
                for name, spec in PACKAGES.items():
                    relative = f'assets/vendor/{name}/{spec["version"]}'
                    self.assertEqual(dist.copy_tree_filtered(ROOT / relative, stage / relative), 3)
            self.assertEqual(dist.scan_stage_content(stage), [])
            archive_path = root / '匯出資產.zip'
            dist.make_zip(stage, archive_path)
            self.assertEqual(dist.verify_archive(archive_path), [])
            with zipfile.ZipFile(archive_path) as archive:
                self.assertEqual(set(archive.namelist()), {dist.STAGE_NAME + '/' + relative for relative in ASSETS})
                for relative in ASSETS:
                    self.assertEqual(archive.read(dist.STAGE_NAME + '/' + relative), (ROOT / relative).read_bytes())

    def _assert_http_assets(self, port, token=None):
        for relative in ASSETS:
            with self.subTest(role=token or '本機', asset=relative):
                headers = {'Authorization': 'Bearer ' + token} if token else {}
                request = Request(f'http://127.0.0.1:{port}/' + quote(relative), headers=headers)
                with urlopen(request, timeout=5) as response:
                    self.assertEqual(response.status, 200)
                    self.assertEqual(response.read(), (ROOT / relative).read_bytes())
                    if relative.endswith('.js'):
                        self.assertIn(response.headers.get_content_type(), ('text/javascript', 'application/javascript'))
                        self.assertIn('no-store', response.headers['Cache-Control'])
                    elif relative.endswith('.json'):
                        self.assertEqual(response.headers.get_content_type(), 'application/json')

    def _serve(self, with_gateway=False):
        with tempfile.TemporaryDirectory() as temp:
            upstream = ThreadingHTTPServer(('127.0.0.1', 0), partial(ST.Handler, directory=str(ROOT)))
            servers = [upstream]
            if with_gateway:
                settings = gateway.Settings(
                    listen_host='127.0.0.1', listen_port=0, upstream_host='127.0.0.1',
                    upstream_port=upstream.server_port, owner_token='pdf-export-test-owner',
                    read_token='pdf-export-test-reader', allowed_hosts=('127.0.0.1',),
                    allowed_host_suffixes=('.ts.net',), max_body_bytes=1024,
                    read_rate_per_minute=100, write_rate_per_minute=100,
                    upstream_timeout_seconds=5, audit_path=Path(temp) / '讀取稽核.jsonl',
                    access_request_path=Path(temp) / '存取請求.json', client_trace_path=Path(temp) / '用戶端.jsonl',
                )
                servers.append(gateway.PrivateWebServer(('127.0.0.1', 0), gateway.Handler, settings))
            threads = [threading.Thread(target=server.serve_forever, daemon=True) for server in servers]
            for thread in threads:
                thread.start()
            try:
                with patch.object(ST, '_BASE', temp):
                    if with_gateway:
                        for token in ('pdf-export-test-owner', 'pdf-export-test-reader'):
                            self._assert_http_assets(servers[-1].server_port, token)
                    else:
                        self._assert_http_assets(upstream.server_port)
            finally:
                for server in reversed(servers):
                    server.shutdown()
                    server.server_close()
                for thread in threads:
                    thread.join(timeout=2)

    def test_local_http_javascript_mime_and_exact_bytes(self):
        self._serve()

    @unittest.skipIf(gateway is None, '分享包不包含私人網站模組')
    def test_private_owner_and_reader_http_mime_and_exact_bytes(self):
        self._serve(with_gateway=True)


class PdfExportPrivacyTests(unittest.TestCase):
    def _scan(self, relative, content, extra=None):
        with tempfile.TemporaryDirectory() as temp:
            stage = Path(temp) / dist.STAGE_NAME
            for name, data in {relative: content, **(extra or {})}.items():
                target = stage / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
            staged = dist.scan_stage_content(stage)
            archive = Path(temp) / '隱私邊界.zip'
            dist.make_zip(stage, archive)
            return staged, dist.verify_archive(archive)

    def test_official_attribution_exception_requires_exact_original_path(self):
        original = (ROOT / JSPDF).read_bytes()
        # 原檔命中來自公開作者／外掛授權署名，固定雜湊例外只處理郵件規則。
        for issues in self._scan(JSPDF, original):
            self.assertEqual(issues, [])
        for issues in self._scan('assets/改名匯出依賴.js', original):
            self.assertIn('email-address', {issue['rule'] for issue in issues})

    def test_changed_original_and_forged_manifest_cannot_reauthorize_exception(self):
        changed = (ROOT / JSPDF).read_bytes() + ('\n// ' + 'sk-' + 'x' * 24).encode('ascii')
        forged = json.dumps({'files': {'jspdf.umd.min.js': hashlib.sha256(changed).hexdigest()}}).encode('utf-8')
        manifest = 'assets/vendor/jspdf/4.2.1/來源資訊.json'
        for issues in self._scan(JSPDF, changed, {manifest: forged}):
            self.assertTrue({'vendor-integrity', 'email-address', 'openai-anthropic-key'}
                            <= {issue['rule'] for issue in issues})

    def test_invalid_utf8_cannot_bypass_vendor_integrity_before_or_after_zip(self):
        for relative in dist.VERIFIED_VENDOR_EMAIL_EXCEPTIONS:
            with self.subTest(asset=relative):
                original = (ROOT / relative).read_bytes()
                changed = original + b'\n// ' + bytes([255]) + b' ' + b'sk-' + b'x' * 24 + b'\n'
                with self.assertRaises(UnicodeDecodeError):
                    changed.decode('utf-8')
                for issues in self._scan(relative, changed):
                    self.assertEqual({issue['rule'] for issue in issues}, {'vendor-integrity'})

    def test_other_legacy_non_utf8_files_keep_existing_scan_policy(self):
        for issues in self._scan('assets/舊編碼.txt', bytes([255, 254])):
            self.assertEqual(issues, [])

    def test_newline_change_also_invalidates_original_exception(self):
        original = (ROOT / JSPDF).read_bytes()
        self.assertIn(b'\n', original)
        changed = original.replace(b'\n', b'\r\n', 1)
        for issues in self._scan(JSPDF, changed):
            self.assertIn('email-address', {issue['rule'] for issue in issues})

    def test_verified_original_still_runs_other_sensitive_rules(self):
        original = (ROOT / JSPDF).read_bytes()
        rules = dist.SENSITIVE_CONTENT_RULES + (('測試其他秘密規則', re.compile('jsPDF')),)
        with patch.object(dist, 'SENSITIVE_CONTENT_RULES', rules):
            for issues in self._scan(JSPDF, original):
                self.assertEqual({issue['rule'] for issue in issues}, {'測試其他秘密規則'})


if __name__ == '__main__':
    unittest.main()
