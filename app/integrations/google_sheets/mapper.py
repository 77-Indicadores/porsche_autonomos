import re
from datetime import datetime
from decimal import Decimal, InvalidOperation


COLUMN_MAP = {
    "Carimbo de data/hora": "created_at",
    "Nome completo do solicitante:": "requester_name",
    "E-mail corporativo do solicitante:": "requester_email",
    "Setor do solicitante:": "department",
    "Local da manutenção:\n(Andar, sala, setor, equipamento...)": "location",
    "Unidade:": "unit",
    "Realizar upload de foto": "photo_url",
    "Categoria:": "category",
    "Natureza do chamado:": "maintenance_type",
    "Descrição do problema:": "problem_description",
    "Status": "status",
    "Urgência": "priority",
    "Valor": "amount",
    "Fornecedor": "supplier",
    "Descrição": "internal_description",
    "Data de conclusão": "completed_at",
    "OS": "work_order",
}


def normalize_text(value):
    if value is None:
        return ""
    return str(value).strip()


def normalize_column(value):
    value = normalize_text(value).replace("\r\n", "\n").replace("\r", "\n")
    return re.sub(r"[ \t]+", " ", value)


def parse_brazilian_currency(value):
    value = normalize_text(value)
    if not value:
        return None

    value = value.replace("R$", "").strip()
    value = value.replace(".", "").replace(",", ".")

    try:
        return Decimal(value)
    except InvalidOperation:
        return None


def parse_brazilian_datetime(value):
    value = normalize_text(value)
    if not value:
        return None

    formats = [
        "%d/%m/%Y %H:%M:%S",
        "%d/%m/%Y %H:%M",
        "%d/%m/%Y",
    ]

    for fmt in formats:
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            pass

    return None


def normalize_status(value):
    value = normalize_text(value).upper()
    status_map = {
        "CONCLUÍDO": "completed",
        "CONCLUIDO": "completed",
        "FECHADO": "closed",
        "ABERTO": "open",
        "EM ANDAMENTO": "in_progress",
        "PENDENTE": "pending",
    }
    return status_map.get(value, value.lower())


def normalize_priority(value):
    value = normalize_text(value).upper()
    priority_map = {
        "BAIXA": "low",
        "MÉDIA": "medium",
        "MEDIA": "medium",
        "ALTA": "high",
        "URGENTE": "urgent",
    }
    return priority_map.get(value, value.lower())


def map_row(row: dict) -> dict:
    normalized_row = {
        normalize_column(column): value
        for column, value in (row or {}).items()
    }

    mapped = {}
    for google_column, internal_column in COLUMN_MAP.items():
        mapped[internal_column] = normalized_row.get(
            normalize_column(google_column),
            "",
        )

    mapped["created_at"] = parse_brazilian_datetime(mapped["created_at"])
    mapped["completed_at"] = parse_brazilian_datetime(mapped["completed_at"])
    mapped["amount"] = parse_brazilian_currency(mapped["amount"])
    mapped["status"] = normalize_status(mapped["status"])
    mapped["priority"] = normalize_priority(mapped["priority"])

    for key, value in mapped.items():
        if isinstance(value, str):
            mapped[key] = normalize_text(value)

    return mapped
