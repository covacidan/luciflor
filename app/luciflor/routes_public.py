from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, joinedload

from . import auth
from .db import get_db
from .models import ACTIVE_STATUSES, Order, OrderStatus, Parcela, natural_key, phone_digits
from .web import clean, flash, form_bool, render, verify_csrf

router = APIRouter()

# Eager-load the figura/parcela of each order (used for grouping and display).
WITH_LOCATION = joinedload(Order.parcela).joinedload(Parcela.figura)


def order_search_conditions(q: str) -> list:
    """Match orders by client name (case/diacritics-insensitive) or by phone digits."""
    pattern = "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
    conditions = [
        func.unaccent(func.lower(Order.client_name)).like(func.unaccent(func.lower(pattern)), escape="\\")
    ]
    digits = phone_digits(q)
    if len(digits) >= 3:
        conditions.append(Order.client_phone_digits.contains(digits))
    return conditions


# ---------------------------------------------------------------- auth ----

@router.get("/login")
def login(request: Request, next: str = "/"):
    return RedirectResponse(auth.build_login_url(request, next), status_code=303)


@router.get("/auth/callback")
def auth_callback(request: Request, code: str = "", state: str = "", error: str = ""):
    if error or not code:
        return RedirectResponse("/login", status_code=303)
    next_url = auth.complete_login(request, code, state)
    return RedirectResponse(next_url, status_code=303)


@router.get("/logout")
def logout(request: Request):
    return RedirectResponse(auth.logout_url(request), status_code=303)


# --------------------------------------------------------------- pages ----

@router.get("/")
def home():
    return RedirectResponse("/lucrari", status_code=303)


@router.get("/lucrari")
def lucrari(request: Request, db: Session = Depends(get_db), user=Depends(auth.require_user)):
    orders = db.scalars(
        select(Order)
        .options(WITH_LOCATION)
        .where(Order.status.in_(ACTIVE_STATUSES))
        .order_by(Order.created_at)
    ).all()

    # Group by figura, then by parcela within it; orders without a location come last.
    figuri: dict[int | None, dict] = {}
    for order in orders:
        figura = order.parcela.figura if order.parcela else None
        fgroup = figuri.setdefault(figura.id if figura else None,
                                   {"figura": figura, "parcele": {}, "total": 0})
        pgroup = fgroup["parcele"].setdefault(order.parcela_id, {"parcela": order.parcela, "orders": []})
        pgroup["orders"].append(order)
        fgroup["total"] += 1

    for fgroup in figuri.values():
        fgroup["parcele"] = sorted(fgroup["parcele"].values(), key=lambda g: natural_key(g["parcela"].name if g["parcela"] else ""))
        for pgroup in fgroup["parcele"]:
            pgroup["orders"].sort(key=lambda o: (natural_key(o.loc), o.created_at))
    ordered = sorted(
        figuri.values(),
        key=lambda g: (g["figura"] is None, natural_key(g["figura"].name if g["figura"] else "")),
    )
    counts = {s: sum(1 for o in orders if o.status == s) for s in ACTIVE_STATUSES}
    return render(request, "lucrari.html", groups=ordered, total=len(orders), counts=counts)


@router.get("/cauta")
def cauta(request: Request, q: str = "", db: Session = Depends(get_db), user=Depends(auth.require_user)):
    q = q.strip()
    results = []
    if len(q) >= 2:
        conditions = order_search_conditions(q)
        results = db.scalars(
            select(Order)
            .options(WITH_LOCATION)
            .where(or_(*conditions))
            .order_by(Order.created_at.desc())
            .limit(200)
        ).all()
    return render(request, "cauta.html", q=q, results=results, searched=len(q) >= 2)


@router.get("/comanda-noua")
def comanda_noua(request: Request, user=Depends(auth.require_user)):
    return render(request, "comanda_noua.html", form={}, errors={}, step=1)


@router.post("/comanda-noua", dependencies=[Depends(verify_csrf)])
async def comanda_noua_submit(request: Request, db: Session = Depends(get_db), user=Depends(auth.require_user)):
    data = await request.form()
    form = {k: clean(data.get(k)) for k in ("client_name", "client_phone", "client_address", "invoice_required", "invoice_paid")}
    errors = {}
    if not form["client_name"]:
        errors["client_name"] = "Numele este obligatoriu."
    if not form["client_phone"]:
        errors["client_phone"] = "Telefonul este obligatoriu."
    elif len(phone_digits(form["client_phone"])) < 6:
        errors["client_phone"] = "Număr de telefon invalid."
    if not form["client_address"]:
        errors["client_address"] = "Adresa este obligatorie."
    invoice_required = form_bool(form["invoice_required"])
    invoice_paid = form_bool(form["invoice_paid"])
    if invoice_required is None:
        errors["invoice_required"] = "Alegeți Da sau Nu."
    if invoice_paid is None:
        errors["invoice_paid"] = "Alegeți Da sau Nu."

    if errors:
        return render(request, "comanda_noua.html", form=form, errors=errors, step=1, status_code=422)

    order = Order(
        client_name=form["client_name"],
        client_phone=form["client_phone"],
        client_phone_digits=phone_digits(form["client_phone"]),
        client_address=form["client_address"],
        invoice_required=invoice_required,
        invoice_paid=invoice_paid,
        status=OrderStatus.noua,
        workflow_step=1,
        created_by=user["username"],
    )
    db.add(order)
    db.commit()
    flash(request, f"Comanda {order.number} a fost înregistrată.")
    return RedirectResponse(f"/comenzi/{order.id}", status_code=303)


@router.get("/comenzi/{order_id}")
def comanda(order_id: int, request: Request, db: Session = Depends(get_db), user=Depends(auth.require_user)):
    order = db.get(Order, order_id)
    if not order:
        return render(request, "error.html", status_code=404, title="Comandă inexistentă",
                      message="Comanda căutată nu există.")
    return render(request, "comanda.html", order=order)


@router.get("/health")
def health():
    return {"status": "ok"}

