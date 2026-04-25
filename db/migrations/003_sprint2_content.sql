-- Sprint 2: Content Agent tables

CREATE TABLE scheduled_posts (
    id                  BIGSERIAL PRIMARY KEY,
    content_plan_id     BIGINT REFERENCES content_plans(id) ON DELETE SET NULL,
    product_id          BIGINT NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    product_name        TEXT NOT NULL DEFAULT '',
    platform            TEXT NOT NULL,
    topic               TEXT NOT NULL,
    body                TEXT NOT NULL DEFAULT '',
    scheduled_at        TIMESTAMPTZ NOT NULL,
    status              TEXT NOT NULL DEFAULT 'pending',
    published_at        TIMESTAMPTZ,
    telegram_message_id BIGINT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT chk_sp_platform CHECK (platform IN ('telegram', 'habr', 'vc.ru', 'linkedin')),
    CONSTRAINT chk_sp_status   CHECK (status   IN ('pending', 'generated', 'published', 'failed'))
);

CREATE TABLE habr_drafts (
    id          BIGSERIAL PRIMARY KEY,
    product_id  BIGINT NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    product_name TEXT NOT NULL DEFAULT '',
    title       TEXT NOT NULL,
    brief       TEXT NOT NULL,
    body        TEXT NOT NULL,
    word_count  INTEGER NOT NULL DEFAULT 0,
    status      TEXT NOT NULL DEFAULT 'draft',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT chk_hd_status CHECK (status IN ('draft', 'ready', 'exported'))
);

CREATE INDEX idx_scheduled_posts_scheduled_at ON scheduled_posts(scheduled_at);
CREATE INDEX idx_scheduled_posts_status       ON scheduled_posts(status, scheduled_at);
CREATE INDEX idx_habr_drafts_product          ON habr_drafts(product_id);
