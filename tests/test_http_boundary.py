#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import io
import unittest

from server.http_boundary import (
    BodyReadError,
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
