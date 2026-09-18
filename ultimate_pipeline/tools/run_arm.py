#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Compatibility wrapper for runbooks referring to 'run_arm'.

Equivalent to:
  python -m ultimate_pipeline.tools.run_experiments arm ...
"""
from __future__ import annotations

from ultimate_pipeline.tools.run_experiments import main

if __name__ == "__main__":
    raise SystemExit(main())
