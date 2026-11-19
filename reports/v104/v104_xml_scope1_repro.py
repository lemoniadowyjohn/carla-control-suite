"""V104 Scope 1 — reproduce V96-XMLBOUND-001 on the PR #30 implementation.

Runs against the PR #30 worktree (head 4d38a1fc) so the reproduction is
against the exact source that owns the finding.
"""

import sys

PR30 = r"F:\wt\v86-acceptance-strict"
sys.path.insert(0, PR30)

from ultimate_pipeline.quality.final_artifact_gates import (  # noqa: E402
    UnsafeXMLError,
    check_xml_boundary,
    parse_xodr_bytes,
)

print("PR#30 source:", PR30)
print()

cases = []

# --- A. UTF-16 encoded DOCTYPE -------------------------------------------
utf16_doc = (
    '<?xml version="1.0" encoding="UTF-16"?>'
    '<!DOCTYPE OpenDRIVE [<!ENTITY xxe SYSTEM "file:///etc/passwd">]>'
    '<OpenDRIVE><road id="1" name="r" length="1" junction="-1"/></OpenDRIVE>'
)
cases.append(("A_utf16_doctype", utf16_doc.encode("utf-16")))

# --- B. DOCTYPE beyond the 64 KiB prefix window --------------------------
padding = b"<!-- " + (b"x" * 70000) + b" -->"
late_doctype = b'<!DOCTYPE OpenDRIVE [<!ENTITY xxe SYSTEM "file:///etc/passwd">]>'
cases.append(
    ("B_late_doctype_gt_64kib", b"<OpenDRIVE>" + padding + late_doctype + b"</OpenDRIVE>")
)

# --- C. fake OpenDRIVE token inside a comment before the padding ---------
fake = b"<!-- <OpenDRIVE> -->"
cases.append(
    (
        "C_fake_opendrive_token_in_comment",
        fake + padding + late_doctype + b"</OpenDRIVE>",
    )
)

# --- controls ------------------------------------------------------------
controls = [
    ("control_plain", b"<OpenDRIVE><road id='1'/></OpenDRIVE>"),
    (
        "control_literal_doctype_in_comment",
        b"<!-- <!DOCTYPE not a declaration -->" + b"<OpenDRIVE><road id='1'/></OpenDRIVE>",
    ),
    ("control_early_doctype", b"<!DOCTYPE OpenDRIVE><OpenDRIVE/>"),
]

results = []

print("=== BYPASS CASES ===")
for name, payload in cases:
    try:
        check_xml_boundary(payload)
        print(f"  {name}: ACCEPTED  -> BYPASS PRESENT")
        results.append((name, "BYPASS"))
    except UnsafeXMLError as exc:
        print(f"  {name}: rejected  -> {exc}")
        results.append((name, "REJECTED"))

print()
print("=== does the payload actually reach the parser? ===")
for name, payload in cases:
    try:
        root = parse_xodr_bytes(payload)
        print(f"  {name}: PARSED, root tag = {root.tag}  -> the attack is LIVE")
    except UnsafeXMLError as exc:
        print(f"  {name}: blocked by the boundary -> {exc}")
    except Exception as exc:
        print(f"  {name}: parser refused for another reason -> {type(exc).__name__}: {exc}")

print()
print("=== CONTROLS (must be accepted) ===")
for name, payload in controls:
    try:
        check_xml_boundary(payload)
        print(f"  {name}: accepted (correct)")
        results.append((name, "ACCEPTED"))
    except UnsafeXMLError as exc:
        print(f"  {name}: REJECTED (false positive) -> {exc}")
        results.append((name, "FALSE_POSITIVE"))

print()
print("=== SUMMARY ===")
for name, status in results:
    print(f"  {name:42s} {status}")
bypasses = [r for r in results if r[1] == "BYPASS"]
print()
print("V96-XMLBOUND-001 STILL REPRODUCED:", bool(bypasses))
print("REPAIRED IMPLEMENTATION PRESENT:", not bool(bypasses))
