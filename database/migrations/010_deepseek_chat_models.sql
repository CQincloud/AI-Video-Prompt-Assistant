BEGIN;

UPDATE ai_models m
SET provider = 'deepseek',
    display_name = CASE
        WHEN m.model_id = 'deepseek-v4-flash' THEN 'DeepSeek V4 Flash'
        WHEN m.model_id = 'deepseek-v4-pro' THEN 'DeepSeek V4 Pro'
        ELSE m.display_name
    END,
    remark = COALESCE(NULLIF(m.remark, ''), 'Moved from dashscope to deepseek provider')
WHERE m.provider = 'dashscope'
  AND m.model_id IN ('deepseek-v4-flash', 'deepseek-v4-pro')
  AND m.is_deleted = FALSE
  AND NOT EXISTS (
      SELECT 1
      FROM ai_models existing
      WHERE existing.provider = 'deepseek'
        AND existing.model_id = m.model_id
        AND existing.is_deleted = FALSE
        AND existing.id <> m.id
  );

UPDATE ai_models m
SET is_deleted = TRUE,
    enabled = FALSE,
    is_default = FALSE,
    remark = COALESCE(NULLIF(m.remark, ''), 'Duplicate DeepSeek model under dashscope provider was retired')
WHERE m.provider = 'dashscope'
  AND m.model_id IN ('deepseek-v4-flash', 'deepseek-v4-pro')
  AND m.is_deleted = FALSE
  AND EXISTS (
      SELECT 1
      FROM ai_models existing
      WHERE existing.provider = 'deepseek'
        AND existing.model_id = m.model_id
        AND existing.is_deleted = FALSE
        AND existing.id <> m.id
  );

INSERT INTO ai_models (provider, model_id, display_name, enabled, is_default, is_deleted, sort_order, remark)
VALUES
    ('deepseek', 'deepseek-v4-flash', 'DeepSeek V4 Flash', FALSE, FALSE, FALSE, 60, 'DeepSeek official chat model; requires DEEPSEEK_API_KEY'),
    ('deepseek', 'deepseek-v4-pro', 'DeepSeek V4 Pro', FALSE, FALSE, FALSE, 70, 'DeepSeek official chat model; first phase uses non-thinking mode')
ON CONFLICT (provider, model_id) WHERE is_deleted = FALSE
DO UPDATE SET
    display_name = EXCLUDED.display_name,
    is_deleted = FALSE,
    sort_order = EXCLUDED.sort_order,
    remark = EXCLUDED.remark;

COMMIT;
