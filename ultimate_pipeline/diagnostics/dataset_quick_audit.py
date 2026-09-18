#!/usr/bin/env python3
from pathlib import Path

def audit_yolo_dataset(root: Path):
    print(f"🔍 Auditing dataset at: {root}")

    images_dir = root / "images" / "train"
    labels_dir = root / "labels" / "train"

    if not images_dir.exists() or not labels_dir.exists():
        print("❌ images/train or labels/train folder missing")
        return

    images = sorted(p for p in images_dir.glob("*.jpg")) + sorted(p for p in images_dir.glob("*.png"))
    labels = sorted(labels_dir.glob("*.txt"))

    print(f"📸 Train images: {len(images)}")
    print(f"📝 Train label files: {len(labels)}")

    # 1. check name matching
    image_basenames = {p.stem for p in images}
    label_basenames = {p.stem for p in labels}

    missing_labels = image_basenames - label_basenames
    orphan_labels = label_basenames - image_basenames

    if missing_labels:
        print(f"❌ Images without labels: {len(missing_labels)} (e.g. {list(missing_labels)[:5]})")
    else:
        print("✅ Every image has a label file")

    if orphan_labels:
        print(f"❌ Labels without images: {len(orphan_labels)} (e.g. {list(orphan_labels)[:5]})")
    else:
        print("✅ No orphan label files")

    # 2. check label content format
    examples_checked = 0
    bad_files = []
    for lbl in labels[:50]:  # just sample a bit
        txt = lbl.read_text().strip()
        if not txt:
            # empty label file is allowed, but we warn
            continue
        for line in txt.splitlines():
            parts = line.split()
            if len(parts) != 5:
                bad_files.append((lbl, f"Expected 5 values, got {len(parts)}"))
                break
            try:
                cls = int(parts[0])
                vals = list(map(float, parts[1:]))
                if not all(0.0 <= v <= 1.0 for v in vals):
                    bad_files.append((lbl, "Coords not normalized 0–1"))
                    break
            except Exception as e:
                bad_files.append((lbl, f"Parse error: {e}"))
                break
        examples_checked += 1

    if bad_files:
        print("❌ Some label files have invalid format:")
        for f, msg in bad_files[:5]:
            print(f"   - {f.name}: {msg}")
    else:
        print(f"✅ First {examples_checked} label files look OK (YOLO format)")

if __name__ == "__main__":
    # TODO: set this to your actual dataset root, e.g. "training_data/auto_yolo"
    dataset_root = Path("training_data/auto_yolo")
    audit_yolo_dataset(dataset_root)
