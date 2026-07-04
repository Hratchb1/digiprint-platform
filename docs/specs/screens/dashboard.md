# Screen: Dashboard

**Audience:** all readers · **Route:** `/dashboard` (default after login) · **Component:** `frontend/src/pages/DashboardPage.tsx`

## Purpose
At-a-glance operational health for a store (or all stores for master admins): today's volume, 30-day totals, overdue work, and the most recent orders.

## Who sees what
- **Staff / store admin:** their own store only (the backend pins stats and lists to the token's `store_id`).
- **Master admin:** an extra **store selector** appears ("All Stores" or a specific store).

## Layout
1. **Header** — date, store selector (master admin only), manual refresh button.
2. **Today bar** — live count of orders and rolls booked today.
3. **Stat cards** (30-day window, from `GET /api/dashboard/stats`):
   - Orders (30d) — highlighted card
   - Delivered
   - Pending — orders in `booked_in` or `scanning`
   - Overdue — pending orders older than 48 hours (card label gains a ⚠ when non-zero)
   - Avg Turnaround — booking → delivery, shown as hours or days
   - Blank Rolls — orders containing blanks
4. **Recent Orders** — last 10 orders (`GET /api/orders?limit=20`, first 10 shown): order number, customer, store, status chip, roll count, relative time. Each row links to the Order Detail screen. "View all" links to `/orders`.

## States
- Per-widget loading placeholders ("…"), "No orders yet" empty state.
- Data auto-caches for 30 s (React Query); the refresh button forces a refetch.

## Known gaps (as of 2026-07-04)
- The status chip colour map still uses the **old** status names (`booked`, `processing`, `scanned`, `print_ready`, `blank`). Orders in the new statuses (`inbound`, `booked_in`, `scanning`, `cancelled`, `discarded`) render with the neutral grey fallback style rather than a dedicated colour.
