"""Импорт форматов: DXF, DWG (через LibreDWG dwg2dxf), Surpac STR/DTM, CSV, облака точек LAS/LAZ/E57/PLY/XYZ,
OBJ/STL, логи станков IREDES XML и CSV. Результат — нейтральные структуры: polylines, meshes, points, holes."""
from __future__ import annotations

import csv
import io
import os
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np

POINT_FORMATS = {"las", "laz", "e57", "ply", "xyz", "pts", "txt"}
MESH_FORMATS = {"obj", "stl"}
SUPPORTED = {"dxf", "dwg", "str", "dtm", "csv", "xml", *POINT_FORMATS, *MESH_FORMATS}


def detect_format(filename: str) -> str:
    ext = Path(filename).suffix.lower().lstrip(".")
    return "xml" if ext in ("iredes",) else ext


def parse(filename: str, data: bytes, max_points: int = 400_000) -> dict:
    fmt = detect_format(filename)
    if fmt == "dxf":
        return parse_dxf(data)
    if fmt == "dwg":
        return parse_dxf(dwg_to_dxf(data))
    if fmt == "str":
        return parse_surpac_str(data.decode("utf-8", "replace"))
    if fmt == "dtm":
        return {"format": "dtm", "note": "surpac_dtm_needs_str", **parse_surpac_dtm(data.decode("utf-8", "replace"))}
    if fmt == "csv":
        return parse_csv(data.decode("utf-8-sig", "replace"))
    if fmt == "xml":
        return parse_iredes(data)
    if fmt in POINT_FORMATS:
        pts = read_points(fmt, data)
        if len(pts) > max_points:
            idx = np.random.default_rng(0).choice(len(pts), max_points, replace=False)
            pts = pts[idx]
        return {"format": fmt, "kind": "points", "count": int(len(pts)), "points": pts,
                "bbox": {"min": pts.min(axis=0).round(2).tolist(), "max": pts.max(axis=0).round(2).tolist()} if len(pts) else None}
    if fmt in MESH_FORMATS:
        import trimesh

        m = trimesh.load(io.BytesIO(data), file_type=fmt, force="mesh")
        return {"format": fmt, "kind": "mesh", "meshes": [{"layer": "MESH", "vertices": m.vertices.round(3).tolist(),
                                                          "faces": m.faces.tolist()}]}
    raise ValueError(f"unsupported_format:{fmt}")


# ---------------- DXF / DWG ----------------
def dwg_to_dxf(data: bytes) -> bytes:
    with tempfile.TemporaryDirectory() as td:
        src, dst = os.path.join(td, "in.dwg"), os.path.join(td, "out.dxf")
        Path(src).write_bytes(data)
        r = subprocess.run(["dwg2dxf", "-y", "-o", dst, src], capture_output=True, timeout=120)
        if not os.path.exists(dst):
            raise ValueError("dwg_convert_failed: " + r.stderr.decode(errors="replace")[-300:])
        return Path(dst).read_bytes()


def parse_dxf(data: bytes) -> dict:
    import ezdxf
    from ezdxf import recover

    try:
        doc = ezdxf.read(io.StringIO(data.decode("utf-8", "replace")))
    except Exception:
        doc, _ = recover.read(io.BytesIO(data))
    msp = doc.modelspace()
    polylines, meshes, texts = [], [], []
    for e in msp:
        t = e.dxftype()
        layer = e.dxf.layer
        name = ""
        if e.has_xdata("DIGITAL_MINE"):
            xd = e.get_xdata("DIGITAL_MINE")
            name = next((v for c, v in xd if c == 1000), "")
        if t == "POLYLINE" and not e.is_poly_face_mesh and not e.is_polygon_mesh:
            pts = [list(v.dxf.location.xyz) for v in e.vertices]
            polylines.append({"layer": layer, "name": name, "points": pts})
        elif t == "LWPOLYLINE":
            z = e.dxf.elevation if e.dxf.hasattr("elevation") else 0
            pts = [[p[0], p[1], z] for p in e.get_points("xy")]
            if e.closed:
                pts.append(pts[0])
            polylines.append({"layer": layer, "name": name, "points": pts})
        elif t == "LINE":
            polylines.append({"layer": layer, "name": name, "points": [list(e.dxf.start.xyz), list(e.dxf.end.xyz)]})
        elif t == "3DFACE":
            vs = [list(e.dxf.get(f"vtx{i}").xyz) for i in range(4)]
            meshes.append({"layer": layer, "vertices": vs, "faces": [[0, 1, 2], [0, 2, 3]]})
        elif t == "MESH":
            meshes.append({"layer": layer, "vertices": [list(v) for v in e.vertices],
                           "faces": [list(f) for f in e.faces]})
        elif t in ("TEXT", "MTEXT"):
            ins = e.dxf.insert.xyz
            txt = e.dxf.text if t == "TEXT" else e.text
            texts.append({"layer": layer, "text": txt, "point": list(ins)})
    # подписи → имена ближайших полилиний без имени
    for pl in polylines:
        if pl["name"] or not texts:
            continue
        mid = np.asarray(pl["points"][len(pl["points"]) // 2])
        best = min(texts, key=lambda tx: np.linalg.norm(np.asarray(tx["point"]) - mid))
        if np.linalg.norm(np.asarray(best["point"]) - mid) < 15:
            pl["name"] = best["text"]
    layers = sorted({p["layer"] for p in polylines} | {m["layer"] for m in meshes})
    return {"format": "dxf", "kind": "cad", "polylines": polylines, "meshes": meshes, "texts": texts, "layers": layers,
            "bbox": _bbox([p for pl in polylines for p in pl["points"]])}


def _bbox(pts) -> dict | None:
    if not pts:
        return None
    a = np.asarray(pts, dtype=float)
    return {"min": a.min(axis=0).round(2).tolist(), "max": a.max(axis=0).round(2).tolist()}


# ---------------- Surpac ----------------
def parse_surpac_str(text: str) -> dict:
    """STR: заголовок, axis-строка, далее «номер_стринга, Y, X, Z, описание…»; номер 0 — разрыв сегмента."""
    lines = text.splitlines()
    polylines: list[dict] = []
    cur: list = []
    cur_id = None
    cur_name = ""
    for ln in lines[2:]:
        parts = [p.strip() for p in ln.split(",")]
        if len(parts) < 4:
            continue
        try:
            sid = int(float(parts[0]))
            y, x, z = float(parts[1]), float(parts[2]), float(parts[3])
        except ValueError:
            continue
        if sid == 0:
            if cur:
                polylines.append({"layer": f"STRING_{cur_id}", "name": cur_name, "points": cur})
            cur, cur_id = [], None
            continue
        if cur_id is None:
            cur_name = parts[4] if len(parts) > 4 else ""
        cur_id = sid
        cur.append([x, y, z])
    if cur:
        polylines.append({"layer": f"STRING_{cur_id}", "name": cur_name, "points": cur})
    return {"format": "str", "kind": "cad", "polylines": polylines, "meshes": [], "texts": [],
            "layers": sorted({p["layer"] for p in polylines}), "bbox": _bbox([p for pl in polylines for p in pl["points"]])}


def parse_surpac_dtm(text: str) -> dict:
    """DTM: треугольники «TRISOLATION»/номера точек STR. Без парного STR сохраняем как ссылку."""
    tri = []
    for ln in text.splitlines():
        parts = [p.strip() for p in ln.split(",")]
        if len(parts) >= 4 and parts[0].isdigit():
            try:
                tri.append([int(parts[1]) - 1, int(parts[2]) - 1, int(parts[3]) - 1])
            except ValueError:
                pass
    return {"kind": "dtm", "triangles": tri, "polylines": [], "meshes": []}


def write_surpac_str(polylines: list[dict], title: str = "digital_mine") -> str:
    out = [f"{title},06-Oct-26,,", "0, 0.000, 0.000, 0.000, 0.000, 0.000, 0.000"]
    for i, pl in enumerate(polylines, start=1):
        for k, (x, y, z) in enumerate(pl["points"]):
            desc = f",{pl.get('name', '')}" if k == 0 else ""
            out.append(f"{i}, {y:.3f}, {x:.3f}, {z:.3f}{desc}")
        out.append("0, 0.000, 0.000, 0.000,")
    out.append("0, 0.000, 0.000, 0.000, END")
    return "\n".join(out) + "\n"


# ---------------- CSV ----------------
def parse_csv(text: str) -> dict:
    sample = text[:2000]
    sep = ";" if sample.count(";") >= sample.count(",") else ","
    rows = list(csv.DictReader(io.StringIO(text), delimiter=sep))
    cols = [c.strip().lower() for c in (rows[0].keys() if rows else [])]
    if {"hole", "length"} <= set(cols) or {"hole", "toe_x"} <= set(cols):
        return {"format": "csv", "kind": "drill_log", "holes": [_drill_row(r) for r in rows], "columns": cols}
    if {"name", "x", "y", "z"} <= set(cols):
        groups: dict[str, list] = {}
        meta: dict[str, dict] = {}
        for r in rows:
            r = {k.strip().lower(): v for k, v in r.items()}
            groups.setdefault(r["name"], []).append([float(r["x"]), float(r["y"]), float(r["z"])])
            meta.setdefault(r["name"], {k: r.get(k) for k in ("type", "level", "status", "section", "direction", "seq",
                                                              "face_chainage") if r.get(k)})
            if r.get("face_chainage"):
                meta[r["name"]]["face_chainage"] = r["face_chainage"]
        pls = [{"layer": meta[n].get("type", "CSV"), "name": n, "points": p, "meta": meta[n]} for n, p in groups.items()]
        return {"format": "csv", "kind": "cad", "polylines": pls, "meshes": [], "texts": [],
                "layers": sorted({p["layer"] for p in pls}), "bbox": _bbox([p for pl in pls for p in pl["points"]])}
    if {"x", "y", "z"} <= set(cols):
        pts = np.array([[float(r["x"]), float(r["y"]), float(r["z"])] for r in
                        ({k.strip().lower(): v for k, v in r.items()} for r in rows)])
        return {"format": "csv", "kind": "points", "count": len(pts), "points": pts, "bbox": _bbox(pts)}
    return {"format": "csv", "kind": "table", "rows": rows[:5000], "columns": cols}


def _drill_row(r: dict) -> dict:
    r = {k.strip().lower(): (v or "").strip() for k, v in r.items()}

    def f(k, d=None):
        try:
            return float(r[k]) if r.get(k) not in (None, "") else d
        except ValueError:
            return d

    return {"id": int(float(r.get("hole") or 0)), "collar_x": f("collar_x"), "collar_y": f("collar_y"),
            "toe_x": f("toe_x"), "toe_y": f("toe_y"), "length": f("length"),
            "drilled": r.get("drilled", "1") not in ("0", "false", "no", "нет")}


# ---------------- облака точек ----------------
def read_points(fmt: str, data: bytes) -> np.ndarray:
    if fmt in ("las", "laz"):
        import laspy

        las = laspy.read(io.BytesIO(data))
        return np.vstack([las.x, las.y, las.z]).T.astype(float)
    if fmt == "e57":
        import pye57

        with tempfile.NamedTemporaryFile(suffix=".e57") as tf:
            tf.write(data)
            tf.flush()
            e = pye57.E57(tf.name)
            arrs = []
            for i in range(e.scan_count):
                d = e.read_scan(i, ignore_missing_fields=True)
                arrs.append(np.vstack([d["cartesianX"], d["cartesianY"], d["cartesianZ"]]).T)
            return np.vstack(arrs).astype(float)
    if fmt == "ply":
        import trimesh

        m = trimesh.load(io.BytesIO(data), file_type="ply")
        return np.asarray(m.vertices, dtype=float)
    # xyz / pts / txt: первые три числа строки
    rows = []
    for ln in data.decode("utf-8", "replace").splitlines():
        parts = ln.replace(",", " ").replace(";", " ").split()
        if len(parts) >= 3:
            try:
                rows.append([float(parts[0]), float(parts[1]), float(parts[2])])
            except ValueError:
                continue
    return np.asarray(rows, dtype=float)


def write_las(points: np.ndarray) -> bytes:
    import laspy

    hdr = laspy.LasHeader(point_format=3, version="1.2")
    hdr.offsets = points.min(axis=0)
    hdr.scales = np.array([0.001, 0.001, 0.001])
    las = laspy.LasData(hdr)
    las.x, las.y, las.z = points[:, 0], points[:, 1], points[:, 2]
    buf = io.BytesIO()
    las.write(buf)
    return buf.getvalue()


# ---------------- IREDES ----------------
def parse_iredes(data: bytes) -> dict:
    """Упрощенный разбор IREDES (Drill Plan / Quality Log): скважины с началом/концом, длиной, диаметром."""
    root = ET.fromstring(data)

    def strip(tag):
        return tag.split("}", 1)[-1]

    holes = []
    meta = {}
    for el in root.iter():
        t = strip(el.tag)
        if t in ("EquipmentId", "Operator", "WorkSite") and el.text:
            meta[t] = el.text.strip()
        if t == "Hole":
            h = {"drilled": True}
            for ch in el.iter():
                ct = strip(ch.tag)
                if ct == "HoleId" and ch.text:
                    h["id"] = int(float(ch.text))
                elif ct in ("HoleStartPoint", "HoleEndPoint"):
                    xyz = {strip(c.tag): float(c.text) for c in ch if c.text}
                    pfx = "collar" if ct == "HoleStartPoint" else "toe"
                    # координаты забоя: X — поперек, Z — вверх; Y — вдоль оси (глубина)
                    h[f"{pfx}_x"], h[f"{pfx}_y"] = xyz.get("PointX"), xyz.get("PointZ")
                    h[f"{pfx}_depth"] = xyz.get("PointY")
                elif ct == "HoleLength" and ch.text:
                    h["length"] = float(ch.text)
                elif ct == "HoleDiameter" and ch.text:
                    h["diameter"] = float(ch.text)
                elif ct == "DrillStartTime" and ch.text:
                    h["ts"] = ch.text
            holes.append(h)
    return {"format": "iredes", "kind": "drill_log", "holes": holes, "meta": meta}


# ---------------- сопоставление слоев ----------------
def guess_type(layer: str, name: str = "") -> str:
    s = f"{layer} {name}".lower()
    rules = [("ramp", ("ramp", "decline", "уклон", "rampa")), ("access", ("access", "заезд", "acceso")),
             ("fwd", ("fwd", "пш", "штрек", "drive", "galer")), ("xc", ("xc", "бдо", "орт", "cross")),
             ("raise", ("raise", "восст", "вв", "chimen")), ("sump", ("sump", "зумпф")), ("niche", ("niche", "ниш"))]
    for t, keys in rules:
        if any(k in s for k in keys):
            return t
    return "other"


def polylines_to_workings(parsed: dict, layer_map: dict[str, str] | None = None, offset: list | None = None,
                          default_section: dict | None = None) -> list[dict]:
    from .geometry import section_info

    layer_map = layer_map or {}
    off = np.asarray(offset or [0, 0, 0], dtype=float)
    out = []
    for i, pl in enumerate(parsed.get("polylines", []), start=1):
        t = layer_map.get(pl["layer"]) or pl.get("meta", {}).get("type") or guess_type(pl["layer"], pl.get("name", ""))
        if t == "skip":
            continue
        pts = (np.asarray(pl["points"], dtype=float) + off).round(3).tolist()
        sec = default_section or {"shape": "arch", "width": 4.5, "height": 4.5, "arch_height": 1.1}
        meta = pl.get("meta") or {}
        if meta.get("section"):
            try:
                shape, wh, ah = meta["section"].split(":")
                w_, h_ = wh.split("x")
                sec = {"shape": shape, "width": float(w_), "height": float(h_)}
                if ah:
                    sec["arch_height"] = float(ah)
            except ValueError:
                pass
        lvl = meta.get("level")
        out.append({"name": pl.get("name") or f"{t.upper()}-{i}", "type": t,
                    "level": float(lvl) if lvl not in (None, "") else round(float(np.median([p[2] for p in pts]))),
                    "axis": pts, "section": section_info(sec), "status": meta.get("status", "planned"),
                    "direction": meta.get("direction", ""), "seq": int(meta["seq"]) if meta.get("seq") else None,
                    "face_chainage": float(meta["face_chainage"]) if meta.get("face_chainage") else None})
    return out
