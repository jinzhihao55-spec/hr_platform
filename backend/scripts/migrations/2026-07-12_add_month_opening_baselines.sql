-- 2026-07-12：HR 显式确认的月初独立基线。
-- 不覆盖上月 daily_reports；跨月首次生成前必须存在该记录及对应模板文件。
-- 幂等：可重复执行。须在 schema.sql 建库后执行。

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
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COMMENT = 'HR 月初独立基线确认记录';
