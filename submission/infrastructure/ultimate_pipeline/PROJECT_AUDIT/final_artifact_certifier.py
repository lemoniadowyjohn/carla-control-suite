import json
import hashlib
import xml.etree.ElementTree as ET
import os

def sha256sum(filename):
    h = hashlib.sha256()
    with open(filename, 'rb') as f:
        while True:
            b = f.read(128*1024)
            if not b:
                break
            h.update(b)
    return h.hexdigest()

def certify(xodr_path, output_path):
    tree = ET.parse(xodr_path)
    root = tree.getroot()
    
    # Check for elevation flatness (b,c,d coefficients must be zero)
    elevations = root.findall('.//elevation')
    flat = True
    for e in elevations:
        if float(e.get('b', 0)) != 0 or float(e.get('c', 0)) != 0 or float(e.get('d', 0)) != 0:
            flat = False
            break
            
    cert = {
        "file_path": xodr_path,
        "sha256": sha256sum(xodr_path),
        "road_count": len(root.findall('.//road')),
        "junction_count": len(root.findall('.//junction')),
        "elevation_flat": flat,
        "object_count": len(root.findall('.//object')),
        "signal_count": len(root.findall('.//signal')),
        "controller_count": len(root.findall('.//controller')),
        "geoReference_present": root.find('.//header/geoReference') is not None
    }
    
    with open(output_path, 'w') as f:
        json.dump(cert, f, indent=2)
    return cert

if __name__ == '__main__':
    certify('artifacts/final_runs/scenario_b_audit/contract_run/08_final_structural_gap.xodr', 
            'ultimate_pipeline/PROJECT_AUDIT/final_artifact_certification.json')
