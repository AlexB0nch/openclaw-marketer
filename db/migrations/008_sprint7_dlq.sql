-- Sprint 7: Dead Letter Queue for failed agent tasks

CREATE TABLE IF NOT EXISTS dead_letter_queue (
    id BIGSERIAL PRIMARY KEY,
    agent TEXT NOT NULL,
    task TEXT NOT NULL,
    payload JSONB DEFAULT '{}',
    error_message TEXT,
    traceback TEXT,
    attempts INT DEFAULT 1,
    status TEXT DEFAULT 'pending',
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_dlq_status_attempts ON dead_letter_queue(status, attempts);
CREATE INDEX IF NOT EXISTS idx_dlq_agent_created ON dead_letter_queue(agent, created_at);
