"""Сканы: компактное представление (профили забоя, карты отклонений стенок камеры),
генерация с заданными отклонениями (эмулятор) и получение из облака точек (импорт LAS/E57/PLY/XYZ)."""
from __future__ import annotations

import math

import numpy as np
from shapely.geometry import Polygon

from .geometry import direction_at, point_at, section_polygon

N_RAYS = 72

# ---------------- проходка ----------------
DEV_EFFECTS = {
    # сценарий → как он искажает выработку (переборы по сторонам, «стаканы», подвигание)
    "drill_deviation": {"uniform": 0.10, "noise": 0.12, "advance": -0.08, "half_cast": -0.25},
    "short_holes": {"advance": -0.15, "uniform": 0.02},
    "water": {"advance": -0.12, "noise": 0.05, "misfires": 0.08},
    "fracturing": {"uniform": 0.14, "noise": 0.10, "half_cast": -0.35},
    "blocky_collapse": {"collapse": 0.9, "uniform": 0.03},
    "cleavage": {"side": 0.45, "steps": 0.25},
    "missing_contour": {"uniform": 0.12, "noise": 0.06, "half_cast": -0.55},
    "overcharge": {"uniform": 0.11, "half_cast": -0.2},
}
STRENGTH = {"weak": 0.5, "medium": 1.0, "strong": 1.6}


def _rays(poly: Polygon, n: int = N_RAYS) -> tuple[np.ndarray, np.ndarray, tuple[float, float]]:
    """Радиусы контура по лучам из центра сечения."""
    c = poly.centroid
    ang = np.linspace(0, 2 * math.pi, n, endpoint=False)
    rad = np.zeros(n)
    ext = poly.exterior
    from shapely.geometry import LineString

    for i, a in enumerate(ang):
        far = LineString([(c.x, c.y), (c.x + 50 * math.cos(a), c.y + 50 * math.sin(a))])
        inter = far.intersection(ext)
        pts = [inter] if inter.geom_type == "Point" else list(getattr(inter, "geoms", []))
        rad[i] = min((math.hypot(p.x - c.x, p.y - c.y) for p in pts), default=0)
    return ang, rad, (c.x, c.y)


def gen_dev_scan(section: dict, design_advance: float, scenarios: dict[str, str], rng: np.random.Generator,
                 n_profiles: int = 5, contour_holes: int = 20, chainage0: float = 0.0) -> dict:
    """Скан участка после цикла: профили сечения с переборами по заданным сценариям."""
    poly = section_polygon(section)
    ang, rad, (cx, cy) = _rays(poly)
    uniform, noise, side, steps, collapse = 0.04, 0.035, 0.0, 0.0, 0.0
    adv_k, half_k = 1.0, 0.85
    for name, strength in (scenarios or {}).items():
        e = DEV_EFFECTS.get(name)
        if not e:
            continue
        k = STRENGTH.get(strength, 1.0)
        uniform += e.get("uniform", 0) * k
        noise += e.get("noise", 0) * k
        side += e.get("side", 0) * k
        steps += e.get("steps", 0) * k
        collapse = max(collapse, e.get("collapse", 0) * k)
        adv_k += e.get("advance", 0) * k
        half_k += e.get("half_cast", 0) * k
    advance = max(0.5, design_advance * min(1.02, adv_k) * (1 + rng.normal(0, 0.015)))
    profiles = []
    floor_mask = np.sin(ang) < -0.75  # почва — без перебора
    for i in range(n_profiles):
        ch = chainage0 + advance * (i + 0.5) / n_profiles
        over = uniform + rng.normal(0, noise, len(ang)).clip(-0.05, None)
        over = np.convolve(np.r_[over[-3:], over, over[:3]], np.ones(5) / 5, mode="same")[3:-3]
        over += side * np.clip(np.cos(ang), 0, None) * 1.2           # одна сторона (кливаж)
        over += steps * (np.floor(ang / (math.pi / 6)) % 2) * np.clip(np.cos(ang), 0, None)
        if collapse:
            centre = math.pi / 2 + rng.normal(0, 0.3)
            over += collapse * np.exp(-((ang - centre) ** 2) / 0.12) * (1.0 if i in (1, 2, 3) else 0.4)
        over[floor_mask] = 0.0
        r = rad + np.maximum(over, -0.08)
        pts = [[round(cx + r[j] * math.cos(a), 3), round(cy + r[j] * math.sin(a), 3)] for j, a in enumerate(ang)]
        profiles.append({"ch": round(ch, 2), "polygon": pts})
    hc = int(round(max(0.0, min(1.0, half_k + rng.normal(0, 0.04))) * contour_holes))
    return {"kind": "face", "advance": round(advance, 3), "profiles": profiles, "half_casts_visible": hc,
            "contour_holes": contour_holes, "chainage_from": chainage0, "chainage_to": round(chainage0 + advance, 2)}


def profiles_from_points(points: np.ndarray, axis: list, ch_from: float, ch_to: float,
                         step: float = 0.5, slab: float = 0.25) -> list[dict]:
    """Облако точек выработки → профили: срезы перпендикулярно оси, контур по максимуму радиуса в секторах."""
    out = []
    for ch in np.arange(ch_from + step / 2, ch_to, step):
        o = np.array(point_at(axis, ch))
        d = np.array(direction_at(axis, ch))
        side = np.array([d[1], -d[0], 0.0])
        side /= np.linalg.norm(side) or 1
        rel = points - o
        along = rel @ d
        sl = rel[np.abs(along) < slab]
        if len(sl) < 30:
            continue
        u, v = sl @ side, sl[:, 2] - 0.0
        cx, cy = np.median(u), np.median(v)
        a = np.arctan2(v - cy, u - cx) % (2 * math.pi)
        r = np.hypot(u - cx, v - cy)
        bins = (a / (2 * math.pi) * N_RAYS).astype(int)
        poly = []
        for b in range(N_RAYS):
            m = bins == b
            if m.any():
                k = np.argmax(r[m])
                poly.append([float(u[m][k]), float(v[m][k])])
        if len(poly) >= 8:
            out.append({"ch": round(float(ch), 2), "polygon": poly})
    return out


def dev_scan_to_points(scan: dict, axis: list, density: int = 3) -> np.ndarray:
    """Профили → облако точек (для выгрузки XYZ демо-рудника и проверки импорта)."""
    pts = []
    for p in scan["profiles"]:
        o = np.array(point_at(axis, p["ch"]))
        d = np.array(direction_at(axis, p["ch"]))
        side = np.array([d[1], -d[0], 0.0])
        side /= np.linalg.norm(side) or 1
        for k in range(density):
            off = (k - density / 2) * 0.1
            for (u, v) in p["polygon"]:
                pts.append(o + side * u + np.array([0, 0, v]) + d * off)
    return np.asarray(pts)


# ---------------- очистная камера (CMS) ----------------
STOPE_EFFECTS = {
    "ring_deviation": {"hw": 0.55, "fw": 0.25, "underbreak": 0.35},
    "overcharge": {"hw": 0.6, "fw": 0.45, "roof": 0.3},
    "undercharge": {"underbreak": 0.9},
    "blocked_holes": {"underbreak": 0.8, "brow": 0.6},
    "weak_hw": {"hw": 1.3},
    "delay_errors": {"hw": 0.35, "fw": 0.35, "underbreak": 0.4},
}
WALLS = ("hw", "fw", "roof", "north", "south")


def gen_cms(stope: dict, scenarios: dict[str, str], rng: np.random.Generator, cell: float = 1.0) -> dict:
    g = stope["geometry"]
    H = stope["level_top"] - stope["level_bottom"]
    W = g["y1"] - g["y0"]
    Lx = g["x_hw"] - g["x_fw"]
    eff = {w: 0.15 for w in WALLS}
    eff["roof"] = 0.12
    under = 0.0
    brow = 0.0
    for name, strength in (scenarios or {}).items():
        e = STOPE_EFFECTS.get(name)
        if not e:
            continue
        k = STRENGTH.get(strength, 1.0)
        for w in WALLS:
            eff[w] += e.get(w, 0) * k
        under += e.get("underbreak", 0) * k
        brow += e.get("brow", 0) * k
    walls = {}
    dims = {"hw": (W, H), "fw": (W, H), "north": (Lx, H), "south": (Lx, H), "roof": (W, Lx)}
    for w, (a, b) in dims.items():
        na, nb = max(2, int(a / cell)), max(2, int(b / cell))
        base = rng.gamma(2.0, eff[w] / 2.0, (nb, na))
        if w in ("hw", "fw"):
            base *= np.linspace(1.3, 0.8, nb)[:, None]  # больше у кровли
        walls[w] = {"cell": cell, "rows": nb, "cols": na, "area": round(a * b, 1),
                    "depth": np.round(base, 2).tolist()}
    zones = []
    if under > 0:
        n_z = 1 + int(under * 2)
        for _ in range(n_z):
            vol = float(rng.uniform(80, 220) * under)
            zones.append({"u": round(float(rng.uniform(g["y0"] + 2, g["y1"] - 2)), 2),
                          "v": round(stope["level_bottom"] + float(rng.uniform(H * 0.4, H * 0.9)), 2),
                          "x": round(float(rng.uniform(g["x_fw"] + 1, g["x_hw"] - 1)), 2),
                          "volume_m3": round(vol, 1), "type": "brow" if brow and rng.random() < 0.5 else "rib"})
    return {"kind": "cms", "walls": walls, "underbreak_zones": zones}


def cms_from_points(points: np.ndarray, stope: dict, cell: float = 1.0) -> dict:
    """Облако CMS → карты отклонений стенок: точка относится к ближайшей проектной стенке."""
    g = stope["geometry"]
    zb, zt = stope["level_bottom"], stope["level_top"]
    planes = {"fw": (0, g["x_fw"], -1), "hw": (0, g["x_hw"], 1), "south": (1, g["y0"], -1),
              "north": (1, g["y1"], 1), "roof": (2, zt, 1)}
    x, y, z = points[:, 0], points[:, 1], points[:, 2]
    dist = {w: (points[:, ax] - val) * sgn for w, (ax, val, sgn) in planes.items()}
    names = list(planes)
    D = np.vstack([np.abs(dist[w]) for w in names])
    nearest = np.argmin(D, axis=0)
    walls = {}
    dims = {"hw": (g["y1"] - g["y0"], zt - zb), "fw": (g["y1"] - g["y0"], zt - zb),
            "north": (g["x_hw"] - g["x_fw"], zt - zb), "south": (g["x_hw"] - g["x_fw"], zt - zb),
            "roof": (g["y1"] - g["y0"], g["x_hw"] - g["x_fw"])}
    for i, w in enumerate(names):
        a, b = dims[w]
        na, nb = max(2, int(a / cell)), max(2, int(b / cell))
        grid = np.zeros((nb, na))
        m = nearest == i
        if w in ("hw", "fw"):
            ua, vb = (y[m] - g["y0"]) / cell, (z[m] - zb) / cell
        elif w in ("north", "south"):
            ua, vb = (x[m] - g["x_fw"]) / cell, (z[m] - zb) / cell
        else:
            ua, vb = (y[m] - g["y0"]) / cell, (x[m] - g["x_fw"]) / cell
        ia, ib = np.clip(ua.astype(int), 0, na - 1), np.clip(vb.astype(int), 0, nb - 1)
        dd = dist[w][m]
        np.maximum.at(grid, (ib, ia), dd)
        walls[w] = {"cell": cell, "rows": nb, "cols": na, "area": round(a * b, 1), "depth": np.round(grid, 2).tolist()}
    return {"kind": "cms", "walls": walls, "underbreak_zones": []}


def cms_to_points(cms: dict, stope: dict) -> np.ndarray:
    g = stope["geometry"]
    zb, zt = stope["level_bottom"], stope["level_top"]
    pts = []
    for w, data in cms["walls"].items():
        c = data["cell"]
        for i, row in enumerate(data["depth"]):
            for j, dpt in enumerate(row):
                a, b = (j + 0.5) * c, (i + 0.5) * c
                if w == "fw":
                    pts.append([g["x_fw"] - dpt, g["y0"] + a, zb + b])
                elif w == "hw":
                    pts.append([g["x_hw"] + dpt, g["y0"] + a, zb + b])
                elif w == "south":
                    pts.append([g["x_fw"] + a, g["y0"] - dpt, zb + b])
                elif w == "north":
                    pts.append([g["x_fw"] + a, g["y1"] + dpt, zb + b])
                else:
                    pts.append([g["x_fw"] + b, g["y0"] + a, zt + dpt])
    return np.asarray(pts)
