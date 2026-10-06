"""Геометрия: оси выработок (полилинии x,y,z), пикеты, сечения."""
from __future__ import annotations

import math
from typing import Iterable, Sequence

import numpy as np
from shapely.geometry import Polygon

Point = Sequence[float]

SECTION_SHAPES = ("arch", "rect", "trapezoid", "horseshoe", "custom")


# ---------------- оси ----------------
def seg_lengths(axis: Sequence[Point]) -> np.ndarray:
    a = np.asarray(axis, dtype=float)
    if len(a) < 2:
        return np.zeros(0)
    return np.linalg.norm(np.diff(a, axis=0), axis=1)


def axis_length(axis: Sequence[Point]) -> float:
    return float(seg_lengths(axis).sum())


def point_at(axis: Sequence[Point], chainage: float) -> list[float]:
    """Точка оси на расстоянии chainage от начала (пикет)."""
    a = np.asarray(axis, dtype=float)
    lens = seg_lengths(axis)
    if chainage <= 0 or len(a) < 2:
        return a[0].tolist()
    acc = 0.0
    for i, L in enumerate(lens):
        if acc + L >= chainage:
            t = (chainage - acc) / L if L else 0
            return (a[i] + t * (a[i + 1] - a[i])).tolist()
        acc += L
    return a[-1].tolist()


def direction_at(axis: Sequence[Point], chainage: float) -> list[float]:
    a = np.asarray(axis, dtype=float)
    lens = seg_lengths(axis)
    acc = 0.0
    for i, L in enumerate(lens):
        if acc + L >= chainage or i == len(lens) - 1:
            d = a[i + 1] - a[i]
            n = np.linalg.norm(d)
            return (d / n).tolist() if n else [1.0, 0.0, 0.0]
        acc += L
    return [1.0, 0.0, 0.0]


def chainage_of(axis: Sequence[Point], p: Point) -> tuple[float, float]:
    """Ближайший пикет к точке p и расстояние до оси."""
    a = np.asarray(axis, dtype=float)
    p = np.asarray(p, dtype=float)
    best = (0.0, float("inf"))
    acc = 0.0
    for i in range(len(a) - 1):
        d = a[i + 1] - a[i]
        L2 = float(d @ d)
        t = 0.0 if L2 == 0 else max(0.0, min(1.0, float((p - a[i]) @ d) / L2))
        q = a[i] + t * d
        dist = float(np.linalg.norm(p - q))
        if dist < best[1]:
            best = (acc + t * math.sqrt(L2), dist)
        acc += math.sqrt(L2)
    return best


def point_at_elevation(axis: Sequence[Point], z: float) -> tuple[list[float], float] | None:
    """Первая точка оси на отметке z (для примыкания к автоуклону) и её пикет."""
    a = np.asarray(axis, dtype=float)
    acc = 0.0
    for i in range(len(a) - 1):
        z0, z1 = a[i][2], a[i + 1][2]
        L = float(np.linalg.norm(a[i + 1] - a[i]))
        if (z0 - z) * (z1 - z) <= 0 and z0 != z1:
            t = (z - z0) / (z1 - z0)
            return (a[i] + t * (a[i + 1] - a[i])).tolist(), acc + t * L
        acc += L
    return None


def by_azimuth(start: Point, azimuth_deg: float, length: float, gradient: float = 0.0) -> list[list[float]]:
    """Ось по азимуту (от севера по часовой), длине и уклону (‰ или доля: -0.143 = 1:7 вниз)."""
    az = math.radians(azimuth_deg)
    horiz = length / math.sqrt(1 + gradient**2)
    dx, dy = horiz * math.sin(az), horiz * math.cos(az)
    dz = horiz * gradient
    return [list(map(float, start)), [start[0] + dx, start[1] + dy, start[2] + dz]]


def azimuth(p0: Point, p1: Point) -> float:
    return (math.degrees(math.atan2(p1[0] - p0[0], p1[1] - p0[1])) + 360) % 360


def format_chainage(m: float) -> str:
    """ПК 12+40 = 1240 м."""
    m = max(0.0, m)
    return f"ПК {int(m // 100)}+{int(round(m % 100)):02d}"


def resample(axis: Sequence[Point], step: float) -> list[list[float]]:
    L = axis_length(axis)
    n = max(2, int(math.ceil(L / step)) + 1)
    return [point_at(axis, L * i / (n - 1)) for i in range(n)]


# ---------------- сечения ----------------
def section_polygon(section: dict, n_arc: int = 24) -> Polygon:
    """Контур сечения в координатах забоя: x — поперёк (0 по оси), y — вверх от почвы."""
    shape = section.get("shape", "arch")
    w = float(section.get("width", 5.0))
    h = float(section.get("height", 5.0))
    if shape == "custom" and section.get("contour"):
        return Polygon(section["contour"])
    if shape == "rect":
        pts = [(-w / 2, 0), (w / 2, 0), (w / 2, h), (-w / 2, h)]
    elif shape == "trapezoid":
        top = float(section.get("top_width", w * 0.8))
        pts = [(-w / 2, 0), (w / 2, 0), (top / 2, h), (-top / 2, h)]
    elif shape == "horseshoe":
        r = w / 2
        wall = max(h - r, 0.1)
        pts = [(-w / 2 * 0.9, 0), (w / 2 * 0.9, 0), (w / 2, wall * 0.3), (w / 2, wall)]
        for i in range(1, n_arc):
            t = math.pi * i / n_arc
            pts.append((r * math.cos(t), wall + r * math.sin(t)))
        pts += [(-w / 2, wall), (-w / 2, wall * 0.3)]
    else:  # arch — прямые стенки + сводчатая кровля (высота свода f)
        f = float(section.get("arch_height", w / 4))
        wall = max(h - f, 0.1)
        pts = [(-w / 2, 0), (w / 2, 0), (w / 2, wall)]
        # дуга окружности через (±w/2, wall) и (0, h)
        R = (f**2 + (w / 2) ** 2) / (2 * f)
        cy = h - R
        a0 = math.atan2(wall - cy, w / 2)
        for i in range(1, n_arc):
            t = a0 + (math.pi - 2 * a0) * i / n_arc
            pts.append((R * math.cos(t), cy + R * math.sin(t)))
        pts.append((-w / 2, wall))
    return Polygon(pts)


def section_area(section: dict) -> float:
    return float(section_polygon(section).area)


def section_info(section: dict) -> dict:
    poly = section_polygon(section)
    minx, miny, maxx, maxy = poly.bounds
    return {**section, "area": round(poly.area, 2), "perimeter": round(poly.length, 2),
            "width": round(maxx - minx, 2), "height": round(maxy - miny, 2)}


def tube_mesh(axis: Sequence[Point], section: dict, n_pts: int = 12) -> dict:
    """Упрощённый 3D-каркас выработки: сечение, протянутое вдоль оси (для three.js / DXF)."""
    poly = section_polygon(section, n_arc=6)
    ring = list(poly.exterior.coords)[:-1]
    if len(ring) > n_pts:
        idx = np.linspace(0, len(ring) - 1, n_pts).astype(int)
        ring = [ring[i] for i in idx]
    a = np.asarray(axis, dtype=float)
    verts: list[list[float]] = []
    faces: list[list[int]] = []
    m = len(ring)
    for i, p in enumerate(a):
        if i < len(a) - 1:
            d = a[i + 1] - p
        else:
            d = p - a[i - 1]
        d = d / (np.linalg.norm(d) or 1)
        side = np.array([d[1], -d[0], 0.0])
        if np.linalg.norm(side) < 1e-6:
            side = np.array([1.0, 0, 0])
        side /= np.linalg.norm(side)
        up = np.array([0, 0, 1.0])
        for (sx, sy) in ring:
            verts.append((p + side * sx + up * sy).round(3).tolist())
    for i in range(len(a) - 1):
        for j in range(m):
            k0, k1 = i * m + j, i * m + (j + 1) % m
            n0, n1 = k0 + m, k1 + m
            faces.append([k0, k1, n1])
            faces.append([k0, n1, n0])
    return {"vertices": verts, "faces": faces}


def bbox(points: Iterable[Point]) -> dict:
    a = np.asarray(list(points), dtype=float)
    return {"min": a.min(axis=0).round(2).tolist(), "max": a.max(axis=0).round(2).tolist()}
