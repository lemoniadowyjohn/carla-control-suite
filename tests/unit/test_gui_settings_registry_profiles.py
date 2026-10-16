"""Task 03 acceptance tests: the 318-setting registry, validation and profiles.

Covers T-CFG-01..04, T-CFG-RANGE-01..06 and T-CFG-PROFILE-01..08.

Offline: no CARLA server, no network, no display, no live simulator.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from ultimate_pipeline.gui.config.controls import ConfiguratorModel
from ultimate_pipeline.gui.config.metadata import (
    ENV_PREFIX,
    SCHEMA,
    UNSET,
    env_name_for,
    load_registry,
)
from ultimate_pipeline.gui.config.profiles import (
    PROFILE_SCHEMA,
    SECRET_MARKER,
    FieldLossError,
    Precedence,
    Profile,
    ProfileError,
    ProfileStore,
    UnknownSchemaVersion,
)
from ultimate_pipeline.gui.config.validation import (
    Severity,
    coerce_for_declared_type,
    validate_profile,
    validate_setting,
)

REGISTRY = load_registry()


# ======================================================================
# T-CFG -- registry completeness
# ======================================================================
def test_T_CFG_01_all_318_catalog_entries_are_mapped():
    assert REGISTRY.schema == SCHEMA
    assert REGISTRY.counts["total"] == 318
    assert len(REGISTRY) == 318
    # every entry carries a citation or an explicit absence
    for entry in REGISTRY:
        assert entry.citation or entry.presence == "ABSENT_AT_HEAD"


def test_T_CFG_02_every_entry_is_verified_against_the_current_source_tree():
    assert REGISTRY.counts["present_at_head"] == 318
    assert REGISTRY.counts["absent_at_head"] == 0
    for entry in REGISTRY:
        assert entry.declaration and entry.declaration.startswith("ultimate_pipeline/")


def test_T_CFG_03_no_default_is_invented_and_ranges_are_unknown():
    # The repository has no validation layer, so NO range may be claimed known.
    assert all(entry.range_is_known is False for entry in REGISTRY)
    assert REGISTRY.counts["range_known"] == 0
    unknown = [e for e in REGISTRY if e.range_or_enum and "UNKNOWN" not in e.range_or_enum]
    for entry in unknown:
        assert entry.range_is_known is False, "a non-UNKNOWN textual range is still not enforced"


def test_T_CFG_04_duplicate_declarations_and_env_coverage_are_declared_not_hidden():
    assert REGISTRY.counts["duplicated_declaration"] == 4
    # 318 catalog ROWS are not 318 distinct settings
    assert REGISTRY.counts["distinct_setting_ids"] == 314
    assert len(REGISTRY.distinct_ids) == 314
    for setting_id in REGISTRY.counts["duplicate_setting_ids"]:
        assert len(REGISTRY.by_id(setting_id)) >= 2
    # env coverage was sampled, not exhaustive
    assert REGISTRY.env_coverage["sampled_not_exhaustive"] is True
    assert REGISTRY.env_coverage["env_reads_discovered"] == 589
    assert REGISTRY.env_coverage["env_reads_outside_settings_sampled"] == 479


# ======================================================================
# T-CFG-RANGE
# ======================================================================
def test_T_CFG_RANGE_01_unknown_setting_id_is_a_hard_error():
    report = validate_profile({"NOT_A_REAL_SETTING": 1}, REGISTRY)
    assert report.ok is False
    assert any(i.severity == Severity.ERROR for i in report.issues)


def test_T_CFG_RANGE_02_missing_range_reports_unverified_not_pass():
    entry = next(e for e in REGISTRY if e.is_editable)
    issue = validate_setting(entry, 1)
    assert issue is not None
    assert issue.severity == Severity.UNVERIFIED
    assert "range/enum is UNKNOWN" in issue.message


def test_T_CFG_RANGE_03_type_coercion_is_reported_honestly():
    assert coerce_for_declared_type("5", "int") == (5, True)
    assert coerce_for_declared_type("true", "bool") == (True, True)
    assert coerce_for_declared_type("2.5", "float") == (2.5, True)
    # not coercible -> value returned unchanged and flagged
    value, ok = coerce_for_declared_type("abc", "int")
    assert ok is False and value == "abc"


def test_T_CFG_RANGE_04_unset_is_reported_unverified_never_defaulted():
    entry = next(e for e in REGISTRY if e.is_editable)
    issue = validate_setting(entry, UNSET)
    assert issue is not None and issue.severity == Severity.UNVERIFIED
    assert "no value staged" in issue.message


def test_T_CFG_RANGE_05_irreversible_and_secret_settings_are_flagged():
    irreversible = [e for e in REGISTRY if e.safety_class == "IRREVERSIBLE"]
    secrets = [e for e in REGISTRY if e.safety_class == "SECRET"]
    assert irreversible and secrets
    issue = validate_setting(irreversible[0], 1)
    assert issue is not None and "irreversible" in issue.message
    issue = validate_setting(secrets[0], "literal-value")
    assert issue is not None and "never be exported" in issue.message


def test_T_CFG_RANGE_06_unbound_entries_cannot_be_written():
    unbound = [e for e in REGISTRY if not e.is_editable]
    assert unbound, "expected some non-writable declaration sites"
    assert all(e.disabled_reason for e in unbound)
    issue = validate_setting(unbound[0], 1)
    assert issue is not None and issue.severity == Severity.ERROR


# ======================================================================
# T-CFG-PROFILE
# ======================================================================
def _editable_ids(count: int = 6) -> list[str]:
    return [m.setting_id for m in REGISTRY.editable()[:count]]


def test_T_CFG_PROFILE_01_export_import_round_trip_is_lossless(tmp_path):
    store = ProfileStore(tmp_path, REGISTRY)
    ids = _editable_ids()
    profile = Profile("p1", {ids[0]: 12345, ids[1]: "abc"})
    store.export(profile)
    loaded = store.load("p1")
    assert loaded.values == profile.values
    # export -> import -> export is byte-identical
    first = store.path_for("p1").read_text(encoding="utf-8")
    store.export(loaded)
    assert store.path_for("p1").read_text(encoding="utf-8") == first


def test_T_CFG_PROFILE_02_writes_are_atomic_and_previous_file_is_backed_up(tmp_path):
    store = ProfileStore(tmp_path, REGISTRY)
    ids = _editable_ids()
    store.export(Profile("p", {ids[0]: 1}))
    result = store.export(Profile("p", {ids[0]: 2}))
    assert result["backup"] and Path(result["backup"]).exists()
    assert not list(tmp_path.glob("*.tmp")), "temp file must not survive"
    assert store.load("p").values[ids[0]] == 2


def test_T_CFG_PROFILE_03_unknown_schema_and_version_are_rejected(tmp_path):
    store = ProfileStore(tmp_path, REGISTRY)
    ids = _editable_ids()
    with pytest.raises(UnknownSchemaVersion):
        store.from_payload({"schema": "something-else/v9", "values": {}})
    with pytest.raises(UnknownSchemaVersion):
        store.from_payload({"schema": PROFILE_SCHEMA, "schema_version": 99,
                            "name": "p", "values": {}})


def test_T_CFG_PROFILE_04_field_loss_is_an_error_not_a_silent_merge(tmp_path):
    store = ProfileStore(tmp_path, REGISTRY)
    with pytest.raises(FieldLossError):
        store.from_payload({"schema": PROFILE_SCHEMA, "schema_version": 1, "values": {}})
    with pytest.raises(ProfileError):
        store.from_payload({"schema": PROFILE_SCHEMA, "schema_version": 1,
                            "name": "p", "values": {}, "extra": 1})


def test_T_CFG_PROFILE_05_secrets_are_never_exported(tmp_path):
    store = ProfileStore(tmp_path, REGISTRY)
    secret_id = next(e.setting_id for e in REGISTRY if e.safety_class == "SECRET")
    result = store.export(Profile("s", {secret_id: "super-secret-literal"}))
    assert result["secret_values_withheld"] >= 1
    on_disk = store.path_for("s").read_text(encoding="utf-8")
    assert "super-secret-literal" not in on_disk
    assert SECRET_MARKER in on_disk


def test_T_CFG_PROFILE_06_env_overrides_are_surfaced_never_silently_applied(tmp_path):
    store = ProfileStore(tmp_path, REGISTRY)
    ids = _editable_ids()
    target = ids[0]
    staged = store.stage({target: 999}, env={env_name_for(target): "from-env"})
    assert staged[0].precedence == Precedence.ENV
    assert staged[0].shadowed_by_env is True
    assert staged[0].effective == "from-env"
    assert env_name_for(target).startswith(ENV_PREFIX)


def test_T_CFG_PROFILE_07_diff_reports_add_change_remove_and_shadowing(tmp_path):
    store = ProfileStore(tmp_path, REGISTRY)
    ids = _editable_ids(4)
    current = Profile("c", {ids[0]: 1, ids[1]: 2})
    incoming = Profile("i", {ids[0]: 9, ids[2]: 3})
    diff = store.diff(current, incoming)
    assert diff.added == {ids[2]: 3}
    assert diff.changed == {ids[0]: (1, 9)}
    assert diff.removed == (ids[1],)
    assert bool(diff) is True


def test_T_CFG_PROFILE_08_irreversible_settings_require_confirmation(tmp_path):
    store = ProfileStore(tmp_path, REGISTRY)
    ids = [e.setting_id for e in REGISTRY.editable()
           if e.safety_class == "IRREVERSIBLE"][:2]
    assert store.requires_confirmation({ids[0]: 1}) == (ids[0],)
    ordinary = [e.setting_id for e in REGISTRY.editable()
                if e.safety_class == "ORDINARY"][:1]
    assert store.requires_confirmation({ordinary[0]: 1}) == ()


# ======================================================================
# GUI contract: searchable, categorised, provenance, disabled reason, undo
# ======================================================================
def test_configurator_is_searchable_categorised_and_does_not_auto_apply():
    model = ConfiguratorModel(REGISTRY)
    controls = model.controls()
    # disabled controls are present too, each with a stated reason
    assert len(controls) == len(REGISTRY)
    # disabled_controls() is row-based (as controls() is); editable() de-dupes
    # the 4 dual-declared ids, so the two must be compared on the same basis.
    non_editable_rows = sum(1 for e in REGISTRY if not e.is_editable)
    assert len(model.disabled_controls()) == non_editable_rows
    assert model.categories(), "controls must be categorised"
    assert model.search("CARLA_HOST"), "search must find a known setting"
    assert all(c.provenance for c in controls), "every control needs provenance help"
    assert all(c.enabled or c.disabled_reason for c in controls)

    target = controls[0].setting_id
    before = None
    import ultimate_pipeline.config.settings as live_settings
    before = getattr(live_settings.Settings(), target, UNSET) if hasattr(
        live_settings.Settings(), "__dataclass_fields__") else UNSET

    model.stage(target, "staged-not-applied")
    assert model.staged_values()[target] == "staged-not-applied"
    after = getattr(live_settings.Settings(), target, UNSET) if hasattr(
        live_settings.Settings(), "__dataclass_fields__") else UNSET
    assert after == before, "staging must NOT auto-apply"

    assert model.undo() == (target,)
    assert target not in model.staged_values()


def test_configurator_refuses_to_stage_a_disabled_setting():
    model = ConfiguratorModel(REGISTRY)
    disabled = REGISTRY.one(next(e.setting_id for e in REGISTRY if not e.is_editable))
    with pytest.raises(PermissionError):
        model.stage(disabled.setting_id, 1)
    with pytest.raises(KeyError):
        model.stage("NOT_A_SETTING", 1)


def test_unassignable_widgets_are_reported_rather_than_invented():
    model = ConfiguratorModel(REGISTRY)
    unassigned = model.unassignable_widgets()
    assert unassigned, "widgets are genuinely still TBD for most settings"
    for control in model.controls():
        if control.setting_id in unassigned:
            assert control.widget == "UNASSIGNED"  # not invented