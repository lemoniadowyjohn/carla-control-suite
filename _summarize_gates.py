import json, os
d = r'stage8_rca_output\p0_before_gate_sweep'
keys = ['geometric_continuity','lane_connectivity','lane_section_successors','elevation_seams','elevation_continuity','origin_sanity','junction_integrity','elevation_missing_and_cliffs','elevation_smoothness','physics_feasibility','post_tiling_integrity','carla_import_s','carla_opendrive_compat','semantic_overlap','randomness_entropy','collision_mesh']
def g(j, *ks):
    for k in ks:
        if k in j:
            return j[k]
    return '?'
for k in keys:
    p = os.path.join(d, k + '.json')
    if not os.path.exists(p):
        print(k, 'MISSING'); continue
    j = json.load(open(p, encoding='utf-8'))
    print(f"{k:32} ok={g(j,'ok')} issues={g(j,'issue_count','num_issues','n_issues','broken_count','still_broken_count')} zero_ratio={g(j,'zero_ratio')} max_link_dz={g(j,'max_link_dz')}")
