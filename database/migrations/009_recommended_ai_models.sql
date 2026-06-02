BEGIN;

UPDATE ai_models
SET is_default = FALSE,
    updated_at = CURRENT_TIMESTAMP
WHERE provider = 'dashscope'
  AND is_deleted = FALSE;

INSERT INTO ai_models (provider, model_id, display_name, enabled, is_default, is_deleted, sort_order, remark)
VALUES
    ('dashscope', 'qwen3.7-plus', '通义千问 3.7 Plus', TRUE, TRUE, FALSE, 10, '默认主力模型，兼顾质量、速度与成本'),
    ('dashscope', 'qwen3.7-max', '通义千问 3.7 Max', TRUE, FALSE, FALSE, 20, '高质量复杂任务模型'),
    ('dashscope', 'qwen3.6-flash', '通义千问 3.6 Flash', TRUE, FALSE, FALSE, 30, '快速低成本模型'),
    ('dashscope', 'qwen3.6-plus', '通义千问 3.6 Plus', TRUE, FALSE, FALSE, 40, '均衡模型，适合需要视觉能力的任务'),
    ('dashscope', 'qwen-plus', '通义千问 Plus', TRUE, FALSE, FALSE, 50, '兼容保留，可逐步下线')
ON CONFLICT (provider, model_id) WHERE is_deleted = FALSE
DO UPDATE SET
    display_name = EXCLUDED.display_name,
    enabled = EXCLUDED.enabled,
    is_default = EXCLUDED.is_default,
    sort_order = EXCLUDED.sort_order,
    remark = EXCLUDED.remark,
    updated_at = CURRENT_TIMESTAMP;

UPDATE ai_models
SET enabled = FALSE,
    is_default = FALSE,
    is_deleted = TRUE,
    remark = COALESCE(NULLIF(remark, ''), '已由推荐模型白名单替换'),
    updated_at = CURRENT_TIMESTAMP
WHERE provider = 'dashscope'
  AND model_id IN ('qwen-max', 'qwen-turbo')
  AND is_deleted = FALSE;

COMMIT;
