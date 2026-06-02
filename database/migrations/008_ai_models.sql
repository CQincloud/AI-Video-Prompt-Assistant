BEGIN;

CREATE TABLE IF NOT EXISTS ai_models (
    id BIGSERIAL PRIMARY KEY,

    provider VARCHAR(50) NOT NULL DEFAULT 'dashscope',
    model_id VARCHAR(120) NOT NULL,
    display_name VARCHAR(120) NOT NULL,

    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    is_default BOOLEAN NOT NULL DEFAULT FALSE,
    is_deleted BOOLEAN NOT NULL DEFAULT FALSE,

    sort_order INTEGER NOT NULL DEFAULT 100,
    min_membership_level VARCHAR(50),
    access_scope VARCHAR(50) NOT NULL DEFAULT 'all',

    remark TEXT,

    created_by BIGINT REFERENCES users(id),
    updated_by BIGINT REFERENCES users(id),

    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE UNIQUE INDEX IF NOT EXISTS uniq_ai_models_provider_model_active
ON ai_models(provider, model_id)
WHERE is_deleted = FALSE;

CREATE UNIQUE INDEX IF NOT EXISTS uniq_ai_models_default_active
ON ai_models(provider)
WHERE is_default = TRUE AND enabled = TRUE AND is_deleted = FALSE;

CREATE INDEX IF NOT EXISTS idx_ai_models_enabled_deleted
ON ai_models(enabled, is_deleted);

CREATE INDEX IF NOT EXISTS idx_ai_models_sort_order
ON ai_models(sort_order, id);

CREATE TABLE IF NOT EXISTS model_usage_logs (
    id BIGSERIAL PRIMARY KEY,

    user_id BIGINT REFERENCES users(id) ON DELETE SET NULL,
    ai_model_id BIGINT REFERENCES ai_models(id) ON DELETE SET NULL,

    provider VARCHAR(50) NOT NULL DEFAULT 'dashscope',
    model_id VARCHAR(120) NOT NULL,

    session_id TEXT,
    mode VARCHAR(30) NOT NULL DEFAULT 'chat',
    prompt_template VARCHAR(100),

    success BOOLEAN NOT NULL DEFAULT TRUE,
    duration_ms INTEGER,

    input_tokens INTEGER,
    output_tokens INTEGER,
    total_tokens INTEGER,

    error_message TEXT,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,

    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_model_usage_logs_model_created
ON model_usage_logs(model_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_model_usage_logs_ai_model_created
ON model_usage_logs(ai_model_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_model_usage_logs_user_created
ON model_usage_logs(user_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_model_usage_logs_success_created
ON model_usage_logs(success, created_at DESC);

DROP TRIGGER IF EXISTS trigger_ai_models_updated_at ON ai_models;
CREATE TRIGGER trigger_ai_models_updated_at
BEFORE UPDATE ON ai_models
FOR EACH ROW
EXECUTE FUNCTION update_updated_at_column();

INSERT INTO ai_models (provider, model_id, display_name, enabled, is_default, sort_order, remark)
VALUES
    ('dashscope', 'qwen-max', '通义千问 Max', TRUE, TRUE, 10, '默认 RAG 聊天模型'),
    ('dashscope', 'qwen-plus', '通义千问 Plus', TRUE, FALSE, 20, '平衡质量与速度'),
    ('dashscope', 'qwen-turbo', '通义千问 Turbo', TRUE, FALSE, 30, '更快响应')
ON CONFLICT DO NOTHING;

COMMIT;
