
from __future__ import annotations

import json
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parents[1]
LOG_DIR = BASE_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)

ERROR_LOG = LOG_DIR / "erros_detalhados.log"
EXCEL_LOG = LOG_DIR / "excel_import_errors.log"


def _safe_json(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, indent=2, default=str)
    except Exception:
        return str(value)


def log_error(contexto: str, exc: Exception, extra: dict | None = None, excel: bool = False) -> str:
    """
    Grava erro detalhado em arquivo .log.
    Retorna o id do erro para exibir na tela.
    """
    error_id = datetime.now().strftime("%Y%m%d_%H%M%S_%f")

    payload = {
        "error_id": error_id,
        "data_hora": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "contexto": contexto,
        "tipo_erro": type(exc).__name__,
        "mensagem": str(exc),
        "extra": extra or {},
        "traceback": traceback.format_exc(),
    }

    bloco = "\n" + "=" * 120 + "\n"
    bloco += _safe_json(payload)
    bloco += "\n" + "=" * 120 + "\n"

    ERROR_LOG.write_text(
        ERROR_LOG.read_text(encoding="utf-8") + bloco if ERROR_LOG.exists() else bloco,
        encoding="utf-8",
    )

    if excel:
        EXCEL_LOG.write_text(
            EXCEL_LOG.read_text(encoding="utf-8") + bloco if EXCEL_LOG.exists() else bloco,
            encoding="utf-8",
        )

    return error_id


def tail_log(path: Path, max_lines: int = 500) -> str:
    if not path.exists():
        return "Nenhum log encontrado ainda."

    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    return "\n".join(lines[-max_lines:])
