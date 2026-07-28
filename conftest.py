import sys
from pathlib import Path

repo_root = Path(__file__).resolve().parent

import __editable___ultimate_pipeline_0_1_0_finder as ed
ed.MAPPING["ultimate_pipeline"] = str(repo_root / "ultimate_pipeline")

for key in list(ed.NAMESPACES):
    if key.startswith("ultimate_pipeline."):
        parts = key.split(".")
        new_path = repo_root
        for p in parts:
            new_path = new_path / p
        ed.NAMESPACES[key] = [str(new_path)]

if str(repo_root) in sys.path:
    sys.path.remove(str(repo_root))
sys.path.insert(0, str(repo_root))

for key in list(sys.modules):
    if key.startswith("ultimate_pipeline"):
        del sys.modules[key]
