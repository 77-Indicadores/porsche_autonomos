"""
Apaga todos os registros de dim_carros.
Rodar na raiz do projeto: python zerar_carros.py
"""
from app.database import engine
from sqlalchemy import text

with engine.begin() as conn:
    result = conn.execute(text("DELETE FROM dim_carros"))
    print(f"Deletados: {result.rowcount} carros")
