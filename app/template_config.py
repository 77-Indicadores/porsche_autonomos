import json

from fastapi.templating import Jinja2Templates

from app.utils import active_link, empresa_curta, format_date, format_money, format_money_input


class CompatJinja2Templates(Jinja2Templates):
    def TemplateResponse(self, *args, **kwargs):
        # Compatibilidade com duas assinaturas:
        # 1) TemplateResponse("template.html", {"request": request, ...}, ...)
        # 2) TemplateResponse(request, "template.html", {...}, ...)
        if len(args) >= 2 and isinstance(args[0], str) and isinstance(args[1], dict):
            name = args[0]
            context = dict(args[1])
            request = context.get("request")
            if request is None:
                raise ValueError("Contexto sem 'request' para renderizacao de template.")

            status_code = kwargs.pop("status_code", 200)
            headers = kwargs.pop("headers", None)
            media_type = kwargs.pop("media_type", None)
            background = kwargs.pop("background", None)
            return super().TemplateResponse(
                request=request,
                name=name,
                context=context,
                status_code=status_code,
                headers=headers,
                media_type=media_type,
                background=background,
            )

        return super().TemplateResponse(*args, **kwargs)


templates = CompatJinja2Templates(directory="app/templates")
templates.env.filters["date_br"] = format_date
templates.env.filters["money_br"] = format_money
templates.env.filters["money_input"] = format_money_input
templates.env.filters["fromjson"] = lambda s: json.loads(s) if s else []
templates.env.globals["active_link"] = active_link
templates.env.filters["empresa_curta"] = empresa_curta
