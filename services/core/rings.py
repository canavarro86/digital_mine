"""Веера глубоких скважин (очистная выемка) и поправочные скважины.

Плоскость веера перпендикулярна оси бурового орта (БДО). Локальные координаты веера: u — по простиранию
(поперек орта), v — по вертикали (отметка). Положение веера вдоль орта — x (от лежачего к висячему боку).
ЛНС — формула Лангефорса с поправками на погрешность бурения. См. README, раздел «Методики расчетов».
"""
from __future__ import annotations

import math

import numpy as np
from shapely.geometry import LineString, Point, Polygon

from . import explosives as ex


def langefors_burden(d_mm: float, density_gcc: float, s: float, f_rock: float, e_b: float = 1.3,
                     fixation: float = 1.0) -> float:
    """B_max = (d/33)·√(P·s / (c̄·f·E/B)), d — мм, P — г/см³; c̄ — постоянная породы с поправкой."""
    c = 0.3 + 0.0125 * f_rock
    cbar = c + 0.05 if c >= 0.3 else c + 0.07
    return (d_mm / 33.0) * math.sqrt(density_gcc * s / (cbar * fixation * e_b))


def stope_section(stope: dict) -> Polygon:
    """Сечение камеры в плоскости веера (u, v): u ∈ [u0, u1], v ∈ [z_bottom, z_top]."""
    g = stope["geometry"]
    return Polygon([(g["y0"], stope["level_bottom"]), (g["y1"], stope["level_bottom"]),
                    (g["y1"], stope["level_top"]), (g["y0"], stope["level_top"])])


def _toes(boundary: Polygon, collar: tuple[float, float], spacing: float, standoff: float,
          direction: str, drive_h: float) -> list[tuple[float, float, str]]:
    """Точки концов скважин вдоль контура камеры с недобуром standoff."""
    inner = boundary.buffer(-standoff, join_style=2)
    if inner.is_empty:
        return []
    minx, miny, maxx, maxy = inner.bounds
    cu, cv = collar
    pts: list[tuple[float, float, str]] = []
    if direction in ("up", "mixed"):
        # левая стенка снизу вверх, кровля, правая стенка сверху вниз
        path = LineString([(minx, cv + drive_h * 0.6), (minx, maxy), (maxx, maxy), (maxx, cv + drive_h * 0.6)])
        n = max(2, int(round(path.length / spacing)))
        for i in range(n + 1):
            p = path.interpolate(i / n, normalized=True)
            side = "roof" if abs(p.y - maxy) < 1e-6 else ("north" if p.x >= maxx - 1e-6 else "south")
            pts.append((p.x, p.y, side))
    if direction in ("down", "mixed"):
        top = maxy if direction == "down" else cv
        path = LineString([(minx, top - drive_h * 0.6), (minx, miny), (maxx, miny), (maxx, top - drive_h * 0.6)])
        n = max(2, int(round(path.length / spacing)))
        for i in range(n + 1):
            p = path.interpolate(i / n, normalized=True)
            side = "floor" if abs(p.y - miny) < 1e-6 else ("north" if p.x >= maxx - 1e-6 else "south")
            pts.append((p.x, p.y, side))
    return pts


def design_rings(inp: dict, stope: dict) -> dict:
    """Расчет вееров камеры. inp: explosive, rock(ore), d_mm, direction(up/down/mixed), standoff, ..."""
    expl = inp["explosive"]
    ore = inp.get("rock") or {}
    d = float(inp.get("hole_diameter", 89))
    direction = inp.get("direction", "up")
    standoff = float(inp.get("standoff", 0.7))
    drive_h = float(inp.get("drive_height", 4.5))
    dens = ex.charge_density(expl)
    s = ex.s_anfo(expl)
    f = float(ore.get("f", 12))
    e_b = float(inp.get("spacing_ratio", 1.3))
    Bmax = langefors_burden(d, dens, s, f, e_b)
    g = stope["geometry"]
    H = stope["level_top"] - stope["level_bottom"]
    err = d / 1000 * 2 + 0.03 * min(H, 30)  # погрешность забуривания и отклонения
    B = float(inp.get("burden") or round(max(Bmax - err, 0.8), 2))
    E = float(inp.get("toe_spacing") or round(B * e_b, 2))
    l_kgm = ex.kg_per_m(expl, d)
    density_ore = float(ore.get("density", 2.9))
    poly = stope_section(stope)
    u_c = (g["y0"] + g["y1"]) / 2
    collar_v = stope["level_bottom"] + drive_h * 0.65 if direction != "down" else stope["level_top"] + 0.5
    collar = (u_c, collar_v)
    x_fw, x_hw = g["x_fw"], g["x_hw"]
    # отрезная щель у висячего бока, далее веера с шагом B к лежачему (отступка)
    slot_x = x_hw - float(inp.get("slot_width", 3.0))
    xs = list(np.arange(slot_x - B, x_fw + B * 0.4, -B))
    if inp.get("max_rings"):
        xs = xs[: int(inp["max_rings"])]
    toes = _toes(poly, collar, E, standoff, direction, drive_h)
    area = poly.area
    rings: list[dict] = []
    for k, x in enumerate(xs, start=1):
        holes = []
        for j, (tu, tv, side) in enumerate(toes, start=1):
            L = math.hypot(tu - collar[0], tv - collar[1])
            dip = math.degrees(math.atan2(tv - collar[1], tu - collar[0]))
            holes.append({"id": j, "u": round(tu, 2), "v": round(tv, 2), "length": round(L, 2),
                          "angle": round(dip, 1), "side": side, "diameter": d, "status": "designed"})
        _uncharged(holes, collar, E, k)
        total = 0.0
        for h in holes:
            h["charge_length"] = round(max(h["length"] - h["uncharged"], 0), 2)
            h["charge_kg"] = round(h["charge_length"] * l_kgm, 1)
            total += h["charge_kg"]
        tonnes = area * B * density_ore
        ring_delay(holes, k, float(inp.get("ring_interval_ms", 75)), inp.get("initiation", "edd"))
        rings.append({"no": k, "x": round(float(x), 2), "burden": B, "holes": holes,
                      "charge_kg": round(total, 1), "tonnes": round(tonnes, 1),
                      "kg_per_t": round(total / tonnes, 3) if tonnes else 0,
                      "drill_m": round(sum(h["length"] for h in holes), 1)})
    tot_kg = sum(r["charge_kg"] for r in rings)
    tot_t = sum(r["tonnes"] for r in rings)
    warnings = ex.check(expl, d, ore.get("water", "dry"))
    if not (64 <= d <= 115):
        warnings.append({"level": "warning", "code": "ring_diameter_range", "params": {"d": d}})
    res = {
        "input": inp, "stope_id": stope.get("id"), "collar": [round(c, 2) for c in collar],
        "section": [list(p) for p in poly.exterior.coords],
        "params": {"B_max": round(Bmax, 2), "burden": B, "toe_spacing": E, "kg_per_m": round(l_kgm, 2),
                   "drill_error": round(err, 2), "standoff": standoff, "direction": direction,
                   "slot_x": round(slot_x, 2), "x_fw": round(x_fw, 2), "x_hw": round(x_hw, 2)},
        "rings": rings,
        "indicators": {"rings": len(rings), "holes": sum(len(r["holes"]) for r in rings),
                       "drill_m": round(sum(r["drill_m"] for r in rings), 1),
                       "explosive_kg": round(tot_kg, 1), "tonnes": round(tot_t, 1),
                       "kg_per_t": round(tot_kg / tot_t, 3) if tot_t else 0,
                       "t_per_drill_m": round(tot_t / max(sum(r["drill_m"] for r in rings), 1), 2)},
        "warnings": warnings,
    }
    res["energy"] = energy_map(res, rings[0]["holes"] if rings else [], l_kgm, B, density_ore) if rings else None
    return res


def _uncharged(holes: list[dict], collar: tuple[float, float], E: float, ring_no: int) -> None:
    """Незаряжаемая часть у устья: заряд начинается, где расстояние до соседних скважин ≥ k·E
    (k чередуется 0,5/0,7 по скважинам и веерам, чтобы не концентрировать энергию у устьев)."""
    n = len(holes)
    for i, h in enumerate(holes):
        k = 0.5 if (i + ring_no) % 2 == 0 else 0.7
        neigh = [holes[j] for j in (i - 1, i + 1) if 0 <= j < n]
        if not neigh:
            h["uncharged"] = round(max(1.5, h["length"] * 0.2), 2)
            continue
        ang = min(abs(math.radians(h["angle"] - o["angle"])) for o in neigh) or 1e-3
        dist = (k * E) / (2 * math.sin(ang / 2)) if ang > 1e-3 else h["length"] * 0.3
        h["uncharged"] = round(min(max(dist, 1.5), h["length"] * 0.6), 2)


def ring_delay(holes: list[dict], ring_no: int, ring_interval: float, mode: str) -> None:
    """Замедления: веер k стартует в (k-1)·интервал; внутри — от центра к краям по парам, шаг 8–25 мс."""
    order = sorted(range(len(holes)), key=lambda i: abs(holes[i]["angle"] - 90))
    for rank, i in enumerate(order):
        base = (ring_no - 1) * ring_interval
        if mode == "edd":
            holes[i]["delay_ms"] = int(base + (rank // 2) * 9)
        else:
            holes[i]["delay_ms"] = int(base)
            holes[i]["delay_no"] = ring_no


def energy_map(res: dict, holes: list[dict], l_kgm: float, B: float, density: float, step: float = 0.75) -> dict:
    """Распределение энергии в плоскости веера: кг ВВ на тонну в ячейке (вклад заряженных интервалов ~1/r²)."""
    poly = Polygon(res["section"])
    minx, miny, maxx, maxy = poly.bounds
    cu, cv = res["collar"]
    us = np.arange(minx + step / 2, maxx, step)
    vs = np.arange(miny + step / 2, maxy, step)
    grid = np.zeros((len(vs), len(us)))
    segs = []
    for h in holes:
        L, u0 = h["length"], h.get("uncharged", 0)
        if L <= 0:
            continue
        du, dv = (h["u"] - cu) / L, (h["v"] - cv) / L
        for t in np.arange(u0, L, 0.5):
            segs.append((cu + du * t, cv + dv * t))
    if segs:
        S = np.array(segs)
        UU, VV = np.meshgrid(us, vs)
        for su, sv in S:
            r2 = (UU - su) ** 2 + (VV - sv) ** 2 + 0.25
            grid += (l_kgm * 0.5) / (math.pi * r2)
    mask = np.array([[poly.contains(Point(u, v)) for u in us] for v in vs])
    grid[~mask] = np.nan
    # калибровка: среднее по сечению = удельному расходу веера (кг/т); цвет — отклонение от среднего
    total = sum(h.get("charge_kg", 0) for h in holes)
    target = total / (poly.area * B * density) if poly.area else 0
    mean = float(np.nanmean(grid)) if np.isfinite(grid).any() else 0
    if mean > 0:
        grid = grid * (target / mean)
    return {"u": us.round(2).tolist(), "v": vs.round(2).tolist(),
            "values": [[None if np.isnan(x) else round(float(x), 3) for x in row] for row in grid],
            "unit": "kg/t", "target": round(target, 3)}


# ---------------- поправочные скважины ----------------
def correction(stope: dict, underbreak: list[dict], inp: dict, econ: dict, grades: dict) -> dict:
    """underbreak: зоны недобора [{u, v, x, volume_m3}] (по скану). Проектирует добурку и считает окупаемость."""
    expl = inp["explosive"]
    d = float(inp.get("hole_diameter", 76))
    l_kgm = ex.kg_per_m(expl, d)
    density = float(inp.get("density", 2.9))
    collar = inp.get("collar") or [(stope["geometry"]["y0"] + stope["geometry"]["y1"]) / 2,
                                    stope["level_bottom"] + 3.0]
    holes, vol = [], 0.0
    for i, z in enumerate(underbreak, start=1):
        vol += float(z["volume_m3"])
        L = math.hypot(z["u"] - collar[0], z["v"] - collar[1]) + 1.0
        n = max(1, int(math.ceil(z["volume_m3"] / 60)))
        for k in range(n):
            holes.append({"id": len(holes) + 1, "zone": i, "u": round(z["u"] + (k - n / 2) * 0.8, 2),
                          "v": round(z["v"], 2), "x": round(z.get("x", 0), 2), "length": round(L, 1),
                          "charge_kg": round((L - 1.5) * l_kgm, 1)})
    tonnes = vol * density
    costs = econ.get("costs", {})
    metal_value = ore_value_per_t(grades, econ)
    value = tonnes * metal_value
    drill_m = sum(h["length"] for h in holes)
    charge = sum(h["charge_kg"] for h in holes)
    hours = drill_m / float(inp.get("drill_rate_mph", 35)) + 4 + len(holes) * 0.3
    cost = (drill_m * costs.get("drilling_per_m", 12) + charge * (float(expl.get("price", 1.3)) +
            costs.get("charging_per_kg", 0.6)) + hours * costs.get("downtime_per_h", 650) +
            tonnes * (costs.get("haulage_per_t", 4.5) + costs.get("processing_per_t", 14)))
    return {
        "holes": holes, "volume_m3": round(vol, 1), "tonnes": round(tonnes, 1),
        "metal": {m: round(tonnes * float(v.get("value", 0)) * (1 if v.get("unit") == "%" else 1), 3)
                  for m, v in (grades or {}).items()},
        "value_usd": round(value, 0), "cost_usd": round(cost, 0), "downtime_h": round(hours, 1),
        "drill_m": round(drill_m, 1), "explosive_kg": round(charge, 1),
        "profit_usd": round(value - cost, 0), "decision": "recover" if value > cost else "leave",
    }


def ore_value_per_t(grades: dict, econ: dict) -> float:
    """Ценность тонны руды (NSR), USD/т."""
    prices = econ.get("metal_prices", {})
    rec = econ.get("recovery", {})
    nsr = float(econ.get("nsr_factor", 0.82))
    v = 0.0
    for m, g in (grades or {}).items():
        val = float(g.get("value", 0))
        pr = prices.get(m, {})
        if g.get("unit") == "%":
            v += val / 100 * float(pr.get("price", 0)) * float(rec.get(m, 0.9))
        else:  # г/т → унции
            v += val / 31.1035 * float(pr.get("price", 0)) * float(rec.get(m, 0.85))
    return v * nsr


def holes_csv(res: dict) -> str:
    rows = ["ring;hole;x;u;v;length;angle_deg;diameter_mm;uncharged_m;charge_kg;delay_ms"]
    for r in res["rings"]:
        for h in r["holes"]:
            rows.append(f"{r['no']};{h['id']};{r['x']:.2f};{h['u']:.2f};{h['v']:.2f};{h['length']:.2f};"
                        f"{h['angle']:.1f};{h['diameter']:.0f};{h['uncharged']:.2f};{h['charge_kg']:.1f};"
                        f"{h.get('delay_ms', '')}")
    return "\n".join(rows) + "\n"


def recalc_actual(res: dict, actual: list[dict]) -> dict:
    """Пересчет вееров по факту бурения Simba: длины, недобур, заблокированные скважины → заряды.
    actual: [{ring, id, length, deviation_pct, drilled, status}]. Соседи заблокированной скважины в веере
    получают до +10 % заряда (в пределах длины), сама скважина исключается."""
    import copy

    out = copy.deepcopy(res)
    by = {(a["ring"], a["id"]): a for a in actual}
    kgm = out["params"]["kg_per_m"]
    blocked_total = 0
    for r in out["rings"]:
        holes = r["holes"]
        for i, h in enumerate(holes):
            a = by.get((r["no"], h["id"]))
            h["design_length"], h["design_charge_kg"] = h["length"], h["charge_kg"]
            if not a:
                continue
            if not a.get("drilled", True) or a.get("status") in ("blocked", "not_drilled"):
                h["status"], h["charge_kg"], h["charge_length"] = "blocked", 0.0, 0.0
                blocked_total += 1
                for j in (i - 1, i + 1):
                    if 0 <= j < len(holes):
                        holes[j]["boost"] = holes[j].get("boost", 0) + 0.10
                continue
            h["status"] = "drilled"
            h["length"] = float(a.get("length", h["length"]))
            h["deviation_pct"] = float(a.get("deviation_pct", 0))
        for h in holes:
            if h.get("status") == "blocked":
                continue
            cl = max(h["length"] - h["uncharged"], 0)
            h["charge_length"] = round(cl, 2)
            h["charge_kg"] = round(cl * kgm * (1 + h.get("boost", 0)), 1)
        r["charge_kg"] = round(sum(h["charge_kg"] for h in holes), 1)
        r["kg_per_t"] = round(r["charge_kg"] / r["tonnes"], 3) if r["tonnes"] else 0
    tot = sum(r["charge_kg"] for r in out["rings"])
    out["indicators"] = {**out["indicators"], "explosive_kg": round(tot, 1),
                         "kg_per_t": round(tot / out["indicators"]["tonnes"], 3) if out["indicators"]["tonnes"] else 0}
    out["recalc"] = {"blocked": blocked_total, "explosive_design_kg": res["indicators"]["explosive_kg"],
                     "explosive_recommended_kg": round(tot, 1)}
    return out
