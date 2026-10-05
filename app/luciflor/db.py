from collections.abc import Iterator

from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import settings

engine = create_engine(settings.database_url, pool_pre_ping=True, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """Create extensions and tables. Schema migrations (Alembic) can replace this later."""
    from . import models  # noqa: F401  (register models)

    with engine.begin() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS unaccent"))
    Base.metadata.create_all(engine)

    # create_all() does not alter existing tables: add the figura/parcela/loc columns to databases
    # created before they existed. The legacy "tarla" table and orders.tarla_id are left untouched.
    with engine.begin() as conn:
        conn.execute(text(
            "ALTER TABLE orders ADD COLUMN IF NOT EXISTS parcela_id INTEGER "
            "REFERENCES parcela(id) ON DELETE SET NULL"
        ))
        conn.execute(text("ALTER TABLE orders ADD COLUMN IF NOT EXISTS loc VARCHAR(20)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_orders_parcela_id ON orders (parcela_id)"))
