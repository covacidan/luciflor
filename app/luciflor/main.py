import logging
from contextlib import asynccontextmanager
from urllib.parse import quote

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException
from starlette.middleware.sessions import SessionMiddleware

from . import routes_admin, routes_public
from .auth import LoginRequired
from .config import settings
from .db import init_db
from .web import BASE_DIR, render

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title="Luciflor", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.session_secret,
    session_cookie="luciflor_session",
    same_site="lax",
    https_only=settings.session_https_only,
    max_age=12 * 3600,
)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
app.include_router(routes_public.router)
app.include_router(routes_admin.router)


@app.exception_handler(LoginRequired)
async def login_required_handler(request: Request, exc: LoginRequired):
    target = request.url.path
    if request.url.query:
        target += "?" + request.url.query
    if request.method != "GET":
        target = "/"
    return RedirectResponse(f"/login?next={quote(target)}", status_code=303)


@app.exception_handler(HTTPException)
async def http_error_handler(request: Request, exc: HTTPException):
    titles = {403: "Acces interzis", 404: "Pagină inexistentă", 405: "Operație nepermisă"}
    message = str(exc.detail)
    if exc.status_code in (404, 405):
        message = "Pagina solicitată nu există."
    return render(request, "error.html", status_code=exc.status_code,
                  title=titles.get(exc.status_code, "Eroare"), message=message)
