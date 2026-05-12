# Mapeamento de Importação Excel

Gerado em: 12/05/2026 00:00:11

Banco analisado: `C:\Users\felip\Documents\Codex\2026-05-11\crie-um-sistema-web-monol-tico\porsche_autonomos\data\app.db`
Router Excel analisado: `C:\Users\felip\Documents\Codex\2026-05-11\crie-um-sistema-web-monol-tico\porsche_autonomos\app\routers\excel.py`

## 1. Resumo das Entidades de Importação

| Entidade | Tabela | Status | Colunas no Excel | Colunas importáveis no banco | Divergências |
|---|---|---:|---:|---:|---:|

## 2. Detalhamento por Entidade

## 3. Schema completo do banco

### autonomos

| Coluna | Tipo | PK | Obrigatório | Default |
|---|---|---:|---:|---|
| `id` | `INTEGER` | Sim | Sim |  |
| `nome` | `VARCHAR(140)` | Não | Sim |  |
| `cargo_id` | `INTEGER` | Não | Não |  |
| `telefone` | `VARCHAR(40)` | Não | Não |  |
| `email` | `VARCHAR(140)` | Não | Não |  |
| `documento` | `VARCHAR(60)` | Não | Não |  |
| `valor_padrao` | `NUMERIC(12, 2)` | Não | Não |  |
| `ativo` | `BOOLEAN` | Não | Sim |  |
| `data_cadastro` | `DATE` | Não | Sim |  |
| `data_saida` | `DATE` | Não | Não |  |
| `motivo_saida` | `VARCHAR(255)` | Não | Não |  |
| `observacao` | `TEXT` | Não | Não |  |
| `criado_em` | `DATETIME` | Não | Sim |  |
| `atualizado_em` | `DATETIME` | Não | Sim |  |

### cargos

| Coluna | Tipo | PK | Obrigatório | Default |
|---|---|---:|---:|---|
| `id` | `INTEGER` | Sim | Sim |  |
| `nome` | `VARCHAR(100)` | Não | Sim |  |
| `ativo` | `BOOLEAN` | Não | Sim |  |
| `criado_em` | `DATETIME` | Não | Sim |  |
| `atualizado_em` | `DATETIME` | Não | Sim |  |

### dim_autonomos

| Coluna | Tipo | PK | Obrigatório | Default |
|---|---|---:|---:|---|
| `id_autonomo` | `INTEGER` | Sim | Sim |  |
| `nome_autonomo` | `VARCHAR(140)` | Não | Sim |  |
| `cpf` | `VARCHAR(20)` | Não | Não |  |
| `telefone` | `VARCHAR(40)` | Não | Não |  |
| `email` | `VARCHAR(140)` | Não | Não |  |
| `tipo_autonomo` | `VARCHAR(40)` | Não | Sim |  |
| `especialidade` | `VARCHAR(120)` | Não | Não |  |
| `data_inclusao` | `DATE` | Não | Sim |  |
| `data_saida` | `DATE` | Não | Não |  |
| `motivo_saida` | `VARCHAR(255)` | Não | Não |  |
| `status_autonomo` | `VARCHAR(30)` | Não | Sim |  |
| `observacoes` | `TEXT` | Não | Não |  |

### dim_etapas

| Coluna | Tipo | PK | Obrigatório | Default |
|---|---|---:|---:|---|
| `id_etapa` | `INTEGER` | Sim | Sim |  |
| `temporada` | `VARCHAR(20)` | Não | Sim |  |
| `nome_etapa` | `VARCHAR(140)` | Não | Sim |  |
| `local` | `VARCHAR(120)` | Não | Não |  |
| `data_inicio` | `DATE` | Não | Não |  |
| `data_fim` | `DATE` | Não | Não |  |
| `status_etapa` | `VARCHAR(30)` | Não | Sim |  |
| `observacoes` | `TEXT` | Não | Não |  |

### dim_motivos_troca

| Coluna | Tipo | PK | Obrigatório | Default |
|---|---|---:|---:|---|
| `id_motivo_troca` | `INTEGER` | Sim | Sim |  |
| `motivo_troca` | `VARCHAR(120)` | Não | Sim |  |
| `descricao` | `TEXT` | Não | Não |  |
| `status` | `VARCHAR(30)` | Não | Sim |  |

### dim_pilotos

| Coluna | Tipo | PK | Obrigatório | Default |
|---|---|---:|---:|---|
| `id_piloto` | `INTEGER` | Sim | Sim |  |
| `nome_piloto` | `VARCHAR(140)` | Não | Sim |  |
| `cpf` | `VARCHAR(20)` | Não | Não |  |
| `telefone` | `VARCHAR(40)` | Não | Não |  |
| `email` | `VARCHAR(140)` | Não | Não |  |
| `equipe` | `VARCHAR(120)` | Não | Não |  |
| `categoria_atual` | `VARCHAR(80)` | Não | Não |  |
| `data_inclusao` | `DATE` | Não | Sim |  |
| `data_desligamento` | `DATE` | Não | Não |  |
| `motivo_desligamento` | `VARCHAR(255)` | Não | Não |  |
| `status_piloto` | `VARCHAR(30)` | Não | Sim |  |
| `observacoes` | `TEXT` | Não | Não |  |

### dim_provas

| Coluna | Tipo | PK | Obrigatório | Default |
|---|---|---:|---:|---|
| `id_prova` | `INTEGER` | Sim | Sim |  |
| `id_etapa` | `INTEGER` | Não | Sim |  |
| `id_tipo_prova` | `INTEGER` | Não | Sim |  |
| `nome_prova` | `VARCHAR(140)` | Não | Sim |  |
| `data_prova` | `DATE` | Não | Não |  |
| `status_prova` | `VARCHAR(30)` | Não | Sim |  |
| `observacoes` | `TEXT` | Não | Não |  |

### dim_status_pagamento

| Coluna | Tipo | PK | Obrigatório | Default |
|---|---|---:|---:|---|
| `id_status_pagamento` | `INTEGER` | Sim | Sim |  |
| `status_pagamento` | `VARCHAR(40)` | Não | Sim |  |

### dim_tipos_prova

| Coluna | Tipo | PK | Obrigatório | Default |
|---|---|---:|---:|---|
| `id_tipo_prova` | `INTEGER` | Sim | Sim |  |
| `nome_tipo_prova` | `VARCHAR(80)` | Não | Sim |  |
| `descricao` | `TEXT` | Não | Não |  |
| `status_tipo_prova` | `VARCHAR(30)` | Não | Sim |  |

### etapas

| Coluna | Tipo | PK | Obrigatório | Default |
|---|---|---:|---:|---|
| `id` | `INTEGER` | Sim | Sim |  |
| `nome` | `VARCHAR(120)` | Não | Sim |  |
| `local` | `VARCHAR(120)` | Não | Não |  |
| `data_inicio` | `DATE` | Não | Não |  |
| `data_fim` | `DATE` | Não | Não |  |
| `temporada` | `VARCHAR(20)` | Não | Não |  |
| `ativo` | `BOOLEAN` | Não | Sim |  |
| `criado_em` | `DATETIME` | Não | Sim |  |
| `atualizado_em` | `DATETIME` | Não | Sim |  |

### fato_piloto_autonomo_prova

| Coluna | Tipo | PK | Obrigatório | Default |
|---|---|---:|---:|---|
| `id_fato` | `INTEGER` | Sim | Sim |  |
| `id_piloto` | `INTEGER` | Não | Sim |  |
| `id_autonomo` | `INTEGER` | Não | Sim |  |
| `id_etapa` | `INTEGER` | Não | Sim |  |
| `id_prova` | `INTEGER` | Não | Sim |  |
| `funcao_autonomo` | `VARCHAR(80)` | Não | Sim |  |
| `data_inicio_vinculo` | `DATE` | Não | Sim |  |
| `data_fim_vinculo` | `DATE` | Não | Não |  |
| `status_vinculo` | `VARCHAR(30)` | Não | Sim |  |
| `foi_substituido` | `VARCHAR(3)` | Não | Sim |  |
| `id_autonomo_substituto` | `INTEGER` | Não | Não |  |
| `data_troca` | `DATE` | Não | Não |  |
| `id_motivo_troca` | `INTEGER` | Não | Não |  |
| `justificativa_troca` | `TEXT` | Não | Não |  |
| `nota_tecnica` | `NUMERIC(4, 2)` | Não | Não |  |
| `nota_pontualidade` | `NUMERIC(4, 2)` | Não | Não |  |
| `nota_comunicacao` | `NUMERIC(4, 2)` | Não | Não |  |
| `nota_relacionamento` | `NUMERIC(4, 2)` | Não | Não |  |
| `nota_geral` | `NUMERIC(4, 2)` | Não | Não |  |
| `comentario_avaliacao` | `TEXT` | Não | Não |  |
| `data_avaliacao` | `DATE` | Não | Não |  |
| `valor_fechado_etapa` | `NUMERIC(12, 2)` | Não | Não |  |
| `status_pagamento` | `VARCHAR(40)` | Não | Não |  |
| `data_pagamento` | `DATE` | Não | Não |  |
| `documento` | `VARCHAR(120)` | Não | Não |  |
| `observacoes` | `TEXT` | Não | Não |  |
| `criado_em` | `DATETIME` | Não | Sim |  |
| `atualizado_em` | `DATETIME` | Não | Sim |  |
| `usuario_responsavel` | `VARCHAR(120)` | Não | Não |  |

### movimentacoes

| Coluna | Tipo | PK | Obrigatório | Default |
|---|---|---:|---:|---|
| `id` | `INTEGER` | Sim | Sim |  |
| `data_movimentacao` | `DATE` | Não | Sim |  |
| `tipo` | `VARCHAR(30)` | Não | Sim |  |
| `etapa_id` | `INTEGER` | Não | Não |  |
| `piloto_id` | `INTEGER` | Não | Não |  |
| `autonomo_anterior_id` | `INTEGER` | Não | Não |  |
| `autonomo_novo_id` | `INTEGER` | Não | Não |  |
| `vinculo_anterior_id` | `INTEGER` | Não | Não |  |
| `vinculo_novo_id` | `INTEGER` | Não | Não |  |
| `cargo_id` | `INTEGER` | Não | Não |  |
| `motivo` | `VARCHAR(255)` | Não | Não |  |
| `observacao` | `TEXT` | Não | Não |  |
| `criado_em` | `DATETIME` | Não | Sim | CURRENT_TIMESTAMP |

### pilotos

| Coluna | Tipo | PK | Obrigatório | Default |
|---|---|---:|---:|---|
| `id` | `INTEGER` | Sim | Sim |  |
| `nome` | `VARCHAR(120)` | Não | Sim |  |
| `categoria` | `VARCHAR(80)` | Não | Não |  |
| `ativo` | `BOOLEAN` | Não | Sim |  |
| `criado_em` | `DATETIME` | Não | Sim |  |
| `atualizado_em` | `DATETIME` | Não | Sim |  |

### vinculos

| Coluna | Tipo | PK | Obrigatório | Default |
|---|---|---:|---:|---|
| `id` | `INTEGER` | Sim | Sim |  |
| `etapa_id` | `INTEGER` | Não | Sim |  |
| `piloto_id` | `INTEGER` | Não | Sim |  |
| `autonomo_id` | `INTEGER` | Não | Sim |  |
| `cargo_id` | `INTEGER` | Não | Não |  |
| `data_inicio` | `DATE` | Não | Sim |  |
| `data_fim` | `DATE` | Não | Não |  |
| `status` | `VARCHAR(20)` | Não | Sim |  |
| `valor_acordado` | `NUMERIC(12, 2)` | Não | Não |  |
| `observacao` | `TEXT` | Não | Não |  |
| `criado_em` | `DATETIME` | Não | Sim |  |
| `atualizado_em` | `DATETIME` | Não | Sim |  |
