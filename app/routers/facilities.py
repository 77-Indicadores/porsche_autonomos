import os
from decimal import Decimal

from fastapi import APIRouter, Depends, Form, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.integrations.google_sheets.client import GoogleSheetsPermissionError
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


@router.get("/facilities")
def index(request: Request, db: Session = Depends(get_db)):
    rows = db.execute(
        select(maintenance_tickets).order_by(maintenance_tickets.c.source_row.desc())
    ).mappings().all()

    chamados = []
    for row in rows:
        item = dict(row)
        item["created_at_fmt"] = fmt_date(item.get("created_at"))
        item["completed_at_fmt"] = fmt_date(item.get("completed_at"))
        item["amount_fmt"] = fmt_money(item.get("amount"))
        item["status_label"] = status_label(item.get("status"))
        item["priority_label"] = priority_label(item.get("priority"))
        chamados.append(item)

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
            },
            **flash_from_request(request),
        },
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
    total = db.execute(select(func.count()).select_from(maintenance_tickets)).scalar_one()
    return {
        "spreadsheet_id": SPREADSHEET_ID,
        "gid": GID_ABA_RESPOSTAS,
        "worksheet_name": WORKSHEET_NAME,
        "oauth_client_path": DEFAULT_OAUTH_CLIENT_PATH,
        "token_path": DEFAULT_TOKEN_PATH,
        "audit_dir": DEFAULT_AUDIT_DIR,
        "has_oauth_client": os.path.exists(DEFAULT_OAUTH_CLIENT_PATH),
        "has_token": os.path.exists(DEFAULT_TOKEN_PATH),
        "tickets": total,
    }
