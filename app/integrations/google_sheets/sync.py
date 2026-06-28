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


garantir_schema()
criar_tabela_maintenance()


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
    created = 0
    updated = 0

    for ticket in tickets:
        where_source = and_(
            maintenance_tickets.c.source_spreadsheet_id == ticket["source_spreadsheet_id"],
            maintenance_tickets.c.source_gid == ticket["source_gid"],
            maintenance_tickets.c.source_row == ticket["source_row"],
        )
        exists = db.execute(select(maintenance_tickets.c.id).where(where_source)).first()

        values = {
            **ticket,
            "updated_system_at": datetime.utcnow(),
        }

        if exists:
            db.execute(update(maintenance_tickets).where(where_source).values(**values))
            updated += 1
        else:
            values["created_system_at"] = datetime.utcnow()
            db.execute(insert(maintenance_tickets).values(**values))
            created += 1

    db.commit()
    print(f"Total de registros criados: {created}")
    print(f"Total de registros atualizados: {updated}")
    return created, updated


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
    created, updated = upsert_tickets(db, tickets)
    csv_path, excel_path = export_to_files(tickets, output_dir)

    return {
        **diagnostics,
        "created": created,
        "updated": updated,
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
