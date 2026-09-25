from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import settings


class Base(DeclarativeBase):
    pass


engine = create_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def upgrade_user_auth_schema() -> None:
    """Additive upgrade for databases created by the earlier prototype versions."""
    inspector = inspect(engine)
    if "users" not in inspector.get_table_names():
        return
    existing = {column["name"] for column in inspector.get_columns("users")}
    statements = {
        "email": "ALTER TABLE users ADD COLUMN email VARCHAR(255)",
        "hashed_password": "ALTER TABLE users ADD COLUMN hashed_password VARCHAR(255)",
        "role": "ALTER TABLE users ADD COLUMN role VARCHAR(32) NOT NULL DEFAULT 'user'",
        "is_account": "ALTER TABLE users ADD COLUMN is_account BOOLEAN NOT NULL DEFAULT FALSE",
    }
    with engine.begin() as connection:
        for name, ddl in statements.items():
            if name not in existing:
                connection.execute(text(ddl))
        connection.execute(text("UPDATE users SET email = 'worker-' || id || '@local.invalid' WHERE email IS NULL"))
        connection.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ix_users_email ON users (email)"))


def reserve_account_ids() -> None:
    """Keep login-account IDs separate from simulator worker IDs (1–50)."""
    if engine.dialect.name == "postgresql":
        with engine.begin() as connection:
            connection.execute(text("SELECT setval(pg_get_serial_sequence('users', 'id'), GREATEST((SELECT COALESCE(MAX(id), 1) FROM users), 1000000), true)"))

