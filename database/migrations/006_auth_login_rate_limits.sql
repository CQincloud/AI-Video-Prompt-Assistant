BEGIN;

CREATE TABLE IF NOT EXISTS auth_login_attempts (
    id BIGSERIAL PRIMARY KEY,
    mobile VARCHAR(20) NOT NULL,
    ip VARCHAR(45),
    success BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_auth_login_attempts_mobile_created
ON auth_login_attempts(mobile, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_auth_login_attempts_ip_created
ON auth_login_attempts(ip, created_at DESC)
WHERE ip IS NOT NULL;

CREATE TABLE IF NOT EXISTS auth_login_blocks (
    scope VARCHAR(20) NOT NULL
        CHECK (scope IN ('mobile', 'ip')),
    identifier TEXT NOT NULL,
    blocked_until TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (scope, identifier)
);

COMMIT;
