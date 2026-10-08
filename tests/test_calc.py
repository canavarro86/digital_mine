"""Эталонные примеры расчетов (допуски — README, раздел «Методики расчетов»)."""
import math

import pytest

from core import explosives as ex
from core import passport, rings
from core.geometry import section_area, section_polygon

SECTIONS = {
    "arch": {"shape": "arch", "width": 5.0, "height": 5.0, "arch_height": 1.25},
    "rect": {"shape": "rect", "width": 5.0, "height": 5.0},
    "trapezoid": {"shape": "trapezoid", "width": 5.0, "height": 5.0, "top_width": 4.0},
    "horseshoe": {"shape": "horseshoe", "width": 5.0, "height": 5.0},
}


def test_section_areas():
    assert section_area(SECTIONS["rect"]) == pytest.approx(25.0, rel=1e-6)
    assert section_area(SECTIONS["trapezoid"]) == pytest.approx(22.5, rel=1e-6)
    # арка: 5×3,75 + сегмент круга с хордой 5 м и стрелой 1,25 м
    R = (1.25 ** 2 + 2.5 ** 2) / (2 * 1.25)
    seg = R * R * math.acos((R - 1.25) / R) - (R - 1.25) * math.sqrt(2 * R * 1.25 - 1.25 ** 2)
    assert section_area(SECTIONS["arch"]) == pytest.approx(5 * 3.75 + seg, rel=0.01)
    assert section_polygon(SECTIONS["horseshoe"]).is_valid


def test_pokrovsky_reference():
    """q = 0,1f · fs · 6,5/√S · e · kd; пример: f=12, кат. III, S=23,11 м², RWS 80 %, d=45 мм."""
    r = passport.pokrovsky(12, 3, 23.11, 80, 45)
    expected = 1.2 * 1.4 * (6.5 / math.sqrt(23.11)) * (105 / 80) * (36 / 45) ** 0.3
    assert r["q"] == pytest.approx(expected, rel=0.005)
    assert r["q"] == pytest.approx(2.788, abs=0.01)


def test_holmberg_cut_reference():
    """Первая секция прямого вруба: a = 1,5φ; φ = D·√n."""
    phi = 0.102 * math.sqrt(2)
    secs = passport.cut_sections(phi, 0.045, 1.75, 0.8, 0.45, 3.8, 3.0)
    assert secs[0]["B"] == pytest.approx(1.5 * phi, abs=0.002)
    assert all(secs[i]["W"] > secs[i - 1]["W"] for i in range(1, len(secs)))
    assert passport.cut_max_advance(phi) == pytest.approx(0.15 + 34.1 * phi - 39.4 * phi ** 2, rel=1e-9)


def test_langefors_reference():
    """B = d/33 · √(P·s / (c̄·f·E/B)): d=89, P=1,10, s=0,8, f=12 (c=0,45, c̄=0,50), E/B=1,3 → 3,14 м."""
    assert rings.langefors_burden(89, 1.10, 0.8, 12, 1.3) == pytest.approx(3.138, abs=0.01)


def test_kg_per_m(expl):
    assert ex.kg_per_m(expl["ANFO"], 45) == pytest.approx(0.875 * 1000 * math.pi * 0.045 ** 2 / 4, rel=1e-6)
    assert ex.kg_per_m(expl["EMUL_CART_32"], 45) == pytest.approx(0.35 / 0.40, rel=1e-6)


def test_anfo_forbidden_on_wet(expl):
    errs = [c for c in ex.check(expl["ANFO"], 45, "flowing") if c["level"] == "error"]
    assert errs and errs[0]["code"] == "not_water_resistant"
    assert not [c for c in ex.check(expl["EMUL_BULK"], 45, "flowing") if c["level"] == "error"]
    assert [c for c in ex.check(expl["EMUL_BULK"], 30, "dry") if c["code"] == "diameter_below_critical"]


@pytest.mark.parametrize("shape", list(SECTIONS))
def test_passport_four_sections(shape, expl):
    inp = {"section": SECTIONS[shape], "rock": {"f": 12, "fracture_cat": 3, "density": 2.75, "water": "dry"},
           "explosive": expl["EMUL_BULK"], "contour_explosive": expl["EMUL_SMOOTH_25"], "hole_depth": 3.8,
           "hole_diameter": 45, "empty_diameter": 102, "cut": {"type": "prismatic"}, "initiation": "edd"}
    r = passport.design(inp)
    ind = r["indicators"]
    by = ind["holes_by_type"]
    assert by["empty"] >= 1 and by["cut"] >= 8 and by["contour"] >= 10 and by["lifter"] >= 4
    # удельный расход по раскладке — в пределах ±45 % от Покровского (разные методики)
    assert 0.55 * ind["q_pokrovsky"] <= ind["q_actual"] <= 1.45 * ind["q_pokrovsky"]
    assert 0.80 <= ind["kish"] <= 0.95
    assert not [w for w in r["warnings"] if w["level"] == "error"]
    # порядок замедлений: вруб → отбойные → контур → подошва
    d = {t: [h["delay_ms"] for h in r["holes"] if h["type"] == t] for t in ("cut", "contour", "lifter")}
    assert max(d["cut"]) < min(d["contour"]) < max(d["contour"]) <= max(d["lifter"])
    assert len({h["id"] for h in r["holes"]}) == len(r["holes"])


def test_passport_evaluate_after_drag(expl):
    inp = {"section": SECTIONS["arch"], "rock": {"f": 12, "fracture_cat": 3}, "explosive": expl["EMUL_BULK"],
           "hole_depth": 3.8, "hole_diameter": 45}
    r = passport.design(inp)
    before = r["indicators"]["explosive_kg"]
    h = next(h for h in r["holes"] if h["type"] == "contour")
    h["x"] += 6.0 if h["x"] >= 0 else -6.0  # утащили шпур за контур
    r2 = passport.evaluate(r)
    moved = next(x for x in r2["holes"] if x["id"] == h["id"])
    assert moved.get("flag") == "outside_contour"
    r2["holes"] = [x for x in r2["holes"] if x["type"] != "stoping" or x["id"] % 2]
    r3 = passport.evaluate(r2)
    assert r3["indicators"]["explosive_kg"] <= before


def test_recalc_actual_and_delays(expl):
    inp = {"section": SECTIONS["arch"], "rock": {"f": 12, "fracture_cat": 3}, "explosive": expl["EMUL_BULK"],
           "hole_depth": 3.8, "hole_diameter": 45, "initiation": "edd"}
    r = passport.design(inp)
    actual = []
    for h in r["holes"]:
        if h["type"] == "empty":
            continue
        shift = 0.35 if h["type"] == "stoping" or h["id"] % 5 == 0 else 0.0
        actual.append({"id": h["id"], "collar_x": h["x"], "collar_y": h["y"], "toe_x": h["x"] + shift, "toe_y": h["y"],
                       "length": 3.7, "drilled": h["id"] != r["holes"][-1]["id"]})
    rc = passport.recalc_actual(r, actual)
    assert rc["recalc"]["not_drilled"]
    assert rc["recalc"]["overloaded"] + rc["recalc"]["underloaded"] > 0
    order = {t: [h["delay_ms"] for h in rc["holes"] if h["type"] == t and not h.get("not_drilled")] for t in ("cut", "lifter")}
    assert max(order["cut"]) < min(order["lifter"])
    csv = passport.edd_program_csv(rc)
    assert csv.startswith("hole;detonator;delay_ms") and len(csv.splitlines()) > 20


def test_rings_up_and_down(expl):
    stope = {"id": 1, "geometry": {"y0": 192.5, "y1": 207.5, "x_fw": 177.4, "x_hw": 189.0}, "level_bottom": -225, "level_top": -200}
    for direction in ("up", "down", "mixed"):
        res = rings.design_rings({"explosive": expl["EMUL_BULK"], "rock": {"f": 12, "density": 2.9}, "hole_diameter": 89,
                                  "direction": direction}, stope)
        assert res["indicators"]["rings"] >= 3
        assert 0.15 < res["indicators"]["kg_per_t"] < 0.9
        assert all(h["uncharged"] >= 1.5 for r in res["rings"] for h in r["holes"])
        assert res["energy"]["values"]


def test_correction_economics(expl, econ):
    stope = {"geometry": {"y0": 0, "y1": 15, "x_fw": 100, "x_hw": 112}, "level_bottom": -225, "level_top": -200}
    zones = [{"u": 7, "v": -210, "x": 105, "volume_m3": 180}]
    good = rings.correction(stope, zones, {"explosive": expl["EMUL_BULK"]}, econ, {"Cu": {"value": 1.4, "unit": "%"}, "Au": {"value": 2.1, "unit": "g/t"}})
    poor = rings.correction(stope, zones, {"explosive": expl["EMUL_BULK"]}, econ, {"Cu": {"value": 0.05, "unit": "%"}})
    assert good["decision"] == "recover" and poor["decision"] == "leave"
    assert good["tonnes"] == pytest.approx(180 * 2.9, rel=0.01)
