"""A4: old/reference vs optimized semantic equivalence for stage-06 diagnostics."""
import copy, importlib.util, json, os, sys
from pathlib import Path
import xml.etree.ElementTree as ET

def load_old():
    spec = importlib.util.spec_from_file_location(
        "s6_old",
        "C:/Users/admin/PycharmProjects/gpt4/pythonProject3/carla_-main/ultimate_pipeline/pipeline_stages/stage_06_links.py")
    m = importlib.util.module_from_spec(spec)
    sys.modules["s6_old"] = m
    spec.loader.exec_module(m)
    return m

sys.path.insert(0, ".")
from ultimate_pipeline.pipeline_stages import stage_06_links as new

SUB = Path(".tmp-b15A/stage06_subset.xodr")
assert SUB.exists(), "run profile_stage06.py first"
old = load_old()

# 1. records changed-SET equality on identical trees (expect empty) + mutated tree
root = ET.parse(str(SUB)).getroot()
os.environ["UP_STAGE6_DIAGNOSTICS"] = "full"
os.environ["UP_STAGE6_FULL_XML_CAP"] = "1000000"
r_old = old._diagnostic_records_for_operation(root, copy.deepcopy(root), operation="probe", reason="t")
r_new = new._diagnostic_records_for_operation(root, copy.deepcopy(root), operation="probe", reason="t")
assert r_old == r_new, "identical-tree records differ"
print("identical-tree records: equal (n=%d)" % len(r_old))

mut = copy.deepcopy(root)
g = mut.find("./road/planView/geometry")
g.set("length", str(float(g.get("length")) + 1.0))
r_old2 = old._diagnostic_records_for_operation(root, mut, operation="probe", reason="t")
r_new2 = new._diagnostic_records_for_operation(root, mut, operation="probe", reason="t")
set_old = {(r["affected_road"], r["geometry_index"]) for r in r_old2}
set_new = {(r["affected_road"], r["geometry_index"]) for r in r_new2}
assert set_old == set_new and r_old2 == r_new2, "mutated records differ"
print("mutated-tree full records: bit-identical (n=%d)" % len(r_old2))

# 2. capped mode: verdict-relevant fields identical
os.environ["UP_STAGE6_DIAGNOSTICS"] = "summary"
os.environ["UP_STAGE6_FULL_XML_CAP"] = "0"
r_new3 = new._diagnostic_records_for_operation(root, mut, operation="probe", reason="t")
core = lambda r: (r["affected_road"], r["geometry_index"], r.get("predicted_endpoint_displacement_m"), r.get("predicted_tangent_change_rad"))
assert {core(r) for r in r_new3 if "affected_road" in r} == {(core(r)) for r in r_old2}, "capped core fields differ"
print("capped-mode core fields: identical; summary note present:",
      any(r.get("mode") == "READ_ONLY_DIAGNOSTIC_SUMMARY" for r in r_new3))

# 3. signature verdict equality (self + mutated file)
mut_path = Path(".tmp-b15A/stage06_subset_mut.xodr")
ET.ElementTree(mut if isinstance(mut, ET.Element) else root).write(str(mut_path), encoding="utf-8", xml_declaration=True)
d_old = old._semantic_stage6_diff(str(SUB), str(mut_path))
d_new = new._semantic_stage6_diff(str(SUB), str(mut_path))
assert d_old["ok"] == d_new["ok"] and d_old["changed"] == d_new["changed"], (d_old, d_new)
print("signature verdict: identical", d_new)
d_old0 = old._semantic_stage6_diff(str(SUB), str(SUB))
d_new0 = new._semantic_stage6_diff(str(SUB), str(SUB))
assert d_old0["ok"] and d_new0["ok"]
print("self-diff: ok both")

# 4. medium-file (2000 roads) old-vs-new verdict equality + new determinism
big = ET.Element("OpenDRIVE")
full = ET.parse(str(SUB)).getroot()  # subset file root has 200 roads; replicate deterministically
roads = list(full.findall("road"))
while len(list(big.findall("road"))) < 2000:
    for r in roads:
        if len(list(big.findall("road"))) >= 2000:
            break
        c = copy.deepcopy(r)
        c.set("id", f"{c.get('id')}_rep{len(list(big.findall('road')))}")
        big.append(c)
med = Path(".tmp-b15A/stage06_med.xodr")
ET.ElementTree(big).write(str(med), encoding="utf-8", xml_declaration=True)
med_mut = Path(".tmp-b15A/stage06_med_mut.xodr")
big2 = copy.deepcopy(big)
g2 = big2.find("./road/planView/geometry")
g2.set("hdg", str(float(g2.get("hdg")) + 0.5))
ET.ElementTree(big2).write(str(med_mut), encoding="utf-8", xml_declaration=True)
d_oldM = old._semantic_stage6_diff(str(med), str(med_mut))
d_newM = new._semantic_stage6_diff(str(med), str(med_mut))
assert d_oldM["ok"] == d_newM["ok"] and d_oldM["changed"] == d_newM["changed"], (d_oldM, d_newM)
print("medium-file verdict: identical", d_newM["changed"][:3])
n1 = new._protected_stage6_signature(str(med))
n2 = new._protected_stage6_signature(str(med))
assert n1 == n2, "new signature not deterministic"
print("new-signature determinism: identical across runs")

json.dump({"verdict": "PASS", "checks": ["identical-tree", "mutated-full", "capped-core", "signature-self", "signature-mut"]},
          open("RQ1B_STAGE06_SEMANTIC_EQUIVALENCE.json", "w"), indent=2)
print("wrote RQ1B_STAGE06_SEMANTIC_EQUIVALENCE.json PASS")
