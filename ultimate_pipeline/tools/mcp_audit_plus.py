from __future__ import annotations

import ast
import json
import os
import re
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple, Iterable


# -----------------------------
# Config you can tweak quickly
# -----------------------------

DEFAULT_EXCLUDE_DIRS = {
    ".git", "__pycache__", ".venv", "venv", "env",
    "build", "dist", ".mypy_cache", ".pytest_cache",
    "ultimate_pipeline_out", "results", "logs", "data", "datasets",
}

# "CARLA contract": only these locations may import carla
DEFAULT_ALLOWED_CARLA_PREFIXES = (
    "ultimate_pipeline/carla",
    "ultimate_pipeline/carla_tools",
    "ultimate_pipeline/core/carla_utils.py",
)

# Optional dependencies that should be guarded (try/except) if used outside specific areas
OPTIONAL_DEPS = {
    "shapely": {"suggest_guard": True},
    "torch": {"suggest_guard": False},  # often hard dependency if you have ML modules
    "cv2": {"suggest_guard": True},
}

# Layer rules: "modules under this path must NOT import these top-level packages"
DEFAULT_LAYER_FORBIDDEN_IMPORTS = [
    # domain gap evaluation should not be coupled to CARLA runtime
    {"path_prefix": "ultimate_pipeline/domain_gap", "forbid": ["carla"]},
    # offline quality should not require CARLA
    {"path_prefix": "ultimate_pipeline/quality", "forbid": ["carla"]},
    # geometry/topology core should not require CARLA
    {"path_prefix": "ultimate_pipeline/geometry", "forbid": ["carla"]},
    {"path_prefix": "ultimate_pipeline/topology", "forbid": ["carla"]},
]

# Geometry freeze policy check: if you claim "geometryFrozen", enforce a guard existence + usage coverage
GEOMETRY_GUARD_EXPECTED_PATHS = [
    "ultimate_pipeline/geometry/geometry_guard.py",
    "ultimate_pipeline/geometry_guard.py",
]

GEOMETRY_MUTATOR_HINTS = (
    "planview", "elevation", "continuity", "smoother", "repair", "curvature", "offset"
)

# -----------------------------
# Data structures
# -----------------------------

@dataclass(frozen=True)
class ImportRef:
    file: str               # rel file
    lineno: int
    kind: str               # "import" or "from"
    module: str             # imported module (resolved best-effort)
    raw: str                # raw import text
    is_relative: bool


@dataclass
class FileNode:
    rel: str
    exists: bool = True
    imports: List[ImportRef] = None  # filled later


# -----------------------------
# Helpers
# -----------------------------

def _relpath(p: Path, root: Path) -> str:
    return str(p.resolve().relative_to(root.resolve())).replace("\\", "/")


def _is_excluded(path: Path, root: Path, exclude_dirs: Set[str]) -> bool:
    rel_parts = Path(_relpath(path, root)).parts
    return any(part in exclude_dirs for part in rel_parts)


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore")


def _safe_parse_ast(path: Path) -> Optional[ast.AST]:
    try:
        return ast.parse(_read_text(path))
    except SyntaxError:
        return None


def _extract_imports(tree: ast.AST, rel_file: str) -> List[ImportRef]:
    imports: List[ImportRef] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                mod = alias.name
                imports.append(
                    ImportRef(
                        file=rel_file,
                        lineno=getattr(node, "lineno", -1),
                        kind="import",
                        module=mod,
                        raw=f"import {alias.name}",
                        is_relative=False,
                    )
                )
        elif isinstance(node, ast.ImportFrom):
            level = node.level or 0
            mod = node.module or ""
            # keep only the 'from X import' module; name-level isn't needed for dependency graph
            raw = f"from {'.'*level}{mod} import ..."
            imports.append(
                ImportRef(
                    file=rel_file,
                    lineno=getattr(node, "lineno", -1),
                    kind="from",
                    module=mod,
                    raw=raw,
                    is_relative=level > 0,
                )
            )
    return imports


def _find_try_except_imports(tree: ast.AST) -> Set[str]:
    """
    Return top-level module names imported inside a try/except block.
    This is a heuristic to detect guarding optional dependencies.
    """
    guarded: Set[str] = set()

    class Visitor(ast.NodeVisitor):
        def visit_Try(self, node: ast.Try):
            # look for import statements in try body
            for stmt in node.body:
                for sub in ast.walk(stmt):
                    if isinstance(sub, ast.Import):
                        for alias in sub.names:
                            guarded.add(alias.name.split(".")[0])
                    elif isinstance(sub, ast.ImportFrom):
                        if sub.module:
                            guarded.add(sub.module.split(".")[0])
            self.generic_visit(node)

    Visitor().visit(tree)
    return guarded


def _top_pkg(mod: str) -> str:
    return (mod or "").split(".")[0] if mod else ""


def _looks_like_internal_module(mod: str, internal_modules: Set[str]) -> bool:
    # Direct hit, or prefix hit for package imports
    if mod in internal_modules:
        return True
    # If they import package "ultimate_pipeline.geometry", treat as internal if any internal module has that prefix
    return any(m.startswith(mod + ".") for m in internal_modules)


def _build_internal_module_index(py_files: List[Path], root: Path) -> Dict[str, str]:
    """
    Map plausible module names -> rel file.
    Works for a conventional layout where the folder name is used as package name.
    Example: ultimate_pipeline/geometry/x.py -> module ultimate_pipeline.geometry.x
    Also includes top-level scripts: main_pipeline.py -> module main_pipeline
    """
    idx: Dict[str, str] = {}
    for p in py_files:
        rel = _relpath(p, root)
        parts = Path(rel).parts
        if rel.endswith(".py"):
            if len(parts) == 1:
                mod = Path(rel).stem
            else:
                mod = ".".join(list(parts[:-1]) + [Path(rel).stem]).replace("\\", "/").replace("/", ".")
            if Path(rel).name == "__init__.py":
                # package module should be folder path
                mod = ".".join(parts[:-1]).replace("\\", "/").replace("/", ".")
            idx[mod] = rel
    return idx


def _resolve_from_import(current_mod: str, imported_mod: str, level: int) -> str:
    """
    Resolve `from .x import` into absolute module name best-effort.
    current_mod: e.g. ultimate_pipeline.geometry.planview_smoother
    level: number of leading dots
    imported_mod: node.module (may be "")
    """
    if level <= 0:
        return imported_mod or ""
    cur_parts = current_mod.split(".")
    # if current module is a package __init__, it still resolves similarly
    base = cur_parts[:-level]
    if imported_mod:
        base += imported_mod.split(".")
    return ".".join([p for p in base if p])


def _module_name_for_file(rel_file: str) -> str:
    parts = Path(rel_file).parts
    if len(parts) == 1:
        return Path(rel_file).stem
    mod = ".".join(list(parts[:-1]) + [Path(rel_file).stem]).replace("\\", "/").replace("/", ".")
    if Path(rel_file).name == "__init__.py":
        mod = ".".join(parts[:-1]).replace("\\", "/").replace("/", ".")
    return mod


def _file_prefix(rel: str) -> str:
    return str(Path(rel).parent).replace("\\", "/")


def _starts_with_any_prefix(rel: str, prefixes: Iterable[str]) -> bool:
    rel = rel.replace("\\", "/")
    return any(rel.startswith(p.replace("\\", "/")) for p in prefixes)


# -----------------------------
# Graph + cycles
# -----------------------------

def _tarjan_scc(graph: Dict[str, List[str]]) -> List[List[str]]:
    """
    Tarjan SCC to find cycles in module dependency graph.
    graph: node -> neighbors
    """
    index = 0
    stack: List[str] = []
    indices: Dict[str, int] = {}
    lowlink: Dict[str, int] = {}
    onstack: Set[str] = set()
    sccs: List[List[str]] = []

    def strongconnect(v: str):
        nonlocal index
        indices[v] = index
        lowlink[v] = index
        index += 1
        stack.append(v)
        onstack.add(v)

        for w in graph.get(v, []):
            if w not in indices:
                strongconnect(w)
                lowlink[v] = min(lowlink[v], lowlink[w])
            elif w in onstack:
                lowlink[v] = min(lowlink[v], indices[w])

        if lowlink[v] == indices[v]:
            comp: List[str] = []
            while True:
                w = stack.pop()
                onstack.remove(w)
                comp.append(w)
                if w == v:
                    break
            sccs.append(comp)

    for v in graph.keys():
        if v not in indices:
            strongconnect(v)

    return sccs


def _reachable_from(entry_nodes: List[str], graph: Dict[str, List[str]]) -> Set[str]:
    seen: Set[str] = set()
    stack = list(entry_nodes)
    while stack:
        n = stack.pop()
        if n in seen:
            continue
        seen.add(n)
        for nei in graph.get(n, []):
            if nei not in seen:
                stack.append(nei)
    return seen


# -----------------------------
# Main audit
# -----------------------------

def run_audit(
    repo_root: Path,
    out_dir: Path,
    exclude_dirs: Set[str],
    allowed_carla_prefixes: Tuple[str, ...],
    layer_forbidden_imports: List[dict],
    entrypoints: Optional[List[str]] = None,
    write_dot: bool = True,
) -> Dict:
    out_dir.mkdir(parents=True, exist_ok=True)

    py_files = [p for p in repo_root.rglob("*.py") if p.is_file() and not _is_excluded(p, repo_root, exclude_dirs)]
    module_index = _build_internal_module_index(py_files, repo_root)
    internal_modules = set(module_index.keys())

    # parse imports and build dependency graph (module-level)
    import_refs: List[ImportRef] = []
    module_deps: Dict[str, List[str]] = {m: [] for m in internal_modules}
    module_ext_imports: Dict[str, Set[str]] = {m: set() for m in internal_modules}
    optional_guarded: Dict[str, Set[str]] = {m: set() for m in internal_modules}

    syntax_errors: List[str] = []

    for p in py_files:
        rel = _relpath(p, repo_root)
        mod = _module_name_for_file(rel)
        tree = _safe_parse_ast(p)
        if tree is None:
            syntax_errors.append(rel)
            continue

        imports = _extract_imports(tree, rel)
        import_refs.extend(imports)
        guarded = _find_try_except_imports(tree)
        optional_guarded[mod] = guarded

        # resolve imports into best-effort absolute module names
        for imp in imports:
            if imp.kind == "import":
                imported = imp.module
                top = _top_pkg(imported)
                if _looks_like_internal_module(imported, internal_modules):
                    # find closest internal module node: prefer exact, else package root
                    target = imported if imported in internal_modules else next(
                        (m for m in internal_modules if m.startswith(imported + ".")),
                        imported
                    )
                    module_deps.setdefault(mod, []).append(target)
                else:
                    module_ext_imports.setdefault(mod, set()).add(top)
            else:  # from import
                # need the actual level; we can't recover it from ImportRef alone
                # so parse again from AST nodes? simplest: re-walk for ImportFrom
                pass

        # second pass for ImportFrom with resolution
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                level = node.level or 0
                imported_abs = _resolve_from_import(mod, node.module or "", level)
                top = _top_pkg(imported_abs)
                if imported_abs and _looks_like_internal_module(imported_abs, internal_modules):
                    target = imported_abs if imported_abs in internal_modules else next(
                        (m for m in internal_modules if m.startswith(imported_abs + ".")),
                        imported_abs
                    )
                    module_deps.setdefault(mod, []).append(target)
                elif imported_abs:
                    module_ext_imports.setdefault(mod, set()).add(top)

    # normalize deps (dedupe)
    for m, ds in module_deps.items():
        module_deps[m] = sorted(set(ds))

    # CARLA import policy: find any module importing "carla" top-level
    carla_importers: List[Tuple[str, str]] = []  # (module, file)
    illegal_carla_importers: List[Tuple[str, str]] = []
    for m in internal_modules:
        if "carla" in module_ext_imports.get(m, set()):
            f = module_index.get(m, "")
            carla_importers.append((m, f))
            if f and not _starts_with_any_prefix(f, allowed_carla_prefixes):
                illegal_carla_importers.append((m, f))

    # Layer forbidden imports checks (best-effort via ext import tops)
    layer_violations: List[dict] = []
    for rule in layer_forbidden_imports:
        prefix = rule["path_prefix"].replace("\\", "/").rstrip("/")
        forbid = set(rule.get("forbid", []))
        for m in internal_modules:
            f = module_index.get(m, "")
            if not f:
                continue
            if f.replace("\\", "/").startswith(prefix):
                used = module_ext_imports.get(m, set())
                bad = sorted(set(used) & forbid)
                if bad:
                    layer_violations.append({
                        "module": m,
                        "file": f,
                        "forbidden_used": bad,
                        "rule": rule,
                    })

    # Optional dependency guard checks
    optional_dep_warnings: List[dict] = []
    for m in internal_modules:
        used = module_ext_imports.get(m, set())
        guarded = optional_guarded.get(m, set())
        f = module_index.get(m, "")
        for dep, cfg in OPTIONAL_DEPS.items():
            if dep in used and cfg.get("suggest_guard", False):
                if dep not in guarded:
                    optional_dep_warnings.append({
                        "module": m,
                        "file": f,
                        "dependency": dep,
                        "message": f"Optional dependency '{dep}' imported without try/except guard.",
                    })

    # Cycles
    sccs = _tarjan_scc(module_deps)
    cycles = [sorted(c) for c in sccs if len(c) > 1]
    self_cycles = []
    for m, ds in module_deps.items():
        if m in ds:
            self_cycles.append(m)

    # Reachability (dead modules detection)
    if entrypoints is None:
        # sensible defaults: top-level scripts if present
        guess = []
        for candidate in ["main_pipeline", "run_full_pipeline", "run_full_domain_gap"]:
            if candidate in internal_modules:
                guess.append(candidate)
        entrypoints = guess or []

    reachable = _reachable_from(entrypoints, module_deps) if entrypoints else set()
    unreachable = sorted([m for m in internal_modules if m not in reachable])

    # Geometry freeze guard checks
    guard_present = any((repo_root / p).exists() for p in GEOMETRY_GUARD_EXPECTED_PATHS)
    guard_calls: List[str] = []
    geometry_mutators: List[str] = []
    for m in internal_modules:
        f = module_index.get(m, "")
        if not f:
            continue
        fname = Path(f).name.lower()
        if any(h in fname for h in GEOMETRY_MUTATOR_HINTS) and "geometry_guard" not in fname:
            geometry_mutators.append(m)

        # scan file content lightly for guard call
        try:
            txt = _read_text(repo_root / f)
            if "assert_geometry_mutable" in txt:
                guard_calls.append(m)
        except Exception:
            pass

    mutator_set = set(geometry_mutators)
    guard_call_set = set(guard_calls)
    mutators_without_guard = sorted(list(mutator_set - guard_call_set))

    # Build DOT (Graphviz)
    dot_path = out_dir / "_mcp_dependency_graph.dot"
    if write_dot:
        with dot_path.open("w", encoding="utf-8") as f:
            f.write("digraph deps {\n")
            f.write('  rankdir="LR";\n')
            # make entrypoints visually distinct
            for m in entrypoints:
                if m:
                    f.write(f'  "{m}" [shape=box, style=filled, fillcolor=lightgray];\n')
            for src, dsts in module_deps.items():
                for dst in dsts:
                    if src in internal_modules and dst in internal_modules:
                        f.write(f'  "{src}" -> "{dst}";\n')
            f.write("}\n")

    report = {
        "repo_root": str(repo_root),
        "out_dir": str(out_dir),
        "counts": {
            "py_files": len(py_files),
            "modules_indexed": len(internal_modules),
            "syntax_errors": len(syntax_errors),
            "carla_importers": len(carla_importers),
            "illegal_carla_importers": len(illegal_carla_importers),
            "layer_violations": len(layer_violations),
            "optional_dep_warnings": len(optional_dep_warnings),
            "cycles": len(cycles),
            "self_cycles": len(self_cycles),
            "entrypoints": len(entrypoints),
            "unreachable_modules": len(unreachable) if entrypoints else None,
            "geometry_guard_present": guard_present,
            "geometry_mutators": len(geometry_mutators),
            "geometry_mutators_without_guard": len(mutators_without_guard),
        },
        "entrypoints": entrypoints,
        "syntax_errors": syntax_errors,
        "illegal_carla_importers": [{"module": m, "file": f} for m, f in illegal_carla_importers],
        "layer_violations": layer_violations,
        "optional_dep_warnings": optional_dep_warnings,
        "cycles": cycles[:50],  # keep bounded
        "self_cycles": self_cycles[:50],
        "unreachable_modules": unreachable[:200] if entrypoints else [],
        "geometry_freeze": {
            "guard_present": guard_present,
            "guard_expected_paths": GEOMETRY_GUARD_EXPECTED_PATHS,
            "mutators_detected": sorted(geometry_mutators)[:200],
            "mutators_without_guard": mutators_without_guard[:200],
        },
        "policy": {
            "exclude_dirs": sorted(exclude_dirs),
            "allowed_carla_prefixes": list(allowed_carla_prefixes),
            "layer_forbidden_imports": layer_forbidden_imports,
            "optional_deps": OPTIONAL_DEPS,
        },
        "artifacts": {
            "dependency_dot": str(dot_path) if write_dot else None,
        },
        "deps": module_deps,  # adjacency list, internal modules only
        "external_import_tops": {m: sorted(list(v)) for m, v in module_ext_imports.items()},
        "module_index": module_index,  # module -> file
    }

    # Write outputs
    (out_dir / "_mcp_audit_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")

    # Write a compact “red flags” file
    red_flags = []
    if syntax_errors:
        red_flags.append(f"Syntax errors in {len(syntax_errors)} files.")
    if illegal_carla_importers:
        red_flags.append(f"Illegal CARLA imports: {len(illegal_carla_importers)} (violates CARLA contract).")
    if layer_violations:
        red_flags.append(f"Layer violations: {len(layer_violations)} (e.g. offline importing CARLA).")
    if cycles:
        red_flags.append(f"Import cycles: {len(cycles)} SCC cycles.")
    if optional_dep_warnings:
        red_flags.append(f"Optional deps unguarded: {len(optional_dep_warnings)} (Shapely/cv2 etc).")
    if guard_present and mutators_without_guard:
        red_flags.append(f"Geometry mutators missing assert_geometry_mutable: {len(mutators_without_guard)}.")

    (out_dir / "_mcp_red_flags.txt").write_text(
        "\n".join(red_flags) if red_flags else "No major red flags detected.\n",
        encoding="utf-8"
    )

    return report


def main(argv: List[str]) -> int:
    import argparse

    ap = argparse.ArgumentParser(description="Stronger MCP audit: imports, deps graph, cycles, policy checks.")
    ap.add_argument("repo_root", nargs="?", default=os.getcwd(), help="Path to repo root.")
    ap.add_argument("--out", default="_mcp_audit", help="Output directory (relative to repo_root if not absolute).")
    ap.add_argument("--no-dot", action="store_true", help="Do not write Graphviz DOT.")
    ap.add_argument("--exclude", default="", help="Comma-separated additional exclude dirs.")
    ap.add_argument("--entrypoints", default="", help="Comma-separated module entrypoints (e.g. main_pipeline,run_full_pipeline).")
    ap.add_argument("--allowed-carla", default="", help="Comma-separated allowed prefixes for importing carla.")
    args = ap.parse_args(argv)

    repo_root = Path(args.repo_root).resolve()
    out_dir = Path(args.out)
    if not out_dir.is_absolute():
        out_dir = repo_root / out_dir

    exclude_dirs = set(DEFAULT_EXCLUDE_DIRS)
    if args.exclude.strip():
        exclude_dirs |= {x.strip() for x in args.exclude.split(",") if x.strip()}

    allowed_carla_prefixes = DEFAULT_ALLOWED_CARLA_PREFIXES
    if args.allowed_carla.strip():
        allowed_carla_prefixes = tuple(x.strip().replace("\\", "/") for x in args.allowed_carla.split(",") if x.strip())

    entrypoints = None
    if args.entrypoints.strip():
        entrypoints = [x.strip() for x in args.entrypoints.split(",") if x.strip()]

    report = run_audit(
        repo_root=repo_root,
        out_dir=out_dir,
        exclude_dirs=exclude_dirs,
        allowed_carla_prefixes=allowed_carla_prefixes,
        layer_forbidden_imports=DEFAULT_LAYER_FORBIDDEN_IMPORTS,
        entrypoints=entrypoints,
        write_dot=not args.no_dot,
    )

    # Console summary
    c = report["counts"]
    print("\n=== MCP AUDIT SUMMARY ===")
    for k in [
        "py_files",
        "modules_indexed",
        "syntax_errors",
        "illegal_carla_importers",
        "layer_violations",
        "cycles",
        "optional_dep_warnings",
        "geometry_guard_present",
        "geometry_mutators_without_guard",
    ]:
        print(f"{k:30s}: {c.get(k)}")
    print(f"\nWrote:\n  {Path(report['out_dir']) / '_mcp_audit_report.json'}")
    print(f"  {Path(report['out_dir']) / '_mcp_red_flags.txt'}")
    if report["artifacts"]["dependency_dot"]:
        print(f"  {report['artifacts']['dependency_dot']}")

    # exit code: fail fast if serious issues
    if c["syntax_errors"] > 0 or c["illegal_carla_importers"] > 0 or c["layer_violations"] > 0:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
