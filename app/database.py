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


def _resolve_database_url(raw_url: str):
    """Retorna (url, kwargs) prontos para create_engine, tratando MSSQL com caracteres especiais."""
    kwargs = {"future": True}

    if raw_url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
        if raw_url == "sqlite:///:memory:":
            kwargs["poolclass"] = StaticPool
        return raw_url, kwargs

    if raw_url.startswith("mssql"):
        import urllib.parse as _up
        from sqlalchemy.engine import URL as _SA_URL
        _stripped = raw_url.replace("mssql+pymssql://", "")
        _userinfo, _hostdb = _stripped.rsplit("@", 1)
        _user, _password = _userinfo.split(":", 1)
        _host_port, _dbname = _hostdb.split("/", 1)
        _host, _port = (_host_port.split(":", 1) if ":" in _host_port else (_host_port, "1433"))
        url = _SA_URL.create(
            "mssql+pymssql",
            username=_up.unquote(_user),
            password=_up.unquote(_password),
            host=_host,
            port=int(_port),
            database=_dbname,
        )
        kwargs["pool_pre_ping"] = True
        kwargs["pool_recycle"] = 1800
        return url, kwargs

    # PostgreSQL e outros
    kwargs["pool_pre_ping"] = True
    kwargs["pool_recycle"] = 1800
    return raw_url, kwargs


_engine_url, engine_kwargs = _resolve_database_url(DATABASE_URL)
engine = create_engine(_engine_url, **engine_kwargs)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def garantir_schema_usuarios(bind=engine):
    """Adiciona campos novos de usuarios em bancos criados por versoes antigas."""
    with bind.begin() as conn:
        dialect = conn.dialect.name

        if dialect == "sqlite":
            tabelas = {
                row[0]
                for row in conn.execute(
                    text("SELECT name FROM sqlite_master WHERE type='table'")
                ).fetchall()
            }
            if "usuarios" not in tabelas:
                return

            colunas = {
                row[1]
                for row in conn.execute(text("PRAGMA table_info(usuarios)")).fetchall()
            }
            if "modulos_acesso" not in colunas:
                conn.execute(text("ALTER TABLE usuarios ADD COLUMN modulos_acesso TEXT"))

        elif dialect == "postgresql":
            conn.execute(
                text(
                    "ALTER TABLE IF EXISTS usuarios "
                    "ADD COLUMN IF NOT EXISTS modulos_acesso TEXT"
                )
            )


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

