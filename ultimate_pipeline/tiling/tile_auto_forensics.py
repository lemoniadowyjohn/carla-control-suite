# ultimate_pipeline/tiling/tile_auto_forensics.py

import os
from typing import Optional


class TileAutoForensics:
    """
    Watches tile QA results.
    If N tiles fail in a row, triggers a recovery action
    (e.g. switch to repaired tiles, fallback tiling, etc.).
    """

    def __init__(
        self,
        tiles_dir: str,
        out_dir: str,
        trigger_n: int = 3,
    ):
        self.tiles_dir = tiles_dir
        self.out_dir = out_dir
        self.trigger_n = trigger_n
        self._consecutive_failures = 0

    def note_tile_result(
        self,
        tile_path: str,
        ok: bool,
    ) -> Optional[str]:
        """
        Register result of a tile QA run.

        Returns:
            - None → continue normally
            - str  → path to NEW tiles directory (restart loop)
        """

        if ok:
            self._consecutive_failures = 0
            return None

        self._consecutive_failures += 1

        if self._consecutive_failures < self.trigger_n:
            return None

        # ---- TRIGGERED ----
        print(
            f"🚨 TileAutoForensics triggered after "
            f"{self._consecutive_failures} consecutive failures"
        )

        self._consecutive_failures = 0

        # For now: NO automatic repair
        # We only *signal* and allow the pipeline to continue safely
        print("ℹ Auto-forensics currently in observation-only mode")

        return None
