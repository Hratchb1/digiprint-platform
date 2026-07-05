-- ============================================================
-- 002 — Email branding columns on store_settings
-- Run this in the Supabase SQL Editor:
--   https://supabase.com/dashboard/project/tyffpxxfeqdojbpedkwj/sql
-- ============================================================
--
-- Adds 4 nullable per-store branding fields used by the v4 email
-- templates (starting with scans_ready_v4). Each field is optional —
-- the templates fall back gracefully when a column is NULL.
--
-- Safe to re-run: every change uses IF NOT EXISTS / DEFAULT.
-- ============================================================

-- Add columns (idempotent)
ALTER TABLE store_settings
    ADD COLUMN IF NOT EXISTS address_line  TEXT,
    ADD COLUMN IF NOT EXISTS reply_email   TEXT,
    ADD COLUMN IF NOT EXISTS hours_label   TEXT DEFAULT 'Open 7 days',
    ADD COLUMN IF NOT EXISTS instagram_url TEXT;

-- ============================================================
-- Seed Bondi (test store) — update other stores via dashboard
-- ============================================================
-- IMPORTANT: replace placeholder address with the real Bondi
--            shop address before go-live.
-- ============================================================

UPDATE store_settings
SET
    address_line  = COALESCE(address_line,  'Westfield Bondi Junction, Level 4, NSW 2022'),
    reply_email   = COALESCE(reply_email,   'lab.bondi@digidirect.com.au'),
    hours_label   = COALESCE(hours_label,   'Open 7 days'),
    instagram_url = COALESCE(instagram_url, 'https://www.instagram.com/digidirect')
WHERE store_id = (SELECT id FROM stores WHERE name = 'Bondi');

-- ============================================================
-- Verification query (paste after running the above)
-- ============================================================
--
--   SELECT s.name, ss.address_line, ss.reply_email, ss.hours_label, ss.instagram_url
--   FROM store_settings ss
--   JOIN stores s ON s.id = ss.store_id
--   ORDER BY s.name;
--
-- Expected: Bondi row populated, other stores NULL (fine).
-- ============================================================
