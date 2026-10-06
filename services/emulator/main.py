"""Эмулятор рудника и пульт (раздел 15.4).

Ведёт буровые (Boomer, Simba), ПДМ и зарядную машину по наряду, проходит все статусы забоев через API
(как диспетчер, инженер, взрывники, маркшейдер), генерирует отчёты бурения, журналы заряжания и сканы
с отклонениями по включённым сценариям. Каждый цикл несёт эталон (ожидаемая причина) для проверки анализатора.
Время событий — реальное; скорость ×1…×500 сжимает длительность работ.
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone

import httpx
import numpy as np
from fastapi import Depends, Header, HTTPException

from common.bus import connect, envelope
from common.settings import get_settings
from common.web import EVENTS, create_app
from core import scans, simulate

log = logging.getLogger("emulator")
app = create_app("emulator")

DEV_SCENARIOS = ["drill_deviation", "short_holes", "water", "fracturing", "blocky_collapse", "cleavage",
                 "missing_contour", "overcharge"]
STOPE_SCENARIOS = ["ring_deviation", "overcharge", "undercharge", "blocked_holes", "weak_hw", "delay_errors"]
OPS_SCENARIOS = ["blasters_late", "machine_idle", "machine_breakdown"]
K = {"weak": 0.5, "medium": 1.0, "strong": 1.6}
# длительности шагов, часы (реальные условия рудника)
STEP_H = {"drilled": 0.3, "recalculated": 0.2, "handed": 0.7, "charged": 0.4, "blasted": 0.5, "ventilation": 0.5,
          "mucking": 2.0, "scaling": 0.8, "support": 1.5, "surveyed": 0.3, "analyzed": 0.1, "draw": 4.0, "cms": 0.5}
NEXT = {"drilled": "recalculated", "recalculated": "handed", "handed": "accepted", "charged": "blasted", "wait_blast": "blasted",
        "blasted": "ventilation", "ventilation": "mucking", "mucking": "scaling", "scaling": "support",
        "support": "surveyed", "surveyed": "analyzed", "analyzed": "ready"}
NEXT_STOPE = {**NEXT, "blasted": "draw", "draw": "cms", "cms": "analyzed"}


def now() -> datetime:
    return datetime.now(timezone.utc)


def check_token(x_internal_token: str | None = Header(default=None)):
    if x_internal_token != get_settings().internal_token:
        raise HTTPException(403, "forbidden")


class Api:
    def __init__(self):
        s = get_settings()
        # без keep-alive: каждое соединение заново балансируется Service между подами api,
        # иначе вся нагрузка эмулятора идёт в один под и HPA добавляет пустые реплики
        self.c = httpx.AsyncClient(base_url=s.api_url, timeout=120,
                                   limits=httpx.Limits(max_keepalive_connections=0),
                                   headers={"x-internal-token": s.internal_token, "x-acting-user": "emulator"})

    async def get(self, path, **params):
        r = await self.c.get(path, params=params)
        r.raise_for_status()
        return r.json()

    async def post(self, path, body=None, ok=(200,), as_user="emulator"):
        r = await self.c.post(path, json=body or {}, headers={"x-acting-user": as_user})
        if r.status_code not in ok:
            return {"_error": r.status_code, **(r.json() if r.headers.get("content-type", "").startswith("application/json") else {})}
        return r.json()

    async def put(self, path, body):
        r = await self.c.put(path, json=body)
        return r.json()


class Emulator:
    def __init__(self):
        self.running = False
        self.speed = 60.0
        self.scenarios: dict[str, str] = {}
        self.auto_dispatch = True
        self.dispatch_delay_h = 1.5
        self.load = {"enabled": False, "rate": 800, "calc": True}
        self.rng = np.random.default_rng()
        self.faces: dict[int, dict] = {}
        self.progress: dict[int, dict] = {}
        self.free_since: dict[int, datetime] = {}
        self.positions: dict[int, list] = {}
        self.log: list[dict] = []
        self.stats = {"cycles": 0, "drill_reports": 0, "scans": 0, "events": 0, "errors": 0, "load_sent": 0}
        self.order_key = None
        self.task: asyncio.Task | None = None
        self.load_task: asyncio.Task | None = None
        self.js = None
        self.api = Api()

    # ---------- журнал пульта ----------
    def note(self, msg: str, **kw) -> None:
        self.log.insert(0, {"ts": now().isoformat(), "msg": msg, **kw})
        del self.log[200:]

    def state(self) -> dict:
        return {"running": self.running, "speed": self.speed, "scenarios": self.scenarios, "auto_dispatch": self.auto_dispatch,
                "load": self.load, "stats": self.stats, "log": self.log[:60],
                "catalog": {"dev": DEV_SCENARIOS, "stope": STOPE_SCENARIOS, "ops": OPS_SCENARIOS,
                            "strengths": list(K)},
                "faces": {str(k): v for k, v in self.faces.items()}, "progress": {str(k): v for k, v in self.progress.items()}}

    # ---------- сценарий цикла ----------
    def pick(self, kind: str) -> tuple[str, float]:
        pool = [s for s in (DEV_SCENARIOS if kind == "dev" else STOPE_SCENARIOS) if s in self.scenarios]
        if pool and self.rng.random() < 0.9:
            s = str(self.rng.choice(pool))
            return s, K[self.scenarios[s]]
        return "none", 0.0

    # ---------- основной цикл ----------
    async def run(self) -> None:
        if self.js is None:
            try:
                _, self.js = await connect()
            except Exception as e:
                log.warning("NATS: %s", e)
        await self.refresh_positions()
        await self.save_runtime()
        last_tele = 0.0
        while self.running:
            t0 = asyncio.get_event_loop().time()
            dt_h = 2.0 * self.speed / 3600
            try:
                await self.ensure_order()
                faces = await self.api.get("/api/workflow/faces")
                board = await self.api.get("/api/dispatch/board")
                # взрыв — только в окне ВР по графику смен рудника
                self.blast_now = bool((await self.api.get("/api/mine/shifts")).get("blast_now"))
                await self.step_faces(faces, board, dt_h)
                await self.dispatch(faces, board)
                if t0 - last_tele >= 2:
                    await self.telemetry(faces, board)
                    last_tele = t0
            except Exception as e:
                self.stats["errors"] += 1
                log.exception("tick")
                self.note(f"error: {e}")
            await asyncio.sleep(max(0.2, 2.0 - (asyncio.get_event_loop().time() - t0)))

    async def save_runtime(self) -> None:
        try:
            cur = (await self.api.get("/api/settings")).get("emulator") or {}
            await self.api.put("/api/settings/emulator", {"value": {**cur, "speed": self.speed, "running": self.running,
                                                                    "scenarios": self.scenarios, "auto_dispatch": self.auto_dispatch}})
        except Exception as e:
            log.debug("runtime: %s", e)

    async def refresh_positions(self) -> None:
        sc = await self.api.get("/api/mine/scene")
        self.positions = {f["id"]: f["pos"] for f in sc["faces"]}

    # ---------- наряд ----------
    async def ensure_order(self) -> None:
        o = await self.api.get("/api/dispatch/order")
        key = (o["date"], o["shift_no"])
        if o["order"] is None:
            await self.api.post("/api/dispatch/order", {"copy": "previous"}, as_user="emulator-dispatcher")
            o = await self.api.get("/api/dispatch/order")
            self.note(f"наряд {key[0]} смена {key[1]} создан (копия предыдущей)")
        if self.order_key != key:
            self.order_key = key
            await self.auto_assign(o["order"])

    async def auto_assign(self, order: dict) -> None:
        """Буровые — на готовые забои; люди — только с действующими допусками на машину и вид работ
        (список кандидатов API, допущенные первыми), своей смены в приоритете."""
        if not order:
            return
        active = [a for a in order["assignments"] if a["active"]]
        fleet = await self.api.get("/api/fleet")
        faces = await self.api.get("/api/workflow/faces")
        used_m = {a["machine_id"] for a in active}
        used_f = {a["face_id"] for a in active if a["work_type"] in ("drilling", "ring_drilling")}
        for m in fleet:
            if m["id"] in used_m or m["status"] not in ("working", "idle") or m["type"] not in ("dev_drill", "ring_drill"):
                continue
            kind = "dev" if m["type"] == "dev_drill" else "stope"
            work = "drilling" if kind == "dev" else "ring_drilling"
            cand = sorted([f for f in faces if f["kind"] == kind and f["status"] in ("ready", "drilling") and f["id"] not in used_f],
                          key=lambda f: (f["status"] != "drilling", f["priority"]))
            if not cand:
                continue
            people = await self.api.get("/api/dispatch/candidates", work_type=work, order_id=order["id"], machine_id=m["id"])
            for p in [x for x in people.get("persons", []) if x["ok"]]:
                r = await self.api.post(f"/api/dispatch/order/{order['id']}/assign",
                                        {"person_id": p["id"], "machine_id": m["id"], "face_id": cand[0]["id"],
                                         "work_type": work}, as_user="emulator-dispatcher")
                if "_error" not in r:
                    used_f.add(cand[0]["id"])
                    self.note(f"наряд: {p['full_name']} — {m['label']} — {cand[0]['name']}")
                    break

    # ---------- забои ----------
    async def step_faces(self, faces: list[dict], board: dict, dt_h: float) -> None:
        drill_rows = {r["face_id"]: r for r in board["rows"] if r["work_type"] in ("drilling", "ring_drilling")}
        for f in faces:
            fid, st = f["id"], f["status"]
            fs = self.faces.setdefault(fid, {"cycle": f["cycle_no"], "wait_h": 0.0})
            if fs.get("cycle") != f["cycle_no"]:
                self.faces[fid] = fs = {"cycle": f["cycle_no"], "wait_h": 0.0}
            if st == "done":
                await self.replace_done(f)
                continue
            if st in ("ready", "drilling"):
                row = drill_rows.get(fid)
                if row:
                    await self.drill(f, row, fs, dt_h)
                continue
            if st == "accepted":
                fs["wait_h"] += dt_h
                if fs["wait_h"] >= 0.6:
                    await self.charge(f, fs)
                continue
            nxt = (NEXT if f["kind"] == "dev" else NEXT_STOPE).get(st)
            if not nxt:
                continue
            if nxt == "blasted" and not getattr(self, "blast_now", False):
                continue  # заряжен — ждёт окна ВР (вне окна сервер переводит забой в «Ждёт ВР»)
            need = STEP_H.get(st, 0.5)
            if st == "handed" and "blasters_late" in self.scenarios:
                need = 2.5 + 2 * K[self.scenarios["blasters_late"]]
            fs["wait_h"] += dt_h
            if fs["wait_h"] < need:
                continue
            fs["wait_h"] = 0.0
            if nxt in ("surveyed", "cms"):
                await self.survey(f, fs)
            elif nxt == "analyzed":
                r = await self.api.post(f"/api/workflow/faces/{fid}/transition", {"to": "analyzed"}, as_user="emulator-engineer")
                if "_error" not in r:
                    self.stats["cycles"] += 1
            elif nxt == "recalculated":
                await self.api.post(f"/api/workflow/faces/{fid}/recalc", as_user="emulator-engineer")
            else:
                user = {"accepted": "emulator-blaster", "blasted": "emulator-blaster"}.get(nxt, "emulator-foreman")
                await self.api.post(f"/api/workflow/faces/{fid}/transition", {"to": nxt}, as_user=user)

    async def drill(self, f: dict, row: dict, fs: dict, dt_h: float) -> None:
        fid = f["id"]
        if "plan" not in fs:
            det = await self.api.get(f"/api/workflow/faces/{fid}")
            if f["kind"] == "dev":
                if not det.get("passport"):
                    return
                pdes = det["passport"]["design"]
                c = pdes["contour"]
                fs["plan"] = {"holes": list(pdes["holes"]), "drill_m": det["passport"]["indicators"]["drill_m"],
                              "pid": det["passport"]["id"],
                              "centroid": (sum(p[0] for p in c) / len(c), sum(p[1] for p in c) / len(c))}
            else:
                if not det.get("rings"):
                    return
                rings_ = det["rings"]["design"]["rings"]  # камера отрабатывается одним взрывом
                holes = [{**h, "ring": r["no"]} for r in rings_ for h in r["holes"]]
                fs["plan"] = {"holes": holes, "drill_m": sum(h["length"] for h in holes)}
            fs["done_m"] = 0.0
            fs["scenario"], fs["k"] = self.pick(f["kind"])
            if f["status"] == "ready":
                await self.api.post(f"/api/workflow/faces/{fid}/transition", {"to": "drilling"}, as_user="emulator-foreman")
        machine = row["machine"]
        rate = 85.0 if f["kind"] == "dev" else 34.0
        booms = 2 if f["kind"] == "dev" else 1
        if "machine_breakdown" in self.scenarios and machine.endswith("№1"):
            return  # машина стоит — алерт простоя
        fs["done_m"] += dt_h * rate * booms * 0.75
        total = fs["plan"]["drill_m"]
        holes = fs["plan"]["holes"]
        n_total = len([h for h in holes if h.get("type") != "empty"])
        done = min(n_total, int(n_total * fs["done_m"] / total))
        left_h = max(total - fs["done_m"], 0) / (rate * booms * 0.75) / self.speed
        prog = {"holes_done": done, "holes_total": n_total, "eta": (now() + timedelta(hours=left_h)).isoformat(),
                "updated": now().isoformat()}
        if f["kind"] == "stope" and holes:
            h = holes[min(done, len(holes) - 1)]
            prog.update(ring=h["ring"], hole=h["id"], ring_holes=sum(1 for x in holes if x["ring"] == h["ring"]))
        last = self.progress.get(row["assignment_id"], {})
        if done != last.get("holes_done"):
            self.progress[row["assignment_id"]] = prog
            await self.api.post(f"/api/dispatch/assignments/{row['assignment_id']}/progress", prog)
        if fs["done_m"] >= total:
            await self.report(f, fs, row)

    async def report(self, f: dict, fs: dict, row: dict) -> None:
        s, k = fs["scenario"], fs["k"]
        holes = []
        rng = self.rng
        mid, pid = row.get("machine_id"), row.get("person_id")
        if f["kind"] == "dev":
            holes = simulate.dev_drill(fs["plan"]["holes"], s, k, rng, fs["plan"]["centroid"])
        else:
            holes = simulate.stope_drill(fs["plan"]["holes"], s, k, rng)
        r = await self.api.post(f"/api/workflow/faces/{f['id']}/drill-report",
                                {"holes": holes, "machine_id": mid, "person_id": pid, "source": "emulator",
                                 "scenario": {"name": s, "k": k}},
                                as_user="emulator-driller")
        if "_error" not in r:
            self.stats["drill_reports"] += 1
            self.free_since[row["assignment_id"]] = now()
            self.note(f"{row['machine']}: {f['name']} обурен", scenario=s)

    async def restore_scenario(self, fs: dict, det: dict) -> None:
        """После перезапуска эмулятора сценарий цикла берётся из отчёта буровой."""
        if "scenario" not in fs:
            sc = ((det.get("drill_report") or {}).get("summary") or {}).get("scenario") or {}
            fs["scenario"], fs["k"] = sc.get("name", "none"), float(sc.get("k", 0))

    async def charge(self, f: dict, fs: dict) -> None:
        det = await self.api.get(f"/api/workflow/faces/{f['id']}")
        await self.restore_scenario(fs, det)
        s, k = fs.get("scenario", "none"), fs.get("k", 0)
        rc = det.get("recalc")
        rng = self.rng
        if f["kind"] == "dev":
            src = (rc or {}).get("result") or det["passport"]["design"]
            holes = simulate.dev_charge(src["holes"], s, k, rng)
        else:
            src = (rc or {}).get("result") or det["rings"]["design"]
            holes = simulate.stope_charge(src["rings"], s, k, rng)
        await self.api.post(f"/api/workflow/faces/{f['id']}/charge-log", {"holes": holes}, as_user="emulator-blaster")

    async def survey(self, f: dict, fs: dict) -> None:
        det = await self.api.get(f"/api/workflow/faces/{f['id']}")
        await self.restore_scenario(fs, det)
        s, k = fs.get("scenario", "none"), fs.get("k", 0)
        strength = simulate.strength_name(k)
        obs = simulate.observations(s, k)
        if f["kind"] == "dev":
            pd = det["passport"]["design"]
            adv = pd["params"]["kish"] * float(pd["input"]["hole_depth"])
            contour = sum(1 for h in pd["holes"] if h["type"] == "contour")
            eff = {s: strength} if s in scans.DEV_EFFECTS else {}
            data = scans.gen_dev_scan(pd["input"]["section"], adv, eff, self.rng, contour_holes=contour,
                                      chainage0=f["chainage"])
        else:
            st = await self.api.get(f"/api/rings/stopes/{f['stope_id']}")
            eff = {s: strength} if s in scans.STOPE_EFFECTS else {}
            data = scans.gen_cms(st, eff, self.rng)
        data["observations"] = obs
        data["scenario"] = {"name": s, "strength": strength if s != "none" else None, "expected": s}
        await self.api.post(f"/api/workflow/faces/{f['id']}/scan", {"data": data}, as_user="emulator-surveyor")
        self.stats["scans"] += 1

    async def replace_done(self, f: dict) -> None:
        """Забой закончен: ввести в работу следующую выработку / камеру."""
        if f.get("_replaced"):
            return
        self.faces[f["id"]]["_replaced"] = True
        if f["kind"] == "stope":
            stopes = await self.api.get("/api/rings/stopes")
            nxt = next((s for s in stopes if s["status"] == "planned" and s["level_bottom"] in (-225, -250)), None)
            if nxt:
                await self.api.post(f"/api/rings/stopes/{nxt['id']}/activate", {}, as_user="emulator-engineer")
                self.note(f"камера {nxt['name']} введена в работу")
        else:
            ws = await self.api.get("/api/workings", status="planned")
            nxt = next((w for w in ws if w["type"] in ("xc", "fwd") and w["level"] in (-200, -225, -250)), None)
            if nxt:
                await self.api.put(f"/api/workings/{nxt['id']}", {"status": "driving"})
                sug = await self.api.get("/api/passports/suggest", working_id=nxt["id"], chainage=0)
                tp = sug["candidates"][0]["id"] if sug["candidates"] else None
                p = await self.api.post("/api/passports/dev", {"working_id": nxt["id"], "typical_id": tp},
                                        as_user="emulator-engineer")
                if "id" in p:
                    await self.api.post(f"/api/passports/dev/{p['id']}/status", {"status": "review"})
                    await self.api.post(f"/api/passports/dev/{p['id']}/status", {"status": "approved"})
                await self.refresh_positions()
                self.note(f"выработка {nxt['name']} в проходке, паспорт {p.get('number', '')}")

    # ---------- диспетчеризация ----------
    async def dispatch(self, faces: list[dict], board: dict) -> None:
        if not self.auto_dispatch:
            return
        fmap = {f["id"]: f for f in faces}
        for r in board["rows"]:
            if r["work_type"] not in ("drilling", "ring_drilling"):
                continue
            f = fmap.get(r["face_id"])
            if not f or f["status"] in ("ready", "drilling"):
                continue
            since = self.free_since.get(r["assignment_id"])
            if not since:
                self.free_since[r["assignment_id"]] = since = now()
            if (now() - since).total_seconds() / 3600 * self.speed < self.dispatch_delay_h:
                continue
            fleet = {m["label"]: m for m in await self.api.get("/api/fleet")}
            m = fleet.get(r["machine"])
            rf = await self.api.get("/api/dispatch/ready-faces", machine_id=m["id"], face_id=f["id"])
            if not rf["faces"]:
                continue
            tgt = rf["faces"][0]
            res = await self.api.post("/api/dispatch/reassign", {"assignment_id": r["assignment_id"],
                                                                 "face_id": tgt["face_id"], "reason": "auto"},
                                      as_user="emulator-dispatcher")
            if "_error" not in res:
                self.note(f"перестановка: {r['machine']} → {tgt['name']}")
                self.free_since.pop(r["assignment_id"], None)

    # ---------- телеметрия ----------
    async def telemetry(self, faces: list[dict], board: dict) -> None:
        if not self.js:
            return
        rows = {r["machine"]: r for r in board["rows"]}
        fleet = await self.api.get("/api/fleet")
        fpos = {f["name"]: self.positions.get(f["id"]) for f in faces}
        for m in fleet:
            if "machine_idle" in self.scenarios and m["label"] == "ПДМ №32":
                continue  # машина не отвечает → алерт «Машина простаивает»
            r = rows.get(m["label"])
            pos = fpos.get(r["face"]) if r else None
            status = m["status"]
            if r and m["status"] == "working":
                busy = (r["work_type"] in ("drilling", "ring_drilling") and r["face_status"] in ("ready", "drilling"))
                status = "working" if busy or r["work_type"] not in ("drilling", "ring_drilling") else "idle"
            elif m["status"] == "working":
                status = "idle"
            p = pos or [0, 0, 0]
            await self.js.publish("dm.telemetry", envelope("telemetry", {
                "machine": m["label"], "machine_type": m["type"], "status": status, "face": r["face"] if r else "",
                "operator": r["person"] if r else "", "x": p[0], "y": p[1], "z": p[2],
                "engine_hours": m["engine_hours"]}))
            self.stats["events"] += 1
        EVENTS.labels("emulator", "telemetry").inc(len(fleet))

    # ---------- нагрузка для HPA ----------
    async def load_loop(self) -> None:
        s = get_settings()
        calc = httpx.AsyncClient(base_url=s.calc_url, timeout=60)
        inp = None
        while self.load["enabled"]:
            t0 = asyncio.get_event_loop().time()
            rate = int(self.load.get("rate", 800))
            if self.js:
                for i in range(rate):
                    await self.js.publish("dm.telemetry", envelope("telemetry", {
                        "machine": f"LOAD-{i % 50}", "machine_type": "load", "status": "load", "x": i, "y": 0, "z": 0}))
                self.stats["load_sent"] += rate
            if self.load.get("calc"):
                if inp is None:
                    dp = (await self.api.get("/api/passports/dev"))[0]
                    inp = (await self.api.get(f"/api/passports/dev/{dp['id']}"))["input"]
                try:
                    await asyncio.gather(*[calc.post("/calc/load", json={"n": 2, "input": inp}) for _ in range(3)])
                except Exception:
                    pass
            await asyncio.sleep(max(0.05, 1.0 - (asyncio.get_event_loop().time() - t0)))


EMU = Emulator()


@app.get("/emulator/state", dependencies=[Depends(check_token)])
def state():
    return EMU.state()


@app.post("/emulator/start", dependencies=[Depends(check_token)])
async def start(body: dict | None = None):
    body = body or {}
    if body.get("speed"):
        EMU.speed = max(1.0, min(500.0, float(body["speed"])))
    if not EMU.running:
        EMU.running = True
        EMU.task = asyncio.get_event_loop().create_task(EMU.run())
        EMU.note(f"старт ×{EMU.speed:g}")
    return EMU.state()


@app.post("/emulator/pause", dependencies=[Depends(check_token)])
async def pause(body: dict | None = None):
    EMU.running = False
    await EMU.save_runtime()
    EMU.note("пауза")
    return EMU.state()


@app.post("/emulator/reset", dependencies=[Depends(check_token)])
async def reset(body: dict | None = None):
    EMU.running = False
    EMU.load["enabled"] = False
    EMU.scenarios = {}
    EMU.faces, EMU.progress, EMU.free_since = {}, {}, {}
    EMU.stats = {k: 0 for k in EMU.stats}
    EMU.order_key = None
    await EMU.save_runtime()
    EMU.note("сброс")
    return EMU.state()


@app.post("/emulator/speed", dependencies=[Depends(check_token)])
async def speed(body: dict):
    EMU.speed = max(1.0, min(500.0, float(body["speed"])))
    await EMU.save_runtime()
    EMU.note(f"скорость ×{EMU.speed:g}")
    return EMU.state()


@app.post("/emulator/scenarios", dependencies=[Depends(check_token)])
async def scenarios(body: dict):
    """{name: weak|medium|strong|null}. null — выключить."""
    for name, strength in body.items():
        if name not in DEV_SCENARIOS + STOPE_SCENARIOS + OPS_SCENARIOS:
            continue
        if strength in K:
            EMU.scenarios[name] = strength
        else:
            EMU.scenarios.pop(name, None)
    EMU.note("сценарии: " + json.dumps(EMU.scenarios, ensure_ascii=False))
    asyncio.get_event_loop().create_task(EMU.save_runtime())
    return EMU.state()


@app.post("/emulator/auto", dependencies=[Depends(check_token)])
async def auto(body: dict):
    EMU.auto_dispatch = bool(body.get("auto_dispatch", True))
    await EMU.save_runtime()
    if body.get("delay_h"):
        EMU.dispatch_delay_h = float(body["delay_h"])
    return EMU.state()


@app.post("/emulator/load", dependencies=[Depends(check_token)])
async def load(body: dict):
    EMU.load.update({k: body[k] for k in ("enabled", "rate", "calc") if k in body})
    if EMU.load["enabled"] and (EMU.load_task is None or EMU.load_task.done()):
        if EMU.js is None:
            try:
                _, EMU.js = await connect()
            except Exception as e:
                raise HTTPException(503, str(e))
        EMU.load_task = asyncio.get_event_loop().create_task(EMU.load_loop())
    EMU.note(f"нагрузка: {EMU.load}")
    return EMU.state()


@app.on_event("startup")
async def autostart() -> None:
    """Автозапуск после рестарта пода, если эмулятор был включён (настройка emulator.running)."""
    async def _later():
        await asyncio.sleep(30)
        try:
            cur = (await EMU.api.get("/api/settings")).get("emulator") or {}
            if cur.get("running"):
                EMU.speed = float(cur.get("speed", 60))
                EMU.scenarios = dict(cur.get("scenarios") or {})
                EMU.auto_dispatch = bool(cur.get("auto_dispatch", True))
                await start({})
        except Exception as e:
            log.info("autostart: %s", e)

    asyncio.get_event_loop().create_task(_later())

