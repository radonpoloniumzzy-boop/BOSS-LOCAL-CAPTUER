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

CREATE TABLE IF NOT EXISTS candidate_profiles (
    candidate_id INTEGER PRIMARY KEY,
    name_or_alias TEXT NOT NULL DEFAULT '',
    city TEXT NOT NULL DEFAULT '',
    current_title TEXT NOT NULL DEFAULT '',
    job_family TEXT NOT NULL DEFAULT '',
    job_track TEXT NOT NULL DEFAULT '',
    years_experience INTEGER,
    industry_tags_json TEXT NOT NULL DEFAULT '[]',
    skill_tags_json TEXT NOT NULL DEFAULT '[]',
    management_experience INTEGER NOT NULL DEFAULT 0,
    salary_range TEXT NOT NULL DEFAULT '',
    education TEXT NOT NULL DEFAULT '',
    last_active_at TEXT NOT NULL DEFAULT '',
    profile_completeness INTEGER NOT NULL DEFAULT 0,
    parser_version TEXT NOT NULL DEFAULT 'rule:v1',
    updated_at TEXT NOT NULL,
    FOREIGN KEY(candidate_id) REFERENCES candidates(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_candidate_profiles_city ON candidate_profiles(city);
CREATE INDEX IF NOT EXISTS idx_candidate_profiles_job ON candidate_profiles(job_family, job_track);
CREATE INDEX IF NOT EXISTS idx_candidate_profiles_years ON candidate_profiles(years_experience);
CREATE INDEX IF NOT EXISTS idx_candidate_profiles_last_active ON candidate_profiles(last_active_at);

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
    confidence TEXT NOT NULL DEFAULT '',
    evidence_json TEXT NOT NULL DEFAULT '[]',
    gap_json TEXT NOT NULL DEFAULT '[]',
    risk_json TEXT NOT NULL DEFAULT '[]',
    recommended_action TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    FOREIGN KEY(run_id) REFERENCES screening_runs(id) ON DELETE CASCADE,
    FOREIGN KEY(candidate_id) REFERENCES candidates(id) ON DELETE CASCADE,
    UNIQUE(run_id, candidate_id)
);

CREATE INDEX IF NOT EXISTS idx_screening_results_run ON screening_results(run_id);
CREATE INDEX IF NOT EXISTS idx_screening_results_candidate ON screening_results(candidate_id);
CREATE INDEX IF NOT EXISTS idx_screening_results_rating ON screening_results(rating);

CREATE TABLE IF NOT EXISTS screening_tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL,
    candidate_id INTEGER NOT NULL,
    role_id INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    route TEXT NOT NULL DEFAULT 'pass_to_ai',
    route_reason TEXT,
    route_details_json TEXT NOT NULL DEFAULT '{}',
    priority INTEGER NOT NULL DEFAULT 0,
    retry_count INTEGER NOT NULL DEFAULT 0,
    max_retry_count INTEGER NOT NULL DEFAULT 2,
    model_name TEXT NOT NULL,
    prompt_version TEXT NOT NULL DEFAULT 'v1',
    request_payload_hash TEXT NOT NULL,
    result_id INTEGER,
    error_message TEXT,
    created_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT,
    updated_at TEXT NOT NULL,
    result_source TEXT NOT NULL DEFAULT '',
    prompt_text TEXT NOT NULL DEFAULT '',
    candidate_text TEXT NOT NULL DEFAULT '',
    locked_at TEXT,
    locked_by TEXT NOT NULL DEFAULT '',
    next_attempt_at TEXT,
    failure_category TEXT NOT NULL DEFAULT '',
    FOREIGN KEY(run_id) REFERENCES screening_runs(id) ON DELETE CASCADE,
    FOREIGN KEY(candidate_id) REFERENCES candidates(id) ON DELETE CASCADE,
    FOREIGN KEY(role_id) REFERENCES screening_profiles(id) ON DELETE CASCADE,
    FOREIGN KEY(result_id) REFERENCES screening_results(id) ON DELETE SET NULL,
    UNIQUE(run_id, candidate_id)
);

CREATE INDEX IF NOT EXISTS idx_screening_tasks_run_status ON screening_tasks(run_id, status);
CREATE INDEX IF NOT EXISTS idx_screening_tasks_candidate ON screening_tasks(candidate_id);
CREATE INDEX IF NOT EXISTS idx_screening_tasks_request_hash
ON screening_tasks(role_id, candidate_id, model_name, prompt_version, request_payload_hash);

CREATE TABLE IF NOT EXISTS candidate_role_matches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    candidate_id INTEGER NOT NULL,
    role_id INTEGER NOT NULL,
    latest_rating TEXT,
    latest_confidence TEXT NOT NULL DEFAULT '',
    match_status TEXT NOT NULL DEFAULT 'screening_pending',
    recruitment_status TEXT NOT NULL DEFAULT 'collected',
    screening_result_id INTEGER,
    human_decision TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(candidate_id) REFERENCES candidates(id) ON DELETE CASCADE,
    FOREIGN KEY(role_id) REFERENCES screening_profiles(id) ON DELETE CASCADE,
    FOREIGN KEY(screening_result_id) REFERENCES screening_results(id) ON DELETE SET NULL,
    UNIQUE(candidate_id, role_id)
);

CREATE INDEX IF NOT EXISTS idx_candidate_role_matches_role_status
ON candidate_role_matches(role_id, match_status, latest_rating);
CREATE INDEX IF NOT EXISTS idx_candidate_role_matches_candidate
ON candidate_role_matches(candidate_id);

CREATE TABLE IF NOT EXISTS candidate_role_status_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    candidate_id INTEGER NOT NULL,
    role_id INTEGER NOT NULL,
    from_status TEXT NOT NULL DEFAULT '',
    to_status TEXT NOT NULL,
    operator TEXT NOT NULL DEFAULT '',
    reason_code TEXT NOT NULL DEFAULT '',
    note TEXT NOT NULL DEFAULT '',
    changed_at TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(candidate_id) REFERENCES candidates(id) ON DELETE CASCADE,
    FOREIGN KEY(role_id) REFERENCES screening_profiles(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_candidate_role_status_events_match_time
ON candidate_role_status_events(candidate_id, role_id, changed_at);
CREATE INDEX IF NOT EXISTS idx_candidate_role_status_events_role_status
ON candidate_role_status_events(role_id, to_status, changed_at);
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
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS screening_tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id INTEGER NOT NULL,
            candidate_id INTEGER NOT NULL,
            role_id INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            route TEXT NOT NULL DEFAULT 'pass_to_ai',
            route_reason TEXT,
            route_details_json TEXT NOT NULL DEFAULT '{}',
            priority INTEGER NOT NULL DEFAULT 0,
            retry_count INTEGER NOT NULL DEFAULT 0,
            max_retry_count INTEGER NOT NULL DEFAULT 2,
            model_name TEXT NOT NULL,
            prompt_version TEXT NOT NULL DEFAULT 'v1',
            request_payload_hash TEXT NOT NULL,
            result_id INTEGER,
            error_message TEXT,
            created_at TEXT NOT NULL,
            started_at TEXT,
            finished_at TEXT,
            updated_at TEXT NOT NULL,
            result_source TEXT NOT NULL DEFAULT '',
            prompt_text TEXT NOT NULL DEFAULT '',
            candidate_text TEXT NOT NULL DEFAULT '',
            locked_at TEXT,
            locked_by TEXT NOT NULL DEFAULT '',
            next_attempt_at TEXT,
            failure_category TEXT NOT NULL DEFAULT '',
            FOREIGN KEY(run_id) REFERENCES screening_runs(id) ON DELETE CASCADE,
            FOREIGN KEY(candidate_id) REFERENCES candidates(id) ON DELETE CASCADE,
            FOREIGN KEY(role_id) REFERENCES screening_profiles(id) ON DELETE CASCADE,
            FOREIGN KEY(result_id) REFERENCES screening_results(id) ON DELETE SET NULL,
            UNIQUE(run_id, candidate_id)
        )
        """
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_screening_tasks_run_status "
        "ON screening_tasks(run_id, status)"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_screening_tasks_candidate "
        "ON screening_tasks(candidate_id)"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_screening_tasks_request_hash "
        "ON screening_tasks(role_id, candidate_id, model_name, prompt_version, request_payload_hash)"
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS candidate_role_matches (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            candidate_id INTEGER NOT NULL,
            role_id INTEGER NOT NULL,
            latest_rating TEXT,
            latest_confidence TEXT NOT NULL DEFAULT '',
            match_status TEXT NOT NULL DEFAULT 'screening_pending',
            recruitment_status TEXT NOT NULL DEFAULT 'collected',
            screening_result_id INTEGER,
            human_decision TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(candidate_id) REFERENCES candidates(id) ON DELETE CASCADE,
            FOREIGN KEY(role_id) REFERENCES screening_profiles(id) ON DELETE CASCADE,
            FOREIGN KEY(screening_result_id) REFERENCES screening_results(id) ON DELETE SET NULL,
            UNIQUE(candidate_id, role_id)
        )
        """
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_candidate_role_matches_role_status "
        "ON candidate_role_matches(role_id, match_status, latest_rating)"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_candidate_role_matches_candidate "
        "ON candidate_role_matches(candidate_id)"
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS candidate_role_status_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            candidate_id INTEGER NOT NULL,
            role_id INTEGER NOT NULL,
            from_status TEXT NOT NULL DEFAULT '',
            to_status TEXT NOT NULL,
            operator TEXT NOT NULL DEFAULT '',
            reason_code TEXT NOT NULL DEFAULT '',
            note TEXT NOT NULL DEFAULT '',
            changed_at TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY(candidate_id) REFERENCES candidates(id) ON DELETE CASCADE,
            FOREIGN KEY(role_id) REFERENCES screening_profiles(id) ON DELETE CASCADE
        )
        """
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_candidate_role_status_events_match_time "
        "ON candidate_role_status_events(candidate_id, role_id, changed_at)"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_candidate_role_status_events_role_status "
        "ON candidate_role_status_events(role_id, to_status, changed_at)"
    )
    result_columns = {
        str(row[1]) for row in connection.execute("PRAGMA table_info(screening_results)").fetchall()
    }
    if "confidence" not in result_columns:
        connection.execute("ALTER TABLE screening_results ADD COLUMN confidence TEXT NOT NULL DEFAULT ''")
    if "evidence_json" not in result_columns:
        connection.execute(
            "ALTER TABLE screening_results ADD COLUMN evidence_json TEXT NOT NULL DEFAULT '[]'"
        )
    if "gap_json" not in result_columns:
        connection.execute(
            "ALTER TABLE screening_results ADD COLUMN gap_json TEXT NOT NULL DEFAULT '[]'"
        )
    if "risk_json" not in result_columns:
        connection.execute(
            "ALTER TABLE screening_results ADD COLUMN risk_json TEXT NOT NULL DEFAULT '[]'"
        )
    if "recommended_action" not in result_columns:
        connection.execute(
            "ALTER TABLE screening_results ADD COLUMN recommended_action TEXT NOT NULL DEFAULT ''"
        )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS candidate_profiles (
            candidate_id INTEGER PRIMARY KEY,
            name_or_alias TEXT NOT NULL DEFAULT '',
            city TEXT NOT NULL DEFAULT '',
            current_title TEXT NOT NULL DEFAULT '',
            job_family TEXT NOT NULL DEFAULT '',
            job_track TEXT NOT NULL DEFAULT '',
            years_experience INTEGER,
            industry_tags_json TEXT NOT NULL DEFAULT '[]',
            skill_tags_json TEXT NOT NULL DEFAULT '[]',
            management_experience INTEGER NOT NULL DEFAULT 0,
            salary_range TEXT NOT NULL DEFAULT '',
            education TEXT NOT NULL DEFAULT '',
            last_active_at TEXT NOT NULL DEFAULT '',
            profile_completeness INTEGER NOT NULL DEFAULT 0,
            parser_version TEXT NOT NULL DEFAULT 'rule:v1',
            updated_at TEXT NOT NULL,
            FOREIGN KEY(candidate_id) REFERENCES candidates(id) ON DELETE CASCADE
        )
        """
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_candidate_profiles_city ON candidate_profiles(city)"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_candidate_profiles_job "
        "ON candidate_profiles(job_family, job_track)"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_candidate_profiles_years "
        "ON candidate_profiles(years_experience)"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_candidate_profiles_last_active "
        "ON candidate_profiles(last_active_at)"
    )
    connection.execute(
        """
        INSERT OR IGNORE INTO candidate_profiles(
            candidate_id,
            name_or_alias,
            current_title,
            salary_range,
            education,
            last_active_at,
            profile_completeness,
            parser_version,
            updated_at
        )
        SELECT
            id,
            COALESCE(name, ''),
            COALESCE(job_title, ''),
            COALESCE(expected_salary, ''),
            COALESCE(education_text, ''),
            COALESCE(capture_time, updated_at, ''),
            0,
            'migration:v1',
            COALESCE(updated_at, created_at, capture_time)
        FROM candidates
        """
    )
    match_columns = {
        str(row[1])
        for row in connection.execute("PRAGMA table_info(candidate_role_matches)").fetchall()
    }
    if "recruitment_status" not in match_columns:
        connection.execute(
            "ALTER TABLE candidate_role_matches ADD COLUMN recruitment_status "
            "TEXT NOT NULL DEFAULT 'collected'"
        )
    task_columns = {
        str(row[1]) for row in connection.execute("PRAGMA table_info(screening_tasks)").fetchall()
    }
    if "route" not in task_columns:
        connection.execute(
            "ALTER TABLE screening_tasks ADD COLUMN route TEXT NOT NULL DEFAULT 'pass_to_ai'"
        )
    if "route_reason" not in task_columns:
        connection.execute("ALTER TABLE screening_tasks ADD COLUMN route_reason TEXT")
    if "route_details_json" not in task_columns:
        connection.execute(
            "ALTER TABLE screening_tasks ADD COLUMN route_details_json TEXT NOT NULL DEFAULT '{}'"
        )
    if "result_source" not in task_columns:
        connection.execute(
            "ALTER TABLE screening_tasks ADD COLUMN result_source TEXT NOT NULL DEFAULT ''"
        )
    if "prompt_text" not in task_columns:
        connection.execute(
            "ALTER TABLE screening_tasks ADD COLUMN prompt_text TEXT NOT NULL DEFAULT ''"
        )
    if "candidate_text" not in task_columns:
        connection.execute(
            "ALTER TABLE screening_tasks ADD COLUMN candidate_text TEXT NOT NULL DEFAULT ''"
        )
    if "locked_at" not in task_columns:
        connection.execute("ALTER TABLE screening_tasks ADD COLUMN locked_at TEXT")
    if "locked_by" not in task_columns:
        connection.execute(
            "ALTER TABLE screening_tasks ADD COLUMN locked_by TEXT NOT NULL DEFAULT ''"
        )
    if "next_attempt_at" not in task_columns:
        connection.execute("ALTER TABLE screening_tasks ADD COLUMN next_attempt_at TEXT")
    if "failure_category" not in task_columns:
        connection.execute(
            "ALTER TABLE screening_tasks ADD COLUMN failure_category TEXT NOT NULL DEFAULT ''"
        )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_screening_tasks_claim "
        "ON screening_tasks(run_id, route, status, next_attempt_at, priority)"
    )
    connection.execute(
        """
        INSERT OR IGNORE INTO screening_tasks(
            run_id,
            candidate_id,
            role_id,
            status,
            route,
            route_reason,
            route_details_json,
            priority,
            retry_count,
            max_retry_count,
            model_name,
            prompt_version,
            request_payload_hash,
            result_id,
            error_message,
            created_at,
            started_at,
            finished_at,
            updated_at,
            result_source
        )
        SELECT
            sr.run_id,
            sr.candidate_id,
            r.profile_id,
            CASE WHEN sr.status = 'failed' THEN 'failed' ELSE 'success' END,
            'pass_to_ai',
            'legacy_screening_result',
            '{}',
            0,
            CASE WHEN sr.status = 'failed' THEN 1 ELSE 0 END,
            2,
            r.model,
            'legacy',
            'legacy:' || sr.run_id || ':' || sr.candidate_id,
            sr.id,
            COALESCE(sr.error, ''),
            sr.created_at,
            r.started_at,
            sr.created_at,
            sr.created_at,
            'legacy'
        FROM screening_results sr
        JOIN screening_runs r ON r.id = sr.run_id
        """
    )
    connection.execute(
        """
        UPDATE screening_tasks
        SET result_source = 'legacy'
        WHERE result_source = ''
          AND result_id IS NOT NULL
          AND status = 'success'
        """
    )
    connection.execute(
        """
        INSERT INTO candidate_role_matches(
            candidate_id,
            role_id,
            latest_rating,
            latest_confidence,
            match_status,
            recruitment_status,
            screening_result_id,
            human_decision,
            created_at,
            updated_at
        )
        SELECT
            t.candidate_id,
            t.role_id,
            COALESCE(r.rating, ''),
            '',
            CASE t.status
                WHEN 'success' THEN 'ai_screened'
                WHEN 'failed' THEN 'ai_failed'
                WHEN 'manual_check' THEN 'manual_check'
                WHEN 'hold' THEN 'hold'
                WHEN 'running' THEN 'screening_running'
                WHEN 'retrying' THEN 'screening_retrying'
                ELSE 'screening_pending'
            END,
            CASE t.status
                WHEN 'success' THEN 'screened'
                ELSE 'collected'
            END,
            t.result_id,
            '',
            t.created_at,
            COALESCE(t.finished_at, t.updated_at, t.created_at)
        FROM screening_tasks t
        LEFT JOIN screening_results r ON r.id = t.result_id
        WHERE t.id = (
            SELECT t2.id
            FROM screening_tasks t2
            WHERE t2.candidate_id = t.candidate_id
              AND t2.role_id = t.role_id
            ORDER BY COALESCE(t2.finished_at, t2.updated_at, t2.created_at) DESC, t2.id DESC
            LIMIT 1
        )
        ON CONFLICT(candidate_id, role_id) DO UPDATE SET
            latest_rating = excluded.latest_rating,
            latest_confidence = excluded.latest_confidence,
            match_status = excluded.match_status,
            screening_result_id = excluded.screening_result_id,
            updated_at = excluded.updated_at
        """
    )
    connection.execute(
        """
        INSERT INTO candidate_role_status_events(
            candidate_id,
            role_id,
            from_status,
            to_status,
            operator,
            reason_code,
            note,
            changed_at,
            created_at
        )
        SELECT
            m.candidate_id,
            m.role_id,
            '',
            m.recruitment_status,
            'system',
            'migration_backfill',
            'Initial recruitment status from existing candidate-role match',
            m.created_at,
            m.created_at
        FROM candidate_role_matches m
        WHERE NOT EXISTS (
            SELECT 1
            FROM candidate_role_status_events e
            WHERE e.candidate_id = m.candidate_id
              AND e.role_id = m.role_id
        )
        """
    )
    connection.execute("DELETE FROM schema_version")
    connection.execute("INSERT INTO schema_version(version) VALUES (12)")
    connection.commit()
