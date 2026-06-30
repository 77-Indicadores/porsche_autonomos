from sqlalchemy import create_engine, inspect, text

from app.database import garantir_schema_usuarios


def test_garante_modulos_acesso_em_banco_antigo():
    engine = create_engine("sqlite:///:memory:", future=True)
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE usuarios (
                    id_usuario INTEGER PRIMARY KEY,
                    nome TEXT NOT NULL,
                    email TEXT NOT NULL,
                    senha_hash TEXT NOT NULL,
                    perfil TEXT NOT NULL,
                    ativo TEXT NOT NULL
                )
                """
            )
        )

    garantir_schema_usuarios(engine)
    garantir_schema_usuarios(engine)

    colunas = {coluna["name"] for coluna in inspect(engine).get_columns("usuarios")}
    assert "modulos_acesso" in colunas
