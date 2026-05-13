from datetime import date
from pathlib import Path
import sys

vendor = Path(__file__).resolve().parent.parent / ".vendor"
if vendor.exists():
    sys.path.insert(0, str(vendor))

from app.database import Base, SessionLocal, engine
from app.models import DimAutonomo, DimEtapa, DimMotivoTroca, DimPiloto, DimProva, DimStatusPagamento, DimTipoProva, FatoPilotoAutonomoProva


def run():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        pilotos = [
            DimPiloto(nome_piloto="Rafael Martins", cpf="111.111.111-11", telefone="(11) 90000-1001", email="rafael@cup.local", data_inclusao=date(2026, 1, 10)),
            DimPiloto(nome_piloto="Bruno Costa", cpf="222.222.222-22", telefone="(11) 90000-1002", email="bruno@cup.local", data_inclusao=date(2026, 1, 12)),
            DimPiloto(nome_piloto="Lucas Almeida", cpf="333.333.333-33", telefone="(11) 90000-1003", email="lucas@cup.local", data_inclusao=date(2026, 1, 15)),
            DimPiloto(nome_piloto="Henrique Dias", cpf="444.444.444-44", telefone="(11) 90000-1004", email="henrique@cup.local", data_inclusao=date(2026, 1, 20)),
        ]
        autonomos = [
            DimAutonomo(nome_autonomo="Joao Silva", cpf="555.555.555-55", telefone="(11) 98888-1001", email="joao@cup.local", tipo_autonomo="Mecanico", especialidade="Suspensao"),
            DimAutonomo(nome_autonomo="Carlos Lima", cpf="666.666.666-66", telefone="(11) 98888-1002", email="carlos@cup.local", tipo_autonomo="Engenheiro", especialidade="Telemetria"),
            DimAutonomo(nome_autonomo="Pedro Rocha", cpf="777.777.777-77", telefone="(11) 98888-1003", email="pedro@cup.local", tipo_autonomo="Mecanico", especialidade="Freios"),
            DimAutonomo(nome_autonomo="Marcos Freitas", cpf="888.888.888-88", telefone="(11) 98888-1004", email="marcos@cup.local", tipo_autonomo="Engenheiro", especialidade="Setup"),
            DimAutonomo(nome_autonomo="Andre Souza", cpf="999.999.999-99", telefone="(11) 98888-1005", email="andre@cup.local", tipo_autonomo="Preparador", especialidade="Motor"),
        ]
        etapas = [
            DimEtapa(temporada="2026", nome_etapa="Etapa 01 - Interlagos", local="Sao Paulo", data_inicio=date(2026, 3, 14), data_fim=date(2026, 3, 16), status_etapa="Concluida"),
            DimEtapa(temporada="2026", nome_etapa="Etapa 02 - Velocitta", local="Mogi Guacu", data_inicio=date(2026, 5, 9), data_fim=date(2026, 5, 11), status_etapa="Em andamento"),
            DimEtapa(temporada="2026", nome_etapa="Etapa 03 - Goiania", local="Goiania", data_inicio=date(2026, 7, 18), data_fim=date(2026, 7, 20), status_etapa="Planejada"),
        ]
        tipos = [
            DimTipoProva(nome_tipo_prova="Sprint"),
            DimTipoProva(nome_tipo_prova="Endurance"),
            DimTipoProva(nome_tipo_prova="Carrera Cup"),
            DimTipoProva(nome_tipo_prova="Sprint Challenge"),
            DimTipoProva(nome_tipo_prova="Outro"),
        ]
        motivos = [
            DimMotivoTroca(motivo_troca="Solicitacao do piloto"),
            DimMotivoTroca(motivo_troca="Baixa performance"),
            DimMotivoTroca(motivo_troca="Problema de relacionamento"),
            DimMotivoTroca(motivo_troca="Indisponibilidade"),
            DimMotivoTroca(motivo_troca="Troca estrategica"),
            DimMotivoTroca(motivo_troca="Encerramento de contrato"),
            DimMotivoTroca(motivo_troca="Outro"),
        ]
        pagamentos = [DimStatusPagamento(status_pagamento=s) for s in ["Pendente", "Aprovado", "Pago", "Reprovado", "Cancelado"]]
        db.add_all(pilotos + autonomos + etapas + tipos + motivos + pagamentos)
        db.flush()

        provas = [
            DimProva(id_etapa=etapas[0].id_etapa, id_tipo_prova=tipos[0].id_tipo_prova, nome_prova="Sprint Interlagos", data_prova=date(2026, 3, 15), status_prova="Concluida"),
            DimProva(id_etapa=etapas[0].id_etapa, id_tipo_prova=tipos[1].id_tipo_prova, nome_prova="Endurance Interlagos", data_prova=date(2026, 3, 16), status_prova="Concluida"),
            DimProva(id_etapa=etapas[1].id_etapa, id_tipo_prova=tipos[0].id_tipo_prova, nome_prova="Sprint Velocitta", data_prova=date(2026, 5, 10), status_prova="Em andamento"),
            DimProva(id_etapa=etapas[1].id_etapa, id_tipo_prova=tipos[1].id_tipo_prova, nome_prova="Endurance Velocitta", data_prova=date(2026, 5, 11), status_prova="Planejada"),
        ]
        db.add_all(provas)
        db.flush()

        fatos = [
            FatoPilotoAutonomoProva(id_piloto=pilotos[0].id_piloto, id_autonomo=autonomos[0].id_autonomo, id_etapa=etapas[0].id_etapa, id_prova=provas[0].id_prova, data_inicio_vinculo=date(2026, 3, 14), data_fim_vinculo=date(2026, 5, 9), status_vinculo="Substituido", foi_substituido="Sim", id_autonomo_substituto=autonomos[2].id_autonomo, data_troca=date(2026, 5, 9), id_motivo_troca=motivos[3].id_motivo_troca, justificativa_troca="Indisponibilidade para a etapa seguinte.", valor_fechado_etapa=3300, dias_trabalhados=3, status_pagamento="Pago", data_pagamento=date(2026, 3, 22), nota_tecnica=8, nota_pontualidade=9, nota_comunicacao=8, nota_relacionamento=8, nota_geral=8.25, comentario_avaliacao="Boa entrega tecnica."),
            FatoPilotoAutonomoProva(id_piloto=pilotos[0].id_piloto, id_autonomo=autonomos[2].id_autonomo, id_etapa=etapas[1].id_etapa, id_prova=provas[2].id_prova, data_inicio_vinculo=date(2026, 5, 9), status_vinculo="Ativo", valor_fechado_etapa=3600, dias_trabalhados=3, status_pagamento="Pendente", nota_tecnica=9, nota_pontualidade=9, nota_comunicacao=8, nota_relacionamento=9, nota_geral=8.75),
            FatoPilotoAutonomoProva(id_piloto=pilotos[0].id_piloto, id_autonomo=autonomos[1].id_autonomo, id_etapa=etapas[0].id_etapa, id_prova=provas[0].id_prova, data_inicio_vinculo=date(2026, 3, 14), status_vinculo="Ativo", valor_fechado_etapa=4600, dias_trabalhados=3, status_pagamento="Pago", data_pagamento=date(2026, 3, 25), nota_geral=9.4),
            FatoPilotoAutonomoProva(id_piloto=pilotos[1].id_piloto, id_autonomo=autonomos[2].id_autonomo, id_etapa=etapas[0].id_etapa, id_prova=provas[1].id_prova, data_inicio_vinculo=date(2026, 3, 15), status_vinculo="Ativo", valor_fechado_etapa=2200, dias_trabalhados=2, status_pagamento="Aprovado", nota_geral=8.1),
            FatoPilotoAutonomoProva(id_piloto=pilotos[2].id_piloto, id_autonomo=autonomos[4].id_autonomo, id_etapa=etapas[1].id_etapa, id_prova=provas[3].id_prova, data_inicio_vinculo=date(2026, 5, 9), status_vinculo="Ativo", valor_fechado_etapa=650, dias_trabalhados=1, status_pagamento="Pendente", nota_geral=7.8),
        ]
        db.add_all(fatos)
        db.commit()
        print("Seed Porsche Cup executado com sucesso.")
    finally:
        db.close()


if __name__ == "__main__":
    run()
