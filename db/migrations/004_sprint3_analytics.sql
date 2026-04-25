-- Sprint 3: Analytics Agent schema additions
-- Run after 003_sprint2_content.sql

-- ── Indexes on existing metrics table for fast aggregation ───────────────────
CREATE INDEX IF NOT EXISTS idx_metrics_date
    ON metrics (date);

CREATE INDEX IF NOT EXISTS idx_metrics_date_campaign
    ON metrics (date, campaign_id);

-- ── Post-level Telegram metrics ──────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS post_metrics (
    id           BIGSERIAL PRIMARY KEY,
    post_id      BIGINT REFERENCES scheduled_posts (id) ON DELETE CASCADE,
    product_id   BIGINT REFERENCES products (id),
    date         DATE NOT NULL,
    views        BIGINT NOT NULL DEFAULT 0,
    forwards     BIGINT NOT NULL DEFAULT 0,
    reactions    BIGINT NOT NULL DEFAULT 0,
    collected_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_post_metrics_date_product
    ON post_metrics (date, product_id);

-- ── Analytics snapshots (daily per-product JSONB snapshots) ─────────────────
CREATE TABLE IF NOT EXISTS analytics_snapshots (
    id            BIGSERIAL PRIMARY KEY,
    snapshot_date DATE NOT NULL,
    product_id    BIGINT REFERENCES products (id),
    data          JSONB NOT NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_analytics_snapshots_date_product
    ON analytics_snapshots (snapshot_date, product_id);
