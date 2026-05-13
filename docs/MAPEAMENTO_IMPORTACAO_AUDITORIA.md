# Mapeamento e Auditoria de Importação

Data: **13/05/2026 12:34:13**

Banco analisado: `C:\Users\felip\OneDrive - 77 Consultoria e Indicadores\Todas\Documentos\PROJETOS\PORSHECADASTROS\porsche_autonomos\data\app.db`

## Estrutura oficial de importação

### cargos_autonomos
Tabela: `dim_cargos_autonomos`

Obrigatórios:
- `nome_cargo`

Opcionais:
- `descricao`
- `status`

### tipos_categoria
Tabela: `dim_tipos_prova`

Obrigatórios:
- `nome_tipo_prova`

Opcionais:
- `descricao`
- `status_tipo_prova`

### motivos_troca
Tabela: `dim_motivos_troca`

Obrigatórios:
- `motivo_troca`

Opcionais:
- `descricao`
- `status`

### etapas
Tabela: `dim_etapas`

Obrigatórios:
- `temporada`
- `nome_etapa`

Opcionais:
- `local`
- `data_inicio`
- `data_fim`
- `status_etapa`
- `observacoes`

### categorias
Tabela: `dim_provas`

Obrigatórios:
- `id_etapa`
- `id_tipo_prova`
- `nome_prova`

Opcionais:
- `data_prova`
- `status_prova`
- `observacoes`

### carros
Tabela: `dim_carros`

Obrigatórios:
- `numero_carro`

Opcionais:
- `modelo`
- `categoria_padrao`
- `chassi`
- `status_carro`
- `observacoes`

### pilotos
Tabela: `dim_pilotos`

Obrigatórios:
- `nome_piloto`

Opcionais:
- `cpf`
- `telefone`
- `email`
- `foto_url`
- `data_inclusao`
- `data_desligamento`
- `motivo_desligamento`
- `status_piloto`
- `observacoes`

### autonomos
Tabela: `dim_autonomos`

Obrigatórios:
- `nome_autonomo`

Opcionais:
- `cpf`
- `telefone`
- `email`
- `foto_url`
- `id_cargo_autonomo`
- `tipo_autonomo`
- `especialidade`
- `data_inclusao`
- `data_saida`
- `motivo_saida`
- `status_autonomo`
- `observacoes`

### alocacoes
Tabela: `fato_piloto_autonomo_prova`

Obrigatórios:
- `id_piloto`
- `id_autonomo`
- `id_etapa`
- `id_prova`
- `id_carro`
- `funcao_autonomo`
- `valor_fechado_etapa`
- `dias_trabalhados`

Opcionais:
- `data_inicio_vinculo`
- `data_fim_vinculo`
- `status_vinculo`
- `foi_substituido`
- `id_autonomo_substituto`
- `data_troca`
- `id_motivo_troca`
- `justificativa_troca`
- `valor_dia`
- `documento`
- `observacoes`
- `criado_em`
- `atualizado_em`

## Alertas

- **Coluna faltante** | `dim_autonomos` | id_cargo_autonomo | Ação: Adicionar coluna ou retirar do modelo de importação