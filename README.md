# Porsche Cup Autonomos

Sistema web local para cadastro, alocacao, troca, avaliacao e custo fechado de autonomos por piloto, etapa e prova.

## Rodar

```powershell
cd porsche_autonomos
python -m app.seed
python run.py
```

Abra:

```text
http://127.0.0.1:8000
```

Tambem existe o atalho:

```powershell
.\run_server.bat
```

## Fluxo principal

1. Cadastre pilotos, autonomos, etapas, tipos e provas.
2. Abra `Gestao de Alocacao`.
3. Crie uma alocacao para piloto + etapa + prova + funcao.
4. Use as acoes da tabela para substituir, avaliar, encerrar ou editar custo.
5. Consulte os relatorios filtraveis.

## Modelo

O banco usa tabelas dimensao:

- `dim_pilotos`
- `dim_autonomos`
- `dim_etapas`
- `dim_tipos_prova`
- `dim_provas`
- `dim_motivos_troca`
- `dim_status_pagamento`

E uma tabela fato principal:

- `fato_piloto_autonomo_prova`

O valor principal de custo e `valor_fechado_etapa`.
