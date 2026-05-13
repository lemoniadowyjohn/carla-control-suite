#!/usr/bin/env python3
import os
import re

ROOT = r"C:\Users\admin\PycharmProjects\gpt4\pythonProject3\carla_-main\ultimate_pipeline"

# regex: capture imports starting with core., topology., geometry., osm., etc.
PATTERN = re.compile(
    r"from\s+(core|geometry|topology|osm|carla_tools|utils|lanes|enrichment|diagnostics|tiling|tile_validation|analysis|domain_gap|perception|quality|reports|scenarios|sensors)\.(.*?)\s+import\s+(.*)"
)

def fix_line(line):
    m = PATTERN.search(line)
    if not m:
        return line

    group = m.group(1)
    module = m.group(2)
    names = m.group(3)

    new_line = f"from ultimate_pipeline.{group}.{module} import {names}"
    print("[FIX] ", new_line)
    return new_line + "\n"


def process_file(path):
    with open(path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    new_lines = []
    changed = False
    for line in lines:
        new_line = fix_line(line)
        if new_line != line:
            changed = True
        new_lines.append(new_line)

    if changed:
        with open(path, "w", encoding="utf-8") as f:
            f.writelines(new_lines)
        print("✔ Updated:", path)


def walk():
    for root, dirs, files in os.walk(ROOT):
        for file in files:
            if file.endswith(".py"):
                process_file(os.path.join(root, file))

walk()
print("🎉 Import rewriting complete!")
