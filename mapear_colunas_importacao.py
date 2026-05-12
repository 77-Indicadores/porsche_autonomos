from pathlib import Path
import sqlite3
import json
import sys
from datetime import datetime

BASE = Path(__file__).resolve().parent
DB_PATH = BASE / "data" / "app.db"
EXCEL_ROUTER = BASE / "app" / "routers" / "excel.py"
OUT_MD = BASE / "MAPEAMENTO_IMPORTACAO_EXCEL.md"
OUT_JSON = BASE / "mapeamento_importacao_excel.json"

# Garante leitura de libs locais do projeto
vendor = BASE / ".vendor"
if vendor.exists():
    sys.path.insert(0, str(vendor))

def get_db_schema():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    tables = conn.execute("""
        SELECT name 
        FROM sqlite_master 
        WHERE type='table'
        AND name NOT LIKE 'sqlite_%'
        ORDER BY name
    """).fetchall()

    schema = {}

    for t in tables:
        table = t["name"]
        cols = conn.execute(f"PRAGMA table_info({table})").fetchall()
        schema[table] = []

        for c in cols:
            schema[table].append({
                "cid": c["cid"],
                "name": c["name"],
                "type": c["type"],
                "notnull": bool(c["notnull"]),
                "default": c["dflt_value"],
                "pk": bool(c["pk"]),
            })

    conn.close()
    return schema

def get_excel_mapping():
    try:
        from app.routers import excel
        return getattr(excel, "ENTIDADES", {})
    except Exception as exc:
        return {"_erro_import_excel_router": str(exc)}

def normalize_mapping(mapping):
    normalized = {}

    for key, cfg in mapping.items():
        if key.startswith("_erro"):
            normalized[key] = cfg
            continue

        normalized[key] = {
            "label": cfg.get("label"),
            "table": cfg.get("table"),
            "unique": cfg.get("unique", []),
            "columns": cfg.get("columns", []),
            "example": cfg.get("example", []),
        }

    return normalized

def compare(schema, mapping):
    comparisons = {}

    for entity, cfg in mapping.items():
        if entity.startswith("_erro"):
            continue

        table = cfg.get("table")
        import_cols = cfg.get("columns", [])

        if table not in schema:
            comparisons[entity] = {
                "table": table,
                "status": "TABELA_NAO_ENCONTRADA",
                "columns_import": import_cols,
                "columns_db": [],
                "missing_in_db": import_cols,
                "missing_in_import": [],
                "suggested_import_columns": [],
            }
            continue

        db_cols = [c["name"] for c in schema[table]]
        pk_cols = [c["name"] for c in schema[table] if c["pk"]]

        ignore_default = set(pk_cols + [
            "id",
            "created_at",
            "updated_at",
            "criado_em",
            "atualizado_em",
        ])

        db_importable = [c for c in db_cols if c not in ignore_default]

        missing_in_db = [c for c in import_cols if c not in db_cols]
        missing_in_import = [c for c in db_importable if c not in import_cols]

        status = "OK"
        if missing_in_db or missing_in_import:
            status = "DIVERGENTE"

        comparisons[entity] = {
            "table": table,
            "status": status,
            "primary_keys": pk_cols,
            "columns_import": import_cols,
            "columns_db": db_cols,
            "db_importable_columns": db_importable,
            "missing_in_db": missing_in_db,
            "missing_in_import": missing_in_import,
            "suggested_import_columns": db_importable,
        }

    return comparisons

def make_markdown(schema, mapping, comparisons):
    lines = []

    lines.append("# Mapeamento de Importação Excel")
    lines.append("")
    lines.append(f"Gerado em: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}")
    lines.append("")
    lines.append(f"Banco analisado: `{DB_PATH}`")
    lines.append(f"Router Excel analisado: `{EXCEL_ROUTER}`")
    lines.append("")

    lines.append("## 1. Resumo das Entidades de Importação")
    lines.append("")
    lines.append("| Entidade | Tabela | Status | Colunas no Excel | Colunas importáveis no banco | Divergências |")
    lines.append("|---|---|---:|---:|---:|---:|")

    for entity, comp in comparisons.items():
        diverg = len(comp.get("missing_in_db", [])) + len(comp.get("missing_in_import", []))
        lines.append(
            f"| `{entity}` | `{comp['table']}` | `{comp['status']}` | "
            f"{len(comp.get('columns_import', []))} | "
            f"{len(comp.get('db_importable_columns', []))} | "
            f"{diverg} |"
        )

    lines.append("")
    lines.append("## 2. Detalhamento por Entidade")
    lines.append("")

    for entity, comp in comparisons.items():
        lines.append(f"### {entity}")
        lines.append("")
        lines.append(f"Tabela: `{comp['table']}`")
        lines.append("")
        lines.append(f"Status: **{comp['status']}**")
        lines.append("")

        lines.append("**Colunas usadas hoje no modelo Excel:**")
        lines.append("")
        for c in comp.get("columns_import", []):
            lines.append(f"- `{c}`")
        if not comp.get("columns_import"):
            lines.append("- Nenhuma coluna mapeada")
        lines.append("")

        lines.append("**Colunas reais no banco:**")
        lines.append("")
        for c in comp.get("columns_db", []):
            lines.append(f"- `{c}`")
        if not comp.get("columns_db"):
            lines.append("- Nenhuma coluna encontrada")
        lines.append("")

        lines.append("**Colunas sugeridas para importação:**")
        lines.append("")
        for c in comp.get("suggested_import_columns", []):
            lines.append(f"- `{c}`")
        if not comp.get("suggested_import_columns"):
            lines.append("- Nenhuma sugestão")
        lines.append("")

        if comp.get("missing_in_db"):
            lines.append("**Colunas no Excel que NÃO existem no banco:**")
            lines.append("")
            for c in comp["missing_in_db"]:
                lines.append(f"- `{c}`")
            lines.append("")

        if comp.get("missing_in_import"):
            lines.append("**Colunas no banco que NÃO estão no Excel:**")
            lines.append("")
            for c in comp["missing_in_import"]:
                lines.append(f"- `{c}`")
            lines.append("")

    lines.append("## 3. Schema completo do banco")
    lines.append("")

    for table, cols in schema.items():
        lines.append(f"### {table}")
        lines.append("")
        lines.append("| Coluna | Tipo | PK | Obrigatório | Default |")
        lines.append("|---|---|---:|---:|---|")

        for c in cols:
            lines.append(
                f"| `{c['name']}` | `{c['type']}` | "
                f"{'Sim' if c['pk'] else 'Não'} | "
                f"{'Sim' if c['notnull'] else 'Não'} | "
                f"{c['default'] or ''} |"
            )

        lines.append("")

    return "\n".join(lines)

def main():
    if not DB_PATH.exists():
        raise SystemExit(f"Banco não encontrado: {DB_PATH}")

    schema = get_db_schema()
    mapping = normalize_mapping(get_excel_mapping())
    comparisons = compare(schema, mapping)

    payload = {
        "generated_at": datetime.now().isoformat(),
        "db_path": str(DB_PATH),
        "excel_router": str(EXCEL_ROUTER),
        "schema": schema,
        "excel_mapping": mapping,
        "comparisons": comparisons,
    }

    OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    OUT_MD.write_text(make_markdown(schema, mapping, comparisons), encoding="utf-8")

    print("MAPEAMENTO GERADO COM SUCESSO")
    print(f"Markdown: {OUT_MD}")
    print(f"JSON: {OUT_JSON}")
    print("")
    print("Resumo:")
    for entity, comp in comparisons.items():
        print(f"- {entity}: {comp['status']} | tabela={comp['table']} | divergências={len(comp.get('missing_in_db', [])) + len(comp.get('missing_in_import', []))}")

if __name__ == "__main__":
    main()
