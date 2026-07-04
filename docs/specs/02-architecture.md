# System Architecture

**Audience:** technical (developers). §1 is readable by everyone.

## 1. Components at a glance

```
┌──────────────┐   CSV export    ┌─────────────────────────────────────────┐
│ Pronto (POS) │──Google Sheet──▶│  FastAPI backend (backend/app/)         │
└──────────────┘   every 10 min  │  ├─ REST API  /api/*  (JWT auth)        │
                                 │  ├─ APScheduler:                        │
┌──────────────┐                 │  │   • pronto_sync   every 10 min      │
│ Film scanner │──uploads──┐     │  │   • drive_watcher every 5 min       │
└──────────────┘           ▼     │  └─ Email sender (Gmail SMTP/store)    │
                   ┌────────────┐│                                         │
                   │Google Drive│◀────── moves folders, sets permissions   │
                   │ Inbox/     ││                                         │
                   │ Delivered  │└──────────────┬──────────────────────────┘
                   └────────────┘               │ SQLAlchemy async (asyncpg)
                                                │ + Supabase PostgREST client
┌──────────────┐    HTTPS/JSON   ┌──────────────▼─────────────┐
│ React SPA    │────────────────▶│  PostgreSQL (Supabase)     │
│ (Vite, TS)   │    /api/*       └────────────────────────────┘
└──────────────┘
```

## 2. Backend

- **FastAPI 0.115** (Python 3.11+), fully async. Entrypoint `backend/app/main.py` (`uvicorn app.main:app`), which mounts seven routers under `/api` (auth, orders, rolls, stores/dashboard, pronto, drive, emails) and starts **APScheduler** on startup: Pronto sync every 10 min (plus one immediate run) and the Drive watcher every 5 min.
- **Two database access paths** (see `03-database.md`): request handlers use the SQLAlchemy 2.0 async ORM; the background services and some endpoints use the synchronous **supabase-py** client (blocking calls are pushed off the event loop with `asyncio.to_thread` in the sync job).
- **Config** — `app/core/config.py`, Pydantic Settings reading `backend/.env`: Supabase URL/keys, `DATABASE_URL` (asyncpg), JWT settings, CORS origins, service-account path. *(Note: `DRIVE_WATCHER_ENABLED` exists but is not currently checked; per-store `drive_config.enabled` is the effective switch. A `PAUSE_EMAILS` flag mentioned in older docs no longer exists.)*
- **Auth** — `app/core/auth.py`: bcrypt password hashing, HS256 JWTs (8-hour expiry), `get_current_user` dependency. See `06-roles-and-permissions.md`.
- **Google integrations** — Drive v3 API with a service account (`backend/service_account.json`); the Pronto Google Sheet is read unauthenticated via its CSV export URL.
- **Email** — Jinja2 HTML templates in `app/templates/email/`, sent through Gmail SMTP (SSL, port 465) using **per-store** Gmail app passwords stored in `drive_config`.
- **Image processing** — `app/services/image_processors/border_processor.py` (Pillow/numpy) adds film borders for the border-scan add-on; runs in an executor, reads scans from a local disk path and uploads results to Drive.

### Layout

```
backend/app/
├── api/          # Route handlers: auth, orders, rolls, stores, pronto, drive, emails
├── core/         # config (env), database (async engine/session), auth (JWT/bcrypt)
├── models/       # orm.py (SQLAlchemy), schemas.py (Pydantic + enums)
├── services/     # order_service, pronto_sync, drive_watcher, email_service,
│                 # image_processors/border_processor
└── templates/email/   # Jinja2 templates (current + staged *_v4 versions)
backend/migrations/    # 001–005 .sql, applied manually in Supabase SQL editor
backend/scripts/       # backfill_inbound_orders.py (one-off)
backend/tests/         # pytest suite for pronto_sync (mocked, no DB needed)
```

> **Legacy code warning:** `backend/main.py`, `backend/config.py`, `backend/models.py`, `backend/db/`, and `backend/routers/` are an **older, unmounted implementation** kept in the tree. Nothing imports them; do not extend them. (The only B2B endpoints live there, i.e. B2B is not currently part of the running app.)

## 3. Frontend

- **React 18 + TypeScript**, built with **Vite 5**, styled with **Tailwind CSS 3** (dark theme, orange `#ff6600` accent), routing via **React Router 6**, server state via **TanStack React Query 5** (30 s stale time, 1 retry).
- `src/lib/api.ts` — single Axios instance; base URL from `VITE_API_URL` (default `http://localhost:8000/api`); request interceptor attaches the JWT from `localStorage`, response interceptor logs out on 401.
- `src/hooks/useAuth.tsx` — auth context (user, token, login/logout). `App.tsx` guards all routes except `/login` with `PrivateRoute`.
- Pages: Login, Dashboard, Orders, Order Detail, Intake (documented individually in `screens/`). Shared shell: `components/layout/Layout.tsx` (sidebar nav, user footer, mobile drawer).

## 4. Runtime & deployment

- **Local dev:** `start.bat` launches both processes; backend `uvicorn app.main:app --reload --port 8000`, frontend `npm run dev` (Vite, port 5173). Database is the shared Supabase project — there is no local Postgres.
- **Production target:** Railway (not yet configured — no Procfile/railway config in the repo).
- **Migrations:** run manually in the Supabase SQL editor, in numeric order. Alembic is installed but unused.
- **Tests:** `cd backend && pytest tests/ -v` (pytest is not yet in `requirements.txt`; install it manually).

## 5. Design decisions worth knowing

- **Statuses live in two vocabularies**: orders use the six-state inbound pipeline (migration 003); rolls kept the older per-roll states (`booked … delivered`, `blank`, `archived`). Twin-check availability is driven by *roll* status (`archived` frees the number).
- **Idempotency by log-table**: the Drive watcher records every folder it touches in `drive_watcher_log` and skips anything already handled; deleting a row is the mechanism for "process this again".
- **Email as the delivery gate**: an order only becomes `delivered` when the customer email actually sends (watcher path) or a manual send succeeds — so a failed SMTP send leaves the order visible in `scanning`.
- **Denormalised customer data on orders** (name/email/phone/account copied at creation) keeps list queries cheap; the `customers` table is secondary.
