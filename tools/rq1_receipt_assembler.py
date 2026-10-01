#!/usr/bin/env python3
"""
Receipt assembler for the RQ1 determinism matrix.

Builds an ``rq1_run_receipt/v1`` receipt from a pipeline trial-run
output directory.

Stage identity
--------------
A stage artifact is named ``<stage_name>_<run_timestamp>.xodr`` by
``Settings.stage_path`` (``ultimate_pipeline/config/settings.py``), e.g.
``03_topology_20261001_042523_540218.xodr``.

The previous version keyed artifacts on the leading two digits only.  That
collides, because two distinct stages share the ``06`` prefix:
``06_continuity`` and ``06_geometry_frozen``.  Both map to the single key
``"6"`` and whichever one ``os.listdir`` happened to yield last silently won,
so a receipt could describe an artifact the pipeline never produced.  This
module keys on the full ``<NN>_<name>`` stage identity instead.

Duplicate detection
-------------------
``_step6_governed_containment`` / ``_run_stage6_read_only_diagnostic`` in
``ultimate_pipeline/pipeline_stages/stage_06_links.py`` run under
``THESIS_STRICT`` and emit ``05_planview`` via ``shutil.copy2`` of the
stage-03 topology output.  ``copy2`` also preserves mtime, so the stage-03 and
stage-05 artifacts are byte-identical *and* mtime-identical.  That is
expected read-only behavior, not a hashing defect or evidence of tampering.
This module records such pairs explicitly (``duplicate_of`` plus
``metadata_preserving_copy``) instead of leaving a reviewer to infer them from
two identical hash lines.

Usage
-----
    python tools/rq1_receipt_assembler.py <run_index> <run_output_base_dir>

``<run_output_base_dir>`` is ``reports/rq1_trial_runs/run_XX``; the most
recent ``YYYYMMDD_HHMMSS_*`` subdirectory is selected.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

SCHEMA = "rq1_run_receipt/v2"

# Pipeline execution order of every stage artifact this assembler understands.
# Two artifacts share the "06" prefix; the order below keeps them distinct and
# establishes which one is the later (terminal) artifact of that step.
STAGE_ORDER: tuple[str, ...] = (
    "01_sanitized",
    "02_sumo_fixed",
    "03_topology",
    "04_elevation",
    "05_planview",
    "06_continuity",
    "06_geometry_frozen",
    "07_lanes",
    "08_final",
)

_RUN_STAMP = re.compile(r"^(\d{2}_[A-Za-z0-9]+(?:_[A-Za-z0-9]+)*)_\d{8}_\d{6}_[0-9]+\.xodr$")
_RUN_DIR = re.compile(r"^\d{8}_\d{6}_\d+$")


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def stage_identity(fname: str) -> str | None:
    """Return the full ``<NN>_<name>`` stage identity for an artifact filename.

    ``None`` when the name does not carry a run timestamp, i.e. it was not
    produced by ``Settings.stage_path`` and has no verifiable stage identity.
    """
    m = _RUN_STAMP.match(fname)
    if m:
        return m.group(1)
    return None


def _order_key(stage_name: str) -> tuple[int, int]:
    """Sort key placing known stages in pipeline order, unknowns last."""
    if stage_name in STAGE_ORDER:
        return (STAGE_ORDER.index(stage_name), 0)
    head = stage_name[:2]
    return (int(head) if head.isdigit() else 99, 1)


def _summarize_xodr(path: Path) -> dict[str, Any]:
    """Structural signature for an XODR artifact.

    ``num_junctions`` here counts *roads carrying a junction reference*, which
    is what ``xodr_structural_summary.summarize_xodr`` returns.  It is NOT the
    count of ``<junction>`` elements in the file; conflating the two previously
    made an unrelated legacy receipt look like a determinism mismatch.
    """
    try:
        from ultimate_pipeline.tools.xodr_structural_summary import summarize_xodr

        result = summarize_xodr(path)
        if isinstance(result, dict):
            return {
                "num_roads": result.get("road_count"),
                "num_junctions": result.get("junction_count"),
                "total_road_length": result.get("total_road_length_m"),
            }
    except Exception as exc:  # pragma: no cover - defensive
        return {"num_roads": None, "num_junctions": None, "total_road_length": None, "error": str(exc)}
    return {"num_roads": None, "num_junctions": None, "total_road_length": None}


def _topology_counts(sig: dict[str, Any]) -> dict[str, Any]:
    return {"junctions": sig.get("num_junctions"), "roads": sig.get("num_roads")}


def _pipeline_status(odir: Path) -> dict[str, Any]:
    """Read the run's own terminal status if the pipeline wrote one."""
    status_path = odir / "run_status.json"
    if not status_path.is_file():
        return {"recorded": False, "status": None, "stage": None, "error": None}
    try:
        data = json.loads(status_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"recorded": True, "status": None, "stage": None, "error": f"unparseable: {exc}"}
    tb = odir / "crash_traceback.txt"
    return {
        "recorded": True,
        "status": data.get("status"),
        "stage": data.get("stage"),
        "message": data.get("message"),
        "error": data.get("error"),
        "timestamp": data.get("timestamp"),
        "crash_traceback": tb.read_text(encoding="utf-8", errors="replace").strip()[-4000:] or None
        if tb.is_file()
        else None,
    }


def _collect_stage_files(odir: Path) -> tuple[dict[str, Path], list[str]]:
    """Map stage identity -> artifact path for every timestamped XODR.

    Returns the mapping plus the names that were skipped so an unrecognized
    artifact can never vanish from the evidence silently.
    """
    stage_files: dict[str, Path] = {}
    skipped: list[str] = []
    for path in sorted(odir.glob("*.xodr")):
        identity = stage_identity(path.name)
        if identity is None:
            skipped.append(path.name)
            continue
        if identity in stage_files:
            raise ValueError(
                f"two artifacts claim stage {identity!r} in {odir}: "
                f"{stage_files[identity].name} and {path.name}"
            )
        stage_files[identity] = path
    return stage_files, skipped


def assemble_receipt(run_index: int, out_dir: str | Path) -> dict[str, Any]:
    """Build an ``rq1_run_receipt/v2`` receipt from a pipeline run directory."""
    odir = Path(out_dir)
    if not odir.is_dir():
        raise FileNotFoundError(f"Output directory not found: {out_dir}")

    stage_files, skipped = _collect_stage_files(odir)
    ordered = sorted(stage_files, key=_order_key)

    completed_stages: dict[str, dict[str, Any]] = {}
    seen_sha: dict[str, str] = {}
    for stage_name in ordered:
        fpath = stage_files[stage_name]
        sha = _sha256_file(fpath)
        stat = fpath.stat()
        prior = seen_sha.get(sha)
        if prior is None:
            seen_sha[sha] = stage_name
        completed_stages[stage_name] = {
            "sha256": sha,
            "bytes": stat.st_size,
            "mtime": stat.st_mtime,
            "artifact": fpath.name,
            "duplicate_of": prior,
            # Identical bytes AND identical mtime is the shutil.copy2
            # signature produced by the stage-06 read-only diagnostic path.
            "metadata_preserving_copy": bool(prior is not None and completed_stages[prior]["mtime"] == stat.st_mtime),
        }

    terminal_stage = ordered[-1] if ordered else None
    terminal_path = stage_files[terminal_stage] if terminal_stage else None

    structural_signature: dict[str, Any] = {
        "num_roads": None,
        "num_junctions": None,
        "total_road_length": None,
    }
    topology_counts: dict[str, Any] = {"junctions": None, "roads": None}
    xodr_sha256: str | None = None
    output_path: str | None = None
    if terminal_path is not None:
        xodr_sha256 = completed_stages[terminal_stage]["sha256"]
        output_path = str(terminal_path)
        structural_signature = _summarize_xodr(terminal_path)
        topology_counts = _topology_counts(structural_signature)

    pipeline = _pipeline_status(odir)
    duplicate_pairs = [
        {"identical_sha256": entry["sha256"], "stages": [entry["duplicate_of"], name]}
        for name, entry in completed_stages.items()
        if entry["duplicate_of"] is not None
    ]

    return {
        "run": run_index,
        "schema": SCHEMA,
        "out_dir": str(odir),
        "run_dir_name": odir.name,
        "status": "INCOMPLETE",
        "pipeline_status": pipeline,
        "terminal_stage": terminal_stage,
        "completed_stages": completed_stages,
        "unattributed_artifacts": skipped,
        "byte_identical_stage_pairs": duplicate_pairs,
        "structural_signature": structural_signature,
        "structural_signature_stage": terminal_stage,
        "junction_metric": "roads_carrying_junction_reference",
        "topology_counts": topology_counts,
        "feature_counts": None,
        "output_path": output_path,
        # Populated by the matrix builder, never by the assembler: content
        # normalization is a separate, explicitly requested audit step.
        "normalized_xodr_sha256": None,
        "xodr_sha256": xodr_sha256,
        "input_xodr": None,
        "input_sha256": None,
        "tileset_digest": None,
        "map_acceptance_digest": None,
        "final_receipt_digest": None,
        "error": pipeline.get("error"),
        "duration_s": None,
    }


def _select_run_dir(out_base: Path) -> Path:
    if not out_base.is_dir():
        raise FileNotFoundError(f"Base dir not found: {out_base}")
    candidates = [d for d in out_base.iterdir() if d.is_dir() and _RUN_DIR.match(d.name)]
    if not candidates:
        raise FileNotFoundError(f"No timestamped run dirs found under {out_base}")
    return max(candidates, key=lambda d: d.name)


def main() -> int:
    parser = argparse.ArgumentParser(description="Assemble an RQ1 run receipt.")
    parser.add_argument("run_index", type=int)
    parser.add_argument("output_base_dir", type=Path, help="reports/rq1_trial_runs/run_XX")
    parser.add_argument("--run-dir", type=Path, default=None, help="exact run dir, skipping timestamp selection")
    parser.add_argument("--out", type=Path, default=None, help="receipt path (default: inside run dir)")
    parser.add_argument(
        "--artifacts-external",
        action="store_true",
        help=(
            "Declare that the stage artifacts were measured in place and are not committed to the "
            "repository. XODR artifacts exceed 100 MB each and are covered by the blanket *.xodr LFS "
            "rule, so the receipt is committed as the durable evidence while the measured artifacts stay "
            "on local disk."
        ),
    )
    args = parser.parse_args()

    run_dir = args.run_dir or _select_run_dir(args.output_base_dir)
    rec = assemble_receipt(args.run_index, run_dir)
    if args.artifacts_external:
        rec["artifact_provenance"] = {
            "artifacts_committed": False,
            "reason": "XODR stage artifacts are >100 MB each and governed by the blanket *.xodr LFS rule; they are measured in place, not committed",
            "measured_run_dir": str(run_dir.resolve()),
        }

    out_path = args.out
    if out_path is None:
        out_path = run_dir / f"receipt_run_{args.run_index:02d}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(rec, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    if not rec["completed_stages"]:
        print(f"WARNING: no stage artifacts found under {run_dir}; receipt records zero stages", file=sys.stderr)

    print(f"Receipt written to {out_path}")
    print(
        json.dumps(
            {
                "run": rec["run"],
                "terminal_stage": rec["terminal_stage"],
                "completed_stages": sorted(rec["completed_stages"]),
                "byte_identical_stage_pairs": rec["byte_identical_stage_pairs"],
                "pipeline_status": rec["pipeline_status"].get("status"),
                "xodr_sha256": rec["xodr_sha256"],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
