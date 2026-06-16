from fastapi.templating import Jinja2Templates

from app.utils import active_link, format_date, format_money


templates = Jinja2Templates(directory="app/templates")
templates.env.filters["date_br"] = format_date
templates.env.filters["money_br"] = format_money
templates.env.globals["active_link"] = active_link
