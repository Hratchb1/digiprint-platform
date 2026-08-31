-- ============================================================
-- 009_rollback.sql
-- ============================================================
-- ⚠ DESTRUCTIVE. Reverses 009_twin_check_allocation.sql in full.
--
-- This is for a FAILED-MIGRATION scenario only — running 009, finding a
-- problem, and needing to cleanly back out before retrying. It is NOT a
-- "turn auto mode off" switch (that's twin_check_sequences.auto_enabled)
-- and NOT a routine maintenance script.
--
-- Running this after 009 has been live for any length of time DROPS EVERY
-- ALLOCATED TWIN CHECK, EVERY PRINT JOB, AND EVERY RESCAN LINK ever
-- recorded — twin_checks, twin_check_sequences, print_jobs, and the
-- rescan_of_order_id/rescan_display_suffix linkage all disappear
-- permanently, with no export step in this script. If 009 has been in use
-- for real bookings (not just the smoke tests in its own VERIFY section),
-- export whatever you need from those tables BEFORE running this —
-- there is no undo for this script.
--
-- REVIEW BEFORE RUNNING. Run manually in the Supabase SQL Editor, exactly
-- like 009 itself — not applied automatically.
--
-- WHAT THIS DELIBERATELY DOES NOT DO
-- -------------------------------------
-- 1. Does NOT delete the store_settings rows 009 seeded. 009 found that
--    table at 0 rows and seeded one per active store — by the time this
--    rollback might run, those rows may hold real config (drive_config-
--    adjacent settings, review URLs, etc. — this table predates 009 and
--    carries more than just the label/printer columns 009 added). This
--    script only drops the 6 columns 009 added to that table; the rows
--    and every pre-existing column on them are untouched.
-- 2. Does NOT revert the sku_map service_type/film_type/category values
--    009 restored on the 5 twin-check SKUs (and set on the 5 non-flagged
--    ones). sku_map had 0 rows before 009 ran — these 10 rows are net-new,
--    and their enrichment columns are the ONLY reason pronto_sync's
--    enrichment currently works at all for those SKUs (see 009's own
--    header note: sku_map being empty broke enrichment for the whole
--    catalog; 009 incidentally fixed it for these 10 as a side effect of
--    touching the rows for twin-check purposes). Deleting these rows or
--    nulling those columns back out would re-break Pronto enrichment for
--    them — a strictly worse state than doing nothing. This script only
--    drops the two twin-check-specific columns (requires_twin_check,
--    process_code); sku_code/product_name/service_type/film_type/category
--    on all 10 rows are left exactly as 009 left them.
--
-- ORDER — WHY THIS DOESN'T MATCH A NAIVE READING OF "reverse 009 top to
-- bottom"
-- ----------------------------------------------------------------------
-- rolls.twin_check_id references twin_checks(id); rolls.process_code and
-- sku_map.process_code reference process_codes(code). Postgres refuses to
-- DROP TABLE twin_checks / process_codes while those columns' FK
-- constraints still exist. So despite "drop the tables" reading first
-- conceptually, the columns that reference those tables have to be
-- dropped FIRST in actual execution — DROP COLUMN removes the column's
-- constraints along with it, no separate DROP CONSTRAINT needed. Section
-- numbers below are grouped for readability, not literal execution order;
-- follow the script top to bottom as written.
-- ============================================================


-- ============================================================
-- 1. PRE-FLIGHT — find rolls an abandoned auto-mode booking left pending
-- ============================================================
-- rolls.twin_check is nullable under 009 (a pending auto-mode roll has no
-- number yet). Restoring NOT NULL below will FAIL if any row is still
-- NULL — i.e. an order was created (POST /orders with pending rolls) but
-- allocate was never called or never succeeded (network failure, staff
-- abandoned the booking, etc. — see twin_check_service.allocate_for_order
-- and IntakePage's pendingOrder retry-safety logic, which exists
-- precisely because this can happen).
--
-- Run this and read the result before proceeding:
SELECT id, order_id, store_id, created_at, service_type, process_code
FROM rolls
WHERE twin_check IS NULL;

-- DECISION — documented here, not automated. There is no safe default to
-- backfill: inventing a twin check number for these rows is exactly the
-- transcription-error class of bug this whole feature exists to prevent,
-- rollback is not an exception to that rule.
--
--   If the result set above is EMPTY: nothing to decide, proceed.
--
--   If it is NOT empty, each row is a real physical roll sitting in an
--   order with no number. Options, in order of preference:
--     a. Give it a real number first, through the existing app (manual
--        twin-check entry on that order, or PATCH /rolls/{id}/twin-check),
--        before running this rollback at all.
--     b. If the parent order was never physically real (an abandoned
--        test/duplicate booking), discard the order through the existing
--        Discard flow — its rolls go with it — before running this
--        rollback.
--     c. If rollback must proceed regardless and neither (a) nor (b) is
--        possible, the only remaining option is deleting the affected
--        roll row(s) outright:
--          DELETE FROM rolls WHERE twin_check IS NULL;
--        This is NOT executed by this script. It permanently discards the
--        roll record (not just the twin check) and must be a deliberate,
--        separate command run by a human who has looked at the SELECT
--        result above, not something this rollback does on your behalf.
--
-- The ALTER TABLE in step 4 below will simply error out with a standard
-- Postgres "column contains null values" message if any NULL rows remain
-- at that point — that failure is the safety net, not a bug to work around.


-- ============================================================
-- 2. Drop columns that hold FKs INTO twin_checks / process_codes
-- ============================================================
-- Must run before dropping those tables (see the ORDER note above).
ALTER TABLE rolls
  DROP COLUMN IF EXISTS twin_check_id,
  DROP COLUMN IF EXISTS process_code;

ALTER TABLE sku_map
  DROP COLUMN IF EXISTS requires_twin_check,
  DROP COLUMN IF EXISTS process_code;
-- sku_map row data (sku_code, product_name, service_type, film_type,
-- category) is untouched — see "WHAT THIS DELIBERATELY DOES NOT DO" above.


-- ============================================================
-- 3. Drop the other columns 009 added — no FK-ordering constraint
-- ============================================================
ALTER TABLE orders
  DROP COLUMN IF EXISTS rescan_of_order_id,
  DROP COLUMN IF EXISTS rescan_display_suffix;

ALTER TABLE store_settings
  DROP COLUMN IF EXISTS label_printer_ip,
  DROP COLUMN IF EXISTS label_printer_dpi,
  DROP COLUMN IF EXISTS label_width_mm,
  DROP COLUMN IF EXISTS label_height_mm,
  DROP COLUMN IF EXISTS label_copies,
  DROP COLUMN IF EXISTS print_agent_token;
-- store_settings ROWS are untouched — see "WHAT THIS DELIBERATELY DOES
-- NOT DO" above. Do not add a DELETE FROM store_settings here.


-- ============================================================
-- 4. Drop the indexes 009 created directly on tables that survive
-- ============================================================
-- idx_twin_checks_order, idx_twin_checks_roll, idx_twin_checks_store_
-- number_active (on twin_checks) and idx_print_jobs_store_status (on
-- print_jobs) are NOT dropped explicitly here — DROP TABLE in step 6
-- removes them automatically along with their parent table. Only the two
-- indexes 009 put on tables that are NOT being dropped need an explicit
-- DROP INDEX:
DROP INDEX IF EXISTS idx_rolls_store_twin_active;
DROP INDEX IF EXISTS idx_orders_rescan_of;


-- ============================================================
-- 5. Restore rolls.twin_check NOT NULL
-- ============================================================
-- See the PRE-FLIGHT section (step 1) above — this fails loudly if any
-- row is still NULL, which is the intended behaviour, not a bug.
ALTER TABLE rolls ALTER COLUMN twin_check SET NOT NULL;


-- ============================================================
-- 6. Drop the allocate_twin_checks() function
-- ============================================================
DROP FUNCTION IF EXISTS allocate_twin_checks(UUID, INT);


-- ============================================================
-- 7. Drop the 4 tables 009 created
-- ============================================================
-- Safe now — the only inbound FKs referencing them (rolls.twin_check_id,
-- rolls.process_code, sku_map.process_code) were already dropped in step
-- 2. No FK relationships exist between these four tables themselves, so
-- their relative order here doesn't matter; kept in the order requested.
-- Each DROP TABLE also removes that table's own indexes and RLS policies
-- automatically — no separate DROP INDEX / DROP POLICY needed for
-- twin_checks / print_jobs (see step 4's note) or for the service_role
-- policies 009 created on all 4 tables.
--
-- ⚠ This is the destructive step — every allocated twin check, print job,
-- and sequence position ever recorded is gone after this runs. See the
-- header warning.
DROP TABLE IF EXISTS print_jobs;
DROP TABLE IF EXISTS twin_checks;
DROP TABLE IF EXISTS twin_check_sequences;
DROP TABLE IF EXISTS process_codes;


-- ============================================================
-- VERIFY AFTER RUNNING
-- ============================================================
-- 1. \d rolls          -- twin_check is NOT NULL again, twin_check_id and
--                          process_code columns gone
-- 2. \d orders          -- rescan_of_order_id / rescan_display_suffix gone
-- 3. \d sku_map         -- requires_twin_check / process_code gone; row
--                          count and service_type/film_type/category on
--                          the 10 rows 009 touched UNCHANGED — confirm
--                          with: SELECT sku_code, service_type, film_type
--                          FROM sku_map ORDER BY sku_code;
-- 4. \d store_settings  -- the 6 label/printer columns gone; row count
--                          UNCHANGED from before this script ran
-- 5. SELECT * FROM pg_tables WHERE tablename IN
--      ('twin_checks','twin_check_sequences','print_jobs','process_codes');
--    -- zero rows — all 4 tables gone
-- 6. SELECT proname FROM pg_proc WHERE proname = 'allocate_twin_checks';
--    -- zero rows
-- 7. Re-run the Supabase advisor — no dangling RLS/policy warnings for
--    any of the 4 dropped tables (they're gone, so there's nothing to warn
--    about; this just confirms the drop was clean).
-- ============================================================
