#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""NEW-327 -- randomness ownership and the governed seed tree.

The pre-existing governed paths had four distinct defects:

1. ``record_route_fixed.py`` executed ``_random.seed(42)`` -- a hardcoded
   literal, on the **process-global** ``random`` module, right before choosing
   NPC blueprints.  It was bound to neither the CLI seed nor ``UP_TM_SEED``.
2. ``vehicle_manager/spawner.py`` called ``random.seed(SPAWNER_SEED)`` at
   **import time**, mutating randomness for every unrelated module in the
   process.
3. ``fixed_traffic_manager.py``, ``actor_stream_manager.py`` and
   ``carla_sim_consolidated.py`` used bare ``random.choice`` /
   ``random.shuffle`` with no seed at all.
4. ``UP_TM_SEED`` defaulted to the literal ``"42"`` and silently fell back to
   ``42`` on a malformed value, so a typo was indistinguishable from a real
   seed.

This module makes every governed path use an **owned** ``random.Random``
instance derived from one experiment seed through an explicit, recorded tree:

    experiment_seed
      -> tm_seed
      -> npc_blueprint_seed
      -> npc_spawn_seed
      -> pedestrian_seed
      -> weather_seed
      -> scenario_seed

Derivation is a stable SHA-256 of ``"<domain>:<experiment_seed>"`` so seeds
are reproducible across processes, platforms and Python versions (unlike
``hash()``, which is salted per process).

This module never calls ``random.seed()`` and never mutates the process-global
RNG.
"""

from __future__ import annotations

import hashlib
import json
import os
import random
from typing import Any, Dict, List, Mapping, Optional

SEED_TREE_SCHEMA = "SEED_TREE/v1"

DOMAIN_TM = "tm"
DOMAIN_NPC_BLUEPRINT = "npc_blueprint"
DOMAIN_NPC_SPAWN = "npc_spawn"
DOMAIN_PEDESTRIAN = "pedestrian"
DOMAIN_WEATHER = "weather"
DOMAIN_SCENARIO = "scenario"

#: The governed domains, in the canonical order used for reporting.
SEED_DOMAINS: tuple = (
    DOMAIN_TM,
    DOMAIN_NPC_BLUEPRINT,
    DOMAIN_NPC_SPAWN,
    DOMAIN_PEDESTRIAN,
    DOMAIN_WEATHER,
    DOMAIN_SCENARIO,
)

SEED_MISSING = "SEED_MISSING"
SEED_INVALID = "SEED_INVALID"
SEED_TREE_MISMATCH = "SEED_TREE_MISMATCH"


def derive_seed(experiment_seed: int, domain: str) -> int:
    """Deterministically derive a domain seed from the experiment seed.

    SHA-256 based (not ``hash()``) so the value is stable across processes.
    """
    material = f"{str(domain)}:{int(experiment_seed)}".encode("utf-8")
    return int(hashlib.sha256(material).hexdigest()[:8], 16)


def build_seed_tree(experiment_seed: int, overrides: Optional[Mapping[str, int]] = None) -> Dict[str, Any]:
    """Resolve the full seed tree for one experiment.

    ``overrides`` may pin individual domains (e.g. a deliberately fixed TM
    seed); each override is recorded as such so a pinned seed is never
    mistaken for a derived one.
    """
    try:
        root = int(experiment_seed)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{SEED_INVALID}:experiment_seed:{experiment_seed!r}") from exc

    overrides = {str(k): int(v) for k, v in dict(overrides or {}).items()}
    unknown = [d for d in overrides if d not in SEED_DOMAINS]
    if unknown:
        raise ValueError(f"{SEED_INVALID}:unknown_seed_domain:{','.join(sorted(unknown))}")

    domains: Dict[str, Any] = {}
    for domain in SEED_DOMAINS:
        derived = derive_seed(root, domain)
        if domain in overrides:
            domains[domain] = {
                "seed": overrides[domain],
                "source": "explicit_override",
                "derived_seed": derived,
            }
        else:
            domains[domain] = {"seed": derived, "source": "derived", "derived_seed": derived}

    return {
        "schema": SEED_TREE_SCHEMA,
        "experiment_seed": root,
        "seeds": {d: domains[d]["seed"] for d in SEED_DOMAINS},
        "domains": domains,
        "all_domains_resolved": True,
        "process_global_rng_mutated": False,
        "derivation": "sha256('<domain>:<experiment_seed>')[:8] hex -> int",
    }


def owned_rng(experiment_seed: int, domain: str, *,
              overrides: Optional[Mapping[str, int]] = None) -> random.Random:
    """Return an **owned** ``random.Random`` for one domain.

    A local instance: using it cannot change the behaviour of any other module
    in the process.
    """
    tree = build_seed_tree(experiment_seed, overrides)
    if domain not in tree["seeds"]:
        raise ValueError(f"{SEED_INVALID}:unknown_seed_domain:{domain}")
    return random.Random(tree["seeds"][domain])


def seed_tree_sha256(tree: Mapping[str, Any]) -> str:
    payload = {
        "schema": SEED_TREE_SCHEMA,
        "experiment_seed": int(tree.get("experiment_seed", 0)),
        "seeds": {str(k): int(v) for k, v in dict(tree.get("seeds") or {}).items()},
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def seed_tree_from_environment(
    environ: Optional[Mapping[str, str]] = None,
) -> Dict[str, Any]:
    """Resolve the seed tree from the governed environment variables.

    ``UP_EXPERIMENT_SEED`` is the single root.  A malformed value is an error,
    never a silent fallback to 42.
    """
    env = dict(environ if environ is not None else os.environ)
    raw = str(env.get("UP_EXPERIMENT_SEED", "")).strip()
    if not raw:
        raise ValueError(f"{SEED_MISSING}:UP_EXPERIMENT_SEED")
    try:
        root = int(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{SEED_INVALID}:UP_EXPERIMENT_SEED:{raw!r}") from exc

    overrides: Dict[str, int] = {}
    for domain in SEED_DOMAINS:
        key = f"UP_{domain.upper()}_SEED"
        val = str(env.get(key, "")).strip()
        if not val:
            continue
        try:
            overrides[domain] = int(val)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{SEED_INVALID}:{key}:{val!r}") from exc

    tree = build_seed_tree(root, overrides)
    tree["root_source"] = "UP_EXPERIMENT_SEED"
    tree["environment_overrides"] = overrides
    tree["seed_tree_sha256"] = seed_tree_sha256(tree)
    return tree


def environment_for_children(seed_tree: Mapping[str, Any]) -> Dict[str, str]:
    """Env overrides exporting the resolved seed tree to child processes."""
    seeds = dict(seed_tree.get("seeds") or {})
    out: Dict[str, str] = {
        "UP_EXPERIMENT_SEED": str(int(seed_tree.get("experiment_seed", 0))),
        "UP_TM_SEED": str(int(seeds.get(DOMAIN_TM, 0))),
        "UP_NPC_BLUEPRINT_SEED": str(int(seeds.get(DOMAIN_NPC_BLUEPRINT, 0))),
        "UP_NPC_SPAWN_SEED": str(int(seeds.get(DOMAIN_NPC_SPAWN, 0))),
        "UP_PEDESTRIAN_SEED": str(int(seeds.get(DOMAIN_PEDESTRIAN, 0))),
        "UP_WEATHER_SEED": str(int(seeds.get(DOMAIN_WEATHER, 0))),
        "UP_SCENARIO_SEED": str(int(seeds.get(DOMAIN_SCENARIO, 0))),
    }
    out["UP_SEED_TREE_SHA256"] = str(seed_tree.get("seed_tree_sha256") or seed_tree_sha256(seed_tree))
    return out


def validate_seed_tree(
    tree: Mapping[str, Any],
    *,
    strict: bool = True,
    require_domains: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Fail-closed validation of a resolved seed tree."""
    reasons: List[str] = []
    needed = list(require_domains if require_domains is not None else SEED_DOMAINS)
    seeds = dict(tree.get("seeds") or {})
    for domain in needed:
        if domain not in seeds:
            reasons.append(f"{SEED_MISSING}:{domain}")
            continue
        try:
            int(seeds[domain])
        except (TypeError, ValueError):
            reasons.append(f"{SEED_INVALID}:{domain}:{seeds[domain]!r}")
    if bool(tree.get("process_global_rng_mutated")):
        reasons.append(f"{SEED_INVALID}:process_global_rng_mutated")
    return {
        "valid": not reasons,
        "invalid_reasons": reasons,
        "seeds": seeds,
        "schema": SEED_TREE_SCHEMA,
        "strict": bool(strict),
    }


def validate_seed_tree_equality(
    manual_tree: Mapping[str, Any], auto_tree: Mapping[str, Any],
    *, domains: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Pair-level seed equality over the domains the protocol pins."""
    wanted = list(domains if domains is not None else SEED_DOMAINS)
    m = dict(manual_tree.get("seeds") or {})
    a = dict(auto_tree.get("seeds") or {})
    reasons: List[str] = []
    for domain in wanted:
        if domain not in m:
            reasons.append(f"{SEED_MISSING}:manual:{domain}")
        if domain not in a:
            reasons.append(f"{SEED_MISSING}:auto:{domain}")
        if domain in m and domain in a and int(m[domain]) != int(a[domain]):
            reasons.append(
                f"{SEED_TREE_MISMATCH}:{domain}:{m[domain]}!={a[domain]}"
            )
    if manual_tree.get("experiment_seed") is not None and \
            auto_tree.get("experiment_seed") is not None and \
            int(manual_tree["experiment_seed"]) != int(auto_tree["experiment_seed"]):
        reasons.append(
            f"{SEED_TREE_MISMATCH}:experiment_seed:"
            f"{manual_tree['experiment_seed']}!={auto_tree['experiment_seed']}"
        )
    return {
        "valid": not reasons,
        "invalid_reasons": reasons,
        "domains_checked": wanted,
    }