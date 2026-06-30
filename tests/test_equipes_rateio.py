from types import SimpleNamespace

from app.routers.equipes import calcular_rateios_equipe_atual


def _fato(id_fato, id_autonomo, id_carro, valor, id_prova=10):
    return SimpleNamespace(
        id_fato=id_fato,
        id_etapa=20,
        id_prova=id_prova,
        id_autonomo=id_autonomo,
        id_piloto=id_carro,
        id_carro=id_carro,
        valor_fechado_etapa=valor,
        dias_trabalhados=5,
    )


def test_rateia_pacote_da_pessoa_entre_dois_carros():
    fatos = [
        _fato(1, id_autonomo=100, id_carro=7, valor=3000),
        _fato(2, id_autonomo=100, id_carro=8, valor=3000),
        _fato(3, id_autonomo=200, id_carro=7, valor=2500),
    ]

    rateios = calcular_rateios_equipe_atual(fatos)

    assert rateios[1]["divisor"] == 2
    assert rateios[1]["valor_no_carro"] == 1500
    assert rateios[2]["valor_no_carro"] == 1500
    assert rateios[3]["divisor"] == 1
    assert rateios[3]["valor_no_carro"] == 2500


def test_nao_rateia_entre_categorias_diferentes():
    fatos = [
        _fato(1, id_autonomo=100, id_carro=7, valor=3000, id_prova=10),
        _fato(2, id_autonomo=100, id_carro=8, valor=3000, id_prova=11),
    ]

    rateios = calcular_rateios_equipe_atual(fatos)

    assert rateios[1]["divisor"] == 1
    assert rateios[1]["valor_no_carro"] == 3000
    assert rateios[2]["divisor"] == 1
    assert rateios[2]["valor_no_carro"] == 3000
