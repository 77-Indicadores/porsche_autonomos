import json
import os
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Column,
    DateTime,
    Integer,
    MetaData,
    Numeric,
    String,
    Table,
    Text,
    and_,
    insert,
    select,
    text,
    update,
)
from sqlalchemy.orm import Session

from app.database import engine
from app.integrations.google_sheets.client import GoogleSheetsClient
from app.integrations.google_sheets.mapper import map_row


SPREADSHEET_ID = "1r6nqxnkIoi16XO3oEOOi9bcU5MaisoMPwnABdDvOm8U"
GID_ABA_RESPOSTAS = 595052879
SHEET_NAME = "Controle de Reformas Prediais V1"
WORKSHEET_NAME = "Respostas ao formulário 1"

metadata_maintenance = MetaData()

maintenance_tickets = Table(
    "maintenance_tickets",
    metadata_maintenance,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("source", String(80), nullable=False),
    Column("source_spreadsheet_id", String(180), nullable=False),
    Column("source_gid", Integer, nullable=False),
    Column("source_row", Integer, nullable=False),
    Column("created_at", DateTime),
    Column("requester_name", Text),
    Column("requester_email", Text),
    Column("department", Text),
    Column("location", Text),
    Column("unit", Text),
    Column("photo_url", Text),
    Column("category", Text),
    Column("maintenance_type", Text),
    Column("problem_description", Text),
    Column("status", String(80)),
    Column("priority", String(80)),
    Column("amount", Numeric(12, 2)),
    Column("supplier", Text),
    Column("internal_description", Text),
    Column("completed_at", DateTime),
    Column("work_order", Text),
    Column("raw_payload", Text),
    # identidade do chamado que nao muda quando linhas sao apagadas na planilha
    Column("chave", Text),
    Column("created_system_at", DateTime, default=datetime.utcnow),
    Column("updated_system_at", DateTime, default=datetime.utcnow),
)


def criar_tabela_maintenance():
    try:
        metadata_maintenance.create_all(engine)
    except Exception as exc:
        print(f"AVISO - não consegui criar tabela maintenance_tickets: {exc}")


def garantir_schema():
    try:
        with engine.begin() as conn:
            if conn.dialect.name == "postgresql":
                conn.execute(text("""
                    CREATE TABLE IF NOT EXISTS maintenance_tickets (
                        id SERIAL PRIMARY KEY,
                        source VARCHAR(80) NOT NULL,
                        source_spreadsheet_id VARCHAR(180) NOT NULL,
                        source_gid INTEGER NOT NULL,
                        source_row INTEGER NOT NULL,
                        created_at TIMESTAMP,
                        requester_name TEXT,
                        requester_email TEXT,
                        department TEXT,
                        location TEXT,
                        unit TEXT,
                        photo_url TEXT,
                        category TEXT,
                        maintenance_type TEXT,
                        problem_description TEXT,
                        status VARCHAR(80),
                        priority VARCHAR(80),
                        amount NUMERIC(12, 2),
                        supplier TEXT,
                        internal_description TEXT,
                        completed_at TIMESTAMP,
                        work_order TEXT,
                        raw_payload TEXT,
                        created_system_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_system_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE(source_spreadsheet_id, source_gid, source_row)
                    )
                """))
                conn.execute(text("""
                    CREATE UNIQUE INDEX IF NOT EXISTS ux_maintenance_source_row
                    ON maintenance_tickets(source_spreadsheet_id, source_gid, source_row)
                """))
            elif conn.dialect.name == "sqlite":
                conn.execute(text("""
                    CREATE UNIQUE INDEX IF NOT EXISTS ux_maintenance_source_row
                    ON maintenance_tickets(source_spreadsheet_id, source_gid, source_row)
                """))
    except Exception as exc:
        print(f"AVISO - não consegui ajustar schema maintenance_tickets: {exc}")


def garantir_coluna_chave():
    try:
        with engine.begin() as conn:
            if conn.dialect.name == "postgresql":
                conn.execute(text("ALTER TABLE maintenance_tickets ADD COLUMN IF NOT EXISTS chave TEXT"))
            else:
                cols = [r[1] for r in conn.execute(text("PRAGMA table_info(maintenance_tickets)"))]
                if cols and "chave" not in cols:
                    conn.execute(text("ALTER TABLE maintenance_tickets ADD COLUMN chave TEXT"))
    except Exception as exc:
        print(f"AVISO - não consegui adicionar a coluna chave: {exc}")


garantir_schema()
criar_tabela_maintenance()
garantir_coluna_chave()


# ─── identidade do chamado ────────────────────────────────────────────────────
# O chamado era identificado pelo NUMERO DA LINHA da planilha, e o complemento
# (status, datas, custo) ficava preso a esse numero. Apagar uma linha fazia
# todas as de baixo subirem, e cada complemento passava a aparecer no chamado
# seguinte. A identidade agora e o carimbo de data/hora do formulario mais o
# e-mail de quem abriu: nao muda quando linhas sao apagadas ou reordenadas.

def chave_chamado(ticket) -> str:
    carimbo = ticket.get("created_at")
    if isinstance(carimbo, datetime):
        carimbo = carimbo.strftime("%Y-%m-%d %H:%M:%S")
    carimbo = str(carimbo or "").strip()[:19]
    quem = str(ticket.get("requester_email") or "").strip().lower()
    if not quem:
        quem = " ".join(str(ticket.get("requester_name") or "").split()).upper()
    if not carimbo:
        return ""
    return f"{carimbo}|{quem}"


def id_estavel(chave: str) -> str:
    """Chave curta (20 caracteres) para as tabelas de complemento e exclusao,
    cuja coluna de identificacao tem esse tamanho. Comeca com "k" para nunca
    se confundir com um numero de linha antigo."""
    import hashlib
    if not chave:
        return ""
    return "k" + hashlib.sha1(chave.encode("utf-8")).hexdigest()[:19]


def json_default(value):
    if isinstance(value, (datetime, Decimal)):
        return str(value)
    return value


def fetch_maintenance_tickets(oauth_client_path: str, token_path: str):
    print("Iniciando conexão Google Sheets...")
    google_client = GoogleSheetsClient(
        oauth_client_path=oauth_client_path,
        token_path=token_path,
    )

    email = google_client.authenticated_email()
    print(f"Conta Google autenticada: {email or 'não identificada'}")

    spreadsheet = google_client.open_spreadsheet(SPREADSHEET_ID)
    print(f"Planilha aberta com sucesso: {spreadsheet.title}")

    worksheets = spreadsheet.worksheets()
    print("Abas encontradas:")
    for worksheet in worksheets:
        print(f"- {worksheet.title} | GID: {worksheet.id}")

    worksheet = google_client.get_worksheet_by_gid(
        spreadsheet_id=SPREADSHEET_ID,
        gid=GID_ABA_RESPOSTAS,
    )

    rows = worksheet.get_all_records()
    print(f"Quantidade de linhas lidas: {len(rows)}")
    print(f"Primeiras linhas lidas: {rows[:3]}")

    tickets = []
    for index, row in enumerate(rows, start=2):
        if not str(row.get("Carimbo de data/hora", "")).strip():
            continue
        ticket = map_row(row)
        ticket["source"] = "google_sheets"
        ticket["source_row"] = index
        ticket["source_spreadsheet_id"] = SPREADSHEET_ID
        ticket["source_gid"] = GID_ABA_RESPOSTAS
        ticket["raw_payload"] = json.dumps(row, ensure_ascii=False, default=json_default)
        tickets.append(ticket)

    # linha copiada e colada gera duas respostas com a mesma identidade; a
    # segunda ganha sufixo para as duas continuarem existindo
    vistas: dict[str, int] = {}
    for ticket in tickets:
        base = chave_chamado(ticket) or f"linha-{ticket['source_row']}"
        vistas[base] = vistas.get(base, 0) + 1
        ticket["chave"] = base if vistas[base] == 1 else f"{base}#{vistas[base]}"

    return tickets, {
        "authenticated_email": email,
        "spreadsheet_title": spreadsheet.title,
        "worksheets": [{"title": w.title, "gid": w.id} for w in worksheets],
        "rows_read": len(rows),
        "first_rows": rows[:3],
    }


def export_to_files(tickets, output_dir):
    os.makedirs(output_dir, exist_ok=True)
    csv_path = os.path.join(output_dir, "bosch_chamados_manutencao.csv")
    excel_path = os.path.join(output_dir, "bosch_chamados_manutencao.xlsx")

    try:
        import pandas as pd

        df = pd.DataFrame(tickets)
        df.to_csv(csv_path, index=False, encoding="utf-8-sig")
        df.to_excel(excel_path, index=False)
    except Exception as exc:
        print(f"AVISO - não consegui exportar auditoria CSV/Excel: {exc}")
        return None, None

    return csv_path, excel_path


def upsert_tickets(db: Session, tickets):
    """Espelha a aba na tabela: cria, atualiza e REMOVE.

    Antes so criava e atualizava, casando pelo numero da linha. Com uma linha
    apagada na planilha, o chamado de baixo sobrescrevia o de cima e a ultima
    linha antiga ficava sobrando no sistema, duplicada. Agora casa pela chave
    do chamado, renumera o que mudou de linha e apaga o que saiu da planilha.
    """
    created = updated = removed = 0
    if not tickets:
        # planilha lida vazia e mais provavel ser falha de leitura do que a
        # aba ter sido esvaziada: nao apaga o espelho inteiro por isso
        return 0, 0, 0

    planilha = tickets[0]["source_spreadsheet_id"]
    aba = tickets[0]["source_gid"]
    da_aba = and_(
        maintenance_tickets.c.source_spreadsheet_id == planilha,
        maintenance_tickets.c.source_gid == aba,
    )
    chaves = {t["chave"] for t in tickets}

    try:
        existentes: dict = {}
        repetidos: list[int] = []
        for r in db.execute(select(maintenance_tickets.c.id, maintenance_tickets.c.chave)
                            .where(da_aba).order_by(maintenance_tickets.c.id)):
            if r.chave in existentes:
                repetidos.append(r.id)   # mesma chave duas vezes no espelho: fica uma
            else:
                existentes[r.chave] = r.id

        # 1. o que nao esta mais na planilha sai (inclui linhas antigas sem chave)
        sumiram = [i for c, i in existentes.items() if c not in chaves] + repetidos
        sem_chave = db.execute(
            select(maintenance_tickets.c.id).where(da_aba).where(maintenance_tickets.c.chave.is_(None))
        ).scalars().all()
        apagar = set(sumiram) | set(sem_chave)
        if apagar:
            db.execute(maintenance_tickets.delete().where(maintenance_tickets.c.id.in_(apagar)))
            removed = len(apagar)

        # 2. numero de linha provisorio e unico: sem isso, mover o chamado da
        #    linha 11 para a 10 bate no indice unico enquanto a 10 ainda existe
        db.execute(update(maintenance_tickets).where(da_aba).values(source_row=-maintenance_tickets.c.id))

        agora = datetime.utcnow()
        for ticket in tickets:
            values = {**ticket, "updated_system_at": agora}
            id_existente = existentes.get(ticket["chave"])
            if id_existente is not None and id_existente not in apagar:
                db.execute(update(maintenance_tickets).where(maintenance_tickets.c.id == id_existente).values(**values))
                updated += 1
            else:
                values["created_system_at"] = agora
                db.execute(insert(maintenance_tickets).values(**values))
                created += 1

        db.commit()
    except Exception:
        db.rollback()
        raise

    print(f"Espelho: {created} criados, {updated} atualizados, {removed} removidos")
    return created, updated, removed


def sync_maintenance_tickets(
    db: Session,
    oauth_client_path: str,
    token_path: str,
    output_dir: str,
):
    tickets, diagnostics = fetch_maintenance_tickets(
        oauth_client_path=oauth_client_path,
        token_path=token_path,
    )
    created, updated, removed = upsert_tickets(db, tickets)
    csv_path, excel_path = export_to_files(tickets, output_dir)

    return {
        **diagnostics,
        "created": created,
        "updated": updated,
        "removed": removed,
        "total": len(tickets),
        "csv_path": csv_path,
        "excel_path": excel_path,
    }


if __name__ == "__main__":
    from app.database import SessionLocal

    default_credentials_dir = os.getenv(
        "GOOGLE_SHEETS_CREDENTIALS_DIR",
        "C:/planilha_google",
    )
    db = SessionLocal()
    try:
        result = sync_maintenance_tickets(
            db=db,
            oauth_client_path=os.path.join(default_credentials_dir, "oauth_client.json"),
            token_path=os.path.join(default_credentials_dir, "token_google.json"),
            output_dir=os.getenv("FACILITIES_AUDIT_DIR", "C:/planilha_google"),
        )
        print(f"Sincronização concluída: {result}")
    finally:
        db.close()
