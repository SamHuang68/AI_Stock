#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""HTTP handlers for feature-flag discovery."""
from __future__ import annotations

import json

from feature_settings import public_payload


class FeaturesRoutesMixin:
    def _handle_features(self):
        payload = public_payload(getattr(self, '_BASE', None))
        self._ok(json.dumps(payload, ensure_ascii=False).encode())
