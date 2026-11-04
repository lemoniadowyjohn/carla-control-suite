import os as _os
# Paths come from the environment (see REPRODUCE.md); no machine-specific paths.
CANDIDATE_WT = _os.environ["CANDIDATE_WT"]
RUN_DIR = _os.environ["RUN_DIR"].rstrip("/\\") + "/"
OUT_DIR = _os.environ.get("OUT_DIR", ".").rstrip("/\\") + "/"

import json, sys
import xml.etree.ElementTree as ET
inv=json.load(open(_os.environ['STUB_INVENTORY']))
base=RUN_DIR
for st,fn,key in (('01','01_sanitized_20261007_214826_524342.xodr','stage01_ids'),('02','02_sumo_fixed_20261007_214826_524342.xodr','stage02_ids')):
    root=ET.parse(base+fn).getroot()
    roads={r.get('id'):r for r in root.findall('road')}
    conns={}
    for j in root.findall('junction'):
        for c in j.findall('connection'):
            conns.setdefault(c.get('connectingRoad'),[]).append((j.get('id'),c))
    stats=dict(n=0,len_ok=0,one_geom=0,in_junction=0,has_conn_laneLink=0,stub_lane_succ_resolves=0,exit_exists=0,exit_is_connector_elsewhere=0)
    for rid in inv['reversed_heading_filtered'][key]:
        r=roads[rid]; stats['n']+=1
        L=float(r.get('length')); stats['len_ok']+= 0.09<=L<=0.11
        stats['one_geom']+= len(r.findall('planView/geometry'))==1
        stats['in_junction']+= r.get('junction')!='-1'
        cs=conns.get(rid,[]); stats['has_conn_laneLink']+= any(c.findall('laneLink') for _,c in cs)
        lk=r.find('link'); succ=lk.find('successor') if lk is not None else None; pred=lk.find('predecessor') if lk is not None else None
        # exit = the road-link end that is not the incoming road
        inc={c.get('incomingRoad') for _,c in cs}
        ends=[e for e in (succ,pred) if e is not None and e.get('elementType')=='road' and e.get('elementId') not in inc]
        if ends and ends[0].get('elementId') in roads:
            stats['exit_exists']+=1
            ex=roads[ends[0].get('elementId')]
            if ex.get('junction')!='-1': stats['exit_is_connector_elsewhere']+=1
            exlanes={l.get('id') for l in ex.iter('lane')}
            tag='successor' if ends[0] is succ else 'predecessor'
            ok=False
            for l in r.iter('lane'):
                if l.get('id')=='0': continue
                s=l.find('link/'+tag)
                if s is not None and s.get('id') in exlanes: ok=True
            stats['stub_lane_succ_resolves']+=ok
    print(st,stats)
