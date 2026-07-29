class UnsupportedGeometryError(ValueError):
    def __init__(self, geometry_type: str):
        super().__init__(f"Unsupported geometry type: {geometry_type}")
        self.geometry_type = geometry_type


class GeometryOutOfRangeError(ValueError):
    def __init__(self, s: float, s0: float, length: float):
        super().__init__(f"s={s:.9g} out of range [{s0:.9g}, {s0 + length:.9g}]")
        self.s = s
        self.s0 = s0
        self.length = length


class ParamPoly3Error(ValueError):
    """Base class for invalid ParamPoly3 records and evaluations."""


class MissingPRangeError(ParamPoly3Error):
    def __init__(self):
        super().__init__("paramPoly3 pRange is required")


class UnsupportedPRangeError(ParamPoly3Error):
    def __init__(self, p_range: object):
        super().__init__(f"unsupported paramPoly3 pRange: {p_range!r}")
        self.p_range = p_range


class InvalidParamPoly3LengthError(ParamPoly3Error):
    def __init__(self, length: float):
        super().__init__(f"paramPoly3 length must be finite and positive, got {length!r}")
        self.length = length


class NonFiniteCoefficientError(ParamPoly3Error):
    def __init__(self, name: str, value: float):
        super().__init__(f"paramPoly3 coefficient {name} must be finite, got {value!r}")
        self.name = name
        self.value = value


class DegenerateTangentError(ParamPoly3Error):
    def __init__(self, s: float):
        super().__init__(f"paramPoly3 tangent is degenerate at s={s:.9g}")
        self.s = s


class InvalidEvaluationRangeError(GeometryOutOfRangeError):
    """Typed ParamPoly3 failure for a nonfinite or out-of-domain s value."""
