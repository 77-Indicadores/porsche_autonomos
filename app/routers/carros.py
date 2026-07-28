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
            (DimCarro.chassi.like(like)) |
            (DimCarro.modelo.like(like)) |
            (DimCarro.status_carro.like(like))
        )

    items = query.order_by(DimCarro.chassi).all()

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
    request: Request,
    id_carro: str = Form(""),
    current_id_carro: str = "",
    chassi: str = Form(...),
    modelo: str = Form(""),
    status_carro: str = Form("Ativo"),
    observacoes: str = Form(""),
    db: Session = Depends(get_db),
):
    current_id_carro = (current_id_carro or request.query_params.get("current_id_carro", "")).strip()
    carro_id_raw = (current_id_carro or id_carro or "").strip()
    if carro_id_raw:
        try:
            carro = db.get(DimCarro, int(carro_id_raw))
        except ValueError:
            return redirect_with_message("/carros", error="ID de carro invalido.")

        if not carro:
            return redirect_with_message("/carros", error="Carro não encontrado.")
    else:
        carro = DimCarro()
        db.add(carro)

    carro.modelo = modelo
    carro.chassi = chassi
    carro.status_carro = status_carro
    carro.observacoes = observacoes

    db.commit()

    return redirect_with_message("/carros", success="Carro salvo com sucesso.")


@router.post("/carros/{id_carro}/inativar")
def inativar_carro(id_carro: int, db: Session = Depends(get_db)):
    carro = db.get(DimCarro, id_carro)
    if not carro:
        return redirect_with_message("/carros", error="Carro não encontrado.")
    carro.status_carro = "Inativo"
    db.commit()
    return redirect_with_message("/carros", success="Carro inativado com sucesso.")

