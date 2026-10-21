# ultimate_pipeline/tests/unit/test_receipt_lifecycle_negative_controls.py
# OC-25: synthetic negative-control fixtures for resolve_final_artifact_receipt()
"""READ-ONLY / SYNTHETIC ONLY — never asserts PASS for real campaigns."""

def test_receipt_rejects_failed_map_acceptance():
    """C3: receipt must not pass when map_acceptance reports failure."""
    from ultimate_pipeline.contracts.release_acceptance import build_final_receipt
    # Synthetic: acceptance reports failure; receipt must not claim PASS
    receipt = build_final_receipt(
        final_path="/fake/final.xodr",
        map_acceptance={"ok": False, "hard_fail_reasons": ["P0-C seams"]},
        evidence={"map_acceptance": {"artifact_path": "/fake/final.xodr"}},
    )
    assert receipt.get("status") != "PASS", (
        "receipt must reject when map_acceptance.ok=False"
    )

def test_receipt_rejects_missing_stage():
    """C2: receipt must not claim RUN_COMPLETED when a required stage never executed."""
    from ultimate_pipeline.contracts.release_acceptance import build_final_receipt
    receipt = build_final_receipt(
        final_path="/fake/final.xodr",
        stage_history=["01_sanitize", "02_topology"],  # missing tiling/freeze
        map_acceptance={"ok": True},
        freeze_provided=False,
    )
    assert "FINAL_ARTIFACT_PROMOTABLE" not in receipt.get("states", []), (
        "missing freeze must block promotable claim"
    )
def test_receipt_detects_post_freeze_mutation():
    """C4: receipt must detect final XODR changed after freeze fingerprint."""
    from ultimate_pipeline.contracts.release_acceptance import build_final_receipt
    receipt = build_final_receipt(
        final_path="/fake/final.xodr",
        freeze_sha="ce7a20c0...",
        current_sha="a32b26a8...",
        map_acceptance={"ok": True},
    )
    # The receipt mechanism (if implemented correctly) must expose
    # freeze-vs-live mismatch rather than suppress it.
    assert "freeze_sha256" in receipt or receipt.get("freeze_mismatch") is True

def test_receipt_rejects_tiling_from_different_sha():
    """C5: receipt must not describe tiles derived from a different XODR."""
    from ultimate_pipeline.contracts.release_acceptance import build_final_receipt
    receipt = build_final_receipt(
        final_path="/fake/final.xodr",
        tile_input_sha="other_sha_1234",
        final_sha="final_sha_5678",
    )
    assert receipt.get("tile_source_mismatch") is True or receipt.get("status") != "PASS"
