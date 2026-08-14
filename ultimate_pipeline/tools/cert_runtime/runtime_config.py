from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Optional

from phase_q.common import PROJECT_ROOT, make_run_id
from tools.verify_candidate_digest import sha256_file

BASE_REPORTS_DIR = PROJECT_ROOT / "reports" / "post_audit_hardening"
DEFAULT_CANDIDATE_XODR = (
    PROJECT_ROOT
    / "campaigns"
    / "ingolstadt_cooked_perception_v1"
    / "candidate"
    / "ingolstadt_perception_final_repaired.xodr"
)


@dataclass(frozen=True)
class CertRuntimeConfig:
    candidate_xodr: Path
    run_id: str
    phase_l_dir: Path
    p4_dir: Path


def _coerce_path(value: Any) -> Optional[Path]:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    return Path(text)


def _infer_run_id(path: Optional[Path]) -> Optional[str]:
    if path is None:
        return None
    name = path.name
    if name.endswith("_P4_RUNTIME_EQUIVALENCE"):
        return name[: -len("_P4_RUNTIME_EQUIVALENCE")]
    return name or None


def resolve_cert_runtime_config(
    *,
    candidate_xodr: Any = None,
    run_id: Any = None,
    phase_l_dir: Any = None,
    p4_dir: Any = None,
    env: Mapping[str, str] | None = None,
) -> CertRuntimeConfig:
    env_map = os.environ if env is None else env

    candidate = (
        _coerce_path(candidate_xodr)
        or _coerce_path(env_map.get("UP_CERT_CANDIDATE_XODR"))
        or DEFAULT_CANDIDATE_XODR
    )

    phase_l_path = _coerce_path(phase_l_dir) or _coerce_path(env_map.get("UP_CERT_PHASE_L_DIR"))
    p4_path = _coerce_path(p4_dir) or _coerce_path(env_map.get("UP_CERT_P4_DIR"))

    run_id_text = str(run_id).strip() if run_id is not None else ""
    if not run_id_text:
        run_id_text = str(env_map.get("UP_CERT_RUNID", "")).strip()
    if not run_id_text:
        run_id_text = _infer_run_id(phase_l_path) or _infer_run_id(p4_path) or make_run_id()

    if phase_l_path is None:
        phase_l_path = BASE_REPORTS_DIR / run_id_text
    if p4_path is None:
        p4_path = BASE_REPORTS_DIR / f"{run_id_text}_P4_RUNTIME_EQUIVALENCE"

    return CertRuntimeConfig(
        candidate_xodr=candidate,
        run_id=run_id_text,
        phase_l_dir=phase_l_path,
        p4_dir=p4_path,
    )


def assert_candidate_consistency(
    *,
    p4_rep_sha256: str | None,
    phase_l_l2_sha256: str | None,
    candidate_xodr: os.PathLike[str] | str,
) -> str:
    candidate_path = Path(candidate_xodr)
    candidate_sha256 = sha256_file(candidate_path)
    evidence = {
        "p4_rep_sha256": p4_rep_sha256,
        "phase_l_l2_sha256": phase_l_l2_sha256,
        "candidate_xodr": str(candidate_path),
        "candidate_sha256": candidate_sha256,
    }

    mismatches = []
    if not p4_rep_sha256:
        mismatches.append("p4 rep_sha256 missing")
    if not phase_l_l2_sha256:
        mismatches.append("phase_l L2 sha256 missing")
    if p4_rep_sha256 and phase_l_l2_sha256 and p4_rep_sha256 != phase_l_l2_sha256:
        mismatches.append("p4 rep_sha256 != phase_l L2 sha256")
    if phase_l_l2_sha256 and candidate_sha256 != phase_l_l2_sha256:
        mismatches.append("candidate sha256 != phase_l L2 sha256")
    if p4_rep_sha256 and candidate_sha256 != p4_rep_sha256:
        mismatches.append("candidate sha256 != p4 rep_sha256")

    if mismatches:
        raise RuntimeError(
            "candidate consistency preflight failed: {} | {}".format(
                "; ".join(mismatches), evidence
            )
        )

    return candidate_sha256

