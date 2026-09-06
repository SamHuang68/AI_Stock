#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Bounded executors dedicated to /pulse orchestration."""
from __future__ import annotations

from deadline import BoundedExecutor

pulse_extras_pool = BoundedExecutor(2, 2, prefix='pulse-ex')
pulse_side_pool = BoundedExecutor(4, 8, prefix='pulse-side')
pulse_quote_pool = BoundedExecutor(6, 18, prefix='pulse-global')
