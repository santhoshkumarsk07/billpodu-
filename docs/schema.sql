-- 83 MEN'S WEAR POS - SQLite database schema
-- Generated from mw83/db/migrations.py (the source of truth). Do not edit by hand.
-- Money columns ending in _paise are integer paise (Rs 1 = 100). Rates ending in _bp are basis points
-- (100 bp = 1%). Foreign keys are enforced (PRAGMA foreign_keys = ON).

-- ===== Migration 1 =====
CREATE TABLE settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE sequences (
    name  TEXT PRIMARY KEY,
    value INTEGER NOT NULL
);

CREATE TABLE categories (
    id         INTEGER PRIMARY KEY,
    name       TEXT NOT NULL UNIQUE COLLATE NOCASE,
    created_at TEXT NOT NULL
);

CREATE TABLE products (
    id           INTEGER PRIMARY KEY,
    name         TEXT NOT NULL,
    category_id  INTEGER REFERENCES categories(id) ON DELETE RESTRICT,
    brand        TEXT NOT NULL DEFAULT '',
    sku          TEXT UNIQUE,                       -- optional style/base SKU
    hsn_code     TEXT NOT NULL DEFAULT '',
    gst_mode     TEXT NOT NULL DEFAULT 'DEFAULT' CHECK (gst_mode IN ('DEFAULT','FIXED','SLAB','EXEMPT')),
    gst_rate_bp  INTEGER NOT NULL DEFAULT 0 CHECK (gst_rate_bp BETWEEN 0 AND 10000),
    cost_paise   INTEGER NOT NULL DEFAULT 0 CHECK (cost_paise >= 0),
    price_paise  INTEGER NOT NULL CHECK (price_paise >= 0),
    mrp_paise    INTEGER NOT NULL DEFAULT 0 CHECK (mrp_paise >= 0),
    min_stock    INTEGER CHECK (min_stock IS NULL OR min_stock >= 0),
    image_file   TEXT NOT NULL DEFAULT '',
    active       INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0,1)),
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL
);
CREATE INDEX idx_products_name ON products(name COLLATE NOCASE);
CREATE INDEX idx_products_category ON products(category_id);

CREATE TABLE variants (
    id          INTEGER PRIMARY KEY,
    product_id  INTEGER NOT NULL REFERENCES products(id) ON DELETE RESTRICT,
    size        TEXT NOT NULL DEFAULT '',
    colour      TEXT NOT NULL DEFAULT '',
    sku         TEXT NOT NULL UNIQUE COLLATE NOCASE,
    barcode     TEXT NOT NULL UNIQUE,
    price_paise INTEGER CHECK (price_paise IS NULL OR price_paise >= 0),
    mrp_paise   INTEGER CHECK (mrp_paise IS NULL OR mrp_paise >= 0),
    cost_paise  INTEGER CHECK (cost_paise IS NULL OR cost_paise >= 0),
    stock       INTEGER NOT NULL DEFAULT 0 CHECK (stock >= 0),
    active      INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0,1)),
    created_at  TEXT NOT NULL
);
CREATE INDEX idx_variants_product ON variants(product_id);
CREATE UNIQUE INDEX idx_variants_size_colour ON variants(product_id, size COLLATE NOCASE, colour COLLATE NOCASE);

CREATE TABLE customers (
    id         INTEGER PRIMARY KEY,
    name       TEXT NOT NULL,
    phone      TEXT NOT NULL DEFAULT '',
    notes      TEXT NOT NULL DEFAULT '',
    is_walkin  INTEGER NOT NULL DEFAULT 0 CHECK (is_walkin IN (0,1)),
    active     INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0,1)),
    created_at TEXT NOT NULL
);
CREATE INDEX idx_customers_name ON customers(name COLLATE NOCASE);
CREATE UNIQUE INDEX idx_customers_phone ON customers(phone) WHERE phone <> '';

CREATE TABLE sales (
    id                   INTEGER PRIMARY KEY,
    invoice_no           TEXT NOT NULL UNIQUE,
    client_ref           TEXT NOT NULL UNIQUE,      -- guards against double-saving one bill
    created_at           TEXT NOT NULL,
    customer_id          INTEGER NOT NULL REFERENCES customers(id),
    customer_name        TEXT NOT NULL DEFAULT '',
    customer_phone       TEXT NOT NULL DEFAULT '',
    status               TEXT NOT NULL DEFAULT 'COMPLETED' CHECK (status IN ('COMPLETED','CANCELLED')),
    gross_paise          INTEGER NOT NULL,          -- sum of qty x unit price
    item_discount_paise  INTEGER NOT NULL DEFAULT 0,
    bill_discount_type   TEXT NOT NULL DEFAULT 'NONE' CHECK (bill_discount_type IN ('NONE','PERCENT','AMOUNT')),
    bill_discount_value  INTEGER NOT NULL DEFAULT 0, -- basis points or paise
    bill_discount_paise  INTEGER NOT NULL DEFAULT 0,
    discount_reason      TEXT NOT NULL DEFAULT '',
    gst_enabled          INTEGER NOT NULL DEFAULT 0,
    prices_include_tax   INTEGER NOT NULL DEFAULT 1,
    inter_state          INTEGER NOT NULL DEFAULT 0,
    taxable_paise        INTEGER NOT NULL DEFAULT 0,
    cgst_paise           INTEGER NOT NULL DEFAULT 0,
    sgst_paise           INTEGER NOT NULL DEFAULT 0,
    igst_paise           INTEGER NOT NULL DEFAULT 0,
    round_off_paise      INTEGER NOT NULL DEFAULT 0,
    total_paise          INTEGER NOT NULL CHECK (total_paise >= 0),
    tendered_paise       INTEGER NOT NULL DEFAULT 0, -- cash handed over
    change_paise         INTEGER NOT NULL DEFAULT 0 CHECK (change_paise >= 0),
    note                 TEXT NOT NULL DEFAULT '',
    shop_gstin           TEXT NOT NULL DEFAULT '',
    shop_state           TEXT NOT NULL DEFAULT '',
    customer_state       TEXT NOT NULL DEFAULT ''
);
CREATE INDEX idx_sales_created ON sales(created_at);
CREATE INDEX idx_sales_customer ON sales(customer_id);

CREATE TABLE sale_items (
    id                   INTEGER PRIMARY KEY,
    sale_id              INTEGER NOT NULL REFERENCES sales(id) ON DELETE RESTRICT,
    line_no              INTEGER NOT NULL,
    variant_id           INTEGER NOT NULL REFERENCES variants(id),
    product_name         TEXT NOT NULL,
    size                 TEXT NOT NULL DEFAULT '',
    colour               TEXT NOT NULL DEFAULT '',
    sku                  TEXT NOT NULL,
    barcode              TEXT NOT NULL,
    hsn_code             TEXT NOT NULL DEFAULT '',
    category_name        TEXT NOT NULL DEFAULT '',
    qty                  INTEGER NOT NULL CHECK (qty > 0),
    unit_price_paise     INTEGER NOT NULL CHECK (unit_price_paise >= 0),
    mrp_paise            INTEGER NOT NULL DEFAULT 0,
    unit_cost_paise      INTEGER NOT NULL DEFAULT 0,
    item_discount_type   TEXT NOT NULL DEFAULT 'NONE' CHECK (item_discount_type IN ('NONE','PERCENT','AMOUNT')),
    item_discount_value  INTEGER NOT NULL DEFAULT 0,
    item_discount_paise  INTEGER NOT NULL DEFAULT 0,
    bill_discount_paise  INTEGER NOT NULL DEFAULT 0,
    gst_rate_bp          INTEGER NOT NULL DEFAULT 0,
    taxable_paise        INTEGER NOT NULL DEFAULT 0,
    cgst_paise           INTEGER NOT NULL DEFAULT 0,
    sgst_paise           INTEGER NOT NULL DEFAULT 0,
    igst_paise           INTEGER NOT NULL DEFAULT 0,
    line_total_paise     INTEGER NOT NULL CHECK (line_total_paise >= 0),
    UNIQUE (sale_id, line_no)
);
CREATE INDEX idx_sale_items_sale ON sale_items(sale_id);
CREATE INDEX idx_sale_items_variant ON sale_items(variant_id);

CREATE TABLE sale_payments (
    id           INTEGER PRIMARY KEY,
    sale_id      INTEGER NOT NULL REFERENCES sales(id) ON DELETE RESTRICT,
    method       TEXT NOT NULL CHECK (method IN ('CASH','UPI','CARD','EXCHANGE')),
    amount_paise INTEGER NOT NULL CHECK (amount_paise > 0),
    reference    TEXT NOT NULL DEFAULT ''
);
CREATE INDEX idx_sale_payments_sale ON sale_payments(sale_id);
CREATE INDEX idx_sale_payments_method ON sale_payments(method);

CREATE TABLE sale_cancellations (
    id         INTEGER PRIMARY KEY,
    sale_id    INTEGER NOT NULL UNIQUE REFERENCES sales(id) ON DELETE RESTRICT,
    reason     TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE held_bills (
    id         INTEGER PRIMARY KEY,
    label      TEXT NOT NULL,
    data_json  TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE returns (
    id               INTEGER PRIMARY KEY,
    return_no        TEXT NOT NULL UNIQUE,
    sale_id          INTEGER NOT NULL REFERENCES sales(id) ON DELETE RESTRICT,
    created_at       TEXT NOT NULL,
    refund_method    TEXT NOT NULL CHECK (refund_method IN ('CASH','UPI','CARD','EXCHANGE')),
    refund_paise     INTEGER NOT NULL CHECK (refund_paise >= 0),
    reason           TEXT NOT NULL,
    note             TEXT NOT NULL DEFAULT '',
    reference        TEXT NOT NULL DEFAULT '',
    exchange_sale_id INTEGER REFERENCES sales(id)
);
CREATE INDEX idx_returns_sale ON returns(sale_id);
CREATE INDEX idx_returns_created ON returns(created_at);

CREATE TABLE return_items (
    id            INTEGER PRIMARY KEY,
    return_id     INTEGER NOT NULL REFERENCES returns(id) ON DELETE RESTRICT,
    sale_item_id  INTEGER NOT NULL REFERENCES sale_items(id),
    variant_id    INTEGER NOT NULL REFERENCES variants(id),
    qty           INTEGER NOT NULL CHECK (qty > 0),
    refund_paise  INTEGER NOT NULL CHECK (refund_paise >= 0),
    taxable_paise INTEGER NOT NULL DEFAULT 0,
    cgst_paise    INTEGER NOT NULL DEFAULT 0,
    sgst_paise    INTEGER NOT NULL DEFAULT 0,
    igst_paise    INTEGER NOT NULL DEFAULT 0,
    restocked     INTEGER NOT NULL CHECK (restocked IN (0,1))
);
CREATE INDEX idx_return_items_sale_item ON return_items(sale_item_id);

CREATE TABLE stock_movements (
    id            INTEGER PRIMARY KEY,
    variant_id    INTEGER NOT NULL REFERENCES variants(id) ON DELETE RESTRICT,
    movement_type TEXT NOT NULL CHECK (movement_type IN
                    ('OPENING','RECEIVED','SALE','SALE_CANCEL','RETURN','DAMAGED','LOST','ADJUSTMENT')),
    qty_change    INTEGER NOT NULL CHECK (qty_change <> 0),
    balance_after INTEGER NOT NULL CHECK (balance_after >= 0),
    ref_type      TEXT NOT NULL DEFAULT '',
    ref_id        INTEGER,
    ref_text      TEXT NOT NULL DEFAULT '',
    reason        TEXT NOT NULL DEFAULT '',
    created_at    TEXT NOT NULL
);
CREATE INDEX idx_movements_variant ON stock_movements(variant_id, id);
CREATE INDEX idx_movements_created ON stock_movements(created_at);

CREATE TABLE tag_print_jobs (
    id         INTEGER PRIMARY KEY,
    created_at TEXT NOT NULL,
    label      TEXT NOT NULL,
    items_json TEXT NOT NULL      -- [[variant_id, copies], ...]
);
PRAGMA user_version = 1;
