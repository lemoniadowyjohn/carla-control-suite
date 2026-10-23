"""Fail-closed sequential executor for one registered stage/capability graph.

Migration adapters supply the original callback objects, without replacing algorithms.
Graph order is registration order. Status records are write-once JSON.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
import os
from pathlib import Path
import re
from typing import Callable, Any, Mapping
from uuid import uuid4

from ultimate_pipeline.common import (digest_object, file_sha256, read_object,
                                       safe_artifact, utc_now, write_immutable_json)
from ultimate_pipeline.contracts.stage_capabilities import GEOMETRY_FROZEN


class StageContractError(RuntimeError):
    pass


class ArtifactIntegrityError(StageContractError):
    pass


@dataclass(frozen=True)
class StageNode:
    name: str
    callable: Callable[["StageContext"], Any] = field(repr=False, compare=False)
    requires: frozenset[str] = frozenset()
    provides: frozenset[str] = frozenset()
    invalidates: frozenset[str] = frozenset()
    mutates_structure: bool = False
    required_profiles: frozenset[str] = frozenset()
    optional_profiles: frozenset[str] = frozenset()
    input_artifacts: tuple[str, ...] = ()
    output_artifacts: tuple[str, ...] = ()
    diagnostic_only: bool = False

    def declaration(self) -> dict[str, Any]:
        return {"name": self.name, "requires": sorted(self.requires),
                "provides": sorted(self.provides), "invalidates": sorted(self.invalidates),
                "mutates_structure": self.mutates_structure,
                "required_profiles": sorted(self.required_profiles),
                "optional_profiles": sorted(self.optional_profiles),
                "input_artifacts": list(self.input_artifacts),
                "output_artifacts": list(self.output_artifacts),
                "diagnostic_only": self.diagnostic_only}


@dataclass(frozen=True)
class StageExecutionRecord:
    name: str
    start_utc: str
    end_utc: str
    elapsed_s: float
    input_hashes: dict[str, str]
    output_hashes: dict[str, str]
    capability_before: list[str]
    capability_after: list[str]
    status: str
    exception: str | None
    git_sha: str
    resumed_from: str | None = None


@dataclass(frozen=True)
class StageContext:
    workspace: Path
    profile: str
    stage_name: str
    capabilities: frozenset[str]
    run_id: str

    def artifact(self, relative: str) -> Path:
        return safe_artifact(self.workspace, relative)


class StageGraphExecutor:
    def __init__(self, nodes: list[StageNode], *, workspace: str | Path,
                 receipts_dir: str | Path, profile: str, git_sha: str,
                 initial_capabilities: frozenset[str] = frozenset(),
                 enabled_optional: frozenset[str] = frozenset()):
        self.nodes = tuple(nodes)
        self.workspace = Path(workspace).resolve()
        self.receipts_dir = Path(receipts_dir).resolve()
        self.profile = profile
        self.git_sha = git_sha
        self.initial_capabilities = frozenset(initial_capabilities)
        self.enabled_optional = frozenset(enabled_optional)
        self.records: list[StageExecutionRecord] = []
        self.receipt_paths: list[Path] = []
        self.run_id: str | None = None
        self._validated = False

    @property
    def graph_sha256(self) -> str:
        return digest_object([stage.declaration() for stage in self.nodes])

    def _selected(self, stage: StageNode) -> bool:
        if not stage.required_profiles and not stage.optional_profiles:
            return True
        return self.profile in stage.required_profiles or (
            self.profile in stage.optional_profiles and stage.name in self.enabled_optional)

    def validate_graph(self) -> None:
        if self.profile == 'THESIS_STRICT' and os.environ.get('UP_SKIP_STAGE_CAPABILITY_CONTRACT', '').strip().lower() not in ('', '0', 'false', 'no'):
            raise StageContractError('THESIS_STRICT rejects UP_SKIP_STAGE_CAPABILITY_CONTRACT')
        if not self.nodes:
            raise StageContractError('Registered graph cannot be empty')
        names: set[str] = set()
        writers: set[str] = set()
        for stage in self.nodes:
            if not re.fullmatch(r'[A-Za-z0-9_.-]+', stage.name) or stage.name in names:
                raise StageContractError(f'Invalid or duplicate stage name: {stage.name}')
            names.add(stage.name)
            if not callable(stage.callable):
                raise StageContractError(f'No callable for stage: {stage.name}')
            if stage.provides & stage.invalidates:
                raise StageContractError(f'A stage cannot provide and invalidate same capability: {stage.name}')
            if stage.required_profiles & stage.optional_profiles:
                raise StageContractError(f'Ambiguous required/optional profile: {stage.name}')
            if len(stage.output_artifacts) != len(set(stage.output_artifacts)):
                raise StageContractError(f'Duplicate output in stage: {stage.name}')
            for name in stage.input_artifacts + stage.output_artifacts:
                safe_artifact(self.workspace, name)
            if writers & set(stage.output_artifacts):
                raise StageContractError(f'Multiple writers for an artifact: {stage.name}')
            writers.update(stage.output_artifacts)
        if not self.enabled_optional.issubset({s.name for s in self.nodes if self.profile in s.optional_profiles}):
            raise StageContractError('Unknown/non-optional enabled stage')
        self._validated = True

    def _hash_artifacts(self, names: tuple[str, ...]) -> dict[str, str]:
        hashes = {}
        for name in names:
            path = safe_artifact(self.workspace, name)
            if not path.is_file():
                raise ArtifactIntegrityError(f'Required file missing: {name}')
            hashes[name] = file_sha256(path)
        return hashes

    def _record(self, index: int, record: StageExecutionRecord) -> None:
        assert self.run_id is not None
        target = self.receipts_dir / self.run_id / f'{index:03d}_{record.name}.json'
        write_immutable_json(target, asdict(record))
        self.records.append(record)
        self.receipt_paths.append(target)

    def _drive(self, *, stop_at: str | None, resume: dict[str, Any] | None = None) -> tuple[StageExecutionRecord, ...]:
        self.validate_graph()
        if stop_at is not None and stop_at not in {node.name for node in self.nodes}:
            raise StageContractError(f'Unknown stop stage: {stop_at}')
        self.run_id = f'{datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")}-{uuid4().hex[:12]}'
        self.records = []
        self.receipt_paths = []
        capabilities = set(self.initial_capabilities)
        tracked: dict[str, str] = {}
        failed = False
        for index, stage in enumerate(self.nodes):
            start = utc_now()
            before = sorted(capabilities)
            ins: dict[str, str] = {}
            outs: dict[str, str] = {}
            status = 'NOT_RUN'
            exception = None
            resumed_from = None
            if resume is not None and stage.name in resume['completed']:
                if failed:
                    raise StageContractError('Completed stage after failed stage in resume')
                prior = resume['completed'][stage.name]
                if not self._selected(stage):
                    raise StageContractError('Cannot resume a stage now omitted by profile')
                if not stage.requires.issubset(capabilities):
                    raise StageContractError(f'Resumed prerequisites changed: {stage.name}')
                outs = self._hash_artifacts(stage.output_artifacts)
                if outs != prior['output_hashes']:
                    raise ArtifactIntegrityError(f'Resumed output changed: {stage.name}')
                ins = self._hash_artifacts(stage.input_artifacts)
                if ins != prior['input_hashes']:
                    raise ArtifactIntegrityError(f'Resumed input changed: {stage.name}')
                if before != prior['capability_before']:
                    raise StageContractError(f'Resumed capability drift: {stage.name}')
                capabilities.difference_update(stage.invalidates)
                capabilities.update(stage.provides)
                if sorted(capabilities) != prior['capability_after']:
                    raise StageContractError(f'Resumed capability result drift: {stage.name}')
                tracked.update(outs)
                status = 'PASS'
                resumed_from = prior['receipt_path']
            elif not self._selected(stage):
                exception = 'Profile selection: not selected'
            elif stop_at is not None and self.nodes.index(stage) > next(i for i, n in enumerate(self.nodes) if n.name == stop_at):
                exception = 'Stopped by execute_until'
            elif failed and not stage.diagnostic_only:
                exception = 'Upstream failure: stage not executed'
            else:
                try:
                    for name, old_digest in tracked.items():
                        if self._hash_artifacts((name,))[name] != old_digest:
                            raise ArtifactIntegrityError(f'Earlier output mutated: {name}')
                    missing = stage.requires - capabilities
                    if missing:
                        raise StageContractError(f'Missing capabilities for {stage.name}: {sorted(missing)}')
                    if stage.mutates_structure and GEOMETRY_FROZEN in capabilities and GEOMETRY_FROZEN not in stage.invalidates:
                        raise StageContractError(f'{stage.name} mutates frozen structure without invalidation')
                    ins = self._hash_artifacts(stage.input_artifacts)
                    ctx = StageContext(self.workspace, self.profile, stage.name, frozenset(capabilities), self.run_id)
                    stage.callable(ctx)
                    outs = self._hash_artifacts(stage.output_artifacts)
                    for name, old_digest in tracked.items():
                        if self._hash_artifacts((name,))[name] != old_digest:
                            raise ArtifactIntegrityError(f'Earlier output mutated by {stage.name}: {name}')
                    capabilities.difference_update(stage.invalidates)
                    capabilities.update(stage.provides)
                    tracked.update(outs)
                    status = 'PASS'
                except Exception as exc:
                    status = 'FAIL'
                    exception = f'{type(exc).__name__}: {exc}'
                    failed = True
            end = utc_now()
            elapsed = max(0.0, (datetime.fromisoformat(end) - datetime.fromisoformat(start)).total_seconds())
            record = StageExecutionRecord(stage.name, start, end, elapsed, ins, outs, before,
                                          sorted(capabilities), status, exception, self.git_sha,
                                          resumed_from)
            self._record(index, record)
        return tuple(self.records)

    def execute(self) -> tuple[StageExecutionRecord, ...]:
        return self._drive(stop_at=None)

    def execute_until(self, stage: str) -> tuple[StageExecutionRecord, ...]:
        return self._drive(stop_at=stage)

    def emit_execution_graph_receipt(self) -> Path:
        if not self.records or self.run_id is None:
            raise StageContractError('Run executor first')
        envelope = {"schema_version": 1, "run_id": self.run_id, "profile": self.profile,
                    "git_sha": self.git_sha, "graph_sha256": self.graph_sha256,
                    "initial_capabilities": sorted(self.initial_capabilities),
                    "enabled_optional": sorted(self.enabled_optional),
                    "stages": [{"name": record.name,
                                "status": record.status,
                                "record_path": str(path), "record_sha256": file_sha256(path)}
                               for record, path in zip(self.records, self.receipt_paths)]}
        target = self.receipts_dir / self.run_id / 'graph_receipt.json'
        write_immutable_json(target, envelope)
        return target

    def resume_from_receipt(self, receipt_path: str | Path) -> tuple[StageExecutionRecord, ...]:
        receipt = read_object(receipt_path)
        if receipt.get('schema_version') != 1 or receipt.get('graph_sha256') != self.graph_sha256:
            raise StageContractError('Resume graph/schema differs')
        if (receipt.get('profile') != self.profile or receipt.get('git_sha') != self.git_sha or
            receipt.get('initial_capabilities') != sorted(self.initial_capabilities) or
            receipt.get('enabled_optional') != sorted(self.enabled_optional)):
            raise StageContractError('Resume identity/profile differs')
        entries = receipt.get('stages')
        if not isinstance(entries, list) or len(entries) != len(self.nodes):
            raise StageContractError('Malformed/missing resume stage list')
        completed: dict[str, Any] = {}
        passed_prefix = True
        for node, entry in zip(self.nodes, entries):
            if not isinstance(entry, dict) or entry.get('name') != node.name:
                raise StageContractError('Resume stage ordering differs')
            path = Path(entry['record_path']).resolve()
            if not path.is_relative_to(self.receipts_dir):
                raise StageContractError('Resume points outside receipt root')
            if file_sha256(path) != entry['record_sha256']:
                raise ArtifactIntegrityError('Previous stage receipt modified')
            record = read_object(path)
            if record.get('name') != node.name or record.get('status') != entry['status']:
                raise StageContractError('Resume stage receipt mismatch')
            if passed_prefix and record['status'] == 'PASS':
                completed[node.name] = {**record, 'receipt_path': str(path)}
            else:
                passed_prefix = False
        return self._drive(stop_at=None, resume={'completed': completed})
