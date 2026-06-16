from fastapi.testclient import TestClient

from app.auth import hash_password, verify_password
from app.main import app


def test_hash_and_verify_password():
    raw = "SenhaForte123!"
    digest = hash_password(raw)
    assert digest != raw
    assert verify_password(raw, digest) is True
    assert verify_password("errada", digest) is False


def test_login_redirects_when_invalid_credentials():
    client = TestClient(app)
    response = client.post(
        "/auth/login",
        data={"email": "naoexiste@local", "senha": "errada"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/auth/login?erro=1"

