from starlette.requests import Request
from sqlalchemy.exc import IntegrityError

from app.models import DimAutonomo, DimPiloto
from app.routers.cadastros import desligar_autonomo, desligar_piloto
from app.routers.usuarios import create_user


def _admin_request() -> Request:
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/",
        "headers": [],
        "state": {"current_user": {"perfil": "admin"}},
    }
    return Request(scope)


class _QueryStub:
    def filter(self, *args, **kwargs):
        return self

    def first(self):
        return None


class _DbCommitIntegrityStub:
    def query(self, *args, **kwargs):
        return _QueryStub()

    def add(self, *args, **kwargs):
        return None

    def commit(self):
        raise IntegrityError("unique", params={}, orig=None)

    def rollback(self):
        return None


class _DbGetCommitStub:
    def __init__(self, obj):
        self.obj = obj

    def get(self, *args, **kwargs):
        return self.obj

    def commit(self):
        return None


def test_create_user_handles_integrity_error():
    response = create_user(
        request=_admin_request(),
        nome="Admin",
        email="admin@local",
        senha="Senha123!",
        perfil="admin",
        db=_DbCommitIntegrityStub(),
    )
    assert response.status_code == 400


def test_desligar_piloto_uses_request_param():
    piloto = DimPiloto(nome_piloto="Piloto Teste", status_piloto="Ativo")
    db = _DbGetCommitStub(piloto)
    desligar_piloto(id_piloto=1, data_desligamento="2026-05-01", motivo_desligamento="Fim de contrato", db=db)
    assert piloto.motivo_desligamento == "Fim de contrato"


def test_desligar_autonomo_uses_request_param():
    autonomo = DimAutonomo(nome_autonomo="Auto Teste", tipo_autonomo="Mecanico", status_autonomo="Ativo")
    db = _DbGetCommitStub(autonomo)
    desligar_autonomo(id_autonomo=1, data_saida="2026-05-01", motivo_saida="Fim de contrato", db=db)
    assert autonomo.motivo_saida == "Fim de contrato"
