"""Отчёты: по забою, буровой, проходчику, смене / суткам / месяцу. Экран (JSON), PDF, CSV; ZIP отчёта смены."""
from __future__ import annotations

import io
import zipfile
from datetime import date, datetime, timedelta

import numpy as np
from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from common import i18n
from common.db import get_db
from common.models import Analysis, Assignment, ChargeLog, DrillReport, Face, FaceEvent, Machine, Person, ShiftOrder, Working
from common.timeutil import current_shift, shift_bounds, to_tz, utcnow
from common.web import attachment
from core import exporters

from ..deps import CurrentUser, audit, require
from ..svc import active_mine

router = APIRouter(prefix="/api/reports", tags=["reports"])
VIEW = require("reports.view")


def _mean(xs):
    xs = [x for x in xs if x is not None]
    return round(float(np.mean(xs)), 3) if xs else None


def _period(db: Session, period: str, day: str | None, shift_no: int | None) -> tuple[datetime, datetime, str]:
    m = active_mine(db)
    cfg = m.config
    sh = current_shift(cfg)
    d = day or sh["date"]
    if period == "shift":
        n = shift_no or sh["shift_no"]
        s, e = shift_bounds(cfg, d, n)
        return s, e, f"{d} / {n}"
    if period == "day":
        s, _ = shift_bounds(cfg, d, 1)
        return s, s + timedelta(days=1), d
    if period == "month":
        dd = date.fromisoformat(d).replace(day=1)
        nxt = (dd + timedelta(days=32)).replace(day=1)
        s, _ = shift_bounds(cfg, dd.isoformat(), 1)
        e, _ = shift_bounds(cfg, nxt.isoformat(), 1)
        return s, e, dd.strftime("%Y-%m")
    raise HTTPException(400, "errors.bad_period")


def _analyses(db: Session, s: datetime, e: datetime) -> list[Analysis]:
    return list(db.scalars(select(Analysis).where(Analysis.created_at >= s, Analysis.created_at < e)))


def period_report(db: Session, period: str, day: str | None, shift_no: int | None) -> dict:
    s, e, label = _period(db, period, day, shift_no)
    an = _analyses(db, s, e)
    dev = [a.result for a in an if a.kind == "dev"]
    st = [a.result for a in an if a.kind == "stope"]
    charges = db.scalars(select(ChargeLog).where(ChargeLog.created_at >= s, ChargeLog.created_at < e)).all()
    faces = {f.id: f.name for f in db.scalars(select(Face))}
    kinds = {f.id: f.kind for f in db.scalars(select(Face))}
    ev = db.scalars(select(FaceEvent).where(FaceEvent.ts >= s, FaceEvent.ts < e,
                                            FaceEvent.to_status.in_(("blasted", "wait_blast")))).all()
    blasted = [x for x in ev if x.to_status == "blasted"]
    override = [x for x in blasted if (x.comment or "").startswith("ВР вне окна")]
    return {
        "period": period, "label": label, "start": s.isoformat(), "end": e.isoformat(),
        # взрывы по графику ВР
        "blasting": {"dev_in_window": sum(1 for x in blasted if x not in override and kinds.get(x.face_id) == "dev"),
                     "stope_in_window": sum(1 for x in blasted if x not in override and kinds.get(x.face_id) == "stope"),
                     "outside_window": len(override),
                     "moved_to_next": len({(x.face_id, x.cycle_no) for x in ev if x.to_status == "wait_blast"})},
        "development": {"cycles": len(dev), "advance_m": round(sum(r.get("advance", 0) for r in dev), 1),
                        "kish": _mean([r.get("kish") for r in dev]),
                        "overbreak_pct": _mean([r.get("overbreak_pct") for r in dev]),
                        "extra_t": round(sum(r.get("extra_t", 0) for r in dev), 1),
                        "extra_cost": round(sum(r.get("extra_cost", 0) for r in dev), 0)},
        "stoping": {"blasts": len(st), "blasted_t": round(sum(r.get("blasted_t", 0) for r in st), 0),
                    "elos_hw": _mean([r.get("elos_hw") for r in st]),
                    "dilution_pct": _mean([r.get("dilution_pct") for r in st]),
                    "loss_t": round(sum(r.get("loss_t", 0) for r in st), 0),
                    "loss_cost": round(sum(r.get("loss_cost_usd", 0) for r in st), 0),
                    "result_usd": round(sum(r.get("result_usd", 0) for r in st), 0)},
        "explosives": {"plan_kg": round(sum(c.summary.get("plan_kg", 0) for c in charges), 1),
                       "fact_kg": round(sum(c.summary.get("fact_kg", 0) for c in charges), 1)},
        "cycles": [{"face": faces.get(a.face_id), "kind": a.kind, "cycle": a.cycle_no,
                    "advance": a.result.get("advance"), "kish": a.result.get("kish"),
                    "overbreak_pct": a.result.get("overbreak_pct"), "extra_t": a.result.get("extra_t"),
                    "extra_cost": a.result.get("extra_cost"), "elos_hw": a.result.get("elos_hw"),
                    "dilution_pct": a.result.get("dilution_pct"), "cause": a.causes.get("primary"),
                    "ts": a.created_at.isoformat()} for a in an],
    }


def face_report(db: Session, face_id: int) -> dict:
    f = db.get(Face, face_id)
    if not f:
        raise HTTPException(404, "errors.not_found")
    an = db.scalars(select(Analysis).where(Analysis.face_id == face_id).order_by(Analysis.cycle_no)).all()
    ch = {c.cycle_no: c.summary for c in db.scalars(select(ChargeLog).where(ChargeLog.face_id == face_id))}
    rows = []
    for a in an:
        r = a.result
        rows.append({"cycle": a.cycle_no, "advance": r.get("advance"), "design_advance": r.get("design_advance"),
                     "kish": r.get("kish"), "overbreak_pct": r.get("overbreak_pct"), "extra_t": r.get("extra_t"),
                     "extra_cost": r.get("extra_cost"), "elos_hw": r.get("elos_hw"), "dilution_pct": r.get("dilution_pct"),
                     "result_usd": r.get("result_usd"),
                     "explosive_plan_kg": (ch.get(a.cycle_no) or {}).get("plan_kg"),
                     "explosive_fact_kg": (ch.get(a.cycle_no) or {}).get("fact_kg"), "cause": a.causes.get("primary"),
                     "ts": a.created_at.isoformat()})
    dev = [a.result for a in an if a.kind == "dev"]
    return {"face": f.name, "kind": f.kind, "cycles": rows,
            "totals": {"cycles": len(rows), "advance_m": round(sum(r.get("advance", 0) for r in dev), 1),
                       "kish": _mean([r.get("kish") for r in dev]), "extra_t": round(sum(r.get("extra_t", 0) for r in dev), 1),
                       "extra_cost": round(sum(r.get("extra_cost", 0) for r in dev), 0),
                       "explosive_fact_kg": round(sum((c or {}).get("fact_kg", 0) for c in ch.values()), 1)}}


def machine_report(db: Session, machine_id: int, days: int = 30) -> dict:
    mc = db.get(Machine, machine_id)
    if not mc:
        raise HTTPException(404, "errors.not_found")
    since = utcnow() - timedelta(days=days)
    reps = db.scalars(select(DrillReport).where(DrillReport.machine_id == machine_id, DrillReport.received_at >= since)).all()
    faces = {f.id: f.name for f in db.scalars(select(Face))}
    rows = [{"face": faces.get(r.face_id), "cycle": r.cycle_no, "ts": r.received_at.isoformat(), **r.summary} for r in reps]
    idle = db.scalars(select(Assignment).where(Assignment.machine_id == machine_id, Assignment.started_at >= since)).all()
    return {"machine": mc.label, "type": mc.type, "engine_hours": mc.engine_hours, "status": mc.status, "reports": rows,
            "totals": {"reports": len(rows), "drill_m": round(sum(r.get("drill_m", 0) for r in rows), 1),
                       "holes": sum(r.get("drilled", 0) for r in rows),
                       "mean_deviation_pct": _mean([r.get("mean_deviation_pct") for r in rows]),
                       "assignments": len(idle)}}


def person_report(db: Session, person_id: int, days: int = 30) -> dict:
    p = db.get(Person, person_id)
    if not p:
        raise HTTPException(404, "errors.not_found")
    since = utcnow() - timedelta(days=days)
    asg = db.scalars(select(Assignment).where(Assignment.person_id == person_id, Assignment.started_at >= since)).all()
    reps = db.scalars(select(DrillReport).where(DrillReport.person_id == person_id, DrillReport.received_at >= since)).all()
    kish = []
    for r in reps:
        a = db.scalar(select(Analysis).where(Analysis.face_id == r.face_id, Analysis.cycle_no == r.cycle_no))
        if a and a.result.get("kish") is not None:
            kish.append(a.result["kish"])
    orders = {o.id: o for o in db.scalars(select(ShiftOrder))}
    machines = {m.id: m.label for m in db.scalars(select(Machine))}
    faces = {f.id: f.name for f in db.scalars(select(Face))}
    return {"person": p.full_name, "profession": p.profession, "professions": p.professions or [],
            "shifts": len({(orders[a.order_id].date, orders[a.order_id].shift_no) for a in asg if a.order_id in orders}),
            "machines": sorted({machines.get(a.machine_id, "") for a in asg if a.machine_id}),
            "faces": sorted({faces.get(a.face_id, "") for a in asg if a.face_id}),
            "drill_m": round(sum(r.summary.get("drill_m", 0) for r in reps), 1),
            "mean_deviation_pct": _mean([r.summary.get("mean_deviation_pct") for r in reps]), "kish": _mean(kish),
            "cycles": len(reps)}


@router.get("/period")
def r_period(period: str = "shift", day: str | None = None, shift_no: int | None = None, db: Session = Depends(get_db),
             _: CurrentUser = Depends(VIEW)):
    return period_report(db, period, day, shift_no)


@router.get("/face/{fid}")
def r_face(fid: int, db: Session = Depends(get_db), _: CurrentUser = Depends(VIEW)):
    return face_report(db, fid)


@router.get("/machine/{mid}")
def r_machine(mid: int, days: int = 30, db: Session = Depends(get_db), _: CurrentUser = Depends(VIEW)):
    return machine_report(db, mid, days)


@router.get("/person/{pid}")
def r_person(pid: int, days: int = 30, db: Session = Depends(get_db), _: CurrentUser = Depends(VIEW)):
    return person_report(db, pid, days)


# ---------------- выгрузки ----------------
def _render(kind: str, data: dict, lang: str, fmt: str, mine_name: str, gen: str) -> tuple[bytes, str]:
    t = lambda k: i18n.t(k, lang)  # noqa: E731
    if kind == "period":
        cols = [("face", t("reports.col.face")), ("kind", t("reports.col.kind")), ("cycle", t("reports.col.cycle")),
                ("advance", t("reports.col.advance")), ("kish", t("reports.col.kish")),
                ("overbreak_pct", t("reports.col.overbreak_pct")), ("extra_t", t("reports.col.extra_t")),
                ("extra_cost", t("reports.col.extra_cost")), ("elos_hw", t("reports.col.elos_hw")),
                ("dilution_pct", t("reports.col.dilution_pct")), ("cause", t("reports.col.cause"))]
        rows = [{**r, "cause": t(f"analysis.causes.{r['cause']}") if r.get("cause") else "", "kind": t(f"common.kind.{r['kind']}")}
                for r in data["cycles"]]
        kv = [(t("reports.dev_advance"), data["development"]["advance_m"]), (t("reports.kish"), data["development"]["kish"]),
              (t("reports.overbreak"), data["development"]["overbreak_pct"]), (t("reports.extra_t"), data["development"]["extra_t"]),
              (t("reports.extra_cost"), data["development"]["extra_cost"]), (t("reports.stope_t"), data["stoping"]["blasted_t"]),
              (t("reports.elos"), data["stoping"]["elos_hw"]), (t("reports.dilution"), data["stoping"]["dilution_pct"]),
              (t("reports.losses_usd"), data["stoping"]["loss_cost"]), (t("reports.expl_plan"), data["explosives"]["plan_kg"]),
              (t("reports.expl_fact"), data["explosives"]["fact_kg"]),
              (t("reports.blasted_in_window"), f"{data['blasting']['dev_in_window']} / {data['blasting']['stope_in_window']}"),
              (t("reports.moved_to_next"), data["blasting"]["moved_to_next"]),
              (t("reports.blasted_outside"), data["blasting"]["outside_window"])]
        title = f"{t('reports.period.' + data['period'])}: {data['label']}"
    elif kind == "face":
        cols = [(k, t(f"reports.col.{k}")) for k in ("cycle", "advance", "kish", "overbreak_pct", "extra_t", "extra_cost",
                                                      "explosive_plan_kg", "explosive_fact_kg", "cause")]
        rows = [{**r, "cause": t(f"analysis.causes.{r['cause']}") if r.get("cause") else ""} for r in data["cycles"]]
        kv = [(t(f"reports.tot.{k}"), v) for k, v in data["totals"].items()]
        title = f"{t('reports.by_face')}: {data['face']}"
    elif kind == "machine":
        cols = [(k, t(f"reports.col.{k}")) for k in ("face", "cycle", "drill_m", "drilled", "not_drilled", "mean_deviation_pct")]
        rows = data["reports"]
        kv = [(t(f"reports.tot.{k}"), v) for k, v in data["totals"].items()]
        title = f"{t('reports.by_machine')}: {data['machine']}"
    else:
        cols = []
        rows = None
        kv = [(t(f"reports.tot.{k}"), ", ".join(v) if isinstance(v, list) else v) for k, v in data.items()
              if k not in ("person",)]
        title = f"{t('reports.by_person')}: {data['person']}"
    if fmt == "csv":
        if rows is None:
            return exporters.table_csv([{k: v for k, v in kv}]).encode("utf-8-sig"), "text/csv"
        return exporters.table_csv([{lbl: r.get(k) for k, lbl in cols} for r in rows]).encode("utf-8-sig"), "text/csv"
    from core.pdf import table_pdf

    return table_pdf(title, f"{mine_name} · {gen}", [{"title": t("reports.summary"), "kv": kv},
                                                    *([{"title": t("reports.details"), "columns": cols, "rows": rows}]
                                                      if rows is not None else [])]), "application/pdf"


@router.get("/export/{kind}/{fmt}")
def export(kind: str, fmt: str, lang: str = "ru", period: str = "shift", day: str | None = None, shift_no: int | None = None,
           id: int | None = None, db: Session = Depends(get_db), user: CurrentUser = Depends(VIEW)):
    m = active_mine(db)
    gen = to_tz(utcnow(), m.config.get("timezone", "UTC")).strftime("%d.%m.%Y %H:%M")
    data = {"period": lambda: period_report(db, period, day, shift_no), "face": lambda: face_report(db, id),
            "machine": lambda: machine_report(db, id), "person": lambda: person_report(db, id)}[kind]()
    body, mt = _render(kind, data, lang, fmt, m.name, gen)
    audit(db, user, "report_export", "report", kind, {"fmt": fmt, "lang": lang}, commit=True)
    return Response(body, media_type=mt, headers=attachment(f"report_{kind}_{lang}.{fmt}"))


@router.get("/shift-zip")
def shift_zip(lang: str = "ru", day: str | None = None, shift_no: int | None = None, db: Session = Depends(get_db),
              user: CurrentUser = Depends(VIEW)):
    """«Выгрузить отчёт смены» → ZIP с PDF и CSV (для планшета или флешки)."""
    m = active_mine(db)
    gen = to_tz(utcnow(), m.config.get("timezone", "UTC")).strftime("%d.%m.%Y %H:%M")
    data = period_report(db, "shift", day, shift_no)
    pdf, _ = _render("period", data, lang, "pdf", m.name, gen)
    csv, _ = _render("period", data, lang, "csv", m.name, gen)
    s, e, _ = _period(db, "shift", day, shift_no)
    events = db.scalars(select(FaceEvent).where(FaceEvent.ts >= s, FaceEvent.ts < e).order_by(FaceEvent.ts)).all()
    faces = {f.id: f.name for f in db.scalars(select(Face))}
    tz = m.config.get("timezone", "UTC")
    ev = exporters.table_csv([{"time_mine": to_tz(x.ts, tz).strftime("%Y-%m-%d %H:%M"), "face": faces.get(x.face_id),
                               "from": x.from_status, "to": x.to_status, "user": x.username, "comment": x.comment}
                              for x in events])
    buf = io.BytesIO()
    label = data["label"].replace(" / ", "_s")
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(f"shift_{label}_{lang}.pdf", pdf)
        z.writestr(f"shift_{label}_cycles.csv", csv)
        z.writestr(f"shift_{label}_events.csv", ev.encode("utf-8-sig"))
    audit(db, user, "shift_zip", "report", label, {"lang": lang}, commit=True)
    return Response(buf.getvalue(), media_type="application/zip",
                    headers=attachment(f"shift_{label}.zip"))


@router.get("/workings-csv")
def workings_csv(db: Session = Depends(get_db), _: CurrentUser = Depends(VIEW)):
    rows = [{"name": w.name, "type": w.type, "level": w.level, "status": w.status, "source": w.source}
            for w in db.scalars(select(Working))]
    return Response(exporters.table_csv(rows).encode("utf-8-sig"), media_type="text/csv",
                    headers=attachment("workings.csv"))
