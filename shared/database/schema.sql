-- AutomataCodex データベーススキーマ定義
-- データベース名: coding_agent
-- 作成順序: 外部キー依存関係に従ってテーブルを作成する

-- ===========================
-- スキーマバージョン管理テーブル
-- ===========================
CREATE TABLE IF NOT EXISTS schema_versions (
    version     TEXT      PRIMARY KEY,
    applied_at  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    description TEXT
);

-- ===========================
-- 1. usersテーブル
-- ===========================
CREATE TABLE IF NOT EXISTS users (
    username      TEXT      PRIMARY KEY,
    password_hash TEXT      NOT NULL,
    role          TEXT      NOT NULL DEFAULT 'user',
    is_active     BOOLEAN   NOT NULL DEFAULT true,
    created_at    TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at    TIMESTAMP          DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_users_is_active ON users (is_active);
CREATE INDEX IF NOT EXISTS idx_users_role      ON users (role);

-- ===========================
-- 2. user_configsテーブル
-- ===========================
CREATE TABLE IF NOT EXISTS user_configs (
    username                      TEXT      PRIMARY KEY,
    llm_provider                  TEXT      NOT NULL DEFAULT 'openai',
    api_key_encrypted             TEXT,
    model_name                    TEXT      NOT NULL DEFAULT 'gpt-4o',
    temperature                   REAL      NOT NULL DEFAULT 0.2,
    max_tokens                    INTEGER   NOT NULL DEFAULT 4096,
    top_p                         REAL      NOT NULL DEFAULT 1.0,
    frequency_penalty             REAL      NOT NULL DEFAULT 0.0,
    presence_penalty              REAL      NOT NULL DEFAULT 0.0,
    base_url                      TEXT,
    timeout                       INTEGER   NOT NULL DEFAULT 120,
    context_compression_enabled   BOOLEAN   NOT NULL DEFAULT true,
    token_threshold               INTEGER,
    keep_recent_messages          INTEGER   NOT NULL DEFAULT 10,
    min_to_compress               INTEGER   NOT NULL DEFAULT 5,
    min_compression_ratio         REAL      NOT NULL DEFAULT 0.8,
    created_at                    TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at                    TIMESTAMP          DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (username) REFERENCES users(username) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_user_configs_provider ON user_configs (llm_provider);

-- ===========================
-- 3. workflow_definitionsテーブル
-- ===========================
CREATE TABLE IF NOT EXISTS workflow_definitions (
    id                  SERIAL    PRIMARY KEY,
    name                TEXT      NOT NULL UNIQUE,
    display_name        TEXT      NOT NULL,
    description         TEXT,
    is_preset           BOOLEAN   NOT NULL DEFAULT false,
    created_by          TEXT,
    graph_definition    JSONB     NOT NULL,
    agent_definition    JSONB     NOT NULL,
    prompt_definition   JSONB     NOT NULL,
    version             TEXT      NOT NULL DEFAULT '1.0.0',
    is_active           BOOLEAN   NOT NULL DEFAULT true,
    created_at          TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at          TIMESTAMP          DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (created_by) REFERENCES users(username) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_workflow_definitions_name       ON workflow_definitions (name);
CREATE INDEX IF NOT EXISTS idx_workflow_definitions_is_preset  ON workflow_definitions (is_preset);
CREATE INDEX IF NOT EXISTS idx_workflow_definitions_created_by ON workflow_definitions (created_by);
CREATE INDEX IF NOT EXISTS idx_workflow_definitions_is_active  ON workflow_definitions (is_active);
CREATE INDEX IF NOT EXISTS idx_workflow_graph_def              ON workflow_definitions USING gin (graph_definition);

-- ===========================
-- 4. user_workflow_settingsテーブル
-- ===========================
CREATE TABLE IF NOT EXISTS user_workflow_settings (
    username                TEXT      PRIMARY KEY,
    workflow_definition_id  INTEGER   NOT NULL,
    custom_settings         TEXT,
    created_at              TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at              TIMESTAMP          DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (username)               REFERENCES users(username)             ON DELETE CASCADE,
    FOREIGN KEY (workflow_definition_id) REFERENCES workflow_definitions(id)   ON DELETE SET DEFAULT
);

CREATE INDEX IF NOT EXISTS idx_user_workflow_settings_definition ON user_workflow_settings (workflow_definition_id);

-- ===========================
-- 5. tasksテーブル
-- ===========================
CREATE TABLE IF NOT EXISTS tasks (
    uuid                    TEXT        PRIMARY KEY,
    task_type               TEXT        NOT NULL,
    task_identifier         TEXT        NOT NULL,
    repository              TEXT        NOT NULL,
    username                TEXT        NOT NULL,
    status                  TEXT        NOT NULL DEFAULT 'running',
    workflow_definition_id  INTEGER,
    created_at              TIMESTAMP   NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at              TIMESTAMP            DEFAULT CURRENT_TIMESTAMP,
    completed_at            TIMESTAMP,
    total_messages          INTEGER     NOT NULL DEFAULT 0,
    total_summaries         INTEGER     NOT NULL DEFAULT 0,
    total_tool_calls        INTEGER     NOT NULL DEFAULT 0,
    final_token_count       INTEGER,
    error_message           TEXT,
    metadata                JSONB                DEFAULT '{}',
    assigned_branches       JSONB,
    selected_branch         VARCHAR(255),
    FOREIGN KEY (username)               REFERENCES users(username)           ON DELETE CASCADE,
    FOREIGN KEY (workflow_definition_id) REFERENCES workflow_definitions(id)  ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_tasks_status          ON tasks (status);
CREATE INDEX IF NOT EXISTS idx_tasks_username        ON tasks (username);
CREATE INDEX IF NOT EXISTS idx_tasks_repository      ON tasks (repository);
CREATE INDEX IF NOT EXISTS idx_tasks_task_identifier ON tasks (task_identifier);
CREATE INDEX IF NOT EXISTS idx_tasks_created_at      ON tasks (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_tasks_completed_at    ON tasks (completed_at DESC) WHERE completed_at IS NOT NULL;

-- ===========================
-- 6. workflow_execution_statesテーブル
-- ===========================
CREATE TABLE IF NOT EXISTS workflow_execution_states (
    execution_id            UUID      PRIMARY KEY,
    task_uuid               TEXT      NOT NULL,
    workflow_definition_id  INTEGER,
    current_node_id         TEXT      NOT NULL,
    completed_nodes         JSONB     NOT NULL DEFAULT '[]',
    workflow_status         TEXT      NOT NULL DEFAULT 'running',
    suspended_at            TIMESTAMP,
    created_at              TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at              TIMESTAMP          DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (task_uuid)               REFERENCES tasks(uuid)              ON DELETE CASCADE,
    FOREIGN KEY (workflow_definition_id)  REFERENCES workflow_definitions(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_wf_exec_states_task_uuid    ON workflow_execution_states (task_uuid);
CREATE INDEX IF NOT EXISTS idx_wf_exec_states_status       ON workflow_execution_states (workflow_status);
CREATE INDEX IF NOT EXISTS idx_wf_exec_states_suspended_at ON workflow_execution_states (suspended_at DESC) WHERE suspended_at IS NOT NULL;

-- ===========================
-- 7. docker_environment_mappingsテーブル
-- ===========================
CREATE TABLE IF NOT EXISTS docker_environment_mappings (
    mapping_id        UUID      PRIMARY KEY,
    execution_id      UUID      NOT NULL,
    node_id           TEXT      NOT NULL,
    container_id      TEXT      NOT NULL,
    container_name    TEXT      NOT NULL,
    environment_name  TEXT      NOT NULL,
    status            TEXT      NOT NULL DEFAULT 'running',
    created_at        TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at        TIMESTAMP          DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (execution_id) REFERENCES workflow_execution_states(execution_id) ON DELETE CASCADE,
    UNIQUE (execution_id, node_id)
);

CREATE INDEX IF NOT EXISTS idx_docker_env_map_exec_id      ON docker_environment_mappings (execution_id);
CREATE INDEX IF NOT EXISTS idx_docker_env_map_container_id ON docker_environment_mappings (container_id);
CREATE INDEX IF NOT EXISTS idx_docker_env_map_status       ON docker_environment_mappings (status);

-- ===========================
-- 8. context_messagesテーブル
-- ===========================
CREATE TABLE IF NOT EXISTS context_messages (
    id                      SERIAL    PRIMARY KEY,
    task_uuid               TEXT      NOT NULL,
    seq                     INTEGER   NOT NULL,
    role                    TEXT      NOT NULL,
    content                 TEXT      NOT NULL,
    tool_call_id            TEXT,
    tool_name               TEXT,
    tokens                  INTEGER,
    is_compressed_summary   BOOLEAN            DEFAULT false,
    compressed_range        JSONB,
    created_at              TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (task_uuid) REFERENCES tasks(uuid) ON DELETE CASCADE,
    UNIQUE (task_uuid, seq)
);

CREATE INDEX IF NOT EXISTS idx_context_messages_task_seq ON context_messages (task_uuid, seq);
CREATE INDEX IF NOT EXISTS idx_context_messages_role     ON context_messages (role);

-- ===========================
-- 9. message_compressionsテーブル
-- ===========================
CREATE TABLE IF NOT EXISTS message_compressions (
    id                      SERIAL    PRIMARY KEY,
    task_uuid               TEXT      NOT NULL,
    start_seq               INTEGER   NOT NULL,
    end_seq                 INTEGER   NOT NULL,
    summary_seq             INTEGER   NOT NULL,
    original_token_count    INTEGER   NOT NULL,
    compressed_token_count  INTEGER   NOT NULL,
    compression_ratio       FLOAT,
    created_at              TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (task_uuid) REFERENCES tasks(uuid) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_message_compressions_task ON message_compressions (task_uuid, created_at DESC);

-- ===========================
-- 10. context_planning_historyテーブル
-- ===========================
CREATE TABLE IF NOT EXISTS context_planning_history (
    id          SERIAL    PRIMARY KEY,
    task_uuid   TEXT      NOT NULL,
    phase       TEXT      NOT NULL,
    node_id     TEXT      NOT NULL,
    plan        JSONB,
    action_id   TEXT,
    result      TEXT,
    created_at  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (task_uuid) REFERENCES tasks(uuid) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_context_planning_task_phase ON context_planning_history (task_uuid, phase, created_at);
CREATE INDEX IF NOT EXISTS idx_context_planning_node       ON context_planning_history (node_id);

-- ===========================
-- 11. context_metadataテーブル
-- ===========================
CREATE TABLE IF NOT EXISTS context_metadata (
    task_uuid          TEXT      PRIMARY KEY,
    task_type          TEXT      NOT NULL,
    task_identifier    TEXT      NOT NULL,
    repository         TEXT      NOT NULL,
    username           TEXT      NOT NULL,
    workflow_name      TEXT,
    created_at         TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at         TIMESTAMP          DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (task_uuid)   REFERENCES tasks(uuid)       ON DELETE CASCADE,
    FOREIGN KEY (username)    REFERENCES users(username)   ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_context_metadata_user       ON context_metadata (username);
CREATE INDEX IF NOT EXISTS idx_context_metadata_repository ON context_metadata (repository);

-- ===========================
-- 12. context_tool_results_metadataテーブル
-- ===========================
CREATE TABLE IF NOT EXISTS context_tool_results_metadata (
    id            SERIAL    PRIMARY KEY,
    task_uuid     TEXT      NOT NULL,
    tool_name     TEXT      NOT NULL,
    tool_command  TEXT,
    file_path     TEXT      NOT NULL,
    file_size     INTEGER   NOT NULL,
    success       BOOLEAN   NOT NULL DEFAULT true,
    created_at    TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (task_uuid) REFERENCES tasks(uuid) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_context_tool_results_task_tool ON context_tool_results_metadata (task_uuid, tool_name, created_at);

-- ===========================
-- 13. system_settingsテーブル
-- ===========================
CREATE TABLE IF NOT EXISTS system_settings (
    key        TEXT      PRIMARY KEY,
    value      TEXT      NOT NULL,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_system_settings_key ON system_settings (key);
CREATE INDEX IF NOT EXISTS idx_context_tool_results_created   ON context_tool_results_metadata (created_at DESC);

-- ===========================
-- 13. todosテーブル
-- ===========================
CREATE TABLE IF NOT EXISTS todos (
    id              SERIAL    PRIMARY KEY,
    task_uuid       TEXT      NOT NULL,
    todo_id         INTEGER,
    parent_todo_id  INTEGER,
    title           TEXT      NOT NULL,
    description     TEXT,
    status          TEXT      NOT NULL DEFAULT 'not-started',
    order_index     INTEGER   NOT NULL,
    created_at      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at      TIMESTAMP          DEFAULT CURRENT_TIMESTAMP,
    completed_at    TIMESTAMP,
    FOREIGN KEY (task_uuid)      REFERENCES tasks(uuid) ON DELETE CASCADE,
    FOREIGN KEY (parent_todo_id) REFERENCES todos(id)  ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_todos_task_uuid ON todos (task_uuid, order_index);
CREATE INDEX IF NOT EXISTS idx_todos_parent    ON todos (parent_todo_id);
CREATE INDEX IF NOT EXISTS idx_todos_status    ON todos (status);

-- ===========================
-- 14. token_usageテーブル
-- ===========================
CREATE TABLE IF NOT EXISTS token_usage (
    id                  SERIAL    PRIMARY KEY,
    username            TEXT      NOT NULL,
    task_uuid           TEXT      NOT NULL,
    node_id             TEXT      NOT NULL,
    model               TEXT      NOT NULL,
    prompt_tokens       INTEGER   NOT NULL,
    completion_tokens   INTEGER   NOT NULL,
    total_tokens        INTEGER   NOT NULL,
    created_at          TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (username) REFERENCES users(username) ON DELETE CASCADE,
    FOREIGN KEY (task_uuid)  REFERENCES tasks(uuid)  ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_token_usage_user_date ON token_usage (username, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_token_usage_task      ON token_usage (task_uuid);
CREATE INDEX IF NOT EXISTS idx_token_usage_model     ON token_usage (model);
CREATE INDEX IF NOT EXISTS idx_token_usage_node      ON token_usage (node_id);
CREATE INDEX IF NOT EXISTS idx_token_usage_created   ON token_usage (created_at DESC);
