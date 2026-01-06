from dataclasses import dataclass
from typing import List, Optional
from pathlib import Path

from ultimate_pipeline.diagnostics.tile_forensics import (
    scan_tile,
    scan_tiles_dir,
    emergency_repair_tiles_dir,
    write_report,
)

@dataclass
class ConsecutiveFailState:
    consecutive_failures: int = 0
    last_failed_tiles: List[str] = None

    def __post_init__(self):
        if self.last_failed_tiles is None:
            self.last_failed_tiles = []


class TileAutoForensics:
    def __init__(self, tiles_dir: str, out_dir: str, trigger_n: int = 3):
        self.tiles_dir = tiles_dir
        self.out_dir = out_dir
        self.trigger_n = trigger_n
        self.state = ConsecutiveFailState()

    def note_tile_result(self, tile_path: str, ok: bool) -> Optional[str]:
        """
        Call after each tile QA.
        If ok=False for N tiles in a row => run forensic scan; if signature matches, run emergency repair.
        Returns repaired_tiles_dir if repair occurred, else None.
        """
        if ok:
            self.state.consecutive_failures = 0
            self.state.last_failed_tiles.clear()
            return None

        self.state.consecutive_failures += 1
        self.state.last_failed_tiles.append(tile_path)
        self.state.last_failed_tiles = self.state.last_failed_tiles[-self.trigger_n :]

        if self.state.consecutive_failures < self.trigger_n:
            return None

        # Trigger forensics
        report = scan_tiles_dir(self.tiles_dir)
        report_path = str(Path(self.out_dir) / "tile_forensics_report.json")
        write_report(report, report_path)

        # Check the last failed tiles signatures
        sigs = [scan_tile(p).signature for p in self.state.last_failed_tiles]
        sig_set = set(sigs)

        # Only attempt emergency repair for the known signature
        if sig_set == {"lane_type_wiped_all_none"}:
            repaired_dir = str(Path(self.out_dir) / "tiles_repaired")
            fix = emergency_repair_tiles_dir(self.tiles_dir, repaired_dir)
            fix_path = str(Path(self.out_dir) / "tile_forensics_repair.json")
            write_report(fix, fix_path)

            # Reset counter after intervention
            self.state.consecutive_failures = 0
            self.state.last_failed_tiles.clear()
            return repaired_dir

        # Otherwise: stop early with a clean error
        raise RuntimeError(
            f"[TILE FORENSICS] {self.trigger_n} consecutive tile failures.\n"
            f"Last signatures: {sigs}\n"
            f"Report: {report_path}\n"
            f"No safe auto-repair available for these signatures."
        )
