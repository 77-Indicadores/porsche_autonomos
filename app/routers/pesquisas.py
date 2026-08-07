from datetime import datetime
from pathlib import Path
import hashlib
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
    Column("hash_conteudo", String(40)),
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
    Column("subgrupo_pergunta", String(160)),
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


def _migrar_pesquisas():
    """Colunas novas em bancos criados antes desta versão."""
    novas = {
        "pesquisa_respostas": {"subgrupo_pergunta": "VARCHAR(160)"},
        "pesquisa_uploads": {"hash_conteudo": "VARCHAR(40)"},
    }
    with engine.connect() as conn:
        dialect = conn.dialect.name
        for tabela, cols in novas.items():
            for col, tipo in cols.items():
                try:
                    if dialect == "postgresql":
                        conn.execute(text(
                            f"ALTER TABLE {tabela} ADD COLUMN IF NOT EXISTS {col} {tipo}"))
                        conn.commit()
                    else:
                        try:
                            conn.execute(text(f"SELECT {col} FROM {tabela} LIMIT 1"))
                        except Exception:
                            conn.rollback()
                            conn.execute(text(f"ALTER TABLE {tabela} ADD COLUMN {col} {tipo}"))
                            conn.commit()
                except Exception as exc:
                    print(f"AVISO - migração {tabela}.{col}: {exc}")


_migrar_pesquisas()

UPLOAD_DIR = BASE_DIR / "data" / "uploads_pesquisas"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

TIPOS_PESQUISA = [
    ("feedback_autonomo", "Avaliação do Autônomo (líder avalia)"),
    ("satisfacao_autonomo", "Satisfação do Autônomo (autônomo responde)"),
    ("feedback_equipe_tecnica", "Feedback Equipe Técnica (ocorrências)"),
    ("feedback_piloto", "Feedback do Piloto"),
]

# Escala qualitativa → nota, para permitir média junto com as escalas numéricas
ESCALA_QUALITATIVA = {
    "excelente": 5.0,
    "otimo": 5.0,
    "muito bom": 4.5,
    "bom": 4.0,
    "boa": 4.0,
    "satisfatorio": 3.5,
    "regular": 3.0,
    "ruim": 2.0,
    "pessimo": 1.0,
    "muito ruim": 1.0,
}


def detectar_tipo(nome_arquivo: str) -> str | None:
    """Descobre o tipo de pesquisa pelo nome do arquivo."""
    k = normalizar(nome_arquivo)
    if "freelancer" in k or "equipe tecnica" in k:
        return "feedback_equipe_tecnica"
    if "satisfacao" in k and "autonomo" in k:
        return "satisfacao_autonomo"
    if "avaliacao de autonomos" in k or ("avaliacao" in k and "autonomo" in k):
        return "feedback_autonomo"
    if "pos etapa" in k or "piloto" in k:
        return "feedback_piloto"
    return None


def detectar_etapas(nome_arquivo: str, etapas: list) -> list:
    """IDs de etapa citados no nome do arquivo.

    Aceita '26ET4' e 'Etapa 4'. Um arquivo pode cobrir mais de uma etapa
    (ex.: '26ET5_ 26ET6 - Portugal').
    """
    k = normalizar(nome_arquivo)
    numeros: list[int] = []

    for m in re.finditer(r"\b\d{2}et(\d{1,2})\b", k):
        numeros.append(int(m.group(1)))
    if not numeros:
        for m in re.finditer(r"\betapa (\d{1,2})\b", k):
            numeros.append(int(m.group(1)))

    achados = []
    for num in dict.fromkeys(numeros):
        for e in etapas:
            nome = normalizar(e.nome_etapa)
            if re.search(rf"\b\d{{2}}et0*{num}\b", nome) or re.search(rf"\betapa 0*{num}\b", nome):
                if e.id_etapa not in achados:
                    achados.append(e.id_etapa)
                break
    return achados


def normalizar(txt):
    if txt is None:
        return ""
    txt = str(txt).strip().lower()
    txt = unicodedata.normalize("NFKD", txt)
    txt = "".join(c for c in txt if not unicodedata.combining(c))
    txt = re.sub(r"[^a-z0-9]+", " ", txt)
    txt = re.sub(r"\s+", " ", txt).strip()
    # "e-mail" vira "e mail" e nunca casava com o termo "email"
    return txt.replace("e mail", "email")


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
    if "excelente" in k or k == "otimo":
        return "Excelente"
    if k in {"bom", "boa"} or "muito bom" in k:
        return "Bom"
    if "regular" in k or "satisfatorio" in k:
        return "Regular"
    if "pessimo" in k or "muito ruim" in k:
        return "Péssimo"
    if "ruim" in k:
        return "Ruim"
    if "manter" in k:
        return "Quero manter"
    if "trocar" in k:
        return "Quero trocar"

    return s


def nota_da_escala(v):
    """Converte a escala qualitativa em nota, para poder tirar média."""
    k = normalizar(v)
    if not k:
        return None
    if k in ESCALA_QUALITATIVA:
        return ESCALA_QUALITATIVA[k]
    for termo, nota in ESCALA_QUALITATIVA.items():
        if termo in k:
            return nota
    return None


def _pergunta_de_permanencia(coluna) -> bool:
    """A coluna pergunta se mantém ou troca a pessoa?"""
    k = normalizar(coluna)
    if "manter" in k or "trocar" in k:
        return True
    return "deseja" in k and "proxima" in k


def manter_trocar(coluna, v):
    """Só classifica quando a pergunta é sobre permanência.

    Antes olhava só a resposta, então qualquer 'SIM' do formulário da equipe
    técnica ("respeitou os horários?") virava 'Manter'.
    """
    if not _pergunta_de_permanencia(coluna):
        return None
    k = normalizar(v)
    if "manter" in k or k == "sim":
        return "Manter"
    if "trocar" in k or k == "nao":
        return "Trocar"
    return None


def grupo_pergunta(coluna):
    k = normalizar(coluna)

    # comentários primeiro: "comentários sobre o seu engenheiro" é comentário,
    # não avaliação do engenheiro
    if "coment" in k or "observ" in k or "sugest" in k or "critica" in k or "opiniao" in k:
        return "Comentário"
    if "descreva o ocorrido" in k:
        return "Comentário"

    # avaliação de pessoas
    if "engenheiro" in k:
        return "Engenheiro"
    if "mecanico" in k:
        return "Mecânico"
    if "coach" in k:
        return "Coach"
    if "analise de dados" in k or "analista" in k:
        return "Análise de Dados"

    # satisfação do autônomo
    if "prestado pelo rh" in k or k.startswith("avalie a atuacao e o suporte prestado pelo rh"):
        return "RH"
    if "apoiadores" in k or "supervisores" in k:
        return "Supervisão"
    if "avalie a equipe" in k:
        return "Equipe"

    # ocorrências da equipe técnica
    if "tipo de ocorrencia" in k or "tipo de feedback" in k:
        return "Ocorrência"
    if "horarios" in k or "asseio" in k or "uniforme" in k or "postura" in k:
        return "Conduta"
    if "qualidade esperada" in k:
        return "Entrega"
    if "ciente da ocorrencia" in k or "reacao do autonomo" in k:
        return "Ocorrência"
    if _pergunta_de_permanencia(coluna):
        return "Permanência"

    # estrutura do evento
    if "relacionamento com pilotos" in k:
        return "Relacionamento com Pilotos"
    if "diretor de provas" in k:
        return "Diretor de Provas"
    if "comissarios" in k or "cba" in k:
        return "Comissários"
    if "buffet" in k:
        return "Buffet"
    if "alimentacao" in k:
        # refeição da equipe, não é o buffet dos pilotos
        return "Alimentação"
    if "aplicativo" in k:
        return "Aplicativo"
    if "carro" in k:
        return "Carro"
    if "evento" in k or "credenciamento" in k or "estacionamento" in k or "desmontagem" in k:
        return "Evento"

    return "Geral"


def subgrupo_pergunta(coluna):
    """Item entre colchetes do Google Forms: 'Engenheiro [Comunicação]' → 'Comunicação'."""
    m = re.search(r"\[(.+?)\]", str(coluna or ""))
    if m:
        return m.group(1).strip().rstrip(";").strip() or None
    return None


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

    if tipo_pesquisa in ("feedback_autonomo", "feedback_equipe_tecnica"):
        # o líder responde sobre um autônomo
        alvo_nome = row.get(col_nome_autonomo) if col_nome_autonomo else None
        respondente_nome = row.get(col_lider) if col_lider else None
        tipo_alvo = "autonomo"

    elif tipo_pesquisa == "satisfacao_autonomo":
        # o próprio autônomo responde sobre o evento; pode se identificar ou não
        col_identifica = (achar_coluna(colunas, ["identificar"])
                          or achar_coluna(colunas, ["nome", "completo"]))
        respondente_nome = row.get(col_identifica) if col_identifica else None
        alvo_nome = respondente_nome
        tipo_alvo = "autonomo"

    else:  # feedback_piloto
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
        # satisfação do autônomo
        ["identificar"],
        ["nome", "completo"],
        ["funcao", "desempenhou"],
        # equipe técnica
        ["etapa"],
        ["categoria"],
        ["piloto", "atendido"],
        ["data", "ocorrido"],
        ["id", "feedback"],
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

    return templates.TemplateResponse(
        "pesquisas/index.html",
        {
            "request": request,
            "uploads": uploads,
            **options(db),
            **flash_from_request(request),
        },
    )


@router.post("/pesquisas/upload")
async def pesquisas_upload(
    request: Request,
    arquivos: list[UploadFile] = File(...),
    db: Session = Depends(get_db),
):
    """Importa uma ou várias planilhas, deduzindo etapa e tipo pelo nome."""
    if not _is_admin(request):
        return RedirectResponse("/?sem_acesso=pesquisas", status_code=303)

    etapas = db.query(DimEtapa).all()
    importados, ignorados = [], []

    for arquivo in arquivos:
        if not (arquivo.filename or "").lower().endswith(".xlsx"):
            ignorados.append(f"{arquivo.filename}: não é .xlsx")
            continue

        tipo_pesquisa = detectar_tipo(arquivo.filename)
        if not tipo_pesquisa:
            ignorados.append(f"{arquivo.filename}: não reconheci o tipo pelo nome")
            continue

        ids_etapa = detectar_etapas(arquivo.filename, etapas)
        conteudo = await arquivo.read()
        msg = await _importar_planilha(db, arquivo.filename, conteudo, tipo_pesquisa,
                                       ids_etapa[0] if ids_etapa else None, etapas)
        (importados if msg[0] else ignorados).append(msg[1])

    db.commit()

    partes = []
    if importados:
        partes.append(" | ".join(importados))
    if ignorados:
        partes.append("Ignorados — " + " | ".join(ignorados))

    if importados:
        return redirect_with_message("/pesquisas", success=" || ".join(partes))
    return redirect_with_message("/pesquisas", error=" || ".join(partes) or "Nenhum arquivo importado.")


async def _importar_planilha(db, nome_arquivo, conteudo, tipo_pesquisa, id_etapa_arquivo, etapas):
    """Grava uma planilha. Devolve (ok, mensagem)."""

    # Nome curto em disco: os exports do Google Forms têm nomes longos e o
    # caminho estourava o limite de 260 caracteres do Windows, fazendo o upload
    # falhar. O nome original continua registrado em pesquisa_uploads.
    digest = hashlib.sha1(conteudo).hexdigest()

    # O mesmo arquivo costuma vir repetido em várias pastas de etapa; importar
    # de novo duplicaria todas as respostas.
    ja = db.execute(
        select(pesquisa_uploads.c.id_upload, pesquisa_uploads.c.arquivo_nome)
        .where(pesquisa_uploads.c.hash_conteudo == digest)
    ).first()
    if ja:
        return False, f"{nome_arquivo}: conteúdo idêntico ao upload #{ja[0]}, já importado"

    destino = UPLOAD_DIR / f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{digest[:8]}.xlsx"

    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    try:
        destino.write_bytes(conteudo)
    except OSError as exc:
        return False, f"{nome_arquivo}: não consegui salvar ({exc})"

    try:
        wb = load_workbook(destino, data_only=True)
    except Exception as exc:
        return False, f"{nome_arquivo}: não consegui abrir o Excel ({exc})"

    # etapa por linha (planilha da equipe técnica) tem prioridade sobre o nome
    mapa_etapas = {}
    for e in etapas:
        n = normalizar(e.nome_etapa)
        m = re.search(r"\b\d{2}et(\d{1,2})\b", n) or re.search(r"\betapa (\d{1,2})\b", n)
        if m:
            mapa_etapas[int(m.group(1))] = e.id_etapa

    def _etapa_da_linha(valor):
        m = re.search(r"(\d{1,2})", str(valor or ""))
        if m:
            return mapa_etapas.get(int(m.group(1)))
        return None

    id_etapa = id_etapa_arquivo or 0

    result = db.execute(
        insert(pesquisa_uploads).values(
            id_etapa=id_etapa,
            tipo_pesquisa=tipo_pesquisa,
            arquivo_nome=nome_arquivo,
            abas=json.dumps(wb.sheetnames, ensure_ascii=False),
            qtd_linhas=0,
            qtd_respostas=0,
            status="Processando",
            hash_conteudo=digest,
            criado_em=datetime.utcnow(),
        )
    )

    id_upload = result.inserted_primary_key[0]
    total_linhas = 0
    total_respostas = 0

    abas_vistas: set = set()

    for ws in wb.worksheets:
        rows = list(ws.iter_rows(values_only=True))
        if not rows:
            continue

        headers = [str(h).strip() if h is not None else "" for h in rows[0]]
        headers = [h if h else f"coluna_{i+1}" for i, h in enumerate(headers)]

        # O export do Forms traz abas derivadas ("Comentários") com as mesmas
        # colunas da aba principal; importar as duas duplicava toda resposta.
        assinatura = tuple(normalizar(h) for h in headers)
        if assinatura in abas_vistas:
            continue
        abas_vistas.add(assinatura)

        ignorar = colunas_metadata(headers)
        col_etapa_planilha = achar_coluna(headers, ["etapa"])

        for idx, values in enumerate(rows[1:], start=2):
            row = {headers[i]: values[i] if i < len(values) else None for i in range(len(headers))}

            if all(is_empty(v) for v in row.values()):
                continue

            total_linhas += 1
            contexto = detectar_contexto(tipo_pesquisa, row)

            id_etapa_linha = id_etapa
            if col_etapa_planilha:
                da_linha = _etapa_da_linha(row.get(col_etapa_planilha))
                if da_linha:
                    id_etapa_linha = da_linha

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

                resposta_texto = str(val).strip()
                grupo = grupo_pergunta(col)
                # nota numérica direta ou convertida da escala qualitativa
                nota = to_float(val)
                if nota is None:
                    nota = nota_da_escala(val)
                mt = manter_trocar(col, resposta_texto)

                db.execute(
                    insert(pesquisa_respostas).values(
                        id_upload=id_upload,
                        id_etapa=id_etapa_linha,
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
                        subgrupo_pergunta=subgrupo_pergunta(col),
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

    rotulo = dict(TIPOS_PESQUISA).get(tipo_pesquisa, tipo_pesquisa)
    nome_etapa = next((e.nome_etapa for e in etapas if e.id_etapa == id_etapa), None)
    onde = f" · {nome_etapa}" if nome_etapa else " · etapa pela planilha"
    return True, f"{nome_arquivo}: {rotulo}{onde} — {total_linhas} linhas, {total_respostas} respostas"


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
