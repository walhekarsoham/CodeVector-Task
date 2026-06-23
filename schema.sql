-- ─────────────────────────────────────────────────────────────────────────────
-- schema.sql — products table + pagination indexes
--
-- KEY DECISIONS:
--
--   UUID primary key (gen_random_uuid())
--     • Avoids sequential integer IDs that leak row counts to clients.
--     • gen_random_uuid() is built into PostgreSQL 13+ (no pgcrypto needed),
--       and Neon runs PostgreSQL 15+, so no extension step required.
--     • Globally unique — safe if you ever shard or merge datasets.
--
--   price as NUMERIC(10, 2)
--     • FLOAT / DOUBLE store prices as binary fractions, causing rounding
--       errors (e.g. ₹99.99 → ₹99.98999…). NUMERIC is exact decimal storage,
--       which is the correct type for any monetary value.
--
--   Composite index (created_at DESC, id DESC)
--     • Powers "keyset" / cursor pagination on the default sort order.
--     • Including `id` as a tie-breaker makes the cursor deterministic when
--       two rows share the same timestamp — without it, pages can overlap or
--       skip rows.
--     • DESC order mirrors the query's ORDER BY so Postgres can scan forward
--       instead of sorting a backward scan.
--
--   Composite index (category, created_at DESC, id DESC)
--     • Same keyset logic, but scoped to a single category. The leading
--       `category` column lets Postgres do an index seek on equality before
--       walking the time-ordered suffix — an index on just created_at would
--       still require filtering out other categories row-by-row.
--     • Covers the most common product-listing query: "give me page N of
--       Electronics sorted by newest first."
--
--   updated_at (timestamptz, no auto-trigger)
--     • Stored here so the application layer can update it explicitly.
--       A trigger could be added later; skipping it now keeps the schema
--       simple and avoids hidden overhead on every UPDATE.
-- ─────────────────────────────────────────────────────────────────────────────

-- Drop and recreate for a clean run (safe during development).
DROP TABLE IF EXISTS products;

CREATE TABLE products (
    id          UUID          PRIMARY KEY DEFAULT gen_random_uuid(),
    name        TEXT          NOT NULL,
    -- 8–10 realistic categories; enforced at the app layer, not as an enum,
    -- so new categories can be added without an ALTER TABLE migration.
    category    TEXT          NOT NULL,
    price       NUMERIC(10,2) NOT NULL,
    created_at  TIMESTAMPTZ   NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ   NOT NULL DEFAULT now()
);

-- ── Index 1: general pagination (newest first, stable cursor) ──────────────
-- Used by: GET /products?cursor=...&limit=...
CREATE INDEX idx_products_created_at_id
    ON products (created_at DESC, id DESC);

-- ── Index 2: category-filtered pagination ─────────────────────────────────
-- Used by: GET /products?category=Electronics&cursor=...&limit=...
CREATE INDEX idx_products_category_created_at_id
    ON products (category, created_at DESC, id DESC);
