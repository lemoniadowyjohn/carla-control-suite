#!/usr/bin/env python3
"""Protocol loading, validation, and snapshotting for thesis reproducibility.

This module provides functions to:
- Load a thesis protocol YAML file
- Validate that all required fields are present and not placeholders
- Write a snapshot of the protocol + provenance to an output directory
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

# Use safe YAML loader; fall back to basic loader if pyyaml not installed
try:
    import yaml
    _HAS_YAML = True
except ImportError:
    yaml = None  # type: ignore[assignment]
    _HAS_YAML = False


class ProtocolValidationError(Exception):
    """Raised when protocol validation fails."""
    pass


def load_protocol(path: str) -> Dict[str, Any]:
    """Load a protocol YAML file and return as dict.

    Args:
        path: Path to the protocol YAML file.

    Returns:
        Parsed protocol as a dictionary.

    Raises:
        FileNotFoundError: If the file does not exist.
        ProtocolValidationError: If YAML parsing fails or pyyaml is not installed.
    """
    p = Path(path).expanduser().resolve()
    if not p.is_file():
        raise FileNotFoundError(f"Protocol file not found: {p}")

    if not _HAS_YAML:
        raise ProtocolValidationError(
            "pyyaml is required to load protocol files. Install with: pip install pyyaml"
        )

    with p.open("r", encoding="utf-8") as f:
        try:
            data = yaml.safe_load(f)
        except yaml.YAMLError as e:
            raise ProtocolValidationError(f"Failed to parse protocol YAML: {e}") from e

    if not isinstance(data, dict):
        raise ProtocolValidationError(
            f"Protocol must be a YAML mapping/dict, got {type(data).__name__}"
        )

    return data


# Placeholder patterns that indicate the protocol hasn't been configured
PLACEHOLDER_PATTERNS = [
    "placeholder",
    "PLACEHOLDER",
    "TODO",
    "FIXME",
    "TBD",
]

CANONICAL_GEO_BOUNDS = {
    "lat_min": 48.74935649548228,
    "lon_min": 11.422268084715878,
    "lat_max": 48.77444431571603,
    "lon_max": 11.47882091528412,
}

REQUIRED_MANUAL_MAPS = {"Grid0821", "Grid0828"}
FPS_DELTA_TOLERANCE = 1e-6
EXPECTED_SIMULATION_FPS = 20.0
EXPECTED_FIXED_DELTA_SECONDS = 0.05
EXPECTED_FPS_DELTA_PRODUCT = 1.0
GEO_BOUNDS_TOLERANCE = 1e-9
MIN_GENERATED_VARIANTS = 5


def _is_placeholder(value: Any) -> bool:
    """Check if a value looks like a placeholder."""
    if not isinstance(value, str):
        return False
    v_lower = value.lower()
    for pattern in PLACEHOLDER_PATTERNS:
        if pattern.lower() in v_lower:
            return True
    return False


def _coerce_float(value: Any) -> Optional[float]:
    try:
        return float(value)
    except Exception:
        return None


def validate_protocol(protocol: Dict[str, Any]) -> None:
    """Validate that a protocol dict has all required fields and no placeholders.

    Required fields:
    - seed (must be present and valid)
    - weather.preset (must be present and not placeholder)
    - routes (must have at least one route with valid route_id)
    - active_route (must exist in routes)
    - simulation.fps == 20 and simulation.fixed_delta_seconds == 0.05
    - simulation.fps * simulation.fixed_delta_seconds == 1.0
    - geo_bounds must match authoritative Ingolstadt bounds
    - maps.manual must include Grid0821 and Grid0828
    - maps.generated.n_variants must be >= 5

    Args:
        protocol: The protocol dictionary to validate.

    Raises:
        ProtocolValidationError: If validation fails with clear error message.
    """
    errors: List[str] = []

    # Check seed
    if "seed" not in protocol:
        errors.append("Missing required field: 'seed'")
    elif protocol["seed"] is None:
        errors.append("Field 'seed' is None; must be a valid integer")

    # Check weather
    weather = protocol.get("weather")
    if not weather:
        errors.append("Missing required section: 'weather'")
    elif not isinstance(weather, dict):
        errors.append("Field 'weather' must be a mapping/dict")
    else:
        preset = weather.get("preset")
        if not preset:
            errors.append("Missing required field: 'weather.preset'")
        elif _is_placeholder(preset):
            errors.append(f"Field 'weather.preset' contains placeholder value: '{preset}'")

    # Check routes - support both flat and nested structures
    routes = protocol.get("routes")
    if not routes:
        errors.append("Missing required section: 'routes'")
    elif not isinstance(routes, dict):
        errors.append("Field 'routes' must be a mapping/dict")
    else:
        # Check for flat structure (routes.route_id)
        if "route_id" in routes:
            route_id = routes.get("route_id")
            if _is_placeholder(route_id):
                errors.append(f"Field 'routes.route_id' contains placeholder value: '{route_id}'")
        else:
            # Check for nested structure (routes.primary.route_id, etc.)
            found_valid_route = False
            for route_name, route_def in routes.items():
                if isinstance(route_def, dict) and "route_id" in route_def:
                    route_id = route_def.get("route_id")
                    if route_id and not _is_placeholder(route_id):
                        found_valid_route = True
                        break
                    elif _is_placeholder(route_id):
                        errors.append(f"Field 'routes.{route_name}.route_id' contains placeholder value: '{route_id}'")

            if not found_valid_route and not any("route_id" in str(e) for e in errors):
                errors.append("No valid route_id found in 'routes' section")

    active_route = protocol.get("active_route")
    if not active_route:
        errors.append("Missing required field: 'active_route'")
    elif _is_placeholder(active_route):
        errors.append(f"Field 'active_route' contains placeholder value: '{active_route}'")
    elif isinstance(routes, dict):
        if "route_id" in routes:
            flat_route_id = routes.get("route_id")
            allowed_flat = {"default", "route"}
            if isinstance(flat_route_id, str) and flat_route_id.strip():
                allowed_flat.add(flat_route_id.strip())
            if str(active_route).strip() not in allowed_flat:
                errors.append(
                    "Field 'active_route' must resolve to the only defined flat route "
                    f"(expected one of {sorted(allowed_flat)}; got '{active_route}')"
                )
        elif str(active_route) not in routes:
            errors.append(
                f"Field 'active_route' references missing route '{active_route}' in routes section"
            )

    # Check simulation fixed-delta contract
    simulation = protocol.get("simulation")
    if not simulation:
        errors.append("Missing required section: 'simulation'")
    elif not isinstance(simulation, dict):
        errors.append("Field 'simulation' must be a mapping/dict")
    else:
        fps = _coerce_float(simulation.get("fps"))
        fixed_delta = _coerce_float(simulation.get("fixed_delta_seconds"))
        if fps is None or fps <= 0.0:
            errors.append(
                "Field 'simulation.fps' must be a positive number"
            )
        if fixed_delta is None or fixed_delta <= 0.0:
            errors.append(
                "Field 'simulation.fixed_delta_seconds' must be a positive number"
            )
        if fps is not None and fps > 0.0:
            if abs(float(fps) - EXPECTED_SIMULATION_FPS) > FPS_DELTA_TOLERANCE:
                errors.append(
                    f"Field 'simulation.fps' must be {EXPECTED_SIMULATION_FPS} "
                    f"for thesis protocol (got {fps})"
                )
        if fixed_delta is not None and fixed_delta > 0.0:
            if abs(float(fixed_delta) - EXPECTED_FIXED_DELTA_SECONDS) > FPS_DELTA_TOLERANCE:
                errors.append(
                    f"Field 'simulation.fixed_delta_seconds' must be {EXPECTED_FIXED_DELTA_SECONDS} "
                    f"for thesis protocol (got {fixed_delta})"
                )
        if fps and fps > 0.0 and fixed_delta and fixed_delta > 0.0:
            product = float(fps) * float(fixed_delta)
            if abs(product - EXPECTED_FPS_DELTA_PRODUCT) > FPS_DELTA_TOLERANCE:
                errors.append(
                    "Field 'simulation' invalid: fps * fixed_delta_seconds != 1.0 "
                    f"(fps={fps}, fixed_delta_seconds={fixed_delta}, product={product})"
                )

    # Check authoritative geo bounds
    geo_bounds = protocol.get("geo_bounds")
    if not geo_bounds:
        errors.append("Missing required section: 'geo_bounds'")
    elif not isinstance(geo_bounds, dict):
        errors.append("Field 'geo_bounds' must be a mapping/dict")
    else:
        for key, expected in CANONICAL_GEO_BOUNDS.items():
            value = _coerce_float(geo_bounds.get(key))
            if value is None:
                errors.append(f"Missing or non-numeric field: 'geo_bounds.{key}'")
                continue
            if abs(float(value) - float(expected)) > GEO_BOUNDS_TOLERANCE:
                errors.append(
                    "geo_bounds mismatch: "
                    f"field 'geo_bounds.{key}' must match authoritative value "
                    f"{expected} (got {value})"
                )

    # Check maps.manual and maps.generated contracts
    maps = protocol.get("maps")
    if not maps:
        errors.append("Missing required section: 'maps'")
    elif not isinstance(maps, dict):
        errors.append("Field 'maps' must be a mapping/dict")
    else:
        manual_maps = maps.get("manual")
        manual_names: set[str] = set()
        if isinstance(manual_maps, list):
            for entry in manual_maps:
                if isinstance(entry, dict):
                    name = entry.get("name")
                else:
                    name = entry
                if isinstance(name, str) and name.strip():
                    manual_names.add(name.strip())
        missing_manual = sorted(REQUIRED_MANUAL_MAPS - manual_names)
        if missing_manual:
            errors.append(
                "Field 'maps.manual' must include required manual map(s): "
                + ", ".join(missing_manual)
            )

        generated = maps.get("generated")
        if not isinstance(generated, dict):
            errors.append("Missing required section: 'maps.generated'")
        else:
            n_variants = generated.get("n_variants")
            try:
                n_variants_int = int(n_variants)
            except Exception:
                n_variants_int = -1
            if n_variants_int < MIN_GENERATED_VARIANTS:
                errors.append(
                    f"Field 'maps.generated.n_variants' invalid: n_variants < {MIN_GENERATED_VARIANTS} "
                    f"(got {n_variants})"
                )

    if errors:
        error_msg = "Protocol validation failed:\n" + "\n".join(f"  - {e}" for e in errors)
        raise ProtocolValidationError(error_msg)


def write_protocol_snapshot(
    out_dir: str,
    protocol: Dict[str, Any],
    provenance: Optional[Dict[str, Any]] = None,
) -> None:
    """Write protocol snapshot and provenance to output directory.

    Creates:
    - protocol_snapshot.yaml (or .json if pyyaml not available)
    - provenance.json

    Args:
        out_dir: Output directory path.
        protocol: The protocol dictionary to snapshot.
        provenance: Optional provenance dictionary to write. If None, a minimal
                    provenance with timestamp is created.
    """
    out_path = Path(out_dir).expanduser().resolve()
    out_path.mkdir(parents=True, exist_ok=True)

    # Write protocol snapshot
    if _HAS_YAML:
        protocol_file = out_path / "protocol_snapshot.yaml"
        with protocol_file.open("w", encoding="utf-8") as f:
            yaml.safe_dump(protocol, f, default_flow_style=False, sort_keys=False)
    else:
        # Fallback to JSON if pyyaml not installed
        protocol_file = out_path / "protocol_snapshot.json"
        with protocol_file.open("w", encoding="utf-8") as f:
            json.dump(protocol, f, indent=2)

    # Build provenance
    if provenance is None:
        provenance = {}

    # Add snapshot metadata
    provenance_with_meta = {
        "snapshot_timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "protocol_source": protocol.get("_source_path", "unknown"),
        **provenance,
    }

    # Write provenance
    provenance_file = out_path / "provenance.json"
    with provenance_file.open("w", encoding="utf-8") as f:
        json.dump(provenance_with_meta, f, indent=2)


def get_default_protocol_path() -> Path:
    """Return the default protocol.yaml path in the thesis experiments directory."""
    return Path(__file__).parent / "protocol.yaml"


# CLI for testing/debugging
if __name__ == "__main__":
    import argparse
    import sys

    ap = argparse.ArgumentParser(description="Validate a thesis protocol YAML file")
    ap.add_argument("protocol", nargs="?", help="Path to protocol YAML file")
    ap.add_argument("--validate-only", action="store_true", help="Only validate, don't print")
    args = ap.parse_args()

    protocol_path = args.protocol or str(get_default_protocol_path())

    try:
        proto = load_protocol(protocol_path)
        print(f"Loaded protocol from: {protocol_path}")
        validate_protocol(proto)
        print("Protocol is valid.")
        if not args.validate_only:
            print(json.dumps(proto, indent=2))
        sys.exit(0)
    except (FileNotFoundError, ProtocolValidationError) as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
