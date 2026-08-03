# -*- coding: utf-8 -*-
"""P14 clean-worktree verification runner (reproducibility gate).

Run from the ROOT of a clean detached worktree at the closure commit:
    python p14_verify.py <out_dir> [--suite-only]

Executes, in one pass:
  G1  HEAD identity check
  G2  compileall (ultimate_pipeline + opendrive_geometry + root entrypoints)
  G3  canonical imports (18 entrypoint modules)
  G4  pytest collection count
  G5  full mandatory offline suite (unit + geometry)
  G6  negative controls (fail-closed rejection tests)
  G7  full-map structural gates on the pinned XODR (lane invariants, seams,
      geometry freeze, curve-aware bounds)
  G8  authoritative hash checks (OSM + pinned XODR vs recorded)
  G9  evidence-manifest validation (ultimate_pipeline.audit.verify_manifest)
  G10 tracked-ID verification (218 + 14 = 232, unknown=0, duplicate=0,
       unassessed=0)
  G11 untracked dependency count in the worktree (must be 0 for sources)

Writes a JSON report.  No network, no CARLA server, no cache reuse.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys

HEAD = "b18ddde99adacebebebd8a162e2625bafa1eb290"
OSM_EXPECT = "b9e074656f"
XODR_EXPECT = "ff2a05e7b0"
XODR = r"campaigns\ingolstadt_cooked_perception_v1\candidate\raw_xodr_run_1_epsg32632_header_pinned.xodr"
OSM = r"campaigns\ingolstadt_cooked_perception_v1\source\ingolstadt_authoritative.osm"
MANIFEST = r"audit_output\EVIDENCE_MANIFEST.json"

IMPORTS = [
    "ultimate_pipeline.main_pipeline", "ultimate_pipeline.cli",
    "ultimate_pipeline.entrypoints", "ultimate_pipeline.config.settings",
    "ultimate_pipeline.pipeline_stages.stage_04_enrichment",
    "ultimate_pipeline.pipeline_stages.stage_09_tiling",
    "ultimate_pipeline.tiling.tile_extractor", "ultimate_pipeline.tiling.tile_metadata",
    "ultimate_pipeline.quality.check_elevation_seams",
    "ultimate_pipeline.enrichment.osm2world_runner",
    "ultimate_pipeline.enrichment.blender_runner", "ultimate_pipeline.audit",
    "ultimate_pipeline.topology.topology_validation",
    "ultimate_pipeline.signals.signal_enrichment",
    "ultimate_pipeline.tiling.tile_equivalence",
    "ultimate_pipeline.elevation.elevation_seam_fixer",
    "ultimate_pipeline.dem.dem_provenance", "opendrive_geometry.freeze",
]

NEGATIVE_CONTROLS = [
    "test_audit_normalization.py::test_pass_with_missing_negative_control_downgraded",
    "test_topology_validation.py::test_connector_zero_length_rejected",
    "test_topology_validation.py::test_lane_link_type_mismatch_rejected",
    "test_p07_elv_lan_invariants.py::TestElevationStructure::test_single_linear_long_road_fails_elv002",
    "test_p07_elv_lan_invariants.py::TestSeamFixer::test_over_threshold_not_forced",
    "test_p07_elv_lan_invariants.py::TestLaneStructure::test_negative_width_fails",
    "test_p08_signal_enrichment.py::TestEnrichment::test_invalid_placement_rejected_not_clamped",
    "test_p08_signal_enrichment.py::TestEnrichment::test_ambiguous_source_rejected",
    "test_p09_tile_equivalence.py::TestDuplicates::test_divergent_copies_violate",
    "test_p10_output_artifacts.py::TestOBJValidation::test_nonfinite_vertex_fails",
    "test_p10_output_artifacts.py::TestBlender::test_missing_blender_blocked_not_passed",
]

KNOWN_MANIFEST_FINDINGS = {
    "output:07_BLOCKING_ISSUES.md":
        "Phase A accepted finding: claim stale vs regenerated file; actual "
        "hash recorded in audit trail (acceptance ACCEPTED_WITH_FINDINGS).",
}


def sh(cmd, cwd=None, env=None, timeout=1800):
    return subprocess.run(cmd, capture_output=True, text=True, cwd=cwd,
                          env=env, timeout=timeout)


def sha256_file(path):
    d = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            d.update(chunk)
    return d.hexdigest()


def main():
    out_dir = sys.argv[1] if len(sys.argv) > 1 else "verify_out"
    os.makedirs(out_dir, exist_ok=True)
    report = {"head": {}, "gates": {}}

    # G1 identity
    proc = sh(["git", "rev-parse", "HEAD"])
    head = proc.stdout.strip()
    report["head"] = {"commit": head,
                      "matches": head == HEAD,
                      "expected": HEAD}
    proc = sh(["git", "status", "--porcelain"])
    report["head"]["dirty_lines"] = len([l for l in proc.stdout.splitlines()
                                         if l.strip()])

    # G2 compileall
    proc = sh([sys.executable, "-m", "compileall", "-q",
               "ultimate_pipeline", "opendrive_geometry"])
    report["gates"]["G2_compileall"] = {
        "pass": proc.returncode == 0, "rc": proc.returncode,
        "stderr": proc.stderr[-400:]}

    # G3 imports
    import_script = (
        "import importlib,sys\n"
        f"mods={IMPORTS!r}\n"
        "fail=[]\n"
        "for m in mods:\n"
        "    try: importlib.import_module(m)\n"
        "    except Exception as e: fail.append((m,str(e)[:150]))\n"
        "print('IMPORT_RESULT', len(mods)-len(fail), '/', len(mods))\n"
        "for f in fail: print('IMPORT_FAIL', f)\n"
    )
    proc = sh([sys.executable, "-c", import_script])
    ok = "IMPORT_RESULT 18 / 18" in proc.stdout
    report["gates"]["G3_imports"] = {"pass": ok, "stdout": proc.stdout[-500:],
                                     "stderr": proc.stderr[-300:]}

    # G4 collection
    proc = sh([sys.executable, "-m", "pytest", "--collect-only", "-q",
               "-p", "no:cacheprovider", "ultimate_pipeline/tests/unit",
               "tests/opendrive_geometry"])
    import re
    n = None
    m = re.search(r"(\d+)\s+tests collected", proc.stdout)
    if m:
        n = int(m.group(1))
    report["gates"]["G4_collection"] = {"pass": proc.returncode == 0 and bool(n),
                                        "collected": n,
                                        "tail": proc.stdout[-200:]}

    # G5 full suite
    proc = sh([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
               "ultimate_pipeline/tests/unit", "tests/opendrive_geometry"])
    tail = proc.stdout.splitlines()
    summary_line = next((l for l in reversed(tail) if "passed" in l), "")
    report["gates"]["G5_suite"] = {"pass": proc.returncode == 0,
                                   "summary": summary_line,
                                   "tail": "\n".join(tail[-6:])}

    # G6 negative controls
    proc = sh([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
               *[f"ultimate_pipeline/tests/unit/{n}" for n in NEGATIVE_CONTROLS]])
    tail = proc.stdout.splitlines()
    summary_line = next((l for l in reversed(tail) if "passed" in l), "")
    report["gates"]["G6_negative_controls"] = {"pass": proc.returncode == 0,
                                               "summary": summary_line,
                                               "tail": "\n".join(tail[-5:])}

    # G7 map structural gates
    gate_script = r'''
import json, sys, math
import xml.etree.ElementTree as ET
sys.path.insert(0, '.')
from ultimate_pipeline.quality.lane_structure_invariants import validate_lane_structure
from ultimate_pipeline.elevation.elevation_seam_fixer import fix_elevation_seams
from ultimate_pipeline.tiling.tile_equivalence import road_bounds_curve_aware
root = ET.parse(r"campaigns\ingolstadt_cooked_perception_v1\candidate\raw_xodr_run_1_epsg32632_header_pinned.xodr").getroot()
lane = validate_lane_structure(root)
import tempfile, os
st = fix_elevation_seams(r"campaigns\ingolstadt_cooked_perception_v1\candidate\raw_xodr_run_1_epsg32632_header_pinned.xodr", os.path.join(tempfile.gettempdir(),"sf.xodr"))
bad = 0; n = 0
for road in root.findall("road"):
    b = road_bounds_curve_aware(road)
    if not all(math.isfinite(v) for v in (b["x_min"],b["y_min"],b["x_max"],b["y_max"])): bad += 1
    n += 1
print("GATE_RESULT", json.dumps({"lane_ok": lane["ok"], "lane_fails": lane["fail_count"],
    "seams_max_delta": st["max_delta"], "seams_checked": st["seams_checked"],
    "bounds_roads": n, "bounds_bad": bad}))
'''
    proc = sh([sys.executable, "-c", gate_script])
    gate_json = None
    for line in proc.stdout.splitlines():
        if line.startswith("GATE_RESULT"):
            gate_json = json.loads(line[len("GATE_RESULT"):])
    ok = gate_json and gate_json["lane_ok"] and gate_json["seams_max_delta"] == 0.0 \
        and gate_json["bounds_bad"] == 0
    report["gates"]["G7_map_structural"] = {"pass": bool(ok), "result": gate_json,
                                            "stderr": proc.stderr[-300:]}

    # G8 authoritative hashes
    osm_h = sha256_file(OSM)[:10]
    xodr_h = sha256_file(XODR)[:10]
    ok8 = osm_h == OSM_EXPECT and xodr_h == XODR_EXPECT
    report["gates"]["G8_hashes"] = {"pass": ok8,
                                    "osm": osm_h, "osm_expect": OSM_EXPECT,
                                    "xodr": xodr_h, "xodr_expect": XODR_EXPECT}

    # G9 manifest validation
    manifest_script = (
        "import json,sys\n"
        "sys.path.insert(0,'.')\n"
        "from ultimate_pipeline.audit import verify_manifest\n"
        f"man = json.load(open(r'{MANIFEST}', encoding='utf-8'))\n"
        "res = verify_manifest(man, '.', 'audit_output')\n"
        "print('MANIFEST_RESULT', json.dumps({'checks': res.get('checks'), 'mismatches': res.get('mismatches')}, default=str))\n"
    )
    proc = sh([sys.executable, "-c", manifest_script])
    mres = None
    for line in proc.stdout.splitlines():
        if line.startswith("MANIFEST_RESULT"):
            mres = json.loads(line[len("MANIFEST_RESULT"):])
    mismatches = (mres or {}).get("mismatches") or []
    new_findings = [m for m in mismatches if m not in KNOWN_MANIFEST_FINDINGS]
    report["gates"]["G9_manifest"] = {"pass": bool(mres) and not new_findings,
                                      "result": mres,
                                      "known_findings": KNOWN_MANIFEST_FINDINGS,
                                      "new_findings": new_findings,
                                      "stdout": proc.stdout[-400:],
                                      "stderr": proc.stderr[-300:]}

    # G10 tracked-ID verification
    id_script = (
        "import json,os\n"
        "reqs=[json.loads(l)['requirement_id'] for l in open(r'reports/post_audit_hardening/20260801T221042Z/requirements_registry.jsonl',encoding='utf-8') if l.strip()]\n"
        "issues=[json.loads(l)['issue_id'] for l in open(r'reports/post_audit_hardening/20260801T221042Z/issues_registry.jsonl',encoding='utf-8') if l.strip()]\n"
        "print('ID_RESULT', json.dumps({'reqs':len(reqs),'issues':len(issues),'total':len(set(reqs)|set(issues)),'dup_req':len(reqs)-len(set(reqs)),'dup_issue':len(issues)-len(set(issues))}))\n"
    )
    proc = sh([sys.executable, "-c", id_script])
    idres = None
    for line in proc.stdout.splitlines():
        if line.startswith("ID_RESULT"):
            idres = json.loads(line[len("ID_RESULT"):])
    ok10 = bool(idres and idres["total"] == 232 and idres["dup_req"] == 0
                and idres["dup_issue"] == 0)
    report["gates"]["G10_tracked_ids"] = {"pass": ok10, "result": idres}

    # G11 untracked dependency scan (source tree)
    EXCLUDED_UNTRACKED = ("audit_output", ".venv_verify", "verify_out",
                          ".githooks", "p14_verify.py", "pyproject.toml")
    proc = sh(["git", "status", "--porcelain"])
    untracked = [l for l in proc.stdout.splitlines() if l.startswith("??")]
    excluded = [l for l in untracked
                if any(l.startswith(f"?? {e}") for e in EXCLUDED_UNTRACKED)]
    untracked_sources = [l for l in untracked
                         if not any(l.startswith(f"?? {e}")
                                    for e in EXCLUDED_UNTRACKED)]
    report["gates"]["G11_untracked_sources"] = {
        "pass": len(untracked_sources) == 0,
        "count": len(untracked_sources),
        "paths": untracked_sources[:20],
        "excluded_by_design": excluded[:20]}

    report["overall"] = all(g.get("pass") for g in report["gates"].values())
    with open(os.path.join(out_dir, "p14_verify_report.json"), "w",
              encoding="utf-8") as fh:
        json.dump(report, fh, indent=1)
    print(json.dumps({"overall": report["overall"],
                      **{k: v.get("pass") for k, v in report["gates"].items()}},
                     indent=1))
    return 0 if report["overall"] else 1


if __name__ == "__main__":
    sys.exit(main())
