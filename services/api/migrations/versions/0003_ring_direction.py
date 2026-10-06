"""Направление бурения вееров в назначении (нисходящие / восходящие) — от него зависит
буровая выработка, из которой бурят камеру.

Revision ID: 0003
"""
import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"


def upgrade():
    if "direction" not in {c["name"] for c in sa.inspect(op.get_bind()).get_columns("assignments")}:
        op.add_column("assignments", sa.Column("direction", sa.String(8), nullable=True))


def downgrade():
    op.drop_column("assignments", "direction")
