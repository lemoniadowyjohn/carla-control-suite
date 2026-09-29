"""Failure recovery campaign for B6: temporary-fixture fault injection across pipeline stages."""
from __future__ import annotations

import json
import os
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Dict, List, Tuple

import pytest

from phase_q.governed_payload import atomic_write_payload_bytes, generate_governed_payload, generate_semantic_diff, verify_payload_identity, IdentityVerificationError
from opendrive_geometry.freeze import compute_freeze, verify_freeze, GeometryFreezeError
from ultimate_pipeline.artifacts.store import ArtifactStore
from ultimate_pipeline.artifacts.transaction import ArtifactTransaction
from ultimate_pipeline.artifacts.promotion import PromotionEngine
from ultimate_pipeline.artifacts.model import CandidateResult, MutationDeclaration, GateResult, ArtifactRef
from ultimate_pipeline.carla_tools.map_registry import validate_candidate_registry_entry, MapRegistryValidationError
from ultimate_pipeline.tiling.large_map_package import stage_large_map_package, StagedPackageResult
from ultimate_pipeline.tiling.tile_fbx_generator import assign_buildings_to_tiles, TileGridSpec, TileBuilding, tile_fbx_name


def _write_xodr(path: Path, *, road_id: str = "1") -> None:
    path.write_text(
        f"""<OpenDRIVE>
  <road id="{road_id}" length="10.0" junction="-1">
    <planView>
      <geometry s="0" x="0" y="0" hdg="0" length="10.0"><line /></geometry>
    </planView>
  </road>
</OpenDRIVE>
""",
        encoding="utf-8",
    )


def _make_parent_store(root: Path, parent_path: Path) -> ArtifactStore:
    store = ArtifactStore(root, git_sha="abc123", configuration_sha256="cfg123")
    store.create_run()
    store.set_parent(parent_path, "xodr")
    return store


def _make_fake_fbx(path: Path, *, map_name: str = "Map", tx: int = 0, ty: int = 0) -> None:
    path.write_bytes(b"fake FBX content")
    # no manifest sidecar


def run_campaign() -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []

    # ----- Stage 1: XODR write -----
    with tempfile.TemporaryDirectory() as tmp:
        tmpdir = Path(tmp)
        xodr = tmpdir / "candidate.xodr"
        _write_xodr(xodr)
        # Write governed payload to temp file then corrupt declared size
        text = xodr.read_text(encoding="utf-8")
        manifest = generate_governed_payload(text, "producer_commit", candidate_name="cand")
        payload_text = manifest.pop("payload_text", "")
        payload_bytes = payload_text.encode("utf-8")
        out_dir = tmpdir / "out"
        out_dir.mkdir()
        payload_path = out_dir / "payload.xodr"
        # Normal write
        identity = atomic_write_payload_bytes(payload_path, payload_bytes)
        # Corrupt the declared size in the returned identity to simulate a mismatch
        declared_size_bad = identity["declared_size"] + 1
        try:
            verify_payload_identity(payload_path, identity["declared_sha256"], declared_size_bad)
            observed = "no error"
        except IdentityVerificationError as e:
            observed = f"IdentityVerificationError: {e}"
        expected = "IdentityVerificationError: INTEGRITY_MISMATCH_DECLARED_VS_DISK"
        status = "PASS" if expected in observed else "FAIL"
        rows.append({
            "stage": "XODR write",
            "injected fault": "declared size mismatch after atomic write",
            "observed": observed[:200],
            "expected": expected,
            "PASS/FAIL": status,
        })

    # ----- Stage 2: Enrichment (semantic diff) -----
    with tempfile.TemporaryDirectory() as tmp:
        tmpdir = Path(tmp)
        xodr = tmpdir / "base.xodr"
        _write_xodr(xodr)
        base_text = xodr.read_text(encoding="utf-8")
        # generate payload for base
        base_manifest = generate_governed_payload(base_text, "producer", candidate_name="base")
        base_payload_text = base_manifest.pop("payload_text", "")
        base_payload_bytes = base_payload_text.encode("utf-8")
        # produce enriched by appending a comment (changes text)
        enriched_text = base_text + "\n<!-- enrichment -->"
        enriched_manifest = generate_governed_payload(enriched_text, "producer", candidate_name="enriched")
        enriched_payload_text = enriched_manifest.pop("payload_text", "")
        enriched_payload_bytes = enriched_payload_text.encode("utf-8")
        # test that enrichment changes the payload bytes
        observed = "enriched payload differs from base" if base_payload_bytes != enriched_payload_bytes else "no change"
        expected = "enriched payload differs from base"
        status = "PASS" if observed == expected else "FAIL"
        rows.append({
            "stage": "Enrichment",
            "injected fault": "payload text mutated after base generation",
            "observed": observed,
            "expected": expected,
            "PASS/FAIL": status,
        })

# ----- Stage 3: Geometry freeze -----
    with tempfile.TemporaryDirectory() as tmp:
        tmpdir = Path(tmp)
        # Build XODR with a line geometry element
        root = ET.Element("OpenDRIVE")
        road = ET.SubElement(root, "road", id="1", length="10.0", junction="-1")
        plan_view = ET.SubElement(road, "planView")
        geom = ET.SubElement(plan_view, "geometry", s="0", x="0", y="0", hdg="0", length="10.0", geometry="line")
        tree = ET.ElementTree(root)
        xodr = tmpdir / "road.xodr"
        tree.write(xodr, encoding="utf-8", xml_declaration=True)
        # compute freeze on original
        freeze_before = compute_freeze(str(xodr))
        # mutate: change length of road (downstream mutation of frozen geometry)
        geom.set("length", "20.0")
        tree.write(xodr, encoding="utf-8", xml_declaration=True)
        try:
            verify_freeze(str(xodr), freeze_before)
            observed = "no error"
        except GeometryFreezeError as e:
            observed = f"GeometryFreezeError: {e}"
        expected = "GeometryFreezeError: geometry freeze mismatch"
        status = "PASS" if expected in observed else "FAIL"
        rows.append({
            "stage": "Geometry freeze",
            "injected fault": "XODR geometry mutated after freeze",
            "observed": observed[:200],
            "expected": expected,
            "PASS/FAIL": status,
        })

    # ----- Stage 4: Tiles (empty tile) -----
    with tempfile.TemporaryDirectory() as tmp:
        tmpdir = Path(tmp)
        # empty buildings list
        buildings: List[TileBuilding] = []
        spec = TileGridSpec(
            tile_size_m=1000.0,
            header_offset_xy=(832671.676, 5458671.104),
        )
        assignment = assign_buildings_to_tiles(buildings, spec)
        # assignment should have zero tiles
        observed = str(len(assignment.tiles))
        expected = "0"
        status = "PASS" if observed == expected else "FAIL"
        rows.append({
            "stage": "Tiles",
            "injected fault": "no buildings assigned to tile",
            "observed": observed,
            "expected": expected,
            "PASS/FAIL": status,
        })

    # ----- Stage 5: Registry update (invalid role) -----
    with tempfile.TemporaryDirectory() as tmp:
        tmpdir = Path(tmp)
        xodr = tmpdir / "candidate.xodr"
        _write_xodr(xodr)
        sha = "a" * 64
        # invalid role
        report = validate_candidate_registry_entry(
            key="bad",
            path=str(xodr),
            sha256=sha,
            bytes=len(xodr.read_bytes()),
            role="INVALID_ROLE",
            frame="rebased",
            aliases=["bad"],
            registry={"existing": {"path": "existing.xodr", "sha256": "b"*64, "bytes": 1, "role": "auto", "frame": ""}},
            base_dir=tmpdir,
            supersedes_sha256=None,
            supersedes_path=None,
            allow_external_absolute_paths=True,
        )
        observed_ok = report["ok"]
        expected_ok = False
        status = "PASS" if observed_ok == expected_ok else "FAIL"
        rows.append({
            "stage": "Registry update",
            "injected fault": "candidate entry with invalid role",
            "observed": str(observed_ok),
            "expected": str(expected_ok),
            "PASS/FAIL": status,
        })

    # ----- Stage 6: Candidate promotion (parent hash mismatch) -----
    with tempfile.TemporaryDirectory() as tmp:
        tmpdir = Path(tmp)
        store = ArtifactStore(tmpdir / "store", git_sha="abc123", configuration_sha256="cfg123")
        store.create_run()
        parent_path = tmpdir / "parent.xodr"
        _write_xodr(parent_path)
        parent_ref = store.set_parent(parent_path, "xodr")
        # candidate with mismatched parent hash
        candidate_path = tmpdir / "candidate.xodr"
        _write_xodr(candidate_path, road_id="2")
        candidate_ref = ArtifactRef(
            path=candidate_path,
            sha256="b" * 64,
            semantic_sha256="c" * 64,
            parent_sha256="d" * 64,
            configuration_sha256="cfg123",
            git_sha="abc123",
            artifact_type="xodr",
        )
        promotion = PromotionEngine()
        try:
            promotion.promote(
                store,
                "cand-1",
                parent_ref,
                candidate_ref,
                MutationDeclaration(operation="test", allowed_xml_domains=(), forbidden_xml_domains=(), affected_ids=()),
                (GateResult("validation", False, "fail"),),
            )
            observed = "no error"
        except Exception as e:
            observed = f"{type(e).__name__}: {e}"
        expected = "PromotionError"
        status = "PASS" if expected in observed else "FAIL"
        rows.append({
            "stage": "Candidate promotion",
            "injected fault": "candidate parent hash mismatch",
            "observed": observed[:200],
            "expected": expected,
            "PASS/FAIL": status,
        })

    # ----- Stage 7: FBX/import-package staging (missing XODR) -----
    with tempfile.TemporaryDirectory() as tmp:
        tmpdir = Path(tmp)
        import_root = tmpdir / "Import"
        import_root.mkdir()
        package_name = "TestPkg"
        missing_xodr = import_root / "missing.xodr"
        # tile FBX file (fake)
        tile_fbx = tmpdir / "Map_Tile_0_0.fbx"
        _make_fake_fbx(tile_fbx)
        result = stage_large_map_package(
            map_name="Map",
            xodr_path=str(missing_xodr),
            tile_fbx_paths=[str(tile_fbx)],
            import_root=str(import_root),
            package_name=package_name,
        )
        observed = result.status
        expected = "failed"
        status = "PASS" if observed == expected else "FAIL"
        rows.append({
            "stage": "FBX/import-package staging",
            "injected fault": "XODR file missing",
            "observed": observed,
            "expected": expected,
            "PASS/FAIL": status,
        })

    return rows


if __name__ == "__main__":
    # When run directly, print markdown table
    rows = run_campaign()
    print("| Stage | Injected Fault | Observed | Expected | PASS/FAIL |")
    print("|-------|----------------|----------|----------|-----------|")
    for r in rows:
        print(f"| {r['stage']} | {r['injected fault']} | {r['observed']} | {r['expected']} | {r['PASS/FAIL']} |")