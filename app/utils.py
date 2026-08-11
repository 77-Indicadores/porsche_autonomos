from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from urllib.parse import urlencode

from fastapi import Request
from fastapi.responses import RedirectResponse


def parse_date(value: str | None) -> date | None:
    if not value:
        return None
    return date.fromisoformat(value)


# Formatos de data que chegam pelo sistema: digitação manual, planilha
# importada (que traz datetime ou serial do Excel) e integrações.
_FORMATOS_DATA = ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d",
                  "%d.%m.%Y", "%d/%m/%y", "%m/%d/%Y")


def data_para_date(valor) -> date | None:
    """Interpreta qualquer data que o sistema receba; None quando não reconhece.

    Datas guardadas como texto chegam em formatos misturados ('09/02/2026',
    '2026-06-02 00:00:00', serial do Excel). Sem um ponto único de conversão,
    cada tela fatiava a string do seu jeito e os filtros de período saíam
    embaralhados.
    """
    if valor is None or valor == "":
        return None
    if isinstance(valor, datetime):
        return valor.date()
    if isinstance(valor, date):
        return valor

    # serial do Excel (dias desde 30/12/1899)
    if isinstance(valor, (int, float)) and not isinstance(valor, bool):
        try:
            return date(1899, 12, 30) + timedelta(days=int(valor))
        except (ValueError, OverflowError):
            return None

    texto = str(valor).strip()
    if not texto:
        return None

    # descarta a parte de hora: '2026-06-02 00:00:00' e '2026-06-02T00:00:00'
    texto = texto.replace("T", " ").split(" ")[0]

    for fmt in _FORMATOS_DATA:
        try:
            return datetime.strptime(texto, fmt).date()
        except ValueError:
            pass

    if texto.replace(".", "", 1).isdigit():
        try:
            return date(1899, 12, 30) + timedelta(days=int(float(texto)))
        except (ValueError, OverflowError):
            return None
    return None


def data_iso(valor) -> str:
    """Forma canônica de gravação: 'YYYY-MM-DD'. Devolve '' se não for data."""
    d = data_para_date(valor)
    return d.isoformat() if d else ""


def competencia_de(valor) -> str:
    """Competência 'YYYY-MM' usada nos filtros de período."""
    d = data_para_date(valor)
    return f"{d.year:04d}-{d.month:02d}" if d else ""


def parse_money(value: str | None) -> Decimal | None:
    if not value:
        return None
    normalized = value.strip().replace(".", "").replace(",", ".")
    try:
        return Decimal(normalized)
    except InvalidOperation:
        return None


def format_date(value):
    """Exibição padrão do sistema: dd/mm/aaaa, venha a data no formato que vier."""
    if not value:
        return "-"
    d = data_para_date(value)
    if d:
        return d.strftime("%d/%m/%Y")
    return value if isinstance(value, str) else str(value)


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
    if params:
        sep = "&" if "?" in url else "?"
        suffix = f"{sep}{urlencode(params)}"
    else:
        suffix = ""
    return RedirectResponse(f"{url}{suffix}", status_code=303)


def flash_from_request(request: Request):
    return {
        "success": request.query_params.get("success"),
        "error": request.query_params.get("error"),
    }


# Razão social → nome curto usado nos filtros dos indicadores.
# A folha grava o nome truncado e sem pontuação, então o match é por trecho.
_EMPRESAS_CURTAS = (
    ("DENER", "Dener"),
    ("PIRES", "Pires"),
    ("GT3", "GT3"),
)


def empresa_curta(nome) -> str:
    """Nome curto da empresa; devolve o original quando não reconhece."""
    bruto = str(nome or "").strip()
    if not bruto:
        return ""
    alvo = bruto.upper()
    for chave, curto in _EMPRESAS_CURTAS:
        if chave in alvo:
            return curto

    # Só encurta o que parece razão social; qualquer outro rótulo fica intacto
    sufixos = {"LTDA", "LTDA.", "S/A", "S.A.", "SA", "ME", "EPP", "EIRELI"}
    palavras = bruto.split()
    if len(palavras) < 3 or not any(p.upper().strip(".") in sufixos for p in palavras):
        return bruto

    return palavras[0].title()


def active_link(request: Request, prefix: str):
    path = request.url.path
    return path == prefix or path.startswith(f"{prefix}/")

