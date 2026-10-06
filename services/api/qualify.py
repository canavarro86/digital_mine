"""Модели машин, профессии и допуски : справочники, подписи, проверка допусков человека,
перенос данных прежней версии с отчётом для проверки."""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from common import i18n
from common.models import Machine, MachineModel, Permit, Person, Profession, WorkKind
from common.settings import load_yaml
from common.timeutil import utcnow

AUTO_PERMIT_DAYS = 30  # срок автодопуска при переносе — до проверки документов


def fleet_types() -> dict:
    return load_yaml("fleet_types.yaml").get("types", {})


def type_works(db: Session) -> dict[str, list[str]]:
    """Допустимые виды работ по типам машин: правка из интерфейса (настройка fleet_type_works) поверх config."""
    from .svc import get_setting

    over = get_setting(db, "fleet_type_works") or {}
    return {k: list(over.get(k, v.get("work", []))) for k, v in fleet_types().items()}


def fleet_params() -> dict:
    return load_yaml("fleet_types.yaml").get("params", {})


def aware(dt: datetime | None) -> datetime | None:
    return dt if dt is None or dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def title(t: dict | str | None, lang: str) -> str:
    if isinstance(t, str):
        return t
    t = t or {}
    return t.get(lang) or t.get("ru") or t.get("en") or next(iter(t.values()), "")


# ---------------- модели машин ----------------
def model_label(m: MachineModel) -> str:
    """«Axera DD421», «Simba E7 C»: короткое имя добавляется, если его нет в названии модели."""
    if m.short_name and m.short_name.lower() not in m.model.lower():
        return f"{m.short_name} {m.model}"
    return m.model


def auto_name(number: str, model: MachineModel | None, type_label: str = "", raw_model: str = "") -> str:
    """Название машины по умолчанию: «Axera №48». Номер с буквами («Boomer №1») уже является названием.
    Без модели из справочника — первое слово модели из карточки («Axera 7» → «Axera»), иначе тип машины."""
    number = (number or "").strip()
    if not re.fullmatch(r"[\d\-/.]+", number):
        return number
    raw = (raw_model or "").split()
    base = (model.short_name or model.model) if model else (raw[0] if raw else type_label)
    return f"{base} №{number}".strip()


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9а-я]", "", (s or "").lower())


def match_model(db: Session, manufacturer: str, model: str, mtype: str = "") -> MachineModel | None:
    """Модель по названию: точное совпадение, затем одно название внутри другого (того же типа)."""
    if not model:
        return None
    models = list(db.scalars(select(MachineModel)))
    key = _norm(model)
    exact = [m for m in models if _norm(m.model) == key or _norm(model_label(m)) == key]
    if manufacturer:
        exact = [m for m in exact if _norm(m.manufacturer) == _norm(manufacturer)] or exact
    if exact:
        return exact[0]
    loose = [m for m in models if (not mtype or m.type == mtype) and len(_norm(m.model)) >= 3
             and (_norm(m.model) in key or key in _norm(m.model))]
    return loose[0] if len(loose) == 1 else None


def machine_dict(mc: Machine, models: dict[int, MachineModel], lang: str = "ru") -> dict:
    d = mc.as_dict()
    d["label"] = mc.label
    m = models.get(mc.model_id) if mc.model_id else None
    d["model_label"] = model_label(m) if m else (mc.model or "")
    d["custom"] = m is None
    base = (m.params if m else {}) or {}
    d["overrides"] = sorted(k for k, v in (mc.params or {}).items() if k in base and base[k] != v) if m else []
    return d


# ---------------- справочники ----------------
def seed_catalogs(db: Session) -> None:
    """Модели, виды работ и профессии из config/: добавляются только отсутствующие записи."""
    have = {(m.manufacturer, m.model) for m in db.scalars(select(MachineModel))}
    for m in load_yaml("machine_models.yaml").get("models", []):
        if (m["manufacturer"], m["model"]) not in have:
            db.add(MachineModel(manufacturer=m["manufacturer"], model=m["model"], short_name=m.get("short_name", ""),
                                type=m["type"], params=m.get("params") or {}, verify=m.get("verify", True),
                                source=m.get("source", ""), builtin=True))
    db.flush()
    cfg = load_yaml("staff.yaml")
    have_w = {w.code for w in db.scalars(select(WorkKind))}
    for w in cfg.get("work_kinds", []):
        if w["code"] not in have_w:
            db.add(WorkKind(code=w["code"], title=w["title"], requires_permit=w.get("requires_permit", True),
                            assignable=w.get("assignable", True), builtin=True))
    have_p = {p.code for p in db.scalars(select(Profession))}
    for p in cfg.get("professions", []):
        if p["code"] not in have_p:
            db.add(Profession(code=p["code"], title=p["title"], permits=[resolve_target(db, x) for x in p.get("permits", [])],
                              trainee=p.get("trainee", False), builtin=True))
    db.flush()


def resolve_target(db: Session, pm: dict) -> dict:
    """model:<производитель>/<модель> из файлов конфигурации → model:<id> в базе."""
    t = str(pm.get("target", ""))
    if pm.get("kind") == "machine" and t.startswith("model:") and "/" in t:
        man, mod = t[6:].split("/", 1)
        m = db.scalar(select(MachineModel).where(MachineModel.manufacturer == man, MachineModel.model == mod))
        t = f"model:{m.id}" if m else t
    return {**pm, "target": t}


class Labels:
    """Подписи допусков, видов работ и машин на языке пользователя (кэш на один запрос)."""

    def __init__(self, db: Session, lang: str = "ru"):
        self.db, self.lang = db, lang
        self.models = {m.id: m for m in db.scalars(select(MachineModel))}
        self.works = {w.code: w for w in db.scalars(select(WorkKind))}
        self.profs = {p.code: p for p in db.scalars(select(Profession))}
        self.types = fleet_types()

    def type_label(self, code: str) -> str:
        return i18n.t(f"fleet.types.{code}", self.lang) if code else ""

    def work_label(self, code: str) -> str:
        w = self.works.get(code)
        return title(w.title, self.lang) if w else i18n.t(f"dispatch.work.{code}", self.lang)

    def prof_label(self, code: str) -> str:
        p = self.profs.get(code)
        return title(p.title, self.lang) if p else code

    def target_label(self, kind: str, target: str) -> str:
        if kind == "work":
            return self.work_label(target)
        if target.startswith("model:"):
            m = self.models.get(int(target[6:])) if target[6:].isdigit() else None
            return model_label(m) if m else target
        return self.type_label(target)

    def machine_requirement(self, mc: Machine) -> str:
        """Чего не хватает для машины: модель («Simba E7 C»), а у нестандартной установки — тип."""
        m = self.models.get(mc.model_id) if mc.model_id else None
        return model_label(m) if m else self.type_label(mc.type)

    def join(self, items: list[str]) -> str:
        return i18n.t("staff.missing_join", self.lang).join(items)

    def is_trainee(self, p: Person) -> bool:
        return any(self.profs[c].trainee for c in (p.professions or []) if c in self.profs)


# ---------------- допуски ----------------
def permit_state(valid_to: datetime, warn_days: int = 14, now: datetime | None = None) -> str:
    now = now or utcnow()
    vt = aware(valid_to)
    if vt < now:
        return "expired"
    if vt < now + timedelta(days=warn_days):
        return "expiring"
    return "valid"


def machine_targets(mc: Machine) -> set[str]:
    return {mc.type} | ({f"model:{mc.model_id}"} if mc.model_id else set())


def requirements(L: Labels, machine: Machine | None, work_type: str) -> list[tuple[str, set[str], str]]:
    """Какие допуски нужны: [(kind, допустимые цели, подпись)] — на машину (модель или тип) и на вид работ."""
    req = []
    if machine:
        req.append(("machine", machine_targets(machine), L.machine_requirement(machine)))
    w = L.works.get(work_type)
    if w is None or w.requires_permit:
        req.append(("work", {work_type}, L.work_label(work_type)))
    return req


def person_permit_issues(L: Labels, person: Person, machine: Machine | None, work_type: str, when: datetime,
                         permits: list[Permit], warn_days: int = 14, kinds: tuple = ("machine", "work")) -> list[dict]:
    """Действующие допуски человека на машину и на вид работ. Текст ошибки называет, чего не хватает."""
    missing, expired, expiring = [], [], []
    for kind, targets, label in requirements(L, machine, work_type):
        if kind not in kinds:
            continue
        own = [p for p in permits if p.kind == kind and p.target in targets]
        valid = [p for p in own if aware(p.valid_to) >= when]
        if not own:
            missing.append(label)
        elif not valid:
            expired.append(label)
        elif all(aware(p.valid_to) < when + timedelta(days=warn_days) for p in valid):
            expiring.append(label)
    out = []
    if missing:
        out.append({"level": "error", "code": "no_permit", "params": {"person": person.full_name, "what": L.join(missing)}})
    if expired:
        out.append({"level": "error", "code": "permit_expired",
                    "params": {"person": person.full_name, "what": L.join(expired)}})
    if expiring:
        out.append({"level": "warning", "code": "permit_expiring",
                    "params": {"person": person.full_name, "what": L.join(expiring), "days": warn_days}})
    return out


def permits_by_person(db: Session) -> dict[int, list[Permit]]:
    out: dict[int, list[Permit]] = {}
    for p in db.scalars(select(Permit)):
        out.setdefault(p.person_id, []).append(p)
    return out


def qualified(L: Labels, permits: list[Permit], machine: Machine | None, work_type: str, when: datetime) -> bool:
    for kind, targets, _ in requirements(L, machine, work_type):
        if not any(p.kind == kind and p.target in targets and aware(p.valid_to) >= when for p in permits):
            return False
    return True


# ---------------- перенос данных прежней версии ----------------
REPORT_KEY = "migration_patch01"


def migrate_patch01(db: Session) -> dict:
    """Машины → модели и названия, старые ключи параметров; люди → профессии из справочника и их допуски
    по умолчанию (отметка auto, срок AUTO_PERMIT_DAYS). Идемпотентно; найденное дописывается в отчёт."""
    from .svc import get_setting, set_setting

    cfg_types = load_yaml("fleet_types.yaml")
    renamed = cfg_types.get("renamed", {})
    types = cfg_types.get("types", {})
    machines, persons = [], []
    adopt = {(x["manufacturer"], x["model"]) for x in load_yaml("machine_models.yaml").get("models", []) if x.get("adopt")}
    for mc in db.scalars(select(Machine).order_by(Machine.id)):
        if mc.name:
            continue
        params = dict(mc.params or {})
        for old, new in renamed.items():
            if old in params:
                v = params.pop(old)
                if isinstance(new, dict):
                    params[new["to"]] = round(float(v) * float(new["factor"]), 2)
                else:
                    params[new] = v
        m = match_model(db, mc.manufacturer, mc.model, mc.type)
        if m and m.type != mc.type:
            m = None
        if m:
            mc.model_id, mc.manufacturer, mc.model = m.id, m.manufacturer, m.model
            # модели с adopt: true — параметры модели целиком (Simba E7 C: 89–127 мм, 51 м по данным Epiroc)
            params = dict(m.params) if (m.manufacturer, m.model) in adopt else {**m.params, **params}
        else:
            params = {**types.get(mc.type, {}).get("defaults", {}), **params}
        mc.params = params
        mc.name = auto_name(mc.number, m, i18n.t(f"fleet.types.{mc.type}", "ru"), mc.model)
        machines.append({"id": mc.id, "number": mc.number, "name": mc.name, "type": mc.type,
                         "model": f"{mc.manufacturer} {mc.model}".strip(), "result": "matched" if m else "custom",
                         "model_label": model_label(m) if m else "",
                         "overrides": sorted(k for k, v in params.items() if m and k in m.params and m.params[k] != v)})
    legacy = load_yaml("staff.yaml").get("legacy", {})
    profs = {p.code: p for p in db.scalars(select(Profession))}
    now = utcnow()
    all_permits = permits_by_person(db)
    for p in db.scalars(select(Person).order_by(Person.id)):
        if p.professions:
            continue
        own = all_permits.get(p.id, [])
        old = p.profession or ""
        if old in profs:
            codes = [old]
        elif old == "driller":
            ring = any(x.kind == "machine" and x.target == "ring_drill" for x in own)
            dev = any(x.kind == "machine" and x.target == "dev_drill" for x in own)
            codes = (["dev_driller"] if dev or not ring else []) + (["ring_driller"] if ring else [])
        else:
            codes = list(legacy.get(old, []))
        unknown = not codes
        if unknown and old:  # своя профессия прежней версии — в справочник, без допусков по умолчанию
            profs[old] = Profession(code=old, title={"ru": old}, permits=[])
            db.add(profs[old])
            codes = [old]
        elif unknown:
            codes = ["miner"]
        p.professions = codes
        p.profession = codes[0] if codes else old
        added = []
        for code in codes:
            for d in profs[code].permits or []:
                if any(x.kind == d["kind"] and x.target == d["target"] for x in own):
                    continue
                pm = Permit(person_id=p.id, kind=d["kind"], target=d["target"], valid_to=now + timedelta(days=AUTO_PERMIT_DAYS),
                            issued_at=None, number="", auto=True)
                db.add(pm)
                own.append(pm)
                added.append({"kind": d["kind"], "target": d["target"]})
        if added or unknown:
            persons.append({"id": p.id, "full_name": p.full_name, "tab_no": p.tab_no, "old": old, "professions": codes,
                            "unknown": unknown, "auto_permits": added})
    db.flush()
    if machines or persons:
        rep = get_setting(db, REPORT_KEY) or {}
        set_setting(db, REPORT_KEY, {"ts": now.isoformat(), "auto_permit_days": AUTO_PERMIT_DAYS,
                                     "machines": (rep.get("machines") or []) + machines,
                                     "persons": (rep.get("persons") or []) + persons})
    return {"machines": len(machines), "persons": len(persons)}
