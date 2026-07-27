-- 2026-07-15: immutable report Runs, source metadata, and independent targets.
-- Raw input bytes are intentionally not persisted; only the sanitized basename is kept.
-- Idempotent for an existing 2026-07-12 schema.

CREATE TABLE IF NOT EXISTS report_runs (
    id                     VARCHAR(36) NOT NULL COMMENT 'Application UUID',
    report_date            DATE        NOT NULL COMMENT 'Report business date',
    status                 VARCHAR(24) NOT NULL COMMENT 'Run lifecycle status',
    rule_version           VARCHAR(64) NOT NULL COMMENT 'Frozen deterministic rule version',
    source_bundle_hash     VARCHAR(64) NULL COMMENT 'Four sources plus baseline fingerprint',
    baseline_report_id     VARCHAR(36) NULL COMMENT 'Published baseline report identifier',
    canonical_run_id       VARCHAR(36) NULL COMMENT 'Canonical Run when deduplicated',
    attempt_no             INT         NOT NULL DEFAULT 0,
    error_code             VARCHAR(64) NULL,
    error_message_redacted TEXT        NULL,
    create_time            DATETIME    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    create_id              VARCHAR(36) NULL,
    update_time            DATETIME    NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    update_id              VARCHAR(36) NULL,
    is_deleted             INT         NOT NULL DEFAULT 0,
    PRIMARY KEY (id),
    UNIQUE KEY uq_report_run_fingerprint (report_date, rule_version, source_bundle_hash),
    KEY ix_report_runs_report_date (report_date),
    KEY ix_report_runs_status (status),
    KEY ix_report_runs_canonical_run_id (canonical_run_id),
    CONSTRAINT fk_report_runs_canonical_run
        FOREIGN KEY (canonical_run_id) REFERENCES report_runs (id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='Immutable report input and baseline attempts';

CREATE TABLE IF NOT EXISTS run_sources (
    id                 VARCHAR(36)  NOT NULL COMMENT 'Application UUID',
    run_id             VARCHAR(36)  NOT NULL,
    source_type        VARCHAR(24)  NOT NULL COMMENT 'personnel/resignation/release/recruitment',
    sha256             VARCHAR(64)  NOT NULL COMMENT 'Source bytes SHA-256',
    schema_version     VARCHAR(64)  NOT NULL,
    parser_version     VARCHAR(64)  NOT NULL,
    media_type         VARCHAR(128) NULL,
    row_count          INT          NOT NULL DEFAULT 0,
    parse_status       VARCHAR(24)  NOT NULL,
    original_extension VARCHAR(16)  NULL COMMENT 'Source extension',
    original_filename  VARCHAR(255) NULL COMMENT 'Sanitized source basename for operator display',
    create_time        DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    create_id          VARCHAR(36)  NULL,
    update_time        DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    update_id          VARCHAR(36)  NULL,
    is_deleted         INT          NOT NULL DEFAULT 0,
    PRIMARY KEY (id),
    UNIQUE KEY uq_run_source_type (run_id, source_type),
    KEY ix_run_sources_run_id (run_id),
    CONSTRAINT fk_run_sources_run
        FOREIGN KEY (run_id) REFERENCES report_runs (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='Per-Run source metadata without raw files';

CREATE TABLE IF NOT EXISTS run_report_targets (
    id                     VARCHAR(36) NOT NULL COMMENT 'Application UUID',
    run_id                 VARCHAR(36) NOT NULL,
    report_kind            VARCHAR(16) NOT NULL COMMENT 'daily/weekly',
    status                 VARCHAR(24) NOT NULL COMMENT 'Independent target lifecycle status',
    preview_hash           VARCHAR(64) NULL,
    validation_summary     TEXT        NULL COMMENT 'Redacted JSON summary',
    published_report_id    VARCHAR(36) NULL,
    error_code             VARCHAR(64) NULL,
    error_message_redacted TEXT        NULL,
    create_time            DATETIME    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    create_id              VARCHAR(36) NULL,
    update_time            DATETIME    NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    update_id              VARCHAR(36) NULL,
    is_deleted             INT         NOT NULL DEFAULT 0,
    PRIMARY KEY (id),
    UNIQUE KEY uq_run_report_target_kind (run_id, report_kind),
    KEY ix_run_report_targets_run_id (run_id),
    KEY ix_run_report_targets_status (status),
    CONSTRAINT fk_run_report_targets_run
        FOREIGN KEY (run_id) REFERENCES report_runs (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='Independent daily and weekly states per Run';
