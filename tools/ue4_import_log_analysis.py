r"""Deterministic UE4.26 / CARLA import-log analyzer.

This is the authoritative measurement instrument for the import hardening work.
Every before/after number in reports/ue4_hardening/ must come from here, so that
baseline and hardened runs are measured by identical code.

Design rules
------------
1. Deterministic. Same bytes in, same JSON out. No wall-clock, no randomness.
2. Lossless categories. Every warning line lands in exactly one category, and
   the category totals sum back to the warning total. If they do not, the report
   says so rather than quietly absorbing the difference into OTHER.
3. Evidence, not inference. Message formats were taken from the real log; see
   ``CATEGORY_PATTERNS`` for the exact text matched.
4. Percentiles are computed with a stated method (linear interpolation on the
   sorted sample), not an approximation.

Usage
-----
    from tools.ue4_import_log_analysis import analyze_file
    metrics = analyze_file(r"G:\CARLA\build_logs\ingolstadt_import_X.log")
"""
from __future__ import annotations

import math
import os
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any, Iterable

# ---------------------------------------------------------------------------
# Line shape
# ---------------------------------------------------------------------------
# [2026.10.04-17.03.26:285][  0]LogStaticMesh: Warning: some message
#
# The verbosity token is matched generically rather than from a fixed list: UE4
# emits tokens beyond Display/Warning/Error/Fatal/Verbose (for example
# "Success"), and a closed alternation silently dropped those lines as
# unparsed -- including the commandlet success marker that decides whether the
# run completed.
LINE_RE = re.compile(
    r"^\[(?P<ts>\d{4}\.\d{2}\.\d{2}-\d{2}\.\d{2}\.\d{2}:\d{3})\]"
    r"\[(?P<frame>[^\]]*)\]"
    r"(?P<category>[A-Za-z0-9_]+):\s*"
    r"(?P<verbosity>[A-Za-z]+):\s*"
    r"(?P<message>.*)$"
)

# ---------------------------------------------------------------------------
# Categories
# ---------------------------------------------------------------------------
CATEGORIES = (
    "FATAL",
    "ASSERTION",
    "SHADER_COMPILATION",
    "SHADER_WORKER",
    "DISTANCE_FIELD",
    "STATIC_MESH_REBUILD",
    "GEOMETRY_DEGENERACY",
    "TANGENT_BINORMAL",
    "SMOOTHING_GROUP",
    "UV",
    "ASSET_MANAGER_DUPLICATE",
    "ASSET_RESOLUTION",
    "CONSOLE_LOOKUP_PERFORMANCE",
    "DDC",
    "IO",
    "OTHER",
)

# ASSET_RESOLUTION is an addition beyond the categories named in the task spec.
# It exists because 5,720 "Failed to find object" warnings were otherwise being
# absorbed into OTHER, which made the category useless for prioritization. The
# spec's list is treated as a floor, not a ceiling.

# Ordered: first match wins, so put specific patterns before generic ones.
CATEGORY_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("FATAL", re.compile(r"\bFatal error\b|\bAssertion failed\b|Unhandled Exception", re.I)),
    ("ASSERTION", re.compile(r"Assertion failed|ensure condition failed", re.I)),
    ("DISTANCE_FIELD", re.compile(
        r"Main thread blocked for .*async distance field build", re.I)),
    ("CONSOLE_LOOKUP_PERFORMANCE", re.compile(
        r"Performance warning: Console object named .*FindConsoleObject\(\) calls", re.I)),
    ("SMOOTHING_GROUP", re.compile(
        r"No smoothing group information was found in this FBX scene", re.I)),
    ("TANGENT_BINORMAL", re.compile(
        r"has degenerate tangent bases|has some nearly zero bi-normals", re.I)),
    ("GEOMETRY_DEGENERACY", re.compile(
        r"degenerate (triangle|face|polygon)|zero area|has no valid triangles", re.I)),
    ("UV", re.compile(r"\bUV\b.*(invalid|out of range|overlap)", re.I)),
    ("ASSET_MANAGER_DUPLICATE", re.compile(
        r"Found Duplicate PrimaryAssetID|must be resolved before saving", re.I)),
    ("ASSET_RESOLUTION", re.compile(
        r"Failed to find object|Failed to load|Failed to find package|"
        r"Can't find file|Cannot find", re.I)),
    ("DDC", re.compile(
        r"LogDerivedDataCache|DerivedDataCache|Boot\.ddc|DDC ", re.I)),
    ("SHADER_WORKER", re.compile(r"Worker \(\d+/\d+\): shaders left to compile", re.I)),
    ("SHADER_COMPILATION", re.compile(
        r"LogShaderCompilers|shaders? left to compile|shaders? compiled|"
        r"Compiling \d+ shaders", re.I)),
    ("STATIC_MESH_REBUILD", re.compile(
        r"rebuild(?:ing)? (?:the )?(?:static )?mesh|is being rebuilt", re.I)),
    ("IO", re.compile(r"LogIO|ReadFile|WriteFile|I/O error|disk full", re.I)),
)

# ---------------------------------------------------------------------------
# Specific extractors
# ---------------------------------------------------------------------------
RE_DF_BLOCK = re.compile(
    r"Main thread blocked for (?P<secs>[0-9]+(?:\.[0-9]+)?)s for async distance "
    r"field build of (?P<mesh>.+?) to complete", re.I)

RE_SHADER_WORKER = re.compile(
    r"Worker \((?P<worker>\d+)/(?P<workers>\d+)\): shaders left to compile "
    r"(?P<remaining>\d+)")

RE_SHADER_TOTAL = re.compile(
    r"LogShaderCompilers:\s*\w+:\s*(?P<kind>Compiling|Finished compiling)\s+"
    r"(?P<count>\d+)\s+shaders?", re.I)

RE_TANGENT = re.compile(r"^(?P<mesh>\S+) has degenerate tangent bases")
RE_BINORMAL = re.compile(r"^(?P<mesh>\S+) has some nearly zero bi-normals")
RE_SMOOTHING = re.compile(r"No smoothing group information was found in this FBX scene")
RE_DUPID = re.compile(
    r"Found Duplicate PrimaryAssetID\s+(?P<pid>\S+?),\s*this must be resolved before "
    r"saving\.\s*Path\s+(?P<replacing>\S+)\s+is replacing path\s+(?P<replaced>\S+)")

RE_CONSOLE_LOOKUP = re.compile(
    r"Console object named '(?P<name>[^']+)' shows many \((?P<count>\d+)\) "
    r"FindConsoleObject\(\) calls")

RE_MISSING_OBJECT = re.compile(
    r"Failed to find object 'Object (?P<path>[^']+)'")

# Ingolstadt mesh names look like Ingolstadt_Tile_10_9_Building_Kita_Am_Blumenviertel
RE_TILE_MESH = re.compile(r"Ingolstadt_Tile_(?P<tx>\d+)_(?P<ty>\d+)_(?P<mesh>.+)$")

# Anchored to the time component after the date separator: the stamp is
# "YYYY.MM.DD-HH.MM.SS:mmm", so the hour follows the '-' directly.
RE_TS = re.compile(r"-(?P<h>\d{2})\.(?P<m>\d{2})\.(?P<s>\d{2}):")


def parse_timestamp(ts: str) -> float:
    """Seconds since midnight from a UE log stamp ``YYYY.MM.DD-HH.MM.SS:mmm``.

    The time part must be anchored *after* the date, otherwise the regex
    matches inside the date ("20.26.10" out of "2026.10.04") and every stamp in
    one log collapses to the same value, silently zeroing every duration.
    """
    m = RE_TS.search(ts)
    if not m:
        return 0.0
    return int(m.group("h")) * 3600 + int(m.group("m")) * 60 + int(m.group("s"))


def percentile(values: list[float], pct: float) -> float:
    """Linear-interpolation percentile. ``pct`` in 0..100."""
    if not values:
        return 0.0
    xs = sorted(values)
    if len(xs) == 1:
        return float(xs[0])
    k = (len(xs) - 1) * (pct / 100.0)
    lo = math.floor(k)
    hi = math.ceil(k)
    if lo == hi:
        return float(xs[int(k)])
    return float(xs[lo] + (xs[hi] - xs[lo]) * (k - lo))


# ---------------------------------------------------------------------------
# Result container
# ---------------------------------------------------------------------------
@dataclass
class LogMetrics:
    path: str = ""
    size_bytes: int = 0
    total_lines: int = 0
    parsed_lines: int = 0
    unparsed_lines: int = 0
    verbosity_counts: dict[str, int] = field(default_factory=dict)
    category_counts: dict[str, int] = field(default_factory=dict)
    warning_total: int = 0
    category_totals_sum: int = 0
    unclassified_warning_lines: int = 0

    first_timestamp: str = ""
    last_timestamp: str = ""
    duration_seconds: float = 0.0

    distance_field_blocks: list[dict[str, Any]] = field(default_factory=list)
    shader_worker_samples: list[int] = field(default_factory=list)
    shader_worker_denominators: set[int] = field(default_factory=set)
    shader_queue_first: int | None = None
    shader_queue_last: int | None = None
    shader_queue_min: int | None = None
    shader_progression: list[dict[str, Any]] = field(default_factory=list)
    shader_compile_events: list[dict[str, Any]] = field(default_factory=list)

    tangent_meshes: list[str] = field(default_factory=list)
    binormal_meshes: list[str] = field(default_factory=list)
    smoothing_warning_count: int = 0

    duplicate_primary_asset_ids: list[dict[str, Any]] = field(default_factory=list)

    console_lookup_warnings: list[dict[str, Any]] = field(default_factory=list)
    missing_object_paths: list[str] = field(default_factory=list)

    per_tile: dict[str, dict[str, int]] = field(default_factory=dict)
    per_mesh: dict[str, dict[str, int]] = field(default_factory=dict)

    terminal_state: str = "UNDETERMINED"
    termination_evidence: list[str] = field(default_factory=list)
    success_marker_line_number: int | None = None
    duplicate_id_total_all_verbosities: int = 0
    missing_object_unique_paths: int = 0

    def to_dict(self) -> dict[str, Any]:
        d = self.__dict__.copy()
        d["shader_worker_denominators"] = sorted(self.shader_worker_denominators)
        return d


# ---------------------------------------------------------------------------
# Analyzer
# ---------------------------------------------------------------------------
def classify(category: str, verbosity: str, message: str) -> str:
    if verbosity in ("Fatal",) or re.search(r"Fatal error", message, re.I):
        return "FATAL"
    for name, pat in CATEGORY_PATTERNS:
        if pat.search(message) or pat.search(category + ": " + message):
            return name
    return "OTHER"


def _bump(d: dict[str, int], key: str, n: int = 1) -> None:
    d[key] = d.get(key, 0) + n


def analyze_lines(lines: Iterable[str], *, path: str = "", size_bytes: int = 0) -> LogMetrics:
    m = LogMetrics(path=path, size_bytes=size_bytes)
    cat_counts: Counter = Counter()
    verb_counts: Counter = Counter()
    per_tile: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    per_mesh: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    dup_pid_counter: Counter = Counter()
    last_queue: dict[int, int] = {}

    for raw in lines:
        m.total_lines += 1
        line = raw.rstrip("\n").rstrip("\r")
        mt = LINE_RE.match(line)
        if not mt:
            m.unparsed_lines += 1
            continue
        m.parsed_lines += 1
        ts = mt.group("ts")
        cat = mt.group("category")
        verb = mt.group("verbosity")
        msg = mt.group("message")

        if not m.first_timestamp:
            m.first_timestamp = ts
        m.last_timestamp = ts
        verb_counts[verb] += 1

        if verb == "Fatal":
            m.termination_evidence.append("Fatal verbosity: " + msg[:200])
        for marker, label in (
            ("Engine exit requested", "engine exit requested"),
            ("RequestExit", "RequestExit"),
            ("LogExit: Exiting", "LogExit"),
            ("Fatal error", "fatal error"),
            ("Assertion failed", "assertion failed"),
            ("Success - 0 error", "commandlet success marker"),
            ("ImportAssetsCommandlet", "commandlet named"),
        ):
            if marker in line and label not in [e.split(":")[0] for e in m.termination_evidence]:
                m.termination_evidence.append(label + ": " + msg[:200])
                if label == "commandlet success marker" and \
                        m.success_marker_line_number is None:
                    m.success_marker_line_number = m.total_lines

        is_warningish = verb in ("Warning", "Error", "Fatal")
        category = classify(cat, verb, msg)
        if is_warningish:
            m.warning_total += 1
            cat_counts[category] += 1

        # ---- distance field ----
        md = RE_DF_BLOCK.search(msg)
        if md:
            entry = {
                "seconds": float(md.group("secs")),
                "mesh": md.group("mesh").strip(),
                "timestamp": ts,
                "timestamp_seconds": parse_timestamp(ts),
            }
            m.distance_field_blocks.append(entry)
            per_mesh[entry["mesh"]]["distance_field_stall"] += 1

        # ---- shaders ----
        mw = RE_SHADER_WORKER.search(msg)
        if mw:
            remaining = int(mw.group("remaining"))
            m.shader_worker_samples.append(remaining)
            m.shader_worker_denominators.add(int(mw.group("workers")))
            last_queue[int(mw.group("worker"))] = remaining
            if m.shader_queue_first is None:
                m.shader_queue_first = remaining
            m.shader_queue_last = remaining
            m.shader_queue_min = (remaining if m.shader_queue_min is None
                                  else min(m.shader_queue_min, remaining))
            per_mesh["__shaders__"]["queue_sample"] += 1

        mtot = RE_SHADER_TOTAL.search(msg)
        if mtot:
            m.shader_compile_events.append({
                "kind": mtot.group("kind"),
                "count": int(mtot.group("count")),
                "timestamp": ts,
                "timestamp_seconds": parse_timestamp(ts),
            })

        # ---- geometry warnings ----
        mtan = RE_TANGENT.search(msg)
        if mtan:
            name = mtan.group("mesh")
            m.tangent_meshes.append(name)
            per_mesh[name]["tangent_degenerate"] += 1
        mbin = RE_BINORMAL.search(msg)
        if mbin:
            name = mbin.group("mesh")
            m.binormal_meshes.append(name)
            per_mesh[name]["binormal_nearly_zero"] += 1
        if RE_SMOOTHING.search(msg):
            m.smoothing_warning_count += 1

        # ---- duplicate primary asset id ----
        mdup = RE_DUPID.search(msg)
        if mdup:
            pid = mdup.group("pid")
            rec = {
                "primary_asset_id": pid,
                "replacing_path": mdup.group("replacing"),
                "replaced_path": mdup.group("replaced"),
                "timestamp": ts,
            }
            m.duplicate_primary_asset_ids.append(rec)
            dup_pid_counter[pid] += 1

        # ---- console lookup ----
        mcl = RE_CONSOLE_LOOKUP.search(msg)
        if mcl:
            m.console_lookup_warnings.append({
                "name": mcl.group("name"),
                "count": int(mcl.group("count")),
                "timestamp": ts,
            })

        # ---- missing objects ----
        mmo = RE_MISSING_OBJECT.search(msg)
        if mmo:
            m.missing_object_paths.append(mmo.group("path"))

        # ---- per tile / per mesh ----
        if is_warningish and cat not in ("OTHER",):
            for token in re.findall(r"Ingolstadt_Tile_\d+_\d+", msg):
                _bump(per_tile[token], category)

    m.category_counts = {c: cat_counts.get(c, 0) for c in CATEGORIES}
    m.verbosity_counts = dict(sorted(verb_counts.items()))
    m.category_totals_sum = sum(cat_counts.values())
    m.unclassified_warning_lines = m.warning_total - m.category_totals_sum

    m.per_tile = {k: dict(sorted(v.items())) for k, v in sorted(per_tile.items())}
    m.per_mesh = {k: dict(sorted(v.items())) for k, v in sorted(per_mesh.items())}

    # shader progression: downsample to keep the report small but keep endpoints
    prog = sorted(last_queue.items())
    m.shader_progression = [
        {"worker": w, "remaining": r} for w, r in prog[:5]
    ] + ([{"worker": "mid", "remaining": None}] if len(prog) > 10 else []) + \
        [{"worker": w, "remaining": r} for w, r in prog[-5:]]

    secs = [b["seconds"] for b in m.distance_field_blocks]
    if m.first_timestamp and m.last_timestamp:
        m.duration_seconds = round(
            parse_timestamp(m.last_timestamp) - parse_timestamp(m.first_timestamp), 3)
        if m.duration_seconds < 0:      # crossed midnight
            m.duration_seconds += 86400

    # terminal state
    #
    # A "Success" substring anywhere in the log is NOT proof of completion: this
    # pipeline logs "Success" during intermediate phases too. Completion is only
    # claimed when the success marker appears at (or within a few lines of) the
    # end of file. Otherwise the run is reported as unterminated, which is the
    # honest description of a log that simply stops mid-stream.
    tail = [e for e in m.termination_evidence]
    success_seen = any("commandlet success marker" in e for e in tail)
    if any("fatal error" in e.lower() or "Fatal verbosity" in e for e in tail):
        m.terminal_state = "FAILED_FATAL"
    elif any("assertion failed" in e.lower() for e in tail):
        m.terminal_state = "FAILED_ASSERTION"
    elif success_seen and m.success_marker_line_number and \
            m.total_lines - m.success_marker_line_number <= 5:
        m.terminal_state = "COMPLETED_SUCCESS"
    elif success_seen:
        m.terminal_state = "SUCCESS_MARKER_MIDSTREAM_NOT_TERMINAL"
    elif any("commandlet named" in e or "engine exit requested" in e or "RequestExit" in e
             for e in tail):
        m.terminal_state = "COMPLETED_NO_SUCCESS_MARKER"
    else:
        m.terminal_state = "TRUNCATED_NO_TERMINATION_MARKER"

    # attach stats helper
    m.distance_field_stats = {  # type: ignore[attr-defined]
        "count": len(secs),
        "total_seconds": round(sum(secs), 3),
        "max_seconds": round(max(secs), 3) if secs else 0.0,
        "p50_seconds": round(percentile(secs, 50), 3),
        "p95_seconds": round(percentile(secs, 95), 3),
        "p99_seconds": round(percentile(secs, 99), 3),
        "over_10s": sum(1 for s in secs if s > 10),
        "over_60s": sum(1 for s in secs if s > 60),
        "over_300s": sum(1 for s in secs if s > 300),
        "sorted_desc": [round(s, 3) for s in sorted(secs, reverse=True)],
        "total_hours": round(sum(secs) / 3600.0, 3),
        "worst_mesh": max(
            m.distance_field_blocks, key=lambda b: b["seconds"])["mesh"]
        if m.distance_field_blocks else None,
    }
    m.duplicate_id_total_all_verbosities = len(m.duplicate_primary_asset_ids)
    m.missing_object_unique_paths = len(set(m.missing_object_paths))
    return m


def analyze_file(path: str | os.PathLike) -> LogMetrics:
    path = str(path)
    size = os.path.getsize(path)
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        return analyze_lines(fh, path=path, size_bytes=size)