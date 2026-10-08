"""GAP-051 -- GATE_CLASS_REGISTRY must cover every gate the pipeline emits.

Before this, the registry carried 24 keys while the pipeline emitted 38 distinct
gate names, so only 4 matched and 20 were dead. classify_gate still failed closed,
so nothing was unsafe -- but the taxonomy was decorative rather than authoritative,
and a mis-spelled gate silently inherited the fail-closed default instead of its
intended class.

This test re-derives the emitted set from the source of truth (the same places the
pipeline names gates) and asserts full coverage, so the drift cannot silently
return.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from ultimate_pipeline.contracts.stage_contracts import (
    GATE_CLASS_REGISTRY,
    GATE_CLASS_REGISTRY_ALIASES,
    GateClass,
    NON_WAIVABLE_CLASSES,
    classify_gate,
    GATE_TAXONOMY_RESERVED_NAMES,
    governed_waiver_allowed,
    production_gate_waiver_allowed,
)

REPO = Path(__file__).resolve().parents[2]
QG = REPO / "ultimate_pipeline" / "quality" / "quality_gates.py"
QM = REPO / "ultimate_pipeline" / "quality" / "quality_gate_manager.py"
MP = REPO / "ultimate_pipeline" / "main_pipeline.py"
MA = REPO / "ultimate_pipeline" / "quality" / "map_acceptance.py"


def _emitted_gate_names() -> set[str]:
    """Every gate name the pipeline can actually produce.

    Sources, all of which are places a name becomes a gate identifier:
      * quality_gates.DRIVABILITY_GATES / TRANSPORT_GATES name sets
      * quality_gates._try("<name>", ...) sweep call sites
      * QualityGateManager._finalize_gate("<name>", ...) published keys
      * MainPipeline._stage_gate(..., "<name>", ...) stage gate names
      * map_acceptance `reports.get("<name>")` consumed keys
    """
    found: set[str] = set()

    qg_src = QG.read_text(encoding="utf-8")
    tree = ast.parse(qg_src)
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
            if any(
                t in ("DRIVABILITY_GATES", "TRANSPORT_GATES", "GATES", "ALL_GATES")
                for t in targets
            ):
                for elt in ast.walk(node.value):
                    if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                        found.add(elt.value)
    for m in re.finditer(r'_try\(\s*"([^"]+)"', qg_src):
        found.add(m.group(1))

    qm_src = QM.read_text(encoding="utf-8")
    for m in re.finditer(r"def (gate_[a-z0-9_]+)\(", qm_src):
        tail = qm_src[m.end() : m.end() + 4000]
        key = re.search(r'_finalize_gate\(\s*"([^"]+)"', tail)
        if key:
            found.add(key.group(1))

    mp_src = MP.read_text(encoding="utf-8")
    for m in re.finditer(r'_stage_gate\(\s*"[^"]*"\s*,\s*"([^"]+)"', mp_src):
        found.add(m.group(1))

    ma_src = MA.read_text(encoding="utf-8")
    for m in re.finditer(r'reports\.get\(\s*"([^"]+)"', ma_src):
        found.add(m.group(1))

    # gate_* are internal QualityGateManager method names, not published keys.
    return {n for n in found if n and not n.startswith("_") and not n.startswith("gate_")}


EMITTED = _emitted_gate_names()


def test_emitted_set_is_non_trivial() -> None:
    """Guard against the discovery silently returning nothing."""
    assert len(EMITTED) >= 25, (
        f"gate-name discovery only found {len(EMITTED)} names; the sources it "
        "scans may have moved, which would make the coverage test vacuous"
    )


@pytest.mark.parametrize("name", sorted(EMITTED))
def test_every_emitted_gate_has_an_explicit_registry_entry(name: str) -> None:
    """The core GAP-051 assertion: explicit coverage, not the fail-closed default.

    Checking `name in GATE_CLASS_REGISTRY` rather than
    `classify_gate(name) is not None` is deliberate. classify_gate also resolves
    aliases, so a name served only by an alias would pass while still not being
    registered under the name the pipeline actually emits.
    """
    assert name in GATE_CLASS_REGISTRY, (
        f"gate '{name}' is emitted by the pipeline but has no GATE_CLASS_REGISTRY "
        "entry; it would silently inherit the fail-closed default"
    )


def test_aliases_all_point_at_registered_names() -> None:
    for alias, target in GATE_CLASS_REGISTRY_ALIASES.items():
        assert target in GATE_CLASS_REGISTRY, (
            f"alias '{alias}' -> '{target}' but '{target}' is not registered"
        )
        assert GATE_CLASS_REGISTRY[target] == classify_gate(alias), (
            f"alias '{alias}' resolves to a different class than '{target}'"
        )


def test_registry_has_no_dead_keys() -> None:
    """Every registry key must be emitted, a declared alias, or reserved.

    The other half of GAP-051: 20 of the original 24 keys were never emitted.
    After the fix, the only keys not emitted by the sweep are the reserved
    taxonomy names (waiver payloads / manifest contracts / NEW-210 doc).
    """
    accounted = EMITTED | set(GATE_CLASS_REGISTRY_ALIASES) | set(
        GATE_TAXONOMY_RESERVED_NAMES
    )
    dead = sorted(set(GATE_CLASS_REGISTRY) - accounted)
    assert not dead, (
        "GATE_CLASS_REGISTRY contains keys that are neither emitted by the "
        f"pipeline, nor aliases, nor reserved taxonomy names: {dead}"
    )


def test_reserved_names_are_actually_referenced() -> None:
    """A reserved name must be justified by a real consumer, not by convention.

    This is what distinguished `required_artifact_presence` (cited by the NEW-210
    taxonomy doc) from `topology_spec`, which nothing referenced and which was
    therefore removed.
    """
    import subprocess

    for name in sorted(GATE_TAXONOMY_RESERVED_NAMES):
        out = subprocess.run(
            ["git", "grep", "-l", "--", name],
            cwd=str(REPO),
            capture_output=True,
            text=True,
            timeout=120,
        )
        others = [
            ln
            for ln in out.stdout.splitlines()
            if ln and not ln.startswith("ultimate_pipeline/contracts/stage_contracts.py")
        ]
        assert others, (
            f"reserved taxonomy name '{name}' is referenced nowhere outside the "
            "registry itself; it should be removed rather than reserved"
        )


def test_the_named_near_miss_is_resolved() -> None:
    """The specific bug GAP-051 was filed for.

    The registry spelled it `geometry_continuity`; the code emits
    `geometric_continuity`. Both must now resolve to the same class, and the
    emitted spelling must be the registered one.
    """
    assert "geometric_continuity" in GATE_CLASS_REGISTRY
    assert classify_gate("geometric_continuity") is not None
    # legacy spelling still resolves rather than falling through to None
    assert classify_gate("geometry_continuity") == classify_gate("geometric_continuity")


def test_unknown_gate_still_fails_closed() -> None:
    """The fail-closed default must be preserved for genuinely unknown names."""
    assert classify_gate("definitely_not_a_real_gate_xyz") is None
    assert production_gate_waiver_allowed({"definitely_not_a_real_gate_xyz": "please"}, "definitely_not_a_real_gate_xyz") is False


def test_every_registered_class_is_a_real_gate_class() -> None:
    for name, cls in GATE_CLASS_REGISTRY.items():
        assert isinstance(cls, GateClass), f"{name} maps to non-GateClass {cls!r}"


def test_non_waivable_classes_are_really_non_waivable() -> None:
    """Identity/structural/runtime gates must never accept a waiver."""
    for name, cls in GATE_CLASS_REGISTRY.items():
        if cls in NON_WAIVABLE_CLASSES:
            assert production_gate_waiver_allowed({name: "please waive"}, name) is False, (
                f"{name} is {cls} which is non-waivable, but a waiver was honored"
            )


def test_quality_deviation_is_waivable_but_never_a_pass() -> None:
    """The one class that may be waived must still not silently PASS."""
    waivable = [n for n, c in GATE_CLASS_REGISTRY.items() if c is GateClass.QUALITY_DEVIATION]
    assert waivable, "expected at least one QUALITY_DEVIATION gate"
    for name in waivable:
        assert production_gate_waiver_allowed({name: "justified"}, name) is True