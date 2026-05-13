# REFAC_VERSION = "v5_preserve"
# NOTE: This file is auto-extracted from ultimate_pipeline/main_pipeline.py.
# It delegates to original helpers by injecting main_pipeline globals at runtime.

from __future__ import annotations

def _inject_main_pipeline_globals():
    # Import is inside to avoid import-time side effects/cycles.
    from ultimate_pipeline import main_pipeline as _mp  # type: ignore
    g = globals()
    for k, v in _mp.__dict__.items():
        if k.startswith("__"):
            continue
        if k in ("_inject_main_pipeline_globals",):
            continue
        # Don't overwrite locally-defined names (e.g., stage functions).
        g.setdefault(k, v)


def _step1_sanitize(self, sanitized: str) -> None:
    _inject_main_pipeline_globals()
    s = self.settings
    print("\n============== 🧼 STEP 1: Sanitize ==============")

    ok = XODRSanitizer.sanitize_xodr(
        s.INPUT_XODR,
        sanitized,
        run_sumo=s.ENABLE_SUMO_REPAIR,
    )
    if not ok:
        print("❌ Sanitization failed; aborting pipeline.")
        self.vreport.log_failure("sanitize", "sanitize_failed")
        raise RuntimeError("Sanitize failed")

    print(f"✅ Sanitized → {sanitized}")
    MapPlotter.save_preview(sanitized, self.out_dir, stage="01_sanitize")
    # Optional QA preview (but never CARLA-load at pre-lane stages)
    if s.QA_AUTOVIS:
        print("⏭️ CARLA QA preview skipped (pre-lane stage).")

    # XML integrity on raw input
    self.qgate.gate_xml_integrity(sanitized)

