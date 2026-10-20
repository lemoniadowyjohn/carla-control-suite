# -*- coding: utf-8 -*-
"""Canonical OpenDRIVE normalization for the frozen RQ1 determinism metric.

Version: ``rq1-xodr-normalization-v1``

Used ONLY for the RQ1 ``normalized_hash_repeatability`` metric.  It is not a
general-purpose XODR cleaner and never rewrites the artifact itself.

Semantic preservation (guarantees)
----------------------------------
* geometry (planView / elevationProfile / lanes / objects) is preserved:
  every attribute value string is copied verbatim (numeric formatting is
  NEVER rewritten);
* topology (roads, lane sections, predecessor/successor links, junction
  connections) is preserved;
* all semantically relevant numerical values are preserved exactly as
  serialized;

Non-semantic serialization differences that ARE normalized (documented,
versioned allowlist):
  N1. XML comments and processing instructions are removed.
  N2. XML declaration styling differences are removed.
  N3. Whitespace-only text between elements (pretty-print indentation /
      tail) is removed; real text nodes keep their content verbatim.
  N4. Attribute order is canonicalized to sorted-by-name.
  N5. Root-level ``road`` and ``junction`` record ordering is
      canonicalized to ascending integer ``id``.  Their relative file
      order carries no OpenDRIVE semantics (references resolve via the
      ``id`` attributes, not record sequence).
  N6. Header generation timestamp ``header@date`` is removed.  This is an
      explicit allowlist entry: no other metadata is dropped and unknown
      fields are always preserved.

Bias toward preservation: a candidate field that is not clearly
non-semantic under the frozen RQ1 semantics is preserved.
"""
from __future__ import annotations

import hashlib
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Dict, Tuple

NORMALIZATION_VERSION = "rq1-xodr-normalization/v1"

# N6: allowlist of non-semantic metadata: tag -> attribute names whose
# values are generation-controlled timestamps/metadata, not map semantics.
METADATA_ATTRIBUTE_ALLOWLIST: Dict[str, Tuple[str, ...]] = {
    "header": ("date",),
}

# N5: root-level record groups whose serialization order is normalized
# (references resolve by id; sibling order has no OpenDRIVE semantics).
ORDER_NORMALIZED_ROOT_TAGS: Tuple[str, str] = ("road", "junction")

_HEADER_TAG = "header"


def _sorted_attribs(elem: ET.Element) -> None:
    # N4 — insertion order defines the serializer output; rebuild sorted.
    elem.attrib = dict(sorted(elem.attrib.items()))


def _clean_whitespace(elem: ET.Element) -> None:
    # N3 — whitespace-only text nodes are pure serialization artifacts.
    if elem.text is not None and not elem.text.strip():
        elem.text = None
    if elem.tail is not None and not elem.tail.strip():
        elem.tail = None


def _canonicalize(root: ET.Element) -> ET.Element:
    """Apply N3-N6 and return the canonical root element.

    Parsed with ``ET.fromstring`` which (default parser) already drops
    comments and processing instructions, covering N1/N2.
    """
    for el in root.iter():
        _sorted_attribs(el)
        _clean_whitespace(el)

    header = root.find(_HEADER_TAG)
    if header is not None:
        for attr in METADATA_ATTRIBUTE_ALLOWLIST.get(_HEADER_TAG, ()):
            header.attrib.pop(attr, None)

    _canonicalize_root_order(root)
    return root


def _id_sort_key(child: ET.Element) -> Tuple[int, Any]:
    raw = child.attrib.get("id", "")
    try:
        return (0, int(raw))
    except ValueError:
        return (1, str(raw))


def _canonicalize_root_order(root: ET.Element) -> None:
    children = list(root)
    head = []
    for i, child in enumerate(children):
        if child.tag == _HEADER_TAG:
            head = children[: i + 1]
            children = children[i + 1 :]
            break
    roads = [c for c in children if c.tag == "road"]
    junctions = [c for c in children if c.tag == "junction"]
    others = [c for c in children if c.tag not in ORDER_NORMALIZED_ROOT_TAGS]
    roads.sort(key=_id_sort_key)
    junctions.sort(key=_id_sort_key)
    ordered = head + others + roads + junctions
    root[:] = ordered  # type: ignore[assignment]


def normalize_xodr(path: str | Path) -> Dict[str, Any]:
    """Compute the versioned canonical normalized identity of an XODR file.

    Never mutates the input file.  Returns::

        {
          "normalization_version": ...,
          "sha256": <canonical normalized bytes sha256>,
          "raw_sha256": <sha256 of the raw file bytes>,
        }
    """
    path = Path(path)
    raw_bytes = path.read_bytes()
    root = ET.fromstring(raw_bytes)
    _canonicalize(root)
    payload = ET.tostring(root, encoding="utf-8", xml_declaration=False)
    return {
        "normalization_version": NORMALIZATION_VERSION,
        "sha256": hashlib.sha256(payload).hexdigest(),
        "raw_sha256": hashlib.sha256(raw_bytes).hexdigest(),
    }


def normalization_rules() -> Dict[str, Any]:
    """Machine-readable rule description embedded in receipts."""
    return {
        "version": NORMALIZATION_VERSION,
        "removed": [
            "comments/processing-instructions (N1)",
            "xml declaration styling (N2)",
            "whitespace-only inter-element text (N3)",
            "whitespace-only tail text (N3)",
            "allowlisted metadata attributes (N6)",
        ],
        "canonicalized": [
            "attribute order sorted (N4)",
            "root-level road order ascending id (N5)",
            "root-level junction order ascending id (N5)",
        ],
        "metadata_attribute_allowlist": {
            tag: list(attrs) for tag, attrs in METADATA_ATTRIBUTE_ALLOWLIST.items()
        },
        "preserved_verbatim": [
            "every non-allowlisted attribute value string",
            "numeric value strings (never reformatted)",
            "unknown fields (never normalized away)",
            "real text node content",
        ],
    }
