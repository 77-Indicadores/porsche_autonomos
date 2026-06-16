from fastapi.testclient import TestClient

from app.main import app
from run import build_parser


def test_usuarios_requires_admin_session():
    client = TestClient(app)
    response = client.get("/usuarios", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"].startswith("/auth/login")


def test_create_user_command_parser_has_required_args():
    parser = build_parser()
    args = parser.parse_args(
        [
            "create-user",
            "--nome",
            "Administrador",
            "--email",
            "admin@local",
            "--senha",
            "Senha123!",
            "--perfil",
            "admin",
        ]
    )
    assert args.command == "create-user"
    assert args.perfil == "admin"

