#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Regression tests for TWSE/TPEx key-stat symbol resolution."""
from __future__ import annotations

import unittest
from server.keystats_resolution import should_retry_tw_keystats_as_otc


class KeyStatsResolutionTest(unittest.TestCase):
    def test_otc_retry_when_tpex_pe_exists_but_quote_is_missing(self):
        partial = {
            "trailingPE": 34.52,
            "eps": None,
            "marketCap": None,
            "regularMarketPrice": None,
        }
        self.assertTrue(should_retry_tw_keystats_as_otc("5347.TW", partial))

    def test_complete_listed_quote_does_not_retry_for_one_missing_field(self):
        partial = {
            "trailingPE": 20.0,
            "eps": 5.0,
            "marketCap": None,
            "regularMarketPrice": 100.0,
        }
        self.assertFalse(should_retry_tw_keystats_as_otc("2330.TW", partial))

    def test_explicit_otc_symbol_never_retries(self):
        self.assertFalse(
            should_retry_tw_keystats_as_otc(
                "5347.TWO", {"regularMarketPrice": None, "marketCap": None}
            )
        )


if __name__ == "__main__":
    unittest.main()
