from pathlib import Path
import sqlite3

BASE = Path(__file__).resolve().parent
DB = BASE / "data" / "app.db"

if not DB.exists():
    raise SystemExit("Banco data/app.db não encontrado.")

conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row

def cols(table):
    return [r["name"] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]

# ============================================================
# 1. Garantir colunas necessárias na fato
# ============================================================

fato_cols = cols("fato_piloto_autonomo_prova")

colunas_fato = {
    "funcao_autonomo": "TEXT",
    "data_inicio_vinculo": "TEXT",
    "data_fim_vinculo": "TEXT",
    "status_vinculo": "TEXT",
    "foi_substituido": "TEXT",
    "id_autonomo_substituto": "INTEGER",
    "data_troca": "TEXT",
    "id_motivo_troca": "INTEGER",
    "justificativa_troca": "TEXT",
    "valor_fechado_etapa": "REAL",
    "dias_trabalhados": "INTEGER",
    "link_avaliacao_externa": "TEXT",
    "documento": "TEXT",
    "observacoes": "TEXT",
}

for coluna, tipo in colunas_fato.items():
    if coluna not in fato_cols:
        conn.execute(f"ALTER TABLE fato_piloto_autonomo_prova ADD COLUMN {coluna} {tipo}")
        print(f"OK - coluna criada na fato: {coluna}")

# ============================================================
# 2. Garantir foto_url no piloto
# ============================================================

piloto_cols = cols("dim_pilotos")

if "foto_url" not in piloto_cols:
    conn.execute("ALTER TABLE dim_pilotos ADD COLUMN foto_url TEXT")
    print("OK - coluna foto_url criada em dim_pilotos")

# ============================================================
# 3. Garantir tabela cargos e vínculo no autônomo
# ============================================================

conn.execute("""
CREATE TABLE IF NOT EXISTS dim_cargos_autonomos (
    id_cargo_autonomo INTEGER PRIMARY KEY AUTOINCREMENT,
    nome_cargo TEXT NOT NULL,
    descricao TEXT,
    status TEXT DEFAULT 'Ativo'
)
""")

aut_cols = cols("dim_autonomos")

if "id_cargo_autonomo" not in aut_cols:
    conn.execute("ALTER TABLE dim_autonomos ADD COLUMN id_cargo_autonomo INTEGER")
    print("OK - coluna id_cargo_autonomo criada em dim_autonomos")

# ============================================================
# 4. Helpers
# ============================================================

def get_or_create(table, unique_col, unique_value, payload):
    row = conn.execute(
        f"SELECT * FROM {table} WHERE LOWER({unique_col}) = LOWER(?) LIMIT 1",
        (unique_value,)
    ).fetchone()

    if row:
        return row[0]

    keys = list(payload.keys())
    sql = f"INSERT INTO {table} ({', '.join(keys)}) VALUES ({', '.join(['?'] * len(keys))})"
    cur = conn.execute(sql, [payload[k] for k in keys])
    return cur.lastrowid

def criar_autonomo(nome, cpf, cargo_id, cargo_nome, especialidade):
    row = conn.execute(
        "SELECT id_autonomo FROM dim_autonomos WHERE LOWER(nome_autonomo)=LOWER(?) LIMIT 1",
        (nome,)
    ).fetchone()

    if row:
        conn.execute("""
            UPDATE dim_autonomos
            SET id_cargo_autonomo=?,
                tipo_autonomo=?,
                especialidade=?,
                status_autonomo='Ativo'
            WHERE id_autonomo=?
        """, (cargo_id, cargo_nome, especialidade, row["id_autonomo"]))

        return row["id_autonomo"]

    cur = conn.execute("""
        INSERT INTO dim_autonomos
        (nome_autonomo, cpf, telefone, email, tipo_autonomo, id_cargo_autonomo, especialidade, data_inclusao, status_autonomo, observacoes)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        nome,
        cpf,
        "(11) 98888-0000",
        nome.lower().replace(" ", ".") + "@exemplo.com",
        cargo_nome,
        cargo_id,
        especialidade,
        "2026-01-20",
        "Ativo",
        "Autônomo de exemplo"
    ))

    return cur.lastrowid

def inserir_alocacao(id_piloto, id_autonomo, id_etapa, id_prova, cargo, valor, dias, status="Ativo", obs=""):
    existe = conn.execute("""
        SELECT id_fato
        FROM fato_piloto_autonomo_prova
        WHERE id_piloto=?
          AND id_prova=?
          AND funcao_autonomo=?
          AND status_vinculo=?
        LIMIT 1
    """, (id_piloto, id_prova, cargo, status)).fetchone()

    if existe:
        return existe["id_fato"]

    cur = conn.execute("""
        INSERT INTO fato_piloto_autonomo_prova
        (id_piloto, id_autonomo, id_etapa, id_prova, funcao_autonomo,
         data_inicio_vinculo, status_vinculo, foi_substituido,
         valor_fechado_etapa, dias_trabalhados, observacoes)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        id_piloto,
        id_autonomo,
        id_etapa,
        id_prova,
        cargo,
        "2026-03-13",
        status,
        "Não",
        valor,
        dias,
        obs,
    ))

    return cur.lastrowid

# ============================================================
# 5. Popular dados de exemplo
# ============================================================

id_mecanico = get_or_create("dim_cargos_autonomos", "nome_cargo", "Mecânico", {
    "nome_cargo": "Mecânico",
    "descricao": "Responsável pela parte mecânica",
    "status": "Ativo",
})

id_engenheiro = get_or_create("dim_cargos_autonomos", "nome_cargo", "Engenheiro", {
    "nome_cargo": "Engenheiro",
    "descricao": "Responsável por engenharia, setup e dados",
    "status": "Ativo",
})

id_preparador = get_or_create("dim_cargos_autonomos", "nome_cargo", "Preparador", {
    "nome_cargo": "Preparador",
    "descricao": "Responsável pela preparação e apoio de box",
    "status": "Ativo",
})

id_carrera = get_or_create("dim_tipos_prova", "nome_tipo_prova", "Carrera Cup", {
    "nome_tipo_prova": "Carrera Cup",
    "descricao": "Tipo de categoria Porsche Cup",
    "status_tipo_prova": "Ativo",
})

id_sprint = get_or_create("dim_tipos_prova", "nome_tipo_prova", "Sprint Challenge", {
    "nome_tipo_prova": "Sprint Challenge",
    "descricao": "Tipo de categoria Porsche Cup",
    "status_tipo_prova": "Ativo",
})

id_interlagos = get_or_create("dim_etapas", "nome_etapa", "Etapa 01 - Interlagos", {
    "temporada": "2026",
    "nome_etapa": "Etapa 01 - Interlagos",
    "local": "São Paulo/SP",
    "data_inicio": "2026-03-13",
    "data_fim": "2026-03-15",
    "status_etapa": "Confirmada",
    "observacoes": "Dados de exemplo",
})

id_velocitta = get_or_create("dim_etapas", "nome_etapa", "Etapa 02 - Velocitta", {
    "temporada": "2026",
    "nome_etapa": "Etapa 02 - Velocitta",
    "local": "Mogi Guaçu/SP",
    "data_inicio": "2026-04-17",
    "data_fim": "2026-04-19",
    "status_etapa": "Planejada",
    "observacoes": "Dados de exemplo",
})

id_cat_carrera_interlagos = get_or_create("dim_provas", "nome_prova", "Carrera Cup - Interlagos", {
    "id_etapa": id_interlagos,
    "id_tipo_prova": id_carrera,
    "nome_prova": "Carrera Cup - Interlagos",
    "data_prova": "2026-03-14",
    "status_prova": "Confirmada",
    "observacoes": "Categoria de exemplo",
})

id_cat_sprint_interlagos = get_or_create("dim_provas", "nome_prova", "Sprint Challenge - Interlagos", {
    "id_etapa": id_interlagos,
    "id_tipo_prova": id_sprint,
    "nome_prova": "Sprint Challenge - Interlagos",
    "data_prova": "2026-03-15",
    "status_prova": "Confirmada",
    "observacoes": "Categoria de exemplo",
})

id_cat_carrera_velocitta = get_or_create("dim_provas", "nome_prova", "Carrera Cup - Velocitta", {
    "id_etapa": id_velocitta,
    "id_tipo_prova": id_carrera,
    "nome_prova": "Carrera Cup - Velocitta",
    "data_prova": "2026-04-18",
    "status_prova": "Planejada",
    "observacoes": "Categoria de exemplo",
})

id_rafael = get_or_create("dim_pilotos", "nome_piloto", "Rafael Martins", {
    "nome_piloto": "Rafael Martins",
    "cpf": "111.111.111-11",
    "telefone": "(11) 99999-1001",
    "email": "rafael@exemplo.com",
    "equipe": "",
    "categoria_atual": "",
    "data_inclusao": "2026-01-10",
    "status_piloto": "Ativo",
    "observacoes": "Piloto de exemplo",
    "foto_url": "",
})

id_bruno = get_or_create("dim_pilotos", "nome_piloto", "Bruno Costa", {
    "nome_piloto": "Bruno Costa",
    "cpf": "222.222.222-22",
    "telefone": "(11) 99999-1002",
    "email": "bruno@exemplo.com",
    "equipe": "",
    "categoria_atual": "",
    "data_inclusao": "2026-01-12",
    "status_piloto": "Ativo",
    "observacoes": "Piloto de exemplo",
    "foto_url": "",
})

id_lucas = get_or_create("dim_pilotos", "nome_piloto", "Lucas Almeida", {
    "nome_piloto": "Lucas Almeida",
    "cpf": "333.333.333-33",
    "telefone": "(11) 99999-1003",
    "email": "lucas@exemplo.com",
    "equipe": "",
    "categoria_atual": "",
    "data_inclusao": "2026-01-15",
    "status_piloto": "Ativo",
    "observacoes": "Piloto de exemplo",
    "foto_url": "",
})

id_joao = criar_autonomo("João Silva", "555.555.555-55", id_mecanico, "Mecânico", "Suspensão e freios")
id_pedro = criar_autonomo("Pedro Souza", "666.666.666-66", id_mecanico, "Mecânico", "Motor e transmissão")
id_carlos = criar_autonomo("Carlos Lima", "777.777.777-77", id_engenheiro, "Engenheiro", "Dados e setup")
id_mariana = criar_autonomo("Mariana Torres", "888.888.888-88", id_engenheiro, "Engenheiro", "Estratégia e telemetria")
id_andre = criar_autonomo("André Rocha", "999.999.999-99", id_preparador, "Preparador", "Preparação geral")
id_renato = criar_autonomo("Renato Alves", "444.444.444-44", id_preparador, "Preparador", "Apoio de box")

id_solicitacao = get_or_create("dim_motivos_troca", "motivo_troca", "Solicitação do piloto", {
    "motivo_troca": "Solicitação do piloto",
    "descricao": "Troca solicitada pelo piloto",
    "status": "Ativo",
})

# Rafael - equipe completa
inserir_alocacao(id_rafael, id_joao, id_interlagos, id_cat_carrera_interlagos, "Mecânico", 3300, 3, "Ativo", "Equipe formada para Interlagos")
inserir_alocacao(id_rafael, id_carlos, id_interlagos, id_cat_carrera_interlagos, "Engenheiro", 5200, 3, "Ativo", "Engenharia de dados")
inserir_alocacao(id_rafael, id_andre, id_interlagos, id_cat_carrera_interlagos, "Preparador", 2400, 3, "Ativo", "Apoio de box")

# Bruno - com substituição
id_antigo = inserir_alocacao(id_bruno, id_pedro, id_interlagos, id_cat_sprint_interlagos, "Mecânico", 3000, 3, "Substituido", "Mecânico substituído durante a etapa")

conn.execute("""
    UPDATE fato_piloto_autonomo_prova
    SET foi_substituido='Sim',
        id_autonomo_substituto=?,
        data_troca='2026-03-14',
        data_fim_vinculo='2026-03-14',
        id_motivo_troca=?,
        justificativa_troca='Piloto solicitou alteração para ajuste de trabalho no box.'
    WHERE id_fato=?
""", (id_joao, id_solicitacao, id_antigo))

inserir_alocacao(id_bruno, id_joao, id_interlagos, id_cat_sprint_interlagos, "Mecânico", 3100, 2, "Ativo", "Entrou como substituto")
inserir_alocacao(id_bruno, id_mariana, id_interlagos, id_cat_sprint_interlagos, "Engenheiro", 5000, 3, "Ativo", "Engenharia Sprint")
inserir_alocacao(id_bruno, id_renato, id_interlagos, id_cat_sprint_interlagos, "Preparador", 2200, 3, "Ativo", "Preparador Sprint")

# Lucas - Velocitta
inserir_alocacao(id_lucas, id_pedro, id_velocitta, id_cat_carrera_velocitta, "Mecânico", 3500, 3, "Ativo", "Equipe prevista Velocitta")
inserir_alocacao(id_lucas, id_carlos, id_velocitta, id_cat_carrera_velocitta, "Engenheiro", 5400, 3, "Ativo", "Engenharia prevista")

conn.commit()
conn.close()

print("OK - Banco corrigido e dados de exemplo populados.")
print("Agora rode o patch da tela Equipes novamente ou acesse /equipes se a rota já existir.")
