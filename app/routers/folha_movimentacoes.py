"""Movimentações da folha: quem mudou de centro de custo, salário ou função.

Compara cada competência importada com a anterior em que a pessoa aparece.
Nada é cadastrado aqui — a movimentação é deduzida dos extratos já importados.
"""

from __future__ import annotations

import re
from io import BytesIO

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.database import get_db
from app.template_config import templates
from app.utils import empresa_curta

router = APIRouter(tags=["folha_movimentacoes"])

TIPOS = {
    "centro_custo": "Centro de custo",
    "cargo": "Função",
    "salario": "Salário",
}


def _ordem_competencia(competencia: str) -> tuple:
    """'03/2026' → (2026, 3). Competência é texto e não ordena sozinha."""
    partes = str(competencia or "").split("/")
    if len(partes) == 2 and partes[0].isdigit() and partes[1].isdigit():
        return (int(partes[1]), int(partes[0]))
    return (0, 0)


def _nomes_centros(db: Session) -> dict[str, str]:
    try:
        return {
            (r["codigo"] or "").strip(): r["nome"]
            for r in db.execute(text(
                "SELECT codigo, nome FROM folha_centros_custo")).mappings()
        }
    except Exception:
        return {}


def _rotulo_cc(mapa: dict[str, str], codigo) -> str:
    cod = str(codigo or "").strip()
    if not cod:
        return "—"
    nome = mapa.get(cod)
    return f"{cod} · {nome}" if nome else cod


def _movimentacoes(db: Session) -> list[dict]:
    """Toda mudança de CC, função ou salário entre competências seguidas."""
    linhas = db.execute(text("""
        SELECT a.empresa_nome AS empresa, f.competencia, f.matricula, f.nome,
               f.centro_custo, f.cargo, f.salario
        FROM folha_funcionarios f
        JOIN folha_arquivos a ON a.id_arquivo = f.id_arquivo
        WHERE COALESCE(f.matricula, '') <> ''
    """)).mappings().all()

    mapa_cc = _nomes_centros(db)

    # a chave é matrícula + empresa: a mesma matrícula pode existir nas duas
    por_pessoa: dict[tuple, list] = {}
    for r in linhas:
        chave = (str(r["matricula"]).strip(), r["empresa"])
        por_pessoa.setdefault(chave, []).append(dict(r))

    movimentos: list[dict] = []
    for (matricula, empresa), registros in por_pessoa.items():
        registros.sort(key=lambda x: _ordem_competencia(x["competencia"]))
        for anterior, atual in zip(registros, registros[1:]):
            base = {
                "matricula": matricula,
                "nome": atual["nome"],
                "empresa": empresa,
                "empresa_curta": empresa_curta(empresa),
                "competencia": atual["competencia"],
                "competencia_anterior": anterior["competencia"],
                "ordem": _ordem_competencia(atual["competencia"]),
            }

            cc_de, cc_para = (str(anterior["centro_custo"] or "").strip(),
                              str(atual["centro_custo"] or "").strip())
            if cc_de != cc_para:
                movimentos.append({**base, "tipo": "centro_custo",
                                   "de": _rotulo_cc(mapa_cc, cc_de),
                                   "para": _rotulo_cc(mapa_cc, cc_para),
                                   "variacao": None})

            cargo_de = str(anterior["cargo"] or "").strip()
            cargo_para = str(atual["cargo"] or "").strip()
            if cargo_de != cargo_para:
                movimentos.append({**base, "tipo": "cargo",
                                   "de": cargo_de or "—", "para": cargo_para or "—",
                                   "variacao": None})

            sal_de = float(anterior["salario"] or 0)
            sal_para = float(atual["salario"] or 0)
            # centavos de arredondamento não são movimentação
            if abs(sal_para - sal_de) >= 0.01:
                movimentos.append({
                    **base, "tipo": "salario",
                    "de": f"{sal_de:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."),
                    "para": f"{sal_para:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."),
                    "variacao": ((sal_para - sal_de) / sal_de * 100) if sal_de else None,
                })

    movimentos.sort(key=lambda m: (m["ordem"], m["nome"], m["tipo"]), reverse=True)
    return movimentos


def _filtrar(movimentos: list[dict], competencia: str, empresa: str,
             tipo: str, busca: str) -> list[dict]:
    resultado = movimentos
    if competencia:
        resultado = [m for m in resultado if m["competencia"] == competencia]
    if empresa:
        resultado = [m for m in resultado if m["empresa"] == empresa]
    if tipo:
        resultado = [m for m in resultado if m["tipo"] == tipo]
    if busca:
        alvo = busca.strip().lower()
        resultado = [m for m in resultado
                     if alvo in m["nome"].lower() or alvo in m["matricula"].lower()]
    return resultado


@router.get("/folha/movimentacoes")
def index(request: Request, competencia: str = "", empresa: str = "",
          tipo: str = "", q: str = "", db: Session = Depends(get_db)):
    try:
        todos = _movimentacoes(db)
    except Exception as exc:
        print(f"AVISO - não consegui apurar movimentações: {exc}")
        todos = []

    competencias = sorted({m["competencia"] for m in todos},
                          key=_ordem_competencia, reverse=True)
    empresas = sorted({m["empresa"] for m in todos})
    movimentos = _filtrar(todos, competencia, empresa, tipo, q)

    resumo = {chave: sum(1 for m in movimentos if m["tipo"] == chave) for chave in TIPOS}

    return templates.TemplateResponse("folha/movimentacoes.html", {
        "request": request,
        "movimentos": movimentos,
        "total": len(movimentos),
        "total_geral": len(todos),
        "resumo": resumo,
        "tipos": TIPOS,
        "competencias": competencias,
        "empresas": empresas,
        "competencia_sel": competencia,
        "empresa_sel": empresa,
        "tipo_sel": tipo,
        "q": q,
        "tem_filtro": bool(competencia or empresa or tipo or q),
    })


@router.get("/folha/movimentacoes/exportar")
def exportar(request: Request, competencia: str = "", empresa: str = "",
             tipo: str = "", q: str = "", db: Session = Depends(get_db)):
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    movimentos = _filtrar(_movimentacoes(db), competencia, empresa, tipo, q)

    wb = Workbook()
    ws = wb.active
    ws.title = "Movimentações"
    colunas = ["Matrícula", "Nome", "Empresa", "Competência", "Competência anterior",
               "Tipo", "De", "Para", "Variação %"]
    ws.append(colunas)
    for c in ws[1]:
        c.fill = PatternFill("solid", fgColor="D9D9D9")
        c.font = Font(bold=True)
        c.alignment = Alignment(horizontal="center")

    for m in movimentos:
        ws.append([m["matricula"], m["nome"], m["empresa_curta"], m["competencia"],
                   m["competencia_anterior"], TIPOS.get(m["tipo"], m["tipo"]),
                   m["de"], m["para"],
                   round(m["variacao"], 2) if m["variacao"] is not None else None])

    for i, titulo in enumerate(colunas, start=1):
        ws.column_dimensions[get_column_letter(i)].width = max(14, len(titulo) + 6)
    ws.freeze_panes = "A2"

    bio = BytesIO()
    wb.save(bio)
    bio.seek(0)
    sufixo = re.sub(r"[^0-9]", "", competencia) or "todas"
    return StreamingResponse(
        bio,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition":
                 f'attachment; filename="movimentacoes_folha_{sufixo}.xlsx"'},
    )
