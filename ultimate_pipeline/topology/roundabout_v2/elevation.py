from __future__ import annotations

import math

def evaluate(record: dict, s: float) -> tuple[float, float]:
    """Evaluate an OpenDRIVE elevation record and its grade at global ``s``."""
    ds = float(s) - float(record["s"])
    a, b, c, d = (float(record[k]) for k in "abcd")
    z = a + b * ds + c * ds * ds + d * ds * ds * ds
    grade = b + 2.0 * c * ds + 3.0 * d * ds * ds
    if not all(math.isfinite(v) for v in (z, grade)):
        raise ValueError("non-finite elevation evaluation")
    return z, grade

def hermite_coefficients(z0: float, grade0: float, z1: float, grade1: float, length: float) -> tuple[float, float, float, float]:
    """Return cubic coefficients satisfying values and grades at both ends."""
    if not math.isfinite(length) or length <= 0:
        raise ValueError("elevation length must be finite and positive")
    if not all(math.isfinite(v) for v in (z0, grade0, z1, grade1)):
        raise ValueError("elevation constraints must be finite")
    a = z0
    b = grade0
    c = (3.0 * (z1 - z0) / length**2) - (2.0 * grade0 + grade1) / length
    d = (2.0 * (z0 - z1) / length**3) + (grade0 + grade1) / length**2
    return a, b, c, d

def validate_records(records: list[dict]) -> None:
    previous = None
    for index, record in enumerate(records):
        try:
            s = float(record["s"])
            values = [float(record[k]) for k in "abcd"]
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"invalid elevation record {index}") from exc
        if not math.isfinite(s) or not all(math.isfinite(v) for v in values):
            raise ValueError(f"non-finite elevation record {index}")
        if previous is not None and s <= previous:
            raise ValueError("elevation record s values must be unique and strictly increasing")
        previous = s
