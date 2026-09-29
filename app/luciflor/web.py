import secrets
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from .auth import current_user
from .models import OrderStatus

BASE_DIR = Path(__file__).parent
templates = Jinja2Templates(directory=BASE_DIR / "templates")


def csrf_token(request: Request) -> str:
    token = request.session.get("csrf")
    if not token:
        token = secrets.token_urlsafe(32)
        request.session["csrf"] = token
    return token


async def verify_csrf(request: Request) -> None:
    """Dependency for every POST form: the hidden csrf field must match the session."""
    form = await request.form()
    sent = form.get("csrf", "")
    expected = request.session.get("csrf", "")
    if not expected or not secrets.compare_digest(str(sent), expected):
        raise HTTPException(400, "Formular expirat. Reîncărcați pagina și încercați din nou.")


def flash(request: Request, message: str, kind: str = "success") -> None:
    request.session.setdefault("flash", []).append({"message": message, "kind": kind})


def render(request: Request, template: str, status_code: int = 200, **context) -> HTMLResponse:
    context.update(
        user=current_user(request),
        csrf=csrf_token(request),
        messages=request.session.pop("flash", []),
        statuses=list(OrderStatus),
        path=request.url.path,
    )
    return templates.TemplateResponse(request, template, context, status_code=status_code)


def form_bool(value: str | None) -> bool | None:
    if value in ("da", "true", "on", "1"):
        return True
    if value in ("nu", "false", "0"):
        return False
    return None


def clean(value: str | None) -> str:
    return (value or "").strip()


LOCAL_TZ = ZoneInfo("Europe/Bucharest")


def fmt_dt(value) -> str:
    return value.astimezone(LOCAL_TZ).strftime("%d.%m.%Y %H:%M") if value else ""


templates.env.filters["dt"] = fmt_dt
