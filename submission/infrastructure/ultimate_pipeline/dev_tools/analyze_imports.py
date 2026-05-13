import ast
from pathlib import Path
from collections import defaultdict

ROOT = Path("ultimate_pipeline")

imports = defaultdict(set)

for py in ROOT.rglob("*.py"):
    try:
        tree = ast.parse(py.read_text(encoding="utf-8"))
    except Exception:
        continue

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for n in node.names:
                imports[py].add(n.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imports[py].add(node.module.split(".")[0])

for k, v in sorted(imports.items()):
    print(k)
    for dep in sorted(v):
        print("   ->", dep)
