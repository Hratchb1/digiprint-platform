-- ============================================================
-- Migration 003 — Inbound Pipeline
-- Run in Supabase SQL Editor
-- ============================================================

-- ── 1. Drop the OLD status check constraint FIRST ─────────────────────────
-- Must drop before UPDATEs run, because the new values (booked_in, scanning)
-- are not in the old constraint's allowed list.
ALTER TABLE orders DROP CONSTRAINT IF EXISTS orders_status_check;

-- ── 2. Rename old status values to the new vocabulary ─────────────────────
UPDATE orders SET status = 'booked_in' WHERE status = 'booked';
UPDATE orders SET status = 'scanning'  WHERE status = 'scanned';

-- Conservative mappings for statuses dropped from the new enum:
--   processing / devready  → scanning  (closest in-progress state)
--   print_ready / printready / blank / archived → delivered  (terminal, work was done)
UPDATE orders SET status = 'scanning'
  WHERE status IN ('processing', 'devready');
UPDATE orders SET status = 'delivered'
  WHERE status IN ('print_ready', 'printready', 'blank', 'archived');

-- ── 3. Add the NEW six-state status check constraint ──────────────────────
ALTER TABLE orders ADD CONSTRAINT orders_status_check
  CHECK (status IN ('inbound', 'booked_in', 'scanning', 'delivered', 'cancelled', 'discarded'));

-- ── 3. New identifier columns ──────────────────────────────────────────────
ALTER TABLE orders ADD COLUMN IF NOT EXISTS pronto_order_number   TEXT;
ALTER TABLE orders ADD COLUMN IF NOT EXISTS pronto_account_number TEXT;

-- Backfill: for all existing orders, pronto_order_number = order_number
-- (the system previously stored the Pronto sales order number in order_number)
UPDATE orders SET pronto_order_number = order_number WHERE pronto_order_number IS NULL;

-- ── 4. New timestamp columns ───────────────────────────────────────────────
ALTER TABLE orders ADD COLUMN IF NOT EXISTS pronto_order_date     TIMESTAMP;
ALTER TABLE orders ADD COLUMN IF NOT EXISTS pronto_shipped_date   TIMESTAMP;
ALTER TABLE orders ADD COLUMN IF NOT EXISTS booked_in_at          TIMESTAMP;
ALTER TABLE orders ADD COLUMN IF NOT EXISTS scanning_at           TIMESTAMP;
ALTER TABLE orders ADD COLUMN IF NOT EXISTS delivered_at          TIMESTAMP;
ALTER TABLE orders ADD COLUMN IF NOT EXISTS cancelled_at          TIMESTAMP;
ALTER TABLE orders ADD COLUMN IF NOT EXISTS discarded_at          TIMESTAMP;
ALTER TABLE orders ADD COLUMN IF NOT EXISTS discarded_by          TEXT;

-- ── 5. Discard workflow columns ────────────────────────────────────────────
ALTER TABLE orders ADD COLUMN IF NOT EXISTS discard_reason        TEXT
  CHECK (discard_reason IS NULL OR discard_reason IN
    ('charge_correction', 'add_on_existing', 'not_film_related', 'duplicate_sale', 'other'));
ALTER TABLE orders ADD COLUMN IF NOT EXISTS discard_notes         TEXT;

-- ── 6. Refund tracking columns ─────────────────────────────────────────────
ALTER TABLE orders ADD COLUMN IF NOT EXISTS refund_status         TEXT
  CHECK (refund_status IS NULL OR refund_status IN ('partial', 'full'));
ALTER TABLE orders ADD COLUMN IF NOT EXISTS refund_pronto_order_number TEXT;
ALTER TABLE orders ADD COLUMN IF NOT EXISTS refund_amount         DECIMAL(10,2);

-- ── 7. Best-effort timestamp backfill for existing rows ───────────────────
-- booked_in_at: all non-inbound orders were booked at created_at
UPDATE orders SET booked_in_at = created_at
  WHERE booked_in_at IS NULL AND status <> 'inbound';

-- scanning_at: use existing date_scanned column if present
UPDATE orders SET scanning_at = date_scanned
  WHERE scanning_at IS NULL AND date_scanned IS NOT NULL;

-- delivered_at: use existing date_delivered column
UPDATE orders SET delivered_at = date_delivered
  WHERE delivered_at IS NULL AND date_delivered IS NOT NULL;

-- ── 8. Indexes ─────────────────────────────────────────────────────────────
CREATE INDEX IF NOT EXISTS idx_orders_pronto_order_number
  ON orders(pronto_order_number);

CREATE INDEX IF NOT EXISTS idx_orders_account_active
  ON orders(pronto_account_number, status)
  WHERE status IN ('inbound', 'booked_in', 'scanning');

CREATE INDEX IF NOT EXISTS idx_orders_pronto_order_date
  ON orders(pronto_order_date)
  WHERE status = 'inbound';

-- ── 9. Territory code column on stores ────────────────────────────────────
ALTER TABLE stores ADD COLUMN IF NOT EXISTS territory_code TEXT;

CREATE UNIQUE INDEX IF NOT EXISTS idx_stores_territory_code
  ON stores(territory_code) WHERE territory_code IS NOT NULL;

-- Seed known territory codes (MELB seeds even if no Melbourne store exists yet)
UPDATE stores SET territory_code = 'BOND' WHERE LOWER(name) = 'bondi';
UPDATE stores SET territory_code = 'BRIS' WHERE LOWER(name) = 'brisbane';
UPDATE stores SET territory_code = 'CANN' WHERE LOWER(name) = 'cannington';
UPDATE stores SET territory_code = 'MELB' WHERE LOWER(name) = 'melbourne';
UPDATE stores SET territory_code = 'MIRA' WHERE LOWER(name) = 'miranda';
UPDATE stores SET territory_code = 'PARR' WHERE LOWER(name) = 'parramatta';

-- ── 10. Order activity log table ──────────────────────────────────────────
CREATE TABLE IF NOT EXISTS order_activity (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  order_id    UUID REFERENCES orders(id) ON DELETE CASCADE,
  event_type  TEXT NOT NULL,
  event_data  JSONB,
  operator_id TEXT,
  created_at  TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_order_activity_order_id
  ON order_activity(order_id, created_at DESC);

-- ── Verification query (run after applying, check 0 rows) ─────────────────
-- SELECT id, order_number, status FROM orders
-- WHERE status NOT IN ('inbound','booked_in','scanning','delivered','cancelled','discarded');
