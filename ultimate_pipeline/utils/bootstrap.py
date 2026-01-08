#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Lightweight bootstrap utilities shared by entrypoints.

Goals:
- Harden stdout/stderr and logging against UnicodeEncodeError (Windows-safe).
- Provide a single, idempotent hook that entrypoints can call first thing.
"""
from __future__ import annotations

import logging

from ultimate_pipeline.utils.console_encoding import ensure_utf8_console

_BOOTSTRAPPED = False


def bootstrap_console() -> None:
    """
    Apply UTF-8/backslashreplace to stdout/stderr and ensure there is at least
    one StreamHandler pointing at the safe streams.
    Idempotent: safe to call from multiple modules.
    """
    global _BOOTSTRAPPED
    if _BOOTSTRAPPED:
        return

    ensure_utf8_console()

    root = logging.getLogger()
    if not root.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
        root.addHandler(handler)

    _BOOTSTRAPPED = True
