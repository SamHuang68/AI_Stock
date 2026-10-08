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
    def test_real_message_without_framing_never_reads_or_changes_timeout(self):
        import http.client
        from types import SimpleNamespace

        # 真 Message 缺少 CL 時 get_all 回 None，不能用 dict 替身遮蔽。
        for raw_headers in (b'Host: localhost\r\n\r\n',
                            b'Content-Length: 0\r\n\r\n'):
            with self.subTest(raw_headers=raw_headers):
                headers = http.client.parse_headers(io.BytesIO(raw_headers))
                handler = SimpleNamespace(headers=headers, rfile=mock.Mock(),
                                          connection=mock.Mock())
                close_rejected_body(handler)
                self.assertTrue(handler.close_connection)
                handler.rfile.read1.assert_not_called()
                handler.connection.gettimeout.assert_not_called()
                handler.connection.settimeout.assert_not_called()


    def test_malformed_rejection_discards_raw_bytes_with_a_size_limit(self):
        handler = _Handler(b'{}NEXTBODY', '-1')
        handler.connection = mock.Mock()
        handler.connection.gettimeout.return_value = 5
        close_rejected_body(handler, max_bytes=8)
        self.assertTrue(handler.close_connection)
        self.assertEqual(handler.rfile.tell(), 8)
        self.assertEqual(handler.rfile.read(), b'DY')
        handler.connection.settimeout.assert_called()
        self.assertEqual(handler.connection.settimeout.call_args, mock.call(5))

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

    def test_rejected_body_discards_unknown_framing_without_reusing_connection(self):
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
                self.assertEqual(handler.rfile.tell(), 2)
                handler.connection.settimeout.assert_called()

    def test_unknown_rejection_drain_keeps_one_deadline_and_restores_timeout(self):
        handler = _Handler(length='invalid')
        handler.rfile = mock.Mock()
        handler.rfile.read1.return_value = b'x'
        handler.connection = mock.Mock()
        handler.connection.gettimeout.return_value = 5
        with mock.patch('server.http_boundary.time.monotonic', side_effect=[0, .05, .11]):
            close_rejected_body(handler, max_bytes=8)
        handler.rfile.read1.assert_called_once_with(8)
        self.assertTrue(handler.close_connection)
        self.assertEqual(handler.connection.settimeout.call_args_list, [mock.call(.05), mock.call(5)])

    def test_unknown_rejection_drain_restores_timeout_after_interruption(self):
        handler = _Handler(length='-1')
        handler.rfile = mock.Mock()
        handler.rfile.read1.side_effect = TimeoutError('受控慢送')
        handler.connection = mock.Mock()
        handler.connection.gettimeout.return_value = 5
        close_rejected_body(handler, max_bytes=8)
        self.assertTrue(handler.close_connection)
        handler.rfile.read1.assert_called_once_with(8)
        self.assertEqual(handler.connection.settimeout.call_args, mock.call(5))

    def test_unknown_rejection_never_reads_more_than_the_total_byte_cap(self):
        handler = _Handler(b'x' * (64 * 1024 + 1), '-1')
        handler.connection = mock.Mock()
        original = handler.rfile.read1
        with mock.patch.object(handler.rfile, 'read1', side_effect=original) as read:
            close_rejected_body(handler)
        self.assertEqual(handler.rfile.tell(), 64 * 1024)
        self.assertEqual(handler.rfile.read(), b'x')
        self.assertEqual(read.call_count, 8)
        self.assertTrue(all(call.args[0] <= 8192 for call in read.call_args_list))
        self.assertTrue(handler.close_connection)

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
