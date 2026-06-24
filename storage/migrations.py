from __future__ import annotations

V1_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER NOT NULL PRIMARY KEY
);

CREATE TABLE IF NOT EXISTS candidates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    candidate_key TEXT NOT NULL UNIQUE,
    raw_text_hash TEXT NOT NULL,
    platform_uid TEXT,
    job_title TEXT NOT NULL,
    source_url TEXT NOT NULL,
    capture_time TEXT NOT NULL,
    name TEXT,
    active_status TEXT,
    expected_salary TEXT,
    work_experience_text TEXT,
    education_text TEXT,
    tags_text TEXT,
    summary_text TEXT,
    raw_card_text TEXT NOT NULL,
    detail_url TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_candidates_name ON candidates(name);
CREATE INDEX IF NOT EXISTS idx_candidates_capture_time ON candidates(capture_time);
CREATE INDEX IF NOT EXISTS idx_candidates_raw_hash ON candidates(raw_text_hash);

CREATE TABLE IF NOT EXISTS capture_batches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_title TEXT NOT NULL,
    source_url TEXT NOT NULL,
    start_time TEXT NOT NULL,
    end_time TEXT,
    total_collected INTEGER NOT NULL DEFAULT 0,
    total_new INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL,
    note TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_capture_batches_job_title ON capture_batches(job_title);
CREATE INDEX IF NOT EXISTS idx_capture_batches_start_time ON capture_batches(start_time);

CREATE TABLE IF NOT EXISTS capture_batch_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_id INTEGER NOT NULL,
    candidate_id INTEGER NOT NULL,
    candidate_key TEXT NOT NULL,
    raw_text_hash TEXT NOT NULL,
    capture_time TEXT NOT NULL,
    job_title TEXT NOT NULL,
    source_url TEXT NOT NULL,
    name TEXT,
    active_status TEXT,
    expected_salary TEXT,
    work_experience_text TEXT,
    education_text TEXT,
    tags_text TEXT,
    summary_text TEXT,
    raw_card_text TEXT NOT NULL,
    detail_url TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY(batch_id) REFERENCES capture_batches(id) ON DELETE CASCADE,
    FOREIGN KEY(candidate_id) REFERENCES candidates(id) ON DELETE CASCADE,
    UNIQUE(batch_id, candidate_key)
);

CREATE INDEX IF NOT EXISTS idx_capture_batch_items_batch_id ON capture_batch_items(batch_id);
CREATE INDEX IF NOT EXISTS idx_capture_batch_items_candidate_id ON capture_batch_items(candidate_id);

CREATE TABLE IF NOT EXISTS screening_profiles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_title TEXT NOT NULL UNIQUE,
    jd_text TEXT NOT NULL,
    prompt_text TEXT NOT NULL,
    prompt_source TEXT NOT NULL DEFAULT 'generated',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS screening_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    profile_id INTEGER NOT NULL,
    source_job_title TEXT,
    batch_id INTEGER,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    origin TEXT NOT NULL DEFAULT 'manual',
    status TEXT NOT NULL,
    total_candidates INTEGER NOT NULL DEFAULT 0,
    completed_candidates INTEGER NOT NULL DEFAULT 0,
    failed_candidates INTEGER NOT NULL DEFAULT 0,
    started_at TEXT NOT NULL,
    completed_at TEXT,
    note TEXT,
    FOREIGN KEY(profile_id) REFERENCES screening_profiles(id) ON DELETE CASCADE,
    FOREIGN KEY(batch_id) REFERENCES capture_batches(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_screening_runs_profile ON screening_runs(profile_id);
CREATE INDEX IF NOT EXISTS idx_screening_runs_started ON screening_runs(started_at);

CREATE TABLE IF NOT EXISTS screening_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL,
    candidate_id INTEGER NOT NULL,
    rating TEXT,
    persona TEXT,
    status TEXT NOT NULL,
    raw_response TEXT,
    error TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY(run_id) REFERENCES screening_runs(id) ON DELETE CASCADE,
    FOREIGN KEY(candidate_id) REFERENCES candidates(id) ON DELETE CASCADE,
    UNIQUE(run_id, candidate_id)
);

CREATE INDEX IF NOT EXISTS idx_screening_results_run ON screening_results(run_id);
CREATE INDEX IF NOT EXISTS idx_screening_results_candidate ON screening_results(candidate_id);
CREATE INDEX IF NOT EXISTS idx_screening_results_rating ON screening_results(rating);
"""


def apply_migrations(connection) -> None:
    connection.executescript(V1_SCHEMA_SQL)
    screening_run_columns = {
        str(row[1]) for row in connection.execute("PRAGMA table_info(screening_runs)").fetchall()
    }
    if "origin" not in screening_run_columns:
        connection.execute(
            "ALTER TABLE screening_runs ADD COLUMN origin TEXT NOT NULL DEFAULT 'manual'"
        )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_screening_runs_origin_started "
        "ON screening_runs(origin, started_at)"
    )
    connection.execute("DELETE FROM schema_version")
    connection.execute("INSERT INTO schema_version(version) VALUES (3)")
    connection.commit()
