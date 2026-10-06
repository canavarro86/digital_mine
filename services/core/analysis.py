"""Анализ «факт против проекта»: проходка (КИШ, переборы, лишняя порода, $) и камеры (ELOS, разубоживание,
потери, $), причины отклонений с долями «бурение / заряжание / геология»."""
from __future__ import annotations

import math

import numpy as np
from shapely.geometry import Point, Polygon

from .geometry import section_polygon
from .rings import ore_value_per_t

DEV_CAUSES = ("drill_deviation", "short_holes", "water", "fracturing", "blocky_collapse", "cleavage",
              "missing_contour", "overcharge")
STOPE_CAUSES = ("ring_deviation", "overcharge", "undercharge", "blocked_holes", "weak_hw", "delay_errors")
CAUSE_GROUP = {
    "drill_deviation": "drilling", "short_holes": "drilling", "missing_contour": "drilling",
    "ring_deviation": "drilling", "blocked_holes": "drilling",
    "overcharge": "charging", "undercharge": "charging", "delay_errors": "charging",
    "water": "geology", "fracturing": "geology", "blocky_collapse": "geology", "cleavage": "geology",
    "weak_hw": "geology", "none": "none",
}


def _shares(scores: dict[str, float]) -> tuple[str, dict, dict]:
    tot = sum(v for v in scores.values() if v > 0)
    if tot <= 0.15:
        return "none", {}, {"drilling": 0, "charging": 0, "geology": 0}
    causes = {k: round(v / tot, 3) for k, v in sorted(scores.items(), key=lambda kv: -kv[1]) if v > 0}
    groups = {"drilling": 0.0, "charging": 0.0, "geology": 0.0}
    for k, v in causes.items():
        groups[CAUSE_GROUP[k]] += v
    primary = max(scores, key=scores.get)
    return primary, causes, {k: round(v, 3) for k, v in groups.items()}


# ---------------- проходка ----------------
def analyze_dev(design: dict, scan: dict, drill: dict | None, charge: dict | None, geology: dict,
                economics: dict) -> dict:
    """design — паспорт (input/params/holes/indicators); scan — профили; drill/charge — факт."""
    inp = design["input"]
    poly_d = section_polygon(inp["section"])
    A_d = poly_d.area
    over_areas, under_areas, sides, depths = [], [], [], []
    boundary = poly_d.exterior
    roof_over = []
    cx = poly_d.centroid.x
    for p in scan.get("profiles", []):
        pa = Polygon(p["polygon"]).buffer(0)
        depths.append(max((boundary.distance(Point(x, y)) for x, y in p["polygon"]
                           if not poly_d.contains(Point(x, y))), default=0.0))
        over = pa.difference(poly_d)
        under = poly_d.difference(pa)
        over_areas.append(over.area)
        under_areas.append(under.area)
        right = over.intersection(Polygon([(cx, -50), (50, -50), (50, 50), (cx, 50)])).area
        left = over.area - right
        sides.append((left, right))
        roof_over.append(over.intersection(Polygon([(-50, poly_d.bounds[3] * 0.75), (50, poly_d.bounds[3] * 0.75),
                                                    (50, 50), (-50, 50)])).area)
    over_a = float(np.mean(over_areas)) if over_areas else 0.0
    max_over_pct = float(np.max(over_areas)) / A_d * 100 if over_areas else 0.0
    advance = float(scan.get("advance", 0))
    design_depth = float(inp.get("design_hole_depth") or inp.get("hole_depth", 3.8))
    holes = (drill or {}).get("holes") or []
    drilled = [h for h in holes if h.get("drilled", True)]
    mean_len = float(np.mean([h["length"] for h in drilled])) if drilled else design_depth
    kish = advance / mean_len if mean_len else 0
    density = float(geology.get("density", 2.7))
    extra_m3 = over_a * advance
    extra_t = extra_m3 * density
    costs = economics.get("costs", {})
    perim = poly_d.length
    extra_cost = extra_t * (costs.get("waste_haulage_per_t", 5.5) + 2.0) + \
        (over_a / perim) * perim * advance * 0.3 * costs.get("support_per_m2", 38) * 0.2
    contour_total = int(scan.get("contour_holes") or sum(1 for h in design.get("holes", []) if h["type"] == "contour"))
    half_cast = (scan.get("half_casts_visible", 0) / contour_total * 100) if contour_total else 0
    left = float(np.mean([s[0] for s in sides])) if sides else 0
    right = float(np.mean([s[1] for s in sides])) if sides else 0
    asym = (max(left, right) + 0.01) / (min(left, right) + 0.01)
    roof_share = (float(np.mean(roof_over)) / over_a) if over_a > 0 else 0
    overbreak_pct = over_a / A_d * 100
    max_depth = float(np.max(depths)) if depths else 0.0
    under_pct = float(np.mean(under_areas)) / A_d * 100 if under_areas else 0

    # ---- признаки для причин ----
    dev_pct = [abs(h.get("deviation_pct", 0)) for h in drilled]
    mean_dev = float(np.mean(dev_pct)) if dev_pct else 0
    short = (design_depth - mean_len) / design_depth * 100 if design_depth else 0
    design_contour = [h for h in design.get("holes", []) if h["type"] == "contour"]
    drilled_ids = {h["id"] for h in drilled} if holes else {h["id"] for h in design.get("holes", [])}
    missing_contour = sum(1 for h in design_contour if h["id"] not in drilled_ids)
    missing_contour_pct = missing_contour / len(design_contour) * 100 if design_contour else 0
    ch_holes = (charge or {}).get("holes") or []
    misfires = sum(1 for h in ch_holes if h.get("status") == "misfire")
    plan_kg = float(design.get("indicators", {}).get("explosive_kg", 0))
    fact_kg = sum(float(h.get("kg", 0)) for h in ch_holes) if ch_holes else plan_kg
    over_charge_pct = (fact_kg - plan_kg) / plan_kg * 100 if plan_kg else 0
    water = geology.get("water", "dry")
    cat = int(geology.get("fracture_cat", 3))
    faults = geology.get("faults") or []
    has_cleavage = any(f.get("type") == "cleavage" for f in faults)
    has_blocky = any(f.get("type") in ("blocky", "crush_zone") for f in faults)

    scores = {
        "drill_deviation": max(0.0, mean_dev - 2.0) * 0.6,
        "short_holes": max(0.0, short - 4) * 0.25,
        "water": (1.5 if water in ("flowing", "inflow") else 0.4 if water == "dripping" else 0) *
                 (1 + misfires) * (1.0 if kish < 0.85 else 0.3),
        "fracturing": (cat - 3) * 0.9 * (1.0 if overbreak_pct > 12 else 0.4) if cat >= 4 and overbreak_pct >= 8 else 0,
        "blocky_collapse": (max(0.0, max_depth - 0.45) * 4 + max(0.0, max_over_pct - 30) / 10) * (1.5 if has_blocky else 0.5),
        "cleavage": max(0.0, asym - 2.0) * (1.2 if has_cleavage else 0.4),
        "missing_contour": missing_contour_pct / 10 + max(0.0, 40 - half_cast) / 30 * (1.0 if mean_dev < 3 else 0.3),
        "overcharge": max(0.0, over_charge_pct - 8) / 4,
    }
    if water in ("flowing", "inflow") and misfires == 0 and kish > 0.85:
        scores["water"] = 0.0  # вода по геологии есть, но в факте нет её следов
    primary, causes, groups = _shares(scores)
    return {
        "kind": "dev",
        "design_area": round(A_d, 2), "actual_area": round(A_d + over_a - float(np.mean(under_areas or [0])), 2),
        "advance": round(advance, 2), "design_advance": round(design_depth * design.get("params", {}).get("kish", 0.9), 2),
        "mean_hole_length": round(mean_len, 2), "kish": round(kish, 3),
        "overbreak_pct": round(overbreak_pct, 1), "underbreak_pct": round(under_pct, 1),
        "max_overbreak_pct": round(max_over_pct, 1), "max_overbreak_depth": round(max_depth, 2),
        "extra_m3": round(extra_m3, 2), "extra_t": round(extra_t, 1), "extra_cost": round(extra_cost, 0),
        "half_cast_pct": round(half_cast, 1), "asymmetry": round(asym, 2), "roof_share": round(roof_share, 2),
        "drill_deviation_pct": round(mean_dev, 2), "short_pct": round(short, 1),
        "missing_contour": missing_contour, "misfires": misfires,
        "explosive_plan_kg": round(plan_kg, 1), "explosive_fact_kg": round(fact_kg, 1),
        "charge_over_pct": round(over_charge_pct, 1),
        "primary_cause": primary, "causes": causes, "groups": groups,
        "currency": economics.get("currency", "USD"),
    }


# ---------------- камера ----------------
def analyze_stope(stope: dict, cms: dict, design: dict | None, drill: dict | None, charge: dict | None,
                  geology: dict, economics: dict) -> dict:
    g = stope["geometry"]
    H = stope["level_top"] - stope["level_bottom"]
    W = g["y1"] - g["y0"]
    Lx = g["x_hw"] - g["x_fw"]
    design_vol = W * H * Lx
    ore_d = float(geology.get("ore_density", 2.9))
    waste_d = float(geology.get("waste_density", 2.7))
    over_vol, wall_over = 0.0, {}
    for w, data in cms["walls"].items():
        arr = np.asarray(data["depth"], dtype=float)
        cell = float(data["cell"])
        v = float(np.clip(arr, 0, None).sum() * cell * cell)
        wall_over[w] = {"volume_m3": round(v, 1), "area_m2": data["area"],
                        "elos": round(v / data["area"], 2) if data["area"] else 0,
                        "max_depth": round(float(arr.max()), 2)}
        over_vol += v
    under_vol = sum(float(z["volume_m3"]) for z in cms.get("underbreak_zones", []))
    design_t = design_vol * ore_d
    loss_t = under_vol * ore_d
    dilution_t = over_vol * waste_d
    blasted_t = design_t - loss_t + dilution_t
    value_t = ore_value_per_t(stope.get("grades") or {}, economics)
    costs = economics.get("costs", {})
    planned_value = design_t * value_t
    mining_cost = blasted_t * (costs.get("mining_per_t", 28) + costs.get("haulage_per_t", 4.5))
    dilution_cost = dilution_t * costs.get("processing_per_t", 14)
    loss_cost = loss_t * value_t
    result_usd = planned_value - mining_cost - dilution_cost - loss_cost

    # признаки причин
    holes = (drill or {}).get("holes") or []
    dev = [abs(h.get("deviation_pct", 0)) for h in holes if h.get("drilled", True)]
    mean_dev = float(np.mean(dev)) if dev else 0
    blocked = sum(1 for h in holes if h.get("status") in ("blocked", "not_drilled") or not h.get("drilled", True))
    blocked_pct = blocked / len(holes) * 100 if holes else 0
    ch = (charge or {}).get("holes") or []
    plan_kg = float((design or {}).get("indicators", {}).get("explosive_kg", 0))
    fact_kg = sum(float(h.get("kg", 0)) for h in ch) if ch else plan_kg
    ch_dev = (fact_kg - plan_kg) / plan_kg * 100 if plan_kg else 0
    delay_err = sum(1 for h in ch if h.get("delay_error"))
    weak_hw = bool(geology.get("weak_hw"))
    elos_hw, elos_fw = wall_over.get("hw", {}).get("elos", 0), wall_over.get("fw", {}).get("elos", 0)
    under_pct = under_vol / design_vol * 100
    scores = {
        "ring_deviation": max(0.0, mean_dev - 2.0) * 0.7,
        "overcharge": max(0.0, ch_dev - 8) / 4,
        "undercharge": max(0.0, -ch_dev - 8) / 4,
        "blocked_holes": blocked_pct / 5,
        "weak_hw": (max(0.0, elos_hw - 0.6) * 2.5 + max(0.0, elos_hw - elos_fw * 1.8) * 1.5)
                   * (1.0 if weak_hw else 0.15) * (1.0 if abs(ch_dev) < 8 and mean_dev < 3 else 0.4),
        "delay_errors": delay_err * 0.5,
    }
    if under_pct > 1.5 and scores["blocked_holes"] < 0.5 and scores["undercharge"] < 0.5 and mean_dev < 2.5:
        scores["delay_errors"] += 0.3 * (under_pct / 2) * (1 if delay_err else 0.2)
    primary, causes, groups = _shares(scores)
    return {
        "kind": "stope", "design_volume_m3": round(design_vol, 0), "design_t": round(design_t, 0),
        "blasted_t": round(blasted_t, 0), "dilution_t": round(dilution_t, 0),
        "dilution_pct": round(dilution_t / blasted_t * 100, 1) if blasted_t else 0,
        "loss_t": round(loss_t, 0), "loss_pct": round(loss_t / design_t * 100, 1) if design_t else 0,
        "elos_hw": elos_hw, "elos_fw": elos_fw, "walls": wall_over,
        "ore_value_per_t": round(value_t, 1), "planned_value_usd": round(planned_value, 0),
        "mining_cost_usd": round(mining_cost, 0), "dilution_cost_usd": round(dilution_cost, 0),
        "loss_cost_usd": round(loss_cost, 0), "result_usd": round(result_usd, 0),
        "drill_deviation_pct": round(mean_dev, 2), "blocked_holes": blocked,
        "explosive_plan_kg": round(plan_kg, 0), "explosive_fact_kg": round(fact_kg, 0),
        "charge_dev_pct": round(ch_dev, 1), "delay_errors": delay_err,
        "underbreak_zones": cms.get("underbreak_zones", []),
        "primary_cause": primary, "causes": causes, "groups": groups,
        "currency": economics.get("currency", "USD"),
    }


def summary_for_ai(res: dict) -> dict:
    drop = {"walls", "underbreak_zones"}
    return {k: v for k, v in res.items() if k not in drop}


def elos(volume: float, area: float) -> float:
    return volume / area if area else math.nan
