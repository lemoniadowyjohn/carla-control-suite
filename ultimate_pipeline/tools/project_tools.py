from __future__ import annotations
import os
from pathlib import Path
import re

ROOT = Path(".").resolve()

IGNORE_DIRS = {
    ".git", ".idea", ".pytest_cache", "__pycache__", "venv", ".venv",
    "build", "dist", ".mypy_cache", ".ruff_cache", "logs", "wandb"
}
IGNORE_EXTS = {".pyc", ".pyo", ".png", ".jpg", ".jpeg", ".mp4", ".avi", ".zip", ".pt", ".pth"}

def is_ignored(path: Path) -> bool:
    for part in path.parts:
        if part in IGNORE_DIRS:
            return True
    if path.suffix.lower() in IGNORE_EXTS:
        return True
    return False

def walk_files(root: Path):
    for p in root.rglob("*"):
        if p.is_file() and not is_ignored(p):
            yield p

def make_tree(root: Path) -> str:
    lines = []
    def rec(dir_path: Path, prefix=""):
        entries = sorted([p for p in dir_path.iterdir() if not is_ignored(p)],
                         key=lambda x: (x.is_file(), x.name.lower()))
        for i, e in enumerate(entries):
            last = (i == len(entries)-1)
            branch = "└── " if last else "├── "
            lines.append(prefix + branch + e.name)
            if e.is_dir():
                rec(e, prefix + ("    " if last else "│   "))
    lines.append(root.name)
    rec(root)
    return "\n".join(lines)

ENTRYPOINT_PATTERNS = [
    re.compile(r"if\s+__name__\s*==\s*[\"']__main__[\"']\s*:", re.M),
    re.compile(r"def\s+main\s*\(", re.M),
    re.compile(r"argparse\.ArgumentParser", re.M),
    re.compile(r"click\.", re.M),
]

def looks_like_entrypoint(text: str) -> bool:
    return sum(bool(p.search(text)) for p in ENTRYPOINT_PATTERNS) >= 2

def main():
    files = list(walk_files(ROOT))
    sizes = sorted(((p, p.stat().st_size) for p in files), key=lambda x: x[1], reverse=True)

    tree_txt = make_tree(ROOT)
    Path("PROJECT_TREE.txt").write_text(tree_txt, encoding="utf-8")

    py_files = [p for p in files if p.suffix.lower() == ".py"]
    entrypoints = []
    for p in py_files:
        try:
            txt = p.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        if looks_like_entrypoint(txt):
            entrypoints.append(p)

    report = []
    report.append(f"# Project Report\n\n**Root:** `{ROOT}`\n")
    report.append("## Top-level Tree\n\n```text\n" + tree_txt + "\n```\n")
    report.append("## Likely Entrypoints\n")
    if entrypoints:
        for p in sorted(entrypoints):
            report.append(f"- `{p.as_posix()}`")
    else:
        report.append("- (None detected — you may have a custom launcher.)")
    report.append("\n## Largest Files (excluding media/models)\n")
    for p, s in sizes[:30]:
        report.append(f"- {s/1024:.1f} KB — `{p.as_posix()}`")

    Path("PROJECT_REPORT.md").write_text("\n".join(report), encoding="utf-8")
    print("Wrote PROJECT_TREE.txt and PROJECT_REPORT.md")

if __name__ == "__main__":
    main()
