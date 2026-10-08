"""Модели машин, профессии, виды работ; название и модель машины, номер уникален
в пределах рудника; несколько профессий и наставник у человека; дата выдачи, скан и отметка автодопуска.

Ревизия 0001 создает схему по текущим моделям (create_all), поэтому на новой базе таблицы и колонки уже есть —
каждое изменение выполняется, только если его еще нет.

Revision ID: 0002
"""
import sqlalchemy as sa
from alembic import op

from common.models import J, MachineModel, Profession, WorkKind

revision = "0002"
down_revision = "0001"

COLUMNS = {
    "fleet": [sa.Column("name", sa.String(128), nullable=False, server_default=""),
              sa.Column("model_id", sa.Integer, nullable=True)],
    "staff": [sa.Column("professions", J, nullable=True),
              sa.Column("mentor_id", sa.Integer, nullable=True)],
    "permits": [sa.Column("issued_at", sa.DateTime(timezone=True), nullable=True),
                sa.Column("file_key", sa.String(256), nullable=False, server_default=""),
                sa.Column("auto", sa.Boolean, nullable=False, server_default=sa.false())],
}


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    tables = set(insp.get_table_names())
    for model in (MachineModel, Profession, WorkKind):
        if model.__tablename__ not in tables:
            model.__table__.create(bind)
    for table, cols in COLUMNS.items():
        have = {c["name"] for c in insp.get_columns(table)}
        for col in cols:
            if col.name not in have:
                op.add_column(table, col)
    # профессия: код новой профессии длиннее, допуск model:<id>
    op.alter_column("staff", "profession", type_=sa.String(48))
    op.alter_column("permits", "target", type_=sa.String(48))
    # номер машины уникален в пределах рудника, а не во всей базе
    for uc in insp.get_unique_constraints("fleet"):
        if uc["column_names"] == ["number"]:
            op.drop_constraint(uc["name"], "fleet", type_="unique")
    if not any(uc["name"] == "uq_fleet_mine_number" for uc in insp.get_unique_constraints("fleet")):
        op.create_unique_constraint("uq_fleet_mine_number", "fleet", ["mine_id", "number"])


def downgrade():
    op.drop_constraint("uq_fleet_mine_number", "fleet", type_="unique")
    op.create_unique_constraint("fleet_number_key", "fleet", ["number"])
    for table, cols in COLUMNS.items():
        for col in cols:
            op.drop_column(table, col.name)
    for model in (WorkKind, Profession, MachineModel):
        model.__table__.drop(op.get_bind())
