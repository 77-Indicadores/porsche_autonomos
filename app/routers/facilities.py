import csv
import os
import json
import shutil
import tempfile
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import RedirectResponse
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
GOOGLE_TOKEN_DB_KEY = "google_sheets_token"

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


def fmt_file_date(path: Path):
    if not path.exists():
        return "-"
    return datetime.fromtimestamp(path.stat().st_mtime).strftime("%d/%m/%Y %H:%M")


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


def _get_config(db: Session, chave: str) -> str | None:
    from app.models import ConfigSistema
    obj = db.query(ConfigSistema).filter(ConfigSistema.chave == chave).first()
    return obj.valor if obj else None


def _set_config(db: Session, chave: str, valor: str):
    from app.models import ConfigSistema
    obj = db.query(ConfigSistema).filter(ConfigSistema.chave == chave).first()
    if obj:
        obj.valor = valor
    else:
        db.add(ConfigSistema(chave=chave, valor=valor))
    db.commit()


def ler_complementos(db: Session) -> dict:
    from app.models import FacilitiesComplemento
    dados: dict = {}
    try:
        rows = db.query(FacilitiesComplemento).all()
        for row in rows:
            dados[row.source_row] = {
                "area_servico": row.area_servico or "",
                "unidade_local": row.unidade_local or "",
                "tipo_atendimento": row.tipo_atendimento or "",
                "data_inicio": row.data_inicio or "",
                "data_finalizacao": row.data_finalizacao or "",
                "dentro_prazo": row.dentro_prazo or "",
                "retrabalho": row.retrabalho or "",
                "custo": row.custo or "",
                "observacao": row.observacao or "",
                "rastreamento": row.rastreamento or "",
                "atualizado_em": row.atualizado_em or "",
            }
    except Exception:
        pass
    # Migração única do JSON legado quando o banco ainda está vazio
    if not dados and os.path.exists(DEFAULT_COMPLEMENTOS_PATH):
        try:
            with open(DEFAULT_COMPLEMENTOS_PATH, "r", encoding="utf-8") as arquivo:
                dados = json.load(arquivo)
        except Exception:
            pass
    return dados


def _upsert_complemento(db: Session, chave: str, dados: dict):
    from app.models import FacilitiesComplemento
    obj = db.query(FacilitiesComplemento).filter(FacilitiesComplemento.source_row == chave).first()
    if obj is None:
        obj = FacilitiesComplemento(source_row=chave)
        db.add(obj)
    obj.area_servico = dados.get("area_servico", "")
    obj.unidade_local = dados.get("unidade_local", "")
    obj.tipo_atendimento = dados.get("tipo_atendimento", "")
    obj.data_inicio = dados.get("data_inicio", "")
    obj.data_finalizacao = dados.get("data_finalizacao", "")
    obj.dentro_prazo = dados.get("dentro_prazo", "")
    obj.retrabalho = dados.get("retrabalho", "")
    obj.custo = dados.get("custo", "")
    obj.observacao = dados.get("observacao", "")
    obj.rastreamento = dados.get("rastreamento", "")
    obj.atualizado_em = dados.get("atualizado_em", "")
    db.commit()


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


def _preparar_token_path(db: Session) -> str:
    """Garante que o token esteja disponível no caminho esperado.

    Tenta carregar do banco quando o arquivo não existe localmente,
    permitindo que o token sobreviva a deploys.
    """
    if not os.path.exists(DEFAULT_TOKEN_PATH):
        token_json = _get_config(db, GOOGLE_TOKEN_DB_KEY)
        if token_json:
            os.makedirs(os.path.dirname(DEFAULT_TOKEN_PATH), exist_ok=True)
            with open(DEFAULT_TOKEN_PATH, "w", encoding="utf-8") as fh:
                fh.write(token_json)
    return DEFAULT_TOKEN_PATH


def _persistir_token_no_banco(db: Session):
    """Salva o token atual (possivelmente renovado) no banco."""
    if os.path.exists(DEFAULT_TOKEN_PATH):
        try:
            with open(DEFAULT_TOKEN_PATH, "r", encoding="utf-8") as fh:
                _set_config(db, GOOGLE_TOKEN_DB_KEY, fh.read())
        except Exception:
            pass


def tentar_atualizar_espelho(db: Session):
    if not os.path.exists(DEFAULT_OAUTH_CLIENT_PATH):
        return None, f"Arquivo OAuth não encontrado: {DEFAULT_OAUTH_CLIENT_PATH}"

    token_path = _preparar_token_path(db)
    if not os.path.exists(token_path):
        return None, f"Token Google não encontrado: {token_path}"

    try:
        result = sync_maintenance_tickets(
            db=db,
            oauth_client_path=DEFAULT_OAUTH_CLIENT_PATH,
            token_path=token_path,
            output_dir=DEFAULT_AUDIT_DIR,
        )
        _persistir_token_no_banco(db)
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

    return preparar_chamados(rows, ler_complementos(db)), source_notice, source_error


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

    complementos = ler_complementos(db)
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
                "has_token": os.path.exists(DEFAULT_TOKEN_PATH) or bool(_get_config(db, GOOGLE_TOKEN_DB_KEY)),
                "cache_csv_path": DEFAULT_CACHE_CSV_PATH,
                "has_cache_csv": os.path.exists(DEFAULT_CACHE_CSV_PATH),
                "complementos_path": DEFAULT_COMPLEMENTOS_PATH,
                "complementar_xlsx_path": str(COMPLEMENTAR_XLSX_PATH),
                "has_complementar_xlsx": COMPLEMENTAR_XLSX_PATH.exists(),
                "complementar_xlsx_updated_at": fmt_file_date(COMPLEMENTAR_XLSX_PATH),
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
    db: Session = Depends(get_db),
):
    chave = str(source_row).strip()
    dados = {
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
        _upsert_complemento(db, chave, dados)
        return redirect_with_message("/facilities", success="Complemento salvo.")
    except Exception as exc:
        return redirect_with_message("/facilities", error=f"Erro ao salvar complemento: {exc}")


@router.post("/facilities/upload-complementar")
async def upload_complementar(request: Request, arquivo: UploadFile = File(...), db: Session = Depends(get_db)):
    if not _is_admin(request):
        return redirect_with_message(
            "/facilities",
            error="Somente o administrador pode carregar a planilha complementar.",
        )

    nome_arquivo = arquivo.filename or ""
    if not nome_arquivo.lower().endswith(".xlsx"):
        return redirect_with_message(
            "/facilities",
            error="Envie um arquivo Excel no formato .xlsx.",
        )

    conteudo = await arquivo.read()
    if not conteudo:
        return redirect_with_message(
            "/facilities",
            error="O arquivo enviado está vazio.",
        )

    COMPLEMENTAR_XLSX_PATH.parent.mkdir(parents=True, exist_ok=True)
    temp_path = COMPLEMENTAR_XLSX_PATH.with_name(
        f"{COMPLEMENTAR_XLSX_PATH.stem}_upload_tmp{COMPLEMENTAR_XLSX_PATH.suffix}"
    )

    try:
        temp_path.write_bytes(conteudo)

        from openpyxl import load_workbook

        wb = load_workbook(temp_path, data_only=True, read_only=True)
        tem_lista_suspensa = "LISTA SUSPENSA" in wb.sheetnames
        tem_facilities = "FACILITIES" in wb.sheetnames

        if not tem_lista_suspensa:
            wb.close()
            return redirect_with_message(
                "/facilities",
                error="A planilha precisa ter a aba LISTA SUSPENSA.",
            )

        # Importa dados da aba FACILITIES para o JSON de complementos
        # Match por: data + nome (primeiro nome) + setor (abreviação)
        linhas_importadas = 0
        if tem_facilities:
            ws_fac = wb["FACILITIES"]

            # Mapa de setor completo (CSV) → abreviação (Excel)
            SETOR_MAP = {
                "RECURSOS HUMANOS": "RHU", "ADMINISTRATIVO": "ADM", "FINANCEIRO": "ADM",
                "DIRETORIA DE OPERAÇOES": "DOP", "DIRETORIA DE OPERAÇÕES": "DOP",
                "PLANEJAMENTO E RELACIONAMENTO": "PER", "LOGÍSTICA": "LOG", "LOGISTICA": "LOG",
                "RECUPERAÇÃO E DESENVOLVIMENTO": "RED", "RECUPERACAO E DESENVOLVIMENTO": "RED",
                "ENGENHARIA DE QUALIDADE": "ENQ", "ENGENHARIA DE OFICINA": "ENG",
                "PEÇAS": "PEC", "PECAS": "PEC", "PNEUS E RODAS": "PNR",
                "CHALLENGE": "CT1", "CARREIRA": "CT2", "FUNILARIA": "FUN",
                "PRESIDÊNCIA": "PRE", "PRESIDENCIA": "PRE", "OFICINA": "CT2",
            }

            def normalizar_nome(nome: str) -> str:
                """Extrai e normaliza o primeiro nome."""
                if not nome:
                    return ""
                # Se for email, pega a parte antes do @
                if "@" in nome:
                    nome = nome.split("@")[0].replace(".", " ")
                return nome.strip().upper().split()[0] if nome.strip() else ""

            def score_match(excel_sol: str, excel_setor: str, csv_nome: str, csv_email: str, csv_setor: str) -> int:
                score = 0
                primeiro_excel = normalizar_nome(str(excel_sol) if excel_sol else "")
                primeiro_csv_nome = normalizar_nome(csv_nome)
                primeiro_csv_email = normalizar_nome(csv_email)
                if primeiro_excel and (primeiro_excel == primeiro_csv_nome or primeiro_excel == primeiro_csv_email):
                    score += 2
                setor_abrev = SETOR_MAP.get(csv_setor.strip().upper(), "")
                if setor_abrev and excel_setor and setor_abrev == str(excel_setor).strip().upper():
                    score += 1
                return score

            from collections import defaultdict
            excel_por_data = defaultdict(list)
            for row in ws_fac.iter_rows(min_row=3, values_only=True):
                if row[0] is None:
                    continue
                data_abertura = row[4]
                if not data_abertura:
                    continue
                data_str = data_abertura.strftime("%Y-%m-%d") if hasattr(data_abertura, "strftime") else str(data_abertura)[:10]
                data_inicio = row[11]
                data_fin = row[12]
                excel_por_data[data_str].append({
                    "solicitante": str(row[2]) if row[2] else "",
                    "setor": str(row[3]) if row[3] else "",
                    "usado": False,
                    "dados": {
                        "data_inicio": data_inicio.strftime("%Y-%m-%d") if hasattr(data_inicio, "strftime") else (str(data_inicio) if data_inicio else ""),
                        "data_finalizacao": data_fin.strftime("%Y-%m-%d") if hasattr(data_fin, "strftime") else (str(data_fin) if data_fin else ""),
                        "prazo": str(row[15]) if row[15] else "",
                        "retrabalho": str(row[16]) if row[16] else "",
                        "custo": str(row[17]) if row[17] else "",
                        "observacao": str(row[18]) if row[18] else "",
                    },
                })

            complementos_novos = {}
            csv_path = DEFAULT_CACHE_CSV_PATH
            if os.path.exists(csv_path):
                with open(csv_path, "r", encoding="utf-8-sig", newline="") as arq:
                    reader = csv.DictReader(arq)
                    vals_list = list(reader.fieldnames) if reader.fieldnames else []
                    for idx, row_csv in enumerate(reader, start=2):
                        vals = list(row_csv.values())
                        if not vals or not vals[0]:
                            continue
                        raw_date = vals[0]
                        try:
                            data_csv = datetime.strptime(raw_date[:10], "%d/%m/%Y").strftime("%Y-%m-%d")
                        except Exception:
                            try:
                                data_csv = datetime.strptime(raw_date[:10], "%Y-%m-%d").strftime("%Y-%m-%d")
                            except Exception:
                                continue
                        csv_nome = vals[1] if len(vals) > 1 else ""
                        csv_email = vals[2] if len(vals) > 2 else ""
                        csv_setor = vals[3] if len(vals) > 3 else ""

                        candidatos = excel_por_data.get(data_csv, [])
                        melhor_idx = -1
                        melhor_score = -1
                        for ci, cand in enumerate(candidatos):
                            if cand["usado"]:
                                continue
                            s = score_match(cand["solicitante"], cand["setor"], csv_nome, csv_email, csv_setor)
                            if s > melhor_score:
                                melhor_score = s
                                melhor_idx = ci

                        if melhor_idx >= 0:
                            candidatos[melhor_idx]["usado"] = True
                            complementos_novos[str(idx)] = candidatos[melhor_idx]["dados"]
                            linhas_importadas += 1

            for chave_novo, dados_novo in complementos_novos.items():
                _upsert_complemento(db, chave_novo, dados_novo)

        wb.close()

        if COMPLEMENTAR_XLSX_PATH.exists():
            backup_path = COMPLEMENTAR_XLSX_PATH.with_name(
                f"{COMPLEMENTAR_XLSX_PATH.stem}_backup_{datetime.now():%Y%m%d_%H%M%S}{COMPLEMENTAR_XLSX_PATH.suffix}"
            )
            shutil.copy2(COMPLEMENTAR_XLSX_PATH, backup_path)

        try:
            if COMPLEMENTAR_XLSX_PATH.exists():
                COMPLEMENTAR_XLSX_PATH.unlink()
            temp_path.replace(COMPLEMENTAR_XLSX_PATH)
        except OSError:
            COMPLEMENTAR_XLSX_PATH.write_bytes(conteudo)

        msg = f"Planilha complementar carregada com sucesso. {linhas_importadas} linhas importadas."
        return redirect_with_message("/facilities", success=msg)
    except Exception as exc:
        return redirect_with_message(
            "/facilities",
            error=f"Não consegui carregar a planilha complementar: {exc}",
        )
    finally:
        if temp_path.exists():
            try:
                temp_path.unlink()
            except OSError:
                pass


@router.post("/facilities/sincronizar")
def sincronizar(
    request: Request,
    oauth_client_path: str = Form(DEFAULT_OAUTH_CLIENT_PATH),
    token_path: str = Form(DEFAULT_TOKEN_PATH),
    audit_dir: str = Form(DEFAULT_AUDIT_DIR),
    db: Session = Depends(get_db),
):
    if not _is_admin(request):
        return RedirectResponse("/?sem_acesso=facilities", status_code=303)
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
