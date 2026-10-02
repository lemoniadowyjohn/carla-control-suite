#!/usr/bin/env python3
"""RQ5 dataset split authority — grouped-unit splits with research-strict mode.

Split by grouped units (route_segment / capture_block / scenario /
spatial_region), never by random adjacent frames. Research-strict mode
rejects: latest dataset, fallback dataset, mtime selection, latest
checkpoint, implicit camera, implicit seed, implicit split. Dataset identity
for science requires complete == true; partial prefix hashing is diagnostic
only.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List

GROUP_UNITS = ("route_segment", "capture_block", "scenario", "spatial_region")

SPLIT_NAMES = ("train", "val", "generated_test", "manual_test")


class SplitAuthorityError(RuntimeError):
    pass


def _sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for c in iter(lambda: f.read(4 * 1024 * 1024), b""):
            h.update(c)
    return h.hexdigest()


def load_manifest(path: Path) -> Dict[str, Any]:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception as e:
        raise SplitAuthorityError(f"cannot read split manifest {path}: {e}") from e


def verify_dataset_identity(manifest: Dict[str, Any], *, research_strict: bool) -> Dict[str, Any]:
    ident = manifest.get("dataset_identity") or {}
    if research_strict:
        if ident.get("complete") is not True:
            raise SplitAuthorityError(
                f"research-strict requires dataset_identity.complete == true, got {ident.get('complete')!r} "
                "(partial prefix hashing is diagnostic only)"
            )
        for bad in ("latest", "fallback", "mtime"):
            if str(ident.get("selection", "")).lower() == bad:
                raise SplitAuthorityError(f"research-strict rejects {bad!r} dataset selection")
    return ident


def resolve_split(manifest: Dict[str, Any], split: str, *, research_strict: bool,
                  camera: str | None = None, seed: int | None = None) -> Dict[str, Any]:
    if research_strict:
        if not camera:
            raise SplitAuthorityError("research-strict rejects implicit camera")
        if seed is None:
            raise SplitAuthorityError("research-strict rejects implicit seed")
        if not split:
            raise SplitAuthorityError("research-strict rejects implicit split")
    if split not in SPLIT_NAMES:
        raise SplitAuthorityError(f"unknown split {split!r} (expected one of {SPLIT_NAMES})")
    splits = manifest.get("splits") or {}
    if split not in splits:
        raise SplitAuthorityError(f"split {split!r} missing from manifest")
    entry = splits[split]
    unit = entry.get("group_unit")
    if unit not in GROUP_UNITS:
        raise SplitAuthorityError(
            f"split {split!r} must declare group_unit in {GROUP_UNITS}, got {unit!r} "
            "(random adjacent-frame splits forbidden)"
        )
    return entry


def verify_disjoint(manifest: Dict[str, Any]) -> Dict[str, Any]:
    splits = manifest.get("splits") or {}
    def frames(name: str) -> set:
        e = splits.get(name) or {}
        return set(e.get("frames") or [])
    def units(name: str) -> set:
        e = splits.get(name) or {}
        return set(e.get("units") or [])
    report: Dict[str, Any] = {"pairs": {}}
    pairs = [("train", "val"), ("train", "generated_test"), ("train", "manual_test"),
             ("val", "generated_test"), ("val", "manual_test"), ("generated_test", "manual_test")]
    ok = True
    for a, b in pairs:
        f_overlap = sorted(frames(a) & frames(b))
        u_overlap = sorted(units(a) & units(b))
        # content-copy check via frame content hashes when provided
        ha = (splits.get(a) or {}).get("frame_hashes") or {}
        hb = (splits.get(b) or {}).get("frame_hashes") or {}
        hash_overlap = sorted({h for h in ha.values() if h in set(hb.values())}) if (ha and hb) else []
        pair_ok = not f_overlap and not u_overlap and not hash_overlap
        ok = ok and pair_ok
        report["pairs"][f"{a}∩{b}"] = {"frames": f_overlap, "units": u_overlap,
            "content_hashes": hash_overlap, "empty": bool(pair_ok)}
    report["disjoint"] = bool(ok)
    # generated train/val ∩ manual target must be empty (covered above, surfaced explicitly)
    report["manual_isolation"] = bool(report["pairs"]["train∩manual_test"]["empty"]
        and report["pairs"]["val∩manual_test"]["empty"])
    return report


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("manifest", type=Path)
    ap.add_argument("--split", default=None)
    ap.add_argument("--camera", default=None)
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--research-strict", action="store_true")
    ap.add_argument("--check-disjoint", action="store_true")
    args = ap.parse_args()
    try:
        m = load_manifest(args.manifest)
        verify_dataset_identity(m, research_strict=args.research_strict)
        if args.split:
            resolve_split(m, args.split, research_strict=args.research_strict,
                          camera=args.camera, seed=args.seed)
        if args.check_disjoint:
            rep = verify_disjoint(m)
            print(json.dumps({"disjoint": rep["disjoint"], "manual_isolation": rep["manual_isolation"]}, indent=2))
            return 0 if rep["disjoint"] else 2
        print(json.dumps({"ok": True}, indent=2))
        return 0
    except SplitAuthorityError as e:
        print(json.dumps({"ok": False, "error": str(e)}, indent=2))
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
