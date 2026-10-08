"""Буква «е» с точками (U+0451) в продукте не используется: в уже сохраненных данных (люди, справочники,
журналы, JSON-поля) заменяется на «е». Затрагиваются только строки, где она есть.

Revision ID: 0004
"""
import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"

TEXT_TYPES = ("character varying", "text", "jsonb", "json")


def upgrade():
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    cols = bind.execute(sa.text(
        "SELECT table_name, column_name, data_type FROM information_schema.columns "
        "WHERE table_schema = current_schema() AND table_name <> 'alembic_version' AND data_type = ANY(:t)"),
        {"t": list(TEXT_TYPES)}).all()
    for table, col, typ in cols:
        val = f'"{col}"::text' if typ in ("jsonb", "json") else f'"{col}"'
        new = f"replace(replace({val}, chr(1105), chr(1077)), chr(1025), chr(1045))"  # е, Е с точками → е, Е
        if typ in ("jsonb", "json"):
            new = f"({new})::{typ}"
        has = f"strpos({val}, chr(1105)) > 0 OR strpos({val}, chr(1025)) > 0"
        bind.execute(sa.text(f'UPDATE "{table}" SET "{col}" = {new} WHERE {has}'))


def downgrade():
    pass
