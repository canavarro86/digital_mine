"""Каждый сценарий нарушений 15.1 и 15.2 должен давать правильную причину (эталон) — критерий ≥ 80 %."""
import numpy as np
import pytest

from api.routers.workflow import normalize_dev_holes
from core import analysis, passport, rings, scans, simulate

DEV = ["drill_deviation", "short_holes", "water", "fracturing", "blocky_collapse", "cleavage", "missing_contour", "overcharge"]
STOPE = ["ring_deviation", "overcharge", "undercharge", "blocked_holes", "weak_hw", "delay_errors"]
N = 6


def run_dev(scn, expl, econ, rng):
    inp = {"section": {"shape": "arch", "width": 5.0, "height": 5.0, "arch_height": 1.25},
           "rock": {"f": 12, "fracture_cat": 3, "density": 2.75, "water": "dry"}, "explosive": expl["EMUL_BULK"],
           "contour_explosive": expl["EMUL_SMOOTH_25"], "hole_depth": 3.8, "hole_diameter": 45}
    d = passport.design(inp)
    k = 1.0
    dr = normalize_dev_holes(d, simulate.dev_drill(d["holes"], scn, k, rng))
    rc = passport.recalc_actual(d, dr)
    ch = simulate.dev_charge(rc["holes"], scn, k, rng)
    eff = {scn: "medium"} if scn in scans.DEV_EFFECTS else {}
    scan = scans.gen_dev_scan(inp["section"], d["params"]["kish"] * 3.8, eff, rng,
                              contour_holes=sum(1 for h in d["holes"] if h["type"] == "contour"))
    geo = {"f": 12, "fracture_cat": 3, "density": 2.75, "water": "dry", "faults": []}
    obs = simulate.observations(scn, k)
    geo.update({k_: v for k_, v in obs.items() if k_ != "faults"})
    geo["faults"] = obs.get("faults", [])
    res = analysis.analyze_dev({**rc, "holes": d["holes"]}, scan, {"holes": dr}, {"holes": ch}, geo, econ)
    return res["primary_cause"]


def run_stope(scn, expl, econ, rng):
    stope = {"id": 1, "geometry": {"y0": 192.5, "y1": 207.5, "x_fw": 177.4, "x_hw": 189.0}, "level_bottom": -225,
             "level_top": -200, "grades": {"Cu": {"value": 1.4, "unit": "%"}}}
    rd = rings.design_rings({"explosive": expl["EMUL_BULK"], "rock": {"f": 12, "density": 2.9}, "hole_diameter": 89}, stope)
    holes = [{**h, "ring": r["no"]} for r in rd["rings"] for h in r["holes"]]
    dr = simulate.stope_drill(holes, scn, 1.0, rng)
    rc = rings.recalc_actual(rd, dr)
    ch = simulate.stope_charge(rc["rings"], scn, 1.0, rng)
    eff = {scn: "medium"} if scn in scans.STOPE_EFFECTS else {}
    cms = scans.gen_cms(stope, eff, rng)
    geo = {"ore_density": 2.9, "waste_density": 2.7, **simulate.observations(scn, 1.0)}
    return analysis.analyze_stope(stope, cms, rc, {"holes": dr}, {"holes": ch}, geo, econ)["primary_cause"]


def test_dev_scenarios(expl, econ):
    rng = np.random.default_rng(7)
    ok, total, by = 0, 0, {}
    for s in DEV:
        hits = sum(run_dev(s, expl, econ, rng) == s for _ in range(N))
        by[s] = hits
        ok += hits
        total += N
    assert ok / total >= 0.8, by
    print("dev scenarios:", by)
    assert all(v >= N // 2 for v in by.values()), by


def test_stope_scenarios(expl, econ):
    rng = np.random.default_rng(11)
    ok, total, by = 0, 0, {}
    for s in STOPE:
        hits = sum(run_stope(s, expl, econ, rng) == s for _ in range(N))
        by[s] = hits
        ok += hits
        total += N
    assert ok / total >= 0.8, by


@pytest.mark.parametrize("kind", ["dev", "stope"])
def test_no_scenario_is_within_norm(kind, expl, econ):
    rng = np.random.default_rng(3)
    fn = run_dev if kind == "dev" else run_stope
    res = [fn("none", expl, econ, rng) for _ in range(N)]
    assert res.count("none") >= N // 2, res
