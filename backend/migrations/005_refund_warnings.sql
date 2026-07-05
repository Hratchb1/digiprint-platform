-- ============================================================
-- Migration 005 — Refund Warnings Table
-- Run in Supabase SQL Editor AFTER 004_pronto_cache_extensions.sql
-- ============================================================

CREATE TABLE IF NOT EXISTS refund_warnings (
  id                         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  refund_pronto_order_number TEXT NOT NULL,
  pronto_account_number      TEXT,
  territory                  TEXT,
  refund_amount              DECIMAL(10,2),
  refund_lines               JSONB,
  status                     TEXT DEFAULT 'pending'
    CHECK (status IN ('pending', 'manually_resolved', 'ignored')),
  resolved_by                TEXT,
  resolved_at                TIMESTAMP,
  resolution_notes           TEXT,
  created_at                 TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_refund_warnings_status
  ON refund_warnings(status, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_refund_warnings_order_number
  ON refund_warnings(refund_pronto_order_number);
