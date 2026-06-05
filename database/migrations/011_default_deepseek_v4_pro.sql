BEGIN;

UPDATE ai_models
SET is_default = FALSE
WHERE is_deleted = FALSE;

UPDATE ai_models
SET enabled = TRUE,
    is_default = TRUE,
    display_name = 'DeepSeek V4 Pro',
    sort_order = 70,
    remark = 'DeepSeek official default chat model; first phase uses non-thinking mode'
WHERE provider = 'deepseek'
  AND model_id = 'deepseek-v4-pro'
  AND is_deleted = FALSE;

COMMIT;
