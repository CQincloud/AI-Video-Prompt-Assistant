BEGIN;

CREATE TABLE IF NOT EXISTS users (
    id BIGSERIAL PRIMARY KEY,
    mobile VARCHAR(20) NOT NULL UNIQUE,
    nickname VARCHAR(50) NOT NULL DEFAULT '',
    avatar_url TEXT,
    role VARCHAR(20) NOT NULL DEFAULT 'user'
        CHECK (role IN ('user', 'admin', 'super_admin')),
    status SMALLINT NOT NULL DEFAULT 1
        CHECK (status IN (0, 1)),
    last_login_at TIMESTAMPTZ,
    last_login_ip VARCHAR(45),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    points INTEGER NOT NULL DEFAULT 0
        CHECK (points >= 0)
);

CREATE TABLE IF NOT EXISTS sms_codes (
    id BIGSERIAL PRIMARY KEY,
    mobile VARCHAR(20) NOT NULL,
    code_hash TEXT NOT NULL,
    used BOOLEAN NOT NULL DEFAULT FALSE,
    expires_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    ip VARCHAR(45)
);

CREATE INDEX IF NOT EXISTS idx_sms_codes_mobile_created_at
ON sms_codes(mobile, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_sms_codes_mobile_used_expires
ON sms_codes(mobile, used, expires_at);

CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMPTZ NOT NULL,
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    ip VARCHAR(45),
    user_agent TEXT
);

CREATE INDEX IF NOT EXISTS idx_sessions_user_id
ON sessions(user_id);

CREATE INDEX IF NOT EXISTS idx_sessions_expires_at
ON sessions(expires_at);

CREATE TABLE IF NOT EXISTS membership_levels (
    id BIGSERIAL PRIMARY KEY,
    code VARCHAR(20) NOT NULL UNIQUE,
    name VARCHAR(50) NOT NULL,
    min_points INTEGER NOT NULL CHECK (min_points >= 0),
    max_points INTEGER,
    sort_order INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CHECK (max_points IS NULL OR max_points > min_points)
);

CREATE INDEX IF NOT EXISTS idx_membership_levels_points
ON membership_levels(min_points, max_points);

CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trigger_users_updated_at ON users;
CREATE TRIGGER trigger_users_updated_at
BEFORE UPDATE ON users
FOR EACH ROW
EXECUTE FUNCTION update_updated_at_column();

DROP TRIGGER IF EXISTS trigger_membership_levels_updated_at ON membership_levels;
CREATE TRIGGER trigger_membership_levels_updated_at
BEFORE UPDATE ON membership_levels
FOR EACH ROW
EXECUTE FUNCTION update_updated_at_column();

INSERT INTO membership_levels (code, name, min_points, max_points, sort_order)
VALUES
    ('normal', '普通会员', 0, 100, 1),
    ('premium', '高级会员', 100, 1000, 2),
    ('super', '超级会员', 1000, NULL, 3)
ON CONFLICT (code) DO NOTHING;

INSERT INTO users (mobile, nickname, role, status, points)
VALUES ('18372086442', '超级管理员', 'super_admin', 1, 0)
ON CONFLICT (mobile) DO NOTHING;

COMMIT;
