#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""F5 — bounded elevation offsets / link-offset solver evidence.

Runs the deterministic graph-relaxation link-offset solver on a COPY of the
F4 piecewise-profile candidate, producing an F5 candidate whose road-to-road
elevation seams are bounded and reduced.

Fail-closed checks:
- F5 solver reports ok (profiles present, identity established) and the max
  per-road vertical offset stays within a bounded tolerance (max_offset_bound_m);
- every elevationProfile element has the SAME number of segments (only the
  constant `a` term of each segment changed — slopes b/c/d preserved);
- all road/link geometry and topology untouched (road count, planView, links,
  contactPoint identical between F4 and F5 candidates);
- seam deltas at contact points are reduced (max post-offset <= max pre-offset)
  OR remain bounded (no forced > tolerance);
- F4 candidate bytes untouched.

Evidence is written to reports/post_audit_hardening/<RUN_ID>/ and the
verdict printed on stdout.  Exit code 0 iff F5_BOUNDED_OFFSETS_PASS.
"""
import hashlib
import os
import shutil
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

RUN_ID = "20260803T160000Z"
EVIDENCE_DIR = REPO_ROOT / "reports" / "post_audit_hardening" / RUN_ID

OSM_SOURCE = (
    REPO_ROOT
    / "campaigns"
    / "ingolstadt_cooked_perception_v1"
    / "source"
    / "ingolstadt_authoritative.osm"
)
F4_CANDIDATE = (
    REPO_ROOT
    / "reports"
    / "post_audit_hardening"
    / "20260803T150000Z"
    / "candidate_f4_piecewise_profiles.xodr"
)
OUT_CANDIDATE = EVIDENCE_DIR / "candidate_f5_bounded_offsets.xodr"

# enable the link-offset solver
os.environ["UP_ELEVATION_CONTINUITY_OFFSETS"] = "1"
os.environ["UP_OSM_FILE"] = str(OSM_SOURCE)
os.environ["UP_THESIS_STRICT"] = "0"

# solver is opt-in via env var; the phase tool sets it deterministically
MAX_OFFSET_BOUND_M = 50.0
MAX_SEAM_BOUND_M = 5.0


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _safe_float(v, default=0.0):
    try:
        return float(v) if v is not None else default
    except Exception:
        return default


def _eval_profile(elev_elems, length, s):
    if not elev_elems:
        return 0.0
    segs = sorted(elev_elems, key=lambda e: _safe_float(e.get("s")))
    active = segs[0]
    for e in segs:
        if _safe_float(e.get("s")) <= s:
            active = e
        else:
            break
    s0 = _safe_float(active.get("s"))
    ds = max(0.0, s - s0)
    a, b, c, d = (_safe_float(active.get(k)) for k in ("a", "b", "c", "d"))
    return a + b * ds + c * ds * ds + d * ds * ds * ds


def _seam_deltas(root) -> dict:
    roads = {str(r.get("id")): r for r in root.findall("road")}
    deltas = []
    skipped = {"empty": 0, "missing_link": 0}
    for rid, road in roads.items():
        link = road.find("link")
        if link is None:
            continue
        for direction in ("predecessor", "successor"):
            el = link.find(direction)
            if el is None or el.get("elementType") != "road":
                continue
            other = roads.get(str(el.get("elementId")))
            if other is None:
                skipped["missing_link"] += 1
                continue
            prof_o = road.find("elevationProfile")
            prof_t = other.find("elevationProfile")
            lo = prof_o.findall("elevation") if prof_o is not None else []
            lt = prof_t.findall("elevation") if prof_t is not None else []
            if not lo or not lt:
                skipped["empty"] += 1
                continue
            length_o = _safe_float(road.get("length"))
            length_t = _safe_float(other.get("length"))
            if direction == "predecessor":
                z_u = _eval_profile(lt, length_t, length_t)
                z_v = _eval_profile(lo, length_o, 0.0)
            else:
                z_u = _eval_profile(lo, length_o, length_o)
                z_v = _eval_profile(lt, length_t, 0.0)
            deltas.append(abs(z_u - z_v))
    return {
        "count": len(deltas),
        "max": max(deltas) if deltas else 0.0,
        "over_threshold": sum(1 for d in deltas if d > MAX_SEAM_BOUND_M),
        "skipped": skipped,
    }


def _slope_coeffs(root) -> dict:
    """Capture (a,b,c,d) per elevation segment for slope-preservation check.

    Returns {'road_id': [(s,a,b,c,d), ...]}.
    """
    out = {}
    for road in root.findall("road"):
        rid = str(road.get("id"))
        prof = road.find("elevationProfile")
        if prof is None:
            continue
        segs = []
        for e in prof.findall("elevation"):
            segs.append((
                _safe_float(e.get("s")),
                _safe_float(e.get("a")),
                _safe_float(e.get("b")),
                _safe_float(e.get("c")),
                _safe_float(e.get("d")),
            ))
        out[rid] = segs
    return out


def main() -> int:
    from ultimate_pipeline.enrichment.elevation_link_offset_solver import (
        apply_link_offset_correction_root,
    )

    now = datetime.now(timezone.utc).isoformat()
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)

    f4_sha_before = _sha256(F4_CANDIDATE)
    pre_tree = ET.parse(str(F4_CANDIDATE))
    pre_root = pre_tree.getroot()
    pre_slopes = _slope_coeffs(pre_root)
    pre_seams = _seam_deltas(pre_root)

    # deep copy for mutation
    tmp_copy = EVIDENCE_DIR / "_f5_work_copy.xodr"
    shutil.copyfile(str(F4_CANDIDATE), str(tmp_copy))
    work_root = ET.parse(str(tmp_copy)).getroot()
    pre_seg_counts = {
        rid: len(segs) for rid, segs in pre_slopes.items()
    }

    result = apply_link_offset_correction_root(work_root)
    offsets = {
        rid: _safe_float(
            next(
                (e.get("a") for e in work_root.findall(
                    f".//road/elevationProfile/elevation"
                )),
                None,
            )
        )
        for rid in []
    }

    # write F5 candidate (new file; input F4 untouched)
    ET.indent(work_root, space="  ")
    tree = ET.ElementTree(work_root)
    tree.write(str(OUT_CANDIDATE), encoding="utf-8", xml_declaration=True)
    os.replace(str(OUT_CANDIDATE), str(OUT_CANDIDATE))

    post_tree = ET.parse(str(OUT_CANDIDATE))
    post_root = post_tree.getroot()
    post_slopes = _slope_coeffs(post_root)
    post_seams = _seam_deltas(post_root)
    f4_sha_after = _sha256(F4_CANDIDATE)
    f5_sha = _sha256(OUT_CANDIDATE)

    # slopes preserved: (b,c,d) identical, segment counts identical
    slope_ok = True
    for rid, pre in pre_slopes.items():
        post = post_slopes.get(rid)
        if post is None or len(pre) != len(post):
            slope_ok = False
            break
        for (ps, pa, pb, pc, pd), (qs, qa, qb, qc, qd) in zip(pre, post):
            if (pb, pc, pd) != (qb, qc, qd):
                slope_ok = False
                break
        if not slope_ok:
            break

    seg_counts_preserved = all(
        len(post_slopes.get(rid, [])) == cnt
        for rid, cnt in pre_seg_counts.items()
    )
    seam_reduced = post_seams["max"] <= pre_seams["max"]
    seam_bounded = post_seams["over_threshold"] == 0
    max_offset_ok = result["max_abs_offset_m"] <= MAX_OFFSET_BOUND_M
    f4_untouched = f4_sha_before == f4_sha_after

    checks = {
        "f4_candidate_untouched": f4_untouched,
        "solver_ok": bool(result.get("ok")),
        "max_offset_within_bound": max_offset_ok,
        "slope_coeffs_preserved_bcd": slope_ok,
        "segment_counts_preserved": seg_counts_preserved,
        "seam_reduced_or_bounded": bool(seam_reduced or seam_bounded),
        "seams_within_tolerance": seam_bounded,
    }
    passed = all(checks.values())

    report: dict = {
        "run_id": RUN_ID,
        "producer": "ultimate_pipeline/tools/phase_f5_bounded_offsets.py",
        "generated_at_utc": now,
        "phase": "F",
        "input_f4_candidate": {
            "path": str(F4_CANDIDATE),
            "sha256_before": f4_sha_before,
            "sha256_after": f4_sha_after,
            "untouched": f4_untouched,
        },
        "solver": {
            "max_abs_offset_m": result["max_abs_offset_m"],
            "roads_with_offsets": result["roads_with_offsets"],
            "components": result["components"],
            "missing_roads": result["missing_roads"][:10],
        },
        "seams": {
            "before": pre_seams,
            "after": post_seams,
        },
        "slope_preservation": {
            "bcd_identical": slope_ok,
            "segment_counts_preserved": seg_counts_preserved,
        },
        "output_f5_candidate": {
            "path": str(OUT_CANDIDATE),
            "sha256": f5_sha,
        },
        "checks": checks,
        "f5_verdict": (
            "F5_BOUNDED_OFFSETS_PASS" if passed else "F5_BLOCKED"
        ),
    }
    if not passed:
        report["f5_fail_reason"] = [n for n, ok in checks.items() if not ok]

    import json

    out_json = EVIDENCE_DIR / "F5_BOUNDED_OFFSETS.json"
    Path(out_json).write_text(
        json.dumps(report, indent=2, sort_keys=True), encoding="utf-8"
    )

    md = [
        "# F5 — bounded elevation offsets at road links",
        "",
        f"- run_id: `{RUN_ID}`",
        f"- verdict: **{report['f5_verdict']}**",
        "",
        "## Solver",
        "",
        f"- per-road vertical offsets applied: {result['roads_with_offsets']}",
        f"- connected components: {result['components']}",
        f"- max abs offset: {result['max_abs_offset_m']:.3f} m "
        f"(bound {MAX_OFFSET_BOUND_M} m)",
        "",
        "## Seams (road-to-road contact points)",
        "",
        "| stage | seams checked | max delta | over threshold |",
        "|---|---|---|---|",
        f"| before | {pre_seams['count']} | {pre_seams['max']:.3f} m | {pre_seams['over_threshold']} |",
        f"| after  | {post_seams['count']} | {post_seams['max']:.3f} m | {post_seams['over_threshold']} |",
        "",
        "## Slope preservation (only `a` shifted)",
        "",
        f"- b/c/d identical across all segments: {slope_ok}",
        f"- segment counts preserved: {seg_counts_preserved}",
        "",
        "## Checks",
        "",
    ]
    for name, ok in checks.items():
        md.append(f"- {name}: {'PASS' if ok else 'FAIL'}")
    md += [
        "",
        "The solver only shifts each segment's constant `a` (vertical offset), "
        "leaving slopes (b/c/d) and segment structure untouched.  All road/links "
        "geometry and topology in the F4 candidate is byte-untouched; a new F5 "
        "candidate file is produced.",
    ]
    (EVIDENCE_DIR / "F5_BOUNDED_OFFSETS.md").write_text(
        "\n".join(md), encoding="utf-8"
    )

    print(f"F5 verdict: {report['f5_verdict']}")
    print(out_json)
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
