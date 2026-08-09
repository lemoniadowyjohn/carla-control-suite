"""C0-R tag-anchored freeze verifier (read-only; schema C0R_TAG_ANCHORED_V2).

Verifies the R13 terminal-C0-R freeze identity WITHOUT writing anything:

  tag exists and is annotated
  tag^{commit} == HEAD       (the tag is the authoritative carrying identity)
  tag^{tree}   == HEAD^{tree}
  current branch correct
  working tree clean
  R13 / R13O / R13P paths exist
  on-disk SHA-256 of R13 / R13O / R13P == machine lines in the tag message
  every R13P evidence entry exists and its SHA-256 matches the manifest
  R13O schema is C0R_TAG_ANCHORED_V2 and contains no future-self fields
    (head_commit / freeze_commit / carrying_commit / tag_object_sha)
  pre-freeze parent recorded in R13O == actual parent of the freeze commit
  no provisional pre-C0 artifact is listed as current release authority

Success verdict: C0R_TAG_FREEZE_VERIFIED   (exit code 0)
Any failure    : C0R_TAG_FREEZE_NOT_VERIFIED (exit code 1)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

FREEZE_BRANCH = "fix/post-audit-phase-e-junctions-roundabouts-20260803"
FREEZE_SCHEMA = "C0R_TAG_ANCHORED_V2"
FORBIDDEN_KEYS = ("head_commit", "freeze_commit", "carrying_commit", "tag_object_sha")
R13_REL = "reports/post_audit_hardening/20260808T000000Z_C0_REMEDIATION/R13_UPDATED_CLAUDE_C0_PACKET.md"
R13O_REL = "reports/post_audit_hardening/20260808T000000Z_C0_REMEDIATION/R13O_C0_REVIEW_FREEZE.json"
R13P_REL = "reports/post_audit_hardening/20260808T000000Z_C0_REMEDIATION/R13P_C0_PRIMARY_EVIDENCE_MANIFEST.json"
R13R_REL = "reports/post_audit_hardening/20260808T000000Z_C0_REMEDIATION/R13R_REPOSITORY_BINDING.json"

MESSAGE_KEYS = (
    "freeze_schema", "freeze_commit", "freeze_tree", "freeze_parent",
    "branch", "repository",
    "r13_path", "r13_sha256", "r13o_path", "r13o_sha256",
    "manifest_path", "manifest_sha256",
    "repository_binding_path", "repository_binding_sha256",
)

VERDICT_OK = "C0R_TAG_FREEZE_VERIFIED"
VERDICT_BAD = "C0R_TAG_FREEZE_NOT_VERIFIED"


def _git(repo: Path, *args: str) -> Tuple[int, str, str]:
    r = subprocess.run(["git", *args], cwd=str(repo),
                       capture_output=True, text=True)
    return r.returncode, r.stdout.strip(), r.stderr.strip()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _rel(repo: Path, path: Path) -> str:
    try:
        return str(path.relative_to(repo)).replace("\\", "/")
    except ValueError:
        return str(path).replace("\\", "/")


def _git_out(repo: Path, *args: str) -> str:
    rc, out, _ = _git(repo, *args)
    return out if rc == 0 else ""


@dataclass
class FreezeCheck:
    name: str
    ok: bool
    detail: str = ""


@dataclass
class C0RFreezeResult:
    verdict: str
    checks: List[FreezeCheck] = field(default_factory=list)

    def to_dict(self) -> Dict:
        return {
            "verdict": self.verdict,
            "checks": [{"name": c.name, "ok": c.ok, "detail": c.detail}
                       for c in self.checks],
        }


class C0RTagFreezeVerifier:
    """Read-only git tag freeze verification (never mutates the repo)."""

    def __init__(
        self,
        repo: Path,
        tag: str,
        *,
        branch: str = FREEZE_BRANCH,
        r13_path: Optional[Path] = None,
        r13o_path: Optional[Path] = None,
        r13p_path: Optional[Path] = None,
        r13r_path: Optional[Path] = None,
    ) -> None:
        self.repo = repo
        self.tag = tag
        self.branch_expected = branch
        self.r13 = r13_path or repo / R13_REL
        self.r13o = r13o_path or repo / R13O_REL
        self.r13p = r13p_path or repo / R13P_REL
        self.r13r = r13r_path or repo / R13R_REL
        self.checks: List[FreezeCheck] = []

    # ------------------------------------------------------------------
    def _add(self, name: str, ok: bool, detail: str = "") -> bool:
        self.checks.append(FreezeCheck(name, ok, detail))
        return ok

    def _tag_message(self) -> Dict[str, str]:
        rc, out, _ = _git(self.repo, "for-each-ref",
                          "--format=%(contents)", f"refs/tags/{self.tag}")
        if rc != 0:
            return {}
        meta: Dict[str, str] = {}
        for line in out.splitlines():
            line = line.strip()
            if "=" in line:
                k, _, v = line.partition("=")
                meta[k.strip()] = v.strip()
        return meta

    # ------------------------------------------------------------------
    def verify(self) -> C0RFreezeResult:
        self.checks = []

        # 1 tag exists
        rc, typ, _ = _git(self.repo, "cat-file", "-t", self.tag)
        tag_exists = rc == 0 and typ in ("tag", "commit")
        if not self._add("tag_exists", tag_exists,
                         f"cat-file rc={rc} type={typ or '<none>'}"):
            return self._result()

        # 2 annotated (lightweight tags resolve to type 'commit')
        self._add("tag_is_annotated", typ == "tag",
                  f"type={typ}")

        tag_commit = _git_out(self.repo, "rev-parse", f"{self.tag}^{{commit}}")
        tag_tree = _git_out(self.repo, "rev-parse", f"{self.tag}^{{tree}}")
        head = _git_out(self.repo, "rev-parse", "HEAD")
        head_tree = _git_out(self.repo, "rev-parse", "HEAD^{tree}")

        self._add("tag_commit_matches_head",
                  bool(tag_commit) and tag_commit == head,
                  f"tag={tag_commit[:12] or '<none>'} head={head[:12]}")
        self._add("tag_tree_matches_head_tree",
                  bool(tag_tree) and tag_tree == head_tree,
                  f"tag={tag_tree[:12] or '<none>'} head={head_tree[:12]}")

        # 3 branch
        branch = _git_out(self.repo, "rev-parse", "--abbrev-ref", "HEAD")
        self._add("branch_correct", branch == self.branch_expected,
                  f"got={branch} expected={self.branch_expected}")

        # 4 clean tree
        _, porc, _ = _git(self.repo, "status", "--porcelain")
        self._add("worktree_clean", porc == "",
                  f"porcelain_lines={len(porc.splitlines()) if porc else 0}")

        # 5 required files exist
        for name, p in (("r13_present", self.r13), ("r13o_present", self.r13o),
                        ("r13p_present", self.r13p)):
            if not self._add(name, p.is_file(), str(p) + (" ok" if p.is_file() else " MISSING")):
                return self._result()

        # 6 tag-message metadata vs on-disk hashes
        meta = self._tag_message()
        for key in MESSAGE_KEYS:
            if key not in meta:
                self._add(f"tag_message_has_{key}", False, f"line '{key}=...' missing")
        for name, key, path in (
            ("r13_sha_matches_tag_metadata", "r13_sha256", self.r13),
            ("r13o_sha_matches_tag_metadata", "r13o_sha256", self.r13o),
            ("r13p_sha_matches_tag_metadata", "manifest_sha256", self.r13p),
            ("r13r_sha_matches_tag_metadata", "repository_binding_sha256",
             self.r13r),
        ):
            disk = sha256_file(path)
            meta_sha = meta.get(key, "")
            self._add(name, bool(meta_sha) and meta_sha == disk,
                      f"tag={meta_sha[:16] or '<missing>'} disk={disk[:16]}")

        # 7 repository binding (tag message must name the exact checkout)
        top = _git_out(self.repo, "rev-parse", "--show-toplevel")
        repo_line = meta.get("repository", "")
        norm_top = (top or "").replace("\\", "/").lower()
        norm_line = repo_line.replace("\\", "/").lower()
        self._add("repository_line_matches_toplevel",
                  bool(norm_top) and norm_top == norm_line,
                  f"msg={repo_line or '<missing>'} toplevel={top}")
        self._add("repository_binding_receipt_present", self.r13r.is_file(),
                  str(self.r13r) + (" ok" if self.r13r.is_file() else " MISSING"))

        # 8 manifest: R13R listed, entries present/hashes match
        try:
            manifest = json.loads(self.r13p.read_text(encoding="utf-8"))
        except Exception as exc:
            self._add("manifest_parse", False, str(exc))
            return self._result()
        entries = manifest.get("entries") or []
        binding_present_in_manifest = any(
            (e.get("path") or "") == _rel(self.repo, self.r13r)
            for e in entries)
        self._add("manifest_contains_repository_binding",
                  binding_present_in_manifest,
                  f"r13_rel={_rel(self.repo, self.r13r)}")
        all_present, all_match, all_immutable = True, True, True
        mismatched = []
        for e in entries:
            rel = e.get("path") or ""
            if e.get("role") == "r13p_evidence_manifest_self":
                continue  # self entry: no embedded sha
            fpath = self.repo / rel
            if not fpath.is_file():
                all_present = False
                continue
            if not e.get("immutable_for_review", False):
                all_immutable = False
            exp = e.get("sha256")
            if exp and sha256_file(fpath) != exp:
                all_match = False
                mismatched.append(rel)
        self._add("manifest_all_entries_present", all_present, f"entries_with_sha={len(entries)}")
        self._add("manifest_all_sha256_match", all_match, f"mismatched={mismatched[:5]}")
        self._add("manifest_all_immutable", all_immutable)

        # 8 R13O schema, no future-self fields, parent == HEAD^
        r13o_ok = True
        r13o_detail = ""
        try:
            r13o = json.loads(self.r13o.read_text(encoding="utf-8"))
            forbidden = [k for k in FORBIDDEN_KEYS if k in r13o]
            if r13o.get("freeze_schema") != FREEZE_SCHEMA:
                r13o_ok = False
                r13o_detail += f" freeze_schema={r13o.get('freeze_schema')}"
            if r13o.get("freeze_tag") != self.tag:
                r13o_ok = False
                r13o_detail += f" freeze_tag={r13o.get('freeze_tag')}"
            if forbidden:
                r13o_ok = False
                r13o_detail += f" forbidden={forbidden}"
            parent = _git_out(self.repo, "rev-parse", "HEAD^")
            if r13o.get("parent_commit") != parent:
                r13o_ok = False
                r13o_detail += (f" parent={ (r13o.get('parent_commit') or '')[:12]}"
                                f" actual={parent[:12]}")
        except Exception as exc:
            r13o_ok = False
            r13o_detail = str(exc)
        self._add("r13o_schema_and_parent", r13o_ok, r13o_detail or "ok")

        # 9 no provisional pre-C0 authority
        prov_ok = True
        try:
            r13o = json.loads(self.r13o.read_text(encoding="utf-8"))
            if not r13o.get("provisional_pre_c0_authority_forbidden", False):
                prov_ok = False
            for e in manifest.get("entries") or []:
                rel = (e.get("path") or "").lower()
                role = (e.get("role") or "").lower()
                if "provisional" in rel or "r00_pre_gate" in rel \
                        or "provisional" in role:
                    prov_ok = False
        except Exception:
            prov_ok = False
        self._add("no_provisional_prec0_authority", prov_ok)

        return self._result()

    def _result(self) -> C0RFreezeResult:
        ok = all(c.ok for c in self.checks)
        failed = [c.name for c in self.checks if not c.ok]
        self.checks.append(FreezeCheck(
            "overall",
            ok,
            "all checks passed" if ok else "; ".join(failed)))
        return C0RFreezeResult(
            verdict=VERDICT_OK if ok else VERDICT_BAD,
            checks=self.checks,
        )


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--tag", required=True,
                    help="annotated freeze tag, e.g. c0r_freeze_20260809_01")
    ap.add_argument("--repo", default=".", help="repository root (default: cwd)")
    ap.add_argument("--branch", default=FREEZE_BRANCH)
    ap.add_argument("--r13-path", default=None)
    ap.add_argument("--r13o-path", default=None)
    ap.add_argument("--r13p-path", default=None)
    ap.add_argument("--r13r-path", default=None)
    args = ap.parse_args(argv)

    verifier = C0RTagFreezeVerifier(
        repo=Path(args.repo),
        tag=args.tag,
        branch=args.branch,
        r13_path=Path(args.r13_path) if args.r13_path else None,
        r13o_path=Path(args.r13o_path) if args.r13o_path else None,
        r13p_path=Path(args.r13p_path) if args.r13p_path else None,
        r13r_path=Path(args.r13r_path) if args.r13r_path else None,
    )
    result = verifier.verify()
    print(json.dumps(result.to_dict(), indent=2, sort_keys=True))
    return 0 if result.verdict == VERDICT_OK else 1


if __name__ == "__main__":
    raise SystemExit(main())