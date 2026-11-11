"""Run against either exact old module or fixed module (path as argument)."""
import importlib.util
import pathlib
import sys
import xml.etree.ElementTree as ET

path = pathlib.Path(sys.argv[1])
spec = importlib.util.spec_from_file_location("lane_gnn_control", path)
mod = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = mod
spec.loader.exec_module(mod)
root = ET.fromstring('<OpenDRIVE><road id="1"/></OpenDRIVE>')
before = ET.tostring(root)
try:
    result = mod.LaneGNNRefiner.run_inplace(root, "unvalidated.pt")
except RuntimeError as exc:
    assert getattr(exc,"code",None) == "BLOCKED_MODEL_UNVALIDATED", str(exc)
else:
    raise AssertionError(f"Configured GNN request silently returned {result!r} without inference")
assert ET.tostring(root) == before
print("CONTROL_PASS: model requested => fail closed without mutation")
