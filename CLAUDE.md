# CLAUDE.md — digiPrint Operations Platform

## What This Is

A full-stack operations platform for managing film processing orders across multiple retail stores. Staff book orders (linking to Pronto sales data), track film rolls through the lab, and notify customers when scans/prints are ready. Integrates with Google Drive for scan delivery and Google Sheets (via Pronto) for order data.

---

## Tech Stack

### Backend
- **FastAPI 0.115** (Python 3.11+) — async REST API
- **SQLAlchemy 2.0** (async ORM) + **asyncpg** driver
- **Alembic 1.13** — migrations (though main schema is in `backend/migrations/001_initial.sql`)
- **Pydantic 2.9** — settings + request/response validation
- **APScheduler** — periodic background tasks (Pronto sync, Drive watcher)
- **python-jose** — JWT auth (HS256)
- **bcrypt** — password hashing
- **Jinja2** — email templating
- **Google API Client** — Google Drive integration
- **HTTPX** — async HTTP client

### Frontend
- **React 18** + **TypeScript**
- **Vite 5** — build tool
- **React Router DOM 6** — routing
- **TanStack React Query 5** — async state management
- **Axios** — HTTP client (with JWT interceptor)
- **Tailwind CSS 3** — styling

### Database
- **PostgreSQL** via **Supabase** (managed, free tier)

### Deployment
- **Railway** (target)

---

## Project Structure

```
digiprint/
├── backend/
│   ├── app/
│   │   ├── api/              # Route handlers (one file per domain)
│   │   │   ├── auth.py       # POST /api/auth/login
│   │   │   ├── orders.py     # Order CRUD + status transitions
│   │   │   ├── stores.py     # Store list + dashboard stats
│   │   │   ├── pronto.py     # Pronto order lookup
│   │   │   ├── drive.py      # Google Drive config + sync
│   │   │   └── emails.py     # Email send + log
│   │   ├── models/
│   │   │   ├── orm.py        # SQLAlchemy ORM models
│   │   │   └── schemas.py    # Pydantic schemas + enums
│   │   ├── services/         # Business logic
│   │   │   ├── order_service.py   # Order creation, status updates, twin logic
│   │   │   ├── email_service.py   # SMTP + Jinja2 email sending
│   │   │   ├── pronto_sync.py     # Google Sheets CSV → pronto_cache table
│   │   │   └── drive_watcher.py   # Drive folder polling + twin matching
│   │   ├── core/
│   │   │   ├── config.py     # Pydantic Settings (reads .env)
│   │   │   ├── database.py   # Async engine + sessionmaker
│   │   │   └── auth.py       # JWT creation/validation, bcrypt
│   │   ├── templates/email/  # Jinja2 .html email templates
│   │   └── main.py           # App init, CORS, routers, scheduler startup
│   ├── migrations/
│   │   └── 001_initial.sql   # Full schema + seed data — run this in Supabase SQL editor
│   └── requirements.txt
├── frontend/
│   ├── src/
│   │   ├── pages/            # Full-page route components
│   │   │   ├── LoginPage.tsx
│   │   │   ├── DashboardPage.tsx
│   │   │   ├── OrdersPage.tsx
│   │   │   ├── OrderDetailPage.tsx
│   │   │   └── IntakePage.tsx    # New order booking form
│   │   ├── components/
│   │   │   ├── layout/Layout.tsx         # Nav + outlet
│   │   │   └── ProntoOrderSummary.tsx    # Pronto lookup display
│   │   ├── hooks/
│   │   │   ├── useAuth.tsx        # Auth context (user, token, login, logout)
│   │   │   └── useProntoLookup.ts # Pronto lookup API calls
│   │   ├── lib/
│   │   │   └── api.ts             # Axios instance + typed API methods
│   │   └── App.tsx               # Router, PrivateRoute guard
│   └── package.json
├── scripts/
│   └── seed_stores.py        # One-time store seeding
├── CLAUDE.md                 # This file
└── README.md
```

---

## Key Files

| File | Purpose |
|------|---------|
| `backend/app/main.py` | FastAPI app init, mounts all routers, starts APScheduler (Pronto sync every 10 min, Drive watcher every 5 min) |
| `backend/app/core/config.py` | All env vars via Pydantic Settings — source of truth for config |
| `backend/app/models/orm.py` | SQLAlchemy ORM definitions for all tables |
| `backend/app/models/schemas.py` | Pydantic schemas + enums (ServiceType, OrderStatus, OrderType, UserRole) |
| `backend/app/services/order_service.py` | Core business logic: create_order, list_orders, update_status, mark_blank |
| `backend/app/services/email_service.py` | Email sending; reads PAUSE_EMAILS env var to suppress sends |
| `backend/app/services/pronto_sync.py` | Fetches Google Sheets CSV, maps SKUs to addon flags, upserts pronto_cache |
| `backend/app/services/drive_watcher.py` | Polls Drive Inbox folders, matches twins, moves to Delivered, triggers status updates |
| `backend/migrations/001_initial.sql` | **Canonical schema** — run once in Supabase SQL Editor to bootstrap |
| `frontend/src/lib/api.ts` | All API calls; JWT auto-attached via Axios request interceptor |
| `frontend/src/hooks/useAuth.tsx` | Auth context; auto-logout on 401 via Axios response interceptor |

---

## Supabase Tables

### `stores`
One row per physical location. Seed: Bondi, Miranda, Parramatta, Brisbane, Cannington.
- `id` UUID PK, `name` (unique), `label`, `email`, `drive_root_folder_id`, `drive_inbox_folder_id`, `is_active`

### `users`
Staff accounts with role-based access.
- `role`: `staff` | `store_admin` | `master_admin`
- `store_id` FK — staff are scoped to one store; master_admin sees all

### `customers`
Customer lookup table (name, email, phone, account).
- Indexed on `email`, `name`

### `orders`
Master order record. One per Pronto order or manual entry.
- `order_type`: `film` | `b2b` | `print_only` | `passport`
- `status`: `booked` → `processing` → `scanned` → `print_ready` → `delivered` | `blank` | `archived` | `cancelled`
- `border_scan`, `contact_sheet`, `rebate_scan` — addon flags set from Pronto SKUs on creation
- `manual_entry` — true if booked without Pronto lookup
- Email tracking: `email_status`, `blank_email_status`, `print_ready_email_status`

### `rolls`
Individual film rolls within an order.
- `twin_check` — 4-digit zero-padded string (e.g., `"0042"`)
- Unique constraint: `(store_id, twin_check)` where `status != 'archived'`
- `service_type`: maps to processing type (e.g., C41, B&W, E6)

### `order_events`
Audit trail for all status changes and actions.
- `event_type`, `description`, `actor_label`, `metadata` (JSONB)

### `email_log`
Email send history per order.
- `email_type`: `delivery` | `blank` | `print_ready` | `b2b`
- `status`: `sent` | `failed` | `skipped`

### `pronto_cache`
Live sync from Google Sheets (RawData tab). Refreshed every 10 minutes.
- Contains: `sales_order_number`, `customer_name`, `sku_code`, etc.

### `store_settings`
Per-store policy configuration (e.g., `print_storage_days`, `negative_storage_days`, `twin_folder_prefix`).

### `drive_config`
Per-store Google Drive settings (`inbox_folder_id`, `delivered_folder_id`, `stabilise_seconds`).

### `vendors` / `vendor_releases`
B2B vendor directory and print batch ("drop") tracking.

---

## API Endpoints

### Auth
- `POST /api/auth/login` — email + password → `{ access_token, user }`

### Orders
- `POST /api/orders` — Create order
- `GET /api/orders` — List (filters: store_id, status, search; pagination)
- `GET /api/orders/:id` — Order detail + rolls
- `PATCH /api/orders/:id/status` — Update status + notes
- `PATCH /api/orders/:id/drive-link` — Set Drive folder URL
- `POST /api/orders/:id/mark-blank` — Mark rolls blank, optionally email customer
- `POST /api/orders/:id/add-rolls` — Add rolls to existing order
- `POST /api/orders/:id/reset-twins` — Unbook rolls (reset twin checks)
- `POST /api/orders/:id/retry-border` — Manually trigger border scan processing
- `GET /api/orders/:id/events` — Audit trail
- `GET /api/orders/check/twin` — Check twin existence (duplicate detection)
- `GET /api/orders/check/order-number` — Check order number existence

### Stores & Dashboard
- `GET /api/stores` — List active stores
- `GET /api/dashboard/stats` — Aggregated stats (totals, overdue, blank, avg turnaround)

### Pronto
- `GET /api/pronto/lookup/:order_number` — Customer + SKU lookup from pronto_cache
- `GET /api/pronto/force-sync` — Manually trigger Pronto cache refresh

### Drive
- `GET/PUT /api/drive/config/:store_id` — Store Drive config
- `POST /api/drive/sync` — Trigger Drive watcher manually
- `GET /api/drive/log` — Drive activity log

### Emails
- `POST /api/emails/send/:order_id` — Send email (Dev/Print)
- `POST /api/emails/resend/:order_id` — Resend email
- `GET /api/emails/log/:order_id` — Email history for order

### Health
- `GET /` — Service info
- `GET /health` — Status check

---

## Important Patterns & Rules

### Authentication
- JWT Bearer (HS256), 480-minute expiry
- Token payload: `sub`, `email`, `role`, `store_id`, `initials`, `full_name`
- `store_id` in token scopes staff to their store — master_admin has no store restriction
- Frontend: Axios request interceptor attaches `Authorization: Bearer <token>`; response interceptor redirects to `/login` on 401

### Twin Check System
- 4-digit zero-padded numbers: `"0042"`, `"0100"`
- Unique per store (partial unique index: status not in archived/delivered)
- Twin checks are freed for reuse when an order reaches: `delivered`, `blank`, `archived`
- Range input supported on intake form: `"0042-0051"` expands to 10 individual rolls
- Validation: must be exactly 4 digits

### Pronto Addon SKU Mapping
- `177426` → `border_scan = true`
- `177427` → `contact_sheet = true`
- `177428` → `rebate_scan = true`

These flags are detected during `create_order()` when a Pronto order number is provided.

### Email Templates
Located in `backend/app/templates/email/`:
- `scans_ready.html`
- `prints_and_scans_ready.html`
- `prints_ready.html`
- `negatives_ready.html`
- `blank_notification.html`

Email sends are suppressed when `PAUSE_EMAILS=1` in env.

### Drive Watcher
- Polls per-store Inbox folders every 5 minutes
- Matches Drive folder names to `twin_check` values using per-store prefix rules (`store_settings.twin_folder_prefix`)
- On match: moves folder to Delivered, updates roll `status` + `date_scanned`, triggers email logic
- Requires `service_account.json` with Google Drive API access

### Order Status Flow
```
booked → processing → scanned → print_ready → delivered
                                             → blank
                    → archived
                    → cancelled
```
Transitions are enforced in `order_service.update_status()`.

### Async Throughout
- All backend I/O is `async/await` (SQLAlchemy async engine, asyncpg, HTTPX)
- APScheduler uses async job executors
- Frontend uses React Query for async data fetching

### Role-Based Access
| Role | Scope |
|------|-------|
| `staff` | Own store only |
| `store_admin` | Own store + some admin features |
| `master_admin` | All stores |

---

## Environment Variables

### Backend (`backend/.env`)
```
SUPABASE_URL=https://your-project-ref.supabase.co
SUPABASE_KEY=your-anon-key
SUPABASE_SERVICE_KEY=your-service-role-key
DATABASE_URL=postgresql+asyncpg://postgres:password@db.ref.supabase.co:5432/postgres
JWT_SECRET=<random hex, e.g. openssl rand -hex 32>
JWT_ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=480
APP_ENV=development
CORS_ORIGINS=http://localhost:5173,http://localhost:3000
GOOGLE_SERVICE_ACCOUNT_FILE=service_account.json  # optional
DRIVE_WATCHER_ENABLED=true                         # optional
PAUSE_EMAILS=0                                     # set to 1 to suppress all emails
```

### Frontend (`frontend/.env`)
```
VITE_API_URL=http://localhost:8000/api
```

---

## Running Locally

### Database Setup (one-time)
1. Create a Supabase project at supabase.com
2. Run `backend/migrations/001_initial.sql` in the Supabase SQL Editor
3. Copy credentials to `backend/.env`

### Backend
```bash
cd backend
python -m venv venv
source venv/Scripts/activate   # Windows
pip install -r requirements.txt
cp .env.example .env           # fill in credentials
uvicorn app.main:app --reload --port 8000
```

### Frontend
```bash
cd frontend
npm install
cp .env.example .env           # set VITE_API_URL=http://localhost:8000/api
npm run dev                    # http://localhost:5173
```
