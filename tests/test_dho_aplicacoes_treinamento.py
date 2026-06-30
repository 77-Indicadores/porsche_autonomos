from sqlalchemy import Column, DateTime, Float, Integer, MetaData, String, Table, create_engine, insert, select

from app.routers.dho import _expandir_aplicacao_por_pessoa, _normalizar_aplicacoes_multiplas


def _tabela_aplicacoes(metadata):
    return Table(
        "dho_treinamento_aplicacoes",
        metadata,
        Column("id_aplicacao", Integer, primary_key=True, autoincrement=True),
        Column("id_treinamento", Integer, nullable=False),
        Column("tipo_pessoa", String(60)),
        Column("id_autonomo", Integer),
        Column("pessoa_nome", String(180)),
        Column("matricula", String(80)),
        Column("funcao", String(180)),
        Column("centro_custo", String(180)),
        Column("data_treinamento", String(20)),
        Column("carga_horaria", Float),
        Column("status", String(60)),
        Column("observacoes", String),
        Column("criado_em", DateTime),
        Column("atualizado_em", DateTime),
    )


def test_expande_um_registro_em_uma_aplicacao_por_colaborador():
    aplicacoes = _expandir_aplicacao_por_pessoa(
        {
            "pessoa_nome": "Ana Silva; Bruno Souza; Carla Lima",
            "matricula": "10; 20; 30",
            "funcao": "Analista",
            "centro_custo": "DHO",
            "status": "Realizado",
        }
    )

    assert [item["pessoa_nome"] for item in aplicacoes] == [
        "Ana Silva",
        "Bruno Souza",
        "Carla Lima",
    ]
    assert [item["matricula"] for item in aplicacoes] == ["10", "20", "30"]
    assert all(item["funcao"] == "Analista" for item in aplicacoes)


def test_normaliza_registro_antigo_e_e_idempotente():
    engine = create_engine("sqlite:///:memory:", future=True)
    metadata = MetaData()
    tabela = _tabela_aplicacoes(metadata)
    metadata.create_all(engine)

    with engine.begin() as conn:
        conn.execute(
            insert(tabela).values(
                id_treinamento=1,
                tipo_pessoa="Colaborador",
                pessoa_nome="Ana Silva; Bruno Souza",
                carga_horaria=2,
                status="Realizado",
            )
        )
        assert _normalizar_aplicacoes_multiplas(conn, tabela) == 1
        assert _normalizar_aplicacoes_multiplas(conn, tabela) == 0

        registros = conn.execute(select(tabela).order_by(tabela.c.id_aplicacao)).mappings().all()

    assert [item["pessoa_nome"] for item in registros] == ["Ana Silva", "Bruno Souza"]
    assert all(item["carga_horaria"] == 2 for item in registros)
