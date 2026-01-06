import numpy as np
from scipy.stats import entropy, ks_2samp

class RandomnessEntropyMetric:

    @staticmethod
    def compute_distribution(values: np.ndarray):
        hist, bins = np.histogram(values, bins=50, density=True)
        hist = hist + 1e-9
        return entropy(hist)

    @staticmethod
    def ks_test(values1: np.ndarray, values2: np.ndarray):
        return ks_2samp(values1, values2).statistic
