from collections import OrderedDict

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import text

from app.database import get_db
from app.models import DimEtapa, DimProva, FatoPilotoAutonomoProva
from app.template_config import templates

router = APIRouter(tags=["equipes"])


def fmt_money(value):
    try:
        return f"R$ {float(value or 0):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except Exception:
        return "R$ 0,00"


def fmt_qtd(value):
    try:
        v = float(value or 0)
        if v.is_integer():
            return str(int(v))
        return str(v).replace(".", ",")
    except Exception:
        return str(value or "")


def calcular_rateios_equipe_atual(fatos):
    """Rateia o pacote de quem aparece em mais de uma equipe na mesma etapa/categoria."""
    destinos_por_pessoa = {}

    for fato in fatos:
        chave_pessoa = (fato.id_etapa, fato.id_prova, fato.id_autonomo)
        chave_equipe = (fato.id_piloto, fato.id_carro)
        destinos_por_pessoa.setdefault(chave_pessoa, set()).add(chave_equipe)

    rateios = {}
    for fato in fatos:
        chave_pessoa = (fato.id_etapa, fato.id_prova, fato.id_autonomo)
        divisor = len(destinos_por_pessoa.get(chave_pessoa, set())) or 1
        valor_pacote = float(fato.valor_fechado_etapa or 0)
        dias = int(fato.dias_trabalhados or 0)
        valor_no_carro = valor_pacote / divisor

        rateios[fato.id_fato] = {
            "divisor": divisor,
            "valor_pacote": valor_pacote,
            "valor_no_carro": valor_no_carro,
            "valor_dia_no_carro": valor_no_carro / dias if dias else 0,
        }

    return rateios



def carregar_equipes_gerais(db: Session):
    try:
        rows = db.execute(
            text("""
                SELECT
                    id_equipe_geral,
                    id_etapa,
                    id_prova,
                    nome_equipe,
                    qtd_pessoas,
                    custo_total
                FROM equipe_geral
            """)
        ).mappings().all()

        mapa = {}

        for r in rows:
            chave = (r["id_etapa"], r["id_prova"])
            mapa.setdefault(chave, []).append(dict(r))

        return mapa

    except Exception as exc:
        print(f"AVISO - não consegui carregar equipe_geral para rateio: {exc}")
        return {}



@router.get("/equipes")
def equipes(
    request: Request,
    id_etapa: str = "",
    id_prova: str = "",
    estabilidade: str = "",
    db: Session = Depends(get_db),
):
    id_etapa_int = int(id_etapa) if str(id_etapa or "").strip() else None
    id_prova_int = int(id_prova) if str(id_prova or "").strip() else None

    etapas = db.query(DimEtapa).order_by(DimEtapa.nome_etapa).all()
    categorias = db.query(DimProva).order_by(DimProva.nome_prova).all()

    query = (
        db.query(FatoPilotoAutonomoProva)
        .options(
            joinedload(FatoPilotoAutonomoProva.piloto),
            joinedload(FatoPilotoAutonomoProva.autonomo),
            joinedload(FatoPilotoAutonomoProva.autonomo_substituto),
            joinedload(FatoPilotoAutonomoProva.etapa),
            joinedload(FatoPilotoAutonomoProva.prova),
            joinedload(FatoPilotoAutonomoProva.carro),
            joinedload(FatoPilotoAutonomoProva.motivo_troca),
        )
    )

    if id_etapa_int:
        query = query.filter(FatoPilotoAutonomoProva.id_etapa == id_etapa_int)

    if id_prova_int:
        query = query.filter(FatoPilotoAutonomoProva.id_prova == id_prova_int)

    fatos = query.order_by(
        FatoPilotoAutonomoProva.id_etapa,
        FatoPilotoAutonomoProva.id_prova,
        FatoPilotoAutonomoProva.id_piloto,
        FatoPilotoAutonomoProva.id_carro,
        FatoPilotoAutonomoProva.funcao_autonomo,
    ).all()

    rateios_equipe_atual = calcular_rateios_equipe_atual(fatos)

    equipes_map = OrderedDict()

    for f in fatos:
        chave = (f.id_etapa, f.id_prova, f.id_piloto, f.id_carro)

        if chave not in equipes_map:
            equipes_map[chave] = {
                "piloto": f.piloto,
                "etapa": f.etapa,
                "categoria": f.prova,
                "carro": f.carro,
                "membros": [],
                "substituicoes": [],
                "custo_equipe_atual": 0.0,
                "custo_rateio_equipe_geral": 0.0,
                "custo_total": 0.0,
                "qtd_membros": 0,
                "teve_troca": False,
                "rateios_equipe_geral": [],
            }

        equipe = equipes_map[chave]

        valor = float(f.valor_fechado_etapa or 0)
        dias = int(f.dias_trabalhados or 0)
        valor_dia = float(f.valor_dia or 0)
        rateio_atual = rateios_equipe_atual.get(
            f.id_fato,
            {
                "divisor": 1,
                "valor_pacote": valor,
                "valor_no_carro": valor,
                "valor_dia_no_carro": valor_dia,
            },
        )

        equipe["membros"].append({
            "funcao": f.funcao_autonomo or "-",
            "nome": getattr(f.autonomo, "nome_autonomo", "-"),
            "valor": valor,
            "dias": dias,
            "valor_dia": valor_dia,
            "divisor": rateio_atual["divisor"],
            "valor_no_carro": rateio_atual["valor_no_carro"],
            "valor_dia_no_carro": rateio_atual["valor_dia_no_carro"],
            "status": f.status_vinculo or "",
            "foi_substituido": (f.foi_substituido or "").lower() == "sim",
            "observacoes": f.observacoes or "",
        })

        equipe["custo_equipe_atual"] += rateio_atual["valor_no_carro"]
        equipe["custo_total"] += rateio_atual["valor_no_carro"]
        equipe["qtd_membros"] += 1

        if (f.foi_substituido or "").lower() == "sim":
            equipe["teve_troca"] = True
            equipe["substituicoes"].append({
                "funcao": f.funcao_autonomo or "-",
                "saiu": getattr(f.autonomo, "nome_autonomo", "-"),
                "entrou": getattr(f.autonomo_substituto, "nome_autonomo", "-"),
                "data": f.data_troca,
                "motivo": getattr(f.motivo_troca, "motivo_troca", "-"),
                "justificativa": f.justificativa_troca or "",
            })

    # ------------------------------------------------------------
    # Rateio da Equipe Geral
    # Regra:
    #   sem categoria (id_prova=None) → rateia para todos os carros da etapa
    #   com categoria                 → rateia apenas para os carros da etapa+categoria
    # ------------------------------------------------------------
    equipes_gerais_map = carregar_equipes_gerais(db)

    # Carros únicos por etapa (todas as categorias)
    carros_por_etapa: dict = {}
    # Carros únicos por etapa+categoria
    carros_por_etapa_categoria: dict = {}

    for equipe in equipes_map.values():
        etapa_id = getattr(equipe["etapa"], "id_etapa", None)
        prova_id = getattr(equipe["categoria"], "id_prova", None)
        carro_id = getattr(equipe["carro"], "id_carro", None)

        if etapa_id and carro_id:
            carros_por_etapa.setdefault(etapa_id, set()).add(carro_id)
        if etapa_id and prova_id and carro_id:
            carros_por_etapa_categoria.setdefault((etapa_id, prova_id), set()).add(carro_id)

    for equipe in equipes_map.values():
        etapa_id = getattr(equipe["etapa"], "id_etapa", None)
        prova_id = getattr(equipe["categoria"], "id_prova", None)

        def _aplicar_rateio(rateio, qtd_carros):
            custo_total_geral = float(rateio.get("custo_total") or 0)
            valor_rateado = custo_total_geral / qtd_carros
            equipe["rateios_equipe_geral"].append({
                "id_equipe_geral": rateio.get("id_equipe_geral"),
                "nome_equipe": rateio.get("nome_equipe") or "Equipe Geral",
                "qtd_pessoas": fmt_qtd(rateio.get("qtd_pessoas")),
                "custo_total": custo_total_geral,
                "custo_total_fmt": fmt_money(custo_total_geral),
                "qtd_carros_rateio": qtd_carros,
                "valor_rateado": valor_rateado,
                "valor_rateado_fmt": fmt_money(valor_rateado),
            })
            equipe["custo_rateio_equipe_geral"] += valor_rateado
            equipe["custo_total"] += valor_rateado

        # Equipes gerais SEM categoria → divide entre todos os carros da etapa
        qtd_etapa = len(carros_por_etapa.get(etapa_id, set())) or 1
        for rateio in equipes_gerais_map.get((etapa_id, None), []):
            _aplicar_rateio(rateio, qtd_etapa)

        # Equipes gerais COM categoria → divide entre carros daquela etapa+categoria
        qtd_ep = len(carros_por_etapa_categoria.get((etapa_id, prova_id), set())) or 1
        for rateio in equipes_gerais_map.get((etapa_id, prova_id), []):
            _aplicar_rateio(rateio, qtd_ep)

    equipes = list(equipes_map.values())

    if estabilidade == "estavel":
        equipes = [e for e in equipes if not e["teve_troca"]]
    elif estabilidade == "nao_estavel":
        equipes = [e for e in equipes if e["teve_troca"]]

    return templates.TemplateResponse(
        "equipes/index.html",
        {
            "request": request,
            "equipes": equipes,
            "etapas": etapas,
            "categorias": categorias,
            "id_etapa": id_etapa_int,
            "id_prova": id_prova_int,
            "estabilidade": estabilidade,
        },
    )
