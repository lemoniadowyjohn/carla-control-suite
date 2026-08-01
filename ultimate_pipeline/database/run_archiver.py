from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import List

from ultimate_pipeline.database.db_manager import Database
from ultimate_pipeline.config.settings import SETTINGS


class RunArchiver:
    """
    Archives old pipeline runs:
    - keeps last N runs locally
    - moves older runs to external drive (D:/ or H:/)
    - records metadata in database
    """

    def __init__(self, keep_last_n: int = 10):
        self.keep_last_n = keep_last_n
        self.db = Database()

        self.output_root = Path(SETTINGS.BASE_OUTPUT_DIR)
        self.archive_root = SETTINGS.DB_ROOT / "archived_runs"
        self.archive_root.mkdir(parents=True, exist_ok=True)

    def _list_runs(self) -> List[Path]:
        runs = [
            p for p in self.output_root.iterdir()
            if p.is_dir() and p.name[:8].isdigit()
        ]
        return sorted(runs, key=lambda p: p.stat().st_mtime, reverse=True)

    def archive_old_runs(self) -> None:
        runs = self._list_runs()

        if len(runs) <= self.keep_last_n:
            return  # nothing to do

        for run_dir in runs[self.keep_last_n:]:
            self._archive_run(run_dir)

    def _archive_run(self, run_dir: Path) -> None:
        run_id = run_dir.name
        target = self.archive_root / run_id

        if target.exists():
            return  # idempotent: already archived

        print(f"📦 Archiving old run → {run_id}")
        shutil.move(str(run_dir), str(target))

        # --------------------------------------------------
        # Collect metadata (ROBUST, NEVER CRASH)
        # --------------------------------------------------
        meta: dict = {}

        settings_path = target / "settings_snapshot.json"
        if settings_path.exists():
            try:
                text = settings_path.read_text(encoding="utf-8").strip()
                if text:
                    meta["settings_snapshot"] = json.loads(text)
                else:
                    meta["settings_snapshot_error"] = "empty file"
            except json.JSONDecodeError as e:
                meta["settings_snapshot_error"] = f"invalid json: {e}"
            except Exception as e:
                meta["settings_snapshot_error"] = f"read failed: {e}"
        else:
            meta["settings_snapshot_error"] = "file missing"

        # --------------------------------------------------
        # Log to database (schema-compatible)
        # --------------------------------------------------
        self.db.log_pipeline_run(
            run_id=run_id,
            timestamp=run_id,  # run_id already encodes time
            output_dir=str(run_dir),
            archive_dir=str(target),
            status="archived",
            metadata_json=json.dumps(meta),
        )
