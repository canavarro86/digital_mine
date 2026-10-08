"""Модели PostgreSQL. Сложные структуры (геометрия, скважины, расчеты) — в JSON-полях."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

J = JSON().with_variant(JSONB(), "postgresql")


def utcnow() -> datetime:
    from .timeutil import utcnow as now

    return now()


class Base(DeclarativeBase):
    def as_dict(self) -> dict:
        out = {}
        for c in self.__table__.columns:
            v = getattr(self, c.key)
            if isinstance(v, datetime):
                if v.tzinfo is None:
                    v = v.replace(tzinfo=timezone.utc)
                v = v.isoformat()
            out[c.key] = v
        return out


TS = DateTime(timezone=True)


# ---------------- пользователи ----------------
class Role(Base):
    __tablename__ = "roles"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True)
    title: Mapped[dict] = mapped_column(J, default=dict)  # {"ru": "...", "en": "..."}
    permissions: Mapped[list] = mapped_column(J, default=list)
    builtin: Mapped[bool] = mapped_column(Boolean, default=False)
    grafana_role: Mapped[str] = mapped_column(String(16), default="Viewer")


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True)
    password_hash: Mapped[str] = mapped_column(String(128))
    full_name: Mapped[str] = mapped_column(String(128), default="")
    role_id: Mapped[int] = mapped_column(ForeignKey("roles.id"))
    lang: Mapped[str] = mapped_column(String(8), default="ru")
    tz: Mapped[str] = mapped_column(String(64), default="Asia/Bangkok")
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow)


class AuditLog(Base):
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(primary_key=True)
    ts: Mapped[datetime] = mapped_column(TS, default=utcnow, index=True)
    user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    username: Mapped[str] = mapped_column(String(64), default="")
    action: Mapped[str] = mapped_column(String(64))
    entity: Mapped[str] = mapped_column(String(64), default="")
    entity_id: Mapped[str] = mapped_column(String(64), default="")
    details: Mapped[dict] = mapped_column(J, default=dict)


class Setting(Base):
    __tablename__ = "settings"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[dict] = mapped_column(J, default=dict)


# ---------------- рудник ----------------
class Mine(Base):
    __tablename__ = "mines"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(128))
    path: Mapped[str] = mapped_column(String(256), default="")
    config: Mapped[dict] = mapped_column(J, default=dict)
    active: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow)


class Working(Base):
    """Выработка: ось (полилиния x,y,z), сечение, статус, источник."""
    __tablename__ = "workings"
    id: Mapped[int] = mapped_column(primary_key=True)
    mine_id: Mapped[int] = mapped_column(ForeignKey("mines.id"), index=True)
    name: Mapped[str] = mapped_column(String(128))
    type: Mapped[str] = mapped_column(String(32))  # ramp, access, fwd, xc, raise, sump, niche, other
    level: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="planned")  # planned, driving, done, closed
    source: Mapped[str] = mapped_column(String(16), default="system")  # system, import, demo, designer
    axis: Mapped[list] = mapped_column(J, default=list)
    section: Mapped[dict] = mapped_column(J, default=dict)
    parent_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    attach_chainage: Mapped[float | None] = mapped_column(Float, nullable=True)
    direction: Mapped[str] = mapped_column(String(8), default="")
    seq: Mapped[int | None] = mapped_column(Integer, nullable=True)
    typical_passport_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    props: Mapped[dict] = mapped_column(J, default=dict)
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(TS, default=utcnow, onupdate=utcnow)


class Stope(Base):
    """Очистная камера: границы (y0..y1 по простиранию, x лежачего/висячего бока на отметках)."""
    __tablename__ = "stopes"
    id: Mapped[int] = mapped_column(primary_key=True)
    mine_id: Mapped[int] = mapped_column(ForeignKey("mines.id"), index=True)
    name: Mapped[str] = mapped_column(String(128))
    level_bottom: Mapped[float] = mapped_column(Float)
    level_top: Mapped[float] = mapped_column(Float)
    drive_id: Mapped[int | None] = mapped_column(Integer, nullable=True)  # нижний БДО
    upper_drive_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    geometry: Mapped[dict] = mapped_column(J, default=dict)
    grades: Mapped[dict] = mapped_column(J, default=dict)
    status: Mapped[str] = mapped_column(String(24), default="planned")
    props: Mapped[dict] = mapped_column(J, default=dict)


class Orebody(Base):
    __tablename__ = "orebodies"
    id: Mapped[int] = mapped_column(primary_key=True)
    mine_id: Mapped[int] = mapped_column(ForeignKey("mines.id"), index=True)
    name: Mapped[str] = mapped_column(String(128))
    mesh: Mapped[dict] = mapped_column(J, default=dict)  # {"vertices": [...], "faces": [...]}
    props: Mapped[dict] = mapped_column(J, default=dict)


# ---------------- геология ----------------
class RockType(Base):
    __tablename__ = "rock_types"
    id: Mapped[int] = mapped_column(primary_key=True)
    mine_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    code: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(128))
    kind: Mapped[str] = mapped_column(String(16), default="waste")  # ore, waste, contact
    f: Mapped[float] = mapped_column(Float, default=10)
    ucs: Mapped[float | None] = mapped_column(Float, nullable=True)
    density: Mapped[float] = mapped_column(Float, default=2.7)
    fracture_cat: Mapped[int] = mapped_column(Integer, default=3)
    fracture_spacing: Mapped[float | None] = mapped_column(Float, nullable=True)
    rqd: Mapped[float | None] = mapped_column(Float, nullable=True)
    rmr: Mapped[float | None] = mapped_column(Float, nullable=True)
    q: Mapped[float | None] = mapped_column(Float, nullable=True)
    water: Mapped[str] = mapped_column(String(16), default="dry")  # dry, damp, dripping, flowing, inflow
    inflow_lpm: Mapped[float | None] = mapped_column(Float, nullable=True)
    grades: Mapped[dict] = mapped_column(J, default=dict)  # {"Cu": {"value": 1.2, "unit": "%"}}
    extra: Mapped[dict] = mapped_column(J, default=dict)  # параметры из config/rocks.yaml


class GeologyAssignment(Base):
    """Назначение свойств: interval (по пикетам) > working > zone (камера/3D-зона) > mine."""
    __tablename__ = "geology_assignments"
    id: Mapped[int] = mapped_column(primary_key=True)
    mine_id: Mapped[int] = mapped_column(ForeignKey("mines.id"), index=True)
    target: Mapped[str] = mapped_column(String(16))
    name: Mapped[str] = mapped_column(String(128), default="")
    working_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    ch_from: Mapped[float | None] = mapped_column(Float, nullable=True)
    ch_to: Mapped[float | None] = mapped_column(Float, nullable=True)
    stope_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    zone: Mapped[dict] = mapped_column(J, default=dict)  # {"min": [x,y,z], "max": [x,y,z]}
    rock_type_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    overrides: Mapped[dict] = mapped_column(J, default=dict)  # water, fracture_cat, f, faults: [...]


# ---------------- ВВ ----------------
class Explosive(Base):
    __tablename__ = "explosives"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(128))
    manufacturer: Mapped[str] = mapped_column(String(128), default="")
    type: Mapped[str] = mapped_column(String(16))  # emulsion, anfo, cartridge
    density_min: Mapped[float] = mapped_column(Float)
    density_max: Mapped[float] = mapped_column(Float)
    vod: Mapped[float] = mapped_column(Float)
    rws: Mapped[float] = mapped_column(Float)
    rbs: Mapped[float] = mapped_column(Float)
    heat: Mapped[float | None] = mapped_column(Float, nullable=True)
    gas: Mapped[float | None] = mapped_column(Float, nullable=True)
    water_resistance: Mapped[str] = mapped_column(String(16), default="none")  # none, limited, full
    crit_diameter: Mapped[float] = mapped_column(Float, default=25)
    min_diameter: Mapped[float] = mapped_column(Float, default=32)
    cart_diameter: Mapped[float | None] = mapped_column(Float, nullable=True)
    cart_length: Mapped[float | None] = mapped_column(Float, nullable=True)
    cart_mass: Mapped[float | None] = mapped_column(Float, nullable=True)
    price: Mapped[float] = mapped_column(Float, default=1.5)  # за кг
    builtin: Mapped[bool] = mapped_column(Boolean, default=False)


class InitiationDevice(Base):
    __tablename__ = "initiation_devices"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(128))
    kind: Mapped[str] = mapped_column(String(16))  # primer, nonel, edd, detcord
    props: Mapped[dict] = mapped_column(J, default=dict)
    price: Mapped[float] = mapped_column(Float, default=0)
    builtin: Mapped[bool] = mapped_column(Boolean, default=False)


# ---------------- паспорта ----------------
class CutTemplate(Base):
    __tablename__ = "cut_library"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(128))
    type: Mapped[str] = mapped_column(String(32))  # prismatic, slot, spiral, wedge, pyramid, custom
    params: Mapped[dict] = mapped_column(J, default=dict)
    holes: Mapped[list] = mapped_column(J, default=list)  # относительные координаты (для custom)
    builtin: Mapped[bool] = mapped_column(Boolean, default=False)


class TypicalPassport(Base):
    __tablename__ = "typical_passports"
    id: Mapped[int] = mapped_column(primary_key=True)
    mine_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    number: Mapped[str] = mapped_column(String(32))
    name: Mapped[str] = mapped_column(String(256))
    working_type: Mapped[str] = mapped_column(String(32))
    section: Mapped[dict] = mapped_column(J, default=dict)
    f_min: Mapped[float] = mapped_column(Float, default=0)
    f_max: Mapped[float] = mapped_column(Float, default=20)
    water: Mapped[list] = mapped_column(J, default=list)  # допустимые обводненности
    explosive_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    input: Mapped[dict] = mapped_column(J, default=dict)
    design: Mapped[dict] = mapped_column(J, default=dict)
    indicators: Mapped[dict] = mapped_column(J, default=dict)
    version: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(16), default="draft")  # draft, review, approved, archived
    approved_by: Mapped[str] = mapped_column(String(64), default="")
    approved_at: Mapped[datetime | None] = mapped_column(TS, nullable=True)
    created_by: Mapped[str] = mapped_column(String(64), default="")
    attachments: Mapped[list] = mapped_column(J, default=list)
    assigned: Mapped[dict] = mapped_column(J, default=dict)  # {"working_types": [], "working_ids": [], "intervals": []}
    updated_at: Mapped[datetime] = mapped_column(TS, default=utcnow, onupdate=utcnow)


class TypicalPassportVersion(Base):
    __tablename__ = "typical_passport_versions"
    id: Mapped[int] = mapped_column(primary_key=True)
    passport_id: Mapped[int] = mapped_column(ForeignKey("typical_passports.id"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    data: Mapped[dict] = mapped_column(J, default=dict)
    changes: Mapped[list] = mapped_column(J, default=list)
    changed_by: Mapped[str] = mapped_column(String(64), default="")
    ts: Mapped[datetime] = mapped_column(TS, default=utcnow)
    note: Mapped[str] = mapped_column(Text, default="")


class DevPassport(Base):
    """Паспорт БВР на проходку конкретного забоя."""
    __tablename__ = "dev_passports"
    id: Mapped[int] = mapped_column(primary_key=True)
    working_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    number: Mapped[str] = mapped_column(String(32), default="")
    name: Mapped[str] = mapped_column(String(256), default="")
    status: Mapped[str] = mapped_column(String(16), default="draft")
    typical_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    parent_id: Mapped[int | None] = mapped_column(Integer, nullable=True)  # копия (ИИ, пересчет)
    input: Mapped[dict] = mapped_column(J, default=dict)
    design: Mapped[dict] = mapped_column(J, default=dict)
    indicators: Mapped[dict] = mapped_column(J, default=dict)
    signatures: Mapped[dict] = mapped_column(J, default=dict)
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_by: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(TS, default=utcnow, onupdate=utcnow)


class RingDesign(Base):
    __tablename__ = "ring_designs"
    id: Mapped[int] = mapped_column(primary_key=True)
    stope_id: Mapped[int] = mapped_column(Integer, index=True)
    name: Mapped[str] = mapped_column(String(256), default="")
    status: Mapped[str] = mapped_column(String(16), default="draft")
    input: Mapped[dict] = mapped_column(J, default=dict)
    design: Mapped[dict] = mapped_column(J, default=dict)
    indicators: Mapped[dict] = mapped_column(J, default=dict)
    created_by: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(TS, default=utcnow, onupdate=utcnow)


class CorrectionPlan(Base):
    __tablename__ = "correction_plans"
    id: Mapped[int] = mapped_column(primary_key=True)
    stope_id: Mapped[int] = mapped_column(Integer, index=True)
    scan_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    design: Mapped[dict] = mapped_column(J, default=dict)
    economics: Mapped[dict] = mapped_column(J, default=dict)
    status: Mapped[str] = mapped_column(String(16), default="proposed")  # proposed, accepted, rejected, done
    result: Mapped[dict] = mapped_column(J, default=dict)
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow)


# ---------------- флот и персонал ----------------
class MachineModel(Base):
    """Модель машины (справочник «Флот → Модели»): тип и технические параметры по паспорту производителя."""
    __tablename__ = "machine_models"
    __table_args__ = (UniqueConstraint("manufacturer", "model"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    manufacturer: Mapped[str] = mapped_column(String(64), default="")
    model: Mapped[str] = mapped_column(String(64))
    short_name: Mapped[str] = mapped_column(String(32), default="")  # для автоназвания машины: «Axera №48»
    type: Mapped[str] = mapped_column(String(32))
    params: Mapped[dict] = mapped_column(J, default=dict)
    verify: Mapped[bool] = mapped_column(Boolean, default=True)  # «проверить по паспорту машины»
    source: Mapped[str] = mapped_column(String(64), default="")
    note: Mapped[str] = mapped_column(Text, default="")
    builtin: Mapped[bool] = mapped_column(Boolean, default=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class Machine(Base):
    __tablename__ = "fleet"
    __table_args__ = (UniqueConstraint("mine_id", "number", name="uq_fleet_mine_number"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    mine_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    number: Mapped[str] = mapped_column(String(64))  # номер уникален в пределах рудника
    name: Mapped[str] = mapped_column(String(128), default="")  # «Axera №48» — выводится в списках и отчетах
    type: Mapped[str] = mapped_column(String(32))  # dev_drill, ring_drill, lhd, charger, bolter, aux, other
    model_id: Mapped[int | None] = mapped_column(Integer, nullable=True)  # None — нестандартная установка
    model: Mapped[str] = mapped_column(String(64), default="")
    manufacturer: Mapped[str] = mapped_column(String(64), default="")
    year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    params: Mapped[dict] = mapped_column(J, default=dict)
    status: Mapped[str] = mapped_column(String(16), default="working")  # working, idle, repair, maintenance
    engine_hours: Mapped[float] = mapped_column(Float, default=0)
    working_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

    @property
    def label(self) -> str:
        return self.name or self.number


class Profession(Base):
    """Профессия: название и допуски по умолчанию для нового человека."""
    __tablename__ = "professions"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(48), unique=True)
    title: Mapped[dict] = mapped_column(J, default=dict)  # {"ru": "...", "en": "..."}
    permits: Mapped[list] = mapped_column(J, default=list)  # [{"kind": "machine"|"work", "target": "..."}]
    trainee: Mapped[bool] = mapped_column(Boolean, default=False)
    builtin: Mapped[bool] = mapped_column(Boolean, default=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class WorkKind(Base):
    """Вид работ — он же допуск «на вид работ»."""
    __tablename__ = "work_kinds"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True)
    title: Mapped[dict] = mapped_column(J, default=dict)
    requires_permit: Mapped[bool] = mapped_column(Boolean, default=True)
    assignable: Mapped[bool] = mapped_column(Boolean, default=True)
    builtin: Mapped[bool] = mapped_column(Boolean, default=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class Person(Base):
    __tablename__ = "staff"
    id: Mapped[int] = mapped_column(primary_key=True)
    mine_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    full_name: Mapped[str] = mapped_column(String(128))
    tab_no: Mapped[str] = mapped_column(String(32), unique=True)
    profession: Mapped[str] = mapped_column(String(48))  # основная (первая) профессия — для отчетов
    professions: Mapped[list] = mapped_column(J, default=list)  # совмещение: ["miner", "aux_operator"]
    mentor_id: Mapped[int | None] = mapped_column(Integer, nullable=True)  # наставник стажера
    crew: Mapped[str] = mapped_column(String(32), default="")
    shift: Mapped[int] = mapped_column(Integer, default=1)
    contacts: Mapped[str] = mapped_column(String(128), default="")
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class Permit(Base):
    __tablename__ = "permits"
    id: Mapped[int] = mapped_column(primary_key=True)
    person_id: Mapped[int] = mapped_column(ForeignKey("staff.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(16))  # machine, work
    target: Mapped[str] = mapped_column(String(48))  # тип машины, model:<id> или вид работ
    valid_to: Mapped[datetime] = mapped_column(TS)
    issued_at: Mapped[datetime | None] = mapped_column(TS, nullable=True)
    number: Mapped[str] = mapped_column(String(32), default="")
    file_key: Mapped[str] = mapped_column(String(256), default="")  # скан документа
    auto: Mapped[bool] = mapped_column(Boolean, default=False)  # выдан автоматически при переносе — проверить


# ---------------- расстановка ----------------
class ShiftOrder(Base):
    __tablename__ = "shift_orders"
    __table_args__ = (UniqueConstraint("mine_id", "date", "shift_no"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    mine_id: Mapped[int] = mapped_column(Integer)
    date: Mapped[str] = mapped_column(String(10))  # дата смены по времени рудника
    shift_no: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16), default="draft")  # draft, active, closed
    created_by: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow)


class Assignment(Base):
    __tablename__ = "assignments"
    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("shift_orders.id", ondelete="CASCADE"), index=True)
    person_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    machine_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    face_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    work_type: Mapped[str] = mapped_column(String(32))  # drilling, ring_drilling, charging, mucking, support, scaling, survey
    direction: Mapped[str | None] = mapped_column(String(8), nullable=True)  # веера: down — нисходящие, up — восходящие
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    progress: Mapped[dict] = mapped_column(J, default=dict)
    started_at: Mapped[datetime] = mapped_column(TS, default=utcnow)
    ended_at: Mapped[datetime | None] = mapped_column(TS, nullable=True)


class Reassignment(Base):
    __tablename__ = "reassignments"
    id: Mapped[int] = mapped_column(primary_key=True)
    assignment_id: Mapped[int] = mapped_column(Integer, index=True)
    new_assignment_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ts: Mapped[datetime] = mapped_column(TS, default=utcnow)
    username: Mapped[str] = mapped_column(String(64), default="")
    change: Mapped[dict] = mapped_column(J, default=dict)
    reason: Mapped[str] = mapped_column(String(256), default="")


# ---------------- рабочий процесс ----------------
class Face(Base):
    """Забой проходки (kind=dev, на выработке) или очистной блок (kind=stope)."""
    __tablename__ = "faces"
    id: Mapped[int] = mapped_column(primary_key=True)
    mine_id: Mapped[int] = mapped_column(Integer, index=True)
    kind: Mapped[str] = mapped_column(String(8))
    working_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    stope_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(24), default="ready")
    cycle_no: Mapped[int] = mapped_column(Integer, default=1)
    passport_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ring_design_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    chainage: Mapped[float] = mapped_column(Float, default=0)  # текущее положение забоя по оси
    priority: Mapped[int] = mapped_column(Integer, default=5)
    status_since: Mapped[datetime] = mapped_column(TS, default=utcnow)
    props: Mapped[dict] = mapped_column(J, default=dict)


class FaceEvent(Base):
    __tablename__ = "face_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    face_id: Mapped[int] = mapped_column(Integer, index=True)
    cycle_no: Mapped[int] = mapped_column(Integer)
    from_status: Mapped[str] = mapped_column(String(24))
    to_status: Mapped[str] = mapped_column(String(24))
    ts: Mapped[datetime] = mapped_column(TS, default=utcnow, index=True)
    username: Mapped[str] = mapped_column(String(64), default="")
    comment: Mapped[str] = mapped_column(Text, default="")


class DrillReport(Base):
    __tablename__ = "drill_reports"
    id: Mapped[int] = mapped_column(primary_key=True)
    face_id: Mapped[int] = mapped_column(Integer, index=True)
    cycle_no: Mapped[int] = mapped_column(Integer)
    machine_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    person_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source: Mapped[str] = mapped_column(String(16), default="manual")  # file, tablet, manual, emulator
    holes: Mapped[list] = mapped_column(J, default=list)
    summary: Mapped[dict] = mapped_column(J, default=dict)
    file_key: Mapped[str] = mapped_column(String(256), default="")
    received_at: Mapped[datetime] = mapped_column(TS, default=utcnow, index=True)


class PassportRecalc(Base):
    __tablename__ = "passport_recalcs"
    id: Mapped[int] = mapped_column(primary_key=True)
    face_id: Mapped[int] = mapped_column(Integer, index=True)
    cycle_no: Mapped[int] = mapped_column(Integer)
    passport_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    result: Mapped[dict] = mapped_column(J, default=dict)
    created_by: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow)


class ChargeLog(Base):
    __tablename__ = "charge_logs"
    id: Mapped[int] = mapped_column(primary_key=True)
    face_id: Mapped[int] = mapped_column(Integer, index=True)
    cycle_no: Mapped[int] = mapped_column(Integer)
    holes: Mapped[list] = mapped_column(J, default=list)
    summary: Mapped[dict] = mapped_column(J, default=dict)
    created_by: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow)


class Scan(Base):
    __tablename__ = "scans"
    id: Mapped[int] = mapped_column(primary_key=True)
    face_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    stope_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    cycle_no: Mapped[int] = mapped_column(Integer, default=1)
    kind: Mapped[str] = mapped_column(String(8))  # face, cms
    file_key: Mapped[str] = mapped_column(String(256), default="")
    data: Mapped[dict] = mapped_column(J, default=dict)  # профили / карты отклонений
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow)


class Analysis(Base):
    __tablename__ = "analyses"
    id: Mapped[int] = mapped_column(primary_key=True)
    face_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    stope_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    cycle_no: Mapped[int] = mapped_column(Integer, default=1)
    kind: Mapped[str] = mapped_column(String(8))  # dev, stope
    result: Mapped[dict] = mapped_column(J, default=dict)
    causes: Mapped[dict] = mapped_column(J, default=dict)
    scenario: Mapped[dict] = mapped_column(J, default=dict)  # эталон эмулятора
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow, index=True)


# ---------------- алерты, ИИ, импорт ----------------
class Alert(Base):
    __tablename__ = "alerts"
    id: Mapped[int] = mapped_column(primary_key=True)
    ts: Mapped[datetime] = mapped_column(TS, default=utcnow, index=True)
    rule: Mapped[str] = mapped_column(String(48), index=True)
    audience: Mapped[str] = mapped_column(String(16))  # dispatcher, engineer, admin
    severity: Mapped[str] = mapped_column(String(8), default="warning")
    params: Mapped[dict] = mapped_column(J, default=dict)
    entity: Mapped[str] = mapped_column(String(64), default="")
    dedup_key: Mapped[str] = mapped_column(String(128), index=True)
    status: Mapped[str] = mapped_column(String(12), default="open")  # open, ack, resolved
    actions: Mapped[list] = mapped_column(J, default=list)
    resolved_by: Mapped[str] = mapped_column(String(64), default="")
    resolved_at: Mapped[datetime | None] = mapped_column(TS, nullable=True)
    notified: Mapped[bool] = mapped_column(Boolean, default=False)


class AiRequest(Base):
    __tablename__ = "ai_requests"
    id: Mapped[int] = mapped_column(primary_key=True)
    ts: Mapped[datetime] = mapped_column(TS, default=utcnow, index=True)
    username: Mapped[str] = mapped_column(String(64))
    module: Mapped[str] = mapped_column(String(32))
    entity_id: Mapped[str] = mapped_column(String(64), default="")
    provider: Mapped[str] = mapped_column(String(32))
    model: Mapped[str] = mapped_column(String(64))
    lang: Mapped[str] = mapped_column(String(8), default="ru")
    input_hash: Mapped[str] = mapped_column(String(64), index=True)
    tokens_in: Mapped[int] = mapped_column(Integer, default=0)
    tokens_out: Mapped[int] = mapped_column(Integer, default=0)
    cost: Mapped[float] = mapped_column(Float, default=0)
    cache_hit: Mapped[bool] = mapped_column(Boolean, default=False)
    demo: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(16), default="ok")
    request: Mapped[dict] = mapped_column(J, default=dict)
    response: Mapped[dict] = mapped_column(J, default=dict)
    decision: Mapped[str] = mapped_column(String(16), default="")  # applied, rejected


class ImportJob(Base):
    __tablename__ = "import_jobs"
    id: Mapped[int] = mapped_column(primary_key=True)
    ts: Mapped[datetime] = mapped_column(TS, default=utcnow)
    username: Mapped[str] = mapped_column(String(64), default="")
    filename: Mapped[str] = mapped_column(String(256))
    fmt: Mapped[str] = mapped_column(String(16))
    kind: Mapped[str] = mapped_column(String(16))  # workings, stopes, orebody, holes, scan, drill_log
    status: Mapped[str] = mapped_column(String(16), default="parsed")
    file_key: Mapped[str] = mapped_column(String(256), default="")
    parsed: Mapped[dict] = mapped_column(J, default=dict)
    summary: Mapped[dict] = mapped_column(J, default=dict)
