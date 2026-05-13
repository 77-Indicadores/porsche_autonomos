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

## Login e usuarios

- Login: `http://127.0.0.1:8000/auth/login`
- Perfis: `admin` e `operador`

## Criacao de usuario via terminal

```powershell
python run.py create-user --nome "Admin" --email "admin@local" --senha "Senha123!" --perfil admin
```

## Banco com PostgreSQL

1. Copie `.env.example` para `.env` e ajuste os valores.
2. Defina `DATABASE_URL` no ambiente antes de subir a app.

## Migracoes (Alembic)

```powershell
alembic upgrade head
```

Criar nova revisao:

```powershell
alembic revision -m "descricao_da_mudanca"
```
