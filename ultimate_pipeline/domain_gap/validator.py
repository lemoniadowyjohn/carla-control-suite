import numpy as np
import scipy.stats as stats


class DomainGapValidator:
    """Validates claims such as the 71% spawn-point gap."""

    @staticmethod
    def validate_spawn_gap(osm_vals, builtin_vals, claimed=0.71):
        osm = np.array(osm_vals)
        builtin = np.array(builtin_vals)

        actual = (builtin.mean() - osm.mean()) / builtin.mean()
        diff = abs(actual - claimed)

        t, p = stats.ttest_ind(osm, builtin)

        return {
            "claimed_gap": claimed,
            "actual_gap": float(actual),
            "difference": float(diff),
            "t_statistic": float(t),
            "p_value": float(p),
            "significant": p < 0.05
        }
