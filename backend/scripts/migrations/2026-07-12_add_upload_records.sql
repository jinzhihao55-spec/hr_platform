-- 2026-07-12：每日输入源上传记录（每日生成门禁的持久化判定依据）
-- 幂等：使用 IF NOT EXISTS，可重复执行。须在 schema.sql 建库之后执行。

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
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COMMENT = '每日各输入源上传记录（门禁判定依据，Redis 仅为展示缓存）';
