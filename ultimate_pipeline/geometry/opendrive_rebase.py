# -*- coding: utf-8 -*-
"""Centralized XODR local-frame rebase (OC-38).

Historically there were two independent rebase implementations with divergent
coordinate coverage:

- ``scripts/regen_map_of_record._rebase_to_local`` shifted only
  ``planView/geometry`` x/y and ``object/outline/cornerGlobal`` x/y.
- ``ultimate_pipeline.tiling.runtime_tile_builder`` shifted
  ``planView/geometry`` x/y, every ``cornerGlobal`` x/y and every
  ``positionInertial`` x/y (but no other absolute-frame element).

Neither implementation shifted the absolute header-frame ``x``/``y`` on
``<object>`` or ``<signal>`` elements, so a map containing those would keep
their global tmerc values while roads were localized -- the exact class of
frame disagreement that produced the earlier verified 7,665 m building/road
centroid drift on the real pinned map.

This module is the single engine used by *both* callers. Every element type
that carries an absolute (header-frame) X/Y coordinate is translated by the
same ``(dx, dy)`` with the same finiteness validation, so canonical regen,
runtime tiles and any future consumer always agree on the covered set.

Coverage contract
-----------------
Strict (a missing or non-finite coordinate aborts the rebase):
  - ``planView/geometry``      -> x, y   (road alignment origins)
  - ``cornerGlobal``           -> x, y   (absolute outline corners)
  - ``positionInertial``       -> x, y   (absolute inertial positions)

Optional (translated only when the element carries the attribute, so that
s/t road-relative ``<object>``/``<signal>`` metadata is left untouched):
  - ``object``                 -> x, y
  - ``signal``                 -> x, y

Never translated (already relative to the element/road frame): ``cornerLocal``,
``positionRoad``, ``positionLane``, lane/planView polynomial parameters.
"""
from __future__ import annotations

import math
import xml.etree.ElementTree as ET

# (kind, selector, attributes, required)
_SELECTORS = (
    ("planview_geometry", ".//planView/geometry", ("x", "y"), True),
    ("corner_global", ".//cornerGlobal", ("x", "y"), True),
    ("position_inertial", ".//positionInertial", ("x", "y"), True),
    ("object_xy", ".//object", ("x", "y"), False),
    ("signal_xy", ".//signal", ("x", "y"), False),
)


class UnboundedCoordinateError(RuntimeError):
    """An absolute coordinate is missing/non-numeric/non-finite or a shift overflowed."""


def _coord(element: ET.Element, attribute: str, where: str) -> float:
    raw = element.get(attribute)
    if raw is None:
        raise UnboundedCoordinateError(
            f"rebase: {where}@{attribute} is missing; an absolute header-frame "
            f"coordinate is required to localize the map"
        )
    try:
        value = float(raw)
    except (TypeError, ValueError):
        raise UnboundedCoordinateError(
            f"rebase: {where}@{attribute}={raw!r} is non-numeric"
        ) from None
    if not math.isfinite(value):
        raise UnboundedCoordinateError(
            f"rebase: {where}@{attribute}={raw!r} is non-finite"
        )
    return value


def planview_min_xy(root: ET.Element) -> tuple[float, float]:
    """Return ``(min_x, min_y)`` over planView geometry in the header frame.

    Raises :class:`UnboundedCoordinateError` when there is no planView geometry
    or any geometry coordinate is non-numeric/non-finite -- a rebase from an
    unknown frame would silently destroy the map.
    """
    xs: list[float] = []
    ys: list[float] = []
    for geometry in root.findall(".//planView/geometry"):
        xs.append(_coord(geometry, "x", "planView/geometry"))
        ys.append(_coord(geometry, "y", "planView/geometry"))
    if not xs:
        raise UnboundedCoordinateError(
            "rebase: no planView geometry to derive a local frame from"
        )
    return min(xs), min(ys)


def rebase_xodr_coordinates(
    root: ET.Element,
    *,
    dx: float,
    dy: float,
    precision: int = 6,
) -> dict:
    """Translate every absolute header-frame X/Y coordinate by ``(dx, dy)``.

    Args:
        root: mutated OpenDRIVE root.
        dx, dy: translation applied identically to every covered element.
        precision: decimal places used to serialize the translated values
            (default 6 = the XODR 1e-6 m fixed-point convention used by the
            canonical map-of-record rebase).

    Returns:
        A per-kind translation report with fully-finite results guaranteed.

    Raises:
        UnboundedCoordinateError: strict elements missing coordinates or any
            translated value going non-finite.
    """
    per_kind: dict[str, int] = {}
    for kind, selector, attributes, required in _SELECTORS:
        translated = 0
        for element in root.findall(selector):
            translated_here = 0
            for attribute in attributes:
                raw = element.get(attribute)
                if raw is None:
                    if required:
                        raise UnboundedCoordinateError(
                            f"rebase: {selector}@{attribute} is missing; an "
                            f"absolute header-frame coordinate is required"
                        )
                    continue
                try:
                    current = float(raw)
                except (TypeError, ValueError):
                    raise UnboundedCoordinateError(
                        f"rebase: {selector}@{attribute}={raw!r} is non-numeric"
                    ) from None
                if not math.isfinite(current):
                    raise UnboundedCoordinateError(
                        f"rebase: {selector}@{attribute}={raw!r} is non-finite"
                    )
                value = current - (dx if attribute == "x" else dy)
                try:
                    if not math.isfinite(value):
                        raise UnboundedCoordinateError(
                            f"rebase: {selector}@{attribute} overflowed after "
                            f"translating {current!r} by "
                            f"{(dx if attribute == 'x' else dy)!r}"
                        )
                except OverflowError:
                    raise UnboundedCoordinateError(
                        f"rebase: {selector}@{attribute} overflowed after "
                        f"translating {current!r} by "
                        f"{(dx if attribute == 'x' else dy)!r}"
                    ) from None
                element.set(attribute, f"{value:.{precision}f}")
                translated_here += 1
            if translated_here:
                translated += 1
        if translated:
            per_kind[kind] = translated
    return {"dx": dx, "dy": dy, "translated_elements": per_kind}