# A7 Adaptation Characterization

Date: 2026-08-15

## Verdict

`ADAPTATION_CHARACTERIZED_GREEN`

CORAL is now characterized without changing its math. The method previously exposed as `apply_mmd` in adaptation alignment code is now explicitly named `apply_mean_matching`, with `apply_mmd` retained only as a deprecated compatibility alias. This removes the false implication that the alignment transform is true kernel MMD.

## Method Naming

- `apply_mean_matching`: shifts source feature means to match target feature means.
- `apply_mmd`: deprecated alias for `apply_mean_matching`.
- `mmd_loss`: true RBF-kernel MMD metric in `ultimate_pipeline/experiments/thesis/core_algorithms.py`.

## Additional Fix

`DomainAdaptation` was passing the tuple returned by `apply_coral` into `_eval`. It now destructures `(Xs_coral, Xt_coral)` and evaluates the transformed source against the returned target. `sklearn` imports were also moved into `_eval` so the module remains importable in offline environments without sklearn.

## Tests

Targeted red:

```text
ModuleNotFoundError: No module named 'sklearn' during adaptation_runner import
```

Targeted green:

```text
tests/unit/test_domain_adaptation.py .......                             [100%]
7 passed, 4 warnings in 7.75s
```

Full suite:

```text
739 passed, 49 warnings in 164.64s (0:02:44)
```

## ESCALATE_TO_CLAUDE

- Thesis text/results must cite this alignment method as mean matching unless using `mmd_loss`, which is the true RBF-kernel MMD metric.
