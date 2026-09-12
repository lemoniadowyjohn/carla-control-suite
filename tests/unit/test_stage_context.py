from types import SimpleNamespace

from ultimate_pipeline.core.stage_context import (
    StageContext,
    ensure_stage_context,
    sync_legacy_semantic_state,
)
from ultimate_pipeline.pipeline_stages.stage_04_enrichment import (
    _mark_geometry_only_stage_contract,
)


def test_stage_context_has_explicit_semantic_contract():
    context = StageContext()
    assert context.has_geometry is False
    assert context.has_elevation is False
    assert context.has_planview is False
    assert context.has_lanes is False


def test_stage_context_rejects_unknown_contract_keys():
    context = StageContext()
    try:
        context.replace(has_routing=True)
        assert False, "expected unknown stage field to fail"
    except KeyError:
        pass


def test_stage4_typed_contract_preserves_the_legacy_mapping_exactly():
    pipeline = SimpleNamespace(
        semantic_state={
            "has_geometry": False,
            "has_elevation": True,
            "has_planview": True,
            "has_lanes": True,
        }
    )
    _mark_geometry_only_stage_contract(pipeline)
    assert pipeline.stage_context == StageContext(has_geometry=True)
    assert pipeline.semantic_state == pipeline.stage_context.as_legacy_mapping()


def test_legacy_stage_test_double_bootstraps_a_typed_context_without_state_loss():
    pipeline = SimpleNamespace(semantic_state={"has_geometry": True})
    context = ensure_stage_context(pipeline)
    assert context == StageContext(has_geometry=True)
    context.replace(has_lanes=True)
    sync_legacy_semantic_state(pipeline, context)
    assert pipeline.semantic_state == {
        "has_geometry": True,
        "has_elevation": False,
        "has_planview": False,
        "has_lanes": True,
    }
