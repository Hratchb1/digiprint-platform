# RollCall — Session 1: Per-Store Login & Store-Scoping (Claude Code Implementation Brief)

**Prepared 11 Aug 2026 by a Cowork 1a discovery pass against the live backend.** Read this before touching code. Source of the plan: `digiDirect HQ/RollCall_Next_Coding_Sessions.md` (Session 1). This brief supersedes the schema assumptions in that plan — see "Corrections" below.

Real backend entry point: `app/main.py` (`uvicorn app.main:app` from `backend/`). Always commit from `digiprint/`.

---

## Goal

Every login sees and acts on **only its own store's** data. Store logins get the **full app, identical experience** — no reduced permissions — just filtered to their `store_id`. Hratch is the **only** all-stores admin. Build this once for Bondi so adding stores later is "create a user + config rows," no code rework.

---

## Corrections to the original plan (confirmed by 1a discovery)

1. **No schema migration needed.** `users` already has `store_id` (FK `stores.id`, NULL = all stores) and `role`. Do **not** add columns. (`migrations/001_initial.sql`, `app/models/orm.py::User`.)
2. **JWT already carries the claims.** `create_access_token` in `app/api/auth.py` already puts `sub`, `email`, `role`, `store_id`, `initials`, `full_name` in the token. Do **not** rework token issuance.
3. **Role vocabulary is fixed by a DB CHECK constraint** — `role IN ('staff','store_admin','master_admin')`. The plan's `'store'`/`'admin'` are **invalid**. Locked decisions:
   - All-stores admin = **`master_admin`** (Hratch, already set by `seed_admin.py`). **Keep — no rename, no constraint change.**
   - Bondi store login = **`store_admin`**.

**So Session 1 is an ENFORCEMENT pass, not a schema change.**

---

## Current state (what 1a found — the gaps to fix)

- **`GET /api/orders` (list_orders, `app/api/orders.py:68`)** is the only store scoping and it's leaky:
  - It falls back to the token `store_id` **only when the client didn't send `?store_id=`** → a store user can pass `?store_id=<another store>` and see it. Client input overrides token.
  - A non-admin whose token `store_id` is NULL falls through to **all stores**.
- **`GET /api/orders/{id}` (get_order)** — **no store check.** Any logged-in user fetches any order by ID.
- **Every action endpoint has no store-ownership check:** `PATCH /{id}/status`, `/{id}/drive-link`, `POST /{id}/mark-blank`, `/{id}/add-rolls`, `/{id}/reset-twins`, `/{id}/retry-border`, `GET /{id}/events`, `POST /{id}/discard`. (`reset-twins` checks role only.)
- **`GET /api/orders/check/twin` and `/check/order-number`** trust the client `store_id` query param.
- **`/api/dashboard/*`** (`app/api/dashboard.py`: counts, needs_attention, today_activity, performance, workload) have **no store filter** — global numbers for everyone.
- **`stores.py::dashboard/stats`** repeats the same leaky master_admin-bypass pattern as list_orders.
- **`app/api/rolls.py::update_twin_check`** scopes twin-uniqueness to `roll.store_id` but never verifies the caller owns that store.
- **Hygiene:** `app/api/auth.py::login` has leftover `DEBUG` prints logging the email and part of the password hash — delete them.
- **Dead code:** `app/core/auth.py::require_admin` checks `role in ("admin","master_admin")` — `"admin"` is not a valid role; nothing calls this. Clean up if touched.

---

## Implementation plan (do in this order; show step 1 before rolling out)

### Step A — One source-of-truth store-scoping dependency
Add a FastAPI dependency (suggest `app/core/auth.py`) that returns the **effective store_id** from the token:

```
def effective_store_id(current_user) -> UUID | None:
    role = current_user.get("role")
    if role == "master_admin":
        return None            # None = all stores
    sid = current_user.get("store_id")
    if not sid:
        raise HTTPException(403, "Account is not assigned to a store")  # close the NULL hole
    return UUID(sid)
```

Rules:
- **Non-admins: derive store_id from the token only. Ignore any client `?store_id=`.**
- master_admin: `None` = all stores; may optionally pass `?store_id=` to filter to one store.
- A non-admin with NULL store_id gets **403**, never all-stores.

Add a helper to assert ownership of a fetched order:

```
def assert_can_access(order, current_user):
    if current_user.get("role") == "master_admin":
        return
    if str(order.store_id) != current_user.get("store_id"):
        raise HTTPException(404, "Order not found")   # 404, don't leak existence
```

### Step B — Apply to the orders list first (approval gate)
Rewrite `list_orders` to use `effective_store_id` instead of the line-68 logic. For non-admins, the client `store_id` param is ignored (or 403 if it contradicts the token — implementer's call, but must not widen access). **Show Hratch this single endpoint change and the diff before rolling out further.**

### Step C — Roll out to the rest
- `get_order` → after fetch, `assert_can_access`.
- Every action endpoint (`status`, `drive-link`, `mark-blank`, `add-rolls`, `reset-twins`, `retry-border`, `events`, `discard`) → fetch order, `assert_can_access` before mutating. Return 404 on cross-store.
- `check/twin` + `check/order-number` → for non-admins, force store_id from token; ignore/deny mismatched client store_id.
- `rolls.py::update_twin_check` → verify caller owns `roll.store_id`.
- `dashboard.py` endpoints → filter every query by `effective_store_id` (master_admin = all).
- `stores.py::dashboard/stats` → replace leaky pattern with `effective_store_id`.

### Step D — Hygiene
Delete the DEBUG prints in `login`. Optionally fix/remove the dead `require_admin` `"admin"` branch.

---

## 1c — Create the Bondi store account
- Email `lab.bondi@digidirect.com.au`, `role='store_admin'`, `store_id=a90c273e-49ff-4733-b709-31066f2ec503` (Bondi).
- Password via a **secure hash only** — never plaintext. Reuse the `seed_admin.py` bcrypt pattern (add a `seed_store_user.py` or parameterize the existing script). Hratch provides the password interactively.
- Confirm Hratch's own account is `role='master_admin'`, `store_id=NULL`.

## 1d — Verification (must pass)
1. Log in as `lab.bondi` → sees **only** Bondi orders, full functionality.
2. Log in as Hratch (`master_admin`) → sees all stores.
3. As `lab.bondi`, hit another store's order by direct ID on **every** endpoint (`GET /{id}`, each PATCH/POST action) → **server returns 404/403**, not just hidden in the list.
4. As `lab.bondi`, pass `?store_id=<another store>` to list + dashboard → still only Bondi.
5. Dashboard numbers for `lab.bondi` reflect Bondi only.

---

## Working constraints (Hratch's standing preferences)
- **Full file replacements**, not partial diffs (partial diffs cause indentation errors).
- Step-by-step; **incremental testing with approval at each file** before moving on.
- **Show the orders-list change first** (Step B) before rolling out.
- No store names or IDs hardcoded in logic — Bondi's UUID appears only in the 1c seed.
- Backend uses service_role (bypasses RLS), so this scoping is enforced in **application code**; RLS migration 006 (Session 2) is defence-in-depth only.
- venv active; run from `backend/`; both PowerShell windows (frontend + backend) stay open.
- End of session: GitHub push + add a Session Logs entry in Notion (WORK → RollCall → Session Logs).
