"""Módulo Folha de Pagamento.

Fluxo:
1. Admin faz upload de um PDF de extrato mensal (modelo Datamétodo/Domínio).
2. O parser (`app.folha_parser`) extrai empresa, competência, funcionários e
   rubricas (proventos/descontos).
3. Os dados viram banco (tabelas folha_arquivos / folha_funcionarios /
   folha_rubricas), com o PDF original guardado para permitir re-download.
4. É possível listar, ver o detalhe e excluir um arquivo (remove em cascata os
   funcionários e rubricas daquele arquivo).
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, File, Request, UploadFile
from fastapi.responses import RedirectResponse, Response
from sqlalchemy import (
    Column,
    DateTime,
    Float,
    Integer,
    LargeBinary,
    MetaData,
    String,
    Table,
    Text,
    delete,
    func,
    insert,
    select,
)
from sqlalchemy.orm import Session

from app.auth import is_admin as _is_admin
from app.database import engine, get_db
from app.folha_parser import parse_folha_pdf
from app.template_config import templates
from app.utils import redirect_with_message

router = APIRouter(tags=["folha"])

metadata_folha = MetaData()

folha_arquivos = Table(
    "folha_arquivos",
    metadata_folha,
    Column("id_arquivo", Integer, primary_key=True, autoincrement=True),
    Column("nome_arquivo", String(255), nullable=False),
    Column("empresa_codigo", String(20)),
    Column("empresa_nome", String(255)),
    Column("cnpj", String(30)),
    Column("competencia", String(60)),
    Column("tipo_calculo", String(120)),
    Column("data_emissao", String(20)),
    Column("qtd_funcionarios", Integer, default=0),
    Column("total_proventos", Float, default=0),
    Column("total_descontos", Float, default=0),
    Column("total_liquido", Float, default=0),
    Column("conteudo_pdf", LargeBinary),
    Column("enviado_por", String(160)),
    Column("criado_em", DateTime, default=datetime.utcnow),
)

folha_funcionarios = Table(
    "folha_funcionarios",
    metadata_folha,
    Column("id_funcionario", Integer, primary_key=True, autoincrement=True),
    Column("id_arquivo", Integer, nullable=False, index=True),
    Column("competencia", String(60)),
    Column("matricula", String(30)),
    Column("nome", String(200)),
    Column("cpf", String(30)),
    Column("situacao", String(80)),
    Column("data_admissao", String(20)),
    Column("vinculo", String(80)),
    Column("centro_custo", String(30)),
    Column("departamento", String(30)),
    Column("horas_mes", Float),
    Column("codigo_cargo", String(30)),
    Column("cargo", String(200)),
    Column("cbo", String(30)),
    Column("filial", String(30)),
    Column("salario", Float),
    Column("total_proventos", Float),
    Column("total_descontos", Float),
    Column("liquido", Float),
    Column("base_inss", Float),
    Column("base_fgts", Float),
    Column("valor_fgts", Float),
    Column("base_irrf", Float),
    Column("observacao", Text),
)

folha_rubricas = Table(
    "folha_rubricas",
    metadata_folha,
    Column("id_rubrica", Integer, primary_key=True, autoincrement=True),
    Column("id_funcionario", Integer, nullable=False, index=True),
    Column("id_arquivo", Integer, nullable=False, index=True),
    Column("codigo", String(20)),
    Column("descricao", String(255)),
    Column("referencia", Float),
    Column("valor", Float),
    Column("tipo", String(1)),  # P = provento, D = desconto
)

metadata_folha.create_all(engine)


def _f(valor) -> float | None:
    return float(valor) if isinstance(valor, Decimal) else valor


def _montar_pivot(rubricas):
    """Monta o pivô de eventos: colunas = eventos distintos (P antes de D),
    lookup = valores por funcionário. Reutilizado no detalhe e no consolidado."""
    colunas: dict[str, dict] = {}
    lookup: dict[int, dict[str, dict]] = {}
    for r in rubricas:
        codigo = r["codigo"] or ""
        colunas.setdefault(
            codigo,
            {"codigo": codigo, "descricao": r["descricao"] or "", "tipo": r["tipo"] or "P"},
        )
        celula = lookup.setdefault(r["id_funcionario"], {}).setdefault(
            codigo, {"hora": None, "valor": 0.0}
        )
        # Mesmo evento repetido para a pessoa (2 cálculos no mês) soma o valor.
        celula["hora"] = r["referencia"]
        celula["valor"] = (celula["valor"] or 0.0) + (r["valor"] or 0.0)

    pivot_colunas = sorted(
        colunas.values(),
        key=lambda c: (0 if c["tipo"] == "P" else 1, c["codigo"].zfill(6)),
    )
    return pivot_colunas, lookup


# ============================================================
# Listagem
# ============================================================
@router.get("/folha")
def folha_home(
    request: Request,
    empresa: str = "",
    competencia: str = "",
    db: Session = Depends(get_db),
):
    arquivos = db.execute(
        select(folha_arquivos).order_by(folha_arquivos.c.criado_em.desc())
    ).mappings().all()

    resumo = {
        "arquivos": len(arquivos),
        "funcionarios": db.execute(select(func.count()).select_from(folha_funcionarios)).scalar() or 0,
        "proventos": db.execute(select(func.coalesce(func.sum(folha_arquivos.c.total_proventos), 0))).scalar() or 0,
        "liquido": db.execute(select(func.coalesce(func.sum(folha_arquivos.c.total_liquido), 0))).scalar() or 0,
    }

    # Opções para os filtros (empresas e competências existentes).
    empresas = db.execute(
        select(folha_arquivos.c.empresa_nome)
        .where(folha_arquivos.c.empresa_nome.is_not(None))
        .distinct()
        .order_by(folha_arquivos.c.empresa_nome)
    ).scalars().all()
    competencias = db.execute(
        select(folha_funcionarios.c.competencia)
        .where(folha_funcionarios.c.competencia.is_not(None))
        .distinct()
        .order_by(folha_funcionarios.c.competencia)
    ).scalars().all()

    # ---- Dados consolidados (com filtros opcionais de empresa/competência) ----
    consulta = (
        select(folha_funcionarios, folha_arquivos.c.empresa_nome)
        .join(folha_arquivos, folha_funcionarios.c.id_arquivo == folha_arquivos.c.id_arquivo)
    )
    if empresa:
        consulta = consulta.where(folha_arquivos.c.empresa_nome == empresa)
    if competencia:
        consulta = consulta.where(folha_funcionarios.c.competencia == competencia)
    consulta = consulta.order_by(
        folha_arquivos.c.empresa_nome,
        folha_funcionarios.c.competencia,
        folha_funcionarios.c.nome,
    )
    funcionarios = db.execute(consulta).mappings().all()

    ids = [f["id_funcionario"] for f in funcionarios]
    if ids:
        rubricas = db.execute(
            select(folha_rubricas).where(folha_rubricas.c.id_funcionario.in_(ids))
        ).mappings().all()
    else:
        rubricas = []
    pivot_colunas, lookup = _montar_pivot(rubricas)

    pivot_linhas = []
    for f in funcionarios:
        celulas = lookup.get(f["id_funcionario"], {})
        pivot_linhas.append(
            {
                "leading": [f["empresa_nome"] or "-", f["competencia"] or "-", f["nome"]],
                "valores": [celulas.get(c["codigo"]) for c in pivot_colunas],
            }
        )

    return templates.TemplateResponse(
        "folha/index.html",
        {
            "request": request,
            "arquivos": arquivos,
            "resumo": resumo,
            "empresas": empresas,
            "competencias": competencias,
            "filtro_empresa": empresa,
            "filtro_competencia": competencia,
            "pivot_leading": ["Empresa", "Competência", "Funcionário"],
            "pivot_colunas": pivot_colunas,
            "pivot_linhas": pivot_linhas,
            "success": request.query_params.get("success"),
            "error": request.query_params.get("error"),
            "is_admin": _is_admin(request),
        },
    )


# ============================================================
# Upload / processamento do PDF
# ============================================================
@router.post("/folha/upload")
async def folha_upload(
    request: Request,
    arquivo: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    if not _is_admin(request):
        return RedirectResponse("/?sem_acesso=folha", status_code=303)

    nome = arquivo.filename or "folha.pdf"
    if not nome.lower().endswith(".pdf"):
        return redirect_with_message("/folha", error="Envie um arquivo PDF.")

    conteudo = await arquivo.read()
    if not conteudo:
        return redirect_with_message("/folha", error="Arquivo vazio.")

    # Evita reprocessar o mesmo arquivo (mesmo nome).
    ja_existe = db.execute(
        select(folha_arquivos.c.id_arquivo).where(folha_arquivos.c.nome_arquivo == nome)
    ).scalar()
    if ja_existe:
        return redirect_with_message(
            "/folha", error=f"Já existe um arquivo importado com o nome '{nome}'. Exclua-o antes de reenviar."
        )

    try:
        folha = parse_folha_pdf(conteudo)
    except Exception as exc:  # noqa: BLE001 - queremos mostrar o erro na tela
        return redirect_with_message("/folha", error=f"Falha ao ler o PDF: {exc}")

    if not folha.funcionarios:
        return redirect_with_message(
            "/folha",
            error="Nenhum funcionário identificado no PDF. Confirme se é um extrato mensal no modelo esperado.",
        )

    usuario = getattr(request.state, "current_user", None) or {}

    id_arquivo = db.execute(
        insert(folha_arquivos).values(
            nome_arquivo=nome,
            empresa_codigo=folha.empresa_codigo,
            empresa_nome=folha.empresa_nome,
            cnpj=folha.cnpj,
            competencia=folha.competencia_resumo,
            tipo_calculo=", ".join(folha.tipos_calculo),
            data_emissao=folha.data_emissao,
            qtd_funcionarios=len(folha.funcionarios),
            total_proventos=_f(folha.total_proventos),
            total_descontos=_f(folha.total_descontos),
            total_liquido=_f(folha.total_liquido),
            conteudo_pdf=conteudo,
            enviado_por=usuario.get("nome") or usuario.get("email") or "sistema",
        )
    ).inserted_primary_key[0]

    for fun in folha.funcionarios:
        id_funcionario = db.execute(
            insert(folha_funcionarios).values(
                id_arquivo=id_arquivo,
                competencia=fun.competencia,
                matricula=fun.matricula,
                nome=fun.nome,
                cpf=fun.cpf,
                situacao=fun.situacao,
                data_admissao=fun.data_admissao,
                vinculo=fun.vinculo,
                centro_custo=fun.centro_custo,
                departamento=fun.departamento,
                horas_mes=_f(fun.horas_mes),
                codigo_cargo=fun.codigo_cargo,
                cargo=fun.cargo,
                cbo=fun.cbo,
                filial=fun.filial,
                salario=_f(fun.salario),
                total_proventos=_f(fun.total_proventos),
                total_descontos=_f(fun.total_descontos),
                liquido=_f(fun.liquido),
                base_inss=_f(fun.base_inss),
                base_fgts=_f(fun.base_fgts),
                valor_fgts=_f(fun.valor_fgts),
                base_irrf=_f(fun.base_irrf),
                observacao=fun.observacao,
            )
        ).inserted_primary_key[0]

        if fun.rubricas:
            db.execute(
                insert(folha_rubricas),
                [
                    {
                        "id_funcionario": id_funcionario,
                        "id_arquivo": id_arquivo,
                        "codigo": r.codigo,
                        "descricao": r.descricao,
                        "referencia": _f(r.referencia),
                        "valor": _f(r.valor),
                        "tipo": r.tipo,
                    }
                    for r in fun.rubricas
                ],
            )

    db.commit()

    return redirect_with_message(
        "/folha",
        success=f"'{nome}' importado: {len(folha.funcionarios)} funcionário(s), competência {folha.competencia_resumo}.",
    )


# ============================================================
# Detalhe de um arquivo
# ============================================================
@router.get("/folha/{id_arquivo}")
def folha_detalhe(id_arquivo: int, request: Request, db: Session = Depends(get_db)):
    arquivo = db.execute(
        select(folha_arquivos).where(folha_arquivos.c.id_arquivo == id_arquivo)
    ).mappings().first()
    if not arquivo:
        return redirect_with_message("/folha", error="Arquivo não encontrado.")

    funcionarios = db.execute(
        select(folha_funcionarios)
        .where(folha_funcionarios.c.id_arquivo == id_arquivo)
        .order_by(folha_funcionarios.c.competencia, folha_funcionarios.c.nome)
    ).mappings().all()

    # ---- Pivô de eventos: funcionários nas linhas, cada rubrica em colunas ----
    rubricas = db.execute(
        select(folha_rubricas).where(folha_rubricas.c.id_arquivo == id_arquivo)
    ).mappings().all()

    pivot_colunas, lookup = _montar_pivot(rubricas)

    pivot_linhas = []
    for f in funcionarios:
        celulas = lookup.get(f["id_funcionario"], {})
        pivot_linhas.append(
            {
                "leading": [f["competencia"] or "-", f["nome"]],
                "valores": [celulas.get(c["codigo"]) for c in pivot_colunas],
            }
        )

    return templates.TemplateResponse(
        "folha/detalhe.html",
        {
            "request": request,
            "arquivo": arquivo,
            "funcionarios": funcionarios,
            "pivot_leading": ["Competência", "Funcionário"],
            "pivot_colunas": pivot_colunas,
            "pivot_linhas": pivot_linhas,
            "is_admin": _is_admin(request),
        },
    )


# ============================================================
# Rubricas de um funcionário (JSON, para expandir na tela)
# ============================================================
@router.get("/folha/funcionario/{id_funcionario}/rubricas")
def folha_rubricas_funcionario(id_funcionario: int, db: Session = Depends(get_db)):
    rubricas = db.execute(
        select(folha_rubricas)
        .where(folha_rubricas.c.id_funcionario == id_funcionario)
        .order_by(folha_rubricas.c.tipo, folha_rubricas.c.codigo)
    ).mappings().all()
    return {
        "rubricas": [
            {
                "codigo": r["codigo"],
                "descricao": r["descricao"],
                "referencia": r["referencia"],
                "valor": r["valor"],
                "tipo": r["tipo"],
            }
            for r in rubricas
        ]
    }


# ============================================================
# Download do PDF original
# ============================================================
@router.get("/folha/{id_arquivo}/pdf")
def folha_download(id_arquivo: int, db: Session = Depends(get_db)):
    arquivo = db.execute(
        select(folha_arquivos.c.nome_arquivo, folha_arquivos.c.conteudo_pdf).where(
            folha_arquivos.c.id_arquivo == id_arquivo
        )
    ).first()
    if not arquivo or not arquivo[1]:
        return redirect_with_message("/folha", error="PDF não disponível.")

    return Response(
        content=arquivo[1],
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{arquivo[0]}"'},
    )


# ============================================================
# Exclusão em cascata
# ============================================================
@router.post("/folha/{id_arquivo}/excluir")
def folha_excluir(id_arquivo: int, request: Request, db: Session = Depends(get_db)):
    if not _is_admin(request):
        return RedirectResponse("/?sem_acesso=folha", status_code=303)

    arquivo = db.execute(
        select(folha_arquivos.c.nome_arquivo).where(folha_arquivos.c.id_arquivo == id_arquivo)
    ).scalar()
    if not arquivo:
        return redirect_with_message("/folha", error="Arquivo não encontrado.")

    db.execute(delete(folha_rubricas).where(folha_rubricas.c.id_arquivo == id_arquivo))
    db.execute(delete(folha_funcionarios).where(folha_funcionarios.c.id_arquivo == id_arquivo))
    db.execute(delete(folha_arquivos).where(folha_arquivos.c.id_arquivo == id_arquivo))
    db.commit()

    return redirect_with_message("/folha", success=f"Arquivo '{arquivo}' excluído.")
