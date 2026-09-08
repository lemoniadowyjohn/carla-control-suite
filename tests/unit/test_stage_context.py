from ultimate_pipeline.core.stage_context import StageContext


def test_stage_context_has_explicit_semantic_contract():
    context = StageContext()
    assert context.has_geometry is False
    assert context.has_elevation is False
    assert context.has_planview is False
    assert context.has_lanes is False
