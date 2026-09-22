#!/usr/bin/env python3
"""Fix stage_05_geometry.py get("ok", True) occurrences."""

filepath = "ultimate_pipeline/pipeline_stages/stage_05_geometry.py"

with open(filepath, "r") as f:
    content = f.read()

# Add import
if 'from ultimate_pipeline.quality.result_normalizer import' not in content:
    lines = content.split('\n')
    for i, line in enumerate(lines):
        if line.startswith('from __future__ import annotations'):
            lines.insert(i+1, 'from ultimate_pipeline.quality.result_normalizer import normalize_quality_result')
    content = '\n'.join(lines)
    with open(filepath, "w") as f:
        f.write(content)
    print('Added import')
else:
    print('Import already present')

# Fix occurrence 1: line 599
old1 = 'if not bool(full_cov.get("ok", True)):'
new1 = 'if not normalize_quality_result(full_cov).get("ok", False):'
if old1 in content:
    content = content.replace(old1, new1, 1)
    print('Fixed geometry occurrence 1')
else:
    print('Geometry occurrence 1 not found')

# Fix occurrence 2: line 813
old2 = 'dem_qc_report.get("ok", True)'
new2 = 'normalize_quality_result(dem_qc_report).get("ok", False)'
# Need to be careful - this might appear in different contexts
idx = content.find(old2)
if idx != -1:
    # Check context - should be used as a boolean condition
    context_start = max(0, idx - 20)
    context_end = min(len(content), idx + len(old2) + 20)
    print(f"Occurrence 2 found at {idx}, context: {content[context_start:context_end]}")
    # Replace only if it's used as a direct condition (not assigned to a variable)
    # Simple approach: just replace all occurrences but we'll be careful
    content = content.replace(old2, new2, 1)
    print('Fixed geometry occurrence 2')
else:
    print('Geometry occurrence 2 not found')

# Fix occurrence 3: line 878
old3 = 'dem_qc_report.get("ok", True)'
new3 = 'normalize_quality_result(dem_qc_report).get("ok", False)'
idx3 = content.find(old3)
if idx3 != -1:
    context_start = max(0, idx3 - 20)
    context_end = min(len(content), idx3 + len(old3) + 20)
    print(f"Occurrence 3 found at {idx3}, context: {content[context_start:context_end]}")
    content = content.replace(old3, new3, 1)
    print('Fixed geometry occurrence 3')
else:
    print('Geometry occurrence 3 not found')

# Fix occurrence 4: line 895
old4 = 'if (strict_dem or strict_quality) and not bool(dem_qc_report.get("ok", True)):'
new4 = 'if (strict_dem or strict_quality) and not normalize_quality_result(dem_qc_report).get("ok", False):'
if old4 in content:
    content = content.replace(old4, new4, 1)
    print('Fixed geometry occurrence 4')
else:
    print('Geometry occurrence 4 not found')

with open(filepath, "w") as f:
    f.write(content)

print("Done fixing stage_05_geometry.py")