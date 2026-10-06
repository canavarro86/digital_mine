"""Сервис importer: разбор DXF/DWG/STR/CSV/IREDES/облаков точек; облака → профили забоя / карты стенок камеры."""
from __future__ import annotations

import json

import numpy as np
from fastapi import File, Form, HTTPException, UploadFile

from common.web import create_app
from core import importers, scans

app = create_app("importer")


def summarize(parsed: dict) -> dict:
    """Облако точек в ответе — только выборка для 3D-предпросмотра и границы."""
    out = {k: v for k, v in parsed.items() if k != "points"}
    if "points" in parsed:
        pts = np.asarray(parsed["points"])
        step = max(1, len(pts) // 4000)
        out["points_sample"] = pts[::step].round(2).tolist()
    return out


@app.post("/import/parse")
async def parse(file: UploadFile = File(...)):
    data = await file.read()
    try:
        return summarize(importers.parse(file.filename, data))
    except ValueError as e:
        raise HTTPException(400, f"errors.import_failed: {e}")


@app.post("/import/scan")
async def scan(file: UploadFile = File(...), context: str = Form(...), kind: str = Form("dev")):
    data = await file.read()
    ctx = json.loads(context)
    parsed = importers.parse(file.filename, data, max_points=1_500_000)
    pts = np.asarray(parsed.get("points"))
    if pts is None or len(pts) == 0:
        raise HTTPException(400, "errors.no_points")
    if kind == "dev":
        profs = scans.profiles_from_points(pts, ctx["axis"], ctx["ch_from"], ctx["ch_to"])
        return {"kind": "face", "profiles": profs, "points": int(len(pts))}
    res = scans.cms_from_points(pts, ctx["stope"])
    res["points"] = int(len(pts))
    return res
