"""Экспорт: DXF (выработки, паспорта, веера), CSV. DXF R2013 открывают Deswik, Micromine, Datamine, Surpac, Vulcan."""
from __future__ import annotations

import io

import ezdxf
from ezdxf.enums import TextEntityAlignment

STATUS_COLOR = {"planned": 5, "driving": 2, "done": 3, "closed": 8}  # ACI: синий, желтый, зеленый, серый
TYPE_COLOR = {"empty": 8, "cut": 1, "stoping": 3, "helper": 4, "contour": 5, "lifter": 6}


def _doc(title: str):
    doc = ezdxf.new("R2013", setup=True)
    doc.header["$INSUNITS"] = 6  # метры
    doc.header["$PROJECTNAME"] = title[:255]
    return doc


def _bytes(doc) -> bytes:
    s = io.StringIO()
    doc.write(s)
    return s.getvalue().encode("utf-8")


def workings_dxf(workings: list[dict], stopes: list[dict] | None = None, orebody: dict | None = None,
                 title: str = "digital_mine") -> bytes:
    """Оси выработок — 3D-полилинии на слоях WORKINGS_<тип>, подписи — TEXT, камеры — 3DFACE, рудное тело — MESH."""
    doc = _doc(title)
    msp = doc.modelspace()
    for w in workings:
        layer = f"WORKINGS_{w['type'].upper()}"
        if layer not in doc.layers:
            doc.layers.add(layer)
        pts = [tuple(p) for p in w["axis"]]
        if len(pts) < 2:
            continue
        pl = msp.add_polyline3d(pts, dxfattribs={"layer": layer, "color": STATUS_COLOR.get(w.get("status"), 7)})
        pl.set_xdata("DIGITAL_MINE", [(1000, w["name"]), (1000, w.get("status", "")),
                                      (1040, float(w.get("section", {}).get("area") or 0))])
        mid = pts[len(pts) // 2]
        msp.add_text(w["name"], height=2.5, dxfattribs={"layer": "LABELS"}).set_placement(
            (mid[0], mid[1], mid[2] + 3), align=TextEntityAlignment.MIDDLE_CENTER)
    if stopes:
        if "STOPES" not in doc.layers:
            doc.layers.add("STOPES", color=30)
        for s in stopes:
            g = s["geometry"]
            x0, x1, y0, y1, z0, z1 = g["x_fw"], g["x_hw"], g["y0"], g["y1"], s["level_bottom"], s["level_top"]
            v = [(x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0), (x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)]
            for f in ((0, 1, 2, 3), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)):
                msp.add_3dface([v[i] for i in f], dxfattribs={"layer": "STOPES"})
    if orebody and orebody.get("vertices"):
        if "OREBODY" not in doc.layers:
            doc.layers.add("OREBODY", color=1)
        mesh = msp.add_mesh(dxfattribs={"layer": "OREBODY"})
        with mesh.edit_data() as md:
            md.vertices = [tuple(v) for v in orebody["vertices"]]
            md.faces = [tuple(f) for f in orebody["faces"]]
    return _bytes(doc)


def passport_dxf(result: dict, title: str = "") -> bytes:
    """Вид на забой: контур, шпуры (окружности по типам), номера и замедления."""
    doc = _doc(title or "passport")
    msp = doc.modelspace()
    for name, col in [("CONTOUR", 7), ("HOLES", 3), ("TEXT", 7)] + [(f"HOLES_{t.upper()}", c) for t, c in TYPE_COLOR.items()]:
        if name not in doc.layers:
            doc.layers.add(name, color=col)
    msp.add_lwpolyline([tuple(p) for p in result["contour"]], close=True, dxfattribs={"layer": "CONTOUR"})
    for h in result["holes"]:
        r = h.get("diameter", 45) / 2000
        layer = f"HOLES_{h['type'].upper()}"
        msp.add_circle((h["x"], h["y"]), max(r, 0.02), dxfattribs={"layer": layer})
        label = f"{h['id']}" + (f"/{h['delay_ms']}" if h.get("delay_ms") is not None and h["type"] != "empty" else "")
        msp.add_text(label, height=0.08, dxfattribs={"layer": "TEXT"}).set_placement((h["x"] + 0.06, h["y"] + 0.06))
    if title:
        msp.add_text(title, height=0.2, dxfattribs={"layer": "TEXT"}).set_placement(
            (min(p[0] for p in result["contour"]), -0.6))
    return _bytes(doc)


def rings_dxf(res: dict, title: str = "") -> bytes:
    """Веера в 3D: скважины — линии от устья до конца, заряженная часть — отдельный слой."""
    doc = _doc(title or "rings")
    msp = doc.modelspace()
    for name, col in (("RING_HOLES", 3), ("RING_CHARGE", 1), ("STOPE_SECTION", 7), ("TEXT", 7)):
        doc.layers.add(name, color=col)
    cu, cv = res["collar"]
    for r in res["rings"]:
        x = r["x"]
        msp.add_polyline3d([(x, p[0], p[1]) for p in res["section"]], dxfattribs={"layer": "STOPE_SECTION"})
        for h in r["holes"]:
            a, b = (x, cu, cv), (x, h["u"], h["v"])
            msp.add_line(a, b, dxfattribs={"layer": "RING_HOLES"})
            L = h["length"] or 1
            t = h["uncharged"] / L
            c0 = (x, cu + (h["u"] - cu) * t, cv + (h["v"] - cv) * t)
            msp.add_line(c0, b, dxfattribs={"layer": "RING_CHARGE"})
        msp.add_text(f"R{r['no']}", height=0.5, dxfattribs={"layer": "TEXT"}).set_placement((x, cu, cv - 1.0))
    return _bytes(doc)


def table_csv(rows: list[dict], columns: list[str] | None = None, sep: str = ";") -> str:
    if not rows:
        return ""
    cols = columns or list(rows[0].keys())
    out = [sep.join(cols)]
    for r in rows:
        out.append(sep.join("" if r.get(c) is None else str(r.get(c)).replace(sep, ",") for c in cols))
    return "\n".join(out) + "\n"
