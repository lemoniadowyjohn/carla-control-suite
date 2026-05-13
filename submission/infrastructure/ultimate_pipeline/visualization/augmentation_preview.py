#!/usr/bin/env python3
"""ultimate_pipeline.visualization.augmentation_preview

Small CLI to preview the project's realism augmentations.

This is a development/thesis-figure helper. It loads one image, runs the
RealismAugmentor several times with a fixed seed sweep, and writes a contact
sheet to disk.

Usage
-----
python -m ultimate_pipeline.visualization.augmentation_preview --in-img path/to/img.png --out out.png --n 12
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np


def _load_image(path: Path) -> np.ndarray:
    try:
        from PIL import Image  # type: ignore
        arr = np.asarray(Image.open(path).convert('RGB'), dtype=np.uint8)
        return arr
    except Exception:
        import matplotlib.image as mpimg  # type: ignore
        arr = mpimg.imread(str(path))
        if arr.dtype != np.uint8:
            arr = (np.clip(arr, 0, 1) * 255).astype(np.uint8)
        if arr.ndim == 2:
            arr = np.stack([arr, arr, arr], axis=-1)
        if arr.shape[-1] == 4:
            arr = arr[..., :3]
        return arr


def _save_contact_sheet(images: list[np.ndarray], out_path: Path, cols: int = 4) -> None:
    import math
    import matplotlib.pyplot as plt  # type: ignore

    n = len(images)
    rows = int(math.ceil(n / cols))

    # Build a canvas
    h, w, _ = images[0].shape
    canvas = np.zeros((rows * h, cols * w, 3), dtype=np.uint8)

    for i, im in enumerate(images):
        r = i // cols
        c = i % cols
        canvas[r * h:(r + 1) * h, c * w:(c + 1) * w] = im

    out_path.parent.mkdir(parents=True, exist_ok=True)
    plt.imsave(str(out_path), canvas)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--in-img', required=True)
    ap.add_argument('--out', default='augmentation_preview.png')
    ap.add_argument('--n', type=int, default=12)
    args = ap.parse_args()

    from ultimate_pipeline.augmentation.realism_augmentor import RealismAugmentor

    in_path = Path(args.in_img)
    img = _load_image(in_path)

    aug = RealismAugmentor()
    outs: list[np.ndarray] = []
    for seed in range(int(args.n)):
        outs.append(aug.apply(img, seed=seed))

    _save_contact_sheet(outs, Path(args.out))
    print('Wrote:', args.out)


if __name__ == '__main__':
    main()
