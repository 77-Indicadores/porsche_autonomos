from pathlib import Path
import re

BASE = Path(__file__).resolve().parent
EXCEL_PATH = BASE / "app" / "routers" / "excel.py"

if not EXCEL_PATH.exists():
    raise SystemExit("Arquivo app/routers/excel.py não encontrado.")

content = EXCEL_PATH.read_text(encoding="utf-8")

backup = EXCEL_PATH.with_suffix(".py.bak_mapping")
if not backup.exists():
    backup.write_text(content, encoding="utf-8")

new_entidades = r'''ENTIDADES = {
    "pilotos": {
        "label": "Pilotos",
        "table": "dim_pilotos",
        "unique": ["cpf"],
        "columns": [
            "nome_piloto",
            "cpf",
            "telefone",
            "email",
            "equipe",
            "categoria_atual",
            "data_inclusao",
            "data_desligamento",
            "motivo_desligamento",
            "status_piloto",
            "observacoes",
        ],
        "example": [
            "Rafael Martins",
            "111.111.111-11",
            "(11) 99999-1001",
            "rafael@email.com",
            "Equipe Alpha",
            "Carrera Cup",
            "2026-01-10",
            "",
            "",
            "Ativo",
            "Exemplo de piloto",
        ],
    },

    "autonomos": {
        "label": "Autônomos",
        "table": "dim_autonomos",
        "unique": ["cpf"],
        "columns": [
            "nome_autonomo",
            "cpf",
            "telefone",
            "email",
            "tipo_autonomo",
            "especialidade",
            "data_inclusao",
            "data_saida",
            "motivo_saida",
            "status_autonomo",
            "observacoes",
        ],
        "example": [
            "João Silva",
            "555.555.555-55",
            "(11) 98888-1001",
            "joao@email.com",
            "Mecânico",
            "Suspensão e freios",
            "2026-01-05",
            "",
            "",
            "Ativo",
            "Exemplo de autônomo",
        ],
    },

    "etapas": {
        "label": "Etapas",
        "table": "dim_etapas",
        "unique": ["temporada", "nome_etapa"],
        "columns": [
            "temporada",
            "nome_etapa",
            "local",
            "data_inicio",
            "data_fim",
            "status_etapa",
            "observacoes",
        ],
        "example": [
            "2026",
            "Etapa 01 - Interlagos",
            "São Paulo/SP",
            "2026-03-13",
            "2026-03-15",
            "Planejada",
            "Exemplo de etapa",
        ],
    },

    "tipos-prova": {
        "label": "Tipos de Prova",
        "table": "dim_tipos_prova",
        "unique": ["nome_tipo_prova"],
        "columns": [
            "nome_tipo_prova",
            "descricao",
            "status_tipo_prova",
        ],
        "example": [
            "Sprint",
            "Prova curta da etapa",
            "Ativo",
        ],
    },

    "provas": {
        "label": "Provas",
        "table": "dim_provas",
        "unique": ["id_etapa", "id_tipo_prova", "nome_prova"],
        "columns": [
            "id_etapa",
            "id_tipo_prova",
            "nome_prova",
            "data_prova",
            "status_prova",
            "observacoes",
        ],
        "example": [
            "1",
            "1",
            "Sprint - Interlagos",
            "2026-03-14",
            "Planejada",
            "Exemplo de prova",
        ],
    },

    "motivos-troca": {
        "label": "Motivos de Troca",
        "table": "dim_motivos_troca",
        "unique": ["motivo_troca"],
        "columns": [
            "motivo_troca",
            "descricao",
            "status",
        ],
        "example": [
            "Solicitação do piloto",
            "Troca solicitada pelo piloto",
            "Ativo",
        ],
    },

    "status-pagamento": {
        "label": "Status de Pagamento",
        "table": "dim_status_pagamento",
        "unique": ["status_pagamento"],
        "columns": [
            "status_pagamento",
        ],
        "example": [
            "Pendente",
        ],
    },

    "alocacoes": {
        "label": "Alocações / Fato Principal",
        "table": "fato_piloto_autonomo_prova",
        "unique": [
            "id_piloto",
            "id_autonomo",
            "id_etapa",
            "id_prova",
            "funcao_autonomo",
        ],
        "columns": [
            "id_piloto",
            "id_autonomo",
            "id_etapa",
            "id_prova",
            "funcao_autonomo",
            "data_inicio_vinculo",
            "data_fim_vinculo",
            "status_vinculo",
            "foi_substituido",
            "id_autonomo_substituto",
            "data_troca",
            "id_motivo_troca",
            "justificativa_troca",
            "nota_tecnica",
            "nota_pontualidade",
            "nota_comunicacao",
            "nota_relacionamento",
            "nota_geral",
            "comentario_avaliacao",
            "data_avaliacao",
            "valor_fechado_etapa",
            "status_pagamento",
            "data_pagamento",
            "documento",
            "observacoes",
            "usuario_responsavel",
        ],
        "example": [
            "1",
            "1",
            "1",
            "1",
            "Mecânico",
            "2026-03-10",
            "",
            "Ativo",
            "Não",
            "",
            "",
            "",
            "",
            "8",
            "9",
            "8",
            "9",
            "8.5",
            "Boa avaliação",
            "2026-03-15",
            "3300",
            "Pendente",
            "",
            "NF-001",
            "Exemplo de alocação",
            "Felipe",
        ],
    },
}'''

# Troca o bloco ENTIDADES inteiro de forma segura.
pattern = r"ENTIDADES\s*=\s*\{.*?\n\}\n\n\ndef get_conn"
replacement = new_entidades + "\n\n\ndef get_conn"

new_content, count = re.subn(pattern, replacement, content, flags=re.DOTALL)

if count == 0:
    raise SystemExit("Não consegui localizar o bloco ENTIDADES no excel.py. Nenhuma alteração feita.")

EXCEL_PATH.write_text(new_content, encoding="utf-8")

print("OK - ENTIDADES corrigido em app/routers/excel.py")
print(f"Backup: {backup}")
