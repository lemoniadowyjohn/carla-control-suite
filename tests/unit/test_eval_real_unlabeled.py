"""C27: eval_real_unlabeled.py shift metrics (entropy/confidence/Frechet).

This module operates purely on RGB images + model OUTPUT logits -- it never loads a
semseg_raw label anywhere, so it is NOT exposed to the Any(255) bug class fixed
elsewhere in C27 (capture_writer / eval_sim_labeled / min_train_segmentation).
These are known-value + end-to-end readiness tests, per the original C27 spec:
"compute entropy/confidence/Frechet SHIFT (not accuracy); identical distributions
give ~0 shift."
"""
import numpy as np
import torch
from PIL import Image

from ultimate_pipeline.perception.eval_real_unlabeled import (
    _entropy_from_logits,
    _frechet_distance,
    _pooled_logits,
    _run_folder,
)


def test_entropy_is_near_zero_for_a_maximally_confident_prediction():
    # One class gets an overwhelming logit -> softmax ~= one-hot -> entropy ~= 0.
    logits = torch.full((1, 5, 2, 2), -50.0)
    logits[0, 2, :, :] = 50.0
    ent = _entropy_from_logits(logits).mean().item()
    assert ent < 1e-3


def test_entropy_is_near_max_for_a_uniform_prediction():
    # Equal logits across C classes -> softmax uniform -> entropy ~= log(C) (max entropy).
    num_classes = 5
    logits = torch.zeros((1, num_classes, 2, 2))
    ent = _entropy_from_logits(logits).mean().item()
    assert abs(ent - np.log(num_classes)) < 1e-4


def test_pooled_logits_is_spatial_mean_per_class():
    logits = torch.zeros((1, 3, 2, 2))
    logits[0, 0] = torch.tensor([[1.0, 3.0], [5.0, 7.0]])  # mean = 4.0
    pooled = _pooled_logits(logits)
    assert abs(pooled[0, 0].item() - 4.0) < 1e-6


def test_frechet_distance_is_zero_for_identical_distributions():
    mu = np.array([1.0, 2.0, 3.0])
    cov = np.eye(3) * 0.5
    d = _frechet_distance(mu, cov, mu, cov)
    assert abs(d) < 1e-6


def test_frechet_distance_is_positive_and_monotone_for_a_mean_shift():
    mu1 = np.array([0.0, 0.0])
    cov = np.eye(2)
    d_small = _frechet_distance(mu1, cov, np.array([1.0, 0.0]), cov)
    d_large = _frechet_distance(mu1, cov, np.array([5.0, 0.0]), cov)
    assert d_small > 0
    assert d_large > d_small


def test_run_folder_end_to_end_on_real_images_with_a_real_model(tmp_path):
    import torchvision

    img_dir = tmp_path / "real_images"
    img_dir.mkdir()
    rng = np.random.default_rng(0)
    for i in range(3):
        arr = rng.integers(0, 255, size=(16, 16, 3), dtype=np.uint8)
        Image.fromarray(arr, mode="RGB").save(img_dir / f"{i:03d}.png")

    num_classes = 29
    model = torchvision.models.segmentation.fcn_resnet50(weights=None, num_classes=num_classes)
    result = _run_folder(model, img_dir, torch.device("cpu"), None, limit=0)

    assert result["n"] == 3
    assert result["entropy_mean"] is not None and result["entropy_mean"] >= 0
    assert 0.0 <= result["confidence_mean"] <= 1.0
    assert result["pooled_logits_cov"] is not None  # n>1 -> covariance computable
