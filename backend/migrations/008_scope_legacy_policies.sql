-- ============================================================
-- 008_scope_legacy_policies.sql
-- ============================================================
-- REVIEW BEFORE RUNNING. Not applied automatically — run manually
-- in the Supabase SQL Editor after review. Closes the last 3
-- Security Advisor findings after 006 + 007 (which cleared all
-- ERROR + INFO items; these 3 are WARN level).
--
-- WHAT THIS FIXES
-- ----------------
-- The Security Advisor flags 3 "RLS Policy Always True" warnings on
-- public.stores, public.orders, public.rolls.
--
-- Root cause: migration 001_initial.sql created these policies:
--     CREATE POLICY "Service role full access - stores"
--         ON stores FOR ALL USING (true);
--     (same for orders, rolls)
-- They are NAMED "Service role full access" but have no `TO service_role`
-- clause — so they default to `TO public`, i.e. they apply to EVERY
-- Postgres role including `anon` and `authenticated`. Combined with
-- USING (true), that means the anon key (shipped in any public client
-- bundle) can read/write every row in stores, orders and rolls
-- directly, bypassing the app's store-scoping.
--
-- The 006 tables don't trip this warning because 006 scoped its
-- policies `TO service_role` correctly. This migration brings these 3
-- legacy policies in line with that same pattern.
--
-- RISK: LOW / NONE for the running app. The backend uses
-- SUPABASE_SERVICE_KEY (service_role, BYPASSRLS) and the frontend has
-- no Supabase client (see 006 header) — so nothing legitimately
-- accesses these tables as anon/authenticated today. This only removes
-- access from roles nothing currently uses. Same shape and reasoning
-- as 006.
--
-- ORDER: drop each permissive policy, recreate scoped to service_role.
-- ============================================================


-- ── stores ──
DROP POLICY IF EXISTS "Service role full access - stores" ON stores;
CREATE POLICY "service_role_full_access_stores"
    ON stores FOR ALL
    TO service_role
    USING (true) WITH CHECK (true);

-- ── orders ──
DROP POLICY IF EXISTS "Service role full access - orders" ON orders;
CREATE POLICY "service_role_full_access_orders"
    ON orders FOR ALL
    TO service_role
    USING (true) WITH CHECK (true);

-- ── rolls ──
DROP POLICY IF EXISTS "Service role full access - rolls" ON rolls;
CREATE POLICY "service_role_full_access_rolls"
    ON rolls FOR ALL
    TO service_role
    USING (true) WITH CHECK (true);


-- ============================================================
-- VERIFY AFTER RUNNING
-- ============================================================
-- 1. Re-run the Security Advisor — the 3 "RLS Policy Always True"
--    warnings on stores/orders/rolls should be gone (0 errors,
--    0 warnings, 0 info).
-- 2. Smoke-test the backend (login, order list, intake) — no
--    regression expected; service_role bypasses RLS entirely.
-- ============================================================
