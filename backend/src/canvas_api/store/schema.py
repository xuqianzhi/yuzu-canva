"""The Postgres schema, as numbered migrations (see migrations.py).

Timestamps are ISO-8601 text (they sort correctly and match the API), and
JSON values are text, as the store reads and writes them whole.
"""

# Each entry runs once, in order, in one transaction. Never edit an entry
# that has shipped: add a new one.
MIGRATIONS: list[str] = [
    # 1: the first Postgres schema.
    """
CREATE TABLE users (
    id TEXT PRIMARY KEY,
    email TEXT NOT NULL,
    created_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL
);
CREATE TABLE user_settings (
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    key TEXT NOT NULL,
    value TEXT NOT NULL,
    PRIMARY KEY (user_id, key)
);
CREATE TABLE usage (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    kind TEXT NOT NULL,
    amount INTEGER NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX usage_user_time ON usage(user_id, created_at);
CREATE TABLE projects (
    id TEXT PRIMARY KEY,
    owner_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    viewport TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    instruction TEXT NOT NULL DEFAULT '',
    workflow TEXT NOT NULL DEFAULT ''
);
CREATE INDEX projects_owner ON projects(owner_id);
CREATE TABLE nodes (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    kind TEXT NOT NULL,
    title TEXT NOT NULL,
    position TEXT NOT NULL,
    size TEXT,
    prompt TEXT NOT NULL,
    params TEXT NOT NULL,
    selected_output_id TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    deleted_at TEXT,
    source TEXT NOT NULL DEFAULT 'generate',
    workflow_step TEXT,
    workflow_item INTEGER
);
CREATE INDEX nodes_project ON nodes(project_id);
CREATE INDEX nodes_workflow ON nodes(project_id, workflow_step);
CREATE TABLE edges (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    source_node_id TEXT NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
    target_node_id TEXT NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL,
    deleted_at TEXT,
    target_handle TEXT NOT NULL DEFAULT '',
    UNIQUE (source_node_id, target_node_id, target_handle)
);
CREATE INDEX edges_project ON edges(project_id);
CREATE TABLE assets (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    kind TEXT NOT NULL,
    mime TEXT NOT NULL,
    filename TEXT NOT NULL,
    bytes BIGINT NOT NULL,
    width INTEGER,
    height INTEGER,
    duration_s DOUBLE PRECISION,
    created_at TEXT NOT NULL
);
CREATE INDEX assets_project ON assets(project_id);
CREATE TABLE jobs (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    node_id TEXT NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
    status TEXT NOT NULL,
    provider TEXT NOT NULL,
    operation TEXT NOT NULL,
    input TEXT NOT NULL,
    progress DOUBLE PRECISION,
    error TEXT,
    output_id TEXT,
    provider_task_id TEXT,
    created_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT
);
CREATE INDEX jobs_node ON jobs(node_id);
CREATE INDEX jobs_status ON jobs(status);
CREATE INDEX jobs_project ON jobs(project_id);
CREATE TABLE outputs (
    seq BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    id TEXT NOT NULL UNIQUE,
    node_id TEXT NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
    job_id TEXT,
    kind TEXT NOT NULL,
    text TEXT,
    asset_id TEXT REFERENCES assets(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL
);
CREATE INDEX outputs_node ON outputs(node_id);
CREATE TABLE workflow_templates (
    id TEXT PRIMARY KEY,
    owner_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    definition TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX workflow_templates_owner ON workflow_templates(owner_id);
CREATE TABLE step_runs (
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    step TEXT NOT NULL,
    prompt TEXT NOT NULL,
    count INTEGER NOT NULL,
    updated_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'done',
    error TEXT,
    PRIMARY KEY (project_id, step)
);
CREATE TABLE messages (
    seq BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    id TEXT NOT NULL UNIQUE,
    node_id TEXT NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
    role TEXT NOT NULL,
    text TEXT NOT NULL,
    proposal TEXT,
    applied_output_id TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX messages_node ON messages(node_id);
CREATE TABLE materials (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    asset_id TEXT NOT NULL REFERENCES assets(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX materials_project ON materials(project_id);
CREATE TABLE global_assets (
    id TEXT PRIMARY KEY,
    owner_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    kind TEXT NOT NULL,
    mime TEXT NOT NULL,
    filename TEXT NOT NULL,
    bytes BIGINT NOT NULL,
    width INTEGER,
    height INTEGER,
    duration_s DOUBLE PRECISION,
    created_at TEXT NOT NULL
);
CREATE INDEX global_assets_owner ON global_assets(owner_id);
""",
]

# Row-level security with no policies on every table: Supabase's public Data
# API (if ever turned on) can't read or write anything. The API connects as
# the tables' owner, which RLS doesn't apply to.
TABLES = [
    "users",
    "user_settings",
    "usage",
    "projects",
    "nodes",
    "edges",
    "assets",
    "jobs",
    "outputs",
    "workflow_templates",
    "step_runs",
    "messages",
    "materials",
    "global_assets",
]
