-- ============================================================
-- digiPrint Operations Platform - Initial Schema
-- Run this in Supabase SQL Editor
-- ============================================================

-- ============================================================
-- STORES
-- ============================================================
CREATE TABLE stores (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name        TEXT NOT NULL UNIQUE,          -- 'Bondi', 'Miranda', etc.
    label       TEXT NOT NULL,                 -- 'digiDirect Bondi'
    email       TEXT NOT NULL,                 -- lab.bondi@digidirect.com.au
    drive_root_folder_id    TEXT,              -- Google Drive root folder ID
    drive_inbox_folder_id   TEXT,              -- Google Drive inbox folder ID
    is_active   BOOLEAN DEFAULT true,
    created_at  TIMESTAMPTZ DEFAULT now()
);

-- Seed stores
INSERT INTO stores (name, label, email) VALUES
    ('Bondi',      'digiDirect Bondi',       'lab.bondi@digidirect.com.au'),
    ('Miranda',    'digiDirect Miranda',     'lab.miranda@digidirect.com.au'),
    ('Parramatta', 'digiDirect Parramatta',  'lab.parramatta@digidirect.com.au'),
    ('Brisbane',   'digiDirect Brisbane',    'lab.brisbane@digidirect.com.au'),
    ('Cannington', 'digiDirect Cannington',  'lab.cannington@digidirect.com.au');

-- ============================================================
-- USERS (staff accounts)
-- ============================================================
CREATE TABLE users (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email           TEXT NOT NULL UNIQUE,
    password_hash   TEXT NOT NULL,
    full_name       TEXT NOT NULL,
    initials        TEXT,                      -- used as operator identifier
    role            TEXT NOT NULL DEFAULT 'staff'
                    CHECK (role IN ('staff', 'store_admin', 'master_admin')),
    store_id        UUID REFERENCES stores(id),  -- NULL = access all stores
    is_active       BOOLEAN DEFAULT true,
    created_at      TIMESTAMPTZ DEFAULT now(),
    last_login      TIMESTAMPTZ
);

-- ============================================================
-- CUSTOMERS
-- ============================================================
CREATE TABLE customers (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name        TEXT NOT NULL,
    email       TEXT,
    phone       TEXT,
    account     TEXT,                          -- B2B account name (from Pronto)
    created_at  TIMESTAMPTZ DEFAULT now(),
    updated_at  TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_customers_email ON customers(email);
CREATE INDEX idx_customers_name ON customers(name);

-- ============================================================
-- ORDERS (maps to a Pronto order / customer visit)
-- ============================================================
CREATE TABLE orders (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    order_number    TEXT NOT NULL,             -- e.g. DD-2025-000123
    store_id        UUID NOT NULL REFERENCES stores(id),
    customer_id     UUID REFERENCES customers(id),

    -- Customer snapshot (denormalised for speed, same as sheet)
    customer_name   TEXT NOT NULL,
    customer_email  TEXT,
    account         TEXT,                      -- B2B account

    -- Order type
    order_type      TEXT NOT NULL DEFAULT 'film'
                    CHECK (order_type IN ('film', 'b2b', 'print_only', 'passport')),

    -- Status lifecycle
    status          TEXT NOT NULL DEFAULT 'booked'
                    CHECK (status IN (
                        'booked',
                        'processing',
                        'scanned',
                        'print_ready',
                        'delivered',
                        'blank',
                        'archived',
                        'cancelled'
                    )),

    -- Drive / delivery
    drive_order_folder_url  TEXT,
    scan_link               TEXT,              -- direct download link if separate

    -- Email tracking (mirrors sheet columns exactly)
    email_status                TEXT DEFAULT '',
    blank_email_status          TEXT DEFAULT '',
    print_ready_email_status    TEXT DEFAULT '',

    -- Flags
    is_print_only   BOOLEAN DEFAULT false,     -- PrintOnly_flag
    has_blanks      BOOLEAN DEFAULT false,     -- computed, updated when rolls marked blank

    -- Timestamps
    created_at          TIMESTAMPTZ DEFAULT now(),   -- Timestamp in sheet
    date_scanned        TIMESTAMPTZ,
    date_delivered      TIMESTAMPTZ,
    date_print_ready_notified TIMESTAMPTZ,

    -- Operator who booked it in
    operator_id         UUID REFERENCES users(id),
    operator_initials   TEXT,

    -- Notes
    notes               TEXT
);

CREATE INDEX idx_orders_order_number ON orders(order_number);
CREATE INDEX idx_orders_store_id ON orders(store_id);
CREATE INDEX idx_orders_status ON orders(status);
CREATE INDEX idx_orders_created_at ON orders(created_at DESC);

-- ============================================================
-- ROLLS (individual film rolls within an order)
-- Maps directly to rows in the Rolls sheet
-- ============================================================
CREATE TABLE rolls (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    order_id        UUID NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    store_id        UUID NOT NULL REFERENCES stores(id),

    -- The twin check number (4-digit padded, e.g. '0042')
    twin_check      TEXT NOT NULL,

    -- Service type per roll
    service_type    TEXT NOT NULL DEFAULT 'Dev+Scan'
                    CHECK (service_type IN (
                        'Dev only',
                        'Dev+Scan',
                        'Dev+Scan+Print',
                        'Dev+Print',
                        'Scan only',
                        'Print only'
                    )),

    -- Status per roll
    status          TEXT NOT NULL DEFAULT 'booked'
                    CHECK (status IN (
                        'booked',
                        'processing',
                        'scanned',
                        'print_ready',
                        'delivered',
                        'blank',
                        'archived'
                    )),

    -- Blank workflow
    is_blank            BOOLEAN DEFAULT false,   -- Blank_Flag
    blank_confirmed_at  TIMESTAMPTZ,
    blank_notified_at   TIMESTAMPTZ,

    -- Drive folder for this specific roll's scans
    drive_folder_name   TEXT,                    -- e.g. '20250001' (8-digit scanner folder)
    drive_folder_url    TEXT,

    -- Timestamps
    created_at      TIMESTAMPTZ DEFAULT now(),
    date_scanned    TIMESTAMPTZ,
    date_delivered  TIMESTAMPTZ,

    -- Operator
    operator_initials   TEXT
);

CREATE INDEX idx_rolls_order_id ON rolls(order_id);
CREATE INDEX idx_rolls_twin_check ON rolls(twin_check);
CREATE INDEX idx_rolls_store_id ON rolls(store_id);
CREATE UNIQUE INDEX idx_rolls_twin_store ON rolls(store_id, twin_check)
    WHERE status != 'archived';

-- ============================================================
-- ORDER EVENTS (audit trail - replaces manual email log)
-- ============================================================
CREATE TABLE order_events (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    order_id    UUID NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    roll_id     UUID REFERENCES rolls(id),
    event_type  TEXT NOT NULL,                 -- 'booked', 'scanned', 'email_sent', etc.
    description TEXT,
    actor_id    UUID REFERENCES users(id),
    actor_label TEXT,                          -- initials or 'system'
    metadata    JSONB DEFAULT '{}',
    created_at  TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_events_order_id ON order_events(order_id);
CREATE INDEX idx_events_created_at ON order_events(created_at DESC);

-- ============================================================
-- B2B VENDORS
-- ============================================================
CREATE TABLE vendors (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name        TEXT NOT NULL UNIQUE,          -- 'Studio X', 'John Smith Photography'
    contact_name TEXT,
    email       TEXT,
    phone       TEXT,
    pixieset_gallery_url TEXT,                 -- their Pixieset gallery
    notes       TEXT,
    is_active   BOOLEAN DEFAULT true,
    created_at  TIMESTAMPTZ DEFAULT now()
);

-- ============================================================
-- B2B RELEASES (batched vendor print jobs - "drops")
-- ============================================================
CREATE TABLE vendor_releases (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    vendor_id       UUID NOT NULL REFERENCES vendors(id),
    store_id        UUID NOT NULL REFERENCES stores(id),
    release_name    TEXT NOT NULL,             -- e.g. 'April 2025 Drop'
    status          TEXT NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending', 'in_production', 'qc', 'ready', 'dispatched', 'complete')),

    -- Pixieset
    pixieset_gallery_url    TEXT,
    pixieset_order_ids      TEXT[],            -- array of Pixieset order IDs

    -- Fulfilment
    total_items     INTEGER DEFAULT 0,
    completed_items INTEGER DEFAULT 0,
    notes           TEXT,

    created_at      TIMESTAMPTZ DEFAULT now(),
    due_date        DATE,
    dispatched_at   TIMESTAMPTZ
);

-- ============================================================
-- EMAIL SEND LOG (replaces script properties fuse)
-- ============================================================
CREATE TABLE email_log (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    order_id    UUID REFERENCES orders(id),
    email_type  TEXT NOT NULL,                 -- 'delivery', 'blank', 'print_ready', 'b2b'
    recipient   TEXT NOT NULL,
    subject     TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'sent'
                CHECK (status IN ('sent', 'failed', 'skipped')),
    error       TEXT,
    sent_at     TIMESTAMPTZ DEFAULT now()
);

-- ============================================================
-- ROW LEVEL SECURITY (basic - can expand later)
-- ============================================================
ALTER TABLE stores ENABLE ROW LEVEL SECURITY;
ALTER TABLE orders ENABLE ROW LEVEL SECURITY;
ALTER TABLE rolls ENABLE ROW LEVEL SECURITY;

-- For now, allow all authenticated service role access
-- (our FastAPI backend uses the service key, so this is fine)
CREATE POLICY "Service role full access - stores"
    ON stores FOR ALL USING (true);
CREATE POLICY "Service role full access - orders"
    ON orders FOR ALL USING (true);
CREATE POLICY "Service role full access - rolls"
    ON rolls FOR ALL USING (true);

-- ============================================================
-- USEFUL VIEWS
-- ============================================================

-- Master dashboard view - one row per order with roll counts
CREATE VIEW v_order_summary AS
SELECT
    o.id,
    o.order_number,
    o.order_type,
    o.status,
    o.customer_name,
    o.customer_email,
    o.account,
    s.name AS store_name,
    s.label AS store_label,
    o.operator_initials,
    o.email_status,
    o.drive_order_folder_url,
    o.is_print_only,
    o.has_blanks,
    o.created_at,
    o.date_scanned,
    o.date_delivered,
    -- Roll counts
    COUNT(r.id) AS total_rolls,
    COUNT(r.id) FILTER (WHERE r.status = 'delivered') AS delivered_rolls,
    COUNT(r.id) FILTER (WHERE r.is_blank = true) AS blank_rolls,
    -- Turnaround (hours from booking to delivery)
    EXTRACT(EPOCH FROM (o.date_delivered - o.created_at))/3600 AS turnaround_hours
FROM orders o
JOIN stores s ON o.store_id = s.id
LEFT JOIN rolls r ON r.order_id = o.id
GROUP BY o.id, s.id;

-- Overdue jobs (booked > 48h ago, not delivered)
CREATE VIEW v_overdue_orders AS
SELECT * FROM v_order_summary
WHERE status NOT IN ('delivered', 'archived', 'cancelled')
AND created_at < now() - interval '48 hours'
ORDER BY created_at ASC;
