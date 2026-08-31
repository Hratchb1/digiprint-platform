# RollCall — Session 2: Security (Runbook + Claude Code Brief)

**Prepared 11 Aug 2026.** Follows Session 1 (store-scoping enforcement, shipped). Source plan: `digiDirect HQ/RollCall_Next_Coding_Sessions.md` (Session 2). Two parts: **Part 1** is your manual work in Supabase (no code). **Part 2** is a Claude Code task for the advisor follow-ups.

Real backend entry point: `app/main.py` (`uvicorn app.main:app` from `backend/`). Credentials live only in `backend/.env` (read by `app/core/config.py`). The frontend has **no** Supabase keys — it only talks to the backend via `VITE_API_URL`. Not on Railway yet, so rotation is local `.env` + restart only.

**Do the three parts in this order:** RLS migration → credential rotation → Code advisor fixes. RLS is zero-downtime; rotation causes a logout; the Code fixes can follow anytime.

---

## Part 1A — Run the RLS migration (safe, no downtime)

Why it's safe: the backend connects with `SUPABASE_SERVICE_KEY` (service_role, which has `BYPASSRLS`), so enabling RLS cannot break it. The fix closes off the `anon` key — which is shipped in any public client bundle — from reading/writing 11 tables that currently have RLS **off**, including `drive_config` (Gmail app passwords in plaintext) and `users` (bcrypt hashes).

Steps:
1. Supabase Dashboard → **SQL Editor** → New query.
2. Paste the full contents of `backend/migrations/006_rls_security_pass.sql` and **Run**. (Review it first — it's heavily commented and self-explanatory.)
3. Verify: re-run the Supabase **Advisor** (Dashboard → Advisors, or the "Security" lint). The 11 *"RLS Disabled in Public"* ERRORs and the 4 *"RLS Enabled No Policy"* INFO findings should all be gone.
4. Smoke-test the live backend: log in (both `master_admin` and `lab.bondi`), load the orders list, do a test intake. Nothing should regress (service_role bypasses RLS), but verify rather than assume.

---

## Part 1B — Rotate credentials (causes a logout — pick a low-traffic window)

All four values live in `backend/.env`. After changing them, restart uvicorn. **`JWT_SECRET` rotation invalidates every existing token — both your `master_admin` session and the new `lab.bondi` login will need to log in again.** Gmail app passwords live in Supabase `drive_config`, not `.env` — **no rotation needed**.

Rotate each, update `backend/.env`, then restart:

1. **`JWT_SECRET`** — generate a fresh random hex (`openssl rand -hex 32`) and replace it. (The old one was previously exposed in git history — this is the important one.)
2. **`SUPABASE_KEY` (anon)** and **`SUPABASE_SERVICE_KEY`** — Supabase Dashboard → Settings → API → roll/reveal keys; paste the current values (or roll them if you want fully fresh keys).
3. **DB password** (inside `DATABASE_URL`) — Settings → Database → reset password; update the password portion of the `postgresql+asyncpg://...` connection string.
4. Restart the backend (`uvicorn app.main:app` in the backend PowerShell window with venv active). Confirm both logins work with the new token.

> If/when you deploy to Railway (Stage 5), these same four values must also be set in the Railway service's environment variables — not just local `.env`.

---

## Part 2 — Claude Code task: advisor follow-ups (the 3 views + 1 function)

These were flagged by the same 10 Aug audit but left out of migration 006 for a dedicated pass (see 006 lines 187–197). Write a new `backend/migrations/007_definer_and_search_path.sql`:

1. **3 `SECURITY DEFINER` views (ERROR level):** `pronto_order_summary`, `v_order_summary`, `v_overdue_orders`. A `SECURITY DEFINER` view runs with the *creator's* privileges, bypassing the RLS policies just added. Recreate each with `security_invoker = on` so it runs as the querying role. Since nothing queries Supabase as `anon`/`authenticated` (frontend uses the backend API, backend uses service_role), this is low-risk — but Code should first fetch each view's current definition (`pg_get_viewdef`) and preserve it exactly, only changing the security mode.
2. **1 mutable-search_path function (WARN level):** `update_drive_config_timestamp`. Add `SET search_path = ''` (or `= public` if it references unqualified public objects) to the function definition.

Process (per standing preferences):
- Author `007_...sql` as a full file; have Code explain each statement and show the current view definitions **before** Hratch runs it in the Supabase SQL Editor.
- After running: re-run the advisor — the 3 SECURITY DEFINER ERRORs + 1 search_path WARN should clear.
- Smoke-test any screen that reads those views (dashboard/overdue/order summary) to confirm no regression.

---

## Definition of done
- Advisor security lint is clean (0 of the RLS/DEFINER/search_path findings above).
- Both logins work after `JWT_SECRET` rotation.
- Dashboard + orders still render (views recreated cleanly).
- Migration 007 committed + pushed; Session Logs entry added in Notion (WORK → RollCall → 📓 Session Logs).

## Working constraints (standing)
- Full file replacements, not partial diffs. Incremental, approval at each file.
- Show SQL before it's run in Supabase; Hratch runs all Supabase SQL manually.
- venv active; run from `backend/`; both PowerShell windows stay open.
