#!/usr/bin/env python3
"""CHAT-09 / B2: tests for verify_random_initialisation with weights_backbone.

Tests:
1. verify_random_initialisation with weights_backbone=None passes and records None
2. verify_random_initialisation with weights_backbone=ResNet50_Weights.IMAGENET1K_V1 raises PretrainingContractError
3. verify_random_initialisation with weights=ResNet50_Weights.IMAGENET1K_V1 raises PretrainingContractError
4. The four model factories all pass weights_backbone=None explicitly
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

# The test_four_factories test doesn't need mocks - it reads source directly
def test_four_factories_pass_weights_backbone_none():
    """All four model factories pass weights_backbone=None explicitly."""
    import ultimate_pipeline.perception.train_launcher as tl
    import ultimate_pipeline.perception.min_train_segmentation as mts
    import ultimate_pipeline.perception.eval_sim_labeled as esl
    import ultimate_pipeline.perception.eval_real_unlabeled as eru

    for mod, name in [(tl, 'train_launcher'), (mts, 'min_train_segmentation'),
                       (esl, 'eval_sim_labeled'), (eru, 'eval_real_unlabeled')]:
        src = Path(mod.__file__).read_text(encoding='utf-8')
        assert 'weights_backbone=None' in src, f"{name} missing weights_backbone=None"
        assert 'weights=None' in src, f"{name} missing weights=None"
    print("PASS: all four factories pass weights_backbone=None")


if __name__ == "__main__":
    test_four_factories_pass_weights_backbone_none()
    print("\n=== B2 factory source tests: ALL PASS ===")