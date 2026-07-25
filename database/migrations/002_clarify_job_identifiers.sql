PRAGMA foreign_keys = ON;

BEGIN IMMEDIATE;

ALTER TABLE jobs
RENAME COLUMN job_id TO public_job_id;

ALTER TABLE reviews
RENAME COLUMN job_id TO job_row_id;

ALTER TABLE agent_calls
RENAME COLUMN job_id TO job_row_id;

INSERT INTO schema_version (
    version,
    name,
    applied_at
)
VALUES (
    2,
    'clarify_job_identifiers',
    strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
);

COMMIT;
