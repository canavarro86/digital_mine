"""SVG-чертежи для PDF: вид на забой, разрез А-А, веер. Подписи передаются уже переведенными."""
from __future__ import annotations

import html
import math

COLORS = {"empty": "#ffffff", "cut": "#d62728", "stoping": "#2ca02c", "helper": "#17becf", "contour": "#1f77b4",
          "lifter": "#9467bd"}


def _esc(s) -> str:
    return html.escape(str(s))


def face_view(result: dict, labels: dict, size: int = 520) -> str:
    contour = result["contour"]
    xs = [p[0] for p in contour]
    ys = [p[1] for p in contour]
    minx, maxx, miny, maxy = min(xs) - 0.6, max(xs) + 0.6, min(ys) - 0.6, max(ys) + 0.6
    sc = size / max(maxx - minx, maxy - miny)
    W, H = (maxx - minx) * sc, (maxy - miny) * sc

    def X(x):
        return (x - minx) * sc

    def Y(y):
        return H - (y - miny) * sc

    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W:.0f}" height="{H:.0f}" viewBox="0 0 {W:.0f} {H:.0f}" '
             f'font-family="DejaVu Sans" font-size="9">']
    pts = " ".join(f"{X(x):.1f},{Y(y):.1f}" for x, y in contour)
    parts.append(f'<polygon points="{pts}" fill="#f6f6f6" stroke="#000" stroke-width="1.6"/>')
    # оси
    parts.append(f'<line x1="{X(0):.1f}" y1="0" x2="{X(0):.1f}" y2="{H:.0f}" stroke="#999" stroke-dasharray="6,3"/>')
    for h in result["holes"]:
        r = max(3.0, h.get("diameter", 45) / 1000 * sc / 2 * 2.2)
        fill = COLORS.get(h["type"], "#555")
        stroke = "#000"
        if h.get("flag") or h.get("zone") in ("overloaded", "underloaded"):
            stroke = "#ff7f0e"
        if h.get("not_drilled"):
            fill, stroke = "#ffffff", "#bbbbbb"
        parts.append(f'<circle cx="{X(h["x"]):.1f}" cy="{Y(h["y"]):.1f}" r="{r:.1f}" fill="{fill}" stroke="{stroke}" '
                     f'stroke-width="1"/>')
        if h["type"] != "empty":
            lab = f'{h["id"]}'
            if h.get("delay_ms") is not None:
                lab += f'/{h["delay_ms"]}'
            parts.append(f'<text x="{X(h["x"]) + r + 1:.1f}" y="{Y(h["y"]) - r:.1f}" font-size="7.5">{_esc(lab)}</text>')
    # размеры
    p = result["params"]
    parts.append(f'<text x="{X(0):.1f}" y="{H - 4:.0f}" text-anchor="middle">B = {p["width"]:.2f} {labels.get("m", "m")}</text>')
    parts.append(f'<text x="4" y="{Y(p["height"] / 2):.0f}">H = {p["height"]:.2f}</text>')
    parts.append("</svg>")
    return "".join(parts)


def section_aa(result: dict, labels: dict, width: int = 520, height: int = 200) -> str:
    """Разрез А-А: шпуры по высоте, длины и углы (контурные/подошвенные с наклоном)."""
    depth = float(result["input"].get("hole_depth", 3.8)) + 0.6
    p = result["params"]
    hmax = p["height"] + 0.6
    sx, sy = (width - 60) / depth, (height - 30) / hmax
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" font-family="DejaVu Sans" font-size="8">']
    parts.append(f'<rect x="30" y="10" width="{depth * sx:.0f}" height="{p["height"] * sy:.0f}" fill="none" stroke="#000"/>')
    shown = {}
    for h in result["holes"]:
        key = (h["type"], round(h["y"], 1))
        if key in shown:
            continue
        shown[key] = 1
        L = h.get("length", depth)
        ang = math.radians(h.get("angle", 0))
        sign = 1 if h["y"] > p["height"] / 2 else -1
        x0, y0 = 30, 10 + (p["height"] - h["y"]) * sy
        x1 = x0 + L * math.cos(ang) * sx
        y1 = y0 - sign * L * math.sin(ang) * sy
        col = COLORS.get(h["type"], "#333")
        parts.append(f'<line x1="{x0}" y1="{y0:.1f}" x2="{x1:.1f}" y2="{y1:.1f}" stroke="{col}" stroke-width="1.4"/>')
        if h.get("charge_length"):
            c0 = x0 + (L - h["charge_length"]) * math.cos(ang) * sx
            parts.append(f'<line x1="{c0:.1f}" y1="{y0 - sign * (L - h["charge_length"]) * math.sin(ang) * sy:.1f}" '
                         f'x2="{x1:.1f}" y2="{y1:.1f}" stroke="{col}" stroke-width="3.5" opacity="0.6"/>')
    parts.append(f'<text x="{30 + depth * sx / 2:.0f}" y="{height - 6}" text-anchor="middle">'
                 f'L = {result["input"].get("hole_depth")} {labels.get("m", "m")}, '
                 f'{labels.get("lookout", "lookout")} {p.get("lookout_deg", 3):.0f}°</text>')
    parts.append("</svg>")
    return "".join(parts)


def ring_view(res: dict, ring: dict, labels: dict, size: int = 460, energy: bool = True) -> str:
    sec = res["section"]
    us = [p[0] for p in sec]
    vs = [p[1] for p in sec]
    minu, maxu, minv, maxv = min(us) - 2, max(us) + 2, min(vs) - 3, max(vs) + 2
    sc = size / max(maxu - minu, maxv - minv)
    W, H = (maxu - minu) * sc, (maxv - minv) * sc

    def X(u):
        return (u - minu) * sc

    def Y(v):
        return H - (v - minv) * sc

    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W:.0f}" height="{H:.0f}" font-family="DejaVu Sans" font-size="8">']
    em = res.get("energy")
    if energy and em and em.get("values"):
        step = (em["u"][1] - em["u"][0]) if len(em["u"]) > 1 else 1
        for j, v in enumerate(em["v"]):
            for i, u in enumerate(em["u"]):
                val = em["values"][j][i]
                if val is None:
                    continue
                k = max(0.0, min(1.0, val / (2 * (em.get("target") or 0.6))))
                col = f"rgb({int(255 * k)},{int(200 * (1 - abs(k - 0.5) * 2))},{int(255 * (1 - k))})"
                parts.append(f'<rect x="{X(u - step / 2):.1f}" y="{Y(v + step / 2):.1f}" width="{step * sc + 0.5:.1f}" '
                             f'height="{step * sc + 0.5:.1f}" fill="{col}" opacity="0.45"/>')
    pts = " ".join(f"{X(u):.1f},{Y(v):.1f}" for u, v in sec)
    parts.append(f'<polygon points="{pts}" fill="none" stroke="#000" stroke-width="1.5"/>')
    cu, cv = res["collar"]
    for h in ring["holes"]:
        L = h["length"] or 1
        t = h["uncharged"] / L
        parts.append(f'<line x1="{X(cu):.1f}" y1="{Y(cv):.1f}" x2="{X(h["u"]):.1f}" y2="{Y(h["v"]):.1f}" stroke="#666"/>')
        parts.append(f'<line x1="{X(cu + (h["u"] - cu) * t):.1f}" y1="{Y(cv + (h["v"] - cv) * t):.1f}" '
                     f'x2="{X(h["u"]):.1f}" y2="{Y(h["v"]):.1f}" stroke="#d62728" stroke-width="2.4"/>')
        parts.append(f'<text x="{X(h["u"]) + 2:.1f}" y="{Y(h["v"]) - 2:.1f}">{h["id"]}: {h["length"]:.1f}/'
                     f'{h["charge_kg"]:.0f}</text>')
    parts.append(f'<rect x="{X(cu - 2.25):.1f}" y="{Y(cv + 2.9):.1f}" width="{4.5 * sc:.1f}" height="{4.5 * sc:.1f}" '
                 f'fill="#ddd" stroke="#000"/>')
    parts.append("</svg>")
    return "".join(parts)
