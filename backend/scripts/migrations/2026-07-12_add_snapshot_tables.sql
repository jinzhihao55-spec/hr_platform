-- 2026-07-12：人员日快照 + 在岗时长汇总基线（周报窗口末在职 / 链式增量的持久化依据）
-- 适用：已按旧 schema.sql 建库的 MySQL 8.0 环境升级到本分支时执行。
-- 幂等：使用 IF NOT EXISTS，可重复执行。
-- 部署顺序：先执行本脚本建表，再发布应用；否则任何人员表上传都会因缺表失败。
-- 全新环境：开发库可用 `python -m scripts.init_db`（ORM 建表）；生产以 database 仓库 schema.sql 为准，
-- 本脚本内容需同步合入该仓库。

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
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COMMENT = '按报告日保存的人员快照（周报窗口末在职与历史重算）';

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
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COMMENT = '已验收日报中的 8 个 BU 在岗时长汇总基线（无人员明细）';

-- 清理历史上同一周、同一事业部的重复行，再补数据库唯一约束。
-- 重复行来自历史重跑：保留 create_time 最新的一条（平手再按 id 字典序），
-- 不能按 UUID 排序——那等于随机保留，可能把旧一轮的数字留在库里。
-- 注意：本段依赖 weekly_reports 已存在，须在 schema.sql 建库之后执行。
DELETE wr_duplicate
FROM weekly_reports AS wr_duplicate
JOIN weekly_reports AS wr_keep
  ON wr_duplicate.week_start = wr_keep.week_start
 AND wr_duplicate.bu <=> wr_keep.bu
 AND (wr_duplicate.create_time < wr_keep.create_time
      OR (wr_duplicate.create_time = wr_keep.create_time
          AND wr_duplicate.id > wr_keep.id));

-- 按索引列判定：权威 schema 的唯一键叫 uk_week_bu、本迁移建的叫
-- uq_weekly_report_week_bu——只要已存在覆盖 (week_start, bu) 的任一唯一索引
-- 就不再重复创建（按名字判会在 schema 建的库上多建一个等价索引）。
SET @weekly_unique_exists = (
    SELECT COUNT(*)
    FROM (
        SELECT index_name
        FROM information_schema.statistics
        WHERE table_schema = DATABASE()
          AND table_name = 'weekly_reports'
          AND non_unique = 0
        GROUP BY index_name
        HAVING GROUP_CONCAT(column_name ORDER BY seq_in_index) = 'week_start,bu'
    ) AS covering_unique
);
SET @weekly_unique_ddl = IF(
    @weekly_unique_exists = 0,
    'ALTER TABLE weekly_reports ADD UNIQUE KEY uq_weekly_report_week_bu (week_start, bu)',
    'SELECT 1'
);
PREPARE weekly_unique_stmt FROM @weekly_unique_ddl;
EXECUTE weekly_unique_stmt;
DEALLOCATE PREPARE weekly_unique_stmt;
