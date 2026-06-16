from fastapi import APIRouter, Depends, Form, Request
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import DimCarro
from app.template_config import templates
from app.utils import flash_from_request, redirect_with_message

router = APIRouter(tags=["carros"])


@router.get("/carros")
def carros(request: Request, q: str = "", db: Session = Depends(get_db)):
    query = db.query(DimCarro)

    if q:
        like = f"%{q}%"
        query = query.filter(
            (DimCarro.numero_carro.like(like)) |
            (DimCarro.modelo.like(like)) |
            (DimCarro.categoria_padrao.like(like)) |
            (DimCarro.status_carro.like(like))
        )

    items = query.order_by(DimCarro.numero_carro).all()

    return templates.TemplateResponse(
        "cadastros/carros.html",
        {
            "request": request,
            "items": items,
            "q": q,
            **flash_from_request(request),
        },
    )


@router.post("/carros")
def salvar_carro(
    id_carro: str = Form(""),
    numero_carro: str = Form(...),
    modelo: str = Form(""),
    categoria_padrao: str = Form(""),
    chassi: str = Form(""),
    status_carro: str = Form("Ativo"),
    observacoes: str = Form(""),
    db: Session = Depends(get_db),
):
    if id_carro:
        carro = db.get(DimCarro, int(id_carro))

        if not carro:
            return redirect_with_message("/carros", error="Carro não encontrado.")
    else:
        carro = DimCarro()
        db.add(carro)

    carro.numero_carro = numero_carro
    carro.modelo = modelo
    carro.categoria_padrao = categoria_padrao
    carro.chassi = chassi
    carro.status_carro = status_carro
    carro.observacoes = observacoes

    db.commit()

    return redirect_with_message("/carros", success="Carro salvo com sucesso.")
