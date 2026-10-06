"""Генерация «факта» по сценариям нарушений (эмулятор и эталонные тесты анализатора используют одну логику)."""
from __future__ import annotations

import math

import numpy as np

K = {"weak": 0.5, "medium": 1.0, "strong": 1.6}


def dev_drill(holes: list[dict], scenario: str, k: float, rng: np.random.Generator,
              centroid: tuple[float, float] = (0.0, 2.2)) -> list[dict]:
    """Фактическое бурение шпуров проходки: устье, конец (проектный + отклонение), длина, «не пробурен»."""
    from .passport import design_toe

    out = []
    sigma = 0.008 + (0.04 * k if scenario == "drill_deviation" else 0)
    for h in holes:
        if h["type"] == "empty":
            continue
        L = h.get("length", 3.8)
        if scenario == "short_holes":
            L *= 1 - 0.1 * k - 0.03
        L *= 1 + rng.normal(0, 0.01)
        drilled = not (scenario == "missing_contour" and h["type"] == "contour" and rng.random() < 0.3 * k)
        dx, dy = rng.normal(0, sigma * L / math.sqrt(2), 2)
        ex, ey = rng.normal(0, 0.03, 2)
        tx, ty = design_toe(h, centroid, L)
        out.append({"id": h["id"], "collar_x": round(h["x"] + ex, 3), "collar_y": round(h["y"] + ey, 3),
                    "toe_x": round(tx + ex + dx, 3), "toe_y": round(ty + ey + dy, 3), "length": round(L, 2), "drilled": drilled})
    return out


def dev_charge(holes: list[dict], scenario: str, k: float, rng: np.random.Generator) -> list[dict]:
    out = []
    for h in holes:
        if h["type"] == "empty" or h.get("not_drilled"):
            continue
        kg = float(h.get("charge_kg", 0))
        if scenario == "overcharge":
            kg *= 1 + 0.2 * k
        kg *= 1 + rng.normal(0, 0.03)
        status = "misfire" if (scenario == "water" and rng.random() < 0.12 * k) else "charged"
        out.append({"id": h["id"], "explosive": h.get("explosive", ""), "kg": round(kg, 2), "length": h.get("charge_length"),
                    "stemming": h.get("stemming"), "detonator": f"EDD-{h['id']:03d}", "delay_ms": h.get("delay_ms"), "status": status})
    return out


def stope_drill(holes: list[dict], scenario: str, k: float, rng: np.random.Generator) -> list[dict]:
    out = []
    for h in holes:
        dev = abs(rng.normal(0, 1.0 + (4.0 * k if scenario == "ring_deviation" else 0)))
        blocked = scenario == "blocked_holes" and rng.random() < 0.15 * k
        out.append({"ring": h["ring"], "id": h["id"], "length": round(h["length"] * (1 + rng.normal(0, 0.01)), 2),
                    "deviation_pct": round(dev, 2), "drilled": not blocked, "status": "blocked" if blocked else "drilled"})
    return out


def stope_charge(rings: list[dict], scenario: str, k: float, rng: np.random.Generator) -> list[dict]:
    out = []
    n_err = int(round(3 * k)) if scenario == "delay_errors" else 0
    for r in rings:
        for h in r["holes"]:
            if h.get("status") == "blocked":
                continue
            kg = float(h["charge_kg"])
            if scenario == "overcharge":
                kg *= 1 + 0.2 * k
            if scenario == "undercharge":
                kg *= 1 - 0.2 * k
            err = n_err > 0 and rng.random() < 0.3
            if err:
                n_err -= 1
            out.append({"ring": r["no"], "id": h["id"], "kg": round(kg * (1 + rng.normal(0, 0.03)), 1),
                        "delay_ms": h.get("delay_ms"), "delay_error": err, "status": "charged"})
    return out


def observations(scenario: str, k: float) -> dict:
    """Что фиксируют маркшейдер и геолог при съёмке (приток, кливаж, вывалы, отслоение висячего бока)."""
    return {
        "water": {"water": "flowing"},
        "fracturing": {"fracture_cat": 5 if k > 1 else 4},
        "blocky_collapse": {"faults": [{"type": "blocky"}]},
        "cleavage": {"faults": [{"type": "cleavage", "azimuth": 20, "dip": 65}]},
        "weak_hw": {"weak_hw": True},
    }.get(scenario, {})


def strength_name(k: float) -> str:
    return next((n for n, v in K.items() if v == k), "medium")
