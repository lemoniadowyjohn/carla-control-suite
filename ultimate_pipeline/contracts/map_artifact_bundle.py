"""Cryptographic map representation chain (source → editor → cooked → runtime).

The runtime snapshot must be acquired by a trusted CARLA RPC probe. Providing
manually invented values is not proof of a running simulator.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from ultimate_pipeline.common import (file_sha256, read_object, require_digest,
                                      safe_artifact, write_immutable_json)

MANUAL_GRID0828_SOURCE_SHA256 = '5eaece230e02f6c1b2075db851894870790e86ac64710abb3465bcfc533e9b0c'


class MapAuthorityError(RuntimeError):
    pass


@dataclass(frozen=True)
class SourceXodr:
    path: str
    sha256: str
    bytes: int
    frame_id: str


@dataclass(frozen=True)
class ArtifactFile:
    path: str
    sha256: str
    bytes: int


@dataclass(frozen=True)
class EditorPackage:
    package_name: str
    manifest_path: str
    manifest_sha256: str
    package_file_hashes: tuple[ArtifactFile, ...]


@dataclass(frozen=True)
class CookedPackage:
    build_sha: str
    cook_run_id: str
    manifest_path: str
    manifest_sha256: str
    package_file_hashes: tuple[ArtifactFile, ...]


@dataclass(frozen=True)
class RuntimeIdentity:
    requested_map: str
    reported_map: str
    normalized_map_id: str
    xodr_sha256_if_retrievable: str | None
    package_manifest_sha256: str
    carla_server_version: str
    executable_sha256: str
    executable_path: str


@dataclass(frozen=True)
class Lineage:
    source_to_editor_receipt: str
    editor_to_cook_receipt: str
    cook_to_runtime_receipt: str


def normalized_map(value: str) -> str:
    """Strip only known CARLA Unreal path wrappers, never fuzzy substring match."""
    if not isinstance(value, str) or not value.strip():
        raise MapAuthorityError('Map identity empty')
    last = value.strip().replace('\\', '/').split('/')[-1]
    if '.' in last:
        prefix, suffix = last.split('.', 1)
        if prefix != suffix:
            raise MapAuthorityError('Unreal package/object identity mismatch')
        last = prefix
    if last.startswith('UEDPIE_'):
        # UEDPIE_0_Map → Map, but reject malformed editor prefixes.
        fields = last.split('_', 2)
        if len(fields) != 3 or not fields[1].isdigit():
            raise MapAuthorityError('Malformed PIE map path')
        last = fields[2]
    if not last:
        raise MapAuthorityError('Map name normalizes empty')
    return last


def normalized_map_path(value: str) -> str:
    """Full Unreal path authority; do not equate maps in different directories."""
    normalized_map(value)  # validates the basename and object suffix
    parts = value.strip().replace('\\', '/').split('/')
    base = normalized_map(parts[-1])
    return '/'.join(parts[:-1] + [base])



@dataclass(frozen=True)
class MapArtifactBundle:
    logical_map_id: str
    role: str
    source_xodr: SourceXodr
    editor_package: EditorPackage
    cooked_package: CookedPackage
    runtime_identity: RuntimeIdentity
    lineage: Lineage
    root: str

    def _root(self) -> Path:
        return Path(self.root).resolve()

    @staticmethod
    def _expect(value: Any, expected: Any, title: str) -> None:
        if value != expected:
            raise MapAuthorityError(f'{title} mismatch: actual={value!r}, expected={expected!r}')

    def _receipt(self, relative: str, *, bindings: dict[str, str]) -> None:
        try:
            evidence = read_object(safe_artifact(self._root(), relative))
        except (OSError, ValueError) as exc:
            raise MapAuthorityError(f'Missing/invalid lineage receipt {relative}: {exc}') from exc
        self._expect(evidence.get('status'), 'PASS', f'{relative} status')
        for key, expected in bindings.items():
            self._expect(evidence.get(key), expected, f'{relative} {key}')

    def _package(self, *, kind: str, manifest_path: str, manifest_sha: str,
                 file_hashes: tuple[ArtifactFile, ...], expected_bindings: dict[str, Any]) -> None:
        try:
            require_digest(manifest_sha, 'manifest_sha256')
            manifest_file = safe_artifact(self._root(), manifest_path)
            self._expect(file_sha256(manifest_file), manifest_sha, f'{kind} manifest digest')
            manifest = read_object(manifest_file)
            for key, expected in expected_bindings.items():
                self._expect(manifest.get(key), expected, f'{kind} manifest {key}')
            paths = [entry.path for entry in file_hashes]
            if not paths or len(paths) != len(set(paths)):
                raise MapAuthorityError(f'{kind}: empty/duplicate package file list')
            # Full equality forbids a manifest from silently omitting tiles/files.
            self._expect(manifest.get('files'), [asdict(entry) for entry in file_hashes], f'{kind} file manifest')
            # The manifest must enumerate EVERY regular file under the package root;
            # otherwise an additional cooked tile could silently escape identity checks.
            package_dir = manifest_file.parent
            expected_paths = {safe_artifact(self._root(), item.path) for item in file_hashes} | {manifest_file}
            actual_paths = {p.resolve() for p in package_dir.rglob('*') if p.is_file()}
            self._expect(actual_paths, expected_paths, f'{kind} complete package inventory')
            for item in file_hashes:
                require_digest(item.sha256, f'{kind}/{item.path}')
                file_path = safe_artifact(self._root(), item.path)
                if not file_path.is_file():
                    raise MapAuthorityError(f'{kind} missing file: {item.path}')
                self._expect(file_path.stat().st_size, item.bytes, f'{kind} {item.path} size')
                self._expect(file_sha256(file_path), item.sha256, f'{kind} {item.path} digest')
        except (OSError, ValueError) as exc:
            raise MapAuthorityError(f'{kind}: {exc}') from exc

    def verify_source(self) -> bool:
        if self.role not in {'manual', 'auto'} or not self.logical_map_id.strip():
            raise MapAuthorityError('Invalid map logical identity/role')
        if self.role == 'manual' and normalized_map(self.logical_map_id) == 'Grid0828':
            self._expect(self.source_xodr.sha256, MANUAL_GRID0828_SOURCE_SHA256,
                         'Certified manual Grid0828 source SHA-256')
        try:
            require_digest(self.source_xodr.sha256, 'source_sha256')
            path = safe_artifact(self._root(), self.source_xodr.path)
            if not path.is_file():
                raise MapAuthorityError('Source XODR missing')
            self._expect(path.stat().st_size, self.source_xodr.bytes, 'XODR byte size')
            self._expect(file_sha256(path), self.source_xodr.sha256, 'XODR SHA-256')
            if not self.source_xodr.frame_id:
                raise MapAuthorityError('Source frame ID missing')
        except (OSError, ValueError) as exc:
            raise MapAuthorityError(f'Source: {exc}') from exc
        return True

    def verify_editor_package(self) -> bool:
        self.verify_source()
        self._package(kind='editor', manifest_path=self.editor_package.manifest_path,
            manifest_sha=self.editor_package.manifest_sha256,
            file_hashes=self.editor_package.package_file_hashes,
            expected_bindings={'schema_version': 1, 'kind': 'editor',
                               'logical_map_id': self.logical_map_id, 'source_sha256': self.source_xodr.sha256,
                               'package_name': self.editor_package.package_name})
        self._receipt(self.lineage.source_to_editor_receipt,
            bindings={'source_sha256': self.source_xodr.sha256,
                      'editor_manifest_sha256': self.editor_package.manifest_sha256})
        return True

    def verify_cooked_package(self) -> bool:
        self.verify_editor_package()
        if not self.cooked_package.build_sha or not self.cooked_package.cook_run_id:
            raise MapAuthorityError('Missing build_sha/cook_run_id')
        self._package(kind='cooked', manifest_path=self.cooked_package.manifest_path,
            manifest_sha=self.cooked_package.manifest_sha256,
            file_hashes=self.cooked_package.package_file_hashes,
            expected_bindings={'schema_version': 1, 'kind': 'cooked',
                               'logical_map_id': self.logical_map_id,
                               'source_sha256': self.source_xodr.sha256,
                               'editor_manifest_sha256': self.editor_package.manifest_sha256,
                               'build_sha': self.cooked_package.build_sha,
                               'cook_run_id': self.cooked_package.cook_run_id})
        self._receipt(self.lineage.editor_to_cook_receipt,
            bindings={'editor_manifest_sha256': self.editor_package.manifest_sha256,
                      'cooked_manifest_sha256': self.cooked_package.manifest_sha256,
                      'source_sha256': self.source_xodr.sha256})
        return True

    def verify_runtime(self) -> bool:
        self.verify_cooked_package()
        runtime = self.runtime_identity
        self._expect(normalized_map_path(runtime.requested_map), normalized_map_path(runtime.reported_map), 'requested/reported world')
        self._expect(runtime.normalized_map_id, normalized_map(runtime.reported_map), 'normalized world identity')
        self._expect(runtime.normalized_map_id, normalized_map(self.logical_map_id), 'logical/runtime map ID')
        self._expect(runtime.package_manifest_sha256, self.cooked_package.manifest_sha256, 'runtime cooked package hash')
        if runtime.xodr_sha256_if_retrievable is not None:
            self._expect(runtime.xodr_sha256_if_retrievable, self.source_xodr.sha256, 'RPC XODR digest')
        if not runtime.carla_server_version:
            raise MapAuthorityError('Missing CARLA server version')
        try:
            require_digest(runtime.executable_sha256, 'executable_sha256')
            exe_path = safe_artifact(self._root(), runtime.executable_path)
            self._expect(file_sha256(exe_path), runtime.executable_sha256, 'CARLA binary digest')
        except (OSError, ValueError) as exc:
            raise MapAuthorityError(f'Runtime executable: {exc}') from exc
        self._receipt(self.lineage.cook_to_runtime_receipt,
            bindings={'cooked_manifest_sha256': self.cooked_package.manifest_sha256,
                      'reported_map': runtime.reported_map,
                      'requested_map': runtime.requested_map,
                      'executable_sha256': runtime.executable_sha256,
                      'carla_server_version': runtime.carla_server_version})
        return True

    def verify_full_chain(self) -> bool:
        return self.verify_runtime()

    def compare_runtime_to_source(self) -> bool:
        return self.verify_full_chain()

    def export_authority_receipt(self, path: str | Path) -> str:
        self.verify_full_chain()
        receipt = {'schema_version': 1, 'status': 'PASS',
                   'logical_map_id': self.logical_map_id, 'role': self.role,
                   'source_sha256': self.source_xodr.sha256,
                   'editor_manifest_sha256': self.editor_package.manifest_sha256,
                   'cooked_manifest_sha256': self.cooked_package.manifest_sha256,
                   'runtime_executable_sha256': self.runtime_identity.executable_sha256,
                   'lineage': asdict(self.lineage)}
        return write_immutable_json(path, receipt)


def create_lineage_receipt(root: Path, path: str, **claims: str) -> str:
    """Fixtures/integration helper; callers MUST obtain claims from real tool evidence."""
    return write_immutable_json(safe_artifact(root, path), {'status': 'PASS', **claims})
