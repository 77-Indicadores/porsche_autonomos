from starlette.requests import Request

from app.routers import composicao_padrao


class _MappingsVazio:
    def mappings(self):
        return self

    def all(self):
        return []


class _DbVazio:
    def execute(self, *_args, **_kwargs):
        return _MappingsVazio()


def test_listagem_vazia_nao_expande_equipes_alocadas(monkeypatch):
    contexto_renderizado = {}

    def renderizar(_template, contexto):
        contexto_renderizado.update(contexto)
        return contexto

    monkeypatch.setattr(composicao_padrao, "options", lambda _db: {})
    monkeypatch.setattr(composicao_padrao, "flash_from_request", lambda _request: {})
    monkeypatch.setattr(composicao_padrao.templates, "TemplateResponse", renderizar)

    request = Request({"type": "http", "method": "GET", "path": "/composicao-padrao", "headers": []})
    composicao_padrao.index(request=request, db=_DbVazio())

    assert contexto_renderizado["items"] == []
    assert contexto_renderizado["total_qtd"] == 0
    assert contexto_renderizado["total_custo"] == 0
