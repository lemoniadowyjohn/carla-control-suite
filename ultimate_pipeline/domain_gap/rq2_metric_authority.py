#!/usr/bin/env python3
"""RQ2 metric authority — production RQ2 entrypoint.

Resolves the pinned auto/manual pair via the C13 registry (never by mtime or
glob), computes the thesis-contract RQ2 metrics under an explicit scope, and
emits machine-readable results + provenance.

Scopes (never mixed):
  manual_hull: crop auto road network to the manual map's convex-hull
    footprint, then compare. This is the PRIMARY RQ2 scope — it measures the
    structural domain gap for the same region.
  whole_map: compare full auto extraction vs the manual patch with no
    cropping. Context only — dominated by the scope artifact (full OSM
    extraction ~13x14 km vs curated ~4.4x2.9 km patch). Construction layers
    (traffic lights, buildings-as-modeled) are reported here, not in hull.

Valid RQ2 metrics (research/thesis_rq_contract.yaml, RQ2.valid_metrics):
  lane_width_gap, curvature_gap, curvature_wasserstein_gap, road_count_ratio,
  road_length_ratio, junction_ratio, building_density_gap, frechet_distance,
  connectivity_gap, semantic_object_gap

--validate-only: recompute both scopes against the CURRENT pinned pair and
assert every value matches the already-frozen RQ2 citations
(FROZEN_CITATIONS, sourced from docs/research/THESIS_TO_CURRENT_PROGRESS.md
2026-09-17 re-verification sections) plus the committed RQ2_RESULTS.json
metrics. Writes a validation report (never RQ2_RESULTS.json /
RQ2_METRIC_PROVENANCE.json) and exits 0 on PASS, 1 on any mismatch — the
merge gate for the rq2-authority branch.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

WORKTREE = Path(__file__).resolve().parents[2]
if str(WORKTREE) not in sys.path:
    sys.path.insert(0, str(WORKTREE))

from ultimate_pipeline.carla_tools.map_registry import verify_pinned_map

VALID_METRICS = [
    "lane_width_gap",
    "curvature_gap",
    "curvature_wasserstein_gap",
    "road_count_ratio",
    "road_length_ratio",
    "junction_ratio",
    "building_density_gap",
    "frechet_distance",
    "connectivity_gap",
    "semantic_object_gap",
]

SCOPES = ("manual_hull", "whole_map")

# ---------------------------------------------------------------------------
# Frozen RQ2 citations — the merge gate for this branch.
# Sources (already-frozen, must not be edited to make validation pass):
#   - docs/research/THESIS_TO_CURRENT_PROGRESS.md, "2026-09-17 update — RQ2
#     local hull-footprint number re-verified against the current pin"
#   - docs/research/THESIS_TO_CURRENT_PROGRESS.md, "2026-09-17 update — RQ2
#     local Frechet-distance number (thesis item #14) re-verified"
#   - docs/research/THESIS_TO_CURRENT_PROGRESS.md, 2026-09-15 whole-map note
#   - RQ2_RESULTS.json (frozen at commit 56a82a35) — compared with exact/atol
#     semantics by build_validation_report, not via this table.
# Citations are stored at their published precision; "round" checks compare
# round(actual, ndp) == expected so the gate is precision-faithful to the doc.
# ---------------------------------------------------------------------------
FROZEN_CITATIONS = [
    {"name": "pair.auto.pin_filename", "source": "THESIS_TO_CURRENT_PROGRESS.md 2026-09-17 (pin filename)", "path": ("pair", "auto", "path"), "expected": "ingolstadt_perception_map_of_record_20260916_232831.xodr", "kind": "suffix"},
    {"name": "pair.auto.sha256_prefix", "source": "THESIS_TO_CURRENT_PROGRESS.md 2026-09-17 (sha256 370abbbbb3...)", "path": ("pair", "auto", "sha256"), "expected": "370abbbbb3", "kind": "prefix"},
    {"name": "hull.road_length_ratio", "source": "THESIS_TO_CURRENT_PROGRESS.md 2026-09-17 hull re-verification", "path": ("scopes", "manual_hull", "metrics", "road_length_ratio"), "expected": 2.683, "kind": "round", "ndp": 3},
    {"name": "hull.junction_ratio", "source": "THESIS_TO_CURRENT_PROGRESS.md 2026-09-17 hull re-verification", "path": ("scopes", "manual_hull", "metrics", "junction_ratio"), "expected": 3.782, "kind": "round", "ndp": 3},
    {"name": "hull.road_count_ratio", "source": "THESIS_TO_CURRENT_PROGRESS.md 2026-09-17 hull re-verification", "path": ("scopes", "manual_hull", "metrics", "road_count_ratio"), "expected": 3.561, "kind": "round", "ndp": 3},
    {"name": "hull.curvature_gap", "source": "THESIS_TO_CURRENT_PROGRESS.md 2026-09-17 hull re-verification", "path": ("scopes", "manual_hull", "metrics", "curvature_gap"), "expected": 0.2206, "kind": "round", "ndp": 4},
    {"name": "hull.lane_width_gap", "source": "THESIS_TO_CURRENT_PROGRESS.md 2026-09-17 hull re-verification", "path": ("scopes", "manual_hull", "metrics", "lane_width_gap"), "expected": 0.0597, "kind": "round", "ndp": 4},
    {"name": "hull.building_density_gap", "source": "THESIS_TO_CURRENT_PROGRESS.md 2026-09-17 hull re-verification", "path": ("scopes", "manual_hull", "metrics", "building_density_gap"), "expected": 0.2308, "kind": "round", "ndp": 4},
    {"name": "frechet.mean_m", "source": "THESIS_TO_CURRENT_PROGRESS.md 2026-09-17 Frechet re-verification", "path": ("scopes", "manual_hull", "metrics", "frechet_distance", "mean_m"), "expected": 58.18, "kind": "round", "ndp": 2},
    {"name": "frechet.median_m", "source": "THESIS_TO_CURRENT_PROGRESS.md 2026-09-17 Frechet re-verification", "path": ("scopes", "manual_hull", "metrics", "frechet_distance", "median_m"), "expected": 36.13, "kind": "round", "ndp": 2},
    {"name": "frechet.p90_m", "source": "THESIS_TO_CURRENT_PROGRESS.md 2026-09-17 Frechet re-verification", "path": ("scopes", "manual_hull", "metrics", "frechet_distance", "p90_m"), "expected": 140.48, "kind": "round", "ndp": 2},
    {"name": "frechet.pairs", "source": "THESIS_TO_CURRENT_PROGRESS.md 2026-09-17 Frechet re-verification (894 matched pairs)", "path": ("scopes", "manual_hull", "metrics", "frechet_distance", "pairs"), "expected": 894, "kind": "exact"},
    {"name": "hull.support.cropped_auto_roads", "source": "THESIS_TO_CURRENT_PROGRESS.md 2026-09-17 (3,536 / 993 cross-check)", "path": ("scopes", "manual_hull", "support", "cropped_auto_roads"), "expected": 3536, "kind": "exact"},
    {"name": "hull.support.manual_roads", "source": "THESIS_TO_CURRENT_PROGRESS.md 2026-09-17 (3,536 / 993 cross-check)", "path": ("scopes", "manual_hull", "support", "manual_roads"), "expected": 993, "kind": "exact"},
    {"name": "whole_map.road_length_ratio", "source": "THESIS_TO_CURRENT_PROGRESS.md 2026-09-15 note (~27.8x uncropped)", "path": ("scopes", "whole_map", "metrics", "road_length_ratio"), "expected": 27.8, "kind": "round", "ndp": 1},
    {"name": "whole_map.support.auto_length_m", "source": "THESIS_TO_CURRENT_PROGRESS.md 2026-09-15 note (1,489,146 m auto)", "path": ("scopes", "whole_map", "support", "auto_length_m"), "expected": 1489146, "kind": "round", "ndp": 0},
    {"name": "whole_map.support.manual_length_m", "source": "THESIS_TO_CURRENT_PROGRESS.md 2026-09-15 note (53,525 m manual)", "path": ("scopes", "whole_map", "support", "manual_length_m"), "expected": 53525, "kind": "round", "ndp": 0},
]

FROZEN_RESULTS_FILENAME = "RQ2_RESULTS.json"
FROZEN_RESULTS_ATOL = 1e-9


def _sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for c in iter(lambda: f.read(4 * 1024 * 1024), b""):
            h.update(c)
    return h.hexdigest()


def resolve_pair() -> Dict[str, Any]:
    auto = verify_pinned_map("auto_map_of_record")
    manual = verify_pinned_map("manual_grid0828")
    assert auto.get("verification_status") == "VERIFIED", auto
    assert manual.get("verification_status") == "VERIFIED", manual
    return {"auto": auto, "manual": manual}


def compute_manual_hull(auto_path: str, manual_path: str) -> Dict[str, Any]:
    from ultimate_pipeline.domain_gap.local_registration import (
        compute_local_registration,
        local_structural_summary,
    )
    from ultimate_pipeline.domain_gap.frechet_gap import compute_frechet_gap

    reg = compute_local_registration(auto_path, manual_path, footprint="hull")
    summary = local_structural_summary(reg)
    frechet = compute_frechet_gap(auto_path, manual_path, footprint="hull")
    m, ca = reg.manual_stats, reg.cropped_auto_stats
    return {
        "scope": "manual_hull",
        "footprint": "hull",
        "metrics": {
            "lane_width_gap": summary["road_network_structural"]["lane_width_gap"],
            "curvature_gap": summary["road_network_structural"]["curvature_gap"],
            "curvature_wasserstein_gap": summary["road_network_structural"]["curvature_wasserstein_gap"],
            "road_count_ratio": summary["road_network_structural"]["road_count_ratio_auto_over_manual"],
            "road_length_ratio": summary["road_network_structural"]["road_length_ratio_auto_over_manual"],
            "junction_ratio": summary["road_network_structural"]["junction_ratio_auto_over_manual"],
            "building_density_gap": summary["building_density_comparison"]["building_density_gap"],
            "frechet_distance": {
                "mean_m": frechet.get("mean_m"),
                "median_m": frechet.get("median_m"),
                "p90_m": frechet.get("p90_m"),
                "pairs": frechet.get("matched_pair_count"),
            },
        },
        "support": {
            "manual_roads": m.num_roads,
            "cropped_auto_roads": ca.num_roads,
            "full_auto_roads": reg.full_auto_road_count,
            "manual_length_m": round(m.total_road_length, 1),
            "cropped_auto_length_m": round(ca.total_road_length, 1),
            "manual_junctions": m.num_junctions,
            "cropped_auto_junctions": ca.num_junctions,
        },
        "implementations": {
            "ratios_gaps": "ultimate_pipeline.domain_gap.local_registration.compute_local_registration+local_structural_summary (footprint=hull)",
            "frechet_distance": "ultimate_pipeline.domain_gap.frechet_gap.compute_frechet_gap (footprint=hull, spacing_m=5.0)",
        },
    }


def compute_whole_map(auto_path: str, manual_path: str) -> Dict[str, Any]:
    from pathlib import Path as _P
    from ultimate_pipeline.tools.xodr_structural_summary import summarize_xodr
    from ultimate_pipeline.domain_gap.connectivity_gap import ConnectivityGap
    from ultimate_pipeline.domain_gap.semantic_gap import SemanticGap

    a = summarize_xodr(_P(auto_path))
    m = summarize_xodr(_P(manual_path))
    conn = ConnectivityGap.compute(manual_path, auto_path)
    sem = SemanticGap.compute(manual_path, auto_path)
    return {
        "scope": "whole_map",
        "footprint": "none (full files, context only)",
        "metrics": {
            "road_count_ratio": round(a["road_count"] / m["road_count"], 3) if m["road_count"] else None,
            "road_length_ratio": round(a["total_road_length_m"] / m["total_road_length_m"], 3) if m["total_road_length_m"] else None,
            "junction_ratio": round(a["junction_count"] / m["junction_count"], 3) if m["junction_count"] else None,
            "building_density_gap": None,
            "connectivity_gap": conn,
            "semantic_object_gap": sem,
        },
        "support": {
            "auto_roads": a["road_count"],
            "manual_roads": m["road_count"],
            "auto_length_m": round(a["total_road_length_m"], 1),
            "manual_length_m": round(m["total_road_length_m"], 1),
            "auto_junctions": a["junction_count"],
            "manual_junctions": m["junction_count"],
        },
        "implementations": {
            "ratios": "ultimate_pipeline.tools.xodr_structural_summary.summarize_xodr (full files)",
            "connectivity_gap": "ultimate_pipeline.domain_gap.connectivity_gap.ConnectivityGap.compute",
            "semantic_object_gap": "ultimate_pipeline.domain_gap.semantic_gap.SemanticGap.compute",
        },
    }


def _dig(doc: Dict[str, Any], path: tuple) -> Any:
    node: Any = doc
    for key in path:
        if not isinstance(node, dict) or key not in node:
            return None
        node = node[key]
    return node


def _check_citation(citation: Dict[str, Any], doc: Dict[str, Any]) -> Dict[str, Any]:
    actual = _dig(doc, citation["path"])
    kind = citation["kind"]
    expected = citation["expected"]
    if kind == "exact":
        ok = actual == expected
        criterion = f"actual == {expected!r}"
    elif kind == "round":
        ok = isinstance(actual, (int, float)) and not isinstance(actual, bool) and round(float(actual), citation["ndp"]) == expected
        criterion = f"round(actual, {citation['ndp']}) == {expected!r}"
    elif kind == "prefix":
        ok = isinstance(actual, str) and actual.startswith(expected)
        criterion = f"actual.startswith({expected!r})"
    elif kind == "suffix":
        ok = isinstance(actual, str) and actual.endswith(expected)
        criterion = f"actual.endswith({expected!r})"
    else:  # unknown criterion must fail closed
        ok = False
        criterion = f"unknown check kind {kind!r}"
    return {
        "name": citation["name"],
        "source": citation["source"],
        "criterion": criterion,
        "expected": expected,
        "actual": actual,
        "status": "PASS" if ok else "FAIL",
    }


def _compare_frozen(expected: Any, actual: Any, path: str, failures: list, atol: float) -> None:
    if isinstance(expected, dict):
        if not isinstance(actual, dict):
            failures.append(f"{path}: expected mapping, got {type(actual).__name__}")
            return
        for key in sorted(expected):
            sub = f"{path}.{key}"
            if key not in actual:
                failures.append(f"{sub}: missing in recomputation")
            else:
                _compare_frozen(expected[key], actual[key], sub, failures, atol)
        for key in sorted(set(actual) - set(expected)):
            failures.append(f"{path}.{key}: unexpected key absent from frozen results")
    elif isinstance(expected, list):
        if not isinstance(actual, list) or len(actual) != len(expected):
            failures.append(f"{path}: list shape mismatch (frozen len "
                            f"{len(expected) if isinstance(expected, list) else 'n/a'}, "
                            f"actual len {len(actual) if isinstance(actual, list) else 'n/a'})")
            return
        for i, (e, a) in enumerate(zip(expected, actual)):
            _compare_frozen(e, a, f"{path}[{i}]", failures, atol)
    elif isinstance(expected, bool) or isinstance(actual, bool):
        if expected is not actual:
            failures.append(f"{path}: frozen {expected!r} != actual {actual!r}")
    elif isinstance(expected, (int, float)) and isinstance(actual, (int, float)):
        if abs(float(expected) - float(actual)) > atol:
            failures.append(f"{path}: frozen {expected!r} != actual {actual!r} (atol={atol})")
    elif expected != actual:
        failures.append(f"{path}: frozen {expected!r} != actual {actual!r}")


def _load_frozen_results() -> Dict[str, Any]:
    for candidate in (WORKTREE / FROZEN_RESULTS_FILENAME, Path.cwd() / FROZEN_RESULTS_FILENAME):
        if candidate.is_file():
            return json.loads(candidate.read_text())
    raise SystemExit(
        f"validate-only requires the frozen {FROZEN_RESULTS_FILENAME} "
        f"(expected at {WORKTREE / FROZEN_RESULTS_FILENAME})"
    )


def build_validation_report(doc: Dict[str, Any], frozen: Dict[str, Any]) -> Dict[str, Any]:
    checks = [_check_citation(c, doc) for c in FROZEN_CITATIONS]

    failures: list = []
    _compare_frozen(frozen.get("pair"), doc.get("pair"), "frozen.pair", failures, FROZEN_RESULTS_ATOL)
    frozen_scopes = frozen.get("scopes", {})
    doc_scopes = doc.get("scopes", {})
    for scope in sorted(set(frozen_scopes) | set(doc_scopes)):
        if scope not in doc_scopes:
            failures.append(f"frozen.scopes.{scope}: missing in recomputation")
            continue
        if scope not in frozen_scopes:
            failures.append(f"scopes.{scope}: present in recomputation but absent from frozen results")
            continue
        for subtree in ("metrics", "support"):
            _compare_frozen(
                frozen["scopes"][scope].get(subtree),
                doc["scopes"][scope].get(subtree),
                f"frozen.scopes.{scope}.{subtree}",
                failures,
                FROZEN_RESULTS_ATOL,
            )
    checks.append({
        "name": "frozen_results.metrics_and_pair",
        "source": f"{FROZEN_RESULTS_FILENAME} (committed at 56a82a35, value subtrees only: pair/metrics/support)",
        "criterion": f"recomputed values equal frozen values within atol={FROZEN_RESULTS_ATOL}",
        "expected": "0 mismatches",
        "actual": failures if failures else "0 mismatches",
        "status": "PASS" if not failures else "FAIL",
    })

    passed = sum(1 for c in checks if c["status"] == "PASS")
    failed = len(checks) - passed
    return {
        "schema": "rq2_validate_only/v1",
        "generated_at_utc": doc.get("generated_at_utc"),
        "mode": "validate-only",
        "pair": doc.get("pair"),
        "checks": checks,
        "summary": {"total": len(checks), "passed": passed, "failed": failed},
        "verdict": "PASS" if failed == 0 else "FAIL",
        "gate": "merge rq2-authority into production only if verdict == PASS",
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--scope", choices=list(SCOPES) + ["both"], default="both")
    ap.add_argument("--out", type=Path, default=Path("RQ2_RESULTS.json"))
    ap.add_argument("--provenance-out", type=Path, default=Path("RQ2_METRIC_PROVENANCE.json"))
    ap.add_argument(
        "--validate-only",
        action="store_true",
        help="recompute both scopes against the current pinned pair, assert every "
             "frozen RQ2 citation (FROZEN_CITATIONS + committed RQ2_RESULTS.json "
             "value subtrees), write only --validation-out, exit 0 on PASS / 1 on FAIL. "
             "Never writes RQ2_RESULTS.json or RQ2_METRIC_PROVENANCE.json.",
    )
    ap.add_argument("--validation-out", type=Path, default=Path("RQ2_VALIDATE_ONLY.json"))
    args = ap.parse_args()

    pair = resolve_pair()
    auto_p = pair["auto"]["resolved_path"]
    manual_p = pair["manual"]["resolved_path"]
    out: Dict[str, Any] = {
        "schema": "rq2_results/v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "pair": {
            "auto": {"path": pair["auto"]["declared_path"], "sha256": pair["auto"]["sha256_actual"], "bytes": pair["auto"]["bytes_actual"]},
            "manual": {"path": pair["manual"]["declared_path"], "sha256": pair["manual"]["sha256_actual"], "bytes": pair["manual"]["bytes_actual"]},
        },
        "valid_metrics": VALID_METRICS,
        "scopes": {},
    }

    if args.validate_only:
        # Validation always covers both scopes: every frozen citation must be
        # exercised, regardless of --scope.
        out["scopes"]["manual_hull"] = compute_manual_hull(auto_p, manual_p)
        out["scopes"]["whole_map"] = compute_whole_map(auto_p, manual_p)
        report = build_validation_report(out, _load_frozen_results())
        args.validation_out.write_text(json.dumps(report, indent=2, sort_keys=True, default=str) + "\n")
        print(json.dumps({
            "verdict": report["verdict"],
            "summary": report["summary"],
            "failed_checks": [c["name"] for c in report["checks"] if c["status"] != "PASS"],
            "out": str(args.validation_out),
        }, indent=2))
        return 0 if report["verdict"] == "PASS" else 1

    if args.scope in ("manual_hull", "both"):
        out["scopes"]["manual_hull"] = compute_manual_hull(auto_p, manual_p)
    if args.scope in ("whole_map", "both"):
        out["scopes"]["whole_map"] = compute_whole_map(auto_p, manual_p)

    args.out.write_text(json.dumps(out, indent=2, sort_keys=True, default=str) + "\n")
    prov = {
        "schema": "rq2_metric_provenance/v1",
        "generated_at_utc": out["generated_at_utc"],
        "pair_sha256": {"auto": out["pair"]["auto"]["sha256"], "manual": out["pair"]["manual"]["sha256"]},
        "metric_implementation": {
            "manual_hull": (out["scopes"].get("manual_hull", {}).get("implementations", {})),
            "whole_map": (out["scopes"].get("whole_map", {}).get("implementations", {})),
        },
        "scope_policy": "manual_hull and whole_map metrics are computed independently and never averaged or mixed.",
        "contract": "research/thesis_rq_contract.yaml RQ2.valid_metrics",
    }
    args.provenance_out.write_text(json.dumps(prov, indent=2, sort_keys=True, default=str) + "\n")
    print(json.dumps({"scopes": list(out["scopes"].keys()), "out": str(args.out)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
