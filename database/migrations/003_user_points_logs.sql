BEGIN;

CREATE TABLE IF NOT EXISTS user_points_logs (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL
        REFERENCES users(id)
        ON DELETE CASCADE,
    change_type VARCHAR(20) NOT NULL
        CHECK (change_type IN ('add', 'subtract', 'adjust')),
    change_amount INTEGER NOT NULL
        CHECK (change_amount > 0),
    before_points INTEGER NOT NULL
        CHECK (before_points >= 0),
    after_points INTEGER NOT NULL
        CHECK (after_points >= 0),
    reason TEXT NOT NULL,
    operator_id BIGINT
        REFERENCES users(id)
        ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CHECK (
        (change_type = 'add' AND after_points = before_points + change_amount)
        OR
        (change_type = 'subtract' AND after_points = before_points - change_amount)
        OR
        (change_type = 'adjust')
    )
);

CREATE INDEX IF NOT EXISTS idx_user_points_logs_user_created
ON user_points_logs(user_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_user_points_logs_operator_created
ON user_points_logs(operator_id, created_at DESC);

COMMIT;
