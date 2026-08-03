import xml.etree.ElementTree as ET
from pathlib import Path
import json

REPAIRED_CANDIDATE = r"C:\Users\admin\PycharmProjects\gpt4\pythonProject3\carla_improvement\ingolstadt-map-quality-v2-202608\work_package_02_connectivity\candidate_connectivity_repaired.xodr"
ORIGINAL_CANDIDATE = r"C:\Users\admin\PycharmProjects\gpt4\pythonProject3\carla_full_replay\reports\full_replay_domain_gap_campaign_20260802T081541Z\replay\run_a\raw_replay_epsg32632_header_pinned.xodr"
OUTPUT_PATH = Path(REPAIRED_CANDIDATE).parent / "validation_report.json"

def load_xodr(path):
    tree = ET.parse(path)
    return tree.getroot()

def get_junction_connections(root):
    junctions = {}
    for j in root.findall('./junction'):
        jid = j.get('id')
        conns = set()
        for c in j.findall('./connection'):
            conns.add((c.get('incomingRoad'), c.get('connectingRoad'), c.get('contactPoint')))
        junctions[jid] = conns
    return junctions

def get_road_links(root):
    road_ids = set()
    road_to_road_links = []
    for r in root.findall('./road'):
        rid = r.get('id')
        road_ids.add(rid)
        link = r.find('./link')
        if link is not None:
            for el in link:
                if el.tag in ('predecessor', 'successor') and el.get('elementType') == 'road':
                    road_to_road_links.append({
                        'road': rid,
                        'link_type': el.tag,
                        'target': el.get('elementId'),
                        'contactPoint': el.get('contactPoint')
                    })
    return road_ids, road_to_road_links

def analyze():
    print("Loading repaired candidate...")
    repaired_root = load_xodr(REPAIRED_CANDIDATE)

    print("Loading original candidate...")
    original_root = load_xodr(ORIGINAL_CANDIDATE)

    print("Comparing junctions...")
    orig_juncs = get_junction_connections(original_root)
    rep_juncs = get_junction_connections(repaired_root)

    added_juncs = [jid for jid in rep_juncs if jid not in orig_juncs]
    removed_juncs = [jid for jid in orig_juncs if jid not in rep_juncs]
    modified_juncs = []
    for jid in set(orig_juncs.keys()) & set(rep_juncs.keys()):
        if orig_juncs[jid] != rep_juncs[jid]:
            modified_juncs.append(jid)

    print("Analyzing road links...")
    rep_road_ids, rep_links = get_road_links(repaired_root)
    _, orig_links = get_road_links(original_root)

    dangling = [ll for ll in rep_links if ll['target'] not in rep_road_ids]

    link_index = {(ll['road'], ll['link_type'], ll['target']): ll for ll in rep_links}
    reciprocal = 0
    for ll in rep_links:
        reverse_key = (ll['target'], 'successor' if ll['link_type'] == 'predecessor' else 'predecessor', ll['road'])
        if reverse_key in link_index:
            reciprocal += 1

    total_links = len(rep_links)
    pred_links = sum(1 for ll in rep_links if ll['link_type'] == 'predecessor')
    succ_links = sum(1 for ll in rep_links if ll['link_type'] == 'successor')

    print("Counting lane links...")
    lane_links_repaired = 0
    for r in repaired_root.findall('./road'):
        for cl in r.findall('.//lane/link'):
            lane_links_repaired += len(cl.findall('./*'))

    roads_count = len(list(repaired_root.findall('./road')))
    junctions_count = len(list(repaired_root.findall('./junction')))
    lane_count = sum(len(r.findall('.//lane')) for r in repaired_root.findall('./road'))

    report = {
        'connectivity_analysis': {
            'total_road_links': total_links,
            'predecessor_links': pred_links,
            'successor_links': succ_links,
            'dangling_links_count': len(dangling),
            'dangling_links_sample': dangling[:5],
            'reciprocal_links_count': reciprocal,
            'reciprocal_links_ratio': round(reciprocal / total_links, 4) if total_links > 0 else 0,
            'lane_links_count': lane_links_repaired,
            'topology_changes': {
                'added_junctions_count': len(added_juncs),
                'removed_junctions_count': len(removed_juncs),
                'modified_junctions_count': len(modified_juncs),
                'added_junctions_sample': added_juncs[:10],
                'modified_junctions_sample': modified_juncs[:10]
            }
        },
        'road_network_summary': {
            'roads': roads_count,
            'junctions': junctions_count,
            'lanes': lane_count,
        },
        'validation': {
            'no_dangling_links': len(dangling) == 0,
            'reciprocal_links_exist': reciprocal > 0,
            'no_junctions_added_or_removed': len(added_juncs) == 0 and len(removed_juncs) == 0,
            'lane_count_preserved': lane_count == 84781,
        }
    }

    OUTPUT_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"Validation report written to {OUTPUT_PATH}")
    return report

if __name__ == '__main__':
    report = analyze()
    print("\n=== VALIDATION SUMMARY ===")
    ca = report['connectivity_analysis']
    print(f"Total road links: {ca['total_road_links']}")
    print(f"  Predecessors: {ca['predecessor_links']}, Successors: {ca['successor_links']}")
    print(f"Dangling links: {ca['dangling_links_count']}")
    print(f"Reciprocal links: {ca['reciprocal_links_count']} ({ca['reciprocal_links_ratio']*100:.1f}%)")
    print(f"Lane links: {ca['lane_links_count']}")
    print(f"Junctions: {report['road_network_summary']['junctions']}")
    print(f"Lanes: {report['road_network_summary']['lanes']}")
    print(f"\nValidation:")
    for k, v in report['validation'].items():
        print(f"  {k}: {v}")
