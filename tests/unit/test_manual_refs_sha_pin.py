"""NEW-291 / GAP-039 -- the manual-XODR SHA256 pin gate must actually reject.

GAP-039 describes NEW-291 as "implemented and wired, but permanently inert
because no manual_xodr_sha256_pin is configured". This test pins down the MECHANISM
separately from the missing production configuration, using temp files, so that:

  * the mechanism is proven to work rather than assumed, and
  * no production pin is invented to make a test pass.

It also documents the deeper defect found on 2026-10-08: both registry entries
point at paths that DO NOT EXIST, so resolve_manual_town() raises
FileNotFoundError before the hash comparison is ever reached. That makes the gate
not merely inert but unreachable.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from ultimate_pipeline.experiments.thesis import manual_refs
from ultimate_pipeline.experiments.thesis.manual_refs import (
    MANUAL_INGOLSTADT_REFS,
    resolve_manual_town,
    sha256_file,
)

GOOD = b"<OpenDRIVE>canonical manual reference bytes</OpenDRIVE>"


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _install_ref(monkeypatch, tmp_path: Path, key: str, payload: bytes, pin):
    """Point one registry entry at a temp file with an optional pin."""
    rel = f"_test_manual_{key}.xodr"
    (tmp_path / rel).write_bytes(payload)
    entry = dict(MANUAL_INGOLSTADT_REFS[key])
    entry["manual_xodr_path"] = rel
    entry["manual_xodr_fallbacks"] = []
    if pin is not None:
        entry["manual_xodr_sha256_pin"] = pin
    else:
        entry.pop("manual_xodr_sha256_pin", None)
    monkeypatch.setitem(MANUAL_INGOLSTADT_REFS, key, entry)
    monkeypatch.setattr(manual_refs, "_repo_root", lambda: tmp_path)
    return tmp_path / rel


# --------------------------------------------------------------------------
# mechanism
# --------------------------------------------------------------------------


def test_matching_pin_passes(monkeypatch, tmp_path: Path) -> None:
    _install_ref(monkeypatch, tmp_path, "Grid0828", GOOD, _sha(GOOD))
    out = resolve_manual_town("Grid0828")
    assert out["manual_xodr_sha256"] == _sha(GOOD)


def test_deliberately_corrupted_copy_is_rejected(monkeypatch, tmp_path: Path) -> None:
    """The test GAP-039 asked for: corrupt the bytes, the gate must fail."""
    _install_ref(monkeypatch, tmp_path, "Grid0828", GOOD, _sha(GOOD))

    # sanity: the untouched file resolves
    assert resolve_manual_town("Grid0828")["manual_xodr_sha256"] == _sha(GOOD)

    # now corrupt it in place, as a bad edit or partial copy would
    (tmp_path / "_test_manual_Grid0828.xodr").write_bytes(GOOD + b"<!-- tampered -->")

    with pytest.raises(RuntimeError, match="SHA256 mismatch"):
        resolve_manual_town("Grid0828")


def test_missing_pin_still_resolves_but_is_unverified(monkeypatch, tmp_path: Path) -> None:
    """Documents the inert-but-working case: hash is reported, nothing enforced."""
    _install_ref(monkeypatch, tmp_path, "Grid0828", GOOD, pin=None)
    out = resolve_manual_town("Grid0828")
    assert out["manual_xodr_sha256"] == _sha(GOOD)


def test_truncated_file_is_rejected(monkeypatch, tmp_path: Path) -> None:
    _install_ref(monkeypatch, tmp_path, "Grid0821", GOOD, _sha(GOOD))
    (tmp_path / "_test_manual_Grid0821.xodr").write_bytes(GOOD[:10])
    with pytest.raises(RuntimeError, match="SHA256 mismatch"):
        resolve_manual_town("Grid0821")


def test_sha256_file_helper(tmp_path: Path) -> None:
    p = tmp_path / "x.bin"
    p.write_bytes(GOOD)
    assert sha256_file(p) == _sha(GOOD)
    assert sha256_file(tmp_path / "absent.bin") == ""


# --------------------------------------------------------------------------
# production configuration reality (documented, not invented)
# --------------------------------------------------------------------------


def test_no_pin_is_configured_in_production_registry() -> None:
    """Records the current GAP-039 state precisely.

    If this starts failing, someone has configured a real pin -- at which point
    the corresponding production files must exist and be verified, not assumed.
    """
    configured = {
        k: v["manual_xodr_sha256_pin"]
        for k, v in MANUAL_INGOLSTADT_REFS.items()
        if v.get("manual_xodr_sha256_pin")
    }
    assert configured == {}, (
        "a production manual_xodr_sha256_pin is now configured; verify the pinned "
        "hash against the real artifact before trusting this suite"
    )


def test_production_registry_paths_are_stale() -> None:
    """Documents the deeper defect found 2026-10-08.

    Neither entry's primary path exists, so resolve_manual_town() raises
    FileNotFoundError before the SHA256 comparison is reached. The gate is not
    merely unconfigured -- it is unreachable. This is reported, not fixed, because
    choosing which artifact is authoritative for a thesis reference map is a
    provenance decision, not a mechanical one.
    """
    root = manual_refs._repo_root()
    missing = []
    for key, entry in MANUAL_INGOLSTADT_REFS.items():
        if not (root / entry["manual_xodr_path"]).is_file():
            missing.append(key)
    assert set(missing) == {"Grid0821", "Grid0828"}, (
        "registry path existence changed; re-verify which manual artifact is "
        f"authoritative before pinning (now missing: {sorted(missing)})"
    )