# ultimate_pipeline/ml/lane_gnn_refiner.py
"""Fail-closed entrypoint for the *unvalidated* lane-refinement feature.

This is NOT a trained or deployable GNN lane refiner. The separate domain-gap
GNN predicts embeddings, not validated OpenDRIVE geometry corrections. Until a
provenance-bound corrective checkpoint, geometry projection, hard-gate adapter,
and held-out validation exist, a request to refine must fail explicitly.

This deliberately preserves the historical `run_inplace` arguments but
never writes to the supplied XML tree or filesystem. A successful import or
an unconfigured opt-out must never be interpreted as ML refinement success.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import math
import re
from typing import Any


POLICY_VERSION = "lane-gnn-disabled-v1"
# A separate, reviewed implementation must change this constant only after
# satisfying all model, projection, rollback, and quality-gate requirements.
GNN_GEOMETRY_REFINEMENT_IMPLEMENTED = False


class LaneRefinementBlocked(RuntimeError):
    """An explicit non-success when model-backed refinement was requested."""

    def __init__(self, code: str, reason: str) -> None:
        self.code = code
        self.reason = reason
        super().__init__(f"{code}: {reason}")


@dataclass(frozen=True)
class LaneRefinementReceipt:
    """Non-authoritative, immutable receipt for an intentionally disabled run.

    ``ok`` and ``release_eligible`` are always false: a skipped GNN cannot
    satisfy a required release gate. Geometry/model digests are unset because
    neither a source artifact nor a checkpoint was actually evaluated.
    """

    status: str = "DISABLED"
    ok: bool = False
    applied: bool = False
    release_eligible: bool = False
    quality_gates_run: bool = False
    model_sha256: None = None
    geometry_before_sha256: None = None
    geometry_after_sha256: None = None
    policy_version: str = POLICY_VERSION
    reason: str = "No validated lane-correction checkpoint or inference engine is available"

    def __bool__(self) -> bool:
        """Prevent ``if receipt:`` from turning a skip into a success."""
        return False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class LaneGNNRefiner:
    """Compatibility entrypoint; only the disabled mode is supported."""

    @staticmethod
    def run_inplace(
        root: Any,
        model_path: str | None,
        device: str = "cpu",
        confidence_thresh: float = 0.7,
    ) -> LaneRefinementReceipt:
        """Never mutates *root*; rejects any requested checkpoint.

        A missing/empty model path means the optional stage was not selected,
        returning a clearly non-passing DISABLED receipt. Supplying any model
        path, including a whitespace path or PathLike object, raises rather
        than silently treating a stub as successful inference. No checkpoint
        deserialization, GPU access, XML serialization, network or file I/O
        occurs in either path. This also avoids untrusted ``torch.load``.

        This is a temporary safety boundary, NOT source-level GNN closure.
        """
        # Do not accept bool (an int subclass), NaN/Inf, or coerced strings.
        if type(confidence_thresh) not in (float, int) or not math.isfinite(confidence_thresh):
            raise LaneRefinementBlocked("INVALID_THRESHOLD", "confidence_thresh must be finite numeric")
        if not 0.0 <= confidence_thresh <= 1.0:
            raise LaneRefinementBlocked("INVALID_THRESHOLD", "confidence_thresh must lie in [0, 1]")
        if not isinstance(device, str) or not re.fullmatch(r"cpu|cuda(?::(?:0|[1-9][0-9]*))?", device):
            raise LaneRefinementBlocked("INVALID_DEVICE", "device must be cpu, cuda or cuda:<index>")

        if model_path is None or (isinstance(model_path, str) and model_path == ""):
            return LaneRefinementReceipt()

        # Fail before examining a path or the supplied XML tree. In particular
        # the old stub returned None here and printed a misleading message.
        raise LaneRefinementBlocked(
            "BLOCKED_MODEL_UNVALIDATED",
            "GNN geometry refinement is unavailable; model execution is prohibited",
        )
