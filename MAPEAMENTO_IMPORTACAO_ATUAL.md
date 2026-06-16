# Mapeamento atual de importações

## Pilotos
- nome_piloto
- cpf
- telefone
- email
- foto_url
- data_inclusao
- data_desligamento
- motivo_desligamento
- status_piloto
- observacoes

Removidos:
- equipe
- categoria_atual

## Cargos de Autônomos
- nome_cargo
- descricao
- status

## Autônomos
- nome_autonomo
- cpf
- telefone
- email
- id_cargo_autonomo
- tipo_autonomo
- especialidade
- data_inclusao
- data_saida
- motivo_saida
- status_autonomo
- observacoes

## Etapas
- temporada
- nome_etapa
- local
- data_inicio
- data_fim
- status_etapa
- observacoes

## Tipos de Categoria
- nome_tipo_prova
- descricao
- status_tipo_prova

## Categorias
- id_etapa
- id_tipo_prova
- nome_prova
- data_prova
- status_prova
- observacoes

## Motivos de Troca
- motivo_troca
- descricao
- status

## Alocações
- id_piloto
- id_autonomo
- id_etapa
- id_prova
- funcao_autonomo
- status_vinculo
- foi_substituido
- id_autonomo_substituto
- data_troca
- id_motivo_troca
- justificativa_troca
- valor_fechado_etapa
- dias_trabalhados
- link_avaliacao_externa
- documento
- observacoes
