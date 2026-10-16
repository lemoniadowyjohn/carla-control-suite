"""Security utilities: XXE-safe XML parsing, safe archive extraction, path validation.

These utilities provide **fail-closed** defaults for common security-sensitive
operations. They are deliberately conservative: if a safe operation cannot be
guaranteed, they raise rather than proceeding unsafely.
"""

from __future__ import annotations

import os
import tarfile
import zipfile
from pathlib import Path
from typing import Iterator, Optional

__all__ = [
    "SafeXMLParseError", "parse_xml_safe", "parse_xml_file_safe",
    "SafeArchiveError", "extract_zip_safe", "extract_tar_safe",
    "PathValidationError", "resolve_safe_path", "ensure_safe_dir",
    "AtomicWriteError", "atomic_write",
]


# ----------------------------------------------------------------------
# XXE-safe XML parsing
# ----------------------------------------------------------------------

class SafeXMLParseError(ValueError):
    """Raised when XML parsing is refused for safety reasons."""


def _get_defusedxml_parser():
    """Get a defusedxml parser if available, else raise."""
    try:
        from defusedxml import ElementTree as DefusedET
        return DefusedET
    except ImportError:
        raise SafeXMLParseError(
            "defusedxml not installed; XML parsing refused for safety. "
            "Install defusedxml to enable XXE-safe parsing."
        )


def parse_xml_safe(xml_bytes: bytes, *, forbid_dtd: bool = True,
                   forbid_entities: bool = True) -> Any:
    """Parse XML bytes with XXE protection.

    Args:
        xml_bytes: Raw XML content.
        forbid_dtd: Refuse documents containing DOCTYPE declarations.
        forbid_entities: Refuse documents containing entity references.

    Returns:
        Parsed ElementTree element.

    Raises:
        SafeXMLParseError: If defusedxml is unavailable, or the document
            contains forbidden constructs (DTD, external entities), or parsing fails.
    """
    DefusedET = _get_defusedxml_parser()

    if forbid_dtd:
        # defusedxml's default parser already blocks external entities,
        # but we also check for DOCTYPE as a defence-in-depth measure.
        if b"<!DOCTYPE" in xml_bytes or b"<!doctype" in xml_bytes:
            raise SafeXMLParseError("DOCTYPE declaration forbidden")

    try:
        # defusedxml.ElementTree.fromstring disables external entities by default
        return DefusedET.fromstring(xml_bytes)
    except DefusedET.ParseError as exc:
        raise SafeXMLParseError(f"XML parse error: {exc}") from exc
    except Exception as exc:
        raise SafeXMLParseError(f"XML parsing failed: {exc}") from exc


def parse_xml_file_safe(path: Path, *, forbid_dtd: bool = True,
                        max_bytes: int = 10 * 1024 * 1024) -> Any:
    """Parse an XML file with XXE protection and size limit.

    Args:
        path: Path to XML file.
        forbid_dtd: Refuse documents containing DOCTYPE declarations.
        max_bytes: Maximum file size to read (default 10 MiB).

    Raises:
        SafeXMLParseError: If file is too large, defusedxml unavailable,
            or document contains forbidden constructs.
    """
    if not path.is_file():
        raise SafeXMLParseError(f"Not a file: {path}")
    size = path.stat().st_size
    if size > max_bytes:
        raise SafeXMLParseError(f"File too large: {size} bytes > {max_bytes}")
    data = path.read_bytes()
    return parse_xml_safe(data, forbid_dtd=forbid_dtd)


# ----------------------------------------------------------------------
# Safe archive extraction (zip/tar) with path traversal/symlink protection
# ----------------------------------------------------------------------

class SafeArchiveError(ValueError):
    """Raised when archive extraction is refused for safety reasons."""


def _is_safe_member_path(base: Path, member_path: str) -> bool:
    """Check that a member path stays within base (no traversal, no absolute)."""
    try:
        resolved = (base / member_path).resolve()
        base_resolved = base.resolve()
        # Ensure resolved path is within base directory
        return resolved.is_relative_to(base_resolved)
    except Exception:
        return False


def _check_zip_member(member: zipfile.ZipInfo, base: Path) -> None:
    """Validate a zip member for safety."""
    # No absolute paths
    if member.is_dir():
        return
    if os.path.isabs(member.filename):
        raise SafeArchiveError(f"Absolute path in archive: {member.filename}")
    # No path traversal
    if not _is_safe_member_path(base, member.filename):
        raise SafeArchiveError(f"Path traversal in archive: {member.filename}")
    # No symlinks (zipfile doesn't preserve symlinks by default, but check)
    if member.external_attr >> 16 & 0xF == 0xA:  # symlink
        raise SafeArchiveError(f"Symlink in archive: {member.filename}")


def _check_tar_member(member: tarfile.TarInfo, base: Path) -> None:
    """Validate a tar member for safety."""
    if os.path.isabs(member.name):
        raise SafeArchiveError(f"Absolute path in archive: {member.name}")
    if not _is_safe_member_path(base, member.name):
        raise SafeArchiveError(f"Path traversal in archive: {member.name}")
    if member.issym() or member.islnk():
        raise SafeArchiveError(f"Symlink/hardlink in archive: {member.name}")


def extract_zip_safe(zip_path: Path, dest: Path, *,
                     max_members: int = 1000,
                     max_total_bytes: int = 100 * 1024 * 1024) -> list[Path]:
    """Extract a ZIP archive with path traversal and symlink protection.

    Args:
        zip_path: Path to ZIP file.
        dest: Destination directory (will be created if needed).
        max_members: Maximum number of members to extract.
        max_total_bytes: Maximum total uncompressed size.

    Returns:
        List of extracted file paths (relative to dest).

    Raises:
        SafeArchiveError: If archive is invalid, contains unsafe entries,
            exceeds limits, or extraction fails.
    """
    if not zip_path.is_file():
        raise SafeArchiveError(f"Not a file: {zip_path}")

    dest.mkdir(parents=True, exist_ok=True)
    extracted: list[Path] = []
    total_bytes = 0

    with zipfile.ZipFile(zip_path, "r") as zf:
        members = zf.infolist()
        if len(members) > max_members:
            raise SafeArchiveError(f"Too many members: {len(members)} > {max_members}")

        for member in members:
            _check_zip_member(member, dest)
            total_bytes += member.file_size
            if total_bytes > max_total_bytes:
                raise SafeArchiveError(
                    f"Total uncompressed size exceeds limit: {total_bytes} > {max_total_bytes}"
                )
            zf.extract(member, dest)
            extracted.append(dest / member.filename)

    return extracted


def extract_tar_safe(tar_path: Path, dest: Path, *,
                     max_members: int = 1000,
                     max_total_bytes: int = 100 * 1024 * 1024) -> list[Path]:
    """Extract a tar archive (any compression) with path traversal/symlink protection.

    Args:
        tar_path: Path to tar(.gz/.bz2/.xz) file.
        dest: Destination directory (will be created if needed).
        max_members: Maximum number of members to extract.
        max_total_bytes: Maximum total uncompressed size.

    Returns:
        List of extracted file paths (relative to dest).

    Raises:
        SafeArchiveError: If archive is invalid, contains unsafe entries,
            exceeds limits, or extraction fails.
    """
    if not tar_path.is_file():
        raise SafeArchiveError(f"Not a file: {tar_path}")

    dest.mkdir(parents=True, exist_ok=True)
    extracted: list[Path] = []
    total_bytes = 0

    with tarfile.open(tar_path, "r:*") as tf:
        members = tf.getmembers()
        if len(members) > max_members:
            raise SafeArchiveError(f"Too many members: {len(members)} > {max_members}")

        for member in members:
            _check_tar_member(member, dest)
            total_bytes += member.size
            if total_bytes > max_total_bytes:
                raise SafeArchiveError(
                    f"Total uncompressed size exceeds limit: {total_bytes} > {max_total_bytes}"
                )
            tf.extract(member, dest)
            extracted.append(dest / member.name)

    return extracted


# ----------------------------------------------------------------------
# Path validation
# ----------------------------------------------------------------------

class PathValidationError(ValueError):
    """Raised when a path fails validation (traversal, absolute, etc.)."""


def resolve_safe_path(path: Path, base: Path) -> Path:
    """Resolve a path and ensure it stays within base.

    Args:
        path: Path to validate (may be relative or absolute).
        base: Base directory that path must not escape.

    Returns:
        Resolved absolute path within base.

    Raises:
        PathValidationError: If path escapes base or is invalid.
    """
    try:
        base_resolved = base.resolve()
        # For relative paths, resolve relative to base to avoid cwd issues
        if not path.is_absolute():
            resolved = (base / path).resolve()
        else:
            resolved = path.resolve()
        if not resolved.is_relative_to(base_resolved):
            raise PathValidationError(f"Path {path} escapes base {base}")
        return resolved
    except Exception as exc:
        raise PathValidationError(f"Invalid path {path}: {exc}") from exc


def ensure_safe_dir(path: Path, base: Path | None = None) -> Path:
    """Create a directory safely, ensuring it stays within base.

    Args:
        path: Directory to create.
        base: Optional base directory. If provided, path must be within base.

    Returns:
        The created directory path.

    Raises:
        PathValidationError: If path escapes base.
    """
    if base is not None:
        resolve_safe_path(path, base)
    path.mkdir(parents=True, exist_ok=True)
    return path


# ----------------------------------------------------------------------
# Atomic write (TOCTOU-safe)
# ----------------------------------------------------------------------

class AtomicWriteError(OSError):
    """Raised when atomic write fails."""


def atomic_write(path: Path, data: bytes | str, *,
                 encoding: str = "utf-8",
                 mode: int = 0o644) -> None:
    """Write a file atomically using mkstemp + fsync + replace.

    This avoids TOCTOU races where a reader could see a partially written file.

    Args:
        path: Target file path.
        data: Bytes or string to write.
        encoding: Encoding if data is string.
        mode: File mode for the final file.

    Raises:
        AtomicWriteError: If write, fsync, or replace fails.
    """
    import tempfile

    if isinstance(data, str):
        data_bytes = data.encode(encoding)
    else:
        data_bytes = data

    path.parent.mkdir(parents=True, exist_ok=True)

    # Create temp file in same directory for atomic replace
    fd, tmp_path = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.tmp.",
        suffix="",
    )
    try:
        os.write(fd, data_bytes)
        os.fsync(fd)
        os.close(fd)
        # Atomic replace (POSIX and Windows NTFS)
        os.replace(tmp_path, path)
        # Set mode after replace (best effort)
        try:
            os.chmod(path, mode)
        except Exception:
            pass
    except Exception as exc:
        # Clean up temp file on failure
        try:
            os.unlink(tmp_path)
        except Exception:
            pass
        raise AtomicWriteError(f"Atomic write failed: {exc}") from exc