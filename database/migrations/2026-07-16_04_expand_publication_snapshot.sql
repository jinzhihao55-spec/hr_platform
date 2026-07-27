-- Existing deployments may contain evidence snapshots larger than MySQL TEXT (64 KiB).

SET @snapshot_type = (
    SELECT DATA_TYPE
    FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE()
      AND TABLE_NAME = 'published_reports'
      AND COLUMN_NAME = 'snapshot_json'
    LIMIT 1
);

SET @snapshot_ddl = IF(
    @snapshot_type = 'longtext',
    'SELECT 1',
    'ALTER TABLE published_reports MODIFY COLUMN snapshot_json LONGTEXT NOT NULL COMMENT ''Canonical preview JSON'''
);

PREPARE snapshot_stmt FROM @snapshot_ddl;
EXECUTE snapshot_stmt;
DEALLOCATE PREPARE snapshot_stmt;
