-- Sprint 5: TG Scout Agent tables
-- Migration: 006_sprint5_tg_scout.sql

CREATE TABLE IF NOT EXISTS tg_channels (
    id SERIAL PRIMARY KEY,
    username VARCHAR(255) UNIQUE NOT NULL,
    title TEXT NOT NULL DEFAULT '',
    subscriber_count INTEGER DEFAULT 0,
    avg_views FLOAT DEFAULT 0,
    er FLOAT DEFAULT 0,
    description TEXT DEFAULT '',
    contact_username VARCHAR(255),
    contact_email VARCHAR(255),
    topics JSONB DEFAULT '[]',
    source VARCHAR(50) DEFAULT 'telethon',
    status VARCHAR(50) DEFAULT 'new',
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS tg_channel_scores (
    id SERIAL PRIMARY KEY,
    channel_id INTEGER REFERENCES tg_channels(id) ON DELETE CASCADE,
    product TEXT NOT NULL,
    score INTEGER DEFAULT 0,
    breakdown JSONB DEFAULT '{}',
    scored_at TIMESTAMP DEFAULT NOW(),
    UNIQUE (channel_id, product)
);

CREATE TABLE IF NOT EXISTS tg_pitch_drafts (
    id SERIAL PRIMARY KEY,
    channel_id INTEGER REFERENCES tg_channels(id) ON DELETE CASCADE,
    product TEXT NOT NULL,
    pitch_short TEXT,
    pitch_medium TEXT,
    pitch_long TEXT,
    status VARCHAR(50) DEFAULT 'pending_approval',
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS tg_channel_outreach (
    id SERIAL PRIMARY KEY,
    channel_id INTEGER REFERENCES tg_channels(id) ON DELETE CASCADE,
    product TEXT,
    action VARCHAR(50) NOT NULL,
    actor TEXT,
    result TEXT,
    timestamp TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS tg_mention_log (
    id SERIAL PRIMARY KEY,
    keyword TEXT NOT NULL,
    message_id BIGINT UNIQUE NOT NULL,
    channel_username TEXT,
    message_text TEXT,
    detected_at TIMESTAMP DEFAULT NOW()
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_tg_channels_status
    ON tg_channels (status);

CREATE INDEX IF NOT EXISTS idx_tg_channel_scores_product_score
    ON tg_channel_scores (product, score DESC);

CREATE INDEX IF NOT EXISTS idx_tg_pitch_drafts_status
    ON tg_pitch_drafts (status);

CREATE INDEX IF NOT EXISTS idx_tg_mention_log_keyword
    ON tg_mention_log (keyword);
