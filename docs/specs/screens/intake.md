# Screen: Film Intake

**Audience:** all readers · **Route:** `/intake` · **Component:** `frontend/src/pages/IntakePage.tsx` (the most behaviour-rich screen)

## Purpose
Book physical film into the lab: link the rolls to a Pronto sale (or enter details manually), assign twin-check numbers, and create/extend the order. Designed for speed — keyboard-first, Enter advances every step.

## Flow (step machine: `operator → lookup [→ manual] → confirm → twins → done`)

### 1. Operator prompt
First visit each browser session asks for the operator's initials (max 5 chars, uppercased, stored in `sessionStorage`). All bookings that session are stamped with these initials.

### 2. Order lookup
Scan or type the **Pronto order number** → `GET /api/pronto/lookup/{order_number}`.
- **Found:** service type is pre-selected from the SKUs (`inferred_service_type`) and a duplicate check runs (`GET /api/orders/check/order-number`). The **Pronto order summary** panel (`ProntoOrderSummary` component) shows customer details plus roll/scan/print breakdowns derived from the SKUs; staff confirm (and can change the service type) to proceed.
- **Not found:** an error panel offers **"Enter manually"**.

### 3. Manual entry (fallback)
Form for customer name (required), email, phone, account number, service type, and — for master admins only — a store selector (staff inherit their store from the JWT). The order is flagged `manual_entry = true` and shows a "Manual" badge everywhere afterwards.

### 4. Duplicate-order modal
If an order with that number already exists at the store, an amber modal shows who booked it, when, roll count and status, and offers:
- **➕ Add more rolls** — attach the new twins to the existing order (`POST /api/orders/{id}/add-rolls`). This is also the path that promotes a Pronto-created **inbound** order to `booked_in`.
- **📋 New booking** — creates a separate order numbered `<order>-B`.
- **✕ Cancel** — reset the form.

### 5. Twin entry
Two modes (toggle):
- **Twin checks** — one field accepting a single 4-digit twin (`0042`) or a dash range (`0042-0051`). Enter adds and refocuses; **Enter on an empty field saves the booking** (rapid keyboard flow).
- **Range** — separate first/last fields with a live "N rolls in range" preview.

Validation (client-side, `validateSingleFieldInput` / `validateRangeInputs`): exactly 4 digits, no `0000`, no wrap-around ranges, max 200 rolls per range. Twins already added this session are rejected; each batch is also checked against the store (duplicates render as red "dup" chips and are excluded from saving). Chips can be removed individually.

### 6. Save & done
**Book/Add N rolls** posts the order (`POST /api/orders` or `/add-rolls`) with the mapped service type (`Develop + Scan` → `Dev+Scan` etc.). Success shows a green confirmation (customer, roll count, order number, operator) with a **Next order** button; the next lookup screen also shows a dismissible "Last booked" banner. Server-side twin conflicts (409) surface as an inline error.

## Known gaps (as of 2026-07-04)
- Store IDs and territory→store mapping are **hard-coded UUIDs** in the component (`TERRITORY_STORE_MAP`, `STORE_OPTIONS`) — new stores require a frontend change.
- The per-batch duplicate check calls `POST /api/rolls/check-twins`, an endpoint that **does not exist** on the backend; the failure is swallowed, so store-duplicate marking never happens client-side. Final save still enforces uniqueness (409).
- Master admins with no store in their token must use manual entry to pick a store; Pronto-path bookings derive the store from the territory only.
