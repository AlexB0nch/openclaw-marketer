-- Sprint 6: Events Agent tables

CREATE TABLE IF NOT EXISTS events_calendar (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    url TEXT NOT NULL,
    start_date DATE,
    cfp_deadline DATE,
    city TEXT,
    is_online BOOL NOT NULL DEFAULT false,
    audience_size INT,
    description TEXT,
    topics JSONB NOT NULL DEFAULT '[]',
    source TEXT,
    status TEXT NOT NULL DEFAULT 'new',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(name, start_date)
);

CREATE TABLE IF NOT EXISTS events_abstracts (
    id SERIAL PRIMARY KEY,
    event_id INT NOT NULL REFERENCES events_calendar(id) ON DELETE CASCADE,
    product TEXT NOT NULL,
    abstract_text TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(event_id, product)
);

CREATE TABLE IF NOT EXISTS events_applications (
    id SERIAL PRIMARY KEY,
    event_id INT NOT NULL REFERENCES events_calendar(id) ON DELETE CASCADE,
    product TEXT NOT NULL,
    action TEXT NOT NULL DEFAULT 'registered',
    note TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_events_calendar_status ON events_calendar(status);
CREATE INDEX IF NOT EXISTS idx_events_calendar_cfp_deadline ON events_calendar(cfp_deadline);
CREATE INDEX IF NOT EXISTS idx_events_calendar_start_date ON events_calendar(start_date);
CREATE INDEX IF NOT EXISTS idx_events_abstracts_event_id ON events_abstracts(event_id);
