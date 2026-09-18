import json
import re
from pathlib import Path

LEDGER_PATH = Path("AGENT_TASK_LEDGER.md")
OUTPUT_PATH = Path("artifacts/governance/ledger_salvage_index.json")

def build_salvage_index():
    if not LEDGER_PATH.exists():
        print(f"Error: {LEDGER_PATH} not found.")
        return

    with open(LEDGER_PATH, "r", encoding="utf-8") as f:
        lines = f.readlines()

    blocks = []
    current_block = {}
    block_start_line = 0
    
    # Regex for task heading: ### <Task ID> — <Title>
    task_heading_re = re.compile(r"^###\s+(T-[A-Z0-9-]+|R-[A-Z0-9-]+)\s+[—–-]\s+(.+)$")
    # Regex for other headings: #, ##, ### (but not task)
    section_heading_re = re.compile(r"^(#+)\s+(.+)$")
    
    # Regex for property lines: - Key: Value
    property_re = re.compile(r"^-\s+([A-Za-z0-9 ]+):\s*(.*)$")

    current_block = {
        "block_number": 0,
        "start_line": 0,
        "type": "preamble",
        "heading_task_id": None,
        "title": "Preamble",
        "properties": {},
        "raw_content": []
    }

    for i, line in enumerate(lines):
        line_stripped = line.strip()
        
        task_match = task_heading_re.match(line_stripped)
        section_match = section_heading_re.match(line_stripped)
        
        if task_match:
            # Close current block
            current_block["end_line"] = i
            blocks.append(current_block)

            # Start new TASK block
            task_id = task_match.group(1)
            title = task_match.group(2)
            
            current_block = {
                "block_number": len(blocks),
                "start_line": i + 1,
                "type": "task",
                "heading_task_id": task_id,
                "title": title,
                "properties": {},
                "raw_content": [line]
            }
        elif section_match:
            # Check if it's a task heading (already handled) or a generic section
            # If it matched task_heading_re, we wouldn't be here (elif)
            # But wait, logic: task_heading_re is specific. section_heading_re is general.
            # So if it matches task_heading_re, it enters the first block.
            # If it matches section_heading_re BUT NOT task_heading_re, it enters here.
            
            # Close current block
            current_block["end_line"] = i
            blocks.append(current_block)
            
            level = len(section_match.group(1))
            title = section_match.group(2)
            
            current_block = {
                "block_number": len(blocks),
                "start_line": i + 1,
                "type": "section",
                "heading_task_id": None,
                "title": title,
                "properties": {},
                "raw_content": [line]
            }
        else:
            # Append to current block
            current_block["raw_content"].append(line)
            if current_block["type"] == "task":
                prop_match = property_re.match(line_stripped)
                if prop_match:
                    key = prop_match.group(1).strip()
                    value = prop_match.group(2).strip()
                    current_block["properties"][key] = value

    # Append the last block
    current_block["end_line"] = len(lines)
    blocks.append(current_block)

    # Post-processing for validation
    task_id_counts = {}
    for block in blocks:
        if block["type"] == "task":
            props = block["properties"]
            heading_id = block["heading_task_id"]
            body_id = props.get("Task ID", "").strip()
            
            block["task_id_value"] = body_id
            block["status"] = props.get("Status", "").strip()
            block["task_class"] = props.get("Task Class", "").strip()
            block["owner"] = props.get("Owner", "").strip()
            
            block["heading_body_match"] = (heading_id == body_id) if body_id else False
            
            # Check metadata for PATCH tasks
            if block["task_class"] == "PATCH":
                required_keys = ["Active Branch", "Target Files", "Patch Ready", "Minimum Verification"]
                missing = [k for k in required_keys if k not in props or props[k] == "TBD"]
                block["missing_patch_metadata"] = missing
            else:
                block["missing_patch_metadata"] = []

            # Count occurrences
            task_id = heading_id
            task_id_counts[task_id] = task_id_counts.get(task_id, 0) + 1

    # Mark duplicates
    for block in blocks:
        if block["type"] == "task":
            task_id = block["heading_task_id"]
            block["is_duplicate"] = task_id_counts[task_id] > 1

    # Ensure output directory exists
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(blocks, f, indent=2)

    print(f"Salvage index created at {OUTPUT_PATH} with {len(blocks)} blocks.")

if __name__ == "__main__":
    build_salvage_index()
