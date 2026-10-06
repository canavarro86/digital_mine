"""Начальная схема: все таблицы модели на момент первой версии.

Revision ID: 0001
"""
from alembic import op

from common.models import Base

revision = "0001"
down_revision = None


def upgrade():
    Base.metadata.create_all(op.get_bind())


def downgrade():
    Base.metadata.drop_all(op.get_bind())
