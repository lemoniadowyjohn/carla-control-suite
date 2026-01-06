from __future__ import annotations
import numpy as np
import pandas as pd
import scipy.stats as stats


class DomainGapStatistics:
    """
    Unified statistical analysis module for thesis:
    - t-tests
    - effect sizes
    - correlations
    - ANOVA
    """

    def calculate_significance(self, df: pd.DataFrame):
        metrics = [
            'object_detection_accuracy',
            'lane_detection_accuracy',
            'semantic_segmentation_iou',
            'obstacle_detection_precision',
            'overall_score',
            'false_positive_rate',
            'inference_time_ms'
        ]

        osm = df[df['domain_type'] == 'OSM_LIKE']
        manual = df[df['domain_type'] == 'MANUAL_LIKE']

        results = {}
        for m in metrics:
            t, p = stats.ttest_ind(osm[m], manual[m])
            pooled_std = np.sqrt((osm[m].std()**2 + manual[m].std()**2) / 2)
            d = (osm[m].mean() - manual[m].mean()) / pooled_std

            results[m] = dict(
                t=float(t),
                p=float(p),
                significant=p < 0.05,
                effect_size=float(d),
                mean_osm=float(osm[m].mean()),
                mean_manual=float(manual[m].mean())
            )
        return results

    def correlations(self, df: pd.DataFrame):
        metrics = [
            'object_detection_accuracy',
            'lane_detection_accuracy',
            'semantic_segmentation_iou',
            'obstacle_detection_precision',
            'overall_score',
            'false_positive_rate',
            'inference_time_ms'
        ]

        results = {}
        for m in metrics:
            r, p = stats.pearsonr(df['complexity_score'], df[m])
            results[m] = dict(
                r=float(r),
                p=float(p),
                significant=p < 0.05
            )
        return results
