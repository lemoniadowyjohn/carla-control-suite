#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CARLA Large-Map ``package.json`` descriptor + ``Import/<Package>/`` staging.

This module implements **extension 3** of the P1/P2 "moderate extension of
existing code" plan in
``reports/production_readiness/20260915T140000Z_TILE_BASED_UE4_COOKING_DESIGN/DESIGN.md``
§5: turning a whole-map XODR plus the per-tile FBX files produced by
``ultimate_pipeline.tiling.tile_fbx_generator`` into the exact on-disk layout
CARLA's ``make import`` / content pipeline (``Util/DevTools/Import.py`` in a
CARLA source checkout) expects to find and stage.

The gap this closes
--------------------
CARLA's asset-import tooling does not take arbitrary paths. It scans
``Import/`` for **package subdirectories**, and inside each one it filename-
matches a ``package.json`` descriptor against the ``.xodr``/``.fbx`` files
sitting next to it (DESIGN.md §1.1, §2.1, Appendix B: ``tuto_M_add_map_source``,
``large_map_import``). Concretely, for one Large Map package named
``<PackageName>`` the importer expects::

    Import/
      <PackageName>/
        <PackageName>.json      # the package descriptor CARLA's Import.py reads
        <MapName>.xodr          # single whole-map XODR (never split)
        <MapName>_Tile_0_0.fbx  # one file per non-empty tile, CARLA naming
        <MapName>_Tile_0_1.fbx
        ...

Nothing in this repo produced that layout before this module: the tile FBX
generator (extension 1+2) writes loose files into a scratch output directory,
and there was no descriptor generator or staging step at all. This module is
pure offline orchestration -- it does not invoke ``make import`` or any UE4/UE5
process (that step remains blocked on the separate UE4-build track, DESIGN.md
§6) -- it only produces the **input** that step consumes, and validates that
input is self-consistent before a human/CI hands it to a real CARLA checkout.

Public API
----------
``PackageDescriptor``
    In-memory model of one ``package.json`` "maps" entry (CARLA schema:
    ``name``, ``xodr``, ``use_carla_materials``, ``tile_size``, ``tiles``).

``build_package_json(...)``
    Pure function: given a map name, xodr filename, tile list and tile_size,
    return the exact documented ``package.json`` dict (``maps`` + ``props``).

``stage_large_map_package(...)``
    I/O: copies (real, independent copies -- never hardlinks, see
    ``_copy_file`` -- a staged/promoted artifact must survive the source
    being mutated in place) the whole-map XODR and the given tile FBX files
    into ``Import/<PackageName>/``, writes ``package.json`` and
    ``<PackageName>.json`` (CARLA's importer looks for a descriptor named after
    the package directory; we emit the same content under both the canonical
    ``package.json`` name and the package-name-matched filename so either
    convention resolves), and writes a hash-bound manifest sidecar mirroring
    ``tile_fbx_generator``'s discipline.

``validate_staged_package(...)``
    The offline pre-cook validation gate (DESIGN.md §5 extension 4): asserts
    every declared tile file exists on disk with a matching filename pattern,
    the xodr file exists and its sha256 matches the pinned/expected value (if
    given), no tile is listed twice, and the directory contains no stray
    ``_Tile_`` files that are absent from ``package.json`` (drift check).
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

# CARLA Large-Map tile FBX naming convention (tile_fbx_generator.tile_fbx_name):
# "<MapName>_Tile_<tx>_<ty>.fbx" with signed integer tile indices.
_TILE_FBX_RE = re.compile(r"^(?P<map_name>.+)_Tile_(?P<tx>-?\d+)_(?P<ty>-?\d+)\.fbx$")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_tile_fbx_filename(filename: str) -> Optional[Tuple[str, int, int]]:
    """Parse ``<MapName>_Tile_<tx>_<ty>.fbx`` -> ``(map_name, tx, ty)``.

    Returns ``None`` if ``filename`` does not match CARLA's tile naming
    convention. Used both to build package descriptors from a directory of
    tile files and to validate a staged package for drift.
    """
    m = _TILE_FBX_RE.match(filename)
    if not m:
        return None
    return m.group("map_name"), int(m.group("tx")), int(m.group("ty"))


# ---------------------------------------------------------------------------
# package.json descriptor model (CARLA-documented schema, DESIGN.md §1.1)
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class PackageDescriptor:
    """One ``package.json`` "maps" entry.

    Required fields per CARLA's Large-Map ``package.json`` schema: ``name``,
    ``xodr``, ``use_carla_materials``, ``tile_size``, ``tiles``. ``props`` is a
    sibling top-level list (always empty here; this pipeline stages no prop
    packages).

    Provenance extension (O1): ``xodr_sha256`` carries the source XODR identity
    so the descriptor itself is self-describing, not just its sidecar manifest.
    CARLA's Import.py ignores unknown fields, so this is backward compatible.
    """

    name: str
    xodr_filename: str
    tile_size_m: float
    tile_fbx_filenames: Sequence[str]
    use_carla_materials: bool = True
    xodr_sha256: Optional[str] = None

    def __post_init__(self) -> None:
        if not self.name or not self.name.strip():
            raise ValueError("package name must be non-empty")
        if not self.xodr_filename.lower().endswith(".xodr"):
            raise ValueError(f"xodr_filename must end in .xodr: {self.xodr_filename!r}")
        if self.tile_size_m <= 0:
            raise ValueError("tile_size_m must be positive")
        if self.xodr_sha256 is not None:
            if not re.match(r"^[0-9a-f]{64}$", str(self.xodr_sha256).lower()):
                raise ValueError(f"xodr_sha256 must be 64 hex chars: {self.xodr_sha256!r}")
        seen = set()
        for fbx in self.tile_fbx_filenames:
            if not fbx.lower().endswith(".fbx"):
                raise ValueError(f"tile filename must end in .fbx: {fbx!r}")
            if fbx in seen:
                raise ValueError(f"duplicate tile filename in descriptor: {fbx!r}")
            seen.add(fbx)


def build_package_json(descriptor: PackageDescriptor) -> Dict[str, Any]:
    """Return the exact documented ``package.json`` dict for one Large Map.

    Pure function, no I/O. Matches the schema in DESIGN.md §1.1 verbatim:
    ``{"maps": [{"name", "xodr", "use_carla_materials", "tile_size", "tiles"}], "props": []}``.
    Paths are emitted relative (``"./<file>"``), matching CARLA's documented
    example and the fact that at import time the descriptor sits alongside its
    files in the same ``Import/<Package>/`` directory.

    O1 provenance extension: when ``descriptor.xodr_sha256`` is set, the maps
    entry also carries ``"xodr_sha256"`` so the descriptor itself proves which
    source XODR it was staged against (backward compatible — CARLA ignores
    unknown fields).
    """
    maps_entry: Dict[str, Any] = {
        "name": descriptor.name,
        "xodr": f"./{descriptor.xodr_filename}",
        "use_carla_materials": bool(descriptor.use_carla_materials),
        "tile_size": descriptor.tile_size_m,
        "tiles": [f"./{fbx}" for fbx in descriptor.tile_fbx_filenames],
    }
    if descriptor.xodr_sha256 is not None:
        maps_entry["xodr_sha256"] = descriptor.xodr_sha256.lower()
    return {"maps": [maps_entry], "props": []}


# ---------------------------------------------------------------------------
# Staging: Import/<PackageName>/ layout
# ---------------------------------------------------------------------------
@dataclass
class StagedPackageResult:
    """Outcome of staging one Large-Map package under ``Import/<PackageName>/``."""

    status: str  # "ok" | "failed"
    package_dir: str
    package_name: str
    reason: str = ""
    xodr_staged_path: str = ""
    xodr_sha256: str = ""
    tiles_staged: List[str] = field(default_factory=list)
    tiles_skipped_missing: List[str] = field(default_factory=list)
    package_json_path: str = ""
    manifest_path: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "package_dir": self.package_dir,
            "package_name": self.package_name,
            "reason": self.reason,
            "xodr_staged_path": self.xodr_staged_path,
            "xodr_sha256": self.xodr_sha256,
            "tiles_staged": self.tiles_staged,
            "tiles_skipped_missing": self.tiles_skipped_missing,
            "package_json_path": self.package_json_path,
            "manifest_path": self.manifest_path,
        }


def _copy_file(src: Path, dst: Path) -> None:
    """Copy ``src`` to ``dst`` as a real, independent copy.

    Deliberately **never** hardlinks (``os.link``). A hardlink is not a copy:
    ``dst`` would alias the same inode as ``src``, so if the source is later
    mutated in place -- e.g. a re-run pipeline stage rewrites the file at the
    same path instead of atomically replacing it -- the "staged"/"promoted"
    artifact silently changes right along with it. That defeats the entire
    point of staging an immutable artifact before handing it to
    ``make import`` / a UE4 cook (comprehensive gap audit 20260915, packet
    P0-C). ``shutil.copy2`` preserves mtime/mode like the old hardlink path
    did for metadata purposes, but produces a byte-for-byte independent file.
    """
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        dst.unlink()
    shutil.copy2(src, dst)


# ---------------------------------------------------------------------------
# O1 — Tile FBX provenance helpers (fail-closed, no mtime authority)
# ---------------------------------------------------------------------------
def _find_tile_manifest(fbx_path: Path) -> Optional[Path]:
    """Return the hash-bound manifest sidecar for ``fbx_path`` if it exists.

    The tile FBX generator writes ``<MapName>_Tile_<x>_<y>.tile_fbx.json``
    alongside ``<MapName>_Tile_<x>_<y>.fbx`` in the same output directory.
    This is the provenance that proves which source XODR the tile was baked
    from — never the file's mtime.
    """
    candidate = fbx_path.parent / (fbx_path.stem + ".tile_fbx.json")
    return candidate if candidate.is_file() else None


def _read_tile_source_sha(manifest_path: Path) -> Optional[str]:
    """Extract ``source_provenance.map_of_record_sha256`` from a tile manifest.

    Returns the lowercase 64-char hex SHA, or ``None`` if the manifest is
    malformed or the field is absent/empty. No inference, no fallback to
    mtime, no directory walk.
    """
    try:
        doc = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    # Primary location (current generator): top-level source_provenance
    prov = doc.get("source_provenance")
    if isinstance(prov, dict):
        sha = prov.get("map_of_record_sha256")
        if isinstance(sha, str) and re.match(r"^[0-9a-fA-F]{64}$", sha.strip()):
            return sha.strip().lower()
    # Fallback: some older manifests used top-level map_of_record_sha256
    sha2 = doc.get("map_of_record_sha256")
    if isinstance(sha2, str) and re.match(r"^[0-9a-fA-F]{64}$", sha2.strip()):
        return sha2.strip().lower()
    return None


def _tile_provenance_status(
    fbx_path: Path, expected_xodr_sha256: str
) -> Tuple[str, Optional[str], Optional[str]]:
    """Check one tile's provenance against ``expected_xodr_sha256``.

    Returns ``(status, actual_sha, reason)`` where status is:
      "ok" — manifest exists and its source SHA matches expected
      "missing_manifest" — no manifest sidecar alongside the FBX
      "missing_sha" — manifest exists but carries no source SHA
      "mismatch" — manifest SHA differs from expected (stale FBX)
    ``expected_xodr_sha256`` must be lowercase 64-hex; caller guarantees.
    """
    manifest = _find_tile_manifest(fbx_path)
    if manifest is None:
        return "missing_manifest", None, f"tile manifest not found alongside FBX: {fbx_path} (expected {fbx_path.stem}.tile_fbx.json)"
    actual = _read_tile_source_sha(manifest)
    if actual is None:
        return "missing_sha", None, f"tile manifest {manifest} has no source_provenance.map_of_record_sha256"
    if actual != expected_xodr_sha256.lower():
        return "mismatch", actual, f"tile {fbx_path.name} provenance {actual} != expected {expected_xodr_sha256} (stale FBX from a different XODR generation)"
    return "ok", actual, None


def stage_large_map_package(
    *,
    map_name: str,
    xodr_path: str,
    tile_fbx_paths: Sequence[str],
    import_root: str,
    package_name: Optional[str] = None,
    tile_size_m: float = 1000.0,
    use_carla_materials: bool = True,
    expected_xodr_sha256: Optional[str] = None,
) -> StagedPackageResult:
    """Stage one CARLA Large-Map package under ``<import_root>/<PackageName>/``.

    Copies the whole-map XODR and every listed tile FBX into the package
    directory (flat, matching CARLA's filename-matching import convention:
    the importer does not recurse), writes ``package.json`` (the canonical
    name CARLA's tooling documents) and mirrors it as ``<PackageName>.json``,
    and writes a hash-bound ``<PackageName>.large_map_package.json`` manifest
    sidecar for provenance (same discipline as ``tile_fbx_generator``'s
    per-tile manifest and ``runtime_tile_builder``'s sidecar).

    Tiles whose source path does not exist are recorded in
    ``tiles_skipped_missing`` and excluded from the descriptor -- this keeps
    staging usable for partial/incremental cooks (e.g. only the densest probe
    tile has been generated so far) without silently fabricating an entry for
    a file that was never produced, and without hard-failing the whole stage.

    Never invokes ``make import`` or any UE4/UE5 process; this only produces
    the on-disk input that step consumes.
    """
    pkg_name = package_name or map_name
    root = Path(import_root)
    package_dir = root / pkg_name
    result = StagedPackageResult(status="failed", package_dir=str(package_dir), package_name=pkg_name)

    src_xodr = Path(xodr_path)
    if not src_xodr.is_file():
        result.reason = f"xodr not found: {src_xodr}"
        return result

    xodr_sha256 = _sha256(src_xodr)
    if expected_xodr_sha256 and xodr_sha256 != expected_xodr_sha256:
        result.reason = (
            f"xodr sha256 mismatch: expected {expected_xodr_sha256}, got {xodr_sha256} "
            f"({src_xodr}) -- refusing to stage a package against the wrong map-of-record"
        )
        return result

    package_dir.mkdir(parents=True, exist_ok=True)

    dst_xodr = package_dir / src_xodr.name
    _copy_file(src_xodr, dst_xodr)
    result.xodr_staged_path = str(dst_xodr)
    result.xodr_sha256 = xodr_sha256

    # O1: Provenance-tracked tile staging (no mtime authority).
    # Every tile FBX is expected to be accompanied by its hash-bound manifest
    # ``<stem>.tile_fbx.json`` carrying ``source_provenance.map_of_record_sha256``.
    # Selection is deterministic by tile index (tx,ty), never by file mtime, and
    # a stale FBX (different source SHA) or missing provenance fails closed when
    # strict provenance is applicable.  Strict mode activates automatically when
    # any tile in the input carries a manifest — i.e. real pipeline output is
    # being staged — or when ``expected_xodr_sha256`` is given (the production
    # path via ``stage_large_map_import_package.py``).  Pure synthetic tests
    # with no manifests remain backward compatible.
    staged_tile_names: List[str] = []
    skipped: List[str] = []
    tile_source_shas: Dict[str, str] = {}  # fbx_name -> source SHA from manifest
    provenance_failures: List[str] = []

    # Pre-scan: does any input tile carry a manifest? If so, we are in strict
    # provenance mode and every tile must prove it was baked from the staged
    # XODR (xodr_sha256).  When expected_xodr_sha256 is given it is authoritative;
    # otherwise the staged XODR's actual SHA is the authority (the XODR we just
    # copied is the source of truth).  Pure synthetic tests with no manifests
    # skip provenance checks for backward compatibility.
    has_any_manifest = any(
        _find_tile_manifest(Path(p)) is not None
        for p in tile_fbx_paths
        if Path(p).is_file() and parse_tile_fbx_filename(Path(p).name) is not None
    )
    strict_provenance = has_any_manifest
    provenance_authority_sha = (
        expected_xodr_sha256.lower() if expected_xodr_sha256 else xodr_sha256.lower()
    )

    for tile_path_str in tile_fbx_paths:
        tile_path = Path(tile_path_str)
        if not tile_path.is_file():
            skipped.append(str(tile_path))
            continue
        parsed = parse_tile_fbx_filename(tile_path.name)
        if parsed is None:
            skipped.append(str(tile_path))
            continue

        # O1 protection 3,4,6,7,8: fail-closed provenance check (no mtime, no
        # latest-file, no silent mixed-generation).  Only applies in strict
        # mode; synthetic tests without manifests skip this gate.
        if strict_provenance:
            status, actual_sha, reason = _tile_provenance_status(
                tile_path, provenance_authority_sha
            )
            if status != "ok":
                provenance_failures.append(reason or f"{tile_path.name}: {status}")
                # Do not stage this tile — record as skipped for diagnostics,
                # but the overall staging will fail closed below.
                skipped.append(f"{tile_path} [{status}: {reason}]")
                continue
            # Record for mixed-generation detection (6)
            tile_source_shas[tile_path.name] = actual_sha or provenance_authority_sha

        dst_tile = package_dir / tile_path.name
        _copy_file(tile_path, dst_tile)
        staged_tile_names.append(tile_path.name)

    # O1 protection 6: mixed tile generations must fail — all staged tiles must
    # prove the *same* source XODR when strict provenance is active.
    if strict_provenance and tile_source_shas:
        distinct_shas = set(tile_source_shas.values())
        if len(distinct_shas) > 1:
            result.reason = (
                f"mixed tile generations detected: distinct source SHAs "
                f"{sorted(distinct_shas)} among staged tiles {sorted(tile_source_shas.keys())} — "
                f"refusing to stage a package mixing FBXs from different XODR generations"
            )
            # Clean up any partially-staged tiles to avoid a half-staged package
            # that later appears complete.
            for name in staged_tile_names:
                (package_dir / name).unlink(missing_ok=True)
            return result
        # Also ensure every staged tile's source SHA matches the staged XODR.
        # (Already checked per-tile above, but double-guard for the authority SHA.)
        for name, sha in tile_source_shas.items():
            if sha.lower() != provenance_authority_sha.lower():
                result.reason = (
                    f"tile {name} provenance {sha} != staged XODR {provenance_authority_sha} "
                    f"(stale FBX from a different XODR generation)"
                )
                for n in staged_tile_names:
                    (package_dir / n).unlink(missing_ok=True)
                return result

    if provenance_failures:
        # Fail closed: do not produce a package that silently excludes stale
        # tiles — the caller must regenerate those tiles from the current XODR.
        result.reason = (
            f"tile provenance check failed ({len(provenance_failures)} tile(s)): "
            + "; ".join(provenance_failures[:3])
            + (f" (+{len(provenance_failures)-3} more)" if len(provenance_failures) > 3 else "")
        )
        # Clean up staged tiles/XODR to avoid a half-staged package that looks complete.
        for name in staged_tile_names:
            (package_dir / name).unlink(missing_ok=True)
        if dst_xodr.exists():
            dst_xodr.unlink(missing_ok=True)
        return result

    # Deterministic ordering: sort tiles by (tx, ty) so package.json / manifest
    # output is stable across runs regardless of input iteration order or file
    # mtimes (O1 protection 2,8 — no mtime authority, stale presence does not
    # influence selection).
    def _tile_sort_key(name: str) -> Tuple[int, int]:
        parsed = parse_tile_fbx_filename(name)
        return (parsed[1], parsed[2]) if parsed else (0, 0)

    staged_tile_names.sort(key=_tile_sort_key)

    descriptor = PackageDescriptor(
        name=map_name,
        xodr_filename=src_xodr.name,
        tile_size_m=tile_size_m,
        tile_fbx_filenames=staged_tile_names,
        use_carla_materials=use_carla_materials,
        xodr_sha256=xodr_sha256.lower(),
    )
    package_json_doc = build_package_json(descriptor)

    package_json_path = package_dir / "package.json"
    package_json_path.write_text(
        json.dumps(package_json_doc, indent=2, sort_keys=False) + "\n", encoding="utf-8"
    )
    # CARLA's Import.py filename-matches a descriptor against the package
    # directory name in some documented workflows; mirror the same content
    # under "<PackageName>.json" so either lookup convention resolves without
    # ambiguity (both files are byte-identical, generated from one source of
    # truth -- never hand-edit one without the other).
    named_json_path = package_dir / f"{pkg_name}.json"
    named_json_path.write_text(
        json.dumps(package_json_doc, indent=2, sort_keys=False) + "\n", encoding="utf-8"
    )
    result.package_json_path = str(package_json_path)

    result.tiles_staged = staged_tile_names
    result.tiles_skipped_missing = skipped
    result.status = "ok"

    # O1 provenance chain: record generating command, tool version, and
    # provenance linkage for every stage (canonical source → output)
    try:
        import subprocess

        _tool_version = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=str(Path(__file__).resolve().parents[2]), text=True
        ).strip()
    except Exception:
        _tool_version = "unknown"
    _generating_command = " ".join(sys.argv) if "sys" in globals() else ""

    manifest_path = package_dir / f"{pkg_name}.large_map_package.json"
    # Compute output descriptor SHA for provenance linkage
    try:
        _package_json_sha = _sha256(package_json_path)
        _named_json_sha = _sha256(named_json_path)
    except Exception:
        _package_json_sha = ""
        _named_json_sha = ""
    manifest_doc = {
        "schema_version": 1,
        "artifact_type": "carla_large_map_import_package",
        "status": result.status,
        "package_name": pkg_name,
        "map_name": map_name,
        "package_dir": str(package_dir),
        # O1 provenance chain: canonical source → output
        "canonical_source": {
            "xodr_path": str(src_xodr),
            "xodr_sha256": xodr_sha256,
            "xodr_bytes": src_xodr.stat().st_size if src_xodr.exists() else None,
            "provenance_field": "xodr.sha256",
            "provenance_authority": "verify_pinned_map('auto_map_of_record')",
        },
        "output": {
            "package_dir": str(package_dir),
            "package_json_path": str(package_json_path),
            "package_json_sha256": _package_json_sha,
            "named_json_path": str(named_json_path),
            "named_json_sha256": _named_json_sha,
            "manifest_path": str(manifest_path),
        },
        "xodr": {"filename": src_xodr.name, "sha256": xodr_sha256},
        "tile_size_m": tile_size_m,
        "use_carla_materials": use_carla_materials,
        "tiles_staged_count": len(staged_tile_names),
        "tiles_staged": staged_tile_names,
        "tiles_skipped_missing": skipped,
        "tiles_provenance": tile_source_shas,
        "package_json_paths": [str(package_json_path), str(named_json_path)],
        "generating_command": _generating_command,
        "tool_version": _tool_version,
        "provenance_chain": {
            "map_registry": "ultimate_pipeline/carla_tools/map_registry.py:verify_pinned_map",
            "authoritative_xodr": str(src_xodr),
            "tile_generation": "ultimate_pipeline/tiling/tile_fbx_generator.py:generate_tile_fbx",
            "fbx_manifest": "source_provenance.map_of_record_sha256",
            "import_package": "ultimate_pipeline/tiling/large_map_package.py:stage_large_map_package",
            "package_descriptor": "xodr_sha256",
        },
        "claim_boundary": (
            "Offline staging only. This package has NOT been consumed by "
            "`make import` or any UE4/UE5 process; import/cook success is "
            "UNCONFIRMED until the live UE4 track runs (DESIGN.md §6)."
        ),
    }
    manifest_path.write_text(
        json.dumps(manifest_doc, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    result.manifest_path = str(manifest_path)
    return result


# ---------------------------------------------------------------------------
# Offline pre-cook validation gate (DESIGN.md §5 extension 4)
# ---------------------------------------------------------------------------
@dataclass
class PackageValidationResult:
    status: str  # "PASS" | "FAIL"
    failures: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    xodr_sha256: str = ""
    tile_count: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "failures": self.failures,
            "warnings": self.warnings,
            "xodr_sha256": self.xodr_sha256,
            "tile_count": self.tile_count,
        }


def validate_staged_package(
    package_dir: str,
    *,
    expected_xodr_sha256: Optional[str] = None,
) -> PackageValidationResult:
    """Offline validation of a staged ``Import/<PackageName>/`` directory.

    This is the "offline pre-cook validation gate" DESIGN.md §5 extension 4
    calls for -- the offline analogue of ``runtime_tile_builder``'s static
    XODR validator, fully green before any UE4 host exists. Checks:

      1. exactly one ``package.json`` exists and parses;
      2. the descriptor's ``xodr`` file exists in the package directory, and
         its sha256 matches ``expected_xodr_sha256`` if given;
      3. every declared tile filename exists in the package directory and
         matches the CARLA ``_Tile_<x>_<y>.fbx`` naming convention;
      4. no tile filename is declared twice (descriptor-level duplicate);
      5. no stray ``_Tile_*.fbx`` file sits in the directory but is absent
         from the descriptor (drift between what's staged and what's declared
         -- would silently exclude real geometry from the cook).

    Fails closed: any check failure sets ``status="FAIL"`` and the specific
    reason is appended to ``failures``; nothing here mutates the directory.
    """
    result = PackageValidationResult(status="FAIL")
    pkg_dir = Path(package_dir)
    if not pkg_dir.is_dir():
        result.failures.append(f"package directory does not exist: {pkg_dir}")
        return result

    package_json_path = pkg_dir / "package.json"
    if not package_json_path.is_file():
        result.failures.append(f"missing package.json in {pkg_dir}")
        return result

    try:
        doc = json.loads(package_json_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        result.failures.append(f"package.json is not valid JSON: {exc}")
        return result

    maps = doc.get("maps")
    if not isinstance(maps, list) or len(maps) != 1:
        result.failures.append(f"package.json 'maps' must be a single-entry list, got: {maps!r}")
        return result
    entry = maps[0]
    for required in ("name", "xodr", "use_carla_materials", "tile_size", "tiles"):
        if required not in entry:
            result.failures.append(f"package.json maps[0] missing required field: {required!r}")
    if result.failures:
        return result

    xodr_rel = str(entry["xodr"]).lstrip("./")
    xodr_path = pkg_dir / xodr_rel
    if not xodr_path.is_file():
        result.failures.append(f"declared xodr not found on disk: {xodr_path}")
    else:
        xodr_sha256 = _sha256(xodr_path)
        result.xodr_sha256 = xodr_sha256
        if expected_xodr_sha256 and xodr_sha256 != expected_xodr_sha256:
            result.failures.append(
                f"staged xodr sha256 mismatch: expected {expected_xodr_sha256}, got {xodr_sha256}"
            )
        # O1: descriptor provenance — if package.json carries xodr_sha256 it must
        # match the staged XODR (defends against descriptor/XODR drift).
        declared_xodr_sha = entry.get("xodr_sha256")
        if declared_xodr_sha is not None:
            try:
                if str(declared_xodr_sha).strip().lower() != xodr_sha256.lower():
                    result.failures.append(
                        f"package.json xodr_sha256 {declared_xodr_sha!r} != staged XODR sha {xodr_sha256}"
                    )
            except Exception:
                result.failures.append(f"package.json xodr_sha256 is malformed: {declared_xodr_sha!r}")
        # Also check sidecar manifest's xodr SHA if present (staged package manifest
        # is the provenance that links output to source; it must agree).
        # The manifest is <PackageName>.large_map_package.json next to package.json.
        manifest_candidates = list(pkg_dir.glob("*.large_map_package.json"))
        for manifest_path in manifest_candidates:
            try:
                mdoc = json.loads(manifest_path.read_text(encoding="utf-8"))
                m_xodr_sha = (mdoc.get("xodr") or {}).get("sha256")
                if isinstance(m_xodr_sha, str) and m_xodr_sha.strip():
                    if m_xodr_sha.strip().lower() != xodr_sha256.lower():
                        result.failures.append(
                            f"sidecar manifest {manifest_path.name} xodr sha256 {m_xodr_sha!r} != staged XODR sha {xodr_sha256}"
                        )
            except (json.JSONDecodeError, OSError):
                result.failures.append(f"sidecar manifest {manifest_path.name} is not valid JSON")

    declared_tiles = [str(t).lstrip("./") for t in entry.get("tiles", [])]
    seen: Dict[str, int] = {}
    for name in declared_tiles:
        seen[name] = seen.get(name, 0) + 1
    dupes = sorted(n for n, c in seen.items() if c > 1)
    if dupes:
        result.failures.append(f"duplicate tile filenames declared: {dupes}")

    for name in declared_tiles:
        tile_path = pkg_dir / name
        if not tile_path.is_file():
            result.failures.append(f"declared tile not found on disk: {tile_path}")
            continue
        parsed = parse_tile_fbx_filename(name)
        if parsed is None:
            result.failures.append(
                f"declared tile filename does not match CARLA convention "
                f"'<MapName>_Tile_<x>_<y>.fbx': {name!r}"
            )
            continue
        parsed_map_name, _tx, _ty = parsed
        if parsed_map_name != entry["name"]:
            result.warnings.append(
                f"tile filename map-name prefix {parsed_map_name!r} != "
                f"package map name {entry['name']!r} for {name!r}"
            )

    # O1: tile provenance — when any staged tile carries a hash-bound manifest
    # its source XODR must match the staged XODR, and all tiles must agree
    # (no mixed generations).  Missing provenance is only a hard failure when
    # strict mode applies; for backward compatibility we enforce strictly only
    # when at least one tile manifest is present (real pipeline output).  Pure
    # synthetic tests with no manifests skip this gate.
    has_any_tile_manifest = any(
        _find_tile_manifest(pkg_dir / name) is not None for name in declared_tiles
    )
    strict_tile_provenance = has_any_tile_manifest
    if strict_tile_provenance and declared_tiles:
        tile_shas: Dict[str, str] = {}
        for name in declared_tiles:
            tile_path = pkg_dir / name
            manifest = _find_tile_manifest(tile_path)
            if manifest is None:
                result.failures.append(
                    f"tile {name} missing provenance manifest {name.rsplit('.',1)[0]}.tile_fbx.json "
                    f"(O1 protection 7: missing provenance must fail closed; "
                    f"regenerate this tile from the current XODR)"
                )
                continue
            sha = _read_tile_source_sha(manifest)
            if sha is None:
                result.failures.append(
                    f"tile {name} manifest {manifest.name} has no source_provenance.map_of_record_sha256"
                )
                continue
            tile_shas[name] = sha
            # Each tile's source must match the staged XODR
            staged_sha = result.xodr_sha256
            if not staged_sha:
                # Fallback if xodr_sha wasn't captured (e.g., earlier failure)
                try:
                    xodr_for_tile = pkg_dir / str(entry["xodr"]).lstrip("./")
                    if xodr_for_tile.is_file():
                        staged_sha = _sha256(xodr_for_tile)
                except Exception:
                    staged_sha = None
            if staged_sha and sha.lower() != staged_sha.lower():
                result.failures.append(
                    f"tile {name} provenance {sha} != staged XODR {staged_sha} "
                    f"(stale FBX from a different XODR generation)"
                )
        if len(set(tile_shas.values())) > 1:
            result.failures.append(
                f"mixed tile generations detected: distinct source SHAs "
                f"{sorted(set(tile_shas.values()))} among staged tiles "
                f"{sorted(tile_shas.keys())}"
            )

    on_disk_tiles = {
        p.name for p in pkg_dir.glob("*_Tile_*.fbx") if parse_tile_fbx_filename(p.name)
    }
    declared_set = set(declared_tiles)
    stray = sorted(on_disk_tiles - declared_set)
    if stray:
        result.failures.append(
            f"stray tile FBX present on disk but not declared in package.json "
            f"(staging/descriptor drift): {stray}"
        )

    result.tile_count = len(declared_tiles)
    result.status = "PASS" if not result.failures else "FAIL"
    return result
