-- 2026-07-15: immutable published report versions and filesystem recovery records.

CREATE TABLE IF NOT EXISTS published_reports (
    id                 VARCHAR(36)  NOT NULL COMMENT 'Application UUID',
    run_id             VARCHAR(36)  NOT NULL,
    report_kind        VARCHAR(16)  NOT NULL COMMENT 'daily/weekly',
    period_start       DATE         NOT NULL,
    period_end         DATE         NOT NULL,
    version            INT          NOT NULL,
    is_current         BOOLEAN      NOT NULL DEFAULT TRUE,
    snapshot_json      LONGTEXT     NOT NULL COMMENT 'Canonical preview JSON',
    snapshot_hash      VARCHAR(64)  NOT NULL,
    baseline_report_id VARCHAR(36)  NULL,
    published_by       VARCHAR(100) NOT NULL,
    published_at       DATETIME     NOT NULL,
    superseded_at      DATETIME     NULL,
    create_time        DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    create_id          VARCHAR(36)  NULL,
    update_time        DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    update_id          VARCHAR(36)  NULL,
    is_deleted         INT          NOT NULL DEFAULT 0,
    PRIMARY KEY (id),
    UNIQUE KEY uq_published_report_period_version
        (report_kind, period_start, period_end, version),
    UNIQUE KEY uq_published_report_run_kind (run_id, report_kind),
    KEY ix_published_reports_run_id (run_id),
    KEY ix_published_reports_report_kind (report_kind),
    KEY ix_published_reports_period_start (period_start),
    KEY ix_published_reports_period_end (period_end),
    KEY ix_published_reports_is_current (is_current),
    CONSTRAINT fk_published_reports_run
        FOREIGN KEY (run_id) REFERENCES report_runs (id) ON DELETE RESTRICT,
    CONSTRAINT fk_published_reports_baseline
        FOREIGN KEY (baseline_report_id) REFERENCES published_reports (id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='Immutable formal report versions';

CREATE TABLE IF NOT EXISTS report_artifacts (
    id             VARCHAR(36)   NOT NULL COMMENT 'Application UUID',
    report_id      VARCHAR(36)   NOT NULL,
    artifact_kind  VARCHAR(32)   NOT NULL,
    protected_path VARCHAR(1024) NOT NULL,
    sha256         VARCHAR(64)   NOT NULL,
    size_bytes     INT           NOT NULL,
    create_time    DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
    create_id      VARCHAR(36)   NULL,
    update_time    DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    update_id      VARCHAR(36)   NULL,
    is_deleted     INT           NOT NULL DEFAULT 0,
    PRIMARY KEY (id),
    UNIQUE KEY uq_report_artifact_kind (report_id, artifact_kind),
    KEY ix_report_artifacts_report_id (report_id),
    CONSTRAINT fk_report_artifacts_report
        FOREIGN KEY (report_id) REFERENCES published_reports (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='Protected formal report artifacts';

CREATE TABLE IF NOT EXISTS publication_attempts (
    id                     VARCHAR(36)   NOT NULL COMMENT 'Application UUID',
    run_id                 VARCHAR(36)   NOT NULL,
    report_kind            VARCHAR(16)   NOT NULL,
    status                 VARCHAR(32)   NOT NULL,
    staging_path           VARCHAR(1024) NOT NULL,
    final_path             VARCHAR(1024) NOT NULL,
    report_id              VARCHAR(36)   NULL,
    manifest_json          TEXT          NULL COMMENT 'Canonical artifact move manifest',
    error_message_redacted TEXT          NULL,
    completed_at           DATETIME      NULL,
    create_time            DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
    create_id              VARCHAR(36)   NULL,
    update_time            DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    update_id              VARCHAR(36)   NULL,
    is_deleted             INT           NOT NULL DEFAULT 0,
    PRIMARY KEY (id),
    KEY ix_publication_attempts_run_id (run_id),
    KEY ix_publication_attempts_report_kind (report_kind),
    KEY ix_publication_attempts_status (status),
    CONSTRAINT fk_publication_attempts_run
        FOREIGN KEY (run_id) REFERENCES report_runs (id) ON DELETE CASCADE,
    CONSTRAINT fk_publication_attempts_report
        FOREIGN KEY (report_id) REFERENCES published_reports (id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='Recoverable filesystem publication attempts';
