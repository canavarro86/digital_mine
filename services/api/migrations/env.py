"""Alembic: миграции схемы PostgreSQL. Соединение передаётся из api.bootstrap.migrate()."""
from alembic import context

from common.db import get_engine
from common.models import Base

target_metadata = Base.metadata


def run() -> None:
    conn = context.config.attributes.get("connection")
    if conn is None:
        with get_engine().connect() as c:
            context.configure(connection=c, target_metadata=target_metadata)
            with context.begin_transaction():
                context.run_migrations()
        return
    context.configure(connection=conn, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


run()
