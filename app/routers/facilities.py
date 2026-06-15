import csv
import io
import json
import os
import re
from datetime import datetime
from urllib.request import urlopen

from fastapi import APIRouter, Depends, Form, Request
from sqlalchemy import (
    Column,
    DateTime,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    delete,
    insert,
    select,
    text,
    update,
)
from sqlalchemy.orm import Session

from app.database import engine, get_db
from app.template_config import templates
from app.utils import flash_from_request, redirect_with_message

router = APIRouter(tags=["facilities"])

DEFAULT_GOOGLE_SHEET_URL = os.getenv(
    "FACILITIES_GOOGLE_SHEET_URL",
    "https://docs.google.com/spreadsheets/d/1r6nqxnkIoi16XO3oEOOi9bcU5MaisoMPwnABdDvOm8U/edit?pli=1&gid=595052879#gid=595052879",
)

metadata_facilities = MetaData()

facilities_campos = Table(
    "facilities_campos",
    metadata_facilities,
    Column("id_campo", Integer, primary_key=True, autoincrement=True),
    Column("nome_campo", String(180), nullable=False),
    Column("ordem", Integer, nullable=False, default=0),
    Column("criado_em", DateTime, default=datetime.utcnow),
)

facilities_registros = Table(
    "facilities_registros",
    metadata_facilities,
    Column("id_registro", Integer, primary_key=True, autoincrement=True),
    Column("dados_json", Text, nullable=False),
    Column("criado_em", DateTime, default=datetime.utcnow),
    Column("atualizado_em", DateTime, default=datetime.utcnow),
)

metadata_facilities.create_all(engine)


def garantir_schema():
    try:
        with engine.begin() as conn:
            if conn.dialect.name == "postgresql":
                conn.execute(text("""
                    CREATE TABLE IF NOT EXISTS facilities_campos (
                        id_campo SERIAL PRIMARY KEY,
                        nome_campo VARCHAR(180) NOT NULL,
                        ordem INTEGER NOT NULL DEFAULT 0,
                        criado_em TIMESTAMP
                    )
                """))
                conn.execute(text("""
                    CREATE TABLE IF NOT EXISTS facilities_registros (
                        id_registro SERIAL PRIMARY KEY,
                        dados_json TEXT NOT NULL,
                        criado_em TIMESTAMP,
                        atualizado_em TIMESTAMP
                    )
                """))
    except Exception as exc:
        print(f"AVISO - não consegui ajustar schema facilities: {exc}")


garantir_schema()


def limpar_campo(nome):
    return str(nome or "").strip()


def normalizar_campos(campos):
    resultado = []
    vistos = {}

    for campo in campos:
        nome = limpar_campo(campo)
        if not nome:
            continue

        base = nome
        vistos[base] = vistos.get(base, 0) + 1
        if vistos[base] > 1:
            nome = f"{base} {vistos[base]}"

        resultado.append(nome)

    return resultado


def get_campos(db: Session):
    rows = db.execute(
        select(facilities_campos).order_by(facilities_campos.c.ordem, facilities_campos.c.id_campo)
    ).mappings().all()
    return [r["nome_campo"] for r in rows]


def carregar_registros(db: Session):
    rows = db.execute(
        select(facilities_registros).order_by(facilities_registros.c.id_registro.desc())
    ).mappings().all()

    registros = []
    for row in rows:
        item = dict(row)
        try:
            item["dados"] = json.loads(item.get("dados_json") or "{}")
        except Exception:
            item["dados"] = {}
        registros.append(item)

    return registros


def substituir_campos(db: Session, campos):
    db.execute(delete(facilities_campos))
    for ordem, campo in enumerate(campos):
        db.execute(
            insert(facilities_campos).values(
                nome_campo=campo,
                ordem=ordem,
                criado_em=datetime.utcnow(),
            )
        )


def ler_csv(conteudo: bytes):
    texto = None
    for encoding in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            texto = conteudo.decode(encoding)
            break
        except UnicodeDecodeError:
            continue

    if texto is None:
        texto = conteudo.decode("utf-8", errors="ignore")

    amostra = texto[:4096]
    try:
        dialect = csv.Sniffer().sniff(amostra, delimiters=",;|\t")
    except Exception:
        dialect = csv.excel

    reader = csv.DictReader(io.StringIO(texto), dialect=dialect)
    campos = normalizar_campos(reader.fieldnames or [])
    registros = []

    for row in reader:
        if not row:
            continue

        dados = {}
        tem_valor = False
        for campo in campos:
            valor = str(row.get(campo) or "").strip()
            if valor:
                tem_valor = True
            dados[campo] = valor

        if tem_valor:
            registros.append(dados)

    return campos, registros


def google_sheet_to_csv_url(sheet_url: str):
    sheet_url = str(sheet_url or "").strip()
    if not sheet_url:
        return ""

    if "docs.google.com/spreadsheets" not in sheet_url:
        return sheet_url

    sheet_id_match = re.search(r"/spreadsheets/d/([^/]+)", sheet_url)
    if not sheet_id_match:
        return sheet_url

    gid_match = re.search(r"(?:gid=|#gid=)(\d+)", sheet_url)
    gid = gid_match.group(1) if gid_match else "0"
    sheet_id = sheet_id_match.group(1)

    return f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv&gid={gid}"


@router.get("/facilities")
def index(request: Request, db: Session = Depends(get_db)):
    campos = get_campos(db)
    registros = carregar_registros(db)

    return templates.TemplateResponse(
        "facilities/index.html",
        {
            "request": request,
            "campos": campos,
            "registros": registros,
            "total_registros": len(registros),
            "google_sheet_url": DEFAULT_GOOGLE_SHEET_URL,
            **flash_from_request(request),
        },
    )


@router.post("/facilities/campos")
def salvar_campos(campos_texto: str = Form(""), db: Session = Depends(get_db)):
    campos = normalizar_campos(campos_texto.replace(";", "\n").replace(",", "\n").splitlines())

    if not campos:
        return redirect_with_message("/facilities", error="Informe pelo menos um campo.")

    substituir_campos(db, campos)
    db.commit()

    return redirect_with_message("/facilities", success="Campos do Facilities atualizados.")


@router.post("/facilities/sincronizar")
def sincronizar_google_drive(
    sheet_url: str = Form(DEFAULT_GOOGLE_SHEET_URL),
    modo: str = Form("substituir"),
    db: Session = Depends(get_db),
):
    csv_url = google_sheet_to_csv_url(sheet_url)

    if not csv_url:
        return redirect_with_message("/facilities", error="Informe a URL da planilha do Google.")

    try:
        with urlopen(csv_url, timeout=20) as response:
            conteudo = response.read()
    except Exception:
        return redirect_with_message(
            "/facilities",
            error="Não consegui conectar na planilha. Compartilhe como 'qualquer pessoa com o link pode ver' ou publique a aba para CSV.",
        )

    campos, registros = ler_csv(conteudo)

    if not campos:
        return redirect_with_message("/facilities", error="Não encontrei cabeçalho no CSV.")

    substituir_campos(db, campos)

    if modo == "substituir":
        db.execute(delete(facilities_registros))

    for dados in registros:
        db.execute(
            insert(facilities_registros).values(
                dados_json=json.dumps(dados, ensure_ascii=False),
                criado_em=datetime.utcnow(),
                atualizado_em=datetime.utcnow(),
            )
        )

    db.commit()

    return redirect_with_message(
        "/facilities",
        success=f"Google Sheets sincronizado: {len(campos)} campos e {len(registros)} registros.",
    )


@router.post("/facilities")
async def salvar_registro(
    request: Request,
    id_registro: str = Form(""),
    db: Session = Depends(get_db),
):
    campos = get_campos(db)
    if not campos:
        return redirect_with_message("/facilities", error="Cadastre ou importe os campos primeiro.")

    form = await request.form()
    dados = {}
    for campo in campos:
        dados[campo] = str(form.get(f"campo__{campo}") or "").strip()

    id_registro = str(id_registro or "").strip()

    if id_registro:
        db.execute(
            update(facilities_registros)
            .where(facilities_registros.c.id_registro == int(id_registro))
            .values(
                dados_json=json.dumps(dados, ensure_ascii=False),
                atualizado_em=datetime.utcnow(),
            )
        )
        msg = "Registro de Facilities atualizado."
    else:
        db.execute(
            insert(facilities_registros).values(
                dados_json=json.dumps(dados, ensure_ascii=False),
                criado_em=datetime.utcnow(),
                atualizado_em=datetime.utcnow(),
            )
        )
        msg = "Registro de Facilities cadastrado."

    db.commit()

    return redirect_with_message("/facilities", success=msg)


@router.post("/facilities/{id_registro}/excluir")
def excluir(id_registro: int, db: Session = Depends(get_db)):
    db.execute(delete(facilities_registros).where(facilities_registros.c.id_registro == id_registro))
    db.commit()

    return redirect_with_message("/facilities", success="Registro excluído.")
