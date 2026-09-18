#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Write a deterministic fingerprint for the final XODR content.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from ultimate_pipeline.utils.file_hashing import safe_sha256_file


def write_map_content_fingerprint(out_dir: str, final_xodr_path: str) -> Optional[str]:
    if not out_dir or not final_xodr_path:
        return None
    out_path = os.path.join(out_dir, "map_content_fingerprint.json")
    data: Dict[str, Any] = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "final_xodr_path": final_xodr_path,
        "final_xodr_sha256": safe_sha256_file(final_xodr_path)
        if os.path.exists(final_xodr_path)
        else None,
    }

    quarantine_path = os.path.join(out_dir, "roads_quarantined.json")
    if os.path.exists(quarantine_path):
        data["roads_quarantined_path"] = quarantine_path
        data["roads_quarantined_sha256"] = safe_sha256_file(quarantine_path)

    try:
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, sort_keys=True, ensure_ascii=True)
    except Exception:
        return None
    return out_path
