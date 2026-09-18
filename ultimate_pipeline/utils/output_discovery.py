import os
from typing import Optional


def find_latest_tiles_dir(base_output_dir: str) -> Optional[str]:
    """
    Finds the most recent <timestamp>/tiles directory that contains .xodr files.
    """

    if not os.path.isdir(base_output_dir):
        return None

    candidates = []

    for name in os.listdir(base_output_dir):
        full = os.path.join(base_output_dir, name)
        tiles = os.path.join(full, "tiles")

        if not os.path.isdir(tiles):
            continue

        xodrs = [
            f for f in os.listdir(tiles)
            if f.lower().endswith(".xodr")
        ]

        if xodrs:
            candidates.append((full, tiles))

    if not candidates:
        return None

    # Sort by directory modification time (latest first)
    candidates.sort(key=lambda x: os.path.getmtime(x[0]), reverse=True)

    return candidates[0][1]
