import os
import sys
import re
import argparse
from typing import List, Dict, Tuple, Set


# --- Helper Functions ---

def get_file_type(file_path: str) -> str:
    ext = os.path.splitext(file_path)[1].lower()
    if ext == ".py":
        return "python"
    if ext == ".md":
        return "markdown"
    if ext == ".ps1":
        return "powershell"
    if ext in [
        ".json", ".csv", ".txt", ".log", ".zip", ".patch", ".pem", ".iml", ".tag", ".h", ".pyd",
        ".pth", ".pyi", ".afm", ".ttf", ".sh", ".xml", ".npz", ".dat", ".jpg", ".png", ".svg",
        ".geojson", ".obj", ".mtl", ".ply", ".7z", ".gltf", ".bin", ".glb", ".sqlite", ".db",
        ".lock", ".dll", ".js", ".css", ".html", ".wasm", ".properties", ".yml", ".yaml",
        ".sumocfg", ".xsd", ".bib", ".adoc", ".c", ".cpp", ".hpp", ".cs", ".jar", ".sln",
        ".csproj", ".map", ".eot", ".woff", ".woff2", ".fmf", ".j2", ".spec", ".wav", ".gz",
        ".ico", ".pyproj"
    ]:
        return "data"
    if ext in [".toml", ".ini", ".cfg"] or "settings" in os.path.basename(file_path).lower():
        return "config"
    if ext in [
        ".tex", ".aux", ".acn", ".acr", ".alg", ".bbl", ".blg", ".glg", ".glo", ".gls", ".glsdefs",
        ".ilg", ".ist", ".lof", ".lot", ".nlo", ".nls", ".toc"
    ]:
        return "latex"
    return "other"


def get_high_level_category(relative_path: str) -> str:
    parts = relative_path.split(os.sep)

    # Prioritize specific well-known top-level directories
    if parts and parts[0] == "ultimate_pipeline":
        if "domain_gap" in parts:
            return "domain_gap"
        if "perception" in parts:
            return "perception"
        if "tools" in parts:
            return "tools"
        if "config" in parts:
            return "config"
        if "tests" in parts:
            return "tests"
        if "docs" in parts:
            return "docs"
        return "pipeline"

    if parts and parts[0] == "domain_gap":
        return "domain_gap"
    if parts and parts[0] == "perception":
        return "perception"
    if parts and parts[0] == "carla":
        return "carla"
    if parts and parts[0] == "tools":
        return "tools"
    if parts and parts[0] == "docs":
        return "docs"
    if parts and parts[0] == "config":
        return "config"
    if parts and parts[0] == "tests":
        return "tests"

    if parts and (
        parts[0] in {"artifacts", "ultimate_pipeline_out", "eval_out", "thesis_results", "out"} or
        (parts[0].startswith("_") and "out" in parts[0])
    ):
        return "data_output"

    if parts and parts[0] == "external":
        return "external_lib"
    if parts and parts[0] == "mcp_server":
        return "carla_mcp_server"

    if "thesis" in relative_path.lower():
        return "thesis_related"
    if "runbook" in relative_path.lower():
        return "docs"

    filename = os.path.basename(relative_path).lower()
    if filename.startswith("run_") or filename.endswith(".ps1") or filename.endswith(".sh"):
        return "pipeline"
    if "readme" in filename or "changelog" in filename or "runbook" in filename or filename.endswith(".md"):
        return "docs"
    if (
        "requirements" in filename or filename == "pyproject.toml" or filename == "pytest.ini" or
        "conftest.py" in filename
    ):
        return "config"
    if ".git" in relative_path.split(os.sep):
        return "config"
    if ".venv" in relative_path.split(os.sep) or "__pycache__" in relative_path.split(os.sep):
        return "build_cache"
    if "test" in filename:
        return "tests"
    if filename.endswith((".json", ".xml", ".csv")):
        return "data"

    return "other"


def infer_description_from_filename(filename: str, file_type: str) -> str:
    name_without_ext = os.path.splitext(os.path.basename(filename))[0]

    if file_type == "python":
        if name_without_ext.startswith("run_"):
            return f"Entry-point script for {name_without_ext.replace('run_', '').replace('_', ' ')}."
        if name_without_ext.startswith("main_"):
            return f"Main script for {name_without_ext.replace('main_', '').replace('_', ' ')}."
        if name_without_ext == "cli":
            return "Command-line interface utility."
        if name_without_ext == "entrypoints":
            return "Defines pipeline entry points."
        if "test" in name_without_ext:
            return f"Test script for {name_without_ext.replace('test_', '').replace('_', ' ')}."
        if name_without_ext == "__init__":
            return "Python package initializer."
        return f"Python module: {name_without_ext.replace('_', ' ')}."

    if file_type == "powershell":
        return f"PowerShell script: {name_without_ext.replace('_', ' ')}."

    if file_type == "markdown":
        low = name_without_ext.lower()
        if "readme" in low:
            return "Project overview and getting started guide."
        if "changelog" in low:
            return "Project change log."
        if "runbook" in low:
            return "Runbook / operational guide."
        if "thesis" in low:
            return "Thesis-related documentation."
        return f"Markdown document: {name_without_ext.replace('_', ' ')}."

    if file_type == "data":
        low = name_without_ext.lower()
        if "requirements" in low:
            return "Python package dependencies."
        if "manifest" in low:
            return "Run manifest or data manifest."
        if "report" in low or "summary" in low:
            return "Generated report or summary data."
        if "config" in low:
            return "Configuration data."
        return f"Data file: {name_without_ext.replace('_', ' ')}."

    if file_type == "config":
        return f"Configuration file: {name_without_ext.replace('_', ' ')}."

    if file_type == "latex":
        return f"LaTeX document or component: {name_without_ext.replace('_', ' ')}."

    return "unknown"


def get_docstring(file_path: str) -> str:
    """
    Best-effort module docstring extraction:
    - Read initial chunk
    - Find first triple-quoted string (triple-double or triple-single)
    - Return first non-empty line
    """
    try:
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read(4096)

        match = re.search(r'"""(.*?)"""', content, re.DOTALL)
        if not match:
            match = re.search(r"'''(.*?)'''", content, re.DOTALL)

        if match:
            docstring = match.group(1).strip()
            if not docstring:
                return "Python module docstring (empty)."
            first_line = docstring.splitlines()[0].strip()
            return first_line if first_line else "Python module docstring (no first line)."
    except Exception:
        pass
    return "unknown (no docstring found or error reading file)"


# --- Main Inventory Processing ---

def process_inventory(raw_paths_string: str, current_dir_abs_path: str) -> Tuple[
    List[Dict[str, str]],
    List[Dict[str, str]],
    List[Dict[str, str]],
    List[str]
]:
    inventory_data: List[Dict[str, str]] = []
    python_files_for_docstrings: List[Dict[str, str]] = []
    unique_data_artifact_dirs: Set[str] = set()

    full_paths = [p.strip() for p in raw_paths_string.splitlines() if p.strip()]

    for full_path in full_paths:
        if not os.path.isfile(full_path):
            continue

        relative_path = os.path.relpath(full_path, current_dir_abs_path)
        file_type = get_file_type(relative_path)
        category = get_high_level_category(relative_path)

        # Record data_output parent dirs (stable + cheap)
        if category == "data_output":
            parent_dir = os.path.dirname(relative_path)
            if parent_dir and parent_dir != ".":
                unique_data_artifact_dirs.add(parent_dir.replace("\\", "/"))

        description = "unknown"
        if file_type == "python":
            python_files_for_docstrings.append({"relative_path": relative_path, "full_path": full_path})
        else:
            description = infer_description_from_filename(os.path.basename(relative_path), file_type)

        inventory_data.append({
            "Path": relative_path.replace("\\", "/"),
            "File type": file_type,
            "High-level category": category,
            "Description": description
        })

    # Update python descriptions from docstrings
    path_to_entry = {e["Path"]: e for e in inventory_data}
    for py in python_files_for_docstrings:
        rel = py["relative_path"].replace("\\", "/")
        docstring = get_docstring(py["full_path"])
        entry = path_to_entry.get(rel)
        if not entry:
            continue
        if entry["Description"] == "unknown" or entry["Description"].startswith("Python module:"):
            entry["Description"] = docstring

    # Entry points + configs
    entry_point_scripts: List[Dict[str, str]] = []
    config_files: List[Dict[str, str]] = []

    for item in inventory_data:
        p = item["Path"]
        ft = item["File type"]
        filename_lower = os.path.basename(p).lower()

        is_entry_point = False
        if ft == "python":
            if (
                filename_lower.startswith("run_")
                or filename_lower in {"cli.py", "entrypoints.py", "main_pipeline.py"}
                or "run_full_domain_gap" in filename_lower
                or "run_quality_gates" in filename_lower
            ):
                is_entry_point = True
        elif ft == "powershell" or (ft == "data" and p.lower().endswith(".sh")):
            is_entry_point = True

        if is_entry_point:
            entry_point_scripts.append(item)

        is_config = (
            ft == "config"
            or (ft == "data" and p.lower().endswith((".json", ".ini", ".cfg", ".toml", ".yaml", ".yml")))
            or ("requirements" in p.lower())
            or ("conftest" in p.lower())
            or ("settings" in os.path.basename(p).lower() and ft == "python")
        )
        if is_config:
            config_files.append(item)

    sorted_data_artifact_dirs = sorted(unique_data_artifact_dirs)
    return inventory_data, entry_point_scripts, config_files, sorted_data_artifact_dirs


# --- Markdown Table Formatting ---

def print_markdown_table(headers: List[str], data: List[Dict[str, str]], include_category: bool = True) -> None:
    actual_headers = [h for h in headers if include_category or h != "High-level category"]

    print("| " + " | ".join(actual_headers) + " |")
    print("| " + " | ".join(["-" * len(h) for h in actual_headers]) + " |")

    for row in data:
        values: List[str] = []
        for header in headers:
            if not include_category and header == "High-level category":
                continue
            v = row.get(header, "") or ""
            values.append(str(v).replace("\n", " ").strip())
        print("| " + " | ".join(values) + " |")


def read_text_file(path: str) -> str:
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        return f.read()


# --- Main Execution Block ---

def main(argv: List[str]) -> int:
    ap = argparse.ArgumentParser(
        description="Process a raw file list (absolute paths) into markdown inventory tables.",
        add_help=True,
    )
    ap.add_argument("raw_file_list_path", nargs="?", help="Path to text file containing absolute file paths, one per line.")
    ap.add_argument("current_working_directory", nargs="?", help="Repo root (used to compute relative paths).")
    args = ap.parse_args(argv[1:])

    # Backward-compatible: require both if provided positionally
    if not args.raw_file_list_path or not args.current_working_directory:
        print(
            "Usage: python inventory_processor.py <path_to_raw_file_list> <current_working_directory>",
            file=sys.stderr
        )
        return 1

    raw_file_list_path = args.raw_file_list_path
    cwd = args.current_working_directory

    try:
        raw_paths_string_from_file = read_text_file(raw_file_list_path)
    except FileNotFoundError:
        print(f"Error: Raw file list not found at {raw_file_list_path}", file=sys.stderr)
        return 1

    inventory, entry_points, configs, data_dirs = process_inventory(raw_paths_string_from_file, cwd)

    # Main Inventory Table
    print("## Project File Inventory\n")
    inventory_headers = ["Path", "File type", "High-level category", "Description"]
    inventory_sorted = sorted(inventory, key=lambda x: x["Path"])
    print_markdown_table(inventory_headers, inventory_sorted, include_category=True)
    print("\n")

    # Entry-Point Scripts
    print("## Entry-Point Scripts\n")
    entry_point_headers = ["Path", "File type", "Description"]
    entry_points_sorted = sorted(entry_points, key=lambda x: x["Path"])
    print_markdown_table(entry_point_headers, entry_points_sorted, include_category=False)
    print("\n")

    # Configuration Files
    print("## Configuration Files\n")
    config_headers = ["Path", "File type", "Description"]
    config_sorted = sorted(configs, key=lambda x: x["Path"])
    print_markdown_table(config_headers, config_sorted, include_category=False)
    print("\n")

    # Data/Artifact Directories
    print("## Data/Artifact Directories\n")
    if data_dirs:
        for d in data_dirs:
            print(f"- `{d}`")
    else:
        print("No data/artifact directories found.")
    print("\n")

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
