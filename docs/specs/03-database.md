# Database Specification

**Audience:** technical (developers). Staff and management can skim the "What each table is for" column headers and the status-lifecycle section.

The platform uses **PostgreSQL hosted on Supabase**. The backend talks to it two ways:

1. **SQLAlchemy 2.0 async ORM** (via `asyncpg`) — used by the API request handlers for the core tables (`app/models/orm.py`).
2. **Supabase Python client (PostgREST)** — used by the background services (`pronto_sync`, `drive_watcher`, `email_service`) and for tables that have no ORM model.

> **Schema sources.** The base schema is `backend/migrations/001_initial.sql`, extended by migrations `002`–`005`. Several tables (`pronto_cache`, `sku_map`, `store_settings`, `drive_config`, `drive_watcher_log`, `promotions`) and the `pronto_order_summary` view were created **directly in the Supabase SQL editor** and have no CREATE statement in the repo — their shapes below are reconstructed from the queries the code runs against them. Migrations are applied manually in the Supabase SQL editor (no Alembic).

---

## Entity overview

```
stores ─┬─< users
        ├─< orders ─┬─< rolls ─< roll_audit_log
        │           ├─< order_events
        │           └─< order_activity
        ├─< vendor_releases >─ vendors
        ├── store_settings   (1:1, policy + email branding)
        └── drive_config     (1:1, Drive folders + Gmail creds)

pronto_cache        (mirror of the Pronto Google Sheet, feeds order creation)
sku_map             (SKU → service/film-type lookup)
refund_warnings     (unmatched refunds awaiting manual review)
email_log           (send history)
drive_watcher_log   (one row per Drive folder the watcher has seen)
customers           (lookup table; orders also carry a denormalised snapshot)
promotions          (active promos injected into customer emails)
```

---

## Core tables

### `stores`
One row per physical retail location. Seeded: Bondi, Miranda, Parramatta, Brisbane, Cannington (Melbourne referenced in code as future).

| Column | Notes |
|---|---|
| `id` UUID PK | |
| `name` | Unique, e.g. `Bondi` |
| `label` | Display name, e.g. `digiDirect Bondi` |
| `email` | Lab inbox, e.g. `lab.bondi@digidirect.com.au` |
| `territory_code` | Migration 003. Unique when set. Maps Pronto CSV "Territory" to a store: `BOND`, `MIRA`, `PARR`, `BRIS`, `CANN`, `MELB` |
| `drive_root_folder_id`, `drive_inbox_folder_id` | Legacy Drive pointers (live config is in `drive_config`) |
| `is_active`, `created_at` | |

### `users`
Staff accounts. Passwords are bcrypt-hashed.

| Column | Notes |
|---|---|
| `id` UUID PK, `email` unique, `password_hash`, `full_name` | |
| `initials` | Operator identifier stamped onto orders/rolls/events |
| `role` | `staff` \| `store_admin` \| `master_admin` |
| `store_id` FK → stores | NULL = access all stores (master admin) |
| `is_active`, `created_at`, `last_login` | |

### `customers`
Simple lookup table (`name`, `email`, `phone`, `account`), indexed on email and name. Orders keep their own denormalised customer snapshot, so this table is secondary.

### `orders`
The master record — one per Pronto sale (or manual booking). This table changed substantially in **migration 003 (inbound pipeline)**.

**Status lifecycle (post-migration-003, enforced by CHECK constraint):**

```
inbound ──> booked_in ──> scanning ──> delivered
   │             │            │
   └── discarded └────────────┴──> cancelled
```

| Status | Meaning |
|---|---|
| `inbound` | Auto-created from the Pronto feed; film not yet physically booked in at the lab |
| `booked_in` | Staff attached rolls/twin checks via the Intake form |
| `scanning` | First scan detected (Drive watcher) or Drive link set manually |
| `delivered` | Scans delivered / customer emailed. Terminal. Also used for all-blank orders (order-level `blank` status was removed in 003) |
| `cancelled` | Full refund detected pre-delivery, or manual cancel. Terminal |
| `discarded` | Staff dismissed an inbound row as not a real lab job (`discard_reason`: `charge_correction`, `add_on_existing`, `not_film_related`, `duplicate_sale`, `other`). Terminal |

Old statuses (`booked`, `processing`, `scanned`, `print_ready`, `blank`, `archived`) were migrated: `booked→booked_in`, `scanned/processing→scanning`, the rest → `delivered`.

**Key columns** (beyond id/store/customer snapshot):

| Group | Columns |
|---|---|
| Identity | `order_number` (indexed), `pronto_order_number`, `pronto_account_number` (003) |
| Type | `order_type`: `film` \| `b2b` \| `print_only` \| `passport` |
| Add-on flags | `border_scan`, `contact_sheet`, `rebate_scan` (set from Pronto SKUs 177426/177427/177428); `border_scan_status` (`processing`/`complete`/`failed`), `bordered_scans_drive_url` |
| Delivery | `drive_order_folder_url`, `scan_link` |
| Email tracking | `email_status`, `blank_email_status`, `print_ready_email_status` |
| Flags | `is_print_only`, `has_blanks`, `manual_entry` (booked without Pronto lookup) |
| Pronto dates (003) | `pronto_order_date`, `pronto_shipped_date` |
| Status timestamps (003) | `booked_in_at`, `scanning_at`, `delivered_at`, `cancelled_at`, `discarded_at`, `discarded_by` |
| Discard (003) | `discard_reason`, `discard_notes` |
| Refund (003) | `refund_status` (`partial`/`full`), `refund_pronto_order_number`, `refund_amount` |
| Legacy dates | `created_at`, `date_scanned`, `date_delivered`, `date_print_ready_notified` |
| Operator | `operator_id` FK → users, `operator_initials`, `notes` |

> The ORM model (`app/models/orm.py`) only maps a subset of the 003 columns (`booked_in_at`); the background services read/write the rest through the Supabase client.

### `rolls`
Individual film rolls inside an order. `ON DELETE CASCADE` from orders.

| Column | Notes |
|---|---|
| `twin_check` | 4-digit zero-padded string (`"0042"`). The physical twin-check ticket number attached to the roll |
| `service_type` | `Dev only`, `Dev+Scan`, `Dev+Scan+Print`, `Dev+Print`, `Scan only`, `Print only` |
| `status` | Roll-level lifecycle (unchanged by 003): `booked → processing → scanned → print_ready → delivered` plus `blank`, `archived` |
| `is_blank`, `blank_confirmed_at`, `blank_notified_at` | Blank-roll workflow |
| `drive_folder_name`, `drive_folder_url` | Set by the Drive watcher when the scan folder is matched |
| `date_scanned`, `date_delivered`, `operator_initials`, timestamps | |

**Twin-check uniqueness:** partial unique index `(store_id, twin_check) WHERE status != 'archived'`. A twin number is **freed for reuse** when its roll is archived — which happens automatically when the parent order reaches a terminal status (`delivered`, `cancelled`, `discarded`; see `TWIN_EXPIRY_STATUSES` in `order_service.py`). Admins can re-lock twins via the reset-twins endpoint.

### `order_events`
Audit trail, one row per action: `event_type` (e.g. `booked_in`, `status_change`, `twin_checks_expired`, `scans_complete`, `delivered`, `border_scan_complete`), `description`, `actor_id`/`actor_label` (initials or `system`/`drive_watcher`), `metadata` JSONB. The ORM maps the `metadata` column to the attribute `event_data`.

### `order_activity` (migration 003)
A second, lighter activity log written by `pronto_sync` (`order_created`, `order_cancelled`, `refund_processed`, `partial_refund_processed`) with `event_data` JSONB and `operator_id` TEXT (`"system"`). Exists alongside `order_events`; the two have not been consolidated.

### `roll_audit_log`
Field-level change history for rolls — currently used for twin-check edits: `roll_id`, `field_name`, `old_value`, `new_value`, `changed_by_user_id`, `changed_at`.

---

## Pronto integration tables

### `pronto_cache`
A near-live mirror of the Pronto master Google Sheet ("RawData" tab), refreshed every 10 minutes. **Append/upsert-only — rows are never deleted.** One row per (sales order, BO suffix, SKU) line.

| Group | Columns |
|---|---|
| Natural key | `cache_key` = `sales_order_number\|bo_suffix\|sku_code`, NOT NULL, unique (migration 004) — upsert conflict target |
| Sheet columns | `territory`, `order_date`, `shipped_date`, `sales_order_number`, `bo_suffix`, `customer_name`, `email_address`, `phone_number`, `pronto_account`, `sales_rep_name`, `sku_code`, `product_name`, `category`, `class`, `group_name`, `shipped_units`, `shipped_value`, `data_updated_on` |
| Enriched from `sku_map` | `service_type`, `film_type`, `scan_resolution` |
| Tracking (004) | `first_seen_at`, `last_seen_at`, `order_created` (an inbound order was made from this row), `is_refund`, `refund_matched_to_order_id`, `refund_match_confidence` (`exact` / `cash_fallback` / `unmatched`), `synced_at` |

### `sku_map`
Lookup table (maintained in Supabase directly): `sku_code → service_type, film_type, scan_resolution, category`. Used to enrich `pronto_cache` rows and drive the intake form's roll/scan/print summaries.

### `pronto_order_summary` (view)
Aggregates `pronto_cache` per sales order for the intake lookup endpoint: customer fields, `inferred_service_type`, `total_rolls`, and a `sku_lines` JSON array with per-line `category`, `film_type`, `scan_resolution`, `product_name`, `shipped_units`. Defined in Supabase (not in repo migrations).

### `refund_warnings` (migration 005)
Refund groups from the Pronto feed that could not be auto-matched to an order. Staff resolve them manually.

| Column | Notes |
|---|---|
| `refund_pronto_order_number`, `pronto_account_number`, `territory`, `refund_amount` | |
| `refund_lines` JSONB | The raw refund line items (sku, product, units, value) |
| `status` | `pending` → `manually_resolved` \| `ignored` |
| `resolved_by`, `resolved_at`, `resolution_notes`, `created_at` | |

---

## Configuration & operations tables

### `store_settings`
Per-store policy and email branding (1:1 with stores).

| Column | Notes |
|---|---|
| `print_storage_days`, `negative_storage_days`, `drive_storage_days` | Drive expiry/pickup windows quoted in customer emails (defaults 30/30/90) |
| `google_review_url` | Review CTA in emails |
| `twin_folder_prefix` | Drive-watcher folder naming rule, e.g. Bondi/Miranda/Cannington use `0000` + twin, Brisbane `A00` + twin, Parramatta raw 4-digit twin |
| `address_line`, `reply_email`, `hours_label`, `instagram_url` | Migration 002 — v4 email branding, all optional |

### `drive_config`
Per-store Google Drive + email-sending config (1:1 with stores).

| Column | Notes |
|---|---|
| `inbox_folder_id`, `delivered_folder_id` | Drive folder IDs the watcher polls / delivers into |
| `stabilise_seconds` | Folder must be unmodified this long before processing (default 30) |
| `enabled` | Watcher on/off per store |
| `gmail_address`, `gmail_app_password` | **Per-store Gmail SMTP credentials** used to send customer emails |
| `film_scans_root`, `border_processing_root` | Local disk paths for border-scan processing (defaults `D:/Film Scans`, `D:/Border Processing`) |

### `drive_watcher_log`
One row per Drive folder the watcher has inspected, upserted on `folder_id`: `store_id`, `folder_name`, `status` (`processing`, `moved`, `emailed`, `skipped`, `ambiguous`, `rescan_detected`, `error`), `detail`, `roll_id`, `order_id`. Acts as both audit log and idempotency guard (already-`moved`/`emailed`/`skipped` folders are not reprocessed). Deleting a row re-enables processing (used for approving rescans).

### `email_log`
Send history: `order_id`, `template_key`, `recipient`, `status` (`sent`/`failed`), `triggered_by` (`manual`), `sent_at`. (The 001 schema had `email_type`/`subject`; the code now writes `template_key`/`triggered_by` — the live table was altered in Supabase.)

### `promotions`
Active promotions injected into customer emails: `active` boolean, `valid_until` date, plus display fields consumed by the templates.

---

## B2B tables (currently dormant)

`vendors` (name, contact, Pixieset gallery URL) and `vendor_releases` (batched print "drops": `status` `pending → in_production → qc → ready → dispatched → complete`, item counts, due date). ORM models exist, but no live API endpoints are mounted for them — the only B2B routes live in the legacy, unmounted `backend/routers/b2b.py`.

---

## Views (from 001)

- `v_order_summary` — one row per order with roll counts, blank counts, turnaround hours.
- `v_overdue_orders` — orders older than 48h not yet delivered/archived/cancelled.

> Note: both views predate migration 003 and still reference the old status vocabulary in their WHERE clauses; the dashboard endpoint computes its own stats in Python instead of using them.

## Row-level security

RLS is enabled on `stores`, `orders`, `rolls` with permissive `USING (true)` policies — effectively no restriction; the backend connects with the service role key and enforces store scoping in application code.
