-- ============================================================
-- Migration 004 — Pronto Cache Extensions
-- Run in Supabase SQL Editor AFTER 003_inbound_pipeline.sql
-- ============================================================

-- ── 1. Tracking columns ────────────────────────────────────────────────────
ALTER TABLE pronto_cache ADD COLUMN IF NOT EXISTS first_seen_at              TIMESTAMP DEFAULT NOW();
ALTER TABLE pronto_cache ADD COLUMN IF NOT EXISTS last_seen_at               TIMESTAMP DEFAULT NOW();
ALTER TABLE pronto_cache ADD COLUMN IF NOT EXISTS order_created              BOOLEAN DEFAULT FALSE;
ALTER TABLE pronto_cache ADD COLUMN IF NOT EXISTS is_refund                  BOOLEAN DEFAULT FALSE;
ALTER TABLE pronto_cache ADD COLUMN IF NOT EXISTS refund_matched_to_order_id UUID;
ALTER TABLE pronto_cache ADD COLUMN IF NOT EXISTS refund_match_confidence    TEXT
  CHECK (refund_match_confidence IS NULL OR refund_match_confidence IN
    ('exact', 'cash_fallback', 'unmatched'));

-- ── 2. Natural key column for upsert ──────────────────────────────────────
-- Concatenates (sales_order_number, bo_suffix_or_empty, sku_code_or_empty)
-- so the Supabase Python SDK can upsert on a single column name.
ALTER TABLE pronto_cache ADD COLUMN IF NOT EXISTS cache_key TEXT;

-- Backfill cache_key for any existing rows
UPDATE pronto_cache
SET cache_key = sales_order_number
             || '|' || COALESCE(bo_suffix, '')
             || '|' || COALESCE(sku_code, '')
WHERE cache_key IS NULL;

-- Make it NOT NULL now that it's backfilled
ALTER TABLE pronto_cache ALTER COLUMN cache_key SET NOT NULL;
ALTER TABLE pronto_cache ALTER COLUMN cache_key SET DEFAULT '';

CREATE UNIQUE INDEX IF NOT EXISTS idx_pronto_cache_natural_key
  ON pronto_cache(cache_key);

-- ── Defensive note ─────────────────────────────────────────────────────────
-- If two CSV rows ever produce the same (sales_order_number, bo_suffix, sku_code)
-- — violating our assumption that Pronto aggregates duplicate SKUs — the sync
-- logs a WARN with the full row payload and keeps the latest. It does not crash.
-- The unique index on cache_key enforces this at DB level during backfill above;
-- the sync handles it at application level.
