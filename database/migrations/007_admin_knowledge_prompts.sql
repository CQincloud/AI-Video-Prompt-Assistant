BEGIN;

CREATE TABLE IF NOT EXISTS kb_documents (
    id BIGSERIAL PRIMARY KEY,

    original_file_name VARCHAR(255) NOT NULL,
    stored_file_name VARCHAR(255) NOT NULL,
    file_path TEXT NOT NULL,

    file_type VARCHAR(20) NOT NULL,
    mime_type VARCHAR(100),
    file_size BIGINT NOT NULL DEFAULT 0,
    file_hash VARCHAR(128),

    title VARCHAR(255),
    description TEXT,
    category VARCHAR(100) NOT NULL DEFAULT 'default',

    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    is_deleted BOOLEAN NOT NULL DEFAULT FALSE,

    vector_status VARCHAR(30) NOT NULL DEFAULT 'pending'
        CHECK (vector_status IN ('pending', 'processing', 'success', 'failed')),

    chunk_count INTEGER NOT NULL DEFAULT 0,

    collection_name VARCHAR(100) NOT NULL DEFAULT 'biz',
    embedding_model VARCHAR(100),

    created_by BIGINT REFERENCES users(id),
    updated_by BIGINT REFERENCES users(id),

    error_message TEXT,

    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_kb_documents_status
ON kb_documents(vector_status);

CREATE INDEX IF NOT EXISTS idx_kb_documents_category
ON kb_documents(category);

CREATE INDEX IF NOT EXISTS idx_kb_documents_enabled_deleted
ON kb_documents(enabled, is_deleted);

CREATE INDEX IF NOT EXISTS idx_kb_documents_created_at
ON kb_documents(created_at DESC);

CREATE INDEX IF NOT EXISTS idx_kb_documents_file_hash
ON kb_documents(file_hash);

CREATE TABLE IF NOT EXISTS kb_document_chunks (
    id BIGSERIAL PRIMARY KEY,

    document_id BIGINT NOT NULL REFERENCES kb_documents(id) ON DELETE CASCADE,

    chunk_index INTEGER NOT NULL,
    content TEXT NOT NULL,

    content_hash VARCHAR(128),
    token_count INTEGER NOT NULL DEFAULT 0,

    vector_id VARCHAR(100),
    collection_name VARCHAR(100) NOT NULL DEFAULT 'biz',

    enabled BOOLEAN NOT NULL DEFAULT TRUE,

    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,

    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_kb_document_chunks_document_id
ON kb_document_chunks(document_id);

CREATE UNIQUE INDEX IF NOT EXISTS uniq_kb_document_chunks_doc_index
ON kb_document_chunks(document_id, chunk_index);

CREATE INDEX IF NOT EXISTS idx_kb_document_chunks_vector_id
ON kb_document_chunks(vector_id);

CREATE INDEX IF NOT EXISTS idx_kb_document_chunks_enabled
ON kb_document_chunks(enabled);

CREATE TABLE IF NOT EXISTS kb_index_tasks (
    id BIGSERIAL PRIMARY KEY,

    document_id BIGINT REFERENCES kb_documents(id) ON DELETE CASCADE,

    task_type VARCHAR(30) NOT NULL
        CHECK (task_type IN ('upload_index', 'reindex', 'delete_index')),

    status VARCHAR(30) NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'processing', 'success', 'failed')),

    chunk_count INTEGER NOT NULL DEFAULT 0,
    vector_count INTEGER NOT NULL DEFAULT 0,

    error_message TEXT,

    created_by BIGINT REFERENCES users(id),

    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_kb_index_tasks_document_id
ON kb_index_tasks(document_id);

CREATE INDEX IF NOT EXISTS idx_kb_index_tasks_status
ON kb_index_tasks(status);

CREATE INDEX IF NOT EXISTS idx_kb_index_tasks_created_at
ON kb_index_tasks(created_at DESC);

CREATE TABLE IF NOT EXISTS system_prompts (
    id BIGSERIAL PRIMARY KEY,

    prompt_key VARCHAR(100) NOT NULL,
    prompt_name VARCHAR(100) NOT NULL,
    prompt_type VARCHAR(100) NOT NULL,

    content TEXT NOT NULL,

    version INTEGER NOT NULL DEFAULT 1,
    enabled BOOLEAN NOT NULL DEFAULT FALSE,

    remark TEXT,

    created_by BIGINT REFERENCES users(id),
    updated_by BIGINT REFERENCES users(id),

    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_system_prompts_key
ON system_prompts(prompt_key);

CREATE INDEX IF NOT EXISTS idx_system_prompts_type
ON system_prompts(prompt_type);

CREATE UNIQUE INDEX IF NOT EXISTS uniq_system_prompts_key_version
ON system_prompts(prompt_key, version);

CREATE UNIQUE INDEX IF NOT EXISTS uniq_system_prompts_active_key
ON system_prompts(prompt_key)
WHERE enabled = TRUE;

DROP TRIGGER IF EXISTS trigger_kb_documents_updated_at ON kb_documents;
CREATE TRIGGER trigger_kb_documents_updated_at
BEFORE UPDATE ON kb_documents
FOR EACH ROW
EXECUTE FUNCTION update_updated_at_column();

DROP TRIGGER IF EXISTS trigger_system_prompts_updated_at ON system_prompts;
CREATE TRIGGER trigger_system_prompts_updated_at
BEFORE UPDATE ON system_prompts
FOR EACH ROW
EXECUTE FUNCTION update_updated_at_column();

COMMIT;
