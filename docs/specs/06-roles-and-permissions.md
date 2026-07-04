# Roles & Permissions

**Audience:** all readers.

## Roles

| Role | Scope | Typical user |
|---|---|---|
| `staff` | Their own store only | Lab/retail staff booking and processing film |
| `store_admin` | Their own store + admin actions | Store manager |
| `master_admin` | All stores | Head office / platform owner |

The role and store live inside the JWT issued at login (`role`, `store_id` claims), alongside `sub` (user id), `email`, `initials`, `full_name`. Tokens expire after **8 hours** (480 min); the frontend then auto-logs-out on the first 401.

## How scoping is enforced

- **Server-side, per endpoint** — not database-level (RLS policies exist but are permissive; the API connects with the service key):
  - `GET /api/orders` and `GET /api/dashboard/stats`: non-`master_admin` callers are pinned to the `store_id` in their token regardless of query params.
  - `POST /api/pronto/sync` and `POST /api/orders/{id}/reset-twins`: require `store_admin` or `master_admin` (403 otherwise).
- **Client-side conveniences** (not security): store selector dropdowns only render for `master_admin` (Dashboard, Orders, Intake manual-entry).

## Operator initials

Separate from login: the Intake screen asks for the operator's initials once per browser session and stamps them on orders, rolls, and audit events (`operator_initials`, `actor_label`). This identifies *who physically handled the film* even when a shared terminal/account is used.

## Known gaps (as of 2026-07-04)

- Endpoints under `/api/drive/*` and `/api/emails/*` have **no authentication at all** — including updating Drive config (which accepts a Gmail app password) and triggering customer emails. High-priority fix: add the `get_current_user` dependency (and role checks where appropriate).
- Order/roll write endpoints authenticate the user but do **not verify the target order belongs to the user's store** — any logged-in staff member can modify any store's orders by ID.
- There is no user-management API (create/disable users, reset passwords); accounts are managed directly in the database (`seed_admin.py` / SQL).
