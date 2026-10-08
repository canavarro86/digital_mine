"""Модели машин и параметры, профессии и допуски, совместимость машины и забоя, смены и график ВР, перенос данных."""
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


def fleet(c, h):
    return {m["label"]: m for m in c.get("/api/fleet", headers=h).json()}


def staff(c, h):
    return {p["tab_no"]: p for p in c.get("/api/staff", headers=h).json()}


def model(c, h, label):
    return next(m for m in c.get("/api/fleet/models", headers=h).json() if m["label"] == label)


def ready_face(c, h, kind):
    return next(f for f in c.get("/api/workflow/faces", headers=h).json() if f["kind"] == kind and f["status"] == "ready")


def check(c, h, **body):
    r = c.post("/api/dispatch/check", json=body, headers=h)
    assert r.status_code == 200, r.text
    return r.json()["issues"]


def errors(issues):
    return [i for i in issues if i["level"] == "error"]


# ---------------- модели машин ----------------
def test_starter_models_and_meta(client, H):
    E = H["engineer"]
    models = client.get("/api/fleet/models", headers=E).json()
    labels = {m["label"] for m in models}
    assert {"Axera DD421", "Simba E7 C", "Boomer M2 C", "Scooptram ST14", "LH517i"} <= labels
    assert all(m["verify"] for m in models)  # «проверить по паспорту машины»
    meta = client.get("/api/fleet/meta", headers=E).json()
    assert "reposition_min" in meta["types"]["dev_drill"]["params"] and meta["params"]["dia_min"]["unit"] == "mm"
    # демо-флот привязан к моделям, название выводится вместо номера
    fl = fleet(client, E)
    assert fl["Axera №48"]["number"] == "48" and fl["Axera №48"]["model_label"] == "Axera DD421"
    # Simba — по модели Epiroc Simba E7 C без отличий; Boomer — своя скорость бурения (отличие от модели, «*»)
    assert fl["Simba №21"]["overrides"] == [] and fl["Simba №22"]["params"]["dia_max"] == 127
    assert fl["Simba №21"]["params"]["max_length"] == 51 and fl["Boomer №2"]["overrides"] == ["drill_rate_mph"]


def test_fresh_install_has_no_migration_items(client, H):
    """Установка с нуля: демо-персонал с полноценными допусками из демо-данных, без «авто» и без отчета переноса."""
    E = H["engineer"]
    people = client.get("/api/staff", headers=E).json()
    permits = [x for p in people for x in p["permits"]]
    assert permits and not any(x["auto"] for x in permits)
    assert all(x["number"] and x["issued_at"] for x in permits)  # номер документа и дата выдачи
    assert all(p["professions"] for p in people)
    rep = client.get("/api/migration/patch01", headers=E).json()
    assert rep["persons"] == [] and rep["machines"] == []  # баннера в «Персонале» нет


def test_machine_from_model_custom_and_edit(client, H):
    E = H["engineer"]
    dd = model(client, E, "Axera DD421")
    r = client.post("/api/fleet", json={"number": "77", "model_id": dd["id"], "status": "working"}, headers=E)
    assert r.status_code == 200, r.text
    m = r.json()
    assert m["name"] == "Axera №77" and m["type"] == "dev_drill" and m["params"] == dd["params"] and m["overrides"] == []
    # номер уникален в пределах рудника
    dup = client.post("/api/fleet", json={"number": "77", "model_id": dd["id"]}, headers=E)
    assert dup.status_code == 400 and dup.json()["detail"]["code"] == "errors.machine_number_exists"
    # правка параметров конкретной машины (износ): отличие помечается, модель не меняется
    r = client.put(f"/api/fleet/{m['id']}", json={"params": {**m["params"], "drill_rate_mph": 70}}, headers=E)
    assert r.status_code == 200 and r.json()["overrides"] == ["drill_rate_mph"]
    assert model(client, E, "Axera DD421")["params"]["drill_rate_mph"] == dd["params"]["drill_rate_mph"]
    # нестандартная установка: тип и параметры вручную
    r = client.post("/api/fleet", json={"number": "90", "type": "ring_drill", "model": "Самодельный станок",
                                        "params": {"booms": 1, "dia_min": 76, "dia_max": 102, "max_length": 30}}, headers=E)
    assert r.status_code == 200, r.text
    cm = r.json()
    assert cm["custom"] and cm["model_id"] is None and cm["params"]["dia_max"] == 102 and cm["name"].endswith("№90")
    # диспетчер меняет только статус
    D = H["dispatcher"]
    client.put(f"/api/fleet/{cm['id']}", json={"status": "idle", "params": {"booms": 9}}, headers=D)
    assert fleet(client, E)[cm["name"]]["params"]["booms"] == 1
    assert client.post("/api/fleet/models", json={"model": "X", "type": "lhd"}, headers=D).status_code == 403


def test_model_crud(client, H):
    E = H["engineer"]
    r = client.post("/api/fleet/models", json={"manufacturer": "Resemin", "model": "Muki FF", "short_name": "Muki",
                                               "type": "dev_drill", "params": {"booms": 1}}, headers=E)
    assert r.status_code == 200, r.text
    mid = r.json()["id"]
    assert r.json()["params"]["dia_min"] == 38  # остальное — значения типа по умолчанию
    assert client.put(f"/api/fleet/models/{mid}", json={"params": {**r.json()["params"], "max_length": 3.0}},
                      headers=E).json()["params"]["max_length"] == 3.0
    used = model(client, E, "Simba E7 C")
    assert client.delete(f"/api/fleet/models/{used['id']}", headers=E).json()["detail"]["code"] == "errors.model_in_use"
    assert client.delete(f"/api/fleet/models/{mid}", headers=E).status_code == 200


def test_passport_checked_against_machine_range(client, H):
    E, D = H["engineer"], H["dispatcher"]
    face = ready_face(client, D, "dev")
    det = client.get(f"/api/workflow/faces/{face['id']}", headers=D).json()
    d = det["passport"]["design"]["input"]["hole_diameter"]
    dd = model(client, E, "Axera DD421")
    m = client.post("/api/fleet", json={"number": "78", "model_id": dd["id"]}, headers=E).json()
    issues = check(client, D, machine_id=m["id"], face_id=face["id"], work_type="drilling")
    assert not errors(issues), issues  # Ø и длина в диапазоне — допустимо
    client.put(f"/api/fleet/{m['id']}", json={"params": {**m["params"], "dia_min": d + 5, "max_length": 2.0}}, headers=E)
    codes = {i["code"]: i["params"] for i in errors(check(client, D, machine_id=m["id"], face_id=face["id"], work_type="drilling"))}
    assert codes["passport_diameter_range"]["machine"] == "Axera №78" and codes["passport_diameter_range"]["d"] == d
    assert codes["passport_length_over"]["max"] == 2.0
    # габариты и зона обуривания — по сечению выработки
    client.put(f"/api/fleet/{m['id']}", json={"params": {**m["params"], "width_m": 6, "cover_w_max": 3}}, headers=E)
    codes = {i["code"] for i in errors(check(client, D, machine_id=m["id"], face_id=face["id"], work_type="drilling"))}
    assert {"machine_too_big", "coverage_too_small"} <= codes


# ---------------- профессии и допуски ----------------
def test_miner_example_from_remark(client, H):
    """Горнорабочий с допусками «Axera DD421» + «Бурение забоя» + «Вспомогательное оборудование»."""
    D = H["dispatcher"]
    p = staff(client, D)["1021"]
    assert p["profession_labels"] == ["Горнорабочий", "Машинист вспомогательного оборудования"]  # совмещение
    assert "Axera DD421" in p["can_work_on"] and "Simba E7 C" not in p["can_work_on"]
    fl = fleet(client, D)
    ok = check(client, D, person_id=p["id"], machine_id=fl["Axera №48"]["id"], face_id=ready_face(client, D, "dev")["id"],
               work_type="drilling")
    assert not errors(ok), ok
    bad = errors(check(client, D, person_id=p["id"], machine_id=fl["Simba №21"]["id"],
                       face_id=ready_face(client, D, "stope")["id"], work_type="ring_drilling"))
    assert bad[0]["code"] == "no_permit"
    assert bad[0]["params"]["what"] == "Simba E7 C и на Бурение вееров"  # «Нет допуска на Simba E7 C и на бурение вееров»
    bad = errors(check(client, D, person_id=p["id"], machine_id=fl["Зарядная №41"]["id"], work_type="charging"))
    assert bad[0]["code"] == "no_permit" and "Заряжание" in bad[0]["params"]["what"]
    ok = check(client, D, person_id=p["id"], machine_id=fl["Автосамосвал №51"]["id"], work_type="aux")
    assert not errors(ok), ok
    # Boomer — проходческая буровая, а допуск у него только на модель Axera DD421
    bad = errors(check(client, D, person_id=p["id"], machine_id=fl["Boomer №1"]["id"], work_type="drilling"))
    assert bad[0]["code"] == "no_permit" and bad[0]["params"]["what"] == "Boomer M2D"


def test_expired_permit_and_english_text(client, H):
    D = H["dispatcher"]
    p = staff(client, D)["1008"]
    issues = errors(check(client, D, person_id=p["id"], machine_id=fleet(client, D)["Boomer №1"]["id"], work_type="drilling"))
    assert issues[0]["code"] == "permit_expired" and issues[0]["params"]["what"] == "Boomer M2D"
    st = {x["label"]: x["state"] for x in p["permits"]}
    assert st["Проходческая буровая"] == "expired"
    # истекает через 9 дней — предупреждение, назначать можно
    p2 = staff(client, D)["1002"]
    w = check(client, D, person_id=p2["id"], machine_id=fleet(client, D)["Boomer №1"]["id"], work_type="drilling")
    assert not errors(w) and any(i["code"] == "permit_expiring" for i in w)


def test_trainee_needs_mentor_in_same_shift(client, H):
    D, E = H["dispatcher"], H["engineer"]
    s = staff(client, D)
    trainee, mentor = s["1022"], s["1001"]
    assert trainee["trainee"] and trainee["mentor_name"] == mentor["full_name"]
    fl = fleet(client, D)
    o = client.post("/api/dispatch/order", json={"date": "2026-11-10", "shift_no": 1}, headers=D).json()
    body = {"person_id": trainee["id"], "machine_id": fl["Boomer №2"]["id"], "work_type": "drilling"}
    r = client.post(f"/api/dispatch/order/{o['id']}/assign", json=body, headers=D)
    assert r.status_code == 400 and r.json()["detail"]["code"] == "errors.trainee_mentor_absent"
    r = client.post(f"/api/dispatch/order/{o['id']}/assign", json={**body, "person_id": mentor["id"]}, headers=D)
    assert r.status_code == 200, r.text
    r = client.post(f"/api/dispatch/order/{o['id']}/assign", json=body, headers=D)  # на машине наставника
    assert r.status_code == 200, r.text
    # стажер без наставника
    prof = client.post("/api/staff", json={"full_name": "Новиков Илья", "tab_no": "9001", "professions": ["trainee"],
                                           "shift": 1}, headers=E)
    assert prof.status_code == 200, prof.text
    issues = errors(check(client, D, person_id=prof.json()["id"], work_type="scaling", order_id=o["id"]))
    assert {"trainee_no_mentor", "no_permit"} <= {i["code"] for i in issues}


def test_candidates_admitted_first(client, H):
    D = H["dispatcher"]
    fl = fleet(client, D)
    r = client.get("/api/dispatch/candidates", params={"work_type": "ring_drilling", "machine_id": fl["Simba №21"]["id"]},
                   headers=D).json()
    ok = [p for p in r["persons"] if p["ok"]]
    assert ok and all(p["ok"] for p in r["persons"][:len(ok)])  # допущенные — первыми
    assert {"Kuznetsov Dmitry", "Muñoz Rojas Pedro"} <= {p["full_name"] for p in ok}
    miner = next(p for p in r["persons"] if p["full_name"] == "Морозов Артем Ильич")
    assert not miner["ok"] and "Simba E7 C" in miner["reasons"][0]
    # машины для работы: только станки глубокого бурения; для выбранного человека — с причиной
    r = client.get("/api/dispatch/candidates", params={"work_type": "drilling", "person_id": staff(client, D)["1021"]["id"]},
                   headers=D).json()
    by = {m["label"]: m for m in r["machines"]}
    assert "Simba №21" not in by and by["Axera №48"]["ok"] and not by["Boomer №1"]["ok"]
    assert r["machines"][0]["ok"]


def test_professions_defaults_and_permit_editing(client, H):
    E = H["engineer"]
    profs = {p["code"]: p for p in client.get("/api/staff/professions", headers=E).json()}
    assert len(profs) >= 11 and profs["miner"]["label"] == "Горнорабочий"
    assert {x["target"] for x in profs["ring_driller"]["permits"]} == {"ring_drill", "ring_drilling"}
    sim = model(client, E, "Simba E7 C")
    r = client.post("/api/staff/professions", json={"title": "Оператор Simba", "permits": [
        {"kind": "machine", "target": f"model:{sim['id']}"}, {"kind": "work", "target": "ring_drilling"}]}, headers=E)
    assert r.status_code == 200, r.text
    code = r.json()["code"]
    # новый человек: допуски по умолчанию передаются из окна «Человек»
    r = client.post("/api/staff", json={"full_name": "Тестов Тест", "tab_no": "9002", "professions": [code, "miner"], "shift": 2,
                                        "permits": [{"kind": "machine", "target": f"model:{sim['id']}", "valid_to": "2031-01-01",
                                                     "number": "7/26", "issued_at": "2026-01-01"},
                                                    {"kind": "work", "target": "ring_drilling", "valid_to": "2031-01-01"}]},
                    headers=E)
    assert r.status_code == 200, r.text
    p = staff(client, E)["9002"]
    assert p["profession_labels"] == ["Оператор Simba", "Горнорабочий"] and p["can_work_on"] == ["Simba E7 C"]
    assert client.post("/api/staff", json={"full_name": "X", "tab_no": "9003", "professions": ["nope"]},
                       headers=E).json()["detail"]["code"] == "errors.bad_profession"
    assert client.post(f"/api/staff/{p['id']}/permits", json={"kind": "machine", "target": "model:99999", "valid_to": "2030-01-01"},
                       headers=E).json()["detail"]["code"] == "errors.bad_permit_target"
    # своя работа в справочнике видов допусков
    r = client.post("/api/staff/work-kinds", json={"code": "ventilation_check", "title": "Замер газа"}, headers=E)
    assert r.status_code == 200, r.text
    assert "ventilation_check" in client.get("/api/dispatch/order", headers=H["dispatcher"]).json()["work_types"]


def test_coverage_warning_and_copy_rechecks(client, H):
    D = H["dispatcher"]
    o = client.post("/api/dispatch/order", json={"date": "2026-11-11", "shift_no": 2}, headers=D).json()
    gaps = {g["machine"] for g in o["coverage"]}
    assert "Boltec M" in gaps and "Simba E7 C" not in gaps  # крепильщик только в смене 1, бурильщики вееров есть в смене 2
    # копирование вчерашнего наряда перепроверяет строки
    s, fl = staff(client, D), fleet(client, D)
    y = client.post("/api/dispatch/order", json={"date": "2026-11-12", "shift_no": 1}, headers=D).json()
    assert client.post(f"/api/dispatch/order/{y['id']}/assign", json={"person_id": s["1001"]["id"], "machine_id": fl["Boomer №3"]["id"],
                                                                     "work_type": "drilling"}, headers=D).status_code == 200
    client.put(f"/api/fleet/{fl['Boomer №3']['id']}", json={"status": "repair"}, headers=D)
    r = client.post("/api/dispatch/order", json={"date": "2026-11-13", "shift_no": 1, "copy": "yesterday"}, headers=D).json()
    assert r["copied"] == 0 and r["skipped"][0]["issues"][0]["code"] == "machine_in_repair"
    client.put(f"/api/fleet/{fl['Boomer №3']['id']}", json={"status": "working"}, headers=D)


def test_migration_of_previous_version(client, H):
    """Данные прежней версии: машина без модели и названия, бурильщик со старым жестким кодом профессии."""
    from datetime import timedelta

    from api import qualify
    from common.db import session_scope
    from common.models import Machine, Permit, Person
    from common.timeutil import utcnow

    with session_scope() as db:
        db.add(Machine(mine_id=1, number="Boomer №9", type="dev_drill", model="Boomer M2D", manufacturer="Epiroc",
                       params={"booms": 2, "drill_rate_mph": 80}))
        db.add(Machine(mine_id=1, number="7", type="lhd", model="LH-старый", params={"bucket_t": 10}))
        db.add(Machine(mine_id=1, number="Simba №5", type="ring_drill", model="Simba E7 C", manufacturer="Epiroc",
                       params={"booms": 1, "dia_min": 64, "dia_max": 115, "max_length": 40, "drill_rate_mph": 32}))
        db.add(Machine(mine_id=1, number="8", type="charger", model="", params={"charge_kg_per_h": 420}))
        p = Person(mine_id=1, full_name="Старый Бурильщик", tab_no="8001", profession="driller", professions=[])
        q = Person(mine_id=1, full_name="Свой Профессионал", tab_no="8002", profession="welder", professions=[])
        db.add_all([p, q])
        db.flush()
        db.add(Permit(person_id=p.id, kind="machine", target="ring_drill", valid_to=utcnow() + timedelta(days=100)))
        db.flush()
        res = qualify.migrate_patch01(db)
        again = qualify.migrate_patch01(db)
    assert res == {"machines": 4, "persons": 2} and again == {"machines": 0, "persons": 0}
    E = H["engineer"]
    rep = client.get("/api/migration/patch01", headers=E).json()
    m = {x["number"]: x for x in rep["machines"]}
    assert "Simba №5" in m and m["Simba №5"]["overrides"] == []  # adopt: параметры модели целиком
    assert m["Boomer №9"]["result"] == "matched" and m["Boomer №9"]["overrides"] == ["drill_rate_mph"]
    assert m["7"]["result"] == "custom" and m["7"]["name"] == "LH-старый №7"
    fl = fleet(client, E)
    assert fl["LH-старый №7"]["params"]["payload_t"] == 10 and "bucket_t" not in fl["LH-старый №7"]["params"]
    assert fl["Зарядная машина №8"]["params"]["charge_kg_min"] == 7.0
    pr = {x["tab_no"]: x for x in rep["persons"]}
    assert pr["8001"]["professions"] == ["ring_driller"] and pr["8001"]["auto_permits"][0]["label"] == "Бурение вееров"
    assert pr["8002"]["unknown"] and pr["8002"]["professions"] == ["welder"]
    # подтверждение автодопуска снимает отметку и убирает из «ждут проверки»
    pid = pr["8001"]["auto_permits"][0]["permit_id"]
    assert client.put(f"/api/staff/permits/{pid}", json={"number": "55/26"}, headers=E).status_code == 200
    rep = client.get("/api/migration/patch01", headers=E).json()
    assert next(x for x in rep["persons"] if x["tab_no"] == "8001")["pending"] == 0


# ---------------- машина ↔ вид работ ↔ забой ----------------
def test_machine_work_face_compatibility(client, H):
    D = H["dispatcher"]
    fl = fleet(client, D)
    dev, stope = ready_face(client, D, "dev"), ready_face(client, D, "stope")
    # Simba на проходческий забой — отказ с понятным текстом
    bad = errors(check(client, D, machine_id=fl["Simba №21"]["id"], face_id=dev["id"], work_type="ring_drilling"))
    codes = {i["code"]: i["params"] for i in bad}
    assert codes["face_kind_mismatch"]["machine"] == "Simba №21" and codes["face_kind_mismatch"]["face"] == dev["name"]
    assert "work_face_mismatch" in codes
    # Boomer на камеру — отказ; Boomer на бурение вееров — машина не для этой работы
    bad = {i["code"] for i in errors(check(client, D, machine_id=fl["Boomer №1"]["id"], face_id=stope["id"], work_type="drilling"))}
    assert {"face_kind_mismatch", "work_face_mismatch"} <= bad
    bad = {i["code"] for i in errors(check(client, D, machine_id=fl["Boomer №1"]["id"], face_id=stope["id"],
                                           work_type="ring_drilling"))}
    assert "machine_wrong_type" in bad
    # допустимые пары
    assert not errors(check(client, D, machine_id=fl["Boomer №1"]["id"], face_id=dev["id"], work_type="drilling"))
    assert not errors(check(client, D, machine_id=fl["Simba №21"]["id"], face_id=stope["id"], work_type="ring_drilling",
                            direction="up"))
    # защита API: прямой запрос на назначение отклоняется
    o = client.post("/api/dispatch/order", json={"date": "2026-11-14", "shift_no": 1}, headers=D).json()
    r = client.post(f"/api/dispatch/order/{o['id']}/assign", json={"machine_id": fl["Simba №21"]["id"], "face_id": dev["id"],
                                                                  "work_type": "drilling"}, headers=D)
    assert r.status_code == 400 and r.json()["detail"]["code"] in ("errors.machine_wrong_type", "errors.face_kind_mismatch")


def test_candidates_filter_machines_and_faces(client, H):
    D = H["dispatcher"]
    fl = fleet(client, D)
    r = client.get("/api/dispatch/candidates", params={"work_type": "ring_drilling"}, headers=D).json()
    assert {m["type"] for m in r["machines"]} == {"ring_drill"}
    assert r["faces"] and all(f["direction"] in ("down", "up") for f in r["faces"])
    r = client.get("/api/dispatch/candidates", params={"work_type": "drilling", "machine_id": fl["Boomer №1"]["id"]},
                   headers=D).json()
    names = {f["label"] for f in r["faces"]}
    assert not any(n.startswith("Камера") for n in names) and "ПШ−200 (С)" in names
    assert {m["type"] for m in r["machines"]} == {"dev_drill"}


def test_ring_direction_and_drill_drive(client, H):
    D = H["dispatcher"]
    r = client.get("/api/dispatch/candidates", params={"work_type": "ring_drilling"}, headers=D).json()
    by = {}
    for f in r["faces"]:
        by.setdefault(f["face_id"], {})[f["direction"]] = f
    fid, opts = next((k, v) for k, v in by.items() if v["up"]["ok"] and v["down"]["ok"])
    assert "восходящие (из БДО" in opts["up"]["label"] and "нисходящие (из БДО" in opts["down"]["label"]
    assert opts["up"]["label"] != opts["down"]["label"]  # разные буровые выработки
    fl = fleet(client, D)
    s = staff(client, D)
    o = client.post("/api/dispatch/order", json={"date": "2026-11-15", "shift_no": 1}, headers=D).json()
    r = client.post(f"/api/dispatch/order/{o['id']}/assign", json={"person_id": s["1007"]["id"], "machine_id": fl["Simba №22"]["id"],
                                                                  "face_id": fid, "work_type": "ring_drilling",
                                                                  "direction": "down"}, headers=D)
    assert r.status_code == 200, r.text
    row = client.get("/api/dispatch/order", params={"date": "2026-11-15", "shift_no": 1}, headers=D).json()["order"]["assignments"][0]
    assert row["direction"] == "down" and "нисходящие" in row["face_name"]
    det = client.get(f"/api/workflow/faces/{fid}", headers=D).json()
    assert det["rings"]["name"].endswith("(нисходящие)")  # проект вееров забоя переключен на направление наряда
    # камера без проекта нисходящих вееров / буровая выработка не пройдена
    from sqlalchemy import select

    from common.db import session_scope
    from common.models import Face, RingDesign, Stope, Working

    with session_scope() as db:
        st = db.get(Stope, db.get(Face, fid).stope_id)
        for rd in db.scalars(select(RingDesign).where(RingDesign.stope_id == st.id)):
            if (rd.input or {}).get("direction") == "down":
                rd.status = "archived"
        db.get(Working, st.drive_id).status = "planned"
    issues = {i["code"] for i in errors(check(client, D, machine_id=fl["Simba №21"]["id"], face_id=fid, work_type="ring_drilling",
                                              direction="down"))}
    assert "rings_not_designed" in issues
    issues = {i["code"] for i in errors(check(client, D, machine_id=fl["Simba №21"]["id"], face_id=fid, work_type="ring_drilling",
                                              direction="up"))}
    assert "drill_drive_status" in issues


def test_type_works_editable(client, H):
    E, D = H["engineer"], H["dispatcher"]
    tw = client.get("/api/fleet/type-works", headers=E).json()
    assert tw["ring_drill"] == ["ring_drilling"]
    assert client.put("/api/fleet/type-works", json={"aux": tw["aux"] + ["support"]}, headers=D).status_code == 403
    r = client.put("/api/fleet/type-works", json={"aux": tw["aux"] + ["support"]}, headers=E)
    assert r.status_code == 200 and "support" in r.json()["aux"]
    m = client.get("/api/dispatch/candidates", params={"work_type": "support"}, headers=D).json()["machines"]
    assert "aux" in {x["type"] for x in m}
    client.put("/api/fleet/type-works", json={"aux": tw["aux"]}, headers=E)


# ---------------- смены и график ВР ----------------
@pytest.mark.parametrize("n,hours", [(1, 24), (2, 12), (3, 8), (4, 6)])
def test_default_shift_tables(n, hours):
    from core import shifts

    t = shifts.default_table(n, "07:00")
    assert [shifts.duration(r["start"], r["end"]) for r in t] == [hours * 60] * n and t[0]["start"] == "07:00"
    assert shifts.validate_table(t) == []
    w = shifts.default_windows(t)
    assert len(w) == n and shifts.validate_windows(t, w) == []
    assert all(shifts.duration(x["start"], x["end"]) == 60 and x["end"] == r["end"] for x, r in zip(w, t))


def test_shift_over_midnight_belongs_to_start_date():
    from datetime import datetime, timezone

    from core import shifts

    cfg = shifts.from_config({"table": [{"no": 1, "start": "07:00", "end": "15:00"}, {"no": 2, "start": "15:00", "end": "23:00"},
                                        {"no": 3, "start": "23:00", "end": "07:00"}]})
    assert shifts.validate(cfg) == []
    cur = shifts.current(cfg, datetime(2026, 10, 7, 2, 0, tzinfo=timezone.utc), "UTC")
    assert cur["shift_no"] == 3 and cur["date"] == "2026-10-06"
    assert shifts.previous(cfg, "2026-10-07", 1, "UTC") == ("2026-10-06", 3)
    w = shifts.windows(cfg, "2026-10-06", 3, "UTC")  # окно 06:00–07:00 следующего дня
    assert w[0]["start"] == datetime(2026, 10, 7, 6, 0, tzinfo=timezone.utc)


def test_shift_gap_overlap_total():
    from core import shifts

    gap = shifts.validate_table([{"no": 1, "start": "07:00", "end": "15:00"}, {"no": 2, "start": "15:30", "end": "23:00"},
                                 {"no": 3, "start": "23:00", "end": "07:00"}])
    assert gap[0]["code"] == "shift_gap" and gap[0]["params"] == {"a": 1, "b": 2, "end": "15:00", "start": "15:30", "minutes": 30}
    ov = shifts.validate_table([{"no": 1, "start": "07:00", "end": "15:00"}, {"no": 2, "start": "15:00", "end": "23:00"},
                                {"no": 3, "start": "22:00", "end": "07:00"}])
    o = next(e for e in ov if e["code"] == "shift_overlap")
    assert o["params"]["a"] == 2 and o["params"]["b"] == 3 and o["params"]["minutes"] == 60
    assert (o["params"]["from"], o["params"]["to"]) == ("22:00", "23:00") and o["field"] == {"row": 2, "key": "start"}
    short = shifts.validate_table([{"no": 1, "start": "00:00", "end": "08:00"}, {"no": 2, "start": "08:00", "end": "16:00"},
                                   {"no": 3, "start": "16:00", "end": "23:00"}])
    assert next(e for e in short if e["code"] == "shift_total")["params"] == {"minutes": 1380, "missing": 60}
    # окно ВР вне своей смены
    t = shifts.default_table(3, "00:00")
    bad = shifts.validate_windows(t, [{"shift": 1, "start": "07:30", "end": "08:30"}])
    assert bad[0]["code"] == "blast_window_outside"
    assert shifts.validate_windows(t, []) == []  # смены без ВР допустимы


def _local(client, h):
    from datetime import datetime
    from zoneinfo import ZoneInfo

    tz = client.get("/api/mine", headers=h).json()["config"]["timezone"]
    return datetime.now(ZoneInfo(tz))


def _set_shifts(client, h, windows):
    r = client.put("/api/mine/config", json={"shifts": {"table": [{"no": 1, "start": "00:00", "end": "00:00"}],
                                                        "blast_windows": windows, "reentry_min": 0}}, headers=h)
    assert r.status_code == 200, r.text


def _hm(dt):
    return dt.strftime("%H:%M")


def test_shift_settings_validation_api(client, H):
    E = H["engineer"]
    bad = {"table": [{"no": 1, "start": "07:00", "end": "15:00"}, {"no": 2, "start": "15:30", "end": "07:00"}]}
    r = client.put("/api/mine/config", json={"shifts": bad}, headers=E)
    assert r.status_code == 400 and r.json()["detail"]["code"] == "errors.shift_gap"
    assert r.json()["detail"]["params"]["minutes_text"] == "30 мин"
    v = client.post("/api/mine/shifts/validate", json={"table": [{"no": 1, "start": "00:00", "end": "08:00"},
                                                                  {"no": 2, "start": "08:00", "end": "16:00"},
                                                                  {"no": 3, "start": "16:00", "end": "23:00"}]}, headers=E).json()
    assert any(i["code"] == "shift_total" and i["params"]["missing_text"] == "1 ч" for i in v["issues"])
    d = client.post("/api/mine/shifts/default", json={"count": 3, "start": "00:00"}, headers=E).json()
    assert [r["end"] for r in d["table"]] == ["08:00", "16:00", "00:00"]
    assert [(w["start"], w["end"]) for w in d["blast_windows"]] == [("07:00", "08:00"), ("15:00", "16:00"), ("23:00", "00:00")]


def test_blasted_only_inside_window_and_carry_over(client, H):
    from datetime import timedelta

    from common.db import session_scope
    from common.models import Face, FaceEvent
    from common.timeutil import utcnow

    E, D, A = H["engineer"], H["dispatcher"], H["admin"]
    now = _local(client, E)
    fid = ready_face(client, D, "dev")["id"]
    with session_scope() as db:
        f = db.get(Face, fid)
        f.status, f.status_since = "charged", utcnow() - timedelta(hours=3)
    # окно ВР было час назад — сейчас вне окна
    _set_shifts(client, E, [{"shift": 1, "start": _hm(now - timedelta(hours=2)), "end": _hm(now - timedelta(hours=1))}])
    r = client.post(f"/api/workflow/faces/{fid}/transition", json={"to": "blasted"}, headers=D)
    assert r.status_code == 400 and r.json()["detail"]["code"] == "errors.blast_outside_window"
    r = client.post(f"/api/workflow/faces/{fid}/transition", json={"to": "blasted"}, headers=A)
    assert r.json()["detail"]["code"] == "errors.blast_override_reason"
    # перенос: заряжен, окно прошло → «Ждет ВР» и алерт диспетчеру
    from alerts.main import evaluate

    evaluate()
    det = client.get(f"/api/workflow/faces/{fid}", headers=D).json()
    assert det["status"] == "wait_blast"
    al = [a for a in client.get("/api/alerts?status=open", headers=D).json() if a["rule"] == "blast_moved"]
    assert al and det["name"] in al[0]["title"]
    # администратор — с обязательной причиной, пишется в журнал
    r = client.post(f"/api/workflow/faces/{fid}/transition", json={"to": "blasted", "override_reason": "пожар — срочно"},
                    headers=A)
    assert r.status_code == 200, r.text
    with session_scope() as db:
        from sqlalchemy import select

        ev = db.scalars(select(FaceEvent).where(FaceEvent.face_id == fid).order_by(FaceEvent.id.desc())).first()
        assert ev.to_status == "blasted" and "пожар" in ev.comment
    rep = client.get("/api/reports/period", params={"period": "day"}, headers=E).json()
    assert rep["blasting"]["outside_window"] >= 1 and rep["blasting"]["moved_to_next"] >= 1


def test_no_assignments_during_blast_window(client, H):
    from datetime import timedelta

    E, D = H["engineer"], H["dispatcher"]
    now = _local(client, E)
    _set_shifts(client, E, [{"shift": 1, "start": _hm(now - timedelta(minutes=30)), "end": _hm(now + timedelta(minutes=30))}])
    cur = client.get("/api/dispatch/order", headers=D).json()
    o = cur["order"] or client.post("/api/dispatch/order", json={}, headers=D).json()
    s, fl = staff(client, D), fleet(client, D)
    r = client.post(f"/api/dispatch/order/{o['id']}/assign", json={"person_id": s["1003"]["id"], "machine_id": fl["Boomer №3"]["id"],
                                                                  "work_type": "drilling"}, headers=D)
    assert r.status_code == 400 and r.json()["detail"]["code"] == "errors.blast_in_progress"
    clock = client.get("/api/clock", headers=D).json()
    assert clock["blast"]["now"] and clock["shift"]["shift_no"] == 1
    _set_shifts(client, E, [])
