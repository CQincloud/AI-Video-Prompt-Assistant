BEGIN;

CREATE TABLE IF NOT EXISTS chat_attachments (
    id BIGSERIAL PRIMARY KEY,
    message_id BIGINT REFERENCES chat_messages(id) ON DELETE CASCADE,
    session_id TEXT NOT NULL REFERENCES chat_sessions(id) ON DELETE CASCADE,
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    purpose VARCHAR(40) NOT NULL
        CHECK (purpose IN (
            'vision',
            'generation_reference',
            'generated_image'
        )),
    file_name TEXT NOT NULL DEFAULT '',
    file_path TEXT,
    file_url TEXT,
    mime_type VARCHAR(120) NOT NULL DEFAULT '',
    file_size BIGINT NOT NULL DEFAULT 0,
    width INTEGER,
    height INTEGER,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_chat_attachments_message
ON chat_attachments(message_id);

CREATE INDEX IF NOT EXISTS idx_chat_attachments_user_created
ON chat_attachments(user_id, created_at DESC);

COMMIT;
