# -*- coding: utf-8 -*-
"""Unit tests for FIX-B' import-namespace patch builder (Lane B)."""
import pytest

from patches.fix_b_import_namespace import (
    NEW_LINE,
    OLD_LINE,
    build_patch,
)

CONTEXT_BEFORE = "        for umap in maps:\n"
TAIL_AFTER = (
    "\n",
    "\n",
    '            if "source" in umap:\n',
    '                tiles = [os.path.join(json_dirname, umap["source"])]\n',
)


def _prestate():
    return [CONTEXT_BEFORE, OLD_LINE, *TAIL_AFTER]


def test_build_patch_replaces_destination_subpath():
    patched = build_patch(_prestate())
    assert patched[1] == NEW_LINE
    assert "Static" in patched[1] and '"Terrain"' in patched[1]
    assert "Maps" not in patched[1]


def test_build_patch_keeps_surrounding_bodies():
    patched = build_patch(_prestate())
    assert patched[0] == CONTEXT_BEFORE
    assert patched[4] == '            if "source" in umap:\n'


def test_build_patch_refuses_reapplication():
    with pytest.raises(RuntimeError, match="already applied"):
        build_patch([CONTEXT_BEFORE, NEW_LINE, *TAIL_AFTER])


def test_build_patch_refuses_unknown_identity():
    with pytest.raises(RuntimeError, match="identity differs"):
        build_patch([CONTEXT_BEFORE, "  maps_dest = 'other'\n", *TAIL_AFTER])


def test_build_patch_refuses_broken_context():
    with pytest.raises(RuntimeError, match="context-before"):
        build_patch(["for umap in maps:\n", OLD_LINE, *TAIL_AFTER])
