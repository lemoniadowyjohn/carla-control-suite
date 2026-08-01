# enrichment/street_furniture_rules.py
# Optional helper for RealismModule

import math

class StreetFurnitureRules:
    """
    Central rule definitions for street furniture placement.
    """

    # Lamp post spacing and lateral offset
    LAMP_SPACING = 40.0     # meters
    LAMP_OFFSET = 5.0       # meters from road center

    # Trash bins near sidewalks
    TRASH_EVERY = 200.0     # meters

    # Benches only on low-speed, residential areas
    BENCH_ALLOWED_SPEEDS = (20, 30, 40)
    BENCH_INTERVAL = 150.0

    # Guardrails on sharp curves
    MAX_CURVATURE_FOR_GUARDRAIL = 0.02   # 1/R threshold

    @staticmethod
    def is_residential(speed):
        return speed in StreetFurnitureRules.BENCH_ALLOWED_SPEEDS

    @staticmethod
    def needs_guardrail(curvature: float) -> bool:
        return abs(curvature) > StreetFurnitureRules.MAX_CURVATURE_FOR_GUARDRAIL
