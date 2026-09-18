#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Deterministic seam artifact writer.

Writes:
  <out_dir>/seams/<kind>/<edge_id>.json
and maintains:
  <out_dir>/seams/seams_manifest.json

Designed for academic reproducibility:
- includes hashes of tile inputs
- records params + settings snapshot
- records schema version + optional git commit
"""

from __future__ import annotations

import os
import re
import json
import time
import hashlib
import subprocess
from typing import Any, Dict, Optional, List, Tuple


SEAM_SCHEMA_VERSION = "seam_schema_v1"


def _mkdir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def file_hash(path: str, algo: str = "sha256", chunk_size: int = 1024 * 1024) -> str:
    h = hashlib.new(algo)
    with open(path, "rb") as f:
        while True:
            b = f.read(chunk_size)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def _slug(s: str) -> str:
    s = s.replace("\\", "/")
    s = re.sub(r"[^a-zA-Z0-9._\-\/]+", "_", s)
    return s.strip("_")


def try_git_commit(cwd: Optional[str] = None) -> Optional[str]:
    try:
        r = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            check=False,
        )
        out = (r.stdout or "").strip()
        if out and re.fullmatch(r"[0-9a-fA-F]{7,40}", out):
            return out
        return None
    except Exception:
        return None


def edge_id(tile_a: str, tile_b: str, directed: bool = True) -> str:
    a = os.path.basename(tile_a)
    b = os.path.basename(tile_b)
    if directed:
        return _slug(f"{a}__to__{b}")
    a, b = sorted([a, b])
    return _slug(f"{a}__{b}")


class SeamArtifactWriter:
    def __init__(
        self,
        out_dir: str,
        *,
        manifest_name: str = "seams_manifest.json",
        algo: str = "sha256",
        directed_edges: bool = True,
        project_root_for_git: Optional[str] = None,
    ) -> None:
        self.out_dir = out_dir
        self.algo = algo
        self.directed_edges = directed_edges
        self.project_root_for_git = project_root_for_git
        self.manifest_name = manifest_name

        self.seams_dir = os.path.join(self.out_dir, "seams")
        _mkdir(self.seams_dir)

    def _manifest_path(self) -> str:
        return os.path.join(self.seams_dir, self.manifest_name)

    def _load_manifest(self) -> Dict[str, Any]:
        p = self._manifest_path()
        if not os.path.exists(p):
            return {
                "schema": SEAM_SCHEMA_VERSION,
                "created_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "git_commit": try_git_commit(self.project_root_for_git),
                "algo": self.algo,
                "directed_edges": self.directed_edges,
                "items": [],
            }
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)

    def _save_manifest(self, m: Dict[str, Any]) -> None:
        items = m.get("items", [])
        if isinstance(items, list):
            items.sort(key=lambda it: (it.get("kind", ""), it.get("edge_id", "")))
            m["items"] = items
        m["updated_utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        tmp = self._manifest_path() + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(m, f, indent=2, sort_keys=True)
        os.replace(tmp, self._manifest_path())

    def write_seam(
        self,
        *,
        tile_a_path: str,
        tile_b_path: str,
        kind: str,
        stats: Dict[str, Any],
        params: Dict[str, Any],
        settings_snapshot: Optional[Dict[str, Any]] = None,
        extra: Optional[Dict[str, Any]] = None,
    ) -> str:
        kind_slug = _slug(kind)
        kind_dir = os.path.join(self.seams_dir, kind_slug)
        _mkdir(kind_dir)

        eid = edge_id(tile_a_path, tile_b_path, directed=self.directed_edges)
        report_path = os.path.join(kind_dir, f"{eid}.json")

        a_hash = file_hash(tile_a_path, algo=self.algo) if os.path.exists(tile_a_path) else None
        b_hash = file_hash(tile_b_path, algo=self.algo) if os.path.exists(tile_b_path) else None

        payload: Dict[str, Any] = {
            "schema": SEAM_SCHEMA_VERSION,
            "kind": kind_slug,
            "edge_id": eid,
            "tile_a": os.path.abspath(tile_a_path),
            "tile_b": os.path.abspath(tile_b_path),
            "tile_a_hash": a_hash,
            "tile_b_hash": b_hash,
            "params": params,
            "stats": stats,
            "settings_snapshot": settings_snapshot or {},
            "extra": extra or {},
            "created_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }

        tmp = report_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, sort_keys=True)
        os.replace(tmp, report_path)

        m = self._load_manifest()
        items: List[Dict[str, Any]] = m.get("items", [])
        if not isinstance(items, list):
            items = []

        item = {
            "kind": kind_slug,
            "edge_id": eid,
            "report": os.path.relpath(report_path, self.seams_dir).replace("\\", "/"),
            "tile_a": os.path.basename(tile_a_path),
            "tile_b": os.path.basename(tile_b_path),
            "tile_a_hash": a_hash,
            "tile_b_hash": b_hash,
        }

        # replace-or-add
        items = [it for it in items if not (it.get("kind") == kind_slug and it.get("edge_id") == eid)]
        items.append(item)
        m["items"] = items
        self._save_manifest(m)

        return report_path
