# CODEX A7 (MED) — Domain-adaptation methods: characterize CORAL + resolve the MMD naming

Repo: C:/Users/admin/PycharmProjects/gpt4/pythonProject3/carla_-main
Branch: fix/post-audit-phase-e-junctions-roundabouts-20260803 · Interp: ./.venv/Scripts/python.exe · UP_DISABLE_CARLA=1
Rules: TDD; full-suite green; **EXPLICIT-PATHSPEC commit** (`git commit -m "..." -- <files>`). Model: Codex 5.x mid.

## Problem
`ultimate_pipeline/domain_gap/adaptation/{coral,mmd}.py` produce the "how much can adaptation close the sim->real
gap" numbers — a core research question. But:
- **CORAL** (`apply_coral`) is a *correct* whitening->recoloring alignment (`Cs^(-1/2)·Ct^(1/2)`, eps-regularized)
  but is **UNTESTED**.
- **MMD** (`apply_mmd`) only matches **means** (first moment); its own docstring says "MMD-inspired baseline".
  It is **NOT true kernel-MMD** and is **UNTESTED**. Reporting it as "MMD" in the thesis is a claim-accuracy risk.

## Steps
1. Characterize CORAL (deterministic synthetic Gaussians):
   - identical source==target -> `Xs_coral ≈ Xs` (near no-op);
   - after alignment, `cov(Xs_coral) ≈ cov(Xt)` within tolerance (the covariance-matching property);
   - output shapes preserved; singular covariance handled via eps (no crash/NaN).
2. MMD DECISION — **ESCALATE_TO_CLAUDE** with both options; ship the chosen one (default (a) if no advisor call):
   (a) rename `apply_mmd` -> `apply_mean_matching` everywhere (code + any report/label) so nothing can claim "MMD"; OR
   (b) implement true RBF-kernel MMD (unbiased estimator, median-heuristic bandwidth), keep the name.
   Characterize whichever ships: mean-matching -> means aligned; kernel-MMD -> MMD^2 ≈ 0 for identical samples,
   > 0 for a shifted distribution, and matches a hand-computed value on a tiny fixture.
3. Report the method-vs-name resolution so the thesis text cites the correct method.

## Boundaries
- Do NOT change CORAL math. If the MMD (a)/(b) choice needs an advisor -> ESCALATE and ship (a) as the safe default.
- Deterministic, offline (synthetic feature matrices; no CARLA/dataset).

## Deliverables / verdict
tests/unit/test_domain_adaptation.py + reports/post_audit_hardening/A7_ADAPTATION.md.
Push (explicit pathspec); local==remote; suite green.
Verdict: ADAPTATION_CHARACTERIZED | PARTIAL | BLOCKED_NEEDS_DECISION.
