# Screen: Orders

**Audience:** all readers · **Route:** `/orders` · **Component:** `frontend/src/pages/OrdersPage.tsx`

## Purpose
Searchable, filterable list of all orders the user can see. The main way staff find an order to open its detail page.

## Layout & controls
1. **Header** — order count and a **New Intake** button (links to `/intake`).
2. **Filters** (query re-runs live, previous results kept while loading):
   - **Search** — matches order number, customer name, or customer email (server-side, case-insensitive substring).
   - **Status dropdown** — All statuses / individual status values.
   - **Store dropdown** — master admin only; staff are pinned to their store by the backend.
3. **Table** (up to 200 rows via `GET /api/orders?limit=200`): Order number · Customer · Status chip · Store · Roll count · **Sale date** (Pronto `order_date` when available) · **Booked in** (`created_at`, when staff entered it) · chevron. Rows collapse to a compact two-line layout on mobile. Every row links to `/orders/{id}`.

## States
- "Loading…" row set, "No orders found" empty state.

## Known gaps (as of 2026-07-04)
- The **status filter options and chip colours still use the pre-migration-003 vocabulary** (`booked`, `scanned`, `print_ready`, `blank`, `archived`). The backend now uses `inbound / booked_in / scanning / delivered / cancelled / discarded`, so several filter options return nothing and new statuses render in the grey fallback chip. Needs a frontend refresh to the new status model.
- No pagination beyond the first 200 orders.
