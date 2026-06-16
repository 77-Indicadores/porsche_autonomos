import csv
import os
import json
import tempfile
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from fastapi import APIRouter, Depends, Form, Request
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.auth import tem_acesso_modulo, is_admin as _is_admin
from app.database import get_db
from app.integrations.google_sheets.client import GoogleSheetsPermissionError
from app.integrations.google_sheets.mapper import map_row
from app.integrations.google_sheets.sync import (
    GID_ABA_RESPOSTAS,
    SHEET_NAME,
    SPREADSHEET_ID,
    WORKSHEET_NAME,
    maintenance_tickets,
    sync_maintenance_tickets,
)
from app.template_config import templates
from app.utils import flash_from_request, redirect_with_message

router = APIRouter(tags=["facilities"])

BASE_DIR = Path(__file__).resolve().parents[2]
COMPLEMENTOS_MEMORIA = {}

DEFAULT_CREDENTIALS_DIR = os.getenv(
    "GOOGLE_SHEETS_CREDENTIALS_DIR",
    "C:/planilha_google",
)
DEFAULT_OAUTH_CLIENT_PATH = os.getenv(
    "GOOGLE_SHEETS_OAUTH_CLIENT_PATH",
    os.path.join(DEFAULT_CREDENTIALS_DIR, "oauth_client.json"),
)
DEFAULT_TOKEN_PATH = os.getenv(
    "GOOGLE_SHEETS_TOKEN_PATH",
    os.path.join(DEFAULT_CREDENTIALS_DIR, "token_google.json"),
)
DEFAULT_AUDIT_DIR = os.getenv("FACILITIES_AUDIT_DIR", DEFAULT_CREDENTIALS_DIR)
DEFAULT_CACHE_CSV_PATH = os.getenv(
    "FACILITIES_CACHE_CSV_PATH",
    os.path.join(DEFAULT_CREDENTIALS_DIR, "dados_reformas.csv"),
)
DEFAULT_COMPLEMENTOS_PATH = os.getenv(
    "FACILITIES_COMPLEMENTOS_PATH",
    os.path.join(tempfile.gettempdir(), "facilities_complementos.json"),
)
COMPLEMENTAR_XLSX_PATH = BASE_DIR.parent / "porsche_facilities" / "Porsche facilities complementar.xlsx"


def fmt_date(value):
    if not value:
        return "-"
    return value.strftime("%d/%m/%Y %H:%M")


def fmt_money(value):
    if value is None or value == "":
        return "-"
    number = Decimal(value)
    formatted = f"{number:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"R$ {formatted}"


def fmt_date_text(value):
    if not value:
        return "-"
    value = str(value)
    for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(value, fmt).strftime("%d/%m/%Y")
        except ValueError:
            pass
    return value


def parse_date_value(value):
    if not value:
        return None
    value = str(value).strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            pass
    return None


def parse_money_value(value):
    if value is None:
        return Decimal("0")
    value = str(value).replace("R$", "").strip()
    if not value:
        return Decimal("0")
    value = value.replace(".", "").replace(",", ".")
    try:
        return Decimal(value)
    except Exception:
        return Decimal("0")


def status_label(value):
    labels = {
        "completed": "Concluído",
        "closed": "Fechado",
        "open": "Aberto",
        "in_progress": "Em andamento",
        "pending": "Pendente",
    }
    return labels.get(value or "", value or "-")


def priority_label(value):
    labels = {
        "low": "Baixa",
        "medium": "Média",
        "high": "Alta",
        "urgent": "Urgente",
    }
    return labels.get(value or "", value or "-")


def status_complemento(complemento):
    if complemento.get("data_finalizacao"):
        return "Finalizado"
    if complemento.get("data_inicio"):
        return "Em andamento"
    return "Pendente"


def tempo_atendimento(complemento):
    inicio = parse_date_value(complemento.get("data_inicio"))
    fim = parse_date_value(complemento.get("data_finalizacao"))
    if not inicio or not fim:
        return "-"
    dias = (fim.date() - inicio.date()).days
    return max(dias, 0)


def ler_complementos():
    dados = dict(COMPLEMENTOS_MEMORIA)
    if os.path.exists(DEFAULT_COMPLEMENTOS_PATH):
        try:
            with open(DEFAULT_COMPLEMENTOS_PATH, "r", encoding="utf-8") as arquivo:
                dados.update(json.load(arquivo))
        except Exception:
            pass
    return dados


def salvar_complementos(dados):
    COMPLEMENTOS_MEMORIA.clear()
    COMPLEMENTOS_MEMORIA.update(dados)

    os.makedirs(os.path.dirname(DEFAULT_COMPLEMENTOS_PATH), exist_ok=True)
    with open(DEFAULT_COMPLEMENTOS_PATH, "w", encoding="utf-8") as arquivo:
        json.dump(dados, arquivo, ensure_ascii=False, indent=2)


def lista_opcoes_complementares():
    opcoes = {
        "setores": [],
        "areas": [],
        "unidades": [],
        "tipos": [],
        "prazos": ["Sim", "Não"],
        "retrabalhos": ["Sim", "Não"],
    }

    if not COMPLEMENTAR_XLSX_PATH.exists():
        return opcoes

    try:
        from openpyxl import load_workbook

        wb = load_workbook(COMPLEMENTAR_XLSX_PATH, data_only=True, read_only=True)
        ws = wb["LISTA SUSPENSA"]
        mapa = {
            "setores": 1,
            "areas": 2,
            "unidades": 3,
            "tipos": 4,
            "prazos": 5,
            "retrabalhos": 6,
        }
        for nome, coluna in mapa.items():
            valores = []
            for row in range(2, ws.max_row + 1):
                value = ws.cell(row=row, column=coluna).value
                if value is not None and str(value).strip():
                    valores.append(str(value).strip())
            if valores:
                opcoes[nome] = sorted(dict.fromkeys(valores))
    except Exception:
        pass

    return opcoes


def tentar_atualizar_espelho(db: Session):
    if not os.path.exists(DEFAULT_OAUTH_CLIENT_PATH):
        return None, f"Arquivo OAuth não encontrado: {DEFAULT_OAUTH_CLIENT_PATH}"
    if not os.path.exists(DEFAULT_TOKEN_PATH):
        return None, f"Token Google não encontrado: {DEFAULT_TOKEN_PATH}"

    try:
        result = sync_maintenance_tickets(
            db=db,
            oauth_client_path=DEFAULT_OAUTH_CLIENT_PATH,
            token_path=DEFAULT_TOKEN_PATH,
            output_dir=DEFAULT_AUDIT_DIR,
        )
        return result, ""
    except GoogleSheetsPermissionError as exc:
        return None, str(exc)
    except Exception as exc:
        message = str(exc)
        if "oauth2.googleapis.com" in message or "sheets.googleapis.com" in message:
            return None, (
                "Não consegui conectar no Google Sheets agora. "
                "O Windows/ambiente bloqueou a saída para os serviços do Google "
                "(oauth2.googleapis.com / sheets.googleapis.com)."
            )
        return None, f"Não consegui atualizar o espelho do Google Sheets agora: {exc}"


def carregar_csv_espelho():
    if not os.path.exists(DEFAULT_CACHE_CSV_PATH):
        return []

    chamados = []
    with open(DEFAULT_CACHE_CSV_PATH, "r", encoding="utf-8-sig", newline="") as arquivo:
        reader = csv.DictReader(arquivo)
        for index, row in enumerate(reader, start=2):
            item = map_row(row)
            item["id"] = index
            item["source"] = "csv_cache"
            item["source_row"] = index
            item["source_spreadsheet_id"] = SPREADSHEET_ID
            item["source_gid"] = GID_ABA_RESPOSTAS
            item["raw_payload"] = json.dumps(row, ensure_ascii=False)
            chamados.append(item)

    return chamados


def preparar_chamados(rows, complementos=None):
    complementos = complementos or {}
    chamados = []
    for row in rows:
        item = dict(row)
        chave = str(item.get("source_row") or item.get("id") or "")
        complemento = complementos.get(chave, {})
        item["created_at_fmt"] = fmt_date(item.get("created_at"))
        item["completed_at_fmt"] = fmt_date(item.get("completed_at"))
        item["amount_fmt"] = fmt_money(item.get("amount"))
        item["status_label"] = status_label(item.get("status"))
        item["priority_label"] = priority_label(item.get("priority"))
        item["complemento"] = complemento
        item["complemento_status"] = status_complemento(complemento)
        item["complemento_data_inicio_fmt"] = fmt_date_text(complemento.get("data_inicio"))
        item["complemento_data_finalizacao_fmt"] = fmt_date_text(complemento.get("data_finalizacao"))
        item["complemento_custo_fmt"] = fmt_money(parse_money_value(complemento.get("custo")))
        item["complemento_tempo"] = tempo_atendimento(complemento)
        item["tem_complemento"] = bool(complemento)
        chamados.append(item)

    return chamados


def carregar_chamados_para_tela(db: Session):
    rows = []
    source_notice = ""
    source_error = ""

    if os.path.exists(DEFAULT_CACHE_CSV_PATH):
        rows = carregar_csv_espelho()
        source_notice = f"Dados carregados do espelho local: {DEFAULT_CACHE_CSV_PATH}"
    else:
        try:
            rows = db.execute(
                select(maintenance_tickets).order_by(maintenance_tickets.c.source_row.desc())
            ).mappings().all()
        except SQLAlchemyError as exc:
            source_error = f"Não consegui ler o espelho local: {exc}"

    return preparar_chamados(rows, ler_complementos()), source_notice, source_error


@router.get("/facilities")
def index(request: Request, db: Session = Depends(get_db)):
    if not tem_acesso_modulo(request, "facilities"):
        return RedirectResponse("/?sem_acesso=facilities", status_code=303)
    sync_result, sync_error = tentar_atualizar_espelho(db)
    cache_notice = ""

    try:
        rows = db.execute(
            select(maintenance_tickets).order_by(maintenance_tickets.c.source_row.desc())
        ).mappings().all()
    except SQLAlchemyError as exc:
        rows = []
        detalhe = (
            "Banco local ainda sem a tabela do espelho. "
            "O SQLite não conseguiu escrever na pasta data/app.db."
        )
        sync_error = f"{sync_error} | {detalhe}" if sync_error else detalhe

    if not rows and os.path.exists(DEFAULT_CACHE_CSV_PATH):
        rows = carregar_csv_espelho()
        cache_notice = (
            "Mostrando dados do espelho local gerado pelo script: "
            f"{DEFAULT_CACHE_CSV_PATH}"
        )
        if sync_error:
            sync_error = (
                "Modo espelho local ativo. Para leitura em tempo real direto no Google, "
                "use Atualizar espelho com a conexão Google liberada neste servidor."
            )

    complementos = ler_complementos()
    chamados = preparar_chamados(rows, complementos)

    total = len(chamados)
    total_abertos = sum(1 for item in chamados if item.get("status") in ("open", "pending", "in_progress"))
    total_concluidos = sum(1 for item in chamados if item.get("status") in ("completed", "closed"))
    valor_total = sum(Decimal(item.get("amount") or 0) for item in chamados)

    return templates.TemplateResponse(
        "facilities/index.html",
        {
            "request": request,
            "chamados": chamados,
            "cards": {
                "total": total,
                "abertos": total_abertos,
                "concluidos": total_concluidos,
                "valor_total": fmt_money(valor_total),
            },
            "config": {
                "spreadsheet_id": SPREADSHEET_ID,
                "sheet_name": SHEET_NAME,
                "worksheet_name": WORKSHEET_NAME,
                "gid": GID_ABA_RESPOSTAS,
                "oauth_client_path": DEFAULT_OAUTH_CLIENT_PATH,
                "token_path": DEFAULT_TOKEN_PATH,
                "audit_dir": DEFAULT_AUDIT_DIR,
                "has_oauth_client": os.path.exists(DEFAULT_OAUTH_CLIENT_PATH),
                "has_token": os.path.exists(DEFAULT_TOKEN_PATH),
                "cache_csv_path": DEFAULT_CACHE_CSV_PATH,
                "has_cache_csv": os.path.exists(DEFAULT_CACHE_CSV_PATH),
                "complementos_path": DEFAULT_COMPLEMENTOS_PATH,
            },
            "opcoes": lista_opcoes_complementares(),
            "sync_result": sync_result,
            "sync_error": sync_error,
            "cache_notice": cache_notice,
            "is_admin": _is_admin(request),
            **flash_from_request(request),
        },
    )


@router.post("/facilities/complementar")
def salvar_complemento(
    source_row: str = Form(...),
    area_servico: str = Form(""),
    unidade_local: str = Form(""),
    tipo_atendimento: str = Form(""),
    data_inicio: str = Form(""),
    data_finalizacao: str = Form(""),
    dentro_prazo: str = Form(""),
    retrabalho: str = Form(""),
    custo: str = Form(""),
    observacao: str = Form(""),
    rastreamento: str = Form(""),
):
    chave = str(source_row).strip()
    dados = ler_complementos()
    dados[chave] = {
        "area_servico": area_servico.strip(),
        "unidade_local": unidade_local.strip(),
        "tipo_atendimento": tipo_atendimento.strip(),
        "data_inicio": data_inicio.strip(),
        "data_finalizacao": data_finalizacao.strip(),
        "dentro_prazo": dentro_prazo.strip(),
        "retrabalho": retrabalho.strip(),
        "custo": custo.strip(),
        "observacao": observacao.strip(),
        "rastreamento": rastreamento.strip(),
        "atualizado_em": datetime.utcnow().isoformat(timespec="seconds"),
    }

    try:
        salvar_complementos(dados)
        return redirect_with_message("/facilities", success="Complemento salvo.")
    except Exception as exc:
        COMPLEMENTOS_MEMORIA.clear()
        COMPLEMENTOS_MEMORIA.update(dados)
        return redirect_with_message(
            "/facilities",
            error=(
                "Complemento mantido em memória nesta sessão, mas não consegui gravar "
                f"o arquivo {DEFAULT_COMPLEMENTOS_PATH}: {exc}"
            ),
        )


@router.post("/facilities/sincronizar")
def sincronizar(
    oauth_client_path: str = Form(DEFAULT_OAUTH_CLIENT_PATH),
    token_path: str = Form(DEFAULT_TOKEN_PATH),
    audit_dir: str = Form(DEFAULT_AUDIT_DIR),
    db: Session = Depends(get_db),
):
    try:
        result = sync_maintenance_tickets(
            db=db,
            oauth_client_path=oauth_client_path,
            token_path=token_path,
            output_dir=audit_dir,
        )
    except GoogleSheetsPermissionError as exc:
        return redirect_with_message("/facilities", error=str(exc))
    except FileNotFoundError as exc:
        return redirect_with_message("/facilities", error=str(exc))
    except Exception as exc:
        return redirect_with_message(
            "/facilities",
            error=f"Erro ao sincronizar Google Sheets: {exc}",
        )

    return redirect_with_message(
        "/facilities",
        success=(
            "Google Sheets sincronizado: "
            f"{result['total']} linhas, "
            f"{result['created']} criadas e "
            f"{result['updated']} atualizadas."
        ),
    )


@router.get("/facilities/diagnostico")
def diagnostico(db: Session = Depends(get_db)):
    try:
        total = db.execute(select(func.count()).select_from(maintenance_tickets)).scalar_one()
    except SQLAlchemyError:
        total = 0
    return {
        "spreadsheet_id": SPREADSHEET_ID,
        "gid": GID_ABA_RESPOSTAS,
        "worksheet_name": WORKSHEET_NAME,
        "oauth_client_path": DEFAULT_OAUTH_CLIENT_PATH,
        "token_path": DEFAULT_TOKEN_PATH,
        "audit_dir": DEFAULT_AUDIT_DIR,
        "cache_csv_path": DEFAULT_CACHE_CSV_PATH,
        "has_oauth_client": os.path.exists(DEFAULT_OAUTH_CLIENT_PATH),
        "has_token": os.path.exists(DEFAULT_TOKEN_PATH),
        "has_cache_csv": os.path.exists(DEFAULT_CACHE_CSV_PATH),
        "tickets": total,
    }
