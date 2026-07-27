-- ============================================
-- AI人事报表智能体 — 数据库建表脚本
-- 数据库: ai_hr_reports | 字符集: utf8mb4 | 引擎: InnoDB
-- 主键策略: CHAR(36) UUID | 软删: is_deleted
-- ============================================

CREATE DATABASE IF NOT EXISTS ai_hr_reports
  DEFAULT CHARACTER SET utf8mb4
  DEFAULT COLLATE utf8mb4_unicode_ci;

USE ai_hr_reports;

-- ============================================
-- 1. projects — 项目表
-- ============================================
CREATE TABLE IF NOT EXISTS projects (
    id              CHAR(36) PRIMARY KEY DEFAULT (UUID()) COMMENT '全局唯一GUID',
    project_code    VARCHAR(20) UNIQUE NOT NULL COMMENT '项目编码',
    project_name    VARCHAR(100) NOT NULL COMMENT '项目名称',
    project_staff   VARCHAR(50) COMMENT '项目人员',
    create_time     DATETIME DEFAULT CURRENT_TIMESTAMP,
    create_id       CHAR(36) COMMENT '创建人ID',
    update_time     DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    update_id       CHAR(36) COMMENT '修改人ID',
    is_deleted      TINYINT DEFAULT 0,
    INDEX idx_project_code (project_code)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='项目表';

-- ============================================
-- 2. employees — 人员主表
-- ============================================
CREATE TABLE IF NOT EXISTS employees (
    id                  CHAR(36) PRIMARY KEY DEFAULT (UUID()) COMMENT '全局唯一GUID',
    employee_no         VARCHAR(20) UNIQUE NOT NULL COMMENT '员工编号/工号',
    name                VARCHAR(50) NOT NULL COMMENT '姓名',
    english_name        VARCHAR(50) COMMENT '英文名',
    alias               VARCHAR(50) COMMENT '别名',
    employee_type       VARCHAR(20) NOT NULL COMMENT '正式员工/实习/外包/顾问',
    status              VARCHAR(20) DEFAULT 'active' COMMENT 'active=在职 resigned=离职 transferred=转签',
    department          VARCHAR(100) COMMENT '部门',
    department_code     VARCHAR(20) COMMENT '部门编码',
    bu                  VARCHAR(50) COMMENT '事业部',
    bu_code             VARCHAR(20) COMMENT '事业部编码',
    position            VARCHAR(50) COMMENT '职位(CN)',
    position_en         VARCHAR(100) COMMENT '职位(EN)',
    job_level           VARCHAR(20) COMMENT '职级',
    report_to           VARCHAR(50) COMMENT '汇报线',
    project_code        VARCHAR(20) COMMENT 'FK → projects.project_code',
    entry_date          DATE COMMENT '入职日期',
    resign_date         DATE COMMENT '离职日期',
    hire_first_visible_date   DATE COMMENT '入职事实首次可见日期(晚到补入今天用)',
    resign_first_visible_date DATE COMMENT '离职事实首次可见日期(晚到补入今天用)',
    contract_start      DATE COMMENT '合同开始日期',
    contract_end        DATE COMMENT '合同结束日期',
    contract_company    VARCHAR(100) COMMENT '签约公司',
    probation_start     DATE COMMENT '试用期开始日期',
    probation_end       DATE COMMENT '试用期结束日期',
    transfer_prev_company VARCHAR(100) COMMENT '转签前单位',
    transfer_prev_contract_start DATE COMMENT '转签前合同开始',
    transfer_prev_contract_end   DATE COMMENT '转签前合同结束',
    intern_contract_start DATE COMMENT '实习期合同开始',
    intern_contract_end   DATE COMMENT '实习期合同结束',
    expected_release_date DATE COMMENT '预计Release日期',
    release_type        VARCHAR(20) COMMENT 'Release类型：主动离职/协议解除/到期不续',
    create_time         DATETIME DEFAULT CURRENT_TIMESTAMP,
    create_id           CHAR(36) COMMENT '创建人ID',
    update_time         DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    update_id           CHAR(36) COMMENT '修改人ID',
    is_deleted          TINYINT DEFAULT 0,
    INDEX idx_status (status),
    INDEX idx_department (department_code),
    INDEX idx_bu (bu_code),
    INDEX idx_entry_date (entry_date),
    INDEX idx_resign_date (resign_date),
    FOREIGN KEY (project_code) REFERENCES projects(project_code)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='人员主表';

-- ============================================
-- 3. employee_resignations — 离职表
-- ============================================
CREATE TABLE IF NOT EXISTS employee_resignations (
    id                  CHAR(36) PRIMARY KEY DEFAULT (UUID()) COMMENT '全局唯一GUID',
    process_no          VARCHAR(50) UNIQUE NOT NULL COMMENT '流程单号',
    node_name           VARCHAR(50) COMMENT '节点名称',
    process_status      VARCHAR(20) COMMENT '流程状态：进行中/已完结/已驳回',
    employee_no         VARCHAR(20) NOT NULL COMMENT 'FK → employees.employee_no（其余人员字段JOIN获取）',
    resign_date         DATE COMMENT '离职日期(LWD)',
    resign_type         VARCHAR(20) COMMENT '离职方式：主动离职/协商解除/合同到期/辞退',
    resign_reason       VARCHAR(200) COMMENT '离职原因',
    release_notice_date DATE COMMENT '项目释放通知时间',
    first_visible_date  DATE COMMENT '首次可见日期',
    create_time         DATETIME DEFAULT CURRENT_TIMESTAMP,
    create_id           CHAR(36) COMMENT '创建人ID',
    update_time         DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    update_id           CHAR(36) COMMENT '修改人ID',
    is_deleted          TINYINT DEFAULT 0,
    FOREIGN KEY (employee_no) REFERENCES employees(employee_no),
    INDEX idx_process_status (process_status),
    INDEX idx_resign_date (resign_date),
    INDEX idx_employee_no (employee_no)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='离职人员报表';

-- ============================================
-- 4. oa_protocols — OA协议签署/离职审批表
-- ============================================
CREATE TABLE IF NOT EXISTS oa_protocols (
    id                  CHAR(36) PRIMARY KEY DEFAULT (UUID()) COMMENT '全局唯一GUID',
    task_no             VARCHAR(50) UNIQUE NOT NULL COMMENT '任务号',
    order_no            VARCHAR(50) UNIQUE NOT NULL COMMENT '单号',
    title               VARCHAR(200) COMMENT '流程标题',
    initiator           VARCHAR(50) COMMENT '发起人',
    initiator_department VARCHAR(50) COMMENT '发起人部门',
    initiate_time       DATETIME COMMENT '发起时间',
    current_status      VARCHAR(20) COMMENT '当前状态：审批中/已通过/已驳回',
    process_type        VARCHAR(20) COMMENT '流程类型：离职审批/协议解除/转签',
    related_employee    VARCHAR(20) COMMENT '关联员工编号',
    related_name        VARCHAR(50) COMMENT '关联员工姓名',
    employee_flag       VARCHAR(30) COMMENT '员工标识',
    first_visible_date  DATE COMMENT '首次可见日期',
    row5_flag           VARCHAR(10) COMMENT 'Row5标志 是/否',
    row30_flag          VARCHAR(10) COMMENT 'Row30标志 是/否',
    remarks             TEXT COMMENT '备注字段',
    create_time         DATETIME DEFAULT CURRENT_TIMESTAMP,
    create_id           CHAR(36) COMMENT '创建人ID',
    update_time         DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    update_id           CHAR(36) COMMENT '修改人ID',
    is_deleted          TINYINT DEFAULT 0,
    INDEX idx_status (current_status),
    INDEX idx_employee (related_employee),
    INDEX idx_visible_date (first_visible_date),
    FOREIGN KEY (related_employee) REFERENCES employees(employee_no)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='OA协议签署/离职审批表';

-- ============================================
-- 5. recruitment_pipeline — 招聘表
-- ============================================
CREATE TABLE IF NOT EXISTS recruitment_pipeline (
    id                      CHAR(36) PRIMARY KEY DEFAULT (UUID()) COMMENT '全局唯一GUID',
    recruiter               VARCHAR(50) COMMENT '招聘专员/模板字段',
    target_position         VARCHAR(50) COMMENT '目标职位',
    month_offers            INT DEFAULT 0 COMMENT '本月发offer数',
    month_offer_date        DATE COMMENT '本月最后一个offer日期的offer数',
    month_offer_prev_cum    INT DEFAULT 0 COMMENT '本月最后offer日期之前+之前offer累积数',
    onboard_m              INT DEFAULT 0 COMMENT '本月内入职数(确定入职)',
    onboard_m_headhunter   INT DEFAULT 0 COMMENT '本月内入职数(猎头/RPO入职+市场渠道)',
    expected_onboard_m     INT DEFAULT 0 COMMENT '本月待入职数(本月offer本月即入职)',
    expected_onboard_m_prev INT DEFAULT 0 COMMENT '本月待入职数(上月offer本月入职)',
    confirmed_onboard_m    INT DEFAULT 0 COMMENT '本月确定入职数(非招聘渠道之外)',
    remarks                 TEXT COMMENT '备注',
    report_date             DATE COMMENT '数据日期',
    create_time             DATETIME DEFAULT CURRENT_TIMESTAMP,
    create_id               CHAR(36) COMMENT '创建人ID',
    update_time             DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    update_id               CHAR(36) COMMENT '修改人ID',
    is_deleted              TINYINT DEFAULT 0,
    INDEX idx_report_date (report_date),
    INDEX idx_recruiter (recruiter)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='招聘漏斗表';

-- ============================================
-- 6. daily_reports — 员工数增减日报
-- ============================================
CREATE TABLE IF NOT EXISTS daily_reports (
    id                          CHAR(36) PRIMARY KEY DEFAULT (UUID()) COMMENT '全局唯一GUID',
    report_date                 DATE NOT NULL COMMENT '报告日期',
    daily_onboard               INT DEFAULT 0 COMMENT '当日入职',
    daily_resign                INT DEFAULT 0 COMMENT '当日离职',
    daily_employee_change       INT DEFAULT 0 COMMENT '当日净增减人数',
    mtd_onboard                 INT DEFAULT 0 COMMENT 'MTD入职',
    mtd_resign                  INT DEFAULT 0 COMMENT 'MTD离职',
    mtd_transfer                INT DEFAULT 0 COMMENT 'MTD转正',
    mtd_project_change          INT DEFAULT 0 COMMENT 'MTD微调项目(调入/调出微项目)',
    mtd_employee_change         INT DEFAULT 0 COMMENT 'MTD净增减人数',
    ytd_onboard                 INT DEFAULT 0 COMMENT 'YTD入职',
    ytd_resign                  INT DEFAULT 0 COMMENT 'YTD离职',
    ytd_transfer                INT DEFAULT 0 COMMENT 'YTD转正',
    ytd_project_change          INT DEFAULT 0 COMMENT 'YTD微调项目(调入/调出微项目)',
    ytd_employee_change         INT DEFAULT 0 COMMENT 'YTD净增减人数',
    predicted_resign_recruitment INT DEFAULT 0 COMMENT '预测离职人数-招聘提供',
    predicted_resign            INT DEFAULT 0 COMMENT '预测离职人数(实际)',
    predicted_onboard           INT DEFAULT 0 COMMENT '预测入职人数',
    release_today               INT DEFAULT 0 COMMENT '当日Release',
    release_cum                 INT DEFAULT 0 COMMENT '累计Release',
    release_pending_total       INT DEFAULT 0 COMMENT '预计Release(待Release)',
    expected_resign_cum         INT DEFAULT 0 COMMENT '预计离职累计(已release+待release)',
    expected_onboard_offer      INT DEFAULT 0 COMMENT '预计入职(本月offer预计入职)',
    expected_onboard_prev       INT DEFAULT 0 COMMENT '预计入职(上月offer预计入职)',
    bi_ytd_resign_rate          VARCHAR(20) COMMENT 'BI口径YTD离职率(mtd)',
    create_time                 DATETIME DEFAULT CURRENT_TIMESTAMP,
    create_id                   CHAR(36) COMMENT '创建人ID',
    UNIQUE KEY uk_report_date (report_date),
    INDEX idx_report_date (report_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='员工数增减日报';

-- ============================================
-- 7. weekly_reports — 员工数增减周报
-- ============================================
CREATE TABLE IF NOT EXISTS weekly_reports (
    id                  CHAR(36) PRIMARY KEY DEFAULT (UUID()) COMMENT '全局唯一GUID',
    week_start          DATE NOT NULL COMMENT '周开始日期',
    week_end            DATE NOT NULL COMMENT '周结束日期',
    bu                  VARCHAR(50) COMMENT '事业部',
    headcount_active    INT DEFAULT 0 COMMENT '在职人数',
    headcount_formal    INT DEFAULT 0 COMMENT '正式员工',
    headcount_intern    INT DEFAULT 0 COMMENT '实习生',
    headcount_outsource INT DEFAULT 0 COMMENT '外包人员',
    resigned_formal     INT DEFAULT 0 COMMENT '本周离职-正式员工',
    onboard_formal      INT DEFAULT 0 COMMENT '本周入职-正式员工',
    create_time         DATETIME DEFAULT CURRENT_TIMESTAMP,
    create_id           CHAR(36) COMMENT '创建人ID',
    UNIQUE KEY uk_week_bu (week_start, bu),
    INDEX idx_week (week_start),
    INDEX idx_bu (bu)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='员工数增减周报';

-- ============================================
-- 8. monthly_reports — 员工数增减月报
-- ============================================
CREATE TABLE IF NOT EXISTS monthly_reports (
    id                  CHAR(36) PRIMARY KEY DEFAULT (UUID()) COMMENT '全局唯一GUID',
    report_month        DATE NOT NULL COMMENT '报告月份(取每月1日)',
    bu                  VARCHAR(50) COMMENT '事业部',
    headcount_start     INT DEFAULT 0 COMMENT '月初在职人数',
    headcount_end       INT DEFAULT 0 COMMENT '月末在职人数',
    onboard_count       INT DEFAULT 0 COMMENT '本月入职人数',
    resign_count        INT DEFAULT 0 COMMENT '本月离职人数',
    transfer_count      INT DEFAULT 0 COMMENT '本月转正人数',
    project_name        VARCHAR(100) COMMENT '项目名称',
    project_headcount   INT DEFAULT 0 COMMENT '项目月末人数',
    monthly_net         INT DEFAULT 0 COMMENT '本月净增',
    ytd_onboard         INT DEFAULT 0 COMMENT 'YTD入职',
    ytd_resign          INT DEFAULT 0 COMMENT 'YTD离职',
    resigned_rate       DECIMAL(5,2) COMMENT '离职率(%)',
    create_time         DATETIME DEFAULT CURRENT_TIMESTAMP,
    create_id           CHAR(36) COMMENT '创建人ID',
    UNIQUE KEY uk_month_bu_project (report_month, bu, project_name),
    INDEX idx_month (report_month),
    INDEX idx_bu (bu)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='员工数增减月报';

-- ============================================
-- chat_messages — 对话历史表
-- ============================================
CREATE TABLE IF NOT EXISTS chat_messages (
    id                  CHAR(36) PRIMARY KEY DEFAULT (UUID()) COMMENT '全局唯一GUID',
    session_id          VARCHAR(36) NOT NULL COMMENT '会话ID（前端生成，同日同组对话共享）',
    report_date         DATE COMMENT '关联报告日期',
    role                VARCHAR(10) NOT NULL COMMENT 'user | assistant',
    content             TEXT NOT NULL COMMENT '消息正文',
    action              VARCHAR(50) COMMENT '触发动作：generate|answer_clarification|seed_baseline|info|error',
    clarification_id    VARCHAR(50) COMMENT '关联澄清ID（Redis hr:clarify:item:{id}）',
    metadata_json       TEXT COMMENT 'JSON附加数据：文件路径/DB更新字段/错误详情',
    create_time         DATETIME DEFAULT CURRENT_TIMESTAMP,
    create_id           CHAR(36) COMMENT '创建人ID',
    update_time         DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    update_id           CHAR(36) COMMENT '修改人ID',
    is_deleted          TINYINT DEFAULT 0,
    INDEX idx_session (session_id),
    INDEX idx_report_date (report_date),
    INDEX idx_role (role)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='对话历史表';

-- ============================================
-- clarifications — 澄清事项表（MySQL永久存储）
-- ============================================
CREATE TABLE IF NOT EXISTS clarifications (
    id              VARCHAR(12) PRIMARY KEY COMMENT '12位hex，与Redis item_id一致',
    report_date     DATE NOT NULL COMMENT '关联报告日期',
    code            VARCHAR(50) NOT NULL COMMENT '澄清类型：baseline_missing/lwd_pending/input_missing等',
    message         TEXT NOT NULL COMMENT '展示给用户的问题全文',
    ref             VARCHAR(100) COMMENT '关联业务对象（单号/工号等）',
    options_json    TEXT COMMENT 'JSON: 建议答复选项列表',
    status          VARCHAR(20) DEFAULT 'pending' COMMENT 'pending | answered',
    answer          TEXT COMMENT '用户答复原文',
    answered_at     DATETIME COMMENT '答复时间戳',
    create_time     DATETIME DEFAULT CURRENT_TIMESTAMP,
    create_id       CHAR(36),
    update_time     DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    update_id       CHAR(36),
    is_deleted      TINYINT DEFAULT 0,
    INDEX idx_report_date (report_date),
    INDEX idx_code (code),
    INDEX idx_status (status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='澄清事项表（永久存储，与Redis双写）';

-- ============================================
-- 10. employee_snapshots — 报告日人员快照（周报窗口末在职与历史重算）
-- ============================================
CREATE TABLE IF NOT EXISTS employee_snapshots (
    id               VARCHAR(36)  NOT NULL COMMENT '应用层生成的 UUID 主键',
    report_date      DATE         NOT NULL COMMENT '报告日（上传人员表对应的快照日）',
    employee_no      VARCHAR(20)  NOT NULL COMMENT '工号',
    employee_type    VARCHAR(20)  NOT NULL COMMENT '员工类型',
    status           VARCHAR(20)  NULL COMMENT 'active/resigned/transferred',
    business_unit    VARCHAR(50)  NULL COMMENT '事业部名称',
    business_unit_no VARCHAR(20)  NULL COMMENT '事业部编号',
    project_code     VARCHAR(100) NULL COMMENT '项目编号（缺失时回退项目名称）',
    project_name     VARCHAR(100) NULL COMMENT '项目名称',
    entry_date       DATE         NULL COMMENT '入职日期',
    resign_date      DATE         NULL COMMENT '离职日期',
    create_time      DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    create_id        VARCHAR(36)  NULL,
    update_time      DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    update_id        VARCHAR(36)  NULL,
    is_deleted       INT          NOT NULL DEFAULT 0 COMMENT '软删：0=正常 1=删除',
    PRIMARY KEY (id),
    UNIQUE KEY uq_employee_snapshot_day_no (report_date, employee_no),
    KEY ix_employee_snapshots_report_date (report_date),
    KEY ix_employee_snapshots_employee_no (employee_no)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='按报告日保存的人员快照（周报窗口末在职与历史重算）';

-- ============================================
-- 11. tenure_snapshot_metrics — 已验收日报的在岗时长汇总基线
-- ============================================
CREATE TABLE IF NOT EXISTS tenure_snapshot_metrics (
    id               VARCHAR(36)   NOT NULL COMMENT '应用层生成的 UUID 主键',
    snapshot_date    DATE          NOT NULL COMMENT '已验收日报的报告日',
    slot             VARCHAR(20)   NOT NULL COMMENT '在岗时长槽位（BU_A..BU_H）',
    business_unit    VARCHAR(50)   NOT NULL COMMENT '事业部标签（来自定稿在岗时长 sheet）',
    ytd_leavers      INT           NOT NULL DEFAULT 0 COMMENT 'YTD 离职人数',
    avg_tenure_years DECIMAL(8, 2) NULL COMMENT '平均在职年限（可空）',
    PRIMARY KEY (id),
    UNIQUE KEY uq_tenure_snapshot_slot (snapshot_date, slot),
    KEY ix_tenure_snapshot_metrics_snapshot_date (snapshot_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='已验收日报中的 8 个 BU 在岗时长汇总基线（无人员明细）';

-- ============================================
-- 12. source_upload_records — 每日输入源上传记录（生成门禁判定依据）
-- ============================================
CREATE TABLE IF NOT EXISTS source_upload_records (
    id            VARCHAR(36) NOT NULL COMMENT '应用层生成的 UUID 主键',
    report_date   DATE        NOT NULL COMMENT '报告日',
    source        VARCHAR(20) NOT NULL COMMENT 'employees/resignations/agreements/recruitment',
    action        VARCHAR(10) NOT NULL COMMENT 'updated=当日上传 / reused=沿用库内',
    rows_upserted INT         NULL COMMENT '本次入库行数（reused 时为空）',
    create_time   DATETIME    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    create_id     VARCHAR(36) NULL,
    update_time   DATETIME    NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    update_id     VARCHAR(36) NULL,
    is_deleted    INT         NOT NULL DEFAULT 0 COMMENT '软删：0=正常 1=删除',
    PRIMARY KEY (id),
    UNIQUE KEY uq_source_upload_day (report_date, source),
    KEY ix_source_upload_records_report_date (report_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='每日各输入源上传记录（门禁判定依据，Redis 仅为展示缓存）';

-- ============================================
-- 13. month_opening_baselines — HR 显式确认的月初独立基线
-- ============================================
CREATE TABLE IF NOT EXISTS month_opening_baselines (
    id                  VARCHAR(36)  NOT NULL COMMENT '应用层 UUID',
    report_month        DATE         NOT NULL COMMENT '目标月份（固定该月 1 日）',
    baseline_date       DATE         NOT NULL COMMENT 'HR 确认的基线日期',
    source_type         VARCHAR(20)  NOT NULL COMMENT 'carry_forward/uploaded',
    baseline_rows_json  TEXT         NOT NULL COMMENT 'Sheet1 B 列数值行 JSON',
    tenure_rows_json    TEXT         NOT NULL COMMENT '在岗时长 8 BU 基线 JSON',
    template_sha256     VARCHAR(64)  NOT NULL COMMENT '月初模板 SHA-256',
    confirmed_by        VARCHAR(100) NOT NULL COMMENT 'HR 确认人',
    create_time         DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    create_id           VARCHAR(36)  NULL,
    update_time         DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    update_id           VARCHAR(36)  NULL,
    is_deleted          INT          NOT NULL DEFAULT 0 COMMENT '软删：0=正常 1=删除',
    PRIMARY KEY (id),
    UNIQUE KEY uq_month_opening_report_month (report_month),
    KEY ix_month_opening_baselines_report_month (report_month)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='HR 月初独立基线确认记录';

-- ============================================
-- 14. report_runs — immutable input and baseline attempts
-- ============================================
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

-- ============================================
-- 15. run_sources — per-Run source metadata, no raw files
-- ============================================
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
    original_extension VARCHAR(16)  NULL COMMENT 'Extension only; no source filename',
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

-- ============================================
-- 16. run_report_targets — independent daily and weekly lifecycle
-- ============================================
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

-- ============================================
-- 17-24. run-scoped canonical facts, events, decisions, and validations
-- ============================================

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

-- ============================================
-- 25. published_reports — immutable formal report versions
-- ============================================
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

-- ============================================
-- 26. report_artifacts — protected formal report files
-- ============================================
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

-- ============================================
-- 27. publication_attempts — recoverable filesystem moves
-- ============================================
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
