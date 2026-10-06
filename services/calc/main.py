"""Сервис calc: расчёты паспортов проходки, вееров, замедлений, поправочных скважин. Без состояния (HPA)."""
from __future__ import annotations

from fastapi import HTTPException

from common.web import create_app
from core import passport, rings

app = create_app("calc")


def _safe(fn, *a):
    try:
        return fn(*a)
    except (KeyError, ValueError, ZeroDivisionError) as e:
        raise HTTPException(400, f"errors.calc_failed: {e}")


@app.post("/calc/passport/design")
def p_design(body: dict):
    return _safe(passport.design, body["input"])


@app.post("/calc/passport/evaluate")
def p_evaluate(body: dict):
    return _safe(passport.evaluate, body["result"])


@app.post("/calc/passport/recalc")
def p_recalc(body: dict):
    return _safe(passport.recalc_actual, body["result"], body["actual"])


@app.post("/calc/rings/design")
def r_design(body: dict):
    return _safe(rings.design_rings, body["input"], body["stope"])


@app.post("/calc/rings/recalc")
def r_recalc(body: dict):
    return _safe(rings.recalc_actual, body["result"], body["actual"])


@app.post("/calc/rings/correction")
def r_correction(body: dict):
    return _safe(rings.correction, body["stope"], body["zones"], body["input"], body["economics"],
                 body["stope"].get("grades") or {})


@app.post("/calc/load")
def load(body: dict):
    """Нагрузочный расчёт для проверки HPA: n паспортов подряд."""
    n = int(body.get("n", 5))
    for _ in range(n):
        passport.design(body["input"])
    return {"n": n}
