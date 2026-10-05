from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from . import auth, keycloak_admin as kc
from .db import get_db
from .models import CODE_MAX_LEN, Employee, Figura, Order, OrderStatus, Parcela, natural_key, valid_code
from .routes_public import WITH_LOCATION, order_search_conditions
from .web import clean, flash, render, verify_csrf

router = APIRouter(prefix="/admin", dependencies=[Depends(auth.require_admin)])
csrf = [Depends(verify_csrf)]


def _not_found(request: Request, what: str):
    return render(request, "error.html", status_code=404, title=f"{what} inexistent(ă)",
                  message="Înregistrarea nu a fost găsită.")


@router.get("")
def dashboard(request: Request, db: Session = Depends(get_db)):
    stats = {
        "comenzi_active": db.scalar(select(func.count()).select_from(Order).where(
            Order.status.in_([OrderStatus.noua, OrderStatus.in_executie]))),
        "comenzi": db.scalar(select(func.count()).select_from(Order)),
        "angajati": db.scalar(select(func.count()).select_from(Employee).where(Employee.active.is_(True))),
        "figuri": db.scalar(select(func.count()).select_from(Figura)),
        "parcele": db.scalar(select(func.count()).select_from(Parcela)),
    }
    return render(request, "admin/dashboard.html", stats=stats)


# ---------------------------------------------------------------- users ----

@router.get("/utilizatori")
def users_list(request: Request):
    try:
        users = kc.list_users()
    except kc.KeycloakError as exc:
        flash(request, str(exc), "error")
        users = []
    return render(request, "admin/users.html", users=users)


@router.get("/utilizatori/nou")
def user_new(request: Request):
    return render(request, "admin/user_form.html", item=None, form={}, errors={})


@router.post("/utilizatori/nou", dependencies=csrf)
async def user_create(request: Request):
    data = await request.form()
    form = {"username": clean(data.get("username")).lower(), "full_name": clean(data.get("full_name")),
            "is_admin": data.get("is_admin") == "on"}
    password, password2 = data.get("password", ""), data.get("password2", "")
    errors = {}
    if len(form["username"]) < 3:
        errors["username"] = "Minim 3 caractere."
    if len(password) < 4:
        errors["password"] = "Parola trebuie să aibă minim 4 caractere."
    elif password != password2:
        errors["password2"] = "Parolele nu coincid."
    if not errors:
        try:
            kc.create_user(form["username"], form["full_name"], password, form["is_admin"])
            flash(request, f"Utilizatorul {form['username']} a fost creat.")
            return RedirectResponse("/admin/utilizatori", status_code=303)
        except kc.KeycloakError as exc:
            errors["username"] = str(exc)
    return render(request, "admin/user_form.html", item=None, form=form, errors=errors, status_code=422)


@router.get("/utilizatori/{user_id}")
def user_edit(user_id: str, request: Request):
    try:
        item = kc.get_user(user_id)
    except kc.KeycloakError:
        return _not_found(request, "Utilizator")
    form = {"username": item["username"], "full_name": item.get("firstName") or "",
            "is_admin": item["is_admin"], "enabled": item.get("enabled", True)}
    return render(request, "admin/user_form.html", item=item, form=form, errors={})


@router.post("/utilizatori/{user_id}", dependencies=csrf)
async def user_update(user_id: str, request: Request, me=Depends(auth.require_admin)):
    try:
        item = kc.get_user(user_id)
    except kc.KeycloakError:
        return _not_found(request, "Utilizator")
    data = await request.form()
    form = {"username": item["username"], "full_name": clean(data.get("full_name")),
            "is_admin": data.get("is_admin") == "on", "enabled": data.get("enabled") == "on"}
    password, password2 = data.get("password", ""), data.get("password2", "")
    errors = {}
    if password and len(password) < 4:
        errors["password"] = "Parola trebuie să aibă minim 4 caractere."
    elif password != password2:
        errors["password2"] = "Parolele nu coincid."
    if user_id == me["sub"] and (not form["is_admin"] or not form["enabled"]):
        errors["is_admin"] = "Nu vă puteți retrage propriile drepturi de administrator sau dezactiva propriul cont."
    if not errors:
        try:
            kc.update_user(user_id, form["full_name"], form["enabled"], password or None, form["is_admin"])
            flash(request, f"Utilizatorul {item['username']} a fost actualizat.")
            return RedirectResponse("/admin/utilizatori", status_code=303)
        except kc.KeycloakError as exc:
            errors["full_name"] = str(exc)
    return render(request, "admin/user_form.html", item=item, form=form, errors=errors, status_code=422)


@router.post("/utilizatori/{user_id}/sterge", dependencies=csrf)
def user_delete(user_id: str, request: Request, me=Depends(auth.require_admin)):
    if user_id == me["sub"]:
        flash(request, "Nu vă puteți șterge propriul cont.", "error")
    else:
        try:
            kc.delete_user(user_id)
            flash(request, "Utilizatorul a fost șters.")
        except kc.KeycloakError as exc:
            flash(request, str(exc), "error")
    return RedirectResponse("/admin/utilizatori", status_code=303)


# ------------------------------------------------------------ employees ----

EMPLOYEE_FIELDS = ("name", "phone", "job_title", "notes")


@router.get("/angajati")
def employees_list(request: Request, db: Session = Depends(get_db)):
    items = db.scalars(select(Employee).order_by(Employee.active.desc(), Employee.name)).all()
    return render(request, "admin/employees.html", items=items)


@router.get("/angajati/nou")
def employee_new(request: Request):
    return render(request, "admin/employee_form.html", item=None, form={"active": True}, errors={})


@router.get("/angajati/{item_id}")
def employee_edit(item_id: int, request: Request, db: Session = Depends(get_db)):
    item = db.get(Employee, item_id)
    if not item:
        return _not_found(request, "Angajat")
    form = {f: getattr(item, f) or "" for f in EMPLOYEE_FIELDS} | {"active": item.active}
    return render(request, "admin/employee_form.html", item=item, form=form, errors={})


# Decorators apply bottom-up: register "/nou" first so it is not parsed as an item_id.
@router.post("/angajati/{item_id}", dependencies=csrf)
@router.post("/angajati/nou", dependencies=csrf)
async def employee_save(request: Request, item_id: int | None = None, db: Session = Depends(get_db)):
    item = db.get(Employee, item_id) if item_id else Employee()
    if item is None:
        return _not_found(request, "Angajat")
    data = await request.form()
    form = {f: clean(data.get(f)) for f in EMPLOYEE_FIELDS} | {"active": data.get("active") == "on"}
    if not form["name"]:
        return render(request, "admin/employee_form.html", item=item if item_id else None, form=form,
                      errors={"name": "Numele este obligatoriu."}, status_code=422)
    for f in EMPLOYEE_FIELDS:
        setattr(item, f, form[f] or None)
    item.active = form["active"]
    db.add(item)
    db.commit()
    flash(request, f"Angajatul {item.name} a fost salvat.")
    return RedirectResponse("/admin/angajati", status_code=303)


@router.post("/angajati/{item_id}/sterge", dependencies=csrf)
def employee_delete(item_id: int, request: Request, db: Session = Depends(get_db)):
    item = db.get(Employee, item_id)
    if item:
        db.delete(item)
        db.commit()
        flash(request, f"Angajatul {item.name} a fost șters.")
    return RedirectResponse("/admin/angajati", status_code=303)


# --------------------------------------------------------------- orders ----

@router.get("/comenzi")
def orders_list(request: Request, q: str = "", status: str = "", db: Session = Depends(get_db)):
    stmt = select(Order).options(WITH_LOCATION).order_by(Order.created_at.desc()).limit(300)
    q = q.strip()
    if q:
        stmt = stmt.where(or_(*order_search_conditions(q)))
    if status in OrderStatus.__members__:
        stmt = stmt.where(Order.status == OrderStatus(status))
    items = db.scalars(stmt).all()
    return render(request, "admin/orders.html", items=items, q=q, status=status)


CODE_ERROR = f"Doar litere și cifre, fără spații (maxim {CODE_MAX_LEN} caractere)."


def _figuri_with_parcele(db: Session) -> list[Figura]:
    """All figuri with their parcele, in natural order (for the order form's parcela picker)."""
    figuri = sorted(db.scalars(select(Figura).options(selectinload(Figura.parcele))).all(),
                    key=lambda f: natural_key(f.name))
    for f in figuri:
        f.parcele.sort(key=lambda p: natural_key(p.name))
    return figuri


@router.get("/comenzi/{item_id}")
def order_edit(item_id: int, request: Request, db: Session = Depends(get_db)):
    item = db.get(Order, item_id)
    if not item:
        return _not_found(request, "Comandă")
    form = {"client_name": item.client_name, "client_address": item.client_address,
            "parcela_id": item.parcela_id, "loc": item.loc or "", "status": item.status.value}
    return render(request, "admin/order_form.html", item=item, form=form, figuri=_figuri_with_parcele(db),
                  errors={})


@router.post("/comenzi/{item_id}", dependencies=csrf)
async def order_update(item_id: int, request: Request, db: Session = Depends(get_db)):
    item = db.get(Order, item_id)
    if not item:
        return _not_found(request, "Comandă")
    data = await request.form()
    parcela_raw = clean(data.get("parcela_id"))
    form = {"client_name": clean(data.get("client_name")), "client_address": clean(data.get("client_address")),
            "parcela_id": int(parcela_raw) if parcela_raw.isdigit() else None,
            "loc": clean(data.get("loc")), "status": clean(data.get("status"))}
    errors = {}
    if not form["client_name"]:
        errors["client_name"] = "Numele este obligatoriu."
    if not form["client_address"]:
        errors["client_address"] = "Adresa este obligatorie."
    if form["status"] not in OrderStatus.__members__:
        errors["status"] = "Status invalid."
    if form["parcela_id"] and not db.get(Parcela, form["parcela_id"]):
        errors["parcela_id"] = "Parcelă inexistentă."
    if form["loc"]:
        if not form["parcela_id"]:
            errors["loc"] = "Alegeți întâi figura / parcela."
        elif not valid_code(form["loc"]):
            errors["loc"] = CODE_ERROR
    if errors:
        return render(request, "admin/order_form.html", item=item, form=form, figuri=_figuri_with_parcele(db),
                      errors=errors, status_code=422)
    item.client_name = form["client_name"]
    item.client_address = form["client_address"]
    item.parcela_id = form["parcela_id"]
    item.loc = form["loc"] or None
    item.status = OrderStatus(form["status"])
    db.commit()
    flash(request, f"Comanda {item.number} a fost actualizată.")
    return RedirectResponse("/admin/comenzi", status_code=303)


# ------------------------------------------------------- figuri / parcele ----

def _order_counts_by_parcela(db: Session) -> dict[int, int]:
    return dict(db.execute(
        select(Order.parcela_id, func.count(Order.id)).where(Order.parcela_id.is_not(None)).group_by(Order.parcela_id)
    ).all())


def _clear_location(db: Session, parcela_ids) -> None:
    """Orders of a parcela being deleted lose their whole location (parcela and loc)."""
    db.execute(update(Order).where(Order.parcela_id.in_(parcela_ids)).values(parcela_id=None, loc=None))


def _code_form(data) -> tuple[dict, dict]:
    form = {"name": clean(data.get("name")), "description": clean(data.get("description"))}
    errors = {}
    if not form["name"]:
        errors["name"] = "Codul este obligatoriu."
    elif not valid_code(form["name"]):
        errors["name"] = CODE_ERROR
    return form, errors


@router.get("/figuri")
def figuri_list(request: Request, db: Session = Depends(get_db)):
    counts = _order_counts_by_parcela(db)
    rows = [(f, sum(counts.get(p.id, 0) for p in f.parcele)) for f in _figuri_with_parcele(db)]
    return render(request, "admin/figuri.html", rows=rows, counts=counts)


@router.get("/figuri/nou")
def figura_new(request: Request):
    return render(request, "admin/figura_form.html", item=None, form={}, errors={}, counts={})


@router.get("/figuri/{item_id}")
def figura_edit(item_id: int, request: Request, db: Session = Depends(get_db)):
    item = db.get(Figura, item_id)
    if not item:
        return _not_found(request, "Figura")
    item.parcele.sort(key=lambda p: natural_key(p.name))
    form = {"name": item.name, "description": item.description or ""}
    return render(request, "admin/figura_form.html", item=item, form=form, errors={},
                  counts=_order_counts_by_parcela(db))


# Decorators apply bottom-up: register "/nou" first so it is not parsed as an item_id.
@router.post("/figuri/{item_id}", dependencies=csrf)
@router.post("/figuri/nou", dependencies=csrf)
async def figura_save(request: Request, item_id: int | None = None, db: Session = Depends(get_db)):
    item = db.get(Figura, item_id) if item_id else Figura()
    if item is None:
        return _not_found(request, "Figura")
    form, errors = _code_form(await request.form())
    if not errors:
        item.name = form["name"]
        item.description = form["description"] or None
        db.add(item)
        try:
            db.commit()
            flash(request, f"Figura {item.name} a fost salvată.")
            # A new figura goes straight to its page so parcele can be added.
            return RedirectResponse(f"/admin/figuri/{item.id}" if not item_id else "/admin/figuri", status_code=303)
        except IntegrityError:
            db.rollback()
            errors["name"] = "Există deja o figură cu acest cod."
    if item_id:
        db.refresh(item)
    return render(request, "admin/figura_form.html", item=item if item_id else None, form=form, errors=errors,
                  counts=_order_counts_by_parcela(db), status_code=422)


@router.post("/figuri/{item_id}/sterge", dependencies=csrf)
def figura_delete(item_id: int, request: Request, db: Session = Depends(get_db)):
    item = db.get(Figura, item_id)
    if item:
        _clear_location(db, select(Parcela.id).where(Parcela.figura_id == item.id))
        db.delete(item)
        db.commit()
        flash(request, f"Figura {item.name} și parcelele ei au fost șterse. Comenzile lor au rămas fără locație.")
    return RedirectResponse("/admin/figuri", status_code=303)


@router.get("/figuri/{figura_id}/parcele/nou")
def parcela_new(figura_id: int, request: Request, db: Session = Depends(get_db)):
    figura = db.get(Figura, figura_id)
    if not figura:
        return _not_found(request, "Figura")
    return render(request, "admin/parcela_form.html", figura=figura, item=None, form={}, errors={})


@router.get("/figuri/{figura_id}/parcele/{item_id}")
def parcela_edit(figura_id: int, item_id: int, request: Request, db: Session = Depends(get_db)):
    item = db.get(Parcela, item_id)
    if not item or item.figura_id != figura_id:
        return _not_found(request, "Parcela")
    form = {"name": item.name, "description": item.description or ""}
    return render(request, "admin/parcela_form.html", figura=item.figura, item=item, form=form, errors={})


@router.post("/figuri/{figura_id}/parcele/{item_id}", dependencies=csrf)
@router.post("/figuri/{figura_id}/parcele/nou", dependencies=csrf)
async def parcela_save(figura_id: int, request: Request, item_id: int | None = None, db: Session = Depends(get_db)):
    figura = db.get(Figura, figura_id)
    item = db.get(Parcela, item_id) if item_id else Parcela(figura_id=figura_id)
    if not figura or item is None or item.figura_id != figura_id:
        return _not_found(request, "Parcela")
    form, errors = _code_form(await request.form())
    if not errors:
        item.name = form["name"]
        item.description = form["description"] or None
        db.add(item)
        try:
            db.commit()
            flash(request, f"Parcela {item.name} din figura {figura.name} a fost salvată.")
            return RedirectResponse(f"/admin/figuri/{figura_id}", status_code=303)
        except IntegrityError:
            db.rollback()
            errors["name"] = f"Figura {figura.name} are deja o parcelă cu acest cod."
    return render(request, "admin/parcela_form.html", figura=figura, item=item if item_id else None, form=form,
                  errors=errors, status_code=422)


@router.post("/figuri/{figura_id}/parcele/{item_id}/sterge", dependencies=csrf)
def parcela_delete(figura_id: int, item_id: int, request: Request, db: Session = Depends(get_db)):
    item = db.get(Parcela, item_id)
    if item and item.figura_id == figura_id:
        _clear_location(db, select(Parcela.id).where(Parcela.id == item.id))
        db.delete(item)
        db.commit()
        flash(request, f"Parcela {item.name} a fost ștearsă. Comenzile ei au rămas fără locație.")
    return RedirectResponse(f"/admin/figuri/{figura_id}", status_code=303)
