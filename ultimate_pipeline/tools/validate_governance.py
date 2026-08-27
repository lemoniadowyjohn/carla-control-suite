from __future__ import annotations

import argparse
from collections import Counter
import json
import re
import subprocess
from pathlib import Path

import yaml
from ultimate_pipeline.contracts.agent_sync import validate_agent_sync

ROOT = Path(__file__).resolve().parents[2]
SYNC_YAML = ROOT / "agent_sync.yaml"
SYNC_MD = ROOT / "AGENT_SYNC.md"
LEDGER_MD = ROOT / "AGENT_TASK_LEDGER.md"
GOVERNED_ROOT_FILES = (
    Path("AGENT_SYNC.md"),
    Path("AGENT_TASK_LEDGER.md"),
    Path("agent_sync.yaml"),
)
SCAN_INCLUDE_DIRS = (Path("ultimate_pipeline"),)
SCAN_EXCLUDED_DIR_NAMES = {
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    "build",
    "dist",
    "external",
}
SCAN_EXCLUDED_NAME_HINTS = (
    "vendored",
    "vendor_snapshot",
    "snapshot_vendor",
)
PRODUCTION_EXCLUDED_SEGMENTS = {
    "external",
    "tests",
    "test",
    "dev_tools",
    "diagnostics",
    "enrichment",
    "osm",
}
SYS_PATH_MUTATION_ALLOWLIST = {
    "ultimate_pipeline/__init__.py",
    "ultimate_pipeline/bootstrap_repo_root.py",
    "ultimate_pipeline/experiments/thesis/experiment_auto_vs_auto.py",
    "ultimate_pipeline/main_pipeline.py",
    "ultimate_pipeline/run_determinism_audit.py",
    "ultimate_pipeline/run_pipeline.py",
    "ultimate_pipeline/run_quality_gates.py",
    "ultimate_pipeline/sitecustomize.py",
    "ultimate_pipeline/usercustomize.py",
}

ALLOWED_STATUSES = {
    "DETECTED", "TRIAGED", "IN_PROGRESS", "BLOCKED", "WAITING", "RESOLVED", "DEFERRED"
}
# Primary task definitions must be at the start of the line with a header symbol
PRIMARY_TASK_HEADER_RE = re.compile(r"^(?:###|##)\s+(T-[A-Z0-9\-]+)\b", flags=re.MULTILINE)
TASK_STATUS_LINE_RE = re.compile(r"^\s*-\s+Status:\s*(.+?)\s*$", flags=re.MULTILINE)
TASK_PATCH_READY_LINE_RE = re.compile(r"^\s*-\s+Patch Ready:\s*(.+?)\s*$", flags=re.MULTILINE)
TASK_CLASS_LINE_RE = re.compile(r"^\s*-\s+Task Class:\s*(.+?)\s*$", flags=re.MULTILINE)
TASK_PRIORITY_LINE_RE = re.compile(r"^\s*-\s+Priority:\s*(.+?)\s*$", flags=re.MULTILINE)
TASK_TARGET_FILES_LINE_RE = re.compile(r"^\s*-\s+Target Files:[ \t]*(.*?)\s*$", flags=re.MULTILINE)
TASK_ACTIVE_BRANCH_LINE_RE = re.compile(r"^\s*-\s+Active Branch:\s*(.+?)\s*$", flags=re.MULTILINE)
TASK_MIN_VERIF_LINE_RE = re.compile(r"^\s*-\s+Minimum Verification:\s*(.+?)\s*$", flags=re.MULTILINE)
TASK_GEMINI_FIRST_LINE_RE = re.compile(r"^\s*-\s+Gemini First:\s*(.+?)\s*$", flags=re.MULTILINE)
TASK_GEMINI_OUTPUT_RE_LINE_RE = re.compile(r"^\s*-\s+Gemini Output Required:\s*(.+?)\s*$", flags=re.MULTILINE)
RESOLVED_TASK_HEADER_RE = re.compile(r"^(?:###|##)\s+(R-[A-Z0-9\-]+)\b", flags=re.MULTILINE)
METADATA_FIELD_LINE_RE = re.compile(r"^\s*-\s+[A-Za-z][A-Za-z0-9 _()/\-]*:\s*")
MIN_VERIF_PLACEHOLDER_RE = re.compile(r"(?:<\s*\.\.\.\s*>|\.\.\.)")

# Spec v1.0: Block absolute paths anywhere (Windows drive root or /home or /tmp)
ABSOLUTE_PATH_RE = re.compile(
    r"(?i)(?:\b[A-Z]:\\[^\s|`\"']+|(?<!\w)/(?:home|tmp)/[^\s|`\"']+)"
)

# Detect _tmp/tmp paths with or without backticks.
TMP_PATH_RE = re.compile(
    r"(?<![A-Za-z0-9_])`?(?:_tmp|tmp)[A-Za-z0-9_\-]*(?:/[A-Za-z0-9_.\-]+)+`?(?![A-Za-z0-9_])"
)
PROMOTED_PATH_RE = re.compile(r"`(?:thesis_results|artifacts)/[A-Za-z0-9_.\-/]+`")
SYS_PATH_MUTATION_RE = re.compile(r"\bsys\.path\.(?:append|insert)\s*\(")
FORBIDDEN_NAMESPACE_IMPORT_RULES = (
    (
        re.compile(r"^\s*from\s+config\.settings\s+import\b"),
        "forbidden namespace drift import; use ultimate_pipeline.config.settings",
    ),
    (
        re.compile(r"^\s*import\s+config\.settings\b"),
        "forbidden namespace drift import; use ultimate_pipeline.config.settings",
    ),
    (
        re.compile(r"^\s*from\s+config\s+import\s+settings\b"),
        "forbidden namespace drift import; use ultimate_pipeline.config.settings",
    ),
)

TMP_ALLOWED_LABELS = ("[WIP]", "[DIAGNOSTIC]", "[POC]")
TMP_ALLOWED_SECTION_KEYWORDS = ("active tasks", "changelog", "diagnostic evidence")

SUBMISSION_DOCS_DIR = ROOT / "docs" / "submission"

def _read(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        # Keep governance validation running even if legacy docs contain
        # non-UTF8 bytes (for example Windows smart quotes).
        return p.read_text(encoding="utf-8", errors="replace")

def _git_porcelain() -> list[str]:
    cp = subprocess.run(
        ["git", "status", "--porcelain=v1"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    lines = [line.rstrip() for line in cp.stdout.splitlines() if line.strip()]
    print(f"DEBUG: git porcelain lines: {lines}")
    return lines


def _parse_git_status_path(status_line: str) -> str:
    text = str(status_line or "").rstrip("\r\n")
    if len(text) < 4:
        return ""
    path_part = text[3:].strip()
    if " -> " in path_part:
        path_part = path_part.split(" -> ", 1)[1].strip()
    if path_part.startswith('"') and path_part.endswith('"') and len(path_part) >= 2:
        # git porcelain may C-quote paths that include spaces or escapes.
        path_part = bytes(path_part[1:-1], "utf-8").decode("unicode_escape")
    return path_part.replace("\\", "/")


def _extract_task_blocks(ledger_md: str) -> list[tuple[str, int, str]]:
    blocks: list[tuple[str, int, str]] = []
    matches = list(PRIMARY_TASK_HEADER_RE.finditer(str(ledger_md or "")))
    for index, match in enumerate(matches):
        task_id = match.group(1)
        block_start = match.start()
        block_end = matches[index + 1].start() if index + 1 < len(matches) else len(ledger_md)
        block_text = ledger_md[block_start:block_end]
        block_line = ledger_md.count("\n", 0, block_start) + 1
        blocks.append((task_id, block_line, block_text))
    return blocks


def _iter_submission_docs_for_tmp_check(dirty_lines: list[str]) -> list[Path]:
    if not SUBMISSION_DOCS_DIR.exists():
        return []

    dirty_paths = {
        _parse_git_status_path(line).lower()
        for line in dirty_lines
        if _parse_git_status_path(line)
    }

    selected: list[Path] = []
    for path in sorted(SUBMISSION_DOCS_DIR.rglob("*.md")):
        rel = path.relative_to(ROOT).as_posix().lower()
        if rel in dirty_paths:
            selected.append(path)
    return selected


def _is_excluded_scan_path(rel_path: Path) -> bool:
    rel = Path(rel_path)
    lowered_parts = {part.lower() for part in rel.parts}
    if lowered_parts.intersection(SCAN_EXCLUDED_DIR_NAMES):
        return True
    rel_lower = rel.as_posix().lower()
    return any(hint in rel_lower for hint in SCAN_EXCLUDED_NAME_HINTS)


def _iter_static_scan_targets() -> list[Path]:
    targets: set[Path] = set()

    for rel_file in GOVERNED_ROOT_FILES:
        abs_file = ROOT / rel_file
        if abs_file.exists():
            targets.add(rel_file)

    for rel_dir in SCAN_INCLUDE_DIRS:
        abs_dir = ROOT / rel_dir
        if not abs_dir.exists():
            continue
        for candidate in abs_dir.rglob("*.py"):
            rel_candidate = candidate.relative_to(ROOT)
            if _is_excluded_scan_path(rel_candidate):
                continue
            targets.add(rel_candidate)

    return sorted(targets)


def _iter_repo_owned_production_modules() -> list[Path]:
    selected: list[Path] = []
    for rel in _iter_static_scan_targets():
        if not (rel.suffix == ".py" and rel.parts and rel.parts[0] == "ultimate_pipeline"):
            continue
        lowered_parts = {part.lower() for part in rel.parts}
        if lowered_parts.intersection(PRODUCTION_EXCLUDED_SEGMENTS):
            continue
        selected.append(rel)
    return selected


def _validate_static_scan_scope() -> list[str]:
    errors: list[str] = []
    targets = _iter_static_scan_targets()
    if not targets:
        errors.append("governance static scan scope is empty")
        return errors

    for rel in targets:
        if _is_excluded_scan_path(rel):
            errors.append(f"governance static scan scope includes excluded path: {rel.as_posix()}")

    return errors


def _validate_no_sys_path_mutation() -> list[str]:
    errors: list[str] = []
    for rel in _iter_repo_owned_production_modules():
        rel_posix = rel.as_posix()
        if rel_posix in SYS_PATH_MUTATION_ALLOWLIST:
            continue
        abs_path = ROOT / rel
        try:
            text = abs_path.read_text(encoding="utf-8", errors="replace")
        except Exception as exc:
            errors.append(f"{rel_posix}: failed to read for sys.path scan: {exc}")
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            if SYS_PATH_MUTATION_RE.search(line):
                errors.append(
                    f"{rel_posix}:{lineno}: forbidden runtime sys.path mutation (sys.path.append/insert)"
                )
    return errors


def _validate_namespace_import_drift() -> list[str]:
    errors: list[str] = []
    for rel in _iter_repo_owned_production_modules():
        rel_posix = rel.as_posix()
        abs_path = ROOT / rel
        try:
            text = abs_path.read_text(encoding="utf-8", errors="replace")
        except Exception as exc:
            errors.append(f"{rel_posix}: failed to read for namespace drift scan: {exc}")
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            for pattern, message in FORBIDDEN_NAMESPACE_IMPORT_RULES:
                if pattern.search(line):
                    errors.append(f"{rel_posix}:{lineno}: {message}")
                    break
    return errors


def _line_has_allowed_tmp_label(line: str) -> bool:
    upper_line = str(line or "").upper()
    return any(label in upper_line for label in TMP_ALLOWED_LABELS)


def _section_allows_tmp(h2_section: str, h3_section: str) -> bool:
    h2 = str(h2_section or "").lower()
    h3 = str(h3_section or "").lower()
    
    # Spec v1.0 allowed sections
    allowed_h2 = ("active tasks", "changelog")
    allowed_h3 = ("diagnostic evidence",)
    
    return any(kw in h2 for kw in allowed_h2) or any(kw in h3 for kw in allowed_h3)


def _resolved_tmp_is_diagnostic_promoted(line: str) -> bool:
    text = str(line or "")
    if "[DIAGNOSTIC] ORIGINAL:" not in text.upper():
        return False
    return bool(PROMOTED_PATH_RE.search(text))


def _validate_evidence_paths(ledger_md: str) -> list[str]:
    errors: list[str] = []
    h2_section = ""
    h3_section = ""

    for lineno, raw_line in enumerate(str(ledger_md or "").splitlines(), start=1):
        line = str(raw_line or "")
        stripped = line.strip()

        if stripped.startswith("## "):
            h2_section = stripped[3:].strip()
            h3_section = ""
        elif stripped.startswith("### "):
            h3_section = stripped[4:].strip()

        # Absolute path check
        abs_matches = ABSOLUTE_PATH_RE.findall(line)
        if abs_matches:
            errors.append(
                f"AGENT_TASK_LEDGER.md:{lineno}: absolute path forbidden (Windows drive root, /home, /tmp): {abs_matches[0]}"
            )

        # _tmp path check
        if not TMP_PATH_RE.search(line):
            continue

        lower_h2 = h2_section.lower()
        lower_h3 = h3_section.lower()

        # Specific forbidden zones
        in_scenario_b = "scenario b completion" in lower_h2
        in_evidence_pack = "evidence pack" in lower_h2 or "evidence pack" in lower_h3
        in_thesis_claim = "thesis claim" in lower_h2 or "thesis claim" in lower_h3
        
        # Evidence rows usually contain | R-XXX | and | RESOLVED |
        in_resolved_row = "| " in line and "RESOLVED" in line.upper()

        if in_scenario_b or in_evidence_pack or in_thesis_claim:
            errors.append(
                f"AGENT_TASK_LEDGER.md:{lineno}: _tmp paths forbidden in Scenario B / Evidence Pack / Thesis Claim sections"
            )
            continue

        if in_resolved_row and not _resolved_tmp_is_diagnostic_promoted(line):
            errors.append(
                f"AGENT_TASK_LEDGER.md:{lineno}: _tmp paths forbidden in RESOLVED evidence row unless labeled [DIAGNOSTIC] original: and promoted"
            )
            continue

        if _section_allows_tmp(h2_section, h3_section) and _line_has_allowed_tmp_label(line):
            continue

        errors.append(
            f"AGENT_TASK_LEDGER.md:{lineno}: _tmp path requires allowed section (Active Tasks/Changelog/Diagnostic Evidence) + [WIP]/[DIAGNOSTIC]/[POC] label"
        )

    return errors


def _validate_tmp_paths_with_labels(doc_name: str, markdown_text: str) -> list[str]:
    errors: list[str] = []
    for lineno, raw_line in enumerate(str(markdown_text or "").splitlines(), start=1):
        line = str(raw_line or "")
        if not TMP_PATH_RE.search(line):
            continue
        if _line_has_allowed_tmp_label(line):
            continue
        errors.append(
            f"{doc_name}:{lineno}: [GOV-TMP-EXT] _tmp path requires same-line [WIP]/[DIAGNOSTIC]/[POC] label"
        )
    return errors


def _validate_tmp_path_extensions(sync_md: str, dirty_lines: list[str]) -> list[str]:
    errors: list[str] = []
    errors.extend(_validate_tmp_paths_with_labels("AGENT_SYNC.md", sync_md))

    for submission_doc in _iter_submission_docs_for_tmp_check(dirty_lines):
        rel_name = submission_doc.relative_to(ROOT).as_posix()
        errors.extend(
            _validate_tmp_paths_with_labels(
                rel_name,
                _read(submission_doc),
            )
        )

    return errors


def _validate_ledger_resolved_section(ledger_md: str) -> list[str]:
    errors: list[str] = []
    active_match = re.search(r"^##\s+Active Tasks\b", ledger_md, flags=re.MULTILINE)
    resolved_match = re.search(r"^##\s+Resolved Tasks\b", ledger_md, flags=re.MULTILINE)
    if not active_match or not resolved_match:
        return errors

    active_start = active_match.start()
    resolved_start = resolved_match.start()
    if resolved_start <= active_start:
        return errors

    for match in RESOLVED_TASK_HEADER_RE.finditer(ledger_md):
        if not (active_start < match.start() < resolved_start):
            continue
        line = ledger_md.count("\n", 0, match.start()) + 1
        task_id = match.group(1)
        errors.append(
            f"AGENT_TASK_LEDGER.md:{line}: [LEDGER-SECTION] resolved task header {task_id} is inside Active Tasks"
        )

    return errors


def _is_blank_or_tbd(value: str) -> bool:
    text = str(value or "").strip()
    return not text or text.upper() == "TBD"


def _looks_like_file_path(value: str) -> bool:
    token = str(value or "").strip().strip("`")
    if _is_blank_or_tbd(token):
        return False
    if "/" not in token and "\\" not in token:
        return False
    if " " in token:
        return False
    return bool(re.search(r"[A-Za-z0-9_]", token))


def _extract_target_file_values(block_text: str) -> list[str]:
    match = TASK_TARGET_FILES_LINE_RE.search(block_text)
    if not match:
        return []

    inline_value = match.group(1).strip()
    values: list[str] = []
    if inline_value and inline_value.upper() != "TBD":
        values.extend(part.strip().strip("`") for part in inline_value.split(",") if part.strip())
        return values

    lines = block_text.splitlines()
    target_idx = None
    for i, line in enumerate(lines):
        if TASK_TARGET_FILES_LINE_RE.match(line):
            target_idx = i
            break
    if target_idx is None:
        return values

    for line in lines[target_idx + 1:]:
        if METADATA_FIELD_LINE_RE.match(line):
            break
        bullet_match = re.match(r"^\s{2,}-\s+`?([^`]+?)`?\s*$", line)
        if bullet_match:
            values.append(bullet_match.group(1).strip())
    return values


def _validate_patch_quality_rules(ledger_md: str) -> list[str]:
    errors: list[str] = []
    for task_id, block_line, block_text in _extract_task_blocks(ledger_md):
        task_class_match = TASK_CLASS_LINE_RE.search(block_text)
        if not task_class_match or task_class_match.group(1).strip().upper() != "PATCH":
            continue

        priority_match = TASK_PRIORITY_LINE_RE.search(block_text)
        priority = priority_match.group(1).strip().upper() if priority_match else ""
        if priority not in {"P0", "P1"}:
            continue

        patch_ready_match = TASK_PATCH_READY_LINE_RE.search(block_text)
        patch_ready = patch_ready_match.group(1).strip().lower() if patch_ready_match else ""
        if patch_ready != "yes":
            continue

        branch_match = TASK_ACTIVE_BRANCH_LINE_RE.search(block_text)
        branch_value = branch_match.group(1).strip() if branch_match else ""
        if _is_blank_or_tbd(branch_value):
            errors.append(
                f"AGENT_TASK_LEDGER.md:{block_line}: {task_id}: [PATCH-QUALITY] Active Branch must not be blank/TBD for patch-ready P0/P1 PATCH tasks"
            )

        target_match = TASK_TARGET_FILES_LINE_RE.search(block_text)
        target_value = target_match.group(1).strip() if target_match else ""
        target_values = _extract_target_file_values(block_text)
        if _is_blank_or_tbd(target_value) and not target_values:
            errors.append(
                f"AGENT_TASK_LEDGER.md:{block_line}: {task_id}: [PATCH-QUALITY] Target Files must not be blank/TBD for patch-ready P0/P1 PATCH tasks"
            )
        elif not any(_looks_like_file_path(candidate) for candidate in target_values):
            errors.append(
                f"AGENT_TASK_LEDGER.md:{block_line}: {task_id}: [PATCH-QUALITY] Target Files must contain at least one valid-looking path"
            )

        min_verif_match = TASK_MIN_VERIF_LINE_RE.search(block_text)
        min_verif_value = min_verif_match.group(1).strip() if min_verif_match else ""
        if _is_blank_or_tbd(min_verif_value):
            errors.append(
                f"AGENT_TASK_LEDGER.md:{block_line}: {task_id}: [PATCH-QUALITY] Minimum Verification must not be blank/TBD for patch-ready P0/P1 PATCH tasks"
            )
        if MIN_VERIF_PLACEHOLDER_RE.search(min_verif_value):
            errors.append(
                f"AGENT_TASK_LEDGER.md:{block_line}: {task_id}: [PATCH-QUALITY] Minimum Verification must not use placeholder text (<...> or ...)"
            )

    return errors


def _normalize_status_token(raw_status: str) -> str:
    text = str(raw_status or "").strip()
    if not text:
        return ""
    cleaned = text.strip("`* ").upper()
    token = re.match(r"([A-Z_]+)\b", cleaned)
    return token.group(1) if token else ""


def _validate_primary_task_statuses(ledger_md: str) -> list[str]:
    errors: list[str] = []
    matches = list(PRIMARY_TASK_HEADER_RE.finditer(str(ledger_md or "")))
    for index, match in enumerate(matches):
        task_id = match.group(1)
        block_start = match.start()
        block_end = matches[index + 1].start() if index + 1 < len(matches) else len(ledger_md)
        block_text = ledger_md[block_start:block_end]
        block_line = ledger_md.count("\n", 0, block_start) + 1

        patch_ready_match = TASK_PATCH_READY_LINE_RE.search(block_text)
        patch_ready_value = patch_ready_match.group(1).strip().lower() if patch_ready_match else ""
        requires_status = patch_ready_value == "yes"

        status_match = TASK_STATUS_LINE_RE.search(block_text)
        if not status_match:
            if requires_status:
                errors.append(f"AGENT_TASK_LEDGER.md:{block_line}: {task_id}: missing Status:")
            continue

        status_line = block_line + block_text.count("\n", 0, status_match.start())
        raw_status = status_match.group(1)
        status_token = _normalize_status_token(raw_status)
        if status_token not in ALLOWED_STATUSES:
            errors.append(
                f"AGENT_TASK_LEDGER.md:{status_line}: {task_id}: illegal Status: {raw_status.strip()}"
            )

    return errors


def _validate_active_patch_metadata(ledger_md: str) -> list[str]:
    errors: list[str] = []
    matches = list(PRIMARY_TASK_HEADER_RE.finditer(str(ledger_md or "")))
    for index, match in enumerate(matches):
        task_id = match.group(1)
        block_start = match.start()
        block_end = matches[index + 1].start() if index + 1 < len(matches) else len(ledger_md)
        block_text = ledger_md[block_start:block_end]
        block_line = ledger_md.count("\n", 0, block_start) + 1

        status_match = TASK_STATUS_LINE_RE.search(block_text)
        status_raw = status_match.group(1).strip() if status_match else ""
        status = _normalize_status_token(status_raw)

        if status in ("RESOLVED", "DEFERRED"):
            continue

        class_match = TASK_CLASS_LINE_RE.search(block_text)
        task_class = class_match.group(1).strip().upper() if class_match else ""

        if task_class == "PATCH":
            if not TASK_ACTIVE_BRANCH_LINE_RE.search(block_text):
                errors.append(f"AGENT_TASK_LEDGER.md:{block_line}: {task_id}: active PATCH missing Active Branch:")
            if not TASK_PATCH_READY_LINE_RE.search(block_text):
                errors.append(f"AGENT_TASK_LEDGER.md:{block_line}: {task_id}: active PATCH missing Patch Ready:")
            if not TASK_MIN_VERIF_LINE_RE.search(block_text):
                errors.append(f"AGENT_TASK_LEDGER.md:{block_line}: {task_id}: active PATCH missing Minimum Verification:")

        # Contradictory routing checks
        gemini_first_match = TASK_GEMINI_FIRST_LINE_RE.search(block_text)
        gemini_first = gemini_first_match.group(1).strip().lower() if gemini_first_match else ""
        
        gemini_output_match = TASK_GEMINI_OUTPUT_RE_LINE_RE.search(block_text)
        gemini_output = gemini_output_match.group(1).strip().lower() if gemini_output_match else ""

        if gemini_first == "no" and gemini_output:
            if any(kw in gemini_output for kw in ("diagnosis", "sync", "complete", "plan")):
                errors.append(
                    f"AGENT_TASK_LEDGER.md:{block_line}: {task_id}: contradictory routing (Gemini First: no BUT Gemini Output Required: {gemini_output})"
                )

    return errors


def validate() -> list[str]:
    errors: list[str] = []
    dirty = _git_porcelain()
    errors.extend(_validate_static_scan_scope())
    errors.extend(_validate_no_sys_path_mutation())
    errors.extend(_validate_namespace_import_drift())

    if not SYNC_YAML.exists():
        errors.append("Missing agent_sync.yaml")
    else:
        try:
            sync_cfg = yaml.safe_load(_read(SYNC_YAML)) or {}
        except yaml.YAMLError as exc:
            errors.append(f"agent_sync.yaml: invalid YAML: {exc}")
            sync_cfg = {}
        if not isinstance(sync_cfg, dict):
            errors.append("agent_sync.yaml: root must be a mapping/object")
            sync_cfg = {}
        if int(sync_cfg.get("version", 0)) < 1:
            errors.append("agent_sync.yaml: missing or invalid version")
        for key in ("lock_policy", "entrypoint_policy", "evidence_policy"):
            if key not in sync_cfg:
                errors.append(f"agent_sync.yaml: missing required key '{key}'")

        schema_report = validate_agent_sync(path=SYNC_YAML, strict=True)
        if not schema_report.get("valid", False):
            for schema_error in schema_report.get("errors", []):
                errors.append(f"agent_sync.yaml schema: {schema_error}")

    sync_md = _read(SYNC_MD)
    ledger_md = _read(LEDGER_MD)

    if "Governance Validation Gate (P0)" not in sync_md:
        errors.append("AGENT_SYNC.md: missing Governance Validation Gate")
    if "Agent Lock Contract (P0)" not in sync_md:
        errors.append("AGENT_SYNC.md: missing Agent Lock Contract")

    header_ids = PRIMARY_TASK_HEADER_RE.findall(ledger_md)
    dupes = sorted([tid for tid, count in Counter(header_ids).items() if count > 1])
    if dupes:
        errors.append(f"AGENT_TASK_LEDGER.md: duplicate task IDs: {', '.join(dupes)}")

    errors.extend(_validate_primary_task_statuses(ledger_md))
    errors.extend(_validate_active_patch_metadata(ledger_md))
    errors.extend(_validate_evidence_paths(ledger_md))
    errors.extend(_validate_tmp_path_extensions(sync_md, dirty))
    errors.extend(_validate_ledger_resolved_section(ledger_md))
    errors.extend(_validate_patch_quality_rules(ledger_md))

    critical = {"AGENT_SYNC.md", "AGENT_TASK_LEDGER.md", "agent_sync.yaml"}
    for line in dirty:
        if len(line) < 3:
            continue
        status_code = line[:2]
        path = _parse_git_status_path(line)
        if path in critical:
            # Allow staged only ('M ', 'A ', etc.)
            # Block if second char is not ' ' (unstaged) or if untracked '??'
            if status_code[1] != ' ' or status_code == '??':
                errors.append(f"Critical governance file has unstaged or untracked changes: {line}")

    return errors

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args()

    errors = validate()
    print(json.dumps({"ok": not errors, "errors": errors}, indent=2))
    return 2 if errors and args.strict else 0

if __name__ == "__main__":
    raise SystemExit(main())
