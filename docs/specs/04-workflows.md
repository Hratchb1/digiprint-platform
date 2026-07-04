# How It Works — End-to-End Workflows

**Audience:** all readers. Written in plain language with technical pointers in brackets for developers.

---

## 1. The big picture

A customer buys film processing at a digiDirect store. The sale lands in **Pronto** (the POS/ERP), which exports to a Google Sheet. digiPrint watches that sheet, creates an **inbound order** automatically, and from there the lab tracks the physical film through booking, scanning, and delivery — ending with an automatic email to the customer containing a Google Drive link to their scans.

```
Pronto sale ──(Google Sheet, synced every 10 min)──> inbound order
     │
Staff book the film in (Intake screen, twin checks) ──> booked_in
     │
Lab develops + scans; scanner uploads folder to Drive Inbox
     │
Drive watcher (every 5 min) matches folder → roll ──> scanning
     │
All rolls scanned → folder moved to Delivered, email sent ──> delivered
```

---

## 2. Pronto sync (every 10 minutes)

[`app/services/pronto_sync.py`, scheduled in `app/main.py`; also runs once at startup and on demand via `POST /api/pronto/sync`]

1. **Fetch** the Pronto master Google Sheet ("RawData" tab) as CSV.
2. **Upsert** every line into `pronto_cache`, keyed on `(sales order, BO suffix, SKU)`. Rows are never deleted; `first_seen_at` is preserved, `last_seen_at` refreshed. SKUs are enriched with service/film-type data from `sku_map`.
3. **Group rows by sales order** and classify each group:
   - **New sale** (no negative quantities) → if no order with that Pronto number exists, create an order with status **`inbound`**, assigned to a store via the sheet's Territory code (`BOND`→Bondi etc.). Unknown territory → skipped with a warning.
   - **Refund** (any negative quantity) → try to match it to an existing order (see §7).
4. **Apply add-on flags**: SKU `177426` → border scan, `177427` → contact sheet, `177428` → rebate scan on the matching order.

A one-off script, `backend/scripts/backfill_inbound_orders.py`, seeds inbound orders from cache rows that predate this pipeline (supports `--dry-run`).

## 3. Booking in (Intake screen)

Staff physically receive the film, stick **twin check** tickets on the rolls, and book the order in:

- Staff look up the Pronto order number; the form auto-fills customer details and shows a roll/scan/print summary derived from the SKUs [`GET /api/pronto/lookup/{order_number}`, `pronto_order_summary` view].
- Twin checks are 1–4 digits, zero-padded to 4 (`42` → `"0042"`); a range like `0042-0051` expands to individual rolls. Each twin must be unique among non-archived rolls in the store — duplicates are rejected with a 409 and can be pre-checked live [`GET /api/orders/check/twin`].
- If the Pronto sync already created an **inbound** order for that number, the system doesn't create a duplicate: rolls are attached to the existing order and it is **promoted to `booked_in`** [`order_service.create_order` guard, and the Intake duplicate-modal "Add rolls" path via `POST /api/orders/{id}/add-rolls`].
- Manual bookings (Pronto down or non-Pronto work) set `manual_entry = true`.

## 4. Scanning and Drive delivery (watcher, every 5 minutes)

[`app/services/drive_watcher.py`; manual trigger `POST /api/drive/sync`]

The lab's scanner uploads each roll's images to a per-store **Inbox folder** on Google Drive, named after the twin check with a per-store prefix (`store_settings.twin_folder_prefix`: e.g. Bondi `00000042`, Brisbane `A000042`, Parramatta plain `0042`).

Each cycle, per enabled store (`drive_config.enabled`):

1. List Inbox subfolders; skip any already handled (`drive_watcher_log` is the idempotency guard) or modified less than `stabilise_seconds` ago (still uploading).
2. Parse the twin from the folder name; find the matching roll in that store. Eligible = not yet scanned, no Drive link, not delivered/blank/archived. Multiple matches → logged `ambiguous`, none → `skipped`; a twin that was already scanned → **`rescan_detected`** (surfaced on the Order Detail screen for staff approval; approving deletes the log row so the next cycle reprocesses it).
3. Move the folder into `Delivered/<year>/<month>/<order number customer name>/`, make it link-shareable, and stamp the roll (`status=scanned`, `date_scanned`, `drive_folder_url`).
4. First scanned roll advances the order **`booked_in` → `scanning`**.
5. When **all** non-blank rolls are scanned: record the order's Drive URL, then send the customer email. **Only if the email sends successfully** does the order advance to **`delivered`** — otherwise it stays in `scanning` for retry.
6. If the order has the **border scan** add-on, a background job copies the images from the local scan drive, adds borders [`app/services/image_processors/border_processor.py`], and uploads a "Bordered Scans" folder next to the originals (`border_scan_status`: `processing`→`complete`/`failed`; staff can retry via `POST /api/orders/{id}/retry-border`).

## 5. Customer emails

[`app/services/email_service.py`]

- **Automatic**: sent by the Drive watcher when the last roll is scanned.
- **Manual**: staff trigger from the Order Detail screen [`POST /api/emails/send/{order_id}`, `/resend/{order_id}`] — used for Dev-only / Print-only orders that never pass through the watcher. A successful manual send also advances a non-terminal order to `delivered`.

The template is picked from the order's service type (`scans_ready`, `prints_and_scans_ready`, `prints_ready`, `negatives_ready`, fallback `blank_notification`), rendered with Jinja2 and sent via **per-store Gmail SMTP** (credentials in `drive_config`). Content includes the Drive link, storage-expiry dates computed from `store_settings` (prints/negatives/Drive retention), active `promotions`, cross-sell tiles for services the order didn't include, and a Google-review link. Every send is recorded in `email_log`, and `orders.email_status` is set to `sent`.

> Redesigned `*_v4.html` templates exist alongside the current ones but are **not yet live** — `TEMPLATE_MAP` still points at the old files (deferred by decision on 2026-07-04).

## 6. Blank rolls

If a developed roll has no images, staff mark it blank on the Order Detail screen [`POST /api/orders/{id}/mark-blank`]: the roll gets `is_blank=true`, `status=blank`, the order gets `has_blanks=true`. If **every** roll is blank the order is terminal and goes straight to `delivered` (the order-level `blank` status was removed in migration 003). The `blank_notification` email can be sent to the customer.

## 7. Refunds

Detected in the Pronto sync when a sales-order group contains negative quantities:

1. Build the refund's SKU signature (non-add-on SKUs and absolute quantities).
2. **Match** it to an order: by Pronto account number + identical SKU signature (`exact`), or for cash sales by store/territory + signature, oldest first (`cash_fallback`).
3. **Apply**:
   - Full refund (covers 100% of the original SKUs) before delivery → order **`cancelled`** (twin checks are freed).
   - Full refund after delivery → order keeps `delivered`, tagged `refund_status='full'`.
   - Partial refund → tagged `refund_status='partial'`.
4. **No match** → a row in `refund_warnings` (`pending`) for staff to resolve manually.

## 8. Twin-check lifecycle

- **Assigned** at intake; unique per store among non-archived rolls (DB partial unique index + application check).
- **Freed** automatically when the order reaches `delivered`, `cancelled`, or `discarded` — all its rolls are archived and the numbers can be reused (`TWIN_EXPIRY_STATUSES`, logged as `twin_checks_expired`).
- **Reset**: admins can re-lock archived twins on an order [`POST /api/orders/{id}/reset-twins`, store_admin/master_admin only].
- **Edited**: any roll's twin can be corrected, even after delivery, unless the new number is actively held in the store [`PATCH /api/rolls/{roll_id}/twin-check`; changes are written to `roll_audit_log` and the order's event trail].

## 9. Discarding inbound orders

Not every Pronto sale is a real lab job (charge corrections, add-ons to existing orders, non-film items, duplicate sales). Staff can mark an inbound order **`discarded`** with a reason (`discard_reason`/`discard_notes`, migration 003), which is terminal and frees nothing (no rolls exist yet).

## 10. Audit trail

Every meaningful action writes to `order_events` (who: `actor_label` = staff initials or `system`/`drive_watcher`/`border_processor`; what: `event_type` + description + JSON metadata). Pronto-sync actions additionally write to `order_activity`. The Order Detail screen shows the trail via `GET /api/orders/{id}/events`.
