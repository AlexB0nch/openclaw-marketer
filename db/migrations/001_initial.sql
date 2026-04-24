-- Sprint 0: initial schema

CREATE TABLE IF NOT EXISTS products (
    id          BIGSERIAL PRIMARY KEY,
    name        TEXT        NOT NULL,
    description TEXT,
    url         TEXT,
    active      BOOLEAN     NOT NULL DEFAULT TRUE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS campaigns (
    id          BIGSERIAL PRIMARY KEY,
    product_id  BIGINT      NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    name        TEXT        NOT NULL,
    platform    TEXT        NOT NULL, -- 'yandex_direct' | 'google_ads' | 'telegram'
    status      TEXT        NOT NULL DEFAULT 'draft', -- draft|active|paused|archived
    budget_rub  NUMERIC(12, 2),
    starts_at   TIMESTAMPTZ,
    ends_at     TIMESTAMPTZ,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS content_items (
    id          BIGSERIAL PRIMARY KEY,
    campaign_id BIGINT      REFERENCES campaigns(id) ON DELETE SET NULL,
    type        TEXT        NOT NULL, -- 'post' | 'ad_copy' | 'banner' | 'video_script'
    title       TEXT,
    body        TEXT        NOT NULL,
    status      TEXT        NOT NULL DEFAULT 'draft', -- draft|review|approved|published
    published_at TIMESTAMPTZ,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS tg_channels (
    id          BIGSERIAL PRIMARY KEY,
    username    TEXT        NOT NULL UNIQUE,
    title       TEXT,
    subscriber_count BIGINT,
    category    TEXT,
    cpm_rub     NUMERIC(10, 2),
    last_checked_at TIMESTAMPTZ,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS metrics (
    id           BIGSERIAL PRIMARY KEY,
    campaign_id  BIGINT      NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
    date         DATE        NOT NULL,
    impressions  BIGINT      NOT NULL DEFAULT 0,
    clicks       BIGINT      NOT NULL DEFAULT 0,
    spend_rub    NUMERIC(12, 2) NOT NULL DEFAULT 0,
    conversions  BIGINT      NOT NULL DEFAULT 0,
    UNIQUE (campaign_id, date)
);

CREATE TABLE IF NOT EXISTS events_calendar (
    id          BIGSERIAL PRIMARY KEY,
    title       TEXT        NOT NULL,
    description TEXT,
    event_date  DATE        NOT NULL,
    type        TEXT        NOT NULL DEFAULT 'promo', -- promo|holiday|launch|review
    campaign_id BIGINT      REFERENCES campaigns(id) ON DELETE SET NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_campaigns_product  ON campaigns(product_id);
CREATE INDEX IF NOT EXISTS idx_content_campaign   ON content_items(campaign_id);
CREATE INDEX IF NOT EXISTS idx_metrics_campaign   ON metrics(campaign_id);
CREATE INDEX IF NOT EXISTS idx_metrics_date       ON metrics(date);
CREATE INDEX IF NOT EXISTS idx_events_date        ON events_calendar(event_date);
