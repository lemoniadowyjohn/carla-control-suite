"""V94 release publication authority (candidate patch; requires verified F1 lease).

A generic signature.json PASS, legacy SUCCESS.txt, candidate artifact PUBLISHED,
experiment-valid receipt, or a standalone final verdict is NOT a release.
The sole release authority is release_commit.json *and its revalidated evidence*.

No cryptographic claim is made against an attacker able to rewrite every file.
The fenced generation claim protects cooperating repository writers; an external
process with arbitrary filesystem rights can defeat a userspace freeze.
"""
from __future__ import annotations

import hashlib
import json
import os
import stat
import uuid
from pathlib import Path
from typing import Any, Mapping

COMMIT_FILE = "release_commit.json"
COMMIT_SCHEMA = "terminal_release_commit/v1"
COMMIT_PURPOSE = "production_map_release"
HASHED_FILES = (
    "run_identity.json",
    "map_acceptance.json",
    "final_artifact_receipt.json",
    "pipeline_health_summary.json",
    "final_run_verdict.json",
    "signature.json",
    "run_status.json",
)
MAX_JSON_BYTES = 16 * 1024 * 1024


class ReleaseAuthorityError(RuntimeError):
    """Release is unavailable, stale or contradicted by durable evidence."""


def _fail(message: str) -> None:
    raise ReleaseAuthorityError(f"TERMINAL_FAILED(RELEASE_AUTHORITY): {message}")


def _canonical_json(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"),
                       ensure_ascii=True, allow_nan=False) + "\n").encode("utf-8")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        if path.is_symlink() or not path.is_file():
            _fail(f"not a regular file: {path}")
        with path.open("rb") as stream:
            identity = os.fstat(stream.fileno())
            if not stat.S_ISREG(identity.st_mode):
                _fail(f"not a regular file: {path}")
            while True:
                chunk = stream.read(1024 * 1024)
                if not chunk:
                    break
                digest.update(chunk)
            after = os.fstat(stream.fileno())
            if (identity.st_dev, identity.st_ino, identity.st_size,
                identity.st_mtime_ns, identity.st_ctime_ns) != (
                after.st_dev, after.st_ino, after.st_size,
                after.st_mtime_ns, after.st_ctime_ns):
                _fail(f"file changed during digest: {path}")
    except OSError as exc:
        _fail(f"unable to hash {path.name}: {exc}")
    return digest.hexdigest()


def _json(path: Path) -> dict[str, Any]:
    try:
        if path.is_symlink() or not path.is_file():
            _fail(f"required receipt missing or symlink: {path.name}")
        with path.open("rb") as f:
            data = f.read(MAX_JSON_BYTES + 1)
        if len(data) > MAX_JSON_BYTES:
            _fail(f"receipt exceeds bounded read: {path.name}")
        result = json.loads(data)
    except (OSError, ValueError, UnicodeError) as exc:
        _fail(f"unreadable receipt {path.name}: {exc}")
    if type(result) is not dict:
        _fail(f"receipt must be JSON object: {path.name}")
    return result


def _inside(root: Path, value: str) -> Path:
    if not isinstance(value, str) or not value.strip():
        _fail("artifact path absent")
    target = Path(value)
    unresolved = target if target.is_absolute() else root / target
    cursor = unresolved
    while cursor != root and cursor != cursor.parent:
        if cursor.is_symlink():
            _fail("symlinked release artifact path component")
        cursor = cursor.parent
    candidate = unresolved.resolve()
    if not candidate.is_relative_to(root) or candidate == root:
        _fail("artifact path escapes output root")
    if candidate.is_symlink() or not candidate.is_file():
        _fail("artifact missing, symlink or not regular")
    # Reject symlink components, even those resolving back inside root.
    cursor = candidate
    while cursor != root:
        if cursor.is_symlink():
            _fail("symlinked release artifact")
        cursor = cursor.parent
    return candidate


def _require(condition: bool, message: str) -> None:
    if not condition:
        _fail(message)


def _mandatory_gates() -> tuple[str, ...]:
    from ultimate_pipeline.quality.final_artifact_gates import RELEASE_MANDATORY_GATES
    return tuple(RELEASE_MANDATORY_GATES)


def _identity(root: Path) -> dict[str, Any]:
    result = _json(root / "run_identity.json")
    # UUID has been used by MainPipeline since Phase 6. Historic basename IDs
    # are never release-certified by the V94 resolver.
    value = result.get("run_id")
    _require(isinstance(value, str) and len(value) == 32
             and all(c in "0123456789abcdef" for c in value.lower()),
             "run_id must be a fresh 32-character UUID hex")
    source = result.get("source_sha")
    _require(isinstance(source, str) and len(source) == 40
             and all(c in "0123456789abcdef" for c in source.lower()),
             "source_sha must be the concrete 40-character implementation SHA")
    _require(isinstance(result.get("profile"), str) and bool(result["profile"]),
             "release profile missing")
    _require(isinstance(result.get("settings_digest"), str)
             and len(result["settings_digest"]) == 64, "settings digest missing")
    return result


def validate_release_candidate(
    out_dir: str | os.PathLike[str], final_xodr: str | os.PathLike[str], *,
    require_status: bool = True, require_success: bool = True,
) -> dict[str, Any]:
    """Re-read and bind all candidate evidence. No authority is issued here.

    This is usable without CARLA, with synthetic fixtures; it is *not* an
    endorsement of an unreviewed lease implementation.
    """
    root = Path(out_dir).expanduser().resolve()
    final_path = _inside(root, str(final_xodr))
    identity = _identity(root)
    run_id = identity["run_id"]
    map_sha = _sha256(final_path)
    acceptance = _json(root / "map_acceptance.json")
    _require(acceptance.get("run_id") == run_id, "acceptance run_id mismatch")
    _require(acceptance.get("valid_for_experiments") is True, "experiment validation failed")
    _require(acceptance.get("release_eligible") is True, "not release eligible")
    policy = acceptance.get("acceptance_policy")
    _require(type(policy) is dict and policy.get("purpose") == "release",
             "diagnostic/legacy acceptance cannot release")
    from ultimate_pipeline.quality.final_artifact_gates import ACCEPTANCE_POLICY_VERSION
    _require(policy.get("policy_version") == ACCEPTANCE_POLICY_VERSION,
             "release acceptance policy version does not match the active gate implementation")
    required = _mandatory_gates()
    supplied = acceptance.get("mandatory_gates")
    _require(type(supplied) is list and len(supplied) == len(required)
             and set(supplied) == set(required), "mandatory gate set differs from canonical policy")
    statuses = acceptance.get("mandatory_gate_status")
    _require(type(statuses) is dict and set(statuses) == set(required)
             and all(statuses.get(gate) == "PASS" for gate in required),
             "a mandatory quality gate is missing or not PASS")
    for name in ("final_xodr_sha256", "evaluated_xodr_sha256"):
        _require(acceptance.get(name) == map_sha, f"{name} does not bind physical map bytes")
    _require(_inside(root, str(acceptance.get("final_xodr_path"))) == final_path,
             "acceptance references another final XODR")
    receipt = _json(root / "final_artifact_receipt.json")
    _require(receipt.get("run_id") == run_id, "artifact receipt run_id mismatch")
    _require(receipt.get("publication_status") == "PUBLISHED",
             "artifact candidate receipt not marked ready")
    final_ref = receipt.get("final_xodr")
    _require(type(final_ref) is dict and final_ref.get("sha256") == map_sha,
             "candidate receipt map SHA mismatch")
    _require(_inside(root, str(final_ref.get("path"))) == final_path,
             "candidate receipt points to other map")
    _require(type(final_ref.get("bytes")) is int and final_ref["bytes"] == final_path.stat().st_size,
             "candidate receipt map byte count mismatch")
    acc_ref = receipt.get("acceptance_receipt")
    _require(type(acc_ref) is dict and acc_ref.get("sha256") == _sha256(root / "map_acceptance.json"),
             "candidate receipt acceptance digest mismatch")
    _require(_inside(root, str(acc_ref.get("path"))) == root / "map_acceptance.json",
             "candidate receipt acceptance path mismatch")
    state = receipt.get("capability_state")
    _require(type(state) is dict and type(state.get("held")) is list
             and {"STRUCTURE_FROZEN", "FINAL_ARTIFACT_PUBLISHED"}.issubset(set(state["held"])),
             "candidate stage ledger not frozen/published")
    topology = receipt.get("topology_certification")
    _require(type(topology) is dict and topology.get("SPEC_TOPOLOGY") == "PASS",
             "literal topology certification is not PASS")
    source_manifest = receipt.get("source_manifest")
    _require(type(source_manifest) is dict and isinstance(source_manifest.get("sha256"), str)
             and len(source_manifest["sha256"]) == 64, "pinned input manifest hash missing")
    manifest_path = source_manifest.get("path")
    _require(isinstance(manifest_path, str) and bool(manifest_path), "source manifest path absent")
    path = Path(manifest_path)
    if not path.is_absolute():
        path = root / path
    _require(_sha256(path) == source_manifest["sha256"], "input manifest bytes changed")
    verdict = _json(root / "final_run_verdict.json")
    _require(verdict.get("status") == "PASS", "final verdict is not PASS")
    _require(verdict.get("run_id") == run_id, "final verdict run_id mismatch")
    _require(verdict.get("release_profile") == identity["profile"], "verdict profile mismatch")
    _require(not verdict.get("blocking_failures") and not verdict.get("blocked_external"),
             "final verdict contains blockers")
    health = _json(root / "pipeline_health_summary.json")
    _require(health.get("overall_ok") is True, "health is not exact boolean PASS")
    if require_status:
        status = _json(root / "run_status.json")
        _require(status.get("run_id") == run_id
                 and status.get("status") == "ok" and status.get("stage") == "done",
                 "run status must bind current run and terminal completion")
    from ultimate_pipeline.utils.finalize_run_pack import verify_run_pack
    pack_result = verify_run_pack(root)
    _require(pack_result.get("status") == "PASS", "run pack physical verification FAIL")
    manifest = _json(root / "signature.json")
    files = manifest.get("files")
    _require(type(files) is dict, "signature manifest has no file digest map")
    for key in ("map_acceptance.json", "final_artifact_receipt.json", "final_run_verdict.json",
                "pipeline_health_summary.json"):
        _require(files.get(key) == _sha256(root / key), f"mandatory signature omits/stales {key}")
    # Both absolute and relative final path keys may appear in old pack
    # normalization; the actual digest must be present, not merely a filename.
    _require(map_sha in files.values(), "final map not present in mandatory signed pack")
    if require_success:
        _require((root / "SUCCESS.txt").is_file(), "SUCCESS marker absent")
    bindings = {key: _sha256(root / key) for key in HASHED_FILES if (root / key).is_file()}
    required_bindings = set(HASHED_FILES) if require_status else set(HASHED_FILES) - {"run_status.json"}
    _require(required_bindings.issubset(bindings), "required terminal evidence missing")
    return {"root": root, "run_id": run_id, "map_sha256": map_sha,
            "map_relpath": final_path.relative_to(root).as_posix(),
            "source_sha": identity["source_sha"], "profile": identity["profile"],
            "settings_sha256": identity["settings_digest"],
            "bindings": bindings, "mandatory_gates": list(required)}


def _fsync_dir(path: Path) -> None:
    if os.name != "nt":
        fd = os.open(path, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


def _atomic_json(target: Path, payload: Mapping[str, Any]) -> None:
    parent = target.parent
    temp = parent / f".{target.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp"
    raw = _canonical_json(dict(payload))
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(raw)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp, target)
        _fsync_dir(parent)
    except BaseException:
        try:
            temp.unlink(missing_ok=True)
        except OSError:
            pass
        raise


def revoke_previous_commit(root: str | os.PathLike[str]) -> None:
    """Call only while holding the new output-root publication lease."""
    path = Path(root).expanduser().resolve() / COMMIT_FILE
    try:
        path.unlink(missing_ok=True)
        _fsync_dir(path.parent)
    except OSError as exc:
        _fail(f"cannot revoke previous terminal commit: {exc}")


def _generation_highwater(root: Path) -> int:
    """Fail closed on a malformed fenced-generation ledger."""
    from ultimate_pipeline.governance.single_writer.worktree_lock import _ledger_path
    path = _ledger_path(root)
    try:
        lines = path.read_text(encoding="ascii").splitlines()
    except (OSError, UnicodeError) as exc:
        _fail(f"generation ledger unavailable: {exc}")
    if not lines or any(not x.isdecimal() for x in lines):
        _fail("generation ledger is missing/malformed")
    values = [int(x) for x in lines]
    if any(b <= a for a, b in zip(values, values[1:])):
        _fail("generation ledger is not monotonically increasing")
    return values[-1]


def _assert_lease(lease: Any, root: Path) -> None:
    from ultimate_pipeline.governance.single_writer.worktree_lock import lease_is_current
    _require(type(lease.generation) is int and lease.generation > 0,
             "fencing generation missing")
    _require(Path(lease.worktree_root).resolve() == root, "lease belongs to different root")
    _require(bool(lease.lease_id) and bool(lease.owner_token), "lease token missing")
    _require(lease_is_current(lease), "lease was lost or superseded")
    _require(_generation_highwater(root) == lease.generation,
             "generation ledger differs from held publication lease")


def publish_terminal_release(
    out_dir: str | os.PathLike[str], final_xodr: str | os.PathLike[str], lease: Any,
) -> dict[str, Any]:
    """Publish one authoritative commit pointer inside the fenced generation claim.

    Call only after MainPipeline has published/verified the compatibility
    SUCCESS marker. No network, CARLA or environmental side effects here.
    """
    from ultimate_pipeline.governance.single_writer.worktree_lock import _generation_claim
    root = Path(out_dir).expanduser().resolve()
    with _generation_claim(root):
        _assert_lease(lease, root)
        snapshot = validate_release_candidate(root, final_xodr)
        commit = {
            "schema": COMMIT_SCHEMA,
            "purpose": COMMIT_PURPOSE,
            "status": "COMMITTED",
            "run_id": snapshot["run_id"],
            "source_sha": snapshot["source_sha"],
            "profile": snapshot["profile"],
            "settings_sha256": snapshot["settings_sha256"],
            "final_xodr": {"path": snapshot["map_relpath"],
                           "sha256": snapshot["map_sha256"]},
            "mandatory_gates": snapshot["mandatory_gates"],
            "lease": {"lease_id": lease.lease_id,
                      "generation": lease.generation,
                      "owner_token_sha256": hashlib.sha256(lease.owner_token.encode()).hexdigest()},
            "bindings": snapshot["bindings"],
            "success_sha256": _sha256(root / "SUCCESS.txt"),
        }
        # Atomic rename is the sole authoritative commit point; the commit
        # never hashes itself and the manifest never hashes the commit.
        _atomic_json(root / COMMIT_FILE, commit)
        try:
            resolve_terminal_release(root, expected_generation=lease.generation)
        except BaseException:
            # The publisher still holds its claim: revoke only its own record.
            try:
                (root / COMMIT_FILE).unlink(missing_ok=True)
                _fsync_dir(root)
            except OSError:
                pass
            raise
        return commit


def resolve_terminal_release(
    out_dir: str | os.PathLike[str], *, expected_generation: int | None = None,
) -> Path:
    """The only public release-grade resolver; never trust raw SUCCESS alone."""
    root = Path(out_dir).expanduser().resolve()
    commit = _json(root / COMMIT_FILE)
    _require(commit.get("schema") == COMMIT_SCHEMA and
             commit.get("purpose") == COMMIT_PURPOSE and
             commit.get("status") == "COMMITTED", "unsupported/weak terminal commit")
    lease = commit.get("lease")
    _require(type(lease) is dict and type(lease.get("generation")) is int
             and lease["generation"] > 0, "terminal lease generation invalid")
    if expected_generation is not None:
        _require(lease["generation"] == expected_generation, "terminal generation mismatched")
    _require(_generation_highwater(root) == lease["generation"],
             "terminal release superseded by later generation")
    path_ref = commit.get("final_xodr")
    _require(type(path_ref) is dict and isinstance(path_ref.get("path"), str),
             "terminal final artifact path missing")
    final_path = _inside(root, path_ref["path"])
    check = validate_release_candidate(root, final_path)
    _require(check["run_id"] == commit.get("run_id"), "terminal run identity changed")
    _require(check["source_sha"] == commit.get("source_sha") and
             check["profile"] == commit.get("profile") and
             check["settings_sha256"] == commit.get("settings_sha256"),
             "terminal source/profile/settings changed")
    _require(check["map_sha256"] == path_ref.get("sha256"),
             "terminal map bytes changed")
    _require(commit.get("mandatory_gates") == check["mandatory_gates"],
             "terminal gate policy changed")
    _require(commit.get("bindings") == check["bindings"],
             "terminal evidence bytes changed")
    _require(commit.get("success_sha256") == _sha256(root / "SUCCESS.txt"),
             "SUCCESS changed or replaced")
    return final_path
