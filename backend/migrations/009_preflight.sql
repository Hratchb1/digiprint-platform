-- ============================================================
-- 009_preflight.sql
-- ============================================================
-- Read-only. Paste into the Supabase SQL Editor and run BEFORE
-- 009_twin_check_allocation.sql. Every check below targets an assumption
-- that migration makes silently — if any of them don't hold, 009 fails
-- partway through, not at the start.
--
-- Reads top to bottom as one result set. Each row: a check name, PASS /
-- FAIL / WARN, and a plain-language detail — no interpretation needed.
-- A single FAIL means fix that first and re-run this script; 009 is not
-- safe to run yet. A WARN does not block 009 (it's already written to be
-- idempotent against a partial prior run — IF NOT EXISTS / ADD COLUMN IF
-- NOT EXISTS / ON CONFLICT DO NOTHING throughout) but tells you why some
-- of its INSERT ... ON CONFLICT DO UPDATE branches might update existing
-- rows instead of inserting fresh ones.
-- ============================================================

WITH

-- ── 1. store_settings: any NOT NULL column with no default? ──────────────
-- 009 does `INSERT INTO store_settings (store_id) SELECT id FROM stores
-- WHERE is_active` — every column other than store_id is left to its
-- default. If any column is NOT NULL with no default, that INSERT fails
-- immediately. store_id itself is excluded from this check — it's NOT
-- NULL by design and is the one column 009's INSERT does supply.
store_settings_missing_defaults AS (
  SELECT column_name
  FROM information_schema.columns
  WHERE table_schema = 'public'
    AND table_name = 'store_settings'
    AND is_nullable = 'NO'
    AND column_default IS NULL
    AND column_name <> 'store_id'
),

-- ── 2. sku_map.sku_code: backed by a unique index? ────────────────────────
-- Every sku_map INSERT in 009 uses `ON CONFLICT (sku_code) DO UPDATE`.
-- Postgres's ON CONFLICT matches against ANY unique index on exactly that
-- column set — it does not have to be backed by a formal UNIQUE/PRIMARY
-- KEY constraint. Checking information_schema.table_constraints alone
-- is NOT sufficient: this environment's sku_map.sku_code is unique via a
-- plain index (sku_map_sku_code_key) that doesn't register as a
-- table_constraints row at all — an earlier version of this check used
-- table_constraints only and produced a false FAIL against this exact
-- table. Verified against the live schema before writing it this way.
sku_code_unique_index AS (
  SELECT ix.relname AS index_name
  FROM pg_index i
  JOIN pg_class t  ON t.oid = i.indrelid
  JOIN pg_class ix ON ix.oid = i.indexrelid
  JOIN pg_namespace n ON n.oid = t.relnamespace
  WHERE n.nspname = 'public'
    AND t.relname = 'sku_map'
    AND i.indisunique
    AND i.indkey::text = (
      SELECT attnum::text FROM pg_attribute WHERE attrelid = t.oid AND attname = 'sku_code'
    )
),

-- ── 3. stores.is_active exists? ───────────────────────────────────────────
-- Used in `WHERE is_active` twice — seeding twin_check_sequences and
-- seeding store_settings. Both fail (column does not exist) without it.
stores_is_active AS (
  SELECT data_type
  FROM information_schema.columns
  WHERE table_schema = 'public' AND table_name = 'stores' AND column_name = 'is_active'
),

-- ── 4a. Do any of 009's new TABLES already exist? ─────────────────────────
existing_tables AS (
  SELECT tablename
  FROM pg_tables
  WHERE schemaname = 'public'
    AND tablename IN ('process_codes', 'twin_check_sequences', 'twin_checks', 'print_jobs')
),

-- ── 4b. Do any of 009's new COLUMNS already exist? ────────────────────────
existing_columns AS (
  SELECT table_name, column_name
  FROM information_schema.columns
  WHERE table_schema = 'public'
    AND (
      (table_name = 'sku_map'        AND column_name IN ('requires_twin_check', 'process_code'))
      OR (table_name = 'rolls'          AND column_name IN ('twin_check_id', 'process_code'))
      OR (table_name = 'orders'         AND column_name IN ('rescan_of_order_id', 'rescan_display_suffix'))
      OR (table_name = 'store_settings' AND column_name IN (
            'label_printer_ip', 'label_printer_dpi', 'label_width_mm',
            'label_height_mm', 'label_copies', 'print_agent_token'
          ))
    )
),

-- ── 4c. Does allocate_twin_checks(uuid, int) already exist? ──────────────
existing_function AS (
  SELECT p.proname
  FROM pg_proc p
  JOIN pg_namespace n ON n.oid = p.pronamespace
  WHERE n.nspname = 'public'
    AND p.proname = 'allocate_twin_checks'
    AND pg_get_function_identity_arguments(p.oid) = 'p_store_id uuid, p_count integer'
),

-- ── 4d. Do any of 009's new INDEXES already exist? ────────────────────────
existing_indexes AS (
  SELECT indexname
  FROM pg_indexes
  WHERE schemaname = 'public'
    AND indexname IN (
      'idx_twin_checks_order', 'idx_twin_checks_roll', 'idx_twin_checks_store_number_active',
      'idx_rolls_store_twin_active', 'idx_print_jobs_store_status', 'idx_orders_rescan_of'
    )
),

-- Postgres rejects an expression in ORDER BY directly on a UNION ALL
-- ("only result column names can be used") — wrap it in one more CTE so
-- the final SELECT can order by a CASE expression.
results AS (
SELECT 1 AS ord, check_name, status, detail FROM (
  SELECT
    'store_settings: NOT NULL columns without defaults' AS check_name,
    CASE WHEN count(*) = 0 THEN 'PASS' ELSE 'FAIL' END AS status,
    CASE WHEN count(*) = 0
      THEN 'None found — the seed INSERT (store_id only) will succeed'
      ELSE 'Blocks the seed INSERT — add a default or make nullable: '
           || string_agg(column_name, ', ')
    END AS detail
  FROM store_settings_missing_defaults
) x

UNION ALL
SELECT 2, check_name, status, detail FROM (
  SELECT
    'sku_map.sku_code is backed by a unique index' AS check_name,
    CASE WHEN count(*) > 0 THEN 'PASS' ELSE 'FAIL' END AS status,
    CASE WHEN count(*) > 0
      THEN 'Found: ' || string_agg(index_name, ', ')
      ELSE 'No unique index on sku_map.sku_code — every "ON CONFLICT (sku_code)" '
           || 'in 009 will error. Add one before running 009.'
    END AS detail
  FROM sku_code_unique_index
) x

UNION ALL
SELECT 3, check_name, status, detail FROM (
  SELECT
    'stores.is_active exists' AS check_name,
    CASE WHEN count(*) > 0 THEN 'PASS' ELSE 'FAIL' END AS status,
    CASE WHEN count(*) > 0
      THEN 'Found, type ' || string_agg(data_type, ', ')
      ELSE 'stores.is_active does not exist — both seed steps ("WHERE is_active") will error'
    END AS detail
  FROM stores_is_active
) x

UNION ALL
SELECT 4, check_name, status, detail FROM (
  SELECT
    'Partial prior run — tables' AS check_name,
    CASE WHEN count(*) = 0 THEN 'PASS' ELSE 'WARN' END AS status,
    CASE WHEN count(*) = 0
      THEN 'None of process_codes / twin_check_sequences / twin_checks / print_jobs exist yet'
      ELSE 'Already exist (not blocking — 009 uses CREATE TABLE IF NOT EXISTS): '
           || string_agg(tablename, ', ')
    END AS detail
  FROM existing_tables
) x

UNION ALL
SELECT 5, check_name, status, detail FROM (
  SELECT
    'Partial prior run — columns' AS check_name,
    CASE WHEN count(*) = 0 THEN 'PASS' ELSE 'WARN' END AS status,
    CASE WHEN count(*) = 0
      THEN 'None of the columns 009 adds exist yet'
      ELSE 'Already exist (not blocking — 009 uses ADD COLUMN IF NOT EXISTS): '
           || string_agg(table_name || '.' || column_name, ', ')
    END AS detail
  FROM existing_columns
) x

UNION ALL
SELECT 6, check_name, status, detail FROM (
  SELECT
    'Partial prior run — allocate_twin_checks() function' AS check_name,
    CASE WHEN count(*) = 0 THEN 'PASS' ELSE 'WARN' END AS status,
    CASE WHEN count(*) = 0
      THEN 'Does not exist yet'
      ELSE 'Already exists (not blocking — 009 uses CREATE OR REPLACE FUNCTION, '
           || 'will simply overwrite it with the same definition)'
    END AS detail
  FROM existing_function
) x

UNION ALL
SELECT 7, check_name, status, detail FROM (
  SELECT
    'Partial prior run — indexes' AS check_name,
    CASE WHEN count(*) = 0 THEN 'PASS' ELSE 'WARN' END AS status,
    CASE WHEN count(*) = 0
      THEN 'None of the indexes 009 creates exist yet'
      ELSE 'Already exist (not blocking — 009 uses CREATE INDEX IF NOT EXISTS): '
           || string_agg(indexname, ', ')
    END AS detail
  FROM existing_indexes
) x
)

SELECT check_name, status, detail
FROM results
ORDER BY CASE status WHEN 'FAIL' THEN 0 WHEN 'WARN' THEN 1 ELSE 2 END, ord;

-- ============================================================
-- HOW TO READ THE RESULT
-- ============================================================
-- Any row with status = 'FAIL': stop, fix that specific thing, re-run this
--   script. Do not run 009 until every row is PASS or WARN.
-- Any row with status = 'WARN': safe to proceed — these are all things 009
--   is already written to tolerate (IF NOT EXISTS / ON CONFLICT DO NOTHING
--   throughout) — but know going in that 009 has partially run before,
--   which changes what to expect in its own VERIFY AFTER RUNNING section
--   (e.g. an sku_map row that already existed will show as updated, not
--   freshly inserted).
-- All PASS: 009 is safe to run as written.
-- ============================================================
