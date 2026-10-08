"""Планируемые выработки: мастер «Новый горизонт», подэтажи, ручное добавление, сравнение с планом проектировщиков."""
from __future__ import annotations

import math
import re
from typing import Any

import numpy as np

from . import geometry as g

DIRECTIONS = {
    "ru": {"N": "С", "S": "Ю", "E": "В", "W": "З"},
    "en": {"N": "N", "S": "S", "E": "E", "W": "W"},
    "es": {"N": "N", "S": "S", "E": "E", "W": "O"},
}

DEFAULT_TEMPLATES = {
    "ru": {"ramp": "Автоуклон №{n}", "access": "Заезд на гор. {гор}", "fwd": "ПШ{гор} ({напр})",
           "xc": "БДО {гор}.{n}", "sump": "Зумпф гор. {гор}", "raise": "ВВС гор. {гор}.{n}",
           "niche": "Ниша гор. {гор}.{n}", "other": "Выработка {n}"},
    "en": {"ramp": "Decline #{n}", "access": "Access L{гор}", "fwd": "FWD L{гор} ({напр})",
           "xc": "XC {гор}.{n}", "sump": "Sump L{гор}", "raise": "Vent raise L{гор}.{n}",
           "niche": "Niche L{гор}.{n}", "other": "Drive {n}"},
    "es": {"ramp": "Rampa N°{n}", "access": "Acceso Nv {гор}", "fwd": "Galería Nv {гор} ({напр})",
           "xc": "XC {гор}.{n}", "sump": "Pozo colector Nv {гор}", "raise": "Chimenea Nv {гор}.{n}",
           "niche": "Nicho Nv {гор}.{n}", "other": "Labor {n}"},
}

WORKING_TYPES = ("ramp", "access", "fwd", "xc", "raise", "sump", "niche", "other")
STATUSES = ("planned", "driving", "done", "closed")


def fmt_level(level: float) -> str:
    """-200 → «−200» (типографский минус, как в чертежах)."""
    v = int(round(level))
    return f"−{abs(v)}" if v < 0 else f"{v}"


def make_name(templates: dict, lang: str, wtype: str, level: float | None = None, n: int | None = None,
              direction: str | None = None) -> str:
    tpl = (templates.get(lang) or DEFAULT_TEMPLATES.get(lang) or DEFAULT_TEMPLATES["ru"]).get(wtype) \
        or DEFAULT_TEMPLATES["ru"][wtype]
    params = {"гор": fmt_level(level) if level is not None else "", "n": n if n is not None else "",
              "напр": DIRECTIONS.get(lang, DIRECTIONS["en"]).get(direction or "", direction or "")}
    params.update({"lvl": params["гор"], "dir": params["напр"]})
    try:
        return tpl.format(**params)
    except (KeyError, IndexError):
        return tpl


def normalize_name(name: str) -> str:
    s = name.lower().replace("−", "-").replace("—", "-").replace("е", "е")
    return re.sub(r"[\s_.()№#]+", "", s)


# ---------------- модель рудного тела ----------------
class OrebodyModel:
    """Крутопадающая жила: лежачий бок x_fw(y,z), горизонтальная мощность. Простирание — вдоль оси y."""

    def __init__(self, params: dict | None = None):
        p = params or {}
        self.x0 = float(p.get("x0", 100.0))
        self.dip = float(p.get("dip_deg", 70.0))
        self.y_min = float(p.get("y_min", 0.0))
        self.y_max = float(p.get("y_max", 400.0))
        self.t_mean = float(p.get("thickness_mean", 11.0))
        self.t_amp = float(p.get("thickness_amp", 3.0))
        self.undulation = float(p.get("undulation_amp", 3.0))
        self.z_top = float(p.get("z_top", -150.0))
        self.z_bottom = float(p.get("z_bottom", -340.0))

    def thickness(self, y: float) -> float:
        t = self.t_mean + self.t_amp * math.sin(2 * math.pi * y / 400 * 1.5 + 0.5)
        return max(self.t_mean - self.t_amp, min(self.t_mean + self.t_amp, t))

    def fw_x(self, y: float, z: float) -> float:
        return self.x0 + (-z) / math.tan(math.radians(self.dip)) + self.undulation * math.sin(y / 60.0)

    def hw_x(self, y: float, z: float) -> float:
        return self.fw_x(y, z) + self.thickness(y) / math.sin(math.radians(self.dip))

    def mesh(self, dy: float = 20, dz: float = 10) -> dict:
        ys = np.arange(self.y_min, self.y_max + 0.1, dy)
        zs = np.arange(self.z_bottom, self.z_top + 0.1, dz)
        verts: list[list[float]] = []
        for side in ("fw", "hw"):
            for z in zs:
                for y in ys:
                    x = self.fw_x(y, z) if side == "fw" else self.hw_x(y, z)
                    verts.append([round(x, 2), round(float(y), 2), round(float(z), 2)])
        ny, nz = len(ys), len(zs)
        faces: list[list[int]] = []
        for s in (0, 1):
            off = s * ny * nz
            for i in range(nz - 1):
                for j in range(ny - 1):
                    a = off + i * ny + j
                    faces += [[a, a + 1, a + ny + 1], [a, a + ny + 1, a + ny]]
        # торцы и кровля/подошва (замыкание)
        for i in range(nz - 1):
            for j in (0, ny - 1):
                a, b = i * ny + j, ny * nz + i * ny + j
                faces += [[a, b, b + ny], [a, b + ny, a + ny]]
        for i in (0, nz - 1):
            for j in range(ny - 1):
                a, b = i * ny + j, ny * nz + i * ny + j
                faces += [[a, a + 1, b + 1], [a, b + 1, b]]
        return {"vertices": verts, "faces": faces}

    def to_dict(self) -> dict:
        return {"type": "plane_vein", "x0": self.x0, "dip_deg": self.dip, "y_min": self.y_min, "y_max": self.y_max,
                "thickness_mean": self.t_mean, "thickness_amp": self.t_amp, "undulation_amp": self.undulation,
                "z_top": self.z_top, "z_bottom": self.z_bottom}


# ---------------- мастер «Новый горизонт» ----------------
def _w(name: str, wtype: str, level: float, axis: list, section: dict, **kw) -> dict:
    return {"name": name, "type": wtype, "level": level, "axis": [[round(c, 3) for c in p] for p in axis],
            "section": g.section_info(section), "status": kw.pop("status", "planned"),
            "source": kw.pop("source", "system"), **kw}


def default_sections(mine_cfg: dict) -> dict:
    s = mine_cfg.get("sections") or {}
    base = {
        "ramp": {"shape": "arch", "width": 5.5, "height": 5.5, "arch_height": 1.4},
        "access": {"shape": "arch", "width": 5.0, "height": 5.0, "arch_height": 1.25},
        "fwd": {"shape": "arch", "width": 5.0, "height": 5.0, "arch_height": 1.25},
        "xc": {"shape": "arch", "width": 4.5, "height": 4.5, "arch_height": 1.1},
        "raise": {"shape": "rect", "width": 3.0, "height": 3.0},
        "sump": {"shape": "rect", "width": 4.0, "height": 4.0},
        "niche": {"shape": "rect", "width": 4.0, "height": 4.0},
        "other": {"shape": "arch", "width": 4.5, "height": 4.5, "arch_height": 1.1},
    }
    base.update(s)
    return base


def extend_ramp(axis: list, level: float, gradient: float = 1 / 7, leg: float = 60.0, gap: float = 15.0) -> list[list[float]]:
    """Продление автоуклона ниже последней точки до отметки level: «змейка» из прямых по leg м с разворотами."""
    a = [list(map(float, p)) for p in axis]
    end, prev = a[-1], a[-2]
    dx, dy = end[0] - prev[0], end[1] - prev[1]
    n = math.hypot(dx, dy) or 1
    ux, uy = dx / n, dy / n
    px, py = -uy, ux
    pts = [end]
    x, y, z = end
    sign = 1
    while z > level + 1e-6:
        for i in range(1, 7):
            step = leg / 6
            x, y = x + ux * step * sign, y + uy * step * sign
            z = max(level - 1, z - step * gradient)
            pts.append([round(x, 2), round(y, 2), round(z, 2)])
            if z <= level:
                break
        if z <= level:
            break
        x, y = x + px * gap, y + py * gap
        z -= math.pi * gap / 2 * gradient
        pts.append([round(x, 2), round(y, 2), round(z, 2)])
        sign = -sign
    return pts


def new_level(mine_cfg: dict, ramp_axis: list, params: dict, lang: str = "ru") -> list[dict]:
    """Строит заезд, ПШ (С/Ю), БДО с шагом, зумпф/нишу/восстающий. Возвращает выработки (без сохранения)."""
    level = float(params["level"])
    templates = mine_cfg.get("name_templates") or DEFAULT_TEMPLATES
    secs = default_sections(mine_cfg)
    ob = OrebodyModel(mine_cfg.get("orebody_model"))
    out: list[dict] = []

    # 1. точка примыкания
    attach = params.get("attach") or {}
    if attach.get("point"):
        p0 = list(map(float, attach["point"]))
        ch = attach.get("chainage")
    elif attach.get("chainage") is not None:
        ch = float(attach["chainage"])
        p0 = g.point_at(ramp_axis, ch)
    else:
        found = g.point_at_elevation(ramp_axis, level)
        if not found:
            if level >= min(p[2] for p in ramp_axis) or not params.get("extend_ramp", True):
                raise ValueError("ramp_does_not_reach_level")
            ext = extend_ramp(ramp_axis, level)
            out.append(_w(make_name(templates, lang, "ramp", n=1) + f" ({fmt_level(level)})", "ramp", level, ext,
                          secs["ramp"], props={"role": "ramp_extension"}))
            p0, ch = list(ext[-1]), g.axis_length(ramp_axis) + g.axis_length(ext)
        else:
            p0, ch = found
    p0[2] = level

    # 2. заезд
    acc = params.get("access") or {}
    fwd = params.get("fwd") or {}
    offset = float(fwd.get("offset", mine_cfg.get("fwd_offset", 20)))
    y_j = p0[1]
    x_fwd_j = ob.fw_x(y_j, level) - offset
    if acc.get("azimuth") is not None and acc.get("length"):
        access_axis = g.by_azimuth(p0, float(acc["azimuth"]), float(acc["length"]), float(acc.get("gradient", 0)))
        junction = access_axis[-1]
    else:
        junction = [x_fwd_j, y_j, level]
        access_axis = [p0, junction]
    out.append(_w(make_name(templates, lang, "access", level), "access", level, access_axis,
                  acc.get("section") or secs["access"], attach_chainage=ch, attach_to="ramp", props={"role": "access"}))

    # 3. полевой штрек
    dirs = fwd.get("directions") or ["N", "S"]
    fwd_axes: dict[str, list] = {}
    for d in dirs:
        length = float(fwd.get(f"length_{d.lower()}", fwd.get("length", 180)))
        sign = 1 if d == "N" else -1
        pts = [junction]
        steps = max(1, int(length // 20))
        for i in range(1, steps + 1):
            y = junction[1] + sign * length * i / steps
            pts.append([ob.fw_x(y, level) - offset, y, level])
        fwd_axes[d] = pts
        out.append(_w(make_name(templates, lang, "fwd", level, direction=d), "fwd", level, pts,
                      fwd.get("section") or secs["fwd"], direction=d, attach_to="access"))

    # 4. буро-доставочные орты
    xc = params.get("xc") or {}
    if xc.get("enabled", True):
        spacing = float(xc.get("spacing", mine_cfg.get("xc_spacing", 20)))
        ang = math.radians(float(xc.get("angle", 90)))
        xc_len = xc.get("length", "to_hw")
        positions: list[tuple[float, str]] = []
        for d, pts in fwd_axes.items():
            L = g.axis_length(pts)
            k = 1
            while k * spacing <= L - 5:
                positions.append((k * spacing * (1 if d == "N" else -1), d))
                k += 1
        positions.sort(key=lambda t: t[0])
        for n, (dy, d) in enumerate(positions, start=1):
            y = junction[1] + dy
            start = [ob.fw_x(y, level) - offset + 2.5, y, level]
            if xc_len == "to_hw":
                length = ob.hw_x(y, level) + 3 - start[0]
            else:
                length = float(xc_len)
            end = [start[0] + length * math.sin(ang), y + length * math.cos(ang) * (1 if d == "N" else -1), level]
            out.append(_w(make_name(templates, lang, "xc", level, n=n), "xc", level, [start, end],
                          xc.get("section") or secs["xc"], seq=n, direction=d, attach_to="fwd"))

    # 5. дополнительно
    extras = params.get("extras") or {}
    if extras.get("sump", True):
        s0 = [junction[0] - 6, junction[1] - 8, level]
        out.append(_w(make_name(templates, lang, "sump", level), "sump", level,
                      [s0, [s0[0] - 12, s0[1], level - 1.2]], secs["sump"], attach_to="access"))
    if extras.get("niche"):
        n0 = [junction[0] - 3, junction[1] + 10, level]
        out.append(_w(make_name(templates, lang, "niche", level, n=1), "niche", level,
                      [n0, [n0[0] - 8, n0[1], level]], secs["niche"], attach_to="access"))
    if extras.get("raise"):
        end_n = fwd_axes.get("N", [junction])[-1]
        h = float(mine_cfg.get("sublevel_height", 25))
        out.append(_w(make_name(templates, lang, "raise", level, n=1), "raise", level,
                      [end_n, [end_n[0], end_n[1], level + h]], secs["raise"], attach_to="fwd"))
    return out


def generate_sublevels(mine_cfg: dict, ramp_axis: list, level_from: float, level_to: float,
                       params: dict | None = None, lang: str = "ru", existing_levels: set | None = None) -> list[dict]:
    h = float((params or {}).get("height") or mine_cfg.get("sublevel_height", 25))
    step = -h if level_to < level_from else h
    out: list[dict] = []
    lvl = level_from
    existing_levels = existing_levels or set()
    while (step < 0 and lvl >= level_to - 1e-6) or (step > 0 and lvl <= level_to + 1e-6):
        if round(lvl) not in existing_levels:
            p = dict(params or {})
            p["level"] = lvl
            out += new_level(mine_cfg, ramp_axis, p, lang)
        lvl += step
    return out


def manual_working(data: dict) -> dict:
    """Ручное добавление: точки оси, или старт + азимут + длина + уклон."""
    if data.get("axis"):
        axis = [list(map(float, p)) for p in data["axis"]]
    else:
        axis = g.by_azimuth(data["start"], float(data["azimuth"]), float(data["length"]), float(data.get("gradient", 0)))
    level = data.get("level")
    if level is None:
        level = round(axis[0][2])
    return _w(data["name"], data.get("type", "other"), level, axis,
              data.get("section") or {"shape": "arch", "width": 4.5, "height": 4.5, "arch_height": 1.1},
              status=data.get("status", "planned"))


# ---------------- сравнение с планом проектировщиков ----------------
def axis_distance(a: list, b: list, step: float = 2.0) -> tuple[float, float]:
    """Среднее и максимальное отклонение оси a от оси b (м)."""
    pts = g.resample(a, step)
    d = [g.chainage_of(b, p)[1] for p in pts]
    return float(np.mean(d)), float(np.max(d))


def compare_plan(system: list[dict], plan: list[dict], tol_match: float = 0.5, tol_geo: float = 15.0) -> list[dict]:
    """Сопоставление по имени, затем по геометрии. Статусы: match, shifted, new, missing."""
    by_name = {normalize_name(w["name"]): w for w in system}
    used: set = set()
    out: list[dict] = []
    for p in plan:
        cand = by_name.get(normalize_name(p["name"]))
        how = "name"
        if cand is None or cand["id"] in used:
            cand, how, best = None, "geometry", tol_geo
            for w in system:
                if w["id"] in used or (p.get("type") and w.get("type") and p["type"] != w["type"]):
                    continue
                mean, _ = axis_distance(p["axis"], w["axis"], step=5)
                if mean < best:
                    cand, best = w, mean
        if cand is None:
            out.append({"status": "new", "plan": p, "working_id": None, "shift_m": None})
            continue
        used.add(cand["id"])
        mean, mx = axis_distance(p["axis"], cand["axis"])
        status = "match" if mx <= tol_match else "shifted"
        out.append({"status": status, "plan": p, "working_id": cand["id"], "working_name": cand["name"],
                    "matched_by": how, "shift_m": round(mean, 2), "shift_max_m": round(mx, 2)})
    for w in system:
        if w["id"] not in used:
            out.append({"status": "missing", "plan": None, "working_id": w["id"], "working_name": w["name"],
                        "shift_m": None})
    return out


def describe(w: dict) -> dict[str, Any]:
    L = g.axis_length(w["axis"])
    return {"length": round(L, 1), "azimuth": round(g.azimuth(w["axis"][0], w["axis"][-1]), 1) if L else None,
            "volume": round(L * w.get("section", {}).get("area", g.section_area(w.get("section") or {})), 1)}
