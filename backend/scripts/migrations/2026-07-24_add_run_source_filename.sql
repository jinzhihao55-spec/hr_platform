-- Existing deployments created before source basenames were shown in the UI.

SET @original_filename_exists = (
    SELECT COUNT(*)
    FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE()
      AND TABLE_NAME = 'run_sources'
      AND COLUMN_NAME = 'original_filename'
);

SET @original_filename_ddl = IF(
    @original_filename_exists > 0,
    'SELECT 1',
    'ALTER TABLE run_sources ADD COLUMN original_filename VARCHAR(255) NULL COMMENT ''Sanitized source basename for operator display'' AFTER original_extension'
);

PREPARE original_filename_stmt FROM @original_filename_ddl;
EXECUTE original_filename_stmt;
DEALLOCATE PREPARE original_filename_stmt;
