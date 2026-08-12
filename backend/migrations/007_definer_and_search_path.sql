-- ============================================================
-- 007_definer_and_search_path.sql
-- ============================================================
-- REVIEW BEFORE RUNNING. Not applied automatically — run manually
-- in the Supabase SQL Editor after review, per the 10 Aug 2026
-- security audit. Follow-up to 006_rls_security_pass.sql (see its
-- footnote, lines 187–197) — these 4 findings were left out of 006
-- for a dedicated pass.
--
-- WHAT THIS FIXES
-- ----------------
-- 1. Three views are defined SECURITY DEFINER (ERROR level):
--      pronto_order_summary, v_order_summary, v_overdue_orders
--    A SECURITY DEFINER view runs with the *view creator's*
--    privileges, not the querying role's — meaning it bypasses the
--    RLS policies just added in 006, regardless of who or what is
--    actually running the query. Fix: flip each view's
--    security_invoker option to on, so it runs as the querying role
--    instead (the Postgres 15+ way to de-DEFINER a view without
--    touching its SQL body at all).
--
-- 2. One function has a mutable search_path (WARN level):
--      update_drive_config_timestamp
--    Without a pinned search_path, the function resolves unqualified
--    names using whatever search_path is active at call time — which
--    a sufficiently privileged attacker could manipulate to redirect
--    the function at objects it doesn't expect. Fix: pin
--    search_path = '' on the function. Its body only touches
--    NEW.updated_at (a trigger row field, not schema-resolved) and
--    calls now(), which is pg_catalog and always resolves regardless
--    of search_path — so '' is safe here with no behavior change.
--
-- RISK: LOW. Nothing queries this Supabase project as anon or
-- authenticated (frontend has no Supabase client — see 006's header
-- for the grep confirming this; backend uses service_role, which has
-- BYPASSRLS and ignores view security mode entirely). So flipping
-- security_invoker on cannot change any currently-live query's
-- results — it only closes a gap that would matter if a future
-- direct-Supabase-client feature queried these views as anon/
-- authenticated.
--
-- WHY security_invoker VIA ALTER, NOT CREATE OR REPLACE
-- --------------------------------------------------------
-- Each view's current definition below was fetched live via
-- pg_get_viewdef() (not reconstructed from memory/docs) and is
-- reproduced here for your review only — this migration does NOT
-- replay it through CREATE OR REPLACE. ALTER VIEW ... SET
-- (security_invoker = on) changes only the view's security mode and
-- cannot alter its query in any way, which is a strictly safer
-- operation than retyping the SELECT and hoping it matches exactly.
--
-- ── pronto_order_summary (current definition, for review) ──
--   SELECT sales_order_number, territory, customer_name,
--          email_address, phone_number, pronto_account,
--          sales_rep_name, order_date,
--          json_agg(json_build_object('sku_code', sku_code,
--            'product_name', product_name, 'service_type', service_type,
--            'film_type', film_type, 'scan_resolution', scan_resolution,
--            'category', category, 'shipped_units', shipped_units)
--            ORDER BY category) AS sku_lines,
--          CASE
--            WHEN bool_or(category = 'Developing') AND bool_or(category = 'Scanning')
--                 AND bool_or(category = 'Film Printing') THEN 'Develop + Scan + Print'
--            WHEN bool_or(category = 'Developing') AND bool_or(category = 'Scanning')
--                 THEN 'Develop + Scan'
--            WHEN bool_or(category = 'Developing') AND bool_or(category = 'Film Printing')
--                 THEN 'Develop + Print'
--            WHEN bool_or(category = 'Developing') THEN 'Develop only'
--            WHEN bool_or(category = 'Scanning') THEN 'Scan only'
--            WHEN bool_or(category = 'Film Printing') THEN 'Print only'
--            ELSE 'Unknown'
--          END AS inferred_service_type,
--          sum(CASE WHEN category = 'Developing' THEN shipped_units ELSE 0 END) AS total_rolls,
--          max(synced_at) AS synced_at
--   FROM pronto_cache p
--   GROUP BY sales_order_number, territory, customer_name, email_address,
--            phone_number, pronto_account, sales_rep_name, order_date;
--
-- ── v_order_summary (current definition, for review) ──
--   SELECT o.id, o.order_number, o.order_type, o.status, o.customer_name,
--          o.customer_email, o.account, s.name AS store_name, s.label AS store_label,
--          o.operator_initials, o.email_status, o.drive_order_folder_url,
--          o.is_print_only, o.has_blanks, o.created_at, o.date_scanned, o.date_delivered,
--          count(r.id) AS total_rolls,
--          count(r.id) FILTER (WHERE r.status = 'delivered') AS delivered_rolls,
--          count(r.id) FILTER (WHERE r.is_blank = true) AS blank_rolls,
--          EXTRACT(epoch FROM o.date_delivered - o.created_at) / 3600::numeric AS turnaround_hours
--   FROM orders o
--   JOIN stores s ON o.store_id = s.id
--   LEFT JOIN rolls r ON r.order_id = o.id
--   GROUP BY o.id, s.id;
--
-- ── v_overdue_orders (current definition, for review) ──
--   SELECT id, order_number, order_type, status, customer_name, customer_email,
--          account, store_name, store_label, operator_initials, email_status,
--          drive_order_folder_url, is_print_only, has_blanks, created_at,
--          date_scanned, date_delivered, total_rolls, delivered_rolls,
--          blank_rolls, turnaround_hours
--   FROM v_order_summary
--   WHERE status <> ALL (ARRAY['delivered','archived','cancelled'])
--     AND created_at < (now() - interval '48:00:00')
--   ORDER BY created_at;
--   -- Note: this view selects FROM v_order_summary, so it inherits
--   -- v_order_summary's rows through a normal (invoker-rights) query
--   -- once v_order_summary itself is flipped below. Both are flipped
--   -- for defense in depth — v_overdue_orders being SECURITY DEFINER
--   -- would independently bypass RLS even if v_order_summary weren't.
-- ============================================================


-- ── 1. Flip the 3 SECURITY DEFINER views to SECURITY INVOKER ──
ALTER VIEW pronto_order_summary SET (security_invoker = on);
ALTER VIEW v_order_summary SET (security_invoker = on);
ALTER VIEW v_overdue_orders SET (security_invoker = on);


-- ── 2. Pin update_drive_config_timestamp's search_path ──
-- Reproduces the current body exactly (fetched live via
-- pg_get_functiondef), adding only the SET search_path clause.
CREATE OR REPLACE FUNCTION public.update_drive_config_timestamp()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = ''
AS $function$
BEGIN
  NEW.updated_at = NOW();
  RETURN NEW;
END;
$function$;


-- ============================================================
-- VERIFY AFTER RUNNING
-- ============================================================
-- 1. Re-run the Supabase advisor (or get_advisors via the Supabase
--    MCP tool) — the 3 "Security Definer View" ERRORs and the 1
--    "Function Search Path Mutable" WARN listed above should all be
--    gone.
-- 2. Sanity-check the views still return the same shape/rows:
--      SELECT * FROM v_order_summary LIMIT 5;
--      SELECT * FROM v_overdue_orders LIMIT 5;
--      SELECT * FROM pronto_order_summary LIMIT 5;
--    (Run as service_role via the SQL Editor — service_role owns
--    these objects, so invoker-rights mode should return identical
--    results to before.)
-- 3. Smoke-test any screen that reads these views — dashboard stats,
--    overdue orders list, Pronto order lookup — to confirm no
--    regression.
-- ============================================================
