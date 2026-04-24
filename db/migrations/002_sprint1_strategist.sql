-- Sprint 1: Strategist Agent tables
-- Content plans and approval workflow

CREATE TABLE content_plans (
    id BIGSERIAL PRIMARY KEY,
    week_start_date DATE NOT NULL,
    week_end_date DATE NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending_approval' CHECK (status IN ('pending_approval', 'approved', 'rejected', 'archived')),
    plan_json JSONB NOT NULL,
    created_by_agent TEXT NOT NULL DEFAULT 'strategist',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    approved_by_user TEXT,
    approval_reason TEXT,
    approved_at TIMESTAMPTZ,
    UNIQUE (week_start_date)
);

CREATE TABLE plan_approvals (
    id BIGSERIAL PRIMARY KEY,
    plan_id BIGINT NOT NULL REFERENCES content_plans(id) ON DELETE CASCADE,
    action TEXT NOT NULL CHECK (action IN ('submitted', 'approved', 'rejected', 'edited')),
    actor TEXT NOT NULL,
    reason TEXT,
    timestamp TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_content_plans_status_created_at ON content_plans(status, created_at DESC);
CREATE INDEX idx_plan_approvals_plan_id_timestamp ON plan_approvals(plan_id, timestamp DESC);
