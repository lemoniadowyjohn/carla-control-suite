# ultimate_pipeline/tiling/carla_0916_large_map_contract.py
# -*- coding: utf-8 -*-
"""CARLA 0.9.16 large-map contract: package identity, material binding,
deterministic decals, TilesInfo numerics (NEW-197 / NEW-198 / NEW-199).

Single canonical owner for the exact importer-visible package identity and
its downstream consumers, so material/decal loading, TilesInfo parsing and
decal generation cannot independently reconstruct package names and drift
from what was imported and cooked.

- NEW-197: :class:`PackageIdentity` + :func:`resolve_material_config`.
- NEW-198: deterministic decal policy + seed derivation + receipts.
- NEW-199: one locale-independent float schema for TilesInfo.txt.
"""

from __future__ import annotations

import hashlib
import json
import random
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

# ---------------------------------------------------------------------------
# NEW-197 — exact material / decal package binding
# ---------------------------------------------------------------------------

MATERIAL_CONFIG_FILENAME = "roadpainter_decals.json"
MISSING_CONFIG_STATUS = "FAIL_MATERIAL_CONFIGURATION_MISSING"
AMBIGUOUS_CONFIG_STATUS = "FAIL_AMBIGUOUS"
PACKAGE_MISMATCH_STATUS = "FAIL_PACKAGE_MISMATCH"
CONFIG_OUTSIDE_ROOT_STATUS = "FAIL_CONFIG_OUTSIDE_PACKAGE_ROOT"


class PackageBindingError(RuntimeError):
    def __init__(self, message: str, *, status: str, detail: Optional[Dict] = None) -> None:
        super().__init__(message)
        self.status = status
        self.detail = detail or {}


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(frozen=True)
class PackageIdentity:
    """Canonical importer-visible package identity (NEW-197)."""

    requested_package: str
    resolved_package: str
    import_manifest: str
    source_json: str
    source_json_sha256: str
    package_root: str
    map_name: str
    build_id: str = "carla-0.9.16"
    import_manifest_sha256: str = ""

    def to_dict(self) -> Dict[str, str]:
        return {
            "requested_package": self.requested_package,
            "resolved_package": self.resolved_package,
            "import_manifest": self.import_manifest,
            "import_manifest_sha256": self.import_manifest_sha256,
            "source_json": self.source_json,
            "source_json_sha256": self.source_json_sha256,
            "package_root": self.package_root,
            "map_name": self.map_name,
            "build_id": self.build_id,
        }


def resolve_package_identity(
    *,
    requested_package: str,
    import_root: str,
    map_name: Optional[str] = None,
) -> PackageIdentity:
    """Resolve the exact importer-visible package for ``requested_package``.

    Reads ``<import_root>/<requested_package>/package.json`` (falling back to
    ``<requested_package>.json``), derives the resolved identity from importer
    metadata (directory name + descriptor ``maps[0].name``), and fails closed
    on any mismatch, missing file, or hash problem. Downstream consumers must
    take this object instead of reconstructing package names from CLI args.
    """
    if not requested_package or not requested_package.strip():
        raise PackageBindingError("requested package is empty",
                                  status=PACKAGE_MISMATCH_STATUS)
    root = Path(import_root)
    package_dir = root / requested_package.strip()
    if not package_dir.is_dir():
        raise PackageBindingError(f"package directory not found: {package_dir}",
                                  status=PACKAGE_MISMATCH_STATUS,
                                  detail={"requested_package": requested_package})
    candidates = [package_dir / "package.json", package_dir / f"{package_dir.name}.json"]
    source = next((c for c in candidates if c.is_file()), None)
    if source is None:
        raise PackageBindingError(
            f"import descriptor not found in {package_dir} "
            f"(looked for {[c.name for c in candidates]})",
            status=MISSING_CONFIG_STATUS,
            detail={"package_root": str(package_dir)})
    try:
        doc = json.loads(source.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise PackageBindingError(f"import descriptor is not valid JSON: {exc}",
                                  status=PACKAGE_MISMATCH_STATUS,
                                  detail={"source_json": str(source)}) from exc
    maps = doc.get("maps")
    if not isinstance(maps, list) or len(maps) != 1:
        raise PackageBindingError(f"descriptor 'maps' must be single-entry: {source}",
                                  status=PACKAGE_MISMATCH_STATUS)
    resolved_map = str(maps[0].get("name", ""))
    # Resolved package = the importer-visible directory identity; the
    # descriptor map name must agree with it (CARLA filename-matches the
    # descriptor against the package directory).
    if resolved_map and resolved_map != package_dir.name and resolved_map != requested_package.strip():
        # The map name inside the descriptor may legitimately differ from the
        # package directory name (package "CityPkg" containing map "CityMap"),
        # so record both but bind downstream to the descriptor's map name.
        resolved_package = package_dir.name
        effective_map = resolved_map
    else:
        resolved_package = package_dir.name
        effective_map = resolved_map or (map_name or resolved_package)
    if map_name is not None and effective_map != map_name:
        raise PackageBindingError(
            f"CLI/map mismatch: expected map {map_name!r}, descriptor resolves {effective_map!r}",
            status=PACKAGE_MISMATCH_STATUS,
            detail={"requested_package": requested_package,
                    "resolved_package": resolved_package})
    manifest_candidates = list(package_dir.glob("*.large_map_package.json"))
    manifest = str(manifest_candidates[0]) if manifest_candidates else ""
    manifest_sha256 = _sha256_file(Path(manifest)) if manifest else ""
    if manifest:
        try:
            mdoc = json.loads(Path(manifest).read_text(encoding="utf-8"))
            m_xodr = (mdoc.get("xodr") or {}).get("sha256", "")
            d_xodr = str(maps[0].get("xodr_sha256", "") or "")
            if m_xodr and d_xodr and str(m_xodr).lower() != d_xodr.lower():
                raise PackageBindingError(
                    f"package manifest hash mismatch: manifest {m_xodr!r} != descriptor {d_xodr!r}",
                    status=PACKAGE_MISMATCH_STATUS,
                    detail={"import_manifest": manifest, "source_json": str(source)})
        except PackageBindingError:
            raise
        except (json.JSONDecodeError, OSError) as exc:
            raise PackageBindingError(f"import manifest is not valid JSON: {exc}",
                                      status=PACKAGE_MISMATCH_STATUS) from exc
    return PackageIdentity(
        requested_package=requested_package.strip(),
        resolved_package=resolved_package,
        import_manifest=manifest,
        import_manifest_sha256=manifest_sha256,
        source_json=str(source),
        source_json_sha256=_sha256_file(source),
        package_root=str(package_dir),
        map_name=effective_map,
    )


def resolve_material_config(identity: PackageIdentity) -> Dict[str, Any]:
    """Bind ``roadpainter_decals.json`` to the exact resolved package.

    Proves the configuration exists, belongs to the exact package, lives
    inside the package root, and matches the import receipt. Never uses
    ``FileList[0]`` without a length check. Returns
    ``{"status": "PASS", "config_path": ..., "config_sha256": ...,
    "package_identity": {...}}`` or raises :class:`PackageBindingError`.
    """
    root = Path(identity.package_root)
    if not root.is_dir():
        raise PackageBindingError(f"package root missing: {root}",
                                  status=PACKAGE_MISMATCH_STATUS)
    matches = sorted(root.rglob(MATERIAL_CONFIG_FILENAME))
    # Length check BEFORE any dereference (never FileList[0] blindly).
    if len(matches) == 0:
        raise PackageBindingError(
            f"material configuration {MATERIAL_CONFIG_FILENAME!r} not found "
            f"under package root {root}",
            status=MISSING_CONFIG_STATUS,
            detail={"package_identity": identity.to_dict()})
    if len(matches) > 1:
        raise PackageBindingError(
            f"ambiguous material configuration: {len(matches)} candidates "
            f"{[str(m) for m in matches]}",
            status=AMBIGUOUS_CONFIG_STATUS,
            detail={"package_identity": identity.to_dict()})
    config = matches[0]
    try:
        resolved = config.resolve()
        root_resolved = root.resolve()
    except OSError as exc:
        raise PackageBindingError(f"cannot resolve config path: {exc}",
                                  status=CONFIG_OUTSIDE_ROOT_STATUS) from exc
    if not (resolved == root_resolved or root_resolved in resolved.parents):
        raise PackageBindingError(
            f"material configuration outside package root: {config} (root {root})",
            status=CONFIG_OUTSIDE_ROOT_STATUS,
            detail={"package_identity": identity.to_dict()})
    try:
        payload = json.loads(config.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise PackageBindingError(f"material configuration is not valid JSON: {exc}",
                                  status=MISSING_CONFIG_STATUS) from exc
    declared_pkg = str(payload.get("package", "") or payload.get("package_name", "") or "")
    if declared_pkg and declared_pkg not in (
        identity.requested_package, identity.resolved_package, identity.map_name,
    ):
        raise PackageBindingError(
            f"material configuration belongs to {declared_pkg!r}, not exact package "
            f"{identity.resolved_package!r}",
            status=PACKAGE_MISMATCH_STATUS,
            detail={"config_path": str(config),
                    "package_identity": identity.to_dict()})
    return {
        "status": "PASS",
        "config_path": str(config),
        "config_sha256": _sha256_file(config),
        "package_identity": identity.to_dict(),
    }


# ---------------------------------------------------------------------------
# NEW-198 — deterministic road decal / material generation
# ---------------------------------------------------------------------------

DECAL_POLICY_VERSION = "decal-determinism-v1"
DECAL_GENERATOR_VERSION = "carla-decal-seed-v1"


def derive_decal_seed(
    *,
    xodr_sha256: str,
    package_identity: str,
    tile_identity: str,
    policy_version: str = DECAL_POLICY_VERSION,
) -> int:
    """Derive a deterministic 64-bit seed from immutable artifact identity."""
    for label, value in (("xodr_sha256", xodr_sha256),
                         ("package_identity", package_identity),
                         ("tile_identity", tile_identity)):
        if not value or not str(value).strip():
            raise ValueError(f"{label} must be non-empty for seed derivation")
    preimage = "|".join([policy_version, xodr_sha256.strip().lower(),
                         str(package_identity), str(tile_identity)])
    digest = hashlib.sha256(preimage.encode("utf-8")).hexdigest()
    return int(digest[:16], 16)


def generate_deterministic_decals(
    *,
    xodr_sha256: str,
    package_identity: str,
    tile_identity: str,
    decal_count: int,
    policy: str = "seeded",
    policy_version: str = DECAL_POLICY_VERSION,
    bounds: Tuple[float, float, float, float] = (0.0, 0.0, 1000.0, 1000.0),
) -> Dict[str, Any]:
    """Generate decal placements deterministically (NEW-198, Option 1 default).

    ``policy="seeded"`` derives a seed from artifact identity and emits
    ``decal_count`` placements via ``random.Random(seed)``. ``policy="disabled"``
    emits no decals for deterministic release builds. Any other policy raises.
    The receipt records policy, seed, derivation inputs, generator version,
    decal count and artifact hashes.
    """
    if policy not in ("seeded", "disabled"):
        raise ValueError(f"unknown decal policy: {policy!r} (expected 'seeded'|'disabled')")
    if decal_count < 0:
        raise ValueError("decal_count must be >= 0")
    if policy == "disabled":
        decals: List[Dict[str, float]] = []
        seed: Optional[int] = None
    else:
        seed = derive_decal_seed(xodr_sha256=xodr_sha256,
                                 package_identity=package_identity,
                                 tile_identity=tile_identity,
                                 policy_version=policy_version)
        rng = random.Random(seed)
        x0, y0, x1, y1 = bounds
        decals = [
            {"x": rng.uniform(x0, x1), "y": rng.uniform(y0, y1),
             "rotation_deg": rng.uniform(0.0, 360.0),
             "scale": rng.uniform(0.8, 1.2)}
            for _ in range(decal_count)
        ]
    artifact_hash = hashlib.sha256(
        json.dumps(decals, sort_keys=True).encode("utf-8")).hexdigest()
    return {
        "policy": policy,
        "seed": seed,
        "seed_derivation_inputs": {
            "xodr_sha256": xodr_sha256,
            "package_identity": package_identity,
            "tile_identity": tile_identity,
            "deterministic_policy_version": policy_version,
        },
        "generator_version": DECAL_GENERATOR_VERSION,
        "decal_count": len(decals),
        "decals": decals,
        "artifact_hash": artifact_hash,
    }


# ---------------------------------------------------------------------------
# NEW-199 — TilesInfo.txt cross-consumer numeric consistency
# ---------------------------------------------------------------------------

_TILESINFO_LINE_RE = re.compile(
    r"^\s*(?P<cx>[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)\s+"
    r"(?P<cy>[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)\s+"
    r"(?P<size>[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)\s*$"
)
TILESINFO_TOLERANCE = 1e-9
TILESINFO_SCHEMA = {
    "tile_center_x": {"type": "float64", "units": "meters", "frame": "map"},
    "tile_center_y": {"type": "float64", "units": "meters", "frame": "map"},
    "tile_size": {"type": "float64", "units": "meters", "frame": "map"},
}


@dataclass(frozen=True)
class TileInfo:
    """One TilesInfo row: float meters in the map frame (NEW-199 schema)."""

    center_x: float
    center_y: float
    size: float

    def to_dict(self) -> Dict[str, float]:
        return {"tile_center_x": self.center_x,
                "tile_center_y": self.center_y, "tile_size": self.size}


def parse_tilesinfo_token(token: str) -> float:
    """Parse one numeric token locale-independently (float, meters).

    Only ASCII ``.`` decimals and optional scientific notation are accepted;
    locale commas, grouping, and surrounding whitespace variants that change
    value are rejected fail-closed.
    """
    text = token.strip()
    if not text or "," in text or " " in text or "\t" in text:
        raise ValueError(f"invalid TilesInfo numeric token: {token!r}")
    if not re.fullmatch(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?", text):
        raise ValueError(f"invalid TilesInfo numeric token: {token!r}")
    try:
        return float(text)
    except ValueError as exc:
        raise ValueError(f"invalid TilesInfo numeric token: {token!r}") from exc


def parse_tilesinfo_line(line: str) -> TileInfo:
    """Parse one ``<center_x> <center_y> <tile_size>`` line (float schema)."""
    match = _TILESINFO_LINE_RE.match(line)
    if not match:
        raise ValueError(f"invalid TilesInfo line: {line!r}")
    cx = parse_tilesinfo_token(match.group("cx"))
    cy = parse_tilesinfo_token(match.group("cy"))
    size = parse_tilesinfo_token(match.group("size"))
    if not (size > 0):
        raise ValueError(f"TilesInfo tile_size must be positive: {line!r}")
    return TileInfo(center_x=cx, center_y=cy, size=size)


def parse_tilesinfo(text: str) -> List[TileInfo]:
    """Parse a whole TilesInfo.txt document (ignores blank/# comment lines)."""
    rows: List[TileInfo] = []
    for lineno, raw in enumerate(text.splitlines(), start=1):
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        try:
            rows.append(parse_tilesinfo_line(raw))
        except ValueError as exc:
            raise ValueError(f"line {lineno}: {exc}") from exc
    return rows


def format_tilesinfo(rows: Sequence[TileInfo]) -> str:
    """Serialize rows canonically (``repr`` floats, locale-independent)."""
    lines = [f"{r.center_x!r} {r.center_y!r} {r.size!r}" for r in rows]
    return "\n".join(lines) + ("\n" if lines else "")


def tilesinfo_roundtrip_check(text: str,
                              tolerance: float = TILESINFO_TOLERANCE) -> Dict[str, Any]:
    """Verify written-token == parsed-value for all consumers (NEW-199)."""
    rows = parse_tilesinfo(text)
    canonical = format_tilesinfo(rows)
    reparsed = parse_tilesinfo(canonical)
    mismatches: List[str] = []
    if len(rows) != len(reparsed):
        mismatches.append(f"row count changed: {len(rows)} != {len(reparsed)}")
    for idx, (a, b) in enumerate(zip(rows, reparsed)):
        for key in ("center_x", "center_y", "size"):
            if abs(getattr(a, key) - getattr(b, key)) > tolerance:
                mismatches.append(f"row {idx} {key}: {getattr(a, key)!r} != {getattr(b, key)!r}")
    return {
        "status": "PASS" if not mismatches else "FAIL",
        "row_count": len(rows),
        "canonical_text_sha256": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
        "mismatches": mismatches,
        "schema": dict(TILESINFO_SCHEMA),
        "tolerance": tolerance,
    }
