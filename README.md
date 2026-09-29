# Luciflor

Order management website for Luciflor: work in progress grouped by *tarla*, order search,
a new-order workflow, and an admin area. Runs as a Docker Compose stack:

| Service    | Image                            | Role                                        |
|------------|----------------------------------|---------------------------------------------|
| `web`      | built from `./app` (FastAPI)     | The website (server-rendered, mobile-first) |
| `keycloak` | `quay.io/keycloak/keycloak:26.3` | Login, users, roles                         |
| `postgres` | `postgres:16-alpine`             | Two databases: `luciflor` and `keycloak`    |

## Quick start

```bash
cp .env.example .env        # then replace every change-me value (openssl rand -hex 32)
docker compose up -d --build
```

- Website: http://localhost:8211 — log in with **admin / admin** (change it from *Administrare → Utilizatori*).
- Keycloak console: http://localhost:8210 — master-realm admin from `KEYCLOAK_ADMIN_USER` / `KEYCLOAK_ADMIN_PASSWORD`.

First start takes ~1 minute while Keycloak builds and imports the realm; `web` waits for it to be healthy.

## Pages

**Website** (any logged-in user)
- `/lucrari` — *Lucrări în execuție*: orders with status *Nouă* or *În execuție*, grouped by tarla (orders without a tarla are listed last).
- `/cauta` — *Caută comenzi*: search by client name (case- and diacritics-insensitive, `stefan` finds `Ștefan`) or by phone number (any formatting).
- `/comanda-noua` — *Comandă nouă*, step 1: client name, phone, address, invoice required (da/nu), invoice paid (da/nu). The order is saved with status *Nouă* and `workflow_step = 1`; later steps will continue from there.

**Administrare** (`/admin`, users with the `admin` realm role)
- *Utilizatori* — create / edit / delete website users (username, full name, password, admin flag, enabled). Users live in Keycloak; the app manages them through the Keycloak Admin API using the `luciflor-web` client's service account.
- *Angajați* — CRUD for employees (name, phone, job title, active, notes).
- *Comenzi* — list/filter orders; edit client name and address, plus tarla and status.
- *Tarlale* — create any number of tarlale. Deleting one keeps its orders (they become "fără tarla").

## Configuration

| File | Purpose |
|------|---------|
| `.env` | All secrets, ports and public URLs (template: `.env.example`) |
| `config/keycloak/luciflor-realm.json` | Realm `luciflor`: `admin` role, `luciflor-web` client, admin user, service-account permissions. Imported only on first start; values like `${APP_PUBLIC_URL}` come from the environment. |
| `config/postgres/init-databases.sh` | Creates the Keycloak database/user and the `unaccent` extension on first start of an empty volume. |

**Two URLs for Keycloak.** The browser uses `KEYCLOAK_PUBLIC_URL`; the web container talks to Keycloak directly at `http://keycloak:8210`. Tokens are always issued with the public URL, and the app verifies that issuer.

**Deploying on a server.** Put a TLS reverse proxy (Caddy, Traefik, nginx) in front of both `web` and `keycloak`, then in `.env` set `APP_PUBLIC_URL` and `KEYCLOAK_PUBLIC_URL` to the https URLs, `SESSION_HTTPS_ONLY=true` and `KC_SSL_REQUIRED=all`. Because the realm is only imported once, if you change `APP_PUBLIC_URL` after the first start, update the client's redirect URIs in the Keycloak console (or run `docker compose down -v` on a fresh install to re-import).

## Development without Docker

```bash
cd app
python -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt
export DATABASE_URL=postgresql+psycopg://luciflor:PASS@localhost:5432/luciflor \
       KEYCLOAK_PUBLIC_URL=http://localhost:8210 KEYCLOAK_CLIENT_SECRET=... SESSION_SECRET=dev
uvicorn luciflor.main:app --reload
```

Tables are created at startup (`create_all`). Before the schema starts changing in production, switch to Alembic migrations.

## Layout

```
docker-compose.yml
.env.example
config/
  keycloak/luciflor-realm.json
  postgres/init-databases.sh
app/
  Dockerfile, requirements.txt
  luciflor/
    main.py            app, sessions, error handling
    auth.py            OIDC login (code + PKCE), guards
    keycloak_admin.py  user management via Keycloak Admin API
    models.py          Tarla, Employee, Order
    routes_public.py   website pages
    routes_admin.py    admin pages
    templates/, static/
```
