"""Генератор демо-рудника  → пакет mines/default_mine/.

Крутопадающая жила (простирание С–Ю 400 м, падение 70° на восток, мощность 8–14 м, Cu-Au),
автоуклон №1 (1:7, спираль с разворотами), горизонты −200…−300 через 25 м, на каждом: заезд, ПШ (С) и (Ю),
БДО через 20 м, зумпф; камеры между БДО соседних подэтажей; зоны геологии; флот; персонал; типовые паспорта.
"""
from __future__ import annotations

import csv
import io
import math
from pathlib import Path

import numpy as np
import yaml

from . import geometry as g
from .planning import DEFAULT_TEMPLATES, OrebodyModel, fmt_level, new_level

LEVELS = [-200, -225, -250, -275, -300]
SUBLEVEL_H = 25
XC_SPACING = 20


def mine_config() -> dict:
    return {
        "code": "default_mine",
        "name": "Демо-рудник «Cerro Azul»",
        "country": "Chile",
        "timezone": "America/Santiago",
        "currency": "USD",
        "coordinate_system": "local mine grid (x — восток, y — север, z — абс. отметка, м)",
        "collar_elevation": 0.0,
        "location": {"lat": -27.37, "lon": -70.33},
        "default_language": "ru",
        "sublevel_height": SUBLEVEL_H,
        "xc_spacing": XC_SPACING,
        "fwd_offset": 20,
        # таблица смен и график ВР: окно ВР — последний час смены, взрыв + проветривание
        "shifts": {"table": [{"no": 1, "start": "08:00", "end": "20:00"}, {"no": 2, "start": "20:00", "end": "08:00"}],
                   "blast_windows": [{"shift": 1, "start": "19:00", "end": "20:00", "note": "blast_vent"},
                                     {"shift": 2, "start": "07:00", "end": "08:00", "note": "blast_vent"}],
                   "ventilation_min": 30, "reentry_min": 30, "blast_zone": "mine"},
        "densities": {"ore": 2.9, "waste": 2.7},
        "costs": {"haulage_per_t": 4.5, "processing_per_t": 14},
        "sections": {
            "ramp": {"shape": "arch", "width": 5.5, "height": 5.5, "arch_height": 1.4},
            "access": {"shape": "arch", "width": 5.0, "height": 5.0, "arch_height": 1.25},
            "fwd": {"shape": "arch", "width": 5.0, "height": 5.0, "arch_height": 1.25},
            "xc": {"shape": "arch", "width": 4.5, "height": 4.5, "arch_height": 1.1},
            "raise": {"shape": "rect", "width": 3.0, "height": 3.0},
            "sump": {"shape": "rect", "width": 4.0, "height": 4.0},
        },
        "standard_passports": {"ramp": "ТП-04", "access": "ТП-01", "fwd": "ТП-01", "xc": "ТП-03"},
        "name_templates": DEFAULT_TEMPLATES,
        "orebody_model": OrebodyModel({"x0": 100, "dip_deg": 70, "y_min": 0, "y_max": 400, "thickness_mean": 11,
                                       "thickness_amp": 3, "z_top": -150, "z_bottom": -330}).to_dict(),
        "grades": {"Cu": {"value": 1.4, "unit": "%"}, "Au": {"value": 2.1, "unit": "g/t"}},
    }


def ramp_axis() -> list[list[float]]:
    """Автоуклон: «беговая дорожка» — две прямые по 160 м (x=35 и x=65) и полуокружности R=15, уклон 1:7."""
    pts: list[list[float]] = []
    grad = 1 / 7
    s = 0.0
    x_e, x_w, y_s, y_n, R = 65.0, 35.0, 120.0, 280.0, 15.0
    cx = (x_e + x_w) / 2
    z_end = -312.0
    lap = 0
    while True:
        # на север по восточной прямой
        for y in np.arange(y_s, y_n, 10.0):
            pts.append([x_e, float(y), -s * grad])
            s += 10
        # разворот на север (против часовой: восток → запад)
        for k in range(0, 12):
            a = math.pi * k / 12
            pts.append([cx + R * math.cos(a), y_n + R * math.sin(a), -s * grad])
            s += math.pi * R / 12
        for y in np.arange(y_n, y_s, -10.0):
            pts.append([x_w, float(y), -s * grad])
            s += 10
        for k in range(0, 12):
            a = math.pi + math.pi * k / 12
            pts.append([cx + R * math.cos(a), y_s + R * math.sin(a), -s * grad])
            s += math.pi * R / 12
        lap += 1
        if -s * grad < z_end or lap > 12:
            break
    out = [p for p in pts if p[2] >= z_end]
    return [[round(c, 2) for c in p] for p in out]


def _status_for(w: dict) -> str:
    lvl, t, _name = w["level"], w["type"], w["name"]
    if lvl in (-200, -225):
        if t == "fwd" and lvl == -200 and w.get("direction") == "N":
            return "driving"
        if t == "xc" and lvl == -200 and w.get("seq", 0) >= 12:
            return "driving" if w["seq"] in (12, 13) else "planned"
        if t == "xc" and lvl == -225 and w.get("seq", 0) == 15:
            return "driving"
        return "done"
    if lvl == -250:
        if t in ("access", "sump"):
            return "done"
        if t == "fwd":
            return "driving"
        return "planned"
    if lvl == -275 and t == "access":
        return "driving"
    return "planned"


def generate(dest: Path, seed: int = 42) -> dict:
    """Создаёт пакет рудника в dest. Возвращает сводку."""
    rng = np.random.default_rng(seed)
    cfg = mine_config()
    dest.mkdir(parents=True, exist_ok=True)
    for sub in ("geometry", "geology", "passports", "drill_logs", "charge_logs", "scans"):
        (dest / sub).mkdir(exist_ok=True)
    ramp = ramp_axis()
    workings = [{"name": "Автоуклон №1", "type": "ramp", "level": None, "axis": ramp,
                 "section": g.section_info(cfg["sections"]["ramp"]), "status": "done", "source": "demo"}]
    for lvl in LEVELS:
        params = {"level": lvl, "fwd": {"directions": ["N", "S"], "length_n": 190, "length_s": 190},
                  "xc": {"spacing": XC_SPACING, "length": "to_hw"}, "extras": {"sump": True}}
        for w in new_level(cfg, ramp, params, "ru"):
            w["source"] = "demo"
            w["status"] = _status_for(w)
            workings.append(w)
    # текущее положение забоев в проходке (доля пройденной длины)
    for w in workings:
        if w["status"] == "driving":
            L = g.axis_length(w["axis"])
            w["face_chainage"] = round(L * (0.75 if w["type"] == "fwd" else 0.45), 1)

    ob = OrebodyModel(cfg["orebody_model"])
    stopes = []
    xcs = {(w["level"], w.get("seq")): w for w in workings if w["type"] == "xc"}
    for lvl_top, lvl_bot in zip(LEVELS[:-1], LEVELS[1:]):
        for (lv, seq), xc in sorted(xcs.items(), key=lambda kv: (kv[0][0], kv[0][1] or 0)):
            if lv != lvl_bot:
                continue
            y = xc["axis"][0][1]
            upper = xcs.get((lvl_top, seq))
            zc = (lvl_top + lvl_bot) / 2
            st_status = "planned"
            if lvl_bot == -225 and seq in (3, 4, 5):
                st_status = "mined"
            elif lvl_bot == -225 and seq in (6, 7, 8):
                st_status = "active"
            elif lvl_bot == -250 and seq in (4, 5):
                st_status = "active"
            stopes.append({
                "name": f"Камера {fmt_level(lvl_bot)}/{fmt_level(lvl_top)}.{seq}",
                "level_bottom": lvl_bot, "level_top": lvl_top, "drive": xc["name"],
                "upper_drive": upper["name"] if upper else None, "status": st_status,
                "geometry": {"y0": round(y - 7.5, 2), "y1": round(y + 7.5, 2),
                             "x_fw": round(ob.fw_x(y, zc), 2), "x_hw": round(ob.hw_x(y, zc), 2)},
                "grades": {"Cu": {"value": round(float(rng.normal(1.4, 0.25)), 2), "unit": "%"},
                           "Au": {"value": round(float(rng.normal(2.1, 0.4)), 2), "unit": "g/t"}},
            })

    # ---- файлы геометрии ----
    with open(dest / "mine.yaml", "w", encoding="utf-8") as f:
        yaml.safe_dump(cfg, f, allow_unicode=True, sort_keys=False)
    buf = io.StringIO()
    wr = csv.writer(buf, delimiter=";")
    wr.writerow(["name", "type", "level", "status", "direction", "seq", "section", "vertex", "x", "y", "z",
                 "face_chainage"])
    for w in workings:
        sec = w["section"]
        sec_s = f"{sec.get('shape')}:{sec.get('width')}x{sec.get('height')}:{sec.get('arch_height', '')}"
        for i, p in enumerate(w["axis"]):
            wr.writerow([w["name"], w["type"], w["level"] if w["level"] is not None else "", w["status"],
                         w.get("direction", ""), w.get("seq", "") or "", sec_s, i, *p,
                         w.get("face_chainage", "") if i == 0 else ""])
    (dest / "geometry" / "workings.csv").write_text(buf.getvalue(), encoding="utf-8")
    with open(dest / "geometry" / "stopes.yaml", "w", encoding="utf-8") as f:
        yaml.safe_dump({"stopes": stopes}, f, allow_unicode=True, sort_keys=False)
    mesh = ob.mesh()
    obj = ["# Orebody — demo vein (Cu-Au)"] + [f"v {x} {y} {z}" for x, y, z in mesh["vertices"]] + \
        [f"f {a + 1} {b + 1} {c + 1}" for a, b, c in mesh["faces"]]
    (dest / "geometry" / "orebody.obj").write_text("\n".join(obj) + "\n", encoding="utf-8")
    try:
        from .exporters import workings_dxf

        (dest / "geometry" / "workings.dxf").write_bytes(
            workings_dxf(workings, stopes=stopes, orebody=mesh, title=cfg["name"]))
    except Exception as e:  # DXF необязателен для загрузки
        (dest / "geometry" / "workings.dxf.error.txt").write_text(str(e))

    # ---- геология ----
    geology = {
        "default_rock": "ANDESITE",
        "ore_rock": "ORE_QZ_CU_AU",
        "assignments": [
            {"target": "interval", "name": "Обводнённый интервал", "working": "ПШ−250 (С)", "ch_from": 40,
             "ch_to": 120, "rock": "ANDESITE", "overrides": {"water": "flowing", "inflow_lpm": 45}},
            {"target": "interval", "name": "Трещиноватый интервал", "working": "ПШ−200 (С)", "ch_from": 100,
             "ch_to": 180, "rock": "ANDESITE_FRAC", "overrides": {"fracture_cat": 4}},
            {"target": "working", "name": "БДО −200.13 — контакт", "working": "БДО −200.13", "rock": "CONTACT_ALT"},
            {"target": "zone", "name": "Зона кливажа", "zone": {"min": [120, 290, -265], "max": [230, 370, -185]},
             "rock": "ANDESITE", "overrides": {"faults": [{"type": "cleavage", "azimuth": 20, "dip": 65}]}},
            {"target": "zone", "name": "Слабый висячий бок", "zone": {"min": [170, 190, -255], "max": [215, 270, -215]},
             "rock": "HW_WEAK", "overrides": {"weak_hw": True}},
            {"target": "zone", "name": "Крупноблочная зона", "zone": {"min": [130, 40, -215], "max": [180, 90, -190]},
             "rock": "DIORITE", "overrides": {"faults": [{"type": "blocky"}]}},
        ],
    }
    with open(dest / "geology" / "zones.yaml", "w", encoding="utf-8") as f:
        yaml.safe_dump(geology, f, allow_unicode=True, sort_keys=False)

    # ---- типовые паспорта (исходные данные; расчёт выполняется при загрузке) ----
    typical = {"passports": [
        {"number": "ТП-01", "name": "ПШ и заезды 5,0×5,0 (арка), f 8–12, сухо — АНФО", "working_type": "fwd",
         "section": cfg["sections"]["fwd"], "f_min": 8, "f_max": 12, "water": ["dry", "damp"],
         "explosive": "ANFO", "contour_explosive": "EMUL_SMOOTH_25", "hole_depth": 3.8, "rock_f": 10, "fracture_cat": 3},
        {"number": "ТП-02", "name": "ПШ 5,0×5,0 (арка), f 12–16 — эмульсия", "working_type": "fwd",
         "section": cfg["sections"]["fwd"], "f_min": 12, "f_max": 16, "water": ["dry", "damp", "dripping", "flowing", "inflow"],
         "explosive": "EMUL_BULK", "contour_explosive": "EMUL_SMOOTH_25", "hole_depth": 3.8, "rock_f": 14, "fracture_cat": 2},
        {"number": "ТП-03", "name": "БДО 4,5×4,5 (арка), f 8–16 — эмульсия", "working_type": "xc",
         "section": cfg["sections"]["xc"], "f_min": 8, "f_max": 16, "water": ["dry", "damp", "dripping", "flowing", "inflow"],
         "explosive": "EMUL_BULK", "contour_explosive": "EMUL_SMOOTH_25", "hole_depth": 3.6, "rock_f": 12, "fracture_cat": 3},
        {"number": "ТП-04", "name": "Автоуклон 5,5×5,5 (арка), f 12–16, обводнённый — эмульсия", "working_type": "ramp",
         "section": cfg["sections"]["ramp"], "f_min": 12, "f_max": 16, "water": ["dry", "damp", "dripping", "flowing", "inflow"],
         "explosive": "EMUL_BULK", "contour_explosive": "EMUL_SMOOTH_25", "hole_depth": 4.2, "rock_f": 14, "fracture_cat": 2},
    ], "rings": {"explosive": "EMUL_BULK", "hole_diameter": 89, "direction": "up", "standoff": 0.7}}
    with open(dest / "passports" / "typical.yaml", "w", encoding="utf-8") as f:
        yaml.safe_dump(typical, f, allow_unicode=True, sort_keys=False)

    # ---- флот и персонал ----
    # номер — уникальный в пределах рудника, название — как его называют на руднике; модель — из справочника
    # config/machine_models.yaml, отличия конкретной машины (износ) — в params
    fleet = [
        *[{"number": str(i), "name": f"Boomer №{i}", "type": "dev_drill", "model": "Boomer M2D", "manufacturer": "Epiroc",
           "year": 2019 + i % 4, "params": {"drill_rate_mph": 85 + 5 * i},
           "status": "repair" if i == 4 else "working", "engine_hours": 6200 + 830 * i} for i in range(1, 5)],
        {"number": "48", "name": "Axera №48", "type": "dev_drill", "model": "DD421", "manufacturer": "Sandvik", "year": 2023,
         "params": {}, "status": "working", "engine_hours": 2100},
        *[{"number": str(i), "name": f"Simba №{i}", "type": "ring_drill", "model": "Simba E7 C", "manufacturer": "Epiroc",
           "year": 2020, "params": {},
           "status": "working", "engine_hours": 9100 + 400 * (i - 21)} for i in (21, 22)],
        *[{"number": str(i), "name": f"ПДМ №{i}", "type": "lhd", "model": "Scooptram ST14", "manufacturer": "Epiroc",
           "year": 2021, "params": {}, "status": "working", "engine_hours": 7400} for i in (31, 32)],
        {"number": "41", "name": "Зарядная №41", "type": "charger", "model": "Charmec MC 605 VE", "manufacturer": "Normet",
         "year": 2022, "params": {}, "status": "working", "engine_hours": 3100},
        {"number": "51", "name": "Автосамосвал №51", "type": "aux", "model": "Minetruck MT42", "manufacturer": "Epiroc",
         "year": 2021, "params": {}, "status": "working", "engine_hours": 5300},
        {"number": "61", "name": "Boltec №61", "type": "bolter", "model": "Boltec M", "manufacturer": "Epiroc",
         "year": 2022, "params": {}, "status": "working", "engine_hours": 2800},
    ]
    # (ФИО, профессии, бригада, смена); допуски по умолчанию — из config/staff.yaml, личные — ниже
    names = [
        ("Иванов Василий Петрович", ["dev_driller"], "А", 1), ("García López Juan", ["dev_driller"], "А", 1),
        ("Петров Николай Сергеевич", ["dev_driller"], "А", 1), ("Muñoz Rojas Pedro", ["dev_driller", "ring_driller"], "Б", 2),
        ("Сидоров Алексей Иванович", ["dev_driller", "ring_driller"], "Б", 2), ("Soto Díaz Carlos", ["dev_driller"], "Б", 2),
        ("Kuznetsov Dmitry", ["ring_driller"], "А", 1), ("Fuentes Vera Diego", ["dev_driller"], "Б", 2),
        ("Смирнов Олег Викторович", ["blaster"], "А", 1), ("Contreras Silva Andrés", ["blaster"], "А", 1),
        ("Волков Игорь Андреевич", ["blaster"], "Б", 2), ("Reyes Morales Felipe", ["blaster"], "Б", 2),
        ("Попов Сергей Николаевич", ["lhd_operator"], "А", 1), ("Pérez González Luis", ["lhd_operator"], "А", 1),
        ("Lebedev Pavel", ["lhd_operator"], "Б", 2), ("Araya Castro Jorge", ["lhd_operator"], "Б", 2),
        ("Козлов Андрей Михайлович", ["foreman"], "А", 1), ("Vargas Núñez Miguel", ["foreman"], "Б", 2),
        ("Новикова Елена Сергеевна", ["surveyor"], "А", 1), ("Herrera Campos Sofía", ["engineer"], "А", 1),
        ("Морозов Артём Ильич", ["miner", "aux_operator"], "А", 1), ("Ortiz Lagos Tomás", ["trainee"], "А", 1),
        ("Белов Роман Олегович", ["bolter"], "А", 1),
    ]
    with open(Path(__file__).resolve().parents[2] / "config" / "staff.yaml", encoding="utf-8") as f:
        prof_permit = {p["code"]: p.get("permits", []) for p in yaml.safe_load(f)["professions"]}
    personal = {
        # горнорабочий: Axera DD421 + бурение забоя + вспомогательное оборудование
        21: [{"kind": "machine", "target": "model:Sandvik/DD421"}, {"kind": "work", "target": "drilling"}],
        # стажёр бурильщика — работает только с наставником (Иванов, таб. 1001)
        22: [{"kind": "machine", "target": "dev_drill"}, {"kind": "work", "target": "drilling"}],
    }
    staff = []
    for i, (fio, profs, crew, shift) in enumerate(names, start=1):
        permits, seen = [], set()
        for d in [x for c in profs for x in prof_permit.get(c, [])] + personal.get(i, []):
            if (d["kind"], d["target"]) in seen:
                continue
            seen.add((d["kind"], d["target"]))
            days = 400 + i * 13
            if i == 2 and d["target"] == "dev_drill":
                days = 9    # истекает через 9 дней — подсветка
            if i == 8 and d["target"] == "dev_drill":
                days = -5   # просрочен — запрет назначения
            permits.append({**d, "days_valid": days, "number": f"{100 + i}/{24 + i % 3}"})
        person = {"full_name": fio, "tab_no": f"{1000 + i}", "profession": profs[0], "professions": profs, "crew": crew,
                  "shift": shift, "permits": permits}
        if "trainee" in profs:
            person["mentor_tab"] = "1001"
        staff.append(person)
    with open(dest / "fleet.yaml", "w", encoding="utf-8") as f:
        yaml.safe_dump({"fleet": fleet}, f, allow_unicode=True, sort_keys=False)
    with open(dest / "staff.yaml", "w", encoding="utf-8") as f:
        yaml.safe_dump({"staff": staff}, f, allow_unicode=True, sort_keys=False)

    # ---- примеры файлов станков и сканов (для проверки импорта) ----
    (dest / "drill_logs" / "example_boomer_iredes.xml").write_text(_example_iredes(), encoding="utf-8")
    (dest / "drill_logs" / "example_boomer.csv").write_text(_example_drill_csv(), encoding="utf-8")
    (dest / "charge_logs" / "README.txt").write_text("Журналы заряжания: CSV hole;explosive;kg;length;stemming;"
                                                      "detonator;delay_ms;status\n", encoding="utf-8")
    (dest / "scans" / "README.txt").write_text("Облака точек (LAS/LAZ/E57/PLY/XYZ) забоев и камер (CMS).\n",
                                               encoding="utf-8")
    fwd = next(w for w in workings if w["name"] == "ПШ−200 (С)")
    from .scans import dev_scan_to_points, gen_dev_scan

    scan = gen_dev_scan(fwd["section"], 3.4, {"cleavage": "medium"}, rng, n_profiles=8,
                        chainage0=fwd["face_chainage"] - 3.4)
    pts = dev_scan_to_points(scan, fwd["axis"])
    np.savetxt(dest / "scans" / "example_face_PSh-200N.xyz", pts, fmt="%.3f")
    return {"workings": len(workings), "stopes": len(stopes), "fleet": len(fleet), "staff": len(staff),
            "levels": LEVELS, "path": str(dest)}


def _example_iredes() -> str:
    holes = []
    for i in range(1, 6):
        holes.append(f"""    <Hole>
      <HoleId>{i}</HoleId>
      <HoleStartPoint><PointX>{-1.5 + i * 0.5:.2f}</PointX><PointY>0.00</PointY><PointZ>{1.2 + 0.3 * i:.2f}</PointZ></HoleStartPoint>
      <HoleEndPoint><PointX>{-1.5 + i * 0.5 + 0.05:.2f}</PointX><PointY>3.78</PointY><PointZ>{1.2 + 0.3 * i + 0.04:.2f}</PointZ></HoleEndPoint>
      <HoleLength>3.78</HoleLength>
      <HoleDiameter>45</HoleDiameter>
      <DrillStartTime>2026-10-05T10:{10 + i:02d}:00Z</DrillStartTime>
    </Hole>""")
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!-- Пример отчёта бурения в стиле IREDES (Drill Plan / Quality Log), упрощённо -->
<IREDES>
  <DRPQualityLog>
    <EquipmentId>Boomer №1</EquipmentId>
    <Operator>1001</Operator>
    <WorkSite>ПШ−200 (С)</WorkSite>
{chr(10).join(holes)}
  </DRPQualityLog>
</IREDES>
"""


def _example_drill_csv() -> str:
    rows = ["hole;collar_x;collar_y;toe_x;toe_y;length;drilled"]
    for i in range(1, 6):
        rows.append(f"{i};{-1.5 + i * 0.5:.2f};{1.2 + 0.3 * i:.2f};{-1.45 + i * 0.5:.2f};{1.24 + 0.3 * i:.2f};3.78;1")
    return "\n".join(rows) + "\n"
