"""A1: profile stage-06 diagnostic primitives on authoritative input (bounded)."""
import cProfile, io, json, pstats, sys, time
from pathlib import Path
import xml.etree.ElementTree as ET

sys.path.insert(0, ".")
from ultimate_pipeline.cache.performance_profiler import PerformanceProfiler
from ultimate_pipeline.carla_tools.map_registry import verify_pinned_map

pinned = verify_pinned_map("auto_map_of_record")
XODR = Path(pinned["resolved_path"])
print("input:", XODR, XODR.stat().st_size)

prof = PerformanceProfiler(run_id="rq1b_stage06_profile")
rec = {"input": str(XODR), "input_bytes": XODR.stat().st_size,
       "input_sha256": pinned["sha256_actual"], "primitives": {}}

def timed(name, fn, **kw):
    t0 = time.perf_counter(); c0 = time.process_time()
    out = fn()
    dt = time.perf_counter() - t0
    rec["primitives"][name] = {"wall_s": round(dt, 3), "cpu_s": round(time.process_time() - c0, 3), **kw}
    print(f"{name}: {dt:.1f}s wall", flush=True)
    return out

def parse():
    return ET.parse(str(XODR)).getroot()

root = timed("et_parse_full", parse)
n_roads = len(root.findall("road"))
n_geoms = sum(1 for _ in root.iter("geometry"))
n_junc = len(root.findall("junction"))
rec["counts"] = {"roads": n_roads, "geometries": n_geoms, "junctions": n_junc}

# deepcopy cost (suspect #1) — single copy only
import copy
t0 = time.perf_counter()
cp = copy.deepcopy(root)
dt = time.perf_counter() - t0
rec["primitives"]["deepcopy_full_tree"] = {"wall_s": round(dt, 3)}
print(f"deepcopy_full_tree: {dt:.1f}s wall")
del cp

# tostring rate (suspect #2): sample 2000 geometries
geoms = [g for _, g in zip(range(2000), root.iter("geometry"))]
t0 = time.perf_counter()
sizes = [len(ET.tostring(g, encoding="unicode")) for g in geoms]
dt = time.perf_counter() - t0
per = dt / len(geoms)
rec["primitives"]["geom_tostring_rate"] = {"wall_s": round(dt, 3), "n": len(geoms),
    "avg_chars": sum(sizes) // len(sizes),
    "projected_full_s": round(per * n_geoms, 1),
    "projected_x2_before_after_s": round(per * n_geoms * 2, 1)}
print(f"geom_tostring projected full x2: {per * n_geoms * 2:.0f}s")

# cProfile hotspot on _diagnostic_records_for_operation over first 200 roads
from ultimate_pipeline.pipeline_stages import stage_06_links as s6
small = ET.Element("OpenDRIVE")
for r in list(root.findall("road"))[:200]:
    small.append(copy.deepcopy(r))
pr = cProfile.Profile()
pr.enable()
s6._diagnostic_records_for_operation(small, small, operation="probe", reason="profile")
pr.disable()
so = io.StringIO()
ps = pstats.Stats(pr, stream=so).sort_stats("cumulative")
ps.print_stats(12)
rec["cprofile_top"] = so.getvalue()[:3000]
print(so.getvalue()[:1500])

# signature build cost on 200-road subset (hash vs string handled in optimization)
t0 = time.perf_counter()
sig = s6._protected_stage6_signature.__wrapped__ if hasattr(s6._protected_stage6_signature, "__wrapped__") else None
# call signature on subset file
sub = Path(".tmp-b15A/stage06_subset.xodr")
sub.parent.mkdir(exist_ok=True)
ET.ElementTree(small).write(str(sub), encoding="utf-8", xml_declaration=True)
t0 = time.perf_counter()
s = s6._protected_stage6_signature(str(sub))
dt = time.perf_counter() - t0
blob = json.dumps(s, default=str)
rec["primitives"]["signature_200roads"] = {"wall_s": round(dt, 3), "json_chars": len(blob)}
print(f"signature_200roads: {dt:.1f}s, json {len(blob)} chars")

Path("RQ1B_STAGE06_PROFILE.json").write_text(json.dumps(rec, indent=2) + "\n")
print("wrote RQ1B_STAGE06_PROFILE.json")
