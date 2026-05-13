#!/usr/bin/env python3
import os, ast

ROOT = os.path.dirname(os.path.abspath(__file__))

def py_files(root):
    for d, _, files in os.walk(root):
        if any(skip in d for skip in ["__pycache__", "venv", ".venv", ".git", "build", "dist"]):
            continue
        for f in files:
            if f.endswith(".py"):
                yield os.path.join(d, f)

def parse_imports(path):
    try:
        src = open(path, encoding="utf-8").read()
    except:
        return []
    try:
        tree = ast.parse(src)
    except:
        return []
    imports = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for n in node.names:
                imports.append(("import", n.name))
        elif isinstance(node, ast.ImportFrom):
            imports.append(("from", node.module or ""))
    return imports

print("# IMPORT MAP")
print(f"# ROOT = {ROOT}\n")

for py in sorted(py_files(ROOT)):
    rel = os.path.relpath(py, ROOT)
    imps = parse_imports(py)
    if not imps:
        continue
    print(f"[FILE] {rel}")
    seen = set()
    for kind, name in imps:
        if (kind, name) not in seen:
            seen.add((kind, name))
            print(f"  {kind} {name}")
    print()
