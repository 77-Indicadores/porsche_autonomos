from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from urllib.parse import urlencode

from fastapi import Request
from fastapi.responses import RedirectResponse


def parse_date(value: str | None) -> date | None:
    if not value:
        return None
    return date.fromisoformat(value)


def parse_money(value: str | None) -> Decimal | None:
    if not value:
        return None
    normalized = value.strip().replace(".", "").replace(",", ".")
    try:
        return Decimal(normalized)
    except InvalidOperation:
        return None


def format_date(value):
    if not value:
        return "-"
    if isinstance(value, datetime):
        value = value.date()
    return value.strftime("%d/%m/%Y")


def format_money(value):
    if value is None or value == "":
        return "-"
    number = Decimal(value)
    formatted = f"{number:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"R$ {formatted}"


def format_money_input(value) -> str:
    """Formata Decimal/float para campo de input: '28000.0' → '28000,00'.
    Compatível com parse_money (vírgula como separador decimal, sem R$).
    """
    if value is None or value == "":
        return ""
    try:
        n = Decimal(str(value))
        return f"{n:.2f}".replace(".", ",")
    except (InvalidOperation, ValueError):
        return str(value)


def is_active(value):
    return value in ("1", "true", "True", "on", True)


def redirect_with_message(url: str, success: str | None = None, error: str | None = None):
    params = {}
    if success:
        params["success"] = success
    if error:
        params["error"] = error
    suffix = f"?{urlencode(params)}" if params else ""
    return RedirectResponse(f"{url}{suffix}", status_code=303)


def flash_from_request(request: Request):
    return {
        "success": request.query_params.get("success"),
        "error": request.query_params.get("error"),
    }


def active_link(request: Request, prefix: str):
    path = request.url.path
    return path == prefix or path.startswith(f"{prefix}/")

