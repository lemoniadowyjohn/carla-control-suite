# GUI Authority Compatibility Matrix

Scope: the CARLA Ops Studio GUI must use the same production authority and
teardown invariants as the CLI. This matrix records the implemented surface,
the fail-closed rule, the code that enforces it, and the tests that exercise it.

Baseline worktree: `production-convergence-20261020`. Date: 2026-10-20.

## Mutation authority

`ultimate_pipeline/gui/repo_authority.py` is the only GUI adapter for writes
whose destination is inside a Git worktree.

| Property | Behaviour |
| --- | --- |
| Repository detection | `find_repository_root()` walks the target's directory ancestry for `.git`; never uses the current directory or mtime. |
| Lease | Per-worktree lease from `ultimate_pipeline.governance.single_writer.worktree_lock`. |
| Re-entrancy | One lease per process/action; nested writes share it until the outermost exits. |
| Read-only session | Refused immediately with `BLOCKED_READ_ONLY_SESSION`. |
| Lease held elsewhere | Refused with `BLOCKED_MUTATION_AUTHORITY`; never stolen. |
| Unknown/malformed lease | Refused with `BLOCKED_MUTATION_AUTHORITY`. |
| Release failure | Raised as `BLOCKED_LEASE_RELEASE`; never reported as success. |
| Outside a worktree | Ungoverned pass-through (temp files, operator-selected external exports). |

## Compatibility matrix

| GUI surface | Mutating operation | Required invariant | Implementation | Evidence | Status |
| --- | --- | --- | --- | --- | --- |
| Experiment plans | `save_plan()` | In-repo save holds the worktree lease and refuses in a read-only session. | `gui/control_center/plans.py:51` | `test_gui_repo_authority.py::test_save_plan_in_repo_is_gated_and_read_only_blocks_it` | GOVERNED |
| Settings profiles | `ProfileStore.export()` | Backup + atomic replace occur while holding one lease. | `gui/config/profiles.py:195` | `test_gui_settings_registry_profiles.py` plus repo-authority tests | GOVERNED |
| Fuzz corpus | `CorpusStore._atomic_write()` | Temp write + `os.replace` are leased. | `gui/fuzz/corpus.py:117` | Full suite `test_gui_fuzz_*` | GOVERNED |
| Audit journal | `AuditJournal.append()` / retention | Append and retention rewrite are leased. | `gui/audit.py:131,173` | `test_gui_status_freshness_audit_mock.py`; shared gate tests | GOVERNED |
| Operator drafts | `export_draft()` | Directory creation, temp file and replace are leased. | `gui/control_center/drafts.py:68` | Shared gate tests in `test_gui_repo_authority.py`; wiring reviewed | GOVERNED |
| UI preferences | `_atomic_write()` | Preference temp file and replace are leased. | `gui/shell/preferences.py:66` | `test_gui_qt_shell.py::test_T_QT_25_only_nonsecret_preferences_are_persisted`; shared gate tests | GOVERNED |
| Weather apply | `apply_weather()` | Snapshot before write; fresh readback only; rollback on any non-ok result; `state_restored` only when readback proves it. | `gui/runtime/weather.py:114-146,209-312` | `test_gui_v31_functional.py::test_weather_partial_write_is_rolled_back_and_verified`, `::test_weather_rollback_failure_is_not_reported_as_restored`, plus weather readback tests | FAIL-CLOSED |
| Map load | `MapsPanel.load_selected_map()` | Release old-world producers before `load_world()`; refuse the load if any release hook fails; no generation bump on refusal. | `gui/control_center/maps_panel.py:389-405`; `gui/session/runtime_session.py:217-271` | `test_gui_runtime_session.py::test_map_load_calls_pre_change_before_load_world`, `::test_map_load_is_refused_when_pre_change_release_fails` | FAIL-CLOSED |
| Feeds release hook | `FeedsPanel._on_runtime_before_change()` | Stop frame ingress, reset frame index, detach native sensors; raise if the bridge cannot prove release. | `gui/control_center/feeds.py:135-157`; `gui/control_center/sensor_feeds.py:132-159` | `test_gui_runtime_session.py::test_feeds_pre_change_hook_refuses_load_when_sensor_release_fails` | FAIL-CLOSED |
| Sensor lifecycle | `SensorInstance.destroy()` | `stop()` before destroy; refuse destroy if stop raises or `is_listening` remains truthy. | `ultimate_pipeline/carla_tools/sensor_registry.py:33-59` | `test_gui_security_hardening.py::test_sensor_instance_calls_stop_before_destroy`, `::test_sensor_instance_stop_failure_refuses_destroy`, `::test_sensor_instance_refuses_destroy_while_still_listening` | FAIL-CLOSED |
| Actor registry teardown | `ActorRegistry.destroy()` for sensors | Same stop-before-destroy rule; leak is surfaced with `PRODUCER_STOP_FAILED` / `PRODUCER_STILL_LIVE` and the actor stays registered. | `gui/session/actor_registry.py:104-180` | `test_gui_lifecycle.py::test_T_LIFE_04_stop_failure_refuses_destroy_and_keeps_actor`, `::test_T_LIFE_10_stop_failure_is_surfaced_and_destroy_is_refused` | FAIL-CLOSED |
| Sensor registry bulk teardown | `SensorRegistry.remove()` / `clear()` | A failed producer stops the removal; `clear()` reports every failure and keeps failed entries. | `ultimate_pipeline/carla_tools/sensor_registry.py:82-102` | `test_gui_security_hardening.py` sensor tests | FAIL-CLOSED |

## Runtime boundary

The GUI never claims a CARLA runtime success from a listening port or a local
object. Map loads still require an actual `load_world()`/readback path, and
weather application requires a fresh `get_weather()` readback after the write.
Unit tests use fakes; external runtime validation remains an explicit,
separate evidence step.

## Verification

Commands are run from the worktree root with an empty `PYTHONPATH` and
`QT_QPA_PLATFORM=offscreen`.

| Check | Command | Result |
| --- | --- | --- |
| Focused authority/lifecycle suite | `pytest tests/unit/test_gui_repo_authority.py tests/unit/test_gui_runtime_session.py tests/unit/test_gui_v31_functional.py tests/unit/test_gui_lifecycle.py tests/unit/test_gui_security_hardening.py -q` | 119 passed |
| Full unit suite | `pytest tests/unit -q` | 3939 passed, 11 skipped, 1 xfailed in 2529.05s (0:42:09) |

Full-suite log: `G:\pytest-tmp\gui_full_final2.log` ends with:

```text
=== 3939 passed, 11 skipped, 1 xfailed, 225 warnings in 2529.05s (0:42:09) ====
```

The full-suite result is authoritative only when the log ends with a passing
summary. A split run or an interrupted run is not reported as a pass.

The full suite was executed before a type-annotation-only correction in
`repo_authority.py` (`repository_write` return type). After that correction,
`tests/unit/test_gui_repo_authority.py` was rerun: 6 passed.

## Static checks

| Check | Command | Result |
| --- | --- | --- |
| Ruff (new adapter and its tests) | `ruff check ultimate_pipeline/gui/repo_authority.py tests/unit/test_gui_repo_authority.py` | All checks passed |
| Mypy (new adapter) | `mypy ultimate_pipeline\gui\repo_authority.py --ignore-missing-imports` | No error attributed to `repo_authority.py`; imported governance modules retain pre-existing type errors |

Ruff over the wider touched set reports pre-existing `F401`/`E402` findings in
legacy GUI test/source files; no new-file finding remains.
