#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'server'))

import notify_contacts as nc  # noqa: E402


class NotifyContactsTests(unittest.TestCase):
    def test_sanitize_keeps_valid_rows_and_mints_ids(self):
        cleaned, errors = nc.sanitize([
            {'name': 'Sam', 'email': 'sam@example.com'},
            {'name': 'Dup', 'email': 'SAM@example.com'},
            {'name': '', 'email': 'bad'},
            {'name': 'Pat', 'email': 'pat@example.com', 'id': 'c_abc123xyz'},
        ])
        self.assertTrue(any('信箱無效' in item for item in errors))
        self.assertEqual(len(cleaned), 2)
        self.assertEqual(cleaned[0]['email'], 'sam@example.com')
        self.assertTrue(cleaned[0]['id'].startswith('c_'))
        self.assertEqual(cleaned[1]['id'], 'c_abc123xyz')
        self.assertEqual(cleaned[1]['name'], 'Pat')

    def test_roundtrip_file(self):
        with tempfile.TemporaryDirectory() as temp:
            path = str(Path(temp) / 'notify_contacts.json')
            saved = nc.save_contacts(
                [{'name': 'Sam', 'email': 'sam@example.com'}],
                path=path,
            )
            loaded = nc.load_contacts(path)
            self.assertEqual(len(saved), 1)
            self.assertEqual(loaded[0]['email'], 'sam@example.com')
            self.assertEqual(loaded[0]['name'], 'Sam')

    def test_report_payload_accepts_text_and_recipient_list(self):
        payload, errors = nc.normalize_report_payload({
            'to': ['a@example.com', 'b@example.com', 'a@example.com'],
            'subject': 'AI 分析',
            'text': '全文朗讀測試 <b>x</b>',
        })
        self.assertEqual(errors, [])
        self.assertEqual(payload['to'], ['a@example.com', 'b@example.com'])
        self.assertIn('&lt;b&gt;x&lt;/b&gt;', payload['html'])
        self.assertEqual(payload['subject'], 'AI 分析')

    def test_report_payload_rejects_empty(self):
        payload, errors = nc.normalize_report_payload({'to': 'not-an-email', 'html': ''})
        self.assertTrue(errors)
        self.assertFalse(payload.get('to'))


class NotifyContactsHttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import importlib.util
        from http.server import ThreadingHTTPServer
        import threading
        spec = importlib.util.spec_from_file_location(
            'st_notify_contacts_http', ROOT / 'server' / 'server.py')
        if spec is None or spec.loader is None:
            raise RuntimeError('unable to load Stock Terminal server')
        cls.ST = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.ST)
        cls.httpd = ThreadingHTTPServer(('127.0.0.1', 0), cls.ST.Handler)
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()
        cls.port = cls.httpd.server_port
        cls.base = f'http://127.0.0.1:{cls.port}'
        cls.old_port = cls.ST.PORT
        cls.ST.PORT = cls.port

    @classmethod
    def tearDownClass(cls):
        cls.ST.PORT = cls.old_port
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.thread.join(timeout=2)

    def test_contacts_roundtrip_and_report_email_validation(self):
        import json
        import tempfile
        import urllib.request
        import urllib.error
        with tempfile.TemporaryDirectory() as temp:
            path = str(Path(temp) / 'notify_contacts.json')
            old = nc.CONTACTS_FILE
            nc.CONTACTS_FILE = path
            try:
                with urllib.request.urlopen(self.base + '/notify/contacts', timeout=3) as response:
                    empty = json.load(response)
                self.assertTrue(empty.get('ok'))
                self.assertEqual(empty.get('contacts'), [])
                req = urllib.request.Request(
                    self.base + '/notify/contacts',
                    data=json.dumps({
                        'contacts': [{'name': 'Sam', 'email': 'sam@example.com'}],
                    }).encode('utf-8'),
                    method='POST',
                    headers={'Content-Type': 'application/json'},
                )
                with urllib.request.urlopen(req, timeout=3) as response:
                    saved = json.load(response)
                self.assertTrue(saved.get('ok'))
                self.assertEqual(saved['contacts'][0]['email'], 'sam@example.com')
                with urllib.request.urlopen(self.base + '/notify/contacts', timeout=3) as response:
                    loaded = json.load(response)
                self.assertEqual(loaded['contacts'][0]['name'], 'Sam')
                bad = urllib.request.Request(
                    self.base + '/report-email',
                    data=json.dumps({'to': 'not-an-email', 'text': 'hello'}).encode('utf-8'),
                    method='POST',
                    headers={'Content-Type': 'application/json'},
                )
                with self.assertRaises(urllib.error.HTTPError) as caught:
                    urllib.request.urlopen(bad, timeout=3)
                self.assertEqual(caught.exception.code, 400)
                err = json.loads(caught.exception.read())
                caught.exception.close()
                self.assertIn('信箱', err.get('error', ''))
            finally:
                nc.CONTACTS_FILE = old


if __name__ == '__main__':
    unittest.main()
