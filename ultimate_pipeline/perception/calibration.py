import numpy as np


def compute_ece(confidences, labels, n_bins=15):
    """
    Expected Calibration Error (ECE).
    confidences: predicted confidence per sample
    labels: 1 if correct else 0
    """
    confidences = np.asarray(confidences, dtype=float)
    labels = np.asarray(labels, dtype=float)
    if confidences.size == 0 or labels.size == 0 or confidences.size != labels.size:
        return 0.0

    bins = np.linspace(0.0, 1.0, int(n_bins) + 1)
    ece = 0.0

    for i in range(int(n_bins)):
        mask = (confidences >= bins[i]) & (confidences < bins[i + 1])
        if np.sum(mask) == 0:
            continue
        acc = np.mean(labels[mask])
        conf = np.mean(confidences[mask])
        ece += np.abs(acc - conf) * np.sum(mask) / len(confidences)

    return float(ece)
