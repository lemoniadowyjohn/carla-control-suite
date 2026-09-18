# ultimate_pipeline/domain_gap/tile_perception_gap.py

from __future__ import annotations
from typing import Dict, List, Optional
import numpy as np


class TilePerceptionGap:
    """
    Computes perception performance per tile, suitable for correlation with
    tile-level domain-gap metrics.

    Supports:
      - per-class IoU
      - mean IoU (mIoU) per tile
      - ignore labels (e.g. 255 for void)
    """

    @staticmethod
    def _iou_per_class(
        pred: np.ndarray,
        gt: np.ndarray,
        class_ids: List[int],
        *,
        ignore_label: Optional[int] = None,
    ) -> Dict[int, float]:
        """
        Compute IoU per class for a single tile.
        """
        ious: Dict[int, float] = {}

        for c in class_ids:
            if ignore_label is not None:
                mask = gt != ignore_label
                pred_c = (pred == c) & mask
                gt_c = (gt == c) & mask
            else:
                pred_c = pred == c
                gt_c = gt == c

            inter = np.logical_and(pred_c, gt_c).sum()
            union = np.logical_or(pred_c, gt_c).sum()

            if union == 0:
                # Class not present in either pred or GT → undefined IoU
                ious[c] = np.nan
            else:
                ious[c] = float(inter / union)

        return ious

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @staticmethod
    def compute_tile_iou(
        predictions: Dict[str, np.ndarray],
        ground_truth: Dict[str, np.ndarray],
        *,
        class_ids: Optional[List[int]] = None,
        ignore_label: Optional[int] = None,
    ) -> Dict[str, Dict[str, float]]:
        """
        Compute per-tile perception metrics.

        Parameters
        ----------
        predictions:
            {tile_id: HxW array of class indices}
        ground_truth:
            {tile_id: HxW array of class indices}
        class_ids:
            list of class IDs to evaluate; if None, inferred from GT
        ignore_label:
            label to ignore in GT (e.g. 255)

        Returns
        -------
        {
          tile_id: {
            "miou": float,
            "iou_class_<id>": float,
            ...
          },
          ...
        }
        """
        results: Dict[str, Dict[str, float]] = {}

        for tile_id, pred in predictions.items():
            gt = ground_truth.get(tile_id)
            if gt is None:
                continue

            if pred.shape != gt.shape:
                raise ValueError(
                    f"Shape mismatch for tile {tile_id}: "
                    f"pred={pred.shape}, gt={gt.shape}"
                )

            # Infer classes if not provided
            if class_ids is None:
                cls = np.unique(gt)
                if ignore_label is not None:
                    cls = cls[cls != ignore_label]
                class_ids_tile = [int(c) for c in cls]
            else:
                class_ids_tile = class_ids

            ious = TilePerceptionGap._iou_per_class(
                pred,
                gt,
                class_ids_tile,
                ignore_label=ignore_label,
            )

            # mean IoU over valid classes
            valid_ious = [v for v in ious.values() if not np.isnan(v)]
            miou = float(np.mean(valid_ious)) if valid_ious else 0.0

            tile_result: Dict[str, float] = {"miou": miou}
            for c, v in ious.items():
                tile_result[f"iou_class_{c}"] = float(v) if not np.isnan(v) else np.nan

            results[tile_id] = tile_result

        return results
