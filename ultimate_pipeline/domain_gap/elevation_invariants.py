from __future__ import annotations

EPS = 1e-6


def check_strict_monotonic_s(segments: list, s_tol: float = EPS) -> list[str]:
    errors: list[str] = []
    for i in range(1, len(segments)):
        if segments[i].s_start < segments[i - 1].s_end - s_tol:
            errors.append(
                f"s non-monotonic at index {i}: "
                f"segment {i-1} ends at {segments[i-1].s_end}, "
                f"segment {i} starts at {segments[i].s_start}"
            )
    return errors


def check_smooth_height(segments: list, height_tol: float = 1e-4) -> list[str]:
    errors: list[str] = []
    for i in range(1, len(segments)):
        gap = abs(segments[i].height_start - segments[i - 1].height_end)
        if gap > height_tol:
            errors.append(
                f"Height discontinuity at index {i}: "
                f"segment {i-1} ends at {segments[i-1].height_end}, "
                f"segment {i} starts at {segments[i].height_start}, gap={gap}"
            )
    return errors


def check_non_decreasing_s(segments: list, s_eps: float = EPS) -> list[str]:
    errors: list[str] = []
    for i in range(1, len(segments)):
        if segments[i].s_start + s_eps < segments[i - 1].s_start:
            errors.append(
                f"s regressed at index {i}: "
                f"segment {i-1} s_start={segments[i-1].s_start}, "
                f"segment {i} s_start={segments[i].s_start}"
            )
    return errors


def check_total_length(segments: list, road_length: float, tol: float = 1e-3) -> list[str]:
    errors: list[str] = []
    total = sum(s.s_end - s.s_start for s in segments)
    if abs(total - road_length) > tol:
        errors.append(
            f"Total elevation length {total} "
            f"does not match road length {road_length} (diff={abs(total - road_length)})"
        )
    return errors
