-- 2026-07-15: run-scoped canonical facts, events, decisions, and validations.
-- Certificate type and number plaintext are forbidden from these tables.

CREATE TABLE IF NOT EXISTS person_identities (
    id                 VARCHAR(36) NOT NULL COMMENT 'Application UUID',
    person_key         VARCHAR(64) NOT NULL COMMENT 'HMAC-SHA256 identity key',
    key_version        VARCHAR(16) NOT NULL,
    match_confidence   VARCHAR(32) NOT NULL,
    identity_namespace VARCHAR(32) NOT NULL,
    create_time        DATETIME    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    create_id          VARCHAR(36) NULL,
    update_time        DATETIME    NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    update_id          VARCHAR(36) NULL,
    is_deleted         INT         NOT NULL DEFAULT 0,
    PRIMARY KEY (id),
    UNIQUE KEY uq_person_identity_key (person_key)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='Opaque natural-person identities';

CREATE TABLE IF NOT EXISTS employment_facts (
    id                  VARCHAR(36)  NOT NULL COMMENT 'Application UUID',
    run_id              VARCHAR(36)  NOT NULL,
    source_row_no       INT          NOT NULL,
    person_id           VARCHAR(36)  NOT NULL,
    employee_no         VARCHAR(50)  NOT NULL COMMENT 'Protected HR display field',
    display_name        VARCHAR(100) NULL COMMENT 'Protected HR display field',
    employee_type       VARCHAR(32)  NOT NULL,
    status              VARCHAR(24)  NULL,
    entry_date          DATE         NULL,
    resign_date         DATE         NULL,
    business_unit       VARCHAR(100) NULL,
    business_unit_no    VARCHAR(50)  NULL,
    project_code        VARCHAR(100) NULL,
    project_name        VARCHAR(200) NULL,
    contract_dates      TEXT         NULL COMMENT 'Canonical JSON',
    first_visible_dates TEXT         NULL COMMENT 'Canonical JSON',
    create_time         DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    create_id           VARCHAR(36)  NULL,
    update_time         DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    update_id           VARCHAR(36)  NULL,
    is_deleted          INT          NOT NULL DEFAULT 0,
    PRIMARY KEY (id),
    UNIQUE KEY uq_employment_fact_run_row (run_id, source_row_no),
    KEY ix_employment_facts_run_id (run_id),
    KEY ix_employment_facts_person_id (person_id),
    CONSTRAINT fk_employment_facts_run
        FOREIGN KEY (run_id) REFERENCES report_runs (id) ON DELETE CASCADE,
    CONSTRAINT fk_employment_facts_person
        FOREIGN KEY (person_id) REFERENCES person_identities (id) ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='Run-scoped employment records';

CREATE TABLE IF NOT EXISTS resignation_facts (
    id                 VARCHAR(36)  NOT NULL COMMENT 'Application UUID',
    run_id             VARCHAR(36)  NOT NULL,
    source_row_no      INT          NOT NULL,
    process_no         VARCHAR(100) NOT NULL,
    person_id          VARCHAR(36)  NULL,
    employee_no        VARCHAR(50)  NULL COMMENT 'Protected HR display field',
    process_status     VARCHAR(32)  NULL,
    application_date   DATE         NULL,
    last_working_day   DATE         NULL,
    resignation_type   VARCHAR(32)  NULL,
    first_visible_date DATE         NULL,
    create_time        DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    create_id          VARCHAR(36)  NULL,
    update_time        DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    update_id          VARCHAR(36)  NULL,
    is_deleted         INT          NOT NULL DEFAULT 0,
    PRIMARY KEY (id),
    UNIQUE KEY uq_resignation_fact_run_process (run_id, process_no),
    KEY ix_resignation_facts_run_id (run_id),
    KEY ix_resignation_facts_person_id (person_id),
    CONSTRAINT fk_resignation_facts_run
        FOREIGN KEY (run_id) REFERENCES report_runs (id) ON DELETE CASCADE,
    CONSTRAINT fk_resignation_facts_person
        FOREIGN KEY (person_id) REFERENCES person_identities (id) ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='Run-scoped resignation workflow facts';

CREATE TABLE IF NOT EXISTS release_facts (
    id                       VARCHAR(36)  NOT NULL COMMENT 'Application UUID',
    run_id                   VARCHAR(36)  NOT NULL,
    source_row_no            INT          NOT NULL,
    order_no                 VARCHAR(100) NOT NULL,
    person_id                VARCHAR(36)  NULL,
    employee_no              VARCHAR(50)  NULL COMMENT 'Protected HR display field',
    application_date         DATE         NULL,
    last_working_day         DATE         NULL,
    process_status           VARCHAR(32)  NULL,
    first_visible_date       DATE         NULL,
    row5_classification      VARCHAR(24)  NULL,
    row30_classification     VARCHAR(24)  NULL,
    ocr_confidence           VARCHAR(24)  NULL,
    create_time              DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    create_id                VARCHAR(36)  NULL,
    update_time              DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    update_id                VARCHAR(36)  NULL,
    is_deleted               INT          NOT NULL DEFAULT 0,
    PRIMARY KEY (id),
    UNIQUE KEY uq_release_fact_run_order (run_id, order_no),
    KEY ix_release_facts_run_id (run_id),
    KEY ix_release_facts_person_id (person_id),
    CONSTRAINT fk_release_facts_run
        FOREIGN KEY (run_id) REFERENCES report_runs (id) ON DELETE CASCADE,
    CONSTRAINT fk_release_facts_person
        FOREIGN KEY (person_id) REFERENCES person_identities (id) ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='Run-scoped OA Release facts';

CREATE TABLE IF NOT EXISTS recruitment_snapshots (
    id                                           VARCHAR(36) NOT NULL COMMENT 'Application UUID',
    run_id                                       VARCHAR(36) NOT NULL,
    source_row_no                                INT         NOT NULL,
    report_date                                  DATE        NOT NULL,
    is_total_row                                 BOOLEAN     NOT NULL DEFAULT FALSE,
    previous_month_offer_current_month_onboard   INT         NULL,
    current_month_offer_current_month_onboard    INT         NULL,
    recognized_labels                            TEXT        NULL COMMENT 'Canonical JSON',
    ocr_confidence                               VARCHAR(24) NULL,
    create_time                                  DATETIME    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    create_id                                    VARCHAR(36) NULL,
    update_time                                  DATETIME    NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    update_id                                    VARCHAR(36) NULL,
    is_deleted                                   INT         NOT NULL DEFAULT 0,
    PRIMARY KEY (id),
    UNIQUE KEY uq_recruitment_snapshot_run_row (run_id, source_row_no),
    KEY ix_recruitment_snapshots_run_id (run_id),
    CONSTRAINT fk_recruitment_snapshots_run
        FOREIGN KEY (run_id) REFERENCES report_runs (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='Run-scoped recruitment values and OCR labels';

CREATE TABLE IF NOT EXISTS fact_events (
    id                 VARCHAR(36)  NOT NULL COMMENT 'Application UUID',
    run_id             VARCHAR(36)  NOT NULL,
    event_key          VARCHAR(128) NOT NULL,
    event_type         VARCHAR(32)  NOT NULL,
    person_id          VARCHAR(36)  NULL,
    employment_ref     VARCHAR(36)  NULL,
    source_type        VARCHAR(24)  NOT NULL,
    source_event_ref   VARCHAR(128) NULL,
    effective_date     DATE         NULL,
    first_visible_date DATE         NULL,
    classification     VARCHAR(32)  NULL,
    minimal_payload    TEXT         NULL COMMENT 'Canonical JSON without protected fields',
    create_time        DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    create_id          VARCHAR(36)  NULL,
    update_time        DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    update_id          VARCHAR(36)  NULL,
    is_deleted         INT          NOT NULL DEFAULT 0,
    PRIMARY KEY (id),
    UNIQUE KEY uq_fact_event_run_key (run_id, event_key),
    KEY ix_fact_events_run_id (run_id),
    CONSTRAINT fk_fact_events_run
        FOREIGN KEY (run_id) REFERENCES report_runs (id) ON DELETE CASCADE,
    CONSTRAINT fk_fact_events_person
        FOREIGN KEY (person_id) REFERENCES person_identities (id) ON DELETE RESTRICT,
    CONSTRAINT fk_fact_events_employment
        FOREIGN KEY (employment_ref) REFERENCES employment_facts (id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='Deduplicated canonical HR events';

CREATE TABLE IF NOT EXISTS run_decisions (
    id            VARCHAR(36)  NOT NULL COMMENT 'Application UUID',
    run_id        VARCHAR(36)  NOT NULL,
    report_kind   VARCHAR(16)  NULL COMMENT 'daily/weekly; NULL means shared',
    decision_code VARCHAR(64)  NOT NULL,
    fact_ref      VARCHAR(128) NOT NULL COMMENT 'Opaque fact reference',
    question      TEXT         NOT NULL,
    options       TEXT         NOT NULL COMMENT 'Canonical JSON',
    answer        TEXT         NULL COMMENT 'Canonical JSON',
    status        VARCHAR(24)  NOT NULL,
    decided_at    DATETIME     NULL,
    operator_ref  VARCHAR(100) NULL,
    create_time   DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    create_id     VARCHAR(36)  NULL,
    update_time   DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    update_id     VARCHAR(36)  NULL,
    is_deleted    INT          NOT NULL DEFAULT 0,
    PRIMARY KEY (id),
    KEY ix_run_decisions_run_id (run_id),
    KEY ix_run_decisions_status (status),
    CONSTRAINT fk_run_decisions_run
        FOREIGN KEY (run_id) REFERENCES report_runs (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='Typed human decisions over canonical facts';

CREATE TABLE IF NOT EXISTS run_validations (
    id              VARCHAR(36) NOT NULL COMMENT 'Application UUID',
    run_id          VARCHAR(36) NOT NULL,
    report_kind     VARCHAR(16) NOT NULL COMMENT 'shared/daily/weekly',
    validation_code VARCHAR(64) NOT NULL,
    severity        VARCHAR(16) NOT NULL COMMENT 'BLOCK/REVIEW/INFO',
    outcome         VARCHAR(16) NOT NULL COMMENT 'PASS/FAIL',
    message         TEXT        NOT NULL,
    evidence_refs   TEXT        NOT NULL COMMENT 'Canonical JSON with opaque references',
    create_time     DATETIME    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    create_id       VARCHAR(36) NULL,
    update_time     DATETIME    NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    update_id       VARCHAR(36) NULL,
    is_deleted      INT         NOT NULL DEFAULT 0,
    PRIMARY KEY (id),
    UNIQUE KEY uq_run_validation_code (run_id, report_kind, validation_code),
    KEY ix_run_validations_run_id (run_id),
    CONSTRAINT fk_run_validations_run
        FOREIGN KEY (run_id) REFERENCES report_runs (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='Scoped validation outcomes and redacted evidence';
