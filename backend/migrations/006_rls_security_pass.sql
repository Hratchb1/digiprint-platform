-- ============================================================
-- 006_rls_security_pass.sql
-- ============================================================
-- REVIEW BEFORE RUNNING. Not applied automatically — run manually
-- in the Supabase SQL Editor after review, per the 10 Aug 2026
-- security audit.
--
-- WHAT THIS FIXES
-- ----------------
-- Supabase's advisor flagged 11 tables with RLS fully disabled:
--   users, customers, order_events, vendors, vendor_releases,
--   sku_map, pronto_cache, drive_config, drive_watcher_log,
--   store_settings, promotions
-- With RLS off, these tables are unconditionally exposed to the
-- anon and authenticated Postgres roles that PostgREST uses for
-- direct Supabase client requests — including drive_config, which
-- holds Gmail app passwords in plaintext (gmail_app_password) and
-- users, which holds bcrypt password hashes.
--
-- AUDIT FINDING THAT SHAPES THE POLICY DESIGN (see 2a)
-- ------------------------------------------------------
-- The frontend (frontend/src/) has no @supabase/supabase-js
-- dependency, no createClient() call, and no VITE_SUPABASE_* env
-- var anywhere — grep across frontend/src for "supabase" and
-- "anon" both come back empty. Every frontend request goes through
-- Axios to VITE_API_URL (the FastAPI backend), authenticated with
-- this app's own JWT (backend/app/core/auth.py — python-jose,
-- HS256, bcrypt), not Supabase Auth. The backend itself talks to
-- Supabase using SUPABASE_SERVICE_KEY (service_role), which has
-- Postgres's BYPASSRLS attribute and is therefore unaffected by
-- anything in this migration — enabling RLS here cannot break the
-- backend.
--
-- One consequence of that finding: because this app never issues
-- or verifies Supabase Auth JWTs, nothing ever legitimately
-- connects to Supabase as the `authenticated` Postgres role either
-- — that role only becomes real once something calls Supabase
-- Auth directly. So this migration does NOT add authenticated-role
-- read/write policies; granting access to a role nothing currently
-- uses would just be unreviewed surface area. If a future feature
-- adds a direct Supabase client (e.g. a realtime subscription),
-- add narrowly-scoped authenticated policies at that time, informed
-- by what that feature actually needs.
--
-- POLICY SHAPE (same on all 11 tables)
-- --------------------------------------
-- 1. Enable RLS.
-- 2. Grant service_role an explicit FOR ALL policy. Technically
--    redundant (service_role bypasses RLS outright), but 001_initial.sql
--    already established this explicit-policy pattern for stores/
--    orders/rolls, and keeping it consistent makes the access model
--    self-documenting from the policy list alone rather than relying
--    on institutional knowledge of BYPASSRLS.
-- 3. No policy for anon or authenticated — once RLS is enabled, the
--    absence of a permissive policy for a role means that role sees
--    zero rows by default. This is the actual fix: today, RLS is off,
--    so anon (the key shipped in any public client bundle) can read
--    and write every row in these tables. After this migration, anon
--    reads/writes nothing here.
--
-- ORDER: most sensitive first (drive_config, users, customers), then
-- the remaining 8 in the order the advisor listed them.
-- ============================================================


-- ── drive_config ── Gmail app passwords + Drive folder IDs per store
ALTER TABLE drive_config ENABLE ROW LEVEL SECURITY;
CREATE POLICY "service_role_full_access_drive_config"
    ON drive_config FOR ALL
    TO service_role
    USING (true) WITH CHECK (true);

-- ── users ── bcrypt password hashes, role, store scoping
ALTER TABLE users ENABLE ROW LEVEL SECURITY;
CREATE POLICY "service_role_full_access_users"
    ON users FOR ALL
    TO service_role
    USING (true) WITH CHECK (true);

-- ── customers ── name/email/phone/account PII
ALTER TABLE customers ENABLE ROW LEVEL SECURITY;
CREATE POLICY "service_role_full_access_customers"
    ON customers FOR ALL
    TO service_role
    USING (true) WITH CHECK (true);

-- ── order_events ── audit trail of every status change/action
ALTER TABLE order_events ENABLE ROW LEVEL SECURITY;
CREATE POLICY "service_role_full_access_order_events"
    ON order_events FOR ALL
    TO service_role
    USING (true) WITH CHECK (true);

-- ── vendors ── B2B vendor directory (contact details)
ALTER TABLE vendors ENABLE ROW LEVEL SECURITY;
CREATE POLICY "service_role_full_access_vendors"
    ON vendors FOR ALL
    TO service_role
    USING (true) WITH CHECK (true);

-- ── vendor_releases ── B2B print batch ("drop") tracking
ALTER TABLE vendor_releases ENABLE ROW LEVEL SECURITY;
CREATE POLICY "service_role_full_access_vendor_releases"
    ON vendor_releases FOR ALL
    TO service_role
    USING (true) WITH CHECK (true);

-- ── sku_map ── Pronto SKU → service_type/film_type mapping
ALTER TABLE sku_map ENABLE ROW LEVEL SECURITY;
CREATE POLICY "service_role_full_access_sku_map"
    ON sku_map FOR ALL
    TO service_role
    USING (true) WITH CHECK (true);

-- ── pronto_cache ── raw Pronto sales data incl. customer name/email/phone
ALTER TABLE pronto_cache ENABLE ROW LEVEL SECURITY;
CREATE POLICY "service_role_full_access_pronto_cache"
    ON pronto_cache FOR ALL
    TO service_role
    USING (true) WITH CHECK (true);

-- ── drive_watcher_log ── Drive polling activity log
ALTER TABLE drive_watcher_log ENABLE ROW LEVEL SECURITY;
CREATE POLICY "service_role_full_access_drive_watcher_log"
    ON drive_watcher_log FOR ALL
    TO service_role
    USING (true) WITH CHECK (true);

-- ── store_settings ── per-store policy config (currently empty — also
--    gates v4 email branding fields; see the held-back Bondi seed item)
ALTER TABLE store_settings ENABLE ROW LEVEL SECURITY;
CREATE POLICY "service_role_full_access_store_settings"
    ON store_settings FOR ALL
    TO service_role
    USING (true) WITH CHECK (true);

-- ── promotions ── marketing banner content for email templates
ALTER TABLE promotions ENABLE ROW LEVEL SECURITY;
CREATE POLICY "service_role_full_access_promotions"
    ON promotions FOR ALL
    TO service_role
    USING (true) WITH CHECK (true);


-- ============================================================
-- BONUS (not part of the flagged 11, found during this audit):
-- email_log, order_activity, refund_warnings, and roll_audit_log
-- already have RLS enabled but carry zero policies — safe today
-- only because the backend uses service_role (BYPASSRLS), but the
-- advisor still flags "RLS enabled, no policy" as worth closing out
-- explicitly rather than relying on that being implicit. Same
-- shape: service_role only, no anon/authenticated policy.
-- ============================================================

CREATE POLICY "service_role_full_access_email_log"
    ON email_log FOR ALL
    TO service_role
    USING (true) WITH CHECK (true);

CREATE POLICY "service_role_full_access_order_activity"
    ON order_activity FOR ALL
    TO service_role
    USING (true) WITH CHECK (true);

CREATE POLICY "service_role_full_access_refund_warnings"
    ON refund_warnings FOR ALL
    TO service_role
    USING (true) WITH CHECK (true);

CREATE POLICY "service_role_full_access_roll_audit_log"
    ON roll_audit_log FOR ALL
    TO service_role
    USING (true) WITH CHECK (true);


-- ============================================================
-- VERIFY AFTER RUNNING
-- ============================================================
-- 1. Re-run the Supabase advisor (or call get_advisors via the
--    Supabase MCP tool) — the 11 "RLS Disabled in Public" ERROR
--    findings and the 4 "RLS Enabled No Policy" INFO findings
--    listed above should all be gone.
-- 2. Smoke-test the backend against this project (staff login,
--    order list, intake) to confirm nothing regressed — it
--    shouldn't, since service_role bypasses RLS entirely, but
--    verify live rather than assume.
-- 3. NOT covered by this migration (found during the same audit,
--    flagged separately by the advisor, left for a follow-up pass):
--      - 3 views (pronto_order_summary, v_order_summary,
--        v_overdue_orders) are defined SECURITY DEFINER — ERROR
--        level. Worth a dedicated look since a SECURITY DEFINER
--        view runs with the view creator's privileges rather than
--        the querying role's, regardless of the RLS policies above.
--      - Function update_drive_config_timestamp has a mutable
--        search_path — WARN level, standard fix is
--        `SET search_path = public` (or empty) on the function.
-- ============================================================
