from pathlib import Path
import os

from sqlalchemy import Date, create_engine, inspect, text
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy.pool import StaticPool


BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)


def load_dotenv_file():
    env_path = BASE_DIR / ".env"
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


load_dotenv_file()

DEFAULT_SQLITE_URL = f"sqlite:///{DATA_DIR / 'app.db'}"
DATABASE_URL = os.getenv("DATABASE_URL", DEFAULT_SQLITE_URL)

engine_kwargs = {"future": True}
if DATABASE_URL.startswith("sqlite"):
    engine_kwargs["connect_args"] = {"check_same_thread": False}
    if DATABASE_URL == "sqlite:///:memory:":
        engine_kwargs["poolclass"] = StaticPool

engine = create_engine(DATABASE_URL, **engine_kwargs)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def limpar_datas_vazias_sqlite():
    if not DATABASE_URL.startswith("sqlite"):
        return

    try:
        inspector = inspect(engine)
        with engine.begin() as conn:
            for table_name in inspector.get_table_names():
                for column in inspector.get_columns(table_name):
                    col_type = column.get("type")
                    is_date = isinstance(col_type, Date) or str(col_type).upper().startswith("DATE")
                    if not is_date:
                        continue

                    quoted_table = table_name.replace('"', '""')
                    quoted_column = column["name"].replace('"', '""')
                    conn.execute(
                        text(
                            f'UPDATE "{quoted_table}" '
                            f'SET "{quoted_column}" = NULL '
                            f'WHERE "{quoted_column}" = ""'
                        )
                    )
    except Exception as exc:
        print(f"AVISO - não consegui limpar datas vazias no SQLite: {exc}")

