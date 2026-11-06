import json
o = json.load(open('stage8_rca_output/p0_before_oracle.json', encoding='utf-8'))
c = o['connector_lane_interface_dz']
print('totals:', c['interface_links'], c['bad_seams'], c['worst_dz'])
for rec in c['bad_examples'][:15]:
    print(rec['junction_id'], rec['connector_road'], rec['from'], '->', rec['to'],
          'dz_s', rec['dz_start'], 'dz_e', rec['dz_end'], rec['classification'])
