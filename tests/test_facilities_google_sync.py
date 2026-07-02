import sys
import types
from pathlib import Path

from starlette.requests import Request


google_module = types.ModuleType("google")
google_auth_module = types.ModuleType("google.auth")
google_auth_transport_module = types.ModuleType("google.auth.transport")
google_auth_transport_requests_module = types.ModuleType("google.auth.transport.requests")
google_auth_transport_requests_module.Request = object
google_oauth2_module = types.ModuleType("google.oauth2")
google_oauth2_credentials_module = types.ModuleType("google.oauth2.credentials")
google_oauth2_credentials_module.Credentials = object
google_auth_oauthlib_module = types.ModuleType("google_auth_oauthlib")
google_auth_oauthlib_flow_module = types.ModuleType("google_auth_oauthlib.flow")
google_auth_oauthlib_flow_module.InstalledAppFlow = object
google_auth_oauthlib_flow_module.Flow = object

sys.modules.setdefault("google", google_module)
sys.modules.setdefault("google.auth", google_auth_module)
sys.modules.setdefault("google.auth.transport", google_auth_transport_module)
sys.modules.setdefault("google.auth.transport.requests", google_auth_transport_requests_module)
sys.modules.setdefault("google.oauth2", google_oauth2_module)
sys.modules.setdefault("google.oauth2.credentials", google_oauth2_credentials_module)
sys.modules.setdefault("google_auth_oauthlib", google_auth_oauthlib_module)
sys.modules.setdefault("google_auth_oauthlib.flow", google_auth_oauthlib_flow_module)

from app.routers import facilities


class _DbFalso:
    def __init__(self):
        self.commits = 0

    def commit(self):
        self.commits += 1

    def rollback(self):
        pass


def _request_admin(path: str = "/facilities/sincronizar"):
    request = Request({"type": "http", "method": "POST", "path": path, "headers": []})
    request.state.current_user = {"perfil": "admin"}
    return request


def test_google_sync_status_orienta_admin_a_conectar_quando_token_ausente():
    status = facilities.google_sync_status(has_oauth_client=True, has_token=False)

    assert status["label"] == "Pendente"
    assert "Atualizar espelho" in status["help"]
    assert "oauth_client.json" not in status["help"]


def test_sincronizar_restaura_e_persiste_credenciais_no_banco(monkeypatch):
    db = _DbFalso()
    restaurados = []
    persistidos = []

    monkeypatch.setattr(facilities, "_is_admin", lambda _request: True)
    monkeypatch.setattr(facilities, "ensure_google_oauth_client_config", lambda _db: True)
    monkeypatch.setattr(
        facilities,
        "_restaurar_arquivo_do_banco",
        lambda _db, chave, caminho: restaurados.append((chave, caminho)) or True,
    )
    monkeypatch.setattr(
        facilities,
        "_persistir_arquivo_no_banco",
        lambda _db, chave, caminho: persistidos.append((chave, caminho)),
    )
    monkeypatch.setattr(
        facilities,
        "sync_maintenance_tickets",
        lambda **_kwargs: {"total": 3, "created": 1, "updated": 2},
    )
    monkeypatch.setattr(facilities, "has_google_oauth_client", lambda _db: True)
    monkeypatch.setattr(facilities, "has_google_token", lambda _db: True)

    response = facilities.sincronizar(request=_request_admin(), db=db)

    assert response.status_code == 303
    assert response.headers["location"].startswith("/facilities?success=")
    assert (facilities.GOOGLE_OAUTH_CLIENT_DB_KEY, facilities.DEFAULT_OAUTH_CLIENT_PATH) in restaurados
    assert (facilities.GOOGLE_TOKEN_DB_KEY, facilities.DEFAULT_TOKEN_PATH) in restaurados
    assert (facilities.GOOGLE_OAUTH_CLIENT_DB_KEY, facilities.DEFAULT_OAUTH_CLIENT_PATH) in persistidos
    assert (facilities.GOOGLE_TOKEN_DB_KEY, facilities.DEFAULT_TOKEN_PATH) in persistidos
    assert db.commits == 1


def test_google_oauth_client_json_do_env_eh_reconhecido(monkeypatch):
    monkeypatch.setattr(
        facilities,
        "GOOGLE_WEB_CLIENT_JSON",
        '{"web":{"client_id":"abc","redirect_uris":["https://example.com/facilities/oauth/callback"]}}',
    )

    config = facilities.load_google_oauth_client_config()

    assert config["web"]["client_id"] == "abc"


def test_sincronizar_redireciona_para_oauth_quando_falta_token(monkeypatch):
    db = _DbFalso()

    monkeypatch.setattr(facilities, "_is_admin", lambda _request: True)
    monkeypatch.setattr(facilities, "_restaurar_credenciais_google", lambda _db: None)
    monkeypatch.setattr(facilities, "has_google_oauth_client", lambda _db: True)
    monkeypatch.setattr(facilities, "has_google_token", lambda _db: False)

    response = facilities.sincronizar(request=_request_admin(), db=db)

    assert response.status_code == 303
    assert response.headers["location"] == "/facilities/oauth/iniciar"


def test_oauth_iniciar_salva_code_verifier_para_callback(monkeypatch):
    db = _DbFalso()
    configs = {}

    class FakeFlow:
        code_verifier = "verifier-123"

        @classmethod
        def from_client_config(cls, *_args, **kwargs):
            assert kwargs["autogenerate_code_verifier"] is True
            return cls()

        def authorization_url(self, **_kwargs):
            return "https://accounts.google.com/o/oauth2/auth", "state-123"

    monkeypatch.setattr(facilities, "_is_admin", lambda _request: True)
    monkeypatch.setattr(facilities, "ensure_google_oauth_client_config", lambda _db: True)
    monkeypatch.setattr(
        facilities,
        "get_google_oauth_client_config",
        lambda _db: {"web": {"client_id": "abc"}},
    )
    monkeypatch.setattr(
        facilities,
        "get_google_oauth_redirect_uri",
        lambda _db: "https://example.com/facilities/oauth/callback",
    )
    monkeypatch.setattr(facilities, "Flow", FakeFlow)
    monkeypatch.setattr(facilities, "_set_config", lambda _db, key, value: configs.__setitem__(key, value))

    response = facilities.facilities_oauth_iniciar(
        request=_request_admin("/facilities/oauth/iniciar"),
        db=db,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "https://accounts.google.com/o/oauth2/auth"
    assert configs[facilities.GOOGLE_OAUTH_STATE_DB_KEY] == "state-123"
    assert configs[facilities.GOOGLE_OAUTH_CODE_VERIFIER_DB_KEY] == "verifier-123"


def test_oauth_callback_reusa_code_verifier_salvo(monkeypatch):
    db = _DbFalso()
    fetch_token_calls = []
    token_path = Path("data/test_token_google.json")
    oauth_client_path = Path("data/test_oauth_client.json")
    if token_path.exists():
        token_path.unlink()

    class FakeCredentials:
        def to_json(self):
            return '{"token":"abc"}'

    class FakeFlow:
        credentials = FakeCredentials()

        @classmethod
        def from_client_config(cls, *_args, **kwargs):
            assert kwargs["state"] == "state-123"
            assert kwargs["code_verifier"] == "verifier-123"
            return cls()

        def fetch_token(self, **kwargs):
            fetch_token_calls.append(kwargs)

    def fake_get_config(_db, key):
        return {
            facilities.GOOGLE_OAUTH_STATE_DB_KEY: "state-123",
            facilities.GOOGLE_OAUTH_CODE_VERIFIER_DB_KEY: "verifier-123",
        }.get(key, "")

    monkeypatch.setattr(facilities, "_is_admin", lambda _request: True)
    monkeypatch.setattr(
        facilities,
        "get_google_oauth_client_config",
        lambda _db: {"web": {"client_id": "abc"}},
    )
    monkeypatch.setattr(
        facilities,
        "get_google_oauth_redirect_uri",
        lambda _db: "https://example.com/facilities/oauth/callback",
    )
    monkeypatch.setattr(facilities, "_get_config", fake_get_config)
    monkeypatch.setattr(facilities, "Flow", FakeFlow)
    monkeypatch.setattr(facilities, "DEFAULT_TOKEN_PATH", str(token_path))
    monkeypatch.setattr(facilities, "DEFAULT_OAUTH_CLIENT_PATH", str(oauth_client_path))
    monkeypatch.setattr(facilities, "_restaurar_credenciais_google", lambda _db: None)
    monkeypatch.setattr(facilities, "_persistir_credenciais_google", lambda _db: None)
    monkeypatch.setattr(
        facilities,
        "sync_maintenance_tickets",
        lambda **_kwargs: {"total": 1, "created": 1, "updated": 0},
    )

    response = facilities.facilities_oauth_callback(
        request=_request_admin("/facilities/oauth/callback"),
        code="code-123",
        state="state-123",
        db=db,
    )

    assert response.status_code == 303
    assert response.headers["location"].startswith("/facilities?success=")
    assert fetch_token_calls == [{"code": "code-123"}]
    if token_path.exists():
        token_path.unlink()


def test_oauth_desconectar_remove_somente_token_e_estado(monkeypatch):
    db = _DbFalso()
    removidos = []
    token_path = Path("data/test_disconnect_token_google.json")
    oauth_client_path = Path("data/test_disconnect_oauth_client.json")
    token_path.write_text('{"token":"abc"}', encoding="utf-8")
    oauth_client_path.write_text('{"web":{"client_id":"abc"}}', encoding="utf-8")

    monkeypatch.setattr(facilities, "_is_admin", lambda _request: True)
    monkeypatch.setattr(facilities, "_delete_config", lambda _db, key: removidos.append(key))
    monkeypatch.setattr(facilities, "DEFAULT_TOKEN_PATH", str(token_path))
    monkeypatch.setattr(facilities, "DEFAULT_OAUTH_CLIENT_PATH", str(oauth_client_path))

    response = facilities.facilities_oauth_desconectar(
        request=_request_admin("/facilities/oauth/desconectar"),
        db=db,
    )

    assert response.status_code == 303
    assert response.headers["location"].startswith("/facilities?success=")
    assert not token_path.exists()
    assert oauth_client_path.exists()
    assert facilities.GOOGLE_TOKEN_DB_KEY in removidos
    assert facilities.GOOGLE_OAUTH_STATE_DB_KEY in removidos
    assert facilities.GOOGLE_OAUTH_CODE_VERIFIER_DB_KEY in removidos
    assert facilities.GOOGLE_OAUTH_CLIENT_DB_KEY not in removidos
    assert db.commits == 1
    oauth_client_path.unlink()
