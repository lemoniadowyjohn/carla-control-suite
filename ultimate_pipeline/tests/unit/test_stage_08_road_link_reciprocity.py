# -*- coding: utf-8 -*-
"""L2 review follow-up (2026-11-02): ultimate_pipeline/pipeline_stages/
stage_08_integrity.py's _step8_markings_and_integrity() must wire
check_road_link_reciprocity() in as a report entry (vreport.add_dict) and
fail the stage when THESIS_STRICT is True AND violations > 0.

The real-map baseline (reports/rq1_trial_runs/run_01/
20261007_214826_524342/07_lanes_...xodr) measured ZERO violations, so
THESIS_STRICT enforcement here does not block any existing run on a
pre-existing condition (see the commit message for the measured counts).
"""
from __future__ import annotations

from pathlib import Path
from unittest import mock

import pytest

import ultimate_pipeline.pipeline_stages.stage_08_integrity as stage_mod


_MISSING_CONTACTPOINT_XODR = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    "<OpenDRIVE>"
    '<road id="A" length="10.0" junction="-1">'
    '<link><successor elementType="road" elementId="B"/></link>'
    '<planView><geometry s="0" x="0" y="0" hdg="0" length="10"><line/></geometry></planView>'
    "<lanes><laneSection s=\"0\"><right>"
    '<lane id="-1" type="driving" level="false">'
    '<width sOffset="0" a="3.5" b="0" c="0" d="0"/>'
    "</lane></right></laneSection></lanes>"
    "</road>"
    '<road id="B" length="10.0" junction="-1">'
    '<planView><geometry s="0" x="10" y="0" hdg="0" length="10"><line/></geometry></planView>'
    "<lanes><laneSection s=\"0\"><right>"
    '<lane id="-1" type="driving" level="false">'
    '<width sOffset="0" a="3.5" b="0" c="0" d="0"/>'
    "</lane></right></laneSection></lanes>"
    "</road>"
    "</OpenDRIVE>\n"
)


def _common_patches():
    return {
        "load_xodr": lambda p: ("fake_tree", "fake_root"),
        "LaneLinkBuilder": mock.Mock(
            sanitize_junction_lane_links=mock.Mock(return_value={"ok": True})
        ),
        "MarkingBuilder": mock.Mock(add_basic_markings=mock.Mock()),
        "save_xodr": lambda tree, path: None,
    }


def test_thesis_strict_fails_stage_on_reciprocity_violation(tmp_path: Path):
    final_out = tmp_path / "final.xodr"
    final_out.write_text(_MISSING_CONTACTPOINT_XODR, encoding="utf-8")

    fake_settings = mock.Mock()
    fake_settings.THESIS_STRICT = True

    fake_self = mock.Mock()
    fake_self.settings = fake_settings
    fake_self.out_dir = str(tmp_path)
    fake_self.vreport = mock.Mock()

    with mock.patch.multiple(stage_mod, create=True, **_common_patches()):
        with pytest.raises(RuntimeError, match="road_link_reciprocity"):
            stage_mod._step8_markings_and_integrity(
                fake_self, "lanes_out.xodr", str(final_out)
            )

    # The violation report must still have been written + recorded before
    # the strict-mode raise, not silently dropped.
    report_path = tmp_path / "road_link_reciprocity_report.json"
    assert report_path.exists(), "reciprocity report must be written before raising"
    add_dict_calls = [c for c in fake_self.vreport.add_dict.call_args_list]
    assert any(c.args[0] == "road_link_reciprocity" for c in add_dict_calls), (
        "road_link_reciprocity must be recorded via vreport.add_dict"
    )


_UNBACKED_JUNCTION_XODR = _MISSING_CONTACTPOINT_XODR.replace(
    '<link><successor elementType="road" elementId="B"/></link>',
    '<link><successor elementType="road" elementId="B" contactPoint="start"/></link>',
).replace(
    '<road id="B" length="10.0" junction="-1">',
    '<road id="B" length="10.0" junction="-1">'
    '<link><predecessor elementType="junction" elementId="GHOST_J"/></link>',
)


def test_thesis_strict_fails_stage_on_unbacked_junction_reference(tmp_path: Path):
    # B claims to be reached through junction GHOST_J, which does not exist.
    # Once the exit-side false positives were removed the real map measures
    # zero such references, so this category is gated like the others.
    final_out = tmp_path / "final.xodr"
    final_out.write_text(_UNBACKED_JUNCTION_XODR, encoding="utf-8")

    fake_settings = mock.Mock()
    fake_settings.THESIS_STRICT = True

    fake_self = mock.Mock()
    fake_self.settings = fake_settings
    fake_self.out_dir = str(tmp_path)
    fake_self.vreport = mock.Mock()

    with mock.patch.multiple(stage_mod, create=True, **_common_patches()):
        with pytest.raises(RuntimeError, match="road_link_reciprocity"):
            stage_mod._step8_markings_and_integrity(
                fake_self, "lanes_out.xodr", str(final_out)
            )


def test_non_strict_reports_violation_without_raising(tmp_path: Path):
    final_out = tmp_path / "final.xodr"
    final_out.write_text(_MISSING_CONTACTPOINT_XODR, encoding="utf-8")

    fake_settings = mock.Mock()
    fake_settings.THESIS_STRICT = False

    fake_self = mock.Mock()
    fake_self.settings = fake_settings
    fake_self.out_dir = str(tmp_path)
    fake_self.vreport = mock.Mock()

    class _StopAfterReciprocity(Exception):
        pass

    patches = _common_patches()
    with mock.patch.multiple(stage_mod, create=True, **patches):
        # Let the real check run (THESIS_STRICT=False means no raise from
        # it); stop the test right after by making the next statement
        # (shutil.copyfile's caller already ran -- we just assert no
        # RuntimeError from OUR block was raised at all).
        try:
            stage_mod._step8_markings_and_integrity(
                fake_self, "lanes_out.xodr", str(final_out)
            )
        except RuntimeError as e:
            assert "road_link_reciprocity" not in str(e), (
                f"must not raise on a measured violation when THESIS_STRICT=False: {e}"
            )
        except Exception:
            # Downstream code (CARLA invariant enforcement, schema checks,
            # etc.) is unmocked past this point and may legitimately fail
            # for unrelated reasons in this minimal fixture -- only the
            # road_link_reciprocity RuntimeError is this test's concern.
            pass

    report_path = tmp_path / "road_link_reciprocity_report.json"
    assert report_path.exists()
    import json

    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["totals"]["violations"] >= 1, report
