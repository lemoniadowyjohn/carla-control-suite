#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Best-effort artifact integrity check (offline).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


from ultimate_pipeline.utils.file_hashing import sha256_file


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _git_commit(repo_root: Path) -> Tuple[Optional[str], Optional[str]]:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            timeout=2,
        )
        if result.returncode == 0:
            return result.stdout.strip(), None
        return None, (result.stderr.strip() or f"git rev-parse failed with code {result.returncode}")
    except FileNotFoundError:
        return None, "git not found"
    except subprocess.TimeoutExpired:
        return None, "git command timed out"
    except Exception as exc:  # noqa: BLE001
        return None, f"git error: {exc}"


def _write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True)
    path.write_text(text + ("\n" if not text.endswith("\n") else ""), encoding="utf-8", newline="\n")


def _open_image_ok(path: Path) -> Tuple[bool, str]:
    try:
        from PIL import Image  # type: ignore

        with Image.open(path) as img:
            img.verify()
        return True, "ok"
    except Exception:
        pass

    try:
        import imghdr

        kind = imghdr.what(path)
        if kind:
            return True, "ok"
        return False, "unknown_format"
    except Exception as exc:  # noqa: BLE001
        return False, f"image_error: {exc}"


def _build_manifest(sample_paths: List[Path]) -> Dict[str, Any]:
    repo_root = Path(__file__).resolve().parents[2]
    git_commit, git_err = _git_commit(repo_root)
    inputs = []
    for path in sample_paths:
        if path.exists():
            inputs.append({"path": str(path), "sha256": sha256_file(path)})
    return {
        "generated_at_utc": _utc_now(),
        "python_version": sys.version.replace("\n", " "),
        "git_commit": git_commit,
        "git_commit_error": git_err,
        "inputs": inputs,
    }


def _sample_paths(paths: List[Path], sample: int) -> List[Path]:
    if sample <= 0:
        return []
    paths = sorted(paths)
    return paths[: min(sample, len(paths))]


def run_integrity_check(run_dir: Path, sample: int) -> Dict[str, Any]:
    if not run_dir.exists():
        return {"ok": False, "error": f"run_dir missing: {run_dir}"}

    all_files = [p for p in run_dir.rglob("*") if p.is_file()]
    json_files = [p for p in all_files if p.suffix.lower() == ".json"]
    image_files = [p for p in all_files if p.suffix.lower() in (".jpg", ".jpeg", ".png")]

    json_sample = _sample_paths(json_files, sample)
    image_sample = _sample_paths(image_files, sample)
    non_empty_sample = _sample_paths(all_files, sample)

    json_failures = []
    for path in json_sample:
        try:
            json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            json_failures.append({"path": str(path), "error": str(exc)})

    image_failures = []
    for path in image_sample:
        ok, err = _open_image_ok(path)
        if not ok:
            image_failures.append({"path": str(path), "error": err})

    empty_failures = []
    for path in non_empty_sample:
        try:
            if path.stat().st_size == 0:
                empty_failures.append({"path": str(path), "error": "empty_file"})
        except Exception as exc:  # noqa: BLE001
            empty_failures.append({"path": str(path), "error": str(exc)})

    ok = not json_failures and not image_failures and not empty_failures
    return {
        "ok": ok,
        "error": None if ok else "integrity_failures",
        "run_dir": str(run_dir),
        "sample_size": sample,
        "counts": {
            "total_files": len(all_files),
            "json_files": len(json_files),
            "image_files": len(image_files),
        },
        "samples": {
            "json": [str(p) for p in json_sample],
            "images": [str(p) for p in image_sample],
            "non_empty": [str(p) for p in non_empty_sample],
        },
        "json_parse_failures": json_failures,
        "image_open_failures": image_failures,
        "empty_file_failures": empty_failures,
    }


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Check integrity of artifacts in a run directory.")
    p.add_argument("--run-dir", type=Path, required=True, help="Run directory to scan")
    p.add_argument("--sample", type=int, default=50, help="Sample size per check")
    return p


def main(argv: Optional[list[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    run_dir = args.run_dir
    report_path = run_dir / "artifacts" / "artifact_integrity_report.json"
    manifest_path = run_dir / "artifacts" / "artifact_integrity_manifest.json"

    payload = run_integrity_check(run_dir, max(0, args.sample))
    _write_json(report_path, payload)

    sample_paths: List[Path] = []
    for key in ("json", "images", "non_empty"):
        for p in payload.get("samples", {}).get(key, []):
            sample_paths.append(Path(p))
    _write_json(manifest_path, _build_manifest(sample_paths))
    return 0 if payload.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
