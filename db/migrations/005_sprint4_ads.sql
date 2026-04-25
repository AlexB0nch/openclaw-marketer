-- Sprint 4: Ads Agent tables

CREATE TABLE IF NOT EXISTS ad_campaigns (
    id          BIGSERIAL PRIMARY KEY,
    product_id  BIGINT REFERENCES products(id) ON DELETE SET NULL,
    platform    TEXT NOT NULL CHECK (platform IN ('yandex', 'youtube')),
    status      TEXT NOT NULL DEFAULT 'draft'
                CHECK (status IN ('draft', 'pending_approval', 'approved', 'running', 'paused', 'rejected', 'completed')),
    config_json JSONB NOT NULL DEFAULT '{}',
    campaign_id_external TEXT,
    budget_rub  NUMERIC(12, 2) NOT NULL DEFAULT 0,
    spent_rub   NUMERIC(12, 2) NOT NULL DEFAULT 0,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    launched_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS ad_variants (
    id          BIGSERIAL PRIMARY KEY,
    campaign_id BIGINT NOT NULL REFERENCES ad_campaigns(id) ON DELETE CASCADE,
    title1      TEXT NOT NULL,
    title2      TEXT NOT NULL,
    text        TEXT NOT NULL,
    display_url TEXT NOT NULL,
    final_url   TEXT NOT NULL,
    clicks      BIGINT NOT NULL DEFAULT 0,
    impressions BIGINT NOT NULL DEFAULT 0,
    ctr         NUMERIC(6, 4) NOT NULL DEFAULT 0,
    status      TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'paused', 'winner'))
);

CREATE TABLE IF NOT EXISTS ad_approvals (
    id          BIGSERIAL PRIMARY KEY,
    campaign_id BIGINT NOT NULL REFERENCES ad_campaigns(id) ON DELETE CASCADE,
    action      TEXT NOT NULL,
    actor       TEXT NOT NULL,
    reason      TEXT,
    timestamp   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS ad_daily_spend (
    id          BIGSERIAL PRIMARY KEY,
    campaign_id BIGINT NOT NULL REFERENCES ad_campaigns(id) ON DELETE CASCADE,
    date        DATE NOT NULL,
    spend_rub   NUMERIC(12, 2) NOT NULL DEFAULT 0,
    clicks      BIGINT NOT NULL DEFAULT 0,
    impressions BIGINT NOT NULL DEFAULT 0,
    ctr         NUMERIC(6, 4) NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_ad_campaigns_product_status ON ad_campaigns(product_id, status);
CREATE INDEX IF NOT EXISTS idx_ad_daily_spend_date ON ad_daily_spend(date);
CREATE INDEX IF NOT EXISTS idx_ad_daily_spend_campaign_date ON ad_daily_spend(campaign_id, date);
