"""Рудник: список и переключение, настройки рудника, 3D-сцена, мастер импорта, экспорт DXF/STR/CSV."""
from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import httpx
from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from common import storage
from common.db import get_db
from common.models import Face, ImportJob, Machine, Mine, Orebody, Stope, Working
from common.settings import get_settings
from common.timeutil import shift_config
from common.web import attachment
from core import exporters, importers, shifts
from core import geometry as g
from core.planning import DEFAULT_TEMPLATES

from ..deps import CurrentUser, audit, get_current_user, require
from ..loader import load_package
from ..svc import active_mine, get_setting

router = APIRouter(prefix="/api/mine", tags=["mine"])

MINE_EDITABLE = ("name", "country", "timezone", "currency", "coordinate_system", "collar_elevation", "location",
                 "sublevel_height", "xc_spacing", "fwd_offset", "shifts", "densities", "costs", "sections",
                 "standard_passports", "name_templates", "default_language", "grades", "edd_template")


@router.get("")
def get_mine(db: Session = Depends(get_db), _: CurrentUser = Depends(get_current_user)):
    m = active_mine(db)
    cfg = dict(m.config)
    cfg.setdefault("name_templates", DEFAULT_TEMPLATES)
    return {"id": m.id, "code": m.code, "name": m.name, "path": m.path, "config": cfg}


@router.get("/list")
def list_mines(db: Session = Depends(get_db), _: CurrentUser = Depends(get_current_user)):
    root = get_settings().root / (get_setting(db, "mines_path") or "mines")
    packages = sorted(p.name for p in root.glob("*") if (p / "mine.yaml").exists()) if root.exists() else []
    loaded = [{"id": m.id, "code": m.code, "name": m.name, "active": m.active, "path": m.path}
              for m in db.scalars(select(Mine).order_by(Mine.id))]
    return {"loaded": loaded, "packages": packages, "root": str(root)}


@router.post("/activate/{mid}")
def activate(mid: int, db: Session = Depends(get_db), user: CurrentUser = Depends(require("mine.settings"))):
    target = db.get(Mine, mid)
    if not target:
        raise HTTPException(404, "errors.not_found")
    for m in db.scalars(select(Mine)):
        m.active = m.id == mid
    audit(db, user, "mine_activate", "mine", mid)
    db.commit()
    return {"ok": True}


@router.post("/load")
def load_mine(body: dict, db: Session = Depends(get_db), user: CurrentUser = Depends(require("mine.settings"))):
    """Загрузить пакет рудника из папки mines/<имя> (путь задаётся в «Настройках»)."""
    root = get_settings().root / (get_setting(db, "mines_path") or "mines")
    path = (root / body["package"]).resolve()
    if root.resolve() not in path.parents or not (path / "mine.yaml").exists():
        raise HTTPException(400, "errors.bad_mine_path")
    m = load_package(db, path, activate=bool(body.get("activate", True)))
    audit(db, user, "mine_load", "mine", m.id, {"path": str(path)}, commit=True)
    return {"id": m.id, "code": m.code}


@router.post("/upload")
async def upload_mine(file: UploadFile = File(...), db: Session = Depends(get_db),
                      user: CurrentUser = Depends(require("mine.settings"))):
    """Архив пакета рудника (zip с mine.yaml) → mines/<имя>/ → загрузка."""
    data = await file.read()
    root = get_settings().root / (get_setting(db, "mines_path") or "mines")
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        names = z.namelist()
        top = next((n.split("/")[0] for n in names if n.endswith("mine.yaml")), None)
        if top is None:
            raise HTTPException(400, "errors.bad_mine_archive")
        dest = root / (top if top != "mine.yaml" else Path(file.filename).stem)
        for n in names:
            if ".." in n:
                raise HTTPException(400, "errors.bad_mine_archive")
        z.extractall(dest.parent if top != "mine.yaml" else dest)
    m = load_package(db, dest)
    audit(db, user, "mine_upload", "mine", m.id, {"file": file.filename}, commit=True)
    return {"id": m.id, "code": m.code}


@router.get("/shifts")
def get_shifts(db: Session = Depends(get_db), _: CurrentUser = Depends(get_current_user)):
    """Таблица смен и график ВР (нормализованные), текущая смена, окно ВР сейчас и ближайшее."""
    m = active_mine(db)
    return shifts_state(m.config)


@router.post("/shifts/default")
def default_shifts(body: dict, _: CurrentUser = Depends(require("mine.settings"))):
    """Автозаполнение: сутки поровну от начала первой смены, окно ВР — последний час каждой смены."""
    table = shifts.default_table(int(body.get("count", 3)), body.get("start", "00:00"))
    return {"table": table, "blast_windows": shifts.default_windows(table)}


@router.post("/shifts/validate")
def validate_shifts(body: dict, user: CurrentUser = Depends(require("mine.settings"))):
    return {"issues": _issue_texts(shifts.validate(shifts.from_config(body)), user.lang)}


def _issue_texts(errs: list[dict], lang: str) -> list[dict]:
    """Длительности в ошибках смен — текстом на языке пользователя («1 ч 30 мин»)."""
    from common import i18n

    def dur(m: int) -> str:
        a = abs(int(m))
        parts = ([f"{a // 60} {i18n.t('units.h', lang)}"] if a // 60 else []) + \
            ([f"{a % 60} {i18n.t('units.min', lang)}"] if a % 60 else [])
        return " ".join(parts) or f"0 {i18n.t('units.min', lang)}"

    out = []
    for e in errs:
        p = dict(e.get("params") or {})
        for k in ("minutes", "missing"):
            if isinstance(p.get(k), int):
                p[f"{k}_text"] = dur(p[k])
        if e["code"] == "shift_total":
            p["total_text"] = dur(p["minutes"])
        code = e["code"] + ("_over" if e["code"] == "shift_total" and p.get("missing", 0) < 0 else "")
        out.append({**e, "code": code, "params": p})
    return out


def shifts_state(cfg: dict, now=None) -> dict:
    from common.timeutil import utcnow

    tz = cfg.get("timezone", "UTC")
    now = now or utcnow()
    sc = shift_config(cfg)
    cur = shifts.current(sc, now, tz)
    iso = lambda w: {**w, "start": w["start"].isoformat(), "end": w["end"].isoformat()} if w else None  # noqa: E731
    return {**sc, "tz": tz, "current": {**cur, "start": cur["start"].isoformat(), "end": cur["end"].isoformat(),
                                         "windows": [iso(w) for w in shifts.windows(sc, cur["date"], cur["shift_no"], tz)]},
            "blast_now": iso(shifts.window_at(sc, now, tz)), "next_blast": iso(shifts.next_window(sc, now, tz))}


@router.put("/config")
def update_config(body: dict, db: Session = Depends(get_db), user: CurrentUser = Depends(require("mine.settings"))):
    m = active_mine(db)
    cfg = dict(m.config)
    for k, v in body.items():
        if k in MINE_EDITABLE:
            cfg[k] = v
    if "shifts" in body:  # таблица смен покрывает сутки без разрывов и пересечений, окна ВР — внутри смен
        sh = shifts.from_config(body["shifts"] or {})
        errs = _issue_texts(shifts.validate(sh), user.lang)
        if errs:
            raise HTTPException(400, {"code": "errors." + errs[0]["code"], "params": errs[0]["params"], "issues": errs})
        cfg["shifts"] = sh
    if "timezone" in body:
        from zoneinfo import ZoneInfo

        try:
            ZoneInfo(body["timezone"])
        except Exception:
            raise HTTPException(400, "errors.bad_timezone")
    m.config = cfg
    if body.get("name"):
        m.name = body["name"]
    audit(db, user, "mine_config", "mine", m.id, {"keys": list(body)})
    db.commit()
    return {"ok": True}


@router.get("/scene")
def scene(db: Session = Depends(get_db), _: CurrentUser = Depends(get_current_user)):
    """Данные 3D-вида: оси выработок, камеры, рудное тело, забои, машины."""
    m = active_mine(db)
    ws = db.scalars(select(Working).where(Working.mine_id == m.id)).all()
    st = db.scalars(select(Stope).where(Stope.mine_id == m.id)).all()
    ob = db.scalar(select(Orebody).where(Orebody.mine_id == m.id))
    faces = db.scalars(select(Face).where(Face.mine_id == m.id)).all()
    machines = db.scalars(select(Machine)).all()
    face_pos = {}
    wmap = {w.id: w for w in ws}
    smap = {s.id: s for s in st}
    for f in faces:
        if f.working_id and f.working_id in wmap:
            face_pos[f.id] = g.point_at(wmap[f.working_id].axis, f.chainage)
        elif f.stope_id and f.stope_id in smap:
            s = smap[f.stope_id]
            gm = s.geometry
            face_pos[f.id] = [(gm["x_fw"] + gm["x_hw"]) / 2, (gm["y0"] + gm["y1"]) / 2, s.level_bottom + 2]
    return {
        "workings": [{"id": w.id, "name": w.name, "type": w.type, "level": w.level, "status": w.status,
                      "source": w.source, "axis": w.axis, "width": (w.section or {}).get("width", 5),
                      "height": (w.section or {}).get("height", 5)} for w in ws],
        "stopes": [{"id": s.id, "name": s.name, "status": s.status, "level_bottom": s.level_bottom,
                    "level_top": s.level_top, **s.geometry} for s in st],
        "orebody": ob.mesh if ob else None,
        "faces": [{"id": f.id, "name": f.name, "kind": f.kind, "status": f.status, "pos": face_pos.get(f.id)} for f in faces],
        "machines": [{"id": mc.id, "number": mc.label, "type": mc.type, "status": mc.status,
                      "pos": face_pos.get(next((f.id for f in faces if f.working_id and f.working_id == mc.working_id), -1))
                      or (g.point_at(wmap[mc.working_id].axis, 0) if mc.working_id in wmap else None)}
                     for mc in machines],
        "levels": sorted({w.level for w in ws if w.level is not None}, reverse=True),
    }


# ---------------- экспорт ----------------
@router.get("/export/{fmt}")
def export(fmt: str, levels: str | None = None, db: Session = Depends(get_db),
           user: CurrentUser = Depends(require("workings.view"))):
    m = active_mine(db)
    q = select(Working).where(Working.mine_id == m.id)
    ws = [w for w in db.scalars(q)]
    if levels:
        lv = {float(x) for x in levels.split(",")}
        ws = [w for w in ws if w.level in lv or w.type == "ramp"]
    items = [{"name": w.name, "type": w.type, "status": w.status, "axis": w.axis, "section": w.section, "level": w.level}
             for w in ws]
    stopes = [{"name": s.name, "geometry": s.geometry, "level_bottom": s.level_bottom, "level_top": s.level_top}
              for s in db.scalars(select(Stope).where(Stope.mine_id == m.id))]
    ob = db.scalar(select(Orebody).where(Orebody.mine_id == m.id))
    audit(db, user, "export", "mine", m.id, {"fmt": fmt}, commit=True)
    if fmt == "dxf":
        data = exporters.workings_dxf(items, stopes=stopes, orebody=ob.mesh if ob else None, title=m.name)
        return Response(data, media_type="application/dxf",
                        headers=attachment(f"{m.code}_workings.dxf"))
    if fmt == "str":
        data = importers.write_surpac_str([{"name": w["name"], "points": w["axis"]} for w in items], m.code)
        return Response(data, media_type="text/plain", headers=attachment(f"{m.code}.str"))
    if fmt == "csv":
        rows = []
        for w in items:
            for i, p in enumerate(w["axis"]):
                rows.append({"name": w["name"], "type": w["type"], "level": w["level"], "status": w["status"],
                             "vertex": i, "x": p[0], "y": p[1], "z": p[2]})
        return Response(exporters.table_csv(rows), media_type="text/csv",
                        headers=attachment(f"{m.code}_workings.csv"))
    raise HTTPException(400, "errors.unsupported_format")


# ---------------- мастер импорта ----------------
def _importer_parse(filename: str, data: bytes) -> dict:
    """Разбор файла сервисом importer (облака точек сокращаются там же)."""
    s = get_settings()
    if not s.db_url.startswith("sqlite"):
        try:
            r = httpx.post(s.importer_url + "/import/parse", files={"file": (filename, data)}, timeout=300)
            if r.status_code == 200:
                return r.json()
            raise HTTPException(400, r.json().get("detail", "errors.import_failed"))
        except httpx.HTTPError:
            pass
    from importer.main import summarize

    return summarize(importers.parse(filename, data))


@router.post("/import/upload")
async def import_upload(file: UploadFile = File(...), kind: str = Form("workings"), db: Session = Depends(get_db),
                        user: CurrentUser = Depends(require("mine.settings", "workflow.transition"))):
    data = await file.read()
    fmt = importers.detect_format(file.filename)
    if fmt not in importers.SUPPORTED:
        raise HTTPException(400, "errors.unsupported_format")
    key = storage.put(f"imports/{user.username}/{file.filename}", data)
    parsed = _importer_parse(file.filename, data)
    job = ImportJob(username=user.username, filename=file.filename, fmt=fmt, kind=kind, file_key=key, parsed=parsed,
                    summary={k: parsed.get(k) for k in ("kind", "layers", "bbox", "count") if k in parsed})
    db.add(job)
    audit(db, user, "import_upload", "import", file.filename, {"kind": kind, "fmt": fmt})
    db.commit()
    return {"job_id": job.id, "fmt": fmt, **job.summary,
            "layers_suggested": {lay: importers.guess_type(lay) for lay in parsed.get("layers") or []},
            "preview": _preview(parsed)}


def _preview(parsed: dict) -> dict:
    """Данные для 3D-предпросмотра: полилинии (прореженные) и выборка точек."""
    pls = [{"layer": p["layer"], "name": p.get("name", ""), "points": p["points"][:: max(1, len(p["points"]) // 60)]}
           for p in (parsed.get("polylines") or [])[:400]]
    pts = (parsed.get("points_sample") or [])[:4000]
    return {"polylines": pls, "points": pts}


@router.get("/import/jobs")
def import_jobs(db: Session = Depends(get_db), _: CurrentUser = Depends(require("mine.settings"))):
    return [{k: v for k, v in j.as_dict().items() if k != "parsed"}
            for j in db.scalars(select(ImportJob).order_by(ImportJob.id.desc()).limit(100))]


@router.post("/import/{job_id}/commit")
def import_commit(job_id: int, body: dict, db: Session = Depends(get_db),
                  user: CurrentUser = Depends(require("mine.settings"))):
    """Импорт: workings (с сопоставлением слоёв и сдвигом координат), orebody, stopes."""
    job = db.get(ImportJob, job_id)
    if not job:
        raise HTTPException(404, "errors.not_found")
    m = active_mine(db)
    kind = body.get("kind", job.kind)
    created = 0
    if kind == "workings":
        ws = importers.polylines_to_workings(job.parsed, body.get("layer_map"), body.get("offset"))
        status = body.get("status", "done")
        for w in ws:
            db.add(Working(mine_id=m.id, name=w["name"], type=w["type"], level=w["level"], status=w.get("status") or status,
                           source="import", axis=w["axis"], section=w["section"], props={"import_job": job.id}))
            created += 1
    elif kind == "orebody":
        meshes = job.parsed.get("meshes") or []
        if not meshes:
            raise HTTPException(400, "errors.no_mesh")
        verts, faces = [], []
        for msh in meshes:
            off = len(verts)
            verts += msh["vertices"]
            faces += [[a + off for a in f] for f in msh["faces"]]
        db.add(Orebody(mine_id=m.id, name=job.filename, mesh={"vertices": verts, "faces": faces}))
        created = 1
    else:
        raise HTTPException(400, "errors.unsupported_kind")
    job.status = "imported"
    job.summary = dict(job.summary, created=created)
    audit(db, user, "import_commit", "import", job_id, {"kind": kind, "created": created})
    db.commit()
    return {"created": created}


@router.get("/import/{job_id}/parsed")
def import_parsed(job_id: int, db: Session = Depends(get_db), _: CurrentUser = Depends(require("mine.settings"))):
    job = db.get(ImportJob, job_id)
    if not job:
        raise HTTPException(404, "errors.not_found")
    return json.loads(json.dumps(job.parsed)[:5_000_000])
