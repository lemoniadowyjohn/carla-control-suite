"""ultimate_pipeline.domain_gap.domain_gap_prep

Thesis helper: prepare inputs/metadata for domain-gap experiments.

This module is intentionally small and dependency-light. It is used to:
- write/read a pair manifest (manual vs auto)
- export feature-proxy perception metrics from run directories

The pair manifest is optional, but helpful for auditability when you have many
runs and a short thesis deadline.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional


def sha256_file(path: str | Path) -> str:
    """Return SHA256 hex digest for a file (small helper for reproducibility)."""
    p = Path(path)
    h = hashlib.sha256()
    with p.open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


@dataclass
class PairManifest:
    """A minimal schema to track a manual-vs-auto comparison."""

    pair_id: str
    manual_xodr: str
    auto_xodr: str
    manual_run_out: str = ''
    auto_run_out: str = ''
    calib_json: str = 'calib_data.json'

    # Optional status block (regression-tested): keeps simulator availability
    # and failure reasons as explicit experimental outcomes.
    ok: bool = True
    carla_enabled: bool = False
    carla_failed: bool = False
    failure_reason: str = ''

    def to_dict(self) -> Dict[str, Any]:
        return {
            'schema_version': 'v1',
            'pair_id': self.pair_id,
            'manual': {
                'xodr': self.manual_xodr,
                'run_out': self.manual_run_out,
            },
            'auto': {
                'xodr': self.auto_xodr,
                'run_out': self.auto_run_out,
            },
            'calib_json': self.calib_json,
            'status': {
                'ok': bool(self.ok),
                'carla_enabled': bool(self.carla_enabled),
                'carla_failed': bool(self.carla_failed),
                'failure_reason': str(self.failure_reason or ''),
            },
        }


def write_pair_manifest(manifest: PairManifest, out_path: str | Path) -> str:
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(manifest.to_dict(), indent=2), encoding='utf-8')
    return str(out_path)


def load_pair_manifest(path: str | Path) -> PairManifest:
    p = Path(path)
    d = json.loads(p.read_text(encoding='utf-8'))
    status = d.get('status', {}) if isinstance(d.get('status', {}), dict) else {}
    return PairManifest(
        pair_id=d.get('pair_id', 'pair'),
        manual_xodr=d.get('manual', {}).get('xodr', ''),
        auto_xodr=d.get('auto', {}).get('xodr', ''),
        manual_run_out=d.get('manual', {}).get('run_out', ''),
        auto_run_out=d.get('auto', {}).get('run_out', ''),
        calib_json=d.get('calib_json', 'calib_data.json'),
        ok=bool(status.get('ok', True)),
        carla_enabled=bool(status.get('carla_enabled', False)),
        carla_failed=bool(status.get('carla_failed', False)),
        failure_reason=str(status.get('failure_reason', '') or ''),
    )


class DomainGapPrep:
    """Convenience helpers for the thesis runbook."""

    @staticmethod
    def ensure_feature_metrics_json(
        run_out_or_json: str | Path,
        *,
        out_name: str = 'perception_metrics_feature.json',
        max_images: int = 2000,
    ) -> Optional[str]:
        """Return a perception-metrics JSON path.

        If `run_out_or_json` is a JSON file, return it.
        If it is a directory, compute feature-proxy metrics inside the directory.
        """
        p = Path(run_out_or_json)
        if p.is_file() and p.suffix.lower() == '.json':
            return str(p)
        if p.is_dir():
            from ultimate_pipeline.perception.perception_metrics_exporter import export_perception_metrics

            return export_perception_metrics(str(p), out_name=out_name, max_images=max_images)
        return None

    @staticmethod
    def manifest_with_hashes(manifest_path: str | Path) -> Dict[str, Any]:
        """Load manifest and attach hashes for key files if they exist."""
        m = load_pair_manifest(manifest_path)
        d = m.to_dict()
        for side in ('manual', 'auto'):
            xodr = Path(d.get(side, {}).get('xodr', '')).expanduser()
            if xodr.is_file():
                d[side]['xodr_sha256'] = sha256_file(xodr)
        calib = Path(d.get('calib_json', 'calib_data.json')).expanduser()
        if calib.is_file():
            d['calib_sha256'] = sha256_file(calib)
        return d
