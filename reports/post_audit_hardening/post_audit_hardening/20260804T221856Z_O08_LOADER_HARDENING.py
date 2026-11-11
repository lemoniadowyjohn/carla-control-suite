"""DEPRECATED prototype - superseded by canonical loader hardening.

This file was a one-off hardening prototype generated for the O08 decision
(20260804T221856Z). All hardening behavior here has been ported into the
canonical production loader:

  ultimate_pipeline/core/carla_opendrive_loader.py
    - load_opendrive_world() / load_opendrive_world_from_file()
    - StrictCarlaOpendriveGate preflight (_preflight_xodr) before any CARLA call
    - world-tick verification (ensure_world_ticks) after generation
    - built-in town fallback blocked (opendrive_load_fallback_blocked)

plus the canonical identity guards:
  ultimate_pipeline/core/xodr_hash_gate.py
  ultimate_pipeline/carla_tools/map_identity_guard.py

The hardcoded EXPECTED_CANDIDATE below references the OLD source candidate
(ff2a05e7...) which is superseded by the repaired candidate (80ebb005...) per
O06_RUNTIME_INPUT_AUTHORITY. Do not use this file for new loads.
"""
import hashlib
import os
import sys
import carla

UP_THESIS_STRICT = os.environ.get('UP_THESIS_STRICT', '1') == '1'

EXPECTED_CANDIDATE = {
    'path': 'campaigns/ingolstadt_cooked_perception_v1/candidate/raw_xodr_run_1_epsg32632_header_pinned.xodr',
    'sha256': 'ff2a05e7b00b8fc1bde38f569413223c03a4f4ac9c31eceb5a8592df47d0d17d',
    'semantic_sha256': '019fc30e989e596b6dedccf82aefa4bad011b0c54ed3e5f185d8b262824ec84e',
    'road_count': 32710,
    'junction_count': 3646,
    'byte_size': 82318919,
}


def compute_sha256(data):
    if isinstance(data, str):
        data = data.encode('utf-8')
    return hashlib.sha256(data).hexdigest()


def load_opendrive_world_enforced(client, xodr_path, expected_sha256=None, expected_road_count=None, expected_junction_count=None, fail_on_town_fallback=True):
    expected_sha256 = expected_sha256 or EXPECTED_CANDIDATE['sha256']
    expected_road_count = expected_road_count or EXPECTED_CANDIDATE['road_count']
    expected_junction_count = expected_junction_count or EXPECTED_CANDIDATE['junction_count']

    if not os.path.exists(xodr_path):
        raise FileNotFoundError(f'XODR file not found: {xodr_path}')

    with open(xodr_path, 'rb') as f:
        xodr_bytes = f.read()

    source_sha256 = hashlib.sha256(xodr_bytes).hexdigest()
    if source_sha256 != expected_sha256:
        raise ValueError(f'Source XODR SHA-256 mismatch: expected {expected_sha256}, got {source_sha256}')

    xodr_text = xodr_bytes.decode('utf-8')
    world = client.generate_opendrive_world(xodr_text)

    map_obj = world.get_map()
    map_name = map_obj.name

    if fail_on_town_fallback and 'Town' in map_name and 'Ingolstadt' not in map_name:
        raise RuntimeError(f'Town fallback detected: loaded map is {map_name}, expected Ingolstadt candidate')

    runtime_opendrive = map_obj.to_opendrive()
    runtime_sha256 = compute_sha256(runtime_opendrive)
    if runtime_sha256 != expected_sha256:
        raise ValueError(f'Runtime XODR SHA-256 mismatch: expected {expected_sha256}, got {runtime_sha256}')

    topology = map_obj.get_topology()
    road_ids = set()
    junction_ids = set()
    for wp_pair in topology:
        for wp in wp_pair:
            road_ids.add(wp.road_id)
            if wp.junction_id is not None and wp.junction_id != 0:
                junction_ids.add(wp.junction_id)

    actual_road_count = len(road_ids)
    actual_junction_count = len(junction_ids)

    if actual_road_count < expected_road_count * 0.9:
        raise ValueError(f'Road count mismatch: expected ~{expected_road_count}, got {actual_road_count}')

    if actual_junction_count < expected_junction_count * 0.9:
        raise ValueError(f'Junction count mismatch: expected ~{expected_junction_count}, got {actual_junction_count}')

    return world, {
        'source_sha256': source_sha256,
        'runtime_sha256': runtime_sha256,
        'map_name': map_name,
        'road_count': actual_road_count,
        'junction_count': actual_junction_count,
        'xodr_path': xodr_path,
    }


def load_builtin_world_enforced(client, map_name, expected_substring='Ingolstadt'):
    if 'Town' in map_name and expected_substring not in map_name:
        if UP_THESIS_STRICT:
            raise RuntimeError(f'Forbidden map fallback: {map_name} does not contain {expected_substring}')
        else:
            print(f'WARNING: Map {map_name} does not contain {expected_substring}', file=sys.stderr)

    world = client.load_world(map_name)
    return world


def validate_world_map_enforced(world, expected_sha256=None, expected_road_count=None, expected_junction_count=None):
    expected_sha256 = expected_sha256 or EXPECTED_CANDIDATE['sha256']
    expected_road_count = expected_road_count or EXPECTED_CANDIDATE['road_count']
    expected_junction_count = expected_junction_count or EXPECTED_CANDIDATE['junction_count']

    map_obj = world.get_map()
    map_name = map_obj.name

    errors = []
    warnings = []

    if 'Town' in map_name and 'Ingolstadt' not in map_name:
        msg = f'Town fallback detected: loaded map is {map_name}'
        if UP_THESIS_STRICT:
            errors.append(msg)
        else:
            warnings.append(msg)

    runtime_opendrive = map_obj.to_opendrive()
    runtime_sha256 = compute_sha256(runtime_opendrive)
    if runtime_sha256 != expected_sha256:
        errors.append(f'Runtime XODR SHA-256 mismatch: expected {expected_sha256}, got {runtime_sha256}')

    topology = map_obj.get_topology()
    road_ids = set()
    junction_ids = set()
    for wp_pair in topology:
        for wp in wp_pair:
            road_ids.add(wp.road_id)
            if wp.junction_id is not None and wp.junction_id != 0:
                junction_ids.add(wp.junction_id)

    actual_road_count = len(road_ids)
    actual_junction_count = len(junction_ids)

    if actual_road_count < expected_road_count * 0.9:
        errors.append(f'Road count mismatch: expected ~{expected_road_count}, got {actual_road_count}')

    if actual_junction_count < expected_junction_count * 0.9:
        errors.append(f'Junction count mismatch: expected ~{expected_junction_count}, got {actual_junction_count}')

    return {
        'valid': len(errors) == 0,
        'map_name': map_name,
        'runtime_sha256': runtime_sha256,
        'road_count': actual_road_count,
        'junction_count': actual_junction_count,
        'errors': errors,
        'warnings': warnings,
    }
