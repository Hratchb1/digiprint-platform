-- ============================================================
-- 009_twin_check_allocation.sql
-- ============================================================
-- REVIEW BEFORE RUNNING. Not applied automatically — run manually
-- in the Supabase SQL Editor after review, per the RollCall twin
-- check allocation brief (16 Aug 2026).
--
-- WHAT THIS ADDS
-- ----------------
-- Server-side twin check allocation + label printing. Staff currently
-- type the twin check number by hand, reading it off a pre-printed
-- sticker — a transcription slip matches a negative to the wrong
-- customer's order. This migration adds the schema for RollCall to
-- allocate the number itself (per store, atomic, gap-free blocks) and
-- print the label, so the number in the database *is* the number on
-- the label by construction. Manual entry stays available in every
-- store, in every mode — auto_enabled only controls whether the
-- number arrives pre-filled or typed (see "ONE CONCEPT" below).
--
-- ONE CONCEPT, ONE SOURCE COLUMN
-- ---------------------------------
-- A twin check is one concept regardless of provenance — same
-- storage, same display, same downstream operations (reprint, void,
-- collision detection, delivery warnings), whether the system
-- allocated it or a staff member typed it off pre-printed stock.
-- twin_checks.source ('auto' | 'manual') is the *entire* distinction;
-- nothing else branches on it. Concretely:
--   - Both write a twin_checks row and populate rolls.twin_check_id.
--   - Only 'auto' rows are drawn from twin_check_sequences and carry
--     a real cycle; 'manual' rows never advance current_value (a
--     mistyped 9500 must never burn thousands of numbers) and store
--     cycle = NULL.
--   - Both run the same collision check before insert.
-- See backend/app/services/twin_check_service.py for the shared
-- collision/insert logic both paths call through.
--
-- COLLISION DETECTION READS rolls, NOT twin_checks — NO BACKFILL
-- ------------------------------------------------------------------
-- Old, uncollected jobs that predate this build have a populated
-- rolls.twin_check but no twin_checks row at all — there is
-- deliberately no backfill of historical rolls into twin_checks.
-- rolls.twin_check (filtered to status <> 'archived', the same filter
-- order_service._get_existing_twins already uses) is therefore the
-- only complete picture of "what numbers are currently live," for
-- both legacy and new rolls. twin_checks exists to track allocation
-- provenance and print/void lifecycle, not to be the collision source
-- of truth.
--
-- SCHEMA VERIFICATION NOTE
-- -------------------------
-- sku_map exists live but had 0 rows and no requires_twin_check /
-- process_code columns at the time this was written. The 5 SKU rows
-- seeded below (§ "sku_map additions") are reconstructed from
-- historical enrichment cached on pronto_cache (written back when
-- sku_map presumably did have rows) — confirmed against live
-- pronto_cache data, not guessed. No E6 SKU exists anywhere in
-- pronto_cache's 24 distinct SKUs, so E6 is not a permitted process
-- code. See process_codes below.
--
-- WHY process_codes IS A TABLE, NOT A CHECK CONSTRAINT
-- ------------------------------------------------------
-- sku_map.requires_twin_check / process_code are designed so a new
-- SKU can be flagged with an INSERT and no deploy (acceptance
-- criterion 11b). A hardcoded CHECK (process_code IN ('C41','BW','RSC'))
-- would defeat that the moment a 4th process code is needed — so
-- process_code is a plain nullable TEXT column with a foreign key
-- into this small lookup table instead. Adding a future code is one
-- INSERT into process_codes.
--
-- WHY rolls.twin_check BECOMES NULLABLE
-- ----------------------------------------
-- Auto-mode order creation and allocation are two separate calls
-- (POST /orders with pending rolls, then POST /orders/{id}/twin-checks/allocate)
-- — the roll exists before it has a real number. NULL (not a sentinel
-- string) represents "not yet allocated": it's what the existing
-- application code already treats falsy twin_check values as
-- (email_service._compute_twin_check_range does
-- `(r.get("twin_check") or "")`), so nothing downstream needs to
-- change to tolerate it, and an abandoned auto-mode booking never
-- leaves a fake value sitting in a column whose whole purpose is to
-- carry real twin-check identity. Manual-mode rolls (and Pronto
-- lookups where auto_enabled is off) still get a real twin_check at
-- creation time, exactly as today.
--
-- STORE_SETTINGS HAS 0 ROWS TODAY
-- ----------------------------------
-- Label/printer config (dpi, dimensions, copies, printer IP, print
-- agent token) is added to store_settings rather than a new table,
-- since it's already a 1:1-per-store table — but with 0 live rows,
-- new columns have nowhere to land. This migration seeds one row per
-- active store so the columns are populated with their defaults from
-- the moment this runs.
--
-- RLS
-- ----
-- Same pattern as 006_rls_security_pass.sql: enable RLS, grant
-- service_role an explicit FOR ALL policy (redundant since
-- service_role has BYPASSRLS, but keeps the access model
-- self-documenting from the policy list), no policy for anon/
-- authenticated — nothing in this app queries Supabase as either
-- role (see 006's audit note), so the absence of a policy means zero
-- rows for them by default.
--
-- allocate_twin_checks() is SECURITY DEFINER with a pinned
-- search_path = '' (matches the 007 hardening pattern) so it can
-- update twin_check_sequences under RLS regardless of caller, while
-- not being exploitable via search_path manipulation.
-- ============================================================


-- ============================================================
-- 1. process_codes — lookup table, not a CHECK constraint
-- ============================================================
CREATE TABLE IF NOT EXISTS process_codes (
  code   TEXT PRIMARY KEY,
  label  TEXT NOT NULL
);

INSERT INTO process_codes (code, label) VALUES
  ('C41', 'Colour negative process'),
  ('BW',  'Black & white process'),
  ('RSC', 'Cut neg rescan')
ON CONFLICT (code) DO NOTHING;


-- ============================================================
-- 2. sku_map additions — requires_twin_check / process_code
-- ============================================================
ALTER TABLE sku_map
  ADD COLUMN IF NOT EXISTS requires_twin_check BOOLEAN NOT NULL DEFAULT false,
  ADD COLUMN IF NOT EXISTS process_code TEXT REFERENCES process_codes(code);

-- Seed exactly the 5 SKUs confirmed live in pronto_cache to represent
-- physical rolls entering the lab. Everything else stays false/null.
-- While touching these 5 rows, also restore their service_type /
-- film_type / category columns to the known-correct historical
-- values — sku_map being empty means Pronto sync enrichment
-- (pronto_sync._get_sku_map) currently returns nothing for every SKU,
-- so this incidentally fixes enrichment for just these 5 as a side
-- effect of the twin-check work, not as a full catalog fix (the
-- other ~19 SKUs pronto_cache has seen stay unenriched — separate,
-- pre-existing issue, not in scope here).
INSERT INTO sku_map (sku_code, product_name, service_type, film_type, category, requires_twin_check, process_code)
VALUES
  ('100020', 'Dev Only 35mm',            'Develop only', 'C41 35mm',  'Developing', true, 'C41'),
  ('100003', 'Dev Only 120mm',           'Develop only', 'C41 120mm', 'Developing', true, 'C41'),
  ('122191', 'Dev Only B&W 35mm',        'Develop only', 'B&W 35mm',  'Developing', true, 'BW'),
  ('100008', 'Dev Only B&W 120mm',       'Develop only', 'B&W 120mm', 'Developing', true, 'BW'),
  ('120152', 'Cut Neg Scanned to Media', 'Scan only',    NULL,        'Scanning',   true, 'RSC')
ON CONFLICT (sku_code) DO UPDATE SET
  product_name         = EXCLUDED.product_name,
  service_type          = EXCLUDED.service_type,
  film_type               = EXCLUDED.film_type,
  category                 = EXCLUDED.category,
  requires_twin_check        = EXCLUDED.requires_twin_check,
  process_code                 = EXCLUDED.process_code;

-- Scanning add-on SKUs that ride along on an already twin-checked
-- roll (Dev+Scan orders) — explicitly NOT flagged, so a 5-roll
-- Dev+Scan order allocates 5 twin checks, not 10. Recorded here for
-- documentation even though false/NULL are already the column
-- defaults, and to restore their enrichment too.
INSERT INTO sku_map (sku_code, product_name, service_type, category, requires_twin_check, process_code)
VALUES
  ('123242', 'Scanning — Standard Res', 'Scan only',  'Scanning',      false, NULL),
  ('123243', 'Scanning — Mid Res',      'Scan only',  'Scanning',      false, NULL),
  ('123244', 'Scanning — Hi Res',       'Scan only',  'Scanning',      false, NULL),
  ('100022', '1 Set 24exp Print',       'Print only', 'Film Printing', false, NULL),
  ('100024', '1 Set 36exp Print',       'Print only', 'Film Printing', false, NULL)
ON CONFLICT (sku_code) DO UPDATE SET
  product_name  = EXCLUDED.product_name,
  service_type  = EXCLUDED.service_type,
  category      = EXCLUDED.category;


-- ============================================================
-- 3. twin_check_sequences — one row per store
-- ============================================================
CREATE TABLE IF NOT EXISTS twin_check_sequences (
  store_id       UUID PRIMARY KEY REFERENCES stores(id),
  current_value  INT NOT NULL DEFAULT 0,
  cycle          INT NOT NULL DEFAULT 1,
  min_value      INT NOT NULL DEFAULT 1,
  max_value      INT NOT NULL DEFAULT 9999,
  auto_enabled   BOOLEAN NOT NULL DEFAULT false,
  updated_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

INSERT INTO twin_check_sequences (store_id)
SELECT id FROM stores WHERE is_active
ON CONFLICT (store_id) DO NOTHING;


-- ============================================================
-- 4. twin_checks — one row per twin check, auto OR manual
-- ============================================================
-- source is the entire distinction between the two paths (see header).
-- cycle is nullable: only 'auto' rows are sequence-derived and carry
-- a real cycle; 'manual' rows never touch twin_check_sequences at all,
-- so cycle = NULL for them ("not applicable", not a guess).
CREATE TABLE IF NOT EXISTS twin_checks (
  id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  store_id           UUID NOT NULL REFERENCES stores(id),
  number             INT NOT NULL CHECK (number BETWEEN 1 AND 9999),
  cycle              INT,
  source             TEXT NOT NULL CHECK (source IN ('auto', 'manual')),
  order_id           UUID REFERENCES orders(id),
  roll_id            UUID REFERENCES rolls(id),
  status             TEXT NOT NULL DEFAULT 'allocated'
    CHECK (status IN ('allocated', 'printed', 'voided')),
  collision_warning  BOOLEAN NOT NULL DEFAULT false,
  allocated_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
  allocated_by       TEXT,
  printed_at         TIMESTAMPTZ,
  voided_at          TIMESTAMPTZ,
  void_reason        TEXT
);

-- twin_checks is provenance/lifecycle tracking, NOT the collision
-- source of truth (that's rolls.twin_check — see header). This index
-- backs order/roll lookups (allocate idempotency, reprint, void), not
-- collision detection.
CREATE INDEX IF NOT EXISTS idx_twin_checks_order
  ON twin_checks (order_id);

CREATE INDEX IF NOT EXISTS idx_twin_checks_roll
  ON twin_checks (roll_id);

CREATE INDEX IF NOT EXISTS idx_twin_checks_store_number_active
  ON twin_checks (store_id, number)
  WHERE status <> 'voided';


-- ============================================================
-- 5. rolls — link to twin_checks, add process_code, twin_check nullable
-- ============================================================
ALTER TABLE rolls
  ALTER COLUMN twin_check DROP NOT NULL,
  ADD COLUMN IF NOT EXISTS twin_check_id UUID REFERENCES twin_checks(id),
  ADD COLUMN IF NOT EXISTS process_code TEXT REFERENCES process_codes(code);

-- Collision detection's actual source of truth: fast lookup of "is
-- this number already live in this store" across ALL rolls, legacy
-- and new, auto or manual — see header note.
CREATE INDEX IF NOT EXISTS idx_rolls_store_twin_active
  ON rolls (store_id, twin_check)
  WHERE status <> 'archived';


-- ============================================================
-- 6. print_jobs — outbound queue for the store print agent
-- ============================================================
CREATE TABLE IF NOT EXISTS print_jobs (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  store_id    UUID NOT NULL REFERENCES stores(id),
  zpl         TEXT NOT NULL,
  status      TEXT NOT NULL DEFAULT 'pending'
    CHECK (status IN ('pending', 'sent', 'failed')),
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  sent_at     TIMESTAMPTZ,
  error       TEXT
);

CREATE INDEX IF NOT EXISTS idx_print_jobs_store_status
  ON print_jobs (store_id, status);


-- ============================================================
-- 7. orders — rescan linkage
-- ============================================================
-- rescan_display_suffix is set once at creation (POST /orders/{id}/rescan)
-- and never recomputed by a live count of rescan children — the
-- existing duplicate-order modal in IntakePage.tsx already writes a
-- literal "{order_number}-B" into order_number for an unrelated case
-- (the same Pronto order booked twice), so a rescan's suffix picker
-- has to check both mechanisms for taken letters before choosing the
-- next one (see twin_check_service._next_rescan_suffix). order_number
-- itself is never modified by a rescan — display assembles
-- "{order_number}-{rescan_display_suffix}" at read time.
ALTER TABLE orders
  ADD COLUMN IF NOT EXISTS rescan_of_order_id UUID REFERENCES orders(id),
  ADD COLUMN IF NOT EXISTS rescan_display_suffix TEXT;

CREATE INDEX IF NOT EXISTS idx_orders_rescan_of
  ON orders (rescan_of_order_id);


-- ============================================================
-- 8. store_settings — label/printer config + print agent auth
-- ============================================================
ALTER TABLE store_settings
  ADD COLUMN IF NOT EXISTS label_printer_ip TEXT,
  ADD COLUMN IF NOT EXISTS label_printer_dpi INT NOT NULL DEFAULT 203,
  ADD COLUMN IF NOT EXISTS label_width_mm NUMERIC NOT NULL DEFAULT 23,
  ADD COLUMN IF NOT EXISTS label_height_mm NUMERIC NOT NULL DEFAULT 15,
  ADD COLUMN IF NOT EXISTS label_copies INT NOT NULL DEFAULT 2,
  ADD COLUMN IF NOT EXISTS print_agent_token TEXT
    DEFAULT encode(gen_random_uuid()::text::bytea, 'hex');

-- store_settings has 0 rows in production today — without seeding,
-- the columns above (and every pre-existing column on this table)
-- have nowhere to live for any store, and nothing will print.
INSERT INTO store_settings (store_id)
SELECT id FROM stores WHERE is_active
ON CONFLICT (store_id) DO NOTHING;

-- Backfill print_agent_token for any store_settings row that predates
-- the column default (defensive — the seed above already covers rows
-- created by this migration, this only matters if a row already
-- existed before this migration ran).
UPDATE store_settings
SET print_agent_token = encode(gen_random_uuid()::text::bytea, 'hex')
WHERE print_agent_token IS NULL;


-- ============================================================
-- 9. allocate_twin_checks() — atomic block allocation
-- ============================================================
-- Row lock via `FOR UPDATE` on the store's sequence row serialises
-- concurrent allocations. Blocks are always contiguous: if a block
-- would cross max_value, wrap first and waste the tail rather than
-- splitting it (§3.2 — a few wasted numbers per wrap is cheaper than
-- a non-contiguous job sheet). This function only ever advances
-- current_value for 'auto' allocations — manual entry never calls it
-- (see header "ONE CONCEPT").
CREATE OR REPLACE FUNCTION allocate_twin_checks(
  p_store_id UUID,
  p_count INT
) RETURNS TABLE (number INT, cycle INT)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
  seq public.twin_check_sequences%ROWTYPE;
  start_at INT;
BEGIN
  IF p_count IS NULL OR p_count < 1 THEN
    RAISE EXCEPTION 'allocate_twin_checks: p_count must be >= 1 (got %)', p_count;
  END IF;

  SELECT * INTO seq
    FROM public.twin_check_sequences
    WHERE store_id = p_store_id
    FOR UPDATE;

  IF NOT FOUND THEN
    RAISE EXCEPTION 'no sequence configured for store %', p_store_id;
  END IF;

  IF p_count > (seq.max_value - seq.min_value + 1) THEN
    RAISE EXCEPTION 'allocate_twin_checks: requested block of % exceeds the sequence range (% .. %)',
      p_count, seq.min_value, seq.max_value;
  END IF;

  -- If the block would cross the ceiling, wrap first and waste the tail.
  IF seq.current_value + p_count > seq.max_value THEN
    seq.current_value := seq.min_value - 1;
    seq.cycle := seq.cycle + 1;
  END IF;

  start_at := seq.current_value + 1;

  UPDATE public.twin_check_sequences
    SET current_value = start_at + p_count - 1,
        cycle = seq.cycle,
        updated_at = now()
    WHERE store_id = p_store_id;

  RETURN QUERY
    SELECT gs::INT, seq.cycle
    FROM generate_series(start_at, start_at + p_count - 1) gs;
END;
$$;

REVOKE ALL ON FUNCTION allocate_twin_checks(UUID, INT) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION allocate_twin_checks(UUID, INT) TO service_role;


-- ============================================================
-- 10. RLS — enable on the 4 new tables, service_role only
-- ============================================================
ALTER TABLE process_codes ENABLE ROW LEVEL SECURITY;
CREATE POLICY "service_role_full_access_process_codes"
    ON process_codes FOR ALL
    TO service_role
    USING (true) WITH CHECK (true);

ALTER TABLE twin_check_sequences ENABLE ROW LEVEL SECURITY;
CREATE POLICY "service_role_full_access_twin_check_sequences"
    ON twin_check_sequences FOR ALL
    TO service_role
    USING (true) WITH CHECK (true);

ALTER TABLE twin_checks ENABLE ROW LEVEL SECURITY;
CREATE POLICY "service_role_full_access_twin_checks"
    ON twin_checks FOR ALL
    TO service_role
    USING (true) WITH CHECK (true);

ALTER TABLE print_jobs ENABLE ROW LEVEL SECURITY;
CREATE POLICY "service_role_full_access_print_jobs"
    ON print_jobs FOR ALL
    TO service_role
    USING (true) WITH CHECK (true);


-- ============================================================
-- VERIFY AFTER RUNNING
-- ============================================================
-- 1. SELECT * FROM twin_check_sequences; -- one row per active store, auto_enabled = false
-- 2. SELECT * FROM store_settings;       -- one row per active store, label_* columns populated
-- 3. SELECT sku_code, requires_twin_check, process_code FROM sku_map ORDER BY sku_code;
--    -- exactly 100020/100003/122191/100008/120152 = true, everything else false/null
-- 4. SELECT * FROM allocate_twin_checks('<a real store_id>'::uuid, 3);
--    -- returns 3 sequential numbers; re-run and confirm current_value advanced further
--    -- (this is a direct DB-level smoke test — the app-level idempotency guarantee
--    -- lives in twin_check_service.allocate_for_order, not in this function itself,
--    -- which always allocates when called)
-- 5. Re-run the Supabase advisor (or get_advisors via the Supabase MCP tool) — confirm
--    no new RLS-disabled warnings for process_codes / twin_check_sequences /
--    twin_checks / print_jobs.
-- 6. Concurrency: run the backend's pytest concurrency test
--    (backend/tests/test_twin_check_service.py) against this schema before
--    relying on it — two parallel allocate calls for the same store must
--    never overlap.
-- ============================================================
