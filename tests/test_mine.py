"""Демо-рудник, планирование выработок, импорт/экспорт форматов."""
import io

import numpy as np
import pytest

from core import exporters, importers, mine_gen, planning, scans
from core import geometry as g


@pytest.fixture(scope="module")
def mine(tmp_path_factory):
    path = tmp_path_factory.mktemp("mine") / "default_mine"
    summary = mine_gen.generate(path)
    return path, summary


def test_demo_mine(mine):
    path, s = mine
    assert s["levels"] == [-200, -225, -250, -275, -300]
    assert s["fleet"] == 12 and s["staff"] == 23
    parsed = importers.parse("workings.csv", (path / "geometry" / "workings.csv").read_bytes())
    ws = importers.polylines_to_workings(parsed)
    names = {w["name"] for w in ws}
    assert {"Автоуклон №1", "ПШ−200 (С)", "ПШ−200 (Ю)", "Заезд на гор. −200", "БДО −200.1"} <= names
    ramp = next(w for w in ws if w["type"] == "ramp")
    z = [p[2] for p in ramp["axis"]]
    # уклон 1:7 по горизонтальной проекции
    horiz = sum(np.hypot(np.diff([p[0] for p in ramp["axis"]]), np.diff([p[1] for p in ramp["axis"]])))
    assert (z[0] - z[-1]) / horiz == pytest.approx(1 / 7, rel=0.02)


def test_dxf_roundtrip(mine):
    path, _ = mine
    data = (path / "geometry" / "workings.dxf").read_bytes()
    parsed = importers.parse("w.dxf", data)
    assert "WORKINGS_FWD" in parsed["layers"] and "OREBODY" in parsed["layers"]
    ws = importers.polylines_to_workings(parsed)
    assert any(w["name"] == "ПШ−200 (С)" and w["type"] == "fwd" for w in ws)


def test_new_level_wizard(mine):
    path, _ = mine
    cfg = mine_gen.mine_config()
    ramp = mine_gen.ramp_axis()
    items = planning.new_level(cfg, ramp, {"level": -300, "xc": {"spacing": 20}, "fwd": {"directions": ["N", "S"]}}, "ru")
    names = [w["name"] for w in items]
    assert "ПШ−300 (С)" in names and "ПШ−300 (Ю)" in names and "Заезд на гор. −300" in names
    for d in ("N", "S"):
        ys = sorted(w["axis"][0][1] for w in items if w["type"] == "xc" and w["direction"] == d)
        assert len(ys) >= 5 and all(abs((b - a) - 20) < 1e-6 for a, b in zip(ys, ys[1:]))
    en = planning.new_level(cfg, ramp, {"level": -300}, "en")
    assert any(w["name"] == "FWD L−300 (N)" for w in en)
    deep = planning.new_level(cfg, ramp, {"level": -340}, "ru")
    ext = [w for w in deep if w["type"] == "ramp"]
    assert ext and abs(ext[0]["axis"][-1][2] - (-340)) < 1.5  # автоуклон продлён до нового горизонта
    with pytest.raises(ValueError):
        planning.new_level(cfg, ramp, {"level": -340, "extend_ramp": False}, "ru")


def test_sublevels():
    cfg = mine_gen.mine_config()
    items = planning.generate_sublevels(cfg, mine_gen.ramp_axis(), -200, -300, None, "ru", existing_levels={-200, -225})
    assert sorted({w["level"] for w in items}) == [-300, -275, -250]


def test_designer_compare():
    cfg = mine_gen.mine_config()
    sysw = planning.new_level(cfg, mine_gen.ramp_axis(), {"level": -300}, "ru")
    system = [{**w, "id": i} for i, w in enumerate(sysw)]
    plan = []
    for w in sysw[:5]:
        plan.append({**w, "axis": [[p[0], p[1], p[2] + 3] for p in w["axis"]]})
    plan.append({"name": "Новая ниша", "type": "niche", "level": -300, "axis": [[0, 0, -300], [5, 0, -300]]})
    res = planning.compare_plan(system, plan)
    st = [r["status"] for r in res]
    assert st.count("shifted") == 5 and st.count("new") == 1 and st.count("missing") == len(system) - 5
    assert all(r["shift_m"] == pytest.approx(3.0, abs=0.3) for r in res if r["status"] == "shifted")


def test_import_formats(tmp_path):
    # STR
    pl = [{"name": "ПШ−1", "points": [[0, 0, -100], [10, 0, -100], [20, 5, -100]]}]
    s = importers.write_surpac_str(pl)
    p = importers.parse("a.str", s.encode())
    assert p["polylines"][0]["points"][2] == [20.0, 5.0, -100.0]
    # LAS
    pts = np.random.default_rng(0).uniform(0, 10, (500, 3))
    las = importers.write_las(pts)
    p = importers.parse("a.las", las)
    assert p["count"] == 500
    # PLY / XYZ
    import trimesh

    ply = trimesh.PointCloud(pts).export(file_type="ply")
    assert importers.parse("a.ply", ply)["count"] == 500
    assert importers.parse("a.xyz", "\n".join(" ".join(map(str, r)) for r in pts).encode())["count"] == 500
    # CSV лог станка и IREDES
    csv = "hole;collar_x;collar_y;toe_x;toe_y;length;drilled\n1;0;1;0.1;1.1;3.8;1\n2;1;1;1;1;3.7;0\n"
    p = importers.parse("log.csv", csv.encode())
    assert p["kind"] == "drill_log" and p["holes"][1]["drilled"] is False
    from core.mine_gen import _example_iredes

    p = importers.parse("log.xml", _example_iredes().encode())
    assert p["kind"] == "drill_log" and len(p["holes"]) == 5 and p["meta"]["EquipmentId"] == "Boomer №1"
    # OBJ
    obj = "v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n"
    assert importers.parse("a.obj", obj.encode())["kind"] == "mesh"


def test_dwg_conversion_available():
    import shutil

    if not shutil.which("dwg2dxf"):
        pytest.skip("LibreDWG не установлен (тест запускается в образе)")
    import subprocess

    r = subprocess.run(["dwg2dxf", "--version"], capture_output=True)
    assert r.returncode == 0


def test_scan_profiles_from_points():
    axis = [[0, 0, 0], [0, 50, 0]]
    sec = {"shape": "rect", "width": 5, "height": 5}
    scan = scans.gen_dev_scan(sec, 3.5, {}, np.random.default_rng(1), n_profiles=10, chainage0=10)
    pts = scans.dev_scan_to_points(scan, axis, density=4)
    profs = scans.profiles_from_points(pts, axis, 10, 13.5)
    assert len(profs) >= 4


def test_export_dxf_opens():
    import ezdxf

    data = exporters.workings_dxf([{"name": "X", "type": "fwd", "status": "planned", "axis": [[0, 0, 0], [10, 0, 0]],
                                    "section": {"area": 20}}])
    doc = ezdxf.read(io.StringIO(data.decode()))
    assert len(doc.modelspace().query("POLYLINE")) == 1
    assert g.format_chainage(1240) == "ПК 12+40"
