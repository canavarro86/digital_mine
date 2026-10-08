"""Паспорт БВР на проходку.

Удельный расход — методика Покровского; раскладка вруба, отбойных, контурных и подошвенных шпуров —
методика Холмберга (Holmberg, 1982) на основе формул Лангефорса. Формулы и источники — README, раздел «Методики расчетов».
Координаты забоя: x — поперек выработки (0 — ось), y — вверх от почвы, м.
"""
from __future__ import annotations

import math
from typing import Any

import numpy as np
from shapely.geometry import LineString, Point, Polygon
from shapely.ops import unary_union

from . import explosives as ex
from .geometry import section_polygon

STRUCTURE_COEF = {1: 1.1, 2: 1.2, 3: 1.4, 4: 1.6, 5: 2.0}
E_REF_RWS = 105.0  # аммонит 6ЖВ ≈ 105 % АНФО (эталон Покровского, e = 1)
HOLE_TYPES = ("empty", "cut", "stoping", "helper", "contour", "lifter")
TYPE_ORDER = {"empty": 0, "cut": 1, "stoping": 2, "helper": 3, "contour": 4, "lifter": 5}


# ---------------- Покровский ----------------
def pokrovsky(f: float, fracture_cat: int, area: float, rws: float, hole_d_mm: float = 45.0) -> dict:
    q1 = 0.1 * f                                     # нормальный удельный расход, кг/м³
    fs = STRUCTURE_COEF.get(int(fracture_cat), 1.4)  # коэффициент структуры
    v = 6.5 / math.sqrt(max(area, 1.0))              # коэффициент зажима (одна плоскость обнажения)
    e = E_REF_RWS / max(rws, 1.0)                    # коэффициент работоспособности ВВ
    kd = (36.0 / hole_d_mm) ** 0.3 if hole_d_mm > 0 else 1.0  # поправка на диаметр (36 мм — эталон)
    q = q1 * fs * v * e * kd
    return {"q1": round(q1, 3), "fs": fs, "v": round(v, 3), "e": round(e, 3), "kd": round(kd, 3), "q": round(q, 3)}


def holes_pokrovsky(q: float, area: float, density_gcc: float, hole_d_mm: float, kz: float = 0.65) -> int:
    """N = 1,27·q·S / (Δ·d²·kз)."""
    d = hole_d_mm / 1000
    return int(math.ceil(1.27 * q * area / (density_gcc * 1000 * d * d * kz)))


def expected_kish(rock: dict, depth: float, cut_type: str, explosive: dict) -> float:
    k = 0.92
    cat = int(rock.get("fracture_cat", 3))
    if cat >= 4:
        k -= 0.03
    if cat == 5:
        k -= 0.03
    if depth > 4.0:
        k -= 0.02 * (depth - 4.0)
    if cut_type in ("wedge", "pyramid"):
        k -= 0.03
    water = rock.get("water", "dry")
    if water in ("flowing", "inflow") and explosive.get("water_resistance") != "full":
        k -= 0.06
    if float(rock.get("f", 10)) > 15:
        k -= 0.02
    return round(max(0.80, min(0.95, k)), 3)


# ---------------- Холмберг ----------------
def rock_constant(f: float) -> float:
    """c ≈ 0,4 кг/м³ для средней породы; растет с крепостью."""
    return round(0.30 + 0.0125 * f, 3)


def cut_max_advance(phi_m: float) -> float:
    """Глубина вруба, при которой достигается ~95 % подвигания: H = 0,15 + 34,1φ − 39,4φ²."""
    return 0.15 + 34.1 * phi_m - 39.4 * phi_m * phi_m


def burden_holmberg(l_kg_m: float, s: float, c: float, f_fix: float, e_b: float) -> float:
    cbar = c + 0.05
    return 0.9 * math.sqrt(l_kg_m * s / (cbar * f_fix * e_b))


def cut_sections(phi: float, d: float, l_max: float, s: float, c: float, depth: float, max_w: float) -> list[dict]:
    """Секции прямого вруба: ЛНС B, ширина отверстия W, требуемая концентрация заряда l."""
    F = 0.01 * depth + 0.02  # погрешность забуривания и отклонения, м
    secs: list[dict] = []
    a1 = 1.5 * phi
    l1 = 55 * d * (a1 / phi) ** 1.5 * (a1 - phi / 2) * (c / 0.4) / s
    secs.append({"n": 1, "B": round(a1, 3), "W": round(a1 * math.sqrt(2), 3), "l": round(l1, 3)})
    W = a1 * math.sqrt(2)
    for n in range(2, 5):
        B = 8.8e-2 * math.sqrt(W * l_max * s / (d * c))
        B = min(B, 2 * W)
        Bp = max(B - F, 0.1)
        Wn = math.sqrt(2) * (Bp + W / 2)
        if Wn > max_w:
            break
        l_need = 32.3 * d * c * Bp / (math.sin(math.atan(W / (2 * Bp))) ** 1.5 * s)
        secs.append({"n": n, "B": round(Bp, 3), "W": round(Wn, 3), "l": round(min(l_need, l_max), 3)})
        W = Wn
        if W >= math.sqrt(depth * 0.9) * 1.1:
            break
    return secs


def _cut_geometry(cut_type: str, secs: list[dict], n_empty: int, D: float, cy: float) -> tuple[list, list]:
    """Холостые и врубовые шпуры (x, y, секция)."""
    empty: list[tuple[float, float]] = []
    cut: list[tuple[float, float, int]] = []
    if cut_type == "slot":
        n_empty = max(n_empty, 2)
        for i in range(n_empty):
            empty.append(((i - (n_empty - 1) / 2) * D * 1.25, cy))
        half = (n_empty - 1) / 2 * D * 1.25
        for s in secs:
            B = s["B"]
            off = half + B * (0.7 if s["n"] == 1 else 1.0)
            r = (s["W"] / 2) if s["n"] > 1 else B
            cut += [(off + (s["n"] - 1) * 0.2, cy, s["n"]), (-off - (s["n"] - 1) * 0.2, cy, s["n"]),
                    (0, cy + r, s["n"]), (0, cy - r, s["n"])]
    elif cut_type == "spiral":
        empty.append((0.0, cy))
        k = 0
        for s in secs:
            for j in range(4):
                ang = math.radians(90 * k + 30 * s["n"])
                r = s["B"] * (1 + 0.5 * j) if s["n"] == 1 else s["W"] / 2 + 0.15 * j
                cut.append((r * math.cos(ang), cy + r * math.sin(ang), s["n"]))
                k += 1
    elif cut_type in ("wedge", "pyramid"):
        # наклонные врубы без холостых: пары сходящихся шпуров
        rows = [cy - 0.5, cy, cy + 0.5] if cut_type == "wedge" else [cy]
        for yy in rows:
            cut += [(-0.9, yy, 1), (0.9, yy, 1)]
        if cut_type == "pyramid":
            cut += [(0, cy - 0.9, 1), (0, cy + 0.9, 1)]
        cut += [(-1.6, cy, 2), (1.6, cy, 2)]
    else:  # prismatic: квадрат в квадрате с поворотом на 45°
        if n_empty <= 1:
            empty.append((0.0, cy))
        else:
            for i in range(n_empty):
                ang = 2 * math.pi * i / n_empty
                empty.append((D * 0.75 * math.cos(ang), cy + D * 0.75 * math.sin(ang)))
        for s in secs:
            if s["n"] == 1:
                r = s["B"]
                pts = [(r, 0), (0, r), (-r, 0), (0, -r)]
            else:
                r = s["W"] / 2
                rot = math.pi / 4 if s["n"] % 2 == 0 else 0
                pts = [(r * math.cos(rot + k * math.pi / 2) * math.sqrt(2) / (1 if rot else math.sqrt(2)),
                        r * math.sin(rot + k * math.pi / 2) * math.sqrt(2) / (1 if rot else math.sqrt(2)))
                       for k in range(4)]
            cut += [(x, cy + y, s["n"]) for x, y in pts]
    return empty, cut


def _points_along(line: LineString, spacing: float, include_ends: bool = True) -> list[tuple[float, float]]:
    L = line.length
    n = max(1, int(round(L / spacing)))
    ts = [i / n for i in range(n + 1)] if include_ends else [(i + 0.5) / n for i in range(n)]
    return [(p.x, p.y) for p in (line.interpolate(t, normalized=True) for t in ts)]


def design(inp: dict) -> dict:
    """Полный расчет паспорта: раскладка по Холмбергу, согласованная с удельным расходом Покровского.
    Если расход по раскладке < 80 % от Покровского, ЛНС и расстояния уменьшаются (до 3 итераций, не более чем на 35 %)."""
    scale = float(inp.get("burden_scale") or 1.0)
    res = _design(inp, scale)
    if inp.get("burden_scale"):
        return res
    for _ in range(3):
        ind = res["indicators"]
        ratio = ind["q_actual"] / ind["q_pokrovsky"] if ind["q_pokrovsky"] else 1
        if ratio >= 0.8:
            break
        scale = max(0.65, scale * math.sqrt(ratio / 0.9))
        res = _design(inp, scale)
    res["params"]["burden_scale"] = round(scale, 3)
    return res


def _design(inp: dict, scale: float) -> dict:
    sec = inp["section"]
    rock = inp.get("rock") or {}
    expl = inp["explosive"]
    expl_contour = inp.get("contour_explosive") or expl
    depth = float(inp.get("hole_depth", 3.8))
    d_mm = float(inp.get("hole_diameter", 45))
    D_mm = float(inp.get("empty_diameter", 102))
    cut_type = (inp.get("cut") or {}).get("type", "prismatic")
    n_empty = (inp.get("cut") or {}).get("n_empty")
    if not n_empty:  # минимальное число холостых, при котором вруб обеспечивает глубину (Холмберг)
        n_empty = next((n for n in range(1, 5) if cut_max_advance(D_mm / 1000 * math.sqrt(n)) * 0.95 >= depth), 4)
    n_empty = int(n_empty)
    f = float(rock.get("f", 10))
    cat = int(rock.get("fracture_cat", 3))
    gamma = math.radians(float(inp.get("lookout_deg", 3)))
    contour_blasting = inp.get("contour_blasting")
    if contour_blasting is None:
        contour_blasting = cat >= 3 or bool(rock.get("cleavage"))

    poly = section_polygon(sec)
    area = poly.area
    minx, miny, maxx, maxy = poly.bounds
    width, height = maxx - minx, maxy - miny
    d, D = d_mm / 1000, D_mm / 1000
    s = ex.s_anfo(expl)
    c = rock_constant(f)
    l_max = ex.kg_per_m(expl, d_mm)
    l_contour = min(ex.kg_per_m(expl_contour, d_mm), 90 * d * d * 1.5) if contour_blasting else l_max
    warnings: list[dict] = list(ex.check(expl, d_mm, rock.get("water", "dry")))
    if expl_contour is not expl:
        warnings += [w for w in ex.check(expl_contour, d_mm, rock.get("water", "dry")) if w not in warnings]

    pk = pokrovsky(f, cat, area, float(expl.get("rws", 100)), d_mm)
    kish = expected_kish(rock, depth, cut_type, expl)
    advance = depth * kish
    area * advance

    # вруб
    phi = D * math.sqrt(n_empty) if cut_type not in ("wedge", "pyramid") else 0
    H_cut = cut_max_advance(phi) if phi else width * 0.45
    if depth > H_cut * 0.95 + 0.05:
        warnings.append({"level": "warning", "code": "cut_too_deep",
                         "params": {"depth": depth, "max": round(H_cut * 0.95, 2), "n_empty": n_empty}})
    cy = float(inp.get("cut_height") or max(1.2, min(height * 0.42, 2.0)))
    secs = cut_sections(phi or 0.15, d, l_max, s, c, depth, min(width, height) * 0.55) if phi else \
        [{"n": 1, "B": 0.9, "W": 1.8, "l": round(l_max, 3)}, {"n": 2, "B": 0.7, "W": 3.2, "l": round(l_max, 3)}]
    empty_pts, cut_pts = _cut_geometry(cut_type, secs, n_empty, D, cy)
    cut_w = max(sx["W"] for sx in secs)

    # отбойные, контурные, подошвенные
    B_s = burden_holmberg(l_max, s, c, 1.2, 1.25) - (0.01 * depth + 0.02)
    E_s = 1.1 * B_s
    B_l = burden_holmberg(l_max, s, c, 1.45, 1.0) - depth * math.sin(gamma) - (0.01 * depth + 0.02)
    if contour_blasting:
        E_c = 15 * d
        B_c = E_c / 0.8
    else:
        B_c = burden_holmberg(l_max, s, c, 1.2, 1.25) * 0.9
        E_c = 1.25 * B_c
    B_l, B_s, B_c = max(B_l * scale, 0.5), max(B_s * scale, 0.5), max(B_c * scale, 0.4)
    E_s, E_c = E_s * scale, E_c * scale

    holes: list[dict] = []

    def add(x, y, t, **kw):
        holes.append({"x": round(float(x), 3), "y": round(float(y), 3), "type": t, **kw})

    for (x, y) in empty_pts:
        add(x, y, "empty", section=0)
    for (x, y, n) in cut_pts:
        add(x, y, "cut", section=n)

    inset = 0.1  # отступ устья контурного шпура от проектного контура
    # контур без почвы: точки контура выше полосы подошвы
    floor_band = 0.8  # нижний контурный шпур стенки выше угловых подошвенных
    inner_poly = poly.buffer(-inset, join_style=2)
    for seg in _split_contour(inner_poly, miny + floor_band):
        for (x, y) in _points_along(seg, E_c):
            if poly.buffer(-0.05).contains(Point(x, y)):
                add(x, y, "contour")
            else:
                p = _pull_inside(poly, x, y, inset)
                add(p[0], p[1], "contour")
    # подошва
    floor_y = miny + 0.15
    floor_line = LineString([(minx + 0.15, floor_y), (maxx - 0.15, floor_y)])
    n_l = max(3, int(math.ceil(floor_line.length / B_l)) + 1)
    for i in range(n_l):
        x = minx + 0.15 + (maxx - minx - 0.3) * i / (n_l - 1)
        add(x, floor_y, "lifter")
    # вспомогательный (оконтуривающий) ряд
    helper_poly = poly.buffer(-(B_c + inset))
    if not helper_poly.is_empty and helper_poly.geom_type == "Polygon":
        for seg in _split_contour(helper_poly, B_l + 0.2 + miny):
            for (x, y) in _points_along(seg, E_s, include_ends=True):
                add(x, y, "helper")
    # отбойные — сетка внутри
    cut_box = Polygon([(-cut_w / 2 - 0.25, cy - cut_w / 2 - 0.25), (cut_w / 2 + 0.25, cy - cut_w / 2 - 0.25),
                       (cut_w / 2 + 0.25, cy + cut_w / 2 + 0.25), (-cut_w / 2 - 0.25, cy + cut_w / 2 + 0.25)])
    lifter_band = Polygon([(minx - 1, miny - 1), (maxx + 1, miny - 1), (maxx + 1, miny + B_l * 0.85),
                           (minx - 1, miny + B_l * 0.85)])
    region = poly.buffer(-(B_c + inset + B_s * 0.75)).difference(unary_union([cut_box, lifter_band]))
    if not region.is_empty:
        xs = np.arange(-math.floor((width / 2) / E_s) * E_s, width / 2 + 1e-6, E_s)
        ys = np.arange(cy - math.floor((cy - miny) / B_s) * B_s, maxy + 1e-6, B_s)
        for j, y in enumerate(ys):
            for x in xs:
                xx = x + (E_s / 2 if j % 2 else 0)
                if region.contains(Point(xx, y)):
                    add(xx, y, "stoping")
    holes = _dedupe(holes, min_dist=min(0.45, B_c * 0.6), min_inner=0.62 * B_s)

    for i, h in enumerate(holes, start=1):
        h["id"] = i
    result = {
        "input": inp,
        "holes": holes,
        "params": {"area": round(area, 2), "width": round(width, 2), "height": round(height, 2),
                   "perimeter": round(poly.length, 2), "c": c, "s_anfo": round(s, 3),
                   "l_max": round(l_max, 3), "l_contour": round(l_contour, 3), "B_stoping": round(B_s, 3),
                   "E_stoping": round(E_s, 3), "B_lifter": round(B_l, 3), "B_contour": round(B_c, 3),
                   "E_contour": round(E_c, 3), "contour_ratio": round(E_c / B_c, 2), "phi": round(phi, 3),
                   "cut_max_depth": round(H_cut, 2), "cut_sections": secs, "cut_height": round(cy, 2),
                   "contour_blasting": contour_blasting, "pokrovsky": pk, "kish": kish,
                   "lookout_deg": math.degrees(gamma)},
        "contour": [list(map(lambda v: round(v, 3), p)) for p in poly.exterior.coords],
        "warnings": warnings,
    }
    return evaluate(result)


def _split_contour(poly: Polygon, floor_band: float) -> list[LineString]:
    """Часть контура выше полосы подошвы (стенки + кровля) одной линией: обрезка контура полуплоскостью."""
    from shapely.geometry import box
    from shapely.ops import linemerge

    minx, miny, maxx, maxy = poly.bounds
    part = poly.exterior.intersection(box(minx - 1, floor_band, maxx + 1, maxy + 1))
    if part.is_empty:
        return []
    if part.geom_type == "MultiLineString":
        part = linemerge(part)
    lines = [part] if part.geom_type == "LineString" else [g for g in getattr(part, "geoms", []) if g.length > 0.2]
    return lines


def _pull_inside(poly: Polygon, x: float, y: float, d: float) -> tuple[float, float]:
    c = poly.centroid
    vx, vy = c.x - x, c.y - y
    n = math.hypot(vx, vy) or 1
    return x + vx / n * d * 1.5, y + vy / n * d * 1.5


def _dedupe(holes: list[dict], min_dist: float, min_inner: float = 0.0) -> list[dict]:
    out: list[dict] = []
    prio = {"empty": 0, "cut": 1, "lifter": 2, "contour": 3, "helper": 4, "stoping": 5}
    for h in sorted(holes, key=lambda h: prio[h["type"]]):
        md = max(min_dist, min_inner) if h["type"] in ("helper", "stoping") else min_dist
        if h["type"] in ("empty", "cut") or all(math.hypot(h["x"] - o["x"], h["y"] - o["y"]) >= md for o in out):
            out.append(h)
    return out


# ---------------- оценка/пересчет по положению шпуров ----------------
def _nn(holes: list[dict], key=("x", "y")) -> list[float]:
    pts = np.array([[h[key[0]], h[key[1]]] for h in holes]) if holes else np.zeros((0, 2))
    out = []
    for i, p in enumerate(pts):
        d = np.hypot(*(pts - p).T)
        d[i] = np.inf
        out.append(float(d.min()) if len(d) > 1 else 0.0)
    return out


def evaluate(result: dict) -> dict:
    """Пересчитывает длины, заряды, замедления и показатели по текущему положению шпуров (редактор)."""
    inp = result["input"]
    p = result["params"]
    expl = inp["explosive"]
    expl_c = inp.get("contour_explosive") or expl
    depth = float(inp.get("hole_depth", 3.8))
    d_mm = float(inp.get("hole_diameter", 45))
    D_mm = float(inp.get("empty_diameter", 102))
    d = d_mm / 1000
    gamma = math.radians(float(inp.get("lookout_deg", 3)))
    holes = result["holes"]
    poly = Polygon(result["contour"])
    empties = [h for h in holes if h["type"] == "empty"]
    secs = {s["n"]: s for s in p.get("cut_sections", [])}
    for h in holes:
        t = h["type"]
        h.setdefault("diameter", D_mm if t == "empty" else d_mm)
        if t == "empty":
            h.update(length=round(depth + 0.2, 2), angle=0.0, charge_kg=0.0, cartridges=0, stemming=0.0,
                     charge_length=0.0, explosive="")
            continue
        angled = t in ("contour", "lifter")
        if inp.get("cut", {}).get("type") in ("wedge", "pyramid") and t == "cut":
            ang = math.radians(65)
            h["angle"] = round(90 - 65, 1)
            h["length"] = round(depth / math.sin(ang), 2)
        else:
            h["angle"] = round(math.degrees(gamma), 1) if angled else 0.0
            h["length"] = round(depth / math.cos(gamma), 2) if angled else round(depth + (0.1 if t == "cut" else 0), 2)
        stem = 0.5 if t == "contour" else max(10 * d, 0.3)
        if t == "cut":
            sec = secs.get(h.get("section", 1), {})
            l_need = sec.get("l", p["l_max"])
            # проверка по фактическому расстоянию до холостого
            if empties and h.get("section", 1) == 1:
                a = min(math.hypot(h["x"] - e["x"], h["y"] - e["y"]) for e in empties)
                phi = p.get("phi") or D_mm / 1000
                l_need = max(0.2, 55 * d * (a / phi) ** 1.5 * (a - phi / 2) * (p["c"] / 0.4) / p["s_anfo"])
                h["burden_to_empty"] = round(a, 3)
                if a > 1.7 * phi:
                    h["flag"] = "cut_burden_too_large"
            l = min(l_need, p["l_max"])
            stem = max(stem, 0.5)
            e_used = expl
        elif t == "contour":
            l, e_used = p["l_contour"], expl_c
        else:
            l, e_used = p["l_max"], expl
        clen = max(h["length"] - stem, 0)
        if t == "lifter":
            stem = 0.2
            clen = h["length"] - stem
        mass = l * clen
        if e_used.get("type") == "cartridge" and e_used.get("cart_mass") and e_used.get("cart_length"):
            n = int(math.ceil(clen / float(e_used["cart_length"])))
            mass = n * float(e_used["cart_mass"])
            h["cartridges"] = n
        else:
            h["cartridges"] = 0
        h.update(charge_kg=round(mass, 2), charge_length=round(clen, 2), stemming=round(stem, 2),
                 explosive=e_used.get("name", ""), kg_per_m=round(l, 3))
    # локальная ЛНС: расстояние до ближайшего соседа против проектной
    loaded = [h for h in holes if h["type"] != "empty"]
    nn = _nn(loaded)
    target = {"stoping": p["B_stoping"], "helper": p["B_stoping"], "lifter": p["B_lifter"] * 0.9,
              "contour": p["E_contour"], "cut": None}
    for h, dist in zip(loaded, nn):
        h["nn_dist"] = round(dist, 3)
        tgt = target.get(h["type"])
        if tgt:
            r = dist / tgt
            h["burden_ratio"] = round(r, 2)
            if r < 0.6:
                h["flag"] = "too_close"
            elif r > 1.35:
                h["flag"] = "too_far"
            elif h.get("flag") in ("too_close", "too_far"):
                h.pop("flag")
        if not poly.buffer(0.3).contains(Point(h["x"], h["y"])):
            h["flag"] = "outside_contour"
    assign_delays(result)
    result["indicators"] = indicators(result)
    return result


def assign_delays(result: dict, actual: dict | None = None) -> None:
    """Порядок: вруб → отбойные → оконтуривающие → контур → подошва. ЭДД — мс каждого шпура; НСИ — серии."""
    inp = result["input"]
    mode = inp.get("initiation", "edd")
    holes = [h for h in result["holes"] if h["type"] != "empty" and not h.get("not_drilled")]
    cy = result["params"].get("cut_height", 1.5)
    pos = (lambda h: (h.get("toe_x", h["x"]), h.get("toe_y", h["y"]))) if actual else (lambda h: (h["x"], h["y"]))

    def dist(h):
        x, y = pos(h)
        return math.hypot(x, y - cy)

    groups: list[list[dict]] = []
    cut = sorted([h for h in holes if h["type"] == "cut"], key=lambda h: (h.get("section", 1), dist(h)))
    groups += [[h] for h in cut]
    for t in ("stoping", "helper"):
        hs = sorted([h for h in holes if h["type"] == t], key=dist)
        groups += [[h] for h in hs]
    cont = sorted([h for h in holes if h["type"] == "contour"], key=lambda h: (-pos(h)[1], abs(pos(h)[0])))
    for i in range(0, len(cont), 2 if mode == "edd" else 3):
        groups.append(cont[i:i + (2 if mode == "edd" else 3)])
    lift = sorted([h for h in holes if h["type"] == "lifter"], key=lambda h: abs(pos(h)[0]))
    groups += [[h] for h in lift]

    min_int = float(inp.get("min_interval_ms", 8))
    k_ms = float(inp.get("ms_per_m_burden", 12))
    if mode == "edd":
        t = 0.0
        prev_type = None
        for grp in groups:
            h = grp[0]
            typ = h["type"]
            if typ == "cut":
                step = 75 if prev_type == "cut" else 0
            elif typ in ("stoping", "helper"):
                step = max(50, k_ms * h.get("nn_dist", 1.0) * 3)
            elif typ == "contour":
                step = 100 if prev_type != "contour" else 25
            else:
                step = 100 if prev_type != "lifter" else 50
            step = max(step, min_int) if prev_type else step
            t += step
            for x in grp:
                x["delay_ms"] = int(round(t))
                x["delay_no"] = None
            prev_type = typ
    else:
        ms = [0, 25, 50, 75, 100, 125, 150, 175, 200, 250, 300, 350, 400, 450, 500]
        lp = [600, 800, 1000, 1400, 1800, 2400, 3000, 3800, 4600, 5500, 6400]
        series = ms + lp
        idx = 1
        per = 1
        for gi, grp in enumerate(groups):
            if grp[0]["type"] != "cut" and gi > 0 and groups[gi - 1][0]["type"] == grp[0]["type"]:
                per += 1
                if per > 3:  # до 3 шпуров на одну ступень замедления
                    idx += 1
                    per = 1
            elif gi > 0:
                idx += 1
                per = 1
            no = min(idx, len(series) - 1)
            for x in grp:
                x["delay_no"] = no
                x["delay_ms"] = series[no]


def indicators(result: dict) -> dict:
    p = result["params"]
    inp = result["input"]
    holes = result["holes"]
    loaded = [h for h in holes if h["type"] != "empty" and not h.get("not_drilled")]
    depth = float(inp.get("hole_depth", 3.8))
    kish = float(result.get("kish_override") or p["kish"])
    advance = depth * kish
    vol = p["area"] * advance
    Q = sum(h.get("charge_kg", 0) for h in loaded)
    drill_m = sum(h.get("length", 0) for h in holes if not h.get("not_drilled"))
    counts = {t: sum(1 for h in holes if h["type"] == t) for t in HOLE_TYPES}
    dets = len(loaded)
    expl = inp["explosive"]
    det_price = float((inp.get("initiation_device") or {}).get("price", 14 if inp.get("initiation", "edd") == "edd" else 4.5))
    cost = Q * float(expl.get("price", 1.5)) + dets * det_price
    booms = float((inp.get("drill") or {}).get("booms", 2))
    rate = float((inp.get("drill") or {}).get("drill_rate_mph", 90))
    density = float((inp.get("rock") or {}).get("density", 2.7))
    return {
        "area": p["area"], "depth": depth, "kish": round(kish, 3), "advance": round(advance, 2),
        "volume": round(vol, 2), "tonnes": round(vol * density, 1), "holes_total": len(holes),
        "holes_loaded": len(loaded), "holes_by_type": counts,
        "holes_pokrovsky": holes_pokrovsky(p["pokrovsky"]["q"], p["area"], ex.charge_density(expl),
                                           float(inp.get("hole_diameter", 45))),
        "q_pokrovsky": p["pokrovsky"]["q"], "explosive_kg": round(Q, 1),
        "q_actual": round(Q / vol, 3) if vol else 0, "kg_per_m": round(Q / advance, 1) if advance else 0,
        "kg_per_t": round(Q / (vol * density), 3) if vol else 0,
        "drill_m": round(drill_m, 1), "drill_m_per_m3": round(drill_m / vol, 2) if vol else 0,
        "detonators": dets, "cost": round(cost, 1),
        "drill_time_h": round(drill_m / (rate * booms) + float((inp.get("drill") or {}).get("setup_h", 0.5)), 2),
        "max_delay_ms": max((h.get("delay_ms") or 0) for h in loaded) if loaded else 0,
    }


# ---------------- пересчет по факту бурения ----------------
def recalc_actual(result: dict, actual_holes: list[dict]) -> dict:
    """actual_holes: {id, collar_x, collar_y, toe_x, toe_y, length, drilled}. Возвращает пересчет."""
    import copy

    res = copy.deepcopy(result)
    p = res["params"]
    by_id = {a["id"]: a for a in actual_holes}
    depth = float(res["input"].get("hole_depth", 3.8))
    for h in res["holes"]:
        a = by_id.get(h["id"])
        h["design_x"], h["design_y"], h["design_length"] = h["x"], h["y"], h.get("length", depth)
        h["design_charge_kg"] = h.get("charge_kg", 0)
        if h["type"] == "empty" and a is None:
            h["toe_x"], h["toe_y"] = h["x"], h["y"]  # холостые в отчете станка могут отсутствовать
            continue
        if a is None or not a.get("drilled", True):
            h["not_drilled"] = True
            h["toe_x"], h["toe_y"] = h["x"], h["y"]
            continue
        h["x"], h["y"] = a.get("collar_x", h["x"]), a.get("collar_y", h["y"])
        h["toe_x"], h["toe_y"] = a.get("toe_x", h["x"]), a.get("toe_y", h["y"])
        h["actual_length"] = float(a.get("length", h["design_length"]))
        h["deviation_m"] = round(math.hypot(h["toe_x"] - h["design_x"], h["toe_y"] - h["design_y"]), 3)
        h["length_dev_pct"] = round((h["actual_length"] - h["design_length"]) / h["design_length"] * 100, 1)
    drilled = [h for h in res["holes"] if not h.get("not_drilled") and h["type"] != "empty"]
    nn_toe = _nn(drilled, key=("toe_x", "toe_y"))
    nn_des = _nn(drilled, key=("design_x", "design_y"))
    zones = []
    for h, da, dd in zip(drilled, nn_toe, nn_des):
        r = da / dd if dd else 1.0
        h["burden_actual"] = round(da, 3)
        h["burden_design"] = round(dd, 3)
        h["burden_ratio"] = round(r, 2)
        kgm = h.get("kg_per_m", p["l_max"])
        clen = max(min(h["actual_length"], h["design_length"] + 0.3) - h.get("stemming", 0.3), 0)
        if h["type"] in ("stoping", "helper", "lifter"):
            factor = max(0.6, min(1.4, r * r))
        elif h["type"] == "contour":
            factor = max(0.7, min(1.2, r))
        else:
            factor = 1.0
        rec_kgm = min(kgm * factor, p["l_max"] * (1.0 if h["type"] != "contour" else 1.3))
        h["recommended_kg"] = round(rec_kgm * clen, 2)
        if r < 0.8:
            h["zone"] = "overloaded"
            zones.append({"id": h["id"], "zone": "overloaded", "ratio": h["burden_ratio"]})
        elif r > 1.2:
            h["zone"] = "underloaded"
            zones.append({"id": h["id"], "zone": "underloaded", "ratio": h["burden_ratio"]})
            if kgm * factor > p["l_max"]:
                h["advice"] = "extra_hole"
        else:
            h["zone"] = "ok"
        h["charge_kg"] = h["recommended_kg"]
    # недобур уменьшает подвигание
    lens = [h["actual_length"] for h in drilled]
    mean_len = float(np.mean(lens)) if lens else depth
    contour_missing = sum(1 for h in res["holes"] if h["type"] == "contour" and h.get("not_drilled"))
    kish = p["kish"]
    mean_dev = float(np.mean([h["deviation_m"] for h in drilled])) if drilled else 0
    kish_adj = kish - max(0, mean_dev - 0.1) * 0.25
    res["kish_override"] = round(max(0.6, kish_adj), 3)
    res["input"] = dict(res["input"], hole_depth=round(mean_len, 2), design_hole_depth=depth)
    assign_delays(res, actual=True)
    res["indicators"] = indicators(res)
    res["recalc"] = {
        "zones": zones, "not_drilled": [h["id"] for h in res["holes"] if h.get("not_drilled")],
        "contour_missing": contour_missing, "mean_length": round(mean_len, 2),
        "mean_deviation_m": round(mean_dev, 3),
        "max_deviation_pct": round(max((h["deviation_m"] / h["design_length"] * 100 for h in drilled), default=0), 2),
        "overloaded": sum(1 for z in zones if z["zone"] == "overloaded"),
        "underloaded": sum(1 for z in zones if z["zone"] == "underloaded"),
        "explosive_design_kg": round(sum(h.get("design_charge_kg", 0) for h in res["holes"]), 1),
        "explosive_recommended_kg": round(sum(h.get("charge_kg", 0) for h in drilled), 1),
    }
    return res


def design_toe(h: dict, centroid: tuple[float, float], depth: float) -> tuple[float, float]:
    """Проектное положение конца шпура в плоскости забоя (контурные — наружу, подошвенные — вниз на угол наклона)."""
    ang = math.radians(h.get("angle", 0) or 0)
    if h["type"] in ("contour", "lifter") and ang:
        off = h.get("length", depth) * math.sin(ang)
        if h["type"] == "lifter":
            return h["x"], h["y"] - off
        vx, vy = h["x"] - centroid[0], h["y"] - centroid[1]
        n = math.hypot(vx, vy) or 1
        return h["x"] + vx / n * off, h["y"] + vy / n * off
    return h["x"], h["y"]


def contour_centroid(result: dict) -> tuple[float, float]:
    c = result["contour"]
    return float(np.mean([p[0] for p in c])), float(np.mean([p[1] for p in c]))


def edd_program_csv(result: dict, template: str | None = None) -> str:
    """Файл программирования ЭДД. Шаблон: строка формата с полями {hole},{det},{delay},{type}."""
    tpl = template or "{hole};{det};{delay}"
    header = (template and template.split("\n")[0].startswith("#")) and "" or "hole;detonator;delay_ms"
    rows = [header] if header else []
    for h in sorted((h for h in result["holes"] if h["type"] != "empty" and not h.get("not_drilled")),
                    key=lambda h: h.get("delay_ms", 0)):
        rows.append(tpl.format(hole=h["id"], det=h.get("detonator", f"DET-{h['id']:03d}"),
                               delay=h.get("delay_ms", 0), type=h["type"]))
    return "\n".join(rows) + "\n"


def holes_csv(result: dict) -> str:
    """CSV для навигации буровой: №, тип, x, y, азимут/наклон, длина, диаметр."""
    rows = ["no;type;x;y;length;angle_deg;diameter_mm;charge_kg;stemming_m;delay_ms"]
    for h in result["holes"]:
        rows.append(f"{h['id']};{h['type']};{h['x']:.3f};{h['y']:.3f};{h.get('length', 0):.2f};"
                    f"{h.get('angle', 0):.1f};{h.get('diameter', 0):.0f};{h.get('charge_kg', 0):.2f};"
                    f"{h.get('stemming', 0):.2f};{h.get('delay_ms', '')}")
    return "\n".join(rows) + "\n"


def summary_for_ai(result: dict) -> dict[str, Any]:
    p, i = result["params"], result["indicators"]
    inp = result["input"]
    return {"section": inp["section"], "rock": inp.get("rock"), "explosive": inp["explosive"].get("name"),
            "hole_depth": inp.get("hole_depth"), "hole_diameter": inp.get("hole_diameter"),
            "cut": inp.get("cut"), "params": {k: p[k] for k in ("B_stoping", "E_stoping", "B_lifter", "B_contour",
                                                                  "E_contour", "contour_blasting", "kish")},
            "indicators": i, "warnings": result.get("warnings", []), "recalc": result.get("recalc")}
