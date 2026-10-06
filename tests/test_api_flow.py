"""Сквозные проверки API на SQLite: роли, полный цикл забоя тремя ролями, геология и ВВ, ИИ (демо, кэш, бюджет),
отчёты на трёх языках, новый язык без правки кода."""
import json
import os
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def client():
    from api.main import app

    with TestClient(app) as c:
        yield c


def login(c, u, p):
    r = c.post("/api/auth/token", data={"username": u, "password": p})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["access_token"]}


@pytest.fixture(scope="module")
def H(client):
    return {"admin": login(client, "admin", "as"), "engineer": login(client, "engineer", "en"),
            "dispatcher": login(client, "dispatcher", "ds")}


def test_login_and_roles(client, H):
    assert client.post("/api/auth/token", data={"username": "admin", "password": "x"}).status_code == 401
    me = client.get("/api/auth/me", headers=H["dispatcher"]).json()
    assert me["role"] == "dispatcher" and me["must_change_password"] is True
    assert "users.manage" not in me["permissions"]
    assert client.get("/api/admin/users", headers=H["dispatcher"]).status_code == 403
    assert client.get("/api/settings", headers=H["engineer"]).status_code == 403
    assert client.get("/api/admin/users", headers=H["admin"]).status_code == 200
    # диспетчер видит паспорта, но не создаёт
    assert client.get("/api/passports/dev", headers=H["dispatcher"]).status_code == 200
    assert client.post("/api/passports/dev", json={}, headers=H["dispatcher"]).status_code == 403
    # инженер не переставляет
    assert client.post("/api/dispatch/reassign", json={"assignment_id": 1}, headers=H["engineer"]).status_code == 403


def test_admin_creates_user_and_role(client, H):
    r = client.post("/api/admin/roles", json={"name": "blaster", "title": {"ru": "Взрывник"},
                                              "permissions": ["workflow.blast", "workflow.transition", "dispatch.view"]},
                    headers=H["admin"])
    assert r.status_code == 200
    rid = r.json()["id"]
    assert client.post("/api/admin/users", json={"username": "vzryvnik", "password": "vz12345", "role_id": rid,
                                                 "full_name": "Взрывник 1"}, headers=H["admin"]).status_code == 200
    hv = login(client, "vzryvnik", "vz12345")
    me = client.get("/api/auth/me", headers=hv).json()
    assert me["role"] == "blaster" and "workflow.blast" in me["permissions"]
    assert client.get("/api/admin/audit?limit=5", headers=H["admin"]).json()


def face_by_name(client, h, name):
    return next(f for f in client.get("/api/workflow/faces", headers=h).json() if f["name"] == name)


def test_full_cycle_three_roles(client, H):
    D, E = H["dispatcher"], H["engineer"]
    staff = {p["tab_no"]: p for p in client.get("/api/staff", headers=D).json()}
    fleet = {m["label"]: m for m in client.get("/api/fleet", headers=D).json()}
    face = face_by_name(client, D, "ПШ−200 (С)")
    assert face["status"] == "ready"
    o = client.post("/api/dispatch/order", json={}, headers=D)
    assert o.status_code == 200, o.text
    oid = o.json()["id"]
    # проверки наряда: просроченный допуск, машина в ремонте
    bad = client.post(f"/api/dispatch/order/{oid}/assign", json={"person_id": staff["1008"]["id"], "machine_id": fleet["Boomer №1"]["id"],
                                                                  "face_id": face["id"], "work_type": "drilling"}, headers=D)
    assert bad.status_code == 400 and bad.json()["detail"]["code"] == "errors.permit_expired"
    bad = client.post(f"/api/dispatch/order/{oid}/assign", json={"person_id": staff["1001"]["id"], "machine_id": fleet["Boomer №4"]["id"],
                                                                  "face_id": face["id"], "work_type": "drilling"}, headers=D)
    assert bad.status_code == 400 and bad.json()["detail"]["code"] == "errors.machine_in_repair"
    ok = client.post(f"/api/dispatch/order/{oid}/assign", json={"person_id": staff["1001"]["id"], "machine_id": fleet["Boomer №1"]["id"],
                                                                 "face_id": face["id"], "work_type": "drilling"}, headers=D)
    assert ok.status_code == 200, ok.text
    board = client.get("/api/dispatch/board", headers=D).json()
    assert any(r["face"] == "ПШ−200 (С)" and r["machine"] == "Boomer №1" for r in board["rows"])

    fid = face["id"]

    def go(h, to, code=200):
        r = client.post(f"/api/workflow/faces/{fid}/transition", json={"to": to}, headers=h)
        assert r.status_code == code, (to, r.text)

    go(D, "drilling")
    det = client.get(f"/api/workflow/faces/{fid}", headers=D).json()
    holes = [{"id": h["id"], "length": h["length"] * 0.97, "drilled": True, "toe_x": h["x"] + 0.05, "toe_y": h["y"]}
             for h in det["passport"]["design"]["holes"] if h["type"] != "empty"]
    holes[-1]["drilled"] = False
    r = client.post(f"/api/workflow/faces/{fid}/drill-report", json={"holes": holes, "source": "tablet",
                                                                      "machine_id": fleet["Boomer №1"]["id"],
                                                                      "person_id": staff["1001"]["id"]}, headers=D)
    assert r.status_code == 200 and r.json()["summary"]["not_drilled"] >= 1
    assert client.post(f"/api/workflow/faces/{fid}/recalc", headers=D).status_code == 403  # диспетчер не пересчитывает
    r = client.post(f"/api/workflow/faces/{fid}/recalc", headers=E)
    assert r.status_code == 200 and r.json()["result"]["recalc"]["not_drilled"]
    edd = client.get(f"/api/workflow/faces/{fid}/edd.csv", headers=E)
    assert edd.status_code == 200 and edd.text.startswith("hole;detonator;delay_ms")
    go(E, "handed")
    go(D, "accepted")
    rc = client.get(f"/api/workflow/faces/{fid}", headers=D).json()["recalc"]["result"]
    ch = [{"id": h["id"], "kg": h["charge_kg"], "status": "charged", "delay_ms": h.get("delay_ms")}
          for h in rc["holes"] if h["type"] != "empty" and not h.get("not_drilled")]
    assert client.post(f"/api/workflow/faces/{fid}/charge-log", json={"holes": ch}, headers=D).status_code == 200
    assert client.get(f"/api/workflow/faces/{fid}", headers=D).json()["status"] == "charged"
    # окна ВР на всю смену — взрыв разрешён в любое время теста (правило окон проверяется в test_patch01)
    assert client.put("/api/mine/config", json={"shifts": {"table": [{"no": 1, "start": "08:00", "end": "20:00"},
                                                                     {"no": 2, "start": "20:00", "end": "08:00"}],
                                                           "blast_windows": [{"shift": 1, "start": "08:00", "end": "20:00"},
                                                                             {"shift": 2, "start": "20:00", "end": "08:00"}]}},
                      headers=E).status_code == 200
    go(D, "blasted")
    # дальше — без окон ВР (0 окон в смене допустимо), чтобы перестановка ниже не попала в «Идут ВР»
    assert client.put("/api/mine/config", json={"shifts": {"table": [{"no": 1, "start": "08:00", "end": "20:00"},
                                                                     {"no": 2, "start": "20:00", "end": "08:00"}],
                                                           "blast_windows": []}}, headers=E).status_code == 200
    for st in ("ventilation", "mucking", "scaling", "support"):
        go(D, st)
    from core import scans

    scan = scans.gen_dev_scan(det["passport"]["design"]["input"]["section"], 3.4, {}, np.random.default_rng(5), chainage0=face["chainage"])
    assert client.post(f"/api/workflow/faces/{fid}/scan", json={"data": scan}, headers=D).status_code == 200
    go(D, "analyzed", 403)
    go(E, "analyzed")
    det = client.get(f"/api/workflow/faces/{fid}", headers=E).json()
    a = det["analysis"]["result"]
    assert det["status"] == "analyzed" and 0.6 < a["kish"] < 1.05 and a["extra_t"] >= 0 and "extra_cost" in a
    go(D, "ready")
    det = client.get(f"/api/workflow/faces/{fid}", headers=D).json()
    assert det["cycle_no"] == 2 and det["chainage"] > face["chainage"]
    users = {e["username"] for e in det["events"]}
    assert {"dispatcher", "engineer"} <= users
    # перестановка
    asg = client.get("/api/dispatch/order", headers=D).json()["order"]["assignments"][0]
    other = face_by_name(client, D, "ПШ−250 (С)")
    r = client.post("/api/dispatch/reassign", json={"assignment_id": asg["id"], "face_id": other["id"], "reason": "тест"}, headers=D)
    assert r.status_code == 200, r.text
    assert client.get("/api/dispatch/reassignments", headers=D).json()[0]["username"] == "dispatcher"


def test_geology_priority_and_anfo_ban(client, H):
    E = H["engineer"]
    ws = {w["name"]: w for w in client.get("/api/workings", headers=E).json()}
    w = ws["ПШ−250 (С)"]
    inside = client.get(f"/api/geology/at?working_id={w['id']}&chainage=60", headers=E).json()
    outside = client.get(f"/api/geology/at?working_id={w['id']}&chainage=150", headers=E).json()
    assert inside["water"] == "flowing" and inside["priority"] == "interval"
    assert outside["water"] != "flowing"
    expl = {e["code"]: e for e in client.get("/api/explosives", headers=E).json()}
    chk = client.post("/api/explosives/check", json={"explosive_id": expl["ANFO"]["id"], "working_id": w["id"], "chainage": 60,
                                                    "diameter": 45}, headers=E).json()
    assert chk["ok"] is False and chk["alternatives"]
    r = client.post("/api/passports/dev", json={"working_id": w["id"], "chainage": 60, "input": {"explosive_id": expl["ANFO"]["id"]}},
                    headers=E)
    assert r.status_code == 400 and r.json()["detail"]["code"] == "errors.not_water_resistant"
    r = client.post("/api/passports/dev", json={"working_id": w["id"], "chainage": 60, "input": {"explosive_id": expl["EMUL_BULK"]["id"]}},
                    headers=E)
    assert r.status_code == 200


def test_typical_versions_and_suggest(client, H):
    E = H["engineer"]
    tps = client.get("/api/passports/typical", headers=E).json()
    tp = tps[0]
    r = client.put(f"/api/passports/typical/{tp['id']}", json={"input": {"hole_depth": 3.4}, "note": "короче"}, headers=E)
    assert r.status_code == 200 and r.json()["version"] == 2 and r.json()["status"] == "draft"
    for st in ("review", "approved"):
        assert client.post(f"/api/passports/typical/{tp['id']}/status", json={"status": st}, headers=E).status_code == 200
    d = client.get(f"/api/passports/typical/{tp['id']}", headers=E).json()
    assert len(d["versions"]) == 2 and d["versions"][0]["changes"]
    w = next(x for x in client.get("/api/workings?type=xc", headers=E).json())
    sug = client.get(f"/api/passports/suggest?working_id={w['id']}", headers=E).json()
    assert sug["candidates"][0]["number"] == "ТП-03"


def test_ai_demo_cache_budget(client, H):
    E, A = H["engineer"], H["admin"]
    pid = client.get("/api/passports/dev", headers=E).json()[0]["id"]
    pv = client.post("/api/ai/preview", json={"module": "dev_passport", "entity_id": pid, "lang": "ru"}, headers=E).json()
    assert pv["provider"] == "demo" and pv["chars"] > 200 and pv["blocked"] is None
    r1 = client.post("/api/ai/send", json={"module": "dev_passport", "entity_id": pid, "lang": "ru"}, headers=E).json()
    r2 = client.post("/api/ai/send", json={"module": "dev_passport", "entity_id": pid, "lang": "ru"}, headers=E).json()
    assert r1["demo"] and not r1["cache_hit"] and r2["cache_hit"]
    ap = client.post(f"/api/ai/requests/{r1['id']}/decision", json={"decision": "applied"}, headers=E)
    assert ap.status_code == 200 and ap.json()["passport_id"]
    ai = client.get("/api/settings", headers=A).json()["ai"]
    ai["monthly_budget_usd"] = 0
    assert client.put("/api/settings/ai", json={"value": ai}, headers=A).status_code == 200
    pid2 = client.get("/api/passports/dev", headers=E).json()[-1]["id"]
    pv = client.post("/api/ai/preview", json={"module": "dev_passport", "entity_id": pid2, "lang": "en"}, headers=E).json()
    assert pv["blocked"] == "budget"
    assert client.post("/api/ai/send", json={"module": "dev_passport", "entity_id": pid2, "lang": "en"}, headers=E).status_code == 400


@pytest.mark.parametrize("lang", ["ru", "en", "es"])
def test_reports_and_pdf(client, H, lang):
    D = H["dispatcher"]
    r = client.get(f"/api/reports/export/period/pdf?period=day&lang={lang}", headers=D)
    assert r.status_code == 200 and r.content[:4] == b"%PDF"
    pid = client.get("/api/passports/dev", headers=D).json()[0]["id"]
    r = client.get(f"/api/passports/dev/{pid}/export/pdf?lang={lang}", headers=D)
    assert r.status_code == 200 and r.content[:4] == b"%PDF"
    z = client.get(f"/api/reports/shift-zip?lang={lang}", headers=D)
    assert z.status_code == 200 and z.content[:2] == b"PK"


def test_new_language_without_code(client):
    root = Path(os.environ["DM_ROOT"])
    en = json.loads((root / "locales" / "en.json").read_text(encoding="utf-8"))
    en["_meta"] = {"name": "Português", "code": "pt"}
    en["menu"]["dashboard"] = "Painel"
    (root / "locales" / "pt.json").write_text(json.dumps(en, ensure_ascii=False), encoding="utf-8")
    langs = {x["code"] for x in client.get("/api/i18n/languages").json()}
    assert {"ru", "en", "es", "pt"} <= langs
    assert client.get("/api/i18n/pt").json()["menu"]["dashboard"] == "Painel"
    from common.i18n import t

    assert t("alerts.rules.kish_low.title", "es", face="X") == "Rendimiento bajo: X"


def test_planned_level_and_designer(client, H):
    E = H["engineer"]
    pv = client.post("/api/workings/wizard/level", json={"level": -325, "preview": True}, headers=E).json()
    names = [w["name"] for w in pv["items"]]
    assert "ПШ−325 (С)" in names and "ПШ−325 (Ю)" in names and any(n.startswith("БДО −325.") for n in names)
    r = client.post("/api/workings/wizard/level", json={"level": -325, "preview": False}, headers=E)
    assert r.status_code == 200 and r.json()["created"] == len(pv["items"])
    # «план проектировщиков»: та же геометрия со сдвигом 4 м
    from core import exporters

    ws = [w for w in client.get("/api/workings?level=-325", headers=E).json()]
    full = [client.get(f"/api/workings/{w['id']}", headers=E).json() for w in ws[:6]]
    dxf = exporters.workings_dxf([{**w, "axis": [[p[0] + 4, p[1], p[2]] for p in w["axis"]]} for w in full])
    up = client.post("/api/mine/import/upload", files={"file": ("plan.dxf", dxf)}, data={"kind": "workings"}, headers=E)
    assert up.status_code == 200, up.text
    jid = up.json()["job_id"]
    cmp = client.post("/api/workings/designer/compare", json={"job_id": jid}, headers=E).json()
    assert cmp["counts"]["shifted"] == 6
    rep = client.post("/api/workings/designer/replace", json={"job_id": jid}, headers=E).json()
    assert rep["replaced"] == 6
    w0 = client.get(f"/api/workings/{full[0]['id']}", headers=E).json()
    assert w0["source"] == "designer" and abs(w0["axis"][0][0] - full[0]["axis"][0][0] - 4) < 1e-6
