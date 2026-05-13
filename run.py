import sys
import argparse
from pathlib import Path


vendor = Path(__file__).resolve().parent / ".vendor"
if vendor.exists():
    sys.path.insert(0, str(vendor))

import uvicorn
from app.auth import hash_password
from app.database import SessionLocal
from app.models import Usuario


def build_parser():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command")

    create_user = sub.add_parser("create-user")
    create_user.add_argument("--nome", required=True)
    create_user.add_argument("--email", required=True)
    create_user.add_argument("--senha", required=True)
    create_user.add_argument("--perfil", choices=["admin", "operador"], default="operador")

    return parser


def create_user_cli(nome: str, email: str, senha: str, perfil: str):
    db = SessionLocal()
    try:
        exists = db.query(Usuario).filter(Usuario.email == email).first()
        if exists:
            raise SystemExit("Usuario ja existe")
        user = Usuario(nome=nome, email=email, senha_hash=hash_password(senha), perfil=perfil, ativo="Sim")
        db.add(user)
        db.commit()
        print(f"Usuario criado: {email} ({perfil})")
    finally:
        db.close()


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "create-user":
        args = build_parser().parse_args()
        create_user_cli(args.nome, args.email, args.senha, args.perfil)
        raise SystemExit(0)

    uvicorn.run("app.main:app", host="127.0.0.1", port=8000)
