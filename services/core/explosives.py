"""ВВ: заряд на метр, проверки совместимости, относительная работоспособность."""
from __future__ import annotations

import math

WATER_ORDER = ["dry", "damp", "dripping", "flowing", "inflow"]
WATER_ALLOWED = {
    "none": {"dry", "damp"},
    "limited": {"dry", "damp", "dripping"},
    "full": set(WATER_ORDER),
}


def charge_density(expl: dict) -> float:
    """Плотность заряжания, г/см³ (середина диапазона)."""
    return (float(expl.get("density_min", 1.0)) + float(expl.get("density_max", 1.0))) / 2


def kg_per_m(expl: dict, hole_d_mm: float) -> float:
    """Заряд на 1 м шпура/скважины: наливное — по диаметру скважины, патроны — по патрону."""
    if expl.get("type") == "cartridge" and expl.get("cart_diameter"):
        if expl.get("cart_mass") and expl.get("cart_length"):
            return float(expl["cart_mass"]) / float(expl["cart_length"])
        d = float(expl["cart_diameter"]) / 1000
        return charge_density(expl) * 1000 * math.pi * d * d / 4
    d = hole_d_mm / 1000
    return charge_density(expl) * 1000 * math.pi * d * d / 4


def s_anfo(expl: dict) -> float:
    """Относительная весовая работоспособность (АНФО = 1)."""
    return float(expl.get("rws", 100)) / 100


def check(expl: dict, hole_d_mm: float, water: str) -> list[dict]:
    """Ошибки и предупреждения: критический диаметр и водоустойчивость против обводнённости."""
    out: list[dict] = []
    crit = float(expl.get("crit_diameter") or 0)
    if hole_d_mm < crit:
        out.append({"level": "error", "code": "diameter_below_critical",
                    "params": {"d": hole_d_mm, "crit": crit, "name": expl.get("name", "")}})
    elif hole_d_mm < float(expl.get("min_diameter") or 0):
        out.append({"level": "warning", "code": "diameter_below_min",
                    "params": {"d": hole_d_mm, "min": expl.get("min_diameter")}})
    if expl.get("type") == "cartridge" and expl.get("cart_diameter") and float(expl["cart_diameter"]) > hole_d_mm - 3:
        out.append({"level": "error", "code": "cartridge_too_big",
                    "params": {"cart": expl["cart_diameter"], "d": hole_d_mm}})
    wr = expl.get("water_resistance", "none")
    if water and water not in WATER_ALLOWED.get(wr, set()):
        out.append({"level": "error", "code": "not_water_resistant",
                    "params": {"name": expl.get("name", ""), "water": water}})
    return out


def suggest_for_water(explosives: list[dict], water: str, hole_d_mm: float) -> list[dict]:
    ok = [e for e in explosives if not [c for c in check(e, hole_d_mm, water) if c["level"] == "error"]]
    return sorted(ok, key=lambda e: (e.get("type") != "emulsion", e.get("price", 0)))
