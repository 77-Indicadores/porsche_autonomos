"""Cadastro de centros de custo da folha (empresa + código → nome do departamento)."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Form, Request
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.database import engine, get_db
from app.template_config import templates
from app.utils import redirect_with_message

router = APIRouter(tags=["folha_centros_custo"])


# ─── tabela ──────────────────────────────────────────────────────────
def _garantir_tabela():
    with engine.begin() as conn:
        if conn.dialect.name == "sqlite":
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS folha_centros_custo (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    empresa VARCHAR(160) NOT NULL,
                    codigo VARCHAR(20) NOT NULL,
                    nome VARCHAR(120) NOT NULL,
                    status VARCHAR(20) DEFAULT 'Ativo',
                    criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    atualizado_em TIMESTAMP
                )
            """))
        else:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS folha_centros_custo (
                    id SERIAL PRIMARY KEY,
                    empresa VARCHAR(160) NOT NULL,
                    codigo VARCHAR(20) NOT NULL,
                    nome VARCHAR(120) NOT NULL,
                    status VARCHAR(20) DEFAULT 'Ativo',
                    criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    atualizado_em TIMESTAMP
                )
            """))
        conn.execute(text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_folha_cc_empresa_codigo "
            "ON folha_centros_custo (empresa, codigo)"
        ))

        # Departamento no Protheus: preenchido pelo analista, fica vazio até lá
        if conn.dialect.name == "sqlite":
            existentes = [r[1] for r in conn.execute(
                text("PRAGMA table_info(folha_centros_custo)")).fetchall()]
            if "departamento_protheus" not in existentes:
                conn.execute(text("ALTER TABLE folha_centros_custo "
                                  "ADD COLUMN departamento_protheus VARCHAR(120)"))
        else:
            conn.execute(text("ALTER TABLE folha_centros_custo "
                              "ADD COLUMN IF NOT EXISTS departamento_protheus VARCHAR(120)"))


_garantir_tabela()


# Carga inicial: o de-para que já existe hoje na folha.
# Só entra se a tabela estiver vazia — nunca sobrescreve o que o usuário cadastrou.
_SEED = [
    ("DENER MOTORSPORT PRODUCOES LTDA.", "44", "PEÇAS"),
    ("DENER MOTORSPORT PRODUCOES LTDA.", "92", "ADMINISTRATIVO"),
    ("DENER MOTORSPORT PRODUCOES LTDA.", "93", "NÃO CADASTRADO BUDGET 2"),
    ("DENER MOTORSPORT PRODUCOES LTDA.", "96", "EVENTOS"),
    ("DENER MOTORSPORT PRODUCOES LTDA.", "97", "MARKETING"),
    ("DENER MOTORSPORT PRODUCOES LTDA.", "110", "PLANEJAMENTO E RELACIONAMENTO"),
    ("DENER MOTORSPORT PRODUCOES LTDA.", "111", "RECURSOS HUMANOS"),
    ("DENER MOTORSPORT PRODUCOES LTDA.", "112", "FINANCEIRO"),
    ("DENER MOTORSPORT PRODUCOES LTDA.", "114", "PRESIDENCIA"),
    ("DENER MOTORSPORT PRODUCOES LTDA.", "117", "ENGENHARIA OFICINA"),
    ("DENER MOTORSPORT PRODUCOES LTDA.", "118", "ENGENHARIA QUALIDADE"),
    ("DENER MOTORSPORT PRODUCOES LTDA.", "119", "ADESIVAGEM"),
    ("DENER MOTORSPORT PRODUCOES LTDA.", "120", "MANUTENÇÃO PREDIAL"),
    ("DENER MOTORSPORT PRODUCOES LTDA.", "121", "NÃO CADASTRADO BUDGET 2"),
    ("PIRES MOTORSPORT SERVICOS MECANICOS LTDA", "4", "NÃO CADASTRADO BUDGET 2"),
    ("PIRES MOTORSPORT SERVICOS MECANICOS LTDA", "19", "NÃO CADASTRADO BUDGET 2"),
    ("PIRES MOTORSPORT SERVICOS MECANICOS LTDA", "29", "FUNILARIA"),
    ("PIRES MOTORSPORT SERVICOS MECANICOS LTDA", "32", "LOGÍSTICA"),
    ("PIRES MOTORSPORT SERVICOS MECANICOS LTDA", "34", "PEÇAS"),
    ("PIRES MOTORSPORT SERVICOS MECANICOS LTDA", "36", "ALMOXARIFADO"),
    ("PIRES MOTORSPORT SERVICOS MECANICOS LTDA", "37", "RECUPERAÇÃO E DESENVOLVIMENTO"),
    ("PIRES MOTORSPORT SERVICOS MECANICOS LTDA", "39", "POWERTRAIN"),
    ("PIRES MOTORSPORT SERVICOS MECANICOS LTDA", "40", "CLÁSSICOS"),
    ("PIRES MOTORSPORT SERVICOS MECANICOS LTDA", "42", "ALINHAMENTO"),
    ("PIRES MOTORSPORT SERVICOS MECANICOS LTDA", "43", "CATEGORIA 1 (CARRERA)"),
    ("PIRES MOTORSPORT SERVICOS MECANICOS LTDA", "44", "CATEGORIA 2 (CHALLENGE)"),
    ("PIRES MOTORSPORT SERVICOS MECANICOS LTDA", "45", "CATEGORIA 3 (TROPHY)"),
    ("PIRES MOTORSPORT SERVICOS MECANICOS LTDA", "46", "DIRETORIA DE OPERAÇÕES"),
    ("PIRES MOTORSPORT SERVICOS MECANICOS LTDA", "47", "PNEUS/RODAS"),
    ("PIRES MOTORSPORT SERVICOS MECANICOS LTDA", "48", "RECURSOS HUMANOS"),
    ("PIRES MOTORSPORT SERVICOS MECANICOS LTDA", "50", "ADESIVAGEM"),
    ("PIRES MOTORSPORT SERVICOS MECANICOS LTDA", "51", "ENGENHARIA OFICINA"),
    ("PIRES MOTORSPORT SERVICOS MECANICOS LTDA", "52", "ENGENHARIA QUALIDADE"),
    ("GT3 CUP EVENTOS ESPORTIVOS LTDA.", "32", "GT3 CUP EVENTOS ESPORTIVOS LTDA."),
]


def _carga_inicial():
    try:
        with engine.begin() as conn:
            total = conn.execute(text("SELECT COUNT(*) FROM folha_centros_custo")).scalar() or 0
            if total:
                return
            for empresa, codigo, nome in _SEED:
                conn.execute(text(
                    "INSERT INTO folha_centros_custo (empresa, codigo, nome, status) "
                    "VALUES (:e, :c, :n, 'Ativo')"
                ), {"e": empresa, "c": codigo, "n": nome})
            print(f"Centros de custo: carga inicial com {len(_SEED)} registros.")
    except Exception as exc:
        print(f"AVISO - carga inicial de centros de custo: {exc}")


_carga_inicial()


# ─── consulta usada pelos indicadores ────────────────────────────────
def mapa_centros_custo(db: Session) -> dict[tuple[str, str], str]:
    """(EMPRESA, CÓDIGO) → nome do centro de custo, só os ativos."""
    try:
        rows = db.execute(text(
            "SELECT empresa, codigo, nome FROM folha_centros_custo "
            "WHERE COALESCE(status, 'Ativo') = 'Ativo'"
        )).mappings().all()
        return {
            ((r["empresa"] or "").strip().upper(), (r["codigo"] or "").strip()): r["nome"]
            for r in rows
        }
    except Exception as exc:
        print(f"AVISO - mapa de centros de custo: {exc}")
        return {}


def nome_centro_custo(mapa: dict, empresa: str, codigo: str) -> str:
    """Nome do centro de custo; se não estiver cadastrado, devolve o próprio código."""
    cod = (codigo or "").strip()
    if not cod:
        return "Não informado"
    nome = mapa.get(((empresa or "").strip().upper(), cod))
    if nome:
        return nome
    # mesmo código em outra empresa serve de fallback antes de mostrar o número cru
    for (_emp, _cod), _nome in mapa.items():
        if _cod == cod:
            return _nome
    return f"CC {cod}"


# ─── tela ────────────────────────────────────────────────────────────
@router.get("/folha/centros-custo")
def index(request: Request, db: Session = Depends(get_db)):
    rows = db.execute(text("""
        SELECT id, empresa, codigo, nome, departamento_protheus, status
        FROM folha_centros_custo
        ORDER BY empresa, CAST(codigo AS INTEGER)
    """)).mappings().all()
    # sugere no campo o que já foi digitado, para o analista não reescrever
    protheus_existentes = sorted({
        (r["departamento_protheus"] or "").strip()
        for r in rows if (r["departamento_protheus"] or "").strip()
    })
    sem_protheus = sum(1 for r in rows if not (r["departamento_protheus"] or "").strip())

    empresas = sorted({r["empresa"] for r in rows if r["empresa"]})
    # empresas que aparecem na folha mas ainda não têm centro de custo cadastrado
    try:
        da_folha = [r[0] for r in db.execute(text(
            "SELECT DISTINCT empresa_nome FROM budget_resultado "
            "WHERE COALESCE(empresa_nome, '') <> ''"
        )).fetchall()]
    except Exception:
        da_folha = []
    empresas = sorted(set(empresas) | set(da_folha))

    return templates.TemplateResponse("folha/centros_custo.html", {
        "request": request,
        "rows": rows,
        "empresas": empresas,
        "protheus_existentes": protheus_existentes,
        "sem_protheus": sem_protheus,
        "success": request.query_params.get("success"),
        "error": request.query_params.get("error"),
    })


@router.post("/folha/centros-custo")
def salvar(
    id: str = Form(""),
    empresa: str = Form(...),
    codigo: str = Form(...),
    nome: str = Form(...),
    departamento_protheus: str = Form(""),
    status: str = Form("Ativo"),
    db: Session = Depends(get_db),
):
    empresa = empresa.strip()
    codigo = codigo.strip()
    nome = nome.strip()

    if not empresa or not codigo or not nome:
        return redirect_with_message("/folha/centros-custo",
                                     error="Empresa, código e nome são obrigatórios.")

    dados = {"e": empresa, "c": codigo, "n": nome, "s": status,
             "dp": departamento_protheus.strip() or None,
             "ts": datetime.utcnow()}
    id = (id or "").strip()

    # o par empresa + código é único
    dup = db.execute(text(
        "SELECT id FROM folha_centros_custo WHERE empresa = :e AND codigo = :c"
    ), {"e": empresa, "c": codigo}).first()
    if dup and (not id or int(id) != dup[0]):
        return redirect_with_message(
            "/folha/centros-custo",
            error=f"O código {codigo} já está cadastrado para {empresa}.")

    if id:
        dados["id"] = int(id)
        db.execute(text("""
            UPDATE folha_centros_custo
            SET empresa = :e, codigo = :c, nome = :n, status = :s,
                departamento_protheus = :dp, atualizado_em = :ts
            WHERE id = :id
        """), dados)
        msg = "Centro de custo atualizado."
    else:
        db.execute(text("""
            INSERT INTO folha_centros_custo
                (empresa, codigo, nome, status, departamento_protheus, atualizado_em)
            VALUES (:e, :c, :n, :s, :dp, :ts)
        """), dados)
        msg = "Centro de custo cadastrado."

    db.commit()
    return redirect_with_message("/folha/centros-custo", success=msg)


@router.post("/folha/centros-custo/{id_cc}/excluir")
def excluir(id_cc: int, db: Session = Depends(get_db)):
    db.execute(text("DELETE FROM folha_centros_custo WHERE id = :id"), {"id": id_cc})
    db.commit()
    return redirect_with_message("/folha/centros-custo", success="Centro de custo excluído.")
