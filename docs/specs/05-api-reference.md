# API Reference

**Audience:** technical (developers).

Base URL: `/api` (dev: `http://localhost:8000/api`). Interactive docs at `/docs` (Swagger) and `/redoc`.

**Authentication:** JWT Bearer (HS256, 480-minute expiry) obtained from `POST /api/auth/login`. Endpoints marked 🔒 require `Authorization: Bearer <token>` (`get_current_user` dependency). Token claims: `sub`, `email`, `role`, `store_id`, `initials`, `full_name`.

> ⚠️ **Known gap:** the `drive` and `emails` routers currently have **no auth dependency** — those endpoints are open to anyone who can reach the API (including reading/writing Drive config, which contains the Gmail app password field on write). Treat as a bug to fix, not a design choice.

---

## Auth — `app/api/auth.py`

| Method & path | Purpose |
|---|---|
| `POST /auth/login` | Body `{email, password}` → `{access_token, token_type, user}`. 401 invalid credentials, 403 disabled account. Updates `last_login`. |

## Orders — `app/api/orders.py` (all 🔒)

| Method & path | Purpose |
|---|---|
| `POST /orders` | Book in an order. Body: `OrderCreate` (`order_number`, `store_id`, `customer_*`, `order_type`, `rolls[{twin_check, service_type}]`, `operator_initials?`, `notes?`, `manual_entry?`). 409 on duplicate twin. If an `inbound` order with the same number exists, attaches rolls to it and promotes it instead of creating a duplicate. Returns 201 + enriched order. |
| `GET /orders` | List. Query: `store_id?`, `status?`, `search?` (order number / customer name / email, ilike), `limit` (≤500, default 100), `offset`. Non-master-admin callers are forced to their own store when `store_id` is omitted. |
| `GET /orders/{id}` | Order detail incl. rolls. 404 if missing. |
| `PATCH /orders/{id}/status` | Body `{status, notes?}` — status must be one of the six `OrderStatus` values. `delivered` also delivers all non-blank rolls; any terminal status (`delivered`/`cancelled`/`discarded`) archives rolls and frees twin checks. |
| `PATCH /orders/{id}/drive-link` | Body `{drive_order_folder_url}`. Sets link + `date_scanned`; advances `booked_in → scanning`. |
| `POST /orders/{id}/mark-blank` | Body `{roll_ids: [], send_email?}`. Marks rolls blank; all-blank order → `delivered`. |
| `POST /orders/{id}/add-rolls` | Body `{rolls: [], operator_initials?}`. 409 on twin conflict. Promotes an `inbound` order to `booked_in` (Intake duplicate-modal path). |
| `POST /orders/{id}/reset-twins` | Admin only (`store_admin`/`master_admin`, else 403). Re-locks archived twins (roll status back to `booked`). |
| `POST /orders/{id}/retry-border` | Re-queues border processing. 400 if no border addon / already processing / no scanned rolls. Returns `{status: "queued"}`. |
| `GET /orders/{id}/events` | Audit trail, newest first. |
| `GET /orders/check/twin?store_id&twin_check` | `{exists, twin_check}` (input zero-padded). |
| `GET /orders/check/order-number?order_number&store_id` | `{exists}` or `{exists: true, order}`. |

## Rolls — `app/api/rolls.py` (🔒)

| Method & path | Purpose |
|---|---|
| `PATCH /rolls/{roll_id}/twin-check` | Body `{twin_check}` (exactly 4 digits). Edits a roll's twin on any status; 409 if the number is held by an active roll in the store. Writes `roll_audit_log` + order event. |

## Stores & dashboard — `app/api/stores.py` (🔒)

| Method & path | Purpose |
|---|---|
| `GET /stores` | Active stores, ordered by name. |
| `GET /dashboard/stats?store_id&period_days` | Totals, delivered, pending (`booked_in`+`scanning`), overdue (pending >48h), blanks, avg turnaround hours, today's orders/rolls. Non-master-admins pinned to their own store. `period_days` 1–365, default 30. |

## Pronto — `app/api/pronto.py` (🔒)

| Method & path | Purpose |
|---|---|
| `GET /pronto/lookup/{order_number}` | Intake auto-fill from the `pronto_order_summary` view: customer fields, `inferred_service_type`, `total_rolls`, roll/scan/print summaries, raw `sku_lines`. 404 if not in cache. |
| `GET /pronto/status` | `{total_rows, last_sync}` of `pronto_cache`. |
| `POST /pronto/sync` | Manually run the sync. Admin only (403 otherwise). Returns the sync summary. |

## Drive — `app/api/drive.py` (⚠️ currently unauthenticated)

| Method & path | Purpose |
|---|---|
| `GET /drive/config` | All store Drive configs (excludes the Gmail password from the select). |
| `GET /drive/config/{store_id}` | One store's config. 404 if none. |
| `PUT /drive/config/{store_id}` | Update allowed fields: `inbox_folder_id`, `delivered_folder_id`, `gmail_address`, `gmail_app_password`, `stabilise_seconds`, `enabled`. |
| `POST /drive/sync` | Run a watcher cycle now. |
| `GET /drive/log?store_id&status&limit` | Recent watcher log entries (default 50). |
| `GET /drive/log/order/{order_id}` | `rescan_detected` entries for an order (Order Detail rescan alerts). |
| `DELETE /drive/log/{folder_id}` | Clear a log entry so the folder is reprocessed (approve a rescan). |

## Emails — `app/api/emails.py` (⚠️ currently unauthenticated)

| Method & path | Purpose |
|---|---|
| `POST /emails/send/{order_id}` | Manual send. Body `{template_override?}` (a `TEMPLATE_MAP` key). Logs to `email_log`; success sets `email_status=sent` and advances non-terminal orders to `delivered`. 500 on failure. |
| `POST /emails/resend/{order_id}` | Resend regardless of previous status. |
| `GET /emails/log/{order_id}` | Send history for an order. |
| `GET /emails/log?status&limit` | Recent sends across all orders. |

## Health — `app/main.py`

| Method & path | Purpose |
|---|---|
| `GET /` | Service name/version/docs pointer. |
| `GET /health` | `{status: "ok"}`. |

---

### Error conventions

- `401` missing/invalid token (frontend auto-logs-out on this), `403` role not allowed, `404` not found, `409` twin-check/order-number conflicts, `422` Pydantic validation, `500` unexpected.

### Background jobs (not endpoints, but part of the API surface's behavior)

- **Pronto sync** — every 10 min + at startup (`sync_pronto_cache`).
- **Drive watcher** — every 5 min (`run_drive_watcher`). Note: `DRIVE_WATCHER_ENABLED` exists in config but is not currently checked; per-store `drive_config.enabled` is the effective switch.
