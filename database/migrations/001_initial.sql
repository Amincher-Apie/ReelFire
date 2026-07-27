PRAGMA foreign_keys = ON;

BEGIN IMMEDIATE;

CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    applied_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    display_name TEXT,
    role TEXT NOT NULL DEFAULT 'user'
        CHECK (role IN ('user', 'admin')),
    is_active INTEGER NOT NULL DEFAULT 1
        CHECK (is_active IN (0, 1)),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    last_login_at TEXT
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_users_username
ON users(username COLLATE NOCASE);

CREATE TABLE IF NOT EXISTS projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    owner_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    description TEXT,
    game_type TEXT,
    status TEXT NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'archived')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (owner_id)
        REFERENCES users(id)
        ON UPDATE CASCADE
        ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS idx_projects_owner
ON projects(owner_id);

CREATE TABLE IF NOT EXISTS assets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL,
    original_name TEXT NOT NULL,
    stored_path TEXT NOT NULL,
    media_type TEXT NOT NULL DEFAULT 'video'
        CHECK (media_type IN ('video', 'image')),
    mime_type TEXT,
    size_bytes INTEGER NOT NULL
        CHECK (size_bytes >= 0),
    sha256 TEXT,
    duration REAL,
    width INTEGER,
    height INTEGER,
    fps REAL,
    source TEXT,
    license_note TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (project_id)
        REFERENCES projects(id)
        ON UPDATE CASCADE
        ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_assets_project
ON assets(project_id);

CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id TEXT NOT NULL UNIQUE,
    project_id INTEGER NOT NULL,
    asset_id INTEGER NOT NULL,
    created_by INTEGER NOT NULL,
    status TEXT NOT NULL
        CHECK (
            status IN (
                'created',
                'queued',
                'running',
                'completed',
                'failed'
            )
        ),
    job_json_path TEXT NOT NULL,
    report_json_path TEXT,
    rough_cut_path TEXT,
    error_code TEXT,
    error_message TEXT,
    created_at TEXT NOT NULL,
    started_at TEXT,
    completed_at TEXT,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (project_id)
        REFERENCES projects(id)
        ON UPDATE CASCADE
        ON DELETE CASCADE,
    FOREIGN KEY (asset_id)
        REFERENCES assets(id)
        ON UPDATE CASCADE
        ON DELETE RESTRICT,
    FOREIGN KEY (created_by)
        REFERENCES users(id)
        ON UPDATE CASCADE
        ON DELETE RESTRICT
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_jobs_public_job_id
ON jobs(job_id);

CREATE INDEX IF NOT EXISTS idx_jobs_project_status
ON jobs(project_id, status);

CREATE INDEX IF NOT EXISTS idx_jobs_asset
ON jobs(asset_id);

CREATE TABLE IF NOT EXISTS reviews (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id INTEGER NOT NULL,
    reviewer_id INTEGER NOT NULL,
    status TEXT NOT NULL
        CHECK (status IN ('approved', 'pending', 'rejected')),
    labels_json TEXT,
    note TEXT,
    segments_json TEXT,
    keyframes_json TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (job_id)
        REFERENCES jobs(id)
        ON UPDATE CASCADE
        ON DELETE CASCADE,
    FOREIGN KEY (reviewer_id)
        REFERENCES users(id)
        ON UPDATE CASCADE
        ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS idx_reviews_job
ON reviews(job_id, updated_at);

CREATE TABLE IF NOT EXISTS agent_calls (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id INTEGER NOT NULL,
    requested_by INTEGER,
    status TEXT NOT NULL
        CHECK (
            status IN (
                'queued',
                'running',
                'completed',
                'failed',
                'needs_review'
            )
        ),
    model_name TEXT,
    prompt_version TEXT,
    input_summary TEXT,
    output_summary TEXT,
    tool_trace_json TEXT,
    references_json TEXT,
    result_path TEXT,
    duration_ms INTEGER
        CHECK (duration_ms IS NULL OR duration_ms >= 0),
    error_code TEXT,
    error_message TEXT,
    created_at TEXT NOT NULL,
    completed_at TEXT,
    FOREIGN KEY (job_id)
        REFERENCES jobs(id)
        ON UPDATE CASCADE
        ON DELETE CASCADE,
    FOREIGN KEY (requested_by)
        REFERENCES users(id)
        ON UPDATE CASCADE
        ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_agent_calls_job_status
ON agent_calls(job_id, status);

CREATE TABLE IF NOT EXISTS knowledge_documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER,
    title TEXT NOT NULL,
    source TEXT NOT NULL,
    license_note TEXT,
    document_path TEXT NOT NULL,
    index_path TEXT,
    embedding_model TEXT,
    chunk_count INTEGER NOT NULL DEFAULT 0
        CHECK (chunk_count >= 0),
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'indexing', 'ready', 'failed')),
    error_message TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (project_id)
        REFERENCES projects(id)
        ON UPDATE CASCADE
        ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_knowledge_project_status
ON knowledge_documents(project_id, status);

INSERT OR IGNORE INTO schema_version (
    version,
    name,
    applied_at
)
VALUES (
    1,
    'initial',
    strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
);

COMMIT;
