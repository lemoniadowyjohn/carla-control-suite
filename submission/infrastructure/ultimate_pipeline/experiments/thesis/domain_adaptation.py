
"""Domain adaptation metrics wrapper."""
from .core_algorithms import coral_loss, mmd_loss
import numpy as np

def compute_metrics(src_features, tgt_features):
    return {
        "coral": float(coral_loss(src_features, tgt_features)),
        "mmd": float(mmd_loss(src_features, tgt_features)),
    }
