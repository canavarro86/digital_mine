"""Сервис analyzer: скан против проекта — КИШ, переборы, лишняя порода (м³, т, $), ELOS, разубоживание, потери, причины."""
from __future__ import annotations

from common.web import EVENTS, create_app
from core import analysis

app = create_app("analyzer")


@app.post("/analyze/dev")
def dev(body: dict):
    EVENTS.labels("analyzer", "dev").inc()
    return analysis.analyze_dev(body["design"], body["scan"], body.get("drill"), body.get("charge"),
                                body.get("geology") or {}, body.get("economics") or {})


@app.post("/analyze/stope")
def stope(body: dict):
    EVENTS.labels("analyzer", "stope").inc()
    return analysis.analyze_stope(body["stope"], body["cms"], body.get("design"), body.get("drill"), body.get("charge"),
                                  body.get("geology") or {}, body.get("economics") or {})
