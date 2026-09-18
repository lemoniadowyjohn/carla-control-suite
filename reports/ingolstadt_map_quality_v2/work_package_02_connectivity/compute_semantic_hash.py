#!/usr/bin/env python3
"""Compute canonical semantic hash (matching DSV08/determinism methodology).

Strips the <header> element (timestamp-containing), then computes SHA-256 of
the JSON-serialized canonical tree: [tag, sorted(attrs), norm_text(text), children].
"""
import hashlib
import json
import xml.etree.ElementTree as ET

REPAIRED = r"C:\Users\admin\PycharmProjects\gpt4\pythonProject3\carla_improvement\ingolstadt-map-quality-v2-202608\work_package_02_connectivity\candidate_connectivity_repaired.xodr"
ORIGINAL = r"C:\Users\admin\PycharmProjects\gpt4\pythonProject3\carla_full_replay\reports\full_replay_domain_gap_campaign_20260802T081541Z\replay\run_a\raw_replay_epsg32632_header_pinned.xodr"
BASELINE_SEM_HASH = "138e6aab2b5a23a9a254ee58c75d3d7deed6199f54b7f0aa3cefa4a79e774a1d"

def norm_text(t):
    if t is None:
        return ''
    return ''.join(t.split())

def canonical_hash_str(tree, include_header):
    def walk(el, include_hdr):
        kids = []
        for ch in el:
            if ch.tag == 'header' and not include_hdr:
                continue
            kids.append(walk(ch, include_hdr))
        return [el.tag, sorted(el.attrib.items()), norm_text(el.text), kids]
    t = walk(tree, include_header)
    return json.dumps(t, sort_keys=True, separators=(',', ':'), ensure_ascii=True)

def compute_hash(path, include_header=False):
    tree = ET.parse(path)
    root = tree.getroot()
    h = hashlib.sha256(canonical_hash_str(root, include_header).encode('utf-8')).hexdigest()
    return h

def main():
    print("Computing canonical semantic hashes...\n")
    
    h_repaired = compute_hash(REPAIRED, include_header=False)
    h_original = compute_hash(ORIGINAL, include_header=False)
    
    h_repaired_full = compute_hash(REPAIRED, include_header=True)
    h_original_full = compute_hash(ORIGINAL, include_header=True)
    
    print(f"Repaired (header excluded): {h_repaired}")
    print(f"Original (header excluded): {h_original}")
    print(f"Baseline target:           {BASELINE_SEM_HASH}")
    print()
    print(f"Repaired (header included):  {h_repaired_full}")
    print(f"Original (header included):  {h_original_full}")
    print()
    
    print("=== DIAGNOSTICS ===")
    print(f"Repaid ≠ Baseline: {h_repaired != BASELINE_SEM_HASH}")
    print(f"Repaired ≠ Original (header excl): {h_repaired != h_original}")
    print(f"Repaired ≠ Original (header incl): {h_repaired_full != h_original_full}")
    
    if h_repaired == BASELINE_SEM_HASH:
        print("\nWARNING: Repaired candidate has SAME canonical semantic hash as baseline!")
        print("Coordinate changes + link repairs produced semantically identical XML tree.")
        print("Need additional semantic content changes (e.g., elevation, signals, objects).")
    else:
        print("\nPASS: Repaired candidate has DIFFERENT canonical semantic hash from baseline.")

if __name__ == '__main__':
    main()
