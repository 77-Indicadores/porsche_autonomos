from datetime import datetime
from pathlib import Path
import json
import re
import unicodedata

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import RedirectResponse
from openpyxl import load_workbook
from sqlalchemy import (
    Column,
    DateTime,
    Float,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    and_,
    func,
    insert,
    select,
    text,
    update,
)
from sqlalchemy.orm import Session

from app.auth import is_admin as _is_admin
from app.database import BASE_DIR, engine, get_db
from app.models import DimAutonomo, DimEtapa, DimPiloto
from app.template_config import templates
from app.utils import flash_from_request, redirect_with_message

router = APIRouter(tags=["pesquisas"])

metadata_pesquisas = MetaData()

pesquisa_uploads = Table(
    "pesquisa_uploads",
    metadata_pesquisas,
    Column("id_upload", Integer, primary_key=True, autoincrement=True),
    Column("id_etapa", Integer, nullable=False),
    Column("tipo_pesquisa", String(80), nullable=False),
    Column("arquivo_nome", String(255), nullable=False),
    Column("abas", Text),
    Column("qtd_linhas", Integer, default=0),
    Column("qtd_respostas", Integer, default=0),
    Column("status", String(40), default="Importado"),
    Column("criado_em", DateTime, default=datetime.utcnow),
)

pesquisa_respostas = Table(
    "pesquisa_respostas",
    metadata_pesquisas,
    Column("id_resposta", Integer, primary_key=True, autoincrement=True),
    Column("id_upload", Integer, nullable=False),
    Column("id_etapa", Integer, nullable=False),
    Column("tipo_pesquisa", String(80), nullable=False),
    Column("aba", String(160)),
    Column("linha_excel", Integer),
    Column("carimbo_data_hora", String(80)),
    Column("email", String(180)),
    Column("respondente_nome", String(180)),
    Column("respondente_chave", String(220)),
    Column("alvo_nome", String(180)),
    Column("alvo_chave", String(220)),
    Column("tipo_alvo", String(60)),
    Column("id_autonomo", Integer),
    Column("id_piloto", Integer),
    Column("categoria_forms", String(180)),
    Column("funcao_forms", String(180)),
    Column("lider_forms", String(180)),
    Column("periodo_forms", String(120)),
    Column("grupo_pergunta", String(120)),
    Column("pergunta_original", Text),
    Column("resposta_original", Text),
    Column("nota_num", Float),
    Column("resposta_padronizada", String(120)),
    Column("manter_trocar", String(80)),
    Column("comentario", Text),
    Column("status_mapeamento", String(40), default="Pendente"),
    Column("criado_em", DateTime, default=datetime.utcnow),
)

pesquisa_mapeamentos = Table(
    "pesquisa_mapeamentos",
    metadata_pesquisas,
    Column("id_mapeamento", Integer, primary_key=True, autoincrement=True),
    Column("tipo_alvo", String(60), nullable=False),
    Column("texto_origem", String(220), nullable=False),
    Column("texto_chave", String(220), nullable=False),
    Column("id_autonomo", Integer),
    Column("id_piloto", Integer),
    Column("criado_em", DateTime, default=datetime.utcnow),
)

metadata_pesquisas.create_all(engine)

UPLOAD_DIR = BASE_DIR / "data" / "uploads_pesquisas"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

TIPOS_PESQUISA = [
    ("feedback_autonomo", "Feedback Autônomo"),
    ("feedback_equipe_tecnica", "Feedback Equipe Técnica"),
    ("feedback_piloto", "Feedback Piloto"),
]


def normalizar(txt):
    if txt is None:
        return ""
    txt = str(txt).strip().lower()
    txt = unicodedata.normalize("NFKD", txt)
    txt = "".join(c for c in txt if not unicodedata.combining(c))
    txt = re.sub(r"[^a-z0-9]+", " ", txt)
    return re.sub(r"\s+", " ", txt).strip()


def is_empty(v):
    return v is None or str(v).strip() == ""


def to_float(v):
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().replace(",", ".")
    try:
        return float(s)
    except Exception:
        return None


def resposta_padrao(v):
    if v is None:
        return None

    s = str(v).strip()
    k = normalizar(s)

    if k in {"sim", "s"}:
        return "Sim"
    if k in {"nao", "n"}:
        return "Não"
    if "nao se aplica" in k or "n a" in k:
        return "Não se aplica"
    if "excelente" in k:
        return "Excelente"
    if "bom" == k or "boa" == k:
        return "Bom"
    if "regular" in k:
        return "Regular"
    if "ruim" in k:
        return "Ruim"
    if "manter" in k:
        return "Quero manter"
    if "trocar" in k:
        return "Quero trocar"

    return s


def manter_trocar(v):
    k = normalizar(v)
    if "manter" in k:
        return "Manter"
    if "trocar" in k:
        return "Trocar"
    if k == "sim":
        return "Manter"
    if k == "nao":
        return "Não manter"
    return None


def grupo_pergunta(coluna):
    k = normalizar(coluna)

    if "engenheiro" in k:
        return "Engenheiro"
    if "mecanico" in k:
        return "Mecânico"
    if "analise de dados" in k or "analista" in k:
        return "Análise de Dados"
    if "relacionamento com pilotos" in k:
        return "Relacionamento com Pilotos"
    if "diretor de provas" in k:
        return "Diretor de Provas"
    if "comissarios" in k or "cba" in k:
        return "Comissários"
    if "buffet" in k:
        return "Buffet"
    if "aplicativo" in k:
        return "Aplicativo"
    if "evento" in k:
        return "Evento"
    if "coment" in k or "observ" in k or "sugest" in k or "critica" in k:
        return "Comentário"

    return "Geral"


def achar_coluna(colunas, termos):
    for c in colunas:
        k = normalizar(c)
        if all(t in k for t in termos):
            return c
    return None


def detectar_contexto(tipo_pesquisa, row):
    colunas = list(row.keys())

    col_email = achar_coluna(colunas, ["endereco", "email"]) or achar_coluna(colunas, ["email"])
    col_data = achar_coluna(colunas, ["carimbo"])

    email = row.get(col_email) if col_email else None
    carimbo = row.get(col_data) if col_data else None

    respondente_nome = None
    alvo_nome = None
    tipo_alvo = None

    categoria_forms = None
    funcao_forms = None
    lider_forms = None
    periodo_forms = None

    col_categoria = achar_coluna(colunas, ["selecione", "categoria"]) or achar_coluna(colunas, ["categoria"])
    col_nome_autonomo = achar_coluna(colunas, ["nome", "autonomo"])
    col_funcao = achar_coluna(colunas, ["funcao", "autonomo"])
    col_lider = achar_coluna(colunas, ["lider"])
    col_periodo = achar_coluna(colunas, ["periodo", "trabalhou"])
    col_respondente = achar_coluna(colunas, ["seu", "nome"]) or achar_coluna(colunas, ["nome"])

    if col_categoria:
        categoria_forms = row.get(col_categoria)

    if col_funcao:
        funcao_forms = row.get(col_funcao)

    if col_lider:
        lider_forms = row.get(col_lider)

    if col_periodo:
        periodo_forms = row.get(col_periodo)

    if tipo_pesquisa == "feedback_autonomo":
        alvo_nome = row.get(col_nome_autonomo) if col_nome_autonomo else None
        respondente_nome = row.get(col_lider) if col_lider else None
        tipo_alvo = "autonomo"

    elif tipo_pesquisa == "feedback_piloto":
        respondente_nome = row.get(col_respondente) if col_respondente else None
        alvo_nome = respondente_nome
        tipo_alvo = "piloto"

    else:
        respondente_nome = row.get(col_respondente) if col_respondente else None
        alvo_nome = respondente_nome
        tipo_alvo = "piloto"

    return {
        "email": str(email).strip() if not is_empty(email) else None,
        "carimbo": str(carimbo).strip() if not is_empty(carimbo) else None,
        "respondente_nome": str(respondente_nome).strip() if not is_empty(respondente_nome) else None,
        "alvo_nome": str(alvo_nome).strip() if not is_empty(alvo_nome) else None,
        "tipo_alvo": tipo_alvo,
        "categoria_forms": str(categoria_forms).strip() if not is_empty(categoria_forms) else None,
        "funcao_forms": str(funcao_forms).strip() if not is_empty(funcao_forms) else None,
        "lider_forms": str(lider_forms).strip() if not is_empty(lider_forms) else None,
        "periodo_forms": str(periodo_forms).strip() if not is_empty(periodo_forms) else None,
    }


def colunas_metadata(colunas):
    ignorar = set()

    for termos in [
        ["carimbo"],
        ["endereco", "email"],
        ["email"],
        ["seu", "nome"],
        ["nome", "autonomo"],
        ["funcao", "autonomo"],
        ["lider"],
        ["periodo", "trabalhou"],
        ["selecione", "categoria"],
    ]:
        c = achar_coluna(colunas, termos)
        if c:
            ignorar.add(c)

    return ignorar


def aplicar_mapeamento(db: Session, tipo_alvo, texto_origem):
    chave = normalizar(texto_origem)

    if not chave:
        return None, None, "Pendente"

    m = db.execute(
        select(pesquisa_mapeamentos).where(
            and_(
                pesquisa_mapeamentos.c.tipo_alvo == tipo_alvo,
                pesquisa_mapeamentos.c.texto_chave == chave,
            )
        )
    ).mappings().first()

    if m:
        return m.get("id_autonomo"), m.get("id_piloto"), "Mapeado"

    if tipo_alvo == "autonomo":
        candidatos = db.query(DimAutonomo).all()
        for a in candidatos:
            if normalizar(a.nome_autonomo) == chave:
                return a.id_autonomo, None, "Mapeado"

    if tipo_alvo == "piloto":
        candidatos = db.query(DimPiloto).all()
        for p in candidatos:
            if normalizar(p.nome_piloto) == chave:
                return None, p.id_piloto, "Mapeado"

    return None, None, "Pendente"


def options(db: Session):
    return {
        "etapas": db.query(DimEtapa).order_by(DimEtapa.temporada.desc(), DimEtapa.data_inicio.desc()).all(),
        "autonomos": db.query(DimAutonomo).order_by(DimAutonomo.nome_autonomo).all(),
        "pilotos": db.query(DimPiloto).order_by(DimPiloto.nome_piloto).all(),
        "tipos_pesquisa": TIPOS_PESQUISA,
    }


@router.get("/pesquisas")
def pesquisas_home(request: Request, db: Session = Depends(get_db)):
    uploads = db.execute(
        select(pesquisa_uploads).order_by(pesquisa_uploads.c.id_upload.desc()).limit(50)
    ).mappings().all()

    pendencias = db.execute(
        text("""
            SELECT
                tipo_alvo,
                alvo_nome,
                alvo_chave,
                COUNT(*) AS qtd
            FROM pesquisa_respostas
            WHERE status_mapeamento = 'Pendente'
              AND alvo_chave IS NOT NULL
              AND alvo_chave <> ''
            GROUP BY tipo_alvo, alvo_nome, alvo_chave
            ORDER BY qtd DESC, alvo_nome
            LIMIT 100
        """)
    ).mappings().all()

    return templates.TemplateResponse(
        "pesquisas/index.html",
        {
            "request": request,
            "uploads": uploads,
            "pendencias": pendencias,
            **options(db),
            **flash_from_request(request),
        },
    )


@router.post("/pesquisas/upload")
async def pesquisas_upload(
    request: Request,
    id_etapa: int = Form(...),
    tipo_pesquisa: str = Form(...),
    arquivo: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    if not _is_admin(request):
        return RedirectResponse("/?sem_acesso=pesquisas", status_code=303)
    if tipo_pesquisa not in [t[0] for t in TIPOS_PESQUISA]:
        return redirect_with_message("/pesquisas", error="Tipo de pesquisa inválido.")

    if not arquivo.filename.lower().endswith(".xlsx"):
        return redirect_with_message("/pesquisas", error="Envie um arquivo .xlsx.")

    nome_seguro = re.sub(r"[^a-zA-Z0-9_.() -]+", "_", arquivo.filename)
    destino = UPLOAD_DIR / f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{nome_seguro}"

    conteudo = await arquivo.read()
    destino.write_bytes(conteudo)

    try:
        wb = load_workbook(destino, data_only=True)
    except Exception as exc:
        return redirect_with_message("/pesquisas", error=f"Não consegui abrir o Excel: {exc}")

    result = db.execute(
        insert(pesquisa_uploads).values(
            id_etapa=id_etapa,
            tipo_pesquisa=tipo_pesquisa,
            arquivo_nome=arquivo.filename,
            abas=json.dumps(wb.sheetnames, ensure_ascii=False),
            qtd_linhas=0,
            qtd_respostas=0,
            status="Processando",
            criado_em=datetime.utcnow(),
        )
    )

    id_upload = result.inserted_primary_key[0]
    total_linhas = 0
    total_respostas = 0

    for ws in wb.worksheets:
        rows = list(ws.iter_rows(values_only=True))
        if not rows:
            continue

        headers = [str(h).strip() if h is not None else "" for h in rows[0]]
        headers = [h if h else f"coluna_{i+1}" for i, h in enumerate(headers)]
        ignorar = colunas_metadata(headers)

        for idx, values in enumerate(rows[1:], start=2):
            row = {headers[i]: values[i] if i < len(values) else None for i in range(len(headers))}

            if all(is_empty(v) for v in row.values()):
                continue

            total_linhas += 1
            contexto = detectar_contexto(tipo_pesquisa, row)

            alvo_chave = normalizar(contexto["alvo_nome"])
            respondente_chave = normalizar(contexto["respondente_nome"])

            id_autonomo, id_piloto, status_mapeamento = aplicar_mapeamento(
                db,
                contexto["tipo_alvo"],
                contexto["alvo_nome"],
            )

            for col, val in row.items():
                if col in ignorar:
                    continue

                if is_empty(val):
                    continue

                nota = to_float(val)
                resposta_texto = str(val).strip()
                grupo = grupo_pergunta(col)
                mt = manter_trocar(resposta_texto)

                db.execute(
                    insert(pesquisa_respostas).values(
                        id_upload=id_upload,
                        id_etapa=id_etapa,
                        tipo_pesquisa=tipo_pesquisa,
                        aba=ws.title,
                        linha_excel=idx,
                        carimbo_data_hora=contexto["carimbo"],
                        email=contexto["email"],
                        respondente_nome=contexto["respondente_nome"],
                        respondente_chave=respondente_chave,
                        alvo_nome=contexto["alvo_nome"],
                        alvo_chave=alvo_chave,
                        tipo_alvo=contexto["tipo_alvo"],
                        id_autonomo=id_autonomo,
                        id_piloto=id_piloto,
                        categoria_forms=contexto["categoria_forms"],
                        funcao_forms=contexto["funcao_forms"],
                        lider_forms=contexto["lider_forms"],
                        periodo_forms=contexto["periodo_forms"],
                        grupo_pergunta=grupo,
                        pergunta_original=col,
                        resposta_original=resposta_texto,
                        nota_num=nota,
                        resposta_padronizada=resposta_padrao(resposta_texto),
                        manter_trocar=mt,
                        comentario=resposta_texto if grupo == "Comentário" else None,
                        status_mapeamento=status_mapeamento,
                        criado_em=datetime.utcnow(),
                    )
                )

                total_respostas += 1

    db.execute(
        update(pesquisa_uploads)
        .where(pesquisa_uploads.c.id_upload == id_upload)
        .values(
            qtd_linhas=total_linhas,
            qtd_respostas=total_respostas,
            status="Importado",
        )
    )

    db.commit()

    return redirect_with_message(
        f"/pesquisas/{id_upload}",
        success=f"Pesquisa importada com sucesso. Linhas: {total_linhas}. Respostas padronizadas: {total_respostas}.",
    )


@router.get("/pesquisas/{id_upload}")
def pesquisas_detalhe(id_upload: int, request: Request, db: Session = Depends(get_db)):
    upload = db.execute(
        select(pesquisa_uploads).where(pesquisa_uploads.c.id_upload == id_upload)
    ).mappings().first()

    if not upload:
        return redirect_with_message("/pesquisas", error="Upload não encontrado.")

    resumo = db.execute(
        text("""
            SELECT
                grupo_pergunta,
                COUNT(*) AS qtd,
                AVG(nota_num) AS media_nota
            FROM pesquisa_respostas
            WHERE id_upload = :id_upload
            GROUP BY grupo_pergunta
            ORDER BY qtd DESC
        """),
        {"id_upload": id_upload},
    ).mappings().all()

    respostas = db.execute(
        text("""
            SELECT *
            FROM pesquisa_respostas
            WHERE id_upload = :id_upload
            ORDER BY status_mapeamento DESC, alvo_nome, linha_excel, id_resposta
            LIMIT 500
        """),
        {"id_upload": id_upload},
    ).mappings().all()

    pendencias = db.execute(
        text("""
            SELECT
                tipo_alvo,
                alvo_nome,
                alvo_chave,
                COUNT(*) AS qtd
            FROM pesquisa_respostas
            WHERE id_upload = :id_upload
              AND status_mapeamento = 'Pendente'
              AND alvo_chave IS NOT NULL
              AND alvo_chave <> ''
            GROUP BY tipo_alvo, alvo_nome, alvo_chave
            ORDER BY qtd DESC, alvo_nome
        """),
        {"id_upload": id_upload},
    ).mappings().all()

    return templates.TemplateResponse(
        "pesquisas/detalhe.html",
        {
            "request": request,
            "upload": upload,
            "resumo": resumo,
            "respostas": respostas,
            "pendencias": pendencias,
            **options(db),
            **flash_from_request(request),
        },
    )


@router.post("/pesquisas/mapear")
def pesquisas_mapear(
    texto_origem: str = Form(...),
    tipo_alvo: str = Form(...),
    id_autonomo: str = Form(""),
    id_piloto: str = Form(""),
    redirect_to: str = Form("/pesquisas"),
    db: Session = Depends(get_db),
):
    chave = normalizar(texto_origem)

    if not chave:
        return redirect_with_message(redirect_to, error="Texto de origem inválido.")

    id_autonomo_int = int(id_autonomo) if id_autonomo else None
    id_piloto_int = int(id_piloto) if id_piloto else None

    existe = db.execute(
        select(pesquisa_mapeamentos).where(
            and_(
                pesquisa_mapeamentos.c.tipo_alvo == tipo_alvo,
                pesquisa_mapeamentos.c.texto_chave == chave,
            )
        )
    ).mappings().first()

    if existe:
        db.execute(
            update(pesquisa_mapeamentos)
            .where(pesquisa_mapeamentos.c.id_mapeamento == existe["id_mapeamento"])
            .values(id_autonomo=id_autonomo_int, id_piloto=id_piloto_int)
        )
    else:
        db.execute(
            insert(pesquisa_mapeamentos).values(
                tipo_alvo=tipo_alvo,
                texto_origem=texto_origem,
                texto_chave=chave,
                id_autonomo=id_autonomo_int,
                id_piloto=id_piloto_int,
                criado_em=datetime.utcnow(),
            )
        )

    valores_update = {
        "status_mapeamento": "Mapeado",
        "id_autonomo": id_autonomo_int,
        "id_piloto": id_piloto_int,
    }

    db.execute(
        update(pesquisa_respostas)
        .where(
            and_(
                pesquisa_respostas.c.tipo_alvo == tipo_alvo,
                pesquisa_respostas.c.alvo_chave == chave,
            )
        )
        .values(**valores_update)
    )

    db.commit()

    return redirect_with_message(redirect_to, success="Mapeamento salvo e aplicado aos registros existentes.")


@router.post("/pesquisas/{id_upload}/reprocessar-mapeamentos")
def reprocessar_mapeamentos(request: Request, id_upload: int, db: Session = Depends(get_db)):
    if not _is_admin(request):
        return RedirectResponse("/?sem_acesso=pesquisas", status_code=303)
    respostas = db.execute(
        select(pesquisa_respostas).where(pesquisa_respostas.c.id_upload == id_upload)
    ).mappings().all()

    atualizados = 0

    for r in respostas:
        id_autonomo, id_piloto, status = aplicar_mapeamento(db, r["tipo_alvo"], r["alvo_nome"])

        if status == "Mapeado":
            db.execute(
                update(pesquisa_respostas)
                .where(pesquisa_respostas.c.id_resposta == r["id_resposta"])
                .values(
                    id_autonomo=id_autonomo,
                    id_piloto=id_piloto,
                    status_mapeamento="Mapeado",
                )
            )
            atualizados += 1

    db.commit()

    return redirect_with_message(
        f"/pesquisas/{id_upload}",
        success=f"Mapeamentos reaplicados. Registros atualizados: {atualizados}.",
    )
