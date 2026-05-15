from app.models import FatoPilotoAutonomoProva
from app.routers.alocacoes import avaliar


class _DbStub:
    def __init__(self, fato):
        self._fato = fato

    def get(self, *args, **kwargs):
        return self._fato

    def commit(self):
        return None


def test_avaliar_rejeita_nota_invalida_sem_500():
    fato = FatoPilotoAutonomoProva(
        id_piloto=1,
        id_autonomo=1,
        id_etapa=1,
        id_prova=1,
    )
    db = _DbStub(fato)
    response = avaliar(
        id_fato=1,
        nota_tecnica="abc",
        nota_pontualidade="8",
        nota_comunicacao="8",
        nota_relacionamento="8",
        nota_geral="",
        comentario_avaliacao="",
        data_avaliacao="2026-05-15",
        db=db,
    )
    assert response.status_code == 303
