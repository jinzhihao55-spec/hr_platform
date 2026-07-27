#!/usr/bin/env bash
set -euo pipefail

: "${MYSQL_HOST:?MYSQL_HOST is required}"
: "${MYSQL_PORT:=3306}"
: "${MYSQL_DATABASE:?MYSQL_DATABASE is required}"
: "${MYSQL_ROOT_PASSWORD:?MYSQL_ROOT_PASSWORD is required}"

if [[ "${MYSQL_DATABASE}" != "ai_hr_reports" ]]; then
  echo "MYSQL_DATABASE must be ai_hr_reports because schema.sql freezes that database name" >&2
  exit 2
fi

client_config="$(mktemp)"
trap 'rm -f "${client_config}"' EXIT
chmod 0600 "${client_config}"
printf '[client]\nhost=%s\nport=%s\nuser=root\npassword=%s\nprotocol=tcp\n' \
  "${MYSQL_HOST}" "${MYSQL_PORT}" "${MYSQL_ROOT_PASSWORD}" > "${client_config}"

remaining="${MIGRATION_WAIT_SECONDS:-120}"
until mysqladmin --defaults-extra-file="${client_config}" ping --silent; do
  if (( remaining <= 0 )); then
    echo "MySQL did not become ready before migration timeout" >&2
    exit 1
  fi
  sleep 2
  remaining=$((remaining - 2))
done

echo "Applying current schema..."
mysql --defaults-extra-file="${client_config}" < /migrations/schema.sql

shopt -s nullglob
for migration in /migrations/migrations/*.sql; do
  echo "Applying $(basename "${migration}")..."
  mysql --defaults-extra-file="${client_config}" "${MYSQL_DATABASE}" < "${migration}"
done

echo "Database schema is current."
