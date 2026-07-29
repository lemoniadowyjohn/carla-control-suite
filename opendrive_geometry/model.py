from __future__ import annotations
import math
from dataclasses import dataclass
from typing import Sequence


@dataclass(frozen=True)
class Vec2:
    x: float
    y: float

    def __add__(self, other: Vec2) -> Vec2:
        return Vec2(self.x + other.x, self.y + other.y)

    def __sub__(self, other: Vec2) -> Vec2:
        return Vec2(self.x - other.x, self.y - other.y)

    def __mul__(self, scalar: float) -> Vec2:
        return Vec2(self.x * scalar, self.y * scalar)

    def __rmul__(self, scalar: float) -> Vec2:
        return Vec2(self.x * scalar, self.y * scalar)

    def rotated(self, angle: float) -> Vec2:
        c = math.cos(angle)
        s = math.sin(angle)
        return Vec2(self.x * c - self.y * s, self.x * s + self.y * c)

    def normalized(self) -> Vec2:
        n = self.length()
        if n < 1e-15:
            return Vec2(1.0, 0.0)
        return Vec2(self.x / n, self.y / n)

    def dot(self, other: Vec2) -> float:
        return self.x * other.x + self.y * other.y

    def cross(self, other: Vec2) -> float:
        return self.x * other.y - self.y * other.x

    def length(self) -> float:
        return math.hypot(self.x, self.y)

    def __repr__(self) -> str:
        return f"Vec2({self.x:.9g}, {self.y:.9g})"


@dataclass(frozen=True)
class Pose2D:
    x: float
    y: float
    hdg: float

    def position(self) -> Vec2:
        return Vec2(self.x, self.y)

    def direction(self) -> Vec2:
        return Vec2(math.cos(self.hdg), math.sin(self.hdg))

    def transformed(self, dx: float = 0.0, dy: float = 0.0, dh: float = 0.0) -> Pose2D:
        return Pose2D(
            x=self.x + dx * math.cos(self.hdg) - dy * math.sin(self.hdg),
            y=self.y + dx * math.sin(self.hdg) + dy * math.cos(self.hdg),
            hdg=self.hdg + dh,
        )

    def __repr__(self) -> str:
        return f"Pose2D({self.x:.9g}, {self.y:.9g}, {self.hdg:.9g})"


@dataclass(frozen=True)
class Bounds2D:
    x_min: float
    x_max: float
    y_min: float
    y_max: float

    def contains(self, point: Vec2) -> bool:
        return self.x_min <= point.x <= self.x_max and self.y_min <= point.y <= self.y_max

    def expanded(self, margin: float) -> Bounds2D:
        return Bounds2D(
            x_min=self.x_min - margin,
            x_max=self.x_max + margin,
            y_min=self.y_min - margin,
            y_max=self.y_max + margin,
        )

    @staticmethod
    def from_points(points: Sequence[Vec2]) -> Bounds2D:
        x_min = min(p.x for p in points)
        x_max = max(p.x for p in points)
        y_min = min(p.y for p in points)
        y_max = max(p.y for p in points)
        return Bounds2D(x_min=x_min, x_max=x_max, y_min=y_min, y_max=y_max)


@dataclass(frozen=True)
class ProjectionResult:
    s: float
    pose: Pose2D
    lateral_offset: float
    distance: float


@dataclass(frozen=True)
class GeometrySegment:
    s0: float
    length: float
    x0: float
    y0: float
    hdg0: float
    geometry_type: str

    @property
    def start(self) -> Pose2D:
        return Pose2D(self.x0, self.y0, self.hdg0)

    @property
    def end_s(self) -> float:
        return self.s0 + self.length
