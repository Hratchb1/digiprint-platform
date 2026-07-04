# Screen: Order Detail

**Audience:** all readers · **Route:** `/orders/{id}` · **Component:** `frontend/src/pages/OrderDetailPage.tsx`

## Purpose
The workbench for a single order: see everything about it, move it through the pipeline, manage rolls (blanks, twin edits), handle Drive links, border scans, rescans, and customer emails, and review the full audit trail.

## Layout

### Main column
1. **Rescan alerts** (amber cards) — shown when the Drive watcher saw a folder for an already-scanned twin (`GET /api/drive/log/order/{id}`, status `rescan_detected`). **Approve** deletes the watcher-log entry so the folder is reprocessed on the next 5-minute cycle.
2. **Order header card** — order number chip, "Manual" badge for manual entries, status chip, customer name (large), account chip, then a grid: email, phone (tap-to-call), store, operator, booked time, delivered time, computed turnaround (h or d). Below: **Open Drive folder** link, or an inline "+ Add Drive folder link" input (`PATCH /api/orders/{id}/drive-link` — also advances `booked_in → scanning`).
3. **Border Scans card** (only when the order has the border-scan add-on) — status chip `pending / processing / complete / failed`; while `processing` the page auto-refreshes every 10 s. `complete` shows the Bordered Scans folder link; `failed` shows a **Retry** button (`POST /api/orders/{id}/retry-border`).
4. **Rolls list** — one row per roll: checkbox, twin check with **inline pencil-edit** (4-digit validation; saves via `PATCH /api/rolls/{roll_id}/twin-check`; 409 conflicts shown as a toast; a reminder toast tells staff to rename any already-uploaded Inbox folder), service type, "Blank" badge, status chip (rolls in `archived` display as "delivered" to staff). Selecting rolls reveals **Mark N blank** (`POST /api/orders/{id}/mark-blank`).
5. **Activity log** — the order's audit trail (`GET /api/orders/{id}/events`): description, actor, timestamp.

### Sidebar
1. **Update Status** — buttons for the allowed next statuses of the current status (`PATCH /api/orders/{id}/status`).
2. **Email panel** —
   - **Notify: Negatives Ready** (all rolls Dev-only) or **Notify: Prints Ready** (print-only) for orders that never pass through the Drive watcher; success marks the order delivered and shows a toast.
   - **Resend Email** — prominent red variant when the last send failed, subtle variant on delivered orders.
   - Status readout for the three tracked emails: Delivery / Blank notice / Print ready.
3. **Admin — Reset Twin Checks** (only when the order has archived/released twins) — re-locks twin numbers with a confirm dialog (`POST /api/orders/{id}/reset-twins`), for orders delivered by mistake.

## States
- Loading and "Order not found" states; toast notifications (5 s) for email/twin/rescan actions.

## Known gaps (as of 2026-07-04)
- **Status vocabulary drift:** the `NEXT_STATUSES` map and chip styles still use the pre-migration-003 statuses (`booked → processing → scanned → print_ready`). Orders in the current statuses (`inbound`, `booked_in`, `scanning`) have no entry, so the **Update Status panel doesn't render for them**, and their chips fall back to grey.
- Several actions use raw `fetch('/api/…')` instead of the shared Axios client: they miss the JWT header (`reset-twins` and `retry-border` therefore get 401 from the authenticated orders router) and rely on a same-origin `/api` proxy rather than `VITE_API_URL`. The email/rescan calls only work because those routers are currently unauthenticated. Should be migrated to `lib/api.ts`.
