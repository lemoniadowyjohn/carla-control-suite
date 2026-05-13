# tools/json_to_csv.py

import json
import csv
import sys

inp = sys.argv[1]
out = sys.argv[2]

with open(inp, "r", encoding="utf-8") as f:
    rows = json.load(f)

if not rows:
    sys.exit(0)

fields = sorted(rows[0].keys())

with open(out, "w", encoding="utf-8", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=fields)
    writer.writeheader()
    writer.writerows(rows)
