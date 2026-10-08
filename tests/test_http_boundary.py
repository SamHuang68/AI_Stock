#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import io
import unittest
from unittest import mock

from server.http_boundary import (
    BodyReadError,
    close_rejected_body,
    is_same_local_origin,
    normalized_origin,
    read_json_body,
)


class _Handler:
    def __init__(self, body: bytes = b'', length: str | None = None, content_type: str | None = None):
        self.rfile = io.BytesIO(body)
        self.headers = {}
        if length is not None:
            self.headers['Content-Length'] = length
        if content_type is not None:
            self.headers['Content-Type'] = content_type


class HttpBoundaryTests(unittest.TestCase):
    def test_rejected_body_drains_small_body_only_once(self):
        handler = _Handler(b'{}NEXT', '2')
        handler.connection = mock.Mock()
        close_rejected_body(handler)
        self.assertTrue(handler.close_connection)
        self.assertEqual(handler.rfile.read(), b'NEXT')
        handler = _Handler(b'{}NEXT', '2', 'application/json')
        handler.connection = mock.Mock()
        self.assertEqual(read_json_body(handler), {})
        close_rejected_body(handler)
        self.assertEqual(handler.rfile.read(), b'NEXT')

    def test_rejected_body_refuses_unknown_large_and_duplicate_lengths(self):
        from email.message import Message
        for length, transfer, duplicate in (('-1', None, False), ('abc', None, False),
                ('65537', None, False), ('2', 'chunked', False), ('2', None, True)):
            with self.subTest(length=length, transfer=transfer, duplicate=duplicate):
                handler = _Handler(b'{}', length)
                headers = Message(); headers['Content-Length'] = length
                if duplicate:
                    headers['Content-Length'] = length
                if transfer:
                    headers['Transfer-Encoding'] = transfer
                handler.headers = headers
                handler.connection = mock.Mock()
                close_rejected_body(handler)
                self.assertTrue(handler.close_connection)
                self.assertEqual(handler.rfile.tell(), 0)
                handler.connection.settimeout.assert_not_called()

    def test_rejected_body_drain_has_total_deadline_and_new_request_marker(self):
        handler = _Handler(b'{}', '2', 'application/json')
        read_json_body(handler)
        handler.headers = {'Content-Length': '10'}
        handler.rfile = mock.Mock()
        handler.rfile.read1.return_value = b'x'
        handler.connection = mock.Mock()
        handler.connection.gettimeout.return_value = 5
        with mock.patch('server.http_boundary.time.monotonic', side_effect=[0, .05, .11]):
            close_rejected_body(handler)
        handler.rfile.read1.assert_called_once_with(10)
        self.assertEqual(handler.connection.settimeout.call_args_list, [mock.call(.05), mock.call(5)])

    def test_json_object_is_bounded_and_decoded(self):
        raw = b'{"ok":true}'
        self.assertEqual(read_json_body(_Handler(raw, str(len(raw))), max_bytes=64), {'ok': True})

    def test_oversized_body_is_rejected_before_read(self):
        handler = _Handler(b'{}', '999')
        with self.assertRaises(BodyReadError) as caught:
            read_json_body(handler, max_bytes=8)
        self.assertEqual(caught.exception.status, 413)
        self.assertEqual(handler.rfile.tell(), 0)

    def test_invalid_length_json_and_shape_are_explicit(self):
        with self.assertRaises(BodyReadError):
            read_json_body(_Handler(b'', '-1'))
        with self.assertRaises(BodyReadError):
            read_json_body(_Handler(b'{', '1'))
        with self.assertRaises(BodyReadError) as caught:
            read_json_body(_Handler(b'[]', '2'))
        self.assertEqual(caught.exception.status, 422)

    def test_origin_comparison_is_exact_not_prefix_based(self):
        self.assertTrue(is_same_local_origin('http://127.0.0.1:18432', 18432))
        self.assertTrue(is_same_local_origin('http://localhost:18432/page', 18432))
        self.assertFalse(is_same_local_origin('http://localhost:18432.evil.invalid', 18432))
        self.assertFalse(is_same_local_origin('https://localhost:18432', 18432))
        self.assertEqual(normalized_origin('http://[::1]:18432/path'), 'http://[::1]:18432')

    def test_explicit_non_json_content_type_is_rejected(self):
        raw = b'{}'
        with self.assertRaises(BodyReadError) as caught:
            read_json_body(_Handler(raw, str(len(raw)), 'text/plain'))
        self.assertEqual(caught.exception.status, 415)


if __name__ == '__main__':
    unittest.main()
