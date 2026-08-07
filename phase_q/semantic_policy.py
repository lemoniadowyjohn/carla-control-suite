"""Q2 - Perception-strict semantic emptiness policy.

The old policy mapped "0 landmarks -> N/A_NO_LANDMARKS -> PASS", which is only
acceptable for a STRUCTURAL_XODR smoke profile.  For perception readiness the
empty-category policy is strict and profile-scoped.

Profiles:

* STRUCTURAL_XODR  - empty categories may be NOT_APPLICABLE_SOURCE_CONFIRMED or
                     PACKAGE_DEPENDENT, but only with authoritative source evidence.
* PACKAGED_MAP     - expected packaged actors and semantic content must be present.
* PERCEPTION_RELEASE - mandatory categories may not pass through generic N/A.

For every empty category the validator must emit exactly one of:

  EXPECTED_ZERO_PROVEN_FROM_AUTHORITY
  PACKAGE_DEPENDENT_AND_VALIDATED_LATER
  SEMANTIC_CONTENT_MISSING
  ACTOR_BINDING_MISSING
  VALIDATOR_UNABLE_TO_QUERY

Dispositions SEMANTIC_CONTENT_MISSING, ACTOR_BINDING_MISSING and
VALIDATOR_UNABLE_TO_QUERY always fail the gate: they never contribute a PASS.

Phase L verdicts are scope-specific: L_ALL_PASS_STRUCTURAL_XODR,
L_ALL_PASS_PACKAGED_MAP, L_ALL_PASS_PERCEPTION_RELEASE.  Ambiguous L_ALL_PASS is
never emitted.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

PROFILE_STRUCTURAL_XODR = "STRUCTURAL_XODR"
PROFILE_PACKAGED_MAP = "PACKAGED_MAP"
PROFILE_PERCEPTION_RELEASE = "PERCEPTION_RELEASE"
ALL_PROFILES = (PROFILE_STRUCTURAL_XODR, PROFILE_PACKAGED_MAP, PROFILE_PERCEPTION_RELEASE)

# Disposition codes
EXPECTED_ZERO_PROVEN_FROM_AUTHORITY = "EXPECTED_ZERO_PROVEN_FROM_AUTHORITY"
PACKAGE_DEPENDENT_AND_VALIDATED_LATER = "PACKAGE_DEPENDENT_AND_VALIDATED_LATER"
SEMANTIC_CONTENT_MISSING = "SEMANTIC_CONTENT_MISSING"
ACTOR_BINDING_MISSING = "ACTOR_BINDING_MISSING"
VALIDATOR_UNABLE_TO_QUERY = "VALIDATOR_UNABLE_TO_QUERY"
NOT_APPLICABLE_SOURCE_CONFIRMED = "NOT_APPLICABLE_SOURCE_CONFIRMED"
PACKAGE_DEPENDENT = "PACKAGE_DEPENDENT"

EXPLICIT_DISPOSITIONS = (
    EXPECTED_ZERO_PROVEN_FROM_AUTHORITY,
    PACKAGE_DEPENDENT_AND_VALIDATED_LATER,
    SEMANTIC_CONTENT_MISSING,
    ACTOR_BINDING_MISSING,
    VALIDATOR_UNABLE_TO_QUERY,
)

# Structural-profile dispositions (Q2), only valid with authoritative source evidence:
STRUCTURAL_EMPTY_CODES = (NOT_APPLICABLE_SOURCE_CONFIRMED, PACKAGE_DEPENDENT)

# Dispositions that fail closed - they never add up to a PASS.
HARD_FAIL_CODES = (SEMANTIC_CONTENT_MISSING, ACTOR_BINDING_MISSING, VALIDATOR_UNABLE_TO_QUERY)

# Semantic categories tracked by Phase Q (Q2/Q3/Q6/Q8).
SEMANTIC_CATEGORIES: List[str] = [
    "signals",
    "signal_references",
    "controllers",
    "objects",
    "crosswalk_objects",
    "traffic_lights",
    "landmarks",
    "speed_limits",
    "road_types",
    "road_markings",
    "lane_change_permissions",
    "turn_lane_semantics",
    "stop_yield_controls",
    "sidewalks",
    "pedestrian_lanes",
    "traffic_light_actor_bindings",
    "semantic_material_classes",
]

# Categories that are mandatory for PERCEPTION_RELEASE.
PERCEPTION_MANDATORY = (
    "signals",
    "crosswalk_objects",
    "speed_limits",
    "road_markings",
    "lane_change_permissions",
    "turn_lane_semantics",
    "stop_yield_controls",
    "sidewalks",
    "pedestrian_lanes",
    "semantic_material_classes",
)

# Categories that are mandatory for PACKAGED_MAP.
PACKAGED_MAP_MANDATORY = (
    "signals",
    "signal_references",
    "controllers",
    "objects",
    "crosswalk_objects",
    "traffic_light_actor_bindings",
)


def profile_mandatory(profile: str) -> frozenset[str]:
    if profile == PROFILE_PERCEPTION_RELEASE:
        return frozenset(PERCEPTION_MANDATORY)
    if profile == PROFILE_PACKAGED_MAP:
        return frozenset(PACKAGED_MAP_MANDATORY)
    return frozenset()


def empty_allowed_for_profile(profile: str) -> tuple[str, ...]:
    if profile == PROFILE_STRUCTURAL_XODR:
        return STRUCTURAL_EMPTY_CODES + EXPLICIT_DISPOSITIONS
    if profile == PROFILE_PACKAGED_MAP:
        return (EXPECTED_ZERO_PROVEN_FROM_AUTHORITY,
                PACKAGE_DEPENDENT_AND_VALIDATED_LATER)
    # PERCEPTION_RELEASE: only proven-zero or validated-later dispositions pass.
    return (EXPECTED_ZERO_PROVEN_FROM_AUTHORITY,
            PACKAGE_DEPENDENT_AND_VALIDATED_LATER)


def evaluate_category(
    category: str,
    count: Optional[int],
    profile: str,
    disposition: str,
    *,
    source_authority: bool = False,
) -> Dict[str, Any]:
    """Evaluate one semantic category under the given profile.

    count is None when the validator could not query the category at all.
    """
    result: Dict[str, Any] = {
        "category": category,
        "count": count,
        "profile": profile,
        "disposition": disposition,
        "status": "FAIL",
        "reason": "",
    }

    mandatory = category in profile_mandatory(profile)

    if count and count > 0:
        # Content present -> disposition not required; PASS if validator can see it.
        result["status"] = "PASS"
        result["reason"] = "non-empty category; count={}".format(count)
        return result

    if disposition == EXPECTED_ZERO_PROVEN_FROM_AUTHORITY:
        if source_authority:
            result["status"] = "PASS"
            result["reason"] = "authority-proven expected zero"
        else:
            result["status"] = "FAIL"
            result["reason"] = "EXPECTED_ZERO requires authoritative source proof"
        return result

    if disposition == PACKAGE_DEPENDENT_AND_VALIDATED_LATER:
        # Permitted only for profiles that defer packaging validation.
        if profile in (PROFILE_PACKAGED_MAP, PROFILE_PERCEPTION_RELEASE):
            result["status"] = "PASS"
            result["reason"] = "deferred to package validation gate; must be re-verified"
        else:
            result["status"] = "FAIL"
            result["reason"] = "PACKAGE_DEPENDENT_AND_VALIDATED_LATER invalid for structural profile"
        return result

    if disposition in HARD_FAIL_CODES:
        result["status"] = "FAIL"
        result["reason"] = "hard-fail disposition {}".format(disposition)
        return result

    # Structural-only dispositions:
    if profile == PROFILE_STRUCTURAL_XODR and disposition in STRUCTURAL_EMPTY_CODES:
        if source_authority:
            result["status"] = "PASS"
            result["reason"] = "structural profile empty category accepted with source authority"
        else:
            result["status"] = "FAIL"
            result["reason"] = "empty category claimed N/A without authoritative source evidence"
        return result

    # Default: unknown / generic N/A in a strict profile is always a failure.
    result["status"] = "FAIL"
    result["reason"] = "generic N/A not allowed (profile {}, mandatory={})".format(
        profile, mandatory)
    return result


def validate_profile(
    categories: Dict[str, Dict[str, Optional[str]]],
    profile: str,
    *,
    authority_ok: Optional[Dict[str, bool]] = None,
) -> Dict[str, Any]:
    """Validate a full category map.

    ``categories`` maps category name -> {"count": <int|None>, "disposition": str}
    ``authority_ok`` maps category name -> whether source authority was present.
    """
    authority_ok = authority_ok or {}
    per_category = []
    failed = []
    for cat in SEMANTIC_CATEGORIES:
        spec = categories.get(cat)
        if spec is None:
            # Validator never queried this category.
            res = evaluate_category(cat, None, profile, VALIDATOR_UNABLE_TO_QUERY,
                                    source_authority=False)
        else:
            res = evaluate_category(
                cat,
                spec.get("count"),
                profile,
                spec.get("disposition") or VALIDATOR_UNABLE_TO_QUERY,
                source_authority=bool(authority_ok.get(cat, False)),
            )
        per_category.append(res)
        if res["status"] != "PASS":
            failed.append(res)

    verdict = "PASS" if not failed else "FAIL"
    return {
        "profile": profile,
        "verdict": verdict,
        "categories": per_category,
        "failed": failed,
    }


def scope_specific_verdict(
    all_pass: bool,
    profile: str,
) -> str:
    """Return an unambiguous scope-specific Phase L verdict."""
    if all_pass:
        return "L_ALL_PASS_{}".format(profile)
    return "L_SOME_FAIL_{}".format(profile)