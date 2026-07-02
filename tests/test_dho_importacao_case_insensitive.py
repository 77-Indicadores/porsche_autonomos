from app.routers.dho import (
    _normalizar_valor_enumerado,
    SEXOS,
    STATUS_VAGA,
    TIPOS_RECRUTAMENTO,
    TIPOS_VAGA,
)


def test_normaliza_variacoes_de_caixa_e_acentos():
    assert _normalizar_valor_enumerado("substituição", TIPOS_VAGA) == "Substituição"
    assert _normalizar_valor_enumerado("feminino", SEXOS) == "Feminino"
    assert _normalizar_valor_enumerado("concluida", STATUS_VAGA) == "Concluída"
    assert _normalizar_valor_enumerado("INTERNO", TIPOS_RECRUTAMENTO) == "Interno"


def test_mantem_fallback_para_valor_invalido():
    assert _normalizar_valor_enumerado("CLT", TIPOS_VAGA) is None
